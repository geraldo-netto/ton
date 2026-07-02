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

from .base import Generator, prepare_child_spec


@dataclass(frozen=True)
class OneOfSpec:
    children: tuple[tuple[Generator, Any], ...]


class OneOfGenerator(Generator):
    """Pick uniformly between several nested generators."""

    type_name = "oneOf"
    is_composite: ClassVar[bool] = True

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
