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
worker_id) tuple, which is the property TODO CONC-001 asked for.
"""

from __future__ import annotations

import hashlib
import struct
from collections.abc import Mapping
from random import Random
from typing import Any

from ._engine import Engine


def derive_rng(parent_seed: int, worker_id: int) -> Random:
    """Return a fresh ``Random`` whose seed is a stable hash of
    ``(parent_seed, worker_id)``.

    Using a hash rather than ``parent_seed + worker_id`` avoids the
    pathological case where adjacent workers see correlated streams
    (e.g. starting from seeds N and N+1 with the same algorithm).
    """
    payload = struct.pack(">qq", parent_seed, worker_id)
    digest = hashlib.blake2b(payload, digest_size=8).digest()
    seed = struct.unpack(">Q", digest)[0]
    return Random(seed)


def fork_engine(
    config: Mapping[str, Any],
    *,
    parent_seed: int,
    worker_id: int,
    rows: int | None = None,
    registry: Mapping[str, Any] | None = None,
    milestone_rows: int = 0,
) -> Engine:
    """Build an Engine with a per-worker RNG and an optional row override."""
    rng = derive_rng(parent_seed, worker_id)
    if rows is not None:
        config = {**config, "rows": rows}
    return Engine(config, registry=registry, rng=rng, milestone_rows=milestone_rows)
