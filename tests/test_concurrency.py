"""Tests for the parallel-worker helpers."""

from __future__ import annotations

import multiprocessing
import pickle
from multiprocessing import get_context
from pathlib import Path
from random import Random

import pytest

from ton import concurrency
from ton._config import ConfigError
from ton._engine import Engine
from ton.concurrency import chunk_rows, derive_rng, derive_seed, fork_engine, write_shard
from ton.generators import _regex_parse as rx


def _render_engine(engine: Engine) -> list[str]:
    return list(engine)


def _write_worker_shard(args: tuple[dict, str, int, int]) -> int:
    config, path, worker_id, workers = args
    return write_shard(config, path, parent_seed=7, worker_id=worker_id, workers=workers)


def test_parallel_worker_contract_streams_shards() -> None:
    documentation = concurrency.__doc__ or ""

    assert "return list(eng)" not in documentation
    assert "concurrency.write_shard(" in documentation


def test_chunk_rows_distributes_remainder_without_dropping_rows() -> None:
    chunks = [chunk_rows(10, 4, worker_id) for worker_id in range(4)]

    assert chunks == [3, 3, 2, 2]
    assert sum(chunks) == 10


@pytest.mark.parametrize("workers, worker_id", [(0, 0), (2, -1), (2, 2)])
def test_chunk_rows_rejects_invalid_worker_coordinates(workers: int, worker_id: int) -> None:
    with pytest.raises(ValueError):
        chunk_rows(10, workers, worker_id)


@pytest.mark.parametrize("total_rows", [-1, True])
def test_chunk_rows_rejects_invalid_total_rows(total_rows: int) -> None:
    with pytest.raises(ValueError, match="non-negative integer"):
        chunk_rows(total_rows, 1, 0)


def test_derive_rng_is_deterministic_for_same_inputs() -> None:
    a = derive_rng(parent_seed=42, worker_id=3)
    b = derive_rng(parent_seed=42, worker_id=3)
    assert [a.random() for _ in range(5)] == [b.random() for _ in range(5)]


def test_derive_rng_differs_across_workers() -> None:
    workers = [derive_rng(parent_seed=42, worker_id=w) for w in range(4)]
    streams = [tuple(rng.random() for _ in range(5)) for rng in workers]
    # All four worker streams must be distinct (collision risk negligible).
    assert len(set(streams)) == 4


def test_fork_engine_overrides_row_count() -> None:
    config = {
        "rows": 100,
        "format": "$n$",
        "types": {"n": {"type": "integer", "minValue": 1, "maxValue": 9, "padWithZero": False}},
    }
    engine = fork_engine(config, parent_seed=1, worker_id=0, workers=15, rows=7)
    assert len(list(engine)) == 7


def test_fork_engine_requires_worker_count_for_row_override() -> None:
    config = {"rows": 10, "fields": {"id": {"type": "sequence"}}}

    with pytest.raises(ValueError, match="workers is required"):
        fork_engine(config, parent_seed=1, worker_id=0, rows=7)


def test_fork_engine_reproducible_per_worker() -> None:
    config = {
        "rows": 5,
        "format": "$n$",
        "types": {"n": {"type": "integer", "minValue": 0, "maxValue": 9999, "padWithZero": False}},
    }
    first = list(fork_engine(config, parent_seed=99, worker_id=2))
    second = list(fork_engine(config, parent_seed=99, worker_id=2))
    assert first == second


def test_fork_engine_offsets_sequence_ranges_without_mutating_config() -> None:
    config = {
        "rows": 6,
        "format": "$id$",
        "types": {"id": {"type": "sequence", "start": 10}},
    }

    first = list(fork_engine(config, parent_seed=1, worker_id=0, workers=2, rows=3))
    second = list(fork_engine(config, parent_seed=1, worker_id=1, workers=2, rows=3))

    assert first == ["10", "11", "12"]
    assert second == ["13", "14", "15"]
    assert config["types"]["id"]["start"] == 10


def test_fork_engine_offsets_uneven_sequence_shards() -> None:
    config = {
        "rows": 10,
        "format": "$id$",
        "types": {"id": {"type": "sequence", "start": 0}},
    }

    chunks = [
        list(
            fork_engine(
                config,
                parent_seed=1,
                worker_id=worker_id,
                workers=3,
                rows=chunk_rows(10, 3, worker_id),
            )
        )
        for worker_id in range(3)
    ]

    assert chunks == [["0", "1", "2", "3"], ["4", "5", "6"], ["7", "8", "9"]]


