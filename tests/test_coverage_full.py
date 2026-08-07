"""Tests targeting the remaining uncovered lines to reach 100% coverage.

Each test is named for the file and approximate concern it exercises.
Direct calls into private helpers are used when the missing line is
unreachable from the public surface (e.g. an internal dispatch branch
guarded by a check that the user-facing parser already rejects).
"""

from __future__ import annotations

import json
import logging
import threading
from collections.abc import Mapping
from pathlib import Path
from random import Random
from typing import Any
from unittest import mock

import pytest

from ton import api
from ton._engine import Engine, TemplateError
from ton._registry import (
    _ensure_default_classes,
    _entry_point_dist,
    _walk_subclasses,
    clear_default_registry_cache,
)
from ton._template import Token, split_segments
from ton.cli import main as cli_main
from ton.generators import Generator
from ton.generators.base import coerce_int

# ---------------------------------------------------------------------------
# _template.split_segments: ``$$`` literal continue branch
# ---------------------------------------------------------------------------


def test_split_segments_skips_literal_dollar_escapes() -> None:
    """Template with `$$` literals plus a real token must split correctly."""
    literals, tokens = split_segments("$$prefix$$$name$tail$$")
    assert tokens == [Token(type_key="name", wants_id=False)]
    assert literals[0] == "$prefix$"
    assert literals[1] == "tail$"


# ---------------------------------------------------------------------------
# _registry._walk_subclasses: seen-skip via diamond inheritance
# ---------------------------------------------------------------------------


def test_walk_subclasses_skips_already_yielded_diamond() -> None:
    """Diamond hierarchy makes the same subclass appear twice on the stack."""

    class Root:
        pass

    class Middle(Root):
        pass

    class Leaf(Middle):  # Leaf is reachable via Root -> Middle -> Leaf
        pass

    # ``Root.__subclasses__()`` returns [Middle, Leaf?]; actually Leaf is
    # only a direct subclass of Middle. To force duplicate stacking we
    # patch ``__subclasses__`` so Leaf is yielded from both Root and
    # Middle, hitting the seen-skip branch.
    real_root_subs = Root.__subclasses__
    real_middle_subs = Middle.__subclasses__

    with mock.patch.object(Root, "__subclasses__", staticmethod(lambda: real_root_subs() + [Leaf])):
        seen = list(_walk_subclasses(Root))  # type: ignore[arg-type]
    assert seen.count(Leaf) == 1  # type: ignore[comparison-overlap]
    # Silence unused-warning lint on the unused helper.
    assert real_middle_subs() == [Leaf]


# ---------------------------------------------------------------------------
# _registry._ensure_default_classes: double-checked lock when populated
# ---------------------------------------------------------------------------


