#!/usr/bin/env python3
"""E25-D07 (#672) audit: the design hand-off pack for the five detector surfaces (SCR-055 ... 059).

Standalone, offline, stdlib only; it runs no repo code and is run with `python3 -I`. It reads the
pack (spec, hand-off, the copy deck) and the pins file from the working tree, and every cited file
AS TEXT with `git show` at the pinned base (`BASE`, `main` with #5415 merged), and E25-D06 at
#5456's merge commit (`D06_REF`).
Default-deny: a gate that cannot read its input FAILs. Shaped like the E24-D05 sibling tool, with
the stage switch of the E37-D05 tool.

Two stages, named by a required `--stage deck|full` (no default; never chosen by which files
exist). `--stage full` runs every gate and needs the five files; a missing one FAILs G-STAGE and
no other gate runs. `--stage deck` (a deck-first PR) needs the deck and this tool and runs
G-STAGE, G-DECK, G-PROV, G-FROZEN (its deck part), G-HYGIENE and G-SCOPE; the gates it does not
run are named on every run, never skipped silently. The self-test runs its stage's mutations.

Gates (each FAIL led by its name):
  G-STAGE     every file the stage needs is in the working tree.
  G-DECK      the deck parses: the header line first (its refs, its key naming PROPOSED), then one row per string with every field, a
              unique `detectors.*` id, a known kind, status, provenance, screen and consumer, an
              owner from the parents' lanes; a `merged` row cites a merged file, a `RULED` row's
              ruling is a ruling id its source line names; each row's text, or its `quote`, is on
              its cited line; a row its source line marks PROPOSED (next to the string, by its
              status segment, or by the tool's reading of a prose status cell) is not `merged`.
  G-PROV      an `estimated` label / value / chip / name / header / announcement says "estimate";
              a row whose text holds "(estimated)" is `estimated`; no row abbreviates the word;
              no row calls a value exchange-provided unless it says "not".
  G-FROZEN    the deck's frozen rows are the tool's register (FZ-1 ... FZ-15, each on its key);
              at the full stage §9.2 lists them in id order with their keys, cites and the
              register's control, both Security controls appear, and each freeze reads PROPOSED.
  G-COMP      every component on the five `14` Components lines has a §3.2 row, and each row's
              `15` cite is that component's heading.
  G-BIND      §5 holds D02's DB-1 ... DB-28 in order, each source cite on its own DB row, each
              field cell's names on that row, each row with a CMP id and a missing / stale
              reading; DB-26 and DB-27 keep the frozen behaviour's words.
  G-STATE     §6's id ranges equal D02 §9's state ids, screen by screen; §6 states E17-D01 D2's
              feed precedence word for word (the feed-state owner, #672 BQ-9).
  G-A11Y      §8.1 has the five screens in order, each focus cite on its screen's D06 line and
              each narrative cell D06 §5's rows for that screen; §8.2 holds D06's findings with
              their severities; §8.3 D06's A-rows; every quoted D06 narrative sentence is a deck
              row; a carried row is PROPOSED, names its request and
              no longer speaks its finding's defect form; §8.2 names it.
  G-EVENT     §12's events are the five `14` Analytics lines' events, each on its screen.
  G-DERIVED   every BUD, COUNT and DATE anchor is computed from its source; `T`'s four render
              budgets (the ticket JSON's Performance notes) equal `14`'s.
  G-CHECKLIST §16's SO rows are the five `14` checklists, item by item, in order.
  G-OPEN      every §14.1 row names an owner and a due date no later than Sprint 13's start;
              every open G / Q row of D01 ... D06 and D01's open AC rows are listed by id; §14.2
              closes exactly the tool's reading, each on the cited line that closes it.
  G-AROW      every hand-off §C row follows a screen's hi-fi pointer line; A-n run without a gap.
  G-CITE      every cite in the pack and the hand-off is in range, on a non-blank line, and equal
              to the pins file's hash; the SHA anchors are the pinned refs.
  G-FILLED    no placeholder word in the pack, the hand-off or the deck.
  G-HYGIENE   no closing keyword, local path, URL or host, agent name, double-brace slot or
              public-text deny word in the texts; no deny word in this tool or the pins file.
  G-SCOPE     the diff against `git merge-base HEAD origin/main` touches only the stage's files;
              at the full stage `14` too, at the listed anchors only: the working tree's `14` is
              the merge base's with each A-row's New on its own line after its anchor (CAT_ANCHORS)
              and no other line changed. The deck stage stays `14`-strict.

Usage (from the repo root):
  python3 -I docs/design/_tools/e25_d07_handoff_audit.py --stage full --check
  python3 -I docs/design/_tools/e25_d07_handoff_audit.py --stage full --json
  python3 -I docs/design/_tools/e25_d07_handoff_audit.py --stage full --self-test
  python3 -I docs/design/_tools/e25_d07_handoff_audit.py --stage deck --self-test
  python3 -I docs/design/_tools/e25_d07_handoff_audit.py --stage full --repin-ruled
      (the pins file's only writer; the full stage only)
"""

from __future__ import annotations

import argparse
import datetime
import difflib
import hashlib
import json
import re
import subprocess
import sys
from collections.abc import Callable
from dataclasses import dataclass, replace
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
SPEC_REL = "docs/design/E25/E25-D07.md"
HAND_REL = "docs/design/E25/E25-D07-handoff.md"
DECK_REL = "docs/design/E25/E25-D07-copy-deck.jsonl"
TOOL_REL = "docs/design/_tools/e25_d07_handoff_audit.py"
PINS_REL = "docs/design/_tools/e25_d07_ruled_pins.txt"
OWN_PATHS = (SPEC_REL, HAND_REL, DECK_REL, TOOL_REL, PINS_REL)
DECK_PATHS = (DECK_REL, TOOL_REL)
STAGES = ("deck", "full")
BASE = "a45ba3ad1404fb0a3f916f877a0ddaba75293203"  # origin/main; #5415 and #5456 merged into it
D06_REF = "a45ba3ad1404fb0a3f916f877a0ddaba75293203"  # #5456's merge commit
JSON_REL = "docs/plan/backlog/E25.json"
PATHS: dict[str, str] = {
    "02": "docs/plan/02-definition-of-ready-done.md",
    "D01": "docs/design/E25/E25-D01.md",
    "14": "docs/plan/14-screens-catalogue.md",
    "15": "docs/plan/15-component-catalogue.md",
    "D02": "docs/design/E25/E25-D02.md",
    "D03": "docs/design/E25/E25-D03.md",
    "D04": "docs/design/E25/E25-D04.md",
    "D05": "docs/design/E25/E25-D05.md",
    "D06": "docs/design/E25/E25-D06.md",
    "16": "docs/plan/16-design-system-brief.md",
    "22": "docs/plan/22-api-openapi.yaml",
    "E17": "docs/design/E17/E17-D01.md",
    "CAL": "docs/plan/backlog/_tools/calendar_cv.py",
}
CAT_REL = PATHS["14"]
# The `14` anchors the full stage permits (the orchestrator's ruling on #5818, 2026-11-04 12:08Z):
# PR 1b applies A-1 ... A-5, each one line after its screen's hi-fi pointer line at the base. A
# `14` edit anywhere else fails G-SCOPE; G-AROW holds hand-off section C to this list.
CAT_ANCHORS = {"A-1": 1359, "A-2": 1385, "A-3": 1410, "A-4": 1424, "A-5": 1438}
REF_OF = {"D06": D06_REF}  # every other key is read at BASE
MERGED_KEYS = ("D02", "D03", "D04", "D05")  # a deck row cites one of these, never a request ref


@dataclass(frozen=True)
class Screen:
    prefix: str  # D02's state-id prefix
    comp: int  # `14`: the Components line
    perf: int  # `14`: the Performance line
    events: int  # `14`: the Analytics line
    hifi: int  # `14`: the hi-fi pointer line the hand-off A-row follows
    check: int  # `14`: the sign-off checklist line
    focus: int  # `D06`: the focus-order bullet


