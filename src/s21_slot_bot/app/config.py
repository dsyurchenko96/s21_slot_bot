from pydantic import Field
from pydantic_settings import BaseSettings


class AppConfig(BaseSettings):
    max_bots: int = Field(alias="MAX_BOTS_DEFAULT", default=2)
    poll_interval_sec: int = Field(alias="POLL_INTERVAL_SEC", default=60)
    jitter_sec: int = Field(alias="POLL_JITTER_SEC", default=8)
