# TODO

Open review findings tracked per the categories defined in
[`AGENTS.md`](AGENTS.md). Closed items live in the commit history.

Status values: `open`, `in-progress`.
Effort values: `S` (<=1h), `M` (1-4h), `L` (>4h).

Last full rescan: 2026-07-02.

## security

| id | status | effort | description |
|----|--------|--------|-------------|
| SEC-001 | open | M | Nested regex repeats bypass the `MAX_LITERAL_REPEAT` guard: `_reject_oversized_repeats` (`ton/generators/regex.py:92-104`) validates each `{n}` node independently against the 10,000 cap but never accounts for multiplicative nesting. `(?:a{5000}){5000}` passes yet `_emit_repeat` (`regex.py:161-167`) materializes ~25M chars/row; deeper nesting yields billions — config-driven memory-exhaustion DoS. |

## code complexity

| id | status | effort | description |
|----|--------|--------|-------------|

## code duplication

| id | status | effort | description |
|----|--------|--------|-------------|

## reliability/correctness

| id      | status | effort | description |
|---------|--------|--------|-------------|
| REL-001 | open | M | Proof-check never validates composite/nested generator output. `_source_proof_failures` (`ton/_engine.py:537`) only calls the top-level generator's `prove`, which for `oneOf`/`weighted`/`sequence_of` is the permissive default `ProofResult(ok=True)`; child generators are never asked to prove. `--proof-check=all/audit` reports "all values passed" while composite outputs are unchecked (false assurance). Compounded by `DistributionTransform.apply` discarding the source value (`ton/transforms/distribution.py:44-46`), so the proven source draw is thrown away and the emitted value is unproven. |

## performance

| id      | status | effort | description |
|---------|--------|--------|-------------|
| PERF-001 | open | M | Regex character-class pools are rebuilt on every emission instead of at prepare time. `_pick_in` does `list(items)` + `_flatten_in` expanding ranges into a fresh char list each call (`ton/generators/regex.py:170-204`), and `_pick_excluding` filters the 95-char ASCII table per call (`regex.py:207-211`). For `[a-z]{20}` or `[^x]{100}` this recomputes the pool per character, per row. |
| PERF-002 | open | S | `PreparedField.is_paired` is a property recomputed on every access (`ton/_engine.py:46-51`); called per-token per-row in the hot path `_resolve` (`_engine.py:399`) whenever any paired type exists, despite the dataclass being frozen. Cache it. |

## scalability

| id | status | effort | description |
|----|--------|--------|-------------|
| SCAL-001 | open | M | Audit proof mode grows `_proof_failures_audit` without bound — one `ProofFailure` appended per failing row (`ton/_engine.py:457`), each copying the full spec dict (`spec=dict(self._types[type_key])`, `_engine.py:568`). A long run with systematic failures accumulates unbounded memory in a list that could be streamed/counted. |

## concurrency

| id | status | effort | description |
|----|--------|--------|-------------|
| CONC-001 | open | S | `_ensure_default_classes` double-checked locking is unsafe. The fast path `if _DEFAULT_CLASSES: return` (`ton/_registry.py:339`) reads the module-global dict without the lock while the lock holder populates it incrementally in place (`_registry.py:344-345`). A concurrent caller can observe a non-empty-but-partial registry and get spurious "Unknown type" errors. Fix: build a local dict and publish atomically. |

## robustness/recovery

| id | status | effort | description |
|----|--------|--------|-------------|
| ROB-001 | open | S | Atomic overwrite silently drops the target file's permissions. `_open_atomic_output` writes via `NamedTemporaryFile` (mode 0600) then `os.replace` over the destination (`ton/cli.py:402-414`), so overwriting an existing 0644 file leaves it 0600, and new files ignore the process umask. Original mode/ownership is not preserved across the replace. |

## architecture/modularity/SOLID

| id       | status | effort | description |
|----------|--------|--------|-------------|

## decoupling

| id      | status | effort | description |
|---------|--------|--------|-------------|

## business/design patterns/DDD

| id | status | effort | description |
|----|--------|--------|-------------|

## plugin extensibility

