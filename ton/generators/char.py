"""Character-sequence generator."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from random import Random
from typing import Any

from .base import Generator, assert_below_cap, coerce_int, require_string_tuple

#: Upper bound on ``maxChar``. A misconfigured value of 1e9 would otherwise
#: produce gigabyte rows (TODO SCALE-002).
MAX_CHAR_LENGTH = 100_000


@dataclass(frozen=True)
class CharSpec:
    values: tuple[str, ...]
    max_char: int


class CharGenerator(Generator):
    """Concatenate ``maxChar`` random picks from ``values`` (with replacement)."""

    type_name = "char"

    def prepare(self, spec: Mapping[str, Any]) -> CharSpec:
        values = require_string_tuple(spec)
        max_char = coerce_int(spec, "maxChar", type_name="char")
        if max_char < 1:
            raise ValueError(f"char 'maxChar' must be >= 1 (got {max_char})")
        assert_below_cap("char", "maxChar", max_char, MAX_CHAR_LENGTH, "MAX_CHAR_LENGTH")
        return CharSpec(values=values, max_char=max_char)

    def generate(self, prepared: CharSpec, rng: Random) -> str:
        return "".join(rng.choice(prepared.values) for _ in range(prepared.max_char))
