import click
import yaml

from bluish.core import (
    Connection,
    PipeContext,
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
    conn.echo_commands = not hide_commands
    conn.echo_output = not hide_output

    pipe = PipeContext(conn, yaml.safe_load(yaml_contents))
    ctx.obj = pipe


@main.command("list")
@click.pass_obj
def list_jobs(pipe: PipeContext) -> None:
    available_jobs = pipe.get_jobs()

    if len(available_jobs) == 0:
        fatal("No jobs found in pipeline file.")

    ids = []
    names = []
    helps = []

    for id, desc in available_jobs.items():
        ids.append(id)
        names.append(desc.get("name", ""))
        helps.append(desc.get("help", ""))

    len_id = max([len(id) for id in ids])
    len_name = max([len(name) for name in names])

    print("List of available jobs:")
    print(f"{'ID':<{len_id}}  {'NAME':<{len_name}}  {'HELP'}")
    for i in range(len(ids)):
        id = ids[i]
        name = names[i]
        help = helps[i]
        print(f"{id:<{len_id}}  {name:<{len_name}}  {help}")


@main.command("run")
@click.argument("job_id", type=str, required=False, nargs=-1)
@click.pass_obj
def run_jobs(pipe: PipeContext, job_id: list[str]) -> None:
    available_jobs = pipe.get_jobs()
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
    except Exception as e:
        raise
        fatal(str(e))


if __name__ == "__main__":
    main()
