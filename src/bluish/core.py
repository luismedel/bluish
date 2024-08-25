import io
import logging
import os
import random
import re
import selectors
import subprocess
import sys
from functools import wraps
from typing import Any, Callable, Dict, TextIO

from bluish.utils import decorate_for_log, ensure_dict

REGISTERED_ACTIONS: Dict[str, Callable[["JobContext"], "ProcessResult"]] = {}


SHELLS = {
    "bash": "bash -euo pipefail",
    "sh": "sh -eu",
    "python": "python3",
}


DEFAULT_SHELL = "bash"


def fatal(message: str, exit_code: int = 1) -> None:
    logging.critical(message)
    exit(exit_code)


class VariableExpandError(Exception):
    pass


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


class Connection:
    def __init__(self, host: str | None = None):
        self._host = host
        self.echo_commands = True
        self.echo_output = True
        self.fail_fast = True

    def _escape_command(self, command: str) -> str:
        return command
        return (
            command.replace("\\", "\\\\")
            .replace("'", "\\'")
            .replace('"', '\\"')
            .replace("$", "\\$")
            .replace("`", "\\`")
        )

    def _escape_quotes(self, command: str) -> str:
        return command.replace('"', '\\"')

    def capture_subprocess_output(
        self, command: str, echo_output: bool
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
            if echo_output:
                sys.stdout.write(line)

        return_code = process.wait()
        stdout = stdout.strip()
        stderr = process.stderr.read()

        return subprocess.CompletedProcess(command, return_code, stdout, stderr)

    def run(self, command: str, **kwargs: Any) -> ProcessResult:
        if self.echo_commands:
            if self._host:
                logging.info(f"At @{self._host}")
            logging.info(decorate_for_log(command))

        remote_command: str

        interpreter = kwargs.pop("interpreter", None)
        if interpreter:
            heredocstr = f"EOF_{random.randint(1, 1000)}"
            remote_command = f"""cat <<{heredocstr} | {interpreter}
{command}
{heredocstr}
"""
        else:
            remote_command = command

        working_dir = kwargs.pop("working_dir", None)
        if working_dir:
            remote_command = f'cd "{working_dir}" && {remote_command}'

        final_command: str
        if self._host:
            final_command = f'ssh {self._host} -- "{remote_command}"'
        else:
            final_command = remote_command

        result = self.capture_subprocess_output(final_command, self.echo_output)

        fail = kwargs.pop("fail", self.fail_fast)
        if fail:
            if self.echo_output and result.stderr:
                logging.error(result.stderr)
            if result.returncode != 0:
                fatal(f"Command failed with exit status {result.returncode}")
        elif result.returncode != 0:
            logging.warn(f"Command failed with exit status {result.returncode}")
        return ProcessResult(result)


class Context:
    def __init__(self, conn: Connection, definition: dict[str, Any]):
        self.conn = conn
        self.definition = definition

        self.vars: dict[str, Any] = {}
        vars = ensure_dict(definition.get("var"))
        if vars:
            for name, value in vars.items():
                self.set_var(name, value)

    def has_var(self, name: str) -> bool:
        return name in self.vars

    def set_var(self, name: str, value: Any) -> None:
        self.vars[name] = value


class PipeContext(Context):
    def __init__(self, conn: Connection, definition: dict[str, Any]):
        super().__init__(conn, definition)

    def get_jobs(self) -> dict[str, Any]:
        return self.definition["jobs"]

    def dispatch_all(self) -> None:
        for id in self.get_jobs().keys():
            self.dispatch_job(id)

    def dispatch_job(self, id: str) -> None:
        # Initialize builtin vars if not already set
        if "working_dir" not in self.vars:
            wd = (
                self.definition.get("working_dir")
                or self.conn.run("pwd").stdout.strip()
            )
            self.vars["working_dir"] = wd

        ctx = JobContext(self, id, self.definition["jobs"][id])
        ctx.dispatch()


class JobContext(Context):
    def __init__(self, pipe: PipeContext, id: str, definition: dict[str, Any]):
        self.pipe = pipe
        self.id = id
        self.job_definition = definition
        assert self.job_definition is not None
        self.steps = self.job_definition["steps"]
        self.can_fail = self.job_definition.get("can_fail", False)
        self._var_regex = re.compile(r"\$?\$\{\{\s*([a-zA-Z_][a-zA-Z0-9_.-]*)\s*\}\}")
        self._current_step = 0
        super().__init__(pipe.conn, self.job_definition)

    def _expand(self, value: Any, _depth: int = 1) -> str:
        MAX_RECURSION = 5

        if not isinstance(value, str):
            return value

        if not value:
            return ""

        if _depth == MAX_RECURSION:
            raise VariableExpandError()

        def replace_match(match: re.Match[str]) -> str:
            if match.group(0).startswith("$$"):
                return match.group(0)[1:]
            try:
                return self._expand(
                    self.get_var(match.group(1), raw=True), _depth=_depth + 1
                )
            except VariableExpandError:
                if _depth > 1:
                    raise
                fatal(f"Too much recursion expanding {match.group(1)} in '{value}'")
                return ""  # unreachable

        return self._var_regex.sub(replace_match, value)

    @property
    def current_step(self) -> dict[str, Any] | None:
        if not self.steps:
            return None
        if self._current_step < 0 or self._current_step >= len(
            self.job_definition["steps"]
        ):
            return None
        return self.steps[self._current_step]

    def increment_step(self) -> bool:
        self._current_step += 1
        return self.current_step is not None

    def dispatch(self) -> None:
        if self.current_step is None:
            return

        while self.current_step is not None:
            step = self.current_step

            if "name" in step:
                logging.info(f"Processing step: {step['name']}")

            execute_action: bool = True

            if "if" in step:
                condition = step["if"]
                logging.info(f"Testing {condition}")
                if not isinstance(condition, str):
                    fatal("Condition must be a string")

                check_cmd = condition.strip()
                check_result = self.run(check_cmd).stdout.strip()
                if not check_result.endswith("true") and not check_result.endswith("1"):
                    logging.info("Skipping step")
                    execute_action = False

            if execute_action:
                fqn = step.get("uses", "command-runner")
                fn = REGISTERED_ACTIONS.get(fqn)
                if fn:
                    logging.info(f"Running action: {fqn}")
                    result = fn(self)
                else:
                    fatal(f"Unknown action: {fqn}")
                self.save_output(result)

            self.increment_step()

    def run(self, command: str, fail: bool | None = None) -> ProcessResult:
        assert self.current_step is not None

        command = self._expand(command.strip())
        lines = command.splitlines()
        while lines and lines[-1].strip() == "":
            lines.pop()

        command = "\n".join(lines)

        if fail is None:
            can_fail = self.current_step.get("can_fail", False)
        else:
            can_fail = fail

        shell = self.current_step.get("shell", DEFAULT_SHELL)
        interpreter = SHELLS.get(shell, shell)

        working_dir = self.get_var("pipe.working_dir")

        return self.pipe.conn.run(
            command,
            fail=not can_fail,
            interpreter=interpreter,
            working_dir=working_dir,
        )

    def get_var(self, name: str, raw: bool = False) -> str:
        assert self.current_step is not None

        def expand(raw_var: Any) -> Any:
            if raw or not isinstance(raw_var, str):
                return raw_var
            return self._expand(raw_var)

        if "." in name:
            prefix, name = name.split(".", maxsplit=1)
            if prefix == "input":
                _with = self.current_step.get("with", {})
                return expand(_with.get(name))
            elif prefix == "step":
                return expand(self.vars.get(name))
            elif prefix == "pipe":
                return expand(self.pipe.vars.get(name))
            elif prefix == "env":
                return expand(os.environ.get(name))
            else:
                if name in self.vars:
                    return expand(self.vars.get(name))
                logging.warn(f"Variable {prefix}.{name} not found.")
                return ""
        else:
            _with = self.current_step.get("with", {})
            if name in _with:
                return expand(_with[name])
            elif name in self.vars:
                return expand(self.vars[name])
            elif name in self.pipe.vars:
                return expand(self.pipe.vars[name])
            else:
                logging.warn(f"Variable {name} not found.")
                return ""

    def set_var(self, name: str, value: str) -> None:
        if "." in name:
            prefix, name = name.split(".", maxsplit=1)

            if prefix == "step":
                self.vars[name] = value
            elif prefix == "pipe":
                self.pipe.vars[name] = value
            else:
                self.vars[name] = value
        else:
            if self.has_var(name):
                self.vars[name] = value
            elif self.pipe.has_var(name):
                self.pipe.vars[name] = value
            else:
                self.vars[name] = value

    def dump_vars(self) -> dict[str, Any]:
        assert self.current_step is not None

        result = {}
        _with = self.current_step.get("with", {})
        result.update({f"input.{k}": v for k, v in _with.items()})
        result.update({f"step.{k}": v for k, v in self.vars.items()})
        result.update({f"pipe.{k}": v for k, v in self.pipe.vars.items()})

        # Now without prefix, preserving the "logic?" order
        result.update(self.pipe.vars)
        result.update(self.vars)
        result.update(_with)
        return result

    def get_inputs(self) -> dict[str, Any]:
        assert self.current_step is not None

        inputs = ensure_dict(self.current_step.get("with"))
        if not inputs:
            return {}

        return {k: self._expand(v) for k, v in inputs.items()}

    def save_output(self, result: ProcessResult) -> None:
        assert self.current_step is not None

        output = result.stdout.strip()

        if "output_alias" in self.current_step:
            key = self.current_step["output_alias"]
            self.set_var(key, output)

        if "id" in self.current_step:
            key = f"steps.{self.current_step['id']}.output"
            self.set_var(key, output)

        key = f"pipe.jobs.{self.id}.output"
        self.set_var(key, output)


class RequiredInputError(Exception):
    def __init__(self, param: str):
        super().__init__(f"Missing required input parameter: {param}")


class RequiredAttributeError(Exception):
    def __init__(self, param: str):
        super().__init__(f"Missing required attribute: {param}")


def action(
    fqn: str,
    required_attrs: list[str] | None = None,
    required_inputs: list[str] | None = None,
) -> Any:
    def inner(
        func: Callable[[JobContext], ProcessResult]
    ) -> Callable[[JobContext], ProcessResult]:
        @wraps(func)
        def wrapper(ctx: JobContext) -> ProcessResult:
            assert ctx.current_step is not None
            if required_attrs:
                step = ctx.current_step
                for attr in required_attrs:
                    if "|" in attr and any(i in step for i in attr.split("|")):
                        continue
                    elif attr in step:
                        continue
                    else:
                        raise RequiredAttributeError(attr)

            if required_inputs:
                ctx_inputs = ctx.get_inputs()
                for param in required_inputs:
                    if "|" in param and any(i in ctx_inputs for i in param.split("|")):
                        continue
                    elif param in ctx_inputs:
                        continue
                    else:
                        raise RequiredInputError(param)

            return func(ctx)

        REGISTERED_ACTIONS[fqn] = wrapper
        return wrapper

    return inner


def init_logging(level_name: str) -> None:
    log_level = getattr(logging, level_name.upper(), logging.INFO)
    logging.basicConfig(level=log_level, format="[%(levelname).1s] %(message)s")


def init_commands() -> None:
    from bluish.docker_commands import docker_build, docker_create_network, docker_run  # noqa
    from bluish.generic_commands import expand_template, generic_run  # noqa

    pass
