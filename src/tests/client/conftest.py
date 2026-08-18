from unittest.mock import MagicMock, create_autospec

import aiohttp
import pytest

from s21_slot_bot.client.config import S21ClientConfig
from s21_slot_bot.client.middleware.auth import School21AuthMiddleware
from s21_slot_bot.client.middleware.retry import School21RetryMiddleware
from s21_slot_bot.client.s21_client import School21Client


@pytest.fixture
def s21_config(config) -> S21ClientConfig:
    return config.s21


@pytest.fixture
def s21_auth_middleware(s21_config: S21ClientConfig) -> School21AuthMiddleware:
    return School21AuthMiddleware(config=s21_config)


@pytest.fixture
def s21_retry_middleware(s21_config: S21ClientConfig) -> School21RetryMiddleware:
    return School21RetryMiddleware(config=s21_config)


@pytest.fixture
def s21_client(
    s21_config: S21ClientConfig,
    s21_auth_middleware_mock: School21AuthMiddleware,
    s21_retry_middleware_mock: School21RetryMiddleware,
) -> School21Client:
    return School21Client(
        config=s21_config,
        auth_middleware=s21_auth_middleware_mock,
        retry_middleware=s21_retry_middleware_mock,
    )


@pytest.fixture
def session() -> aiohttp.ClientSession:
    session = create_autospec(aiohttp.ClientSession, instance=True, spec_set=True)
    session.closed = False
    return session


@pytest.fixture
def request_mock(session: aiohttp.ClientSession) -> aiohttp.ClientRequest:
    request = MagicMock(spec=aiohttp.ClientRequest)
    request.session = session
    request.url = aiohttp.client_reqrep.URL("https://platform.21-school.ru/services/graphql")
    request.headers = {}
    return request


@pytest.fixture
def response_mock() -> aiohttp.ClientResponse:
    return MagicMock(spec=aiohttp.ClientResponse)
