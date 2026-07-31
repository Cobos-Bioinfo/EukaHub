"""Structured JSON logging for the API.

One JSON object per line to stdout, so a container runtime or log aggregator
parses records without regex. Level comes from ``LOG_LEVEL`` (default INFO).
Call :func:`configure_logging` once at startup — the app does this in its
lifespan (see ``main.py``). Structured fields ride along via logging's
``extra=`` and are merged into the JSON object.
"""

from __future__ import annotations

import json
import logging
import os
import sys
from datetime import UTC, datetime

# Standard LogRecord attribute names, discovered from a sample record so this
# tracks the running Python version; used to separate caller ``extra=`` fields
# (which we emit) from the record's built-ins (which we render explicitly).
_RESERVED = frozenset(
    logging.LogRecord("", 0, "", 0, "", (), None).__dict__
) | {"message", "asctime", "taskName"}


class JsonFormatter(logging.Formatter):
    """Render a log record as a single-line JSON object."""

    def format(self, record: logging.LogRecord) -> str:
        payload: dict[str, object] = {
            "ts": datetime.fromtimestamp(record.created, tz=UTC).isoformat(),
            "level": record.levelname,
            "logger": record.name,
            "message": record.getMessage(),
        }
        if record.exc_info:
            payload["exc"] = self.formatException(record.exc_info)
        for key, value in record.__dict__.items():
            if key not in _RESERVED and not key.startswith("_"):
                payload[key] = value
        return json.dumps(payload, default=str)


def configure_logging() -> None:
    """Point the root logger at a single JSON stdout handler at ``LOG_LEVEL``.

    Idempotent — safe to call more than once (replaces handlers rather than
    stacking them). Uvicorn's loggers are set to propagate so their records
    flow through the same JSON handler instead of uvicorn's default format.
    """
    level = os.environ.get("LOG_LEVEL", "INFO").upper()
    handler = logging.StreamHandler(sys.stdout)
    handler.setFormatter(JsonFormatter())

    root = logging.getLogger()
    root.handlers = [handler]
    root.setLevel(level)

    for name in ("uvicorn", "uvicorn.error", "uvicorn.access"):
        logger = logging.getLogger(name)
        logger.handlers = []
        logger.propagate = True
