"""Helpers for safely sharing TON across worker processes / threads.

Each worker owns its RNG state so scheduling cannot change which worker
receives a particular random draw. CPython's core random draws are thread-safe,
but sharing a seeded RNG does not give deterministic worker streams. This
module provides the two primitives a parallel runner needs:

* :func:`derive_rng` -- deterministic per-worker RNG derived from the
  parent seed plus a worker id (so worker 0 always sees the same
  stream regardless of how many other workers run);
* :func:`fork_engine` -- convenience builder returning a fresh
  :class:`ton.api.Engine` whose RNG is derived for ``worker_id``.

A multi-process generator can stream each worker directly to its own shard::

    from multiprocessing import Pool
    from ton import api, concurrency

    def work(task: tuple[dict, str, int, int]) -> int:
        config, path, worker_id, workers = task
        return concurrency.write_shard(
            config, path, parent_seed=42, worker_id=worker_id, workers=workers
        )

    if __name__ == "__main__":
        config = api.load_config("examples/dna.json")
        workers = 3
        tasks = [
            (config, f"chunk-{worker_id}.txt", worker_id, workers)
            for worker_id in range(workers)
        ]
        with Pool(workers) as p:
            counts = p.map(work, tasks)

The output is *deterministic* for a given (parent_seed, workers,
worker_id) tuple. Merge shard files in worker-id order to reproduce
the partitioned row order.
"""

from __future__ import annotations

import hashlib
import struct
from collections.abc import Mapping
from random import Random
from typing import Any, cast

from ._config import validate_structure
from ._engine import Engine, EngineOptions, TemplateError
from ._logging import LogEvent
from ._logging import logger as _logger
from ._output import open_output_path
from ._proofcheck import ProofFailureSink
from ._registry import default_transforms, make_registry, resolve_reference
from ._specpath import SpecPath, format_spec_path
from ._specsnapshot import snapshot_spec
from ._template import parse
from ._transforms import Transform
from ._validation import Validator
from .generators import Generator
from .generators.base import coerce_int
from .generators.sequence import SequenceGenerator
from .generators.sequence_of import SequenceOfGenerator

_UINT64_MODULUS = 1 << 64


def chunk_rows(total_rows: int, workers: int, worker_id: int) -> int:
    """Return this worker's share without dropping remainder rows."""
    if not isinstance(total_rows, int) or isinstance(total_rows, bool) or total_rows < 0:
        raise ValueError("total_rows must be a non-negative integer")
    _validate_worker_coordinates(workers, worker_id)
    base, remainder = divmod(total_rows, workers)
    return base + (1 if worker_id < remainder else 0)


def _validate_worker_coordinates(workers: int | None, worker_id: int) -> None:
    if not isinstance(worker_id, int) or isinstance(worker_id, bool) or worker_id < 0:
        raise ValueError("worker_id must be a non-negative integer")
    if workers is None:
        return
    if not isinstance(workers, int) or isinstance(workers, bool) or workers < 1:
        raise ValueError("workers must be a positive integer")
    if worker_id >= workers:
        raise ValueError(f"worker_id must be in [0, {workers})")


def derive_seed(parent_seed: int, worker_id: int) -> int:
    """Return the deterministic per-worker seed for ``(parent_seed, worker_id)``.

    Using a hash rather than ``parent_seed + worker_id`` avoids the
    pathological case where adjacent workers see correlated streams
    (e.g. starting from seeds N and N+1 with the same algorithm). The
    derived integer is also recorded in each worker's
    :class:`~ton._proof.ProofFailure` provenance so audit records can be
    traced back to the worker that produced them (CONC-001).
    """
    payload = struct.pack(">QQ", _uint64(parent_seed), _uint64(worker_id))
    digest = hashlib.blake2b(payload, digest_size=8).digest()
    return int(struct.unpack(">Q", digest)[0])


def _uint64(value: int) -> int:
    return value % _UINT64_MODULUS


