import os
from typing import Any

from dotenv import dotenv_values

import bluish.core
import bluish.nodes
import bluish.nodes.job
import bluish.process
from bluish.logging import debug, error, info


class PrepareHostContext:
    def __init__(
        self, node: bluish.nodes.Node, existing_host: dict[str, Any] | None
    ) -> None:
        self.node = node
        self.existing_host = existing_host
        self.cleanup_host = False

    def __enter__(self) -> None:
        if self.node.attrs.runs_on and not getattr(self.node, "runs_on_host", None):
            runs_on_host = bluish.process.prepare_host(
                self.node.expand_expr(self.node.attrs.runs_on)
            )
            setattr(self.node, "runs_on_host", runs_on_host)
            self.cleanup_host = True
        else:
            setattr(self.node, "runs_on_host", self.existing_host)
            self.cleanup_host = False

    def __exit__(self, exc_type, exc_val, exc_tb) -> None:
        if (
            not self.cleanup_host
            or getattr(self.node, "runs_on_host", None) is self.existing_host
        ):
            return
        bluish.process.cleanup_host(self.node.runs_on_host)
        setattr(self.node, "runs_on_host", None)


def prepare_host(
    node: bluish.nodes.Node, existing_host: dict[str, Any] | None = None
) -> PrepareHostContext:
    return PrepareHostContext(node, existing_host)


class Workflow(bluish.nodes.Node):
    NODE_TYPE = "workflow"

    def __init__(self, definition: bluish.nodes.Definition) -> None:
        super().__init__(None, definition)

        self.matrix: dict
        self.sys_env: dict
        self.jobs: dict
        self.runs_on_host: dict[str, Any] | None
        self._inputs: dict[str, str] | None = None

        self._job_definitions: dict = {}
        for k, v in self.attrs.jobs.items():
            v["id"] = k
            self._job_definitions[k] = bluish.nodes.JobDefinition(**v)

        self.reset()

    @property
    def inputs(self) -> dict[str, str]:
        return self._inputs or {}

    def reset(self) -> None:
        self.matrix = {}
        self.jobs = {}
        self.runs_on_host = None

        self.secrets.update(
            {
                k: v
                for k, v in dotenv_values(self.attrs.secrets_file or ".secrets").items()
                if v is not None
            }
        )

        self._sys_env: dict | None = None

        for k, v in self._job_definitions.items():
            self.jobs[k] = bluish.nodes.job.Job(self, v)

    @property
    def sys_env(self) -> dict[str, str]:
        if self._sys_env is None:
            self._sys_env = {
                **os.environ,
                **dotenv_values(self.attrs.env_file or ".env"),
            }
        return self._sys_env

    def set_inputs(self, inputs: dict[str, str]) -> None:
        def is_true(v: Any) -> bool:
            return v in ("true", "1", True)

        self._inputs = {}
        for param in self.attrs.inputs:
            name = param.get("name")
            if not name:
                raise ValueError("Invalid input parameter (missing name)")

            if is_true(param.get("sensitive")):
                self.sensitive_inputs.add(name)

            if name in inputs or "default" in param:
                self._inputs[name] = self.expand_expr(
                    inputs.get(name, param.get("default"))
                )
            elif is_true(param.get("required")):
                raise ValueError(f"Missing required input parameter: {name}")

        # Check for unknown input parameters
        unknowns = list(k for k in inputs.keys() if k not in self._inputs)
        if unknowns:
            if len(unknowns) == 1:
                raise ValueError(f"Unknown input parameter: {unknowns[0]}")
            else:
                raise ValueError(f"Unknown input parameters: {unknowns}")

    def dispatch(self) -> bluish.process.ProcessResult:
        self.reset()

        self.status = bluish.core.ExecutionStatus.RUNNING

        bluish.nodes.log_dict(
            self.inputs,
            header="with",
            ctx=self,
            sensitive_keys=self.sensitive_inputs,
        )

        try:
            for job in self.jobs.values():
                result = self.dispatch_job(job, no_deps=False)
                self.result = result
                if result.failed and not job.attrs.continue_on_error:
                    self.failed = True
                    break

            return self.result

        finally:
            if self.status == bluish.core.ExecutionStatus.RUNNING:
                self.status = bluish.core.ExecutionStatus.FINISHED

    def dispatch_job(
        self, job: bluish.nodes.job.Job, no_deps: bool
    ) -> bluish.process.ProcessResult:
        return self.__dispatch_job(job, no_deps, set())

    def __dispatch_job(
        self, job: bluish.nodes.job.Job, no_deps: bool, visited_jobs: set[str]
    ) -> bluish.process.ProcessResult:
        if job.attrs.id in visited_jobs:
            raise bluish.nodes.CircularDependencyError("Circular reference detected")

        if job.status == bluish.core.ExecutionStatus.FINISHED:
            info(f"Job {job.attrs.id} already dispatched and finished")
            return job.result
        elif job.status == bluish.core.ExecutionStatus.SKIPPED:
            info(f"Re-running skipped job {job.attrs.id}")

        visited_jobs.add(job.attrs.id)

        if not no_deps:
            debug("Getting dependency map...")
            for dependency_id in job.attrs.depends_on or []:
                dep_job = self.jobs.get(dependency_id)
                if not dep_job:
                    raise RuntimeError(f"Invalid dependency job id: {dependency_id}")

                result = self.__dispatch_job(dep_job, no_deps, visited_jobs)
                if result.failed:
                    error(f"Dependency {dependency_id} failed")
                    return result

        def get_matrix_hash(matrix: dict[str, Any]) -> str:
            return "-".join(sorted(f"{k}:{v}" for k, v in matrix.items()))

        executed_matrices = set()

        for wf_matrix in bluish.nodes._generate_matrices(self):
            self.matrix = wf_matrix

            with prepare_host(self, self.runs_on_host):
                for job_matrix in bluish.nodes._generate_matrices(job):
                    matrix = {**wf_matrix, **job_matrix}
                    if matrix:
                        matrix_hash = get_matrix_hash(matrix)
                        if matrix_hash in executed_matrices:
                            info("Skipping already executed matrix...")
                            continue
                        executed_matrices.add(matrix_hash)

                    job.reset()
                    job.matrix = matrix

                    with prepare_host(job, self.runs_on_host):
                        result = job.dispatch()
                        if result.failed:
                            return result

        return bluish.process.ProcessResult()
