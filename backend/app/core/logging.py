"""
Structured JSON logging.

Every log line is a single JSON object so it can be shipped to any log
aggregator as-is. A `request_id` contextvar is bound per-request by the
telemetry middleware and automatically included on every line emitted while
handling that request. It is the id that shows up in error responses.
"""
from __future__ import annotations

import contextvars
import json
import logging
import sys
from datetime import UTC, datetime

# Per-request correlation id, set by telemetry middleware.
request_id_ctx: contextvars.ContextVar[str | None] = contextvars.ContextVar(
    "request_id", default=None
)


class JsonFormatter(logging.Formatter):
    """Render each record as one compact JSON object."""

    def format(self, record: logging.LogRecord) -> str:
        payload: dict[str, object] = {
            "ts": datetime.now(UTC).isoformat(),
            "level": record.levelname,
            "logger": record.name,
            "message": record.getMessage(),
        }
        rid = request_id_ctx.get()
        if rid:
            payload["request_id"] = rid

        # Attach any structured extras passed via logger.info(..., extra={...}).
        for key, value in record.__dict__.items():
            if key in _RESERVED or key.startswith("_"):
                continue
            payload.setdefault(key, value)

        if record.exc_info:
            payload["exception"] = self.formatException(record.exc_info)

        return json.dumps(payload, default=str)


_RESERVED = {
    "name", "msg", "args", "levelname", "levelno", "pathname", "filename",
    "module", "exc_info", "exc_text", "stack_info", "lineno", "funcName",
    "created", "msecs", "relativeCreated", "thread", "threadName",
    "processName", "process", "message", "taskName",
}


def configure_logging(level: str = "INFO") -> None:
    """Install the JSON formatter on the root logger (idempotent)."""
    root = logging.getLogger()
    root.setLevel(level.upper())

    # Replace existing handlers so we don't double-log under uvicorn reload.
    for handler in list(root.handlers):
        root.removeHandler(handler)

    handler = logging.StreamHandler(sys.stdout)
    handler.setFormatter(JsonFormatter())
    root.addHandler(handler)

    # Quiet noisy libraries; let our app logger speak.
    for noisy in ("uvicorn.access", "httpx", "httpcore", "sentence_transformers"):
        logging.getLogger(noisy).setLevel("WARNING")


def get_logger(name: str) -> logging.Logger:
    return logging.getLogger(name)
