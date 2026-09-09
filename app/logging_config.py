"""
Structured logging setup using structlog with a JSON renderer.

configure_logging() is idempotent and called once at app import time.
get_logger() returns a bound structlog logger.

Log events emitted by the app:
  - request.completed : request_id, method, path, status_code, latency_ms, user_id
  - occ.conflict      : task_id, expected_version, actual_version
  - db.error          : error_type, message  (no stack trace in prod logs)
"""

import logging
import sys

import structlog

_configured = False


def configure_logging() -> None:
    global _configured
    if _configured:
        return

    # Route stdlib logging through to stdout at INFO.
    logging.basicConfig(
        format="%(message)s",
        stream=sys.stdout,
        level=logging.INFO,
    )

    structlog.configure(
        processors=[
            structlog.contextvars.merge_contextvars,
            structlog.processors.add_log_level,
            structlog.processors.TimeStamper(fmt="iso"),
            structlog.processors.StackInfoRenderer(),
            structlog.processors.JSONRenderer(),
        ],
        wrapper_class=structlog.make_filtering_bound_logger(logging.INFO),
        logger_factory=structlog.PrintLoggerFactory(),
        cache_logger_on_first_use=True,
    )
    _configured = True


def get_logger(name: str = "app"):
    """Return a structlog logger bound with the given name."""
    if not _configured:
        configure_logging()
    return structlog.get_logger(name)
