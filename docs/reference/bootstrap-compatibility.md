# Bootstrap compatibility classification

This is the Phase 7 classification of observable differences between the frozen bootstrap checker and `repo-context` version 1. The source characterization remains authoritative for seed behavior; this report records whether each paired result is an equivalent diagnostic, an intended improvement, or a defect.

## Classification rules

- **Equivalent diagnostic** means both engines reach the same policy outcome even though the target uses stable diagnostic identities, structured fields, and different prose.
- **Intended improvement** means the target deliberately rejects a seed defect, reports a previously silent condition, or provides a specified capability the seed lacks.
- **Defect** means an inherited behavior that should remain compatible changed without a higher-authority specification or accepted decision.

No defect remains in the completed comparison.

## Repository comparison

Both engines were run over this repository with no base and with `HEAD` as the base. The seed uses the fixture-scoped clean JSON policy solely for this comparison; normal validation uses `repo-context.toml` through `scripts/context-check`.

The seed and target both complete successfully. With `HEAD`, the target reports no blocking diagnostics, no documentation graph findings or unreachable documents, a within-limit `bootstrap` context, and no file or policy ratchet change. The target additionally emits advisory `CTX001` warnings for files above their warning thresholds. Without a base, it emits the specified nonblocking `RAT001` note instead of silently skipping the ratchet. These are intended improvements.

`RepositorySelfHostingTests` reruns this comparison, asserts all self-hosted domains, and verifies that the wrapper works without installation from an unrelated directory.

## Executable compatibility fixtures

`tests/test_seed_target_compatibility.py` runs both command-line engines over every fixture in this matrix. Exact prose is not treated as an interface equivalence; the target assertion uses exit status and stable diagnostic identity.

| Fixture | Seed result | Target result | Classification |
| --- | --- | --- | --- |
| Clean repository | Exit `0` with pass summary | Exit `0` with zero-error summary | Equivalent diagnostic |
| Hard file limit | Exit `1` with an oversized-file error | Exit `1` with `CTX002` | Equivalent diagnostic |
| Missing entrypoint | Exit `1` with a missing-entrypoint error | Exit `1` with `DOC006` | Equivalent diagnostic |
| Increased file limit relative to base | Exit `1` with a non-weakening error | Exit `1` with `RAT006` | Equivalent diagnostic |
| Intermediate documentation ancestor | Exit `0` because the ancestor is omitted | Exit `1` with `DOC003` and reachability findings | Intended improvement |
| Missing local Markdown target | Exit `0` because target existence is unchecked | Exit `1` with `DOC009` | Intended improvement |
| Requested missing base | Exit `0` after silently skipping comparison | Exit `2` with `GIT006` | Intended improvement |
| Unsafe config path | Unbounded traceback and exit `1` | Bounded exit `2` with `CFG006` | Intended improvement |

## Complete intended-difference inventory

The paired fixtures above cover cross-engine command outcomes. The lower-level characterization and target suites retain every other known semantic difference without duplicating the exhaustive seed characterization suite.

| Difference | Target evidence | Classification |
| --- | --- | --- |
| Explicit repository root and arbitrary caller working directory | `CliIntegrationTests.test_explicit_relative_repository_works_from_an_unrelated_directory` and `RepositorySelfHostingTests.test_wrapper_uses_source_tree_from_an_unrelated_directory` | Intended improvement |
| Ancestor-aware documentation discovery and independent root reachability | `IntendedImprovementCompatibilityTests.test_intermediate_documentation_ancestor_is_target_only` and `SourceDifferenceIntegrationTests.test_intermediate_directory_gap_passes_seed_but_fails_target_hierarchy` | Intended improvement |
| Reference-style Markdown support while code and comments are ignored | `SourceDifferenceIntegrationTests.test_reference_links_count_while_code_and_comment_links_do_not` plus the parser matrix in `tests/test_markdown.py` | Intended improvement |
| Repository globs in which only `**` crosses path components | `tests/test_matcher.py` and `tests/test_matcher_syntax.py` | Intended improvement |
| Immediate-base file ratchet instead of stale manual legacy ceilings | `RatchetRepositoryIntegrationTests.test_git_blob_comparison_locks_in_each_partial_reduction_without_mutation` | Intended improvement |
| No hardcoded structured-data exclusion bypass | `PolicyRatchetTests.test_unscanned_expansion_is_reported_without_seed_exemptions` | Intended improvement |
| Named context sets with de-duplicated aggregate accounting | `tests/test_context_sets.py` and `RepositorySelfHostingTests.test_root_policy_covers_budgets_graph_context_and_ratchet` | Intended improvement |
| Stable diagnostics, warning thresholds, JSON, SARIF, audit, explain, and guarded init | `tests/test_cli_integration.py` and all report and initialization suites | Intended improvement |
| Base file blobs and policy are read without modifying the worktree or index | `tests/test_ratchet_integration.py` | Intended improvement |
| Strict TOML types, duplicate-key rejection, and complete structural validation | `tests/test_config_invalid_shape.py` and `tests/test_config_invalid_semantics.py` | Intended improvement |
| Canonical configured and candidate paths, including bounded unsafe-input errors | `tests/test_config_invalid_semantics.py`, `tests/test_git_output_validation.py`, `tests/test_worktree_inventory_safety.py`, and `tests/test_cli_integration.py` | Intended improvement |
| Local files, directories, explicit IDs, and heading fragments are validated | `IntendedImprovementCompatibilityTests.test_missing_local_target_is_target_only` and `SourceDifferenceIntegrationTests.test_missing_target_and_fragment_are_target_only_failures` | Intended improvement |
| Missing nonzero base revisions fail while the all-zero sentinel remains nonblocking | `IntendedImprovementCompatibilityTests.test_missing_requested_base_is_a_target_operational_failure` and `tests/test_runner.py` | Intended improvement |
| Expected argument, configuration, and repository failures never emit tracebacks | `IntendedImprovementCompatibilityTests.test_unsafe_config_is_a_bounded_target_failure` and `tests/test_cli_integration.py` | Intended improvement |

## Frozen oracle status

`tools/check_repository_policy.py` remains byte-identical and is loaded only by source-characterization and paired-compatibility tests. It is not the repository-validation engine, is not imported by production code, and is not selected by any normal policy entrypoint; its execution during local, bootstrap, or CI validation is test-only. `tests/fixtures/seed/clean-policy.json` is an adapted fixture for comparisons only; the former root bootstrap JSON policy has been removed.
