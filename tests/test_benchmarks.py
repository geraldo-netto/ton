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


@pytest.mark.parametrize("mutation", ["parameters", "sha256", "memory_sha256", "environment"])
def test_benchmark_comparison_rejects_different_work(benchmark_report, mutation):
    before = benchmark_report
    after = deepcopy(before)
    result = after["results"]["string_proof@2"]
    if mutation == "parameters":
        result["parameters"]["size"] = 10
    elif mutation == "sha256":
        result["samples"][0]["sha256"] = "different"
    elif mutation == "environment":
        after["environment"]["packages"]["ton"] = "different"
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


def _git(root, *args):
    return subprocess.check_output(
        [
            "git",
            "-c",
            "user.name=Benchmark Test",
            "-c",
            "user.email=benchmark@example.invalid",
            *args,
        ],
        cwd=root,
        text=True,
    ).strip()


@pytest.fixture
def source_repository(tmp_path, monkeypatch):
    """PERF-052: isolated Git state; no mutations to the actual checkout."""
    from benchmarks import run, workloads

    monkeypatch.setitem(sys.modules, "benchmarks.workloads", workloads)

    root = tmp_path / "repo"
    (root / "ton").mkdir(parents=True)
    (root / "benchmarks").mkdir()
    (root / "ton/leaf.py").write_text("value = 1\n")
    for name in ("run.py", "workloads.py"):
        (root / "benchmarks" / name).write_text("# fixture harness\n")
    (root / "uv.lock").write_text("version = 1\n")
    (root / ".gitignore").write_text("__pycache__/\n*.pyc\n")
    _git(root, "init", "--quiet")
    _git(root, "config", "core.hooksPath", str(tmp_path / "no-hooks"))
    _git(root, "add", ".")
    _git(root, "commit", "--quiet", "-m", "fixture")
    monkeypatch.setattr(run, "ROOT", root)
    monkeypatch.setattr(sys, "path", list(sys.path))
    monkeypatch.setattr(sys, "argv", ["benchmarks/run.py", "--cases", "integer"])
    monkeypatch.setattr(
        run,
        "benchmark",
        lambda *args: {
            "timings": {"setup_seconds": {"median": 0.0}, "run_seconds": {"median": 0.0}},
        },
    )
    return root


def test_benchmark_identifies_clean_and_dirty_source(source_repository, capsys):
    """PERF-052: dirty source has its own fingerprint under the same committed revision."""
    from benchmarks import run

    root = source_repository
    run.main()
    clean = json.loads(capsys.readouterr().out)
    assert clean["source"]["revision"] == clean["revision"] == _git(root, "rev-parse", "HEAD")
    assert clean["source"]["dirty"] is False
    (root / "ton/leaf.py").write_text("value = 2\n")
    run.main()
    dirty = json.loads(capsys.readouterr().out)
    assert dirty["source"]["dirty"] is True
    assert dirty["revision"] == clean["revision"]
    assert dirty["source"]["sha256"] != clean["source"]["sha256"]
    assert dirty["harness_sha256"] == clean["harness_sha256"]
    assert "pytest" in dirty["environment"]["packages"]
    assert dirty["environment"]["implementation"]


@pytest.mark.parametrize("mutation", ["edit", "add", "delete", "commit", "dependency"])
def test_benchmark_rejects_mid_run_source_changes(source_repository, monkeypatch, mutation):
    """PERF-052: equal output cannot legitimize samples from different source states."""
    from benchmarks import run

    root = source_repository
    original = run.benchmark

    def mutate(*args):
        if mutation == "edit":
            (root / "ton/leaf.py").write_text("value = 2\n")
        elif mutation == "add":
            (root / "ton/new.py").write_text("value = 3\n")
        elif mutation == "delete":
            (root / "ton/leaf.py").unlink()
        elif mutation == "dependency":
            (root / "uv.lock").write_text("version = 2\n")
        else:
            _git(root, "commit", "--quiet", "--allow-empty", "-m", "changed revision")
        return original(*args)

    output = root / "existing.json"
    output.write_text("previous report\n")
    monkeypatch.setattr(run, "benchmark", mutate)
    monkeypatch.setattr(sys, "argv", [*sys.argv, "--output", str(output)])
    with pytest.raises(RuntimeError, match="source changed during benchmark"):
        run.main()
    assert output.read_text() == "previous report\n"


def test_benchmark_ignores_generated_cache_files(source_repository, monkeypatch, capsys):
    """PERF-052: normal interpreter cache writes do not invalidate a source measurement."""
    from benchmarks import run

    root = source_repository
    original = run.benchmark

    def cached(*args):
        (root / "ton/__pycache__").mkdir()
        (root / "ton/__pycache__/leaf.pyc").write_bytes(b"cache")
        return original(*args)

    monkeypatch.setattr(run, "benchmark", cached)
    run.main()
    assert json.loads(capsys.readouterr().out)["source"]["dirty"] is False


def test_benchmark_rejects_mid_run_environment_changes(source_repository, monkeypatch):
    """PERF-052: changed installed dependencies invalidate otherwise identical samples."""
    from benchmarks import run

    original = run.benchmark
    version = "before"

    def changed(*args):
        nonlocal version
        version = "after"
        return original(*args)

    monkeypatch.setattr(run, "environment_state", lambda: {"packages": {"plugin": version}})
    monkeypatch.setattr(run, "benchmark", changed)
    with pytest.raises(RuntimeError, match="environment changed during benchmark"):
        run.main()
