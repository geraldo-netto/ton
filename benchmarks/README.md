# Benchmarks

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
