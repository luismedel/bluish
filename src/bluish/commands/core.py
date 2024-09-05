import os

from bluish.core import StepContext, action, read_file, write_file
from bluish.logging import error, info
from bluish.process import ProcessResult


@action("core/default-action", required_attrs=["run|set"])
def generic_run(step: StepContext) -> ProcessResult:
    """The generic action. It runs the command specified in the `run` attribute.

    Note: `set` dict is processed in the `@action` decorator. We require
    it here to enforce either run or set (or both) and avoid having empty
    actions."""
    if not step.attrs.run:
        return ProcessResult()

    command = step.attrs.run.strip()

    echo_commands = step.get_inherited_attr("echo_commands", True)
    echo_output = step.get_inherited_attr("echo_output", True)
    assert echo_commands is not None
    assert echo_output is not None

    command = step.expand_expr(command)

    if echo_commands:
        info(step, command)

    return step.job.exec(command, step, stream_output=echo_output)


@action("core/expand-template", required_inputs=["input|input_file", "output_file"])
def expand_template(step: StepContext) -> ProcessResult:
    inputs = step.inputs

    template_content: str
    if "input_file" in inputs:
        template_file = inputs["input_file"]

        info(step, f"Reading template file: {template_file}...")
        template_content = read_file(step, template_file).decode()
    else:
        template_content = inputs["input"]

    expanded_content = step.expand_expr(template_content)

    output_file = inputs.get("output_file")
    if output_file:
        info(step, f"Writing expanded content to: {output_file}...")
        write_file(step, output_file, expanded_content.encode())

        if "chmod" in inputs:
            permissions = inputs["chmod"]
            info(step, f"Setting permissions to {permissions} on {output_file}...")
            _ = step.job.exec(f"chmod {permissions} {output_file}", step)

    return ProcessResult(stdout=expanded_content)


@action("core/upload-file", required_inputs=["source_file", "destination_file"])
def upload_file(step: StepContext) -> ProcessResult:
    inputs = step.inputs

    contents: str

    source_file = inputs["source_file"]
    source_file = os.path.expanduser(source_file)

    info(step, f"Reading file: {source_file}...")
    with open(source_file, "r") as f:
        contents = f.read()
    info(step, f" - Read {len(contents)} bytes.")

    destination_file = inputs.get("destination_file")
    assert destination_file is not None

    info(step, f"Writing file to: {destination_file}...")
    try:
        write_file(step, destination_file, contents.encode())
        result = ProcessResult()
    except IOError as e:
        error(step, f"Failed to write file: {str(e)}")
        return ProcessResult(returncode=1)

    if "chmod" in inputs:
        permissions = inputs["chmod"]
        info(step, f"Setting permissions to {permissions} on {destination_file}...")
        result = step.job.exec(f"chmod {permissions} {destination_file}", step)
        if result.failed:
            error(step, f"Failed to set permissions: {result.stderr}")

    return result


@action("core/download-file", required_inputs=["source_file", "destination_file"])
def download_file(step: StepContext) -> ProcessResult:
    inputs = step.inputs

    source_file = inputs["source_file"]
    info(step, f"Reading file: {source_file}...")
    try:
        raw_contents = read_file(step, source_file)
    except IOError as e:
        error(step, f"Failed to read file: {str(e)}")
        return ProcessResult(returncode=1)

    info(step, f" - Read {len(raw_contents)} bytes.")

    destination_file: str | None = None

    try:
        destination_file = inputs.get("destination_file")
        if destination_file:
            info(step, f"Writing file to: {destination_file}...")
            with open(destination_file, "wb") as f:
                f.write(raw_contents)
    except Exception as e:
        error(step, f"Failed to write file: {str(e)}")
        return ProcessResult(returncode=1)

    try:
        if destination_file and "chmod" in inputs:
            permissions = inputs["chmod"]
            info(step, f"Setting permissions to {permissions} on {destination_file}...")
            os.chmod(destination_file, permissions)
    except Exception as e:
        error(step, f"Failed to set permissions: {str(e)}")
        return ProcessResult(returncode=1)

    return ProcessResult()
