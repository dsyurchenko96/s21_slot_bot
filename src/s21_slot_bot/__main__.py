import logging.config

from s21_slot_bot.config import SlotBotServiceConfig
from s21_slot_bot.logging_config import setup_logging
from s21_slot_bot.service import SlotBotService


def main() -> None:
    config = SlotBotServiceConfig()
    setup_logging(config.log)
    service = SlotBotService(config=config)
    service.start()


if __name__ == "__main__":
    main()
