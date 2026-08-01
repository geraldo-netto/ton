"""Tests that keep public documentation examples accurate."""

from __future__ import annotations

from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
README = (ROOT / "README.md").read_text(encoding="utf-8")
CI = (ROOT / ".github" / "workflows" / "ci.yml").read_text(encoding="utf-8")
PRE_COMMIT = (ROOT / ".githooks" / "pre-commit").read_text(encoding="utf-8")


def test_library_streaming_example_writes_each_row_once() -> None:
    streaming_example = README.split("# Streaming form for large outputs:", 1)[1].split("```", 1)[0]

    assert streaming_example.count("sink.write(row)") == 1


def test_documented_quality_commands_match_ci_and_pre_commit_gate() -> None:
    commands = (
        "ruff check ton tests",
        "ruff format --check ton tests",
        "mypy ton",
        "pyright ton",
    )

    for command in commands:
        assert command in README
        assert command in CI
        assert command in PRE_COMMIT
    assert "mypy ton tests" not in README
