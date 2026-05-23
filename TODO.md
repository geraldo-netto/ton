# TODO

Open review findings tracked per the categories defined in
[`AGENTS.md`](AGENTS.md). Closed items live in the commit history.

Status values: `open`, `in-progress`.
Effort values: `S` (≤1h), `M` (1-4h), `L` (>4h).

## security

| id      | status | effort | description |
|---------|--------|--------|-------------|
| SEC-003 | open   | M      | `registry_with_entry_points()` (ton/_registry.py:106) loads every `ton.generators` entry-point factory unconditionally. A typosquatted or hijacked package installed alongside TON could inject arbitrary code via `factory()`. Add `include_entry_points=False` opt-out and an `allowlist` argument; CLI default should be secure (`--entry-points` to opt in). |
| SEC-004 | open   | S      | `registry_with_entry_points()` (ton/_registry.py:108-110) does not wrap `ep.load()` / `factory()` in try/except. One broken third-party plugin kills the whole process. Catch per-entry, emit a `WARNING` via the ton logger, and skip. |
| SEC-005 | open   | S      | CLI `-o/--output` (ton/cli.py:131-138) writes to any path the user passes with no normalization, no symlink check, no `/dev/*` rejection. Acceptable for an interactive tool but worth documenting; consider refusing to overwrite when stdout target is a special file. |
| SEC-006 | open   | S      | The `registry_discovered` log event (ton/_registry.py:83-91) includes the full list of generator type names in `extra={"names": ...}`. Benign today, but a malicious entry-point can poison logs with arbitrary unicode in `ep.value`; sanitize before logging. |

## performance

| id      | status | effort | description |
|---------|--------|--------|-------------|
| PERF-009 | open  | M      | `Engine._render_row` (ton/_engine.py:118-123) allocates a fresh `values` dict and runs `_TOKEN_RE.sub` once per row. For wide rows the regex pass dominates; precomputing token spans during `parse()` and rendering via direct concatenation eliminates the per-row regex overhead. |
| PERF-010 | open  | S      | `_emit` (ton/generators/regex.py:110-114) builds a list and `''.join`s it for every nested AST node. `_emit_repeat` (ton/generators/regex.py:159-164) calls `_emit` per repetition, allocating a fresh list each time. Reuse a single `io.StringIO` or accumulate into the parent's list. |
| PERF-011 | open  | S      | `cli._stream` (ton/cli.py:147-160) stores `["row", "\n", "row", "\n", ...]` and joins when the list grows past `_BATCH_ROWS * 2`. Writing each row + `"\n"` straight to the stream (which is already line-buffered for stdout, block-buffered for files) avoids the list allocation. Benchmark before committing the change. |
| PERF-012 | open  | M      | Every `Engine` construction calls `default_registry()` (ton/_engine.py:38) which instantiates 20 generators even when the template only references one type. Build the registry lazily by type name from `_DEFAULT_CLASSES`. |

## scalability

| id      | status | effort | description |
|---------|--------|--------|-------------|
| SCALE-001 | open | S | `_BATCH_ROWS = 1024` (ton/cli.py:31) is hard-coded. Wide rows (regex / bytes / text) can make the buffered chunk multi-MB; expose `--batch-rows` or scale by row width. |
| SCALE-002 | open | S | `MAX_LITERAL_REPEAT = 10_000` (ton/generators/regex.py:52) lets a single row hold a 10K-character regex expansion. Combined with `MAX_CHAR_LENGTH` and `MAX_BYTES_LENGTH`, one row can exceed 1 MB before any user-visible warning. Document the worst-case row width and consider a global per-row cap. |
| SCALE-003 | open | S | `MAX_ROWS = 1_000_000_000` (ton/_config.py:27) is enforced but there is no checkpoint/resume support, so any run that crashes near the end has to restart from row 0. Add a `--resume-from` flag once SCALE-001 is in place. |
| SCALE-004 | open | M | `Engine.__iter__` (ton/_engine.py:95-116) keeps a `count` only for the logger; the milestone INFO event is the only feedback channel for long-running iterations. Library callers cannot interrupt cleanly without inspecting private state. Expose a public `rows_emitted` property. |

## concurrency

| id      | status | effort | description |
|---------|--------|--------|-------------|
| CONC-002 | open | S | `default_registry()` (ton/_registry.py:80-92) mutates the `_DEFAULT_CLASSES` global with a check-then-assign. Two threads racing on first call duplicate the subclass walk; harmless today (idempotent result) but converts cleanly to a `threading.Lock` or a `functools.cache`-wrapped helper. |
| CONC-003 | open | M | `SequenceGenerator` (ton/generators/sequence.py:36-56) stores `itertools.count()` on the prepared spec. `itertools.count` is **not** thread-safe; an Engine shared across threads can hand out duplicate or skipped ids. Either document the Engine-per-thread contract or wrap the counter in a lock. |
| CONC-004 | open | S | `fork_engine` (ton/concurrency.py:61-72) builds a new Engine but emits no `engine_forked` log event with the worker id, so multi-process runs are indistinguishable in the structured log stream (see OBS-007). |

## code complexity

| id     | status | effort | description |
|--------|--------|--------|-------------|
| CC-001 | open  | S      | `cli._run_inner` (ton/cli.py:101-120) carries two nested try/except blocks plus an `if args.verbose` tail. Splitting the build/exec phases into separate helpers keeps each function under a 5-branch ceiling. |
| CC-002 | open  | S      | `_flatten_in` (ton/generators/regex.py:180-192) handles four `op` cases inline; if more class-element kinds get added the if-chain will hit the C901=10 cap (currently at 4). Convert to a dispatch table like `_EMIT_HANDLERS`. |

