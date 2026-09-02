# Version 1 commands and output

This contract defines command-boundary inputs, semantic exits, stream selection, text safety, the versioned JSON envelope, SARIF mapping, audit metrics, explain projection, and initialization diagnostics. Repository policy semantics remain owned by the linked configuration, budget, documentation, and ratchet contracts.

## Evaluation boundary

`check`, `audit`, and `explain` receive an evaluation date in addition to repository root, current policy path, working-tree snapshot, and optional base revision. `--evaluation-date YYYY-MM-DD` supplies it explicitly. When omitted, the CLI captures the current UTC calendar date exactly once before orchestration and injects that value into every exception decision and report field. Pure runners never read a clock, so identical explicit inputs produce identical ordered results.

The current config path and first-adoption sidecar are canonical repository-relative paths. They must be repo-contained regular files read through the snapshot-verified no-follow boundary, but they need not be Git-visible. Historical policy selection remains exact Git-tree data.

`explain` accepts `--base-ref` so an oversized path can report actual Git or manifest migration state. Without a base it reports the configured baseline source as unavailable and never infers history.

## Status and exit codes

The result status is one of `complete`, `configuration_error`, `operational_error`, or `internal_error`.

- Exit `0` means a command completed; for `check`, it also means no error-severity policy diagnostic remains after migration reconciliation.
- Exit `1` is exclusive to a completed `check` with at least one error-severity policy diagnostic. Warnings and notes do not change the exit.
- Exit `2` means argument parsing, configuration, repository access, initialization, or internal execution failed. Runtime `CFG` diagnostics make a repository run a configuration failure rather than a completed policy result.
- `audit` and `explain` return `0` after a complete run even when visible policy diagnostics exist. Explain filters unrelated path diagnostics from its output. `init` refusal returns `2`.

Expected failures never print a traceback. An unexpected exception becomes `INT001` with only its exception type exposed.

## Streams and broken pipes

Successful text is written to stdout. Text for exit `1` or `2` is written to stderr. JSON and SARIF always produce exactly one machine-readable document on stdout for semantic exits `0`, `1`, and `2`; stderr remains empty. `argparse` usage errors remain text on stderr with exit `2`.

A broken output pipe is caught without a traceback or secondary diagnostic. The already determined semantic exit is preserved, and the broken descriptor is redirected to the platform null device when available so interpreter shutdown cannot emit another error.

## Text output

Each diagnostic occupies one physical line and begins with uppercase severity and stable code. Paths and names use JSON string quoting, so controls, newlines, quotes, and backslashes cannot forge output lines. Structured details render as compact key-sorted JSON. A field path, real line and column, and hint appear only when present.

Every text report ends with exactly one line in this form:

```text
Summary: 2 errors, 1 warning, 1 note.
```

Counts are derived from the rendered diagnostic sequence. Audit and explain place their deterministic data sections before diagnostics and the final summary. Text audit lists at most the ten largest governed files and ten highest-fan-out documentation directories while JSON retains the complete ordered collections. Its remaining sections expose threshold debt, classification and context totals, migration status, exception status, and the count of base changes.

## JSON envelope

JSON is UTF-8, two-space-indented, literal-Unicode text with LF and one final newline. Machine documents are written through an explicit UTF-8 byte boundary rather than the process locale encoding. Public command paths reject Unicode surrogates, and diagnostic detail projection escapes any non-scalar text received from an operating-system argument boundary. Every command uses this top-level shape and fixed emission order:

```json
{
  "schema_version": 1,
  "tool": {
    "name": "repo-context",
    "version": "0.0.0"
  },
  "command": "check",
  "status": "complete",
  "summary": {
    "errors": 0,
    "warnings": 0,
    "notes": 0
  },
  "diagnostics": [],
  "data": {}
}
```

`tool.version` comes from the package's single authoritative version constant. `data` is `null` for a command failure. A diagnostic always has `code`, `severity`, `message`, `location`, `field_path`, `details`, and `hint`. `location` is `null` or contains `path`, `line`, and `column`, with absent positions represented as `null`. Details are a JSON object preserving their deterministic record order.

