from __future__ import annotations

import subprocess
import tempfile
import unittest
from datetime import date
from pathlib import Path
from unittest import mock

from repo_context.config import (
    load_policy,
    parse_policy,
    render_starter_policy,
    starter_policy,
)
from repo_context.model import (
    ContextSet,
    DocumentationSettings,
    Entrypoint,
    ExactSelector,
    ExceptionSettings,
    FileKind,
    FileRule,
    InventoryMode,
    OutputFormat,
    OutputSettings,
    PathOverride,
    PatternSelector,
    RatchetSettings,
    RepositorySettings,
    TextEncoding,
)
from tests.support.config import (
    STARTER_POLICY_BYTES,
    STARTER_POLICY_TEXT,
    append_exception_record,
)
from tests.support.paths import ROOT


class ValidConfigurationTests(unittest.TestCase):
    def test_starter_policy_projects_every_section_into_typed_records(self) -> None:
        policy = parse_policy(STARTER_POLICY_BYTES)
        self.assertEqual(policy.version, 1)
        self.assertEqual(
            policy.repository,
            RepositorySettings(InventoryMode.GIT_VISIBLE, TextEncoding.UTF8, False),
        )
        self.assertEqual(
            policy.output,
            OutputSettings(OutputFormat.TEXT, True),
        )
        self.assertEqual(
            policy.file_rules,
            (
                FileRule(
                    name="generated-state",
                    patterns=(
                        "uv.lock",
                        "**/uv.lock",
                        "package-lock.json",
                        "**/package-lock.json",
                        "repo-context.debt.json",
                    ),
                    kind=FileKind.GENERATED,
                    scan=False,
                    warn_bytes=None,
                    hard_bytes=None,
                    reason="Machine-generated dependency and migration state is validated by its owning tool.",
                ),
                FileRule("authored", ("**",), FileKind.AUTHORED, True, 20480, 25600),
            ),
        )
        self.assertEqual(
            policy.path_overrides,
            (
                PathOverride(ExactSelector("AGENTS.md"), 8192, 12288),
                PathOverride(ExactSelector("README.md"), 12288, 16384),
                PathOverride(ExactSelector("ARCHITECTURE.md"), 6144, 8192),
                PathOverride(PatternSelector("docs/**/index.md"), 8192, 12288),
            ),
        )
        self.assertEqual(
            policy.documentation,
            DocumentationSettings(
                roots=("docs/index.md",),
                exclude=(),
                require_directory_indexes=True,
                require_sibling_links=True,
                require_child_index_links=True,
                require_root_reachability=True,
                check_local_targets=True,
                check_fragments=True,
                allow_authored_symlinks=False,
            ),
        )
        self.assertEqual(
            policy.entrypoints,
            (
                Entrypoint("AGENTS.md", ("docs/index.md",)),
                Entrypoint("README.md", ("docs/index.md",)),
                Entrypoint("ARCHITECTURE.md", ("docs/architecture/index.md",)),
            ),
        )
        self.assertEqual(
            policy.context_sets,
            (
                ContextSet(
                    "bootstrap",
                    ("AGENTS.md", "ARCHITECTURE.md", "docs/index.md"),
                    (),
                    24576,
                    32768,
                ),
            ),
        )
        self.assertEqual(
            policy.ratchet,
            RatchetSettings(True, True, True, True, True, True),
        )
        self.assertEqual(
            policy.exceptions,
            ExceptionSettings(True, True, True, False, ()),
        )

    def test_optional_repeatable_sections_default_to_empty_tuples(self) -> None:
        text = STARTER_POLICY_TEXT
        for start, end in (
            ("[[path_override]]\n", "[documentation]\n"),
            ("[[entrypoint]]\n", "[[context_set]]\n"),
            ("[[context_set]]\n", "[ratchet]\n"),
        ):
            first = text.index(start)
            last = text.index(end, first)
            text = text[:first] + text[last:]
        policy = parse_policy(text.encode())
        self.assertEqual(policy.path_overrides, ())
        self.assertEqual(policy.entrypoints, ())
        self.assertEqual(policy.context_sets, ())

    def test_context_patterns_and_exception_records_are_preserved_in_order(self) -> None:
        text = STARTER_POLICY_TEXT.replace(
            "[ratchet]\n",
            """[[context_set]]
name = "fixtures"
patterns = ["fixtures/**/*.golden"]
warn_bytes = 1000
hard_bytes = 2000

[ratchet]
""",
            1,
        )
        text = append_exception_record(
            text,
            """path = "generated/schema.json"
owner = "tooling"
rationale = "Temporary generated compatibility boundary"
tracking_reference = "ADR-42"
created_on = 2026-08-01
scan = false""",
        )
        text = append_exception_record(
            text,
            """pattern = "fixtures/**/*.golden"
owner = "testing"
rationale = "Reviewed large compatibility snapshots"
tracking_reference = "issue-7"
created_on = 2026-08-02
expires_on = 2026-12-31
warn_bytes = 30000
hard_bytes = 40000""",
        )
        policy = parse_policy(text.encode())
        self.assertEqual(policy.context_sets[-1].patterns, ("fixtures/**/*.golden",))
        self.assertEqual(
            [record.selector for record in policy.exceptions.records],
            [
                ExactSelector("generated/schema.json"),
                PatternSelector("fixtures/**/*.golden"),
            ],
        )
        self.assertEqual(policy.exceptions.records[1].created_on, date(2026, 8, 2))
        self.assertEqual(policy.exceptions.records[1].expires_on, date(2026, 12, 31))

    def test_disjoint_equal_specificity_pattern_overrides_are_valid(self) -> None:
        text = STARTER_POLICY_TEXT.replace(
            "[documentation]\n",
            """[[path_override]]
pattern = "source/*.txt"
warn_bytes = 100
hard_bytes = 200

[[path_override]]
pattern = "vendor/*.txt"
warn_bytes = 100
hard_bytes = 200

[documentation]
""",
            1,
        )
        policy = parse_policy(text.encode())
        self.assertEqual(len(policy.path_overrides), 6)

    def test_later_literal_components_can_prove_pattern_overrides_disjoint(self) -> None:
        text = STARTER_POLICY_TEXT.replace(
            "[documentation]\n",
            '''[[path_override]]
pattern = "docs/*/one.md"
warn_bytes = 100
hard_bytes = 200

[[path_override]]
pattern = "docs/*/two.md"
warn_bytes = 100
hard_bytes = 200

[documentation]
''',
            1,
        )
        policy = parse_policy(text.encode())
        self.assertEqual(len(policy.path_overrides), 6)

    def test_stars_inside_a_character_class_are_literal_class_members(self) -> None:
        text = STARTER_POLICY_TEXT.replace(
            'pattern = "docs/**/index.md"',
            'pattern = "docs/[**].md"',
            1,
        )
        policy = parse_policy(text.encode())
        self.assertEqual(policy.path_overrides[-1].selector, PatternSelector("docs/[**].md"))

    def test_independent_ratchet_flags_remain_parseable_when_disabled(self) -> None:
        text = STARTER_POLICY_TEXT
        for key in (
            "forbid_limit_increases",
            "forbid_exclusion_expansion",
            "forbid_removed_documentation_roots",
            "forbid_removed_entrypoint_targets",
        ):
            text = text.replace(f"{key} = true", f"{key} = false", 1)
        policy = parse_policy(text.encode())
        self.assertFalse(policy.ratchet.forbid_limit_increases)
        self.assertTrue(policy.ratchet.compare_file_sizes)

    def test_loading_policy_does_not_scan_or_invoke_git(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "repo-context.toml"
            path.write_bytes(STARTER_POLICY_BYTES)
            with (
                mock.patch.object(subprocess, "run", side_effect=AssertionError("Git invoked")),
                mock.patch.object(Path, "rglob", side_effect=AssertionError("repository scanned")),
                mock.patch.object(Path, "resolve", side_effect=AssertionError("path resolved")),
            ):
                policy = load_policy(path)
        self.assertEqual(policy, starter_policy())


class StarterTemplateTests(unittest.TestCase):
    def test_template_is_deterministic_and_normalized(self) -> None:
        first = render_starter_policy()
        second = render_starter_policy()
        self.assertIs(first, second)
        self.assertEqual(first, STARTER_POLICY_BYTES)
        self.assertTrue(first.endswith(b"\n"))
        self.assertNotIn(b"\r\n", first)

    def test_template_round_trip_matches_starter_model(self) -> None:
        self.assertEqual(parse_policy(render_starter_policy()), starter_policy())
        self.assertEqual(starter_policy(), parse_policy(STARTER_POLICY_BYTES))

    def test_template_classifies_the_exact_custom_debt_sidecar(self) -> None:
        rendered = render_starter_policy(debt_manifest_path="config/project-policy.debt.json")
        policy = parse_policy(rendered)
        debt_rule = next(rule for rule in policy.file_rules if rule.name == "generated-state")
        self.assertEqual(debt_rule.patterns[-1], "config/project-policy.debt.json")
        self.assertEqual(debt_rule.kind, FileKind.GENERATED)
        self.assertFalse(debt_rule.scan)


class AdoptedRootPolicyTests(unittest.TestCase):
    def test_root_policy_adds_project_specific_scanned_classifications(self) -> None:
        policy = load_policy(ROOT / "repo-context.toml")
        self.assertNotEqual(policy, starter_policy())
        rules = {rule.name: rule for rule in policy.file_rules}

        frozen = rules["frozen-scene-maker"]
        self.assertEqual(frozen.kind, FileKind.VENDORED)
        self.assertEqual(
            frozen.patterns,
            (
                "tools/check_repository_policy.py",
                "reference/scene-maker/repository-policy.yml",
                "reference/scene-maker/lychee.toml",
            ),
        )
        self.assertTrue(frozen.scan)
        self.assertEqual((frozen.warn_bytes, frozen.hard_bytes), (20480, 25600))

        fixtures = rules["test-fixtures"]
        self.assertEqual(fixtures.kind, FileKind.FIXTURE)
        self.assertEqual(fixtures.patterns, ("tests/fixtures/**",))
        self.assertTrue(fixtures.scan)
        self.assertEqual((fixtures.warn_bytes, fixtures.hard_bytes), (20480, 25600))

        release_lock = rules["release-lock"]
        self.assertEqual(release_lock.kind, FileKind.GENERATED)
        self.assertEqual(release_lock.patterns, ("requirements/release.txt",))
        self.assertTrue(release_lock.scan)
        self.assertEqual((release_lock.warn_bytes, release_lock.hard_bytes), (20480, 25600))

        legal = rules["legal-material"]
        self.assertEqual(legal.kind, FileKind.LEGAL)
        self.assertEqual(legal.patterns, ("LICENSE", "NOTICE"))
        self.assertTrue(legal.scan)
        self.assertEqual((legal.warn_bytes, legal.hard_bytes), (20480, 25600))


if __name__ == "__main__":
    unittest.main()
