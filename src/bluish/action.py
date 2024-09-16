from functools import wraps
from typing import Any, Callable, Dict

from bluish.logging import debug, info
from bluish.utils import safe_string

DEFAULT_ACTION = "core/default-action"

REGISTERED_ACTIONS: Dict[str, Callable] = {}


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
    sensitive_inputs: list[str] | None = None,
) -> Any:
    """Defines a new action.

    Controls which attributes and inputs are required for the action to run.
    """

    from bluish import context, process

    def inner(
        func: Callable[[context.StepContext], process.ProcessResult]
    ) -> Callable[[context.StepContext], process.ProcessResult]:
        @wraps(func)
        def wrapper(step: context.StepContext) -> process.ProcessResult:
            def key_exists(key: str, values: dict) -> bool:
                """Checks if a key (or pipe-separated alternative keys) exists in a dictionary."""
                return (
                    "|" in key and any(i in values for i in key.split("|"))
                ) or key in values

            if required_attrs:
                for attr in required_attrs:
                    if not key_exists(attr, step.attrs.__dict__):
                        raise RequiredAttributeError(attr)

            if required_inputs:
                if not step.attrs._with:
                    raise RequiredInputError(required_inputs[0])

                for param in required_inputs:
                    if not key_exists(param, step.attrs._with):
                        raise RequiredInputError(param)

            if step.attrs._with:
                info("with:")
                for k, v in step.attrs._with.items():
                    v = step.expand_expr(v)
                    step.inputs[k] = v
                    if sensitive_inputs and k in sensitive_inputs:
                        info(f"  {k}: ********")
                    else:
                        info(f"  {k}: {safe_string(v)}")

            step.result = func(step)

            if step.attrs.set:
                variables = step.attrs.set
                for key, value in variables.items():
                    value = step.expand_expr(value)
                    debug(f"Setting {key} = {value}")
                    step.set_value(key, value)

            return step.result

        REGISTERED_ACTIONS[fqn] = wrapper
        return wrapper

    return inner
