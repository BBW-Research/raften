# Repository inventory boundary

`repo_context.inventory` is the public facade and the only production module allowed to invoke Git or read base-revision objects. It accepts an explicit root, returns immutable sorted records, and raises `RepositoryAccessError` containing stable structured diagnostics for expected failures. It never searches upward from the selected path and never infers a repository from the package location.

The facade delegates pure Git-output decoding to `git_records.py`, trusted executable discovery to `git_executable.py`, no-follow metadata inspection to `worktree.py`, and shared diagnostic construction to `repository_errors.py`. These helpers never import the facade, so dependency flow remains one-way and public callers retain one repository API.

## Root validation

`open_repository()` rejects an empty or NUL-containing input, resolves the supplied directory once, accepts a symlink to a root by returning its canonical target, and requires the candidate to be the exact top level of a non-bare Git worktree. A repository subdirectory is rejected rather than silently changing the selected target. Linked worktrees are supported without assuming whether `.git` is a directory or file.

Every later Git invocation uses the validated root as its explicit current working directory. The process current directory therefore has no effect on inventory or base access.

## Git process isolation

Git is invoked with an argument vector, `stdin` disconnected, binary captured streams, no shell, and a 120-second operation timeout. Before setting the child working directory, the process resolves Git to a canonical absolute executable through absolute `PATH` directories only. Empty, relative, duplicate, nonexistent, and selected-repository directories are removed after canonicalization, so a repository file or a symlinked path entry into the repository cannot become the Git executable. The sanitized path is also passed to Git, and Windows current-directory executable search is disabled; absolute-directory lookup retains the platform's `PATHEXT` behavior without prepending the current directory.

Ambient `GIT_*` variables are removed. Prompts, optional locks, lazy fetching of missing partial-clone objects, system configuration, global configuration, attributes from the system file, and locale-sensitive output are disabled or fixed.

`core.excludesFile` is explicitly neutralized. `core.fsmonitor` and `core.hooksPath` point at the platform null device so an executable configured by the repository cannot run during index refresh or as a hook. A null-device pathname is used instead of the newer Boolean `core.fsmonitor = false` spelling because Git 2.35.1 and earlier interpret Boolean text as a hook pathname. The untracked cache is disabled so current directory enumeration is authoritative rather than dependent on cached extension state. Consequently `--exclude-standard` means repository-owned `.gitignore` files and `.git/info/exclude`, not a user-global or externally configured ignore file. Repository-local ignore rules still apply, while a tracked path remains inventoried even if a later ignore rule covers it.

The boundary requires Git features used by the documented argument vectors, including `rev-parse --end-of-options`. Distribution validation will establish the supported Git-version floor; the engine does not weaken ref safety for an older executable.

## Current inventory

One snapshot reads three NUL-delimited Git views in order:

1. `git ls-files --stage -t -z` supplies tracked paths, index modes, object identities, merge stages, and the `S` tag for skip-worktree entries.
2. `git ls-files --deleted -z` distinguishes tracked deletions already visible at the snapshot boundary from later disappearance.
3. `git ls-files --others --exclude-standard -z` supplies non-ignored untracked paths.

All records use strict framing and strict UTF-8 path decoding. Duplicate paths, impossible tracked/untracked overlap, unsupported modes, malformed object identities, and nonzero merge stages fail the whole snapshot rather than producing guessed or partial state. Object identities support both 40-character SHA-1 and 64-character SHA-256 repositories.

The resulting tuple is explicitly sorted by exact Python string order, with no case folding or Unicode normalization. Rename identity is not inferred: an unstaged rename is a tracked deletion plus an untracked addition, while a staged rename reflects the destination stored in the index.

| Inventory state | `source` | `kind` | Additional data |
| --- | --- | --- | --- |
| Present tracked regular file | `tracked` | `regular` | Raw worktree byte size, filesystem identity, and index mode/object identity |
| Present non-ignored untracked regular file | `untracked` | `regular` | Raw worktree byte size and filesystem identity |
| Tracked path absent at the deletion snapshot | `deleted` | `missing` | Index mode/object identity |
| Sparse-checkout path absent with the skip-worktree bit | `tracked` | `missing` | Index mode/object identity and `skip_worktree = true` |
| Leaf symlink | `tracked` or `untracked` | `symlink` | Link text read with `readlink`; target is not followed |
| Directory, FIFO, device, or other non-regular leaf | `tracked` or `untracked` | `other` | No byte size |

Later current-content checks exclude `deleted` entries, while ratchet logic may still use their base-tree records. A submodule is represented by index mode `160000`; version 1 does not recurse into it as another governed repository.

## Filesystem safety and races

Worktree inspection uses `lstat`. Every parent component is checked before the leaf so an existing intermediate symlink or Windows junction cannot redirect inspection outside the repository. A leaf symlink is recorded without opening its target. Regular entries retain mode, device, inode, size, modification time, and change time as their snapshot identity.

`read_worktree_bytes()` is the only public current-content reader. It delegates to `worktree.py`, rechecks parents, uses descriptor-relative no-follow and nonblocking opens, compares descriptor identity before and after the raw read, and bounds reading to the snapshot size plus one byte. Same-size replacement, in-place mutation, concurrent growth, type changes, and symlink or junction redirection therefore fail as `GIT005`; unrelated open or read failures use `GIT009`. A platform without the required secure open primitives fails closed instead of using a path-following fallback. The [file and context budget contract](../specs/file-budgets-v1.md) defines how one verified read is shared by later checks.

A tracked path already listed by the deletion view becomes `deleted` plus `missing`. A path that disappears, appears, or changes through an intermediate component after the relevant Git view produces `GIT005`; an unrelated filesystem access failure produces `GIT009`. The engine does not retry into a mixed snapshot or lock the user's worktree.

## Base revisions and objects

Base access never checks out a tree and never writes the worktree or index. `GIT_NO_REPLACE_OBJECTS=1` makes validated commit and blob identities exact even when the repository has local replacement refs:

1. `git rev-parse --verify --end-of-options REF^{commit}` resolves the requested ref to a commit object identity and prevents option injection.
2. `git ls-tree -r -t -z --full-tree COMMIT_ID` returns complete tree, blob, and gitlink metadata with NUL-framed paths.
3. `git cat-file blob OBJECT_ID` reads a selected blob lazily by validated object identity.

Base metadata is sorted independently of Git output. Directories use mode `040000` with tree objects, regular, executable, and symlink entries have blob objects, and a gitlink has a commit object. Trees and gitlinks cannot be read as blobs. Blob bytes are returned exactly, including NUL or invalid UTF-8, because content classification belongs to a later phase. Base-operation tests preserve byte-identical index content, selected dirty worktree bytes, deletion and symlink state, and porcelain status; the status probe itself disables optional locks.

## Diagnostic identities

| Code | Meaning |
| --- | --- |
| `GIT001` | The explicit root is absent, not a directory, not a worktree root, bare, or a repository subdirectory |
| `GIT002` | Git could not execute, timed out, or a current-inventory command failed |
| `GIT003` | Git returned malformed framing, metadata, object identity, or non-UTF-8 path data |
| `GIT004` | Git returned an unsafe or noncanonical repository path |
| `GIT005` | A listed worktree path disappeared, appeared, or changed through an unsafe intermediate component |
| `GIT006` | A requested base ref is empty, missing, unavailable, or does not resolve to a commit |
| `GIT007` | A base tree or selected base blob is unavailable or has the wrong object type |
| `GIT008` | The index contains unresolved merge stages |
| `GIT009` | Filesystem metadata or content access failed, including absence of a secure no-follow open primitive |
