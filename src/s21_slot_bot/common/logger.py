import enum
import logging
from enum import IntEnum, StrEnum
from logging import Logger, LoggerAdapter
from typing import Any, MutableMapping

from telegram import CallbackQuery, Update


class LogLevel(IntEnum):
    DEBUG = logging.DEBUG
    INFO = logging.INFO
    WARNING = logging.WARNING
    ERROR = logging.ERROR
    CRITICAL = logging.CRITICAL


class LogEntity(StrEnum):
    BOT = enum.auto()
    USER_INPUT = enum.auto()


class LoggerAdapterID(LoggerAdapter):
    def process(self, msg: Any, kwargs: MutableMapping[str, Any]) -> tuple[Any, MutableMapping[str, Any]]:
        return "[%s #%s] %s" % (self.extra["entity"], self.extra["id"], msg), kwargs


def get_user_input_logger(user_input: Update | CallbackQuery) -> LoggerAdapterID:
    input_id = user_input.id if isinstance(user_input, CallbackQuery) else user_input.update_id
    return get_id_logger(LogEntity.USER_INPUT, input_id)


def get_id_logger(entity_name: LogEntity, entity_id: str | int) -> LoggerAdapterID:
    logger = logging.getLogger()
    adapter = LoggerAdapterID(logger, {"entity": entity_name, "id": entity_id})
    return adapter


LoggerLike = LoggerAdapterID | Logger
