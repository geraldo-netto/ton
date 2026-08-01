"""Public, library-facing facade for TON.

This is the *only* module external callers should import from.
:mod:`ton._engine`, :mod:`ton._template`, :mod:`ton._registry`, and
:mod:`ton._config` are private (single leading underscore, per PEP 8)
and may change between releases without notice (TODO ARCH-004).

The supported surface, re-exported here, is:

* :func:`load_config` -- read and validate a JSON config file
* :func:`generate` / :func:`generate_from_file` -- iterators of rows
* :func:`build_extension_catalog` -- the canonical plugin-loading API:
  namespaced data types, transforms, and validators (TODO PLUG-004)
* :func:`build_registry` -- *deprecated* generator-only registry; kept
  as a thin compatibility shim over the catalog
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

    # Opt into third-party entry points when you trust the installed packages:
    catalog = api.build_extension_catalog(include_entry_points=True)
    for row in api.generate(config_dict, registry=catalog.generators(),
                            transforms=catalog.transforms(),
                            validators=catalog.validators()):
        ...
"""

from __future__ import annotations

import warnings
from collections.abc import Iterable, Iterator, Mapping
from typing import Any

from . import _config
from ._config import ConfigError
from ._config import output_encoding as _output_encoding
from ._engine import (
    Engine,
    EngineOptions,
    GeneratorExecutionError,
    PipelineStageError,
    ProofError,
    ProofEvaluationError,
    TemplateError,
    TransformExecutionError,
    ValidatorExecutionError,
)
from ._logging import LogEvent, configure_stderr, logger
from ._output import (
    OutputEncodingError,
    OutputPublishedError,
    PartialOutputCommitError,
    StagedOutput,
    cleanup_staged_outputs,
    inspect_staged_outputs,
    open_output_path,
)
from ._proof import ProofFailure, ProvenanceRecord
from ._proofcheck import ProofFailureSink
from ._registry import (
    EntryPointSelector,
    ExtensionCatalog,
    RegistryError,
    catalog_with_entry_points,
    default_registry,
    normalize_reference,
    registry_with_entry_points,
)
from ._registry import (
    build_extension_catalog as _build_extension_catalog,
)
from ._template import UndeclaredVariableError
from ._transforms import Transform
from ._validation import ValidationError, Validator
from .concurrency import chunk_rows, derive_rng, derive_seed, fork_engine, write_shard
from .generators import Generator, PairedGenerator

__all__ = [
    "ConfigError",
    "Engine",
    "EngineOptions",
    "EntryPointSelector",
    "Generator",
    "GeneratorExecutionError",
    "LogEvent",
    "OutputEncodingError",
    "OutputPublishedError",
    "PairedGenerator",
    "PartialOutputCommitError",
    "StagedOutput",
    "PipelineStageError",
    "ProofError",
    "ProofEvaluationError",
    "ProofFailure",
    "ProofFailureSink",
    "ProvenanceRecord",
    "RegistryError",
    "TemplateError",
    "Transform",
    "TransformExecutionError",
    "UndeclaredVariableError",
    "ValidationError",
    "Validator",
    "ValidatorExecutionError",
    "ExtensionCatalog",
    "build_extension_catalog",
    "build_registry",
    "cleanup_staged_outputs",
    "configure_stderr",
    "chunk_rows",
    "derive_rng",
    "derive_seed",
    "fork_engine",
    "write_shard",
    "generate",
    "generate_from_file",
    "load_config",
    "inspect_staged_outputs",
    "logger",
    "normalize_reference",
    "open_output_path",
    "output_encoding",
    "validate_config",
]


def load_config(path: str) -> dict[str, Any]:
    """Read, parse, and validate a JSON config file."""
    return _config.load(path)


def output_encoding(config: Mapping[str, Any]) -> str:
    """Return the config's output encoding, defaulting to UTF-8 (CFG-001)."""
    return _output_encoding(config)


def validate_config(
    config: dict[str, Any],
    *,
    catalog: ExtensionCatalog | None = None,
) -> None:
    """Validate config references against an extension catalog.

    This is the canonical catalog-aware validation path (TODO CFG-003):
    it reports unknown type/transform references with the available-name
    lists and plugin-namespace diagnostics. :func:`load_config` performs
    structural-only validation, and constructing an :class:`Engine`
    validates lazily at build time with a terser message; callers that
    want full diagnostics (including the CLI ``--validate`` flag) should
    route through here.
    """
    _config.validate_with_catalog(config, catalog or build_extension_catalog())


