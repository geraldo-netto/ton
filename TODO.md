# TODO

## Open

### Performance

| id | status | severity | effort | description |
|---|---|---|---|---|

### Scalability

| id | status | severity | effort | description |
|---|---|---|---|---|
| SCALE-023 | open | high | large | Scalability: reduce retained backtracking state in `ton/generators/regex.py::_matches`, `_advance_match` and `_advance_repeat`. For pattern `(?:a?){N}a{N}`, actual values generated with `Random(42)` at N=50/100/200 contain 69/145/287 characters, but proof peaks at 1.74/6.98/26.46 MB and takes 0.012/0.044/0.227 s. The matcher stores every visited position/continuation tuple, including repeat-task objects. Use compact/interned continuations, feasible-length pruning and an execution strategy that releases obsolete states. Add deterministic state-growth regressions plus exhaustive small-pattern equivalence for acceptance/rejection, nullable nested repeats, large counted repeats and deep groups, without limiting valid patterns or output lengths. |
| SCALE-024 | open | high | large | Scalability: separate proof metadata from repeated copies of unchanged string payloads in `ton/_pipeline.py::DrawnValue`, `_GeneratedChildValue` and their composite callers. Each `str` subclass wrapper copies the entire child text and retains the prior wrapper through its trace. A single 100,000-character value wrapped in 10/40/80 one-choice `oneOf` levels peaks at 1.11/4.13/8.16 MB in proof-all mode versus about 0.10/0.11/0.11 MB with proofs off. Preserve shared text storage across passthrough traces while retaining exact child ownership and transformed before/after values. Add payload-sharing/allocation-growth regressions covering nested composites, child pipelines, sampling, rejected children and pickle/deepcopy behavior. |

## Blocked / Deferred

| id | status | severity | effort | description |
|---|---|---|---|---|
| DOC-044 | blocked | low | small | Documentation/policy: the session-supplied AGENTS.md instructions require every contradiction to be blocked, while checked-in AGENTS.md Rules classify known bugs with clear expected behavior as open and reserve blocked for unavailable prerequisites. These sources give conflicting ledger instructions despite the maintainer's earlier request to revise the rule. Align the supplied instruction source with the approved readiness-based policy; unblock when that external instruction source is updated or its replacement is explicitly established. This policy-source synchronization does not prevent implementing the independently actionable findings above. |

## Rejected / Won't fix

| id | status | severity | effort | description |
|---|---|---|---|---|
| PLAT-015 | wont_fix | high | small | Platform: Windows CI verification of the POSIX-only test skip and remaining suite is not required by maintainer decision. |
