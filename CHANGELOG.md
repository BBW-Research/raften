# Changelog

All user-visible changes to `raften` are recorded here. Version headings use PEP 440 versions and ISO dates.

## Unreleased

### Fixed

- Disable Git filesystem monitors with the supported Boolean configuration instead of making current Git attempt to execute the platform null device.
- Replace the porcelain cleanliness probe with a raw index, `HEAD`, and worktree comparison that never executes repository-configured content filters, streams uninspected blobs, and verifies inspected blobs during one-file-at-a-time evaluation.

### Changed

- Removed the duplicate source `NOTICE`; all distribution formats retain the unchanged MIT `LICENSE`.
- Replaced private source-project identifiers with generic bootstrap references while retaining the frozen checker and pilot policy content hashes.
- Made the source and development history public at `BBW-Research/raften`.
- Renamed the GitHub repository to `BBW-Research/raften`, updated package links, and aligned publication guidance with the existing review controls.
- Renamed the product, distribution, Python package, CLI, and report identity to Raften. New policies use `raften.toml` and `raften.debt.json`; existing adopters retain their policy history with `--config repo-context.toml`.
- Archived the completed standalone-tool plan and recorded the private repository's hosted CI, CODEOWNERS, and protected-branch controls.
- Split near-limit implementation, test, and completion-evidence files by responsibility; removed malformed repository-specific Codex agent definitions; and extended ownership to agent guidance and configuration.

## 1.0.0 - 2026-09-02

### Added

- Initial standalone CLI with strict version 1 TOML policy, deterministic diagnostics, file and policy ratchets, documentation graph validation, audit and explain reports, and safe first-adoption initialization.
- Hash-locked isolated wheel and source-distribution builds, deterministic dependency-free zipapp output, and clean-environment qualification on macOS and Linux with Python 3.12 and 3.13.
- MIT project licensing by BBW-Research with the project-owned bootstrap notice retained in every distribution format.
