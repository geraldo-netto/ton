"""Integer value generator."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from random import Random
from typing import Any

from .._contracts import Generator
from .._proof import ProofResult, proof_result
from .._scalars import (
    coerce_bool,
    coerce_int,
    int_to_str,
    pad_with_zero,
    require_min_le_max,
    str_to_int,
)
from .._transforms import TransformResult


@dataclass(frozen=True)
class IntegerSpec:
    min_value: int
    max_value: int
    pad_width: int  # 0 = no padding


class IntegerGenerator(Generator):
    """Uniform integer in ``[minValue, maxValue]`` with optional zero padding."""

    type_name = "integer"

    def prepare(self, spec: Mapping[str, Any], context: Any = None) -> IntegerSpec:
        min_value = coerce_int(spec, "minValue", type_name="integer")
        max_value = coerce_int(spec, "maxValue", type_name="integer")
        require_min_le_max("integer", min_value, max_value)
        pad_width = 0
        if coerce_bool(spec, "padWithZero", type_name="integer", default=False):
            # Width must cover the widest possible rendering so a positive
            # value and the corresponding negative line up in fixed-width
            # output (REL-014).
            pad_width = max(len(int_to_str(min_value)), len(int_to_str(max_value)))
        return IntegerSpec(min_value=min_value, max_value=max_value, pad_width=pad_width)

    def generate(self, prepared: IntegerSpec, rng: Random) -> str:
        value = int_to_str(rng.randint(prepared.min_value, prepared.max_value))
        if prepared.pad_width:
            return pad_with_zero(value, prepared.pad_width)
        return value

    def prove(self, prepared: IntegerSpec, result: TransformResult) -> ProofResult:
        try:
            value = str_to_int(result.value)
        except ValueError:
            return proof_result(False, "value is not an integer")
        expected = pad_with_zero(int_to_str(value), prepared.pad_width)
        return proof_result(
            prepared.min_value <= value <= prepared.max_value and result.value == expected,
            "integer value is outside its bounds or padding contract",
        )
