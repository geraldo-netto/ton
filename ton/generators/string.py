"""String value generator."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from random import Random
from typing import Any

from .._contracts import Generator
from .._proof import ProofResult, proof_result
from .._scalars import require_string_tuple
from .._transforms import TransformResult


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

    def prove(self, prepared: StringSpec, result: TransformResult) -> ProofResult:
        return proof_result(result.value in prepared.values, "value is not in string 'values'")
