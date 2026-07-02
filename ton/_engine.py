"""Row-generation engine.

Glues template parsing, the generator registry, and a deterministic RNG
together. The engine is iterable so callers can stream rows to stdout,
files, or anywhere else without buffering the full dataset in memory.
"""

from __future__ import annotations

import threading
from collections.abc import Iterator, Mapping
from dataclasses import dataclass
from functools import cached_property
from random import Random
from typing import Any

from . import _config
from ._logging import LogEvent
from ._logging import logger as _logger
from ._proof import ProofFailure, ProvenanceRecord
from ._proofcheck import ProofChecker
from ._registry import build_extension_catalog, make_registry, normalize_reference
from ._template import Token, UndeclaredVariableError, parse, split_segments, validate_against
from ._transforms import Transform, TransformResult
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
    rng: Random | None = None
    proof_mode: str = "off"
    proof_sample_rate: int = 1
    seed: int | None = None
    milestone_rows: int = 0


@dataclass(frozen=True)
class PreparedTransform:
    transform: Transform
    prepared: Any


@dataclass(frozen=True)
class PreparedField:
    generator: Generator
    source_prepared: Any
    transforms: tuple[PreparedTransform, ...]

    @cached_property
    def is_paired(self) -> bool:
        # Cached because _resolve reads it per token per row on the hot
        # path; the value is fixed once the field is prepared (PERF-002).
        # cached_property writes through __dict__, so it works on this
        # frozen dataclass.
        if not self.transforms:
            return self.generator.is_paired
        last = self.transforms[-1].transform
        return self.generator.is_paired and last.capabilities.preserves_pairing


@dataclass(frozen=True)
class TransformStep:
    prepared: PreparedTransform
    before: TransformResult
    after: TransformResult


class Engine:
    """Render rows from a parsed TON config."""

    def __init__(
        self,
        config: Mapping[str, Any],
        registry: Mapping[str, Generator] | None = None,
        transforms: Mapping[str, Transform] | None = None,
        rng: Random | None = None,
        *,
        proof_mode: str = "off",
        proof_sample_rate: int = 1,
        seed: int | None = None,
        milestone_rows: int = 0,
    ) -> None:
        self._template: str = config["format"]
        self._types: Mapping[str, Mapping[str, Any]] = config["types"]
        self._rows: int = int(config["rows"])
        self._tokens = parse(self._template)
        self._registry = self._resolve_registry(registry)
        self._transforms = dict(transforms or build_extension_catalog().transforms())
        self._rng = rng if rng is not None else Random()
        self._proof = ProofChecker(mode=proof_mode, sample_rate=proof_sample_rate, seed=seed)
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
            rng=engine_rng,
            proof_mode=options.proof_mode,
            proof_sample_rate=options.proof_sample_rate,
            seed=options.seed,
            milestone_rows=options.milestone_rows,
        )

    @classmethod
    def from_config(
        cls,
        config: Mapping[str, Any],
        *,
        seed: int | None = None,
        registry: Mapping[str, Generator] | None = None,
        transforms: Mapping[str, Transform] | None = None,
        rng: Random | None = None,
        proof_mode: str = "off",
        proof_sample_rate: int = 1,
        milestone_rows: int = 0,
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
                rng=rng,
                proof_mode=proof_mode,
                proof_sample_rate=proof_sample_rate,
                seed=seed,
                milestone_rows=milestone_rows,
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
        rng: Random | None = None,
        proof_mode: str = "off",
        proof_sample_rate: int = 1,
        milestone_rows: int = 0,
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
            rng=rng,
            proof_mode=proof_mode,
            proof_sample_rate=proof_sample_rate,
            milestone_rows=milestone_rows,
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
        """Proof failures collected in audit mode."""
        return tuple(self._proof.failures)

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
            failures = sum(1 for failure in self._proof.failures if failure.type_key == type_key)
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
        needed: set[str] = set()
        for token in self._tokens:
            spec = self._types.get(token.type_key)
            if isinstance(spec, Mapping) and "type" in spec:
                _collect_nested_types(spec, needed)
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

    def __iter__(self) -> Iterator[str]:
        if not self._iteration_lock.acquire(blocking=False):
            raise RuntimeError("Engine instances cannot be iterated concurrently")
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
        except ProofError:
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
        pair = field.generator.generate_pair(field.source_prepared, self._rng)  # type: ignore[attr-defined]
        source = TransformResult(value=pair[1], id_value=pair[0])
        transformed, steps = self._apply_transforms_with_trace(field, source)
        self._handle_proof_failures(type_key, field, source, steps)
        return (transformed.id_value or "", transformed.value)

    def _generate_single(self, type_key: str, field: PreparedField) -> str:
        source = TransformResult(field.generator.generate(field.source_prepared, self._rng))
        transformed, steps = self._apply_transforms_with_trace(field, source)
        self._handle_proof_failures(type_key, field, source, steps)
        return transformed.value

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


def _collect_nested_types(spec: Mapping[str, Any], needed: set[str]) -> None:
    """Walk ``spec`` collecting every ``type`` referenced inside it.

    Composite specs (e.g. ``weighted`` with ``choices``) embed nested
    type specs the engine's lazy registry would otherwise miss. The
    walk recurses through any list/dict value, picking up ``type``
    keys at every level.
    """
    type_name = spec.get("type")
    if isinstance(type_name, str):
        needed.add(_runtime_type_name(type_name))
    for value in spec.values():
        _walk_value_for_types(value, needed)


def _walk_value_for_types(value: Any, needed: set[str]) -> None:
    if isinstance(value, Mapping):
        if "type" in value and isinstance(value["type"], str):
            _collect_nested_types(value, needed)
            return
        for inner in value.values():
            _walk_value_for_types(inner, needed)
        return
    if isinstance(value, list):
        for item in value:
            _walk_value_for_types(item, needed)


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
