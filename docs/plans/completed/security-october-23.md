# October 23 security remediation

The October 23, 2026 Codex Security Cloud scan of `58683e6` reported four new findings. Each has a tracking issue and a separate fix PR. Runtime remains standard-library-only and the frozen bootstrap oracle remains unchanged. Cloud findings remain open pending merge and verification.

## Nested Git inputs

[Issue #34](https://github.com/BBW-Research/raften/issues/34) tracks omitted nested ref witnesses. Administration traversal now distinguishes object payloads from mutable metadata independently of its root-recursion state. Nested refs, reflogs, and reftable files share the existing 4,096-file witness ceiling. Full file identity stamps detect in-place and restored writes before and after Git commands; split-index freshening retains its established exception.

Five focused regressions reproduced the omission before the fix and cover branch/tag/symbolic refs, reftable/reflog inputs, pre-command refusal, restored writes during resolution, linked-worktree common refs, and witness-limit accounting. Validation and independent review are recorded in the PR.

Nested-input validation: `BASE_REF=origin/main scripts/validate` passed 605 tests on Python 3.13 with one filesystem-capability skip. Independent read-only review passed 39 focused tests and found no actionable defect. Repository policy reports zero errors and the existing `inventory.py` size advisory.
