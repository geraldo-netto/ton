"""Size-controlled workloads; configuration and prototypes are benchmark inputs."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path

from ton import api
from ton._proofaudit import ProofAuditWriter
from ton.generators.string import StringGenerator

DEFAULT_SIZES = {
    "paired_proof": 100,
    "nested_proof": 8,
    "transform_proof": 4,
    "wide_compile": 250,
    "deep_compile": 150,
    "worker": 4,
    "string_proof": 100,
    "email_proof": 100,
    "date_proof": 2000,
    "char_proof": 64,
    "regex_proof": 30,
    "trace_proof": 10,
    "snapshot_compile": 10000,
    "unused_compile": 10000,
    "worker_compile": 150,
    "decimal": 10000,
    "extension_compile": 10000,
    "audit": 10000,
}


def integer():
    return {"type": "integer", "minValue": -1000000, "maxValue": 1000000}


def nested(spec, size):
    for _ in range(size):
        spec = {"type": "oneOf", "choices": [spec]}
    return spec


def pool(size):
    return {"type": "string", "values": [f"value-{i}" for i in range(size)]}


def _wide(config, size, width):
    config["types"] = {f"x{i}": integer() for i in range(size)}
    config["format"] = ",".join(f"$x{i}$" for i in range(size))


def _unused(config, size, width):
    config["types"]["unused"] = pool(size)


def _mixed(config, size, width):
    rows = config["rows"]
    config.update(
        json.loads((Path(__file__).resolve().parents[1] / "examples/hwmetrics.json").read_text())
    )
    config["rows"] = rows


def _paired(config, size, width):
    config["format"] = "$x[id]$:$x$"
    config["types"]["x"] = {**pool(size), "type": "hash", "algorithm": "sha256"}


FIELD_FACTORIES = {
    "nested_proof": lambda n, w: nested(integer(), n),
    "deep_compile": lambda n, w: nested(integer(), n),
    "worker_compile": lambda n, w: nested({"type": "sequence"}, n),
    "transform_proof": lambda n, w: {
        **integer(),
        "transforms": [{"type": "identity"} for _ in range(n)],
    },
    "worker": lambda n, w: {
        "type": "sequence_of",
        "count": 3,
        "separator": ",",
        "spec": {"type": "sequence"},
    },
    "string_proof": lambda n, w: pool(n),
    "snapshot_compile": lambda n, w: pool(n),
    "email_proof": lambda n, w: {"type": "email", "domains": [f"d{i}.example" for i in range(n)]},
    "date_proof": lambda n, w: {
        "type": "date",
        "minValue": "0001-01-01",
        "maxValue": f"{n:04d}-12-31T23:59:59",
    },
    "char_proof": lambda n, w: {"type": "char", "values": ["a", "aa"], "maxChar": n},
    "regex_proof": lambda n, w: {"type": "regex", "pattern": f"(?:a?){{{n}}}a{{{n}}}"},
    "trace_proof": lambda n, w: nested({"type": "string", "values": ["x" * w]}, n),
    "decimal": lambda n, w: {
        "type": "decimal",
        "minValue": 0,
        "maxValue": f"1e-{n}",
        "decimals": 0,
    },
    "extension_compile": lambda n, w: {"type": "large"},
    "audit": lambda n, w: pool(n),
}
CONFIG_EDITORS = {
    "wide_compile": _wide,
    "unused_compile": _unused,
    "mixed": _mixed,
    "paired_proof": _paired,
}


def config_for(case, rows, size, width):
    config = {"rows": rows, "format": "$x$", "types": {"x": integer()}}
    if case in FIELD_FACTORIES:
        config["types"]["x"] = FIELD_FACTORIES[case](size, width)
    if case in CONFIG_EDITORS:
        CONFIG_EDITORS[case](config, size, width)
    return config


class LargePrototype(api.Generator):
    type_name = "large"

    def __init__(self, size):
        self.payload = list(range(size))

    def generate(self, prepared, rng):
        return "x"


class RejectingString(StringGenerator):
    def prove(self, prepared, result):
        return api.ProofResult(False, "benchmark rejection")


class DigestSink:
    """Count/hash serialized audit bytes without retaining a report."""

    def __init__(self):
        self.digest = hashlib.sha256()
        self.characters = 0

    def write(self, value):
        self.digest.update(value.encode("utf-8"))
        self.characters += len(value)
        return len(value)


def options_for(case, size):
    if case == "extension_compile":
        return api.EngineOptions(registry={"large": LargePrototype(size)}, seed=42)
    if case == "audit":
        return api.EngineOptions(
            registry={"string": RejectingString()}, seed=42, proof_mode="audit"
        )
    return api.EngineOptions(seed=42, proof_mode="all" if "proof" in case else "off")


def build_engine(case, config, options, size, sink):
    if case in {"worker", "worker_compile", "extension_compile"}:
        workers = size if case == "worker" else 4
        engine = api.fork_engine(
            config,
            parent_seed=42,
            worker_id=min(2, workers - 1),
            workers=workers,
            rows=config["rows"],
            options=options,
        )
    else:
        engine = api.Engine.from_options(config, options)
    if case == "audit":
        engine.set_proof_failure_sink(ProofAuditWriter(sink))
    return engine
