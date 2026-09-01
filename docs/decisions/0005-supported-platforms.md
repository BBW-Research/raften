# 0005: Support macOS and Linux for the first stable release

- Status: accepted
- Date: 2026-09-01

## Context

The original product contract made Windows support a first-release gate alongside macOS and Linux. The primary user does not need Windows, so that gate would require a secure Windows content-reading backend and a Windows validation matrix without serving the intended usage.

The engine already has platform-neutral path semantics, including canonical handling of Windows-style inputs, and fails closed when a platform cannot provide the primitives required for safe repository reads. Those defensive properties are useful independently of the supported-platform promise.

## Decision

Support Python 3.12 and 3.13 on macOS and Linux for the first stable release. Windows is not a supported target and is not part of the Phase 8 release gate.

Retain generic Windows-aware path handling and fail-closed safety behavior. Do not add a Windows-specific secure content reader, CI job, or release qualification unless a later accepted decision expands the supported-platform scope.

## Consequences

- Release acceptance and Phase 8 validation cover macOS and Linux only.
- Windows behavior may remain partially functional, but it is not qualified or supported.
- Existing cross-platform normalization tests remain valuable and need not be removed.
- Expanding support to Windows requires an explicit decision, a secure content-reading implementation, and platform-specific validation.
