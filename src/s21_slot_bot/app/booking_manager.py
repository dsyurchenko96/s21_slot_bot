import asyncio
from datetime import UTC, datetime, timedelta

from telegram import InlineKeyboardButton, InlineKeyboardMarkup
from telegram.constants import ParseMode

from s21_slot_bot.app.consts import CURRENT_BOOKINGS_SEARCH_WINDOW, UPCOMING_REVIEW_REMINDER_WINDOW
from s21_slot_bot.app.flows.actions import BookFlowAction
from s21_slot_bot.app.messenger import Messenger
from s21_slot_bot.app.models import App, BotInstance, CustomContext, FlowCategory, IntervalSec, SearchConfig
from s21_slot_bot.client.errors import School21Error, School21NoPointsError, School21SlotNotFoundError
from s21_slot_bot.client.models import Booking, DryBooking
from s21_slot_bot.client.s21_client import School21Client
from s21_slot_bot.common.logger import LogEntity, LoggerLike, get_id_logger
from s21_slot_bot.common.random import hash_id
from s21_slot_bot.common.strings import escape_str
from s21_slot_bot.common.time import dt_to_pretty, dt_to_pretty_time, safe_isoz_to_dt


class BookingManager:
    def __init__(
        self,
        s21_client: School21Client,
        messenger: Messenger,
        app: App,
        refresh_interval: IntervalSec,
        chat_id: int,
    ):
        self._s21_client = s21_client
        self._messenger = messenger
        self._dry_bookings: dict[str, DryBooking] = {}
        self._bookings: dict[str, Booking] = {}
        self._booking_lock = asyncio.Lock()
        self._notifications_sent: dict[str, bool] = {}

        self._job = app.job_queue.run_repeating(self._refresh_bookings, refresh_interval, chat_id=chat_id)

    @property
    def bookings(self) -> dict[str, Booking]:
        return self._bookings

    @property
    def dry_bookings(self) -> dict[str, DryBooking]:
        return self._dry_bookings

    async def book_dry(
        self,
        inst: BotInstance,
        answer_id: str,
        start_time: datetime,
        context: CustomContext,
        is_staff_slot: bool = False,
    ) -> None:
        cfg = inst.cfg
        dry_run_id = hash_id(f"{cfg.project_id}|{start_time}")
        dry_booking = DryBooking(
            dry_run_id=dry_run_id,
            is_staff_slot=is_staff_slot,
            answer_id=answer_id,
            project_id=cfg.project_id,
            project_name=cfg.project_name,
            start=start_time,
        )
        self._dry_bookings[dry_run_id] = dry_booking
        inst.stats.attempts_success += 1
        kb = InlineKeyboardMarkup(
            [
                [
                    InlineKeyboardButton(
                        "📝 записаться",
                        callback_data=f"{FlowCategory.BOOK}:{BookFlowAction.BOOK_ATTEMPT_MANUAL}"
                        f":{cfg.bot_id}:{dry_run_id}",
                    )
                ]
            ]
        )
        await self._messenger.send(
            context,
            f"🔔 бот #{cfg.bot_id} ({cfg.project_name}) остановлен: найден слот\n"
            f"начало: {dt_to_pretty(start_time, tz=context.bot.defaults.tzinfo)}",
            kb=kb,
        )

    async def book(
        self,
        inst: BotInstance,
        answer_id: str,
        start_time: datetime,
        logger: LoggerLike,
        context: CustomContext,
        is_staff_slot: bool = False,
    ) -> bool:
        p2p_points_left = True
        cfg = inst.cfg
        try:
            booking_id = self._s21_client.book(
                answer_id=answer_id,
                start_time=start_time,
                is_staff_slot=is_staff_slot,
                logger=logger,
            )
            booking = Booking(
                id=booking_id,
                answer_id=answer_id,
                project_id=cfg.project_id,
                project_name=cfg.project_name,
                start=start_time,
                is_online=True,
            )
            async with self._booking_lock:
                self._bookings[booking_id] = booking
            inst.stats.currently_booked += 1
            inst.stats.attempts_success += 1
            await self._messenger.send(
                context,
                f"✅ бот #{cfg.bot_id} ({cfg.project_name}): записался\n"
                f"начало: {dt_to_pretty(start_time, tz=context.bot.defaults.tzinfo)}\n"
                f"проверок: {inst.stats.currently_booked}/{cfg.required_reviews}",
            )
        except School21NoPointsError:
            logger.info("Not enough points to book")
            p2p_points_left = False
            await self._messenger.send(
                context,
                f"⛔ бот #{cfg.bot_id} ({cfg.project_name}): остановлен, недостаточно P2P пойнтов",
            )
        except School21SlotNotFoundError as e:
            logger.info("Slot is no longer available")
            inst.stats.attempts_failed += 1
            cancelled_time = safe_isoz_to_dt(
                isoz=e.location.get("input", {}).get("startTime"),
                tz=UTC,
                logger=logger,
            )
            cancelled_slot_message = (
                f"слот на {dt_to_pretty(cancelled_time, tz=context.bot.defaults.tzinfo)} недоступен"
                if cancelled_time
                else "слот недоступен"
            )
            await self._messenger.send(
                context,
                f"⚠️ бот #{cfg.bot_id} ({cfg.project_name}): {cancelled_slot_message}",
            )
        return p2p_points_left

    def pop_dry(self, dry_run_id: str) -> DryBooking | None:
        dry_booking = self._dry_bookings.pop(dry_run_id, None)
        return dry_booking

    async def _refresh_bookings(self, context: CustomContext) -> None:
        logger = get_id_logger(LogEntity.BOOKING_REFRESHER)
        logger.info("Refreshing bookings")
        now = datetime.now(tz=context.bot.defaults.tzinfo)
        search_to = now + CURRENT_BOOKINGS_SEARCH_WINDOW
        try:
            fresh_bookings = self._s21_client.get_bookings(now, search_to, logger)
            async with self._booking_lock:
                stale_bookings = self._bookings.copy()
                self._bookings = fresh_bookings
            cancelled_bookings = self._get_cancelled_bookings(fresh_bookings, stale_bookings, now, logger)
            await self._notify_on_cancelled_reviews(cancelled_bookings, context, logger)
            for booking_id, booking in fresh_bookings.items():
                if (
                    booking.start > now
                    and booking.start - now <= UPCOMING_REVIEW_REMINDER_WINDOW
                    and not self._notifications_sent.get(booking_id, False)
                ):
                    await self._notify_on_upcoming_review(booking, context, logger)
        except Exception:
            logger.exception("Failed to refresh bookings")

    def _get_cancelled_bookings(
        self,
        fresh_bookings: dict[str, Booking],
        stale_bookings: dict[str, Booking],
        now: datetime,
        logger: LoggerLike,
    ) -> list[Booking]:
        removed_ids = stale_bookings.keys() - fresh_bookings.keys()
        cancelled_ids = set()
        expired_ids = set()
        for removed_id in removed_ids:
            self._notifications_sent.pop(removed_id, None)
            stale = stale_bookings[removed_id]
            if now >= stale.start:
                expired_ids.add(removed_id)
            else:
                cancelled_ids.add(removed_id)
        if expired_ids:
            expired_bookings = {
                stale_bookings[exp_id].project_name: stale_bookings[exp_id].start for exp_id in expired_ids
            }
            logger.info("Expired bookings: %s", expired_bookings)
        cancelled_bookings = [stale_bookings[cancelled_id] for cancelled_id in cancelled_ids]
        return cancelled_bookings

    async def _notify_on_upcoming_review(self, booking: Booking, context: CustomContext, logger: LoggerLike) -> None:
        logger.info("Sending a notification about an upcoming review of %s at %s", booking.project_name, booking.start)
        link_text = f"\nссылка для подключения: {booking.url}" if booking.url else ""
        text = (
            f"🔔 проверка проекта {escape_str(booking.project_name)} начинается в {dt_to_pretty_time(booking.start, tz=context.bot.defaults.tzinfo)}!"
            + link_text
        )
        await self._messenger.send(context, text, parse_mode=ParseMode.MARKDOWN_V2)
        self._notifications_sent[booking.id] = True

    async def _notify_on_cancelled_reviews(
        self,
        cancelled_bookings: list[Booking],
        context: CustomContext,
        logger: LoggerLike,
    ) -> None:
        if not cancelled_bookings:
            return

        project_to_time = {
            booking.project_name: dt_to_pretty(booking.start, tz=context.bot.defaults.tzinfo)
            for booking in cancelled_bookings
        }
        logger.info("Notifying on cancelled reviews: %s", project_to_time)
        warning = ["⚠️ проверка отменена!" if len(project_to_time) == 1 else "⚠️ проверки отменены!"]
        lines = [
            f"🚫 проект {project_name} - слот на {cancelled_time}"
            for project_name, cancelled_time in project_to_time.items()
        ]
        text = "\n".join(warning + lines)
        await self._messenger.send(context, text)
