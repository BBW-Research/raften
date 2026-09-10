"""Measure the supported synthetic inventory and documentation workloads."""

from __future__ import annotations

import argparse
import json
import os
import resource
import shutil
import subprocess
import sys
import tempfile
import time
from dataclasses import replace
from datetime import date
from pathlib import Path

from raften.config import starter_policy
from raften.docs import (
    compile_documentation_policy,
    documentation_text_paths,
    evaluate_documentation,
)
from raften.inventory import inventory_worktree, open_repository
from raften.markdown import parse_markdown
from raften.model import (
    DocumentationSettings,
    FileRatchetEvaluation,
    InventoryEntry,
    InventorySource,
    RatchetBaselineSource,
    TextDocument,
    WorktreeKind,
)
from raften.report_json import render_json
from raften.run_model import RepositoryRun, RunStatus
from raften.size_policy import compile_size_policy
from raften.sizes import evaluate_sizes


EVALUATION_DATE = date(2026, 9, 2)


def run_benchmarks(counts: tuple[int, ...], *, include_git: bool = True) -> dict[str, object]:
    if not counts or any(count < 100 for count in counts):
        raise ValueError("benchmark counts must each be at least 100")
    return {
        "schema_version": 1,
        "evaluation_date": EVALUATION_DATE.isoformat(),
        "workloads": [
            _benchmark_count(count, include_git=include_git)
            for count in counts
        ],
        "deep_documentation": _benchmark_deep_documentation(1_000),
    }


def _benchmark_count(count: int, *, include_git: bool) -> dict[str, object]:
    started = time.perf_counter()
    entries, document_payloads = _synthetic_entries(count)
    inventory_construction_seconds = time.perf_counter() - started

    policy = _benchmark_policy()
    compiled_documentation = compile_documentation_policy(policy)
    started = time.perf_counter()
    retained_paths = documentation_text_paths(compiled_documentation, entries)
    selection_seconds = time.perf_counter() - started

    counters = {"reads": 0, "bytes": 0}

    def read_content(entry: InventoryEntry) -> bytes:
        payload = document_payloads.get(entry.path, _source_payload(entry.path))
        counters["reads"] += 1
        counters["bytes"] += len(payload)
        return payload

    started = time.perf_counter()
    sizes = evaluate_sizes(
        compile_size_policy(policy),
        entries,
        read_content,
        evaluation_date=EVALUATION_DATE,
        retain_text_paths=retained_paths,
    )
    content_seconds = time.perf_counter() - started

    started = time.perf_counter()
    parsed = tuple(parse_markdown(item.path, item.text) for item in sizes.documents)
    markdown_parse_seconds = time.perf_counter() - started

    started = time.perf_counter()
    documentation = evaluate_documentation(
        compiled_documentation,
        entries,
        sizes.documents,
        file_assessments=sizes.files,
    )
    documentation_seconds = time.perf_counter() - started

    run = RepositoryRun(
        status=RunStatus.COMPLETE,
        repository_root=Path("/synthetic"),
        config_path="raften.toml",
        policy=policy,
        inventory=entries,
        sizes=sizes,
        documentation=documentation,
        ratchet=FileRatchetEvaluation(RatchetBaselineSource.DISABLED, (), ()),
        diagnostics=tuple((*sizes.diagnostics, *documentation.diagnostics)),
        base_commit_id=None,
        evaluation_date=EVALUATION_DATE,
    )
    started = time.perf_counter()
    check_json_bytes = len(render_json("check", run).encode("utf-8"))
    check_render_seconds = time.perf_counter() - started
    started = time.perf_counter()
    audit_json_bytes = len(render_json("audit", run).encode("utf-8"))
    audit_render_seconds = time.perf_counter() - started
    peak_rss = resource.getrusage(resource.RUSAGE_SELF).ru_maxrss
    peak_rss_bytes = peak_rss if sys.platform == "darwin" else peak_rss * 1_024

    git_inventory_seconds = None
    git_inventory_count = None
    if include_git:
        git_inventory_seconds, git_inventory_count = _measure_git_inventory(count)

    selected_inventory_seconds = (
        inventory_construction_seconds
        if git_inventory_seconds is None
        else git_inventory_seconds
    )
    pipeline_seconds = (
        selected_inventory_seconds
        + selection_seconds
        + content_seconds
        + documentation_seconds
    )
    total_check_seconds = pipeline_seconds + check_render_seconds

    retained_content_bytes = sum(item.size_bytes for item in sizes.documents)
    return {
        "path_count": count,
        "git_inventory_seconds": git_inventory_seconds,
        "git_inventory_count": git_inventory_count,
        "inventory_construction_seconds": inventory_construction_seconds,
        "documentation_selection_seconds": selection_seconds,
        "content_evaluation_seconds": content_seconds,
        "markdown_parse_seconds": markdown_parse_seconds,
        "documentation_graph_seconds": documentation_seconds,
        "check_render_seconds": check_render_seconds,
        "audit_render_seconds": audit_render_seconds,
        "total_check_seconds": total_check_seconds,
        "total_audit_seconds": pipeline_seconds + audit_render_seconds,
        "content_reads": counters["reads"],
        "bytes_read": counters["bytes"],
        "retained_document_count": len(sizes.documents),
        "retained_content_bytes": retained_content_bytes,
        "parsed_document_count": len(parsed),
        "governed_document_count": len(documentation.governed_paths),
        "documentation_edge_count": len(documentation.edges),
        "check_json_bytes": check_json_bytes,
        "audit_json_bytes": audit_json_bytes,
        "peak_rss_bytes": peak_rss_bytes,
    }


