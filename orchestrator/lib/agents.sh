# shellcheck shell=bash
# Agent backend adapter.
#
# The swarm loop only ever calls the five agent_* verbs at the bottom of this
# file. Which implementation they dispatch to is decided by
# PIPELINE_AGENT_MODE (herdr | headless | mock), so the loop itself never
# learns anything about terminal multiplexers or process management.

HERDR_BIN="${HERDR_BIN:-herdr}"

_agent_pidfile() { printf '%s/locks/%s.pid' "$PIPELINE_STATE_ABS" "$1"; }
_agent_logfile() { printf '%s/runs/%s.agent.log' "$PIPELINE_STATE_ABS" "$1"; }

# --- herdr -----------------------------------------------------------------
# Panes are observable: you can attach and watch an implementer work, which is
# the whole reason for preferring this backend during interactive runs.

_herdr_spawn() {
  local name="$1" cwd="$2" prompt_file="$3"
  local -a cmd
  # shellcheck disable=SC2206  # deliberate word-splitting of a flag string
  cmd=("$PIPELINE_AGENT_CMD" ${PIPELINE_AGENT_ARGS})

  # --no-focus keeps five spawning agents from stealing the terminal, but it
  # is not accepted by every herdr version. Fall back rather than fail the
  # bead over a cosmetic flag.
  if ! "$HERDR_BIN" agent start "$name" --cwd "$cwd" \
         --split "$PIPELINE_HERDR_SPLIT" --no-focus \
         -- "${cmd[@]}" >/dev/null 2>&1; then
    log_debug "herdr agent start rejected --no-focus, retrying without it"
    "$HERDR_BIN" agent start "$name" --cwd "$cwd" \
      --split "$PIPELINE_HERDR_SPLIT" \
      -- "${cmd[@]}" >/dev/null 2>&1 \
      || { log_error "herdr agent start failed for $name"; return 1; }
  fi

  # The pane needs to reach a prompt before it will accept input. Poll rather
  # than sleeping a fixed amount: cold starts vary by an order of magnitude.
  local waited=0
  while (( waited < 60 )); do
    case "$(_herdr_status "$name")" in
      idle|working) break ;;
    esac
    sleep 2; waited=$((waited + 2))
  done

  _herdr_send "$name" "$(cat "$prompt_file")"
}

_herdr_send() {
  local name="$1" text="$2"
  "$HERDR_BIN" agent send "$name" "$text" >/dev/null 2>&1 \
    || { log_error "herdr agent send failed for $name"; return 1; }
}

