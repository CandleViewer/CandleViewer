"""Shared helpers for the editor-model compilers (E35-T04).

Hostile-input bounds are enforced *before* any model is walked (security note: the compiler must
not itself be the DoS vector), and everything here is iterative so depth cannot exhaust the stack.
"""

from __future__ import annotations

from typing import Any

from pydantic import ValidationError

from candleviewer.rules.ir.canonical import IrValueError
from candleviewer.rules.ir.models import Rule
from candleviewer.rules.issues import Issue, RuleCompileError

MAX_ITEMS = 20_000  # total dict/list/scalar values in one editor document
MAX_DEPTH = 64  # nesting of the condition tree / document
MAX_GRAPH_NODES = 1_000
MAX_GRAPH_EDGES = 4_000


def check_bounds(doc: Any, what: str) -> None:
    """Reject over-sized or over-deep documents before walking them."""
    stack: list[tuple[Any, int]] = [(doc, 0)]
    count = 0
    while stack:
        cur, depth = stack.pop()
        count += 1
        if count > MAX_ITEMS or depth > MAX_DEPTH:
            raise RuleCompileError(
                [
                    Issue(
                        "$",
                        "schema_error",
                        f"The {what} is too large or too deeply nested to compile "
                        f"(limit {MAX_ITEMS} values, {MAX_DEPTH} levels).",
                        klass="syntax",
                    )
                ]
            )
        if isinstance(cur, dict):
            stack.extend((v, depth + 1) for v in cur.values())
        elif isinstance(cur, (list, tuple)):
            stack.extend((v, depth + 1) for v in cur)


def _loc(loc: tuple[Any, ...]) -> str:
    out = ""
    for part in loc:
        if isinstance(part, int):
            out += f"[{part}]"
        elif isinstance(part, str) and part.isidentifier():
            out += f".{part}" if out else part
        # discriminator tags like 'comparison' are noise for the user; skipped.
    return out or "$"


def schema_issues(exc: ValidationError) -> list[Issue]:
    return [
        Issue(_loc(e["loc"]), "schema_error", str(e["msg"]), klass="syntax")
        for e in exc.errors(include_url=False, include_input=False, include_context=False)
    ]


def value_issues(exc: IrValueError) -> list[Issue]:
    """``schema_issues`` for a value the hash cannot hold (a non-finite number in ``params``)."""
    return [Issue(_loc(exc.loc), "schema_error", exc.reason, klass="syntax")]


def build_rule(doc: dict[str, Any]) -> Rule:
    try:
        return Rule.model_validate(doc)
    except ValidationError as exc:
        raise RuleCompileError(schema_issues(exc)) from exc
