# Parallel generation

[Documentation](README.md) · [Project overview](../README.md)

Commands and relative config paths assume the repository root.

## Write and merge shards

```python
import shutil
from multiprocessing import get_context
from pathlib import Path
from tempfile import TemporaryDirectory

from ton import api

def write_worker(task):
    config, path, parent_seed, worker_id, workers, encoding = task
    return api.write_shard(
        config,
        path,
        parent_seed=parent_seed,
        worker_id=worker_id,
        workers=workers,
        encoding=encoding,
    )

if __name__ == "__main__":
    config = api.load_config("huge.json")
    workers = 3
    encoding = api.output_encoding(config)
    with TemporaryDirectory(prefix="ton-shards-") as directory:
        shards = [Path(directory) / f"part-{worker_id}.txt" for worker_id in range(workers)]
        tasks = [
            (config, str(path), 1, worker_id, workers, encoding)
            for worker_id, path in enumerate(shards)
        ]
        with get_context("spawn").Pool(workers) as pool:
            counts = pool.map(write_worker, tasks)

        with api.open_output_path("combined.txt", encoding=encoding) as output:
            for path in shards:
                with path.open("r", encoding=encoding, newline="") as shard:
                    shutil.copyfileobj(shard, output)

        assert sum(counts) == config["rows"]
```

Each shard receives an exact, non-overlapping row count and a deterministic
worker RNG. Workers write atomically to separate files, so no worker accumulates
its output in memory. The parent merges shards in worker-id order to preserve
partition order. `TemporaryDirectory` removes completed shards and any
worker-temporary files after success or failure; the final merged file is also
published atomically.

## Stream from one worker

Parallel runs use the public `ton.concurrency` helpers re-exported by `ton.api`.
`write_shard` is the bounded-memory process-pool primitive used in the complete
merge/cleanup recipe in this guide. It honors the config's output encoding (UTF-8 when
absent); an explicit `encoding=` overrides that setting. Callers with their own
streaming sink can instead
construct one worker engine directly:

```python
from ton import api, concurrency

config = api.load_config("examples/dna.json")
workers = 3
worker_id = 0
eng = concurrency.fork_engine(
    config,
    parent_seed=42,
    worker_id=worker_id,
    workers=workers,
    rows=concurrency.chunk_rows(config["rows"], workers, worker_id),
    options=api.EngineOptions(proof_mode="all"),
)
for row in eng:
    ...
```

Each worker derives its RNG from `BLAKE2b(parent_seed, worker_id)` so adjacent workers do not see correlated streams. An `engine_forked` log event is emitted with `worker_id` / `parent_seed` so multi-process runs stay distinguishable in the structured log stream.

## Worker options

Both `fork_engine` and `write_shard` accept `options=api.EngineOptions(...)` for
registries, transforms, validators, proof checking, audit sinks, and milestones.
The worker seed and RNG are derived from `parent_seed` and `worker_id`, overriding
those two option fields; the other options are preserved. Options passed through
a spawned process pool, including plugin instances and sinks, must be pickleable.

See [partition capabilities](extensions.md#worker-partitioning) when writing
stateful or composite plugins that need disjoint worker ranges.
