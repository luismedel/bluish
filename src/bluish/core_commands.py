import base64
import logging
import random

from bluish.core import ProcessResult, StepContext, action


@action("core/default-action", required_attrs=["run|set"])
def generic_run(step: StepContext) -> ProcessResult:
    variables = step.attrs.set
    if variables:
        for key, value in variables.items():
            value = step.expand_expr(value)
            logging.debug(f"Setting {key} = {value}")
            step.pipe.set_value(key, value)

    if step.attrs.run:
        return step.pipe.run_command(step.attrs.run, step)

    return ProcessResult("")


@action("core/expand-template", required_inputs=["input|input_file", "output_file"])
def expand_template(step: StepContext) -> ProcessResult:
    inputs = step.attrs._with

    template_content: str
    if "input_file" in inputs:
        template_file = step.expand_expr(inputs["input_file"])
        template_content = step.pipe.run_command(f"cat {template_file}", step).stdout
    else:
        template_content = inputs["input"]

    expanded_content = step.expand_expr(template_content)

    output_file = step.expand_expr(inputs.get("output_file"))
    if output_file:
        b64 = base64.b64encode(expanded_content.encode()).decode()
        step.pipe.run_command(
            f'echo "{b64}" | base64 -di - > {output_file}',
            step,
        )
    return ProcessResult(expanded_content)
