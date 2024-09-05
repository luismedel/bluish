import base64
import os
import re
from enum import Enum
from functools import wraps
from typing import Any, Callable, Dict, Optional, TypeVar, Union, cast
from uuid import uuid4

from dotenv import dotenv_values

import bluish.process as process
from bluish.logging import debug, error, info, warning

DEFAULT_ACTION = "core/default-action"

REGISTERED_ACTIONS: Dict[str, Callable[["StepContext"], process.ProcessResult]] = {}


SHELLS = {
    "bash": "bash -euo pipefail",
    "sh": "sh -eu",
    "python": "python3 -qsIEB",
}


DEFAULT_SHELL = "sh"

VAR_REGEX = re.compile(r"\$?\$\{\{\s*([a-zA-Z_.][a-zA-Z0-9_.-]*)\s*\}\}")
CAPTURE_REGEX = re.compile(r"^\s*capture\:(.+)$")


class ExecutionStatus(Enum):
    PENDING = "PENDING"
    RUNNING = "RUNNING"
    FINISHED = "FINISHED"
    SKIPPED = "SKIPPED"


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
        name = f".{name}"

    root, varname = name.split(".", maxsplit=1)

    if root == "":
        if varname == "result":
            return prepare_value(
                "" if ctx.result is None else ctx.result.stdout.strip()
            )
        return (False, "")
    elif root in ("env", "var"):
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
        return False

    root, varname = name.split(".", maxsplit=1)
    if root == "":
        root, varname = varname.split(".", maxsplit=1)

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


def can_dispatch(context: Union["StepContext", "JobContext"]) -> bool:
    if context.attrs._if is None:
        return True

    info(context, f"Testing {context.attrs._if}")
    if not isinstance(context.attrs._if, str):
        raise ValueError("Condition must be a string")

    check_cmd = context.attrs._if.strip()
    job = get_job(context)
    assert job is not None
    return job.exec(check_cmd, context, shell=DEFAULT_SHELL).returncode == 0


def read_file(ctx: "ContextNode", file_path: str) -> bytes:
    """Reads a file from a host and returns its content as bytes."""

    job = get_job(ctx)
    assert job is not None

    result = job.exec(f"base64 -i '{file_path}'", ctx)
    if result.failed:
        raise IOError(f"Failure reading from {file_path}: {result.error}")

    return base64.b64decode(result.stdout)


def write_file(ctx: "ContextNode", file_path: str, content: bytes) -> None:
    """Writes content to a file on a host."""

    job = get_job(ctx)
    assert job is not None

    b64 = base64.b64encode(content).decode()

    result = job.exec(f"echo {b64} | base64 -di - > {file_path}", ctx)
    if result.failed:
        raise IOError(f"Failure writing to {file_path}: {result.error}")


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

    def __contains__(self, name: str) -> bool:
        return name in self.__dict__

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

        self.id: str | None = self.attrs.id
        self.env = dict(self.attrs.env)
        self.var = dict(self.attrs.var)
        self.outputs = dict(self.attrs.outputs or {})
        self.result = process.ProcessResult()
        self.failed = False
        self.status: ExecutionStatus = ExecutionStatus.PENDING

    def expand_expr(self, value: Any, _depth: int = 1) -> Any:
        MAX_EXPAND_RECURSION = 5

        if value is None:
            return ""

        if not isinstance(value, str):
            return value

        if "$" not in value:
            return value

        if _depth == MAX_EXPAND_RECURSION:
            raise VariableExpandError()

        def replace_match(match: re.Match[str]) -> str:
            if match.group(0).startswith("$$"):
                return match.group(0)[1:]
            try:
                v = self.get_value(match.group(1), raw=True)
                return str(self.expand_expr(v, _depth=_depth + 1))
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

    def try_dispatch(self) -> tuple[bool, process.ProcessResult | None]:
        raise NotImplementedError()

    def set_attr(self, name: str, value: Any) -> None:
        setattr(self.attrs, name, value)

    def try_get_attr(self, name: str) -> tuple[bool, Any]:
        if hasattr(self, name):
            return (True, getattr(self, name))
        elif name in self.attrs:
            return (True, getattr(self.attrs, name))
        else:
            return (False, None)

    def get_inherited_attr(
        self, name: str, default: TResult | None = None
    ) -> TResult | None:
        ctx: ContextNode | None = self
        while ctx is not None:
            found, v = ctx.try_get_attr(name)
            if found:
                return cast(TResult, v)
            ctx = ctx.parent
        return default


class WorkflowContext(ContextNode):
    def __init__(self, definition: dict[str, Any]) -> None:
        super().__init__(None, definition)

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

    def try_dispatch(self) -> tuple[bool, process.ProcessResult | None]:
        self.status = ExecutionStatus.RUNNING

        try:
            for job in self.jobs.values():
                run, result = job.try_dispatch()
                if not run:
                    continue

                assert result is not None

                self.result = result

                if result.failed and not job.attrs.continue_on_error:
                    self.failed = True
                    break
        finally:
            self.status = ExecutionStatus.FINISHED

        return (True, self.result)


