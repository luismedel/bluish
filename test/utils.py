
from typing import Any

import bluish.nodes.environment
import bluish.nodes.workflow
import yaml
from bluish.nodes import WorkflowDefinition


def create_environment(definition: dict[str, Any]) -> bluish.nodes.environment.Environment:
    return bluish.nodes.environment.Environment(**definition)


def create_workflow(environment: bluish.nodes.environment.Environment | None, yaml_definition: str) -> bluish.nodes.workflow.Workflow:
    definition = WorkflowDefinition(**yaml.safe_load(yaml_definition))
    return bluish.nodes.workflow.Workflow(environment, definition)
