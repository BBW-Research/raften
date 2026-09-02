"""Verify and privately stage the exact hash-locked release wheelhouse."""

from __future__ import annotations

import argparse
import hashlib
import re
from dataclasses import dataclass
from pathlib import Path


_LOCK_LINE = re.compile(
    r"(?P<name>[A-Za-z0-9][A-Za-z0-9._-]*)=="
    r"(?P<version>[0-9]+(?:\.[0-9]+)*) "
    r"--hash=sha256:(?P<sha256>[0-9a-f]{64})\Z"
)


class WheelhouseError(RuntimeError):
    """The release wheelhouse does not exactly match its reviewed lock."""


@dataclass(frozen=True, slots=True)
class LockedWheel:
    name: str
    version: str
    filename: str
    sha256: str
    data: bytes


def verify_locked_wheelhouse(
    source: Path,
    requirements: Path,
) -> tuple[LockedWheel, ...]:
    """Read and verify every locked universal wheel exactly once."""

    locks = _parse_requirements(requirements)
    if not source.is_dir() or source.is_symlink():
        raise WheelhouseError(f"wheelhouse is not a regular directory: {source}")
    actual = tuple(sorted(source.iterdir(), key=lambda item: item.name))
    expected_names = tuple(sorted(item.filename for item in locks))
    actual_names = tuple(item.name for item in actual)
    if actual_names != expected_names:
        raise WheelhouseError(
            "wheelhouse files do not exactly match the release lock: "
            f"expected={expected_names!r}, actual={actual_names!r}"
        )

    by_filename = {item.filename: item for item in locks}
    verified: list[LockedWheel] = []
    for path in actual:
        if not path.is_file() or path.is_symlink():
            raise WheelhouseError(f"wheelhouse member is not a regular file: {path.name}")
        locked = by_filename[path.name]
        data = path.read_bytes()
        actual_hash = hashlib.sha256(data).hexdigest()
        if actual_hash != locked.sha256:
            raise WheelhouseError(
                f"wheelhouse hash mismatch for {path.name}: "
                f"expected={locked.sha256}, actual={actual_hash}"
            )
        verified.append(
            LockedWheel(
                name=locked.name,
                version=locked.version,
                filename=locked.filename,
                sha256=locked.sha256,
                data=data,
            )
        )
    return tuple(verified)


def stage_locked_wheelhouse(
    source: Path,
    requirements: Path,
    destination: Path,
) -> tuple[LockedWheel, ...]:
    """Copy verified bytes into a newly owned directory for isolated installers."""

    verified = verify_locked_wheelhouse(source, requirements)
    if destination.exists() or destination.is_symlink():
        raise WheelhouseError(f"staged wheelhouse destination already exists: {destination}")
    destination.mkdir(mode=0o700)
    for item in verified:
        with (destination / item.filename).open("xb") as stream:
            stream.write(item.data)
    return verified


def _parse_requirements(path: Path) -> tuple[LockedWheel, ...]:
    if not path.is_file() or path.is_symlink():
        raise WheelhouseError(f"release lock is not a regular file: {path}")
    try:
        lines = path.read_text(encoding="ascii").splitlines()
    except (OSError, UnicodeError) as error:
        raise WheelhouseError(f"cannot read release lock: {error}") from error

    records: list[LockedWheel] = []
    seen_names: set[str] = set()
    seen_hashes: set[str] = set()
    for line_number, line in enumerate(lines, 1):
        if not line or line.startswith("#"):
            continue
        match = _LOCK_LINE.fullmatch(line)
        if match is None:
            raise WheelhouseError(f"unsupported release lock line {line_number}")
        name = _canonical_name(match["name"])
        version = match["version"]
        sha256 = match["sha256"]
        if name in seen_names or sha256 in seen_hashes:
            raise WheelhouseError(f"duplicate release lock identity on line {line_number}")
        seen_names.add(name)
        seen_hashes.add(sha256)
        filename = f"{name.replace('-', '_')}-{version}-py3-none-any.whl"
        records.append(LockedWheel(name, version, filename, sha256, b""))
    if not records:
        raise WheelhouseError("release lock contains no wheel records")
    return tuple(sorted(records, key=lambda item: item.filename))


def _canonical_name(name: str) -> str:
    return re.sub(r"[-_.]+", "-", name).lower()


def main(arguments: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source", type=Path, required=True)
    parser.add_argument("--requirements", type=Path, required=True)
    parser.add_argument("--destination", type=Path, required=True)
    options = parser.parse_args(arguments)
    try:
        stage_locked_wheelhouse(
            options.source,
            options.requirements,
            options.destination,
        )
    except WheelhouseError as error:
        parser.exit(1, f"error: {error}\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
