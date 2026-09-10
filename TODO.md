# TODO

## Open

### Reliability / correctness

| id | status | severity | effort | description |
|---|---|---|---|---|
| REL-038 | open | medium | small | Reliability/correctness: weighted source and distribution-transform proof evaluate a selected child's proof twice when it rejects: `_distribution.WeightedChoiceSet.accepts` calls `prove`, then `rejection` calls it again for the reason. A stateful hook rejecting once and raising on its second call produces `ProofEvaluationError` instead of the original rejection; even pure expensive hooks double their work. Carry the first proof result and reason through both paths. Verify one invocation and the original reason in strict and audit modes. |
| REL-024 | open | medium | medium | Reliability/correctness: `generators.date._proof_resolution` replaces exact formatted-component constraints with a contiguous time span. For singleton `2024-01-01T12:34:56.123456`, proof accepts `2024-01-01 000001` under `%Y-%m-%d %f`, and `01` under `%S` or `%M`; none can be produced from that range. The approved fix required negative component cases as well as removal of false failures. Resolve by checking whether a timestamp within bounds has every represented component, without accepting gaps in a convex range. |
| REL-041 | open | medium | small | Reliability/correctness: `generators.identity.EmailGenerator.prepare` accepts domain strings containing an at-sign. With `domains: ['bad@x']`, ordinary generation emits `dara.silva@bad@x`, while the same seeded run under strict proof rejects its own output. Resolve domain override validation so accepted configurations produce values satisfying the email generator's contract. Cover malformed domains and ordinary custom domains through validation and generation. |
| REL-042 | open | medium | small | Reliability/correctness: `generators.decimal.DecimalGenerator.prove` bypasses its scale check whenever `decimals == 0`. A spec bounded by 0 and 2 at zero decimal places accepts proof for `1.5`, although generation draws only integers and README promises exactly the configured fractional scale. Require integral values at zero scale and retain correct padding/bounds checks. Test fractional negative cases as well as generated zero-scale values. |

### Scalability

| id | status | severity | effort | description |
|---|---|---|---|---|
| SCALE-012 | open | medium | medium | Scalability: `_specsnapshot.snapshot_spec` has no object-identity memo, so shared in-memory metadata is expanded repeatedly. A graph containing only 15 distinct dictionaries, each parent referencing the same child twice, becomes 32,767 dictionaries in one snapshot; engine construction can make multiple such copies. Preserve shared subgraphs within an isolated snapshot, or otherwise avoid repeated expansion. Verify near-linear copy work and isolation from the caller; handle cyclic metadata explicitly without introducing a workload cap. |
| SCALE-007 | open | high | large | Scalability: `AGENTS.md` forbids workload caps, but `_recursion.max_supported_depth` derives a hard nesting ceiling from an assumed 8,192 bytes per level and `ensure_depth_headroom` rejects valid specs above it, even with zero rows; a 1,026-level spec fails on the local 8 MB stack. It also changes the process-global recursion limit instead of implementing the approved iterative preparation. Resolve by making nested preparation/generation stack-safe without an estimated depth gate or global-limit mutation; cover default and explicitly supplied catalogs. |
| SCALE-009 | open | medium | small | Scalability: `generators.decimal._coerce_decimal` converts numeric inputs through `str(raw)`. An exact integer bound `10**4300` therefore fails preparation at the interpreter digit limit, contrary to the no-precision-cap rule; interpolating that bound into the error message also fails. Convert integer inputs directly to Decimal and keep error formatting safe. Verify large integral bounds in preparation, generation, and proof without a replacement ceiling. |
| SCALE-010 | open | medium | small | Scalability: `_regex_parse._read_brace` uses built-in `int` for repeat counts, retaining the interpreter's decimal-digit ceiling after the separate regex compiler overflow fix. A zero-row spec whose ASCII repeat count has 4,301 digits fails preparation despite requiring no output expansion. Resolve with arbitrary-size integer parsing shared with numeric configuration; test preparation without materializing the requested output or changing global interpreter limits. |
| SCALE-011 | open | high | medium | Scalability/concurrency: `concurrency._offset_sequences` still uses recursive `deepcopy` and recursive offset traversal. In a fresh process, `fork_engine` on a valid 600-level oneOf chain raises raw `RecursionError` before the compiler's depth handling; direct generation supports that depth. Resolve worker config copying and owned-child traversal iteratively, without nesting caps or reliance on another engine first raising a global limit. Verify fresh-process worker construction and generation. |
| SCALE-013 | open | high | medium | Scalability/audit: `_proofaudit` still uses standard `json.dumps` for integer values in specs and record fields. A failure containing an integer bound `10**4300` raises the interpreter's digit-limit ValueError before the report is written, although such bounds now generate successfully and audit promises to stream every failure. Serialize arbitrary-size integers exactly in fingerprints and payloads, including large seeds, without process-global digit-limit changes. Test actual report output and decoded numeric values. |
| SCALE-014 | open | medium | medium | Scalability/precision: `generators.decimal._scaled_integral` raises only Decimal context precision, leaving its default exponent range in force. A finite singleton bound `Decimal('1e1000000')` with zero decimal places prepares successfully but generation raises `decimal.Overflow` while scaling, contrary to the no-precision-cap rule. Resolve exact coefficient/exponent scaling without inheriting a restrictive default context; verify large finite exponents and proof without a new cap. |

