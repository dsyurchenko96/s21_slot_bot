#!/usr/bin/env python3
# -*- coding: utf-8 -*-

from __future__ import annotations

import argparse
import html
import os
import random
import re
import sys
import time
import uuid
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any, Dict, Optional, Tuple, List
from urllib.parse import urljoin, urlparse, parse_qs

import requests

from queries import Q_GET_MODULE, Q_GET_SLOTS, Q_BOOK

AUTH_BASE = "https://auth.21-school.ru"
REALM = "EduPowerKeycloak"
CLIENT_ID = "school21"
REDIRECT_URI = "https://platform.21-school.ru/"

GRAPHQL_URL = "https://platform.21-school.ru/services/graphql"

class School21Error(RuntimeError):
    pass


def _extract_login_action(html_text: str, base_url: str) -> str:
    """
    Ищем action у формы логина: .../login-actions/authenticate?...session_code=...&execution=...&tab_id=...
    """
    m = re.search(
        r'action\s*=\s*"([^"]*login-actions/authenticate[^"]*)"',
        html_text,
        flags=re.IGNORECASE,
    )
    if not m:
        raise School21Error("Не смог найти login form action в HTML Keycloak (возможно изменилась страница логина).")
    action = html.unescape(m.group(1))
    return urljoin(base_url, action)


def _extract_code_from_redirect_history(history: list[requests.Response]) -> str | None:
    """
    code приходит в Location с fragment: https://platform.../#state=...&code=...
    requests при переходе отбрасывает fragment, поэтому берем из Location в history.
    """
    for resp in reversed(history):
        loc = resp.headers.get("Location") or resp.headers.get("location")
        if not loc:
            continue
        if "code=" not in loc:
            continue
        u = urlparse(loc)
        frag = u.fragment  # "state=...&code=..."
        if not frag:
            continue
        qs = parse_qs(frag)
        code = (qs.get("code") or [None])[0]
        if code:
            return code
    return None


def _utc_now_iso_z() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="milliseconds").replace("+00:00", "Z")


@dataclass
class Tokens:
    access_token: str
    refresh_token: str
    expires_at_epoch: float  # epoch seconds


