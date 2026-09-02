# Version 1 file and context budgets

This contract defines deterministic file classification, plaintext detection, byte thresholds, context-set accounting, intentional-exception application, audit records, and explain data. Configuration shapes and static validation belong to the [version 1 configuration schema](configuration-v1.md); repository paths and pattern matching belong to the [version 1 path and glob contract](repository-paths-and-globs-v1.md).

## Evaluation inputs

Budget evaluation receives a parsed policy, one Git-visible inventory snapshot, a snapshot-verified content reader, and an explicit evaluation date. It does not consult the wall clock, network, locale, filesystem enumeration order, or filename extensions. Inventory paths, assessments, retained text documents, and diagnostics are explicitly sorted.

Every policy pattern is compiled once before evaluation. The content reader is invoked at most once for each regular file that is effectively scanned, explicitly requested for text retention, or requires ordinary-oversize classification while file-size ratcheting is enabled. A retained path is classified and decoded even when its size policy is unscanned, but it receives no byte-limit state or size diagnostic. An ordinary-oversized authored path is likewise classified once even when an intentional exception disables effective scan, preserving the historical ratchet without a later reopen. A caller identifies paths needed for later Markdown parsing; text for a scanned path comes from the same raw read used for content classification and byte accounting.

## Classification and ordinary limits

File rules retain declaration order. The first rule containing a matching pattern wins, and the first matching pattern within that rule supplies provenance. The result records the rule index, pattern index, source pattern, classification kind, scan decision, and ordinary thresholds. A path that matches no rule produces `CFG014` and is not read.

An exact path override wins over every matching pattern override. Without an exact match, the matching pattern with the greatest configuration-defined specificity wins. An override remains visible in explain data even when its rule is unscanned, but it never enables scanning. For a scanned rule, ordinary warning and hard thresholds are the minimum of the rule and selected override values, so an override can tighten but cannot silently weaken ordinary policy.

The `authored`, `generated`, `vendored`, `fixture`, and `legal` kinds are explicit labels, not filename inferences. Each inventoried path retains its kind in audit data whether it is scanned, binary, missing, or non-regular. Generated and vendored files are unscanned only when a matching repository rule says so; `.json`, `.lock`, `.png`, and other extensions have no built-in exemption.

## Intentional exceptions

Intentional exceptions are applied after ordinary classification and override resolution. Exact selectors win over pattern selectors. Without an exact match, the matching pattern with greatest specificity wins; equal-specificity overlapping exception patterns are rejected statically with `CFG011` instead of using declaration order.

An exception is active through its `expires_on` date and expired when the explicit evaluation date is later. Every expired record produces `EXC002` and is not applied. An active exception may replace scan behavior, replace thresholds, or do both. Exception thresholds replace ordinary thresholds and may therefore be larger; ordinary thresholds remain separately available for audit, explain, and later ratchet evaluation. Effective unscanned paths have no effective thresholds.

If a valid static record cannot produce a complete policy for a path at run time, evaluation emits `CFG015` and does not read the file. Examples are enabling scan for an ordinarily unscanned rule without replacement thresholds, or attaching threshold-only relief to a path that remains unscanned.

## Snapshot-verified content reads

Current inventory records a regular file's mode, device, inode, raw size, modification time, and change time. The public repository reader reopens parent components and the leaf through descriptor-relative no-follow opens, compares descriptor metadata with the inventory identity before reading and again after reading, and verifies the returned byte count. The leaf open is nonblocking so a concurrent FIFO replacement cannot stall before type verification. Reads are bounded to the snapshot size plus one byte, so concurrent growth cannot cause unbounded memory or run time. A platform without the required secure open primitives fails closed with `GIT009` rather than following a path-based fallback.

Disappearance, type changes, intermediate symlinks or junctions, same-size replacement, and mutation during a read produce `GIT005`. Unrelated open, metadata, or read failures produce `GIT009`. Deleted, sparse-missing, symlink, and other non-regular entries are never opened as file content.

