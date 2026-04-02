from pydantic import ValidationError
from telegram import Update
from telegram.ext import ContextTypes

from s21_slot_bot.app.bot_manager import BotManager
from s21_slot_bot.app.exceptions import InvalidCallbackData
from s21_slot_bot.app.flows.collector import FlowCollector
from s21_slot_bot.app.menu_markup import MAIN_MENU_KB
from s21_slot_bot.app.models import Screen, FlowCategory
from s21_slot_bot.client.s21_client import School21Client


def _screen_set(ctx: ContextTypes.DEFAULT_TYPE, scr: Screen) -> None:
    ctx.chat_data["screen"] = scr


def _screen_get(ctx: ContextTypes.DEFAULT_TYPE) -> Screen:
    v = ctx.chat_data.get("screen", Screen.MENU)
    try:
        return Screen(v)
    except Exception:
        return Screen.MENU


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
            await self.flows.stop.stop_menu(update, context)
            return
        if txt == "✏️ изменить":
            await self.flows.edit.edit_pick(update, context)
            return
        if txt == "📌 статус":
            await self.flows.status.status_show(update, context)
            return
        if txt == "⚙️ настройки":
            await self.flows.settings.settings_menu(update, context)
            return

        # wizard custom input
        if scr == Screen.START_WAIT_FROM:
            await self.flows.start.custom_from(update, context)
            return
        if scr == Screen.START_WAIT_TO:
            await self.flows.start.custom_to(update, context)
            return
        if scr == Screen.EDIT_WAIT_FROM:
            await self.flows.edit.edit_custom_from(update, context)
            return
        if scr == Screen.EDIT_WAIT_TO:
            await self.flows.edit.edit_custom_to(update, context)
            return
        if scr == Screen.EDIT_WAIT_INTERVAL:
            await self.flows.edit.edit_custom_interval(update, context)
            return
        if scr == Screen.SETTINGS_WAIT_INTERVAL:
            await self.flows.settings.settings_custom_interval(update, context)
            return

        # TODO: delete this message once the user clicks a valid button?
        await update.message.reply_text("выбери действие в меню 🙂", reply_markup=MAIN_MENU_KB)

    # -------------------- callbacks --------------------
    async def on_cb(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        query = update.callback_query
        await query.answer()
        data = query.data or ""

        callback_data = data.split(":")
        callback_data.reverse()
        try:
            category = FlowCategory(callback_data.pop())
            flow = self.flows.get_flow(category)
            await flow.parse_callback(callback_data, query, context)
        except IndexError, ValueError, ValidationError, InvalidCallbackData:
            raise InvalidCallbackData(f"Failed to parse callback data: `{data}`")
