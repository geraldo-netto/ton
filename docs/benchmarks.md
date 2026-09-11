# Benchmarks

[Documentation](README.md) · [Project overview](../README.md)

The [benchmark runner](../benchmarks/run.py),
[comparison script](../benchmarks/compare.py) and saved results live in `benchmarks/`.

Run from the repository root with the same Python interpreter and idle machine:

```sh
uv run --no-sync python benchmarks/run.py --output benchmarks/results/performance-before.json
uv run --no-sync python benchmarks/run.py --output benchmarks/results/performance-after.json
uv run --no-sync python benchmarks/compare.py benchmarks/results/performance-before.json benchmarks/results/performance-after.json --output benchmarks/results/performance-comparison.md
```

The dependency-free harness measures fresh-process imports, Engine construction,
streaming generation, proof checking, nested composites, wide/deep compilation,
and worker setup/generation. Each case gets one discarded warmup and five fresh
process samples. Setup and generation are timed separately; generation includes
row counting and a streaming SHA-256 checksum, with no retained dataset. The
checksums verify equal workloads across repetitions and before/after runs.

Memory uses a separate tracemalloc pass with 1,000 rows, so tracing overhead does
not affect timing samples. Version 2 reports separate construction and runtime
allocation peaks: tracing restarts between phases, excluding input creation and
imports from both Engine measurements. Runtime peak counts newly allocated memory;
it excludes the already retained Engine and input. Import cases measure import
allocations separately. These are Python allocation peaks, not whole-process RSS.
Import measurements use
warm filesystem caches, not a cold disk. Compile cases intentionally emit no rows.
Worker generation uses a fixed worker id and a sequence composite; it measures
the worker helper without process-pool startup or filesystem throughput.

Use `--rows`, `--repeats`, `--memory-rows`, and `--cases` to change workloads.
Keep the same values for comparisons. Negative changes mean less time or memory.
Medians and raw min/max/sample data are saved; small differences within run-to-run
spread are noise, not evidence of an improvement. Results describe this machine
and workload, not a universal performance guarantee.

## Size sweeps

`--sizes` runs each selected case at every supplied size. Cases have independent
default sizes when the option is omitted. `--width` sets the string payload size
for `trace_proof` (100,000 characters by default). Reports retain both dimensions,
and comparison rejects different dimensions, harness code or output fingerprints.
The original ten cases remain the default suite; select the additional cases
explicitly so expensive proof sweeps use an appropriate row count.

| Cases | Meaning of size |
|---|---|
| `paired_proof`, `string_proof`, `email_proof` | Pool entries |
| `nested_proof`, `deep_compile`, `worker_compile`, `trace_proof` | Composite depth |
| `transform_proof` | Identity transform count |
| `wide_compile` | Template field count |
| `worker` | Worker count (one worker is measured) |
| `date_proof` | Upper calendar year, within Python's supported calendar |
| `char_proof` | Draw count from the ambiguous pool `a`, `aa` |
| `regex_proof` | N in `(?:a?){N}a{N}` |
| `snapshot_compile`, `unused_compile` | Referenced/unreferenced string pool entries |
| `extension_compile` | Mutable plugin prototype entries copied by worker construction |
| `decimal` | Negative exponent of the upper bound, with integer output precision |
| `audit` | Pool entries in a failing field; the report is hashed without retention |

```sh
uv run --no-sync python benchmarks/run.py --cases string_proof paired_proof email_proof --sizes 100 1000 10000 --rows 1000 --memory-rows 100 --output benchmarks/results/pools-before.json
uv run --no-sync python benchmarks/run.py --cases deep_compile worker_compile --sizes 100 500 1000 --rows 1 --memory-rows 1 --output benchmarks/results/depth-before.json
uv run --no-sync python benchmarks/run.py --cases regex_proof char_proof trace_proof --sizes 10 30 60 --rows 10 --memory-rows 1 --output benchmarks/results/proofs-before.json
uv run --no-sync python benchmarks/run.py --cases snapshot_compile unused_compile extension_compile decimal audit --sizes 1000 10000 100000 --rows 2 --memory-rows 1 --output benchmarks/results/storage-before.json
uv run --no-sync python benchmarks/run.py --cases date_proof --sizes 100 1000 9999 --rows 100 --memory-rows 10 --output benchmarks/results/dates-before.json
```

Repeat with `after` filenames and compare each corresponding pair. Audit
fingerprints include the full report bytes, independently of write chunk sizes.
The harness hash includes both `run.py` and `workloads.py`. The archived v1
architecture measurements below used combined import/workload allocation peaks
and remain historical results; the current comparison script expects v2 reports.

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
