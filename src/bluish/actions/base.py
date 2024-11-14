from typing import Sequence

import bluish.contexts.step
import bluish.process
from bluish.logging import debug


class RequiredInputError(Exception):
    def __init__(self, param: str):
        super().__init__(f"Missing required input parameter: {param}")


class RequiredAttributeError(Exception):
    def __init__(self, param: str):
        super().__init__(f"Missing required attribute: {param}")


def _key_exists(key: str, values: dict) -> bool:
    """Checks if a key (or pipe-separated alternative keys) exists in a dictionary."""
    return ("|" in key and any(i in values for i in key.split("|"))) or key in values


class Action:
    FQN: str = ""
    REQUIRED_ATTRS: Sequence[str] = tuple()
    REQUIRED_INPUTS: Sequence[str] = tuple()
    SENSITIVE_INPUTS: Sequence[str] = tuple()

    def run(
        self, step: bluish.contexts.step.StepContext
    ) -> bluish.process.ProcessResult:
        raise NotImplementedError()

    def execute(
        self, step: bluish.contexts.step.StepContext
    ) -> bluish.process.ProcessResult:
        for attr in self.REQUIRED_ATTRS:
            if not _key_exists(attr, step.attrs.__dict__):
                raise RequiredAttributeError(attr)

        if self.REQUIRED_INPUTS and not step.attrs._with:
            raise RequiredInputError(self.REQUIRED_INPUTS[0])

        for param in self.REQUIRED_INPUTS:
            if not _key_exists(param, step.attrs._with):
                raise RequiredInputError(param)

        step.sensitive_inputs.update(self.SENSITIVE_INPUTS)
        step.log_inputs()

        step.result = self.run(step)

        if step.attrs.set:
            variables = step.attrs.set
            for key, value in variables.items():
                value = step.expand_expr(value)
                debug(f"Setting {key} = {value}")
                step.set_value(key, value)

        return step.result
