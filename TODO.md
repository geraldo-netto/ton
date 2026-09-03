# TODO

## Open

| id | status | severity | effort | description |
|---|---|---|---|---|
| SEC-022 | open | medium | m | Sanitize or reject every entry-point-derived value before logging it. Unicode-confusable entry-point identifiers pass `_validate_identifier()` and are emitted raw by `plugin_registered`, while distribution names and versions reach entry-point log messages and structured fields without `_sanitize_for_log()`, contradicting the documented printable-ASCII logging contract. |
| REL-037 | open | low | s | Align the public `Mapping` input contract with runtime validation. `api.generate()` and `Engine` annotate configs as `Mapping[str, Any]`, but `_validate_root()` and nested validators require concrete `dict` objects, causing valid read-only/custom mappings such as `MappingProxyType` to fail before generation. |
| CLI-021 | open | low | s | Classify non-UTF-8 JSON as invalid configuration instead of an unexpected internal error. `api.load_config()` lets `UnicodeDecodeError` escape and the CLI returns exit 3, despite the documented exit-2 contract for invalid configs; map decode failures with a focused CLI regression. |
| DOC-034 | open | low | s | Correct `ton/generators/sequence.py`'s multiprocessing guidance. It tells callers to offset `start` manually for `fork_engine()`, but `fork_engine()` already computes exact sequence offsets, so following the module documentation double-offsets later shards; cover this guidance in documentation tests. |
| DOC-035 | open | low | s | Remove the stale `(TODO CLI-002, CFG-003)` annotation from `ton/cli.py` and make the stale-marker regression match whitespace-separated `TODO` IDs. The current newline after `TODO` bypasses the test even though the referenced work is closed. |

## Blocked / Deferred

| id | status | severity | effort | description |
|---|---|---|---|---|

## Rejected / Won't fix

| id | status | severity | effort | description |
|---|---|---|---|---|
