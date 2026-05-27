import asyncio
import random
from asyncio import Task
from datetime import datetime
from typing import Any

from s21_slot_bot.app.config import BotConfig
from s21_slot_bot.app.messenger import Messenger
from s21_slot_bot.app.models import BotInstance, CustomContext, Lifecycle, Mode
from s21_slot_bot.client.config import S21ClientConfig
from s21_slot_bot.client.s21_client import School21Client
from s21_slot_bot.common.exceptions import BotNotFoundError, BotRuntimeError, TooManyBotsError


class BotManager:
    def __init__(
        self,
        bot_config: BotConfig,
        messenger: Messenger,
        s21_config: S21ClientConfig,
        s21_client_factory: type[School21Client] = School21Client,
    ) -> None:
        self.bot_config = bot_config
        self._messenger = messenger
        self._s21_config = s21_config
        self._s21_client_factory = s21_client_factory
        self._bots: dict[str, BotInstance] = {}

    def check_bot_limits(self) -> None:
        if len(self.running()) >= self.bot_config.max_bots:
            raise TooManyBotsError(f"Максимальное количество ботов превышено ({self.bot_config.max_bots})")

    def get_bot(self, bot_id: str | None) -> BotInstance:
        bot = self._bots.get(bot_id)
        if not bot:
            raise BotNotFoundError(f"бот #{bot_id} не найден")
        return bot

    def list_all(self) -> list[BotInstance]:
        arr = [b for b in self._bots.values()]

        def key(x: BotInstance) -> tuple[int, int, str]:
            pr = {Lifecycle.RUNNING: 0, Lifecycle.STOPPED: 1}.get(x.state, 9)
            return pr, x.cfg.project_id, x.cfg.bot_id

        return sorted(arr, key=key)

    def running(self) -> list[BotInstance]:
        return [b for b in self.list_all() if b.state == Lifecycle.RUNNING]

    def stop_bot(self, bot_id: str) -> bool:
        inst = self._bots.get(bot_id)
        if not inst:
            return False
        if inst.task and not inst.task.done():
            inst.task.cancel()
        inst.state = Lifecycle.STOPPED
        return True

    def delete_bot(self, bot_id: str) -> bool:
        inst = self._bots.pop(bot_id, None)
        return bool(inst)

    def stop_all(self) -> None:
        for inst in self.running():
            self.stop_bot(inst.cfg.bot_id)

    def start_bot(self, inst: BotInstance, context: CustomContext) -> None:
        inst.state = Lifecycle.RUNNING
        inst.task = context.application.create_task(self.run_bot_loop(inst, context))
        self._bots[inst.cfg.bot_id] = inst

    # TODO: add exception propagation in task.add_done_callback
    async def run_bot_loop(self, inst: BotInstance, context: CustomContext) -> None:
        cfg = inst.cfg
        logger = inst.logger()
        s21_client = self._s21_client_factory(config=self._s21_config)

        try:
            task_id, answer_id = s21_client.get_task_and_answer(cfg.project_id, logger)
        except Exception as e:
            inst.state = Lifecycle.STOPPED
            raise BotRuntimeError(
                f"бот #{cfg.bot_id}: не удалось получить необходимую информацию для начала поиска"
            ) from e
            # await self._messenger.send(f"❌ бот #{cfg.bot_id}: не смог получить task/answer: {e}")
            # await app.bot.send_message(
            #     chat_id, f"❌ bot #{cfg.bot_id}: не смог получить task/answer: {e}", reply_markup=MAIN_MENU_KB
            # )
            return

        while True:
            if inst.state != Lifecycle.RUNNING:
                return

            if datetime.now(tz=self.bot_config.timezone) >= cfg.to_dt:
                self.delete_bot(inst.cfg.bot_id)
                logger.info("Removing the current bot search due to expiration")
                await self._messenger.send(context, f"⌛️ бот #{cfg.bot_id}: остановлен, окно поиска истекло")
                # await app.bot.send_message(
                #     chat_id, f"⌛️ bot #{cfg.bot_id}: окно поиска истекло.", reply_markup=MAIN_MENU_KB
                # )
                return

            inst.stats.attempts_total += 1
            inst.stats.last_ping = datetime.now(tz=self.bot_config.timezone)

            try:
                slots, already_booked = s21_client.get_timeslots(task_id, cfg.from_dt, cfg.to_dt, inst.logger())
                currently_booked = inst.stats.currently_booked
                inst.stats.currently_booked = already_booked
                missing = cfg.required_reviews - already_booked
                # TODO: move currently_booked into a separate Project entity (store in DB?),
                #  to avoid multiple bots for 1 project sending the same message
                if already_booked < currently_booked:
                    # TODO: output which review was cancelled
                    await self._messenger.send(
                        context,
                        f"⚠️ бот #{cfg.bot_id} отменена проверка\n"
                        f"проект: {cfg.project_name}\n"
                        f"нужно ещё: {missing}/{cfg.required_reviews}",
                    )

                if missing > 0:
                    picked = self._pick_candidate_start(slots)
                    if picked:
                        start_time, staff_slot = picked
                        # TODO: give the option to (try to) book the found slot
                        # TODO: delete the message after booking
                        if cfg.mode == Mode.ONLY_FIND:
                            inst.stats.attempts_success += 1
                            await self._messenger.send(
                                context,
                                f"🔔 бот #{cfg.bot_id}: найден слот\n"
                                f"проект: {cfg.project_name}\nначало: {start_time}\n",
                                # f"нужно ещё: {missing}/{cfg.required_reviews}",
                            )
                            # TODO: delete bot?
                            self.stop_bot(inst.cfg.bot_id)
                            return

                        s21_client.book(
                            answer_id=answer_id,
                            start_time_iso_z=start_time,
                            staff_slot=staff_slot,
                            logger=logger,
                        )
                        currently_booked = already_booked + 1
                        inst.stats.currently_booked = currently_booked
                        inst.stats.attempts_success += 1
                        await self._messenger.send(
                            context,
                            f"✅ бот #{cfg.bot_id}: записался\n"
                            f"проект: {cfg.project_name}\nначало: {start_time}\n"
                            f"проверок: {currently_booked}/{cfg.required_reviews}",
                        )

            except asyncio.CancelledError:
                inst.state = Lifecycle.STOPPED
                await self._messenger.send(context, f"⛔ бот #{cfg.bot_id}: остановлен")
                return
            except Exception as e:
                inst.stats.attempts_failed += 1
                logger.exception("Failed attempt %d running bot %s", inst.stats.attempts_failed, cfg.bot_id)
                if inst.stats.attempts_failed % self.bot_config.max_retries == 0:
                    inst.state = Lifecycle.STOPPED
                    raise BotRuntimeError(f"бот #{cfg.bot_id}: ошибка поиска") from e

            sleep_sec = cfg.interval_sec + random.randint(0, self.bot_config.poll_jitter_sec)
            await asyncio.sleep(sleep_sec)

    def _pick_candidate_start(self, timeslots: list[dict[str, Any]]) -> tuple[str, bool] | None:
        candidates: list[tuple[str, bool]] = []
        for slot in timeslots:
            staff = bool(slot.get("staffSlot", False))
            for time in slot.get("validStartTimes") or []:
                candidates.append((time, staff))
        if not candidates:
            return None
        candidates.sort(key=lambda candidate: candidate[0])
        return candidates[0]
