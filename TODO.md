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
| SCAL-002 | open | M | Remove the fixed `MAX_UNBOUNDED_REPEAT = 8` expansion ceiling from the regex generator. It silently narrows every valid `*`, `+`, and `{n,}` pattern, contrary to TON's operator-controlled batch resource policy; use a terminating distribution with unbounded support or an explicit operator setting that does not impose a restrictive default, and document/test seeded behavior. |
| SCAL-003 | open | M | Prevent `DigestPairSpec.cache`/`BcryptPairSpec.cache` from growing to one digest per selected pool value during long runs. Cheap hashes need no duplicate full-pool cache, while expensive bcrypt needs an operator-controlled or spillable strategy rather than an implicit process-lifetime dictionary; retain deterministic output and avoid a hard pool-size cap. |

## concurrency

| id | status | effort | description |
|----|--------|--------|-------------|

## robustness/recovery

| id | status | effort | description |
|----|--------|--------|-------------|
| ROB-001 | open | M | Add crash-recovery handling for same-directory `.<basename>.*.tmp` output/proof files. Context-manager cleanup covers Python exceptions and interrupts, but process termination or power loss leaves staged files indefinitely; define ownership/age metadata and a concurrency-safe inspect/reconcile path so later runs can report or clean stale artifacts without deleting a live writer's file. |

## architecture/modularity/SOLID

| id       | status | effort | description |
|----------|--------|--------|-------------|
| ARCH-006 | open | M | Expose the streaming proof-failure sink through the public engine/API option model. The only attachment point is private `Engine._set_proof_failure_sink()`, so library callers cannot consume every audit failure in bounded memory without relying on internals, even though `EngineOptions` is the public construction boundary. Add the public type/option, lifecycle validation, docs, and tests. |

## decoupling

| id      | status | effort | description |
|---------|--------|--------|-------------|

## business/design patterns/DDD

| id | status | effort | description |
|----|--------|--------|-------------|

## plugin extensibility

| id       | status | effort | description |
|----------|--------|--------|-------------|
| PLUG-005 | open | M | Report and fail unsatisfied explicit entry-point selectors. A typoed or uninstalled `--entry-point GROUP:DISTRIBUTION:NAME` currently yields no candidate, no summary, and a successful `--list-namespaces`/core-only run; distinguish exact-selector missing/load-failed outcomes from broad `--entry-points` failure isolation and surface them through the catalog API and CLI. |

## CLI / option integrity

| id      | status | effort | description |
|---------|--------|--------|-------------|
| CLI-003 | open | S | Allow `--redact-proof-failures` to protect strict proof diagnostics and structured logs without requiring `--proof-report` (which also forces audit mode). The engine already supports redaction independently, but the CLI argument gate prevents users of `--proof-check=sample/all` from selecting it; align validation, help, README, and exit-path tests. |

## configuration discoverability

| id      | status | effort | description |
|---------|--------|--------|-------------|
| CFG-004 | open | S | Reject JSON booleans as weights in every weighted/distribution shape. `float(True)` and `float(False)` currently accept them as `1.0`/`0.0` despite the documented numeric contract; centralize coercion so composite choices, parallel arrays, and record values produce the same path-aware error. |
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