SCREENS: dict[str, Screen] = {
    "SCR-055": Screen("S55", 1352, 1356, 1357, 1359, 1360, 66),
    "SCR-056": Screen("S56", 1376, 1380, 1381, 1385, 1386, 67),
    "SCR-057": Screen("S57", 1404, 1407, 1408, 1410, 1411, 68),
    "SCR-058": Screen("S58", 1418, 1421, 1422, 1424, 1425, 69),
    "SCR-059": Screen("S59", 1431, 1435, 1436, 1438, 1439, 70),
}
CONSUMERS = tuple(f"E25-S0{i}" for i in range(1, 7))
OWN_KEY = "E25-D07"
E17_D2 = 239  # `E17`: D2, the feed precedence (one state per surface, D1)
T_PERF = re.compile(  # the ticket JSON's Performance notes: SCR-055 ... SCR-058, in that order
    r"SCR-055 <=([\d.]+) ms at (\d+) Hz, SCR-056 <=([\d.]+) ms at (\d+) Hz, "
    r"SCR-057 <=([\d.]+) ms on change, SCR-058 open <=(\d+) ms"
)
T_BUDS = ("s55.ms", "s55.hz", "s56.ms", "s56.hz", "s57.ms", "s58.ms")
PANELS = ("SCR-055", "SCR-056", "SCR-057")  # D06 §5's `all` rows: the panels' one status node
D06_PR = "#5456"
CARRY_DEFECT = {"F-01": re.compile(r"\bpercent\b|%")}  # the spoken form D06 F-01 rules out
# The frozen register (§9.2): id -> (deck key, control). D04 §11 items 1-3 name each control's parts.
ARMED, APPLY = "armed-rule warning", "non-optimistic apply"
FROZEN: dict[str, tuple[str, str]] = {
    "FZ-1": ("detectors.methodology.honesty", "honesty"),
    "FZ-2": ("detectors.settings.armed.callout", ARMED),
    "FZ-3": ("detectors.settings.armed.rationale", ARMED),
    "FZ-4": ("detectors.settings.confirm.title", ARMED),
    "FZ-5": ("detectors.settings.confirm.apply", ARMED),
    "FZ-6": ("detectors.settings.confirm.failsafe", ARMED),
    "FZ-7": ("detectors.settings.confirm.failsafe_heading", ARMED),
    "FZ-8": ("detectors.settings.applying", APPLY),
    "FZ-9": ("detectors.settings.applied", APPLY),
    "FZ-10": ("detectors.settings.not_applied", APPLY),
    "FZ-11": ("detectors.settings.unknown", APPLY),
    "FZ-12": ("detectors.settings.confirm.scope_limited", ARMED),  # D04 §11 item 3: the scope line
    "FZ-13": ("detectors.settings.confirm.scope_all", ARMED),
    "FZ-14": ("detectors.settings.not_sent", APPLY),  # item 2: the `forbidden` leg
    "FZ-15": ("detectors.settings.try_again", APPLY),  # item 2: the deliberate re-fill
}
CONTROLS = ("honesty", ARMED, APPLY)
SECURITY_CONTROLS = (ARMED, APPLY)
DECK_OWNERS = (  # the lanes that hold a deck string's wording
    "E25-D02", "E25-D03", "E25-D04", "E25-D05", "E25-D06", "E09-D09", "E18-D02", "E25-T05",
    "E25-T07", "E40", "the `14` owner",
)  # fmt: skip
RULING = re.compile(r"#\d+ (BQ-\d+)\b|#\d+ comment (\d{6,})")
# A prose status cell, read string by string in its String cell's order (PROPOSED: never merged).
STATUS_READING: dict[tuple[str, int], tuple[str, ...]] = {
    # "PROPOSED in the vocabulary's shape (D04-G4); final CTA (D-10); E09-D09 §3.1"
    ("D04", 406): ("PROPOSED", "merged", "PROPOSED", "merged"),
    # "the first RULED (...); the next three PROPOSED (...); the last composes E09-D09 ..."
    ("D04", 412): ("RULED", "PROPOSED", "PROPOSED", "PROPOSED", "merged"),
}
OPENS_PROPOSED = re.compile(r"(?:^|; )PROPOSED\b")
FROZEN_READINGS = {  # §9.2: the behaviour around the frozen strings is frozen with them
    "DB-26": ("CF-2", "every armed rule listed"),
    "DB-27": ("200: applied", "AP-4 restores", "never re-sends"),
}
# The parents' G / Q tables: (doc, section, first-cell pattern, the id's kind).
PARENT_TABLES = (
    ("D01", "### 9.3", r"G(\d+)", "G"),
    ("D02", "## 23.", r"D02-G(\d+)", "G"),
    ("D02", "## 23.", r"Q(\d+)", "Q"),
    ("D03", "## 16.", r"D03-G(\d+)", "G"),
    ("D04", "## 16.", r"D04-G(\d+)", "G"),
    ("D05", "## 16.", r"G(\d+)", "G"),
    ("D05", "## 17.", r"Q(\d+)", "Q"),
    ("D06", "## 13.", r"G-(\d+)", "G"),
    ("D06", "## 13.", r"Q-(\d+)", "Q"),
)
# Rows a parent or a later parent closed at the base: id -> (doc, line, the words that close it).
CLOSED: dict[str, tuple[str, int, str]] = {
    "D01 G5": ("D01", 301, "**Withdrawn"),
    "D02 Q2": ("D02", 582, "closed: percent"),
    "D02 Q7": ("D04", 110, "memo Q7 closed"),
    "D02 Q9": ("D02", 589, "BQ-7 RULED"),
    "D02 Q11": ("D03", 142, "memo Q11; RULED with R1"),
    "D02 Q12": ("D04", 183, "D01 Q12 closed by the #670 ruling"),
    "D05 Q8": ("D04", 110, "D05 Q8 closes with it"),
    "D05 Q9": ("D03", 142, "memo Q11; RULED with R1"),  # D05 Q9 is memo Q11 (`D02`:110)
    "D04 G1": ("22", 15133, "`422 validation_failed`"),  # #4948 closed D04-G1, G3, G6 and G7
    "D04 G3": ("22", 15130, "Owner-only (`admin:write`)"),
    "D04 G6": ("22", 15134, "Audited as `settings.change`"),
    "D04 G7": ("22", 15137, "Requires `Idempotency-Key`"),
}
CITE = re.compile(r"`(\d\d|D0[1-6]|E17|CAL)`:(\d+(?:–\d+)?(?:, :\d+(?:–\d+)?)*)")
ANCHOR = re.compile(r"`?([^\s<|(`]+)`?<!--=([A-Z0-9]+:[A-Za-z0-9.]+)-->")
CLOSING = re.compile(r"\b(?:close[sd]?|fix(?:e[sd])?|resolve[sd]?)\s+#\d+", re.IGNORECASE)
LOCAL_PATH = re.compile(
    "/" + "home/|/" + "tmp/|/Users/|[A-Za-z]:\\\\|\\bnotes" + "/|\\bwt-" + "notes\\b"
)  # assembled, so this file carries none of the paths it refuses
AGENT_NAME = re.compile(r"\b[a-z]{2,4}-worker-\d\b")
URL_OR_HOST = re.compile(r"https?://|penpot\.[a-z]|team-id=|file-id=", re.IGNORECASE)
PLACEHOLDER = re.compile(r"\bTBD\b|\bTODO\b|\bFIXME\b|\?\?\?|\bXXX\b")
DENY = (
    "le" + "ak",
    "expo" + "sed",
    "by" + "pass",
    "ex" + "ploit",
    "att" + "ack",
    "ora" + "cle",
    "rev" + "eal",
    "unbou" + "nded",
    "flo" + "od",
    "st" + "all",
    "d" + "os",
    "advi" + "sory",
    "gh" + "sa",
    "pre-" + "auth",
)  # each entry an explicit `+` join, so the tool's own text carries none of the words
FIELDS = ("id", "text", "screen", "kind", "where", "status", "owner", "provenance", "source")
OPTIONAL = ("quote", "ruling", "carry", "request")
KINDS = (
    "label",
    "value",
    "chip",
    "name",
    "header",
    "announce",
    "message",
    "notice",
    "reason",
    "button",
    "column",
    "callout",
    "dialog",
    "description",
)
STATUSES = ("merged", "RULED", "PROPOSED")
PROVENANCE = ("none", "estimated")
WORDED_KINDS = ("label", "value", "chip", "name", "header", "announce")
FZ_ID = re.compile(r"FZ-\d+")


