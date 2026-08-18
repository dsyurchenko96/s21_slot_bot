from collections.abc import Callable

from telegram import CallbackQuery, Update

from s21_slot_bot.app.bot_manager import BotManager
from s21_slot_bot.app.flows.actions import DeleteFlowAction
from s21_slot_bot.app.flows.delete import DeleteFlow
from s21_slot_bot.app.messenger import Messenger
from s21_slot_bot.app.models import BotInstance, CustomContext, Lifecycle


class TestDeleteFlow:
    async def test_delete_menu_renders_empty_state(
        self,
        delete_flow: DeleteFlow,
        bot_manager_mock: BotManager,
        messenger_mock: Messenger,
        update_mock: Update,
        context: CustomContext,
    ) -> None:
        bot_manager_mock.list_all.return_value = []

        await delete_flow.delete_menu(update_mock, context)

        assert "нет ботов" in messenger_mock.render_menu_message.await_args.args[1]

    async def test_delete_menu_lists_bots(
        self,
        delete_flow: DeleteFlow,
        bot_manager_mock: BotManager,
        messenger_mock: Messenger,
        update_mock: Update,
        context: CustomContext,
        bot_instance_factory: Callable[..., BotInstance],
    ) -> None:
        bot_manager_mock.list_all.return_value = [
            bot_instance_factory(bot_id="bot-1"),
            bot_instance_factory(bot_id="bot-2"),
        ]

        await delete_flow.delete_menu(update_mock, context)

        assert messenger_mock.render_menu_message.await_args.args[1] == "удалить ботов:"

    async def test_delete_one(
        self,
        delete_flow: DeleteFlow,
        bot_manager_mock: BotManager,
        messenger_mock: Messenger,
        query_mock: CallbackQuery,
        context: CustomContext,
    ) -> None:
        bot_manager_mock.delete_bot.return_value = True

        await delete_flow.parse_callback(
            ["bot-1", DeleteFlowAction.DELETE_ONE],
            query_mock,
            context,
        )

        bot_manager_mock.delete_bot.assert_called_once()
        assert "бот #bot-1 удален" in messenger_mock.render_menu_message.await_args.args[1]

    async def test_delete_all_stopped(
        self,
        delete_flow: DeleteFlow,
        bot_manager_mock: BotManager,
        query_mock: CallbackQuery,
        context: CustomContext,
    ) -> None:
        bot_manager_mock.delete_all.return_value = 2

        await delete_flow.parse_callback(
            [DeleteFlowAction.DELETE_ALL_STOPPED],
            query_mock,
            context,
        )

        assert bot_manager_mock.delete_all.call_args.kwargs["states"] == {
            Lifecycle.STOPPED,
            Lifecycle.FAILED,
        }
