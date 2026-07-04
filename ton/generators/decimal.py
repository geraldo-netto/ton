"""Decimal value generator."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from random import Random
from typing import Any

from .base import Generator, coerce_float, coerce_int, pad_with_zero, require_min_le_max


@dataclass(frozen=True)
class DecimalSpec:
    min_value: float
    max_value: float
    decimals: int
    pad_width: int  # 0 = no padding


class DecimalGenerator(Generator):
    """Uniform float in ``[minValue, maxValue]`` rounded to ``decimals``."""

    type_name = "decimal"

    def prepare(self, spec: Mapping[str, Any]) -> DecimalSpec:
        min_value = coerce_float(spec, "minValue", type_name="decimal")
        max_value = coerce_float(spec, "maxValue", type_name="decimal")
        require_min_le_max("decimal", min_value, max_value)
        decimals = coerce_int(spec, "decimals", type_name="decimal")
        if decimals < 0:
            raise ValueError(f"decimal 'decimals' must be >= 0 (got {decimals})")
        pad_width = 0
        if spec.get("padWithZero", False):
            # Width must cover the widest possible rendering -- include the
            # '-' sign on negative bounds and the decimal point + fraction
            # (TODO REL-014).
            pad_width = max(
                len(f"{min_value:.{decimals}f}"),
                len(f"{max_value:.{decimals}f}"),
            )
        return DecimalSpec(
            min_value=min_value,
            max_value=max_value,
            decimals=decimals,
            pad_width=pad_width,
        )

    def generate(self, prepared: DecimalSpec, rng: Random) -> str:
        raw = rng.uniform(prepared.min_value, prepared.max_value)
        # f-string formatting keeps trailing zeros so pad_width math stays
        # consistent (str(round(1.5, 2)) drops the trailing zero).
        value = f"{raw:.{prepared.decimals}f}"
        if prepared.pad_width:
            return pad_with_zero(value, prepared.pad_width)
        return value
