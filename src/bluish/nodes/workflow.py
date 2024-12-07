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

        self._job_definitions: dict = {}
        for k, v in self.attrs.jobs.items():
            v["id"] = k
            self._job_definitions[k] = bluish.nodes.JobDefinition(**v)

        self.reset()

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

    def dispatch(self) -> bluish.process.ProcessResult:
        self.reset()

        self.status = bluish.core.ExecutionStatus.RUNNING

        if self.attrs.runs_on:
            self.runs_on_host = bluish.process.prepare_host(
                self.expand_expr(self.attrs.runs_on)
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
            bluish.process.cleanup_host(self.runs_on_host)
            self.runs_on_host = None

    def dispatch_job(
        self, job: bluish.nodes.job.Job, no_deps: bool
    ) -> bluish.process.ProcessResult | None:
        return self.__dispatch_job(job, no_deps, set())

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
                job.matrix = {**wf_matrix, **job_matrix}
                result = job.dispatch()
                if result and result.failed:
                    return result

        return bluish.process.ProcessResult()
