"""Decimal value generator."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from decimal import ROUND_CEILING, ROUND_FLOOR, Decimal
from functools import cached_property
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
    pad_with_zero: bool

    @cached_property
    def steps(self) -> DecimalSteps:
        """Build and retain precision-dependent generation state on first use."""
        return _build_decimal_steps(self)

    @property
    def scale(self) -> int:
        return self.steps.scale

    @property
    def min_step(self) -> int:
        return self.steps.min_step

    @property
    def max_step(self) -> int:
        return self.steps.max_step

    @property
    def pad_width(self) -> int:
        return self.steps.pad_width


@dataclass(frozen=True)
class DecimalSteps:
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
        if not _has_representable_value(min_value, max_value, decimals):
            raise ValueError(
                f"decimal range contains no value representable with {decimals} decimal place(s)"
            )
        return DecimalSpec(
            min_value=min_value,
            max_value=max_value,
            decimals=decimals,
            pad_with_zero=coerce_bool(spec, "padWithZero", type_name="decimal", default=False),
        )

    def generate(self, prepared: DecimalSpec, rng: Random) -> str:
        steps = prepared.steps
        step = rng.randint(steps.min_step, steps.max_step)
        # f-string formatting keeps trailing zeros so pad_width math stays
        # consistent (str(round(1.5, 2)) drops the trailing zero).
        value = f"{step / steps.scale:.{prepared.decimals}f}"
        if steps.pad_width:
            return pad_with_zero(value, steps.pad_width)
        return value


def _has_representable_value(min_value: float, max_value: float, decimals: int) -> bool:
    """Validate the range without scaling when its lower bound already fits."""
    minimum = Decimal(str(min_value))
    maximum = Decimal(str(max_value))
    exponent = minimum.as_tuple().exponent
    if (
        minimum.is_finite()
        and maximum.is_finite()
        and isinstance(exponent, int)
        and exponent >= -decimals
    ):
        return True
    _, min_step, max_step = _step_bounds(min_value, max_value, decimals)
    return min_step <= max_step


def _build_decimal_steps(prepared: DecimalSpec) -> DecimalSteps:
    scale, min_step, max_step = _step_bounds(
        prepared.min_value,
        prepared.max_value,
        prepared.decimals,
    )
    pad_width = 0
    if prepared.pad_with_zero:
        # Width must cover the widest possible rendering -- include the
        # '-' sign on negative bounds and the decimal point + fraction
        # (TODO REL-014).
        pad_width = max(
            len(f"{min_step / scale:.{prepared.decimals}f}"),
            len(f"{max_step / scale:.{prepared.decimals}f}"),
        )
    return DecimalSteps(
        scale=scale,
        min_step=min_step,
        max_step=max_step,
        pad_width=pad_width,
    )


def _step_bounds(min_value: float, max_value: float, decimals: int) -> tuple[int, int, int]:
    scale = 10**decimals
    min_step = int((Decimal(str(min_value)) * scale).to_integral_value(rounding=ROUND_CEILING))
    max_step = int((Decimal(str(max_value)) * scale).to_integral_value(rounding=ROUND_FLOOR))
    return scale, min_step, max_step
