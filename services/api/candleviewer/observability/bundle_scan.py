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

from candleviewer.observability.redaction import (
    _DOUBLED_DQ,
    _DOUBLED_SQ,
    _JWT_RE,
    _KEY_NAMES,
    _LABEL_SPACE,
    _LABEL_START,
    _NO_VALUE,
    _NOT_DOTTED,
    _SPACE_ESCAPE,
    _TO_LINE_END,
)


@dataclass(frozen=True)
class Finding:
    file: str
    rule: str


#: What may come between a label's separator and its value (#4713): escapes (a run of `\`, with an
#: escaped whitespace character's letter or code and whitespace after it or not: `\\n`, `\x0b `)
#: and quotes, each
#: escaped, doubled or not (`\'`, `\\'`, `''`). The filter reads them as the start of a value or as
#: its quotes; the scan reads past them, and past whitespace after a doubled quote, as the filter
#: reads such a value (`_DOUBLED_DQ`, `_DOUBLED_SQ`).
#: A doubled quote as the log buffer escapes it (`\'\'`, `\\"\\"`), and whitespace after it, where a
#: value and a closing one follow on the line, as the filter reads such a value; `{q}` is the quote.
#: A run is read from its start only (the look-behinds), so a long run is read once.
_ESCAPED_DOUBLED: Final = (
    r"""(?<![\\{q}])(?:\\++{q}){{2,}}+(?=\s*+[^\s"'\\][^\n]*?(?:\\++{q}){{2}})\s*+"""
)
_VALUE_LEAD: Final = (
    rf"""(?:(?<!")"{{2,}}+(?={_DOUBLED_DQ})[\s']*+|(?<!')'{{2,}}+(?={_DOUBLED_SQ})[\s"]*+"""
    rf"""|{_ESCAPED_DOUBLED.format(q='"')}|{_ESCAPED_DOUBLED.format(q="'")}"""
    rf"""|\\++(?:{_SPACE_ESCAPE}\s*+)?|["'])"""
)
#: `api_secret=ABC...` / `"password": "ABC..."`, each key name with `-` and `_` alike; what
#: the redaction writes for a value (a marker, the end of a cut text) or a placeholder is fine.
#: The log buffer writes a line break as `\n` (#415): a label after one, or with one before its
#: value, is read as on one line, so a label and its value on two lines are found. The space after
#: the separator is possessive: an escaped `\t` given back would read as a value. A quote that the
#: buffer escapes (`\'`, `\"`) before a value reads as a quote, as the filter reads it (#415).
#: A label starts where the filter's starts (`_LABEL_START`: after any escaped whitespace
#: character), its name may be in doubled quotes (`""token"":`), and `_VALUE_LEAD` comes before its
#: value, as the filter reads them; the `lead` group is where they start. A `_TO_LINE_END` name's
#: value is read as the filter reads it, to the line's end, spaces and quotes included (#4713).
_LABELLED = re.compile(rf"""(?ix)["']?{_LABEL_START}{_NOT_DOTTED}(?:{_KEY_NAMES})
    (?P<line>{_TO_LINE_END})?["']{{0,2}}{_LABEL_SPACE}(?P<lead>{_VALUE_LEAD}*){_NO_VALUE}
    (?:(?(line)[^\n]|[^\s"',}}\]])){{6,}}""")


def _six_character_head(rule: re.Pattern[str]) -> re.Pattern[str]:
    """`rule`, whose value is six or more characters, with a value of exactly six."""
    head = rule.pattern.removesuffix("{6,}")
    if head == rule.pattern:
        raise ValueError("the rule's value is not six or more characters")
    return re.compile(head + "{6}", rule.flags)


#: `_LABELLED` with a value of exactly six characters: the same matches start at the same places,
#: and a search costs no more than the six characters past a value's start.
_LABELLED_HEAD: Final = _six_character_head(_LABELLED)
#: The log buffer `repr`s a text the redaction wrote (a traceback, a stack, an event dict's value),
#: so `password:\n[redacted:key-name]` reaches the scan as `password:\\n[redacted:key-name]`, its
#: escape doubled (#4681). A value that is escapes and quotes (`_VALUE_LEAD`, #4713) and then a
#: marker or a placeholder, as `_NO_VALUE` names them, holds no value.
_ESCAPE_RUN: Final = re.compile(f"{_VALUE_LEAD}*+", re.IGNORECASE)
#: `_NO_VALUE` is a negative lookahead: it matches (the empty string) where no marker or
#: placeholder starts, so a match means the text there holds a value.
_HOLDS_VALUE: Final = re.compile(_NO_VALUE, re.IGNORECASE)
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
)


def _labelled(text: str) -> bool:
    """`_LABELLED` finds a value that is not a marker after the buffer's doubled escapes.

    The escapes and quotes are read from where they start (#4713), so a match that starts its value
    inside one (the `n` of `\\n`) is read as the whole escape and what follows it.
    """
    pos = 0
    while (match := _LABELLED_HEAD.search(text, pos)) is not None:
        pos = match.start("lead")
        escapes = _ESCAPE_RUN.match(text, pos)  # it matches here, if only the empty string
        pos = escapes.end() if escapes else pos
        if _HOLDS_VALUE.match(text, pos):
            return True
    return False


def scan_text(text: str) -> Iterator[str]:
    """Yield the rule name of each rule that matches `text` (once per rule)."""
    for name, pattern in _RULES:
        if pattern.search(text):
            yield name
    if _labelled(text):
        yield "labelled-secret"


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