Completed check data contains evaluation date, resolved base identity when any, baseline source, and inventory, documentation, and context counts. Audit adds every governed file: sized paths are ordered by descending size then path, followed by paths without a raw size ordered by path. It also adds warning and hard assessments, classification counts, context members and totals, documentation metrics, migration records, exception status, and ratchet changes. Explain contains only one path's policy and assessment provenance, applied exception record and expiry status, context membership, documentation membership and edges, and migration record.

## Audit formulas

Audit documentation depth is the count of repository path components in a governed directory; `.` has depth zero. Directory fan-out is its direct non-index document count plus immediate child-directory count. Maximum depth is the maximum governed directory depth or zero when no directory exists.

`files_above_warning` includes both warning and raw hard assessments even when proven debt suppressed the final `CTX002`. Exception status includes expiry against the injected evaluation date and the number of current paths for which that exception won. `changes_from_base` is the ordered non-`RAT001` diagnostic projection plus the separate migration records; audit does not read unrelated base blobs merely to create a trend.

## SARIF 2.1.0

Only `check` accepts `--format sarif`. The document declares SARIF 2.1.0 and the standard schema URI. Stable diagnostic codes become sorted rule IDs; severity maps directly to `error`, `warning`, or `note`; structured field path, details, and hint remain result properties.

An artifact location is emitted only when the diagnostic path is the current config path or belongs to the current inventory snapshot. Its URI is percent-encoded and relative to `%SRCROOT%`. A region is emitted only for a real positive source line, and a column is never fabricated without a line. Global diagnostics, historical source labels, and failures without a completed snapshot have no location. `executionSuccessful` describes engine completion, so a completed policy check with violations remains a successful SARIF invocation even though the CLI exits `1`.

## Initialization

`init` requires a clean index, tracked worktree, and nonignored-untracked set both before evaluation and immediately before writing. Ignored untracked files do not make the repository dirty. `--force` permits replacement only of existing regular initialization artifacts; it never bypasses dirty-state or uncaptured-debt refusal.

The config parent directory must already exist as a real repo-contained directory. A symlink, junction, directory, or other non-regular destination is never replaced. Initialization fails closed with `INIT002` when descriptor-relative no-follow primitives are unavailable. Before inventory or preparation, it opens and retains the validated repository-root directory. Every prepared parent is reached without following links from that anchor, and the selected root pathname, parent chain, and directory identities are revalidated before and after activation. Moving or replacing the root or destination parent therefore refuses and rolls back the transaction.

All target paths are preflighted; temporary bytes, rollback quarantine placeholders, and directories are synced before or during installation. No-force installation is atomic and no-overwrite, and a destination appearing after preflight is path-scoped `INIT002`. Forced activation first moves the current regular destination into an owned quarantine, verifies that it is the preflight inode, promotes that verified inode to the rollback backup, renews an empty quarantine, and publishes the prepared bytes with no-overwrite semantics. Every published artifact is checked around its directory and parent revalidation, all non-guard artifacts receive a final group-boundary identity sweep, and every removed absence guard receives a final group-boundary absence check. Group rollback never blindly unlinks or overwrites a published name: it atomically moves the current target into an owned random quarantine, verifies that the moved inode is the installed artifact, and restores prior data with a no-overwrite link. Concurrent replacement data and displaced prior data are preserved under reported repository-relative recovery paths when ownership is uncertain. Once every replacement is installed and its directory synced, auxiliary cleanup failure returns `INIT004` without rolling committed destinations back and preserves the remaining recovery names.

Without `--capture-debt`, every starter-policy oversized authored file produces `INIT003` and no artifact is written. With capture, the sidecar is written before the config activation file and exists even when its entry list is empty. A non-capture run holds an owned absence guard at the sidecar name through config activation. Guard cleanup quarantines and verifies its inode; a concurrent replacement is restored or retained as recovery data, config activation rolls back, and the replacement is never deleted. Existing sidecars may not be silently retained by a non-capture initialization. Config and sidecar paths are excluded from their own debt assessment.

| Code | Meaning |
| --- | --- |
| `INIT001` | The repository is dirty at an initialization precondition check. |
| `INIT002` | A destination, parent, collision, or stale sidecar is unsafe. |
| `INIT003` | Starter-policy oversized authored content requires explicit debt capture. |
| `INIT004` | Atomic artifact preparation or installation failed. |
| `INT001` | An unexpected internal exception crossed the command boundary. |
