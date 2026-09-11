"""Neutral weighted-distribution primitives shared across package layers."""

from __future__ import annotations

from bisect import bisect
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from decimal import Decimal, InvalidOperation
from fractions import Fraction
from itertools import accumulate
from math import gcd, lcm
from random import Random
from typing import Any, cast

from ._contracts import PreparationContext
from ._pipeline import as_result, drawn, proven_draws, public_value
from ._proof import ProofResult
from ._speckeys import require_known_keys
from ._specpath import format_spec_path
from ._steps import Call, Steps, cooperative, run_steps

_CHOICE_KEYS = frozenset(("weight", "spec"))


@dataclass(frozen=True)
class WeightedChoiceSet:
    """Weights paired with prepared child generators."""

    weights: tuple[Fraction, ...]
    cum_weights: tuple[int, ...]
    children: tuple[tuple[Any, Any], ...]

    @cooperative
    def choose(self, rng: Random) -> str:
        return public_value(run_steps(self, "choose", rng))

    def _choose_steps(self, rng: Random) -> Steps:
        index = weighted_index(self.cum_weights, rng)
        generator, prepared = self.children[index]
        value = yield Call(generator, "generate", (prepared, rng))
        return drawn(generator, prepared, value, self)

    @cooperative
    def prove(self, result: Any) -> ProofResult:
        return cast(ProofResult, run_steps(self, "prove", result))

    def _prove_steps(self, result: Any) -> Steps:
        """Evaluate each selected child once and carry its original rejection (REL-038)."""
        draws = proven_draws(result, self)
        if draws is not None:
            for draw in draws:
                proof = yield Call(
                    draw.generator,
                    "prove",
                    (draw.prepared, as_result(draw.value)),
                    proof_stage="source",
                )
                if not proof.ok:
                    return proof
            return ProofResult(True)
        for generator, prepared in self.children:
            proof = yield Call(generator, "prove", (prepared, result), proof_stage="source")
            if proof.ok:
                return ProofResult(True)
        return ProofResult(False)


def prepare_distribution(
    spec: Mapping[str, Any],
    registry: Mapping[str, Any],
    *,
    label: str,
    min_choices: int,
    context: PreparationContext | None = None,
) -> WeightedChoiceSet:
    raw_choices = spec.get("choices")
    if not isinstance(raw_choices, list) or len(raw_choices) < min_choices:
        raise ValueError(_choices_error(label, min_choices))
    weights: list[Fraction] = []
    children: list[tuple[Any, Any]] = []
    preparation = context or PreparationContext(registry)
    for index, choice in enumerate(raw_choices):
        weight, child = _prepare_choice(index, choice, preparation, label)
        weights.append(weight)
        children.append(child)
    validate_weights(weights, label)
    return WeightedChoiceSet(tuple(weights), cumulative_weights(weights), tuple(children))


def _prepare_choice(
    index: int,
    choice: Any,
    context: Any,
    label: str,
) -> tuple[Fraction, tuple[Any, Any]]:
    if not isinstance(choice, Mapping):
        raise ValueError(
            f"{label} 'choices[{index}]' must be an object with 'weight' and 'spec' keys"
        )

    def location() -> str:
        owner = f"types.{format_spec_path(context.path)}" if context.path else label
        return f"{owner}.choices[{index}]"

    require_known_keys(location, choice, _CHOICE_KEYS)
    weight = _coerce_weight(index, choice, label)
    child = context.prepare_child(label, ("choices", index, "spec"), choice.get("spec"))
    return weight, child


def _coerce_weight(index: int, choice: Mapping[str, Any], label: str) -> Fraction:
    if "weight" not in choice:
        return Fraction(1)
    return coerce_weight(choice["weight"], f"{label} 'choices[{index}].weight'")


def coerce_weight(value: Any, location: str) -> Fraction:
    """Convert a configured weight without accepting JSON booleans as numbers."""
    if isinstance(value, bool):
        raise ValueError(f"{location} must be numeric")
    try:
        value = Decimal(value) if isinstance(value, str) else value
    except InvalidOperation as exc:
        raise ValueError(f"{location} must be numeric") from exc
    try:
        return Fraction(value)
    except TypeError as exc:
        raise ValueError(f"{location} must be numeric") from exc
    except (ValueError, OverflowError) as exc:
        raise ValueError(f"{location} must be finite") from exc


def validate_weights(weights: Sequence[Fraction], label: str) -> None:
    """Reject exact weights that cannot define a proportional distribution."""
    if any(weight < 0 for weight in weights):
        raise ValueError(f"{label} 'weights' must be non-negative")
    if not any(weight > 0 for weight in weights):
        raise ValueError(f"{label} 'weights' must sum to a positive number")


def cumulative_weights(weights: Sequence[Fraction]) -> tuple[int, ...]:
    """Build the smallest integer intervals preserving every exact ratio."""
    denominator = lcm(*(weight.denominator for weight in weights))
    integers = [weight.numerator * (denominator // weight.denominator) for weight in weights]
    divisor = gcd(*integers)
    return tuple(accumulate(weight // divisor for weight in integers))


def weighted_index(cum_weights: tuple[int, ...], rng: Random) -> int:
    """Draw an index without allocating the temporary objects used by ``choices``."""
    return bisect(cum_weights, rng.randrange(cum_weights[-1]), 0, len(cum_weights) - 1)


def _choices_error(label: str, min_choices: int) -> str:
    if min_choices == 1:
        return f"{label} 'choices' must be a non-empty list"
    return f"{label} 'choices' must contain at least {min_choices} entries"
