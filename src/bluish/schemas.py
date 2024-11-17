from typing import Any, Union

KV = {
    "type": dict,
    "key_schema": {"type": str},
    "value_schema": {"type": str},
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
        "secrets": [KV, None],
        "secrets_file": [str, None],
        "env_file": [str, None],
        "uses": [str, None],
        "run": [str, None],
        "with": [Any, None],
        "if": [str, None],
        "continue_on_error": [bool, None],
    },
}

JOB_SCHEMA = {
    "type": dict,
    "properties": {
        "name": [str, None],
        "env": [KV, None],
        "var": [KV, None],
        "secrets": [KV, None],
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
        "secrets": [KV, None],
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


def _find_type(value: Any, t: type_def | None) -> dict | type | None:
    if value is None or t is None:
        return None
    elif isinstance(t, list):
        return next((tt for tt in t if _find_type(value, tt)), None)  # type: ignore
    elif isinstance(t, dict):
        if "type" not in t:
            return None
        if t["type"] is Any:
            return t
        return t if type(value) is t["type"] else None
    else:
        if t is Any:
            return t  # type: ignore
        return t if type(value) is t else None


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

    type_def = _find_type(data, schema)
    if type_def is None:
        raise ValueError(
            f"{data} is not any of the allowed types: {_get_type_repr(schema)}"
        )

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
                    raise ValueError(f"Missing required key: {prop}")
                validate_schema(tdef, data[prop])

        if reject_extra_keys and "properties" in type_def:
            extra_keys = set(data.keys()) - set(type_def["properties"].keys())
            if extra_keys:
                raise ValueError(f"Extra keys: {extra_keys}")
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
