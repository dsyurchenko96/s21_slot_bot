from collections.abc import Callable
from unittest.mock import AsyncMock, MagicMock

import pytest
from telegram import CallbackQuery, Update

from s21_slot_bot.app.bot_manager import BotManager
from s21_slot_bot.app.errors import InvalidCallbackDataError
from s21_slot_bot.app.flows.actions import DeleteFlowAction
from s21_slot_bot.app.flows.delete import DeleteFlow
from s21_slot_bot.app.messenger import Messenger
from s21_slot_bot.app.models import BotInstance, CustomContext, Lifecycle


class TestDeleteFlow:
    async def test_delete_menu_empty(
        self,
        delete_flow: DeleteFlow,
        bot_manager: BotManager,
        messenger: Messenger,
        update_mock: Update,
        context: CustomContext,
    ) -> None:
        bot_manager.list_all = MagicMock(return_value=[])
        messenger.render_menu_message = AsyncMock()
        await delete_flow.delete_menu(update_mock, context)
        assert "нет ботов" in messenger.render_menu_message.await_args.args[1]

    async def test_delete_menu_lists_bots(
        self,
        delete_flow: DeleteFlow,
        bot_manager: BotManager,
        messenger: Messenger,
        bot_instance_factory: Callable[..., BotInstance],
        update_mock: Update,
        context: CustomContext,
    ) -> None:
        bot_manager.list_all = MagicMock(return_value=[bot_instance_factory()])
        messenger.render_menu_message = AsyncMock()
        await delete_flow.delete_menu(update_mock, context)
        assert messenger.render_menu_message.await_args.args[1] == "удалить ботов:"

    @pytest.mark.parametrize(("result", "expected"), [(True, "удален"), (False, "не удалось")])
    async def test_delete_one(
        self,
        delete_flow: DeleteFlow,
        bot_manager: BotManager,
        messenger: Messenger,
        query_mock: CallbackQuery,
        context: CustomContext,
        result: bool,
        expected: str,
    ) -> None:
        bot_manager.delete_bot = MagicMock(return_value=result)
        messenger.render_menu_message = AsyncMock()
        await delete_flow.parse_callback(["bot-1", DeleteFlowAction.DELETE_ONE], query_mock, context)
        assert expected in messenger.render_menu_message.await_args.args[1]

    @pytest.mark.parametrize(
        ("action", "states"),
        [
            (DeleteFlowAction.DELETE_ALL, None),
            (DeleteFlowAction.DELETE_ALL_STOPPED, {Lifecycle.STOPPED, Lifecycle.FAILED}),
        ],
    )
    async def test_delete_all(
        self,
        delete_flow: DeleteFlow,
        bot_manager: BotManager,
        messenger: Messenger,
        query_mock: CallbackQuery,
        context: CustomContext,
        action: DeleteFlowAction,
        states: set[Lifecycle] | None,
    ) -> None:
        bot_manager.delete_all = MagicMock(return_value=2)
        messenger.render_menu_message = AsyncMock()
        await delete_flow.parse_callback([action], query_mock, context)
        assert bot_manager.delete_all.call_args.kwargs["states"] == states
        assert "удалено ботов: 2" in messenger.render_menu_message.await_args.args[1]

    async def test_delete_all_empty(
        self,
        delete_flow: DeleteFlow,
        bot_manager: BotManager,
        messenger: Messenger,
        query_mock: CallbackQuery,
        context: CustomContext,
    ) -> None:
        bot_manager.delete_all = MagicMock(return_value=0)
        messenger.render_menu_message = AsyncMock()
        await delete_flow.parse_callback([DeleteFlowAction.DELETE_ALL], query_mock, context)
        assert "не найдено" in messenger.render_menu_message.await_args.args[1]

    async def test_unknown_action(
        self,
        delete_flow: DeleteFlow,
        query_mock: CallbackQuery,
        context: CustomContext,
    ) -> None:
        with pytest.raises(InvalidCallbackDataError):
            await delete_flow.parse_callback(["bad"], query_mock, context)
