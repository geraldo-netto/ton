"""Compile-time plan contract for the runtime Engine."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any

from ._logging import LogEvent
from ._logging import logger as _logger
from ._proof import PreparedField, PreparedTransform
from ._registry import (
    build_extension_catalog,
    make_registry,
    normalize_reference,
    runtime_type_name,
)
from ._template import Token, UndeclaredVariableError, parse, split_segments, validate_against
from ._transforms import Transform, fold_paired_capabilities
from ._validation import Validator
from .generators import Generator


@dataclass(frozen=True)
class CompiledPlan:
    """Immutable configuration artifacts required by row generation."""

    template: str
    types: Mapping[str, Mapping[str, Any]]
    rows: int
    tokens: tuple[Token, ...]
    registry: Mapping[str, Generator]
    transforms: Mapping[str, Transform]
    validators: Mapping[str, Validator]
    prepared: Mapping[str, PreparedField]
    has_paired: bool
    literals: tuple[str, ...]
    plan_tokens: tuple[Token, ...]
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
    ) -> None:
        self.template = str(config["format"])
        self.types: Mapping[str, Mapping[str, Any]] = config["types"]
        self.rows = int(config["rows"])
        self.tokens = tuple(parse(self.template))
        self.registry = self._resolve_registry(registry)
        catalog = build_extension_catalog()
        self.transforms = dict(transforms if transforms is not None else catalog.transforms())
        self.validators = dict(validators if validators is not None else catalog.validators())

    def compile(self) -> CompiledPlan:
        self._validate()
        prepared = self._build_prepared()
        literals, plan_tokens = split_segments(self.template)
        resolved_tokens = tuple(
            ResolvedToken(token, prepared[token.type_key], prepared[token.type_key].is_direct)
            for token in plan_tokens
        )
        return CompiledPlan(
            template=self.template,
            types=self.types,
            rows=self.rows,
            tokens=self.tokens,
            registry=self.registry,
            transforms=self.transforms,
            validators=self.validators,
            prepared=prepared,
            has_paired=any(prepared[token.type_key].is_paired for token in self.tokens),
            literals=tuple(literals),
            plan_tokens=tuple(plan_tokens),
            resolved_tokens=resolved_tokens,
        )

    def _resolve_registry(
        self, registry: Mapping[str, Generator] | None
    ) -> Mapping[str, Generator]:
        if registry is not None:
            return dict(registry)
        root_specs: list[Mapping[str, Any]] = []
        root_types: set[str] = set()
        for token in self.tokens:
            spec = self.types.get(token.type_key)
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
        try:
            validate_against(self.template, self.types.keys())
        except UndeclaredVariableError as exc:
            raise TemplateError(str(exc)) from exc
        for token in self.tokens:
            type_name = runtime_type_name(self.types[token.type_key]["type"])
            if type_name not in self.registry:
                raise TemplateError(f"Unknown type {type_name!r} for variable {token.type_key!r}")

    def _build_prepared(self) -> dict[str, PreparedField]:
        from .generators.base import PreparationContext

        prepared: dict[str, PreparedField] = {}
        context = PreparationContext(self.registry)
        for token in self.tokens:
            if token.type_key in prepared:
                continue
            spec = self.types[token.type_key]
            generator = self.registry[runtime_type_name(spec["type"])]
            try:
                prepared[token.type_key] = PreparedField(
                    generator=generator,
                    source_prepared=context.prepare_generator(generator, spec),
                    transforms=self._prepare_transforms(token.type_key, spec, generator),
                    validators=self._resolve_validators(token.type_key, spec),
                )
            except Exception as exc:  # noqa: BLE001
                _logger.warning(
                    "prepare_failed type_key=%s generator_type=%s error=%s",
                    token.type_key,
                    type(generator).__name__,
                    exc,
                    extra={
                        "event": LogEvent.PREPARE_FAILED.value,
                        "type_key": token.type_key,
                        "generator_type": type(generator).__name__,
                        "error": f"{type(exc).__name__}: {exc}",
                    },
                )
                raise TemplateError(
                    f"Invalid spec for variable {token.type_key!r}: {type(exc).__name__}: {exc}"
                ) from exc
        return prepared

    def _prepare_transforms(
        self, type_key: str, spec: Mapping[str, Any], generator: Generator
    ) -> tuple[PreparedTransform, ...]:
        is_paired = bool(generator.is_paired)
        prepared: list[PreparedTransform] = []
        for transform_spec in spec.get("transforms", []):
            transform = self._resolve_transform(type_key, transform_spec["type"])
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
            raise TemplateError(f"Unknown transform {reference!r} for variable {type_key!r}")
        return transform

    def _resolve_validators(self, type_key: str, spec: Mapping[str, Any]) -> tuple[Validator, ...]:
        resolved: list[Validator] = []
        for reference in spec.get("validators", []):
            normalized = normalize_reference(reference)
            validator = self.validators.get(normalized) or self.validators.get(reference)
            if validator is None:
                raise TemplateError(f"Unknown validator {reference!r} for variable {type_key!r}")
            resolved.append(validator)
        return tuple(resolved)


def compile_plan(
    config: Mapping[str, Any],
    *,
    registry: Mapping[str, Generator] | None = None,
    transforms: Mapping[str, Transform] | None = None,
    validators: Mapping[str, Validator] | None = None,
) -> CompiledPlan:
    """Compile one config through the canonical compiler boundary."""
    return EngineCompiler(config, registry, transforms, validators).compile()
