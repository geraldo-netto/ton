"""Public, library-facing facade for TON.

This is the *only* module external callers should import from.
:mod:`ton._engine`, :mod:`ton._template`, :mod:`ton._registry`, and
:mod:`ton._config` are private (single leading underscore, per PEP 8)
and may change between releases without notice (TODO ARCH-004).

The supported surface, re-exported here, is:

* :func:`load_config` -- read and validate a JSON config file
* :func:`generate` / :func:`generate_from_file` -- iterators of rows
* :func:`build_registry` -- a fresh generator registry
* :data:`ConfigError`, :data:`TemplateError`,
  :data:`UndeclaredVariableError` -- the exception types
* :class:`Engine` -- the iterator class, for callers that want to
  drive iteration themselves or inspect the engine
* :class:`Generator`, :class:`PairedGenerator` -- the strategy types
  third-party generators subclass

Typical use::

    from ton import api

    rows = list(api.generate_from_file("examples/dna.json", seed=42))

    # Streaming form for large outputs:
    for row in api.generate(config_dict, seed=42):
        sink.write(row)

    # Inject a custom registry (or extend the default one):
    registry = api.build_registry(include_entry_points=True)
    registry["uuid"] = MyUuidGenerator()
    for row in api.generate(config_dict, registry=registry):
        ...
"""

from __future__ import annotations

from collections.abc import Iterator, Mapping
from random import Random
from typing import Any

from . import _config
from ._config import ConfigError
from ._engine import Engine, TemplateError
from ._logging import configure_stderr, logger
from ._registry import default_registry, registry_with_entry_points
from ._template import UndeclaredVariableError
from .generators import Generator, PairedGenerator

__all__ = [
    "ConfigError",
    "Engine",
    "Generator",
    "PairedGenerator",
    "TemplateError",
    "UndeclaredVariableError",
    "build_registry",
    "configure_stderr",
    "generate",
    "generate_from_file",
    "load_config",
    "logger",
]


def load_config(path: str) -> dict[str, Any]:
    """Read, parse, and validate a JSON config file."""
    return _config.load(path)


def build_registry(include_entry_points: bool = True) -> dict[str, Generator]:
    """Return a fresh registry of generator instances.

    When ``include_entry_points`` is True (default), generators
    advertised by other packages via the ``ton.generators`` entry-point
    group are merged in on top of the built-ins.
    """
    if include_entry_points:
        return registry_with_entry_points()
    return default_registry()


def generate(
    config: Mapping[str, Any],
    *,
    seed: int | None = None,
    registry: Mapping[str, Generator] | None = None,
    milestone_rows: int = 0,
) -> Iterator[str]:
    """Yield generated rows for an in-memory config mapping."""
    rng = Random(seed) if seed is not None else Random()
    return iter(
        Engine(config, registry=registry, rng=rng, milestone_rows=milestone_rows)
    )


def generate_from_file(
    path: str,
    *,
    seed: int | None = None,
    registry: Mapping[str, Generator] | None = None,
    milestone_rows: int = 0,
) -> Iterator[str]:
    """Yield generated rows for a config loaded from ``path``."""
    return generate(
        load_config(path),
        seed=seed,
        registry=registry,
        milestone_rows=milestone_rows,
    )
