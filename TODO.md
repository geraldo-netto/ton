# TODO

## Open

### Reliability / correctness

| id | status | severity | effort | description |
|---|---|---|---|---|
| REL-057 | open | high | medium | Reliability/correctness: keep source containers alive while `ton/_specsnapshot.py::snapshot_spec` uses their IDs as memo keys. A `Mapping` whose `__getitem__(k)` returns a fresh `{'value': k}` snapshots keys 0–19 as values `[0,0,2,2,...,18,18]`: completed source dictionaries are freed and later children reuse their IDs, silently acquiring unrelated snapshots. Preserve real aliases/cycles while preventing false aliases for computed mappings/sequences. Add permanent mutable/immutable snapshot regressions using ephemeral children, plus an Engine/plugin metadata integration case; retain the lazy-width allocation tests. |
| REL-058 | open | medium | medium | Reliability/correctness: stop root strict proof evaluation at the first failed proof in `ton/_proofcheck.py::build_failures/evaluate`. A source returning `ProofResult(False, 'first rejection')` followed by a transform whose proof raises currently produces `ProofEvaluationError` for the later hook, masking the original rejection and changing the CLI outcome from proof failure to unexpected pipeline failure. Nested pipelines already stop at their first rejection. Add all/sample regressions asserting the original failure and no later proof calls, while preserving audit collection of every stage and existing proof-before-validator ordering. |
| REL-059 | open | medium | medium | Reliability/correctness: isolate mutable opaque plugin settings in `ton/_specsnapshot.py::snapshot_spec`; its scalar fallback currently retains caller-owned `bytearray`, sets and custom objects. Confirmed: construct an Engine whose plugin reads `spec['blob']`, mutate the original `bytearray(b'before')` to `b'after'`, and the Engine emits `after`. Copy supported opaque values without interpreting them as child specs, using a coherent memo to preserve aliases/cycles and clear errors for uncopyable state. Add permanent caller-mutation and cross-Engine isolation regressions, including mutable opaque state nested in audit snapshots. |
| REL-060 | open | low | small | Reliability/correctness: preserve proof support for string subclasses in `ton/_pool.py::StringPool.__contains__`. A `str` subclass overriding equality with `str.__eq__` and therefore having `__hash__ = None` previously worked with tuple membership; `StringGenerator.prove` now raises `TypeError` for an equal configured value. Keep the indexed fast path for ordinary strings and a correct fallback for valid unhashable string inputs. Add permanent accepting/rejecting source and paired-plaintext proof regressions without changing ordered sampling or duplicate weights. |
| REL-061 | open | medium | medium | Reliability/correctness: avoid overflowing timezone conversion of date proof bounds in `ton/generators/date.py::_matching_dates/_time_in_bounds`. Bounds `2024-01-01T00:00:00+02:00` through `9999-12-31T23:59:59+00:00` prepare successfully and seed 42 generates `3063-09-28 23:11:25`, but its proof raises `OverflowError` when converting the upper bound to the lower bound's timezone. Compare interval endpoints without constructing an out-of-calendar datetime. Add permanent upper/lower calendar-edge offset cases for valid and rejected values, partial formats and Engine proof modes. |

### Robustness / recovery

| id | status | severity | effort | description |
|---|---|---|---|---|
| ROB-015 | open | medium | small | Robustness/recovery: handle short writes in `ton/_proofaudit.py::_write_chunks` before marking a spec emitted. A sink that stores `text[:1]` and returns `1` makes a complete failure record become only `{`, yet `ProofAuditWriter` reports success and adds its fingerprint to `_emitted_specs`. Drain the unwritten suffix, fail clearly on zero/invalid progress, and commit fingerprint state only after the complete newline-terminated record. Add permanent partial-progress, zero-progress and later-error tests while retaining bounded chunk sizes and exact serialized bytes. |

### CLI / option integrity

| id | status | severity | effort | description |
|---|---|---|---|---|
| CLI-023 | open | medium | small | CLI/option integrity: map config-read `OSError` failures consistently in `ton/cli.py::_map_config_errors`. Only `FileNotFoundError` is handled there; a `PermissionError` reading an existing config during normal generation or `--validate` reaches the unexpected-error safety net and exits 3 instead of the input/output error path (1). Add permanent injected permission/read-I/O failures asserting exit code, concise diagnostic and one `cli_failed` event with zero rows; preserve exit 2 for malformed config content. |

### Performance

| id | status | severity | effort | description |
|---|---|---|---|---|
| PERF-051 | open | medium | medium | Performance: reduce transient continuation/interner work in `ton/generators/regex.py::_Continuations.push` and the frontier evaluator without losing SCALE-023's memory bound. Saved `benchmarks/results/proofs-comparison.md` shows N=60 regex proofs 76.1% slower despite 91.2% lower runtime allocation. A ten-proof profile of the generated `(?:a?){60}a{60}` value makes 158,150 interner pushes and 69,500 weak-reference insertions/removals. Reuse compact states or specialize suitable transitions; retain exhaustive/nullable/deep/count regressions and the frontier memory test, add structural allocation/work-count coverage, and rerun the saved size sweep with matching fingerprints. |
| PERF-052 | open | medium | small | Performance/benchmark validity: capture the measured source state in `benchmarks/run.py`, not only `git rev-parse HEAD` after all samples. Uncommitted runtime edits are currently labeled as the unchanged commit, and a checkout/edit during the run can mix implementations while equal-output samples still pass. Record a source/worktree fingerprint at the start and verify it remains stable through completion; identify dirty measurements explicitly and retain dependency/environment provenance needed to reproduce them. Add fixture-repository regressions for clean, dirty and mid-run changes without rejecting legitimate dirty-tree benchmarking. |

### Scalability

| id | status | severity | effort | description |
|---|---|---|---|---|
| SCALE-027 | open | high | medium | Scalability: detach completed proof traces before retaining/exporting diagnostic values in `ton/_proofcheck.py::_make_failure`. A composite that draws a newly allocated 100,000-character child, then returns `x`, stores the entire child graph through each failure's `DrawnValue`; 10/100 audit failures retain approximately 1.01/10.10 MB despite one-character visible values. Store plain diagnostic strings once proof evaluation finishes, retaining exact value/id/reason/spec and redaction behavior. Add permanent weak-reference or retained-allocation regressions for composites and transformed children, including strict errors and streamed/retained audit records; do not reduce the sample boundary or cap child sizes. |

## Blocked / Deferred

| id | status | severity | effort | description |
|---|---|---|---|---|
| DOC-044 | blocked | low | small | Documentation/policy: the session-supplied AGENTS.md instructions require every contradiction to be blocked, while checked-in AGENTS.md Rules classify known bugs with clear expected behavior as open and reserve blocked for unavailable prerequisites. These sources give conflicting ledger instructions despite the maintainer's earlier request to revise the rule. Align the supplied instruction source with the approved readiness-based policy; unblock when that external instruction source is updated or its replacement is explicitly established. This policy-source synchronization does not prevent implementing the independently actionable findings above. |

## Rejected / Won't fix

| id | status | severity | effort | description |
|---|---|---|---|---|
| PLAT-015 | wont_fix | high | small | Platform: Windows CI verification of the POSIX-only test skip and remaining suite is not required by maintainer decision. |
