"""Target command-line contract for the standalone implementation."""

from __future__ import annotations

import argparse
import sys
from collections.abc import Sequence
from pathlib import Path

from repo_context import __version__


FORMATS = ("text", "json", "sarif")


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="repo-context",
        description=(
            "Enforce repository context budgets, documentation reachability, "
            "and monotonic policy ratchets."
        ),
    )
    parser.add_argument("--version", action="version", version=f"%(prog)s {__version__}")
    subparsers = parser.add_subparsers(dest="command")

    check = subparsers.add_parser("check", help="Run blocking policy checks.")
    _add_common_options(check)
    check.add_argument("--base-ref", help="Git revision used for ratchet comparisons.")

    audit = subparsers.add_parser("audit", help="Report context debt without changing files.")
    _add_common_options(audit)
    audit.add_argument("--base-ref", help="Optional Git revision used for trend comparisons.")

    explain = subparsers.add_parser("explain", help="Explain the effective policy for one path.")
    _add_common_options(explain)
    explain.add_argument("path", type=Path, help="Repository-relative path to explain.")

    init = subparsers.add_parser("init", help="Create a starter policy for a repository.")
    init.add_argument("--repo", type=Path, default=Path.cwd(), help="Repository root.")
    init.add_argument(
        "--config",
        type=Path,
        default=Path("repo-context.toml"),
        help="Repository-relative destination policy path.",
    )
    init.add_argument(
        "--capture-debt",
        action="store_true",
        help="Record existing oversized files as migration debt.",
    )
    init.add_argument("--force", action="store_true", help="Replace an existing policy file.")
    return parser


def _add_common_options(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("--repo", type=Path, default=Path.cwd(), help="Repository root.")
    parser.add_argument(
        "--config",
        type=Path,
        default=Path("repo-context.toml"),
        help="Repository-relative policy path.",
    )
    parser.add_argument("--format", choices=FORMATS, default="text", help="Diagnostic format.")


def main(argv: Sequence[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    if args.command is None:
        parser.print_help()
        return 0

    print(
        f"repo-context {args.command!r} is scaffolded but not implemented; "
        "follow docs/plans/active/standalone-tool.md",
        file=sys.stderr,
    )
    return 2
