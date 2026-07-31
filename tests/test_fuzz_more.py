"""Additional fuzz / property tests covering invariants the original
``test_fuzz.py`` does not assert.

Each test drives a seeded RNG and checks a structural property of the
engine rather than a single example. Iteration counts stay small so the
suite runs in well under a second.
"""

from __future__ import annotations

import json
import re
from collections.abc import Callable
from pathlib import Path
from random import Random
from typing import Any

import pytest

from ton import api
from ton._engine import Engine
from ton._registry import make_registry
from ton.concurrency import derive_rng, fork_engine

pytestmark = pytest.mark.fuzz

# ---------------------------------------------------------------------------
# Determinism: same seed -> identical full-row sequence, every type
# ---------------------------------------------------------------------------


def _basic_int_config(rows: int) -> dict[str, Any]:
    return {
        "rows": rows,
        "format": "$n$",
        "types": {
            "n": {"type": "integer", "minValue": 0, "maxValue": 1_000_000, "padWithZero": False}
        },
    }


@pytest.mark.parametrize("seed", list(range(20)))
def test_engine_seed_determinism(seed: int) -> None:
    config = _basic_int_config(40)
    first = list(api.generate(config, seed=seed))
    second = list(api.generate(config, seed=seed))
    assert first == second


@pytest.mark.parametrize("seed", list(range(10)))
def test_engine_from_config_matches_constructor(seed: int) -> None:
    config = _basic_int_config(15)
    via_helper = list(Engine.from_config(config, seed=seed))
    via_ctor = list(Engine(config, rng=Random(seed)))
    assert via_helper == via_ctor


@pytest.mark.parametrize("seed", list(range(20)))
def test_core_namespaced_type_matches_legacy_type(seed: int) -> None:
    legacy = _basic_int_config(20)
    namespaced = {
        **legacy,
        "types": {
            "n": {
                **legacy["types"]["n"],
                "type": "core.integer",
            }
        },
    }

    assert list(api.generate(namespaced, seed=seed)) == list(api.generate(legacy, seed=seed))


# ---------------------------------------------------------------------------
# rows_emitted always equals the iteration count
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("rows", [0, 1, 7, 32, 100])
def test_rows_emitted_tracks_iteration_count(rows: int) -> None:
    engine = Engine.from_config(_basic_int_config(rows), seed=0)
    consumed = list(engine)
    assert len(consumed) == rows
    assert engine.rows_emitted == rows


# ---------------------------------------------------------------------------
# Resume invariant: full[k:] == run-with-resume-from(k) for any 0 <= k <= n
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("k", [0, 1, 5, 9, 10])
def test_cli_resume_from_matches_truncated_full_run(write_config, tmp_path: Path, k: int) -> None:
    from ton.cli import main as cli_main

    config = write_config({"rows": 10})

    full_out = tmp_path / "full.txt"
    cli_main([str(config), "--seed", "0", "-o", str(full_out)])
    full_rows = full_out.read_text().splitlines()

    resume_out = tmp_path / "resume.txt"
    cli_main([str(config), "--seed", "0", "-o", str(resume_out), "--resume-from", str(k)])
    resume_rows = resume_out.read_text().splitlines()
    assert resume_rows == full_rows[k:]


# ---------------------------------------------------------------------------
# Concurrency: workers produce independent, reproducible streams whose
# union has no collisions on integer ids.
# ---------------------------------------------------------------------------


def test_fork_engine_workers_yield_disjoint_streams_when_partitioned() -> None:
    workers = 4
    rows_per_worker = 50
    chunks: list[list[str]] = []
    for wid in range(workers):
        config = {
            "rows": rows_per_worker,
            "format": "$id$",
            "types": {
                "id": {
                    "type": "sequence",
                    "start": wid * rows_per_worker,
                    "step": 1,
                }
            },
        }
        chunks.append(
            list(
                fork_engine(
                    config,
                    parent_seed=42,
                    worker_id=wid,
                    workers=workers,
                    rows=rows_per_worker,
                )
            )
        )
    flattened = [row for chunk in chunks for row in chunk]
    assert len(set(flattened)) == workers * rows_per_worker


