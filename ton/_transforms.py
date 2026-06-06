"""Transform contracts for post-generation value processing."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from random import Random
from typing import Any, ClassVar, Protocol, runtime_checkable


@dataclass(frozen=True)
class TransformCapabilities:
    """Declared input/output behavior for a transform."""

    accepts_paired: bool = False
    preserves_pairing: bool = False


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

    def prepare(self, spec: Mapping[str, Any]) -> Any:
        """Validate and normalize a raw transform spec."""

    def prepare_composite(
        self,
        spec: Mapping[str, Any],
        registry: Mapping[str, Any],
    ) -> Any:
        """Validate specs that need access to data-type registrations."""

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

    def prepare(self, spec: Mapping[str, Any]) -> Any:
        return spec

    def prepare_composite(
        self,
        spec: Mapping[str, Any],
        registry: Mapping[str, Any],
    ) -> Any:
        del registry
        return self.prepare(spec)

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
    capabilities: ClassVar[TransformCapabilities] = TransformCapabilities(
        accepts_paired=True,
        preserves_pairing=True,
    )
