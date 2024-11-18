from typing import cast

import bluish.actions.base
import bluish.contexts.job
import bluish.contexts.step
import bluish.process
from bluish.logging import debug, error, info, warning
from bluish.schemas import STR_LIST
from bluish.utils import decorate_for_log


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


def _is_valid_docker_id(id: str) -> bool:
    return len(id) in (12, 64) and all(c in "0123456789abcdef" for c in id)


def run_and_get_pid(command: str, step: bluish.contexts.step.StepContext) -> str:
    job = cast(bluish.contexts.job.JobContext, step.parent)
    result = job.exec(command, step)
    return result.stdout.strip() if result.returncode == 0 else ""


def docker_ps(
    step: bluish.contexts.step.StepContext,
    name: str | None = None,
    pid: str | None = None,
) -> bluish.process.ProcessResult:
    filter = f"name={name}" if name else f"id={pid}"
    job = cast(bluish.contexts.job.JobContext, step.parent)
    return job.exec(f"docker ps -f {filter} --all --quiet", step)


class Login(bluish.actions.base.Action):
    FQN: str = "docker/login"

    INPUTS_SCHEMA = {
        "type": dict,
        "properties": {
            "username": str,
            "password": str,
            "registry": [str, None],
        },
    }

    SENSITIVE_INPUTS: tuple[str, ...] = ("password",)

    def run(
        self, step: bluish.contexts.step.StepContext
    ) -> bluish.process.ProcessResult:
        inputs = step.inputs

        username = inputs["username"]
        password = inputs["password"]
        registry = inputs.get("registry", "")

        command = step.expand_expr(
            f"docker login --username '{username}' --password '{password}' {registry}"
        )
        if step.get_inherited_attr("echo_commands", True):
            protected_command = (
                f"docker login --username '{username}' --password ******** {registry}"
            )
            info(f"Docker login:\n -> {protected_command}")

        job = cast(bluish.contexts.job.JobContext, step.parent)
        login_result = job.exec(command, step, stream_output=True)
        if login_result.failed:
            error(f"Login failed: {login_result.error}")
        return login_result


class Logout(bluish.actions.base.Action):
    FQN: str = "docker/logout"

    def run(
        self, step: bluish.contexts.step.StepContext
    ) -> bluish.process.ProcessResult:
        command = "docker logout"
        if step.get_inherited_attr("echo_commands", True):
            info("Logging out of Docker...")
        job = cast(bluish.contexts.job.JobContext, step.parent)
        return job.exec(command, step)


class Build(bluish.actions.base.Action):
    FQN: str = "docker/build"

    INPUTS_SCHEMA = {
        "type": dict,
        "properties": {
            "dockerfile": [str, None],
            "tags": [str, STR_LIST],
            "context": [str, None],
        },
    }

    def run(
        self, step: bluish.contexts.step.StepContext
    ) -> bluish.process.ProcessResult:
        inputs = step.inputs

        dockerfile = inputs.get("dockerfile", "Dockerfile")

        options = f"-f '{dockerfile}'"
        options += _build_list_opt("-t", inputs["tags"])
        working_dir = step.get_inherited_attr("working_directory", ".")
        context = inputs.get("context", working_dir)
        command = step.expand_expr(f"docker build {options} {context}")
        if step.get_inherited_attr("echo_commands", True):
            info(f"Building image:\n -> {command}")

        job = cast(bluish.contexts.job.JobContext, step.parent)
        build_result = job.exec(command, step, stream_output=True)
        if build_result.failed:
            error(f"Failed to build image: {build_result.error}")
        return build_result


class GetPid(bluish.actions.base.Action):
    FQN: str = "docker/get-pid"

    INPUTS_SCHEMA = {
        "type": dict,
        "properties": {
            "name": str,
        },
    }

    def run(
        self, step: bluish.contexts.step.StepContext
    ) -> bluish.process.ProcessResult:
        name = step.inputs["name"]

        ps_result = docker_ps(step, name=name)
        pid = ps_result.stdout.strip()
        if ps_result.failed or not _is_valid_docker_id(pid):
            error(f"Failed to get container id for {name}: {ps_result.error}")
            return (
                ps_result
                if ps_result.failed
                else bluish.process.ProcessResult(
                    returncode=1, stdout=ps_result.stdout, stderr=ps_result.stderr
                )
            )

        return bluish.process.ProcessResult(
            stdout=docker_ps(step, name=name).stdout.strip()
        )


