import os
from itertools import product
from typing import Any

from dotenv import dotenv_values

import bluish.contexts
import bluish.contexts.job
import bluish.core
import bluish.process
from bluish.logging import debug, error, info


class WorkflowContext(bluish.contexts.ContextNode):
    NODE_TYPE = "workflow"

    def __init__(self, definition: bluish.contexts.Definition) -> None:
        super().__init__(None, definition)

        self.attrs.ensure_property("var", {})
        self.attrs.ensure_property("secrets", {})
        self.attrs.ensure_property("jobs", {})

        self.secrets = {
            **self.attrs.secrets,
            **dotenv_values(self.attrs.secrets_file or ".secrets"),
        }

        self.env = {
            **self.attrs.env,
        }

        self.sys_env = {
            **os.environ,
            **dotenv_values(self.attrs.env_file or ".env"),
        }

        self.jobs = {
            k: bluish.contexts.job.JobContext(self, k, bluish.contexts.JobDefinition(v))
            for k, v in self.attrs.jobs.items()
        }
        self.var = dict(self.attrs.var)

        self.runs_on_host: dict[str, Any] | None = None

    def dispatch(self) -> bluish.process.ProcessResult:
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
        self, job: bluish.contexts.job.JobContext, no_deps: bool
    ) -> bluish.process.ProcessResult | None:
        return self.__dispatch_job(job, no_deps, set())

    def __dispatch_job(
        self, job: bluish.contexts.job.JobContext, no_deps: bool, visited_jobs: set[str]
    ) -> bluish.process.ProcessResult | None:
        if job.id in visited_jobs:
            raise bluish.contexts.CircularDependencyError("Circular reference detected")

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

        if job.attrs.matrix:
            for matrix_tuple in product(*job.attrs.matrix.values()):
                job.matrix = {
                    key: self.expand_expr(value)
                    for key, value in zip(job.attrs.matrix.keys(), matrix_tuple)
                }
                result = job.dispatch()
                job.matrix = {}
                if result and result.failed:
                    return result

            return bluish.process.ProcessResult()
        else:
            return job.dispatch()
