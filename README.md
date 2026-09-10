# Raften

Policy checks for code and documentation in agentic coding projects. Raften enforces file and context budgets, checks documentation navigation, and catches policy weakening against Git history.

Source and issue tracking are on [GitHub](https://github.com/BBW-Research/raften).

The standalone `check`, `audit`, `explain`, and guarded `init` commands are implemented under `src/raften/` and run locally without installation or network access. `scripts/context-check`, local validation, bootstrap, and CI use this engine; the verbatim bootstrap checker remains only as a characterized test oracle.

## Start here

After unpacking the archive:

```sh
scripts/bootstrap
```

That initializes a local Git repository when needed and runs the offline validation suite. No package installation is required for the starter.

The completed build and release qualification record is retained in [`docs/plans/completed/standalone-tool.md`](docs/plans/completed/standalone-tool.md). The original end-to-end Codex assignment remains under [`docs/prompts/codex-build.md`](docs/prompts/codex-build.md).

Useful commands:

```sh
scripts/context-check
scripts/test
scripts/validate
PYTHONPATH=src python3 -m raften --help
```

The target public interface is:

```sh
raften check
raften audit
raften explain PATH
raften init
```

See the [documentation index](docs/index.md) for the specification, architecture, decisions, acceptance criteria, test matrix, and source provenance.

The distribution, command, and Python import are all `raften`. New projects use `raften.toml`; existing projects can keep their policy path with `--config repo-context.toml`. This repository's `scripts/context-check` wrapper selects that existing path to preserve policy history.

The [release and consumption guide](docs/release/index.md) covers hash-locked offline builds, native and Docker qualification, installed wheels, pinned zipapps, vendored source wrappers, and migration from the former name.

## License

`raften` is released under the [MIT License](LICENSE).
