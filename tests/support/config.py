from __future__ import annotations

from raften.config import render_starter_policy


STARTER_POLICY_BYTES = render_starter_policy()
STARTER_POLICY_TEXT = STARTER_POLICY_BYTES.decode("utf-8")


def replace_once(text: str, old: str, new: str) -> str:
    if text.count(old) != 1:
        raise AssertionError(f"expected one occurrence of {old!r}, found {text.count(old)}")
    return text.replace(old, new, 1)


def append_exception_record(text: str, body: str) -> str:
    return f"{text.rstrip()}\n\n[[exceptions.record]]\n{body.strip()}\n"
