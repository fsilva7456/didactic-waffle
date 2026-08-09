# Agentic build pipeline

An orchestrated process for building software with Claude Code: a PRD becomes
an architecture, an isolated reviewer attacks that architecture, the approved
design becomes a dependency graph of beads, and a swarm of up to five
implementation agents drains the graph one bead at a time while the
orchestrator validates and merges every result.

```
1 PRD ──▶ 2 Architecture ──▶ 3 Independent review ──┐
                    ▲                               │ changes requested
                    └───────────────────────────────┘
                                 approved
                                    │
                    4 Bead decomposition ──▶ 5 Swarm (≤5 agents) ──▶ 6 Integration
                                                 ▲            │
                                                 └── loop ────┘
```

Claude Code is the orchestrator. [beads](https://github.com/steveyegge/beads)
(`bd`) holds the work graph. [herdr](https://herdr.dev) runs each
implementation agent in its own observable pane.

## Why it is shaped this way

Three decisions carry most of the weight:

**Every bead gets its own git worktree.** Five agents editing one checkout
would trample each other constantly. Isolated worktrees on isolated branches
mean parallel edits, test runs, and build artifacts cannot collide, and the
orchestrator merges them back serially so conflicts surface one at a time
instead of as a pile-up at the end.

**A completion report is a claim, not evidence.** Agents are convincing about
finishing work they did not finish. Nothing merges until the orchestrator runs
the configured gates against the bead's own worktree and confirms the docs were
updated. Failures go back to the same agent with the specific errors attached.

**The architecture reviewer is genuinely isolated.** It runs in a sandbox
holding only the PRD and the design document — no codebase, no git history,
none of the reasoning that produced the design. A reviewer that watched a
design evolve will accept reasoning it should be attacking.

## Requirements

| | |
| --- | --- |
| bash 4+, git, jq, flock, timeout | worktrees, JSON, locking |
| [`bd`](https://github.com/steveyegge/beads) | the bead graph |
| [`herdr`](https://herdr.dev) | agent panes (optional — see backends) |
| `claude` | the agents themselves |

```bash
orchestrator/bin/doctor.sh    # checks all of the above, plus your config
```

`doctor.sh` also probes the `bd` and `herdr` command surfaces this repo was
written against. Both tools move fast; when a probe fails, the fix belongs in
`orchestrator/lib/beads.sh` or `orchestrator/lib/agents.sh`, which is where
every call to them lives.

## Quick start

```bash
bd init                                  # once per project
cp pipeline.config.sh pipeline.config.local.sh   # set your test/lint commands
orchestrator/bin/doctor.sh
```

Then, in Claude Code:

```
Run the agentic pipeline for <your feature>
```

That invokes the `agentic-pipeline` skill, which drives all six phases and
holds the gates between them. To run a single phase, ask for it directly —
"review this architecture", "decompose this into beads", "launch the swarm".

## Running phases by hand

```bash
orchestrator/bin/review-arch.sh --arch docs/architecture/current.md --round 1
orchestrator/bin/decompose.sh  --arch docs/architecture/current.md
orchestrator/bin/swarm.sh --dry-run     # what would dispatch next
orchestrator/bin/swarm.sh               # run until the graph is drained
orchestrator/bin/status.sh              # from another terminal, mid-run
```

`review-arch.sh` exits `0` approved, `3` changes requested. `swarm.sh` exits
non-zero if any bead was parked as blocked.

## Configuration

Everything lives in `pipeline.config.sh`; override in a gitignored
`pipeline.config.local.sh` or via the environment. The settings that matter
most:

| | |
| --- | --- |
| `PIPELINE_MAX_AGENTS` | concurrent implementers (default 5) |
| `PIPELINE_TEST_CMD` / `LINT` / `BUILD` / `INSTALL` | the validation gates |
| `PIPELINE_MAX_ATTEMPTS` | retries before a bead is parked (default 3) |
| `PIPELINE_AGENT_MODE` | `herdr` \| `headless` \| `mock` |
| `PIPELINE_REQUIRE_DOCS` | reject beads that changed no documentation |

**Set `PIPELINE_TEST_CMD`.** With no test gate, validation accepts any bead
whose agent wrote a well-formed report.

### Agent backends

- **`herdr`** (default) — each implementer gets a pane you can attach to and
  watch. What you want interactively.
- **`headless`** — `claude -p` in a background process. For CI, or if you
  don't run herdr.
- **`mock`** — a scripted fake implementer that honours the same contract.
  Used by the test suite.

## Tests

```bash
orchestrator/bin/test-swarm.sh
```

Runs the whole loop against mock beads and mock agents in a scratch clone:
dependency-ordered scheduling, the concurrency ceiling, worktree isolation, the
validation gate, retry-then-block, serialised merges, and conflict recovery.
Your repository is never touched.

## Layout

```
orchestrator/
  bin/     doctor, review-arch, decompose, swarm, status, test-swarm
  lib/     beads + agent adapters, worktrees, validation, logging
  prompts/ implementer, arch-reviewer, decomposer
  templates/ prd, architecture
.claude/
  skills/agentic-pipeline/   the orchestrator's playbook
  agents/                    in-session reviewer and decomposer
docs/PIPELINE.md             the process in detail
.pipeline/                   run logs, reports, prompts (gitignored)
```

## Limits worth knowing

- Beads that edit the same files still conflict. The decomposer is told to
  avoid it and the swarm recovers when it happens, but a decomposition that
  ignores file overlap will spend its time on merge retries.
- Blocked beads need a human. The swarm parks them and keeps going by design;
  nothing retries them on the next run until you reopen them.
- Wall-clock throughput is bounded by the width of the dependency graph, not
  by `PIPELINE_MAX_AGENTS`. A serial graph runs one agent at a time no matter
  what the ceiling says.
