"""Handler-level redaction filter for structured logging (M24, E04-T01).

Implements SR-120..SR-124 (`docs/plan/04-security-program.md` §6.9) and
mitigates threat K1/U5 (`docs/plan/threat-models/E04-observability.md` row
L4): a secret written to any logger, anywhere, must never reach stdout.

Two layers of defence, both required (belt and braces per the ticket's
Technical notes):

1. `RedactionProcessor` — a `structlog` processor, applied to every
   `structlog` logger's event dict.
2. `RedactionFilter` — a stdlib `logging.Filter` attached directly to the
   root handler, so records from third-party stdlib loggers (`httpx`,
   `websockets`, `sqlalchemy`, `pybit`) that never touch structlog are still
   scrubbed. This is the filter that a new call site cannot bypass, because
   nothing reaches stdout without passing through the root handler.

Both layers share the same matching engine (`_redact_value`/`_redact_mapping`)
so there is exactly one rule set to keep in sync (the ticket's "freezes the
redaction rule set" language in the Context section).
"""

from __future__ import annotations

import re
from typing import Any, Final

from candleviewer.domain.order_link import EXT_ID, OUR_ID
from candleviewer.observability.secret_type import Secret

#: Exact key names redacted regardless of value shape (case-insensitive).
#: Frozenset membership test — O(1), no regex, per the ticket's cost-control
#: note.
_REDACT_KEYS: Final[frozenset[str]] = frozenset(
    {
        "api_key",
        "api_secret",
        "secret",
        "password",
        "cookie",
        "set-cookie",
        "authorization",
        "x-bapi-sign",
        "x-bapi-api-key",
        "totp",
        "recovery_code",
        "session",
        "csrf",
        "access_token",
        "token",
        # the token and header forms the services use (#415)
        "refresh_token",
        "session_token",
        "bearer",
        "x-api-key",
        "x-auth-token",
        "x-access-token",
        "x-csrf-token",
        "proxy-authorization",
        # C-12.6 names signatures: a name is their control, as their hex shape stays readable
        "sign",
        "signature",
        # pydantic writes the input it refuses in a ValidationError's text by this name (#415)
        "input_value",
    }
)
#: `_REDACT_KEYS` with `-` read as `_`, as `_is_redact_key` reads a name: the hyphenated and the
#: underscored twin of each name (`refresh-token`, `x_api_key`) is redacted too (#415).
_REDACT_KEY_FORMS: Final[frozenset[str]] = frozenset(k.replace("-", "_") for k in _REDACT_KEYS)

