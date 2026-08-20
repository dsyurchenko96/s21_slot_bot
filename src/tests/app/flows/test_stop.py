from collections.abc import Callable
from unittest.mock import AsyncMock, MagicMock

import pytest
from telegram import CallbackQuery, Update

from s21_slot_bot.app.bot_manager import BotManager
from s21_slot_bot.app.errors import InvalidCallbackDataError
from s21_slot_bot.app.flows.actions import StopFlowAction
from s21_slot_bot.app.flows.stop import StopFlow
from s21_slot_bot.app.messenger import Messenger
from s21_slot_bot.app.models import BotInstance, CustomContext, Lifecycle


class TestStopFlow:
    async def test_stop_menu_empty(
        self,
        stop_flow: StopFlow,
        bot_manager: BotManager,
        messenger: Messenger,
        update_mock: Update,
        context: CustomContext,
    ) -> None:
        bot_manager.list_all = MagicMock(return_value=[])
        messenger.render_menu_message = AsyncMock()
        await stop_flow.stop_menu(update_mock, context)
        assert "нет активных ботов" in messenger.render_menu_message.await_args.args[1]

    async def test_stop_menu_lists_running_bots(
        self,
        stop_flow: StopFlow,
        bot_manager: BotManager,
        messenger: Messenger,
        bot_instance_factory: Callable[..., BotInstance],
        update_mock: Update,
        context: CustomContext,
    ) -> None:
        inst = bot_instance_factory(state=Lifecycle.RUNNING)
        bot_manager.list_all = MagicMock(return_value=[inst])
        messenger.render_menu_message = AsyncMock()
        await stop_flow.stop_menu(update_mock, context)
        assert messenger.render_menu_message.await_args.args[1] == "остановить ботов:"

    @pytest.mark.parametrize(("result", "expected"), [(True, "остановлен"), (False, "не найден")])
    async def test_stop_one(
        self,
        stop_flow: StopFlow,
        bot_manager: BotManager,
        messenger: Messenger,
        query_mock: CallbackQuery,
        context: CustomContext,
        result: bool,
        expected: str,
    ) -> None:
        bot_manager.stop_bot = MagicMock(return_value=result)
        messenger.render_menu_message = AsyncMock()
        await stop_flow.parse_callback(["bot-1", StopFlowAction.STOP_ONE], query_mock, context)
        assert expected in messenger.render_menu_message.await_args.args[1]

    async def test_stop_all(
        self,
        stop_flow: StopFlow,
        bot_manager: BotManager,
        messenger: Messenger,
        query_mock: CallbackQuery,
        context: CustomContext,
    ) -> None:
        bot_manager.stop_all = MagicMock()
        messenger.render_menu_message = AsyncMock()
        await stop_flow.parse_callback([StopFlowAction.STOP_ALL], query_mock, context)
        bot_manager.stop_all.assert_called_once()
        assert "все боты остановлены" in messenger.render_menu_message.await_args.args[1]

    async def test_unknown_action(
        self,
        stop_flow: StopFlow,
        query_mock: CallbackQuery,
        context: CustomContext,
    ) -> None:
        with pytest.raises(InvalidCallbackDataError):
            await stop_flow.parse_callback(["bad"], query_mock, context)
