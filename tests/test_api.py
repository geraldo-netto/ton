"""Tests for the public ton.api facade."""

from __future__ import annotations

import errno
import logging
import os
import stat
from collections.abc import Mapping
from contextlib import nullcontext
from pathlib import Path
from random import Random
from types import MappingProxyType
from typing import Any
from unittest import mock

import pytest

from ton import api
from ton._contracts import Generator
from ton._proof import ProofResult
from ton._transforms import TransformResult

EXPECTED_PUBLIC_API = {
    "CatalogSnapshot",
    "ConfigError",
    "Engine",
    "EngineOptions",
    "EntryPointSelector",
    "ExtensionCatalog",
    "Generator",
    "GeneratorExecutionError",
    "LogEvent",
    "OutputEncodingError",
    "OutputPublishedError",
    "PairedGenerator",
    "PartialOutputCommitError",
    "PipelineStageError",
    "PreparationContext",
    "ProofError",
    "ProofEvaluationError",
    "ProofFailure",
    "ProofFailureSink",
    "ProofResult",
    "ProvenanceRecord",
    "RegistryError",
    "StagedOutput",
    "TemplateError",
    "Transform",
    "TransformCapabilities",
    "TransformExecutionError",
    "TransformProof",
    "TransformResult",
    "UndeclaredVariableError",
    "ValidationError",
    "Validator",
    "ValidatorExecutionError",
    "build_extension_catalog",
    "cleanup_staged_outputs",
    "chunk_rows",
    "configure_stderr",
    "derive_rng",
    "derive_seed",
    "fork_engine",
    "write_shard",
    "generate",
    "generate_from_file",
    "load_config",
    "inspect_staged_outputs",
    "logger",
    "normalize_reference",
    "open_output_path",
    "output_encoding",
    "validate_config",
}


def test_generate_yields_iterator(basic_config: dict) -> None:
    rows = list(api.generate(basic_config, seed=0))
    assert len(rows) == 4
    assert all(row.isdigit() for row in rows)


def test_generate_and_validate_accept_read_only_mappings() -> None:
    transform = MappingProxyType({"type": "identity"})
    spec = MappingProxyType({"type": "string", "values": ["ok"], "transforms": [transform]})
    config = MappingProxyType(
        {
            "rows": 1,
            "format": "$value$",
            "types": MappingProxyType({"value": spec}),
        }
    )

    api.validate_config(config)
    assert list(api.generate(config)) == ["ok"]


def test_public_api_surface_matches_supported_checklist() -> None:
    assert set(api.__all__) == EXPECTED_PUBLIC_API


def test_concurrency_helpers_are_available_from_public_facade() -> None:
    assert api.chunk_rows(10, 3, 0) == 4
    first = api.derive_rng(1, 0).random()
    second = api.derive_rng(1, 0).random()
    assert first == second
    assert callable(api.fork_engine)


def test_engine_options_is_public_parameter_object() -> None:
    options = api.EngineOptions(seed=42, proof_mode="audit")

    assert options.seed == 42
    assert options.proof_mode == "audit"


def test_generate_is_seed_deterministic(basic_config: dict) -> None:
    first = list(api.generate(basic_config, seed=42))
    second = list(api.generate(basic_config, seed=42))
    assert first == second


def test_generate_streams_audit_failures_through_public_sink() -> None:
    class RejectingGenerator(Generator):
        type_name = "rejecting"

        def generate(self, prepared: Any, rng: Random) -> str:
            return "invalid"

        def prove(self, prepared: Any, result: TransformResult) -> ProofResult:
            return ProofResult(ok=False, reason="rejected")

    failures = []
    config = {
        "rows": 1,
        "format": "$value$",
        "types": {"value": {"type": "rejecting"}},
    }

    rows = list(
        api.generate(
            config,
            registry={"rejecting": RejectingGenerator()},
            proof_mode="audit",
            proof_failure_sink=failures.append,
        )
    )

    assert rows == ["invalid"]
    assert len(failures) == 1
    assert failures[0].reason == "rejected"


