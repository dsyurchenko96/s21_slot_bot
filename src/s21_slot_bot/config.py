from pydantic import Field, SecretStr
from pydantic_settings import BaseSettings

from s21_slot_bot.app.config import BotConfig
from s21_slot_bot.client.config import S21ClientConfig
from s21_slot_bot.common.logger import LogLevel


class SlotBotServiceConfig(BaseSettings):
    s21: S21ClientConfig = Field(default_factory=S21ClientConfig)
    bot: BotConfig = Field(default_factory=BotConfig)
    tg_token: SecretStr = Field(alias="TG_BOT_TOKEN")
    log_level: LogLevel = Field(alias="LOG_LEVEL", default=LogLevel.INFO)
