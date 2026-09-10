# 0009: Name the product Raften

- Status: accepted
- Date: 2026-09-10
- Authority: explicit user selection
- Supersedes: product and package identity in [decision 0007](0007-distribution-name.md)

## Context

The former distribution name `repo-context-policy`, command `repo-context`, and import `repo_context` split the product across three identities. The bare `repo-context` distribution and command also overlap an unrelated Python package. The name should accommodate checks over code, documentation, tests, scripts, and configuration.

The user selected Raften after a naming review. Exact PyPI, npm, and crates.io metadata lookups found no package entries for `raften` during that review. These checks neither reserve a namespace nor establish trademark clearance.

## Decision

Use **Raften** as the product name and **Policy checks for code and documentation** as its short description. The Python distribution, import package, and sole console command are all `raften`. `python3 -m raften` remains available for source-tree use. Wheel and source-distribution names use `raften`; zipapps use `raften-<version>.pyz`. JSON and SARIF identify the tool as `raften` while retaining diagnostic codes and schema versions.

New projects default to `raften.toml` and the config-derived `raften.debt.json` sidecar. Existing policy and debt schemas remain valid. Existing adopters should keep their tracked filenames and pass `--config repo-context.toml`, which also selects `repo-context.debt.json` when a first-adoption manifest is needed. Do not silently discover a second policy path or install a `repo-context` command alias.

This repository retains its adopted `repo-context.toml` and its CODEOWNERS entry. `scripts/context-check` invokes Raften with that explicit path so Git comparisons continue reading the same historical policy. A filename-only migration would otherwise make earlier revisions appear to have no policy. The shared engine needs no repository-specific migration branch.

The MIT license, owner, and existing `BBW-Research/repo-context` GitHub identity from [decision 0008](0008-project-license-and-owner.md) remain in effect. Selecting the product name does not create or rename a remote repository, change visibility, or publish a package.

## Consequences

- Consumers update executable and import references; existing policies can remain in place using the explicit config option.
- Current specifications and release tooling use Raften. Completed build evidence, historical decisions, and hash-frozen pilot inputs retain their original identities.
- The version constant remains 1.0.0. Earlier artifact qualification is historical evidence under the former name; freshly built Raften artifacts still require the full supported-platform qualification described in the [release guide](../release/index.md) before publication.
- Namespace availability must be rechecked immediately before registration or publication.

## Implementation verification

On 2026-09-10, `BASE_REF=HEAD scripts/validate` passed on macOS using CPython 3.12.14 and 3.13.13, with 523 tests and one skip per interpreter. Each run included offline archive bootstrap, package metadata and archive checks, and executable zipapp smoke tests. The adopted policy reported zero errors, warnings, or notes against `HEAD`.

The CLI regression suite verifies that an explicit legacy policy uses the exact Git baseline and still rejects a limit increase with `RAT006`. A read-only review of all 45 renamed source modules, packaging, documentation, and frozen provenance found no actionable issues. Fresh wheel/sdist builds and the Linux release matrix remain publication gates, not claims of this source validation.
