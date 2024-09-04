import logging

# TODO: Fix circular import if we impòrt StepContext and JobContext from bluish.core


def decorate_for_log(value: str, decoration: str = "    ") -> str:
    """Decorates a multiline string for pretty logging."""

    if "\n" not in value:
        return value
    lines = value.splitlines(keepends=True)
    return "\n" + "".join(f"{decoration}{line}" for line in lines)


def _prepare_message(ctx, message: str) -> str:
    """Stub to add more context to the log message."""
    return message


def debug(ctx, message: str) -> None:
    logging.debug(_prepare_message(ctx, message))


def info(ctx, message: str) -> None:
    logging.info(_prepare_message(ctx, message))


def warning(ctx, message: str) -> None:
    logging.warning(_prepare_message(ctx, message))


def error(ctx, message: str) -> None:
    logging.error(_prepare_message(ctx, message))
