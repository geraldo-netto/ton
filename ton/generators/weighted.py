"""Weighted-choice value generator.

Picks one of several alternatives. Weights are optional in every shape;
when omitted the generator falls back to uniform sampling (1/N per
entry). Three spec shapes are accepted; pick whichever reads best:

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

from ..transforms.distribution import (
    DistributionSpec,
    choose_distribution,
    prepare_distribution,
)
from .base import Generator


@dataclass(frozen=True)
class WeightedSpec:
    weights: tuple[float, ...]
    #: Populated for the legacy ``values`` form.
    values: tuple[str, ...] | None = None
    #: Populated for the composite ``choices`` form.
    distribution: DistributionSpec | None = None


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
        distribution = prepare_distribution(
            _distribution_spec(spec),
            registry,
            label="weighted",
            min_choices=1,
        )
        return WeightedSpec(
            weights=distribution.weights,
            distribution=distribution,
        )

    def generate(self, prepared: WeightedSpec, rng: Random) -> str:
        if prepared.distribution is not None:
            return choose_distribution(prepared.distribution, rng)
        # Legacy string-only form.
        return rng.choices(prepared.values, weights=prepared.weights, k=1)[0]  # type: ignore[arg-type]

    def _prepare_legacy(self, spec: Mapping[str, Any]) -> WeightedSpec:
        values, weights = _coerce(spec)
        if not values:
            raise ValueError("weighted 'values' must be non-empty")
        self._validate_weights(weights)
        return WeightedSpec(values=values, weights=weights)

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
        # Record form: [{value, weight}, ...]. ``weight`` defaults to 1.0
        # so a list of bare ``{"value": ...}`` records still works -- the
        # generator falls back to uniform weighting.
        return (
            tuple(str(item["value"]) for item in raw_values),
            tuple(float(item.get("weight", 1.0)) for item in raw_values),
        )
    # Parallel-array form. Missing ``weights`` defaults to uniform so
    # ``{"values": [...]}`` is equivalent to picking with equal
    # probability (1/N per entry).
    if "weights" not in spec:
        return (
            tuple(str(v) for v in raw_values),
            tuple(1.0 for _ in raw_values),
        )
    weights: Sequence[Any] = spec["weights"]
    if not isinstance(weights, list) or len(weights) != len(raw_values):
        raise ValueError(
            "weighted 'weights' must be a list the same length as 'values'"
        )
    return (
        tuple(str(v) for v in raw_values),
        tuple(float(w) for w in weights),
    )


def _distribution_spec(spec: Mapping[str, Any]) -> dict[str, Any]:
    return {"type": "distribution", "choices": spec["choices"]}
