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
from typing import Any, cast

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
from ._proofcheck import ProofChecker
from ._transforms import Transform, TransformResult
from ._validation import ValidationError, Validator
from .generators import Generator

TemplateError = _TemplateError


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
        _config.validate_structure(config)
        plan = compile_plan(
            config,
            registry=registry,
            transforms=transforms,
            validators=validators,
        )
        self._plan = plan
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
            return literals[0]
        parts: list[str] = []
        for index, resolved in enumerate(resolved_tokens):
            parts.append(literals[index])
            parts.append(self._resolve(resolved, paired_cache))
        parts.append(literals[-1])
        return "".join(parts)

    def _resolve(
        self, resolved: ResolvedToken, paired_cache: dict[str, tuple[str, str]] | None
    ) -> str:
        token = resolved.token
        field = resolved.field
        generator = field.generator
        try:
            if resolved.direct and not self._proof.enabled:
                return cast(str, generator.generate(field.source_prepared, self._rng))
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
                "generate_failed type_key=%s generator_type=%s row=%d error_type=%s",
                token.type_key,
                type(generator).__name__,
                self._rows_emitted + 1,
                type(exc).__name__,
                extra={
                    "event": LogEvent.GENERATE_FAILED.value,
                    "type_key": token.type_key,
                    "generator_type": type(generator).__name__,
                    "row": self._rows_emitted + 1,
                    "error_type": type(exc).__name__,
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
            spec=self._plan.types[type_key],
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
