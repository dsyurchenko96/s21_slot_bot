import logging

import pytest

from s21_slot_bot.common.logger import (
    LogEntity,
    LoggerAdapterID,
    LoggerSensitiveFilter,
    LogLevel,
    get_user_input_logger,
)


class TestLogger:
    @pytest.mark.parametrize(
        ("value", "expected"),
        [
            ("debug", LogLevel.DEBUG),
            ("INFO", LogLevel.INFO),
            ("Warning", LogLevel.WARNING),
            ("error", LogLevel.ERROR),
            ("critical", LogLevel.CRITICAL),
            ("unknown", LogLevel.INFO),
        ],
    )
    def test_log_level_from_str(self, value: str, expected: LogLevel) -> None:
        assert LogLevel.from_str(value) == expected

    def test_sensitive_filter_replaces_matching_content(self) -> None:
        sensitive_filter = LoggerSensitiveFilter({r"(https://api\.telegram\.org/bot)([^/]+)/": r"\1[TOKEN]/"})
        record = logging.LogRecord(
            name="test",
            level=logging.INFO,
            pathname=__file__,
            lineno=1,
            msg="POST %s",
            args=("https://api.telegram.org/botsecret123/sendMessage",),
            exc_info=None,
        )

        result = sensitive_filter.filter(record)

        assert result is record
        assert record.getMessage() == "POST https://api.telegram.org/bot[TOKEN]/sendMessage"
        assert record.args == ()

    def test_logger_adapter_adds_entity_and_id(self) -> None:
        adapter = LoggerAdapterID(
            logging.getLogger("test"),
            {"entity": LogEntity.BOT, "id": "abc123"},
        )

        message, kwargs = adapter.process("started", {})

        assert message == "[bot #abc123] started"
        assert kwargs == {}

    def test_get_user_input_logger_falls_back_to_unknown_for_arbitrary_object(self) -> None:
        logger = get_user_input_logger(object())

        assert logger.extra["entity"] == LogEntity.UNKNOWN
        assert isinstance(logger.extra["id"], str)
        assert logger.extra["id"]
