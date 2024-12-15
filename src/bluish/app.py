import contextlib
import logging
import os
from typing import Any, Iterable

import click
import yaml
from dotenv import dotenv_values
from typing_extensions import Never

from bluish.__main__ import PROJECT_VERSION
from bluish.core import (
    init_commands,
)
from bluish.nodes import WorkflowDefinition
from bluish.nodes.environment import Environment
from bluish.nodes.job import Job
from bluish.nodes.workflow import Workflow


class LogFormatter(logging.Formatter):
    COLORS = {
        logging.DEBUG: "white",
        logging.INFO: "bright_white",
        logging.WARNING: "yellow",
        logging.ERROR: "red",
        logging.CRITICAL: "bright_red",
    }

    def __init__(self, format: str) -> None:
        super().__init__(fmt=format)

    def format(self, record: logging.LogRecord) -> str:
        record.msg = click.style(
            record.msg, fg=self.COLORS.get(record.levelno, "white")
        )
        return super().format(record)


def fatal(message: str, exit_code: int = 1) -> Never:
    click.secho(message, fg="red", bold=True)
    exit(exit_code)


def init_logging(level_name: str) -> None:
    for level in [
        logging.INFO,
        logging.DEBUG,
        logging.WARNING,
        logging.ERROR,
        logging.CRITICAL,
    ]:
        logging.addLevelName(level, "")

    log_level = getattr(logging, level_name.upper(), logging.INFO)
    logging.basicConfig(level=log_level)
    logging.getLogger().handlers[0].setFormatter(
        LogFormatter("%(levelname)s%(message)s")
    )


def locate_yaml(name: str) -> str | None:
    """Locates the workflow file."""

    if not name:
        name = "bluish"

    paths = (name, f".bluish/{name}")
    exts = (".yaml", ".yml")

    for path in paths:
        for ext in exts:
            if os.path.exists(f"{path}{ext}"):
                return f"{path}{ext}"

    return None


def create_environment(definition: dict[str, Any]) -> Environment:
    """Creates an environment object."""

    return Environment(
        **{
            "sys_env": definition.get(
                "sys_env", {**os.environ, **dotenv_values(".env")}
            ),
            "with": definition.get("with", {}),
        }
    )


def load_workflow(file: str, args: Iterable[str]) -> Workflow:
    yaml_contents: str = ""
    yaml_path = file or locate_yaml("")
    if not yaml_path:
        fatal("No workflow file found.")
        return

    logging.info(f"Loading workflow from {yaml_path}")
    logging.info("")

    with contextlib.suppress(FileNotFoundError):
        with open(yaml_path, "r") as yaml_file:
            yaml_contents = yaml_file.read()

    if not yaml_contents:
        fatal("No workflow file found.")
        return

    environment = create_environment(
        {"with": {k: v for k, v in (arg.split("=", maxsplit=1) for arg in args)}}
    )
    definition = WorkflowDefinition(**yaml.safe_load(yaml_contents))
    wf = Workflow(environment, definition)
    wf.yaml_root = os.path.dirname(yaml_path)
    return wf


def list_workflow_jobs(wf: Workflow) -> None:
    if not wf.jobs:
        fatal("No jobs found in workflow file.")

    items = sorted(
        (
            (id, job.attrs.name or "", job.attrs.depends_on)
            for id, job in wf.jobs.items()
        ),
        key=lambda x: x[0],
    )
    id_len = max(len(id) for id, _, _ in items)

    click.secho(f"{'ID':<{id_len}}  NAME", fg="yellow", bold=True)
    for id, name, depends_on in items:
        if depends_on:
            name = f"{name} (depends on: {', '.join(depends_on)})"
        click.echo(f"{id:<{id_len}}  {name}")


@click.command("blu")
@click.argument("job_id", type=str, required=True)
@click.option("--no-deps", is_flag=True, help="Don't run job dependencies")
@click.option(
    "--log-level",
    type=click.Choice(["DEBUG", "INFO", "WARNING", "ERROR"]),
    default="INFO",
    help="Log level",
)
@click.version_option(PROJECT_VERSION)
@click.argument("args", nargs=-1, type=click.UNPROCESSED)
def blu_cli(
    job_id: str,
    no_deps: bool,
    log_level: str,
    args: tuple[str],
) -> None:
    init_logging(log_level)
    init_commands()

    file: str = ""
    if ":" in job_id:
        file, job_id = job_id.split(":")

    yaml_path = locate_yaml(file)
    if not yaml_path:
        fatal("No workflow file found.")
        return

    logging.info(f"Loading workflow from {yaml_path}")
    logging.info("")

    wf = load_workflow(yaml_path, args)
    if not job_id:
        list_workflow_jobs(wf)
        return

    job: Job | None = wf.jobs.get(job_id)
    if not job:
        fatal(f"Job '{job_id}' not found.")
        return

    try:
        result = wf.dispatch_job(job, no_deps)
        if result.failed:
            exit(result.returncode)
        else:
            click.secho("Job completed successfully.", fg="green")

    except Exception as e:
        if os.environ.get("BLUISH_DEBUG"):
            import traceback

            trace = traceback.format_exc()
            print(trace)
        fatal(str(e))


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
@click.version_option(PROJECT_VERSION)
@click.pass_context
def bluish_cli(
    ctx: click.Context,
    file: str,
    log_level: str,
) -> None:
    init_logging(log_level)
    init_commands()

    yaml_path = file or locate_yaml("")
    if not yaml_path:
        fatal("No workflow file found.")
        return

    ctx.obj = yaml_path


@bluish_cli.command("list")
@click.pass_obj
def list_jobs(yaml_path: str) -> None:
    wf = load_workflow(yaml_path, [])
    list_workflow_jobs(wf)


@bluish_cli.command("run")
@click.argument("job_id", type=str, required=True)
@click.option("--no-deps", is_flag=True, help="Don't run job dependencies")
@click.argument("args", nargs=-1, type=click.UNPROCESSED)
@click.pass_obj
def run_job(yaml_path: str, job_id: str, no_deps: bool, args: tuple[str]) -> None:
    wf = load_workflow(yaml_path, args)
    job = wf.jobs.get(job_id)
    if not job:
        fatal(f"Job '{job_id}' not found.")
        return

    try:
        result = wf.dispatch_job(job, no_deps)
        if result.failed:
            exit(result.returncode)
        else:
            click.secho("Job completed successfully.", fg="green")
    except Exception as e:
        if os.environ.get("BLUISH_DEBUG"):
            import traceback

            trace = traceback.format_exc()
            print(trace)

        fatal(str(e))


if __name__ == "__main__":
    pass
