"""Row-generation engine.

Glues template parsing, the generator registry, and a deterministic RNG
together. The engine is iterable so callers can stream rows to stdout,
files, or anywhere else without buffering the full dataset in memory.
"""

from __future__ import annotations

from random import Random
from typing import Any, Dict, Iterator, Mapping, Optional, Tuple

from .generators import Generator, PairedGenerator
from ._registry import default_registry
from ._template import Token, UndeclaredVariableError, parse, render, validate_against


class TemplateError(ValueError):
    """Raised when a template references a type not declared in the config."""


class Engine:
    """Render rows from a parsed TON config."""

    def __init__(
        self,
        config: Mapping[str, Any],
        registry: Optional[Mapping[str, Generator]] = None,
        rng: Optional[Random] = None,
    ) -> None:
        self._template: str = config["format"]
        self._types: Mapping[str, Mapping[str, Any]] = config["types"]
        self._rows: int = int(config["rows"])
        self._registry = dict(registry) if registry is not None else default_registry()
        self._rng = rng if rng is not None else Random()
        self._tokens = parse(self._template)
        self._validate()
        # Each referenced type spec is parsed once via Generator.prepare;
        # the per-row hot path just looks up the prepared spec by name.
        self._prepared: Dict[str, Tuple[Generator, Any]] = self._build_prepared()
        # Skip per-row paired_cache allocation when no referenced type is paired.
        self._has_paired = any(
            self._prepared[t.type_key][0].is_paired for t in self._tokens
        )

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

    def _build_prepared(self) -> Dict[str, Tuple[Generator, Any]]:
        prepared: Dict[str, Tuple[Generator, Any]] = {}
        for token in self._tokens:
            if token.type_key in prepared:
                continue
            spec = self._types[token.type_key]
            generator = self._registry[spec["type"]]
            try:
                prepared[token.type_key] = (generator, generator.prepare(spec))
            except Exception as exc:  # noqa: BLE001 - boundary; re-raised below
                # Catch broadly so a buggy third-party generator that raises
                # AttributeError / RuntimeError / etc. still surfaces as a
                # clean TemplateError instead of leaking a traceback (REL-012).
                raise TemplateError(
                    f"Invalid spec for variable {token.type_key!r}: "
                    f"{type(exc).__name__}: {exc}"
                ) from exc
        return prepared

    def __iter__(self) -> Iterator[str]:
        for _ in range(self._rows):
            yield self._render_row()

    def _render_row(self) -> str:
        paired_cache: Optional[dict[str, tuple[str, str]]] = {} if self._has_paired else None
        values: dict[str, str] = {}
        for token in self._tokens:
            values[token.placeholder] = self._resolve(token, paired_cache)
        return render(self._template, values)

    def _resolve(
        self, token: Token, paired_cache: Optional[dict[str, tuple[str, str]]]
    ) -> str:
        generator, prepared = self._prepared[token.type_key]
        if paired_cache is not None and isinstance(generator, PairedGenerator):
            pair = paired_cache.get(token.type_key)
            if pair is None:
                pair = generator.generate_pair(prepared, self._rng)
                paired_cache[token.type_key] = pair
            return pair[0] if token.wants_id else pair[1]
        return generator.generate(prepared, self._rng)
