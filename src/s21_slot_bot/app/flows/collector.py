from s21_slot_bot.app.bot_manager import BotManager
from s21_slot_bot.app.flows.base import Flow
from s21_slot_bot.app.flows.edit import EditFlow
from s21_slot_bot.app.flows.start import StartFlow
from s21_slot_bot.app.flows.status import StatusFlow
from s21_slot_bot.app.flows.stop import StopFlow
from s21_slot_bot.app.messenger import Messenger
from s21_slot_bot.app.models import FlowCategory
from s21_slot_bot.client.s21_client import School21Client
from s21_slot_bot.common.exceptions import InvalidCallbackDataError


class FlowCollector:
    def __init__(
        self,
        s21_client: School21Client,
        bot_manager: BotManager,
        messenger: Messenger,
        start_factory: type[StartFlow] = StartFlow,
        stop_factory: type[StopFlow] = StopFlow,
        edit_factory: type[EditFlow] = EditFlow,
        status_factory: type[StatusFlow] = StatusFlow,
    ):
        self.start = start_factory(s21_client=s21_client, bot_manager=bot_manager, messenger=messenger)
        self.stop = stop_factory(s21_client=s21_client, bot_manager=bot_manager, messenger=messenger)
        self.edit = edit_factory(s21_client=s21_client, bot_manager=bot_manager, messenger=messenger)
        self.status = status_factory(s21_client=s21_client, bot_manager=bot_manager, messenger=messenger)

        self._flow_map = {
            FlowCategory.START: self.start,
            FlowCategory.STOP: self.stop,
            FlowCategory.EDIT: self.edit,
            FlowCategory.STATUS: self.status,
        }

    def get_flow(self, category: FlowCategory) -> Flow:
        if category not in self._flow_map:
            raise InvalidCallbackDataError
        flow = self._flow_map[category]
        return flow
