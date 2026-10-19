"""Scrubber for every capture the harness writes (03-testing-strategy §4.1).

Credential fields become `***`. UIDs, account, connection, message, cursor and order identifiers
get stable, shape-keeping stand-ins, one per raw value for the whole run, so a REST page and the
private stream still agree (an execution's `orderId` is its order's): an `OUR_ID` link keeps its
env letter, `seq2` and purpose tag, a UUID stays a UUID, a digit string stays digits. In free
text (`retMsg`) a raw id already met, or any `OUR_ID`- or UUID-shaped token, gets its stand-in
too. `dumps` refuses output that still holds a known credential value or matches a secret
pattern of the CI gates (gitleaks Bybit rules, `packages/fixtures/scripts/verify.mjs`, a
key-shape tripwire).
"""

from __future__ import annotations

import json
import re
from collections.abc import Iterable
from dataclasses import replace
from typing import Any, Final
from uuid import UUID

from candleviewer.domain.order_link import OUR_ID
from candleviewer.domain.primitives import GroupId
from candleviewer.oms.order_link import OrderLinkIdParts
from candleviewer.secrets import Secret

MASK: Final = "***"
_CREDENTIAL: Final = frozenset(
    {"apikey", "api_key", "api-key", "apisecret", "api_secret", "secret", "sign", "signature"}
    | {"token", "password", "authorization", "cookie", "x-bapi-api-key", "x-bapi-sign"}
)
_ACCOUNT: Final = frozenset(
    {"uid", "userid", "user_id", "accountid", "account_id", "subuid", "parentuid", "memberid"}
)
_LINK: Final = frozenset({"orderlinkid", "parentorderlinkid"})
_OPAQUE: Final = frozenset(
    {"orderid", "execid", "blocktradeid", "id", "conn_id", "connid", "nextpagecursor"}
)
_UUID: Final = re.compile(
    r"[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12}"
)
_TOKEN: Final = re.compile(r"[A-Za-z0-9_-]+")
_PATTERNS: Final = {
    "key-field": re.compile(r'(?i)"(api[_-]?key|api[_-]?secret)"\s*:\s*"[A-Za-z0-9]{16,}"'),
    "signature-field": re.compile(r'(?i)"sign(ature)?"\s*:\s*"[A-Fa-f0-9]{32,}"'),
    "auth-header": re.compile(r"""(?i)X-BAPI-(API-KEY|SIGN)["']?\s*[:=]\s*["']?[A-Za-z0-9]{16,}"""),
    "hex-signature": re.compile(r"\b[a-fA-F0-9]{64}\b"),
}


class LeakError(ValueError):
    """Scrubbed output still matched a secret pattern; carries the pattern names only."""

    def __init__(self, patterns: list[str]) -> None:
        super().__init__(", ".join(patterns))
        self.patterns = patterns


def _key_shaped(token: str) -> bool:
    """A bare 18-20 or 36 character run of letters and digits: the shape of an exchange key or
    secret. Digit-only runs (`timeNano`) and letter-only enum values (`CancelByTpSlTsClear`) never
    count; the exact key id is caught by the known-value check."""
    if not (token.isascii() and token.isalnum()) or not (
        18 <= len(token) <= 20 or len(token) == 36
    ):
        return False
    return any(c.isdigit() for c in token) and any(c.isalpha() for c in token)


class Scrubber:
    """One per run, shared by the REST recorder and the private-stream capture."""

    def __init__(self, known: Iterable[Secret[str]] = ()) -> None:
        self._known: list[Secret[str]] = list(known)
        self._map: dict[str, str] = {}
        self._outs: set[str] = set()
        self._counts: dict[str, int] = {}

    def add_known(self, value: str) -> None:
        """A credential-like value (the key id, the account UID) that must never be written."""
        if value:
            self._known.append(Secret(value))

    def stand_in(self, kind: str, raw: str) -> str:
        """The stand-in of `raw` for `kind` (`account`, `link` or `opaque`); `""` stays `""`."""
        if not raw or raw in self._outs:  # already a stand-in: scrubbing twice changes nothing
            return raw
        if raw in self._map:
            return self._map[raw]
        n = self._counts[kind] = self._counts.get(kind, 0) + 1
        if kind == "link" and OUR_ID.fullmatch(raw):
            parts = OrderLinkIdParts.parse(raw)
            out = replace(parts, group_id=GroupId(UUID(int=n)), account_tag="0000").value
        elif kind == "account":
            out = str(100_000_000 + n) if raw.isdigit() else f"acct-{n}"
        elif _UUID.fullmatch(raw):
            out = str(UUID(int=n))
        elif raw.isdigit():
            out = str(n).zfill(len(raw))
        else:
            out = f"{kind}-{n}"
        self._map[raw] = out
        self._outs.add(out)
        return out

    def scrub(self, value: Any, key: str = "") -> Any:
        """A scrubbed deep copy of a JSON value; `key` is the field name it sits under."""
        name = key.lower()
        if isinstance(value, dict):
            return {k: self.scrub(v, str(k)) for k, v in value.items()}
        if isinstance(value, list):
            return [self.scrub(v, key) for v in value]
        if name in _CREDENTIAL:
            return value if value in (None, "") else MASK
        kind = "account" if name in _ACCOUNT else "link" if name in _LINK else None
        kind = "opaque" if kind is None and name in _OPAQUE else kind
        if kind and isinstance(value, str | int) and not isinstance(value, bool):
            out = self.stand_in(kind, str(value))
            return int(out) if isinstance(value, int) and out.isdigit() else out
        return self._text(value) if isinstance(value, str) else value

    def _text(self, text: str) -> str:
        for known in self._known:
            if known.reveal() in text:
                text = text.replace(known.reveal(), MASK)
        return _TOKEN.sub(self._token, text)

    def _token(self, match: re.Match[str]) -> str:
        """A known raw id, or an id-shaped token (`OUR_ID`, UUID) met first in free text."""
        token = match.group(0)
        if token in self._map:
            return self._map[token]
        if OUR_ID.fullmatch(token):
            return self.stand_in("link", token)
        return self.stand_in("opaque", token) if _UUID.fullmatch(token) else token

    def leaks(self, text: str) -> list[str]:
        """Names of the checks `text` fails (empty when clean)."""
        found = [name for name, rx in _PATTERNS.items() if rx.search(text)]
        if any(_key_shaped(token) for token in _TOKEN.findall(text)):
            found.append("key-shape")
        if any(known.reveal() in text for known in self._known):
            found.append("known-value")
        return found

    def check(self, text: str) -> str:
        """`text` unchanged, or `LeakError` naming the checks it fails."""
        leaks = self.leaks(text)
        if leaks:
            raise LeakError(leaks)
        return text

    def dumps(self, value: Any, *, indent: int | None = None) -> str:
        """`value` scrubbed and serialised; raises `LeakError` rather than return a leak."""
        return self.check(json.dumps(self.scrub(value), ensure_ascii=False, indent=indent))
