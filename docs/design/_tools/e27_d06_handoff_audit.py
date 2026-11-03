#!/usr/bin/env python3
"""E27-D06 (#819) audit: the engineering hand-off pack for the accounts and key-vault screens.

Standalone, offline, stdlib only; it runs no repo code and is run with `python3 -I`. It reads the
pack, the copy deck and the pins file from the working tree, and every cited file AS TEXT with
`git show` at the pinned base (`BASE`). Default-deny: a gate that cannot read its input FAILs.

Two stages, named by `--stage` (required; never guessed from the working tree). The deck stage
reads the deck and this tool only, so the deck lands first (PR 1a); the full stage adds the pack
and the pins file (PR 1b) and runs every gate, and the pack or the pins missing FAILs.

Gates (each FAIL led by its name):
  G-DECK     the header line first, then one row per string with every field; a unique id of a
             known form; a known screen, status and consumer; a merged row's text (or each part)
             stands quoted on its cited E27-D03 line; a PROPOSED row's quote stands on its E27-D05
             line, its ruled `14` line or its registered `24` line, and it names the string it
             replaces.
  G-COVER    by id, never by row position: every id of E27-D03 §12.1 and §12.2 is in the deck
             once, with D03's string unless the row is a lift; no other id but the named lifts.
  G-RULES    "shown" only as "can't be shown"; a withdrawal OFF only beside "verified"; the rung-3
             actions (NR-4) ask for the account's name and SCR-127 carries the typed label; (full)
             §2 holds NR-1 ... NR-4, each naming deck ids that exist and carry the rule's words;
             SCR-129's disable and delete markers name their registered codes (BQ-09).
  G-SECRET   NR-1 and C-2.7 over every field of every deck row (and, in the full stage, the pack and
             the pins): no long letter-and-digit run, no long hex run, no signing header, signature,
             bearer or key/secret assignment form; no deck fill but `{key_id_masked}` / `{last4}`;
             and no secret-bearing string offers to show, copy out or unmask a key or secret.
  G-INDEX    §3 has one row per screen; every component of the screen's `14` Components line is in
             the row; every board is one of D03's and its export exists; the deck screen and the
             consumer match the deck.
  G-DATA     every §4 operation is in `22` at the base, under the named method and path, and the
             permission is one of its x-rbac permissions (or `self` for a self-scoped one); every
             topic is in `23`'s topic table.
  G-EVENT    §10's events are the ones the ticket's Observability names, each on a known screen;
             the compromise event's row says it is PROPOSED, registered by E27-S03/S04's contract
             commit (`24` §15.5), and names its request row (R6).
  G-RULING   (full) §16.1 has the fold rows BQ-01 ... BQ-10, each opening with agreed, amended or
             disagreed; §10 pins the code registry's spellings (`accounts.create`, `api_key.import`,
             `account.updated`, `api_key.rotate`, `api_key.revoke` and `api_key.revoked`).
  G-MOTION   §7's rows are D04's M rows with the same recipe; a cut is reduced to "identical".
  G-A11Y     §8.2 carries every D05 F row with its severity; §8.1's ranges are D05's.
  G-BUDGET   every BUD and COUNT anchor is computed from its source.
  G-AHEAD    every DATE and SPRINT anchor is computed from the calendar and the ticket JSON.
  G-AROW     §14's A rows run without a gap and each Old text stands on its cited line.
  G-SIGN     §15 names the three roles in order, none recorded as signed without a comment.
  G-CITE     every cite is in range, on a non-blank line, and equal to the pins file's hash;
             the SHA anchor is the pinned base.
  G-FILLED   no placeholder word in the pack or the deck.
  G-HYGIENE  no closing keyword, local path, URL or host, agent name, double-brace slot or
             public-text deny word in the texts, this tool or the pins file; no unknown anchor.
  G-SCOPE    the stage's files are present, and the diff against `git merge-base HEAD
             origin/main` touches only this ticket's files.

Usage (from the repo root):
  python3 -I docs/design/_tools/e27_d06_handoff_audit.py --stage deck --check
  python3 -I docs/design/_tools/e27_d06_handoff_audit.py --stage full --check
  python3 -I docs/design/_tools/e27_d06_handoff_audit.py --stage full --json
  python3 -I docs/design/_tools/e27_d06_handoff_audit.py --stage full --self-test
  python3 -I docs/design/_tools/e27_d06_handoff_audit.py --stage full --repin-ruled
"""

from __future__ import annotations

import argparse
import datetime
import hashlib
import json
import re
import subprocess
import sys
from collections import Counter
from collections.abc import Callable
from dataclasses import dataclass, replace
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[3]
HAND_REL = "docs/design/E27/E27-D06-handoff.md"
DECK_REL = "docs/design/E27/E27-D06-copy-deck.jsonl"
TOOL_REL = "docs/design/_tools/e27_d06_handoff_audit.py"
PINS_REL = "docs/design/_tools/e27_d06_ruled_pins.txt"
DECK, FULL = "deck", "full"
DECK_PATHS = (DECK_REL, TOOL_REL)
OWN_PATHS = (HAND_REL, PINS_REL, *DECK_PATHS)
BASE = "a7d659a5bee5d06a28950f324800f84dc3853e6f"  # origin/main when written (re-pinned by content)
JSON_REL = "docs/plan/backlog/E27.json"
IMG_DIR = "docs/design/E27/img"
PATHS: dict[str, str] = {
    "02": "docs/plan/02-definition-of-ready-done.md",
    "05": "docs/plan/05-accessibility-standard.md",
    "11": "docs/plan/11-user-stories.md",
    "14": "docs/plan/14-screens-catalogue.md",
    "15": "docs/plan/15-component-catalogue.md",
    "16": "docs/plan/16-design-system-brief.md",
    "22": "docs/plan/22-api-openapi.yaml",
    "23": "docs/plan/23-ws-protocol.md",
    "24": "docs/plan/24-internal-schemas.md",
    "D01": "docs/design/research/e27-key-custody.md",
    "D02": "docs/design/E27/E27-D02.md",
    "D03": "docs/design/E27/E27-D03.md",
    "D03H": "docs/design/E27/E27-D03-handoff.md",
    "D04": "docs/design/E27/E27-D04.md",
    "D05": "docs/design/E27/E27-D05.md",
    "CAL": "docs/plan/backlog/_tools/calendar_cv.py",
    "TM": "docs/security/threat-models/E27-accounts.md",
}
OWN_KEY = "E27-D06"
SCREENS = ("SCR-125", "SCR-126", "SCR-127", "SCR-128", "SCR-129", "SCR-079", "SCR-016", "SCR-019")
DECK_SCREENS = (*SCREENS, "shared", "CMP-034", "CMP-175")
CONSUMER_OF = {
    "SCR-125": "E27-S01", "SCR-019": "E27-S01", "shared": "E27-S01", "CMP-175": "E27-S01",
    "SCR-126": "E27-S02", "SCR-016": "E27-S02", "CMP-034": "E27-S02",
    "SCR-127": "E27-S03", "SCR-128": "E27-S03", "SCR-129": "E27-S04", "SCR-079": "E27-S05",
}  # fmt: skip
CONSUMERS = ("E27-S01", "E27-S02", "E27-S03", "E27-S04", "E27-S05")
COMPONENTS_LINE = {"SCR-125": 2662, "SCR-126": 2690, "SCR-127": 2703, "SCR-128": 2712,
                   "SCR-129": 2727, "SCR-079": 1846}  # fmt: skip  # `14`: each Components line
