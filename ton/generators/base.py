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
from dataclasses import dataclass
from inspect import signature
from random import Random
from typing import Any, ClassVar

from .._proof import ProofResult
from .._transforms import TransformResult


@dataclass(frozen=True)
class PreparationContext:
    """Registry-aware services available while preparing a generator spec."""

    registry: Mapping[str, Generator]

    def prepare_child(
        self,
        parent_type: str,
        location: str,
        nested_spec: Any,
    ) -> tuple[Generator, Any]:
        return prepare_child_spec(parent_type, location, nested_spec, self.registry)

    def prepare_generator(self, generator: Generator, spec: Mapping[str, Any]) -> Any:
        """Prepare through the context while retaining legacy plugin compatibility."""
        if len(signature(generator.prepare).parameters) == 1:
            return generator.prepare(spec)
        return generator.prepare(spec, self)


class Generator(ABC):
    """Strategy interface: produce one string value from a prepared spec.

    Catalog registration treats an instance as a prototype and deep-copies
    it for each registry view. Generator state may therefore be Engine-local,
    but every attribute must support :func:`copy.deepcopy`.
    """

    #: JSON ``type`` discriminator handled by this generator.
    type_name: str = ""
    config_keys: ClassVar[frozenset[str] | None] = None

    #: True when the generator can return a (primary, id) pair within a row.
    #: The engine reads this flag instead of doing ``isinstance`` checks so
    #: third-party generators can opt in without subclassing a concrete type.
    is_paired: ClassVar[bool] = False

    #: Legacy composite marker retained for compatibility. New extensions
    #: accept ``PreparationContext`` in :meth:`prepare` instead.
    is_composite: ClassVar[bool] = False

    def prepare(
        self,
        spec: Mapping[str, Any],
        context: PreparationContext | None = None,
    ) -> Any:
        """Validate and pre-parse ``spec`` once per Engine construction.

        Override to return a typed value-object (a dataclass works well)
        so that :meth:`generate` becomes a pure draw + format step.
        The default passes the dict through, preserving the legacy
        contract for third-party generators that take a raw dict.

        Composite generators use ``context.prepare_child(...)`` to resolve
        nested specs through the same registry as their parent.
        """
        del context
        return spec

    def _composite_path_error(self) -> ValueError:
        """Return the standard "use the engine's composite path" error (DUP-003)."""
        return ValueError(
            f"{self.type_name!r} requires the engine's composite preparation path; "
            "build an Engine instead of calling prepare() directly"
        )

    def prepare_composite(
        self,
        spec: Mapping[str, Any],
        registry: Mapping[str, Generator],
    ) -> Any:
        """Composite hook: prepare ``spec`` with access to ``registry``.

        Default implementation delegates to :meth:`prepare` so non-
        composite generators stay unaffected. Set
        :attr:`is_composite` ``= True`` and override this method when
        the prepared spec needs to resolve nested type specs against
        the engine's registry (e.g. ``weighted`` composing other types).
        """
        del registry
        return self.prepare(spec)

    def nested_types(self, spec: Mapping[str, Any]) -> tuple[str, ...]:
        """Return direct child generator references declared by ``spec``.

        Composite extensions override this discovery hook so lazy registry
        construction does not need to infer generator references from
        arbitrary nested mappings.
        """
        names: list[str] = []
        for _location, nested_spec in self.nested_specs(spec):
            names.extend(self._nested_type_names(nested_spec))
        return tuple(names)

    def nested_specs(self, spec: Mapping[str, Any]) -> tuple[tuple[str, Mapping[str, Any]], ...]:
        """Return ``(location, spec)`` pairs owned as nested generators.

        Composite extensions override this hook to declare only their real
        generator-bearing config locations. Ordinary plugin metadata is not
        interpreted as a generator merely because it contains ``type``.
        """
        del spec
        return ()

    @staticmethod
    def _nested_type_names(specs: Any) -> tuple[str, ...]:
        """Collect type references below a composite-owned spec subtree."""
        names: list[str] = []
        values = specs if isinstance(specs, list) else [specs]
        for value in values:
            if not isinstance(value, Mapping):
                continue
            type_name = value.get("type")
            if isinstance(type_name, str):
                names.append(type_name)
            for nested in value.values():
                if isinstance(nested, (Mapping, list)):
                    names.extend(Generator._nested_type_names(nested))
        return tuple(names)

    @abstractmethod
    def generate(self, prepared: Any, rng: Random) -> str:
        """Return the generated value, using the prepared spec."""

    def prove(self, prepared: Any, result: TransformResult) -> ProofResult:
        """Return whether ``result`` satisfies ``prepared``.

        Generators that can cheaply check their output should override
        this. The default is permissive so existing third-party generators
        automatically participate in the proof-check protocol.
        """
        del prepared, result
        return ProofResult(ok=True)


