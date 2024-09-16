# The dreaded "utils" module, where lazy programmers put all the miscellaneous functions.


from bluish.redacted_string import RedactedString


def safe_string(value: str | RedactedString) -> str:
    """Returns the string value of a RedactedString."""
    if isinstance(value, RedactedString):
        return value.redacted_value
    else:
        return value


def decorate_for_log(value: str | RedactedString, decoration: str = "    ") -> str:
    """Decorates a multiline string for pretty logging."""

    def decorate(value: str, decoration: str) -> str:
        value = value.rstrip()
        if not value:
            return value

        if "\n" not in value:
            return f"{decoration}{value}"
        lines = value.rstrip().splitlines(keepends=True)
        return "\n" + "".join(f"{decoration}{line}" for line in lines)

    if isinstance(value, RedactedString):
        result = RedactedString(value)
        result.redacted_value = decorate(value.redacted_value, decoration)
        return result
    else:
        return decorate(value, decoration)
