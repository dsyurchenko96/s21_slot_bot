import asyncio
import os
import re
import secrets
from dataclasses import dataclass, field
from datetime import datetime, timedelta, UTC
from enum import Enum
from typing import Dict, List, Optional, Set, Tuple

from telegram import InlineKeyboardButton, InlineKeyboardMarkup, ReplyKeyboardMarkup, Update
from telegram.ext import (
    Application,
    ContextTypes,
)

from s21_slot_bot.client.s21_client import School21Client, School21Error, pick_candidate_start

MAIN_MENU_KB = ReplyKeyboardMarkup(
    [
        ["▶️ Начать", "⛔ Остановить"],
        ["✏️ Изменить", "📌 Статус"],
        ["⚙️ Настройки"],
    ],
    resize_keyboard=True,
    is_persistent=True,
)

DEFAULT_MAX_BOTS = int(os.getenv("MAX_BOTS_DEFAULT", "2"))
DEFAULT_GLOBAL_INTERVAL = int(os.getenv("POLL_INTERVAL_SEC", "60"))
DEFAULT_JITTER_SEC = int(os.getenv("POLL_JITTER_SEC", "8"))

MIN_REQUIRED_REVIEWS = 1
MAX_REQUIRED_REVIEWS = 3


class Lifecycle(str, Enum):
    queued = "queued"
    running = "running"
    stopped = "stopped"
    done = "done"


class Screen(str, Enum):
    menu = "menu"

    start_pick_project = "start_pick_project"
    start_pick_num = "start_pick_num"
    start_pick_from = "start_pick_from"
    start_wait_from = "start_wait_from"
    start_pick_to = "start_pick_to"
    start_wait_to = "start_wait_to"
    start_pick_mode = "start_pick_mode"
    start_confirm = "start_confirm"

    stop_menu = "stop_menu"
    stop_multi = "stop_multi"

    edit_pick = "edit_pick"
    edit_menu = "edit_menu"
    edit_wait_from = "edit_wait_from"
    edit_wait_to = "edit_wait_to"
    edit_wait_interval = "edit_wait_interval"

    settings_menu = "settings_menu"
    settings_wait_interval = "settings_wait_interval"


@dataclass
class Stats:
    last_ping: Optional[datetime] = None
    attempts_total: int = 0
    attempts_success: int = 0
    attempts_failed: int = 0
    currently_booked: int = 0


@dataclass
class BotConfig:
    bot_id: str
    chat_id: int
    project_id: str
    project_name: str
    required_reviews: int
    from_iso_z: str
    to_iso_z: str
    interval_sec: int
    dry_run: bool


@dataclass
class BotInstance:
    cfg: BotConfig
    state: Lifecycle = Lifecycle.queued
    stats: Stats = field(default_factory=Stats)
    task: Optional[asyncio.Task] = None


@dataclass
class Settings:
    max_bots: int = DEFAULT_MAX_BOTS
    interval_sec: int = DEFAULT_GLOBAL_INTERVAL


