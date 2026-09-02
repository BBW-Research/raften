# AGENTS.md

## Repository map

- Start with the [documentation index](docs/index.md).
- The product contract is `docs/specs/repo-context.md`.
- The completed executable build sequence is `docs/plans/completed/standalone-tool.md`.
- The completed Codex assignment is retained in `docs/prompts/codex-build.md`.
- Architecture boundaries are summarized in `ARCHITECTURE.md` and expanded under `docs/architecture/`.
- The scene-maker source snapshot and known limitations are documented under `docs/reference/` and `reference/scene-maker/`.

## Authority

1. Explicit user instructions.
2. This file.
3. The product spec and accepted decisions.
4. The active implementation plan.
5. Existing code and tests.

When lower-authority material conflicts with a higher-authority contract, preserve the higher-authority contract and update the stale material in the same change.

## Default workflow

1. Read the relevant spec, decision records, implementation plan or completion evidence, and source characterization before editing.
2. For follow-up work, read the completed plan and relevant evidence, then create a focused active plan only when phased execution is warranted.
3. Add or tighten tests before refactoring behavior inherited from scene-maker.
4. Make the smallest coherent change that closes the phase acceptance gate.
5. Run `scripts/validate` before claiming completion.
6. Update the active plan with completed work, remaining work, and newly discovered risks.

## Durable invariants

- The final CLI is harness-neutral, deterministic, local-first, and usable without network access.
- Runtime dependencies remain standard-library-only unless an accepted decision documents why a dependency is necessary.
- Do not hard-wrap Markdown prose.
- All diagnostics are stable, sorted, and testable. Human-readable wording may improve without changing diagnostic identity.
- Git-visible authored text is governed by default. Generated, vendored, lock, fixture, and legal material must be classified explicitly rather than hidden behind broad exclusions.
- Policy limits may tighten but must not silently weaken relative to a configured base revision.
- `tools/check_repository_policy.py` is the frozen test oracle copied from scene-maker. Do not edit it; production behavior belongs in `src/repo_context/`.
- Never add project-specific exemptions to shared engine code.
- Keep every authored code and documentation file below the repository policy ceiling. Split by responsibility, not merely to satisfy byte counts.

## Validation

- Full local validation: `scripts/validate`.
- Tests only: `scripts/test`.
- Bootstrap a freshly unpacked archive: `scripts/bootstrap`.
- Self-hosted policy check: `scripts/context-check`.
- Target CLI smoke test: `PYTHONPATH=src python3 -m repo_context --help`.

## Subagents

- Use explorer and reviewer agents for parallel read-only work.
- Do not run multiple writing agents against the same working tree.
- A reviewer should inspect each completed implementation phase before the next phase begins.