#: What the value of a key named in `_REDACT_KEYS` is replaced by.
_KEY_NAME_MARKER: Final[str] = "[redacted:key-name]"
#: `_REDACT_KEY_FORMS` as a pattern, each name with `-` and `_` alike; the bundle scan's too.
_KEY_NAMES: Final = "|".join(sorted(re.escape(k).replace("_", "[-_]") for k in _REDACT_KEY_FORMS))
#: A name after a `.` is part of a dotted id, not a label, when a `:` follows it at once and then a
#: character other than a space or a quote: a WS machine topic such as `machines.session:<id>.state`
#: stays readable (#415). A dotted attribute and its value is a label (`self.password='…'`,
#: `obj.api_secret=…`, `cfg.token: …`), and an escaped line break or quote (`\n`, `\'`, as the
#: bundle's buffer writes them) reads as a space or a quote. The bundle scan's too.
_NOT_DOTTED: Final = rf"""(?!(?<=\.)(?:{_KEY_NAMES}):(?!\\[tnr"'])[^\s"'])"""
#: A labelled value that holds nothing to redact: a marker, the end of a cut text or a placeholder,
#: as the whole value, so `password=***x` holds a value (#415). What follows it ends a value: a
#: space, a quote, a comma, a closing bracket, the end, a `\`, as the bundle's buffer writes a line
#: break or a quote (`\n`, `\'`), or the end of a cut text, which a cut right after a marker leaves
#: there, when a space, a quote, a `\` or the end follows it, as a cut leaves it (#415). The bundle
#: scan reads the same as no value.
_NO_VALUE: Final = (
    r"(?!(?:\[redacted:[a-z-]+\]|\.\.\.\[truncated:oversize\]|<omitted>|\*\*\*|null|none)"
    r"""(?=[\s"',}\]\\]|\.\.\.\[truncated:oversize\](?=[\s"'\\]|\Z)|\Z))"""
)
#: The first letters of the key names: most words fail this check before any name is tried.
_KEY_FIRST: Final = "".join(sorted({k[0] for k in _REDACT_KEY_FORMS}))
#: A part of a value in quotes: to its closing quote (a `\` escapes a character) or the line's end.
_QUOTED: Final = r"""(?:"(?:\\.|[^"\\\n])*"?|'(?:\\.|[^'\\\n])*'?)"""
#: Names whose value, when it is not quoted, runs to the line's end (#415): a header's value is the
#: rest of its line (`Cookie: a=…; b=…`), and pydantic writes an input of any type (`{…}`, `[…]`).
#: Read as the end of the name just matched, so the other names cost nothing more.
_TO_LINE_END: Final = r"(?<=cookie)|(?<=input[-_]value)"
#: A label's `:` or `=` and the whitespace around it, read as the bundle scan reads them: the
#: redaction filter and the bundle scan agree on whitespace between a label and its value.
_LABEL_SPACE: Final = r"\s*[:=](?:\s|\\[tnr])*+"
#: A value labelled with a key name in text (`token = …`, `"password": "…"`, `Authorization: Bearer
#: …`): the bundle scan's labelled-secret rule as a substitution (#415). On its line, a
#: quoted value runs to its closing quote, a `_TO_LINE_END` name's to the line's end, and any other
#: bare one, after a `Bearer` or `Basic` scheme, to a space, comma or closing bracket, with any
#: quoted part in it (`access_token="…"`).
_LABELLED_VALUE: Final = re.compile(
    rf"""(?ix)(?P<label>\b(?=[{_KEY_FIRST}]){_NOT_DOTTED}(?:{_KEY_NAMES})(?P<line>{_TO_LINE_END})?
    ["']?{_LABEL_SPACE})
    (?:(?P<quote>["']){_NO_VALUE}(?:\\.|(?!(?P=quote))[^\\\n])+
    |{_NO_VALUE}(?(line)[^\s"'][^\n]*
    |(?:(?:bearer|basic)[ \t]+)?[^\s"',}}\]](?:[^\s"',}}\]]|{_QUOTED})*))"""
)
#: A label's `:` or `=` follows a letter (each key name ends with one), a quote or whitespace:
#: text whose separators all follow something else (a timestamp, an address) is not scanned further.
_LABEL_SEP: Final = re.compile(r"""[:=](?:(?<=[^\W\d_].)|(?<=["'\s].))""")

#: Maximum string length scanned for value-shape patterns. Longer values are
#: truncated with a marker *before* scanning so one huge payload cannot stall
#: the redaction loop (Technical notes cost-control paragraph).
_MAX_SCAN_LEN: Final[int] = 4096

#: Maximum recursion depth into nested dicts/lists. Deeper structures (or a
#: cyclic one) are replaced wholesale rather than recursed into.
_MAX_DEPTH: Final[int] = 6

