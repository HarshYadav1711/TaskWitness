# TaskWitness — Project Context

## Project

TaskWitness is an evidence-first, human-controlled computer operator built for a time-boxed HulChul AI Engineering internship assessment.

It is not a general-purpose computer-use framework.

## Assessment goal

Build a small working operator that:

- accepts a plain-English business goal;
- operates applications in a controlled test environment;
- completes a meaningful multi-step recruiting workflow;
- shows real application interaction;
- supports goal variation without source changes;
- handles a meaningful interruption/failure safely;
- independently verifies resulting state;
- produces evidence of completion;
- keeps incomplete work visible;
- shows progress;
- allows pause;
- seeks approval when an action exceeds granted authority.

## Selected workflow

Synthetic recruiting operations:

1. Read candidate input from `candidates.csv`.
2. Operate TalentDesk (synthetic ATS) to inspect and update pipeline stages.
3. Operate TeamMail (synthetic mailbox) to prepare follow-ups and optionally send.
4. Pause for approval when autonomous send authority is absent.
5. Verify outcomes and produce evidence.

## Controlled applications

| Application | Role |
|---|---|
| TalentDesk | Synthetic ATS with fictional candidates and stage changes |
| TeamMail | Synthetic mailbox for drafts and synthetic sends |
| candidates.csv | Synthetic candidate input |

No real candidate data. No real email. No production service in the core assessment path.

## Core product principle

**AI interprets intent. Deterministic software performs side effects. Independent verification determines completion.**

- The LLM must never be treated as proof that an action succeeded.
- The LLM must never receive unrestricted browser control.
- Natural-language goals become a typed, validated `TaskSpec`.
- Deterministic code executes only permitted operations.
- Postconditions independently decide whether work completed.

Additional invariants:

- "No exception" is not success.
- Side effects must eventually be journalled.
- Unknown outcomes must be verified before retry.
- The implementation must stay explainable in a technical interview.

## Required demonstrations

1. **Base workflow** — shortlisted AI Engineering candidates: prepare follow-up, set stage, ask before send.
2. **Variation** — shortlisted Backend Engineering candidates: prepare follow-ups only; no send; no stage change. No source changes.
3. **Failure/recovery** — ambiguous send acknowledgement: inspect app state, suppress duplicate retry, record recovery.

## Human authority model

Authority is separate from requested actions.

Example: `actions` may include `send_message` while `authority.send_message = false`. Sending is not impossible; autonomous sending is not authorized. Execution must await human approval before that side effect. Denied approval leaves completed work visible and may yield `PARTIAL`, not a false `FAILED`.

## Verification philosophy

Completion is decided by independent postconditions against application state and artifacts, not by model claims or by a side-effect call returning without exception.

## Synthetic-data policy

All candidates, emails, and messages are fictional. Use `example.test` for synthetic email addresses. Never imply synthetic data is real.

## Time-box

Optimize for a strong, understandable, reliable prototype—not maximum feature count.

## Current implementation status

**Phase 5 complete — durable journal and safe recovery.**

Effectful workflow actions are write-ahead journaled locally. Ambiguous send acknowledgements are classified `UNKNOWN`, reconciled against visible TeamMail Sent state by stable `operation_id`, and recovered without blind retry. Independent goal verification / evidence packs and the final operator UI are not implemented yet.

## Explicitly out of scope

LangChain, LangGraph, RAG, embeddings, vector DBs, multi-agent systems, autonomous browser-agent frameworks, Redis, Celery, Docker, Kubernetes, React, Next.js, auth/accounts, real Gmail/Outlook, LinkedIn automation, production ATS/Slack/calendar integrations, OCR, voice, analytics dashboards, cloud deployment, production monitoring/telemetry, external databases, paid APIs required for basic evaluation.

## Source-of-truth hierarchy

1. Original HulChul assessment requirements
2. `docs/PROJECT_CONTEXT.md`
3. `docs/RULES.md`
4. `docs/PRD.md`
5. `docs/ARCHITECTURE.md`
6. `docs/DESIGN.md`
7. `docs/PHASES.md`
8. Current approved phase instruction

If a lower-level instruction conflicts with a higher-level document: **STOP**. Do not resolve the conflict unilaterally.
