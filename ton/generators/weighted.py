"""Weighted-choice value generator.

Picks one of several alternatives with non-uniform probability. Three
spec shapes are accepted; pick whichever reads best:

* **Parallel arrays** -- legacy form, string-only::

      {
        "type":    "weighted",
        "values":  ["Intel", "AMD", "ARM"],
        "weights": [90, 8, 2]
      }

* **Record form** -- legacy, also string-only::

      {
        "type":   "weighted",
        "values": [
          {"value": "Intel", "weight": 90},
          {"value": "AMD",   "weight": 8},
          {"value": "ARM",   "weight": 2}
        ]
      }

* **Composite form** -- weight any generator type::

      {
        "type":    "weighted",
        "choices": [
          {"weight": 70,
           "spec":   {"type": "string", "values": ["common"]}},
          {"weight": 25,
           "spec":   {"type": "integer", "minValue": 1, "maxValue": 9}},
          {"weight":  5,
           "spec":   {"type": "uuid", "version": 4}}
        ]
      }

  Nested ``spec`` is itself a full type spec. The engine resolves it
  against the same registry used for top-level types so any registered
  generator (built-in or third-party, including another ``weighted``)
  can be composed.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from random import Random
from typing import Any, ClassVar

from .base import Generator


@dataclass(frozen=True)
class WeightedSpec:
    weights: tuple[float, ...]
    #: Populated for the legacy ``values`` form.
    values: tuple[str, ...] | None = None
    #: Populated for the composite ``choices`` form.
    children: tuple[tuple[Generator, Any], ...] | None = None


class WeightedGenerator(Generator):
    """Pick one alternative with probability proportional to its weight."""

    type_name = "weighted"
    is_composite: ClassVar[bool] = True

    def prepare(self, spec: Mapping[str, Any]) -> WeightedSpec:
        # Composite specs require ``prepare_composite`` so they can
        # access the engine's registry; legacy specs are routed here
        # directly so callers that bypass the engine still work.
        if "choices" in spec:
            raise ValueError(
                "weighted 'choices' form requires the engine's composite "
                "preparation path; call Engine.prepare_composite via the "
                "engine instead of WeightedGenerator.prepare directly"
            )
        return self._prepare_legacy(spec)

    def prepare_composite(
        self,
        spec: Mapping[str, Any],
        registry: Mapping[str, Generator],
    ) -> WeightedSpec:
        raw_choices = spec.get("choices")
        if raw_choices is None:
            return self._prepare_legacy(spec)
        if not isinstance(raw_choices, list) or not raw_choices:
            raise ValueError("weighted 'choices' must be a non-empty list")
        weights: list[float] = []
        children: list[tuple[Generator, Any]] = []
        for index, choice in enumerate(raw_choices):
            weight, child = self._prepare_choice(index, choice, registry)
            weights.append(weight)
            children.append(child)
        self._validate_weights(weights)
        return WeightedSpec(
            weights=tuple(weights),
            children=tuple(children),
        )

    def generate(self, prepared: WeightedSpec, rng: Random) -> str:
        if prepared.children is not None:
            index = rng.choices(
                range(len(prepared.children)),
                weights=prepared.weights,
                k=1,
            )[0]
            child_gen, child_prepared = prepared.children[index]
            return child_gen.generate(child_prepared, rng)
        # Legacy string-only form.
        return rng.choices(prepared.values, weights=prepared.weights, k=1)[0]  # type: ignore[arg-type]

    def _prepare_legacy(self, spec: Mapping[str, Any]) -> WeightedSpec:
        values, weights = _coerce(spec)
        if not values:
            raise ValueError("weighted 'values' must be non-empty")
        self._validate_weights(weights)
        return WeightedSpec(values=values, weights=weights)

    def _prepare_choice(
        self,
        index: int,
        choice: Any,
        registry: Mapping[str, Generator],
    ) -> tuple[float, tuple[Generator, Any]]:
        if not isinstance(choice, Mapping):
            raise ValueError(
                f"weighted 'choices[{index}]' must be an object with "
                "'weight' and 'spec' keys"
            )
        try:
            weight = float(choice["weight"])
        except (KeyError, TypeError, ValueError) as exc:
            raise ValueError(
                f"weighted 'choices[{index}]' missing numeric 'weight'"
            ) from exc
        nested_spec = choice.get("spec")
        if not isinstance(nested_spec, Mapping) or "type" not in nested_spec:
            raise ValueError(
                f"weighted 'choices[{index}].spec' must be an object with "
                "a 'type' field"
            )
        nested_type = nested_spec["type"]
        if nested_type not in registry:
            raise ValueError(
                f"weighted 'choices[{index}].spec' references unknown "
                f"type {nested_type!r}"
            )
        child_generator = registry[nested_type]
        if child_generator.is_composite:
            child_prepared = child_generator.prepare_composite(nested_spec, registry)
        else:
            child_prepared = child_generator.prepare(nested_spec)
        return weight, (child_generator, child_prepared)

    @staticmethod
    def _validate_weights(weights: Sequence[float]) -> None:
        if any(w < 0 for w in weights):
            raise ValueError("weighted 'weights' must be non-negative")
        if sum(weights) <= 0:
            raise ValueError("weighted 'weights' must sum to a positive number")


def _coerce(spec: Mapping[str, Any]) -> tuple[tuple[str, ...], tuple[float, ...]]:
    raw_values = spec.get("values")
    if not isinstance(raw_values, list):
        raise ValueError("weighted 'values' must be a list")
    if raw_values and isinstance(raw_values[0], dict):
        # Record form: [{value, weight}, ...]
        return (
            tuple(str(item["value"]) for item in raw_values),
            tuple(float(item["weight"]) for item in raw_values),
        )
    # Parallel-array form
    weights: Sequence[Any] = spec.get("weights", [])
    if not isinstance(weights, list) or len(weights) != len(raw_values):
        raise ValueError(
            "weighted 'weights' must be a list the same length as 'values'"
        )
    return (
        tuple(str(v) for v in raw_values),
        tuple(float(w) for w in weights),
    )