#: A single pre-compiled alternation covering: Exchange-style API key/secret
#: charsets (long alphanumeric runs), JWT-like `xx.yy.zz` triples, and a
#: 6-digit code (TOTP shape) — all fairly permissive because the *label*
#: (key-name check above) already carries most of the recall.
_JWT_RE = r"[A-Za-z0-9_-]{10,}\.[A-Za-z0-9_-]{10,}\.[A-Za-z0-9_-]{10,}"
#: `_JWT_RE` as `_VALUE_PATTERN` scans it (#2689): it starts only where a run of segment characters
#: starts, and each segment is possessive. Unanchored, the greedy first segment was retried from
#: every offset of a long dot-free run and backtracked each time: O(n^2), ~10 ms per call at
#: `_MAX_SCAN_LEN` on client-shaped text. A segment never contains `.`, so a match inside a run
#: implies one from the run's start and no segment ever has to give characters back: with this
#: form `_VALUE_PATTERN.search` returns the same group and span as with `_JWT_RE`
#: (property-tested), in linear time. `bundle_scan` keeps `_JWT_RE`: its `\b` anchors can start a
#: match inside a run, so they need the backtracking form.
_JWT_SCAN_RE = r"(?<![A-Za-z0-9_-])[A-Za-z0-9_-]{10,}+\.[A-Za-z0-9_-]{10,}+\.[A-Za-z0-9_-]{10,}+"
_APIKEY_RE = r"\b[A-Za-z0-9]{18,36}\b"
_TOTP_RE = r"\b\d{6}\b"
#: The fewest characters a URL-safe token shape takes: the invite shape's lower bound.
_TOKEN_MIN = 42
#: Where a URL-safe value can start: not inside a run of URL-safe characters.
_URL_SAFE_START = r"(?<![A-Za-z0-9_-])"
#: Nor where a snake_case identifier starts, a run of `[a-z0-9_]` with an `_` (a log event or a
#: metric name stays readable; a `token_urlsafe` draw is practically never one; #415). Possessive:
#: the lookahead reads the run once, so the scan stays linear.
_NOT_SNAKE_CASE = r"(?![a-z0-9]*+_[a-z0-9_]*+(?![A-Za-z0-9_-]))"
#: A run shorter than `_TOKEN_MIN` is passed over before the identifier check and the shapes read
#: it: no match changes, and a scan of ordinary words costs what it did.
_TOKEN_START = f"{_URL_SAFE_START}(?=[A-Za-z0-9_-]{{{_TOKEN_MIN}}}){_NOT_SNAKE_CASE}"
#: A `secrets.token_urlsafe` value of 31 to 33 bytes: 42 to 44 URL-safe characters, standalone
#: (#415). 32 bytes (43 characters) is the invite, access and link token, and an invite token sits
#: in a URL path (`/invites/<token>`; C-12.6). The range stays tight so that ids stay readable: a
#: uuid4 (36 characters), a commit id (40) and a sha256 digest (64) are outside it.
_INVITE_BODY = f"[A-Za-z0-9_-]{{{_TOKEN_MIN},44}}(?![A-Za-z0-9_-])"
_INVITE_SHAPE_RE = _TOKEN_START + _INVITE_BODY
#: A `secrets.token_urlsafe(48)` value: 64 URL-safe characters, standalone (#415), the refresh token
#: of the session service. A run of 64 lowercase hex characters stays readable: it is a digest
#: (sha256), and also the shape of an HMAC-SHA256 signature and of a `secrets.token_hex(32)` value,
#: for which a key name (`sign`, `signature`, `x-bapi-sign`, as a field or a label) is the control.
#: Linear like the others: the start check fails at once inside a run, so the bounded
#: lookahead and the fixed count run only where a run starts.
_REFRESH_BODY = r"(?![0-9a-f]{64}(?![A-Za-z0-9_-]))[A-Za-z0-9_-]{64}(?![A-Za-z0-9_-])"
_REFRESH_SHAPE_RE = _TOKEN_START + _REFRESH_BODY
#: E42-T05 BK-11: a backup fetch's path, whatever its token's shape (defence in depth, AD-I04).
_DOWNLOAD_PATH_RE = r"/admin/backups/[^/]*/download/[^/\s]"  # an empty backupId too
#: The two URL-safe shapes share one start check: a position inside a run costs one lookbehind,
#: not two. It matches as `|(?P<invite>{_INVITE_SHAPE_RE})|(?P<refresh>{_REFRESH_SHAPE_RE})` would
#: (property-tested).
_VALUE_PATTERN = re.compile(
    f"(?P<jwt>{_JWT_SCAN_RE})|(?P<apikey>{_APIKEY_RE})"
    f"|{_TOKEN_START}(?:(?P<invite>{_INVITE_BODY})|(?P<refresh>{_REFRESH_BODY}))"
    f"|(?P<totp>{_TOTP_RE})|(?P<download>{_DOWNLOAD_PATH_RE})"
)

_REASON_BY_GROUP: Final[dict[str, str]] = {
    "jwt": "jwt-shape",
    "apikey": "key-shape",
    "totp": "totp-shape",
    "invite": "invite-token-shape",
    "refresh": "refresh-token-shape",
    "download": "download-path",
}

