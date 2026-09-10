# TODO

## Open

### Reliability / correctness

| id | status | severity | effort | description |
|---|---|---|---|---|
| REL-044 | open | high | small | Reliability/correctness: calculate date spans with exact timedelta components in `ton/generators/_datetime.py::duration_seconds`. From `0001-01-01` to `9999-12-31T23:59:58.999999`, float rounding lets the maximum draw produce `9999-12-31T23:59:59`, outside the bounds; using the final datetime microsecond instead raises `OverflowError`. Add a permanent regression using an RNG that selects the upper endpoint for both cases before fixing. |
| REL-045 | open | medium | small | Reliability/correctness: tighten the date oracle in `tests/test_type_e2e.py::_check_date`. It expands a date-only upper bound to 23:59:59, although `DateGenerator` uses midnight; with a datetime output format it accepts `2024-12-31 12:00:00` for `maxValue="2024-12-31"`. Compare the actual represented interval without widening the bound, add datetime-format coverage, and prove the oracle rejects an injected out-of-range value. |
| REL-046 | open | medium | small | Reliability/correctness: make `tests/test_type_e2e.py::_check_timestamp_unix` use exact UTC bounds. It interprets naive bounds in local time, expands the upper bound to end-of-day, adds another day of slack, and truncates milliseconds; it accepts noon after an upper bound of `2024-12-31` midnight. Remove the slack and unit truncation; add oracle regressions rejecting values one second or millisecond outside either endpoint, independent of the host timezone. |
| REL-047 | open | medium | medium | Reliability/correctness: preserve nested validator exception attribution across `ton/generators/base.py::ChildPipelineGenerator._generate_steps` and `ton/_engine.py::_generate_source`. A validator raising `RuntimeError` yields `ValidatorExecutionError` at the root but `GeneratorExecutionError` naming `OneOfGenerator` when the same field is nested. Add permanent root/nested regressions asserting the validator error type, reference, row log context, and CLI exit 3; preserve ordinary validator rejection as `ValidationError`. |
| REL-048 | open | medium | small | Reliability/correctness: repair the first four validation tests in `tests/test_weighted_generator.py`. The empty/mismatched/negative/zero-weight cases use removed `values`/`weights` options and omit `PreparationContext`, so all pass solely on the composite-context guard without reaching the validation named by each test. Use current choices specs and a real context, assert the intended diagnostics, and retain obsolete-key rejection separately through the normal compiler path. |

### Configuration discoverability

| id | status | severity | effort | description |
|---|---|---|---|---|
| CFG-029 | open | medium | small | Configuration discoverability: reject the bcrypt-only `rounds` option for other algorithms in `ton/generators/hash.py::HashGenerator.prepare`, as already done for `cache`. `algorithm="sha256", rounds="invalid"` currently validates and silently ignores the option. Add direct, catalog-validation, and CLI regressions for irrelevant rounds before fixing. |
| CFG-030 | open | medium | small | Configuration discoverability: preserve the owning field path for choice-wrapper errors in `ton/_distribution.py::_prepare_choice`. A misspelled weight inside `types.outer.choices[0].choices[0]` reports only `weighted.choices[0].weigth`, losing the parent path promised by README diagnostics. Build the location from `PreparationContext.path`; add permanent nested weighted and distribution-transform regressions asserting the complete path and suggestion. |

### Scalability

| id | status | severity | effort | description |
|---|---|---|---|---|
| SCALE-016 | open | high | medium | Scalability: preserve finite decimal weights in `ton/_distribution.py::coerce_weight`, `validate_weights`, and cumulative sampling. Equal positive weights `Decimal("1e-400")` become zero and reject the job; `Decimal("1e400")` becomes infinity and also rejects it. Use exact proportional arithmetic without float precision or exponent ceilings. Add permanent JSON and in-memory regressions for tiny/large equal weights, mixed magnitudes, zero weights, and deterministic selection thresholds for both weighted generators and distribution transforms. |

### Concurrency

| id | status | severity | effort | description |
|---|---|---|---|---|
| CONC-019 | open | high | medium | Concurrency: make sequence offsets occurrence-specific in `ton/concurrency.py::_offset_sequences` / `_offset_sequence_spec`. If `types.a` and `types.b` share one sequence mapping, worker 1 of two for four rows produces `4/4, 5/5` instead of `2/2, 3/3`, because the alias-preserving snapshot is offset twice. Add permanent shared-root and shared-child regressions, including different occurrence counts and an unchanged caller config; isolate offset state by configuration occurrence. |
| CONC-020 | open | medium | small | Concurrency: make proof-traced string values reconstructible in `ton/generators/base.py::DrawnValue` and `_GeneratedChildValue`. `deepcopy` and pickle round-trips call their multi-argument `__new__` with only the string, raising `TypeError`; `proven_draws` explicitly promises preserved ownership. Add permanent round-trip tests for plain and transformed composite draws and retained audit failures, verifying proof ownership and rejection survive serialization. |
| CONC-021 | open | high | small | Concurrency: detect active-path cycles while traversing declared children in `ton/concurrency.py::_offset_sequence_spec`. A `oneOf` whose sole choice is itself raises a contextual `TemplateError` through `Engine.from_config`, but `fork_engine` loops indefinitely before compilation (reproduced with a two-second subprocess timeout). Add a permanent subprocess regression for generator and transform cycles, retaining support for acyclic shared specs. |

### Plugin extensibility

| id | status | severity | effort | description |
|---|---|---|---|---|
| PLUG-021 | open | high | medium | Plugin extensibility: validate prototype cloneability inside the isolated entry-point loading boundary in `ton/_registry.py::_load_catalog_candidate`. A generator containing a `threading.Lock` is logged as successfully loaded, but the subsequent `catalog.generators()` raises `TypeError`, aborting broad discovery despite its documented broken-plugin isolation. Add permanent generator/transform/validator regressions: broad loading skips and logs the uncloneable provider, exact selectors raise `RegistryError`, and valid providers remain usable. |

### Architecture / modularity / SOLID

| id | status | severity | effort | description |
|---|---|---|---|---|
| ARCH-023 | open | medium | small | Architecture/modularity/SOLID: remove the unused recursive `Generator.nested_types` / `_nested_type_names` discovery path in `ton/generators/base.py` and update its fixtures in `tests/test_composite_generators.py`. The hook is documented there as the extension discovery contract, but the compiler and worker traversal consult only `nested_specs`; the legacy plugin test passes because it supplies a full registry. Use the canonical ownership declaration and retain a regression that a declared plugin child is prepared and receives worker sequence offsets. |

## Blocked / Deferred

| id | status | severity | effort | description |
|---|---|---|---|---|

## Rejected / Won't fix

| id | status | severity | effort | description |
|---|---|---|---|---|
| PLAT-015 | wont_fix | high | small | Platform: Windows CI verification of the POSIX-only test skip and remaining suite is not required by maintainer decision. |
