# 0008: License the project under MIT in the BBW-Research repository

- Status: accepted
- Date: 2026-09-02

## Context

Release artifacts need an explicit project license distinct from the retained scene-maker provenance in `NOTICE`. Package metadata and repository links also need one stable project owner before publication can be qualified.

## Decision

License `repo-context` under the MIT License with `Copyright (c) 2026 BBW-Research`. Retain the upstream scene-maker MIT terms and provenance separately in `NOTICE`.

Use `BBW-Research/repo-context` as the canonical GitHub repository identity and `https://github.com/BBW-Research/repo-context` as the package repository and homepage URL. Assign policy, workflow, and release-sensitive paths to the writable GitHub user `@taiqihe` in `.github/CODEOWNERS`.

## Consequences

- Every wheel, source distribution, zipapp, and vendored-source handoff includes both `LICENSE` and `NOTICE`.
- Package core metadata declares the SPDX expression `MIT` and lists both legal files through PEP 639 metadata.
- The GitHub organization is not itself a valid CODEOWNERS principal; `@taiqihe` is the selected individual owner.
- Hosted ownership enforcement still requires an existing remote repository, explicit write access for `@taiqihe`, and enabled code-owner review in the default-branch protection rule.
