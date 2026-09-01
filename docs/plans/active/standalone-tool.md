# Build the standalone repo-context tool

- Status: active
- Owner: Codex implementation agent
- Started: 2026-08-31
- Source oracle: scene-maker commit `9e792124bc61f55150416b8bf803862c6c634c78`
- Completion authority: `docs/quality/acceptance.md`

## Objective

Turn the frozen scene-maker checker into a reusable, tested, self-hosting Python CLI without inheriting scene-maker-specific assumptions. Work through the phases in order. Do not stop after producing design notes or scaffolding; the assignment is complete only when the standalone CLI replaces the transitional checker and all acceptance criteria pass.

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

- [x] Verify `reference/scene-maker/SOURCE.json` against the copied Python checker and referenced workflow files.
- [x] Expand source characterization tests to cover every public behavior in the seed: policy parsing, path canonicalization, Git inventory invocation, UTF-8 classification, limit selection, legacy ceilings, document discovery, required indexes, sibling links, child-index links, entrypoint targets, base-policy loading, non-weakening comparisons, exit codes, and deterministic ordering.
- [x] Create fixture-repository helpers that initialize temporary Git repositories, commit a base state, mutate a working tree, and run either checker without network access.
- [x] Add golden text fixtures only where structured assertions cannot express behavior. Normalize temporary paths before comparison.
- [x] Record the intended differences rather than forcing parity for known seed defects: missing ancestor-directory discovery, implicit `fnmatch` semantics, regex-only link parsing, stale manual legacy ceilings, hardcoded structured-data exemptions, and package-location root inference.
- [x] Decide the packaging backend after a current dependency review. Keep runtime dependency-free. Add a lock file only when the chosen workflow needs one.
- [x] Confirm the starter runs on Python 3.12 and 3.13 locally or in CI.

### Gate

- [x] Every behavior inherited from scene-maker has at least one characterization test.
- [x] The frozen checker hash test passes.
- [x] Known differences have explicit target tests or documented deferred test cases.
- [x] `scripts/validate` passes without network access.

### Phase 0 completion evidence

- Completed: 2026-09-01.
- Baseline: root commit `6b4263d` records the validated 50-file starter before implementation changes.
- Provenance: tests verify the recorded scene-maker repository and commit, every copied file's verbatim mode and Git blob, and the checker SHA-256. The frozen checker remains byte-identical at `bb796f2304f3692089a5e87cef55a7fbe3e7c4c9521d6d2299b738a84f7ebd11`.
- Characterization: 74 tests cover the complete source surface and deterministic CLI streams. Real temporary repositories isolate ambient Git configuration, use fixed identities and timestamps, commit reproducible base states, mutate tracked and untracked content, and run both seed and target entrypoints. Structured assertions were sufficient, so Phase 0 added no golden output file.
- Intended differences: `docs/reference/scene-maker-seed.md` maps the known intended differences to retained seed evidence and an owning target phase.
- Packaging: accepted decision 0004 pins `setuptools==84.0.0` after a 2026-09-01 review of release age, Python compatibility, ownership, maintenance, license, dependency footprint, execution surface, and artifact provenance. Runtime dependencies remain empty and no environment-manager lock is warranted yet.
- Validation: `scripts/validate` and the offline Lychee check pass without network access. The seed policy check, compile checks, CLI help, diff check, and all 74 tests pass locally on Python 3.12.14 and 3.13.13 without package installation. The suite also passes with hostile ambient `GIT_DIR` and injected Git configuration.
- Review: the read-only Phase 0 reviewer found and verified fixes for Git-environment isolation, Windows-invalid fixture names, overly broad symlink skips, deterministic commit evidence, and dependency-review completeness. No review finding remains open.
- Remaining work: Phase 1 begins immutable models and strict TOML parsing; no production seed behavior was extracted during Phase 0.
- Risks: local cross-version evidence is macOS arm64; Linux and Windows execution remains dependent on the supported-version CI and release matrix. Symlink assertions skip only when the host cannot create symlinks. Isolated distribution builds will require the reviewed backend artifact to be available and will receive explicit offline artifact verification in Phase 8.

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

