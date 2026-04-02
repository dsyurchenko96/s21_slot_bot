from s21_slot_bot.app.bot_manager import BotManager
from s21_slot_bot.app.exceptions import InvalidCallbackData
from s21_slot_bot.app.flows.base import Flow
from s21_slot_bot.app.flows.edit import EditFlow
from s21_slot_bot.app.flows.settings import SettingsFlow
from s21_slot_bot.app.flows.start import StartFlow
from s21_slot_bot.app.flows.status import StatusFlow
from s21_slot_bot.app.flows.stop import StopFlow
from s21_slot_bot.app.models import FlowCategory
from s21_slot_bot.client.s21_client import School21Client


class FlowCollector:
    def __init__(
        self,
        s21_client: School21Client,
        bot_manager: BotManager,
        start_factory: type[StartFlow] = StartFlow,
        stop_factory: type[StopFlow] = StopFlow,
        edit_factory: type[EditFlow] = EditFlow,
        status_factory: type[StatusFlow] = StatusFlow,
        settings_factory: type[SettingsFlow] = SettingsFlow,
    ):
        self.start = start_factory(s21_client=s21_client, bot_manager=bot_manager)
        self.stop = stop_factory(s21_client=s21_client, bot_manager=bot_manager)
        self.edit = edit_factory(s21_client=s21_client, bot_manager=bot_manager)
        self.status = status_factory(s21_client=s21_client, bot_manager=bot_manager)
        self.settings = settings_factory(s21_client=s21_client, bot_manager=bot_manager)

        self._flow_map = {
            FlowCategory.START: self.start,
            FlowCategory.STOP: self.stop,
            FlowCategory.EDIT: self.edit,
            FlowCategory.STATUS: self.status,
            FlowCategory.SETTINGS: self.settings,
        }

    def get_flow(self, category: FlowCategory) -> Flow:
        if category not in self._flow_map:
            raise InvalidCallbackData
        flow = self._flow_map[category]
        return flow
