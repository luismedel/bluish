from enum import Enum


class ExecutionStatus(Enum):
    PENDING = "PENDING"
    RUNNING = "RUNNING"
    FINISHED = "FINISHED"
    SKIPPED = "SKIPPED"


def init_commands() -> None:
    import bluish.actions.core  # noqa
    import bluish.actions.linux  # noqa
    import bluish.actions.macos  # noqa
    import bluish.actions.docker  # noqa
    import bluish.actions.git  # noqa

    actions = [
        bluish.actions.core.RunCommand,
        bluish.actions.core.ExpandTemplate,
        bluish.actions.core.DownloadFile,
        bluish.actions.core.UploadFile,
        bluish.actions.linux.InstallPackages,
        bluish.actions.macos.InstallPackages,
        bluish.actions.docker.Build,
        bluish.actions.docker.Run,
        bluish.actions.docker.Login,
        bluish.actions.docker.Logout,
        bluish.actions.docker.GetPid,
        bluish.actions.docker.CreateNetwork,
        bluish.actions.docker.Exec,
        bluish.actions.docker.Stop,
        bluish.actions.git.Checkout,
    ]

    from bluish.actions import register_action

    for klass in actions:
        register_action(klass)
