import asyncio
import enum
from datetime import datetime
from enum import StrEnum

from pydantic import BaseModel, Field, ConfigDict


class Lifecycle(StrEnum):
    QUEUED = enum.auto()
    RUNNING = enum.auto()
    STOPPED = enum.auto()
    DONE = enum.auto()


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
    last_ping: datetime | None = None
    attempts_total: int = 0
    attempts_success: int = 0
    attempts_failed: int = 0
    currently_booked: int = 0


class BotConfig(BaseModel):
    bot_id: str
    chat_id: int
    project_id: str
    project_name: str
    required_reviews: int
    from_iso_z: str
    to_iso_z: str
    interval_sec: int
    dry_run: bool


class BotInstance(BaseModel):
    cfg: BotConfig
    state: Lifecycle = Lifecycle.QUEUED
    stats: Stats = Field(default_factory=Stats)
    task: asyncio.Task | None = None

    model_config = ConfigDict(arbitrary_types_allowed=True)
