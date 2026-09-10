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
from fractions import Fraction
from random import Random
from typing import Any, cast

from .._contracts import Generator, PreparationContext
from .._distribution import (
    WeightedChoiceSet,
    prepare_distribution,
)
from .._proof import ProofResult
from .._specpath import SpecPath
from .._steps import Call, Steps, cooperative, run_steps
from .._transforms import TransformResult


@dataclass(frozen=True)
class WeightedSpec:
    weights: tuple[Fraction, ...]
    cum_weights: tuple[int, ...]
    distribution: WeightedChoiceSet


class WeightedGenerator(Generator):
    """Pick one alternative with probability proportional to its weight."""

    type_name = "weighted"
    config_keys = frozenset(("choices",))

    def nested_specs(
        self, spec: Mapping[str, Any]
    ) -> tuple[tuple[SpecPath, Mapping[str, Any]], ...]:
        choices = spec.get("choices")
        if not isinstance(choices, list):
            return ()
        nested: list[tuple[SpecPath, Mapping[str, Any]]] = []
        for index, choice in enumerate(choices):
            if isinstance(choice, Mapping) and isinstance(choice.get("spec"), Mapping):
                nested.append((("choices", index, "spec"), choice["spec"]))
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

    @cooperative
    def generate(self, prepared: WeightedSpec, rng: Random) -> str:
        return cast(str, run_steps(self, "generate", prepared, rng))

    def _generate_steps(self, prepared: WeightedSpec, rng: Random) -> Steps:
        return (yield Call(prepared.distribution, "choose", (rng,)))

    @cooperative
    def prove(self, prepared: WeightedSpec, result: TransformResult) -> ProofResult:
        return cast(ProofResult, run_steps(self, "prove", prepared, result))

    def _prove_steps(self, prepared: WeightedSpec, result: TransformResult) -> Steps:
        # Recurse into the child that was drawn (REL-001, REL-022).
        proof = yield Call(prepared.distribution, "prove", (result,))
        if proof.ok:
            return ProofResult(ok=True)
        detail = proof.reason
        reason = "no weighted choice accepts the value"
        return ProofResult(ok=False, reason=f"{reason}: {detail}" if detail else reason)


def _distribution_spec(spec: Mapping[str, Any]) -> dict[str, Any]:
    return {"type": "distribution", "choices": spec["choices"]}
