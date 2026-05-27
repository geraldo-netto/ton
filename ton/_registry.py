"""Registry mapping JSON ``type`` discriminators to Generator instances.

The default registry is sourced from the explicit allowlist
``ton.generators.BUILTIN_GENERATOR_CLASSES`` (TODO ARCH-005). Walking
``Generator.__subclasses__()`` is still exposed via
:func:`discover_generator_classes` for callers that want full
introspection, but the default registry no longer picks up in-process
test fixtures or unrelated third-party subclasses.

Construction goes through :func:`make_registry` so callers can request
only the type names they need (TODO PERF-012); the legacy
:func:`default_registry` builds the full dictionary for backwards
compatibility.
"""

from __future__ import annotations

import inspect
import threading
from collections.abc import Iterable, Iterator
from importlib.metadata import entry_points

from ._logging import LogEvent
from ._logging import logger as _logger

# Importing ``ton.generators`` imports every concrete-generator submodule,
# which is what populates Generator.__subclasses__() below.
from .generators import BUILTIN_GENERATOR_CLASSES, Generator

#: Entry-point group third-party packages publish to expose a Generator
#: class. The entry-point *name* becomes the JSON ``type`` discriminator;
#: the loaded object must be a callable returning a Generator (typically
#: the Generator subclass itself).
ENTRY_POINT_GROUP = "ton.generators"

#: Allowlist of built-in ``type_name`` strings. Used by
#: :func:`discover_generator_classes` to ignore in-process subclasses
#: that aren't part of TON itself (TODO ARCH-005).
_BUILTIN_TYPE_NAMES: frozenset[str] = frozenset(
    cls.type_name for cls in BUILTIN_GENERATOR_CLASSES
)


def discover_generator_classes() -> list[type[Generator]]:
    """Return every concrete :class:`Generator` subclass with a ``type_name``
    that matches a known built-in.

    Walks the full subclass tree but filters by the built-in allowlist so
    test fixtures and third-party plugins do not leak in (TODO ARCH-005).
    """
    return [
        cls
        for cls in _walk_subclasses(Generator)  # type: ignore[type-abstract]
        if not inspect.isabstract(cls)
        and cls.type_name
        and cls.type_name in _BUILTIN_TYPE_NAMES
    ]


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


#: Process-wide cache of the discovered generator classes, indexed by
#: ``type_name`` so per-name lookups stay O(1) (TODO PERF-012).
_DEFAULT_CLASSES: dict[str, type[Generator]] = {}
_DEFAULT_CLASSES_LOCK = threading.Lock()


def clear_default_registry_cache() -> None:
    """Force the next :func:`default_registry` call to re-discover classes.

    Useful after a test or third-party plugin has registered a new
    ``Generator`` subclass and wants it picked up by the default
    registry.
    """
    with _DEFAULT_CLASSES_LOCK:
        _DEFAULT_CLASSES.clear()


def _ensure_default_classes() -> dict[str, type[Generator]]:
    """Populate and return the cached ``type_name -> class`` mapping.

    Thread-safe (TODO CONC-002): the first caller acquires
    :data:`_DEFAULT_CLASSES_LOCK` and runs the subclass walk; subsequent
    callers either find the cache populated or block briefly on the lock.
    """
    if _DEFAULT_CLASSES:
        return _DEFAULT_CLASSES
    with _DEFAULT_CLASSES_LOCK:
        if _DEFAULT_CLASSES:
            return _DEFAULT_CLASSES
        for cls in discover_generator_classes():
            _DEFAULT_CLASSES[cls.type_name] = cls
        _logger.info(
            "registry_discovered generators=%d",
            len(_DEFAULT_CLASSES),
            extra={
                "event": LogEvent.REGISTRY_DISCOVERED.value,
                "generators": len(_DEFAULT_CLASSES),
                "names": sorted(_DEFAULT_CLASSES),
            },
        )
    return _DEFAULT_CLASSES


