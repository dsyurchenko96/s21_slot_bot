from typing import Annotated

from pydantic import PositiveInt, Field

from s21_slot_bot.app.consts import MIN_REQUIRED_REVIEWS, MAX_REQUIRED_REVIEWS, MIN_INTERVAL_SEC, MAX_INTERVAL_SEC, \
    MIN_NUM_BOTS, MAX_NUM_BOTS

RequiredReviews = Annotated[PositiveInt, Field(ge=MIN_REQUIRED_REVIEWS, le=MAX_REQUIRED_REVIEWS)]
IntervalSec = Annotated[PositiveInt, Field(ge=MIN_INTERVAL_SEC, le=MAX_INTERVAL_SEC)]
NumBots = Annotated[PositiveInt, Field(ge=MIN_NUM_BOTS, le=MAX_NUM_BOTS)]
