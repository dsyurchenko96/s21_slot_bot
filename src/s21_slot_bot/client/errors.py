from enum import StrEnum

from s21_slot_bot.common.error import Error


class School21ErrorType(StrEnum):
    NO_P2P_POINTS = "TEAM_MEMBER_HAS_NOT_ENOUGH_PEER_REVIEW_POINTS"
    SLOT_NOT_FOUND = "TIMETABLE_TIMESLOTS_NOT_FOUND"
    DEFAULT_ERROR = "DEFAULT_UI_ERROR_MESSAGE"


class School21Error(Error): ...


class School21LoginError(School21Error):
    default_help_text = "проверь правильность логина и пароля"


class School21NoPointsError(School21Error): ...


class School21SlotNotFoundError(School21Error): ...


class School21ParsingError(School21Error):
    default_help_text = "заведи баг"
