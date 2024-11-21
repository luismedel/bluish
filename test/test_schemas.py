
from bluish.schemas import (
    AnyType,
    DefaultDict,
    Dict,
    InvalidTypeError,
    List,
    Object,
    Optional,
    RequiredAttributeError,
    Str,
)


def test_happy() -> None:
    schema = Object({
        "name": Str,
        "env": DefaultDict,
    })

    schema.validate({
        "name": "test",
        "env": {"a": "b"},
    })


def test_default_values() -> None:
    schema = Object({
        "name": Str,
        "env": DefaultDict,
        "items": List(Str, default=["a", "b"]),
    })

    data = {
        "name": "test",
    }
    # This should add the default values for "env" and "items"
    schema.validate(data)

    assert "env" in data
    assert data["env"] == {}

    assert "items" in data
    assert data["items"] == ["a", "b"]


def test_missing_key() -> None:
    schema = Object({
        "name": Str,
        "env": Dict,
    })

    try:
        schema.validate({
            "name": "test",
        })
        raise AssertionError("Should have raised an exception")
    except RequiredAttributeError:
        pass


def test_optional_key() -> None:
    schema = Object({
        "name": Optional(Str),
    })

    schema.validate({})
    schema.validate({
        "name": "test",
    })

def test_lists() -> None:
    schema = Object({
        "values": List(Str),
    })
    
    schema.validate({
        "values": ["a", "b"],
    })


def test_lists_any() -> None:
    schema = Object({
        "values": List(AnyType),
    })

    schema.validate({
        "values": ["a", "b", 1, {"a": "b"}, [1, 2, 3]],
    })


def test_lists_ko() -> None:
    schema = Object({
        "values": List(Str),
    })

    try:
        schema.validate({
            "values": ["a", "b", 1],
        })
        raise AssertionError("Should have raised an exception")
    except InvalidTypeError:
        pass
