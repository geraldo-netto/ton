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
from typing import Any, cast

from .._contracts import Generator, PreparationContext
from .._pipeline import drawn, prove_draws, proven_draws, public_value
from .._proof import ProofResult
from .._specpath import SpecPath
from .._steps import Call, Steps, cooperative, run_steps
from .._transforms import TransformResult


@dataclass(frozen=True)
class OneOfSpec:
    children: tuple[tuple[Generator, Any], ...]


class OneOfGenerator(Generator):
    """Pick uniformly between several nested generators."""

    type_name = "oneOf"
    config_keys = frozenset(("choices",))

    def nested_specs(
        self, spec: Mapping[str, Any]
    ) -> tuple[tuple[SpecPath, Mapping[str, Any]], ...]:
        choices = spec.get("choices")
        if not isinstance(choices, list):
            return ()
        return tuple(
            (("choices", index), choice)
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
            context.prepare_child("oneOf", ("choices", i), entry) for i, entry in enumerate(raw)
        )
        return OneOfSpec(children=children)

    @cooperative
    def generate(self, prepared: OneOfSpec, rng: Random) -> str:
        return public_value(run_steps(self, "generate", prepared, rng))

    def _generate_steps(self, prepared: OneOfSpec, rng: Random) -> Steps:
        child_gen, child_prepared = rng.choice(prepared.children)
        value = yield Call(child_gen, "generate", (child_prepared, rng))
        return drawn(child_gen, child_prepared, value, prepared)

    @cooperative
    def prove(self, prepared: OneOfSpec, result: TransformResult) -> ProofResult:
        return cast(ProofResult, run_steps(self, "prove", prepared, result))

    def _prove_steps(self, prepared: OneOfSpec, result: TransformResult) -> Steps:
        # Prove the branch that actually ran. Asking every child instead let a
        # permissive sibling mask the selected child's failure (REL-021).
        draws = proven_draws(result, prepared)
        if draws is not None:
            return (yield from prove_draws(draws, "oneOf choice"))
        # A value TON did not draw here (external or re-derived): it is valid
        # if any choice accepts it; permissive children never false-fail.
        proofs = []
        for gen, prep in prepared.children:
            proofs.append((yield Call(gen, "prove", (prep, result), proof_stage="source")))
        if any(proof.ok for proof in proofs):
            return ProofResult(ok=True)
        detail = next((proof.reason for proof in proofs if proof.reason), "")
        reason = "no oneOf choice accepts the value"
        return ProofResult(ok=False, reason=f"{reason}: {detail}" if detail else reason)
