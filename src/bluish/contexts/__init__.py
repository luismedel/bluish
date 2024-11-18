import base64
import re
from collections import namedtuple
from typing import Any, Callable, Optional, TypeVar, cast

import bluish.core
import bluish.process
from bluish.logging import info
from bluish.safe_string import SafeString
from bluish.schemas import (
    JOB_SCHEMA,
    STEP_SCHEMA,
    WORKFLOW_SCHEMA,
    get_extra_properties,
    validate_schema,
)
from bluish.utils import safe_string

TResult = TypeVar("TResult")


class Definition:
    SCHEMA: dict[str, Any] = {}

    def __init__(self, attrs: dict[str, Any]):
        self.__dict__["_attrs"] = attrs
        _ = self._validate_attrs(attrs)

    def as_dict(self) -> dict[str, Any]:
        return self.__dict__["_attrs"]

    def get(self, name: str, default: Any = None) -> Any:
        return self.__dict__["_attrs"].get(name, default)

    def _validate_attrs(self, attrs: dict[str, Any]) -> dict[str, Any]:
        if self.SCHEMA:
            validate_schema(self.SCHEMA, attrs)
            return get_extra_properties(self.SCHEMA, attrs)
        else:
            return attrs

    def ensure_property(self, name: str, default_value: Any) -> None:
        if name.startswith("_"):
            name = name[1:]
        if name not in self.attrs:
            self.__dict__["_attrs"][name] = default_value

    def __getattr__(self, name: str) -> Any:
        if name == "attrs":
            return self.__dict__["_attrs"]
        if name.startswith("_"):
            name = name[1:]
        return self.__dict__["_attrs"].get(name)

    def __setattr__(self, name: str, value: Any) -> None:
        if name.startswith("_"):
            name = name[1:]
        self.__dict__["_attrs"][name] = value

    def __contains__(self, name: str) -> bool:
        if name.startswith("_"):
            name = name[1:]
        return name in self.__dict__["_attrs"]


class WorkflowDefinition(Definition):
    SCHEMA = WORKFLOW_SCHEMA
    pass


class JobDefinition(Definition):
    SCHEMA = JOB_SCHEMA
    pass


class StepDefinition(Definition):
    SCHEMA = STEP_SCHEMA
    pass


class ContextNode:
    NODE_TYPE: str = ""

    def __init__(self, parent: Optional["ContextNode"], definition: Definition):
        self.parent = parent
        self.attrs = definition

        self.attrs.ensure_property("env", {})
        self.attrs.ensure_property("var", {})

        self.id: str = self.attrs.id
        self.env = dict(self.attrs.env)
        self.var = dict(self.attrs.var)
        self.outputs: dict[str, Any] = {}
        self.inputs: dict[str, Any] = {}
        self.result = bluish.process.ProcessResult()
        self.failed = False
        self.status = bluish.core.ExecutionStatus.PENDING

        self._expression_parser: Callable[[str], Any] | None = None

    @property
    def display_name(self) -> str:
        return self.attrs.name if self.attrs.name else self.id

    @property
    def expression_parser(self) -> Callable[[str], Any]:
        # HACK This doesn't make me happy
        from bluish.expressions import create_parser

        if not self._expression_parser:
            self._expression_parser = create_parser(self)
        return self._expression_parser

    def dispatch(self) -> bluish.process.ProcessResult | None:
        raise NotImplementedError()

    def expand_expr(self, value: Any) -> Any:
        if isinstance(value, str):
            return _expand_expr(self, value)
        else:
            return value

    def get_value(self, name: str, default: Any = None, raw: bool = False) -> Any:
        value = _try_get_value(self, name, raw=raw)
        if value is None and default is None:
            raise ValueError(f"Variable {name} not found")
        return value if value is not None else default

    def set_value(self, name: str, value: Any) -> None:
        if not _try_set_value(self, name, value):
            raise ValueError(f"Invalid variable name: {name}")

    def set_attr(self, name: str, value: Any) -> None:
        setattr(self.attrs, name, value)

    def get_inherited_attr(
        self, name: str, default: TResult | None = None
    ) -> TResult | None:
        result = default
        ctx: ContextNode | None = self
        while ctx is not None:
            if hasattr(ctx, name):
                result = cast(TResult, getattr(ctx, name))
                break
            elif name in ctx.attrs:
                result = cast(TResult, getattr(ctx.attrs, name))
                break
            else:
                ctx = ctx.parent
        return self.expand_expr(result)


