# 0010: Canonical Raften repository and review controls

- Status: accepted
- Date: 2026-09-10
- Authority: explicit user approval of the private repository rename and retention of the current review rules.
- Supersedes: repository identity and review-control statements in [decision 0008](0008-project-license-and-owner.md); follows [decision 0009](0009-raften-name.md).

## Context

The Raften product rename is merged and has passed hosted qualification. The GitHub repository still used the former name, and the release guide described stronger review requirements than the effective provider settings. The owner chose to keep the current rules and correct the documentation.

## Decision

Use `BBW-Research/raften` as the canonical GitHub repository, retaining repository ID `1354736712`. Keep the existing MIT license, owner, and CODEOWNERS mapping. Update current package and documentation URLs while preserving historical decisions, source provenance, and completed qualification records.

Retain the existing PR workflow for a single maintainer without requiring a second approver. The verified settings have one authoritative home in the [release guide](../release/index.md#repository-controls). Documentation correction does not weaken the live controls or change the tool's policy ratchets.

## Consequences

- Repository renaming and technical qualification are complete preparation steps; public visibility still depends on the separate [publication procedure](../release/publication.md).
- Consumers should use the canonical URL and recheck any repository allowlists or hosted-Action references.
- Existing pre-rename qualification records remain historical evidence; each release candidate requires fresh qualification.