@dataclass(frozen=True)
class Texts:
    spec: str
    hand: str
    deck: str
    pins: str
    tool: str
    changed: list[str] | None
    memo: dict[str, str | None]
    full: bool
    missing: tuple[str, ...]
    cat14: str = ""  # the working tree's `14` (the full stage), as PR 1b applied the A-rows


def git(*args: str) -> str | None:
    try:
        r = subprocess.run(["git", "-C", str(ROOT), *args], capture_output=True, check=False)
    except OSError:
        return None
    return r.stdout.decode("utf-8", "surrogateescape") if r.returncode == 0 else None


def show(t: Texts, rev: str, rel: str) -> str | None:
    key = f"{rev}:{rel}"
    if key not in t.memo:
        t.memo[key] = git("show", key)
    return t.memo[key]


def at(t: Texts, key: str) -> str:
    ref = REF_OF.get(key, BASE)
    text = show(t, ref, PATHS[key])
    if text is None:
        raise SystemExit(f"{PATHS[key]} does not resolve at {ref[:10]}; fetch first")
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


def first_table(text: str) -> list[list[str]]:
    """The data rows of the first table in `text` (no header, no separator)."""
    rows: list[list[str]] = []
    started = False
    for ln in text.split("\n"):
        if ln.startswith("|"):
            started = True
            rows.append(cells(ln))
        elif started:
            break
    return rows[2:] if len(rows) > 2 else []


def expand(cell: str) -> list[str]:
    """`S55-1 … S55-14` and `S55-1, S55-3` to the ids they name."""
    out: list[str] = []
    for part in re.split(r",\s*", cell):
        m = re.fullmatch(r"(S5\d)-(\d+)(?: … \1-(\d+))?", part.strip())
        if m:
            out += [f"{m[1]}-{i}" for i in range(int(m[2]), int(m[3] or m[2]) + 1)]
    return out


def expand_n(cell: str) -> list[str]:
    """`N-9 … N-16` and `N-1, N-2` to the narrative ids they name."""
    out: list[str] = []
    for m in re.finditer(r"N-(\d+)(?: … N-(\d+))?", cell):
        out += [f"N-{i}" for i in range(int(m[1]), int(m[2] or m[1]) + 1)]
    return out


def row_ids(cell: str) -> list[str]:
    """`D02-G1, G2`, `D05 Q1–Q7, Q10`, `D06 G-1` and `D01 AC1–AC3` to ids like `D02 G1`.

    A cell names one or more parents, `;`-separated; a cell naming none (Q-1, C-1) is the pack's.
    """
    out: list[str] = []
    for part in cell.split(";"):
        m = re.fullmatch(r"\s*(D0\d)[ -](.+?)\s*", part)
        if not m:
            continue
        for tok in re.split(r",\s*", m[2]):
            k = re.fullmatch(r"(AC|[GQ])-?(\d+)(?:–(?:AC|[GQ])?-?(\d+))?", tok.strip())
            if k:
                out += [f"{m[1]} {k[1]}{i}" for i in range(int(k[2]), int(k[3] or k[2]) + 1)]
            else:
                out.append(f"{m[1]} {tok.strip()}")  # an id no parent carries: G-OPEN names it
    return out


# ---------------------------------------------------------------------------- the deck


@dataclass(frozen=True)
class Deck:
    head: dict[str, object]
    rows: list[dict[str, str | None]]
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
        problems.append("the deck's first line is not the E25-D07 header")
        head = {}
    rows: list[dict[str, str | None]] = []
    for i, ln in enumerate(lines[1:], 2):
        try:
            row = json.loads(ln)
        except json.JSONDecodeError as e:
            problems.append(f"deck:{i} does not parse: {e}")
            continue
        if not isinstance(row, dict) or not all(
            isinstance(v, str) or v is None for v in row.values()
        ):
            problems.append(f"deck:{i} is not an object of strings")
            continue
        rows.append(row)
    return Deck(head, rows, problems)


def s(row: dict[str, str | None], field: str) -> str:
    v = row.get(field)
    return v if isinstance(v, str) else ""


def frozen_rows(t: Texts) -> list[dict[str, str | None]]:
    return [r for r in parse_deck(t.deck).rows if r.get("frozen")]


# ---------------------------------------------------------------------------- values


def find(text: str, rx: str, where: str) -> str:
    m = re.search(rx, text)
    if not m:
        raise LookupError(f"{where} no longer carries /{rx}/ at its base")
    return m[1]


def tickets(t: Texts) -> list[dict[str, object]]:
    raw = show(t, BASE, JSON_REL)
    if raw is None:
        raise LookupError(f"{JSON_REL} does not resolve at the base")
    doc = json.loads(raw)
    items = doc if isinstance(doc, list) else doc.get("tickets", [])
    return [it for it in items if isinstance(it, dict)]


def sprints(t: Texts) -> dict[str, int]:
    out: dict[str, int] = {}
    for it in tickets(t):
        m = re.fullmatch(r"Sprint (\d+)", str(it.get("sprint", "")))
        if m:
            out[str(it.get("key"))] = int(m[1])
    return out


def d02_states(t: Texts) -> list[str]:
    return [r[0] for r in table_rows(section(at(t, "D02"), "## 9."), "S5")]


def checklist(t: Texts, n: int) -> list[str]:
    return [x.strip() for x in line(t, "14", n).split("[ ]")[1:]]


def events_of(t: Texts, n: int) -> list[str]:
    return re.findall(r"`([a-z_]+\.[a-z_]+)`", line(t, "14", n))


def compute(t: Texts) -> dict[str, str]:
    v: dict[str, str] = {"SHA:BASE": BASE[:10], "SHA:D06": D06_REF[:9]}
    deck = parse_deck(t.deck)
    v["COUNT:deck.rows"] = str(len(deck.rows))
    for st in STATUSES:
        v[f"COUNT:deck.{st.lower()}"] = str(sum(r.get("status") == st for r in deck.rows))
    if not t.full:
        return v
    ids = d02_states(t)
    v["COUNT:states.total"] = str(len(ids))
    for sc in SCREENS.values():
        v[f"COUNT:states.{sc.prefix.lower()}"] = str(
            sum(i.startswith(sc.prefix + "-") for i in ids)
        )
    v["COUNT:checklist"] = str(sum(len(checklist(t, sc.check)) for sc in SCREENS.values()))
    v["COUNT:events"] = str(sum(len(events_of(t, sc.events)) for sc in SCREENS.values()))
    p = {k: line(t, "14", sc.perf) for k, sc in SCREENS.items()}
    v["BUD:s55.hz"] = find(p["SCR-055"], r"renders at <=(\d+) Hz", "`14` SCR-055")
    v["BUD:s55.ms"] = find(p["SCR-055"], r"with a ([\d.]+) ms budget", "`14` SCR-055")
    v["BUD:s56.ring"] = find(p["SCR-056"], r"bounded ([\d,]+)-event ring", "`14` SCR-056")
    v["BUD:s56.hz"] = find(p["SCR-056"], r"renders <=(\d+) Hz", "`14` SCR-056")
    v["BUD:s56.ms"] = find(p["SCR-056"], r"with a ([\d.]+) ms budget", "`14` SCR-056")
    v["BUD:s57.hz"] = find(p["SCR-057"], r"at most (\d+) Hz", "`14` SCR-057")
    v["BUD:s57.ms"] = find(p["SCR-057"], r"Budget <=(\d+) ms", "`14` SCR-057")
    v["BUD:s58.ms"] = find(p["SCR-058"], r"opens in <=(\d+) ms", "`14` SCR-058")
    v["BUD:s59.s"] = find(p["SCR-059"], r"window \(<=(\d+) s\)", "`14` SCR-059")
    own = next((str(it.get("body", "")) for it in tickets(t) if it.get("key") == OWN_KEY), "")
    tm = T_PERF.search(own)
    if not tm:
        raise LookupError("the ticket JSON's Performance notes no longer carry the four budgets")
    v.update({f"BUD:t.{k}": tm[i] for i, k in enumerate(T_BUDS, 1)})
    cal = at(t, "CAL")
    y, mo, d = (int(x) for x in re.findall(r"\d+", find(cal, r"SPRINT01_START = (.+)", "CAL")))
    start = datetime.date(y, mo, d)
    days = int(find(cal, r"SPRINT_DAYS = (\d+)", "CAL"))
    sp = sprints(t)
    if OWN_KEY not in sp or any(c not in sp for c in CONSUMERS):
        raise LookupError("the ticket JSON lacks a sprint for E25-D07 or a consumer")
    first = min(sp[c] for c in CONSUMERS)

    def s_start(n: int) -> datetime.date:
        return start + datetime.timedelta(days=(n - 1) * days)

    def s_end(n: int) -> datetime.date:
        return s_start(n) + datetime.timedelta(days=days - 1)

    v["DATE:s11.end"] = s_end(sp[OWN_KEY]).isoformat()
    v["DATE:s13.start"] = s_start(first).isoformat()
    v["DATE:s12.end"] = (s_start(first) - datetime.timedelta(days=1)).isoformat()
    v["DATE:s10.end"] = s_end(first - 3).isoformat()
    return v


