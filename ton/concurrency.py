"""Helpers for safely sharing TON across worker processes / threads.

`random.Random` is not thread-safe and a single seeded RNG cannot be
reused across workers without losing reproducibility. This module
provides the two primitives a parallel runner needs:

* :func:`derive_rng` -- deterministic per-worker RNG derived from the
  parent seed plus a worker id (so worker 0 always sees the same
  stream regardless of how many other workers run);
* :func:`fork_engine` -- convenience builder returning a fresh
  :class:`ton.engine.Engine` whose RNG is derived for ``worker_id``.

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
from copy import deepcopy
from random import Random
from typing import Any

from ._engine import Engine, EngineOptions
from ._logging import LogEvent
from ._logging import logger as _logger
from ._output import open_output_path
from ._registry import runtime_type_name
from ._template import parse
from ._transforms import Transform
from ._validation import Validator
from .generators import Generator

_UINT64_MODULUS = 1 << 64


def chunk_rows(total_rows: int, workers: int, worker_id: int) -> int:
    """Return this worker's share without dropping remainder rows."""
    if not isinstance(total_rows, int) or isinstance(total_rows, bool) or total_rows < 0:
        raise ValueError("total_rows must be a non-negative integer")
    if workers < 1:
        raise ValueError("workers must be >= 1")
    if not 0 <= worker_id < workers:
        raise ValueError(f"worker_id must be in [0, {workers})")
    base, remainder = divmod(total_rows, workers)
    return base + (1 if worker_id < remainder else 0)


def derive_seed(parent_seed: int, worker_id: int) -> int:
    """Return the deterministic per-worker seed for ``(parent_seed, worker_id)``.

    Using a hash rather than ``parent_seed + worker_id`` avoids the
    pathological case where adjacent workers see correlated streams
    (e.g. starting from seeds N and N+1 with the same algorithm). The
    derived integer is also recorded in each worker's
    :class:`~ton._proof.ProofFailure` provenance so audit records can be
    traced back to the worker that produced them (TODO CONC-001).
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
) -> Engine:
    """Build an Engine with a per-worker RNG and an optional row override.

    Mirrors the :meth:`Engine.from_config` surface so forked workers can
    use plugin ``transforms`` and proof-check options the same way the
    parent process does. The worker's derived seed is threaded into the
    engine as ``seed`` so proof/provenance records are attributable to
    the worker (TODO CONC-001).
    """
    seed = derive_seed(parent_seed, worker_id)
    rng = Random(seed)
    total_rows = int(config["rows"])
    worker_rows = int(total_rows if rows is None else rows)
    if rows is not None and workers is None:
        raise ValueError("workers is required when rows overrides a worker shard")
    offset = worker_id * worker_rows
    if workers is not None:
        offset = _chunk_offset(total_rows, workers, worker_id)
    config = _offset_sequences(config, offset)
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
    rows = chunk_rows(int(config["rows"]), workers, worker_id)
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


def _chunk_offset(total_rows: int, workers: int, worker_id: int) -> int:
    """Return the number of rows assigned to workers before ``worker_id``."""
    chunk_rows(total_rows, workers, worker_id)
    base, remainder = divmod(total_rows, workers)
    return worker_id * base + min(worker_id, remainder)


def _offset_sequences(config: Mapping[str, Any], offset: int) -> dict[str, Any]:
    copied = deepcopy(dict(config))
    occurrences: dict[str, int] = {}
    for token in parse(str(copied.get("format", ""))):
        occurrences[token.type_key] = occurrences.get(token.type_key, 0) + 1
    for type_key, spec in copied.get("types", {}).items():
        _offset_sequence_spec(spec, offset * occurrences.get(type_key, 0))
    return copied


def _offset_sequence_spec(value: Any, offset: int) -> None:
    if isinstance(value, dict):
        type_name = runtime_type_name(value.get("type"))
        if type_name == "sequence":
            start = int(value.get("start", 0))
            step = int(value.get("step", 1))
            value["start"] = start + offset * step
            return
        if type_name == "sequence_of":
            count = int(value.get("count", 0))
            _offset_sequence_spec(value.get("spec"), offset * count)
            return
        for nested in value.values():
            _offset_sequence_spec(nested, offset)
    elif isinstance(value, list):
        for nested in value:
            _offset_sequence_spec(nested, offset)
