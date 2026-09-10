"""Canonical repository-path validation for public command arguments."""

from __future__ import annotations

from pathlib import Path

from raften.config import ConfigurationError
from raften.diagnostics import CFG_PATH, config_diagnostic
from raften.matcher import normalize_platform_path, path_validation_error


def validate_command_path(value: str | Path, field_path: str) -> str:
    rendered = value.as_posix() if isinstance(value, Path) else value
    error = _unicode_scalar_error(rendered) if isinstance(rendered, str) else "path must be text"
    if error is None:
        error = path_validation_error(rendered)
    if error is not None:
        _fail_command_path(rendered, field_path, error)
    return rendered


def validate_candidate_command_path(value: str | Path, field_path: str) -> str:
    """Normalize and validate a user-supplied Git candidate path."""

    rendered = value.as_posix() if isinstance(value, Path) else value
    error = _unicode_scalar_error(rendered) if isinstance(rendered, str) else "path must be text"
    normalized: str | None = None
    if error is None:
        try:
            normalized = normalize_platform_path(rendered)
        except ValueError as path_error:
            error = str(path_error)
    if error is not None:
        _fail_command_path(rendered, field_path, error)
    assert normalized is not None
    return normalized


def _fail_command_path(value: object, field_path: str, error: str) -> None:
    safe_value = (
        value.encode("utf-8", errors="backslashreplace").decode("utf-8")
        if isinstance(value, str)
        else str(value)
    )
    diagnostic = config_diagnostic(
        CFG_PATH,
        "<command-line>",
        field_path,
        error,
        details=(("value", safe_value),),
    )
    raise ConfigurationError((diagnostic,))


def _unicode_scalar_error(value: str) -> str | None:
    try:
        value.encode("utf-8", errors="strict")
    except UnicodeEncodeError:
        return "path must contain only Unicode scalar values"
    return None
