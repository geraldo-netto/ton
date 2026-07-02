# TODO

Open review findings tracked per the categories defined in
[`AGENTS.md`](AGENTS.md). Closed items live in the commit history.

Status values: `open`, `in-progress`.
Effort values: `S` (<=1h), `M` (1-4h), `L` (>4h).

Last full rescan: 2026-07-02.

## security

| id | status | effort | description |
|----|--------|--------|-------------|

## code complexity

| id | status | effort | description |
|----|--------|--------|-------------|

## code duplication

| id | status | effort | description |
|----|--------|--------|-------------|

## reliability/correctness

| id      | status | effort | description |
|---------|--------|--------|-------------|

## performance

| id      | status | effort | description |
|---------|--------|--------|-------------|

## scalability

| id | status | effort | description |
|----|--------|--------|-------------|

## concurrency

| id | status | effort | description |
|----|--------|--------|-------------|

## robustness/recovery

| id | status | effort | description |
|----|--------|--------|-------------|

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

## configuration discoverability

| id      | status | effort | description |
|---------|--------|--------|-------------|
| CFG-001 | open | S | The top-level `encoding` key appears in the README config example (`README.md:242`) and every bundled example (`examples/hwmetrics.json:2`, `dna.json:2`, `winhash.json:2`), but is absent from `_REQUIRED_TOP_LEVEL` (`ton/_config.py:26`), never validated, never read by the Engine, and not listed in the README config-format field bullets (`README.md:252-254`). It looks authoritative (implies configurable output encoding) yet is silently ignored. |

## data governance

| id     | status | effort | description |
|--------|--------|--------|-------------|

## dependency

| id | status | effort | description |
|----|--------|--------|-------------|
| DEP-001 | open | M | Regex generator depends on undocumented CPython internals: it imports private `sre_parse`/`sre_constants`, falling back to the equally-private `re._parser`/`re._constants` on 3.13+ (`ton/generators/regex.py:33-42`), and consumes their internal AST opcodes throughout. These carry no compatibility guarantee and can change/disappear between Python releases, silently breaking the `regex` type on a future supported interpreter. |

## platform

| id | status | effort | description |
|----|--------|--------|-------------|

## observability

| id      | status | effort | description |
|---------|--------|--------|-------------|
| OBS-002 | open | S | The `proof_check_summary` event is emitted with two payload schemas for one discriminator: the Engine emits `{mode, failures}` (`ton/_engine.py:372-378`) while the CLI audit summary emits `{failures}` with no `mode` (`ton/cli.py:297-301`), so a consumer keying on `event="proof_check_summary"` sees inconsistent fields. |

## documentation

| id      | status | effort | description |
|---------|--------|--------|-------------|
| DOC-001 | open | S | The README observability event table (`README.md:848-863`) omits 5 events actually emitted from the `LogEvent` enum (`ton/_logging.py:59-63`): `plugin_registered`, `transform_prepared`, `config_validated`, `proof_check_failed`, `proof_check_summary`. The table presents itself as the event catalog but is incomplete. |