def make_registry(type_names: Iterable[str] | None = None) -> dict[str, Generator]:
    """Return a fresh registry containing only the requested built-ins.

    When ``type_names`` is ``None`` every built-in is instantiated
    (matches :func:`default_registry`). When passed an iterable of names,
    only those generators are constructed -- the Engine uses this to
    skip the per-construction cost of the 19 generators it does not need
    (TODO PERF-012).

    Unknown names are silently dropped; the Engine's existing
    "Unknown type" validation catches them with a better message.
    """
    classes = _ensure_default_classes()
    if type_names is None:
        return {name: cls() for name, cls in classes.items()}
    requested = set(type_names)
    return {name: classes[name]() for name in requested if name in classes}


def default_registry() -> dict[str, Generator]:
    """Return a fresh registry containing every built-in generator.

    Each call constructs a new dict of fresh instances so per-spec state
    (e.g. :class:`ton.generators.sequence.SequenceGenerator` counters)
    stays Engine-scoped.
    """
    return make_registry()


def registry_with_entry_points() -> dict[str, Generator]:
    """Return the built-in registry merged with entry-point generators.

    Third-party packages can register additional generators by declaring::

        [project.entry-points."ton.generators"]
        uuid = "my_pkg.generators:UuidGenerator"

    Entry-point names override built-ins with the same key.
    """
    registry = default_registry()
    loaded = 0
    failed = 0
    for ep in entry_points(group=ENTRY_POINT_GROUP):
        safe_name = _sanitize_for_log(ep.name)
        safe_value = _sanitize_for_log(ep.value)
        dist_name, dist_version = _entry_point_dist(ep)
        try:
            factory = ep.load()
            instance = factory()
        except Exception as exc:  # noqa: BLE001 - per-entry sandbox
            # SEC-004: one broken third-party plugin must not abort the
            # whole registry build. Log a WARNING with attribution and
            # skip the entry instead of letting ImportError/etc. bubble
            # up to every Engine construction.
            failed += 1
            _logger.warning(
                "entry_point_failed name=%s value=%s error=%s",
                safe_name,
                safe_value,
                exc,
                extra={
                    "event": LogEvent.ENTRY_POINT_FAILED.value,
                    "ep_name": safe_name,
                    "value": safe_value,
                    "dist_name": dist_name,
                    "dist_version": dist_version,
                    "error": f"{type(exc).__name__}: {exc}",
                },
            )
            continue
        registry[ep.name] = instance
        loaded += 1
        _logger.info(
            "entry_point_loaded name=%s value=%s dist=%s version=%s",
            safe_name,
            safe_value,
            dist_name,
            dist_version,
            extra={
                "event": LogEvent.ENTRY_POINT_LOADED.value,
                "ep_name": safe_name,
                "value": safe_value,
                "dist_name": dist_name,
                "dist_version": dist_version,
            },
        )
    if loaded or failed:
        _logger.info(
            "entry_points_summary loaded=%d failed=%d",
            loaded,
            failed,
            extra={
                "event": LogEvent.ENTRY_POINTS_SUMMARY.value,
                "loaded": loaded,
                "failed": failed,
            },
        )
    return registry


def _sanitize_for_log(value: object) -> str:
    """Strip non-printable / non-ASCII chars from logged plugin metadata.

    A malicious or typo-squatted entry point can plant control codes or
    unicode lookalikes inside ``ep.name`` / ``ep.value``. Logs feed
    operators directly, so SEC-006 requires that we coerce to ASCII
    printable text before emitting. Non-conforming bytes are replaced
    with ``?`` so the original payload is still attributable but cannot
    poison terminals or downstream log parsers.
    """
    raw = str(value)
    return "".join(ch if 0x20 <= ord(ch) < 0x7F else "?" for ch in raw)


def _entry_point_dist(ep: object) -> tuple[str | None, str | None]:
    """Return ``(name, version)`` of the distribution that ships ``ep``.

    ``EntryPoint.dist`` is only present on importlib.metadata 3.10+ and
    can still be ``None`` for entry points discovered outside any
    installed distribution; tolerate either case (TODO OBS-005).
    """
    dist = getattr(ep, "dist", None)
    if dist is None:
        return (None, None)
    return (getattr(dist, "name", None), getattr(dist, "version", None))
