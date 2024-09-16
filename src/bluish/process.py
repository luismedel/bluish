import contextlib
import logging
import subprocess
from typing import Callable

from bluish.logging import debug

SHELLS = {
    "bash": "bash -euo pipefail",
    "sh": "sh -eu",
    "python": "python3 -qsIEB",
}


DEFAULT_SHELL = "sh"


class ProcessResult(subprocess.CompletedProcess[str]):
    """The result of a process execution."""

    def __init__(self, stdout: str = "", stderr: str = "", returncode: int = 0):
        super().__init__("", returncode, stdout, stderr)

    @property
    def failed(self) -> bool:
        return self.returncode != 0

    @property
    def error(self) -> str:
        return self.stderr or self.stdout

    @staticmethod
    def from_subprocess_result(
        data: subprocess.CompletedProcess[str]
    ) -> "ProcessResult":
        return ProcessResult(
            stdout=data.stdout or "",
            stderr=data.stderr or "",
            returncode=data.returncode,
        )


def _escape_command(command: str) -> str:
    return command.replace("\\", r"\\\\").replace("$", "\\$")


def _get_docker_pid(host: str) -> str:
    """Gets the container id from the container name or id."""

    docker_pid = run(f"docker ps -f name={host} -qa").stdout.strip()
    if not docker_pid:
        docker_pid = run(f"docker ps -f id={host} -qa").stdout.strip()
    if not docker_pid:
        logging.info(f"Preparing container {host}...")
        command = f"docker run --detach {host} sleep infinity"
        debug(f" > {command}")
        run_result = run(command)
        if run_result.failed:
            raise ValueError(f"Could not start container {host}: {run_result.error}")
        docker_pid = run_result.stdout.strip()
        debug(f"Docker pid {docker_pid}")
    return docker_pid


def prepare_host(host: str | None) -> str | None:
    """Prepares a host for running commands."""

    if host and host.startswith("docker://"):
        host = host[9:]
        docker_pid = _get_docker_pid(host)
        if not docker_pid:
            raise ValueError(f"Could not find container with name or id {host}")
        return f"docker://{docker_pid}"
    return host


def cleanup_host(host: str | None) -> None:
    """Stops and removes a container if it was started by the process module."""

    if not host:
        return

    if host.startswith("docker://"):
        host = host[9:]
        logging.info(f"Stopping and removing container {host}...")

        with contextlib.suppress(Exception):
            run(f"docker stop {host}")

        with contextlib.suppress(Exception):
            run(f"docker rm {host}")


def capture_subprocess_output(
    command: str,
    stdout_handler: Callable[[str], None] | None = None,
) -> subprocess.CompletedProcess[str]:
    # Got the poll() trick from https://gist.github.com/tonykwok/e341a1413520bbb7cdba216ea7255828
    # Thanks @tonykwok!

    # shell = True is required for passing a string command instead of a list
    # bufsize = 1 means output is line buffered
    # universal_newlines = True is required for line buffering
    process = subprocess.Popen(
        command,
        shell=True,
        bufsize=1,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        universal_newlines=True,
        text=True,
    )

    assert process.stdout is not None
    assert process.stderr is not None

    stdout: str = ""
    stderr: str = ""

    def process_line(line: str) -> None:
        nonlocal stdout
        stdout += line
        if stdout_handler:
            stdout_handler(line.rstrip())

    while process.poll() is None:
        process_line(process.stdout.readline())

    # Process the remaining lines
    for line in process.stdout.readlines():
        process_line(line)

    return_code = process.wait()
    stdout = stdout.rstrip()
    stderr = process.stderr.read().rstrip()

    return subprocess.CompletedProcess(command, return_code, stdout, stderr)


def run(
    command: str,
    host: str | None = None,
    stdout_handler: Callable[[str], None] | None = None,
    stderr_handler: Callable[[str], None] | None = None,
) -> ProcessResult:
    """Runs a command on a host and returns the result.

    - `host` can be `None` (or empty) for the local host, `ssh://[user@]<host>` for an SSH host
    or `docker://<container>` for a running Docker container.
    - `stdout_handler` and `stderr_handler` are optional functions that are called
    with the output of the command as it is produced.

    Returns a `ProcessResult` object with the output of the command.
    """

    command = _escape_command(command)

    if host and host.startswith("ssh://"):
        ssh_host = host[6:]
        command = f"ssh {ssh_host} -- '{command}'"
    elif host and host.startswith("docker://"):
        docker_pid = host[9:]
        command = f"docker exec -i {docker_pid} sh -euc '{command}'"

    cmd_result = capture_subprocess_output(command, stdout_handler)

    result = ProcessResult.from_subprocess_result(cmd_result)
    if result.failed and result.stderr and stderr_handler:
        stderr_handler(cmd_result.stderr)

    return result


def get_flavor(host: str | None) -> str:
    ids = {}
    for line in run("cat /etc/os-release | grep ^ID", host).stdout.splitlines():
        key, value = line.split("=", maxsplit=1)
        ids[key] = value.strip().strip('"')
    return ids.get("ID_LIKE", ids.get("ID", "Unknown"))


def install_package(
    host: str | None, packages: list[str], flavor: str = "auto"
) -> ProcessResult:
    """Installs a package on a host."""

    package_list = " ".join(packages)

    flavor = get_flavor(host) if flavor == "auto" else flavor
    if flavor in ("alpine", "alpine-edge"):
        return run(f"apk update && apk add {package_list}", host)
    elif flavor in ("debian", "ubuntu"):
        return run(f"apt-get update && apt-get install -y {package_list}", host)
    elif flavor in ("fedora", "centos", "rhel", "rocky"):
        return run(f"dnf install -y {package_list}", host)
    elif flavor in ("arch"):
        return run(f"pacman -S --noconfirm {package_list}", host)
    elif flavor in ("suse", "opensuse", "opensuse-leap", "opensuse-tumbleweed"):
        return run(f"zypper install -y {package_list}", host)
    elif flavor in ("gentoo"):
        return run(f"emerge -v {package_list}", host)
    else:
        raise ValueError(f"Unsupported flavor: {flavor}")
