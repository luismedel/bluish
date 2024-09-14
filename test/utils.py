
import yaml
from bluish.context import WorkflowContext


def create_workflow(yaml_definition: str) -> WorkflowContext:
    definition = yaml.safe_load(yaml_definition)
    return WorkflowContext(definition)
