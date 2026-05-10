import telegram
from pydantic import ValidationError
from telegram import Update

from s21_slot_bot.app.bot_manager import BotManager
from s21_slot_bot.app.flows.collector import FlowCollector
from s21_slot_bot.app.menu_markup import MAIN_MENU_KB
from s21_slot_bot.app.messages import ensure_wizard_message, render_message
from s21_slot_bot.app.models import CustomContext, FlowCategory, MenuButton, Screen
from s21_slot_bot.client.s21_client import School21Client
from s21_slot_bot.common.exceptions import InvalidCallbackData
from s21_slot_bot.common.logger import get_user_input_logger


# TODO: handle (telegram.error.BadRequest: Message is not modified:) error on all calls
class InputHandler:
    def __init__(
        self,
        s21_client: School21Client,
        bot_manager: BotManager,
    ):
        self._flows = FlowCollector(s21_client=s21_client, bot_manager=bot_manager)
        self._button_to_method = {
            MenuButton.START: self._flows.start.list_projects,
            MenuButton.STOP: self._flows.stop.stop_menu,
            MenuButton.EDIT: self._flows.edit.list_bots,
            MenuButton.STATUS: self._flows.status.status_show,
        }
        self._screen_to_method = {
            Screen.START_PICK_FROM: self._flows.start.custom_from,
            Screen.START_PICK_TO: self._flows.start.custom_to,
            Screen.EDIT_WAIT_FROM: self._flows.edit.edit_custom_from,
            Screen.EDIT_WAIT_TO: self._flows.edit.edit_custom_to,
            Screen.EDIT_WAIT_INTERVAL: self._flows.edit.edit_custom_interval,
        }

    async def cmd_start(self, update: Update, context: CustomContext) -> None:
        context.chat_data.screen = Screen.MENU
        await update.message.reply_text("Slot bot — меню", reply_markup=MAIN_MENU_KB)

    async def on_text(self, update: Update, context: CustomContext) -> None:
        text = update.message.text
        screen = context.chat_data.screen
        chat_id = update.message.chat_id
        logger = get_user_input_logger(update)
        logger.info("Handling text `%s` with screen `%s`", text, screen)

        await context.bot.delete_message(chat_id, update.message.message_id)
        button_method = text in MenuButton and self._button_to_method.get(MenuButton(text))
        screen_method = self._screen_to_method.get(screen)
        method = button_method or screen_method
        if not method:
            await render_message(update, context, "выбери действие в меню")
            return

        await ensure_wizard_message(chat_id, context)
        await method(update, context)
        return

    async def on_cb(self, update: Update, context: CustomContext) -> None:
        logger = get_user_input_logger(update)
        query = update.callback_query
        await query.answer()
        data = query.data or ""

        callback_data = data.split(":")
        callback_data.reverse()
        try:
            category = FlowCategory(callback_data.pop())
            flow = self._flows.get_flow(category)
            await flow.parse_callback(callback_data, query, context)
        # TODO: catch errors in flows and reraise them as only InvalidCallbackData?
        except telegram.error.BadRequest as e:
            if "message not modified" in e.message:
                logger.info("No update has taken place: %s", e)
                return
            raise
        except IndexError, ValueError, ValidationError, InvalidCallbackData:
            raise InvalidCallbackData(f"Failed to parse callback data: `{data}`")
