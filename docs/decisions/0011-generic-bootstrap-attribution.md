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

Renaming a scanned policy rule and its literal selectors requires an explicit migration review. This decision introduces no engine exemption or general permission to bypass CI.

## Reviewed policy migration

The owner approved a one-time required-check exception for [PR #5](https://github.com/BBW-Research/raften/pull/5), reviewed at `731bbeede47c8fbc89057d4c4a95cf63dd1e05e6`. Only the scanned rule name and its selector tuple changed in policy. Across seven path moves, all 203 retained files kept their classifications, scanning, byte limits, overrides, exceptions, and context membership; this new decision record inherited existing authored enforcement. The four frozen snapshots and `LICENSE` retained their exact bytes and modes.

The normal comparison against the preceding policy reported two `RAT008` findings, `scanned_rule_removed` and `authored_classification_removed`, in [PR workflow run 34480711544](https://github.com/BBW-Research/raften/actions/runs/34480711544). Local validation completed 523 tests with one expected macOS capability skip, and the wheel, source archive, and zipapp built from the reviewed commit qualified on macOS with Python 3.12 and 3.13. These checks supplied migration evidence; they did not make the original-base comparison pass.

The approved cleanup merged normally as `7e6af9ec4df997bf26c7abff556a0732090f30ff`. The strict `Required repository policy` check was restored immediately after the merge, and a full protection readback matched the saved settings. Other branch controls stayed in place. The [initial main workflow](https://github.com/BBW-Research/raften/actions/runs/34482582333) retains the original-base comparison; the completion-evidence follow-up uses the migrated policy as its base under the restored required check.
