"""Neutral weighted-distribution primitives shared across package layers."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from random import Random
from typing import Any, Protocol


class DistributionGenerator(Protocol):
    """Structural generator contract needed by weighted distributions."""

    is_composite: bool

    def prepare(self, spec: Mapping[str, Any]) -> Any: ...

    def prepare_composite(
        self, spec: Mapping[str, Any], registry: Mapping[str, DistributionGenerator]
    ) -> Any: ...

    def generate(self, prepared: Any, rng: Random) -> str: ...

    def prove(self, prepared: Any, result: Any) -> Any: ...


@dataclass(frozen=True)
class WeightedChoiceSet:
    """Weights paired with prepared child generators."""

    weights: tuple[float, ...]
    cum_weights: tuple[float, ...]
    children: tuple[tuple[DistributionGenerator, Any], ...]

    def choose(self, rng: Random) -> str:
        index = rng.choices(range(len(self.children)), cum_weights=self.cum_weights, k=1)[0]
        generator, prepared = self.children[index]
        return generator.generate(prepared, rng)

    def accepts(self, result: Any) -> bool:
        return any(generator.prove(prepared, result).ok for generator, prepared in self.children)


def prepare_distribution(
    spec: Mapping[str, Any],
    registry: Mapping[str, DistributionGenerator],
    *,
    label: str,
    min_choices: int,
) -> WeightedChoiceSet:
    raw_choices = spec.get("choices")
    if not isinstance(raw_choices, list) or len(raw_choices) < min_choices:
        raise ValueError(_choices_error(label, min_choices))
    weights: list[float] = []
    children: list[tuple[DistributionGenerator, Any]] = []
    for index, choice in enumerate(raw_choices):
        weight, child = _prepare_choice(index, choice, registry, label)
        weights.append(weight)
        children.append(child)
    validate_weights(weights, label)
    return WeightedChoiceSet(tuple(weights), cumulative_weights(weights), tuple(children))


def _prepare_choice(
    index: int,
    choice: Any,
    registry: Mapping[str, DistributionGenerator],
    label: str,
) -> tuple[float, tuple[DistributionGenerator, Any]]:
    if not isinstance(choice, Mapping):
        raise ValueError(
            f"{label} 'choices[{index}]' must be an object with 'weight' and 'spec' keys"
        )
    weight = _coerce_weight(index, choice, label)
    child = _prepare_child(label, f"'choices[{index}].spec'", choice.get("spec"), registry)
    return weight, child


def _prepare_child(
    parent: str,
    path: str,
    raw_spec: Any,
    registry: Mapping[str, DistributionGenerator],
) -> tuple[DistributionGenerator, Any]:
    if not isinstance(raw_spec, Mapping):
        raise ValueError(f"{parent} {path} must be an object")
    type_name = raw_spec.get("type")
    if not isinstance(type_name, str) or not type_name:
        raise ValueError(f"{parent} {path} must contain a non-empty string 'type'")
    generator = registry.get(type_name) or registry.get(type_name.removeprefix("core."))
    if generator is None:
        raise ValueError(f"{parent} {path} references unknown type {type_name!r}")
    if generator.is_composite:
        return generator, generator.prepare_composite(raw_spec, registry)
    return generator, generator.prepare(raw_spec)


def _coerce_weight(index: int, choice: Mapping[str, Any], label: str) -> float:
    if "weight" not in choice:
        return 1.0
    try:
        return float(choice["weight"])
    except (TypeError, ValueError) as exc:
        raise ValueError(f"{label} 'choices[{index}].weight' must be numeric") from exc


def validate_weights(weights: Sequence[float], label: str) -> None:
    if any(weight < 0 for weight in weights):
        raise ValueError(f"{label} 'weights' must be non-negative")
    if sum(weights) <= 0:
        raise ValueError(f"{label} 'weights' must sum to a positive number")


def cumulative_weights(weights: Sequence[float]) -> tuple[float, ...]:
    total = 0.0
    cumulative: list[float] = []
    for weight in weights:
        total += weight
        cumulative.append(total)
    return tuple(cumulative)


def _choices_error(label: str, min_choices: int) -> str:
    if min_choices == 1:
        return f"{label} 'choices' must be a non-empty list"
    return f"{label} 'choices' must contain at least {min_choices} entries"
