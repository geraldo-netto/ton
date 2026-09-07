# TODO

Reviewed 2026-09-07 against the current code; runtime probes used CPython 3.11.15 with the default 4,300-digit conversion limit. This pass corrects the ledger only. Implementation findings remain pending; no source fixes are claimed.

Approved direction: remove obsolete contracts and spec forms. Do not restore compatibility, add shims, or introduce deprecation/migration layers. Existing approved resolutions remain open; unresolved conflicts in proposed fixes or overlapping tasks are blocked below.

Order related implementation work deliberately: REL-020 before CFG-004 and root distribution proof coverage; ARCH-007 before SCALE-008; coordinate SCALE-005, CFG-006, and CFG-007 around shared numeric handling. Resolve ARCH-006's snapshot boundary before SCALE-007, which remains last in the implementation pass. Each independently completed implementation item still gets its own commit.

DOC-003/004/005 share one executable README-example helper: introduce it once and extend coverage per item, so individual commits do not depend on fixing another stale block first. Once all three are corrected, check every documented spec/output pair with the stated four-row config and `--seed 1`. This audit ran 24 such pairs; exactly those three differed.

## Open

### Reliability / correctness

| id | status | severity | effort | description |
|---|---|---|---|---|

### Scalability

| id | status | severity | effort | description |
|---|---|---|---|---|
| SCALE-007 | open | medium | large | Scalability: `_discover_generator_types` is already iterative; `_validate_generator_keys` and composite child preparation still recurse. Confirmed locally on CPython 3.11.15: 50 nested single-choice `oneOf` levels generate `x`, while 150 and 250 fail during preparation with a wrapped `RecursionError`. The threshold is runtime-dependent, not a fixed TON limit. Approved direction: explicit-stack key validation and preparation, retaining iterative discovery and complete diagnostics. Sequence last; coordinate with ARCH-006 so config snapshotting does not reintroduce recursion failure. Acceptance: deeply nested valid specs prepare without changing recursion settings, and representative generation/proof checks succeed. This finding's measured failure is preparation; do not claim unlimited runtime nesting solely from a preparation fix. |

### Concurrency

| id | status | severity | effort | description |
|---|---|---|---|---|

### Architecture / modularity / SOLID

| id | status | severity | effort | description |
|---|---|---|---|---|

### Plugin extensibility

| id | status | severity | effort | description |
|---|---|---|---|---|

### CLI / option integrity

| id | status | severity | effort | description |
|---|---|---|---|---|

### Configuration discoverability

| id | status | severity | effort | description |
|---|---|---|---|---|

### Data governance

| id | status | severity | effort | description |
|---|---|---|---|---|

### Observability

| id | status | severity | effort | description |
|---|---|---|---|---|

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
| DOC-011 | blocked | low | small | Documentation/task contradiction: this item's former direction was to correct the shared-cache comment in `registry_with_entry_points`, but approved PLUG-006 deletes that function. Both instructions target the same disappearing code and would create a redundant edit/commit. Blocked on PLUG-006's deletion; no standalone comment rewrite or compatibility restoration. The current comment is indeed false because `catalog.generators()` deep-copies its snapshot. Remove this row when PLUG-006 removes the function and its comment; do not report the underlying work complete before then. |

## Rejected / Won't fix

| id | status | severity | effort | description |
|---|---|---|---|---|
