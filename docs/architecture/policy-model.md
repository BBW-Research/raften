# Policy model

## Inputs

A run has four explicit inputs:

1. Repository root.
2. Policy file.
3. Working-tree state, including Git-tracked and non-ignored untracked files.
4. Optional base revision.

The same inputs must produce the same ordered diagnostics. Wall-clock time, locale, filesystem enumeration order, and network state must not affect results.

## Canonical paths

All paths are repository-relative POSIX strings. Reject absolute paths, backslashes, empty path components, `.` components, and parent traversal. Decode link destinations only after separating queries and fragments. A path that leaves the repository is external to the policy graph and must never be opened.

## Classification

Classification determines whether a file is scanned and which limits apply. Rule order is significant: the first matching `file_rule` wins. Exact `path_override` entries then narrow the effective limit. Pattern overrides are evaluated after exact overrides and from most specific to least specific; ambiguous equal-specificity matches are a configuration error.

The initial kinds are:

- `authored`: human- or agent-authored source, prose, configuration, tests, and scripts. Scanned by default.
- `generated`: reproducible machine output such as lockfiles or generated schemas. Excluded from authored context totals but still reported in audit inventory.
- `vendored`: third-party source retained in the repository. Excluded only through explicit narrow rules.
- `fixture`: intentionally large test or snapshot data. Governed by fixture-specific limits rather than silently excluded.
- `legal`: licenses and notices whose integrity matters more than context size. Reported but not split automatically.

A file with no matching rule is an error. The starter policy ends with a catch-all authored rule, so ordinary repositories remain governed by default.

## Limits

Each scanned file has a warning threshold and a hard threshold. Warning diagnostics are non-blocking in `check` unless policy promotes them. Hard-threshold violations block.

Context sets are named collections of explicit paths and optional patterns. They account for the combined bytes an agent is expected to load for a task, such as the root instruction path. Missing required members are errors. The first implementation measures bytes only; token estimates may be added later as advisory output, never as the authoritative gate.

## Documentation graph

Configured documentation roots are index files, not merely directories. Markdown documents under each root directory become graph nodes. Local Markdown links become directed edges after canonical resolution.

Hierarchical mode adds structural requirements:

- Every directory containing governed Markdown has an `index.md`.
- An index directly links its sibling documents.
- An index directly links each immediate child directory's `index.md`.
- Every governed document is reachable from at least one configured root.
- Local targets and configured fragments exist.
- Authored documentation symlinks are rejected by default.

The graph must include every ancestor directory between a document and its configured root, even when an intermediate directory contains no non-index Markdown. This fixes the ancestor-discovery gap in the seed checker.

## Base revision and ratchet

The base revision supplies both the old policy and old file contents. For a current file above its ordinary hard limit:

- It fails when the base revision did not contain the file.
- It fails when the base file was within the ordinary limit.
- It fails when its current byte size exceeds its base byte size.
- It may pass only while equal to or smaller than the already-oversized base file.

This locks in every partial reduction without maintaining a stale ceiling map.

Policy comparison separately rejects silent weakening: increased limits, expanded exclusion rules, removed documentation roots, removed required entrypoint targets, weakened context sets, and ungoverned new exception records. A repository may intentionally change policy through owner review, but the default CI path must surface the weakening rather than treating configuration as unquestioned authority.

## Exceptions

An intentional exception is structured data with an exact path or narrow pattern, owner, rationale, tracking reference, creation date, and optional expiry. Migration debt captured during adoption is separate from intentional exceptions. Generated and vendored classifications are also separate. The CLI must explain which mechanism affected a path.
