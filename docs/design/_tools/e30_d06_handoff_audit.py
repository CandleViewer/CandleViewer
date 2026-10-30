#!/usr/bin/env python3
"""E30-D06 (#919) audit: the engineering hand-off pack for the order ticket.

Standalone, offline, stdlib only; it executes no repo code and runs under `python3 -I`. It reads,
AS TEXT at the pinned base (`git show BASE:<path>`), the plan texts, the merged E30 design docs, the
E09-D09 vocabulary, E32-D06's pattern, the audit registry, the icon registry, the key map, the
shipped CMP-044, the token JSON and the calendar; then the pack (`E30-D06.md`), its copy deck
(`E30-D06-copy.json`), its state inventory (`E30-D06-states.json`) and the pins from the working
tree, and `14` / `15` from the working tree and the merge-base (G-UNTOUCHED).

Values. Every `{{KIND:key}}` outside a code span is COMPUTED: CITE (a figure parsed from its cited
line at the base), COUNT (the pack, the deck, the inventory, the image folder), SPRINT (the
calendar), RULED (R919's own figures). `--fill` writes `VALUE<!--=KIND:key-->`; `--check`
re-derives every anchored value. The gates, each FAIL led by its code:

- [G-ANCHOR] every anchored value equals the tool's; no placeholder left unfilled.
- [G-MARKER] every HTML comment is a value anchor.
- [G-CITE] every `KEY`:line cite resolves at the base to non-blank ends inside the file.
- [G-VERSION] by content, never a file sha: each cited range stands, in order and contiguous,
  somewhere in its file at `origin/main` (a move is fine, an edit FAILs; an unresolvable
  `origin/main` FAILs); the version line names the base and every sha on it is a commit under the
  base; the deck and the inventory carry the pack, version and base.
- [G-QUOTE] every quoted string of QUOTE_MIN+ characters outside a fence is in the deck, a cited
  source of its line, a core source or R919's words.
- [G-DECK] the deck's shape; each key the mechanical form of its first merged key; each source
  text read at its cite (or R919 / A50 for an A50 string; every ruled entry cites A50); each
  example rendering from its template (a renamed slot read back through its `parent`); an
  `amended` entry cites its D05 F row first and its parent string is `not_carried` with that row as
  reason; every quoted string of the source rows an entry or a `not_carried` item with a reason;
  every placeholder a typed, identifier-safe parameter; every announcement's politeness an enum
  with a rate; no side or direction word outside a parameter; the security set flagged.
- [G-ONCE] AC2: no string under two keys (a server-field `{detail}` entry excepted), no merged key
  with two strings on one surface.
- [G-FIXTURE] no board fixture (account, symbol, decimal, time) outside a parameter; a digit
  outside a parameter only where `fixed` lists it.
- [G-CODES] every code registered at the base (`22` slug or rule, preview code, `24` OMS code or
  sizing reason), never a retCode; `by_code` equals the recomputed map, one key per code per
  surface, and its `*` row names each refusal surface's Problem.detail fallback; every refusal
  string has codes, a `codes_pending` row or the fallback role; a code's target sentence names no
  other cause (row 3).
- [G-NATIVE] S-30: `sl.note` equals D02 and E32-D06's S-6 byte for byte; `v.sl.required` is A50
  item 10; the native-SL set is present and flagged, no string over-claims; no inventory record
  gates a carve-out control; the view-as and FREEZE records keep the carve-out enabled; an
  "every order" native-SL string is named in a C-row; the A-row correcting `14`'s SL clause
  carries C-2.6's own scope, read from CONST.
- [G-STATES] both directions: every record has a frame (or "owed (PR 3)", lifted only) and a
  twin that resolves; every `14` / `15` States token is a twin or closed; every parent frame is a
  record; every screen record has a fixture handle and no two repeat each other's cells.
- [G-A11Y] every D05 row id the pack names exists in D05, and D05's AR / T2 / LR / SD sets are
  the ranges §3.2 states; §5's T2 table is T2-01..T2-29, each reason a deck key and each id on a
  record; every key a record `speaks` carries an announcement.
- [G-LEDGER] §4.1: L-1..L-26 in order, the rows of O0847, the disposition vocabulary and R919's
  tally; each row lifted into the deck or a record carries D05's replacement there (F-02 verbatim,
  F-08's `{arm key}`, F-13's template, F-14's label-first names, LR-01, LR-09, LR-24).
- [G-AROW] §12.3: A-1..A-n in order; each Old (or anchor) at its base line and unique in scope.
- [G-UNTOUCHED] PR 1: only the pack's five files differ from `git merge-base HEAD origin/main`;
  PR 2: `14` and `15` equal the merge-base with §12.3 applied, and only the pins may change in
  the pack. Fails closed when git cannot answer.
- [G-TOKENS] every token named in §8 resolves in `packages/ui/tokens` at the base; a request in
  the exceptions table does not.
- [G-HEX] no colour literal anywhere; no px value in §8, the deck or the inventory.
- [G-ICONS] §9 against the registry: every name and description verbatim; every D04 §3.3 name
  listed; a "none" row names a G-row.
- [G-EVENTS] every audited action is registered and its pair named in §10; every unregistered
  event is in the G-ledger; every event of `14`'s lines and D03 §15 is on a record, in G-17 or in
  a C-row (completeness).
- [G-ROWS] C-, G- and Q-rows in order with owners (and due dates); every id referenced exists.
- [G-WALK] §13.2's needs resolve; §13.3's reader row is pending or recorded (pending FAILs under
  `--strict-walk`).
- [G-RULED] the stamp in its sites; R919's words; §6.2 equals the deck's ten A50 entries.
- [G-PUBLIC] by pattern only: no word on the public-text list, local path, host, URL, uuid other
  than the parents' page ids, closing keyword, or agent or session name.
- [G-RULED-PIN] a default-deny pin set over every unit of the spec (heading, table row by its
  lead cell, sentence, fenced block), every deck entry and every inventory record, anchored values
  cut out; `--repin-ruled` is its only writer. When another gate FAILs, its findings print as
  NOTE (the exit status stays 1).

`--a-rows` prints §12.3 as JSON (PR 2's payload); `--self-test` applies at least one mutation per
gate and passes only when each adds exactly one new FAIL with its gate's code, a re-run reproduces
the base result and no file on disk changed. The report is ASCII, every line at most 100 characters.

Usage (from the repo root):
  python3 -I docs/design/_tools/e30_d06_handoff_audit.py --check [--json] [--fill]
  python3 -I docs/design/_tools/e30_d06_handoff_audit.py --check --strict-walk
  python3 -I docs/design/_tools/e30_d06_handoff_audit.py --self-test
  python3 -I docs/design/_tools/e30_d06_handoff_audit.py --repin-ruled
  python3 -I docs/design/_tools/e30_d06_handoff_audit.py --a-rows
Exit 0 = no FAIL; 1 = at least one FAIL.
"""

from __future__ import annotations

import argparse
import datetime
import hashlib
import json
import re
import subprocess
import sys
import unicodedata
from collections.abc import Callable
from dataclasses import dataclass, replace
from functools import cache
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[3]
BASE = "e607a3f104"  # every cite was read here (the version line)
HEAD = "origin/main"  # G-VERSION: a cited range edited at origin/main FAILs
SPEC_REL = "docs/design/E30/E30-D06.md"
DECK_REL = "docs/design/E30/E30-D06-copy.json"
STATES_REL = "docs/design/E30/E30-D06-states.json"
TOOL_REL = "docs/design/_tools/e30_d06_handoff_audit.py"
PINS_REL = "docs/design/_tools/e30_d06_ruled_pins.txt"
OWN_PATHS = (SPEC_REL, DECK_REL, STATES_REL, TOOL_REL, PINS_REL)
P14 = "docs/plan/14-screens-catalogue.md"
P15 = "docs/plan/15-component-catalogue.md"
TARGETS = {"14": P14, "15": P15}
IMG_REL = "docs/design/E30/img"
DS_JSON_DIR = "packages/ui/tokens"
TICKET = "E30-D06"
RULING_ID = "6528489355"
BQ_LIST_ID = "6528033284"
A50_ID = "6528462939"
REPORT_WIDTH = 100
QUOTE_MIN = 12
E30 = "docs/design/E30/E30-"
KEYS: dict[str, str] = {
    "02": "docs/plan/02-definition-of-ready-done.md",
    "05": "docs/plan/05-accessibility-standard.md",
    "06": "docs/plan/06-performance-and-load-standard.md",
    "14": P14,
    "15": P15,
    "16": "docs/plan/16-design-system-brief.md",
    "22": "docs/plan/22-api-openapi.yaml",
    "24": "docs/plan/24-internal-schemas.md",
    "28": "docs/plan/28-statechart-catalogue.md",
    "D02": E30 + "D02.md",
    "D03": E30 + "D03.md",
    "D03H": E30 + "D03-handoff.md",
    "D04": E30 + "D04.md",
    "D04H": E30 + "D04-handoff.md",
    "D05": E30 + "D05.md",
    "E09-D09": "docs/design/E09/E09-D09.md",
    "E32D06": "docs/design/E32/E32-D06.md",
    "README": "docs/design/README.md",
    "CONST": "CONSTITUTION.md",
    "DS": ".claude/rules/32-design-specs.md",
    "ACT": "services/api/candleviewer/audit/actions.py",
    "ICONS": "packages/ui/src/icons/registry.ts",
    "KM": "apps/web/src/keymap/keymap.json",
    "CD": "packages/ui/src/components/ConfirmDialog.tsx",
    "CAL": "docs/plan/backlog/_tools/calendar_cv.py",
    "E30J": "docs/plan/backlog/E30.json",
}
# the version line: every sha on it (a commit under the base)
PAGES = (
    "E30-D02",
    "E30-D03 Confirmation, rejection, defaults and selector",
    "E30-D04 Trading ticket DS and motion",
)
RULED_VALUES = {"RULED:bq.total": "31", "RULED:bq.byname": "11"}
# R919's own words, cited by the pack (G-QUOTE, G-RULED)
RULING_QUOTES = (
    "the exchange holds the stop",
    "Every position-opening order requires a stop-loss.",
)
STAMP = (
    "RULED (orchestrator, 2026-10-30, #919 ruling of record — 6528033284's answer; A50 for the "
    "deck's ruled strings)"
)
A50: dict[int, tuple[str, str]] = {
    1: (
        "ticket.order.defaults.unavailable",
        "Your trading defaults could not be loaded — the ticket uses your profile's values.",
    ),
    2: (
        "ticket.defaults.limit.unavailable",
        "Limit unavailable — checked by the server when you save",
    ),
    3: ("ticket.order.profile.unavailable", "Profile limits unavailable — new orders off."),
    4: ("ticket.defaults.load_error", "Your trading defaults could not be loaded."),
    5: ("ticket.defaults.save_failed", "Not saved — your changes are still here. Try again."),
    6: ("ticket.order.frozen.reason", "Trading frozen by the owner — new orders off."),
    7: ("ticket.order.profile.blocked", "This order is outside your profile."),
    8: ("ticket.order.pending_key.reason", "API key pending — new orders off."),
    9: ("ticket.order.stop_pending.reason", "Protective stop pending — new entries off."),
    10: ("ticket.order.v.sl.required", "Every position-opening order requires a stop-loss."),
}
SURFACES = ("order", "group", "confirm", "reject", "ratelimit", "defaults", "template", "hotkeys")
STATUSES = ("merged", "amended", "ruled", "by-reference")
# the deck's source rows: (cite key, first line, last line, quoted columns)
SOURCE_ROWS = (
    ("D02", 373, 451, (1,)),
    ("D03", 454, 538, (1,)),
    ("D03", 246, 254, (4, 5)),
    ("D03", 264, 266, (2,)),
)
# the ledger of O0847: the 26 rows in order, and R919's tally (BQ-7)
LEDGER_ROWS = tuple(f"F-{n:02d}" for n in range(1, 20)) + (
    "C-i",
    "C-m",
    "C-o",
    "C-p",
    "A-6 (D05)",
    "A-7 (D05)",
    "G-02",
)
TALLY = {
    "fixed by PR 0": 1,
    "lifted": 13,
    "recorded": 5,
    "carried": 2,
    "closed": 1,
    "applied": 1,
    "PR 2": 2,
    "named": 1,
}
NATIVE_ALIASES = (
    "sl.note",
    "sl.holder",
    "sl.reduce_only",
    "accepted",
    "accepted.partial",
    "stop_pending.pending",
    "stop_pending.retrying",
    "stop_pending.unrecoverable",
    "stop_pending.flattened",
    "stop_pending.flatten_now",
    "stop_pending.set_stop",
    "stop_pending.reason",
    "v.sl.required",
    "reason.stop_missing",
)
CARVE_ALIASES = ("stop_pending.flatten_now", "stop_pending.set_stop", "lockout.button")
CARVE_RECORDS = (
    "SCR-060/view-as",
    "SCR-060/view-as-held",
    "SCR-060/frozen",
    "SCR-060/blocked-by-lockout",
    "SCR-060/stop-pending-1",
    "SCR-060/stop-pending-4",
)
LIFTED = (
    "SCR-060/view-as",
    "SCR-060/view-as-held",
    "SCR-060/defaults-unavailable",
    "SCR-060/profile-unavailable",
    "SCR-060/default-above-cap",
    "SCR-114/loading",
    "SCR-114/load-error",
    "SCR-114/save-failed",
    "SCR-114/ceiling-unconfirmed",
    "SCR-077/placement",
)
FIFTEEN = (
    "CMP-100",
    "CMP-101",
    "CMP-102",
    "CMP-103",
    "CMP-105",
    "CMP-107",
    "CMP-119",
    "CMP-121",
    "CMP-122",
    "CMP-130",
    "CMP-139",
    "CMP-158",
    "CMP-229",
    "CMP-231",
    "CMP-232",
)
# D05's id sets as §3.2 states them (G-A11Y)
A11Y_RANGES = {"AR": 17, "T2": 29, "LR": 35, "SD": 4}

