#!/usr/bin/env bash
# Phase 5: the execution swarm.
#
# Keeps up to PIPELINE_MAX_AGENTS implementers alive, one bead each, until the
# bead graph is drained. Every cycle: reap finished agents (validate, merge,
# close), then dispatch new ones into the free slots.
#
#   swarm.sh              run until the graph is drained
#   swarm.sh --once       one dispatch/reap cycle, then exit
#   swarm.sh --dry-run    show what would be dispatched, change nothing

set -Eeuo pipefail
source "$(cd "$(dirname "${BASH_SOURCE[0]}")/../lib" && pwd)/config.sh"
source "$PIPELINE_LIB_DIR/beads.sh"
source "$PIPELINE_LIB_DIR/agents.sh"
source "$PIPELINE_LIB_DIR/worktree.sh"
source "$PIPELINE_LIB_DIR/validate.sh"

ONCE=0; DRY_RUN=0
while (( $# )); do
  case "$1" in
    --once)    ONCE=1 ;;
    --dry-run) DRY_RUN=1 ;;
    --max)     shift; PIPELINE_MAX_AGENTS="$1" ;;
    -h|--help) sed -n '2,12p' "$0"; exit 0 ;;
    *) die "unknown flag: $1" ;;
  esac
  shift
done

declare -A ACTIVE=()      # bead -> epoch seconds when dispatched
declare -A ATTEMPTS=()    # bead -> validation attempts so far
LANDED=0; BLOCKED=0

ARCH_DOC="${PIPELINE_ARCH_DOC:-$PIPELINE_DOCS_DIR/architecture/current.md}"

# --- dispatch --------------------------------------------------------------

dispatch_bead() {
  local bead="$1" path prompt name
  name="bead-$bead"

  if ! bd_claim "$bead"; then
    log_debug "$bead: claim lost to another orchestrator, skipping"
    return 1
  fi

  path=$(wt_create "$bead") || { bd_block "$bead" "worktree creation failed"; return 1; }
  rm -f "$(report_path "$bead")"

  prompt="$PIPELINE_STATE_ABS/tasks/$bead.prompt.md"
  render_prompt "$bead" "$path" >"$prompt"

  if ! agent_spawn "$name" "$path" "$prompt"; then
    bd_block "$bead" "agent spawn failed"
    wt_remove "$bead"
    return 1
  fi

  ACTIVE["$bead"]=$(date +%s)
  ATTEMPTS["$bead"]=${ATTEMPTS["$bead"]:-0}
  bd_set_status "$bead" in_progress
  log_info "$bead: dispatched to $name"
  log_event dispatch "$bead" "$name"
}

