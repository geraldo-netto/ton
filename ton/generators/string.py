"""String value generator."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from random import Random
from typing import Any

from .base import Generator, require_string_tuple


@dataclass(frozen=True)
class StringSpec:
    values: tuple[str, ...]


class StringGenerator(Generator):
    """Pick one literal string from ``values``."""

    type_name = "string"

    def prepare(self, spec: Mapping[str, Any], context: Any = None) -> StringSpec:
        return StringSpec(values=require_string_tuple(spec))

    def generate(self, prepared: StringSpec, rng: Random) -> str:
        return rng.choice(prepared.values)
