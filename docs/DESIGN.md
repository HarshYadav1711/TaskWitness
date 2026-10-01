# TaskWitness — Design

## Design principle

Operational clarity with technical precision.

## Desired character

Calm, precise, professional, evidence-oriented, human-controlled, functional, intentionally designed. Dense enough to be useful; never visually noisy.

## Avoid

Glassmorphism; neon/glow; generic purple AI gradients; large marketing heroes; animated blobs; meaningless animation; random KPI cards; AI sparkle iconography; robot artwork; excessive pills; excessive rounded cards; chat-interface-first layouts; generic AI SaaS aesthetics; decorative elements without operational meaning.

## Planned layout

```
HEADER
  TaskWitness | run state | pause/resume

LEFT
  plain-English goal
  selected source
  run control

MAIN
  execution trace (primary focus)
  current step
  completed / failed / recovering steps

BOTTOM OR SIDE
  evidence count
  verification / postcondition status
```

The execution trace is the main visual focus.

## Approval UI

Must show:

- exact action;
- target / recipient;
- why approval is required;
- **Reject**;
- **Approve and continue**.

## Run states (eventual UI)

`ready` · `planning` · `running` · `paused` · `awaiting_approval` · `verifying` · `recovering` · `completed` · `partial` · `failed`

## Phase 0 note

No visual identity lock-in yet. No elaborate design tokens. Room remains for deliberate refinement in the UI phase (Phase 7). Do not invent decorative polish ahead of operational need.
