#!/usr/bin/env bash
# What the swarm is doing right now. Safe to run from another terminal while a
# run is in flight.
set -Eeuo pipefail
source "$(cd "$(dirname "${BASH_SOURCE[0]}")/../lib" && pwd)/config.sh"
source "$PIPELINE_LIB_DIR/beads.sh"
source "$PIPELINE_LIB_DIR/agents.sh"
source "$PIPELINE_LIB_DIR/worktree.sh"

echo "== beads =="
if bd_available; then
  bd_raw list --json 2>/dev/null | _bd_unwrap_list | _bd_normalise \
    | jq -r 'group_by(.status)[] | "  \(.[0].status): \(length)"'
  echo
  echo "  ready now:"
  bd_ready_json | jq -r '.[] | "    \(.id)  p\(.priority)  \(.title)"' | head -20
else
  echo "  bd not available"
fi

echo
echo "== live worktrees =="
if [[ -d "$PIPELINE_WORKTREE_ROOT" ]]; then
  for d in "$PIPELINE_WORKTREE_ROOT"/*/; do
    [[ -d "$d" ]] || continue
    bead=$(basename "$d")
    status=$(agent_status "bead-$bead" 2>/dev/null || echo unknown)
    commits=$(git -C "$PIPELINE_REPO_ROOT" rev-list --count \
                "$PIPELINE_INTEGRATION_BRANCH..$(wt_branch "$bead")" 2>/dev/null || echo 0)
    report="—"
    [[ -f "$PIPELINE_STATE_ABS/reports/$bead.json" ]] && \
      report=$(jq -r '.status // "?"' "$PIPELINE_STATE_ABS/reports/$bead.json")
    printf '  %-14s agent=%-8s commits=%-3s report=%s\n' "$bead" "$status" "$commits" "$report"
  done
else
  echo "  none"
fi

echo
echo "== integration branch =="
if git -C "$PIPELINE_REPO_ROOT" show-ref --verify --quiet "refs/heads/$PIPELINE_INTEGRATION_BRANCH"; then
  ahead=$(git -C "$PIPELINE_REPO_ROOT" rev-list --count \
            "$PIPELINE_BASE_BRANCH..$PIPELINE_INTEGRATION_BRANCH" 2>/dev/null || echo 0)
  printf '  %s is %s commit(s) ahead of %s\n' \
    "$PIPELINE_INTEGRATION_BRANCH" "$ahead" "$PIPELINE_BASE_BRANCH"
  git -C "$PIPELINE_REPO_ROOT" log --merges --oneline -8 "$PIPELINE_INTEGRATION_BRANCH" \
    | sed 's/^/    /'
else
  echo "  not created yet"
fi

echo
echo "== latest run =="
latest=$(ls -t "$PIPELINE_STATE_ABS"/runs/*.log 2>/dev/null | head -1 || true)
if [[ -n "$latest" ]]; then
  printf '  %s\n' "$latest"
  tail -12 "$latest" | sed 's/^/    /'
else
  echo "  no runs yet"
fi
