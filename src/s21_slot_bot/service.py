from zoneinfo import ZoneInfo

from telegram.ext import (
    Application,
    ApplicationBuilder,
    CallbackQueryHandler,
    CommandHandler,
    ContextTypes,
    Defaults,
    MessageHandler,
    filters,
)

from s21_slot_bot.app.booking_manager import BookingManager
from s21_slot_bot.app.bot_manager import BotManager
from s21_slot_bot.app.flows.collector import FlowCollector
from s21_slot_bot.app.input_handler import InputHandler
from s21_slot_bot.app.messenger import Messenger
from s21_slot_bot.app.models import App, BotData, ChatData, CustomContext
from s21_slot_bot.client.s21_client import School21Client
from s21_slot_bot.config import SlotBotServiceConfig


class SlotBotService:
    def __init__(
        self,
        config: SlotBotServiceConfig,
        s21_client_factory: type[School21Client] = School21Client,
        tg_app_builder: type[ApplicationBuilder] = ApplicationBuilder,
        messenger_factory: type[Messenger] = Messenger,
        bot_manager_factory: type[BotManager] = BotManager,
        booking_manager_factory: type[BookingManager] = BookingManager,
        flow_collector_factory: type[FlowCollector] = FlowCollector,
        input_handler_factory: type[InputHandler] = InputHandler,
    ):
        self._s21_client = s21_client_factory(config=config.s21)
        self._chat_id = config.bot.tg_chat_id.get_secret_value()
        self._tg_app = self._build_tg_app(
            tg_app_builder=tg_app_builder, token=config.tg_token.get_secret_value(), timezone=config.timezone
        )
        self._messenger = messenger_factory(chat_id=self._chat_id, bot=self._tg_app.bot)
        self._booking_manager = booking_manager_factory(
            s21_client=self._s21_client,
            messenger=self._messenger,
            app=self._tg_app,
            refresh_interval=config.bot.refresh_bookings_interval_sec,
            chat_id=self._chat_id,
        )
        self._bot_manager = bot_manager_factory(
            bot_config=config.bot,
            chat_id=self._chat_id,
            messenger=self._messenger,
            booking_manager=self._booking_manager,
            s21_config=config.s21,
            s21_client_factory=s21_client_factory,
        )
        self._flows = flow_collector_factory(
            s21_client=self._s21_client,
            bot_manager=self._bot_manager,
            booking_manager=self._booking_manager,
            messenger=self._messenger,
        )
        self._input_handler = input_handler_factory(
            bot_manager=self._bot_manager,
            messenger=self._messenger,
            flows=self._flows,
            chat_id=self._chat_id,
        )

        self._wire_app_handlers()

    def _build_tg_app(self, tg_app_builder: type[ApplicationBuilder], token: str, timezone: ZoneInfo) -> App:
        defaults = Defaults(tzinfo=timezone)
        context_types = ContextTypes(context=CustomContext, bot_data=BotData, chat_data=ChatData)
        app = tg_app_builder().token(token).context_types(context_types).defaults(defaults).build()
        return app

    def _wire_app_handlers(self):
        # TODO: check in a new chat
        self._tg_app.add_handler(CommandHandler("start", self._input_handler.on_cmd_start))
        self._tg_app.add_handler(CallbackQueryHandler(self._input_handler.on_callback))
        self._tg_app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, self._input_handler.on_text))
        self._tg_app.add_error_handler(self._input_handler.on_error)
        self._tg_app.post_stop = self._input_handler.on_stop

    def start(self):
        self._tg_app.run_polling()
