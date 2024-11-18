from typing import Any, Iterable, Union

from bluish.safe_string import SafeString


class InvalidTypeError(Exception):
    def __init__(self, value: Any, types: str):
        super().__init__(f"{value} is not any of the allowed types: {types}")


class RequiredAttributeError(Exception):
    def __init__(self, param: str):
        super().__init__(f"Missing required attribute: {param}")


class UnexpectedAttributesError(Exception):
    def __init__(self, attrs: Iterable[str]):
        super().__init__(f"Unexpected attributes: {attrs}")


KV = {
    "type": dict,
    "key_schema": str,
    "value_schema": [str, bool, int, float, None],
}

STR_KV = {
    "type": dict,
    "key_schema": str,
    "value_schema": str,
}

STR_LIST = {
    "type": list,
    "item_schema": str,
}

STEP_SCHEMA = {
    "type": dict,
    "properties": {
        "name": [str, None],
        "env": [KV, None],
        "var": [KV, None],
        "secrets": [STR_KV, None],
        "secrets_file": [str, None],
        "env_file": [str, None],
        "uses": [str, None],
        "if": [str, None],
        "continue_on_error": [bool, None],
        "set": [KV, None],
        "echo_commands": [bool, None],
        "echo_output": [bool, None],
        "with": [Any, None],
    },
}

JOB_SCHEMA = {
    "type": dict,
    "properties": {
        "name": [str, None],
        "env": [KV, None],
        "var": [KV, None],
        "secrets": [STR_KV, None],
        "secrets_file": [str, None],
        "env_file": [str, None],
        "runs_on": [str, None],
        "depends_on": [STR_LIST, None],
        "continue_on_error": [bool, None],
        "with": [Any, None],
        "steps": {
            "type": list,
            "item_schema": STEP_SCHEMA,
        },
    },
}

WORKFLOW_SCHEMA = {
    "type": dict,
    "properties": {
        "name": [str, None],
        "env": [KV, None],
        "var": [KV, None],
        "secrets": [STR_KV, None],
        "secrets_file": [str, None],
        "env_file": [str, None],
        "runs_on": [str, None],
        "with": [Any, None],
        "jobs": {
            "type": dict,
            "key_schema": str,
            "value_schema": JOB_SCHEMA,
        },
    },
}


type_def = Union[type, dict, list, None]


def _get_type_repr(t: type_def | None) -> str:
    if t is None:
        return "None"
    elif isinstance(t, list):
        return " | ".join(_get_type_repr(tt) for tt in t)
    elif isinstance(t, dict) and "type" in t:
        return f"{t['type']}"
    else:
        return f"{t}"


def _find_type(value: Any, _def: type_def | None) -> dict | type | None:
    def get_origin(t):
        if t is None:
            return None
        if isinstance(t, SafeString):
            return str
        return get_origin(t.__origin__) if "__origin__" in t.__dict__ else t

    if value is None or _def is None:
        return None
    elif isinstance(_def, list):
        for tt in _def:
            if _find_type(value, tt):
                return tt
        return None
    elif isinstance(_def, dict):
        _t = _def.get("type")
        if _t is None:
            return None
        if _t is Any:
            return _def
        return _def if get_origin(type(value)) is get_origin(_t) else None
    else:
        if _def is Any:
            return _def  # type: ignore
        return _def if get_origin(type(value)) is get_origin(_def) else None


def _is_required(t: type_def | None) -> bool:
    if t is None:
        return False
    elif isinstance(t, list):
        return all(_is_required(tt) for tt in t)
    elif isinstance(t, dict):
        return t.get("required", True)
    else:
        return True


def validate_schema(
    schema: type_def, data: Any, reject_extra_keys: bool = False
) -> None:
    """
    Validate a data structure against a schema.

    >>> validate_schema({"type": str}, "hello")
    >>> validate_schema({"type": str}, 42)
    Traceback (most recent call last):
    ...
    ValueError: 42 is not any of the allowed types: <class 'str'>
    >>> validate_schema({"type": str}, {"hello": "world"})
    Traceback (most recent call last):
    ...
    ValueError: {'hello': 'world'} is not any of the allowed types: <class 'str'>
    >>> validate_schema({"type": dict, "key_schema": {"type": str}, "value_schema": {"type": str}}, {"hello": "world"})
    >>> validate_schema({"type": dict, "key_schema": {"type": str}, "value_schema": {"type": str}}, {"hello": 42})
    Traceback (most recent call last):
    ...
    ValueError: 42 is not any of the allowed types: <class 'str'>
    >>> validate_schema({"type": list, "item_schema": {"type": str}}, ["hello", "world"])
    >>> validate_schema({"type": list, "item_schema": {"type": str}}, ["hello", 42])
    Traceback (most recent call last):
    ...
    ValueError: 42 is not any of the allowed types: <class 'str'>
    """
    
    if data is None and not _is_required(schema):
        return

    type_def = _find_type(data, schema)
    if type_def is None:
        raise InvalidTypeError(data, _get_type_repr(schema))

    if isinstance(type_def, type) or type_def is Any:
        return

    if type_def["type"] == dict:
        assert isinstance(data, dict)
        if "key_schema" in type_def:
            key_schema = type_def["key_schema"]
            for key in data.keys():
                validate_schema(key_schema, key)
        if "value_schema" in type_def:
            value_schema = type_def["value_schema"]
            for val in data.values():
                validate_schema(value_schema, val)
        if "properties" in type_def:
            properties: dict = type_def["properties"]
            for prop, tdef in properties.items():
                if data.get(prop) is None:
                    if not _is_required(tdef):
                        continue
                    raise RequiredAttributeError(f"Missing required key: {prop}")
                validate_schema(tdef, data[prop])

        if reject_extra_keys and "properties" in type_def:
            extra_keys = set(data.keys()) - set(type_def["properties"].keys())
            if extra_keys:
                raise UnexpectedAttributesError(extra_keys)
    elif type_def["type"] == list:
        assert isinstance(data, list)
        item_schema = type_def["item_schema"]
        for item in data:
            validate_schema(item_schema, item)
    elif (
        type_def["type"] not in (str, int, float, bool) and type_def["type"] is not Any
    ):
        raise ValueError(f"Invalid type: {type_def['type']}")


def get_extra_properties(schema: type_def, data: dict) -> dict:
    """
    Get the properties in the data not present in the schema properties.
    """
    if type_def is Any or not isinstance(schema, dict) or not isinstance(data, dict):
        return {}

    properties = schema["properties"].keys()
    return {k: v for k, v in data.items() if k not in properties}
