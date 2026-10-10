# October security follow-up

The October 8, 2026 Codex Security Cloud scan of `c162828` reported five new findings. Each fix has a separate issue and PR, with deterministic safety ceilings, focused regressions, full local validation, and independent read-only review. Runtime remains standard-library-only and the frozen oracle remains unchanged.

## Acceptance gates

- [x] [Report amplification](https://github.com/BBW-Research/raften/issues/19): preserve version 1 output with lazy projection and bounded atomic encoding.
- [ ] [Glob amplification](https://github.com/BBW-Research/raften/issues/22): bound patterns before compilation and matcher work before allocation.
- [ ] [Selector cross product](https://github.com/BBW-Research/raften/issues/20): bound aggregate evaluation work and context retention.
- [ ] [Markdown amplification](https://github.com/BBW-Research/raften/issues/21): bound semantic objects, graph edges, and diagnostics before retention.
- [ ] [Git administration ownership](https://github.com/BBW-Research/raften/issues/23): verify ordinary and linked-worktree administration and revalidate later commands.

## Evidence

Report validation: `BASE_REF=origin/main scripts/validate` passed 565 tests on Python 3.13 with one filesystem-capability skip. Five focused resource tests cover repeated rationale, inclusive Unicode byte limits, encoded-value limits, complete CLI failure output, and lazy text row projection. Independent read-only review found and verified the text audit allocation fix, then reported no remaining blocker. Schema normalization and pagination are deferred to a separate interface change; over-ceiling version 1 reports refuse with a bounded operational failure.

Other fixes are in progress. PR creation does not authorize merging or marking cloud findings fixed before merge.
