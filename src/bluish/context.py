import base64
import os
import re
from itertools import product
from logging import debug, error, info, warning
from typing import Any, Optional, TypeVar, cast
from uuid import uuid4

from dotenv import dotenv_values

from bluish import action, process
from bluish.core import ExecutionStatus


class CircularDependencyError(Exception):
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

        self.id: str = self.attrs.id
        self.env = dict(self.attrs.env)
        self.var = dict(self.attrs.var)
        self.outputs: dict[str, Any] = {}
        self.result = process.ProcessResult()
        self.failed = False
        self.status: ExecutionStatus = ExecutionStatus.PENDING

    def dispatch(self) -> process.ProcessResult | None:
        raise NotImplementedError()

    def expand_expr(self, value: Any) -> Any:
        return expand_expr(self, value)

    def get_value(
        self, name: str, default: Any = None, raw: bool = False
    ) -> str | None:
        found, value = _try_get_value(self, name, raw=raw)
        if not found and default is None:
            raise ValueError(f"Variable {name} not found")
        return default if not found else value

    def set_value(self, name: str, value: Any) -> None:
        if not _try_set_value(self, name, value):
            raise ValueError(f"Invalid variable name: {name}")

    def set_attr(self, name: str, value: Any) -> None:
        setattr(self.attrs, name, value)

    def get_inherited_attr(
        self, name: str, default: TResult | None = None
    ) -> TResult | None:
        ctx: ContextNode | None = self
        while ctx is not None:
            if hasattr(ctx, name):
                return cast(TResult, getattr(ctx, name))
            elif name in ctx.attrs:
                return cast(TResult, getattr(ctx.attrs, name))
            else:
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

    def dispatch(self) -> process.ProcessResult:
        self.status = ExecutionStatus.RUNNING

        try:
            for job in self.jobs.values():
                result = self.dispatch_job(job, no_deps=False)
                if not result:
                    continue

                self.result = result
                if result.failed and not job.attrs.continue_on_error:
                    self.failed = True
                    break

            return self.result

        finally:
            self.status = ExecutionStatus.FINISHED

    def dispatch_job(
        self, job: "JobContext", no_deps: bool
    ) -> process.ProcessResult | None:
        return self.__dispatch_job(job, no_deps, set())

    def __dispatch_job(
        self, job: "JobContext", no_deps: bool, visited_jobs: set[str]
    ) -> process.ProcessResult | None:
        if job.id in visited_jobs:
            raise CircularDependencyError("Circular reference detected")

        if job.status == ExecutionStatus.FINISHED:
            info(f"Job {job.id} already dispatched and finished")
            return job.result
        elif job.status == ExecutionStatus.SKIPPED:
            info(f"Re-running skipped job {job.id}")

        visited_jobs.add(job.id)

        if not no_deps:
            debug("Getting dependency map...")
            for dependency_id in job.attrs.depends_on or []:
                dep_job = self.jobs.get(dependency_id)
                if not dep_job:
                    raise RuntimeError(f"Invalid dependency job id: {dependency_id}")

                result = self.__dispatch_job(dep_job, no_deps, visited_jobs)
                if result and result.failed:
                    error(f"Dependency {dependency_id} failed")
                    return result

        if job.attrs.matrix:
            for matrix_tuple in product(*job.attrs.matrix.values()):
                job.matrix = {
                    key: self.expand_expr(value)
                    for key, value in zip(job.attrs.matrix.keys(), matrix_tuple)
                }
                result = job.dispatch()
                job.matrix = {}
                if result and result.failed:
                    return result

            return process.ProcessResult()
        else:
            return job.dispatch()


