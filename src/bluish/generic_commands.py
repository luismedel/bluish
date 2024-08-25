import random

from bluish.core import JobContext, ProcessResult, action


@action("command-runner", required_attrs=["run"])
def generic_run(ctx: JobContext) -> ProcessResult:
    assert ctx.current_step is not None
    return ctx.run(ctx.current_step["run"])


@action("expand-template", required_inputs=["input|input_file", "output_file"])
def expand_template(ctx: JobContext) -> ProcessResult:
    assert ctx.current_step is not None
    inputs = ctx.get_inputs()

    template_content: str
    if "input_file" in inputs:
        template_file = inputs["input_file"]
        template_content = ctx.run(f"cat {template_file}").stdout
    else:
        template_content = inputs["input"]

    expanded_content = template_content

    output_file = inputs.get("output_file")
    if output_file:
        heredocstr = f"EOF_{random.randint(1, 1000)}"
        ctx.run(
            f"""cat <<{heredocstr} > {output_file}
{expanded_content}
{heredocstr}
"""
        )
    return ProcessResult(expanded_content)
