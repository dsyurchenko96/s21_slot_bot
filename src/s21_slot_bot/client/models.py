from datetime import datetime
from enum import StrEnum
from typing import Annotated
from zoneinfo import ZoneInfo

from pydantic import (
    AfterValidator,
    AliasPath,
    AwareDatetime,
    BaseModel,
    BeforeValidator,
    ConfigDict,
    Field,
    NonNegativeInt,
    PositiveInt,
)
from pydantic.alias_generators import to_camel
from pydantic_core.core_schema import ValidationInfo

from s21_slot_bot.client.consts import MAX_REQUIRED_REVIEWS

type CoercedStr = Annotated[str, BeforeValidator(lambda val: str(val) if isinstance(val, int) else val)]

type RequiredReviews = Annotated[PositiveInt, Field(le=MAX_REQUIRED_REVIEWS)]
type BookedReviews = Annotated[NonNegativeInt, Field(le=MAX_REQUIRED_REVIEWS)]


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
    id: CoercedStr | None = Field(default=None, description="Project ID", alias="goalId")
    name: str = Field(description="Project name", alias="goalName")
    course_id: CoercedStr | None = Field(default=None, description="Course ID", alias="localCourseId")
    course_status: ProjectStatus | None = Field(
        default=None, description="Current course status", alias="displayedCourseStatus"
    )
    status: ProjectStatus | None = Field(default=None, description="Current project status", alias="goalStatus")


class ProjectExtended(Project):
    review_info: ReviewInfo


class TimeSlot(S21Model):
    start: AwareDatetime = Field(description="Start time of the available slot")
    end: AwareDatetime = Field(description="End time of the available slot")
    valid_start_times: list[AwareDatetime] = Field(
        description="List of valid time slots that can be booked between start "
        "and end time, considering the duration of the review"
    )
    staff_slot: bool = Field(description="Flag showing whether this is a staff or peer slot")


class ReviewInfo(S21Model):
    required: RequiredReviews = Field(
        description="Number of reviews required for the project", alias="reviewByStudentCount"
    )
    booked: BookedReviews = Field(
        description="Number of reviews already booked for the project", alias="relevantReviewByStudentsCount"
    )


class BookingBase(S21Model):
    answer_id: str = Field(description="ID required to book a slot for a given project")
    project_id: str = Field(description="Project ID", validation_alias=AliasPath("task", "goalId"))
    project_name: str = Field(description="Project name", validation_alias=AliasPath("task", "goalName"))
    start: AwareDatetime = Field(
        description="Start time of the booked slot", validation_alias=AliasPath("eventSlot", "start")
    )


class Booking(BookingBase):
    id: str = Field(description="Booking ID")
    is_online: bool = Field(default=True, description="Whether the review takes place online or not")
    url: str | None = Field(default=None, description="URL of the online review call", alias="vcLinkUrl")


class DryBooking(BookingBase):
    dry_run_id: str = Field(description="Booking ID generated during a dry-run")
    is_staff_slot: bool = Field(default=False, description="Whether the found slot was opened by staff or by a student")


class SlotsInfo(S21Model):
    check_duration: int = Field(description="Duration of a review in minutes")
    review_info: ReviewInfo = Field(alias="projectReviewsInfo")
    time_slots: list[TimeSlot]
