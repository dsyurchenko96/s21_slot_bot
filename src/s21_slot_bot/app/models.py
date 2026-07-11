import enum
from enum import StrEnum
from typing import Annotated

from pydantic import AwareDatetime, BaseModel, ConfigDict, Field, InstanceOf, PositiveInt, TypeAdapter
from telegram.ext import Application, CallbackContext, ExtBot, JobQueue

from s21_slot_bot.app.consts import (
    MAX_INTERVAL_SEC,
    MAX_NUM_BOTS,
    MAX_REQUIRED_REVIEWS,
    MIN_INTERVAL_SEC,
    MIN_NUM_BOTS,
    MIN_REQUIRED_REVIEWS,
)
from s21_slot_bot.client.s21_client import School21Client
from s21_slot_bot.common.logger import LogEntity, LoggerAdapterID, get_id_logger

type RequiredReviews = Annotated[PositiveInt, Field(ge=MIN_REQUIRED_REVIEWS, le=MAX_REQUIRED_REVIEWS)]
type IntervalSec = Annotated[PositiveInt, Field(ge=MIN_INTERVAL_SEC, le=MAX_INTERVAL_SEC)]
type NumBots = Annotated[PositiveInt, Field(ge=MIN_NUM_BOTS, le=MAX_NUM_BOTS)]

type App = Application[ExtBot, CustomContext, dict, ChatData, BotData, JobQueue[CustomContext]]

RequiredReviewsAdapter = TypeAdapter(RequiredReviews)
IntervalSecAdapter = TypeAdapter(IntervalSec)


class MenuButton(StrEnum):
    START = "▶️ Начать"
    STOP = "⛔ Остановить"
    DELETE = "🗑️ Удалить"
    EDIT = "✏️ Изменить"
    STATUS = "📌 Статус"


class Lifecycle(StrEnum):
    RUNNING = enum.auto()
    STOPPED = enum.auto()

    def to_text(self) -> str:
        match self:
            case Lifecycle.RUNNING:
                return "активен"
            case Lifecycle.STOPPED:
                return "остановлен"


class FlowCategory(StrEnum):
    START = enum.auto()
    STOP = enum.auto()
    DELETE = enum.auto()
    EDIT = enum.auto()
    STATUS = enum.auto()


class Mode(StrEnum):
    ONLY_FIND = enum.auto()
    FIND_AND_BOOK = enum.auto()

    def to_text(self) -> str:
        match self:
            case Mode.ONLY_FIND:
                return "найти слот без записи"
            case Mode.FIND_AND_BOOK:
                return "найти слоты и записаться"


class Screen(StrEnum):
    MENU = enum.auto()

    START_PICK_FROM = enum.auto()
    START_PICK_TO = enum.auto()

    EDIT_WAIT_FROM = enum.auto()
    EDIT_WAIT_TO = enum.auto()
    EDIT_WAIT_INTERVAL = enum.auto()


class Stats(BaseModel):
    last_ping: AwareDatetime | None = None
    attempts_total: PositiveInt = 0
    attempts_success: PositiveInt = 0
    attempts_failed: PositiveInt = 0
    currently_booked: PositiveInt = 0


class BotConfig(BaseModel):
    bot_id: str
    project_id: PositiveInt
    project_name: str
    required_reviews: RequiredReviews
    from_dt: AwareDatetime
    to_dt: AwareDatetime
    interval_sec: IntervalSec
    mode: Mode


class BotInstance(BaseModel):
    cfg: BotConfig
    state: Lifecycle = Lifecycle.STOPPED
    stats: Stats = Field(default_factory=Stats)

    def logger(self) -> LoggerAdapterID:
        return get_id_logger(LogEntity.BOT, self.cfg.bot_id)


class JobData(BaseModel):
    s21_client: School21Client
    inst: BotInstance
    task_id: str
    answer_id: str

    model_config = ConfigDict(arbitrary_types_allowed=True)


class ChatData(BaseModel):
    screen: Screen = Screen.MENU
    menu_msg_id: int | None = None
    menu_error_msg_id: int | None = None

    projects_map: dict[int, str] = Field(default_factory=dict)
    start_project_id: int | None = None
    start_required_reviews: RequiredReviews | None = None
    start_from: AwareDatetime | None = None
    start_to: AwareDatetime | None = None
    start_mode: Mode | None = None

    edit_bot_id: str | None = None


# NOTE: bot_data is not None on unhandled errors, unlike chat_data
class BotData(BaseModel):
    chat_should_move_menu: dict[int, bool] = Field(default_factory=dict)


class CustomContext(CallbackContext[ExtBot, dict, ChatData, BotData]):
    """Wrapper around CallbackContext to pass a custom chat data model as a type parameter."""

    def __init__(
        self,
        application: App,
        chat_id: int | None = None,
        user_id: int | None = None,
    ):
        super().__init__(application=application, chat_id=chat_id, user_id=user_id)
