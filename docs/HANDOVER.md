# Handover — setting this up on a Mac

For a fresh Claude Code session picking this repo up locally. Read this first,
then `README.md` for what the system is and `docs/PIPELINE.md` for how each
phase works.

**Branch:** `claude/agentic-code-orchestration-v8ieaa`

## What exists

A six-phase orchestrated build pipeline: PRD → architecture → independent
architecture review → bead decomposition → parallel swarm (≤5 implementers,
one bead each) → integration. Claude Code orchestrates; `bd` holds the work
graph; `herdr` runs each implementer in its own pane.

```
orchestrator/bin/     doctor, review-arch, decompose, swarm, status, test-swarm
orchestrator/lib/     bd + agent adapters, worktrees, validation, locking, logging
orchestrator/prompts/ implementer, arch-reviewer, decomposer
.claude/skills/agentic-pipeline/   the orchestrator's playbook
pipeline.config.sh    all configuration
```

**Status:** the orchestration loop is written and tested (23 assertions, all
passing, no LLM or network needed). It has **never run against a real `bd`, a
real `herdr`, or a real Claude implementer** — it was built in a Linux
container where none of those were installed. Your first job is to close that
gap. The section on unverified assumptions below tells you exactly where the
risk is.

## Install

Everything except `bd` is one Homebrew line each.

```bash
brew install bash          # REQUIRED — see below
brew install jq
brew install coreutils     # optional; provides gtimeout
brew install herdr
```

### bash 4+ is not optional

macOS ships bash 3.2 from 2007 as `/bin/bash`. This code uses associative
arrays and other bash 4 features, so it cannot run on it. The scripts use
`#!/usr/bin/env bash`, so once Homebrew's bash is ahead of `/usr/bin` in
`PATH` everything resolves correctly — no shebang edits.

```bash
brew install bash
bash --version          # must report 5.x
```

If it still reports 3.2, Homebrew's bin directory is not early enough in
`PATH`. On Apple Silicon add `export PATH="/opt/homebrew/bin:$PATH"` to your
shell profile; on Intel it is `/usr/local/bin`.

`orchestrator/lib/config.sh` fails immediately with this instruction rather
than emitting a hundred syntax errors, so a wrong bash is obvious.

### What the Mac does *not* need

`flock` and GNU `timeout` do not exist on macOS. Rather than making you install
coreutils, the pipeline provides both itself:

- **Locking** is `mkdir`-based (atomic everywhere), with reclamation of locks
  left behind by a killed orchestrator.
- **Timeouts** use `timeout`, else `gtimeout`, else a built-in watchdog. The
  watchdog exits 143 instead of coreutils' 124; nothing depends on the
  distinction.

Both are directly covered by the test suite.

### beads

You said you have an existing `bd` setup. Confirm it is on `PATH` and that this
repo is initialised:

```bash
bd --version
bd init            # only if this repo has no bd database yet
bd ready           # should not error
```

If your `bd` lives somewhere unusual, set `BD_BIN=/path/to/bd`.

### herdr

```bash
brew install herdr
herdr                  # starts the server and drops you into a pane
```

`herdr` is a terminal multiplexer with a server: agents survive you closing the
window. **Run the pipeline from inside a herdr pane** — the CLI talks to the
server over a local socket, and `doctor.sh` will tell you if it cannot reach
it.

Useful keys: `ctrl+b` then `shift+n` new workspace, `ctrl+b` then `v` or `-`
split, `ctrl+b` then `w` switch workspace. `herdr server stop` kills the server
and every pane it owns.

## Verify before running anything

```bash
orchestrator/bin/doctor.sh        # environment + probes bd and herdr surfaces
orchestrator/bin/test-swarm.sh    # 23 assertions, ~40s, touches nothing real
```

`doctor.sh` is not decorative — it probes the exact `bd` and `herdr`
subcommands the adapters call and names the file to fix when one is missing.
Get it to zero problems before phase 5.

`test-swarm.sh` runs the entire loop in a scratch clone using a fake `bd` and
fake agents. If it passes, the orchestration logic is sound and any remaining
failure is an integration mismatch with the real tools.

## Configure

```bash
cp pipeline.config.sh pipeline.config.local.sh   # gitignored, overrides the default
```

Set the validation gates for whatever project you point this at:

```bash
PIPELINE_TEST_CMD='npm test'
PIPELINE_LINT_CMD='npm run lint'
PIPELINE_BUILD_CMD='npm run build'
PIPELINE_INSTALL_CMD='npm ci'
```

**Set `PIPELINE_TEST_CMD` before the first real run.** With no test gate,
validation accepts any bead whose agent wrote a well-formed completion report,
which removes the main defence against an agent that believes it succeeded.

Also worth setting: `PIPELINE_BASE_BRANCH` (defaults to `main`) and
`PIPELINE_MAX_AGENTS` (defaults to 5).

## First run

Start conservatively. The loop has never driven a real agent, so shrink the
blast radius before trusting it with five.

```bash
# 1. Environment is sane
orchestrator/bin/doctor.sh

# 2. Exercise one real implementer against one real bead
PIPELINE_MAX_AGENTS=1 orchestrator/bin/swarm.sh --once

# 3. Watch it: attach to the pane herdr created, or from another terminal
orchestrator/bin/status.sh
```

