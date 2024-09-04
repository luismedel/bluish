import base64
import logging
import os
import random
import re
from functools import wraps
from typing import Any, Callable, Dict, Never, Optional, TypeVar, Union, cast

from dotenv import dotenv_values

from bluish.process import (
    ProcessError,
    ProcessResult,
    cleanup_host,
    prepare_host,
    read_file,
    run,
)
from bluish.utils import decorate_for_log

DEFAULT_ACTION = "core/default-action"

REGISTERED_ACTIONS: Dict[str, Callable[["StepContext"], "ProcessResult"]] = {}


SHELLS = {
    "bash": "bash -euo pipefail",
    "sh": "sh -eu",
    "python": "python3 -qsIEB",
}


DEFAULT_SHELL = "sh"

VAR_REGEX = re.compile(r"\$?\$\{\{\s*([a-zA-Z_][a-zA-Z0-9_.-]*)\s*\}\}")
CAPTURE_REGEX = re.compile(r"^\s*capture\:(.+)$")


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


def get_step(ctx: "ContextNode") -> Optional["StepContext"]:
    if isinstance(ctx, StepContext):
        return ctx
    return None


def get_job(ctx: "ContextNode") -> Optional["JobContext"]:
    if isinstance(ctx, JobContext):
        return ctx
    elif isinstance(ctx, StepContext):
        return ctx.job
    return None


def get_workflow(ctx: "ContextNode") -> Optional["WorkflowContext"]:
    if isinstance(ctx, WorkflowContext):
        return ctx
    elif isinstance(ctx, JobContext):
        return ctx.workflow
    elif isinstance(ctx, StepContext):
        return ctx.job.workflow
    return None


def try_get_value(ctx: "ContextNode", name: str, raw: bool = False) -> tuple[bool, str]:
    def get_from_dict(
        ctx: ContextNode, dict_name: str, varname: str
    ) -> tuple[bool, Any]:
        values = getattr(ctx, dict_name, None)
        if not values or varname not in values:
            return (False, None)
        return (True, values[varname])

    def prepare_value(value: str | None) -> tuple[bool, str]:
        if not value:
            return (True, "")
        else:
            return (True, value if raw else ctx.expand_expr(value))

    if "." not in name:
        if name == "output":
            return prepare_value(getattr(ctx, "output", None))
    else:
        root, varname = name.split(".", maxsplit=1)

        if root in ("env", "var"):
            varname = name[4:]
            current: ContextNode | None = ctx
            while current:
                if root == "env":
                    found, value = get_from_dict(current, "sys_env", varname)
                    if not found:
                        found, value = get_from_dict(current, "env", varname)
                    if found:
                        return prepare_value(value)
                elif root == "var":
                    found, value = get_from_dict(current, "var", varname)
                    if found:
                        return prepare_value(value)
                current = current.parent
        elif root == "workflow":
            wf = get_workflow(ctx)
            if not wf:
                raise ValueError("Workflow reference not found")
            return try_get_value(wf, varname, raw)
        elif root == "jobs":
            wf = get_workflow(ctx)
            if not wf:
                raise ValueError("Workflow reference not found")
            job_id, varname = varname.split(".", maxsplit=1)
            job = wf.jobs.get(job_id)
            if not job:
                raise ValueError(f"Job {job_id} not found")
            return try_get_value(job, varname, raw)
        elif root == "job":
            job = get_job(ctx)
            if not job:
                raise ValueError("Job reference not found")
            return try_get_value(job, varname, raw)
        elif root == "steps":
            job = get_job(ctx)
            if not job:
                raise ValueError("Job reference not found")
            step_id, varname = varname.split(".", maxsplit=1)
            step = job.steps.get(step_id)
            if not step:
                raise ValueError(f"Step {step_id} not found")
            return try_get_value(step, varname, raw)
        elif root == "step":
            step = get_step(ctx)
            if not step:
                raise ValueError("Step reference not found")
            return try_get_value(step, varname, raw)
        elif root == "inputs":
            step = get_step(ctx)
            if not step:
                raise ValueError("Step reference not found")
            found, value = get_from_dict(step, "inputs", varname)
            if found:
                return prepare_value(value)
        elif root == "outputs":
            node = get_step(ctx) or get_job(ctx)
            if not node:
                return (False, "")
            found, value = get_from_dict(node, "outputs", varname)
            if found:
                return prepare_value(value)

    return (False, "")


