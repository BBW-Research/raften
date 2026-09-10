# Build the standalone repo-context tool

- Status: completed
- Owner: Codex implementation agent
- Started: 2026-08-31
- Completed: 2026-09-02
- Source oracle: the hash-verified bootstrap snapshot recorded in `reference/bootstrap/SOURCE.json`.
- Completion authority: `docs/quality/acceptance.md`

This is the completed build record under the former `repo-context` name. The subsequent Raften rename and its validation are recorded in [decision 0009](../../decisions/0009-raften-name.md).

## Objective

Turn the frozen bootstrap checker into a reusable, tested, self-hosting Python CLI without inheriting bootstrap-specific assumptions. Work through the phases in order. Do not stop after producing design notes or scaffolding; the assignment is complete only when the standalone CLI replaces the transitional checker and all acceptance criteria pass.

## Working rules

- Read `AGENTS.md`, the product spec, architecture docs, decisions, quality docs, and source-reference note before implementation.
- Preserve `tools/check_repository_policy.py` byte-for-byte until Phase 7.
- Add characterization tests before moving behavior out of the seed.
- Implement one phase at a time and have a read-only reviewer inspect it before beginning the next phase.
- Keep runtime standard-library-only unless a dependency decision is accepted.
- Before adding or pinning any package-manager, build, lint, typing, Markdown, or test dependency, verify its current official release and compatibility within seven days of the change. Record the decision and regenerate the lock file through the selected package manager. Do not add speculative dependencies.
- Keep code and documentation files below the policy limit. Split by stable responsibility.
- Run `scripts/validate` at every phase gate. Update this file with concrete completed work, remaining tasks, and risks.
- Do not weaken policy or add an exclusion merely to make validation green.

## Phase 0: Freeze the baseline and establish characterization

### Tasks

- [x] Verify `reference/bootstrap/SOURCE.json` against the copied Python checker and referenced workflow files.
- [x] Expand source characterization tests to cover every public behavior in the seed: policy parsing, path canonicalization, Git inventory invocation, UTF-8 classification, limit selection, legacy ceilings, document discovery, required indexes, sibling links, child-index links, entrypoint targets, base-policy loading, non-weakening comparisons, exit codes, and deterministic ordering.
- [x] Create fixture-repository helpers that initialize temporary Git repositories, commit a base state, mutate a working tree, and run either checker without network access.
- [x] Add golden text fixtures only where structured assertions cannot express behavior. Normalize temporary paths before comparison.
- [x] Record the intended differences rather than forcing parity for known seed defects: missing ancestor-directory discovery, implicit `fnmatch` semantics, regex-only link parsing, stale manual legacy ceilings, hardcoded structured-data exemptions, and package-location root inference.
- [x] Decide the packaging backend after a current dependency review. Keep runtime dependency-free. Add a lock file only when the chosen workflow needs one.
- [x] Confirm the starter runs on Python 3.12 and 3.13 locally or in CI.

### Gate

- [x] Every behavior inherited from bootstrap has at least one characterization test.
- [x] The frozen checker hash test passes.
- [x] Known differences have explicit target tests or documented deferred test cases.
- [x] `scripts/validate` passes without network access.

### Phase 0 completion evidence

