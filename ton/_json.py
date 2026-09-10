"""Exact, stack-safe JSON encoding for audit payloads and fingerprints."""

from __future__ import annotations

import json
from collections.abc import Iterator, Mapping
from decimal import Decimal
from typing import Any


def iter_json(value: Any, *, sort_keys: bool = False) -> Iterator[str]:
    """Stream JSON tokens without converting decimal numbers to binary floats."""
    pending = [iter(((False, value),))]
    active: set[int] = set()
    containers: list[Any] = []
    while pending:
        try:
            literal, item = next(pending[-1])
        except StopIteration:
            pending.pop()
            if containers:
                active.remove(id(containers.pop()))
            continue
        if literal:
            yield item
        elif isinstance(item, (Mapping, list, tuple)):
            if id(item) in active:
                raise ValueError("Circular reference detected")
            active.add(id(item))
            containers.append(item)
            pending.append(_container_tokens(item, sort_keys))
        else:
            yield _scalar(item)


def _container_tokens(value: Any, sort_keys: bool) -> Iterator[tuple[bool, Any]]:
    if isinstance(value, Mapping):
        yield True, "{"
        keys = sorted(value) if sort_keys else value
        for index, key in enumerate(keys):
            if index:
                yield True, ","
            # Delegate JSON's object-key conversion and validation to its public encoder.
            yield True, json.dumps({key: None}, ensure_ascii=True).removesuffix(" null}")[1:]
            yield False, value[key]
        yield True, "}"
    else:
        yield True, "["
        for index, item in enumerate(value):
            if index:
                yield True, ","
            yield False, item
        yield True, "]"


def _scalar(value: Any) -> str:
    if isinstance(value, Decimal):
        if not value.is_finite():
            raise ValueError("Non-finite Decimal is not a JSON number")
        return str(value)
    return json.dumps(value, ensure_ascii=True, separators=(",", ":"), allow_nan=False)