class InputOutputNode(ContextNode):
    def __init__(self, parent: ContextNode, definition: Definition):
        super().__init__(parent, definition)

        self.sensitive_inputs: set[str] = {"password", "token"}

    def log_inputs(self) -> None:
        if not self.attrs._with:
            return
        info("with:")
        for k, v in self.attrs._with.items():
            v = self.expand_expr(v)
            self.inputs[k] = v
            if k in self.sensitive_inputs:
                info(f"  {k}: ********")
            else:
                info(f"  {k}: {safe_string(v)}")


class CircularDependencyError(Exception):
    pass


class VariableExpandError(Exception):
    pass


EXPR_REGEX = re.compile(r"\$?\$\{\{\s*([a-zA-Z_.][a-zA-Z0-9_.-]*)\s*\}\}")


ValueResult = namedtuple("ValueResult", ["value", "contains_secrets"])


def _step_or_job(ctx: ContextNode) -> InputOutputNode:
    if isinstance(ctx, InputOutputNode):
        return ctx
    raise ValueError(f"Can't find step or job in context of type: {ctx.NODE_TYPE}")


def _step(ctx: ContextNode) -> ContextNode:
    if ctx.NODE_TYPE == "step":
        return ctx
    raise ValueError(f"Can't find step in context of type: {ctx.NODE_TYPE}")


def _job(ctx: ContextNode) -> ContextNode:
    if ctx.NODE_TYPE == "job":
        return ctx
    elif ctx.NODE_TYPE == "step":
        return ctx.parent  # type: ignore
    raise ValueError(f"Can't find job in context of type: {ctx.NODE_TYPE}")


def _workflow(ctx: ContextNode) -> ContextNode:
    if ctx.NODE_TYPE == "workflow":
        return ctx
    elif ctx.NODE_TYPE == "job":
        return ctx.parent  # type: ignore
    elif ctx.NODE_TYPE == "step":
        return ctx.parent.parent  # type: ignore
    raise ValueError(f"Can't find workflow in context of type: {ctx.NODE_TYPE}")


def _try_get_value(ctx: ContextNode, name: str, raw: bool = False) -> Any:
    import bluish.contexts.job
    import bluish.contexts.step
    import bluish.contexts.workflow

    def prepare_value(value: Any) -> Any:
        if value is None:
            return None
        elif raw or not isinstance(value, str):
            return value
        else:
            return cast(str, _expand_expr(ctx, value))

    if "." not in name:
        # Handle a non-fully qualified variable name and avoid ambiguity
        member_result = _try_get_value(ctx, f".{name}", raw=raw)
        var_result = _try_get_value(ctx, f"var.{name}", raw=raw)

        if var_result is not None and member_result is not None:
            raise ValueError(f"Ambiguous value reference: {name}")
        elif var_result is not None:
            return var_result
        elif member_result is not None:
            return member_result
        else:
            return None

    root, varname = name.split(".", maxsplit=1)

    if root == "":
        if varname == "stdout":
            return prepare_value(
                "" if ctx.result is None else ctx.result.stdout.strip()
            )
        elif varname == "stderr":
            return prepare_value(
                "" if ctx.result is None else ctx.result.stderr.strip()
            )
        elif varname == "returncode":
            return prepare_value(0 if ctx.result is None else ctx.result.returncode)
    elif root == "env":
        current: ContextNode | None = ctx
        while current:
            for k in ("sys_env", "env"):
                dict_ = getattr(current, k, None)
                if dict_ and varname in dict_:
                    return prepare_value(dict_[varname])
            current = current.parent
    elif root == "var":
        current = ctx
        while current:
            if varname in current.var:
                return prepare_value(current.var[varname])
            current = current.parent
    elif root == "workflow":
        return _try_get_value(_workflow(ctx), varname, raw)
    elif root == "secrets":
        wf = cast(bluish.contexts.workflow.WorkflowContext, _workflow(ctx))
        if varname in wf.secrets:
            return prepare_value(
                SafeString(cast(str, wf.secrets[varname]), "********")
            )
    elif root == "jobs":
        wf = cast(bluish.contexts.workflow.WorkflowContext, _workflow(ctx))
        job_id, varname = varname.split(".", maxsplit=1)
        job = wf.jobs.get(job_id)
        if not job:
            raise ValueError(f"Job {job_id} not found")
        return _try_get_value(job, varname, raw)
    elif root == "job":
        return _try_get_value(_job(ctx), varname, raw)
    elif root == "steps":
        job = cast(bluish.contexts.job.JobContext, _job(ctx))
        step_id, varname = varname.split(".", maxsplit=1)
        step = next((step for step in job.steps if step.id == step_id), None)
        if not step:
            raise ValueError(f"Step {step_id} not found")
        return _try_get_value(step, varname, raw)
    elif root == "matrix":
        job = cast(bluish.contexts.job.JobContext, _job(ctx))
        if varname in job.matrix:
            return prepare_value(job.matrix[varname])
    elif root == "step":
        return _try_get_value(_step(ctx), varname, raw)
    elif root == "inputs":
        node = _step_or_job(ctx)
        if varname in node.inputs:
            if varname in node.sensitive_inputs:
                return prepare_value(SafeString(node.inputs[varname], "********"))
            else:
                return prepare_value(node.inputs[varname])
    elif root == "outputs":
        node = _step_or_job(ctx)
        if varname in node.outputs:
            return prepare_value(node.outputs[varname])

    return None


