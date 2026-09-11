"""Statistical distribution transform."""

from __future__ import annotations

from collections.abc import Mapping
from random import Random
from typing import Any, ClassVar, cast

from .._contracts import PreparationContext
from .._distribution import WeightedChoiceSet, prepare_distribution
from .._pipeline import as_result, public_result
from .._specpath import SpecPath
from .._steps import Call, Steps, cooperative, run_steps
from .._transforms import BaseTransform, TransformCapabilities, TransformProof, TransformResult


class DistributionTransform(BaseTransform):
    """Choose among two-or-more prepared candidate data types."""

    type_name: ClassVar[str] = "distribution"
    capabilities: ClassVar[TransformCapabilities] = TransformCapabilities()
    config_keys: ClassVar[frozenset[str] | None] = frozenset(("choices",))
    requires_source: ClassVar[bool] = False

    def nested_specs(
        self,
        spec: Mapping[str, Any],
    ) -> tuple[tuple[SpecPath, Mapping[str, Any]], ...]:
        choices = spec.get("choices")
        if not isinstance(choices, list):
            return ()
        return tuple(
            (("choices", index, "spec"), choice["spec"])
            for index, choice in enumerate(choices)
            if isinstance(choice, Mapping) and isinstance(choice.get("spec"), Mapping)
        )

    def prepare(
        self,
        spec: Mapping[str, Any],
        context: PreparationContext,
    ) -> WeightedChoiceSet:
        return prepare_distribution(
            spec,
            context.registry,
            label="distribution",
            min_choices=2,
            context=context,
        )

    @cooperative
    def apply(
        self,
        prepared: WeightedChoiceSet,
        value: TransformResult,
        rng: Random,
    ) -> TransformResult:
        return public_result(run_steps(self, "apply", prepared, value, rng))

    def _apply_steps(
        self, prepared: WeightedChoiceSet, value: TransformResult, rng: Random
    ) -> Steps:
        return as_result((yield Call(prepared, "choose", (rng,))))

    @cooperative
    def prove(
        self,
        prepared: WeightedChoiceSet,
        before: TransformResult,
        after: TransformResult,
    ) -> TransformProof:
        return cast(TransformProof, run_steps(self, "prove", prepared, before, after))

    def _prove_steps(
        self, prepared: WeightedChoiceSet, before: TransformResult, after: TransformResult
    ) -> Steps:
        # apply() discards the source value and emits a child draw, so the
        # emitted value -- not the source -- is what must be proven (REL-001).
        del before
        proof = yield Call(prepared, "prove", (after,))
        if proof.ok:
            return TransformProof(ok=True)
        detail = proof.reason
        reason = "no distribution choice accepts the value"
        return TransformProof(ok=False, reason=f"{reason}: {detail}" if detail else reason)
