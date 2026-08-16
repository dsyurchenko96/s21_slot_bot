from typing import override

from telegram import CallbackQuery, InlineKeyboardButton, InlineKeyboardMarkup, Update

from s21_slot_bot.app.errors import InvalidCallbackDataError
from s21_slot_bot.app.flows.actions import DeleteFlowAction
from s21_slot_bot.app.flows.base import Flow
from s21_slot_bot.app.models import CustomContext, Lifecycle
from s21_slot_bot.common.logger import get_user_input_logger


class DeleteFlow(Flow):
    @override
    async def parse_callback(self, callback_data: list[str], query: CallbackQuery, context: CustomContext) -> None:
        logger = get_user_input_logger(query)
        action = callback_data.pop()
        match action:
            case DeleteFlowAction.DELETE_ONE:
                bot_id = callback_data.pop()
                ok = self._bot_manager.delete_bot(bot_id, context, logger)
                text = f"🗑️ бот #{bot_id} удален" if ok else f"⚠️ не удалось удалить бота #{bot_id}"
                await self._messenger.render_menu_message(context, text, logger)
            case DeleteFlowAction.DELETE_ALL | DeleteFlowAction.DELETE_ALL_STOPPED:
                states = (
                    {Lifecycle.STOPPED, Lifecycle.FAILED} if action == DeleteFlowAction.DELETE_ALL_STOPPED else None
                )
                num_deleted = self._bot_manager.delete_all(context, logger, states=states)
                text = f"🗑️ удалено ботов: {num_deleted}" if num_deleted else "⚠️ не найдено ботов для удаления"
                await self._messenger.render_menu_message(context, text, logger)
            case _:
                raise InvalidCallbackDataError(f"неподдерживаемое действие '{action}' при удалении бота")

    async def delete_menu(self, user_input: Update | CallbackQuery, context: CustomContext) -> None:
        logger = get_user_input_logger(user_input)
        logger.info("Showing delete menu...")
        all_bots = self._bot_manager.list_all()
        if not all_bots:
            await self._messenger.render_menu_message(context, "🚫 нет ботов", logger)
            return
        kb = InlineKeyboardMarkup(
            [
                [
                    InlineKeyboardButton(
                        f"🗑️ #{b.cfg.bot_id} — {b.cfg.project_name}",
                        callback_data=f"{self._category}:{DeleteFlowAction.DELETE_ONE}:{b.cfg.bot_id}",
                    )
                ]
                for b in all_bots
            ]
            + [
                [
                    InlineKeyboardButton(
                        "🗑 удалить всех",
                        callback_data=f"{self._category}:{DeleteFlowAction.DELETE_ALL}",
                    )
                ],
                [
                    InlineKeyboardButton(
                        "🗑 удалить всех остановленных",
                        callback_data=f"{self._category}:{DeleteFlowAction.DELETE_ALL_STOPPED}",
                    )
                ],
            ]
        )
        await self._messenger.render_menu_message(context, "удалить ботов:", logger, kb=kb)
