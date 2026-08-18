import asyncio
from typing import override

import aiohttp
from aiohttp import ClientHandlerType, ClientRequest, ClientResponse

from s21_slot_bot.app.errors import InternalError
from s21_slot_bot.client.config import S21ClientConfig
from s21_slot_bot.client.middleware.base import School21Middleware
from s21_slot_bot.common.logger import LogEntity, get_id_logger


class School21RetryMiddleware(School21Middleware):
    def __init__(self, config: S21ClientConfig):
        self._attempts = config.max_request_retries
        self._delay_sec = config.retry_delay_sec

    @override
    async def __call__(
        self,
        request: ClientRequest,
        handler: ClientHandlerType,
    ) -> ClientResponse:
        logger = get_id_logger(LogEntity.MIDDLEWARE)
        last_error: Exception | None = None
        for attempt in range(self._attempts):
            try:
                response = await handler(request)
                return response
            except (TimeoutError, aiohttp.ClientConnectionError) as e:
                logger.error("Connection failed: %s", e)
                last_error = e
                if attempt == self._attempts - 1:
                    raise
                await asyncio.sleep(self._delay_sec * (attempt + 1))
        raise last_error if last_error is not None else InternalError("ошибка повторного запроса")
