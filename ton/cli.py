"""Command-line entry point for TON."""

from __future__ import annotations

import argparse
import json
import logging
import os
import sys
import time
from collections.abc import Callable, Iterator, Sequence
from contextlib import contextmanager
from dataclasses import dataclass
from typing import TextIO, cast

from . import __version__, api
from ._logging import terminal_failure_fields
from ._output import (
    EncodingNormalizingStream,
    OutputPublishedError,
    PartialOutputCommitError,
    open_output_path,
)
from ._proofaudit import ProofAuditWriteError, ProofAuditWriter
from ._proofcheck import PROOF_MODES, ProofFailureSinkError
from .api import (
    ConfigError,
    Engine,
    EngineOptions,
    LogEvent,
    PipelineStageError,
    ProofError,
    RegistryError,
    TemplateError,
    ValidationError,
    configure_stderr,
)
from .api import logger as _logger

_progress_logger = logging.getLogger("ton.progress")

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


@dataclass
class _WriteState:
    rows_written: int = 0


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
        help="Refuse to overwrite an existing --output or --proof-report file.",
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
        "--proof-report",
        metavar="PATH",
        help="With --proof-check=audit, stream every failure as UTF-8 JSON Lines to PATH.",
    )
    parser.add_argument(
        "--redact-proof-failures",
        action="store_true",
        help="Mask values, paired ids, reasons, and field specs in proof diagnostics and logs.",
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
        type=_entry_point_selector,
        metavar="GROUP:DISTRIBUTION:NAME",
        dest="entry_point_allowlist",
        default=[],
        help="Allow only this exact entry-point provider. May be passed more than once.",
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
    """argparse helper rejecting negative integers (REL-017)."""
    parsed = int(value)
    if parsed < 0:
        raise argparse.ArgumentTypeError(f"must be >= 0 (got {value})")
    return parsed


def _positive_int(value: str) -> int:
    parsed = int(value)
    if parsed < 1:
        raise argparse.ArgumentTypeError(f"must be >= 1 (got {value})")
    return parsed


def _entry_point_selector(value: str) -> api.EntryPointSelector:
    try:
        return api.EntryPointSelector.parse(value)
    except api.RegistryError as exc:
        raise argparse.ArgumentTypeError(str(exc)) from exc


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
        # attached via ``--log-level`` (OBS-008); the print line
        # keeps the v1 "ton: ..." stderr contract for users without a
        # log handler configured.
        _logger.exception(
            "cli_unexpected_error type=%s",
            type(exc).__name__,
            extra={"event": LogEvent.CLI_UNEXPECTED_ERROR.value, "error_type": type(exc).__name__},
        )
        _log_terminal_failure("unexpected", 3, 0, 0, exc)
        print(f"ton: unexpected error: {type(exc).__name__}: {exc}", file=sys.stderr)
        return 3


def _run_inner(args: argparse.Namespace) -> int:
    option_error = _validate_proof_report_args(args)
    if option_error is not None:
        return option_error
    if args.list_namespaces:
        result = _map_config_errors(lambda: _print_namespaces(args))
        return result if isinstance(result, int) else 0
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


def _validate_proof_report_args(args: argparse.Namespace) -> int | None:
    if args.proof_report is not None and args.proof_check != "audit":
        print("ton: --proof-report requires --proof-check=audit", file=sys.stderr)
        return 2
    if (
        args.proof_report is not None
        and args.output is not None
        and _same_output_target(args.proof_report, args.output)
    ):
        print("ton: --proof-report and --output must use different paths", file=sys.stderr)
        return 2
    return None


def _same_output_target(first: str, second: str) -> bool:
    """Return whether two path spellings identify the same output target."""
    canonical_first = os.path.normcase(os.path.realpath(first))
    canonical_second = os.path.normcase(os.path.realpath(second))
    if canonical_first == canonical_second:
        return True
    samefile = getattr(os.path, "samefile", None)
    if not callable(samefile):
        return False
    try:
        return bool(samefile(first, second))
    except OSError:
        return False


def _validate_config(args: argparse.Namespace) -> int:
    """Validate the config with catalog-aware diagnostics and exit.

    Uses :func:`ton.api.validate_config` rather than constructing an
    Engine so unknown type/transform references are reported with the
    available-name lists and plugin-namespace diagnostics, keeping CLI
    ``--validate`` aligned with the library validation path.
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


def _map_config_errors[T](operation: Callable[[], T]) -> T | int:
    """Run a config operation and map its domain failures to CLI exit codes.

    Every exit here is terminal, so each one emits ``cli_failed`` -- these
    paths used to return silently, leaving a missing config with no terminal
    record at all (OBS-009). No rows can have been written yet, so the counts
    are zero.
    """
    try:
        return operation()
    except FileNotFoundError as exc:
        return _fail_before_generation("output", 1, exc, f"ton: {exc}")
    except RegistryError as exc:
        return _fail_before_generation("validation", 2, exc, f"ton: plugin error: {exc}")
    except (ConfigError, TemplateError, json.JSONDecodeError) as exc:
        return _fail_before_generation("validation", 2, exc, f"ton: invalid config: {exc}")


def _fail_before_generation(category: str, exit_code: int, exc: Exception, message: str) -> int:
    """Record and report a failure that happened before any row was generated."""
    _log_terminal_failure(category, exit_code, 0, 0, exc)
    print(message, file=sys.stderr)
    return exit_code


def _warn_resume_overshoot(engine: Engine, resume_from: int) -> None:
    if resume_from >= engine.total_rows and engine.total_rows > 0:
        # REL-018: a value that skips past every row produces a silent
        # empty file. Surface this through both stderr and the logger
        # so the user actually notices.
        _logger.warning(
            "resume_overshoot resume_from=%d total_rows=%d",
            resume_from,
            engine.total_rows,
            extra={
                "event": LogEvent.RESUME_OVERSHOOT.value,
                "resume_from": resume_from,
                "total_rows": engine.total_rows,
            },
        )
        print(
            f"ton: --resume-from={resume_from} >= total rows "
            f"({engine.total_rows}); output will be empty",
            file=sys.stderr,
        )


def _execute(engine: Engine, args: argparse.Namespace, encoding: str) -> int:
    _warn_resume_overshoot(engine, args.resume_from)
    started = time.perf_counter()
    data_published = False
    write_state = _WriteState()
    try:
        with _open_proof_report(
            args.proof_report,
            no_clobber=args.no_clobber,
        ) as failure_sink:
            engine.set_proof_failure_sink(failure_sink)
            with _open_output(args.output, no_clobber=args.no_clobber, encoding=encoding) as stream:
                _stream(
                    engine,
                    stream,
                    progress_every=args.progress,
                    batch_rows=args.batch_rows,
                    resume_from=args.resume_from,
                    write_state=write_state,
                )
            data_published = args.output is not None
    except (ProofAuditWriteError, ProofFailureSinkError) as exc:
        return _handle_proof_report_error(
            engine, args, exc, data_published, write_state.rows_written
        )
    except OSError as exc:
        if (
            isinstance(exc, OutputPublishedError)
            and args.output is not None
            and args.proof_report is not None
        ):
            return _report_partial_commit(
                engine,
                PartialOutputCommitError((exc.path,), args.proof_report, exc),
                write_state.rows_written,
            )
        _log_terminal_failure("output", 1, write_state.rows_written, engine.total_rows, exc)
        print(f"ton: cannot write output: {exc}", file=sys.stderr)
        return 1
    except PipelineStageError as exc:
        # A component raised at row time: an unexpected failure (exit 3), not
        # an invalid config (exit 2). Reported with the real row counts, which
        # the top-level safety net cannot know (CLI-002).
        _log_terminal_failure("pipeline", 3, write_state.rows_written, engine.total_rows, exc)
        print(f"ton: unexpected error: {exc}", file=sys.stderr)
        return 3
    except ProofError as exc:
        _log_terminal_failure("proof", 2, write_state.rows_written, engine.total_rows, exc)
        print(f"ton: proof failed: {exc}", file=sys.stderr)
        return 2
    except ValidationError as exc:
        _log_terminal_failure("validation", 2, write_state.rows_written, engine.total_rows, exc)
        print(f"ton: validation failed: {exc}", file=sys.stderr)
        return 2
    except TemplateError as exc:
        _log_terminal_failure("validation", 2, write_state.rows_written, engine.total_rows, exc)
        print(f"ton: invalid config: {exc}", file=sys.stderr)
        return 2
    if args.verbose:
        _report(write_state.rows_written, time.perf_counter() - started)
    if args.proof_check == "audit":
        _report_proof_audit(engine, args.proof_report)
    return 0


def _handle_proof_report_error(
    engine: Engine,
    args: argparse.Namespace,
    error: Exception,
    data_published: bool,
    rows_written: int,
) -> int:
    if data_published and args.output is not None and args.proof_report is not None:
        published = [args.output]
        if isinstance(error.__cause__, OutputPublishedError):
            published.append(error.__cause__.path)
        return _report_partial_commit(
            engine,
            PartialOutputCommitError(tuple(published), args.proof_report, error),
            rows_written,
        )
    _log_terminal_failure("output", 1, rows_written, engine.total_rows, error)
    print(f"ton: cannot write proof report: {error}", file=sys.stderr)
    return 1


def _report_partial_commit(
    engine: Engine,
    error: PartialOutputCommitError,
    rows_written: int,
) -> int:
    _log_terminal_failure(
        "output",
        1,
        rows_written,
        engine.total_rows,
        error,
    )
    print(f"ton: {error}", file=sys.stderr)
    return 1


def _log_terminal_failure(
    category: str,
    exit_code: int,
    rows_written: int,
    total_rows: int,
    exc: Exception,
) -> None:
    fields = terminal_failure_fields(
        category,
        exit_code,
        rows_written=rows_written,
        total_rows=total_rows,
        error_type=type(exc).__name__,
    )
    _logger.error(
        "cli_failed category=%s exit_code=%d rows_written=%d total_rows=%d error_type=%s",
        category,
        exit_code,
        rows_written,
        total_rows,
        type(exc).__name__,
        extra=fields,
    )


def _report_proof_audit(engine: Engine, report_path: str | None = None) -> None:
    """Print the audit proof-check summary to stderr.

    Audit mode collects failures instead of aborting, so a normal run
    exits 0 and the user would otherwise never learn that any value
    failed its proof. Surface the count and point at the structured
    ``proof_check_failed`` log events that carry the per-row detail.
    """
    count = engine.proof_failure_count
    if count == 0:
        print("ton: proof-check audit: all generated values passed", file=sys.stderr)
        return
    print(
        f"ton: proof-check audit: {count} value(s) failed"
        + (
            f"; details written to {report_path}"
            if report_path is not None
            else "; use --proof-report PATH for per-value detail"
        ),
        file=sys.stderr,
    )


def _catalog_from_args(args: argparse.Namespace) -> api.ExtensionCatalog:
    """Build the extension catalog implied by the entry-point flags.

    Single source of truth for the catalog used by engine construction,
    ``--validate``, and ``--list-namespaces`` so all three observe the
    same plugin surface (CFG-003).
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
        # stdout bypasses open_output_path, so apply the same normalization
        # here rather than leaving one writer with raw codec errors (REL-027).
        with _reconfigured_stdout(encoding) as stream:
            yield cast(TextIO, EncodingNormalizingStream(stream))
        return
    with open_output_path(path, no_clobber=no_clobber, encoding=encoding) as stream:
        yield stream


@contextmanager
def _open_proof_report(
    path: str | None,
    *,
    no_clobber: bool,
) -> Iterator[ProofAuditWriter | None]:
    if path is None:
        yield None
        return
    report = open_output_path(path, no_clobber=no_clobber, encoding="utf-8")
    stream = _translate_proof_report_io(report.__enter__)
    try:
        yield ProofAuditWriter(stream)
    except BaseException:
        error = sys.exc_info()
        suppress_error = _translate_proof_report_io(lambda: report.__exit__(*error))
        if not suppress_error:
            raise
    else:
        _translate_proof_report_io(lambda: report.__exit__(None, None, None))


def _translate_proof_report_io[T](operation: Callable[[], T]) -> T:
    """Map only proof-report resource I/O to its CLI-specific error."""
    try:
        return operation()
    except ProofAuditWriteError:
        raise
    except OSError as exc:
        raise ProofAuditWriteError(str(exc)) from exc


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
    write_state: _WriteState,
) -> int:
    """Write rows and flush periodically, emitting an ``engine_progress`` event
    every ``progress_every`` rows (OBS-006). Skips the first
    ``resume_from`` rows before writing any output (SCALE-003).

    Returns the total row count actually written for use by --verbose
    summaries.
    """
    count = 0
    started = time.perf_counter()
    flush_at = batch_rows
    for row in engine:
        count += 1
        if count <= resume_from:
            continue
        # open_output_path normalizes codec failures to OutputEncodingError.
        stream.write(f"{row}\n")
        write_state.rows_written += 1
        if write_state.rows_written % flush_at == 0:
            # Block-buffered streams (e.g. files) rely on the interpreter
            # for write batching; this controls only the flush cadence.
            stream.flush()
        if progress_every and write_state.rows_written % progress_every == 0:
            _emit_progress(write_state.rows_written, time.perf_counter() - started)
    return write_state.rows_written


