"""Integer value generator."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from random import Random
from typing import Any

from .base import Generator, coerce_bool, coerce_int, pad_with_zero, require_min_le_max


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
            # output (TODO REL-014).
            pad_width = max(len(str(min_value)), len(str(max_value)))
        return IntegerSpec(min_value=min_value, max_value=max_value, pad_width=pad_width)

    def generate(self, prepared: IntegerSpec, rng: Random) -> str:
        value = str(rng.randint(prepared.min_value, prepared.max_value))
        if prepared.pad_width:
            return pad_with_zero(value, prepared.pad_width)
        return value
