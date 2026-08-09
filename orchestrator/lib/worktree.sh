# shellcheck shell=bash
# One git worktree per bead.
#
# This is what makes five concurrent implementers safe. Each agent gets its own
# checkout on its own branch, so parallel edits, test runs and build artifacts
# cannot collide. Merges back into the integration branch are serialised by the
# orchestrator, one bead at a time, so conflicts surface individually instead
# of as a pile-up at the end.

wt_path() { printf '%s/%s' "$PIPELINE_WORKTREE_ROOT" "$1"; }
wt_branch() { printf 'bead/%s' "$1"; }

# Create the integration branch on first use. All bead branches fork from it,
# so each implementer sees the work that has already landed.
wt_ensure_integration() {
  local repo="$PIPELINE_REPO_ROOT"
  if git -C "$repo" show-ref --verify --quiet "refs/heads/$PIPELINE_INTEGRATION_BRANCH"; then
    return 0
  fi
  log_info "creating integration branch $PIPELINE_INTEGRATION_BRANCH from $PIPELINE_BASE_BRANCH"
  git -C "$repo" branch "$PIPELINE_INTEGRATION_BRANCH" "$PIPELINE_BASE_BRANCH"
}

wt_create() {
  local bead="$1" path branch
  path=$(wt_path "$bead"); branch=$(wt_branch "$bead")
  mkdir -p "$PIPELINE_WORKTREE_ROOT"

  # A worktree left behind by a crashed run would otherwise poison this bead.
  wt_remove "$bead" >/dev/null 2>&1 || true

  git -C "$PIPELINE_REPO_ROOT" worktree add -q -B "$branch" "$path" \
      "$PIPELINE_INTEGRATION_BRANCH" \
    || { log_error "worktree add failed for $bead"; return 1; }
  printf '%s' "$path"
}

wt_remove() {
  local bead="$1" path branch
  path=$(wt_path "$bead"); branch=$(wt_branch "$bead")
  [[ -d "$path" ]] && git -C "$PIPELINE_REPO_ROOT" worktree remove --force "$path" >/dev/null 2>&1
  git -C "$PIPELINE_REPO_ROOT" worktree prune >/dev/null 2>&1 || true
  git -C "$PIPELINE_REPO_ROOT" branch -D "$branch" >/dev/null 2>&1 || true
  return 0
}

wt_has_commits() {
  local bead="$1" branch; branch=$(wt_branch "$bead")
  local n
  n=$(git -C "$PIPELINE_REPO_ROOT" rev-list --count \
        "$PIPELINE_INTEGRATION_BRANCH..$branch" 2>/dev/null || echo 0)
  (( n > 0 ))
}

wt_changed_files() {
  local bead="$1" branch; branch=$(wt_branch "$bead")
  git -C "$PIPELINE_REPO_ROOT" diff --name-only \
      "$PIPELINE_INTEGRATION_BRANCH...$branch" 2>/dev/null || true
}

# Commit anything the agent left dirty. Real agents are told to commit their
# own work, but a run must not lose changes just because one forgot.
wt_autocommit() {
  local bead="$1" path; path=$(wt_path "$bead")
  [[ -d "$path" ]] || return 0
  if [[ -n "$(git -C "$path" status --porcelain)" ]]; then
    log_warn "$bead: agent left uncommitted changes; committing them"
    git -C "$path" add -A
    git -C "$path" -c user.email=orchestrator@pipeline -c user.name=orchestrator \
        commit -qm "chore($bead): orchestrator autocommit of agent leftovers"
  fi
}

# Serialised, single-bead merge into the integration branch. Called under
# with_lock so two beads never merge at once.
wt_merge() {
  local bead="$1" branch repo
  branch=$(wt_branch "$bead"); repo="$PIPELINE_REPO_ROOT"

  local prev; prev=$(git -C "$repo" rev-parse --abbrev-ref HEAD)
  git -C "$repo" checkout -q "$PIPELINE_INTEGRATION_BRANCH" || return 1

  if git -C "$repo" merge --no-ff -q -m "merge($bead): land bead $bead" "$branch"; then
    git -C "$repo" checkout -q "$prev" 2>/dev/null || true
    return 0
  fi

  git -C "$repo" merge --abort 2>/dev/null || true
  git -C "$repo" checkout -q "$prev" 2>/dev/null || true
  return 2   # 2 == conflict, distinct from a generic failure
}

wt_conflict_files() {
  local bead="$1" branch; branch=$(wt_branch "$bead")
  git -C "$PIPELINE_REPO_ROOT" diff --name-only --diff-filter=U 2>/dev/null
  git -C "$PIPELINE_REPO_ROOT" merge-tree \
      "$(git -C "$PIPELINE_REPO_ROOT" merge-base "$PIPELINE_INTEGRATION_BRANCH" "$branch")" \
      "$PIPELINE_INTEGRATION_BRANCH" "$branch" 2>/dev/null \
    | grep -E '^\+<<<<<<<|^changed in both' -A2 | head -40 || true
}

# Pull newly-landed work into a still-running bead's branch. Keeps late beads
# from drifting far enough behind integration to conflict badly.
wt_refresh() {
  local bead="$1" path; path=$(wt_path "$bead")
  [[ -d "$path" ]] || return 0

  # Never leave an agent's worktree mid-merge: it is working in there right
  # now, and a conflicted index would corrupt whatever it does next.
  if git -C "$path" merge --no-edit -q "$PIPELINE_INTEGRATION_BRANCH" 2>/dev/null; then
    return 0
  fi
  git -C "$path" merge --abort 2>/dev/null || true
  return 1
}
