#!/usr/bin/env python3
"""E47-Q04: strip secrets from the a11y reports before they are uploaded or summarised.

axe and Lighthouse embed the HTML of the offending node and the page text, and the keyboard and tree
collectors write the accessible names. A stubbed form can carry an API key, a request signature, a
CandleViewer token, a recovery code, a TOTP secret or code, a session id in a URL or an email address;
none of them may reach an artifact or the job summary (C-2.7, C-12.2).

The shapes follow `.gitleaks.toml` (the Bybit key/secret, signature and X-BAPI-* rules, the `cvs_` /
`cvr_` / `cvi_` tokens, recovery codes, TOTP secrets) and widen them where a report differs from
source: no `\\b` around a token (a `_` is a word character, so `\\bcvs_` misses `x_cvs_...`, and a
trailing `-` defeats a closing `\\b`), spaced base32, URL parameters and labelled one-time codes.

Every regular file under the directory is rewritten in place; JSON keeps its shape, and both its
values and its keys are redacted. A file with a suffix this tool cannot read as text (an image, a
trace, a zip) fails the run rather than being uploaded unread. Stdlib only.

Usage: python -m tools.a11y.redact reports/a11y      (rewrite a directory)
       python -m tools.a11y.redact -                  (filter stdin to stdout)
"""

from __future__ import annotations

import json
import re
import sys
from pathlib import Path

REDACTED = "[redacted]"
TEXT_SUFFIXES = frozenset(
    {".json", ".txt", ".html", ".htm", ".md", ".log", ".csv", ".xml", ".svg", ".css", ".js", ".mjs"}
)
EXIT_OK, EXIT_UNREADABLE = 0, 3

# --- names that mark a value as secret ---------------------------------------------------------

_NAME = r"(?:api[-_ ]?key|api[-_ ]?secret|secret|token|password|passwd|totp|otp|one[-_]?time|recovery)"
# As an input's name/id/type/label the bare word `code` is a secret too; as a JSON key it is a rule id.
_ATTR_NAME = r"(?:" + _NAME + r"|code|session|sid)"
_KEY_RE = re.compile(
    r"(?i)(?:^|[-_ .])(?:api[-_ ]?key|api[-_ ]?secret|secret|token|password|passwd|totp|otp|"
    r"sign|signature|authorization|cookie|set-cookie|session|sid|recovery[-_]?codes?|"
    r"x-bapi-[a-z-]+|email)(?:$|[-_ .])"
)

_ATTR_BEFORE = re.compile(
    r"""(?P<pre>(?:name|id|type|autocomplete|data-testid|aria-label|placeholder)\s*=\s*["'][^"']*"""
    rf"""{_ATTR_NAME}[^"']*["'][^>]*?\bvalue\s*=\s*["'])[^"']*""",
    re.I,
)
_ATTR_AFTER = re.compile(
    r"""(?P<pre>\bvalue\s*=\s*["'])[^"']*(?P<post>["'][^>]*?(?:name|id|type|autocomplete|data-testid|aria-label|placeholder)"""
    rf"""\s*=\s*["'][^"']*{_ATTR_NAME})""",
    re.I,
)

# --- value shapes ------------------------------------------------------------------------------

_B32_SPACED = r"[A-Z2-7]{4}(?:[ -][A-Z2-7]{4}){3,}"
_PATTERNS: tuple[re.Pattern[str], ...] = (
    # Bybit: key/secret fields, HMAC signature, X-BAPI-* headers (gitleaks rules, any quoting)
    re.compile(r"""(?i)(?:api[-_ ]?key|api[-_ ]?secret)["']?\s*[:=]\s*["']?[A-Za-z0-9]{12,}"""),
    re.compile(r"""(?i)["']?sign(?:ature)?["']?\s*[:=]\s*["']?[A-Fa-f0-9]{24,}"""),
    re.compile(r"""(?i)x-bapi-[a-z-]+["']?\s*[:=]\s*["']?[A-Za-z0-9+/=_-]{8,}"""),
    # CandleViewer tokens: no \b either side (see the module doc)
    re.compile(r"cv[srin]_[A-Za-z0-9_-]{20,}"),
    # recovery codes, labelled lists and bare ABCDE-FGHIJ groups
    re.compile(
        r"""(?i)recovery[-_ ]?codes?["']?\s*[:=]?\s*["'\[(]*[A-Z2-7]{5}-[A-Z2-7]{5}"""
        r"""(?:["']?\s*[,;]?\s*["']?[A-Z2-7]{5}-[A-Z2-7]{5})*"""
    ),
    re.compile(r"(?<![A-Z2-7-])[A-Z2-7]{5}-[A-Z2-7]{5}(?![A-Z2-7-])"),
    # TOTP secrets: labelled (plain or spaced base32), otpauth secret=, bare spaced base32 groups
    re.compile(
        r"""(?i)(?:totp[-_ ]?secret|secret[-_ ]?key|setup[-_ ]?key|manual[-_ ]?(?:entry|key)|"""
        rf"""authenticator[-_ ]?(?:secret|key))["']?\s*[:=]?\s*["']?(?:{_B32_SPACED}|[A-Za-z2-7]{{16,}})"""
    ),
    re.compile(r"(?i)secret=[A-Za-z2-7]{16,}"),
    re.compile(rf"(?<![A-Za-z0-9]){_B32_SPACED}(?![A-Za-z0-9])"),
    # generic credentials
    re.compile(r"[A-Za-z0-9._%+-]+@[A-Za-z0-9-]+(?:\.[A-Za-z0-9-]+)+"),
    re.compile(r"\b(?:sk|pk|rk)[-_][A-Za-z0-9_-]{16,}"),
    re.compile(r"\bBearer\s+[A-Za-z0-9._~+/=-]{16,}"),
    re.compile(r"\beyJ[A-Za-z0-9_-]{8,}\.[A-Za-z0-9_-]{8,}\.[A-Za-z0-9_-]*"),
)
_ASSIGN = re.compile(
    rf"""(?P<k>["']?{_NAME}[A-Za-z_-]*["']?\s*[:=]\s*["']?)(?P<v>[A-Za-z0-9._~+/=-]{{4,}})""", re.I
)
# ?session=, &sid=, ;jsessionid=, ?token=, ...: keep the parameter name, drop the value
_URL_PARAM = re.compile(
    r"(?i)(?P<k>[?&;#](?:session(?:[-_]?id)?|jsessionid|sid|(?:access|refresh|id|auth|invite|api)?[-_]?token|"
    r"api[-_]?key|key|secret|auth|signature|sig|code|otp|totp|email|jwt)=)[^&#\s\"'<>]+"
)
# a six-digit code (123456 or 123 456) after an authentication-code label, across markup
_CODE_LABEL = re.compile(
    r"(?is)(?P<k>(?:authenticat\w*|verification|security|one[-_ ]?time|auth|mfa|2fa|totp|otp)[-_ ]*"
    r"(?:code|token|password)|\bcode\b)(?P<gap>.{0,200}?)(?<![\d.])(?P<v>\d{3}[ -]?\d{3})(?![\d.])"
)
_BARE_FULL = re.compile(r"(?=.*\d)(?=.*[A-Za-z])[A-Za-z0-9]{18,}")  # a whole value that looks like a key
_B32_FULL = re.compile(r"[A-Z2-7]{16,}")


