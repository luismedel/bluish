import base64
import logging
import os
import re
import subprocess
from functools import wraps
from typing import Any, Callable, Dict, Never, Optional, TypeVar

from dotenv import dotenv_values

from bluish.utils import decorate_for_log

DEFAULT_ACTION = "core/default-action"

REGISTERED_ACTIONS: Dict[str, Callable[["StepContext"], "ProcessResult"]] = {}


SHELLS = {
    "bash": "bash -euo pipefail",
    "sh": "sh -eu",
    "python": "python3 -PqsIEB",
}


DEFAULT_SHELL = "bash"


def fatal(message: str, exit_code: int = 1) -> Never:
    logging.critical(message)
    exit(exit_code)


def set_obj_attr(obj: Any, name: str, value: Any) -> None:
    if isinstance(obj, dict):
        obj[name] = value
    else:
        setattr(obj, name, value)


def get_obj_attr(obj: Any, name: str) -> tuple[bool, Any]:
    if isinstance(obj, dict) and name in obj:
        return (True, obj[name])
    elif hasattr(obj, name):
        return (True, getattr(obj, name))
    return (False, None)


def traverse_obj(obj: Any, path: str) -> tuple[bool, Any]:
    if not path:
        return (True, obj)

    parent = obj.parent

    parts = path.split(".")
    while parts:
        key = parts.pop(0)
        found, obj = get_obj_attr(obj, key)
        if not found:
            if parent:
                return traverse_obj(parent, path)
            return (False, "")

    return (True, obj)


class VariableExpandError(Exception):
    pass


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


class Connection:
    def __init__(self, host: str | None = None):
        self.default_host = host

    def _escape_command(self, command: str) -> str:
        return command.replace("\\", r"\\\\").replace("$", "\\$")

    def _escape_quotes(self, command: str) -> str:
        return command.replace('"', '\\"')

    def capture_subprocess_output(
        self,
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
        self,
        command: str,
        host: str | None = None,
        stdout_handler: Callable[[str], None] | None = None,
        stderr_handler: Callable[[str], None] | None = None,
    ) -> ProcessResult:
        host = host or self.default_host

        command = self._escape_command(command)

        if host:
            command = f'ssh {host} -- "{command}"'

        result = self.capture_subprocess_output(command, stdout_handler)

        if result.stderr and stderr_handler:
            stderr_handler(result.stderr)

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
        self.attrs.ensure_property("var", {})

        self.env = dict(self.attrs.env)
        self.var = dict(self.attrs.env)

        self.id: str | None = self.attrs.id

    def expand_expr(self, value: Any, _depth: int = 1) -> str:
        MAX_EXPAND_RECURSION = 5

        if value is None:
            return ""

        if not isinstance(value, str):
            return str(value)

        if "$" not in value:
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

    def try_get_value(self, name: str, raw: bool = False) -> tuple[bool, str]:
        """
        Tries to get a value from the context.
        - If the name is not a fully qualified name (fqn), it will try to get it from the vars/env properties.
        - If the name is a fqn, it will try to traverse the contex to find the value.
        """

        def try_get_from_dict(dict_name: str, varname: str) -> tuple[bool, str]:
            """Tries to get a variable from a dict property (env or var) up into the parent chain"""
            obj: ContextNode | None = self
            while obj is not None:
                _dict: dict[str, Any] | None
                _dict = getattr(obj, dict_name, None)
                if _dict and varname in _dict:
                    return (True, str(_dict[varname]))
                obj = obj.parent
            return (False, "")

        if name.startswith("env."):
            return try_get_from_dict("env", name[4:])
        elif name.startswith("var."):
            return try_get_from_dict("var", name[4:])
        elif "." not in name:
            # Not a fqn? Let's try to get it from env/var
            found, value = try_get_from_dict("env", name)
            if not found:
                found, value = try_get_from_dict("var", name)
            if found:
                return (True, value)
            return (False, "")

        path, varname = name.rsplit(".", maxsplit=1) if "." in name else ("", name)
        found, obj = traverse_obj(self, path)
        if not found:
            return (False, "")
        found, value = get_obj_attr(obj, varname)
        if not found:
            return (False, "")
        value = str(value) if raw else self.expand_expr(value)
        return (True, value if raw else self.expand_expr(value))

    def get_value(self, name: str, default: Any = None) -> str | None:
        found, value = self.try_get_value(name)
        return default if not found else value

    def get_bool_value(self, name: str, default: bool = False) -> bool:
        value = self.get_value(name)
        if value is None:
            return default
        return value.lower() in ("true", "1")

    def set_value(self, name: str, value: str) -> None:
        if "." not in name:
            # Not a fqn? Let's treat it as a env variable
            self.env[name] = value
        else:
            path, varname = name.rsplit(".", maxsplit=1) if "." in name else ("", name)
            found, obj = traverse_obj(self, path)
            if not found:
                raise ValueError(f"Variable {name} not found")

            set_obj_attr(obj, varname, value)

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

        self.env = {
            "WORKING_DIR": self.conn.run("pwd").stdout.strip(),
            "HOST": self.conn.default_host or "",
            **self.attrs.env,
            **os.environ,
            **dotenv_values(".env"),
        }

        self.jobs = {k: JobContext(self, k, v) for k, v in self.attrs.jobs.items()}
        self.var = dict(self.attrs.var)

    def run_command(
        self,
        command: str,
        context: ContextNode,
        shell: str | None = None,
        echo_command: bool | None = None,
        echo_output: bool | None = None,
    ) -> ProcessResult:
        command = context.expand_expr(command).strip()

        if echo_command is None:
            echo_command = (
                self.get_inherited_attr("echo_commands", True)
                if self.attrs.echo_command is None
                else self.attrs.echo_command
            )

        if echo_output is None:
            echo_output = (
                context.get_inherited_attr("echo_output", True)
                if self.attrs.echo_output is None
                else self.attrs.echo_output
            )

        if context.get_inherited_attr("is_sensitive", False):
            echo_command = False
            echo_output = False

        assert echo_command is not None
        assert echo_output is not None

        host = context.get_value("env.HOST", self.conn.default_host)

        if echo_command:
            if host:
                logging.info(f"At @{host}")
            logging.info(decorate_for_log(command))

        can_fail = (
            context.attrs.can_fail if context.attrs.can_fail is not None else False
        )

        if shell is None:
            shell = (
                context.attrs.shell
                if context.attrs.shell is not None
                else DEFAULT_SHELL
            )
        assert shell is not None

        interpreter = SHELLS.get(shell, shell)
        if interpreter:
            b64 = base64.b64encode(command.encode()).decode()
            command = f"echo {b64} | base64 -di - | {interpreter}"

        working_dir = self.get_value("env.WORKING_DIR")
        if working_dir:
            command = f'cd "{working_dir}" && {command}'

        def stdout_handler(line: str) -> None:
            logging.info(line.strip())

        def stderr_handler(line: str) -> None:
            logging.error(line.strip())

        result = self.conn.run(
            command,
            host=host,
            stdout_handler=stdout_handler,
            stderr_handler=stderr_handler,
        )

        if result.failed:
            msg = f"Command failed with exit status {result.returncode}"
            if not can_fail:
                raise ProcessError(result, msg)
            logging.warning(msg)

        return result

    def can_dispatch(self, context: ContextNode) -> bool:
        if context.attrs._if is None:
            return True

        logging.info(f"Testing {context.attrs._if}")
        if not isinstance(context.attrs._if, str):
            raise ValueError("Condition must be a string")

        check_cmd = context.attrs._if.strip()
        try:
            _ = self.run_command(check_cmd, context, shell=DEFAULT_SHELL)
            return True
        except ProcessError:
            return False

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

        self.steps: dict[str, StepContext] = {}
        for i, step in enumerate(self.attrs.steps):
            key = step["id"] if "id" in step else f"steps_{i}"
            self.steps[key] = StepContext(self, step)

    def dispatch(self) -> ProcessResult | None:
        if not self.pipe.can_dispatch(self):
            logging.info("Job skipped")
            return None

        result: ProcessResult | None = None
        for step in self.steps.values():
            result = step.dispatch()

        if result:
            self.set_value(f"jobs.{self.id}.output", result.stdout.strip())

        return result


