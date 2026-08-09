#!/usr/bin/env bash
# A stand-in implementer used by the test suite.
#
# It honours exactly the same contract as a real Claude implementer: rebase on
# whatever has landed, do the work in the worktree, touch documentation,
# commit, then write a completion report. That lets test-swarm.sh exercise the
# full dispatch / validate / merge / retry machinery without an LLM in the path.
set -Eeuo pipefail

cwd="$1"; bead="$2"
report="${PIPELINE_STATE_ABS:?}/reports/$bead.json"
integration="${PIPELINE_INTEGRATION_BRANCH:-pipeline/integration}"
cd "$cwd"

git_commit() {
  git -c user.email=mock@pipeline -c user.name="mock agent" commit -q "$@"
}

sleep "${MOCK_AGENT_DELAY:-1}"

# Step one of the conflict feedback the orchestrator sends: merge what has
# landed since this bead started. A real agent reasons about each conflict;
# the mock keeps its own side, which is enough to prove the loop recovers.
if git rev-parse --verify -q "$integration" >/dev/null 2>&1; then
  if ! git merge --no-edit -q "$integration" 2>/dev/null; then
    while read -r f; do
      [[ -n "$f" ]] || continue
      git checkout --ours -- "$f" 2>/dev/null || true
      git add -- "$f"
    done < <(git diff --name-only --diff-filter=U)
    git_commit -m "merge($bead): resolve conflicts with $integration" || true
  fi
fi

mkdir -p src docs/beads
printf 'export const %s = () => "%s";\n' "${bead//-/_}" "$bead" >"src/$bead.js"
printf '# %s\n\nImplemented by the swarm.\n' "$bead" >"docs/beads/$bead.md"

# MOCK_CONTENDED_FILE makes every bead rewrite the same line of the same file,
# which is how the conflict-handling path gets exercised.
if [[ -n "${MOCK_CONTENDED_FILE:-}" ]]; then
  printf 'owner = %s\n' "$bead" >"$MOCK_CONTENDED_FILE"
fi

git add -A
git_commit -m "feat($bead): mock implementation" || true

# MOCK_FAIL_BEADS lets a test force the failure path for specific beads.
if [[ " ${MOCK_FAIL_BEADS:-} " == *" $bead "* ]]; then
  cat >"$report" <<JSON
{"bead":"$bead","status":"failed","summary":"mock forced failure",
 "files_changed":["src/$bead.js"],"docs_updated":["docs/beads/$bead.md"],
 "tests_run":"none","notes":"MOCK_FAIL_BEADS"}
JSON
  exit 0
fi

cat >"$report" <<JSON
{"bead":"$bead","status":"complete","summary":"mock implementation of $bead",
 "files_changed":["src/$bead.js"],"docs_updated":["docs/beads/$bead.md"],
 "tests_run":"mock","notes":""}
JSON
