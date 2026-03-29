import logging

from s21_slot_bot.config import SlotBotServiceConfig
from s21_slot_bot.service import SlotBotService


def main() -> None:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    config = SlotBotServiceConfig()
    service = SlotBotService(config=config)
    service.start()

    # app = Application.builder().token(config.tg_token).build()
    # app.add_handler(CommandHandler("start", cmd_start))
    # app.add_handler(CallbackQueryHandler(on_cb))
    # app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, on_text))
    # app.run_polling(close_loop=False)


if __name__ == "__main__":
    main()