# ---------------------------------------------------------------------------- headings
TRACE_HEAD = "Acceptance-criteria trace"
RULED_HEAD = "The questions BQ-1..BQ-31"
LOCKED_HEAD = "1.1 Locked inputs"
BUDGET_HEAD = "1.3 Budgets"
FRAMES_HEAD = "2.1 The merged boards"
A11Y_HEAD = "3.2 The accessibility package"
LEDGER_HEAD = "4.1 The 26 E30-D05 rows"
LOOKS_HEAD = "5. Disabled looks"
DECK_HEAD = "6. The copy deck"
A50_HEAD = "6.2 The ruled strings"
STATES_HEAD = "7. The state inventory"
REDLINE_HEAD = "8. Redlines and tokens"
ICON_HEAD = "9. Assets"
EVENTS_HEAD = "10. Observability"
QROW_HEAD = "11. The open-questions log"
CROW_HEAD = "12.1 C-rows"
GROW_HEAD = "12.2 The G-ledger"
AROW_HEAD = "12.3 §C Copy-ready A-rows"
CONSUMER_HEAD = "13.1 Consumers"
WALK_HEAD = "13.2 The role passes"
READER_HEAD = "13.3 The outside reader"
VERSION_HEAD = "14.1 Versioning"

Values = dict[str, str]
Unit = tuple[str, str, str]  # (region, location, normalised text)
STRICT_WALK: list[bool] = []
HEAD_OVERRIDE: list[tuple[str, str]] = []  # self-test lever: (rel, text) pretended at origin/main
_PATCHES: list[tuple[dict[str, str], str, str]] = []


# ---------------------------------------------------------------------------- git and text


def git(*args: str) -> str | None:
    try:
        out = subprocess.run(
            ["git", "-C", str(ROOT), *args], capture_output=True, check=False, timeout=120
        )
    except (OSError, subprocess.TimeoutExpired):
        return None
    if out.returncode != 0:
        return None
    return out.stdout.decode("utf-8", errors="replace")


@cache
def at_rev(rev: str, rel: str) -> str | None:
    return git("show", f"{rev}:{rel}")


def at_base(rel: str) -> str | None:
    return at_rev(BASE, rel)


def at_head(rel: str) -> str | None:
    for r, text in reversed(HEAD_OVERRIDE):
        if r == rel:
            return text
    return at_rev(HEAD, rel)


def read(rel: str) -> str:
    p = ROOT / rel
    return p.read_text(encoding="utf-8") if p.exists() else ""


def lines(text: str) -> list[str]:
    return text.split("\n")


@cache
def base_lines(key: str) -> tuple[str, ...]:
    return tuple(lines(at_base(KEYS[key]) or ""))


def base_line(key: str, n: int) -> str:
    bl = base_lines(key)
    return bl[n - 1] if 1 <= n <= len(bl) else ""


HEADING = re.compile(r"^(#{1,6}) (.*)$")
RULE_ROW = re.compile(r"^\|(?:\s*:?-+:?\s*\|)+\s*$")
FENCE = re.compile(r"^```")
ANCHOR = re.compile(r"<!--=([A-Z]+:[^>]+?)-->")
PLACEHOLDER = re.compile(r"\{\{([A-Z]+:[^{}]+)\}\}")
ANCHORED = re.compile(r"([^\s|(/·]*?)<!--=([A-Z]+:[^>]+?)-->")
COMMENT = re.compile(r"<!--.*?-->", re.DOTALL)
QUOTED = re.compile(r'"([^"\n]*)"')


def split_row(line: str) -> list[str]:
    cells = re.split(r"(?<!\\)\|", line.strip())
    return [c.strip() for c in cells[1:-1]]


def unfence(text: str) -> str:
    """The text with fenced blocks blanked (line count kept)."""
    out, inside = [], False
    for ln in lines(text):
        if FENCE.match(ln):
            inside = not inside
            out.append("")
            continue
        out.append("" if inside else ln)
    return "\n".join(out)


def section(text: str, title: str) -> str:
    """The body under the heading whose text starts with `title`, up to the next heading of the
    same or a higher level."""
    out: list[str] = []
    level = 0
    fenced = False
    for ln in lines(text):
        if FENCE.match(ln):
            fenced = not fenced
        m = HEADING.match(ln) if not fenced else None
        if m and level and len(m.group(1)) <= level:
            break
        if m and not level and m.group(2).startswith(title):
            level = len(m.group(1))
            continue
        if level:
            out.append(ln)
    return "\n".join(out)


def table_rows(block: str) -> list[list[str]]:
    rows = []
    for ln in lines(unfence(block)):
        if ln.startswith("|") and not RULE_ROW.match(ln):
            rows.append(split_row(ln))
    return rows[1:] if rows else []


def heading_titles(text: str) -> list[str]:
    return [m.group(2) for ln in lines(unfence(text)) if (m := HEADING.match(ln))]


def loose(s: str) -> str:
    s = unicodedata.normalize("NFKC", s).replace('\\"', '"').replace("\\|", "|")
    s = re.sub(r"[‐-―−]", "-", s).replace("’", "'").replace("“", '"').replace("”", '"')
    return re.sub(r"\s+", " ", s).strip().lower()


def ascii_line(s: str) -> str:
    return s.encode("ascii", "replace").decode("ascii")


def report(line: str) -> str:
    s = ascii_line(line)
    return s if len(s) <= REPORT_WIDTH else s[: REPORT_WIDTH - 3] + "..."


# ---------------------------------------------------------------------------- texts


@dataclass(frozen=True)
class Texts:
    spec: str
    deck: str
    states: str
    pins: str
    changed: tuple[str, ...] | None  # paths differing from the merge-base; None = git failed
    now: tuple[tuple[str, str], ...]  # ("14" | "15", working-tree text)
    mbase: tuple[tuple[str, str], ...]  # ("14" | "15", merge-base text)
    mbase_spec: str | None  # the spec at the merge-base (PR 2 mode)


def deck_data(t: Texts) -> dict[str, Any]:
    try:
        d = json.loads(t.deck)
    except json.JSONDecodeError:
        return {}
    return d if isinstance(d, dict) else {}


def entries(t: Texts) -> dict[str, dict[str, Any]]:
    s = deck_data(t).get("strings")
    return s if isinstance(s, dict) else {}


def states_data(t: Texts) -> dict[str, Any]:
    try:
        d = json.loads(t.states)
    except json.JSONDecodeError:
        return {}
    return d if isinstance(d, dict) else {}


def records(t: Texts) -> list[dict[str, Any]]:
    r = states_data(t).get("records")
    return [x for x in r if isinstance(x, dict)] if isinstance(r, list) else []


def by_id(t: Texts) -> dict[str, dict[str, Any]]:
    return {str(r.get("id")): r for r in records(t)}


def aliases(e: dict[str, Any]) -> list[str]:
    a = e.get("alias")
    return [str(x) for x in a] if isinstance(a, list) else []


def anns(e: dict[str, Any]) -> list[dict[str, Any]]:
    """An entry's announcements: one LR row, or a list where two rows speak it."""
    a = e.get("announce")
    rows = a if isinstance(a, list) else [a] if a is not None else []
    return [x if isinstance(x, dict) else {} for x in rows]


def t2s(r: dict[str, Any]) -> list[str]:
    t = r.get("t2")
    return [str(x) for x in t] if isinstance(t, list) else [str(t)] if t else []


def params(e: dict[str, Any]) -> list[dict[str, Any]]:
    p = e.get("params")
    return [x for x in p if isinstance(x, dict)] if isinstance(p, list) else []


def parent_form(text: str, e: dict[str, Any]) -> str:
    """The text with each renamed or parameterised slot written as its parent wrote it."""
    for p in params(e):
        if "parent" in p:
            text = text.replace("{" + str(p.get("name")) + "}", str(p["parent"]))
    return text


# ---------------------------------------------------------------------------- findings


@dataclass(frozen=True)
class Finding:
    gate: str
    level: str
    msg: str


def fails(gate: str, problems: list[str]) -> list[Finding]:
    return [Finding(gate, "FAIL", p) for p in problems]


# ---------------------------------------------------------------------------- values


def figure(key: str, n: int, pattern: str) -> str:
    m = re.search(pattern, base_line(key, n))
    return m.group(1) if m else "?"


def cite_values() -> Values:
    return {
        "CITE:budget.recompute": figure("14", 1439, r"≤(\d+) ms"),
        "CITE:budget.ack.demo": figure("06", 28, r"p95 < ?(\d+) ?ms \(demo"),
        "CITE:budget.ack.live": figure("06", 28, r"p95 < ?(\d+) ?ms \(live"),
        "CITE:budget.backend": figure("06", 125, r"portion budget \(≤(\d+) ?ms\)"),
        "CITE:budget.hotkey": figure("E30J", 254, r"submit \S*?(\d+) ms client-side"),
    }


@cache
def cal() -> tuple[datetime.date, int]:
    text = "\n".join(base_lines("CAL"))
    m = re.search(r"SPRINT01_START = datetime\.date\((\d{4}), (\d{1,2}), (\d{1,2})\)", text)
    d = re.search(r"SPRINT_DAYS = (\d+)", text)
    start = datetime.date(int(m.group(1)), int(m.group(2)), int(m.group(3))) if m else None
    return (start or datetime.date(1970, 1, 1)), int(d.group(1)) if d else 7


def sprint_start(n: int) -> datetime.date:
    start, days = cal()
    return start + datetime.timedelta(days=(n - 1) * days)


def sprint_values() -> Values:
    start, days = cal()
    today = datetime.date(2026, 10, 30)  # the BQ list's and R919's date
    return {
        "SPRINT:today": f"S{(today - start).days // days + 1:02d}",
        "SPRINT:s15.end": (sprint_start(16) - datetime.timedelta(days=1)).isoformat(),
        "SPRINT:s16.start": sprint_start(16).isoformat(),
        "SPRINT:s17.start": sprint_start(17).isoformat(),
    }


def img_count() -> int:
    folder = ROOT / IMG_REL
    if not folder.is_dir():
        return 0
    return sum(1 for p in folder.glob("E30-D0[234]-*.png"))


def ledger_rows(spec: str) -> list[list[str]]:
    return table_rows(section(spec, LEDGER_HEAD))


def disposition(cell: str) -> str:
    c = cell.strip().strip("*")
    for d in sorted(TALLY, key=len, reverse=True):
        if c.startswith(d):
            return d
    return c


def count_values(t: Texts) -> Values:
    es = entries(t)
    rs = records(t)
    scr = [r for r in rs if r.get("screen")]
    v = {
        "COUNT:deck.entries": len(es),
        "COUNT:deck.merged": sum(e.get("status") == "merged" for e in es.values()),
        "COUNT:deck.amended": sum(e.get("status") == "amended" for e in es.values()),
        "COUNT:deck.ruled": sum(e.get("status") == "ruled" for e in es.values()),
        "COUNT:deck.byref": sum(e.get("status") == "by-reference" for e in es.values()),
        "COUNT:deck.notcarried": len(deck_data(t).get("not_carried") or []),
        "COUNT:deck.codes": len([c for c in deck_data(t).get("by_code") or {} if c != "*"]),
        "COUNT:deck.labels": sum(e.get("kind") == "label" for e in es.values()),
        "COUNT:deck.typed": sum(bool(params(e)) for e in es.values()),
        "COUNT:deck.announced": sum(bool(anns(e)) for e in es.values()),
        "COUNT:states.speaks": sum(bool(r.get("speaks")) for r in rs),
        "COUNT:deck.native": sum(bool(e.get("native_sl")) for e in es.values()),
        "COUNT:deck.security": sum(bool(e.get("security")) for e in es.values()),
        "COUNT:states.records": len(rs),
        "COUNT:states.screens": len(scr),
        "COUNT:states.components": len(rs) - len(scr),
        "COUNT:states.lifted": sum(bool(r.get("lifted")) for r in rs),
        "COUNT:states.owed": sum(r.get("frame") == "owed (PR 3)" for r in rs),
        "COUNT:states.t2": sum(r.get("look") == "T2" for r in scr),
        "COUNT:states.validity": sum(r.get("look") == "validity" for r in scr),
        "COUNT:states.busy": sum(r.get("look") == "busy" for r in scr),
        "COUNT:states.carve": sum(bool(r.get("carve_out")) for r in rs),
        "COUNT:boards": img_count(),
        "COUNT:gates": len(GATES),
        "COUNT:mutations": len(MUTATIONS),
        "COUNT:spec.lines": len(t.spec.splitlines()),
        "COUNT:spec.arows": len(lines(section(t.spec, AROW_HEAD))) + 1,
    }
    for s in SURFACES:
        v[f"COUNT:deck.{s}"] = sum(e.get("surface") == s for e in es.values())
    tally = {d: 0 for d in TALLY}
    for r in ledger_rows(t.spec):
        if len(r) > 2 and disposition(r[2]) in tally:
            tally[disposition(r[2])] += 1
    names = {
        "fixed by PR 0": "fixed",
        "lifted": "lifted",
        "recorded": "recorded",
        "carried": "carried",
        "closed": "closed",
        "applied": "applied",
        "PR 2": "pr2",
        "named": "named",
    }
    for d, n in tally.items():
        v[f"COUNT:ledger.{names[d]}"] = n
    v["COUNT:ledger.total"] = sum(tally.values())
    return {k: str(x) for k, x in v.items()}


@cache
def fixed_values() -> tuple[tuple[str, str], ...]:
    v = cite_values()
    v.update(sprint_values())
    v.update(RULED_VALUES)
    return tuple(sorted(v.items()))


def compute(t: Texts) -> Values:
    v = dict(fixed_values())
    v.update(count_values(t))
    return v


