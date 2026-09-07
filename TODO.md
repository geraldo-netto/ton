# TODO

Reviewed 2026-09-07 against the current code; runtime probes used CPython 3.11.15 with the default 4,300-digit conversion limit. This pass corrects the ledger only. Implementation findings remain pending; no source fixes are claimed.

Approved direction: remove obsolete contracts and spec forms. Do not restore compatibility, add shims, or introduce deprecation/migration layers. Existing approved resolutions remain open; unresolved conflicts in proposed fixes or overlapping tasks are blocked below.

Order related implementation work deliberately: REL-020 before CFG-004 and root distribution proof coverage; ARCH-007 before SCALE-008; coordinate SCALE-005, CFG-006, and CFG-007 around shared numeric handling. Resolve ARCH-006's snapshot boundary before SCALE-007, which remains last in the implementation pass. Each independently completed implementation item still gets its own commit.

DOC-003/004/005 share one executable README-example helper: introduce it once and extend coverage per item, so individual commits do not depend on fixing another stale block first. Once all three are corrected, check every documented spec/output pair with the stated four-row config and `--seed 1`. This audit ran 24 such pairs; exactly those three differed.

## Open

### Reliability / correctness

| id | status | severity | effort | description |
|---|---|---|---|---|
| REL-027 | open | medium | small | Reliability/correctness / CLI option integrity: `open_output_path` and `write_shard` expose raw `UnicodeEncodeError`; only CLI `_stream` translates it. Confirmed: an ASCII shard containing `é` raises the raw exception and correctly rolls back its regular-file stage. Approved direction: normalize output encoding failures at shared output boundaries with `OutputEncodingError` and accurate encoding metadata. Acceptance: direct output contexts and shards expose the domain error and retain regular-file rollback; FIFO remains a direct stream. When relocating `_stream` handling, preserve CLI stdout translation too—stdout bypasses `open_output_path`. Cover writes and output finalization without reclassifying unrelated pipeline failures. |

### Scalability

| id | status | severity | effort | description |
|---|---|---|---|---|
| SCALE-007 | open | medium | large | Scalability: `_discover_generator_types` is already iterative; `_validate_generator_keys` and composite child preparation still recurse. Confirmed locally on CPython 3.11.15: 50 nested single-choice `oneOf` levels generate `x`, while 150 and 250 fail during preparation with a wrapped `RecursionError`. The threshold is runtime-dependent, not a fixed TON limit. Approved direction: explicit-stack key validation and preparation, retaining iterative discovery and complete diagnostics. Sequence last; coordinate with ARCH-006 so config snapshotting does not reintroduce recursion failure. Acceptance: deeply nested valid specs prepare without changing recursion settings, and representative generation/proof checks succeed. This finding's measured failure is preparation; do not claim unlimited runtime nesting solely from a preparation fix. |

### Concurrency

| id | status | severity | effort | description |
|---|---|---|---|---|
| CONC-004 | open | medium | small | Concurrency/configuration: `fork_engine` and `_offset_sequence_spec` coerce original values with `int()` before normal validation; `write_shard` also coerces the total row count. Confirmed: fractional sequence start 1.5 becomes 1, and a shard with `rows: true` writes one row. Approved direction: validate original config values and explicit overrides using ordinary structural/numeric rules before offsets or replacement can hide invalid input. Acceptance: direct generation, forked engines, and shards reject these inputs consistently, including nested sequences; valid integral inputs retain ordinary coercion semantics. Avoid duplicate plugin preparation just to validate offsets. |
| CONC-005 | open | high | medium | Concurrency: `_offset_sequence_spec` returns early for `sequence` and `sequence_of`, skipping their transform-owned sequences. Confirmed: two two-row workers whose sequence source is replaced by a distribution-selected sequence both emit `0, 1`. Approved direction: traverse source children and transform children independently. Apply `sequence_of.count` only to its source child's draw count, not to transforms of the enclosing field. Acceptance: replacing transforms on both source kinds receive correct worker offsets; repeated template fields and child counts preserve non-overlap. Coordinate validation with CONC-004 and context routing with REL-020. |
| CONC-006 | open | low | small | Concurrency/test integrity: `test_fork_engine_workers_yield_disjoint_streams_when_partitioned` creates different configs with manual starts and gives each config only 50 total rows while requesting four 50-row shards. It contradicts automatic-offset guidance and can pass if automatic offsets disappear. Approved direction: use one unoffset 200-row config, derive each worker's 50-row share, and assert exact consecutive ranges for workers 0–3 plus the complete combined range. A disjointness-only assertion is insufficient. |

### Architecture / modularity / SOLID