def test_generate_from_file_round_trip(write_config) -> None:
    path = write_config()
    rows = list(api.generate_from_file(str(path), seed=7))
    assert len(rows) == 4


def test_custom_registry_can_override_or_add_types() -> None:
    class TagGenerator(Generator):
        type_name = "tag"

        def generate(self, prepared: Any, rng: Random) -> str:
            return prepared["tag"]

    registry = api.build_extension_catalog().generators()
    registry["tag"] = TagGenerator()
    config = {
        "rows": 3,
        "format": "[$t$]",
        "types": {"t": {"type": "tag", "tag": "hello"}},
    }
    rows = list(api.generate(config, registry=registry, seed=0))
    assert rows == ["[hello]", "[hello]", "[hello]"]


def test_load_config_validates(tmp_path: Path) -> None:
    bad = tmp_path / "bad.json"
    bad.write_text("{}", encoding="utf-8")
    from ton.api import ConfigError

    with pytest.raises(ConfigError):
        api.load_config(str(bad))


def test_public_output_sink_replaces_atomically_and_preserves_mode(
    tmp_path: Path, caplog: pytest.LogCaptureFixture
) -> None:
    output = tmp_path / "rows.txt"
    output.write_text("old\n", encoding="utf-8")
    os.chmod(output, 0o640)
    expected_mode = stat.S_IMODE(output.stat().st_mode)

    with (
        caplog.at_level(logging.WARNING, logger="ton"),
        api.open_output_path(str(output)) as stream,
    ):
        stream.write("new\n")
        assert not any(
            getattr(record, "event", "") == "output_overwrite" for record in caplog.records
        )

    assert output.read_text(encoding="utf-8") == "new\n"
    assert stat.S_IMODE(output.stat().st_mode) == expected_mode
    overwrite = [
        record for record in caplog.records if getattr(record, "event", "") == "output_overwrite"
    ]
    assert len(overwrite) == 1
    assert overwrite[0].committed is True


def test_new_output_mode_does_not_mutate_process_umask(monkeypatch, tmp_path: Path) -> None:
    from ton import _output

    mutate_umask = mock.Mock(side_effect=AssertionError("process umask mutated"))
    monkeypatch.setattr(_output.os, "umask", mutate_umask)

    mode = _output.target_mode(str(tmp_path / "new-output.txt"))

    assert mode & ~0o666 == 0
    mutate_umask.assert_not_called()
    assert list(tmp_path.glob(".ton-mode.*")) == []


def test_public_output_sink_rolls_back_failed_write(tmp_path: Path) -> None:
    output = tmp_path / "rows.txt"
    output.write_text("old\n", encoding="utf-8")

    def write_then_fail() -> None:
        with api.open_output_path(str(output)) as stream:
            stream.write("partial\n")
            raise RuntimeError("failed")

    with pytest.raises(RuntimeError, match="failed"):
        write_then_fail()

    assert output.read_text(encoding="utf-8") == "old\n"
    assert list(tmp_path.glob(".*.tmp")) == []


@pytest.mark.parametrize("basename", ["x" * 240, "é" * 120])
@pytest.mark.parametrize("fail", [False, True])
def test_long_output_names_preserve_publication_and_recovery(
    tmp_path: Path, basename: str, fail: bool
) -> None:
    output = tmp_path / basename
    try:
        output.write_text("old\n", encoding="utf-8")
    except OSError as exc:
        if exc.errno != errno.ENAMETOOLONG and getattr(exc, "winerror", None) != 206:
            raise
        pytest.skip("destination itself is not supported by this filesystem")

    outcome = pytest.raises(RuntimeError, match="interrupted") if fail else nullcontext()
    with outcome, api.open_output_path(str(output)) as stream:
        stream.write("new\n")
        stages = api.inspect_staged_outputs(str(output))
        assert len(stages) == 1
        assert stages[0].managed and stages[0].owner_running
        assert api.inspect_staged_outputs(str(tmp_path / "other-output")) == ()
        assert api.cleanup_staged_outputs(str(output), stale_after_seconds=0) == ()
        if fail:
            raise RuntimeError("interrupted")

    assert output.read_text(encoding="utf-8") == ("old\n" if fail else "new\n")
    assert api.inspect_staged_outputs(str(output)) == ()
    assert list(tmp_path.glob(".*.tmp")) == []


