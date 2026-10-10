"""Explicit work accounting for repository glob evaluation."""

from dataclasses import dataclass, field

from raften import resource_limits as limits


@dataclass(slots=True)
class MatchBudget:
    limit: int = field(default_factory=lambda: limits.MAX_MATCH_WORK)
    work: int = 0

    def charge(self, count: int) -> None:
        self.work += count
        limits.require_resource("matcher_work", self.work, self.limit,
                                operation="match-pattern")
