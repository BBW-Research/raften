"""Strict, side-effect-free parsing for version 1 repository policies."""

from __future__ import annotations

import tomllib
from pathlib import Path
from typing import Any

from repo_context.config_records import (
    parse_context_sets,
    parse_entrypoints,
    parse_exception_records,
)
from repo_context.config_rules import parse_file_rules, parse_path_overrides
from repo_context.config_template import DEFAULT_POLICY_TOML
from repo_context.config_validation import Validator
from repo_context.config_values import parse_enum, parse_path_list, parse_pattern_list
from repo_context.diagnostics import (
    CFG_INCONSISTENT,
    CFG_PARSE,
    CFG_VALUE,
    config_diagnostic,
    config_diagnostic_sort_key,
)
from repo_context.model import (
    Diagnostic,
    DocumentationSettings,
    ExceptionSettings,
    InventoryMode,
    OutputFormat,
    OutputSettings,
    Policy,
    RatchetSettings,
    RepositorySettings,
    TextEncoding,
)


_TOP_LEVEL_KEYS = frozenset(
    {
        "version",
        "repository",
        "output",
        "file_rule",
        "path_override",
        "documentation",
        "entrypoint",
        "context_set",
        "ratchet",
        "exceptions",
    }
)


class ConfigurationError(ValueError):
    """One or more deterministic policy diagnostics."""

    def __init__(self, diagnostics: tuple[Diagnostic, ...]) -> None:
        if not diagnostics:
            raise ValueError("ConfigurationError requires at least one diagnostic")
        self.diagnostics = diagnostics
        first = diagnostics[0]
        suffix = "" if len(diagnostics) == 1 else f" ({len(diagnostics)} errors)"
        super().__init__(f"{first.code} {first.field_path}: {first.message}{suffix}")


def parse_policy(
    data: bytes,
    *,
    source_path: str = "repo-context.toml",
) -> Policy:
    try:
        text = data.decode("utf-8")
    except UnicodeDecodeError as error:
        diagnostic = config_diagnostic(
            CFG_PARSE,
            source_path,
            "$",
            "configuration must be valid UTF-8",
            details=(("byte_offset", error.start),),
        )
        raise ConfigurationError((diagnostic,)) from error
    try:
        raw = tomllib.loads(text)
    except tomllib.TOMLDecodeError as error:
        diagnostic = config_diagnostic(
            CFG_PARSE,
            source_path,
            "$",
            f"invalid TOML: {error}",
            line=getattr(error, "lineno", None),
            column=getattr(error, "colno", None),
        )
        raise ConfigurationError((diagnostic,)) from error
    return _PolicyParser(raw, source_path).parse()


def load_policy(path: Path) -> Policy:
    return parse_policy(path.read_bytes(), source_path=path.as_posix())


def render_starter_policy() -> bytes:
    return DEFAULT_POLICY_TOML


def starter_policy() -> Policy:
    return parse_policy(DEFAULT_POLICY_TOML, source_path="<starter-policy>")


