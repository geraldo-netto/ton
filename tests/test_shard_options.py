"""The shard writer shares configuration and extension options with other entry points."""

import json
import multiprocessing
from concurrent.futures import ProcessPoolExecutor
from dataclasses import replace

import pytest

from ton import api
from ton.cli import main


@pytest.mark.parametrize("encoding", [None, "utf-16", "latin-1"])
@pytest.mark.parametrize("override", [None, "utf-8"])
def test_shard_encoding_matches_config_and_explicit_override(tmp_path, encoding, override):
    """ARCH-035: default shard bytes follow the same codec policy as the CLI."""
    config = {"rows": 2, "format": "$x$", "types": {"x": {"type": "string", "values": ["é"]}}}
    if encoding is not None:
        config["encoding"] = encoding
    config_path, cli_path, shard_path = (
        tmp_path / name for name in ("config.json", "cli.txt", "shard.txt")
    )
    config_path.write_text(json.dumps(config), encoding="utf-8")
    assert main([str(config_path), "--output", str(cli_path)]) == 0
    kwargs = {} if override is None else {"encoding": override}
    assert (
        api.write_shard(config, str(shard_path), parent_seed=42, worker_id=0, workers=1, **kwargs)
        == 2
    )
    expected = "é\né\n".encode(override or encoding or "utf-8")
    assert shard_path.read_bytes() == expected
    if override is None:
        assert shard_path.read_bytes() == cli_path.read_bytes()


class PluginSource(api.Generator):
    type_name = "source"
    config_keys = frozenset({"value"})

    def prepare(self, spec, context=None):
        return spec["value"]

    def generate(self, prepared, rng):
        return prepared

    def prove(self, prepared, result):
        return api.ProofResult(False, "audit this source")


class PluginSuffix:
    type_name = "suffix"
    config_keys = frozenset()
    capabilities = api.TransformCapabilities()
    requires_source = True

    def nested_specs(self, spec):
        return ()

    def prepare(self, spec, context):
        return None

    def apply(self, prepared, value, rng):
        return api.TransformResult(value.value + "!")

    def prove(self, prepared, before, after):
        return api.TransformProof(after.value == before.value + "!")


class PluginValidator:
    type_name = "suffix"

    def validate(self, value):
        return value == "value!"


def plugin_job(sink):
    config = {
        "rows": 2,
        "format": "$x$",
        "types": {
            "x": {
                "type": "example.source",
                "value": "value",
                "transforms": [{"type": "example.suffix"}],
                "validators": ["example.suffix"],
            }
        },
    }
    options = api.EngineOptions(
        registry={"example.source": PluginSource()},
        transforms={"example.suffix": PluginSuffix()},
        validators={"example.suffix": PluginValidator()},
        proof_mode="audit",
        redact_proof_failures=True,
        proof_failure_sink=sink,
        seed=123,
        milestone_rows=1,
    )
    return config, options


@pytest.mark.parametrize("spawned", [False, True])
def test_shard_writer_forwards_complete_engine_options(tmp_path, spawned):
    """ARCH-034: plugin, proof and redaction options reach ordinary and spawned writers."""
    context = multiprocessing.get_context("spawn")
    with context.Manager() as manager:
        failures = manager.list()
        config, options = plugin_job(failures.append)
        path = tmp_path / "plugin.txt"
        kwargs = {"parent_seed": 42, "worker_id": 0, "workers": 1, "options": options}
        if spawned:
            with ProcessPoolExecutor(max_workers=1, mp_context=context) as pool:
                written = pool.submit(api.write_shard, config, str(path), **kwargs).result(
                    timeout=30
                )
        else:
            written = api.write_shard(config, str(path), **kwargs)
        assert written == 2
        assert path.read_text() == "value!\nvalue!\n"
        assert len(failures) == 2
        assert all(failure.is_redacted and failure.value == "<redacted>" for failure in failures)
        assert all(failure.seed == api.derive_seed(42, 0) for failure in failures)
        assert options.seed == 123


def test_shard_writer_proof_options_preserve_existing_output_on_failure(tmp_path):
    """ARCH-034: strict proof failures abort publication through the shared writer."""
    config, options = plugin_job(None)
    options = replace(options, proof_mode="all")
    path = tmp_path / "old.txt"
    path.write_text("previous\n")
    with pytest.raises(api.ProofError):
        api.write_shard(config, str(path), parent_seed=42, worker_id=0, workers=1, options=options)
    assert path.read_text() == "previous\n"
