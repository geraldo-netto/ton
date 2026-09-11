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
DEFAULT_CASES = (
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


# Keep the original quick suite as the default; expensive sweeps are explicit.
CASES = (
    *DEFAULT_CASES,
    "string_proof",
    "email_proof",
    "date_proof",
    "char_proof",
    "regex_proof",
    "trace_proof",
    "snapshot_compile",
    "unused_compile",
    "worker_compile",
    "decimal",
    "extension_compile",
    "audit",
)


def measure(
    case: str, rows: int, memory: bool, *, size: int | None = None, width: int = 100000
) -> dict:
    sys.path.insert(0, str(ROOT))
    if case.startswith("import_"):
        if memory:
            tracemalloc.start()
        started = time.perf_counter()
        importlib.import_module("ton._json" if case == "import_json" else "ton.api")
        result = {"setup_seconds": time.perf_counter() - started, "run_seconds": 0.0}
        if memory:
            result.update(setup_peak_bytes=tracemalloc.get_traced_memory()[1], run_peak_bytes=0)
            tracemalloc.stop()
        return result
    return measure_engine(case, rows, memory=memory, size=size, width=width)


def measure_engine(case, rows, *, memory=False, size=None, width=100000):
    from benchmarks.workloads import (
        DEFAULT_SIZES,
        DigestSink,
        build_engine,
        config_for,
        options_for,
    )

    # Input creation and imports are outside both measured phases.
    size = DEFAULT_SIZES.get(case, 1) if size is None else size
    config = config_for(case, rows, size, width)
    options = options_for(case, size)
    sink = DigestSink()
    if memory:
        tracemalloc.start()
    started = time.perf_counter()
    engine = build_engine(case, config, options, size, sink)
    result = {"setup_seconds": time.perf_counter() - started}
    if memory:
        result["setup_peak_bytes"] = tracemalloc.get_traced_memory()[1]
        tracemalloc.stop()
        tracemalloc.start()
    started = time.perf_counter()
    result.update(consume(engine, case, sink))
    result["run_seconds"] = time.perf_counter() - started
    if memory:
        result["run_peak_bytes"] = tracemalloc.get_traced_memory()[1]
        tracemalloc.stop()
    return result


def consume(engine, case, sink):
    count = characters = 0
    digest = hashlib.sha256()
    if not case.endswith("compile"):
        for row in engine:
            count += 1
            characters += len(row)
            digest.update(row.encode("utf-8"))
            digest.update(b"\n")
    return {
        "rows": count,
        "characters": characters,
        "sha256": digest.hexdigest(),
        "audit_characters": sink.characters,
        "audit_sha256": sink.digest.hexdigest(),
    }


def sample(case, rows, *, memory=False, size=None, width=100000):
    command = [
        sys.executable,
        str(Path(__file__).resolve()),
        "--worker",
        case,
        "--rows",
        str(rows),
        "--width",
        str(width),
    ]
    if size is not None:
        command.extend(("--sizes", str(size)))
    if memory:
        command.append("--trace-memory")
    completed = subprocess.run(command, check=True, capture_output=True, text=True, cwd=ROOT)
    return json.loads(completed.stdout)


def fingerprint(sample):
    return tuple(
        sample.get(key)
        for key in ("rows", "characters", "sha256", "audit_characters", "audit_sha256")
    )


def benchmark(case, args, size):
    sample(case, args.rows, size=size, width=args.width)
    samples = [sample(case, args.rows, size=size, width=args.width) for _ in range(args.repeats)]
    if len({fingerprint(s) for s in samples}) != 1:
        raise RuntimeError(f"non-deterministic benchmark output: {case}")
    timings = {}
    for key in ("setup_seconds", "run_seconds"):
        values = [s[key] for s in samples]
        timings[key] = {"median": statistics.median(values), "min": min(values), "max": max(values)}
    memory = sample(
        case, min(args.rows, args.memory_rows), memory=True, size=size, width=args.width
    )
    return {
        "parameters": {"size": size, "width": args.width},
        "samples": samples,
        "timings": timings,
        "memory_sample": memory,
    }


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
    parser.add_argument("--cases", nargs="+", choices=CASES, default=list(DEFAULT_CASES))
    parser.add_argument(
        "--sizes",
        type=positive_int,
        nargs="+",
        help="Sweep each case over these sizes (see docs/benchmarks.md).",
    )
    parser.add_argument(
        "--width", type=positive_int, default=100000, help="Payload characters for trace_proof."
    )
    parser.add_argument("--output", type=Path)
    parser.add_argument("--worker", choices=CASES, help=argparse.SUPPRESS)
    parser.add_argument("--trace-memory", action="store_true", help=argparse.SUPPRESS)
    args = parser.parse_args()
    if args.worker:
        print(
            json.dumps(
                measure(
                    args.worker,
                    args.rows,
                    args.trace_memory,
                    size=args.sizes[0] if args.sizes else None,
                    width=args.width,
                )
            )
        )
        return
    sys.path.insert(0, str(ROOT))
    from benchmarks.workloads import DEFAULT_SIZES

    results = {}
    for case in args.cases:
        for size in args.sizes or [DEFAULT_SIZES.get(case, 1)]:
            key = f"{case}@{size}"
            results[key] = benchmark(case, args, size)
            timing = results[key]["timings"]
            print(
                f"{key}: setup={timing['setup_seconds']['median']:.6f}s "
                f"run={timing['run_seconds']['median']:.6f}s",
                file=sys.stderr,
                flush=True,
            )
    report = {
        "schema": "ton.benchmark/v2",
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
        "harness_sha256": hashlib.sha256(
            Path(__file__).read_bytes() + (ROOT / "benchmarks/workloads.py").read_bytes()
        ).hexdigest(),
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
