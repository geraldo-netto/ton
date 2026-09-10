"""Neutral weighted-distribution primitives shared across package layers."""

from __future__ import annotations

from bisect import bisect
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from math import isfinite
from random import Random
from typing import TYPE_CHECKING, Any, cast

from ._proof import ProofResult
from ._speckeys import require_known_keys

_CHOICE_KEYS = frozenset(("weight", "spec"))

if TYPE_CHECKING:
    from .generators.base import PreparationContext


def _as_result(value: str) -> Any:
    from ._transforms import TransformResult

    return TransformResult(value)


@dataclass(frozen=True)
class WeightedChoiceSet:
    """Weights paired with prepared child generators."""

    weights: tuple[float, ...]
    cum_weights: tuple[float, ...]
    children: tuple[tuple[Any, Any], ...]

    def choose(self, rng: Random) -> str:
        from .generators.base import drawn

        index = weighted_index(self.cum_weights, rng)
        generator, prepared = self.children[index]
        return drawn(generator, prepared, cast(str, generator.generate(prepared, rng)))

    def prove(self, result: Any) -> ProofResult:
        """Evaluate each selected child once and carry its original rejection (REL-038)."""
        from .generators.base import proven_draws

        draws = proven_draws(result, self.children)
        if draws is not None:
            for draw in draws:
                proof = draw.generator.prove(draw.prepared, _as_result(draw.value))
                if not proof.ok:
                    return proof
            return ProofResult(True)
        return ProofResult(
            any(generator.prove(prepared, result).ok for generator, prepared in self.children)
        )


def prepare_distribution(
    spec: Mapping[str, Any],
    registry: Mapping[str, Any],
    *,
    label: str,
    min_choices: int,
    context: PreparationContext | None = None,
) -> WeightedChoiceSet:
    from .generators.base import PreparationContext

    raw_choices = spec.get("choices")
    if not isinstance(raw_choices, list) or len(raw_choices) < min_choices:
        raise ValueError(_choices_error(label, min_choices))
    weights: list[float] = []
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
) -> tuple[float, tuple[Any, Any]]:
    if not isinstance(choice, Mapping):
        raise ValueError(
            f"{label} 'choices[{index}]' must be an object with 'weight' and 'spec' keys"
        )
    require_known_keys(f"{label}.choices[{index}]", choice, _CHOICE_KEYS)
    weight = _coerce_weight(index, choice, label)
    child = context.prepare_child(label, f"'choices[{index}].spec'", choice.get("spec"))
    return weight, child


def _coerce_weight(index: int, choice: Mapping[str, Any], label: str) -> float:
    if "weight" not in choice:
        return 1.0
    return coerce_weight(choice["weight"], f"{label} 'choices[{index}].weight'")


def coerce_weight(value: Any, location: str) -> float:
    """Convert a configured weight without accepting JSON booleans as numbers."""
    if isinstance(value, bool):
        raise ValueError(f"{location} must be numeric")
    try:
        return float(value)
    except (TypeError, ValueError) as exc:
        raise ValueError(f"{location} must be numeric") from exc


def validate_weights(weights: Sequence[float], label: str) -> None:
    """Reject weights that cannot define a proportional distribution.

    Only the inputs themselves are checked. Rejecting a set because its
    *sum* overflowed turned away finite, representable weights such as
    [1e308, 1e308], contrary to proportional-weight behavior (SCALE-008);
    accumulation is scaled instead, so the total never overflows.
    """
    if not all(isfinite(weight) for weight in weights):
        raise ValueError(f"{label} 'weights' must be finite")
    if any(weight < 0 for weight in weights):
        raise ValueError(f"{label} 'weights' must be non-negative")
    if not any(weight > 0 for weight in weights):
        raise ValueError(f"{label} 'weights' must sum to a positive number")


def cumulative_weights(weights: Sequence[float]) -> tuple[float, ...]:
    """Accumulate ``weights`` scaled by the largest of them.

    Scaling keeps every partial sum finite for any finite input while
    preserving the ratios that define the distribution -- summing raw
    weights overflowed to infinity for values near the float maximum
    (SCALE-008). ``validate_weights`` runs first, so the maximum is
    positive.
    """
    scale = max(weights)
    total = 0.0
    cumulative: list[float] = []
    for weight in weights:
        total += weight / scale
        cumulative.append(total)
    return tuple(cumulative)


def weighted_index(cum_weights: tuple[float, ...], rng: Random) -> int:
    """Draw an index without allocating the temporary objects used by ``choices``."""
    return bisect(cum_weights, rng.random() * cum_weights[-1], 0, len(cum_weights) - 1)


def _choices_error(label: str, min_choices: int) -> str:
    if min_choices == 1:
        return f"{label} 'choices' must be a non-empty list"
    return f"{label} 'choices' must contain at least {min_choices} entries"
