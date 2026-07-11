import asyncio
import logging
from contextlib import suppress

import telegram
from pydantic import ValidationError
from telegram import Update
from telegram.ext import Application

from s21_slot_bot.app.bot_manager import BotManager
from s21_slot_bot.app.flows.collector import FlowCollector
from s21_slot_bot.app.messenger import MAIN_MENU_KB, Messenger
from s21_slot_bot.app.models import App, CustomContext, FlowCategory, MenuButton, Screen
from s21_slot_bot.client.s21_client import School21Client
from s21_slot_bot.common.exceptions import Error, ForbiddenError, InvalidCallbackDataError, MenuError
from s21_slot_bot.common.logger import get_service_hook_logger, get_user_input_logger


class InputHandler:
    def __init__(
        self,
        s21_client: School21Client,
        bot_manager: BotManager,
        messenger: Messenger,
        chat_id: int,
    ):
        self._bot_manager = bot_manager
        self._messenger = messenger
        self._chat_id = chat_id
        self._flows = FlowCollector(s21_client=s21_client, bot_manager=bot_manager, messenger=messenger)
        self._button_to_method = {
            MenuButton.START: self._flows.start.list_projects,
            MenuButton.STOP: self._flows.stop.stop_menu,
            MenuButton.DELETE: self._flows.delete.delete_menu,
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

    async def cmd_start(self, update: Update, _: CustomContext) -> None:
        self._validate_access(update)
        await self._messenger.safe_delete(update.message.message_id)
        message = await update.message.reply_text("Slot bot — меню", reply_markup=MAIN_MENU_KB)

    async def on_text(self, update: Update, context: CustomContext) -> None:
        self._validate_access(update)
        text = update.message.text
        screen = context.chat_data.screen
        logger = get_user_input_logger(update)
        logger.info("Handling text `%s` with screen `%s`", text, screen)

        await self._messenger.safe_delete(update.message.message_id, logger)
        button_method = text in MenuButton and self._button_to_method.get(MenuButton(text))
        screen_method = self._screen_to_method.get(screen)
        method = button_method or screen_method
        if not method:
            raise MenuError("выбери действие в меню")
            # await self._messenger.render_menu(context, "выбери действие в меню")
            # return

        # context.chat_data.screen = Screen.MENU
        if not context.chat_data.menu_msg_id:
            await self._messenger.render_menu_message(context, "обработка запроса...", logger)
        await method(update, context)
        await self.on_success(update, context)

    async def on_callback(self, update: Update, context: CustomContext) -> None:
        self._validate_access(update)
        logger = get_user_input_logger(update)
        query = update.callback_query
        # TODO: Put "loading" in on_text?
        await query.answer()
        data = query.data or ""
        logger.info("Processing callback `%s`", data)

        callback_data = data.split(":")
        callback_data.reverse()
        try:
            category = FlowCategory(callback_data.pop())
            flow = self._flows.get_flow(category)
            # context.chat_data.screen = Screen.MENU
            await flow.parse_callback(callback_data, query, context)
            await self.on_success(update, context)
        # TODO: catch errors in flows and reraise them as only InvalidCallbackDataError?
        except (IndexError, ValueError, ValidationError, InvalidCallbackDataError) as e:
            raise InvalidCallbackDataError("не удалось обработать команду", location=data) from e

    async def on_error(self, update: Update | object, context: CustomContext) -> None:
        logger = get_user_input_logger(update)
        error = context.error
        match error:
            case telegram.error.BadRequest():
                if "not modified" in error.message.lower():
                    logger.info("No update has taken place in error handle: %s", error)
                    return
                await self._messenger.send(context, f"❌ ошибка обработки запроса телеграма: {error}")
            case MenuError():
                await self._messenger.render_menu_error(context, error.to_pretty(), logger)
            case Error():
                await self._messenger.send(context, error.to_pretty())
            case _:
                await self._messenger.send(context, f"❌ неизвестная ошибка: {error}")
        if job := context.job:
            self._bot_manager.stop_bot(job.name, context)
        logger.error("Exception while handling an update: %s", error, exc_info=error)

    async def on_success(self, update: Update, context: CustomContext) -> None:
        logger = get_user_input_logger(update)
        await self._messenger.safe_delete(context.chat_data.menu_error_msg_id, logger)
        context.chat_data.menu_error_msg_id = None

    async def on_stop(self, application: App) -> None:
        logger = get_service_hook_logger()
        logger.info("Running custom on-stop application hook...")
        chat_data = application.chat_data.get(self._chat_id)
        if chat_data:
            await self._messenger.safe_delete(chat_data.menu_error_msg_id, logger)
            await self._messenger.safe_delete(chat_data.menu_msg_id, logger)
            logger.info("Deleted menu messages")

    def _validate_access(self, update: Update) -> None:
        message = update.message or update.callback_query.message
        if message.chat_id != self._chat_id:
            raise ForbiddenError("отсутствует доступ к боту")
