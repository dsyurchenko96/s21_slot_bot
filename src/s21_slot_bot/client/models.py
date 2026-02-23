from enum import StrEnum

from pydantic import BaseModel, Field, ConfigDict
from pydantic.alias_generators import to_camel


class Tokens(BaseModel):
    access_token: str
    refresh_token: str
    expires_at_epoch: float


class ProjectStatus(StrEnum):
    UNAVAILABLE = "UNAVAILABLE"
    REGISTRATION_IS_OPEN = "REGISTRATION_IS_OPEN"
    READY_TO_START = "READY_TO_START"
    IN_PROGRESS = "IN_PROGRESS"
    P2P_EVALUATIONS = "P2P_EVALUATIONS"
    COMPLETED = "COMPLETED"


class Project(BaseModel):
    id: int | None = Field(default=None, description="Project ID", alias="goalId")
    name: str = Field(description="Project name", alias="goalName")
    course_id: int | None = Field(default=None, description="Course ID", alias="localCourseId")
    status: ProjectStatus | None = Field(
        default=None, description="Current project status", alias="displayedCourseStatus"
    )

    num_reviews: int | None = Field(default=None, description="Current number of reviews for this project")

    model_config = ConfigDict(alias_generator=to_camel, populate_by_name=True)


class ContentType(StrEnum):
    APPLICATION_JSON = "application/json"
    APPLICATION_FORM_URL_ENCODED = "application/x-www-form-urlencoded"
