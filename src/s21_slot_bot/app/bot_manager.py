import asyncio
import secrets
from datetime import datetime

from telegram.ext import Application

from s21_slot_bot.app.config import BotConfig
from s21_slot_bot.app.menu_markup import MAIN_MENU_KB
from s21_slot_bot.app.models import BotInstance, Lifecycle
from s21_slot_bot.client.config import S21ClientConfig
from s21_slot_bot.client.s21_client import School21Client, pick_candidate_start


class BotManager:
    def __init__(
        self,
        bot_config: BotConfig,
        s21_config: S21ClientConfig,
        s21_client_factory: type[School21Client] = School21Client,
    ) -> None:
        self.bot_config = bot_config
        self._s21_config = s21_config
        self._s21_client_factory = s21_client_factory
        self._bots: dict[str, BotInstance] = {}

    def get_bot(self, bot_id: str | None) -> BotInstance | None:
        return self._bots.get(bot_id)

    def list_all(self, chat_id: int) -> list[BotInstance]:
        arr = [b for b in self._bots.values() if b.cfg.chat_id == chat_id]

        def key(x: BotInstance) -> tuple[int, str]:
            pr = {Lifecycle.RUNNING: 0, Lifecycle.STOPPED: 1}.get(x.state, 9)
            return pr, x.cfg.bot_id

        return sorted(arr, key=key)

    def running(self, chat_id: int) -> list[BotInstance]:
        return [b for b in self._bots.values() if b.cfg.chat_id == chat_id and b.state == Lifecycle.RUNNING]

    def running_count(self, chat_id: int) -> int:
        return len(self.running(chat_id))

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

    # TODO: move chat_id to env
    def stop_all(self, chat_id: int) -> None:
        for inst in list(self.list_all(chat_id)):
            if inst.state == Lifecycle.RUNNING:
                self.stop_bot(inst.cfg.bot_id)

    async def start_bot(self, inst: BotInstance, app: Application) -> None:
        inst.state = Lifecycle.RUNNING
        inst.task = asyncio.create_task(self.run_bot_loop(inst, app))
        self._bots[inst.cfg.bot_id] = inst

    async def run_bot_loop(self, inst: BotInstance, app: Application) -> None:
        chat_id = inst.cfg.chat_id
        cfg = inst.cfg
        interval = cfg.interval_sec
        logger = inst.logger()
        s21_client = self._s21_client_factory(config=self._s21_config)

        try:
            task_id, answer_id = s21_client.get_task_and_answer(cfg.project_id, logger)
        except Exception as e:
            inst.state = Lifecycle.STOPPED
            await app.bot.send_message(
                chat_id, f"❌ bot #{cfg.bot_id}: не смог получить task/answer: {e}", reply_markup=MAIN_MENU_KB
            )
            return

        while True:
            if inst.state != Lifecycle.RUNNING:
                return

            if datetime.now(tz=self.bot_config.timezone) >= cfg.to_dt:
                self.delete_bot(inst.cfg.bot_id)
                logger.info("Removing the current bot search due to expiration")
                await app.bot.send_message(
                    chat_id, f"⌛️ bot #{cfg.bot_id}: окно поиска истекло.", reply_markup=MAIN_MENU_KB
                )
                return

            inst.stats.attempts_total += 1
            inst.stats.last_ping = datetime.now(tz=self.bot_config.timezone)

            try:
                slots, already_booked = s21_client.get_timeslots(task_id, cfg.from_dt, cfg.to_dt, inst.logger())
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
                            self.delete_bot(inst.cfg.bot_id)
                            inst.stats.attempts_success += 1
                            await app.bot.send_message(
                                chat_id,
                                f"🔔 bot #{cfg.bot_id} (dry-run): найден слот\n"
                                f"проект: {cfg.project_name}\nstart: {start_time}\n"
                                f"нужно ещё: {missing}/{cfg.required_reviews}",
                                reply_markup=MAIN_MENU_KB,
                            )
                            return

                        # booking mode: book one slot and continue until enough
                        s21_client.book(
                            answer_id=answer_id,
                            start_time_iso_z=start_time,
                            staff_slot=staff_slot,
                            logger=inst.logger(),
                        )
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
                return
            except Exception:
                logger.exception("Failed to run boot loop")
                inst.stats.attempts_failed += 1

            sleep_s = interval + (secrets.randbelow(self.bot_config.jitter_sec + 1))
            await asyncio.sleep(sleep_s)
