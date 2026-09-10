# Pilot results

## Method

Phase 8 ran the vendorable artifact with Python 3.13.13 on macOS 26.6.2 arm64 against detached local clones. Each clone used `git clone --local --no-hardlinks`, an explicit commit, a stored candidate policy, an exact migration-debt sidecar, and evaluation date 2026-09-02. Source working directories were never modified. Scene Maker's source worktree had five modified and nineteen untracked paths; those changes were absent from its clone.

The candidate policy and sidecar were the only overlay files for Scene Maker. NanoDLLM and Research Vault had no canonical `index.md`, which version 1 requires for a documentation root, so each pilot also added the small proposed `docs/index.md` stored with its policy fixture. Checks used `--base-ref HEAD`; because HEAD has no version 1 policy, the exact sidecar supplied the first-adoption baseline. Each run also exercised JSON `audit` and `explain README.md`.

## Results

| Pilot | Source commit | Inventory | Governed docs | Errors | Advisory warnings | Migration paths | Migration bytes | Check wall time | Bootstrap bytes |
| --- | --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| [scene-maker](https://github.com/BBW-Research/scene-maker) | [`dedba615885166fbbd838476d92b3d4fb9dffdf4`](https://github.com/BBW-Research/scene-maker/commit/dedba615885166fbbd838476d92b3d4fb9dffdf4) | 1,083 | 102 | 0 | 67 | 198 | 10,201,558 | 0.78 s | 9,059 |
| [nano-dllm](https://github.com/BBW-Research/nano-dllm) | [`005e075a4c588bc14b4833ecd81828b274236971`](https://github.com/BBW-Research/nano-dllm/commit/005e075a4c588bc14b4833ecd81828b274236971) | 727 | 114 | 0 | 42 | 94 | 4,335,546 | 1.18 s | 38,747 |
| [research-vault](https://github.com/taiqihe/research-vault) | [`00e2ea44b0647ff6b984fe80dc7e073b3c364477`](https://github.com/taiqihe/research-vault/commit/00e2ea44b0647ff6b984fe80dc7e073b3c364477) | 810 | 83 | 0 | 23 | 96 | 7,823,695 | 1.10 s | 33,023 |

All three runs completed with zero blocking diagnostics and `baseline_source = "manifest"`. Every advisory was `CTX001`: a scanned authored plaintext file above its warning threshold but not its effective hard threshold. The exact debt manifests suppressed hard findings only for identity-verified oversized authored paths; they contain no patterns, exceptions, or blanket exclusions. All three context sets were within their configured hard limits.

The reproducible input identities are:

| Pilot | Policy SHA-256 | Debt-manifest SHA-256 | Debt file bytes | Proposed index SHA-256 |
| --- | --- | --- | ---: | --- |
| scene-maker | `2869d79ea5b1d20e89f5553a6bd9891178d2e37ea9d7703ae6b236b52e0069cd` | `c7f7f65c08b61f8191aa68189484410db6ab998f4fe1b20c745ac8720fd11ff5` | 38,706 | not needed |
| nano-dllm | `02d2f8287e86543875ba0a962d0fde3eb4404f602e6afb0de4e2734a851d62f2` | `f7e6167f4e5e153bda0c1f06671d993faeea24fe142b33d03783e2c4554238e3` | 18,685 | `d4a4c3fccc1d20df1eade6bfbc589fb7819eb26dc4444b6fd1cbf3d1c05c1005` |
| research-vault | `3fddfed64f1fc23c5090eb5d1a07f504bdc731151b25647963a6a7132315ba51` | `fb51fca9faa2106343f79d62e853ce6bc6e42af5ed7dc11cbc2fe3d415bc7e43` | 20,617 | `7e25d0844f7a0e86af6060f06f635395e796e22bdf7ab832cd0ba39833663d10` |

Debt sidecars are generated, commit-specific adoption state; Scene Maker's exceeds the fixture ceiling. To reproduce them, check out the recorded source commit and run `raften init --capture-debt --config repo-context.toml` while clean. Apply any stored index, replace the starter with the stored policy, and check against `HEAD`. Keep `--config repo-context.toml` for all commands to preserve the original paths. The hashes above detect regeneration drift.

## Documentation adoption findings

The starter policy intentionally exposed existing documentation-governance debt rather than treating it as an engine defect. Before tailoring, Scene Maker had 14 blocking findings, NanoDLLM had 251, and Research Vault had 179. Most were missing canonical directory indexes, missing sibling or child routes, and unreachable documents. Scene Maker additionally has two existing unresolved local targets and no `ARCHITECTURE.md`; NanoDLLM and Research Vault use `README.md` and `ARCHITECTURE.md` conventions instead of canonical root indexes.

The pilot policies stage structure, sibling, child-index, and reachability requirements as disabled, which is a passable initial policy state that can only be tightened after adoption. NanoDLLM and Research Vault retain local-target and fragment checking and pass it. Scene Maker stages those two checks off because its current tree has two real broken targets. This is explicit project configuration, not an exception and not a shared-engine branch.

Scene Maker's old broad JSON exemptions were not migrated. Authored configuration and schemas remain scanned, and oversized files remain exact monotonic debt. The other pilots likewise avoid guessing that project files are generated or fixtures merely because of their extension or directory name. The only unscanned rule covers exact dependency lock conventions and the exact generated debt sidecar; every such rule remains visible in audit classification counts.

No blocking diagnostic was judged a false positive after the candidate policies reflected each repository's actual entrypoints and documentation maturity. Advisory sizes and exact migration records are context-debt signals, not false positives. Potential future classifications of generated results or fixtures require those repository owners' review and were not invented during this pilot.

## General engine findings

Two findings generalized without project-specific behavior:

- `init --capture-debt` could generate a sufficiently large sidecar that its own starter policy classified as oversized authored text. The starter now renders the exact sidecar path into its explicit generated-state rule, including for a custom policy filename. The strict sidecar codec still validates its contents.
- Exact literal glob components dominated the first 100,000-path benchmark even though their lengths usually differed immediately. The matcher now retains literal components at compile time and compares them directly. Existing matcher characterization remains unchanged; the corrected 100,000-path synthetic content phase fell from 20.19 seconds to 1.59 seconds on the same host.

The missing canonical indexes did not justify relaxing the version 1 documentation-root contract. Proposed project-local indexes solved the adoption boundary. No production module contains a branch or name check for any pilot repository.

## Scale baseline

`scripts/benchmark` generated mixed small plaintext entirely in memory and built a real Git index containing 10,000 and 100,000 missing skip-worktree entries that all reference one blob. This measures the real NUL-delimited Git inventory path without creating or committing enormous fixture trees. The check totals combine that Git measurement with content, documentation, and rendering stages; they are stage-composed baselines rather than claims about a particular physical filesystem. Peak RSS includes the complete Python process, while retained content is the exact document text retained by the shared read cache.

| Paths | Git inventory | Bytes read | Retained content | Markdown parse | Graph pipeline | Total check | Total audit | Peak RSS | Audit JSON |
| ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| 10,000 | 0.206 s | 959,751 | 711 B / 10 docs | 0.001 s | 0.006 s | 0.362 s | 0.407 s | 59.7 MiB | 8,812,875 B |
| 100,000 | 1.920 s | 9,598,131 | 7,731 B / 100 docs | 0.008 s | 0.067 s | 3.583 s | 4.145 s | 353.9 MiB | 88,120,435 B |

A separate 1,000-level documentation hierarchy produced 1,001 directory records, zero unreachable documents, and completed in 0.023 seconds. The benchmark asserts counts and relationships but deliberately has no tight timing threshold. Complete JSON audit collections scale linearly and produce a large 88 MB report at 100,000 paths; that is an operator-visible output-volume cost of the version 1 machine-output contract, not retained source content.