### Performance

| id | status | severity | effort | description |
|---|---|---|---|---|
| PERF-040 | open | medium | small | Performance: `generators.base.proven_draws` rebuilds a set containing every candidate's generator/prepared identities on every proof, even though the selected branch is recorded. Proving one selected child among 1,000 candidates performs 2,002 identity lookups and allocates a 1,000-entry set per row. Precompute ownership membership during preparation or tag draws with their owning composite. Verify proof work scales with selected draws rather than the entire choice pool. |
| PERF-039 | open | medium | medium | Performance: the approved composite-proof cost requirement excludes trace allocation in proof-off and unsampled rows, but `drawn`, `WeightedChoiceSet.choose`, and `SequenceOfGenerator.generate` unconditionally create DrawnValue/ChildDraw records. Three rows containing 100 sequence children allocate 300 ChildDraw records in off, sample, and all modes alike. Resolve row-scoped trace collection for every composite, including those without child pipelines, and preserve validators, RNG draws, and output. Verify allocation counts on off and unsampled rows. |

### Concurrency

| id | status | severity | effort | description |
|---|---|---|---|---|
| CONC-018 | open | high | medium | Concurrency/plugin ownership: `concurrency._offset_source_spec` recursively interprets arbitrary plugin metadata as generator specs, bypassing the `Generator.nested_specs` ownership contract. A plugin rendering `metadata.start` with metadata `{'type': 'sequence', 'start': 100}` emits 100 directly but 102 in worker 1 when four total rows are split between two workers. Resolve sequence offset discovery through declared generator/transform child locations and the effective catalog; preserve opaque metadata and the caller's config. Cover custom plugins and replacing transforms. |

### Architecture / modularity / SOLID

| id | status | severity | effort | description |
|---|---|---|---|---|
| ARCH-006 | open | high | medium | Architecture/data governance: `_proofcheck._audit_spec` creates a separate but mutable dict shared by retained failures and the sink. A sink changing `failure.spec['values'][0]` changes earlier and later retained records; `_proofaudit` still reuses the fingerprint of the pre-mutation serialization. Audit content must remain immutable. Resolve by preventing sink/consumer mutation from altering retained audit content or its fingerprint; test record contents and serialized references, not only generated rows. |
| ARCH-007 | open | medium | small | Architecture/schema: weighted preparation now implements only `choices`, but `generators.__init__.BUILTIN_GENERATOR_CONFIG_KEYS['weighted']` still admits removed `values` and `weights` options. A valid `choices` spec mixed with `values: ['ignored']` and `weights: [0]` validates and silently ignores those fields, contrary to the approved single-form schema and unknown-key checks. Remove obsolete accepted keys and test rejection of mixed forms; do not restore legacy behavior. |

### Plugin extensibility

| id | status | severity | effort | description |
|---|---|---|---|---|
| PLUG-005 | open | medium | medium | Plugin extensibility/provenance: `_registry._PLUGIN_PROVENANCE` stores provider data globally by plugin class instead of the approved catalog registration record. Loading the same generator class from a second provider changes `Engine.provenance` on an already-built first engine; an entry point returning `StringGenerator` also labels unrelated built-in string engines with that provider. Resolve with registration-scoped metadata carried through catalog snapshots and process serialization, while retaining support for frozen/slotted plugins. Test two providers sharing a class and untouched core registrations. |

### Configuration discoverability

| id | status | severity | effort | description |
|---|---|---|---|---|
| CFG-007 | open | medium | medium | Configuration precision/audit-format: the approved contract preserves numeric JSON syntax through audit serialization, but `_proofaudit._json_default` returns `str(Decimal(...))`; a numeric bound `0.10000000000000001` becomes a quoted string in the report. Its docstring incorrectly treats JSON numbers as inherently binary floats. Resolve with exact numeric JSON serialization for both payloads and fingerprint input, without float conversion or a replacement precision cap. Test decoded types and exact values, not just matching text. |
| CFG-008 | open | medium | small | Configuration discoverability: `_compiler._available_type_names` unconditionally unions the supplied registry with `make_registry()`. An explicitly empty registry reports every built-in as available, although generation cannot resolve any of them; default generation still lists 22 bare names while catalog validation lists 44 bare/core references. Resolve diagnostics against the effective catalog, honoring explicit empty/restricted mappings and consistent alias naming without constructing unused generators. Test actual available-name sets across generation, CLI, and validation. |
| CFG-004 | open | medium | small | Configuration discoverability: nested transform-child key errors still lose the owning field path in `_compiler`. A typo inside `types.x.choices[0].transforms[0].choices[0].spec` is reported as `types.oneOf.'choices[0]'.transforms[0].choices[0].spec.minvalue` in both generation and validation. README and the approved finding require the full actual config path. Carry the field/index path through recursive preparation rather than reconstructing it from the parent generator type; assert the complete path for mixed generator/transform nesting. |

