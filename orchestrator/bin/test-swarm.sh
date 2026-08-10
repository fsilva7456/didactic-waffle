#!/usr/bin/env bash
# End-to-end exercise of the swarm loop against mock beads and mock agents.
#
# Proves the parts that are easy to get wrong and expensive to debug live:
# dependency-ordered scheduling, the concurrency ceiling, worktree isolation,
# the validation gate, retry-then-block, and serialised merges.
#
# Runs in a scratch clone; your repo is never touched.
set -Eeuo pipefail

HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ORCH="$(cd "$HERE/.." && pwd)"
SRC="$(cd "$ORCH/.." && pwd)"

SANDBOX=$(mktemp -d)
trap 'rm -rf "$SANDBOX"' EXIT
REPO="$SANDBOX/repo"

# coreutils `timeout` is absent on stock macOS; Homebrew ships it as gtimeout.
if command -v timeout >/dev/null 2>&1;      then TIMEOUT=timeout
elif command -v gtimeout >/dev/null 2>&1;   then TIMEOUT=gtimeout
else TIMEOUT=""; fi
run_bounded() { local s="$1"; shift; if [[ -n "$TIMEOUT" ]]; then "$TIMEOUT" "$s" "$@"; else "$@"; fi; }

pass=0; fail=0
ok()   { printf '  \033[32mPASS\033[0m %s\n' "$1"; pass=$((pass+1)); }
bad()  { printf '  \033[31mFAIL\033[0m %s\n' "$1"; fail=$((fail+1)); }
check(){ if [[ "$2" == "$3" ]]; then ok "$1"; else bad "$1 (expected '$3', got '$2')"; fi; }

# --- sandbox ---------------------------------------------------------------

mkdir -p "$REPO"
cp -r "$SRC/orchestrator" "$REPO/"
cp "$SRC/pipeline.config.sh" "$REPO/"
cd "$REPO"
git init -q -b main
git config user.email test@pipeline; git config user.name test
mkdir -p docs && echo '# sandbox' >docs/README.md
git add -A && git commit -qm "initial"

# Fake `bd` on PATH.
mkdir -p "$SANDBOX/bin"
ln -sf "$REPO/orchestrator/lib/mock_bd.sh" "$SANDBOX/bin/bd"
chmod +x "$REPO/orchestrator/lib/mock_bd.sh" "$REPO/orchestrator/lib/mock_agent.sh"
export PATH="$SANDBOX/bin:$PATH"
export MOCK_BD_STORE="$SANDBOX/beads.json"

# A graph with a real dependency: bd-005 is blocked until bd-001 closes.
cat >"$MOCK_BD_STORE" <<'JSON'
[
 {"id":"bd-001","title":"schema","description":"create the schema","status":"open","priority":0,"deps":[]},
 {"id":"bd-002","title":"api","description":"build the api","status":"open","priority":1,"deps":[]},
 {"id":"bd-003","title":"ui","description":"build the ui","status":"open","priority":1,"deps":[]},
 {"id":"bd-004","title":"auth","description":"add auth","status":"open","priority":1,"deps":[]},
 {"id":"bd-005","title":"reports","description":"needs schema","status":"open","priority":2,"deps":["bd-001"]},
 {"id":"bd-006","title":"metrics","description":"independent","status":"open","priority":2,"deps":[]},
 {"id":"bd-bad","title":"doomed","description":"always fails","status":"open","priority":2,"deps":[]}
]
JSON

export PIPELINE_AGENT_MODE=mock
export PIPELINE_MAX_AGENTS=5
export PIPELINE_POLL_INTERVAL=1
export PIPELINE_MAX_ATTEMPTS=2
export PIPELINE_AGENT_TIMEOUT=120
export PIPELINE_REQUIRE_DOCS=1
export PIPELINE_TEST_CMD='test -f package.json || true'
export PIPELINE_WORKTREE_ROOT="$SANDBOX/worktrees"
export MOCK_AGENT_DELAY=1
export MOCK_FAIL_BEADS="bd-bad"
export PIPELINE_LOG_LEVEL=warn

echo
echo "== portability primitives =="

