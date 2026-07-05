"""
AI Pulse – Structured Logging
==============================
Uses structlog for structured, contextual logging.
Outputs JSON in production, colored console in development.
"""

from __future__ import annotations

import logging
import sys
from typing import Any

import structlog
from structlog.types import EventDict, WrappedLogger


def add_app_context(
    logger: WrappedLogger, method_name: str, event_dict: EventDict
) -> EventDict:
    """Add application-level context to every log entry."""
    event_dict["app"] = "ai-pulse"
    return event_dict


def setup_logging(log_level: str = "info", is_production: bool = False) -> None:
    """
    Configure structlog for the application.

    Args:
        log_level: Logging level (debug, info, warning, error, critical)
        is_production: If True, outputs JSON. If False, colored console output.
    """
    log_level_upper = log_level.upper()
    numeric_level = getattr(logging, log_level_upper, logging.INFO)

    # Configure standard library logging
    logging.basicConfig(
        format="%(message)s",
        stream=sys.stdout,
        level=numeric_level,
    )

    # Shared processors applied to all log entries
    shared_processors: list[Any] = [
        structlog.contextvars.merge_contextvars,
        structlog.stdlib.add_logger_name,
        structlog.stdlib.add_log_level,
        structlog.stdlib.PositionalArgumentsFormatter(),
        structlog.processors.TimeStamper(fmt="iso"),
        structlog.processors.StackInfoRenderer(),
        add_app_context,
    ]

    if is_production:
        # Production: JSON output for log aggregators (Datadog, CloudWatch, etc.)
        processors = shared_processors + [
            structlog.processors.format_exc_info,
            structlog.processors.JSONRenderer(),
        ]
    else:
        # Development: Rich colored console output
        processors = shared_processors + [
            structlog.processors.ExceptionPrettyPrinter(),
            structlog.dev.ConsoleRenderer(colors=True),
        ]

    structlog.configure(
        processors=processors,
        wrapper_class=structlog.stdlib.BoundLogger,
        context_class=dict,
        logger_factory=structlog.stdlib.LoggerFactory(),
        cache_logger_on_first_use=True,
    )


def get_logger(name: str = __name__) -> structlog.BoundLogger:
    """
    Get a named logger instance.

    Usage:
        logger = get_logger(__name__)
        logger.info("event", key="value")
    """
    return structlog.get_logger(name)


# Module-level logger for the logging module itself
logger = get_logger(__name__)
