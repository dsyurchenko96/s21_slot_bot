import logging
import os

from telegram.ext import Application, CommandHandler, CallbackQueryHandler, MessageHandler, filters

from bot_app import cmd_start, on_cb, on_text


def main() -> None:
    token = os.getenv("TG_BOT_TOKEN", "").strip()
    if not token:
        raise RuntimeError("TG_BOT_TOKEN не задан")

    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")

    app = Application.builder().token(token).build()
    app.add_handler(CommandHandler("start", cmd_start))
    app.add_handler(CallbackQueryHandler(on_cb))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, on_text))
    app.run_polling(close_loop=False)


if __name__ == "__main__":
    main()