- Completed: 2026-09-01.
- Models: frozen, slotted records and immutable tuple collections cover the complete policy surface plus inventory entries, source locations, links, diagnostics, and run results. Exact and pattern selectors are distinct union variants, preventing dual-selector parser states.
- Configuration: the UTF-8 `tomllib` boundary validates exact table shapes, types, canonical paths, repository-pattern syntax, ordered file rules, the mandatory final scanned authored catch-all, deterministic override specificity, documentation dependencies, context sets, ratchets, and governed intentional exceptions. Configuration failures use stable `CFG001` through `CFG013` and `EXC001` identities with unambiguous field paths and deterministic source/position/code ordering.
- Serialization: `render_starter_policy()` returns a package-owned byte template that is LF-normalized, final-newline-terminated, byte-identical to the normative root policy, and model-equivalent after parsing. No general TOML writer or runtime dependency was added.
- Contract: `docs/specs/configuration-v1.md` is the authoritative exact schema for table shapes, static precedence, path and pattern syntax, exceptions, and diagnostic identities. The product and architecture documents link to it rather than duplicating the detailed contract.
- Tests: 70 Phase 1 tests cover every immutable record family, complete root-policy projection, optional record defaults, template round trips, strict shape/type failures, every semantic invariant, malformed path and pattern cases, ambiguity proofs, exception governance, side-effect isolation, and diagnostic identity/order. The full 144-test repository suite passes on Python 3.12.14 and 3.13.13, including warnings-as-errors probes.
- Validation: `scripts/validate`, the transitional policy check with `--base-ref HEAD`, hostile ambient Git-variable execution, and offline Lychee validation pass. The frozen checker remains byte-identical at `bb796f2304f3692089a5e87cef55a7fbe3e7c4c9521d6d2299b738a84f7ebd11`.
- Review: the read-only reviewer found and verified fixes for wildcard-aligned disjointness, literal stars inside character classes, public diagnostic sort order, Unicode C1 controls, and exact schema wording. The final review reports no findings and confirms config/model code has no CLI, reporting, Git, scanning, or matcher-bypass dependency.
- Remaining work: Phase 2 owns repository-root validation, Git inventory, base blobs, canonical platform path normalization, and actual glob matching. Phase 1 intentionally implements only pattern syntax and conservative static ambiguity analysis.
- Risks: static ambiguity analysis intentionally rejects equal-specificity overrides unless disjointness is provable from aligned literals. Exception expiry against an evaluation date remains a deterministic run-time check; parsing validates date types and chronology without consulting the wall clock.

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

- Completed: 2026-09-01.
- Inventory: explicit canonical roots work independently of package and process location. Three strictly framed NUL-delimited Git views produce globally path-sorted immutable records for tracked, non-ignored untracked, deleted, sparse-missing, regular, executable, symlink, other, and gitlink states. SHA-1 and SHA-256 object identities, unresolved index stages, filesystem races, parent symlinks, and Windows junction shapes have explicit behavior and stable `GIT001` through `GIT009` diagnostics.
- Process boundary: Git runs through a canonical absolute executable resolved before the child changes directory. The sanitized search path rejects empty, relative, selected-repository, directory-symlink, and executable-symlink routes into repository content and is inherited by Git with Windows current-directory search disabled. Argument vectors, binary streams, prompt and lock suppression, configuration isolation, null-device hooks and filesystem monitor, disabled lazy fetch, disabled replacement objects, and a timeout keep operations deterministic and noninteractive.
- Base access: safe ref resolution, sorted recursive tree metadata, binary-search lookup, and lazy exact-object blob reads preserve invalid UTF-8 and NUL bytes without checkout or index/worktree mutation. Gitlinks remain commit objects rather than readable blobs, and local replacement refs cannot substitute validated identities.
- Matcher: canonical platform conversion and an iterative dynamic-programming engine define full-path `*`, `?`, component-only `**`, character classes, dotfiles, literal candidate metacharacters, exact case, and unnormalized Unicode behavior without `fnmatch`, regular-expression backtracking, or filesystem globbing.
- Contract: `docs/specs/repository-paths-and-globs-v1.md` is authoritative for canonical paths and matcher semantics. `docs/architecture/inventory.md` owns root, process, snapshot, base-object, race, and diagnostic behavior; the product, configuration, and architecture indexes link to those contracts rather than duplicating them.
- Tests: 55 tests added since Phase 1 cover real repositories, hostile environments, process non-execution, malformed Git bytes, races, sparse checkout, gitlinks, symlinks, SHA-256 when supported, base-state non-mutation, path normalization, the complete matcher matrix, and architecture boundaries. The full 199-test suite passes on Python 3.12.14 and 3.13.13 with warnings as errors; one macOS filesystem-capability test for an invalid UTF-8 filename skips. The reviewer independently compared 949,221 matcher cases with complete agreement.
- Validation: `scripts/validate`, the transitional policy check with `--base-ref HEAD`, hostile ambient Git-variable execution, target CLI help, `git diff --check`, and offline Lychee validation pass. The frozen checker remains byte-identical at `bb796f2304f3692089a5e87cef55a7fbe3e7c4c9521d6d2299b738a84f7ebd11`.
- Review: the read-only reviewer found and verified fixes for executable filesystem-monitor configuration, replacement refs, readlink error identity, sparse-checkout absence, nested Windows drive components, empty and NUL roots, base-state mutation evidence, mixed-source failure ordering, and repository-controlled Git executable search. The final review reports no remaining findings.
- Remaining work: Phase 3 owns classification, shared no-follow content reads, byte accounting, file budgets, context sets, and explain data. Public CLI integration remains Phase 6 work.
- Risks: local cross-version evidence is macOS arm64 with Git 2.55.0; real Linux and Windows execution remains dependent on CI, including Windows junction and executable-search behavior. The supported Git-version floor remains deferred to distribution validation. `inventory.py` is 779 lines and must split by stable responsibility before Phase 3 grows this boundary. Centralized no-follow content opening must reduce the documented parent-inspection-to-leaf-open race.

