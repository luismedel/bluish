import logging
import subprocess

from bluish.core import ProcessError, ProcessResult, StepContext, action


def _build_list_opt(opt: str, items: list[str] | None) -> str:
    if not items:
        return ""
    if isinstance(items, str):
        items = [items]
    result = " ".join(f"{opt} {o}" for o in items)
    return f" {result}"


def _build_opt(opt: str, value: str | None) -> str:
    if not value:
        return ""
    return f" {opt} {value}"


def _build_flag(flag: str, value: bool | None) -> str:
    return "" if not value else f" {flag}"


class EmptyPIDError(Exception):
    pass


def run_and_get_pid(command: str, step: StepContext) -> str:
    result = step.job.run_command(command, step)
    return result.stdout.strip()


def docker_ps(
    step: StepContext, name: str | None = None, pid: str | None = None
) -> ProcessResult:
    filter = f"name={name}" if name else f"id={pid}"
    return step.job.run_command(f"docker ps -f {filter} --all --quiet", step)


@action("docker/build", required_inputs=["tags"])
def docker_build(step: StepContext) -> ProcessResult:
    inputs = step.inputs

    dockerfile = inputs.get("dockerfile", "Dockerfile")

    options = f"-f '{dockerfile}'"
    options += _build_list_opt("-t", inputs.get("tags"))

    context = inputs.get("context", step.try_get_value("env.WORKING_DIR"))
    return step.job.run_command(f"docker build {options} {context}", step)


@action("docker/get-pid", required_inputs=["name"])
def docker_get_pid(step: StepContext) -> ProcessResult:
    name = step.inputs["name"]
    return ProcessResult(docker_ps(step, name=name).stdout.strip())


@action("docker/run", required_inputs=["image", "name"])
def docker_run(step: StepContext) -> ProcessResult:
    inputs = step.inputs

    image = step.expand_expr(inputs["image"])
    name = step.expand_expr(inputs["name"])
    fail_if_running = inputs.get("fail_if_running", True)

    container_pid = docker_ps(step, name=name).stdout.strip()
    if container_pid:
        msg = f"Container with name {name} is already running with id {container_pid}."
        if fail_if_running:
            raise ProcessError(None, msg)
        logging.info(msg)
        return ProcessResult(container_pid)

    options = f"--name {name} --detach"
    options += _build_list_opt("-p", inputs.get("ports"))
    options += _build_list_opt("-v", inputs.get("volumes"))
    options += _build_list_opt("-e", inputs.get("env"))
    options += _build_list_opt("--env-file", inputs.get("env_file"))
    options += _build_flag("--rm", inputs.get("remove"))

    for opt in ["network", "label", "pull", "user"]:
        options += _build_opt(f"--{opt}", inputs.get(opt))
    for flag in ["quiet"]:
        options += _build_flag(f"--{flag}", inputs.get(flag))

    container_pid = run_and_get_pid(f"docker run {options} {image}", step)
    return ProcessResult(container_pid)


@action("docker/stop", required_inputs=["name|pid"])
def docker_stop(step: StepContext) -> ProcessResult:
    inputs = step.inputs

    name = inputs.get("name")
    container_pid = inputs.get("pid")
    input_attr = f"name {name}" if name else f"pid {container_pid}"
    fail_if_not_found = inputs.get("fail_if_not_found", True)
    remove = inputs.get("remove", False)
    issue_stop = True

    container_pid = docker_ps(step, name=name, pid=container_pid).stdout.strip()
    if not container_pid:
        msg = f"Can't find a running container with {input_attr}."
        if fail_if_not_found:
            raise ProcessError(None, msg)
        issue_stop = False
        logging.warning(msg)
        # If don't need to remove the container, we can stop here
        if not remove:
            return ProcessResult("")

    if issue_stop:
        options = ""
        for opt in ["signal", "time"]:
            options += _build_opt(f"--{opt}", inputs.get(opt))

        if not run_and_get_pid(
            f"docker container stop {options} {container_pid}", step
        ):
            logging.warning(f"Failed to stop container with {input_attr}.")

    if not run_and_get_pid(f"docker container rm {options} {container_pid}", step):
        logging.warning(f"Failed to remove container with {input_attr}.")

    return ProcessResult(container_pid)


@action("docker/exec", required_inputs=["name|pid", "run"])
def docker_exec(step: StepContext) -> ProcessResult:
    inputs = step.inputs

    name = inputs.get("name")
    container_pid = inputs.get("pid")
    command = inputs["run"]
    input_attr = f"name {name}" if name else f"pid {container_pid}"

    container_pid = docker_ps(step, name=name, pid=container_pid).stdout.strip()
    if not container_pid:
        raise ProcessError(None, f"Can't find a running container with {input_attr}.")

    options = ""
    options += _build_list_opt("-e", inputs.get("env"))
    options += _build_list_opt("--env-file", inputs.get("env_file"))

    for opt in ["workdir"]:
        options += _build_opt(f"--{opt}", inputs.get(opt))

    output = ""

    i = 0
    command_lines = command.splitlines()
    while i < len(command_lines):
        line = command_lines[i].strip()
        while line.endswith("\\"):
            i += 1
            line = line[:-1] + command_lines[i].strip()
        i += 1

        result = step.job.run_command(
            f"docker exec {options} {container_pid} {line}", step
        )
        output += result.stdout
        if result.returncode != 0:
            # TODO: This is a hack to get the command that failed
            cp = subprocess.CompletedProcess(
                command, result.returncode, output, result.stderr
            )
            return ProcessResult(cp)

    return ProcessResult(output)


@action("docker/create-network", required_inputs=["name"])
def docker_create_network(step: StepContext) -> ProcessResult:
    inputs = step.inputs

    name = inputs["name"]
    fail_if_exists = inputs.get("fail_if_exists", True)

    result = step.job.run_command(f"docker network ls -f name={name} --quiet", step)

    network_id = result.stdout.strip()
    if network_id:
        msg = f"Network {name} already exists with id {network_id}."
        if fail_if_exists:
            raise ProcessError(result, msg)
        logging.info(msg)
    else:
        options = "--attachable"
        for opt in ["label"]:
            options += _build_opt(f"--{opt}", inputs.get(opt))
        for flag in ["ingress", "internal"]:
            options += _build_flag(f"--{flag}", inputs.get(flag))
        network_id = step.job.run_command(
            f"docker network create {options} {name}", step
        ).stdout.strip()
        logging.info(f"Network {name} created with id {network_id}.")

    return ProcessResult(network_id)
