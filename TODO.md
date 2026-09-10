# TODO

## Open

### Reliability / correctness

| id | status | severity | effort | description |
|---|---|---|---|---|
| REL-024 | open | medium | medium | Reliability/correctness: `generators.date._proof_resolution` replaces exact formatted-component constraints with a contiguous time span. For singleton `2024-01-01T12:34:56.123456`, proof accepts `2024-01-01 000001` under `%Y-%m-%d %f`, and `01` under `%S` or `%M`; none can be produced from that range. The approved fix required negative component cases as well as removal of false failures. Resolve by checking whether a timestamp within bounds has every represented component, without accepting gaps in a convex range. |

### Scalability

| id | status | severity | effort | description |
|---|---|---|---|---|
| SCALE-007 | open | high | large | Scalability: `AGENTS.md` forbids workload caps, but `_recursion.max_supported_depth` derives a hard nesting ceiling from an assumed 8,192 bytes per level and `ensure_depth_headroom` rejects valid specs above it, even with zero rows; a 1,026-level spec fails on the local 8 MB stack. It also changes the process-global recursion limit instead of implementing the approved iterative preparation. Resolve by making nested preparation/generation stack-safe without an estimated depth gate or global-limit mutation; cover default and explicitly supplied catalogs. |
| SCALE-011 | open | high | medium | Scalability/concurrency: `concurrency._offset_sequences` still uses recursive `deepcopy` and recursive offset traversal. In a fresh process, `fork_engine` on a valid 600-level oneOf chain raises raw `RecursionError` before the compiler's depth handling; direct generation supports that depth. Resolve worker config copying and owned-child traversal iteratively, without nesting caps or reliance on another engine first raising a global limit. Verify fresh-process worker construction and generation. |

### Performance

| id | status | severity | effort | description |
|---|---|---|---|---|

### Concurrency

| id | status | severity | effort | description |
|---|---|---|---|---|
| CONC-018 | open | high | medium | Concurrency/plugin ownership: `concurrency._offset_source_spec` recursively interprets arbitrary plugin metadata as generator specs, bypassing the `Generator.nested_specs` ownership contract. A plugin rendering `metadata.start` with metadata `{'type': 'sequence', 'start': 100}` emits 100 directly but 102 in worker 1 when four total rows are split between two workers. Resolve sequence offset discovery through declared generator/transform child locations and the effective catalog; preserve opaque metadata and the caller's config. Cover custom plugins and replacing transforms. |

### Architecture / modularity / SOLID

| id | status | severity | effort | description |
|---|---|---|---|---|
| ARCH-006 | open | high | medium | Architecture/data governance: `_proofcheck._audit_spec` creates a separate but mutable dict shared by retained failures and the sink. A sink changing `failure.spec['values'][0]` changes earlier and later retained records; `_proofaudit` still reuses the fingerprint of the pre-mutation serialization. Audit content must remain immutable. Resolve by preventing sink/consumer mutation from altering retained audit content or its fingerprint; test record contents and serialized references, not only generated rows. |

### Plugin extensibility

| id | status | severity | effort | description |
|---|---|---|---|---|
| PLUG-005 | open | medium | medium | Plugin extensibility/provenance: `_registry._PLUGIN_PROVENANCE` stores provider data globally by plugin class instead of the approved catalog registration record. Loading the same generator class from a second provider changes `Engine.provenance` on an already-built first engine; an entry point returning `StringGenerator` also labels unrelated built-in string engines with that provider. Resolve with registration-scoped metadata carried through catalog snapshots and process serialization, while retaining support for frozen/slotted plugins. Test two providers sharing a class and untouched core registrations. |

### Configuration discoverability

| id | status | severity | effort | description |
|---|---|---|---|---|

### Observability

| id | status | severity | effort | description |
|---|---|---|---|---|

### Platform

| id | status | severity | effort | description |
|---|---|---|---|---|

### Documentation

| id | status | severity | effort | description |
|---|---|---|---|---|

## Blocked / Deferred

| id | status | severity | effort | description |
|---|---|---|---|---|
| PLAT-015 | blocked | high | small | Platform: verify the Windows CI lane with the Windows-only skip on `tests/test_scale_bounds.py::test_unlimited_stack_falls_back_to_an_assumed_size`. Blocked pending Windows CI results confirming that this test skips and the remaining suite passes; local Linux results cannot supply that evidence. Missing-module fallback coverage is tracked independently as PLAT-016. |

## Rejected / Won't fix

| id | status | severity | effort | description |
|---|---|---|---|---|
