"""Row-generation engine.

Glues template parsing, the generator registry, and a deterministic RNG
together. The engine is iterable so callers can stream rows to stdout,
files, or anywhere else without buffering the full dataset in memory.
"""

from __future__ import annotations

import threading
from collections.abc import Iterator, Mapping
from dataclasses import dataclass
from random import Random
from typing import Any

from . import _config
from ._logging import LogEvent
from ._logging import logger as _logger
from ._proof import (
    PreparedField,
    PreparedTransform,
    ProofFailure,
    ProvenanceRecord,
    TransformStep,
)
from ._proofcheck import ProofChecker
from ._registry import build_extension_catalog, make_registry, normalize_reference
from ._template import Token, UndeclaredVariableError, parse, split_segments, validate_against
from ._transforms import Transform, TransformResult
from ._validation import ValidationError, Validator
from .generators import Generator


class TemplateError(ValueError):
    """Raised when a template references a type not declared in the config."""


class ProofError(TemplateError):
    """Raised when strict proof checking finds an invalid generated value."""


@dataclass(frozen=True)
class EngineOptions:
    """Bundle of engine construction options (DEC-001).

    Threading these as one value object keeps the option set defined in a
    single place: :meth:`Engine.from_options` is the one builder that
    knows how to turn them into an engine (including deriving the RNG
    from ``seed``), and the boundary helpers -- :func:`ton.api.generate`,
    :func:`ton.concurrency.fork_engine`, the CLI -- construct one instead
    of re-enumerating the same seven parameters at every call site.
    """

    registry: Mapping[str, Generator] | None = None
    transforms: Mapping[str, Transform] | None = None
    validators: Mapping[str, Validator] | None = None
    rng: Random | None = None
    proof_mode: str = "off"
    proof_sample_rate: int = 1
    seed: int | None = None
    milestone_rows: int = 0
    redact_proof_failures: bool = False


