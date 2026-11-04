"""E47-T05 (#1360): the one home of the host, address, key and id patterns the a11y register tools share.

`conformance.py` scans every string leaf of the limitations register and the generated report with
them; `register.py` scans a sign-off name with them. Stdlib only. Messages built from a match must
name the class and the path, never the value.
"""

from __future__ import annotations

import re

#: Any scheme (`ftp://`, `wss://`), a scheme-relative `//name`, and the named host forms; any case.
URL_RE = re.compile(
    r"\b[a-z][a-z0-9+.-]*://|(?<![\w:/])//[a-z0-9]|www\.|/home/|localhost|\.local\b"
    r"|\b[a-z0-9-]+\.(?:com|io|org|net)\b",
    re.IGNORECASE,
)
KEYLIKE_RE = re.compile(r"[A-Za-z0-9+/=_-]{24,}")
IMAGE_RE = re.compile(r"!\[|<img|\.png\b|\.svg\b", re.IGNORECASE)
IDLIKE_RE = re.compile(r"\b\d{6,}\b|\bUID\b")

EMAIL_RE = re.compile(r"[\w.+-]+@[\w-]+(?:\.[\w-]+)+")
_OCTET = r"(?:25[0-5]|2[0-4]\d|1\d\d|[1-9]?\d)"
IPV4_RE = re.compile(rf"(?<![\w.]){_OCTET}(?:\.{_OCTET}){{3}}(?![\w]|\.\d)")
_H = r"[0-9A-Fa-f]{1,4}"
IPV6_RE = re.compile(
    rf"(?<![\w:])(?:(?:{_H}:){{7}}{_H}|(?:{_H}:){{1,7}}:(?:{_H}(?::{_H}){{0,6}})?|::(?:{_H}:){{0,6}}{_H})(?![\w:])"
)
#: File and document extensions that read as a top-level domain but name a file, not a host.
FILE_SUFFIXES = (
    "json|md|mdx|py|pyi|ts|tsx|js|jsx|mjs|cjs|yml|yaml|toml|txt|lock|css|scss|html|htm|sh|sql|"
    "csv|xml|ini|cfg|log|pdf|map|snap|rs|go|ipynb|tf|conf|env|gz|zip"
)
#: A dotted name ending in letters: any top-level domain (`example.dev`, `a.b.example.zone`), any case.
HOST_RE = re.compile(
    rf"(?<![\w@./-])(?:[A-Za-z0-9](?:[A-Za-z0-9-]*[A-Za-z0-9])?\.)+(?!(?:{FILE_SUFFIXES})\b)[a-z]{{2,}}(?![\w-])",
    re.IGNORECASE,
)

#: Host, address, key-like or id strings (a sign-off name is checked against all of them).
#: Each part keeps its own case rule (a scoped flag group), so the join matches what the parts do.
LEAK_RE = re.compile(
    "|".join(
        f"(?{'i' if r.flags & re.IGNORECASE else ''}:{r.pattern})"
        for r in (URL_RE, HOST_RE, EMAIL_RE, IPV4_RE, IPV6_RE, KEYLIKE_RE, IDLIKE_RE)
    )
)
#: (pattern, what it found), for a content scan of free text.
CONTENT_CHECKS = (
    (URL_RE, "a host"),
    (HOST_RE, "a host"),
    (EMAIL_RE, "an email address"),
    (IPV4_RE, "an IP address"),
    (IPV6_RE, "an IP address"),
    (KEYLIKE_RE, "a key-like string"),
    (IMAGE_RE, "an image"),
    (IDLIKE_RE, "an id"),
)
