# TODO

Open review findings tracked per the categories defined in
[`AGENTS.md`](AGENTS.md). Closed items live in the commit history.

Status values: `open`, `in-progress`.
Effort values: `S` (<=1h), `M` (1-4h), `L` (>4h).

Last full rescan: 2026-06-06.
Verification run during rescan: `python -m pytest`, `python -m pytest --cov=ton --cov-report=term-missing`, `python -m ruff check .`, `python -m mypy ton`, and `python -m mypy ton tests`.

## security

| id      | status | effort | description |
|---------|--------|--------|-------------|
| SEC-003 | open   | M      | `registry_with_entry_points()` (`ton/_registry.py`) loads every `ton.generators` entry-point factory unconditionally when that registry path is used. A typosquatted or hijacked package installed alongside TON can execute code via `factory()`. Add an opt-in entry-point path and an allowlist/trust policy for third-party generators. |

## code complexity

| id      | status | effort | description |
|---------|--------|--------|-------------|
| CPLX-001 | open  | M      | `python -m mypy ton tests` fails with 60 strict-mode errors across tests even though production code passes `python -m mypy ton`. Either type the test helpers or configure mypy's intended scope explicitly so the strictness signal is not noisy. |

## code duplication

| id      | status | effort | description |
|---------|--------|--------|-------------|

## reliability/correctness

| id      | status | effort | description |
|---------|--------|--------|-------------|

## performance

| id      | status | effort | description |
|---------|--------|--------|-------------|

## scalability

| id      | status | effort | description |
|---------|--------|--------|-------------|
| SCALE-001 | open | M      | `--resume-from` skips by generating and discarding every prior row in `_stream()` (`ton/cli.py`). High-offset shard starts are O(resume_from), which is expensive for large jobs or costly generators. Document the tradeoff more clearly or add generator-aware fast-forward support where feasible. |

## concurrency

| id      | status | effort | description |
|---------|--------|--------|-------------|
| CONC-001 | open | M      | A single `Engine` instance can be iterated from multiple threads with shared RNG and prepared generator state (`ton/_engine.py`, `ton/generators/sequence.py`). The README documents one engine per worker/thread, but the runtime does not guard accidental concurrent iteration. Add a fail-fast guard or make the contract explicit in API docs. |

## robustness/recovery

| id      | status | effort | description |
|---------|--------|--------|-------------|
| ROB-001 | open  | M      | `ton -o PATH` opens the final output path directly with `open(path, "w")` (`ton/cli.py`). A crash or interruption after truncation can leave a partial final file. Consider an optional atomic temp-file + replace mode, or document that streaming output is not crash-atomic. |

## architecture/modularity/SOLID

| id      | status | effort | description |
|---------|--------|--------|-------------|

## decoupling

| id      | status | effort | description |
|---------|--------|--------|-------------|

## business/design patterns/DDD

| id      | status | effort | description |
|---------|--------|--------|-------------|
| PAT-008 | open   | M      | Add a generic `hash` generator with `algorithm: md5\|sha1\|sha256\|sha512\|bcrypt` (later: argon2, scrypt). Keep `lmhash` as-is -- it stays the Windows NT-hash specialty. New `hash` should reuse `PairedGenerator` so `$word[id]$` returns the plaintext like `lmhash` already does. |

## plugin extensibility

| id      | status | effort | description |
|---------|--------|--------|-------------|
| PLUG-001 | open | M      | Entry-point factories are not type-checked before insertion into the registry (`ton/_registry.py`). A factory returning a non-`Generator` object can be accepted and fail later during engine preparation/rendering. Validate the instance against the generator protocol and log/skip invalid plugins. |

## CLI / option integrity

| id      | status | effort | description |
|---------|--------|--------|-------------|
| CLI-001 | open  | M      | The CLI has no `--entry-points`/`--no-entry-points` option, and `api.generate()` does not expose `include_entry_points`; users must manually call `api.build_registry()` and pass the result. Align CLI/API behavior with the documented plugin story and the security policy from `SEC-003`. |
| CLI-002 | open  | S      | `--log-level` help text exposes the internal review tag `(OBS-003)` to end users (`ton/cli.py`). Remove internal TODO IDs from CLI help so generated help remains product-facing. |

## configuration discoverability

| id      | status | effort | description |
|---------|--------|--------|-------------|
| CFG-001 | open  | M      | Config validation is split between `_config.py` and each generator's `prepare()` method, but there is no machine-readable schema or `ton --validate` mode. Add a documented validation surface so operators can check configs without starting a generation run. |

## data governance

| id      | status | effort | description |
|---------|--------|--------|-------------|
| DG-001  | open   | S      | The rescan found no committed secrets or private absolute paths in tracked text files, but the repo has no automated guard for that check. Add a lightweight CI/pre-commit grep for secrets and private paths so future generated fixtures do not leak sensitive data. |

## dependency

| id      | status | effort | description |
|---------|--------|--------|-------------|

## platform

| id      | status | effort | description |
|---------|--------|--------|-------------|

## observability

| id      | status | effort | description |
|---------|--------|--------|-------------|
| OBS-001 | open   | S      | Repeated calls to `configure_stderr()` (`ton/_logging.py`) add multiple stderr handlers, which can duplicate log lines in long-lived library processes. Make the helper idempotent or document that callers own handler deduplication. |

## documentation

| id      | status | effort | description |
|---------|--------|--------|-------------|
| DOC-001 | open   | S      | `ton/generators/__init__.py` still says to add new built-ins to `default_registry()`, but the actual registration source is `BUILTIN_GENERATOR_CLASSES`. Update the contributor note so new generator instructions match the current registry architecture. |