def anchor_problems(t: Texts, vals: dict[str, str], prefixes: tuple[str, ...]) -> list[str]:
    bad = []
    for text in (t.spec, t.hand):
        for value, key in ANCHOR.findall(text):
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
    for key, a, b in cites(t.spec + "\n" + t.hand):
        label = f"{key}:{a}" if a == b else f"{key}:{a}–{b}"
        if label in hashes:
            continue
        ls = at(t, key).split("\n")
        if not 0 < a <= b <= len(ls):
            bad.append(f"{label} is past the end of {PATHS[key]} ({len(ls)} lines)")
            continue
        blank = [n for n in (a, b) if not ls[n - 1].strip()]
        if blank:
            bad.append(f"{label}: line {blank[0]} is blank at its ref")
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


def g_stage(t: Texts, vals: dict[str, str]) -> list[str]:
    return [f"{p} is missing; the {stage(t)} stage needs it" for p in t.missing]


def source_reading(ln: str, want: str, where: tuple[str, int]) -> str | None:
    """What a copy-table line's status cell says of the string `want`: PROPOSED, RULED or None."""
    if not ln.startswith("| CP"):
        return None
    c = cells(ln)
    strings = re.findall(r'"([^"]+)"', c[2]) if len(c) > 3 else []
    idx = next((i for i, x in enumerate(strings) if x == want), None)
    if idx is None:
        idx = next((i for i, x in enumerate(strings) if want in x), None)
    if idx is None:
        return None
    if where in STATUS_READING:
        reading = STATUS_READING[where]
        return reading[idx] if idx < len(reading) and reading[idx] != "merged" else None
    segs = c[-1].split(" · ")
    seg = segs[idx] if len(segs) == len(strings) else c[-1]
    return "PROPOSED" if OPENS_PROPOSED.search(seg) else None


def g_deck(t: Texts, vals: dict[str, str]) -> list[str]:
    deck = parse_deck(t.deck)
    bad = list(deck.problems)
    refs = (deck.head.get("base"), deck.head.get("d06_ref"))
    if deck.head and refs != (BASE[:10], D06_REF[:9]):
        bad.append("the deck's header names other refs than the tool's")
    if deck.head and deck.head.get("key_naming") != "PROPOSED":
        bad.append("the deck's header does not keep the key naming PROPOSED (#672 BQ-13)")
    seen: set[str] = set()
    for r in deck.rows:
        k = s(r, "id") or "?"
        missing = [f for f in FIELDS if not s(r, f)]
        if missing or "frozen" not in r or not s(r, "consumer"):
            bad.append(f"{k}: no {', '.join(missing) or 'frozen flag or consumer'}")
            continue
        extra = set(r) - {*FIELDS, "frozen", "consumer", *OPTIONAL}
        if extra:
            bad.append(f"{k}: unknown fields {sorted(extra)}")
        if not re.fullmatch(r"detectors\.[a-z0-9_.]+", k):
            bad.append(f"{k}: not a `detectors.*` key")
        if k in seen:
            bad.append(f"{k}: a repeated id")
        seen.add(k)
        checks = (("kind", KINDS), ("status", STATUSES), ("provenance", PROVENANCE),
                  ("screen", (*SCREENS, "all")), ("consumer", CONSUMERS))  # fmt: skip
        for field, allowed in checks:
            if s(r, field) not in allowed:
                bad.append(f"{k}: {field} {s(r, field)!r} is not one of the deck's")
        if r.get("frozen") is not None and not FZ_ID.fullmatch(s(r, "frozen")):
            bad.append(f"{k}: frozen {r.get('frozen')!r} is neither null nor an FZ id")
        m = re.fullmatch(r"(D0[2-5]):(\d+)", s(r, "source"))
        if not m or m[1] not in MERGED_KEYS:
            bad.append(f"{k}: source {s(r, 'source')!r} is not a merged parent and a line")
            continue
        stray = [o for o in s(r, "owner").split(", ") if o not in DECK_OWNERS]
        if stray:
            bad.append(f"{k}: owner {stray[0]!r} is not one of the parents' lanes")
        want = s(r, "quote") or s(r, "text")
        ln = line(t, m[1], int(m[2]))
        if s(r, "status") == "RULED":
            rm = RULING.search(s(r, "ruling"))
            if not rm or (rm[1] or rm[2]) not in ln:
                bad.append(f"{k}: ruling {s(r, 'ruling')!r} is no ruling id its source line names")
        if want not in ln:
            bad.append(f"{k}: {want[:40]!r} is not on {s(r, 'source')} at the base")
        marked = (f'"{want}" (PROPOSED', f'"{want}" PROPOSED', f"{want} (PROPOSED")
        reading = source_reading(ln, want, (m[1], int(m[2])))
        if s(r, "status") == "merged" and (any(x in ln for x in marked) or reading):
            bad.append(f"{k}: its source line marks it {reading or 'PROPOSED'}; the row: merged")
        elif reading == "RULED" and s(r, "status") != "RULED":
            bad.append(f"{k}: its source line rules it; the row says {s(r, 'status')}")
    return bad


def g_prov(t: Texts, vals: dict[str, str]) -> list[str]:
    bad = []
    for r in parse_deck(t.deck).rows:
        k, text = s(r, "id"), s(r, "text")
        low = text.lower()
        worded = s(r, "provenance") == "estimated" and s(r, "kind") in WORDED_KINDS
        if worded and "estimate" not in low:
            bad.append(f"{k}: an estimated {s(r, 'kind')} that does not say so")
        if "(estimated)" in low and s(r, "provenance") != "estimated":
            bad.append(f"{k}: says (estimated) but its provenance is {s(r, 'provenance')!r}")
        if "Est." in text:
            bad.append(f"{k}: abbreviates the word (`D02`: the full word, never the short form)")
        if "exchange-provided" in low and "not exchange-provided" not in low:
            bad.append(f"{k}: calls a value exchange-provided")
    return bad


def g_frozen(t: Texts, vals: dict[str, str]) -> list[str]:
    deck = frozen_rows(t)
    got = {s(r, "frozen"): s(r, "id") for r in deck}
    want = {fz: key for fz, (key, _) in FROZEN.items()}
    bad = []
    if len(got) != len(deck) or got != want:
        diff = sorted(f for f in {*got, *want} if got.get(f) != want.get(f)) or ["a repeated id"]
        bad.append(f"the deck's frozen rows differ from the tool's register on {diff}")
    if not t.full:
        return bad
    rows = table_rows(section(t.spec, "### 9.2"), "FZ-")
    order = sorted(FROZEN, key=lambda f: int(f[3:]))
    if [r[0] for r in rows] != order:
        bad.append(f"§9.2's rows are {[r[0] for r in rows]}; the register is {order}")
    by_id = {s(r, "frozen"): r for r in deck}
    for r in rows:
        d, reg = by_id.get(r[0]), FROZEN.get(r[0])
        if d is None or reg is None or len(r) < 5:
            continue
        if r[1].strip("`") != reg[0]:
            bad.append(f"{r[0]}: §9.2 names {r[1]}, the register {reg[0]}")
        if r[2] != reg[1]:
            bad.append(f"{r[0]}: control {r[2]!r}; the register (D04 §11) reads {reg[1]!r}")
        if r[3].replace("`", "") != s(d, "source"):
            bad.append(f"{r[0]}: the owner cite {r[3]} is not the deck row's {s(d, 'source')}")
        if r[4] != "PROPOSED":
            bad.append(f"{r[0]}: the freeze reads {r[4]!r}; only the owner rules it")
    for c in SECURITY_CONTROLS:
        if c not in {r[2] for r in rows if len(r) > 2}:
            bad.append(f"no frozen string carries the {c} (`T` Security note)")
    return bad


