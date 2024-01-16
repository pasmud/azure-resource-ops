"""Strict JSON input and deterministic JSON output for local artifacts."""

import json
from pathlib import Path

from .core import InputError


def _object(pairs: list[tuple]) -> dict:
    result: dict = {}
    for key, value in pairs:
        if key in result:
            raise InputError("duplicate JSON object member")
        result[key] = value
    return result


def _no_constant(_: str) -> None:
    raise InputError("nonstandard JSON number")


def decode(text: str) -> object:
    try:
        return json.loads(text, object_pairs_hook=_object, parse_constant=_no_constant)
    except InputError:
        raise
    except (ValueError, RecursionError):
        raise InputError("invalid JSON") from None


def read_json(path: Path, label: str) -> object:
    try:
        return decode(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError):
        raise InputError(f"cannot read {label} as UTF-8") from None
    except InputError as exc:
        raise InputError(f"{label}: {exc}") from None


def render(value: object) -> str:
    return json.dumps(value, indent=2, sort_keys=True, ensure_ascii=True) + "\n"
