from collections.abc import Callable
from unittest.mock import MagicMock

import pytest

from s21_slot_bot.app.errors import AppNotInitializedError
from s21_slot_bot.app.models import BotInstance, CustomContext, Lifecycle, Mode


class TestModels:
    @pytest.mark.parametrize(
        ("state", "expected"),
        [
            (Lifecycle.RUNNING, ("▶️", "активен")),
            (Lifecycle.STOPPED, ("⏸️", "остановлен")),
            (Lifecycle.FAILED, ("❌", "ошибка")),
        ],
    )
    def test_lifecycle_to_emoji_text(self, state: Lifecycle, expected: tuple[str, str]) -> None:
        assert state.to_emoji_text() == expected

    @pytest.mark.parametrize(
        ("mode", "expected"),
        [
            (Mode.ONLY_FIND, ("🔍", "только найти слот (без записи)")),
            (Mode.FIND_AND_BOOK, ("📝", "найти слоты и записаться")),
        ],
    )
    def test_mode_to_emoji_text(self, mode: Mode, expected: tuple[str, str]) -> None:
        assert mode.to_emoji_text() == expected

    def test_bot_instance_logger(self, bot_instance_factory: Callable[..., BotInstance]) -> None:
        inst: BotInstance = bot_instance_factory(bot_id="abc")
        assert inst.logger().extra["id"] == "abc"

    def test_context_guards(self) -> None:
        context = MagicMock(spec=CustomContext)
        context.chat_data = None
        context.job_queue = None
        with pytest.raises(AppNotInitializedError):
            CustomContext.ensured_chat_data.fget(context)
        with pytest.raises(AppNotInitializedError):
            CustomContext.ensured_job_queue.fget(context)
