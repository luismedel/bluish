import os
from contextlib import contextmanager
from typing import Any, Generator

from dotenv import dotenv_values

import bluish.core
import bluish.nodes
import bluish.nodes.job
import bluish.process
from bluish.logging import debug, error, info


@contextmanager
def prepare_host_for(
    node: bluish.nodes.Node
) -> Generator[dict[str, Any] | None, None, None]:
    inherited = node.get_inherited_attr("runs_on_host")
    if node.attrs.runs_on:
        runs_on_host = bluish.process.prepare_host(node.expand_expr(node.attrs.runs_on))
        node.set_attr("runs_on_host", runs_on_host)
        yield runs_on_host
        node.clear_attr("runs_on_host")
        if runs_on_host is not inherited:
            runs_on_host.clear()
            bluish.process.cleanup_host(runs_on_host)
    else:
        node.set_attr("runs_on_host", inherited)
        yield inherited
        node.clear_attr("runs_on_host")


class Workflow(bluish.nodes.Node):
    NODE_TYPE = "workflow"

    def __init__(self, definition: bluish.nodes.Definition) -> None:
        super().__init__(None, definition)

        self._sys_env: dict[str, str | None] | None
        self.jobs: dict[str, bluish.nodes.job.Job] = {}

        self.secrets.update(
            {
                k: v
                for k, v in dotenv_values(self.attrs.secrets_file or ".secrets").items()
                if v is not None
            }
        )

        self._sys_env = None

        for k, v in self.attrs.jobs.items():
            v["id"] = k
            self.jobs[k] = bluish.nodes.job.Job(self, bluish.nodes.JobDefinition(**v))

    @property
    def sys_env(self) -> dict[str, str | None]:
        if self._sys_env is None:
            self._sys_env = {
                **os.environ,
                **dotenv_values(self.attrs.env_file or ".env"),
            }
        return self._sys_env

    def set_inputs(self, inputs: dict[str, str]) -> None:
        def is_true(v: Any) -> bool:
            return v in ("true", "1", True)

        for param in self.attrs.inputs:
            name = param.get("name")
            if not name:
                raise ValueError("Invalid input parameter (missing name)")

            if is_true(param.get("sensitive")):
                self.sensitive_inputs.add(name)

            if name in inputs or "default" in param:
                self.inputs[name] = self.expand_expr(
                    inputs.get(name, param.get("default"))
                )
            elif is_true(param.get("required")):
                raise ValueError(f"Missing required input parameter: {name}")

        known_keys = set(p["name"] for p in self.attrs.inputs)

        # Check for unknown input parameters
        unknowns = list(k for k in inputs.keys() if k not in known_keys)
        if unknowns:
            if len(unknowns) == 1:
                raise ValueError(f"Unknown input parameter: {unknowns[0]}")
            else:
                raise ValueError(f"Unknown input parameters: {unknowns}")

    def dispatch(self) -> bluish.process.ProcessResult:
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

            with prepare_host_for(self):
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

                    with prepare_host_for(job):
                        result = job.dispatch()
                        if result.failed:
                            return result

        return bluish.process.ProcessResult()