@pytest.mark.parametrize("reference", ["sequence", "core.sequence"])
def test_fork_engine_offsets_default_start_with_exact_step(reference: str) -> None:
    config = {
        "rows": 6,
        "format": "$id$",
        "types": {"id": {"type": reference, "step": 2}},
    }

    first = list(fork_engine(config, parent_seed=1, worker_id=0, workers=2, rows=3))
    second = list(fork_engine(config, parent_seed=1, worker_id=1, workers=2, rows=3))

    assert first == ["0", "2", "4"]
    assert second == ["6", "8", "10"]


def test_fork_engine_offsets_repeated_sequence_draws_per_row() -> None:
    config = {
        "rows": 6,
        "format": "$id$,$id$",
        "types": {"id": {"type": "sequence"}},
    }

    first = list(fork_engine(config, parent_seed=1, worker_id=0, workers=2, rows=3))
    second = list(fork_engine(config, parent_seed=1, worker_id=1, workers=2, rows=3))

    assert first == ["0,1", "2,3", "4,5"]
    assert second == ["6,7", "8,9", "10,11"]


def test_fork_engine_offsets_nested_sequence_multiplicity() -> None:
    config = {
        "rows": 6,
        "format": "$ids$",
        "types": {
            "ids": {
                "type": "sequence_of",
                "count": 2,
                "separator": ",",
                "spec": {"type": "sequence"},
            }
        },
    }

    first = list(fork_engine(config, parent_seed=1, worker_id=0, workers=2, rows=3))
    second = list(fork_engine(config, parent_seed=1, worker_id=1, workers=2, rows=3))

    assert first == ["0,1", "2,3", "4,5"]
    assert second == ["6,7", "8,9", "10,11"]


def test_derive_seed_matches_derive_rng() -> None:
    seed = derive_seed(parent_seed=7, worker_id=1)
    assert derive_rng(parent_seed=7, worker_id=1).random() == Random(seed).random()


def test_derive_seed_accepts_large_python_ints() -> None:
    large_seed = 2**100 + 123
    assert derive_seed(parent_seed=large_seed, worker_id=1) == derive_seed(
        parent_seed=large_seed % (1 << 64),
        worker_id=1,
    )


def test_fork_engine_threads_worker_seed_and_proof_options() -> None:
    config = {
        "rows": 1,
        "format": "$n$",
        "types": {"n": {"type": "integer", "minValue": 0, "maxValue": 9, "padWithZero": False}},
    }
    engine = fork_engine(
        config,
        parent_seed=5,
        worker_id=1,
        proof_mode="audit",
        proof_sample_rate=3,
    )
    assert engine._seed == derive_seed(parent_seed=5, worker_id=1)
    assert engine._proof.mode == "audit"
    assert engine._proof.sample_rate == 3


def test_fork_engine_threads_validators_and_redaction() -> None:
    class AcceptAll:
        type_name = "accept_all"

        def validate(self, value: str) -> bool:
            return True

    config = {
        "rows": 1,
        "format": "$n$",
        "types": {
            "n": {
                "type": "integer",
                "minValue": 0,
                "maxValue": 9,
                "validators": ["accept_all"],
            }
        },
    }

    engine = fork_engine(
        config,
        parent_seed=5,
        worker_id=1,
        validators={"accept_all": AcceptAll()},
        proof_mode="audit",
        redact_proof_failures=True,
    )

    assert list(engine) != []
    assert engine._proof.redact is True


def test_fork_engine_threads_public_proof_failure_sink() -> None:
    failures = []
    config = {
        "rows": 0,
        "format": "$value$",
        "types": {"value": {"type": "string", "values": ["valid"]}},
    }

    engine = fork_engine(
        config,
        parent_seed=5,
        worker_id=0,
        proof_mode="audit",
        proof_failure_sink=failures.append,
    )

    assert engine._proof.failure_sink == failures.append


@pytest.mark.parametrize(
    "start_method",
    [
        method
        for method in ("spawn", "forkserver")
        if method in multiprocessing.get_all_start_methods()
    ],
)
def test_prepared_bytes_engine_crosses_process_boundary(start_method: str) -> None:
    config = {
        "rows": 2,
        "format": "$token$",
        "types": {"token": {"type": "bytes", "length": 4, "encoding": "base64"}},
    }
    engine = Engine.from_config(config, seed=17)
    expected = list(Engine.from_config(config, seed=17))
    context = multiprocessing.get_context(start_method)

    with context.Pool(1) as pool:
        actual = pool.apply(_render_engine, (engine,))

    assert actual == expected