@pytest.mark.parametrize("seed_pair", [(1, 1), (42, 42), (99, 99)])
def test_derive_rng_is_reproducible(seed_pair: tuple[int, int]) -> None:
    parent, worker = seed_pair
    first = [derive_rng(parent, worker).random() for _ in range(20)]
    second = [derive_rng(parent, worker).random() for _ in range(20)]
    assert first == second


# ---------------------------------------------------------------------------
# Template / placeholder: render(parse(...)) sanity for random templates
# ---------------------------------------------------------------------------


_TYPE_KEYS = ("alpha", "beta", "gamma", "delta", "epsilon")


def _random_multi_token_config(rng: Random) -> dict[str, Any]:
    used = rng.sample(_TYPE_KEYS, k=rng.randint(1, len(_TYPE_KEYS)))
    template_parts: list[str] = []
    for name in used:
        template_parts.append(f"${name}$")
        template_parts.append(rng.choice([" ", "-", ":", ","]))
    template_parts.append("\\end")
    template = "".join(template_parts)
    types = {
        name: {
            "type": "integer",
            "minValue": 0,
            "maxValue": 9,
            "padWithZero": False,
        }
        for name in used
    }
    return {"rows": 8, "format": template, "types": types}


@pytest.mark.parametrize("seed", list(range(40)))
def test_multi_token_templates_render_consistently(seed: int) -> None:
    rng = Random(seed)
    config = _random_multi_token_config(rng)
    rows = list(api.generate(config, seed=seed))
    assert len(rows) == 8
    placeholder_re = re.compile(r"\$\w+\$")
    for row in rows:
        # No raw placeholder survives.
        assert not placeholder_re.search(row)


# ---------------------------------------------------------------------------
# Make_registry: requested subset is what comes out, never more
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("seed", list(range(10)))
def test_make_registry_returns_only_requested_types(seed: int) -> None:
    rng = Random(seed)
    universe = [
        "integer",
        "decimal",
        "uuid",
        "sequence",
        "bytes",
        "text",
        "char",
        "string",
        "boolean",
    ]
    requested = set(rng.sample(universe, k=rng.randint(1, len(universe))))
    registry = make_registry(requested)
    assert set(registry.keys()) == requested


# ---------------------------------------------------------------------------
# Padded integer outputs: width invariant holds for every drawn value
# ---------------------------------------------------------------------------


_PAD_RANGES = [
    (0, 9999),
    (-999, 999),
    (-1, 1),
    (-100, -50),
]


@pytest.mark.parametrize("lo,hi", _PAD_RANGES)
@pytest.mark.parametrize("seed", list(range(10)))
def test_integer_pad_width_matches_widest_bound(lo: int, hi: int, seed: int) -> None:
    config = {
        "rows": 60,
        "format": "$n$",
        "types": {"n": {"type": "integer", "minValue": lo, "maxValue": hi, "padWithZero": True}},
    }
    expected_width = max(len(str(lo)), len(str(hi)))
    rows = list(api.generate(config, seed=seed))
    assert all(len(row) == expected_width for row in rows)


# ---------------------------------------------------------------------------
# Regex generator output continues to match its pattern across many seeds
# ---------------------------------------------------------------------------


_REGEX_FUZZ_PATTERNS = [
    "[A-Z0-9]{8}",
    "[a-z]+[0-9]*",
    "(red|green|blue)-[0-9]{2,4}",
    "[A-F0-9]{2}(:[A-F0-9]{2}){5}",
    "\\w{3,5}\\.\\w{2,3}@\\w{4,8}\\.(com|net|org)",
]


