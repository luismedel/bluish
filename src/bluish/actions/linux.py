from typing import cast

import bluish.actions.base
import bluish.contexts.job
import bluish.contexts.step
import bluish.process
from bluish.logging import error, info
from bluish.schemas import STR_LIST


class InstallPackages(bluish.actions.base.Action):
    FQN: str = "linux/install-packages"

    INPUTS_SCHEMA = {
        "type": dict,
        "properties": {
            "packages": STR_LIST,
            "flavor": [str, None],
        },
    }

    def run(
        self, step: bluish.contexts.step.StepContext
    ) -> bluish.process.ProcessResult:
        package_str = " ".join(step.inputs["packages"])
        flavor = step.inputs.get("flavor", "auto")

        info(f"Installing packages {package_str}...")

        job = cast(bluish.contexts.job.JobContext, step.parent)

        result = bluish.process.install_package(
            job.runs_on_host, step.inputs["packages"], flavor=flavor
        )
        if result.failed:
            error(f"Failed to install packages {package_str}\n{result.error}")

        return result