# herdr reports idle | working | blocked | done | unknown. `done` means the
# agent process exited; `idle` means it is alive and waiting for input. Both
# mean "no longer working", which is all the swarm cares about.
_herdr_status() {
  local name="$1" out
  out=$("$HERDR_BIN" agent list --json 2>/dev/null) || { echo unknown; return; }
  jq -r --arg n "$name" '
    (if type=="array" then . else (.result.agents // .agents // .data // []) end)
    | map(select((.name // .id // "") == $n))
    | if length == 0 then "missing" else (.[0].status // .[0].state // "unknown") end
  ' <<<"$out" 2>/dev/null || echo unknown
}

_herdr_read() {
  local name="$1" lines="${2:-80}"
  "$HERDR_BIN" agent read "$name" --source recent --lines "$lines" 2>/dev/null || true
}

_herdr_stop() {
  local name="$1"
  "$HERDR_BIN" agent stop "$name" >/dev/null 2>&1 || true
}

# --- headless --------------------------------------------------------------
# `claude -p` in a background process. No multiplexer, so this is the backend
# for CI and for anyone who does not run herdr.

_headless_spawn() {
  local name="$1" cwd="$2" prompt_file="$3"
  local log pid_file
  log=$(_agent_logfile "$name"); pid_file=$(_agent_pidfile "$name")
  # Remembered so feedback can be replayed with its original task attached.
  cp "$prompt_file" "$PIPELINE_STATE_ABS/locks/$name.prompt" 2>/dev/null || true
  # shellcheck disable=SC2206
  local -a args=(${PIPELINE_AGENT_ARGS})
  (
    cd "$cwd" || exit 1
    nohup "$PIPELINE_AGENT_CMD" "${args[@]}" -p "$(cat "$prompt_file")" \
      >"$log" 2>&1 &
    echo $! >"$pid_file"
  )
  [[ -s "$pid_file" ]] || { log_error "headless spawn failed for $name"; return 1; }
}

# A headless agent has no input channel once started, so feedback means a
# fresh process. It gets the original task again along with the feedback —
# a bare "fix these errors" to an agent with no memory of the bead is useless.
_headless_send() {
  local name="$1" text="$2" cwd original tmp rc=0
  cwd=$(cat "$PIPELINE_STATE_ABS/locks/$name.cwd" 2>/dev/null) || return 1
  original="$PIPELINE_STATE_ABS/locks/$name.prompt"
  tmp=$(mktemp)
  {
    [[ -f "$original" ]] && { cat "$original"; printf '\n\n---\n\n'; }
    printf '## Feedback on your previous attempt\n\n%s\n' "$text"
  } >"$tmp"
  _headless_spawn "$name" "$cwd" "$tmp" || rc=$?
  rm -f "$tmp"
  return $rc
}

_headless_status() {
  local pid_file pid
  pid_file=$(_agent_pidfile "$1")
  [[ -f "$pid_file" ]] || { echo missing; return; }
  pid=$(cat "$pid_file")
  if kill -0 "$pid" 2>/dev/null; then echo working; else echo done; fi
}

_headless_read() {
  local log; log=$(_agent_logfile "$1")
  [[ -f "$log" ]] && tail -n "${2:-80}" "$log" || true
}

_headless_stop() {
  local pid_file pid
  pid_file=$(_agent_pidfile "$1")
  [[ -f "$pid_file" ]] || return 0
  pid=$(cat "$pid_file")
  kill "$pid" 2>/dev/null || true
  rm -f "$pid_file"
}

# --- mock ------------------------------------------------------------------
# A fake implementer used by the test suite. It performs the same contract a
# real one does — touch a file, update docs, write a report — so the swarm
# loop can be exercised without an LLM in the way.

_mock_spawn() {
  local name="$1" cwd="$2" prompt_file="$3"
  local log pid_file bead
  log=$(_agent_logfile "$name"); pid_file=$(_agent_pidfile "$name")
  bead="${name#bead-}"
  (
    "$PIPELINE_HOME/lib/mock_agent.sh" "$cwd" "$bead" "$prompt_file" >"$log" 2>&1 &
    echo $! >"$pid_file"
  )
}

_mock_send()   { _mock_spawn "$1" "$(cat "$PIPELINE_STATE_ABS/locks/$1.cwd")" /dev/null; }
_mock_status() { _headless_status "$@"; }
_mock_read()   { _headless_read "$@"; }
_mock_stop()   { _headless_stop "$@"; }

# --- dispatch --------------------------------------------------------------

agent_spawn() {
  local name="$1" cwd="$2" prompt_file="$3"
  printf '%s' "$cwd" >"$PIPELINE_STATE_ABS/locks/$name.cwd"
  log_info "spawning agent $name in $cwd (mode=$PIPELINE_AGENT_MODE)"
  "_${PIPELINE_AGENT_MODE}_spawn" "$name" "$cwd" "$prompt_file"
}

agent_send()   { "_${PIPELINE_AGENT_MODE}_send"   "$@"; }
agent_read()   { "_${PIPELINE_AGENT_MODE}_read"   "$@"; }
agent_stop()   { "_${PIPELINE_AGENT_MODE}_stop"   "$@"; rm -f "$PIPELINE_STATE_ABS/locks/$1.cwd"; }
agent_status() { "_${PIPELINE_AGENT_MODE}_status" "$@"; }

# Spawn a one-shot agent and block until it produces `expect_file`.
# Used by the review and decomposition phases, which are single-agent steps
# rather than swarm work. Returns 1 on timeout, 2 if the agent died first.
agent_run_until_file() {
  local name="$1" cwd="$2" prompt_file="$3" expect_file="$4" timeout="${5:-1800}"
  rm -f "$expect_file"
  agent_spawn "$name" "$cwd" "$prompt_file" || return 2

  local waited=0 settled_for=0
  while (( waited < timeout )); do
    [[ -f "$expect_file" ]] && { agent_stop "$name"; return 0; }
    if agent_settled "$name"; then
      # Grace period: the file may still be mid-write as the agent exits.
      settled_for=$(( settled_for + 5 ))
      if (( settled_for >= 15 )); then
        [[ -f "$expect_file" ]] && { agent_stop "$name"; return 0; }
        log_error "$name settled without producing $expect_file"
        agent_read "$name" 40 | sed 's/^/    | /' >&2
        agent_stop "$name"; return 2
      fi
    else
      settled_for=0
    fi
    sleep 5; waited=$(( waited + 5 ))
  done

  log_error "$name timed out after ${timeout}s"
  agent_stop "$name"
  return 1
}

# True when the agent is no longer producing work and the orchestrator should
# look for its completion report.
agent_settled() {
  case "$(agent_status "$1")" in
    idle|done|missing|unknown) return 0 ;;
    *) return 1 ;;
  esac
}
