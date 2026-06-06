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
from collections.abc import Container, Iterable, Iterator, Mapping
from importlib.metadata import entry_points
from typing import Any

from ._logging import LogEvent
from ._logging import logger as _logger
from ._transforms import IdentityTransform, Transform

# Importing ``ton.generators`` imports every concrete-generator submodule,
# which is what populates Generator.__subclasses__() below.
from .generators import BUILTIN_GENERATOR_CLASSES, Generator

#: Entry-point group third-party packages publish to expose a Generator
#: class. The entry-point *name* becomes the JSON ``type`` discriminator;
#: the loaded object must be a callable returning a Generator (typically
#: the Generator subclass itself).
ENTRY_POINT_GROUP = "ton.generators"
TRANSFORM_ENTRY_POINT_GROUP = "ton.transforms"
VALIDATOR_ENTRY_POINT_GROUP = "ton.validators"
CORE_NAMESPACE = "core"

#: Allowlist of built-in ``type_name`` strings. Used by
#: :func:`discover_generator_classes` to ignore in-process subclasses
#: that aren't part of TON itself (TODO ARCH-005).
_BUILTIN_TYPE_NAMES: frozenset[str] = frozenset(cls.type_name for cls in BUILTIN_GENERATOR_CLASSES)


class RegistryError(ValueError):
    """Raised when plugin registration would make lookup ambiguous."""


class ExtensionCatalog:
    """Namespaced catalog for data types, transforms, and validators."""

    def __init__(
        self,
        *,
        generators: Mapping[str, Generator] | None = None,
        transforms: Mapping[str, Transform] | None = None,
        validators: Mapping[str, Any] | None = None,
    ) -> None:
        self._generators: dict[str, dict[str, Generator]] = {
            CORE_NAMESPACE: dict(generators or default_registry())
        }
        self._transforms: dict[str, dict[str, Transform]] = {CORE_NAMESPACE: dict(transforms or {})}
        self._validators: dict[str, dict[str, Any]] = {CORE_NAMESPACE: dict(validators or {})}

    def register_data_type(
        self,
        namespace: str,
        name: str,
        generator: Generator,
    ) -> None:
        self._register(self._generators, namespace, name, generator)
        _log_plugin_registered("data_type", namespace, name)

    def register_transform(
        self,
        namespace: str,
        name: str,
        transform: Transform,
    ) -> None:
        self._register(self._transforms, namespace, name, transform)
        _log_plugin_registered("transform", namespace, name)

    def register_validator(self, namespace: str, name: str, validator: Any) -> None:
        self._register(self._validators, namespace, name, validator)
        _log_plugin_registered("validator", namespace, name)

    def generators(self) -> dict[str, Generator]:
        return self._flatten(self._generators)

    def transforms(self) -> dict[str, Transform]:
        return self._flatten(self._transforms)

    def validators(self) -> dict[str, Any]:
        return self._flatten(self._validators)

    def list_data_types(self) -> tuple[str, ...]:
        return tuple(sorted(self.generators()))

    def list_transforms(self) -> tuple[str, ...]:
        return tuple(sorted(self.transforms()))

    def list_validators(self) -> tuple[str, ...]:
        return tuple(sorted(self.validators()))

    def namespaces(self) -> tuple[str, ...]:
        names = set(self._generators) | set(self._transforms) | set(self._validators)
        return tuple(sorted(names))

    def get_data_type(self, reference: str) -> Generator:
        return self.generators()[normalize_reference(reference)]

    def get_transform(self, reference: str) -> Transform:
        return self.transforms()[normalize_reference(reference)]

    @staticmethod
    def _flatten(store: Mapping[str, Mapping[str, Any]]) -> dict[str, Any]:
        flattened: dict[str, Any] = {}
        for namespace, values in store.items():
            for name, value in values.items():
                flattened[f"{namespace}.{name}"] = value
                if namespace == CORE_NAMESPACE:
                    flattened.setdefault(name, value)
        return flattened

    @staticmethod
    def _register(
        store: dict[str, dict[str, Any]],
        namespace: str,
        name: str,
        value: Any,
    ) -> None:
        _validate_identifier("namespace", namespace)
        _validate_identifier("name", name)
        if namespace == CORE_NAMESPACE and name in store[CORE_NAMESPACE]:
            raise RegistryError(f"cannot replace built-in registration {name!r}")
        bucket = store.setdefault(namespace, {})
        if name in bucket:
            raise RegistryError(f"registration {namespace}.{name} already exists")
        bucket[name] = value


def normalize_reference(reference: str) -> str:
    """Return a qualified registry reference."""
    _validate_reference(reference)
    if "." in reference:
        return reference
    return f"{CORE_NAMESPACE}.{reference}"


def build_extension_catalog() -> ExtensionCatalog:
    """Return a catalog containing the built-in data types."""
    from .transforms import DistributionTransform

    return ExtensionCatalog(
        transforms={
            "distribution": DistributionTransform(),
            "identity": IdentityTransform(),
        }
    )


def catalog_with_entry_points(
    *,
    allowed_names: Container[str] | None = None,
) -> ExtensionCatalog:
    """Return a catalog merged with trusted plugin entry points."""
    catalog = build_extension_catalog()
    _load_catalog_entry_points(
        catalog,
        group=ENTRY_POINT_GROUP,
        kind="data_type",
        allowed_names=allowed_names,
    )
    _load_catalog_entry_points(
        catalog,
        group=TRANSFORM_ENTRY_POINT_GROUP,
        kind="transform",
        allowed_names=allowed_names,
    )
    _load_catalog_entry_points(
        catalog,
        group=VALIDATOR_ENTRY_POINT_GROUP,
        kind="validator",
        allowed_names=allowed_names,
    )
    return catalog


