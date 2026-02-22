from dataclasses import dataclass
from enum import StrEnum


@dataclass
class Tokens:
    access_token: str
    refresh_token: str
    expires_at_epoch: float


class ContentType(StrEnum):
    APPLICATION_JSON = "application/json"
    APPLICATION_FORM_URL_ENCODED = "application/x-www-form-urlencoded"
