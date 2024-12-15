from typing import Any

import bluish.nodes


class Environment(bluish.nodes.Node):
    NODE_TYPE = "environment"

    def __init__(self, **kwargs: Any) -> None:
        super().__init__(None, bluish.nodes.Definition(**kwargs))
