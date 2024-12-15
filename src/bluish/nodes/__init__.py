import base64
import re
from collections import ChainMap, namedtuple
from itertools import product
from typing import Any, Callable, Generator, Iterable, Optional, Sequence, TypeVar, cast

import bluish.core
import bluish.process
from bluish.logging import info
from bluish.safe_string import SafeString
from bluish.schemas import (
    JOB_SCHEMA,
    STEP_SCHEMA,
    WORKFLOW_SCHEMA,
    Validator,
)
from bluish.utils import safe_string

TResult = TypeVar("TResult")


def log_dict(
    dict_: dict | ChainMap,
    header: str,
    ctx: "Node | None" = None,
    sensitive_keys: Sequence[str] | Iterable[str] = (),
) -> None:
    if dict_ is None or not dict_:
        return
    info(f"{header}:")
    print(dict_.items())
    for k, v in dict_.items():
        if ctx:
            v = ctx.expand_expr(v)
        if k in sensitive_keys:
            info(f"  {k}: ********")
        else:
            info(f"  {k}: {safe_string(v)}")


class Definition:
    SCHEMA: Validator | None = None

    def __init__(self, **kwargs: Any):
        self.__dict__["_attrs"] = kwargs
        self._validate_attrs(kwargs)

    def as_dict(self) -> dict[str, Any]:
        return self.__dict__["_attrs"]

    def get(self, name: str, default: Any = None) -> Any:
        return self.__dict__["_attrs"].get(name, default)

    def _validate_attrs(self, attrs: dict[str, Any]):
        if self.SCHEMA:
            self.SCHEMA.validate(attrs)

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

    def __init__(self, **kwargs: Any):
        super().__init__(**kwargs)
        self.yaml_root: str | None = None


class JobDefinition(Definition):
    SCHEMA = JOB_SCHEMA
    pass


class StepDefinition(Definition):
    SCHEMA = STEP_SCHEMA
    pass


class Node:
    NODE_TYPE: str = ""

    def __init__(self, parent: Optional["Node"], definition: Definition):
        self.parent = parent
        self.attrs = definition
        self.sensitive_inputs: set[str] = {"password", "token"}
        self._expression_parser: Callable[[str], Any] | None = None

        self.reset()

        self._mutated_attrs: dict
        self.result: bluish.process.ProcessResult
        self.status: bluish.core.ExecutionStatus
        self._inputs: ChainMap | None
        self._outputs: dict[str, Any]
        self._env: ChainMap | None
        self._var: ChainMap | None
        self.matrix: dict[str, Any] = {}
        self._secrets: ChainMap | None

    def reset(self) -> None:
        self._mutated_attrs = {}

        self._inputs = None
        self._outputs = {}
        self._env = None
        self._var = None
        self.matrix = {}
        self._secrets = None

        self.result = bluish.process.ProcessResult()
        self.status = bluish.core.ExecutionStatus.PENDING

    def get_opt_value(self, name: str, default: Any = None) -> Any:
        n: Node | None = self
        while n and n.NODE_TYPE != "environment":
            n = n.parent
        if n:
            return n.attrs.get(name, default)
        return default

    def get_opt_flag(self, name: str, default: bool = False) -> bool:
        return self.get_opt_value(name, default)  # type: ignore

    @property
    def inputs(self) -> dict[str, Any]:
        if self._inputs is None:
            self._inputs = ChainMap(
                {}, self.attrs._with, self.parent.inputs if self.parent else {}
            )
        return self._inputs  # type: ignore

    @property
    def outputs(self) -> dict[str, Any]:
        return self._outputs

    @property
    def secrets(self) -> dict[str, str]:
        if self._secrets is None:
            self._secrets = ChainMap(
                self.attrs.secrets or {}, self.parent.secrets if self.parent else {}
            )
        return self._secrets  # type: ignore

    @property
    def env(self) -> dict[str, Any]:
        if self._env is None:
            self._env = ChainMap(
                self.attrs.env or {}, self.parent.env if self.parent else {}
            )
        return self._env  # type: ignore

    @property
    def var(self) -> dict[str, Any]:
        if self._var is None:
            self._var = ChainMap(
                self.attrs.var or {}, self.parent.var if self.parent else {}
            )
        return self._var  # type: ignore

    @property
    def display_name(self) -> str:
        return self.attrs.name if self.attrs.name else self.attrs.id

    @property
    def expression_parser(self) -> Callable[[str], Any]:
        # HACK This doesn't make me happy
        from bluish.expressions import create_parser

        if not self._expression_parser:
            self._expression_parser = create_parser(self)
        return self._expression_parser

    def dispatch(self) -> bluish.process.ProcessResult:
        raise NotImplementedError()

    def expand_expr(self, value: Any) -> Any:
        if isinstance(value, str):
            return _expand_expr(self, value)
        elif isinstance(value, list):
            return [_expand_expr(self, v) for v in value]
        elif isinstance(value, dict):
            return {k: _expand_expr(self, v) for k, v in value.items()}
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

    def clear_attr(self, name: str) -> None:
        if name in self._mutated_attrs:
            del self._mutated_attrs[name]

    def set_attr(self, name: str, value: Any) -> None:
        self._mutated_attrs[name] = value

    def get_attr(self, name: str, default: TResult | None = None) -> TResult | None:
        if name in self._mutated_attrs:
            return self.expand_expr(self._mutated_attrs[name])
        elif name in self.attrs:
            return self.expand_expr(getattr(self.attrs, name))
        else:
            return default

    def get_inherited_attr(
        self, name: str, default: TResult | None = None
    ) -> TResult | None:
        result = default
        ctx: Node | None = self
        while ctx is not None:
            if name in ctx._mutated_attrs:
                result = ctx._mutated_attrs[name]
                break
            elif name in ctx.attrs:
                result = cast(TResult, getattr(ctx.attrs, name))
                break
            else:
                ctx = ctx.parent
        return self.expand_expr(result)


