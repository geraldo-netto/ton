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


def validate_output_target(path: str, *, no_clobber: bool = False) -> bool:
    """Validate ``path`` and return whether it names an existing FIFO."""
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
) -> Iterator[TextIO]:
    """Yield a temporary stream and atomically replace ``path`` on success."""
    directory = os.path.dirname(os.path.abspath(path)) or "."
    basename = os.path.basename(path)
    tmp_name = ""
    try:
        with tempfile.NamedTemporaryFile(
            "w",
            encoding=encoding,
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
        os.replace(tmp_name, path)
        tmp_name = ""
    finally:
        if tmp_name:
            with suppress(FileNotFoundError):
                os.unlink(tmp_name)
