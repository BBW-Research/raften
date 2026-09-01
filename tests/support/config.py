from __future__ import annotations

from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
ROOT_POLICY_BYTES = (ROOT / "repo-context.toml").read_bytes()
ROOT_POLICY_TEXT = ROOT_POLICY_BYTES.decode("utf-8")


def replace_once(text: str, old: str, new: str) -> str:
    if text.count(old) != 1:
        raise AssertionError(f"expected one occurrence of {old!r}, found {text.count(old)}")
    return text.replace(old, new, 1)


def append_exception_record(text: str, body: str) -> str:
    return f"{text.rstrip()}\n\n[[exceptions.record]]\n{body.strip()}\n"
