# repo-context starter

This repository is an implementation starter for a standalone checker that keeps coding-agent repositories bounded, navigable, and economical to load into context windows.

It contains a verbatim snapshot of scene-maker's working `tools/check_repository_policy.py`, a clean policy that validates this repository, a target Python package skeleton, characterization tests, and a phase-by-phase Codex build contract. The standalone engine is **not finished** in this starter: `scripts/context-check` uses the source snapshot while `repo-context check`, `audit`, `explain`, and `init` remain deliberate stubs.

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
