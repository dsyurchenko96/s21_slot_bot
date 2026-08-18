from unittest.mock import AsyncMock, patch

import aiohttp
import pytest

from s21_slot_bot.client.middleware.retry import School21RetryMiddleware


class TestSchool21RetryMiddleware:
    async def test_success_does_not_retry(
        self,
        s21_retry_middleware: School21RetryMiddleware,
        request_mock: aiohttp.ClientRequest,
        response_mock: aiohttp.ClientResponse,
    ) -> None:
        handler = AsyncMock(return_value=response_mock)

        with patch("s21_slot_bot.client.middleware.retry.asyncio.sleep", new_callable=AsyncMock) as sleep:
            actual = await s21_retry_middleware(request_mock, handler)

        assert actual is response_mock
        handler.assert_awaited_once_with(request_mock)
        sleep.assert_not_awaited()

    async def test_retries_connection_errors_until_success(
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
            actual = await s21_retry_middleware(request_mock, handler)

        assert actual is response_mock
        assert handler.await_count == 3
        assert [call.args[0] for call in sleep.await_args_list] == [2, 4]

    async def test_reraises_last_connection_error_when_retries_exhausted(
        self,
        s21_retry_middleware: School21RetryMiddleware,
        request_mock: aiohttp.ClientRequest,
    ) -> None:
        handler = AsyncMock(side_effect=aiohttp.ClientConnectionError("broken"))

        with (
            patch("s21_slot_bot.client.middleware.retry.asyncio.sleep", new_callable=AsyncMock) as sleep,
            pytest.raises(aiohttp.ClientConnectionError, match="broken"),
        ):
            await s21_retry_middleware(request_mock, handler)

        assert handler.await_count == 3
        assert sleep.await_count == 2