def test_hashed_stage_cleanup_is_scoped_to_its_destination(monkeypatch, tmp_path: Path) -> None:
    from ton import _output

    output = tmp_path / ("x" * 240)
    other_output = tmp_path / ("x" * 239 + "y")
    with mock.patch("ton._output.os.getpid", return_value=999999):
        stage = tmp_path / (_output._stage_prefix(output.name) + "random.tmp")
        other_stage = tmp_path / (_output._stage_prefix(other_output.name) + "random.tmp")
    stage.write_text("abandoned\n", encoding="utf-8")
    other_stage.write_text("other destination\n", encoding="utf-8")
    monkeypatch.setattr(_output, "_process_is_running", lambda pid: False)

    assert api.cleanup_staged_outputs(str(output), stale_after_seconds=0) == (str(stage),)
    assert not stage.exists()
    assert other_stage.read_text(encoding="utf-8") == "other destination\n"


def test_output_stage_inspection_preserves_live_writer(tmp_path: Path) -> None:
    output = tmp_path / "rows.txt"

    with api.open_output_path(str(output)) as stream:
        stream.write("partial\n")
        stages = api.inspect_staged_outputs(str(output))

        assert len(stages) == 1
        assert stages[0].managed
        assert stages[0].owner_pid == os.getpid()
        assert stages[0].owner_running is True
        assert api.cleanup_staged_outputs(str(output), stale_after_seconds=0) == ()

    assert api.inspect_staged_outputs(str(output)) == ()


def _stage_name(basename: str, suffix: str) -> str:
    """Build a stage filename for ``basename`` the way ton._output does."""
    from ton import _output

    return f"{_output._stage_file_prefix(basename)}{suffix}"


def test_output_stage_cleanup_removes_only_confirmed_abandoned_writer(
    monkeypatch, tmp_path: Path
) -> None:
    from ton import _output

    output = tmp_path / "rows.txt"
    managed = tmp_path / _stage_name("rows.txt", "ton-999999-1-token.tmp")
    legacy = tmp_path / _stage_name("rows.txt", "legacy.tmp")
    managed.write_text("partial\n", encoding="utf-8")
    legacy.write_text("unknown\n", encoding="utf-8")
    monkeypatch.setattr(_output, "_process_is_running", lambda pid: False)

    stages = api.inspect_staged_outputs(str(output))
    removed = api.cleanup_staged_outputs(str(output), stale_after_seconds=0)

    assert [(stage.owner_pid, stage.managed) for stage in stages] == [
        (None, False),
        (999999, True),
    ]
    assert removed == (str(managed),)
    assert not managed.exists()
    assert legacy.exists()


def test_output_stage_inspection_ignores_non_regular_candidates(tmp_path: Path) -> None:
    output = tmp_path / "rows.txt"
    (tmp_path / _stage_name("rows.txt", "legacy.tmp")).mkdir()

    assert api.inspect_staged_outputs(str(output)) == ()


def test_output_stage_inspection_tolerates_publish_race(monkeypatch, tmp_path: Path) -> None:
    from ton import _output

    entry = mock.Mock()
    entry.name = _stage_name("rows.txt", "ton-999999-1-token.tmp")
    entry.path = str(tmp_path / entry.name)
    scan = mock.MagicMock()
    scan.__enter__.return_value = [entry]
    monkeypatch.setattr(_output.os, "scandir", mock.Mock(return_value=scan))
    stat_file = mock.Mock(side_effect=FileNotFoundError)
    monkeypatch.setattr(_output.os, "stat", stat_file)

    assert api.inspect_staged_outputs(str(tmp_path / "rows.txt")) == ()
    stat_file.assert_called_once_with(entry.path, follow_symlinks=False)
    entry.stat.assert_not_called()


