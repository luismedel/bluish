import subprocess

import click
import yaml

from bluish.core import (
    Connection,
    PipeContext,
    init_commands,
)
from bluish.log import fatal


# @click.command()
# @click.argument("pipeline_file", type=click.Path(exists=True))
# @click.option("--host", "-h", help="Host to connect to via SSH")
def main(pipeline_file: str, host: str) -> None:
    try:
        conn = Connection(host)
        with open(pipeline_file, "r") as yaml_file:
            yaml_contents = yaml_file.read()

        yaml_contents = """
working_dir: /tmp

jobs:
  cwd:
    - steps:
        - run: pwd
"""
        pipe = PipeContext(conn, yaml.safe_load(yaml_contents))
        pipe.dispatch()
    except subprocess.CalledProcessError as e:
        fatal(e.stderr)


init_commands()

if __name__ == "__main__":
    main("", "development")
