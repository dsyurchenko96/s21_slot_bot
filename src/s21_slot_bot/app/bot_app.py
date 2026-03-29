from pydantic import ValidationError
from telegram import InlineKeyboardButton, InlineKeyboardMarkup, Update, CallbackQuery
from telegram.ext import ContextTypes

from s21_slot_bot.app.bot_manager import MANAGER, BotManager
from s21_slot_bot.app.exceptions import InvalidCallbackData
from s21_slot_bot.app.flows.collector import FlowCollector
from s21_slot_bot.app.menu_markup import MAIN_MENU_KB
from s21_slot_bot.app.models import Lifecycle, Screen, BotInstance, FlowCategory
from s21_slot_bot.client.config import S21ClientConfig
from s21_slot_bot.client.s21_client import School21Client
from s21_slot_bot.common.time import str_to_dt, dt_to_pretty


def _get_client() -> School21Client:
    return School21Client(S21ClientConfig())


def _screen_set(ctx: ContextTypes.DEFAULT_TYPE, scr: Screen) -> None:
    ctx.chat_data["screen"] = scr


def _screen_get(ctx: ContextTypes.DEFAULT_TYPE) -> Screen:
    v = ctx.chat_data.get("screen", Screen.MENU)
    try:
        return Screen(v)
    except Exception:
        return Screen.MENU


def _bot_line(inst: BotInstance) -> str:
    c = inst.cfg
    lp = dt_to_pretty(inst.stats.last_ping) if inst.stats.last_ping else "—"
    return (
        f"#{c.bot_id} [{inst.state}] {c.project_name} "
        f"({c.required_reviews} reviews, {'dry' if c.dry_run else 'book'})\n"
        f"time: {dt_to_pretty(c.from_dt)} → {dt_to_pretty(c.to_dt)}\n"
        f"last ping: {lp}, attempts: {inst.stats.attempts_total} "
        f"(ok {inst.stats.attempts_success} / fail {inst.stats.attempts_failed} / booked {inst.stats.currently_booked})\n"
    )