@pytest.mark.parametrize(
    "suffix",
    [
        "ton-not-a-pid-1-token.tmp",
        "ton-1-not-a-time-token.tmp",
        "ton-0-1-token.tmp",
        "ton-1-0-token.tmp",
    ],
)
def test_output_stage_inspection_treats_bad_metadata_as_unowned(
    suffix: str, tmp_path: Path
) -> None:
    name = _stage_name("rows.txt", suffix)
    output = tmp_path / "rows.txt"
    (tmp_path / name).write_text("partial\n", encoding="utf-8")

    stage = api.inspect_staged_outputs(str(output))[0]

    assert not stage.managed
    assert stage.owner_pid is None


def test_output_stage_cleanup_waits_for_stale_age(monkeypatch, tmp_path: Path) -> None:
    from ton import _output

    output = tmp_path / "rows.txt"
    created_at_ns = _output.time.time_ns()
    stage = tmp_path / _stage_name("rows.txt", f"ton-999999-{created_at_ns}-token.tmp")
    stage.write_text("partial\n", encoding="utf-8")
    monkeypatch.setattr(_output, "_process_is_running", lambda pid: False)

    assert api.cleanup_staged_outputs(str(output), stale_after_seconds=60) == ()
    assert stage.exists()


def test_output_stage_cleanup_rechecks_owner_liveness(monkeypatch, tmp_path: Path) -> None:
    from ton import _output

    output = tmp_path / "rows.txt"
    stage = tmp_path / _stage_name("rows.txt", "ton-999999-1-token.tmp")
    stage.write_text("partial\n", encoding="utf-8")
    running = mock.Mock(side_effect=[False, True])
    monkeypatch.setattr(_output, "_process_is_running", running)

    assert api.cleanup_staged_outputs(str(output), stale_after_seconds=0) == ()
    assert stage.exists()


def test_output_stage_cleanup_tolerates_concurrent_disappearance(
    monkeypatch, tmp_path: Path
) -> None:
    from ton import _output

    output = tmp_path / "rows.txt"
    stage = tmp_path / _stage_name("rows.txt", "ton-999999-1-token.tmp")
    stage.write_text("partial\n", encoding="utf-8")
    monkeypatch.setattr(_output, "_process_is_running", lambda pid: False)
    candidate = _output._staged_candidates(str(output))[0]
    stage.unlink()

    assert not _output._remove_abandoned_stage(candidate)


def test_output_stage_cleanup_preserves_replaced_candidate(monkeypatch, tmp_path: Path) -> None:
    from ton import _output

    output = tmp_path / "rows.txt"
    stage = tmp_path / _stage_name("rows.txt", "ton-999999-1-token.tmp")
    replacement = tmp_path / "replacement.tmp"
    stage.write_text("partial\n", encoding="utf-8")
    replacement.write_text("live\n", encoding="utf-8")
    monkeypatch.setattr(_output, "_process_is_running", lambda pid: False)
    candidate = _output._staged_candidates(str(output))[0]
    os.replace(replacement, stage)

    assert not _output._remove_abandoned_stage(candidate)
    assert stage.read_text(encoding="utf-8") == "live\n"


def test_output_stage_cleanup_tolerates_unlink_race(monkeypatch, tmp_path: Path) -> None:
    from ton import _output

    output = tmp_path / "rows.txt"
    stage = tmp_path / _stage_name("rows.txt", "ton-999999-1-token.tmp")
    stage.write_text("partial\n", encoding="utf-8")
    monkeypatch.setattr(_output, "_process_is_running", lambda pid: False)
    candidate = _output._staged_candidates(str(output))[0]
    monkeypatch.setattr(_output.os, "unlink", mock.Mock(side_effect=FileNotFoundError))

    assert not _output._remove_abandoned_stage(candidate)


