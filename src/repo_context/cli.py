"""Public arguments, streams, and semantic exit codes."""

from __future__ import annotations

import argparse
import os
import sys
from collections.abc import Sequence
from datetime import date, datetime, timezone
from typing import TextIO

from repo_context import __version__
from repo_context.diagnostics import INT_INTERNAL, operational_diagnostic
from repo_context.model import OutputFormat
from repo_context.report import (
    command_exit_code,
    render_emergency_failure,
    render_report,
)
from repo_context.run_model import CommandFailure, RunStatus
from repo_context.runner import explain_repository_path, initialize_repository, run_repository


CHECK_FORMATS = ("text", "json", "sarif")
REPORT_FORMATS = ("text", "json")


class _SafeArgumentParser(argparse.ArgumentParser):
    """Route argparse output through the shared broken-pipe boundary."""

    def _print_message(self, message: str | None, file: TextIO | None = None) -> None:
        if message:
            _emit(sys.stderr if file is None else file, message)


def build_parser() -> argparse.ArgumentParser:
    parser = _SafeArgumentParser(
        prog="repo-context",
        description=(
            "Enforce repository context budgets, documentation reachability, "
            "and monotonic policy ratchets."
        ),
    )
    parser.add_argument("--version", action="version", version=f"%(prog)s {__version__}")
    subparsers = parser.add_subparsers(
        dest="command",
        parser_class=_SafeArgumentParser,
    )

    check = subparsers.add_parser("check", help="Run blocking policy checks.")
    _add_repository_options(check, formats=CHECK_FORMATS)
    check.add_argument("--base-ref", help="Git revision used for ratchet comparisons.")

    audit = subparsers.add_parser("audit", help="Report context debt without changing files.")
    _add_repository_options(audit, formats=REPORT_FORMATS)
    audit.add_argument("--base-ref", help="Optional Git revision used for trend comparisons.")

    explain = subparsers.add_parser("explain", help="Explain the effective policy for one path.")
    _add_repository_options(explain, formats=REPORT_FORMATS)
    explain.add_argument("--base-ref", help="Optional Git revision used for migration status.")
    explain.add_argument("path", help="Repository-relative path to explain.")

    init = subparsers.add_parser("init", help="Create a starter policy for a repository.")
    init.add_argument("--repo", default=".", help="Repository root.")
    init.add_argument(
        "--config",
        default="repo-context.toml",
        help="Repository-relative destination policy path.",
    )
    init.add_argument(
        "--capture-debt",
        action="store_true",
        help="Record existing oversized files as migration debt.",
    )
    init.add_argument(
        "--force",
        action="store_true",
        help="Replace existing regular initialization artifacts.",
    )
    return parser


def _add_repository_options(
    parser: argparse.ArgumentParser,
    *,
    formats: tuple[str, ...],
) -> None:
    parser.add_argument("--repo", default=".", help="Repository root.")
    parser.add_argument(
        "--config",
        default="repo-context.toml",
        help="Repository-relative policy path.",
    )
    parser.add_argument("--format", choices=formats, default="text", help="Output format.")
    parser.add_argument(
        "--evaluation-date",
        type=_evaluation_date,
        help="UTC policy date in YYYY-MM-DD form (defaults to the current UTC date).",
    )


def main(argv: Sequence[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    if args.command is None:
        _emit(sys.stdout, parser.format_help())
        return 0

    output_format = OutputFormat.TEXT if args.command == "init" else OutputFormat(args.format)
    try:
        outcome = _dispatch(args)
        rendered = render_report(args.command, outcome, output_format)
        exit_code = command_exit_code(args.command, outcome)
    except Exception as error:
        outcome = _internal_failure(error)
        exit_code = 2
        try:
            rendered = render_report(args.command, outcome, output_format)
        except Exception:
            rendered = render_emergency_failure(args.command, outcome, output_format)

    stream = _output_stream(output_format, exit_code)
    if output_format is OutputFormat.TEXT:
        _emit(stream, rendered)
    else:
        _emit_utf8(stream, rendered)
    return exit_code


def _dispatch(args):
    if args.command == "init":
        return initialize_repository(
            args.repo,
            config_path=args.config,
            capture_debt=args.capture_debt,
            force=args.force,
        )
    evaluation_date = args.evaluation_date or datetime.now(timezone.utc).date()
    if args.command == "explain":
        return explain_repository_path(
            args.repo,
            args.path,
            config_path=args.config,
            base_ref=args.base_ref,
            evaluation_date=evaluation_date,
        )
    return run_repository(
        args.repo,
        config_path=args.config,
        base_ref=args.base_ref,
        evaluation_date=evaluation_date,
    )


def _evaluation_date(value: str) -> date:
    try:
        parsed = date.fromisoformat(value)
    except ValueError as error:
        raise argparse.ArgumentTypeError("must be a calendar date in YYYY-MM-DD form") from error
    if parsed.isoformat() != value:
        raise argparse.ArgumentTypeError("must use canonical YYYY-MM-DD form")
    return parsed


def _internal_failure(error: Exception) -> CommandFailure:
    diagnostic = operational_diagnostic(
        INT_INTERNAL,
        "unexpected internal failure",
        details=(("error_type", type(error).__name__),),
        hint="rerun after preserving the repository state and report this diagnostic",
    )
    return CommandFailure(RunStatus.INTERNAL_ERROR, (diagnostic,))


def _output_stream(output_format: OutputFormat, exit_code: int) -> TextIO:
    if output_format is not OutputFormat.TEXT or exit_code == 0:
        return sys.stdout
    return sys.stderr


def _emit(stream: TextIO, value: str) -> bool:
    try:
        stream.write(value)
        stream.flush()
        return True
    except BrokenPipeError:
        _silence_broken_pipe(stream)
        return False


def _emit_utf8(stream: TextIO, value: str) -> bool:
    try:
        buffer = stream.buffer
    except AttributeError:
        return _emit(stream, value)
    try:
        buffer.write(value.encode("utf-8", errors="strict"))
        buffer.flush()
        return True
    except BrokenPipeError:
        _silence_broken_pipe(stream)
        return False


def _silence_broken_pipe(stream: TextIO) -> None:
    try:
        descriptor = stream.fileno()
        null_descriptor = os.open(os.devnull, os.O_WRONLY)
        try:
            os.dup2(null_descriptor, descriptor)
        finally:
            os.close(null_descriptor)
    except (AttributeError, OSError, ValueError):
        pass