def redact_text(text: str) -> str:
    """Redact one string: credentials by shape, by label and by URL parameter."""
    text = _ATTR_BEFORE.sub(lambda m: m.group("pre") + REDACTED, text)
    text = _ATTR_AFTER.sub(lambda m: m.group("pre") + REDACTED + m.group("post"), text)
    text = _URL_PARAM.sub(lambda m: m.group("k") + REDACTED, text)
    text = _CODE_LABEL.sub(lambda m: m.group("k") + m.group("gap") + REDACTED, text)
    for pat in _PATTERNS:
        text = pat.sub(REDACTED, text)
    return _ASSIGN.sub(lambda m: m.group("k") + REDACTED, text)


def _redact_all(node: object) -> object:
    """Every string under a secret-named key, whatever it looks like."""
    if isinstance(node, str):
        return REDACTED
    if isinstance(node, list):
        return [_redact_all(v) for v in node]
    if isinstance(node, dict):
        return {k: _redact_all(v) for k, v in node.items()}
    return node


def _redact_value(s: str) -> str:
    out = redact_text(s)
    if out == s and (_BARE_FULL.fullmatch(s) or _B32_FULL.fullmatch(s)):
        return REDACTED
    return out


def _redact_key(key: str) -> str:
    return redact_text(key)


def redact_json(node: object) -> object:
    """Redact JSON values and keys; a value under a secret-named key is replaced whole."""
    if isinstance(node, str):
        return _redact_value(node)
    if isinstance(node, list):
        return [redact_json(v) for v in node]
    if isinstance(node, dict):
        out: dict[str, object] = {}
        for k, v in node.items():
            nk = _redact_key(str(k))
            if nk in out:  # two keys redacted to the same text: keep both, distinguishable
                nk = f"{nk}#{len(out)}"
            out[nk] = _redact_all(v) if _KEY_RE.search(str(k)) else redact_json(v)
        return out
    return node


class UnreadableReport(Exception):
    """A file the tool cannot read as text: it must not be uploaded unredacted."""


def redact_dir(root: str | Path) -> list[str]:
    """Rewrite every regular file under root; return those that changed.

    Raises UnreadableReport for a suffix outside TEXT_SUFFIXES or a file that is not UTF-8.
    """
    files = [p for p in sorted(Path(root).rglob("*")) if p.is_file() or p.is_symlink()]
    bad = [str(p) for p in files if p.is_symlink() or p.suffix.lower() not in TEXT_SUFFIXES]
    if bad:
        raise UnreadableReport(
            "A11Y-INFRA redaction cannot read (unknown suffix or link), so these would be uploaded "
            "unredacted: " + ", ".join(bad)
        )
    changed: list[str] = []
    for path in files:
        try:
            raw = path.read_text(encoding="utf-8")
        except UnicodeDecodeError as exc:
            raise UnreadableReport(f"A11Y-INFRA redaction cannot read {path}: {exc}") from exc
        out = raw
        if path.suffix.lower() == ".json":
            try:
                data = json.loads(raw)
            except json.JSONDecodeError:
                out = redact_text(raw)
            else:
                clean = redact_json(data)
                if clean != data:
                    out = json.dumps(clean, indent=2, ensure_ascii=False)
        else:
            out = redact_text(raw)
        if out != raw:
            path.write_text(out, encoding="utf-8")
            changed.append(str(path))
    return changed


def main(argv: list[str] | None = None) -> int:
    argv = sys.argv[1:] if argv is None else argv
    if argv == ["-"]:
        sys.stdout.write(redact_text(sys.stdin.read()))
        return EXIT_OK
    if len(argv) != 1 or not Path(argv[0]).is_dir():
        print("usage: python -m tools.a11y.redact <report-dir> | -", file=sys.stderr)
        return EXIT_UNREADABLE
    try:
        changed = redact_dir(argv[0])
    except UnreadableReport as exc:
        print(exc, file=sys.stderr)
        return EXIT_UNREADABLE
    print(f"a11y redact: {len(changed)} file(s) rewritten")
    return EXIT_OK


if __name__ == "__main__":
    sys.exit(main())
