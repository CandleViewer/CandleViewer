#!/usr/bin/env python3
"""E49-Q01 (#1335, BQ-08): scrub credentials from Playwright failure artefacts before upload.

A Playwright trace records every request and response verbatim, headers and bodies included, and
every typed value of a ``fill``/``type`` action; a HAR does the same for the network (ticket
Security notes). This walks a results directory and rewrites, in place: trace archives (``*.zip``:
each text member), HAR, JSON, NDJSON trace/network logs, markdown error contexts, HTML, XML and
text logs.
Trace resources named ``.dat`` (bodies with no known mime type, such as a form post) are scrubbed
as text unless they look binary. Binary members and media (screenshots, videos) are left as they
are; they hold pixels, not headers.

What is replaced by ``[REDACTED]``, by pattern (no literal secret, host or header value is named):

* name/value records (trace and HAR form) whose name is a sensitive header (Authorization,
  Proxy-Authorization, Cookie, Set-Cookie, any ``x-...`` header ending in key, sign, signature,
  secret or token) or a credential-like name, and every record inside a ``cookies`` array; raw
  ``<sensitive>: value`` header lines; header maps in object form (``{"cookie": "..."}``);
* JSON members whose key names a credential (password, passphrase, secret, token, api key,
  signature, TOTP, otpauth, OTP code, recovery codes, session id), string or number valued, at any
  escaping depth (a request body inside a trace is JSON inside a JSON string), and an OTP-shaped
  (6 to 8 digit) ``code``/``otp``/``pin``;
* credentials in URLs and form bodies (``?token=``, ``&signature=``, ``password=``, ...), URL
  userinfo (``scheme://user:password@host``), whole ``otpauth://`` URIs and the token segment of
  ``/invite/<token>``;
* the ``value``/``text`` parameter of every typing action (``fill``, ``type``,
  ``pressSequentially``, ``insertText``, ``keyboardType``, ``keyboardInsertText``) in a trace's
  NDJSON events, and the argument of the call-log line Playwright writes for it
  (``fill("...")``, raw or JSON-escaped);
* every ``__playwright_value_`` in a trace's DOM snapshots (fail-safe: all of them, not only
  password-typed or OTP-named inputs, because a snapshot records every input's live value and
  the attributes that would tell a credential apart are not reliable), and likewise the plain
  ``value`` attribute of every INPUT/TEXTAREA snapshot node and a TEXTAREA's text child (React
  copies a controlled field's value there), raw or JSON-escaped; in page HTML, every
  ``<input value>`` and ``<textarea>`` body (SELECT/OPTION values are the page's own, left);
* the value of every ``textbox``/``searchbox``/``spinbutton`` line of an aria snapshot
  (``error-context.md``, and the ``\\n``-escaped form inside a trace's JSON): fail-safe for every
  label, because an accessible name ("Code", "Enter the 6 digits") does not reliably say whether
  the field holds a credential;
* credentials under unquoted keys in evaluated source (``{ password: "...", otp: 123456 }``);
* ``Bearer``/``Basic`` credentials anywhere.

Fail-closed: a file that cannot be read or rewritten (a truncated trace archive from a killed
worker, an I/O error) is deleted, the walk goes on, and the exit code is 1, so the workflow's
upload steps (gated on this step's success) publish nothing unscrubbed.

``--self-test`` seeds a trace archive and a HAR with fake values in each form, scrubs them and
fails unless every seeded value is gone; the nightly runs it before scrubbing real artefacts.
Exit codes: 0 scrubbed, 1 self-test failed or a file could not be scrubbed, 2 usage. Stdlib only.
"""

from __future__ import annotations

import argparse
import io
import json
import re
import sys
import tempfile
import zipfile
import zlib
from collections.abc import Callable, Sequence
from pathlib import Path
from typing import Any

