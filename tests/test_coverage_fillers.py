"""Tests added purely to push per-file coverage above 80%.

Each test exercises a code path the regular tests did not reach yet
(error-handling branches, the ``python -m ton`` invocation, public
helpers that are exported but unused inside the package).
"""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path
from random import Random
from typing import Any
from unittest import mock

import pytest

REPO_ROOT = Path(__file__).resolve().parent.parent


def test_python_m_ton_runs_cli() -> None:
    """`python -m ton` should invoke ton.cli.main and respect --version."""
    from ton import __version__

    result = subprocess.run(
        [sys.executable, "-m", "ton", "--version"],
        cwd=REPO_ROOT,
        capture_output=True,
        text=True,
        timeout=10,
    )
    assert result.returncode == 0
    assert result.stdout.strip() == f"ton {__version__}"


@pytest.mark.parametrize("example", ["dna.json", "hwmetrics.json", "winhash.json"])
def test_python_m_ton_with_example_config(example: str) -> None:
    """End-to-end smoke through the __main__ entry point."""
    result = subprocess.run(
        [sys.executable, "-m", "ton", f"examples/{example}", "--seed", "1"],
        cwd=REPO_ROOT,
        capture_output=True,
        text=True,
        timeout=10,
    )
    assert result.returncode == 0
    assert len(result.stdout.strip().splitlines()) == 10


def test_ton_main_executes_inprocess(monkeypatch) -> None:
    """Drive ``ton.__main__`` via runpy so the ``if __name__ == '__main__'``
    block executes inside this process and contributes to coverage."""
    import runpy

    monkeypatch.setattr(sys, "argv", ["ton", "--version"])
    with pytest.raises(SystemExit) as info:
        runpy.run_module("ton", run_name="__main__")
    assert info.value.code == 0


# ---------------------------------------------------------------------------
# Public helpers exported but unused inside the package
# ---------------------------------------------------------------------------


def test_require_non_empty_values_accepts_list() -> None:
    from ton.generators.base import require_non_empty_values

    assert require_non_empty_values({"values": [1, 2, 3]}) == [1, 2, 3]


@pytest.mark.parametrize("spec", [{}, {"values": None}, {"values": []}, {"values": "abc"}])
def test_require_non_empty_values_rejects_bad_input(spec: dict) -> None:
    from ton.generators.base import require_non_empty_values

    with pytest.raises(ValueError):
        require_non_empty_values(spec)


# ---------------------------------------------------------------------------
# Registry: subclass walk visits duplicate edges (`continue`) and the
# entry-point loop body.
# ---------------------------------------------------------------------------


def test_walk_subclasses_dedups_diamond_inheritance() -> None:
    """`_walk_subclasses` must skip classes it has already yielded."""
    from ton._registry import _walk_subclasses
    from ton.generators import Generator

    # The Generator subclass tree already contains diamond-ish edges
    # because PairedGenerator subclasses can be reached through multiple
    # inheritance paths. The walker should yield each
    # class exactly once regardless of how many paths reach it.
    seen = list(_walk_subclasses(Generator))
    assert len(seen) == len(set(seen))


def test_registry_with_entry_points_merges_in_third_party() -> None:
    """Synthesize a fake entry-point and verify the merged registry."""
    from ton._registry import registry_with_entry_points
    from ton.generators import Generator

    class FakePlugin(Generator):
        type_name = "fake_plugin"

        def generate(self, prepared: Any, rng: Random) -> str:
            return "synthetic"

    fake_ep = mock.Mock()
    fake_ep.name = "fake_plugin"
    fake_ep.load.return_value = FakePlugin

    with mock.patch("ton._registry.entry_points", return_value=[fake_ep]):
        merged = registry_with_entry_points()

    assert "fake_plugin" in merged
    assert isinstance(merged["fake_plugin"], FakePlugin)


# ---------------------------------------------------------------------------
# CLI _report branch when elapsed time rounds to 0.0
# ---------------------------------------------------------------------------


def test_cli_report_handles_zero_elapsed(capsys: pytest.CaptureFixture[str]) -> None:
    """_report should not ZeroDivisionError when elapsed == 0."""
    from ton.cli import _report

    _report(rows=0, elapsed=0.0)
    captured = capsys.readouterr()
    assert "0 rows" in captured.err


# ---------------------------------------------------------------------------
# Regex generator branches: NOT_LITERAL, ANY (.), AT (anchors), CATEGORY
# negation forms, NEGATE class.
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "pattern",
    [
        ".",  # ANY
        "[^abc]",  # NEGATE
        "[^0-9]",  # NEGATE with RANGE
        "\\D",  # CATEGORY_NOT_DIGIT
        "\\W",  # CATEGORY_NOT_WORD
        "\\S",  # CATEGORY_NOT_SPACE
        "[^\\d]",  # NEGATE with CATEGORY
        r"^abc$",  # AT anchors
        "[abc\\d]",  # class with literal + category
    ],
)
def test_regex_generator_handles_extended_constructs(pattern: str) -> None:
    from ton.generators.regex import RegexGenerator

    gen = RegexGenerator()
    prepared = gen.prepare({"pattern": pattern})
    for seed in range(5):
        value = gen.generate(prepared, Random(seed))
        assert isinstance(value, str)


