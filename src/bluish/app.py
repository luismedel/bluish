import subprocess
from typing import Any

import click
import yaml

from bluish.core import (
    REGISTERED_ACTIONS,
    Connection,
    JobContext,
    PipeContext,
    init_commands,
)
from bluish.log import fatal, info
from bluish.utils import ensure_list


def initialize_vars(pipe: PipeContext) -> None:
    pipe.vars["pipe.working_dir"] = pipe.conn.run("pwd").stdout.strip()


def process_pipeline(pipe: PipeContext) -> None:
    initialize_vars(pipe)

    for job in pipe.get_jobs():
        process_job(job)


def process_job(ctx: JobContext) -> None:
    if ctx.current_step is None:
        return

    while ctx.current_step is not None:
        step = ctx.current_step

        if "name" in step:
            info(f"Processing step: {step['name']}")

        execute_action: bool = True

        if "if" in step:
            condition = step["if"]
            info(f"Testing {condition}")
            if not isinstance(condition, str):
                fatal("Condition must be a string")

            check_cmd = condition.strip()
            check_result = ctx.run(check_cmd).stdout.strip()
            if not check_result.endswith("true") and not check_result.endswith("1"):
                info("Skipping step")
                execute_action = False

        if execute_action:
            fqn = step.get("uses", "command-runner")
            fn = REGISTERED_ACTIONS.get(fqn)
            if fn:
                info(f"Running action: {fqn}")
                result = fn(ctx)
            else:
                fatal(f"Unknown action: {fqn}")
            ctx.save_output(result)

        ctx.increment_step()


# @click.command()
# @click.argument("pipeline_file", type=click.Path(exists=True))
# @click.option("--host", "-h", help="Host to connect to via SSH")
def main(pipeline_file: str, host: str) -> None:
    try:
        conn = Connection(host)
        pipe_def: dict[str, Any]
        with open(pipeline_file, "r") as yaml_file:
            pipe_def = yaml.safe_load(yaml_file)
        pipe_def["jobs"] = ensure_list(pipe_def["jobs"])
        pipe = PipeContext(conn, pipe_def)
        for ctx in pipe.get_jobs():
            process_job(ctx)
    except subprocess.CalledProcessError as e:
        fatal(e.stderr)
    except Exception as e:
        fatal(str(e))


init_commands()

if __name__ == "__main__":
    main("/Users/luis/src/blue-green/blue/deploy/test.yaml", "development")
