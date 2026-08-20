from unittest.mock import patch

from s21_slot_bot.logging_config import LogConfig, setup_logging


class TestLoggingConfig:
    def test_setup_logging_applies_level_and_silenced_libraries(self, log_config: LogConfig) -> None:
        with patch("s21_slot_bot.logging_config.logging.config.dictConfig") as dict_config:
            setup_logging(log_config)

        applied = dict_config.call_args.args[0]
        assert applied["root"]["level"] == "DEBUG"
        assert applied["loggers"] == {
            "telegram": {"level": "WARNING", "propagate": True},
            "httpx": {"level": "WARNING", "propagate": True},
        }
