"""The message a firing carries, rendered at fire time (E40-D02 CC-1, D-17).

A firing's delivery `title` is the alert's name and its `body` this module's output: the
message template with each `{{namespace.leaf}}` replaced by the value it names, or, for an empty
template, the condition restated with its values in E36-D01 G4's verbs, past tense ("Price
65,012.5 crossed above 65,000"). Pure, synchronous and side-effect free.

The output is plain text, never markup:
- a value is substituted once and nothing is evaluated; the rendered text never carries `{{`
  or `}}` (a brace pair is split after control characters are removed), so no surface shows a
  raw placeholder (D-17);
- C0 and C1 control characters (but `\n`) and the Unicode Bidi_Control set are removed from the
  title and the body, so neither can drive a terminal, an OS notification or a mail client;
- placeholders are those `compiler.validate_template` admitted at save time; anything else, and
  any leaf with no value at fire time, renders `—`.

**No account data reaches any channel** (CC-1, D-23): the one body is written for every channel
of the firing, so the value of a metric whose registry scope is `account` or `position` renders
`—` wherever it would appear (the restatement, `{{market.<metric>}}`, `{{footprint.<metric>}}`,
`{{alert.condition_summary}}`), as does every `position.*` leaf, and a metric the registry does
not know is treated the same way (fail closed). An in-app-only body for them waits for a
position read.
"""

from __future__ import annotations

import re
from collections.abc import Callable, Iterable, Mapping
from dataclasses import dataclass
from datetime import UTC, datetime
from decimal import Decimal, InvalidOperation
from typing import Any, Final, NamedTuple

from candleviewer.rules.ir.models import (
    ArithmeticNode,
    BooleanNode,
    Comparison,
    ConditionNode,
    Literal_,
    MetricRef,
    TemporalNode,
)
from candleviewer.rules.vocabulary.registry import MetricRegistry

#: The rendered body is cut here (a template holds at most 500 characters; values widen it).
BODY_MAX: Final = 1000
#: A template is read up to here (`AlertInput.message_template`'s bound).
TEMPLATE_MAX: Final = 500
#: A single substituted text value is cut here.
VALUE_MAX: Final = 64
NO_VALUE: Final = "—"
_PLACEHOLDER = re.compile(r"\{\{(.*?)\}\}", re.DOTALL)

#: G4's verbs, past tense (the notification reads in the past tense, E36-D01 F14).
_VERB: Final[Mapping[str, str]] = {
    "gt": "was above", "gte": "was at least", "lt": "was below", "lte": "was at most",
    "eq": "was", "neq": "was not", "crosses_above": "crossed above",
    "crosses_below": "crossed below",
}  # fmt: skip
_ARITH: Final[Mapping[str, str]] = {
    "add": "plus", "sub": "minus", "mul": "times", "div": "divided by", "pct_of": "% of",
}  # fmt: skip
#: Registry scopes whose values are the owner's account data: never rendered (D-23).
ACCOUNT_SCOPES: Final = frozenset({"account", "position"})
#: Removed from every rendered text: C0 but `\n`, DEL, C1, and Unicode's Bidi_Control set.
_CONTROL = re.compile("[\x00-\x09\x0b-\x1f\x7f-\x9f\u061c\u200e\u200f\u202a-\u202e\u2066-\u2069]")
_BRACES = re.compile(r"([{}])(?=\1)")


class MetricInfo(NamedTuple):
    """What the renderer needs of a metric: its display title, G8's estimated flag and its
    registry scope (`symbol`, `position`, `account`, `global`)."""

    title: str
    estimated: bool
    scope: str


#: A metric's `MetricInfo`; None when the registry does not know the name.
TitleOf = Callable[[str], MetricInfo | None]


def default_title(_name: str) -> MetricInfo | None:
    """No registry wired: every metric is spoken by its id and its value is never shown."""
    return None


def registry_titles(registry: MetricRegistry | None) -> TitleOf:
    """The registry's display titles (G3: never the id where a title exists), G8's estimated
    flag and each metric's scope, read once; no registry is `default_title`."""
    if registry is None:
        return default_title
    infos = {
        n: MetricInfo(d.title, d.confidence == "estimated", d.scope)
        for n in registry.names()
        if (d := registry.get(n)) is not None
    }
    return infos.get


def clean_text(text: str) -> str:
    """Plain text for any surface: control and bidirectional-control characters removed."""
    return _CONTROL.sub("", text)


def inert(text: str) -> str:
    """A substituted value that can never read as a placeholder: `{{` becomes `{ {`."""
    return _BRACES.sub(r"\1 ", text)


def value_shown(name: str, title_of: TitleOf) -> bool:
    """Only a known metric of `symbol` or `global` scope has its value rendered (fail closed)."""
    info = title_of(name)
    return info is not None and info.scope not in ACCOUNT_SCOPES


