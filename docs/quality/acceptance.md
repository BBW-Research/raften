# Acceptance criteria

The standalone tool is release-ready only when every release-blocking item below is satisfied.

## Repository and configuration

- [ ] `repo-context` accepts an explicit repository root and works from any current working directory.
- [ ] The v1 TOML parser rejects unknown keys, invalid types, unsafe paths, ambiguous rules, invalid limits, and broad exceptions.
- [ ] Rule and override precedence is documented, deterministic, and covered by tests.
- [ ] Runtime checks make no network requests and do not execute repository content.
- [ ] Python 3.12 and 3.13 are supported on macOS, Linux, and Windows.

## File and context budgets

- [ ] Git-tracked and non-ignored untracked files are inventoried; ignored files are omitted.
- [ ] Plaintext detection and raw-byte counting match the specification.
- [ ] Warning and hard thresholds behave correctly at exact boundaries.
- [ ] Generated, vendored, fixture, legal, authored, migration, and intentional-exception states remain distinguishable.
- [ ] Named context sets de-duplicate members, detect missing required members, and enforce aggregate thresholds.
- [ ] `audit` identifies the largest governed files and effective rules.
- [ ] `explain` identifies the exact rule, override, and context sets for a path.

## Documentation graph

- [ ] Every governed directory receives an ancestor-aware `index.md` check.
- [ ] Sibling and immediate child-index links are enforced when enabled.
- [ ] Every governed document is reachable from a configured root.
- [ ] Local file targets and heading fragments are validated.
- [ ] Inline, reference-style, angle-bracket, escaped, percent-encoded, query, fragment, code-span, code-fence, and HTML-comment cases are tested.
- [ ] Symlinks and repository-escape attempts cannot cause reads outside the repository.

## Ratchets and governance

- [ ] Newly oversized authored files fail relative to a base revision.
- [ ] Existing oversized files may only stay equal or shrink relative to their immediate base version.
- [ ] Partial reductions are locked in automatically.
- [ ] Files that return below the ordinary limit automatically leave migration debt.
- [ ] Increased limits, expanded exclusions, removed roots, removed targets, weakened context sets, disabled ratchets, and broadened exceptions are reported.
- [ ] First-adoption debt capture is deterministic and never creates broad exclusions.
- [ ] Expired or malformed intentional exceptions fail.

## CLI and diagnostics

- [ ] `check`, `audit`, `explain`, and `init` work end to end.
- [ ] Exit codes are exactly `0` success, `1` completed check with violations, and `2` argument/configuration/operational failure.
- [ ] Expected failures do not emit tracebacks.
- [ ] Diagnostics have stable codes, severities, paths, positions when real, structured details, and deterministic order.
- [ ] Text, JSON, and SARIF outputs are tested and versioned where appropriate.
- [ ] Broken-pipe handling is quiet and conventional.

## Extraction and self-hosting

- [ ] The frozen scene-maker source hash remains verified.
- [ ] Characterization tests cover all inherited seed behavior.
- [ ] Intended differences from the seed are explicit and tested.
- [ ] Production code does not import the seed checker.
- [ ] `scripts/context-check` and CI run the new package rather than the seed.
- [ ] The new tool validates this repository's file budgets, documentation graph, context set, and base ratchet.
- [ ] `scripts/validate` succeeds offline in a clean checkout or freshly bootstrapped archive.

## Distribution and pilots

- [ ] Wheel and source distribution build in isolation.
- [ ] Installed CLI works in clean environments.
- [ ] A vendorable offline distribution path is documented and tested.
- [ ] Migration from the scene-maker JSON policy is documented.
- [ ] `scene-maker`, `nano-dllm`, and `research-vault` have been piloted without adding project-specific engine branches.
- [ ] The eventual repository protects the required CI check and policy-sensitive files through repository settings and ownership review.
