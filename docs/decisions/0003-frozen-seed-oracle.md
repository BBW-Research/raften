# 0003: Preserve the source checker as a frozen oracle

- Status: accepted
- Date: 2026-08-31

## Context

Refactoring the scene-maker script directly would make it difficult to distinguish deliberate improvements from accidental behavior changes. The source already provides working size, index, entrypoint, and policy-ratchet behavior that can seed characterization tests.

## Decision

Keep `tools/check_repository_policy.py` byte-for-byte identical to scene-maker commit `9e792124bc61f55150416b8bf803862c6c634c78` until the new engine passes parity and self-hosting gates. `reference/scene-maker/SOURCE.json` records both the Git blob hash and SHA-256 digest. A test enforces that snapshot.

Do not import the source checker from production modules. Tests may load it as an oracle. Improvements such as ancestor-aware documentation traversal, explicit matcher semantics, and true base-size ratcheting belong only in the new package and must have tests showing the intended difference.

## Consequences

- The extraction has a stable behavioral baseline.
- Known defects are not accidentally canonized as target behavior.
- The final transition can compare old and new diagnostics on fixture repositories before replacing the wrapper.
