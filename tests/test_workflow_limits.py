"""Repository-owned duration bounds and fail-closed required checks."""

from pathlib import Path
import os
import re
import subprocess
import unittest


WORKFLOW = Path(__file__).resolve().parents[1] / ".github/workflows/repository-policy.yml"


class WorkflowLimitTests(unittest.TestCase):
    def test_every_job_has_a_bounded_timeout(self) -> None:
        text = WORKFLOW.read_text(encoding="utf-8").split("jobs:\n", 1)[1]
        jobs = re.split(r"(?m)^  ([a-z_]+):\n", text)
        self.assertEqual(jobs[1::2], ["qualification", "links", "required"])
        for name, body in zip(jobs[1::2], jobs[2::2]):
            with self.subTest(job=name):
                timeout = re.findall(r"(?m)^    timeout-minutes: ([0-9]+)$", body)
                self.assertEqual(len(timeout), 1)
                self.assertTrue(0 < int(timeout[0]) <= 30)

    def test_required_check_rejects_failed_or_cancelled_prerequisites(self) -> None:
        text = WORKFLOW.read_text(encoding="utf-8")
        required = text.split("  required:\n", 1)[1]
        self.assertIn("if: always()", required)
        script = required.split("        run: |\n", 1)[1]
        for link in ("success", "failure", "cancelled", "skipped"):
            for qualification in ("success", "failure", "cancelled", "skipped"):
                result = subprocess.run(
                    ["sh", "-eu", "-c", script],
                    env={**os.environ, "LINK_RESULT": link,
                         "QUALIFICATION_RESULT": qualification},
                    check=False, timeout=5,
                )
                self.assertEqual(result.returncode == 0,
                                 link == qualification == "success")
