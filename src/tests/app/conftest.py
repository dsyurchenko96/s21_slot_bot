from collections.abc import Callable
from datetime import datetime, timedelta
from unittest.mock import AsyncMock, MagicMock
from zoneinfo import ZoneInfo

import pytest
from telegram import CallbackQuery, Message, Update, User
from telegram.ext import Application, Defaults, ExtBot, Job, JobQueue

from s21_slot_bot.app.booking_manager import BookingManager
from s21_slot_bot.app.bot_manager import BotManager
from s21_slot_bot.app.flows.collector import FlowCollector
from s21_slot_bot.app.input_handler import InputHandler
from s21_slot_bot.app.messenger import Messenger
from s21_slot_bot.app.models import (
    BotData,
    BotInstance,
    ChatData,
    CustomContext,
    Lifecycle,
    Mode,
    SearchConfig,
)
from s21_slot_bot.client.models import Booking, ReviewInfo, SlotsInfo, TimeSlot
from s21_slot_bot.client.s21_client import School21Client
from s21_slot_bot.config import SlotBotServiceConfig


@pytest.fixture
def update_mock(config: SlotBotServiceConfig) -> Update:
    update = MagicMock(spec=Update)
    update.update_id = 100

    message = MagicMock(spec=Message)
    message.message_id = 10
    message.chat_id = config.bot.tg_chat_id.get_secret_value()
    message.text = ""
    update.message = message

    user = MagicMock(spec=User)
    user.id = config.bot.tg_chat_id.get_secret_value()
    update.effective_user = user
    update.callback_query = None
    return update


@pytest.fixture
def query_mock(config: SlotBotServiceConfig) -> CallbackQuery:
    query = MagicMock(spec=CallbackQuery)
    query.id = "query-100"
    query.data = ""
    query.answer = AsyncMock()

    message = MagicMock(spec=Message)
    message.message_id = 11
    message.chat_id = config.bot.tg_chat_id.get_secret_value()
    query.message = message
    return query


@pytest.fixture
def job_queue_mock() -> JobQueue:
    return MagicMock(spec=JobQueue)


@pytest.fixture
def job_mock() -> Job:
    job = MagicMock(spec=Job)
    job.run = AsyncMock()
    return job


@pytest.fixture
def context(
    tg_app_mock: Application,
    job_queue_mock: JobQueue,
    timezone: ZoneInfo,
) -> CustomContext:
    context = MagicMock(spec=CustomContext)
    context.application = tg_app_mock
    context.bot = MagicMock()
    context.bot.defaults = Defaults(tzinfo=timezone)
    context.bot_data = BotData()
    context.ensured_chat_data = ChatData()
    context.ensured_job_queue = job_queue_mock
    context.job = None
    return context


@pytest.fixture
def bot_instance_factory(
    now: datetime,
) -> Callable[..., BotInstance]:
    def factory(
        *,
        bot_id: str = "bot-1",
        project_id: str = "project-1",
        project_name: str = "Project 1",
        required_reviews: int = 2,
        from_dt: datetime | None = None,
        to_dt: datetime | None = None,
        interval_sec: int = 60,
        mode: Mode = Mode.FIND_AND_BOOK,
        state: Lifecycle = Lifecycle.STOPPED,
    ) -> BotInstance:
        return BotInstance(
            cfg=SearchConfig(
                bot_id=bot_id,
                project_id=project_id,
                project_name=project_name,
                required_reviews=required_reviews,
                from_dt=from_dt or now,
                to_dt=to_dt or now + timedelta(hours=2),
                interval_sec=interval_sec,
                mode=mode,
            ),
            state=state,
        )

    return factory


@pytest.fixture
def booking_factory(
    now: datetime,
) -> Callable[..., Booking]:
    def factory(
        *,
        booking_id: str = "booking-1",
        answer_id: str = "answer-1",
        project_id: str = "project-1",
        project_name: str = "Project 1",
        start: datetime | None = None,
        url: str | None = None,
    ) -> Booking:
        return Booking(
            id=booking_id,
            answer_id=answer_id,
            project_id=project_id,
            project_name=project_name,
            start=start or now + timedelta(minutes=10),
            url=url,
        )

    return factory


@pytest.fixture
def timeslot_factory(
    now: datetime,
) -> Callable[..., TimeSlot]:
    def factory(
        *,
        valid_start_times: list[datetime] | None = None,
        staff_slot: bool = False,
    ) -> TimeSlot:
        valid = valid_start_times if valid_start_times is not None else [now + timedelta(minutes=30)]
        return TimeSlot(
            start=min(valid) if valid else now,
            end=(max(valid) if valid else now) + timedelta(hours=1),
            valid_start_times=valid,
            staff_slot=staff_slot,
        )

    return factory


@pytest.fixture
def slots_info_factory(
    timeslot_factory,
) -> Callable[..., SlotsInfo]:
    def factory(
        *,
        booked: int = 0,
        required: int = 2,
        time_slots: list[TimeSlot] | None = None,
    ) -> SlotsInfo:
        return SlotsInfo(
            check_duration=45,
            review_info=ReviewInfo(required=required, booked=booked),
            time_slots=time_slots if time_slots is not None else [timeslot_factory()],
        )

    return factory


@pytest.fixture
def booking_manager(
    config: SlotBotServiceConfig,
    s21_client_mock: School21Client,
    messenger_mock: Messenger,
    tg_app_mock: Application,
    job_queue_mock: JobQueue,
) -> BookingManager:
    tg_app_mock.job_queue = job_queue_mock
    return BookingManager(
        s21_client=s21_client_mock,
        messenger=messenger_mock,
        app=tg_app_mock,
        refresh_interval=config.bot.refresh_bookings_interval_sec,
        chat_id=config.bot.tg_chat_id.get_secret_value(),
    )


@pytest.fixture
def bot_manager(
    config: SlotBotServiceConfig,
    messenger_mock: Messenger,
    s21_client_mock: School21Client,
    booking_manager_mock: BookingManager,
) -> BotManager:
    return BotManager(
        bot_config=config.bot,
        chat_id=config.bot.tg_chat_id.get_secret_value(),
        messenger=messenger_mock,
        s21_client=s21_client_mock,
        booking_manager=booking_manager_mock,
    )


@pytest.fixture
def messenger(config: SlotBotServiceConfig, bot_mock: ExtBot) -> Messenger:
    return Messenger(
        chat_id=config.bot.tg_chat_id.get_secret_value(),
        bot=bot_mock,
    )


@pytest.fixture
def input_handler(
    config: SlotBotServiceConfig,
    bot_manager_mock: BotManager,
    messenger_mock: Messenger,
    flow_collector_mock: FlowCollector,
) -> InputHandler:
    return InputHandler(
        bot_manager=bot_manager_mock,
        messenger=messenger_mock,
        flows=flow_collector_mock,
        chat_id=config.bot.tg_chat_id.get_secret_value(),
    )
