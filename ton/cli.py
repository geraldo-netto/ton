"""Command-line entry point for TON."""

from __future__ import annotations

import argparse
import json
import logging
import sys
import time
from collections.abc import Callable, Iterator, Sequence
from contextlib import contextmanager
from typing import TextIO, TypeVar

from . import __version__, api
from ._output import open_output_path
from ._proofcheck import PROOF_MODES
from .api import (
    ConfigError,
    Engine,
    EngineOptions,
    LogEvent,
    ProofError,
    TemplateError,
    ValidationError,
    configure_stderr,
)
from .api import logger as _logger

_LOG_LEVELS = {
    "debug": logging.DEBUG,
    "info": logging.INFO,
    "warning": logging.WARNING,
    "error": logging.ERROR,
    "critical": logging.CRITICAL,
}

#: Default rows between explicit output flushes. Overridable via
#: ``--batch-rows``.
_DEFAULT_BATCH_ROWS = 1024
_T = TypeVar("_T")


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="ton",
        description="TON: mass data generator. Render rows from a JSON template.",
    )
    parser.add_argument("config", nargs="?", help="Path to the JSON config file.")
    parser.add_argument(
        "-o",
        "--output",
        help="Write rows to this file instead of stdout.",
    )
    parser.add_argument(
        "--seed",
        type=int,
        default=None,
        help="Seed the RNG for reproducible output.",
    )
    parser.add_argument(
        "--verbose",
        action="store_true",
        help="Print final row count, elapsed time, and rows/sec to stderr.",
    )
    parser.add_argument(
        "--progress",
        type=_non_negative_int,
        metavar="EVERY",
        default=0,
        help="Emit a JSON progress line to stderr every EVERY rows (0 disables).",
    )
    parser.add_argument(
        "--batch-rows",
        type=_positive_int,
        metavar="N",
        default=_DEFAULT_BATCH_ROWS,
        help="Flush output every N written rows (default: 1024).",
    )
    parser.add_argument(
        "--no-clobber",
        action="store_true",
        help="Refuse to overwrite an existing --output file.",
    )
    parser.add_argument(
        "--resume-from",
        type=_non_negative_int,
        metavar="ROW",
        default=0,
        help=(
            "Skip the first ROW generated rows before writing any output. "
            "Skipped rows are still generated to preserve deterministic state."
        ),
    )
    parser.add_argument(
        "--validate",
        action="store_true",
        help=(
            "Validate the config (structure, type/transform references, and "
            "per-field specs) and exit without generating rows."
        ),
    )
    parser.add_argument(
        "--proof-check",
        choices=PROOF_MODES,
        default="off",
        help="Proof-check generated values: off, sampled strict checks, all rows, or audit.",
    )
    parser.add_argument(
        "--proof-sample-rate",
        type=_positive_int,
        metavar="N",
        default=1,
        help="With --proof-check=sample, check every Nth generated row.",
    )
    parser.add_argument(
        "--redact-proof-failures",
        action="store_true",
        help=(
            "Mask generated values and field specs in retained audit "
            "proof-failure records so they carry no sensitive data."
        ),
    )
    parser.add_argument(
        "--list-namespaces",
        action="store_true",
        help=(
            "List available built-in namespaces, data types, transforms, and validators. "
            "Built-ins are always available; plugin loading is opt-in."
        ),
    )
    parser.add_argument(
        "--entry-points",
        action="store_true",
        help=(
            "Load trusted third-party plugins from the ton.generators, "
            "ton.transforms, and ton.validators entry-point groups into "
            "the extension catalog."
        ),
    )
    parser.add_argument(
        "--entry-point",
        action="append",
        metavar="NAME",
        dest="entry_point_allowlist",
        default=[],
        help="Allow only this entry-point name. May be passed more than once.",
    )
    parser.add_argument(
        "--log-level",
        choices=sorted(_LOG_LEVELS.keys()),
        default=None,
        help="Attach a stderr handler to the 'ton' logger at this level.",
    )
    parser.add_argument(
        "--version",
        action="version",
        version=f"%(prog)s {__version__}",
    )
    return parser


