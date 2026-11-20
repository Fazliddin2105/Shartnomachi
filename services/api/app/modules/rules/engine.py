"""Deterministic legal rule engine (pure, no I/O).

A rule is JSON authored by legal experts in the CMS:

    {
      "code": "LABOR_PROBATION_MAX",
      "scope": "answers",                       # answers | clause
      "severity": "red",                        # red | yellow | blue
      "when": {"all": [
          {"field": "answers.probation_months", "op": "gt", "value": 3}
      ]},
      "message": "Sinov muddati {answers.probation_months} oy — qonuniy chegaradan oshgan",
      "law_ref": "Mehnat kodeksi",
      "fix_suggestion": "Sinov muddatini 3 oydan oshirmang"
    }

Conditions compose with `all` / `any` / `not`. Leaf operators are listed in
`_OPS`. `{"field": ...}` as a value compares two fields. `expr` evaluates a
sandboxed arithmetic expression over flattened numeric fields
(`answers.price` -> `answers__price`).

The engine is the single source of truth for verdicts; AI is only allowed to
*explain* findings (spec §9: "qoida ustun").
"""

from __future__ import annotations

import re
from collections.abc import Callable, Iterable, Mapping
from dataclasses import dataclass, field
from datetime import date
from enum import StrEnum
from functools import lru_cache
from typing import Any

from app.core import safe_expr


class Severity(StrEnum):
    RED = "red"  # qonunga zid — generatsiya bloklanadi / tasdiq talab qilinadi
    YELLOW = "yellow"  # xavfli / nomuvofiq
    BLUE = "blue"  # maslahat

    @property
    def weight(self) -> int:
        return {"red": 3, "yellow": 2, "blue": 1}[self.value]


class Scope(StrEnum):
    ANSWERS = "answers"
    CLAUSE = "clause"


class RuleError(ValueError):
    pass


_MISSING = object()


def get_path(ctx: Mapping[str, Any], path: str) -> Any:
    cur: Any = ctx
    for part in path.split("."):
        if isinstance(cur, Mapping) and part in cur:
            cur = cur[part]
        elif isinstance(cur, list) and part.isdigit() and int(part) < len(cur):
            cur = cur[int(part)]
        else:
            return _MISSING
    return cur


def _num(x: Any) -> float | None:
    if isinstance(x, bool):
        return None
    if isinstance(x, (int, float)):
        return float(x)
    if isinstance(x, str):
        try:
            return float(x.replace(" ", "").replace(",", "."))
        except ValueError:
            return None
    return None


@lru_cache(maxsize=1024)
def _rx(pattern: str) -> re.Pattern[str]:
    return re.compile(pattern, re.IGNORECASE | re.UNICODE)


def _is_empty(v: Any) -> bool:
    return v is _MISSING or v is None or (isinstance(v, (str, list, dict)) and len(v) == 0)


def _date(x: Any) -> date | None:
    if isinstance(x, date):
        return x
    if isinstance(x, str) and len(x) == 10 and x[4] == "-":
        try:
            return date.fromisoformat(x)
        except ValueError:
            return None
    return None


def _cmp(fn: Callable[[Any, Any], bool]) -> Callable[[Any, Any, dict[str, Any]], bool]:
    """Numeric comparison; ISO dates (YYYY-MM-DD) are compared as dates."""

    def op(actual: Any, expected: Any, _: dict[str, Any]) -> bool:
        da, db_ = _date(actual), _date(expected)
        if da is not None and db_ is not None:
            return fn(da, db_)
        a, b = _num(actual), _num(expected)
        return a is not None and b is not None and fn(a, b)

    return op


def _numbers_in_text(text: Any, cond: dict[str, Any]) -> list[float]:
    if not isinstance(text, str):
        return []
    pattern = cond.get("pattern", r"(\d+(?:[.,]\d+)?)")
    out = []
    for m in _rx(pattern).finditer(text):
        n = _num(m.group(1) if m.groups() else m.group(0))
        if n is not None:
            out.append(n)
    return out


