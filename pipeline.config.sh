# shellcheck shell=bash
# Pipeline configuration. Sourced by every orchestrator script.
# Override any value by exporting it before invoking, or by editing here.

# ---------------------------------------------------------------------------
# Concurrency
# ---------------------------------------------------------------------------

# Maximum number of implementer sub-agents alive at once. Each one owns exactly
# one bead. The dependency graph usually caps this lower than the ceiling.
: "${PIPELINE_MAX_AGENTS:=5}"

# Seconds between polls of the active agent set.
: "${PIPELINE_POLL_INTERVAL:=15}"

# Wall-clock budget for a single bead before the orchestrator reclaims it.
: "${PIPELINE_AGENT_TIMEOUT:=3600}"

# How many times a single bead may fail validation before it is parked as
# blocked and the loop moves on to other work.
: "${PIPELINE_MAX_ATTEMPTS:=3}"

# ---------------------------------------------------------------------------
# Agent backend
# ---------------------------------------------------------------------------

# herdr   - spawn each implementer in a herdr pane (observable, the default)
# headless- spawn each implementer via `claude -p` (CI, no multiplexer)
# mock    - run the built-in fake implementer (used by the test suite)
: "${PIPELINE_AGENT_MODE:=herdr}"

# Executable herdr hands to `agent start ... -- <cmd>`.
: "${PIPELINE_AGENT_CMD:=claude}"

# Extra flags appended to the agent command line.
: "${PIPELINE_AGENT_ARGS:=--permission-mode acceptEdits}"

# Direction passed to `herdr agent start --split`.
: "${PIPELINE_HERDR_SPLIT:=right}"

# ---------------------------------------------------------------------------
# Git topology
# ---------------------------------------------------------------------------

# Branch that accumulates completed beads. Created from PIPELINE_BASE_BRANCH on
# first run. Never push straight to the base branch.
: "${PIPELINE_INTEGRATION_BRANCH:=pipeline/integration}"
: "${PIPELINE_BASE_BRANCH:=main}"

# Where per-bead worktrees are created. Kept outside the repo so that agent
# file globs and test runners never see sibling worktrees.
: "${PIPELINE_WORKTREE_ROOT:=${TMPDIR:-/tmp}/pipeline-worktrees}"

# Delete a bead's worktree after a successful merge.
: "${PIPELINE_CLEAN_WORKTREES:=1}"

# ---------------------------------------------------------------------------
# Validation gates
# ---------------------------------------------------------------------------
# Run inside the bead's worktree, in this order, after the agent reports done.
# Empty string disables a gate. Non-zero exit fails the bead.

: "${PIPELINE_INSTALL_CMD:=}"
: "${PIPELINE_LINT_CMD:=}"
: "${PIPELINE_TEST_CMD:=}"
: "${PIPELINE_BUILD_CMD:=}"

# Require the agent to have modified at least one file under docs/ (or another
# path listed here, space separated) before a bead may merge.
: "${PIPELINE_DOCS_PATHS:=docs README.md}"
: "${PIPELINE_REQUIRE_DOCS:=1}"

# ---------------------------------------------------------------------------
# Layout
# ---------------------------------------------------------------------------

: "${PIPELINE_STATE_DIR:=.pipeline}"
: "${PIPELINE_DOCS_DIR:=docs}"
: "${PIPELINE_LOG_LEVEL:=info}"   # debug | info | warn | error
