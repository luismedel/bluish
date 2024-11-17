import bluish.actions
import bluish.contexts as contexts
import bluish.core
import bluish.process
from bluish.logging import info


class StepContext(contexts.InputOutputNode):
    NODE_TYPE = "step"

    def __init__(self, parent: contexts.ContextNode, definition: contexts.Definition):
        super().__init__(parent, definition)

        self.attrs.ensure_property("name", "")
        self.attrs.ensure_property("uses", "")
        self.attrs.ensure_property("continue_on_error", False)
        self.attrs.ensure_property("shell", bluish.process.DEFAULT_SHELL)

        self.id = self.attrs.id

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
            return self.id

    def dispatch(self) -> bluish.process.ProcessResult | None:
        info(f"* Run step '{self.display_name}'")

        if not contexts.can_dispatch(self):
            self.status = bluish.core.ExecutionStatus.SKIPPED
            info(" >>> Skipped")
            return None

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
