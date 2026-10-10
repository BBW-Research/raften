"""Command-owned budgets for selectors and retained context relations."""

from dataclasses import dataclass, field

from raften import resource_limits as limits
from raften.matcher_limits import MatchBudget


@dataclass(slots=True)
class EvaluationBudget:
    matcher: MatchBudget = field(default_factory=lambda: MatchBudget(limits.MAX_COMMAND_MATCH_WORK))
    selector_checks: int = 0
    memberships: int = 0
    pattern_refs: int = 0

    def preflight(self, count: int) -> None:
        limits.require_resource("selector_checks", self.selector_checks + count,
                                limits.MAX_SELECTOR_CHECKS, operation="evaluate-selectors")

    def selectors(self, count: int) -> None:
        self.preflight(count)
        self.selector_checks += count

    def member(self) -> None:
        limits.require_resource("context_memberships", self.memberships + 1,
                                limits.MAX_CONTEXT_MEMBERSHIPS, operation="evaluate-contexts")
        self.memberships += 1

    def references(self, count: int) -> None:
        limits.require_resource("context_pattern_refs", self.pattern_refs + count,
                                limits.MAX_CONTEXT_PATTERN_REFS, operation="evaluate-contexts")
        self.pattern_refs += count
