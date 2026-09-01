# 0004: Use a pinned Setuptools build backend

- Status: accepted
- Date: 2026-09-01
- Dependency review date: 2026-09-01

## Context

The project needs a PEP 517 build backend but does not need runtime dependencies, native extensions, dynamic version discovery, or executable build scripts. The starter already uses declarative PEP 621 metadata and Setuptools package discovery in `pyproject.toml`.

The dependency review used the official [Setuptools 84.0.0 PyPI metadata](https://pypi.org/project/setuptools/84.0.0/) and [Setuptools quickstart](https://setuptools.pypa.io/en/latest/userguide/quickstart.html). Version 84.0.0 was released on 2026-08-08, more than seven days before this decision, requires Python 3.10 or newer, and publishes a platform-independent Python 3 wheel. The documented minimal backend configuration uses `setuptools.build_meta` and does not require `wheel` as a separate build dependency.

The canonical PyPI project identifies the Python Packaging Authority as author, three current owner or maintainer accounts, the `pypa/setuptools` source repository, an MIT license expression, and a long active release history. Its dependency metadata has no unconditional `Requires-Dist` entries; all declared dependencies belong to extras that this project does not request. The backend executes Python only when a build frontend invokes PEP 517 hooks and is not imported by the runtime or test commands. The reviewed wheel and source archive were uploaded to the official PyPI project with published SHA-256 hashes but without PyPI Trusted Publishing, so Phase 8 must reassess artifact provenance and hash-lock any offline release inputs rather than treating this version pin as artifact verification.

Alternative backends would add a migration with no demonstrated correctness or distribution benefit at this phase. An in-tree backend would create packaging code that this project would have to maintain and validate across platforms.

## Decision

Use `setuptools.build_meta` and pin the sole build requirement to `setuptools==84.0.0`. Keep runtime dependencies empty.

Do not add a package-manager lock file in Phase 0. The project has no selected environment manager or resolved development dependency set, and the exact PEP 517 backend requirement is already deterministic. Phase 8 must perform a fresh dependency review before selecting and pinning any build frontend or release environment.

## Consequences

- Direct `PYTHONPATH=src` development and validation remain installation-free and offline.
- Isolated distribution builds request one known backend version and do not install an unnecessary `wheel` requirement.
- Building from source requires that exact backend to be available to the build frontend; producing and testing offline distribution inputs remains Phase 8 work.
- A backend upgrade requires another age, compatibility, provenance, and release-history review.
