"""Registry mapping JSON ``type`` discriminators to Generator instances.

The default registry is sourced from the explicit allowlist
``ton.generators.BUILTIN_GENERATOR_CLASSES`` (ARCH-005). Walking
``Generator.__subclasses__()`` is still exposed via
:func:`discover_generator_classes` for callers that want full
introspection, but the default registry no longer picks up in-process
test fixtures or unrelated third-party subclasses.

Construction goes through :func:`make_registry` so callers can request
only the type names they need (PERF-012); the legacy
:func:`default_registry` builds the full dictionary for backwards
compatibility.
"""

from __future__ import annotations

import inspect
import re
import threading
from collections import Counter
from collections.abc import Collection, Iterable, Iterator, Mapping
from copy import deepcopy
from dataclasses import dataclass
from importlib.metadata import entry_points
from typing import Any, TypeVar

from ._logging import LogEvent
from ._logging import logger as _logger
from ._transforms import IdentityTransform, Transform
from ._validation import NonEmptyValidator, Validator

# Importing ``ton.generators`` imports every concrete-generator submodule,
# which is what populates Generator.__subclasses__() below.
from .generators import BUILTIN_GENERATOR_CLASSES, Generator
from .transforms import DistributionTransform

#: Entry-point group third-party packages publish to expose a Generator
#: class. The entry-point *name* becomes the JSON ``type`` discriminator;
#: the loaded object must be a callable returning a Generator (typically
#: the Generator subclass itself).
ENTRY_POINT_GROUP = "ton.generators"
TRANSFORM_ENTRY_POINT_GROUP = "ton.transforms"
VALIDATOR_ENTRY_POINT_GROUP = "ton.validators"
CORE_NAMESPACE = "core"
_T = TypeVar("_T")

#: Identity-based allowlist of built-in classes. A third-party subclass may
#: reuse a core ``type_name`` but can never become a default implementation.
_BUILTIN_GENERATOR_CLASSES: frozenset[type[Generator]] = frozenset(BUILTIN_GENERATOR_CLASSES)
_ASCII_IDENTIFIER = re.compile(r"[A-Za-z0-9_]+\Z")
_ASCII_DISTRIBUTION = re.compile(r"[A-Za-z0-9]+(?:-[A-Za-z0-9]+)*\Z")


class RegistryError(ValueError):
    """Raised when plugin registration would make lookup ambiguous."""


