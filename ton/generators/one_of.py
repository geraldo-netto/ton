"""Uniform-choice composite generator (PAT-011).

Picks one of the nested specs with equal probability and renders it.
For non-uniform probabilities use ``weighted`` instead.

Spec::

    {
      "type":    "oneOf",
      "choices": [
        {"type": "string", "values": ["a", "b"]},
        {"type": "integer", "minValue": 0, "maxValue": 99,
         "padWithZero": false}
      ]
    }

Each entry in ``choices`` is itself a full type spec resolved against
the engine's registry, so any built-in or registered generator
(including another ``oneOf`` or ``weighted``) can be composed.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from random import Random
from typing import Any

from .._proof import ProofResult
from .._transforms import TransformResult
from .base import Generator, PreparationContext, drawn, prove_draws, proven_draws


@dataclass(frozen=True)
class OneOfSpec:
    children: tuple[tuple[Generator, Any], ...]


class OneOfGenerator(Generator):
    """Pick uniformly between several nested generators."""

    type_name = "oneOf"

    def nested_specs(self, spec: Mapping[str, Any]) -> tuple[tuple[str, Mapping[str, Any]], ...]:
        choices = spec.get("choices")
        if not isinstance(choices, list):
            return ()
        return tuple(
            (f"choices[{index}]", choice)
            for index, choice in enumerate(choices)
            if isinstance(choice, Mapping)
        )

    def prepare(
        self,
        spec: Mapping[str, Any],
        context: PreparationContext | None = None,
    ) -> OneOfSpec:
        if context is None:
            raise self._composite_path_error()
        raw = spec.get("choices")
        if not isinstance(raw, list) or not raw:
            raise ValueError("oneOf 'choices' must be a non-empty list")
        children = tuple(
            context.prepare_child("oneOf", f"'choices[{i}]'", entry) for i, entry in enumerate(raw)
        )
        return OneOfSpec(children=children)

    def generate(self, prepared: OneOfSpec, rng: Random) -> str:
        child_gen, child_prepared = rng.choice(prepared.children)
        return drawn(child_gen, child_prepared, child_gen.generate(child_prepared, rng))

    def prove(self, prepared: OneOfSpec, result: TransformResult) -> ProofResult:
        # Prove the branch that actually ran. Asking every child instead let a
        # permissive sibling mask the selected child's failure (REL-021).
        draws = proven_draws(result, prepared.children)
        if draws is not None:
            return prove_draws(draws, "oneOf choice")
        # A value TON did not draw here (external or re-derived): it is valid
        # if any choice accepts it; permissive children never false-fail.
        proofs = tuple(gen.prove(prep, result) for gen, prep in prepared.children)
        if any(proof.ok for proof in proofs):
            return ProofResult(ok=True)
        detail = next((proof.reason for proof in proofs if proof.reason), "")
        reason = "no oneOf choice accepts the value"
        return ProofResult(ok=False, reason=f"{reason}: {detail}" if detail else reason)