_OPS: dict[str, Callable[[Any, Any, dict[str, Any]], bool]] = {
    "eq": lambda a, b, _: a is not _MISSING and (a == b or (_num(a) is not None and _num(a) == _num(b))),
    "ne": lambda a, b, _: not (a is not _MISSING and (a == b or (_num(a) is not None and _num(a) == _num(b)))),
    "gt": _cmp(lambda a, b: a > b),
    "gte": _cmp(lambda a, b: a >= b),
    "lt": _cmp(lambda a, b: a < b),
    "lte": _cmp(lambda a, b: a <= b),
    "between": lambda a, b, _: _num(a) is not None and float(b[0]) <= _num(a) <= float(b[1]),  # type: ignore[operator]
    "in": lambda a, b, _: a is not _MISSING and a in b,
    "not_in": lambda a, b, _: a is _MISSING or a not in b,
    "exists": lambda a, b, _: (not _is_empty(a)) == bool(b if b is not None else True),
    "missing": lambda a, b, _: _is_empty(a),
    "true": lambda a, b, _: a is True,
    "false": lambda a, b, _: a is False or a is _MISSING or a is None,
    "contains": lambda a, b, _: (
        (isinstance(a, str) and str(b).lower() in a.lower()) or (isinstance(a, list) and b in a)
    ),
    "not_contains": lambda a, b, _: (
        not ((isinstance(a, str) and str(b).lower() in a.lower()) or (isinstance(a, list) and b in a))
    ),
    "regex": lambda a, b, _: isinstance(a, str) and bool(_rx(b).search(a)),
    "not_regex": lambda a, b, _: not (isinstance(a, str) and bool(_rx(b).search(a))),
    "len_gt": lambda a, b, _: isinstance(a, (str, list)) and len(a) > int(b),
    "len_lt": lambda a, b, _: isinstance(a, (str, list)) and len(a) < int(b),
    "number_in_text_gt": lambda a, b, c: any(n > float(b) for n in _numbers_in_text(a, c)),
    "number_in_text_lt": lambda a, b, c: any(n < float(b) for n in _numbers_in_text(a, c)),
}

OPERATORS = frozenset(_OPS) | {"expr"}


def _flatten_numeric(ctx: Mapping[str, Any], prefix: str = "") -> dict[str, float | bool]:
    out: dict[str, float | bool] = {}
    for k, v in ctx.items():
        key = f"{prefix}__{k}" if prefix else str(k)
        if isinstance(v, Mapping):
            out.update(_flatten_numeric(v, key))
        elif isinstance(v, bool):
            out[key] = v
        else:
            n = _num(v)
            if n is not None:
                out[key] = n
    return out


@dataclass(slots=True)
class _Trace:
    fields: list[str] = field(default_factory=list)


def evaluate(cond: Mapping[str, Any], ctx: Mapping[str, Any], trace: _Trace | None = None) -> bool:
    if "all" in cond:
        return all(evaluate(c, ctx, trace) for c in cond["all"])
    if "any" in cond:
        return any(evaluate(c, ctx, trace) for c in cond["any"])
    if "not" in cond:
        return not evaluate(cond["not"], ctx, None)
    op = cond.get("op")
    if op == "expr":
        variables = _flatten_numeric(ctx)
        try:
            return bool(safe_expr.evaluate(cond["value"], variables))
        except Exception:
            return False
    if op not in _OPS:
        raise RuleError(f"Unknown operator: {op!r}")
    path = cond.get("field")
    if not isinstance(path, str):
        raise RuleError("Leaf condition requires 'field'")
    actual = get_path(ctx, path)
    expected = cond.get("value")
    if isinstance(expected, Mapping) and "field" in expected:
        expected = get_path(ctx, expected["field"])
        if expected is _MISSING:
            return False
    result = _OPS[op](actual, expected, dict(cond))
    if result and trace is not None:
        trace.fields.append(path)
    return result


def validate_condition(cond: Any, depth: int = 0) -> None:
    """Structural validation used by the CMS before a rule is saved."""
    if depth > 10:
        raise RuleError("Condition nesting is too deep")
    if not isinstance(cond, Mapping):
        raise RuleError("Condition must be an object")
    for key in ("all", "any"):
        if key in cond:
            if not isinstance(cond[key], list) or not cond[key]:
                raise RuleError(f"'{key}' must be a non-empty list")
            for c in cond[key]:
                validate_condition(c, depth + 1)
            return
    if "not" in cond:
        validate_condition(cond["not"], depth + 1)
        return
    op = cond.get("op")
    if op not in OPERATORS:
        raise RuleError(f"Unknown operator: {op!r}")
    if op == "expr":
        safe_expr._parse(str(cond.get("value", "")))
        return
    if not isinstance(cond.get("field"), str):
        raise RuleError("Leaf condition requires 'field'")
    if op in ("regex", "not_regex"):
        try:
            _rx(str(cond.get("value")))
        except re.error as e:
            raise RuleError(f"Invalid regex: {e}") from e
    if "pattern" in cond:
        try:
            _rx(str(cond["pattern"]))
        except re.error as e:
            raise RuleError(f"Invalid pattern: {e}") from e
    if op == "between" and not (isinstance(cond.get("value"), list) and len(cond["value"]) == 2):
        raise RuleError("'between' needs [min, max]")


_PLACEHOLDER = re.compile(r"\{([a-zA-Z0-9_.]+)\}")


