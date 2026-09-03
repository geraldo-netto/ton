# TODO

## Open

| id | status | severity | effort | description |
|---|---|---|---|---|
| DOC-034 | open | low | s | Correct `ton/generators/sequence.py`'s multiprocessing guidance. It tells callers to offset `start` manually for `fork_engine()`, but `fork_engine()` already computes exact sequence offsets, so following the module documentation double-offsets later shards; cover this guidance in documentation tests. |
| DOC-035 | open | low | s | Remove the stale `(TODO CLI-002, CFG-003)` annotation from `ton/cli.py` and make the stale-marker regression match whitespace-separated `TODO` IDs. The current newline after `TODO` bypasses the test even though the referenced work is closed. |

## Blocked / Deferred

| id | status | severity | effort | description |
|---|---|---|---|---|

## Rejected / Won't fix

| id | status | severity | effort | description |
|---|---|---|---|---|
