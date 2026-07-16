"""Decimal value generator."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from decimal import ROUND_CEILING, ROUND_FLOOR, Decimal
from random import Random
from typing import Any

from .base import (
    Generator,
    coerce_bool,
    coerce_float,
    coerce_int,
    pad_with_zero,
    require_min_le_max,
)


@dataclass(frozen=True)
class DecimalSpec:
    min_value: float
    max_value: float
    decimals: int
    scale: int
    min_step: int
    max_step: int
    pad_width: int  # 0 = no padding


class DecimalGenerator(Generator):
    """Uniform float in ``[minValue, maxValue]`` rounded to ``decimals``."""

    type_name = "decimal"

    def prepare(self, spec: Mapping[str, Any], context: Any = None) -> DecimalSpec:
        min_value = coerce_float(spec, "minValue", type_name="decimal")
        max_value = coerce_float(spec, "maxValue", type_name="decimal")
        require_min_le_max("decimal", min_value, max_value)
        decimals = coerce_int(spec, "decimals", type_name="decimal")
        if decimals < 0:
            raise ValueError(f"decimal 'decimals' must be >= 0 (got {decimals})")
        scale = 10**decimals
        min_step = int((Decimal(str(min_value)) * scale).to_integral_value(rounding=ROUND_CEILING))
        max_step = int((Decimal(str(max_value)) * scale).to_integral_value(rounding=ROUND_FLOOR))
        if min_step > max_step:
            raise ValueError(
                f"decimal range contains no value representable with {decimals} decimal place(s)"
            )
        pad_width = 0
        if coerce_bool(spec, "padWithZero", type_name="decimal", default=False):
            # Width must cover the widest possible rendering -- include the
            # '-' sign on negative bounds and the decimal point + fraction
            # (TODO REL-014).
            pad_width = max(
                len(f"{min_step / scale:.{decimals}f}"),
                len(f"{max_step / scale:.{decimals}f}"),
            )
        return DecimalSpec(
            min_value=min_value,
            max_value=max_value,
            decimals=decimals,
            scale=scale,
            min_step=min_step,
            max_step=max_step,
            pad_width=pad_width,
        )

    def generate(self, prepared: DecimalSpec, rng: Random) -> str:
        step = rng.randint(prepared.min_step, prepared.max_step)
        # f-string formatting keeps trailing zeros so pad_width math stays
        # consistent (str(round(1.5, 2)) drops the trailing zero).
        value = f"{step / prepared.scale:.{prepared.decimals}f}"
        if prepared.pad_width:
            return pad_with_zero(value, prepared.pad_width)
        return value
