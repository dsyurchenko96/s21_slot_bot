import enum
import logging
import re
from enum import IntEnum, StrEnum
from logging import Logger, LoggerAdapter, LogRecord
from typing import Any, MutableMapping, override

from telegram import CallbackQuery, Update

from s21_slot_bot.common.random import random_id


class LogLevel(IntEnum):
    DEBUG = logging.DEBUG
    INFO = logging.INFO
    WARNING = logging.WARNING
    ERROR = logging.ERROR
    CRITICAL = logging.CRITICAL

    @classmethod
    def from_str(cls, value: str) -> "LogLevel":
        return getattr(cls, value.upper(), cls.INFO)


class LogEntity(StrEnum):
    BOT = enum.auto()
    USER_INPUT = enum.auto()
    SERVICE_HOOK = enum.auto()
    UNKNOWN = enum.auto()


class LoggerSensitiveFilter(logging.Filter):
    def __init__(self, substitution_patterns: dict[str, str]):
        super().__init__()
        self._compiled = [(re.compile(p), r) for p, r in substitution_patterns.items()]

    @override
    def filter(self, record: LogRecord) -> bool | LogRecord:
        message = record.getMessage()
        for pattern, substitution in self._compiled:
            message = re.sub(pattern, substitution, message)
        record.msg = message
        record.args = ()
        return record


class LoggerAdapterID(LoggerAdapter):
    def process(self, msg: Any, kwargs: MutableMapping[str, Any]) -> tuple[Any, MutableMapping[str, Any]]:
        return "[%s #%s] %s" % (self.extra["entity"], self.extra["id"], msg), kwargs


def get_user_input_logger(user_input: Update | CallbackQuery | object) -> LoggerAdapterID:
    if isinstance(user_input, CallbackQuery):
        input_id = user_input.id
    elif isinstance(user_input, Update):
        input_id = user_input.update_id
    else:  # update may be `object` in error handling
        return get_id_logger(LogEntity.UNKNOWN, random_id())
    return get_id_logger(LogEntity.USER_INPUT, input_id)


def get_service_hook_logger() -> LoggerAdapterID:
    return get_id_logger(LogEntity.SERVICE_HOOK, random_id())


def get_id_logger(entity_name: LogEntity, entity_id: str | int) -> LoggerAdapterID:
    logger = logging.getLogger()
    adapter = LoggerAdapterID(logger, {"entity": entity_name, "id": entity_id})
    return adapter


LoggerLike = LoggerAdapterID | Logger
