from collections.abc import Callable
from unittest.mock import AsyncMock

import pytest
from telegram import CallbackQuery, Update

from s21_slot_bot.app.bot_manager import BotManager
from s21_slot_bot.app.errors import InvalidUserInputError
from s21_slot_bot.app.flows.actions import EditFlowAction, InputFlowAction
from s21_slot_bot.app.flows.edit import EditFlow
from s21_slot_bot.app.messenger import Messenger
from s21_slot_bot.app.models import BotInstance, CustomContext, Lifecycle, Mode


class TestEditFlow:
    async def test_list_bots_renders_empty_state(
        self,
        edit_flow: EditFlow,
        bot_manager_mock: BotManager,
        messenger_mock: Messenger,
        update_mock: Update,
        context: CustomContext,
    ) -> None:
        bot_manager_mock.list_all.return_value = []

        await edit_flow.list_bots(update_mock, context)

        assert "нет ботов" in messenger_mock.render_menu_message.await_args.args[1]

    async def test_list_bots_renders_bot_selection(
        self,
        edit_flow: EditFlow,
        bot_manager_mock: BotManager,
        messenger_mock: Messenger,
        update_mock: Update,
        context: CustomContext,
        bot_instance_factory: Callable[..., BotInstance],
    ) -> None:
        bot_manager_mock.list_all.return_value = [bot_instance_factory(bot_id="bot-1")]

        await edit_flow.list_bots(update_mock, context)

        assert messenger_mock.render_menu_message.await_args.args[1] == "выбери бота:"

    async def test_switch_to_only_find_resets_required_reviews(
        self,
        edit_flow: EditFlow,
        bot_manager_mock: BotManager,
        query_mock: CallbackQuery,
        context: CustomContext,
        bot_instance_factory: Callable[..., BotInstance],
    ) -> None:
        inst = bot_instance_factory(
            required_reviews=3,
            mode=Mode.FIND_AND_BOOK,
        )
        context.ensured_chat_data.edit_bot_id = inst.cfg.bot_id
        bot_manager_mock.get_bot.return_value = inst
        edit_flow.edit_menu = AsyncMock()

        await edit_flow.parse_callback(
            [Mode.ONLY_FIND, InputFlowAction.PICK_MODE],
            query_mock,
            context,
        )

        assert inst.cfg.mode == Mode.ONLY_FIND
        assert inst.cfg.required_reviews == 1
        edit_flow.edit_menu.assert_awaited_once()

    async def test_change_interval_restarts_bot(
        self,
        edit_flow: EditFlow,
        bot_manager_mock: BotManager,
        query_mock: CallbackQuery,
        context: CustomContext,
        bot_instance_factory: Callable[..., BotInstance],
    ) -> None:
        inst = bot_instance_factory(interval_sec=60, state=Lifecycle.RUNNING)
        context.ensured_chat_data.edit_bot_id = inst.cfg.bot_id
        bot_manager_mock.get_bot.return_value = inst
        edit_flow.edit_menu = AsyncMock()

        await edit_flow.parse_callback(
            ["30", EditFlowAction.SET_INTERVAL],
            query_mock,
            context,
        )

        assert inst.cfg.interval_sec == 30
        bot_manager_mock.stop_bot.assert_called_once()
        bot_manager_mock.start_bot.assert_awaited_once()
        assert "интервал обновлен" in edit_flow.edit_menu.await_args.kwargs["update_text"]

    async def test_restart_rejects_running_bot(
        self,
        edit_flow: EditFlow,
        bot_manager_mock: BotManager,
        query_mock: CallbackQuery,
        context: CustomContext,
        bot_instance_factory: Callable[..., BotInstance],
    ) -> None:
        inst = bot_instance_factory(state=Lifecycle.RUNNING)
        context.ensured_chat_data.edit_bot_id = inst.cfg.bot_id
        bot_manager_mock.get_bot.return_value = inst

        with pytest.raises(InvalidUserInputError, match="уже активен"):
            await edit_flow.edit_restart(query_mock, context)

    async def test_restart_stopped_bot(
        self,
        edit_flow: EditFlow,
        bot_manager_mock: BotManager,
        query_mock: CallbackQuery,
        context: CustomContext,
        bot_instance_factory: Callable[..., BotInstance],
    ) -> None:
        inst = bot_instance_factory(state=Lifecycle.STOPPED)
        context.ensured_chat_data.edit_bot_id = inst.cfg.bot_id
        bot_manager_mock.get_bot.return_value = inst
        edit_flow.edit_menu = AsyncMock()

        await edit_flow.edit_restart(query_mock, context)

        bot_manager_mock.start_bot.assert_awaited_once()
        assert "перезапущен" in edit_flow.edit_menu.await_args.kwargs["update_text"]