class CircularDependencyError(Exception):
    pass


class VariableExpandError(Exception):
    pass


EXPR_REGEX = re.compile(r"\$?\$\{\{\s*([a-zA-Z_.][a-zA-Z0-9_.-]*)\s*\}\}")


ValueResult = namedtuple("ValueResult", ["value", "contains_secrets"])


def _step(ctx: Node) -> Node:
    if ctx.NODE_TYPE == "step":
        return ctx
    raise ValueError(f"Can't find step in context of type: {ctx.NODE_TYPE}")


def _job(ctx: Node) -> Node:
    if ctx.NODE_TYPE == "job":
        return ctx
    elif ctx.NODE_TYPE == "step":
        return ctx.parent  # type: ignore
    raise ValueError(f"Can't find job in context of type: {ctx.NODE_TYPE}")


def _workflow(ctx: Node) -> Node:
    if ctx.NODE_TYPE == "workflow":
        return ctx
    elif ctx.NODE_TYPE == "job":
        return ctx.parent  # type: ignore
    elif ctx.NODE_TYPE == "step":
        return ctx.parent.parent  # type: ignore
    raise ValueError(f"Can't find workflow in context of type: {ctx.NODE_TYPE}")


def _environment(ctx: Node) -> Node:
    if ctx.NODE_TYPE == "environment":
        return ctx
    elif ctx.NODE_TYPE == "workflow":
        return ctx.parent  # type: ignore
    elif ctx.NODE_TYPE == "job":
        return ctx.parent.parent  # type: ignore
    elif ctx.NODE_TYPE == "step":
        return ctx.parent.parent.parent  # type: ignore
    raise ValueError(f"Can't find environment in context of type: {ctx.NODE_TYPE}")


def _generate_matrices(ctx: Node) -> Generator[dict[str, Any], None, None]:
    if not ctx.attrs.matrix:
        yield {}
        return

    for matrix_tuple in product(*ctx.attrs.matrix.values()):
        yield {
            key: ctx.expand_expr(value)
            for key, value in zip(ctx.attrs.matrix.keys(), matrix_tuple)
        }


