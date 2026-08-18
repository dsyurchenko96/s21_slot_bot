from s21_slot_bot.app.booking_manager import BookingManager
from s21_slot_bot.app.bot_manager import BotManager
from s21_slot_bot.app.flows.collector import FlowCollector
from s21_slot_bot.app.flows.start import StartFlow
from s21_slot_bot.app.messenger import Messenger
from s21_slot_bot.app.models import FlowCategory
from s21_slot_bot.client.s21_client import School21Client


class TestFlowCollector:
    def test_get_flow_returns_category_flow(
        self,
        s21_client_mock: School21Client,
        bot_manager_mock: BotManager,
        booking_manager_mock: BookingManager,
        messenger_mock: Messenger,
    ) -> None:
        collector = FlowCollector(
            s21_client=s21_client_mock,
            bot_manager=bot_manager_mock,
            booking_manager=booking_manager_mock,
            messenger=messenger_mock,
        )

        assert collector.get_flow(FlowCategory.START) is collector.start
        assert isinstance(collector.start, StartFlow)
