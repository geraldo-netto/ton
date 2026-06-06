# TODO

Open review findings tracked per the categories defined in
[`AGENTS.md`](AGENTS.md). Closed items live in the commit history.

Status values: `open`, `in-progress`.
Effort values: `S` (<=1h), `M` (1-4h), `L` (>4h).

Last full rescan: 2026-06-06.

## security

| id | status | effort | description |
|----|--------|--------|-------------|

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
| CONC-001 | open | M | Extend `ton.concurrency.fork_engine` to support the current engine surface: transform registries/catalogs, proof-check mode, proof sample rate, and seed/provenance context. Forked workers currently cannot use plugin transforms or proof options without bypassing the helper. |

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
| PLUG-004 | open | M | Define one canonical plugin loading API. The newer `ExtensionCatalog` supports namespaced data types/transforms/validators, but the older `build_registry()` API still exposes generator-only entry-point loading with different shadowing and naming behavior. |

## CLI / option integrity

| id      | status | effort | description |
|---------|--------|--------|-------------|
| CLI-002 | open | M | Make `--validate` use catalog-aware validation. The CLI currently constructs an `Engine`, so unknown types/transforms are reported without the available-type/transform lists from `api.validate_config`, and plugin namespace diagnostics differ between validation and library callers. |
| CLI-003 | open | S | Update CLI help for `--entry-points`. It now loads generator, transform, and validator entry-point groups through the catalog path, but the help text still says only trusted third-party generators from `ton.generators` are loaded. |

## configuration discoverability

| id      | status | effort | description |
|---------|--------|--------|-------------|
| CFG-003 | open | M | Normalize config validation entry points. `load_config()` remains structural-only, `api.validate_config()` is catalog-aware, and `Engine` performs another validation path; decide which public path guarantees available-name diagnostics and keep CLI/library behavior aligned. |

## data governance

| id     | status | effort | description |
|--------|--------|--------|-------------|
| DG-002 | open | M | Define redaction controls for proof failure records before exposing them to logs, manifests, or audit exports. `ProofFailure` currently stores raw generated `value`, `id_value`, and full field spec, which can include sensitive synthetic identifiers or source value pools. |

## dependency

| id | status | effort | description |
|----|--------|--------|-------------|

## platform

| id | status | effort | description |
|----|--------|--------|-------------|

## observability

| id      | status | effort | description |
|---------|--------|--------|-------------|
| OBS-002 | open | S | Surface audit proof-check summaries in the CLI and structured logs. `--proof-check audit` can collect `Engine.proof_failures` but normal CLI runs exit 0 without reporting the failure count or where audit details can be retrieved. |

## documentation

| id      | status | effort | description |
|---------|--------|--------|-------------|
| DOC-003 | open | S | Fix README library example for `Engine.from_file`. The README shows `api.Engine.from_file("examples/dna.json", seed=42)`, but `Engine.from_file` does not accept `seed`, so the documented snippet raises `TypeError`. |
| DOC-004 | open | S | Refresh README CLI/plugin documentation for the current option surface. The flags table omits `--proof-check`, `--proof-sample-rate`, and `--list-namespaces`, and the entry-point text still describes generator-only loading despite transform/validator entry-point support. |
