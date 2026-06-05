"""Unit tests for the row-generation engine."""

from __future__ import annotations

from random import Random
from threading import Barrier, Thread

import pytest

from ton._engine import Engine, TemplateError


def test_engine_yields_requested_row_count(basic_config: dict) -> None:
    basic_config["rows"] = 5
    rows = list(Engine(basic_config, rng=Random(0)))
    assert len(rows) == 5


def test_engine_is_deterministic_for_a_seed(basic_config: dict) -> None:
    first = list(Engine(basic_config, rng=Random(123)))
    second = list(Engine(basic_config, rng=Random(123)))
    assert first == second


def test_engine_rejects_unknown_template_var(basic_config: dict) -> None:
    basic_config["format"] = "$missing$"
    with pytest.raises(TemplateError):
        Engine(basic_config)


def test_engine_rejects_unknown_type(basic_config: dict) -> None:
    basic_config["types"]["n"]["type"] = "nope"
    with pytest.raises(TemplateError):
        Engine(basic_config)


def test_engine_wraps_unexpected_prepare_error_as_template_error() -> None:
    """A buggy third-party generator that raises a non-ValueError must still
    surface as TemplateError so the CLI maps to exit 2 (REL-012)."""
    from collections.abc import Mapping
    from typing import Any

    from ton.generators import Generator

    class BrokenGenerator(Generator):
        type_name = "broken"

        def prepare(self, spec: Mapping[str, Any]) -> Any:
            raise RuntimeError("third-party plugin blew up")

        def generate(self, prepared: Any, rng: Random) -> str:
            return ""

    registry = {"broken": BrokenGenerator()}
    config = {
        "rows": 1,
        "format": "$v$",
        "types": {"v": {"type": "broken"}},
    }
    with pytest.raises(TemplateError, match="RuntimeError"):
        Engine(config, registry=registry)


def test_engine_pairs_lmhash_within_a_row() -> None:
    config = {
        "rows": 3,
        "format": "$word[id]$=$word$",
        "types": {"word": {"type": "lmhash", "values": ["alpha", "beta"]}},
    }
    for row in Engine(config, rng=Random(0)):
        plain, _, digest = row.partition("=")
        from ton.generators.lmhash import LMHashGenerator
        expected = LMHashGenerator._nt_hash(plain)
        assert digest == expected


def test_engine_rejects_concurrent_iteration(basic_config: dict) -> None:
    basic_config["rows"] = 2
    engine = Engine(basic_config, rng=Random(0))
    iterator = iter(engine)
    next(iterator)

    errors: list[BaseException] = []
    barrier = Barrier(2)

    def _iterate_again() -> None:
        barrier.wait()
        try:
            list(engine)
        except BaseException as exc:  # noqa: BLE001 - test captures thread failure
            errors.append(exc)

    thread = Thread(target=_iterate_again)
    thread.start()
    barrier.wait()
    thread.join(timeout=2)
    list(iterator)

    assert len(errors) == 1
    assert isinstance(errors[0], RuntimeError)
    assert "concurrently" in str(errors[0])