class JobContext(ContextNode):
    def __init__(self, parent: WorkflowContext, id: str, definition: dict[str, Any]):
        super().__init__(parent, definition)

        self.workflow = parent
        self.id = id

        self.runs_on_host: str | None = None

        self.attrs.ensure_property("steps", [])
        self.attrs.ensure_property("continue_on_error", False)

        self.env = {
            **parent.env,
            **self.attrs.env,
        }

        self.var = {
            **parent.var,
            **self.attrs.var,
        }

        self.steps: dict[str, StepContext] = {}
        for i, step in enumerate(self.attrs.steps):
            if "id" not in step:
                step["id"] = f"step_{i+1}"
            key = step["id"]
            self.steps[key] = StepContext(self, step)

    def try_dispatch(self) -> tuple[bool, process.ProcessResult | None]:
        self.status = ExecutionStatus.RUNNING

        try:
            self.runs_on_host = process.prepare_host(
                self.expand_expr(self.attrs.runs_on)
            )

            if not can_dispatch(self):
                self.status = ExecutionStatus.SKIPPED
                info(self, "Job skipped")
                return (False, None)

            for step in self.steps.values():
                run, result = step.try_dispatch()
                if not run:
                    continue

                assert result is not None

                self.result = result

                if result.failed and not step.attrs.continue_on_error:
                    self.failed = True
                    break

        finally:
            if self.status == ExecutionStatus.RUNNING:
                self.status = ExecutionStatus.FINISHED
            process.cleanup_host(self.runs_on_host)

        return (True, self.result)

    def exec(
        self,
        command: str,
        context: ContextNode,
        shell: str | None = None,
        stream_output: bool = False,
    ) -> process.ProcessResult:
        command = context.expand_expr(command).strip()
        if "${{" in command:
            raise ValueError("Command contains unexpanded variables")

        host = self.runs_on_host

        if context.get_inherited_attr("is_sensitive", False):
            stream_output = False

        # Define where to capture the output with the >> operator
        capture_filename = f"/tmp/{uuid4().hex}"
        debug(self, f"Capture file: {capture_filename}")
        if process.run(f"touch {capture_filename}", host).failed:
            error(context, f"Failed to create capture file: {capture_filename}")
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
            warning(
                self,
                "BLUISH_OUTPUT is a reserved environment variable. Overwriting it.",
            )

        env["BLUISH_OUTPUT"] = capture_filename

        env_str = "; ".join([f'{k}="{v}"' for k, v in env.items()]).strip()
        if env_str:
            command = f"{env_str}; {command}"

        if shell is None:
            shell = context.get_inherited_attr("shell", DEFAULT_SHELL)
        assert shell is not None

        interpreter = SHELLS.get(shell, shell)
        if interpreter:
            b64 = base64.b64encode(command.encode()).decode()
            command = f"echo {b64} | base64 -di - | {interpreter}"

        working_dir = context.get_inherited_attr("working_directory")
        if working_dir:
            debug(self, f"Working dir: {working_dir}")
            command = f'cd "{working_dir}" && {command}'

        def stdout_handler(line: str) -> None:
            line = line.strip()
            if line:
                info(self, line)

        def stderr_handler(line: str) -> None:
            line = line.strip()
            if line:
                info(self, line)

        result = process.run(
            command,
            host=host,
            stdout_handler=stdout_handler if stream_output else None,
            stderr_handler=stderr_handler if stream_output else None,
        )

        # HACK: We should use process.read_file here,
        # but it currently causes an infinite recursion
        output_result = process.run(f"cat {capture_filename}", host)
        if output_result.failed:
            error(self, f"Failed to read capture file: {output_result.error}")
        else:
            for line in output_result.stdout.splitlines():
                k, v = line.split("=", maxsplit=1)
                context.set_value(f"outputs.{k}", v)

        if result.failed:
            msg = f"Command failed with exit status {result.returncode}."
            warning(self, msg)

        return result


class StepContext(ContextNode):
    def __init__(self, parent: JobContext, definition: dict[str, Any]):
        super().__init__(parent, definition)

        self.workflow = parent.workflow
        self.job = parent

        self.attrs.ensure_property("name", "")
        self.attrs.ensure_property("uses", DEFAULT_ACTION)
        self.attrs.ensure_property("continue_on_error", False)
        self.attrs.ensure_property("shell", DEFAULT_SHELL)

        self.id = self.attrs.id

        self.inputs = dict(self.attrs._with or {})
        self.outputs = dict(self.attrs.outputs or {})

    def try_dispatch(self) -> tuple[bool, process.ProcessResult | None]:
        if not can_dispatch(self):
            self.status = ExecutionStatus.SKIPPED
            info(self, "Step skipped")
            return (False, None)

        self.status = ExecutionStatus.RUNNING

        try:
            if self.attrs.name:
                info(self, self.expand_expr(self.attrs.name))

            fqn = self.attrs.uses or DEFAULT_ACTION
            fn = REGISTERED_ACTIONS.get(fqn)
            if not fn:
                raise ValueError(f"Unknown action: {fqn}")

            info(self, f"Run {fqn}")
            if self.inputs:
                info(self, "with:")
                for k, v in self.inputs.items():
                    v = self.expand_expr(v)
                    self.inputs[k] = v
                    info(self, f"  {k}: {v}")

            self.result = fn(self)
            self.failed = self.result.failed

        finally:
            self.status = ExecutionStatus.FINISHED

        return (True, self.result)


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
        func: Callable[[StepContext], process.ProcessResult]
    ) -> Callable[[StepContext], process.ProcessResult]:
        @wraps(func)
        def wrapper(step: StepContext) -> process.ProcessResult:
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

            step.result = func(step)

            if step.attrs.set:
                variables = step.attrs.set
                for key, value in variables.items():
                    value = step.expand_expr(value)
                    debug(step, f"Setting {key} = {value}")
                    step.set_value(key, value)

            return step.result

        REGISTERED_ACTIONS[fqn] = wrapper
        return wrapper

    return inner


def init_commands() -> None:
    import bluish.commands.core  # noqa
    import bluish.commands.docker  # noqa
    import bluish.commands.git  # noqa

    pass
