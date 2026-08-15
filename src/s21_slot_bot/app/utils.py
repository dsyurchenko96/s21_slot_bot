from datetime import tzinfo

from telegram import Update

from s21_slot_bot.app.errors import AppNotInitializedError, InternalError
from s21_slot_bot.app.models import CustomContext


def get_tzinfo(context: CustomContext) -> tzinfo:
    if not context.bot.defaults:
        raise AppNotInitializedError("приложение не инициализировано: значения по умолчанию не заданы")
    return context.bot.defaults.tzinfo


def get_message_text(update: Update) -> str:
    if not update.message or not update.message.text:
        raise InternalError("не удалось обработать сообщение")
    return update.message.text
