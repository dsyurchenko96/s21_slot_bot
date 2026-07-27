import html
import json
import re
import time
import uuid
from datetime import datetime, timedelta, tzinfo
from http import HTTPStatus
from typing import Any, NoReturn
from urllib.parse import parse_qs, urljoin, urlparse

# TODO: move to aiohttp?
import requests
from requests import HTTPError

from s21_slot_bot.client.config import S21ClientConfig
from s21_slot_bot.client.consts import (
    AUTH_URL,
    CLIENT_ID,
    GRAPHQL_URL,
    PLATFORM_URL,
    REALM,
    USER_ROLE,
    X_EDU_ORG_UNIT_ID,
    X_EDU_PRODUCT_ID,
)
from s21_slot_bot.client.errors import (
    School21Error,
    School21ErrorType,
    School21LoginError,
    School21NoPointsError,
    School21ParsingError,
    School21SlotNotFoundError,
)
from s21_slot_bot.client.models import (
    Booking,
    ContentType,
    Project,
    ProjectExtended,
    ProjectStatus,
    ReviewInfo,
    SlotsInfo,
    Tokens,
)
from s21_slot_bot.client.queries import (
    Q_BOOK,
    Q_GET_BOOKINGS,
    Q_GET_CUR_PROJECTS,
    Q_GET_LOCAL_COURSE_GOALS,
    Q_GET_MODULE,
    Q_GET_PROJECT_INFO,
    Q_GET_SLOTS,
    Q_GET_USER,
)
from s21_slot_bot.common.logger import LoggerLike
from s21_slot_bot.common.time import dt_to_isoz