def _non_negative_int(value: str) -> int:
    """argparse helper rejecting negative integers (TODO REL-017)."""
    parsed = int(value)
    if parsed < 0:
        raise argparse.ArgumentTypeError(f"must be >= 0 (got {value})")
    return parsed


def _positive_int(value: str) -> int:
    parsed = int(value)
    if parsed < 1:
        raise argparse.ArgumentTypeError(f"must be >= 1 (got {value})")
    return parsed


def main(argv: Sequence[str] | None = None) -> int:
    """CLI entry point. Returns a shell exit code."""
    args = _build_parser().parse_args(argv)
    if args.log_level is not None:
        configure_stderr(_LOG_LEVELS[args.log_level])
    if args.progress:
        _install_progress_handler()
    return _run(args)


def _run(args: argparse.Namespace) -> int:
    """Execute the parsed command. Split out of main() so flag handling
    stays small as new options are added."""
    try:
        return _run_inner(args)
    except KeyboardInterrupt:
        print("ton: interrupted", file=sys.stderr)
        return 130
    except Exception as exc:  # noqa: BLE001 - top-level CLI safety net
        # ``logger.exception`` records the traceback for any handler
        # attached via ``--log-level`` (TODO OBS-008); the print line
        # keeps the v1 "ton: ..." stderr contract for users without a
        # log handler configured.
        _logger.exception(
            "cli_unexpected_error type=%s",
            type(exc).__name__,
            extra={"event": LogEvent.CLI_UNEXPECTED_ERROR.value, "error_type": type(exc).__name__},
        )
        print(f"ton: unexpected error: {type(exc).__name__}: {exc}", file=sys.stderr)
        return 3


def _run_inner(args: argparse.Namespace) -> int:
    if args.list_namespaces:
        _print_namespaces(args)
        return 0
    if args.config is None:
        print("ton: config path is required", file=sys.stderr)
        return 1
    if args.validate:
        return _validate_config(args)
    built = _prepare_engine(args)
    if isinstance(built, int):
        return built
    engine, encoding = built
    return _execute(engine, args, encoding)


def _validate_config(args: argparse.Namespace) -> int:
    """Validate the config with catalog-aware diagnostics and exit.

    Uses :func:`ton.api.validate_config` rather than constructing an
    Engine so unknown type/transform references are reported with the
    available-name lists and plugin-namespace diagnostics, keeping CLI
    ``--validate`` aligned with the library validation path (TODO
    CLI-002, CFG-003).
    """

    def validate() -> None:
        config = api.load_config(args.config)
        api.validate_config(config, catalog=_catalog_from_args(args))

    result = _map_config_errors(validate)
    if isinstance(result, int):
        return result
    print("ton: config valid", file=sys.stderr)
    return 0


def _prepare_engine(args: argparse.Namespace) -> tuple[Engine, str] | int:
    """Build the Engine + resolve output encoding, or return an exit code.

    Loads the config once so the engine and the output encoding
    (CFG-001) share a single parse.
    """

    def prepare() -> tuple[Engine, str]:
        config = api.load_config(args.config)
        return _build_engine(args, config), api.output_encoding(config)

    return _map_config_errors(prepare)


def _map_config_errors(operation: Callable[[], _T]) -> _T | int:
    """Run a config operation and map its domain failures to CLI exit codes."""
    try:
        return operation()
    except FileNotFoundError as exc:
        print(f"ton: {exc}", file=sys.stderr)
        return 1
    except (ConfigError, TemplateError, json.JSONDecodeError) as exc:
        print(f"ton: invalid config: {exc}", file=sys.stderr)
        return 2