BUDGET_LINE = {"test.s": (2689, r"targets <=(\d+) s"), "rotate.s": (2702, r"target <=(\d+) s"),
               "summary.s": (2726, r"\(<=(\d+) s\)"), "drawer.ms": (1849, r"<=(\d+) ms"),
               "health.s": (2661, r"every (\d+) s")}  # fmt: skip  # `14`: line and rule
NEW_LIFTS = (
    "e27.scr129.announce.loaded",
    "e27.shared.announce.chips",
    "e27.scr127.typed",
    "e27.scr127.hint.typed",
    "e27.scr129.marker.disable",
    "e27.scr129.marker.delete",
)
RULED_SOURCES = ("14:2706", "24:5360")  # a lift may stand on a ruled `14` or registered `24` line
MARKER = re.compile(r"^Recorded in the audit log · .+ \(([a-z_]+\.[a-z_]+)\)$")
SCR129_CODES = {"e27.scr129.marker.disable": "account.disabled",
                "e27.scr129.marker.delete": "account.deleted"}  # fmt: skip  # BQ-09
STATUSES = ("merged", "RULED", "PROPOSED")
FIELDS = ("id", "screen", "where", "status", "owner", "source", "origin", "consumer")
KEY_FORM = re.compile(
    r"e27\.[a-z0-9_]+(?:\.[a-z0-9_]+)+|(?:keys|accounts|rbac)\.[a-z_]+|frozen|lockout"
    r"|arm\.locked|pending_key(?:\.untimed)?"
)
OWNER = re.compile(r"E\d\d-[DSTQXK]\d\d")
CITE = re.compile(r"`(\d\d|D0[1-5]H?|CAL|TM)`:(\d+(?:–\d+)?(?:, :\d+(?:–\d+)?)*)")
ANCHOR = re.compile(r"`?([^\s<|(`]+)`?<!--=([A-Z]+:[A-Za-z0-9.\-]+)-->")
CLOSING = re.compile(r"\b(?:close[sd]?|fix(?:e[sd])?|resolve[sd]?)\s+#\d+", re.IGNORECASE)
LOCAL_PATH = re.compile(
    "/" + "home/|/" + "tmp/|/Users/|[A-Za-z]:\\\\|\\bnotes" + "/|\\bwt-" + "notes\\b"
)  # assembled, so this file carries none of the paths it refuses
AGENT_NAME = re.compile(r"\b[a-z]{2,4}-worker-\d\b")
URL_OR_HOST = re.compile(r"https?://|penpot\.[a-z]|team-id=|file-id=", re.IGNORECASE)
PLACEHOLDER = re.compile(r"\bTBD\b|\bTODO\b|\bFIXME\b|\?\?\?|\bXXX\b")
DENY = (
    "le" + "ak", "expo" + "sed", "by" + "pass", "ex" + "ploit", "att" + "ack", "ora" + "cle",
    "rev" + "eal", "unbou" + "nded", "flo" + "od", "st" + "all", "d" + "os", "advi" + "sory",
    "gh" + "sa", "pre-" + "auth",
)  # fmt: skip  # each entry an explicit `+` join, so the tool's own text carries none of the words
SHOW_SECRET = re.compile(
    r"\b(?:show|hide|unmask|peek|display|view|copy|export|download)\s+(?:the\s+|your\s+|this\s+)?"
    r"(?:full\s+|new\s+|old\s+)?(?:api\s+)?(?:key|secret)s?\b",
    re.IGNORECASE,
)  # a show or copy-out verb before a key or secret (NR-1)
UNMASK = re.compile(r"\b(?:" + "rev" + "eal" + r"|unmask|peek|un-?hide)\w*", re.IGNORECASE)
SECRET_BEARING = re.compile(r"\b(?:key|secret)s?\b", re.IGNORECASE)
B62_RUN = re.compile(r"[A-Za-z0-9]{16,}")  # key-like when it holds a letter and a digit
HEX_RUN = re.compile(r"(?<![0-9A-Fa-f])[0-9A-Fa-f]{32,}(?![0-9A-Fa-f])")
WIRE = re.compile(
    "|".join((r"\bx-" + "bapi-", r"\bsig" + r"n=", r"\bbea" + r"rer\s+\S",
              r"\b(?:api[_-]?)?(?:key|secret|signature)\s*=")),
    re.IGNORECASE,
)  # fmt: skip  # assembled from parts, so this file carries none of the forms it refuses
KEY_FILLS = ("key_id_masked", "last4")
RUNG1_ASK, RUNG3_ASK = "e27.scr125.menu.ask.keys", "e27.scr125.menu.ask.label"
RUNG3_ACTIONS = ("Disable…", "Delete…", "Rotate key…")  # `14`:2724 and `14`:2706
TYPED = "Type {label} to confirm:"  # the rung-3 typed label's field text (`e27.scr129.typed`)
WITHDRAWAL_OFF = re.compile(r"withdraw\w*(?: and transfer)?:? (?:OFF|off)\b", re.IGNORECASE)
NR_WORDS = {"NR-1": ("write-only", "can't be shown"), "NR-2": ("ithdrawal",),
            "NR-3": ("as of", "since"), "NR-4": ("Type", "password")}  # fmt: skip
ROLES = ("Chief Design Officer or delegate", "Accessibility specialist", "Security engineer")


@dataclass(frozen=True)
class Texts:
    stage: str
    hand: str
    deck: str
    pins: str
    tool: str
    changed: list[str] | None
    memo: dict[str, str | None]


def git(*args: str) -> str | None:
    try:
        r = subprocess.run(["git", "-C", str(ROOT), *args], capture_output=True, check=False)
    except OSError:
        return None
    return r.stdout.decode("utf-8", "surrogateescape") if r.returncode == 0 else None


def show(t: Texts, rel: str) -> str | None:
    if rel not in t.memo:
        t.memo[rel] = git("show", f"{BASE}:{rel}")
    return t.memo[rel]


def at(t: Texts, key: str) -> str:
    text = show(t, PATHS[key])
    if text is None:
        raise SystemExit(f"{PATHS[key]} does not resolve at {BASE[:10]}; fetch first")
    return text


def line(t: Texts, key: str, n: int) -> str:
    ls = at(t, key).split("\n")
    return ls[n - 1] if 0 < n <= len(ls) else ""


def norm(s: str) -> str:
    return " ".join(s.split())


def cells(ln: str) -> list[str]:
    """A table row's cells; an escaped pipe (a backslash before it) stays inside its cell."""
    return [c.strip() for c in re.split(r"(?<!\\)\|", ln.strip().strip("|"))]


