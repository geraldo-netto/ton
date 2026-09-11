# TODO

## Open

### Architecture / modularity

| id | status | severity | effort | description |
|---|---|---|---|---|
| ARCH-031 | open | medium | large | Architecture/runtime correctness: root and nested pipelines have separate execution models. `Engine._generate_single`/`_generate_pair` prove before validating, but `ChildPipelineGenerator._generate_steps` validates while generating, before its later proof phase (`ton/_engine.py:460-490`, `ton/_pipeline.py`). Reproduction: a generator returning an empty string with a failing proof and non_empty validator raises ProofError at the root in all mode, but ValidationError inside oneOf; audit mode records one proof failure at the root and none when nested. Consolidate stage ordering through a shared pipeline execution contract that preserves nested traces and the direct fast path. Add root/nested parity regressions for strict/audit modes, validators, transforms, pairing, and original failure attribution. |
| ARCH-032 | open | medium | medium | Architecture/public extension gap: documented composite plugins call child.generate directly (`README.md:319-340`), while stack-safe dispatch, selected-child traces, and originating-hook attribution require private `_steps`/generator helpers. A public-only passthrough composite nested beyond the interpreter recursion limit raises GeneratorExecutionError with RecursionError; a nested leaf raising LookupError is attributed to the wrapper class. Expose a supported cooperative child-execution contract and update the public example to use it, building on ARCH-026/ARCH-031. Add public-API-only regressions for deep generation/proof, selected-child tracing, and leaf generator/transform/proof error attribution; do not require plugins to import private modules. |
| ARCH-036 | open | medium | small | Architecture/public typing boundary: the annotated extension API is checked only inside the checkout (`pyproject.toml`, `.github/workflows/ci.yml`); the package has no py.typed marker. In an isolated installed-package layout, mypy reports import-untyped and reveals api.Engine as Any, missing an invalid string seed argument. Adding the marker in that isolated copy restores the expected argument error. Publish the inline typing marker and add an installed-artifact consumer check that exercises public generator/transform/validator contracts, accepts valid implementations, and rejects invalid API calls. Verify the marker is included in the wheel rather than relying only on source-tree type checks. |

## Blocked / Deferred

| id | status | severity | effort | description |
|---|---|---|---|---|
| DOC-044 | blocked | low | small | Documentation/policy: the session-supplied AGENTS.md instructions require every contradiction to be blocked, while checked-in AGENTS.md Rules classify known bugs with clear expected behavior as open and reserve blocked for unavailable prerequisites. These sources give conflicting ledger instructions despite the maintainer's earlier request to revise the rule. Align the supplied instruction source with the approved readiness-based policy; unblock when that external instruction source is updated or its replacement is explicitly established. This policy-source synchronization does not prevent implementing the independently actionable findings above. |

## Rejected / Won't fix

| id | status | severity | effort | description |
|---|---|---|---|---|
| PLAT-015 | wont_fix | high | small | Platform: Windows CI verification of the POSIX-only test skip and remaining suite is not required by maintainer decision. |
