import logging

from s21_slot_bot.config import SlotBotServiceConfig
from s21_slot_bot.service import SlotBotService


def main() -> None:
    logging.basicConfig(level=logging.INFO, format="[%(asctime)s %(levelname)s] %(message)s")
    config = SlotBotServiceConfig()
    service = SlotBotService(config=config)
    service.start()

if __name__ == "__main__":
    main()
