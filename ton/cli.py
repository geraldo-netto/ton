"""Command-line entry point for TON."""

from __future__ import annotations

import argparse
import json
import logging
import os
import stat
import sys
import tempfile
import time
from collections.abc import Iterator, Sequence
from contextlib import contextmanager, suppress
from random import Random
from typing import TextIO, cast

from . import __version__, api
from .api import ConfigError, Engine, LogEvent, TemplateError, configure_stderr
from .api import logger as _logger

_LOG_LEVELS = {
    "debug": logging.DEBUG,
    "info": logging.INFO,
    "warning": logging.WARNING,
    "error": logging.ERROR,
    "critical": logging.CRITICAL,
}

#: Default rows per write() syscall when streaming to a file. Picked to
#: be big enough to amortize Python attribute / interpreter overhead but
#: small enough to keep peak memory bounded for wide rows. Overridable
#: via ``--batch-rows``.
_DEFAULT_BATCH_ROWS = 1024


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="ton",
        description="TON: mass data generator. Render rows from a JSON template.",
    )
    parser.add_argument("config", help="Path to the JSON config file.")
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
        help=(
            "Buffer N rendered rows per write() syscall. Larger values "
            "amortize syscall overhead at the cost of peak memory for "
            "wide rows."
        ),
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
        help="Validate the config and exit without generating rows.",
    )
    parser.add_argument(
        "--entry-points",
        action="store_true",
        help="Load trusted third-party generators from the ton.generators entry-point group.",
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
    built = _prepare_engine(args)
    if isinstance(built, int):
        return built
    if args.validate:
        print("ton: config valid", file=sys.stderr)
        return 0
    engine = built
    return _execute(engine, args)


def _prepare_engine(args: argparse.Namespace) -> Engine | int:
    """Build the Engine or return a non-zero exit code on config errors."""
    try:
        return _build_engine(args)
    except FileNotFoundError as exc:
        print(f"ton: {exc}", file=sys.stderr)
        return 1
    except (ConfigError, TemplateError, json.JSONDecodeError) as exc:
        print(f"ton: invalid config: {exc}", file=sys.stderr)
        return 2


def _execute(engine: Engine, args: argparse.Namespace) -> int:
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
        with _open_output(args.output, no_clobber=args.no_clobber) as stream:
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
    if args.verbose:
        _report(rows_written, time.perf_counter() - started)
    return 0


def _build_engine(args: argparse.Namespace) -> Engine:
    rng = Random(args.seed) if args.seed is not None else Random()
    config = api.load_config(args.config)
    registry = None
    if args.entry_points or args.entry_point_allowlist:
        allowed = set(args.entry_point_allowlist) or None
        registry = api.build_registry(
            include_entry_points=True,
            allowed_entry_points=allowed,
        )
    # --progress already prints JSON; reuse the same interval as the
    # engine's logger milestone so structured handlers see the same
    # boundaries.
    return Engine.from_config(
        config,
        registry=registry,
        rng=rng,
        milestone_rows=args.progress,
    )


@contextmanager
def _open_output(path: str | None, *, no_clobber: bool = False) -> Iterator[TextIO]:
    if path is None:
        yield sys.stdout
        return
    exists = os.path.exists(path)
    if exists:
        # SEC-005: ``open(path, 'w')`` will happily redirect output into
        # ``/dev/sda`` or any other block / character device the user
        # can write to. Refuse explicitly so a stray ``-o`` argument
        # cannot scribble over hardware nodes or named pipes.
        st = os.stat(path)
        if not (stat.S_ISREG(st.st_mode) or stat.S_ISFIFO(st.st_mode)):
            _logger.error(
                "output_special_file_rejected path=%s mode=%o",
                path,
                st.st_mode,
                extra={
                    "event": LogEvent.OUTPUT_SPECIAL_FILE_REJECTED.value,
                    "path": path,
                    "mode": st.st_mode,
                },
            )
            raise OSError(
                f"refusing to write to special file (not a regular file): {path}"
            )
        if no_clobber:
            raise OSError(f"refusing to overwrite existing file: {path}")
        _logger.warning(
            "output_overwrite path=%s",
            path,
            extra={"event": LogEvent.OUTPUT_OVERWRITE.value, "path": path},
        )
    if exists and stat.S_ISFIFO(os.stat(path).st_mode):
        with open(path, "w", encoding="utf-8") as fh:
            yield fh
        return
    with _open_atomic_output(path) as stream:
        yield stream


@contextmanager
def _open_atomic_output(path: str) -> Iterator[TextIO]:
    directory = os.path.dirname(os.path.abspath(path)) or "."
    basename = os.path.basename(path)
    tmp_name = ""
    try:
        with tempfile.NamedTemporaryFile(
            "w",
            encoding="utf-8",
            dir=directory,
            prefix=f".{basename}.",
            suffix=".tmp",
            delete=False,
        ) as fh:
            tmp_name = fh.name
            yield cast(TextIO, fh)
            fh.flush()
            os.fsync(fh.fileno())
        os.replace(tmp_name, path)
        tmp_name = ""
    finally:
        if tmp_name:
            with suppress(FileNotFoundError):
                os.unlink(tmp_name)


def _stream(
    engine: Engine,
    stream: TextIO,
    *,
    progress_every: int,
    batch_rows: int,
    resume_from: int,
) -> int:
    """Write rows in batches, emitting a logger ``engine_progress`` event
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
        stream.write(row)
        stream.write("\n")
        written += 1
        if written and written % flush_at == 0:
            # Block-buffered streams (e.g. files) still rely on the
            # interpreter for syscall batching; the explicit flush
            # boundary keeps wide rows from sitting in memory past
            # ``batch_rows`` (TODO PERF-011).
            stream.flush()
        if progress_every and count % progress_every == 0:
            _emit_progress(count, time.perf_counter() - started)
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
