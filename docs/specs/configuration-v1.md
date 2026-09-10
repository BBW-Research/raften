# Version 1 configuration schema

`raften.toml` is a strict, UTF-8 TOML document. Version 1 rejects unknown keys, wrong TOML types, unsupported enum values, unsafe repository paths, malformed patterns, duplicate identities, ambiguous overrides, invalid limits, and inconsistent settings. Declaration order is preserved for records whose semantics depend on it.

Human-facing `name`, `reason`, `owner`, `rationale`, and `tracking_reference` values must be nonblank and reject C0, DEL, and C1 control characters whenever supplied.

The package-owned `raften.config.render_starter_policy()` bytes are the normative generic serialized example; the implementation does not contain a general-purpose TOML writer. The root [adopted policy](../../repo-context.toml) began from that template and may add repository-specific classifications or tighter limits without changing the generic initializer output. Its historical filename is selected explicitly by this repository's wrapper, as described in [decision 0009](../decisions/0009-raften-name.md).

## Root keys

The root accepts exactly these keys:

| Key | TOML shape | Required |
| --- | --- | --- |
| `version` | Integer | Yes; must be `1` |
| `repository` | Table | Yes |
| `output` | Table | Yes |
| `file_rule` | Array of tables | Yes |
| `path_override` | Array of tables | No |
| `documentation` | Table | Yes |
| `entrypoint` | Array of tables | No |
| `context_set` | Array of tables | No |
| `ratchet` | Table | Yes |
| `exceptions` | Table | Yes |

Optional arrays of tables default to empty immutable tuples. Every other collection is projected into a tuple in declaration order.

## Repository and output

`[repository]` requires exactly `inventory`, `encoding`, and `follow_symlinks`. Version 1 accepts only `inventory = "git-visible"`, `encoding = "utf-8"`, and `follow_symlinks = false`. A configured path is never resolved and a repository is never scanned while this table is parsed.

`[output]` requires exactly `default_format` and `stable_sort`. The command default must be `default_format = "text"`; JSON and SARIF remain explicit command selections. `stable_sort` must be `true`.

## File rules

Each `[[file_rule]]` accepts exactly `name`, `patterns`, `kind`, `scan`, `warn_bytes`, `hard_bytes`, and `reason`. `name`, a nonempty `patterns` array, `kind`, and `scan` are required. Names are nonblank and unique. Pattern values are unique both within one rule and across all rules.

`kind` is one of `authored`, `generated`, `vendored`, `fixture`, or `legal`. A scanned rule requires positive integer `warn_bytes` and `hard_bytes`, with `warn_bytes < hard_bytes`. An unscanned rule omits both limits, supplies a nonblank `reason`, and may not use the `authored` kind.

Exactly one rule must consist solely of `patterns = ["**"]`. That rule must be the final rule, use `kind = "authored"`, and enable scanning. Rules retain declaration order because classification uses the first match.

## Path overrides

Each `[[path_override]]` requires positive, increasing `warn_bytes` and `hard_bytes`, plus exactly one selector:

- `path` for one canonical exact path.
- `pattern` for a pattern containing at least one wildcard.

Exact selectors are unique and pattern selectors are unique. Exact overrides take precedence over pattern overrides. Pattern precedence uses this specificity tuple, compared lexicographically from greatest to least:

1. Number of fully literal path components.
2. Number of literal characters.
3. Number of path components.
4. Negative number of `**` components.
5. Negative number of other wildcards.

Equal-specificity patterns are accepted only when static analysis proves them disjoint through an aligned, differing literal path component. Ordinary wildcard components preserve later component alignment. Around `**`, only the anchored prefix before the first recursive component and anchored suffix after the last recursive component can prove disjointness; interior recursive matches remain conservatively ambiguous. Otherwise equal-specificity patterns are rejected rather than made declaration-order-dependent.

## Documentation

`[documentation]` requires exactly these keys:

- `roots`: a nonempty array of unique canonical paths ending in `index.md`.
- `exclude`: an array of unique repository patterns.
- `require_directory_indexes`.
- `require_sibling_links`.
- `require_child_index_links`.
- `require_root_reachability`.
- `check_local_targets`.
- `check_fragments`.
- `allow_authored_symlinks`.

Every flag is a TOML Boolean. Version 1 requires `allow_authored_symlinks = false` because the snapshot reader deliberately does not follow symlinks; a later alias contract may expand this without weakening repository-escape safety. A root may not also appear as an exact exclusion and may not be excluded by the global `**` pattern. Sibling-link and child-index-link requirements depend on directory-index requirements. Fragment checking depends on local-target checking. More general root-versus-exclusion overlap is evaluated by the matcher once repository inventory exists.

## Entrypoints and context sets

