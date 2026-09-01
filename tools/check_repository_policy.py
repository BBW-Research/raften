#!/usr/bin/env python3
"""Enforce bounded plaintext files and a navigable documentation graph."""

from __future__ import annotations

import argparse
import fnmatch
import json
import posixpath
import re
import stat
import subprocess
import sys
from pathlib import Path, PurePosixPath
from typing import Any
from urllib.parse import unquote


LINK_RE = re.compile(r"(?<!!)\[[^\]]+\]\((<[^>]+>|[^)\s]+)(?:\s+[^)]*)?\)")
REQUIRED_KEYS = {
    "policy_version",
    "max_text_bytes",
    "index_max_bytes",
    "entrypoint_limits",
    "documentation_roots",
    "documentation_excluded_globs",
    "text_excluded_globs",
    "required_entrypoint_links",
    "legacy_oversize",
}
STRUCTURED_DATA_SIZE_EXEMPTIONS = frozenset(
    {"config/*.json", "schemas/*.json"}
)


class PolicyError(ValueError):
    pass


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--config",
        default="config/repository_policy.v1.json",
        help="repository-relative policy JSON",
    )
    parser.add_argument(
        "--base-ref",
        help="optional Git revision whose policy limits may not be weakened",
    )
    return parser.parse_args()


def canonical_rel(value: str) -> str:
    path = PurePosixPath(value)
    if path.is_absolute() or value != path.as_posix() or ".." in path.parts:
        raise PolicyError(f"unsafe or non-canonical repository path: {value!r}")
    return value


def load_policy_bytes(data: bytes, source: str) -> dict[str, Any]:
    try:
        policy = json.loads(data)
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise PolicyError(f"invalid policy JSON at {source}: {exc}") from exc
    if not isinstance(policy, dict):
        raise PolicyError(f"policy at {source} must be an object")
    unknown = set(policy) - REQUIRED_KEYS
    missing = REQUIRED_KEYS - set(policy)
    if unknown or missing:
        raise PolicyError(
            f"policy keys at {source} differ: missing={sorted(missing)}, unknown={sorted(unknown)}"
        )
    if policy["policy_version"] != 1:
        raise PolicyError(f"unsupported policy_version at {source}")
    for key in ("max_text_bytes", "index_max_bytes"):
        if not isinstance(policy[key], int) or policy[key] <= 0:
            raise PolicyError(f"{key} at {source} must be a positive integer")
    for key in ("entrypoint_limits", "legacy_oversize"):
        if not isinstance(policy[key], dict):
            raise PolicyError(f"{key} at {source} must be an object")
        for raw_path, limit in policy[key].items():
            canonical_rel(raw_path)
            if not isinstance(limit, int) or limit <= 0:
                raise PolicyError(f"invalid byte limit for {raw_path!r} at {source}")
    for key in (
        "documentation_roots",
        "documentation_excluded_globs",
        "text_excluded_globs",
    ):
        if not isinstance(policy[key], list) or not all(
            isinstance(item, str) and item for item in policy[key]
        ):
            raise PolicyError(f"{key} at {source} must be a non-empty string list")
    for root in policy["documentation_roots"]:
        canonical_rel(root)
    required_links = policy["required_entrypoint_links"]
    if not isinstance(required_links, dict):
        raise PolicyError(f"required_entrypoint_links at {source} must be an object")
    for raw_path, targets in required_links.items():
        canonical_rel(raw_path)
        if not isinstance(targets, list) or not all(isinstance(item, str) for item in targets):
            raise PolicyError(f"invalid required links for {raw_path!r} at {source}")
        for target in targets:
            canonical_rel(target)
    return policy


def load_policy(path: Path) -> dict[str, Any]:
    return load_policy_bytes(path.read_bytes(), path.as_posix())


def git_paths(root: Path) -> list[str]:
    result = subprocess.run(
        ["git", "ls-files", "--cached", "--others", "--exclude-standard", "-z"],
        cwd=root,
        check=True,
        stdout=subprocess.PIPE,
    )
    return sorted(item.decode("utf-8") for item in result.stdout.split(b"\0") if item)


