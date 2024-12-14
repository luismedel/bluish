import logging
from typing import Dict

_REGISTERED_ACTIONS: Dict[str, type] = {}
_PROTOCOL_ACTIONS: Dict[str, type] = {}


def get_action(fqn: str) -> type | None:
    if fqn in _REGISTERED_ACTIONS:
        return _REGISTERED_ACTIONS[fqn]
    else:
        for prefix, action in _PROTOCOL_ACTIONS.items():
            if fqn.startswith(prefix):
                return action
    return None


def register_action(klass: type) -> None:
    if not hasattr(klass, "FQN"):
        raise ValueError("Action class must have an FQN attribute")
    if klass.FQN in _REGISTERED_ACTIONS and _REGISTERED_ACTIONS[klass.FQN] != klass:
        raise ValueError(f"Action {klass.FQN} is already registered")
    if not klass.FQN:
        logging.debug(f"Registering default action from {klass.__name__}")
    else:
        logging.debug(f"Registering action {klass.FQN} from {klass.__name__}")
    _REGISTERED_ACTIONS[klass.FQN] = klass


def register_protocol_action(prefix: str, klass: type) -> None:
    if not hasattr(klass, "FQN"):
        raise ValueError("Action class must have an FQN attribute")
    if prefix in _PROTOCOL_ACTIONS and _PROTOCOL_ACTIONS[prefix] != klass:
        raise ValueError(f"Protocol {prefix} is already registered")
    logging.debug(f"Registering protocol action {prefix} from {klass.__name__}")
    _PROTOCOL_ACTIONS[prefix] = klass


def reset_actions() -> None:
    _REGISTERED_ACTIONS.clear()
    _PROTOCOL_ACTIONS.clear()
