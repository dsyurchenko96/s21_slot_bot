from datetime import datetime, timedelta
from http import HTTPStatus
from unittest.mock import AsyncMock, MagicMock

import aiohttp
import pytest

from s21_slot_bot.client.errors import (
    School21Error,
    School21NoPointsError,
    School21ParsingError,
    School21SlotNotFoundError,
)
from s21_slot_bot.client.models import OperationName, Project, ProjectStatus
from s21_slot_bot.client.s21_client import School21Client
from s21_slot_bot.common.logger import LoggerLike


class TestSchool21Client:
    async def test_get_user_and_student_id_caches_result(
        self,
        s21_client: School21Client,
        logger_mock: LoggerLike,
    ) -> None:
        s21_client._graphql = AsyncMock(
            return_value={
                "user": {
                    OperationName.GET_USER: {
                        "id": "user-1",
                        "currentSchoolStudentId": "student-1",
                    }
                }
            }
        )

        first = await s21_client.get_user_and_student_id(logger_mock)
        second = await s21_client.get_user_and_student_id(logger_mock)

        assert first == ("user-1", "student-1")
        assert second == first
        s21_client._graphql.assert_awaited_once_with(OperationName.GET_USER, {}, logger_mock)

    async def test_get_user_and_student_id_wraps_invalid_response(
        self,
        s21_client: School21Client,
        logger_mock: LoggerLike,
    ) -> None:
        s21_client._graphql = AsyncMock(return_value={"user": {}})

        with pytest.raises(School21ParsingError):
            await s21_client.get_user_and_student_id(logger_mock)

    async def test_get_reviewed_projects_filters_projects_and_course_goals(
        self,
        s21_client: School21Client,
        logger_mock: LoggerLike,
    ) -> None:
        s21_client._graphql = AsyncMock(
            return_value={
                "student": {
                    OperationName.GET_CUR_PROJECTS: [
                        {
                            "goalId": "direct-1",
                            "goalName": "Direct review",
                            "goalStatus": "P2P_EVALUATIONS",
                        },
                        {
                            "goalId": "course-wrapper",
                            "goalName": "Course",
                            "displayedCourseStatus": "IN_PROGRESS",
                            "localCourseId": "course-1",
                        },
                        {
                            "goalId": "completed",
                            "goalName": "Completed",
                            "goalStatus": "COMPLETED",
                        },
                    ]
                }
            }
        )
        s21_client.get_local_course_goals = AsyncMock(
            return_value=[
                Project(id="nested-1", name="Nested review", status=ProjectStatus.P2P_EVALUATIONS),
                Project(id="nested-2", name="Nested done", status=ProjectStatus.COMPLETED),
            ]
        )

        projects = await s21_client.get_reviewed_projects("user-1", logger_mock)

        assert [project.id for project in projects] == ["direct-1", "nested-1"]
        s21_client.get_local_course_goals.assert_awaited_once_with("course-1", logger_mock)

    async def test_get_reviewed_projects_fetches_multiple_courses(
        self,
        s21_client: School21Client,
        logger_mock: LoggerLike,
    ) -> None:
        s21_client._graphql = AsyncMock(
            return_value={
                "student": {
                    OperationName.GET_CUR_PROJECTS: [
                        {
                            "goalName": "Course 1",
                            "displayedCourseStatus": "IN_PROGRESS",
                            "localCourseId": "course-1",
                        },
                        {
                            "goalName": "Course 2",
                            "displayedCourseStatus": "IN_PROGRESS",
                            "localCourseId": "course-2",
                        },
                    ]
                }
            }
        )
        s21_client.get_local_course_goals = AsyncMock(
            side_effect=[
                [Project(id="p1", name="P1", status=ProjectStatus.P2P_EVALUATIONS)],
                [Project(id="p2", name="P2", status=ProjectStatus.P2P_EVALUATIONS)],
            ]
        )

        projects = await s21_client.get_reviewed_projects("user-1", logger_mock)

        assert {project.id for project in projects} == {"p1", "p2"}
        assert s21_client.get_local_course_goals.await_count == 2

    async def test_get_task_and_answer(
        self,
        s21_client: School21Client,
        logger_mock: LoggerLike,
    ) -> None:
        s21_client._graphql = AsyncMock(
            return_value={
                "student": {
                    "getModuleById": {
                        "currentTask": {
                            "taskId": "task-1",
                            "lastAnswer": {"id": "answer-1"},
                        }
                    }
                }
            }
        )

        result = await s21_client.get_task_and_answer("module-1", logger_mock)

        assert result == ("task-1", "answer-1")

    async def test_get_slots_info(
        self,
        s21_client: School21Client,
        logger_mock: LoggerLike,
        now: datetime,
    ) -> None:
        end = now + timedelta(hours=2)
        s21_client._graphql = AsyncMock(
            return_value={
                "student": {
                    "getNameLessStudentTimeslotsForReview": {
                        "checkDuration": 45,
                        "projectReviewsInfo": {
                            "reviewByStudentCount": 3,
                            "relevantReviewByStudentsCount": 1,
                        },
                        "timeSlots": [
                            {
                                "start": now.isoformat(),
                                "end": end.isoformat(),
                                "validStartTimes": [now.isoformat()],
                                "staffSlot": False,
                            }
                        ],
                    }
                }
            }
        )

        info = await s21_client.get_slots_info("task-1", now, end, logger_mock)

        assert info.check_duration == 45
        assert info.review_info.required == 3
        assert info.review_info.booked == 1
        assert info.time_slots[0].start == now

    async def test_get_bookings(
        self,
        s21_client: School21Client,
        logger_mock: LoggerLike,
        now: datetime,
    ) -> None:
        end = now + timedelta(hours=2)
        s21_client._graphql = AsyncMock(
            return_value={
                "student": {
                    "getMyCalendarBookings": [
                        {
                            "id": "booking-1",
                            "answerId": "answer-1",
                            "task": {
                                "goalId": "project-1",
                                "goalName": "Project",
                            },
                            "eventSlot": {
                                "start": now.isoformat(),
                            },
                        }
                    ]
                }
            }
        )

        bookings = await s21_client.get_bookings(now, end, logger_mock)

        assert set(bookings) == {"booking-1"}
        assert bookings["booking-1"].project_id == "project-1"

    async def test_book_disables_retry_middleware(
        self,
        s21_client: School21Client,
        logger_mock: LoggerLike,
        now: datetime,
    ) -> None:
        s21_client._graphql = AsyncMock(
            return_value={
                "student": {
                    "addBookingP2PToEventSlot": {
                        "id": "booking-1",
                    }
                }
            }
        )

        booking_id = await s21_client.book(
            answer_id="answer-1",
            start_time=now,
            logger=logger_mock,
            is_staff_slot=True,
            is_online=False,
        )

        assert booking_id == "booking-1"
        call = s21_client._graphql.await_args
        assert call.args[0] == OperationName.BOOK
        assert call.args[1] == {
            "answerId": "answer-1",
            "startTime": "2026-08-16T15:30:15.000Z",
            "wasStaffSlotChosen": True,
            "isOnline": False,
        }
        assert call.kwargs["overridden_middleware"] == (s21_client._auth_middleware,)

    @pytest.mark.parametrize(
        ("error_code", "expected_error"),
        [
            (
                "TEAM_MEMBER_HAS_NOT_ENOUGH_PEER_REVIEW_POINTS",
                School21NoPointsError,
            ),
            (
                "TIMETABLE_TIMESLOTS_NOT_FOUND",
                School21SlotNotFoundError,
            ),
            (
                "SOMETHING_ELSE",
                School21Error,
            ),
        ],
    )
    def test_raise_error_from_response(
        self,
        s21_client: School21Client,
        error_code: str,
        expected_error: type[School21Error],
    ) -> None:
        errors = [{"extensions": {"uiErrorCode": error_code}}]

        with pytest.raises(expected_error) as raised:
            s21_client._raise_error_from_response(
                OperationName.BOOK,
                {"answerId": "a"},
                errors,
            )

        assert raised.value.location is not None

    async def test_graphql_raises_on_http_error(
        self,
        s21_client: School21Client,
        logger_mock: LoggerLike,
        session: aiohttp.ClientSession,
        response_mock: aiohttp.ClientResponse,
    ) -> None:
        response_mock.ok = False
        response_mock.status = HTTPStatus.BAD_GATEWAY
        response_mock.reason = "Bad Gateway"
        response_mock.text = AsyncMock(return_value="upstream failed")

        request_context = MagicMock()
        request_context.__aenter__ = AsyncMock(return_value=response_mock)
        session.post.return_value = request_context
        s21_client._session_internal = session

        with pytest.raises(School21Error) as raised:
            await s21_client._graphql(OperationName.GET_USER, {}, logger_mock)

        assert raised.value.effective_status == HTTPStatus.BAD_GATEWAY

    async def test_graphql_raises_typed_graphql_error(
        self,
        s21_client: School21Client,
        logger_mock: LoggerLike,
        session: aiohttp.ClientSession,
        response_mock: aiohttp.ClientResponse,
    ) -> None:
        response_mock.ok = True
        response_mock.json = AsyncMock(
            return_value={
                "errors": [
                    {
                        "extensions": {
                            "uiErrorCode": "TIMETABLE_TIMESLOTS_NOT_FOUND",
                        }
                    }
                ]
            }
        )

        request_context = MagicMock()
        request_context.__aenter__ = AsyncMock(return_value=response_mock)
        session.post.return_value = request_context
        s21_client._session_internal = session

        with pytest.raises(School21SlotNotFoundError):
            await s21_client._graphql(OperationName.GET_SLOTS, {}, logger_mock)

    async def test_graphql_returns_data(
        self,
        s21_client: School21Client,
        logger_mock: LoggerLike,
        session: aiohttp.ClientSession,
        response_mock: aiohttp.ClientResponse,
    ) -> None:
        expected = {"user": {"value": 1}}
        response_mock.ok = True
        response_mock.json = AsyncMock(return_value={"data": expected})

        request_context = MagicMock()
        request_context.__aenter__ = AsyncMock(return_value=response_mock)
        session.post.return_value = request_context
        s21_client._session_internal = session

        actual = await s21_client._graphql(OperationName.GET_USER, {}, logger_mock)

        assert actual == expected
        _, kwargs = session.post.call_args
        assert kwargs["json"]["operationName"] == OperationName.GET_USER
        assert kwargs["json"]["variables"] == {}
        assert kwargs["json"]["query"]
        assert kwargs["middlewares"] is None
