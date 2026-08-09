# The pipeline in detail

Reference for what each phase does, what state it reads and writes, and why
the mechanisms are built the way they are. For the operator's playbook see
`.claude/skills/agentic-pipeline/SKILL.md`; for setup see the README.

## State

The pipeline keeps almost nothing of its own. Beads are the state, which is
what makes every phase resumable: re-running the swarm picks up wherever the
graph is.

| Location | Contents | Lifetime |
| --- | --- | --- |
| `bd` database | the work graph, statuses, comments | the project |
| `docs/prd/`, `docs/architecture/` | PRD, design, review rounds | committed |
| `pipeline/integration` branch | landed beads, one merge commit each | until merged out |
| `bead/<id>` branches | one implementer's work | deleted on land |
| `.pipeline/reports/<id>.json` | completion reports | run |
| `.pipeline/runs/` | run logs, event streams, agent output | run |
| `$PIPELINE_WORKTREE_ROOT/<id>` | per-bead checkouts | deleted on land, kept on block |

`.pipeline/` is gitignored. Worktrees live outside the repo so agent file
globs and test runners never see sibling worktrees.

## Phase 1 — PRD

Interactive, in the main Claude Code session, from
`orchestrator/templates/prd.md`. Output: `docs/prd/<feature>.md`.

The gate is explicit user sign-off. The non-goals section matters more than it
looks — both the reviewer and the decomposer read it as a boundary, and an
empty one produces scope creep in phase 5 that nobody authorised.

## Phase 2 — Architecture

Also in the main session, where the codebase is visible, from
`orchestrator/templates/architecture.md`. Output:
`docs/architecture/current.md`.

Every section gets filled in. The reviewer treats silence as a gap and is
right to: an unstated assumption is exactly what an independent reader cannot
supply for you.

## Phase 3 — Independent review

```bash
orchestrator/bin/review-arch.sh --arch <path> --round N [--prd <path>] [--no-prd]
```

The script builds `.pipeline/review/round-N/` containing `ARCHITECTURE.md`,
`PRD.md`, and — from round 2 — `PRIOR-REVIEW.md`, then starts an agent with
that directory as its entire working context.

The isolation is the mechanism, not a detail. A reviewer with repository access
reconstructs the author's reasoning from the code and starts agreeing with it.
One with only the document can only judge what is written down, which is the
same position every future maintainer will be in.

The PRD is included by default because a reviewer without requirements can only
check the design against itself. `--no-prd` gives a pure principles review.

**Verdict handling.** The script reads the reviewer's stated verdict *and*
counts blocker/major findings, and requires both to agree before it reports
approval. A review that files a blocker and then writes "approved" has
contradicted itself; the safe reading is the blocker.

Exit `0` approved, `3` changes requested, `1` the review did not run.

**The loop.** On changes-requested the orchestrator revises the architecture
and runs round N+1. Each finding is either fixed or rebutted in writing —
a rebuttal is legitimate when the reviewer misread something, but it goes in
the document so round N+1 can see it. Three rounds without approval means the
design has a problem iteration is not fixing; that goes to the user.

## Phase 4 — Decomposition

```bash
orchestrator/bin/decompose.sh --arch <path> [--prd <path>]
```

Runs an agent inside the repository — it needs `bd`, and it needs to see
existing code so it does not file beads for work already done. Output: beads in
`bd`, plus `.pipeline/decomposition.json` summarising the graph.

Bead sizing is the highest-leverage decision in the pipeline. Each bead goes to
an agent that knows nothing about the others, so a bead must be finishable in
one sitting, verifiable by running something, and as free of file overlap with
its siblings as the design allows. Where several beads must agree on a contract,
one bead establishes it and the rest depend on it — that single pattern
prevents most integration failures.

The script fails when nothing is ready (a cycle, or a bad root) and warns when
the ready set is narrower than the agent ceiling.

**Then the orchestrator reviews the graph by hand.** This is the cheapest place
to catch a bad plan and the most expensive one to skip.

## Phase 5 — Swarm

```bash
orchestrator/bin/swarm.sh [--once] [--dry-run] [--max N]
```

Each cycle reaps then dispatches.

**Dispatch** — for each free slot, take the next bead from `bd ready`:
`bd update --claim` it (an atomic claim, so two orchestrators cannot both win),
create `bead/<id>` from the integration branch in a fresh worktree, render the
implementer prompt with the bead's brief, and start the agent.

**Reap** — for each active bead: time it out if over budget; otherwise wait for
`.pipeline/reports/<id>.json`.

The report file is the completion contract, not the agent's terminal state. A
pane going idle only means the agent stopped talking — it may have crashed,
finished, or wandered off. An agent that settles without a report is treated as
a failure, after a grace period for a report still being written.

**Validate** — the gate is the same regardless of how confident the report
sounds: the report parses and says `complete`; the branch has commits; a
documentation path changed; and install, lint, test, and build each pass *in
the bead's own worktree*. Uncommitted leftovers are committed rather than lost.

**Merge** — serialised under a lock, `--no-ff` into `pipeline/integration`, so
every bead lands as exactly one revertable merge commit. Then every other live
worktree is refreshed from the new integration tip, so late finishers do not
drift into avoidable conflicts. A refresh that conflicts is abandoned quietly:
the agent is mid-bead and a conflicted index would corrupt whatever it does
next, and the same conflict gets handled properly at merge time.

**Failure** — feedback goes back to the *same* agent, which still holds the
context, with the specific errors attached. A merge conflict is routed the same
way, since the agent that wrote the code is best placed to resolve it. After
`PIPELINE_MAX_ATTEMPTS` the bead is parked as blocked with the reason attached,
its worktree kept for inspection, and the loop continues — one bad bead must
not stall the graph.

**Interruption** — SIGINT stops the active agents and releases their claims so
a rerun can pick them up.

`swarm.sh` exits non-zero if any bead was blocked.

## Phase 6 — Integration

Beads pass individually and can still break each other, so the full suite runs
against the integration branch as a whole. Parallel agents also produce
duplicated helpers and inconsistent naming; that gets fixed in one pass here
rather than bead by bead. Follow-ups the agents recorded live in
`.pipeline/reports/*.json`.

## Tuning

| Symptom | Likely cause | Change |
| --- | --- | --- |
| Constant merge conflicts | overlapping beads in one ready set | add dependency edges, or split the contended file |
| Swarm idles under capacity | narrow graph | fine if genuinely serial; otherwise re-decompose |
| Beads blocked on the same gate | gate misconfigured | `doctor.sh` |
| Agents drift out of scope | bead scope too vague | list what the bead must NOT touch |
| A bead fails identically every attempt | the bead is wrong, not the agent | rewrite the bead |

Raising `PIPELINE_MAX_AGENTS` past about 8 usually buys more conflicts than
throughput. Throughput is bounded by graph width anyway.