MASK = "[REDACTED]"
TEXT_SUFFIXES = {
    ".har",
    ".json",
    ".jsonl",
    ".trace",
    ".network",
    ".stacks",
    ".md",
    ".txt",
    ".log",
    ".html",
    ".xml",
}
#: Bounds that keep every pattern linear: a key word wrapped in at most 64 name characters
#: (`x_cv_api_key_v2`), a quote at most 8 escaping levels deep. Unbounded, a long run of key
#: words or backslashes made a scan quadratic (minutes on a megabyte).
_W = "{0,64}"
_SENSITIVE_HEADER = (
    r"(?:proxy-)?authorization|cookie|set-cookie"
    r"|x-[a-z0-9-]{0,64}(?:key|sign|signature|secret|token)"
)
_CREDENTIAL_WORD = (
    r"password|passphrase|secret|token|api[_-]?key|apikey|signature|totp|otpauth|otp[_-]?code"
    r"|recovery[_-]?codes?|session[_-]?id|sessionid|session[_-]?token"
)
_SENSITIVE_KEY = (
    rf"[A-Za-z0-9_-]{_W}(?:{_CREDENTIAL_WORD})[A-Za-z0-9_-]{_W}|{_SENSITIVE_HEADER}|sid|ssid|sess"
)
#: A record name that marks its value as a credential: a header, a credential-like word, or a
#: session cookie name (`cv_session`, `sid`, ...).
_SENSITIVE_NAME = re.compile(
    rf"^(?:{_SENSITIVE_KEY}"
    rf"|[A-Za-z0-9_.-]{_W}(?:session|sess|sid|auth|csrf|xsrf)[A-Za-z0-9_.-]{_W})$",
    re.I,
)
#: A query or form parameter name that carries a credential (`?token=`, `&sig=`, `password=`).
_PARAM = (
    rf"[A-Za-z0-9_-]{_W}(?:{_CREDENTIAL_WORD}|session)[A-Za-z0-9_-]{_W}|code|key|sig|sid|otp|pin"
)
# A quote at some escaping depth: `"`, `\"`, `\\\"`, ... (at most 8 levels); the value ends at the
# same depth.
_Q = r'(?P<q>\\{0,8}")'
_VALUE = r"(?P<v>.*?)(?<!\\)(?P=q)"
_NUMBER = r"(?P<n>-?\d[\d.eE+-]*)"
_RECORD = re.compile(
    rf"{_Q}name(?P=q)\s*:\s*(?P=q)(?P<h>[^\"\\]*)(?P=q)\s*,\s*"
    rf"(?P=q)value(?P=q)\s*:\s*(?:(?P=q){_VALUE}|{_NUMBER})",
    re.I,
)
_KEY_STRING = re.compile(rf"{_Q}(?P<k>{_SENSITIVE_KEY})(?P=q)\s*:\s*(?P=q){_VALUE}", re.I)
#: A numeric credential (`"otp": 123456`, `"pin": 1234`); counts such as `tokens_used` stay.
_NUMERIC_KEY = (
    rf"[A-Za-z0-9_-]{_W}(?:password|passphrase|secret|totp|otp|pin|api[_-]?key|apikey)"
    rf"[A-Za-z0-9_-]{_W}|[A-Za-z_-]{_W}token"
)
_KEY_NUMBER = re.compile(rf"{_Q}(?P<k>{_NUMERIC_KEY})(?P=q)\s*:\s*{_NUMBER}", re.I)
_OTP_SHAPED = re.compile(
    rf"{_Q}(?P<k>code|otp|pin)(?P=q)\s*:\s*(?:(?P=q)(?P<v>\d{{6,8}})(?P=q)|(?P<n>\d{{6,8}})\b)",
    re.I,
)
_KEY_ARRAY = re.compile(rf"{_Q}(?P<k>{_SENSITIVE_KEY})(?P=q)\s*:\s*\[[^\]]*\]", re.I)
_COOKIES = re.compile(rf"{_Q}(?:request_?|response_?)?cookies(?P=q)\s*:\s*\[", re.I)
_COOKIE_VALUE = r"(?P<pre>{q}value{q}\s*:\s*{q})(?P<v>.*?)(?<!\\){q}"
_HEADER_LINE = re.compile(rf"(?im)^(?P<h>\s*(?:{_SENSITIVE_HEADER})\s*:)[^\r\n]*")
_SCHEME = re.compile(r"\b(?P<s>Bearer|Basic)\s+[A-Za-z0-9._~+/=-]{4,}", re.I)
_URL_PARAM = re.compile(
    rf"(?P<k>(?<![A-Za-z0-9_.-])(?:{_PARAM})=)(?!{re.escape(MASK)})[^&\s\"'#<>\\]+", re.I
)
_OTPAUTH = re.compile(r"otpauth://(?!\[REDACTED\])[^\s\"'<>\\]+", re.I)
_INVITE = re.compile(r"(?P<p>/invite/)(?!\[REDACTED\]|:)[^/?#\s\"'<>\\]+")
#: Trace actions whose `value`/`text` parameter is what the test typed.
TYPED_METHODS = {
    "fill",
    "type",
    "pressSequentially",
    "insertText",
    "keyboardType",
    "keyboardInsertText",
}
#: The call-log line of a typing action (`  fill("...")`), raw or at any escaping depth.
_TYPED_LOG = re.compile(
    rf"(?<![A-Za-z0-9_])(?:fill|type|pressSequentially|insertText)\({_Q}{_VALUE}\)"
)
#: The live value of every input in a DOM snapshot.
_SNAPSHOT_VALUE = re.compile(rf"{_Q}__playwright_value_(?P=q)\s*:\s*(?P=q){_VALUE}")
#: An INPUT or TEXTAREA node of a DOM snapshot, up to its attribute map: `["INPUT",{`. React
#: copies a controlled input's value into the plain `value` attribute, and a controlled
#: textarea's into its text child, so both are masked for every such node, as for
#: `__playwright_value_`. SELECT/OPTION `value`s are left: they are the page's own option values,
#: not typed text (the selection is the separate `__playwright_selected_` flag).
_FIELD_NODE = re.compile(rf"\[\s*{_Q}(?P<tag>INPUT|TEXTAREA)(?P=q)\s*,\s*\{{", re.I)
#: The same fields in page HTML (a `.html` trace resource or report): `<input ... value="...">`
#: and the body of a `<textarea>`.
_HTML_INPUT = re.compile(r"<input\b(?:[^<>\"']|\"[^\"]*\"|'[^']*')*>?", re.I)
#: Its `value`, quoted (raw, or `\"` inside a JSON string) or bare; the mask keeps the quoting.
_HTML_VALUE = re.compile(
    r"(?P<p>\svalue\s*=\s*)(?:(?P<o>\\{0,8}[\"'])(?P<v>.*?)(?<!\\)(?P=o)|(?P<b>[^\s\"'>\\]+))",
    re.I | re.S,
)
_HTML_TEXTAREA = re.compile(r"(?P<p><textarea\b[^<>]*>)(?P<v>[^<]+)(?=</textarea\s*>)", re.I)
#: The userinfo of a URL (`scheme://user:password@host`).
_USERINFO = re.compile(
    r"(?P<s>\b[A-Za-z][A-Za-z0-9+.-]{0,30}://)(?!\[REDACTED\]@)"
    r"[^\s/?#@:\"'<>\\]{0,256}:[^\s/?#@\"'<>\\]{1,2048}@"
)
_ARIA_FIELD = r"- (?:textbox|searchbox|spinbutton)"
#: An aria-snapshot field line with a value, raw (`error-context.md`).
_ARIA_RAW = re.compile(
    rf'(?m)^(?P<p>[ \t]*{_ARIA_FIELD}(?: "(?:[^"\\\n]|\\.)*")?(?: \[[^\]\n]*\])*: )(?P<v>[^\n]+)'
)
#: The same line inside a JSON string, where newlines are `\n` and quotes `\"`.
_ARIA_ESCAPED = re.compile(
    rf'(?P<p>(?:\\n|(?<!\\)")[ \t]*{_ARIA_FIELD}(?: \\"(?:(?!\\")[^\r\n])*?\\")?'
    rf"(?: \[[^\]\\\r\n]*\])*: )(?P<v>(?:[^\\\"\r\n]|\\[^n\r\n])+)"
)
#: A credential under an unquoted key (JavaScript source in an `evaluateExpression` event).
_BARE_KEY_STRING = re.compile(
    rf"(?<![A-Za-z0-9_\"\\-])(?P<k>{_SENSITIVE_KEY})\s*:\s*{_Q}{_VALUE}", re.I
)
_BARE_KEY_NUMBER = re.compile(
    rf"(?<![A-Za-z0-9_\"\\-])(?P<q>)(?P<k>{_NUMERIC_KEY})\s*:\s*{_NUMBER}", re.I
)