def code_spans(line: str) -> list[tuple[int, int]]:
    return [(m.start(), m.end()) for m in re.finditer(r"`[^`\n]*`", line)]


def fill(text: str, values: Values) -> tuple[str, list[str]]:
    missing: list[str] = []

    def sub(m: re.Match[str]) -> str:
        key = m.group(1)
        if key not in values:
            missing.append(key)
            return m.group(0)
        return f"{values[key]}<!--={key}-->"

    out = []
    for ln in lines(text):
        spans = code_spans(ln)
        pieces, last = [], 0
        for m in PLACEHOLDER.finditer(ln):
            if any(a <= m.start() < b for a, b in spans):
                continue
            pieces.append(ln[last : m.start()])
            pieces.append(sub(m))
            last = m.end()
        pieces.append(ln[last:])
        out.append("".join(pieces))
    return "\n".join(out), missing


def anchored(text: str) -> list[tuple[str, str]]:
    return [(m.group(1), m.group(2)) for m in ANCHORED.finditer(unfence(text))]


def unfill(text: str) -> str:
    """The text with each anchored value cut out (the pins never see a value)."""
    return ANCHORED.sub(lambda m: f"<!--={m.group(2)}-->", text)


def g_anchor(t: Texts) -> list[Finding]:
    v = compute(t)
    bad: list[str] = []
    for m in PLACEHOLDER.finditer(re.sub(r"`[^`\n]*`", "", unfence(t.spec))):
        bad.append(f"{{{{{m.group(1)}}}}} is not filled (run --fill)")
    for got, key in anchored(t.spec):
        want = v.get(key)
        if want is None:
            bad.append(f"{key} is not a value the tool computes")
        elif not got.endswith(want) or (got[: -len(want)] and got[: -len(want)][-1].isdigit()):
            bad.append(f"{key} reads {got!r}, the tool computes {want!r}")
    return fails("G-ANCHOR", bad)


def g_marker(t: Texts) -> list[Finding]:
    bad = [
        f"an HTML comment that is not a value anchor ({m.group(0)[:24]!r})"
        for m in COMMENT.finditer(t.spec)
        if not ANCHOR.fullmatch(m.group(0))
    ]
    return fails("G-MARKER", bad)


# ---------------------------------------------------------------------------- cites


_KEYALT = "|".join(sorted((re.escape(k) for k in KEYS), key=len, reverse=True))
CITE = re.compile(
    r"(?:`(" + _KEYALT + r")`|(?<![\w`-])(" + _KEYALT + r"))"
    r":(\d+)(?:[–-](\d+))?((?:,\s*:\d+(?:[–-]\d+)?)*)"
)
CONT = re.compile(r":(\d+)(?:[–-](\d+))?")


def cites_in(text: str) -> list[tuple[str, int, int]]:
    out: list[tuple[str, int, int]] = []
    for m in CITE.finditer(text):
        key = m.group(1) or m.group(2)
        a, b = int(m.group(3)), int(m.group(4) or m.group(3))
        out.append((key, a, b))
        for c in CONT.finditer(m.group(5) or ""):
            out.append((key, int(c.group(1)), int(c.group(2) or c.group(1))))
    return out


def all_cites(t: Texts) -> list[tuple[str, int, int]]:
    seen: dict[tuple[str, int, int], None] = {}
    texts = [unfence(t.spec)]
    for e in entries(t).values():
        for s in e.get("sources") or []:
            if isinstance(s, dict):
                texts.append(str(s.get("cite", "")))
    for r in records(t):
        texts.append(str(r.get("cite", "")))
    for x in texts:
        for c in cites_in(x):
            seen.setdefault(c, None)
    return list(seen)


def g_cite(t: Texts) -> list[Finding]:
    bad: list[str] = []
    for key, a, b in all_cites(t):
        bl = base_lines(key)
        if bl == ("",):
            bad.append(f"`{key}` is unreadable at {BASE}")
            continue
        if not (1 <= a <= b <= len(bl)):
            bad.append(f"`{key}`:{a}-{b} is outside the file ({len(bl)} lines)")
            continue
        if not bl[a - 1].strip() or not bl[b - 1].strip():
            bad.append(f"`{key}`:{a}-{b} starts or ends on a blank line")
    return fails("G-CITE", bad)


def unique_block(base: tuple[str, ...], a: int, b: int) -> list[str]:
    lo, hi = a - 1, b
    while base[lo:hi] and base.count(base[lo]) > 1 and (lo > 0 or hi < len(base)):
        lo, hi = max(0, lo - 1), min(len(base), hi + 1)
    return list(base[lo:hi])


@cache
def head_joined_git(rel: str) -> str:
    return "\n" + (at_rev(HEAD, rel) or "") + "\n"


def head_joined(rel: str) -> str:
    for r, text in reversed(HEAD_OVERRIDE):
        if r == rel:
            return "\n" + text + "\n"
    return head_joined_git(rel)


@cache
def head_ok() -> bool:
    return bool((git("rev-parse", "--verify", "--quiet", f"{HEAD}^{{commit}}") or "").strip())


@cache
def under_base(sha: str) -> bool:
    full = (git("rev-parse", "--verify", "--quiet", f"{sha}^{{commit}}") or "").strip()
    return bool(full) and (git("merge-base", full, BASE) or "").strip() == full


def g_version(t: Texts) -> list[Finding]:
    bad: list[str] = []
    if not head_ok():
        bad.append(f"{HEAD} does not resolve: no cited range compared (fail closed)")
    else:
        for key, a, b in all_cites(t):
            bl = base_lines(key)
            if not (1 <= a <= b <= len(bl)):
                continue
            block = unique_block(bl, a, b)
            if ("\n" + "\n".join(block) + "\n") not in head_joined(KEYS[key]):
                bad.append(f"`{key}`:{a}-{b} was edited at {HEAD}")
    start = next((ln for ln in lines(t.spec) if ln.startswith("**Start.**")), "")
    if f"**v1 at base `{BASE}`.**" not in start:
        bad.append("the version line does not name v1 at the base")
    for sha in re.findall(r"`([0-9a-f]{10})`", start):
        if not under_base(sha):
            bad.append(f"`{sha}` on the version line is not a commit under the base")
    if f"v1 at base `{BASE}`" not in section(t.spec, VERSION_HEAD):
        bad.append("§14.1 does not name v1 at the base")
    for name, d in (("deck", deck_data(t)), ("inventory", states_data(t))):
        if (d.get("pack"), d.get("version"), d.get("base")) != (TICKET, "v1", BASE):
            bad.append(f"the {name}'s pack, version or base is not {TICKET} v1 at {BASE}")
    return fails("G-VERSION", bad)


CORE = ("D02", "D03", "D04", "D05", "14", "15", "22", "E09-D09", "E32D06", "ICONS", "CONST", "DS")


@cache
def loose_source(key: str) -> str:
    return loose("\n".join(base_lines(key)))


def g_quote(t: Texts) -> list[Finding]:
    es = entries(t)
    pool: list[str] = []
    for e in es.values():
        pool.append(str(e.get("string", "")))
        pool.append(parent_form(str(e.get("string", "")), e))
        for x in e.get("examples") or []:
            if isinstance(x, dict):
                pool.append(str(x.get("text", "")))
    deck_text = loose("\n".join(pool))
    ruled = loose("\n".join(RULING_QUOTES))
    bad: list[str] = []
    for i, ln in enumerate(lines(unfence(t.spec)), 1):
        cited = [k for k, _a, _b in cites_in(ln)]
        for q in QUOTED.findall(COMMENT.sub("", ln)):
            q = q.strip()
            if len(q) < QUOTE_MIN:
                continue
            lq = loose(q)
            if lq in deck_text or lq in ruled or any(lq in loose_source(k) for k in cited):
                continue
            if any(lq in loose_source(k) for k in CORE):
                continue
            bad.append(f"line {i}: {q[:50]!r} is in no cited source, the deck or R919")
    return fails("G-QUOTE", bad)


# ---------------------------------------------------------------------------- the deck


def render(template: str, params: dict[str, str]) -> str:
    out = template
    for k, v in params.items():
        out = out.replace("{" + k + "}", v)
    return out


def mechanical(surface: str, alias: str) -> str:
    head, _, rest = alias.partition(".")
    return f"ticket.{surface}." + (rest if head == surface and rest else alias)


def source_ok(cite: str, text: str) -> bool:
    m = re.fullmatch(r"`(" + _KEYALT + r")`:(\d+)", cite)
    if m:
        return loose(text) in loose(base_line(m.group(1), int(m.group(2))))
    ruled = (f"R919 {RULING_ID}", f"A50 {A50_ID}")
    return cite in ruled and any(s == text for _k, s in A50.values())


def quoted_cells(key: str, n: int, cols: tuple[int, ...]) -> list[str]:
    c = split_row(base_line(key, n))
    out: list[str] = []
    for col in cols:
        if col < len(c):
            out += [
                q.replace('\\"', '"') for q in re.findall(r'\\?"((?:[^"\\]|\\.)*?)\\?"', c[col])
            ]
    return out


F_ROW = re.compile(r"^\| (F-\d\d) \|")
POLITENESS = ("none", "polite", "assertive")
PARAM_TYPES = ("string", "decimal", "integer", "enum", "time", "datetime", "duration")
IDENT = re.compile(r"[a-z][a-z0-9_]*")
SIDE_WORDS = re.compile(r"\bBUY\b|\bSELL\b|\brises to\b|\bfalls to\b")
# BQ-23's security-bearing set, by merged key: the whole of §6.4 (SCR-061's count strings named by
# the round-1 lens; the rest added by the light lens r2, Minor 1), so a dropped flag on any of the
# set's entries FAILs here, not only through COUNT:deck.security
SECURITY_ALIASES = (
    "selector.group",
    "selector.group_row",
    "selector.name",
    "selector.narrowed",
    "selector.no_groups.manager",
    "rbac.view_as",
    "rbac.account",
    "rbac.account_read_only",
    "rbac.env",
    "rbac.permission",
    "rbac.owner_only",
    "guard.mismatch",
    "notice.panel_read_only.account_read_only",
    "notice.panel_read_only.permission",
    "drawer.role_unavailable",
    "record.never_stored",
    "ratelimit.link.manager",
    "confirm.fanout.held",
    "confirm.fanout.skipped",
    "refusal.account_locked",
    "refusal.key_invalid",
    "refusal.symbol_not_allowed",
    "refusal.trading_disabled.account_disabled_by_policy",
    "refusal.trading_disabled.account_unhealthy",
    "refusal.trading_disabled.no_active_key",
    "refusal.unmapped",
    "refusal.view_as_expired",
    "profile.blocked",
    "profile.unavailable",
    "pending_key",
    "pending_key.reason",
    "glyph.name",
)


def param_problems(k: str, e: dict[str, Any], s: str, exs: list[dict[str, Any]]) -> list[str]:
    """Row 1: every placeholder a typed, identifier-safe parameter; examples use those names."""
    names = list(dict.fromkeys(re.findall(r"\{([^{}]*)\}", s)))
    ps = params(e)
    bad: list[str] = []
    if [str(p.get("name")) for p in ps] != names:
        bad.append(f"{k}: `params` does not type every placeholder, in order")
    for p in ps:
        if not IDENT.fullmatch(str(p.get("name"))) or p.get("type") not in PARAM_TYPES:
            bad.append(f"{k}: the parameter {p.get('name')!r} is not identifier-safe and typed")
    for x in exs:
        extra = set(x.get("params") or {}) - set(names)
        if extra:
            bad.append(f"{k}: an example names {min(extra)!r}, which is no parameter")
    return bad


def amended_problems(d: dict[str, Any], k: str, e: dict[str, Any]) -> list[str]:
    """An entry amended by a D05 F row (the ladder's rung 4): its first source is that row and
    its parent string is `not_carried` with the row as its reason."""
    row = re.fullmatch(r"D05 (F-\d\d)", str(e.get("amended", "")))
    srcs = [x for x in e.get("sources") or [] if isinstance(x, dict)]
    m = re.fullmatch(r"`D05`:(\d+)", str(srcs[0].get("cite", ""))) if srcs else None
    if not row or not m:
        return [f"{k}: an amended entry that names no D05 F row or cites none first"]
    f = F_ROW.match(base_line("D05", int(m.group(1))))
    if not f or f.group(1) != row.group(1):
        return [f"{k}: amended by {row.group(1)}, but its first source is not that row"]
    nc = [x for x in d.get("not_carried") or [] if isinstance(x, dict)]
    if not any(
        x.get("superseded_by") == k and row.group(1) in str(x.get("reason", "")) for x in nc
    ):
        return [f"{k}: its parent string is not `not_carried` with {row.group(1)} as reason"]
    return []


