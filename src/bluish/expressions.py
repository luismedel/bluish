import re
from typing import Any, Callable

import lark

from bluish import context

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

    %import common.ESCAPED_STRING -> STRING
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

    def expr(self, expr: Any) -> Any:
        return expr

    def add(self, a: float, b: float) -> float:
        return a + b

    def sub(self, a: float, b: float) -> float:
        return a - b

    def mul(self, a: float, b: float) -> float:
        return a * b

    def div(self, a: float, b: float) -> float:
        return a / b

    def mod(self, a: float, b: float) -> float:
        return a % b

    def neg(self, a: float) -> float:
        return -a

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
            return self.context.get_value(name)


def create_parser(ctx: context.ContextNode) -> Callable[[str, bool], Any]:
    """Create a parser with the given context.

    >>> ctx = context.ContextNode(None, {})
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
    10
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
    """

    parser = lark.Lark(
        EXPRESSION_GRAMMAR, parser="lalr", transformer=ExprTransformer(ctx)
    )

    def parse(value: str, redact_secrets: bool = False) -> Any:
        def replace(m) -> str:
            group1 = m.group(1)
            if redact_secrets and any(
                s for s in SENSITIVE_LITERALS if s in group1.lower()
            ):
                return "********"
            return str(parser.parse(group1))

        result = re.sub(EXPRESSION_REGEX, replace, value)
        if result in ("True", "False"):
            return result == "True"
        elif result.isdigit():
            return int(result)
        elif result.replace(".", "", 1).isdigit():
            return float(result)
        else:
            return result

    return parse