@dataclass(frozen=True, order=True)
class EntryPointSelector:
    """Trusted entry-point identity in ``GROUP:DISTRIBUTION:NAME`` form."""

    group: str
    distribution: str
    name: str

    def __post_init__(self) -> None:
        if self.group not in {
            ENTRY_POINT_GROUP,
            TRANSFORM_ENTRY_POINT_GROUP,
            VALIDATOR_ENTRY_POINT_GROUP,
        }:
            raise RegistryError(f"unsupported entry-point group {self.group!r}")
        object.__setattr__(self, "distribution", _normalize_distribution_name(self.distribution))
        if not self.name or ":" in self.name:
            raise RegistryError("entry-point name must be non-empty and cannot contain ':'")
        _validate_reference(self.name)

    @classmethod
    def parse(cls, value: str) -> EntryPointSelector:
        """Parse ``GROUP:DISTRIBUTION:NAME`` into a trusted selector."""
        parts = value.split(":", 2)
        if len(parts) != 3:
            raise RegistryError("entry-point selector must use GROUP:DISTRIBUTION:NAME")
        return cls(*parts)

    def __str__(self) -> str:
        return f"{self.group}:{self.distribution}:{self.name}"


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
            CORE_NAMESPACE: dict(default_registry() if generators is None else generators)
        }
        self._transforms: dict[str, dict[str, Transform]] = {CORE_NAMESPACE: dict(transforms or {})}
        self._validators: dict[str, dict[str, Any]] = {CORE_NAMESPACE: dict(validators or {})}
        self._lock = threading.RLock()
        # Flattened views are rebuilt only when a registration mutates a
        # store (PERF-003); catalog reads during config validation hit
        # the cache instead of re-running _flatten per field/transform.
        self._flat_cache: dict[str, dict[str, Any]] = {}

    def register_data_type(
        self,
        namespace: str,
        name: str,
        generator: Generator,
    ) -> None:
        if not isinstance(generator, Generator):
            raise TypeError("generator must be a Generator")
        with self._lock:
            self._register(self._generators, namespace, name, generator)
        _log_plugin_registered("data_type", namespace, name)

    def register_transform(
        self,
        namespace: str,
        name: str,
        transform: Transform,
    ) -> None:
        if not isinstance(transform, Transform):
            raise TypeError("transform must implement the Transform protocol")
        with self._lock:
            self._register(self._transforms, namespace, name, transform)
        _log_plugin_registered("transform", namespace, name)

    def register_validator(self, namespace: str, name: str, validator: Any) -> None:
        if not isinstance(validator, Validator):
            raise TypeError("validator must implement the Validator protocol")
        with self._lock:
            self._register(self._validators, namespace, name, validator)
        _log_plugin_registered("validator", namespace, name)

    def generators(self) -> dict[str, Generator]:
        # The catalog stores prototypes. Clone the complete flattened view
        # so aliases still share one instance within an Engine while separate
        # Engine builds never share mutable generator state.
        with self._lock:
            return deepcopy(self._flattened("generators", self._generators))

    def transforms(self) -> dict[str, Transform]:
        with self._lock:
            return deepcopy(self._flattened("transforms", self._transforms))

    def validators(self) -> dict[str, Any]:
        with self._lock:
            return deepcopy(self._flattened("validators", self._validators))

    def list_data_types(self) -> tuple[str, ...]:
        with self._lock:
            return tuple(sorted(self._flattened("generators", self._generators)))

    def list_transforms(self) -> tuple[str, ...]:
        with self._lock:
            return tuple(sorted(self._flattened("transforms", self._transforms)))

    def list_validators(self) -> tuple[str, ...]:
        with self._lock:
            return tuple(sorted(self._flattened("validators", self._validators)))

    def namespaces(self) -> tuple[str, ...]:
        with self._lock:
            names = set(self._generators) | set(self._transforms) | set(self._validators)
            return tuple(sorted(names))

    def get_data_type(self, reference: str) -> Generator:
        with self._lock:
            return self._clone_prototype(self._generators, reference)

    def get_transform(self, reference: str) -> Transform:
        with self._lock:
            return self._clone_prototype(self._transforms, reference)

    @staticmethod
    def _clone_prototype(store: Mapping[str, Mapping[str, _T]], reference: str) -> _T:
        normalized = normalize_reference(reference)
        namespace, name = normalized.split(".", 1)
        try:
            prototype = store[namespace][name]
        except KeyError:
            raise KeyError(normalized) from None
        return deepcopy(prototype)

    def _flattened(self, key: str, store: Mapping[str, Mapping[str, Any]]) -> dict[str, Any]:
        cached = self._flat_cache.get(key)
        if cached is None:
            cached = self._flatten(store)
            self._flat_cache[key] = cached
        return dict(cached)

    @staticmethod
    def _flatten(store: Mapping[str, Mapping[str, Any]]) -> dict[str, Any]:
        flattened: dict[str, Any] = {}
        for namespace, values in store.items():
            for name, value in values.items():
                flattened[f"{namespace}.{name}"] = value
                if namespace == CORE_NAMESPACE:
                    flattened.setdefault(name, value)
        return flattened

    def _register(
        self,
        store: dict[str, dict[str, Any]],
        namespace: str,
        name: str,
        value: Any,
    ) -> None:
        _validate_identifier("namespace", namespace)
        _validate_identifier("name", name)
        if namespace == CORE_NAMESPACE:
            raise RegistryError("namespace 'core' is reserved for built-in registrations")
        bucket = store.setdefault(namespace, {})
        if name in bucket:
            raise RegistryError(f"registration {namespace}.{name} already exists")
        bucket[name] = value
        # Registration mutated a store; drop cached flattened views so
        # the next read reflects the new plugin (PERF-003).
        self._flat_cache.clear()


def normalize_reference(reference: str) -> str:
    """Return a qualified registry reference."""
    _validate_reference(reference)
    if "." in reference:
        return reference
    return f"{CORE_NAMESPACE}.{reference}"


def resolve_reference(registry: Mapping[str, _T], reference: str) -> _T | None:
    """Resolve qualified or bare references using registry namespace rules."""
    normalized = normalize_reference(reference)
    return (
        registry.get(normalized)
        or registry.get(reference)
        or registry.get(normalized.removeprefix(f"{CORE_NAMESPACE}."))
    )


def runtime_type_name(reference: object) -> str:
    """Return the bare runtime key for a built-in qualified reference."""
    if isinstance(reference, str):
        return normalize_reference(reference).removeprefix(f"{CORE_NAMESPACE}.")
    return str(reference)


