from typing import cast

import bluish.actions.base
import bluish.contexts.job
import bluish.contexts.step
import bluish.process
from bluish.logging import error, info


class InstallPackages(bluish.actions.base.Action):
    FQN: str = "linux/install-packages"
    REQUIRED_INPUTS: tuple[str, ...] = ("packages",)

    def run(
        self, step: bluish.contexts.step.StepContext
    ) -> bluish.process.ProcessResult:
        package_str = " ".join(step.inputs["packages"])
        flavor = step.inputs.get("flavor", "auto")

        info(f"Installing packages {package_str}...")

        job = cast(bluish.contexts.job.JobContext, step.job)

        result = bluish.process.install_package(
            job.runs_on_host, step.inputs["packages"], flavor=flavor
        )
        if result.failed:
            error(f"Failed to install packages {package_str}\n{result.error}")

        return result
