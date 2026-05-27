import enum

from telegram import CallbackQuery, InlineKeyboardButton, InlineKeyboardMarkup, Update

from s21_slot_bot.app.flows.base import Flow, FlowAction
from s21_slot_bot.app.models import BotInstance, CustomContext, FlowCategory
from s21_slot_bot.common.exceptions import InvalidCallbackDataError
from s21_slot_bot.common.logger import get_user_input_logger
from s21_slot_bot.common.strings import ensure_str
from s21_slot_bot.common.time import dt_to_pretty


class StatusFlowAction(FlowAction):
    SHOW = enum.auto()


class StatusFlow(Flow):
    async def parse_callback(self, callback_data: list[str], query: CallbackQuery, context: CustomContext) -> None:
        action = callback_data.pop()
        match action:
            case StatusFlowAction.SHOW:
                await self.status_show(query, context)
            case _:
                raise InvalidCallbackDataError

    # TODO: break down bot statuses based on project
    async def status_show(self, user_input: Update | CallbackQuery, context: CustomContext) -> None:
        logger = get_user_input_logger(user_input)
        logger.info("Showing status...")
        running = len(self._bot_manager.running())
        lines = [
            "📌 статус",
            f"активных: {running}",
            f"максимум: {self._bot_manager.bot_config.max_bots}",
            f"интервал: {self._bot_manager.bot_config.poll_interval_sec} секунд",
        ]
        bots = self._bot_manager.list_all()
        if not bots:
            lines.append("ботов нет")
        else:
            for b in bots:
                lines.append(self._bot_line(b))
        text = "\n".join(lines)
        kb = InlineKeyboardMarkup(
            [
                [InlineKeyboardButton("🔄 обновить", callback_data=f"{FlowCategory.STATUS}:{StatusFlowAction.SHOW}")],
            ]
        )
        await self._messenger.render_menu_message(context, text, kb=kb)

    def _bot_line(self, inst: BotInstance) -> str:
        c = inst.cfg
        return (
            f"#{c.bot_id} {c.project_name} [{inst.state.to_text()}]\n"
            f"проверок: {inst.stats.currently_booked}/{c.required_reviews}, режим {c.mode.to_text()})\n"
            f"окно поиска: {dt_to_pretty(c.from_dt)} → {dt_to_pretty(c.to_dt)}\n"
            f"последняя попытка: {ensure_str(inst.stats.last_ping, getter=dt_to_pretty)}\n"
            f"всего: {inst.stats.attempts_total}\n ({inst.stats.attempts_success} успешных, {inst.stats.attempts_failed} с ошибкой)\n"
        )
