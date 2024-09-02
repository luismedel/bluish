import os

import click
import yaml

from bluish.core import (
    JobContext,
    ProcessError,
    WorkflowContext,
    fatal,
    init_commands,
    init_logging,
)


def locate_yaml(name: str) -> str | None:
    if not name:
        name = "bluish"
    if os.path.exists(f"{name}.yaml"):
        return f"{name}.yaml"
    elif os.path.exists(f".bluish/{name}.yaml"):
        return f".bluish/{name}.yaml"
    return None


def pipe_from_file(file: str) -> WorkflowContext:
    yaml_contents: str = ""
    try:
        with open(file, "r") as yaml_file:
            yaml_contents = yaml_file.read()
    except FileNotFoundError:
        pass

    if not yaml_contents:
        fatal("No pipeline file found.")

    return WorkflowContext(yaml.safe_load(yaml_contents))


def dispatch_job(pipe: WorkflowContext, job_id: str, no_deps: bool) -> None:
    available_jobs = pipe.jobs

    job = available_jobs.get(job_id)
    if not job:
        fatal(f"Invalid job id: {job_id}")

    executed_jobs: set[str] = set()
    deps: dict[str, list[JobContext]] = {}

    def gen_dependencies(job: JobContext) -> None:
        assert job.id is not None

        if job.id in deps:
            return
        deps[job.id] = []
        for dep in job.attrs.depends_on or []:
            dep_job = available_jobs.get(dep)
            if not dep_job:
                fatal(f"Invalid dependency job id: {dep}")
            deps[job.id].append(dep_job)
            gen_dependencies(dep_job)

    def dispatch_job(job: JobContext):
        assert job.id is not None

        if job.id in executed_jobs:
            return
        executed_jobs.add(job.id)

        dependencies = deps.get(job.id)
        if dependencies:
            for dependency in dependencies:
                dispatch_job(dependency)

        job.dispatch()

    if not no_deps:
        gen_dependencies(job)

    try:
        dispatch_job(job)
    except ProcessError as e:
        if e.result:
            fatal(str(e), e.result.returncode)
        else:
            fatal(str(e))
    except Exception:
        raise


@click.command("blu")
@click.argument("job_id", type=str, required=True)
@click.option("--no-deps", is_flag=True, help="Don't run job dependencies")
@click.option(
    "--log-level",
    type=click.Choice(["DEBUG", "INFO", "WARNING", "ERROR"]),
    default="INFO",
    help="Log level",
)
def blu_cli(
    job_id: str,
    no_deps: bool,
    log_level: str,
) -> None:
    init_logging(log_level)
    init_commands()

    file: str = ""
    if ":" in job_id:
        file, job_id = job_id.split(":")

    yaml_path = locate_yaml(file)
    if not yaml_path:
        fatal("No pipeline file found.")

    pipe = pipe_from_file(yaml_path)
    dispatch_job(pipe, job_id, no_deps)


@click.group("bluish")
@click.option(
    "--file", "-f", type=click.Path(dir_okay=False, readable=True, resolve_path=True)
)
@click.option(
    "--log-level",
    type=click.Choice(["DEBUG", "INFO", "WARNING", "ERROR"]),
    default="INFO",
    help="Log level",
)
@click.pass_context
def bluish_cli(
    ctx: click.Context,
    file: str,
    log_level: str,
) -> None:
    init_logging(log_level)
    init_commands()

    yaml_contents: str = ""
    yaml_path = file or locate_yaml("")
    if not yaml_path:
        fatal("No pipeline file found.")

    try:
        with open(yaml_path, "r") as yaml_file:
            yaml_contents = yaml_file.read()
    except FileNotFoundError:
        pass

    if not yaml_contents:
        fatal("No pipeline file found.")

    pipe = WorkflowContext(yaml.safe_load(yaml_contents))
    ctx.obj = pipe


@bluish_cli.command("list")
@click.pass_obj
def list_jobs(pipe: WorkflowContext) -> None:
    available_jobs = pipe.jobs

    if len(available_jobs) == 0:
        fatal("No jobs found in pipeline file.")

    ids = []
    names = []

    for id, job in available_jobs.items():
        ids.append(id)
        names.append(job.attrs.name or "")

    len_id = max([len(id) for id in ids])

    print("List of available jobs:")
    print(f"{'ID':<{len_id}}  NAME")
    for i in range(len(ids)):
        id = ids[i]
        name = names[i]
        print(f"{id:<{len_id}}  {name}")


@bluish_cli.command("run")
@click.argument("job_id", type=str, required=True)
@click.option("--no-deps", is_flag=True, help="Don't run job dependencies")
@click.pass_obj
def run_job(pipe: WorkflowContext, job_id: str, no_deps: bool) -> None:
    dispatch_job(pipe, job_id, no_deps)


if __name__ == "__main__":
    pass
