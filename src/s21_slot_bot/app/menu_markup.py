from telegram import ReplyKeyboardMarkup

MAIN_MENU_KB = ReplyKeyboardMarkup(
    [
        ["▶️ Начать", "⛔ Остановить"],
        ["✏️ Изменить", "📌 Статус"],
        ["⚙️ Настройки"],
    ],
    resize_keyboard=True,
    is_persistent=True,
)
