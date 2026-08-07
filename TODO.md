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

Targeted SonarCloud review: 2026-08-07 (all 133 open findings for `geraldo-netto_ton`, analyzed revision `52f8119`; grouped below by independently verifiable rule family).

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
| SONAR-REL-002 | open | L | `tests/test_api.py:238,443`; `tests/test_bytes_generator.py:53,58`; `tests/test_composite_generators.py:99,233`; `tests/test_config.py:188,196,203`; `tests/test_core_proofs.py:114`; `tests/test_coverage_fillers.py:194,202,242`; `tests/test_coverage_full.py:567`; `tests/test_engine.py:148,168,185,205,466,493`; `tests/test_generators.py:45,81,86,91,96,101,106,111,177,183,233,269,344,349,355,365,384,457,463,469,477`; `tests/test_identity_generators.py:29,44,68`; `tests/test_network_generators.py:45,78,83`; `tests/test_proof_audit.py:149,165,321`; `tests/test_regex_generator.py:44,49,76,124,143,149`; `tests/test_registry.py:301,331,344,349,369`; `tests/test_scale_bounds.py:107`; `tests/test_sequence_generator.py:32,37`; `tests/test_text_generator.py:37,42`; `tests/test_uuid_generator.py:51`; `tests/test_validators.py:60,91,103,109`; `tests/test_weighted_generator.py:42,47,54,68,73,78,83,88,94,99,111,217,309,323` — scope all 85 `python:S5778` exception assertions to one potentially raising invocation. This stays one mechanical diagnostics group; splitting it would create artificial work and partial rule compliance. |

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
