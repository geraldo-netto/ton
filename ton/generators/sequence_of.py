"""Fixed-count composite generator (PAT-011).

Concatenates ``count`` independent draws from a single child generator,
joined by an optional ``separator``. Useful for compound identifiers
(e.g. four hex octets), comma-separated lists, repeat counts that don't
fit cleanly into the ``regex`` generator's quantifier surface, etc.

Spec::

    {
      "type":      "sequence_of",
      "count":     4,
      "separator": "-",
      "spec":      {"type": "integer", "minValue": 0, "maxValue": 9,
                    "padWithZero": false}
    }

``count`` is operator-controlled and has no implicit workload ceiling.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from random import Random
from typing import Any, ClassVar

from .._proof import ProofResult
from .._transforms import TransformResult
from .base import (
    Generator,
    PreparationContext,
    coerce_int,
)


@dataclass(frozen=True)
class SequenceOfSpec:
    count: int
    separator: str
    child: tuple[Generator, Any]


class SequenceOfGenerator(Generator):
    """Concatenate ``count`` independent draws from a single child generator."""

    type_name = "sequence_of"
    is_composite: ClassVar[bool] = True

    def nested_specs(self, spec: Mapping[str, Any]) -> tuple[tuple[str, Mapping[str, Any]], ...]:
        child = spec.get("spec")
        return (("spec", child),) if isinstance(child, Mapping) else ()

    def prepare(
        self,
        spec: Mapping[str, Any],
        context: PreparationContext | None = None,
    ) -> SequenceOfSpec:
        if context is None:
            raise self._composite_path_error()
        return self._prepare(spec, context)

    def prepare_composite(
        self,
        spec: Mapping[str, Any],
        registry: Mapping[str, Generator],
    ) -> SequenceOfSpec:
        return self._prepare(spec, PreparationContext(registry))

    def _prepare(self, spec: Mapping[str, Any], context: PreparationContext) -> SequenceOfSpec:
        count = coerce_int(spec, "count", type_name="sequence_of")
        if count < 1:
            raise ValueError("sequence_of 'count' must be >= 1")
        separator = spec.get("separator", "")
        if not isinstance(separator, str):
            raise ValueError("sequence_of 'separator' must be a string")
        child = context.prepare_child("sequence_of", "'spec'", spec.get("spec"))
        return SequenceOfSpec(count=count, separator=separator, child=child)

    def generate(self, prepared: SequenceOfSpec, rng: Random) -> str:
        child_gen, child_prepared = prepared.child
        return prepared.separator.join(
            child_gen.generate(child_prepared, rng) for _ in range(prepared.count)
        )

    def prove(self, prepared: SequenceOfSpec, result: TransformResult) -> ProofResult:
        # Recurse into the child for each element (REL-001). Only attempt
        # this when a non-empty separator lets us split unambiguously into
        # exactly ``count`` parts; otherwise stay permissive rather than
        # risk a false failure on a separator that also occurs in output.
        child_gen, child_prepared = prepared.child
        if not prepared.separator:
            return ProofResult(ok=True)
        parts = result.value.split(prepared.separator)
        if len(parts) != prepared.count:
            return ProofResult(ok=True)
        for part in parts:
            proof = child_gen.prove(child_prepared, TransformResult(part))
            if not proof.ok:
                return ProofResult(ok=False, reason=f"sequence_of element failed: {proof.reason}")
        return ProofResult(ok=True)
