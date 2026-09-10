# 0011: Generic bootstrap attribution

- Status: accepted
- Date: 2026-09-10
- Authority: the owner requested removal of private source-project references and the duplicate source notice from current files, and confirmed that the original project contains only their work and agent-assisted contributions.
- Updates: public source-attribution wording in [decision 0003](0003-frozen-seed-oracle.md) and legal-file packaging in [decision 0008](0008-project-license-and-owner.md).

## Decision

Use generic bootstrap names for the frozen checker, source manifest, compatibility documentation, and repository-specific policy label. Remove private repository locators from current source records. Identify the corresponding pilot as `private-pilot`, retain its recorded measurements and hash-verified policy, and state that its source locator is withheld.

Retain the copied checker, workflow, link-checker configuration, and pilot policy byte-for-byte. Content hashes and characterization tests continue to enforce those snapshots. The production engine remains independent of every source and pilot project.

The project-owned bootstrap is distributed under the existing BBW-Research MIT terms. Remove the duplicate `NOTICE`; retain the unchanged `LICENSE` in every wheel, source distribution, zipapp, and vendored-source handoff. Package core metadata declares `MIT` and only `LICENSE` through PEP 639. This owner-directed packaging change preserves the copyright notice and license permissions.

## Scope and controls

This cleanup applies to current files. Existing Git and pull-request history remains outside its scope. Historical documents use generic source labels while retaining their technical findings and qualification evidence.

Renaming a scanned policy rule and its literal selectors still requires review under the normal policy gate. This attribution decision does not suppress ratchet findings or authorize a CI bypass.
