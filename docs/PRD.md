# TaskWitness — Product Requirements

## Problem

Recruiting operators need to carry out multi-step work across business apps (ATS + mail) without handing the computer unrestricted autonomous control, and without treating model output as proof of success.

## Product goal

Provide an evidence-first operator that interprets a recruiting goal, executes only authorized deterministic steps across synthetic apps, pauses for human decisions when authority is exceeded, verifies outcomes independently, and makes progress and incomplete work visible.

## Target user

A technical evaluator / operator who can run a local controlled environment, issue a plain-English goal, watch application interaction, approve or deny gated actions, and inspect evidence.

## Primary business workflow

Synthetic recruiting ops: filter candidates from CSV, update TalentDesk stages when authorized, prepare TeamMail follow-ups, gate sends on authority, verify resulting state.

## Primary user story

As an operator, I want to describe a recruiting task in natural language so that TaskWitness can carry out the authorized work across business applications while keeping me informed and asking for approval before exceeding my authority.

## Functional requirements

- Accept a plain-English company/business goal.
- Convert intent into a typed validated task plan (`TaskSpec`).
- Operate TalentDesk and TeamMail through visible interaction in a controlled environment.
- Support goal variation without source-code changes.
- Pause execution on request.
- Seek approval before actions that exceed granted authority.
- Handle ambiguous/interrupted side effects without duplicate retries.
- Independently verify application state and artifacts.
- Produce evidence of resulting state.
- Expose incomplete work via an explicit `PARTIAL` outcome when appropriate.

## Base scenario

From `candidates.csv`, process shortlisted AI Engineering candidates in TalentDesk. Prepare an interview follow-up, move each matching candidate to Interview Ready, and ask before sending any message.

## Variation scenario

Process shortlisted Backend Engineering candidates from `candidates.csv`. Prepare follow-ups only. Do not send messages and do not change candidate stages. Same codebase; different goal/input only.

## Failure/recovery scenario

Ambiguous send: Send is clicked, message is persisted, acknowledgement is interrupted. Operator must not immediately retry Send; must inspect TeamMail state, detect the existing message, suppress duplicate send, and record successful recovery.

## Human-control requirements

- Pause / resume.
- Approval UI before exceeding authority (exact action, target, reason; Reject / Approve and continue).
- Authority separate from requested actions.
- Denied approval → keep completed work visible; prefer `PARTIAL` over false `FAILED` when appropriate.

## Verification requirements

- Defined postconditions, not "no exception".
- Independent of LLM claims.
- Unknown outcomes verified against target app state before retry.

## Evidence requirements

- Evidence that requested authorized work completed (or why it did not).
- Incomplete work visible.
- Progress visible during execution.

## Non-functional requirements

- Understandable enough to defend in a technical interview.
- Reliable within a controlled synthetic environment.
- Minimal dependencies; no paid API required for basic evaluation.
- Time-boxed prototype quality over breadth.

## Non-goals

General-purpose computer-use framework; production ATS/email integrations; multi-agent stacks; cloud deployment; analytics dashboards; real PII or real outbound email.

## Acceptance criteria

Future end-to-end acceptance (not Phase 0) requires:

1. Actual visible application operation for the base recruiting workflow.
2. Variation via goal/input change only—no source edits.
3. Meaningful failure recovery for ambiguous send.
4. No duplicate side effect during recovery.
5. Pause and resume.
6. Approval before exceeding authority.
7. Independently verified completion.
8. Explicit `PARTIAL` for incomplete authorized work.
9. Evidence generated for resulting application state/artifacts.
