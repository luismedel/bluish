import contextlib
import logging
import os
from typing import Never

import click
import yaml

from bluish.__main__ import PROJECT_VERSION
from bluish.core import (
    WorkflowContext,
    init_commands,
)


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
    logging.addLevelName(logging.INFO, "")
    logging.addLevelName(logging.ERROR, "[ERROR] ")
    logging.addLevelName(logging.WARNING, "[WARNING] ")
    logging.addLevelName(logging.DEBUG, "[DEBUG] ")
    logging.addLevelName(logging.CRITICAL, "[CRITICAL] ")

    log_level = getattr(logging, level_name.upper(), logging.INFO)
    logging.basicConfig(level=log_level)
    logging.getLogger().handlers[0].setFormatter(
        LogFormatter("%(levelname)s%(message)s")
    )


def locate_yaml(name: str) -> str | None:
    """Locates the workflow file."""

    if not name:
        name = "bluish"
    if os.path.exists(f"{name}.yaml"):
        return f"{name}.yaml"
    elif os.path.exists(f".bluish/{name}.yaml"):
        return f".bluish/{name}.yaml"
    return None


def workflow_from_file(file: str) -> WorkflowContext:
    """Loads the workflow from a file."""

    yaml_contents: str = ""

    with contextlib.suppress(FileNotFoundError):
        with open(file, "r") as yaml_file:
            yaml_contents = yaml_file.read()

    if not yaml_contents:
        fatal("No workflow file found.")

    return WorkflowContext(yaml.safe_load(yaml_contents))


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
        fatal("No workflow file found.")

    wf = workflow_from_file(yaml_path)
    job = wf.jobs.get(job_id)
    if not job:
        fatal(f"Job '{job_id}' not found.")

    try:
        run, result = wf.try_dispatch_job(job, no_deps)
        if run and result and result.failed:
            exit(result.returncode)
    except Exception as e:
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

    yaml_contents: str = ""
    yaml_path = file or locate_yaml("")
    if not yaml_path:
        fatal("No workflow file found.")

    with contextlib.suppress(FileNotFoundError):
        with open(yaml_path, "r") as yaml_file:
            yaml_contents = yaml_file.read()

    if not yaml_contents:
        fatal("No workflow file found.")

    wf = WorkflowContext(yaml.safe_load(yaml_contents))
    ctx.obj = wf


@bluish_cli.command("list")
@click.pass_obj
def list_jobs(wf: WorkflowContext) -> None:
    available_jobs = wf.jobs

    if len(available_jobs) == 0:
        fatal("No jobs found in workflow file.")

    ids = []
    names = []

    for id, job in available_jobs.items():
        ids.append(id)
        names.append(job.attrs.name or "")

    len_id = max([len(id) for id in ids])

    click.secho(f"{'ID':<{len_id}}  NAME", fg="yellow", bold=True)
    for i in range(len(ids)):
        id = click.style(ids[i], fg="cyan")
        name = click.style(names[i], fg="white")
        click.echo(f"{id:<{len_id}}  {name}")


@bluish_cli.command("run")
@click.argument("job_id", type=str, required=True)
@click.option("--no-deps", is_flag=True, help="Don't run job dependencies")
@click.pass_obj
def run_job(wf: WorkflowContext, job_id: str, no_deps: bool) -> None:
    job = wf.jobs.get(job_id)
    if not job:
        fatal(f"Job '{job_id}' not found.")

    try:
        run, result = wf.try_dispatch_job(job, no_deps)
        if run and result and result.failed:
            exit(result.returncode)
    except Exception as e:
        fatal(str(e))


def test_adhoc():
    blu_cli("ci:fix", False, "DEBUG")


if __name__ == "__main__":
    test_adhoc()
