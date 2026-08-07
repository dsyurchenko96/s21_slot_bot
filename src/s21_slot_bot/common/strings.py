from typing import Any, Callable


def ensure_str(field: Any, getter: Callable[..., str] | None = None, default: str = "-", **kwargs) -> str:
    getter = getter if getter is not None else lambda _: field
    try:
        value = getter(field, **kwargs)
        if value is None:
            return default
        return str(value)
    except Exception:
        return default


def backtick_wrap(text: str) -> str:
    return f"`{text}`"