# with_lock and run_with_timeout replace flock and coreutils timeout, neither
# of which exists on a stock macOS. They are load-bearing for merge safety and
# gate budgets, so they get tested directly rather than only in passing.
(
  # shellcheck source=/dev/null
  source "$REPO/orchestrator/lib/config.sh"

  # Mutual exclusion: two concurrent holders must not interleave.
  marker="$SANDBOX/lock-order"; : >"$marker"
  critical() { printf '%s-in\n' "$1" >>"$marker"; sleep 0.3; printf '%s-out\n' "$1" >>"$marker"; }
  with_lock t critical A & p1=$!
  sleep 0.05
  with_lock t critical B & p2=$!
  wait $p1 $p2
  if grep -qE '^(A-in\nA-out\nB-in\nB-out|B-in\nB-out\nA-in\nA-out)$' <(cat "$marker") 2>/dev/null \
     || [[ "$(tr '\n' ' ' <"$marker")" == "A-in A-out B-in B-out " \
        || "$(tr '\n' ' ' <"$marker")" == "B-in B-out A-in A-out " ]]; then
    echo "LOCK_OK"
  else
    echo "LOCK_BAD: $(tr '\n' ' ' <"$marker")"
  fi

  # A lock left by a dead process must be reclaimed, not wedge every later run.
  mkdir -p "$PIPELINE_STATE_ABS/locks/stale.lock.d"
  echo 999999 >"$PIPELINE_STATE_ABS/locks/stale.lock.d/pid"
  if with_lock stale true 2>/dev/null; then echo "STALE_OK"; else echo "STALE_BAD"; fi

  # Watchdog fallback: force the no-coreutils path and confirm it still kills.
  PIPELINE_TIMEOUT_BIN=""
  start=$(date +%s)
  run_with_timeout 1 sleep 30 >/dev/null 2>&1 || true
  elapsed=$(( $(date +%s) - start ))
  if (( elapsed <= 5 )); then echo "TIMEOUT_OK"; else echo "TIMEOUT_BAD:${elapsed}s"; fi
) >"$SANDBOX/prim.out" 2>&1 || true

check "with_lock serialises concurrent holders" \
  "$(grep -c LOCK_OK "$SANDBOX/prim.out")" "1"
check "with_lock reclaims a lock from a dead process" \
  "$(grep -c STALE_OK "$SANDBOX/prim.out")" "1"
check "run_with_timeout kills without coreutils installed" \
  "$(grep -c TIMEOUT_OK "$SANDBOX/prim.out")" "1"

echo
echo "== scheduling and concurrency =="

# Dry run must respect both the ready-set and the concurrency ceiling.
dry=$(./orchestrator/bin/swarm.sh --once --dry-run 2>/dev/null)
check "dispatches exactly PIPELINE_MAX_AGENTS beads" "$(grep -c '^would dispatch' <<<"$dry")" "5"
check "blocked bead is not schedulable" "$(grep -c 'bd-005' <<<"$dry" || true)" "0"

echo
echo "== full run to drain =="

set +e
./orchestrator/bin/swarm.sh >"$SANDBOX/run.log" 2>&1
rc=$?
set -e

closed=$(jq -r '[.[]|select(.status=="closed")]|length' "$MOCK_BD_STORE")
blocked=$(jq -r '[.[]|select(.status=="blocked")]|length' "$MOCK_BD_STORE")
open=$(jq -r '[.[]|select(.status=="open")]|length' "$MOCK_BD_STORE")

check "six good beads landed"            "$closed"  "6"
check "the failing bead is parked"       "$blocked" "1"
check "nothing left open"                "$open"    "0"
check "exit code reports the blockage"   "$rc"      "1"

echo
echo "== merge integrity =="

git checkout -q pipeline/integration

# bd-005 depends on bd-001, so bd-001's merge must be an ancestor of bd-005's.
# That is the real guarantee: bd-005 was built on top of bd-001's code, not
# merely merged after it in wall-clock time.
m001=$(git log --merges --format='%H %s' | awk '/merge\(bd-001\)/{print $1}')
m005=$(git log --merges --format='%H %s' | awk '/merge\(bd-005\)/{print $1}')
if [[ -n "$m001" && -n "$m005" ]] && git merge-base --is-ancestor "$m001" "$m005"; then
  ok "dependent bead was built on top of its dependency"
else
  bad "bd-005 did not build on bd-001 (m001=$m001 m005=$m005)"
fi

for b in bd-001 bd-002 bd-003 bd-004 bd-005 bd-006; do
  [[ -f "src/$b.js" ]] || bad "missing src/$b.js on integration branch"
done
[[ -f src/bd-bad.js ]] && bad "failing bead leaked onto the integration branch"
ok "all landed beads present, failed bead excluded"

check "docs updated by the swarm" \
  "$(ls docs/beads 2>/dev/null | wc -l | tr -d ' ')" "6"

# Every landed bead must arrive as its own merge commit — that is what makes a
# single bead revertable after the fact.
check "one merge commit per landed bead" \
  "$(git log --merges --oneline | grep -c 'merge(bd-')" "6"

check "retry happened before blocking" \
  "$(grep -c 'attempt 1 failed' "$SANDBOX/run.log")" "1"

echo
echo "== cleanup =="
check "worktrees pruned for landed beads" \
  "$(ls "$PIPELINE_WORKTREE_ROOT" 2>/dev/null | grep -cv 'bd-bad' || true)" "0"
