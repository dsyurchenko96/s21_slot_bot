import asyncio
import enum
import logging
from enum import StrEnum

from pydantic import BaseModel, Field, ConfigDict, AwareDatetime, PositiveInt

from s21_slot_bot.app.consts import MIN_REQUIRED_REVIEWS, MAX_REQUIRED_REVIEWS, MIN_INTERVAL_SEC
from s21_slot_bot.common.logger import LoggerAdapterID


class Lifecycle(StrEnum):
    RUNNING = enum.auto()
    STOPPED = enum.auto()


class FlowCategory(StrEnum):
    START = enum.auto()
    STOP = enum.auto()
    EDIT = enum.auto()
    STATUS = enum.auto()
    SETTINGS = enum.auto()


class Mode(StrEnum):
    ONLY_FIND = enum.auto()
    FIND_AND_BOOK = enum.auto()


# TODO: separate into Action? rename?
class Screen(StrEnum):
    MENU = enum.auto()

    START_PICK_PROJECT = enum.auto()
    START_PICK_NUM = enum.auto()
    START_PICK_FROM = enum.auto()
    START_WAIT_FROM = enum.auto()
    START_PICK_TO = enum.auto()
    START_WAIT_TO = enum.auto()
    START_PICK_MODE = enum.auto()
    START_CONFIRM = enum.auto()

    STOP_MENU = enum.auto()
    STOP_MULTI = enum.auto()

    EDIT_PICK = enum.auto()
    EDIT_MENU = enum.auto()
    EDIT_WAIT_FROM = enum.auto()
    EDIT_WAIT_TO = enum.auto()
    EDIT_WAIT_INTERVAL = enum.auto()

    SETTINGS_MENU = enum.auto()
    SETTINGS_WAIT_INTERVAL = enum.auto()


class Stats(BaseModel):
    last_ping: AwareDatetime | None = None
    attempts_total: PositiveInt = 0
    attempts_success: PositiveInt = 0
    attempts_failed: PositiveInt = 0
    currently_booked: PositiveInt = 0


class BotConfig(BaseModel):
    bot_id: str
    # TODO: move chat_id to env
    chat_id: PositiveInt
    project_id: PositiveInt
    project_name: str
    required_reviews: int = Field(ge=MIN_REQUIRED_REVIEWS, le=MAX_REQUIRED_REVIEWS)
    from_dt: AwareDatetime
    to_dt: AwareDatetime
    interval_sec: int = Field(ge=MIN_INTERVAL_SEC)
    dry_run: bool


class BotInstance(BaseModel):
    cfg: BotConfig
    state: Lifecycle = Lifecycle.STOPPED
    stats: Stats = Field(default_factory=Stats)
    task: asyncio.Task | None = None

    model_config = ConfigDict(arbitrary_types_allowed=True)

    def logger(self) -> LoggerAdapterID:
        logger = logging.getLogger(__name__)
        adapter = LoggerAdapterID(logger, {"id": self.cfg.bot_id})
        return adapter
