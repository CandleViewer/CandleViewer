"""The profile writes' request edge (E28-T02 #906, slice D2-3; 22's profile write operations).

The write handlers call these in their admission order (#906), and each refuses with a typed error
the handler answers: the `Idempotency-Key` (`Refused`, 422), the raw body under its operation's
cap (`BodyTooLarge`, 413) before anything parses it, its JSON (`Refused`), the generated model's
failures as `ProfileRejected` entries, the `name` code-point check, and `If-Match`
(`IfMatchMissing`, 428; `IfMatchRefused`, 412). `refused` counts an answer's members.

Nothing a client sent is echoed (C-12.6): an unknown member is named by its parent, never by its
key (#4147 R1S-02), no entry carries an input, and each model message passes `redact_text`. B1's
and B2's entries hold only constants and validated figures, so they pass as they are:
`redact_structure`'s TOTP rule would hide a six-digit limit.
"""

from __future__ import annotations

import json
import re
import unicodedata
from collections.abc import Sequence
from typing import Final, NoReturn

from fastapi import Request
from pydantic import ValidationError

from candleviewer.accounts.profile_input import ProfileBody, ProfileFieldError, field_path
from candleviewer.api.idempotency import idempotency_key
from candleviewer.observability.redaction import redact_text
from candleviewer.ws.limits import json_depth_exceeds

#: 22: a profile body over 64 KiB is `413 payload_too_large`. The largest one the schema admits,
#: two 500-entry symbol lists of at most 21 characters each, takes about 25 KB.
MAX_PROFILE_BODY_BYTES: Final = 65_536
#: 22: a binding body over 1 KiB is `413 payload_too_large`; it holds one id.
MAX_BINDING_BODY_BYTES: Final = 1_024
#: A profile body nests 3 deep (an object in `take_profit_ladder`), checked before it is decoded.
MAX_JSON_DEPTH: Final = 8
#: The generated model's entries answered (B1 Sec.3); B1's own follow them, never cut.
MODEL_ERRORS_SHOWN: Final = 20
_LENGTH: Final = re.compile(r"[0-9]{1,19}")  # a usable `Content-Length`, as `api/drawings.py`
_TAG: Final = re.compile(r'W/"([0-9a-f-]{36}(?::default)?):([1-9][0-9]{0,18})"')
#: D2-c R1S-06 (the coordinator's note of 2026-10-23 12:28Z): Unicode's control and format
#: categories, read per code point, since `re` has no Unicode property classes.
_HIDDEN: Final = frozenset({"Cc", "Cf"})
_HIDDEN_IN_NAME: Final = ProfileFieldError(
    "name", "not_allowed", "name takes no control or format character (Unicode Cc or Cf)."
)
_NOT_A_KEY: Final = ProfileFieldError(
    "Idempotency-Key", "uuid_parsing", "Idempotency-Key must be a UUID."
)
_NOT_JSON: Final = "The body is not UTF-8 JSON."
#: pydantic names the class it expected, which `redact_text` would read as a key (R1C-01).
_NOT_AN_OBJECT: Final = "Input should be an object."
_TOO_DEEP: Final = f"JSON nesting is deeper than {MAX_JSON_DEPTH} levels."


class BodyTooLarge(Exception):
    """413 `payload_too_large`: the body is over `cap` bytes."""

    def __init__(self, cap: int) -> None:
        super().__init__(f"The request body exceeds {cap} bytes.")
        self.cap = cap


class Refused(Exception):
    """422 `validation_failed`: the `Problem.errors[]` entries and the `detail` counting them."""

    def __init__(self, errors: Sequence[ProfileFieldError], detail: str) -> None:
        super().__init__(detail)
        self.errors, self.detail = tuple(errors), detail


class IfMatchMissing(Exception):
    """428 `precondition_required`: the write carries no `If-Match`."""


class IfMatchRefused(Exception):
    """412 `version_conflict`: `If-Match` is not exactly one weak tag of this resource."""


def refused(
    errors: Sequence[ProfileFieldError], *, noun: str = "member", limits: bool = False
) -> Refused:
    """A 422 of `errors`, its `detail` counting their distinct fields (22's `ProfileRejected`): "n
    member(s) failed validation.", or with `limits` "n member(s) break(s) an exchange limit."; the
    binding body's noun is "field"."""
    n = len({e.field for e in errors})
    one = n == 1
    verb = f"break{'s' if one else ''} an exchange limit" if limits else "failed validation"
    return Refused(errors, f"{n} {noun}{'' if one else 's'} {verb}.")


