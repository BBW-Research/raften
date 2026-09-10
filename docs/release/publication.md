# Repository publication

The proposed target is `BBW-Research/raften`. As of 2026-09-10, the source repository remains private at `BBW-Research/repo-context` (GitHub repository ID `1354736712`). Preparation does not execute the remote rename, visibility switch, history rewrite, or package publication. Artifact release requirements remain in the [release guide](index.md).

## Resolve publication scope

Before changing visibility, approve the information that will become public: file contents across every branch and tag, raw author and committer identities, commit messages, pull requests, issues, wiki content, and Actions logs and artifacts. Review retained pilot material and upstream provenance as part of that scope. Keep detailed privacy reports outside the repository.

If historical identities or content must remain private, choose either a coordinated cleanup of the existing repository or a fresh public repository containing only the reviewed source snapshot. A fresh repository also needs its own access controls and CI qualification. Do not execute the existing-repository commands below for that alternative. A `.mailmap` only changes identity presentation; it does not remove the original metadata from Git objects. History cleanup also requires reviewing old pull-request references and provider caches; follow GitHub's [sensitive-data removal guidance](https://docs.github.com/en/authentication/keeping-your-account-and-data-secure/removing-sensitive-data-from-a-repository).

Record the approved source commit and remote branch/tag inventory privately, and repeat the scan if either changes. A pattern-based scan is evidence for the inspected scope, not proof that all sensitive material has been identified.

## Prepare the existing repository

1. Review and merge the Raften changes through the repository's protected-branch workflow while it is private. Require the full CI matrix and stable `Required repository policy` check for the exact commit.
2. Resolve the privacy review above, including any wiki or retained Actions artifact that could not be inspected. Use an approved public commit identity for subsequent commits.
3. Recheck that `BBW-Research/raften` is available and authenticate an administrator. Verify the repository ID, current visibility, branch protection, code owners, and required check before mutation. Record the effective settings; a repository-level admin flag alone does not prove an API token can manage them.
4. Rename while the repository is still private. This command requires explicit authorization for the remote rename:

```sh
gh repo rename raften --repo BBW-Research/repo-context
git remote set-url origin https://github.com/BBW-Research/raften.git
```

The syntax follows the [GitHub CLI rename manual](https://cli.github.com/manual/gh_repo_rename). GitHub redirects ordinary web and Git references after a rename, but callers of hosted Actions need explicit updates. Do not reuse the old repository name if those redirects are needed. See GitHub's [rename behavior](https://docs.github.com/en/repositories/creating-and-managing-repositories/renaming-a-repository).

Update the live repository URLs in `pyproject.toml`, `README.md`, and the release guide, plus the GitHub description to “Policy checks for code and documentation.” Preserve historical decision records and upstream provenance. Check external CI consumers for pinned URLs, repository allowlists, and any `uses:` references to the old name. Validate and merge the URL changes while private, then inspect the resulting CI logs and artifacts before publication.

## Make the repository public

Approve the exact repository and reviewed state after the privacy findings are resolved. Changing visibility exposes Actions history and logs and disables push rulesets, so check the resulting settings against the controls in the [release guide](index.md#repository-controls). These consequences are documented by [GitHub](https://docs.github.com/en/repositories/managing-your-repositorys-settings-and-features/managing-repository-settings/setting-repository-visibility).

Only after that approval, run the explicit visibility command from the [GitHub CLI edit manual](https://cli.github.com/manual/gh_repo_edit):

```sh
gh repo edit BBW-Research/raften --visibility public --accept-visibility-change-consequences
```

Verify the same repository ID, public visibility, anonymous clone access, required checks, and effective branch protections. Use the new canonical URL for CI consumers and pin a reviewed commit or qualified artifact. Public source access can precede a package release; publishing a version or release artifact still requires fresh Raften qualification under the [acceptance criteria](../quality/acceptance.md#distribution-and-pilots).
