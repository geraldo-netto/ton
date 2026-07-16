# TODO

Open review findings tracked per categories in
[`AGENTS.md`](AGENTS.md). Closed items live in commit history.

Status values: `open`, `in-progress`.
Effort values: `S` (<=1h), `M` (1-4h), `L` (>4h).

Last full rescan: 2026-07-16 (all categories; cache files/directories excluded).

## security

| id | status | effort | description |
|----|--------|--------|-------------|
| SEC-010 | open | S | Define one shared maximum total-expansion budget and overflow-safe product helper for composite generator preparation, aligned with `regex.MAX_TOTAL_EXPANSION`. |
| SEC-013 | open | S | Apply the total-expansion budget to nested `sequence_of` specs; reject products above the cap during validation/prepare. |
| SEC-014 | open | S | Propagate and enforce the total-expansion budget through nested `oneOf` and `weighted` branches. |
| SEC-015 | open | S | Add boundary and adversarial nesting tests proving composite expansion is accepted at the cap and rejected above it without materializing output. |
| SEC-011 | open | S | `generators/hash.py:48` bcrypt-hashes every entry of an unbounded `values` list at prepare time (up to 2^12 rounds each). `--validate` runs `prepare`, so a "validate only, no rows" invocation performs unbounded KDF work (1000 words ~= minutes of CPU). Cap `values` length for bcrypt or hash lazily. |
| SEC-012 | open | S | `_output.py:85` `target_mode` flips the process-wide umask to 0 and restores it to read it. In an embedding/threaded process any file created in that window lands at 0666/0777. Derive the mode without mutating global umask. |
| SEC-016 | open | S | `DecimalGenerator.prepare` computes `10 ** decimals` with no upper bound. A local or uploaded config such as `{"decimals": 1000000000}` can consume unbounded CPU/memory during normal construction or `--validate`; define and enforce a decimal precision cap before exponentiation. |

## code complexity

| id | status | effort | description |
|----|--------|--------|-------------|

## code duplication

| id | status | effort | description |
|----|--------|--------|-------------|

## reliability/correctness

| id      | status | effort | description |
|---------|--------|--------|-------------|

## performance

| id      | status | effort | description |
|---------|--------|--------|-------------|

## scalability

| id | status | effort | description |
|----|--------|--------|-------------|
| SCAL-010 | open | S | Replace the `concurrency.py` worker contract that returns `list(eng)` with a bounded-memory shard-to-file or chunk-streaming primitive. |
| SCAL-013 | open | S | Add multiprocess tests proving the replacement preserves exact row counts/order expectations and does not accumulate an entire worker shard in memory. |
| SCAL-014 | open | S | Rewrite the documented multiprocessing recipe to use the bounded-memory primitive and explain output merge/cleanup behavior. |
| SCAL-011 | open | S | Define row-width limit semantics for literals plus all placeholders, including whether the existing 2 MB guidance becomes a hard default or configurable cap. |
| SCAL-015 | open | S | Compute a conservative prepared worst-case width for fixed/bounded generators and reject templates whose aggregate width exceeds the configured limit. |
| SCAL-016 | open | S | Enforce a runtime row-width guard for generators whose maximum cannot be known during prepare, before unbounded content is retained or written. |
| SCAL-017 | open | S | Add aggregate-placeholder, composite, boundary, and unknown-width tests; document the row-width limit and error. |

## concurrency

| id | status | effort | description |
|----|--------|--------|-------------|

## robustness/recovery

| id | status | effort | description |
|----|--------|--------|-------------|

## architecture/modularity/SOLID

| id       | status | effort | description |
|----------|--------|--------|-------------|

## decoupling

| id      | status | effort | description |
|---------|--------|--------|-------------|

## business/design patterns/DDD

| id | status | effort | description |
|----|--------|--------|-------------|

## plugin extensibility

| id       | status | effort | description |
|----------|--------|--------|-------------|

## CLI / option integrity

| id      | status | effort | description |
|---------|--------|--------|-------------|

## configuration discoverability

| id      | status | effort | description |
|---------|--------|--------|-------------|

## data governance

| id     | status | effort | description |
|--------|--------|--------|-------------|

## dependency

| id | status | effort | description |
|----|--------|--------|-------------|

## platform

| id | status | effort | description |
|----|--------|--------|-------------|

## observability

| id      | status | effort | description |
|---------|--------|--------|-------------|
| OBS-020 | open | S | Define a bounded proof-audit report schema and CLI destination/format, including redaction semantics and behavior when the sample cap is reached. |
| OBS-024 | open | S | Emit retained `Engine.proof_failures` through the proof-audit report path and make `--redact-proof-failures` affect that visible output. |
| OBS-025 | open | S | Add CLI tests for clear/redacted reports, sampling caps, paired values, and report-write failures; update proof-audit help/docs. |

## documentation

| id      | status | effort | description |
|---------|--------|--------|-------------|
