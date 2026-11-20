"""A tiny, sandboxed arithmetic expression evaluator.

Used for editor-defined formulas (state fees, penalties), e.g.

    "max(bhm * 0.5, amount * 0.01)"

Only numeric literals, whitelisted variables, + - * / // % **, comparisons,
`a if cond else b` and a handful of pure functions are allowed. Python's
`eval` is never used.
"""

from __future__ import annotations

import ast
import math
import operator
from collections.abc import Callable, Mapping
from decimal import ROUND_HALF_UP, Decimal
from functools import lru_cache
from typing import Any

from app.core.errors import ValidationFailed

_BIN_OPS: dict[type[ast.operator], Callable[[Any, Any], Any]] = {
    ast.Add: operator.add,
    ast.Sub: operator.sub,
    ast.Mult: operator.mul,
    ast.Div: operator.truediv,
    ast.FloorDiv: operator.floordiv,
    ast.Mod: operator.mod,
    ast.Pow: operator.pow,
}
_UNARY_OPS: dict[type[ast.unaryop], Callable[[Any], Any]] = {
    ast.UAdd: operator.pos,
    ast.USub: operator.neg,
    ast.Not: operator.not_,
}
_CMP_OPS: dict[type[ast.cmpop], Callable[[Any, Any], Any]] = {
    ast.Eq: operator.eq,
    ast.NotEq: operator.ne,
    ast.Lt: operator.lt,
    ast.LtE: operator.le,
    ast.Gt: operator.gt,
    ast.GtE: operator.ge,
}


def _round(x: float, ndigits: int = 0) -> float:
    q = Decimal(1).scaleb(-int(ndigits))
    return float(Decimal(str(x)).quantize(q, rounding=ROUND_HALF_UP))


_FUNCS: dict[str, Callable[..., Any]] = {
    "min": min,
    "max": max,
    "abs": abs,
    "round": _round,
    "ceil": math.ceil,
    "floor": math.floor,
}

_MAX_POW = 12


@lru_cache(maxsize=512)
def _parse(expr: str) -> ast.Expression:
    if len(expr) > 500:
        raise ValidationFailed("Formula is too long", code="formula_invalid")
    try:
        return ast.parse(expr, mode="eval")
    except SyntaxError as e:
        raise ValidationFailed(f"Formula syntax error: {e.msg}", code="formula_invalid") from e


def evaluate(expr: str, variables: Mapping[str, float | int | bool]) -> float:
    tree = _parse(expr)

    def ev(node: ast.AST) -> Any:
        match node:
            case ast.Expression(body=body):
                return ev(body)
            case ast.Constant(value=v) if isinstance(v, (int, float, bool)):
                return v
            case ast.Name(id=name):
                if name not in variables:
                    raise ValidationFailed(f"Unknown variable '{name}'", code="formula_invalid")
                return variables[name]
            case ast.BinOp(left=l, op=op, right=r):
                fn = _BIN_OPS.get(type(op))
                if fn is None:
                    raise ValidationFailed("Operator not allowed", code="formula_invalid")
                lv, rv = ev(l), ev(r)
                if isinstance(op, ast.Pow) and abs(rv) > _MAX_POW:
                    raise ValidationFailed("Exponent too large", code="formula_invalid")
                return fn(lv, rv)
            case ast.UnaryOp(op=op, operand=o):
                fn1 = _UNARY_OPS.get(type(op))
                if fn1 is None:
                    raise ValidationFailed("Operator not allowed", code="formula_invalid")
                return fn1(ev(o))
            case ast.BoolOp(op=op, values=values):
                vals = [ev(v) for v in values]
                return all(vals) if isinstance(op, ast.And) else any(vals)
            case ast.Compare(left=l, ops=ops, comparators=comps):
                left = ev(l)
                for op, c in zip(ops, comps, strict=True):
                    fn2 = _CMP_OPS.get(type(op))
                    if fn2 is None:
                        raise ValidationFailed("Comparison not allowed", code="formula_invalid")
                    right = ev(c)
                    if not fn2(left, right):
                        return False
                    left = right
                return True
            case ast.IfExp(test=t, body=b, orelse=o):
                return ev(b) if ev(t) else ev(o)
            case ast.Call(func=ast.Name(id=fname), args=args, keywords=[]) if fname in _FUNCS:
                return _FUNCS[fname](*[ev(a) for a in args])
            case _:
                raise ValidationFailed(f"Expression element not allowed: {type(node).__name__}", code="formula_invalid")

    try:
        result = ev(tree)
    except ZeroDivisionError as e:
        raise ValidationFailed("Division by zero in formula", code="formula_invalid") from e
    return float(result)


def validate(expr: str, allowed_vars: set[str]) -> None:
    """Static check used by the CMS when an editor saves a formula."""
    tree = _parse(expr)
    for node in ast.walk(tree):
        if isinstance(node, ast.Name) and node.id not in allowed_vars and node.id not in _FUNCS:
            raise ValidationFailed(f"Unknown variable '{node.id}'", code="formula_invalid")
    evaluate(expr, dict.fromkeys(allowed_vars, 1))
