# Raften product specification

- Status: authoritative implementation target
- Version: draft v1
- Date: 2026-08-31

## Purpose

`raften` is a local repository policy tool for coding-agent projects. It keeps high-value authored material bounded enough to load selectively, ensures documentation can be discovered from stable entrypoints, and prevents existing context debt or policy exceptions from silently growing.

It is not a general code-quality linter. Its unit of concern is the repository as an information environment for humans and agents.

## Required outcomes

The completed tool must:

1. Inventory Git-visible tracked and non-ignored untracked paths deterministically.
2. Classify plaintext files and enforce warning and hard byte budgets.
3. Enforce smaller budgets for instruction files, root entrypoints, and documentation indexes.
4. Build a documentation graph rooted in configured index files.
5. Verify directory indexes, sibling routing, child-index routing, local target existence, fragment existence, and root reachability.
6. Measure named multi-file context sets such as the agent bootstrap path.
7. Compare current files and policy with a Git base revision so existing debt can only shrink.
8. Distinguish generated data, vendored material, fixtures, legal material, migration debt, and intentional exceptions.
9. Emit stable diagnostics in human-readable text, JSON, and SARIF.
10. Explain the effective policy for any path.
11. Initialize a clean policy and optionally capture migration debt for an existing repository.
12. Run without network access and without repository-specific engine code.

## Non-goals

Version 1 does not:

- Measure cyclomatic complexity, source-code architecture, style, formatting, test coverage, or dependency security.
- Decide whether a large file is semantically well factored. It reports a context boundary; maintainers decide the correct split.
- Validate remote URLs during the core run.
- Rewrite documentation or source files automatically.
- Estimate model-specific tokens as a blocking measure.
- Replace repository-specific `scripts/validate` orchestration.
- Enforce GitHub branch protection or CODEOWNERS by itself.

## Terminology

- **Repository root:** explicit directory containing the target Git worktree.
- **Git-visible:** returned by the equivalent of `git ls-files --cached --others --exclude-standard`; ignored files are not governed by default.
- **Plaintext:** a regular file without NUL bytes that decodes as UTF-8.
- **Authored file:** source, prose, tests, scripts, or configuration intended to be read and maintained directly.
- **Documentation root:** configured Markdown index file from which governed documentation must be reachable.
- **Context set:** named group of files representing a common agent-loading path.
- **Ordinary limit:** the effective hard threshold derived from classification and path overrides.
- **Migration debt:** a file already above its ordinary limit when a repository adopts the policy.
- **Intentional exception:** reviewed structured permission for a narrowly identified path to use a different policy.
- **Base revision:** Git commit or ref used to compare prior files and prior policy.

## Command-line contract

The installed executable is `raften`.

### `raften check`

Run blocking checks and return a policy exit code.

```text
raften check [--repo PATH] [--config PATH] [--base-ref REF] [--evaluation-date YYYY-MM-DD] [--format text|json|sarif]
```

Defaults:

- `--repo`: current directory.
- `--config`: `raften.toml` relative to the repository root.
- `--format`: `text`.
- `--base-ref`: absent; current-state checks still run, while ratchet comparisons requiring history are reported as unavailable rather than guessed.
- `--evaluation-date`: current UTC calendar date captured once; an explicit canonical date makes expiry evaluation reproducible.

### `raften audit`

Produce a non-mutating inventory and trend report. Hard violations remain visible, but the command exits successfully unless configuration or repository access fails.

```text
raften audit [--repo PATH] [--config PATH] [--base-ref REF] [--evaluation-date YYYY-MM-DD] [--format text|json]
```

The report includes largest governed files, files above warning thresholds, migration debt, documentation depth and fan-out, unreachable documents, context-set totals, classification counts, exception status, and changes from the base revision when supplied.

### `raften explain`

Explain exactly how one repository-relative path is handled.

