"""Tests that keep public documentation examples accurate."""

from __future__ import annotations

from pathlib import Path

README = (Path(__file__).resolve().parent.parent / "README.md").read_text(encoding="utf-8")


def test_library_streaming_example_writes_each_row_once() -> None:
    streaming_example = README.split("# Streaming form for large outputs:", 1)[1].split("```", 1)[0]

    assert streaming_example.count("sink.write(row)") == 1
