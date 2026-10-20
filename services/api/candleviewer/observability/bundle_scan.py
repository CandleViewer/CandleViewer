"""Pre-write secret scan for the support bundle (E04-S02, SR-124, threat K1/D3).

A gitleaks-style rule set (gitleaks itself is not a runtime dependency) plus a
labelled-secret rule built from the E04-T01 redaction key names. A finding
carries the file and rule name only - never the matched value.
"""

from __future__ import annotations

import re
from collections.abc import Iterator
from dataclasses import dataclass
from pathlib import Path
from typing import Final

from candleviewer.observability.redaction import _JWT_RE, _KEY_NAMES, _NO_VALUE, _NOT_DOTTED


@dataclass(frozen=True)
class Finding:
    file: str
    rule: str


#: `api_secret=ABC...` / `"password": "ABC..."`, each key name with `-` and `_` alike; what
#: the redaction writes for a value (a marker, the end of a cut text) or a placeholder is fine.
#: The log buffer writes a line break as `\n` (#415): a label after one, or with one before its
#: value, is read as on one line, so a label and its value on two lines are found. The space after
#: the separator is possessive: an escaped `\t` given back would read as a value.
_LABELLED = re.compile(rf"""(?ix)["']?(?:\b|(?<=\\[tnr])){_NOT_DOTTED}(?:{_KEY_NAMES})["']?
    \s*[:=](?:\s|\\[tnr])*+["']?{_NO_VALUE}[^\s"',}}\]]{{6,}}""")
_RULES: Final[tuple[tuple[str, re.Pattern[str]], ...]] = (
    ("private-key-block", re.compile(r"-----BEGIN [A-Z ]*PRIVATE KEY-----")),
    ("aws-access-key-id", re.compile(r"\b(?:AKIA|ASIA)[0-9A-Z]{16}\b")),
    (
        "github-token",
        re.compile(r"\b(?:gh[pousr]_[A-Za-z0-9]{30,}|github_pat_[A-Za-z0-9_]{30,})\b"),
    ),
    ("slack-token", re.compile(r"\bxox[abprs]-[A-Za-z0-9-]{10,}\b")),
    ("generic-api-key-prefix", re.compile(r"\bsk-[A-Za-z0-9]{20,}\b")),
    ("bearer-token", re.compile(r"(?i)\bbearer\s+[A-Za-z0-9._~+/=-]{16,}")),
    ("jwt", re.compile(rf"\b{_JWT_RE}\b")),
    ("labelled-secret", _LABELLED),
)


def scan_text(text: str) -> Iterator[str]:
    """Yield the rule name of each rule that matches `text` (once per rule)."""
    for name, pattern in _RULES:
        if pattern.search(text):
            yield name


def scan_file(path: Path, rel: str) -> list[Finding]:
    """Scan one file line by line (bounded memory); one finding per rule."""
    seen: set[str] = set()
    with path.open("r", encoding="utf-8", errors="replace") as fh:
        for line in fh:
            seen.update(scan_text(line))
    return [Finding(rel, rule) for rule in sorted(seen)]


def scan_tree(root: Path) -> list[Finding]:
    findings: list[Finding] = []
    for path in sorted(p for p in root.rglob("*") if p.is_file()):
        findings.extend(scan_file(path, path.relative_to(root).as_posix()))
    return findings