def _mask_value(m: re.Match[str]) -> str:
    """Rewrite one match, replacing its `v` (string) or `n` (number) group by the mask."""
    q = m.group("q")
    whole = m.group(0)
    if m.groupdict().get("v") is not None:
        return whole[: m.start("v") - m.start(0)] + MASK + whole[m.end("v") - m.start(0) :]
    return whole[: m.start("n") - m.start(0)] + q + MASK + q + whole[m.end("n") - m.start(0) :]


def _record(m: re.Match[str]) -> str:
    return _mask_value(m) if _SENSITIVE_NAME.match(m.group("h")) else m.group(0)


def _array_end(text: str, start: int, q: str) -> int:
    """Index of the `]` closing the array whose `[` precedes `start`, skipping strings at `q`."""
    string = re.compile(r"(.*?)(?<!\\)" + re.escape(q), re.S)
    depth, i = 1, start
    while i < len(text):
        if text.startswith(q, i) and (i == 0 or text[i - 1] != "\\"):
            m = string.match(text, i + len(q))
            i = m.end() if m else len(text)
            continue
        c = text[i]
        if c == "[":
            depth += 1
        elif c == "]":
            depth -= 1
            if not depth:
                return i
        i += 1
    return len(text)


def _masker(q: str) -> Callable[[re.Match[str]], str]:
    def mask(v: re.Match[str]) -> str:
        return v.group("pre") + MASK + q

    return mask


