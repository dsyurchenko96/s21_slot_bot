from typing import override

from telegram import CallbackQuery, InlineKeyboardButton, InlineKeyboardMarkup, Update
from telegram.constants import ParseMode

from s21_slot_bot.app.errors import InvalidCallbackDataError
from s21_slot_bot.app.flows.actions import StatusFlowAction
from s21_slot_bot.app.flows.base import Flow
from s21_slot_bot.app.models import BotInstance, CustomContext, Lifecycle
from s21_slot_bot.common.logger import get_user_input_logger
from s21_slot_bot.common.strings import ensure_str, escape_str
from s21_slot_bot.common.time import dt_to_pretty


class StatusFlow(Flow):
    @override
    async def parse_callback(self, callback_data: list[str], query: CallbackQuery, context: CustomContext) -> None:
        action = callback_data.pop()
        match action:
            case StatusFlowAction.SHOW:
                await self.status_show(query, context)
            case _:
                raise InvalidCallbackDataError(f"неподдерживаемое действие '{action}' при демонстрации статуса")

    # TODO: break down bot statuses based on project + show numbers "booked/required"
    # TODO: show currently booked slots?
    async def status_show(self, user_input: Update | CallbackQuery, context: CustomContext) -> None:
        logger = get_user_input_logger(user_input)
        logger.info("Showing status...")
        num_running_bots = len(self._bot_manager.list_all(state=Lifecycle.RUNNING))
        num_total_bots = len(self._bot_manager.list_all())
        lines = [
            "📌 статус",
            f"активных: {num_running_bots}",
            f"всего: {num_total_bots}",
            f"максимум: {self._bot_manager.max_bots}",
            f"интервал: {self._bot_manager.poll_interval_sec} секунд",
        ]
        bots = self._bot_manager.list_all()
        if not bots:
            lines.append("ботов нет")
        else:
            for b in bots:
                lines.append(self._bot_line(b, context, is_markdown=True))
        text = "\n".join(lines)
        kb = InlineKeyboardMarkup(
            [
                [InlineKeyboardButton("🔄 обновить", callback_data=f"{self._category}:{StatusFlowAction.SHOW}")],
            ]
        )
        await self._messenger.render_menu_message(context, text, logger, kb=kb, parse_mode=ParseMode.MARKDOWN_V2)

    def _bot_line(self, inst: BotInstance, context: CustomContext, is_markdown: bool = False) -> str:
        c = inst.cfg
        project_name = escape_str(c.project_name) if is_markdown else c.project_name
        from_pretty = dt_to_pretty(c.from_dt, tz=context.bot.defaults.tzinfo)
        to_pretty = dt_to_pretty(c.to_dt, tz=context.bot.defaults.tzinfo)
        return (
            f"#{c.bot_id} {project_name} [{inst.state.to_text()}]\n"
            f"проверок: {inst.stats.currently_booked}/{c.required_reviews}, режим {c.mode.to_text()})\n"
            f"окно поиска: {from_pretty} → {to_pretty}\n"
            f"последняя попытка: {ensure_str(inst.stats.last_ping, getter=dt_to_pretty, tz=context.bot.defaults.tzinfo)}\n"
            f"всего: {inst.stats.attempts_total} ({inst.stats.attempts_success} успешных, {inst.stats.attempts_failed} с ошибкой)\n"
        )