def table_rows(text: str, lead: str) -> list[list[str]]:
    return [cells(ln) for ln in text.split("\n") if ln.startswith("| " + lead)]


def section(text: str, head: str) -> str:
    i = text.find("\n" + head)
    if i < 0:
        return ""
    depth = head.split(" ")[0]
    j = text.find("\n" + depth + " ", i + 1)
    return text[i : j if j > 0 else len(text)]


# ---------------------------------------------------------------------------- the deck


@dataclass(frozen=True)
class Deck:
    head: dict[str, Any]
    rows: list[dict[str, Any]]
    problems: list[str]


def parse_deck(text: str) -> Deck:
    problems: list[str] = []
    lines = [ln for ln in text.split("\n") if ln.strip()]
    if not lines:
        return Deck({}, [], ["the deck is empty"])
    try:
        head = json.loads(lines[0])
    except json.JSONDecodeError as e:
        return Deck({}, [], [f"the deck's header line does not parse: {e}"])
    if not isinstance(head, dict) or head.get("pack") != OWN_KEY:
        problems.append("the deck's first line is not the E27-D06 header")
        head = {}
    rows: list[dict[str, Any]] = []
    for i, ln in enumerate(lines[1:], 2):
        try:
            row = json.loads(ln)
        except json.JSONDecodeError as e:
            problems.append(f"deck:{i} does not parse: {e}")
            continue
        if not isinstance(row, dict):
            problems.append(f"deck:{i} is not an object")
            continue
        rows.append(row)
    return Deck(head, rows, problems)


def strings(row: dict[str, Any]) -> list[str]:
    if isinstance(row.get("text"), str):
        return [row["text"]]
    parts = row.get("parts")
    return [p for p in parts if isinstance(p, str)] if isinstance(parts, list) else []


def d03_deck(t: Texts) -> dict[str, tuple[int, str]]:
    """E27-D03 §12.1 and §12.2's keys: key -> (line, the string cell), at the base."""
    text = at(t, "D03").split("\n")
    out: dict[str, tuple[int, str]] = {}
    try:
        a = text.index("### 12.1 The deck")
        c = text.index("### 12.3 Observability")
    except ValueError:
        return out
    for i in range(a, c):
        m = re.match(r"^\| `([a-z0-9_.]+)`", text[i])
        if not m:
            continue
        cs = cells(text[i])
        out[m[1]] = (i + 1, cs[2] if m[1].startswith("e27.") else cs[1])
    return out


def cell_strings(cell: str) -> list[str]:
    if cell.startswith('"') and cell.endswith('"') and cell.count('"') == 2:
        return [cell[1:-1]]
    return re.findall(r'"([^"]*)"', cell)


# ---------------------------------------------------------------------------- values


def sprints(t: Texts) -> dict[str, int]:
    raw = show(t, JSON_REL)
    if raw is None:
        raise LookupError(f"{JSON_REL} does not resolve at the base")
    out: dict[str, int] = {}
    for it in json.loads(raw):
        m = re.fullmatch(r"Sprint (\d+)", str(it.get("sprint", "")))
        if m:
            out[str(it.get("key"))] = int(m[1])
    return out


def compute(t: Texts) -> dict[str, str]:
    v: dict[str, str] = {"SHA:BASE": BASE[:10]}
    rows = parse_deck(t.deck).rows
    v["COUNT:deck.rows"] = str(len(rows))
    for s in STATUSES:
        v[f"COUNT:deck.{s.lower()}"] = str(sum(r.get("status") == s for r in rows))
    d03 = {k: cell_strings(c) for k, (_, c) in d03_deck(t).items() if k.startswith("e27.")}
    v["COUNT:d03.ids"] = str(len(d03))
    v["COUNT:deck.byid"] = str(sum(strings(r) == d03.get(str(r.get("id"))) for r in rows))
    v["COUNT:deck.lifts"] = str(sum(str(r.get("source")).startswith("D05:") for r in rows))
    by = Counter(str(r.get("screen")) for r in rows)
    for s in DECK_SCREENS:
        v[f"COUNT:screen.{s}"] = str(by[s])
    for name, (n, rx) in BUDGET_LINE.items():
        m = re.search(rx, line(t, "14", n))
        if not m:
            raise LookupError(f"`14`:{n} no longer carries /{rx}/")
        v[f"BUD:{name}"] = m[1]
    cal = at(t, "CAL")
    m1 = re.search(r"SPRINT01_START = datetime\.date\((\d+), (\d+), (\d+)\)", cal)
    m2 = re.search(r"SPRINT_DAYS = (\d+)", cal)
    if not m1 or not m2:
        raise LookupError("the calendar's constants moved")
    start = datetime.date(int(m1[1]), int(m1[2]), int(m1[3]))
    days = int(m2[1])
    sp = sprints(t)
    if OWN_KEY not in sp or any(c not in sp for c in CONSUMERS):
        raise LookupError("the ticket JSON lacks a sprint for E27-D06 or a consumer")
    first = min(sp[c] for c in CONSUMERS)

    def s_start(n: int) -> datetime.date:
        return start + datetime.timedelta(days=(n - 1) * days)

    v["SPRINT:own"], v["SPRINT:first"] = str(sp[OWN_KEY]), str(first)
    v["SPRINT:ahead"] = str(first - 3)  # `02`: Done >= 2 sprints before the first story starts
    v["DATE:ahead.end"] = (s_start(first - 2) - datetime.timedelta(days=1)).isoformat()
    v["DATE:first.start"] = s_start(first).isoformat()
    return v


def anchor_problems(t: Texts, vals: dict[str, str], prefixes: tuple[str, ...]) -> list[str]:
    bad = []
    for value, key in ANCHOR.findall(t.hand):
        if key.startswith(prefixes) and key in vals and vals[key] != value:
            bad.append(f"`{key}` reads {value}; the tool derives {vals[key]}")
    return bad


# ---------------------------------------------------------------------------- cites


def cites(text: str) -> list[tuple[str, int, int]]:
    out = []
    for m in CITE.finditer(text):
        for part in m[2].split(", :"):
            a, _, b = part.partition("–")
            out.append((m[1], int(a), int(b or a)))
    return out


def cite_hashes(t: Texts) -> tuple[dict[str, str], list[str]]:
    hashes: dict[str, str] = {}
    bad: list[str] = []
    for key, a, b in cites(t.hand):
        label = f"{key}:{a}" if a == b else f"{key}:{a}–{b}"
        if label in hashes:
            continue
        ls = at(t, key).split("\n")
        if not 0 < a <= b <= len(ls):
            bad.append(f"{label} is past the end of {PATHS[key]} ({len(ls)} lines)")
            continue
        blank = [n for n in (a, b) if not ls[n - 1].strip()]
        if blank:
            bad.append(f"{label}: line {blank[0]} is blank at its base")
            continue
        joined = norm(ls[a - 1]) + "\n" + norm(ls[b - 1])
        hashes[label] = hashlib.sha256(joined.encode()).hexdigest()[:12]
    return hashes, bad


