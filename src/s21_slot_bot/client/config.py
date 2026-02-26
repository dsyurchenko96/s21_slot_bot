from pydantic import Field, SecretStr
from pydantic_settings import BaseSettings


class S21ClientConfig(BaseSettings):
    username: str = Field(alias="S21_USERNAME")
    password: SecretStr = Field(alias="S21_PASSWORD")
    timeout_sec: int = Field(alias="S21_TIMEOUT_SEC", default=25)