class JobContext(ContextNode):
    def __init__(
        self, parent: WorkflowContext, step_id: str, definition: dict[str, Any]
    ):
        super().__init__(parent, definition)

        self.workflow = parent
        self.id = step_id

        self.runs_on_host: str | None = None

        self.attrs.ensure_property("steps", [])
        self.attrs.ensure_property("continue_on_error", False)

        self.matrix: dict[str, Any] = {}

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
            step_id = step["id"]
            step = StepContext(self, step)
            if not step.id:
                step.id = step_id
            self.steps[step_id] = step

    def dispatch(self) -> process.ProcessResult | None:
        self.status = ExecutionStatus.RUNNING

        name = self.attrs.name or self.id
        info("")
        info(f"** {name}")

        self.runs_on_host = process.prepare_host(self.expand_expr(self.attrs.runs_on))

        try:
            if self.matrix:
                info("matrix:")
                for k, v in self.matrix.items():
                    info(f"  {k}: {v}")

            if not can_dispatch(self):
                self.status = ExecutionStatus.SKIPPED
                info("Job skipped")
                return None

            for step in self.steps.values():
                result = step.dispatch()
                if not result:
                    continue

                self.result = result

                if result.failed and not step.attrs.continue_on_error:
                    self.failed = True
                    break

        finally:
            if self.status == ExecutionStatus.RUNNING:
                self.status = ExecutionStatus.FINISHED
            process.cleanup_host(self.runs_on_host)

        return self.result

    def read_file(self, file_path: str) -> bytes:
        return _read_file(self, file_path)

    def write_file(self, file_path: str, content: bytes) -> None:
        _write_file(self, file_path, content)

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
        debug(f"Capture file: {capture_filename}")
        touch_result = process.run(f"touch {capture_filename}", host)
        if touch_result.failed:
            error(
                f"Failed to create capture file {capture_filename}: {touch_result.error}"
            )
            return touch_result

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
            shell = context.get_inherited_attr("shell", process.DEFAULT_SHELL)
        assert shell is not None

        interpreter = process.SHELLS.get(shell, shell)
        if interpreter:
            b64 = base64.b64encode(command.encode()).decode()
            command = f"echo {b64} | base64 -di - | {interpreter}"

        working_dir = context.get_inherited_attr("working_directory")
        if working_dir:
            debug(f"Working dir: {working_dir}")
            debug("Making sure working directory exists...")
            mkdir_result = process.run(f"mkdir -p {working_dir}", host)
            if mkdir_result.failed:
                error(
                    f"Failed to create working directory {working_dir}: {mkdir_result.error}"
                )
                return mkdir_result

            command = f'cd "{working_dir}" && {command}'

        def stdout_handler(line: str) -> None:
            info(line)

        def stderr_handler(line: str) -> None:
            error(line)

        run_result = process.run(
            command,
            host=host,
            stdout_handler=stdout_handler if stream_output else None,
            stderr_handler=stderr_handler if stream_output else None,
        )

        # HACK: We should use our own process.read_file here,
        # but it currently causes an infinite recursion
        output_result = process.run(f"cat {capture_filename}", host)
        if output_result.failed:
            error(f"Failed to read capture file: {output_result.error}")
            return output_result

        for line in output_result.stdout.splitlines():
            k, v = line.split("=", maxsplit=1)
            context.outputs[k] = v

        return run_result


class StepContext(ContextNode):
    def __init__(self, parent: JobContext, definition: dict[str, Any]):
        super().__init__(parent, definition)

        self.workflow = parent.workflow
        self.job = parent

        self.attrs.ensure_property("name", "")
        self.attrs.ensure_property("uses", action.DEFAULT_ACTION)
        self.attrs.ensure_property("continue_on_error", False)
        self.attrs.ensure_property("shell", process.DEFAULT_SHELL)

        self.id = self.attrs.id

        self.inputs: dict[str, Any] = {}
        self.outputs: dict[str, Any] = {}

    def dispatch(self) -> process.ProcessResult | None:
        if self.attrs.name:
            info(f"* {self.attrs.name} ({self.id})")
        else:
            info(f"* {self.id}")

        if not can_dispatch(self):
            self.status = ExecutionStatus.SKIPPED
            info("Step skipped")
            return None

        self.status = ExecutionStatus.RUNNING

        try:
            fn = action.REGISTERED_ACTIONS.get(self.attrs.uses or action.DEFAULT_ACTION)
            if not fn:
                raise ValueError(f"Unknown action: {self.attrs.uses}")

            if self.attrs.uses:
                info(f"Running {self.attrs.uses}")

            self.result = fn(self)
            self.failed = self.result.failed

        finally:
            self.status = ExecutionStatus.FINISHED

        return self.result


