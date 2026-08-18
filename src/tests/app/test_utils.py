from unittest.mock import MagicMock

import pytest
from telegram import Update

from s21_slot_bot.app.errors import AppNotInitializedError, InternalError
from s21_slot_bot.app.models import CustomContext
from s21_slot_bot.app.utils import get_message_text, get_tzinfo


class TestUtils:
    def test_get_tzinfo(self, context: CustomContext, timezone) -> None:
        assert get_tzinfo(context) == timezone

    def test_get_tzinfo_requires_defaults(self, context: CustomContext) -> None:
        context.bot.defaults = None

        with pytest.raises(AppNotInitializedError):
            get_tzinfo(context)

    def test_get_message_text(self) -> None:
        update = MagicMock(spec=Update)
        update.message.text = "hello"

        assert get_message_text(update) == "hello"

    @pytest.mark.parametrize("message", [None, MagicMock(text=None), MagicMock(text="")])
    def test_get_message_text_rejects_missing_text(self, message) -> None:
        update = MagicMock(spec=Update)
        update.message = message

        with pytest.raises(InternalError):
            get_message_text(update)
