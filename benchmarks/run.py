"""Reproducible benchmarks; each sample runs in a fresh Python process."""

from __future__ import annotations

import argparse
import hashlib
import importlib
import json
import os
import platform
import statistics
import subprocess
import sys
import time
import tracemalloc
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
CASES = (
    "import_json",
    "import_api",
    "integer",
    "mixed",
    "paired_proof",
    "nested_proof",
    "transform_proof",
    "wide_compile",
    "deep_compile",
    "worker",
)


def config_for(case: str, rows: int) -> dict:
    integer = {"type": "integer", "minValue": -1000000, "maxValue": 1000000}
    config = {"rows": rows, "format": "$x$", "types": {"x": integer}}
    if case == "mixed":
        config = json.loads((ROOT / "examples" / "hwmetrics.json").read_text())
        config["rows"] = rows
    elif case == "paired_proof":
        config["format"] = "$x[id]$:$x$"
        config["types"]["x"] = {
            "type": "hash",
            "algorithm": "sha256",
            "values": [f"value-{i}" for i in range(100)],
        }
    elif case in {"nested_proof", "deep_compile"}:
        for _ in range(8 if case == "nested_proof" else 150):
            integer = {"type": "oneOf", "choices": [integer]}
        config["types"]["x"] = integer
    elif case == "transform_proof":
        integer["transforms"] = [{"type": "identity"} for _ in range(4)]
    elif case == "wide_compile":
        config["types"] = {f"x{i}": dict(integer) for i in range(250)}
        config["format"] = ",".join(f"$x{i}$" for i in range(250))
    elif case == "worker":
        config["types"]["x"] = {
            "type": "sequence_of",
            "count": 3,
            "separator": ",",
            "spec": {"type": "sequence"},
        }
    return config


def measure(case: str, rows: int, memory: bool) -> dict:
    sys.path.insert(0, str(ROOT))
    if memory:
        tracemalloc.start()
    if case.startswith("import_"):
        started = time.perf_counter()
        importlib.import_module("ton._json" if case == "import_json" else "ton.api")
        result = {"setup_seconds": time.perf_counter() - started, "run_seconds": 0.0}
    else:
        result = measure_engine(case, rows)
    if memory:
        result["peak_traced_bytes"] = tracemalloc.get_traced_memory()[1]
        tracemalloc.stop()
    return result


def measure_engine(case: str, rows: int) -> dict:
    from ton import api

    config = config_for(case, rows)
    started = time.perf_counter()
    if case == "worker":
        engine = api.fork_engine(config, parent_seed=42, worker_id=2, workers=4, rows=rows)
    else:
        engine = api.Engine.from_options(
            config, api.EngineOptions(seed=42, proof_mode="all" if "proof" in case else "off")
        )
    setup = time.perf_counter() - started
    count = characters = 0
    digest = hashlib.sha256()
    started = time.perf_counter()
    if not case.endswith("compile"):
        for row in engine:
            count += 1
            characters += len(row)
            digest.update(row.encode("utf-8"))
            digest.update(b"\n")
    return {
        "setup_seconds": setup,
        "run_seconds": time.perf_counter() - started,
        "rows": count,
        "characters": characters,
        "sha256": digest.hexdigest(),
    }


def sample(case: str, rows: int, *, memory: bool = False) -> dict:
    command = [sys.executable, str(Path(__file__).resolve()), "--worker", case, "--rows", str(rows)]
    if memory:
        command.append("--trace-memory")
    completed = subprocess.run(command, check=True, capture_output=True, text=True, cwd=ROOT)
    return json.loads(completed.stdout)


def benchmark(case: str, args: argparse.Namespace) -> dict:
    sample(case, args.rows)  # Discard one warmup; timings still use fresh interpreters.
    samples = [sample(case, args.rows) for _ in range(args.repeats)]
    fingerprints = {(s.get("rows"), s.get("characters"), s.get("sha256")) for s in samples}
    if len(fingerprints) != 1:
        raise RuntimeError(f"non-deterministic benchmark output: {case}")
    timings = {}
    for key in ("setup_seconds", "run_seconds"):
        values = [s[key] for s in samples]
        timings[key] = {"median": statistics.median(values), "min": min(values), "max": max(values)}
    memory = sample(case, min(args.rows, args.memory_rows), memory=True)
    return {"samples": samples, "timings": timings, "memory_sample": memory}


def positive_int(value: str) -> int:
    result = int(value)
    if result < 1:
        raise argparse.ArgumentTypeError("must be positive")
    return result


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--rows", type=positive_int, default=20000)
    parser.add_argument("--repeats", type=positive_int, default=5)
    parser.add_argument("--memory-rows", type=positive_int, default=1000)
    parser.add_argument("--cases", nargs="+", choices=CASES, default=list(CASES))
    parser.add_argument("--output", type=Path)
    parser.add_argument("--worker", choices=CASES, help=argparse.SUPPRESS)
    parser.add_argument("--trace-memory", action="store_true", help=argparse.SUPPRESS)
    args = parser.parse_args()
    if args.worker:
        print(json.dumps(measure(args.worker, args.rows, args.trace_memory)))
        return
    results = {}
    for case in args.cases:
        results[case] = benchmark(case, args)
        timing = results[case]["timings"]
        print(
            f"{case}: setup={timing['setup_seconds']['median']:.6f}s "
            f"run={timing['run_seconds']['median']:.6f}s",
            file=sys.stderr,
            flush=True,
        )
    report = {
        "schema": "ton.benchmark/v1",
        "revision": subprocess.check_output(
            ["git", "rev-parse", "HEAD"], cwd=ROOT, text=True
        ).strip(),
        "python": platform.python_version(),
        "platform": platform.system(),
        "machine": platform.machine(),
        "cpu_count": os.cpu_count(),
        "rows": args.rows,
        "repeats": args.repeats,
        "memory_rows": min(args.rows, args.memory_rows),
        "harness_sha256": hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
        "results": results,
    }
    payload = json.dumps(report, indent=2) + "\n"
    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(payload, encoding="utf-8")
    else:
        print(payload, end="")


if __name__ == "__main__":
    main()