## code duplication

| id     | status | effort | description |
|--------|--------|--------|-------------|
| DUP-004 | open | S      | The "`maxValue` must be >= `minValue`" validation is duplicated four times: ton/generators/integer.py:30, ton/generators/decimal.py:31, ton/generators/date.py:49, ton/generators/timestamp_unix.py:46. Extract `_require_min_le_max(type_name, lo, hi)` into `generators/base.py`. |
| DUP-005 | open | S      | The "`X` exceeds `MAX_X`" cap-error pattern repeats in ton/generators/char.py:33-36, ton/generators/bytes.py:49-52, ton/generators/text.py:64-67. Extract `_assert_below_cap(field, value, cap, type_name)`. |
| DUP-006 | open | S      | Every generator's `prepare` re-runs the same `int(spec.get("X", default))` coercion. A small `_coerce_int(spec, key, *, default, allow_negative=False)` helper would absorb the surface area and centralize error messages. |

## architecture / modularity / SOLID

| id      | status | effort | description |
|---------|--------|--------|-------------|
| ARCH-005 | open | M | The default registry walks `Generator.__subclasses__()` (ton/_registry.py:42-51). Any in-process subclass with a non-empty `type_name` ends up in `default_registry()` — including test fixtures (see `tests/test_engine.py` `BrokenGenerator`). Add an explicit allowlist or move discovery to entry points. |
| ARCH-006 | open | S | `ton/cli.py` imports `_engine`, `_config`, and `_logging` directly instead of going through `ton.api`. The CLI is a library consumer; routing through the public facade keeps the private API truly private. |

## decoupling

| id      | status | effort | description |
|---------|--------|--------|-------------|
| DEC-003 | open | S      | `Engine._resolve` (ton/_engine.py:125-134) does an `isinstance(generator, PairedGenerator)` check even though `Generator.is_paired` already exists. Replacing the isinstance with a polymorphic call removes Engine's knowledge of the PairedGenerator subclass hierarchy. |
| DEC-004 | open | S      | `api.generate` (ton/api.py) and `concurrency.fork_engine` (ton/concurrency.py:61-72) duplicate Engine-construction logic. Extract a shared `_build_engine(config, *, rng, registry, milestone_rows)` helper in `_engine.py`. |

## business / design patterns / DDD

| id      | status | effort | description |
|---------|--------|--------|-------------|
| PAT-008 | open  | M      | `hash` generator with `algorithm: md5\|sha1\|sha256\|sha512\|bcrypt`: modern replacement for `lmhash`. Optional `id` paired form already supported by `PairedGenerator`. |
| PAT-009 | open  | S      | `Engine.__init__` now carries four params (`config, registry, rng, milestone_rows`). Convert to a Builder (`Engine.from_config(config).with_rng(...).with_milestone(...)`) or add a `from_file` classmethod that wraps `_config.load` + Engine construction. |
| PAT-010 | open  | M      | Logger events use stringly-typed `event=` values in `extra` (e.g. `"engine_constructed"`, `"engine_milestone"`). Promote to a `LogEvent` enum or a typed dataclass per event so consumers can `match` instead of string-comparing. |

## reliability / correctness

| id      | status | effort | description |
|---------|--------|--------|-------------|
| REL-014 | open | S | `Engine.__iter__` (ton/_engine.py:95-116) has no try/except around `generator.generate` / `generate_pair`. A buggy generator that raises mid-iteration bubbles up to the CLI's top-level `BLE001` net (ton/cli.py:93) and emits a generic `unexpected error` message instead of an identifying log line. |
| REL-016 | open | S | `_open_output` (ton/cli.py:131-138) opens the output path with mode `"w"`, silently overwriting any existing file. Add a `--no-clobber` / `--append` flag or at minimum log when an existing file is overwritten. |
| REL-017 | open | S | `--progress` (ton/cli.py:56-62) accepts negative integers without validation; the milestone modulo math is well-defined but counterintuitive. Reject `<0` in `_build_parser`. |

## observability

| id      | status | effort | description |
|---------|--------|--------|-------------|
| OBS-004 | open | S | `_build_prepared` (ton/_engine.py:76-93) catches every `Exception`, re-raises as `TemplateError`, but never logs which generator/spec triggered the failure. Emit a `WARNING` log record with `event="prepare_failed"`, `type_key`, and `generator_type` before the re-raise. |
| OBS-005 | open | S | `entry_point_loaded` records log `name` and `value` (ton/_registry.py:111-120) but not the distribution name or version of the providing package, so attribution of a misbehaving plugin requires manual mapping. Add `ep.dist.name` / `ep.dist.version`. |
| OBS-006 | open | S | `cli._emit_progress` (ton/cli.py:164-170) writes JSON directly to stderr instead of going through the `ton` logger. Two parallel observability channels for the same milestone make consumers choose, and JSON-on-stderr cannot be filtered by log level. Route through `logger.info(extra={...})`. |
| OBS-007 | open | S | `fork_engine` (ton/concurrency.py:61-72) does not log a `engine_forked` event with `worker_id` / `parent_seed` / `rows`. Multi-process workers are indistinguishable in the structured log stream. |
| OBS-008 | open | S | The CLI's catch-all (ton/cli.py:93-98) prints `"ton: unexpected error: ..."` via `print` instead of `logger.exception(...)`. Stack trace is lost; users with `--log-level debug` still cannot see it. |
