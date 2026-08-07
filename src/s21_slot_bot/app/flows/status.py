from collections import defaultdict
from typing import override

from pydantic import AwareDatetime
from telegram import CallbackQuery, InlineKeyboardButton, InlineKeyboardMarkup, Update
from telegram.constants import ParseMode

from s21_slot_bot.app.consts import STATUS_LINE_INDENT
from s21_slot_bot.app.errors import InvalidCallbackDataError
from s21_slot_bot.app.flows.actions import StatusFlowAction
from s21_slot_bot.app.flows.base import Flow
from s21_slot_bot.app.models import BotInstance, CustomContext, Lifecycle
from s21_slot_bot.client.models import Booking, DryBooking
from s21_slot_bot.common.logger import get_user_input_logger
from s21_slot_bot.common.strings import backtick_wrap, ensure_str
from s21_slot_bot.common.time import dt_to_markdown, dt_to_pretty


class StatusFlow(Flow):
    @override
    async def parse_callback(self, callback_data: list[str], query: CallbackQuery, context: CustomContext) -> None:
        action = callback_data.pop()
        match action:
            case StatusFlowAction.SHOW:
                await self.status_show(query, context)
            case _:
                raise InvalidCallbackDataError(f"неподдерживаемое действие '{action}' при демонстрации статуса")

    # TODO: show numbers "booked/required"?
    # TODO: add Rich Messages once they're supported (https://github.com/python-telegram-bot/python-telegram-bot/issues/5261)
    async def status_show(self, user_input: Update | CallbackQuery, context: CustomContext) -> None:
        logger = get_user_input_logger(user_input)
        logger.info("Showing status...")
        status_lines = self._get_status_lines(context)
        text = "\n".join(status_lines)
        kb = InlineKeyboardMarkup(
            [
                [InlineKeyboardButton("🔄 обновить", callback_data=f"{self._category}:{StatusFlowAction.SHOW}")],
            ]
        )
        await self._messenger.render_menu_message(context, text, logger, kb=kb, parse_mode=ParseMode.MARKDOWN_V2)

    def _get_status_lines(self, context: CustomContext) -> list[str]:
        status_lines = self._get_base_lines()
        booking_refresher_lines = self._get_booking_refresher_lines(context)
        status_lines.append("\n".join(booking_refresher_lines))
        all_bots = self._bot_manager.list_all()
        if not all_bots:
            status_lines.append("📭 ботов нет")
            return status_lines

        project_names_to_bots: dict[str, list[BotInstance]] = defaultdict(list)
        bookings = self._booking_manager.bookings
        dry_bookings = self._booking_manager.dry_bookings
        for bot in all_bots:
            project_names_to_bots[bot.cfg.project_name].append(bot)

        for project_name, project_bots in sorted(project_names_to_bots.items()):
            status_lines.append(f"📁 {backtick_wrap(project_name)}")
            booking_lines = self._get_booking_lines(project_name, bookings, dry_bookings, context)
            if booking_lines:
                status_lines.append("\n".join(booking_lines))
            for bot in project_bots:
                bot_lines = self._get_bot_lines(bot, context)
                status_lines.append("\n".join(bot_lines))
            status_lines.append("\n")
        return status_lines

    def _get_base_lines(self) -> list[str]:
        num_running_bots = len(self._bot_manager.list_all(state=Lifecycle.RUNNING))
        num_total_bots = len(self._bot_manager.list_all())
        base_lines = [
            "📌 статус",
            f"активных: {num_running_bots}",
            f"всего: {num_total_bots}",
            f"максимум: {self._bot_manager.max_bots}",
            f"интервал: {self._bot_manager.poll_interval_sec} секунд",
            "\n",
        ]
        return base_lines

    def _get_bot_lines(self, inst: BotInstance, context: CustomContext) -> list[str]:
        c = inst.cfg
        from_pretty = dt_to_pretty(c.from_dt, tz=context.bot.defaults.tzinfo)
        to_pretty = dt_to_pretty(c.to_dt, tz=context.bot.defaults.tzinfo)
        emoji = "▶️" if inst.state == Lifecycle.RUNNING else "⏸️"
        bot_lines = [
            f"{emoji} #{c.bot_id} [{inst.state.to_text()}]",
            f"проверок: {inst.stats.currently_booked}/{c.required_reviews}",
            f"режим: {c.mode.to_text()}",
            f"окно поиска: {from_pretty} → {to_pretty}",
            f"последняя попытка: {ensure_str(inst.stats.last_ping, getter=dt_to_pretty, tz=context.bot.defaults.tzinfo)}",
            f"всего: {inst.stats.attempts_total} ({inst.stats.attempts_success} успешных, {inst.stats.attempts_failed} с ошибкой)",
        ]
        self._add_indent(bot_lines, STATUS_LINE_INDENT * 3, first_indent_delta=len(emoji) * 3)
        return bot_lines

    def _get_booking_refresher_lines(self, context: CustomContext) -> list[str]:
        emoji, state = ("▶️", "активно") if self._booking_manager.is_refreshing else ("⏸️", "остановлено")
        last_refresh = ensure_str(
            context.chat_data.last_booking_refresh_time, getter=dt_to_pretty, tz=context.bot.defaults.tzinfo
        )
        booking_refresher_lines = [
            f"{emoji} обновление актуальных проверок [{state}]",
            f"последний запуск: {last_refresh}",
            "\n",
        ]
        self._add_indent(booking_refresher_lines, STATUS_LINE_INDENT, first_indent_delta=STATUS_LINE_INDENT)
        return booking_refresher_lines

    def _get_booking_lines(
        self,
        project_name: str,
        bookings: dict[str, Booking],
        dry_bookings: dict[str, DryBooking],
        context: CustomContext,
    ) -> list[str]:
        start_to_dry: dict[AwareDatetime, bool] = {}
        for booking in bookings.values():
            if booking.project_name == project_name:
                start_to_dry[booking.start] = False
        for dry_booking in dry_bookings.values():
            if dry_booking.project_name == project_name:
                start_to_dry[dry_booking.start] = True
        booking_lines = []
        for start_time, is_dry in sorted(start_to_dry.items()):
            message = "🔍 найден слот" if is_dry else "📝 запись"
            line = f"🗓️ {dt_to_markdown(start_time, tz=context.bot.defaults.tzinfo)} - {message}"
            booking_lines.append(line)
        self._add_indent(booking_lines, STATUS_LINE_INDENT)
        return booking_lines

    def _add_indent(self, lines: list[str], len_indent: int, first_indent_delta: int = 0) -> None:
        indent = " " * len_indent
        first_indent_len = max(0, len_indent - first_indent_delta)
        first_indent = " " * first_indent_len
        for idx, line in enumerate(lines):
            if idx == 0:
                lines[idx] = first_indent + line
            else:
                lines[idx] = indent + line