class _PolicyParser:
    def __init__(self, raw: dict[str, Any], source_path: str) -> None:
        self.raw = raw
        self.validator = Validator(source_path)

    def parse(self) -> Policy:
        self.validator.keys(
            self.raw,
            parent="$",
            allowed=_TOP_LEVEL_KEYS,
            required=frozenset(),
        )
        version = self.validator.integer(
            self.raw,
            "version",
            parent="$",
            required=True,
        )
        if version is not None and version != 1:
            self.validator.add(
                CFG_VALUE,
                "version",
                f"unsupported policy version {version}",
                details=(("supported", 1), ("value", version)),
            )

        repository = self._parse_repository()
        output = self._parse_output()
        file_rules = parse_file_rules(self.raw, self.validator)
        path_overrides = parse_path_overrides(self.raw, self.validator)
        documentation = self._parse_documentation()
        entrypoints = parse_entrypoints(self.raw, self.validator)
        context_sets = parse_context_sets(self.raw, self.validator)
        ratchet = self._parse_ratchet()
        exceptions = self._parse_exceptions()

        if self.validator.diagnostics:
            diagnostics = tuple(
                sorted(self.validator.diagnostics, key=config_diagnostic_sort_key)
            )
            raise ConfigurationError(diagnostics)
        if any(
            item is None
            for item in (version, repository, output, documentation, ratchet, exceptions)
        ):
            raise AssertionError("configuration validation lost a required diagnostic")
        return Policy(
            version=version,
            repository=repository,
            output=output,
            file_rules=file_rules,
            path_overrides=path_overrides,
            documentation=documentation,
            entrypoints=entrypoints,
            context_sets=context_sets,
            ratchet=ratchet,
            exceptions=exceptions,
        )

    def _parse_repository(self) -> RepositorySettings | None:
        table = self.validator.table(self.raw, "repository")
        if table is None:
            return None
        parent = "repository"
        self.validator.keys(
            table,
            parent=parent,
            allowed=frozenset({"inventory", "encoding", "follow_symlinks"}),
            required=frozenset({"inventory", "encoding", "follow_symlinks"}),
        )
        inventory = parse_enum(
            self.validator,
            table,
            "inventory",
            parent,
            InventoryMode,
            required=False,
        )
        encoding = parse_enum(
            self.validator,
            table,
            "encoding",
            parent,
            TextEncoding,
            required=False,
        )
        follow_symlinks = self.validator.boolean(
            table,
            "follow_symlinks",
            parent=parent,
            required=False,
        )
        if follow_symlinks is True:
            self.validator.add(
                CFG_INCONSISTENT,
                "repository.follow_symlinks",
                "version 1 never follows repository symlinks globally",
            )
        if inventory is None or encoding is None or follow_symlinks is None:
            return None
        return RepositorySettings(inventory, encoding, follow_symlinks)

    def _parse_output(self) -> OutputSettings | None:
        table = self.validator.table(self.raw, "output")
        if table is None:
            return None
        parent = "output"
        self.validator.keys(
            table,
            parent=parent,
            allowed=frozenset({"default_format", "stable_sort"}),
            required=frozenset({"default_format", "stable_sort"}),
        )
        default_format = parse_enum(
            self.validator,
            table,
            "default_format",
            parent,
            OutputFormat,
            required=False,
        )
        stable_sort = self.validator.boolean(
            table,
            "stable_sort",
            parent=parent,
            required=False,
        )
        if default_format is not None and default_format is not OutputFormat.TEXT:
            self.validator.add(
                CFG_VALUE,
                "output.default_format",
                "version 1 command defaults are text",
                details=(("value", default_format.value),),
            )
        if stable_sort is False:
            self.validator.add(
                CFG_INCONSISTENT,
                "output.stable_sort",
                "stable diagnostic ordering may not be disabled",
            )
        if default_format is None or stable_sort is None:
            return None
        return OutputSettings(default_format, stable_sort)

    def _parse_documentation(self) -> DocumentationSettings | None:
        table = self.validator.table(self.raw, "documentation")
        if table is None:
            return None
        parent = "documentation"
        boolean_keys = (
            "require_directory_indexes",
            "require_sibling_links",
            "require_child_index_links",
            "require_root_reachability",
            "check_local_targets",
            "check_fragments",
            "allow_authored_symlinks",
        )
        self.validator.keys(
            table,
            parent=parent,
            allowed=frozenset({"roots", "exclude", *boolean_keys}),
            required=frozenset({"roots", "exclude", *boolean_keys}),
        )
        roots = parse_path_list(
            self.validator,
            table,
            "roots",
            parent=parent,
            required=False,
            nonempty=True,
        )
        exclude = parse_pattern_list(
            self.validator,
            table,
            "exclude",
            parent=parent,
            required=False,
            nonempty=False,
        )
        flags = {
            key: self.validator.boolean(table, key, parent=parent, required=False)
            for key in boolean_keys
        }
        if roots is not None:
            for index, root in enumerate(roots):
                if root != "index.md" and not root.endswith("/index.md"):
                    self.validator.add(
                        CFG_VALUE,
                        f"documentation.roots[{index}]",
                        "documentation roots must be index.md files",
                    )
                if exclude is not None and (root in exclude or "**" in exclude):
                    self.validator.add(
                        CFG_INCONSISTENT,
                        f"documentation.roots[{index}]",
                        "a documentation root may not be explicitly excluded",
                    )
        if flags["require_sibling_links"] is True and flags["require_directory_indexes"] is False:
            self.validator.add(
                CFG_INCONSISTENT,
                "documentation.require_sibling_links",
                "sibling link requirements need directory indexes",
            )
        if flags["require_child_index_links"] is True and flags["require_directory_indexes"] is False:
            self.validator.add(
                CFG_INCONSISTENT,
                "documentation.require_child_index_links",
                "child-index link requirements need directory indexes",
            )
        if flags["check_fragments"] is True and flags["check_local_targets"] is False:
            self.validator.add(
                CFG_INCONSISTENT,
                "documentation.check_fragments",
                "fragment checks require local target checks",
            )
        if roots is None or exclude is None or any(value is None for value in flags.values()):
            return None
        return DocumentationSettings(roots=roots, exclude=exclude, **flags)

    def _parse_ratchet(self) -> RatchetSettings | None:
        table = self.validator.table(self.raw, "ratchet")
        if table is None:
            return None
        parent = "ratchet"
        keys = (
            "compare_file_sizes",
            "forbid_new_oversize",
            "forbid_limit_increases",
            "forbid_exclusion_expansion",
            "forbid_removed_documentation_roots",
            "forbid_removed_entrypoint_targets",
        )
        self.validator.keys(
            table,
            parent=parent,
            allowed=frozenset(keys),
            required=frozenset(keys),
        )
        values = {
            key: self.validator.boolean(table, key, parent=parent, required=False)
            for key in keys
        }
        if values["forbid_new_oversize"] is True and values["compare_file_sizes"] is False:
            self.validator.add(
                CFG_INCONSISTENT,
                "ratchet.forbid_new_oversize",
                "forbid_new_oversize requires compare_file_sizes",
            )
        if any(value is None for value in values.values()):
            return None
        return RatchetSettings(**values)

    def _parse_exceptions(self) -> ExceptionSettings | None:
        table = self.validator.table(self.raw, "exceptions")
        if table is None:
            return None
        parent = "exceptions"
        keys = (
            "require_reason",
            "require_owner",
            "require_tracking_reference",
            "allow_expired",
        )
        self.validator.keys(
            table,
            parent=parent,
            allowed=frozenset({*keys, "record"}),
            required=frozenset(keys),
        )
        values = {
            key: self.validator.boolean(table, key, parent=parent, required=False)
            for key in keys
        }
        for key in keys[:3]:
            if values[key] is False:
                self.validator.add(
                    CFG_INCONSISTENT,
                    f"exceptions.{key}",
                    "version 1 exception governance fields are mandatory",
                )
        if values["allow_expired"] is True:
            self.validator.add(
                CFG_INCONSISTENT,
                "exceptions.allow_expired",
                "expired intentional exceptions may not be allowed",
            )
        records = parse_exception_records(table, self.validator)
        if any(value is None for value in values.values()):
            return None
        return ExceptionSettings(records=records, **values)