def _load_catalog_entry_points(
    catalog: ExtensionCatalog,
    *,
    group: str,
    kind: str,
    allowed_names: Container[str] | None,
) -> None:
    loaded = 0
    failed = 0
    for ep in entry_points(group=group):
        if allowed_names is not None and ep.name not in allowed_names:
            continue
        try:
            plugin = ep.load()()
            namespace, name = _entry_point_namespace_name(ep.name, kind, plugin)
            _register_entry_point_plugin(catalog, kind, namespace, name, plugin)
        except Exception as exc:  # noqa: BLE001 - per-entry sandbox
            failed += 1
            _log_entry_point_failed(ep, exc)
            continue
        loaded += 1
        _log_entry_point_loaded(ep)
    if loaded or failed:
        _logger.info(
            "entry_points_summary loaded=%d failed=%d",
            loaded,
            failed,
            extra={
                "event": LogEvent.ENTRY_POINTS_SUMMARY.value,
                "loaded": loaded,
                "failed": failed,
                "group": group,
            },
        )


def _register_entry_point_plugin(
    catalog: ExtensionCatalog,
    kind: str,
    namespace: str,
    name: str,
    plugin: Any,
) -> None:
    if kind == "data_type":
        if not isinstance(plugin, Generator):
            raise TypeError("data type entry point must return a Generator")
        catalog.register_data_type(namespace, name, plugin)
        return
    if kind == "transform":
        if not _is_transform(plugin):
            raise TypeError("transform entry point must return a Transform")
        catalog.register_transform(namespace, name, plugin)
        return
    catalog.register_validator(namespace, name, plugin)


def _is_transform(plugin: Any) -> bool:
    return all(callable(getattr(plugin, name, None)) for name in ("prepare", "apply", "prove"))


def _entry_point_namespace_name(
    entry_point_name: str,
    kind: str,
    plugin: Any,
) -> tuple[str, str]:
    if "." in entry_point_name:
        namespace, name = entry_point_name.split(".", 1)
        _validate_identifier("namespace", namespace)
        _validate_identifier("name", name)
        return namespace, name
    try:
        _validate_identifier("name", entry_point_name)
    except RegistryError:
        if kind != "data_type":
            raise
        type_name = getattr(plugin, "type_name", "")
        _validate_identifier("name", type_name)
        return "plugin", type_name
    return "plugin", entry_point_name


def _validate_reference(reference: str) -> None:
    parts = reference.split(".")
    if len(parts) == 1:
        _validate_identifier("name", parts[0])
        return
    if len(parts) == 2:
        _validate_identifier("namespace", parts[0])
        _validate_identifier("name", parts[1])
        return
    raise RegistryError(f"invalid registry reference {reference!r}")


def _validate_identifier(label: str, value: str) -> None:
    if not value or not value.replace("_", "").isalnum():
        raise RegistryError(f"{label} must contain only letters, numbers, or '_'")


def discover_generator_classes() -> list[type[Generator]]:
    """Return every concrete :class:`Generator` subclass with a ``type_name``
    that matches a known built-in.

    Walks the full subclass tree but filters by the built-in allowlist so
    test fixtures and third-party plugins do not leak in (TODO ARCH-005).
    """
    return [
        cls
        for cls in _walk_subclasses(Generator)  # type: ignore[type-abstract]
        if not inspect.isabstract(cls) and cls.type_name and cls.type_name in _BUILTIN_TYPE_NAMES
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


def registry_with_entry_points(
    *,
    allowed_names: Container[str] | None = None,
) -> dict[str, Generator]:
    """Return the built-in registry merged with entry-point generators.

    Third-party packages can register additional generators by declaring::

        [project.entry-points."ton.generators"]
        uuid = "my_pkg.generators:UuidGenerator"

    Entry-point names override built-ins with the same key. When
    ``allowed_names`` is provided, only matching entry-point names are
    loaded; all others are ignored without importing their target.
    """
    catalog = catalog_with_entry_points(allowed_names=allowed_names)
    registry = catalog.generators()
    for qualified, generator in list(registry.items()):
        if "." not in qualified:
            continue
        namespace, name = qualified.split(".", 1)
        if namespace != CORE_NAMESPACE and name not in registry:
            registry[name] = generator
    return registry


def _log_plugin_registered(kind: str, namespace: str, name: str) -> None:
    if namespace == CORE_NAMESPACE:
        return
    _logger.info(
        "plugin_registered kind=%s namespace=%s name=%s",
        kind,
        namespace,
        name,
        extra={
            "event": LogEvent.PLUGIN_REGISTERED.value,
            "kind": kind,
            "namespace": namespace,
            "plugin_name": name,
            "reference": f"{namespace}.{name}",
        },
    )


def _log_entry_point_failed(ep: object, exc: Exception) -> None:
    safe_name = _sanitize_for_log(getattr(ep, "name", ""))
    safe_value = _sanitize_for_log(getattr(ep, "value", ""))
    dist_name, dist_version = _entry_point_dist(ep)
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


def _log_entry_point_loaded(ep: object) -> None:
    safe_name = _sanitize_for_log(getattr(ep, "name", ""))
    safe_value = _sanitize_for_log(getattr(ep, "value", ""))
    dist_name, dist_version = _entry_point_dist(ep)
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