def _scrub_cookie_arrays(text: str) -> str:
    """Every name/value record inside a `cookies` array: the value goes, whatever the name."""
    out, pos = [], 0
    for m in _COOKIES.finditer(text):
        if m.start() < pos:
            continue
        q = m.group("q")
        end = _array_end(text, m.end(), q)
        value = re.compile(_COOKIE_VALUE.format(q=re.escape(q)), re.I | re.S)
        region = value.sub(_masker(q), text[m.end() : end])
        out += [text[pos : m.end()], region]
        pos = end
    return "".join(out) + text[pos:] if out else text


def _mask_typed(node: Any) -> bool:
    """Masks the typed value of each typing action under `node`; True when one changed."""
    changed = False
    if isinstance(node, dict):
        method = str(node.get("method") or str(node.get("apiName", "")).rsplit(".", 1)[-1])
        params = node.get("params")
        if method in TYPED_METHODS and isinstance(params, dict):
            for key in ("value", "text"):
                if key in params and params[key] not in ("", MASK):
                    params[key] = MASK
                    changed = True
        for child in node.values():
            changed |= _mask_typed(child)
    elif isinstance(node, list):
        for child in node:
            changed |= _mask_typed(child)
    return changed


def _scrub_typed(text: str) -> str:
    if "params" not in text or not any(m in text for m in TYPED_METHODS):
        return text
    try:
        whole = json.loads(text)
    except ValueError:
        whole = None
    if whole is not None:
        return json.dumps(whole, ensure_ascii=False) + "\n" if _mask_typed(whole) else text
    lines = text.split("\n")
    for i, line in enumerate(lines):
        if line.lstrip().startswith("{") and "params" in line:
            try:
                event = json.loads(line)
            except ValueError:
                continue
            if _mask_typed(event):
                lines[i] = json.dumps(event, ensure_ascii=False)
    return "\n".join(lines)


def _attr_pattern(q: str) -> re.Pattern[str]:
    """One `"name":"value"` pair of a snapshot attribute map at quote `q`, then `,` or `}`."""
    qe = re.escape(q)
    return re.compile(
        rf"\s*{qe}(?P<k>[^\"\\]{{0,256}}){qe}\s*:\s*{qe}(?P<v>.*?)(?<!\\){qe}\s*(?P<e>,|\}})", re.S
    )


