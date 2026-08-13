import asyncio
import json
from collections.abc import Awaitable
from datetime import datetime
from functools import cache, lru_cache
from http import HTTPStatus
from importlib.resources import files
from typing import Any, NoReturn

import aiohttp

from s21_slot_bot.client.config import S21ClientConfig
from s21_slot_bot.client.consts import (
    GRAPHQL_QUERIES_MODULE,
    GRAPHQL_URL,
    PLATFORM_URL,
    USER_ROLE,
    X_EDU_ORG_UNIT_ID,
    X_EDU_PRODUCT_ID,
)
from s21_slot_bot.client.errors import (
    School21Error,
    School21ErrorType,
    School21NoPointsError,
    School21ParsingError,
    School21SlotNotFoundError,
)
from s21_slot_bot.client.middleware import School21AuthMiddleware
from s21_slot_bot.client.models import (
    Booking,
    ContentType,
    OperationName,
    Project,
    ProjectStatus,
    ReviewInfo,
    SlotsInfo,
)
from s21_slot_bot.common.logger import LoggerLike
from s21_slot_bot.common.time import dt_to_isoz


class School21Client:
    def __init__(
        self,
        config: S21ClientConfig,
        auth_middleware: School21AuthMiddleware,
    ):
        self._timeout_sec = aiohttp.ClientTimeout(total=config.timeout_sec)
        self._auth_middleware = auth_middleware
        self._session_internal: aiohttp.ClientSession | None = None
        self._user_id: str | None = None
        self._student_id: str | None = None

    @property
    def _session(self) -> aiohttp.ClientSession:
        if not self._is_session_open:
            raise RuntimeError("School21Client не инициализирован")
        return self._session_internal

    @property
    def _is_session_open(self) -> bool:
        return self._session_internal is not None and not self._session_internal.closed

    async def start(self) -> None:
        if self._is_session_open:
            return
        self._session_internal = aiohttp.ClientSession(
            timeout=self._timeout_sec,
            middlewares=(self._auth_middleware,),
        )

    async def stop(self) -> None:
        if not self._is_session_open:
            await self._session_internal.close()

    async def get_user_and_student_id(self, logger: LoggerLike) -> tuple[str, str]:
        if self._user_id and self._student_id:
            return self._user_id, self._student_id

        operation_name = OperationName.GET_USER
        data = await self._graphql(operation_name, {}, logger)
        try:
            user_info = data["user"][operation_name]
            user_id, student_id = user_info["id"], user_info["currentSchoolStudentId"]
            self._user_id, self._student_id = user_id, student_id
            logger.info("User ID is `%s`", user_id)
            return user_id, student_id
        except Exception as e:
            self._raise_parsing_error(operation_name, e, data)

    async def get_reviewed_projects(self, user_id: str, logger: LoggerLike) -> list[Project]:
        operation_name = OperationName.GET_CUR_PROJECTS
        data = await self._graphql(operation_name, {"userId": user_id}, logger)
        try:
            projects: list[dict[str, Any]] = data["student"][operation_name]
            reviewed_projects: list[Project] = []
            course_ids: list[str] = []
            logger.info("Processing %d projects in review", len(projects))
            for raw_project in projects:
                project = Project.model_validate(raw_project)
                if project.course_status == ProjectStatus.IN_PROGRESS and project.course_id:
                    course_ids.append(project.course_id)
                elif project.status == ProjectStatus.P2P_EVALUATIONS:
                    reviewed_projects.append(project)
            grouped_course_projects = await asyncio.gather(
                *[self.get_local_course_goals(course_id, logger) for course_id in course_ids]
            )
            for course_projects in grouped_course_projects:
                reviewed_course_projects = list(
                    filter(lambda p: p.status == ProjectStatus.P2P_EVALUATIONS, course_projects)
                )
                reviewed_projects.extend(reviewed_course_projects)
            logger.info("Currently reviewed projects: %s", [project.name for project in reviewed_projects] or "None")
            return reviewed_projects
        except School21Error:
            raise
        except Exception as e:
            self._raise_parsing_error(operation_name, e, data)

    async def get_local_course_goals(self, course_id: str, logger: LoggerLike) -> list[Project]:
        operation_name = OperationName.GET_LOCAL_COURSE_GOALS
        data = await self._graphql(operation_name, {"localCourseId": course_id}, logger)
        try:
            course_goals: list[dict] = data["course"][operation_name]["localCourseGoals"]
            course_projects = [Project.model_validate(goal) for goal in course_goals]
            logger.info(
                "Local course projects for course_id `%s`: %s",
                course_id,
                [project.name for project in course_projects] or "None",
            )
            return course_projects
        except Exception as e:
            self._raise_parsing_error(operation_name, e, data)

    async def get_review_info(self, goal_id: str, student_id: str, logger: LoggerLike) -> ReviewInfo:
        operation_name = OperationName.GET_PROJECT_INFO
        data = await self._graphql(operation_name, {"goalId": goal_id, "studentId": student_id}, logger)
        try:
            raw_info = data["school21"]["getP2PChecksInfo"]["projectReviewsInfo"]
            review_info = ReviewInfo.model_validate(raw_info)
            logger.info("Project ID `%s`: %d / %d reviews", goal_id, review_info.booked, review_info.required)
            return review_info
        except Exception as e:
            self._raise_parsing_error(operation_name, e, data)

    async def get_task_and_answer(self, module_id: str, logger: LoggerLike) -> tuple[str, str]:
        operation_name = OperationName.GET_MODULE
        data = await self._graphql(operation_name, {"moduleId": module_id}, logger)
        try:
            cur = data["student"]["getModuleById"]["currentTask"]
            task_id, answer_id = cur["taskId"], cur["lastAnswer"]["id"]
            logger.info("Received task_id `%s` and answer_id `%s`", task_id, answer_id)
            return task_id, answer_id
        except Exception as e:
            self._raise_parsing_error(operation_name, e, data)

    async def get_slots_info(self, task_id: str, from_dt: datetime, to_dt: datetime, logger: LoggerLike) -> SlotsInfo:
        from_iso_z, to_iso_z = dt_to_isoz(from_dt), dt_to_isoz(to_dt)
        operation_name = OperationName.GET_SLOTS
        data = await self._graphql(operation_name, {"taskId": task_id, "from": from_iso_z, "to": to_iso_z}, logger)
        try:
            review_data = data["student"]["getNameLessStudentTimeslotsForReview"]
            slots_info = SlotsInfo.model_validate(review_data)
            logger.info("Received %d slots, %d booked", len(slots_info.time_slots), slots_info.review_info.booked)
            return slots_info
        except Exception as e:
            self._raise_parsing_error(operation_name, e, data)

    async def get_bookings(self, from_dt: datetime, to_dt: datetime, logger: LoggerLike) -> dict[str, Booking]:
        from_iso_z, to_iso_z = dt_to_isoz(from_dt), dt_to_isoz(to_dt)
        operation_name = OperationName.GET_BOOKINGS
        data = await self._graphql(operation_name, {"from": from_iso_z, "to": to_iso_z}, logger)
        try:
            raw_bookings: list[dict[str, Any]] = data["student"]["getMyCalendarBookings"]
            bookings = {raw["id"]: Booking.model_validate(raw) for raw in raw_bookings}
            logger.info("Received %d bookings: %s", len(bookings), bookings)
            return bookings
        except Exception as e:
            self._raise_parsing_error(operation_name, e, data)

    async def book(
        self,
        answer_id: str,
        start_time: datetime,
        logger: LoggerLike,
        is_staff_slot: bool = False,
        is_online: bool = True,
    ) -> str:
        start_time_iso_z = dt_to_isoz(start_time)
        operation_name = OperationName.BOOK
        data = await self._graphql(
            operation_name,
            {
                "answerId": answer_id,
                "startTime": start_time_iso_z,
                "wasStaffSlotChosen": is_staff_slot,
                "isOnline": is_online,
            },
            logger,
        )
        try:
            booking_id = data["student"]["addBookingP2PToEventSlot"]["id"]
            logger.info("Successfully booked a review, id `%s`", booking_id)
            return booking_id
        except Exception as e:
            self._raise_parsing_error(operation_name, e, data)

    async def _graphql(
        self,
        operation_name: OperationName,
        variables: dict[str, Any],
        logger: LoggerLike,
    ) -> dict[str, Any]:
        logger.info("Calling `%s` with variables `%s`", operation_name, variables)
        headers = {
            "Content-Type": ContentType.APPLICATION_JSON,
            "Accept": ContentType.APPLICATION_JSON,
            "userrole": USER_ROLE,
            "schoolid": X_EDU_ORG_UNIT_ID,
            "x-edu-org-unit-id": X_EDU_ORG_UNIT_ID,
            "x-edu-product-id": X_EDU_PRODUCT_ID,
            "Origin": PLATFORM_URL,
            "Referer": f"{PLATFORM_URL}/calendar",
        }
        query = _get_query(operation_name)
        payload = {
            "operationName": operation_name,
            "variables": variables,
            "query": query,
        }
        async with self._session.post(
            GRAPHQL_URL,
            json=payload,
            headers=headers,
        ) as resp:
            if not resp.ok:
                text = await resp.text()
                raise School21Error(
                    f"ошибка запроса к Школе 21 во время исполнения операции "
                    f"`{operation_name}`: `{resp.status} {resp.reason}`",
                    status=HTTPStatus(resp.status),
                    location={
                        "operation": operation_name,
                        "input": variables,
                        "response": text,
                    },
                )
            data = await resp.json()
            logger.debug(
                "Received response from operation `%s`: %s",
                operation_name,
                json.dumps(data, indent=2, ensure_ascii=False),
            )
            if errors := data.get("errors"):
                self._raise_error_from_response(
                    operation_name,
                    variables,
                    errors,
                )
            return data.get("data", {})

    def _raise_error_from_response(
        self, operation_name: str, variables: dict[str, Any], errors: list[dict[str, Any]]
    ) -> NoReturn:
        location = {"operation": operation_name, "input": variables, "errors": errors}
        for error in errors:
            error_type = error and error.get("extensions", {}).get("uiErrorCode")
            match error_type:
                case School21ErrorType.NO_P2P_POINTS:
                    raise School21NoPointsError("недостаточно P2P-пойнтов для записи на проверку", location=location)
                case School21ErrorType.SLOT_NOT_FOUND:
                    raise School21SlotNotFoundError("слот не найден", location=location)

        raise School21Error(
            "ошибка запроса к Школе 21",
            location=location,
        )

    def _raise_parsing_error(self, operation_name: str, error: Exception, data: dict[str, Any]) -> NoReturn:
        raise School21ParsingError(
            f"не удалось обработать ответ от операции {operation_name}, ошибка: `{error}`", location=data
        ) from error


@cache
def _get_query(operation_name: OperationName) -> str:
    graphql = files(GRAPHQL_QUERIES_MODULE).joinpath(f"{operation_name}.graphql").read_text(encoding="utf-8").strip()
    return graphql