class Run(bluish.actions.base.Action):
    FQN: str = "docker/run"

    INPUTS_SCHEMA = {
        "type": dict,
        "properties": {
            "image": str,
            "name": str,
            "fail_if_running": [bool, None],
            "ports": [str, list[str], None],
            "volumes": [str, list[str], None],
            "env": [str, list[str], None],
            "env_file": [str, list[str], None],
            "network": [str, None],
            "label": [str, list[str], None],
            "pull": [str, None],
            "user": [str, None],
            "remove": [bool, None],
            "quiet": [bool, None],
        },
    }

    def run(
        self, step: bluish.contexts.step.StepContext
    ) -> bluish.process.ProcessResult:
        inputs = step.inputs

        image = inputs["image"]
        name = inputs["name"]

        info(f"Running container with image {image} and name {name}...")
        ps_result = docker_ps(step, name=name)
        if ps_result.failed:
            error(
                f"Failed to check if container with name {name} is already running: {ps_result.error}"
            )
            return ps_result

        container_pid = ps_result.stdout.strip()
        if _is_valid_docker_id(container_pid):
            msg = f"Container with name {name} is already running with id {container_pid}."
            if inputs.get("fail_if_running", True):
                error(msg)
                return bluish.process.ProcessResult(returncode=1, stdout=container_pid)
            else:
                warning(msg)
                return bluish.process.ProcessResult(stdout=container_pid)

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

        job = cast(bluish.contexts.job.JobContext, step.parent)
        run_result = job.exec(f"docker run {options} {image}", step)
        if run_result.failed:
            error(f"Failed to start container with image {image}: {run_result.error}")
            return run_result

        container_pid = run_result.stdout.strip()
        if not _is_valid_docker_id(container_pid):
            error(f"Failed to get container id for {name}: {container_pid}")
            return bluish.process.ProcessResult(
                returncode=1, stdout=run_result.stdout, stderr=run_result.stderr
            )

        info(f"Container started with id {container_pid}.")
        return bluish.process.ProcessResult(stdout=container_pid)


class Stop(bluish.actions.base.Action):
    FQN: str = "docker/stop"

    INPUTS_SCHEMA = {
        "type": dict,
        "properties": {
            "name": [str, None],
            "pid": [str, None],
            "signal": [str, None],
            "time": [str, None],
            "remove": [bool, None],
            "fail_if_not_found": [bool, None],
        },
    }

    def run(
        self, step: bluish.contexts.step.StepContext
    ) -> bluish.process.ProcessResult:
        inputs = step.inputs

        name = inputs.get("name")
        container_pid = inputs.get("pid")
        input_attr = f"name {name}" if name else f"pid {container_pid}"
        remove_container = inputs.get("remove", False)
        stop_container = True

        job = cast(bluish.contexts.job.JobContext, step.parent)

        info(f"Stopping container with {input_attr}...")

        ps_result = docker_ps(step, name=name, pid=container_pid)
        if ps_result.failed:
            msg = f"Can't find a container with {input_attr}."
            if inputs.get("fail_if_not_found", True):
                error(msg)
                return ps_result
            else:
                warning(msg)
                stop_container = False
                # If don't need to remove the container, we can stop here
                if not remove_container:
                    return bluish.process.ProcessResult()

        container_pid = ps_result.stdout.strip()
        if not _is_valid_docker_id(container_pid):
            error(
                f"Failed to verify container id for container with {input_attr}: {container_pid}"
            )
            return bluish.process.ProcessResult(
                returncode=1, stdout=ps_result.stdout, stderr=ps_result.stderr
            )

        if name:
            info(f"Container found with id {container_pid}.")

        if stop_container:
            info(f"Stopping container with {input_attr}...")
            options = ""
            for opt in ["signal", "time"]:
                options += _build_opt(f"--{opt}", inputs.get(opt))

            stop_result = job.exec(
                f"docker container stop {options} {container_pid}", step
            )
            if stop_result.failed:
                error(
                    f"Failed to stop container with {input_attr}: {stop_result.error}"
                )
                return stop_result

        if remove_container:
            rm_result = job.exec(f"docker container rm {options} {container_pid}", step)
            if rm_result.failed:
                error(
                    f"Failed to remove container with {input_attr}: {rm_result.error}"
                )
                return rm_result

        return bluish.process.ProcessResult(stdout=container_pid)


