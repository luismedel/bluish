import inspect
from collections import ChainMap
from typing import Any as TAny
from typing import Iterable, Union, cast

import bluish.process
from bluish.safe_string import SafeString


class Validator:
    def __init__(self, *types: type | TAny | None, **kwargs: TAny) -> None:
        self._types = tuple(_ensure_validator_instance(t) for t in types)
        self._args = kwargs
        self._default_value = self._get_default_raw_value()

    @property
    def has_default_value(self) -> bool:
        return self._default_value is not None

    def get_default_value(self) -> TAny | None:
        if self._default_value is not None:
            return (
                self._default_value()
                if callable(self._default_value)
                else self._default_value
            )
        return None

    def _get_default_raw_value(self) -> TAny | None:
        _default: TAny | None = None

        if "default" not in self._args:
            for t in self._types:
                if t is None or not isinstance(t, Validator):
                    continue

                _default = t._get_default_raw_value()
                if _default is not None:
                    return _default
            return None
        else:
            return self._args["default"]

    def validate(self, data: TAny) -> None:
        for t in self._types:
            if _validate_type(t, data):
                return
        raise InvalidTypeError(self, None, data)

    def __repr__(self) -> str:
        return f"{self.__class__.__name__}({self._types})"


TTypeValidator = Union[type, Validator, None]


class InvalidTypeError(Exception):
    def __init__(
        self, type: TTypeValidator, property: str | None, value: TAny | None
    ) -> None:
        super().__init__()
        self.type = type
        self.property = property
        self.value = value

    def __str__(self) -> str:
        if self.property is None:
            return f"{self.value} is not any of the allowed types: {self.type}"
        return f"Property '{self.property}' with value {self.value} is not any of the allowed types: {self.type}"


class RequiredAttributeError(Exception):
    def __init__(self, attr: str):
        super().__init__()
        self.attr = attr

    def __str__(self) -> str:
        return f"Required attribute '{self.attr}' is missing"


class UnexpectedAttributesError(Exception):
    def __init__(self, attrs: Iterable[str]):
        super().__init__(f"Unexpected attributes: {attrs}")


def _validate_type(t: TTypeValidator, data: TAny) -> bool:
    if t is None:
        return True
    elif t is TAny:
        return True
    elif isinstance(t, Validator):
        t.validate(data)
        return True
    elif isinstance(data, cast(type, t)):
        return True
    else:
        return False


def _validate_or_fail(t: TTypeValidator, data: TAny) -> None:
    if not _validate_type(t, data):
        raise InvalidTypeError(t, None, data)


def _ensure_validator_instance(t: TTypeValidator) -> TTypeValidator:
    """
    Ensure that if we receive an uninstanciated Validator class, we return an instance of it.
    """
    if t is None:
        return None
    elif inspect.isclass(t) and issubclass(t, Validator):
        return t()
    else:
        return t


class Str(Validator):
    def __init__(self, **kwargs: TAny) -> None:
        super().__init__(str, SafeString, **kwargs)

    def __repr__(self) -> str:
        return "string"


class Int(Validator):
    def __init__(self, **kwargs: TAny) -> None:
        super().__init__(int, **kwargs)

    def __repr__(self) -> str:
        return "int"


class Float(Validator):
    def __init__(self, **kwargs: TAny) -> None:
        super().__init__(float, int, **kwargs)

    def __repr__(self) -> str:
        return "float"


class Bool(Validator):
    def __init__(self, **kwargs: TAny) -> None:
        super().__init__(bool, **kwargs)

    def __repr__(self) -> str:
        return "bool"


class AnyType(Validator):
    def __init__(self, **kwargs: TAny) -> None:
        super().__init__(TAny, **kwargs)

    def __repr__(self) -> str:
        return "any"


class Dict(Validator):
    def __init__(
        self,
        key_schema: TTypeValidator = Str,
        value_schema: TTypeValidator = AnyType,
        **kwargs: TAny,
    ) -> None:
        super().__init__(dict, **kwargs)
        self._key_schema = _ensure_validator_instance(key_schema)
        self._value_schema = _ensure_validator_instance(value_schema)

    def validate(self, data: TAny) -> None:
        if not isinstance(data, (dict, ChainMap)):
            raise InvalidTypeError(self, None, data)

        for k, v in data.items():
            _validate_or_fail(self._key_schema, k)
            _validate_or_fail(self._value_schema, v)

    def __repr__(self) -> str:
        return f"dict<{repr(self._key_schema)}, {repr(self._value_schema)}>"


