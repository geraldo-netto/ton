"""Weighted-choice value generator.

Picks one of several alternatives with probability proportional to its
weight. ``weight`` is optional and defaults to 1.0, so a choices list
without weights samples uniformly (1/N per entry)::

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
can be composed. Use ``{"type": "string", "values": [...]}`` children to
weight plain strings.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from random import Random
from typing import Any

from .._distribution import (
    WeightedChoiceSet,
    prepare_distribution,
)
from .._proof import ProofResult
from .._transforms import TransformResult
from .base import Generator, PreparationContext


@dataclass(frozen=True)
class WeightedSpec:
    weights: tuple[float, ...]
    cum_weights: tuple[float, ...]
    distribution: WeightedChoiceSet


class WeightedGenerator(Generator):
    """Pick one alternative with probability proportional to its weight."""

    type_name = "weighted"

    def nested_specs(self, spec: Mapping[str, Any]) -> tuple[tuple[str, Mapping[str, Any]], ...]:
        choices = spec.get("choices")
        if not isinstance(choices, list):
            return ()
        nested: list[tuple[str, Mapping[str, Any]]] = []
        for index, choice in enumerate(choices):
            if isinstance(choice, Mapping) and isinstance(choice.get("spec"), Mapping):
                nested.append((f"choices[{index}].spec", choice["spec"]))
        return tuple(nested)

    def prepare(
        self,
        spec: Mapping[str, Any],
        context: PreparationContext | None = None,
    ) -> WeightedSpec:
        if context is None:
            raise self._composite_path_error()
        distribution = prepare_distribution(
            _distribution_spec(spec),
            context.registry,
            label="weighted",
            min_choices=1,
            context=context,
        )
        return WeightedSpec(
            weights=distribution.weights,
            cum_weights=distribution.cum_weights,
            distribution=distribution,
        )

    def generate(self, prepared: WeightedSpec, rng: Random) -> str:
        return prepared.distribution.choose(rng)

    def prove(self, prepared: WeightedSpec, result: TransformResult) -> ProofResult:
        # Recurse into the child that was drawn (REL-001, REL-022).
        proof = prepared.distribution.prove(result)
        if proof.ok:
            return ProofResult(ok=True)
        detail = proof.reason
        reason = "no weighted choice accepts the value"
        return ProofResult(ok=False, reason=f"{reason}: {detail}" if detail else reason)


def _distribution_spec(spec: Mapping[str, Any]) -> dict[str, Any]:
    return {"type": "distribution", "choices": spec["choices"]}