def matches_any(path: str, patterns: list[str]) -> bool:
    return any(fnmatch.fnmatchcase(path, pattern) for pattern in patterns)


def is_utf8_text(data: bytes) -> bool:
    if b"\0" in data:
        return False
    try:
        data.decode("utf-8")
    except UnicodeDecodeError:
        return False
    return True


def markdown_targets(source: str, text: str, root: Path) -> set[str]:
    targets: set[str] = set()
    for match in LINK_RE.finditer(text):
        raw = match.group(1)
        if raw.startswith("<") and raw.endswith(">"):
            raw = raw[1:-1]
        raw = unquote(raw.split("#", 1)[0].split("?", 1)[0])
        if not raw or raw.startswith("/") or "://" in raw or raw.startswith("mailto:"):
            continue
        resolved = posixpath.normpath(posixpath.join(posixpath.dirname(source), raw))
        if resolved == ".." or resolved.startswith("../"):
            continue
        candidate = root / resolved
        if candidate.is_dir():
            resolved = posixpath.join(resolved, "index.md")
        targets.add(resolved)
    return targets


def effective_limit(path: str, policy: dict[str, Any]) -> int:
    limit = policy["max_text_bytes"]
    if path in policy["entrypoint_limits"]:
        limit = min(limit, policy["entrypoint_limits"][path])
    if path.endswith("/index.md") or path == "index.md":
        if any(path == root or path.startswith(f"{root}/") for root in policy["documentation_roots"]):
            limit = min(limit, policy["index_max_bytes"])
    return limit


def check_sizes(root: Path, paths: list[str], policy: dict[str, Any]) -> tuple[list[str], int]:
    errors: list[str] = []
    text_count = 0
    seen: set[str] = set()
    for path in paths:
        absolute = root / path
        try:
            mode = absolute.lstat().st_mode
        except FileNotFoundError:
            continue
        if not stat.S_ISREG(mode) or matches_any(path, policy["text_excluded_globs"]):
            continue
        data = absolute.read_bytes()
        if not is_utf8_text(data):
            continue
        text_count += 1
        seen.add(path)
        size = len(data)
        limit = effective_limit(path, policy)
        legacy_limit = policy["legacy_oversize"].get(path)
        if size > limit and legacy_limit is None:
            errors.append(f"{path}: {size} bytes exceeds {limit}; split the file")
        elif legacy_limit is not None and size > legacy_limit:
            errors.append(f"{path}: {size} bytes exceeds legacy ceiling {legacy_limit}")
        elif legacy_limit is not None and size <= limit:
            errors.append(f"{path}: now within {limit} bytes; remove its legacy ceiling")

    for path, legacy_limit in policy["legacy_oversize"].items():
        if legacy_limit <= effective_limit(path, policy):
            errors.append(f"{path}: legacy ceiling must exceed its ordinary limit")
        if path not in seen:
            errors.append(f"{path}: legacy ceiling points to a missing, excluded, or non-text file")
    return errors, text_count


def check_docs(root: Path, paths: list[str], policy: dict[str, Any]) -> tuple[list[str], int]:
    errors: list[str] = []
    docs: set[str] = set()
    for path in paths:
        if not path.endswith(".md"):
            continue
        if not any(path == doc_root or path.startswith(f"{doc_root}/") for doc_root in policy["documentation_roots"]):
            continue
        if matches_any(path, policy["documentation_excluded_globs"]):
            continue
        absolute = root / path
        if absolute.is_symlink():
            errors.append(f"{path}: authored documentation may not be a symlink")
        elif absolute.is_file():
            docs.add(path)

    links_by_index: dict[str, set[str]] = {}
    directories = {posixpath.dirname(path) for path in docs}
    for directory in sorted(directories):
        index = posixpath.join(directory, "index.md")
        if index not in docs:
            errors.append(f"{directory}: missing required index.md")
            continue
        links_by_index[index] = markdown_targets(index, (root / index).read_text(), root)

    for directory in sorted(directories):
        index = posixpath.join(directory, "index.md")
        linked = links_by_index.get(index, set())
        direct_files = {
            path
            for path in docs
            if posixpath.dirname(path) == directory and posixpath.basename(path) != "index.md"
        }
        for path in sorted(direct_files - linked):
            errors.append(f"{index}: does not directly link sibling document {path}")

        prefix = f"{directory}/" if directory else ""
        child_dirs: set[str] = set()
        for other in directories:
            if not other.startswith(prefix) or other == directory:
                continue
            remainder = other[len(prefix) :]
            if "/" not in remainder:
                child_dirs.add(other)
        for child in sorted(child_dirs):
            child_index = posixpath.join(child, "index.md")
            if child_index not in linked:
                errors.append(f"{index}: does not directly link child index {child_index}")

    for entrypoint, required in policy["required_entrypoint_links"].items():
        absolute = root / entrypoint
        if not absolute.is_file():
            errors.append(f"{entrypoint}: required entrypoint is missing")
            continue
        linked = markdown_targets(entrypoint, absolute.read_text(), root)
        for target in required:
            if target not in linked:
                errors.append(f"{entrypoint}: missing required link to {target}")
    return errors, len(docs)


