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

from typing import ClassVar, Protocol, runtime_checkable


class ValidationError(ValueError):
    """Raised when a generated value fails a configured validator."""


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
