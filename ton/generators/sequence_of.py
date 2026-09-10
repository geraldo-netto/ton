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
from typing import Any, cast

from .._proof import ProofResult, _trace_enabled
from .._specpath import SpecPath
from .._steps import Call, Steps, cooperative, run_steps
from .._transforms import TransformResult
from .base import (
    ChildDraw,
    DrawnValue,
    Generator,
    PreparationContext,
    coerce_int,
    prove_draws,
    proven_draws,
)


@dataclass(frozen=True)
class SequenceOfSpec:
    count: int
    separator: str
    child: tuple[Generator, Any]


class SequenceOfGenerator(Generator):
    """Concatenate ``count`` independent draws from a single child generator."""

    type_name = "sequence_of"

    def nested_specs(
        self, spec: Mapping[str, Any]
    ) -> tuple[tuple[SpecPath, Mapping[str, Any]], ...]:
        child = spec.get("spec")
        return ((("spec",), child),) if isinstance(child, Mapping) else ()

    def prepare(
        self,
        spec: Mapping[str, Any],
        context: PreparationContext | None = None,
    ) -> SequenceOfSpec:
        if context is None:
            raise self._composite_path_error()
        count = coerce_int(spec, "count", type_name="sequence_of")
        if count < 1:
            raise ValueError("sequence_of 'count' must be >= 1")
        separator = spec.get("separator", "")
        if not isinstance(separator, str):
            raise ValueError("sequence_of 'separator' must be a string")
        child = context.prepare_child("sequence_of", ("spec",), spec.get("spec"))
        return SequenceOfSpec(count=count, separator=separator, child=child)

    @cooperative
    def generate(self, prepared: SequenceOfSpec, rng: Random) -> str:
        return cast(str, run_steps(self, "generate", prepared, rng))

    def _generate_steps(self, prepared: SequenceOfSpec, rng: Random) -> Steps:
        child_gen, child_prepared = prepared.child
        parts = []
        for _ in range(prepared.count):
            parts.append((yield Call(child_gen, "generate", (child_prepared, rng))))
        if not _trace_enabled.get():
            return prepared.separator.join(parts)
        # Keep every element's own draw: joining into plain text dropped the
        # children's proof context, so a rejecting child passed (REL-023).
        return DrawnValue(
            prepared.separator.join(parts),
            tuple(ChildDraw(child_gen, child_prepared, part) for part in parts),
            prepared,
        )

    @cooperative
    def prove(self, prepared: SequenceOfSpec, result: TransformResult) -> ProofResult:
        return cast(ProofResult, run_steps(self, "prove", prepared, result))

    def _prove_steps(self, prepared: SequenceOfSpec, result: TransformResult) -> Steps:
        # Elements TON generated carry their own draws, so every element is
        # proven even with an empty or ambiguous separator (REL-023).
        draws = proven_draws(result, prepared)
        if draws is not None:
            return (yield from prove_draws(draws, "sequence_of element"))
        # A value TON did not generate here can only be split heuristically:
        # attempt it when a non-empty separator yields exactly ``count`` parts,
        # otherwise stay permissive rather than risk a false failure.
        child_gen, child_prepared = prepared.child
        if not prepared.separator:
            return ProofResult(ok=True)
        parts = result.value.split(prepared.separator)
        if len(parts) != prepared.count:
            return ProofResult(ok=True)
        for part in parts:
            proof = yield Call(child_gen, "prove", (child_prepared, TransformResult(part)))
            if not proof.ok:
                return ProofResult(ok=False, reason=f"sequence_of element failed: {proof.reason}")
        return ProofResult(ok=True)