class VariableExpandError(Exception):
    pass


VAR_REGEX = re.compile(r"\$?\$\{\{\s*([a-zA-Z_.][a-zA-Z0-9_.-]*)\s*\}\}")


def get_step(ctx: "ContextNode") -> StepContext | None:
    if isinstance(ctx, StepContext):
        return ctx
    return None


def get_job(ctx: "ContextNode") -> JobContext | None:
    if isinstance(ctx, JobContext):
        return ctx
    elif isinstance(ctx, StepContext):
        return ctx.job
    return None


def get_workflow(ctx: "ContextNode") -> WorkflowContext | None:
    if isinstance(ctx, WorkflowContext):
        return ctx
    elif isinstance(ctx, JobContext):
        return ctx.workflow
    elif isinstance(ctx, StepContext):
        return ctx.job.workflow
    return None


def _try_get_value(ctx: ContextNode, name: str, raw: bool = False) -> tuple[bool, str]:
    def prepare_value(value: str | None) -> tuple[bool, str]:
        if value is None:
            return (True, "")
        else:
            return (True, value if raw else ctx.expand_expr(value))

    if "." not in name:
        # Handle a non-fully qualified variable name and avoid ambiguity
        member_found, member_value = _try_get_value(ctx, f".{name}", raw=True)
        var_found, var_value = _try_get_value(ctx, f"var.{name}", raw=True)

        if var_found and member_found:
            raise ValueError(f"Ambiguous value reference: {name}")
        elif var_found:
            return prepare_value(var_value)
        elif member_found:
            return prepare_value(member_value)
        else:
            return (False, "")

    root, varname = name.split(".", maxsplit=1)

    if root == "":
        if varname == "result":
            return prepare_value(
                "" if ctx.result is None else ctx.result.stdout.strip()
            )
    elif root in ("env", "var"):
        varname = name[4:]
        current: ContextNode | None = ctx
        while current:
            if root == "env":
                for k in ("sys_env", "env"):
                    dict_ = getattr(current, k, None)
                    if dict_ and varname in dict_:
                        return prepare_value(dict_[varname])
            elif root == "var" and varname in current.var:
                return prepare_value(current.var[varname])
            current = current.parent
    elif root == "workflow":
        wf = get_workflow(ctx)
        if wf:
            return _try_get_value(wf, varname, raw)
    elif root == "jobs":
        wf = get_workflow(ctx)
        if wf:
            job_id, varname = varname.split(".", maxsplit=1)
            job = wf.jobs.get(job_id)
            if not job:
                raise ValueError(f"Job {job_id} not found")
            return _try_get_value(job, varname, raw)
    elif root == "job":
        job = get_job(ctx)
        if job:
            return _try_get_value(job, varname, raw)
    elif root == "steps":
        job = get_job(ctx)
        if job:
            step_id, varname = varname.split(".", maxsplit=1)
            step = job.steps.get(step_id)
            if not step:
                raise ValueError(f"Step {step_id} not found")
            return _try_get_value(step, varname, raw)
    elif root == "matrix":
        job = get_job(ctx)
        if job and varname in job.matrix:
            return prepare_value(job.matrix[varname])
    elif root == "step":
        step = get_step(ctx)
        if not step:
            raise ValueError("Step reference not found")
        return _try_get_value(step, varname, raw)
    elif root == "inputs":
        step = get_step(ctx)
        if not step:
            raise ValueError("Step reference not found")
        if varname in step.inputs:
            return prepare_value(step.inputs[varname])
    elif root == "outputs":
        node = get_step(ctx) or get_job(ctx)
        if node and varname in node.outputs:
            return prepare_value(node.outputs[varname])

    return (False, "")


