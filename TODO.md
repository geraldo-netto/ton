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

_All previously-open performance items closed in this round._

## scalability

_All previously-open scalability items closed in this round._

## concurrency

_All previously-open concurrency items closed in this round._

## code complexity

_All previously-open complexity items closed in this round._

## code duplication

_All previously-open duplication items closed in this round._

## architecture / modularity / SOLID

_All previously-open architecture items closed in this round._

## decoupling

_All previously-open decoupling items closed in this round._

## business / design patterns / DDD

| id      | status | effort | description |
|---------|--------|--------|-------------|
| PAT-008 | open  | M      | `hash` generator with `algorithm: md5\|sha1\|sha256\|sha512\|bcrypt`: modern replacement for `lmhash`. Optional `id` paired form already supported by `PairedGenerator`. |
| PAT-010 | open  | M      | Logger events use stringly-typed `event=` values in `extra` (e.g. `"engine_constructed"`, `"engine_milestone"`). Promote to a `LogEvent` enum or a typed dataclass per event so consumers can `match` instead of string-comparing. |
| PAT-011 | open  | M      | `Generator.is_composite` + `prepare_composite` is the Composite pattern entry point. Today only `weighted` uses it. A `oneOf` / `union` generator (any spec wrapped, no weights) and a `sequence_of` generator (fixed N draws from a child type joined by a separator) would round out the composition surface using the same hook. |

## reliability / correctness

| id      | status | effort | description |
|---------|--------|--------|-------------|
| REL-018 | open | S | `cli._stream` (ton/cli.py:_stream) accepts `--resume-from` values >= the total row count and silently produces an empty output file. Validate against `engine._rows` (or log a WARNING) so users notice the run produced nothing. |
| REL-019 | open | S | `Weighted` composite generator returns `child.generate(prepared, rng)` for paired child generators (ton/generators/weighted.py:_prepare_choice). The paired contract (`$name[id]$`) is silently lost when a paired type is nested inside `weighted`. Document the restriction or reject paired nested specs explicitly. |

## observability

_All previously-open observability items closed in this round._
