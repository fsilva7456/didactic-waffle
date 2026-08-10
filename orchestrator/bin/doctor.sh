#!/usr/bin/env bash
# Preflight. Checks the assumptions the pipeline makes about your machine,
# and — importantly — probes the `bd` and `herdr` command surfaces this repo
# was written against. Both tools move quickly; when one of these checks
# fails, the fix belongs in lib/beads.sh or lib/agents.sh, not in the loop.
set -Eeuo pipefail
source "$(cd "$(dirname "${BASH_SOURCE[0]}")/../lib" && pwd)/config.sh"
source "$PIPELINE_LIB_DIR/beads.sh"
source "$PIPELINE_LIB_DIR/agents.sh"

ok=0; warn=0; bad=0
IS_MAC=""; [[ "$(uname -s)" == "Darwin" ]] && IS_MAC=1
pass() { printf '  \033[32m✓\033[0m %s\n' "$1"; ok=$((ok+1)); }
soft() { printf '  \033[33m!\033[0m %s\n' "$1"; warn=$((warn+1)); }
hard() { printf '  \033[31m✗\033[0m %s\n' "$1"; bad=$((bad+1)); }

echo "== host =="
printf '  · %s, bash %s\n' "$(uname -s)" "${BASH_VERSINFO[0]}.${BASH_VERSINFO[1]}"
if (( BASH_VERSINFO[0] >= 4 )); then
  pass "bash 4+"
else
  hard "bash 4+ required — macOS ships 3.2; \`brew install bash\`"
fi
for c in git jq; do
  command -v "$c" >/dev/null && pass "$c" \
    || hard "$c not found${IS_MAC:+ — brew install $c}"
done
# Locking is mkdir-based, so flock is deliberately not required.
if [[ -n "$PIPELINE_TIMEOUT_BIN" ]]; then
  pass "timeout: $PIPELINE_TIMEOUT_BIN"
else
  soft "no timeout/gtimeout — using the built-in watchdog (brew install coreutils for the real thing)"
fi

echo
echo "== repository =="
pass "repo root: $PIPELINE_REPO_ROOT"
if git -C "$PIPELINE_REPO_ROOT" show-ref --verify --quiet "refs/heads/$PIPELINE_BASE_BRANCH"; then
  pass "base branch: $PIPELINE_BASE_BRANCH"
else
  hard "base branch '$PIPELINE_BASE_BRANCH' does not exist (set PIPELINE_BASE_BRANCH)"
fi
if [[ -n "$(git -C "$PIPELINE_REPO_ROOT" status --porcelain)" ]]; then
  soft "working tree is dirty — commit or stash before a swarm run"
else
  pass "working tree clean"
fi
git -C "$PIPELINE_REPO_ROOT" worktree list --porcelain | grep -c '^worktree' >/dev/null \
  && pass "worktree support available"

echo
echo "== beads (bd) =="
if bd_available; then
  pass "bd found: $(command -v "$BD_BIN")"
  "$BD_BIN" --version 2>/dev/null | head -1 | sed 's/^/  · /' || true
  if bd_raw ready --json >/dev/null 2>&1; then
    pass "\`bd ready --json\` works"
    n=$(bd_ready_ids | grep -c . || true)
    printf '  · %s bead(s) currently ready\n' "$n"
  else
    hard "\`bd ready --json\` failed — is this a bd project? try \`bd init\`"
  fi
  if [[ -n "$(bd_ready_ids | head -1)" ]]; then
    probe=$(bd_ready_ids | head -1)
    [[ -n "$(bd_show_json "$probe" | jq -r '.id // empty')" ]] \
      && pass "bead JSON shape matches lib/beads.sh" \
      || hard "bead JSON shape unrecognised — adjust _bd_normalise in lib/beads.sh"
  else
    soft "no ready beads, so the JSON shape could not be verified"
  fi
else
  hard "bd not found — install beads, or run with mock agents only"
fi

echo
echo "== agent backend: $PIPELINE_AGENT_MODE =="
case "$PIPELINE_AGENT_MODE" in
  herdr)
    if command -v "$HERDR_BIN" >/dev/null; then
      pass "herdr found: $(command -v "$HERDR_BIN")"
      if "$HERDR_BIN" pane list >/dev/null 2>&1; then
        pass "herdr server reachable"
      else
        hard "herdr server not reachable — start herdr and run this from inside a herdr pane"
      fi
      # The adapter needs these three: agent get (status), pane close (stop),
      # agent start/send. `agent stop` does not exist in herdr — termination
      # goes through the agent's pane.
      "$HERDR_BIN" agent list >/dev/null 2>&1 \
        && pass "\`herdr agent list\` works" \
        || soft "\`herdr agent list\` failed — see _herdr_status in lib/agents.sh"
      if "$HERDR_BIN" agent --help 2>&1 | grep -q '\bget\b'; then
        pass "\`herdr agent get\` available (status + pane resolution)"
      else
        soft "no \`herdr agent get\` — _herdr_status falls back to scraping \`agent list\`"
      fi
      "$HERDR_BIN" pane --help 2>&1 | grep -q '\bclose\b' \
        && pass "\`herdr pane close\` available (agent termination)" \
        || soft "no \`herdr pane close\` — finished agents will leave panes open"
    else
      hard "herdr not found — install it or set PIPELINE_AGENT_MODE=headless"
    fi
    command -v "$PIPELINE_AGENT_CMD" >/dev/null \
      && pass "agent command: $PIPELINE_AGENT_CMD" \
      || hard "agent command '$PIPELINE_AGENT_CMD' not found"
    ;;
  headless)
    command -v "$PIPELINE_AGENT_CMD" >/dev/null \
      && pass "agent command: $PIPELINE_AGENT_CMD" \
      || hard "agent command '$PIPELINE_AGENT_CMD' not found"
    ;;
  mock) soft "mock mode — no real agents will run" ;;
  *) hard "unknown PIPELINE_AGENT_MODE: $PIPELINE_AGENT_MODE" ;;
esac

echo
echo "== validation gates =="
for pair in "install:$PIPELINE_INSTALL_CMD" "lint:$PIPELINE_LINT_CMD" \
            "test:$PIPELINE_TEST_CMD" "build:$PIPELINE_BUILD_CMD"; do
  label=${pair%%:*}; cmd=${pair#*:}
  [[ -n "$cmd" ]] && pass "$label: $cmd" || soft "$label: not configured"
done
# A swarm with no test gate merges on the agent's word alone.
[[ -z "$PIPELINE_TEST_CMD" ]] && \
  soft "no test command: validation will accept any bead that compiles a report"

echo
echo "== concurrency =="
printf '  · max agents: %s\n  · attempts per bead: %s\n  · agent timeout: %ss\n' \
  "$PIPELINE_MAX_AGENTS" "$PIPELINE_MAX_ATTEMPTS" "$PIPELINE_AGENT_TIMEOUT"
(( PIPELINE_MAX_AGENTS > 8 )) && soft "more than 8 concurrent agents tends to produce more merge conflicts than throughput"

echo
printf '%d ok, %d warnings, %d problems\n' "$ok" "$warn" "$bad"
(( bad == 0 ))
