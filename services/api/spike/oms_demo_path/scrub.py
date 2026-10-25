"""The scrubber every output passes before it is written (#843 A4 brief item 7; #843 security
notes; `03-testing-strategy.md` §4.1).

An allow-list design, as `tools/fixtures/redact.py` asks of a private-stream capture: a value
under a key the venue uses for an identifier (`ID_KEYS`) becomes a stable per-run token
(`order#3`), from an in-memory map that is never written; a header, a signature and the like
(`DROP_KEYS`) are dropped with their key; an `auth` frame is dropped whole. Then every string
left is cleaned of every value the run has registered: the account and key ids it was given,
each request's key id and signature, and every identifier any record has shown under an id key,
the record's own included (two passes), so a venue that echoes one in free text (`retMsg`, an
unknown field) does not carry it out. A push id that leads with digits (`<uid>_<symbol>_<seq>`)
teaches it the UID. `check` re-scans the final text and refuses it (`LeakDetected`) if any
registered value is left, so a line is written scrubbed or not at all.
"""

from __future__ import annotations

import json
import re
from collections.abc import Mapping, Sequence
from typing import Any, Final

#: The venue's identifier keys (REST rows, pushes, frame envelopes) and the harness's own model
#: names for them, each to its token class.
ID_KEYS: Final[Mapping[str, str]] = {
    "orderId": "order",
    "orderLinkId": "link",
    "parentOrderLinkId": "link",
    "execId": "exec",
    "blockTradeId": "block",
    "smpOrderId": "order",
    "nextPageCursor": "cursor",
    "cursor": "cursor",
    "id": "push",
    "conn_id": "conn",
    "req_id": "req",
    "uid": "uid",
    "userId": "uid",
    "userID": "uid",
    "accountId": "account",
    "account_id": "account",
    "exchange_order_id": "order",
    "order_link_id": "link",
    "exec_id": "exec",
    "key_ref": "key",
    "key_id": "key",
    "credential_id": "key",
    "apiKey": "key",
    "api_key": "key",
}
#: Keys dropped with their value, compared case-insensitively: request headers and anything
#: that holds a key, a signature or a session.
DROP_KEYS: Final = frozenset(
    {
        "headers",
        "x-bapi-api-key",
        "x-bapi-sign",
        "x-bapi-timestamp",
        "x-bapi-recv-window",
        "signature",
        "sign",
        "secret",
        "api_secret",
        "authorization",
        "cookie",
        "set-cookie",
        "args",
    }
)
#: A shorter value is no identifier the venue issues; registering it would rewrite ordinary text.
MIN_LEN: Final = 6
REDACTED: Final = "<redacted>"
_PUSH_ID: Final = re.compile(r"(\d{5,})_[A-Z0-9]+_\d+")


class LeakDetected(RuntimeError):
    """A registered value survived the scrub: the text is refused, never written."""


def _digits(value: str) -> re.Pattern[str]:
    """An all-digit value matches only between non-digits, so it never rewrites a timestamp."""
    return re.compile(rf"(?<!\d){re.escape(value)}(?!\d)")


