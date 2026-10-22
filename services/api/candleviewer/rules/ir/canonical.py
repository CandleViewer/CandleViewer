"""Canonical serialisation and content hash for the rule IR (ADR-0026, E35-T01).

Strategy 2 of the E35-K01 spike: JCS-style JSON where every number is a canonical decimal string,
sha256 over UTF-8 bytes. Computed server-side only, before persistence (never from a jsonb
round-trip). Any change to this algorithm changes every hash: bump ``IR_HASH_VERSION`` and ship an
upcaster. A float (only an untyped ``params`` holds one) hashes as ``Decimal(float.__repr__(x))``;
a value with no canonical form is refused with ``IrValueError`` (``422 rule_ir_invalid``, not 500):
a non-finite number, or text holding a lone surrogate (it has no UTF-8 form, so no hash holds it).
"""

from __future__ import annotations

import hashlib
import json
from decimal import Decimal
from typing import Any
from uuid import UUID

from candleviewer.rules.errors import RulesError
from candleviewer.rules.ir.models import Rule

IR_HASH_VERSION = 1

# Presentation fields (ADR-0026 §4) plus persistence metadata that changes on every save and so
# must not mint a new content hash. Stripped ONLY from the top-level Rule document: free-form
# ``params`` dicts (Action/MetricRef) are semantic and must never lose keys.
PRESENTATION_KEYS = frozenset({"graph_layout", "editor"})
METADATA_KEYS = frozenset({"created_by", "created_at", "updated_at"})
_EXCLUDED = PRESENTATION_KEYS | METADATA_KEYS
#: JSON's ``"\ud800"`` escape decodes to a lone UTF-16 surrogate, which UTF-8 cannot encode.
_UNPAIRED = "Text holds an unpaired surrogate code point"


class IrValueError(RulesError, ValueError):
    """A value the canonical form cannot hold: a non-finite number, text holding a lone surrogate,
    or (``IrTypeError``) a type with no JSON form. ``loc`` is its field path, e.g.
    ``("actions", 0, "params", "weight")``, built step by step while the error unwinds (never on
    the success path); a refused key ends it with the code point escaped (``\\ud800``), so it
    prints as UTF-8. ``args`` is ``(loc, reason)``, so the error pickles and copies."""

    def __init__(self, loc: tuple[str | int, ...], reason: str) -> None:
        super().__init__(loc, reason)
        self.loc = loc
        self.reason = reason

    def at(self, step: str | int) -> None:
        """Prepend one path step (called by ``_normalise`` on the way out)."""
        self.loc = (step, *self.loc)
        self.args = (self.loc, self.reason)

    def __str__(self) -> str:
        return f"{self.reason} at /{'/'.join(map(str, self.loc))}"


class IrTypeError(IrValueError, TypeError):
    """A Python type with no canonical form: only code builds one, never JSON."""


def parse_ir_json(text: str) -> Rule:
    """Parse IR JSON text into a ``Rule`` without a float round-trip (numbers become Decimal)."""
    raw = json.loads(text, parse_float=Decimal)
    return Rule.model_validate(raw)


def dec_str(d: Decimal) -> str:
    """Plain notation, no exponent, no trailing fractional zeros, no ``+``, ``-0`` -> ``0``."""
    if d == 0:
        return "0"
    return format(d.normalize(), "f")


def _strip(node: Any) -> Any:
    if isinstance(node, dict):
        return {k: v for k, v in node.items() if k not in _EXCLUDED}
    return node


# Free-form payloads: never renumbered (their values are data, not node references).
_OPAQUE_KEYS = frozenset({"params", "const"})


def _renumber(doc: Any) -> Any:
    """Rewrite ``node_id``/``ref`` in DFS first-visit order (hash view only, ADR-0026 §3)."""
    mapping: dict[str, str] = {}

    def visit(n: Any) -> None:
        if isinstance(n, dict):
            nid = n.get("node_id")
            if isinstance(nid, str) and nid not in mapping:
                mapping[nid] = f"n{len(mapping) + 1}"
            for k in sorted(n):
                if k not in _OPAQUE_KEYS:
                    visit(n[k])
        elif isinstance(n, (list, tuple)):
            for v in n:
                visit(v)

    def rewrite(n: Any) -> Any:
        if isinstance(n, dict):
            return {
                k: (
                    v
                    if k in _OPAQUE_KEYS
                    else (
                        mapping.get(v, v)
                        if k in ("node_id", "ref") and isinstance(v, str)
                        else rewrite(v)
                    )
                )
                for k, v in n.items()
            }
        if isinstance(n, (list, tuple)):
            return [rewrite(v) for v in n]
        return n

    visit(doc)
    return rewrite(doc)


