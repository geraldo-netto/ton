# TODO

## Open

### Performance

| id | status | severity | effort | description |
|---|---|---|---|---|
| PERF-051 | open | medium | medium | Performance: reduce transient continuation/interner work in `ton/generators/regex.py::_Continuations.push` and the frontier evaluator without losing SCALE-023's memory bound. Saved `benchmarks/results/proofs-comparison.md` shows N=60 regex proofs 76.1% slower despite 91.2% lower runtime allocation. A ten-proof profile of the generated `(?:a?){60}a{60}` value makes 158,150 interner pushes and 69,500 weak-reference insertions/removals. Reuse compact states or specialize suitable transitions; retain exhaustive/nullable/deep/count regressions and the frontier memory test, add structural allocation/work-count coverage, and rerun the saved size sweep with matching fingerprints. |
| PERF-052 | open | medium | small | Performance/benchmark validity: capture the measured source state in `benchmarks/run.py`, not only `git rev-parse HEAD` after all samples. Uncommitted runtime edits are currently labeled as the unchanged commit, and a checkout/edit during the run can mix implementations while equal-output samples still pass. Record a source/worktree fingerprint at the start and verify it remains stable through completion; identify dirty measurements explicitly and retain dependency/environment provenance needed to reproduce them. Add fixture-repository regressions for clean, dirty and mid-run changes without rejecting legitimate dirty-tree benchmarking. |

## Blocked / Deferred

| id | status | severity | effort | description |
|---|---|---|---|---|
| DOC-044 | blocked | low | small | Documentation/policy: the session-supplied AGENTS.md instructions require every contradiction to be blocked, while checked-in AGENTS.md Rules classify known bugs with clear expected behavior as open and reserve blocked for unavailable prerequisites. These sources give conflicting ledger instructions despite the maintainer's earlier request to revise the rule. Align the supplied instruction source with the approved readiness-based policy; unblock when that external instruction source is updated or its replacement is explicitly established. This policy-source synchronization does not prevent implementing the independently actionable findings above. |

## Rejected / Won't fix

| id | status | severity | effort | description |
|---|---|---|---|---|
| PLAT-015 | wont_fix | high | small | Platform: Windows CI verification of the POSIX-only test skip and remaining suite is not required by maintainer decision. |