## Phase 3: Implement classification, file budgets, and context sets

### Tasks

- [ ] Implement first-match file-rule classification and exact/pattern override precedence.
- [ ] Detect plaintext with NUL and UTF-8 rules and count raw bytes exactly once per file.
- [ ] Emit advisory diagnostics at warning thresholds and blocking diagnostics at hard thresholds.
- [ ] Report unclassified paths as configuration failures.
- [ ] Make generated, vendored, fixture, and legal handling explicit in audit output.
- [ ] Implement named context sets with de-duplicated membership, missing-member diagnostics, aggregate warning thresholds, and aggregate hard thresholds.
- [ ] Add `explain` data for matched rule, override, effective limits, and context-set membership even before the CLI renderer is complete.
- [ ] Test boundary values at limit minus one, exact limit, and limit plus one using multibyte UTF-8 content and CRLF bytes.
- [ ] Test that file extensions do not automatically confer exemption.

### Gate

- [ ] File and context-set checks satisfy the target spec on fixture repositories.
- [ ] Every diagnostic has a stable code and structured fields.
- [ ] One read of a file is shared by classification, size, and later document parsing where possible.
- [ ] Audit data identifies the largest governed files and their effective limits.

## Phase 4: Implement Markdown extraction and documentation graph

### Tasks

- [ ] Write tests for supported inline and reference-style Markdown links before implementing the parser.
- [ ] Ignore links in inline code, fenced code blocks, and HTML comments.
- [ ] Normalize angle-bracket destinations, percent encoding, queries, directory targets, and fragments safely.
- [ ] Extract headings, explicit IDs, and deterministic GitHub-style slugs. Specify duplicate-heading suffix behavior in tests.
- [ ] Check local file targets and fragments. Never open a resolved path outside the repository.
- [ ] Discover every governed Markdown file below each configured root directory.
- [ ] Add all ancestor directories to the hierarchical index model, fixing the source checker's intermediate-directory gap.
- [ ] Require directory indexes, sibling links, and immediate child-index links according to policy.
- [ ] Traverse from every configured root and report unreachable documents.
- [ ] Keep images and other local assets distinct from navigation edges while still checking configured local assets when supported.
- [ ] Decide whether the standard-library parser is sufficient. Add a CommonMark dependency only through an accepted decision and current dependency review.

### Gate

- [ ] Documentation fixtures cover nested empty ancestors, sibling docs, child indexes, multiple roots, excluded docs, circular links, orphan docs, directory links, Unicode paths, escaped destinations, reference links, headings, duplicate headings, and broken fragments.
- [ ] The new engine intentionally differs from the seed on the known ancestor and parsing defects.
- [ ] Graph results are deterministic and independent of filesystem order.
- [ ] The repository's own documentation passes the new graph checks.

## Phase 5: Implement file and policy ratchets

### Tasks

- [ ] Compare current oversized authored files with base-revision blobs.
- [ ] Reject newly oversized paths, files whose base versions were ordinary-sized, and any oversized file that grows relative to its base bytes.
- [ ] Automatically remove migration status when a file falls within its ordinary limit.
- [ ] Ensure a partial reduction becomes the next ceiling without updating a manual map.
- [ ] Compare current and base policies for increased limits, weakened overrides, expanded unscanned rules, removed documentation roots, removed graph requirements, removed entrypoint targets, weakened context sets, disabled ratchets, and broadened exceptions.
- [ ] Define deterministic behavior when the base commit has no policy, the base ref is all zeroes, the base ref is shallow or missing, or the file changed type.
- [ ] Implement the migration-debt manifest used only by first-adoption `init --capture-debt`.
- [ ] Test renames as delete-plus-add unless reliable identity can be inferred without heuristic behavior.

