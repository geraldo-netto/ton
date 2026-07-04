# TODO

Open review findings tracked per the categories defined in
[`AGENTS.md`](AGENTS.md). Closed items live in the commit history.

Status values: `open`, `in-progress`.
Effort values: `S` (<=1h), `M` (1-4h), `L` (>4h).

Last full rescan: 2026-07-04.

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
| REL-020 | open | M | `decimal.py:50-53` rounds `rng.uniform(min,max)` half-up, so a `maxValue` off the rounding grid overflows the range (e.g. `min=0,max=0.99,decimals=0` emits `"1"` ~half the time). Clamp the rounded result to `[min,max]`, or round endpoints inward at prepare and reject an empty range. |
| REL-022 | open | M | `regex.py` empty/unsatisfiable character classes (`[^ -~]`, reversed `[z-a]`) prepare cleanly then raise mid-`generate()` on row N. Force pool resolution for every `IN` node at `prepare` so a bad config fails at engine construction. |
| REL-023 | open | M | `_config.py:_validate_encoding` accepts any codec `codecs.lookup` knows, including non-text ones (`base64`, `hex`, `rot13`); `--validate` reports the config valid, then the real run raises `LookupError` at `open(encoding=...)`. Reject codecs where `CodecInfo._is_text_encoding` is false. |

## performance

| id      | status | effort | description |
|---------|--------|--------|-------------|
| PERF-013 | open | M | Weighted hot path (`weighted.py:109` legacy form and `transforms/distribution.py:33` `WeightedChoiceSet.choose`) calls `rng.choices(..., weights=...)` per row, which rebuilds the cumulative-weight list every draw. Precompute `cum_weights` once at prepare time and pass `cum_weights=` (or use `bisect`) to make each draw O(log n) with no per-row allocation. |

## scalability

| id | status | effort | description |
|----|--------|--------|-------------|
| SCALE-006 | open | M | `hash.py:41-45` precomputes a bcrypt digest for the whole word pool at prepare time with `rounds` allowed up to 31 (`2^31` iterations/word), so a tiny config stalls engine construction regardless of `rows`. Cap effective rounds lower or hash lazily. |

## concurrency

| id | status | effort | description |
|----|--------|--------|-------------|

## robustness/recovery

| id | status | effort | description |
|----|--------|--------|-------------|
| ROB-002 | open | M | `_regex_parse.py` recurses on nested groups with no depth guard; a deeply nested pattern raises an uncaught `RecursionError` instead of `RegexParseError`, escaping the config-error path. Cap nesting depth (or pattern length) in the parser. |

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
| CLI-003 | open | M | The `encoding` config key only reaches file output (`_open_output` passes it to the temp file); when writing to stdout (`args.output is None`) the CLI yields `sys.stdout` unchanged, so a non-UTF-8 `encoding` is silently ignored. Reconfigure the stdout stream (or document that `encoding` applies to `-o` only). |

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
| DOC-004 | open | S | Built-in `identity` transform (registered in `_registry.build_extension_catalog`, surfaced by `--list-namespaces`) is undocumented; README/architecture only mention `distribution`. Describe it or note it is an internal pass-through. |
| DOC-005 | open | S | README:424 says only `lmhash` is rejected as a composite child, but `hash` is also paired (`is_paired=True`) and equally rejected; the later "Paired references" section already says "hash and lmhash". Change to "(`hash`, `lmhash`)". |
| DOC-006 | open | S | `_registry.py:387` `make_registry` docstring says "the 19 generators it does not need"; there are 23 built-ins (README correctly says twenty-three). Update or make count-agnostic. |
| DOC-007 | open | S | `_datetime.py` `_BARE_OFFSET` comment claims it normalizes offsets like `-0530`, but the regex `([+-]\d{2})$` only rewrites hour-only tails; 4-digit offsets are untouched. Fix the comment. |
| DOC-008 | open | S | `timestamp_unix.py` `millis` unit multiplies a second-resolution epoch by 1000, so millisecond output always ends in `000` — the draw has no sub-second precision. Note the limitation (or draw true milliseconds). |
