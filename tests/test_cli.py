"""Smoke tests for the CLI entry point."""

from __future__ import annotations

import io
import json
import os
import stat
import sys
from pathlib import Path
from unittest import mock

import pytest

from ton.cli import main


def test_cli_writes_rows_to_stdout(write_config, capsys: pytest.CaptureFixture[str]) -> None:
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


def test_cli_output_uses_configured_encoding(write_config, tmp_path: Path) -> None:
    config = write_config({"encoding": "utf-16"})
    out_file = tmp_path / "out.txt"
    assert main([str(config), "-o", str(out_file), "--seed", "0"]) == 0
    raw = out_file.read_bytes()
    # utf-16 encodes ASCII digits with a null high byte and a BOM.
    assert b"\x00" in raw
    assert out_file.read_text(encoding="utf-16").strip().splitlines() != []


def test_cli_stdout_uses_configured_encoding(write_config, monkeypatch) -> None:
    config = write_config({"encoding": "utf-16"})
    raw = io.BytesIO()
    stdout = io.TextIOWrapper(raw, encoding="utf-8")
    monkeypatch.setattr(sys, "stdout", stdout)

    assert main([str(config), "--seed", "0"]) == 0

    stdout.flush()
    data = raw.getvalue()
    assert b"\x00" in data
    assert data.decode("utf-16").strip().splitlines() != []
    assert stdout.encoding.lower().replace("_", "-") == "utf-8"


def test_cli_non_encodable_generated_stdout_returns_output_error(
    write_config, monkeypatch, capsys: pytest.CaptureFixture[str]
) -> None:
    config = write_config(
        {
            "encoding": "ascii",
            "format": "$word$",
            "types": {"word": {"type": "string", "values": ["café"]}},
        }
    )
    stdout = io.TextIOWrapper(io.BytesIO(), encoding="utf-8")
    monkeypatch.setattr(sys, "stdout", stdout)

    assert main([str(config)]) == 1
    error = capsys.readouterr().err
    assert "cannot write output" in error
    assert "unexpected error" not in error


