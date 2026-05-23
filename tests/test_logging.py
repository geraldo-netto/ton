"""Tests for the ``ton`` library logger (OBS-003)."""

from __future__ import annotations

import logging
from random import Random
from typing import Any, Dict

import pytest

from ton._engine import Engine
from ton._logging import LOGGER_NAME, configure_stderr, logger
from ton._registry import clear_default_registry_cache, default_registry


def test_logger_name_is_ton() -> None:
    assert logger.name == LOGGER_NAME
    assert logger is logging.getLogger("ton")


def test_logger_has_null_handler_attached() -> None:
    assert any(isinstance(h, logging.NullHandler) for h in logger.handlers)


def test_engine_construction_emits_info_event(
    basic_config: Dict[str, Any], caplog: pytest.LogCaptureFixture
) -> None:
    with caplog.at_level(logging.INFO, logger=LOGGER_NAME):
        Engine(basic_config, rng=Random(0))
    events = [r for r in caplog.records if getattr(r, "event", None) == "engine_constructed"]
    assert events, "expected an engine_constructed log record"
    record = events[0]
    assert record.rows == basic_config["rows"]  # type: ignore[attr-defined]
    assert record.types == len(basic_config["types"])  # type: ignore[attr-defined]
    assert record.paired is False  # type: ignore[attr-defined]


def test_engine_iteration_emits_completion(
    basic_config: Dict[str, Any], caplog: pytest.LogCaptureFixture
) -> None:
    with caplog.at_level(logging.INFO, logger=LOGGER_NAME):
        list(Engine(basic_config, rng=Random(0)))
    completed = [r for r in caplog.records if getattr(r, "event", None) == "engine_completed"]
    assert len(completed) == 1
    assert completed[0].rows == basic_config["rows"]  # type: ignore[attr-defined]


def test_engine_milestone_fires_at_configured_interval(
    basic_config: Dict[str, Any], caplog: pytest.LogCaptureFixture
) -> None:
    basic_config["rows"] = 10
    with caplog.at_level(logging.INFO, logger=LOGGER_NAME):
        list(Engine(basic_config, rng=Random(0), milestone_rows=3))
    milestones = [r for r in caplog.records if getattr(r, "event", None) == "engine_milestone"]
    # rows=10, interval=3 -> milestones at 3, 6, 9.
    assert [r.rows for r in milestones] == [3, 6, 9]  # type: ignore[attr-defined]


def test_engine_milestone_zero_disables_logging(
    basic_config: Dict[str, Any], caplog: pytest.LogCaptureFixture
) -> None:
    with caplog.at_level(logging.INFO, logger=LOGGER_NAME):
        list(Engine(basic_config, rng=Random(0), milestone_rows=0))
    milestones = [r for r in caplog.records if getattr(r, "event", None) == "engine_milestone"]
    assert milestones == []


def test_registry_discovery_emits_event(caplog: pytest.LogCaptureFixture) -> None:
    clear_default_registry_cache()
    with caplog.at_level(logging.INFO, logger=LOGGER_NAME):
        default_registry()
    events = [r for r in caplog.records if getattr(r, "event", None) == "registry_discovered"]
    assert events, "expected a registry_discovered log record"
    assert events[0].generators >= 20  # type: ignore[attr-defined]
    clear_default_registry_cache()


def test_configure_stderr_attaches_stream_handler() -> None:
    handler = configure_stderr(logging.DEBUG, fmt="%(message)s")
    try:
        assert handler in logger.handlers
        assert handler.level == logging.DEBUG
        assert logger.level <= logging.DEBUG
    finally:
        logger.removeHandler(handler)