check "failed bead's worktree kept for inspection" \
  "$([[ -d "$PIPELINE_WORKTREE_ROOT/bd-bad" ]] && echo yes || echo no)" "yes"

echo
echo "== merge conflicts =="

# Every bead now rewrites the same line of the same file, so the first lands
# cleanly and the rest arrive conflicted. The swarm must still drain the graph
# rather than deadlock or lose work.
CONFLICT_SB=$(mktemp -d); trap 'rm -rf "$SANDBOX" "$CONFLICT_SB"' EXIT
cp -r "$SRC/orchestrator" "$SRC/pipeline.config.sh" "$CONFLICT_SB/"
cd "$CONFLICT_SB"
git init -q -b main; git config user.email t@t; git config user.name t
mkdir -p docs; echo '# sandbox' >docs/README.md; echo 'owner = none' >OWNER
git add -A; git commit -qm initial

export MOCK_BD_STORE="$CONFLICT_SB/beads.json"
cat >"$MOCK_BD_STORE" <<'JSON'
[{"id":"bd-c1","title":"c1","description":"contend","status":"open","priority":1,"deps":[]},
 {"id":"bd-c2","title":"c2","description":"contend","status":"open","priority":1,"deps":[]},
 {"id":"bd-c3","title":"c3","description":"contend","status":"open","priority":1,"deps":[]}]
JSON
export MOCK_CONTENDED_FILE="OWNER"
export MOCK_FAIL_BEADS=""
export PIPELINE_WORKTREE_ROOT="$CONFLICT_SB/worktrees"
export PIPELINE_MAX_ATTEMPTS=3

set +e
run_bounded 180 ./orchestrator/bin/swarm.sh >"$CONFLICT_SB/run.log" 2>&1
crc=$?
set -e

check "swarm terminates instead of deadlocking on conflicts" \
  "$([[ $crc -ne 124 && $crc -ne 143 ]] && echo yes || echo no)" "yes"
check "conflicts were detected and routed back to the agent" \
  "$([[ $(grep -c 'merge conflict, returning to agent' "$CONFLICT_SB/run.log") -ge 1 ]] && echo yes || echo no)" "yes"
check "every contended bead resolved and closed" \
  "$(jq -r '[.[]|select(.status=="closed")]|length' "$MOCK_BD_STORE")" "3"

git checkout -q pipeline/integration
check "no conflict markers survived into integration" \
  "$(grep -q '<<<<<<<' OWNER && echo dirty || echo clean)" "clean"
check "the last writer owns the contended file" \
  "$(grep -c '^owner = bd-c' OWNER)" "1"

echo
echo "== headless backend =="

# The headless path (`claude -p`, no multiplexer) is what CI uses, so it gets
# the same end-to-end treatment as the default backend.
HL_SB=$(mktemp -d); trap 'rm -rf "$SANDBOX" "$CONFLICT_SB" "$HL_SB"' EXIT
cp -r "$SRC/orchestrator" "$SRC/pipeline.config.sh" "$HL_SB/"
cd "$HL_SB"
git init -q -b main; git config user.email t@t; git config user.name t
mkdir -p docs; echo '# sandbox' >docs/README.md
git add -A; git commit -qm initial
chmod +x orchestrator/lib/fake_claude.sh

export MOCK_BD_STORE="$HL_SB/beads.json"
cat >"$MOCK_BD_STORE" <<'JSON'
[{"id":"bd-h1","title":"h1","description":"headless","status":"open","priority":1,"deps":[]},
 {"id":"bd-h2","title":"h2","description":"headless","status":"open","priority":1,"deps":[]}]
JSON
export PIPELINE_AGENT_MODE=headless
export PIPELINE_AGENT_CMD="$HL_SB/orchestrator/lib/fake_claude.sh"
export PIPELINE_AGENT_ARGS=""
export PIPELINE_WORKTREE_ROOT="$HL_SB/worktrees"
export MOCK_CONTENDED_FILE="" MOCK_FAIL_BEADS="bd-h2" PIPELINE_MAX_ATTEMPTS=2

set +e
run_bounded 180 ./orchestrator/bin/swarm.sh >"$HL_SB/run.log" 2>&1
set -e

check "headless agent landed its bead" \
  "$(jq -r '[.[]|select(.status=="closed")]|length' "$MOCK_BD_STORE")" "1"
check "headless retry carried the original task plus the failure" \
  "$([[ -f "$HL_SB/.pipeline/runs/bd-h2.feedback.txt" ]] && \
     grep -q 'You own exactly' "$HL_SB/.pipeline/runs/bd-h2.feedback.txt" && \
     echo yes || echo no)" "yes"

echo
printf '%d passed, %d failed\n' "$pass" "$fail"
(( fail == 0 ))
