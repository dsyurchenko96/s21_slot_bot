from http import HTTPStatus

import pytest

from s21_slot_bot.app.errors import BotRuntimeError
from s21_slot_bot.client.errors import School21Error


class TestError:
    def test_error_effective_status_inherited_implicit_context(self):
        with pytest.raises(BotRuntimeError) as exc_info:
            try:
                err = School21Error("not found", status=HTTPStatus.NOT_FOUND)
                raise err
            except School21Error:
                raise BotRuntimeError("run!")
        error = exc_info.value
        assert error.effective_status == HTTPStatus.NOT_FOUND

    def test_error_effective_status_overridden_explicit_cause(self):
        with pytest.raises(BotRuntimeError) as exc_info:
            try:
                err = School21Error("not found", status=HTTPStatus.NOT_FOUND)
                raise err
            except School21Error as e:
                raise BotRuntimeError("run!", status=HTTPStatus.INTERNAL_SERVER_ERROR) from e
        error = exc_info.value
        assert error.effective_status == HTTPStatus.INTERNAL_SERVER_ERROR
