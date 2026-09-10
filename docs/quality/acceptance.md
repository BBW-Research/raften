# Acceptance criteria

The standalone tool is release-ready only when every release-blocking item below is satisfied.

## Repository and configuration

- [x] `raften` accepts an explicit repository root and works from any current working directory.
- [x] The v1 TOML parser rejects unknown keys, invalid types, unsafe paths, ambiguous rules, invalid limits, and broad exceptions.
- [x] Rule and override precedence is documented, deterministic, and covered by tests.
- [x] Runtime checks make no network requests and do not execute repository content.
- [x] Python 3.12 and 3.13 are supported on macOS and Linux.

## File and context budgets

- [x] Git-tracked and non-ignored untracked files are inventoried; ignored files are omitted.
- [x] Plaintext detection and raw-byte counting match the specification.
- [x] Warning and hard thresholds behave correctly at exact boundaries.
- [x] Generated, vendored, fixture, legal, authored, migration, and intentional-exception states remain distinguishable.
- [x] Named context sets de-duplicate members, detect missing required members, and enforce aggregate thresholds.
- [x] `audit` identifies the largest governed files and effective rules.
- [x] `explain` identifies the exact rule, override, and context sets for a path.

## Documentation graph

- [x] Every governed directory receives an ancestor-aware `index.md` check.
- [x] Sibling and immediate child-index links are enforced when enabled.
- [x] Every governed document is reachable from a configured root.
- [x] Local file targets and heading fragments are validated.
- [x] Inline, reference-style, angle-bracket, escaped, percent-encoded, query, fragment, code-span, code-fence, and HTML-comment cases are tested.
- [x] Symlinks and repository-escape attempts cannot cause reads outside the repository.

## Ratchets and governance

- [x] Newly oversized authored files fail relative to a base revision.
- [x] Existing oversized files may only stay equal or shrink relative to their immediate base version.
- [x] Partial reductions are locked in automatically.
- [x] Files that return below the ordinary limit automatically leave migration debt.
- [x] Increased limits, expanded exclusions, removed roots, removed targets, weakened context sets, disabled ratchets, and broadened exceptions are reported.
- [x] First-adoption debt capture is deterministic and never creates broad exclusions.
- [x] Expired or malformed intentional exceptions fail.

## CLI and diagnostics

- [x] `check`, `audit`, `explain`, and `init` work end to end.
- [x] Exit codes are exactly `0` success, `1` completed check with violations, and `2` argument/configuration/operational failure.
- [x] Expected failures do not emit tracebacks.
- [x] Diagnostics have stable codes, severities, paths, positions when real, structured details, and deterministic order.
- [x] Text, JSON, and SARIF outputs are tested and versioned where appropriate.
- [x] Broken-pipe handling is quiet and conventional.

## Extraction and self-hosting

- [x] The frozen scene-maker source hash remains verified.
- [x] Characterization tests cover all inherited seed behavior.
- [x] Intended differences from the seed are explicit and tested.
- [x] Production code does not import the seed checker.
- [x] `scripts/context-check` and CI run the new package rather than the seed.
- [x] The new tool validates this repository's file budgets, documentation graph, context set, and base ratchet.
- [x] `scripts/validate` succeeds offline in a clean checkout or freshly bootstrapped archive.

## Distribution and pilots

The completed Phase 8 evidence qualified artifacts under the former distribution name. The two pending items require fresh Raften artifacts across the supported matrix, as required by [decision 0009](../decisions/0009-raften-name.md) and the [release guide](../release/index.md).

- [ ] Raften wheel and source distribution build in isolation from the reviewed release commit.
- [ ] Installed Raften CLI works in clean environments across the supported release matrix.
- [x] A vendorable offline distribution path is documented and tested.
- [x] Migration from the scene-maker JSON policy is documented.
- [x] `scene-maker`, `nano-dllm`, and `research-vault` have been piloted without adding project-specific engine branches.
- [x] The repository protects the required CI check and policy-sensitive files through repository settings and ownership review.