def parse_pins(text: str) -> dict[str, str]:
    out = {}
    for ln in text.split("\n"):
        parts = ln.split("\t")
        if len(parts) == 2 and not ln.startswith("#"):
            out[parts[0]] = parts[1]
    return out


# ---------------------------------------------------------------------------- gates


def g_deck(t: Texts, vals: dict[str, str]) -> list[str]:
    deck = parse_deck(t.deck)
    bad = list(deck.problems)
    if deck.head and deck.head.get("base") != BASE[:10]:
        bad.append("the deck's header names another base than the tool's")
    seen: set[str] = set()
    for r in deck.rows:
        k = str(r.get("id", "?"))
        missing = [f for f in FIELDS if not isinstance(r.get(f), str) or not r.get(f)]
        if missing or not strings(r) or ("text" in r) == ("parts" in r):
            bad.append(f"{k}: no {', '.join(missing) or 'text or parts (exactly one)'}")
            continue
        if not KEY_FORM.fullmatch(k):
            bad.append(f"{k}: not a known key form")
        if k in seen:
            bad.append(f"{k}: a repeated key")
        seen.add(k)
        if r["screen"] not in DECK_SCREENS:
            bad.append(f"{k}: screen {r['screen']!r} is not one of the pack's")
        elif r["consumer"] != CONSUMER_OF[r["screen"]]:
            bad.append(f"{k}: consumer {r['consumer']} is not {CONSUMER_OF[r['screen']]}")
        if r["status"] not in STATUSES:
            bad.append(f"{k}: status {r['status']!r} is not merged, RULED or PROPOSED")
        if not OWNER.fullmatch(r["owner"]):
            bad.append(f"{k}: owner {r['owner']!r} is not a ticket key")
        m = re.fullmatch(r"(D03|D05|14|24):(\d+)", r["source"])
        if not m or (m[1] in ("14", "24") and r["source"] not in RULED_SOURCES):
            bad.append(f"{k}: source {r['source']!r} is not a D03, D05, ruled `14` or `24` line")
            continue
        ln = line(t, m[1], int(m[2]))
        if r["status"] == "merged":
            if m[1] != "D03" or r["owner"] != "E27-D03":
                bad.append(f"{k}: a merged row cites E27-D03 and is owned by it")
            for s in strings(r):
                if f'"{s}"' not in ln:
                    bad.append(f"{k}: {s[:40]!r} is not quoted on `D03`:{m[2]}")
        else:
            quote = r.get("quote")
            if m[1] == "D03" or r["owner"] != OWN_KEY:
                bad.append(f"{k}: a lift cites E27-D05 or a ruled line, owned by E27-D06")
            if not isinstance(quote, str) or not quote or quote not in ln:
                bad.append(f"{k}: its quote is not on `{m[1]}`:{m[2]}")
            if k not in NEW_LIFTS and not r.get("d03_text"):
                bad.append(f"{k}: a lift names no d03_text it replaces")
    return bad


def g_cover(t: Texts, vals: dict[str, str]) -> list[str]:
    theirs = d03_deck(t)
    bad = [] if theirs else ["E27-D03 §12 carries no deck rows at the base"]
    rows = parse_deck(t.deck).rows
    count = Counter(str(r.get("id")) for r in rows)
    for k in theirs:
        if count[k] != 1:
            bad.append(f"{k}: in the deck {count[k]} times (E27-D03 §12 holds it once)")
    for r in rows:
        k = str(r.get("id"))
        if k not in theirs:
            if k not in NEW_LIFTS:
                bad.append(f"{k}: not an E27-D03 key and not a named lift")
            continue
        want = cell_strings(theirs[k][1])
        if r.get("status") == "merged" and strings(r) != want:
            bad.append(f"{k}: the text is not E27-D03's")
        if r.get("status") != "merged":
            d03 = r.get("d03_text")
            if not isinstance(d03, str) or cell_strings(d03 if '"' in d03 else f'"{d03}"') != want:
                bad.append(f"{k}: d03_text is not E27-D03's string")
    return bad


def g_rules(t: Texts, vals: dict[str, str]) -> list[str]:
    rows = parse_deck(t.deck).rows
    bad = []
    for r in rows:
        for s in strings(r):
            if "shown" in s and s.count("shown") != s.count("can't be shown"):
                bad.append(f"{r.get('id')}: 'shown' not negated (NR-1)")
            if WITHDRAWAL_OFF.search(s) and "verified" not in s:
                bad.append(f"{r.get('id')}: a withdrawal OFF with no verified time (NR-2)")
    by = {str(r.get("id")): r for r in rows}
    low, high = (str(by.get(k, {}).get("where", "")) for k in (RUNG1_ASK, RUNG3_ASK))
    for act in RUNG3_ACTIONS:
        if act in low or act not in high:
            bad.append(f"{act} is not on the rung-3 ask `{RUNG3_ASK}` alone (NR-4)")
    if not any(s == TYPED for r in rows if r.get("screen") == "SCR-127" for s in strings(r)):
        bad.append("SCR-127 carries no typed account label (NR-4; `14`:2706)")
    for k, code in SCR129_CODES.items():
        got = [MARKER.match(s) for s in strings(by.get(k, {}))]
        if not any(g and g[1] == code for g in got):
            bad.append(f"`{k}` does not name the registered `{code}` (BQ-09; `24`:5360)")
    if t.stage == DECK:
        return bad
    nrs = table_rows(section(t.hand, "## 2."), "NR-")
    if [n[0] for n in nrs] != list(NR_WORDS):
        bad.append(f"§2's rules are {[n[0] for n in nrs]}, not NR-1 ... NR-4")
    for n in nrs:
        keys = re.findall(r"`([a-z0-9_.]+)`", n[-1])
        if not keys:
            bad.append(f"{n[0]} names no deck key")
        for k in keys:
            if k not in by:
                bad.append(f"{n[0]}: `{k}` is not a deck key")
            elif n[0] in NR_WORDS and not any(
                w.lower() in s.lower() for s in strings(by[k]) for w in NR_WORDS[n[0]]
            ):
                bad.append(f"{n[0]}: `{k}` carries none of {NR_WORDS[n[0]]}")
    return bad


def field_strings(v: Any) -> list[str]:
    if isinstance(v, str):
        return [v]
    if isinstance(v, list):
        return [x for e in v for x in field_strings(e)]
    if isinstance(v, dict):
        return [x for k, e in v.items() for x in (str(k), *field_strings(e))]
    return []


def material(s: str, fills: bool = True) -> str | None:
    """What key material `s` carries, or None (C-2.7, C-12.2); fills are the deck's slots."""
    for m in B62_RUN.finditer(s):
        if re.search(r"[A-Za-z]", m[0]) and re.search(r"\d", m[0]):
            return "a long letter-and-digit run"
    if HEX_RUN.search(s):
        return "a long hex run"
    if WIRE.search(s):
        return "a signing header, signature, bearer or assignment form"
    for slot in re.findall(r"\{([^{}]*)\}", s) if fills else ():
        if re.search(r"key|secret|sign", slot, re.IGNORECASE) and slot not in KEY_FILLS:
            return f"the key fill {{{slot}}}"
    return None