def derive_rng(parent_seed: int, worker_id: int) -> Random:
    """Return a fresh ``Random`` seeded by :func:`derive_seed`."""
    return Random(derive_seed(parent_seed, worker_id))


def fork_engine(
    config: Mapping[str, Any],
    *,
    parent_seed: int,
    worker_id: int,
    workers: int | None = None,
    rows: int | None = None,
    registry: Mapping[str, Generator] | None = None,
    transforms: Mapping[str, Transform] | None = None,
    validators: Mapping[str, Validator] | None = None,
    proof_mode: str = "off",
    proof_sample_rate: int = 1,
    milestone_rows: int = 0,
    redact_proof_failures: bool = False,
    proof_failure_sink: ProofFailureSink | None = None,
) -> Engine:
    """Build an Engine with a per-worker RNG and an optional row override.

    Mirrors the :meth:`Engine.from_config` surface so forked workers can
    use plugin ``transforms`` and proof-check options the same way the
    parent process does. The worker's derived seed is threaded into the
    engine as ``seed`` so proof/provenance records are attributable to
    the worker (CONC-001).
    """
    if rows is not None and workers is None:
        raise ValueError("workers is required when rows overrides a worker shard")
    _validate_worker_coordinates(workers, worker_id)
    seed = derive_seed(parent_seed, worker_id)
    rng = Random(seed)
    # Validate the caller's config before deriving offsets: coercing first
    # let workers accept values ordinary generation rejects (CONC-004).
    total_rows = validated_total_rows(config)
    worker_rows = total_rows if rows is None else rows
    offset = worker_id * worker_rows
    if workers is not None:
        offset = _chunk_offset(total_rows, workers, worker_id)
    config = _offset_sequences(config, offset, registry, transforms)
    if rows is not None:
        config = {**config, "rows": rows}
    engine = Engine.from_options(
        config,
        EngineOptions(
            registry=registry,
            transforms=transforms,
            validators=validators,
            rng=rng,
            seed=seed,
            proof_mode=proof_mode,
            proof_sample_rate=proof_sample_rate,
            milestone_rows=milestone_rows,
            redact_proof_failures=redact_proof_failures,
            proof_failure_sink=proof_failure_sink,
        ),
    )
    _logger.info(
        "engine_forked worker_id=%d parent_seed=%d rows=%d",
        worker_id,
        parent_seed,
        int(config["rows"]),
        extra={
            "event": LogEvent.ENGINE_FORKED.value,
            "worker_id": worker_id,
            "parent_seed": parent_seed,
            "rows": int(config["rows"]),
        },
    )
    return engine


def write_shard(
    config: Mapping[str, Any],
    path: str,
    *,
    parent_seed: int,
    worker_id: int,
    workers: int,
    encoding: str = "utf-8",
) -> int:
    """Stream one deterministic worker shard to ``path`` in bounded memory."""
    rows = chunk_rows(validated_total_rows(config), workers, worker_id)
    engine = fork_engine(
        config,
        parent_seed=parent_seed,
        worker_id=worker_id,
        workers=workers,
        rows=rows,
    )
    written = 0
    with open_output_path(path, encoding=encoding) as stream:
        for row in engine:
            stream.write(f"{row}\n")
            written += 1
    return written


def validated_total_rows(config: Mapping[str, Any]) -> int:
    """Return ``config['rows']`` after the ordinary structural validation.

    Worker helpers used to call ``int()`` on the raw value, which silently
    accepted ``rows: true`` as one row where direct generation rejects it
    (CONC-004).
    """
    validate_structure(config)
    return cast(int, config["rows"])


def _chunk_offset(total_rows: int, workers: int, worker_id: int) -> int:
    """Return the number of rows assigned to workers before ``worker_id``."""
    chunk_rows(total_rows, workers, worker_id)
    base, remainder = divmod(total_rows, workers)
    return worker_id * base + min(worker_id, remainder)


