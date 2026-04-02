import enum
import logging
from enum import StrEnum

import telegram
from telegram import CallbackQuery, Update, InlineKeyboardMarkup, InlineKeyboardButton
from telegram.ext import ContextTypes

from s21_slot_bot.app.exceptions import InvalidCallbackData
from s21_slot_bot.app.flows.base import Flow
from s21_slot_bot.app.models import Lifecycle, BotInstance, FlowCategory
from s21_slot_bot.common.time import dt_to_pretty

_logger = logging.getLogger(__name__)


class StatusFlowAction(StrEnum):
    REFRESH = enum.auto()


class StatusFlow(Flow):
    async def parse_callback(
        self, callback_data: list[str], query: CallbackQuery, context: ContextTypes.DEFAULT_TYPE
    ) -> None:
        action = callback_data.pop()
        match action:
            case StatusFlowAction.REFRESH:
                await self.status_show(query, context)
            case _:
                raise InvalidCallbackData


    # TODO: break down bot statuses based on project
    async def status_show(self, user_input: Update | CallbackQuery, context: ContextTypes.DEFAULT_TYPE) -> None:
        chat_id = user_input.message.chat_id
        running = self._bot_manager.running_count(chat_id)
        queued = len(self._bot_manager.queues.get(chat_id, []))
        lines = [
            f"📌 статус\nrunning: {running}\nqueued: {queued}\n"
            f"max: {self._bot_manager.config.max_bots}\ninterval: {self._bot_manager.config.poll_interval_sec}s\n"
        ]
        bots = self._bot_manager.list_all(chat_id)
        if not bots:
            lines.append("ботов нет")
        else:
            for b in bots:
                if b.state != Lifecycle.DONE:
                    lines.append(self._bot_line(b))
        text = "\n".join(lines).strip()
        kb = InlineKeyboardMarkup(
            [
                [
                    InlineKeyboardButton(
                        "🔄 обновить", callback_data=f"{FlowCategory.STATUS}:{StatusFlowAction.REFRESH}"
                    )
                ],
            ]
        )
        try:
            await self._respond_to_input(user_input, text, kb)
        except telegram.error.BadRequest as e:
            _logger.info("No update has taken place: %s", e)

    def _bot_line(self, inst: BotInstance) -> str:
        c = inst.cfg
        lp = dt_to_pretty(inst.stats.last_ping) if inst.stats.last_ping else "—"
        return (
            f"#{c.bot_id} [{inst.state}] {c.project_name} "
            f"({c.required_reviews} reviews, {'dry' if c.dry_run else 'book'})\n"
            f"time: {dt_to_pretty(c.from_dt)} → {dt_to_pretty(c.to_dt)}\n"
            f"last ping: {lp}, attempts: {inst.stats.attempts_total} "
            f"(ok {inst.stats.attempts_success} / fail {inst.stats.attempts_failed} / booked {inst.stats.currently_booked})\n"
        )
