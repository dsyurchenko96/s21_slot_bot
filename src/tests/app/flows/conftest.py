from collections.abc import Callable

import pytest

from s21_slot_bot.app.booking_manager import BookingManager
from s21_slot_bot.app.bot_manager import BotManager
from s21_slot_bot.app.flows.book import BookFlow
from s21_slot_bot.app.flows.delete import DeleteFlow
from s21_slot_bot.app.flows.edit import EditFlow
from s21_slot_bot.app.flows.start import StartFlow
from s21_slot_bot.app.flows.status import StatusFlow
from s21_slot_bot.app.flows.stop import StopFlow
from s21_slot_bot.app.messenger import Messenger
from s21_slot_bot.app.models import FlowCategory
from s21_slot_bot.client.models import Project, ProjectExtended, ProjectStatus, ReviewInfo
from s21_slot_bot.client.s21_client import School21Client


@pytest.fixture
def project_factory() -> Callable[..., Project]:
    def factory(
        *,
        project_id: str = "project-1",
        name: str = "Project 1",
        status: ProjectStatus = ProjectStatus.P2P_EVALUATIONS,
        course_id: str | None = None,
        course_status: ProjectStatus | None = None,
    ) -> Project:
        return Project(
            id=project_id,
            name=name,
            status=status,
            course_id=course_id,
            course_status=course_status,
        )

    return factory


@pytest.fixture
def project_extended_factory() -> Callable[..., ProjectExtended]:
    def factory(
        *,
        project_id: str = "project-1",
        name: str = "Project 1",
        booked: int = 0,
        required: int = 3,
    ) -> ProjectExtended:
        return ProjectExtended(
            id=project_id,
            name=name,
            status=ProjectStatus.P2P_EVALUATIONS,
            review_info=ReviewInfo(required=required, booked=booked),
        )

    return factory


@pytest.fixture
def start_flow(
    s21_client_mock: School21Client,
    bot_manager_mock: BotManager,
    booking_manager_mock: BookingManager,
    messenger_mock: Messenger,
) -> StartFlow:
    return StartFlow(
        s21_client=s21_client_mock,
        bot_manager=bot_manager_mock,
        booking_manager=booking_manager_mock,
        messenger=messenger_mock,
        category=FlowCategory.START,
    )


@pytest.fixture
def stop_flow(
    s21_client_mock: School21Client,
    bot_manager_mock: BotManager,
    booking_manager_mock: BookingManager,
    messenger_mock: Messenger,
) -> StopFlow:
    return StopFlow(
        s21_client=s21_client_mock,
        bot_manager=bot_manager_mock,
        booking_manager=booking_manager_mock,
        messenger=messenger_mock,
        category=FlowCategory.STOP,
    )


@pytest.fixture
def delete_flow(
    s21_client_mock: School21Client,
    bot_manager_mock: BotManager,
    booking_manager_mock: BookingManager,
    messenger_mock: Messenger,
) -> DeleteFlow:
    return DeleteFlow(
        s21_client=s21_client_mock,
        bot_manager=bot_manager_mock,
        booking_manager=booking_manager_mock,
        messenger=messenger_mock,
        category=FlowCategory.DELETE,
    )


@pytest.fixture
def edit_flow(
    s21_client_mock: School21Client,
    bot_manager_mock: BotManager,
    booking_manager_mock: BookingManager,
    messenger_mock: Messenger,
) -> EditFlow:
    return EditFlow(
        s21_client=s21_client_mock,
        bot_manager=bot_manager_mock,
        booking_manager=booking_manager_mock,
        messenger=messenger_mock,
        category=FlowCategory.EDIT,
    )


@pytest.fixture
def status_flow(
    s21_client_mock: School21Client,
    bot_manager_mock: BotManager,
    booking_manager_mock: BookingManager,
    messenger_mock: Messenger,
) -> StatusFlow:
    return StatusFlow(
        s21_client=s21_client_mock,
        bot_manager=bot_manager_mock,
        booking_manager=booking_manager_mock,
        messenger=messenger_mock,
        category=FlowCategory.STATUS,
    )


@pytest.fixture
def book_flow(
    s21_client_mock: School21Client,
    bot_manager_mock: BotManager,
    booking_manager_mock: BookingManager,
    messenger_mock: Messenger,
) -> BookFlow:
    return BookFlow(
        s21_client=s21_client_mock,
        bot_manager=bot_manager_mock,
        booking_manager=booking_manager_mock,
        messenger=messenger_mock,
        category=FlowCategory.BOOK,
    )
