# AGENTS.md

## Repository map

- Start with the [documentation index](docs/index.md).
- The product contract is `docs/specs/raften.md`.
- The completed executable build sequence is `docs/plans/completed/standalone-tool.md`.
- The completed Codex assignment is retained in `docs/prompts/codex-build.md`.
- Architecture boundaries are summarized in `ARCHITECTURE.md` and expanded under `docs/architecture/`.
- The bootstrap source snapshot and known limitations are documented under `docs/reference/` and `reference/bootstrap/`.

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
3. Add or tighten tests before refactoring behavior inherited from bootstrap.
4. Make the smallest coherent change that closes the phase acceptance gate.
5. Run `scripts/validate` before claiming completion.
6. Update the relevant plan or completion evidence when behavior, accepted state, or material risks change.

## Durable invariants

- The final CLI is harness-neutral, deterministic, local-first, and usable without network access.
- Runtime dependencies remain standard-library-only unless an accepted decision documents why a dependency is necessary.
- Do not hard-wrap Markdown prose.
- All diagnostics are stable, sorted, and testable. Human-readable wording may improve without changing diagnostic identity.
- Git-visible authored text is governed by default. Generated, vendored, lock, fixture, and legal material must be classified explicitly rather than hidden behind broad exclusions.
- Policy limits may tighten but must not silently weaken relative to a configured base revision.
- `tools/check_repository_policy.py` is the frozen test oracle copied from bootstrap. Do not edit it; production behavior belongs in `src/raften/`.
- Never add project-specific exemptions to shared engine code.
- Keep every authored code and documentation file below the repository policy ceiling. Split by responsibility, not merely to satisfy byte counts.

## Validation

- Full local validation: `scripts/validate`.
- Tests only: `scripts/test`.
- Bootstrap a freshly unpacked archive: `scripts/bootstrap`.
- Self-hosted policy check: `scripts/context-check`.
- Target CLI smoke test: `PYTHONPATH=src python3 -m raften --help`.

## Parallel work

- Use parallel agents only for independent read-only exploration or review.
- Do not run multiple writing agents against the same working tree.
- Have a read-only reviewer inspect substantive implementation changes before merge.
