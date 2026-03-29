from zoneinfo import ZoneInfo

from pydantic import Field, PositiveInt
from pydantic_settings import BaseSettings

from s21_slot_bot.app.consts import MIN_INTERVAL_SEC


class BotConfig(BaseSettings):
    max_bots: PositiveInt = Field(alias="MAX_BOTS_DEFAULT", default=2)
    poll_interval_sec: PositiveInt = Field(alias="POLL_INTERVAL_SEC", ge=MIN_INTERVAL_SEC, default=60)
    jitter_sec: PositiveInt = Field(alias="POLL_JITTER_SEC", default=8)
    # TODO: move to service config
    timezone: ZoneInfo = Field(alias="BOT_TIMEZONE", default=ZoneInfo("Europe/Moscow"))
