import os

# TODO: move to AppConfig
DEFAULT_JITTER_SEC = int(os.getenv("POLL_JITTER_SEC", "8"))

MIN_REQUIRED_REVIEWS = 1
MAX_REQUIRED_REVIEWS = 3
