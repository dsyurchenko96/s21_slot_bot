import asyncio
import logging
import os
import re
from collections import deque
from dataclasses import dataclass
from datetime import datetime, timezone, timedelta, UTC
from enum import IntEnum, auto

from telegram import InlineKeyboardButton, InlineKeyboardMarkup, Update
from telegram.ext import (
    Application,
    CallbackQueryHandler,
    CommandHandler,
    ContextTypes,
    ConversationHandler,
    MessageHandler,
    filters,
)

from slot_bot import School21Client, School21Error, pick_candidate_start
from zoneinfo import ZoneInfo

logging.Formatter.converter = lambda *args: datetime.now(tz=ZoneInfo("Europe/Moscow")).timetuple()

logging.basicConfig(
    format='%(asctime)s - %(levelname)s - %(message)s',
    level=logging.INFO
)
log = logging.getLogger("school21-bot")

MAX_REVIEWS = 3


class State(IntEnum):
    PROJECT_ID = auto()
    FROM = auto()
    NUM_REVIEWS = auto()
    TO = auto()
    CONFIRM = auto()


@dataclass
class SearchConfig:
    module_id: str
    project_name: str
    from_iso_z: str
    to_iso_z: str
    num_reviews: int


class BotState:
    def __init__(self) -> None:
        self.search_task: asyncio.Task | None = None
        self.search_cfg: SearchConfig | None = None
        self.last_ping: datetime | None = None
        self.num_booked: int = 0


BOT_STATE = BotState()


