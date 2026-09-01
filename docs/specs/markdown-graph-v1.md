# Version 1 Markdown and documentation graph

This contract defines the supported Markdown subset, local-destination normalization, anchors, documentation discovery, graph requirements, and `DOC` diagnostics. Configuration shapes belong to the [version 1 configuration schema](configuration-v1.md), canonical repository glob matching belongs to the [path and glob contract](repository-paths-and-globs-v1.md), and verified content retention belongs to the [file and context budget contract](file-budgets-v1.md).

## Inputs and separation

Markdown extraction receives a canonical source path, decoded UTF-8 text, and the inventory-derived set of known repository directories. It performs no repository access and returns immutable links and anchors with one-based source positions. LF, CRLF, and CR are the recognized physical line endings; other Unicode separators remain ordinary text. Documentation evaluation receives the parsed policy, one Git-visible inventory snapshot, and retained text from budget evaluation. It does not reopen files, enumerate the filesystem, invoke Git, or validate remote URLs.

Only lowercase `.md` paths become documentation graph nodes or fragment-anchor targets in version 1. Configured entrypoint sources are parsed with the same Markdown subset regardless of extension so their required outbound links can be checked, but a non-`.md` entrypoint does not supply fragment anchors. Extraction may retain Markdown outside configured roots so fragments reached through local links can be checked, but only root-contained, non-excluded Markdown becomes a governed graph node.

## Ignored regions

The extractor uses a stateful scan rather than regular-expression-only parsing. It ignores link and anchor syntax inside:

- fenced code blocks opened by at least three backticks or tildes after no more than three leading spaces and closed by the same character with a run at least as long;
- inline code spans delimited by equal-length backtick runs;
- an unescaped `<!--` through the next `-->`, including multiline comments.

An unclosed fence or comment remains ignored through end of file. An unmatched inline backtick run is ordinary text.

## Links and references

Version 1 extracts inline navigation links and images with balanced labels and destinations. Destinations may be bare or angle-bracketed and may have an ignored single- or double-quoted or parenthesized title. Backslash escapes for ASCII punctuation are decoded at the ordered source-markup step below.

Full, collapsed, and shortcut reference links and images are supported. A reference label contains at most 999 source characters. Reference definitions occupy one physical line, may use a bare or angle-bracket destination plus an optional title, and do not create links themselves. Labels decode character references, trim and collapse Unicode whitespace, and use Unicode case folding. The first definition for a normalized label wins. An unresolved, overlong, or malformed reference is ordinary text.

Each occurrence is retained in source order. A source-level destination recognized as an external URI scheme or `//host` after Markdown escape and character-reference decoding is omitted before local percent and path validation; this boundary prevents remote-URL validation. A scheme or network path encoded with percent escapes is omitted only after the strict percent-decoding step below. Images remain distinct from navigation links. Malformed Markdown that does not form one of these supported constructs is ignored deterministically.

## Destination normalization

The extractor preserves the raw destination and normalizes a local destination in this order:

1. Split at the first literal `#`, then split the preceding portion at the first literal `?`. The query does not participate in lookup.
2. Validate every percent escape and percent-decode the path and fragment separately to strict UTF-8. Replacement decoding is forbidden.
3. Decode Markdown backslash escapes and character references.
4. Reject a root drive qualifier, omit a decoded URI scheme or `//host`, then reject decoded NUL, control characters, backslashes, remaining drive-qualified components, and absolute `/path` spelling.
5. Resolve `.` and safe `..` components relative to the source document directory. A component that would move above the repository root is unsafe.
6. Preserve exact case and Unicode spelling. Do not perform Unicode normalization.
7. Treat an empty path as the source document. Treat a trailing slash, a final `.` or `..` component, or an inventory-known directory as a directory and append `index.md`.

Encoded separators and traversal components are interpreted only after decoding, so they cannot bypass repository-boundary checks. A nonexistent trailing-slash destination still normalizes to its expected `index.md` and receives a missing-target diagnostic later. Fragment comparison is exact and case-sensitive after percent decoding.

