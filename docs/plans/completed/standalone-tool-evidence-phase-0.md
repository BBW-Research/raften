# Standalone tool phase 0 evidence

This companion to the [completed standalone-tool plan](standalone-tool.md) retains phase evidence so the executable checklist remains compact. Evidence moved here only after its phase gate was complete.

## Phase 0 completion evidence

- Completed: 2026-09-01.
- Baseline: root commit `6b4263d` records the validated 50-file starter before implementation changes.
- Provenance: tests verify the recorded bootstrap snapshot and owner, every copied file's verbatim mode and Git blob, and the checker SHA-256. The frozen checker remains byte-identical at `bb796f2304f3692089a5e87cef55a7fbe3e7c4c9521d6d2299b738a84f7ebd11`.
- Characterization: 74 tests cover the complete source surface and deterministic CLI streams. Real temporary repositories isolate ambient Git configuration, use fixed identities and timestamps, commit reproducible base states, mutate tracked and untracked content, and run both seed and target entrypoints. Structured assertions were sufficient, so Phase 0 added no golden output file.
- Intended differences: `docs/reference/bootstrap-seed.md` maps the known intended differences to retained seed evidence and an owning target phase.
- Packaging: accepted decision 0004 pins `setuptools==84.0.0` after a 2026-09-01 review of release age, Python compatibility, ownership, maintenance, license, dependency footprint, execution surface, and artifact provenance. Runtime dependencies remain empty and no environment-manager lock is warranted yet.
- Validation: `scripts/validate` and the offline Lychee check pass without network access. The seed policy check, compile checks, CLI help, diff check, and all 74 tests pass locally on Python 3.12.14 and 3.13.13 without package installation. The suite also passes with hostile ambient `GIT_DIR` and injected Git configuration.
- Review: the read-only Phase 0 reviewer found and verified fixes for Git-environment isolation, Windows-invalid fixture names, overly broad symlink skips, deterministic commit evidence, and dependency-review completeness. No review finding remains open.
- Remaining work: Phase 1 begins immutable models and strict TOML parsing; no production seed behavior was extracted during Phase 0.
- Risks: local cross-version evidence is macOS arm64; Linux and Windows execution remains dependent on the supported-version CI and release matrix. Symlink assertions skip only when the host cannot create symlinks. Isolated distribution builds will require the reviewed backend artifact to be available and will receive explicit offline artifact verification in Phase 8.
