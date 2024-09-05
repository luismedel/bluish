import subprocess

from bluish.core import StepContext, action
from bluish.logging import decorate_for_log, error, info, warning
from bluish.process import ProcessResult


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
    result = step.job.exec(command, step)
    return result.stdout.strip() if result.returncode == 0 else ""


def docker_ps(
    step: StepContext, name: str | None = None, pid: str | None = None
) -> ProcessResult:
    filter = f"name={name}" if name else f"id={pid}"
    return step.job.exec(f"docker ps -f {filter} --all --quiet", step)


@action("docker/build", required_inputs=["tags"])
def docker_build(step: StepContext) -> ProcessResult:
    inputs = step.inputs

    dockerfile = inputs.get("dockerfile", "Dockerfile")

    options = f"-f '{dockerfile}'"
    options += _build_list_opt("-t", inputs.get("tags"))

    working_dir = step.get_inherited_attr("working_directory", ".")
    context = inputs.get("context", working_dir)
    return step.job.exec(f"docker build {options} {context}", step)


@action("docker/get-pid", required_inputs=["name"])
def docker_get_pid(step: StepContext) -> ProcessResult:
    name = step.inputs["name"]
    return ProcessResult(stdout=docker_ps(step, name=name).stdout.strip())


@action("docker/run", required_inputs=["image", "name"])
def docker_run(step: StepContext) -> ProcessResult:
    inputs = step.inputs

    image = inputs["image"]
    name = inputs["name"]

    info(step, f"Running container with image {image} and name {name}...")
    result = docker_ps(step, name=name)
    container_pid = result.stdout.strip()
    if container_pid:
        msg = f"Container with name {name} is already running with id {container_pid}."
        if inputs.get("fail_if_running", True):
            error(step, msg)
            return ProcessResult(returncode=1, stdout=container_pid)
        else:
            warning(step, msg)
            return ProcessResult(stdout=container_pid)

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
    info(step, f"Container started with id {container_pid}.")
    return ProcessResult(stdout=container_pid)


@action("docker/stop", required_inputs=["name|pid"])
def docker_stop(step: StepContext) -> ProcessResult:
    inputs = step.inputs

    name = inputs.get("name")
    container_pid = inputs.get("pid")
    input_attr = f"name {name}" if name else f"pid {container_pid}"
    remove_container = inputs.get("remove", False)
    stop_container = True

    info(step, f"Stopping container with {input_attr}...")

    result = docker_ps(step, name=name, pid=container_pid)
    container_pid = result.stdout.strip()
    if not container_pid:
        msg = f"Can't find a running container with {input_attr}."
        if inputs.get("fail_if_not_found", True):
            error(step, msg)
            return ProcessResult(returncode=1, stdout=container_pid)
        stop_container = False
        warning(step, msg)
        # If don't need to remove the container, we can stop here
        if not remove_container:
            return ProcessResult(stdout=container_pid)
    else:
        if name:
            info(step, f"Container found with id {container_pid}.")

    if stop_container:
        info(step, f"Stopping container with {input_attr}...")
        options = ""
        for opt in ["signal", "time"]:
            options += _build_opt(f"--{opt}", inputs.get(opt))
        _ = run_and_get_pid(f"docker container stop {options} {container_pid}", step)

    if remove_container:
        _ = run_and_get_pid(f"docker container rm {options} {container_pid}", step)

    return ProcessResult(stdout=container_pid)


@action("docker/exec", required_inputs=["name|pid", "run"])
def docker_exec(step: StepContext) -> ProcessResult:
    inputs = step.inputs

    name = inputs.get("name")
    container_pid = inputs.get("pid")
    command = inputs["run"]
    input_attr = f"name {name}" if name else f"pid {container_pid}"

    container_pid = docker_ps(step, name=name, pid=container_pid).stdout.strip()
    if not container_pid:
        error(step, f"Can't find a running container with {input_attr}.")
        return ProcessResult(returncode=1)

    options = ""
    options += _build_list_opt("-e", inputs.get("env"))
    options += _build_list_opt("--env-file", inputs.get("env_file"))

    for opt in ["workdir"]:
        options += _build_opt(f"--{opt}", inputs.get(opt))

    output = ""

    echo_commands = step.get_inherited_attr("echo_commands", True)
    echo_output = step.get_inherited_attr("echo_output", False)

    i = 0
    command_lines = command.splitlines()
    while i < len(command_lines):
        line = command_lines[i].strip()
        while line.endswith("\\"):
            i += 1
            line = line[:-1] + command_lines[i].strip()
        i += 1

        if echo_commands:
            info(step, line)
        result = step.job.exec(f"docker exec {options} {container_pid} {line}", step)
        output += result.stdout

        if echo_output:
            info(step, decorate_for_log(result.stdout))

        if result.failed:
            if echo_output and result.stderr:
                error(step, decorate_for_log(result.stderr))

            # TODO: This is a hack to get the command that failed
            cp = subprocess.CompletedProcess(
                command, result.returncode, output, result.stderr
            )
            return ProcessResult.from_subprocess_result(cp)

    return ProcessResult(stdout=output)


@action("docker/create-network", required_inputs=["name"])
def docker_create_network(step: StepContext) -> ProcessResult:
    inputs = step.inputs

    name = inputs["name"]

    info(step, f"Creating network {name}...")
    result = step.job.exec(f"docker network ls -f name={name} --quiet", step)

    network_id = result.stdout.strip()
    if network_id:
        msg = f"Network {name} already exists with id {network_id}."
        if inputs.get("fail_if_exists", True):
            error(step, msg)
            return ProcessResult(returncode=1)
        warning(step, msg)
    else:
        options = "--attachable"
        for opt in ["label"]:
            options += _build_opt(f"--{opt}", inputs.get(opt))
        for flag in ["ingress", "internal"]:
            options += _build_flag(f"--{flag}", inputs.get(flag))

        result = step.job.exec(f"docker network create {options} {name}", step)
        if result.failed:
            error(step, f"Failed to create network {name}.")
            return result

        network_id = result.stdout.strip()
        info(step, f"Network {name} created with id {network_id}.")

    return ProcessResult(stdout=network_id)
