import logging
from enum import IntEnum
from logging import LoggerAdapter, Logger
from typing import Any, MutableMapping


class LogLevel(IntEnum):
    DEBUG = logging.DEBUG
    INFO = logging.INFO
    WARNING = logging.WARNING
    ERROR = logging.ERROR
    CRITICAL = logging.CRITICAL


class LoggerAdapterID(LoggerAdapter):
    def process(self, msg: Any, kwargs: MutableMapping[str, Any]) -> tuple[Any, MutableMapping[str, Any]]:
        return "[%s] %s" % (self.extra["id"], msg), kwargs


LoggerLike = LoggerAdapterID | Logger