class School21Client:
    def __init__(self, config: S21ClientConfig):
        self._username = config.username
        self._password = config.password
        self._timeout_sec = config.timeout_sec

        self._sess = requests.Session()
        self._tokens: Tokens | None = None
        self._user_id: str | None = None
        self._student_id: str | None = None

    @property
    def _token_endpoint(self) -> str:
        return f"{AUTH_URL}/auth/realms/{REALM}/protocol/openid-connect/token"

    @property
    def _auth_endpoint(self) -> str:
        state = str(uuid.uuid4())
        nonce = str(uuid.uuid4())
        return (
            f"{AUTH_URL}/auth/realms/{REALM}/protocol/openid-connect/auth"
            f"?client_id={CLIENT_ID}"
            f"&redirect_uri={requests.utils.quote(PLATFORM_URL, safe='')}"
            f"&state={state}"
            f"&response_mode=fragment"
            f"&response_type=code"
            f"&scope=openid"
            f"&nonce={nonce}"
        )

    def login(self, logger: LoggerLike) -> None:
        logger.info("Logging in")
        auth_resp = self._sess.get(self._auth_endpoint, timeout=self._timeout_sec)
        try:
            auth_resp.raise_for_status()
        except HTTPError as e:
            raise School21LoginError(f"ошибка авторизации: `{e}`", status=HTTPStatus(auth_resp.status_code)) from e

        action_url = self._extract_login_action(auth_resp.text, AUTH_URL)
        action_resp = self._sess.post(
            action_url,
            data={"username": self._username, "password": self._password.get_secret_value()},
            allow_redirects=True,
            timeout=self._timeout_sec,
        )

        code = self._extract_code_from_redirect_history(action_resp.history + [action_resp])
        if not code:
            raise School21LoginError("не удалось извлечь код авторизации", status=HTTPStatus(auth_resp.status_code))

        token_resp = self._sess.post(
            self._token_endpoint,
            data={
                "code": code,
                "grant_type": "authorization_code",
                "client_id": CLIENT_ID,
                "redirect_uri": PLATFORM_URL,
            },
            headers={"Content-Type": ContentType.APPLICATION_FORM_URL_ENCODED},
            timeout=self._timeout_sec,
        )
        try:
            token_resp.raise_for_status()
        except HTTPError as e:
            raise School21LoginError(
                f"ошибка при запросе токена: `{e}`", status=HTTPStatus(token_resp.status_code)
            ) from e

        payload = token_resp.json()

        self._set_tokens_from_payload(payload)

    def get_user_and_student_id(self, logger: LoggerLike) -> tuple[str, str]:
        if self._user_id and self._student_id:
            return self._user_id, self._student_id

        operation_name = "getCurrentUser"
        data = self._graphql(operation_name, Q_GET_USER, {}, logger)
        try:
            user_info = data["user"][operation_name]
            user_id, student_id = user_info["id"], user_info["currentSchoolStudentId"]
            self._user_id, self._student_id = user_id, student_id
            logger.info("User ID is `%s`", user_id)
            return user_id, student_id
        except Exception as e:
            self._raise_parsing_error(operation_name, e, data)

    def get_reviewed_projects(self, user_id: str, logger: LoggerLike) -> list[Project]:
        operation_name = "getStudentCurrentProjects"
        data = self._graphql(operation_name, Q_GET_CUR_PROJECTS, {"userId": user_id}, logger)
        try:
            projects: list[dict[str, Any]] = data["student"][operation_name]
            reviewed_projects: list[Project] = []
            logger.info("Processing %d projects in review", len(projects))
            for raw_project in projects:
                project = Project.model_validate(raw_project)
                if project.status == ProjectStatus.IN_PROGRESS and project.course_id:
                    course_projects = self.get_local_course_goals(project.course_id, logger)
                    course_reviewed_projects = list(
                        filter(lambda p: p.status == ProjectStatus.P2P_EVALUATIONS, course_projects)
                    )
                    reviewed_projects.extend(course_reviewed_projects)
                    continue
                if project.status == ProjectStatus.P2P_EVALUATIONS:
                    reviewed_projects.append(project)
            logger.info("Currently reviewed projects: %s", [project.name for project in reviewed_projects] or "None")
            return reviewed_projects
        except School21Error:
            raise
        except Exception as e:
            self._raise_parsing_error(operation_name, e, data)

    def get_local_course_goals(self, course_id: str, logger: LoggerLike) -> list[Project]:
        operation_name = "getLocalCourseGoals"
        data = self._graphql(operation_name, Q_GET_LOCAL_COURSE_GOALS, {"localCourseId": course_id}, logger)
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

    def get_review_info(self, goal_id: str, student_id: str, logger: LoggerLike) -> ReviewInfo:
        operation_name = "getProjectInfo"
        data = self._graphql(operation_name, Q_GET_PROJECT_INFO, {"goalId": goal_id, "studentId": student_id}, logger)
        try:
            raw_info = data["school21"]["getP2PChecksInfo"]["projectReviewsInfo"]
            review_info = ReviewInfo.model_validate(raw_info)
            logger.info("Project ID `%s`: %d / %d reviews", goal_id, review_info.booked, review_info.required)
            return review_info
        except Exception as e:
            self._raise_parsing_error(operation_name, e, data)

    def get_task_and_answer(self, module_id: str, logger: LoggerLike) -> tuple[str, str]:
        operation_name = "calendarGetModule"
        data = self._graphql(operation_name, Q_GET_MODULE, {"moduleId": module_id}, logger)
        try:
            cur = data["student"]["getModuleById"]["currentTask"]
            task_id, answer_id = cur["taskId"], cur["lastAnswer"]["id"]
            logger.info("Received task_id `%s` and answer_id `%s`", task_id, answer_id)
            return task_id, answer_id
        except Exception as e:
            self._raise_parsing_error(operation_name, e, data)

    def get_slots_info(self, task_id: str, from_dt: datetime, to_dt: datetime, logger: LoggerLike) -> SlotsInfo:
        from_iso_z, to_iso_z = dt_to_isoz(from_dt), dt_to_isoz(to_dt)
        operation_name = "calendarGetNameLessStudentTimeslotsForReview"
        data = self._graphql(
            operation_name, Q_GET_SLOTS, {"taskId": task_id, "from": from_iso_z, "to": to_iso_z}, logger
        )
        try:
            review_data = data["student"]["getNameLessStudentTimeslotsForReview"]
            slots_info = SlotsInfo.model_validate(review_data)
            logger.info("Received %d slots, %d booked", len(slots_info.time_slots), slots_info.review_info.booked)
            return slots_info
        except Exception as e:
            self._raise_parsing_error(operation_name, e, data)

    def get_bookings(self, from_dt: datetime, to_dt: datetime, logger: LoggerLike) -> dict[str, Booking]:
        from_iso_z, to_iso_z = dt_to_isoz(from_dt), dt_to_isoz(to_dt)
        operation_name = "calendarGetMyBookings"
        data = self._graphql(operation_name, Q_GET_BOOKINGS, {"from": from_iso_z, "to": to_iso_z}, logger)
        try:
            raw_bookings: list[dict[str, Any]] = data["student"]["getMyCalendarBookings"]
            bookings = {raw["id"]: Booking.model_validate(raw) for raw in raw_bookings}
            logger.info("Received %d bookings: %s", len(bookings), bookings)
            return bookings
        except Exception as e:
            self._raise_parsing_error(operation_name, e, data)

    def book(
        self,
        answer_id: str,
        start_time: datetime,
        logger: LoggerLike,
        is_staff_slot: bool = False,
        is_online: bool = True,
    ) -> str:
        start_time_iso_z = dt_to_isoz(start_time)
        operation_name = "calendarAddBookingToEventSlot"
        data = self._graphql(
            operation_name,
            Q_BOOK,
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

    def _graphql(
        self, operation_name: str, query: str, variables: dict[str, Any], logger: LoggerLike
    ) -> dict[str, Any]:
        logger.info("Calling `%s` with variables `%s`", operation_name, variables)
        self._refresh_if_needed(logger)

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

        resp = self._sess.post(
            GRAPHQL_URL,
            json={
                "operationName": operation_name,
                "variables": variables,
                "query": query,
            },
            headers=headers,
            timeout=self._timeout_sec,
        )

        if resp.status_code in {HTTPStatus.UNAUTHORIZED, HTTPStatus.FORBIDDEN}:
            self.login(logger)
            resp = self._sess.post(
                GRAPHQL_URL,
                json={
                    "operationName": operation_name,
                    "variables": variables,
                    "query": query,
                },
                headers=headers,
                timeout=self._timeout_sec,
            )

        try:
            resp.raise_for_status()
        except HTTPError as e:
            raise School21Error(
                f"ошибка запроса к Школе 21 во время исполнения операции `{operation_name}`: `{e}`",
                status=HTTPStatus(resp.status_code),
                location={"operation": operation_name, "input": variables},
            ) from e

        data = resp.json()
        logger.debug(
            "Received response from operation `%s`: %s",
            operation_name,
            json.dumps(data, indent=2, ensure_ascii=False),
        )

        if errors := data.get("errors"):
            self._raise_error_from_response(operation_name, variables, errors)

        return data.get("data", {})

    def _refresh_if_needed(self, logger: LoggerLike) -> None:
        if not self._tokens or not self._tokens.refresh_token:
            self.login(logger)
            return
        if time.time() < self._tokens.expires_at_epoch:
            return

        resp = self._sess.post(
            self._token_endpoint,
            data={
                "grant_type": "refresh_token",
                "client_id": CLIENT_ID,
                "refresh_token": self._tokens.refresh_token,
            },
            headers={"Content-Type": ContentType.APPLICATION_FORM_URL_ENCODED},
            timeout=self._timeout_sec,
        )
        if not resp.ok:
            logger.warning("Failed to login with status %d, trying again...", resp.status_code)
            self.login(logger)
            return

        payload = resp.json()
        self._set_tokens_from_payload(payload)

    def _set_tokens_from_payload(self, payload: dict[str, Any]) -> None:
        access = payload["access_token"]
        refresh = payload.get("refresh_token", self._tokens.refresh_token if self._tokens else "")
        expires_in = float(payload.get("expires_in", 300))
        self._tokens = Tokens(
            access_token=access,
            refresh_token=refresh,
            expires_at_epoch=time.time() + expires_in,
        )
        self._sess.cookies.set("tokenId", access, domain="platform.21-school.ru", path="/")
        self._sess.cookies.set("tokenId", access, domain=".21-school.ru", path="/")

    def _extract_login_action(self, html_text: str, base_url: str) -> str:
        match = re.search(
            r'action\s*=\s*"([^"]*login-actions/authenticate[^"]*)"',
            html_text,
            flags=re.IGNORECASE,
        )
        if not match:
            raise School21LoginError("не удалось извлечь информацию для авторизации")
        return urljoin(base_url, html.unescape(match.group(1)))

    def _extract_code_from_redirect_history(self, history: list[requests.Response]) -> str | None:
        for resp in reversed(history):
            loc = resp.headers.get("Location") or resp.headers.get("location")
            if not loc or "code=" not in loc:
                continue
            u = urlparse(loc)
            if not u.fragment:
                continue
            qs = parse_qs(u.fragment)
            code = (qs.get("code") or [None])[0]
            if code:
                return code
        return None

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