def default_transforms() -> dict[str, Transform]:
    """Return fresh built-in transform prototypes without building generators."""
    return {"distribution": DistributionTransform(), "identity": IdentityTransform()}


def default_validators() -> dict[str, Validator]:
    """Return fresh built-in validators without building generators."""
    return {"non_empty": NonEmptyValidator()}


def build_extension_catalog() -> ExtensionCatalog:
    """Return a catalog containing all built-in extension kinds."""
    return ExtensionCatalog(transforms=default_transforms(), validators=default_validators())


def catalog_with_entry_points(
    *,
    allowed_selectors: Collection[EntryPointSelector] | None = None,
) -> ExtensionCatalog:
    """Return a catalog merged with trusted plugin entry points."""
    catalog = build_extension_catalog()
    failures: set[str] = set()
    for group, kind in (
        (ENTRY_POINT_GROUP, "data_type"),
        (TRANSFORM_ENTRY_POINT_GROUP, "transform"),
        (VALIDATOR_ENTRY_POINT_GROUP, "validator"),
    ):
        failures.update(
            _load_catalog_entry_points(
                catalog,
                group=group,
                kind=kind,
                allowed_selectors=allowed_selectors,
            )
        )
    if failures:
        details = "; ".join(sorted(failures))
        raise RegistryError(f"explicit entry-point selector unsatisfied: {details}")
    return catalog


def _load_catalog_entry_points(
    catalog: ExtensionCatalog,
    *,
    group: str,
    kind: str,
    allowed_selectors: Collection[EntryPointSelector] | None,
) -> set[str]:
    loaded = 0
    requested = (
        {selector for selector in allowed_selectors if selector.group == group}
        if allowed_selectors is not None
        else set()
    )
    candidates = _entry_point_candidates(group, allowed_selectors)
    matched = {
        selector
        for ep in candidates
        if (selector := _selector_for_entry_point(group, ep)) is not None
    }
    missing = requested - matched
    failed = len(missing)
    explicit_failures = {f"{selector} was not found" for selector in missing}
    duplicate_names = {
        name for name, count in Counter(str(ep.name) for ep in candidates).items() if count > 1
    }
    for ep in candidates:
        succeeded, explicit_failure = _load_catalog_candidate(
            catalog,
            ep,
            group=group,
            kind=kind,
            duplicate=str(ep.name) in duplicate_names,
            allowed_selectors=allowed_selectors,
        )
        loaded += int(succeeded)
        failed += int(not succeeded)
        if explicit_failure is not None:
            explicit_failures.add(explicit_failure)
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
    return explicit_failures


def _load_catalog_candidate(
    catalog: ExtensionCatalog,
    ep: Any,
    *,
    group: str,
    kind: str,
    duplicate: bool,
    allowed_selectors: Collection[EntryPointSelector] | None,
) -> tuple[bool, str | None]:
    selector = _selector_for_entry_point(group, ep)
    if duplicate:
        _log_entry_point_failed(ep, RegistryError("duplicate entry-point providers"))
        return False, _explicit_entry_point_failure(
            selector, allowed_selectors, "has duplicate providers"
        )
    try:
        plugin = ep.load()()
        namespace, name = _entry_point_namespace_name(ep.name, kind, plugin)
        _validate_entry_point_plugin(kind, plugin)
        _stamp_plugin_dist(plugin, ep)
        _register_entry_point_plugin(catalog, kind, namespace, name, plugin)
    except Exception as exc:  # noqa: BLE001 - per-entry failure isolation
        _log_entry_point_failed(ep, exc)
        return False, _explicit_entry_point_failure(
            selector,
            allowed_selectors,
            f"failed to load ({type(exc).__name__})",
        )
    _log_entry_point_loaded(ep)
    return True, None


def _explicit_entry_point_failure(
    selector: EntryPointSelector | None,
    allowed_selectors: Collection[EntryPointSelector] | None,
    message: str,
) -> str | None:
    if selector is None or allowed_selectors is None:
        return None
    return f"{selector} {message}"


def _entry_point_candidates(
    group: str,
    allowed_selectors: Collection[EntryPointSelector] | None,
) -> list[Any]:
    """Return trusted candidates in provider-stable order without importing them."""
    candidates = []
    for ep in entry_points(group=group):
        if allowed_selectors is not None:
            selector = _selector_for_entry_point(group, ep)
            if selector is None or selector not in allowed_selectors:
                continue
        candidates.append(ep)
    return sorted(candidates, key=_entry_point_sort_key)