def _emit_progress(rows: int, elapsed: float) -> None:
    """Emit one progress event via the ``ton`` logger (OBS-006).

    The CLI installs :class:`_ProgressJSONHandler` on the logger when
    ``--progress`` is set so the event is surfaced as a JSON-on-stderr
    line. Other consumers can filter by ``event="engine_progress"``
    instead of grepping stderr.
    """
    rate = _rows_per_second(rows, elapsed)
    extra = {
        "event": LogEvent.ENGINE_PROGRESS.value,
        "rows": rows,
        "elapsed_seconds": round(elapsed, 3),
        "rows_per_second": rate,
    }
    _logger.info(
        "engine_progress rows=%d elapsed=%.3fs",
        rows,
        elapsed,
        extra=extra,
    )
    _progress_logger.info("engine_progress rows=%d elapsed=%.3fs", rows, elapsed, extra=extra)


class _ProgressJSONHandler(logging.Handler):
    """Stderr handler that writes ``engine_progress`` events as JSON.

    Other log events are ignored so the JSON-on-stderr stream stays
    parseable (OBS-006).
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
    for handler in _progress_logger.handlers:
        if isinstance(handler, _ProgressJSONHandler):
            return
    _progress_logger.addHandler(_ProgressJSONHandler())
    _progress_logger.setLevel(logging.INFO)
    _progress_logger.propagate = False


def _report(rows: int, elapsed: float) -> None:
    rate = _rows_per_second(rows, elapsed)
    rate_text = str(rate) if rate is not None else "unknown"
    print(
        f"ton: wrote {rows} rows in {elapsed:.3f}s ({rate_text} rows/s)",
        file=sys.stderr,
    )


def _rows_per_second(rows: int, elapsed: float) -> float | None:
    return round(rows / elapsed, 1) if elapsed > 0 else None
