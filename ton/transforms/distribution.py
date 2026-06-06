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
class DistributionSpec:
    weights: tuple[float, ...]
    children: tuple[tuple[Generator, Any], ...]


class DistributionTransform(BaseTransform):
    """Choose among two-or-more prepared candidate data types."""

    type_name: ClassVar[str] = "distribution"
    capabilities: ClassVar[TransformCapabilities] = TransformCapabilities()

    def prepare_composite(
        self,
        spec: Mapping[str, Any],
        registry: Mapping[str, Generator],
    ) -> DistributionSpec:
        raw_choices = spec.get("choices")
        if not isinstance(raw_choices, list) or len(raw_choices) < 2:
            raise ValueError("distribution 'choices' must contain at least two entries")
        weights: list[float] = []
        children: list[tuple[Generator, Any]] = []
        for index, choice in enumerate(raw_choices):
            weight, child = _prepare_choice(index, choice, registry)
            weights.append(weight)
            children.append(child)
        _validate_weights(weights)
        return DistributionSpec(weights=tuple(weights), children=tuple(children))

    def apply(
        self,
        prepared: DistributionSpec,
        value: TransformResult,
        rng: Random,
    ) -> TransformResult:
        del value
        index = rng.choices(range(len(prepared.children)), weights=prepared.weights, k=1)[0]
        child_gen, child_prepared = prepared.children[index]
        return TransformResult(child_gen.generate(child_prepared, rng))


def choose_distribution(prepared: DistributionSpec, rng: Random) -> str:
    """Return one generated value from ``prepared``."""
    index = rng.choices(range(len(prepared.children)), weights=prepared.weights, k=1)[0]
    child_gen, child_prepared = prepared.children[index]
    return child_gen.generate(child_prepared, rng)


def _prepare_choice(
    index: int,
    choice: Any,
    registry: Mapping[str, Generator],
) -> tuple[float, tuple[Generator, Any]]:
    if not isinstance(choice, Mapping):
        raise ValueError(f"distribution 'choices[{index}]' must be an object")
    weight = _coerce_weight(index, choice)
    child = prepare_child_spec(
        "distribution",
        f"'choices[{index}].spec'",
        choice.get("spec"),
        registry,
    )
    return weight, child


def _coerce_weight(index: int, choice: Mapping[str, Any]) -> float:
    if "weight" not in choice:
        return 1.0
    try:
        return float(choice["weight"])
    except (TypeError, ValueError) as exc:
        raise ValueError(f"distribution 'choices[{index}].weight' must be numeric") from exc


def _validate_weights(weights: Sequence[float]) -> None:
    if any(weight < 0 for weight in weights):
        raise ValueError("distribution 'weights' must be non-negative")
    if sum(weights) <= 0:
        raise ValueError("distribution 'weights' must sum to a positive number")
