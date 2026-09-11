"""Validator extension point (PLUG-001).

A *validator* is a small post-generation check a config can attach to a
field: after the generator and any transforms produce the final value,
each referenced validator's :meth:`Validator.validate` runs against it and
a failure aborts generation with :class:`ValidationError`.

Validators are registered through :class:`ton._registry.ExtensionCatalog`
(``register_validator`` / the ``ton.validators`` entry-point group) and
referenced from a field spec's ``validators`` list.
"""

from __future__ import annotations

from collections.abc import Iterator
from contextlib import contextmanager
from contextvars import ContextVar
from typing import ClassVar, Protocol, runtime_checkable


class ValidationError(ValueError):
    """Raised when a generated value fails a configured validator."""


class ValidatorHookError(RuntimeError):
    """Carry validator attribution through nested generator/transform calls."""

    def __init__(self, reference: str, cause: Exception) -> None:
        self.reference = reference
        self.cause = cause
        super().__init__(str(cause))


class NonEmptyValidator:
    """Reference validator accepting values containing at least one character."""

    type_name = "non_empty"
    config_keys: ClassVar[frozenset[str] | None] = frozenset()

    def validate(self, value: str) -> bool:
        return bool(value)


@runtime_checkable
class Validator(Protocol):
    """Post-generation value check.

    Implementations expose a ``type_name`` discriminator and a
    :meth:`validate` returning ``True`` when ``value`` is acceptable.
    """

    type_name: str

    def validate(self, value: str) -> bool: ...


def validate_with_reference(validator: Validator, value: str) -> bool:
    """Preserve unexpected validator failures until the engine adds row context."""
    try:
        return validator.validate(value)
    except Exception as exc:
        raise ValidatorHookError(validator.type_name, exc) from exc


# Checked rows defer child validators until the enclosing field has been proved.
# A separate scope for every row isolates reentrant Engines and failure cleanup.
type _Validation = tuple[tuple[Validator, ...], str, str]
_pending: ContextVar[list[_Validation] | None] = ContextVar("ton_pending_validation", default=None)


@contextmanager
def validation_scope(checked: bool) -> Iterator[None]:
    token = _pending.set([] if checked else None)
    try:
        yield
    finally:
        _pending.reset(token)


def validate_pipeline(
    validators: tuple[Validator, ...], value: str, label: str, *, defer: bool = False
) -> None:
    """Validate after proof, queuing child checks only for a checked Engine row."""
    pending = _pending.get()
    if defer and pending is not None:
        if validators:
            pending.append((validators, value, label))
        return
    if pending:
        batches = tuple(pending)
        pending.clear()
        for batch in batches:
            _validate(*batch)
    _validate(validators, value, label)


def _validate(validators: tuple[Validator, ...], value: str, label: str) -> None:
    for validator in validators:
        if not validate_with_reference(validator, value):
            raise ValidationError(f"{label} failed validator {validator.type_name!r}")


@contextmanager
def validation_transaction() -> Iterator[None]:
    """Discard validators belonging to an abandoned child when a plugin recovers."""
    pending = _pending.get()
    start = len(pending) if pending is not None else 0
    try:
        yield
    except BaseException:
        if pending is not None:
            del pending[start:]
        raise
