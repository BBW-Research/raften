# Security audit remediation

The October 2, 2026 Codex Security Cloud scan of `eb0466c` reported six availability and initialization-integrity findings. Each has its own GitHub issue and will receive a separate PR. The fixes form a reviewable sequence; runtime dependencies remain standard-library-only and the frozen bootstrap oracle remains unchanged.

## Acceptance gates

- [x] [CI duration bounds](https://github.com/BBW-Research/raften/issues/12): explicit job timeouts and fail-closed aggregation.
- [x] [Policy ambiguity amplification](https://github.com/BBW-Research/raften/issues/9): bound input, records, comparison work, and diagnostics while retaining deterministic conflict witnesses.
- [x] [Markdown delimiter rescanning](https://github.com/BBW-Research/raften/issues/8): index delimiter matches and enforce an operational parse ceiling.
- [x] [Git metadata volume](https://github.com/BBW-Research/raften/issues/7): bound child output, records, and paths and reap failed children.
- [x] [Content materialization](https://github.com/BBW-Research/raften/issues/10): bound current and base content before allocation and aggregate retained Markdown.
- [ ] [Initialization root identity](https://github.com/BBW-Research/raften/issues/11): detect namespace substitution throughout validation and before publication.

Each phase adds focused regression coverage, updates the authoritative contract, runs `scripts/validate`, and receives independent read-only review. PR descriptions record remaining platform or hosted-validation limitations. Opening the PRs does not authorize merging them or closing cloud findings before merge.

## Evidence

CI jobs use conservative ceilings of 30 minutes for each qualification matrix entry, 10 minutes for offline links, and 5 minutes for the result aggregator. The existing aggregator accepts only `success`, including when a prerequisite times out or is cancelled. Same-ref cancellation and the four-platform/version qualification matrix remain in effect. These are operational budgets, not measured performance guarantees; hosted runs will provide fresh timing evidence.

CI validation: `scripts/validate` passed 525 tests (one filesystem-capability skip); the new regression checks all jobs for finite timeouts and executes the aggregator against every success/failure/cancelled/skipped prerequisite combination. A deliberately stalled hosted job was not run.

Policy validation: `scripts/validate` passed 529 tests (one filesystem-capability skip), followed by six focused resource regressions including disjoint-pattern exhaustion, cross-section comparison accounting, inclusive ceilings, and deterministic first-witness diagnostics. Independent review found no blocking defect. Fixed parser limits and diagnostic semantics are defined in the [configuration contract](../../specs/configuration-v1.md).

Markdown validation: `scripts/validate` passed 536 tests on Python 3.13 (one filesystem-capability skip), and six focused resource tests passed after adding heading/HTML budget coverage. Delimiter regressions count character work; byte, destination, heading recursion, and HTML work exhaustion fail with `DOC012`. The [Markdown contract](../../specs/markdown-graph-v1.md) defines limits and whole unmatched-run behavior. Independent review found no blocking defect.

Git metadata validation: `scripts/validate` passed 544 tests on Python 3.13 (one filesystem-capability skip), followed by eight focused resource tests after tightening pure decoder guards. Real child pipes cover overflow, fragmented records, timeout after EOF, and reaping. Independent review found no blocking defect. The official `scripts/benchmark --count 100000` completed with exactly 100,000 inventoried paths (1.93 seconds for Git inventory), 351,895,552 bytes process peak RSS reported by the benchmark, and a 1,000-level documentation workload. Timing is observational, not a gate. The [inventory boundary](../../architecture/inventory.md) defines the envelope.

Content validation: `scripts/validate` passed 551 tests on Python 3.13 (one filesystem-capability skip), including six content regressions and canonical manifest rendering. Tests reject sparse policies before reading, oversized expanded base blobs before content commands, lying size preflights during stream collection, and per-file/aggregate retained content overflow. They preserve exact UTF-8/NUL classification, hashes, inclusive limits, and operational exits for check/audit. The official 100,000-path benchmark still completes with 100,000 content reads and 7,731 retained text bytes. Review identified manifest output allocation before its cap; incremental bounded JSON encoding closes that path. The [content envelope](../../specs/file-budgets-v1.md#operational-content-envelope) documents the fixed bounds.
