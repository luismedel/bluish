import os

from bluish.core import StepContext, action
from bluish.process import ProcessError, ProcessResult


def run_git_command(command: str, step: StepContext) -> ProcessResult:
    preamble: str = ""

    key_file = step.inputs.get("ssh_key_file")
    if key_file:
        preamble = f"export GIT_SSH_COMMAND='ssh -i {key_file} -o IdentitiesOnly=yes -o StrictHostKeychecking=no';"

    return step.job.run_command(f"{preamble} {command}", step)


def prepare_environment(step: StepContext) -> None:
    if step.job.run_internal_command("which git", step).returncode != 0:
        is_alpine = step.job.run_internal_command("which apk", step).returncode == 0

        command = (
            "apk update && apk add git"
            if is_alpine
            else "apt update && apt install git -y"
        )
        result = step.job.run_internal_command(command, step)
        if result.returncode != 0:
            raise ProcessError(None, f"Failed to install git. Error: {result.stdout}")


def cleanup_environment(step: StepContext) -> None:
    pass


@action("git/checkout", required_inputs=["repository"])
def git_checkout(step: StepContext) -> ProcessResult:
    try:
        prepare_environment(step)

        inputs = step.inputs

        options = ""
        if "depth" in inputs:
            options += f"--depth {inputs['depth']}"
        else:
            options += "--depth 1"

        if "branch" in inputs:
            options += f" --branch {inputs['branch']}"

        repository: str = inputs["repository"]
        repo_name = os.path.basename(repository)
        result = run_git_command(
            f"git clone {repository} {options} ./{repo_name}", step
        )

        # Update the current job working dir to the newly cloned repo
        wd = step.job.get_value("env.WORKING_DIR", "")
        step.job.set_value("env.WORKING_DIR", f"{wd}/{repo_name}")

        return result
    finally:
        cleanup_environment(step)
