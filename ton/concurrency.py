"""Helpers for safely sharing TON across worker processes / threads.

`random.Random` is not thread-safe and a single seeded RNG cannot be
reused across workers without losing reproducibility. This module
provides the two primitives a parallel runner needs:

* :func:`derive_rng` -- deterministic per-worker RNG derived from the
  parent seed plus a worker id (so worker 0 always sees the same
  stream regardless of how many other workers run);
* :func:`fork_engine` -- convenience builder returning a fresh
  :class:`ton.engine.Engine` whose RNG is derived for ``worker_id``.

A multi-process generator can then do::

    from multiprocessing import Pool
    from ton import api, concurrency

    config = api.load_config("examples/dna.json")
    rows_per_worker = config["rows"] // workers

    def work(worker_id: int) -> list[str]:
        eng = concurrency.fork_engine(config, parent_seed=42,
                                      worker_id=worker_id,
                                      rows=rows_per_worker)
        return list(eng)

    with Pool(workers) as p:
        for chunk in p.imap(work, range(workers)):
            for row in chunk:
                print(row)

The output is *deterministic* for a given (parent_seed, workers,
worker_id) tuple.
"""

from __future__ import annotations

import hashlib
import struct
from collections.abc import Mapping
from random import Random
from typing import Any

from ._engine import Engine, EngineOptions
from ._logging import LogEvent
from ._logging import logger as _logger
from ._transforms import Transform
from .generators import Generator

_UINT64_MODULUS = 1 << 64


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
    rows: int | None = None,
    registry: Mapping[str, Generator] | None = None,
    transforms: Mapping[str, Transform] | None = None,
    proof_mode: str = "off",
    proof_sample_rate: int = 1,
    milestone_rows: int = 0,
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
    if rows is not None:
        config = {**config, "rows": rows}
    engine = Engine.from_options(
        config,
        EngineOptions(
            registry=registry,
            transforms=transforms,
            rng=rng,
            seed=seed,
            proof_mode=proof_mode,
            proof_sample_rate=proof_sample_rate,
            milestone_rows=milestone_rows,
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