@pytest.mark.parametrize(
    ("side_effect", "expected"),
    [
        (None, True),
        (ProcessLookupError(), False),
        (PermissionError(), True),
        (OverflowError(), False),
        (ValueError(), False),
        (OSError(), None),
    ],
)
def test_output_stage_process_liveness_mapping(
    monkeypatch, side_effect: BaseException | None, expected: bool | None
) -> None:
    from ton import _output

    kill = mock.Mock(side_effect=side_effect)
    monkeypatch.setattr(_output.os, "name", "posix")
    monkeypatch.setattr(_output.os, "kill", kill)

    assert _output._process_is_running(os.getpid() + 10_000) is expected


def test_output_stage_process_liveness_uses_windows_probe(monkeypatch) -> None:
    from ton import _output

    probe = mock.Mock(return_value=None)
    monkeypatch.setattr(_output.os, "name", "nt")
    monkeypatch.setattr(_output, "_windows_process_is_running", probe)
    pid = os.getpid() + 10_000

    assert _output._process_is_running(pid) is None
    probe.assert_called_once_with(pid)


@pytest.mark.parametrize("stale_after", [-1, True, float("inf"), "one day"])
def test_output_stage_cleanup_rejects_invalid_age(stale_after: object, tmp_path: Path) -> None:
    with pytest.raises(ValueError, match="finite non-negative"):
        api.cleanup_staged_outputs(str(tmp_path / "rows.txt"), stale_after_seconds=stale_after)  # type: ignore[arg-type]


def test_public_output_sink_no_clobber_publish_is_atomic(tmp_path: Path) -> None:
    output = tmp_path / "rows.txt"

    def race_publish() -> None:
        with api.open_output_path(str(output), no_clobber=True) as stream:
            stream.write("generated\n")
            output.write_text("racing writer\n", encoding="utf-8")

    with pytest.raises(FileExistsError):
        race_publish()

    assert output.read_text(encoding="utf-8") == "racing writer\n"
    assert list(tmp_path.glob(".*.tmp")) == []


def test_public_output_sink_no_clobber_publishes_new_file(tmp_path: Path) -> None:
    output = tmp_path / "rows.txt"

    with api.open_output_path(str(output), no_clobber=True) as stream:
        stream.write("generated\n")

    assert output.read_text(encoding="utf-8") == "generated\n"


def test_atomic_output_fsyncs_parent_directory(tmp_path: Path) -> None:
    output = tmp_path / "rows.txt"

    with (
        mock.patch("ton._output._fsync_directory") as fsync_directory,
        api.open_output_path(str(output)) as stream,
    ):
        stream.write("row\n")

    fsync_directory.assert_called_once_with(str(tmp_path))


def test_directory_fsync_is_noop_on_windows(monkeypatch: pytest.MonkeyPatch) -> None:
    from ton import _output

    monkeypatch.setattr(_output.os, "name", "nt")
    with mock.patch.object(_output.os, "open") as open_directory:
        _output._fsync_directory(".")

    open_directory.assert_not_called()


def test_directory_fsync_uses_posix_file_operations(monkeypatch: pytest.MonkeyPatch) -> None:
    from ton import _output

    monkeypatch.setattr(_output.os, "name", "posix")
    with (
        mock.patch.object(_output.os, "open", return_value=42) as open_directory,
        mock.patch.object(_output.os, "fsync") as fsync_directory,
        mock.patch.object(_output.os, "close") as close_directory,
    ):
        _output._fsync_directory(".")

    flags = os.O_RDONLY | getattr(os, "O_DIRECTORY", 0)
    open_directory.assert_called_once_with(".", flags)
    fsync_directory.assert_called_once_with(42)
    close_directory.assert_called_once_with(42)


def test_public_output_sink_matches_cli_symlink_policy(tmp_path: Path) -> None:
    target = tmp_path / "target.txt"
    target.write_text("old\n", encoding="utf-8")
    link = tmp_path / "rows.txt"
    link.symlink_to(target)

    with pytest.raises(OSError, match="symbolic-link"), api.open_output_path(str(link)):
        pass

    assert link.is_symlink()
    assert target.read_text(encoding="utf-8") == "old\n"