class Engine:
    """Render rows from a parsed TON config.

    An Engine is a single-shot iterator. Construct a new Engine for each
    pass so seeded RNG and generator-owned prepared state have one clear
    lifecycle.
    """

    def __init__(
        self,
        config: Mapping[str, Any],
        registry: Mapping[str, Generator] | None = None,
        transforms: Mapping[str, Transform] | None = None,
        validators: Mapping[str, Validator] | None = None,
        rng: Random | None = None,
        *,
        proof_mode: str = "off",
        proof_sample_rate: int = 1,
        seed: int | None = None,
        milestone_rows: int = 0,
        redact_proof_failures: bool = False,
    ) -> None:
        self._template: str = config["format"]
        self._types: Mapping[str, Mapping[str, Any]] = config["types"]
        self._rows: int = int(config["rows"])
        self._tokens = parse(self._template)
        self._registry = self._resolve_registry(registry)
        self._transforms = dict(
            transforms if transforms is not None else build_extension_catalog().transforms()
        )
        self._validators = dict(
            validators if validators is not None else build_extension_catalog().validators()
        )
        self._rng = rng if rng is not None else Random()
        self._proof = ProofChecker(
            mode=proof_mode,
            sample_rate=proof_sample_rate,
            seed=seed,
            redact=redact_proof_failures,
        )
        self._seed = seed
        self._validate()
        # Each referenced type spec is parsed once via Generator.prepare;
        # the per-row hot path just looks up the prepared spec by name.
        self._prepared: dict[str, PreparedField] = self._build_prepared()
        # Skip per-row paired_cache allocation when no referenced type is paired.
        self._has_paired = any(self._prepared[t.type_key].is_paired for t in self._tokens)
        # Precompute the literal segments that surround placeholders so
        # the per-row render is a straight string-join with no regex
        # pass (TODO PERF-009).
        literals, plan_tokens = split_segments(self._template)
        self._literals: list[str] = literals
        self._plan_tokens: list[Token] = plan_tokens
        self._milestone_rows = max(0, int(milestone_rows))
        self._rows_emitted = 0
        self._iteration_lock = threading.Lock()
        self._iteration_started = False
        _logger.info(
            "engine_constructed rows=%d types=%d paired=%s",
            self._rows,
            len(self._types),
            self._has_paired,
            extra={
                "event": LogEvent.ENGINE_CONSTRUCTED.value,
                "rows": self._rows,
                "types": len(self._types),
                "paired": self._has_paired,
                "milestone_rows": self._milestone_rows,
            },
        )

    @classmethod
    def from_options(cls, config: Mapping[str, Any], options: EngineOptions) -> Engine:
        """Build an Engine from a config and an :class:`EngineOptions`.

        The single builder that turns the bundled option set into an
        engine, deriving the RNG from ``seed`` when ``rng`` is None so
        that RNG-construction defaults live in exactly one place
        (DEC-001, DEC-002).
        """
        engine_rng = options.rng if options.rng is not None else _rng_for_seed(options.seed)
        return cls(
            config,
            registry=options.registry,
            transforms=options.transforms,
            validators=options.validators,
            rng=engine_rng,
            proof_mode=options.proof_mode,
            proof_sample_rate=options.proof_sample_rate,
            seed=options.seed,
            milestone_rows=options.milestone_rows,
            redact_proof_failures=options.redact_proof_failures,
        )

    @classmethod
    def from_config(
        cls,
        config: Mapping[str, Any],
        *,
        seed: int | None = None,
        registry: Mapping[str, Generator] | None = None,
        transforms: Mapping[str, Transform] | None = None,
        validators: Mapping[str, Validator] | None = None,
        rng: Random | None = None,
        proof_mode: str = "off",
        proof_sample_rate: int = 1,
        milestone_rows: int = 0,
        redact_proof_failures: bool = False,
    ) -> Engine:
        """Build an Engine, deriving the RNG from ``seed`` when ``rng`` is None.

        Thin keyword-friendly wrapper over :meth:`from_options` used by
        :mod:`ton.api` and :mod:`ton.concurrency`.
        """
        return cls.from_options(
            config,
            EngineOptions(
                registry=registry,
                transforms=transforms,
                validators=validators,
                rng=rng,
                proof_mode=proof_mode,
                proof_sample_rate=proof_sample_rate,
                seed=seed,
                milestone_rows=milestone_rows,
                redact_proof_failures=redact_proof_failures,
            ),
        )

    @classmethod
    def from_file(
        cls,
        path: str,
        *,
        seed: int | None = None,
        registry: Mapping[str, Generator] | None = None,
        transforms: Mapping[str, Transform] | None = None,
        validators: Mapping[str, Validator] | None = None,
        rng: Random | None = None,
        proof_mode: str = "off",
        proof_sample_rate: int = 1,
        milestone_rows: int = 0,
        redact_proof_failures: bool = False,
    ) -> Engine:
        """Build an Engine from a JSON config on disk.

        Wraps :func:`ton._config.load` + :meth:`from_config` so callers
        do not need to import the private config module just to load a
        file (TODO PAT-009). Accepts ``seed`` for parity with
        :meth:`from_config`; when ``rng`` is also given, ``rng`` wins and
        ``seed`` is recorded only as proof/provenance context.
        """
        return cls.from_config(
            _config.load(path),
            seed=seed,
            registry=registry,
            transforms=transforms,
            validators=validators,
            rng=rng,
            proof_mode=proof_mode,
            proof_sample_rate=proof_sample_rate,
            milestone_rows=milestone_rows,
            redact_proof_failures=redact_proof_failures,
        )

    @property
    def rows_emitted(self) -> int:
        """Number of rows yielded by the most recent / current iteration.

        Public counterpart of the private ``count`` previously kept only
        for the milestone log (TODO SCALE-004). Library callers can
        watch this attribute from another thread to monitor progress.
        """
        return self._rows_emitted

    @property
    def total_rows(self) -> int:
        """Total rows the engine will yield when iterated to completion."""
        return self._rows

    @property
    def proof_failures(self) -> tuple[ProofFailure, ...]:
        """Detailed audit proof failures (bounded sample; see SCAL-001)."""
        return tuple(self._proof.failures)

    @property
    def proof_failure_count(self) -> int:
        """Total audit proof failures seen, independent of the sample cap."""
        return self._proof.failure_count

    @property
    def provenance(self) -> tuple[ProvenanceRecord, ...]:
        """Generation metadata for each prepared template field."""
        records: list[ProvenanceRecord] = []
        seen: set[str] = set()
        for token in self._tokens:
            type_key = token.type_key
            if type_key in seen:
                continue
            seen.add(type_key)
            field = self._prepared[type_key]
            generator = field.generator
            failures = self._proof.failure_counts.get(type_key, 0)
            records.append(
                ProvenanceRecord(
                    type_key=type_key,
                    source_type=generator.type_name,
                    transforms=tuple(prepared.transform.type_name for prepared in field.transforms),
                    proof_mode=self._proof.mode,
                    proof_sample_rate=self._proof.sample_rate,
                    proof_failures=failures,
                    plugin_package=getattr(generator, "_ton_plugin_package", None),
                    plugin_version=getattr(generator, "_ton_plugin_version", None),
                )
            )
        return tuple(records)

    def _resolve_registry(
        self, registry: Mapping[str, Generator] | None
    ) -> Mapping[str, Generator]:
        if registry is not None:
            return dict(registry)
        # Build only the generator instances the template references so
        # constructing an Engine for a one-type config does not allocate
        # the other 19 built-ins (TODO PERF-012). Tokens referencing
        # undeclared variables are tolerated here so the real diagnostic
        # comes from :meth:`_validate` instead of a ``KeyError``. The
        # walk recurses into composite specs (e.g. ``weighted``'s
        # ``choices``) so nested types are present at prepare time.
        root_specs: list[Mapping[str, Any]] = []
        root_types: set[str] = set()
        for token in self._tokens:
            spec = self._types.get(token.type_key)
            if isinstance(spec, Mapping) and "type" in spec:
                root_specs.append(spec)
                root_types.add(_runtime_type_name(spec["type"]))
        roots = make_registry(root_types)
        needed = set(root_types)
        for spec in root_specs:
            generator = roots.get(_runtime_type_name(spec["type"]))
            if generator is not None:
                needed.update(_runtime_type_name(name) for name in generator.nested_types(spec))
        return make_registry(needed)

    def _validate(self) -> None:
        try:
            validate_against(self._template, self._types.keys())
        except UndeclaredVariableError as exc:
            raise TemplateError(str(exc)) from exc
        for token in self._tokens:
            type_name = _runtime_type_name(self._types[token.type_key]["type"])
            if type_name not in self._registry:
                raise TemplateError(f"Unknown type {type_name!r} for variable {token.type_key!r}")

    def _build_prepared(self) -> dict[str, PreparedField]:
        prepared: dict[str, PreparedField] = {}
        for token in self._tokens:
            if token.type_key in prepared:
                continue
            spec = self._types[token.type_key]
            generator = self._registry[_runtime_type_name(spec["type"])]
            try:
                if generator.is_composite:
                    source_prepared = generator.prepare_composite(spec, self._registry)
                else:
                    source_prepared = generator.prepare(spec)
                prepared[token.type_key] = PreparedField(
                    generator=generator,
                    source_prepared=source_prepared,
                    transforms=self._prepare_transforms(token.type_key, spec, generator),
                    validators=self._resolve_validators(token.type_key, spec),
                )
            except Exception as exc:  # noqa: BLE001 - boundary; re-raised below
                # Surface the failing spec to log handlers before
                # collapsing the exception to a TemplateError so a
                # buggy third-party generator can be attributed
                # without an interpreter traceback (TODO OBS-004).
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
        self,
        type_key: str,
        spec: Mapping[str, Any],
        generator: Generator,
    ) -> tuple[PreparedTransform, ...]:
        is_paired = bool(generator.is_paired)
        prepared: list[PreparedTransform] = []
        for transform_spec in spec.get("transforms", []):
            transform = self._resolve_transform(type_key, transform_spec["type"])
            if is_paired and not transform.capabilities.accepts_paired:
                raise TemplateError(
                    f"Transform {transform_spec['type']!r} for variable "
                    f"{type_key!r} does not accept paired input"
                )
            prepared.append(
                PreparedTransform(
                    transform,
                    transform.prepare_composite(transform_spec, self._registry),
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
        return tuple(prepared)

    def _resolve_transform(self, type_key: str, reference: str) -> Transform:
        normalized = normalize_reference(reference)
        if normalized in self._transforms:
            return self._transforms[normalized]
        if reference in self._transforms:
            return self._transforms[reference]
        raise TemplateError(f"Unknown transform {reference!r} for variable {type_key!r}")

    def _resolve_validators(self, type_key: str, spec: Mapping[str, Any]) -> tuple[Validator, ...]:
        resolved: list[Validator] = []
        for reference in spec.get("validators", []):
            normalized = normalize_reference(reference)
            validator = self._validators.get(normalized) or self._validators.get(reference)
            if validator is None:
                raise TemplateError(f"Unknown validator {reference!r} for variable {type_key!r}")
            resolved.append(validator)
        return tuple(resolved)

    def __iter__(self) -> Iterator[str]:
        if not self._iteration_lock.acquire(blocking=False):
            raise RuntimeError("Engine instances cannot be iterated concurrently")
        if self._iteration_started:
            self._iteration_lock.release()
            raise RuntimeError("Engine instances are single-shot and cannot be iterated twice")
        self._iteration_started = True
        return self._iterate()

    def __getstate__(self) -> dict[str, Any]:
        """Return pickle state without the process-local iteration lock."""
        state = self.__dict__.copy()
        state.pop("_iteration_lock", None)
        return state

    def __setstate__(self, state: dict[str, Any]) -> None:
        """Restore pickle state with a new process-local iteration lock."""
        self.__dict__.update(state)
        self._iteration_lock = threading.Lock()

    def _iterate(self) -> Iterator[str]:
        try:
            milestone = self._milestone_rows
            self._rows_emitted = 0
            self._proof.reset()
            for _ in range(self._rows):
                yield self._render_row()
                self._rows_emitted += 1
                if milestone and self._rows_emitted % milestone == 0:
                    _logger.info(
                        "engine_milestone rows=%d/%d",
                        self._rows_emitted,
                        self._rows,
                        extra={
                            "event": LogEvent.ENGINE_MILESTONE.value,
                            "rows": self._rows_emitted,
                            "total": self._rows,
                        },
                    )
            _logger.info(
                "engine_completed rows=%d",
                self._rows_emitted,
                extra={
                    "event": LogEvent.ENGINE_COMPLETED.value,
                    "rows": self._rows_emitted,
                },
            )
            self._proof.log_summary()
        finally:
            self._iteration_lock.release()

    def _render_row(self) -> str:
        paired_cache: dict[str, tuple[str, str]] | None = {} if self._has_paired else None
        literals = self._literals
        plan_tokens = self._plan_tokens
        if not plan_tokens:
            return literals[0]
        parts: list[str] = []
        for index, token in enumerate(plan_tokens):
            parts.append(literals[index])
            parts.append(self._resolve(token, paired_cache))
        parts.append(literals[-1])
        return "".join(parts)

    def _resolve(self, token: Token, paired_cache: dict[str, tuple[str, str]] | None) -> str:
        field = self._prepared[token.type_key]
        generator = field.generator
        try:
            if paired_cache is not None and field.is_paired:
                pair = paired_cache.get(token.type_key)
                if pair is None:
                    pair = self._generate_pair(token.type_key, field)
                    paired_cache[token.type_key] = pair
                return pair[0] if token.wants_id else pair[1]
            return self._generate_single(token.type_key, field)
        except (ProofError, ValidationError):
            raise
        except Exception as exc:  # noqa: BLE001 - boundary; re-raised below
            # A generator that raises mid-iteration would otherwise hit
            # the CLI's catch-all (TODO REL-014). Log an identifying
            # event before letting it propagate as TemplateError.
            _logger.error(
                "generate_failed type_key=%s generator_type=%s row=%d error=%s",
                token.type_key,
                type(generator).__name__,
                self._rows_emitted + 1,
                exc,
                extra={
                    "event": LogEvent.GENERATE_FAILED.value,
                    "type_key": token.type_key,
                    "generator_type": type(generator).__name__,
                    "row": self._rows_emitted + 1,
                    "error": f"{type(exc).__name__}: {exc}",
                },
            )
            raise TemplateError(
                f"Generator {type(generator).__name__} for variable "
                f"{token.type_key!r} raised {type(exc).__name__}: {exc}"
            ) from exc

    def _generate_pair(self, type_key: str, field: PreparedField) -> tuple[str, str]:
        pair = field.generator.generate_pair(field.source_prepared, self._rng)
        source = TransformResult(value=pair[1], id_value=pair[0])
        transformed, steps = self._apply_transforms_with_trace(field, source)
        self._handle_proof_failures(type_key, field, source, steps)
        self._run_validators(type_key, field, transformed.value)
        return (transformed.id_value or "", transformed.value)

    def _generate_single(self, type_key: str, field: PreparedField) -> str:
        source = TransformResult(field.generator.generate(field.source_prepared, self._rng))
        transformed, steps = self._apply_transforms_with_trace(field, source)
        self._handle_proof_failures(type_key, field, source, steps)
        self._run_validators(type_key, field, transformed.value)
        return transformed.value

    def _run_validators(self, type_key: str, field: PreparedField, value: str) -> None:
        for validator in field.validators:
            if not validator.validate(value):
                raise ValidationError(
                    f"Value {value!r} for variable {type_key!r} failed "
                    f"validator {validator.type_name!r}"
                )

    def _handle_proof_failures(
        self,
        type_key: str,
        field: PreparedField,
        source_result: TransformResult,
        steps: tuple[TransformStep, ...],
    ) -> None:
        failure = self._proof.evaluate(
            type_key,
            field,
            source_result,
            steps,
            rows_emitted=self._rows_emitted,
            spec=self._types[type_key],
        )
        if failure is not None:
            raise ProofError(
                f"Proof failed at row {failure.row} for {failure.type_key!r} "
                f"{failure.stage} {failure.reference!r}: {failure.reason}"
            )

    def _apply_transforms_with_trace(
        self,
        field: PreparedField,
        result: TransformResult,
    ) -> tuple[TransformResult, tuple[TransformStep, ...]]:
        steps: list[TransformStep] = []
        for prepared in field.transforms:
            before = result
            result = prepared.transform.apply(prepared.prepared, before, self._rng)
            steps.append(TransformStep(prepared=prepared, before=before, after=result))
        return result, tuple(steps)


def _rng_for_seed(seed: int | None) -> Random:
    """Return a seeded ``Random`` when ``seed`` is given, else an unseeded one.

    Single home for the ``Random(seed) if seed is not None else Random()``
    idiom that was duplicated across the engine and CLI (DEC-002).
    """
    return Random(seed) if seed is not None else Random()


def _runtime_type_name(type_name: object) -> str:
    if isinstance(type_name, str) and type_name.startswith("core."):
        return type_name.split(".", 1)[1]
    return str(type_name)
