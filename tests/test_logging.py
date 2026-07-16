"""Tests for the ``ton`` library logger (OBS-003)."""

from __future__ import annotations

import logging
from pathlib import Path
from random import Random
from typing import Any
from unittest import mock

import pytest

from ton import api
from ton._engine import Engine
from ton._logging import LOGGER_NAME, LogEvent, configure_stderr, logger, terminal_failure_fields
from ton._proof import ProofResult
from ton._registry import clear_default_registry_cache, default_registry
from ton._transforms import TransformResult
from ton.generators import Generator


def test_terminal_failure_schema_is_safe_and_complete() -> None:
    fields = terminal_failure_fields(
        "output", 1, rows_written=3, total_rows=10, error_type="OSError"
    )

    assert fields == {
        "event": "cli_failed",
        "error_category": "output",
        "exit_code": 1,
        "rows_written": 3,
        "total_rows": 10,
        "error_type": "OSError",
    }
    with pytest.raises(ValueError, match="unknown terminal"):
        terminal_failure_fields("other", 1, rows_written=0, total_rows=0, error_type="X")


def test_logger_name_is_ton() -> None:
    assert logger.name == LOGGER_NAME
    assert logger is logging.getLogger("ton")


def test_logger_has_null_handler_attached() -> None:
    assert any(isinstance(h, logging.NullHandler) for h in logger.handlers)


def test_engine_construction_emits_info_event(
    basic_config: dict[str, Any], caplog: pytest.LogCaptureFixture
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
    basic_config: dict[str, Any], caplog: pytest.LogCaptureFixture
) -> None:
    with caplog.at_level(logging.INFO, logger=LOGGER_NAME):
        list(Engine(basic_config, rng=Random(0)))
    completed = [r for r in caplog.records if getattr(r, "event", None) == "engine_completed"]
    assert len(completed) == 1
    assert completed[0].rows == basic_config["rows"]  # type: ignore[attr-defined]


def test_engine_milestone_fires_at_configured_interval(
    basic_config: dict[str, Any], caplog: pytest.LogCaptureFixture
) -> None:
    basic_config["rows"] = 10
    with caplog.at_level(logging.INFO, logger=LOGGER_NAME):
        list(Engine(basic_config, rng=Random(0), milestone_rows=3))
    milestones = [r for r in caplog.records if getattr(r, "event", None) == "engine_milestone"]
    # rows=10, interval=3 -> milestones at 3, 6, 9.
    assert [r.rows for r in milestones] == [3, 6, 9]  # type: ignore[attr-defined]


