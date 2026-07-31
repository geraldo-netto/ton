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
from typing import Any, NoReturn, cast

from . import _config
from ._compiler import ResolvedToken, compile_plan
from ._compiler import TemplateError as _TemplateError
from ._logging import LogEvent
from ._logging import logger as _logger
from ._proof import (
    PreparedField,
    ProofFailure,
    ProvenanceRecord,
    TransformStep,
)
from ._proofcheck import ProofChecker, ProofFailureSink, ProofHookError
from ._transforms import Transform, TransformResult
from ._validation import ValidationError, Validator
from .generators import Generator

TemplateError = _TemplateError


class ProofError(TemplateError):
    """Raised when strict proof checking finds an invalid generated value."""


class PipelineStageError(TemplateError):
    """Base for unexpected failures attributed to one pipeline component."""

    def __init__(
        self,
        stage: str,
        reference: str,
        type_key: str,
        cause: Exception,
    ) -> None:
        self.stage = stage
        self.reference = reference
        self.type_key = type_key
        self.cause = cause
        super().__init__(
            f"{stage} {reference} for variable {type_key!r} raised {type(cause).__name__}: {cause}"
        )


class GeneratorExecutionError(PipelineStageError):
    """A source generator raised during a row draw."""


class TransformExecutionError(PipelineStageError):
    """A transform raised while applying a prepared stage."""


class ProofEvaluationError(PipelineStageError):
    """A source or transform proof hook raised unexpectedly."""


