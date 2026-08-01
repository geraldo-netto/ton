# TODO

Open review findings tracked per categories in
[`AGENTS.md`](AGENTS.md). Closed items live in commit history.

Status values: `open`, `in-progress`.
Effort values: `S` (<=1h), `M` (1-4h), `L` (>4h).

Resource policy: TON is a batch-processing system. Do not reject valid jobs or
impose hard CPU, memory, row-width, expansion, pool-size, or precision caps.
Prefer streaming, lazy evaluation, chunking, spill-to-disk, and explicit
operator-controlled settings that do not introduce restrictive defaults.

Last full rescan: 2026-08-01 (all categories; cache/build files and directories excluded).

## security

| id | status | effort | description |
|----|--------|--------|-------------|
| SEC-007 | open | L | Replace `RegexGenerator.prove()`'s user-pattern `re.fullmatch()` with a ReDoS-resilient matcher whose worst-case work is bounded polynomially, preferably a Thompson NFA/automaton over TON's prepared AST. `(a+)+$` shows exponential rejection growth, and a one-row `(a+)+^` config exceeded a 3-second subprocess timeout in `proof_mode="all"` because generation ignores the internal anchor before proofing. Coordinate anchor semantics with REL-022, cover nested repeats/overlapping alternations/failing suffixes with deterministic complexity regressions, and do not mitigate by imposing pattern, repeat, row-width, or input-length caps. |

## code complexity

| id | status | effort | description |
|----|--------|--------|-------------|

## code duplication

| id | status | effort | description |
|----|--------|--------|-------------|

## reliability/correctness

| id      | status | effort | description |
|---------|--------|--------|-------------|

## performance

| id      | status | effort | description |
|---------|--------|--------|-------------|

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

## configuration discoverability

| id      | status | effort | description |
|---------|--------|--------|-------------|
| CFG-005 | open | M | Validate keys owned by distribution choice wrappers and weighted record entries. Typos such as `weigth` are currently ignored and silently fall back to uniform weight, because extension-key validation stops at the top-level transform/generator and child spec; allow only `weight`/`spec` or `value`/`weight`, with indexed diagnostics and suggestions. |

## data governance

| id     | status | effort | description |
|--------|--------|--------|-------------|
| DG-004 | open | S | Keep plugin-controlled proof reasons out of value-free structured logs by default. `_log_failure()` stores `failure.reason` in `LogRecord.extra`; a plugin can echo `result.value` there even though architecture/docs promise proof logs contain identifiers rather than raw generated values. Omit or sanitize the log field independently of the opt-in proof-report payload, and add a regression that inspects all record attributes rather than only `getMessage()`. |

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
| DOC-002 | open | S | Align the README development type-check command with the enforced scope. `mypy ton tests` currently fails with three test-suite errors, while CI and `.githooks/pre-commit` run only `mypy ton`; either fix/type-check tests in both gates or document the actual `mypy ton` contract, then add a drift check for the documented commands. |
| DOC-003 | open | S | Remove or reword stale `TODO <id>` annotations that refer to already-closed findings absent from `TODO.md` (for example `TODO PERF-007`, `TODO ARCH-005`, and `TODO CONC-003`). They currently look like untracked open work despite this file stating that closed items live in commit history; retain issue provenance without the `TODO` marker or maintain an explicit closed index. |
