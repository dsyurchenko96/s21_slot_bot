import html
import json
import logging
import re
import time
import uuid
from http import HTTPStatus
from typing import Any
from urllib.parse import urljoin, urlparse, parse_qs

import requests

from s21_slot_bot.client.config import S21ClientConfig
from s21_slot_bot.client.consts import (
    AUTH_URL,
    REALM,
    CLIENT_ID,
    PLATFORM_URL,
    GRAPHQL_URL,
    X_EDU_ORG_UNIT_ID,
    X_EDU_PRODUCT_ID,
    USER_ROLE,
)
from s21_slot_bot.client.errors import School21Error
from s21_slot_bot.client.models import Tokens, ContentType, Project, ProjectStatus
from s21_slot_bot.client.queries import (
    Q_GET_MODULE,
    Q_GET_SLOTS,
    Q_BOOK,
    Q_GET_CUR_PROJECTS,
    Q_GET_USER,
    Q_GET_LOCAL_COURSE_GOALS,
)

logger = logging.getLogger(__name__)


class School21Client:
    def __init__(self, config: S21ClientConfig):
        self.username = config.username
        self.password = config.password.get_secret_value()
        self.timeout_sec = config.timeout_sec

        self.sess = requests.Session()
        self.tokens: Tokens | None = None
        self._user_id: str | None = None

    @property
    def user_id(self) -> str:
        if not self._user_id:
            self._user_id = self.get_user_id()
        return self._user_id

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

    def login(self) -> None:
        auth_resp = self.sess.get(self._auth_endpoint, timeout=self.timeout_sec)
        auth_resp.raise_for_status()

        action_url = self._extract_login_action(auth_resp.text, AUTH_URL)
        action_resp = self.sess.post(
            action_url,
            data={"username": self.username, "password": self.password},
            allow_redirects=True,
            timeout=self.timeout_sec,
        )

        code = self._extract_code_from_redirect_history(action_resp.history + [action_resp])
        if not code:
            raise School21Error("не смог извлечь code из редиректов (логин/пароль/2fa?)")

        token_resp = self.sess.post(
            self._token_endpoint,
            data={
                "code": code,
                "grant_type": "authorization_code",
                "client_id": CLIENT_ID,
                "redirect_uri": PLATFORM_URL,
            },
            headers={"Content-Type": ContentType.APPLICATION_FORM_URL_ENCODED},
            timeout=self.timeout_sec,
        )
        token_resp.raise_for_status()
        payload = token_resp.json()

        self._set_tokens_from_payload(payload)

    def get_user_id(self) -> str:
        data = self._graphql("getCurrentUser", Q_GET_USER, {})
        try:
            return data["user"]["getCurrentUser"]["id"]
        except Exception as e:
            raise self._formatted_error("не смог распарсить getCurrentUser", e, data)

    def get_reviewed_projects(self, user_id: str) -> list[Project]:
        data = self._graphql("getStudentCurrentProjects", Q_GET_CUR_PROJECTS, {"userId": user_id})
        try:
            projects = data["student"]["getStudentCurrentProjects"]
            reviewed_projects = []
            for project_dict in projects:
                project = Project(**project_dict)
                if project.status == ProjectStatus.IN_PROGRESS and project.course_id:
                    course_projects = self.get_local_course_goals(project.course_id)
                    course_reviewed_projects = list(
                        filter(lambda p: p.status == ProjectStatus.P2P_EVALUATIONS, course_projects)
                    )
                    reviewed_projects.extend(course_reviewed_projects)
                    continue
                if project.status == ProjectStatus.P2P_EVALUATIONS:
                    reviewed_projects.append(project)
            return reviewed_projects
        except Exception as e:
            raise self._formatted_error("не смог распарсить getStudentCurrentProjects", e, data)

    def get_local_course_goals(self, course_id: int) -> list[Project]:
        data = self._graphql("getLocalCourseGoals", Q_GET_LOCAL_COURSE_GOALS, {"localCourseId": str(course_id)})
        try:
            course_goals: list[dict] = data["course"]["getLocalCourseGoals"]["localCourseGoals"]
            course_projects = [Project(**goal) for goal in course_goals]
            return course_projects
        except Exception as e:
            raise self._formatted_error("не смог распарсить getLocalCourseGoals", e, data)

    def get_task_and_answer(self, module_id: str) -> tuple[str, str]:
        data = self._graphql("calendarGetModule", Q_GET_MODULE, {"moduleId": module_id})
        try:
            cur = data["student"]["getModuleById"]["currentTask"]
            return cur["taskId"], cur["lastAnswer"]["id"]
        except Exception as e:
            raise self._formatted_error("не смог распарсить calendarGetModule", e, data)

    def get_timeslots(self, task_id: str, from_iso_z: str, to_iso_z: str) -> tuple[list[dict[str, Any]], int]:
        data = self._graphql(
            "calendarGetNameLessStudentTimeslotsForReview",
            Q_GET_SLOTS,
            {"taskId": task_id, "from": from_iso_z, "to": to_iso_z},
        )
        try:
            review_data = data["student"]["getNameLessStudentTimeslotsForReview"]
            timeslots = review_data.get("timeSlots") or []
            booked = int(review_data["projectReviewsInfo"]["relevantReviewByStudentsCount"])
            return timeslots, booked
        except Exception as e:
            raise self._formatted_error("не смог распарсить calendarGetNameLessStudentTimeslotsForReview", e, data)

    def book(
        self,
        answer_id: str,
        start_time_iso_z: str,
        staff_slot: bool,
        is_online: bool = True,
    ) -> str:
        data = self._graphql(
            "calendarAddBookingToEventSlot",
            Q_BOOK,
            {
                "answerId": answer_id,
                "startTime": start_time_iso_z,
                "wasStaffSlotChosen": staff_slot,
                "isOnline": is_online,
            },
        )
        try:
            return data["student"]["addBookingP2PToEventSlot"]["id"]
        except Exception as e:
            raise self._formatted_error("не смог распарсить calendarAddBookingToEventSlot", e, data)

    def _graphql(self, operation_name: str, query: str, variables: dict[str, Any]) -> dict[str, Any]:
        self._refresh_if_needed()
        assert self.tokens is not None

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

        resp = self.sess.post(
            GRAPHQL_URL,
            json={
                "operationName": operation_name,
                "variables": variables,
                "query": query,
            },
            headers=headers,
            timeout=self.timeout_sec,
        )

        if resp.status_code in {HTTPStatus.UNAUTHORIZED, HTTPStatus.FORBIDDEN}:
            self.login()
            resp = self.sess.post(
                GRAPHQL_URL,
                json={
                    "operationName": operation_name,
                    "variables": variables,
                    "query": query,
                },
                headers=headers,
                timeout=self.timeout_sec,
            )

        resp.raise_for_status()
        data = resp.json()

        if data.get("errors"):
            raise School21Error(f"graphql errors: {data['errors']}")

        return data.get("data", {})

    def _refresh_if_needed(self) -> None:
        if not self.tokens or not self.tokens.refresh_token:
            self.login()
            return
        if time.time() < self.tokens.expires_at_epoch:
            return

        resp = self.sess.post(
            self._token_endpoint,
            data={
                "grant_type": "refresh_token",
                "client_id": CLIENT_ID,
                "refresh_token": self.tokens.refresh_token,
            },
            headers={"Content-Type": ContentType.APPLICATION_FORM_URL_ENCODED},
            timeout=self.timeout_sec,
        )
        if not resp.ok:
            self.login()
            return

        payload = resp.json()
        self._set_tokens_from_payload(payload)

    def _set_tokens_from_payload(self, payload: dict[str, Any]) -> None:
        access = payload["access_token"]
        refresh = payload.get("refresh_token", self.tokens.refresh_token if self.tokens else "")
        expires_in = float(payload.get("expires_in", 300))
        self.tokens = Tokens(
            access_token=access,
            refresh_token=refresh,
            expires_at_epoch=time.time() + expires_in,
        )
        self.sess.cookies.set("tokenId", access, domain="platform.21-school.ru", path="/")
        self.sess.cookies.set("tokenId", access, domain=".21-school.ru", path="/")

    def _extract_login_action(self, html_text: str, base_url: str) -> str:
        m = re.search(
            r'action\s*=\s*"([^"]*login-actions/authenticate[^"]*)"',
            html_text,
            flags=re.IGNORECASE,
        )
        if not m:
            raise School21Error("не смог найти login form action в HTML keycloak")
        return urljoin(base_url, html.unescape(m.group(1)))

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

    def _formatted_error(self, error_message: str, error: Exception, data: dict[str, Any]) -> School21Error:
        return School21Error(
            f"{error_message}:\n\nError: {error}\n\nData:\n{json.dumps(data, ensure_ascii=False, indent=4)}"
        )


def pick_candidate_start(timeslots: list[dict[str, Any]]) -> tuple[str, bool] | None:
    candidates: list[tuple[str, bool]] = []
    for slot in timeslots:
        staff = bool(slot.get("staffSlot", False))
        for t in slot.get("validStartTimes") or []:
            candidates.append((t, staff))
    if not candidates:
        return None
    candidates.sort(key=lambda x: x[0])
    return candidates[0]
