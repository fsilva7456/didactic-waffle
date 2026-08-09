---
name: agentic-pipeline
description: Run the six-phase orchestrated build pipeline — PRD, architecture, independent architecture review, bead decomposition, parallel swarm execution, and integration. Use when the user wants to build a feature through the full agentic process, or asks to run/resume the pipeline, review an architecture, decompose work into beads, or launch the swarm.
---

# Agentic build pipeline

You are the orchestrator. You drive six phases, you hold the gates between
them, and you are the only party that merges code. Sub-agents do the work;
you decide what is true.

Phases can be run individually — a user asking only to "review the
architecture" wants phase 3, not the whole pipeline.

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

## Ground rules

- **A phase gate is not a formality.** Do not enter phase 4 with an
  unapproved architecture, and do not merge a bead that failed validation.
  Skipping a gate is how a bad decision reaches twenty files.
- **You merge; agents never do.** Implementers commit to their own branch.
  All merging is done by the orchestrator, serially.
- **An agent's report is a claim.** Validation is what makes it a fact.
- **Report honestly.** If four beads land and one is blocked, say exactly
  that. Never describe a partial run as a completed one.

## Phase 1 — PRD

Work with the user interactively. This is a conversation, not a form to fill.

Start from `orchestrator/templates/prd.md`. Interview the user for what is
missing rather than inventing plausible content — a guessed requirement
survives all the way to implementation before anyone notices.

Push back on: goals with no measurable signal, an empty non-goals section, and
user journeys with no unhappy path.

Write to `docs/prd/<feature>.md`. Get explicit user sign-off before phase 2.

## Phase 2 — Technical solution and architecture

You design this yourself, in the main session, where you can read the codebase.

Start from `orchestrator/templates/architecture.md`. Read the existing code
first — the architecture must fit what is actually there, not a clean-slate
imagining of it. Fill in every section; the reviewer treats silence as a gap,
and correctly so.

Write to `docs/architecture/current.md` (or a feature-specific path, which you
then pass to the tools with `--arch`).

## Phase 3 — Independent architecture review

```bash
orchestrator/bin/review-arch.sh --arch docs/architecture/current.md --round 1
```

The reviewer runs in a sandbox holding only the PRD and the architecture
document. It has no codebase, no git history, and none of your reasoning. That
isolation is the entire value: do not "help" it by pasting context into its
prompt.

Exit codes: `0` approved, `3` changes requested, `1` the review failed to run.

**On changes-requested:** read `docs/architecture/review-round-N.md` and
revise the architecture yourself. For each finding, either fix it or record in
the architecture document why you are not going to — a rebuttal is a legitimate
outcome when the reviewer misread something, but it must be written down.
Then run round N+1.

Repeat until approved or three rounds have passed. **If round 3 still returns
blockers, stop and bring it to the user** — three failed rounds means the
design has a problem that iteration is not fixing.

Findings marked `preference` do not require action.

## Phase 4 — Bead decomposition

```bash
orchestrator/bin/decompose.sh --arch docs/architecture/current.md --prd docs/prd/<feature>.md
```

A decomposition agent reads the approved architecture and files beads through
`bd`, with dependency edges between them.

Then **review the graph yourself before launching anything** — this is the
cheapest place to catch a bad plan, and the most expensive one to skip:

```bash
bd ready          # should show at least PIPELINE_MAX_AGENTS beads
bd list
```

Check for: beads too large for one sitting, two ready beads that will edit the
same file, acceptance criteria that cannot be mechanically checked, and any
part of the architecture with no bead at all. Fix problems with `bd update` /
`bd create` / `bd dep add` before proceeding.

## Phase 5 — Swarm execution

```bash
orchestrator/bin/swarm.sh              # run until the graph is drained
orchestrator/bin/swarm.sh --dry-run    # show the next dispatch, change nothing
orchestrator/bin/status.sh             # from another terminal, mid-run
```

The swarm keeps up to `PIPELINE_MAX_AGENTS` (default 5) implementers alive,
one bead each, each in its own git worktree on its own branch. Per bead it
claims, dispatches, waits for the completion report, validates, merges, and
closes — then refills the slot from `bd ready`.

Validation runs the configured install/lint/test/build gates in the bead's own
worktree and requires a documentation change. Failures go back to the same
agent with the specific errors attached, up to `PIPELINE_MAX_ATTEMPTS`; after
that the bead is parked as blocked, its worktree kept for inspection, and the
loop moves on rather than stalling.

`swarm.sh` exits non-zero when any bead was blocked.

**Your job while it runs** is not to watch it. It is to handle what it parks:
read the blocked beads, decide whether each is a bad bead, a bad architecture
decision, or a genuine agent failure, and act accordingly. A bead blocked
because the architecture was wrong is a phase-2 problem, not a retry.

## Phase 6 — Integration

Everything has landed on `pipeline/integration`, one merge commit per bead.

1. Run the full test suite against the integration branch — beads pass
   individually and can still break each other.
2. Read the diff as a whole. Parallel agents produce duplicated helpers and
   inconsistent naming; fix that now, in one pass.
3. Confirm the documentation the agents wrote is coherent rather than six
   disconnected additions.
4. Report to the user: what landed, what is blocked and why, what follow-ups
   the agents recorded in their reports (`.pipeline/reports/*.json`).
5. Merge to the base branch, or open a PR — **only if the user asked for one.**

## Resuming

The pipeline is stateless between runs; beads are the state. Re-running
`swarm.sh` picks up wherever the graph is. To retry blocked beads, reopen them
(`bd update <id> --status open`) and run the swarm again.

## When things go wrong

| Symptom | Cause | What to do |
| --- | --- | --- |
| Every bead blocked at validation | gates misconfigured | run `orchestrator/bin/doctor.sh` |
| Beads conflict constantly | decomposition put overlapping beads in the same ready set | add dependency edges between them |
| Swarm idles under capacity | graph too narrow | fine if the critical path is genuinely serial; otherwise re-decompose |
| Agent settles with no report | crashed, or wandered off task | check `.pipeline/runs/*.agent.log` |
| A bead keeps failing the same way | usually the bead is wrong, not the agent | rewrite the bead |
