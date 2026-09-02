"""Build the dependency-free vendorable artifact deterministically."""

from __future__ import annotations

import argparse
import os
import tempfile
import zipfile
from datetime import datetime, timezone
from pathlib import Path


_MAIN = b"from repo_context.cli import main\n\nraise SystemExit(main())\n"
_MINIMUM_ZIP_EPOCH = 315_532_800
_MAXIMUM_ZIP_EPOCH = 4_354_819_198


def build_zipapp(source_root: Path, destination: Path, *, epoch: int) -> tuple[str, ...]:
    """Write one stored, timestamp-normalized executable archive without overwriting."""

    package = source_root / "repo_context"
    if not package.is_dir() or not (package / "__init__.py").is_file():
        raise ValueError(f"source root does not contain repo_context: {source_root}")
    legal_files: dict[str, Path] = {}
    for name in ("LICENSE", "NOTICE"):
        path = source_root.parent / name
        if not path.is_file() or path.is_symlink():
            raise ValueError(f"source tree does not contain a regular {name}: {path}")
        legal_files[name] = path
    if destination.exists() or destination.is_symlink():
        raise FileExistsError(destination)
    if not _MINIMUM_ZIP_EPOCH <= epoch <= _MAXIMUM_ZIP_EPOCH:
        raise ValueError("zipapp epoch must be representable by the ZIP timestamp format")

    entries = {name: path.read_bytes() for name, path in legal_files.items()}
    entries["__main__.py"] = _MAIN
    for path in sorted(package.rglob("*.py")):
        if path.is_symlink():
            raise ValueError(f"zipapp source may not be a symlink: {path}")
        entries[path.relative_to(source_root).as_posix()] = path.read_bytes()

    destination.parent.mkdir(parents=True, exist_ok=True)
    descriptor, temporary_name = tempfile.mkstemp(
        prefix=f".{destination.name}.",
        dir=destination.parent,
    )
    temporary = Path(temporary_name)
    try:
        with os.fdopen(descriptor, "wb") as stream:
            stream.write(b"#!/usr/bin/env python3\n")
            with zipfile.ZipFile(stream, "w", compression=zipfile.ZIP_STORED) as archive:
                for name in sorted(entries):
                    info = _zip_info(name, epoch)
                    archive.writestr(info, entries[name])
            stream.flush()
            os.fsync(stream.fileno())
        temporary.chmod(0o755)
        os.link(temporary, destination)
        temporary.unlink()
    except BaseException:
        temporary.unlink(missing_ok=True)
        raise
    return tuple(sorted(entries))


def _zip_info(name: str, epoch: int) -> zipfile.ZipInfo:
    normalized = epoch - (epoch % 2)
    timestamp = datetime.fromtimestamp(normalized, timezone.utc)
    info = zipfile.ZipInfo(name, timestamp.timetuple()[:6])
    info.compress_type = zipfile.ZIP_STORED
    info.create_system = 3
    info.external_attr = 0o100644 << 16
    info.flag_bits = 0
    return info


def main(arguments: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--epoch", type=int, required=True)
    options = parser.parse_args(arguments)
    build_zipapp(options.source, options.output, epoch=options.epoch)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