### Gate

- [ ] A legacy file reduced from 100 KiB to 60 KiB cannot return to 61 KiB in the next comparison.
- [ ] A clean repository cannot add its first oversized authored file.
- [ ] Policy weakening produces `RAT` diagnostics independently of current-state violations.
- [ ] Base comparisons never modify the worktree or index.

## Phase 6: Complete CLI, reports, audit, explain, and init

### Tasks

- [ ] Replace command stubs with runner integration while preserving the documented arguments and exit codes.
- [ ] Implement concise text output with deterministic order and one final summary.
- [ ] Implement versioned JSON output whose diagnostics and audit records are stable enough for automation.
- [ ] Implement SARIF output for blocking and advisory diagnostics with real locations only.
- [ ] Make `audit` non-mutating and successful despite policy violations while still failing on invalid configuration or repository access.
- [ ] Implement `explain PATH` with rule provenance, override precedence, scan decision, limits, context sets, graph membership, migration status, and exception status.
- [ ] Implement `init` with safe no-overwrite default, deterministic starter policy, clean-repository refusal, optional migration-debt capture, and no automatic broad exclusions.
- [ ] Add CLI integration tests for stdout/stderr separation, broken pipes, unknown commands, invalid formats, relative repository paths, and execution outside the repository.
- [ ] Add `--version` from package metadata or a single authoritative version constant.

### Gate

- [ ] All four public commands work end to end.
- [ ] Exit codes match the spec.
- [ ] Text, JSON, and SARIF outputs pass schema or golden tests.
- [ ] No expected user error emits a Python traceback.

## Phase 7: Self-host and retire the transitional path

### Tasks

- [ ] Run the seed checker and new engine over the repository and all compatibility fixtures.
- [ ] Classify every output difference as intended improvement, equivalent diagnostic, or defect.
- [ ] Update `scripts/context-check` to invoke `PYTHONPATH=src python3 -m repo_context check` without requiring package installation.
- [ ] Update CI to run the new engine with the existing base-ref behavior.
- [ ] Keep the scene-maker checker as a frozen test oracle or move it byte-for-byte under a fixture path. Update provenance paths without changing contents.
- [ ] Remove the bootstrap JSON policy only after the new TOML policy is authoritative and no script depends on it.
- [ ] Make the new tool validate its own file budgets, documentation graph, bootstrap context set, and base ratchet.
- [ ] Add a test ensuring production code does not import the frozen oracle.

### Gate

- [ ] `scripts/validate` is green using only the standalone engine.
- [ ] The old checker is not executed by normal local or CI workflows.
- [ ] Intended behavior differences are documented and tested.
- [ ] A clean clone or unpacked archive can bootstrap and validate offline.

## Phase 8: Package, release, and pilot

### Tasks

- [ ] Finalize package metadata, license, versioning policy, changelog process, and supported Python matrix.
- [ ] Build wheel and source distribution in an isolated environment.
- [ ] Add an optional zipapp or equivalent vendorable artifact if it can remain dependency-free and deterministic.
- [ ] Verify installation and execution on macOS, Linux, and Windows with Python 3.12 and 3.13.
- [ ] Document three consumption modes: installed package, pinned zipapp, and vendored source with a project-local wrapper.
- [ ] Create migration instructions from the scene-maker JSON format to v1 TOML.
- [ ] Pilot in `scene-maker`, `nano-dllm`, and `research-vault` using separate project policies.
- [ ] Record false positives, performance, context-debt findings, and policy features that genuinely generalize.
- [ ] Do not add project-specific behavior to the engine during pilots; add configuration or a separately justified generic feature.
- [ ] Configure the eventual GitHub repository's required CI check, branch protection, and ownership review for policy, workflow, and release files.

### Gate

- [ ] Distribution artifacts install and run from clean environments.
- [ ] Three pilot repositories pass or have explicit monotonic migration debt.
- [ ] No release-blocking acceptance item remains unchecked.
- [ ] This plan is moved to a completed-plan location with a concise final report.

## Required final report

When all phases are complete, update this document or its completed successor with:

- Final CLI and configuration version.
- Runtime and development dependencies with rationale.
- Compatibility and intended-difference summary relative to scene-maker.
- Test counts and supported platforms.
- Self-hosting evidence.
- Pilot results and remaining non-blocking work.
- Exact release or commit identifier.