render_prompt() {
  local bead="$1" path="$2" tmpl brief
  tmpl=$(cat "$PIPELINE_HOME/prompts/implementer.md")
  brief=$(bd_brief "$bead")

  # Substitute with awk-free parameter expansion so that briefs containing
  # sed metacharacters (regexes, slashes, backslashes) survive intact.
  tmpl=${tmpl//'{{BEAD_ID}}'/$bead}
  tmpl=${tmpl//'{{WORKTREE}}'/$path}
  tmpl=${tmpl//'{{BRANCH}}'/$(wt_branch "$bead")}
  tmpl=${tmpl//'{{REPORT_FILE}}'/$(report_path "$bead")}
  tmpl=${tmpl//'{{ARCH_DOC}}'/$PIPELINE_REPO_ROOT/$ARCH_DOC}
  tmpl=${tmpl//'{{TEST_CMD}}'/${PIPELINE_TEST_CMD:-(no test command configured)}}
  tmpl=${tmpl//'{{BEAD_BRIEF}}'/$brief}
  printf '%s\n' "$tmpl"
}

# --- reap ------------------------------------------------------------------

reap_bead() {
  local bead="$1" name="bead-$1" started now age
  started=${ACTIVE["$bead"]}; now=$(date +%s); age=$(( now - started ))

  if (( age > PIPELINE_AGENT_TIMEOUT )); then
    log_warn "$bead: timed out after ${age}s"
    agent_stop "$name"
    finish_blocked "$bead" "timed out after ${age}s"
    return 0
  fi

  # Two independent signals. The report file is the contract; agent state is
  # only a hint that it is worth looking for one. A settled agent with no
  # report means it died or wandered off.
  local have_report=0
  [[ -f "$(report_path "$bead")" ]] && have_report=1

  if (( ! have_report )); then
    agent_settled "$name" || return 0
    sleep 3   # let a just-written report land before deciding it is missing
    [[ -f "$(report_path "$bead")" ]] || {
      log_warn "$bead: agent settled without a report"
      handle_failure "$bead" "The agent stopped without writing a completion report."
      return 0
    }
  fi

  log_info "$bead: validating"
  if ! validate_bead "$bead"; then
    handle_failure "$bead" "$(validation_feedback "$bead" "$(( ${ATTEMPTS[$bead]} + 1 ))")"
    return 0
  fi

  log_info "$bead: validated, merging"
  local rc=0
  with_lock merge wt_merge "$bead" || rc=$?

  case "$rc" in
    0)
      agent_stop "$name"
      bd_close "$bead"
      unset 'ACTIVE[$bead]'
      LANDED=$(( LANDED + 1 ))
      log_info "$bead: LANDED"
      log_event landed "$bead"
      [[ "$PIPELINE_CLEAN_WORKTREES" == "1" ]] && wt_remove "$bead"
      refresh_active_worktrees "$bead"
      ;;
    2)
      # Conflict: the agent that wrote the code is best placed to resolve it,
      # and it still has its worktree and its context.
      log_warn "$bead: merge conflict, returning to agent"
      handle_failure "$bead" "$(conflict_feedback "$bead")"
      ;;
    *)
      handle_failure "$bead" "Merge failed unexpectedly (exit $rc)."
      ;;
  esac
}

conflict_feedback() {
  local bead="$1"
  cat <<EOF
Your branch conflicts with work that landed on $PIPELINE_INTEGRATION_BRANCH
while you were building.

Resolve it inside your worktree:

    git merge $PIPELINE_INTEGRATION_BRANCH

Keep both sides' intent — the other change is already accepted, so do not
revert it. Re-run the tests, commit the merge, and rewrite your completion
report. Conflicting paths:

$(wt_conflict_files "$bead")
EOF
}

# Feedback goes back to the same agent, which still holds the context. Only
# after PIPELINE_MAX_ATTEMPTS do we give up and park the bead.
handle_failure() {
  local bead="$1" feedback="$2" name="bead-$1"
  ATTEMPTS["$bead"]=$(( ${ATTEMPTS["$bead"]:-0} + 1 ))

  if (( ${ATTEMPTS[$bead]} >= PIPELINE_MAX_ATTEMPTS )); then
    log_error "$bead: exhausted ${PIPELINE_MAX_ATTEMPTS} attempts"
    agent_stop "$name"
    finish_blocked "$bead" "failed validation ${ATTEMPTS[$bead]} times: $(printf '%s; ' "${VALIDATION_ERRORS[@]:-}")"
    return 0
  fi

  log_warn "$bead: attempt ${ATTEMPTS[$bead]} failed, sending feedback"
  log_event retry "$bead" "${ATTEMPTS[$bead]}"
  rm -f "$(report_path "$bead")"

  if ! agent_send "$name" "$feedback"; then
    agent_stop "$name"
    finish_blocked "$bead" "agent unreachable for feedback"
    return 0
  fi
  ACTIVE["$bead"]=$(date +%s)   # restart the clock for the retry
}

finish_blocked() {
  local bead="$1" reason="$2"
  bd_block "$bead" "$reason"
  unset 'ACTIVE[$bead]'
  BLOCKED=$(( BLOCKED + 1 ))
  log_event blocked "$bead" "$reason"
  # Worktree is deliberately left in place for a human to inspect.
  log_error "$bead: BLOCKED — $reason (worktree kept at $(wt_path "$bead"))"
}

# After a merge, pull the new integration tip into every still-running bead so
# late finishers do not drift into avoidable conflicts.
refresh_active_worktrees() {
  local skip="$1" b
  for b in "${!ACTIVE[@]}"; do
    [[ "$b" == "$skip" ]] && continue
    if wt_refresh "$b"; then
      log_debug "$b: refreshed from integration"
    else
      # Refresh is opportunistic. A conflict here is not fatal — the agent is
      # still mid-bead, and the same conflict will be handled properly at
      # merge time with the agent's own context behind it.
      log_debug "$b: could not fast-refresh from integration, deferring"
    fi
  done
  return 0
}

# --- main loop -------------------------------------------------------------

cycle() {
  local b
  # Reap over a snapshot: reap_bead mutates ACTIVE as beads land or block.
  local -a snapshot=("${!ACTIVE[@]}")
  for b in "${snapshot[@]}"; do
    [[ -n "${ACTIVE[$b]:-}" ]] || continue
    reap_bead "$b" || log_warn "$b: reap returned non-zero, continuing"
  done

  local free=$(( PIPELINE_MAX_AGENTS - ${#ACTIVE[@]} ))
  (( free > 0 )) || { log_debug "all $PIPELINE_MAX_AGENTS slots busy"; return 0; }

  local ready; ready=$(bd_ready_ids)
  [[ -n "$ready" ]] || { log_debug "no ready beads"; return 0; }

  while read -r bead; do
    [[ -n "$bead" ]] || continue
    (( free > 0 )) || break
    [[ -n "${ACTIVE[$bead]:-}" ]] && continue

    if (( DRY_RUN )); then
      printf 'would dispatch %s — %s\n' "$bead" "$(bd_title "$bead")"
      free=$(( free - 1 )); continue
    fi
    dispatch_bead "$bead" && free=$(( free - 1 ))
  done <<<"$ready"
  return 0
}

shutdown() {
  log_warn "interrupted — stopping ${#ACTIVE[@]} active agent(s)"
  local b
  for b in "${!ACTIVE[@]}"; do
    agent_stop "bead-$b"
    bd_set_status "$b" open      # release the claim so a rerun can pick it up
  done
  exit 130
}
trap shutdown INT TERM

main() {
  bd_available || die "bd (beads) not found. Install it, or run bin/doctor.sh."
  need_cmd jq
  need_cmd git
  wt_ensure_integration

  log_info "swarm starting: max=$PIPELINE_MAX_AGENTS mode=$PIPELINE_AGENT_MODE run=$PIPELINE_RUN_ID"

  while true; do
    cycle
    if (( ONCE )); then break; fi
    if (( ${#ACTIVE[@]} == 0 )) && [[ -z "$(bd_ready_ids)" ]]; then
      log_info "bead graph drained"
      break
    fi
    sleep "$PIPELINE_POLL_INTERVAL"
  done

  log_info "swarm finished: landed=$LANDED blocked=$BLOCKED remaining_open=$(bd_open_count)"
  (( BLOCKED == 0 ))
}

main "$@"
