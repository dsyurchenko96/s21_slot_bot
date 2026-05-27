from zoneinfo import ZoneInfo

from pydantic import Field, NonNegativeInt, PositiveInt, Secret
from pydantic_settings import BaseSettings

from s21_slot_bot.app.models import IntervalSec, NumBots


class BotConfig(BaseSettings):
    tg_chat_id: Secret[int] = Field(
        alias="TG_CHAT_ID",
        description="Chat ID used for user authentication and sending messages to",
    )
    max_bots: NumBots = Field(
        alias="MAX_BOTS",
        description="Maximum number of total bots at a time",
        default=3,
    )
    max_retries: NonNegativeInt = Field(
        alias="MAX_RETRIES",
        description="Maximum number of request retries in a running bot loop before an error message is sent to the chat. "
        "Set to 0 to disable",
        default=3,
    )
    poll_interval_sec: IntervalSec = Field(
        alias="POLL_INTERVAL_SEC",
        description="Interval (in seconds) between slot polling requests",
        default=60,
    )
    poll_jitter_sec: NonNegativeInt = Field(
        alias="POLL_JITTER_SEC",
        description="Upper limit (in seconds) of added random delay to polling interval. Set to 0 to disable",
        default=8,
    )
    timezone: ZoneInfo = Field(
        alias="BOT_TIMEZONE",
        description="Timezone used for input processing (unless specified in user prompt) and output",
        default=ZoneInfo("Europe/Moscow"),
    )
