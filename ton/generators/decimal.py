"""Decimal value generator."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from decimal import ROUND_CEILING, ROUND_FLOOR, Decimal, InvalidOperation, localcontext
from functools import cached_property
from random import Random
from typing import Any

from .._proof import ProofResult
from .._transforms import TransformResult
from .base import (
    Generator,
    coerce_bool,
    coerce_int,
    pad_with_zero,
    proof_result,
    require_min_le_max,
)


@dataclass(frozen=True)
class DecimalSpec:
    min_value: Decimal
    max_value: Decimal
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
    """Uniform fixed-point value in ``[minValue, maxValue]``."""

    type_name = "decimal"

    def prepare(self, spec: Mapping[str, Any], context: Any = None) -> DecimalSpec:
        min_value = _coerce_decimal(spec, "minValue")
        max_value = _coerce_decimal(spec, "maxValue")
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
        value = _format_step(step, steps.scale, prepared.decimals)
        if steps.pad_width:
            return pad_with_zero(value, steps.pad_width)
        return value

    def prove(self, prepared: DecimalSpec, result: TransformResult) -> ProofResult:
        expected_fraction = result.value.lstrip("-0").partition(".")[2]
        try:
            value = Decimal(result.value)
        except InvalidOperation:
            return proof_result(False, "value is not decimal")
        width_ok = not prepared.pad_width or len(result.value) == prepared.pad_width
        return proof_result(
            value.is_finite()
            and prepared.min_value <= value <= prepared.max_value
            and (prepared.decimals == 0 or len(expected_fraction) == prepared.decimals)
            and width_ok,
            "decimal value is outside its bounds, scale, or padding contract",
        )


def _coerce_decimal(spec: Mapping[str, Any], key: str) -> Decimal:
    if key not in spec:
        raise ValueError(f"decimal {key!r} is required")
    raw = spec[key]
    if isinstance(raw, bool):
        raise ValueError(f"decimal {key!r} must be a number (got {raw!r})")
    try:
        value = Decimal(str(raw))
    except (InvalidOperation, ValueError) as exc:
        raise ValueError(f"decimal {key!r} must be a number (got {raw!r})") from exc
    if not value.is_finite():
        raise ValueError(f"decimal {key!r} must be a finite number (got {raw!r})")
    return value


def _has_representable_value(min_value: Decimal, max_value: Decimal, decimals: int) -> bool:
    """Validate the range without scaling when its lower bound already fits."""
    exponent = min_value.as_tuple().exponent
    if (
        min_value.is_finite()
        and max_value.is_finite()
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
        # (REL-014).
        pad_width = max(
            len(_format_step(min_step, scale, prepared.decimals)),
            len(_format_step(max_step, scale, prepared.decimals)),
        )
    return DecimalSteps(
        scale=scale,
        min_step=min_step,
        max_step=max_step,
        pad_width=pad_width,
    )


def _step_bounds(min_value: Decimal, max_value: Decimal, decimals: int) -> tuple[int, int, int]:
    scale = 10**decimals
    min_step = _scaled_integral(min_value, scale, decimals, ROUND_CEILING)
    max_step = _scaled_integral(max_value, scale, decimals, ROUND_FLOOR)
    return scale, min_step, max_step


def _scaled_integral(value: Decimal, scale: int, decimals: int, rounding: str) -> int:
    digits = value.as_tuple().digits
    exponent = value.as_tuple().exponent
    precision = len(digits) + abs(exponent if isinstance(exponent, int) else 0) + decimals + 2
    with localcontext() as context:
        context.prec = precision
        return int((value * scale).to_integral_value(rounding=rounding))


def _format_step(step: int, scale: int, decimals: int) -> str:
    if decimals == 0:
        return str(step)
    whole, fraction = divmod(abs(step), scale)
    sign = "-" if step < 0 else ""
    return f"{sign}{whole}.{fraction:0{decimals}d}"
