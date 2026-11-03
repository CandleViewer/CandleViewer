#!/usr/bin/env python3
"""E47-Q04: strip secrets from the a11y reports before they are uploaded as artifacts.

axe, pa11y and Lighthouse embed the HTML of the offending node and the page text. A stubbed form can
carry an API-key-like value, a TOTP code or an email address; none of them may reach an artifact
(C-2.7, C-12.2). Every string in every `*.json` / `*.txt` / `*.html` file under the directory is
rewritten in place; JSON keeps its shape. Stdlib only.

Usage: python -m tools.a11y.redact reports/a11y
"""

from __future__ import annotations

import json
import re
import sys
from pathlib import Path

REDACTED = "[redacted]"

# An input's value / a field named like a secret: `name="otp" value="123456"`, `"apiKey": "..."`.
_SECRET_NAME = r"(?:api[-_]?key|api[-_]?secret|secret|token|password|passwd|totp|otp|one[-_]?time)"
# As an input's name/id the bare word `code` is a secret too; as a JSON key it is a rule id.
_SECRET_ATTR = r"(?:" + _SECRET_NAME + r"|code)"
_ATTR_RE = re.compile(
    rf"""(?P<pre>(?:name|id|autocomplete|data-testid|aria-label)\s*=\s*["'][^"']*{_SECRET_ATTR}[^"']*["'][^>]*?\bvalue\s*=\s*["'])[^"']*""",
    re.I,
)
_ATTR_REV_RE = re.compile(
    rf"""(?P<pre>\bvalue\s*=\s*["'])[^"']*(?P<post>["'][^>]*?(?:name|id|autocomplete|data-testid|aria-label)\s*=\s*["'][^"']*{_SECRET_ATTR})""",
    re.I,
)
_PATTERNS: tuple[re.Pattern[str], ...] = (
    re.compile(r"[A-Za-z0-9._%+-]+@[A-Za-z0-9-]+(?:\.[A-Za-z0-9-]+)+"),  # email
    re.compile(r"\b(?:sk|pk|rk)[-_][A-Za-z0-9_-]{16,}\b"),  # prefixed API keys
    re.compile(r"\b[A-Za-z0-9]{18,}\b(?=\s*$)"),  # bare long token at end of a value
    re.compile(r"\bBearer\s+[A-Za-z0-9._~+/=-]{16,}"),
    re.compile(r"\beyJ[A-Za-z0-9_-]{8,}\.[A-Za-z0-9_-]{8,}\.[A-Za-z0-9_-]*"),  # JWT
    re.compile(r"\b[A-Z2-7]{16,32}\b(?=\s*$)"),  # base32 TOTP seed
)
_ASSIGN_RE = re.compile(
    rf"""(?P<k>["']?{_SECRET_NAME}[A-Za-z_-]*["']?\s*[:=]\s*["']?)(?P<v>[A-Za-z0-9._~+/=-]{{4,}})""",
    re.I,
)
_TOTP_RE = re.compile(r"(?<![\d.])\d{6}(?![\d.])")


def redact_text(text: str) -> str:
    """Redact one string: emails, key-like tokens, secret-named assignments and attribute values."""
    text = _ATTR_RE.sub(lambda m: m.group("pre") + REDACTED, text)
    text = _ATTR_REV_RE.sub(lambda m: m.group("pre") + REDACTED + m.group("post"), text)
    text = _ASSIGN_RE.sub(lambda m: m.group("k") + REDACTED, text)
    for pat in _PATTERNS:
        text = pat.sub(REDACTED, text)
    # a six-digit code only where the text also names a code / otp / totp field
    if re.search(r"otp|totp|one[-_ ]?time|verification code|authenticator", text, re.I):
        text = _TOTP_RE.sub(REDACTED, text)
    return text


def redact_json(node: object) -> object:
    if isinstance(node, str):
        return redact_text(node)
    if isinstance(node, list):
        return [redact_json(v) for v in node]
    if isinstance(node, dict):
        return {k: redact_json(v) for k, v in node.items()}
    return node


def redact_dir(root: str | Path) -> list[str]:
    """Rewrite every report under root; return the files that changed."""
    changed: list[str] = []
    for path in sorted(Path(root).rglob("*")):
        if not path.is_file() or path.suffix not in (".json", ".txt", ".html"):
            continue
        raw = path.read_text(encoding="utf-8", errors="replace")
        out = raw
        if path.suffix == ".json":
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
    if len(argv) != 1 or not Path(argv[0]).is_dir():
        print("usage: python -m tools.a11y.redact <report-dir>", file=sys.stderr)
        return 3
    changed = redact_dir(argv[0])
    print(f"a11y redact: {len(changed)} file(s) rewritten")
    return 0


if __name__ == "__main__":
    sys.exit(main())
