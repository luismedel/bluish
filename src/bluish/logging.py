from logging import critical as logging_critical
from logging import debug as logging_debug
from logging import error as logging_error
from logging import exception as logging_exception
from logging import info as logging_info
from logging import log as logging_log
from logging import warning as logging_warning
from typing import Any

from bluish.redacted_string import RedactedString


def info(message: str, *args: Any, **kwargs: Any) -> None:
    msg = message.redacted_value if isinstance(message, RedactedString) else message
    logging_info(msg, *args, **kwargs)


def error(message: str, *args: Any, **kwargs: Any) -> None:
    msg = message.redacted_value if isinstance(message, RedactedString) else message
    logging_error(msg, *args, **kwargs)


def warning(message: str, *args: Any, **kwargs: Any) -> None:
    msg = message.redacted_value if isinstance(message, RedactedString) else message
    logging_warning(msg, *args, **kwargs)


def debug(message: str, *args: Any, **kwargs: Any) -> None:
    msg = message.redacted_value if isinstance(message, RedactedString) else message
    logging_debug(msg, *args, **kwargs)


def critical(message: str, *args: Any, **kwargs: Any) -> None:
    msg = message.redacted_value if isinstance(message, RedactedString) else message
    logging_critical(msg, *args, **kwargs)


def exception(message: str, *args: Any, **kwargs: Any) -> None:
    msg = message.redacted_value if isinstance(message, RedactedString) else message
    logging_exception(msg, *args, **kwargs)


def log(level: int, message: str, *args: Any, **kwargs: Any) -> None:
    msg = message.redacted_value if isinstance(message, RedactedString) else message
    logging_log(level, msg, *args, **kwargs)
