# Benchmarks

[Documentation](README.md) · [Project overview](../README.md)

The [benchmark runner](../benchmarks/run.py),
[comparison script](../benchmarks/compare.py) and saved results live in `benchmarks/`.

Run from the repository root with the same Python interpreter and idle machine:

```sh
uv run --no-sync python benchmarks/run.py --output benchmarks/results/before.json
uv run --no-sync python benchmarks/run.py --output benchmarks/results/after.json
uv run --no-sync python benchmarks/compare.py benchmarks/results/before.json benchmarks/results/after.json --output benchmarks/results/comparison.md
```

The dependency-free harness measures fresh-process imports, Engine construction,
streaming generation, proof checking, nested composites, wide/deep compilation,
and worker setup/generation. Each case gets one discarded warmup and five fresh
process samples. Setup and generation are timed separately; generation includes
row counting and a streaming SHA-256 checksum, with no retained dataset. The
checksums verify equal workloads across repetitions and before/after runs.

Memory uses a separate tracemalloc pass with 1,000 rows, so tracing overhead does
not affect timing samples. Reported peak includes Python allocations during API
import and the workload; it is not whole-process RSS. Import measurements use
warm filesystem caches, not a cold disk. Compile cases intentionally emit no rows.
Worker generation uses a fixed worker id and a sequence composite; it measures
the worker helper without process-pool startup or filesystem throughput.

Use `--rows`, `--repeats`, `--memory-rows`, and `--cases` to change workloads.
Keep the same values for comparisons. Negative changes mean less time or memory.
Medians and raw min/max/sample data are saved; small differences within run-to-run
spread are noise, not evidence of an improvement. Results describe this machine
and workload, not a universal performance guarantee.

## Recorded architecture comparison

[The saved comparison](../benchmarks/results/comparison.md) compares `e7d6569` with `57127f6`
using the unchanged harness, Python 3.12.3, 20,000 rows and five measured samples
per case. All generated row counts, character counts and output checksums match.
Raw timings and traced allocation peaks are in [before.json](../benchmarks/results/before.json)
and [after.json](../benchmarks/results/after.json).

Representative median elapsed times:

| Measurement | Before | After | Change |
|---|---:|---:|---:|
| JSON-only import | 28.23 ms | 6.99 ms | -75.2% |
| Integer generation | 21.72 ms | 38.81 ms | +78.7% |
| Mixed generation | 112.46 ms | 133.57 ms | +18.8% |
| Four-transform generation with proof | 113.19 ms | 231.01 ms | +104.1% |

The larger runtime increases exceed the observed sample ranges. The new row
validation scope and shared transform dispatcher add work in these paths; this
run measures their combined effect with the other architecture changes, without
isolating individual contributions. The nested-proof median increased 4.6%, but
its before/after sample ranges overlap. JSON-only traced peak allocations fell
50.9%; the remaining cases increased roughly 2%.
