from collections.abc import Callable

from telegram import CallbackQuery, Update

from s21_slot_bot.app.bot_manager import BotManager
from s21_slot_bot.app.flows.actions import StopFlowAction
from s21_slot_bot.app.flows.stop import StopFlow
from s21_slot_bot.app.messenger import Messenger
from s21_slot_bot.app.models import BotInstance, CustomContext, Lifecycle


class TestStopFlow:
    async def test_stop_menu_renders_empty_state(
        self,
        stop_flow: StopFlow,
        bot_manager_mock: BotManager,
        messenger_mock: Messenger,
        update_mock: Update,
        context: CustomContext,
    ) -> None:
        bot_manager_mock.list_all.return_value = []

        await stop_flow.stop_menu(update_mock, context)

        assert "нет активных ботов" in messenger_mock.render_menu_message.await_args.args[1]

    async def test_stop_menu_lists_running_bots(
        self,
        stop_flow: StopFlow,
        bot_manager_mock: BotManager,
        messenger_mock: Messenger,
        update_mock: Update,
        context: CustomContext,
        bot_instance_factory: Callable[..., BotInstance],
    ) -> None:
        bot_manager_mock.list_all.return_value = [
            bot_instance_factory(bot_id="bot-1", state=Lifecycle.RUNNING),
        ]

        await stop_flow.stop_menu(update_mock, context)

        bot_manager_mock.list_all.assert_called_once_with(states={Lifecycle.RUNNING})
        assert messenger_mock.render_menu_message.await_args.args[1] == "остановить ботов:"

    async def test_stop_one(
        self,
        stop_flow: StopFlow,
        bot_manager_mock: BotManager,
        messenger_mock: Messenger,
        query_mock: CallbackQuery,
        context: CustomContext,
    ) -> None:
        bot_manager_mock.stop_bot.return_value = True

        await stop_flow.parse_callback(
            ["bot-1", StopFlowAction.STOP_ONE],
            query_mock,
            context,
        )

        bot_manager_mock.stop_bot.assert_called_once()
        assert "бот #bot-1 остановлен" in messenger_mock.render_menu_message.await_args.args[1]

    async def test_stop_all(
        self,
        stop_flow: StopFlow,
        bot_manager_mock: BotManager,
        messenger_mock: Messenger,
        query_mock: CallbackQuery,
        context: CustomContext,
    ) -> None:
        await stop_flow.parse_callback(
            [StopFlowAction.STOP_ALL],
            query_mock,
            context,
        )

        bot_manager_mock.stop_all.assert_called_once()
        assert "все боты остановлены" in messenger_mock.render_menu_message.await_args.args[1]
