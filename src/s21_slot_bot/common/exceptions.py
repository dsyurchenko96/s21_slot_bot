import json
from http import HTTPStatus
from typing import Any


class Error(Exception):
    default_help_text: str | None = None

    def __init__(
        self,
        message: str,
        status: HTTPStatus | None = None,
        location: str | dict[str, Any] | None = None,
        help_text: str | None = None,
    ):
        super().__init__(message)
        self.message = message
        self.status = status
        self.location = json.dumps(location, ensure_ascii=False, indent=2) if isinstance(location, dict) else location
        self.help_text = help_text or self.default_help_text

    def __str__(self) -> str:
        return f"message=`{self.message}`, status=`{self.effective_status}`, help=`{self.help_text}`\nlocation={self.location}"

    @property
    def effective_status(self) -> HTTPStatus | None:
        if self.status is not None:
            return self.status
        cause = self.__cause__
        if isinstance(cause, Error):
            return cause.effective_status
        context = self.__context__
        if isinstance(context, Error):
            return context.effective_status
        return None

    def to_pretty(self) -> str:
        text = f"❌ {self.message}"
        if self.help_text:
            text += f"\nℹ️ {self.help_text}"
        if status := self.effective_status:
            text += f"\nстатус: {status} ({status.phrase})"
        return text


class School21Error(Error): ...


class MenuError(Error): ...


class InvalidUserInputError(MenuError):
    default_help_text = "попробуй еще раз"


class InvalidCallbackDataError(MenuError): ...


class TooManyBotsError(MenuError):
    default_help_text = "останови/удали имеющихся или поменяй количество ботов"


class BotNotFoundError(MenuError): ...


class ForbiddenError(Error):
    default_help_text = "проверь, что ID чата совпадает с выставленным в приложении"


class InternalError(Error):
    default_help_text = "заведи баг"


class BotRuntimeError(InternalError): ...