@dataclass(frozen=True, slots=True)
class FiringFacts:
    """What a firing knows when it is recorded."""

    alert_id: str
    name: str
    severity: str
    symbol: str | None
    timeframe: str | None
    fired_at_ms: int
    values: Mapping[str, Any]


def fmt_value(v: Any) -> str:
    """A value as text: numbers grouped ("65,012.5"), booleans as words, None as `—`. A
    `Decimal` reaches the context as its string (`evaluator._jsonable`), so a numeric string is
    a number here."""
    if v is None:
        return NO_VALUE
    if isinstance(v, bool):
        return "true" if v else "false"
    if isinstance(v, str):
        if len(v) > _NUMBER_TEXT_MAX:  # decided on the length alone: never parsed or scanned
            return NO_VALUE if _NUMBER_START.match(v) else v[:VALUE_MAX]
        return _grouped(Decimal(v)) if _NUMBER.fullmatch(v) else v[:VALUE_MAX]
    if isinstance(v, int) and v.bit_length() > _INT_BITS_MAX:
        return NO_VALUE
    if isinstance(v, int | float | Decimal):
        try:
            d = v if isinstance(v, Decimal) else Decimal(v if isinstance(v, int) else str(v))
        except InvalidOperation:  # pragma: no cover - str() of a number always parses
            return NO_VALUE
        return _grouped(d) if d.is_finite() else NO_VALUE
    return NO_VALUE  # a structured value is not text (the detail drawer shows it)


#: A plain or exponent-form decimal ("65012.5", "1E+3", "-2.5e-4"). The exponent has at most
#: four digits; a longer one is not a value any metric produces, and the string is shown as text.
_NUMBER = re.compile(r"^-?\d+(\.\d+)?([eE][+-]?\d{1,4})?$", re.ASCII)
_NUMBER_START = re.compile(r"-?\d", re.ASCII)
#: A numeric string longer than this is no value a metric produces: it renders `—` unparsed.
_NUMBER_TEXT_MAX: Final = 2 * VALUE_MAX
#: An integer past Python's default 4,300-digit text limit renders `—` unconverted.
_INT_BITS_MAX: Final = 4300 * 10 // 3


def _grouped(d: Decimal) -> str:
    """Positional and grouped ("1E+3" -> "1,000"); a number too long for that keeps its
    scientific form rather than being cut. The form is chosen from the leading exponent and the
    digit count before any text is built: a number with either beyond `VALUE_MAX` has a positional
    form wider than `VALUE_MAX`, so it goes straight to the scientific form."""
    if not d.is_finite():
        return NO_VALUE
    if abs(d.adjusted()) > VALUE_MAX or len(d.as_tuple().digits) > VALUE_MAX:
        return f"{d:.6E}"
    text = f"{d:,f}"
    return text if len(text) <= VALUE_MAX else f"{d:.6E}"


def _duration(ms: int) -> str:
    if ms % 60_000 == 0:
        return f"{ms // 60_000} min"
    return f"{fmt_value(Decimal(ms) / 1000)} s"


def _bounded(parts: Iterable[str]) -> list[str]:
    """Each part cut at `BODY_MAX`, and no part taken once the text has passed `BODY_MAX` (at
    least two are kept, for "either ... or ..."): the rest could never be shown, so it is never
    built."""
    out: list[str] = []
    size = 0
    for part in parts:
        if size > BODY_MAX and len(out) >= 2:
            break
        out.append(part[:BODY_MAX])
        size += len(out[-1]) + 2
    return out


