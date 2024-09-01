
import base64
import os
from bluish.core import StepContext, action
from bluish.process import ProcessResult, write_file


GIT_KEY_FILE = "$HOME/.ssh/git-key"


def run_git_command(command: str, step: StepContext) -> ProcessResult:
    PREAMBLE = f"export GIT_SSH_COMMAND='ssh -i {GIT_KEY_FILE} -o IdentitiesOnly=yes -o StrictHostKeychecking=no';"
    return step.job.run_command(f"{PREAMBLE} {command}", step)


def prepare_environment(step: StepContext) -> None:
    ssh_key: str | None = None

    ssh_key_file = step.inputs.get("ssh_key_file")
    if ssh_key_file:
        with open(ssh_key_file, "r") as f:
            ssh_key = f.read()

    if not ssh_key:
        ssh_key = step.inputs.get("ssh_key")

    if ssh_key:
        b64 = base64.b64encode(ssh_key.encode()).decode()
        _ = step.job.run_command(f"mkdir -p ~/.ssh", step)
        _ = step.job.run_command(f"echo {b64} | base64 -di - > {GIT_KEY_FILE}", step, shell="sh", echo_command=False)
        _ = step.job.run_command(f"chmod 600 {GIT_KEY_FILE}", step)
        _ = step.job.run_command(f"apt update && apt install git -y", step, echo_output=False)
        step.attrs._needs_cleanup = True


def cleanup_environment(step: StepContext) -> None:
    if not step.attrs._needs_cleanup:
        return
    try:
        _ = step.job.run_command(f"rm -f {GIT_KEY_FILE}", step)
    except Exception:
        pass


@action("git/checkout", required_inputs=["repository"])
def git_checkout(step: StepContext) -> ProcessResult:
    try:
        prepare_environment(step)

        inputs = step.inputs

        repository: str = inputs["repository"]
        repo_name = os.path.basename(repository)
        result = run_git_command(f"git clone {repository} ./{repo_name}", step)

        # Update the current job working dir to the newly cloned repo
        wd = step.job.get_value("env.WORKING_DIR", "")
        step.job.set_value("env.WORKING_DIR", f"{wd}/{repo_name}")

        return result
    finally:
        cleanup_environment(step)
