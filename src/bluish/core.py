import logging
import random
import re
import subprocess
import sys
from functools import wraps
from typing import Any, Callable, Dict, Never, Optional, TypeVar

from bluish.utils import decorate_for_log

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


def traverse_context(obj: Any, path: str) -> tuple[bool, Any]:
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
            return (False, "")

        if obj is None:
            return (False, "")

    return (True, obj)


class VariableExpandError(Exception):
    pass


class ProcessError(Exception):
    def __init__(self, result: "ProcessResult", message: str | None = None):
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


class Connection:
    def __init__(self, host: str | None = None):
        self.default_host = host

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

    def run(
        self, command: str, echo_output: bool, host: str | None = None
    ) -> ProcessResult:
        host = host or self.default_host

        final_command: str
        if host:
            final_command = f'ssh {host} -- "{command}"'
        else:
            final_command = command

        result = self.capture_subprocess_output(final_command, echo_output)

        if echo_output and result.stderr:
            logging.error(result.stderr)

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

    def expand_expr(self, value: Any, _depth: int = 1) -> str:
        MAX_EXPAND_RECURSION = 5

        if value is None:
            return ""

        if (not isinstance(value, str)) or ("$" not in value):
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
                raise RecursionError(
                    f"Too much recursion expanding {match.group(1)} in '{value}'"
                )

        return self.VAR_REGEX.sub(replace_match, value)

    def try_get_env(self, name: str) -> tuple[bool, str]:
        prefix, varname = name.split(".", maxsplit=1) if "." in name else ("", name)
        if prefix not in ("env", ""):
            return (False, "")

        obj: ContextNode | None = self
        while obj is not None:
            if varname in obj.env:
                return (True, str(obj.env[varname]))
            obj = obj.parent

        return (False, "")

    def try_get_value(self, name: str, raw: bool = False) -> tuple[bool, str]:
        raise NotImplementedError()

    def get_value(self, name: str, default: Any = None) -> str | None:
        found, value = self.try_get_value(name)
        return default if not found else value

    def get_bool_value(self, name: str, default: bool = False) -> bool:
        value = self.get_value(name)
        if value is None:
            return default
        return value.lower() in ("true", "1")

    def set_value(self, name: str, value: str) -> bool:
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

    def get_inherited_attr(self, name: str, default: Any = None) -> Any:
        obj: ContextNode | None = self
        while obj is not None:
            if not hasattr(obj.attrs, name):
                return getattr(obj.attrs, name)
            obj = obj.parent
        return default