def test_cli_non_encodable_literal_cleans_atomic_output(
    write_config, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    config = write_config({"encoding": "ascii", "format": "$n$é"})
    output = tmp_path / "out.txt"

    assert main([str(config), "-o", str(output)]) == 1
    assert not output.exists()
    assert list(tmp_path.glob(".out.txt.*.tmp")) == []
    assert "unexpected error" not in capsys.readouterr().err


def test_cli_stdout_without_reconfigure_still_writes(monkeypatch) -> None:
    from ton import cli

    stdout = io.StringIO()
    monkeypatch.setattr(sys, "stdout", stdout)

    with cli._open_output(None, encoding="utf-16") as stream:
        stream.write("ok")

    assert stdout.getvalue() == "ok"


def test_cli_seed_is_reproducible(write_config, capsys: pytest.CaptureFixture[str]) -> None:
    config = write_config()
    main([str(config), "--seed", "42"])
    first = capsys.readouterr().out
    main([str(config), "--seed", "42"])
    second = capsys.readouterr().out
    assert first == second


def test_cli_missing_config_returns_1(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    exit_code = main([str(tmp_path / "missing.json")])
    captured = capsys.readouterr()
    assert exit_code == 1
    assert "ton:" in captured.err


def test_cli_invalid_config_returns_2(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
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


def test_cli_progress_does_not_enable_engine_milestones(
    write_config, caplog: pytest.LogCaptureFixture
) -> None:
    config = write_config()

    with caplog.at_level("INFO", logger="ton"):
        assert main([str(config), "--seed", "0", "--progress", "2"]) == 0

    events = [getattr(record, "event", None) for record in caplog.records]
    assert "engine_progress" in events
    assert "engine_milestone" not in events


def test_cli_progress_counts_only_rows_written_after_resume(
    write_config, capsys: pytest.CaptureFixture[str]
) -> None:
    config = write_config()

    assert main([str(config), "--resume-from", "2", "--progress", "2"]) == 0

    progress = [
        json.loads(line) for line in capsys.readouterr().err.splitlines() if line.startswith("{")
    ]
    assert [event["rows"] for event in progress] == [2]


def test_cli_validate_checks_config_without_generating_rows(
    write_config, capsys: pytest.CaptureFixture[str]
) -> None:
    config = write_config()
    exit_code = main([str(config), "--validate"])
    captured = capsys.readouterr()
    assert exit_code == 0
    assert captured.out == ""
    assert "config valid" in captured.err


def test_cli_validate_reports_unknown_type_with_catalog_diagnostics(
    write_config, capsys: pytest.CaptureFixture[str]
) -> None:
    config = write_config({"format": "$x$", "types": {"x": {"type": "nope"}}})
    exit_code = main([str(config), "--validate"])
    captured = capsys.readouterr()
    assert exit_code == 2
    assert "invalid config" in captured.err
    assert "Available types" in captured.err


def test_cli_validate_rejects_bad_field_bounds(
    write_config, capsys: pytest.CaptureFixture[str]
) -> None:
    # --validate must run prepare so bad bounds fail here, not only at
    # generation time (CLI-001).
    config = write_config(
        {"format": "$x$", "types": {"x": {"type": "integer", "minValue": 100, "maxValue": 1}}}
    )
    exit_code = main([str(config), "--validate"])
    captured = capsys.readouterr()
    assert exit_code == 2
    assert "invalid config" in captured.err


def test_cli_validate_rejects_non_string_transform_type(
    write_config, capsys: pytest.CaptureFixture[str]
) -> None:
    config = write_config({"types": {"n": {"type": "integer", "transforms": [{"type": 7}]}}})

    assert main([str(config), "--validate"]) == 2
    assert "invalid config" in capsys.readouterr().err


def test_cli_validate_missing_config_returns_1(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    exit_code = main([str(tmp_path / "missing.json"), "--validate"])
    captured = capsys.readouterr()
    assert exit_code == 1
    assert "ton:" in captured.err


def test_cli_proof_audit_reports_clean_summary(
    write_config, capsys: pytest.CaptureFixture[str]
) -> None:
    config = write_config()
    exit_code = main([str(config), "--proof-check", "audit", "--seed", "0"])
    captured = capsys.readouterr()
    assert exit_code == 0
    assert "all generated values passed" in captured.err


def test_cli_proof_audit_reports_failure_count(
    monkeypatch, write_config, capsys: pytest.CaptureFixture[str]
) -> None:
    from random import Random
    from typing import Any

    from ton import cli
    from ton._engine import Engine
    from ton._proof import ProofResult
    from ton._transforms import TransformResult
    from ton.generators import Generator

    class FailingGenerator(Generator):
        type_name = "failing"

        def generate(self, prepared: Any, rng: Random) -> str:
            return "bad"

        def prove(self, prepared: Any, result: TransformResult) -> ProofResult:
            del prepared, result
            return ProofResult(ok=False, reason="bad value")

    engine = Engine.from_config(
        {"rows": 2, "format": "$v$", "types": {"v": {"type": "failing"}}},
        registry={"failing": FailingGenerator()},
        proof_mode="audit",
    )
    monkeypatch.setattr(cli, "_build_engine", lambda args, config: engine)
    config = write_config()
    exit_code = main([str(config), "--proof-check", "audit"])
    captured = capsys.readouterr()
    assert exit_code == 0
    assert "2 value(s) failed" in captured.err


def test_cli_help_does_not_expose_internal_todo_ids(
    capsys: pytest.CaptureFixture[str],
) -> None:
    with pytest.raises(SystemExit) as exc:
        main(["--help"])
    captured = capsys.readouterr()
    assert exc.value.code == 0
    assert "OBS-003" not in captured.out
    assert "--proof-check" in captured.out
    assert "--redact-proof-failures" not in captured.out
    assert "loading is opt-in" in captured.out


def test_cli_proof_choices_share_proof_checker_modes() -> None:
    from ton import cli
    from ton._proofcheck import PROOF_MODES

    action = next(action for action in cli._build_parser()._actions if action.dest == "proof_check")

    assert action.choices == PROOF_MODES


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


def test_cli_accepts_proof_check_flags(write_config, capsys: pytest.CaptureFixture[str]) -> None:
    config = write_config()
    exit_code = main(
        [
            str(config),
            "--proof-check",
            "sample",
            "--proof-sample-rate",
            "2",
        ]
    )
    captured = capsys.readouterr()

    assert exit_code == 0
    assert len(captured.out.strip().splitlines()) == 4


def test_cli_build_engine_preserves_seed_for_proof_context(write_config) -> None:
    from ton import cli

    config = write_config()
    args = cli._build_parser().parse_args(
        [
            str(config),
            "--seed",
            "7",
            "--proof-check",
            "audit",
        ]
    )
    engine = cli._build_engine(args, cli.api.load_config(str(config)))

    assert engine._seed == 7


def test_cli_proof_error_returns_2(
    monkeypatch, write_config, capsys: pytest.CaptureFixture[str]
) -> None:
    from ton import cli
    from ton.api import ProofError

    def _boom(*args, **kwargs):
        raise ProofError("bad generated value")

    monkeypatch.setattr(cli, "_stream", _boom)
    config = write_config()
    exit_code = main([str(config), "--proof-check", "all"])
    captured = capsys.readouterr()

    assert exit_code == 2
    assert "proof failed" in captured.err


def test_cli_row_time_template_error_returns_2(
    monkeypatch, write_config, capsys: pytest.CaptureFixture[str]
) -> None:
    from ton import cli
    from ton.api import TemplateError

    def _boom(*args, **kwargs):
        raise TemplateError("generator failed on row")

    monkeypatch.setattr(cli, "_stream", _boom)
    config = write_config()
    exit_code = main([str(config)])
    captured = capsys.readouterr()

    assert exit_code == 2
    assert "invalid config" in captured.err
    assert "unexpected error" not in captured.err


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


def test_cli_atomic_output_preserves_existing_file_mode(write_config, tmp_path: Path) -> None:
    config = write_config()
    out_file = tmp_path / "out.txt"
    out_file.write_text("old\n", encoding="utf-8")
    os.chmod(out_file, 0o644)

    assert main([str(config), "-o", str(out_file), "--seed", "0"]) == 0
    assert stat.S_IMODE(os.stat(out_file).st_mode) == 0o644


def test_cli_refuses_symlink_output_without_replacing_link(write_config, tmp_path: Path) -> None:
    config = write_config()
    target = tmp_path / "target.txt"
    target.write_text("old\n", encoding="utf-8")
    link = tmp_path / "output.txt"
    link.symlink_to(target)

    assert main([str(config), "-o", str(link)]) == 1
    assert link.is_symlink()
    assert target.read_text(encoding="utf-8") == "old\n"


def test_cli_atomic_output_new_file_respects_umask(write_config, tmp_path: Path) -> None:
    config = write_config()
    out_file = tmp_path / "fresh.txt"
    old_umask = os.umask(0o022)
    try:
        assert main([str(config), "-o", str(out_file), "--seed", "0"]) == 0
    finally:
        os.umask(old_umask)
    assert stat.S_IMODE(os.stat(out_file).st_mode) == 0o644


def test_cli_entry_point_allowlist_option_still_generates_rows(
    write_config, capsys: pytest.CaptureFixture[str]
) -> None:
    config = write_config()
    exit_code = main([str(config), "--entry-point", "trusted", "--seed", "0"])
    captured = capsys.readouterr()
    assert exit_code == 0
    assert len(captured.out.strip().splitlines()) == 4


def test_open_output_streams_existing_fifo(tmp_path: Path) -> None:
    from ton.cli import _open_output

    fifo = tmp_path / "rows.fifo"
    fifo.write_text("", encoding="utf-8")
    fifo_stat = os.stat_result(
        (
            stat.S_IFIFO | 0o600,
            0,
            0,
            1,
            0,
            0,
            0,
            0,
            0,
            0,
        )
    )
    opened = mock.mock_open()
    with (
        mock.patch("ton._output.os.stat", return_value=fifo_stat),
        mock.patch("builtins.open", opened),
        _open_output(str(fifo)) as writer,
    ):
        writer.write("row\n")

    opened.assert_called_once_with(str(fifo), "w", encoding="utf-8", newline="\n")
    opened().write.assert_called_once_with("row\n")
