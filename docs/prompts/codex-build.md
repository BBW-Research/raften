# Codex assignment: build repo-context to completion

Use the following as the implementation assignment for Codex in this repository.

---

Build the standalone `repo-context` tool in this repository to completion. Start work immediately; do not stop after restating the plan or adding more scaffolding.

Read, in order:

1. `AGENTS.md`
2. `docs/specs/repo-context.md`
3. `docs/architecture/index.md` and its linked documents
4. `docs/decisions/index.md` and all accepted decisions
5. `docs/quality/index.md` and its linked documents
6. `docs/reference/scene-maker-seed.md`
7. `docs/plans/active/standalone-tool.md`
8. `tools/check_repository_policy.py` and `reference/scene-maker/SOURCE.json`

Then execute `docs/plans/active/standalone-tool.md` phase by phase until every release-blocking item in `docs/quality/acceptance.md` is satisfied.

Non-negotiable constraints:

- Preserve `tools/check_repository_policy.py` byte-for-byte until the self-hosting phase. It is a source oracle, not production architecture.
- Write characterization tests before extracting or replacing inherited behavior.
- Implement new code under `src/repo_context/`; do not import the source oracle from production modules.
- The final engine must be repository-agnostic, accept an explicit repository root, and run offline.
- Keep the runtime standard-library-only unless a dependency is necessary for correctness and an accepted decision records the tradeoff.
- Before adding or pinning a package-manager, build, lint, typing, Markdown, or test dependency, verify the current official version and compatibility within seven days of the change. Commit the resulting lock data only after that review.
- Do not add project-specific path exemptions to shared code. Express repository choices in `repo-context.toml`.
- Do not weaken limits, expand exclusions, or suppress a diagnostic merely to make tests pass.
- Keep authored files under the repository byte limit and split them by stable responsibility.
- Preserve deterministic path handling, output order, exit codes, and stdout/stderr behavior.
- No network access is permitted in `check`, `audit`, `explain`, tests that exercise runtime behavior, or self-hosting validation.
- Do not run multiple writing agents against the same worktree.

Working method:

- Use the explorer subagent for read-only mapping or targeted research inside the repository.
- At the end of each phase, run `scripts/validate`, inspect the complete diff, and use the reviewer subagent for a read-only correctness and regression review.
- Fix phase findings before beginning the next phase.
- Update the active plan after each phase with completed tasks, remaining work, and discovered risks. Check boxes only when the corresponding acceptance gate is actually demonstrated.
- Prefer small coherent commits aligned with phase boundaries. Never mix an unrelated cleanup into a policy-behavior commit.
- When a source behavior is defective, retain a source-characterization test and add a separate target test that captures the intended correction.
- Use real temporary Git repositories for integration behavior rather than mocking history-sensitive cases.

Required final state:

- `repo-context check`, `audit`, `explain`, and `init` are fully implemented.
- Text, JSON, and SARIF output contracts are tested.
- File limits, context sets, documentation reachability, local targets and fragments, base-size ratcheting, policy ratcheting, and exception governance match the specification.
- `scripts/context-check` and CI invoke the new package, not the source oracle.
- This repository validates itself with the new tool from a clean checkout and without network access.
- Distribution artifacts build and install in clean environments for the supported Python versions and platforms.
- Migration guidance exists for scene-maker's JSON policy.
- Pilot findings for `scene-maker`, `nano-dllm`, and `research-vault` are recorded without introducing project-specific engine branches.
- The active plan contains a final report and no unchecked release-blocking work.

Run `scripts/validate` now to establish the starter baseline, then begin Phase 0.

---
