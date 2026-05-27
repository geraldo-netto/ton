"""Row-generation engine.

Glues template parsing, the generator registry, and a deterministic RNG
together. The engine is iterable so callers can stream rows to stdout,
files, or anywhere else without buffering the full dataset in memory.
"""

from __future__ import annotations

from collections.abc import Iterator, Mapping
from random import Random
from typing import Any

from . import _config
from ._logging import logger as _logger
from ._registry import make_registry
from ._template import Token, UndeclaredVariableError, parse, split_segments, validate_against
from .generators import Generator


class TemplateError(ValueError):
    """Raised when a template references a type not declared in the config."""


class Engine:
    """Render rows from a parsed TON config."""

    def __init__(
        self,
        config: Mapping[str, Any],
        registry: Mapping[str, Generator] | None = None,
        rng: Random | None = None,
        *,
        milestone_rows: int = 0,
    ) -> None:
        self._template: str = config["format"]
        self._types: Mapping[str, Mapping[str, Any]] = config["types"]
        self._rows: int = int(config["rows"])
        self._tokens = parse(self._template)
        self._registry = self._resolve_registry(registry)
        self._rng = rng if rng is not None else Random()
        self._validate()
        # Each referenced type spec is parsed once via Generator.prepare;
        # the per-row hot path just looks up the prepared spec by name.
        self._prepared: dict[str, tuple[Generator, Any]] = self._build_prepared()
        # Skip per-row paired_cache allocation when no referenced type is paired.
        self._has_paired = any(
            self._prepared[t.type_key][0].is_paired for t in self._tokens
        )
        # Precompute the literal segments that surround placeholders so
        # the per-row render is a straight string-join with no regex
        # pass (TODO PERF-009).
        literals, plan_tokens = split_segments(self._template)
        self._literals: list[str] = literals
        self._plan_tokens: list[Token] = plan_tokens
        self._milestone_rows = max(0, int(milestone_rows))
        self._rows_emitted = 0
        _logger.info(
            "engine_constructed rows=%d types=%d paired=%s",
            self._rows,
            len(self._types),
            self._has_paired,
            extra={
                "event": "engine_constructed",
                "rows": self._rows,
                "types": len(self._types),
                "paired": self._has_paired,
                "milestone_rows": self._milestone_rows,
            },
        )

    @classmethod
    def from_config(
        cls,
        config: Mapping[str, Any],
        *,
        seed: int | None = None,
        registry: Mapping[str, Generator] | None = None,
        rng: Random | None = None,
        milestone_rows: int = 0,
    ) -> Engine:
        """Build an Engine, deriving the RNG from ``seed`` when ``rng`` is None.

        Single entry point used by :mod:`ton.api` and
        :mod:`ton.concurrency` so RNG-construction defaults stay in one
        place (TODO DEC-004).
        """
        engine_rng = rng if rng is not None else (
            Random(seed) if seed is not None else Random()
        )
        return cls(
            config,
            registry=registry,
            rng=engine_rng,
            milestone_rows=milestone_rows,
        )

    @classmethod
    def from_file(
        cls,
        path: str,
        *,
        registry: Mapping[str, Generator] | None = None,
        rng: Random | None = None,
        milestone_rows: int = 0,
    ) -> Engine:
        """Build an Engine from a JSON config on disk.

        Wraps :func:`ton._config.load` + the regular constructor so
        callers do not need to import the private config module just to
        load a file (TODO PAT-009).
        """
        return cls(
            _config.load(path),
            registry=registry,
            rng=rng,
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
            type_name = self._types[token.type_key]["type"]
            if type_name not in self._registry:
                raise TemplateError(
                    f"Unknown type {type_name!r} for variable {token.type_key!r}"
                )

    def _build_prepared(self) -> dict[str, tuple[Generator, Any]]:
        prepared: dict[str, tuple[Generator, Any]] = {}
        for token in self._tokens:
            if token.type_key in prepared:
                continue
            spec = self._types[token.type_key]
            generator = self._registry[spec["type"]]
            try:
                if generator.is_composite:
                    prepared[token.type_key] = (
                        generator,
                        generator.prepare_composite(spec, self._registry),
                    )
                    continue
                prepared[token.type_key] = (generator, generator.prepare(spec))
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
                        "event": "prepare_failed",
                        "type_key": token.type_key,
                        "generator_type": type(generator).__name__,
                        "error": f"{type(exc).__name__}: {exc}",
                    },
                )
                raise TemplateError(
                    f"Invalid spec for variable {token.type_key!r}: "
                    f"{type(exc).__name__}: {exc}"
                ) from exc
        return prepared

    def __iter__(self) -> Iterator[str]:
        milestone = self._milestone_rows
        self._rows_emitted = 0
        for _ in range(self._rows):
            yield self._render_row()
            self._rows_emitted += 1
            if milestone and self._rows_emitted % milestone == 0:
                _logger.info(
                    "engine_milestone rows=%d/%d",
                    self._rows_emitted,
                    self._rows,
                    extra={
                        "event": "engine_milestone",
                        "rows": self._rows_emitted,
                        "total": self._rows,
                    },
                )
        _logger.info(
            "engine_completed rows=%d",
            self._rows_emitted,
            extra={"event": "engine_completed", "rows": self._rows_emitted},
        )

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

    def _resolve(
        self, token: Token, paired_cache: dict[str, tuple[str, str]] | None
    ) -> str:
        generator, prepared = self._prepared[token.type_key]
        try:
            if paired_cache is not None and generator.is_paired:
                pair = paired_cache.get(token.type_key)
                if pair is None:
                    pair = generator.generate_pair(prepared, self._rng)  # type: ignore[attr-defined]
                    paired_cache[token.type_key] = pair
                return pair[0] if token.wants_id else pair[1]
            return generator.generate(prepared, self._rng)
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
                    "event": "generate_failed",
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


def _collect_nested_types(spec: Mapping[str, Any], needed: set[str]) -> None:
    """Walk ``spec`` collecting every ``type`` referenced inside it.

    Composite specs (e.g. ``weighted`` with ``choices``) embed nested
    type specs the engine's lazy registry would otherwise miss. The
    walk recurses through any list/dict value, picking up ``type``
    keys at every level.
    """
    type_name = spec.get("type")
    if isinstance(type_name, str):
        needed.add(type_name)
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
