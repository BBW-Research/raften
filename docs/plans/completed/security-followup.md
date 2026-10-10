# October security follow-up

The October 8, 2026 Codex Security Cloud scan of `c162828` reported five new findings. Each fix has a separate issue and PR, with deterministic safety ceilings, focused regressions, full local validation, and independent read-only review. Runtime remains standard-library-only and the frozen oracle remains unchanged.

## Acceptance gates

- [x] [Report amplification](https://github.com/BBW-Research/raften/issues/19): preserve version 1 output with lazy projection and bounded atomic encoding.
- [x] [Glob amplification](https://github.com/BBW-Research/raften/issues/22): bound patterns before compilation and matcher work before allocation.
- [x] [Selector cross product](https://github.com/BBW-Research/raften/issues/20): bound aggregate evaluation work and context retention.
- [x] [Markdown amplification](https://github.com/BBW-Research/raften/issues/21): bound semantic objects, graph edges, and diagnostics before retention.
- [x] [Git administration ownership](https://github.com/BBW-Research/raften/issues/23): verify ordinary and linked-worktree administration and revalidate later commands.

## Evidence

Report validation: `BASE_REF=origin/main scripts/validate` passed 565 tests on Python 3.13 with one filesystem-capability skip. Five focused resource tests cover repeated rationale, inclusive Unicode byte limits, encoded-value limits, complete CLI failure output, and lazy text row projection. Independent read-only review found and verified the text audit allocation fix, then reported no remaining blocker. Schema normalization and pagination are deferred to a separate interface change; over-ceiling version 1 reports refuse with a bounded operational failure.

All five fixes are prepared for PR review. PR creation does not authorize merging or marking cloud findings fixed before merge.

Glob validation: `BASE_REF=origin/main scripts/validate` passed 572 tests on Python 3.13 with one filesystem-capability skip. Seven resource regressions cover scalar/list configuration refusal, byte/token boundaries, class-range cost, shared budgets, and refusal before character-table scans. Independent review passed 112 focused tests and compared 91,892 match outcomes against the prior implementation without a mismatch. Cumulative command accounting follows in the selector fix.

Selector validation: `BASE_REF=origin/main scripts/validate` passed 579 tests on Python 3.13 with one filesystem-capability skip. Six selector regressions cover real maximum context records, pre-read rejection, duplicate match sharing, independent membership/reference bounds, inclusive ceilings, and repeat evaluation. The benchmark continues after a report-boundary refusal and records `audit_status` rather than disabling the ceiling. The official 100,000-path benchmark completed with 100,000 Git paths and content reads, 7,731 retained bytes, and a 1,000-level documentation workload; its full audit correctly refused above the report envelope. Independent read-only review passed 122 focused tests and found no blocker.

Markdown validation: `BASE_REF=origin/main scripts/validate` passed 587 tests on Python 3.13 with one filesystem-capability skip. Eight new regressions cover adjacent and external links, combined anchor candidates, shared semantic limits, repeated reference normalization, inclusive counts, retained destination bytes, distinct graph edges, directory metadata, and producer/final diagnostic refusal. Independent read-only review verified pre-retention checks and compatibility of graph deduplication and migration diagnostic reconciliation.

Git administration validation: `BASE_REF=origin/main scripts/validate` passed 599 tests on Python 3.13 with one filesystem-capability skip. Twelve new regressions cover unrelated gitfiles, linked backlinks, pre-command replacement, restored administration/root ancestors around children, symlinked Git inputs, alternate borrowing, pointer mutation, independent limits, unvalidated/mismatched handles, split-index freshness, and special files. Independent review reproduced two initial gaps (ancestor restoration and legitimate split-index freshness), verified both fixes, passed 71 focused tests, and independently confirmed external linked-worktree ancestor refusal. Namespace guards are scoped to each child and release all descriptors. Separate-git-dir and submodule gitfiles without linked registration remain unsupported; concurrent administration activity and unreliable filesystem change reporting remain documented limits.

The final official 100,000-path benchmark completed with 100,000 Git paths and content reads, 7,731 retained bytes, and a 1,000-level documentation workload. Full audit output correctly refused above its envelope. Independent cumulative integration review passed 89 focused tests across the first four fixes. Hosted repository-policy CI passed for PRs #24–#27 before final Git PR submission; the final PR has its own hosted check.