class Exec(bluish.actions.base.Action):
    FQN: str = "docker/exec"

    INPUTS_SCHEMA = {
        "type": dict,
        "properties": {
            "name": [str, None],
            "pid": [str, None],
            "run": str,
            "env": [str, list[str], None],
            "env_file": [str, list[str], None],
            "workdir": [str, None],
        },
    }

    def run(
        self, step: bluish.contexts.step.StepContext
    ) -> bluish.process.ProcessResult:
        inputs = step.inputs

        name = inputs.get("name")
        container_pid = inputs.get("pid")
        command = inputs["run"]
        input_attr = f"name {name}" if name else f"pid {container_pid}"

        pid_result = docker_ps(step, name=name, pid=container_pid)
        if pid_result.failed:
            error(
                f"Can't find a running container with {input_attr}: {pid_result.error}"
            )
            return (
                pid_result
                if pid_result.failed
                else bluish.process.ProcessResult(returncode=1)
            )

        container_pid = pid_result.stdout.strip()
        if not _is_valid_docker_id(container_pid):
            error(
                f"Failed to verify container id for container with {input_attr}: {container_pid}"
            )
            return bluish.process.ProcessResult(
                returncode=1, stdout=pid_result.stdout, stderr=pid_result.stderr
            )

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
                info(line)

            job = cast(bluish.contexts.job.JobContext, step.parent)
            result = job.exec(f"docker exec {options} {container_pid} {line}", step)
            output += result.stdout

            if echo_output:
                info(decorate_for_log(result.stdout, "  > "))

            if result.failed:
                if echo_output:
                    error(decorate_for_log(result.error, " ** "))
                return bluish.process.ProcessResult(
                    returncode=result.returncode, stdout=output, stderr=result.stderr
                )

        return bluish.process.ProcessResult(stdout=output)


class CreateNetwork(bluish.actions.base.Action):
    FQN: str = "docker/create-network"

    INPUTS_SCHEMA = {
        "type": dict,
        "properties": {
            "name": str,
            "fail_if_exists": [bool, None],
            "label": [str, list[str], None],
            "ingress": [bool, None],
            "internal": [bool, None],
        },
    }

    def run(
        self, step: bluish.contexts.step.StepContext
    ) -> bluish.process.ProcessResult:
        inputs = step.inputs

        name = inputs["name"]
        job = cast(bluish.contexts.job.JobContext, step.parent)

        info(f"Creating network {name}...")

        debug(f"Checking if network {name} already exists...")
        network_ls_result = job.exec(f"docker network ls -f name={name} --quiet", step)
        if network_ls_result.failed:
            error(f"Failed to list networks: {network_ls_result.error}")
            return network_ls_result

        network_id = network_ls_result.stdout.strip()
        if network_id:
            msg = f"Network {name} already exists with id {network_id}."
            if inputs.get("fail_if_exists", True):
                error(msg)
                return bluish.process.ProcessResult(returncode=1)
            else:
                warning(msg)
        else:
            options = "--attachable"
            for opt in ["label"]:
                options += _build_opt(f"--{opt}", inputs.get(opt))
            for flag in ["ingress", "internal"]:
                options += _build_flag(f"--{flag}", inputs.get(flag))

            network_create_result = job.exec(
                f"docker network create {options} {name}", step
            )
            if network_create_result.failed:
                error(f"Failed to create network {name}: {network_create_result.error}")
                return network_create_result

            network_id = network_create_result.stdout.strip()
            if not _is_valid_docker_id(network_id):
                error(f"Failed to get network id for {name}: {network_id}")
                return bluish.process.ProcessResult(
                    returncode=1,
                    stdout=network_create_result.stdout,
                    stderr=network_create_result.stderr,
                )
            info(f"Network {name} created with id {network_id}.")

        return bluish.process.ProcessResult(stdout=network_id)
