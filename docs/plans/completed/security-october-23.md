# October 23 security remediation

The October 23, 2026 Codex Security Cloud scan of `58683e6` reported four new findings. Each has a tracking issue and a separate fix PR. Runtime remains standard-library-only and the frozen bootstrap oracle remains unchanged. Cloud findings remain open pending merge and verification.

## Nested Git inputs

[Issue #34](https://github.com/BBW-Research/raften/issues/34) tracks omitted nested ref witnesses. Administration traversal now distinguishes object payloads from mutable metadata independently of its root-recursion state. Nested refs, reflogs, and reftable files share the existing 4,096-file witness ceiling. Full file identity stamps detect in-place and restored writes before and after Git commands; split-index freshening retains its established exception.

Five focused regressions reproduced the omission before the fix and cover branch/tag/symbolic refs, reftable/reflog inputs, pre-command refusal, restored writes during resolution, linked-worktree common refs, and witness-limit accounting. Validation and independent review are recorded in the PR.

Nested-input validation: `BASE_REF=origin/main scripts/validate` passed 605 tests on Python 3.13 with one filesystem-capability skip. Independent read-only review passed 39 focused tests and found no actionable defect. Repository policy reports zero errors and the existing `inventory.py` size advisory.

## Debt manifest structure

[Issue #33](https://github.com/BBW-Research/raften/issues/33) tracks JSON object amplification. A linear lexical pass bounds tokens, depth, object members, array entries, and numeric tokens before invoking the standard JSON decoder. Escape-aware string scanning preserves literal filename data and existing schema and duplicate-key diagnostics. Capture and rendering enforce the entry ceiling before projection and generated output must pass the same envelope. The limits are authoritative in the [first-adoption contract](../../specs/ratchets-v1.md#first-adoption-manifest).

Debt validation: `BASE_REF=origin/main scripts/validate` passed 609 tests on Python 3.13 with one filesystem-capability skip. Four focused regressions cover pre-decoder refusal, inclusive boundaries, escaped strings, and capture/render limits. Independent read-only review passed 47 focused tests and checked exact and one-below boundaries for 1,000 generated JSON values without an accounting mismatch.

## Aggregate content work

[Issue #32](https://github.com/BBW-Research/raften/issues/32) tracks cumulative reads, hashing, and Git child creation. Repository handles now share fixed byte and child allowances across all current/base content and cleanliness hashing, charging before expensive work. Base streams are capped at their reserved expanded size. Ratchet candidates sharing historical object IDs reuse compact classifications instead of retaining raw bytes. Independent commands receive fresh budgets; counter state does not affect snapshot identity.

Content validation: `BASE_REF=origin/main scripts/validate` passed 616 tests on Python 3.13 with one filesystem-capability skip. Seven initial regressions cover shared byte limits, pre-open refusal, streaming initialization hashes, inclusive process limits, empty blobs, duplicate historical objects, and complete CLI failures; an additional short-output regression passed with the focused suite. Independent read-only review passed 79 focused tests and found no blocking bypass. Release export also shares this allowance, with its current file-count implication documented in the [release guide](../../release/index.md).
