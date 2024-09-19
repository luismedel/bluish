import os

from bluish.action import action
from bluish.context import StepContext
from bluish.logging import error, info
from bluish.process import ProcessResult, install_package


def run_git_command(command: str, step: StepContext) -> ProcessResult:
    preamble: str = ""

    key_file = step.inputs.get("ssh_key_file")
    if key_file:
        preamble = f"export GIT_SSH_COMMAND='ssh -i {key_file} -o IdentitiesOnly=yes -o StrictHostKeychecking=no';"

    return step.job.exec(f"{preamble} {command}", step)


def prepare_environment(step: StepContext) -> ProcessResult:
    if step.job.exec("which git", step).failed:
        info("Installing git...")
        result = install_package(step.job.runs_on_host, ["git"])
        if result.failed:
            error(f"Failed to install git. Error: {result.error}")
            return result

    return ProcessResult()


def cleanup_environment(step: StepContext) -> None:
    pass


@action(
    "git/checkout",
    required_inputs=["repository"],
    sensitive_inputs=["ssh_key_file", "password"],
)
def git_checkout(step: StepContext) -> ProcessResult:
    try:
        result = prepare_environment(step)
        if result.failed:
            return result

        inputs = step.inputs

        options = ""
        if "depth" in inputs:
            options += f"--depth {inputs['depth']}"
        else:
            options += "--depth 1"

        if "branch" in inputs:
            options += f" --branch {inputs['branch']}"

        repository: str = inputs["repository"]
        protocol, repository = repository.split("://", maxsplit=1)
        repo_name = os.path.basename(repository)

        if step.attrs.token:
            command = f"git clone {protocol}://{step.attrs.token}@{repository} {options} ./{repo_name}"
        elif step.attrs.username and step.attrs.password:
            command = f"git clone {protocol}://{step.attrs.username}:{step.attrs.password}@{repository} {options} ./{repo_name}"
        elif step.attrs.ssh_key_file:
            key_file = step.inputs["ssh_key_file"]
            command = f"ssh-agent sh -c 'ssh-add {key_file}; git clone git@{repository} ./{repo_name}'"
        else:
            repository = f"{protocol}://{repository}"
            command = f"git clone {repository} {options} ./{repo_name}"

        info(f"Cloning repository: {repository}...")
        clone_result = run_git_command(command, step)
        if clone_result.failed:
            error(f"Failed to clone repository: {clone_result.error}")
            return clone_result

        # Update the current job working dir to the newly cloned repo
        info(f"Setting working directory to: {repo_name}...")
        wd = step.get_inherited_attr("working_directory", ".")
        step.job.set_attr("working_directory", f"{wd}/{repo_name}")

        return clone_result
    finally:
        cleanup_environment(step)