def g_comp(t: Texts, vals: dict[str, str]) -> list[str]:
    rows = {r[0]: r for r in table_rows(section(t.spec, "### 3.2"), "CMP-")}
    bad = []
    for name, sc in SCREENS.items():
        need = re.findall(r"CMP-\d{3}", line(t, "14", sc.comp))
        if not need:
            bad.append(f"`14` {name}'s Components line names no component")
        bad += [f"{c} is on `14` {name}'s Components line but has no §3.2 row" for c in need
                if c not in rows]  # fmt: skip
    for c, r in rows.items():
        m = re.fullmatch(r"`15`:(\d+)", r[2]) if len(r) > 2 else None
        if not m:
            bad.append(f"{c}: no `15` heading cite")
        elif not line(t, "15", int(m[1])).startswith(f"### {c} "):
            bad.append(f"{c}: `15`:{m[1]} is not its heading")
    return bad


def g_bind(t: Texts, vals: dict[str, str]) -> list[str]:
    theirs = [r[0] for r in table_rows(section(at(t, "D02"), "## 15."), "DB-")]
    ours = table_rows(section(t.spec, "## 5."), "DB-")
    bad = []
    if [r[0] for r in ours] != theirs or not theirs:
        bad.append(f"§5's rows are {[r[0] for r in ours]}, not D02 §15's {theirs}")
    for r in ours:
        if len(r) < 8:
            bad.append(f"{r[0]}: {len(r)} cells, not 8")
            continue
        m = re.fullmatch(r"`D02`:(\d+)", r[3])
        theirs_ln = line(t, "D02", int(m[1])) if m else ""
        if not theirs_ln.startswith(f"| {r[0]} "):
            bad.append(f"{r[0]}: the source cite {r[3]} is not D02's {r[0]} row")
        if not r[4]:
            bad.append(f"{r[0]}: no field cell")
        bad += [f"{r[0]}: the field {n!r} is not on D02's row" for n in re.findall(r"`([^`]+)`", r[4])
                if n not in theirs_ln]  # fmt: skip
        if not re.search(r"CMP-\d{3}", r[5]):
            bad.append(f"{r[0]}: no component")
        if r[7] in ("", "—"):
            bad.append(f"{r[0]}: no missing / insufficient / stale reading")
        bad += [f"{r[0]}: the frozen behaviour's {w!r} is gone from its reading"
                for w in FROZEN_READINGS.get(r[0], ()) if w not in r[7]]  # fmt: skip
    return bad


def g_state(t: Texts, vals: dict[str, str]) -> list[str]:
    ids = d02_states(t)
    rows = {r[0]: r for r in table_rows(section(t.spec, "## 6."), "SCR-")}
    bad = [] if ids else ["D02 §9 has no state rows"]
    m = re.search(r"Feed precedence is ([A-Za-z >]+?);", line(t, "E17", E17_D2))
    if not m or m[1] not in section(t.spec, "## 6."):
        bad.append("§6 does not state E17-D01 D2's feed precedence word for word")
    for name, sc in SCREENS.items():
        theirs = sorted((i for i in ids if i.startswith(sc.prefix + "-")), key=lambda i: int(i[4:]))
        r = rows.get(name)
        ours = expand(r[1]) if r and len(r) > 1 else []
        if ours != theirs:
            bad.append(f"{name}: §6 names {len(ours)} ids, D02 §9 has {theirs}")
    return bad


def g_a11y(t: Texts, vals: dict[str, str]) -> list[str]:
    bad = []
    rows = table_rows(section(t.spec, "### 8.1"), "SCR-")
    if [r[0] for r in rows] != list(SCREENS):
        bad.append(f"§8.1's rows are {[r[0] for r in rows]}, not the five screens")
    d06 = at(t, "D06")
    narr: dict[str, list[str]] = {}
    for r in table_rows(section(d06, "## 5."), "N-"):
        for name in PANELS if len(r) > 1 and r[1] == "all" else r[1:2]:
            narr.setdefault(name, []).append(r[0])
    for r in rows:
        sc = SCREENS.get(r[0])
        if sc is None or len(r) < 5 or any(not c for c in r[1:5]):
            bad.append(f"§8.1 {r[0]}: a missing cell (focus, narrative, T2, reduce)")
            continue
        if r[1] != f"`D06`:{sc.focus}" or not line(t, "D06", sc.focus).startswith(f"- **{r[0]}:"):
            bad.append(f"§8.1 {r[0]}: the focus cite {r[1]} is not its D06 focus line")
        if expand_n(r[2]) != narr.get(r[0], []):
            bad.append(f"§8.1 {r[0]}: narrative {r[2]!r}; D06 §5 has {narr.get(r[0], [])}")
    theirs = {r[0]: r[1] for r in table_rows(section(d06, "## 11."), "F-")}
    ours = {r[0]: r[1] for r in table_rows(section(t.spec, "### 8.2"), "F-")}
    if ours != theirs or not theirs:
        diff = sorted(k for k in {*ours, *theirs} if ours.get(k) != theirs.get(k))
        bad.append(f"§8.2 differs from D06 §11 on {diff or 'every row'}")
    a_theirs = re.findall(r"^- \*\*(A-\d+) ", section(d06, "## 12."), re.MULTILINE)
    a_ours = [r[0].removeprefix("D06 ") for r in table_rows(section(t.spec, "### 8.3"), "D06 A-")]
    if a_ours != a_theirs or not a_theirs:
        bad.append(f"§8.3 routes {a_ours}; D06 §12 has {a_theirs}")
    deck = parse_deck(t.deck).rows
    texts = {s(r, "text") for r in deck}
    for r in table_rows(section(d06, "## 5."), "N-"):
        quoted = re.findall(r'"([^"]+)"', r[3]) if len(r) > 3 else []
        if not quoted:
            continue
        if quoted[0] not in texts:
            bad.append(f"{r[0]}: D06's sentence {quoted[0][:40]!r} is not a deck row")
    request = re.compile(rf"D06 A-\d+ \({D06_PR}\)")
    for d in deck:
        f, k = s(d, "carry"), s(d, "id")
        if not f:
            continue
        rx = CARRY_DEFECT.get(f)
        if rx is None or rx.search(s(d, "text")):
            bad.append(f"{k}: still speaks {f}'s defect form; the text takes the A-row's form")
        if s(d, "status") != "PROPOSED" or not request.fullmatch(s(d, "request")):
            bad.append(f"{k}: a carried row is PROPOSED and names its request (D06 A-n ({D06_PR}))")
    carried = [s(r, "id") for r in deck if s(r, "carry") == "F-01"]
    f01 = next((r for r in table_rows(section(t.spec, "### 8.2"), "F-01")), [])
    if not carried or not f01 or f"`{carried[0]}`" not in f01[-1]:
        bad.append("F-01's carry is not on a deck row named in §8.2")
    return bad


def g_event(t: Texts, vals: dict[str, str]) -> list[str]:
    theirs = {(e, name) for name, sc in SCREENS.items() for e in events_of(t, sc.events)}
    ours = {(r[0].strip("`"), r[1]) for r in table_rows(section(t.spec, "## 12."), "`")}
    bad = [] if theirs else ["the `14` Analytics lines name no event"]
    if ours != theirs:
        bad.append(f"§12 differs from `14`: {sorted(ours ^ theirs)}")
    return bad


def g_derived(t: Texts, vals: dict[str, str]) -> list[str]:
    bad = [f"`T`'s {k} reads {vals[f'BUD:t.{k}']}; `14` reads {vals[f'BUD:{k}']}" for k in T_BUDS
           if vals[f"BUD:t.{k}"] != vals[f"BUD:{k}"]]  # fmt: skip
    return bad + anchor_problems(t, vals, ("BUD:", "COUNT:", "DATE:"))