def deck_problems(t: Texts) -> list[str]:
    d = deck_data(t)
    bad: list[str] = []
    if not d:
        return ["the deck is not a JSON object"]
    if tuple(d.get("surfaces") or {}) != SURFACES:
        bad.append("the deck's surfaces are not the eight of BQ-12, in order")
    if d.get("ruling") != RULING_ID:
        bad.append("the deck does not name R919")
    known: set[str] = set()
    for k, e in entries(t).items():
        s, surf, al = str(e.get("string", "")), str(e.get("surface", "")), aliases(e)
        known.add(loose(s))
        if surf not in SURFACES:
            bad.append(f"{k}: surface {surf!r} is not one of the eight")
        if e.get("status") not in STATUSES:
            bad.append(f"{k}: status {e.get('status')!r}")
        if not al or k != mechanical(surf, al[0]):
            bad.append(f"{k}: not the mechanical key of its first merged key")
        srcs = [x for x in e.get("sources") or [] if isinstance(x, dict)]
        if not srcs:
            bad.append(f"{k}: no source")
        exs = [x for x in e.get("examples") or [] if isinstance(x, dict)]
        renders = {s, parent_form(s, e)}
        for x in exs:
            p = x.get("params")
            if not isinstance(p, dict) or render(s, p) != x.get("text"):
                bad.append(f"{k}: an example does not render from the template")
            renders.add(str(x.get("text", "")))
            renders.add(parent_form(render(s, p if isinstance(p, dict) else {}), e))
            known.add(loose(str(x.get("text", ""))))
        known.add(loose(parent_form(s, e)))
        bad += param_problems(k, e, s, exs)
        for ann in anns(e):
            if ann.get("politeness") not in POLITENESS or not ann.get("rate"):
                bad.append(f"{k}: an announcement whose politeness is not an enum or has no rate")
        if SIDE_WORDS.search(re.sub(r"\{[^{}]*\}", "", s)):
            bad.append(f"{k}: a hard-coded side or direction outside a parameter (row 12)")
        if any(a in SECURITY_ALIASES for a in al) and not e.get("security"):
            bad.append(f"{k}: a security-bearing string not flagged `security` (BQ-23)")
        if e.get("server_field") and (e.get("status") != "by-reference" or s != "{detail}"):
            bad.append(f"{k}: a server-field entry that is not `{{detail}}` by reference")
        for src in srcs:
            cite, text = str(src.get("cite", "")), str(src.get("text", ""))
            if not source_ok(cite, text):
                bad.append(f"{k}: {text[:40]!r} is not at {cite}")
            if text not in renders and e.get("status") != "amended":
                bad.append(
                    f"{k}: the source text {text[:40]!r} is neither the string nor an example"
                )
        if e.get("status") == "ruled":
            item = re.fullmatch(r"A50 item (\d+)", str(e.get("ruled", "")))
            if not item or A50.get(int(item.group(1))) != (k, s):
                bad.append(f"{k}: a ruled entry that is not its A50 item")
            if not any(str(x.get("cite")) == f"A50 {A50_ID}" for x in srcs):
                bad.append(f"{k}: a ruled entry that does not cite A50 ({A50_ID})")
        if e.get("status") == "amended":
            bad += amended_problems(d, k, e)
    nc = [x for x in d.get("not_carried") or [] if isinstance(x, dict)]
    for x in nc:
        if not x.get("reason") or not source_ok(str(x.get("cite", "")), str(x.get("text", ""))):
            bad.append(f"not_carried {str(x.get('text', ''))[:30]!r}: no reason or not at its cite")
    carried = {(loose(str(x.get("text", ""))), str(x.get("cite", ""))) for x in nc}
    for key, a, b, cols in SOURCE_ROWS:
        for n in range(a, b + 1):
            for q in quoted_cells(key, n, cols):
                if loose(q) not in known and (loose(q), f"`{key}`:{n}") not in carried:
                    bad.append(
                        f"`{key}`:{n}: {q[:40]!r} is no entry and not recorded as not carried"
                    )
    return bad


def g_deck(t: Texts) -> list[Finding]:
    return fails("G-DECK", deck_problems(t))


def g_once(t: Texts) -> list[Finding]:
    bad: list[str] = []
    seen: dict[str, str] = {}
    slot: dict[tuple[str, str], str] = {}
    es = entries(t)
    for k, e in es.items():
        s = str(e.get("string", ""))
        if s in seen and not (e.get("server_field") and es[seen[s]].get("server_field")):
            bad.append(f"{k} and {seen[s]} carry the same string {s[:30]!r}")
        seen.setdefault(s, k)
        for a in aliases(e):
            pair = (str(e.get("surface")), a)
            if pair in slot and slot[pair] != k:
                bad.append(f"the merged key {a} has two strings on {pair[0]} ({slot[pair]}, {k})")
            slot[pair] = k
    return fails("G-ONCE", bad)


FIXTURE_NAMES = re.compile(r"\b(?:Main|Desk4|Core3|sub_\d{3})\b|\b[A-Z0-9]{2,}USDT\b")
DIGITS = re.compile(r"\d[\d,.]*\d|\d")


def g_fixture(t: Texts) -> list[Finding]:
    bad: list[str] = []
    for k, e in entries(t).items():
        s = str(e.get("string", ""))
        bare = re.sub(r"\{[^{}]*\}", "", s)
        fixed = [str(x) for x in e.get("fixed") or []]
        for m in FIXTURE_NAMES.finditer(bare):
            bad.append(f"{k}: the fixture {m.group(0)!r} outside a parameter")
        runs = DIGITS.findall(bare)
        for r in runs:
            if r not in fixed:
                bad.append(f"{k}: the digit run {r!r} is neither a parameter nor in `fixed`")
        for f in fixed:
            if f not in runs:
                bad.append(f"{k}: `fixed` lists {f!r}, which the string does not carry")
    return fails("G-FIXTURE", bad)


@cache
def registered_codes() -> dict[str, frozenset[str]]:
    api = "\n".join(base_lines("22"))
    a, b = api.find("\nx-error-codes:"), api.find("\nx-error-codes-ws:")
    problem = frozenset(re.findall(r"- code: ([a-z_]+)", api[a:b] if a >= 0 and b > a else ""))
    enum = re.search(r"code:\s*\n\s*type: string\s*\n\s*enum:\s*\n\s*\[([^\]]*)\]", api)
    preview = frozenset(re.findall(r"[a-z_]+", enum.group(1))) if enum else frozenset()
    rules = frozenset(re.findall(r"`validation_failed` / `([a-z_]+)`", api))
    i24 = "\n".join(base_lines("24"))
    blk = re.search(r"class OmsErrorCode\(StrEnum\):\n((?:    .*\n)+)", i24)
    oms = (
        frozenset(re.findall(r"^    ([A-Z_]+) = ", blk.group(1), re.MULTILINE))
        if blk
        else frozenset()
    )
    sizing = frozenset(("invalid_stop_distance", "below_min_notional")) & frozenset(
        re.findall(r"`([a-z_]+)`", i24)
    )
    return {"problem": problem, "preview": preview, "rule": rules, "oms": oms, "sizing": sizing}


# Row 3: a cause a target sentence names, and the codes that sentence is true for
CAUSES: tuple[tuple[re.Pattern[str], frozenset[str]], ...] = tuple(
    (re.compile(p), frozenset(c.split()))
    for p, c in (
        (r"stop is missing|native stop", "native_stop_required"),
        (r"[Ss]top distance", "invalid_stop_distance"),
        (
            r"rate limited|request budget|[Rr]ate budget|budget allows",
            "rate_limited exchange_rate_limited rate_budget_exhausted RATE_BUDGET_EXCEEDED",
        ),
        (r"\bmargin\b", "insufficient_margin INSUFFICIENT_MARGIN insufficient_balance"),
        (r"\btick\b", "tick_size_violation"),
        (r"\bstep\b", "lot_size_violation"),
        (r"[Ll]everage", "leverage_unavailable LEVERAGE_ERROR"),
        (r"profile cap\b", "risk_limit_breached cap_breached"),
        (r"risk-limit tier", "RISK_LIMIT_EXCEEDED"),
        (r"hedge mode|one-way mode", "POSITION_MODE_MISMATCH"),
        (r"[Rr]educe-only", "REDUCE_ONLY_VIOLATION"),
        (r"at least", "below_min_notional"),
        (r"feed stale", "degraded_data"),
        (r"[Ff]rozen", "kill_switch_engaged"),
        (r"API key", "key_invalid no_active_key"),
        (r"not allowed on", "symbol_not_allowed"),
        (r"\blocked\b", "account_locked session_not_armed"),
        (r"maintenance", "maintenance"),
        (r"by policy", "account_disabled_by_policy"),
        (r"health check", "account_unhealthy"),
        (r"No answer from the exchange", "timeout"),
        (r"Rejected by Bybit", "exchange_error"),
    )
)


def sentence_problems(code: str, key: str, text: str) -> list[str]:
    """Row 3: a code's target names no other field or cause than the code's own."""
    segs = set(code.split(":")[1:])
    return [
        f"{code} resolves to {key}, whose sentence names another cause ({m.group(0)!r})"
        for rx, ok in CAUSES
        if (m := rx.search(text)) and not segs & ok
    ]


def g_codes(t: Texts) -> list[Finding]:
    bad: list[str] = []
    reg = registered_codes()
    want: dict[str, dict[str, str]] = {}
    gids = row_ids(t.spec, GROW_HEAD, "G")
    es = entries(t)
    bc = dict(deck_data(t).get("by_code") or {})
    fallback = bc.pop("*", None)
    defaults = set(fallback.values()) if isinstance(fallback, dict) else set()
    for k, e in es.items():
        codes = [str(c) for c in e.get("codes") or []]
        surfs = [str(x) for x in e.get("code_surfaces") or [e.get("surface")]]
        for c in codes:
            kind, _, rest = c.partition(":")
            slug = rest.split(":")[0]
            if re.search(r"\d{4,}", c):
                bad.append(f"{k}: {c} carries a retCode")
            elif slug not in reg.get(kind, frozenset()):
                bad.append(f"{k}: {c} is not registered at the base")
            bad += sentence_problems(c, k, str(e.get("string", "")))
            slot = want.setdefault(c, {})
            for surf in surfs:
                if surf in slot:
                    bad.append(f"{c} resolves to two keys on {surf} ({slot[surf]}, {k})")
                slot[surf] = k
        pend = str(e.get("codes_pending", ""))
        open_row = re.match(r"G-\d+ ", pend)
        if e.get("kind") == "refusal" and not codes and not open_row and k not in defaults:
            bad.append(f"{k}: a refusal string with no code, no open row and no fallback role")
        if pend and (m := re.match(r"(G-\d+) ", pend)) and m.group(1) not in gids:
            bad.append(f"{k}: codes_pending names {m.group(1)}, which §12.2 lacks")
        refusal_key = any(a.startswith(("refusal.", "rejected.class.")) for a in aliases(e))
        if refusal_key and e.get("kind") != "refusal":
            bad.append(f"{k}: a refusal key not marked as a refusal")
    if bc != {c: dict(sorted(want[c].items())) for c in sorted(want)}:
        bad.append("by_code is not the inverse of the entries' codes")
    surfaces = sorted({s for v in want.values() for s in v})
    if not isinstance(fallback, dict) or sorted(fallback) != surfaces:
        bad.append("by_code's `*` row does not name one fallback per refusal surface (row 5)")
    else:
        for surf, key in fallback.items():
            e = es.get(key, {})
            if e.get("surface") != surf or e.get("server_field") != "Problem.detail":
                bad.append(f"by_code's `*` row: {key} is not {surf}'s Problem.detail fallback")
    return fails("G-CODES", bad)


OVERCLAIM = re.compile(
    r"\b(?:guarantee[ds]?|always protected|fully protected|never unprotected|risk-free|"
    r"cannot (?:be )?lost?)\b",
    re.IGNORECASE,
)
CARVE_WORDS = re.compile(r"Set stop by hand|Flatten now|Close position|\bcancel", re.IGNORECASE)
EVERY_ORDER = re.compile(r"\bevery order\b", re.IGNORECASE)


@cache
def c26_scope() -> str:
    """C-2.6's own scope, read from CONST at the base (the subject of its bold sentence)."""
    m = re.search(
        r"\*\*(Every position-opening order, .*?), must carry", " ".join(base_lines("CONST"))
    )
    return m.group(1) if m else "(C-2.6 unreadable at the base)"


def g_native(t: Texts) -> list[Finding]:
    bad: list[str] = []
    es = entries(t)
    by_alias = {a: (k, e) for k, e in es.items() for a in aliases(e)}
    note = es.get("ticket.order.sl.note", {}).get("string")
    d02 = quoted_cells("D02", 394, (1,))
    e32 = re.findall(r'"([^"]+)"', base_line("E32D06", 120))
    if not d02 or note != d02[0] or not e32 or note != e32[0]:
        bad.append("ticket.order.sl.note is not D02:394 and E32-D06 S-6 byte for byte")
    vsl = es.get("ticket.order.v.sl.required", {})
    if vsl.get("string") != A50[10][1] or vsl.get("status") != "ruled":
        bad.append("ticket.order.v.sl.required is not A50 item 10")
    for a in NATIVE_ALIASES:
        hit = by_alias.get(a)
        if not hit or not hit[1].get("native_sl"):
            bad.append(f"the native-SL string {a} is missing or not flagged")
    for k, e in es.items():
        if OVERCLAIM.search(str(e.get("string", ""))):
            bad.append(f"{k}: the string claims more than the exchange holding the stop")
        if any(a in CARVE_ALIASES for a in aliases(e)) and "never gated" not in str(e.get("note")):
            bad.append(f"{k}: a carve-out control without its never-gated note")
    rec = by_id(t)
    for rid in CARVE_RECORDS:
        if not rec.get(rid, {}).get("carve_out"):
            bad.append(f"{rid}: the carve-out controls are not kept enabled")
    for rid, r in rec.items():
        gated = str(r.get("gated", ""))
        if CARVE_WORDS.search(gated) and "except" not in gated:
            bad.append(f"{rid}: the record gates a carve-out control ({gated[:40]!r})")
    if "except the C-2.6 carve-out" not in str(rec.get("SCR-060/view-as", {}).get("gated", "")):
        bad.append("SCR-060/view-as does not except the C-2.6 carve-out")
    crows = " ".join(" ".join(r) for r in table_rows(section(t.spec, CROW_HEAD)))
    for k, e in es.items():
        native = e.get("native_sl") and EVERY_ORDER.search(str(e.get("string", "")))
        if native and f"`{k}`" not in crows:
            bad.append(f"{k}: an 'every order' native-SL string with no accuracy C-row")
    fix = [r for r in a_rows(t.spec)[0] if r.file == "14" and A50[10][1] in r.new]
    if (
        len(fix) != 1
        or loose(c26_scope()) not in loose(fix[0].new)
        or "account profile requires" in fix[0].new
    ):
        bad.append("the A-row correcting `14`'s SL clause does not carry C-2.6's scope")
    return fails("G-NATIVE", bad)


