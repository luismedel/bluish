import os
import re
import subprocess
from functools import wraps
from typing import Any, Callable, Dict

from bluish.log import error, fatal, info, warn
from bluish.utils import ensure_dict

REGISTERED_ACTIONS: Dict[str, Callable[["JobContext"], "ProcessResult"]] = {}


SHELLS = {
    "bash": "bash -eo pipefail",
    "sh": "sh",
    "python": "python3",
}


class VariableExpandError(Exception):
    pass


class ProcessResult(subprocess.CompletedProcess[str]):
    def __init__(self, data: subprocess.CompletedProcess[str] | str):
        if isinstance(data, str):
            self.stdout = data
            self.stderr = ""
            self.returncode = 0
        elif isinstance(data, subprocess.CompletedProcess):
            self.__dict__.update(data.__dict__)
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
        return (
            command.replace("\\", "\\\\")
            .replace("'", "\\'")
            .replace('"', '\\"')
            .replace("$", "\\$")
            .replace("`", "\\`")
        )

    def _escape_quotes(self, command: str) -> str:
        return command.replace('"', '\\"')

    def run(self, command: str, **kwargs: Any) -> ProcessResult:
        if self.echo_commands:
            info(f"@{self._host} $ {command}")
        fail = kwargs.pop("fail", self.fail_fast)

        remote_command: str = ""

        escape_command = kwargs.pop("escape_commands", False)
        if escape_command:
            command = self._escape_command(command)
        else:
            command = self._escape_quotes(command)

        interpreter = kwargs.pop("interpreter", None)
        if interpreter:
            remote_command = f"""cat <<CMDEOF | {interpreter}
{command}
CMDEOF
"""
        else:
            remote_command = command

        working_dir = kwargs.pop("working_dir", None)
        if working_dir:
            remote_command = f"cd {working_dir} && {remote_command}"

        final_command: str
        if self._host:
            final_command = f'ssh {self._host} -- "{remote_command}"'
        else:
            final_command = remote_command

        if self.echo_output:
            stdout: str = ""
            stderr: str = ""
            process = subprocess.Popen(
                final_command,
                shell=True,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                **kwargs,
            )

            assert process.stdout is not None

            while True:
                line = process.stdout.readline()
                if not line:
                    break
                if isinstance(line, bytes):
                    line = line.decode("utf-8")
                line = line.rstrip()
                stdout += line
                info(line)
            process.wait()
            if process.stderr:
                stderr = process.stderr.read().decode("utf-8")
            result = subprocess.CompletedProcess(
                process.args, process.returncode, stdout, stderr
            )
        else:
            result = subprocess.run(
                final_command,
                shell=True,
                text=True,
                stdout=subprocess.PIPE,
                **kwargs,
            )

        if fail:
            if self.echo_output and result.stderr.strip():
                error(result.stderr.strip())
            result.check_returncode()
        elif result.returncode != 0:
            warn(f"Command failed with status {result.returncode}")
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

    def dispatch(self) -> None:
        if "working_dir" in self.definition:
            self.vars["working_dir"] = self.definition["working_dir"]
        else:
            self.vars["working_dir"] = self.conn.run("pwd").stdout.strip()

        for id, details in self.definition["jobs"].items():
            ctx = JobContext(self, id, details)
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
                info(f"Processing step: {step['name']}")

            execute_action: bool = True

            if "if" in step:
                condition = step["if"]
                info(f"Testing {condition}")
                if not isinstance(condition, str):
                    fatal("Condition must be a string")

                check_cmd = condition.strip()
                check_result = self.run(check_cmd).stdout.strip()
                if not check_result.endswith("true") and not check_result.endswith("1"):
                    info("Skipping step")
                    execute_action = False

            if execute_action:
                fqn = step.get("uses", "command-runner")
                fn = REGISTERED_ACTIONS.get(fqn)
                if fn:
                    info(f"Running action: {fqn}")
                    result = fn(self)
                else:
                    fatal(f"Unknown action: {fqn}")
                self.save_output(result)

            self.increment_step()

    def run(self, command: str, fail: bool | None = None) -> ProcessResult:
        assert self.current_step is not None

        command = self._expand(command.strip())
        lines = [s for s in command.splitlines() if len(s.strip()) > 0]

        escape_commands = self.current_step.get("escape_commands", False)
        working_dir = self.get_var("pipe.working_dir")
        if False and working_dir:
            prepend_cd = True
            for i in range(len(lines)):
                line = lines[i]
                if prepend_cd:
                    line = f"cd {working_dir} && {line}"
                prepend_cd = True
                if line.endswith("\\"):
                    prepend_cd = False
                lines[i] = line

        command = "\n".join(lines)

        if fail is None:
            can_fail = self.current_step.get("can_fail", False)
        else:
            can_fail = fail

        shell = self.current_step.get("shell")
        interpreter = SHELLS.get(shell, shell) if shell else None

        return self.pipe.conn.run(
            command,
            fail=not can_fail,
            interpreter=interpreter,
            working_dir=working_dir,
            escape_commands=escape_commands,
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
                warn(f"Variable {prefix}.{name} not found.")
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
                warn(f"Variable {name} not found.")
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


def init_commands() -> None:
    from bluish.docker_commands import docker_build, docker_create_network, docker_run  # noqa
    from bluish.generic_commands import expand_template, generic_run  # noqa
    from bluish.git_commands import git_get_latest_release  # noqa

    pass
