import subprocess

import click
import yaml

from bluish.core import (
    Connection,
    PipeContext,
    init_commands,
)
from bluish.log import fatal, warn


@click.command()
@click.argument("pipeline_file", type=click.Path(exists=True))
@click.option("--host", "-h", type=str, required=False, help="Host to connect to via SSH")
@click.option("--hide-commands", is_flag=True, help="Don't echo commands")
@click.option("--hide-output", is_flag=True, help="Don't echo commands output")
def main(pipeline_file: str, host: str, hide_commands: bool, hide_output: bool) -> None:
    init_commands()

    if not host:
        warn("No host specified. Running locally.")
    conn = Connection(host)
    conn.echo_commands = not hide_commands
    conn.echo_output = not hide_output
    with open(pipeline_file, "r") as yaml_file:
        yaml_contents = yaml_file.read()

    pipe = PipeContext(conn, yaml.safe_load(yaml_contents))
    pipe.dispatch()


if __name__ == "__main__":
    main()
