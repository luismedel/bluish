import logging
import random
import re
import subprocess
import sys
from functools import wraps
from typing import Any, Callable, Dict, Never, Optional, TypeVar, cast

from bluish.utils import decorate_for_log, ensure_dict

REGISTERED_ACTIONS: Dict[str, Callable[["StepContext"], "ProcessResult"]] = {}


SHELLS = {
    "bash": "bash -euo pipefail",
    "sh": "sh -eu",
    "python": "python3",
}


DEFAULT_SHELL = "bash"


def fatal(message: str, exit_code: int = 1) -> Never:
    logging.critical(message)
    exit(exit_code)

def traverse_context(obj: Any, path: str) -> Any:
    parts = path.split(".")
    while parts:
        key = parts.pop(0)
        if isinstance(obj, dict):
            obj = obj.get(key)
        elif hasattr(obj, key):
            obj = getattr(obj, key)
        elif hasattr(obj.attrs, key):
            obj = getattr(obj.attrs, key)
        elif obj.attrs._with and key in obj.attrs._with:
            obj = obj.attrs[key]
        else:
            return (False, None)

        if obj is None:
            return (False, None)

    return (True, obj)
    


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

        final_command: str
        if self._host:
            final_command = f'ssh {self._host} -- "{command}"'
        else:
            final_command = command

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


TResult = TypeVar("TResult")


class DictAttrs:
    def __init__(self, definition: dict[str, Any]):
        self.__dict__.update(definition)

    def __getattr__(self, name: str) -> Any:
        if name == "_with":
            return getattr(self, "with")
        elif name == "_if":
            return getattr(self, "if")
        else:
            return None

    def __setattr__(self, name: str, value: Any) -> None:
        if name == "_with":
            setattr(self, "with", value)
        elif name == "_if":
            setattr(self, "if", value)
        else:
            self.__dict__[name] = value

    def ensure_property(self, name: str, default_value: Any) -> None:
        value = getattr(self, name, None)
        if value is None:
            setattr(self, name, default_value)


class ContextNode:
    VAR_REGEX = re.compile(r"\$?\$\{\{\s*([a-zA-Z_][a-zA-Z0-9_.-]*)\s*\}\}")

    def __init__(self, parent: Optional["ContextNode"], definition: dict[str, Any]):
        self.parent = parent
        self.attrs = DictAttrs(definition)
        self.attrs.ensure_property("env", {})

        self.env: dict[str, Any] = dict(self.attrs.env)

    def get_root(self) -> "ContextNode":
        if self.parent:
            return self.parent.get_root()
        return self

    def expand_expr(self, value: Any, _depth: int = 1) -> str:
        MAX_EXPAND_RECURSION = 5

        if value is None:
            return ""

        if not isinstance(value, str) or "$" not in value:
            return value

        if _depth == MAX_EXPAND_RECURSION:
            raise VariableExpandError()

        def replace_match(match: re.Match[str]) -> str:
            if match.group(0).startswith("$$"):
                return match.group(0)[1:]
            try:
                found, v = self.try_get_value(match.group(1), raw=True)
                if not found:
                    return ""
                return self.expand_expr(v, _depth=_depth + 1)
            except VariableExpandError:
                if _depth > 1:
                    raise
                fatal(f"Too much recursion expanding {match.group(1)} in '{value}'")

        return self.VAR_REGEX.sub(replace_match, value)

    def try_get_env(self, name: str) -> tuple[bool, Any]:
        prefix, varname = name.split(".", maxsplit=1) if "." in name else ("", name)
        if prefix not in ("env", ""):
            return (False, None)

        obj: ContextNode | None = self
        while obj is not None:
            if varname in obj.env:
                return (True, obj.env[varname])
            obj = obj.parent
        
        return (False, None)

    def try_get_value(self, name: str, raw: bool = False) -> tuple[bool, Any]:
        raise NotImplementedError()

    def set_value(self, name: str, value: Any) -> bool:
        prefix, varname = name.split(".", maxsplit=1) if "." in name else ("", name)
        if prefix not in ("env", ""):
            return False

        obj: ContextNode | None = self
        while obj is not None:
            if varname in obj.env:
                obj.env[varname] = value
                return True
            obj = obj.parent
        return False

    def dispatch(self) -> ProcessResult | None:
        pass


class PipeContext(ContextNode):
    def __init__(self, definition: dict[str, Any], connection: Connection) -> None:
        super().__init__(None, definition)

        self.conn = connection
        self.output: str = ""

        self.attrs.ensure_property("var", {})
        self.attrs.ensure_property("jobs", {})
        self.attrs.ensure_property("pipelines", {})

        if "WORKING_DIR" not in self.env:
            self.env["WORKING_DIR"] = self.conn.run("pwd").stdout.strip()

        self.jobs = {
            k: JobContext(self, k, v) for k, v in self.attrs.jobs.items()
        }

    def try_get_value(self, name: str, raw: bool = False) -> tuple[bool, Any]:
        found, value = self.try_get_env(name)
        if found:
            return (True, value)
        return traverse_context(self, name)

    def set_value(self, name: str, value: Any) -> bool:
        if super().set_value(name, value):
            return True

        obj = self
        path, varname = name.rsplit(".", maxsplit=1)
        found, obj = traverse_context(self, path)
        if not found:
            raise ValueError(f"Variable {name} not found")

        if isinstance(obj, dict):
            obj[varname] = value
        else:
            setattr(obj, varname, value)
        return True

    def dispatch(self) -> ProcessResult | None:
        result: ProcessResult | None = None
        for job in self.jobs.values():
            result = job.dispatch()
        return result

    def dispatch_job(self, id: str) -> ProcessResult | None:
        job = next((j for j in self.jobs if j.id == id), None)
        if not job:
            raise ValueError(f"Job {id} not found")
        return job.dispatch()


