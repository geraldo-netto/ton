"""Registry mapping JSON ``type`` discriminators to Generator instances.

The default registry is *auto-discovered* (TODO DUP-003): we walk the
``Generator`` subclass tree after :mod:`ton.generators` has imported
every submodule and instantiate each concrete leaf with a non-empty
``type_name``. Adding a new built-in is now a two-touchpoint change
(create the module, import it from ``ton.generators.__init__``)
instead of the previous four (module, import, ``__all__`` entry, and
a separate line in this module's hand-maintained list).
"""

from __future__ import annotations

import inspect
from collections.abc import Iterator
from importlib.metadata import entry_points

from ._logging import logger as _logger

# Importing ``ton.generators`` imports every concrete-generator submodule,
# which is what populates Generator.__subclasses__() below.
from .generators import Generator

#: Entry-point group third-party packages publish to expose a Generator
#: class. The entry-point *name* becomes the JSON ``type`` discriminator;
#: the loaded object must be a callable returning a Generator (typically
#: the Generator subclass itself).
ENTRY_POINT_GROUP = "ton.generators"


def discover_generator_classes() -> list[type[Generator]]:
    """Return every concrete :class:`Generator` subclass with a ``type_name``.

    Walks the full subclass tree so future intermediate roles
    (e.g. ``PairedGenerator`` or third-party mixins) are followed.
    """
    # ``Generator`` itself is abstract; mypy --strict flags passing it to a
    # parameter typed ``type[Generator]``. The walk only ever yields
    # subclasses, so the call site is safe.
    return [cls for cls in _walk_subclasses(Generator)  # type: ignore[type-abstract]
            if not inspect.isabstract(cls) and cls.type_name]


def _walk_subclasses(root: type[Generator]) -> Iterator[type[Generator]]:
    seen: set[type[Generator]] = set()
    stack: list[type[Generator]] = list(root.__subclasses__())
    while stack:
        cls = stack.pop()
        if cls in seen:
            continue
        seen.add(cls)
        yield cls
        stack.extend(cls.__subclasses__())


#: Process-wide cache of the discovered generator classes. Populated
#: lazily on first call to :func:`default_registry`. The subclass walk
#: + ``inspect.isabstract`` filter runs once per process instead of on
#: every Engine construction (TODO PERF-008).
_DEFAULT_CLASSES: tuple[type[Generator], ...] = ()


def clear_default_registry_cache() -> None:
    """Force the next :func:`default_registry` call to re-discover classes.

    Useful after a test or third-party plugin has registered a new
    ``Generator`` subclass and wants it picked up by the default
    registry.
    """
    global _DEFAULT_CLASSES
    _DEFAULT_CLASSES = ()


def default_registry() -> dict[str, Generator]:
    """Return a fresh registry containing all built-in generators.

    The discovered class list is cached at module scope, but each call
    still constructs a new dict of fresh instances so per-spec state
    (e.g. :class:`ton.generators.sequence.SequenceGenerator` counters)
    stays Engine-scoped.
    """
    global _DEFAULT_CLASSES
    if not _DEFAULT_CLASSES:
        _DEFAULT_CLASSES = tuple(discover_generator_classes())
        _logger.info(
            "registry_discovered generators=%d",
            len(_DEFAULT_CLASSES),
            extra={
                "event": "registry_discovered",
                "generators": len(_DEFAULT_CLASSES),
                "names": sorted(cls.type_name for cls in _DEFAULT_CLASSES),
            },
        )
    return {cls.type_name: cls() for cls in _DEFAULT_CLASSES}


def registry_with_entry_points() -> dict[str, Generator]:
    """Return the built-in registry merged with entry-point generators.

    Third-party packages can register additional generators by declaring::

        [project.entry-points."ton.generators"]
        uuid = "my_pkg.generators:UuidGenerator"

    Entry-point names override built-ins with the same key.
    """
    registry = default_registry()
    loaded = 0
    for ep in entry_points(group=ENTRY_POINT_GROUP):
        factory = ep.load()
        registry[ep.name] = factory()
        loaded += 1
        _logger.info(
            "entry_point_loaded name=%s value=%s",
            ep.name,
            ep.value,
            extra={
                "event": "entry_point_loaded",
                "name": ep.name,
                "value": ep.value,
            },
        )
    if loaded:
        _logger.info(
            "entry_points_summary loaded=%d",
            loaded,
            extra={"event": "entry_points_summary", "loaded": loaded},
        )
    return registry
