"""Statistical distribution transform."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from random import Random
from typing import Any, ClassVar

from .._transforms import BaseTransform, TransformCapabilities, TransformResult
from ..generators import Generator
from ..generators.base import prepare_child_spec


@dataclass(frozen=True)
class WeightedChoiceSet:
    """Weights paired with prepared child generators (PAT-001).

    The single value object behind every weighted-choice concept
    (``distribution`` transform and the composite ``weighted``
    generator): it carries the weights and their prepared children and
    knows how to :meth:`choose` one child proportional to weight and
    generate from it. Weight validation lives in :func:`validate_weights`
    so the legacy string-only ``weighted`` form can share it too
    (DUP-001).
    """

    weights: tuple[float, ...]
    children: tuple[tuple[Generator, Any], ...]

    def choose(self, rng: Random) -> str:
        """Return one generated value drawn proportional to the weights."""
        index = rng.choices(range(len(self.children)), weights=self.weights, k=1)[0]
        child_gen, child_prepared = self.children[index]
        return child_gen.generate(child_prepared, rng)


class DistributionTransform(BaseTransform):
    """Choose among two-or-more prepared candidate data types."""

    type_name: ClassVar[str] = "distribution"
    capabilities: ClassVar[TransformCapabilities] = TransformCapabilities()

    def prepare_composite(
        self,
        spec: Mapping[str, Any],
        registry: Mapping[str, Generator],
    ) -> WeightedChoiceSet:
        return prepare_distribution(
            spec,
            registry,
            label="distribution",
            min_choices=2,
        )

    def apply(
        self,
        prepared: WeightedChoiceSet,
        value: TransformResult,
        rng: Random,
    ) -> TransformResult:
        del value
        return TransformResult(prepared.choose(rng))


def prepare_distribution(
    spec: Mapping[str, Any],
    registry: Mapping[str, Generator],
    *,
    label: str,
    min_choices: int,
) -> WeightedChoiceSet:
    raw_choices = spec.get("choices")
    if not isinstance(raw_choices, list) or len(raw_choices) < min_choices:
        raise ValueError(_choices_error(label, min_choices))
    weights: list[float] = []
    children: list[tuple[Generator, Any]] = []
    for index, choice in enumerate(raw_choices):
        weight, child = _prepare_choice(index, choice, registry, label)
        weights.append(weight)
        children.append(child)
    validate_weights(weights, label)
    return WeightedChoiceSet(weights=tuple(weights), children=tuple(children))


def _prepare_choice(
    index: int,
    choice: Any,
    registry: Mapping[str, Generator],
    label: str,
) -> tuple[float, tuple[Generator, Any]]:
    if not isinstance(choice, Mapping):
        raise ValueError(
            f"{label} 'choices[{index}]' must be an object with 'weight' and 'spec' keys"
        )
    weight = _coerce_weight(index, choice, label)
    child = prepare_child_spec(
        label,
        f"'choices[{index}].spec'",
        choice.get("spec"),
        registry,
    )
    return weight, child


def _coerce_weight(index: int, choice: Mapping[str, Any], label: str) -> float:
    if "weight" not in choice:
        return 1.0
    try:
        return float(choice["weight"])
    except (TypeError, ValueError) as exc:
        raise ValueError(f"{label} 'choices[{index}].weight' must be numeric") from exc


def validate_weights(weights: Sequence[float], label: str) -> None:
    """Reject negative weights or a non-positive sum (DUP-001).

    Shared by :func:`prepare_distribution` and the legacy string-only
    ``weighted`` form so the two rules stay in one place.
    """
    if any(weight < 0 for weight in weights):
        raise ValueError(f"{label} 'weights' must be non-negative")
    if sum(weights) <= 0:
        raise ValueError(f"{label} 'weights' must sum to a positive number")


def _choices_error(label: str, min_choices: int) -> str:
    if min_choices == 1:
        return f"{label} 'choices' must be a non-empty list"
    return f"{label} 'choices' must contain at least {min_choices} entries"
