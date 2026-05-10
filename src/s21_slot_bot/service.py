from telegram.ext import (
    Application,
    ApplicationBuilder,
    CommandHandler,
    CallbackQueryHandler,
    MessageHandler,
    filters,
    ContextTypes,
)

from s21_slot_bot.app.bot_manager import BotManager
from s21_slot_bot.app.input_handler import InputHandler
from s21_slot_bot.app.models import ChatDataModel, CustomContext
from s21_slot_bot.client.s21_client import School21Client
from s21_slot_bot.config import SlotBotServiceConfig


class SlotBotService:
    def __init__(
        self,
        config: SlotBotServiceConfig,
        s21_client_factory: type[School21Client] = School21Client,
        bot_manager_factory: type[BotManager] = BotManager,
        input_handler_factory: type[InputHandler] = InputHandler,
        tg_app_builder: type[ApplicationBuilder] = ApplicationBuilder,
    ):
        self._s21_client = s21_client_factory(config=config.s21)
        self._bot_manager = bot_manager_factory(
            bot_config=config.bot, s21_config=config.s21, s21_client_factory=s21_client_factory
        )
        self._input_handler = input_handler_factory(s21_client=self._s21_client, bot_manager=self._bot_manager)
        self._tg_app = self._build_tg_app(
            tg_app_builder=tg_app_builder, token=config.tg_token.get_secret_value(), input_handler=self._input_handler
        )

    def _build_tg_app(
        self, tg_app_builder: type[ApplicationBuilder], token: str, input_handler: InputHandler
    ) -> Application:
        context_types = ContextTypes(context=CustomContext, chat_data=ChatDataModel)
        app = tg_app_builder().token(token).context_types(context_types).build()
        app.add_handler(CommandHandler("start", input_handler.cmd_start))
        app.add_handler(CallbackQueryHandler(input_handler.on_cb))
        app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, input_handler.on_text))
        # TODO: add error handler
        return app

    def start(self):
        self._tg_app.run_polling()