[Phase 0 completion evidence](standalone-tool-evidence-phase-0.md#phase-0-completion-evidence) is retained in the companion evidence log.

## Phase 1: Define immutable models and strict configuration

### Tasks

- [x] Add immutable typed records for policy, file rules, overrides, documentation settings, entrypoints, context sets, ratchet settings, exceptions, inventory entries, links, diagnostics, and run results.
- [x] Implement strict `tomllib` parsing for `repo-context.toml`.
- [x] Reject unknown keys, wrong types, duplicate names, missing catch-all classification, ambiguous overrides, unsafe paths, invalid limits, broad exception patterns, and internally inconsistent settings.
- [x] Preserve declaration order where semantics require it.
- [x] Produce configuration diagnostics with stable codes and field paths.
- [x] Implement configuration serialization needed by `init` without creating a general-purpose TOML writer. A deterministic project-owned template is acceptable.
- [x] Add round-trip tests for generated starter policy where applicable.

### Gate

- [x] The root `repo-context.toml` parses into immutable records.
- [x] Invalid-policy fixture coverage includes every validation rule in the product spec.
- [x] No scanning or Git access occurs during configuration parsing.
- [x] Reviewer confirms model/config modules do not depend on CLI, reporting, or repository I/O.

### Phase 1 completion evidence

[Phase 1 completion evidence](standalone-tool-evidence-phase-1.md#phase-1-completion-evidence) is retained in the companion evidence log.

## Phase 2: Build deterministic inventory and matcher semantics

### Tasks

- [x] Implement repository-root validation independent of package location and current working directory.
- [x] Implement Git-visible inventory using argument-vector subprocess calls and NUL-delimited output.
- [x] Represent tracked, untracked, deleted, regular, symlink, and missing states explicitly where relevant.
- [x] Add base-revision blob and metadata access without checking out or modifying the worktree.
- [x] Implement canonical POSIX path normalization on macOS, Linux, and Windows.
- [x] Implement the specified repository glob language. `*` and `?` must not cross `/`; `**` must. Do not call raw `fnmatch` outside the matcher module.
- [x] Add matcher tests for root files, nested files, dotfiles, Unicode, character classes, repeated separators, `**`, case sensitivity, and malformed patterns.
- [x] Sort inventory and all derived collections explicitly.
- [x] Handle files that disappear during a run with a deterministic operational diagnostic.

### Gate

- [x] Inventory APIs work with an explicit target while the process current directory is outside it; Phase 6 owns public CLI wiring for the release-level criterion.
- [x] Fixture tests cover tracked and non-ignored untracked files, ignored files, deletion, rename, symlinks, and base blobs.
- [x] Matcher behavior is completely defined by tests and documentation.
- [x] No code outside `inventory.py` invokes Git; no code outside `matcher.py` interprets policy globs.

### Phase 2 completion evidence

[Phase 2 completion evidence](standalone-tool-evidence-phase-2.md#phase-2-completion-evidence) is retained in the companion evidence log.

## Phase 3: Implement classification, file budgets, and context sets

### Tasks

- [x] Implement first-match file-rule classification and exact/pattern override precedence.
- [x] Detect plaintext with NUL and UTF-8 rules and count raw bytes exactly once per file.
- [x] Emit advisory diagnostics at warning thresholds and blocking diagnostics at hard thresholds.
- [x] Report unclassified paths as configuration failures.
- [x] Make generated, vendored, fixture, and legal handling explicit in audit output.
- [x] Implement named context sets with de-duplicated membership, missing-member diagnostics, aggregate warning thresholds, and aggregate hard thresholds.
- [x] Add `explain` data for matched rule, override, effective limits, and context-set membership even before the CLI renderer is complete.
- [x] Test boundary values at limit minus one, exact limit, and limit plus one using multibyte UTF-8 content and CRLF bytes.
- [x] Test that file extensions do not automatically confer exemption.

### Gate

- [x] File and context-set checks satisfy the target spec on fixture repositories.
- [x] Every diagnostic has a stable code and structured fields.
- [x] One read of a file is shared by classification, size, and later document parsing where possible.
- [x] Audit data identifies the largest governed files and their effective limits.

### Phase 3 completion evidence

[Phase 3 completion evidence](standalone-tool-evidence-phase-3.md#phase-3-completion-evidence) is retained in the companion evidence log.

## Phase 4: Implement Markdown extraction and documentation graph

### Tasks

- [x] Write tests for supported inline and reference-style Markdown links before implementing the parser.
- [x] Ignore links in inline code, fenced code blocks, and HTML comments.
- [x] Normalize angle-bracket destinations, percent encoding, queries, directory targets, and fragments safely.
- [x] Extract headings, explicit IDs, and deterministic GitHub-style slugs. Specify duplicate-heading suffix behavior in tests.
- [x] Check local file targets and fragments. Never open a resolved path outside the repository.
- [x] Discover every governed Markdown file below each configured root directory.
- [x] Add all ancestor directories to the hierarchical index model, fixing the source checker's intermediate-directory gap.
- [x] Require directory indexes, sibling links, and immediate child-index links according to policy.
- [x] Traverse from every configured root and report unreachable documents.
- [x] Keep images and other local assets distinct from navigation edges while still checking configured local assets when supported.
- [x] Decide whether the standard-library parser is sufficient. Add a CommonMark dependency only through an accepted decision and current dependency review.

### Gate

- [x] Documentation fixtures cover nested empty ancestors, sibling docs, child indexes, multiple roots, excluded docs, circular links, orphan docs, directory links, Unicode paths, escaped destinations, reference links, headings, duplicate headings, and broken fragments.
- [x] The new engine intentionally differs from the seed on the known ancestor and parsing defects.
- [x] Graph results are deterministic and independent of filesystem order.
- [x] The repository's own documentation passes the new graph checks.

### Phase 4 completion evidence

[Phase 4 completion evidence](standalone-tool-evidence-phase-4.md#phase-4-completion-evidence) is retained in the companion evidence log.

## Phase 5: Implement file and policy ratchets

### Tasks

- [x] Compare current oversized authored files with base-revision blobs.
- [x] Reject newly oversized paths, files whose base versions were ordinary-sized, and any oversized file that grows relative to its base bytes.
- [x] Automatically remove migration status when a file falls within its ordinary limit.
- [x] Ensure a partial reduction becomes the next ceiling without updating a manual map.
- [x] Compare current and base policies for increased limits, weakened overrides, expanded unscanned rules, removed documentation roots, removed graph requirements, removed entrypoint targets, weakened context sets, disabled ratchets, and broadened exceptions.
- [x] Define deterministic behavior when the base commit has no policy, the base ref is all zeroes, the base ref is shallow or missing, or the file changed type.
- [x] Implement the migration-debt manifest used only by first-adoption `init --capture-debt`.
- [x] Test renames as delete-plus-add unless reliable identity can be inferred without heuristic behavior.

### Gate

- [x] A legacy file reduced from 100 KiB to 60 KiB cannot return to 61 KiB in the next comparison.
- [x] A clean repository cannot add its first oversized authored file.
- [x] Policy weakening produces `RAT` diagnostics independently of current-state violations.
- [x] Base comparisons never modify the worktree or index.

### Phase 5 completion evidence

[Phase 5 completion evidence](standalone-tool-evidence-phase-5.md#phase-5-completion-evidence) is retained in the companion evidence log.

## Phase 6: Complete CLI, reports, audit, explain, and init

### Tasks

- [x] Replace command stubs with runner integration while preserving the documented arguments and exit codes.
- [x] Implement concise text output with deterministic order and one final summary.
- [x] Implement versioned JSON output whose diagnostics and audit records are stable enough for automation.
- [x] Implement SARIF output for blocking and advisory diagnostics with real locations only.
- [x] Make `audit` non-mutating and successful despite policy violations while still failing on invalid configuration or repository access.
- [x] Implement `explain PATH` with rule provenance, override precedence, scan decision, limits, context sets, graph membership, migration status, and exception status.
- [x] Implement `init` with safe no-overwrite default, deterministic starter policy, clean-repository refusal, optional migration-debt capture, and no automatic broad exclusions.
- [x] Add CLI integration tests for stdout/stderr separation, broken pipes, unknown commands, invalid formats, relative repository paths, and execution outside the repository.
- [x] Add `--version` from package metadata or a single authoritative version constant.

### Gate

- [x] All four public commands work end to end.
- [x] Exit codes match the spec.
- [x] Text, JSON, and SARIF outputs pass schema or golden tests.
- [x] No expected user error emits a Python traceback.

### Phase 6 completion evidence

[Phase 6 completion evidence](standalone-tool-evidence-phase-6.md) is retained in the companion evidence log.

## Phase 7: Self-host and retire the transitional path

### Tasks

- [x] Run the seed checker and new engine over the repository and all compatibility fixtures.
- [x] Classify every output difference as intended improvement, equivalent diagnostic, or defect.
- [x] Update `scripts/context-check` to invoke `PYTHONPATH=src python3 -m repo_context check` without requiring package installation.
- [x] Update CI to run the new engine with the existing base-ref behavior.
- [x] Keep the bootstrap checker as a frozen test oracle or move it byte-for-byte under a fixture path. Update provenance paths without changing contents.
- [x] Remove the bootstrap JSON policy only after the new TOML policy is authoritative and no script depends on it.
- [x] Make the new tool validate its own file budgets, documentation graph, bootstrap context set, and base ratchet.
- [x] Add a test ensuring production code does not import the frozen oracle.

### Gate

- [x] `scripts/validate` is green using only the standalone engine.
- [x] The old checker is not selected as the repository validation engine by normal local or CI workflows; any execution is confined to characterization and paired-compatibility tests.
- [x] Intended behavior differences are documented and tested.
- [x] A clean clone or unpacked archive can bootstrap and validate offline.

### Phase 7 completion evidence

[Phase 7 completion evidence](standalone-tool-evidence-phase-7.md) is retained in the companion evidence log.

## Phase 8: Package, release, and pilot

### Tasks

- [x] Finalize package metadata, license, versioning policy, changelog process, and supported Python matrix.
- [x] Build wheel and source distribution in an isolated environment.
- [x] Add an optional zipapp or equivalent vendorable artifact if it can remain dependency-free and deterministic.
- [x] Verify installation and execution on macOS and Linux with Python 3.12 and 3.13.
- [x] Document three consumption modes: installed package, pinned zipapp, and vendored source with a project-local wrapper.
- [x] Create migration instructions from the bootstrap JSON format to v1 TOML.
- [x] Pilot in `private-pilot`, `nano-dllm`, and `research-vault` using separate project policies.
- [x] Record false positives, performance, context-debt findings, and policy features that genuinely generalize.
- [x] Do not add project-specific behavior to the engine during pilots; add configuration or a separately justified generic feature.
- [x] Configure the GitHub repository's required CI check, branch protection, and ownership review for policy, workflow, and release files.

### Gate

- [x] Distribution artifacts install and run from clean environments.
- [x] Three pilot repositories pass or have explicit monotonic migration debt.
- [x] No release-blocking acceptance item remains unchecked.
- [x] This plan is moved to a completed-plan location with a concise final report.

### Phase 8 completion evidence

[Phase 8 qualification evidence](standalone-tool-evidence-phase-8.md) records the completed artifact, platform, pilot, hosted-CI, and repository-control work.

## Final report

- Interface: release 1.0.0 provides `repo-context check`, `audit`, `explain`, and guarded `init`; the configuration schema and JSON output schema are both version 1.
- Dependencies: runtime uses only CPython's standard library plus Git 2.39.5 or newer. Distribution builds use the separately reviewed, hash-locked `build`, `packaging`, `pyproject-hooks`, and `setuptools` artifacts because standards-compliant wheel and sdist construction is a release concern rather than a runtime concern.
- Compatibility: the frozen bootstrap checker remains a byte-verified characterization oracle. The [compatibility report](../../reference/bootstrap-compatibility.md) classifies equivalent results and intentional fixes for ancestor discovery, Markdown parsing, base handling, and unsafe paths; no comparison defect remains.
- Validation: the current local suite contains 522 tests and passes under CPython 3.12 and 3.13 on macOS, with one host-capability skip. Pinned Debian Bookworm containers pass the complete artifact-era 512-test suite without skips on both versions, and the four-entry native Ubuntu/macOS GitHub matrix plus offline link validation passes in [workflow run 33629864145](https://github.com/BBW-Research/repo-context/actions/runs/33629864145).
- Self-hosting: `scripts/context-check`, `scripts/validate`, bootstrap, and CI select `src/repo_context` rather than the oracle. A freshly unpacked archive validates offline, and comparison against the reviewed policy baseline has no blocking or ratchet diagnostic.
- Pilots: the private pilot, NanoDLLM, and Research Vault pass at the recorded commits with zero blocking diagnostics and no project-specific engine branch. Exact policy, debt, performance, and context-size evidence is retained in the [pilot report](../../pilots/index.md).
- Release identity: the qualified MIT candidate was exported from exact clean commit `c67b394601fcaedad6cb69c852f0f4bb940788ec`; its wheel, source archive, zipapp, and checksum hashes are recorded in the [Phase 8 evidence](standalone-tool-evidence-phase-8.md). `BBW-Research/repo-context` is private, `@taiqihe` has administrator access, GitHub reports no CODEOWNERS error, and protected `main` requires pull requests, one current code-owner approval, resolved conversations, and the stable `Required repository policy` check with administrator enforcement.
- Remaining non-blocking work: the repository intentionally remains private for now. No tag, package-index publication, or trusted publisher has been created; those require a separate publication request and a fresh build and qualification from the selected exact release commit. Four existing files remain above advisory thresholds but below hard ceilings, and one macOS filename-capability test may skip on filesystems that cannot represent its byte sequence.
