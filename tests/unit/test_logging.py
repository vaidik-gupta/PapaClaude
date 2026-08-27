import logging

from app.logging_config import DEEP_DEBUG_LEVEL, get_logger, setup_logging


def test_deep_debug_level_registered():
    assert DEEP_DEBUG_LEVEL == 5
    assert logging.getLevelName(DEEP_DEBUG_LEVEL) == "DEEP_DEBUG"


def test_logger_has_deep_debug_method(caplog):
    logger = get_logger("test.deep")
    with caplog.at_level(DEEP_DEBUG_LEVEL, logger="test.deep"):
        logger.deep_debug("hello %s", "world")
    messages = [r.getMessage() for r in caplog.records]
    assert "hello world" in messages


def test_setup_logging_is_idempotent():
    setup_logging()
    n1 = len(logging.getLogger().handlers)
    setup_logging()
    n2 = len(logging.getLogger().handlers)
    assert n1 == n2
