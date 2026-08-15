from pydantic import Field, NonNegativeInt, PositiveInt, SecretStr
from pydantic_settings import BaseSettings


class S21ClientConfig(BaseSettings):
    username: str = Field(alias="S21_USERNAME")
    password: SecretStr = Field(alias="S21_PASSWORD")
    timeout_sec: NonNegativeInt = Field(alias="S21_TIMEOUT_SEC", default=25)
    max_request_retries: PositiveInt = Field(
        alias="S21_MAX_REQUEST_RETRIES",
        description="Maximum number of request retries. Set to 1 to disable retries",
        default=3,
    )
    retry_delay_sec: NonNegativeInt = Field(
        alias="S21_RETRY_DELAY_SEC",
        description="Initial delay (in seconds) between retries, each consecutive delay is multiplied by the attempt number",
        default=2,
    )
