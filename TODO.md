# TODO

Open review findings tracked per the categories defined in
[`AGENTS.md`](AGENTS.md). Closed items live in the commit history.

Status values: `open`, `in-progress`.
Effort values: `S` (≤1h), `M` (1-4h), `L` (>4h).

## security

| id      | status | effort | description |
|---------|--------|--------|-------------|
| SEC-003 | open   | M      | `registry_with_entry_points()` loads every `ton.generators` entry-point factory unconditionally. A typosquatted or hijacked package installed alongside TON could inject arbitrary code via `factory()`. Add an opt-out flag (`include_entry_points=False`) call path in CLI, plus an `allowlist` argument for restricting which names are loaded. CLI default should be secure (`--entry-points` to opt in). |
| SEC-004 | open   | S      | `registry_with_entry_points()` does not wrap `ep.load()` / `factory()` in try/except. A single broken third-party plugin (import error, constructor raises, returns wrong type) kills the whole process. Catch per-entry, log a warning, and skip. |

## business / design patterns / DDD

| id      | status | effort | description |
|---------|--------|--------|-------------|
| PAT-008 | open   | M      | `hash` generator with `algorithm: md5\|sha1\|sha256\|sha512\|bcrypt`: modern replacement for `lmhash`. Optional `id` paired form already supported by `PairedGenerator`. |

## observability

| id      | status | effort | description |
|---------|--------|--------|-------------|
| OBS-003 | open  | S      | No `logging` instrumentation. CLI users get `--verbose` / `--progress`, but library callers have to monkey-patch or wrap the Engine to observe row rate, validation failures, or entry-point loading. Add a `ton` logger with structured INFO events for engine construction, row count milestones, and entry-point discovery; CLI flags can then attach a handler that prints to stderr. |