def g_checklist(t: Texts, vals: dict[str, str]) -> list[str]:
    rows = table_rows(section(t.spec, "## 16."), "SO-")
    bad = []
    if [r[0] for r in rows] != [f"SO-{i}" for i in range(1, len(rows) + 1)] or not rows:
        bad.append(f"§16's rows are {[r[0] for r in rows]}: a gap or none")
    for name, sc in SCREENS.items():
        theirs = checklist(t, sc.check)
        ours = [r[2] for r in rows if len(r) > 3 and r[1] == name]
        if ours != theirs or not theirs:
            bad.append(f"{name}: §16's items differ from `14`'s checklist ({len(theirs)} boxes)")
        bad += [f"{r[0]}: no 'Met in' cell" for r in rows if r[1] == name and not r[-1]]
    return bad


def parent_ids(t: Texts) -> tuple[set[str], list[str]]:
    """Every G / Q id the parents' tables carry, and D01's open AC rows (D01's Q rows are D02's)."""
    ids: set[str] = set()
    bad: list[str] = []
    for doc, head, rx, kind in PARENT_TABLES:
        for r in table_rows(section(at(t, doc), head), ""):
            m = re.fullmatch(rx, r[0])
            if m:
                ids.add(f"{doc} {kind}{m[1]}")
    trace = section(at(t, "D01"), "## Acceptance-criteria trace")
    for r in table_rows(trace, "AC"):
        m = re.match(r"AC(\d+) ", r[0])
        if m and len(r) > 2 and r[2] == "open":
            ids.add(f"D01 AC{m[1]}")
    memo_q = [r[0] for r in table_rows(section(at(t, "D01"), "### 9.4"), "Q") if r[0][1:].isdigit()]
    handed = sorted((i for i in ids if i.startswith("D02 Q")), key=lambda i: int(i[5:]))
    if [f"D02 {q}" for q in memo_q] != handed or not memo_q:
        bad.append(f"D01 §9.4's {memo_q} are not D02 §23's handed-over rows")
    if not any(i.startswith("D06 ") for i in ids) or not any(i.startswith("D01 G") for i in ids):
        bad.append("a parent's G / Q table no longer parses")
    return ids, bad


def g_open(t: Texts, vals: dict[str, str]) -> list[str]:
    rows = first_table(section(t.spec, "### 14.1"))
    shut = first_table(section(t.spec, "### 14.2"))
    bad = [] if rows else ["§14.1 has no rows"]
    last = vals.get("DATE:s13.start", "")
    for r in rows:
        due = re.search(r"\d{4}-\d\d-\d\d", r[3]) if len(r) > 3 else None
        if len(r) < 4 or not r[2]:
            bad.append(f"§14 {r[0]}: no owner")
        elif not due:
            bad.append(f"§14 {r[0]}: no due date")
        elif due[0] > last:
            bad.append(f"§14 {r[0]}: due {due[0]}, after Sprint 13's first day {last}")
    ids, bad_p = parent_ids(t)
    bad += bad_p
    listed = [i for r in rows for i in row_ids(r[0])]
    closed = {i: r for r in shut for i in row_ids(r[0])}
    seen = listed + list(closed)
    bad += [f"§14 names {i}, which no parent carries" for i in sorted(set(seen) - ids)]
    bad += [f"§14 names {i} twice" for i in sorted({i for i in seen if seen.count(i) > 1})]
    bad += [f"{i} is open in its parent and not in §14.1" for i in sorted(ids - set(seen))
            if i not in CLOSED]  # fmt: skip
    for i, (doc, n, words) in CLOSED.items():
        if words not in line(t, doc, n):
            bad.append(f"{i}: `{doc}`:{n} no longer carries {words!r}")
        if i not in closed:
            bad.append(f"{i} is closed at `{doc}`:{n}; §14.2 does not record it")
        elif f"`{doc}`:{n}" not in closed[i][-1]:
            bad.append(f"§14.2 {i}: the cite is not `{doc}`:{n}, the line that closes it")
    bad += [f"§14.2 closes {i}, which the tool reads as open" for i in closed if i not in CLOSED]
    return bad


def g_arow(t: Texts, vals: dict[str, str]) -> list[str]:
    rows = table_rows(section(t.hand, "## §C"), "A-")
    bad = []
    if [r[0] for r in rows] != [f"A-{i}" for i in range(1, len(rows) + 1)] or not rows:
        bad.append(f"§C's rows are {[r[0] for r in rows]}: a gap or none")
    hit = set()
    for r in rows:
        m = re.match(r"`14`:(\d+)", r[1]) if len(r) > 2 else None
        if not m or not line(t, "14", int(m[1])).startswith("- **Hi-fi (E25-D0"):
            bad.append(f"{r[0]}: does not follow a screen's hi-fi pointer line")
            continue
        hit.add(int(m[1]))
        if r[2] != "—":
            bad.append(f"{r[0]}: an insert row with Old text")
    if hit != {sc.hifi for sc in SCREENS.values()}:
        bad.append("§C does not follow each of the five screens' pointer lines once")
    anchors = {r[0]: int(m[1]) for r in rows if (m := re.match(r"`14`:(\d+)", r[1]))}
    if anchors != CAT_ANCHORS:
        bad.append(f"§C's anchors {anchors} are not the permitted list {CAT_ANCHORS}")
    return bad


def g_cite(t: Texts, vals: dict[str, str]) -> list[str]:
    hashes, bad = cite_hashes(t)
    pinned = parse_pins(t.pins)
    for label, h in hashes.items():
        if label not in pinned:
            bad.append(f"cite {label} is unpinned: verify it by content, then --repin-ruled")
        elif pinned[label] != h:
            bad.append(f"cite {label}: the line at its ref is not the pinned content")
    bad += anchor_problems(t, vals, ("SHA:",))
    return bad


def g_filled(t: Texts, vals: dict[str, str]) -> list[str]:
    bad = []
    for label, text in (("spec", t.spec), ("hand-off", t.hand), ("deck", t.deck)):
        for i, ln in enumerate(text.split("\n"), 1):
            if PLACEHOLDER.search(ln):
                bad.append(f"{label}:{i} carries a placeholder")
    return bad


def g_hygiene(t: Texts, vals: dict[str, str]) -> list[str]:
    bad = []
    checks = ((CLOSING, "a closing keyword (the closing PR alone closes #672)"),
              (LOCAL_PATH, "a local path"), (AGENT_NAME, "an agent name"),
              (URL_OR_HOST, "a URL or a host"))  # fmt: skip
    for label, text in (("spec", t.spec), ("hand-off", t.hand), ("deck", t.deck)):
        for i, ln in enumerate(text.split("\n"), 1):
            for rx, what in checks:
                if rx.search(ln):
                    bad.append(f"{label}:{i} carries {what}")
            if "{{" in ln:
                bad.append(f"{label}:{i} carries a double-brace slot")
            if any(d in ln.lower() for d in DENY):
                bad.append(f"{label}:{i} carries a public-text deny word")
    for label, text in (("tool", t.tool), ("pins", t.pins)):
        for i, ln in enumerate(text.split("\n"), 1):
            if any(d in ln.lower() for d in DENY):
                bad.append(f"{label}:{i} carries a public-text deny word")
    for text in (t.spec, t.hand):
        for _, key in ANCHOR.findall(text):
            if key not in vals:
                bad.append(f"an anchor `{key}` the tool does not compute")
    return bad


def cat_scope(t: Texts) -> list[str]:
    """The full stage's `14`: the merge base's, with each A-row's New on its own line after its
    listed anchor (CAT_ANCHORS), bottom-up; any other difference is a stray edit."""
    mb = git("merge-base", "HEAD", "origin/main")
    old = show(t, mb.strip(), CAT_REL) if mb else None
    if old is None:
        return ["cannot read `14` at the merge base (git failed)"]
    ls = old.split("\n")
    new_of = {r[0]: r[3] for r in table_rows(section(t.hand, "## §C"), "A-") if len(r) > 3}
    bad, at_i = [], []
    for aid, n in CAT_ANCHORS.items():
        anchor, new = line(t, "14", n), new_of.get(aid, "")
        if len(new) < 2 or not (new[0] == new[-1] == '"'):
            bad.append(f"{aid}: §C carries no quoted New text to apply")
            continue
        hits = [i for i, x in enumerate(ls) if x == anchor]
        if len(hits) != 1:
            bad.append(f"{aid}: its anchor `14`:{n} stands {len(hits)} times at the merge base")
            continue
        at_i.append((hits[0], new[1:-1]))
    for i, new in sorted(at_i, reverse=True):
        ls.insert(i + 1, new)
    want, have = ls, t.cat14.split("\n")
    ops = difflib.SequenceMatcher(None, want, have, autojunk=False).get_opcodes()
    for op, _, _, j1, j2 in ops:
        if op != "equal":
            where = f"`14`:{j1 + 1}" if j2 > j1 else f"after `14`:{j1}"
            bad.append(f"{where}: {op} outside the permitted anchors {sorted(CAT_ANCHORS)}")
    return bad