| id | status | severity | effort | description |
|---|---|---|---|---|
| ARCH-008 | open | low | small | Architecture/modularity: approved simplification removes pre-hash filename recognition from `_staged_candidates`; inspect and manage only hashed destination prefixes. Update `inspect_staged_outputs` documentation as well as legacy-specific expectations. Existing tests using old names also cover owner liveness, age, replacement races, malformed metadata, and non-regular candidates: convert that still-relevant safety coverage to hashed names instead of deleting it wholesale. Acceptance: hashed-stage inspection/cleanup retains those guarantees and old-name recognition is absent. |
| ARCH-009 | open | low | small | Architecture/modularity: `default_registry()` only wraps `make_registry()`, and the module overview explicitly calls it a compatibility entry point. Approved direction: keep `make_registry` as the sole built-in constructor and remove the wrapper, updating internal callers, test imports, cache-helper documentation, and generator module comments. `ton.api.build_extension_catalog` remains the public catalog construction surface. Coordinate with PLUG-006, which removes the facade's old registry shim. Acceptance: one constructor, fresh instances, preserved lazy selection, and no compatibility wording or replacement alias. |

### Plugin extensibility

| id | status | severity | effort | description |
|---|---|---|---|---|
| PLUG-005 | open | medium | medium | Plugin extensibility: `_stamp_plugin_dist` writes attributes onto entry-point instances, although the validator/transform protocols do not require mutability. Confirmed: frozen/slotted protocol implementations register manually but fail exact entry-point loading during metadata stamping. Approved direction: keep distribution provenance in catalog registration metadata, not plugin attributes. Carry that metadata through catalog snapshots into `Engine.provenance`; moving storage alone must not silently drop attribution. Acceptance: frozen and slotted validators/transforms load, mutable generators retain package/version provenance, and copied catalog views keep their existing isolation semantics. Coordinate transform fixtures with REL-020. |
| PLUG-007 | open | medium | small | Plugin extensibility/decoupling: `ton.api` is documented as the supported facade but does not export `TransformResult`, `TransformProof`, `TransformCapabilities`, `ProofResult`, or `PreparationContext`. Confirmed all five are absent. Approved direction: export these contract types and document their roles. Acceptance: a plugin implemented entirely using facade imports can register, prepare, transform, and prove; align its signatures with REL-020/PLUG-008. No additional compatibility facade or alias layer. |
| PLUG-006 | open | medium | small | Plugin extensibility/architecture: `api.build_registry(True)` claims generator-only loading but invokes the all-kind catalog loader; a validator-only provider is executed. Approved resolution is deletion, not narrower compatibility loading: remove `api.build_registry`, `_registry.registry_with_entry_points`, their imports/exports/deprecation code, documentation, and obsolete tests. Keep `build_extension_catalog` as the single plugin-loading facade and retain meaningful loading/selection/isolation tests there. Audit all references; the change is not limited to the previously claimed four files. Remove DOC-011 with the deleted comment; coordinate the built-in constructor cleanup with ARCH-009. No replacement shim. |

### CLI / option integrity

| id | status | severity | effort | description |
|---|---|---|---|---|

### Configuration discoverability

| id | status | severity | effort | description |
|---|---|---|---|---|
| CFG-005 | open | medium | small | Configuration discoverability/plugin extensibility: `_validate_common_field_key_typos` rejects keys before resolving extension ownership. Confirmed: a generator declaring `config_keys={"values", "transform"}` is rejected for `transform`; the same happens with open keys (`config_keys=None`). Approved direction: apply typo diagnostics after resolving extension key ownership, using the existing extension-aware boundary. Acceptance: declared/open plugin keys work, while undeclared keys on closed extensions still fail with appropriate suggestions. Structural-only loading must not guess ownership before a catalog is available. |
| CFG-008 | open | medium | small | Configuration discoverability: default generation and the CLI build a narrowed registry, so an unknown root type alone reports `Available types: (none)`; `api.validate_config` reports 44 references for 22 built-ins, including core aliases. Confirmed with `nosuch`. Approved direction: source default-path suggestions from the full built-in name catalog without eagerly constructing unused generators. Acceptance: default `generate`, CLI, and `validate_config` list the same names. Explicitly supplied empty or restricted registries must still advertise only their actual available types; do not undo explicit-empty registry support. |

### Data governance

| id | status | severity | effort | description |
|---|---|---|---|---|
| DG-004 | open | high | medium | Data governance: a proof hook raising `ValueError("private-proof-value")` leaks that text through `ProofEvaluationError` even with redaction enabled. Confirmed in the library exception string, explicit cause, and formatted traceback; CLI prints the same diagnostic. Approved D1: redacted hook failures retain stage/reference/field and exception class, omit exception text, and suppress chaining; unredacted diagnostics stay detailed. Acceptance: check library `str(exc)`, `__cause__`, default formatted/logged tracebacks, and CLI stderr for source and transform hooks. Do not describe `raise ... from None` as erasing `__context__`; ensure any public cause attribute does not re-expose the redacted message. Coordinate CLI classification with CLI-002. |

### Observability

| id | status | severity | effort | description |
|---|---|---|---|---|
| OBS-009 | open | medium | small | Observability: `_map_config_errors` returns for missing files, invalid config, registry errors, and preparation failures without a `cli_failed` event; missing config arguments and invalid proof-report option combinations also return without it. Confirmed these handled paths emit zero terminal events. Approved direction: each handled pre-generation failure after argument parsing emits exactly one safe terminal record with consistent category, its existing exit code, and zero row counts. Cover generation, `--validate`, namespace/plugin loading, and option-validation paths; preserve single emission for the existing outer unexpected-error handler. This scope does not claim argparse failures before logging setup are already covered. |

