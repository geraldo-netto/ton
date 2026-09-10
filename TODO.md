# TODO

## Open

### Reliability / correctness

| id | status | severity | effort | description |
|---|---|---|---|---|
| REL-055 | open | medium | medium | Reliability/correctness: preserve nested generator exception attribution through composite execution. A generator raising `RuntimeError` reports `GeneratorExecutionError` with its own class at the root, but reports `OneOfGenerator` inside oneOf and becomes `TransformExecutionError(reference='distribution')` inside a distribution candidate. Preserve the failing generator's public error type/reference and original cause; add permanent root/nested API and row-context regressions before fixing. |
| REL-056 | open | medium | medium | Reliability/correctness: preserve nested transform exception attribution in `ChildPipelineGenerator._generate_steps` and engine error translation. A transform raising `RuntimeError` produces `TransformExecutionError(reference='crash')` at the root, but becomes `GeneratorExecutionError(reference='OneOfGenerator')` inside oneOf or is attributed to the outer distribution transform. Add permanent root/nested regressions for public error type, transform reference, cause and row log context before fixing. |

### Observability

| id | status | severity | effort | description |
|---|---|---|---|---|
| OBS-032 | open | medium | medium | Observability: retain the originating nested proof hook's stage/reference across `ChildPipelineGenerator._prove_steps`, composite proof traversal and `ProofChecker`. A transform proof raising `RuntimeError` is reported as `Transform proof / proof_crash` at the root, `Source proof / oneOf` inside oneOf, and `Transform proof / distribution` inside a distribution candidate. Add permanent root/nested hook-failure regressions for exception and structured-log attribution before fixing. |

## Blocked / Deferred

| id | status | severity | effort | description |
|---|---|---|---|---|
| DOC-044 | blocked | low | small | Documentation/policy: the session-supplied AGENTS.md instructions require every contradiction to be blocked, while checked-in AGENTS.md Rules classify known bugs with clear expected behavior as open and reserve blocked for unavailable prerequisites. These sources give conflicting ledger instructions despite the maintainer's earlier request to revise the rule. Align the supplied instruction source with the approved readiness-based policy; unblock when that external instruction source is updated or its replacement is explicitly established. This policy-source synchronization does not prevent implementing the independently actionable findings above. |

## Rejected / Won't fix

| id | status | severity | effort | description |
|---|---|---|---|---|
| PLAT-015 | wont_fix | high | small | Platform: Windows CI verification of the POSIX-only test skip and remaining suite is not required by maintainer decision. |
