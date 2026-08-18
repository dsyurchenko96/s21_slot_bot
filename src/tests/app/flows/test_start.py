from collections.abc import Callable
from datetime import datetime, timedelta
from unittest.mock import AsyncMock, patch

import pytest
from telegram import CallbackQuery, Update

from s21_slot_bot.app.bot_manager import BotManager
from s21_slot_bot.app.errors import InvalidUserInputError, MenuError
from s21_slot_bot.app.flows.actions import InputFlowAction
from s21_slot_bot.app.flows.start import StartFlow
from s21_slot_bot.app.messenger import Messenger
from s21_slot_bot.app.models import BotInstance, CustomContext, Mode
from s21_slot_bot.client.consts import MIN_REQUIRED_REVIEWS
from s21_slot_bot.client.errors import School21Error
from s21_slot_bot.client.models import Project, ProjectExtended, ReviewInfo
from s21_slot_bot.client.s21_client import School21Client


class TestStartFlow:
    async def test_list_projects_renders_empty_state(
        self,
        start_flow: StartFlow,
        s21_client_mock: School21Client,
        bot_manager_mock: BotManager,
        messenger_mock: Messenger,
        update_mock: Update,
        context: CustomContext,
    ) -> None:
        s21_client_mock.get_user_and_student_id = AsyncMock(return_value=("user-1", "student-1"))
        s21_client_mock.get_reviewed_projects = AsyncMock(return_value=[])

        await start_flow.list_projects(update_mock, context)

        bot_manager_mock.check_bot_limits.assert_called_once_with()
        assert "нет активных проектов" in messenger_mock.render_menu_message.await_args.args[1]

    async def test_list_projects_auto_selects_single_project(
        self,
        start_flow: StartFlow,
        s21_client_mock: School21Client,
        update_mock: Update,
        context: CustomContext,
        project_factory: Callable[..., Project],
    ) -> None:
        project = project_factory(project_id="project-1")
        review_info = ReviewInfo(required=3, booked=1)
        s21_client_mock.get_user_and_student_id = AsyncMock(return_value=("user-1", "student-1"))
        s21_client_mock.get_reviewed_projects = AsyncMock(return_value=[project])
        s21_client_mock.get_review_info = AsyncMock(return_value=review_info)
        start_flow.pick_mode = AsyncMock()

        await start_flow.list_projects(update_mock, context)

        assert context.ensured_chat_data.start_project_id == "project-1"
        assert context.ensured_chat_data.projects_map["project-1"].review_info == review_info
        start_flow.pick_mode.assert_awaited_once_with(update_mock, context)

    async def test_list_projects_renders_multiple_projects(
        self,
        start_flow: StartFlow,
        s21_client_mock: School21Client,
        messenger_mock: Messenger,
        update_mock: Update,
        context: CustomContext,
        project_factory: Callable[..., Project],
    ) -> None:
        projects = [
            project_factory(project_id="project-1", name="One"),
            project_factory(project_id="project-2", name="Two"),
        ]
        s21_client_mock.get_user_and_student_id = AsyncMock(return_value=("user-1", "student-1"))
        s21_client_mock.get_reviewed_projects = AsyncMock(return_value=projects)
        s21_client_mock.get_review_info = AsyncMock(
            side_effect=[
                ReviewInfo(required=3, booked=1),
                ReviewInfo(required=2, booked=0),
            ]
        )

        await start_flow.list_projects(update_mock, context)

        assert set(context.ensured_chat_data.projects_map) == {"project-1", "project-2"}
        assert messenger_mock.render_menu_message.await_args.args[1] == "выбери проект:"

    async def test_list_projects_wraps_school21_error(
        self,
        start_flow: StartFlow,
        s21_client_mock: School21Client,
        update_mock: Update,
        context: CustomContext,
    ) -> None:
        s21_client_mock.get_user_and_student_id = AsyncMock(side_effect=School21Error("backend failed"))

        with pytest.raises(MenuError, match="не удалось получить проекты"):
            await start_flow.list_projects(update_mock, context)

    async def test_parse_callback_only_find_sets_min_reviews(
        self,
        start_flow: StartFlow,
        query_mock: CallbackQuery,
        context: CustomContext,
    ) -> None:
        start_flow.pick_from = AsyncMock()

        await start_flow.parse_callback(
            [Mode.ONLY_FIND, InputFlowAction.PICK_MODE],
            query_mock,
            context,
        )

        assert context.ensured_chat_data.start_mode == Mode.ONLY_FIND
        assert context.ensured_chat_data.start_required_reviews == MIN_REQUIRED_REVIEWS
        start_flow.pick_from.assert_awaited_once_with(query_mock, context)

    async def test_custom_to_rejects_time_before_start(
        self,
        start_flow: StartFlow,
        update_mock: Update,
        context: CustomContext,
        now: datetime,
    ) -> None:
        context.ensured_chat_data.start_from = now
        update_mock.message.text = "18:00"

        with pytest.raises(InvalidUserInputError):
            await start_flow.custom_to(update_mock, context)

    async def test_finalize_starts_bot_with_selected_parameters(
        self,
        start_flow: StartFlow,
        bot_manager_mock: BotManager,
        messenger_mock: Messenger,
        update_mock: Update,
        context: CustomContext,
        now: datetime,
        project_extended_factory: Callable[..., ProjectExtended],
    ) -> None:
        project = project_extended_factory(project_id="project-1", name="Project")
        context.ensured_chat_data.projects_map = {"project-1": project}
        context.ensured_chat_data.start_project_id = "project-1"
        context.ensured_chat_data.start_required_reviews = 2
        context.ensured_chat_data.start_from = now
        context.ensured_chat_data.start_to = now + timedelta(hours=2)
        context.ensured_chat_data.start_mode = Mode.FIND_AND_BOOK
        bot_manager_mock.poll_interval_sec = 60

        with patch("s21_slot_bot.app.flows.start.random_id", return_value="bot-1"):
            await start_flow.finalize(update_mock, context)

        bot_manager_mock.check_bot_limits.assert_called_once_with()
        inst = bot_manager_mock.start_bot.await_args.args[0]
        assert isinstance(inst, BotInstance)
        assert inst.cfg.bot_id == "bot-1"
        assert inst.cfg.project_id == "project-1"
        assert inst.cfg.required_reviews == 2
        assert inst.cfg.mode == Mode.FIND_AND_BOOK
        messenger_mock.render_menu_message.assert_awaited_once()
