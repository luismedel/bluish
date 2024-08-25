from typing import Any


def ensure_list(value: Any) -> list[Any] | None:
    if value is None:
        return None
    elif isinstance(value, list):
        return value
    else:
        return [value]
