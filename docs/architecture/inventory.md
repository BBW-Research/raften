# Repository inventory boundary

`raften.inventory` is the public facade and the only production module allowed to invoke Git or read base-revision objects. It accepts an explicit root, returns immutable sorted records, and raises `RepositoryAccessError` containing stable structured diagnostics for expected failures. It never searches upward from the selected path and never infers a repository from the package location.

The facade delegates pure Git-output decoding to `git_records.py`, trusted executable discovery to `git_executable.py`, no-follow metadata inspection to `worktree.py`, and shared diagnostic construction to `repository_errors.py`. These helpers never import the facade, so dependency flow remains one-way and public callers retain one repository API.

## Root validation

`open_repository()` rejects an empty or NUL-containing input, resolves the supplied directory once, accepts a symlink to a root by returning its canonical target, and requires the candidate to be the exact top level of a non-bare Git worktree. A repository subdirectory is rejected rather than silently changing the selected target. Before any Git child, `git_administration.py` binds the administration identity carried by `RepositoryHandle`: an in-root real `.git` directory, or a regular no-follow gitfile whose target is exactly a common directory's `worktrees/<id>` registration. The registration's bounded `commondir` pointer must name that common directory and its `gitdir` backlink must name the canonical selected root's `.git` entry. This follows Git's documented [linked-worktree registration](https://git-scm.com/docs/git-worktree). Unrelated or separate-git-dir gitfiles, submodule gitfiles without this registration, nested common indirection, symlinks, and special pointer files refuse with `GIT001`.

Every Git invocation uses the validated root as its explicit current working directory, pins `--git-dir` and `--work-tree`, and supplies absolute validated `GIT_COMMON_DIR` and `GIT_OBJECT_DIRECTORY` values. It verifies the immutable binding before spawning and after reaping the child, including on failed collection. A root-only handle cannot invoke the transport. Administration changes abort with `GIT005` before results are consumed; the process current directory and renewed Git discovery have no effect on inventory or base access.

Each child scope also retains descriptor-bound namespace guards for the selected root and, when external, the common directory. The same macOS vnode rename notifications and conservative timestamp fallback described below detect root or ancestor substitution restored before the child returns. Scope exit verifies the guards even when Git fails, and releases every descriptor and event queue. Git namespace failures map to `GIT005`.

Binding performs one bounded no-follow scan of administration-root metadata and Git input directories (`objects`, `refs`, `info`, `logs`, and `reftable`), rejecting symlinks and special files without reading object bodies. Disabled hooks, non-recursed submodules, other worktree registrations, and `rr-cache` are omitted. Nonempty `objects/info/alternates` refuses external object borrowing. Pointer files allow 8,192 bytes; scans allow 250,000 entries, 4,096 retained directories, and 4,096 retained mutable metadata files, with `GIT010` on overflow. Directory device/inode/mode/size/mtime/ctime witnesses detect later leaf replacement and out-and-back directory changes. Root metadata, nested refs, reflogs, reftable inputs, object-info metadata, and pointer files retain the same full witnesses to catch in-place changes; canonical ancestors retain no-follow directory identities. Checks depend on retained directory and metadata-file counts rather than object-file count. Concurrent administrative activity is conservatively refused, and timestamp witnesses assume faithful filesystem change reporting. Initialization retains its `INIT002` diagnostic when its namespace guard is invalidated.

Valid `sharedindex.<object-id>` files retain no-follow device/inode/mode/size witnesses plus their containing directory's replacement witness, allowing Git's documented [split-index timestamp refresh](https://git-scm.com/docs/git-update-index#_split_index) during reads. Freshness updates preserve binding; replacement or symlink insertion still refuses.

Initialization binds the canonical directory namespace before Git validation. It retains no-follow directory descriptors for the root and every canonical ancestor below the filesystem root. It rechecks that binding after root validation, inventory, clean-state capture, content evaluation, and immediately before artifact publication. Direct or ancestor out-and-back renames invalidate preflight even when the selected pathname again names the original inode. The same retained root descriptor authorizes transaction writes. Preflight witnesses stop being checked when Raften's own staging begins; existing descriptor-relative parent and root identity barriers remain active during publication.

On macOS, descriptor-bound [kqueue vnode notifications](https://docs.python.org/3.12/library/select.html#kevent-objects) observe rename, deletion, and revocation of each retained directory. Watches are registered before validation without draining earlier events; any event or queue failure refuses initialization with `INIT002`. Events coalesce per watched descriptor, and verification reads at most one because any event invalidates preflight. Unrelated sibling creation, renaming, or deletion does not invalidate an ancestor watch. The root additionally retains its device/inode/mtime/ctime content witness. Where kqueue is unavailable, including Linux, every retained directory uses that timestamp witness instead. This conservative fallback can refuse initialization when unrelated ancestor directory entries change; retry after that activity stops. Both paths assume the local filesystem faithfully reports the relevant changes, and the engine never retries automatically into a mixed binding.

Normal `check`, `audit`, and `explain` evaluation acquires the same root/ancestor namespace guard before opening Git and retains its descriptors through all inventory, content, documentation, and baseline work. It verifies after root opening, after inventory, before returning any result, and before propagating expected failures. Changed or unavailable anchoring produces `GIT005`; descriptors close on all paths. Explain projection and output rendering then use immutable results without filesystem reads. The guard detects coherent replacement trees and restored renames under its existing filesystem assumptions. Root entry creation/deletion also refuses. On macOS vnode events ignore unrelated ancestor sibling activity; the timestamp fallback on other systems conservatively refuses such activity, so concurrent namespace changes may require a retry.

## Git process isolation

Each repository handle owns a cumulative I/O budget independent of equality and snapshot identity. All Git launches, current content reads, and streaming index-verification hashes charge this shared session before work; expanded base blobs reserve their declared size before the content child. The [content envelope](../specs/file-budgets-v1.md#operational-content-envelope) defines the fixed byte and process ceilings.

Git is invoked with an argument vector, `stdin` disconnected, binary captured streams, no shell, and a 120-second operation timeout. Before setting the child working directory, the process resolves Git to a canonical absolute executable through absolute `PATH` directories only. Empty, relative, duplicate, nonexistent, and selected-repository directories are removed after canonicalization, so a repository file or a symlinked path entry into the repository cannot become the Git executable. The sanitized path is also passed to Git, and Windows current-directory executable search is disabled; absolute-directory lookup retains the platform's `PATHEXT` behavior without prepending the current directory.

On supported macOS/Linux hosts, both child pipes are drained concurrently against one deadline that includes process exit. Standard output is capped at 64 MiB and standard error at 64 KiB; error bytes are counted and discarded. Metadata commands additionally stop at 250,000 NUL records or a record longer than 8,320 bytes, with an exact UTF-8 path ceiling of 8,192 bytes before decoding. Current tracked plus untracked paths share the 250,000-path ceiling. The envelope includes the supported 100,000-path workload. Overflow raises `GIT010` with `operation`, `resource`, and `limit`; every failed child is killed if still running and reaped. NUL decoding yields one record at a time from the bounded output instead of copying the complete stream into split collections. These fixed host-safety limits cannot be raised by repository policy.

Ambient `GIT_*` variables are removed. Prompts, optional locks, lazy fetching of missing partial-clone objects, system configuration, global configuration, attributes from the system file, and locale-sensitive output are disabled or fixed.

`core.excludesFile` is explicitly neutralized, `core.fsmonitor` is set to `false`, and `core.hooksPath` points at the platform null device so repository-configured filesystem monitors and hooks cannot run. The supported Git floor interprets the Boolean filesystem-monitor setting directly instead of attempting to execute the null device as a hook. The untracked cache is disabled so current directory enumeration is authoritative rather than dependent on cached extension state. Consequently `--exclude-standard` means repository-owned `.gitignore` files and `.git/info/exclude`, not a user-global or externally configured ignore file. Repository-local ignore rules still apply, while a tracked path remains inventoried even if a later ignore rule covers it.

Cleanliness is derived from the isolated inventory, the exact `HEAD` tree, index metadata, and no-follow raw worktree reads. It does not invoke porcelain status, attributes, or configured clean and smudge filters. Raw bytes, executable state, and symlink targets must match the index; gitlinks fail closed because version 1 does not recurse into nested repositories. A worktree that Git considers clean only after attribute-driven conversion is therefore conservatively refused by `init` and release-source qualification. Regular blobs that later evaluation will not inspect are hashed incrementally without retaining their contents. Initialization defers verification of evaluator-selected blobs until each file is read, verifies and consumes that one value immediately, and retains no aggregate content cache.

Version 1 supports Git 2.39.5 or newer. This conservative floor is the oldest Git version exercised by the release matrix and supplies every feature used by the documented argument vectors, including `rev-parse --end-of-options`; the engine does not weaken ref safety for an older executable.

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

`read_worktree_bytes()` is the only public current-content reader. It delegates to `worktree.py`, rechecks parents, uses descriptor-relative no-follow and nonblocking opens, compares descriptor identity before and after the raw read, and bounds reading to the snapshot size plus one byte after rejecting snapshots above the fixed [content envelope](../specs/file-budgets-v1.md#operational-content-envelope). Same-size replacement, in-place mutation, concurrent growth, type changes, and symlink or junction redirection therefore fail as `GIT005`; unrelated open or read failures use `GIT009`. A platform without the required secure open primitives fails closed instead of using a path-following fallback. The [file and context budget contract](../specs/file-budgets-v1.md) defines how one verified read is shared by later checks.

`inspect_repository_path()` creates the same no-follow snapshot record for one canonical repo-contained config or sidecar path without requiring Git visibility. It returns an explicit missing record rather than following or guessing. `repository_is_clean()` compares the current index with `HEAD`, verifies indexed blobs against raw worktree content and type, and rejects nonignored-untracked paths. Initialization captures that verified state before evaluation, then immediately before mutation repeats inventory and `HEAD` resolution and requires the complete identities to remain equal; unchanged regular content is not reread. An empty unborn repository is clean, while a staged addition in an unborn repository is not.

A tracked path already listed by the deletion view becomes `deleted` plus `missing`. A path that disappears, appears, or changes through an intermediate component after the relevant Git view produces `GIT005`; an unrelated filesystem access failure produces `GIT009`. The engine does not retry into a mixed snapshot or lock the user's worktree.

## Base revisions and objects

Base access never checks out a tree and never writes the worktree or index. `GIT_NO_REPLACE_OBJECTS=1` makes validated commit and blob identities exact even when the repository has local replacement refs:

1. `git rev-parse --verify --end-of-options REF^{commit}` resolves the requested ref to a commit object identity and prevents option injection.
2. `git ls-tree -r -t -z --full-tree COMMIT_ID` returns complete tree, blob, and gitlink metadata with NUL-framed paths.
3. `git cat-file -s OBJECT_ID` checks expanded size against the selected content ceiling, then `git cat-file blob OBJECT_ID` reads a selected blob lazily by validated object identity with an independent output ceiling.

Base metadata is sorted independently of Git output. Directories use mode `040000` with tree objects, regular, executable, and symlink entries have blob objects, and a gitlink has a commit object. Trees and gitlinks cannot be read as blobs. Blob bytes are returned exactly, including NUL or invalid UTF-8, because content classification belongs to a later phase. Base-operation tests preserve byte-identical index content, selected dirty worktree bytes, deletion and symlink state, and porcelain status; the status probe itself disables optional locks.

## Diagnostic identities

| Code | Meaning |
| --- | --- |
| `GIT001` | The explicit root or its Git administration is unavailable, unsafe, or not owned by the selected worktree |
| `GIT002` | Git could not execute, timed out, or a current-inventory command failed |
| `GIT003` | Git returned malformed framing, metadata, object identity, or non-UTF-8 path data |
| `GIT004` | Git returned an unsafe or noncanonical repository path |
| `GIT005` | The scan namespace, a listed worktree path, or bound Git administration changed or redirected through an unsafe component |
| `GIT006` | A requested base ref is empty, missing, unavailable, or does not resolve to a commit |
| `GIT007` | A base tree or selected base blob is unavailable or has the wrong object type |
| `GIT008` | The index contains unresolved merge stages |
| `GIT009` | Filesystem metadata or content access failed, including absence of a secure no-follow open primitive |
| `GIT010` | Repository-controlled data exceeds a fixed operational resource ceiling |
