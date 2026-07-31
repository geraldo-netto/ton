"""Reusable output-target policy and sink primitives."""

from __future__ import annotations

import os
import stat
import tempfile
from collections.abc import Iterator
from contextlib import contextmanager, suppress
from typing import TextIO, cast

from ._logging import LogEvent
from ._logging import logger as _logger


class OutputEncodingError(OSError):
    """A configured codec could not encode generated output.

    Encoding failures are output errors, not invalid configuration: the
    codec is valid, but a generated value is not representable in it.
    ``field_name`` identifies a field when the failing value can be traced
    before row rendering; otherwise it is ``None`` for the rendered row.
    """

    def __init__(self, encoding: str, reason: str, *, field_name: str | None = None) -> None:
        self.encoding = encoding
        self.field_name = field_name
        self.reason = reason
        context = f"field {field_name!r}" if field_name is not None else "rendered row"
        super().__init__(f"cannot encode {context} as {encoding!r}: {reason}")


class OutputPublishedError(OSError):
    """Publication changed the destination but durability confirmation failed."""

    def __init__(self, path: str, cause: OSError) -> None:
        self.path = path
        self.destination_changed = True
        self.cause = cause
        super().__init__(
            f"output was published to {path!r}, but finalization failed: {cause}; "
            "inspect the destination before retrying"
        )


def validate_output_target(path: str, *, no_clobber: bool = False) -> bool:
    """Validate ``path`` and return whether it names an existing FIFO."""
    if os.path.islink(path):
        raise OSError(f"refusing to replace symbolic-link output: {path}")
    if not os.path.exists(path):
        return False
    target = os.stat(path)
    if not (stat.S_ISREG(target.st_mode) or stat.S_ISFIFO(target.st_mode)):
        _logger.error(
            "output_special_file_rejected path=%s mode=%o",
            path,
            target.st_mode,
            extra={
                "event": LogEvent.OUTPUT_SPECIAL_FILE_REJECTED.value,
                "path": path,
                "mode": target.st_mode,
            },
        )
        raise OSError(f"refusing to write to special file (not a regular file): {path}")
    if no_clobber:
        raise OSError(f"refusing to overwrite existing file: {path}")
    _logger.warning(
        "output_overwrite path=%s",
        path,
        extra={"event": LogEvent.OUTPUT_OVERWRITE.value, "path": path},
    )
    return stat.S_ISFIFO(target.st_mode)


@contextmanager
def atomic_output(
    path: str,
    *,
    encoding: str = "utf-8",
    mode: int = 0o600,
    no_clobber: bool = False,
) -> Iterator[TextIO]:
    """Yield a temporary stream and atomically replace ``path`` on success."""
    directory = os.path.dirname(os.path.abspath(path)) or "."
    basename = os.path.basename(path)
    tmp_name = ""
    published = False
    try:
        with tempfile.NamedTemporaryFile(
            "w",
            encoding=encoding,
            newline="\n",
            dir=directory,
            prefix=f".{basename}.",
            suffix=".tmp",
            delete=False,
        ) as stream:
            tmp_name = stream.name
            yield cast(TextIO, stream)
            stream.flush()
            os.fsync(stream.fileno())
        os.chmod(tmp_name, mode)
        try:
            if no_clobber:
                os.link(tmp_name, path)
                published = True
                os.unlink(tmp_name)
            else:
                os.replace(tmp_name, path)
                published = True
            tmp_name = ""
            _fsync_directory(directory)
        except OSError as exc:
            if published:
                raise OutputPublishedError(path, exc) from exc
            raise
    finally:
        if tmp_name:
            with suppress(FileNotFoundError):
                os.unlink(tmp_name)


@contextmanager
def open_output_path(
    path: str,
    *,
    no_clobber: bool = False,
    encoding: str = "utf-8",
) -> Iterator[TextIO]:
    """Open a validated path with FIFO or atomic regular-file semantics."""
    if validate_output_target(path, no_clobber=no_clobber):
        with open(path, "w", encoding=encoding, newline="\n") as stream:
            yield stream
        return
    with atomic_output(
        path,
        encoding=encoding,
        mode=target_mode(path),
        no_clobber=no_clobber,
    ) as stream:
        yield stream


def target_mode(path: str) -> int:
    """Preserve destination permissions or apply the process file-creation mask."""
    try:
        return stat.S_IMODE(os.stat(path).st_mode)
    except FileNotFoundError:
        directory = os.path.dirname(os.path.abspath(path)) or "."
        return _new_file_mode(directory)


def _new_file_mode(directory: str) -> int:
    """Probe default file permissions without mutating the process umask."""
    with tempfile.TemporaryDirectory(prefix=".ton-mode.", dir=directory) as probe_dir:
        probe_path = os.path.join(probe_dir, "probe")
        descriptor = os.open(
            probe_path,
            os.O_WRONLY | os.O_CREAT | os.O_EXCL,
            0o666,
        )
        try:
            return stat.S_IMODE(os.fstat(descriptor).st_mode)
        finally:
            os.close(descriptor)


def _fsync_directory(directory: str) -> None:
    """Persist a published directory entry where directory fsync is supported."""
    if os.name == "nt":
        return
    flags = os.O_RDONLY | getattr(os, "O_DIRECTORY", 0)
    descriptor = os.open(directory, flags)
    try:
        os.fsync(descriptor)
    finally:
        os.close(descriptor)