## Plaintext and file thresholds

A raw byte sequence is plaintext only when it contains no NUL byte and decodes completely with strict UTF-8. A UTF-8 byte-order mark decodes as the ordinary U+FEFF character. The NUL state takes precedence when bytes also contain invalid UTF-8. Invalid UTF-8 and NUL-containing files retain explicit content states but do not receive plaintext file-size diagnostics.

Byte size is `len(raw_bytes)`. UTF-8 code points, CRLF sequences, and all other bytes are counted exactly as stored; text is never newline-normalized for policy accounting.

For a plaintext scanned file with warning threshold `W`, hard threshold `H`, and raw size `S`:

- `S <= W` is within policy.
- `W < S <= H` produces advisory `CTX001`.
- `S > H` produces blocking `CTX002`.

Only the strongest file diagnostic is emitted. In particular, exceeding the hard limit produces `CTX002` without an additional warning diagnostic. Exact equality with the hard threshold remains an advisory warning because it is already above the warning threshold but does not exceed the hard threshold. Budget evaluation does not assume historical state; final run diagnostics suppress `CTX002` only after the [file ratchet](ratchets-v1.md#size-diagnostic-reconciliation) proves that exact path is non-growing migration debt. The immutable hard assessment remains available to audit and explain.

## Context sets

Each context set takes the union of its exact paths and all inventoried paths matching its patterns. Membership is path-sorted and de-duplicated, so overlap between selectors never counts a path twice within one set. The same file may be counted once in each of several independently configured sets.

Every present regular member contributes its inventory snapshot byte size, including unscanned, generated, vendored, NUL-containing, and invalid-UTF-8 files. Context accounting therefore does not force content reads and measures the exact material selected for that context rather than only authored plaintext.

An exact member must resolve to a present regular file. Absent, deleted, sparse-missing, symlink, and other non-regular exact members each produce blocking `CTX003` with a structured state. A pattern that matches no paths is valid, and a non-regular pattern match remains visible in membership data without contributing bytes or producing a missing-member diagnostic unless the same path is also exact.

Context thresholds use the same strict comparison as file thresholds: a total above the warning threshold and at or below the hard threshold produces advisory `CTX004`; a total above the hard threshold produces blocking `CTX005`; only the strongest aggregate diagnostic is emitted.

## Audit and explain data

Each file assessment exposes inventory state, classification, rule and pattern provenance, selected override, selected exception, ordinary and effective scan decisions, ordinary and effective thresholds, raw size when available, content state and SHA-256 identity when read, and threshold state for plaintext. Largest governed files sort by descending raw size with path as the tie-breaker. Classification counts retain every explicit kind.

Audit retains every governed inventory state. Sized paths sort by descending raw size with path as the tie-breaker; deleted, symlink, and other states without a raw size follow in path order. Explain resolution works for both inventoried and nonexistent canonical paths. It returns the same rule, override, exception, ordinary/effective policy, and context-set membership that evaluation would use; an assessment is attached only when the path exists in the supplied evaluation.

## Diagnostic identities

All diagnostics use immutable structured fields and the repository-wide deterministic sort key. Advisory diagnostics use warning severity; configuration, missing-member, expired-exception, and hard-limit diagnostics use error severity.

| Code | Meaning |
| --- | --- |
| `CFG014` | An inventoried path matches no file rule |
| `CFG015` | Runtime resolution produced an incomplete or ineffective file policy |
| `CTX001` | Plaintext file exceeds its warning threshold |
| `CTX002` | Plaintext file exceeds its hard threshold |
| `CTX003` | Required exact context-set member is not a present regular file |
| `CTX004` | Context-set total exceeds its warning threshold |
| `CTX005` | Context-set total exceeds its hard threshold |
| `EXC002` | Intentional exception is expired at the explicit evaluation date |
