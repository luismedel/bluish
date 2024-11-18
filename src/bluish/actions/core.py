import os
from collections import ChainMap
from typing import cast

import bluish.actions.base
import bluish.contexts.job
import bluish.contexts.step
import bluish.process
from bluish.logging import error, info
from bluish.utils import safe_string


class RunCommand(bluish.actions.base.Action):
    FQN: str = ""
    SCHEMA = {
        "type": dict,
        "properties": {
            "run": str,
            "shell": [str, None],
        },
    }

    def run(
        self, step: bluish.contexts.step.StepContext
    ) -> bluish.process.ProcessResult:
        env = ChainMap(step.env, step.parent.env, step.parent.parent.env)  # type: ignore

        if env:
            info("env:")
            for k, v in env.items():
                info(f"  {k}: {safe_string(v)}")

        if not step.attrs.run:
            return bluish.process.ProcessResult()

        command = step.attrs.run.strip()

        echo_commands = step.get_inherited_attr("echo_commands", True)
        echo_output = step.get_inherited_attr("echo_output", True)
        assert echo_commands is not None
        assert echo_output is not None

        command = step.expand_expr(command)

        if echo_commands:
            info(command)

        return step.parent.exec(command, step, env=env, stream_output=echo_output)  # type: ignore


class ExpandTemplate(bluish.actions.base.Action):
    FQN: str = "core/expand-template"

    INPUTS_SCHEMA = {
        "type": dict,
        "properties": {
            "input": [str, None],
            "input_file": [str, None],
            "output_file": str,
            "chmod": [int, str, None],
        },
    }

    def run(
        self, step: bluish.contexts.step.StepContext
    ) -> bluish.process.ProcessResult:
        inputs = step.inputs

        job = cast(bluish.contexts.job.JobContext, step.parent)

        template_content: str
        if "input_file" in inputs:
            template_file = inputs["input_file"]

            info(f"Reading template file: {template_file}...")
            template_content = job.read_file(template_file).decode()
        else:
            template_content = inputs["input"]

        expanded_content = step.expand_expr(template_content)

        output_file = inputs.get("output_file")
        if output_file:
            info(f"Writing expanded content to: {output_file}...")
            job.write_file(output_file, expanded_content.encode())

            if "chmod" in inputs:
                permissions = inputs["chmod"]
                info(f"Setting permissions to {permissions} on {output_file}...")
                _ = job.exec(f"chmod {permissions} {output_file}", step)

        return bluish.process.ProcessResult(stdout=expanded_content)


class UploadFile(bluish.actions.base.Action):
    FQN: str = "core/upload-file"

    INPUTS_SCHEMA = {
        "type": dict,
        "properties": {
            "source_file": str,
            "destination_file": str,
            "chmod": [int, str, None],
        },
    }

    def run(
        self, step: bluish.contexts.step.StepContext
    ) -> bluish.process.ProcessResult:
        inputs = step.inputs

        contents: str

        source_file = inputs["source_file"]
        source_file = os.path.expanduser(source_file)

        info(f"Reading file: {source_file}...")
        with open(source_file, "r") as f:
            contents = f.read()
        info(f" - Read {len(contents)} bytes.")

        destination_file = inputs.get("destination_file")
        assert destination_file is not None

        job = cast(bluish.contexts.job.JobContext, step.parent)

        info(f"Writing file to: {destination_file}...")
        try:
            job.write_file(destination_file, contents.encode())
            result = bluish.process.ProcessResult()
        except IOError as e:
            error(f"Failed to write file: {str(e)}")
            return bluish.process.ProcessResult(returncode=1)

        if "chmod" in inputs:
            permissions = inputs["chmod"]
            info(f"Setting permissions to {permissions} on {destination_file}...")
            chmod_result = job.exec(f"chmod {permissions} {destination_file}", step)
            if chmod_result.failed:
                error(f"Failed to set permissions: {result.stderr}")
                return chmod_result

        return result


class DownloadFile(bluish.actions.base.Action):
    FQN: str = "core/download-file"

    INPUTS_SCHEMA = {
        "type": dict,
        "properties": {
            "source_file": str,
            "destination_file": str,
            "chmod": [int, str, None],
        },
    }

    def run(
        self, step: bluish.contexts.step.StepContext
    ) -> bluish.process.ProcessResult:
        inputs = step.inputs

        source_file = inputs["source_file"]
        info(f"Reading file: {source_file}...")
        try:
            job = cast(bluish.contexts.job.JobContext, step.parent)
            raw_contents = job.read_file(source_file)
        except IOError as e:
            error(f"Failed to read file: {str(e)}")
            return bluish.process.ProcessResult(returncode=1)

        info(f" - Read {len(raw_contents)} bytes.")

        destination_file: str | None = None

        try:
            destination_file = inputs.get("destination_file")
            if destination_file:
                info(f"Writing file to: {destination_file}...")
                with open(destination_file, "wb") as f:
                    f.write(raw_contents)
        except Exception as e:
            error(f"Failed to write file: {str(e)}")
            return bluish.process.ProcessResult(returncode=1)

        if destination_file and "chmod" in inputs:
            permissions = inputs["chmod"]
            info(f"Setting permissions to {permissions} on {destination_file}...")
            try:
                os.chmod(destination_file, permissions)
            except Exception as e:
                error(f"Failed to set permissions: {str(e)}")
                return bluish.process.ProcessResult(returncode=1)

        return bluish.process.ProcessResult()
