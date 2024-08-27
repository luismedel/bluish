import logging

from bluish.core import ProcessError, ProcessResult, StepContext, action


def _build_list_opt(opt: str, items: list[str] | None) -> str:
    if not items:
        return ""
    result = " ".join(f"{opt} {o}" for o in items)
    return f" {result}"


def _build_opt(opt: str, value: str | None) -> str:
    if not value:
        return ""
    return f" {opt} {value}"


def _build_flag(flag: str, value: bool | None) -> str:
    return "" if not value else f" {flag}"


@action("docker/build", required_inputs=["tags"])
def docker_build(step: StepContext) -> ProcessResult:
    inputs = step.attrs._with

    dockerfile = inputs.get("dockerfile", "Dockerfile")

    options = f"-f '{dockerfile}'"
    options += _build_list_opt("-t", inputs.get("tags"))

    context = inputs.get("context", step.try_get_value("env.WORKING_DIR"))
    return step.pipe.run_command(f"docker build {options} {context}", step)


@action("docker/get-pid", required_inputs=["name"])
def docker_get_pid(step: StepContext) -> ProcessResult:
    name = step.attrs._with["name"]
    return step.pipe.run_command(f"docker ps -f name={name} --quiet", step)


@action("docker/run", required_inputs=["image", "name"])
def docker_run(step: StepContext) -> ProcessResult:
    inputs = step.attrs._with

    image = inputs["image"]
    name = inputs["name"]
    fail_if_running = inputs.get("fail_if_running", True)

    result = step.pipe.run_command(f"docker ps -f name={name} --quiet", step)
    container_pid = result.stdout.strip()
    if container_pid:
        msg = f"Container with name {name} is already running with id {container_pid}."
        if fail_if_running:
            raise ProcessError(result, msg)
        logging.info(msg)
    else:
        options = "--detach"
        options += _build_list_opt("-p", inputs.get("ports"))
        options += _build_list_opt("-v", inputs.get("volumes"))
        options += _build_list_opt("-e", inputs.get("env"))
        options += _build_list_opt("--env-file", inputs.get("env_file"))
        options += _build_flag("--rm", inputs.get("remove_on_exit"))

        for opt in ["name", "network", "label", "pull", "user"]:
            options += _build_opt(f"--{opt}", inputs.get(opt))
        for flag in ["quiet"]:
            options += _build_flag(f"--{flag}", inputs.get(flag))

        container_pid = step.pipe.run_command(
            f"docker run {options} {image}", step
        ).stdout.strip()

    return ProcessResult(container_pid)


@action("docker/create-network", required_inputs=["name"])
def docker_create_network(step: StepContext) -> ProcessResult:
    inputs = step.attrs._with
    name = inputs["name"]
    fail_if_exists = inputs.get("fail_if_exists", True)

    result = step.pipe.run_command(f"docker network ls -f name={name} --quiet", step)

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
        network_id = step.pipe.run_command(
            f"docker network create {options} {name}", step
        ).stdout.strip()
        logging.info(f"Network {name} created with id {network_id}.")

    return ProcessResult(network_id)
