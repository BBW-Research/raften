# Architecture boundaries

## Target package

The target implementation lives under `src/repo_context/`. Keep the package decomposed by policy responsibility rather than by command. The expected shape is:

```text
src/repo_context/
├── __init__.py
├── __main__.py
├── cli.py
├── command_paths.py
├── config.py
├── debt.py
├── diagnostics.py
├── document_checks.py
├── docs.py
├── git_executable.py
├── git_records.py
├── inventory.py
├── init_preparation.py
├── init_recovery.py
├── init_safety.py
├── init_transaction.py
├── initialization.py
├── markdown.py
├── markdown_lines.py
├── markdown_links.py
├── markdown_normalization.py
├── matcher.py
├── model.py
├── policy_comparison.py
├── policy_domains.py
├── policy_ratchet.py
├── ratchet.py
├── report.py
├── report_common.py
├── report_data.py
├── report_emergency.py
├── report_json.py
├── report_sarif.py
├── report_text.py
├── repository_errors.py
├── run_model.py
├── runner.py
├── size_policy.py
├── sizes.py
└── worktree.py
```

This is a target boundary, not a requirement to create empty modules immediately. Add each module when its phase begins.

## Dependency direction

The dependency direction is intentionally one-way:

```text
cli -> runner -> inventory/config -> pure checks -> model/diagnostics
  \-> report -> run_model/model/diagnostics
runner -> initialization -> inventory/config/model
```

- `model.py` contains immutable domain records and no filesystem or subprocess access.
- `config.py` parses and validates TOML into model records. It does not scan a repository.
- `git_executable.py` resolves an absolute Git executable through a sanitized search path that excludes relative, empty, and selected-repository entries. It does not invoke Git.
- `git_records.py` purely decodes and validates NUL-delimited index, path, tree, and object records. It has no subprocess or worktree access.
- `inventory.py` is the public repository facade and the only module that invokes Git or reads base-revision blobs. Its exact root, snapshot, and base-object contract is documented in [Repository inventory](inventory.md).
- `command_paths.py` validates public repository-relative path arguments once and converts failures into stable configuration diagnostics, distinguishing strict configured paths from native candidate paths such as the filename accepted by `explain`.
- `initialization.py` owns first-adoption policy, debt, and clean-state orchestration; `init_safety.py` anchors the validated root and no-follow parent chain, `init_preparation.py` owns destination preflight and artifact staging, `init_transaction.py` coordinates atomic activation and error translation, and `init_recovery.py` owns artifact identities, ownership-guarded cleanup, and rollback. Initialization is exposed through the runner facade rather than imported directly by the CLI.
- `matcher.py` owns the [version 1 repository path and glob semantics](../specs/repository-paths-and-globs-v1.md). No other module may call `fnmatch` or invent matching behavior.
- `markdown.py` extracts normalized local links and anchors. It does not decide policy violations.
- `markdown_lines.py` defines the LF, CRLF, and CR physical-line model shared by Markdown extraction.
- `markdown_links.py` implements supported inline/reference syntax, while `markdown_normalization.py` owns reference-label and safe local-destination normalization without repository access.
- `docs.py` builds the documentation graph and emits document diagnostics.
- `document_checks.py` evaluates graph structure, targets, entrypoints, and reachability without discovering files or performing I/O.
- `size_policy.py` compiles patterns and resolves rule, override, and exception provenance without reading repository content.
- `sizes.py` classifies plaintext and evaluates file and context-set budgets through an injected snapshot reader. Its complete behavior is defined by the [version 1 file and context budget contract](../specs/file-budgets-v1.md).
- `debt.py` strictly parses, captures, and renders the first-adoption migration sidecar without repository access.
- `ratchet.py` compares current authored files with injected Git or manifest baselines and reconciles proven migration debt with raw size diagnostics.
- `policy_ratchet.py` owns ordered file-rule and override comparison and assembles the complete policy result. `policy_domains.py` compares documentation, entrypoint, context, ratchet-setting, and exception guarantees; `policy_comparison.py` contains their shared typed value and diagnostic helpers.
- `diagnostics.py` defines stable diagnostic identities, locations, severity, and structured payloads.
- `run_model.py` contains immutable command results without filesystem or presentation behavior.
- `report.py` dispatches pure text, JSON, and SARIF renderers without changing diagnostic meaning. `report_common.py` owns envelope primitives, `report_data.py` projects typed run data for both human and machine renderers, and `report_emergency.py` preserves a fixed-shape `INT001` document if normal rendering fails. Format modules never inspect the filesystem or depend on one another.
- `repository_errors.py` owns the shared structured-error boundary for repository helpers without importing the inventory facade.
- `runner.py` orchestrates checks, explanation, and initialization entrypoints and returns typed results. It contains no presentation logic.
- `cli.py` maps arguments, exit codes, and output streams onto the runner.
- `worktree.py` joins validated repository paths, performs no-follow filesystem metadata inspection, and owns snapshot-verified current-content reads without invoking Git.

Circular imports are a design failure. Resolve them by moving shared immutable concepts into `model.py`, not by adding runtime import tricks.

## Repository boundary

The engine accepts an explicit repository path and must work from any current working directory. It must not infer its target repository from the installed package location. All repository-relative paths use canonical POSIX separators internally, including on Windows.

The consuming repository owns:

- `repo-context.toml`.
- Local wrapper scripts and CI invocation.
- Documentation roots and context sets.
- Classification rules and intentional exceptions.
- Branch protection and ownership of policy files.

The engine owns:

- Configuration validation and deterministic semantics.
- Git-visible inventory.
- File classification and byte accounting.
- Documentation graph construction.
- Base-revision comparisons.
- Diagnostics and output formats.

## Offline boundary

Runtime checks must not perform network requests. Remote-link validation is outside the core product. Local links, local fragments, repository history, and policy comparisons are in scope. Release tooling may use network access, but release behavior must remain separate from `repo-context check` and `repo-context audit`.

## Source-fixture boundary

`tools/check_repository_policy.py` is a frozen source oracle copied from scene-maker. Production modules must not import it. Characterization and paired-compatibility tests may import or execute it by path. Normal local validation, bootstrap, and CI select the standalone package through `scripts/context-check`; oracle execution within those workflows is test-only, never the repository policy entrypoint.
