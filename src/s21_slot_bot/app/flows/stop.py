import enum
from enum import StrEnum

from telegram import CallbackQuery, Update, InlineKeyboardMarkup, InlineKeyboardButton
from telegram.ext import ContextTypes

from s21_slot_bot.app.exceptions import InvalidCallbackData
from s21_slot_bot.app.flows.base import Flow
from s21_slot_bot.app.menu_markup import MAIN_MENU_KB
from s21_slot_bot.app.models import Screen, FlowCategory


class StopFlowAction(StrEnum):
    STOP_PICK_ONE = enum.auto()
    STOP_ONE_BOT = enum.auto()
    STOP_ALL = enum.auto()


class StopFlow(Flow):
    async def parse_callback(
        self, callback_data: list[str], query: CallbackQuery, context: ContextTypes.DEFAULT_TYPE
    ) -> None:
        action = callback_data.pop()
        match action:
            case StopFlowAction.STOP_ALL:
                self._bot_manager.stop_all(query.message.chat_id)
                await query.message.reply_text("⛔ остановил всех", reply_markup=MAIN_MENU_KB)
            case StopFlowAction.STOP_PICK_ONE:
                await self.stop_pick_one(query, context)
            case StopFlowAction.STOP_ONE_BOT:
                bot_id = callback_data.pop()
                ok = self._bot_manager.stop_bot(bot_id)
                await query.message.reply_text("⛔ остановил" if ok else "не нашёл", reply_markup=MAIN_MENU_KB)
            case _:
                raise InvalidCallbackData

    async def stop_menu(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        self._screen_set(context, Screen.STOP_MENU)
        chat_id = update.message.chat_id
        if not self._bot_manager.running(chat_id):
            await update.message.reply_text("нет активных ботов", reply_markup=MAIN_MENU_KB)
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
                        "🛑 остановить одного", callback_data=f"{FlowCategory.STOP}:{StopFlowAction.STOP_PICK_ONE}"
                    )
                ],
            ]
        )
        await update.message.reply_text("остановить ботов:", reply_markup=kb)

    async def stop_pick_one(self, q, context: ContextTypes.DEFAULT_TYPE) -> None:
        chat_id = q.message.chat_id
        bots = self._bot_manager.running(chat_id)
        kb = [
            [
                InlineKeyboardButton(
                    f"🛑 #{b.cfg.bot_id} — {b.cfg.project_name}",
                    callback_data=f"{FlowCategory.STOP}:{StopFlowAction.STOP_ONE_BOT}:{b.cfg.bot_id}",
                )
            ]
            for b in bots[:20]
        ]
        await q.message.reply_text("выбери бота:", reply_markup=InlineKeyboardMarkup(kb))
