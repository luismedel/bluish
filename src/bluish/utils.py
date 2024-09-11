# The dreaded "utils" module, where lazy programmers put all the miscellaneous functions.


def decorate_for_log(value: str, decoration: str = "    ") -> str:
    """Decorates a multiline string for pretty logging."""

    if "\n" not in value:
        return f"{decoration}value"

    lines = value.splitlines(keepends=True)
    return "\n" + "".join(f"{decoration}{line}" for line in lines)