### Observability

| id | status | severity | effort | description |
|---|---|---|---|---|
| OBS-009 | open | medium | small | Observability: config exceptions now produce a terminal failure event, but `cli._run_inner` returns before that handling when the config argument is missing or proof-report options conflict. With a working events logger, `cli.main([])` exits 1 and invalid proof-report combinations exit 2, both with zero `cli_failed` events. Complete the promised terminal event coverage for these post-parse early returns, with zero row counts and exactly one failure event. |

### Platform

| id | status | severity | effort | description |
|---|---|---|---|---|
| PLAT-016 | open | medium | small | Platform: add permanent automated coverage for `_recursion._stack_bytes` when `resource` is unavailable. Simulate the missing module on any host and verify the documented fallback stack size and usable depth without importing POSIX-only modules. This coverage can proceed independently of the Windows CI verification in PLAT-015. |

### Documentation

| id | status | severity | effort | description |
|---|---|---|---|---|
| DOC-009 | open | medium | small | Documentation: The public `ton.api` module docstring teaches `sink.write(row)`, concatenating every generated record. `test_library_streaming_example_preserves_record_boundaries` claims to execute the documented snippet but actually executes a separately rewritten loop and checks only one literal in README. Correct the remaining public example and execute the actual documented snippets when checking their record boundaries. |
| DOC-036 | open | medium | small | Documentation/plugin-contract: README still promises support for legacy one-argument `prepare(spec)` and says discovery uses `nested_types`; `generators.base` introduces the old signature and `_proof` mentions legacy-signature tracing. The compiler now always calls `prepare(spec, context)` and discovers declared `nested_specs`, and `AGENTS.md` explicitly rejects compatibility shims. Update the extension guidance to the implemented contract and test a documented plugin against it; do not restore the removed adapter. |
| DOC-037 | open | medium | small | Documentation/transform-contract: `docs/architecture.md` says transform preparation calls `Transform.prepare_composite()`, but that method was removed and the protocol/compiler require `prepare(spec, context)`. A plugin following the architecture guide implements the wrong hook. Correct the pipeline and transform guidance, with an executable contract example using the public API. |
| DOC-038 | open | medium | small | Documentation/schema: `docs/architecture.md` says weighted generation preserves legacy config shapes and its Compatibility section promises both legacy and composite forms. Weighted preparation now requires `choices`, and `AGENTS.md` says to remove legacy layers and compatibility notes. Rewrite the affected weighted/compatibility guidance and README's architecture link text around the current schema; do not reintroduce removed forms. |
| DOC-039 | open | low | small | Documentation/recovery: README's safety notes and public `inspect_staged_outputs` still document reporting older `.<basename>.*.tmp` files, but `_staged_candidates` now recognizes only the hashed destination prefix. Such older files are absent from inspection results. Correct the recovery API documentation to the supported recognition scheme; do not restore legacy filename handling. |
| DOC-040 | open | low | small | Documentation: README describes the whole email value as lowercased, but `EmailGenerator.generate` preserves custom domain case; `domains: ['EXAMPLE.COM']` produces `dara.silva@EXAMPLE.COM` and passes proof. Clarify the documentation's case guarantee to match the implemented local-part normalization, or explicitly decide to normalize configured domains and align proof. Cover the chosen custom-domain behavior. |
| DOC-042 | open | low | small | Documentation: `ton.concurrency` states `random.Random` is not thread-safe, while the supported CPython standard-library implementation documents its core random draw as thread-safe. Sharing an RNG does compromise deterministic worker stream assignment, which already justifies TON's per-worker RNGs. Correct the rationale to distinguish reproducibility and state ownership from an unconditional thread-safety claim, and replace the stale `ton.engine.Engine` reference with the public API. |
| DOC-043 | open | low | small | Documentation/distribution: README says an entry with omitted `weight` samples uniformly at 1/N, but `_distribution._coerce_weight` assigns weight 1.0 and sampling remains proportional to all effective weights. With two choices weighted 9 and omitted, the omitted choice has probability 1/10, not 1/2. Document the default weight and say uniform sampling applies when all effective weights are equal; cover a mixed explicit/default example. |

## Blocked / Deferred

| id | status | severity | effort | description |
|---|---|---|---|---|
| PLAT-015 | blocked | high | small | Platform: verify the Windows CI lane with the Windows-only skip on `tests/test_scale_bounds.py::test_unlimited_stack_falls_back_to_an_assumed_size`. Blocked pending Windows CI results confirming that this test skips and the remaining suite passes; local Linux results cannot supply that evidence. Missing-module fallback coverage is tracked independently as PLAT-016. |

## Rejected / Won't fix

| id | status | severity | effort | description |
|---|---|---|---|---|