def try_set_value(ctx: "ContextNode", name: str, value: str) -> bool:
    def set_in_dict(
        ctx: "ContextNode", dict_name: str, varname: str, value: str
    ) -> bool:
        values = getattr(ctx, dict_name, None)
        if values is None:
            return False
        values[varname] = value
        return True

    if "." not in name:
        if name == "output":
            setattr(ctx, "output", value)
            return True
    else:
        root, varname = name.split(".", maxsplit=1)

        if root == "env":
            return set_in_dict(ctx, "env", name[4:], value)
        elif root == "var":
            return set_in_dict(ctx, "var", name[4:], value)
        elif root == "workflow":
            wf = get_workflow(ctx)
            if not wf:
                return False
            return try_set_value(wf, varname, value)
        elif root == "jobs":
            wf = get_workflow(ctx)
            if not wf:
                return False
            job_id, varname = varname.split(".", maxsplit=1)
            job = wf.jobs.get(job_id)
            if not job:
                raise ValueError(f"Job {job_id} not found")
            return try_set_value(job, varname, value)
        elif root == "job":
            job = get_job(ctx)
            if not job:
                return False
            return try_set_value(job, varname, value)
        elif root == "steps":
            job = get_job(ctx)
            if not job:
                return False
            step_id, varname = varname.split(".", maxsplit=1)
            step = job.steps.get(step_id)
            if not step:
                raise ValueError(f"Step {step_id} not found")
            return try_set_value(step, varname, value)
        elif root == "step":
            step = get_step(ctx)
            if not step:
                return False
            return try_set_value(step, varname, value)
        elif root == "inputs":
            step = get_step(ctx)
            if not step:
                return False
            return set_in_dict(step, "inputs", varname, value)
        elif root == "outputs":
            node = get_step(ctx) or get_job(ctx)
            if not node:
                return False
            return set_in_dict(node, "outputs", varname, value)

    return False


class VariableExpandError(Exception):
    pass


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
    def __init__(self, parent: Optional["ContextNode"], definition: dict[str, Any]):
        self.parent = parent
        self.attrs = DictAttrs(definition)

        self.attrs.ensure_property("env", {})
        self.attrs.ensure_property("var", {})

        self.env = dict(self.attrs.env)
        self.var = dict(self.attrs.var)

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
                v = self.get_value(match.group(1), raw=True)
                return self.expand_expr(v, _depth=_depth + 1)
            except VariableExpandError:
                if _depth > 1:
                    raise
                raise RecursionError(
                    f"Too much recursion expanding {match.group(1)} in '{value}'"
                )

        return VAR_REGEX.sub(replace_match, value)

    def get_value(
        self, name: str, default: Any = None, raw: bool = False
    ) -> str | None:
        found, value = try_get_value(self, name, raw=raw)
        if not found and default is None:
            raise ValueError(f"Variable {name} not found")
        return default if not found else value

    def get_bool_value(self, name: str, default: bool = False) -> bool:
        value = self.get_value(name)
        if value is None:
            return default
        return value.lower() in ("true", "1")

    def set_value(self, name: str, value: str) -> None:
        if not try_set_value(self, name, value):
            raise ValueError(f"Invalid variable name: {name}")

    def dispatch(self) -> ProcessResult | None:
        pass

    def get_inherited_attr(self, name: str, default: TResult = None) -> TResult:
        obj: ContextNode | None = self
        while obj is not None:
            if not hasattr(obj.attrs, name):
                return cast(TResult, getattr(obj.attrs, name))
            obj = obj.parent
        return default


