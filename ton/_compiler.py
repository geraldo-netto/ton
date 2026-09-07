"""Compile-time plan contract for the runtime Engine."""

from __future__ import annotations

from collections.abc import Iterable, Mapping
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
from .generators.base import (
    ChildPipelineGenerator,
    ChildPipelineSpec,
    PreparationContext,
    prepare_child_spec,
)


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
    has_child_pipelines: bool = False


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
        self.has_child_pipelines = False
        self.tokens = tuple(parse(self.template))
        self.field_keys = (
            tuple(self.types)
            if prepare_all_fields
            else tuple(dict.fromkeys(token.type_key for token in self.tokens))
        )
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
        self.registry = self._resolve_registry(registry)

    def compile(self) -> CompiledPlan:
        self._validate()
        prepared = self._build_prepared()
        self._validate_id_references(prepared)
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
            has_paired=any(prepared[token.type_key].source_is_paired for token in self.tokens),
            literals=tuple(literals),
            resolved_tokens=resolved_tokens,
            has_child_pipelines=self.has_child_pipelines,
        )

    def _resolve_registry(
        self, registry: Mapping[str, Generator] | None
    ) -> Mapping[str, Generator]:
        if registry is not None:
            return dict(registry)
        root_specs: list[Mapping[str, Any]] = []
        for type_key in self.field_keys:
            spec = self.types.get(type_key)
            if isinstance(spec, Mapping) and "type" in spec:
                root_specs.append(spec)
        return make_registry(self._discover_generator_types(root_specs))

    def _discover_generator_types(
        self,
        root_specs: list[Mapping[str, Any]],
    ) -> set[str]:
        needed: set[str] = set()
        pending = list(root_specs)
        while pending:
            spec = pending.pop()
            type_name = runtime_type_name(spec.get("type"))
            needed.add(type_name)
            generator = make_registry((type_name,)).get(type_name)
            if generator is not None:
                pending.extend(child for _location, child in generator.nested_specs(spec))
            pending.extend(self._transform_child_specs(spec))
        return needed

    def _transform_child_specs(
        self,
        field_spec: Mapping[str, Any],
    ) -> tuple[Mapping[str, Any], ...]:
        children: list[Mapping[str, Any]] = []
        transforms = field_spec.get("transforms", [])
        if not isinstance(transforms, list):
            return ()
        for transform_spec in transforms:
            if not isinstance(transform_spec, Mapping):
                continue
            reference = transform_spec.get("type")
            if not isinstance(reference, str):
                continue
            transform = self.transforms.get(normalize_reference(reference)) or self.transforms.get(
                reference
            )
            if transform is not None:
                children.extend(
                    child for _location, child in transform.nested_specs(transform_spec)
                )
        return tuple(children)

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
        prepared: dict[str, PreparedField] = {}
        context = PreparationContext(self.registry, self._prepare_child)
        for type_key in self.field_keys:
            spec = self.types[type_key]
            generator = self.registry[runtime_type_name(spec["type"])]
            try:
                self._validate_generator_keys(f"types.{type_key}", spec, generator)
                transforms, is_paired, uses_source = self._prepare_transforms(
                    type_key, spec, generator, context
                )
                prepared[type_key] = PreparedField(
                    generator=generator,
                    source_prepared=context.prepare_generator(generator, spec),
                    transforms=transforms,
                    is_paired=is_paired,
                    source_is_paired=bool(generator.is_paired and uses_source),
                    uses_source=uses_source,
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

    def _prepare_child(
        self,
        context: PreparationContext,
        parent_type: str,
        location: str,
        nested_spec: Any,
    ) -> tuple[Generator, Any]:
        child, source_prepared = prepare_child_spec(
            parent_type,
            location,
            nested_spec,
            self.registry,
            context,
        )
        transforms, _is_paired, uses_source = self._prepare_transforms(
            f"{parent_type}.{location}", nested_spec, child, context
        )
        validators = self._resolve_validators(f"{parent_type}.{location}", nested_spec)
        if not transforms and not validators:
            return child, source_prepared
        self.has_child_pipelines = True
        return ChildPipelineGenerator(), ChildPipelineSpec(
            generator=child,
            source_prepared=source_prepared,
            transforms=transforms,
            uses_source=uses_source,
            validators=validators,
        )

    def _validate_id_references(self, prepared: Mapping[str, PreparedField]) -> None:
        for token in self.tokens:
            if token.wants_id and not prepared[token.type_key].is_paired:
                raise TemplateError(
                    f"Variable {token.type_key!r} cannot use [id] because its "
                    "generator/transform chain does not preserve pairing"
                )

    def _validate_generator_keys(
        self,
        path: str,
        spec: Mapping[str, Any],
        generator: Generator,
    ) -> None:
        error = extension_key_error(path, spec, generator.config_keys, COMMON_FIELD_KEYS)
        if error is not None:
            raise TemplateError(error)
        self._validate_child_keys(path, generator.nested_specs(spec))

    def _validate_child_keys(
        self,
        path: str,
        nested: Iterable[tuple[str, Mapping[str, Any]]],
    ) -> None:
        """Key-check declared child generator specs, whoever owns them (CFG-004).

        Generators and transforms both declare children through
        ``nested_specs``, so both reach the same validation boundary with
        path-specific diagnostics.
        """
        for location, nested_spec in nested:
            reference = nested_spec.get("type")
            if not isinstance(reference, str):
                continue
            child = self.registry.get(runtime_type_name(reference))
            if child is not None:
                self._validate_generator_keys(f"{path}.{location}", nested_spec, child)

    def _prepare_transforms(
        self,
        type_key: str,
        spec: Mapping[str, Any],
        generator: Generator,
        context: PreparationContext,
    ) -> tuple[tuple[PreparedTransform, ...], bool, bool]:
        transform_specs = self._transform_specs(type_key, spec)
        resolved = [
            (transform_spec, self._resolve_transform(type_key, transform_spec["type"]))
            for transform_spec in transform_specs
        ]
        source_independent = [
            index
            for index, (_spec, transform) in enumerate(resolved)
            if not transform.requires_source
        ]
        if source_independent and source_independent != [0]:
            raise TemplateError(
                f"Source-independent transform {resolved[source_independent[0]][0]['type']!r} "
                f"for variable {type_key!r} must be the first transform"
            )
        uses_source = not source_independent
        capability = fold_paired_capabilities(
            bool(generator.is_paired and uses_source),
            tuple(transform.capabilities for _transform_spec, transform in resolved),
        )
        if capability.incompatible_index is not None:
            reference = transform_specs[capability.incompatible_index]["type"]
            raise TemplateError(
                f"Transform {reference!r} for variable {type_key!r} does not accept paired input"
            )
        is_paired = bool(generator.is_paired and uses_source)
        prepared: list[PreparedTransform] = []
        for index, (transform_spec, transform) in enumerate(resolved):
            error = extension_key_error(
                f"types.{type_key}.transforms[{index}]",
                transform_spec,
                transform.config_keys,
                frozenset(("type",)),
            )
            if error is not None:
                raise TemplateError(error)
            self._validate_child_keys(
                f"types.{type_key}.transforms[{index}]",
                transform.nested_specs(transform_spec),
            )
            prepared.append(
                PreparedTransform(
                    transform,
                    transform.prepare(transform_spec, context),
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
            is_paired = is_paired and transform.capabilities.preserves_pairing
        return tuple(prepared), capability.preserves_pairing, uses_source

    @staticmethod
    def _transform_specs(
        type_key: str,
        spec: Mapping[str, Any],
    ) -> list[Mapping[str, Any]]:
        raw = spec.get("transforms", [])
        if not isinstance(raw, list):
            raise TemplateError(f"Transforms for variable {type_key!r} must be a list")
        for index, transform in enumerate(raw):
            if not isinstance(transform, Mapping) or not isinstance(transform.get("type"), str):
                raise TemplateError(
                    f"Transform {index} for variable {type_key!r} must be an object "
                    "with a string 'type' field"
                )
        return raw

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
        references = spec.get("validators", [])
        if not isinstance(references, list):
            raise TemplateError(f"Validators for variable {type_key!r} must be a list")
        if any(not isinstance(reference, str) for reference in references):
            raise TemplateError(f"Validator references for variable {type_key!r} must be strings")
        for reference in references:
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