def _selector_for_entry_point(group: str, ep: object) -> EntryPointSelector | None:
    distribution, _ = _entry_point_dist(ep)
    name = getattr(ep, "name", None)
    if not isinstance(distribution, str) or not isinstance(name, str):
        return None
    try:
        return EntryPointSelector(group, distribution, name)
    except RegistryError:
        return None


def _entry_point_sort_key(ep: object) -> tuple[str, str, str]:
    distribution, _ = _entry_point_dist(ep)
    return (
        distribution if isinstance(distribution, str) else "",
        str(getattr(ep, "name", "")),
        str(getattr(ep, "value", "")),
    )


def _normalize_distribution_name(value: str) -> str:
    normalized = re.sub(r"[-_.]+", "-", value).lower()
    if _ASCII_DISTRIBUTION.fullmatch(normalized) is None:
        raise RegistryError(f"invalid distribution name {value!r}")
    return normalized


def _register_entry_point_plugin(
    catalog: ExtensionCatalog,
    kind: str,
    namespace: str,
    name: str,
    plugin: Any,
) -> None:
    _validate_entry_point_plugin(kind, plugin)
    if kind == "data_type":
        catalog.register_data_type(namespace, name, plugin)
        return
    if kind == "transform":
        catalog.register_transform(namespace, name, plugin)
        return
    catalog.register_validator(namespace, name, plugin)


def _validate_entry_point_plugin(kind: str, plugin: Any) -> None:
    if kind == "data_type" and not isinstance(plugin, Generator):
        raise TypeError("data type entry point must return a Generator")
    if kind == "transform" and not _is_transform(plugin):
        raise TypeError("transform entry point must return a Transform")
    if kind == "validator" and not isinstance(plugin, Validator):
        raise TypeError("validator entry point must return a Validator")


def _is_transform(plugin: Any) -> bool:
    return isinstance(plugin, Transform)


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
    if _ASCII_IDENTIFIER.fullmatch(value) is None:
        raise RegistryError(f"{label} must contain only ASCII letters, numbers, or '_'")