def test_multiprocess_shards_stream_exact_order_and_counts(tmp_path) -> None:
    workers = 3
    config = {
        "rows": 10,
        "format": "$id$",
        "types": {"id": {"type": "sequence", "start": 0}},
    }
    paths = [str(tmp_path / f"part-{worker}.txt") for worker in range(workers)]
    context = multiprocessing.get_context("spawn")
    with context.Pool(workers) as pool:
        counts = pool.map(
            _write_worker_shard,
            [(config, paths[worker], worker, workers) for worker in range(workers)],
        )

    assert counts == [4, 3, 3]
    rows = [line for path in paths for line in Path(path).read_text().splitlines()]
    assert rows == [str(value) for value in range(10)]


def test_write_shard_streams_without_returning_rows(tmp_path) -> None:
    config = {
        "rows": 2,
        "format": "$id$",
        "types": {"id": {"type": "sequence", "start": 5}},
    }
    path = tmp_path / "part.txt"
    assert write_shard(config, str(path), parent_seed=1, worker_id=0, workers=1) == 2
    assert path.read_text().splitlines() == ["5", "6"]


def _drain(engine: Engine) -> list[str]:
    return list(engine)


def test_prepared_regex_engine_survives_a_spawn_round_trip() -> None:
    """Unbounded repeats must keep their sentinel identity across processes (CONC-007)."""
    config = {
        "rows": 3,
        "format": "$x$",
        "types": {"x": {"type": "regex", "pattern": "a+"}},
    }
    engine = Engine.from_config(config, seed=1)
    expected = list(Engine.from_config(config, seed=1))

    with get_context("spawn").Pool(1) as pool:
        assert pool.apply(_drain, (engine,)) == expected


def test_repeat_sentinel_identity_survives_pickling() -> None:
    """Enum members pickle by name, so ``is`` comparisons stay valid (CONC-007)."""
    assert pickle.loads(pickle.dumps(rx.MAXREPEAT)) is rx.MAXREPEAT


def test_fork_engine_rejects_a_fractional_sequence_start() -> None:
    """Workers must apply the generator's numeric rules, not int() (CONC-004)."""
    config = {"rows": 2, "format": "$x$", "types": {"x": {"type": "sequence", "start": 1.5}}}

    with pytest.raises(ValueError, match="sequence 'start' must be an integer"):
        fork_engine(config, parent_seed=1, worker_id=0, workers=2)


@pytest.mark.parametrize("helper", ["fork_engine", "write_shard"])
def test_worker_helpers_reject_a_boolean_row_count(tmp_path: Path, helper: str) -> None:
    """rows: true was silently coerced to one row (CONC-004)."""
    config = {"rows": True, "format": "$x$", "types": {"x": {"type": "string", "values": ["a"]}}}

    with pytest.raises(ConfigError, match="non-negative integer"):
        if helper == "fork_engine":
            fork_engine(config, parent_seed=1, worker_id=0, workers=1)
        else:
            write_shard(config, str(tmp_path / "shard.txt"), parent_seed=1, worker_id=0, workers=1)


@pytest.mark.parametrize(
    ("label", "field"),
    [
        ("plain", {"type": "sequence", "start": 0}),
        (
            "transform_owned",
            {
                "type": "sequence",
                "start": 0,
                "transforms": [
                    {
                        "type": "distribution",
                        "choices": [
                            {"weight": 100, "spec": {"type": "sequence", "start": 0}},
                            {"weight": 0, "spec": {"type": "string", "values": ["z"]}},
                        ],
                    }
                ],
            },
        ),
        (
            "nested",
            {
                "type": "sequence_of",
                "count": 2,
                "separator": "-",
                "spec": {"type": "sequence", "start": 0},
            },
        ),
    ],
)
def test_partitioned_workers_emit_disjoint_sequences(label: str, field: dict) -> None:
    """A sequence in a replacing transform must be offset too (CONC-005)."""
    workers = 3
    config = {"rows": 12, "format": "$x$", "types": {"x": field}}

    shards = [
        list(
            fork_engine(
                config,
                parent_seed=1,
                worker_id=worker_id,
                workers=workers,
                rows=chunk_rows(config["rows"], workers, worker_id),
            )
        )
        for worker_id in range(workers)
    ]

    emitted = [value for shard in shards for value in shard]
    assert len(emitted) == config["rows"]
    assert len(set(emitted)) == len(emitted)