# ---------------------------------------------------------------------------- states


def paren_split(s: str) -> list[str]:
    out, buf, depth = [], "", 0
    i = 0
    while i < len(s):
        ch = s[i]
        depth += ch in "(["
        depth -= ch in ")]"
        if depth == 0 and s.startswith(", ", i):
            out.append(buf)
            buf = ""
            i += 2
            continue
        buf += ch
        i += 1
    out.append(buf)
    return out


def head_token(tok: str) -> str:
    tok = re.sub(r"^and ", "", tok.strip().replace("**", "")).strip(" .")
    tok = re.split(r" ?\(", tok, maxsplit=1)[0]
    return tok.strip()


def entry_at(key: str, heading: str) -> list[str]:
    bl = base_lines(key)
    out: list[str] = []
    on = False
    for ln in bl:
        if ln.startswith("### "):
            if on:
                break
            on = ln.startswith(heading)
            continue
        if on:
            out.append(ln)
    return out


@cache
def tokens14(screen: str) -> tuple[str, ...]:
    for ln in entry_at("14", f"### {screen} "):
        if ln.startswith("- **States:**"):
            body = ln.removeprefix("- **States:**")
            return tuple(head_token(x) for x in body.split(" · ") if head_token(x))
    return ()


@cache
def tokens15(cmp: str) -> tuple[str, ...]:
    for ln in entry_at("15", f"### {cmp} "):
        if ln.startswith("- **States**"):
            body = ln.split(":", 1)[1].split("**E3")[0]
            out: list[str] = []
            for x in paren_split(body):
                alt = re.search(r"`([a-z_ |]+)`", x)
                if alt and "|" in alt.group(1):
                    out += [a.strip() for a in alt.group(1).split("|")]
                    continue
                h = head_token(x)
                if h:
                    out.append(h)
            return tuple(out)
    return ()


def parent_frames() -> set[str]:
    out: set[str] = set()
    for key, a, b, col in (("D02", 275, 300, 6), ("D03", 162, 395, 0)):
        for n in range(a, b + 1):
            c = split_row(base_line(key, n))
            if len(c) == 7:
                out |= set(re.findall(r"`(SCR-\d{3}/[a-z0-9-]+)`", c[col]))
    return out


def row_ids(spec: str, head: str, prefix: str) -> set[str]:
    return {r[0] for r in table_rows(section(spec, head)) if re.fullmatch(prefix + r"-\d+", r[0])}


def states_problems(t: Texts) -> list[str]:
    bad: list[str] = []
    rs = records(t)
    if not rs:
        return ["the inventory has no records"]
    crows = row_ids(t.spec, CROW_HEAD, "C")
    arows = {r.aid: r for r in a_rows(t.spec)[0]}
    looks = set(states_data(t).get("looks") or [])
    twins: set[tuple[str, str]] = set()
    ids = set()
    for r in rs:
        rid = str(r.get("id"))
        ids.add(rid)
        if r.get("look") not in looks:
            bad.append(f"{rid}: look {r.get('look')!r}")
        fr = r.get("frame")
        if isinstance(fr, dict):
            if fr.get("page") not in PAGES:
                bad.append(f"{rid}: its frame names no parent page")
        elif fr == "owed (PR 3)":
            if not r.get("lifted"):
                bad.append(f"{rid}: owed by PR 3 but not a lifted record")
        elif not (isinstance(fr, str) and fr in crows):
            bad.append(f"{rid}: no frame and no C-row")
        tw = str(r.get("twin", ""))
        if tw.startswith("14:"):
            if tw[3:] not in tokens14(str(r.get("screen"))):
                bad.append(f"{rid}: `14` {r.get('screen')} has no States token {tw[3:]!r}")
            twins.add((str(r.get("screen")), tw[3:]))
        elif tw.startswith("15:"):
            _, cmp, tok = tw.split(":", 2)
            if tok not in tokens15(cmp):
                bad.append(f"{rid}: `15` {cmp} has no States token {tok!r}")
            twins.add((cmp, tok))
        elif re.fullmatch(r"A-\d+(:.*)?", tw):
            aid, _, txt = tw.partition(":")
            row = arows.get(aid)
            want = txt or str(r.get("state"))
            if not row or want not in row.new:
                bad.append(f"{rid}: {aid} does not add {want!r}")
        elif tw not in crows:
            bad.append(f"{rid}: the twin {tw!r} resolves to nothing")
    closed = states_data(t).get("closed_14") or {}
    for screen in ("SCR-060", "SCR-061"):
        for tok in tokens14(screen):
            c = closed.get(f"{screen}:{tok}") if isinstance(closed, dict) else None
            if (screen, tok) not in twins and not (c and c in crows):
                bad.append(f"`14` {screen} States {tok!r} has no record and no C-row")
    for cmp in FIFTEEN:
        for tok in tokens15(cmp):
            if (cmp, tok) not in twins:
                bad.append(f"`15` {cmp} States {tok!r} has no record")
    for fr in sorted(parent_frames() - ids):
        bad.append(f"the parent frame {fr} is no record")
    lifted = {str(r.get("id")) for r in rs if r.get("lifted")}
    if lifted != set(LIFTED):
        bad.append("the lifted records are not D05's ten")
    cells: dict[tuple[str, ...], str] = {}
    for r in rs:
        if not r.get("screen"):
            continue
        rid = str(r.get("id"))
        if not str(r.get("fixture", "")).strip():
            bad.append(f"{rid}: no fixture or precondition handle (row 33)")
        sig = tuple(str(r.get(f)) for f in ("screen", "trigger", "exit", "carrier", "announce"))
        if sig in cells:
            bad.append(f"{rid} repeats {cells[sig]}'s cells: nothing selects it (row 7)")
        cells.setdefault(sig, rid)
    return bad


def g_states(t: Texts) -> list[Finding]:
    return fails("G-STATES", states_problems(t))


def g_a11y(t: Texts) -> list[Finding]:
    bad: list[str] = []
    d05 = "\n".join(base_lines("D05"))
    have = {p: set(re.findall(r"^\| (" + p + r"-\d\d) ", d05, re.MULTILINE)) for p in A11Y_RANGES}
    for p, n in A11Y_RANGES.items():
        want = {f"{p}-{i:02d}" for i in range(1, n + 1)}
        if have[p] != want:
            bad.append(f"D05's {p} rows are not {p}-01..{p}-{n:02d}")
        if f"{p}-01..{p}-{n:02d}" not in section(t.spec, A11Y_HEAD):
            bad.append(f"§3.2 does not state {p}-01..{p}-{n:02d}")
    fids = set(re.findall(r"^\| (F-\d\d) ", d05, re.MULTILINE))
    for f in re.findall(r"\bF-\d\d\b", unfence(t.spec)):
        if f not in fids:
            bad.append(f"{f} is no D05 finding")
    es = entries(t)
    for k, e in es.items():
        for ann in anns(e):
            if "lr" in ann and ann.get("lr") not in have["LR"]:
                bad.append(f"{k}: {ann.get('lr')} is no D05 LR row")
    rec = by_id(t)
    for r in rec.values():
        for x in t2s(r):
            if x not in have["T2"]:
                bad.append(f"{r.get('id')}: {x} is no D05 T2 row")
        for key in r.get("speaks") or []:
            if not anns(es.get(str(key), {})):
                bad.append(f"{r.get('id')} speaks {key}, which has no announcement in the deck")
    bad += t2_table_problems(t, es, rec)
    return fails("G-A11Y", bad)


def t2_table_problems(
    t: Texts, es: dict[str, dict[str, Any]], rec: dict[str, dict[str, Any]]
) -> list[str]:
    """Row 10: §5 lifts D05's T2-01..T2-29; every reason a deck key, every id on a record."""
    rows = [r for r in table_rows(section(t.spec, LOOKS_HEAD)) if re.fullmatch(r"T2-\d\d", r[0])]
    bad: list[str] = []
    n = A11Y_RANGES["T2"]
    if [r[0] for r in rows] != [f"T2-{i:02d}" for i in range(1, n + 1)]:
        return [f"§5's T2 table is not T2-01..T2-{n:02d} in order"]
    for r in rows:
        keys = re.findall(r"`(ticket\.[a-z0-9_.]+)`", r[2] if len(r) > 2 else "")
        if not keys or any(k not in es for k in keys):
            bad.append(f"§5 {r[0]}: its reason names no deck key, or one the deck lacks")
        ids = re.findall(r"`((?:SCR|CMP)-\d{3}[/:][^`]+)`", r[-1])
        if not ids or any(r[0] not in t2s(rec.get(i, {})) for i in ids):
            bad.append(f"§5 {r[0]}: its record column names no record carrying {r[0]}")
    return bad


LOCKED_DESC = "ticket.order.arm.locked.description"
SUBMIT_NAME = "ticket.order.submit.name"


def lift_problems(t: Texts) -> list[str]:
    """Each L-row lifted into the deck or a record: D05's replacement reached its target."""
    es, rec = entries(t), by_id(t)
    cells = {r[0]: r[3] for r in ledger_rows(t.spec) if len(r) > 3}

    def amended(key: str, row: str, head: str) -> bool:
        e = es.get(key, {})
        text = parent_form(str(e.get("string", "")), e)
        return e.get("amended") == f"D05 {row}" and text.startswith(head)

    def spoken(key: str, lr: str, politeness: str) -> bool:
        a = anns(es.get(key, {}))
        return any(x.get("lr") == lr and x.get("politeness") == politeness for x in a)

    f02 = quoted_cells("D05", 487, (3,))
    f13 = quoted_cells("D05", 498, (3,))
    desc, name = es.get(LOCKED_DESC, {}), es.get(SUBMIT_NAME, {})
    place = str(rec.get("SCR-077/placement", {}).get("carrier", ""))
    summary = str(rec.get("SCR-060/invalid-summary", {}).get("announce", ""))
    checks = {
        "L-2": bool(f02) and f02[0] in place,
        "L-2 (cell)": bool(f02) and loose(f02[0]) in loose(cells.get("L-2", "")),
        "L-8": amended("ticket.order.arm.locked.description", "F-08", "")
        and "{arm key}" in parent_form(str(desc.get("string")), desc),
        "L-9": summary.startswith("LR-24")
        and spoken("ticket.order.v.summary.heading", "LR-24", "none"),
        "L-10": spoken("ticket.order.arm.refused", "LR-09", "polite"),
        "L-12": spoken("ticket.order.readout.line", "LR-01", "polite"),
        "L-13": bool(f13)
        and amended("ticket.order.submit.name", "F-13", "")
        and parent_form(str(name.get("string")), name) == f13[0],
        "L-14": all(
            amended(k, "F-14", "{confirm label}, ")
            for k in ("ticket.confirm.confirm.name", "ticket.confirm.confirm.name.fanout")
        ),
    }
    bad = [
        f"{row}: D05's replacement has not reached its target"
        for row, ok in checks.items()
        if not ok
    ]
    lifted = {r[0] for r in ledger_rows(t.spec) if len(r) > 2 and disposition(r[2]) == "lifted"}
    for lid, cell in cells.items():
        if lid in lifted and cell.startswith("the deck") and lid not in checks:
            bad.append(f"{lid}: lifted into the deck with no target check")
    return bad


def g_ledger(t: Texts) -> list[Finding]:
    bad: list[str] = lift_problems(t)
    rows = ledger_rows(t.spec)
    if [r[0] for r in rows] != [f"L-{n}" for n in range(1, len(LEDGER_ROWS) + 1)]:
        bad.append("the ledger is not L-1..L-26 in order")
    if [r[1] if len(r) > 1 else "" for r in rows] != list(LEDGER_ROWS):
        bad.append("the ledger's rows are not O0847's twenty-six, in order")
    got = {d: 0 for d in TALLY}
    for r in rows:
        d = disposition(r[2]) if len(r) > 2 else ""
        if d not in got:
            bad.append(f"{r[0]}: disposition {d!r} is outside the vocabulary")
        else:
            got[d] += 1
    if got != TALLY:
        bad.append("the tally is not R919's (BQ-7)")
    return fails("G-LEDGER", bad)


# ---------------------------------------------------------------------------- §C: the A-rows


@dataclass(frozen=True)
class ARow:
    aid: str
    entry: str
    fld: str
    file: str
    line: int
    op: str
    src: str
    old: str
    new: str


OPS = ("replace fragment", "insert after")
ROW_HEAD = re.compile(r"^#### (A-\d+) · (.+?) · (.+)$")
ROW_META = re.compile(r"^`(14|15)`:(\d+) · ([a-z ]+?) · from (.+)$")


def a_rows(spec: str) -> tuple[list[ARow], list[str]]:
    body = lines(section(spec, AROW_HEAD))
    rows: list[ARow] = []
    bad: list[str] = []
    i = 0
    while i < len(body):
        m = ROW_HEAD.match(body[i])
        if not m:
            i += 1
            continue
        meta = ROW_META.match(body[i + 2]) if i + 2 < len(body) else None
        blocks: list[tuple[str, list[str]]] = []
        j = i + 3
        while j < len(body) and not ROW_HEAD.match(body[j]) and len(blocks) < 2:
            if body[j].startswith("```") and len(body[j]) > 3:
                kind, k, buf = body[j][3:], j + 1, []
                while k < len(body) and body[k] != "```":
                    buf.append(body[k])
                    k += 1
                blocks.append((kind, buf))
                j = k
            j += 1
        if not meta or len(blocks) != 2:
            bad.append(f"{m.group(1)}: no meta line or not two fenced blocks")
            i = j
            continue
        (k1, old), (k2, new) = blocks
        op = meta.group(3)
        want = "anchor" if op == "insert after" else "old"
        if k1 != want or k2 != "new" or len(old) != 1:
            bad.append(f"{m.group(1)}: the blocks are not ```{want} (one line) then ```new")
        rows.append(
            ARow(
                m.group(1),
                m.group(2),
                m.group(3),
                meta.group(1),
                int(meta.group(2)),
                op,
                meta.group(4),
                old[0] if old else "",
                "\n".join(new),
            )
        )
        i = j
    return rows, bad


