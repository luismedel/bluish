from typing import cast

import bluish.actions.base
import bluish.contexts.job
import bluish.contexts.step
from bluish.logging import error, info
from bluish.process import ProcessResult, install_package
from bluish.schemas import STR_LIST


class InstallPackages(bluish.actions.base.Action):
    FQN: str = "macos/install-packages"

    INPUTS_SCHEMA = {
        "type": dict,
        "properties": {
            "packages": STR_LIST,
            "flavor": [str, None],
        },
    }

    def run(self, step: bluish.contexts.step.StepContext) -> ProcessResult:
        package_str = " ".join(step.inputs["packages"])
        flavor = step.inputs.get("flavor", "auto")

        info(f"Installing packages {package_str}...")

        job = cast(bluish.contexts.job.JobContext, step.parent)

        result = install_package(
            job.runs_on_host, step.inputs["packages"], flavor=flavor
        )
        if result.failed:
            error(f"Failed to install packages {package_str}\n{result.error}")

        return result