def test_engine_milestone_zero_disables_logging(
    basic_config: dict[str, Any], caplog: pytest.LogCaptureFixture
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


def test_plugin_registration_emits_structured_event(
    caplog: pytest.LogCaptureFixture,
) -> None:
    class CustomGenerator(Generator):
        type_name = "custom"

        def generate(self, prepared: Any, rng: Random) -> str:
            return "custom"

    ep = mock.Mock()
    ep.name = "acme.custom"
    ep.value = "pkg:Custom"
    ep.load.return_value = CustomGenerator

    def _entry_points(group: str):
        return [ep] if group == "ton.generators" else []

    with (
        mock.patch("ton._registry.entry_points", side_effect=_entry_points),
        caplog.at_level(logging.INFO, logger=LOGGER_NAME),
    ):
        api.build_extension_catalog(include_entry_points=True)

    events = [r for r in caplog.records if getattr(r, "event", None) == "plugin_registered"]
    assert events
    assert events[0].kind == "data_type"  # type: ignore[attr-defined]
    assert events[0].reference == "acme.custom"  # type: ignore[attr-defined]


def test_transform_preparation_emits_structured_event(
    caplog: pytest.LogCaptureFixture,
) -> None:
    config = {
        "rows": 1,
        "format": "$v$",
        "types": {
            "v": {
                "type": "string",
                "values": ["x"],
                "transforms": [{"type": "identity"}],
            }
        },
    }

    with caplog.at_level(logging.INFO, logger=LOGGER_NAME):
        Engine(config, rng=Random(0))

    events = [r for r in caplog.records if getattr(r, "event", None) == "transform_prepared"]
    assert events
    assert events[0].type_key == "v"  # type: ignore[attr-defined]
    assert events[0].transform == "identity"  # type: ignore[attr-defined]


def test_proof_failure_logs_identifier_without_value(
    caplog: pytest.LogCaptureFixture,
) -> None:
    class FailingGenerator(Generator):
        type_name = "failing"

        def generate(self, prepared: Any, rng: Random) -> str:
            return "secret-value"

        def prove(self, prepared: Any, result: TransformResult) -> ProofResult:
            del prepared, result
            return ProofResult(ok=False, reason="bad")

    config = {"rows": 1, "format": "$v$", "types": {"v": {"type": "failing"}}}
    engine = Engine.from_config(
        config,
        registry={"failing": FailingGenerator()},
        proof_mode="audit",
    )

    with caplog.at_level(logging.INFO, logger=LOGGER_NAME):
        assert list(engine) == ["secret-value"]

    failures = [r for r in caplog.records if getattr(r, "event", None) == "proof_check_failed"]
    summaries = [r for r in caplog.records if getattr(r, "event", None) == "proof_check_summary"]
    assert failures
    assert failures[0].type_key == "v"  # type: ignore[attr-defined]
    assert not any("secret-value" in record.getMessage() for record in caplog.records)
    assert summaries[0].failures == 1  # type: ignore[attr-defined]
    # proof_check_summary always carries a mode field (OBS-002).
    assert summaries[0].mode == "audit"  # type: ignore[attr-defined]


def test_cli_audit_summary_event_carries_mode(
    caplog: pytest.LogCaptureFixture, write_config
) -> None:
    from ton.cli import main

    config = write_config()
    with caplog.at_level(logging.INFO, logger=LOGGER_NAME):
        main([str(config), "--proof-check", "audit", "--seed", "0"])

    summaries = [r for r in caplog.records if getattr(r, "event", None) == "proof_check_summary"]
    # Both the engine and the CLI audit summary emit the same event; every
    # one carries a mode field so consumers see a consistent schema (OBS-002).
    assert summaries
    assert all(getattr(r, "mode", None) == "audit" for r in summaries)


def test_readme_documents_every_log_event() -> None:
    # The README observability table is the public event catalog; keep it
    # complete so it cannot silently drift from the enum (DOC-001).
    readme = (Path(__file__).resolve().parent.parent / "README.md").read_text(encoding="utf-8")
    missing = [event.value for event in LogEvent if f"`{event.value}`" not in readme]
    assert missing == [], f"README event table is missing: {missing}"


def test_catalog_validation_emits_summary(caplog: pytest.LogCaptureFixture) -> None:
    config = {
        "rows": 1,
        "format": "$v$",
        "types": {"v": {"type": "string", "values": ["x"]}},
    }

    with caplog.at_level(logging.INFO, logger=LOGGER_NAME):
        api.validate_config(config)

    events = [r for r in caplog.records if getattr(r, "event", None) == "config_validated"]
    assert events
    assert events[0].types == 1  # type: ignore[attr-defined]


def test_configure_stderr_attaches_stream_handler() -> None:
    handler = configure_stderr(logging.DEBUG, fmt="%(message)s")
    try:
        assert handler in logger.handlers
        assert handler.level == logging.DEBUG
        assert logger.level <= logging.DEBUG
    finally:
        logger.removeHandler(handler)


def test_configure_stderr_is_idempotent() -> None:
    first = configure_stderr(logging.INFO, fmt="%(message)s")
    second = configure_stderr(logging.ERROR, fmt="%(levelname)s:%(message)s")
    try:
        assert first is second
        assert logger.handlers.count(first) == 1
        assert first.level == logging.ERROR
    finally:
        logger.removeHandler(first)


def test_configure_stderr_can_lower_logger_level() -> None:
    original_level = logger.level
    logger.setLevel(logging.ERROR)
    handler = configure_stderr(logging.DEBUG)
    try:
        assert logger.level == logging.DEBUG
    finally:
        logger.removeHandler(handler)
        logger.setLevel(original_level)


def test_configure_stderr_existing_handler_can_lower_logger_level() -> None:
    original_level = logger.level
    handler = configure_stderr(logging.INFO)
    logger.setLevel(logging.ERROR)
    try:
        same = configure_stderr(logging.DEBUG)
        assert same is handler
        assert logger.level == logging.DEBUG
    finally:
        logger.removeHandler(handler)
        logger.setLevel(original_level)
