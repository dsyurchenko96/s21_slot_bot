from typing import Any, Callable


def ensure_str(field: Any, getter: Callable[[Any], str] | None = None, default: str = "-") -> str:
    getter = getter if getter is not None else lambda _: field
    try:
        value = getter(field)
        if value is None:
            return default
        return str(value)
    except Exception:
        return default


def escape_str(text: str) -> str:
    return f"`{text}`"
