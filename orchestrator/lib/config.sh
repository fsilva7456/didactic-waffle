# shellcheck shell=bash
# Bootstrap: locate the repo, load config, set up state dirs.
# Every entrypoint sources this file first.

set -Eeuo pipefail

# macOS ships bash 3.2 (2007) as /bin/bash and it cannot run this code —
# associative arrays alone are bash 4. Fail with an instruction rather than a
# hundred lines of syntax errors.
if (( BASH_VERSINFO[0] < 4 )); then
  cat >&2 <<'EOF'
This pipeline requires bash 4 or newer; you are running bash 3.
On macOS:  brew install bash
Then make sure Homebrew's bin directory precedes /usr/bin in PATH.
The scripts use `#!/usr/bin/env bash`, so no shebang edits are needed.
EOF
  exit 1
fi

PIPELINE_LIB_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PIPELINE_HOME="$(cd "$PIPELINE_LIB_DIR/.." && pwd)"
export PIPELINE_LIB_DIR PIPELINE_HOME

# Repo root is wherever the orchestrator is checked out under.
if PIPELINE_REPO_ROOT="$(git -C "$PIPELINE_HOME" rev-parse --show-toplevel 2>/dev/null)"; then
  export PIPELINE_REPO_ROOT
else
  echo "orchestrator must live inside a git repository" >&2
  exit 1
fi

# Config: repo default, then a gitignored local override.
# shellcheck source=/dev/null
[[ -f "$PIPELINE_REPO_ROOT/pipeline.config.sh" ]] && source "$PIPELINE_REPO_ROOT/pipeline.config.sh"
# shellcheck source=/dev/null
[[ -f "$PIPELINE_REPO_ROOT/pipeline.config.local.sh" ]] && source "$PIPELINE_REPO_ROOT/pipeline.config.local.sh"

# Agents, validation gates and hooks all run as child processes and need the
# configuration. Export the whole PIPELINE_* namespace rather than maintaining
# a hand-written list that drifts.
for _v in $(compgen -v PIPELINE_); do export "${_v?}"; done
unset _v

PIPELINE_STATE_ABS="$PIPELINE_REPO_ROOT/$PIPELINE_STATE_DIR"
mkdir -p "$PIPELINE_STATE_ABS"/{runs,reports,tasks,locks}
export PIPELINE_STATE_ABS

: "${PIPELINE_RUN_ID:=$(date -u +%Y%m%dT%H%M%SZ)-$$}"
export PIPELINE_RUN_ID
export PIPELINE_RUN_LOG="$PIPELINE_STATE_ABS/runs/$PIPELINE_RUN_ID.log"
export PIPELINE_EVENT_LOG="$PIPELINE_STATE_ABS/runs/$PIPELINE_RUN_ID.jsonl"
: >"$PIPELINE_RUN_LOG"
: >"$PIPELINE_EVENT_LOG"

# shellcheck source=log.sh
source "$PIPELINE_LIB_DIR/log.sh"

need_cmd() {
  command -v "$1" >/dev/null 2>&1 || die "required command not found: $1${2:+ ($2)}"
}

# Serialise a critical section across concurrent orchestrator actions.
# Usage: with_lock <name> <command...>
#
# mkdir rather than flock: flock is util-linux and absent on macOS, while
# mkdir is atomic everywhere. The pid file lets a lock left behind by a killed
# orchestrator be reclaimed instead of wedging every later run.
with_lock() {
  local name="$1"; shift
  local lockdir="$PIPELINE_STATE_ABS/locks/$name.lock.d"
  local waited=0 owner
  local limit="${PIPELINE_LOCK_TIMEOUT:-300}"

  until mkdir "$lockdir" 2>/dev/null; do
    owner=$(cat "$lockdir/pid" 2>/dev/null || true)
    if [[ -n "$owner" ]] && ! kill -0 "$owner" 2>/dev/null; then
      log_warn "reclaiming stale '$name' lock from dead pid $owner"
      rm -rf "$lockdir"
      continue
    fi
    sleep 0.2
    waited=$(( waited + 1 ))
    if (( waited > limit * 5 )); then
      log_error "timed out after ${limit}s waiting for the '$name' lock"
      return 1
    fi
  done

  printf '%s' "$$" >"$lockdir/pid"
  local rc=0
  "$@" || rc=$?
  rm -rf "$lockdir"
  return $rc
}

# GNU coreutils `timeout` is not present on a stock macOS; Homebrew's coreutils
# installs it as `gtimeout`. Fall back to a watchdog when neither exists so the
# pipeline degrades rather than failing outright.
if command -v timeout >/dev/null 2>&1; then
  PIPELINE_TIMEOUT_BIN=timeout
elif command -v gtimeout >/dev/null 2>&1; then
  PIPELINE_TIMEOUT_BIN=gtimeout
else
  PIPELINE_TIMEOUT_BIN=""
fi
export PIPELINE_TIMEOUT_BIN

run_with_timeout() {
  local secs="$1"; shift
  if [[ -n "$PIPELINE_TIMEOUT_BIN" ]]; then
    "$PIPELINE_TIMEOUT_BIN" "$secs" "$@"
    return $?
  fi
  # Watchdog fallback. Exits 143 (SIGTERM) on expiry rather than coreutils'
  # 124 — still non-zero, which is all the callers test for.
  "$@" &
  local cmd_pid=$! rc=0
  ( sleep "$secs"; kill -TERM "$cmd_pid" 2>/dev/null ) &
  local watch_pid=$!
  wait "$cmd_pid" 2>/dev/null || rc=$?
  kill "$watch_pid" 2>/dev/null || true
  wait "$watch_pid" 2>/dev/null || true
  return $rc
}
