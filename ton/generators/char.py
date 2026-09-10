"""Character-sequence generator."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from random import Random
from typing import Any

from .._contracts import Generator
from .._proof import ProofResult, proof_result
from .._scalars import coerce_int, require_string_tuple
from .._transforms import TransformResult


@dataclass(frozen=True)
class CharSpec:
    values: tuple[str, ...]
    max_char: int


class CharGenerator(Generator):
    """Concatenate ``maxChar`` random picks from ``values`` (with replacement)."""

    type_name = "char"

    def prepare(self, spec: Mapping[str, Any], context: Any = None) -> CharSpec:
        values = require_string_tuple(spec)
        max_char = coerce_int(spec, "maxChar", type_name="char")
        if max_char < 1:
            raise ValueError(f"char 'maxChar' must be >= 1 (got {max_char})")
        return CharSpec(values=values, max_char=max_char)

    def generate(self, prepared: CharSpec, rng: Random) -> str:
        return "".join(rng.choices(prepared.values, k=prepared.max_char))

    def prove(self, prepared: CharSpec, result: TransformResult) -> ProofResult:
        positions = {0}
        for _ in range(prepared.max_char):
            positions = {
                position + len(candidate)
                for position in positions
                for candidate in prepared.values
                if result.value.startswith(candidate, position)
            }
            if not positions:
                break
        return proof_result(len(result.value) in positions, "value is not a valid char sequence")
