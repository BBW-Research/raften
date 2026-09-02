# 0006: Build releases from a hash-locked offline wheelhouse

- Status: accepted
- Date: 2026-09-02
- Dependency review date: 2026-09-02

## Context

The first release needs isolated wheel and source-distribution builds without adding runtime dependencies. The release workflow therefore needs a build frontend and the transitive packages that frontend imports, while the PEP 517 backend remains the Setuptools version selected by [decision 0004](0004-setuptools-build-backend.md).

The review used official PyPI metadata and upstream release histories for [build 1.5.0](https://pypi.org/project/build/1.5.0/), [packaging 26.3](https://pypi.org/project/packaging/26.3/), [pyproject-hooks 1.2.0](https://pypi.org/project/pyproject-hooks/1.2.0/), and [Setuptools 84.0.0](https://pypi.org/project/setuptools/84.0.0/). All four versions are more than seven days old, support the project's Python matrix, and publish platform-independent wheels. PyPI records Trusted Publishing provenance for the first three wheels. Setuptools 84.0.0 lacks a Trusted Publishing attestation, so its exact official PyPI wheel hash and the upstream ownership and release history were reviewed explicitly.

The newer build 1.6.0 was released on 2026-08-27 and is ineligible under the seven-day age gate on the decision date. Build 1.5.1 is yanked because its maintainers consider its behavior breaking. Build 1.5.0 is not yanked, has no listed vulnerability, requires only `packaging>=24.0` and `pyproject-hooks` on the supported platforms, and retains the default behavior of building a source distribution before building the wheel from that source distribution.

The exact release-input wheel hashes are kept in `requirements/release.txt`. Before any build or qualification, the release tooling requires the exact reviewed universal-wheel filenames, verifies every SHA-256, and copies the already verified bytes into a newly owned temporary directory. The release build installs those files with `--require-hashes` and no dependency resolution, then gives the PEP 517 isolation environment access only to that private staged wheelhouse. Fetching the wheelhouse is the sole networked preparation step; building, installing, and exercising artifacts are separate network-disabled operations.

Linux qualification uses full official Python Bookworm images because Git is part of the runtime contract and the slim images omit it. The immutable multi-architecture image digests are `sha256:581429e3df12d76e6af4be5ab7d0e7fc2013eb57dc23d2de691411c8efdbb970` for Python 3.12.14 and `sha256:8b9a8b28d9cc221c6ab5d40e9cfcd99429959f6a8f5171612a99147975ab043f` for Python 3.13.14. Both images exceed the dependency age gate. Qualification uses cached images with pulling disabled, networking disabled, a read-only root filesystem, dropped capabilities, and read-only source and artifact mounts.

## Decision

Use build 1.5.0 as the release frontend. Hash-lock its complete supported-platform dependency closure and Setuptools 84.0.0 as platform-independent wheels in `requirements/release.txt`.

Keep wheelhouse acquisition explicit in `scripts/fetch-release-tools`. Make `scripts/build-release` refuse a dirty or non-repository worktree, export exact regular blobs from the reviewed `HEAD` commit, build only that export, create a fresh frontend environment, install only privately staged locked wheels, retain normal PEP 517 build isolation, build the wheel from the generated source distribution, validate archive structure, build the deterministic dependency-free zipapp, and emit `SHA256SUMS`.

Use `scripts/qualify-artifacts` for native clean-environment installation tests and `scripts/qualify-linux` for the pinned Docker matrix. Neither qualification path may use the network. Runtime dependencies remain empty.

## Consequences

- A release operator must acquire and retain the four verified wheels before going offline.
- A release candidate cannot be built from uncommitted or ignored worktree content; Git object bytes from the resolved clean commit are the sole source.
- Upgrading any release input requires a fresh age, compatibility, ownership, provenance, release-history, and hash review.
- Wheel and source-distribution reproducibility is not promised by this decision; the zipapp is byte-deterministic for a fixed source tree and `SOURCE_DATE_EPOCH`.
- A fresh Linux machine must pull the pinned image digests once before network-disabled qualification can run.
- The GitHub matrix independently exercises native Ubuntu x86-64 and macOS arm64 while local Docker qualification exercises the available Docker architecture.
