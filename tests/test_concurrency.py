"""Tests for the parallel-worker helpers."""

from __future__ import annotations

import multiprocessing
from random import Random

import pytest

from ton._engine import Engine
from ton.concurrency import chunk_rows, derive_rng, derive_seed, fork_engine


def _render_engine(engine: Engine) -> list[str]:
    return list(engine)


def test_chunk_rows_distributes_remainder_without_dropping_rows() -> None:
    chunks = [chunk_rows(10, 4, worker_id) for worker_id in range(4)]

    assert chunks == [3, 3, 2, 2]
    assert sum(chunks) == 10


@pytest.mark.parametrize("workers, worker_id", [(0, 0), (2, -1), (2, 2)])
def test_chunk_rows_rejects_invalid_worker_coordinates(workers: int, worker_id: int) -> None:
    with pytest.raises(ValueError):
        chunk_rows(10, workers, worker_id)


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
