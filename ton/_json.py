"""Exact, stack-safe JSON decoding and encoding."""

from __future__ import annotations

import json
import re
from collections.abc import Iterator, Mapping
from dataclasses import dataclass
from decimal import Decimal
from typing import Any

from ._scalars import int_to_str, str_to_int
from ._specsnapshot import FrozenSequence

_SCALAR_DECODER = json.JSONDecoder(parse_int=str_to_int, parse_float=Decimal)
_SPACE = re.compile(r"[ \t\n\r]*")


@dataclass
class _JsonFrame:
    container: Any
    first: bool = True


def parse_json(text: str) -> Any:
    """Decode containers iteratively, using the public JSON decoder for scalar syntax."""
    reader = _JsonReader(text)
    result = reader.value()
    while reader.frames:
        reader.fill(reader.frames[-1])
    reader.whitespace()
    if reader.position != len(text):
        raise json.JSONDecodeError("Extra data", text, reader.position)
    return result


class _JsonReader:
    def __init__(self, text: str) -> None:
        self.text = text
        self.position = 0
        self.frames: list[_JsonFrame] = []

    def whitespace(self) -> None:
        match = _SPACE.match(self.text, self.position)
        assert match is not None
        self.position = match.end()

    def take(self, token: str) -> bool:
        self.whitespace()
        if not self.text.startswith(token, self.position):
            return False
        self.position += len(token)
        return True

    def require(self, token: str) -> None:
        if not self.take(token):
            raise json.JSONDecodeError(f"Expecting '{token}' delimiter", self.text, self.position)

    def value(self) -> Any:
        self.whitespace()
        char = self.text[self.position : self.position + 1]
        if char in ("{", "["):
            self.position += 1
            container: Any = {} if char == "{" else []
            self.frames.append(_JsonFrame(container))
            return container
        value, self.position = _SCALAR_DECODER.raw_decode(self.text, self.position)
        return value

    def fill(self, frame: _JsonFrame) -> None:
        is_object = isinstance(frame.container, dict)
        if self.take("}" if is_object else "]"):
            self.frames.pop()
            return
        if not frame.first:
            self.require(",")
        frame.first = False
        if is_object:
            self.whitespace()
            if not self.text.startswith('"', self.position):
                raise json.JSONDecodeError(
                    "Expecting property name enclosed in double quotes", self.text, self.position
                )
            key = self.value()
            self.require(":")
            frame.container[key] = self.value()
        else:
            frame.container.append(self.value())


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
        elif isinstance(item, (Mapping, list, tuple, FrozenSequence)):
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
    if isinstance(value, int) and not isinstance(value, bool):
        return int_to_str(value)
    if isinstance(value, Decimal):
        if not value.is_finite():
            raise ValueError("Non-finite Decimal is not a JSON number")
        return str(value)
    return json.dumps(value, ensure_ascii=True, separators=(",", ":"), allow_nan=False)
