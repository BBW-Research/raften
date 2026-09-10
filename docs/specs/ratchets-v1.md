# Version 1 file and policy ratchets

This contract defines base availability, file migration debt, first-adoption debt capture, the conservative policy partial order, diagnostic reconciliation, and `RAT` identities. Current classification and ordinary limits belong to the [file and context budget contract](file-budgets-v1.md), policy shapes belong to the [configuration schema](configuration-v1.md), paths and pattern overlap belong to the [path and glob contract](repository-paths-and-globs-v1.md), and exact base-object access belongs to the [repository inventory contract](../architecture/inventory.md).

## Inputs and separation

File-ratchet evaluation receives a valid current policy, sorted current file assessments, and exactly one baseline source. A Git baseline consists of a valid policy parsed from the resolved base commit, its sorted tree metadata, and an injected exact-object blob reader. A first-adoption baseline consists of a valid migration-debt manifest. The evaluator performs no filesystem access, invokes no subprocess, reads no wall clock, and never mutates the worktree or index.

Policy comparison receives two valid version 1 policies and emits findings independently of current file, context, or documentation violations. Base settings govern the comparison, so disabling a current ratchet cannot disable its own weakening diagnostic.

## Current candidates and ordinary limits

A current path enters the file ratchet only when it is a present regular file, its current first-match classification is `authored`, its current ordinary policy scans it, its bytes are plaintext, and its exact raw byte size is greater than its current ordinary hard limit. Exact equality with the ordinary hard limit is not migration debt. Generated, vendored, fixture, legal, NUL-containing, invalid-UTF-8, deleted, symlink, gitlink, and other non-regular paths do not enter the file ratchet.

The current ordinary hard limit, including the current selected path override but excluding every intentional exception, is authoritative for both the current candidate test and the base oversized test. Policy comparison separately reports an attempted limit increase. This makes an intentional limit tightening take effect immediately without consulting superseded base thresholds.

When file-size comparison is enabled, an ordinary-oversized authored path is classified once even if an intentional exception disables its effective scan. This preserves the ordinary ratchet without reopening content. Every classified payload retains a `sha256:` identity of its exact bytes for possible first-adoption capture; LF, CRLF, multibyte UTF-8, and every other byte remain unnormalized.

## Git baseline truth table

Only current candidates require base lookup or blob reads. Identity is the exact canonical path; content similarity, Git rename detection, and matching object IDs never infer a rename. A staged or unstaged rename is therefore one deletion and one addition.

For each candidate:

- No exact base path produces `RAT002` when new oversize is forbidden.
- A base symlink, gitlink, tree, other non-regular type, NUL-containing blob, or invalid-UTF-8 blob produces `RAT005`. Regular mode `100644` and executable mode `100755` are the same eligible file type.
- A regular plaintext base blob at or below the current ordinary hard limit produces `RAT003`.
- A current size greater than the exact base blob size produces `RAT004`.
- An equal or smaller current size whose base was already above the current ordinary hard limit is migration debt and emits no blocking ratchet finding.
- A current path at or below its ordinary hard limit has no migration record and does not read its base blob, even if an earlier revision was oversized.

`ceiling_bytes` is populated only when an eligible oversized Git blob or manifest entry supplies a real migration ceiling, including a growth violation. New paths, ineligible types or content, and base versions within the ordinary limit retain any observed base size separately but have no ceiling.

The immediate selected base blob is the only Git ceiling. If a 100 KiB file shrinks to 60 KiB and that state is committed, 60 KiB is the next comparison ceiling; a later 61 KiB version fails without updating configuration or a manual map.

## Size-diagnostic reconciliation

Budget evaluation retains the raw `LimitState.HARD` assessment and initially emits `CTX002` without assuming history. After a successful base comparison, final run diagnostics suppress `CTX002` only for paths proven to be migration debt. `CTX002` remains for a new path, an ineligible base, growth, an unavailable comparison, or disabled comparison. Advisory findings and the immutable raw assessment remain available to audit and explain output.

## Base availability

When file-size comparison is enabled, an absent base ref and a nonempty ref consisting only of ASCII `0` are distinct unavailable states. Both permit current-state checks, produce nonblocking `RAT001` with a structured reason, and never invoke Git. Any all-zero length is accepted to preserve the established CI sentinel behavior. A policy that disables file-size comparison has no requested comparison and therefore emits no unavailability note.

A nonzero requested ref must resolve to an available commit through the isolated inventory boundary. A missing ref, a commit unavailable in shallow history, or another resolution failure is operational `GIT006`; the engine never fetches or guesses. An unavailable tree, selected blob, or wrong object type is operational `GIT007`.

The base policy is read as exact blob bytes and parsed with a source label containing the commit identity and policy path. Invalid base policy bytes produce configuration diagnostics at that source. When a resolved base commit has no policy and current file comparison is enabled, a valid current first-adoption manifest may supply the baseline; without that manifest the requested historical comparison is operational `GIT007`. A disabled current comparison needs no first-adoption manifest when the base has no policy. A base config path present as a non-regular object is `GIT007`, not first adoption. Once the base contains a policy, the Git tree and blobs take precedence and any current migration manifest is ignored.

## First-adoption manifest

For a canonical config path, the sidecar replaces a final `.toml` suffix with `.debt.json`; the default is `raften.debt.json`. `init --capture-debt` captures only current candidate paths. It never writes a pattern, classification rule, exception, or exclusion.

The sidecar is strict UTF-8 JSON with this exact logical schema:

```json
{
  "schema_version": 1,
  "entries": [
    {
      "path": "legacy.txt",
      "size_bytes": 61440,
      "content_identity": "sha256:0000000000000000000000000000000000000000000000000000000000000000"
    }
  ]
}
```