```text
raften explain PATH [--repo PATH] [--config PATH] [--base-ref REF] [--evaluation-date YYYY-MM-DD] [--format text|json]
```

The explanation includes matched rule, rule order, kind, scan status, effective thresholds, matching override, context-set membership, documentation-graph membership, migration status, and exception record. `--base-ref` enables exact Git or first-adoption migration status; without it history remains explicitly unavailable rather than inferred.

### `raften init`

Create a starter policy without rewriting source or documentation.

```text
raften init [--repo PATH] [--config PATH] [--capture-debt] [--force]
```

Without `--capture-debt`, initialization fails when current authored files exceed the generated ordinary limits. With `--capture-debt`, the command records a deterministic baseline manifest containing current oversized file sizes and content identities. It must never add broad exclusions automatically. The manifest schema and config-derived sidecar path are defined by the [version 1 ratchet contract](ratchets-v1.md#first-adoption-manifest).

Initialization requires a clean repository before evaluation and again before writing. It never follows destination symlinks. `--force` replaces only existing regular initialization artifacts and never bypasses dirty-state or uncaptured-debt refusal. A capture writes a versioned sidecar even when it has zero entries; a non-capture run refuses to leave a stale sidecar silently.

### Exit codes

- `0`: command completed and, for `check`, no blocking violations exist.
- `1`: `check` completed and found blocking policy violations.
- `2`: invalid configuration, invalid arguments, Git failure, unsafe path, unsupported repository state, or other operational error.

No traceback is printed for expected user or policy errors. Unexpected internal failures may include a traceback only when an explicit debug flag is added in a later version.

## Configuration contract

The default file is `raften.toml`. Version 1 uses strict TOML parsed with Python's `tomllib`. Unknown keys are errors so misspellings cannot silently disable checks.

An existing `repo-context.toml` remains usable with an explicit `--config repo-context.toml`; there is no automatic legacy-path discovery. The [release migration guide](../release/index.md#existing-projects) explains how to preserve historical policy comparisons.

The package-owned bytes returned by `raften.config.render_starter_policy()` are the normative generic configuration example used by initialization. A repository's root `raften.toml` is its adopted policy and may add project-specific classifications or tighter limits. The implementation must support these sections:

- `version`
- `repository`
- `output`
- ordered `file_rule` records
- `path_override` records
- `documentation`
- `entrypoint` records
- `context_set` records
- `ratchet`
- `exceptions`
- optional intentional exception records added by the implementation spec

The parser returns immutable typed records. Validation errors name the exact key and source location when available.

The exact table shapes, cross-field invariants, static pattern precedence, intentional-exception record format, and configuration diagnostic codes are defined by the [version 1 configuration schema](configuration-v1.md). Classification, raw-byte limits, context-set accounting, and exception application are defined by the [version 1 file and context budget contract](file-budgets-v1.md). Markdown extraction, local-destination normalization, anchors, graph evaluation, and `DOC` diagnostics are defined by the [version 1 Markdown and documentation graph contract](markdown-graph-v1.md).

## Inventory and path semantics

The tool requires Git for version 1. It discovers current paths with tracked plus non-ignored untracked semantics. The inventory retains deleted tracked paths as explicit missing records; they are absent from current-content checks but may be read from the base revision for comparison. The [repository inventory boundary](../architecture/inventory.md) defines root validation, Git isolation, snapshot states, base-object access, races, and `GIT` diagnostic identities.

Internal paths use `/` regardless of platform. Reject:

- Absolute paths.
- `..` traversal.
- Backslashes in configured paths.
- Non-canonical `.` or duplicate separators.
- NUL bytes.
- Link destinations that resolve outside the repository.

Symlinks are inspected with `lstat`. The tool never follows a symlink outside the repository. Authored-document symlinks are rejected by default. Other symlink policy is classification-dependent and must be explicit.

Filesystem and Git outputs are sorted before evaluation. Diagnostic ordering is by path, source position, diagnostic code, then message-independent structured detail.

## Pattern semantics

Do not inherit Python `fnmatch` behavior implicitly. The complete normative contract is [version 1 repository paths and globs](repository-paths-and-globs-v1.md). In summary, version 1 defines repository globs:

- `*` matches zero or more characters except `/`.
- `?` matches one character except `/`.
- `**` matches across path components.
- Character classes follow the documented subset implemented by the matcher.
- A pattern without `/` matches a basename at any depth only when explicitly prefixed by `**/` in configuration; do not add Gitignore-style magic silently.
- Patterns are repository-relative and case-sensitive on every platform.

Rules are evaluated in declaration order and first match wins. Version 1 requires exactly one final catch-all scanned authored rule. Exact path overrides take precedence over pattern overrides. Ambiguous equal-precedence pattern overrides are configuration errors rather than order-dependent surprises.

## Plaintext and size accounting

A regular file is plaintext when it contains no NUL byte and decodes as UTF-8. Byte counts use raw file bytes, not Unicode character counts and not line-ending-normalized content.

Each scanned file receives:

- `warn_bytes`: advisory threshold.
- `hard_bytes`: blocking threshold.

A warning does not fail `check` by default. A hard violation does. The target defaults are 20 KiB warning and 25 KiB hard for authored files, with smaller path overrides for high-fan-out entrypoints and indexes.

The engine must not hardcode special paths such as `config/*.json` or `schemas/*.json`. Repositories classify generated schemas or large declarative data explicitly. Extension alone does not prove that a file is generated.

Audit output reports at least size, effective thresholds, classification, matching rule, and percentage of hard limit.

## Context sets

A context set measures the aggregate bytes of files commonly loaded together. Members may be exact paths and, after the initial implementation, narrow patterns. Missing exact members are blocking configuration violations.

A file is counted once per context set even if multiple selectors match it. Context-set warning and hard limits behave like file limits. The starter defines `bootstrap` as `AGENTS.md`, `ARCHITECTURE.md`, and `docs/index.md`.

Version 1 uses bytes as the authoritative measure. An optional approximate token count may be reported later, but it must be clearly advisory and must not require a model tokenizer or network access.

## Documentation graph

For every configured root index:

1. Determine its governed directory.
2. Discover every governed Markdown file below that directory, excluding only explicit documentation exclusions.
3. Add all ancestor directories between every document and the root, even when an ancestor contains only a child directory.
4. Require `index.md` for every governed directory when hierarchical mode is enabled.
5. Parse local Markdown links and anchors.
6. Normalize directory links to their `index.md` target.
7. Verify local file targets and fragments.
8. Require each index to link direct sibling documents and immediate child indexes when those options are enabled.
9. Traverse the graph from the root and report every unreachable document.

Navigation requirements use Markdown links. Images may be checked as local assets but do not create documentation reachability edges. Links inside code spans, fenced code blocks, or HTML comments do not create edges.

The parser must support the local-link forms used by repository documentation, including inline links, angle-bracket destinations, and reference-style links. If a CommonMark dependency becomes necessary, it requires a decision record and must preserve offline operation. Regex-only parsing without documented limitations is not acceptable.

Fragments are matched against explicit HTML IDs and deterministic GitHub-style heading slugs defined and tested by this project. Duplicate heading behavior must be specified. Percent-encoded destinations are decoded safely after separating query and fragment components.

## Base-size ratchet

When `--base-ref` is supplied, the tool reads both the prior policy and prior file blobs from Git without checking out another tree.

For each current authored plaintext file above its current ordinary hard limit:

- A new path fails.
- A path whose base version was within the ordinary limit fails.
- A path larger than its base version fails.
- A path equal to or smaller than its already-oversized base version may pass as migration debt.
- A path that falls within the ordinary limit ceases to be migration debt automatically.

This comparison is authoritative. A manually maintained legacy ceiling must not allow a partially reduced file to grow back.

`init --capture-debt` may create a baseline manifest for first adoption when no prior policy exists. That manifest records exact paths, base sizes, and content identities. After the first committed policy, ordinary Git base comparison takes precedence. Exact eligibility, type-change, unavailable-base, manifest, diagnostic-reconciliation, and partial-order behavior is defined by the [version 1 ratchet contract](ratchets-v1.md).

## Policy ratchet

When the base revision contains a policy, `check` reports weakening attempts, including:

- Increased warning or hard limits.
- Removal or weakening of path overrides.
- Expansion of unscanned classifications or exclusion patterns.
- Removal of documentation roots or graph requirements, or addition of a reachability seed inside an already governed tree.
- Removal of required entrypoint targets.
- Removal or weakening of context sets.
- Addition or broadening of exception relief, including a removal or limit fallback that exposes weaker enforcement; every surfaced addition retains its required governance record for review.
- Disabling base-size comparison.

The engine surfaces these changes; repository review and branch protection determine whether an intentional policy migration is accepted. Do not provide a generic `--ignore-policy-weakening` switch in version 1. The conservative structural comparison and stable `RAT` identities are defined by the [version 1 ratchet contract](ratchets-v1.md#policy-partial-order).

## Exceptions and classifications

Generated, vendored, fixture, and legal material are classifications, not intentional exceptions. Migration debt is derived from history, not an exception. An intentional exception must contain:

- Exact path or narrow pattern.
- Owner.
- Rationale.
- Tracking issue or decision reference.
- Creation date.
- Optional expiry.
- Replacement thresholds or scan behavior.

Expired exceptions fail. Broad catch-all exception patterns fail validation. `explain` must make the governing mechanism visible.

## Diagnostics

Diagnostics are records with:

- Stable code.
- Severity.
- Repository-relative path when applicable.
- Optional line and column.
- Concise message.
- Structured details.
- Optional remediation hint.

Initial code families:

- `CFG`: configuration and canonical-path errors.
- `GIT`: inventory and base-revision errors.
- `CTX`: file and context-set budget violations.
- `DOC`: documentation graph, target, and fragment violations.
- `RAT`: file and policy ratchet violations.
- `EXC`: exception governance violations.
- `INT`: unexpected internal consistency failures.

Codes are assigned in the implementation phase and then treated as public API. Tests assert codes and structured fields, not only prose.

Text output is concise and sorted. JSON has an explicit schema version. SARIF maps paths and positions without fabricating source locations. Summary counts are derived from diagnostics rather than maintained separately. Exact stream, escaping, audit-metric, explain-filtering, initialization, and machine-schema behavior is defined by the [version 1 commands and output contract](output-v1.md).

## Performance and safety

The target is responsive on repositories with 100,000 Git-visible paths. Read file contents at most once per run unless a test proves caching unnecessary. Avoid retaining all large file contents after parsing. Use bounded subprocess calls with explicit arguments and no shell interpolation.

Never execute repository files, Markdown, configuration values, hooks, or generated commands. Never follow local links outside the repository. Never make network requests. Treat malformed UTF-8, invalid Git output, and disappearing files as deterministic operational errors or diagnostics according to documented policy.

## Compatibility and distribution

Support Python 3.12 and 3.13 on macOS and Linux before the first stable release, as recorded in [decision 0005](../decisions/0005-supported-platforms.md). Local development and tests must continue to work through `PYTHONPATH=src` without package installation.

The first release should produce a wheel and source distribution. An optional zipapp is desirable for vendored offline use. A consuming starter template may pin a release or vendor the package source, but its `scripts/context-check` wrapper remains the stable project interface.

## Definition of done

The tool is complete when every item in `docs/quality/acceptance.md` passes, the target CLI replaces the seed checker in `scripts/context-check`, the repository validates itself with the new engine, the fixture suite demonstrates intended parity and intended differences from scene-maker, and the active implementation plan records no unfinished release-blocking work.
