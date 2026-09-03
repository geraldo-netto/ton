# TODO

## Open

| id | status | severity | effort | description |
|---|---|---|---|---|
| SEC-007 | open | medium | l | Replace `RegexGenerator.prove()`'s user-pattern `re.fullmatch()` with a ReDoS-resilient matcher over the prepared AST. Failing suffixes against patterns such as `(a+)+$` still trigger exponential backtracking; cover nested repeats and overlapping alternations without imposing pattern, repeat, row-width, or input-length caps. |
| SEC-022 | open | medium | m | Sanitize or reject every entry-point-derived value before logging it. Unicode-confusable entry-point identifiers pass `_validate_identifier()` and are emitted raw by `plugin_registered`, while distribution names and versions reach entry-point log messages and structured fields without `_sanitize_for_log()`, contradicting the documented printable-ASCII logging contract. |
| REL-033 | open | high | m | Include transform-owned child generator types in lazy registry discovery. The documented `distribution` transform with a `string` source and an `integer` choice passes `validate_config()` but normal `Engine`/CLI generation fails with `references unknown type 'integer'`; add a transform discovery hook and parity regressions. |
| REL-034 | open | high | m | Reject or correctly implement regex constructs whose vendored-parser semantics diverge from Python regex semantics. Patterns such as `[^]` and `[\d-a]` pass preparation but are invalid to `re`, while `a{,2}` is emitted literally although `re` treats it as a quantifier; ensure every accepted pattern generates values satisfying its stated regex. |
| REL-035 | open | medium | l | Make `DateGenerator.prove()` enforce the configured interval and calendar relationships, not only per-directive text shapes. An out-of-range value such as `2099-12-31` passes a `2024-01-01..2024-01-02` `%Y-%m-%d` proof, so proof modes cannot detect bounded-date generation faults. |
| REL-036 | open | medium | m | Make `SequenceGenerator.prove()` verify the configured start/step progression as well as integer syntax and padding. The prepared spec discards start/step metadata, so arbitrary values such as `-999` pass proof for a sequence starting at 10 with step 2. |
| REL-037 | open | low | s | Align the public `Mapping` input contract with runtime validation. `api.generate()` and `Engine` annotate configs as `Mapping[str, Any]`, but `_validate_root()` and nested validators require concrete `dict` objects, causing valid read-only/custom mappings such as `MappingProxyType` to fail before generation. |
| CLI-021 | open | low | s | Classify non-UTF-8 JSON as invalid configuration instead of an unexpected internal error. `api.load_config()` lets `UnicodeDecodeError` escape and the CLI returns exit 3, despite the documented exit-2 contract for invalid configs; map decode failures with a focused CLI regression. |
| PERF-038 | open | medium | m | Cache proof-audit spec fingerprints per prepared field/report. `ProofAuditWriter` serializes and SHA-256-hashes the same potentially large field spec for every failure merely to rediscover an existing `spec_ref`, leaving proof-report CPU proportional to failures multiplied by spec size even though the spec payload is emitted once. |
| DG-004 | open | medium | s | Keep plugin-controlled proof reasons out of value-free structured logs by default. `_log_failure()` stores `failure.reason` in `LogRecord.extra`, allowing a plugin to echo a generated value even though the architecture and README promise proof logs contain identifiers rather than raw values; omit or sanitize the field independently of proof-report payloads. |
| DOC-034 | open | low | s | Correct `ton/generators/sequence.py`'s multiprocessing guidance. It tells callers to offset `start` manually for `fork_engine()`, but `fork_engine()` already computes exact sequence offsets, so following the module documentation double-offsets later shards; cover this guidance in documentation tests. |
| DOC-035 | open | low | s | Remove the stale `(TODO CLI-002, CFG-003)` annotation from `ton/cli.py` and make the stale-marker regression match whitespace-separated `TODO` IDs. The current newline after `TODO` bypasses the test even though the referenced work is closed. |

## Blocked / Deferred

| id | status | severity | effort | description |
|---|---|---|---|---|

## Rejected / Won't fix

| id | status | severity | effort | description |
|---|---|---|---|---|