def _execute(engine: Engine, args: argparse.Namespace, encoding: str) -> int:
    if args.resume_from >= engine.total_rows and engine.total_rows > 0:
        # REL-018: a value that skips past every row produces a silent
        # empty file. Surface this through both stderr and the logger
        # so the user actually notices.
        _logger.warning(
            "resume_overshoot resume_from=%d total_rows=%d",
            args.resume_from,
            engine.total_rows,
            extra={
                "event": LogEvent.RESUME_OVERSHOOT.value,
                "resume_from": args.resume_from,
                "total_rows": engine.total_rows,
            },
        )
        print(
            f"ton: --resume-from={args.resume_from} >= total rows "
            f"({engine.total_rows}); output will be empty",
            file=sys.stderr,
        )
    started = time.perf_counter()
    try:
        with _open_output(args.output, no_clobber=args.no_clobber, encoding=encoding) as stream:
            rows_written = _stream(
                engine,
                stream,
                progress_every=args.progress,
                batch_rows=args.batch_rows,
                resume_from=args.resume_from,
            )
    except OSError as exc:
        print(f"ton: cannot write output: {exc}", file=sys.stderr)
        return 1
    except ProofError as exc:
        print(f"ton: proof failed: {exc}", file=sys.stderr)
        return 2
    except ValidationError as exc:
        print(f"ton: validation failed: {exc}", file=sys.stderr)
        return 2
    except TemplateError as exc:
        print(f"ton: invalid config: {exc}", file=sys.stderr)
        return 2
    if args.verbose:
        _report(rows_written, time.perf_counter() - started)
    if args.proof_check == "audit":
        _report_proof_audit(engine)
    return 0


def _report_proof_audit(engine: Engine) -> None:
    """Print the audit proof-check summary to stderr (TODO OBS-002).

    Audit mode collects failures instead of aborting, so a normal run
    exits 0 and the user would otherwise never learn that any value
    failed its proof. Surface the count and point at the structured
    ``proof_check_failed`` log events that carry the per-row detail.
    """
    count = engine.proof_failure_count
    _logger.info(
        "cli_proof_audit_summary failures=%d",
        count,
        # Mirror the engine's proof_check_summary payload shape so a
        # consumer keying on the event sees a consistent schema (OBS-002).
        extra={"event": LogEvent.PROOF_CHECK_SUMMARY.value, "mode": "audit", "failures": count},
    )
    if count == 0:
        print("ton: proof-check audit: all generated values passed", file=sys.stderr)
        return
    print(
        f"ton: proof-check audit: {count} value(s) failed; "
        "rerun with --log-level warning for per-row proof_check_failed detail",
        file=sys.stderr,
    )


def _catalog_from_args(args: argparse.Namespace) -> api.ExtensionCatalog:
    """Build the extension catalog implied by the entry-point flags.

    Single source of truth for the catalog used by engine construction,
    ``--validate``, and ``--list-namespaces`` so all three observe the
    same plugin surface (TODO CFG-003).
    """
    allowed = set(args.entry_point_allowlist) or None
    return api.build_extension_catalog(
        include_entry_points=bool(args.entry_points or args.entry_point_allowlist),
        allowed_entry_points=allowed,
    )


def _build_engine(args: argparse.Namespace, config: dict[str, object]) -> Engine:
    registry = None
    transforms = None
    validators = None
    if args.entry_points or args.entry_point_allowlist:
        catalog = _catalog_from_args(args)
        registry = catalog.generators()
        transforms = catalog.transforms()
        validators = catalog.validators()
    # Pass only --seed; from_config derives the RNG from it so the
    # Random(seed)-or-Random() idiom lives solely in the engine (DEC-002).
    return Engine.from_options(
        config,
        EngineOptions(
            registry=registry,
            transforms=transforms,
            validators=validators,
            seed=args.seed,
            proof_mode=args.proof_check,
            proof_sample_rate=args.proof_sample_rate,
            redact_proof_failures=args.redact_proof_failures,
        ),
    )


def _print_namespaces(args: argparse.Namespace) -> None:
    catalog = _catalog_from_args(args)
    print("namespaces:", ", ".join(catalog.namespaces()))
    print("data types:", ", ".join(catalog.list_data_types()))
    print("transforms:", ", ".join(catalog.list_transforms()))
    print("validators:", ", ".join(catalog.list_validators()))


