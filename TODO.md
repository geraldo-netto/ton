# TODO

Reviewed 2026-09-07 against the current code and implemented in full: all 43 open
items were resolved, one commit each, with regression coverage. The tables below are
empty; add new findings under the matching category.

Approved direction: remove obsolete contracts and spec forms. Do not restore
compatibility, add shims, or introduce deprecation/migration layers.

Residual limitation from SCALE-007: preparation and row generation descend once per
nesting level through the published extension contract, so composite nesting depth is
bounded by the process stack (about 1024 levels on a default 8 MB stack, raised with
`ulimit -s`). Discovery, key validation and config snapshotting are iterative and
have no ceiling. TON reports the operator remedy rather than faulting.

## Open

### Reliability / correctness

| id | status | severity | effort | description |
|---|---|---|---|---|

### Scalability

| id | status | severity | effort | description |
|---|---|---|---|---|

### Concurrency

| id | status | severity | effort | description |
|---|---|---|---|---|

### Architecture / modularity / SOLID

| id | status | severity | effort | description |
|---|---|---|---|---|

### Plugin extensibility

| id | status | severity | effort | description |
|---|---|---|---|---|

### CLI / option integrity

| id | status | severity | effort | description |
|---|---|---|---|---|

### Configuration discoverability

| id | status | severity | effort | description |
|---|---|---|---|---|

### Data governance

| id | status | severity | effort | description |
|---|---|---|---|---|

### Observability

| id | status | severity | effort | description |
|---|---|---|---|---|

### Documentation

| id | status | severity | effort | description |
|---|---|---|---|---|

## Blocked / Deferred

| id | status | severity | effort | description |
|---|---|---|---|---|

## Rejected / Won't fix

| id | status | severity | effort | description |
|---|---|---|---|---|
