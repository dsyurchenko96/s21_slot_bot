from zoneinfo import ZoneInfo

from pydantic import Field, PositiveInt
from pydantic_settings import BaseSettings

from s21_slot_bot.app.types import IntervalSec, NumBots


class BotConfig(BaseSettings):
    max_bots: NumBots = Field(alias="MAX_BOTS_DEFAULT", default=3)
    poll_interval_sec: IntervalSec = Field(alias="POLL_INTERVAL_SEC", default=60)
    jitter_sec: PositiveInt = Field(alias="POLL_JITTER_SEC", default=8)
    # TODO: move to service config
    timezone: ZoneInfo = Field(alias="BOT_TIMEZONE", default=ZoneInfo("Europe/Moscow"))