class StepContext(ContextNode):
    def __init__(self, parent: JobContext, definition: dict[str, Any]):
        super().__init__(parent, definition)

        self.pipe = parent.pipe
        self.job = parent
        self.output: str = ""

        self.attrs.ensure_property("name", "")
        self.attrs.ensure_property("uses", DEFAULT_ACTION)
        self.attrs.ensure_property("if", None)
        self.attrs.ensure_property("can_fail", False)
        self.attrs.ensure_property("shell", DEFAULT_SHELL)

        self.inputs = dict(self.attrs._with or {})

    def dispatch(self) -> ProcessResult | None:
        if not self.pipe.can_dispatch(self):
            logging.info("Step skipped")
            return None

        if self.attrs.name:
            logging.info(f"Processing step: {self.attrs.name}")

        fqn = self.attrs.uses or DEFAULT_ACTION
        fn = REGISTERED_ACTIONS.get(fqn)
        if not fn:
            raise ValueError(f"Unknown action: {fqn}")

        logging.info(f"Running {fqn}")
        result = fn(self)
        if self.attrs.id:
            self.job.set_value(
                f"steps.{self.attrs.id}.output",
                result.stdout.strip(),
            )
        return result


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
                if not step.inputs:
                    raise RequiredInputError(required_inputs[0])

                for param in required_inputs:
                    if not exists(param, step.inputs):
                        raise RequiredInputError(param)

            return func(step)

        REGISTERED_ACTIONS[fqn] = wrapper
        return wrapper

    return inner


def init_logging(level_name: str) -> None:
    log_level = getattr(logging, level_name.upper(), logging.INFO)
    logging.basicConfig(level=log_level, format="[%(levelname).1s] %(message)s")


def init_commands() -> None:
    from bluish.core_commands import expand_template, generic_run  # noqa
    from bluish.docker_commands import (
        docker_build,  # noqa
        docker_create_network,  # noqa
        docker_exec,  # noqa
        docker_ps,  # noqa
        docker_run,  # noqa
        docker_stop,  # noqa
    )

    pass
