"""Generator and preparation contracts, independent of catalogs and execution."""

from __future__ import annotations

from abc import ABC, abstractmethod
from collections.abc import Callable, Mapping
from dataclasses import dataclass, field
from random import Random
from typing import Any, ClassVar

from ._proof import ProofResult
from ._references import resolve_reference
from ._specpath import SpecLocation, SpecPath, format_spec_path
from ._transforms import TransformResult

ChildPreparer = Callable[
    ["PreparationContext", str, SpecPath, Any],
    tuple["Generator", Any],
]


@dataclass(frozen=True)
class PreparationContext:
    """Registry-aware services available while preparing a generator spec.

    ``path`` shares its ancestors. Iterate it (or use ``tuple(context.path)``)
    for components; append a relative tuple with ``+`` without copying ancestors.
    """

    registry: Mapping[str, Generator]
    child_preparer: ChildPreparer | None = None
    path: SpecLocation = field(default_factory=SpecLocation)

    def prepare_child(
        self,
        parent_type: str,
        location: SpecPath,
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

    Engine construction treats supplied instances as prototypes and deep-copies
    all extension kinds together. Mutable generator state is Engine-local;
    every attribute must support :func:`copy.deepcopy`.
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

    def nested_specs(
        self, spec: Mapping[str, Any]
    ) -> tuple[tuple[SpecPath, Mapping[str, Any]], ...]:
        """Return ``(location, spec)`` pairs owned as nested generators.

        Locations are tuples of literal mapping keys and list indices, such
        as ``("choices", 0, "spec")``. Pass the same location to prepare_child.
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


def prepare_child_spec(
    parent_type: str,
    location: SpecPath,
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
    parent_type: str, location: SpecPath, nested_spec: Any, registry: Mapping[str, Generator]
) -> Generator:
    """Resolve and validate a child before iterative preparation schedules it."""
    label = repr(format_spec_path(location))
    if not isinstance(nested_spec, Mapping) or "type" not in nested_spec:
        raise ValueError(f"{parent_type} {label} must be an object with a 'type' field")
    nested_type = str(nested_spec["type"])
    child = resolve_reference(registry, nested_type)
    if child is None:
        raise ValueError(f"{parent_type} {label} references unknown type {nested_type!r}")
    if child.is_paired:
        raise ValueError(
            f"{parent_type} {label} uses paired type {nested_type!r}; "
            "paired generators cannot be nested inside a composite generator "
            "(the [id] half would be unreachable)"
        )
    return child
