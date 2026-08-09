#!/usr/bin/env bash
# A fake `claude` binary for testing PIPELINE_AGENT_MODE=headless.
#
# Accepts the same shape of invocation the headless backend uses
# (`claude <flags> -p <prompt>`), then performs the mock implementer's work.
# The bead id comes from the worktree directory name, which is how a real
# agent's cwd is set up too.
set -Eeuo pipefail

prompt=""
while (( $# )); do
  case "$1" in
    -p) shift; prompt="${1:-}" ;;
    *)  ;;
  esac
  shift || break
done

bead=$(basename "$PWD")

# Feedback rounds re-invoke with the task plus the failure. Record it so tests
# can assert the agent was actually told what went wrong.
if [[ "$prompt" == *"Feedback on your previous attempt"* ]]; then
  printf '%s\n' "$prompt" >"${PIPELINE_STATE_ABS:?}/runs/$bead.feedback.txt"
fi

exec "$(dirname "${BASH_SOURCE[0]}")/mock_agent.sh" "$PWD" "$bead" /dev/null
