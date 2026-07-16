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

from collections.abc import Mapping
from dataclasses import dataclass
from random import Random
from typing import Any, ClassVar

from .._distribution import (
    WeightedChoiceSet,
    cumulative_weights,
    prepare_distribution,
    validate_weights,
)
from .._proof import ProofResult
from .._transforms import TransformResult
from .base import Generator


@dataclass(frozen=True)
class WeightedSpec:
    weights: tuple[float, ...]
    cum_weights: tuple[float, ...]
    #: Populated for the legacy ``values`` form.
    values: tuple[str, ...] | None = None
    #: Populated for the composite ``choices`` form.
    distribution: WeightedChoiceSet | None = None


class WeightedGenerator(Generator):
    """Pick one alternative with probability proportional to its weight."""

    type_name = "weighted"
    is_composite: ClassVar[bool] = True

    def nested_types(self, spec: Mapping[str, Any]) -> tuple[str, ...]:
        return self._nested_type_names(spec.get("choices"))

    def prepare(self, spec: Mapping[str, Any]) -> WeightedSpec:
        # Composite specs require ``prepare_composite`` so they can
        # access the engine's registry; legacy specs are routed here
        # directly so callers that bypass the engine still work.
        if "choices" in spec:
            raise self._composite_path_error()
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
            cum_weights=distribution.cum_weights,
            distribution=distribution,
        )

    def generate(self, prepared: WeightedSpec, rng: Random) -> str:
        if prepared.distribution is not None:
            return prepared.distribution.choose(rng)
        # Legacy string-only form.
        return rng.choices(prepared.values, cum_weights=prepared.cum_weights, k=1)[0]  # type: ignore[arg-type]

    def prove(self, prepared: WeightedSpec, result: TransformResult) -> ProofResult:
        # Composite form recurses into the drawn child; the legacy string
        # form checks membership in the value pool (REL-001).
        if prepared.distribution is not None:
            if prepared.distribution.accepts(result):
                return ProofResult(ok=True)
            return ProofResult(ok=False, reason="no weighted choice accepts the value")
        if result.value in (prepared.values or ()):
            return ProofResult(ok=True)
        return ProofResult(ok=False, reason="value is not in weighted 'values'")

    def _prepare_legacy(self, spec: Mapping[str, Any]) -> WeightedSpec:
        values, weights = _coerce(spec)
        if not values:
            raise ValueError("weighted 'values' must be non-empty")
        validate_weights(weights, "weighted")
        return WeightedSpec(values=values, weights=weights, cum_weights=cumulative_weights(weights))


def _coerce(spec: Mapping[str, Any]) -> tuple[tuple[str, ...], tuple[float, ...]]:
    raw_values = spec.get("values")
    if not isinstance(raw_values, list):
        raise ValueError("weighted 'values' must be a list")
    if raw_values and isinstance(raw_values[0], dict):
        return _coerce_record(raw_values)
    return _coerce_parallel(spec, raw_values)


def _coerce_record(raw_values: list[Any]) -> tuple[tuple[str, ...], tuple[float, ...]]:
    # Record form: [{value, weight}, ...]. ``weight`` defaults to 1.0 so a
    # list of bare ``{"value": ...}`` records still works -- the generator
    # falls back to uniform weighting.
    values: list[str] = []
    weights: list[float] = []
    for index, item in enumerate(raw_values):
        if not isinstance(item, Mapping) or "value" not in item:
            raise ValueError(
                "weighted record values must be objects containing 'value' "
                f"(bad entry at index {index})"
            )
        values.append(str(item["value"]))
        weights.append(float(item.get("weight", 1.0)))
    return tuple(values), tuple(weights)


def _coerce_parallel(
    spec: Mapping[str, Any],
    raw_values: list[Any],
) -> tuple[tuple[str, ...], tuple[float, ...]]:
    # Parallel-array form. Missing ``weights`` defaults to uniform so
    # ``{"values": [...]}`` is equivalent to picking with equal probability
    # (1/N per entry).
    if "weights" not in spec:
        return (
            tuple(str(v) for v in raw_values),
            tuple(1.0 for _ in raw_values),
        )
    weights = spec["weights"]
    if not isinstance(weights, list) or len(weights) != len(raw_values):
        raise ValueError("weighted 'weights' must be a list the same length as 'values'")
    return (
        tuple(str(v) for v in raw_values),
        tuple(float(w) for w in weights),
    )


def _distribution_spec(spec: Mapping[str, Any]) -> dict[str, Any]:
    return {"type": "distribution", "choices": spec["choices"]}
