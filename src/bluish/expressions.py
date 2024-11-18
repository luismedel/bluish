import re
from typing import Any, Callable

import lark

import bluish.contexts
from bluish.safe_string import SafeString

SENSITIVE_LITERALS = ("password", "secret", "token")

EXPRESSION_REGEX = re.compile(r"\${{(.+?)}}", re.DOTALL)

EXPRESSION_GRAMMAR = r"""
    ?start: expression

    ?expression: or_expr
    ?ternary_expr: or_expr "?" or_expr ":" or_expr -> ternary

    ?or_expr: and_expr
            | or_expr "||" and_expr -> or_
            | ternary_expr

    ?and_expr: equality_expr
             | and_expr "&&" equality_expr -> and_

    ?equality_expr: relational_expr
                  | equality_expr "==" relational_expr -> eq
                  | equality_expr "!=" relational_expr -> ne

    ?relational_expr: additive_expr
                    | relational_expr "<" additive_expr  -> lt
                    | relational_expr ">" additive_expr  -> gt
                    | relational_expr "<=" additive_expr -> le
                    | relational_expr ">=" additive_expr -> ge

    ?additive_expr: multiplicative_expr
                | additive_expr "+" multiplicative_expr  -> add
                | additive_expr "-" multiplicative_expr  -> sub

    ?multiplicative_expr: unary_expr
                        | multiplicative_expr "*" unary_expr -> mul
                        | multiplicative_expr "/" unary_expr -> div
                        | multiplicative_expr "%" unary_expr -> mod

    ?unary_expr: primary_expr
               | "-" unary_expr -> neg
               | "!" unary_expr -> not_

    ?primary_expr: NUMBER             -> number
                 | VARIABLE           -> var
                 | STRING             -> str
                 | "(" expression ")"

    VARIABLE: /[a-zA-Z_.][a-zA-Z0-9_.]*/
    NUMBER: /[0-9]+(\.[0-9]+)?/
    STRING: ESCAPED_STRING | /'[^']*'/ | /"[^"]*"/

    %import common.ESCAPED_STRING
    %import common.WS

    %ignore WS
"""


_parser = lark.Lark(EXPRESSION_GRAMMAR, parser="lalr")


def to_number(value: Any) -> Any:
    if isinstance(value, (int, float)):
        return value
    elif value.isnumeric():
        return int(value)
    elif value.replace(".", "").isnumeric():
        return float(value)
    else:
        raise ValueError(f"Invalid number: {value}")


def to_bool(value: Any) -> bool:
    if isinstance(value, bool):
        return value
    elif value.isnumeric() or value.replace(".", "").isnumeric():
        return float(value) != 0
    else:
        return bool(value)


def concat(a: Any, b: Any) -> Any:
    if a is None:
        return b
    if b is None:
        return a

    result = SafeString(str(a) + str(b))
    result.redacted_value = (
        a.redacted_value if isinstance(a, SafeString) else str(a)
    )
    result.redacted_value += (
        b.redacted_value if isinstance(b, SafeString) else str(b)
    )
    return result


