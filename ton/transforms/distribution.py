"""Statistical distribution transform."""

from __future__ import annotations

from collections.abc import Mapping
from random import Random
from typing import Any, ClassVar

from .._distribution import WeightedChoiceSet, prepare_distribution
from .._transforms import BaseTransform, TransformCapabilities, TransformProof, TransformResult
from ..generators.base import PreparationContext


class DistributionTransform(BaseTransform):
    """Choose among two-or-more prepared candidate data types."""

    type_name: ClassVar[str] = "distribution"
    capabilities: ClassVar[TransformCapabilities] = TransformCapabilities()
    config_keys: ClassVar[frozenset[str] | None] = frozenset(("choices",))
    requires_source: ClassVar[bool] = False

    def nested_specs(
        self,
        spec: Mapping[str, Any],
    ) -> tuple[tuple[str, Mapping[str, Any]], ...]:
        choices = spec.get("choices")
        if not isinstance(choices, list):
            return ()
        return tuple(
            (f"choices[{index}].spec", choice["spec"])
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

    def apply(
        self,
        prepared: WeightedChoiceSet,
        value: TransformResult,
        rng: Random,
    ) -> TransformResult:
        del value
        return TransformResult(prepared.choose(rng))

    def prove(
        self,
        prepared: WeightedChoiceSet,
        before: TransformResult,
        after: TransformResult,
    ) -> TransformProof:
        # apply() discards the source value and emits a child draw, so the
        # emitted value -- not the source -- is what must be proven (REL-001).
        del before
        if prepared.accepts(after):
            return TransformProof(ok=True)
        detail = prepared.rejection(after)
        reason = "no distribution choice accepts the value"
        return TransformProof(ok=False, reason=f"{reason}: {detail}" if detail else reason)
