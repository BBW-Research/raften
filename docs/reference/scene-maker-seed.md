# Scene-maker seed

## Source

The bootstrap implementation is copied from `BBW-Research/scene-maker` at commit `9e792124bc61f55150416b8bf803862c6c634c78`.

- Source path: `tools/check_repository_policy.py`
- Git blob: `a18f52d15c8f70a53bad2e0d961f5fa355a50a84`
- Local frozen path: `tools/check_repository_policy.py`
- Provenance manifest: `reference/scene-maker/SOURCE.json`

The working scene-maker workflow and Lychee configuration are preserved under `reference/scene-maker/`. The enormous scene-maker migration inventory is intentionally not copied; the starter policy contains no legacy oversized files.

## Seed behavior to preserve initially

The source checker:

- Inventories tracked and non-ignored untracked Git paths.
- Treats regular UTF-8 files without NUL bytes as plaintext.
- Enforces a default byte ceiling, smaller entrypoint limits, and smaller documentation-index limits.
- Allows listed legacy oversized files only up to manually recorded ceilings.
- Requires an `index.md` in discovered documentation directories.
- Requires each index to link sibling documents and immediate child indexes.
- Requires configured root entrypoints to link configured targets.
- Compares selected policy fields with a base revision and rejects several weakening changes.
- Uses exit code `0` for pass, `1` for violations, and `2` for operational or configuration errors.

## Seed limitations to improve

The standalone target must not preserve these as design constraints:

1. **Package-location root inference.** The seed assumes its repository root is the parent of `tools/`. An installed tool must accept an explicit repository.
2. **Incomplete ancestor discovery.** Documentation directories are derived from immediate parents of Markdown files. An intermediate directory with only a deeper child can escape index enforcement.
3. **Regex-only Markdown parsing.** The seed recognizes a subset of inline links and can neither robustly ignore code nor handle all reference forms and fragments.
4. **Implicit glob semantics.** Python `fnmatch` behavior is not a sufficiently explicit cross-platform repository pattern contract.
5. **Stale legacy ceilings.** A file reduced below its recorded ceiling can regrow up to that old ceiling. The target compares directly with base bytes.
6. **Hardcoded shared exemptions.** The source checker treats `config/*.json` and `schemas/*.json` as special policy additions. Classification belongs in project configuration.
7. **No graph reachability traversal.** Hierarchical direct-link requirements approximate navigation but do not prove reachability from configured roots.
8. **No context-set accounting.** It cannot measure the total root context an agent is instructed to load.
9. **No structured diagnostics or audit interface.** Output is prose-only and there is no path explanation or initialization command.
10. **Policy-only base reads.** It reads prior policy but not prior file bytes, preventing a true monotonic size ratchet.

## Extraction rule

Use the seed as an oracle for compatible behavior, not as the module layout. Production modules must be designed around explicit inputs and immutable results. When target behavior intentionally differs, write a fixture showing both outputs and document why the target result is safer or more precise.