class Scrubber:
    """Per-run tokens and registered values, in memory only (see the module docstring)."""

    def __init__(self) -> None:
        self._tokens: dict[str, str] = {}
        #: The tokens issued: a value already scrubbed is never learnt again (idempotent).
        self._issued: set[str] = {REDACTED}
        self._counts: dict[str, int] = {}
        self._secrets: set[str] = set()
        self._numeric: dict[str, re.Pattern[str]] = {}
        self._ordered: list[tuple[str, str]] | None = None

    def secret(self, value: str | None) -> None:
        """A value that is replaced wherever it appears and never written (`<redacted>`)."""
        if value is None or value in self._issued:
            return
        if len(value) >= MIN_LEN and value not in self._tokens:
            if value not in self._secrets:
                self._secrets.add(value)
                self._ordered = None
            if value.isdigit():
                self._numeric[value] = _digits(value)

    def known(self, kind: str, value: str) -> str:
        """`value`'s token of class `kind`, the same for the whole run; a token is its own."""
        if value in self._issued:
            return value
        token = self._tokens.get(value)
        if token is None:
            self._counts[kind] = self._counts.get(kind, 0) + 1
            token = self._tokens[value] = f"{kind}#{self._counts[kind]}"
            self._issued.add(token)
            self._secrets.discard(value)
            self._ordered = None
            if value.isdigit() and len(value) >= MIN_LEN:
                self._numeric[value] = _digits(value)
        return token

    def scrub(self, value: object, transient: Sequence[str] = ()) -> object:
        """`value` with every identifier replaced and every dropped key gone: first the record's
        own identifiers are learnt, then everything is rewritten."""
        self._learn(value)
        extra = tuple(v for v in transient if v and len(v) >= MIN_LEN)
        return self._rewrite(value, extra)

    def _learn(self, value: object) -> None:
        if isinstance(value, Mapping):
            for key, item in value.items():
                if str(key).lower() in DROP_KEYS:
                    continue
                kind = ID_KEYS.get(str(key))
                if kind is not None and isinstance(item, str | int) and str(item) != "":
                    text = str(item)
                    self.known(kind, text)
                    if kind == "push" and (m := _PUSH_ID.fullmatch(text)) is not None:
                        self.secret(m.group(1))
                else:
                    self._learn(item)
        elif isinstance(value, list | tuple):
            for item in value:
                self._learn(item)

    def _rewrite(self, value: object, extra: Sequence[str]) -> object:
        if isinstance(value, Mapping):
            out: dict[str, object] = {}
            for key, item in value.items():
                if str(key).lower() in DROP_KEYS:
                    continue
                kind = ID_KEYS.get(str(key))
                if kind is not None and isinstance(item, str | int) and str(item) != "":
                    text = str(item)
                    out[str(key)] = (
                        text if text in self._issued else self._tokens.get(text, REDACTED)
                    )
                else:
                    out[str(key)] = self._rewrite(item, extra)
            return out
        if isinstance(value, list | tuple):
            return [self._rewrite(item, extra) for item in value]
        if isinstance(value, str):
            return self._clean(value, extra)
        if isinstance(value, int) and not isinstance(value, bool) and str(value) in self._numeric:
            return self._tokens.get(str(value), REDACTED)
        return value

    def _registered(self, extra: Sequence[str]) -> list[tuple[str, str]]:
        """Every value a string is cleaned of, longest first (so no shorter one splits it): the
        call's transient values, the secrets and every identifier long enough to be one."""
        if self._ordered is None:
            pairs = [(v, REDACTED) for v in self._secrets]
            pairs += [(v, t) for v, t in self._tokens.items() if len(v) >= MIN_LEN]
            self._ordered = sorted(pairs, key=lambda p: -len(p[0]))
        if not extra:
            return self._ordered
        return sorted([(v, REDACTED) for v in extra] + self._ordered, key=lambda p: -len(p[0]))

    def _clean(self, text: str, extra: Sequence[str]) -> str:
        for value, replacement in self._registered(extra):
            pattern = self._numeric.get(value)
            if pattern is not None:
                text = pattern.sub(replacement, text)
            elif value in text:
                text = text.replace(value, replacement)
        return text

    def check(self, text: str, transient: Sequence[str] = ()) -> None:
        """Refuse `text` if any registered value is still in it."""
        for value, _ in self._registered(tuple(v for v in transient if v and len(v) >= MIN_LEN)):
            pattern = self._numeric.get(value)
            found = pattern.search(text) is not None if pattern is not None else value in text
            if found:
                raise LeakDetected("a registered identifier survived the scrub; nothing written")

    def dumps(self, value: object, transient: Sequence[str] = ()) -> str:
        """`value` scrubbed, as compact JSON, checked."""
        text = json.dumps(self.scrub(value, transient), separators=(",", ":"), default=str)
        self.check(text, transient)
        return text

    def frame(self, frame: str) -> Any:
        """A private-stream frame, scrubbed, or `None`: an `auth` op or reply is never kept."""
        try:
            decoded = json.loads(frame)
        except ValueError:
            return None
        if isinstance(decoded, dict) and decoded.get("op") == "auth":
            return None
        return self.scrub(decoded)