def discover_generator_classes() -> list[type[Generator]]:
    """Return every concrete :class:`Generator` subclass with a ``type_name``
    that is explicitly registered as a built-in.

    Walks the full subclass tree but filters by the built-in allowlist so
    test fixtures and third-party plugins do not leak in (ARCH-005).
    """
    return [
        cls
        for cls in _walk_subclasses(Generator)  # type: ignore[type-abstract]
        if not inspect.isabstract(cls) and cls in _BUILTIN_GENERATOR_CLASSES
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
#: ``type_name`` so per-name lookups stay O(1) (PERF-012).
_DEFAULT_CLASSES: dict[str, type[Generator]] = {}
_DEFAULT_CLASSES_LOCK = threading.Lock()


def clear_default_registry_cache() -> None:
    """Force the next :func:`default_registry` call to rebuild its class map.

    Rebinds to a fresh empty dict (rather than clearing in place) so a
    concurrent reader keeps its own consistent snapshot (CONC-001).
    """
    global _DEFAULT_CLASSES
    with _DEFAULT_CLASSES_LOCK:
        _DEFAULT_CLASSES = {}


def _ensure_default_classes() -> dict[str, type[Generator]]:
    """Populate and return the cached ``type_name -> class`` mapping.

    Thread-safe (CONC-001): the class mapping is built into a *local*
    dict under :data:`_DEFAULT_CLASSES_LOCK` and published with a single
    atomic rebind. The lock-free fast path therefore only ever observes
    an empty dict or the fully-built one -- never a partially-populated
    mapping that would raise spurious "Unknown type" errors.
    """
    global _DEFAULT_CLASSES
    cached = _DEFAULT_CLASSES
    if cached:
        return cached
    with _DEFAULT_CLASSES_LOCK:
        if _DEFAULT_CLASSES:
            return _DEFAULT_CLASSES
        built = {cls.type_name: cls for cls in BUILTIN_GENERATOR_CLASSES}
        _logger.info(
            "registry_discovered generators=%d",
            len(built),
            extra={
                "event": LogEvent.REGISTRY_DISCOVERED.value,
                "generators": len(built),
                "names": sorted(built),
            },
        )
        _DEFAULT_CLASSES = built
        return _DEFAULT_CLASSES


def make_registry(type_names: Iterable[str] | None = None) -> dict[str, Generator]:
    """Return a fresh registry containing only the requested built-ins.

    When ``type_names`` is ``None`` every built-in is instantiated
    (matches :func:`default_registry`). When passed an iterable of names,
    only those generators are constructed -- the Engine uses this to
    skip the per-construction cost of generators it does not need
    (PERF-012).

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
    allowed_selectors: Collection[EntryPointSelector] | None = None,
) -> dict[str, Generator]:
    """Return the built-in registry merged with entry-point generators.

    Third-party packages can register additional generators by declaring::

        [project.entry-points."ton.generators"]
        widget = "my_pkg.generators:WidgetGenerator"

    Entry-point generators cannot shadow built-ins (PLUG-002): an
    unqualified entry-point name lands in the ``plugin`` namespace
    (``plugin.widget``) and is also promoted to the bare key ``widget``
    only when no built-in already claims it. Core registrations are never
    replaced. When ``allowed_selectors`` is provided, only exact
    group/distribution/name identities are loaded; all others are ignored
    without importing their target.
    """
    catalog = catalog_with_entry_points(allowed_selectors=allowed_selectors)
    # Copy the cached flattened view before mutating it: catalog.generators()
    # returns the shared cache (PERF-003), so promoting plugin names to bare
    # keys must not scribble on it.
    registry = dict(catalog.generators())
    for qualified, generator in list(registry.items()):
        if "." not in qualified:
            continue
        namespace, name = qualified.split(".", 1)
        if namespace != CORE_NAMESPACE and name not in registry:
            registry[name] = generator
    return registry


def _log_plugin_registered(kind: str, namespace: str, name: str) -> None:
    safe_namespace = _sanitize_for_log(namespace)
    safe_name = _sanitize_for_log(name)
    _logger.info(
        "plugin_registered kind=%s namespace=%s name=%s",
        kind,
        safe_namespace,
        safe_name,
        extra={
            "event": LogEvent.PLUGIN_REGISTERED.value,
            "kind": kind,
            "namespace": safe_namespace,
            "plugin_name": safe_name,
            "reference": f"{safe_namespace}.{safe_name}",
        },
    )


def _log_entry_point_failed(ep: object, exc: Exception) -> None:
    safe_name = _sanitize_for_log(getattr(ep, "name", ""))
    safe_value = _sanitize_for_log(getattr(ep, "value", ""))
    dist_name, dist_version = _safe_entry_point_dist(ep)
    _logger.warning(
        "entry_point_failed name=%s value=%s error_type=%s",
        safe_name,
        safe_value,
        type(exc).__name__,
        extra={
            "event": LogEvent.ENTRY_POINT_FAILED.value,
            "ep_name": safe_name,
            "value": safe_value,
            "dist_name": dist_name,
            "dist_version": dist_version,
            "error_type": type(exc).__name__,
        },
    )


def _log_entry_point_loaded(ep: object) -> None:
    safe_name = _sanitize_for_log(getattr(ep, "name", ""))
    safe_value = _sanitize_for_log(getattr(ep, "value", ""))
    dist_name, dist_version = _safe_entry_point_dist(ep)
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


def _safe_entry_point_dist(ep: object) -> tuple[str | None, str | None]:
    name, version = _entry_point_dist(ep)
    return (
        _sanitize_for_log(name) if name is not None else None,
        _sanitize_for_log(version) if version is not None else None,
    )


def _stamp_plugin_dist(plugin: Any, ep: object) -> None:
    """Record the providing distribution on the plugin instance (OBS-001).

    ``Engine.provenance`` reads these attributes to attribute a
    plugin-provided data type back to its package/version. Built-in
    generators never carry them, so provenance reports ``None`` for core
    types.
    """
    name, version = _safe_entry_point_dist(ep)
    plugin._ton_plugin_package = name
    plugin._ton_plugin_version = version


def _entry_point_dist(ep: object) -> tuple[str | None, str | None]:
    """Return ``(name, version)`` of the distribution that ships ``ep``.

    ``EntryPoint.dist`` is only present on importlib.metadata 3.10+ and
    can still be ``None`` for entry points discovered outside any
    installed distribution; tolerate either case (OBS-005).
    """
    dist = getattr(ep, "dist", None)
    if dist is None:
        return (None, None)
    return (getattr(dist, "name", None), getattr(dist, "version", None))
