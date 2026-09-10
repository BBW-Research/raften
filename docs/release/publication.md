# Repository publication

The canonical repository is [`BBW-Research/raften`](https://github.com/BBW-Research/raften), GitHub repository ID `1354736712`. It remains private as of 2026-09-10. The private rename and current review workflow are recorded in [decision 0010](../decisions/0010-canonical-repository-and-review-controls.md); artifact publication follows the [release guide](index.md).

## Completed preparation

The product, distribution, Python package, and CLI rename was merged through [PR #3](https://github.com/BBW-Research/raften/pull/3). Fresh Raften builds and supported-platform qualification are recorded in the [acceptance evidence](../quality/acceptance.md#distribution-and-pilots). The GitHub repository was then renamed from `BBW-Research/repo-context` while private, retaining its identity, history, and protection settings.

GitHub redirects ordinary web and Git references after a rename, but callers of hosted Actions need explicit updates. Do not reuse the former repository name while those redirects are needed. See GitHub's [rename behavior](https://docs.github.com/en/repositories/creating-and-managing-repositories/renaming-a-repository).

## Resolve publication scope

Before changing visibility, review the information that will become public: file contents across every branch and tag, raw author and committer identities, commit messages, pull requests, issues, wiki content, and Actions logs and artifacts. Include retained pilot material and upstream provenance. Keep detailed privacy reports outside the repository.

If historical identities or content must remain private, complete a coordinated cleanup of the existing repository or use a fresh public repository containing only reviewed source. A fresh repository also needs its own access controls and CI qualification. A `.mailmap` only changes identity presentation; it does not remove metadata from Git objects. A history rewrite also requires checking provider-held pull-request references and cached commits, as described in GitHub's [sensitive-data removal guidance](https://docs.github.com/en/authentication/keeping-your-account-and-data-secure/removing-sensitive-data-from-a-repository).

Record the approved source commit and remote branch/tag inventory privately, and repeat the scan if either changes. A pattern scan is evidence for the inspected scope, not proof that all sensitive material has been identified.

## Final private checks

1. Verify the canonical URLs in package metadata, the README, and release guidance, plus the repository description. Check CI consumers for pinned URLs, repository allowlists, and any hosted-Action references using the former name.
2. Require the full CI matrix and stable `Required repository policy` check for the exact source commit. Inspect its retained Actions logs and artifacts before publication.
3. Resolve the privacy review above, including any wiki or retained artifact that could not be inspected. Use an approved public commit identity for subsequent commits.
4. Verify the repository ID, private visibility, CODEOWNERS, and effective [branch controls](index.md#repository-controls). Preserve the verified settings through publication.

## Make the repository public

Approve the exact repository and reviewed state after the privacy findings are resolved. Changing visibility exposes Actions history and logs and disables push rulesets; GitHub documents these effects in its [visibility guidance](https://docs.github.com/en/repositories/managing-your-repositorys-settings-and-features/managing-repository-settings/setting-repository-visibility).

Once authorized, use the [GitHub CLI edit command](https://cli.github.com/manual/gh_repo_edit):

```sh
gh repo edit BBW-Research/raften --visibility public --accept-visibility-change-consequences
```

Verify the same repository ID, public visibility, anonymous clone access, required checks, and effective branch protections. Use the canonical URL for CI consumers and pin a reviewed commit or qualified artifact. Public source access can precede a package release; publishing a version or release artifact still requires qualification of the exact candidate under the [acceptance criteria](../quality/acceptance.md#distribution-and-pilots).