What to confirm on that first bead, in order — each is a different adapter:

1. A pane appears and Claude starts in it (`agent start` + `agent send`).
2. `status.sh` shows the agent as `working` (`_herdr_status`).
3. The agent writes `.pipeline/reports/<bead>.json` (the prompt contract).
4. Validation runs your gates in the bead's worktree, not the main checkout.
5. The bead lands as exactly one merge commit on `pipeline/integration`.
6. The pane closes (`pane close` — the part I am least sure of).

Then raise `PIPELINE_MAX_AGENTS` to 5 and run the full pipeline through the
`agentic-pipeline` skill.

## Unverified assumptions — where this will break first

Every call to `bd` and `herdr` is confined to two files, deliberately, because
both tools move fast and I could not test against either.

### `orchestrator/lib/agents.sh` — herdr

Built against the published CLI reference. What it relies on:

| Call | Confidence |
| --- | --- |
| `herdr agent start <name> --cwd P --split right --no-focus -- claude` | documented; falls back if `--no-focus` is rejected |
| `herdr agent send <name> <text>` | documented |
| `herdr agent read <name> --source recent --lines N` | documented |
| `herdr agent get <name>` → status, pane id | documented; **JSON envelope is not** |
| `herdr pane close <pane_id>` | documented |

Two things to know:

- **There is no `herdr agent stop`.** Agents are panes, so stopping one means
  resolving it to its pane id and closing that. If pane resolution fails, dead
  panes accumulate — one per bead, five per cycle.
- **The JSON envelope is undocumented.** `_herdr_status` searches the response
  for the first object carrying a status rather than hard-coding a path, and
  falls back to scraping plain text. It is defensive, not verified.

First thing to run on the Mac:

```bash
herdr agent --help
herdr pane --help
herdr agent get <some-agent>     # look at the actual JSON shape
```

If the shape differs, fix `_herdr_status` and `_herdr_stop`. Nothing else
touches herdr.

### `orchestrator/lib/beads.sh` — bd

`bd`'s JSON envelope has shifted across releases, so `_bd_unwrap_list` accepts
bare arrays, `{issues:[…]}`, `{data:[…]}` and `{results:[…]}`, and
`_bd_normalise` reduces each bead to the seven fields the loop needs. Adjust
those two functions if your `bd` disagrees; `doctor.sh` checks this
automatically when at least one bead is ready.

The loop calls: `ready`, `show`, `list`, `update --claim`, `update --status`,
`close`, `comment`, and `dep add` (decomposer only). `update --claim` must be
atomic — it is what stops two orchestrators taking the same bead.

## What is actually tested

23 assertions in `test-swarm.sh`, all against mocks:

- portable locking (mutual exclusion, stale-lock reclamation) and the timeout
  watchdog
- dependency-ordered scheduling and the concurrency ceiling
- worktree isolation; a dependent bead builds on top of its dependency
- the validation gate, including the documentation requirement
- retry-with-feedback, then park-as-blocked after N attempts
- serialised merges, one revertable merge commit per bead, failed beads
  excluded
- merge-conflict detection, routing back to the agent, and recovery
- the headless backend, including that a retry carries the original task

Building these caught five real bugs, the last of which is worth knowing about
because it is the kind of thing that would have looked like model flakiness:
in headless mode the agent's prompt was read by the forked child of an
asynchronous command while the caller deleted the temp file, so retries
intermittently started with an **empty prompt**.

**Not tested:** anything involving a real `bd`, a real `herdr`, or a real
Claude implementer. That is your first run, and it is why step 2 above uses
`--max 1 --once`.

## Deliberate deviation from the original spec

The original process was: validate → sub-agent updates documentation → merge.

Implemented instead: documentation is part of the bead, and the validator
rejects a bead that changed no documentation. One pass rather than a round
trip, and the docs describe code that has actually passed its gates by the time
anything merges. If you want the original ordering it is a second state in the
reap loop in `orchestrator/bin/swarm.sh` — not hard, but it was not what got
built.

## Operating notes

- **Blocked beads need a human.** The swarm parks them, keeps their worktree
  for inspection, and moves on. Nothing retries them on the next run until you
  reopen them: `bd update <id> --status open`.
- **Throughput is bounded by graph width**, not by `PIPELINE_MAX_AGENTS`. A
  serial dependency chain runs one agent at a time whatever the ceiling says.
- **Beads that edit the same file will conflict.** The swarm recovers, but a
  decomposition that ignores file overlap spends its time on merge retries.
  Fix it in phase 4 by adding dependency edges, not in phase 5.
- **Interrupting is safe.** SIGINT stops the agents and releases their claims
  so a rerun picks them up.
- **`.pipeline/`** holds run logs, completion reports, rendered prompts and
  review sandboxes. Gitignored. It is the first place to look when something
  goes wrong; `.pipeline/runs/*.agent.log` has the agent's own output.

## Kicking off in the new session

```
Read docs/HANDOVER.md, then run orchestrator/bin/doctor.sh and
orchestrator/bin/test-swarm.sh and tell me what needs fixing before
we can do a real run.
```