def g_secret(t: Texts, vals: dict[str, str]) -> list[str]:
    deck = parse_deck(t.deck)
    bad = []
    for name, row in (("header", deck.head), *((str(r.get("id")), r) for r in deck.rows)):
        for field, v in row.items():
            for s in field_strings(v):
                what = material(s)
                if what:
                    bad.append(f"{name}: `{field}` carries {what} (C-2.7)")
        if name == "header":
            continue
        for s in strings(row):
            if SECRET_BEARING.search(s) and (SHOW_SECRET.search(s) or UNMASK.search(s)):
                bad.append(f"{name}: offers to show, copy out or unmask a key or secret (NR-1)")
    if t.stage == FULL:
        for label, text in (("pack", t.hand), ("pins", t.pins)):
            for i, ln in enumerate(text.split("\n"), 1):
                what = material(ln, fills=False)  # `{keyId}` there is a path parameter
                if what:
                    bad.append(f"{label}:{i} carries {what} (C-2.7)")
    return bad


def board_list(t: Texts) -> set[str]:
    return set(re.findall(r"^\| (\d\d)  \| `E27-D03 / \1 ", at(t, "D03"), re.MULTILINE))


def g_index(t: Texts, vals: dict[str, str]) -> list[str]:
    rows = table_rows(section(t.hand, "## 3."), "SCR-")
    bad = []
    if [r[0] for r in rows] != list(SCREENS):
        bad.append(f"§3's screens are {[r[0] for r in rows]}, not {list(SCREENS)}")
    boards = board_list(t)
    tree = git("ls-tree", "--name-only", BASE, IMG_DIR + "/") or ""
    deck_screens = {str(r.get("screen")) for r in parse_deck(t.deck).rows}
    for r in rows:
        if len(r) < 6:
            bad.append(f"{r[0]}: the row has {len(r)} cells")
            continue
        scr, _, brd, dscr, comps, cons = r[:6]
        for b in re.findall(r"\b(\d\d)\b", brd):
            if b not in boards:
                bad.append(f"{scr}: board {b} is not one of E27-D03's")
            elif f"{IMG_DIR}/E27-D03-{b}-" not in tree:
                bad.append(f"{scr}: board {b} has no export at the base")
        if dscr != scr or dscr not in deck_screens:
            bad.append(f"{scr}: the deck screen {dscr!r} has no deck rows")
        if cons != CONSUMER_OF.get(scr):
            bad.append(f"{scr}: consumer {cons} is not {CONSUMER_OF.get(scr)}")
        n = COMPONENTS_LINE.get(scr)
        if n:
            src = line(t, "14", n)
            if not src.startswith("- **Components:**") or f"`14`:{n}" not in comps:
                bad.append(f"{scr}: the row does not cite its `14` Components line {n}")
            for c in re.findall(r"CMP-\d{3}", src):
                if c not in comps:
                    bad.append(f"{scr}: {c} of `14`:{n} is not in the row")
    return bad


def ops_22(t: Texts) -> dict[str, tuple[str, str, list[str], str]]:
    """operationId -> (path, method, x-rbac permissions, scope) at the base."""
    out: dict[str, tuple[str, str, list[str], str]] = {}
    path = method = op = ""
    for s in at(t, "22").split("\n"):
        m = re.match(r"^  (/[^:]*):\s*$", s)
        if m:
            path, method, op = m[1], "", ""
            continue
        m = re.match(r"^    (get|post|put|patch|delete):\s*$", s)
        if m:
            method, op = m[1], ""
            continue
        if not (path and method):
            continue
        m = re.match(r"^      operationId: (\w+)\s*$", s)
        if m:
            op = m[1]
            out[op] = (path, method, [], "")
        m = re.match(r"^      x-rbac: \{ permissions: \[([^\]]*)\], scope: (\w+) \}", s)
        if m and op:
            perms = [p.strip() for p in m[1].split(",") if p.strip()]
            out[op] = (path, method, perms, m[2])
    return out


def topics_23(t: Texts) -> set[str]:
    return set(re.findall(r"^\| `([a-z_.{}]+)`\s+\|", at(t, "23"), re.MULTILINE))


def g_data(t: Texts, vals: dict[str, str]) -> list[str]:
    ops = ops_22(t)
    topics = topics_23(t)
    body = section(t.hand, "## 4.")
    rows = table_rows(body, "`")
    bad = [] if rows else ["§4 carries no operation rows"]
    for r in rows:
        op = r[0].strip("`")
        m = re.fullmatch(r"`(GET|POST|PUT|PATCH|DELETE) (/\S+)`", r[1])
        if op not in ops:
            bad.append(f"`{op}` is not an operationId in `22` at the base")
            continue
        path, method, perms, scope = ops[op]
        if not m or (m[1].lower(), m[2]) != (method, path):
            bad.append(f"`{op}`: `22` serves it as {method.upper()} {path}, not {r[1]}")
        want = r[2].strip("`")
        if not (want in perms or (want == "self" and scope == "self" and not perms)):
            bad.append(f"`{op}`: permission {want} is not its x-rbac {perms or scope}")
    for para in re.findall(r"^Topics: (.*)$", body, re.MULTILINE):
        head = re.split(r"[.;]", re.sub(r"\([^)]*\)", "", para))[0]  # the topic names only
        for tp in re.findall(r"`([a-z_]+)`", head):
            if tp not in topics:
                bad.append(f"topic `{tp}` is not in `23`'s topic table")
    return bad


def ticket_events(t: Texts) -> set[str]:
    raw = show(t, JSON_REL)
    if raw is None:
        return set()
    body = next((it.get("body", "") for it in json.loads(raw) if it.get("key") == OWN_KEY), "")
    obs = section("\n" + str(body), "## Observability")
    return set(re.findall(r"`([a-z_]+\.[a-z_]+)`", obs))


def g_event(t: Texts, vals: dict[str, str]) -> list[str]:
    theirs = ticket_events(t)
    rows = table_rows(section(t.hand, "## 10."), "`")
    ours = {r[0].strip("`") for r in rows}
    bad = [] if theirs else ["the ticket's Observability names no event"]
    if ours != theirs:
        bad.append(f"§10's events differ from the ticket's: {sorted(ours ^ theirs)}")
    for r in rows:
        for s in re.findall(r"SCR-\d{3}", r[2]):
            if s not in SCREENS:
                bad.append(f"{r[0]}: {s} is not a pack screen")
    gap = next((r for r in rows if r[0] == "`admin.key_marked_compromised`"), None)
    need = ("PROPOSED", "E27-S03/S04", "§15.5", "R6")
    if gap is None or len(gap) < 4 or "BLOCKS" in gap[3] or any(n not in gap[3] for n in need):
        bad.append(
            "the compromise event's row must say PROPOSED, E27-S03/S04's commit, `24` §15.5 and R6"
        )
    return bad


