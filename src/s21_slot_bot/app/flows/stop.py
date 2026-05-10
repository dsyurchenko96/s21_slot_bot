import enum
from enum import StrEnum

from telegram import CallbackQuery, InlineKeyboardButton, InlineKeyboardMarkup, Update

from s21_slot_bot.app.flows.base import Flow
from s21_slot_bot.app.messages import render_message
from s21_slot_bot.app.models import CustomContext, FlowCategory, Screen
from s21_slot_bot.common.exceptions import InvalidCallbackData


class StopFlowAction(StrEnum):
    STOP_MENU = enum.auto()
    PICK_ONE = enum.auto()
    STOP_ONE = enum.auto()
    STOP_ALL = enum.auto()


class StopFlow(Flow):
    async def parse_callback(self, callback_data: list[str], query: CallbackQuery, context: CustomContext) -> None:
        action = callback_data.pop()
        match action:
            case StopFlowAction.STOP_MENU:
                await self.stop_menu(query, context)
            case StopFlowAction.STOP_ALL:
                self._bot_manager.stop_all(query.message.chat_id)
                text = "⛔ все боты остановлены"
                await render_message(query, context, text)
            case StopFlowAction.PICK_ONE:
                await self.stop_pick_one(query, context)
            case StopFlowAction.STOP_ONE:
                bot_id = callback_data.pop()
                ok = self._bot_manager.stop_bot(bot_id)
                text = f"⛔ бот #{bot_id} остановлен" if ok else f"⚠️ бот #{bot_id} не найден"
                await render_message(query, context, text)
            case _:
                raise InvalidCallbackData

    # TODO: change signature
    async def stop_menu(self, update: Update, context: CustomContext) -> None:
        self._screen_set(context, Screen.STOP_MENU)
        chat_id = update.message.chat_id
        if not self._bot_manager.running(chat_id):
            text = "нет активных ботов"
            await render_message(update, context, text)
            return
        kb = InlineKeyboardMarkup(
            [
                [
                    InlineKeyboardButton(
                        "🛑 остановить всех", callback_data=f"{FlowCategory.STOP}:{StopFlowAction.STOP_ALL}"
                    )
                ],
                [
                    InlineKeyboardButton(
                        "🛑 остановить одного", callback_data=f"{FlowCategory.STOP}:{StopFlowAction.PICK_ONE}"
                    )
                ],
            ]
        )
        text = "остановить ботов:"
        await render_message(update, context, text, kb=kb)

    async def stop_pick_one(self, q, context: CustomContext) -> None:
        chat_id = q.message.chat_id
        bots = self._bot_manager.running(chat_id)
        kb = InlineKeyboardMarkup(
            [
                [
                    InlineKeyboardButton(
                        f"🛑 #{b.cfg.bot_id} — {b.cfg.project_name}",
                        callback_data=f"{FlowCategory.STOP}:{StopFlowAction.STOP_ONE}:{b.cfg.bot_id}",
                    )
                ]
                for b in bots[:20]
            ]
        )
        text = "выбери бота:"
        await render_message(q, context, text, kb=kb)
