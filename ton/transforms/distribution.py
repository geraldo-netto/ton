"""Statistical distribution transform."""

from __future__ import annotations

from collections.abc import Mapping
from random import Random
from typing import Any, ClassVar

from .._distribution import WeightedChoiceSet, prepare_distribution
from .._transforms import BaseTransform, TransformCapabilities, TransformProof, TransformResult
from ..generators import Generator


class DistributionTransform(BaseTransform):
    """Choose among two-or-more prepared candidate data types."""

    type_name: ClassVar[str] = "distribution"
    capabilities: ClassVar[TransformCapabilities] = TransformCapabilities()
    config_keys: ClassVar[frozenset[str] | None] = frozenset(("choices",))

    def prepare_composite(
        self,
        spec: Mapping[str, Any],
        registry: Mapping[str, Generator],
    ) -> WeightedChoiceSet:
        return prepare_distribution(
            spec,
            registry,
            label="distribution",
            min_choices=2,
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
        return TransformProof(ok=False, reason="no distribution choice accepts the value")