def _unpaired(s: str) -> bool:
    """``s`` holds a lone surrogate (no UTF-8 form). Callers skip ASCII text first: ``isascii()``
    is O(1) and true for most of the IR."""
    try:
        s.encode()
    except UnicodeEncodeError:
        return True
    return False


def _normalise(o: Any) -> Any:
    if isinstance(o, str):
        if not o.isascii() and _unpaired(o):
            raise IrValueError((), _UNPAIRED)
        return o
    if isinstance(o, bool) or o is None:
        return o
    if isinstance(o, float):  # an untyped place (Action.params): its shortest exact decimal
        o = Decimal(float.__repr__(o))  # float's own repr, whatever a subclass prints
    if isinstance(o, int):
        return dec_str(Decimal(o))
    if isinstance(o, Decimal):
        if not o.is_finite():  # NaN / Infinity: Python's json reads them; no hash holds them
            raise IrValueError((), "Input should be a finite number")
        return dec_str(o)
    if isinstance(o, UUID):
        return str(o)
    if isinstance(o, dict):
        out: dict[Any, Any] = {}
        for k, v in o.items():
            if isinstance(k, str) and not k.isascii() and _unpaired(k):
                # a refused key is named escaped, so the path prints as UTF-8
                raise IrValueError((k.encode(errors="backslashreplace").decode(),), _UNPAIRED)
            try:
                out[k] = _normalise(v)
            except IrValueError as exc:  # the path is built on failure only
                exc.at(k)
                raise
        return out
    if isinstance(o, (list, tuple)):
        items: list[Any] = []
        for v in o:
            try:
                items.append(_normalise(v))
            except IrValueError as exc:
                exc.at(len(items))  # the failing element's index
                raise
        return items
    raise IrTypeError((), f"unsupported type in IR: {type(o).__name__}")


def _as_rule(ir: Rule | dict[str, Any]) -> Rule:
    return ir if isinstance(ir, Rule) else Rule.model_validate(ir)


def _utf8(text: str) -> bytes:
    """``text`` as UTF-8: ``_normalise`` refuses a lone surrogate first, this is the backstop."""
    try:
        return text.encode()
    except UnicodeEncodeError as exc:
        raise IrValueError((), _UNPAIRED) from exc


def canonicalize(ir: Rule | dict[str, Any]) -> bytes:
    """Canonical UTF-8 bytes of the hashed view of ``ir`` (idempotent, order-insensitive)."""
    dumped = _as_rule(ir).model_dump(mode="python")
    view = _normalise(_renumber(_strip(dumped)))
    return _utf8(json.dumps(view, sort_keys=True, separators=(",", ":"), ensure_ascii=False))


def ir_hash(ir: Rule | dict[str, Any]) -> str:
    """sha256 hex of ``canonicalize(ir)``."""
    return hashlib.sha256(canonicalize(ir)).hexdigest()


#: The condition half of the IR (E40-T02): what an alert and a rule can share.
CONDITION_KEYS = ("ir_version", "trigger", "conditions", "variables")


def condition_hash(dumped: dict[str, Any]) -> str:
    """sha256 hex of the canonical *condition* view of a dumped rule or alert IR.

    Same pipeline as ``canonicalize`` (renumber, normalise, sorted compact JSON) over only
    ``CONDITION_KEYS`` (empty ``variables`` dropped), so an identical condition authored in a
    rule and in an alert hashes identically - E40-T03 keys shared subscriptions on it.
    """
    view = {k: dumped[k] for k in CONDITION_KEYS if dumped.get(k) not in (None, {})}
    body = json.dumps(
        _normalise(_renumber(view)), sort_keys=True, separators=(",", ":"), ensure_ascii=False
    )
    return hashlib.sha256(_utf8(body)).hexdigest()
