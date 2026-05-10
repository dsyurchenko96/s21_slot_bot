from telegram import ReplyKeyboardMarkup

from s21_slot_bot.app.models import MenuButton

MAIN_MENU_KB = ReplyKeyboardMarkup(
    [
        [MenuButton.START, MenuButton.STOP],
        [MenuButton.EDIT, MenuButton.STATUS],
    ],
    resize_keyboard=True,
    is_persistent=True,
)
