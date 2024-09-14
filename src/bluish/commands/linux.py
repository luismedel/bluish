from bluish.action import action
from bluish.context import StepContext
from bluish.logging import error, info
from bluish.process import ProcessResult, install_package


@action("linux/install-packages", required_inputs=["packages"])
def system_install_packages(step: StepContext) -> ProcessResult:
    package_str = " ".join(step.inputs["packages"])
    flavor = step.inputs.get("flavor", "auto")

    info(f"Installing packages {package_str}...")

    result = install_package(
        step.job.runs_on_host, step.inputs["packages"], flavor=flavor
    )
    if result.failed:
        error(f"Failed to install packages {package_str}\n{result.error}")

    return result
