"""Host safety ceilings independent of repository-controlled policy."""

from raften.diagnostics import GIT_RESOURCE_LIMIT
from raften.repository_errors import fail_repository


MAX_GIT_OUTPUT_BYTES = 64 * 1024 * 1024
MAX_GIT_STDERR_BYTES = 64 * 1024
MAX_GIT_RECORDS = 250_000
MAX_GIT_PATH_BYTES = 8192
MAX_CONTENT_BYTES = 16 * 1024 * 1024
MAX_COMMAND_CONTENT_BYTES = 512 * 1024 * 1024
MAX_COMMAND_GIT_PROCESSES = 1024
MAX_MANIFEST_BYTES = 8 * 1024 * 1024
MAX_MANIFEST_TOKENS = 262_144
MAX_MANIFEST_DEPTH = 16
MAX_MANIFEST_ENTRIES = 8192
MAX_MANIFEST_OBJECT_KEYS = 16
MAX_MANIFEST_NUMBER_CHARACTERS = 128
MAX_RETAINED_TEXT_BYTES = 16 * 1024 * 1024
MAX_REPORT_BYTES = 16 * 1024 * 1024
MAX_REPORT_ITEMS = 100_000
MAX_PATTERN_BYTES = 4096
MAX_PATTERN_TOKENS = 1024
MAX_MATCH_WORK = 1_000_000
MAX_COMMAND_MATCH_WORK = 128_000_000
MAX_SELECTOR_CHECKS = 4_000_000
MAX_CONTEXT_MEMBERSHIPS = 100_000
MAX_CONTEXT_PATTERN_REFS = 100_000
MAX_COMMAND_DIAGNOSTICS = 65_536


def require_resource(resource: str, actual: int, limit: int, *, operation: str,
                     path: str | None = None) -> None:
    if actual > limit:
        fail_repository(
            GIT_RESOURCE_LIMIT, "repository exceeds an operational safety limit",
            path=path,
            details=(("operation", operation), ("resource", resource), ("limit", limit)),
        )
