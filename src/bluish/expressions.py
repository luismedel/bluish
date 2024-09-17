import re
from typing import Any, Callable

import lark

from bluish import context
from bluish.redacted_string import RedactedString

SENSITIVE_LITERALS = ("password", "secret", "token")

EXPRESSION_REGEX = re.compile(r"\${{(.+?)}}", re.DOTALL)

EXPRESSION_GRAMMAR = r"""
    ?start: expression

    ?expression: or_expr

    ?or_expr: and_expr
            | or_expr "||" and_expr -> or_

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


@lark.v_args(inline=True)  # Affects the signatures of the methods
class ExprTransformer(lark.Transformer):
    def __init__(self, ctx: context.ContextNode):
        self.expr_depth: int = 0
        self.context = ctx

    def number(self, value: str) -> float:
        return float(value)

    def str(self, value: str) -> str:
        if isinstance(value, RedactedString):
            return RedactedString(value[1:-1], value.redacted_value[1:-1])
        elif isinstance(value, str):
            return value[1:-1]
        else:
            return str(value)

    def expr(self, expr: Any) -> Any:
        return expr

    def to_number(self, value: Any) -> Any:
        if isinstance(value, (int, float)):
            return value
        elif value.isnumeric():
            return int(value)
        else:
            return float(value)

    def add(self, a: Any, b: Any) -> Any:
        if isinstance(a, (int, float)) or isinstance(b, (int, float)):
            return a + b
        elif isinstance(a, str) and isinstance(b, str):
            if isinstance(a, RedactedString) or isinstance(b, RedactedString):
                return self.concat(a, b)
            else:
                return a + b
        else:
            return float(a) + float(b)

    def sub(self, a: Any, b: Any) -> float:
        return float(a) - float(b)

    def mul(self, a: Any, b: Any) -> float:
        return float(a) * float(b)

    def div(self, a: Any, b: Any) -> float:
        return float(a) / float(b)

    def mod(self, a: Any, b: Any) -> float:
        return float(a) % float(b)

    def neg(self, a: Any) -> float:
        return -float(a)

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
        return bool(a) and bool(b)

    def or_(self, a: Any, b: Any) -> bool:
        return bool(a) or bool(b)

    def not_(self, a: Any) -> bool:
        return not bool(a)

    def var(self, name) -> Any:
        if name == "true":
            return True
        elif name == "false":
            return False
        else:
            return self.context.get_value(str(name))

    @staticmethod
    def concat(a: Any, b: Any) -> Any:
        if a is None:
            return b
        if b is None:
            return a

        result = RedactedString(str(a) + str(b))
        result.redacted_value = (
            a.redacted_value if isinstance(a, RedactedString) else str(a)
        )
        result.redacted_value += (
            b.redacted_value if isinstance(b, RedactedString) else str(b)
        )
        return result


def create_parser(ctx: context.ContextNode) -> Callable[[str], Any]:
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

    parser = lark.Lark(
        EXPRESSION_GRAMMAR, parser="lalr", transformer=ExprTransformer(ctx)
    )

    def parse(value: str) -> Any:
        result: Any = None

        offset = 0

        for m in re.finditer(EXPRESSION_REGEX, value):
            previous_chunk = value[offset : m.start()]
            parse_result = parser.parse(m.group(1))
            offset = m.end()

            if previous_chunk:
                result = ExprTransformer.concat(result, previous_chunk)

            result = ExprTransformer.concat(result, parse_result)

        last_chunk = value[offset:]
        if last_chunk:
            result = ExprTransformer.concat(result, last_chunk)

        return result

    return parse
