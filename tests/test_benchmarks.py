"""PERF-050: benchmark dimensions, phase accounting and output comparability."""

import json
import subprocess
import sys
from copy import deepcopy
from pathlib import Path

import pytest

from benchmarks.compare import compare

ROOT = Path(__file__).resolve().parents[1]


@pytest.fixture(scope="module")
def benchmark_report(tmp_path_factory):
    output = tmp_path_factory.mktemp("benchmarks") / "report.json"
    subprocess.run(
        [
            sys.executable,
            str(ROOT / "benchmarks/run.py"),
            "--cases",
            "string_proof",
            "trace_proof",
            "audit",
            "worker_compile",
            "--sizes",
            "2",
            "3",
            "--rows",
            "2",
            "--memory-rows",
            "1",
            "--repeats",
            "1",
            "--width",
            "8",
            "--output",
            str(output),
        ],
        cwd=ROOT,
        check=True,
        capture_output=True,
        text=True,
        timeout=60,
    )
    return json.loads(output.read_text())


def test_benchmark_sweeps_separate_phases_and_preserve_fingerprints(benchmark_report):
    report = benchmark_report
    assert report["schema"] == "ton.benchmark/v2"
    assert len(report["results"]) == 8
    for result in report["results"].values():
        assert result["parameters"]["size"] in {2, 3}
        assert result["parameters"]["width"] == 8
        memory = result["memory_sample"]
        assert memory["setup_peak_bytes"] > 0
        assert memory["run_peak_bytes"] >= 0
        assert memory["rows"] in {0, 1}
        assert result["samples"][0]["rows"] in {0, 2}
    assert "Run allocation change" in compare(report, deepcopy(report))


@pytest.mark.parametrize("mutation", ["parameters", "sha256", "memory_sha256"])
def test_benchmark_comparison_rejects_different_work(benchmark_report, mutation):
    before = benchmark_report
    after = deepcopy(before)
    result = after["results"]["string_proof@2"]
    if mutation == "parameters":
        result["parameters"]["size"] = 10
    elif mutation == "sha256":
        result["samples"][0]["sha256"] = "different"
    else:
        result["memory_sample"]["sha256"] = "different"
    with pytest.raises(ValueError):
        compare(before, after)


def test_benchmark_additional_workloads_smoke():
    from benchmarks.run import CASES, DEFAULT_CASES, measure

    for case in set(CASES) - set(DEFAULT_CASES):
        result = measure(case, 2, True, size=2, width=8)
        assert result["rows"] == (0 if case.endswith("compile") else 2)
        assert len(result["sha256"]) == 64
        assert result["setup_peak_bytes"] > 0
        assert result["run_peak_bytes"] >= 0
