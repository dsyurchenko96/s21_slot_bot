from unittest.mock import AsyncMock, patch

import aiohttp
import pytest

from s21_slot_bot.client.middleware.retry import School21RetryMiddleware


class TestSchool21RetryMiddleware:
    async def test_success_is_not_retried(
        self,
        s21_retry_middleware: School21RetryMiddleware,
        request_mock: aiohttp.ClientRequest,
        response_mock: aiohttp.ClientResponse,
    ) -> None:
        handler = AsyncMock(return_value=response_mock)

        assert await s21_retry_middleware(request_mock, handler) is response_mock
        handler.assert_awaited_once_with(request_mock)

    async def test_connection_errors_are_retried(
        self,
        s21_retry_middleware: School21RetryMiddleware,
        request_mock: aiohttp.ClientRequest,
        response_mock: aiohttp.ClientResponse,
    ) -> None:
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

    async def test_last_connection_error_is_reraised(
        self,
        s21_retry_middleware: School21RetryMiddleware,
        request_mock: aiohttp.ClientRequest,
    ) -> None:
        handler = AsyncMock(side_effect=aiohttp.ClientConnectionError("broken"))

        with (
            patch("s21_slot_bot.client.middleware.retry.asyncio.sleep", new_callable=AsyncMock),
            pytest.raises(aiohttp.ClientConnectionError, match="broken"),
        ):
            await s21_retry_middleware(request_mock, handler)
