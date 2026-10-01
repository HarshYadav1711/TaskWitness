# TaskWitness — Rules

## SOURCE OF TRUTH

Before implementation work, read in order:

1. `docs/PROJECT_CONTEXT.md`
2. `docs/RULES.md`
3. `docs/PRD.md`
4. `docs/ARCHITECTURE.md`
5. `docs/DESIGN.md`
6. `docs/PHASES.md`

Document authority order (highest first): HulChul assessment → PROJECT_CONTEXT → RULES → PRD → ARCHITECTURE → DESIGN → PHASES → current approved phase instruction.

Conflict with a higher document → **STOP**. Do not resolve unilaterally.

## SCOPE

- Implement only the approved phase.
- Do not implement future-phase functionality early.
- Do not add nice-to-have features.
- Do not broaden product scope autonomously.

## ARCHITECTURE

Do not change without explicit review:

- component responsibilities;
- architecture boundaries;
- storage strategy;
- authority semantics;
- execution semantics;
- verification semantics.

## DEPENDENCIES

- Every dependency must solve a current requirement.
- Prefer the standard library when reasonable.
- Use current stable, maintained versions.
- No abandoned/deprecated packages.
- No prerelease without explicit approval.
- No paid API required for basic evaluation.
- No service requiring credit-card billing for core behavior.
- Do not introduce frameworks for resume value.

## AI BOUNDARIES

- LLM output is untrusted.
- LLM may interpret intent.
- LLM may not prove success.
- LLM may not bypass authority.
- LLM may not create arbitrary executable browser commands.
- LLM may not invent capabilities.

## COMPUTER OPERATION

- When visible browser interaction is required, do not secretly mutate target-app state through private APIs to simulate successful UI operation.
- Test/setup APIs may be used only when explicitly documented and not as a substitute for demonstrated browser work.

## SIDE EFFECTS

- Future effectful operations must be explicitly represented.
- Unknown action outcomes must be verified before retrying.
- Duplicate effects are unacceptable.

## VERIFICATION

- Function return without exception is not proof of business success.
- Success requires defined postconditions.

## CLAIMS

Never fabricate performance metrics, reliability percentages, benchmarks, test results, customer/user statistics, production usage, or unsupported capabilities.

## DATA

- Synthetic data only.
- Use `example.test` for synthetic emails.
- Never imply synthetic data is real.

## SECURITY

- No credentials in the repository.
- Secrets belong in environment variables.
- `.env` must be ignored.
- `.env.example` may contain only placeholders.

## DESIGN

- Do not replace deliberate design with generic AI-generated SaaS patterns.
- Every visible element must have an operational reason.
- Do not add decorative UI merely for polish.

## TESTING

- Never say tests pass unless executed.
- Always report exact test command and results.
- Tests must verify behavior, not implementation trivia.

## CODE QUALITY

- Prefer small explicit modules.
- No unnecessary base classes.
- No speculative abstraction.
- No generic agent framework.
- No excessive comments.
- Use names that match domain concepts.
- Type public/domain-facing interfaces sensibly.
- Avoid overengineering.

## CHANGE CONTROL

**STOP** and request review before changing:

- project scope;
- architecture;
- dependencies beyond the current phase;
- authority semantics;
- verification semantics;
- recovery strategy;
- design system;
- assessment interpretation.
