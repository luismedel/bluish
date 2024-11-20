
from bluish.contexts import WorkflowDefinition
import bluish.contexts.workflow
import yaml


def create_workflow(yaml_definition: str) -> bluish.contexts.workflow.WorkflowContext:
    definition = WorkflowDefinition(**yaml.safe_load(yaml_definition))
    return bluish.contexts.workflow.WorkflowContext(definition)
