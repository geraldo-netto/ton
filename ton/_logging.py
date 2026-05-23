"""Library-level logger for TON (OBS-003).

Single module-scoped :class:`logging.Logger` named ``ton``. Library code
emits structured INFO events at structural boundaries:

* engine construction (rows, declared types, paired flag),
* row-count milestones (opt-in via :class:`ton._engine.Engine`'s
  ``milestone_rows`` argument),
* generator-registry discovery and entry-point loading.

Library callers attach a handler the usual way::

    import logging
    logging.basicConfig(level=logging.INFO)
    # ...or wire a handler to ``logging.getLogger("ton")`` directly.

A :class:`logging.NullHandler` is attached at import time so library
code never emits the "No handlers could be found" warning when no
caller has configured logging.
"""

from __future__ import annotations

import logging

LOGGER_NAME = "ton"

logger = logging.getLogger(LOGGER_NAME)
logger.addHandler(logging.NullHandler())


def configure_stderr(
    level: int = logging.INFO,
    *,
    fmt: str | None = None,
) -> logging.Handler:
    """Attach a stderr handler to the ``ton`` logger and return it.

    The CLI calls this when ``--log-level`` is passed. Library callers
    generally prefer to wire their own handler instead of using this
    helper so the formatter and destination stay under their control.
    """
    handler = logging.StreamHandler()
    handler.setLevel(level)
    handler.setFormatter(
        logging.Formatter(fmt or "ton: %(levelname)s %(message)s")
    )
    logger.addHandler(handler)
    if logger.level == logging.NOTSET or level < logger.level:
        logger.setLevel(level)
    return handler
