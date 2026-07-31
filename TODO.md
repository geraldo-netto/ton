# TODO

Open review findings tracked per categories in
[`AGENTS.md`](AGENTS.md). Closed items live in commit history.

Status values: `open`, `in-progress`.
Effort values: `S` (<=1h), `M` (1-4h), `L` (>4h).

Resource policy: TON is a batch-processing system. Do not reject valid jobs or
impose hard CPU, memory, row-width, expansion, pool-size, or precision caps.
Prefer streaming, lazy evaluation, chunking, spill-to-disk, and explicit
operator-controlled settings that do not introduce restrictive defaults.

Last full rescan: 2026-08-01 (all categories; cache/build files and directories excluded).

## security

| id | status | effort | description |
|----|--------|--------|-------------|
| SEC-017 | open | M | Entry-point allowlisting trusts only `ep.name` (`_registry.py:236-237`) and reuses that name set across generator, transform, and validator groups. Any installed distribution can publish the same allowed name (in any group) and execute during `ep.load()()`. Bind trust to at least group + distribution identity + entry-point name, reject duplicate providers deterministically, and expose the stronger selector through API/CLI. |
| SEC-018 | open | S | `ProofFailure.redacted()` masks `value`, `id_value`, and `spec` but preserves the generator/transform-controlled `reason` (`_proof.py:77-92`). A plugin can return `ProofResult(False, reason=f"bad {result.value}")`, so `--redact-proof-failures` still leaks the generated value through reports and structured logs. Redact or structurally constrain untrusted reasons and add an echoing-reason regression test. |
| SEC-019 | open | S | Validator failures embed the complete generated value in `ValidationError` (`_engine.py:402-408`), and the CLI prints that exception to stderr (`cli.py:368-372`) with no redaction option. Remove raw values from the default diagnostic (or apply the same explicit redaction policy as proof failures) so credential-like fixture data is not disclosed. |
| SEC-020 | open | M | FIFO output opening has a symlink-swap race: `validate_output_target()` checks `islink`/`stat` and returns `True`, then `open_output_path()` later calls path-based `open()` (`_output.py:33-59,109-112`). In a writable shared directory an attacker can replace the checked FIFO with a symlink before open and redirect the write. Open with no-follow flags where available, validate the opened descriptor with `fstat`, and test a swapped target. |
| SEC-021 | open | S | CI executes mutable third-party action tags (`actions/checkout@v4`, `actions/setup-python@v5`; `.github/workflows/ci.yml:21-24,39-42,68-71,84-87`). Pin actions to reviewed commit SHAs (with version comments) so a moved/compromised tag cannot change trusted build code. |

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
| OBS-031 | open | S | `output_overwrite` is emitted during preflight as soon as a target exists (`_output.py:33-59`), before generation or atomic replacement. Failed/interrupted jobs leave the old file intact but still claim an overwrite; README also says the file was “truncated” (`README.md:1022`). Emit a committed-replacement event after publication and use a separate preflight warning if desired. |

## documentation

| id      | status | effort | description |
|---------|--------|--------|-------------|
