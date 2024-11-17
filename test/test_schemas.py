
from typing import Any

from bluish.schemas import KV, validate_schema


def test_happy() -> None:
    schema = {
        "type": dict,
        "properties": {
            "name": [str, None],
            "env": [KV, None],
        },
    }

    validate_schema(schema, {
        "name": "test",
        "env": {"a": "b"},
    })
    
    validate_schema(schema, {
        "name": "test",
    })


def test_missing_key() -> None:
    schema = {
        "type": dict,
        "properties": {
            "name": str,
            "env": KV,
        },
    }

    data = {
        "name": "test",
    }
    
    try:
        validate_schema(schema, data)
        raise AssertionError("Should have raised an exception")
    except ValueError as e:
        assert str(e) == "Missing required key: env"


def test_optional_key() -> None:
    schema = {
        "type": dict,
        "properties": {
            "name": [str, None],
        },
    }

    data: dict = {
    }

    validate_schema(schema, data)


def test_lists() -> None:
    schema = {
        "type": dict,
        "properties": {
            "values": {
                "type": list,
                "item_schema": str,
            },
        },
    }
    
    data = {
        "values": ["a", "b"],
    }
    
    validate_schema(schema, data)


def test_lists_any() -> None:
    schema = {
        "type": dict,
        "properties": {
            "values": {
                "type": list,
                "item_schema": Any,
            },
        },
    }

    data = {
        "values": ["a", "b", 1, {"a": "b"}, [1, 2, 3]],
    }
    
    validate_schema(schema, data)


def test_lists_ko() -> None:
    schema = {
        "type": dict,
        "properties": {
            "values": {
                "type": list,
                "item_schema": str,
            },
        },
    }

    data = {
        "values": ["a", "b", 1],
    }
    
    try:
        validate_schema(schema, data)
        raise AssertionError("Should have raised an exception")
    except ValueError as e:
        assert str(e) == "1 is not any of the allowed types: <class 'str'>"
