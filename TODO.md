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
| DOC-009 | open | medium | small | Documentation/test integrity: README and the `ton.api` docstring use `sink.write(row)`, but generated rows contain no added terminator. `test_library_streaming_example_writes_each_row_once` only counts that incorrect literal. Approved direction: show `sink.write(row + "\n")` in both examples and execute the extracted streaming example against a text sink. Acceptance: each generated row appears once with its intended newline boundary; avoid testing only source-text occurrence counts. |
| DOC-012 | open | low | small | Documentation: README's char table calls `maxChar` output length, while `CharGenerator` uses it as draw count and allows multi-character pool strings. Confirmed: `values: ["ab"]`, `maxChar: 2` emits `abab`. Approved direction: document number of draws with replacement and multi-character token semantics; output length is the sum of the selected token lengths. |

## Blocked / Deferred

| id | status | severity | effort | description |
|---|---|---|---|---|

## Rejected / Won't fix

| id | status | severity | effort | description |
|---|---|---|---|---|
