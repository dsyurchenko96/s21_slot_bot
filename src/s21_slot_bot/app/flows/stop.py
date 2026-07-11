import enum
from typing import override

from telegram import CallbackQuery, InlineKeyboardButton, InlineKeyboardMarkup, Update

from s21_slot_bot.app.consts import MAX_NUM_BOTS
from s21_slot_bot.app.flows.base import Flow, FlowAction
from s21_slot_bot.app.models import CustomContext, FlowCategory, Lifecycle
from s21_slot_bot.common.exceptions import InvalidCallbackDataError
from s21_slot_bot.common.logger import get_user_input_logger


class StopFlowAction(FlowAction):
    STOP_MENU = enum.auto()
    STOP_ONE = enum.auto()
    STOP_ALL = enum.auto()


class StopFlow(Flow):
    @override
    async def parse_callback(self, callback_data: list[str], query: CallbackQuery, context: CustomContext) -> None:
        logger = get_user_input_logger(query)
        action = callback_data.pop()
        match action:
            case StopFlowAction.STOP_ONE:
                bot_id = callback_data.pop()
                ok = self._bot_manager.stop_bot(bot_id, context)
                text = f"⛔ бот #{bot_id} остановлен" if ok else f"⚠️ бот #{bot_id} не найден"
                await self._messenger.render_menu_message(context, text, logger)
            case StopFlowAction.STOP_ALL:
                self._bot_manager.stop_all(context)
                await self._messenger.render_menu_message(context, "⛔ все боты остановлены", logger)
            case _:
                raise InvalidCallbackDataError(f"неподдерживаемое действие '{action}' при остановке бота")

    async def stop_menu(self, user_input: Update | CallbackQuery, context: CustomContext) -> None:
        logger = get_user_input_logger(user_input)
        logger.info("Showing stop menu...")
        running_bots = self._bot_manager.list_all(state=Lifecycle.RUNNING)
        if not running_bots:
            await self._messenger.render_menu_message(context, "🚫 нет активных ботов", logger)
            return
        kb = InlineKeyboardMarkup(
            [
                [
                    InlineKeyboardButton(
                        f"🛑 #{b.cfg.bot_id} — {b.cfg.project_name}",
                        callback_data=f"{self._category}:{StopFlowAction.STOP_ONE}:{b.cfg.bot_id}",
                    )
                ]
                for b in running_bots
            ]
            + [
                [
                    InlineKeyboardButton(
                        "🛑 остановить всех", callback_data=f"{self._category}:{StopFlowAction.STOP_ALL}"
                    )
                ]
            ]
        )
        await self._messenger.render_menu_message(context, "остановить ботов:", logger, kb=kb)