class WorkflowContext(ContextNode):
    def __init__(self, definition: dict[str, Any]) -> None:
        super().__init__(None, definition)

        self.output: str = ""

        self.attrs.ensure_property("var", {})
        self.attrs.ensure_property("jobs", {})

        self.env = {
            **self.attrs.env,
        }

        self.sys_env = {
            **os.environ,
            **dotenv_values(".env"),
        }

        self.jobs = {k: JobContext(self, k, v) for k, v in self.attrs.jobs.items()}
        self.var = dict(self.attrs.var)

    def dispatch(self) -> ProcessResult | None:
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
    def __init__(self, parent: WorkflowContext, id: str, definition: dict[str, Any]):
        super().__init__(parent, definition)

        self.workflow = parent
        self.id = id
        self.output: str = ""

        self.runs_on_host: str | None = None

        self.attrs.ensure_property("steps", [])
        self.attrs.ensure_property("echo_commands", True)
        self.attrs.ensure_property("echo_output", True)
        self.attrs.ensure_property("is_sensitive", False)
        self.attrs.ensure_property("can_fail", False)

        self.env = {
            **parent.env,
            **self.attrs.env,
        }

        self.var = {
            **parent.var,
            **self.attrs.var,
        }

        self.outputs = dict(self.attrs.outputs or {})

        self.steps: dict[str, StepContext] = {}
        for i, step in enumerate(self.attrs.steps):
            if "id" not in step:
                step["id"] = f"steps_{i}"
            key = step["id"]
            self.steps[key] = StepContext(self, step)

    def can_dispatch(self, context: Union["StepContext", "JobContext"]) -> bool:
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
        try:
            self.runs_on_host = prepare_host(self.expand_expr(self.attrs.runs_on))

            if not self.can_dispatch(self):
                logging.info("Job skipped")
                return None

            result: ProcessResult | None = None
            for step in self.steps.values():
                result = step.dispatch()

            if result:
                self.set_value(f"jobs.{self.id}.output", result.stdout.strip())

            return result
        except ProcessError as e:
            if e.result:
                logging.error(
                    str(e),
                    extra={
                        "returncode": e.result.returncode,
                        "stdout": e.result.stdout,
                        "stderr": e.result.stderr,
                    },
                )
            else:
                logging.error(str(e))
            raise
        finally:
            cleanup_host(self.runs_on_host)

    def run_command(
        self,
        command: str,
        context: Union["StepContext", "JobContext"],
        shell: str | None = None,
        can_fail: bool | None = None,
        echo_command: bool | None = None,
        echo_output: bool | None = None,
    ) -> ProcessResult:
        host = self.runs_on_host

        if echo_command is None:
            echo_command = self.get_inherited_attr("echo_commands", True)

        if echo_output is None:
            echo_output = context.get_inherited_attr("echo_output", True)

        if context.get_inherited_attr("is_sensitive", False):
            echo_command = False
            echo_output = False

        if echo_command:
            if host:
                logging.info(f"In @{host}:")
            logging.info(decorate_for_log(command))

        command = context.expand_expr(command).strip()

        # Define where to capture the output with the >> operator
        capture_filename = (
            f"/tmp/bluish-capture-{self.id}-{hex(random.randint(0, 65535))}.txt"
        )
        logging.debug(f"Capture file: {capture_filename}")

        # Build the env map
        env = {}

        ctx: ContextNode | None = context
        while ctx:
            for k, v in ctx.env.items():
                if k in env:
                    continue
                env[k] = ctx.expand_expr(v)
            ctx = ctx.parent

        if "BLUISH_OUTPUT" in env:
            logging.warning(
                "BLUISH_OUTPUT is a reserved environment variable. Overwriting it."
            )

        env["BLUISH_OUTPUT"] = capture_filename

        env_str = "; ".join([f'{k}="{v}"' for k, v in env.items()]).strip()
        if env_str:
            command = f"{env_str}; {command}"

        if can_fail is None:
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

        working_dir = context.get_value("env.WORKING_DIR", "")
        if working_dir:
            logging.debug(f"Working dir: {working_dir}")
            command = f'cd "{working_dir}" && {command}'

        def stdout_handler(line: str) -> None:
            line = line.strip()
            if line:
                logging.info(line)

        def stderr_handler(line: str) -> None:
            line = line.strip()
            if line:
                logging.info(line)

        result = run(
            command,
            host=host,
            stdout_handler=stdout_handler if echo_output else None,
            stderr_handler=stderr_handler if echo_output else None,
        )

        if result.failed:
            msg = f"Command failed with exit status {result.returncode}."
            if not can_fail:
                raise ProcessError(result, msg)
            if echo_output:
                logging.warning(msg)

        for line in read_file(host, capture_filename).decode().splitlines():
            k, v = line.split("=", maxsplit=1)
            context.set_value(f"outputs.{k}", v)

        return result

    def run_internal_command(
        self, command: str, context: Union["StepContext", "JobContext"]
    ):
        return self.run_command(
            command, context, echo_command=False, echo_output=False, can_fail=True
        )


class StepContext(ContextNode):
    def __init__(self, parent: JobContext, definition: dict[str, Any]):
        super().__init__(parent, definition)

        self.workflow = parent.workflow
        self.job = parent
        self.output: str = ""

        self.attrs.ensure_property("name", "")
        self.attrs.ensure_property("uses", DEFAULT_ACTION)
        self.attrs.ensure_property("echo_commands", True)
        self.attrs.ensure_property("echo_output", True)
        self.attrs.ensure_property("is_sensitive", False)
        self.attrs.ensure_property("can_fail", False)
        self.attrs.ensure_property("shell", DEFAULT_SHELL)

        self.id = self.attrs.id

        self.inputs = dict(self.attrs._with or {})
        self.outputs = dict(self.attrs.outputs or {})

    def dispatch(self) -> ProcessResult | None:
        if not self.job.can_dispatch(self):
            logging.info("Step skipped")
            return None

        if self.attrs.name:
            logging.info(f"Processing step: {self.attrs.name}")

        fqn = self.attrs.uses or DEFAULT_ACTION
        fn = REGISTERED_ACTIONS.get(fqn)
        if not fn:
            raise ValueError(f"Unknown action: {fqn}")

        logging.info(f"Running {fqn}")
        return fn(self)


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
    """Defines a new action.
    
    Controls which attributes and inputs are required for the action to run.
    """
    def inner(
        func: Callable[[StepContext], ProcessResult]
    ) -> Callable[[StepContext], ProcessResult]:
        @wraps(func)
        def wrapper(step: StepContext) -> ProcessResult:
            def exists(key: str, values: dict) -> bool:
                """Checks if a key (or pipe-separated alternative keys) exists in a dictionary."""
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

            result = func(step)
            step.output = result.stdout.strip()

            if step.attrs.set:
                variables = step.attrs.set
                for key, value in variables.items():
                    value = step.expand_expr(value)
                    logging.debug(f"Setting {key} = {value}")
                    step.set_value(key, value)

            return result

        REGISTERED_ACTIONS[fqn] = wrapper
        return wrapper

    return inner


def init_logging(level_name: str) -> None:
    log_level = getattr(logging, level_name.upper(), logging.INFO)
    logging.basicConfig(level=log_level, format="[%(levelname).1s] %(message)s")


def init_commands() -> None:
    import bluish.commands.core  # noqa
    import bluish.commands.docker  # noqa
    import bluish.commands.git  # noqa

    pass
