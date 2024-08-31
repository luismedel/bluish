import base64
import logging

from bluish.core import ProcessResult, StepContext, action


@action("core/default-action", required_attrs=["run|set"])
def generic_run(step: StepContext) -> ProcessResult:
    result: ProcessResult | None = None

    if step.attrs.run:
        result = step.pipe.run_command(step.attrs.run, step)
        # HACK to allow using the output in the 'set' section
        step.output = result.stdout.strip()

    if step.attrs.set:
        variables = step.attrs.set
        for key, value in variables.items():
            value = step.expand_expr(value)
            logging.debug(f"Setting {key} = {value}")
            step.set_value(key, value)

    return result or ProcessResult("")


@action("core/expand-template", required_inputs=["input|input_file", "output_file"])
def expand_template(step: StepContext) -> ProcessResult:
    inputs = step.inputs

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
            echo_command=False,
            echo_output=False,
        )
    return ProcessResult(expanded_content)
