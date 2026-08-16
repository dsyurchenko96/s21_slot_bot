import telegram

from s21_slot_bot.common.error import Error


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


class BookingRefresherError(InternalError): ...


class AppNotInitializedError(InternalError): ...


def is_not_modified_tg_error(error: telegram.error.BadRequest) -> bool:
    return "not modified" in error.message.lower()
