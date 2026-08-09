# Architecture: <feature name>

**Status:** draft | under review | approved
**PRD:** <path>
**Review rounds:** <links to docs/architecture/review-round-N.md>

## Summary

Three sentences: what is being built, the shape of the solution, and the one
decision that matters most.

## Context

What already exists that this must fit into. Name the systems, their owners,
and the contracts you are bound by.

## Approach

The design in prose before diagrams. A reader should be able to explain the
system back to you after this section.

## Components

For each component:

### <name>
- **Responsibility:** one sentence. If it needs "and", split the component.
- **Owns:** the state or data it is the single writer for
- **Depends on:** what it calls, and what it does when those calls fail
- **Interface:** the contract other components code against

## Data model

Entities, relationships, and ownership. Include the migration path for data
that already exists — a design that only describes the end state is
incomplete.

## Sequence of the critical path

Walk the most important operation end to end, naming each component in order
and what crosses each boundary.

## Failure modes

| What fails | Detected how | Behaviour | Recovery |
| --- | --- | --- | --- |
| | | | |

Cover at minimum: each external dependency being slow or down, partial writes,
duplicate delivery, and the system restarting mid-operation.

## Security and privacy

Trust boundaries, where authentication and authorisation are enforced, secret
handling, and what appears in logs.

## Observability

The metrics, logs, and traces an on-call engineer would need. State what will
be alerted on and what threshold makes it fire.

## Alternatives considered

| Option | Why not |
| --- | --- |
| | |

The reviewer reads this closely. An architecture with no rejected alternatives
usually means only one was imagined.

## Rollout

How this ships: flags, phases, backfills, and how to turn it off.

## Decomposition notes

Guidance for the bead decomposer — natural seams, shared interfaces that must
land first, and files likely to be contended by parallel agents.
