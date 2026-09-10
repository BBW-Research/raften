# Version 1 repository paths and globs

This document is the authoritative matching contract for version 1. `raften.matcher` owns compilation and interpretation; no other production module may call `fnmatch`, `glob`, `Path.match`, or implement a second pattern language.

## Canonical repository paths

Internal paths are nonempty repository-relative strings whose component separator is `/` on every operating system. They reject absolute spellings, a drive qualifier at the start of any component, NUL, a trailing or repeated separator, and `.` or `..` components. Checking every component prevents a nested `C:` value from resetting the drive when components are joined on Windows. Paths are case-sensitive and are never case-folded or Unicode-normalized.

Configured exact paths are stricter than Git inventory paths: they also reject backslashes, C0, DEL, and C1 controls, and the glob metacharacters `*`, `?`, `[`, and `]`. Configured patterns use the same strict path boundary before their pattern syntax is validated.

Git paths are decoded as strict UTF-8 and retain their exact decoded spelling. Literal glob metacharacters, controls other than NUL, and, on POSIX, literal backslashes are filename data rather than pattern syntax. On Windows, Git paths containing `\` are invalid because Git's internal path separator is `/`. A Git path that cannot satisfy this structural contract produces an operational diagnostic instead of being normalized or silently omitted.

Native user input crosses an explicit platform boundary. POSIX input preserves a literal backslash. Windows input converts `\` separators to `/` and then applies canonical repository-path validation. Absolute, UNC, traversal, dot-component, and duplicate-separator inputs remain invalid after conversion.

Version 1 does not normalize Unicode. For example, a composed `é` and the decomposed sequence `e` plus combining acute accent are distinct internal paths when the host filesystem and Git can represent both spellings.

## Full-path matching

Patterns match the complete canonical repository path. There is no substring search, implicit basename recursion, Gitignore anchoring rule, or host-filesystem case behavior.

- `*.py` matches `module.py` and does not match `src/module.py`.
- `**/*.py` matches both `module.py` and `src/module.py`.
- `index.md` matches only the root `index.md`; `**/index.md` also matches nested indexes.
- `docs/*.md` matches `docs/index.md` and does not match `docs/api/index.md`.

Dotfiles and dot directories have no hidden-file exception. `*` matches `.env`, and `**/*.yml` can match `.github/workflows/check.yml`.

## Operators

`*` consumes zero or more Unicode code points inside one path component. `?` consumes exactly one Unicode code point inside one component. Neither operator consumes `/`.

`**` is recursive only when it occupies a complete component. It consumes zero or more complete path components:

- `**` matches every valid canonical path.
- `docs/**` matches `docs` itself and every descendant.
- `docs/**/index.md` matches `docs/index.md`, `docs/api/index.md`, and deeper indexes.
- Separate consecutive recursive components such as `**/**/index.md` are valid and retain the same zero-or-more component rule.

An embedded double star such as `file**.md`, `***`, or `a**b` is malformed rather than being treated as two ordinary stars.

## Character classes

A character class consumes exactly one Unicode code point inside a component. `[abc]` is a union, `[a-z]` is an inclusive ordinal range, and a leading `!` negates the class. `^` has no special meaning. A hyphen is literal only at the first or last position; stars and question marks inside a class are literals. Classes never match `/` because matching is component-local.

Empty, nested, unclosed, unmatched, descending-range, and malformed-range classes are invalid. Pattern compilation raises `PatternSyntaxError`; configuration parsing maps the same syntax failure to `CFG007` with the relevant field path.

## Unicode and complexity

Matching compares Unicode code points exactly, independent of locale and operating system. `?` counts code points, not UTF-8 bytes or user-perceived grapheme clusters. The matcher uses iterative dynamic programming across components and tokens, so recursive stars and repeated ordinary stars do not invoke regular-expression backtracking.

## Literal metacharacters in Git names

Candidate filenames may contain literal pattern metacharacters. Those characters are interpreted only in the configured pattern, never in the candidate path. The catch-all `**` still governs such a file. Because version 1 exact selectors reject glob metacharacters, a Git filename containing `*`, `?`, `[` or `]` cannot receive an exact override; repositories needing that distinction must use an unambiguous pattern until a future selector encoding is specified.
