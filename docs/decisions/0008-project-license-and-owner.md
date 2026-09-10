# 0008: License the project under MIT in the BBW-Research repository

- Status: accepted
- Date: 2026-09-02
- Superseded in part: repository identity and review controls by [decision 0010](0010-canonical-repository-and-review-controls.md); licensing and ownership remain in effect.
- Attribution update: project-owned bootstrap wording follows [decision 0011](0011-generic-bootstrap-attribution.md).

## Context

Release artifacts need an explicit project license alongside the retained bootstrap notice in `NOTICE`. Package metadata and repository links also need one stable project owner before publication can be qualified.

## Decision

License `repo-context` under the MIT License with `Copyright (c) 2026 BBW-Research`. Retain the project-owned bootstrap MIT terms separately in `NOTICE`.

Use `BBW-Research/repo-context` as the canonical GitHub repository identity and `https://github.com/BBW-Research/repo-context` as the package repository and homepage URL. Assign policy, workflow, and release-sensitive paths to the writable GitHub user `@taiqihe` in `.github/CODEOWNERS`.

## Consequences

- Every wheel, source distribution, zipapp, and vendored-source handoff includes both `LICENSE` and `NOTICE`.
- Package core metadata declares the SPDX expression `MIT` and lists both legal files through PEP 639 metadata.
- The GitHub organization is not itself a valid CODEOWNERS principal; `@taiqihe` is the selected individual owner.
- The private `BBW-Research/repo-context` remote grants `@taiqihe` administrator access and enables code-owner review in the default-branch protection rule.