class School21Client:
    """
    Клиент: Keycloak login -> access_token -> GraphQL.
    """

    def __init__(
        self,
        username: str,
        password: str,
        userrole: str = "STUDENT",
        x_edu_org_unit_id: str = "6bfe3c56-0211-4fe1-9e59-51616caac4dd",
        x_edu_product_id: str = "96098f4b-5708-4c42-a62c-6893419169b3",
        timeout_s: int = 25,
    ):
        self.username = username
        self.password = password
        self.userrole = userrole
        self.x_edu_org_unit_id = x_edu_org_unit_id
        self.x_edu_product_id = x_edu_product_id
        self.timeout_s = timeout_s

        self.sess = requests.Session()
        self.tokens: Optional[Tokens] = None

    def _token_endpoint(self) -> str:
        return f"{AUTH_BASE}/auth/realms/{REALM}/protocol/openid-connect/token"

    def _auth_endpoint(self, state: str, nonce: str) -> str:
        return (
            f"{AUTH_BASE}/auth/realms/{REALM}/protocol/openid-connect/auth"
            f"?client_id={CLIENT_ID}"
            f"&redirect_uri={requests.utils.quote(REDIRECT_URI, safe='')}"
            f"&state={state}"
            f"&response_mode=fragment"
            f"&response_type=code"
            f"&scope=openid"
            f"&nonce={nonce}"
        )

    def login(self) -> None:
        """
        1) GET /auth (Keycloak login page) -> достать form action
        2) POST creds -> редиректы -> вытащить authorization code из Location fragment
        3) POST /token (authorization_code) -> access_token/refresh_token
        """
        state = str(uuid.uuid4())
        nonce = str(uuid.uuid4())
        auth_url = self._auth_endpoint(state=state, nonce=nonce)

        r = self.sess.get(auth_url, timeout=self.timeout_s)
        r.raise_for_status()

        action_url = _extract_login_action(r.text, AUTH_BASE)

        data = {"username": self.username, "password": self.password}
        r2 = self.sess.post(action_url, data=data, allow_redirects=True, timeout=self.timeout_s)

        # code лежит в редиректе на platform (в Location с fragment)
        code = _extract_code_from_redirect_history(r2.history + [r2])
        if not code:
            raise School21Error(
                "Не смог извлечь authorization code из редиректов. "
                "Проверь, что логин/пароль верные, и что нет дополнительных шагов (2FA/капча)."
            )

        token_resp = self.sess.post(
            self._token_endpoint(),
            data={
                "code": code,
                "grant_type": "authorization_code",
                "client_id": CLIENT_ID,
                "redirect_uri": REDIRECT_URI,
            },
            headers={"Content-Type": "application/x-www-form-urlencoded"},
            timeout=self.timeout_s,
        )
        token_resp.raise_for_status()
        payload = token_resp.json()

        access = payload["access_token"]
        self.sess.cookies.set("tokenId", access, domain="platform.21-school.ru", path="/")
        refresh = payload.get("refresh_token", "")
        expires_in = float(payload.get("expires_in", 300))
        expires_at = time.time() + expires_in - 20  # небольшой запас

        self.tokens = Tokens(access_token=access, refresh_token=refresh, expires_at_epoch=expires_at)

    def _refresh_if_needed(self) -> None:
        if not self.tokens:
            self.login()
            return
        if time.time() < self.tokens.expires_at_epoch:
            return
        if not self.tokens.refresh_token:
            # если refresh_token не пришел — просто перелогинимся
            self.login()
            return

        resp = self.sess.post(
            self._token_endpoint(),
            data={
                "grant_type": "refresh_token",
                "client_id": CLIENT_ID,
                "refresh_token": self.tokens.refresh_token,
            },
            headers={"Content-Type": "application/x-www-form-urlencoded"},
            timeout=self.timeout_s,
        )
        if resp.status_code >= 400:
            # fallback: полный логин
            self.login()
            return

        payload = resp.json()
        access = payload["access_token"]
        refresh = payload.get("refresh_token", self.tokens.refresh_token)
        expires_in = float(payload.get("expires_in", 300))
        self.tokens = Tokens(access_token=access, refresh_token=refresh, expires_at_epoch=time.time() + expires_in - 20)

    def graphql(self, operation_name: str, query: str, variables: Dict[str, Any]) -> Dict[str, Any]:
        self._refresh_if_needed()
        assert self.tokens is not None

        headers = {
            "Content-Type": "application/json",
            "Accept": "application/json",
            # "Authorization": f"Bearer {self.tokens.access_token}",
            "userrole": self.userrole,
            "schoolid": self.x_edu_org_unit_id,
            "x-edu-org-unit-id": self.x_edu_org_unit_id,
            "x-edu-product-id": self.x_edu_product_id,
            "Origin": "https://platform.21-school.ru",
            "Referer": "https://platform.21-school.ru/calendar",
        }

        resp = self.sess.post(
            GRAPHQL_URL,
            json={
                "operationName": operation_name,
                "variables": variables,
                "query": query,
            },
            headers=headers,
            timeout=self.timeout_s,
        )

        # если токен внезапно протух — один раз перелогинимся и повторим
        if resp.status_code in (401, 403):
            self.login()
            # headers["Authorization"] = f"Bearer {self.tokens.access_token}"
            resp = self.sess.post(
                GRAPHQL_URL,
                json={"operationName": operation_name, "variables": variables, "query": query},
                headers=headers,
                timeout=self.timeout_s,
            )

        resp.raise_for_status()
        data = resp.json()

        if "errors" in data and data["errors"]:
            # GraphQL ошибки часто информативны
            raise School21Error(f"GraphQL errors: {data['errors']}")

        return data.get("data", {})

    def get_project_name(self, module_id: str) -> str:
        resp = self.sess.get(
            f"https://platform.21-school.ru/services/21-school/api/v1/projects/{module_id}",
            headers={"Authorization": f"Bearer {self.tokens.access_token}"},
            timeout=self.timeout_s,
        )
        resp.raise_for_status()
        data = resp.json()
        return data["title"]

    def get_task_and_answer(self, module_id: str) -> Tuple[str, str]:
        data = self.graphql(
            "calendarGetModule",
            Q_GET_MODULE,
            {"moduleId": str(module_id)},
        )
        try:
            cur = data["student"]["getModuleById"]["currentTask"]
            task_id = cur["taskId"]
            answer_id = cur["lastAnswer"]["id"]
            return str(task_id), str(answer_id)
        except Exception as e:
            raise School21Error(f"Не смог распарсить taskId/answerId из calendarGetModule: {e}")

    def get_timeslots(self, task_id: str, from_iso_z: str, to_iso_z: str) -> tuple[list[dict[str, Any]], int]:
        data = self.graphql(
            "calendarGetNameLessStudentTimeslotsForReview",
            Q_GET_SLOTS,
            {"taskId": str(task_id), "from": from_iso_z, "to": to_iso_z},
        )
        try:
            review_data = data["student"]["getNameLessStudentTimeslotsForReview"]
            timeslots: list[dict[str, Any]] = review_data["timeSlots"]
            num_booked_reviews: int = review_data["relevantReviewByStudentsCount"]
            return timeslots, num_booked_reviews
        except Exception as e:
            raise School21Error(f"Не смог распарсить timeSlots: {e}")

    def book(self, answer_id: str, start_time_iso_z: str, staff_slot: bool, is_online: bool = True) -> str:
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
            raise School21Error(f"Не смог распарсить booking id: {e}")