def _parse_dt_to_utc_z(text: str) -> str:
    """
    Принимает:
      - ISO с Z: 2025-12-14T21:00:00.000Z
      - или "YYYY-MM-DD HH:MM" (в часовом поясе BOT_TZ_OFFSET, по умолчанию +03:00)
    Возвращает: ISO с .000Z
    """
    s = text.strip()

    # already Z
    if re.match(r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(\.\d{3})?Z$", s):
        if "." not in s:
            return s.replace("Z", ".000Z")
        return s

    # local "YYYY-MM-DD HH:MM"
    m = re.match(r"^(\d{4}-\d{2}-\d{2})\s+(\d{2}:\d{2})$", s)
    if not m:
        raise ValueError("Неверный формат. Нужно ISO Z или 'YYYY-MM-DD HH:MM'.")

    date_part, time_part = m.group(1), m.group(2)
    dt_local = datetime.strptime(f"{date_part} {time_part}", "%Y-%m-%d %H:%M")

    # offset like +03:00
    off = os.getenv("BOT_TZ_OFFSET", "+03:00")
    sign = 1 if off[0] == "+" else -1
    hh = int(off[1:3])
    mm = int(off[4:6])
    delta_minutes = sign * (hh * 60 + mm)

    # convert local -> UTC by subtracting offset
    dt_utc = dt_local.timestamp() - (delta_minutes * 60)
    dt_utc_dt = datetime.fromtimestamp(dt_utc, UTC)
    return dt_utc_dt.strftime("%Y-%m-%dT%H:%M:%S.000Z")


async def start_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    kb = InlineKeyboardMarkup([
        [InlineKeyboardButton("🔎 Выбрать проект для поиска слотов", callback_data="choose_project")],
        [InlineKeyboardButton("⛔ Остановить поиск", callback_data="stop_search")],
        [InlineKeyboardButton("📌 Статус", callback_data="status")],
    ])
    await update.message.reply_text("Что делаем?", reply_markup=kb)
    return ConversationHandler.END


async def on_menu_click(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    q = update.callback_query
    await q.answer()

    if q.data == "choose_project":
        await q.message.reply_text("Введи ID проекта (moduleId), например: 26566")
        return State.PROJECT_ID

    if q.data == "back_time":
        await q.message.reply_text("Ок, введи *начальное* время заново.", parse_mode="Markdown")
        return State.FROM

    if q.data == "stop_search":
        await stop_search(update, context)
        return ConversationHandler.END

    if q.data == "status":
        await status(update)
        return ConversationHandler.END

    if q.data in ("start_dry", "start_book"):
        cfg: SearchConfig | None = context.user_data.get("cfg")
        if not cfg:
            await q.message.reply_text("⚠️ Не вижу выбранного проекта/времени. Начни заново через /start.")
            return ConversationHandler.END

        dry_run = (q.data == "start_dry")

        # стопаем предыдущий поиск
        if BOT_STATE.search_task and not BOT_STATE.search_task.done():
            BOT_STATE.search_task.cancel()
            BOT_STATE.search_task = None

        BOT_STATE.search_cfg = cfg

        mode = "dry-run (только искать)" if dry_run else "записаться при первом слоте"
        await q.message.reply_text(
            f"🚀 Запускаю поиск: {mode}\n"
            f"Проект: {cfg.project_name} (ID {cfg.module_id})\n"
            f"UTC: {cfg.from_iso_z} → {cfg.to_iso_z}"
        )

        BOT_STATE.search_task = asyncio.create_task(
            _search_loop(chat_id=update.effective_chat.id, cfg=cfg, app=context.application, dry_run=dry_run)
        )
        return ConversationHandler.END

    return ConversationHandler.END


def _get_client() -> School21Client:
    username = os.getenv("S21_USERNAME", "").strip()
    password = os.getenv("S21_PASSWORD", "").strip()
    if not username or not password:
        raise RuntimeError("S21_USERNAME / S21_PASSWORD не заданы")

    client = School21Client(username=username, password=password)
    return client


async def handle_project_id(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    module_id = update.message.text.strip()

    client = _get_client()
    client.login()

    # валидация через get_project_name
    try:
        project_name = client.get_project_name(module_id)
    except Exception as e:
        log.exception("Unable to get project name for module_id '%s'", module_id)
        await update.message.reply_text(f"❌ Не смог найти проект по ID {module_id}.\nОшибка: {e}\nПопробуй другой ID.")
        return State.PROJECT_ID

    context.user_data["module_id"] = module_id
    context.user_data["project_name"] = project_name

    await update.message.reply_text(
        f"✅ Ок, проект: {project_name}\n\n"
        "Введи количество проверок.\n",
    )
    return State.NUM_REVIEWS


async def handle_num_reviews(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    try:
        num_reviews = int(update.message.text)
        if not 1 <= num_reviews <= 3:
            raise ValueError("Количество проверок должно быть от 1 до 3.")
    except Exception as e:
        await update.message.reply_text(f"❌ {e}\nПопробуй ещё раз.")
        return State.NUM_REVIEWS

    context.user_data["num_reviews"] = num_reviews
    await update.message.reply_text(
        f"Количество проверок: {num_reviews}\n\n"
        "Теперь введи *начальное* время.\n"
        "Формат:\n"
        "- ISO UTC: `2025-12-14T21:00:00.000Z`\n"
        "- или локально: `YYYY-MM-DD HH:MM` (часовой пояс берём из BOT_TZ_OFFSET, по умолчанию +03:00)\n",
        parse_mode="Markdown",
    )
    return State.FROM


async def handle_from(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    try:
        from_iso = _parse_dt_to_utc_z(update.message.text)
    except Exception as e:
        await update.message.reply_text(f"❌ {e}\nПопробуй ещё раз.")
        return State.FROM

    context.user_data["from_iso"] = from_iso

    await update.message.reply_text(
        "Теперь введи *конечное* время (тот же формат).",
        parse_mode="Markdown",
    )
    return State.TO


async def handle_to(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    try:
        to_iso = _parse_dt_to_utc_z(update.message.text)
    except Exception as e:
        await update.message.reply_text(f"❌ {e}\nПопробуй ещё раз.")
        return State.TO

    module_id = context.user_data["module_id"]
    project_name = context.user_data["project_name"]
    num_reviews = context.user_data["num_reviews"]
    from_iso = context.user_data["from_iso"]

    cfg = SearchConfig(module_id=module_id, project_name=project_name, from_iso_z=from_iso, to_iso_z=to_iso, num_reviews=num_reviews)
    context.user_data["cfg"] = cfg

    kb = InlineKeyboardMarkup([
        [InlineKeyboardButton("🔎 Искать слоты", callback_data="start_dry")],
        [InlineKeyboardButton("✅ Записаться", callback_data="start_book")],
        [InlineKeyboardButton("↩️ Назад (изменить время)", callback_data="back_time")],
        [InlineKeyboardButton("⛔ Остановить поиск", callback_data="stop_search")],
    ])

    await update.message.reply_text(
        f"Готово. Проект:\n{project_name} (ID {module_id})\n"
        f"Интервал UTC:\n{from_iso} → {to_iso}\n\n"
        f"Выбери режим:",
        reply_markup=kb,
    )
    return State.CONFIRM


async def _search_loop(chat_id: int, cfg: SearchConfig, app: Application, dry_run: bool) -> None:
    interval = int(os.getenv("POLL_INTERVAL_SEC", "60"))
    jitter = int(os.getenv("POLL_JITTER_SEC", "8"))

    client = _get_client()
    client.login()

    # получаем task/answer
    task_id, answer_id = client.get_task_and_answer(cfg.module_id)
    log.info("Start search: module=%s task=%s answer=%s", cfg.module_id, task_id, answer_id)

    attempt = 0
    while True:
        attempt += 1
        try:
            now = datetime.now()
            dt_to = datetime.strptime(cfg.to_iso_z, "%Y-%m-%dT%H:%M:%S.000Z")
            if now >= dt_to:
                await app.bot.send_message(
                    chat_id,
                    f"⌛️ Таймаут! Время на поиск слота истекло\nПроект: {cfg.project_name}\nID: {cfg.module_id}\n"
                )
                return
            slots, num_already_booked = client.get_timeslots(task_id, cfg.from_iso_z, cfg.to_iso_z)
            if num_already_booked < BOT_STATE.num_booked:
                await app.bot.send_message(
                    chat_id,
                    f"⚠️ Похоже, что проверка отменилась!\nПроект: {cfg.project_name}\nID: {cfg.module_id}\n"
                    f"Количество записей: {BOT_STATE.num_booked}/{MAX_REVIEWS}\n"
                )
            BOT_STATE.num_booked = num_already_booked
            picked = pick_candidate_start(slots)
            BOT_STATE.last_ping = now
            if not picked:
                message = f"[{attempt}] no slots found"
                log.info(message)
            else:
                start_time, staff_slot = picked

                if dry_run:
                    await app.bot.send_message(
                        chat_id,
                        f"🔔 Найден слот (dry-run):\nПроект: {cfg.project_name}\nStart: {start_time}\n"
                        f"Если хочешь записаться — нажми /start → 'Записаться' и введи те же параметры (или я добавлю кнопку)."
                    )
                    return
                if BOT_STATE.num_booked < cfg.num_reviews:
                    booking_id = client.book(answer_id=answer_id, start_time_iso_z=start_time, staff_slot=staff_slot)
                    BOT_STATE.num_booked += 1
                    await app.bot.send_message(
                        chat_id,
                        f"✅ Успешно записался!\nПроект: {cfg.project_name}\nID: {cfg.module_id}\n"
                        f"Начало: {start_time}\nID брони: {booking_id}\n"
                        f"Количество записей: {BOT_STATE.num_booked}/{MAX_REVIEWS}\n"
                    )
                # if num_found_slots >= cfg.num_reviews or num_currently_booked >= MAX_REVIEWS:
                #     await app.bot.send_message(
                #         chat_id,
                #         "Все необходимые проверки найдены, останавливаю поиск..."
                #     )
                #     return

        except School21Error as e:
            # “слот уже забрали” и т.п.
            await app.bot.send_message(chat_id, f"[{attempt}] ошибка: {e}")
        except Exception as e:
            log.exception("Unexpected error!")
            await app.bot.send_message(chat_id, f"[{attempt}] unexpected: {e}")

        await asyncio.sleep(interval + (0 if jitter <= 0 else (attempt % (jitter + 1))))


async def stop_search(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if BOT_STATE.search_task and not BOT_STATE.search_task.done():
        BOT_STATE.search_task.cancel()
        BOT_STATE.search_task = None
        BOT_STATE.search_cfg = None
        await update.callback_query.message.reply_text("⛔ Поиск остановлен.")
    else:
        await update.callback_query.message.reply_text("ℹ️ Поиск и так не запущен.")


async def status(update: Update) -> None:
    if not BOT_STATE.search_task or BOT_STATE.search_task.done():
        await update.callback_query.message.reply_text("😴 Бот не запущен.")
        return
    if BOT_STATE.last_ping is None:
        await update.callback_query.message.reply_text("📭 Бот запущен, запрос на поиск еще не был отправлен.")
        return
    now = datetime.now()
    # TODO: refactor
    interval = int(os.getenv("POLL_INTERVAL_SEC", "60"))
    jitter = int(os.getenv("POLL_JITTER_SEC", "8"))
    last_ping_delta = now - BOT_STATE.last_ping
    if last_ping_delta < timedelta(seconds=(interval + jitter) * 2):
        message = f"✅ Бот ищет слоты (последний пинг {last_ping_delta} назад)\n"
    else:
        message = f"☠️ Бот не делал запросов в течение {last_ping_delta}\n"
    message += f"Проверок: {BOT_STATE.num_booked}/{BOT_STATE.search_cfg.num_reviews}"
    await update.callback_query.message.reply_text(message)


def main() -> None:
    token = os.getenv("TG_BOT_TOKEN", "").strip()
    if not token:
        raise RuntimeError("TG_BOT_TOKEN не задан")

    app = Application.builder().token(token).build()

    conv = ConversationHandler(
        entry_points=[CallbackQueryHandler(on_menu_click)],
        states={
            State.PROJECT_ID: [MessageHandler(filters.TEXT & ~filters.COMMAND, handle_project_id)],
            State.NUM_REVIEWS: [MessageHandler(filters.TEXT & ~filters.COMMAND, handle_num_reviews)],
            State.FROM: [MessageHandler(filters.TEXT & ~filters.COMMAND, handle_from)],
            State.TO: [MessageHandler(filters.TEXT & ~filters.COMMAND, handle_to)],
            State.CONFIRM: [CallbackQueryHandler(on_menu_click)],
        },
        fallbacks=[CommandHandler("start", start_cmd)],
        allow_reentry=True,
    )

    app.add_handler(CommandHandler("start", start_cmd))
    app.add_handler(conv)
    app.add_handler(CallbackQueryHandler(on_menu_click))

    app.run_polling(close_loop=False)


if __name__ == "__main__":
    main()
