"""Smoke tests for the CLI entry point."""

from __future__ import annotations

import json
import os
from pathlib import Path
from threading import Thread

import pytest

from ton.cli import main


def test_cli_writes_rows_to_stdout(
    write_config, capsys: pytest.CaptureFixture[str]
) -> None:
    config = write_config()
    exit_code = main([str(config), "--seed", "0"])
    captured = capsys.readouterr()
    assert exit_code == 0
    lines = captured.out.strip().splitlines()
    assert len(lines) == 4
    assert all(line.isdigit() for line in lines)


def test_cli_writes_rows_to_output_file(write_config, tmp_path: Path) -> None:
    config = write_config()
    out_file = tmp_path / "out.txt"
    exit_code = main([str(config), "-o", str(out_file), "--seed", "0"])
    assert exit_code == 0
    assert len(out_file.read_text().strip().splitlines()) == 4


def test_cli_seed_is_reproducible(
    write_config, capsys: pytest.CaptureFixture[str]
) -> None:
    config = write_config()
    main([str(config), "--seed", "42"])
    first = capsys.readouterr().out
    main([str(config), "--seed", "42"])
    second = capsys.readouterr().out
    assert first == second


def test_cli_missing_config_returns_1(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    exit_code = main([str(tmp_path / "missing.json")])
    captured = capsys.readouterr()
    assert exit_code == 1
    assert "ton:" in captured.err


def test_cli_invalid_config_returns_2(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    bad = tmp_path / "bad.json"
    bad.write_text("{}", encoding="utf-8")
    exit_code = main([str(bad)])
    captured = capsys.readouterr()
    assert exit_code == 2
    assert "ton:" in captured.err


def test_cli_verbose_prints_summary_to_stderr(
    write_config, capsys: pytest.CaptureFixture[str]
) -> None:
    config = write_config()
    exit_code = main([str(config), "--seed", "0", "--verbose"])
    captured = capsys.readouterr()
    assert exit_code == 0
    assert "wrote 4 rows" in captured.err
    assert "rows/s" in captured.err


def test_cli_unwritable_output_returns_1(
    write_config, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    config = write_config()
    bad_output = tmp_path / "no_such_dir" / "out.txt"
    exit_code = main([str(config), "-o", str(bad_output)])
    captured = capsys.readouterr()
    assert exit_code == 1
    assert "cannot write output" in captured.err


def test_cli_unexpected_error_returns_3(
    monkeypatch, write_config, capsys: pytest.CaptureFixture[str]
) -> None:
    """Anything not already mapped to exit 1/2 should still produce a
    clean 'ton: ...' line and exit 3, not a Python traceback (REL-013)."""
    from ton import cli

    def _boom(*args, **kwargs):
        raise RuntimeError("simulated upstream failure")

    monkeypatch.setattr(cli, "_build_engine", _boom)
    config = write_config()
    exit_code = main([str(config)])
    captured = capsys.readouterr()
    assert exit_code == 3
    assert "unexpected error" in captured.err
    assert "RuntimeError" in captured.err


def test_cli_keyboard_interrupt_returns_130(
    monkeypatch, write_config, capsys: pytest.CaptureFixture[str]
) -> None:
    from ton import cli

    def _boom(*args, **kwargs):
        raise KeyboardInterrupt

    monkeypatch.setattr(cli, "_build_engine", _boom)
    config = write_config()
    exit_code = main([str(config)])
    captured = capsys.readouterr()
    assert exit_code == 130
    assert "interrupted" in captured.err


def test_cli_progress_emits_json_lines_to_stderr(
    write_config, capsys: pytest.CaptureFixture[str]
) -> None:
    config = write_config()
    exit_code = main([str(config), "--seed", "0", "--progress", "2"])
    captured = capsys.readouterr()
    assert exit_code == 0
    # 4 rows, progress every 2 -> two JSON lines.
    progress_lines = [line for line in captured.err.splitlines() if line.startswith("{")]
    assert len(progress_lines) == 2
    payload = json.loads(progress_lines[-1])
    assert payload["rows"] == 4
    assert "elapsed_seconds" in payload


def test_cli_validate_checks_config_without_generating_rows(
    write_config, capsys: pytest.CaptureFixture[str]
) -> None:
    config = write_config()
    exit_code = main([str(config), "--validate"])
    captured = capsys.readouterr()
    assert exit_code == 0
    assert captured.out == ""
    assert "config valid" in captured.err


def test_cli_help_does_not_expose_internal_todo_ids(
    capsys: pytest.CaptureFixture[str],
) -> None:
    with pytest.raises(SystemExit) as exc:
        main(["--help"])
    captured = capsys.readouterr()
    assert exc.value.code == 0
    assert "OBS-003" not in captured.out
    assert "--proof-check" in captured.out
    assert "loading is opt-in" in captured.out


def test_cli_list_namespaces_without_config(capsys: pytest.CaptureFixture[str]) -> None:
    exit_code = main(["--list-namespaces"])
    captured = capsys.readouterr()

    assert exit_code == 0
    assert "namespaces: core" in captured.out
    assert "string" in captured.out
    assert "distribution" in captured.out


def test_cli_requires_config_when_not_listing(
    capsys: pytest.CaptureFixture[str],
) -> None:
    exit_code = main([])
    captured = capsys.readouterr()

    assert exit_code == 1
    assert "config path is required" in captured.err


def test_cli_accepts_proof_check_flags(
    write_config, capsys: pytest.CaptureFixture[str]
) -> None:
    config = write_config()
    exit_code = main([
        str(config),
        "--proof-check",
        "sample",
        "--proof-sample-rate",
        "2",
    ])
    captured = capsys.readouterr()

    assert exit_code == 0
    assert len(captured.out.strip().splitlines()) == 4


def test_cli_atomic_output_keeps_existing_file_on_failure(
    monkeypatch, write_config, tmp_path: Path
) -> None:
    from ton import cli

    config = write_config()
    out_file = tmp_path / "out.txt"
    out_file.write_text("old\n", encoding="utf-8")

    def _boom(*args, **kwargs):
        raise RuntimeError("stream failed")

    monkeypatch.setattr(cli, "_stream", _boom)
    assert main([str(config), "-o", str(out_file)]) == 3
    assert out_file.read_text(encoding="utf-8") == "old\n"
    assert list(tmp_path.glob(".out.txt.*.tmp")) == []


def test_cli_entry_point_allowlist_option_still_generates_rows(
    write_config, capsys: pytest.CaptureFixture[str]
) -> None:
    config = write_config()
    exit_code = main([str(config), "--entry-point", "trusted", "--seed", "0"])
    captured = capsys.readouterr()
    assert exit_code == 0
    assert len(captured.out.strip().splitlines()) == 4


def test_open_output_streams_existing_fifo(tmp_path: Path) -> None:
    if not hasattr(os, "mkfifo"):
        pytest.skip("mkfifo is not available on this platform")
    from ton.cli import _open_output

    fifo = tmp_path / "rows.fifo"
    os.mkfifo(fifo)
    received: list[str] = []

    def _read_fifo() -> None:
        with open(fifo, encoding="utf-8") as reader:
            received.append(reader.read())

    reader_thread = Thread(target=_read_fifo)
    reader_thread.start()
    with _open_output(str(fifo)) as writer:
        writer.write("row\n")
    reader_thread.join(timeout=2)

    assert received == ["row\n"]
