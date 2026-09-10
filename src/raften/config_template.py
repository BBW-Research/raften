"""Package-owned deterministic starter policy template."""

from __future__ import annotations

import json


_DEBT_PATH_MARKER = b"__RAFTEN_DEBT_PATH__"
_POLICY_TEMPLATE = b'''version = 1

[repository]
inventory = "git-visible"
encoding = "utf-8"
follow_symlinks = false

[output]
default_format = "text"
stable_sort = true

# Rules are evaluated in declaration order. The first matching rule wins.
[[file_rule]]
name = "generated-state"
patterns = ["uv.lock", "**/uv.lock", "package-lock.json", "**/package-lock.json", __RAFTEN_DEBT_PATH__]
kind = "generated"
scan = false
reason = "Machine-generated dependency and migration state is validated by its owning tool."

[[file_rule]]
name = "authored"
patterns = ["**"]
kind = "authored"
scan = true
warn_bytes = 20480
hard_bytes = 25600

[[path_override]]
path = "AGENTS.md"
warn_bytes = 8192
hard_bytes = 12288

[[path_override]]
path = "README.md"
warn_bytes = 12288
hard_bytes = 16384

[[path_override]]
path = "ARCHITECTURE.md"
warn_bytes = 6144
hard_bytes = 8192

[[path_override]]
pattern = "docs/**/index.md"
warn_bytes = 8192
hard_bytes = 12288

[documentation]
roots = ["docs/index.md"]
exclude = []
require_directory_indexes = true
require_sibling_links = true
require_child_index_links = true
require_root_reachability = true
check_local_targets = true
check_fragments = true
allow_authored_symlinks = false

[[entrypoint]]
path = "AGENTS.md"
required_targets = ["docs/index.md"]

[[entrypoint]]
path = "README.md"
required_targets = ["docs/index.md"]

[[entrypoint]]
path = "ARCHITECTURE.md"
required_targets = ["docs/architecture/index.md"]

[[context_set]]
name = "bootstrap"
paths = ["AGENTS.md", "ARCHITECTURE.md", "docs/index.md"]
warn_bytes = 24576
hard_bytes = 32768

[ratchet]
compare_file_sizes = true
forbid_new_oversize = true
forbid_limit_increases = true
forbid_exclusion_expansion = true
forbid_removed_documentation_roots = true
forbid_removed_entrypoint_targets = true

[exceptions]
require_reason = true
require_owner = true
require_tracking_reference = true
allow_expired = false
'''


def render_policy_template(debt_manifest_path: str) -> bytes:
    encoded_path = json.dumps(debt_manifest_path, ensure_ascii=False).encode("utf-8")
    return _POLICY_TEMPLATE.replace(_DEBT_PATH_MARKER, encoded_path)


DEFAULT_POLICY_TOML = render_policy_template("raften.debt.json")
