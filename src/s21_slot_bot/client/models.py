from datetime import datetime
from enum import StrEnum

from pydantic import BaseModel, ConfigDict, Field
from pydantic.alias_generators import to_camel


class ContentType(StrEnum):
    APPLICATION_JSON = "application/json"
    APPLICATION_FORM_URL_ENCODED = "application/x-www-form-urlencoded"


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


class S21Model(BaseModel):
    model_config = ConfigDict(alias_generator=to_camel, populate_by_name=True)


class Project(S21Model):
    id: int | None = Field(default=None, description="Project ID", alias="goalId")
    name: str = Field(description="Project name", alias="goalName")
    course_id: int | None = Field(default=None, description="Course ID", alias="localCourseId")
    status: ProjectStatus | None = Field(
        default=None, description="Current project status", alias="displayedCourseStatus"
    )

    num_reviews: int | None = Field(default=None, description="Current number of reviews for this project")


class TimeSlot(S21Model):
    start: datetime = Field(description="Start time of the available slot")
    end: datetime = Field(description="End time of the available slot")
    valid_start_times: list[datetime] = Field(
        description="List of valid time slots that can be booked between start "
        "and end time, considering the duration of the review"
    )
    staff_slot: bool = Field(description="Flag showing whether this is a staff or peer slot")


class ReviewInfo(S21Model):
    needed: int = Field(description="Number of reviews needed for the project", alias="reviewByStudentCount")
    booked: int = Field(
        description="Number of reviews already booked for the project", alias="relevantReviewByStudentsCount"
    )


class SlotsInfo(S21Model):
    check_duration: int = Field(description="Duration of a review in minutes")
    review_info: ReviewInfo = Field(alias="projectReviewsInfo")
    time_slots: list[TimeSlot]
