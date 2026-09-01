# 0001: Python and standard-library-first runtime

- Status: accepted
- Date: 2026-08-31

## Context

The seed checker is Python, the work is dominated by Git subprocesses, path handling, text parsing, and policy semantics, and the user's projects already rely heavily on Python. A compiled Rust implementation would add release artifacts, cross-platform build work, and a second language before the policy contract is stable.

## Decision

Build the first standalone implementation in Python 3.12 or newer. The runtime remains standard-library-only unless a later accepted decision demonstrates that a dependency materially improves correctness and cannot be replaced by a small maintainable implementation.

Development and packaging dependencies are not automatically forbidden, but they must be reviewed before introduction, pinned through the chosen workflow, and kept out of the offline runtime path. The starter uses `unittest` and direct `PYTHONPATH` execution so validation works without installing anything.

## Consequences

- Iteration and behavioral extraction remain fast.
- The tool can initially ship as a Python package and optional zipapp.
- Performance work begins with measurement rather than a language rewrite.
- A later Rust implementation may preserve the CLI, configuration, diagnostics, and fixture corpus once those contracts stabilize.