def idempotency(request: Request, operation: str) -> str | None:
    """`<operation>:<uuid>` from `Idempotency-Key`, or `None` without one (H6); a key that is no
    UUID is refused, never echoed."""
    try:
        return idempotency_key(request, operation)
    except ValueError:
        raise refused([_NOT_A_KEY], noun="field") from None


async def read_capped(request: Request, cap: int) -> bytes:
    """The raw body, refused past `cap` bytes before it is buffered whole (H7): a declared
    `Content-Length` over `cap` unread, and a stream at the chunk that passes it."""
    declared = request.headers.get("content-length", "")
    if _LENGTH.fullmatch(declared) and int(declared) > cap:
        raise BodyTooLarge(cap)
    raw = bytearray()
    async for chunk in request.stream():
        raw += chunk
        if len(raw) > cap:
            raise BodyTooLarge(cap)
    return bytes(raw)


def _no_constant(name: str) -> NoReturn:
    raise ValueError("not a JSON number")  # `NaN` and `Infinity` (RFC 8259 has neither)


def decode(raw: bytes, *, field: str = "") -> object:
    """The JSON value of `raw`: strict UTF-8 nested at most `MAX_JSON_DEPTH` deep, checked before
    anything decodes it, with `NaN` and `±Infinity` refused. A refusal is one entry at `field`,
    `json_invalid` or `json_too_deep`, counted as a "field" when `field` names one (the binding)."""
    noun = "field" if field else "member"
    try:
        text = raw.decode("utf-8")
        deep = json_depth_exceeds(text, MAX_JSON_DEPTH)
        value = None if deep else json.loads(text, parse_constant=_no_constant)
    except ValueError:  # not UTF-8, not JSON, a constant, or an integer past 4300 digits
        raise refused([ProfileFieldError(field, "json_invalid", _NOT_JSON)], noun=noun) from None
    if deep:
        raise refused([ProfileFieldError(field, "json_too_deep", _TOO_DEEP)], noun=noun)
    return value


def model_errors(exc: ValidationError, *, prefix: str = "") -> list[ProfileFieldError]:
    """The generated model's first `MODEL_ERRORS_SHOWN` failures, each at its member's path under
    `prefix` with the validator's own type as its rule: an unknown member at its parent, never by
    its key; no input and no context; each message through `redact_text`, but a non-object's,
    which is a constant."""
    found = exc.errors(include_url=False, include_input=False, include_context=False)
    entries = []
    for error in found[:MODEL_ERRORS_SHOWN]:
        loc = error["loc"][:-1] if error["type"] == "extra_forbidden" else error["loc"]
        path = ".".join(part for part in (prefix, field_path(loc)) if part)
        model_type = error["type"] == "model_type"  # names a class, not a value
        message = _NOT_AN_OBJECT if model_type else redact_text(error["msg"])
        entries.append(ProfileFieldError(path, error["type"], message))
    return entries


def name_errors(body: ProfileBody) -> list[ProfileFieldError]:
    """D2-c R1S-06: `name` holds no control or format code point (DEL, the C1 controls, U+200B,
    U+202E, U+FEFF), judged by its Unicode category, which the contract's pattern cannot name:
    such a name can pass for another on the Owner's screens. It runs with the first pass, on the
    body the schema phase accepted."""
    name = body.get("name")
    hidden = isinstance(name, str) and any(unicodedata.category(c) in _HIDDEN for c in name)
    return [_HIDDEN_IN_NAME] if hidden else []


def if_match_version(request: Request, resource: str) -> int:
    """The version `If-Match` names of `resource`, a profile id or `<accountId>:default` (U1, D1,
    B1): no header is `IfMatchMissing`; anything but exactly one weak tag of this resource (`*`, a
    list, two headers, the strong form, another resource's tag) is `IfMatchRefused`."""
    sent = request.headers.getlist("if-match")
    if not sent:
        raise IfMatchMissing
    tag = _TAG.fullmatch(sent[0].strip()) if len(sent) == 1 else None
    if tag is None or tag.group(1) != resource:
        raise IfMatchRefused
    return int(tag.group(2))
