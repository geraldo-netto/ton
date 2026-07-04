# TODO

Open review findings tracked per the categories defined in
[`AGENTS.md`](AGENTS.md). Closed items live in the commit history.

Status values: `open`, `in-progress`.
Effort values: `S` (<=1h), `M` (1-4h), `L` (>4h).

Last full rescan: 2026-07-04.

## security

| id | status | effort | description |
|----|--------|--------|-------------|
| SEC-010 | open | S | `hash` with `algorithm: bcrypt` derives the salt deterministically from the plaintext (`hash.py`), so identical plaintexts always yield identical digests — bcrypt's per-value salt is defeated and hashes are precomputable. Fine for fixtures but undocumented; add an explicit "not real bcrypt salting" note at the code. |

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
| SCALE-005 | open | S | `sequence.py:57` `padWidth` is uncapped while every other length knob (bytes/char/text/sequence_of) is bounded by a `MAX_*` cap; `padWidth: 10_000_000` makes each row a 10 MB `zfill`. Apply `assert_below_cap` to `padWidth`. |
| SCALE-006 | open | M | `hash.py:41-45` precomputes a bcrypt digest for the whole word pool at prepare time with `rounds` allowed up to 31 (`2^31` iterations/word), so a tiny config stalls engine construction regardless of `rows`. Cap effective rounds lower or hash lazily. |

## concurrency

| id | status | effort | description |
|----|--------|--------|-------------|
| CONC-004 | open | S | `concurrency.py:derive_seed` uses `struct.pack(">qq", parent_seed, worker_id)`, which raises `struct.error` for any seed outside int64 range even though `--seed`/`Random(seed)` accept arbitrary Python ints. `fork_engine` then crashes on a large seed. Reduce the seed modulo 2^64 (or hash its bytes) before packing. |

## robustness/recovery

| id | status | effort | description |
|----|--------|--------|-------------|
| ROB-002 | open | M | `_regex_parse.py` recurses on nested groups with no depth guard; a deeply nested pattern raises an uncaught `RecursionError` instead of `RegexParseError`, escaping the config-error path. Cap nesting depth (or pattern length) in the parser. |
| ROB-003 | open | S | `weighted.py:143-146` record form does `str(item["value"])` with no guard: a record missing `"value"` raises `KeyError`, and a mixed list (dict then bare string) raises `TypeError`, instead of the module's friendly `ValueError`. Validate each record is a mapping containing `"value"`. |

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
| CFG-004 | open | S | Per-field `validators` config key (a list of validator references, wired by PLUG-001 in `_config.py:210-224`) is undocumented in the README type-spec reference — only the `ton.validators` entry-point group is mentioned. Document the key and its shape alongside `transforms`. |

## data governance

| id     | status | effort | description |
|--------|--------|--------|-------------|
| DG-004 | open | S | `base.py:coerce_int` silently truncates numerics: `int(3.9)→3`, `int(True)→1`, so `minValue: 3.9` quietly becomes `3` and masks config typos. Reject non-integral numerics. |

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
| DOC-002 | open | S | README "Flags" table omits `--redact-proof-failures` (defined in `cli.py:120-127`, threaded through `_build_engine`); every other flag is documented. Add the row. |
| DOC-003 | open | S | `--list-namespaces` help text and README say "namespaces, data types, and transforms" but `_print_namespaces` also prints a `validators:` line. Add validators to both. |
| DOC-004 | open | S | Built-in `identity` transform (registered in `_registry.build_extension_catalog`, surfaced by `--list-namespaces`) is undocumented; README/architecture only mention `distribution`. Describe it or note it is an internal pass-through. |
| DOC-005 | open | S | README:424 says only `lmhash` is rejected as a composite child, but `hash` is also paired (`is_paired=True`) and equally rejected; the later "Paired references" section already says "hash and lmhash". Change to "(`hash`, `lmhash`)". |
| DOC-006 | open | S | `_registry.py:387` `make_registry` docstring says "the 19 generators it does not need"; there are 23 built-ins (README correctly says twenty-three). Update or make count-agnostic. |
| DOC-007 | open | S | `_datetime.py` `_BARE_OFFSET` comment claims it normalizes offsets like `-0530`, but the regex `([+-]\d{2})$` only rewrites hour-only tails; 4-digit offsets are untouched. Fix the comment. |
| DOC-008 | open | S | `timestamp_unix.py` `millis` unit multiplies a second-resolution epoch by 1000, so millisecond output always ends in `000` — the draw has no sub-second precision. Note the limitation (or draw true milliseconds). |
