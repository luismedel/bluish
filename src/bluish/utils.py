from typing import Any


def decorate_for_log(value: str, decoration: str = "    ") -> str:
    """Decorates a multiline string for pretty logging."""
    
    if "\n" not in value:
        return value
    first, *rest = value.splitlines(keepends=True)
    return "".join([first] + [f"{decoration}{line}" for line in rest])
