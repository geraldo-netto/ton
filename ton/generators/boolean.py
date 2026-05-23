"""Boolean value generator."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from random import Random
from typing import Any

from .base import Generator


@dataclass(frozen=True)
class BooleanSpec:
    when_true: str
    when_false: str


class BooleanGenerator(Generator):
    """Pick one of two literals with equal probability."""

    type_name = "boolean"

    def prepare(self, spec: Mapping[str, Any]) -> BooleanSpec:
        return BooleanSpec(
            when_true=str(spec["whenTrue"]),
            when_false=str(spec["whenFalse"]),
        )

    def generate(self, prepared: BooleanSpec, rng: Random) -> str:
        return rng.choice((prepared.when_true, prepared.when_false))