@pytest.mark.skipif(os.name == "nt", reason="requires POSIX FIFO and symlink support")
def test_public_output_sink_rejects_fifo_symlink_swap(monkeypatch, tmp_path: Path) -> None:
    from ton import _output

    fifo = tmp_path / "rows.fifo"
    victim = tmp_path / "victim.txt"
    os.mkfifo(fifo)
    victim.write_text("keep\n", encoding="utf-8")
    validate = _output.validate_output_target

    def validate_then_swap(path: str, *, no_clobber: bool = False) -> bool:
        is_fifo = validate(path, no_clobber=no_clobber)
        fifo.unlink()
        fifo.symlink_to(victim)
        return is_fifo

    monkeypatch.setattr(_output, "validate_output_target", validate_then_swap)

    with pytest.raises(OSError), api.open_output_path(str(fifo)):
        pass

    assert fifo.is_symlink()
    assert victim.read_text(encoding="utf-8") == "keep\n"


def test_output_encoding_error_carries_codec_and_field_context() -> None:
    error = api.OutputEncodingError("ascii", "ordinal not in range", field_name="city")

    assert error.encoding == "ascii"
    assert error.field_name == "city"
    assert "field 'city'" in str(error)


@pytest.mark.parametrize(
    "config",
    [
        {},
        {"rows": True, "format": "$x$", "types": {"x": {"type": "string", "values": ["x"]}}},
        {"rows": 1, "format": 123, "types": {"x": {"type": "string", "values": ["x"]}}},
    ],
)
def test_in_memory_generation_uses_structural_validation(config: dict) -> None:
    with pytest.raises(api.ConfigError):
        list(api.generate(config))


@pytest.mark.parametrize("writer", ["open_output_path", "write_shard"])
def test_encoding_failures_normalize_at_the_output_boundary(tmp_path: Path, writer: str) -> None:
    """Raw UnicodeEncodeError must not escape the public output API (REL-027)."""
    target = tmp_path / "rows.txt"
    config = {"rows": 2, "format": "$x$", "types": {"x": {"type": "string", "values": ["é"]}}}

    with pytest.raises(api.OutputEncodingError) as excinfo:
        if writer == "open_output_path":
            with api.open_output_path(str(target), encoding="ascii") as stream:
                stream.write("é")
        else:
            api.write_shard(
                config, str(target), parent_seed=1, worker_id=0, workers=1, encoding="ascii"
            )

    assert excinfo.value.encoding == "ascii"
    assert not target.exists()


def test_writelines_is_normalized_like_write(tmp_path: Path) -> None:
    """writelines must not bypass the boundary via attribute forwarding (REL-027)."""
    target = tmp_path / "rows.txt"

    with (
        pytest.raises(api.OutputEncodingError) as excinfo,
        api.open_output_path(str(target), encoding="ascii") as stream,
    ):
        stream.writelines(["ok\n", "é\n"])

    assert excinfo.value.encoding == "ascii"
    assert not target.exists()


def test_output_stream_still_exposes_the_underlying_attributes(tmp_path: Path) -> None:
    """The proxy forwards everything it does not normalize."""
    target = tmp_path / "rows.txt"

    with api.open_output_path(str(target), encoding="utf-8") as stream:
        assert stream.encoding == "utf-8"
        stream.writelines(["a\n", "b\n"])

    assert target.read_text(encoding="utf-8") == "a\nb\n"


