# TODO

Reviewed 2026-09-07 against the current code; runtime probes used CPython 3.11.15 with the default 4,300-digit conversion limit. This pass corrects the ledger only. Implementation findings remain pending; no source fixes are claimed.

Approved direction: remove obsolete contracts and spec forms. Do not restore compatibility, add shims, or introduce deprecation/migration layers. Existing approved resolutions remain open; unresolved conflicts in proposed fixes or overlapping tasks are blocked below.

Order related implementation work deliberately: REL-020 before CFG-004 and root distribution proof coverage; ARCH-007 before SCALE-008; coordinate SCALE-005, CFG-006, and CFG-007 around shared numeric handling. Resolve ARCH-006's snapshot boundary before SCALE-007, which remains last in the implementation pass. Each independently completed implementation item still gets its own commit.

DOC-003/004/005 share one executable README-example helper: introduce it once and extend coverage per item, so individual commits do not depend on fixing another stale block first. Once all three are corrected, check every documented spec/output pair with the stated four-row config and `--seed 1`. This audit ran 24 such pairs; exactly those three differed.

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
