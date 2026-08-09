#!/usr/bin/env bash
# Phase 4: turn the approved architecture into a bead graph.
#
# Unlike the reviewer, this agent runs inside the repository — it needs `bd`
# and it needs to see what already exists so it does not file beads for work
# that is already done.
#
#   decompose.sh [--arch docs/architecture/current.md] [--prd docs/prd/x.md]

set -Eeuo pipefail
source "$(cd "$(dirname "${BASH_SOURCE[0]}")/../lib" && pwd)/config.sh"
source "$PIPELINE_LIB_DIR/agents.sh"
source "$PIPELINE_LIB_DIR/beads.sh"

ARCH=""; PRD=""
while (( $# )); do
  case "$1" in
    --arch) shift; ARCH="$1" ;;
    --prd)  shift; PRD="$1" ;;
    -h|--help) sed -n '2,10p' "$0"; exit 0 ;;
    *) die "unknown flag: $1" ;;
  esac
  shift
done

[[ -n "$ARCH" ]] || ARCH="$PIPELINE_DOCS_DIR/architecture/current.md"
[[ -f "$PIPELINE_REPO_ROOT/$ARCH" || -f "$ARCH" ]] || die "architecture not found: $ARCH"
bd_available || die "bd (beads) not found — the decomposer cannot file beads without it"

OUTPUT="$PIPELINE_STATE_ABS/decomposition.json"
PROMPT="$PIPELINE_STATE_ABS/tasks/decompose.prompt.md"

BEFORE=$(bd_open_count)

tmpl=$(cat "$PIPELINE_HOME/prompts/decomposer.md")
tmpl=${tmpl//'{{PRD}}'/${PRD:-(none supplied)}}
tmpl=${tmpl//'{{ARCH_DOC}}'/$ARCH}
tmpl=${tmpl//'{{REVIEW_DIR}}'/$PIPELINE_DOCS_DIR/architecture}
tmpl=${tmpl//'{{REPO_ROOT}}'/$PIPELINE_REPO_ROOT}
tmpl=${tmpl//'{{MAX_AGENTS}}'/$PIPELINE_MAX_AGENTS}
tmpl=${tmpl//'{{OUTPUT}}'/$OUTPUT}
printf '%s\n' "$tmpl" >"$PROMPT"

log_info "decomposing $ARCH into beads"

if ! agent_run_until_file "decomposer" "$PIPELINE_REPO_ROOT" "$PROMPT" "$OUTPUT" \
       "${PIPELINE_DECOMPOSE_TIMEOUT:-2400}"; then
  die "decomposition did not complete"
fi

AFTER=$(bd_open_count)
CREATED=$(( AFTER - BEFORE ))
READY=$(bd_ready_ids | grep -c . || true)

log_info "decomposition complete: $CREATED new beads, $READY ready to start"

# A graph with nothing ready is a cycle or a bad root; a graph narrower than
# the agent ceiling will simply run under capacity. Both are worth flagging
# before five agents get launched against it.
if (( READY == 0 )); then
  log_error "no beads are ready — the graph is cyclic or every bead is blocked"
  exit 1
fi
if (( READY < PIPELINE_MAX_AGENTS )); then
  log_warn "only $READY bead(s) ready against a ceiling of $PIPELINE_MAX_AGENTS; the swarm will start under capacity"
fi

jq -r '"\nbeads: \(.beads|length)\nready:  \(.ready_at_start|join(", "))\ncritical path: \(.critical_path|join(" -> "))\nrisks:\n" + (.risks|map("  - "+.)|join("\n"))' \
  "$OUTPUT" 2>/dev/null || cat "$OUTPUT"