class _Restater:
    def __init__(self, values: Mapping[str, Any], title_of: TitleOf) -> None:
        self._values, self._title_of = values, title_of

    def title(self, metric: str) -> str:
        got = self._title_of(metric)
        if got is None:
            return metric.replace("_", " ")  # the id spoken, never a raw id with underscores
        title = got.title
        if title[1:2].islower():  # in-sentence case ("tape speed"), an acronym kept ("POC")
            title = title[:1].lower() + title[1:]
        return f"{title} (estimated)" if got.estimated else title

    def operand(self, op: Any, *, with_value: bool) -> str:
        if isinstance(op, MetricRef):
            name = self.title(op.metric)
            if not with_value:
                return name
            if not value_shown(op.metric, self._title_of):  # account data: never rendered (D-23)
                return f"{name} {NO_VALUE}"
            return f"{name} {fmt_value(self._values.get(op.metric))}"
        if isinstance(op, Literal_):
            return fmt_value(op.const)
        if isinstance(op, ArithmeticNode):
            parts = _bounded(self.operand(o, with_value=False) for o in op.operands)
            if op.op in _ARITH and len(parts) == 2:
                return f"{parts[0]} {_ARITH[op.op]} {parts[1]}"
            return f"{op.op.replace('_', ' ')} of {', '.join(parts)}"
        return NO_VALUE

    def comparison(self, c: Comparison) -> str:
        left = self.operand(c.left, with_value=c.op not in ("is_true", "is_false"))
        right = "" if c.right is None else self.operand(c.right, with_value=False)
        right2 = "" if c.right2 is None else self.operand(c.right2, with_value=False)
        if c.op in _VERB:
            return f"{left} {_VERB[c.op]} {right}".rstrip()
        if c.op == "between":
            return f"{left} was between {right} and {right2}"
        if c.op == "outside":
            return f"{left} was outside {right} to {right2}"
        if c.op in ("in_set", "not_in_set"):
            word = "one" if c.op == "in_set" else "none"
            return f"{left} was {word} of {', '.join(_bounded(c.set_values))}"
        if c.op == "changed":
            return f"{left} changed"
        return f"{left} was {'true' if c.op == 'is_true' else 'false'}"

    def node(self, n: ConditionNode) -> str:
        if isinstance(n, Comparison):
            return self.comparison(n)
        if isinstance(n, BooleanNode):
            parts = _bounded(self.node(ch) for ch in n.children)
            if n.op == "all_of":
                return " and ".join(parts)
            if n.op == "any_of":
                if len(n.children) == 2:
                    return f"either {parts[0]} or {parts[1]}"
                return f"any of: {', '.join(parts)}"
            lead = "none" if n.op == "none_of" else str(n.n or 1)
            return f"{lead} of: {', '.join(parts)}"
        if isinstance(n, TemporalNode):
            inner, w = self.node(n.child)[:BODY_MAX], _duration(n.window_ms)
            if n.op == "occurred_within":
                return f"{inner} within {w}"
            if n.op == "count_within":
                return f"{inner} at least {n.min_count} times within {w}"
            return f"{inner} for at least {w}"
        return NO_VALUE


def restate(
    condition: ConditionNode, values: Mapping[str, Any], title_of: TitleOf = default_title
) -> str:
    """The condition in words with the values it fired on (CC-1's empty-template body)."""
    text = inert(clean_text(_Restater(values, title_of).node(condition)))
    return (text[:1].upper() + text[1:])[:BODY_MAX]


def _iso(ms: int) -> str:
    return datetime.fromtimestamp(ms / 1000, tz=UTC).strftime("%Y-%m-%dT%H:%M:%SZ")


def _leaf(name: str, facts: FiringFacts, summary: Callable[[], str], title_of: TitleOf) -> str:
    ns, _, leaf = name.partition(".")
    if ns == "alert":
        alert: dict[str, Callable[[], str]] = {
            "name": lambda: facts.name, "id": lambda: facts.alert_id,
            "severity": lambda: facts.severity,
            "triggered_at": lambda: _iso(facts.fired_at_ms), "condition_summary": summary,
        }  # fmt: skip
        return alert[leaf]() if leaf in alert else NO_VALUE
    if ns == "market" and leaf == "symbol":
        return facts.symbol or NO_VALUE
    if ns == "footprint" and leaf == "timeframe":
        return facts.timeframe or NO_VALUE
    if ns in ("market", "footprint") and value_shown(leaf, title_of):
        return fmt_value(facts.values.get(leaf))
    # position.* (no position read yet), an account- or position-scope metric, an unknown one,
    # and anything not admitted at save
    return NO_VALUE


def render_body(
    template: str,
    condition: ConditionNode,
    facts: FiringFacts,
    title_of: TitleOf = default_title,
) -> str:
    """CC-1: the template rendered with this firing's values; an empty one restates the
    condition with them."""
    summary = _Once(lambda: restate(condition, facts.values, title_of))
    if not template.strip():
        return summary()
    out = _PLACEHOLDER.sub(
        lambda m: _leaf(m.group(1).strip(" \t"), facts, summary, title_of),
        template[:TEMPLATE_MAX],
    )
    # cleaned first, then made inert: a removed control character can no longer join a brace pair
    return inert(clean_text(out))[:BODY_MAX]


class _Once:
    """The restatement, built at most once and only when a template asks for it."""

    def __init__(self, fn: Callable[[], str]) -> None:
        self._fn: Callable[[], str] = fn
        self._v: str | None = None

    def __call__(self) -> str:
        if self._v is None:
            self._v = self._fn()
        return self._v


__all__ = [
    "ACCOUNT_SCOPES",
    "BODY_MAX",
    "NO_VALUE",
    "FiringFacts",
    "MetricInfo",
    "TitleOf",
    "clean_text",
    "default_title",
    "fmt_value",
    "inert",
    "registry_titles",
    "render_body",
    "restate",
    "value_shown",
]
