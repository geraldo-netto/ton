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

## robustness/recovery

| id | status | effort | description |
|----|--------|--------|-------------|

## architecture/modularity/SOLID

| id       | status | effort | description |
|----------|--------|--------|-------------|
| ARCH-001 | open   | L      | Model data types as namespaced registrations: built-ins live under a stable default namespace, plugin types register into additional namespaces, and type lookup resolves by explicit qualified or legacy name without allowing plugins to remove or shadow defaults accidentally. |

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
| DG-001 | open   | M      | Define provenance metadata for generated values: source data type, plugin package/version when used, transform chain, validation mode, and proof result. Keep it optional for streaming output but available to audit logs or sidecar manifests. |

## dependency

| id | status | effort | description |
|----|--------|--------|-------------|

## platform

| id | status | effort | description |
|----|--------|--------|-------------|

## observability

| id      | status | effort | description |
|---------|--------|--------|-------------|
| OBS-001 | open   | M      | Add structured events for plugin mount/unmount decisions, transform preparation, proof-check failures, and validation summaries. Events should include namespace/type/transform ids without leaking generated sensitive values by default. |

## documentation

| id      | status | effort | description |
|---------|--------|--------|-------------|
| DOC-001 | open   | M      | Write an architecture note for namespaced data-type registration: built-in namespace, plugin registrations, transform pipeline, validation/proof-check lifecycle, and compatibility guarantees for existing configs. |
