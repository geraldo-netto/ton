"""Weighted-choice value generator.

Like ``string`` but draws values with non-uniform probability so
realistic skewed distributions are possible. Two spec shapes are
accepted; pick whichever reads better in the config::

    # parallel arrays
    {
      "type":    "weighted",
      "values":  ["Intel", "AMD", "ARM"],
      "weights": [90, 8, 2]
    }

    # records
    {
      "type":   "weighted",
      "values": [
        {"value": "Intel", "weight": 90},
        {"value": "AMD",   "weight": 8},
        {"value": "ARM",   "weight": 2}
      ]
    }
"""

from __future__ import annotations

from dataclasses import dataclass
from random import Random
from typing import Any, Mapping, Sequence, Tuple

from .base import Generator


@dataclass(frozen=True)
class WeightedSpec:
    values: Tuple[str, ...]
    weights: Tuple[float, ...]


class WeightedGenerator(Generator):
    """Pick one of ``values`` with probability proportional to its weight."""

    type_name = "weighted"

    def prepare(self, spec: Mapping[str, Any]) -> WeightedSpec:
        values, weights = _coerce(spec)
        if not values:
            raise ValueError("weighted 'values' must be non-empty")
        if any(w < 0 for w in weights):
            raise ValueError("weighted 'weights' must be non-negative")
        if sum(weights) <= 0:
            raise ValueError("weighted 'weights' must sum to a positive number")
        return WeightedSpec(values=values, weights=weights)

    def generate(self, prepared: WeightedSpec, rng: Random) -> str:
        return rng.choices(prepared.values, weights=prepared.weights, k=1)[0]


def _coerce(spec: Mapping[str, Any]) -> Tuple[Tuple[str, ...], Tuple[float, ...]]:
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
