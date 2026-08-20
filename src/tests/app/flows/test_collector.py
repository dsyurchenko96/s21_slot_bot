import pytest

from s21_slot_bot.app.errors import InvalidCallbackDataError
from s21_slot_bot.app.flows.book import BookFlow
from s21_slot_bot.app.flows.collector import FlowCollector
from s21_slot_bot.app.flows.start import StartFlow
from s21_slot_bot.app.models import FlowCategory


class TestFlowCollector:
    def test_get_flow(
        self,
        flow_collector: FlowCollector,
        start_flow: StartFlow,
        book_flow: BookFlow,
    ) -> None:
        assert flow_collector.get_flow(FlowCategory.START) is start_flow
        assert flow_collector.get_flow(FlowCategory.BOOK) is book_flow

    def test_get_flow_rejects_missing_category(self, flow_collector: FlowCollector) -> None:
        flow_collector._flow_map.pop(FlowCategory.START)
        with pytest.raises(InvalidCallbackDataError):
            flow_collector.get_flow(FlowCategory.START)
