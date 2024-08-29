import click
import yaml

from bluish.core import (
    Connection,
    JobContext,
    PipeContext,
    ProcessError,
    fatal,
    init_commands,
    init_logging,
)


@click.group("bluish")
@click.option(
    "--file",
    "-f",
    type=click.Path(dir_okay=False, readable=True, resolve_path=True),
    default="./bluish.yaml",
)
@click.option(
    "--host", "-h", type=str, required=False, help="Host to connect to via SSH"
)
@click.option("--hide-commands", is_flag=True, help="Hide commands from stdout")
@click.option("--hide-output", is_flag=True, help="Hide commands output from stdout")
@click.option(
    "--log-level",
    type=click.Choice(["DEBUG", "INFO", "WARNING", "ERROR"]),
    default="INFO",
    help="Log level",
)
@click.pass_context
def main(
    ctx: click.Context,
    file: str,
    host: str,
    hide_commands: bool,
    hide_output: bool,
    log_level: str,
) -> None:
    init_logging(log_level)
    init_commands()

    yaml_contents: str = ""
    try:
        with open(file, "r") as yaml_file:
            yaml_contents = yaml_file.read()
    except FileNotFoundError:
        pass

    if not yaml_contents:
        fatal("No pipeline file found.")

    conn = Connection(host)

    pipe = PipeContext(yaml.safe_load(yaml_contents), conn)
    ctx.obj = pipe


@main.command("list")
@click.pass_obj
def list_jobs(pipe: PipeContext) -> None:
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


@main.command("run")
@click.argument("job_id", type=str, required=True)
@click.option("--no-deps", is_flag=True, help="Don't run job dependencies")
@click.pass_obj
def run_jobs(pipe: PipeContext, job_id: str, no_deps: bool) -> None:
    available_jobs = pipe.jobs
    if len(available_jobs) == 0:
        fatal("No jobs found in pipeline file.")

    if not job_id:
        fatal("No job id specified.")

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


if __name__ == "__main__":
    main()