def _try_set_value(ctx: "ContextNode", name: str, value: str) -> bool:
    import bluish.contexts.job
    import bluish.contexts.step
    import bluish.contexts.workflow

    if "." not in name:
        return False

    name = cast(str, _expand_expr(ctx, name))
    root, varname = name.split(".", maxsplit=1)
    if root == "":
        root, varname = varname.split(".", maxsplit=1)

    if root == "env":
        ctx.env[varname] = value
        return True
    elif root == "var":
        ctx.var[varname] = value
        return True
    elif root == "workflow":
        return _try_set_value(_workflow(ctx), varname, value)
    elif root == "jobs":
        wf = cast(bluish.contexts.workflow.WorkflowContext, _workflow(ctx))
        job_id, varname = varname.split(".", maxsplit=1)
        job = wf.jobs.get(job_id)
        if not job:
            raise ValueError(f"Job {job_id} not found")
        return _try_set_value(job, varname, value)
    elif root == "job":
        return _try_set_value(_job(ctx), varname, value)
    elif root == "steps":
        job = cast(bluish.contexts.job.JobContext, _job(ctx))
        step_id, varname = varname.split(".", maxsplit=1)
        step = next((step for step in job.steps if step.id == step_id), None)
        if not step:
            raise ValueError(f"Step {step_id} not found")
        return _try_set_value(step, varname, value)
    elif root == "step":
        return _try_set_value(_step(ctx), varname, value)
    elif root == "inputs":
        step = cast(bluish.contexts.step.StepContext, _step(ctx))
        step.inputs[varname] = value
        return True
    elif root == "outputs":
        node = _step_or_job(ctx)
        node.outputs[varname] = value
        return True

    return False


TExpandValue = str | dict[str, Any] | list[str]


def _expand_expr(
    ctx: ContextNode, value: TExpandValue | None, _depth: int = 1
) -> TExpandValue:
    if not isinstance(value, str):
        if isinstance(value, dict):
            return {k: _expand_expr(ctx, v, _depth=_depth) for k, v in value.items()}
        elif isinstance(value, list):
            return [cast(str, _expand_expr(ctx, v, _depth=_depth)) for v in value]
        else:
            return value  # type: ignore

    if "${{" not in value:
        return value

    return ctx.expression_parser(value)


def can_dispatch(context: InputOutputNode) -> bool:
    if context.attrs._if is None:
        return True

    info(f"Testing {context.attrs._if}")
    if isinstance(context.attrs._if, bool):
        return context.attrs._if
    elif not isinstance(context.attrs._if, str):
        raise ValueError("Condition must be a bool or a string")

    # Allow bare `if` expressions without placeholders
    condition = context.attrs._if
    if "${{" not in condition:
        condition = "${{" + condition + "}}"

    return bool(context.expand_expr(condition))


def _read_file(ctx: ContextNode, file_path: str) -> bytes:
    """Reads a file from a host and returns its content as bytes."""

    import bluish.contexts.job

    job = cast(bluish.contexts.job.JobContext, _job(ctx))
    result = job.exec(f"base64 -i '{file_path}'", ctx)
    if result.failed:
        raise IOError(f"Failure reading from {file_path}: {result.error}")

    return base64.b64decode(result.stdout)


def _write_file(ctx: ContextNode, file_path: str, content: bytes) -> None:
    """Writes content to a file on a host."""

    import bluish.contexts.job

    job = cast(bluish.contexts.job.JobContext, _job(ctx))
    b64 = base64.b64encode(content).decode()

    result = job.exec(f"echo {b64} | base64 -di - > {file_path}", ctx)
    if result.failed:
        raise IOError(f"Failure writing to {file_path}: {result.error}")
