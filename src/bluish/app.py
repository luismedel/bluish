import click
import yaml

from bluish.core import (
    Connection,
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
    pipe.env["ECHO_COMMANDS"] = not hide_commands
    pipe.env["ECHO_OUTPUT"] = not hide_output
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
@click.argument("job_id", type=str, required=False, nargs=-1)
@click.pass_obj
def run_jobs(pipe: PipeContext, job_id: list[str]) -> None:
    available_jobs = pipe.jobs
    if len(available_jobs) == 0:
        fatal("No jobs found in pipeline file.")

    if not job_id:
        fatal("No job id specified.")

    for id in job_id:
        if id not in available_jobs:
            fatal(f"Invalid job id: {id}")

    try:
        for id in job_id:
            pipe.dispatch_job(id)
    except ProcessError as e:
        fatal(str(e), e.result.returncode)
    except Exception as e:
        fatal(str(e))


if __name__ == "__main__":
    main()
