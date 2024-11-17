import logging
from typing import Dict

_REGISTERED_ACTIONS: Dict[str, type] = {}


def get_action(fqn: str) -> type | None:
    return _REGISTERED_ACTIONS.get(fqn)


def register_action(klass: type) -> None:
    if not hasattr(klass, "FQN"):
        raise ValueError("Action class must have an FQN attribute")
    if klass.FQN in _REGISTERED_ACTIONS and _REGISTERED_ACTIONS[klass.FQN] != klass:
        raise ValueError(f"Action {klass.FQN} is already registered")
    logging.debug(f"Registering action: {klass.FQN}")
    _REGISTERED_ACTIONS[klass.FQN] = klass