class JobContext(ContextNode):
    def __init__(self, parent: PipeContext, id: str, definition: dict[str, Any]):
        super().__init__(parent, definition)

        self.pipe = parent
        self.id = id
        self.output: str = ""

        self.attrs.ensure_property("steps", [])
        self.attrs.ensure_property("can_fail", False)

        self.steps: list[StepContext] = [
            StepContext(self, step) for step in self.attrs.steps
        ]

    def dispatch(self) -> ProcessResult | None:
        result: ProcessResult | None = None
        for step in self.steps:
            result = step.dispatch()

        if result:
            self.set_value(f"jobs.{self.id}.output", result.stdout.strip())

        return result

    def try_get_value(self, name: str, raw: bool = False) -> tuple[bool, Any]:
        found, value = self.try_get_env(name)
        if found:
            return (True, value)

        prefix, _ = name.split(".", maxsplit=1) if "." in name else ("", name)
        if prefix != "steps":
            return self.pipe.try_get_value(name, raw)

        return traverse_context(self, name)

    def set_value(self, name: str, value: Any) -> bool:
        prefix, _ = name.split(".", maxsplit=1) if "." in name else ("", name)
        if prefix != "steps":
            return self.pipe.set_value(name, value)

        path, varname = name.rsplit(".", maxsplit=1)
        found, obj = traverse_context(self, path)
        if not found:
            raise ValueError(f"Variable {name} not found")

        if isinstance(obj, dict):
            obj[varname] = value
        else:
            setattr(obj, varname, value)
        return True
 

class StepContext(ContextNode):
    def __init__(self, parent: JobContext, definition: dict[str, Any]):
        super().__init__(parent, definition)

        self.job = parent
        self.output: str = ""

        self.attrs.ensure_property("name", "")
        self.attrs.ensure_property("uses", "command-runner")
        self.attrs.ensure_property("if", None)
        self.attrs.ensure_property("can_fail", False)
        self.attrs.ensure_property("shell", DEFAULT_SHELL)
        self.attrs.ensure_property("with", {})

    def dispatch(self) -> ProcessResult | None:
        if self.attrs.name:
            logging.info(f"Processing step: {self.attrs.name}")

        execute_action: bool = True

        if self.attrs._if:
            logging.info(f"Testing {self.attrs._if}")
            if not isinstance(self.attrs._if, str):
                fatal("Condition must be a string")

            check_cmd = self.attrs._if.strip()
            check_result = self.run_command(check_cmd).stdout.strip()
            if not check_result.endswith("true") and not check_result.endswith("1"):
                logging.info("Skipping step")
                execute_action = False

        if execute_action:
            fqn = self.attrs.uses or "command-runner"
            fn = REGISTERED_ACTIONS.get(fqn)
            if not fn:
                fatal(f"Unknown action: {fqn}")

            logging.info(f"Running action: {fqn}")
            result = fn(self)
            if self.attrs.id:
                self.set_value(f"jobs.{self.job.id}steps.{self.attrs.id}.output", result.stdout.strip())
            return result
        return None

    def run_command(self, command: str) -> ProcessResult:
        command = self.expand_expr(command).strip()

        interpreter = SHELLS.get(self.attrs.shell, self.attrs.shell)
        if interpreter:
            heredocstr = f"EOF_{random.randint(1, 1000)}"
            command = f"""cat <<{heredocstr} | {interpreter}
{command}
{heredocstr}
"""

        has_wd, working_dir = self.try_get_value("env.WORKING_DIR")
        if has_wd:
            command = f'cd "{working_dir}" && {command}'

        if False:
            lines = command.splitlines()
            while lines and lines[-1].strip() == "":
                lines.pop()

            command = "\n".join(lines)

        return self.job.pipe.conn.run(command, fail=self.attrs.can_fail is True)

    def try_get_value(self, name: str, raw: bool = False) -> tuple[bool, Any]:
        found, value = self.try_get_env(name)
        if found:
            return (True, value)

        found, obj = traverse_context(self, name)
        if not found:
            return self.job.try_get_value(name, raw)
        return (True, obj)

    def set_value(self, name: str, value: Any) -> bool:
        prefix, varname = name.split(".", maxsplit=1) if "." in name else ("", name)
        if prefix != "with":
            return self.job.set_value(name, value)

        found, obj = traverse_context(self, name)
        if not found:
            raise ValueError(f"Variable {name} not found")
        
        if isinstance(obj, dict):
            obj[varname] = value
        else:
            setattr(obj, varname, value)
        return True

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
        func: Callable[[StepContext], ProcessResult]
    ) -> Callable[[StepContext], ProcessResult]:
        @wraps(func)
        def wrapper(step: StepContext) -> ProcessResult:
            def exists(key: str, values: dict) -> bool:
                return (
                    "|" in key and any(i in values for i in key.split("|"))
                ) or key in values

            if required_attrs:
                for attr in required_attrs:
                    if not exists(attr, step.attrs.__dict__):
                        raise RequiredAttributeError(attr)

            if required_inputs:
                inputs = step.attrs._with
                if not inputs:
                    raise RequiredInputError(required_inputs[0])

                for param in required_inputs:
                    if not exists(param, inputs):
                        raise RequiredInputError(param)

            return func(step)

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
