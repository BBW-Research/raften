# Scene-maker seed

## Source

The bootstrap implementation is copied from `BBW-Research/scene-maker` at commit `9e792124bc61f55150416b8bf803862c6c634c78`.

- Source path: `tools/check_repository_policy.py`
- Git blob: `a18f52d15c8f70a53bad2e0d961f5fa355a50a84`
- Local frozen path: `tools/check_repository_policy.py`
- Provenance manifest: `reference/scene-maker/SOURCE.json`

The working scene-maker workflow and Lychee configuration are preserved under `reference/scene-maker/`. The enormous scene-maker migration inventory is intentionally not copied; the starter policy contains no legacy oversized files.

The completed [Phase 7 compatibility classification](scene-maker-compatibility.md) records every equivalent diagnostic and intended target improvement. No comparison defect remains.

## Seed behavior to preserve initially

The source checker:

- Inventories tracked and non-ignored untracked Git paths.
- Treats regular UTF-8 files without NUL bytes as plaintext.
- Enforces a default byte ceiling, smaller entrypoint limits, and smaller documentation-index limits.
- Allows listed legacy oversized files only up to manually recorded ceilings.
- Requires an `index.md` in discovered documentation directories.
- Requires each index to link sibling documents and immediate child indexes.
- Requires configured root entrypoints to link configured targets.
- Compares selected policy fields with a base revision and rejects several weakening changes.
- Uses exit code `0` for pass, `1` for violations, and `2` for operational or configuration errors.

## Phase 0 characterization coverage

The source oracle is exercised directly by responsibility. `tests/support/repository.py` creates deterministic temporary Git repositories, writes exact bytes, commits base states, mutates worktrees, and runs either the copied seed or target module with argument-vector subprocesses. Structured assertions cover the source contract completely, so no golden text fixture is needed in this phase.

| Source responsibility | Characterization evidence |
| --- | --- |
| JSON policy parsing, path canonicalization, and inherited `fnmatch` behavior | `tests/test_seed_policy.py` |
| Git-visible inventory, UTF-8 classification, raw-byte limits, and manual legacy ceilings | `tests/test_seed_files.py` |
| Inline link extraction, documentation discovery, indexes, siblings, child indexes, and entrypoint targets | `tests/test_seed_docs.py` |
| Base-policy reads and every non-weakening comparison | `tests/test_seed_ratchet.py` |
| Argument defaults, exit codes, stdout/stderr, deterministic ordering, missing-base behavior, and repository-root inference | `tests/test_seed_cli.py` |
| Snapshot repository, commit, verbatim modes, Git blobs, and checker SHA-256 | `tests/test_seed_provenance.py` |

## Intended differences and deferred target cases

The target must not preserve the following source behavior. The seed-side evidence is retained permanently; the target-side assertion belongs to the listed implementation phase and must invert or supersede the source behavior without weakening the characterization.

| Source behavior or missing capability | Phase 0 evidence | Required target case |
| --- | --- | --- |
| The checker infers the repository from its own location and has no `--repo` argument. | `SeedCliCharacterizationTests.test_seed_targets_the_checker_location_not_the_current_directory` and `test_seed_has_no_explicit_repository_argument` | Phase 2 accepts an explicit root from any current directory; Phase 6 exposes it through every public command. |
| An intermediate documentation directory containing only a deeper child escapes index and child-routing checks. | `SeedDocumentationCheckTests.test_seed_omits_intermediate_directory_without_direct_documents` | Phase 4 reports the missing ancestor index and missing immediate child route. |
| Regex-only Markdown extraction misses reference links and treats link-looking text in code and HTML comments as navigation. | `SeedMarkdownTargetTests.test_seed_misses_reference_links_and_reads_links_inside_code_and_comments` | Phase 4 supports the specified inline and reference forms while ignoring code spans, fenced code, and HTML comments. |
| Python `fnmatch` lets `*` and `?` cross `/` and gives basename-like patterns implicit depth behavior. | `SeedMatcherTests.test_seed_star_and_question_mark_cross_path_separators` | Phase 2 implements the repository glob language in which only `**` crosses path components. |
| A partially reduced legacy file may regrow beneath its stale manual ceiling. | `SeedSizeCheckTests.test_seed_manual_ceiling_allows_regrowth_after_partial_reduction` | Phase 5 compares the immediate base blob and rejects any regrowth above the partially reduced size. |
| Additions of `config/*.json` and `schemas/*.json` to text exclusions bypass the seed policy ratchet. | `SeedPolicyRatchetTests.test_seed_hardcodes_structured_data_exclusion_additions_as_allowed` | Phase 3 expresses structured-data classification only in repository policy; Phase 5 reports exclusion expansion like any other weakening. |
| Direct-link checks do not perform an independent root-reachability traversal. | The intermediate-directory fixture above passes despite a disconnected deep subtree. | Phase 4 reports every governed document unreachable from all configured roots. |
| The policy has no context-set model. | Strict source-policy key tests reject any additional section. | Phase 3 implements de-duplicated aggregate context sets and missing-member diagnostics. |
| Output is prose-only and there is no audit, explain, or initialization interface. | `tests/test_seed_cli.py` records the complete source argument and stream contract. | Phase 6 adds stable diagnostics and the four target commands without reusing source prose as diagnostic identity. |
| Base reads load only prior policy, not prior file blobs. | `tests/test_seed_ratchet.py` records the sole Git read and the manual-ceiling tests record its consequence. | Phase 5 reads base blobs without modifying the worktree and implements the size ratchet. |
| JSON policy parsing accepts booleans as integers, last-write-wins duplicate keys, empty required lists, and non-canonical glob strings. | `SeedPolicyParsingTests.test_seed_accepts_boolean_numbers_empty_lists_and_duplicate_json_keys` and `test_seed_does_not_validate_glob_canonicality` | Phase 1 applies strict TOML types and structural validation; duplicate TOML keys remain parser errors and unsafe matcher patterns are rejected. |
| Canonical path validation accepts `.`, backslashes, and NUL characters. | `SeedCanonicalPathTests.test_seed_accepts_dot_backslash_and_nul_paths` | Phases 1 and 2 reject every unsafe or non-canonical configured and inventory path required by the specification. |
| Markdown fragments are discarded and nonexistent local targets are not validated. | `SeedDocumentationCheckTests.test_seed_does_not_validate_missing_local_targets_or_fragments` | Phase 4 validates normalized local files and directories plus explicit IDs and deterministic heading slugs. |
| A supplied missing base policy or ref is silently ignored. | `SeedCliCharacterizationTests.test_missing_and_all_zero_base_refs_are_silently_skipped` | Phase 5 distinguishes the documented all-zero sentinel from a missing or unreadable requested base and emits an operational diagnostic. |
| An unsafe `--config` value escapes the seed error boundary and prints a traceback. | `SeedCliCharacterizationTests.test_unsafe_config_path_escapes_seed_operational_error_handling` | Phase 6 maps every expected argument, configuration, and repository error to exit code 2 without a traceback. |

## Extraction rule

Use the seed as an oracle for compatible behavior, not as the module layout. Production modules must be designed around explicit inputs and immutable results. When target behavior intentionally differs, write a fixture showing both outputs and document why the target result is safer or more precise.
