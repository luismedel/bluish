import os
from typing import Any

from dotenv import dotenv_values

import bluish.core
import bluish.nodes
import bluish.nodes.job
import bluish.process
from bluish.logging import debug, error, info


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
        self.sys_env = {}
        self.jobs = {}
        self.runs_on_host = None

        self.secrets.update(
            {
                k: v
                for k, v in dotenv_values(self.attrs.secrets_file or ".secrets").items()
                if v is not None
            }
        )

        self.sys_env = {
            **os.environ,
            **dotenv_values(self.attrs.env_file or ".env"),
        }

        for k, v in self._job_definitions.items():
            self.jobs[k] = bluish.nodes.job.Job(self, v)

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

        cleanup_host = False
        if not self.runs_on_host:
            self.runs_on_host = self.runs_on_host or bluish.process.prepare_host(
                self.expand_expr(self.attrs.runs_on)
            )
            cleanup_host = True

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
                if not result:
                    continue

                self.result = result
                if result.failed and not job.attrs.continue_on_error:
                    self.failed = True
                    break

            return self.result

        finally:
            if self.status == bluish.core.ExecutionStatus.RUNNING:
                self.status = bluish.core.ExecutionStatus.FINISHED

            if cleanup_host:
                bluish.process.cleanup_host(self.runs_on_host)
                self.runs_on_host = None

    def dispatch_job(
        self, job: bluish.nodes.job.Job, no_deps: bool
    ) -> bluish.process.ProcessResult | None:
        cleanup_host = False
        if not self.runs_on_host:
            self.runs_on_host = self.runs_on_host or bluish.process.prepare_host(
                self.expand_expr(self.attrs.runs_on)
            )
            cleanup_host = True
        result = self.__dispatch_job(job, no_deps, set())

        if cleanup_host:
            bluish.process.cleanup_host(self.runs_on_host)
            self.runs_on_host = None

        return result

    def __dispatch_job(
        self, job: bluish.nodes.job.Job, no_deps: bool, visited_jobs: set[str]
    ) -> bluish.process.ProcessResult | None:
        if job.id in visited_jobs:
            raise bluish.nodes.CircularDependencyError("Circular reference detected")

        if job.status == bluish.core.ExecutionStatus.FINISHED:
            info(f"Job {job.id} already dispatched and finished")
            return job.result
        elif job.status == bluish.core.ExecutionStatus.SKIPPED:
            info(f"Re-running skipped job {job.id}")

        visited_jobs.add(job.id)

        if not no_deps:
            debug("Getting dependency map...")
            for dependency_id in job.attrs.depends_on or []:
                dep_job = self.jobs.get(dependency_id)
                if not dep_job:
                    raise RuntimeError(f"Invalid dependency job id: {dependency_id}")

                result = self.__dispatch_job(dep_job, no_deps, visited_jobs)
                if result and result.failed:
                    error(f"Dependency {dependency_id} failed")
                    return result

        for wf_matrix in bluish.nodes._generate_matrices(self):
            for job_matrix in bluish.nodes._generate_matrices(job):
                job.reset()

                if job.attrs.runs_on:
                    job.runs_on_host = bluish.process.prepare_host(
                        self.expand_expr(job.attrs.runs_on)
                    )
                else:
                    job.runs_on_host = self.runs_on_host
                
                job.matrix = {**wf_matrix, **job_matrix}
                
                try:
                    result = job.dispatch()
                    if result and result.failed:
                        return result
                except:
                    raise
                finally:
                    if job.runs_on_host and job.runs_on_host is not self.runs_on_host:
                        bluish.process.cleanup_host(job.runs_on_host)
                        job.runs_on_host = None

        return bluish.process.ProcessResult()
