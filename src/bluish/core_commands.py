import base64
import os

from bluish.core import ProcessResult, StepContext, action
from bluish.process import ProcessError


@action("core/default-action", required_attrs=["run"])
def generic_run(step: StepContext) -> ProcessResult:
    return step.job.run_command(step.attrs.run, step)


@action("core/expand-template", required_inputs=["input|input_file", "output_file"])
def expand_template(step: StepContext) -> ProcessResult:
    inputs = step.inputs

    template_content: str
    if "input_file" in inputs:
        template_file = step.expand_expr(inputs["input_file"])
        b64 = step.job.run_internal_command(f"cat {template_file} | base64", step).stdout.strip()
        template_content = base64.b64decode(b64).decode()
    else:
        template_content = inputs["input"]

    expanded_content = step.expand_expr(template_content)

    output_file = step.expand_expr(inputs.get("output_file"))
    if output_file:
        b64 = base64.b64encode(expanded_content.encode()).decode()
        step.job.run_internal_command(
            f'echo "{b64}" | base64 -di - > {output_file}',
            step
        )

        if "chmod" in inputs:
            permissions = inputs["chmod"]
            _ = step.job.run_command(f"chmod {permissions} {output_file}", step)

    return ProcessResult(stdout=expanded_content)


@action("core/upload-file", required_inputs=["source_file", "destination_file"])
def upload_file(step: StepContext) -> ProcessResult:
    inputs = step.inputs

    contents: str

    source_file = step.expand_expr(inputs["source_file"])
    source_file = os.path.expanduser(source_file)
    with open(source_file, "r") as f:
        contents = f.read()
    b64 = base64.b64encode(contents.encode()).decode()

    destination_file = step.expand_expr(inputs.get("destination_file"))
    result = step.job.run_internal_command(
        f'echo "{b64}" | base64 -di - > {destination_file}',
        step
    )

    if "chmod" in inputs:
        permissions = inputs["chmod"]
        result = step.job.run_command(f"chmod {permissions} {destination_file}", step)

    return result


@action("core/download-file", required_inputs=["source_file", "destination_file"])
def download_file(step: StepContext) -> ProcessResult:
    inputs = step.inputs

    source_file = step.expand_expr(inputs["source_file"])
    b64 = step.job.run_internal_command(f"cat {source_file} | base64", step).stdout.strip()
    raw_contents = base64.b64decode(b64)

    try:
        destination_file = step.expand_expr(inputs.get("destination_file"))
        with open(destination_file, "wb") as f:
            f.write(raw_contents)
    except Exception as e:
        raise ProcessError(None, f"Failed to write file: {str(e)}")

    try:
        if "chmod" in inputs:
            permissions = inputs["chmod"]
            os.chmod(destination_file, permissions)
    except Exception as e:
        raise ProcessError(None, f"Failed to set permissions: {str(e)}")

    return ProcessResult("")