def _offset_sequences(
    config: Mapping[str, Any],
    offset: int,
    registry: Mapping[str, Generator] | None = None,
    transforms: Mapping[str, Transform] | None = None,
) -> dict[str, Any]:
    copied: dict[str, Any] = snapshot_spec(config)
    generators = registry if registry is not None else make_registry()
    transform_registry = transforms if transforms is not None else default_transforms()
    occurrences: dict[str, int] = {}
    for token in parse(str(copied.get("format", ""))):
        occurrences[token.type_key] = occurrences.get(token.type_key, 0) + 1
    for type_key, count in occurrences.items():
        copied["types"][type_key] = _offset_sequence_spec(
            copied["types"][type_key],
            offset * count,
            generators,
            transform_registry,
            path=f"types.{type_key}",
        )
    return copied


def _offset_sequence_spec(
    value: Any,
    offset: int,
    registry: Mapping[str, Generator],
    transforms: Mapping[str, Transform],
    *,
    path: str,
) -> dict[str, Any]:
    """Visit only declared generator children, preserving opaque plugin metadata (CONC-018)."""
    root = dict(value)
    pending = [(value, root, offset, path, False)]
    active: set[int] = set()
    while pending:
        original, spec, child_offset, child_path, ready = pending.pop()
        if ready:
            active.remove(id(original))
            continue
        if id(original) in active:
            raise TemplateError(f"Cyclic generator specification at {child_path}")
        active.add(id(original))
        pending.append((original, spec, child_offset, child_path, True))
        uses_source, children = _transform_sequence_children(spec, child_offset, transforms)
        reference = spec.get("type")
        generator = resolve_reference(registry, reference) if isinstance(reference, str) else None
        if generator is not None and uses_source:
            children.extend(_offset_source_spec(spec, child_offset, generator))
        owned: set[SpecPath] = set()
        for location, child, amount in children:
            child_copy = dict(child)
            _replace_owned_child(spec, location, child_copy, owned)
            pending.append(
                (child, child_copy, amount, f"{child_path}.{format_spec_path(location)}", False)
            )
    return root


def _replace_owned_child(
    spec: dict[str, Any], location: SpecPath, child: dict[str, Any], owned: set[SpecPath]
) -> None:
    """Copy each owned container occurrence once, retaining opaque metadata aliases."""
    target: Any = spec
    for index, key in enumerate(location[:-1]):
        prefix = location[: index + 1]
        if prefix not in owned:
            target[key] = target[key].copy()
            owned.add(prefix)
        target = target[key]
    target[location[-1]] = child


def _offset_source_spec(
    value: Any, offset: int, generator: Generator
) -> list[tuple[SpecPath, Any, int]]:
    """Apply built-in sequence semantics to the effective generator implementation."""
    if isinstance(generator, SequenceGenerator):
        start = coerce_int(value, "start", type_name="sequence", default=0)
        step = coerce_int(value, "step", type_name="sequence", default=1)
        value["start"] = start + offset * step
    if isinstance(generator, SequenceOfGenerator):
        offset *= coerce_int(value, "count", type_name="sequence_of", default=0)
    return [(location, child, offset) for location, child in generator.nested_specs(value)]


def _transform_sequence_children(
    value: Mapping[str, Any], offset: int, registry: Mapping[str, Transform]
) -> tuple[bool, list[tuple[SpecPath, Any, int]]]:
    uses_source = True
    children: list[tuple[SpecPath, Any, int]] = []
    specs = value.get("transforms", [])
    if not isinstance(specs, list):
        return uses_source, children
    for index, spec in enumerate(specs):
        if not isinstance(spec, Mapping) or not isinstance(spec.get("type"), str):
            continue
        transform = resolve_reference(registry, spec["type"])
        if transform is not None:
            if index == 0:
                uses_source = transform.requires_source
            children.extend(
                (("transforms", index, *location), child, offset)
                for location, child in transform.nested_specs(spec)
            )
    return uses_source, children
