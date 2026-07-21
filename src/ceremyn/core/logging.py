"""Structured logging setup.

dev environment  -> human-readable colored console output
prod environment -> one JSON object per line (machine-parseable, audit-friendly)

Call `configure_logging()` exactly once at process startup, then obtain loggers
anywhere with `structlog.get_logger(__name__)`.
"""

import logging
import sys
from collections import deque
from typing import Any

import structlog

from ceremyn.config import Settings

# Bounded in-memory tail of recent log events, for the dashboard's "System Logs"
# page (`api/runtime.py::_LogSourceAdapter`) -- nothing else retains structured
# logs anywhere for that purpose, so without this the Logs page is permanently
# empty regardless of real application log volume.
_RING_BUFFER: deque[dict[str, Any]] = deque(maxlen=1000)


def recent_log_entries(limit: int) -> list[dict[str, Any]]:
    """The most recent `limit` captured log events, newest first."""
    return list(reversed(_RING_BUFFER))[:limit]


def _capture_to_ring_buffer(
    logger: object, method_name: str, event_dict: structlog.typing.EventDict
) -> structlog.typing.EventDict:
    _RING_BUFFER.append(dict(event_dict))
    return event_dict


def configure_logging(settings: Settings) -> None:
    level = getattr(logging, settings.log_level.upper(), logging.INFO)

    logging.basicConfig(format="%(message)s", stream=sys.stdout, level=level)

    shared_processors: list[structlog.typing.Processor] = [
        structlog.contextvars.merge_contextvars,
        structlog.stdlib.add_logger_name,
        structlog.stdlib.add_log_level,
        structlog.processors.TimeStamper(fmt="iso", utc=True),
        structlog.processors.StackInfoRenderer(),
        _capture_to_ring_buffer,
    ]

    renderer: structlog.typing.Processor
    if settings.environment == "prod":
        # format_exc_info must precede the JSON renderer; ConsoleRenderer
        # formats exceptions itself and must NOT be paired with it.
        shared_processors.append(structlog.processors.format_exc_info)
        renderer = structlog.processors.JSONRenderer()
    else:
        renderer = structlog.dev.ConsoleRenderer()

    structlog.configure(
        processors=[*shared_processors, renderer],
        wrapper_class=structlog.make_filtering_bound_logger(level),
        logger_factory=structlog.stdlib.LoggerFactory(),
        cache_logger_on_first_use=True,
    )