def _synthetic_entries(count: int) -> tuple[tuple[InventoryEntry, ...], dict[str, bytes]]:
    document_count = min(100, max(10, count // 1_000))
    document_paths = ["docs/index.md"] + [
        f"docs/topic-{index:03d}/note.md"
        for index in range(1, document_count)
    ]
    document_payloads = {
        "docs/index.md": (
            "# Synthetic documentation\n\n"
            + "".join(
                f"- [Topic {index}]({path.removeprefix('docs/')})\n"
                for index, path in enumerate(document_paths[1:], 1)
            )
        ).encode("utf-8")
    }
    for index, path in enumerate(document_paths[1:], 1):
        document_payloads[path] = (
            f"# Topic {index}\n\n[Documentation root](../index.md)\n"
        ).encode("utf-8")

    paths = document_paths + [
        f"src/package-{index % 100:03d}/module-{index:06d}.py"
        for index in range(count - len(document_paths))
    ]
    entries = tuple(
        InventoryEntry(
            path=path,
            source=InventorySource.TRACKED,
            kind=WorktreeKind.REGULAR,
            size_bytes=len(document_payloads.get(path, _source_payload(path))),
        )
        for path in paths
    )
    return entries, document_payloads


def _source_payload(path: str) -> bytes:
    target_size = 64 + len(path.encode("utf-8")) % 192
    return (f"# {path}\n".encode("utf-8") + b"x" * target_size)[:target_size]


def _benchmark_policy():
    policy = starter_policy()
    return replace(
        policy,
        path_overrides=(),
        entrypoints=(),
        context_sets=(),
        documentation=DocumentationSettings(
            roots=("docs/index.md",),
            exclude=(),
            require_directory_indexes=False,
            require_sibling_links=False,
            require_child_index_links=False,
            require_root_reachability=True,
            check_local_targets=True,
            check_fragments=True,
            allow_authored_symlinks=False,
        ),
        ratchet=replace(policy.ratchet, compare_file_sizes=False),
    )


def _measure_git_inventory(count: int) -> tuple[float, int]:
    git = shutil.which("git")
    if git is None:
        raise RuntimeError("Git is required for the inventory benchmark")
    git = str(Path(git).resolve(strict=True))
    with tempfile.TemporaryDirectory(prefix="raften-git-benchmark-") as directory:
        root = Path(directory)
        environment = _git_environment()
        _run_git(git, root, environment, "init", "--quiet")
        object_id = _run_git(
            git,
            root,
            environment,
            "hash-object",
            "-w",
            "--stdin",
            input_bytes=b"synthetic\n",
        ).decode("ascii").strip()
        paths = tuple(f"inventory/file-{index:06d}.txt" for index in range(count))
        index_records = b"".join(
            f"100644 {object_id}\t{path}\n".encode("utf-8")
            for path in paths
        )
        _run_git(
            git,
            root,
            environment,
            "update-index",
            "--index-info",
            input_bytes=index_records,
        )
        _run_git(
            git,
            root,
            environment,
            "update-index",
            "--skip-worktree",
            "--stdin",
            input_bytes="".join(f"{path}\n" for path in paths).encode("utf-8"),
        )
        repository = open_repository(root)
        started = time.perf_counter()
        snapshot = inventory_worktree(repository)
        elapsed = time.perf_counter() - started
        return elapsed, len(snapshot.entries)


def _run_git(
    git: str,
    root: Path,
    environment: dict[str, str],
    *arguments: str,
    input_bytes: bytes | None = None,
) -> bytes:
    result = subprocess.run(
        [git, "-C", str(root), *arguments],
        check=False,
        stdin=None if input_bytes is not None else subprocess.DEVNULL,
        input=input_bytes,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        env=environment,
        timeout=120,
    )
    if result.returncode != 0:
        raise RuntimeError(
            f"benchmark Git {arguments!r} failed: {result.stderr.decode(errors='replace')}"
        )
    return result.stdout


def _git_environment() -> dict[str, str]:
    environment = dict(os.environ)
    for name in tuple(environment):
        if name.startswith("GIT_"):
            environment.pop(name, None)
    environment.update(
        {
            "GIT_CONFIG_GLOBAL": os.devnull,
            "GIT_CONFIG_NOSYSTEM": "1",
            "GIT_OPTIONAL_LOCKS": "0",
            "LC_ALL": "C",
        }
    )
    return environment


def _benchmark_deep_documentation(depth: int) -> dict[str, object]:
    nested = "docs/" + "/".join(f"level-{index:04d}" for index in range(depth))
    topic = f"{nested}/topic.md"
    root_text = f"# Root\n\n[Deep topic](../{topic})\n"
    topic_text = "# Topic\n"
    entries = (
        InventoryEntry("docs/index.md", InventorySource.TRACKED, WorktreeKind.REGULAR, len(root_text)),
        InventoryEntry(topic, InventorySource.TRACKED, WorktreeKind.REGULAR, len(topic_text)),
    )
    documents = (
        _text_document("docs/index.md", root_text),
        _text_document(topic, topic_text),
    )
    policy = _benchmark_policy()
    started = time.perf_counter()
    result = evaluate_documentation(
        compile_documentation_policy(policy),
        entries,
        documents,
    )
    elapsed = time.perf_counter() - started
    return {
        "depth": depth,
        "seconds": elapsed,
        "directory_count": len(result.directories),
        "unreachable_count": len(result.unreachable_paths),
    }


def _text_document(path: str, text: str) -> TextDocument:
    return TextDocument(path, text, len(text.encode("utf-8")))


def main(arguments: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--count", type=int, action="append", dest="counts")
    parser.add_argument("--skip-git-inventory", action="store_true")
    options = parser.parse_args(arguments)
    counts = tuple(options.counts or (10_000, 100_000))
    result = run_benchmarks(counts, include_git=not options.skip_git_inventory)
    print(json.dumps(result, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
