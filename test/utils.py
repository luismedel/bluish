
import yaml
from bluish.core import (
    PipeContext,
)


def create_pipe(yaml_definition: str) -> PipeContext:
    definition = yaml.safe_load(yaml_definition)
    return PipeContext(definition)
