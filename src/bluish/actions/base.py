from typing import Sequence

import bluish.contexts.step
import bluish.process
from bluish.contexts import Definition
from bluish.logging import debug
from bluish.schemas import validate_schema


def _key_exists(key: str, attrs: Definition) -> bool:
    """Checks if a key (or pipe-separated alternative keys) exists in a dictionary."""
    return ("|" in key and any(i in attrs for i in key.split("|"))) or key in attrs


class Action:
    FQN: str = ""

    SCHEMA: dict = {}
    INPUTS_SCHEMA: dict = {}
    SENSITIVE_INPUTS: Sequence[str] = tuple()

    def run(
        self, step: bluish.contexts.step.StepContext
    ) -> bluish.process.ProcessResult:
        raise NotImplementedError()

    def execute(
        self, step: bluish.contexts.step.StepContext
    ) -> bluish.process.ProcessResult:
        if self.SCHEMA:
            validate_schema(self.SCHEMA, step.attrs.as_dict())
        if self.INPUTS_SCHEMA and step.attrs._with:
            validate_schema(self.INPUTS_SCHEMA, step.attrs._with)

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
