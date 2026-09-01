# Testing strategy

## Principles

Tests define the policy contract. Assert diagnostic codes and structured fields rather than relying only on human-readable prose. Use temporary Git repositories for integration behavior, deterministic fixture builders, and standard-library `unittest` unless a reviewed dependency is accepted.

Do not mock Git for behavior that depends on tracked, untracked, ignored, deleted, renamed, or base-revision state. Small real repositories are clearer and more reliable. Unit-test command construction and error translation separately.

## Test layers

### Source characterization

Load `tools/check_repository_policy.py` by path and record its existing behavior without importing it into production code. Cover successful and failing policy parsing, exact limits, document indexing, link resolution, entrypoint requirements, policy comparison, and CLI exit paths.

Known defects must not become target expectations. Mark them as explicit source-versus-target cases:

- Intermediate documentation directories can escape seed discovery.
- `fnmatch` allows path behavior not defined as repository glob semantics.
- Regex link extraction misses valid Markdown and can inspect code-like text.
- Manual legacy ceilings allow regrowth after partial reduction.
- Structured JSON exemptions are hardcoded in shared logic.
- The seed infers repository root from its own file location.

### Unit tests

Test immutable models, strict TOML validation, path canonicalization, glob matching, plaintext detection, limit precedence, link and heading extraction, graph traversal, ratchet comparison, diagnostic sorting, and each renderer without subprocess or large filesystem setup.

### Fixture-repository integration tests

Create repositories through a helper that can:

- Initialize Git with deterministic identity and timestamps where relevant.
- Write bytes or text with exact line endings.
- Mark files ignored, tracked, untracked, deleted, renamed, or symlinked.
- Commit a base state and return its SHA.
- Run the CLI from inside or outside the repository.
- Capture stdout, stderr, and exit code.

Required fixture families:

1. Clean minimal repository.
2. New oversized authored file.
3. Existing oversized file that shrinks, stays equal, grows, or crosses below the limit.
4. Generated, vendored, fixture, legal, and intentional-exception classifications.
5. Warning and hard boundary values with ASCII, multibyte UTF-8, LF, and CRLF.
6. Nested documentation with missing ancestor index.
7. Missing sibling and child-index links.
8. Orphan, cycle, multiple roots, and excluded documentation.
9. Broken local files, directories, anchors, duplicate headings, escaped destinations, and reference links.
10. Unsafe path, symlink escape, disappearing file, malformed Git output, missing base ref, and shallow history.
11. Policy weakening for every ratchet category.
12. CLI formats, stdout/stderr, broken pipe, and execution from another directory.

### Output contract tests

Text output uses focused golden files after replacing temporary paths and commit IDs. JSON output is parsed and asserted structurally; maintain a schema version and representative schema fixture. SARIF is parsed and checked for rule IDs, levels, real artifact locations, and absence of invented positions.

### Self-hosting tests

Run the built package over this repository and compare it with the bootstrap checker. Assert expected equivalence where behavior should carry forward and expected target-only diagnostics where defects were fixed. Add a test that scans production imports and rejects references to the frozen seed.

### Distribution tests

Build wheel and source distribution in an isolated environment, install each into a clean environment, and run all public commands against a fixture repository. Test the vendorable artifact separately. Run supported-platform CI before release.

## Performance tests

Generate synthetic inventories without committing enormous fixture trees to Git. Measure at least 10,000 and 100,000 paths, mixed small text files, and a deep documentation hierarchy. Set regression budgets only after baseline measurements are stable; avoid timing assertions that are too tight for shared CI.

Track:

- Git inventory time.
- Bytes read.
- Peak retained content.
- Markdown parse time.
- Graph construction time.
- Total check and audit time.

## Validation command

`scripts/validate` is the required local gate. During the starter phase it runs the source checker, compile checks, tests, and `git diff --check`. During self-hosting it must switch to the new CLI without weakening any existing gate. CI additionally runs offline Lychee until the new local-link implementation has demonstrated equivalent or stronger coverage; retaining Lychee as an independent defense is acceptable.
