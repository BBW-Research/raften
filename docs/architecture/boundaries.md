# Architecture boundaries

## Target package

The target implementation lives under `src/repo_context/`. Keep the package decomposed by policy responsibility rather than by command. The expected shape is:

```text
src/repo_context/
├── __init__.py
├── __main__.py
├── cli.py
├── config.py
├── diagnostics.py
├── docs.py
├── inventory.py
├── markdown.py
├── matcher.py
├── model.py
├── ratchet.py
├── report.py
├── runner.py
└── sizes.py
```

This is a target boundary, not a requirement to create empty modules immediately. Add each module when its phase begins.

## Dependency direction

The dependency direction is intentionally one-way:

```text
cli -> runner -> checks -> inventory/config/model -> standard library
                     -> diagnostics/report
```

- `model.py` contains immutable domain records and no filesystem or subprocess access.
- `config.py` parses and validates TOML into model records. It does not scan a repository.
- `inventory.py` is the only module that invokes Git or reads base-revision blobs.
- `matcher.py` owns documented path-pattern semantics. No other module may call `fnmatch` or invent matching behavior.
- `markdown.py` extracts normalized local links and anchors. It does not decide policy violations.
- `docs.py` builds the documentation graph and emits document diagnostics.
- `sizes.py` classifies plaintext and evaluates file and context-set budgets.
- `ratchet.py` compares current policy and current files with the base revision.
- `diagnostics.py` defines stable diagnostic identities, locations, severity, and structured payloads.
- `report.py` renders text, JSON, and SARIF without changing diagnostic meaning.
- `runner.py` orchestrates checks and returns a result object. It contains no presentation logic.
- `cli.py` maps arguments, exit codes, and output streams onto the runner.

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

`tools/check_repository_policy.py` is a frozen source oracle copied from scene-maker. Production modules must not import it. Characterization tests may import it by path. The bootstrap wrapper may execute it until the self-hosting gate, after which it remains only as a historical parity fixture or is moved to a test fixture without changing its bytes.
