import asyncio
from datetime import UTC, datetime

from telegram import InlineKeyboardButton, InlineKeyboardMarkup
from telegram.constants import ParseMode
from telegram.ext import Job

from s21_slot_bot.app.consts import CURRENT_BOOKINGS_SEARCH_WINDOW, UPCOMING_REVIEW_REMINDER_WINDOW
from s21_slot_bot.app.errors import AppNotInitializedError
from s21_slot_bot.app.flows.actions import BookFlowAction
from s21_slot_bot.app.messenger import Messenger
from s21_slot_bot.app.models import App, BotInstance, CustomContext, FlowCategory, IntervalSec
from s21_slot_bot.app.utils import get_tzinfo
from s21_slot_bot.client.errors import School21NoPointsError, School21SlotNotFoundError
from s21_slot_bot.client.models import Booking, DryBooking
from s21_slot_bot.client.s21_client import School21Client
from s21_slot_bot.common.id import hash_id
from s21_slot_bot.common.logger import LogEntity, LoggerLike, get_id_logger
from s21_slot_bot.common.strings import backtick_wrap
from s21_slot_bot.common.time import dt_to_markdown, dt_to_pretty, safe_isoz_to_dt


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
        self._app = app
        self._refresh_interval = refresh_interval
        self._chat_id = chat_id
        self._job: Job[CustomContext] | None = None

    @property
    def bookings(self) -> dict[str, Booking]:
        return self._bookings

    @property
    def dry_bookings(self) -> dict[str, DryBooking]:
        return self._dry_bookings

    @property
    def is_refreshing(self) -> bool:
        return self._job is not None

    def start_refreshing(self, logger: LoggerLike) -> None:
        if not self._app.job_queue:
            raise AppNotInitializedError("очередь задач не инициализирована")
        if self._job is not None:
            logger.info("Booking refresher is already running")
            return
        logger.info("Starting the booking refresher job")
        self._job = self._app.job_queue.run_repeating(
            self._refresh_bookings, self._refresh_interval, chat_id=self._chat_id
        )

    def stop_refreshing(self, logger: LoggerLike) -> None:
        if self._job is None:
            logger.info("Booking refresher is already stopped")
            return
        logger.info("Stopping the booking refresher job")
        self._job.schedule_removal()
        self._job = None

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
            f"🔔 бот #{cfg.bot_id} ({backtick_wrap(cfg.project_name)}) остановлен: найден слот\n"
            f"начало: {dt_to_markdown(start_time, tz=get_tzinfo(context))}",
            kb=kb,
            parse_mode=ParseMode.MARKDOWN_V2,
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
        are_p2p_points_left = True
        cfg = inst.cfg
        tz = get_tzinfo(context)
        try:
            booking_id = await self._s21_client.book(
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
                f"✅ бот #{cfg.bot_id} ({backtick_wrap(cfg.project_name)}): записан\n"
                f"начало: {dt_to_markdown(start_time, tz=tz)}\n"
                f"проверок: {inst.stats.currently_booked}/{cfg.required_reviews}",
                parse_mode=ParseMode.MARKDOWN_V2,
            )
        except School21NoPointsError:
            logger.info("Not enough points to book")
            are_p2p_points_left = False
            await self._messenger.send(
                context,
                f"⛔ бот #{cfg.bot_id} ({cfg.project_name}): остановлен, недостаточно P2P пойнтов",
            )
        except School21SlotNotFoundError as e:
            logger.info("Slot is no longer available")
            inst.stats.attempts_failed += 1
            isoz = e.location.get("input", {}).get("startTime") if e.location else None
            cancelled_time = safe_isoz_to_dt(
                isoz=isoz,
                tz=UTC,
                logger=logger,
            )
            cancelled_slot_message = (
                f"слот на {dt_to_pretty(cancelled_time, tz=tz)} недоступен" if cancelled_time else "слот недоступен"
            )
            await self._messenger.send(
                context,
                f"⚠️ бот #{cfg.bot_id} ({cfg.project_name}): {cancelled_slot_message}",
            )
        return are_p2p_points_left

    def pop_dry(self, dry_run_id: str) -> DryBooking | None:
        dry_booking = self._dry_bookings.pop(dry_run_id, None)
        return dry_booking

    async def _refresh_bookings(self, context: CustomContext) -> None:
        logger = get_id_logger(LogEntity.BOOKING_REFRESHER)
        logger.info("Refreshing bookings")
        now = datetime.now(tz=get_tzinfo(context))
        search_to = now + CURRENT_BOOKINGS_SEARCH_WINDOW
        try:
            fresh_bookings = await self._s21_client.get_bookings(now, search_to, logger)
            async with self._booking_lock:
                stale_bookings = self._bookings.copy()
                self._bookings = fresh_bookings
            context.ensured_chat_data.last_booking_refresh_time = now
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
            f"🔔 проверка проекта {backtick_wrap(booking.project_name)} начинается в {dt_to_markdown(booking.start, tz=get_tzinfo(context))}!"
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
            booking.project_name: dt_to_pretty(booking.start, tz=get_tzinfo(context)) for booking in cancelled_bookings
        }
        logger.info("Notifying on cancelled reviews: %s", project_to_time)
        warning = ["⚠️ проверка отменена!" if len(project_to_time) == 1 else "⚠️ проверки отменены!"]
        lines = [
            f"🚫 проект {project_name} - слот на {cancelled_time}"
            for project_name, cancelled_time in project_to_time.items()
        ]
        text = "\n".join(warning + lines)
        await self._messenger.send(context, text)
