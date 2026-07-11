import asyncio
import logging
import random
from asyncio import Task
from datetime import datetime
from typing import Any

from s21_slot_bot.app.config import BotConfig
from s21_slot_bot.app.messenger import Messenger
from s21_slot_bot.app.models import BotInstance, CustomContext, IntervalSec, JobData, Lifecycle, Mode, NumBots
from s21_slot_bot.client.config import S21ClientConfig
from s21_slot_bot.client.models import TimeSlot
from s21_slot_bot.client.s21_client import School21Client
from s21_slot_bot.common.exceptions import BotNotFoundError, BotRuntimeError, TooManyBotsError
from s21_slot_bot.common.time import dt_to_pretty

_logger = logging.getLogger(__name__)


class BotManager:
    def __init__(
        self,
        bot_config: BotConfig,
        messenger: Messenger,
        chat_id: int,
        s21_config: S21ClientConfig,
        s21_client_factory: type[School21Client] = School21Client,
    ) -> None:
        self._bot_config = bot_config
        self._messenger = messenger
        self._chat_id = chat_id
        self._s21_config = s21_config
        self._s21_client_factory = s21_client_factory
        self._bots: dict[str, BotInstance] = {}

    @property
    def max_bots(self) -> NumBots:
        return self._bot_config.max_bots

    @property
    def poll_interval_sec(self) -> IntervalSec:
        return self._bot_config.poll_interval_sec

    def check_bot_limits(self) -> None:
        if len(self.list_all()) >= self._bot_config.max_bots:
            raise TooManyBotsError(f"Максимальное количество ботов превышено ({self._bot_config.max_bots})")

    def get_bot(self, bot_id: str | None) -> BotInstance:
        bot = self._bots.get(bot_id)
        if not bot:
            raise BotNotFoundError(f"бот #{bot_id} не найден")
        return bot

    def list_all(self, state: Lifecycle | None = None) -> list[BotInstance]:
        arr = [b for b in self._bots.values() if not state or b.state == state]

        def key(x: BotInstance) -> tuple[int, int, str]:
            pr = {Lifecycle.RUNNING: 0, Lifecycle.STOPPED: 1}.get(x.state, 9)
            return pr, x.cfg.project_id, x.cfg.bot_id

        return sorted(arr, key=key)

    def stop_bot(self, bot_id: str, context: CustomContext) -> bool:
        inst = self._bots.get(bot_id)
        if not inst:
            _logger.warning("Unable to find bot `%s`", bot_id)
            return False
        logger = inst.logger()
        inst.state = Lifecycle.STOPPED
        jobs = context.job_queue.get_jobs_by_name(bot_id)
        if not jobs:
            logger.error("Unable to find job for bot `%s`", bot_id)
            return False
        if len(jobs) > 1:
            logger.warning("%d jobs found with ID `%s` - there may be a name collision", len(jobs), bot_id)
        for job in jobs:
            job.schedule_removal()
            logger.info("Stopped job ID `%s`", job.name)
        return True

    def stop_all(self, context: CustomContext) -> None:
        for inst in self.list_all(state=Lifecycle.RUNNING):
            self.stop_bot(inst.cfg.bot_id, context)

    def delete_bot(self, bot_id: str, context: CustomContext) -> bool:
        if not self.stop_bot(bot_id, context):
            return False
        inst = self._bots.pop(bot_id, None)
        return bool(inst)

    def delete_all(self, context: CustomContext, state: Lifecycle | None = None) -> int:
        deleted_counter = 0
        for inst in self.list_all(state=state):
            if self.delete_bot(inst.cfg.bot_id, context):
                deleted_counter += 1
        return deleted_counter

    async def start_bot(self, inst: BotInstance, context: CustomContext) -> None:
        cfg = inst.cfg
        logger = inst.logger()
        s21_client = self._s21_client_factory(config=self._s21_config)
        try:
            task_id, answer_id = s21_client.get_task_and_answer(cfg.project_id, logger)
        except Exception as e:
            raise BotRuntimeError(
                f"бот #{cfg.bot_id}: не удалось получить необходимую информацию для начала поиска"
            ) from e

        inst.state = Lifecycle.RUNNING
        self._bots[inst.cfg.bot_id] = inst
        job_data = JobData(s21_client=s21_client, inst=inst, task_id=task_id, answer_id=answer_id)
        job = context.application.job_queue.run_repeating(
            self._search, cfg.interval_sec, data=job_data, chat_id=self._chat_id, name=cfg.bot_id
        )
        await job.run(context.application)
        # inst.task = context.application.create_task(self.run_bot_loop(inst, context))

    async def _search(self, context: CustomContext) -> None:
        job = context.job
        job_data = JobData.model_validate(job.data)
        s21_client, inst, answer_id, task_id = job_data.s21_client, job_data.inst, job_data.answer_id, job_data.task_id
        logger = inst.logger()
        cfg = inst.cfg

        if inst.state != Lifecycle.RUNNING:
            logger.warning("Bot `%s` is not currently running, stopping job `%s`", cfg.bot_id, job.name)
            job.schedule_removal()
            return

        if datetime.now(tz=context.bot.defaults.tzinfo) >= cfg.to_dt:
            logger.info("Removing the current bot search due to expiration")
            self.delete_bot(inst.cfg.bot_id, context)
            await self._messenger.send(
                context,
                f"⌛️ бот #{cfg.bot_id} ({cfg.project_name}): удален, окно поиска истекло",
            )
            return

        inst.stats.attempts_total += 1
        inst.stats.last_ping = datetime.now(tz=context.bot.defaults.tzinfo)

        try:
            slots_info = s21_client.get_slots_info(task_id, cfg.from_dt, cfg.to_dt, logger)
            # TODO: move check to Start/EditFlow?
            needed = slots_info.review_info.needed
            if cfg.required_reviews > needed:
                await self._messenger.send(
                    context,
                    f"📉 бот #{cfg.bot_id} ({cfg.project_name}): выставленное количество проверок ({cfg.required_reviews}) больше необходимого ({needed})",
                )
                cfg.required_reviews = needed
            already_booked = slots_info.review_info.booked
            currently_booked = inst.stats.currently_booked
            inst.stats.currently_booked = already_booked
            missing = cfg.required_reviews - already_booked
            # TODO: move currently_booked into a separate Project entity (store in DB?),
            #  to avoid multiple bots for 1 project sending the same message
            if already_booked < currently_booked:
                # TODO: output which review was cancelled
                await self._messenger.send(
                    context,
                    f"⚠️ бот #{cfg.bot_id} ({cfg.project_name}): отменена проверка\n"
                    f"нужно ещё: {missing}/{cfg.required_reviews}",
                )

            if missing > 0:
                picked = self._pick_candidate_start(slots_info.time_slots)
                if picked:
                    start_time, staff_slot = picked
                    # TODO: give the option to (try to) book the found slot
                    # TODO: delete the message after booking
                    if cfg.mode == Mode.ONLY_FIND:
                        inst.stats.attempts_success += 1
                        await self._messenger.send(
                            context,
                            f"🔔 бот #{cfg.bot_id} ({cfg.project_name}) остановлен: найден слот\n"
                            f"начало: {dt_to_pretty(start_time)}\n",
                            # f"нужно ещё: {missing}/{cfg.required_reviews}",
                        )
                        # TODO: delete bot?
                        self.stop_bot(cfg.bot_id, context)
                        return

                    s21_client.book(
                        answer_id=answer_id,
                        start_time_dt=start_time,
                        staff_slot=staff_slot,
                        logger=logger,
                    )
                    currently_booked = already_booked + 1
                    inst.stats.currently_booked = currently_booked
                    inst.stats.attempts_success += 1
                    await self._messenger.send(
                        context,
                        f"✅ бот #{cfg.bot_id} ({cfg.project_name}): записался\n"
                        f"начало: {dt_to_pretty(start_time)}\n"
                        f"проверок: {currently_booked}/{cfg.required_reviews}",
                    )
        except Exception as e:
            inst.stats.attempts_failed += 1
            logger.exception("Failed attempt %d running bot %s", inst.stats.attempts_failed, cfg.bot_id)
            if inst.stats.attempts_failed % self._bot_config.max_retries == 0:
                raise BotRuntimeError(f"бот #{cfg.bot_id} ({cfg.project_name}): ошибка поиска") from e

    # # TODO: add exception propagation in task.add_done_callback
    # async def run_bot_loop(self, inst: BotInstance, context: CustomContext) -> None:
    #     cfg = inst.cfg
    #     logger = inst.logger()
    #     s21_client = self._s21_client_factory(config=self._s21_config)
    #
    #     try:
    #         task_id, answer_id = s21_client.get_task_and_answer(cfg.project_id, logger)
    #     except Exception as e:
    #         inst.state = Lifecycle.STOPPED
    #         raise BotRuntimeError(
    #             f"бот #{cfg.bot_id}: не удалось получить необходимую информацию для начала поиска"
    #         ) from e
    #         # await self._messenger.send(f"❌ бот #{cfg.bot_id}: не смог получить task/answer: {e}")
    #         # await app.bot.send_message(
    #         #     chat_id, f"❌ bot #{cfg.bot_id}: не смог получить task/answer: {e}", reply_markup=MAIN_MENU_KB
    #         # )
    #         return
    #
    #     while True:
    #         if inst.state != Lifecycle.RUNNING:
    #             return
    #
    #         if datetime.now(tz=self._bot_config.timezone) >= cfg.to_dt:
    #             self.delete_bot(inst.cfg.bot_id)
    #             logger.info("Removing the current bot search due to expiration")
    #             await self._messenger.send(context, f"⌛️ бот #{cfg.bot_id}: остановлен, окно поиска истекло")
    #             # await app.bot.send_message(
    #             #     chat_id, f"⌛️ bot #{cfg.bot_id}: окно поиска истекло.", reply_markup=MAIN_MENU_KB
    #             # )
    #             return
    #
    #         inst.stats.attempts_total += 1
    #         inst.stats.last_ping = datetime.now(tz=self._bot_config.timezone)
    #
    #         try:
    #             slots, already_booked = s21_client.get_timeslots(task_id, cfg.from_dt, cfg.to_dt, inst.logger())
    #             currently_booked = inst.stats.currently_booked
    #             inst.stats.currently_booked = already_booked
    #             missing = cfg.required_reviews - already_booked
    #             # TODO: move currently_booked into a separate Project entity (store in DB?),
    #             #  to avoid multiple bots for 1 project sending the same message
    #             if already_booked < currently_booked:
    #                 # TODO: output which review was cancelled
    #                 await self._messenger.send(
    #                     context,
    #                     f"⚠️ бот #{cfg.bot_id} отменена проверка\n"
    #                     f"проект: {cfg.project_name}\n"
    #                     f"нужно ещё: {missing}/{cfg.required_reviews}",
    #                 )
    #
    #             if missing > 0:
    #                 picked = self._pick_candidate_start(slots)
    #                 if picked:
    #                     start_time, staff_slot = picked
    #                     # TODO: give the option to (try to) book the found slot
    #                     # TODO: delete the message after booking
    #                     if cfg.mode == Mode.ONLY_FIND:
    #                         inst.stats.attempts_success += 1
    #                         await self._messenger.send(
    #                             context,
    #                             f"🔔 бот #{cfg.bot_id}: найден слот\n"
    #                             f"проект: {cfg.project_name}\nначало: {start_time}\n",
    #                             # f"нужно ещё: {missing}/{cfg.required_reviews}",
    #                         )
    #                         # TODO: delete bot?
    #                         self.stop_bot(inst.cfg.bot_id)
    #                         return
    #
    #                     s21_client.book(
    #                         answer_id=answer_id,
    #                         start_time_iso_z=start_time,
    #                         staff_slot=staff_slot,
    #                         logger=logger,
    #                     )
    #                     currently_booked = already_booked + 1
    #                     inst.stats.currently_booked = currently_booked
    #                     inst.stats.attempts_success += 1
    #                     await self._messenger.send(
    #                         context,
    #                         f"✅ бот #{cfg.bot_id}: записался\n"
    #                         f"проект: {cfg.project_name}\nначало: {start_time}\n"
    #                         f"проверок: {currently_booked}/{cfg.required_reviews}",
    #                     )
    #
    #         except asyncio.CancelledError:
    #             inst.state = Lifecycle.STOPPED
    #             await self._messenger.send(context, f"⛔ бот #{cfg.bot_id}: остановлен")
    #             return
    #         except Exception as e:
    #             inst.stats.attempts_failed += 1
    #             logger.exception("Failed attempt %d running bot %s", inst.stats.attempts_failed, cfg.bot_id)
    #             if inst.stats.attempts_failed % self._bot_config.max_retries == 0:
    #                 raise BotRuntimeError(f"бот #{cfg.bot_id}: ошибка поиска") from e
    #
    #         sleep_sec = cfg.interval_sec + random.randint(0, self._bot_config.poll_jitter_sec)
    #         await asyncio.sleep(sleep_sec)

    def _pick_candidate_start(self, timeslots: list[TimeSlot]) -> tuple[datetime, bool] | None:
        candidates: list[tuple[datetime, bool]] = []
        for slot in timeslots:
            for time in slot.valid_start_times:
                candidates.append((time, slot.staff_slot))
        if not candidates:
            return None
        candidates.sort(key=lambda candidate: candidate[0])
        return candidates[0]
