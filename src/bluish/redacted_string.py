class RedactedString(str):
    """A string with two values: one for logging and one for the actual value."""

    @property
    def redacted_value(self) -> str:
        return getattr(self, "_redacted_value", self)

    @redacted_value.setter
    def redacted_value(self, value: str) -> None:
        self._redacted_value = value
