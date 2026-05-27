import logging.config

from s21_slot_bot.common.logger import LogLevel


def setup_logging(log_level: LogLevel) -> None:
    level_name = log_level.name
    logging_config = {
        "version": 1,
        "disable_existing_loggers": False,
        "filters": {
            "sanitize": {
                "()": "s21_slot_bot.common.logger.LoggerSensitiveFilter",
                "substitution_patterns": {
                    r"(https://api\.telegram\.org/bot)([^/]+)/": r"\1[TOKEN]/",
                },
            },
        },
        "formatters": {
            "default": {
                "format": "[%(asctime)s %(levelname)s] %(message)s",
            },
        },
        "handlers": {
            "console": {
                "class": "logging.StreamHandler",
                "level": level_name,
                "formatter": "default",
                "filters": ["sanitize"],
                "stream": "ext://sys.stdout",
            },
        },
        "root": {
            "level": level_name,
            "handlers": ["console"],
        },
    }
    logging.config.dictConfig(logging_config)