def test_ensure_default_classes_second_thread_finds_populated_cache() -> None:
    """Hold the lock from one thread while another tries to populate."""
    clear_default_registry_cache()
    # Pre-fill the cache from the helper itself, then call it again -- the
    # function takes the cache-populated early-return path (the lock-held
    # branch is best-effort under contention and covered functionally by
    # the parallel call exercised below).
    _ensure_default_classes()

    barrier = threading.Barrier(2)
    results: list[int] = []

    def worker() -> None:
        barrier.wait()
        results.append(len(_ensure_default_classes()))

    threads = [threading.Thread(target=worker) for _ in range(2)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    assert results[0] == results[1] > 0


def test_ensure_default_classes_second_check_inside_lock(monkeypatch) -> None:
    """Force the double-checked path by clearing then populating between checks."""
    import ton._registry as registry_mod

    clear_default_registry_cache()
    original_lock = registry_mod._DEFAULT_CLASSES_LOCK

    class _PrimingLock:
        def __enter__(self) -> None:
            # Populate the cache between the outer ``if`` and the inner
            # ``if`` so the second check returns the populated dict.
            for cls in registry_mod.discover_generator_classes():
                registry_mod._DEFAULT_CLASSES[cls.type_name] = cls
            original_lock.acquire()

        def __exit__(self, *args: Any) -> None:
            original_lock.release()

    monkeypatch.setattr(registry_mod, "_DEFAULT_CLASSES_LOCK", _PrimingLock())
    result = registry_mod._ensure_default_classes()
    assert result is registry_mod._DEFAULT_CLASSES
    clear_default_registry_cache()


# ---------------------------------------------------------------------------
# _registry._entry_point_dist: missing dist attribute
# ---------------------------------------------------------------------------


def test_entry_point_dist_returns_none_when_attribute_missing() -> None:
    class _StubEP:
        pass  # no ``dist`` attribute at all

    assert _entry_point_dist(_StubEP()) == (None, None)


# ---------------------------------------------------------------------------
# Engine.from_file + rows_emitted property
# ---------------------------------------------------------------------------


def test_engine_from_file_loads_and_iterates(tmp_path: Path) -> None:
    path = tmp_path / "cfg.json"
    path.write_text(
        json.dumps(
            {
                "rows": 3,
                "format": "$n$",
                "types": {
                    "n": {"type": "integer", "minValue": 1, "maxValue": 9, "padWithZero": False}
                },
            }
        ),
        encoding="utf-8",
    )
    engine = Engine.from_file(str(path))
    rows = list(engine)
    assert len(rows) == 3
    assert engine.rows_emitted == 3


def test_engine_from_file_accepts_seed(tmp_path: Path) -> None:
    path = tmp_path / "cfg.json"
    path.write_text(
        json.dumps(
            {
                "rows": 3,
                "format": "$n$",
                "types": {
                    "n": {"type": "integer", "minValue": 1, "maxValue": 9, "padWithZero": False}
                },
            }
        ),
        encoding="utf-8",
    )
    engine = Engine.from_file(str(path), seed=42)
    assert engine._seed == 42
    assert list(engine) == list(Engine.from_file(str(path), seed=42))


# ---------------------------------------------------------------------------
# Engine._render_row: literal-only template (no placeholders)
# ---------------------------------------------------------------------------


def test_engine_iter_literal_only_template() -> None:
    config = {
        "rows": 2,
        "format": "literal-row",
        "types": {
            "unused": {"type": "integer", "minValue": 0, "maxValue": 1, "padWithZero": False}
        },
    }
    rows = list(api.generate(config, seed=0))
    assert rows == ["literal-row", "literal-row"]


# ---------------------------------------------------------------------------
# Engine._resolve: generator raises mid-iteration -> generate_failed log
# ---------------------------------------------------------------------------


class _RaisingGenerator(Generator):
    type_name = "raises"

    def generate(self, prepared: Any, rng: Random) -> str:
        raise RuntimeError("boom")


def test_engine_logs_generate_failed_and_wraps_in_template_error(
    caplog: pytest.LogCaptureFixture,
) -> None:
    registry: Mapping[str, Generator] = {"raises": _RaisingGenerator()}
    config = {
        "rows": 1,
        "format": "$v$",
        "types": {"v": {"type": "raises"}},
    }
    engine = Engine(config, registry=registry, rng=Random(0))
    with caplog.at_level(logging.ERROR, logger="ton"), pytest.raises(TemplateError):
        list(engine)
    events = [r for r in caplog.records if getattr(r, "event", None) == "generate_failed"]
    assert events
    assert getattr(events[0], "generator_type", "") == "_RaisingGenerator"


# ---------------------------------------------------------------------------
# CLI: --progress rejects negatives; --batch-rows positive-int helper
# ---------------------------------------------------------------------------


def test_cli_rejects_negative_progress(write_config, capsys: pytest.CaptureFixture[str]) -> None:
    config = write_config()
    with pytest.raises(SystemExit):
        cli_main([str(config), "--progress", "-1"])
    err = capsys.readouterr().err
    assert "must be >= 0" in err


def test_cli_rejects_zero_batch_rows(write_config, capsys: pytest.CaptureFixture[str]) -> None:
    config = write_config()
    with pytest.raises(SystemExit):
        cli_main([str(config), "--batch-rows", "0"])
    err = capsys.readouterr().err
    assert "must be >= 1" in err


def test_cli_accepts_explicit_batch_rows(write_config, tmp_path: Path) -> None:
    config = write_config()
    out = tmp_path / "out.txt"
    code = cli_main([str(config), "-o", str(out), "--batch-rows", "2", "--seed", "0"])
    assert code == 0
    assert len(out.read_text().strip().splitlines()) == 4


# ---------------------------------------------------------------------------
# CLI: --log-level wires configure_stderr
# ---------------------------------------------------------------------------


def test_cli_log_level_attaches_handler(write_config, capsys: pytest.CaptureFixture[str]) -> None:
    config = write_config()
    code = cli_main([str(config), "--seed", "0", "--log-level", "info"])
    assert code == 0
    err = capsys.readouterr().err
    assert "engine_constructed" in err or "INFO" in err


# ---------------------------------------------------------------------------
# CLI: --no-clobber refuses existing files; overwrite emits warning
# ---------------------------------------------------------------------------


def test_cli_no_clobber_refuses_existing_file(
    write_config, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    config = write_config()
    out = tmp_path / "out.txt"
    out.write_text("preexisting", encoding="utf-8")
    code = cli_main([str(config), "-o", str(out), "--no-clobber"])
    assert code == 1
    assert "refusing to overwrite" in capsys.readouterr().err


def test_cli_overwrite_logs_warning(
    write_config, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    config = write_config()
    out = tmp_path / "out.txt"
    out.write_text("old", encoding="utf-8")
    code = cli_main([str(config), "-o", str(out), "--log-level", "warning"])
    assert code == 0
    err = capsys.readouterr().err
    assert "output_overwrite" in err


# ---------------------------------------------------------------------------
# CLI: --resume-from skips rows
# ---------------------------------------------------------------------------


def test_cli_resume_from_skips_rows(write_config, capsys: pytest.CaptureFixture[str]) -> None:
    config = write_config({"rows": 10})
    code = cli_main([str(config), "--seed", "0", "--resume-from", "7"])
    assert code == 0
    lines = capsys.readouterr().out.strip().splitlines()
    assert len(lines) == 3


# ---------------------------------------------------------------------------
# CLI: progress handler install is idempotent
# ---------------------------------------------------------------------------


def test_progress_handler_install_idempotent(
    write_config, capsys: pytest.CaptureFixture[str]
) -> None:
    """Two CLI runs with --progress must not stack duplicate handlers."""
    from ton import cli

    config = write_config()
    cli_main([str(config), "--seed", "0", "--progress", "2"])
    cli_main([str(config), "--seed", "0", "--progress", "2"])
    progress_handlers = [
        h for h in cli._progress_logger.handlers if isinstance(h, cli._ProgressJSONHandler)
    ]
    assert len(progress_handlers) == 1
    # Drain captured output so subsequent tests do not see this run's JSON.
    capsys.readouterr()


# ---------------------------------------------------------------------------
# base.coerce_int: required key missing + bad coercion
# ---------------------------------------------------------------------------


def test_coerce_int_rejects_missing_required_key() -> None:
    with pytest.raises(ValueError, match="is required"):
        coerce_int({}, "minValue", type_name="integer")


def test_coerce_int_rejects_non_integer_value() -> None:
    with pytest.raises(ValueError, match="must be an integer"):
        coerce_int({"minValue": "not-a-number"}, "minValue", type_name="integer")


def test_generator_default_prepare_composite_delegates_to_prepare() -> None:
    """Non-composite generators must transparently route through the base hook."""
    from ton.generators.integer import IntegerGenerator

    gen = IntegerGenerator()
    spec = {"minValue": 0, "maxValue": 9, "padWithZero": False}
    via_default = gen.prepare_composite(spec, registry={})
    via_direct = gen.prepare(spec)
    assert via_default == via_direct


# ---------------------------------------------------------------------------
# SEC-004: broken entry point logs WARNING and is skipped, not fatal
# ---------------------------------------------------------------------------


def test_registry_skips_broken_entry_point(
    caplog: pytest.LogCaptureFixture,
) -> None:
    import logging as logging_mod

    from ton._logging import LogEvent as _LE
    from ton._registry import registry_with_entry_points

    bad = mock.Mock()
    bad.name = "bad_plugin"
    bad.value = "broken.module:Thing"
    bad.load.side_effect = ImportError("missing dep")

    with (
        mock.patch("ton._registry.entry_points", return_value=[bad]),
        caplog.at_level(logging_mod.WARNING, logger="ton"),
    ):
        registry = registry_with_entry_points()
    assert "bad_plugin" not in registry
    events = [
        r for r in caplog.records if getattr(r, "event", None) == _LE.ENTRY_POINT_FAILED.value
    ]
    assert events
    assert getattr(events[0], "error_type", "") == "ImportError"
    assert "missing dep" not in events[0].getMessage()


# ---------------------------------------------------------------------------
# SEC-005: refuse writes to special files (e.g. /dev/null)
# ---------------------------------------------------------------------------


def test_cli_refuses_write_to_special_file(
    write_config, capsys: pytest.CaptureFixture[str], tmp_path: Path
) -> None:
    """``/dev/null`` is a character device; the CLI must reject it."""
    config = write_config()
    output = tmp_path / "special-output"
    output.write_text("", encoding="utf-8")
    real_stat = mock.Mock(wraps=__import__("os").stat)
    device_stat = mock.Mock()
    device_stat.st_mode = 0

    def fake_stat(path: str | Path, *args: Any, **kwargs: Any) -> object:
        if Path(path) == output:
            return device_stat
        return real_stat(path, *args, **kwargs)

    with mock.patch("ton._output.os.stat", side_effect=fake_stat):
        code = cli_main([str(config), "-o", str(output)])
    assert code == 1
    assert "special file" in capsys.readouterr().err


# ---------------------------------------------------------------------------
# SEC-006: sanitize unicode / control codes from logged ep metadata
# ---------------------------------------------------------------------------


def test_sanitize_for_log_strips_non_printable() -> None:
    from ton._registry import _sanitize_for_log

    assert _sanitize_for_log("ok") == "ok"
    assert _sanitize_for_log("a\x00b\x1bc") == "a?b?c"
    # Unicode lookalikes (e.g. fullwidth letters) replaced.
    assert _sanitize_for_log("Aレ") == "A?"


def test_entry_point_load_logs_sanitized_name(
    caplog: pytest.LogCaptureFixture,
) -> None:
    import logging as logging_mod

    from ton._logging import LogEvent as _LE
    from ton._registry import registry_with_entry_points
    from ton.generators import Generator as _Gen

    class _Fake(_Gen):
        type_name = "fake_sanitized"

        def generate(self, prepared: Any, rng: Random) -> str:
            return "ok"

    ep = mock.Mock()
    ep.name = "fake_sanitized\x1b[31m"
    ep.value = "mal:Thing\x00"
    ep.load.return_value = _Fake

    with (
        mock.patch("ton._registry.entry_points", return_value=[ep]),
        caplog.at_level(logging_mod.INFO, logger="ton"),
    ):
        registry_with_entry_points()
    record = next(
        r for r in caplog.records if getattr(r, "event", None) == _LE.ENTRY_POINT_LOADED.value
    )
    assert "\x1b" not in getattr(record, "ep_name", "")
    assert "\x00" not in getattr(record, "value", "")


# ---------------------------------------------------------------------------
# REL-018: --resume-from past the end warns and produces empty output
# ---------------------------------------------------------------------------


def test_cli_resume_overshoot_warns_and_empties(
    write_config, capsys: pytest.CaptureFixture[str], tmp_path: Path
) -> None:
    config = write_config({"rows": 4})
    out = tmp_path / "out.txt"
    code = cli_main([str(config), "--seed", "0", "-o", str(out), "--resume-from", "999"])
    assert code == 0
    assert out.read_text() == ""
    err = capsys.readouterr().err
    assert "999" in err
    assert "total rows" in err


# ---------------------------------------------------------------------------
# hash._select_md4_backend: stdlib MD4 available path
# ---------------------------------------------------------------------------


def test_ntlm_uses_stdlib_md4_when_available(monkeypatch) -> None:
    """Force ``hashlib.new('md4')`` to succeed and pick the stdlib branch."""
    import hashlib as hashlib_mod

    from ton.generators import hash as hash_mod

    class _FakeHasher:
        def __init__(self, data: bytes = b"") -> None:
            self._data = data

        def digest(self) -> bytes:
            return b"\x00" * 16

    def _fake_new(name: str, data: bytes = b"") -> Any:
        if name != "md4":
            return hashlib_mod.new(name, data)
        return _FakeHasher(data)

    monkeypatch.setattr(hash_mod.hashlib, "new", _fake_new)
    backend = hash_mod._select_md4_backend()
    assert backend(b"hello") == b"\x00" * 16


# ---------------------------------------------------------------------------
# network._parse_oui: wrong-length OUI
# ---------------------------------------------------------------------------


def test_mac_oui_rejects_wrong_length() -> None:
    config = {
        "rows": 1,
        "format": "$m$",
        "types": {"m": {"type": "mac", "oui": "AABB"}},
    }
    with pytest.raises(TemplateError, match="24 bits"):
        list(api.generate(config))


# ---------------------------------------------------------------------------
# regex internals: direct dispatch coverage for branches the public
# pattern surface cannot exercise (CATEGORY / RANGE / empty class /
# unsupported op / unsupported class element / unsupported category /
# negated class with no satisfying chars).
# ---------------------------------------------------------------------------


def _regex_internals():
    """Lazy import wrapper; the module pokes private symbols intentionally."""
    from ton.generators import regex as regex_mod

    return regex_mod


def test_regex_emit_category_top_level_dispatch() -> None:
    mod = _regex_internals()
    out: list[str] = []
    mod._emit_category(mod.rx.CATEGORY_DIGIT, Random(0), out)
    assert out
    assert out[0].isdigit()


def test_regex_emit_range_top_level_dispatch() -> None:
    mod = _regex_internals()
    out: list[str] = []
    mod._emit_range((ord("a"), ord("c")), Random(0), out)
    assert out
    assert out[0] in {"a", "b", "c"}


def test_regex_emit_not_literal_top_level_dispatch() -> None:
    mod = _regex_internals()
    out: list[str] = []
    pool = mod._prepare_nodes(((mod.rx.NOT_LITERAL, ord("a")),))[0][1]
    mod._emit_not_literal(pool, Random(0), out)
    assert out
    assert out[0] != "a"


def test_regex_rejects_unsupported_construct() -> None:
    mod = _regex_internals()
    with pytest.raises(ValueError, match="unsupported construct"):
        mod._emit_into([("not-a-real-op", None)], Random(0), [])


def test_regex_rejects_unsupported_class_element() -> None:
    mod = _regex_internals()
    with pytest.raises(ValueError, match="unsupported class element"):
        mod._flatten_in([("not-a-real-op", None)])


def test_regex_empty_character_class_rejected() -> None:
    mod = _regex_internals()
    with pytest.raises(ValueError, match="empty character class"):
        mod._in_pool(())


def test_regex_negated_class_excluding_all_rejected() -> None:
    mod = _regex_internals()
    excluded = frozenset(mod._PRINTABLE_ASCII)
    with pytest.raises(ValueError, match="cannot satisfy negated class"):
        mod._excluding_pool(excluded)


def test_regex_category_space_pool_returned() -> None:
    mod = _regex_internals()
    assert mod._category_pool(mod.rx.CATEGORY_SPACE) == mod._SPACE


def test_regex_unsupported_category_rejected() -> None:
    mod = _regex_internals()
    with pytest.raises(ValueError, match="unsupported category"):
        mod._category_pool("not-a-real-category")
