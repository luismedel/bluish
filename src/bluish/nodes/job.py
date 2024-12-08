import base64
from typing import Any
from uuid import uuid4

import bluish.core
import bluish.nodes
import bluish.process
from bluish.logging import debug, error, info, warning
from bluish.utils import decorate_for_log


class Job(bluish.nodes.Node):
    NODE_TYPE = "job"

    def __init__(
        self,
        parent: bluish.nodes.Node,
        definition: bluish.nodes.Definition,
    ):
        import bluish.nodes.step

        super().__init__(parent, definition)

        self.runs_on_host: dict[str, Any] | None
        self.matrix: dict[str, Any]
        self.steps: list[bluish.nodes.step.Step]

        self._step_definitions: list[bluish.nodes.StepDefinition] = []
        for i, step_dict in enumerate(self.attrs.steps):
            step_dict["id"] = step_dict.get("id", f"step_{i+1}")
            self._step_definitions.append(bluish.nodes.StepDefinition(**step_dict))

        self.reset()

    def reset(self) -> None:
        import bluish.nodes.step

        self.runs_on_host = None
        self.matrix = {}
        self.steps = []

        for step_def in self._step_definitions:
            step = bluish.nodes.step.Step(self, step_def)
            self.steps.append(step)

    def dispatch(self) -> bluish.process.ProcessResult | None:
        self.status = bluish.core.ExecutionStatus.RUNNING

        info(f"** Run job '{self.display_name}'")

        if self.attrs.runs_on:
            self.runs_on_host = bluish.process.prepare_host(
                self.expand_expr(self.attrs.runs_on)
            )
        else:
            self.runs_on_host = self.parent.runs_on_host  # type: ignore

        try:
            bluish.nodes.log_dict(self.matrix, header="matrix", ctx=self)

            if not bluish.nodes.can_dispatch(self):
                self.status = bluish.core.ExecutionStatus.SKIPPED
                info("Job skipped")
                return None

            for step in self.steps:
                result = step.dispatch()
                if not result:
                    continue

                self.result = result

                if result.failed and not step.attrs.continue_on_error:
                    self.failed = True
                    break

        finally:
            if self.status == bluish.core.ExecutionStatus.RUNNING:
                self.status = bluish.core.ExecutionStatus.FINISHED
            bluish.process.cleanup_host(self.runs_on_host)
            self.runs_on_host = None

        return self.result

    def read_file(self, file_path: str) -> bytes:
        return bluish.nodes._read_file(self, file_path)

    def write_file(self, file_path: str, content: bytes) -> None:
        bluish.nodes._write_file(self, file_path, content)

    def exec(
        self,
        command: str,
        context: bluish.nodes.Node,
        env: dict[str, str] | None = None,
        shell: str | None = None,
        stream_output: bool = False,
    ) -> bluish.process.ProcessResult:
        command = context.expand_expr(command).strip()
        if "${{" in command:
            raise ValueError("Command contains unexpanded variables")

        host = self.runs_on_host

        if context.get_inherited_attr("is_sensitive", False):
            stream_output = False

        # Define where to capture the output with the >> operator
        capture_filename = f"/tmp/{uuid4().hex}"
        debug(f"Capture file: {capture_filename}")
        touch_result = bluish.process.run(f"touch {capture_filename}", host)
        if touch_result.failed:
            error(
                f"Failed to create capture file {capture_filename}: {touch_result.error}"
            )
            return touch_result

        env = env or {}

        if "BLUISH_OUTPUT" in env:
            warning(
                "BLUISH_OUTPUT is a reserved environment variable. Overwriting it.",
            )

        env["BLUISH_OUTPUT"] = capture_filename

        env_str = "; ".join([f'{k}="{v}"' for k, v in env.items()]).strip()
        if env_str:
            command = f"{env_str}; {command}"

        if shell is None:
            shell = context.get_inherited_attr("shell", bluish.process.DEFAULT_SHELL)
        assert shell is not None

        interpreter = bluish.process.SHELLS.get(shell, shell)
        if interpreter:
            b64 = base64.b64encode(command.encode()).decode()
            command = f"echo {b64} | base64 -di - | {interpreter}"

        working_dir = context.get_inherited_attr("working_directory")
        if working_dir:
            debug(f"Working dir: {working_dir}")
            debug("Making sure working directory exists...")
            mkdir_result = bluish.process.run(f"mkdir -p {working_dir}", host)
            if mkdir_result.failed:
                error(
                    f"Failed to create working directory {working_dir}: {mkdir_result.error}"
                )
                return mkdir_result

            command = f'cd "{working_dir}" && {command}'

        def stdout_handler(line: str) -> None:
            info(decorate_for_log(line.rstrip(), "  > "))

        def stderr_handler(line: str) -> None:
            error(decorate_for_log(line.rstrip(), " ** "))

        run_result = bluish.process.run(
            command,
            host_opts=host,
            stdout_handler=stdout_handler if stream_output else None,
            stderr_handler=stderr_handler if stream_output else None,
        )

        # HACK: We should use our own process.read_file here,
        # but it currently causes an infinite recursion
        output_result = bluish.process.run(f"cat {capture_filename}", host)
        if output_result.failed:
            error(f"Failed to read capture file: {output_result.error}")
            return output_result

        for line in output_result.stdout.splitlines():
            k, v = line.split("=", maxsplit=1)
            context.outputs[k] = v

        return run_result
