from s21_slot_bot.app.booking_manager import BookingManager
from s21_slot_bot.app.bot_manager import BotManager
from s21_slot_bot.app.errors import InvalidCallbackDataError
from s21_slot_bot.app.flows.base import Flow
from s21_slot_bot.app.flows.book import BookFlow
from s21_slot_bot.app.flows.delete import DeleteFlow
from s21_slot_bot.app.flows.edit import EditFlow
from s21_slot_bot.app.flows.start import StartFlow
from s21_slot_bot.app.flows.status import StatusFlow
from s21_slot_bot.app.flows.stop import StopFlow
from s21_slot_bot.app.messenger import Messenger
from s21_slot_bot.app.models import FlowCategory
from s21_slot_bot.client.s21_client import School21Client


class FlowCollector:
    def __init__(
        self,
        s21_client: School21Client,
        bot_manager: BotManager,
        booking_manager: BookingManager,
        messenger: Messenger,
        start_factory: type[StartFlow] = StartFlow,
        stop_factory: type[StopFlow] = StopFlow,
        delete_factory: type[DeleteFlow] = DeleteFlow,
        edit_factory: type[EditFlow] = EditFlow,
        status_factory: type[StatusFlow] = StatusFlow,
        book_factory: type[BookFlow] = BookFlow,
    ):
        self.start = start_factory(
            s21_client=s21_client,
            bot_manager=bot_manager,
            booking_manager=booking_manager,
            messenger=messenger,
            category=FlowCategory.START,
        )
        self.stop = stop_factory(
            s21_client=s21_client,
            bot_manager=bot_manager,
            booking_manager=booking_manager,
            messenger=messenger,
            category=FlowCategory.STOP,
        )
        self.delete = delete_factory(
            s21_client=s21_client,
            bot_manager=bot_manager,
            booking_manager=booking_manager,
            messenger=messenger,
            category=FlowCategory.DELETE,
        )
        self.edit = edit_factory(
            s21_client=s21_client,
            bot_manager=bot_manager,
            booking_manager=booking_manager,
            messenger=messenger,
            category=FlowCategory.EDIT,
        )
        self.status = status_factory(
            s21_client=s21_client,
            bot_manager=bot_manager,
            booking_manager=booking_manager,
            messenger=messenger,
            category=FlowCategory.STATUS,
        )
        self.book = book_factory(
            s21_client=s21_client,
            bot_manager=bot_manager,
            booking_manager=booking_manager,
            messenger=messenger,
            category=FlowCategory.BOOK,
        )

        self._flow_map = {
            FlowCategory.START: self.start,
            FlowCategory.STOP: self.stop,
            FlowCategory.DELETE: self.delete,
            FlowCategory.EDIT: self.edit,
            FlowCategory.STATUS: self.status,
            FlowCategory.BOOK: self.book,
        }

    def get_flow(self, category: FlowCategory) -> Flow:
        if category not in self._flow_map:
            raise InvalidCallbackDataError(f"отсутствует категория {category}")
        flow = self._flow_map[category]
        return flow