def scope_heading(bl: list[str], idx: int) -> str:
    for k in range(idx, -1, -1):
        if HEADING.match(bl[k]):
            return bl[k]
    return ""


def locate(cur: list[str], bl: list[str], row: ARow) -> int | None:
    frag = row.op == "replace fragment"
    head = scope_heading(bl, row.line - 1)
    starts = [k for k, ln in enumerate(cur) if ln == head]
    if len(starts) != 1:
        return None
    hm = HEADING.match(head)
    level = len(hm.group(1)) if hm else 7
    hits: list[int] = []
    for k in range(starts[0] + 1, len(cur)):
        m = HEADING.match(cur[k])
        if m and len(m.group(1)) <= level:
            break
        if (row.old in cur[k]) if frag else (cur[k] == row.old):
            hits.append(k)
    return hits[0] if len(hits) == 1 else None


def apply_rows(text: str, base_text: str, rows: list[ARow], file: str) -> str | None:
    cur, bl = lines(text), lines(base_text)
    edits: list[tuple[int, int, ARow]] = []
    for r in rows:
        if r.file != file:
            continue
        k = locate(cur, bl, r)
        if k is None:
            return None
        edits.append((k, 0 if r.op == "insert after" else 1, r))
    for k, _, r in sorted(edits, key=lambda e: (e[0], e[1]), reverse=True):
        if r.op == "replace fragment":
            cur[k] = cur[k].replace(r.old, r.new, 1)
        else:
            cur[k + 1 : k + 1] = lines(r.new)
    return "\n".join(cur)


def export(rows: list[ARow]) -> list[dict[str, Any]]:
    return [
        {
            "id": r.aid,
            "target_file": TARGETS[r.file],
            "line": r.line,
            "op": r.op,
            "entry": r.entry,
            "field": r.fld,
            "from": r.src,
            "anchor" if r.op == "insert after" else "old": r.old,
            "new": r.new,
        }
        for r in rows
    ]


def g_arow(t: Texts) -> list[Finding]:
    rows, bad = a_rows(t.spec)
    if not rows:
        bad.append("§12.3 has no A-rows")
    for n, r in enumerate(rows, 1):
        if r.aid != f"A-{n}":
            bad.append(f"{r.aid}: out of order (expected A-{n})")
        if r.op not in OPS:
            bad.append(f"{r.aid}: unknown op {r.op!r}")
            continue
        bl = list(base_lines(r.file))
        at = bl[r.line - 1] if 1 <= r.line <= len(bl) else ""
        if (at.count(r.old) != 1) if r.op == "replace fragment" else (at != r.old):
            bad.append(
                f"{r.aid}: the Old is not `{r.file}`:{r.line} (or not once in it) at the base"
            )
            continue
        if locate(bl, bl, r) != r.line - 1:
            bad.append(f"{r.aid}: the Old is not unique in its scope")
    return fails("G-AROW", bad)


def changed_paths() -> tuple[str, ...] | None:
    mb = git("merge-base", "HEAD", HEAD)
    if mb is None:
        return None
    committed = git("diff", "--name-only", mb.strip(), "--")
    status = git("status", "--porcelain", "--untracked-files=all")
    if committed is None or status is None:
        return None
    paths = {p for p in committed.split("\n") if p}
    for ln in status.split("\n"):
        if ln.strip():
            paths.add(ln[3:].split(" -> ")[-1].strip('"'))
    return tuple(sorted(paths))


def g_untouched(t: Texts) -> list[Finding]:
    if t.changed is None:
        return fails("G-UNTOUCHED", ["git cannot name the changed paths (fail closed)"])
    if SPEC_REL in t.changed or t.mbase_spec is None:  # PR 1: only the pack's five files
        return fails(
            "G-UNTOUCHED",
            [
                f"PR 1 changes {p}, not one of the pack's five"
                for p in t.changed
                if p not in OWN_PATHS
            ],
        )
    bad = [
        f"PR 2 changes {p}, not `14`, `15` or the pins"
        for p in t.changed
        if p not in (*TARGETS.values(), PINS_REL)
    ]
    rows, _ = a_rows(t.spec)
    now, mb = dict(t.now), dict(t.mbase)
    for key in TARGETS:
        want = apply_rows(mb.get(key, ""), "\n".join(base_lines(key)), rows, key)
        if want is None:
            bad.append(f"PR 2: a §12.3 row for `{key}` cannot be re-pointed at the merge-base")
        elif now.get(key) != want:
            bad.append(f"PR 2: `{key}` is not the merge-base with §12.3 applied, byte for byte")
    return fails("G-UNTOUCHED", bad)


# ---------------------------------------------------------------------------- tokens, hex, icons


@cache
def token_names() -> frozenset[str]:
    names: set[str] = set()

    def walk(d: object, path: list[str]) -> None:
        if isinstance(d, dict):
            if "$value" in d:
                names.add(".".join(path))
                return
            for k, v in d.items():
                if not k.startswith("$"):
                    walk(v, path + [k])

    listing = git("ls-tree", "--name-only", f"{BASE}:{DS_JSON_DIR}") or ""
    for f in listing.split():
        if f.endswith(".tokens.json"):
            try:
                walk(json.loads(at_base(f"{DS_JSON_DIR}/{f}") or "{}"), [])
            except json.JSONDecodeError:
                continue
    return frozenset(names)


TOKEN_NAME = re.compile(r"`([a-z][a-z0-9-]*(?:\.[a-z0-9-]+)+(?:\.\*)?)`")


def g_tokens(t: Texts) -> list[Finding]:
    body = section(t.spec, REDLINE_HEAD)
    names = token_names()
    bad: list[str] = []
    exc_start = body.find("**Exceptions**")
    main, exc = (body[:exc_start], body[exc_start:]) if exc_start >= 0 else (body, "")
    for m in TOKEN_NAME.finditer(main):
        n = m.group(1)
        if n.endswith(".*"):
            if not any(x.startswith(n[:-1]) for x in names):
                bad.append(f"§8 names {n}, which matches no token")
        elif n not in names:
            bad.append(f"§8 names {n}, which does not resolve at the base")
    for m in TOKEN_NAME.finditer(exc):
        if m.group(1) in names:
            bad.append(f"§8's exception {m.group(1)} already resolves (not a request)")
    if not names:
        bad.append("the token JSON is unreadable at the base")
    return fails("G-TOKENS", bad)


HEXLIT = re.compile(r"(?<![\w&])#[0-9A-Fa-f]{6}(?![0-9A-Za-z])|\brgba?\(|\bhsla?\(")
PX = re.compile(r"\b\d+(?:\.\d+)? ?px\b")


def g_hex(t: Texts) -> list[Finding]:
    bad: list[str] = []
    for name, text in (("spec", t.spec), ("deck", t.deck), ("inventory", t.states)):
        for m in HEXLIT.finditer(text):
            bad.append(f"{name}: a colour literal at offset {m.start()}")
    for name, text in (
        ("§8", section(t.spec, REDLINE_HEAD)),
        ("deck", t.deck),
        ("inventory", t.states),
    ):
        for m in PX.finditer(text):
            bad.append(f"{name}: a raw dimension {m.group(0)!r} (name its token)")
    return fails("G-HEX", bad)


@cache
def registry() -> dict[str, str]:
    t = "\n".join(base_lines("ICONS"))
    return {
        m.group(1): m.group(2)
        for m in re.finditer(
            r'^  "?([a-z0-9-]+)"?: \{\n(?:.*\n){0,3}?    description: "([^"]*)"', t, re.MULTILINE
        )
    }


def g_icons(t: Texts) -> list[Finding]:
    bad: list[str] = []
    reg = registry()
    gids = row_ids(t.spec, GROW_HEAD, "G")
    listed: set[str] = set()
    for r in table_rows(section(t.spec, ICON_HEAD)):
        if len(r) < 3:
            continue
        listed |= set(re.findall(r"`(icon/[a-z-]+)`", r[0]))
        m = re.fullmatch(r"`([a-z0-9-]+)`", r[1])
        if m:
            q = re.findall(r'"([^"]*)"', r[2])
            if m.group(1) not in reg:
                bad.append(f"§9: {m.group(1)} is not in the registry at the base")
            elif not q or q[0] != reg[m.group(1)]:
                bad.append(f"§9: {m.group(1)}'s description is not the registry's")
        else:
            g = re.search(r"none — (G-\d+)", r[1])
            if not g or g.group(1) not in gids:
                bad.append(f"§9: {r[0][:30]} maps to nothing and names no G-row")
    d04 = set(re.findall(r"`(icon/[a-z-]+)`", "\n".join(base_lines("D04")[283:296])))
    for n in sorted(d04 - listed):
        bad.append(f"§9 lacks D04 §3.3's {n}")
    return fails("G-ICONS", bad)


@cache
def act_names() -> frozenset[str]:
    return frozenset(
        re.findall(r'^\s+"([a-z_]+\.[a-z_.]+)",', "\n".join(base_lines("ACT")), re.MULTILINE)
    )


# BQ-17's sources: `14`'s Analytics / Audit line of each pack screen, and D03 §15's event column
EVENT_LINES = (("14", 1440), ("14", 1474), ("14", 1772), ("14", 1783), ("14", 2401), ("14", 3115))
D03_EVENTS = (611, 619)
EVENT_NAME = re.compile(r"`([a-z_]+\.[a-z_]+|_[a-z_]+)`")
CLASSES = ("audit", "analytics", "audit · analytics", "none")


def source_events() -> list[str]:
    cells = [base_line(k, n) for k, n in EVENT_LINES]
    cells += [split_row(base_line("D03", n))[0] for n in range(D03_EVENTS[0], D03_EVENTS[1] + 1)]
    out: list[str] = []
    for cell in cells:
        last = ""
        for m in EVENT_NAME.finditer(cell):
            name = m.group(1)
            if name.startswith("_"):  # D03's `order.rejection_viewed` / `_payload_expanded`
                name = last.rsplit("_", 1)[0] + name
            else:
                last = name
            out.append(name)
    return list(dict.fromkeys(out))


def in_g17(name: str, g17: str) -> bool:
    return f"`{name}`" in g17 or any(
        f"`{p}*`" in g17 and name.startswith(p) for p in ("order.confirmation_", "order.rejection_")
    )


def g_events(t: Texts) -> list[Finding]:
    bad: list[str] = []
    acts = act_names()
    g17 = " ".join(" ".join(r) for r in table_rows(section(t.spec, GROW_HEAD)) if r[0] == "G-17")
    crows = " ".join(" ".join(r) for r in table_rows(section(t.spec, CROW_HEAD)))
    obs = section(t.spec, EVENTS_HEAD)
    named: set[str] = set()
    for r in records(t):
        if not r.get("screen"):
            continue
        rid, ev, cls = str(r.get("id")), r.get("event"), r.get("class")
        if cls not in CLASSES:
            bad.append(f"{rid}: class {cls!r}")
        pairs = r.get("audit_action") or {}
        if not isinstance(pairs, dict):
            bad.append(f"{rid}: audit_action is not a map of event to action")
            pairs = {}
        for name, act in pairs.items():
            if act not in acts:
                bad.append(f"{rid}: {act} is not a registered audit action")
            elif f"`{name}` / `{act}`" not in obs:
                bad.append(f"{rid}: the pair {name} / {act} is not in §10 (C-10)")
        if not ev:
            continue
        for name in str(ev).split(" / "):
            named.add(name)
            if name in acts or name in pairs:
                continue
            if not in_g17(name, g17):
                bad.append(f"{rid}: {name} is neither registered nor in G-17")
    for name in source_events():
        if name not in named and not in_g17(name, g17) and f"`{name}`" not in crows:
            bad.append(f"{name} (`14` / D03 §15) is on no record, in no G-17 and no C-row")
    return fails("G-EVENTS", bad)


ID_REF = re.compile(r"(?<![\w-])([CGQ])-([1-9]\d*)(?![\w])")
DUE = re.compile(r"^(?:\d{4}-\d{2}-\d{2}(?:<!--=[^>]+-->)?|at once)$")


def g_rows(t: Texts) -> list[Finding]:
    bad: list[str] = []
    have: dict[str, set[str]] = {}
    for head, p in ((CROW_HEAD, "C"), (GROW_HEAD, "G"), (QROW_HEAD, "Q")):
        rows = table_rows(section(t.spec, head))
        ids = [r[0] for r in rows]
        if ids != [f"{p}-{n}" for n in range(1, len(ids) + 1)]:
            bad.append(f"the {p}-rows are not {p}-1..{p}-{len(ids)} in order")
        have[p] = set(ids)
        for r in rows:
            if len(r) < 3 or not r[-1 if p == "C" else 2].strip():
                bad.append(f"{r[0]}: no owner")
            if p in "GQ" and (len(r) < 4 or not DUE.match(r[3].strip())):
                bad.append(f"{r[0]}: no due date")
    refs = [unfence(t.spec), t.deck, t.states]
    for text in refs:
        for m in ID_REF.finditer(text):
            if f"{m.group(1)}-{m.group(2)}" not in have[m.group(1)]:
                bad.append(f"{m.group(1)}-{m.group(2)} is referenced but no row carries it")
    return fails("G-ROWS", sorted(set(bad)))