Each optional `[[entrypoint]]` has exactly one canonical `path` and a nonempty `required_targets` array. Entrypoint paths are unique. Targets are canonical and unique and may not include the entrypoint itself.

Each optional `[[context_set]]` requires a unique nonblank `name`, positive increasing limits, and at least one member from `paths` or `patterns`. Exact paths and patterns are unique within their arrays. Context patterns must be narrow: they contain a wildcard, have a fixed literal top-level directory before the first wildcard, and retain a literal filename portion after the last `/`. Membership overlap is valid because a file is counted once within each context set.

## Ratchets

`[ratchet]` requires exactly six Boolean keys: `compare_file_sizes`, `forbid_new_oversize`, `forbid_limit_increases`, `forbid_exclusion_expansion`, `forbid_removed_documentation_roots`, and `forbid_removed_entrypoint_targets`. `forbid_new_oversize = true` requires `compare_file_sizes = true`. Other false values remain syntactically representable so later base-policy comparison can report attempted weakening against a configured revision. The exact monotonic comparison belongs to the [version 1 ratchet contract](ratchets-v1.md).

## Intentional exceptions

`[exceptions]` requires exactly `require_reason`, `require_owner`, `require_tracking_reference`, and `allow_expired`, plus optional nested `[[exceptions.record]]` tables. Version 1 requires the first three governance flags to be true and `allow_expired` to be false.

Each exception record requires:

- Exactly one canonical `path` or narrow wildcard `pattern` selector.
- Nonblank `owner`, `rationale`, and `tracking_reference` strings.
- A TOML local date in `created_on`.
- An optional TOML local date in `expires_on` that is not earlier than `created_on`.
- Replacement scan behavior, a complete pair of replacement limits, or both when consistent.

`scan = false` may not be combined with byte limits. Selectors are unique within the exception table. Catch-all and other broad exception patterns are invalid. Pattern exceptions use the same specificity and conservative equal-specificity ambiguity rules as pattern overrides; exact exception selectors take precedence at evaluation time.

Configuration parsing does not consult the wall clock: the same bytes always produce the same model or diagnostics. Expiry relative to an evaluation date is a run-time exception check and receives that date as an explicit run input; an expired record then produces `EXC002`. Complete evaluation semantics are defined by the [version 1 file and context budget contract](file-budgets-v1.md).

## Paths and patterns

All configured paths and patterns are nonempty repository-relative POSIX strings. They reject absolute and drive-qualified paths, backslashes, control characters, trailing or repeated separators, and `.` or `..` components. Exact paths also reject glob metacharacters.

Patterns support `*`, `?`, `**`, and nonempty character classes such as `[abc]`, `[a-z]`, `[!abc]`, and `[**]`. Stars inside a character class are literals; outside a class, `**` must occupy a complete path component. Character classes may not be empty, nested, unclosed, unmatched, or contain malformed or descending ranges; a hyphen is literal only at a class boundary. Pattern interpretation is case-sensitive and belongs exclusively to `matcher.py`; parsing only validates syntax and static precedence properties. Full matching, recursive-component, Unicode, candidate-filename, and native-platform conversion behavior is defined by the [version 1 repository paths and globs contract](repository-paths-and-globs-v1.md).

## Configuration diagnostics

Every failure has a stable code and field path. Array-of-table indexes are zero-based, such as `file_rule[1].hard_bytes` and `exceptions.record[0].owner`. Unknown keys that cannot be represented unambiguously as dot components use escaped bracket notation such as `$["unknown.key"]`. Diagnostics are sorted by source path, real source position when available, code, field path, and structured details before `ConfigurationError` exposes its immutable tuple.

| Code | Meaning |
| --- | --- |
| `CFG001` | Invalid UTF-8 or TOML syntax |
| `CFG002` | Unknown key |
| `CFG003` | Missing required key or table |
| `CFG004` | Wrong TOML type |
| `CFG005` | Unsupported or empty value |
| `CFG006` | Unsafe or noncanonical exact path |
| `CFG007` | Malformed or invalid pattern |
| `CFG008` | Duplicate named record |
| `CFG009` | Duplicate path, pattern, or selector |
| `CFG010` | Missing or invalid file-rule catch-all |
| `CFG011` | Ambiguous equal-specificity pattern overrides or exceptions |
| `CFG012` | Invalid byte limits |
| `CFG013` | Internally inconsistent settings |
| `CFG014` | Inventoried path is unclassified at evaluation time |
| `CFG015` | Effective run-time file policy is incomplete or ineffective |
| `EXC001` | Broad intentional-exception selector |
| `EXC002` | Exception expired at the explicit evaluation date |

`CFG001` through `CFG013` are emitted while parsing configuration and carry a configuration source location and field path. `CFG014` and `CFG015` are run-time configuration failures tied to an inventoried repository path. `EXC002` is tied to the expired record's field path and explicit evaluation date without consulting the wall clock.
