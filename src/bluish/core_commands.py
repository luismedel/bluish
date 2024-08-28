import logging
import random

from bluish.core import ProcessResult, StepContext, action


@action("default-action", required_attrs=["run|set"])
def generic_run(step: StepContext) -> ProcessResult:
    variables = step.attrs._with.get("set")
    if variables:
        for key, value in variables.items():
            logging.info(f"Updating {key}...")
            step.pipe.set_value(key, step.expand_expr(value))

    if step.attrs.run:
        return step.pipe.run_command(step.attrs.run, step)

    return ProcessResult("")    


@action("expand-template", required_inputs=["input|input_file", "output_file"])
def expand_template(step: StepContext) -> ProcessResult:
    inputs = step.attrs._with

    template_content: str
    if "input_file" in inputs:
        template_file = inputs["input_file"]
        template_content = step.pipe.run_command(f"cat {template_file}", step).stdout
    else:
        template_content = inputs["input"]

    expanded_content = step.expand_expr(template_content)

    output_file = inputs.get("output_file")
    if output_file:
        heredocstr = f"EOF_{random.randint(1, 1000)}"
        step.pipe.run_command(
            f"""cat <<{heredocstr} > {output_file}
{expanded_content}
{heredocstr}
""",
            step,
        )
    return ProcessResult(expanded_content)
