"""The shard writer shares configuration and extension options with other entry points."""

import json

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