def g_walk(t: Texts) -> list[Finding]:
    bad: list[str] = []
    titles = heading_titles(t.spec)
    secs = {m.group(1) for x in titles if (m := re.match(r"(\d+(?:\.\d+)?)\.? ", x))}
    rec = by_id(t)
    led = {r[0] for r in ledger_rows(t.spec)}
    gids = row_ids(t.spec, GROW_HEAD, "G")
    consumers = section(t.spec, CONSUMER_HEAD)
    for r in table_rows(section(t.spec, WALK_HEAD)):
        if len(r) < 2:
            continue
        num = re.search(r"#\d+", r[0])
        if num and num.group(0) not in consumers:
            bad.append(f"{r[0]}: no hand-off comment in §13.1")
        need = r[1]
        for s in re.findall(r"§(\d+(?:\.\d+)?)", need):
            if s not in secs:
                bad.append(f"{r[0]}: §{s} is no heading")
        for x in re.findall(r"`((?:SCR|CMP)-\d{3}/[a-z0-9-]+)`", need):
            if x not in rec:
                bad.append(f"{r[0]}: {x} is no inventory record")
        for x in re.findall(r"the deck `([a-z]+)`", need):
            if x not in SURFACES:
                bad.append(f"{r[0]}: the deck has no surface {x}")
        for x in re.findall(r"\bL-\d+\b", need):
            if x not in led:
                bad.append(f"{r[0]}: {x} is no ledger row")
        for x in re.findall(r"\bG-\d+\b", need):
            if x not in gids:
                bad.append(f"{r[0]}: {x} is no G-row")
    readers = table_rows(section(t.spec, READER_HEAD))
    if not readers:
        bad.append("§13.3 has no outside-reader row")
    for r in readers:
        rec_cell = r[-1] if r else ""
        if rec_cell.startswith("pending"):
            if STRICT_WALK:
                bad.append("the outside reader's row is still pending (--strict-walk)")
        elif not re.fullmatch(r"#919 comment \d{8,}", rec_cell):
            bad.append(f"the outside reader's record {rec_cell!r} is neither pending nor a comment")
    return fails("G-WALK", bad)


def g_ruled(t: Texts) -> list[Finding]:
    bad: list[str] = []
    heads = heading_titles(t.spec)
    for h in (RULED_HEAD, A50_HEAD):
        if not any(x.startswith(h) and STAMP in x for x in heads):
            bad.append(f"the heading {h!r} lacks the stamp")
    for q in RULING_QUOTES:
        if q not in t.spec and q not in t.deck:
            bad.append(f"R919's words {q[:40]!r} are not in the pack")
    rows = table_rows(section(t.spec, A50_HEAD))
    es = entries(t)
    if [r[0] for r in rows] != [str(n) for n in A50]:
        bad.append("§6.2 is not A50 items 1..10 in order")
    for r in rows:
        n = int(r[0]) if r[0].isdigit() else 0
        key, s = A50.get(n, ("", ""))
        if r[1] != f"`{key}`" or r[2] != f'"{s}"' or es.get(key, {}).get("string") != s:
            bad.append(f"§6.2 row {r[0]} is not A50 item {r[0]} as the deck holds it")
    if sum(e.get("status") == "ruled" for e in es.values()) != len(A50):
        bad.append("the deck's ruled entries are not A50's ten")
    for i in (BQ_LIST_ID, RULING_ID, A50_ID):
        if i not in t.spec:
            bad.append(f"the pack does not cite {i}")
    return fails("G-RULED", bad)


# The lane's public-text list, held reversed so this file never spells a word it forbids.
_HIDDEN = (
    "kael",
    "desopxe",
    "ssapyb",
    "tiolpxe",
    "kcatta",
    "elcaro",
    "laever",
    "dednuobnu",
    "doolf",
    "llats",
    "yrosivda",
    "ashg",
    "htua-erp",
)
BANNED = re.compile(
    "|".join(re.escape(w[::-1]) for w in _HIDDEN) + r"|\b" + "sod"[::-1] + r"\b", re.IGNORECASE
)
LOCAL_PATH = re.compile("/" + "(?:home|Users|mnt|tmp)" + r"/[^\s`)]+")
HOSTNAME = re.compile(r"\b[a-z0-9-]+\.(?:com|net|org)\b|\bpenpot\.[a-z0-9-]+\.", re.IGNORECASE)
UUID = re.compile(r"\b[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}\b")
URL = re.compile(r"https?://", re.IGNORECASE)
CLOSING = re.compile(
    r"\b(?:close[sd]?|fix(?:e[sd])?|resolve[sd]?)\s*:?\s*(?:[\w-]+/[\w-]+)?#\d+", re.IGNORECASE
)
# an agent or session name, by shape only: a lowercase hyphenated word chain ending in a number
# (never inside an id or a path), or a session hex id; a state name of the inventory is exempt
AGENTS = re.compile(r"(?<![/\w-])[a-z]+(?:-[a-z]+)+-\d+\b|\bsession [0-9a-f]{8}")


@cache
def page_ids() -> frozenset[str]:
    out: set[str] = set()
    for key in ("D02", "D03", "D04"):
        for ln in base_lines(key)[:80]:
            if "page" in ln.lower():
                out |= set(UUID.findall(ln))
    return frozenset(out)


def g_public(t: Texts) -> list[Finding]:
    bad: list[str] = []
    state_names = {str(r.get("state", "")) for r in records(t)}
    for name, text in (("spec", t.spec), ("deck", t.deck), ("inventory", t.states)):
        for rx, what in (
            (BANNED, "a word on the public-text list"),
            (LOCAL_PATH, "a local path"),
            (HOSTNAME, "a host name"),
            (URL, "a URL"),
            (CLOSING, "a closing keyword"),
            (AGENTS, "an agent or session name"),
        ):
            for m in rx.finditer(text):
                if rx is AGENTS and m.group(0) in state_names:
                    continue
                bad.append(f"{name}: {what} ({m.group(0)[:3]}..., offset {m.start()})")
        for m in UUID.finditer(text):
            if m.group(0) not in page_ids():
                bad.append(f"{name}: a uuid that is not a parent page id (offset {m.start()})")
    return fails("G-PUBLIC", bad)


# ---------------------------------------------------------------------------- pins

FULL_STOP = re.compile(r"(?<=[.!?])\s+(?=[*`\"(A-Z0-9§])")


def pin_norm(text: str) -> str:
    return " ".join(unicodedata.normalize("NFKC", text).split())


def units(text: str) -> list[Unit]:
    out: list[Unit] = []
    path: list[tuple[int, str]] = []
    seen: dict[str, int] = {}
    region, k, fence = "spec:(top)#1", 0, -1
    rows: dict[str, int] = {}
    buf: list[str] = []
    for raw in lines(unfill(text)):
        if fence >= 0:
            if raw == "```":
                digest = hashlib.sha256("\n".join(buf).encode("utf-8")).hexdigest()[:16]
                out.append((region, f"fence {fence}", f"{len(buf)} lines sha256:{digest}"))
                fence, buf = -1, []
            else:
                buf.append(raw)
            continue
        if FENCE.match(raw):
            k += 1
            fence = k
            continue
        m = HEADING.match(raw)
        if m:
            level = len(m.group(1))
            path = [p for p in path if p[0] < level] + [(level, pin_norm(m.group(2)))]
            key = "spec:" + " › ".join(p[1] for p in path)
            seen[key] = seen.get(key, 0) + 1
            region, k, rows = f"{key}#{seen[key]}", 0, {}
            out.append((region, "heading", pin_norm(raw)))
            continue
        if not raw.strip() or RULE_ROW.match(raw):
            continue
        if raw.lstrip().startswith("|"):
            cells = split_row(raw)
            lead = pin_norm(cells[0]) if cells else "(blank)"
            rows[lead] = rows.get(lead, 0) + 1
            loc = f"row {lead}" + (f"#{rows[lead]}" if rows[lead] > 1 else "")
            out.append((region, loc, " | ".join(pin_norm(c) for c in cells)))
            continue
        for x in FULL_STOP.split(raw.strip()):
            if x.strip():
                k += 1
                out.append((region, f"s{k}", pin_norm(x)))
    return out


def all_units(t: Texts) -> list[Unit]:
    out = units(t.spec)
    for k, e in entries(t).items():
        out.append(("deck", k, json.dumps(e, ensure_ascii=False, sort_keys=True)))
    for r in records(t):
        out.append(
            ("inventory", str(r.get("id")), json.dumps(r, ensure_ascii=False, sort_keys=True))
        )
    return out


def write_pins(us: list[Unit]) -> str:
    head = (
        "# E30-D06 pins (every unit of the pack, every deck entry, every inventory record): "
        f"region, location, the exact normalised text; {len(us)} units.\n# Written by "
        "`--repin-ruled` only; `--check` reads it (never hand-edit; see the tool's G-RULED-PIN).\n"
    )
    return head + "".join("\t".join(u) + "\n" for u in us)


def parse_pins(text: str) -> list[Unit]:
    out: list[Unit] = []
    for ln in lines(text):
        parts = ln.split("\t")
        if ln and not ln.startswith("#") and len(parts) == 3:
            out.append((parts[0], parts[1], parts[2]))
    return out


def pin_problems(pinned: list[Unit], current: list[Unit]) -> list[str]:
    if not pinned:
        return ["the pins file is empty or missing (run --repin-ruled)"]
    bad: list[str] = []
    by_old: dict[str, list[tuple[str, str]]] = {}
    by_new: dict[str, list[tuple[str, str]]] = {}
    for r, loc, txt in pinned:
        by_old.setdefault(r, []).append((loc, txt))
    for r, loc, txt in current:
        by_new.setdefault(r, []).append((loc, txt))
    for r in by_new:
        if r not in by_old:
            bad.append(f"region '{r[-60:]}' is unpinned (new)")
    for r in by_old:
        if r not in by_new:
            bad.append(f"region '{r[-60:]}' deleted or renamed")
    for r, now_units in by_new.items():
        if r in by_old and now_units != by_old[r]:
            was = dict(by_old[r])
            what = "units moved or reordered"
            for loc, txt in now_units:
                if was.get(loc) != txt:
                    what = f"{loc[:30]} changed: {txt[:30]!r}"
                    break
            bad.append(f"'{r[-40:]}' {what}")
    return bad


def g_ruled_pin(t: Texts) -> list[Finding]:
    return fails("G-RULED-PIN", pin_problems(parse_pins(t.pins), all_units(t)))


# ---------------------------------------------------------------------------- run

GATES: tuple[tuple[str, Callable[[Texts], list[Finding]]], ...] = (
    ("G-ANCHOR", g_anchor),
    ("G-MARKER", g_marker),
    ("G-CITE", g_cite),
    ("G-VERSION", g_version),
    ("G-QUOTE", g_quote),
    ("G-DECK", g_deck),
    ("G-ONCE", g_once),
    ("G-FIXTURE", g_fixture),
    ("G-CODES", g_codes),
    ("G-NATIVE", g_native),
    ("G-STATES", g_states),
    ("G-A11Y", g_a11y),
    ("G-LEDGER", g_ledger),
    ("G-AROW", g_arow),
    ("G-UNTOUCHED", g_untouched),
    ("G-TOKENS", g_tokens),
    ("G-HEX", g_hex),
    ("G-ICONS", g_icons),
    ("G-EVENTS", g_events),
    ("G-ROWS", g_rows),
    ("G-WALK", g_walk),
    ("G-RULED", g_ruled),
    ("G-PUBLIC", g_public),
    ("G-RULED-PIN", g_ruled_pin),
)


def run(t: Texts) -> list[Finding]:
    out: list[Finding] = []
    for _, fn in GATES:
        out += fn(t)
    if any(f.level == "FAIL" and f.gate != "G-RULED-PIN" for f in out):
        out = [replace(f, level="NOTE") if f.gate == "G-RULED-PIN" else f for f in out]
    return out


def load() -> Texts:
    mb = git("merge-base", "HEAD", HEAD)
    mbase = (
        tuple((k, git("show", f"{mb.strip()}:{rel}") or "") for k, rel in TARGETS.items())
        if mb
        else ()
    )
    return Texts(
        spec=read(SPEC_REL),
        deck=read(DECK_REL),
        states=read(STATES_REL),
        pins=read(PINS_REL),
        changed=changed_paths(),
        now=tuple((k, read(rel)) for k, rel in TARGETS.items()),
        mbase=mbase,
        mbase_spec=git("show", f"{mb.strip()}:{SPEC_REL}") if mb else None,
    )


# ---------------------------------------------------------------------------- the self-test


def _sub(field_name: str, old: str, new: str) -> Callable[[Texts], Texts]:
    def f(t: Texts) -> Texts:
        text = getattr(t, field_name)
        if text.count(old) < 1:
            raise SystemExit(f"self-test: {old[:50]!r} not found in {field_name}")
        kw: dict[str, Any] = {field_name: text.replace(old, new, 1)}
        return replace(t, **kw)

    return f


def _re(field_name: str, pattern: str, new: str) -> Callable[[Texts], Texts]:
    def f(t: Texts) -> Texts:
        text = getattr(t, field_name)
        out, n = re.subn(pattern, new, text, count=1, flags=re.MULTILINE)
        if n != 1:
            raise SystemExit(f"self-test: {pattern[:50]!r} not found in {field_name}")
        kw: dict[str, Any] = {field_name: out}
        return replace(t, **kw)

    return f


def _deck(fn: Callable[[dict[str, Any]], None]) -> Callable[[Texts], Texts]:
    def f(t: Texts) -> Texts:
        d = json.loads(t.deck)
        fn(d)
        return replace(t, deck=json.dumps(d, ensure_ascii=False, indent=2))

    return f


def _states(fn: Callable[[dict[str, Any]], None]) -> Callable[[Texts], Texts]:
    def f(t: Texts) -> Texts:
        d = json.loads(t.states)
        fn(d)
        return replace(t, states=json.dumps(d, ensure_ascii=False, indent=2))

    return f


