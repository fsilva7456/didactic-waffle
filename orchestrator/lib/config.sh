# shellcheck shell=bash
# Bootstrap: locate the repo, load config, set up state dirs.
# Every entrypoint sources this file first.

set -Eeuo pipefail

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
with_lock() {
  local name="$1"; shift
  local lockfile="$PIPELINE_STATE_ABS/locks/$name.lock"
  exec {lock_fd}>"$lockfile"
  flock "$lock_fd"
  local rc=0
  "$@" || rc=$?
  exec {lock_fd}>&-
  return $rc
}
