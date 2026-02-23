import html
import logging
import re
import time
import uuid
from http import HTTPStatus
from typing import Any
from urllib.parse import urljoin, urlparse, parse_qs

import requests

from client.consts import (
    AUTH_URL,
    REALM,
    CLIENT_ID,
    PLATFORM_URL,
    GRAPHQL_URL,
    X_EDU_ORG_UNIT_ID,
    X_EDU_PRODUCT_ID,
    USER_ROLE,
)
from client.errors import School21Error
from client.models import Tokens, ContentType
from client.queries import (
    Q_GET_MODULE,
    Q_GET_SLOTS,
    Q_BOOK,
    Q_GET_CUR_PROJECTS,
    Q_GET_USER,
)

logger = logging.getLogger(__name__)


def _extract_login_action(html_text: str, base_url: str) -> str:
    m = re.search(
        r'action\s*=\s*"([^"]*login-actions/authenticate[^"]*)"',
        html_text,
        flags=re.IGNORECASE,
    )
    if not m:
        raise School21Error("не смог найти login form action в HTML keycloak")
    return urljoin(base_url, html.unescape(m.group(1)))


def _extract_code_from_redirect_history(history: list[requests.Response]) -> str | None:
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


class School21Client:
    def __init__(
        self,
        username: str,
        password: str,
        timeout_sec: int = 25,
    ):
        self.username = username
        self.password = password
        self.timeout_sec = timeout_sec

        self.sess = requests.Session()
        self.tokens: Tokens | None = None

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
        r = self.sess.get(self._auth_endpoint, timeout=self.timeout_sec)
        r.raise_for_status()

        action_url = _extract_login_action(r.text, AUTH_URL)
        r2 = self.sess.post(
            action_url,
            data={"username": self.username, "password": self.password},
            allow_redirects=True,
            timeout=self.timeout_sec,
        )

        code = _extract_code_from_redirect_history(r2.history + [r2])
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

        access = payload["access_token"]
        refresh = payload.get("refresh_token", "")
        expires_in = float(payload.get("expires_in", 300))
        self.tokens = Tokens(
            access_token=access,
            refresh_token=refresh,
            expires_at_epoch=time.time() + expires_in - 20,
        )
        self._set_token_cookie(access)

    def graphql(self, operation_name: str, query: str, variables: dict[str, Any]) -> dict[str, Any]:
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

    def get_user_id(self) -> str:
        data = self.graphql("getCurrentUser", Q_GET_USER, {})
        try:
            return str(data["user"]["getCurrentUser"]["id"])
        except Exception as e:
            raise School21Error(f"bad getCurrentUser response: {e}, data={data}")

    def get_project_name(self, module_id: str) -> str:
        assert self.tokens is not None
        resp = self.sess.get(
            f"https://platform.21-school.ru/services/21-school/api/v1/participants/{self.username}/projects/{module_id}",
            headers={"Authorization": f"Bearer {self.tokens.access_token}"},
            timeout=self.timeout_sec,
        )
        resp.raise_for_status()
        return resp.json()["title"]

    def get_reviewed_projects(self, user_id: str) -> list[tuple[str, str]]:
        data = self.graphql("getStudentCurrentProjects", Q_GET_CUR_PROJECTS, {"userId": str(user_id)})
        try:
            val = data["student"]["getStudentCurrentProjects"]
        except Exception as e:
            raise School21Error(f"bad getStudentCurrentProjects: {e}, data={data}")

        items: list[dict] = []
        if isinstance(val, list):
            items = val
        elif isinstance(val, dict) and "goals" in val and isinstance(val["goals"], list):
            items = val["goals"]
        elif isinstance(val, dict) and "items" in val and isinstance(val["items"], list):
            items = val["items"]
        elif isinstance(val, dict) and val:
            items = [val]

        out: list[tuple[str, str]] = []
        for p in items:
            if p.get("goalStatus") == "P2P_EVALUATIONS" and p.get("goalId"):
                out.append((str(p["goalId"]), str(p.get("name") or p.get("title") or "")))
        return out

    def get_task_and_answer(self, module_id: str) -> tuple[str, str]:
        data = self.graphql("calendarGetModule", Q_GET_MODULE, {"moduleId": str(module_id)})
        try:
            cur = data["student"]["getModuleById"]["currentTask"]
            return str(cur["taskId"]), str(cur["lastAnswer"]["id"])
        except Exception as e:
            raise School21Error(f"не смог распарсить task/answer: {e}")

    def get_timeslots(self, task_id: str, from_iso_z: str, to_iso_z: str) -> tuple[list[dict[str, Any]], int]:
        data = self.graphql(
            "calendarGetNameLessStudentTimeslotsForReview",
            Q_GET_SLOTS,
            {"taskId": str(task_id), "from": from_iso_z, "to": to_iso_z},
        )
        try:
            review_data = data["student"]["getNameLessStudentTimeslotsForReview"]
            timeslots = review_data.get("timeSlots") or []
            booked = int(review_data["projectReviewsInfo"]["relevantReviewByStudentsCount"])
            return timeslots, booked
        except Exception as e:
            raise School21Error(f"не смог распарсить timeslots: {e}")

    def book(
        self,
        answer_id: str,
        start_time_iso_z: str,
        staff_slot: bool,
        is_online: bool = True,
    ) -> str:
        data = self.graphql(
            "calendarAddBookingToEventSlot",
            Q_BOOK,
            {
                "answerId": str(answer_id),
                "startTime": start_time_iso_z,
                "wasStaffSlotChosen": bool(staff_slot),
                "isOnline": bool(is_online),
            },
        )
        try:
            return str(data["student"]["addBookingP2PToEventSlot"]["id"])
        except Exception as e:
            raise School21Error(f"не смог распарсить booking id: {e}")

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
        access = payload["access_token"]
        refresh = payload.get("refresh_token", self.tokens.refresh_token)
        expires_in = float(payload.get("expires_in", 300))
        self.tokens = Tokens(
            access_token=access,
            refresh_token=refresh,
            expires_at_epoch=time.time() + expires_in - 20,
        )
        self._set_token_cookie(access)

    def _set_token_cookie(self, access: str) -> None:
        self.sess.cookies.set("tokenId", access, domain="platform.21-school.ru", path="/")
        self.sess.cookies.set("tokenId", access, domain=".21-school.ru", path="/")


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
