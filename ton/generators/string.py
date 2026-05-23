"""String value generator."""

from __future__ import annotations

from dataclasses import dataclass
from random import Random
from typing import Any, Mapping, Tuple

from .base import Generator, require_string_tuple


@dataclass(frozen=True)
class StringSpec:
    values: Tuple[str, ...]


class StringGenerator(Generator):
    """Pick one literal string from ``values``."""

    type_name = "string"

    def prepare(self, spec: Mapping[str, Any]) -> StringSpec:
        return StringSpec(values=require_string_tuple(spec))

    def generate(self, prepared: StringSpec, rng: Random) -> str:
        return rng.choice(prepared.values)
