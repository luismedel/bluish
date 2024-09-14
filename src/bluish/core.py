from enum import Enum


class ExecutionStatus(Enum):
    PENDING = "PENDING"
    RUNNING = "RUNNING"
    FINISHED = "FINISHED"
    SKIPPED = "SKIPPED"


def init_commands() -> None:
    import bluish.commands.core  # noqa
    import bluish.commands.linux  # noqa
    import bluish.commands.docker  # noqa
    import bluish.commands.git  # noqa

    pass
