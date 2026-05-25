"""
Structured logging setup for HLTV API.

v3.5: Upgraded to structlog for structured, JSON-formatted logging
with context enrichment across async boundaries.
"""

from __future__ import annotations

import logging
import sys
from typing import Any

from src.config import LoggingConfig


def setup_logger(config: LoggingConfig | None = None) -> Any:
    """Configure and return the application logger.

    Uses structlog for structured logging with JSON output support.

    Args:
        config: Logging configuration.

    Returns:
        Configured logger instance.
    """
    if config is None:
        config = LoggingConfig()

    level = getattr(logging, config.level.upper(), logging.INFO)
    use_json = config.format == "json"

    try:
        import structlog

        # Configure structlog
        structlog.configure(
            processors=[
                structlog.contextvars.merge_contextvars,
                structlog.stdlib.filter_by_level,
                structlog.stdlib.add_logger_name,
                structlog.stdlib.add_log_level,
                structlog.stdlib.PositionalArgumentsFormatter(),
                structlog.processors.TimeStamper(fmt="iso"),
                structlog.processors.StackInfoRenderer(),
                structlog.processors.format_exc_info,
                structlog.dev.ConsoleRenderer() if not use_json else structlog.processors.JSONRenderer(),
            ],
            wrapper_class=structlog.stdlib.BoundLogger,
            context_class=dict,
            logger_factory=structlog.stdlib.LoggerFactory(),
            cache_logger_on_first_use=True,
        )

        logger = structlog.get_logger("hltv")
        logger.setLevel(level)

        # File logging
        if config.file:
            file_handler = logging.FileHandler(config.file, encoding="utf-8")
            file_handler.setLevel(level)
            file_handler.setFormatter(
                logging.Formatter(
                    "%(asctime)s | %(levelname)-8s | %(name)s | %(message)s"
                )
            )
            logging.getLogger("hltv").addHandler(file_handler)

        return logger

    except ImportError:
        # Fallback to stdlib logging if structlog not installed
        return _stdlib_logger(config)


def _stdlib_logger(config: LoggingConfig) -> Any:
    """Fallback logger using stdlib when structlog is not installed."""
    import logging as stdlib_logging

    logger = stdlib_logging.getLogger("hltv")
    logger.setLevel(getattr(stdlib_logging, config.level.upper(), stdlib_logging.INFO))
    logger.handlers.clear()

    handler = stdlib_logging.StreamHandler(sys.stdout)
    if config.format == "json":
        class JsonFormatter(stdlib_logging.Formatter):
            def format(self, record: stdlib_logging.LogRecord) -> str:
                import json
                entry: dict[str, Any] = {
                    "timestamp": self.formatTime(record, "%Y-%m-%dT%H:%M:%S"),
                    "level": record.levelname,
                    "name": record.name,
                    "message": record.getMessage(),
                }
                if record.exc_info and record.exc_info[0]:
                    entry["exception"] = self.formatException(record.exc_info)
                return json.dumps(entry, ensure_ascii=False)
        handler.setFormatter(JsonFormatter())
    else:
        handler.setFormatter(
            stdlib_logging.Formatter(
                "[%(asctime)s] %(levelname)-8s %(name)s | %(message)s",
                datefmt="%H:%M:%S",
            )
        )
    handler.setLevel(getattr(stdlib_logging, config.level.upper(), stdlib_logging.INFO))
    logger.addHandler(handler)

    if config.file:
        file_handler = stdlib_logging.FileHandler(config.file, encoding="utf-8")
        file_handler.setFormatter(
            stdlib_logging.Formatter(
                "%(asctime)s | %(levelname)-8s | %(name)s | %(message)s"
            )
        )
        logger.addHandler(file_handler)

    logger.propagate = False
    return logger


def get_logger(name: str | None = None) -> Any:
    """Get a child logger with a consistent API.

    Always returns a structlog-style logger when structlog is installed,
    or a stdlib logger with consistent interface when it's not.

    Args:
        name: Sub-namespace (e.g., 'endpoints.matches').

    Returns:
        Logger instance with .info(), .warning(), .error(), .debug(), .bind() methods.
    """
    logger_name = "hltv." + name if name else "hltv"
    try:
        import structlog
        return structlog.get_logger(logger_name)
    except ImportError:
        import logging
        return logging.getLogger(logger_name)