@pytest.mark.parametrize("pattern", _REGEX_FUZZ_PATTERNS)
def test_regex_output_property_across_many_seeds(pattern: str) -> None:
    config = {
        "rows": 30,
        "format": "$v$",
        "types": {"v": {"type": "regex", "pattern": pattern}},
    }
    matcher = re.compile(f"^{pattern}$")
    for seed in range(15):
        for row in api.generate(config, seed=seed):
            assert matcher.match(row), f"seed={seed}: {row!r} mismatches {pattern!r}"


# ---------------------------------------------------------------------------
# Paired generator: $name[id]$ and $name$ never desync within a row
# ---------------------------------------------------------------------------


def test_ntlm_paired_within_row_stays_consistent() -> None:
    config = {
        "rows": 100,
        "format": "$w[id]$=$w$",
        "types": {
            "w": {
                "type": "hash",
                "algorithm": "ntlm",
                "values": ["alpha", "bravo", "charlie"],
            }
        },
    }
    seen_pairs: set[tuple[str, str]] = set()
    for row in api.generate(config, seed=0):
        plain, hashed = row.split("=")
        seen_pairs.add((plain, hashed))
    # Each plaintext maps to exactly one hash; no plaintext shares a hash.
    by_plain = {p: h for p, h in seen_pairs}
    assert len(by_plain) == len({h for _, h in seen_pairs})


# ---------------------------------------------------------------------------
# JSON output integrity: every emitted line is a non-empty UTF-8 string
# ---------------------------------------------------------------------------


def test_cli_output_lines_are_utf8_decodable(write_config, tmp_path: Path) -> None:
    config_path = tmp_path / "cfg.json"
    config_path.write_text(
        json.dumps(
            {
                "rows": 25,
                "format": "$a$|$b$",
                "types": {
                    "a": {"type": "uuid", "version": 4},
                    "b": {"type": "bytes", "length": 8, "encoding": "hex"},
                },
            }
        ),
        encoding="utf-8",
    )
    out = tmp_path / "out.txt"
    from ton.cli import main as cli_main

    cli_main([str(config_path), "-o", str(out), "--seed", "1"])
    raw = out.read_bytes()
    assert raw.decode("utf-8")
    lines = raw.decode("utf-8").strip().splitlines()
    assert len(lines) == 25
    for line in lines:
        left, right = line.split("|")
        assert len(left) == 36  # uuid string length
        assert len(right) == 16  # 8 bytes hex


# ---------------------------------------------------------------------------
# Worst-case bound consistency: caps cannot be exceeded per row
# ---------------------------------------------------------------------------


def _capped_specs(rng: Random) -> list[Callable[[], int]]:
    """Return spec factories whose maximum output width is known."""
    pool = string_pool = ["a", "b", "c"]

    def char_factory() -> int:
        n = rng.randint(1, 32)
        config = {
            "rows": 5,
            "format": "$v$",
            "types": {"v": {"type": "char", "values": pool, "maxChar": n}},
        }
        for row in api.generate(config, seed=0):
            assert len(row) == n
        return n

    def bytes_factory() -> int:
        n = rng.randint(1, 32)
        config = {
            "rows": 5,
            "format": "$v$",
            "types": {"v": {"type": "bytes", "length": n, "encoding": "hex"}},
        }
        for row in api.generate(config, seed=0):
            assert len(row) == 2 * n
        return n

    def text_factory() -> int:
        n = rng.randint(1, 5)
        config = {
            "rows": 5,
            "format": "$v$",
            "types": {"v": {"type": "text", "unit": "words", "count": n}},
        }
        for row in api.generate(config, seed=0):
            assert len(row.split(" ")) == n
        return n

    assert string_pool == pool
    return [char_factory, bytes_factory, text_factory]


@pytest.mark.parametrize("seed", list(range(8)))
def test_per_field_caps_are_respected_at_random_inputs(seed: int) -> None:
    rng = Random(seed)
    factories = _capped_specs(rng)
    for factory in factories:
        factory()
