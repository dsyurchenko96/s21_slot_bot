import time
from http import HTTPStatus
from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

import aiohttp
import pytest

from s21_slot_bot.client.errors import School21LoginError
from s21_slot_bot.client.middleware.auth import School21AuthMiddleware
from s21_slot_bot.client.models import Tokens


class TestSchool21AuthMiddleware:
    @pytest.fixture
    def valid_tokens(self) -> Tokens:
        return Tokens(
            access_token="access-1",
            refresh_token="refresh-1",
            expires_at_epoch=time.time() + 3600,
        )

    @pytest.fixture
    def expired_tokens(self) -> Tokens:
        return Tokens(
            access_token="access-old",
            refresh_token="refresh-old",
            expires_at_epoch=time.time() - 1,
        )

    def test_set_tokens(self, s21_auth_middleware: School21AuthMiddleware) -> None:
        with patch("s21_slot_bot.client.middleware.auth.time.time", return_value=1000.0):
            s21_auth_middleware._set_tokens(
                {
                    "access_token": "access",
                    "refresh_token": "refresh",
                    "expires_in": 120,
                }
            )

        assert s21_auth_middleware._tokens == Tokens(
            access_token="access",
            refresh_token="refresh",
            expires_at_epoch=1120.0,
        )

    def test_set_tokens_reuses_old_refresh_token(
        self,
        s21_auth_middleware: School21AuthMiddleware,
        valid_tokens: Tokens,
    ) -> None:
        s21_auth_middleware._tokens = valid_tokens

        with patch("s21_slot_bot.client.middleware.auth.time.time", return_value=1000.0):
            s21_auth_middleware._set_tokens(
                {
                    "access_token": "access-2",
                    "expires_in": 120,
                }
            )

        assert s21_auth_middleware._tokens.refresh_token == "refresh-1"

    @pytest.mark.parametrize(
        "payload",
        [
            {},
            {"access_token": "access"},
            {"refresh_token": "refresh"},
            {"access_token": "", "refresh_token": "refresh"},
        ],
    )
    def test_set_tokens_rejects_missing_tokens(
        self,
        s21_auth_middleware: School21AuthMiddleware,
        payload: dict[str, Any],
    ) -> None:
        with pytest.raises(School21LoginError):
            s21_auth_middleware._set_tokens(payload)

    @pytest.mark.parametrize(
        ("html_text", "expected"),
        [
            (
                '<form action="https://auth.21-school.ru/test/login-actions/authenticate?x=1&amp;y=2">',
                "https://auth.21-school.ru/test/login-actions/authenticate?x=1&y=2",
            ),
            (
                '<form action="/auth/login-actions/authenticate?x=1">',
                "https://auth.21-school.ru/auth/login-actions/authenticate?x=1",
            ),
        ],
    )
    def test_extract_login_action(
        self,
        s21_auth_middleware: School21AuthMiddleware,
        html_text: str,
        expected: str,
    ) -> None:
        assert s21_auth_middleware._extract_login_action(html_text, "https://auth.21-school.ru") == expected

    def test_extract_login_action_raises_when_missing(
        self,
        s21_auth_middleware: School21AuthMiddleware,
    ) -> None:
        with pytest.raises(School21LoginError):
            s21_auth_middleware._extract_login_action("<html></html>", "https://auth.21-school.ru")

    async def test_ensure_authenticated_keeps_valid_tokens(
        self,
        s21_auth_middleware: School21AuthMiddleware,
        valid_tokens: Tokens,
        session: aiohttp.ClientSession,
    ) -> None:
        s21_auth_middleware._tokens = valid_tokens
        s21_auth_middleware._try_refresh = AsyncMock()
        s21_auth_middleware._login = AsyncMock()

        await s21_auth_middleware._ensure_authenticated(session)

        s21_auth_middleware._try_refresh.assert_not_awaited()
        s21_auth_middleware._login.assert_not_awaited()

    async def test_ensure_authenticated_uses_refresh_before_login(
        self,
        s21_auth_middleware: School21AuthMiddleware,
        expired_tokens: Tokens,
        session: aiohttp.ClientSession,
    ) -> None:
        s21_auth_middleware._tokens = expired_tokens
        s21_auth_middleware._try_refresh = AsyncMock(return_value=True)
        s21_auth_middleware._login = AsyncMock()

        await s21_auth_middleware._ensure_authenticated(session)

        s21_auth_middleware._try_refresh.assert_awaited_once_with(session)
        s21_auth_middleware._login.assert_not_awaited()

    async def test_ensure_authenticated_logs_in_when_refresh_fails(
        self,
        s21_auth_middleware: School21AuthMiddleware,
        expired_tokens: Tokens,
        session: aiohttp.ClientSession,
    ) -> None:
        s21_auth_middleware._tokens = expired_tokens
        s21_auth_middleware._try_refresh = AsyncMock(return_value=False)
        s21_auth_middleware._login = AsyncMock()

        await s21_auth_middleware._ensure_authenticated(session)

        s21_auth_middleware._try_refresh.assert_awaited_once_with(session)
        s21_auth_middleware._login.assert_awaited_once_with(session)

    async def test_request_success_is_sent_once(
        self,
        s21_auth_middleware: School21AuthMiddleware,
        valid_tokens: Tokens,
        request_mock: aiohttp.ClientRequest,
        response_mock: aiohttp.ClientResponse,
    ) -> None:
        s21_auth_middleware._tokens = valid_tokens
        s21_auth_middleware._ensure_authenticated = AsyncMock()
        s21_auth_middleware._apply_auth = MagicMock()
        response_mock.status = HTTPStatus.OK
        handler = AsyncMock(return_value=response_mock)

        actual = await s21_auth_middleware(request_mock, handler)

        assert actual is response_mock
        s21_auth_middleware._ensure_authenticated.assert_awaited_once_with(request_mock.session)
        s21_auth_middleware._apply_auth.assert_called_once_with(request_mock)
        handler.assert_awaited_once_with(request_mock)

    def test_extract_code_from_redirect_history(
        self,
        s21_auth_middleware: School21AuthMiddleware,
    ) -> None:
        response_without_code = MagicMock(spec=aiohttp.ClientResponse)
        response_without_code.headers = {"Location": "https://example.test/no-code"}
        response_with_code = MagicMock(spec=aiohttp.ClientResponse)
        response_with_code.headers = {"Location": "https://platform.21-school.ru/#state=state-1&code=code-1"}

        assert (
            s21_auth_middleware._extract_code_from_redirect_history([response_without_code, response_with_code])
            == "code-1"
        )

    def test_extract_code_from_redirect_history_returns_none_when_missing(
        self,
        s21_auth_middleware: School21AuthMiddleware,
    ) -> None:
        response_without_location = MagicMock(spec=aiohttp.ClientResponse)
        response_without_location.headers = {}
        response_without_code = MagicMock(spec=aiohttp.ClientResponse)
        response_without_code.headers = {"Location": "https://example.test/#state=x"}

        assert (
            s21_auth_middleware._extract_code_from_redirect_history([response_without_location, response_without_code])
            is None
        )

    @pytest.mark.parametrize("status", [HTTPStatus.UNAUTHORIZED, HTTPStatus.FORBIDDEN])
    async def test_auth_error_reauthenticates_and_retries_once(
        self,
        s21_auth_middleware: School21AuthMiddleware,
        valid_tokens: Tokens,
        request_mock: aiohttp.ClientRequest,
        status: HTTPStatus,
    ) -> None:
        s21_auth_middleware._tokens = valid_tokens
        s21_auth_middleware._ensure_authenticated = AsyncMock()
        s21_auth_middleware._force_reauthenticate = AsyncMock()
        s21_auth_middleware._apply_auth = MagicMock()

        auth_error_response = MagicMock(spec=aiohttp.ClientResponse)
        auth_error_response.status = status
        success_response = MagicMock(spec=aiohttp.ClientResponse)
        success_response.status = HTTPStatus.OK
        handler = AsyncMock(side_effect=[auth_error_response, success_response])

        actual = await s21_auth_middleware(request_mock, handler)

        assert actual is success_response
        auth_error_response.release.assert_called_once_with()
        s21_auth_middleware._force_reauthenticate.assert_awaited_once_with(request_mock.session)
        assert s21_auth_middleware._apply_auth.call_count == 2
        assert handler.await_count == 2

    def test_apply_auth_adds_token_cookie(
        self,
        s21_auth_middleware: School21AuthMiddleware,
        valid_tokens: Tokens,
        request_mock: aiohttp.ClientRequest,
    ) -> None:
        s21_auth_middleware._tokens = valid_tokens
        cookies = MagicMock()
        cookies.output.return_value = "session=abc; tokenId=access-1"
        request_mock.session.cookie_jar.filter_cookies.return_value = cookies

        s21_auth_middleware._apply_auth(request_mock)

        assert request_mock.headers["Cookie"] == "session=abc; tokenId=access-1"

    def test_apply_auth_requires_tokens(
        self,
        s21_auth_middleware: School21AuthMiddleware,
        request_mock: aiohttp.ClientRequest,
    ) -> None:
        with pytest.raises(School21LoginError, match="токен"):
            s21_auth_middleware._apply_auth(request_mock)
