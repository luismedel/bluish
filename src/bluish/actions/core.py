import os
from typing import cast

import yaml

import bluish.actions.base
import bluish.nodes.environment
import bluish.nodes.job
import bluish.nodes.step
import bluish.nodes.workflow
import bluish.process
from bluish.logging import error, info
from bluish.nodes import WorkflowDefinition
from bluish.schemas import Int, List, Object, Optional, Str


class RunCommand(bluish.actions.base.Action):
    FQN: str = ""
    SCHEMA = Object(
        {
            "run": Str,
        }
    )

    def run(self, step: bluish.nodes.step.Step) -> bluish.process.ProcessResult:
        bluish.nodes.log_dict(
            step.env, header="env", ctx=step, sensitive_keys=self.SENSITIVE_INPUTS
        )

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
        return step.parent.exec(command, step, use_env=True, stream_output=echo_output)  # type: ignore


class ExpandTemplate(bluish.actions.base.Action):
    FQN: str = "core/expand-template"

    INPUTS_SCHEMA = Object(
        {
            "input": Optional(Str, List(Str)),
            "input_file": Optional(Str),
            "output_file": Str,
            "chmod": Optional(Int, Str),
        }
    )

    def run(self, step: bluish.nodes.step.Step) -> bluish.process.ProcessResult:
        inputs = step.inputs

        job = cast(bluish.nodes.job.Job, step.parent)

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

    INPUTS_SCHEMA = Object(
        {
            "source_file": Str,
            "destination_file": Str,
            "chmod": Optional(Int, Str),
        }
    )

    def run(self, step: bluish.nodes.step.Step) -> bluish.process.ProcessResult:
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

        job = cast(bluish.nodes.job.Job, step.parent)

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

    INPUTS_SCHEMA = Object(
        {
            "source_file": Str,
            "destination_file": Str,
            "chmod": Optional(Int, Str),
        }
    )

    def run(self, step: bluish.nodes.step.Step) -> bluish.process.ProcessResult:
        inputs = step.inputs

        source_file = inputs["source_file"]
        info(f"Reading file: {source_file}...")
        try:
            job = cast(bluish.nodes.job.Job, step.parent)
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


class RunExternal(bluish.actions.base.Action):
    FQN: str = "core/run-external"

    INPUTS_SCHEMA = Object(
        {
            "job": Optional(Str),
        }
    )

    def run(self, step: bluish.nodes.step.Step) -> bluish.process.ProcessResult:
        workflow = self._get_workflow(step)
        job = workflow.jobs.get("default")
        if not job:
            raise ValueError("No job named 'default' found in the workflow")

        with bluish.process.prepare_host_for(
            workflow, step.get_inherited_attr("runs_on_host")
        ):
            workflow.set_attr("woking_dir", step.get_inherited_attr("working_dir"))

            result = workflow.dispatch_job(job, no_deps=False)
            for k, v in workflow.outputs.items():
                step.outputs[k] = v
            return result

    def _get_workflow(
        self, step: bluish.nodes.step.Step
    ) -> bluish.nodes.workflow.Workflow:
        current_wf = cast(bluish.nodes.workflow.Workflow, step.parent.parent)  # type: ignore
        path = self._get_path(current_wf.yaml_root, step.attrs.uses)
        with open(path, "rb") as f:
            contents = f.read()
        definition = WorkflowDefinition(**yaml.safe_load(contents))
        environment = bluish.nodes.environment.Environment(**{"with": step.attrs._with})
        workflow = bluish.nodes.workflow.Workflow(environment, definition)
        workflow.yaml_root = os.path.dirname(path)
        return workflow

    def _get_path(self, root: str | None, spec: str) -> str:
        if spec.startswith("file://"):
            path = os.path.expanduser(spec[len("file://") :])
            path = os.path.join(root, path) if root else path
            if not path.endswith(".yaml") and not path.endswith(".yml"):
                for ext in (".yaml", ".yml"):
                    if os.path.exists(path + ext):
                        path += ext
                        break
        else:
            raise ValueError(f"Unknown file spec: {spec}")

        if not os.path.exists(path):
            raise ValueError(f"File not found: {path}")

        return path