@contextmanager
def _open_output(
    path: str | None,
    *,
    no_clobber: bool = False,
    encoding: str = "utf-8",
) -> Iterator[TextIO]:
    if path is None:
        with _reconfigured_stdout(encoding) as stream:
            yield stream
        return
    with open_output_path(path, no_clobber=no_clobber, encoding=encoding) as stream:
        yield stream


@contextmanager
def _reconfigured_stdout(encoding: str) -> Iterator[TextIO]:
    stream = sys.stdout
    reconfigure = getattr(stream, "reconfigure", None)
    if not callable(reconfigure):
        yield stream
        return
    old_encoding = stream.encoding
    old_errors = getattr(stream, "errors", None)
    reconfigure(encoding=encoding)
    try:
        yield stream
    finally:
        restore: dict[str, str] = {}
        if old_encoding is not None:
            restore["encoding"] = old_encoding
        if old_errors is not None:
            restore["errors"] = old_errors
        if restore:
            reconfigure(**restore)


def _stream(
    engine: Engine,
    stream: TextIO,
    *,
    progress_every: int,
    batch_rows: int,
    resume_from: int,
) -> int:
    """Write rows and flush periodically, emitting an ``engine_progress`` event
    every ``progress_every`` rows (TODO OBS-006). Skips the first
    ``resume_from`` rows before writing any output (TODO SCALE-003).

    Returns the total row count actually written for use by --verbose
    summaries.
    """
    count = 0
    written = 0
    started = time.perf_counter()
    flush_at = batch_rows
    for row in engine:
        count += 1
        if count <= resume_from:
            continue
        stream.write(f"{row}\n")
        written += 1
        if written and written % flush_at == 0:
            # Block-buffered streams (e.g. files) rely on the interpreter
            # for write batching; this controls only the flush cadence.
            stream.flush()
        if progress_every and written % progress_every == 0:
            _emit_progress(written, time.perf_counter() - started)
    return written


def _emit_progress(rows: int, elapsed: float) -> None:
    """Emit one progress event via the ``ton`` logger (TODO OBS-006).

    The CLI installs :class:`_ProgressJSONHandler` on the logger when
    ``--progress`` is set so the event is surfaced as a JSON-on-stderr
    line. Other consumers can filter by ``event="engine_progress"``
    instead of grepping stderr.
    """
    rate = round(rows / elapsed, 1) if elapsed > 0 else None
    _logger.info(
        "engine_progress rows=%d elapsed=%.3fs",
        rows,
        elapsed,
        extra={
            "event": LogEvent.ENGINE_PROGRESS.value,
            "rows": rows,
            "elapsed_seconds": round(elapsed, 3),
            "rows_per_second": rate,
        },
    )


class _ProgressJSONHandler(logging.Handler):
    """Stderr handler that writes ``engine_progress`` events as JSON.

    Other log events are ignored so the JSON-on-stderr stream stays
    parseable (TODO OBS-006).
    """

    def __init__(self) -> None:
        super().__init__(level=logging.INFO)

    def emit(self, record: logging.LogRecord) -> None:
        if getattr(record, "event", None) != "engine_progress":
            return
        payload = {
            "rows": getattr(record, "rows", None),
            "elapsed_seconds": getattr(record, "elapsed_seconds", None),
            "rows_per_second": getattr(record, "rows_per_second", None),
        }
        sys.stderr.write(json.dumps(payload) + "\n")
        sys.stderr.flush()


def _install_progress_handler() -> None:
    """Attach :class:`_ProgressJSONHandler` to the ``ton`` logger once."""
    for handler in _logger.handlers:
        if isinstance(handler, _ProgressJSONHandler):
            return
    _logger.addHandler(_ProgressJSONHandler())
    if _logger.level == logging.NOTSET or _logger.level > logging.INFO:
        _logger.setLevel(logging.INFO)


def _report(rows: int, elapsed: float) -> None:
    rate = round(rows / elapsed, 1) if elapsed > 0 else float("inf")
    print(
        f"ton: wrote {rows} rows in {elapsed:.3f}s ({rate} rows/s)",
        file=sys.stderr,
    )