def proof_result(ok: bool, reason: str) -> ProofResult:
    """Build a compact proof result with a reason only on failure."""
    return ProofResult(ok=ok, reason="" if ok else reason)


class PairedGenerator(Generator):
    """Generator that emits a pair of related values for a single row.

    Use this when ``$name$`` and ``$name[id]$`` in the template must
    refer to two facets of the same draw (canonical example: ``hash``
    -- ``$word$`` is the hash, ``$word[id]$`` is the plaintext).

    ``generate_pair`` returns ``(id_value, primary_value)``. The engine
    routes ``$name[id]$`` to ``id_value`` and ``$name$`` to
    ``primary_value`` -- that resolution is fixed at the engine level
    and does not depend on the class flags below.

    The single-valued shortcut path :meth:`generate` returns the
    primary by default. Subclasses that want the id half instead can
    flip :attr:`generate_returns_id` to True without overriding
    :meth:`generate` (ARCH-005).
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

    Common validator for string-pool, char, and hash generators.
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
    coercion that was repeated in five generators (string / char / hash /
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


_MISSING = object()


def _value_or_default(spec: Mapping[str, Any], key: str, type_name: str, default: Any) -> Any:
    if default is _MISSING:
        if key not in spec:
            raise ValueError(f"{type_name} {key!r} is required")
        return spec[key]
    return spec.get(key, default)


def coerce_int(
    spec: Mapping[str, Any],
    key: str,
    *,
    type_name: str,
    default: Any = _MISSING,
) -> int:
    """Read ``spec[key]`` and coerce to ``int`` with a uniform error message.

    When ``default`` is omitted the key is required; passing any value
    (including ``None``) treats it as optional. Used by integer / decimal
    / char / bytes / text / sequence / uuid generators so their per-field
    coercion + validation surface stays centralized (DUP-006).
    """
    raw = _value_or_default(spec, key, type_name, default)
    if isinstance(raw, bool):
        raise ValueError(f"{type_name} {key!r} must be an integer (got {raw!r})")
    if isinstance(raw, int):
        return raw
    if isinstance(raw, float):
        if raw.is_integer():
            return int(raw)
        raise ValueError(f"{type_name} {key!r} must be an integer (got {raw!r})")
    try:
        return int(raw)
    except (TypeError, ValueError) as exc:
        raise ValueError(f"{type_name} {key!r} must be an integer (got {raw!r})") from exc


def coerce_string(
    spec: Mapping[str, Any],
    key: str,
    *,
    type_name: str,
    default: Any = _MISSING,
) -> str:
    """Read ``spec[key]`` and coerce it to ``str`` with uniform missing-key errors."""
    return str(_value_or_default(spec, key, type_name, default))


def coerce_bool(
    spec: Mapping[str, Any],
    key: str,
    *,
    type_name: str,
    default: Any = _MISSING,
) -> bool:
    """Read a JSON boolean without treating non-empty strings as true."""
    raw = _value_or_default(spec, key, type_name, default)
    if not isinstance(raw, bool):
        raise ValueError(f"{type_name} {key!r} must be a boolean (got {raw!r})")
    return raw


def require_min_le_max(type_name: str, lo: Any, hi: Any) -> None:
    """Raise when ``hi < lo``. Centralizes the bounds check used by the
    integer / decimal / date / timestamp_unix generators (DUP-004).
    """
    if hi < lo:
        raise ValueError(f"{type_name} 'maxValue' ({hi}) must be >= 'minValue' ({lo})")


def prepare_child_spec(
    parent_type: str,
    location: str,
    nested_spec: Any,
    registry: Mapping[str, Generator],
) -> tuple[Generator, Any]:
    """Resolve a nested type spec through ``registry`` for composite parents.

    Shared by every :class:`Generator` whose prepared form embeds another
    generator (``weighted``, ``oneOf``, ``sequence_of`` -- PAT-011).
    Returns the ``(generator, prepared)`` pair so the parent can call
    ``generator.generate(prepared, rng)`` at row time.

    Raises ``ValueError`` if ``nested_spec`` is malformed, references an
    unknown type, or names a paired generator (which would silently
    lose its ``[id]`` half once nested -- REL-019).
    """
    if not isinstance(nested_spec, Mapping) or "type" not in nested_spec:
        raise ValueError(f"{parent_type} {location} must be an object with a 'type' field")
    from .._registry import resolve_reference

    nested_type = str(nested_spec["type"])
    child = resolve_reference(registry, nested_type)
    if child is None:
        raise ValueError(f"{parent_type} {location} references unknown type {nested_type!r}")
    if child.is_paired:
        raise ValueError(
            f"{parent_type} {location} uses paired type {nested_type!r}; "
            "paired generators cannot be nested inside a composite generator "
            "(the [id] half would be unreachable)"
        )
    context = PreparationContext(registry)
    return child, context.prepare_generator(child, nested_spec)
