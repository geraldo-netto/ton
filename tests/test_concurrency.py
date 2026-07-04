"""Tests for the parallel-worker helpers."""

from __future__ import annotations

from random import Random

from ton.concurrency import derive_rng, derive_seed, fork_engine


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
    engine = fork_engine(config, parent_seed=1, worker_id=0, rows=7)
    assert len(list(engine)) == 7


def test_fork_engine_reproducible_per_worker() -> None:
    config = {
        "rows": 5,
        "format": "$n$",
        "types": {"n": {"type": "integer", "minValue": 0, "maxValue": 9999, "padWithZero": False}},
    }
    first = list(fork_engine(config, parent_seed=99, worker_id=2))
    second = list(fork_engine(config, parent_seed=99, worker_id=2))
    assert first == second


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
