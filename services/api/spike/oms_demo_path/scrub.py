"""The scrubber every output passes before it is written (#843 A4 brief item 7; #843 security
notes; `03-testing-strategy.md` §4.1).

An allow-list design, as `tools/fixtures/redact.py` asks of a private-stream capture: a value
under a key the venue uses for an identifier (`ID_KEYS`) becomes a stable per-run token
(`order#3`), from an in-memory map that is never written; a header, a signature and the like
(`DROP_KEYS`) are dropped with their key; an `auth` frame is dropped whole. Then every string
left is cleaned of every value the run has registered: the account and key ids it was given,
each request's key id and signature, and every identifier any record has shown under an id key,
the record's own included (two passes), so a venue that echoes one in free text (`retMsg`, an
unknown field) does not carry it out. A push id teaches it the UID in both of the venue's forms:
`<uid>_<symbol>_<seq>` (`execution`) and `<uid><uuid>` (`order`, `position`, `wallet`), the
UID being what precedes the 36-character UUID. `check` re-scans the final text and refuses it
(`LeakDetected`) if any registered value is left, so a line is written scrubbed or not at all.

The clean and the check cost O(len(text)), whatever the number of registered values (R1C-03:
a run registers thousands): the registered values are indexed by their first `MIN_LEN`
characters, so each position of a text costs one lookup, and only a position where a value
could start is compared.
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
#: The `execution` push id: `<uid>_<symbol>_<seq>`.
_PUSH_ID: Final = re.compile(r"(\d{6,})_[A-Z0-9]+_\d+")
#: The `order`, `position` and `wallet` push id: `<uid><uuid>`, the UID what precedes the UUID.
_UUID_PUSH_ID: Final = re.compile(
    r"(\d{6,})[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}"
)
#: A push id of neither form that leads with 7 or more digits: that run is learnt as it is.
_LEADING_DIGITS: Final = re.compile(r"\d{7,}")


class LeakDetected(RuntimeError):
    """A registered value survived the scrub: the text is refused, never written."""


def _bounded(text: str, at: int, length: int) -> bool:
    """An all-digit value matches only between non-digits, so it never rewrites a timestamp."""
    before = at > 0 and text[at - 1].isdigit()
    end = at + length
    return not before and not (end < len(text) and text[end].isdigit())


class Scrubber:
    """Per-run tokens and registered values, in memory only (see the module docstring)."""

    def __init__(self) -> None:
        self._tokens: dict[str, str] = {}
        #: The tokens issued: a value already scrubbed is never learnt again (idempotent).
        self._issued: set[str] = {REDACTED}
        self._counts: dict[str, int] = {}
        #: Every registered value at least `MIN_LEN` long, to what replaces it: its token, else
        #: `REDACTED`. Indexed by its first `MIN_LEN` characters (`_heads`: the lengths of the
        #: values that start so, longest first).
        self._replace: dict[str, str] = {}
        self._heads: dict[str, list[int]] = {}

    def _register(self, value: str, replacement: str) -> None:
        if len(value) < MIN_LEN:
            return
        if value not in self._replace:
            lengths = self._heads.setdefault(value[:MIN_LEN], [])
            if len(value) not in lengths:
                lengths.append(len(value))
                lengths.sort(reverse=True)
        self._replace[value] = replacement

    def secret(self, value: str | None) -> None:
        """A value that is replaced wherever it appears and never written (`<redacted>`)."""
        if value is None or value in self._issued or value in self._tokens:
            return
        self._register(value, REDACTED)

    def known(self, kind: str, value: str) -> str:
        """`value`'s token of class `kind`, the same for the whole run; a token is its own."""
        if value in self._issued:
            return value
        token = self._tokens.get(value)
        if token is None:
            self._counts[kind] = self._counts.get(kind, 0) + 1
            token = self._tokens[value] = f"{kind}#{self._counts[kind]}"
            self._issued.add(token)
            self._register(value, token)
        return token

    def registered(self) -> int:
        """How many values a text is cleaned of."""
        return len(self._replace)

    def scrub(self, value: object, transient: Sequence[str] = ()) -> object:
        """`value` with every identifier replaced and every dropped key gone: first the record's
        own identifiers are learnt, then everything is rewritten."""
        self._learn(value)
        extra = sorted((v for v in transient if v and len(v) >= MIN_LEN), key=len, reverse=True)
        return self._rewrite(value, extra)

    def _learn_push(self, text: str) -> None:
        """The UID a push id carries, in either of the venue's forms (see the module docstring)."""
        for form in (_PUSH_ID, _UUID_PUSH_ID):
            if (m := form.fullmatch(text)) is not None:
                self.secret(m.group(1))
                return
        if (m := _LEADING_DIGITS.match(text)) is not None:
            self.secret(m.group(0))

    def _learn(self, value: object) -> None:
        if isinstance(value, Mapping):
            for key, item in value.items():
                if str(key).lower() in DROP_KEYS:
                    continue
                kind = ID_KEYS.get(str(key))
                if kind is not None and isinstance(item, str | int) and str(item) != "":
                    text = str(item)
                    self.known(kind, text)
                    if kind == "push":
                        self._learn_push(text)
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
        if isinstance(value, int) and not isinstance(value, bool):
            text = str(value)
            if text in self._replace and text.isdigit():
                return self._replace[text]
        return value

    def _match(self, text: str, at: int) -> tuple[int, str] | None:
        """The longest registered value starting at `at`, with what replaces it."""
        lengths = self._heads.get(text[at : at + MIN_LEN])
        if lengths is None:
            return None
        for length in lengths:
            found = self._replace.get(text[at : at + length])
            if found is not None and (
                not text[at].isdigit()
                or not text[at : at + length].isdigit()
                or _bounded(text, at, length)
            ):
                return length, found
        return None

    def _clean(self, text: str, extra: Sequence[str]) -> str:
        for value in extra:  # the call's own values (few), longest first
            text = text.replace(value, REDACTED)
        heads = self._heads
        if len(text) < MIN_LEN or not heads:
            return text
        parts: list[str] = []
        start = 0
        for at in range(len(text) - MIN_LEN + 1):
            if at < start or text[at : at + MIN_LEN] not in heads:
                continue
            hit = self._match(text, at)
            if hit is not None:
                parts += [text[start:at], hit[1]]
                start = at + hit[0]
        return "".join([*parts, text[start:]]) if parts else text

    def check(self, text: str, transient: Sequence[str] = ()) -> None:
        """Refuse `text` if any registered value is still in it."""
        for value in transient:
            if value and len(value) >= MIN_LEN and value in text:
                raise LeakDetected("a registered identifier survived the scrub; nothing written")
        heads = self._heads
        for at in range(len(text) - MIN_LEN + 1):
            if text[at : at + MIN_LEN] in heads and self._match(text, at) is not None:
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
