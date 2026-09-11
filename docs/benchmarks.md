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

Reports record the starting revision and dirty-tree status, plus content hashes
for tracked and nonignored files under `ton/`, Python benchmark scripts,
`pyproject.toml` and `uv.lock`. Cache/build outputs are excluded. Interpreter build
and installed distribution versions are recorded separately. Dirty source is
allowed and identified by its own fingerprint; the revision alone does not
identify an uncommitted implementation. Keep the corresponding changes to
reproduce a dirty measurement.

Source and environment are checked before and after the samples. If they differ,
the run fails before publishing its report; an existing output remains intact.
Keep source and dependencies stable throughout a run: boundary checks cannot
detect a change that is reverted before verification. Comparisons also require
matching recorded environments.

## Regex continuation follow-up

PERF-051 compares `b11f00c` with the subsequent continuation optimization using
the same harness: one warmup, five timed samples of 10 rows, and one allocation
sample of 1 row at sizes 10, 30 and 60. The after report identifies the measured
working-tree source hashes and marks that source as dirty. All output fingerprints
match, including the allocation samples.

| Repeat size | Before | After | Runtime change | Runtime allocation change |
|---|---:|---:|---:|---:|
| 10 | 8.75 ms | 3.95 ms | -54.9% | -61.8% |
| 30 | 58.15 ms | 26.19 ms | -55.0% | -58.8% |
| 60 | 236.63 ms | 105.39 ms | -55.5% | -67.8% |

At size 60, a single seed-42 proof allocates 2,617 continuation nodes instead
of 6,950 and makes 5,242 interner calls instead of 15,815. Completed tasks and
single-node repeat bodies avoid temporary sequence states. The existing frontier
memory, exhaustive matching, nullable repetition and deep nesting tests remain
in the suite, alongside permanent allocation/work-count checks.

Saved [before](../benchmarks/results/regex-continuations-before.json),
[after](../benchmarks/results/regex-continuations-after.json) and
[full comparison](../benchmarks/results/regex-continuations-comparison.md).
Reproduce the sweep with:

```bash
uv run --no-sync python benchmarks/run.py --cases regex_proof --sizes 10 30 60 --rows 10 --memory-rows 1 --repeats 5 --output benchmarks/results/regex-continuations-after.json
```

## Recorded performance and scalability comparison

The September 11, 2026 run compares `1ccdea4` (the expanded harness, before
runtime changes) with `f80de01` (all 17 performance/scalability items completed).
Both use Python 3.12.3 on Linux x86-64, the same harness and dimensions, one
warmup and five measured samples. All 52 case/size combinations passed comparison:
row counts, character counts, row checksums and audit byte checksums match,
including the separate allocation samples.

| Suite and comparison | Timed rows | Allocation rows | Raw reports |
|---|---:|---:|---|
| [Default suite](../benchmarks/results/performance-comparison.md) | 20,000 | 1,000 | [Before](../benchmarks/results/performance-before.json), [after](../benchmarks/results/performance-after.json) |
| [Pool sizes](../benchmarks/results/pools-comparison.md) | 1,000 | 100 | [Before](../benchmarks/results/pools-before.json), [after](../benchmarks/results/pools-after.json) |
| [Compilation depth](../benchmarks/results/depth-comparison.md) | 1 | 1 | [Before](../benchmarks/results/depth-before.json), [after](../benchmarks/results/depth-after.json) |
| [Proof sizes](../benchmarks/results/proofs-comparison.md) | 10 | 1 | [Before](../benchmarks/results/proofs-before.json), [after](../benchmarks/results/proofs-after.json) |
| [Storage and numeric sizes](../benchmarks/results/storage-comparison.md) | 2 | 1 | [Before](../benchmarks/results/storage-before.json), [after](../benchmarks/results/storage-after.json) |
| [Date intervals](../benchmarks/results/dates-comparison.md) | 100 | 10 | [Before](../benchmarks/results/dates-before.json), [after](../benchmarks/results/dates-after.json) |

Rows above are runner settings; import and compilation cases emit no rows.
The size-sweep commands above reproduce the targeted workloads.

Representative median elapsed times (generation/proof unless marked setup):

| Measurement | Before | After | Change |
|---|---:|---:|---:|
| Integer, 20,000 rows | 38.37 ms | 25.00 ms | -34.9% |
| Four transforms with proof, 20,000 rows | 217.44 ms | 153.34 ms | -29.5% |
| String proof, 10,000 pool entries, 1,000 rows | 31.20 ms | 3.17 ms | -89.9% |
| Compilation setup, depth 1,000 | 98.19 ms | 15.31 ms | -84.4% |
| Date proof, years 0001–9999, 100 rows | 374.14 ms | 1.86 ms | -99.5% |
| Character proof, 60 draws, 10 rows | 2.63 ms | 0.46 ms | -82.6% |
| Nested trace, depth 60, 100,000 characters, 10 rows | 22.24 ms | 2.96 ms | -86.7% |
| Audit, 100,000 pool entries, 2 rows | 285.73 ms | 213.70 ms | -25.2% |

Large-input allocation reductions are also substantial. At depth 1,000,
compilation setup peak fell from 8.90 MB to 1.00 MB. For one checked row, the
depth-60 string trace fell from 6.14 MB to 0.22 MB (-96.4%); the first audit record
with 100,000 pool entries fell from 10.67 MB to 1.31 MB (-87.8%). MB here means
1,000,000 bytes. Unused 100,000-entry pools no longer dominate construction:
setup fell from 55.17 ms / 10.81 MB to 0.16 ms / 0.03 MB.

There are measured tradeoffs. Regex proofs at N=60 used 91.2% less runtime
allocation (2.77 MB to 0.24 MB), but ten rows took 233.53 ms versus 132.59 ms
(+76.1%). The frontier matcher releases history while doing more work on this
ambiguous pattern. Small nested integer proofs at depth 8 increased from
671.50 ms to 717.85 ms (+6.9%) for 20,000 rows. Both increases exceed the observed
sample ranges. These results record the combined implementation changes.

Lazy membership indexes exchange retained memory for faster pool proofs. The
10,000-entry string case's new runtime allocation peak rose from 5.2 KB to
657.1 KB, while setup peak fell from 1.09 MB to 0.26 MB. Runtime measurement
includes first-use index construction; proof-off jobs do not build the index.
Cached transform calls and separate trace objects also increase some small-case
allocation peaks. Phase peaks cannot be added to obtain a process-memory peak.

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