def test_a_plugin_can_be_written_against_the_facade_alone() -> None:
    """Every contract type a plugin must name is exported by ton.api (PLUG-007)."""

    class TagTransform:
        """A transform implemented without importing any private module."""

        type_name = "tag"
        capabilities = api.TransformCapabilities(accepts_paired=True, preserves_pairing=True)
        config_keys = frozenset({"suffix"})
        requires_source = True

        def nested_specs(self, spec: Mapping[str, Any]) -> tuple[Any, ...]:
            del spec
            return ()

        def prepare(self, spec: Mapping[str, Any], context: api.PreparationContext) -> str:
            del context
            return str(spec.get("suffix", "!"))

        def apply(
            self, prepared: str, value: api.TransformResult, rng: Random
        ) -> api.TransformResult:
            del rng
            return api.TransformResult(value.value + prepared, value.id_value)

        def prove(
            self, prepared: str, before: api.TransformResult, after: api.TransformResult
        ) -> api.TransformProof:
            if after.value == before.value + prepared:
                return api.TransformProof(ok=True)
            return api.TransformProof(ok=False, reason="suffix not applied")

    class ShoutGenerator(api.Generator):
        type_name = "shout"
        config_keys = frozenset({"type", "word"})

        def prepare(self, spec: Mapping[str, Any], context: Any = None) -> str:
            del context
            return str(spec["word"]).upper()

        def generate(self, prepared: str, rng: Random) -> str:
            del rng
            return prepared

        def prove(self, prepared: str, result: api.TransformResult) -> api.ProofResult:
            return api.ProofResult(ok=result.value.startswith(prepared), reason="wrong word")

    catalog = api.build_extension_catalog()
    catalog.register_data_type("acme", "shout", ShoutGenerator())
    catalog.register_transform("acme", "tag", TagTransform())
    config = {
        "rows": 2,
        "format": "$x$",
        "types": {"x": {"type": "acme.shout", "word": "hi", "transforms": [{"type": "acme.tag"}]}},
    }

    rows = list(
        api.generate(
            config,
            seed=1,
            registry=catalog.generators(),
            transforms=catalog.transforms(),
            proof_mode="all",
        )
    )

    assert rows == ["HI!", "HI!"]


def test_public_facade_exports_the_plugin_contract_types() -> None:
    for name in (
        "PreparationContext",
        "ProofResult",
        "TransformCapabilities",
        "TransformProof",
        "TransformResult",
    ):
        assert name in api.__all__
        assert hasattr(api, name)


@pytest.mark.parametrize("no_clobber", [False, True])
@pytest.mark.parametrize("direct", [False, True])
def test_output_publication_retains_opening_directory(tmp_path, monkeypatch, no_clobber, direct):
    """ROB-014: publication keeps the path resolved when the context was entered."""
    from ton._output import atomic_output

    first, second = tmp_path / "first", tmp_path / "second"
    first.mkdir()
    second.mkdir()
    other = second / "result.txt"
    other.write_text("unrelated")
    monkeypatch.chdir(first)
    opener = atomic_output if direct else api.open_output_path
    with opener("result.txt", no_clobber=no_clobber) as stream:
        stream.write("generated")
        monkeypatch.chdir(second)
    assert (first / "result.txt").read_text() == "generated"
    assert other.read_text() == "unrelated"
    assert sorted(path.name for path in first.iterdir()) == ["result.txt"]


def test_output_no_clobber_race_checks_original_directory(tmp_path, monkeypatch):
    """ROB-014: a competing original target survives a cwd change and rollback."""
    first, second = tmp_path / "first", tmp_path / "second"
    first.mkdir()
    second.mkdir()
    monkeypatch.chdir(first)
    with (
        pytest.raises(FileExistsError),
        api.open_output_path("result.txt", no_clobber=True) as stream,
    ):
        stream.write("generated")
        (first / "result.txt").write_text("competitor")
        monkeypatch.chdir(second)
    assert (first / "result.txt").read_text() == "competitor"
    assert list(second.iterdir()) == []
    assert sorted(path.name for path in first.iterdir()) == ["result.txt"]


def test_output_body_failure_cleans_original_directory(tmp_path, monkeypatch):
    """ROB-014: failed generation removes the stage even after cwd changes."""
    first, second = tmp_path / "first", tmp_path / "second"
    first.mkdir()
    second.mkdir()
    monkeypatch.chdir(first)
    with (
        pytest.raises(RuntimeError, match="interrupted"),
        api.open_output_path("result.txt") as stream,
    ):
        stream.write("partial")
        monkeypatch.chdir(second)
        raise RuntimeError("interrupted")
    assert list(first.iterdir()) == list(second.iterdir()) == []