def g_scope(t: Texts, vals: dict[str, str]) -> list[str]:
    if t.changed is None:
        return ["cannot list the changed paths (git failed)"]
    own = (*OWN_PATHS, CAT_REL) if t.full else DECK_PATHS
    bad = [f"{p} is touched; the {stage(t)} stage owns {', '.join(own)}" for p in t.changed
           if p not in own]  # fmt: skip
    return bad + (cat_scope(t) if t.full else [])


GATES: dict[str, Callable[[Texts, dict[str, str]], list[str]]] = {
    "G-STAGE": g_stage, "G-DECK": g_deck, "G-PROV": g_prov, "G-FROZEN": g_frozen,
    "G-COMP": g_comp, "G-BIND": g_bind, "G-STATE": g_state, "G-A11Y": g_a11y,
    "G-EVENT": g_event, "G-DERIVED": g_derived, "G-CHECKLIST": g_checklist, "G-OPEN": g_open,
    "G-AROW": g_arow, "G-CITE": g_cite, "G-FILLED": g_filled, "G-HYGIENE": g_hygiene,
    "G-SCOPE": g_scope,
}  # fmt: skip
DECK_GATES = ("G-STAGE", "G-DECK", "G-PROV", "G-FROZEN", "G-HYGIENE", "G-SCOPE")
DECK_LEAVES = ("G-FROZEN's §9.2 match", "G-HYGIENE over the spec, the hand-off and the pins")


def stage(t: Texts) -> str:
    return "full" if t.full else "deck"


def gates_of(t: Texts) -> dict[str, Callable[[Texts, dict[str, str]], list[str]]]:
    return {g: fn for g, fn in GATES.items() if t.full or g in DECK_GATES}


def not_run(t: Texts) -> list[str]:
    return [g for g in GATES if g not in gates_of(t)]


def audit(t: Texts) -> list[tuple[str, str]]:
    if t.missing:  # default-deny: no gate reads a file that is not there
        return [("G-STAGE", m) for m in g_stage(t, {})]
    try:
        vals = compute(t)
    except LookupError as e:
        return [("G-DERIVED", str(e))]
    return [(g, msg) for g, fn in gates_of(t).items() for msg in fn(t, vals)]


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


def load(stage_name: str) -> Texts:
    full = stage_name == "full"
    need = OWN_PATHS if full else DECK_PATHS
    missing = tuple(rel for rel in need if not (ROOT / rel).exists())
    if full:
        return Texts(read(SPEC_REL), read(HAND_REL), read(DECK_REL), read(PINS_REL),
                     read(TOOL_REL), changed_paths(), {}, True, missing, read(CAT_REL))  # fmt: skip
    # the deck stage reads the deck and this tool alone, present pack files or not
    return Texts("", "", read(DECK_REL), "", read(TOOL_REL), changed_paths(), {}, False, missing)


Mutation = Callable[[Texts], Texts]


def sub(field: str, old: str, new: str) -> Mutation:
    def f(t: Texts) -> Texts:
        text = str(getattr(t, field))
        if text.count(old) != 1:
            raise SystemExit(f"self-test: {field} carries {old[:50]!r} {text.count(old)} times")
        new_text = text.replace(old, new)
        if field == "spec":
            return replace(t, spec=new_text)
        if field == "hand":
            return replace(t, hand=new_text)
        return replace(t, deck=new_text)

    return f


def set_cell(row: str, col: int, value: str, within: str = "") -> Mutation:
    def f(t: Texts) -> Texts:
        ls = t.spec.split("\n")
        start = next(k for k, ln in enumerate(ls) if ln.startswith(within)) if within else 0
        i = next(k for k, ln in enumerate(ls) if k >= start and ln.startswith(f"| {row} "))
        cs = cells(ls[i])
        cs[col] = value
        ls[i] = "| " + " | ".join(cs) + " |"
        return replace(t, spec="\n".join(ls))

    return f


def deck_set(key: str, **fields: str) -> Mutation:
    def f(t: Texts) -> Texts:
        out = []
        for ln in t.deck.split("\n"):
            if ln.startswith(f'{{"id": "{key}"'):
                row = json.loads(ln)
                row.update(fields)
                ln = json.dumps(row, ensure_ascii=False)
            out.append(ln)
        return replace(t, deck="\n".join(out))

    return f


def missing(rel: str) -> Mutation:
    return lambda t: replace(t, missing=(rel,))


def deny_in_tool(t: Texts) -> Texts:
    return replace(t, tool=t.tool + "\n# " + DENY[6] + "\n")


def touch_14(t: Texts) -> Texts:
    return replace(t, changed=[*(OWN_PATHS if t.full else DECK_PATHS), PATHS["14"]])


def touch_15(t: Texts) -> Texts:
    return replace(t, changed=[*OWN_PATHS, CAT_REL, PATHS["15"]])


def add_a7(t: Texts) -> Texts:
    ls = t.hand.split("\n")
    i = next(k for k, ln in enumerate(ls) if ln.startswith("| A-5 |"))
    return replace(t, hand="\n".join([*ls[: i + 1], "| A-7 " + ls[i][6:], *ls[i + 1 :]]))


def cat_sub(old: str, new: str) -> Mutation:
    """Edits the working tree's `14` only (the full stage's applied A-rows)."""

    def f(t: Texts) -> Texts:
        if t.cat14.count(old) != 1:
            raise SystemExit(f"self-test: `14` carries {old[:50]!r} {t.cat14.count(old)} times")
        return replace(t, cat14=t.cat14.replace(old, new))

    return f


