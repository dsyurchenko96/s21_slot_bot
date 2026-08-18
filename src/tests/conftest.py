from datetime import datetime
from logging import Logger
from unittest.mock import AsyncMock, MagicMock, create_autospec
from zoneinfo import ZoneInfo

import pytest
from _pytest.monkeypatch import MonkeyPatch
from telegram.ext import Application, ApplicationBuilder, ExtBot

from s21_slot_bot.app.booking_manager import BookingManager
from s21_slot_bot.app.bot_manager import BotManager
from s21_slot_bot.app.flows.collector import FlowCollector
from s21_slot_bot.app.input_handler import InputHandler
from s21_slot_bot.app.messenger import Messenger
from s21_slot_bot.client.middleware.auth import School21AuthMiddleware
from s21_slot_bot.client.middleware.retry import School21RetryMiddleware
from s21_slot_bot.client.s21_client import School21Client
from s21_slot_bot.config import SlotBotServiceConfig
from s21_slot_bot.service import SlotBotService

# ----------- COMMON --------------


@pytest.fixture
def logger_mock() -> Logger:
    return create_autospec(Logger, instance=True, spec_set=True)


@pytest.fixture
def timezone() -> ZoneInfo:
    return ZoneInfo("Europe/Moscow")


@pytest.fixture
def now(timezone: ZoneInfo) -> datetime:
    return datetime(2026, 8, 16, 18, 30, 15, tzinfo=timezone)


@pytest.fixture
def bot_mock() -> ExtBot:
    return create_autospec(
        ExtBot,
        instance=True,
        spec_set=True,
    )


# ----------- SERVICE COMPONENT MOCKS --------------


@pytest.fixture
def s21_auth_middleware_mock() -> School21AuthMiddleware:
    return create_autospec(
        School21AuthMiddleware,
        instance=True,
        spec_set=True,
    )


@pytest.fixture
def s21_retry_middleware_mock() -> School21RetryMiddleware:
    return create_autospec(
        School21RetryMiddleware,
        instance=True,
        spec_set=True,
    )


@pytest.fixture
def s21_client_mock() -> School21Client:
    return create_autospec(
        School21Client,
        instance=True,
        spec_set=True,
    )


@pytest.fixture
def messenger_mock() -> Messenger:
    return create_autospec(
        Messenger,
        instance=True,
        spec_set=True,
    )


@pytest.fixture
def booking_manager_mock() -> BookingManager:
    return create_autospec(
        BookingManager,
        instance=True,
        spec_set=True,
    )


@pytest.fixture
def bot_manager_mock() -> BotManager:
    return create_autospec(
        BotManager,
        instance=True,
        spec_set=True,
    )


@pytest.fixture
def flow_collector_mock() -> FlowCollector:
    flows = MagicMock(spec=FlowCollector)
    flows.start = MagicMock()
    flows.start.list_projects = AsyncMock()
    flows.start.custom_from = AsyncMock()
    flows.start.custom_to = AsyncMock()

    flows.stop = MagicMock()
    flows.stop.stop_menu = AsyncMock()

    flows.delete = MagicMock()
    flows.delete.delete_menu = AsyncMock()

    flows.edit = MagicMock()
    flows.edit.list_bots = AsyncMock()
    flows.edit.edit_custom_from = AsyncMock()
    flows.edit.edit_custom_to = AsyncMock()
    flows.edit.edit_custom_interval = AsyncMock()

    flows.status = MagicMock()
    flows.status.status_refresh = AsyncMock()

    flows.book = MagicMock()
    flows.get_flow = MagicMock()
    return flows


@pytest.fixture
def input_handler_mock() -> InputHandler:
    return create_autospec(
        InputHandler,
        instance=True,
        spec_set=True,
    )


@pytest.fixture
def tg_app_mock(bot_mock: ExtBot) -> Application:
    app = create_autospec(
        Application,
        instance=True,
        spec_set=True,
    )
    app.bot = bot_mock
    app.chat_data = {}
    return app


# ----------- SERVICE COMPONENT FACTORIES --------------


@pytest.fixture
def s21_client_factory(s21_client_mock: School21Client) -> MagicMock:
    return MagicMock(return_value=s21_client_mock)


@pytest.fixture
def messenger_factory(messenger_mock: Messenger) -> MagicMock:
    return MagicMock(return_value=messenger_mock)


@pytest.fixture
def bot_manager_factory(bot_manager_mock: BotManager) -> MagicMock:
    return MagicMock(return_value=bot_manager_mock)


@pytest.fixture
def booking_manager_factory(booking_manager_mock: BookingManager) -> MagicMock:
    return MagicMock(return_value=booking_manager_mock)


@pytest.fixture
def s21_auth_middleware_factory(s21_auth_middleware_mock: School21AuthMiddleware) -> MagicMock:
    return MagicMock(return_value=s21_auth_middleware_mock)


@pytest.fixture
def s21_retry_middleware_factory(s21_retry_middleware_mock: School21RetryMiddleware) -> MagicMock:
    return MagicMock(return_value=s21_retry_middleware_mock)


@pytest.fixture
def flow_collector_factory(flow_collector_mock: FlowCollector) -> MagicMock:
    return MagicMock(return_value=flow_collector_mock)


@pytest.fixture
def input_handler_factory(input_handler_mock: InputHandler) -> MagicMock:
    return MagicMock(return_value=input_handler_mock)


@pytest.fixture
def tg_app_builder(
    tg_app_mock: Application,
) -> MagicMock:
    builder = create_autospec(
        ApplicationBuilder,
        instance=True,
        spec_set=True,
    )

    builder.token.return_value = builder
    builder.context_types.return_value = builder
    builder.job_queue.return_value = builder
    builder.defaults.return_value = builder
    builder.build.return_value = tg_app_mock

    factory = MagicMock(return_value=builder)

    return factory


# ----------- CONFIG & SERVICE -----------


@pytest.fixture
def config(monkeypatch: MonkeyPatch) -> SlotBotServiceConfig:
    env_dict = {
        "S21_USERNAME": "user1",
        "S21_PASSWORD": "123",
        "TG_BOT_TOKEN": "tok123",
        "TG_CHAT_ID": 12345,
    }
    for k, v in env_dict.items():
        monkeypatch.setenv(k, v)
    config = SlotBotServiceConfig()
    return config


@pytest.fixture
def service(
    config: SlotBotServiceConfig,
    s21_auth_middleware_factory: MagicMock,
    s21_retry_middleware_factory: MagicMock,
    s21_client_factory: MagicMock,
    tg_app_builder: MagicMock,
    messenger_factory: MagicMock,
    bot_manager_factory: MagicMock,
    booking_manager_factory: MagicMock,
    flow_collector_factory: MagicMock,
    input_handler_factory: MagicMock,
) -> SlotBotService:
    return SlotBotService(
        config=config,
        s21_auth_middleware_factory=s21_auth_middleware_factory,
        s21_retry_middleware_factory=s21_retry_middleware_factory,
        s21_client_factory=s21_client_factory,
        tg_app_builder=tg_app_builder,
        messenger_factory=messenger_factory,
        bot_manager_factory=bot_manager_factory,
        booking_manager_factory=booking_manager_factory,
        flow_collector_factory=flow_collector_factory,
        input_handler_factory=input_handler_factory,
    )