class Object(Validator):
    def __init__(self, properties: dict[str, TTypeValidator], **kwargs: TAny) -> None:
        reject_extra = kwargs.pop("reject_extra", True)

        super().__init__(dict, **kwargs)
        self._properties = {
            k: _ensure_validator_instance(v) for k, v in properties.items()
        }
        self._reject_extra = reject_extra

    def validate(self, data: TAny) -> None:
        if not isinstance(data, (dict, ChainMap)):
            raise InvalidTypeError(self, None, data)

        all_props = self._properties.items()
        required = {k for k, t in all_props if not isinstance(t, Optional)}
        optional = {k for k, t in all_props if isinstance(t, Optional)}

        def ensure_property(k: str) -> bool:
            t = self._properties[k]
            if k not in data and isinstance(t, Validator) and t.has_default_value:
                data[k] = t.get_default_value()
                return True
            return False

        def validate_property(k: str) -> None:
            try:
                _validate_or_fail(self._properties[k], data[k])
            except InvalidTypeError:
                raise InvalidTypeError(self._properties[k], k, data[k])

        for k in required:
            if k not in data:
                if not ensure_property(k):
                    raise RequiredAttributeError(k)
                continue
            try:
                validate_property(k)
            except InvalidTypeError as ex:
                raise InvalidTypeError(self._properties[k], k, data[k]) from ex
            except RequiredAttributeError as ex:
                raise RequiredAttributeError(f"{k}.{ex.attr}") from ex

        for k in optional:
            if k not in data:
                _ = ensure_property(k)
                continue
            try:
                validate_property(k)
            except InvalidTypeError as ex:
                raise InvalidTypeError(self._properties[k], k, data[k]) from ex
            except RequiredAttributeError as ex:
                raise RequiredAttributeError(f"{k}.{ex.attr}") from ex

    def __repr__(self) -> str:
        return f"object<{', '.join(f'{k}: {v}' for k, v in self._properties.items())}>"


class List(Validator):
    def __init__(self, item_schema: type | Validator, **kwargs: TAny) -> None:
        super().__init__(list, **kwargs)
        self._item_schema = _ensure_validator_instance(item_schema)

    def validate(self, data: TAny) -> None:
        if not isinstance(data, list):
            raise InvalidTypeError(self, None, data)

        for item in data:
            _validate_or_fail(self._item_schema, item)

    def __repr__(self) -> str:
        return f"list<{repr(self._item_schema)}>"


class Optional(Validator):
    def __init__(self, *types: type | Validator, **kwargs: TAny) -> None:
        super().__init__(None, *types, **kwargs)

    def __repr__(self) -> str:
        return f"Optional<{', '.join(repr(t) for t in self._types)}>"


DefaultDict = Dict(default=dict)

DefaultStringDict = Dict(Str, Str, default=dict)

DefaultStringList = List(Str, default=list)

_COMMON_PROPERTIES = {
    "id": Optional(Str),
    "name": Optional(Str),
    "description": Optional(Str),
    "env": DefaultDict,
    "var": DefaultDict,
    "secrets": DefaultStringDict,
    "secrets_file": Optional(Str),
    "env_file": Optional(Str),
    "if": Optional(Str, Bool),
    "echo_commands": Bool(default=True),
    "echo_output": Bool(default=True),
    "continue_on_error": Bool(default=False),
    "with": DefaultDict,
    "outputs": DefaultDict,
    "set": DefaultDict,
}

STEP_SCHEMA = Object(
    {
        **_COMMON_PROPERTIES,
        "uses": Str(default=""),
        "shell": Str(default=bluish.process.DEFAULT_SHELL),
    }
)


INPUT_DEFINITION_SCHEMA = Object(
    {
        "name": Str,
        "description": Optional(Str),
        "required": Bool(default=False),
        "sensitive": Bool(default=False),
        "default": Optional(AnyType),
    }
)


JOB_SCHEMA = Object(
    {
        **_COMMON_PROPERTIES,
        "inputs": List(INPUT_DEFINITION_SCHEMA, default=list),
        "runs_on": Optional(Str),
        "depends_on": DefaultStringList,
        "steps": List(STEP_SCHEMA),
    }
)


WORKFLOW_SCHEMA = Object(
    {
        **_COMMON_PROPERTIES,
        "inputs": List(INPUT_DEFINITION_SCHEMA, default=list),
        "runs_on": Optional(Str),
        "jobs": Dict(Str, JOB_SCHEMA),
    }
)
