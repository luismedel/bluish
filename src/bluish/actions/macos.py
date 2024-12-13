from typing import cast

import bluish.actions.base
import bluish.nodes.job
import bluish.nodes.step
from bluish.logging import error, info
from bluish.process import ProcessResult, install_package
from bluish.schemas import DefaultStringList, Object, Optional, Str


class InstallPackages(bluish.actions.base.Action):
    FQN: str = "macos/install-packages"

    INPUTS_SCHEMA = Object(
        {
            "packages": DefaultStringList,
            "flavor": Optional(Str),
        }
    )

    def run(self, step: bluish.nodes.step.Step) -> ProcessResult:
        package_str = " ".join(step.inputs["packages"])
        flavor = step.inputs.get("flavor", "auto")

        info(f"Installing packages {package_str}...")

        job = cast(bluish.nodes.job.Job, step.parent)

        result = install_package(
            job.get_inherited_attr("runs_on_host"),
            step.inputs["packages"],
            flavor=flavor,
        )
        if result.failed:
            error(f"Failed to install packages {package_str}\n{result.error}")

        return result
