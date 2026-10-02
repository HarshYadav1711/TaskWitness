# TaskWitness — Design

## Design principle

Operational clarity with technical precision.

## Desired character

Calm, precise, professional, evidence-oriented, human-controlled, functional, intentionally designed. Dense enough to be useful; never visually noisy.

## Avoid

Glassmorphism; neon/glow; generic purple AI gradients; large marketing heroes; animated blobs; meaningless animation; random KPI cards; AI sparkle iconography; robot artwork; excessive pills; excessive rounded cards; chat-interface-first layouts; generic AI SaaS aesthetics; decorative elements without operational meaning.

## Implemented operator layout (Phase 7)

```
HEADER
  TaskWitness wordmark | run state | Pause / Resume

OPTIONAL BANNER
  Validated Plan Demo Mode (development only)

LEFT
  Business goal textarea
  controlled source (candidates.csv, read-only)
  Run / Start validated plan
  clarification / config error
  run metadata (run id, journal id, mode)

MAIN
  Execution trace (primary focus)
  current step summary

BOTTOM
  Execution vs Verification summaries (separate)
  postcondition checks by candidate
  incomplete work (first-class)
  evidence package path
```

Dark header strip, warm paper surfaces, system fonts, 3px radius, sparse borders. Status uses text labels plus restrained color (never color alone).

## Approval UI

Modal dialog (`role="dialog"`, `aria-modal`):

- exact action, candidate, target, reason, optional operation ID;
- **Reject** (receives initial focus);
- **Approve and continue**;
- server-enforced one-time resolve (no Enter-to-approve shortcut).

## Run states

`ready` · `planning` · `running` · `paused` · `awaiting_approval` · `verifying` · `recovering` · `completed` · `partial` · `failed`

Verification shown separately after execution:

- **verified** / **incomplete** / **failed** / **blocked**
- postcondition counts
- “Goal verified” only when `verified_complete=true`

## Synthetic applications (Phase 1)

TalentDesk and TeamMail are **business apps being operated**, not the TaskWitness control surface.

- Shared restrained base stylesheet; distinct header accent only (green-leaning ATS vs slate mailbox).
- Dense tables, explicit labels, real links/forms—no KPI cards, gradients, or chat-first layouts.
- Stable `id` / `data-testid` only on workflow controls needed for Playwright.
- Drafts list exposes **Operation ID** so browser automation can locate logical follow-ups without database access.
