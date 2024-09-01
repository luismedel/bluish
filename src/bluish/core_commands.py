import base64
import logging

from bluish.core import ProcessResult, StepContext, action


@action("core/default-action", required_attrs=["run|set"])
def generic_run(step: StepContext) -> ProcessResult:
    result: ProcessResult | None = None

    if step.attrs.run:
        result = step.job.run_command(step.attrs.run, step)
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
        template_content = step.job.run_command(f"cat {template_file}", step).stdout
    else:
        template_content = inputs["input"]

    expanded_content = step.expand_expr(template_content)

    output_file = step.expand_expr(inputs.get("output_file"))
    if output_file:
        b64 = base64.b64encode(expanded_content.encode()).decode()
        step.job.run_command(
            f'echo "{b64}" | base64 -di - > {output_file}',
            step,
            shell="sh",
            echo_command=False,
            echo_output=False,
        )
    return ProcessResult(expanded_content)


@action("core/upload-file", required_inputs=["source_file", "destination_file"])
def upload_file(step: StepContext) -> ProcessResult:
    inputs = step.inputs

    contents: str
    source_file = step.expand_expr(inputs["source_file"])
    with open(source_file, "r") as f:
        contents = f.read()
    b64 = base64.b64encode(contents.encode()).decode()

    destination_file = step.expand_expr(inputs.get("destination_file"))
    return step.job.run_command(
        f'echo "{b64}" | base64 -di - > {destination_file}',
        step,
        shell="sh",
        echo_command=False,
        echo_output=False,
    )


@action("core/download-file", required_inputs=["source_file", "destination_file"])
def download_file(step: StepContext) -> ProcessResult:
    inputs = step.inputs

    source_file = step.expand_expr(inputs["source_file"])
    b64 = step.job.run_command(f"cat {source_file} | base64", step).stdout.strip()
    raw_contents = base64.b64decode(b64)
    
    destination_file = step.expand_expr(inputs.get("destination_file"))
    with open(destination_file, "wb") as f:
        f.write(raw_contents)

    return ProcessResult("")