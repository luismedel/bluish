
import bluish.nodes.workflow
import yaml
from bluish.nodes import WorkflowDefinition


def create_workflow(yaml_definition: str) -> bluish.nodes.workflow.Workflow:
    definition = WorkflowDefinition(**yaml.safe_load(yaml_definition))
    return bluish.nodes.workflow.Workflow(definition)
