"""Shared pytest fixtures.

Centralizes the small "config dict" / "config on disk" helpers that
were duplicated across test_engine.py, test_api.py, and test_cli.py
(TODO DUP-002).
"""

from __future__ import annotations

import json
from collections.abc import Callable
from pathlib import Path
from typing import Any

import pytest


def _basic_config() -> dict[str, Any]:
    """A minimal valid config: 4 rows of a single integer 1..9."""
    return {
        "rows": 4,
        "format": "$n$",
        "types": {
            "n": {"type": "integer", "minValue": 1, "maxValue": 9, "padWithZero": False},
        },
    }


@pytest.fixture
def basic_config() -> dict[str, Any]:
    """Return a fresh copy of the canonical basic config."""
    return _basic_config()


@pytest.fixture
def write_config(tmp_path: Path) -> Callable[..., Path]:
    """Return a helper that writes a config dict to a temp JSON file.

    Usage::

        def test_something(write_config):
            path = write_config()                 # canonical basic config
            path = write_config({"rows": 100})    # merge override
    """

    def _write(overrides: dict[str, Any] | None = None) -> Path:
        payload = _basic_config()
        if overrides:
            payload.update(overrides)
        path = tmp_path / "config.json"
        path.write_text(json.dumps(payload), encoding="utf-8")
        return path

    return _write