RULING_OPENERS = ("agreed", "amended", "disagreed")
SPELLINGS = (
    ("account.created", ("`accounts.create`", "`api_key.import`")),
    ("account.updated", ("`account.updated`",)),
    ("account.key_rotated", ("`api_key.rotate`",)),
    ("account.key_revoked", ("`api_key.revoke`", "`api_key.revoked`")),
)


def g_ruling(t: Texts, vals: dict[str, str]) -> list[str]:
    rows = table_rows(section(t.hand, "### 16.1"), "BQ-")
    want = [f"BQ-{i:02d}" for i in range(1, 11)]
    bad = []
    if [r[0] for r in rows] != want:
        bad.append(f"§16.1's fold rows are {[r[0] for r in rows]}, not {want}")
    for r in rows:
        if len(r) < 3 or not r[2].startswith(RULING_OPENERS):
            bad.append(f"{r[0]}: the fold cell opens with none of {RULING_OPENERS}")
    events = {r[0].strip("`"): r for r in table_rows(section(t.hand, "## 10."), "`")}
    for event, spellings in SPELLINGS:
        row = events.get(event)
        for sp in spellings:
            if row is None or sp not in row[3]:
                bad.append(f"§10's {event} row does not pin the registered spelling {sp}")
    return bad


def g_motion(t: Texts, vals: dict[str, str]) -> list[str]:
    theirs = {r[0]: r[3] for r in table_rows(section(at(t, "D04"), "## 2."), "M-")}
    ours = table_rows(section(t.hand, "## 7."), "M-")
    bad = [] if theirs else ["`D04` §2 carries no M rows at the base"]
    if [r[0] for r in ours] != list(theirs):
        bad.append(f"§7's rows are {[r[0] for r in ours]}, not D04's {list(theirs)}")
    for r in ours:
        if r[0] in theirs and r[2] != theirs[r[0]]:
            bad.append(f"{r[0]}: recipe {r[2]!r} is not D04's {theirs[r[0]]!r}")
        if r[2] == "a cut" and r[3] != "identical (a cut)":
            bad.append(f"{r[0]}: a cut's reduced form is 'identical (a cut)'")
        if r[2] != "a cut" and "reduce" not in r[3]:
            bad.append(f"{r[0]}: a recipe row names no reduce cell")
    return bad


def g_a11y(t: Texts, vals: dict[str, str]) -> list[str]:
    d05 = at(t, "D05")
    theirs = {r[0]: r[1] for r in table_rows(section(d05, "## 14."), "F-")}
    ours = table_rows(section(t.hand, "### 8.2"), "F-")
    bad = [] if theirs else ["`D05` §14 carries no F rows at the base"]
    if {r[0]: r[1] for r in ours} != theirs:
        bad.append("§8.2's F rows and severities are not D05 §14's")
    for r in ours:
        if not r[2] or not re.match(r"(lifted|recorded)", r[2]):
            bad.append(f"{r[0]}: no disposition")
    for prefix in ("FO", "LR", "SR"):
        ids = sorted({int(n) for n in re.findall(rf"^\| {prefix}-(\d\d) ", d05, re.MULTILINE)})
        want = f"{prefix}-01 … {prefix}-{ids[-1]:02d}" if ids else "?"
        if want not in t.hand:
            bad.append(f"§8.1 does not name {want}, D05's range")
    named = set(re.findall(r"FO-\d\d", section(t.hand, "### 8.1")))
    ids_fo = {f"FO-{n}" for n in re.findall(r"^\| FO-(\d\d) ", d05, re.MULTILINE)}
    if ids_fo and not ids_fo <= named:
        bad.append(f"§8.1 maps no screen to {sorted(ids_fo - named)}")
    return bad


def g_budget(t: Texts, vals: dict[str, str]) -> list[str]:
    return anchor_problems(t, vals, ("BUD:", "COUNT:"))


def g_ahead(t: Texts, vals: dict[str, str]) -> list[str]:
    return anchor_problems(t, vals, ("DATE:", "SPRINT:"))


def g_arow(t: Texts, vals: dict[str, str]) -> list[str]:
    rows = table_rows(section(t.hand, "## 14."), "A-")
    bad = []
    if not rows or [r[0] for r in rows] != [f"A-{i}" for i in range(1, len(rows) + 1)]:
        bad.append(f"§14's rows are {[r[0] for r in rows]}: a gap or none")
    for r in rows:
        m = re.match(r"`(\d\d|D0[2-5])`:(\d+)", r[1])
        if not m:
            bad.append(f"{r[0]}: no file and line")
            continue
        old = r[2]
        if old != "—" and old.strip('"') not in line(t, m[1], int(m[2])):
            bad.append(f"{r[0]}: the Old text is not on `{m[1]}`:{m[2]} at the base")
    return bad


def g_sign(t: Texts, vals: dict[str, str]) -> list[str]:
    body = table_rows(section(t.hand, "## 15."), "")
    rows = [r for r in body if r[0] != "Role" and not r[0].startswith("-")]
    bad = []
    if [r[0] for r in rows] != list(ROLES):
        bad.append(f"§15's roles are {[r[0] for r in rows]}, not {list(ROLES)}")
    for r in rows:
        rec = r[-1]
        if not (rec.startswith("PENDING") or re.search(r"comment \d{6,}", rec)):
            bad.append(f"{r[0]}: recorded as {rec!r} with no comment id")
    return bad


def g_cite(t: Texts, vals: dict[str, str]) -> list[str]:
    hashes, bad = cite_hashes(t)
    pinned = parse_pins(t.pins)
    for label, h in hashes.items():
        if label not in pinned:
            bad.append(f"cite {label} is unpinned: verify it by content, then --repin-ruled")
        elif pinned[label] != h:
            bad.append(f"cite {label}: the line at its base is not the pinned content")
    bad += anchor_problems(t, vals, ("SHA:",))
    return bad


def g_filled(t: Texts, vals: dict[str, str]) -> list[str]:
    bad = []
    for label, text in (("pack", t.hand), ("deck", t.deck)):
        for i, ln in enumerate(text.split("\n"), 1):
            if PLACEHOLDER.search(ln):
                bad.append(f"{label}:{i} carries a placeholder")
    return bad


def g_hygiene(t: Texts, vals: dict[str, str]) -> list[str]:
    bad = []
    checks = ((CLOSING, "a closing keyword (the closing PR alone closes #819)"),
              (LOCAL_PATH, "a local path"), (AGENT_NAME, "an agent name"),
              (URL_OR_HOST, "a URL or a host"))  # fmt: skip
    texts = (("deck", t.deck),) if t.stage == DECK else (("pack", t.hand), ("deck", t.deck))
    for label, text in texts:
        for i, ln in enumerate(text.split("\n"), 1):
            for rx, what in checks:
                if rx.search(ln):
                    bad.append(f"{label}:{i} carries {what}")
            if "{{" in ln:
                bad.append(f"{label}:{i} carries a double-brace slot")
            if any(d in ln.lower() for d in DENY):
                bad.append(f"{label}:{i} carries a public-text deny word")
    for label, text in (("tool", t.tool), ("pins", t.pins if t.stage == FULL else "")):
        for i, ln in enumerate(text.split("\n"), 1):
            if any(d in ln.lower() for d in DENY):
                bad.append(f"{label}:{i} carries a public-text deny word")
    if t.stage == FULL:
        for _, key in ANCHOR.findall(t.hand):
            if key not in vals:
                bad.append(f"an anchor `{key}` the tool does not compute")
    return bad


