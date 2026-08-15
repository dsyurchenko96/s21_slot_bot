from datetime import datetime

from s21_slot_bot.app.booking_manager import BookingManager
from s21_slot_bot.app.config import BotConfig
from s21_slot_bot.app.errors import (
    BotNotFoundError,
    BotRuntimeError,
    InternalError,
    TooManyBotsError,
)
from s21_slot_bot.app.messenger import Messenger
from s21_slot_bot.app.models import (
    BotInstance,
    CustomContext,
    IntervalSec,
    JobData,
    Lifecycle,
    Mode,
    NumBots,
)
from s21_slot_bot.app.utils import get_tzinfo
from s21_slot_bot.client.models import TimeSlot
from s21_slot_bot.client.s21_client import School21Client
from s21_slot_bot.common.logger import LoggerLike


class BotManager:
    def __init__(
        self,
        bot_config: BotConfig,
        chat_id: int,
        messenger: Messenger,
        s21_client: School21Client,
        booking_manager: BookingManager,
    ) -> None:
        self._bot_config = bot_config
        self._chat_id = chat_id
        self._messenger = messenger
        self._s21_client = s21_client
        self._booking_manager = booking_manager
        self._bots: dict[str, BotInstance] = {}

    @property
    def max_bots(self) -> NumBots:
        return self._bot_config.max_bots

    @property
    def poll_interval_sec(self) -> IntervalSec:
        return self._bot_config.poll_interval_sec

    def check_bot_limits(self) -> None:
        if len(self.list_all()) > self._bot_config.max_bots:
            raise TooManyBotsError(f"Максимальное количество ботов превышено ({self._bot_config.max_bots})")

    def get_bot(self, bot_id: str | None) -> BotInstance:
        bot = self._bots.get(bot_id) if bot_id else None
        if not bot:
            raise BotNotFoundError(f"бот #{bot_id} не найден")
        return bot

    def list_all(self, state: Lifecycle | None = None) -> list[BotInstance]:
        arr = [b for b in self._bots.values() if not state or b.state == state]

        def key(x: BotInstance) -> tuple[int, str, str]:
            pr = {Lifecycle.RUNNING: 0, Lifecycle.STOPPED: 1}.get(x.state, 9)
            return pr, x.cfg.project_id, x.cfg.bot_id

        return sorted(arr, key=key)

    def stop_bot(self, bot_id: str, context: CustomContext, logger: LoggerLike) -> bool:
        inst = self._bots.get(bot_id)
        if not inst:
            logger.warning("Unable to find bot `%s`", bot_id)
            return False
        inst.state = Lifecycle.STOPPED
        jobs = context.ensured_job_queue.get_jobs_by_name(bot_id)
        if not jobs:
            logger.error("Unable to find job for bot `%s`", bot_id)
            return False
        if len(jobs) > 1:
            logger.warning("%d jobs found with ID `%s` - there may be a name collision", len(jobs), bot_id)
        for job in jobs:
            job.schedule_removal()
            logger.info("Stopped job ID `%s`", job.name)
        has_running_bots = bool(self.list_all(state=Lifecycle.RUNNING))
        if not has_running_bots and not self._bot_config.should_refresh_bookings_always:
            self._booking_manager.stop_refreshing(logger)
        return True

    def stop_all(self, context: CustomContext, logger: LoggerLike) -> None:
        for inst in self.list_all(state=Lifecycle.RUNNING):
            self.stop_bot(inst.cfg.bot_id, context, logger)

    def delete_bot(self, bot_id: str, context: CustomContext, logger: LoggerLike) -> bool:
        if not self.stop_bot(bot_id, context, logger):
            return False
        inst = self._bots.pop(bot_id, None)
        is_deleted = bool(inst)
        return is_deleted

    def delete_all(self, context: CustomContext, logger: LoggerLike, state: Lifecycle | None = None) -> int:
        deleted_counter = 0
        for inst in self.list_all(state=state):
            if self.delete_bot(inst.cfg.bot_id, context, logger):
                deleted_counter += 1
        return deleted_counter

    async def start_bot(self, inst: BotInstance, context: CustomContext, logger: LoggerLike) -> None:
        cfg = inst.cfg
        try:
            task_id, answer_id = await self._s21_client.get_task_and_answer(cfg.project_id, logger)
        except Exception as e:
            raise BotRuntimeError(
                f"бот #{cfg.bot_id}: не удалось получить необходимую информацию для начала поиска"
            ) from e

        inst.state = Lifecycle.RUNNING
        self._bots[cfg.bot_id] = inst
        job_data = JobData(inst=inst, task_id=task_id, answer_id=answer_id)
        job = context.ensured_job_queue.run_repeating(
            self._search, cfg.interval_sec, data=job_data, chat_id=self._chat_id, name=cfg.bot_id
        )
        logger.info("Started bot #%s", cfg.bot_id)
        self._booking_manager.start_refreshing(logger)
        await job.run(context.application)  # type: ignore [arg-type]

    async def _search(self, context: CustomContext) -> None:
        job = context.job
        if not job:
            raise InternalError("задача на поиск не найдена")
        job_data = JobData.model_validate(job.data)
        inst, answer_id, task_id = job_data.inst, job_data.answer_id, job_data.task_id
        logger = inst.logger()
        cfg = inst.cfg
        tz = get_tzinfo(context)

        if inst.state != Lifecycle.RUNNING:
            logger.warning("Bot `%s` is not currently running, stopping job `%s`", cfg.bot_id, job.name)
            self.stop_bot(cfg.bot_id, context, logger)
            return

        if datetime.now(tz=tz) >= cfg.to_dt:
            logger.info("Removing the current bot search due to expiration")
            self.delete_bot(cfg.bot_id, context, logger)
            await self._messenger.send(
                context,
                f"⌛️ бот #{cfg.bot_id} ({cfg.project_name}): удален, окно поиска истекло",
            )
            return

        inst.stats.attempts_total += 1
        inst.stats.last_ping = datetime.now(tz=tz)

        try:
            slots_info = await self._s21_client.get_slots_info(task_id, cfg.from_dt, cfg.to_dt, logger)
            currently_booked = slots_info.review_info.booked
            inst.stats.currently_booked = currently_booked
            missing = cfg.required_reviews - currently_booked
            if missing < 1:
                logger.info(
                    "No more reviews required (%d/%d), finishing current search", currently_booked, cfg.required_reviews
                )
                return

            picked = self._pick_candidate_start(slots_info.time_slots)
            if not picked:
                logger.info("No suitable timeslots found")
                return

            start_time, is_staff_slot = picked
            match cfg.mode:
                case Mode.ONLY_FIND:
                    await self._booking_manager.book_dry(
                        inst=inst,
                        answer_id=answer_id,
                        start_time=start_time,
                        context=context,
                        is_staff_slot=is_staff_slot,
                    )
                    self.stop_bot(cfg.bot_id, context, logger)
                case Mode.FIND_AND_BOOK:
                    are_p2p_points_left = await self._booking_manager.book(
                        inst=inst,
                        answer_id=answer_id,
                        start_time=start_time,
                        logger=logger,
                        context=context,
                        is_staff_slot=is_staff_slot,
                    )
                    if not are_p2p_points_left:
                        self.stop_bot(cfg.bot_id, context, logger)
            inst.stats.failed_retry = 0
        except Exception as e:
            inst.stats.attempts_failed += 1
            inst.stats.failed_retry += 1
            logger.exception(
                "Failed attempt %d (retry %d) running bot %s",
                inst.stats.attempts_failed,
                inst.stats.failed_retry,
                cfg.bot_id,
            )
            if inst.stats.failed_retry % self._bot_config.max_retries == 0:
                raise BotRuntimeError(f"бот #{cfg.bot_id} ({cfg.project_name}): ошибка поиска") from e

    def _pick_candidate_start(self, timeslots: list[TimeSlot]) -> tuple[datetime, bool] | None:
        candidates: list[tuple[datetime, bool]] = []
        for slot in timeslots:
            for time in slot.valid_start_times:
                candidates.append((time, slot.staff_slot))
        if not candidates:
            return None
        candidates.sort(key=lambda candidate: candidate[0])
        return candidates[0]