### Documentation

| id | status | severity | effort | description |
|---|---|---|---|---|
| DOC-002 | open | low | small | Documentation: README describes uniform floating-point drawing and rounding, but `DecimalGenerator` draws uniformly from representable fixed-point integer steps. Approved direction: describe inclusive bounds, inward rounding to representable steps, and rejection when the interval contains no value at the requested precision. Keep the separate stale seeded output correction in DOC-003. |
| DOC-007 | open | medium | small | Documentation/plugin extensibility: README's unquoted `my_ns.my_transform` TOML key parses as `{"my_ns": {"my_transform": ...}}`, not a flat entry-point mapping. Approved direction: quote the complete key. Acceptance: parse the actual documented TOML and assert `ton.transforms` maps `my_ns.my_transform` directly to the import string. |
| DOC-008 | open | low | small | Documentation/CLI option integrity: README's `-o` flag row rejects all non-regular targets, while Safety notes and `validate_output_target` allow regular files and FIFOs. Approved direction: state that policy consistently, including refusal of other special targets. Keep this as a documentation change; output behavior already permits FIFO streams. |
| DOC-009 | open | medium | small | Documentation/test integrity: README and the `ton.api` docstring use `sink.write(row)`, but generated rows contain no added terminator. `test_library_streaming_example_writes_each_row_once` only counts that incorrect literal. Approved direction: show `sink.write(row + "\n")` in both examples and execute the extracted streaming example against a text sink. Acceptance: each generated row appears once with its intended newline boundary; avoid testing only source-text occurrence counts. |
| DOC-010 | open | low | small | Documentation: the `_registry` module overview advertises full subclass introspection through `discover_generator_classes`, but the function filters the walked tree through the built-in identity allowlist. Approved direction: describe filtered built-in discovery accurately. The discovery implementation and its allowlist tests already match that contract; do not broaden discovery. |
| DOC-012 | open | low | small | Documentation: README's char table calls `maxChar` output length, while `CharGenerator` uses it as draw count and allows multi-character pool strings. Confirmed: `values: ["ab"]`, `maxChar: 2` emits `abab`. Approved direction: document number of draws with replacement and multi-character token semantics; output length is the sum of the selected token lengths. |
| DOC-003 | open | low | small | Documentation: README's decimal seed-one block is stale. Confirmed with the documented four-row CLI command: `22.01`, `93.25`, `10.33`, `41.79`. Approved direction: regenerate that block and cover its actual JSON spec/output with the shared executable README check described above. Keep the sampling explanation change separate in DOC-002. |
| DOC-004 | open | low | small | Documentation: README's char seed-one block is stale. Confirmed with the documented four-row CLI command: `ATTCCC`, `GTAATC`, `TACGAT`, `TAAGTC`. Approved direction: regenerate that block and cover its actual JSON spec/output with the shared executable README check described above. |
| DOC-005 | open | low | small | Documentation: all four rows in README's phone seed-one block are stale. Confirmed CLI output: `+1 (187) 244-6700`, `+1 (847) 047-2990`, `+1 (059) 324-0244`, `+1 (222) 420-8561`. Approved direction: regenerate that block and cover its actual JSON spec/output with the shared executable README check described above. |
| DOC-006 | open | low | small | Documentation: README says twenty-three built-in types; the catalog contains twenty-two distinct built-in generators. Its 44 listed references include bare/core aliases and must not be counted as 44 types. Approved direction: correct the count and test the documented count against unique canonical built-in references from the public catalog. |

## Blocked / Deferred

| id | status | severity | effort | description |
|---|---|---|---|---|
| ARCH-006 | blocked | high | medium | Architecture/data governance / proposed-fix contradiction: `CompiledPlan.types` retains caller-owned nested mappings; audit failures reuse them and `ProofAuditWriter` caches fingerprints by identity. Confirmed: caller mutation changes an earlier failure, and sink mutation changes retained specs while the writer reuses a fingerprint for older serialized content. The approved one-deep-copy direction isolates the caller but does not by itself prevent sink mutation of the shared snapshot. Blocked on specifying that ownership boundary before implementation. Required resolution: retain one isolated engine snapshot with a read-only nested audit view or equivalent mutation isolation; failures and fingerprints must always describe the same content. Acceptance: both caller and sink mutation cannot change retained records or fingerprint meaning; coordinate exact JSON serialization with CFG-007 and stack safety with SCALE-007. |
| DOC-011 | blocked | low | small | Documentation/task contradiction: this item's former direction was to correct the shared-cache comment in `registry_with_entry_points`, but approved PLUG-006 deletes that function. Both instructions target the same disappearing code and would create a redundant edit/commit. Blocked on PLUG-006's deletion; no standalone comment rewrite or compatibility restoration. The current comment is indeed false because `catalog.generators()` deep-copies its snapshot. Remove this row when PLUG-006 removes the function and its comment; do not report the underlying work complete before then. |

## Rejected / Won't fix

| id | status | severity | effort | description |
|---|---|---|---|---|