def _scrub_field_nodes(text: str) -> str:
    """The `value` attribute of every INPUT/TEXTAREA snapshot node, and a TEXTAREA's text child,
    raw or at any escaping depth. Attributes are walked pair by pair at the node's own depth."""
    out, pos = [], 0
    for m in _FIELD_NODE.finditer(text):
        if m.start() < pos:
            continue
        q = m.group("q")
        attr = _attr_pattern(q)
        out.append(text[pos : m.end()])
        i, closed = m.end(), text.startswith("}", m.end())
        if closed:
            out.append("}")
            i += 1
        while not closed and (a := attr.match(text, i)):
            if a.group("k").lower() == "value":
                out += [text[i : a.start("v")], MASK, text[a.end("v") : a.end()]]
            else:
                out.append(text[i : a.end()])
            i, closed = a.end(), a.group("e") == "}"
        if closed and m.group("tag").upper() == "TEXTAREA":
            child = re.compile(rf"\s*,\s*{re.escape(q)}(?P<v>.*?)(?<!\\){re.escape(q)}", re.S)
            c = child.match(text, i)
            if c and c.group("v") not in ("", MASK):
                out += [text[i : c.start("v")], MASK, text[c.end("v") : c.end()]]
                i = c.end()
        pos = i
    return "".join(out) + text[pos:] if out else text


def _mask_html_value(m: re.Match[str]) -> str:
    quote = m.group("o") or ""
    return m.group("p") + quote + MASK + quote


def _mask_aria(m: re.Match[str]) -> str:
    return m.group("p") + MASK


def scrub_text(text: str) -> str:
    text = _scrub_typed(text)
    text = _TYPED_LOG.sub(_mask_value, text)
    text = _SNAPSHOT_VALUE.sub(_mask_value, text)
    text = _scrub_field_nodes(text)
    text = _HTML_INPUT.sub(lambda t: _HTML_VALUE.sub(_mask_html_value, t.group(0)), text)
    text = _HTML_TEXTAREA.sub(lambda m: m.group("p") + MASK, text)
    text = _ARIA_RAW.sub(_mask_aria, text)
    text = _ARIA_ESCAPED.sub(_mask_aria, text)
    text = _scrub_cookie_arrays(text)
    text = _RECORD.sub(_record, text)
    text = _KEY_STRING.sub(_mask_value, text)
    text = _KEY_NUMBER.sub(_mask_value, text)
    text = _OTP_SHAPED.sub(_mask_value, text)
    text = _BARE_KEY_STRING.sub(_mask_value, text)
    text = _BARE_KEY_NUMBER.sub(_mask_value, text)
    text = _KEY_ARRAY.sub(
        lambda m: f"{m.group('q')}{m.group('k')}{m.group('q')}: {m.group('q')}{MASK}{m.group('q')}",
        text,
    )
    text = _HEADER_LINE.sub(lambda m: f"{m.group('h')} {MASK}", text)
    text = _OTPAUTH.sub(f"otpauth://{MASK}", text)
    text = _URL_PARAM.sub(lambda m: m.group("k") + MASK, text)
    text = _INVITE.sub(lambda m: m.group("p") + MASK, text)
    text = _USERINFO.sub(lambda m: f"{m.group('s')}{MASK}@", text)
    return _SCHEME.sub(lambda m: f"{m.group('s')} {MASK}", text)


def _looks_binary(data: bytes) -> bool:
    head = data[:8192]
    return b"\x00" in head or head.startswith((b"\x89PNG", b"\xff\xd8\xff", b"GIF8", b"RIFF"))


def _scrub_bytes(data: bytes, strict: bool = False) -> bytes | None:
    """The scrubbed bytes, or None when nothing changed. Text that is not valid UTF-8 is still
    scrubbed (undecodable bytes round-trip); `strict` skips it as binary instead."""
    try:
        text = data.decode("utf-8")
    except UnicodeDecodeError:
        if strict or _looks_binary(data):
            return None
        text = data.decode("utf-8", "surrogateescape")
    out = scrub_text(text)
    return None if out == text else out.encode("utf-8", "surrogateescape")


def _is_text_member(name: str) -> bool:
    suffix = Path(name).suffix.lower()
    # Trace resources are named by hash with no suffix (request/response bodies), a mime
    # extension (`.json`) or `.dat` when the mime type is unknown (a form post).
    return suffix in TEXT_SUFFIXES or suffix in ("", ".dat")


