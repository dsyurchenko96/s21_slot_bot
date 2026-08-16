from abc import ABC

from aiohttp import ClientHandlerType, ClientRequest, ClientResponse


class School21Middleware(ABC):
    """Base class for School21Client middleware"""

    async def __call__(
        self,
        request: ClientRequest,
        handler: ClientHandlerType,
    ) -> ClientResponse:
        raise NotImplementedError
