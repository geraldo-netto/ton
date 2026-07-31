# TODO

Open review findings tracked per categories in
[`AGENTS.md`](AGENTS.md). Closed items live in commit history.

Status values: `open`, `in-progress`.
Effort values: `S` (<=1h), `M` (1-4h), `L` (>4h).

Resource policy: TON is a batch-processing system. Do not reject valid jobs or
impose hard CPU, memory, row-width, expansion, pool-size, or precision caps.
Prefer streaming, lazy evaluation, chunking, spill-to-disk, and explicit
operator-controlled settings that do not introduce restrictive defaults.

Last full rescan: 2026-07-16 (all categories; cache files/directories excluded).

## security

| id | status | effort | description |
|----|--------|--------|-------------|
| SEC-011 | open | S | `generators/hash.py:48` bcrypt-hashes every entry in `values` during prepare, so `--validate` performs the full KDF workload without generating rows. Prepare bcrypt entries lazily and cache them on demand without limiting the configured pool size. |
| SEC-012 | open | S | `_output.py:85` `target_mode` flips the process-wide umask to 0 and restores it to read it. In an embedding/threaded process any file created in that window lands at 0666/0777. Derive the mode without mutating global umask. |
| SEC-016 | open | S | `DecimalGenerator.prepare` eagerly computes `10 ** decimals`, making validation perform the requested high-precision workload. Defer precision-dependent allocation until generation without restricting configured precision. |

## code complexity

| id | status | effort | description |
|----|--------|--------|-------------|

## code duplication

| id | status | effort | description |
|----|--------|--------|-------------|

## reliability/correctness

| id      | status | effort | description |
|---------|--------|--------|-------------|
| REL-028 | open | S | `cli._validate_proof_report_args` compares only `abspath` strings. Two paths that resolve to the same file through a symlinked directory (or case alias on a case-insensitive platform) pass validation; the outer proof-report atomic replacement then overwrites the generated data and the CLI exits `0`. Compare canonical targets with `realpath`/`normcase` plus `samefile` where available, and add alias-path tests. |

## performance

| id      | status | effort | description |
|---------|--------|--------|-------------|

## scalability

| id | status | effort | description |
|----|--------|--------|-------------|

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
| DEC-019 | open | S | Core `Engine` imports the infrastructure-specific `_proofaudit.ProofAuditWriteError` solely to let report failures escape its generator exception wrapper, while `_set_proof_failure_sink` is explicitly CLI-owned. Any other sink exception is misreported as `TemplateError: Generator ... raised ...`. Define a proof-layer sink/error boundary and keep report serialization/output exceptions out of `_engine.py`. |

## business/design patterns/DDD

| id | status | effort | description |
|----|--------|--------|-------------|

## plugin extensibility

| id       | status | effort | description |
|----------|--------|--------|-------------|

## CLI / option integrity

| id      | status | effort | description |
|---------|--------|--------|-------------|
| CLI-018 | open | S | `_open_proof_report` catches `OSError` around its `yield`, so errors raised by the primary `_open_output`/`_stream` body are converted to `ProofAuditWriteError`. With a valid report plus an unwritable or non-encodable data output, the CLI incorrectly prints `cannot write proof report`. Restrict translation to report open/write/finalize failures and preserve exceptions from the context body; add combined-output tests. |

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

## documentation

| id      | status | effort | description |
|---------|--------|--------|-------------|
