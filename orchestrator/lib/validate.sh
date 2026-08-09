# shellcheck shell=bash
# The orchestrator's validation gate.
#
# An implementer claiming success is a claim, not evidence. Nothing merges
# until these checks pass against the bead's own worktree. Failures are
# written back as structured feedback so the same agent can be handed a
# concrete list of what to fix rather than "try again".

report_path() { printf '%s/reports/%s.json' "$PIPELINE_STATE_ABS" "$1"; }

validate_reset() { VALIDATION_ERRORS=(); }

_fail() { VALIDATION_ERRORS+=("$1"); log_warn "validate: $1"; }

# Run one gate inside the worktree, capturing output for the feedback message.
_run_gate() {
  local bead="$1" label="$2" cmd="$3" path out rc=0
  [[ -n "$cmd" ]] || return 0
  path=$(wt_path "$bead")
  log_info "$bead: gate '$label' -> $cmd"
  out=$(cd "$path" && timeout 900 bash -lc "$cmd" 2>&1) || rc=$?
  if (( rc != 0 )); then
    _fail "$label failed (exit $rc):
\`\`\`
$(tail -n 40 <<<"$out")
\`\`\`"
    return 1
  fi
  return 0
}

# Returns 0 when the bead is mergeable. Populates VALIDATION_ERRORS otherwise.
validate_bead() {
  local bead="$1"
  validate_reset

  local report; report=$(report_path "$bead")
  if [[ ! -f "$report" ]]; then
    _fail "no completion report at $report — the agent never signalled done."
    return 1
  fi

  if ! jq -e . "$report" >/dev/null 2>&1; then
    _fail "completion report is not valid JSON."
    return 1
  fi

  local status; status=$(jq -r '.status // "unknown"' "$report")
  if [[ "$status" != "complete" ]]; then
    _fail "agent reported status=$status: $(jq -r '.summary // .notes // ""' "$report")"
    return 1
  fi

  wt_autocommit "$bead"

  if ! wt_has_commits "$bead"; then
    _fail "branch $(wt_branch "$bead") has no commits over $PIPELINE_INTEGRATION_BRANCH."
    return 1
  fi

  # Documentation is part of the definition of done, not a follow-up bead.
  if [[ "$PIPELINE_REQUIRE_DOCS" == "1" ]]; then
    local changed touched=0 p
    changed=$(wt_changed_files "$bead")
    for p in $PIPELINE_DOCS_PATHS; do
      grep -qE "^${p}(/|$)" <<<"$changed" && { touched=1; break; }
    done
    (( touched )) || _fail "no documentation change under: $PIPELINE_DOCS_PATHS"
  fi

  _run_gate "$bead" install "$PIPELINE_INSTALL_CMD" || true
  _run_gate "$bead" lint    "$PIPELINE_LINT_CMD"    || true
  _run_gate "$bead" test    "$PIPELINE_TEST_CMD"    || true
  _run_gate "$bead" build   "$PIPELINE_BUILD_CMD"   || true

  (( ${#VALIDATION_ERRORS[@]} == 0 ))
}

# Feedback handed straight back to the agent that produced the failure.
validation_feedback() {
  local bead="$1" attempt="$2" e
  printf 'Validation failed for bead %s (attempt %s of %s). Fix every item below in this same worktree, commit, then rewrite your completion report.\n\n' \
    "$bead" "$attempt" "$PIPELINE_MAX_ATTEMPTS"
  for e in "${VALIDATION_ERRORS[@]}"; do
    printf -- '- %s\n' "$e"
  done
  printf '\nDo not start unrelated work. Do not touch files outside this bead.\n'
}
