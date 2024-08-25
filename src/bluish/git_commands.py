from bluish.core import JobContext, ProcessResult


def _git_command(ctx: JobContext, command: str) -> ProcessResult:
    inputs = ctx.get_inputs()

    pwd = inputs.get("path") or ctx.get_var("pipe.working_dir")
    if not pwd:
        return ctx.run(f"git {command}")
    else:
        return ctx.run(f'git -C "{pwd}" {command}')


def git(ctx: JobContext) -> None:
    inputs = ctx.get_inputs()
    result = _git_command(ctx, inputs["args"])
    ctx.save_output(result)


def git_pull(ctx: JobContext) -> ProcessResult:
    return _git_command(ctx, "pull")


def git_get_latest_release(ctx: JobContext) -> ProcessResult:
    return _git_command(ctx, "rev-parse --short HEAD")