def owned(stage: str) -> tuple[str, ...]:
    return DECK_PATHS if stage == DECK else OWN_PATHS


def g_scope(t: Texts, vals: dict[str, str]) -> list[str]:
    if t.changed is None:
        return ["cannot list the changed paths (git failed)"]
    bad = [f"{p} is touched; this ticket owns {', '.join(OWN_PATHS)}"
           for p in t.changed if p not in OWN_PATHS]  # fmt: skip
    if t.stage == FULL and not (t.hand and t.pins):
        bad.append(f"{HAND_REL} or {PINS_REL} is missing (full stage)")
    if not t.deck:
        bad.append(f"{DECK_REL} is missing")
    return bad


GATES: dict[str, Callable[[Texts, dict[str, str]], list[str]]] = {
    "G-DECK": g_deck, "G-COVER": g_cover, "G-RULES": g_rules, "G-SECRET": g_secret, "G-INDEX": g_index,
    "G-DATA": g_data, "G-EVENT": g_event, "G-RULING": g_ruling, "G-MOTION": g_motion, "G-A11Y": g_a11y,
    "G-BUDGET": g_budget, "G-AHEAD": g_ahead, "G-AROW": g_arow, "G-SIGN": g_sign,
    "G-CITE": g_cite, "G-FILLED": g_filled, "G-HYGIENE": g_hygiene, "G-SCOPE": g_scope,
}  # fmt: skip
DECK_GATES = ("G-DECK", "G-COVER", "G-RULES", "G-SECRET", "G-FILLED", "G-HYGIENE", "G-SCOPE")


def gates_of(stage: str) -> list[str]:
    return [g for g in GATES if stage == FULL or g in DECK_GATES]


def audit(t: Texts) -> list[tuple[str, str]]:
    try:
        vals = compute(t)
    except LookupError as e:
        return [("G-BUDGET", str(e))]
    return [(g, msg) for g in gates_of(t.stage) for msg in GATES[g](t, vals)]


# ---------------------------------------------------------------------------- load, self-test


def changed_paths() -> list[str] | None:
    mb = git("merge-base", "HEAD", "origin/main")
    if not mb:
        return None
    a = git("diff", "--name-only", mb.strip())
    b = git("status", "--porcelain", "--untracked-files=all")
    if a is None or b is None:
        return None
    out = {p for p in a.split("\n") if p}
    out |= {ln[3:].split(" -> ")[-1].strip('"') for ln in b.split("\n") if len(ln) > 3}
    return sorted(out)


def read(rel: str) -> str:
    p = ROOT / rel
    return p.read_text(encoding="utf-8") if p.exists() else ""


def load(stage: str) -> Texts:
    """The deck stage never reads the pack or the pins, present or not."""
    full = stage == FULL
    hand, pins = (read(HAND_REL), read(PINS_REL)) if full else ("", "")
    return Texts(stage, hand, read(DECK_REL), pins, read(TOOL_REL), changed_paths(), {})


def sub(field: str, old: str, new: str) -> Callable[[Texts], Texts]:
    def f(t: Texts) -> Texts:
        text = str(getattr(t, field))
        if text.count(old) != 1:
            raise SystemExit(f"self-test: {field} carries {old[:50]!r} {text.count(old)} times")
        out = text.replace(old, new)
        return replace(t, hand=out) if field == "hand" else replace(t, deck=out)

    return f


def deck_set(row_key: str, /, **fields: Any) -> Callable[[Texts], Texts]:
    def f(t: Texts) -> Texts:
        out = []
        for ln in t.deck.split("\n"):
            if ln.startswith(f'{{"id": "{row_key}"'):
                row = json.loads(ln)
                row.update(fields)
                ln = json.dumps(row, ensure_ascii=False)
            out.append(ln)
        return replace(t, deck="\n".join(out))

    return f