#: Where a text cut to `_MAX_SCAN_LEN` (`_cut`) lost characters.
_TRUNCATED: Final[str] = "...[truncated:oversize]"
#: The longest text that is not cut: a text cut once is not cut again.
_CUT_LEN: Final = _MAX_SCAN_LEN + len(_TRUNCATED)
#: The most of a long text's end that a cut keeps, as whole lines: a traceback names its exception
#: last (#415).
_TAIL_MAX: Final = 3072

#: A run of the characters the value shapes are made of: word characters, `.` and `-`. A match of
#: each shape but the download path lies inside one run, and the pattern matches a run alone exactly
#: as it matches it inside the text (what borders a run is a boundary to each of those shapes), so
#: `_redact_runs` can replace a whole run, and no part of a matched value stays beside its marker. A
#: download path holds `/`, which no run does: `_DOWNLOAD_PATH` takes it.
_RUN: Final = re.compile(r"[\w.-]+")
#: A run as `_cut` reads it: `_RUN` and the other characters of a marker and a placeholder (`[`,
#: `]`, `:`, `<`, `>`, `*`), so that a cut drops a marker or a placeholder whole: a part of one
#: after a label would read as a value (`_NO_VALUE`), and a second pass would change the text
#: (#415).
_CUT_RUN: Final = re.compile(r"[\w.\[\]:<>*-]+")
#: A backup download path as `_redact_runs` reads it (#415): `_DOWNLOAD_PATH_RE` and the rest of its
#: token, to a `/` or a space. It is replaced by `_DOWNLOAD_MARK` where it stands, the marker that a
#: message line holding one becomes. Linear: a backup id ends at the next `/`, so no two ids
#: overlap, and the token is possessive.
_DOWNLOAD_PATH: Final = re.compile(f"{_DOWNLOAD_PATH_RE}[^/\\s]*+")
_DOWNLOAD_MARK: Final = f"[redacted:{_REASON_BY_GROUP['download']}]"


def _is_redact_key(key: object) -> bool:
    return isinstance(key, str) and key.strip().lower().replace("-", "_") in _REDACT_KEY_FORMS


def _marker(match: re.Match[str]) -> str:
    return f"[redacted:{_REASON_BY_GROUP.get(match.lastgroup or '', 'value-shape')}]"


def _label_marker(match: re.Match[str]) -> str:
    """The label and its opening quote stay; the value is the key-name marker."""
    return f"{match['label']}{match['quote'] or ''}{_KEY_NAME_MARKER}"


def _cut(text: str) -> str:
    """`text`, or, when it is longer than `_CUT_LEN`, its start and its last lines (up to
    `_TAIL_MAX` characters), `_MAX_SCAN_LEN` characters in all, joined by `_TRUNCATED` (#415).

    The start is cut before a run that the cut would split, so no cut part of a value stays. Only
    the character at the cut is read forward, so a cut costs the same for a run of any length.
    """
    if len(text) <= _CUT_LEN:
        return text
    line = text.find("\n", len(text) - _TAIL_MAX)
    tail = text[line:] if line >= 0 else ""
    end = _MAX_SCAN_LEN - len(tail)
    if _CUT_RUN.match(text, end, end + 1) and (split := _CUT_RUN.match(text[end - 1 :: -1])):
        end -= split.end()
    return text[:end] + _TRUNCATED + tail


#: #3865 (SR-E29-16): the correlation key (ADR-0006 rule 1). Both §8.3 forms hold a key-shape
#: word (the 22-character group, the 32 hex digits), so the scan alone would mask every id.
_ORDER_LINK_KEY: Final[str] = "order_link_id"


def _is_order_link_id(key: object, value: object) -> bool:
    """The typed pass, never a field exemption: an exact `str` under the exact key
    `order_link_id` that fully matches a §8.3 form (`OUR_ID`, `EXT_ID`;
    `docs/plan/24-internal-schemas.md`). `fullmatch`, as `$` also matches before a trailing
    newline; a `str` subclass renders as it likes. Every other value is scanned as before."""
    return (
        type(key) is str
        and key == _ORDER_LINK_KEY
        and type(value) is str
        and (OUR_ID.fullmatch(value) is not None or EXT_ID.fullmatch(value) is not None)
    )


