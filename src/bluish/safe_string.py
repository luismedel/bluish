from typing import cast


class SafeString(str):
    """A string with two values: one for logging and one for the actual value."""

    def __new__(cls, value: str, redacted_value: str | None = None) -> "SafeString":
        result = cast(SafeString, super().__new__(cls, value))
        result.redacted_value = redacted_value or value
        return result

    @property
    def redacted_value(self) -> str:
        return getattr(self, "_redacted_value", self)

    @redacted_value.setter
    def redacted_value(self, value: str) -> None:
        self._redacted_value = value
