"""Redaction layer for `before_state`/`after_state` (ticket "Scope /
Deliverables": "removes any field classified SECRET ... and hashes PII where
the value itself is not needed").

Fail-closed by design (ticket "Security notes": "a redactor with a
fail-closed default — unknown fields in a SECRET-classified object are
dropped, not passed"): `redact()` only ever *removes or replaces* data, it
never lets an un-recognised nested structure pass through unexamined —
dicts are walked recursively and lists element-wise, so a field nested three
levels deep is caught exactly like a top-level one.

One reviewed exception (#966 BK-11): `_ENUM_PASS_THROUGH` names a
secret-named key whose value is kept when it is exactly one of a closed set
of fixed words: `bearer` is `matched` or `absent`, the flag `downloadBackup`
records for whether a fetch carried the issuing user's bearer. A value equal
to a word the code chose cannot carry a credential: it says only which word.
Every other value under that key (another string, a dict, a list, None, a
number) is still replaced, and every other key is untouched by the table.

The field-name registry below is deliberately name-based (not type-based):
every column comment in `0001_identity_rbac_sessions_mfa.py` marked `SECRET`
or `PII` names the exact field this list mirrors 1:1
(`password_hash`, TOTP `secret`, `recovery_codes.code_hash`,
`sessions.refresh_token_hash`, invite tokens, API keys). A field name is
matched case-insensitively and after stripping common separators, so
`passwordHash`, `password_hash` and `PASSWORD-HASH` are all caught.
"""

from __future__ import annotations

import hashlib
import json
import re
from collections.abc import Mapping
from types import MappingProxyType
from typing import Any

REDACTION_MARKER = "<redacted:secret>"
PII_HASH_PREFIX = "<hashed:pii>:"

#: Name fragments that mark a field as SECRET — dropped entirely, replaced
#: with `REDACTION_MARKER`. Matched against the normalised (lowercased,
#: separators stripped) field name as a substring, so `totp_seed`,
#: `totpSeed`, `mfa_secret` are all covered by `secret`/`seed`/`token`/`hash`.
_SECRET_FIELD_FRAGMENTS: frozenset[str] = frozenset(
    {
        "passwordhash",
        "password",
        "secret",
        "totpseed",
        "seed",
        "recoverycode",
        "refreshtoken",
        "accesstoken",
        "invitetoken",
        "apikey",
        "privatekey",
        "signature",
        "dek",
        "kek",
        "token",
        "hash",
    }
)

#: Exact (normalised) field names that mark a field as PII — matched exactly,
#: not as substrings (a substring match on `ip` would hash `description`,
#: `recipient`, ...). The value is replaced with a SHA-256 digest
#: (`PII_HASH_PREFIX` + hex) rather than dropped, so
#: correlation (e.g. "same IP as this other entry") stays possible without
#: storing the raw value (ticket: "hashes PII where the value itself is not
#: needed").
_PII_FIELD_NAMES: frozenset[str] = frozenset(
    {
        "email",
        "actorip",
        "ip",
        "ipaddress",
        "sourceip",
        "useragent",
        "displayname",
        "phonenumber",
        "phone",
    }
)

#: Exact (normalised: lowercased, every non-alphanumeric stripped) field
#: names that are credentials in their own right (security review of PR #1561,
#: finding 3): HTTP auth headers, exchange request-signing headers (the adapter's signature header),
#: one-time codes, session identifiers and bearer tokens. Exact match, not
#: substring, so `sign` does not redact `design`/`assign`. `recv_window` is
#: deliberately absent — it is a timing parameter, not a secret.
_SECRET_EXACT_NAMES: frozenset[str] = frozenset(
    {
        "key",
        "authorization",
        "proxyauthorization",
        "cookie",
        "setcookie",
        "bearer",
        "credential",
        "credentials",
        "passphrase",
        "sign",
        "signature",
        "xbapisign",
        "xbapiapikey",
        "otp",
        "totp",
        "otpcode",
        "totpcode",
        "mfacode",
        "session",
        "sid",
        "sessionid",
        "jwt",
        "idtoken",
        "accesstoken",
        "refreshtoken",
        "privatekey",
    }
)

#: Secret-named keys (normalised, exact) whose value passes only when it is exactly
#: one of these words, case-sensitive and unstripped (the module docstring).
#: Adding an entry is a security-reviewed edit (C-10.2).
_ENUM_PASS_THROUGH: Mapping[str, frozenset[str]] = MappingProxyType(
    {"bearer": frozenset({"matched", "absent"})}  # `downloadBackup` after_state.bearer
)

#: Secret-fragment names (normalised, exact) that hold reviewed metadata, never key material
#: (#4535): `kek_version` names which KEK enrolled, loaded or re-wrapped, and is kept only when
#: it is a version number (a positive int, or its decimal string). Any other value under the
#: name is still replaced. Adding an entry is a security-reviewed edit (C-10.2).
_METADATA_VERSION_NAMES: frozenset[str] = frozenset({"kekversion"})
_VERSION_RE = re.compile(r"[1-9][0-9]{0,8}")

#: snake_case suffixes (after camelCase/kebab-case are folded to snake_case)
#: that mark a field as SECRET: `secret_key`, `webhookSecret`, `csrf-token`.
_SECRET_SUFFIXES: tuple[str, ...] = ("_key", "_secret", "_token", "_password")

