"""Transform contracts for post-generation value processing."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from random import Random
from typing import Any, ClassVar, Protocol, runtime_checkable

from ._specpath import SpecPath


@dataclass(frozen=True)
class TransformCapabilities:
    """Declared input/output behavior for a transform."""

    accepts_paired: bool = False
    preserves_pairing: bool = False


@dataclass(frozen=True)
class PairedCapabilityResult:
    """Result of folding a transform chain's paired-value capabilities."""

    preserves_pairing: bool
    incompatible_index: int | None = None


def fold_paired_capabilities(
    starts_paired: bool,
    capabilities: Sequence[TransformCapabilities],
) -> PairedCapabilityResult:
    """Check paired-input compatibility and fold pairing preservation."""
    is_paired = starts_paired
    for index, capability in enumerate(capabilities):
        if is_paired and not capability.accepts_paired:
            return PairedCapabilityResult(False, index)
        is_paired = is_paired and capability.preserves_pairing
    return PairedCapabilityResult(is_paired)


@dataclass(frozen=True)
class TransformResult:
    """Value returned by a transform stage."""

    value: str
    id_value: str | None = None

    @property
    def is_paired(self) -> bool:
        return self.id_value is not None


@dataclass(frozen=True)
class TransformProof:
    """Proof-check result for one transform stage."""

    ok: bool
    reason: str = ""


@runtime_checkable
class Transform(Protocol):
    """Protocol implemented by value transforms.

    A transform prepares its config once, receives generated values at row
    time, and can prove whether an output value satisfies its prepared config.
    """

    type_name: ClassVar[str]
    capabilities: ClassVar[TransformCapabilities]
    config_keys: ClassVar[frozenset[str] | None]
    requires_source: ClassVar[bool]

    def nested_specs(
        self,
        spec: Mapping[str, Any],
    ) -> tuple[tuple[SpecPath, Mapping[str, Any]], ...]:
        """Declare generator-bearing config locations for lazy discovery."""
        raise NotImplementedError  # pragma: no cover

    def prepare(self, spec: Mapping[str, Any], context: Any) -> Any:
        """Validate and normalize a raw transform spec.

        ``context`` is the engine's :class:`PreparationContext`; composite
        transforms resolve nested type specs with ``context.prepare_child``
        so children get the same registry and pipeline services as the
        parent field (REL-020).
        """

    def apply(
        self,
        prepared: Any,
        value: TransformResult,
        rng: Random,
    ) -> TransformResult:
        """Return the transformed value."""
        raise NotImplementedError  # pragma: no cover

    def prove(
        self,
        prepared: Any,
        before: TransformResult,
        after: TransformResult,
    ) -> TransformProof:
        """Return whether ``after`` is valid for ``before`` and ``prepared``."""
        raise NotImplementedError  # pragma: no cover


class BaseTransform:
    """Small base class for transforms that only need defaults."""

    type_name: ClassVar[str] = ""
    capabilities: ClassVar[TransformCapabilities] = TransformCapabilities()
    config_keys: ClassVar[frozenset[str] | None] = None
    requires_source: ClassVar[bool] = True

    def nested_specs(
        self,
        spec: Mapping[str, Any],
    ) -> tuple[tuple[SpecPath, Mapping[str, Any]], ...]:
        """Declare generator-bearing config locations for lazy discovery."""
        del spec
        return ()

    def prepare(self, spec: Mapping[str, Any], context: Any) -> Any:
        del context
        return spec

    def apply(
        self,
        prepared: Any,
        value: TransformResult,
        rng: Random,
    ) -> TransformResult:
        del prepared, rng
        return value

    def prove(
        self,
        prepared: Any,
        before: TransformResult,
        after: TransformResult,
    ) -> TransformProof:
        del prepared, before, after
        return TransformProof(ok=True)


class IdentityTransform(BaseTransform):
    """Built-in transform that returns values unchanged."""

    type_name: ClassVar[str] = "identity"
    config_keys: ClassVar[frozenset[str] | None] = frozenset()
    capabilities: ClassVar[TransformCapabilities] = TransformCapabilities(
        accepts_paired=True,
        preserves_pairing=True,
    )
