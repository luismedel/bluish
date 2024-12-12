import bluish.actions
import bluish.core
import bluish.nodes as nodes
import bluish.process
from bluish.logging import info


class Step(nodes.Node):
    NODE_TYPE = "step"

    def __init__(self, parent: nodes.Node, definition: nodes.Definition):
        super().__init__(parent, definition)

        self.action_class = bluish.actions.get_action(self.attrs.uses)
        if self.action_class is None:
            raise ValueError(f"Unknown action: {self.attrs.uses}")

    @property
    def display_name(self) -> str:
        if self.attrs.name:
            return self.attrs.name
        elif self.action_class.FQN:  # type: ignore
            return self.action_class.FQN  # type: ignore
        elif self.attrs.run:
            return self.attrs.run.split("\n", maxsplit=1)[0]
        else:
            return self.attrs.id

    def dispatch(self) -> bluish.process.ProcessResult:
        info(f"* Run step '{self.display_name}'")

        if not nodes.can_dispatch(self):
            self.status = bluish.core.ExecutionStatus.SKIPPED
            info(" >>> Skipped")
            return bluish.process.ProcessResult.EMPTY

        self.status = bluish.core.ExecutionStatus.RUNNING

        try:
            assert self.action_class is not None

            if self.attrs.uses:
                info(f"Running {self.attrs.uses}")

            self.result = self.action_class().execute(self)
            self.failed = self.result.failed

        finally:
            self.status = bluish.core.ExecutionStatus.FINISHED

        return self.result