def policy_from_git(root: Path, ref: str, config_path: str) -> dict[str, Any] | None:
    result = subprocess.run(
        ["git", "show", f"{ref}:{config_path}"],
        cwd=root,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
    )
    if result.returncode != 0:
        return None
    return load_policy_bytes(result.stdout, f"{ref}:{config_path}")


def check_not_weakened(current: dict[str, Any], base: dict[str, Any]) -> list[str]:
    errors: list[str] = []
    if current["max_text_bytes"] > base["max_text_bytes"]:
        errors.append("max_text_bytes may not increase")
    if current["index_max_bytes"] > base["index_max_bytes"]:
        errors.append("index_max_bytes may not increase")
    for path, old_limit in base["entrypoint_limits"].items():
        if path not in current["entrypoint_limits"]:
            errors.append(f"entrypoint limit may not be removed: {path}")
        elif current["entrypoint_limits"][path] > old_limit:
            errors.append(f"entrypoint limit may not increase: {path}")
    if not set(base["documentation_roots"]).issubset(current["documentation_roots"]):
        errors.append("documentation roots may not be removed")
    for key in ("documentation_excluded_globs", "text_excluded_globs"):
        additions = set(current[key]) - set(base[key])
        if key == "text_excluded_globs":
            additions -= STRUCTURED_DATA_SIZE_EXEMPTIONS
        if additions:
            errors.append(f"{key} may not expand: {sorted(additions)}")
    for entrypoint, old_targets in base["required_entrypoint_links"].items():
        new_targets = set(current["required_entrypoint_links"].get(entrypoint, []))
        if not set(old_targets).issubset(new_targets):
            errors.append(f"required entrypoint links may not be removed: {entrypoint}")
    additions = set(current["legacy_oversize"]) - set(base["legacy_oversize"])
    if additions:
        errors.append(f"new legacy oversized files are forbidden: {sorted(additions)}")
    for path, current_limit in current["legacy_oversize"].items():
        old_limit = base["legacy_oversize"].get(path)
        if old_limit is not None and current_limit > old_limit:
            errors.append(f"legacy ceiling may not increase: {path}")
    return errors


def main() -> int:
    args = parse_args()
    root = Path(__file__).resolve().parents[1]
    config_rel = canonical_rel(args.config)
    try:
        policy = load_policy(root / config_rel)
        paths = git_paths(root)
        errors, text_count = check_sizes(root, paths, policy)
        doc_errors, doc_count = check_docs(root, paths, policy)
        errors.extend(doc_errors)
        if args.base_ref and set(args.base_ref) != {"0"}:
            base = policy_from_git(root, args.base_ref, config_rel)
            if base is not None:
                errors.extend(check_not_weakened(policy, base))
    except (OSError, PolicyError, subprocess.CalledProcessError) as exc:
        print(f"repository policy error: {exc}", file=sys.stderr)
        return 2

    if errors:
        for error in errors:
            print(f"ERROR: {error}", file=sys.stderr)
        print(f"repository policy failed with {len(errors)} error(s)", file=sys.stderr)
        return 1
    print(
        f"repository policy passed: {text_count} plaintext files, "
        f"{doc_count} authored Markdown files"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