def render_message(template: str, ctx: Mapping[str, Any]) -> str:
    def sub(m: re.Match[str]) -> str:
        v = get_path(ctx, m.group(1))
        return "—" if v is _MISSING or v is None else str(v)

    return _PLACEHOLDER.sub(sub, template or "")


@dataclass(frozen=True, slots=True)
class Rule:
    code: str
    severity: Severity
    when: Mapping[str, Any]
    message: str
    scope: Scope = Scope.ANSWERS
    law_ref: str | None = None
    lex_url: str | None = None
    fix_suggestion: str | None = None
    category: str | None = None  # restrict clause rules to a clause category
    version: int = 1
    autofix: Mapping[str, Any] | None = None  # {"field": "answers.x", "value": 3} -> one-click fix in UI

    @classmethod
    def from_json(cls, d: Mapping[str, Any]) -> Rule:
        validate_condition(d["when"])
        return cls(
            code=d["code"],
            severity=Severity(d["severity"]),
            when=d["when"],
            message=d["message"],
            scope=Scope(d.get("scope", "answers")),
            law_ref=d.get("law_ref"),
            lex_url=d.get("lex_url"),
            fix_suggestion=d.get("fix_suggestion"),
            category=d.get("category"),
            version=int(d.get("version", 1)),
            autofix=d.get("autofix"),
        )


@dataclass(frozen=True, slots=True)
class Finding:
    rule_code: str
    severity: Severity
    message: str
    law_ref: str | None
    lex_url: str | None
    fix_suggestion: str | None
    fields: tuple[str, ...] = ()
    clause_index: int | None = None
    rule_version: int = 1
    autofix: Mapping[str, Any] | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "rule_code": self.rule_code,
            "severity": self.severity.value,
            "message": self.message,
            "law_ref": self.law_ref,
            "lex_url": self.lex_url,
            "fix_suggestion": self.fix_suggestion,
            "fields": list(self.fields),
            "clause_index": self.clause_index,
            "rule_version": self.rule_version,
            "autofix": dict(self.autofix) if self.autofix else None,
        }


def _finding(rule: Rule, ctx: Mapping[str, Any], trace: _Trace, clause_index: int | None = None) -> Finding:
    return Finding(
        rule_code=rule.code,
        severity=rule.severity,
        message=render_message(rule.message, ctx),
        law_ref=rule.law_ref,
        lex_url=rule.lex_url,
        fix_suggestion=render_message(rule.fix_suggestion, ctx) if rule.fix_suggestion else None,
        fields=tuple(dict.fromkeys(trace.fields)),
        clause_index=clause_index,
        rule_version=rule.version,
        autofix=rule.autofix,
    )


def run_answers(rules: Iterable[Rule], ctx: Mapping[str, Any]) -> list[Finding]:
    out: list[Finding] = []
    for rule in rules:
        if rule.scope != Scope.ANSWERS:
            continue
        trace = _Trace()
        if evaluate(rule.when, ctx, trace):
            out.append(_finding(rule, ctx, trace))
    return sort_findings(out)


def run_clauses(rules: Iterable[Rule], clauses: list[Mapping[str, Any]], base_ctx: Mapping[str, Any]) -> list[Finding]:
    """Clause rules see `{"clause": {"text", "category", "index"}, **base_ctx}`."""
    out: list[Finding] = []
    clause_rules = [r for r in rules if r.scope == Scope.CLAUSE]
    for clause in clauses:
        ctx = {**base_ctx, "clause": clause}
        for rule in clause_rules:
            if rule.category and rule.category != clause.get("category"):
                continue
            trace = _Trace()
            if evaluate(rule.when, ctx, trace):
                out.append(_finding(rule, ctx, trace, clause_index=int(clause.get("index", 0))))
    return sort_findings(out)


def sort_findings(findings: list[Finding]) -> list[Finding]:
    return sorted(findings, key=lambda f: (-f.severity.weight, f.clause_index or 0, f.rule_code))


def summarize(findings: Iterable[Finding]) -> dict[str, Any]:
    counts = {s.value: 0 for s in Severity}
    for f in findings:
        counts[f.severity.value] += 1
    return {"counts": counts, "blocking": counts["red"] > 0}


def run_tests(rule: Rule, cases: Iterable[Mapping[str, Any]]) -> list[dict[str, Any]]:
    """Expert-authored regression tests: [{"name", "context", "expect": bool}]."""
    results = []
    for case in cases:
        ctx = case.get("context", {})
        if rule.scope == Scope.CLAUSE:
            got = bool(run_clauses([rule], [ctx.get("clause", {})], ctx))
        else:
            got = evaluate(rule.when, ctx)
        results.append(
            {
                "name": case.get("name"),
                "expected": bool(case.get("expect")),
                "got": got,
                "passed": got == bool(case.get("expect")),
            }
        )
    return results
