"""Compile-time plan contract for the runtime Engine."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any

from ._logging import LogEvent
from ._logging import logger as _logger
from ._proof import PreparedField, PreparedTransform
from ._registry import (
    RegistryError,
    default_transforms,
    default_validators,
    make_registry,
    normalize_reference,
    runtime_type_name,
)
from ._speckeys import COMMON_FIELD_KEYS, extension_key_error
from ._template import Token, parse, split_segments
from ._transforms import Transform, fold_paired_capabilities
from ._validation import Validator
from .generators import Generator


@dataclass(frozen=True)
class CompiledPlan:
    """Immutable configuration artifacts required by row generation."""

    types: Mapping[str, Mapping[str, Any]]
    rows: int
    tokens: tuple[Token, ...]
    prepared: Mapping[str, PreparedField]
    has_paired: bool
    literals: tuple[str, ...]
    resolved_tokens: tuple[ResolvedToken, ...]


@dataclass(frozen=True)
class ResolvedToken:
    """A template token with its prepared field and static fast-path eligibility."""

    token: Token
    field: PreparedField
    direct: bool


class TemplateError(ValueError):
    """Raised when a template or prepared field cannot be compiled."""


class EngineCompiler:
    """Compile configuration and extension catalogs into a runtime plan."""

    def __init__(
        self,
        config: Mapping[str, Any],
        registry: Mapping[str, Generator] | None,
        transforms: Mapping[str, Transform] | None,
        validators: Mapping[str, Validator] | None,
        prepare_all_fields: bool = False,
    ) -> None:
        self.template = str(config["format"])
        self.types: Mapping[str, Mapping[str, Any]] = config["types"]
        self.rows = int(config["rows"])
        self.tokens = tuple(parse(self.template))
        self.field_keys = (
            tuple(self.types)
            if prepare_all_fields
            else tuple(dict.fromkeys(token.type_key for token in self.tokens))
        )
        self.registry = self._resolve_registry(registry)
        built_in_transforms = default_transforms()
        built_in_validators = default_validators()
        self.transforms = dict(
            transforms
            if transforms is not None
            else {
                **built_in_transforms,
                **{f"core.{name}": value for name, value in built_in_transforms.items()},
            }
        )
        self.validators = dict(
            validators
            if validators is not None
            else {
                **built_in_validators,
                **{f"core.{name}": value for name, value in built_in_validators.items()},
            }
        )

    def compile(self) -> CompiledPlan:
        self._validate()
        prepared = self._build_prepared()
        literals, plan_tokens = split_segments(self.template)
        resolved_tokens = tuple(
            ResolvedToken(token, prepared[token.type_key], prepared[token.type_key].is_direct)
            for token in plan_tokens
        )
        return CompiledPlan(
            types=self.types,
            rows=self.rows,
            tokens=self.tokens,
            prepared=prepared,
            has_paired=any(prepared[token.type_key].is_paired for token in self.tokens),
            literals=tuple(literals),
            resolved_tokens=resolved_tokens,
        )

    def _resolve_registry(
        self, registry: Mapping[str, Generator] | None
    ) -> Mapping[str, Generator]:
        if registry is not None:
            return dict(registry)
        root_specs: list[Mapping[str, Any]] = []
        root_types: set[str] = set()
        for type_key in self.field_keys:
            spec = self.types.get(type_key)
            if isinstance(spec, Mapping) and "type" in spec:
                root_specs.append(spec)
                root_types.add(runtime_type_name(spec["type"]))
        roots = make_registry(root_types)
        needed = set(root_types)
        for spec in root_specs:
            generator = roots.get(runtime_type_name(spec["type"]))
            if generator is not None:
                needed.update(runtime_type_name(name) for name in generator.nested_types(spec))
        return make_registry(needed)

    def _validate(self) -> None:
        for type_key in self.field_keys:
            try:
                normalize_reference(self.types[type_key]["type"])
            except RegistryError as exc:
                raise TemplateError(str(exc)) from exc
            type_name = runtime_type_name(self.types[type_key]["type"])
            if type_name not in self.registry:
                available = ", ".join(sorted(self.registry)) or "(none)"
                raise TemplateError(
                    f"Unknown type {type_name!r} for variable {type_key!r}. "
                    f"Available types: {available}."
                )

    def _build_prepared(self) -> dict[str, PreparedField]:
        from .generators.base import PreparationContext

        prepared: dict[str, PreparedField] = {}
        context = PreparationContext(self.registry)
        for type_key in self.field_keys:
            spec = self.types[type_key]
            generator = self.registry[runtime_type_name(spec["type"])]
            try:
                self._validate_generator_keys(f"types.{type_key}", spec, generator)
                prepared[type_key] = PreparedField(
                    generator=generator,
                    source_prepared=context.prepare_generator(generator, spec),
                    transforms=self._prepare_transforms(type_key, spec, generator),
                    validators=self._resolve_validators(type_key, spec),
                )
            except Exception as exc:  # noqa: BLE001
                _logger.warning(
                    "prepare_failed type_key=%s generator_type=%s error_type=%s",
                    type_key,
                    type(generator).__name__,
                    type(exc).__name__,
                    extra={
                        "event": LogEvent.PREPARE_FAILED.value,
                        "type_key": type_key,
                        "generator_type": type(generator).__name__,
                        "error_type": type(exc).__name__,
                    },
                )
                raise TemplateError(
                    f"Invalid spec for variable {type_key!r}: {type(exc).__name__}: {exc}"
                ) from exc
        return prepared

    def _validate_generator_keys(
        self,
        path: str,
        spec: Mapping[str, Any],
        generator: Generator,
    ) -> None:
        error = extension_key_error(path, spec, generator.config_keys, COMMON_FIELD_KEYS)
        if error is not None:
            raise TemplateError(error)
        for location, nested_spec in generator.nested_specs(spec):
            reference = nested_spec.get("type")
            if not isinstance(reference, str):
                continue
            child = self.registry.get(runtime_type_name(reference))
            if child is not None:
                self._validate_generator_keys(f"{path}.{location}", nested_spec, child)

    def _prepare_transforms(
        self, type_key: str, spec: Mapping[str, Any], generator: Generator
    ) -> tuple[PreparedTransform, ...]:
        is_paired = bool(generator.is_paired)
        prepared: list[PreparedTransform] = []
        for index, transform_spec in enumerate(spec.get("transforms", [])):
            transform = self._resolve_transform(type_key, transform_spec["type"])
            error = extension_key_error(
                f"types.{type_key}.transforms[{index}]",
                transform_spec,
                transform.config_keys,
                frozenset(("type",)),
            )
            if error is not None:
                raise TemplateError(error)
            capability = fold_paired_capabilities(is_paired, (transform.capabilities,))
            if capability.incompatible_index is not None:
                raise TemplateError(
                    f"Transform {transform_spec['type']!r} for variable "
                    f"{type_key!r} does not accept paired input"
                )
            prepared.append(
                PreparedTransform(
                    transform,
                    transform.prepare_composite(transform_spec, self.registry),
                )
            )
            _logger.info(
                "transform_prepared type_key=%s transform=%s paired=%s",
                type_key,
                transform.type_name,
                is_paired,
                extra={
                    "event": LogEvent.TRANSFORM_PREPARED.value,
                    "type_key": type_key,
                    "transform": transform.type_name,
                    "paired_input": is_paired,
                },
            )
            is_paired = capability.preserves_pairing
        return tuple(prepared)

    def _resolve_transform(self, type_key: str, reference: str) -> Transform:
        normalized = normalize_reference(reference)
        transform = self.transforms.get(normalized) or self.transforms.get(reference)
        if transform is None:
            raise TemplateError(
                f"Unknown transform {reference!r} for variable {type_key!r}. "
                f"{_available_extensions('transforms', self.transforms)}"
            )
        return transform

    def _resolve_validators(self, type_key: str, spec: Mapping[str, Any]) -> tuple[Validator, ...]:
        resolved: list[Validator] = []
        for reference in spec.get("validators", []):
            normalized = normalize_reference(reference)
            validator = self.validators.get(normalized) or self.validators.get(reference)
            if validator is None:
                raise TemplateError(
                    f"Unknown validator {reference!r} for variable {type_key!r}. "
                    f"{_available_extensions('validators', self.validators)}"
                )
            resolved.append(validator)
        return tuple(resolved)


def _available_extensions(kind: str, registry: Mapping[str, Any]) -> str:
    available = ", ".join(sorted(registry)) or "(none)"
    return f"Available {kind}: {available}. Use 'namespace.name' for plugin references."


def compile_plan(
    config: Mapping[str, Any],
    *,
    registry: Mapping[str, Generator] | None = None,
    transforms: Mapping[str, Transform] | None = None,
    validators: Mapping[str, Validator] | None = None,
    prepare_all_fields: bool = False,
) -> CompiledPlan:
    """Compile one config through the canonical compiler boundary."""
    return EngineCompiler(
        config,
        registry,
        transforms,
        validators,
        prepare_all_fields=prepare_all_fields,
    ).compile()
