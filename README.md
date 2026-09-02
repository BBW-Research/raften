# repo-context

This repository builds a standalone checker that keeps coding-agent repositories bounded, navigable, and economical to load into context windows.

The standalone `check`, `audit`, `explain`, and guarded `init` commands are implemented under `src/repo_context/` and run locally without installation or network access. The verbatim scene-maker checker remains the transitional `scripts/context-check` oracle until the Phase 7 self-hosting switch.

## Start here

After unpacking the archive:

```sh
scripts/bootstrap
```

That initializes a local Git repository when needed and runs the offline validation suite. No package installation is required for the starter.

To hand the implementation to Codex, use [`docs/prompts/codex-build.md`](docs/prompts/codex-build.md). Codex should then work through [`docs/plans/active/standalone-tool.md`](docs/plans/active/standalone-tool.md) until the self-hosted tool replaces the bootstrap checker.

Useful commands:

```sh
scripts/context-check
scripts/test
scripts/validate
PYTHONPATH=src python3 -m repo_context --help
```

The target public interface is:

```sh
repo-context check
repo-context audit
repo-context explain PATH
repo-context init
```

See the [documentation index](docs/index.md) for the specification, architecture, decisions, acceptance criteria, test matrix, and source provenance.
