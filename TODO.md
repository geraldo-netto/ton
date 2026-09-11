# TODO

## Open

### Performance

| id | status | severity | effort | description |
|---|---|---|---|---|
| PERF-051 | open | medium | medium | Performance: reduce transient continuation/interner work in `ton/generators/regex.py::_Continuations.push` and the frontier evaluator without losing SCALE-023's memory bound. Saved `benchmarks/results/proofs-comparison.md` shows N=60 regex proofs 76.1% slower despite 91.2% lower runtime allocation. A ten-proof profile of the generated `(?:a?){60}a{60}` value makes 158,150 interner pushes and 69,500 weak-reference insertions/removals. Reuse compact states or specialize suitable transitions; retain exhaustive/nullable/deep/count regressions and the frontier memory test, add structural allocation/work-count coverage, and rerun the saved size sweep with matching fingerprints. |

## Blocked / Deferred

| id | status | severity | effort | description |
|---|---|---|---|---|
| DOC-044 | blocked | low | small | Documentation/policy: the session-supplied AGENTS.md instructions require every contradiction to be blocked, while checked-in AGENTS.md Rules classify known bugs with clear expected behavior as open and reserve blocked for unavailable prerequisites. These sources give conflicting ledger instructions despite the maintainer's earlier request to revise the rule. Align the supplied instruction source with the approved readiness-based policy; unblock when that external instruction source is updated or its replacement is explicitly established. This policy-source synchronization does not prevent implementing the independently actionable findings above. |

## Rejected / Won't fix

| id | status | severity | effort | description |
|---|---|---|---|---|
| PLAT-015 | wont_fix | high | small | Platform: Windows CI verification of the POSIX-only test skip and remaining suite is not required by maintainer decision. |
