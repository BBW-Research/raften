# 0007: Preserve the repo-context CLI under a distinct distribution name

- Status: accepted
- Date: 2026-09-02

## Context

Python distribution names, import packages, and console-script names are independent identities. The intended command `repo-context` and import package `repo_context` already form the documented public interface. However, the public [PyPI `repo-context` project](https://pypi.org/project/repo-context/) belongs to an unrelated package and currently publishes version 0.4.0. Building or publishing this project with the same distribution name would create ambiguous artifacts and cannot establish ownership of that PyPI namespace.

An exact PyPI project lookup for `repo-context-policy` returned no existing project on the decision date. Absence does not reserve the name; actual publication still requires repository ownership, PyPI project creation, and trusted-publisher configuration.

## Decision

Use `repo-context-policy` as the Python distribution name. Preserve `repo_context` as the import package and `repo-context` as the console command and human-facing tool name.

Use version 1.0.0 for the first stable artifact. Later stable versions follow the documented PEP 440-compatible `MAJOR.MINOR.PATCH` policy.

## Consequences

- Wheel and source-distribution filenames use the normalized `repo_context_policy` prefix.
- Installation documentation names the distribution, while command documentation continues to say `repo-context`.
- A future publisher must recheck name availability immediately before creating the PyPI project.
- Changing the distribution channel or name later does not require changing policy files, the import package, or project-local wrappers.