def _entry(key: str, fld: str, value: object) -> Callable[[dict[str, Any]], None]:
    def f(d: dict[str, Any]) -> None:
        d["strings"][key][fld] = value

    return f


def _record(rid: str, fld: str, value: object) -> Callable[[dict[str, Any]], None]:
    def f(d: dict[str, Any]) -> None:
        for r in d["records"]:
            if r["id"] == rid:
                r[fld] = value

    return f


def _head_edit(t: Texts) -> Texts:
    rel = KEYS["D05"]
    text = at_rev(HEAD, rel) or ""
    HEAD_OVERRIDE.append(
        (
            rel,
            text.replace("One row per action across the seven surfaces.", "One row per action.", 1),
        )
    )
    return t


def _pr1_extra(t: Texts) -> Texts:
    return replace(t, changed=(*(t.changed or ()), "docs/plan/16-design-system-brief.md"))


def _fixed_drop(d: dict[str, Any]) -> None:
    d["strings"]["ticket.order.type.emulated.reason"].pop("fixed")


def _nc_moved(d: dict[str, Any]) -> None:
    for x in d["not_carried"]:
        if x.get("superseded_by") == "ticket.order.submit.name":
            x["superseded_by"] = "ticket.order.submit.label.limit"


def _a50_dropped(d: dict[str, Any]) -> None:
    e = d["strings"]["ticket.order.frozen.reason"]
    e["sources"] = [x for x in e["sources"] if not str(x["cite"]).startswith("A50 ")]


def _security_moved(d: dict[str, Any]) -> None:
    # the count stays 35: the flag moves off a non-selector §6.4 entry onto an unflagged one
    d["strings"]["ticket.reject.record.never_stored"].pop("security")
    d["strings"]["ticket.defaults.title"]["security"] = True


def _readout_loud(d: dict[str, Any]) -> None:
    d["strings"]["ticket.order.readout.line"]["announce"]["politeness"] = "assertive"


def _twin_string(d: dict[str, Any]) -> None:
    ask, bid = (
        d["strings"]["ticket.hotkeys.ticket.snap_ask"],
        d["strings"]["ticket.hotkeys.ticket.snap_bid"],
    )
    bid["string"], bid["sources"] = ask["string"], ask["sources"]


def _code_twice(d: dict[str, Any]) -> None:
    d["strings"]["ticket.ratelimit.scope.exchange"]["codes"].append("problem:rate_limited")
    d["by_code"]["problem:rate_limited"]["ratelimit"] = "ticket.ratelimit.scope.exchange"


def _code_untrue(d: dict[str, Any]) -> None:
    d["strings"]["ticket.order.rejected.class.transient"]["codes"].append("oms:INSUFFICIENT_MARGIN")
    d["by_code"]["oms:INSUFFICIENT_MARGIN"]["order"] = "ticket.order.rejected.class.transient"


def _code_retcode(d: dict[str, Any]) -> None:
    e = d["strings"]["ticket.reject.reason.risk_tier"]
    e["codes"] = ["oms:RISK_LIMIT_EXCEEDED:110013"]
    bc = d["by_code"]
    bc["oms:RISK_LIMIT_EXCEEDED:110013"] = bc.pop("oms:RISK_LIMIT_EXCEEDED")
    d["by_code"] = dict(sorted(bc.items()))


MUTATIONS: tuple[tuple[str, str, Callable[[Texts], Texts]], ...] = (
    (
        "G-ANCHOR",
        "an unfilled placeholder in §0",
        _sub("spec", "## 0. Status", "## 0. Status {{COUNT:gates}}"),
    ),
    (
        "G-MARKER",
        "a free HTML comment in §0",
        _sub("spec", "## 0. Status", "## 0. Status <!-- x -->"),
    ),
    ("G-CITE", "a cite past the end of D03H", _sub("spec", "D03H:24–62", "D03H:24–6200")),
    ("G-VERSION", "a cited D05 sentence edited at origin/main", _head_edit),
    (
        "G-QUOTE",
        "a quoted sentence no source holds",
        _sub(
            "spec",
            "## 0. Status and evidence",
            '## 0. Status and evidence "an invented quotation here"',
        ),
    ),
    (
        "G-DECK",
        "a source cite one line off",
        _deck(
            _entry(
                "ticket.defaults.title",
                "sources",
                [{"cite": "`D03`:511", "text": "Trading defaults"}],
            )
        ),
    ),
    ("G-ONCE", "one string under two keys", _deck(_twin_string)),
    (
        "G-ONCE",
        "one merged key with two strings on a surface",
        _deck(_entry("ticket.defaults.dirty", "alias", ["defaults.dirty", "defaults.saving"])),
    ),
    ("G-DECK", "an amended entry's parent superseded by another key", _deck(_nc_moved)),
    ("G-DECK", "a ruled entry without its A50 cite", _deck(_a50_dropped)),
    ("G-DECK", "a §6.4 entry outside the selector set unflagged", _deck(_security_moved)),
    ("G-FIXTURE", "a digit outside a parameter with no `fixed`", _deck(_fixed_drop)),
    ("G-CODES", "a retCode as a code", _deck(_code_retcode)),
    ("G-CODES", "one code resolving to two keys on a surface", _deck(_code_twice)),
    ("G-CODES", "a code whose target sentence names another cause (row 3)", _deck(_code_untrue)),
    (
        "G-NATIVE",
        "the frozen record gates Flatten now",
        _states(_record("SCR-060/frozen", "gated", "the submit and Flatten now")),
    ),
    (
        "G-NATIVE",
        "an 'every order' native-SL string drops out of its C-row",
        _sub("spec", "`ticket.defaults.stop.kept`", "the kept-stop line"),
    ),
    (
        "G-NATIVE",
        "A-3 narrows C-2.6's scope",
        _sub("spec", " in every environment, including every leg of a trade-group fan-out,", ""),
    ),
    (
        "G-STATES",
        "a record's twin names no token",
        _states(_record("SCR-060/partially-filled", "twin", "14:steady")),
    ),
    (
        "G-STATES",
        "a `15` States token left without a record",
        _states(_record("CMP-231:option-focused", "twin", "C-3")),
    ),
    (
        "G-A11Y",
        "an LR id D05 lacks",
        _deck(
            _entry(
                "ticket.defaults.stop.kept",
                "announce",
                {"lr": "LR-99", "politeness": "polite", "rate": "once", "cite": "`D05`:320"},
            )
        ),
    ),
    ("G-LEDGER", "a ledger row that is not O0847's", _re("spec", r"^(\| L-22 \| )C-o", r"\1C-q")),
    ("G-LEDGER", "the read-out line loses LR-01's politeness (L-12)", _deck(_readout_loud)),
    (
        "G-LEDGER",
        "SCR-077's placement loses F-02's conditions (L-2)",
        _states(_record("SCR-077/placement", "carrier", "placement (never covers the focus)")),
    ),
    (
        "G-AROW",
        "an A-row's Old edited",
        _sub("spec", "CMP-069 InfoPanel.\n```", "CMP-069 InfoPane.\n```"),
    ),
    ("G-UNTOUCHED", "PR 1 changes a plan file", _pr1_extra),
    (
        "G-TOKENS",
        "a token name that does not resolve",
        _sub("spec", "`size.control.compact`", "`size.control.tiny`"),
    ),
    (
        "G-HEX",
        "a colour literal in §8",
        _sub(
            "spec",
            "## 8. Redlines and tokens by name (BQ-18)",
            "## 8. Redlines and tokens by name (BQ-18) #12AB9F",
        ),
    ),
    (
        "G-ICONS",
        "a registry name the registry lacks",
        _re("spec", r"^(\| `icon/warning`\s+\| )`warning`", r"\1`warnings`"),
    ),
    (
        "G-EVENTS",
        "an audit action the registry lacks",
        _states(
            _record(
                "SCR-114/saved", "audit_action", {"trading_defaults.changed": "settings.changed"}
            )
        ),
    ),
    (
        "G-EVENTS",
        "a D03 §15 event dropped from its record (completeness)",
        _states(_record("SCR-077/record-served", "event", "order.rejection_payload_expanded")),
    ),
    (
        "G-ROWS",
        "a G-row with no due date",
        _re("spec", r"^(\| G-18 \|.*\| )at once(\s*\|)$", r"\1later\2"),
    ),
    (
        "G-WALK",
        "the outside reader's record names no comment",
        _sub("spec", "#919 comment 6532243963", "#919 comment 65"),
    ),
    (
        "G-RULED",
        "the stamp dropped from §6.2",
        _sub(
            "spec", "### 6.2 The ruled strings (A50; RULED", "### 6.2 The ruled strings (A50; ruled"
        ),
    ),
    (
        "G-PUBLIC",
        "a closing keyword in §0",
        _sub(
            "spec", "## 0. Status and evidence", "## 0. Status and evidence (" + "Clo" + "ses #919)"
        ),
    ),
    (
        "G-PUBLIC",
        "an agent-shaped name in §0",
        _sub("spec", "## 0. Status and evidence", "## 0. Status and evidence (ab-cdefg-1)"),
    ),
    (
        "G-RULED-PIN",
        "one word of §14.2 changed",
        _sub("spec", "the spec runs past", "the spec still runs past"),
    ),
)


def fail_keys(fs: list[Finding]) -> list[tuple[str, str]]:
    return [(f.gate, f.msg) for f in fs if f.level == "FAIL"]


def digests() -> dict[str, str]:
    return {p: hashlib.sha256(read(p).encode("utf-8")).hexdigest() for p in OWN_PATHS}


def self_test(t: Texts) -> list[str]:
    before = digests()
    base = fail_keys(run(t))
    bad: list[str] = []
    for n, (gate, desc, fn) in enumerate(MUTATIONS, 1):
        try:
            got = fail_keys(run(fn(t)))
        finally:
            HEAD_OVERRIDE.clear()
            STRICT_WALK.clear()
        new = [k for k in got if k not in base]
        if len(new) != 1 or new[0][0] != gate:
            shown = ", ".join(f"{g}: {m[:50]}" for g, m in new[:3]) or "none"
            bad.append(f"M-{n} ({gate}, {desc}): {len(new)} new FAIL(s) [{shown}]")
    covered = {g for g, _d, _f in MUTATIONS}
    bad += [f"{g}: no mutation" for g, _fn in GATES if g not in covered]
    if fail_keys(run(t)) != base:
        bad.append("self-test: a re-run does not reproduce the base result")
    if digests() != before:
        bad.append("self-test: a file on disk changed")
    return bad


# ---------------------------------------------------------------------------- main


def write_if_changed(rel: str, text: str) -> bool:
    if read(rel) == text:
        return False
    (ROOT / rel).write_text(text, encoding="utf-8")
    return True


def main(argv: list[str]) -> int:
    ap = argparse.ArgumentParser(description=(__doc__ or "").splitlines()[0])
    ap.add_argument("--check", action="store_true", help="exit 1 on any FAIL")
    ap.add_argument("--json", action="store_true", help="print the values and findings as JSON")
    ap.add_argument("--fill", action="store_true", help="fill the placeholders")
    ap.add_argument("--self-test", action="store_true", help="one mutation per gate")
    ap.add_argument("--repin-ruled", action="store_true", help="rewrite the pins file")
    ap.add_argument("--a-rows", action="store_true", help="print §12.3 as JSON (PR 2)")
    ap.add_argument("--strict-walk", action="store_true", help="a pending reader row FAILs")
    args = ap.parse_args(argv)
    if any(at_base(rel) is None for rel in KEYS.values()):
        print(f"FAIL [G-CITE] the inputs are unreadable at {BASE} (fetch first)")
        return 1
    if args.strict_walk:
        STRICT_WALK.append(True)
    t = load()
    if args.a_rows:
        print(json.dumps(export(a_rows(t.spec)[0]), ensure_ascii=False, indent=1))
        return 0
    if args.fill:
        text, missing = fill(ANCHORED.sub(lambda m: "{{" + m.group(2) + "}}", t.spec), compute(t))
        for key in missing:
            print(f"no value for {key}")
        write_if_changed(SPEC_REL, text)
        t = load()
    if args.repin_ruled:
        if PLACEHOLDER.search(re.sub(r"`[^`\n]*`", "", unfence(t.spec))):
            print("refused: a placeholder is unfilled (run --fill first)")
            return 1
        write_if_changed(PINS_REL, write_pins(all_units(t)))
        t = load()
    found = run(t)
    st = self_test(t) if args.self_test else []
    if args.json:
        payload: dict[str, Any] = {
            "values": compute(t),
            "findings": [f"{f.level} [{f.gate}] {f.msg}" for f in found],
        }
        if args.self_test:
            payload["self_test"] = st
        print(json.dumps(payload, ensure_ascii=False, indent=1, sort_keys=True))
    else:
        out = [report(f"{f.level} [{f.gate}] {f.msg}") for f in found]
        n_fail = sum(f.level == "FAIL" for f in found)
        n_warn = sum(f.level == "WARN" for f in found)
        n_note = sum(f.level == "NOTE" for f in found)
        out.append(
            f"gates: {len(GATES)}; FAIL {n_fail} / WARN {n_warn} / NOTE {n_note}; deck "
            f"{len(entries(t))} entries; inventory {len(records(t))} records; A-rows "
            f"{len(a_rows(t.spec)[0])}"
        )
        if args.self_test:
            out += [report(f"FAIL [self-test] {x}") for x in st]
            out.append(
                f"self-test: {'ok' if not st else 'FAILED'}: {len(MUTATIONS)} mutations (at least "
                "one per gate), each new FAIL from its gate only; a re-run reproduces the base; "
                "files on disk unchanged"
            )
        print("\n".join(out))
    failed = any(f.level == "FAIL" for f in found) or bool(st)
    return 1 if failed and (args.check or args.self_test) else 0


if __name__ == "__main__":
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")
    raise SystemExit(main(sys.argv[1:]))
