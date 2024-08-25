from typing import Any


def ensure_dict(value: Any) -> dict[str, Any] | None:
    if value is None:
        return None
    elif isinstance(value, list):
        result = {}
        for d in value:
            if len(d) > 1:
                raise ValueError("Expected a list of dictionaries with one key-value pair")
            result.update(d)
        return result
    elif isinstance(value, dict):
        return value
    else:
        raise ValueError(f"Expected a list or dict, got {type(value)}")
