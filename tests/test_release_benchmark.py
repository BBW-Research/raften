from __future__ import annotations

import unittest

from release_tools.benchmark import run_benchmarks


class ReleaseBenchmarkTests(unittest.TestCase):
    def test_small_synthetic_workload_reports_correct_counts_without_timing_budgets(self) -> None:
        report = run_benchmarks((100,), include_git=False)
        workload = report["workloads"][0]

        self.assertEqual(report["schema_version"], 1)
        self.assertEqual(workload["path_count"], 100)
        self.assertEqual(workload["content_reads"], 100)
        self.assertEqual(workload["retained_document_count"], 10)
        self.assertEqual(workload["parsed_document_count"], 10)
        self.assertEqual(workload["governed_document_count"], 10)
        self.assertEqual(workload["git_inventory_seconds"], None)
        self.assertGreater(workload["bytes_read"], workload["retained_content_bytes"])
        self.assertGreater(workload["audit_json_bytes"], workload["check_json_bytes"])
        self.assertGreater(workload["peak_rss_bytes"], 0)
        self.assertEqual(report["deep_documentation"]["depth"], 1_000)
        self.assertEqual(report["deep_documentation"]["directory_count"], 1_001)
        self.assertEqual(report["deep_documentation"]["unreachable_count"], 0)

    def test_real_git_inventory_uses_missing_skip_worktree_entries(self) -> None:
        report = run_benchmarks((100,), include_git=True)
        workload = report["workloads"][0]
        self.assertEqual(workload["git_inventory_count"], 100)
        self.assertGreaterEqual(workload["git_inventory_seconds"], 0)


if __name__ == "__main__":
    unittest.main()