def build_registry(
    include_entry_points: bool = False,
    *,
    allowed_entry_points: Iterable[str | EntryPointSelector] | None = None,
) -> dict[str, Generator]:
    """Return a fresh generator-only registry of generator instances.

    .. deprecated::
        :func:`build_extension_catalog` is the canonical plugin-loading
        API (TODO PLUG-004). It loads generators, transforms, and
        validators under one namespaced surface, whereas this helper only
        loads generators and promotes plugin names to bare keys with
        different shadowing rules. Prefer
        ``build_extension_catalog(...).generators()``.

    When ``include_entry_points`` is True, generators advertised by
    other packages via the ``ton.generators`` entry-point group are
    merged in on top of the built-ins. Entry points execute package
    code while loading, so this path is opt-in.
    """
    warnings.warn(
        "api.build_registry is deprecated; use api.build_extension_catalog(...) "
        "which loads generators, transforms, and validators as the canonical "
        "plugin API.",
        DeprecationWarning,
        stacklevel=2,
    )
    if include_entry_points:
        return registry_with_entry_points(
            allowed_selectors=_normalize_entry_point_selectors(allowed_entry_points)
        )
    return default_registry()


def build_extension_catalog(
    include_entry_points: bool = False,
    *,
    allowed_entry_points: Iterable[str | EntryPointSelector] | None = None,
) -> ExtensionCatalog:
    """Return a catalog for data types, transforms, and validators.

    Allowed entry points use exact ``GROUP:DISTRIBUTION:NAME`` selectors;
    name-only allowlists are intentionally rejected.
    """
    if include_entry_points:
        return catalog_with_entry_points(
            allowed_selectors=_normalize_entry_point_selectors(allowed_entry_points)
        )
    return _build_extension_catalog()


def _normalize_entry_point_selectors(
    values: Iterable[str | EntryPointSelector] | None,
) -> frozenset[EntryPointSelector] | None:
    if values is None:
        return None
    return frozenset(
        value if isinstance(value, EntryPointSelector) else EntryPointSelector.parse(value)
        for value in values
    )


def generate(
    config: Mapping[str, Any],
    *,
    seed: int | None = None,
    registry: Mapping[str, Generator] | None = None,
    transforms: Mapping[str, Transform] | None = None,
    validators: Mapping[str, Validator] | None = None,
    proof_mode: str = "off",
    proof_sample_rate: int = 1,
    milestone_rows: int = 0,
    redact_proof_failures: bool = False,
    proof_failure_sink: ProofFailureSink | None = None,
) -> Iterator[str]:
    """Yield generated rows for an in-memory config mapping.

    The returned iterator is single-shot. Call :func:`generate` again to
    obtain a fresh Engine and repeat a seeded generation pass.
    """
    return iter(
        Engine.from_options(
            config,
            EngineOptions(
                registry=registry,
                transforms=transforms,
                validators=validators,
                proof_mode=proof_mode,
                proof_sample_rate=proof_sample_rate,
                seed=seed,
                milestone_rows=milestone_rows,
                redact_proof_failures=redact_proof_failures,
                proof_failure_sink=proof_failure_sink,
            ),
        )
    )


def generate_from_file(
    path: str,
    *,
    seed: int | None = None,
    registry: Mapping[str, Generator] | None = None,
    transforms: Mapping[str, Transform] | None = None,
    validators: Mapping[str, Validator] | None = None,
    proof_mode: str = "off",
    proof_sample_rate: int = 1,
    milestone_rows: int = 0,
    redact_proof_failures: bool = False,
    proof_failure_sink: ProofFailureSink | None = None,
) -> Iterator[str]:
    """Yield generated rows for a config loaded from ``path``."""
    return generate(
        load_config(path),
        seed=seed,
        registry=registry,
        transforms=transforms,
        validators=validators,
        proof_mode=proof_mode,
        proof_sample_rate=proof_sample_rate,
        milestone_rows=milestone_rows,
        redact_proof_failures=redact_proof_failures,
        proof_failure_sink=proof_failure_sink,
    )
