"""Logging setup with three application levels: INFO, DEBUG, and DEEP_DEBUG.

DEEP_DEBUG is a custom level below DEBUG for the most verbose tracing:

    DEEP_DEBUG (5) < DEBUG (10) < INFO (20)

Usage:
    from app.logging_config import get_logger
    logger = get_logger(__name__)
    logger.info("...")
    logger.debug("...")
    logger.deep_debug("...")
"""

import logging
import sys

from app.config import settings

DEEP_DEBUG_LEVEL = 5
logging.addLevelName(DEEP_DEBUG_LEVEL, "DEEP_DEBUG")


def _deep_debug(self: logging.Logger, message: str, *args, **kwargs) -> None:
    if self.isEnabledFor(DEEP_DEBUG_LEVEL):
        self._log(DEEP_DEBUG_LEVEL, message, args, **kwargs)


# Attach deep_debug() to every logger instance.
logging.Logger.deep_debug = _deep_debug  # type: ignore[attr-defined]

_LEVELS = {
    "DEEP_DEBUG": DEEP_DEBUG_LEVEL,
    "DEBUG": logging.DEBUG,
    "INFO": logging.INFO,
    "WARNING": logging.WARNING,
    "ERROR": logging.ERROR,
}

_configured = False


def setup_logging(level: str | None = None) -> None:
    """Configure the root logger. Idempotent — safe to call more than once."""
    global _configured
    if _configured:
        return

    resolved = (level or settings.log_level).upper()
    numeric_level = _LEVELS.get(resolved, logging.INFO)

    handler = logging.StreamHandler(sys.stdout)
    handler.setFormatter(
        logging.Formatter(
            "%(asctime)s | %(levelname)-9s | %(name)s | %(message)s",
            datefmt="%Y-%m-%d %H:%M:%S",
        )
    )

    root = logging.getLogger()
    root.setLevel(numeric_level)
    root.handlers.clear()
    root.addHandler(handler)

    _configured = True


def get_logger(name: str) -> logging.Logger:
    return logging.getLogger(name)