def _try_get_value(ctx: Node, name: str, raw: bool = False) -> Any:
    import bluish.nodes.job
    import bluish.nodes.step
    import bluish.nodes.workflow

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
    elif root == "global":
        return _try_get_value(_environment(ctx), varname, raw)
    elif root == "workflow":
        return _try_get_value(_workflow(ctx), varname, raw)
    elif root == "job":
        return _try_get_value(_job(ctx), varname, raw)
    elif root == "step":
        return _try_get_value(_step(ctx), varname, raw)
    elif root == "env":
        if varname in ctx.env:
            return prepare_value(ctx.env[varname])
        else:
            sys_env = ctx.get_attr("sys_env", None)
            if sys_env and varname in sys_env:
                return prepare_value(sys_env[varname])
    elif root == "var":
        if varname in ctx.var:
            return prepare_value(ctx.var[varname])
    elif root == "secrets":
        if varname in ctx.secrets:
            return prepare_value(SafeString(ctx.secrets[varname], "********"))
    elif root == "matrix":
        if varname in ctx.matrix:
            return prepare_value(ctx.matrix[varname])
        elif ctx.parent:
            return _try_get_value(ctx.parent, f"matrix.{varname}", raw)
    elif root == "jobs":
        wf = cast(bluish.nodes.workflow.Workflow, _workflow(ctx))
        job_id, varname = varname.split(".", maxsplit=1)
        job = wf.jobs.get(job_id)
        if not job:
            raise ValueError(f"Job {job_id} not found")
        return _try_get_value(job, varname, raw)
    elif root == "steps":
        job = cast(bluish.nodes.job.Job, _job(ctx))
        step_id, varname = varname.split(".", maxsplit=1)
        step = next((step for step in job.steps if step.attrs.id == step_id), None)
        if not step:
            raise ValueError(f"Step {step_id} not found")
        return _try_get_value(step, varname, raw)
    elif root == "inputs":
        if varname in ctx.inputs:
            value = ctx.inputs[varname]
            if varname in ctx.sensitive_inputs:
                value = prepare_value(SafeString(value, "********"))
            return prepare_value(value)
    elif root == "outputs":
        if varname in ctx.outputs:
            return prepare_value(ctx.outputs[varname])

    return None


def _try_set_value(ctx: "Node", name: str, value: str) -> bool:
    import bluish.nodes.job
    import bluish.nodes.step
    import bluish.nodes.workflow

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
        wf = cast(bluish.nodes.workflow.Workflow, _workflow(ctx))
        job_id, varname = varname.split(".", maxsplit=1)
        job = wf.jobs.get(job_id)
        if not job:
            raise ValueError(f"Job {job_id} not found")
        return _try_set_value(job, varname, value)
    elif root == "job":
        return _try_set_value(_job(ctx), varname, value)
    elif root == "steps":
        job = cast(bluish.nodes.job.Job, _job(ctx))
        step_id, varname = varname.split(".", maxsplit=1)
        step = next((step for step in job.steps if step.attrs.id == step_id), None)
        if not step:
            raise ValueError(f"Step {step_id} not found")
        return _try_set_value(step, varname, value)
    elif root == "step":
        return _try_set_value(_step(ctx), varname, value)
    elif root == "inputs":
        step = cast(bluish.nodes.step.Step, _step(ctx))
        step.inputs[varname] = value
        return True
    elif root == "outputs":
        ctx.outputs[varname] = value
        return True

    return False


TExpandValue = str | dict[str, Any] | list[str]


def _expand_expr(
    ctx: Node, value: TExpandValue | None, _depth: int = 1
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


def can_dispatch(context: Node) -> bool:
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


def _read_file(ctx: Node, file_path: str) -> bytes:
    """Reads a file from a host and returns its content as bytes."""

    import bluish.nodes.job

    job = cast(bluish.nodes.job.Job, _job(ctx))
    result = job.exec(f"base64 -i '{file_path}'", ctx)
    if result.failed:
        raise IOError(f"Failure reading from {file_path}: {result.error}")

    return base64.b64decode(result.stdout)


def _write_file(ctx: Node, file_path: str, content: bytes) -> None:
    """Writes content to a file on a host."""

    import bluish.nodes.job

    job = cast(bluish.nodes.job.Job, _job(ctx))
    b64 = base64.b64encode(content).decode()

    result = job.exec(f"echo {b64} | base64 -di - > {file_path}", ctx)
    if result.failed:
        raise IOError(f"Failure writing to {file_path}: {result.error}")
