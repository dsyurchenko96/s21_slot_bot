import logging

from s21_slot_bot.config import SlotBotServiceConfig
from s21_slot_bot.service import SlotBotService


def main() -> None:
    config = SlotBotServiceConfig()
    logging.basicConfig(level=config.log_level, format="[%(asctime)s %(levelname)s] %(message)s")
    service = SlotBotService(config=config)
    service.start()


if __name__ == "__main__":
    main()
