# 0002: Shared engine, repository-owned contract

- Status: accepted
- Date: 2026-08-31

## Context

Copying the bootstrap script into every project would make adoption easy but would cause divergent bug fixes and project-specific behavior. Embedding every project policy inside one central tool would create the opposite problem: the shared package would accumulate repository assumptions and become difficult to upgrade safely.

## Decision

The standalone package owns the reusable engine and stable CLI. Every consuming repository owns its policy file, wrapper command, CI gate, context sets, documentation roots, and explicit exceptions.

A starter template may vendor or pin a release for offline use, but vendoring is a distribution mechanism rather than a fork. The wrapper remains the stable command agents use, while the implementation can move between a vendored module, an installed package, or a zipapp.

## Consequences

- Shared defects are fixed once.
- Repositories retain control over what counts as authored, generated, or navigable.
- CI policy changes remain reviewable alongside project code.
- Project-specific architecture checks continue to live in each repository's broader `scripts/validate` rather than expanding this tool into a generic linter.
