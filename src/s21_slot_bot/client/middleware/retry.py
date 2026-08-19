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
        for attempt in range(1, self._attempts + 1):
            try:
                return await handler(request)
            except (TimeoutError, aiohttp.ClientConnectionError) as e:
                logger.warning(
                    "Request attempt %d/%d failed with %s: %s",
                    attempt,
                    self._attempts,
                    type(e).__name__,
                    e,
                )
                if attempt == self._attempts:
                    logger.error("Request failed after %d attempts", self._attempts)
                    raise
                delay = self._delay_sec * attempt
                logger.info("Retrying request in %.1f seconds", delay)
                await asyncio.sleep(delay)
        raise InternalError("недостижимое состояние retry middleware")
