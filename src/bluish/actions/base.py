from typing import Sequence

import bluish.nodes.step
import bluish.process
from bluish.logging import debug
from bluish.nodes import Definition, log_dict
from bluish.schemas import Validator


def _key_exists(key: str, attrs: Definition) -> bool:
    """Checks if a key (or pipe-separated alternative keys) exists in a dictionary."""
    return ("|" in key and any(i in attrs for i in key.split("|"))) or key in attrs


class Action:
    FQN: str = ""

    SCHEMA: Validator | None = None
    INPUTS_SCHEMA: Validator | None = None
    SENSITIVE_INPUTS: Sequence[str] = tuple()

    def run(self, step: bluish.nodes.step.Step) -> bluish.process.ProcessResult:
        raise NotImplementedError()

    def execute(self, step: bluish.nodes.step.Step) -> bluish.process.ProcessResult:
        if self.SCHEMA:
            self.SCHEMA.validate(step.attrs.as_dict())
        if self.INPUTS_SCHEMA and step.inputs:
            self.INPUTS_SCHEMA.validate(step.inputs)

        step.sensitive_inputs.update(self.SENSITIVE_INPUTS)

        # Were we log step.attrs._with instead of step.inputs because we
        # only want to list the inputs that were passed explicitly to the
        # step.
        log_dict(
            step.attrs._with,
            header="with",
            ctx=step,
            sensitive_keys=self.SENSITIVE_INPUTS,
        )

        step.result = self.run(step)

        if step.attrs.set:
            variables = step.attrs.set
            for key, value in variables.items():
                value = step.expand_expr(value)
                debug(f"Setting {key} = {value}")
                step.set_value(key, value)

        return step.result