class ValidatorExecutionError(PipelineStageError):
    """A validator raised instead of returning a result."""


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
        _config.validate_structure(config)
        plan = compile_plan(
            config,
            registry=registry,
            transforms=transforms,
            validators=validators,
        )
        self._plan = plan
        self._max_row_width = _config.row_width_limit(config)
        self._rng = rng if rng is not None else Random()
        self._proof = ProofChecker(
            mode=proof_mode,
            sample_rate=proof_sample_rate,
            seed=seed,
            redact=redact_proof_failures,
        )
        self._seed = seed
        self._milestone_rows = max(0, int(milestone_rows))
        self._rows_emitted = 0
        self._iteration_lock = threading.Lock()
        self._iteration_started = False
        _logger.info(
            "engine_constructed rows=%d types=%d paired=%s",
            plan.rows,
            len(plan.types),
            plan.has_paired,
            extra={
                "event": LogEvent.ENGINE_CONSTRUCTED.value,
                "rows": plan.rows,
                "types": len(plan.types),
                "paired": plan.has_paired,
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
        return cls.from_options(
            _config.load(path),
            EngineOptions(
                seed=seed,
                registry=registry,
                transforms=transforms,
                validators=validators,
                rng=rng,
                proof_mode=proof_mode,
                proof_sample_rate=proof_sample_rate,
                milestone_rows=milestone_rows,
                redact_proof_failures=redact_proof_failures,
            ),
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
        return self._plan.rows

    @property
    def proof_failures(self) -> tuple[ProofFailure, ...]:
        """Detailed audit proof failures (bounded sample; see SCAL-001)."""
        return tuple(self._proof.failures)

    @property
    def proof_failure_count(self) -> int:
        """Total audit proof failures seen, independent of the sample cap."""
        return self._proof.failure_count

    def _set_proof_failure_sink(
        self,
        failure_sink: ProofFailureSink | None,
    ) -> None:
        """Attach the CLI-owned streaming report destination before iteration."""
        self._proof.failure_sink = failure_sink

    @property
    def provenance(self) -> tuple[ProvenanceRecord, ...]:
        """Generation metadata for each prepared template field."""
        records: list[ProvenanceRecord] = []
        seen: set[str] = set()
        for token in self._plan.tokens:
            type_key = token.type_key
            if type_key in seen:
                continue
            seen.add(type_key)
            field = self._plan.prepared[type_key]
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
            for _ in range(self._plan.rows):
                row = self._render_row()
                self._rows_emitted += 1
                if milestone and self._rows_emitted % milestone == 0:
                    _logger.info(
                        "engine_milestone rows=%d/%d",
                        self._rows_emitted,
                        self._plan.rows,
                        extra={
                            "event": LogEvent.ENGINE_MILESTONE.value,
                            "rows": self._rows_emitted,
                            "total": self._plan.rows,
                        },
                    )
                yield row
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
        paired_cache: dict[str, tuple[str, str]] | None = {} if self._plan.has_paired else None
        literals = self._plan.literals
        resolved_tokens = self._plan.resolved_tokens
        if not resolved_tokens:
            return self._bounded_row(literals[0])
        parts: list[str] = []
        for index, resolved in enumerate(resolved_tokens):
            parts.append(literals[index])
            parts.append(self._resolve(resolved, paired_cache))
        parts.append(literals[-1])
        return self._bounded_row("".join(parts))

    def _bounded_row(self, row: str) -> str:
        if self._max_row_width is not None and len(row) > self._max_row_width:
            raise TemplateError(
                f"rendered row width {len(row)} exceeds maxRowWidth ({self._max_row_width})"
            )
        return row

    def _resolve(
        self, resolved: ResolvedToken, paired_cache: dict[str, tuple[str, str]] | None
    ) -> str:
        token = resolved.token
        field = resolved.field
        if resolved.direct and not self._proof.enabled:
            return self._generate_source(token.type_key, field)
        if paired_cache is not None and field.source_is_paired:
            pair = paired_cache.get(token.type_key)
            if pair is None:
                pair = self._generate_pair(token.type_key, field)
                paired_cache[token.type_key] = pair
            return pair[0] if token.wants_id else pair[1]
        return self._generate_single(token.type_key, field)

    def _generate_source(self, type_key: str, field: PreparedField) -> str:
        try:
            return cast(str, field.generator.generate(field.source_prepared, self._rng))
        except Exception as exc:
            self._raise_pipeline_error(
                GeneratorExecutionError,
                "Generator",
                type(field.generator).__name__,
                type_key,
                exc,
            )

    def _generate_pair(self, type_key: str, field: PreparedField) -> tuple[str, str]:
        try:
            pair = field.generator.generate_pair(field.source_prepared, self._rng)
        except Exception as exc:
            self._raise_pipeline_error(
                GeneratorExecutionError,
                "Generator",
                type(field.generator).__name__,
                type_key,
                exc,
            )
        source = TransformResult(value=pair[1], id_value=pair[0])
        transformed, steps = self._apply_transforms_with_trace(type_key, field, source)
        self._handle_proof_failures(type_key, field, source, steps)
        self._run_validators(type_key, field, transformed.value)
        return (transformed.id_value or "", transformed.value)

    def _generate_single(self, type_key: str, field: PreparedField) -> str:
        source = TransformResult(
            self._generate_source(type_key, field) if field.uses_source else ""
        )
        transformed, steps = self._apply_transforms_with_trace(type_key, field, source)
        self._handle_proof_failures(type_key, field, source, steps)
        self._run_validators(type_key, field, transformed.value)
        return transformed.value

    def _run_validators(self, type_key: str, field: PreparedField, value: str) -> None:
        for validator in field.validators:
            try:
                valid = validator.validate(value)
            except Exception as exc:
                self._raise_pipeline_error(
                    ValidatorExecutionError,
                    "Validator",
                    validator.type_name,
                    type_key,
                    exc,
                )
            if not valid:
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
        try:
            failure = self._proof.evaluate(
                type_key,
                field,
                source_result,
                steps,
                rows_emitted=self._rows_emitted,
                spec=self._plan.types[type_key],
            )
        except ProofHookError as exc:
            self._raise_pipeline_error(
                ProofEvaluationError,
                f"{exc.stage.capitalize()} proof",
                exc.reference,
                type_key,
                exc.cause,
            )
        if failure is not None:
            raise ProofError(
                f"Proof failed at row {failure.row} for {failure.type_key!r} "
                f"{failure.stage} {failure.reference!r}: {failure.reason}"
            )

    def _apply_transforms_with_trace(
        self,
        type_key: str,
        field: PreparedField,
        result: TransformResult,
    ) -> tuple[TransformResult, tuple[TransformStep, ...]]:
        steps: list[TransformStep] = []
        for prepared in field.transforms:
            before = result
            try:
                result = prepared.transform.apply(prepared.prepared, before, self._rng)
            except Exception as exc:
                self._raise_pipeline_error(
                    TransformExecutionError,
                    "Transform",
                    prepared.transform.type_name,
                    type_key,
                    exc,
                )
            steps.append(TransformStep(prepared=prepared, before=before, after=result))
        return result, tuple(steps)

    def _raise_pipeline_error(
        self,
        error_type: type[PipelineStageError],
        stage: str,
        reference: str,
        type_key: str,
        cause: Exception,
    ) -> NoReturn:
        _logger.error(
            "pipeline_stage_failed stage=%s reference=%s type_key=%s row=%d error_type=%s",
            stage,
            reference,
            type_key,
            self._rows_emitted + 1,
            type(cause).__name__,
            extra={
                "event": LogEvent.GENERATE_FAILED.value,
                "stage": stage,
                "reference": reference,
                "type_key": type_key,
                "row": self._rows_emitted + 1,
                "error_type": type(cause).__name__,
            },
        )
        raise error_type(stage, reference, type_key, cause) from cause


def _rng_for_seed(seed: int | None) -> Random:
    """Return a seeded ``Random`` when ``seed`` is given, else an unseeded one.

    Single home for the ``Random(seed) if seed is not None else Random()``
    idiom that was duplicated across the engine and CLI (DEC-002).
    """
    return Random(seed) if seed is not None else Random()
