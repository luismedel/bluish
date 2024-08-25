import logging

from bluish.core import JobContext, ProcessResult, action, fatal


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
def docker_build(ctx: JobContext) -> ProcessResult:
    inputs = ctx.get_inputs()

    dockerfile = inputs.get("dockerfile", "Dockerfile")

    options = f"-f '{dockerfile}'"
    options += _build_list_opt("-t", inputs.get("tags"))

    context = inputs.get("context", ctx.get_var("pipe.working_dir"))
    return ctx.run(f"docker build {options} {context}")


@action("docker/get-pid", required_inputs=["name"])
def docker_get_pid(ctx: JobContext) -> ProcessResult:
    inputs = ctx.get_inputs()
    name = inputs["name"]
    return ctx.run(f"docker ps -f name={name} --quiet")


@action("docker/run", required_inputs=["image", "name"])
def docker_run(ctx: JobContext) -> ProcessResult:
    inputs = ctx.get_inputs()
    image = inputs["image"]
    name = inputs["name"]
    fail_if_running = inputs.get("fail_if_running", True)

    container_pid = ctx.run(
        f"docker ps -f name={name} --quiet", fail=False
    ).stdout.strip()
    if container_pid:
        if fail_if_running:
            fatal(
                f"Container with name {name} is already running with id {container_pid}."
            )
        else:
            logging.info(
                f"Container with name {name} is already running with id {container_pid}."
            )
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

        container_pid = ctx.run(f"docker run {options} {image}").stdout.strip()

    return ProcessResult(container_pid)


@action("docker/create-network", required_inputs=["name"])
def docker_create_network(ctx: JobContext) -> ProcessResult:
    inputs = ctx.get_inputs()
    name = inputs["name"]
    fail_if_exists = inputs.get("fail_if_exists", True)

    network_id = ctx.run(
        f"docker network ls -f name={name} --quiet", fail=False
    ).stdout.strip()
    if network_id:
        if fail_if_exists:
            fatal(f"Network {name} already exists with id {network_id}.")
        else:
            logging.info(f"Network {name} already exists with id {network_id}.")
    else:
        options = "--attachable"
        for opt in ["label"]:
            options += _build_opt(f"--{opt}", inputs.get(opt))
        for flag in ["ingress", "internal"]:
            options += _build_flag(f"--{flag}", inputs.get(flag))
        network_id = ctx.run(f"docker network create {options} {name}").stdout.strip()
        logging.info(f"Network {name} created with id {network_id}.")

    return ProcessResult(network_id)
