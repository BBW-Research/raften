# repo-context

This repository builds a standalone checker that keeps coding-agent repositories bounded, navigable, and economical to load into context windows.

The standalone `check`, `audit`, `explain`, and guarded `init` commands are implemented under `src/repo_context/` and run locally without installation or network access. `scripts/context-check`, local validation, bootstrap, and CI use this engine; the verbatim scene-maker checker remains only as a characterized test oracle.

## Start here

After unpacking the archive:

```sh
scripts/bootstrap
```

That initializes a local Git repository when needed and runs the offline validation suite. No package installation is required for the starter.

Release qualification and the remaining external ownership decisions are tracked in [`docs/plans/active/standalone-tool.md`](docs/plans/active/standalone-tool.md). The original end-to-end Codex assignment remains under [`docs/prompts/codex-build.md`](docs/prompts/codex-build.md).

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

The [release and consumption guide](docs/release/index.md) covers hash-locked offline builds, native and Docker qualification, installed wheels, pinned zipapps, and vendored source wrappers. The distribution name is `repo-context-policy`; the command and import package remain `repo-context` and `repo_context`.

## License

`repo-context` is released under the [MIT License](LICENSE). The [upstream notice](NOTICE) retains the license and provenance of the scene-maker source from which part of the tool was derived.
