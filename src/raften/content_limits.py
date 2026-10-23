"""Explicit cumulative I/O accounting owned by one repository session."""

from dataclasses import dataclass

from raften import resource_limits as limits


@dataclass(slots=True)
class ContentBudget:
    content_bytes: int = 0
    git_processes: int = 0

    def content(self, size: int, *, operation: str, path: str) -> None:
        total = self.content_bytes + size
        limits.require_resource("command_content_bytes", total, limits.MAX_COMMAND_CONTENT_BYTES,
                                operation=operation, path=path)
        self.content_bytes = total

    def git(self, operation: str) -> None:
        total = self.git_processes + 1
        limits.require_resource("command_git_processes", total, limits.MAX_COMMAND_GIT_PROCESSES,
                                operation=operation)
        self.git_processes = total
