import random

from bluish.core import ProcessResult, StepContext, action


@action("command-runner", required_attrs=["run"])
def generic_run(step: StepContext) -> ProcessResult:
    return step.run_command(step.attrs.run)


@action("expand-template", required_inputs=["input|input_file", "output_file"])
def expand_template(step: StepContext) -> ProcessResult:
    inputs = step.attrs._with

    template_content: str
    if "input_file" in inputs:
        template_file = inputs["input_file"]
        template_content = step.run_command(f"cat {template_file}").stdout
    else:
        template_content = inputs["input"]

    expanded_content = template_content

    output_file = inputs.get("output_file")
    if output_file:
        heredocstr = f"EOF_{random.randint(1, 1000)}"
        step.run_command(
            f"""cat <<{heredocstr} > {output_file}
{expanded_content}
{heredocstr}
"""
        )
    return ProcessResult(expanded_content)