class BotManager:
    def __init__(self) -> None:
        self.settings = Settings()
        self.bots: Dict[str, BotInstance] = {}
        self.queues: Dict[int, List[str]] = {}  # chat_id -> bot_ids

    def list_all(self, chat_id: int) -> List[BotInstance]:
        arr = [b for b in self.bots.values() if b.cfg.chat_id == chat_id]

        def key(x: BotInstance) -> Tuple[int, str]:
            pr = {Lifecycle.running: 0, Lifecycle.queued: 1, Lifecycle.done: 2, Lifecycle.stopped: 3}.get(x.state, 9)
            return (pr, x.cfg.bot_id)

        return sorted(arr, key=key)

    def running(self, chat_id: int) -> List[BotInstance]:
        return [b for b in self.bots.values() if b.cfg.chat_id == chat_id and b.state == Lifecycle.running]

    def queued(self, chat_id: int) -> List[BotInstance]:
        return [b for b in self.bots.values() if b.cfg.chat_id == chat_id and b.state == Lifecycle.queued]

    def running_count(self, chat_id: int) -> int:
        return len(self.running(chat_id))

    def active_count(self, chat_id: int) -> int:
        return len(
            [
                b
                for b in self.bots.values()
                if b.cfg.chat_id == chat_id and b.state in (Lifecycle.running, Lifecycle.queued)
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
        inst.state = Lifecycle.stopped
        q = self.queues.get(inst.cfg.chat_id, [])
        self.queues[inst.cfg.chat_id] = [x for x in q if x != bot_id]
        return True

    def stop_all(self, chat_id: int) -> None:
        for inst in list(self.list_all(chat_id)):
            if inst.state in (Lifecycle.running, Lifecycle.queued):
                self.stop_bot(inst.cfg.bot_id)

    async def try_start_next(self, chat_id: int, app: Application) -> None:
        q = self.queues.setdefault(chat_id, [])
        while self.running_count(chat_id) < self.settings.max_bots and q:
            bot_id = q.pop(0)
            inst = self.bots.get(bot_id)
            if not inst or inst.state != Lifecycle.queued:
                continue
            inst.state = Lifecycle.running
            inst.task = asyncio.create_task(run_bot_loop(inst, app, self))

    async def on_finished(self, inst: BotInstance, app: Application) -> None:
        await self.try_start_next(inst.cfg.chat_id, app)


MANAGER = BotManager()


def _get_client() -> School21Client:
    u = os.getenv("S21_USERNAME", "").strip()
    p = os.getenv("S21_PASSWORD", "").strip()
    if not u or not p:
        raise RuntimeError("S21_USERNAME/S21_PASSWORD не заданы")
    return School21Client(username=u, password=p)


def _screen_set(ctx: ContextTypes.DEFAULT_TYPE, scr: Screen) -> None:
    ctx.chat_data["screen"] = scr.value


def _screen_get(ctx: ContextTypes.DEFAULT_TYPE) -> Screen:
    v = ctx.chat_data.get("screen", Screen.menu.value)
    try:
        return Screen(v)
    except Exception:
        return Screen.menu


def _isoz_now() -> str:
    return datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%S.000Z")


def _isoz_plus(hours: int = 0, minutes: int = 0) -> str:
    dt = datetime.now(UTC) + timedelta(hours=hours, minutes=minutes)
    return dt.strftime("%Y-%m-%dT%H:%M:%S.000Z")


def _isoz_to_dt(s: str) -> datetime:
    return datetime.strptime(s, "%Y-%m-%dT%H:%M:%S.000Z").replace(tzinfo=UTC)


def _parse_dt_to_utc_z(text: str) -> str:
    s = (text or "").strip()
    if re.match(r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(\.\d{3})?Z$", s):
        return s if "." in s else s.replace("Z", ".000Z")

    m = re.match(r"^(\d{4}-\d{2}-\d{2})\s+(\d{2}:\d{2})$", s)
    if not m:
        raise ValueError("нужен формат ISO Z или 'YYYY-MM-DD HH:MM'")

    dt_local = datetime.strptime(f"{m.group(1)} {m.group(2)}", "%Y-%m-%d %H:%M")

    off = os.getenv("BOT_TZ_OFFSET", "+03:00")
    sign = 1 if off[0] == "+" else -1
    hh = int(off[1:3])
    mm = int(off[4:6])
    delta = sign * (hh * 60 + mm)

    utc_ts = dt_local.timestamp() - delta * 60
    dt_utc = datetime.fromtimestamp(utc_ts, UTC)
    return dt_utc.strftime("%Y-%m-%dT%H:%M:%S.000Z")


def _bot_line(inst: BotInstance) -> str:
    c = inst.cfg
    lp = inst.stats.last_ping.strftime("%Y-%m-%d %H:%M:%S") if inst.stats.last_ping else "—"
    return (
        f"#{c.bot_id} [{inst.state}] {c.project_name} "
        f"({c.required_reviews} reviews, {'dry' if c.dry_run else 'book'})\n"
        f"utc: {c.from_iso_z} → {c.to_iso_z}\n"
        f"last ping: {lp}, attempts: {inst.stats.attempts_total} "
        f"(ok {inst.stats.attempts_success} / fail {inst.stats.attempts_failed} / booked {inst.stats.currently_booked})\n"
    )


async def run_bot_loop(inst: BotInstance, app: Application, manager: BotManager) -> None:
    chat_id = inst.cfg.chat_id
    cfg = inst.cfg
    interval = max(10, int(cfg.interval_sec))
    jitter = max(0, int(DEFAULT_JITTER_SEC))

    client = _get_client()
    client.login()

    try:
        task_id, answer_id = client.get_task_and_answer(cfg.project_id)
    except Exception as e:
        inst.state = Lifecycle.stopped
        await app.bot.send_message(
            chat_id, f"❌ bot #{cfg.bot_id}: не смог получить task/answer: {e}", reply_markup=MAIN_MENU_KB
        )
        await manager.on_finished(inst, app)
        return

    while True:
        if inst.state != Lifecycle.running:
            return

        if datetime.now(UTC) >= _isoz_to_dt(cfg.to_iso_z):
            inst.state = Lifecycle.done
            await app.bot.send_message(
                chat_id, f"⌛️ bot #{cfg.bot_id}: окно поиска истекло.", reply_markup=MAIN_MENU_KB
            )
            await manager.on_finished(inst, app)
            return

        inst.stats.attempts_total += 1
        inst.stats.last_ping = datetime.now(UTC)

        try:
            slots, already_booked = client.get_timeslots(task_id, cfg.from_iso_z, cfg.to_iso_z)
            currently_booked = inst.stats.currently_booked
            inst.stats.currently_booked = already_booked
            missing = cfg.required_reviews - int(already_booked)
            # TODO: move currently_booked into a separate Project entity (store in DB?),
            #  to avoid multiple bots for 1 project sending the same message
            if already_booked < currently_booked:
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
                        inst.state = Lifecycle.done
                        inst.stats.attempts_success += 1
                        await app.bot.send_message(
                            chat_id,
                            f"🔔 bot #{cfg.bot_id} (dry-run): найден слот\n"
                            f"проект: {cfg.project_name}\nstart: {start_time}\n"
                            f"нужно ещё: {missing}/{cfg.required_reviews}",
                            reply_markup=MAIN_MENU_KB,
                        )
                        await manager.on_finished(inst, app)
                        return

                    # booking mode: book one slot and continue until enough
                    booking_id = client.book(answer_id=answer_id, start_time_iso_z=start_time, staff_slot=staff_slot)
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
            inst.state = Lifecycle.stopped
            await app.bot.send_message(chat_id, f"⛔ bot #{cfg.bot_id}: остановлен.", reply_markup=MAIN_MENU_KB)
            await manager.on_finished(inst, app)
            return
        except School21Error:
            inst.stats.attempts_failed += 1
        except Exception:
            inst.stats.attempts_failed += 1

        sleep_s = interval + (secrets.randbelow(jitter + 1) if jitter else 0)
        await asyncio.sleep(sleep_s)


async def cmd_start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    _screen_set(context, Screen.menu)
    await update.message.reply_text("Slot bot — меню", reply_markup=MAIN_MENU_KB)


# -------------------- menu text handler --------------------
async def on_text(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    txt = (update.message.text or "").strip().lower()
    scr = _screen_get(context)

    if txt == "▶️ начать":
        await start_begin(update, context)
        return
    if txt == "⛔ остановить":
        await stop_menu(update, context)
        return
    if txt == "✏️ изменить":
        await edit_pick(update, context)
        return
    if txt == "📌 статус":
        await status_show(update, context)
        return
    if txt == "⚙️ настройки":
        await settings_menu(update, context)
        return

    # wizard custom input
    if scr == Screen.start_wait_from:
        await start_custom_from(update, context)
        return
    if scr == Screen.start_wait_to:
        await start_custom_to(update, context)
        return
    if scr == Screen.edit_wait_from:
        await edit_custom_from(update, context)
        return
    if scr == Screen.edit_wait_to:
        await edit_custom_to(update, context)
        return
    if scr == Screen.edit_wait_interval:
        await edit_custom_interval(update, context)
        return
    if scr == Screen.settings_wait_interval:
        await settings_custom_interval(update, context)
        return

    await update.message.reply_text("выбери действие в меню 🙂", reply_markup=MAIN_MENU_KB)


# -------------------- callbacks --------------------
async def on_cb(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    q = update.callback_query
    await q.answer()
    data = q.data or ""
    chat_id = q.message.chat_id

    if data == "nav:menu":
        _screen_set(context, Screen.menu)
        await q.message.reply_text("Slot bot — меню", reply_markup=MAIN_MENU_KB)
        return

    # start wizard
    if data.startswith("start:proj:"):
        pid = data.split(":", 2)[2]
        context.chat_data["start_project_id"] = pid
        context.chat_data["start_project_name"] = context.chat_data.get("projects_map", {}).get(pid, pid)
        await start_pick_num(q, context)
        return

    if data.startswith("start:num:"):
        n = int(data.split(":")[2])
        context.chat_data["start_required_reviews"] = n
        await start_pick_from(q, context)
        return

    if data.startswith("start:from:"):
        kind = data.split(":")[2]
        if kind == "now":
            context.chat_data["start_from"] = _isoz_now()
            await start_pick_to(q, context)
            return
        if kind == "p30":
            context.chat_data["start_from"] = _isoz_plus(minutes=30)
            await start_pick_to(q, context)
            return
        if kind == "p60":
            context.chat_data["start_from"] = _isoz_plus(hours=1)
            await start_pick_to(q, context)
            return
        if kind == "custom":
            _screen_set(context, Screen.start_wait_from)
            await q.message.reply_text("введи start (ISO Z или YYYY-MM-DD HH:MM)", reply_markup=MAIN_MENU_KB)
            return

    if data.startswith("start:to:"):
        kind = data.split(":")[2]
        if kind == "p120":
            context.chat_data["start_to"] = _isoz_plus(hours=2)
            await start_pick_mode(q, context)
            return
        if kind == "p240":
            context.chat_data["start_to"] = _isoz_plus(hours=4)
            await start_pick_mode(q, context)
            return
        if kind == "custom":
            _screen_set(context, Screen.start_wait_to)
            await q.message.reply_text("введи end (тот же формат)", reply_markup=MAIN_MENU_KB)
            return

    if data.startswith("start:mode:"):
        mode = data.split(":")[2]
        context.chat_data["start_dry_run"] = mode == "dry"
        await start_confirm(q, context)
        return

    if data.startswith("start:confirm:"):
        action = data.split(":")[2]
        await start_finalize(q, context, action)
        return

    # stop
    if data == "stop:all":
        MANAGER.stop_all(chat_id)
        await q.message.reply_text("⛔ остановил всех", reply_markup=MAIN_MENU_KB)
        return

    if data == "stop:one":
        await stop_pick_one(q, context)
        return

    if data.startswith("stop:bot:"):
        bot_id = data.split(":")[2]
        ok = MANAGER.stop_bot(bot_id)
        await q.message.reply_text("⛔ остановил" if ok else "не нашёл", reply_markup=MAIN_MENU_KB)
        return

    if data == "stop:multi":
        await stop_multi(q, context)
        return

    if data.startswith("stop:toggle:"):
        bot_id = data.split(":")[2]
        sel: Set[str] = context.chat_data.get("stop_selected", set())
        if bot_id in sel:
            sel.remove(bot_id)
        else:
            sel.add(bot_id)
        context.chat_data["stop_selected"] = sel
        await stop_multi(q, context)
        return

    if data == "stop:selected":
        sel: Set[str] = context.chat_data.get("stop_selected", set())
        for bot_id in list(sel):
            MANAGER.stop_bot(bot_id)
        context.chat_data["stop_selected"] = set()
        await q.message.reply_text("⛔ остановил выбранные", reply_markup=MAIN_MENU_KB)
        return

    # edit
    if data.startswith("edit:bot:"):
        bot_id = data.split(":")[2]
        context.chat_data["edit_bot_id"] = bot_id
        await edit_menu(q, context)
        return

    if data == "edit:set_from":
        _screen_set(context, Screen.edit_wait_from)
        await q.message.reply_text("введи новый start", reply_markup=MAIN_MENU_KB)
        return

    if data == "edit:set_to":
        _screen_set(context, Screen.edit_wait_to)
        await q.message.reply_text("введи новый end", reply_markup=MAIN_MENU_KB)
        return

    if data == "edit:set_interval":
        _screen_set(context, Screen.edit_wait_interval)
        await q.message.reply_text("введи новый интервал (сек)", reply_markup=MAIN_MENU_KB)
        return

    if data == "edit:toggle_dry":
        bot_id = context.chat_data.get("edit_bot_id")
        inst = MANAGER.bots.get(bot_id) if bot_id else None
        if inst:
            inst.cfg.dry_run = not inst.cfg.dry_run
        await edit_menu(q, context)
        return

    if data == "edit:restart":
        await edit_restart(q, context)
        return

    # status
    if data == "status:refresh":
        await status_show(q, context)
        return

    # settings
    if data == "settings:max":
        await settings_pick_max(q, context)
        return
    if data.startswith("settings:setmax:"):
        await settings_apply_max(q, context, int(data.split(":")[2]))
        return
    if data == "settings:interval":
        _screen_set(context, Screen.settings_wait_interval)
        await q.message.reply_text("введи новый глобальный интервал (сек)", reply_markup=MAIN_MENU_KB)
        return

    await q.message.reply_text("не понял кнопку — вернись в меню", reply_markup=MAIN_MENU_KB)


# -------------------- start wizard steps --------------------
async def start_begin(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    _screen_set(context, Screen.start_pick_project)
    chat_id = update.message.chat_id

    client = _get_client()
    client.login()

    try:
        projects = client.get_reviewed_projects(client.user_id)
    except Exception as e:
        await update.message.reply_text(f"❌ не смог получить проекты: {e}", reply_markup=MAIN_MENU_KB)
        return

    if not projects:
        await update.message.reply_text("📭 нет активных проектов на проверке", reply_markup=MAIN_MENU_KB)
        return

    context.chat_data["projects_map"] = {project.id: project.name for project in projects}

    if len(projects) == 1:
        project = projects[0]
        context.chat_data["start_project_id"] = project.id
        context.chat_data["start_project_name"] = project.name
        await update.message.reply_text(f"проект выбран: {project.name} (id {project.id})", reply_markup=MAIN_MENU_KB)
        await start_pick_num(update, context)
        return

    kb = [
        [InlineKeyboardButton(f"{project.name} ({project.id})", callback_data=f"start:proj:{project.id}")]
        for project in projects[:20]
    ]
    kb.append([InlineKeyboardButton("⬅️ меню", callback_data="nav:menu")])
    await update.message.reply_text("выбери проект:", reply_markup=InlineKeyboardMarkup(kb))


async def start_pick_num(msg_or_q, context: ContextTypes.DEFAULT_TYPE) -> None:
    _screen_set(context, Screen.start_pick_num)
    kb = InlineKeyboardMarkup(
        [
            [
                InlineKeyboardButton("1", callback_data="start:num:1"),
                InlineKeyboardButton("2", callback_data="start:num:2"),
                InlineKeyboardButton("3", callback_data="start:num:3"),
            ],
            [InlineKeyboardButton("⬅️ меню", callback_data="nav:menu")],
        ]
    )
    if hasattr(msg_or_q, "message"):
        await msg_or_q.message.reply_text("сколько проверок нужно (1–3)?", reply_markup=kb)
    else:
        await msg_or_q.edit_message_text("сколько проверок нужно (1–3)?", reply_markup=kb)


async def start_pick_from(msg_or_q, context: ContextTypes.DEFAULT_TYPE) -> None:
    _screen_set(context, Screen.start_pick_from)
    kb = InlineKeyboardMarkup(
        [
            [
                InlineKeyboardButton("сейчас", callback_data="start:from:now"),
                InlineKeyboardButton("+30м", callback_data="start:from:p30"),
                InlineKeyboardButton("+1ч", callback_data="start:from:p60"),
            ],
            [InlineKeyboardButton("ввести вручную", callback_data="start:from:custom")],
            [InlineKeyboardButton("⬅️ меню", callback_data="nav:menu")],
        ]
    )
    if hasattr(msg_or_q, "message"):
        await msg_or_q.message.reply_text("выбери start (по умолчанию сейчас):", reply_markup=kb)
    else:
        await msg_or_q.edit_message_text("выбери start (по умолчанию сейчас):", reply_markup=kb)


async def start_custom_from(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    try:
        context.chat_data["start_from"] = _parse_dt_to_utc_z(update.message.text)
    except Exception as e:
        await update.message.reply_text(f"❌ {e}\nпопробуй ещё раз", reply_markup=MAIN_MENU_KB)
        return
    await start_pick_to(update, context)


async def start_pick_to(msg_or_q, context: ContextTypes.DEFAULT_TYPE) -> None:
    _screen_set(context, Screen.start_pick_to)
    kb = InlineKeyboardMarkup(
        [
            [
                InlineKeyboardButton("+2ч", callback_data="start:to:p120"),
                InlineKeyboardButton("+4ч", callback_data="start:to:p240"),
            ],
            [InlineKeyboardButton("ввести вручную", callback_data="start:to:custom")],
            [InlineKeyboardButton("⬅️ меню", callback_data="nav:menu")],
        ]
    )
    if hasattr(msg_or_q, "message"):
        await msg_or_q.message.reply_text("выбери end (по умолчанию +2ч):", reply_markup=kb)
    else:
        await msg_or_q.edit_message_text("выбери end (по умолчанию +2ч):", reply_markup=kb)


async def start_custom_to(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    try:
        context.chat_data["start_to"] = _parse_dt_to_utc_z(update.message.text)
    except Exception as e:
        await update.message.reply_text(f"❌ {e}\nпопробуй ещё раз", reply_markup=MAIN_MENU_KB)
        return
    await start_pick_mode(update, context)


async def start_pick_mode(msg_or_q, context: ContextTypes.DEFAULT_TYPE) -> None:
    _screen_set(context, Screen.start_pick_mode)
    kb = InlineKeyboardMarkup(
        [
            [InlineKeyboardButton("🔎 Искать слоты", callback_data="start:mode:dry")],
            [InlineKeyboardButton("✅ Записаться", callback_data="start:mode:book")],
            [InlineKeyboardButton("⬅️ меню", callback_data="nav:menu")],
        ]
    )
    if hasattr(msg_or_q, "message"):
        await msg_or_q.message.reply_text("выбери режим:", reply_markup=kb)
    else:
        await msg_or_q.edit_message_text("выбери режим:", reply_markup=kb)


async def start_confirm(msg_or_q, context: ContextTypes.DEFAULT_TYPE) -> None:
    _screen_set(context, Screen.start_confirm)
    chat_id = msg_or_q.message.chat_id if hasattr(msg_or_q, "message") else msg_or_q.message.chat_id

    pid = context.chat_data["start_project_id"]
    name = context.chat_data["start_project_name"]
    n = int(context.chat_data["start_required_reviews"])
    frm = context.chat_data["start_from"]
    to = context.chat_data["start_to"]
    dry = bool(context.chat_data["start_dry_run"])

    summary = (
        f"проект: {name} (id {pid})\n"
        f"нужно проверок: {n}\n"
        f"utc окно: {frm} → {to}\n"
        f"режим: {'dry-run' if dry else 'booking'}\n\n"
        f"активных: {MANAGER.active_count(chat_id)} / max {MANAGER.settings.max_bots}"
    )
    kb = InlineKeyboardMarkup(
        [
            [InlineKeyboardButton("🚀 старт", callback_data="start:confirm:start")],
            [InlineKeyboardButton("➕ в очередь", callback_data="start:confirm:queue")],
            [InlineKeyboardButton("⬅️ меню", callback_data="nav:menu")],
        ]
    )
    if hasattr(msg_or_q, "message"):
        await msg_or_q.message.reply_text(summary, reply_markup=kb)
    else:
        await msg_or_q.edit_message_text(summary, reply_markup=kb)


async def start_finalize(q, context: ContextTypes.DEFAULT_TYPE, action: str) -> None:
    chat_id = q.message.chat_id

    pid = context.chat_data["start_project_id"]
    name = context.chat_data["start_project_name"]
    n = int(context.chat_data["start_required_reviews"])
    frm = context.chat_data["start_from"]
    to = context.chat_data["start_to"]
    dry = bool(context.chat_data["start_dry_run"])

    bot_id = secrets.token_hex(3)
    cfg = BotConfig(
        bot_id=bot_id,
        chat_id=chat_id,
        project_id=pid,
        project_name=name,
        required_reviews=n,
        from_iso_z=frm,
        to_iso_z=to,
        interval_sec=MANAGER.settings.interval_sec,
        dry_run=dry,
    )
    inst = BotInstance(cfg=cfg)
    MANAGER.add_bot(inst)

    if action == "start" and MANAGER.running_count(chat_id) < MANAGER.settings.max_bots:
        await q.message.reply_text(f"✅ добавил bot #{bot_id} и запускаю", reply_markup=MAIN_MENU_KB)
        await MANAGER.try_start_next(chat_id, context.application)
    elif action == "start":
        await q.message.reply_text(
            f"✅ добавил bot #{bot_id}, лимит достигнут — поставил в очередь", reply_markup=MAIN_MENU_KB
        )
    else:
        await q.message.reply_text(f"➕ добавил bot #{bot_id} в очередь", reply_markup=MAIN_MENU_KB)

    _screen_set(context, Screen.menu)


# -------------------- stop --------------------
async def stop_menu(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    _screen_set(context, Screen.stop_menu)
    chat_id = update.message.chat_id
    if not MANAGER.running(chat_id) and not MANAGER.queued(chat_id):
        await update.message.reply_text("нет активных ботов", reply_markup=MAIN_MENU_KB)
        return
    kb = InlineKeyboardMarkup(
        [
            [InlineKeyboardButton("🛑 остановить всех", callback_data="stop:all")],
            [InlineKeyboardButton("🛑 остановить одного", callback_data="stop:one")],
            [InlineKeyboardButton("☑️ выбрать несколько", callback_data="stop:multi")],
            [InlineKeyboardButton("⬅️ меню", callback_data="nav:menu")],
        ]
    )
    await update.message.reply_text("остановить ботов:", reply_markup=kb)


async def stop_pick_one(q, context: ContextTypes.DEFAULT_TYPE) -> None:
    chat_id = q.message.chat_id
    bots = [b for b in MANAGER.list_all(chat_id) if b.state in (Lifecycle.running, Lifecycle.queued)]
    kb = [
        [InlineKeyboardButton(f"🛑 #{b.cfg.bot_id} — {b.cfg.project_name}", callback_data=f"stop:bot:{b.cfg.bot_id}")]
        for b in bots[:20]
    ]
    kb.append([InlineKeyboardButton("⬅️ меню", callback_data="nav:menu")])
    await q.message.reply_text("выбери бота:", reply_markup=InlineKeyboardMarkup(kb))


async def stop_multi(q, context: ContextTypes.DEFAULT_TYPE) -> None:
    _screen_set(context, Screen.stop_multi)
    chat_id = q.message.chat_id
    bots = [b for b in MANAGER.list_all(chat_id) if b.state in (Lifecycle.running, Lifecycle.queued)]
    sel: Set[str] = context.chat_data.get("stop_selected", set())

    kb = []
    for b in bots[:20]:
        mark = "☑️" if b.cfg.bot_id in sel else "⬜️"
        kb.append(
            [
                InlineKeyboardButton(
                    f"{mark} #{b.cfg.bot_id} — {b.cfg.project_name}", callback_data=f"stop:toggle:{b.cfg.bot_id}"
                )
            ]
        )
    kb.append([InlineKeyboardButton("🛑 остановить выбранные", callback_data="stop:selected")])
    kb.append([InlineKeyboardButton("⬅️ меню", callback_data="nav:menu")])
    await q.message.reply_text("выбери несколько:", reply_markup=InlineKeyboardMarkup(kb))


# -------------------- edit --------------------
async def edit_pick(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    _screen_set(context, Screen.edit_pick)
    chat_id = update.message.chat_id
    bots = [b for b in MANAGER.list_all(chat_id) if b.state in (Lifecycle.running, Lifecycle.queued)]
    if not bots:
        await update.message.reply_text("нет активных ботов для изменения", reply_markup=MAIN_MENU_KB)
        return
    kb = [
        [InlineKeyboardButton(f"✏️ #{b.cfg.bot_id} — {b.cfg.project_name}", callback_data=f"edit:bot:{b.cfg.bot_id}")]
        for b in bots[:20]
    ]
    kb.append([InlineKeyboardButton("⬅️ меню", callback_data="nav:menu")])
    await update.message.reply_text("выбери бота:", reply_markup=InlineKeyboardMarkup(kb))


async def edit_menu(q, context: ContextTypes.DEFAULT_TYPE) -> None:
    _screen_set(context, Screen.edit_menu)
    bot_id = context.chat_data.get("edit_bot_id")
    inst = MANAGER.bots.get(bot_id) if bot_id else None
    if not inst:
        await q.message.reply_text("не нашёл бота", reply_markup=MAIN_MENU_KB)
        return
    c = inst.cfg
    text = (
        f"✏️ bot #{c.bot_id}\n{c.project_name}\n"
        f"utc: {c.from_iso_z} → {c.to_iso_z}\n"
        f"interval: {c.interval_sec}s\nmode: {'dry-run' if c.dry_run else 'booking'}\n"
        f"state: {inst.state}"
    )
    kb = InlineKeyboardMarkup(
        [
            [
                InlineKeyboardButton("изменить start", callback_data="edit:set_from"),
                InlineKeyboardButton("изменить end", callback_data="edit:set_to"),
            ],
            [
                InlineKeyboardButton("интервал", callback_data="edit:set_interval"),
                InlineKeyboardButton("toggle dry", callback_data="edit:toggle_dry"),
            ],
            [InlineKeyboardButton("перезапустить", callback_data="edit:restart")],
            [InlineKeyboardButton("⬅️ меню", callback_data="nav:menu")],
        ]
    )
    await q.message.reply_text(text, reply_markup=kb)


async def edit_custom_from(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    bot_id = context.chat_data.get("edit_bot_id")
    inst = MANAGER.bots.get(bot_id) if bot_id else None
    if not inst:
        await update.message.reply_text("не нашёл бота", reply_markup=MAIN_MENU_KB)
        _screen_set(context, Screen.menu)
        return
    try:
        inst.cfg.from_iso_z = _parse_dt_to_utc_z(update.message.text)
    except Exception as e:
        await update.message.reply_text(f"❌ {e}", reply_markup=MAIN_MENU_KB)
        return
    _screen_set(context, Screen.edit_menu)
    await update.message.reply_text("✅ обновил start", reply_markup=MAIN_MENU_KB)


async def edit_custom_to(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    bot_id = context.chat_data.get("edit_bot_id")
    inst = MANAGER.bots.get(bot_id) if bot_id else None
    if not inst:
        await update.message.reply_text("не нашёл бота", reply_markup=MAIN_MENU_KB)
        _screen_set(context, Screen.menu)
        return
    try:
        inst.cfg.to_iso_z = _parse_dt_to_utc_z(update.message.text)
    except Exception as e:
        await update.message.reply_text(f"❌ {e}", reply_markup=MAIN_MENU_KB)
        return
    _screen_set(context, Screen.edit_menu)
    await update.message.reply_text("✅ обновил end", reply_markup=MAIN_MENU_KB)


async def edit_custom_interval(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    bot_id = context.chat_data.get("edit_bot_id")
    inst = MANAGER.bots.get(bot_id) if bot_id else None
    if not inst:
        await update.message.reply_text("не нашёл бота", reply_markup=MAIN_MENU_KB)
        _screen_set(context, Screen.menu)
        return
    try:
        val = int((update.message.text or "").strip())
        if val < 10 or val > 3600:
            raise ValueError("интервал 10..3600")
        inst.cfg.interval_sec = val
    except Exception as e:
        await update.message.reply_text(f"❌ {e}", reply_markup=MAIN_MENU_KB)
        return
    _screen_set(context, Screen.edit_menu)
    await update.message.reply_text("✅ обновил интервал", reply_markup=MAIN_MENU_KB)


async def edit_restart(q, context: ContextTypes.DEFAULT_TYPE) -> None:
    chat_id = q.message.chat_id
    bot_id = context.chat_data.get("edit_bot_id")
    inst = MANAGER.bots.get(bot_id) if bot_id else None
    if not inst:
        await q.message.reply_text("не нашёл бота", reply_markup=MAIN_MENU_KB)
        return
    if inst.state == Lifecycle.running:
        MANAGER.stop_bot(bot_id)
        inst.state = Lifecycle.queued
        MANAGER.queues.setdefault(chat_id, []).append(bot_id)
        await q.message.reply_text("🔄 поставил в очередь (перезапуск)", reply_markup=MAIN_MENU_KB)
        await MANAGER.try_start_next(chat_id, context.application)
    else:
        await q.message.reply_text("бот не running", reply_markup=MAIN_MENU_KB)


# -------------------- status --------------------
async def status_show(msg_or_q, context: ContextTypes.DEFAULT_TYPE) -> None:
    chat_id = msg_or_q.message.chat_id if hasattr(msg_or_q, "message") else msg_or_q.message.chat_id
    running = MANAGER.running_count(chat_id)
    queued = len(MANAGER.queues.get(chat_id, []))
    lines = [
        f"📌 статус\nrunning: {running}\nqueued: {queued}\n"
        f"max: {MANAGER.settings.max_bots}\ninterval: {MANAGER.settings.interval_sec}s\n"
    ]
    bots = MANAGER.list_all(chat_id)
    if not bots:
        lines.append("ботов нет")
    else:
        for b in bots:
            if b.state != Lifecycle.done:
                lines.append(_bot_line(b))
    text = "\n".join(lines).strip()
    kb = InlineKeyboardMarkup(
        [
            [InlineKeyboardButton("🔄 обновить", callback_data="status:refresh")],
            [InlineKeyboardButton("⬅️ меню", callback_data="nav:menu")],
        ]
    )
    if hasattr(msg_or_q, "message"):
        await msg_or_q.message.reply_text(text, reply_markup=kb)
    else:
        await msg_or_q.edit_message_text(text, reply_markup=kb)


# -------------------- settings --------------------
async def settings_menu(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    _screen_set(context, Screen.settings_menu)
    kb = InlineKeyboardMarkup(
        [
            [InlineKeyboardButton(f"макс. ботов: {MANAGER.settings.max_bots}", callback_data="settings:max")],
            [InlineKeyboardButton(f"интервал: {MANAGER.settings.interval_sec}s", callback_data="settings:interval")],
            [InlineKeyboardButton("⬅️ меню", callback_data="nav:menu")],
        ]
    )
    await update.message.reply_text("⚙️ настройки:", reply_markup=kb)


async def settings_pick_max(q, context: ContextTypes.DEFAULT_TYPE) -> None:
    kb = [[InlineKeyboardButton(str(n), callback_data=f"settings:setmax:{n}")] for n in range(1, 6)]
    kb.append([InlineKeyboardButton("⬅️ меню", callback_data="nav:menu")])
    await q.message.reply_text("выбери max bots (1–5):", reply_markup=InlineKeyboardMarkup(kb))


async def settings_apply_max(q, context: ContextTypes.DEFAULT_TYPE, new_max: int) -> None:
    chat_id = q.message.chat_id
    old = MANAGER.settings.max_bots
    MANAGER.settings.max_bots = max(1, new_max)

    # если уменьшили ниже текущего running — останавливаем "лишние" (последние)
    if MANAGER.running_count(chat_id) > MANAGER.settings.max_bots:
        extras = MANAGER.running_count(chat_id) - MANAGER.settings.max_bots
        for inst in MANAGER.running(chat_id)[-extras:]:
            MANAGER.stop_bot(inst.cfg.bot_id)

    await q.message.reply_text(f"✅ max bots: {old} → {MANAGER.settings.max_bots}", reply_markup=MAIN_MENU_KB)
    await MANAGER.try_start_next(chat_id, context.application)


async def settings_custom_interval(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    try:
        val = int((update.message.text or "").strip())
        if val < 10 or val > 3600:
            raise ValueError("интервал 10..3600")
        MANAGER.settings.interval_sec = val
    except Exception as e:
        await update.message.reply_text(f"❌ {e}", reply_markup=MAIN_MENU_KB)
        return
    _screen_set(context, Screen.settings_menu)
    await update.message.reply_text(f"✅ интервал: {val}s", reply_markup=MAIN_MENU_KB)
