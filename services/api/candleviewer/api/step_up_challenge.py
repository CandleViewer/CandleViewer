"""What a step-up challenge restates, and the fingerprint of the request it refuses (#2304; PR
#2290 ruling, rule 4).

Restates: `Problem.action_summary` is the route's fixed-template text over the validated request,
naming each account by its label, `environment` and `exchange_uid` with every label escaped so
its quotes bound it; `Problem.target` is the typed-confirmation text. Both come from server-side
records, never from the client.

Fingerprints: `request_fingerprint` is the hex SHA-256 of the method, a line feed, the raw
request target (path and query string as received: no percent-decoding, no trailing-slash or
parameter-order normalisation), a line feed, and the RFC 8785 (JCS) serialisation of the body as
the operation validated it (empty when the operation takes no body). Headers, `Idempotency-Key`
included, are not part of it. It names one request exactly, so the grant of a no-grace class
(`auth.step_up.NO_GRACE_ACTION_CLASSES`) can be bound to the challenged request. Pure functions,
no I/O; the caller passes the one object its route validated, so the summary, the fingerprint and
the executed action cannot disagree.
"""

from __future__ import annotations

import hashlib
import math
import re
from collections.abc import Iterable
from dataclasses import dataclass

from starlette.requests import Request

from candleviewer.accounts.models import ExchangeEnv

_ENVIRONMENTS = frozenset(env.value for env in ExchangeEnv)
_EXCHANGE_UID = re.compile(r"[0-9]{1,20}")


@dataclass(frozen=True)
class ChallengeText:
    """What a challenge restates: the route's fixed-template summary of the validated request,
    and the text a typed confirmation must equal (None when the action asks for none)."""

    action_summary: str
    target: str | None = None


def quote_label(label: str) -> str:
    """A label quoted for `action_summary`: `'` and `\\` get a backslash, and every character
    outside printable ASCII is written `\\u{XXXX}` (upper-case hex, at least four digits)."""
    out = []
    for ch in label:
        if ch in "'\\":
            out.append("\\" + ch)
        elif " " <= ch <= "~":
            out.append(ch)
        else:
            out.append(f"\\u{{{ord(ch):04X}}}")
    return "'" + "".join(out) + "'"


def account_reference(label: str, environment: str, exchange_uid: str) -> str:
    """An account named beyond its label, which can be renamed and need not be unique: its
    `environment` and `exchange_uid` never change after registration."""
    if environment not in _ENVIRONMENTS or not _EXCHANGE_UID.fullmatch(exchange_uid):
        raise ValueError("an account is named by its registered environment and UID")
    return f"{quote_label(label)} ({environment}, UID {exchange_uid})"


def typed_target(label: str, identifier: str, others: Iterable[str]) -> str:
    """`Problem.target`: the label only when it is printable ASCII and no other object of its
    kind the caller can see has it (compared case-insensitively); else the identifier."""
    folded = label.casefold()
    unique = all(other.casefold() != folded for other in others)
    return label if unique and label.isascii() and label.isprintable() else identifier


#: ECMAScript Number.prototype.toString uses plain digits for exponents -6 < n <= 21.
_ES_PLAIN_LOW, _ES_PLAIN_HIGH = -6, 21
#: An IEEE-754 double holds every integer up to 2**53 exactly; beyond it a JSON integer is not
#: I-JSON (RFC 7493 §2.2), so two different requests could share one fingerprint: refused.
_EXACT_INT = 2**53
_SHORT_ESCAPES = {
    '"': '\\"',
    "\\": "\\\\",
    "\b": "\\b",
    "\t": "\\t",
    "\n": "\\n",
    "\f": "\\f",
    "\r": "\\r",
}


def _es_number(value: float) -> str:
    """RFC 8785 §3.2.2.3: the ECMAScript string of an IEEE-754 double."""
    if not math.isfinite(value):
        raise ValueError("RFC 8785: NaN and Infinity have no JSON form")
    if value == 0:
        return "0"  # also -0
    # `repr` is the shortest round-tripping decimal, as ECMAScript requires.
    mantissa, _, exp = repr(abs(value)).partition("e")
    whole, _, frac = mantissa.partition(".")
    stripped = (whole + frac).lstrip("0")
    digits = stripped.rstrip("0")
    # value = digits x 10**(n - k): the ECMAScript k (digit count) and n (point position).
    k = len(digits)
    n = int(exp or 0) - len(frac) + len(stripped)
    sign = "-" if value < 0 else ""
    if k <= n <= _ES_PLAIN_HIGH:
        return sign + digits + "0" * (n - k)
    if 0 < n <= _ES_PLAIN_HIGH:
        return sign + digits[:n] + "." + digits[n:]
    if _ES_PLAIN_LOW < n <= 0:
        return sign + "0." + "0" * -n + digits
    head = digits[0] + ("." + digits[1:] if k > 1 else "")
    e = n - 1
    return f"{sign}{head}e{'+' if e >= 0 else '-'}{abs(e)}"


def _es_string(text: str) -> str:
    """RFC 8785 §3.2.2.2: JSON.stringify's string form; a lone surrogate is not I-JSON."""
    out = ['"']
    for ch in text:
        code = ord(ch)
        if 0xD800 <= code <= 0xDFFF:
            raise ValueError("RFC 8785: a lone surrogate is not I-JSON")
        out.append(_SHORT_ESCAPES.get(ch) or (f"\\u{code:04x}" if code < 0x20 else ch))
    out.append('"')
    return "".join(out)


def _jcs(value: object) -> str:
    if value is None:
        return "null"
    if isinstance(value, bool):
        return "true" if value else "false"
    if isinstance(value, int):
        if abs(value) > _EXACT_INT:
            raise ValueError("RFC 8785: an integer beyond 2**53 is not I-JSON")
        return str(value)
    if isinstance(value, float):
        return _es_number(value)
    if isinstance(value, str):
        return _es_string(value)
    if isinstance(value, list | tuple):
        return "[" + ",".join(_jcs(v) for v in value) + "]"
    if isinstance(value, dict):
        if not all(isinstance(k, str) for k in value):
            raise TypeError("RFC 8785: object member names are strings")
        # Members sort by their UTF-16 code units (§3.2.3), not by code points.
        keys = sorted(value, key=lambda k: k.encode("utf-16-be", "surrogatepass"))
        return "{" + ",".join(f"{_es_string(k)}:{_jcs(value[k])}" for k in keys) + "}"
    raise TypeError(f"RFC 8785: {type(value).__name__} is not a JSON value")


def canonical_json(value: object) -> bytes:
    """The RFC 8785 (JCS) UTF-8 serialisation of a parsed JSON value."""
    return _jcs(value).encode("utf-8")


def raw_request_target(request: Request) -> bytes:
    """The path and query string as received (ASGI `raw_path`, falling back to `path` for a
    server that omits that optional key, plus `query_string`)."""
    scope = request.scope
    raw = scope.get("raw_path")
    path = raw if isinstance(raw, bytes) else str(scope["path"]).encode("utf-8")
    query = scope.get("query_string") or b""
    return path + b"?" + query if query else path


def request_fingerprint(method: str, target: bytes, body: object | None) -> str:
    """Hex SHA-256 of `method LF target LF JCS(body)`; `body=None` is an empty body."""
    canonical = b"" if body is None else canonical_json(body)
    return hashlib.sha256(b"\n".join((method.encode("ascii"), target, canonical))).hexdigest()


__all__ = [
    "ChallengeText",
    "account_reference",
    "canonical_json",
    "quote_label",
    "raw_request_target",
    "request_fingerprint",
    "typed_target",
]
