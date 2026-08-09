#!/usr/bin/env bash
# Phase 3: independent architecture review.
#
# Spawns a reviewer in a sandbox containing nothing but the PRD, the
# architecture document, and its own previous round's findings. No repository,
# no git history, no conversation. The isolation is the point: a reviewer that
# has watched the design evolve will accept reasoning it should be attacking.
#
#   review-arch.sh --arch docs/architecture/current.md [--prd docs/prd/x.md]
#                  [--round N] [--no-prd]
#
# Exit: 0 approved | 3 changes requested | 1 the review did not complete

set -Eeuo pipefail
source "$(cd "$(dirname "${BASH_SOURCE[0]}")/../lib" && pwd)/config.sh"
source "$PIPELINE_LIB_DIR/agents.sh"

ARCH=""; PRD=""; ROUND=1; INCLUDE_PRD=1
while (( $# )); do
  case "$1" in
    --arch)   shift; ARCH="$1" ;;
    --prd)    shift; PRD="$1" ;;
    --round)  shift; ROUND="$1" ;;
    --no-prd) INCLUDE_PRD=0 ;;
    -h|--help) sed -n '2,14p' "$0"; exit 0 ;;
    *) die "unknown flag: $1" ;;
  esac
  shift
done

[[ -n "$ARCH" ]] || ARCH="$PIPELINE_DOCS_DIR/architecture/current.md"
[[ -f "$ARCH" ]] || die "architecture document not found: $ARCH"

SANDBOX="$PIPELINE_STATE_ABS/review/round-$ROUND"
rm -rf "$SANDBOX"; mkdir -p "$SANDBOX"

cp "$ARCH" "$SANDBOX/ARCHITECTURE.md"

if (( INCLUDE_PRD )); then
  # The reviewer needs the requirements to judge fit — without them it can only
  # review the design against itself.
  [[ -z "$PRD" && -d "$PIPELINE_DOCS_DIR/prd" ]] && \
    PRD=$(find "$PIPELINE_DOCS_DIR/prd" -name '*.md' -print -quit 2>/dev/null || true)
  [[ -n "$PRD" && -f "$PRD" ]] && cp "$PRD" "$SANDBOX/PRD.md"
fi

# Carry the previous round forward so the reviewer can check whether its own
# findings were actually addressed rather than restating them.
PREV=$(( ROUND - 1 ))
PREV_REVIEW="$PIPELINE_DOCS_DIR/architecture/review-round-$PREV.md"
[[ -f "$PREV_REVIEW" ]] && cp "$PREV_REVIEW" "$SANDBOX/PRIOR-REVIEW.md"

PROMPT="$SANDBOX/.prompt.md"
sed "s/{{ROUND}}/$ROUND/g" "$PIPELINE_HOME/prompts/arch-reviewer.md" >"$PROMPT"

# A sandbox git repo keeps the agent's tooling happy without exposing history.
git -C "$SANDBOX" init -q 2>/dev/null || true

log_info "architecture review round $ROUND (sandbox: $SANDBOX)"

if ! agent_run_until_file "arch-reviewer-r$ROUND" "$SANDBOX" "$PROMPT" \
       "$SANDBOX/REVIEW.md" "${PIPELINE_REVIEW_TIMEOUT:-1800}"; then
  die "architecture review round $ROUND did not produce a review"
fi

DEST="$PIPELINE_DOCS_DIR/architecture/review-round-$ROUND.md"
mkdir -p "$(dirname "$DEST")"
cp "$SANDBOX/REVIEW.md" "$DEST"
log_info "review written to $DEST"

VERDICT=$(grep -iEm1 '^\*\*verdict:?\*\*' "$DEST" | grep -oiE 'approved|changes-requested' || true)
BLOCKERS=$(grep -ciE '^###[[:space:]]*\[(blocker|major)\]' "$DEST" || true)

printf '\n%s\n' "$(cat "$DEST")"
printf '\n--- verdict: %s (%s blocker/major findings) ---\n' "${VERDICT:-unknown}" "$BLOCKERS"

log_event review "$ROUND" "${VERDICT:-unknown}" "$BLOCKERS"

# Trust the findings over the self-reported verdict: a reviewer that files a
# blocker and then writes "approved" has contradicted itself, and the safe
# reading is the blocker.
if [[ "$VERDICT" == "approved" ]] && (( BLOCKERS == 0 )); then
  exit 0
fi
exit 3
