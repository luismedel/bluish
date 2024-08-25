from typing import Any


def decorate_for_log(value: str, decoration: str = "    ") -> str:
    if "\n" not in value:
        return value
    first, *rest = value.splitlines(keepends=True)
    return "".join([first] + [f"{decoration}{line}" for line in rest])


def ensure_dict(value: Any) -> dict[str, Any] | None:
    if value is None:
        return None
    elif isinstance(value, list):
        result = {}
        for d in value:
            if len(d) > 1:
                raise ValueError(
                    "Expected a list of dictionaries with one key-value pair"
                )
            result.update(d)
        return result
    elif isinstance(value, dict):
        return value
    else:
        raise ValueError(f"Expected a list or dict, got {type(value)}")