class PipeContext(ContextNode):
    def __init__(self, definition: dict[str, Any], connection: Connection) -> None:
        super().__init__(None, definition)

        self.conn = connection
        self.output: str = ""

        self.attrs.ensure_property("var", {})
        self.attrs.ensure_property("jobs", {})
        self.attrs.ensure_property("pipelines", {})

        self.env = {
            "WORKING_DIR": self.conn.run("pwd", echo_output=False).stdout.strip(),
            "HOST": self.conn.default_host or "",
            **self.attrs.env,
        }

        self.jobs = {k: JobContext(self, k, v) for k, v in self.attrs.jobs.items()}

    def try_get_value(self, name: str, raw: bool = False) -> tuple[bool, str]:
        found, value = self.try_get_env(name)
        if found:
            return (True, value)
        found, value = traverse_context(self, name)
        if found:
            return (True, str(value))
        return (False, "")

    def set_value(self, name: str, value: str) -> bool:
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

    def run_command(
        self, command: str, context: ContextNode, override_can_fail: bool = False
    ) -> ProcessResult:
        command = context.expand_expr(command).strip()

        echo_command = (
            self.get_inherited_attr("echo_commands", True)
            if self.attrs.echo_command is None
            else self.attrs.echo_command
        )
        echo_output = (
            context.get_inherited_attr("echo_output", True)
            if self.attrs.echo_output is None
            else self.attrs.echo_output
        )

        if context.get_inherited_attr("is_sensitive", False):
            echo_command = False
            echo_output = False

        host = context.get_value("env.HOST", self.conn.default_host)

        if echo_command:
            if host:
                logging.info(f"At @{host}")
            logging.info(decorate_for_log(command))

        raise_on_fail = (context.attrs.can_fail is True) and not override_can_fail

        shell = (
            context.attrs.shell if context.attrs.shell is not None else DEFAULT_SHELL
        )
        interpreter = SHELLS.get(shell, shell)
        if interpreter:
            heredocstr = f"EOF_{random.randint(1, 1000)}"
            command = f"""cat <<{heredocstr} | {interpreter}
{command}
{heredocstr}
"""

        working_dir = self.get_value("env.WORKING_DIR")
        if working_dir:
            command = f'cd "{working_dir}" && {command}'

        result = self.conn.run(
            command,
            host=host,
            echo_output=echo_output,
        )

        if result.failed:
            if raise_on_fail:
                raise ProcessError(result)
            logging.warning(f"Command failed with exit status {result.returncode}")

        return result

    def can_dispatch(self, context: ContextNode) -> bool:
        if context.attrs._if is None:
            return True

        logging.info(f"Testing {context.attrs._if}")
        if not isinstance(context.attrs._if, str):
            raise ValueError("Condition must be a string")

        check_cmd = context.attrs._if.strip()
        check_result = self.run_command(
            check_cmd, context, override_can_fail=True
        ).stdout.strip()
        if not check_result.endswith("true") and not check_result.endswith("1"):
            return False
        return True

    def dispatch(self) -> ProcessResult | None:
        if not self.can_dispatch(self):
            logging.info("Pipeline skipped")
            return None

        result: ProcessResult | None = None
        for job in self.jobs.values():
            result = job.dispatch()
        return result

    def dispatch_job(self, id: str) -> ProcessResult | None:
        job = next((v for k, v in self.jobs.items() if k == id), None)
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
        if not self.pipe.can_dispatch(self):
            logging.info("Job skipped")
            return None

        result: ProcessResult | None = None
        for step in self.steps:
            result = step.dispatch()

        if result:
            self.set_value(f"jobs.{self.id}.output", result.stdout.strip())

        return result

    def try_get_value(self, name: str, raw: bool = False) -> tuple[bool, str]:
        found, value = self.try_get_env(name)
        if found:
            return (True, value)

        prefix, _ = name.split(".", maxsplit=1) if "." in name else ("", name)
        if prefix != "steps":
            return self.pipe.try_get_value(name, raw)

        found, value = traverse_context(self, name)
        if found:
            return (True, str(value))
        return (False, "")

    def set_value(self, name: str, value: str) -> bool:
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

        self.pipe = parent.pipe
        self.job = parent
        self.output: str = ""

        self.attrs.ensure_property("name", "")
        self.attrs.ensure_property("uses", "command-runner")
        self.attrs.ensure_property("if", None)
        self.attrs.ensure_property("can_fail", False)
        self.attrs.ensure_property("shell", DEFAULT_SHELL)
        self.attrs.ensure_property("with", {})

    def dispatch(self) -> ProcessResult | None:
        if not self.pipe.can_dispatch(self):
            logging.info("Step skipped")
            return None

        if self.attrs.name:
            logging.info(f"Processing step: {self.attrs.name}")

        execute_action: bool = True

        if self.attrs._if:
            logging.info(f"Testing {self.attrs._if}")
            if not isinstance(self.attrs._if, str):
                raise ValueError("Condition must be a string")

            check_cmd = self.attrs._if.strip()
            check_result = self.pipe.run_command(check_cmd, self).stdout.strip()
            if not check_result.endswith("true") and not check_result.endswith("1"):
                logging.info("Skipping step")
                execute_action = False

        if execute_action:
            fqn = self.attrs.uses or "command-runner"
            fn = REGISTERED_ACTIONS.get(fqn)
            if not fn:
                raise ValueError(f"Unknown action: {fqn}")

            logging.info(f"Running action: {fqn}")
            result = fn(self)
            if self.attrs.id:
                self.set_value(
                    f"jobs.{self.job.id}steps.{self.attrs.id}.output",
                    result.stdout.strip(),
                )
            return result
        return None

    def try_get_value(self, name: str, raw: bool = False) -> tuple[bool, str]:
        found, value = self.try_get_env(name)
        if found:
            return (True, value)

        found, value = traverse_context(self, name)
        if not found:
            return self.job.try_get_value(name, raw)
        return (True, str(value))

    def set_value(self, name: str, value: str) -> bool:
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
