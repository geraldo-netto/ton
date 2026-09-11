# TODO

## Open

### Performance

| id | status | severity | effort | description |
|---|---|---|---|---|
| PERF-048 | open | medium | medium | Performance: remove redundant copies of privately owned extension graphs across `ton/_config.py::validate_with_catalog`, `ton/cli.py::_build_engine`, `ton/concurrency.py::_worker_options` and `ton/_compiler.py::EngineCompiler.__init__`. A counted prototype is deep-copied once by direct Engine construction but twice by validation and worker construction; plugin CLI construction similarly snapshots then copies again. Introduce an internal ownership handoff shared by these builders, while public Engine inputs remain isolated prototypes. This is one shared ownership-boundary change; verify copy counts, cross-kind aliases, provider metadata, partition-hook mutations and isolation between separate workers/Engines. |
| PERF-049 | open | medium | medium | Performance: avoid rediscovering every segmentation of generated char values in `ton/generators/char.py::CharGenerator.prove`. With `values=['a','aa']`, proving `'a' * (N + N//2)` examines a growing set of positions for each of N draws; N=250/500/1,000 takes 0.0044/0.0189/0.0776 s for a single valid value. Compile reusable token matching information and/or retain verifiable draw segmentation on checked rows so generated-value proof work does not grow quadratically. Keep acceptance exact for ambiguous, empty and multi-character tokens and arbitrary external strings. Add structural work-count and exhaustive small-pool equivalence regressions, preserving seeded generation. |

### Scalability

| id | status | severity | effort | description |
|---|---|---|---|---|
| SCALE-023 | open | high | large | Scalability: reduce retained backtracking state in `ton/generators/regex.py::_matches`, `_advance_match` and `_advance_repeat`. For pattern `(?:a?){N}a{N}`, actual values generated with `Random(42)` at N=50/100/200 contain 69/145/287 characters, but proof peaks at 1.74/6.98/26.46 MB and takes 0.012/0.044/0.227 s. The matcher stores every visited position/continuation tuple, including repeat-task objects. Use compact/interned continuations, feasible-length pruning and an execution strategy that releases obsolete states. Add deterministic state-growth regressions plus exhaustive small-pattern equivalence for acceptance/rejection, nullable nested repeats, large counted repeats and deep groups, without limiting valid patterns or output lengths. |
| SCALE-024 | open | high | large | Scalability: separate proof metadata from repeated copies of unchanged string payloads in `ton/_pipeline.py::DrawnValue`, `_GeneratedChildValue` and their composite callers. Each `str` subclass wrapper copies the entire child text and retains the prior wrapper through its trace. A single 100,000-character value wrapped in 10/40/80 one-choice `oneOf` levels peaks at 1.11/4.13/8.16 MB in proof-all mode versus about 0.10/0.11/0.11 MB with proofs off. Preserve shared text storage across passthrough traces while retaining exact child ownership and transformed before/after values. Add payload-sharing/allocation-growth regressions covering nested composites, child pipelines, sampling, rejected children and pickle/deepcopy behavior. |
| SCALE-026 | open | medium | medium | Scalability: stream proof-audit serialization in bounded chunks in `ton/_proofaudit.py::ProofAuditWriter.__call__` instead of `''.join(iter_json(payload)) + '\n'` followed by one write. A first failure whose spec contains 100,000 `'abc'` values creates a single 600,270-character write and peaks at 6.83 MB of extra allocations even with a sink that retains nothing. Drain JSON tokens through a bounded buffer; preserve exact JSONL bytes, spec fingerprint caching, redaction and publication/error semantics, and handle oversized scalar tokens without reinstating a whole-record buffer. Add sink write-size/allocation-growth coverage, later-chunk failure tests and existing report round-trip checks. |

## Blocked / Deferred

| id | status | severity | effort | description |
|---|---|---|---|---|
| DOC-044 | blocked | low | small | Documentation/policy: the session-supplied AGENTS.md instructions require every contradiction to be blocked, while checked-in AGENTS.md Rules classify known bugs with clear expected behavior as open and reserve blocked for unavailable prerequisites. These sources give conflicting ledger instructions despite the maintainer's earlier request to revise the rule. Align the supplied instruction source with the approved readiness-based policy; unblock when that external instruction source is updated or its replacement is explicitly established. This policy-source synchronization does not prevent implementing the independently actionable findings above. |

## Rejected / Won't fix

| id | status | severity | effort | description |
|---|---|---|---|---|
| PLAT-015 | wont_fix | high | small | Platform: Windows CI verification of the POSIX-only test skip and remaining suite is not required by maintainer decision. |