class TelegramNotifier:
    def __init__(self, bot_token: str, chat_id: str, timeout_s: int = 15):
        self.bot_token = bot_token
        self.chat_id = chat_id
        self.timeout_s = timeout_s

    def send(self, text: str) -> None:
        url = f"https://api.telegram.org/bot{self.bot_token}/sendMessage"
        r = requests.post(url, json={"chat_id": self.chat_id, "text": text}, timeout=self.timeout_s)
        r.raise_for_status()


def pick_candidate_start(timeslots: List[Dict[str, Any]]) -> Optional[Tuple[str, bool]]:
    """
    Выбираем “лучший” старт: самый ранний validStartTimes.
    Возвращаем (start_time_iso_z, staff_slot).
    """
    candidates: List[Tuple[str, bool]] = []
    for slot in timeslots:
        staff = bool(slot.get("staffSlot", False))
        for t in slot.get("validStartTimes") or []:
            candidates.append((t, staff))
    if not candidates:
        return None
    candidates.sort(key=lambda x: x[0])
    return candidates[0]


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--module-id", required=True, help="ID проекта/модуля (moduleId), который проверяется")
    ap.add_argument("--from", dest="from_iso", required=True, help="UTC ISO, например 2025-12-14T21:00:00.000Z")
    ap.add_argument("--to", dest="to_iso", required=True, help="UTC ISO, например 2025-12-21T20:59:59.999Z")
    ap.add_argument("--interval", type=int, default=60, help="интервал опроса (сек)")
    ap.add_argument("--jitter", type=int, default=7, help="рандомный джиттер (сек) чтобы не долбить ровно по минуте")
    ap.add_argument("--telegram", action="store_true", help="включить уведомление в Telegram")
    ap.add_argument("--dry-run", action="store_true", help="не бронировать, только печатать найденный слот")

    args = ap.parse_args()

    username = os.environ.get("S21_USERNAME", "").strip()
    password = os.environ.get("S21_PASSWORD", "").strip()
    if not username or not password:
        print("Нужно задать переменные окружения S21_USERNAME и S21_PASSWORD", file=sys.stderr)
        return 2

    client = School21Client(username=username, password=password)
    client.login()

    tg = None
    if args.telegram:
        bot_token = os.environ.get("TG_BOT_TOKEN", "").strip()
        chat_id = os.environ.get("TG_CHAT_ID", "").strip()
        if not bot_token or not chat_id:
            print("Для Telegram нужны TG_BOT_TOKEN и TG_CHAT_ID", file=sys.stderr)
            return 2
        tg = TelegramNotifier(bot_token, chat_id)
        project_name = client.get_project_name(args.module_id)
        tg.send(f"Starting to look for slots for {project_name} from {args.from_iso} to {args.to_iso}...")

    task_id, answer_id = client.get_task_and_answer(args.module_id)

    print(f"[ok] taskId={task_id}, answerId={answer_id}")

    attempt = 0
    while True:
        attempt += 1
        try:
            slots, _ = client.get_timeslots(task_id, args.from_iso, args.to_iso)
            picked = pick_candidate_start(slots)
            if not picked:
                print(f"[{attempt}] нет слотов ({_utc_now_iso_z()})")
            else:
                start_time, staff_slot = picked
                print(f"[{attempt}] найден слот: {start_time} (staffSlot={staff_slot})")

                if args.dry_run:
                    msg = f"DRY RUN: найден слот {start_time} (moduleId={args.module_id})"
                    if tg:
                        tg.send(msg)
                    return 0

                booking_id = client.book(answer_id=answer_id, start_time_iso_z=start_time, staff_slot=staff_slot)
                msg = f"✅ Успешно записался на ревью!\nmoduleId={args.module_id}\nstart={start_time}\nbookingId={booking_id}"
                print(msg)
                if tg:
                    tg.send(msg)
                return 0

        except School21Error as e:
            # типичный кейс: слот уже забрали, GraphQL вернул ошибку — продолжаем
            print(f"[{attempt}] ошибка: {e}", file=sys.stderr)
        except requests.RequestException as e:
            print(f"[{attempt}] network error: {e}", file=sys.stderr)

        sleep_s = args.interval + random.randint(0, max(0, args.jitter))
        time.sleep(sleep_s)


if __name__ == "__main__":
    raise SystemExit(main())