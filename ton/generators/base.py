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

* ``prepare(spec_dict, context)`` -- validate the raw JSON dict and return a
  typed "prepared spec" (typically a dataclass). The engine caches the
  result and never re-parses the dict. Default implementation passes
  the dict through. Composite preparation resolves declared children
  through the supplied context.
* ``generate(prepared, rng)`` -- the hot path. Receives whatever
  ``prepare`` returned. Built-in generators receive a typed dataclass
  so their runtime code is pure draw + format.
"""

from __future__ import annotations

import re
from abc import ABC, abstractmethod
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from decimal import Decimal
from numbers import Rational
from random import Random
from typing import Any, ClassVar, cast

from .._proof import PreparedTransform, ProofResult, TransformStep, _trace_enabled
from .._steps import Call, Steps, cooperative, run_steps
from .._transforms import TransformResult
from .._validation import ValidationError

ChildPreparer = Callable[
    ["PreparationContext", str, str, Any],
    tuple["Generator", Any],
]


@dataclass(frozen=True)
class PreparationContext:
    """Registry-aware services available while preparing a generator spec."""

    registry: Mapping[str, Generator]
    child_preparer: ChildPreparer | None = None
    path: str = ""

    def prepare_child(
        self,
        parent_type: str,
        location: str,
        nested_spec: Any,
    ) -> tuple[Generator, Any]:
        if self.child_preparer is not None:
            return self.child_preparer(self, parent_type, location, nested_spec)
        return prepare_child_spec(parent_type, location, nested_spec, self.registry, self)

    def prepare_generator(self, generator: Generator, spec: Mapping[str, Any]) -> Any:
        """Prepare ``spec`` through this context's registry and services."""
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

    def prepare(
        self,
        spec: Mapping[str, Any],
        context: PreparationContext | None = None,
    ) -> Any:
        """Validate and pre-parse ``spec`` once per Engine construction.

        Override to return a typed value-object (a dataclass works well)
        so that :meth:`generate` becomes a pure draw + format step.
        The default passes the dict through unchanged.

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

    def nested_specs(self, spec: Mapping[str, Any]) -> tuple[tuple[str, Mapping[str, Any]], ...]:
        """Return ``(location, spec)`` pairs owned as nested generators.

        Composite extensions override this hook to declare only their real
        generator-bearing config locations. Ordinary plugin metadata is not
        interpreted as a generator merely because it contains ``type``.
        """
        del spec
        return ()

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


@dataclass(frozen=True)
class ChildDraw:
    """One child draw: the generator/prepared pair and the text it produced."""

    generator: Generator
    prepared: Any
    value: str


class DrawnValue(str):
    """Generated text tagged with the child draw(s) that produced it.

    Composite generators (``oneOf``, ``weighted``, ``sequence_of``) and the
    ``distribution`` transform pick one branch at row time but used to prove
    a value by asking *every* branch. A branch whose proof is permissive
    then masked the selected branch's failure (REL-021, REL-022, REL-023).
    Carrying the draws lets each composite prove exactly what ran.

    It subclasses ``str`` so the value stays an ordinary string everywhere
    else -- rendering, transforms, validators, and output are unaffected.
    """

    draws: tuple[ChildDraw, ...]
    owner: object

    def __new__(cls, value: str, draws: tuple[ChildDraw, ...], owner: object) -> DrawnValue:
        instance = super().__new__(cls, value)
        instance.draws = draws
        instance.owner = owner
        return instance

    def __getnewargs_ex__(self) -> tuple[tuple[Any, ...], dict[str, Any]]:
        return (str(self), self.draws, self.owner), {}


def drawn(generator: Generator, prepared: Any, value: str, owner: object) -> str:
    """Tag ``value`` with the single child draw that produced it."""
    if not _trace_enabled.get():
        return value
    return DrawnValue(value, (ChildDraw(generator, prepared, value),), owner)


def proven_draws(result: TransformResult, owner: object) -> tuple[ChildDraw, ...] | None:
    """Return draws belonging to this prepared composite in constant time (PERF-040).

    External or re-derived values retain the composite's ordinary fallback.
    Ownership is carried by the value, so pickle/deepcopy preserve the relationship.
    """
    value = result.value
    if not isinstance(value, DrawnValue) or value.owner is not owner:
        return None
    return value.draws


def prove_draws(draws: tuple[ChildDraw, ...], label: str) -> Steps:
    """Prove every recorded draw against the child that produced it."""
    for draw in draws:
        proof = yield Call(draw.generator, "prove", (draw.prepared, TransformResult(draw.value)))
        if not proof.ok:
            reason = f"{label} failed its own proof"
            return ProofResult(
                ok=False, reason=f"{reason}: {proof.reason}" if proof.reason else reason
            )
    return ProofResult(ok=True)


class _GeneratedChildValue(str):
    """String carrying the exact nested transform trace until proofing."""

    pipeline: ChildPipelineSpec
    source: TransformResult
    steps: tuple[TransformStep, ...]

    def __new__(
        cls,
        value: str,
        pipeline: ChildPipelineSpec,
        source: TransformResult,
        steps: tuple[TransformStep, ...],
    ) -> _GeneratedChildValue:
        instance = super().__new__(cls, value)
        instance.pipeline = pipeline
        instance.source = source
        instance.steps = steps
        return instance

    def __getnewargs_ex__(self) -> tuple[tuple[Any, ...], dict[str, Any]]:
        return (str(self), self.pipeline, self.source, self.steps), {}


@dataclass(frozen=True)
class ChildPipelineSpec:
    """Prepared source and transform stages for one composite child."""

    generator: Generator
    source_prepared: Any
    transforms: tuple[PreparedTransform, ...]
    uses_source: bool
    validators: tuple[Any, ...] = ()


class ChildPipelineGenerator(Generator):
    """Adapt a nested field pipeline to the existing generator protocol."""

    type_name = "child_pipeline"

    @cooperative
    def generate(self, prepared: ChildPipelineSpec, rng: Random) -> str:
        return cast(str, run_steps(self, "generate", prepared, rng))

    def _generate_steps(self, prepared: ChildPipelineSpec, rng: Random) -> Steps:
        source = TransformResult(
            (yield Call(prepared.generator, "generate", (prepared.source_prepared, rng)))
            if prepared.uses_source
            else ""
        )
        result = source
        steps: list[TransformStep] | None = [] if _trace_enabled.get() else None
        for transform in prepared.transforms:
            before = result
            result = yield Call(transform.transform, "apply", (transform.prepared, before, rng))
            if steps is not None:
                steps.append(TransformStep(transform, before, result))
        for validator in prepared.validators:
            if not validator.validate(result.value):
                raise ValidationError(f"Nested value failed validator {validator.type_name!r}")
        if steps is None:
            return result.value
        return _GeneratedChildValue(result.value, prepared, source, tuple(steps))

    @cooperative
    def prove(self, prepared: ChildPipelineSpec, result: TransformResult) -> ProofResult:
        return cast(ProofResult, run_steps(self, "prove", prepared, result))

    def _prove_steps(self, prepared: ChildPipelineSpec, result: TransformResult) -> Steps:
        value = result.value
        if not isinstance(value, _GeneratedChildValue) or value.pipeline is not prepared:
            return ProofResult(ok=True)
        if prepared.uses_source:
            source_proof = yield Call(
                prepared.generator, "prove", (prepared.source_prepared, value.source)
            )
            if not source_proof.ok:
                return source_proof
        for step in value.steps:
            proof = yield Call(
                step.prepared.transform, "prove", (step.prepared.prepared, step.before, step.after)
            )
            if not proof.ok:
                return ProofResult(ok=False, reason=proof.reason)
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


#: Shape of a plain decimal integer, used to keep :func:`str_to_int` as
#: strict as ``int`` when it falls back to the arbitrary-size path.
_INTEGER_TEXT = re.compile(r"[+-]?\d+")


def int_to_str(value: int) -> str:
    """Render ``value`` in decimal, whatever its size.

    CPython refuses ``str()`` on integers over ``sys.get_int_max_str_digits()``
    (4,300 by default). TON has no digit ceiling, so oversized values fall back
    to an exact ``Decimal`` rendering instead of failing or requiring a
    process-global setting change (SCALE-005). The fast path is unchanged.
    """
    try:
        return str(value)
    except ValueError:
        return format(Decimal(value), "f")


def str_to_int(text: str) -> int:
    """Parse a decimal integer of any size, as strictly as ``int``."""
    try:
        return int(text)
    except ValueError:
        if not _INTEGER_TEXT.fullmatch(text.strip()):
            raise
        return int(Decimal(text))


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
    if isinstance(raw, Rational):
        if raw.denominator == 1:
            return int(raw.numerator)
        raise ValueError(f"{type_name} {key!r} must be an integer (got {raw!r})")
    # Check Decimal exactly before int() can truncate it (CFG-024).
    if isinstance(raw, Decimal) and (not raw.is_finite() or raw != raw.to_integral_value()):
        raise ValueError(f"{type_name} {key!r} must be an integer (got {raw!r})")
    if isinstance(raw, float):
        if raw.is_integer():
            return int(raw)
        raise ValueError(f"{type_name} {key!r} must be an integer (got {raw!r})")
    try:
        return str_to_int(raw) if isinstance(raw, str) else int(raw)
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
    context: PreparationContext | None = None,
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
    child = resolve_child_spec(parent_type, location, nested_spec, registry)
    preparation = context or PreparationContext(registry)
    return child, preparation.prepare_generator(child, nested_spec)


def resolve_child_spec(
    parent_type: str, location: str, nested_spec: Any, registry: Mapping[str, Generator]
) -> Generator:
    """Resolve and validate a child before iterative preparation schedules it."""
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
    return child