def _redact_str_value(value: str) -> str:
    """Redact a string: each value labelled with a key name shows the key-name marker, and the
    whole string is a shape's marker when a value shape matches in it (#415). A long string is cut
    first (`_cut`), and bounded again after, as markers can lengthen it.

    A 6-digit TOTP is only redacted by shape when found alongside a
    totp-ish neighbour is impractical to detect at this granularity (we do
    not have sibling-key context inside a bare string), so the key-name path
    is the primary control for TOTP and this shape check is a defence-in-
    depth catch for TOTP codes appearing inside free-form text (e.g. an
    exception message that echoes user input).
    """
    if len(value) > _CUT_LEN:
        value = _cut(value)
    if ("=" in value or ":" in value) and _LABEL_SEP.search(value):
        value = _LABELLED_VALUE.sub(_label_marker, value)
        if len(value) > _CUT_LEN:
            value = _cut(value)
    match = _VALUE_PATTERN.search(value)
    return value if match is None else _marker(match)


def _run_marker(run: re.Match[str]) -> str:
    match = _VALUE_PATTERN.search(run.group())
    return run.group() if match is None else _marker(match)


def _redact_runs(text: str) -> str:
    """Redact the text of a traceback or a stack where each value stands (#415).

    Each value labelled with a key name shows the key-name marker, each backup download path
    (`_DOWNLOAD_PATH`) shows its marker, and each run (`_RUN`) in which a value shape matches is
    replaced by that shape's marker; the rest of the text stays, so a traceback keeps its frames
    and lines. A long text is cut first (`_cut`), and bounded again after, as markers can lengthen
    it: a second pass changes nothing. A path still left at the end (paths nested in one another,
    or a cut right after a path's `/download/`) makes the whole text the marker, as for a message
    line.
    """
    text = _cut(_LABELLED_VALUE.sub(_label_marker, _cut(text)))
    text = _DOWNLOAD_PATH.sub(_DOWNLOAD_MARK, text)
    if _VALUE_PATTERN.search(text) is not None:
        text = _cut(_RUN.sub(_run_marker, text))
    return _DOWNLOAD_MARK if _DOWNLOAD_PATH.search(text) else text


def _exception_text(exc: BaseException, depth: int) -> str:
    """The text a renderer writes for an exception logged as a value or an argument (`str`).

    With `BaseException`'s own `__str__`, it is made from the arguments redacted first, so a
    mapping's keys and bytes get their rules (#415); with any other, it is `str(exc)`, which the
    text rules read. A broken `__str__` must not break the log call: it gets the `traceback`
    module's text.
    """
    try:
        if type(exc).__str__ is not BaseException.__str__:
            return str(exc)
        args = _redact_value(exc.args, depth)
        return str(args[0]) if len(args) == 1 else str(args) if args else ""
    except Exception:
        return "<exception str() failed>"


def _redact_value(value: Any, depth: int) -> Any:
    if depth > _MAX_DEPTH:
        return "[redacted:depth]"
    if isinstance(value, Secret):  # E27-T02: Secret never renders, whatever it wraps
        return "***"
    if isinstance(value, bytes | bytearray | memoryview):  # E27-T02: raw key buffers
        return "[redacted:bytes]"
    if isinstance(value, str):
        return _redact_str_value(value)
    if isinstance(value, dict):
        return _redact_mapping(value, depth + 1)
    if isinstance(value, (list, tuple)):
        redacted = [_redact_value(item, depth + 1) for item in value]
        return type(value)(redacted) if isinstance(value, tuple) else redacted
    if isinstance(value, BaseException):  # #415: its text is rendered here, then redacted
        return _redact_str_value(_exception_text(value, depth))
    return value


def _redact_mapping(mapping: dict[Any, Any], depth: int = 0) -> dict[Any, Any]:
    if depth > _MAX_DEPTH:
        return {"_": "[redacted:depth]"}
    out: dict[Any, Any] = {}
    for key, value in mapping.items():
        if _is_redact_key(key):
            out[key] = _KEY_NAME_MARKER
        elif _is_order_link_id(key, value):
            out[key] = value
        else:
            out[key] = _redact_value(value, depth)
    return out


def redact_text(value: str) -> str:
    """Public: redact a free-form string using the shared rule set."""
    return _redact_str_value(value)


def redact_structure(value: Any) -> Any:
    """Public: redact any JSON-like structure using the shared rule set."""
    return _redact_value(value, 0)