LIFT = "e27.shared.announce.chips"  # a lift's text is the pack's own, so only G-RULES reads it
BOTH, FULL_ONLY = (DECK, FULL), (FULL,)
MUTATIONS: tuple[tuple[str, str, Callable[[Texts], Texts], tuple[str, ...]], ...] = (
    ("G-DECK", "blank a row's consumer", deck_set("e27.shell.h1", consumer=""), BOTH),
    ("G-DECK", "give a lift a quote not on its line", deck_set(LIFT, quote="{n} rows changed"), BOTH),
    ("G-COVER", "rename a lifted E27-D03 id in the deck", deck_set("e27.scr126.secret.label", id="e27.scr126.secret_label"), BOTH),
    ("G-RULES", "make a withdrawal OFF undated", deck_set(LIFT, text="Withdrawal OFF on {n} accounts"), BOTH),
    ("G-RULES", "put the rotation ask back on rung 1", deck_set(RUNG1_ASK, where="second line of Add a key…, Rotate key…, Revoke key… · frame 11"), BOTH),
    ("G-RULES", "drop SCR-127's typed label", deck_set("e27.scr127.typed", text="Confirm:"), BOTH),
    ("G-RULES", "unname the delete marker's code", deck_set("e27.scr129.marker.delete", text="Recorded in the audit log"), BOTH),
    ("G-BUDGET", "misstate the by-id count", sub("hand", "<!--=COUNT:deck.byid-->", "1<!--=COUNT:deck.byid-->"), FULL_ONLY),
    ("G-SECRET", "a key-like run in a PROPOSED text", deck_set(LIFT, text="{n} accounts: " + "Ab3" * 6), BOTH),
    ("G-SECRET", "a 64-hex run in a merged row's where", deck_set("e27.shell.h1", where="frame 1 " + "0f" * 32), BOTH),
    ("G-SECRET", "a signing header in an origin", deck_set("e27.shell.h1", origin="consumed · X-" + "BAPI-SIGN"), BOTH),
    ("G-SECRET", "a signature form in a where", deck_set(LIFT, where="polite, once · sig" + "n=1"), BOTH),
    ("G-SECRET", "a bearer form in a d03_where", deck_set("e27.scr126.secret.label", d03_where="Bea" + "rer abc"), BOTH),
    ("G-SECRET", "a key assignment form in a where", deck_set("e27.shell.h1", where="frame 1 api_" + "key=x"), BOTH),
    ("G-SECRET", "a key fill other than the masked id", deck_set(LIFT, text="{n} accounts: {api_" + "secret}"), BOTH),
    ("G-SECRET", "a copy-out verb in a secret label", deck_set("e27.scr126.secret.label", text="API secret (write-only) · Copy secret"), BOTH),
    ("G-SECRET", "a show verb in a secret label", deck_set("e27.scr126.secret.label", text="API secret (write-only) · Show secret"), BOTH),
    ("G-SECRET", "an unmask verb in a secret label", deck_set("e27.scr126.secret.label", text="API secret (write-only) · Unmask"), BOTH),
    ("G-SECRET", "a key-like run in the pack", sub("hand", "Text-first, pre-staged on the blocker.", "Text-first, pre-staged on the blocker " + "Ab3" * 6 + "."), FULL_ONLY),
    ("G-RULES", "name a deck key NR-3 does not carry", sub("hand", "`e27.shell.meta`, `e27.scr079.balances.caption`", "`e27.shell.h1`, `e27.scr079.balances.caption`"), FULL_ONLY),
    ("G-INDEX", "drop a component from SCR-129's row", sub("hand", "CMP-027, CMP-044, CMP-093 (`14`:2727)", "CMP-027, CMP-093 (`14`:2727)"), FULL_ONLY),
    ("G-DATA", "give an operation a permission it lacks", sub("hand", "| `rotateApiKey` | `POST /exchange-accounts/{accountId}/keys/{keyId}/rotate` | `keys:manage` |", "| `rotateApiKey` | `POST /exchange-accounts/{accountId}/keys/{keyId}/rotate` | `keys:read` |"), FULL_ONLY),
    ("G-EVENT", "rename an event", sub("hand", "| `admin.key_test_run`  ", "| `admin.key_tested`    "), FULL_ONLY),
    ("G-EVENT", "let the compromise row drop its proposed gate", sub("hand", "PROPOSED; registered by E27-S03/S04's contract commit (`24` §15.5), R6", "the card writes none, R6"), FULL_ONLY),
    ("G-RULING", "drop the BQ-06 fold row", sub("hand", "| BQ-06 | The design-ahead AC      |", "| BQ-6  | The design-ahead AC      |"), FULL_ONLY),
    ("G-RULING", "change the registered rotate spelling", sub("hand", "registered as `api_key.rotate` (code registry); `24`:5360", "registered as `apikey.rotated` (code registry); `24`:5360"), FULL_ONLY),
    ("G-MOTION", "give M-10 the wrong recipe", sub("hand", "| row 2b                           |", "| row 2a                           |"), FULL_ONLY),
    ("G-A11Y", "change a finding's severity", sub("hand", "| F-09 | Major    |", "| F-09 | Minor    |"), FULL_ONLY),
    ("G-BUDGET", "type a wrong drawer budget", sub("hand", "opens from cache in 100<!--=BUD:drawer.ms-->", "opens from cache in 200<!--=BUD:drawer.ms-->"), FULL_ONLY),
    ("G-AHEAD", "type a wrong date", sub("hand", "2026-12-17<!--=DATE:ahead.end-->", "2026-12-24<!--=DATE:ahead.end-->"), FULL_ONLY),
    ("G-AROW", "change an A-row's Old text", sub("hand", '"Then the account row shows green with the last heartbeat age"', '"Then the account row shows red with the last heartbeat age"  '), FULL_ONLY),
    ("G-SIGN", "claim a sign-off with no comment", sub("hand", "| PENDING: owner approval pending, after one Opus security pass on §2 and the key-state rows |", "| signed |"), FULL_ONLY),
    ("G-CITE", "re-point a cite to an unpinned line", sub("hand", "(`D04`:155)", "(`D04`:156)"), FULL_ONLY),
    ("G-FILLED", "write a placeholder", sub("hand", "The table is empty until the walkthrough or the dry run is logged on #819.", "The table is TBD."), FULL_ONLY),
    ("G-FILLED", "write a placeholder into the deck", deck_set(LIFT, where="TBD"), BOTH),
    ("G-HYGIENE", "write a closing keyword against #819", sub("hand", "links this file and names the consumer's screens (§3);", "links this file and names the consumer's screens (§3). Closes #819;"), FULL_ONLY),
    ("G-HYGIENE", "put a deny word into the tool's own text", lambda t: replace(t, tool=t.tool + "\n# " + DENY[6] + "\n"), BOTH),
    ("G-SCOPE", "touch `14` in the diff", lambda t: replace(t, changed=[*OWN_PATHS, PATHS["14"]]), BOTH),
)  # fmt: skip


def selftest(stage: str) -> tuple[bool, list[str]]:
    base = replace(load(stage), changed=list(owned(stage)))
    before = (base.hand, base.deck)
    found = audit(base)
    out = [f"self-test ({stage}): baseline {len(found)} FAIL"]
    out += [f"  baseline {g}: {m}" for g, m in found]
    ok = not found
    run = [m for m in MUTATIONS if stage in m[3]]
    for i, (gate, what, fn, _) in enumerate(run, 1):
        gates = sorted({g for g, _ in audit(fn(base))})
        good = gates == [gate]
        ok &= good
        out.append(
            f"{'ok  ' if good else 'FAIL'} MU-{i} {gate}: {what} -> {', '.join(gates) or 'none'}"
        )
    after = load(stage)
    restored = (after.hand, after.deck) == before
    ok &= restored
    out.append(f"self-test: {len(run)} mutations, texts restored: {'yes' if restored else 'NO'}")
    out.append(f"self-test: {'PASS' if ok else 'FAIL'}")
    return ok, out


def main(argv: list[str]) -> int:
    ap = argparse.ArgumentParser(description="E27-D06 hand-off pack audit")
    ap.add_argument("--stage", required=True, choices=(DECK, FULL))
    g = ap.add_mutually_exclusive_group()
    g.add_argument("--check", action="store_true")
    g.add_argument("--self-test", action="store_true")
    g.add_argument("--repin-ruled", action="store_true")
    ap.add_argument("--json", action="store_true")
    a = ap.parse_args(argv)
    if a.self_test:
        ok, lines = selftest(a.stage)
        print("\n".join(lines))
        return 0 if ok else 1
    t = load(a.stage)
    if a.repin_ruled:
        if a.stage != FULL or not t.hand:
            print("refused: --repin-ruled runs in the full stage, with the pack present")
            return 1
        hashes, bad = cite_hashes(t)
        if bad:
            print(f"refused: {bad[0]}")
            return 1
        head = "# E27-D06 cite pins: the cite, a hash of its cited line(s) at the base. Written by --repin-ruled only.\n"
        body = "".join(f"{k}\t{h}\n" for k, h in hashes.items())
        (ROOT / PINS_REL).write_text(head + body, encoding="utf-8")
        print(f"wrote {PINS_REL} ({len(hashes)} cites)")
        return 0
    found = audit(t)
    if a.json:
        doc = {"stage": a.stage, "base": BASE, "values": compute(t),
               "findings": [{"gate": g, "msg": m} for g, m in found]}  # fmt: skip
        print(json.dumps(doc, ensure_ascii=False, indent=2))
    else:
        for gate, msg in found:
            print(f"FAIL {gate}: {msg}")
        n = len(cite_hashes(t)[0]) if a.stage == FULL else 0
        rows = len(parse_deck(t.deck).rows)
        print(
            f"{len(found)} FAIL ({len(gates_of(a.stage))} gates, {a.stage} stage; {n} cites; {rows} deck rows)"
        )
    return 1 if found else 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
