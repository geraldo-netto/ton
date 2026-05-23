"""Generator protocol, paired-generator role, and shared helpers.

Generators follow the **Strategy** pattern: each subclass owns exactly
one ``type`` discriminator and knows nothing about templates, configs,
or rows. The :mod:`ton.registry` module wires them together so the
engine can dispatch by ``type`` without import-time coupling.

Most types are *single-valued* (``generate`` returns one string).
Some types are *paired* and expose both a primary value and a secondary
("id") value within the same row -- see :class:`PairedGenerator`.

Two-phase contract
------------------

Generators have an *optional* preparation step that runs once when the
engine is constructed, plus the per-row ``generate`` call:

* ``prepare(spec_dict)`` -- validate the raw JSON dict and return a
  typed "prepared spec" (typically a dataclass). The engine caches the
  result and never re-parses the dict. Default implementation passes
  the dict through, so third-party generators that have not migrated
  to typed specs still work.
* ``generate(prepared, rng)`` -- the hot path. Receives whatever
  ``prepare`` returned. Built-in generators receive a typed dataclass
  so their runtime code is pure draw + format.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from collections.abc import Mapping
from random import Random
from typing import Any, ClassVar


class Generator(ABC):
    """Strategy interface: produce one string value from a (prepared) spec."""

    #: JSON ``type`` discriminator handled by this generator.
    type_name: str = ""

    #: True when the generator can return a (primary, id) pair within a row.
    #: The engine reads this flag instead of doing ``isinstance`` checks so
    #: third-party generators can opt in without subclassing a concrete type.
    is_paired: ClassVar[bool] = False

    def prepare(self, spec: Mapping[str, Any]) -> Any:
        """Validate and pre-parse ``spec`` once per Engine construction.

        Override to return a typed value-object (a dataclass works well)
        so that :meth:`generate` becomes a pure draw + format step.
        The default passes the dict through, preserving the legacy
        contract for third-party generators that take a raw dict.
        """
        return spec

    @abstractmethod
    def generate(self, prepared: Any, rng: Random) -> str:
        """Return the generated value, using the prepared spec."""


class PairedGenerator(Generator):
    """Generator that emits a pair of related values for a single row.

    Use this when ``$name$`` and ``$name[id]$`` in the template must
    refer to two facets of the same draw (canonical example: ``lmhash``
    -- ``$word$`` is the hash, ``$word[id]$`` is the plaintext).

    ``generate_pair`` returns ``(id_value, primary_value)``. The engine
    routes ``$name[id]$`` to ``id_value`` and ``$name$`` to
    ``primary_value`` -- that resolution is fixed at the engine level
    and does not depend on the class flags below.

    The single-valued shortcut path :meth:`generate` returns the
    primary by default. Subclasses that want the id half instead can
    flip :attr:`generate_returns_id` to True without overriding
    :meth:`generate` (TODO ARCH-005).
    """

    is_paired: ClassVar[bool] = True

    #: When True, the single-valued :meth:`generate` returns the first
    #: ("id") element of :meth:`generate_pair`; when False (default),
    #: it returns the second ("primary"). Set on the subclass.
    generate_returns_id: ClassVar[bool] = False

    @abstractmethod
    def generate_pair(self, prepared: Any, rng: Random) -> tuple[str, str]:
        """Return ``(id_value, primary_value)`` for the current row.

        ``id_value`` is what ``$name[id]$`` resolves to;
        ``primary_value`` is what ``$name$`` resolves to.
        """

    def generate(self, prepared: Any, rng: Random) -> str:
        """Single-valued shortcut.

        Returns ``primary_value`` by default; subclasses that prefer
        the id half flip :attr:`generate_returns_id`.
        """
        id_value, primary = self.generate_pair(prepared, rng)
        return id_value if self.generate_returns_id else primary


def pad_with_zero(value: str, width: int) -> str:
    """Left-pad ``value`` with zeros to ``width`` characters."""
    return value.zfill(width)


def require_non_empty_values(spec: Mapping[str, Any]) -> list[Any]:
    """Return ``spec['values']`` after asserting it is a non-empty list.

    Common validator for string-pool / char / lmhash generators.
    Raises ``ValueError`` (the config layer translates this to
    ``ConfigError``) so the failure happens at engine construction,
    not on the first row.
    """
    values = spec.get("values")
    if not isinstance(values, list) or not values:
        raise ValueError(
            "'values' must be a non-empty list (got: "
            f"{type(values).__name__ if values is not None else 'missing'})"
        )
    return values


def require_string_tuple(spec: Mapping[str, Any], key: str = "values") -> tuple[str, ...]:
    """Return ``spec[key]`` as a non-empty ``Tuple[str, ...]``.

    Combines the non-empty-list check with the ``tuple(str(v) for v in ...)``
    coercion that was repeated in five generators (string / char / lmhash /
    weighted / identity). Raises ``ValueError`` on a missing, non-list,
    or empty value.
    """
    raw = spec.get(key)
    if not isinstance(raw, list) or not raw:
        raise ValueError(
            f"{key!r} must be a non-empty list (got: "
            f"{type(raw).__name__ if raw is not None else 'missing'})"
        )
    return tuple(str(v) for v in raw)
