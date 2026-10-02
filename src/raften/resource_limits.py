"""Host safety ceilings independent of repository-controlled policy."""

from raften.diagnostics import GIT_RESOURCE_LIMIT
from raften.repository_errors import fail_repository


MAX_GIT_OUTPUT_BYTES = 64 * 1024 * 1024
MAX_GIT_STDERR_BYTES = 64 * 1024
MAX_GIT_RECORDS = 250_000
MAX_GIT_PATH_BYTES = 8192


def require_resource(resource: str, actual: int, limit: int, *, operation: str,
                     path: str | None = None) -> None:
    if actual > limit:
        fail_repository(
            GIT_RESOURCE_LIMIT, "repository exceeds an operational safety limit",
            path=path,
            details=(("operation", operation), ("resource", resource), ("limit", limit)),
        )