## Anchors

Version 1 extracts ATX headings with one through six `#` markers and setext headings. Heading display text keeps code-span content and resolved-link label text, removes formatting delimiters and supported inline HTML start tags, end tags, comments, declarations, processing instructions, and CDATA spans, and decodes character references once. An unresolved full reference is ordinary text, so both of its bracket groups contribute display text after punctuation removal.

The project-defined GitHub-style slug algorithm lowercases the display text, trims it, converts each whitespace run to `-`, removes Unicode punctuation except `-` and `_`, and preserves Unicode letters, numbers, marks, and symbols. Leading and trailing hyphens are removed. An empty result creates no heading anchor.

Heading identifiers are unique in source order. The first available base slug is used; collisions try `-1`, `-2`, and higher until unused. This also handles literal suffix collisions deterministically. Real `id` attributes on inline HTML start tags outside ignored regions create exact, case-sensitive explicit anchors. Nonstandard heading-attribute extensions such as `{#id}` are not syntax in version 1.

## Discovery and directories

For each configured root, its directory governs every current Git-visible lowercase `.md` path at or below that directory unless a documentation exclusion pattern matches. Deleted, sparse-missing, and other absent entries are not graph nodes. A governed symlink produces `DOC001`; version 1 requires `allow_authored_symlinks = false` and evaluation never follows the symlink.

The governed set is the sorted union across roots. Every directory between a governed document and each containing root directory enters the hierarchy, including an ancestor that contains no direct Markdown file. Each directory record has its expected `index.md`, direct sibling documents, and immediate child directories.

If an exclusion matches a configured root, evaluation emits `CFG013` for that root because the policy is dynamically inconsistent.

## Targets, structure, and reachability

When local-target checking is enabled, a target must be a present Git-visible regular file or symlink. Deleted, sparse-missing, other, and absent paths are missing. Directory destinations check their normalized `index.md`. No target check follows a symlink or opens content outside the snapshot.

When fragment checking is enabled, the normalized target must be retained Markdown with the requested heading or explicit anchor. A fragment on unavailable or non-Markdown content is missing.

Only navigation links to governed Markdown nodes create graph edges. Images and navigation links to other local assets can be target-checked but never create reachability edges or satisfy sibling, child-index, or entrypoint navigation requirements. Link-looking syntax inside a recognized image label is alt text, not an independent link or asset occurrence.

When enabled, every hierarchy directory requires its expected index, that index must link each direct sibling document other than itself, and it must link every immediate child directory's expected index. These are direct-edge requirements; a transitive route does not satisfy them.

Reachability is a deterministic multi-source traversal from every present configured root. Cycles are valid. Each governed document not reached from at least one root receives one diagnostic.

Configured entrypoints are parsed with the same rules but do not become graph roots. Each must be a present regular retained text document, and each configured target must have a direct navigation link from that entrypoint.

## Diagnostics

All `DOC` diagnostics are blocking errors and sort by source path, real source position, code, and structured details. Link failures use the opening `[` position.

| Code | Meaning |
| --- | --- |
| `DOC001` | A governed Markdown path is a disallowed authored-document symlink. |
| `DOC002` | A required root or governed document has unavailable plaintext content. |
| `DOC003` | A hierarchy directory lacks its expected `index.md`. |
| `DOC004` | A directory index lacks a direct link to a sibling document. |
| `DOC005` | A directory index lacks a direct link to an immediate child index. |
| `DOC006` | A configured entrypoint is unavailable. |
| `DOC007` | A configured entrypoint lacks a required direct navigation link. |
| `DOC008` | A local-looking Markdown destination is unsafe. |
| `DOC009` | A normalized local target is absent or not a current file. |
| `DOC010` | A requested fragment is absent from its Markdown target. |
| `DOC011` | A governed Markdown document is unreachable from all configured roots. |
