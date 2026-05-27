# TODO

Open review findings tracked per the categories defined in
[`AGENTS.md`](AGENTS.md). Closed items live in the commit history.

Status values: `open`, `in-progress`.
Effort values: `S` (≤1h), `M` (1-4h), `L` (>4h).

## security

| id      | status | effort | description |
|---------|--------|--------|-------------|
| SEC-003 | open   | M      | `registry_with_entry_points()` (ton/_registry.py) loads every `ton.generators` entry-point factory unconditionally. A typosquatted or hijacked package installed alongside TON could inject arbitrary code via `factory()`. Add `include_entry_points=False` opt-out and an `allowlist` argument; CLI default should be secure (`--entry-points` to opt in). |

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

## reliability / correctness

_All previously-open reliability items closed in this round._

## observability

_All previously-open observability items closed in this round._
