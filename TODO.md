# TODO

## Open

### Reliability / correctness

| id | status | severity | effort | description |
|---|---|---|---|---|
| REL-054 | open | medium | medium | Reliability/correctness: make the vendored regex parser validate syntax independently of the stdlib compiler's workload limits. `RegexGenerator.prepare` rejects `a{2}{3}` but accepts invalid `a{4294967296}{3}` and `a{4294967296}[\d-a]` when `re.compile` overflows before reaching the syntax error. Add permanent zero-row regressions for malformed repeated quantifiers and class ranges after huge valid prefixes; retain unlimited valid repeat counts. |
| REL-055 | open | medium | medium | Reliability/correctness: preserve nested generator exception attribution through composite execution. A generator raising `RuntimeError` reports `GeneratorExecutionError` with its own class at the root, but reports `OneOfGenerator` inside oneOf and becomes `TransformExecutionError(reference='distribution')` inside a distribution candidate. Preserve the failing generator's public error type/reference and original cause; add permanent root/nested API and row-context regressions before fixing. |
| REL-056 | open | medium | medium | Reliability/correctness: preserve nested transform exception attribution in `ChildPipelineGenerator._generate_steps` and engine error translation. A transform raising `RuntimeError` produces `TransformExecutionError(reference='crash')` at the root, but becomes `GeneratorExecutionError(reference='OneOfGenerator')` inside oneOf or is attributed to the outer distribution transform. Add permanent root/nested regressions for public error type, transform reference, cause and row log context before fixing. |

### Performance

| id | status | severity | effort | description |
|---|---|---|---|---|
| PERF-041 | open | medium | medium | Performance: avoid copying the same owned choices list once per child in `ton/concurrency.py::_replace_owned_child`. A zero-row worker with 200 oneOf choices copies 40,000 list slots; an N-choice field incurs quadratic copying before compilation. Copy each occurrence's intermediate containers once, preserving alias/metadata isolation. Add a permanent structural work-count regression for wide oneOf and distribution fields, without timing thresholds or workload caps. |

### Scalability

| id | status | severity | effort | description |
|---|---|---|---|---|
| SCALE-017 | open | medium | medium | Scalability: remove the JSON decoder's nesting ceiling from `ton/_config.py::load`. A valid zero-row config containing 5,000 nested oneOf wrappers fails with `RecursionError` in `json.load`, although downstream snapshots and composite compilation use iterative traversal. Add a permanent fresh-process file-loading regression and use stack-safe parsing without changing the process recursion limit or imposing a depth cap. |

### Plugin extensibility

| id | status | severity | effort | description |
|---|---|---|---|---|
| PLUG-023 | open | high | medium | Plugin extensibility: make child-preparation cache keys unambiguous in `ton/_compiler.py::_prepare_child` / `_preparation_order`. A plugin declaring both `a` (a wrapper owning `child`) and the literal key `a.child` maps both children to the same flattened path. A reproduced config expecting `nested/literal` emits `nested/nested`, even with all proofs enabled. Preserve distinct configuration occurrences; add a permanent plugin regression for colliding dotted/index-like keys before fixing. |

### Architecture / modularity / SOLID

| id | status | severity | effort | description |
|---|---|---|---|---|
| ARCH-024 | open | low | small | Architecture/modularity/SOLID: remove the unused alternate built-in discovery path `discover_generator_classes` / `_walk_subclasses` in `ton/_registry.py`. Production `make_registry` uses `BUILTIN_GENERATOR_CLASSES` directly; the subclass walker is called only by tests and its own helper. Retarget relevant built-in isolation/registration tests to the canonical catalog and remove the duplicate discovery implementation and stale explanatory comments. |

### Observability

| id | status | severity | effort | description |
|---|---|---|---|---|
| OBS-032 | open | medium | medium | Observability: retain the originating nested proof hook's stage/reference across `ChildPipelineGenerator._prove_steps`, composite proof traversal and `ProofChecker`. A transform proof raising `RuntimeError` is reported as `Transform proof / proof_crash` at the root, `Source proof / oneOf` inside oneOf, and `Transform proof / distribution` inside a distribution candidate. Add permanent root/nested hook-failure regressions for exception and structured-log attribution before fixing. |

### Concurrency

| id | status | severity | effort | description |
|---|---|---|---|---|
| CONC-023 | open | medium | medium | Concurrency: stop interpreting every plugin child-location string as a dotted/indexed traversal path in `ton/concurrency.py::_replace_owned_child`. A declared child stored under the literal key `dotted.key` generates `0, 1` through the ordinary engine but `fork_engine` raises `KeyError('dotted')`. Use an unambiguous ownership/location representation shared with compilation; add permanent direct/worker parity regressions for literal dots and brackets while preserving metadata isolation. |

## Blocked / Deferred

| id | status | severity | effort | description |
|---|---|---|---|---|
| DOC-044 | blocked | low | small | Documentation/policy: the session-supplied AGENTS.md instructions require every contradiction to be blocked, while checked-in AGENTS.md Rules classify known bugs with clear expected behavior as open and reserve blocked for unavailable prerequisites. These sources give conflicting ledger instructions despite the maintainer's earlier request to revise the rule. Align the supplied instruction source with the approved readiness-based policy; unblock when that external instruction source is updated or its replacement is explicitly established. This policy-source synchronization does not prevent implementing the independently actionable findings above. |

## Rejected / Won't fix

| id | status | severity | effort | description |
|---|---|---|---|---|
| PLAT-015 | wont_fix | high | small | Platform: Windows CI verification of the POSIX-only test skip and remaining suite is not required by maintainer decision. |