# ---------------------------------------------------------------------------
# Network generator edge cases
# ---------------------------------------------------------------------------


def test_ipv6_default_cidr_returns_value() -> None:
    from ton.generators.network import IPv6Generator

    gen = IPv6Generator()
    prepared = gen.prepare({})  # default ::/0
    assert ":" in gen.generate(prepared, Random(0))


def test_mac_separator_can_be_empty() -> None:
    from ton.generators.network import MACGenerator

    gen = MACGenerator()
    prepared = gen.prepare({"separator": ""})
    value = gen.generate(prepared, Random(0))
    # 12 hex chars, no separators.
    assert len(value) == 12
    assert all(c in "0123456789abcdef" for c in value)


def test_mac_oui_non_string_rejected() -> None:
    """`oui` value must be a string."""
    from ton.generators.network import MACGenerator

    generator = MACGenerator()
    with pytest.raises(ValueError):
        generator.prepare({"oui": 12345})


def test_mac_oui_non_hex_rejected() -> None:
    """`oui` value with non-hex characters is rejected."""
    from ton.generators.network import MACGenerator

    generator = MACGenerator()
    with pytest.raises(ValueError):
        generator.prepare({"oui": "zzzzzz"})


# ---------------------------------------------------------------------------
# _config _validate_root / _validate_format / _validate_types rejection
# branches (small functions where missing one branch drops below 80% per
# function).
# ---------------------------------------------------------------------------


def test_validate_root_rejects_non_dict() -> None:
    from ton._config import ConfigError, validate_structure

    with pytest.raises(ConfigError, match="JSON object"):
        validate_structure([1, 2, 3])


def test_validate_format_rejects_non_string() -> None:
    from ton._config import ConfigError, validate_structure

    with pytest.raises(ConfigError, match="'format' must"):
        validate_structure({"rows": 1, "format": 42, "types": {"a": {"type": "string"}}})


def test_validate_types_rejects_non_dict() -> None:
    from ton._config import ConfigError, validate_structure

    with pytest.raises(ConfigError, match="'types' must"):
        validate_structure({"rows": 1, "format": "$a$", "types": []})


# ---------------------------------------------------------------------------
# weighted rejects non-list values
# ---------------------------------------------------------------------------


def test_weighted_rejects_non_list_values() -> None:
    from ton.generators.weighted import WeightedGenerator

    generator = WeightedGenerator()
    with pytest.raises(ValueError, match="must be a list"):
        generator.prepare({"values": "abc", "weights": [1, 2, 3]})


# ---------------------------------------------------------------------------
# timestamp_unix already-tz-aware path
# ---------------------------------------------------------------------------


def test_timestamp_unix_handles_tz_aware_input() -> None:
    from ton.generators.timestamp_unix import TimestampUnixGenerator

    gen = TimestampUnixGenerator()
    prepared = gen.prepare(
        {
            "minValue": "2024-01-01T00:00:00+00:00",
            "maxValue": "2024-01-01T00:00:01+00:00",
        }
    )
    assert int(gen.generate(prepared, Random(0))) > 0


# ---------------------------------------------------------------------------
# api.generate_from_file is the only api entry not covered yet.
# ---------------------------------------------------------------------------


def test_api_generate_from_file_with_seed(write_config) -> None:
    from ton import api

    path = write_config()
    rows = list(api.generate_from_file(str(path), seed=1))
    assert len(rows) == 4


def test_api_build_registry_with_entry_points_default() -> None:
    """Cover the include_entry_points=True branch of build_registry."""
    from ton import api

    with pytest.warns(DeprecationWarning):
        registry = api.build_registry()  # default True
    assert "integer" in registry


def test_cli_stream_flushes_batch_when_buffer_full(
    tmp_path, capsys: pytest.CaptureFixture[str]
) -> None:
    """Exercise the mid-iteration batch flush in cli._stream."""
    import json

    from ton.cli import main

    config_path = tmp_path / "big.json"
    config_path.write_text(
        json.dumps(
            {
                "rows": 5000,  # > 2 * _BATCH_ROWS triggers the mid-stream write
                "format": "$n$",
                "types": {
                    "n": {"type": "integer", "minValue": 0, "maxValue": 9, "padWithZero": False}
                },
            }
        ),
        encoding="utf-8",
    )
    output = tmp_path / "out.txt"
    code = main([str(config_path), "-o", str(output), "--seed", "0"])
    assert code == 0
    assert len(output.read_text().strip().splitlines()) == 5000
