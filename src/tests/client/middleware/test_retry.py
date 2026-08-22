from collections.abc import Callable
from http import HTTPStatus
from unittest.mock import AsyncMock, MagicMock, patch

import aiohttp
import pytest

from s21_slot_bot.client.errors import School21Error
from s21_slot_bot.client.middleware.retry import School21RetryMiddleware


class TestSchool21RetryMiddleware:
    async def test_success_is_not_retried(
        self,
        s21_retry_middleware: School21RetryMiddleware,
        request_mock: aiohttp.ClientRequest,
        response_factory: Callable[..., aiohttp.ClientResponse],
    ) -> None:
        response_mock = response_factory()
        handler = AsyncMock(return_value=response_mock)

        assert await s21_retry_middleware(request_mock, handler) is response_mock
        handler.assert_awaited_once_with(request_mock)

    async def test_connection_errors_are_retried(
        self,
        s21_retry_middleware: School21RetryMiddleware,
        request_mock: aiohttp.ClientRequest,
        response_factory: Callable[..., aiohttp.ClientResponse],
    ) -> None:
        response_mock = response_factory()
        handler = AsyncMock(
            side_effect=[
                aiohttp.ClientConnectionError("first"),
                aiohttp.ClientConnectionError("second"),
                response_mock,
            ]
        )

        with patch("s21_slot_bot.client.middleware.retry.asyncio.sleep", new_callable=AsyncMock) as sleep:
            assert await s21_retry_middleware(request_mock, handler) is response_mock

        assert handler.await_count == 3
        assert [call.args[0] for call in sleep.await_args_list] == [2, 4]

    async def test_server_errors_are_retried(
        self,
        s21_retry_middleware: School21RetryMiddleware,
        request_mock: aiohttp.ClientRequest,
        response_factory: Callable[..., aiohttp.ClientResponse],
    ) -> None:
        internal_error_response = response_factory(status=HTTPStatus.INTERNAL_SERVER_ERROR)
        bad_gateway_response = response_factory(status=HTTPStatus.BAD_GATEWAY)
        ok_response = response_factory()
        handler = AsyncMock(
            side_effect=[
                internal_error_response,
                bad_gateway_response,
                ok_response,
            ]
        )

        with patch("s21_slot_bot.client.middleware.retry.asyncio.sleep", new_callable=AsyncMock) as sleep:
            assert await s21_retry_middleware(request_mock, handler) is ok_response

        assert handler.await_count == 3
        assert [call.args[0] for call in sleep.await_args_list] == [2, 4]

    async def test_wrong_content_type_error_is_retried(
        self,
        s21_retry_middleware: School21RetryMiddleware,
        request_mock: aiohttp.ClientRequest,
        response_factory: Callable[..., aiohttp.ClientResponse],
    ) -> None:
        invalid_content_type_response = response_factory(status=HTTPStatus.OK)
        invalid_content_type_response.json = AsyncMock(
            side_effect=aiohttp.ContentTypeError(request_info=MagicMock(), history=())
        )
        ok_response = response_factory()
        handler = AsyncMock(
            side_effect=[
                invalid_content_type_response,
                ok_response,
            ]
        )

        with patch("s21_slot_bot.client.middleware.retry.asyncio.sleep", new_callable=AsyncMock):
            assert await s21_retry_middleware(request_mock, handler) is ok_response

        assert handler.await_count == 2

    async def test_last_connection_error_is_reraised(
        self,
        s21_retry_middleware: School21RetryMiddleware,
        request_mock: aiohttp.ClientRequest,
    ) -> None:
        handler = AsyncMock(side_effect=aiohttp.ClientConnectionError("broken"))

        with (
            patch("s21_slot_bot.client.middleware.retry.asyncio.sleep", new_callable=AsyncMock),
            pytest.raises(School21Error, match="broken"),
        ):
            await s21_retry_middleware(request_mock, handler)
