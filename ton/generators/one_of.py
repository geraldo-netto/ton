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
from typing import Any, ClassVar

from .._proof import ProofResult
from .._transforms import TransformResult
from .base import Generator, PreparationContext, prepare_child_spec


@dataclass(frozen=True)
class OneOfSpec:
    children: tuple[tuple[Generator, Any], ...]


class OneOfGenerator(Generator):
    """Pick uniformly between several nested generators."""

    type_name = "oneOf"
    is_composite: ClassVar[bool] = True

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
        return self.prepare_composite(spec, context.registry)

    def prepare_composite(
        self,
        spec: Mapping[str, Any],
        registry: Mapping[str, Generator],
    ) -> OneOfSpec:
        raw = spec.get("choices")
        if not isinstance(raw, list) or not raw:
            raise ValueError("oneOf 'choices' must be a non-empty list")
        children = tuple(
            prepare_child_spec("oneOf", f"'choices[{i}]'", entry, registry)
            for i, entry in enumerate(raw)
        )
        return OneOfSpec(children=children)

    def generate(self, prepared: OneOfSpec, rng: Random) -> str:
        child_gen, child_prepared = rng.choice(prepared.children)
        return child_gen.generate(child_prepared, rng)

    def prove(self, prepared: OneOfSpec, result: TransformResult) -> ProofResult:
        # The value came from one child, so it fails only if no child
        # accepts it; permissive-default children never false-fail (REL-001).
        if any(gen.prove(prep, result).ok for gen, prep in prepared.children):
            return ProofResult(ok=True)
        return ProofResult(ok=False, reason="no oneOf choice accepts the value")
