"""Library-level logger for TON (OBS-003).

Single module-scoped :class:`logging.Logger` named ``ton``. Library code
emits structured INFO events at structural boundaries:

* engine construction (rows, declared types, paired flag),
* row-count milestones (opt-in via :class:`ton._engine.Engine`'s
  ``milestone_rows`` argument),
* generator-registry discovery and entry-point loading.

Library callers attach a handler the usual way::

    import logging
    logging.basicConfig(level=logging.INFO)
    # ...or wire a handler to ``logging.getLogger("ton")`` directly.

A :class:`logging.NullHandler` is attached at import time so library
code never emits the "No handlers could be found" warning when no
caller has configured logging.
"""

from __future__ import annotations

import logging
from enum import Enum
from typing import Any

LOGGER_NAME = "ton"

logger = logging.getLogger(LOGGER_NAME)
logger.addHandler(logging.NullHandler())


class LogEvent(str, Enum):
    """Canonical ``event=...`` discriminator for the ``ton`` logger.

    Promotes the previously stringly-typed event values into a typed
    enum so consumers can ``match LogEvent(record.event)`` instead of
    string-comparing (PAT-010). The enum subclasses ``str`` so the
    serialised value in log handlers / JSON sinks stays the same
    canonical string ("engine_constructed", "engine_milestone", ...).

    Callers that emit events should write ``LogEvent.<NAME>.value`` into
    the ``extra`` dict so the on-the-wire representation is the bare
    string regardless of Python version (``str(Enum.X)`` was changed in
    3.11).
    """

    ENGINE_CONSTRUCTED = "engine_constructed"
    ENGINE_MILESTONE = "engine_milestone"
    ENGINE_COMPLETED = "engine_completed"
    ENGINE_PROGRESS = "engine_progress"
    ENGINE_FORKED = "engine_forked"
    PREPARE_FAILED = "prepare_failed"
    GENERATE_FAILED = "generate_failed"
    REGISTRY_DISCOVERED = "registry_discovered"
    ENTRY_POINT_LOADED = "entry_point_loaded"
    ENTRY_POINT_FAILED = "entry_point_failed"
    ENTRY_POINTS_SUMMARY = "entry_points_summary"
    PLUGIN_REGISTERED = "plugin_registered"
    TRANSFORM_PREPARED = "transform_prepared"
    PROOF_CHECK_FAILED = "proof_check_failed"
    PROOF_CHECK_SUMMARY = "proof_check_summary"
    CONFIG_VALIDATED = "config_validated"
    OUTPUT_OVERWRITE = "output_overwrite"
    OUTPUT_SPECIAL_FILE_REJECTED = "output_special_file_rejected"
    RESUME_OVERSHOOT = "resume_overshoot"
    CLI_UNEXPECTED_ERROR = "cli_unexpected_error"
    CLI_FAILED = "cli_failed"


#: ``pipeline`` is a component (generator/transform/validator/proof hook)
#: raising at row time; ``unexpected`` is anything the CLI did not
#: attribute to one. Both exit 3 (CLI-002).
FAILURE_CATEGORIES = frozenset(("validation", "proof", "output", "pipeline", "unexpected"))


def terminal_failure_fields(
    category: str,
    exit_code: int,
    *,
    rows_written: int,
    total_rows: int,
    error_type: str,
) -> dict[str, Any]:
    """Build the safe, stable payload for one terminal CLI failure."""
    if category not in FAILURE_CATEGORIES:
        raise ValueError(f"unknown terminal failure category {category!r}")
    return {
        "event": LogEvent.CLI_FAILED.value,
        "error_category": category,
        "exit_code": exit_code,
        "rows_written": rows_written,
        "total_rows": total_rows,
        "error_type": error_type,
    }


def configure_stderr(
    level: int = logging.INFO,
    *,
    fmt: str | None = None,
) -> logging.Handler:
    """Attach a stderr handler to the ``ton`` logger and return it.

    The CLI calls this when ``--log-level`` is passed. Library callers
    generally prefer to wire their own handler instead of using this
    helper so the formatter and destination stay under their control.
    """
    formatter = logging.Formatter(fmt or "ton: %(levelname)s %(message)s")
    for existing in logger.handlers:
        if getattr(existing, "_ton_configure_stderr", False):
            if getattr(getattr(existing, "stream", None), "closed", False):
                logger.removeHandler(existing)
                continue
            existing.setLevel(level)
            existing.setFormatter(formatter)
            if logger.level == logging.NOTSET or level < logger.level:
                logger.setLevel(level)
            return existing
    handler = logging.StreamHandler()
    handler._ton_configure_stderr = True  # type: ignore[attr-defined]
    handler.setLevel(level)
    handler.setFormatter(formatter)
    logger.addHandler(handler)
    if logger.level == logging.NOTSET or level < logger.level:
        logger.setLevel(level)
    return handler
