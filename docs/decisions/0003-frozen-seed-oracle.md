# 0003: Preserve the source checker as a frozen oracle

- Status: accepted
- Date: 2026-08-31
- Attribution update: current source labels follow [decision 0011](0011-generic-bootstrap-attribution.md); the frozen snapshot contract remains unchanged.

## Context

Refactoring the bootstrap script directly would make it difficult to distinguish deliberate improvements from accidental behavior changes. The source already provides working size, index, entrypoint, and policy-ratchet behavior that can seed characterization tests.

## Decision

Keep `tools/check_repository_policy.py` byte-for-byte identical to the accepted bootstrap snapshot until the new engine passes parity and self-hosting gates. `reference/bootstrap/SOURCE.json` records both the Git blob hash and SHA-256 digest. A test enforces that snapshot.

Do not import the source checker from production modules. Tests may load it as an oracle. Improvements such as ancestor-aware documentation traversal, explicit matcher semantics, and true base-size ratcheting belong only in the new package and must have tests showing the intended difference.

## Consequences

- The extraction has a stable behavioral baseline.
- Known defects are not accidentally canonized as target behavior.
- The final transition can compare old and new diagnostics on fixture repositories before replacing the wrapper.
