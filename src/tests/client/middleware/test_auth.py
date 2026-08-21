import time
from collections.abc import Callable
from http import HTTPStatus
from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

import aiohttp
import pytest

from s21_slot_bot.client.errors import School21LoginError
from s21_slot_bot.client.middleware.auth import School21AuthMiddleware
from s21_slot_bot.client.models import Tokens
from tests.conftest import response_context


class TestSchool21AuthMiddleware:
    @pytest.fixture
    def valid_tokens(self) -> Tokens:
        return Tokens(access_token="access-1", refresh_token="refresh-1", expires_at_epoch=time.time() + 3600)

    @pytest.fixture
    def expired_tokens(self) -> Tokens:
        return Tokens(access_token="old", refresh_token="refresh-1", expires_at_epoch=time.time() - 1)

    def test_endpoints_and_tokens_valid(
        self,
        s21_auth_middleware: School21AuthMiddleware,
        valid_tokens: Tokens,
    ) -> None:
        assert s21_auth_middleware._token_endpoint.endswith("/token")
        assert "client_id=" in s21_auth_middleware._auth_endpoint
        assert s21_auth_middleware._tokens_valid is False
        s21_auth_middleware._tokens = valid_tokens
        assert s21_auth_middleware._tokens_valid is True

    def test_set_tokens(self, s21_auth_middleware: School21AuthMiddleware) -> None:
        with patch("s21_slot_bot.client.middleware.auth.time.time", return_value=1000.0):
            s21_auth_middleware._set_tokens({"access_token": "access", "refresh_token": "refresh", "expires_in": 120})
        assert s21_auth_middleware._tokens == Tokens(
            access_token="access", refresh_token="refresh", expires_at_epoch=1120.0
        )

    def test_set_tokens_reuses_refresh(
        self,
        s21_auth_middleware: School21AuthMiddleware,
        valid_tokens: Tokens,
    ) -> None:
        s21_auth_middleware._tokens = valid_tokens
        s21_auth_middleware._set_tokens({"access_token": "new", "expires_in": 120})
        assert s21_auth_middleware._tokens.refresh_token == "refresh-1"

    @pytest.mark.parametrize("payload", [{}, {"access_token": "access"}, {"refresh_token": "refresh"}])
    def test_set_tokens_rejects_incomplete_response(
        self,
        s21_auth_middleware: School21AuthMiddleware,
        payload: dict[str, Any],
    ) -> None:
        with pytest.raises(School21LoginError):
            s21_auth_middleware._set_tokens(payload)

    async def test_ensure_authenticated_keeps_valid_tokens(
        self,
        s21_auth_middleware: School21AuthMiddleware,
        valid_tokens: Tokens,
        session_mock: aiohttp.ClientSession,
    ) -> None:
        s21_auth_middleware._tokens = valid_tokens
        s21_auth_middleware._try_refresh = AsyncMock()
        s21_auth_middleware._login = AsyncMock()
        await s21_auth_middleware._ensure_authenticated(session_mock)
        s21_auth_middleware._try_refresh.assert_not_awaited()
        s21_auth_middleware._login.assert_not_awaited()

    async def test_ensure_authenticated_refreshes_or_logs_in(
        self,
        s21_auth_middleware: School21AuthMiddleware,
        expired_tokens: Tokens,
        session_mock: aiohttp.ClientSession,
    ) -> None:
        s21_auth_middleware._tokens = expired_tokens
        s21_auth_middleware._try_refresh = AsyncMock(return_value=True)
        s21_auth_middleware._login = AsyncMock()
        await s21_auth_middleware._ensure_authenticated(session_mock)
        s21_auth_middleware._login.assert_not_awaited()

        s21_auth_middleware._try_refresh = AsyncMock(return_value=False)
        await s21_auth_middleware._ensure_authenticated(session_mock)
        s21_auth_middleware._login.assert_awaited_once_with(session_mock)

    async def test_force_reauthenticate(
        self,
        s21_auth_middleware: School21AuthMiddleware,
        session_mock: aiohttp.ClientSession,
    ) -> None:
        s21_auth_middleware._login = AsyncMock()
        await s21_auth_middleware._force_reauthenticate(session_mock)
        s21_auth_middleware._login.assert_awaited_once_with(session_mock)

    async def test_successful_request_is_sent_once(
        self,
        s21_auth_middleware: School21AuthMiddleware,
        valid_tokens: Tokens,
        request_mock: aiohttp.ClientRequest,
        response_factory: Callable[..., aiohttp.ClientResponse],
    ) -> None:
        s21_auth_middleware._tokens = valid_tokens
        s21_auth_middleware._ensure_authenticated = AsyncMock()
        s21_auth_middleware._apply_auth = MagicMock()
        response_mock = response_factory()
        handler = AsyncMock(return_value=response_mock)
        assert await s21_auth_middleware(request_mock, handler) is response_mock
        handler.assert_awaited_once_with(request_mock)

    @pytest.mark.parametrize("status", [HTTPStatus.UNAUTHORIZED, HTTPStatus.FORBIDDEN])
    async def test_auth_failure_reauthenticates_and_retries_once(
        self,
        s21_auth_middleware: School21AuthMiddleware,
        valid_tokens: Tokens,
        request_mock: aiohttp.ClientRequest,
        response_factory: Callable[..., aiohttp.ClientResponse],
        status: HTTPStatus,
    ) -> None:
        s21_auth_middleware._tokens = valid_tokens
        s21_auth_middleware._ensure_authenticated = AsyncMock()
        s21_auth_middleware._force_reauthenticate = AsyncMock()
        s21_auth_middleware._apply_auth = MagicMock()
        failed = response_factory(status=status)
        successful = response_factory()
        handler = AsyncMock(side_effect=[failed, successful])
        assert await s21_auth_middleware(request_mock, handler) is successful
        failed.release.assert_called_once()
        s21_auth_middleware._force_reauthenticate.assert_awaited_once_with(request_mock.session)
        assert handler.await_count == 2

    def test_apply_auth(
        self,
        s21_auth_middleware: School21AuthMiddleware,
        valid_tokens: Tokens,
        request_mock: aiohttp.ClientRequest,
    ) -> None:
        with pytest.raises(School21LoginError):
            s21_auth_middleware._apply_auth(request_mock)

        s21_auth_middleware._tokens = valid_tokens
        cookies = MagicMock()
        cookies.output.return_value = "session=abc;tokenId=access-1"
        request_mock.session.cookie_jar.filter_cookies.return_value = cookies
        s21_auth_middleware._apply_auth(request_mock)
        assert request_mock.headers["Cookie"] == "session=abc;tokenId=access-1"

    async def test_login_success(
        self,
        s21_auth_middleware: School21AuthMiddleware,
        session_mock: aiohttp.ClientSession,
        response_factory: Callable[..., aiohttp.ClientResponse],
    ) -> None:
        auth_response = response_factory(text="<html>")
        action_response = response_factory()
        token_response = response_factory(
            json={"access_token": "access", "refresh_token": "refresh", "expires_in": 120}
        )
        s21_auth_middleware._extract_login_action = MagicMock(return_value="https://auth/action")
        s21_auth_middleware._extract_code_from_redirect_history = MagicMock(return_value="code")
        session_mock.get.return_value = response_context(auth_response)
        session_mock.post.side_effect = [response_context(action_response), response_context(token_response)]

        await s21_auth_middleware._login(session_mock)

        assert s21_auth_middleware._tokens is not None
        assert s21_auth_middleware._tokens.access_token == "access"

    async def test_login_auth_page_failure(
        self,
        s21_auth_middleware: School21AuthMiddleware,
        session_mock: aiohttp.ClientSession,
        response_factory: Callable[..., aiohttp.ClientResponse],
    ) -> None:
        response = response_factory(status=HTTPStatus.BAD_GATEWAY, reason="Bad Gateway", text="bad")
        session_mock.get.return_value = response_context(response)
        with pytest.raises(School21LoginError) as exc_info:
            await s21_auth_middleware._login(session_mock)
        assert exc_info.value.effective_status == HTTPStatus.BAD_GATEWAY

    async def test_login_requires_authorization_code(
        self,
        s21_auth_middleware: School21AuthMiddleware,
        session_mock: aiohttp.ClientSession,
        response_factory: Callable[..., aiohttp.ClientResponse],
    ) -> None:
        auth_response = response_factory(text="<html>")
        action_response = response_factory(status=HTTPStatus.UNAUTHORIZED)
        s21_auth_middleware._extract_login_action = MagicMock(return_value="https://auth/action")
        s21_auth_middleware._extract_code_from_redirect_history = MagicMock(return_value=None)
        session_mock.get.return_value = response_context(auth_response)
        session_mock.post.return_value = response_context(action_response)
        with pytest.raises(School21LoginError):
            await s21_auth_middleware._login(session_mock)

    async def test_login_token_failure(
        self,
        s21_auth_middleware: School21AuthMiddleware,
        session_mock: aiohttp.ClientSession,
        response_factory: Callable[..., aiohttp.ClientResponse],
    ) -> None:
        auth_response = response_factory(text="<html>")
        action_response = response_factory()
        token_response = response_factory(status=HTTPStatus.UNAUTHORIZED, reason="Unauthorized", text="bad token")
        s21_auth_middleware._extract_login_action = MagicMock(return_value="https://auth/action")
        s21_auth_middleware._extract_code_from_redirect_history = MagicMock(return_value="code")
        session_mock.get.return_value = response_context(auth_response)
        session_mock.post.side_effect = [response_context(action_response), response_context(token_response)]
        with pytest.raises(School21LoginError):
            await s21_auth_middleware._login(session_mock)

    async def test_try_refresh(
        self,
        s21_auth_middleware: School21AuthMiddleware,
        valid_tokens: Tokens,
        session_mock: aiohttp.ClientSession,
    ) -> None:
        assert await s21_auth_middleware._try_refresh(session_mock) is False

        s21_auth_middleware._tokens = valid_tokens
        failed = MagicMock(spec=aiohttp.ClientResponse)
        failed.ok = False
        session_mock.post.return_value = response_context(failed)
        assert await s21_auth_middleware._try_refresh(session_mock) is False

        success = MagicMock(spec=aiohttp.ClientResponse)
        success.ok = True
        success.json = AsyncMock(return_value={"access_token": "new", "refresh_token": "refresh", "expires_in": 120})
        session_mock.post.return_value = response_context(success)
        assert await s21_auth_middleware._try_refresh(session_mock) is True
        assert s21_auth_middleware._tokens.access_token == "new"

    def test_extract_login_action(self, s21_auth_middleware: School21AuthMiddleware) -> None:
        html = '<form action="/auth/login-actions/authenticate?x=1&amp;y=2">'
        assert s21_auth_middleware._extract_login_action(html, "https://auth.21-school.ru") == (
            "https://auth.21-school.ru/auth/login-actions/authenticate?x=1&y=2"
        )
        with pytest.raises(School21LoginError):
            s21_auth_middleware._extract_login_action("<html></html>", "https://auth.21-school.ru")

    def test_extract_code_from_redirect_history(self, s21_auth_middleware: School21AuthMiddleware) -> None:
        no_location = MagicMock(spec=aiohttp.ClientResponse)
        no_location.headers = {}
        no_fragment = MagicMock(spec=aiohttp.ClientResponse)
        no_fragment.headers = {"Location": "https://example.test/?code=x"}
        with_code = MagicMock(spec=aiohttp.ClientResponse)
        with_code.headers = {"Location": "https://platform.21-school.ru/#state=x&code=code-1"}
        assert (
            s21_auth_middleware._extract_code_from_redirect_history([no_location, no_fragment, with_code]) == "code-1"
        )
        assert s21_auth_middleware._extract_code_from_redirect_history([no_location]) is None