@lark.v_args(inline=True)
class ExprTransformer(lark.visitors.Transformer_InPlaceRecursive):
    def __init__(self, ctx: bluish.contexts.ContextNode):
        self.expr_depth: int = 0
        self.context = ctx

    def number(self, value: str) -> int | float:
        return to_number(value)

    def str(self, value: str) -> str:
        if isinstance(value, SafeString):
            return SafeString(value[1:-1], value.redacted_value[1:-1])
        elif isinstance(value, str):
            return value[1:-1]
        else:
            return str(value)

    def expr(self, expr: Any) -> Any:
        return expr

    def add(self, a: Any, b: Any) -> Any:
        if isinstance(a, (int, float)) or isinstance(b, (int, float)):
            return a + b
        else:
            return concat(a, b)

    def sub(self, a: int | float, b: int | float) -> int | float:
        return to_number(a) - to_number(b)

    def mul(self, a: int | float, b: int | float) -> int | float:
        return to_number(a) * to_number(b)

    def div(self, a: int | float, b: int | float) -> int | float:
        return to_number(a) / to_number(b)

    def mod(self, a: int | float, b: int | float) -> int | float:
        return to_number(a) % to_number(b)

    def neg(self, a: int | float) -> int | float:
        return -to_number(a)

    def eq(self, a: Any, b: Any) -> bool:
        return a == b

    def ne(self, a: Any, b: Any) -> bool:
        return a != b

    def lt(self, a: Any, b: Any) -> bool:
        return a < b

    def gt(self, a: Any, b: Any) -> bool:
        return a > b

    def le(self, a: Any, b: Any) -> bool:
        return a <= b

    def ge(self, a: Any, b: Any) -> bool:
        return a >= b

    def and_(self, a: Any, b: Any) -> bool:
        return to_bool(a) and to_bool(b)

    def or_(self, a: Any, b: Any) -> bool:
        return to_bool(a) or to_bool(b)

    def not_(self, a: Any) -> bool:
        return not to_bool(a)

    def var(self, name) -> Any:
        if name == "true":
            return True
        elif name == "false":
            return False
        else:
            return self.context.get_value(str(name))

    def ternary(self, condition: Any, true_expr: Any, false_expr: Any) -> Any:
        return true_expr if to_bool(condition) else false_expr


def create_parser(ctx: bluish.contexts.ContextNode) -> Callable[[str], Any]:
    """Create a parser with the given context.

    >>> ctx = context.WorkflowContext({"secrets": {"password": "1234"}})
    >>> ctx.set_value("var.x", 10)
    >>> parse = create_parser(ctx)
    >>> parse("${{ x + 10 }}")
    20.0
    >>> parse("${{ x * 10 }}")
    100.0
    >>> parse("${{ x == 10 }}")
    True
    >>> parse("${{ x != 10 }}")
    False
    >>> parse("${{ x < 10 }}")
    False
    >>> parse("${{ x > 10 }}")
    False
    >>> parse("${{ x <= 10 }}")
    True
    >>> parse("${{ x >= 10 }}")
    True
    >>> parse("${{ x && true }}")
    True
    >>> parse("${{ x || false }}")
    True
    >>> parse("${{ !x }}")
    False
    >>> bool(parse("${{ x }}"))
    True
    >>> bool(parse("${{ true }}"))
    True
    >>> bool(parse("${{ false }}"))
    False
    >>> ctx.set_value("var.x", 10)
    >>> parse("${{ x }}")
    10.0
    >>> ctx.set_value("var.x", 10.0)
    >>> parse("${{ x }}")
    10.0
    >>> ctx.set_value("var.x", "hello")
    >>> parse("${{ x }}")
    'hello'
    >>> ctx.set_value("var.x", True)
    >>> parse("${{ x }}")
    True
    >>> ctx.set_value("var.x", 1)
    >>> parse("one == ${{ x }}")
    'one == 1'
    >>> parse("one == ${{ x }}!!")
    'one == 1!!'
    >>> parse('${{ "a" + "b" }}')
    'ab'
    >>> parse('${{ "a" + secrets.password }}')
    'a1234'
    >>> parse('${{ "a" + secrets.password }}').redacted_value
    'a********'
    >>> parse('${{ secrets.password }}')
    '1234'
    """

    transformer = ExprTransformer(ctx)

    def parse(value: str) -> Any:
        result: Any = None

        offset = 0

        for m in re.finditer(EXPRESSION_REGEX, value):
            previous_chunk = value[offset : m.start()]
            ast = _parser.parse(m.group(1))
            try:
                parse_result = transformer.transform(ast)
            except lark.exceptions.VisitError as e:
                if e.orig_exc:
                    raise e.orig_exc
                else:
                    raise RuntimeError(
                        f"Error parsing expression: {m.group(1)}: {str(e)}"
                    )

            offset = m.end()

            if previous_chunk:
                result = concat(result, previous_chunk)

            result = concat(result, parse_result)

        last_chunk = value[offset:]
        if last_chunk:
            result = concat(result, last_chunk)

        return result

    return parse
