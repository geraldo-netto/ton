# TODO

Open review findings tracked per the categories defined in
[`AGENTS.md`](AGENTS.md). Closed items live in the commit history.

Status values: `open`, `in-progress`.
Effort values: `S` (<=1h), `M` (1-4h), `L` (>4h).

Last full rescan: 2026-06-06.

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

| id | status | effort | description |
|----|--------|--------|-------------|

## performance

| id | status | effort | description |
|----|--------|--------|-------------|

## scalability

| id | status | effort | description |
|----|--------|--------|-------------|

## concurrency

| id | status | effort | description |
|----|--------|--------|-------------|

## robustness/recovery

| id | status | effort | description |
|----|--------|--------|-------------|

## architecture/modularity/SOLID

| id | status | effort | description |
|----|--------|--------|-------------|

## decoupling

| id | status | effort | description |
|----|--------|--------|-------------|

## business/design patterns/DDD

| id      | status | effort | description |
|---------|--------|--------|-------------|
| PAT-008 | open   | M      | Add a generic `hash` generator with `algorithm: md5\|sha1\|sha256\|sha512\|bcrypt` (later: argon2, scrypt). Keep `lmhash` as-is -- it stays the Windows NT-hash specialty. New `hash` should reuse `PairedGenerator` so `$word[id]$` returns the plaintext like `lmhash` already does. |

## plugin extensibility

| id | status | effort | description |
|----|--------|--------|-------------|

## CLI / option integrity

| id | status | effort | description |
|----|--------|--------|-------------|

## configuration discoverability

| id | status | effort | description |
|----|--------|--------|-------------|

## data governance

| id | status | effort | description |
|----|--------|--------|-------------|

## dependency

| id | status | effort | description |
|----|--------|--------|-------------|

## platform

| id | status | effort | description |
|----|--------|--------|-------------|

## observability

| id | status | effort | description |
|----|--------|--------|-------------|

## documentation

| id | status | effort | description |
|----|--------|--------|-------------|
