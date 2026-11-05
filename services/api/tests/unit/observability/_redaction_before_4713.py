"""The labelled-value rules of the redaction filter and the bundle scan as `main` had them before
#4713 (075f6111c), frozen: the baseline that the widened rules are compared against.

Every fragment is copied as text, the key names too, so a later change to `redaction` or
`bundle_scan` leaves the baseline as it was. Only the parts of the two rules that read a label and
its value are copied; the full redaction of a text shorter than the cut uses the steps around them
(the value shapes, the download paths, the runs) from `redaction`, as #4713 did not change them.
"""

from __future__ import annotations

import re
from typing import Final

from candleviewer.observability import redaction

#: `redaction._REDACT_KEY_FORMS` before #4713.
KEY_FORMS: Final = frozenset(
    {
        "access_token",
        "api_key",
        "api_secret",
        "arm_token",
        "authorization",
        "bearer",
        "cookie",
        "csrf",
        "dek_ref",
        "input_value",
        "password",
        "proxy_authorization",
        "recovery_code",
        "refresh_token",
        "sealed_seed",
        "secret",
        "session",
        "session_token",
        "set_cookie",
        "sign",
        "signature",
        "token",
        "totp",
        "x_access_token",
        "x_api_key",
        "x_arm_token",
        "x_auth_token",
        "x_bapi_api_key",
        "x_bapi_sign",
        "x_csrf_token",
    }
)
#: Names the key list gained after #4713 (#1400 S3: the alert webhook's columns). The rules' shape
#: stays frozen; the names they read follow `redaction._REDACT_KEY_FORMS`, as `redaction`'s own
#: copy of the rule before #4713 reads the live list.
ADDED_SINCE: Final = frozenset(
    {"webhook_url", "webhook_url_enc", "webhook_secret", "webhook_secret_enc", "sealed_secret"}
)
KEY_MARKER: Final = "[redacted:key-name]"
_KEY_NAMES: Final = "|".join(
    sorted(re.escape(k).replace("_", "[-_]") for k in KEY_FORMS | ADDED_SINCE)
)
_NOT_DOTTED: Final = rf"""(?!(?<=\.)(?:{_KEY_NAMES}):(?!\\[tnr"'])[^\s"'])"""
_NO_VALUE: Final = (
    r"(?!(?:\[redacted:[a-z-]+\]|\.\.\.\[truncated:oversize\]|<omitted>|\*\*\*|null|none)"
    r"""(?=[\s"',}\]\\]|\.\.\.\[truncated:oversize\](?=[\s"'\\]|\Z)|\Z))"""
)
_KEY_FIRST: Final = "".join(sorted({k[0] for k in KEY_FORMS | ADDED_SINCE}))
_QUOTED: Final = r"""(?:"(?:\\.|[^"\\\n])*"?|'(?:\\.|[^'\\\n])*'?)"""
_TO_LINE_END: Final = r"(?<=cookie)|(?<=input[-_]value)"
_LABEL_START: Final = r"(?:\b|(?<=\\[tnr]))"
_LABEL_SPACE: Final = r"\s*[:=](?:\s|\\[tnr])*+"

#: `redaction._LABELLED_VALUE` before #4713.
LABELLED_VALUE: Final = re.compile(
    rf"""(?ix)(?P<label>{_LABEL_START}(?=[{_KEY_FIRST}]){_NOT_DOTTED}(?:{_KEY_NAMES})
    (?P<line>{_TO_LINE_END})?["']?{_LABEL_SPACE})
    (?:(?P<quote>["']){_NO_VALUE}(?:\\.|(?!(?P=quote))[^\\\n])+
    |{_NO_VALUE}(?(line)[^\s"'][^\n]*
    |(?:(?:bearer|basic)[ \t]+)?[^\s"',}}\]](?:[^\s"',}}\]]|{_QUOTED})*))"""
)
#: `redaction._LABEL_SEP` before #4713.
_LABEL_SEP: Final = re.compile(r"""[:=](?:(?<=[^\W\d_].)|(?<=["'\s].))""")


def _label_marker(match: re.Match[str]) -> str:
    return f"{match['label']}{match['quote'] or ''}{KEY_MARKER}"


def redact_labelled(text: str) -> str:
    """The labelled-value step of `redaction._redact_str_value` before #4713."""
    if ("=" in text or ":" in text) and _LABEL_SEP.search(text):
        return LABELLED_VALUE.sub(_label_marker, text)
    return text


def _uncut(text: str) -> str:
    if len(text) > redaction._CUT_LEN:
        raise ValueError("the baseline reads a text shorter than the cut")
    return text


def redact_text(text: str) -> str:
    """`redaction.redact_text` before #4713, for a text shorter than the cut: the labelled-value
    step, then the value shapes, which #4713 did not change."""
    text = redact_labelled(_uncut(text))
    match = redaction._VALUE_PATTERN.search(text)
    return text if match is None else redaction._marker(match)


def redact_runs(text: str) -> str:
    """`redaction._redact_runs` before #4713, for a text shorter than the cut: the labelled-value
    step, then the download paths and the runs, which #4713 did not change."""
    text = LABELLED_VALUE.sub(_label_marker, _uncut(text))
    text = redaction._DOWNLOAD_PATH.sub(redaction._DOWNLOAD_MARK, text)
    if redaction._VALUE_PATTERN.search(text) is not None:
        text = redaction._cut(redaction._RUN.sub(redaction._run_marker, text))
    return redaction._DOWNLOAD_MARK if redaction._DOWNLOAD_PATH.search(text) else text


#: `bundle_scan._LABELLED` before #4713 (as #4681 left it).
LABELLED_SOURCE: Final = rf"""(?ix)["']?(?:\b|(?<=\\[tnr])){_NOT_DOTTED}(?:{_KEY_NAMES})["']?
    \s*[:=](?:\s|\\[tnr])*+(?:\\?["'])?{_NO_VALUE}[^\s"',}}\]]{{6,}}"""
_LABELLED_HEAD: Final = re.compile(LABELLED_SOURCE.removesuffix("{6,}") + "{6}", re.I | re.X)
_ESCAPE_RUN: Final = re.compile(r"(?:\\++[tnr]?)*+")
_HOLDS_VALUE: Final = re.compile(_NO_VALUE, re.IGNORECASE)


def scan_labelled(text: str) -> bool:
    """`bundle_scan._labelled` before #4713: a labelled value that is not a marker."""
    pos = 0
    while (match := _LABELLED_HEAD.search(text, pos)) is not None:
        pos = match.end() - 6
        escapes = _ESCAPE_RUN.match(text, pos)
        pos = escapes.end() if escapes else pos
        if _HOLDS_VALUE.match(text, pos):
            return True
    return False