# fmt: off
MUTATIONS: tuple[tuple[str, str, Mutation], ...] = (
    ("G-STAGE", "the hand-off missing at the full stage", missing(HAND_REL)),
    ("G-DECK", "blank a deck row's owner", deck_set("detectors.tape.header", owner="")),
    ("G-DECK", "give a row a text not on its line", deck_set("detectors.tape.band.calm", text="steady")),
    ("G-DECK", "call a PROPOSED string merged (the counts kept)", lambda t: deck_set("detectors.tape.window.1s", status="PROPOSED")(deck_set("detectors.settings.invalid.big_trade.absolute_usd", status="merged")(t))),
    ("G-DECK", "call a status-cell PROPOSED row merged (the counts kept)", lambda t: deck_set("detectors.tape.window.5s", status="PROPOSED")(deck_set("detectors.imbalance.recomputing", status="merged")(t))),
    ("G-DECK", "call FZ-11's prose-read PROPOSED row merged (the counts kept)", lambda t: deck_set("detectors.tape.window.30s", status="PROPOSED")(deck_set("detectors.settings.unknown", status="merged")(t))),
    ("G-DECK", "give a RULED row a free-text ruling", deck_set("detectors.settings.scope", ruling="the owner said so")),
    ("G-DECK", "give a PROPOSED row an owner no lane holds", deck_set("detectors.tape.header", owner="nobody")),
    ("G-PROV", "mark a row estimated that does not say so", deck_set("detectors.tape.band.calm", provenance="estimated")),
    ("G-PROV", "flip an (estimated) chip's provenance to none", deck_set("detectors.regime.chip.calm", provenance="none")),
    ("G-FROZEN", "rule a freeze in the spec", set_cell("FZ-3", 4, "RULED")),
    ("G-FROZEN", "relabel FZ-6's control", set_cell("FZ-6", 2, "honesty")),
    ("G-COMP", "point CMP-131's heading cite at CMP-132's", set_cell("CMP-131", 2, "`15`:1632")),
    ("G-BIND", "blank DB-7's missing reading", set_cell("DB-7", 7, "—")),
    ("G-BIND", "make DB-27's reading optimistic", set_cell("DB-27", 7, "the press: applied; refused: a re-send")),
    ("G-STATE", "drop a state from §6", sub("spec", "S57-1 … S57-12", "S57-1 … S57-11")),
    ("G-A11Y", "lower F-01's severity", set_cell("F-01", 1, "Minor")),
    ("G-A11Y", "cut SCR-059's narrative cell to N-9", set_cell("SCR-059", 2, "N-9", within="### 8.1")),
    ("G-A11Y", "put F-01's defect form back into the carried row", deck_set("detectors.imbalance.row.name", text="Sell stack ×3, 64,060 to 64,090, ratio 310 percent, tested, 350 ticks above")),
    ("G-EVENT", "rename an event", set_cell("`imbalance.event_clicked`", 0, "`imbalance.row_clicked`")),
    ("G-DERIVED", "type a wrong SCR-056 budget", sub("spec", "1.5<!--=BUD:s56.ms-->", "2<!--=BUD:s56.ms-->")),
    ("G-CHECKLIST", "reword a checklist item", set_cell("SO-5", 2, "quiet-market state")),
    ("G-OPEN", "drop an owner from §14", set_cell("C-3", 2, "")),
    ("G-OPEN", "move a due date past Sprint 13's start", set_cell("C-4", 3, "2027-01-07")),
    ("G-OPEN", "drop a row #4948 closed from §14.2", sub("spec", "| D04 G3 ", "| D04 G33 ")),
    ("G-STATE", "rank Delayed above Resyncing in §6", sub("spec", "> Resyncing > Delayed >", "> Delayed > Resyncing >")),
    ("G-DERIVED", "type a wrong `T` budget", sub("spec", "1.5<!--=BUD:t.s56.ms-->", "2<!--=BUD:t.s56.ms-->")),
    ("G-OPEN", "drop a parent's open row from §14", sub("spec", "D05 G1, G11, G12", "D05 G1, G11")),
    ("G-OPEN", "close an open row in §14.2", sub("spec", "| D05 Q9 ", "| D05 Q9, Q10 ")),
    ("G-AROW", "leave a gap in §C (an A-7 after A-5)", add_a7),
    ("G-CITE", "re-point a `D04` cite to an unpinned line", sub("spec", "(`D04`:208)", "(`D04`:209)")),
    ("G-FILLED", "write a placeholder", sub("spec", "The table is empty until the walkthrough is posted on #672.", "The table is TBD.")),
    ("G-HYGIENE", "write a closing keyword against #672", sub("spec", "it alone carries the closing line,", "it alone carries the closing line (Closes #672),")),
    ("G-HYGIENE", "put a deny word into the tool's own text", deny_in_tool),
    ("G-SCOPE", "touch `15` in the diff", touch_15),
    ("G-SCOPE", "edit a `14` line no A-row lists (SCR-055's checklist)", cat_sub("rolling window selector (10s/1m/5m)", "rolling window selector (10s/1m)")),
    ("G-SCOPE", "drop A-3's line from `14`", cat_sub("the sign-off rows SO-13 … SO-18)\n", "")),
    ("G-AROW", "move A-5 off its listed anchor", lambda t: replace(t, hand=t.hand.replace("| A-5 | `14`:1438,", "| A-5 | `14`:1439,"))),
)
DECK_MUTATIONS: tuple[tuple[str, str, Mutation], ...] = (
    ("G-STAGE", "the deck missing at the deck stage", missing(DECK_REL)),
    ("G-DECK", "blank a deck row's owner", deck_set("detectors.tape.header", owner="")),
    ("G-DECK", "settle the key naming in the header", sub("deck", '"key_naming": "PROPOSED"', '"key_naming": "merged"')),
    ("G-PROV", "abbreviate the word", deck_set("detectors.regime.chip.calm", text="Calm (Est.) · medium", quote="Calm (estimated) · medium")),
    ("G-DECK", "give a PROPOSED row an owner no lane holds", deck_set("detectors.tape.header", owner="nobody")),
    ("G-PROV", "flip an (estimated) chip's provenance to none", deck_set("detectors.regime.chip.calm", provenance="none")),
    ("G-FROZEN", "skip a frozen id", deck_set("detectors.settings.applied", frozen="FZ-16")),
    ("G-HYGIENE", "put a deny word into the tool's own text", deny_in_tool),
    ("G-SCOPE", "touch `14` in the diff", touch_14),
)
# fmt: on


def header(t: Texts) -> list[str]:
    out = [f"stage: {stage(t)} ({len(gates_of(t))} gates)"]
    if not t.full:
        out.append(f"stage: not run here, the full stage runs them: {', '.join(not_run(t))}")
        out.append(f"stage: parts of the gates that run, left out here: {'; '.join(DECK_LEAVES)}")
    return out


def repin_refusal(t: Texts) -> str | None:
    """Why --repin-ruled must not write: the deck stage, or a pack file missing."""
    return "--repin-ruled needs the full stage with every pack file present" if (
        not t.full or t.missing) else None  # fmt: skip


def selftest(stage_name: str) -> tuple[bool, list[str]]:
    first = load(stage_name)
    base = replace(first, changed=list((*OWN_PATHS, CAT_REL) if first.full else DECK_PATHS))
    muts = MUTATIONS if base.full else DECK_MUTATIONS
    before = (base.spec, base.hand, base.deck, base.cat14)
    found = audit(base)
    out = [*(f"self-test: {h}" for h in header(base)), f"self-test: baseline {len(found)} FAIL"]
    out += [f"  baseline {g}: {m}" for g, m in found]
    ok = not found
    for i, (gate, what, fn) in enumerate(muts, 1):
        gates = sorted({g for g, _ in audit(fn(base))})
        good = gates == [gate]
        ok &= good
        out.append(
            f"{'ok  ' if good else 'FAIL'} MU-{i} {gate}: {what} -> {', '.join(gates) or 'none'}"
        )
    if not base.full:
        probe = repin_refusal(base) is not None
        ok &= probe
        out.append(f"{'ok  ' if probe else 'FAIL'} P-1 --repin-ruled refuses at the deck stage")
    seen = {g for g, _, _ in muts}
    uncovered = [g for g in gates_of(base) if g not in seen]
    ok &= not uncovered
    if uncovered:
        out.append(f"FAIL no mutation for {', '.join(uncovered)}")
    after = load(stage_name)
    restored = (after.spec, after.hand, after.deck, after.cat14) == before
    ok &= restored
    out.append(f"self-test: {len(muts)} mutations, texts restored: {'yes' if restored else 'NO'}")
    out.append(f"self-test: {'PASS' if ok else 'FAIL'}")
    return ok, out


def main(argv: list[str]) -> int:
    ap = argparse.ArgumentParser(description="E25-D07 hand-off pack audit")
    g = ap.add_mutually_exclusive_group()
    g.add_argument("--check", action="store_true")
    g.add_argument("--self-test", action="store_true")
    g.add_argument("--repin-ruled", action="store_true")
    ap.add_argument("--json", action="store_true")
    ap.add_argument("--stage", choices=STAGES, required=True)
    a = ap.parse_args(argv)
    if a.self_test:
        ok, out = selftest(a.stage)
        print("\n".join(out))
        return 0 if ok else 1
    t = load(a.stage)
    if a.repin_ruled:
        why = repin_refusal(t)
        if why:
            print(f"refused: {why}")
            return 1
        hashes, bad = cite_hashes(t)
        if bad:
            print(f"refused: {bad[0]}")
            return 1
        head = (
            "# E25-D07 cite pins: the cite, a hash of its cited line(s) at its ref."
            " Written by --repin-ruled only.\n"
        )
        body = "".join(f"{k}\t{h}\n" for k, h in hashes.items())
        (ROOT / PINS_REL).write_text(head + body, encoding="utf-8")
        print(f"wrote {PINS_REL} ({len(hashes)} cites)")
        return 0
    found = audit(t)
    if a.json:
        doc = {
            "stage": stage(t),
            "not_run": not_run(t),
            "base": BASE,
            "d06": D06_REF,
            "values": {} if t.missing else compute(t),
            "findings": [{"gate": g, "msg": m} for g, m in found],
        }
        print(json.dumps(doc, ensure_ascii=False, indent=2))
    else:
        print("\n".join(header(t)))
        for gate, msg in found:
            print(f"FAIL {gate}: {msg}")
        n = len(cite_hashes(t)[0]) if t.full and not t.missing else 0
        rows = len(parse_deck(t.deck).rows)
        print(f"{len(found)} FAIL ({len(gates_of(t))} gates; {n} cites; {rows} deck rows)")
    return 1 if found else 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