| id       | status | effort | description |
|----------|--------|--------|-------------|
| PLUG-001 | open | M | Validators are a dead extension point: `register_validator` (`ton/_registry.py:85`), the `ton.validators` entry-point group (`_registry.py:38`, loaded at `_registry.py:184`) and `list_validators()` all exist and load, but nothing consumes a validator — configs can't reference one, the Engine never invokes them, and `--list-namespaces` (`ton/cli.py:350-354`) doesn't print them. A third party can register a validator that does nothing. |
| PLUG-002 | open | S | `registry_with_entry_points` docstring claims "Entry-point names override built-ins with the same key" (`ton/_registry.py:399-400`) and its example registers `uuid`, but `ExtensionCatalog._register` forbids replacing core (`_registry.py:136-137`) and unqualified entry points land in the `plugin` namespace, so a `uuid` entry point resolves to `plugin.uuid` and never shadows the built-in. Documented override behavior does not occur. |

## CLI / option integrity

| id      | status | effort | description |
|---------|--------|--------|-------------|
| CLI-001 | open | M | `--validate` gives false confidence: `_validate_config` → `validate_with_catalog` (`ton/cli.py:211`, `ton/_config.py:72`) only checks structure + type/transform references, never calling `Generator.prepare`, so per-field validation (bounds, value lists, caps) is skipped. A config with `integer minValue=100 maxValue=1` prints `ton: config valid` (exit 0) under `--validate` but the real run exits 2 (`Invalid spec ... maxValue (1) must be >= minValue (100)`). Help text ("Validate the config and exit") does not convey this deferral. |

## configuration discoverability

| id      | status | effort | description |
|---------|--------|--------|-------------|
| CFG-001 | open | S | The top-level `encoding` key appears in the README config example (`README.md:242`) and every bundled example (`examples/hwmetrics.json:2`, `dna.json:2`, `winhash.json:2`), but is absent from `_REQUIRED_TOP_LEVEL` (`ton/_config.py:26`), never validated, never read by the Engine, and not listed in the README config-format field bullets (`README.md:252-254`). It looks authoritative (implies configurable output encoding) yet is silently ignored. |

## data governance

| id     | status | effort | description |
|--------|--------|--------|-------------|
| DG-002 | open | M | Define redaction controls for proof failure records before exposing them to logs, manifests, or audit exports. `ProofFailure` currently stores raw generated `value`, `id_value`, and full field spec, which can include sensitive synthetic identifiers or source value pools. |
| DG-003 | open | S | `uuid` type with `version:1` calls `uuid.uuid1()` (`ton/generators/uuid.py:54`), which embeds the host machine's real MAC address and clock into the "synthetic" output, leaking host hardware/network identifiers. Only the version-4 path is seed-reproducible/synthetic. |

## dependency

| id | status | effort | description |
|----|--------|--------|-------------|
| DEP-001 | open | M | Regex generator depends on undocumented CPython internals: it imports private `sre_parse`/`sre_constants`, falling back to the equally-private `re._parser`/`re._constants` on 3.13+ (`ton/generators/regex.py:33-42`), and consumes their internal AST opcodes throughout. These carry no compatibility guarantee and can change/disappear between Python releases, silently breaking the `regex` type on a future supported interpreter. |

## platform

| id | status | effort | description |
|----|--------|--------|-------------|
| PLAT-001 | open | S | `datetime.fromisoformat()` parses user `minValue`/`maxValue` in `ton/generators/date.py:46-47` and `timestamp_unix.py:43-44`. On Python 3.10 (declared-supported; pyproject `requires-python >=3.10`) this parser rejects common ISO 8601 forms that 3.11+ accepts (trailing `Z`, basic `YYYYMMDD`, `+HH` offsets), so a config working on 3.11+ raises on 3.10. |
| PLAT-002 | open | S | The date generator passes the user-supplied `format` straight to `datetime.strftime` (`ton/generators/date.py:58`). `strftime` directive support is platform-dependent — `%-d`/`%-m` are glibc-only and fail on Windows, `%Y` padding for years <1000 differs by libc — so identical configs produce divergent/erroring output across the supported OS matrix. |

## observability

| id      | status | effort | description |
|---------|--------|--------|-------------|
| OBS-002 | open | S | The `proof_check_summary` event is emitted with two payload schemas for one discriminator: the Engine emits `{mode, failures}` (`ton/_engine.py:372-378`) while the CLI audit summary emits `{failures}` with no `mode` (`ton/cli.py:297-301`), so a consumer keying on `event="proof_check_summary"` sees inconsistent fields. |

## documentation

| id      | status | effort | description |
|---------|--------|--------|-------------|
| DOC-001 | open | S | The README observability event table (`README.md:848-863`) omits 5 events actually emitted from the `LogEvent` enum (`ton/_logging.py:59-63`): `plugin_registered`, `transform_prepared`, `config_validated`, `proof_check_failed`, `proof_check_summary`. The table presents itself as the event catalog but is incomplete. |