class InputHandler:
    def __init__(
        self,
        s21_client: School21Client,
        bot_manager: BotManager,
    ):
        self.flows = FlowCollector(s21_client=s21_client, bot_manager=bot_manager)

    async def cmd_start(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        _screen_set(context, Screen.MENU)
        await update.message.reply_text("Slot bot — меню", reply_markup=MAIN_MENU_KB)

    async def on_text(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        txt = (update.message.text or "").strip().lower()
        scr = _screen_get(context)

        if txt == "▶️ начать":
            await self.flows.start.pick_projects(update, context)
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
        if scr == Screen.START_WAIT_FROM:
            await self.flows.start.custom_from(update, context)
            return
        if scr == Screen.START_WAIT_TO:
            await self.flows.start.custom_to(update, context)
            return
        if scr == Screen.EDIT_WAIT_FROM:
            await edit_custom_from(update, context)
            return
        if scr == Screen.EDIT_WAIT_TO:
            await edit_custom_to(update, context)
            return
        if scr == Screen.EDIT_WAIT_INTERVAL:
            await edit_custom_interval(update, context)
            return
        if scr == Screen.SETTINGS_WAIT_INTERVAL:
            await settings_custom_interval(update, context)
            return

        await update.message.reply_text("выбери действие в меню 🙂", reply_markup=MAIN_MENU_KB)

    # -------------------- callbacks --------------------
    async def on_cb(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        q = update.callback_query
        await q.answer()
        data = q.data or ""
        chat_id = q.message.chat_id

        callback_data = data.split(":")
        callback_data.reverse()
        try:
            category = FlowCategory(callback_data.pop())
            flow = self.flows.get_flow(category)
            await flow.parse_callback(callback_data, q, context)
        except IndexError, ValueError, ValidationError, InvalidCallbackData:
            raise InvalidCallbackData(f"Failed to parse callback data: `{data}`")

        if data == "nav:menu":
            _screen_set(context, Screen.MENU)
            await q.message.reply_text("Slot bot — меню", reply_markup=MAIN_MENU_KB)
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
            sel: set[str] = context.chat_data.get("stop_selected", set())
            if bot_id in sel:
                sel.remove(bot_id)
            else:
                sel.add(bot_id)
            context.chat_data["stop_selected"] = sel
            await stop_multi(q, context)
            return

        if data == "stop:selected":
            sel: set[str] = context.chat_data.get("stop_selected", set())
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
            _screen_set(context, Screen.EDIT_WAIT_FROM)
            await q.message.reply_text("введи новый start", reply_markup=MAIN_MENU_KB)
            return

        if data == "edit:set_to":
            _screen_set(context, Screen.EDIT_WAIT_TO)
            await q.message.reply_text("введи новый end", reply_markup=MAIN_MENU_KB)
            return

        if data == "edit:set_interval":
            _screen_set(context, Screen.EDIT_WAIT_INTERVAL)
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
            _screen_set(context, Screen.SETTINGS_WAIT_INTERVAL)
            await q.message.reply_text("введи новый глобальный интервал (сек)", reply_markup=MAIN_MENU_KB)
            return

        await q.message.reply_text("не понял кнопку — вернись в меню", reply_markup=MAIN_MENU_KB)


async def _respond_to_input(user_input: Update | CallbackQuery, message: str, kb: InlineKeyboardMarkup) -> None:
    match user_input:
        case Update():
            await user_input.message.reply_text(message, reply_markup=kb)
        case CallbackQuery():
            await user_input.edit_message_text(message, reply_markup=kb)


# -------------------- start wizard steps --------------------
# async def start_begin(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
#     _screen_set(context, Screen.START_PICK_PROJECT)
#     chat_id = update.message.chat_id
#
#     client = _get_client()
#     client.login()
#
#     try:
#         projects = client.get_reviewed_projects(client.user_id)
#     except Exception as e:
#         await update.message.reply_text(f"❌ не смог получить проекты: {e}", reply_markup=MAIN_MENU_KB)
#         return
#
#     if not projects:
#         await update.message.reply_text("📭 нет активных проектов на проверке", reply_markup=MAIN_MENU_KB)
#         return
#
#     context.chat_data["projects_map"] = {project.id: project.name for project in projects}
#
#     if len(projects) == 1:
#         project = projects[0]
#         context.chat_data["start_project_id"] = project.id
#         context.chat_data["start_project_name"] = project.name
#         await update.message.reply_text(f"проект выбран: {project.name} (id {project.id})", reply_markup=MAIN_MENU_KB)
#         await start_pick_num(update, context)
#         return
#
#     kb = [
#         [InlineKeyboardButton(f"{project.name} ({project.id})", callback_data=f"start:proj:{project.id}")]
#         for project in projects[:20]
#     ]
#     kb.append([InlineKeyboardButton("⬅️ меню", callback_data="nav:menu")])
#     await update.message.reply_text("выбери проект:", reply_markup=InlineKeyboardMarkup(kb))
#
#
# async def start_pick_num(user_input: Update | CallbackQuery, context: ContextTypes.DEFAULT_TYPE) -> None:
#     _screen_set(context, Screen.START_PICK_NUM)
#     kb = InlineKeyboardMarkup(
#         [
#             [
#                 InlineKeyboardButton("1", callback_data="start:num:1"),
#                 InlineKeyboardButton("2", callback_data="start:num:2"),
#                 InlineKeyboardButton("3", callback_data="start:num:3"),
#             ],
#             [InlineKeyboardButton("⬅️ меню", callback_data="nav:menu")],
#         ]
#     )
#     message = "сколько проверок нужно (1–3)?"
#     await _respond_to_input(user_input, message, kb)
#
#
# async def start_pick_from(user_input: Update | CallbackQuery, context: ContextTypes.DEFAULT_TYPE) -> None:
#     _screen_set(context, Screen.START_PICK_FROM)
#     kb = InlineKeyboardMarkup(
#         [
#             [
#                 InlineKeyboardButton("сейчас", callback_data="start:from:now"),
#                 InlineKeyboardButton("+30м", callback_data="start:from:p30"),
#                 InlineKeyboardButton("+1ч", callback_data="start:from:p60"),
#             ],
#             [InlineKeyboardButton("ввести вручную", callback_data="start:from:custom")],
#             [InlineKeyboardButton("⬅️ меню", callback_data="nav:menu")],
#         ]
#     )
#     message = "выбери start (по умолчанию сейчас):"
#     await _respond_to_input(user_input, message, kb)
#
#
# async def start_custom_from(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
#     try:
#         context.chat_data["start_from"] = str_to_dt(update.message.text, MANAGER.config.timezone)
#     except Exception as e:
#         await update.message.reply_text(f"❌ {e}\nпопробуй ещё раз", reply_markup=MAIN_MENU_KB)
#         return
#     await start_pick_to(update, context)
#
#
# async def start_pick_to(user_input: Update | CallbackQuery, context: ContextTypes.DEFAULT_TYPE) -> None:
#     _screen_set(context, Screen.START_PICK_TO)
#     kb = InlineKeyboardMarkup(
#         [
#             [
#                 InlineKeyboardButton("+2ч", callback_data="start:to:p120"),
#                 InlineKeyboardButton("+4ч", callback_data="start:to:p240"),
#             ],
#             [InlineKeyboardButton("ввести вручную", callback_data="start:to:custom")],
#             [InlineKeyboardButton("⬅️ меню", callback_data="nav:menu")],
#         ]
#     )
#     message = "выбери end (по умолчанию +2ч от start):"
#     await _respond_to_input(user_input, message, kb)
#
#
# async def start_custom_to(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
#     try:
#         context.chat_data["start_to"] = str_to_dt(update.message.text, MANAGER.config.timezone)
#     except Exception as e:
#         await update.message.reply_text(f"❌ {e}\nпопробуй ещё раз", reply_markup=MAIN_MENU_KB)
#         return
#     await start_pick_mode(update, context)
#
#
# async def start_pick_mode(user_input: Update | CallbackQuery, context: ContextTypes.DEFAULT_TYPE) -> None:
#     _screen_set(context, Screen.START_PICK_MODE)
#     kb = InlineKeyboardMarkup(
#         [
#             [InlineKeyboardButton("🔎 Искать слоты", callback_data="start:mode:dry")],
#             [InlineKeyboardButton("✅ Записаться", callback_data="start:mode:book")],
#             [InlineKeyboardButton("⬅️ меню", callback_data="nav:menu")],
#         ]
#     )
#     message = "выбери режим:"
#     await _respond_to_input(user_input, message, kb)
#
#
# async def start_confirm(user_input: Update | CallbackQuery, context: ContextTypes.DEFAULT_TYPE) -> None:
#     _screen_set(context, Screen.START_CONFIRM)
#     chat_id = user_input.message.chat_id
#
#     pid = context.chat_data["start_project_id"]
#     name = context.chat_data["start_project_name"]
#     n = int(context.chat_data["start_required_reviews"])
#     frm = context.chat_data["start_from"]
#     to = context.chat_data["start_to"]
#     dry = bool(context.chat_data["start_dry_run"])
#
#     summary = (
#         f"проект: {name} (id {pid})\n"
#         f"нужно проверок: {n}\n"
#         f"окно: {dt_to_pretty(frm)} → {dt_to_pretty(to)}\n"
#         f"режим: {'dry-run' if dry else 'booking'}\n\n"
#         f"активных: {MANAGER.active_count(chat_id)} / max {MANAGER.config.max_bots}"
#     )
#     kb = InlineKeyboardMarkup(
#         [
#             [InlineKeyboardButton("🚀 старт", callback_data="start:confirm:start")],
#             [InlineKeyboardButton("➕ в очередь", callback_data="start:confirm:queue")],
#             [InlineKeyboardButton("⬅️ меню", callback_data="nav:menu")],
#         ]
#     )
#     await _respond_to_input(user_input, summary, kb)
#
#
# async def start_finalize(q, context: ContextTypes.DEFAULT_TYPE, action: str) -> None:
#     chat_id = q.message.chat_id
#
#     pid = context.chat_data["start_project_id"]
#     name = context.chat_data["start_project_name"]
#     n = int(context.chat_data["start_required_reviews"])
#     frm = context.chat_data["start_from"]
#     to = context.chat_data["start_to"]
#     dry = bool(context.chat_data["start_dry_run"])
#
#     bot_id = secrets.token_hex(3)
#     cfg = BotConfig(
#         bot_id=bot_id,
#         chat_id=chat_id,
#         project_id=pid,
#         project_name=name,
#         required_reviews=n,
#         from_dt=frm,
#         to_dt=to,
#         interval_sec=MANAGER.config.poll_interval_sec,
#         dry_run=dry,
#     )
#     inst = BotInstance(cfg=cfg)
#     MANAGER.add_bot(inst)
#
#     if action == "start" and MANAGER.running_count(chat_id) < MANAGER.config.max_bots:
#         await q.message.reply_text(f"✅ добавил bot #{bot_id} и запускаю", reply_markup=MAIN_MENU_KB)
#         await MANAGER.try_start_next(chat_id, context.application)
#     elif action == "start":
#         await q.message.reply_text(
#             f"✅ добавил bot #{bot_id}, лимит достигнут — поставил в очередь", reply_markup=MAIN_MENU_KB
#         )
#     else:
#         await q.message.reply_text(f"➕ добавил bot #{bot_id} в очередь", reply_markup=MAIN_MENU_KB)
#
#     _screen_set(context, Screen.MENU)


# -------------------- stop --------------------
async def stop_menu(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    _screen_set(context, Screen.STOP_MENU)
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
    bots = [b for b in MANAGER.list_all(chat_id) if b.state in (Lifecycle.RUNNING, Lifecycle.QUEUED)]
    kb = [
        [InlineKeyboardButton(f"🛑 #{b.cfg.bot_id} — {b.cfg.project_name}", callback_data=f"stop:bot:{b.cfg.bot_id}")]
        for b in bots[:20]
    ]
    kb.append([InlineKeyboardButton("⬅️ меню", callback_data="nav:menu")])
    await q.message.reply_text("выбери бота:", reply_markup=InlineKeyboardMarkup(kb))


async def stop_multi(q, context: ContextTypes.DEFAULT_TYPE) -> None:
    _screen_set(context, Screen.STOP_MULTI)
    chat_id = q.message.chat_id
    bots = [b for b in MANAGER.list_all(chat_id) if b.state in (Lifecycle.RUNNING, Lifecycle.QUEUED)]
    sel: set[str] = context.chat_data.get("stop_selected", set())

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
    _screen_set(context, Screen.EDIT_PICK)
    chat_id = update.message.chat_id
    bots = [b for b in MANAGER.list_all(chat_id) if b.state in (Lifecycle.RUNNING, Lifecycle.QUEUED)]
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
    _screen_set(context, Screen.EDIT_MENU)
    bot_id = context.chat_data.get("edit_bot_id")
    inst = MANAGER.bots.get(bot_id) if bot_id else None
    if not inst:
        await q.message.reply_text("не нашёл бота", reply_markup=MAIN_MENU_KB)
        return
    c = inst.cfg
    text = (
        f"✏️ bot #{c.bot_id}\n{c.project_name}\n"
        f"utc: {c.from_dt} → {c.to_dt}\n"
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
        _screen_set(context, Screen.MENU)
        return
    try:
        inst.cfg.from_dt = str_to_dt(update.message.text, MANAGER.config.timezone)
    except Exception as e:
        await update.message.reply_text(f"❌ {e}", reply_markup=MAIN_MENU_KB)
        return
    _screen_set(context, Screen.EDIT_MENU)
    await update.message.reply_text("✅ обновил start", reply_markup=MAIN_MENU_KB)


async def edit_custom_to(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    bot_id = context.chat_data.get("edit_bot_id")
    inst = MANAGER.bots.get(bot_id) if bot_id else None
    if not inst:
        await update.message.reply_text("не нашёл бота", reply_markup=MAIN_MENU_KB)
        _screen_set(context, Screen.MENU)
        return
    try:
        inst.cfg.to_dt = str_to_dt(update.message.text, MANAGER.config.timezone)
    except Exception as e:
        await update.message.reply_text(f"❌ {e}", reply_markup=MAIN_MENU_KB)
        return
    _screen_set(context, Screen.EDIT_MENU)
    await update.message.reply_text("✅ обновил end", reply_markup=MAIN_MENU_KB)


async def edit_custom_interval(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    bot_id = context.chat_data.get("edit_bot_id")
    inst = MANAGER.bots.get(bot_id) if bot_id else None
    if not inst:
        await update.message.reply_text("не нашёл бота", reply_markup=MAIN_MENU_KB)
        _screen_set(context, Screen.MENU)
        return
    try:
        val = int((update.message.text or "").strip())
        if val < 10 or val > 3600:
            raise ValueError("интервал 10..3600")
        inst.cfg.interval_sec = val
    except Exception as e:
        await update.message.reply_text(f"❌ {e}", reply_markup=MAIN_MENU_KB)
        return
    _screen_set(context, Screen.EDIT_MENU)
    await update.message.reply_text("✅ обновил интервал", reply_markup=MAIN_MENU_KB)


async def edit_restart(q, context: ContextTypes.DEFAULT_TYPE) -> None:
    chat_id = q.message.chat_id
    bot_id = context.chat_data.get("edit_bot_id")
    inst = MANAGER.bots.get(bot_id) if bot_id else None
    if not inst:
        await q.message.reply_text("не нашёл бота", reply_markup=MAIN_MENU_KB)
        return
    if inst.state == Lifecycle.RUNNING:
        MANAGER.stop_bot(bot_id)
        inst.state = Lifecycle.QUEUED
        MANAGER.queues.setdefault(chat_id, []).append(bot_id)
        await q.message.reply_text("🔄 поставил в очередь (перезапуск)", reply_markup=MAIN_MENU_KB)
        await MANAGER.try_start_next(chat_id, context.application)
    else:
        await q.message.reply_text("бот не running", reply_markup=MAIN_MENU_KB)


# -------------------- status --------------------
# TODO: break down bot statuses based on project
async def status_show(user_input: Update | CallbackQuery, context: ContextTypes.DEFAULT_TYPE) -> None:
    chat_id = user_input.message.chat_id
    running = MANAGER.running_count(chat_id)
    queued = len(MANAGER.queues.get(chat_id, []))
    lines = [
        f"📌 статус\nrunning: {running}\nqueued: {queued}\n"
        f"max: {MANAGER.config.max_bots}\ninterval: {MANAGER.config.poll_interval_sec}s\n"
    ]
    bots = MANAGER.list_all(chat_id)
    if not bots:
        lines.append("ботов нет")
    else:
        for b in bots:
            if b.state != Lifecycle.DONE:
                lines.append(_bot_line(b))
    text = "\n".join(lines).strip()
    kb = InlineKeyboardMarkup(
        [
            [InlineKeyboardButton("🔄 обновить", callback_data="status:refresh")],
            [InlineKeyboardButton("⬅️ меню", callback_data="nav:menu")],
        ]
    )
    await _respond_to_input(user_input, text, kb)


# -------------------- settings --------------------
async def settings_menu(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    _screen_set(context, Screen.SETTINGS_MENU)
    kb = InlineKeyboardMarkup(
        [
            [InlineKeyboardButton(f"макс. ботов: {MANAGER.config.max_bots}", callback_data="settings:max")],
            [InlineKeyboardButton(f"интервал: {MANAGER.config.poll_interval_sec}s", callback_data="settings:interval")],
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
    old = MANAGER.config.max_bots
    MANAGER.config.max_bots = max(1, new_max)

    # если уменьшили ниже текущего running — останавливаем "лишние" (последние)
    if MANAGER.running_count(chat_id) > MANAGER.config.max_bots:
        extras = MANAGER.running_count(chat_id) - MANAGER.config.max_bots
        for inst in MANAGER.running(chat_id)[-extras:]:
            MANAGER.stop_bot(inst.cfg.bot_id)

    await q.message.reply_text(f"✅ max bots: {old} → {MANAGER.config.max_bots}", reply_markup=MAIN_MENU_KB)
    await MANAGER.try_start_next(chat_id, context.application)


async def settings_custom_interval(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    try:
        val = int((update.message.text or "").strip())
        if val < 10 or val > 3600:
            raise ValueError("интервал 10..3600")
        MANAGER.config.poll_interval_sec = val
    except Exception as e:
        await update.message.reply_text(f"❌ {e}", reply_markup=MAIN_MENU_KB)
        return
    _screen_set(context, Screen.SETTINGS_MENU)
    await update.message.reply_text(f"✅ интервал: {val}s", reply_markup=MAIN_MENU_KB)