def scrub_zip(path: Path) -> int:
    """Rewrite each changed text member of an archive; returns the number of members changed.
    Raises on an unreadable archive (scrub_tree deletes it)."""
    changed = 0
    buf = io.BytesIO()
    with zipfile.ZipFile(path) as src, zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as dst:
        for info in src.infolist():
            data = src.read(info)
            suffix = Path(info.filename).suffix.lower()
            if not _is_text_member(info.filename) or (suffix == ".dat" and _looks_binary(data)):
                new = None
            else:
                new = _scrub_bytes(data, strict=suffix == "")
            if new is not None:
                changed += 1
                data = new
            dst.writestr(info, data)
    if changed:
        path.write_bytes(buf.getvalue())
    return changed


#: What a truncated or corrupt archive, or a failing disk, raises while it is read or rewritten.
UNREADABLE = (zipfile.BadZipFile, zipfile.LargeZipFile, zlib.error, EOFError, OSError, ValueError)


def scrub_tree(root: Path) -> dict[str, int]:
    """Scrubs every archive and text file under `root`. A file that cannot be scrubbed is deleted
    (fail-closed) and counted in `failed`; the walk goes on."""
    counts = {"files": 0, "changed": 0, "failed": 0}
    for path in sorted(p for p in root.rglob("*") if p.is_file() and not p.is_symlink()):
        suffix = path.suffix.lower()
        if suffix not in TEXT_SUFFIXES and suffix != ".zip":
            continue
        counts["files"] += 1
        try:
            if suffix == ".zip":
                counts["changed"] += scrub_zip(path)
            else:
                new = _scrub_bytes(path.read_bytes())
                if new is not None:
                    path.write_bytes(new)
                    counts["changed"] += 1
        except UNREADABLE as exc:
            counts["failed"] += 1
            print(
                f"::warning title=ga-regression scrub::{path.name}: could not be scrubbed"
                f" ({type(exc).__name__}); deleted so it is never uploaded"
            )
            path.unlink(missing_ok=True)
    return counts


def _seeds() -> list[str]:
    # Low-entropy, obviously fake values, built at run time (no key-shaped literal in the repo).
    kinds = (
        "auth",
        "cookie",
        "body",
        "key",
        "jar",
        "map",
        "query",
        "form",
        "uri",
        "invite",
        "typed",
        "keyboard",
        "log",
        "snapshot",
        "aria",
        "ariajson",
        "dat",
        "source",
        "attr",
        "textarea",
        "userinfo",
        "html",
    )
    return [f"seeded-{kind}-value-{n}" for n, kind in enumerate(kinds)]


#: A numeric credential seed (a one-time code), checked as digits.
_NUMERIC_SEED = 271828


