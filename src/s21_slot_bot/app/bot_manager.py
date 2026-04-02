import asyncio
import logging
import secrets
from datetime import datetime

from telegram.ext import Application

from s21_slot_bot.app.config import BotConfig
from s21_slot_bot.app.menu_markup import MAIN_MENU_KB
from s21_slot_bot.app.models import BotInstance, Lifecycle
from s21_slot_bot.client.s21_client import School21Client, pick_candidate_start

# TODO: add wrapper in BotInstance
_logger = logging.getLogger(__name__)


class BotManager:
    def __init__(self, config: BotConfig, s21_client: School21Client) -> None:
        self.config = config
        self._s21_client = s21_client
        self.bots: dict[str, BotInstance] = {}
        self.queues: dict[int, list[str]] = {}  # chat_id -> bot_ids

    def list_all(self, chat_id: int) -> list[BotInstance]:
        arr = [b for b in self.bots.values() if b.cfg.chat_id == chat_id]

        def key(x: BotInstance) -> tuple[int, str]:
            pr = {Lifecycle.RUNNING: 0, Lifecycle.QUEUED: 1, Lifecycle.DONE: 2, Lifecycle.STOPPED: 3}.get(x.state, 9)
            return (pr, x.cfg.bot_id)

        return sorted(arr, key=key)

    def running(self, chat_id: int) -> list[BotInstance]:
        return [b for b in self.bots.values() if b.cfg.chat_id == chat_id and b.state == Lifecycle.RUNNING]

    def queued(self, chat_id: int) -> list[BotInstance]:
        return [b for b in self.bots.values() if b.cfg.chat_id == chat_id and b.state == Lifecycle.QUEUED]

    def running_count(self, chat_id: int) -> int:
        return len(self.running(chat_id))

    def active_count(self, chat_id: int) -> int:
        return len(
            [
                b
                for b in self.bots.values()
                if b.cfg.chat_id == chat_id and b.state in (Lifecycle.RUNNING, Lifecycle.QUEUED)
            ]
        )

    def add_bot(self, inst: BotInstance) -> None:
        self.bots[inst.cfg.bot_id] = inst
        self.queues.setdefault(inst.cfg.chat_id, []).append(inst.cfg.bot_id)

    def stop_bot(self, bot_id: str) -> bool:
        inst = self.bots.get(bot_id)
        if not inst:
            return False
        if inst.task and not inst.task.done():
            inst.task.cancel()
        inst.state = Lifecycle.STOPPED
        q = self.queues.get(inst.cfg.chat_id, [])
        self.queues[inst.cfg.chat_id] = [x for x in q if x != bot_id]
        return True

    # TODO: move chat_id to env
    def stop_all(self, chat_id: int) -> None:
        for inst in list(self.list_all(chat_id)):
            if inst.state in (Lifecycle.RUNNING, Lifecycle.QUEUED):
                self.stop_bot(inst.cfg.bot_id)

    # TODO: check max bots on running
    async def try_start_next(self, chat_id: int, app: Application) -> None:
        q = self.queues.setdefault(chat_id, [])
        while self.running_count(chat_id) < self.config.max_bots and q:
            bot_id = q.pop(0)
            inst = self.bots.get(bot_id)
            if not inst or inst.state != Lifecycle.QUEUED:
                continue
            inst.state = Lifecycle.RUNNING
            inst.task = asyncio.create_task(self.run_bot_loop(inst, app))

    async def on_finished(self, inst: BotInstance, app: Application) -> None:
        await self.try_start_next(inst.cfg.chat_id, app)

    async def run_bot_loop(self, inst: BotInstance, app: Application) -> None:
        chat_id = inst.cfg.chat_id
        cfg = inst.cfg
        interval = cfg.interval_sec

        try:
            task_id, answer_id = self._s21_client.get_task_and_answer(cfg.project_id)
        except Exception as e:
            inst.state = Lifecycle.STOPPED
            await app.bot.send_message(
                chat_id, f"❌ bot #{cfg.bot_id}: не смог получить task/answer: {e}", reply_markup=MAIN_MENU_KB
            )
            await self.on_finished(inst, app)
            return

        while True:
            if inst.state != Lifecycle.RUNNING:
                return

            if datetime.now(tz=self.config.timezone) >= cfg.to_dt:
                inst.state = Lifecycle.DONE
                await app.bot.send_message(
                    chat_id, f"⌛️ bot #{cfg.bot_id}: окно поиска истекло.", reply_markup=MAIN_MENU_KB
                )
                await self.on_finished(inst, app)
                return

            inst.stats.attempts_total += 1
            inst.stats.last_ping = datetime.now(tz=self.config.timezone)

            try:
                slots, already_booked = self._s21_client.get_timeslots(task_id, cfg.from_dt, cfg.to_dt)
                currently_booked = inst.stats.currently_booked
                inst.stats.currently_booked = already_booked
                missing = cfg.required_reviews - int(already_booked)
                # TODO: move currently_booked into a separate Project entity (store in DB?),
                #  to avoid multiple bots for 1 project sending the same message
                if already_booked < currently_booked:
                    # TODO: output which review was cancelled
                    await app.bot.send_message(
                        chat_id,
                        f"⚠️ bot #{cfg.bot_id} отменена проверка\n"
                        f"проект: {cfg.project_name}\n"
                        f"нужно ещё: {missing}/{cfg.required_reviews}",
                        reply_markup=MAIN_MENU_KB,
                    )

                if missing > 0:
                    picked = pick_candidate_start(slots)
                    if picked:
                        start_time, staff_slot = picked

                        if cfg.dry_run:
                            inst.state = Lifecycle.DONE
                            inst.stats.attempts_success += 1
                            await app.bot.send_message(
                                chat_id,
                                f"🔔 bot #{cfg.bot_id} (dry-run): найден слот\n"
                                f"проект: {cfg.project_name}\nstart: {start_time}\n"
                                f"нужно ещё: {missing}/{cfg.required_reviews}",
                                reply_markup=MAIN_MENU_KB,
                            )
                            await self.on_finished(inst, app)
                            return

                        # booking mode: book one slot and continue until enough
                        booking_id = self._s21_client.book(
                            answer_id=answer_id, start_time_iso_z=start_time, staff_slot=staff_slot
                        )
                        # TODO: add logging for booking_id?
                        currently_booked = already_booked + 1
                        inst.stats.currently_booked = currently_booked
                        inst.stats.attempts_success += 1
                        await app.bot.send_message(
                            chat_id,
                            f"✅ bot #{cfg.bot_id}: записался\n"
                            f"проект: {cfg.project_name}\nstart: {start_time}\n"
                            f"записано: {currently_booked}/{cfg.required_reviews}",
                            reply_markup=MAIN_MENU_KB,
                        )

            except asyncio.CancelledError:
                inst.state = Lifecycle.STOPPED
                await app.bot.send_message(chat_id, f"⛔ bot #{cfg.bot_id}: остановлен.", reply_markup=MAIN_MENU_KB)
                await self.on_finished(inst, app)
                return
            except Exception:
                _logger.exception("Failed to run boot loop")
                inst.stats.attempts_failed += 1

            sleep_s = interval + (secrets.randbelow(self.config.jitter_sec + 1))
            await asyncio.sleep(sleep_s)