#: A field literally named `code` is a one-time code when it sits next to an
#: OTP marker (`{"method": "totp", "code": "123456"}` / `{"totp": ..., "code": ...}`).
_OTP_MARKERS: frozenset[str] = frozenset({"otp", "totp", "mfa"})

#: Embedded-JSON handling (PR #1561 N4): a string value that parses as a JSON
#: object/array (e.g. a logged request `body`) is redacted structurally and
#: re-serialised. Bounded so hostile input cannot turn redaction into a DoS:
#: nesting of embedded JSON strings is followed at most `_MAX_EMBED_DEPTH`
#: levels, and strings over `_MAX_EMBED_BYTES` are replaced wholesale
#: (fail closed: an oversized opaque blob might hide a secret).
_MAX_EMBED_DEPTH = 4
_MAX_EMBED_BYTES = 64 * 1024
OVERSIZE_MARKER = "<redacted:oversize-json>"

_NORMALISE_RE = re.compile(r"[^a-z0-9]")
_CAMEL_RE = re.compile(r"(?<=[a-z0-9])(?=[A-Z])")


def _normalise(name: str) -> str:
    return _NORMALISE_RE.sub("", name.lower())


def _snake(name: str) -> str:
    return _CAMEL_RE.sub("_", name).lower().replace("-", "_")


def _classify(field_name: str) -> str | None:
    normalised = _normalise(field_name)
    if normalised in _SECRET_EXACT_NAMES or _snake(field_name).endswith(_SECRET_SUFFIXES):
        return "secret"
    for fragment in _SECRET_FIELD_FRAGMENTS:
        if fragment in normalised:
            return "secret"
    if normalised in _PII_FIELD_NAMES:
        return "pii"
    return None


def _hash_pii(value: Any) -> str:
    digest = hashlib.sha256(repr(value).encode("utf-8")).hexdigest()
    return f"{PII_HASH_PREFIX}{digest}"


def redact(state: dict[str, Any] | None) -> dict[str, Any] | None:
    """Return a redacted copy of `state` (or `None` if `state` is `None`).

    Never mutates the input. SECRET-classified fields (by name, see
    `_SECRET_FIELD_FRAGMENTS`) become `REDACTION_MARKER`, unless the value is
    one of the key's fixed words in `_ENUM_PASS_THROUGH`; PII-classified
    fields become a SHA-256 digest of their `repr`; everything else is walked
    recursively (nested dicts/lists) so a SECRET value nested under an
    unclassified parent key is still caught.
    """
    if state is None:
        return None
    try:
        return _redact_mapping(state, 0)
    except RecursionError:
        # Pathologically deep structural nesting (e.g. `[[[[...]]]]` thousands
        # deep) exhausts the interpreter stack before `_MAX_EMBED_DEPTH` (which
        # bounds only *embedded-JSON* hops) can apply. Fail closed: the record
        # is kept, its state replaced wholesale by the oversize marker, so no
        # unredacted field can leak and the audited action is not refused.
        return {"_redacted": OVERSIZE_MARKER}


def _has_otp_sibling(mapping: dict[str, Any]) -> bool:
    for key, value in mapping.items():
        norm_key = _normalise(key)
        if any(marker in norm_key for marker in _OTP_MARKERS):
            return True
        if isinstance(value, str) and _normalise(value) in _OTP_MARKERS:
            return True
    return False


def _is_version_metadata(key: str, value: Any) -> bool:
    """A reviewed metadata name (`_METADATA_VERSION_NAMES`) holding a version number only."""
    if _normalise(key) not in _METADATA_VERSION_NAMES:
        return False
    if type(value) is int:
        return 0 < value < 10**9
    return type(value) is str and _VERSION_RE.fullmatch(value) is not None


def _redact_mapping(mapping: dict[str, Any], depth: int) -> dict[str, Any]:
    out: dict[str, Any] = {}
    otp_context = _has_otp_sibling(mapping)
    for key, value in mapping.items():
        classification = _classify(key)
        if classification is None and otp_context and _normalise(key) == "code":
            classification = "secret"
        if classification == "secret" and _is_version_metadata(key, value):
            out[key] = value
        elif classification == "secret":
            words = _ENUM_PASS_THROUGH.get(_normalise(key), frozenset())
            out[key] = value if type(value) is str and value in words else REDACTION_MARKER
        elif classification == "pii":
            out[key] = _hash_pii(value) if value is not None else None
        else:
            out[key] = _redact_value(value, depth)
    return out


def _redact_sequence(items: list[Any], depth: int) -> list[Any]:
    return [_redact_value(item, depth) for item in items]


def _redact_value(value: Any, depth: int) -> Any:
    if isinstance(value, dict):
        return _redact_mapping(value, depth)
    if isinstance(value, list):
        return _redact_sequence(value, depth)
    if isinstance(value, str):
        return _redact_embedded_json(value, depth)
    return value


def _redact_embedded_json(value: str, depth: int) -> str:
    stripped = value.lstrip()
    if not stripped or stripped[0] not in "{[":
        return value
    if len(value.encode("utf-8")) > _MAX_EMBED_BYTES:
        return OVERSIZE_MARKER
    try:
        parsed = json.loads(value)
    except ValueError:
        return value
    if not isinstance(parsed, dict | list):
        return value
    if depth >= _MAX_EMBED_DEPTH:
        return OVERSIZE_MARKER
    return json.dumps(_redact_value(parsed, depth + 1), separators=(",", ":"))
