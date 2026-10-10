from __future__ import annotations

import unittest
from unittest import mock

from raften.model import ContextSet
from raften.repository_errors import RepositoryAccessError
from raften.sizes import compile_size_policy, evaluate_sizes
from raften.evaluation_limits import EvaluationBudget
from raften.docs import compile_documentation_policy, evaluate_documentation
from tests.support.sizes import TODAY, policy_with, regular


class SelectorResourceTests(unittest.TestCase):
    def test_maximum_context_records_reject_large_inventory_at_real_ceiling(self) -> None:
        contexts = tuple(ContextSet(f"c{i}", (), (f"data/{i}*.txt",), 100, 200) for i in range(1024))
        compiled = compile_size_policy(policy_with(context_sets=contexts))
        reader = mock.Mock(return_value=b"x")
        with self.assertRaises(RepositoryAccessError):
            evaluate_sizes(compiled, tuple(regular(f"data/{i}.txt", 1) for i in range(5000)),
                           reader, evaluation_date=TODAY)
        reader.assert_not_called()

    def test_sizes_and_documentation_share_remaining_budget(self) -> None:
        budget = EvaluationBudget()
        policy = policy_with()
        entries = (regular("docs/index.md", 1),)
        with mock.patch("raften.resource_limits.MAX_SELECTOR_CHECKS", 1):
            evaluate_sizes(compile_size_policy(policy, budget=budget), entries,
                           lambda entry: b"x", evaluation_date=TODAY)
            with self.assertRaises(RepositoryAccessError):
                evaluate_documentation(compile_documentation_policy(policy, budget=budget), entries, ())

    def test_compilation_and_inclusive_retention_bounds(self) -> None:
        contexts = (ContextSet("a", (), ("data/*.txt",), 100, 200),
                    ContextSet("b", (), ("data/*.txt",), 100, 200))
        compiled = compile_size_policy(policy_with(context_sets=contexts))
        self.assertIs(compiled.contexts[0].patterns[0], compiled.contexts[1].patterns[0])
        with mock.patch("raften.resource_limits.MAX_CONTEXT_MEMBERSHIPS", 2), \
             mock.patch("raften.resource_limits.MAX_CONTEXT_PATTERN_REFS", 3):
            result = evaluate_sizes(compiled, (regular("data/a.txt", 1),),
                                    lambda entry: b"x", evaluation_date=TODAY)
            repeated = evaluate_sizes(compiled, (regular("data/a.txt", 1),),
                                      lambda entry: b"x", evaluation_date=TODAY)
        self.assertEqual(len(result.contexts), 2)
        self.assertEqual(result, repeated)

    def test_cross_product_is_rejected_before_content_reads(self) -> None:
        contexts = tuple(ContextSet(f"c{i}", (), (f"data/{i}*.txt",), 100, 200) for i in range(10))
        compiled = compile_size_policy(policy_with(context_sets=contexts))
        entries = tuple(regular(f"data/{i}.txt", 1) for i in range(10))
        reader = mock.Mock(return_value=b"x")
        with mock.patch("raften.resource_limits.MAX_SELECTOR_CHECKS", 100, create=True):
            with self.assertRaises(RepositoryAccessError) as caught:
                evaluate_sizes(compiled, entries, reader, evaluation_date=TODAY)
        reader.assert_not_called()
        self.assertEqual(dict(caught.exception.diagnostics[0].details)["resource"], "selector_checks")

    def test_duplicate_context_patterns_share_match_results(self) -> None:
        contexts = tuple(ContextSet(f"c{i}", (), ("data/*.txt",), 100, 200) for i in range(3))
        compiled = compile_size_policy(policy_with(context_sets=contexts))
        entries = tuple(regular(f"data/{i}.txt", 1) for i in range(5))
        import raften.sizes as sizes
        with mock.patch("raften.sizes.match_path", wraps=sizes.match_path) as matches:
            outcome = evaluate_sizes(compiled, entries, lambda entry: b"x", evaluation_date=TODAY)
        self.assertEqual(matches.call_count, 5)
        self.assertEqual([len(item.members) for item in outcome.contexts], [5, 5, 5])

    def test_membership_and_pattern_reference_limits_are_independent(self) -> None:
        context = ContextSet("c", ("absent.txt",), ("data/*.txt", "**/*.txt"), 100, 200)
        for resource, limit in (("MAX_CONTEXT_MEMBERSHIPS", 2), ("MAX_CONTEXT_PATTERN_REFS", 1)):
            with self.subTest(resource=resource):
                compiled = compile_size_policy(policy_with(context_sets=(context,)))
                with mock.patch(f"raften.resource_limits.{resource}", limit, create=True):
                    with self.assertRaises(RepositoryAccessError):
                        evaluate_sizes(compiled, (regular("data/a.txt", 1), regular("data/b.txt", 1)),
                                       lambda entry: b"x", evaluation_date=TODAY)


if __name__ == "__main__":
    unittest.main()
