# Release and consumption

## Support contract

The first stable release supports CPython 3.12 and 3.13 on macOS and Linux. Windows is not qualified. Runtime behavior requires Git 2.39.5 or newer, as defined by the [repository inventory boundary](../architecture/inventory.md), plus only the Python standard library; building distributions uses the separately reviewed and hash-locked release environment in `requirements/release.txt`.

The public distribution is `repo-context-policy`, the import package is `repo_context`, and the stable command is `repo-context`. Version 1.0.0 is the first stable artifact version. The project is MIT licensed by BBW-Research, and its canonical repository is `https://github.com/BBW-Research/repo-context`. The package version has one authoritative source in `repo_context.__version__`; release tags and changelog headings must use the same PEP 440 version. Stable versions follow `MAJOR.MINOR.PATCH`, with major increments for incompatible CLI, configuration, or machine-output changes.

## Build and qualify

Start from a reviewed clean commit. Acquire the release wheelhouse while network access is available, then perform every subsequent step offline:

```console
$ scripts/fetch-release-tools /path/to/empty-wheelhouse
$ SOURCE_DATE_EPOCH=$(git log -1 --format=%ct) scripts/build-release /path/to/empty-wheelhouse /path/to/empty-output
$ PYTHON=python3.12 scripts/qualify-artifacts /path/to/empty-output /path/to/empty-wheelhouse
$ PYTHON=python3.13 scripts/qualify-artifacts /path/to/empty-output /path/to/empty-wheelhouse
$ scripts/qualify-linux /path/to/empty-output /path/to/empty-wheelhouse
```

`scripts/build-release` refuses a dirty or non-repository source, exports exact regular blobs from the reviewed `HEAD` commit, and builds only that export. It verifies the wheelhouse's exact filenames and SHA-256 values against `requirements/release.txt`, copies the verified bytes into an owned temporary directory, creates a fresh frontend environment, builds an sdist and then a wheel from that sdist through normal PEP 517 isolation, builds the zipapp with sorted stored entries and a normalized timestamp, validates all three archives, and writes sorted `SHA256SUMS`. Qualification first copies the exact three artifacts and checksum manifest into owned temporary storage, then validates, installs, and executes only those staged bytes. It independently verifies and privately stages the locked wheelhouse before exposing it to sdist build isolation. The build and qualification steps discard ambient Python and pip controls and set pip to local-wheelhouse-only operation. `scripts/qualify-linux` additionally enforces Docker `--network=none`, a read-only root filesystem, dropped capabilities, and immutable Python image digests.

Run the native artifact qualifier on both supported Python versions on macOS. The Docker script covers both Python versions on Linux using the local Docker architecture, while the required GitHub matrix covers native Ubuntu x86-64 and macOS arm64. Do not publish or tag unless all matrix jobs and the stable `Required repository policy` check pass.

## Consumption modes

### Installed package

Verify the release checksum manifest, install the wheel into a dedicated environment without dependencies, and keep a project-local wrapper as the stable invocation point:

```console
$ python3 -m venv .tools/repo-context
$ .tools/repo-context/bin/python -m pip install --no-deps /verified/repo_context_policy-1.0.0-py3-none-any.whl
$ .tools/repo-context/bin/repo-context check --repo .
```

Use the exact reviewed release filename. A wrapper should execute `.tools/repo-context/bin/repo-context "$@"` and the project should pin the artifact SHA-256 alongside its update procedure.

### Pinned zipapp

Copy the release `repo-context-<version>.pyz` into a project-controlled tools directory, record its line from `SHA256SUMS`, and verify that checksum before adoption. Invoke it with either supported interpreter:

```console
$ python3 tools/repo-context-<version>.pyz check --repo .
```

The zipapp contains the `repo_context` Python sources, a generated entrypoint, `LICENSE`, and `NOTICE`. It requires no installation and is byte-identical when built from the same source with the same `SOURCE_DATE_EPOCH`. The consuming repository's `scripts/context-check` should name the pinned file explicitly rather than select a moving download.

### Vendored source

Copy the reviewed `src/repo_context` directory to a versioned project location such as `vendor/repo-context/src/repo_context`, retain both `LICENSE` and `NOTICE`, and make the project-local wrapper select only that source tree:

```sh
#!/bin/sh
set -eu
ROOT=$(CDPATH= cd -P -- "$(dirname -- "$0")/.." && pwd -P)
PYTHONPATH="$ROOT/vendor/repo-context/src" exec python3 -P -m repo_context check --repo "$ROOT" "$@"
```

Do not append ambient `PYTHONPATH`; that could select an unintended package. Record the vendored version, source commit, and tree hash, and update the copy as one reviewed change.

## Changelog process

Add user-visible changes to the `Unreleased` section of `CHANGELOG.md` in the same change that introduces them. At release time, replace `Unreleased` contents with a heading containing the exact version and ISO date, then create a new empty `Unreleased` section. Separate breaking changes, features, fixes, and governance or packaging changes where those categories are present; omit empty categories. Diagnostic identities, configuration schema changes, command behavior, and supported-platform changes are always user-visible.

## Repository controls

The GitHub repository requires the stable `Required repository policy` check on the default branch, pull requests, at least one approving review, dismissal of stale approvals, approval of the most recent reviewable push, code-owner review, conversation resolution, and administrator enforcement. Individual matrix job names are not required checks; the stable aggregator owns that interface while the matrix may evolve.

`.github/CODEOWNERS` assigns `@taiqihe` to the repository's agent guidance, Codex configuration, policy, workflow, packaging, licensing, and release surfaces. The exact protected path set is asserted by the release qualification suite. GitHub reports no parsing errors, and `@taiqihe` has explicit administrator access. Provider settings, rather than workflow and CODEOWNERS text alone, enforce protected-branch review.