def _try_set_value(ctx: "ContextNode", name: str, value: str) -> bool:
    if "." not in name:
        return False

    root, varname = expand_expr(ctx, name).split(".", maxsplit=1)
    if root == "":
        root, varname = varname.split(".", maxsplit=1)

    if root == "env":
        ctx.env[varname] = value
        return True
    elif root == "var":
        ctx.var[varname] = value
        return True
    elif root == "workflow":
        wf = get_workflow(ctx)
        if wf:
            return _try_set_value(wf, varname, value)
    elif root == "jobs":
        wf = get_workflow(ctx)
        if wf:
            job_id, varname = varname.split(".", maxsplit=1)
            job = wf.jobs.get(job_id)
            if not job:
                raise ValueError(f"Job {job_id} not found")
            return _try_set_value(job, varname, value)
    elif root == "job":
        job = get_job(ctx)
        if job:
            return _try_set_value(job, varname, value)
    elif root == "steps":
        job = get_job(ctx)
        if job:
            step_id, varname = varname.split(".", maxsplit=1)
            step = job.steps.get(step_id)
            if not step:
                raise ValueError(f"Step {step_id} not found")
            return _try_set_value(step, varname, value)
    elif root == "step":
        step = get_step(ctx)
        if step:
            return _try_set_value(step, varname, value)
    elif root == "inputs":
        step = get_step(ctx)
        if step:
            step.inputs[varname] = value
            return True
    elif root == "outputs":
        node = get_step(ctx) or get_job(ctx)
        if node:
            node.outputs[varname] = value
            return True

    return False


def expand_expr(ctx: ContextNode, value: Any, _depth: int = 1) -> Any:
    MAX_EXPAND_RECURSION = 5

    if value is None:
        return ""

    if not isinstance(value, str):
        if isinstance(value, dict):
            return {
                expand_expr(ctx, k, _depth=_depth): expand_expr(ctx, v, _depth=_depth)
                for k, v in value.items()
            }
        elif isinstance(value, list):
            return [expand_expr(ctx, v, _depth=_depth) for v in value]
        else:
            return value

    if "$" not in value:
        return value

    if _depth == MAX_EXPAND_RECURSION:
        raise VariableExpandError()

    def replace_match(match: re.Match[str]) -> str:
        if match.group(0).startswith("$$"):
            return match.group(0)[1:]
        try:
            v = ctx.get_value(match.group(1), raw=True)
            return str(expand_expr(ctx, v, _depth=_depth + 1))
        except VariableExpandError:
            if _depth > 1:
                raise
            raise RecursionError(
                f"Too much recursion expanding {match.group(1)} in '{value}'"
            )

    return VAR_REGEX.sub(replace_match, value)


def can_dispatch(context: StepContext | JobContext) -> bool:
    if context.attrs._if is None:
        return True

    info(f"Testing {context.attrs._if}")
    if not isinstance(context.attrs._if, str):
        raise ValueError("Condition must be a string")

    check_cmd = context.attrs._if.strip()
    job = get_job(context)
    assert job is not None
    return job.exec(check_cmd, context, shell=process.DEFAULT_SHELL).returncode == 0


def _read_file(ctx: ContextNode, file_path: str) -> bytes:
    """Reads a file from a host and returns its content as bytes."""

    job = get_job(ctx)
    assert job is not None

    result = job.exec(f"base64 -i '{file_path}'", ctx)
    if result.failed:
        raise IOError(f"Failure reading from {file_path}: {result.error}")

    return base64.b64decode(result.stdout)


def _write_file(ctx: ContextNode, file_path: str, content: bytes) -> None:
    """Writes content to a file on a host."""

    job = get_job(ctx)
    assert job is not None

    b64 = base64.b64encode(content).decode()

    result = job.exec(f"echo {b64} | base64 -di - > {file_path}", ctx)
    if result.failed:
        raise IOError(f"Failure writing to {file_path}: {result.error}")