def self_test() -> list[str]:
    """Seeds every form into a trace archive and a HAR, scrubs, returns the seeds still present."""
    seeds = _seeds()
    auth, cookie, body, key, jar, hmap, query, form, uri, invite, typed = seeds[:11]
    keyboard, log, snapshot, aria, ariajson, dat, source = seeds[11:18]
    attr, textarea, userinfo, html = seeds[18:]
    headers = [
        {"name": "Authorization", "value": f"Bearer {auth}"},
        {"name": "cookie", "value": f"sid={cookie}"},
        {"name": "x-demo-api-key", "value": key},
        {"name": "accept", "value": "application/json"},
    ]
    request = {
        "url": f"http://127.0.0.1:4173/invite/{invite}?token={query}&page=2",
        "headers": headers,
        "cookies": [{"name": "cv_jar", "value": jar}],
        "postData": json.dumps({"password": body, "otp": _NUMERIC_SEED}),
    }
    network = json.dumps(
        {
            "type": "resource-snapshot",
            "snapshot": {
                "request": request,
                "response": {"headers": [{"name": "Set-Cookie", "value": f"sid={cookie}"}]},
            },
        }
    )
    events = [
        {"type": "before", "method": "fill", "params": {"selector": "#otp", "value": typed}},
        # The shapes a Playwright 1.64 trace records for a typed credential.
        {"type": "before", "class": "Page", "method": "keyboardType", "params": {"text": keyboard}},
        {"type": "log", "callId": "c@1", "message": f'  fill("{log}")'},
        {
            "type": "frame-snapshot",
            "snapshot": {"html": ["INPUT", {"__playwright_value_": snapshot, "type": "password"}]},
        },
        # React copies a controlled field's value into the `value` attribute (a textarea's into
        # its text child); the recorded node shape is `["INPUT",{...,"value":"..."}]`.
        {
            "type": "frame-snapshot",
            "snapshot": {
                "html": [
                    "FORM",
                    {},
                    ["INPUT", {"__playwright_value_": "", "name": "pw", "value": attr}],
                    ["TEXTAREA", {"name": "note"}, textarea],
                ]
            },
        },
        {"type": "after", "result": {"snapshot": f'- textbox "Code" [ref=e6]: "{ariajson}"'}},
        {
            "type": "before",
            "method": "evaluateExpression",
            "params": {"expression": f'() => post({{ password: "{source}" }})'},
        },
        {"type": "route", "headers": {"authorization": hmap, "accept": "text/html"}},
        {"type": "console", "text": f"enrol otpauth://totp/CV:ann?secret={uri}&issuer=CV"},
        {"type": "console", "text": f"GET http://ann:{userinfo}@127.0.0.1:4173/"},
    ]
    trace = "\n".join(json.dumps(e) for e in events) + "\n"
    har = json.dumps(
        {
            "log": {
                "entries": [
                    {
                        "request": {
                            "headers": headers,
                            "postData": {"text": f"username=ann&password={form}"},
                        }
                    }
                ]
            }
        },
        indent=2,
    )
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        with zipfile.ZipFile(root / "trace.zip", "w") as z:
            z.writestr("trace.network", network + "\n")
            z.writestr("trace.trace", trace)
            z.writestr("resources/0a1b2c", json.dumps({"recovery_codes": [body, key]}))
            z.writestr("resources/3d4e5f.dat", f"username=ann&password={dat}")
            z.writestr("resources/page.png", b"\x89PNG\r\n\x1a\n" + auth.encode())
            z.writestr("resources/f00d.html", f'<form><input name=pw value="{html}"></form>')
        (root / "network.har").write_text(har, encoding="utf-8")
        context = f'Authorization: Bearer {auth}\n- textbox "Password" [ref=e4]: {aria}\n'
        (root / "error-context.md").write_text(context, encoding="utf-8")
        counts = scrub_tree(root)
        if counts["failed"]:
            return ["a seeded artefact could not be scrubbed"]
        texts = [(root / "network.har").read_text(encoding="utf-8")]
        texts.append((root / "error-context.md").read_text(encoding="utf-8"))
        with zipfile.ZipFile(root / "trace.zip") as z:
            texts += [
                z.read(n).decode()
                for n in (
                    "trace.network",
                    "trace.trace",
                    "resources/0a1b2c",
                    "resources/3d4e5f.dat",
                    "resources/f00d.html",
                )
            ]
            if z.read("resources/page.png")[:8] != b"\x89PNG\r\n\x1a\n":
                return ["binary member changed"]
        if "application/json" not in texts[0] or "text/html" not in texts[3]:
            return ["a non-sensitive header was scrubbed"]
    joined = "\n".join(texts)
    left = [s for s in seeds if s in joined]
    return left + ([str(_NUMERIC_SEED)] if str(_NUMERIC_SEED) in joined else [])


def main(argv: Sequence[str] | None = None) -> int:
    p = argparse.ArgumentParser(description=__doc__.split("\n", 1)[0])
    p.add_argument("dirs", nargs="*", type=Path)
    p.add_argument("--self-test", action="store_true")
    args = p.parse_args(argv)
    if args.self_test:
        left = self_test()
        if left:
            print(f"::error title=ga-regression scrub::self-test left {len(left)} seeded value(s)")
            return 1
        print("scrub self-test: every seeded credential form was removed")
    if not args.dirs and not args.self_test:
        p.print_usage()
        return 2
    failed = 0
    for d in args.dirs:
        if d.is_dir():
            c = scrub_tree(d)
            failed += c["failed"]
            print(
                f"scrubbed {d}: {c['changed']} changed of {c['files']} text files/archives,"
                f" {c['failed']} unreadable (deleted)"
            )
        else:
            print(f"{d}: no such directory (nothing to scrub)")
    if failed:
        print(
            f"::error title=ga-regression scrub::{failed} file(s) could not be scrubbed; the upload"
            " steps are skipped (fail-closed)"
        )
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
