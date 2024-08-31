import subprocess
from typing import Callable, Optional


class ProcessError(Exception):
    def __init__(self, result: Optional["ProcessResult"], message: str | None = None):
        super().__init__(message)
        self.result = result


class ProcessResult(subprocess.CompletedProcess[str]):
    def __init__(self, data: subprocess.CompletedProcess[str] | str):
        if isinstance(data, str):
            self.stdout = data
            self.stderr = ""
            self.returncode = 0
        elif isinstance(data, subprocess.CompletedProcess):
            self.stdout = data.stdout or ""
            self.stderr = data.stderr or ""
            self.returncode = data.returncode
        else:
            raise ValueError("Invalid data type")

    @property
    def failed(self) -> bool:
        return self.returncode != 0


def _escape_command(command: str) -> str:
    return command.replace("\\", r"\\\\").replace("$", "\\$")


def _get_docker_pid(host: str) -> str:
    docker_pid = run(f"docker ps -f name={host} -qa").stdout.strip()
    if not docker_pid:
        docker_pid = run(f"docker ps -f id={host} -qa").stdout.strip()
    if not docker_pid:
        docker_pid = run(f"docker run -d --rm {host}").stdout.strip()
    return docker_pid


def prepare_host(host: str | None) -> str | None:
    if host and host.startswith("docker://"):
        host = host[9:]
        docker_pid = _get_docker_pid(host)
        if not docker_pid:
            raise ValueError(f"Could not find container with name or id {host}")
        return f"docker://{docker_pid}"
    return host


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

    while process.poll() is None:
        line = process.stdout.readline()
        stdout += line
        if stdout_handler:
            stdout_handler(line)

    return_code = process.wait()
    stdout = stdout.strip()
    stderr = process.stderr.read()

    return subprocess.CompletedProcess(command, return_code, stdout, stderr)


def run(
    command: str,
    host: str | None = None,
    stdout_handler: Callable[[str], None] | None = None,
    stderr_handler: Callable[[str], None] | None = None,
) -> ProcessResult:
    command = _escape_command(command)

    if host and host.startswith("ssh://"):
        ssh_host = host[6:]
        command = f"ssh {ssh_host} -- '{command}'"
    elif host and not host.startswith("docker://"):
        docker_pid = host[9:]
        command = f"docker exec -i {docker_pid} bash -c '{command}'"

    result = capture_subprocess_output(command, stdout_handler)

    if result.stderr and stderr_handler:
        stderr_handler(result.stderr)

    return ProcessResult(result)


def cleanup(host: str) -> None:
    if host.startswith("docker://"):
        host = host[9:]
        run(f"docker stop {host}")
        run(f"docker rm {host}")