Root and entry keys are exact. The schema version is integer `1`; entries are sorted by unique canonical exact Git path; sizes are positive integers; and identities use `sha256:` plus 64 lowercase hexadecimal digits. An entry `path` is always literal filename data, never a selector, so Git-valid glob metacharacters, backslashes, and JSON-escaped control characters retain exact identity. Rendering uses two-space indentation, literal Unicode, LF, and one final newline. Parsing rejects duplicate JSON keys, duplicate paths, unsafe or noncanonical candidate paths, non-finite numbers, unknown keys, missing keys, wrong types, and invalid identities with existing `CFG` identities. A selector-shaped field such as `pattern` is unknown; metacharacters inside the required exact `path` value have no pattern semantics.

The captured identity records provenance; later partial reduction changes the identity and is still allowed when the size does not grow. A manifest entry supplies the same size ceiling truth table as a Git blob. Falling within the current ordinary limit removes debt automatically, while an unlisted oversized path or growth beyond the captured size fails.

## Policy partial order

The version 1 comparison is deliberately conservative where general glob-language containment is not proven. A structurally changed guarantee is surfaced for owner review instead of being guessed safe.

File rules use their unique names as record identity and retain first-match guarantees. Ordering transitions that can change which scanned rule supplies finite limits or move unscanned coverage ahead of an earlier scanned rule are surfaced when either the base exclusion or limit guard is enabled; disabling only one guard cannot defeat the other.

- A retained scanned rule keeps its selector tuple, scan state, classification, and relative order; warning and hard limits may only decrease.
- Removing a scanned rule, changing its selector tuple or classification, disabling scan, or reordering retained scanned rules is weakening.
- A retained unscanned rule may be removed, enabled, or have patterns removed while retaining its classification. It may not move ahead of a base scanned rule that previously preceded it. When it is enabled, any newly added pattern is evaluated as new scanned coverage rather than inheriting the old exclusion identity.
- Adding an unscanned rule or pattern is weakening whenever either exclusion expansion or limit increases are forbidden because it replaces finite enforcement with no file limit. This includes `config/*.json` and `schemas/*.json`; there are no built-in structured-data exemptions.
- A new scanned rule or newly scanned selector is accepted only when it remains authored wherever it may intercept base-authored coverage and its limits are no larger than every potentially overlapping scanned base rule. Conservative pattern overlap treats any pair not proven disjoint as potentially overlapping.

Path overrides use exact selector identity. Every base override must remain and neither limit may increase. A newly added exact or more-specific pattern override is weakening when it can displace a potentially overlapping tighter base override. Selector changes are removal plus addition.

Documentation roots outside every base root directory may be added because they expand governed coverage. A root added inside a base governed tree is a new reachability traversal seed and is weakening when base reachability is required because it can make an existing orphan pass without an inbound route. Documentation exclusions may only be removed, and a true directory-index, sibling-link, child-index-link, reachability, local-target, or fragment requirement may not become false. Every base entrypoint path remains, and its required targets may only be added.

Context sets use unique names as identity. Every base set remains; exact paths and pattern selectors may only be added; and limits may only decrease. A selector rewrite is treated as removal plus addition rather than an unproved containment relation.

Every base ratchet Boolean that is true remains true. File-limit, exclusion, documentation, and entrypoint comparisons are gated by the corresponding base setting, never by the current setting. Context membership and exception governance remain monotone whenever a base policy is compared.

Intentional exceptions use exact selector identity. Removing a `scan = false` exception is tightening. Other exact-selector removal avoids `RAT013` only when current ordinary or pattern fallback enforcement, evaluated while records are active, is no weaker in scan state and both byte limits. An effective policy that would produce `CFG015` is fail-closed: repairing such a base state is safe only when complete finite scanning replaces it, while leaving the path unscanned is weakening. A current `CFG015` state is surfaced conservatively by policy comparison because its exact path need not be present in the inventory that produces run-time configuration diagnostics. Other pattern-selector removal is conservatively surfaced because arbitrary coverage cannot be proven tighter. Removing replacement limits from an exact exception uses the same effective fallback rule, while removing them from a pattern exception is surfaced conservatively. Shortening an expiry remains tightening because the retained expired record produces blocking `EXC002`; removing an expiry or extending it is broadening. A new selector, a change from forced scan toward ordinary or unscanned behavior, newly added replacement limits, or increased replacement limits is also broadening. A new exception is surfaced even when its mandatory owner, rationale, tracking reference, and dates are valid; otherwise the addition rule would be vacuous because malformed governance never reaches policy comparison. Metadata text changes alone do not broaden relief.

## Diagnostic identities

File and policy ratchet violations are blocking errors. Comparison unavailability is a note. Diagnostics use current repository paths or the current policy path, structured base/current values, and the shared deterministic sort key.

| Code | Meaning |
| --- | --- |
| `RAT001` | File-size comparison is unavailable because no historical or first-adoption baseline applies. |
| `RAT002` | A current oversized authored path has no exact baseline path. |
| `RAT003` | The exact baseline version was within the current ordinary hard limit. |
| `RAT004` | An oversized authored file grew relative to its immediate baseline bytes. |
| `RAT005` | The baseline path has an ineligible file type or non-plaintext content state. |
| `RAT006` | A file-rule warning or hard limit increased. |
| `RAT007` | A path override was removed, increased, or displaced by weaker relief. |
| `RAT008` | Ordered file classification or scan coverage weakened. |
| `RAT009` | Documentation roots, reachability seeds, exclusions, or graph requirements weakened. |
| `RAT010` | A required entrypoint or target was removed. |
| `RAT011` | A context set was removed or weakened. |
| `RAT012` | A configured base ratchet was disabled. |
| `RAT013` | An intentional exception was added or changed so effective fallback relief may broaden. |
