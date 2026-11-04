#!/usr/bin/env python3
"""E34-D05 (#1043) audit: the hand-off package for SCR-061 and SCR-062.

Standalone, offline, stdlib only; it runs no repo code and is run with `python3 -I`. It reads the
copy deck, the pack, the hand-off file and the pins file from the working tree, every cited plan
or design file AS TEXT with `git show` at the pinned base (`BASE`), and the three unmerged parents
with `git show` at their pinned heads (`PINS`, `BOARDS`). Default-deny: a gate that cannot read
its input FAILs.

Two stages, named by `--stage` (required; never guessed from the working tree). The deck stage
reads the deck and this tool only, so the deck lands first (PR 1a); the full stage adds the pack,
the hand-off file and the pins (PR 1b) and runs every gate; any of them missing FAILs G-SCOPE.

Gates (each FAIL led by its name):
  G-DECK      the header line first; one row per string with exactly the fields; a unique id of
              the `e34.` form and a unique text; a known screen, kind, status and consumer; every
              row frozen; only known slots; a merged row's text on its cited line at the base; a
              RULED or PROPOSED row's text inside its parent's cited section at the pin; RULED
              only on the six recovery triggers, and all six RULED.
  G-COVER     by text, never by row position: every string of D02 §11, D03 §7, D03 §3.5's
              trigger and confirm labels and D03 §5.3's words is a deck text, except a string a
              ruling supersedes (`SUPERSEDED`), which the full stage needs named in its C-row.
  G-SAFE      no deck text carries a word of the header's `never` list or offers to remove,
              loosen, skip or turn off a stop; the native-stop notice is in the deck.
  G-COPY      (full) every deck id the pack or the hand-off names is in the deck; §9's counts
              and its anchor equal the deck.
  G-STATES    (full) §4.1 lists exactly D02's S061 ids plus the cover, §4.2 exactly D03's M62
              ids; SD rows in order; each frame in its parent's register; each Gap cell "—" or a
              DG row, its "Until served" cell filled exactly when a gap is named; a row with a
              lockout, frozen, view-as or read-only T2 id names T2's key, D02 §5, G-T2.4 and
              G-T2.6, and that protective actions are never T2 under lockout.
  G-DATA      (full) every status value §4 names is in its `22` enum at the base; every
              backticked field or operation in §4 is in `22`, or is an `rbac.` T2 key of
              E09-D09 at the base; no ticket-only name is served.
  G-GAP       (full) DG rows in order; each parent's gap ids (D02 §9, D03 §11.1) appear
              exactly once in its crosswalk column; each row has exactly one known owner; every
              DG id the pack names exists.
  G-MAP       (full) MP rows in order; the ticket's eighteen ids once each in MP-01 … MP-18;
              every id of `14`'s two Components lines in the table; a CMP cell is a prefix of
              its `15` heading, or the row is `new`; a new or new-variant row names its
              design-system ticket, any other row names none.
  G-RECOVERY  (full) RC-1 … RC-6 with their deck ids, RC-1 armed on LIVE, RC-2 … RC-5 never;
              each trigger's text equals D03 §3.5's label for its RC.
  G-RULES     (full) §1 holds rules 1 … 7; rule 6 names the four guards and says each is
              re-enforced server-side; rule 2 names `native_sl_confirmed`.
  G-BUDGET    (full) every figure of §10 stands on its cited `14` line.
  G-EVENT     (full) EV rows in order, each `ui_fanout_*` or `ui_group_action_*`, both families
              present; no event field names an account label, a quantity or a price.
  G-HANDOFF   (full) one block per contract, in order, each with `16` §11.4's thirteen labels in
              order; each line checked, N/A or PENDING with a reason; the four a11y lines never
              N/A.
  G-REQUEST   (full) no line cite into a parent; the R rows' SHAs are the pins; every "D0n §x"
              resolves at its pin; each §0 board id and export stands on one line of its parent
              at the boards head.
  G-CITE      (full) every cite in range, on a non-blank line, and equal to the pins file.
  G-HYGIENE   no closing keyword, local path, URL, agent name, double-brace slot or public-text
              deny word in the deck, the pack, the hand-off, the pins or this tool.
  G-SCOPE     the stage's files are present, and the diff against `git merge-base HEAD
              origin/main` touches only this ticket's files for that stage.

Usage (from the repo root):
  python3 -I docs/design/_tools/e34_d05_handoff_audit.py --stage deck --check
  python3 -I docs/design/_tools/e34_d05_handoff_audit.py --stage full --check
  python3 -I docs/design/_tools/e34_d05_handoff_audit.py --stage full --json
  python3 -I docs/design/_tools/e34_d05_handoff_audit.py --stage full --self-test
  python3 -I docs/design/_tools/e34_d05_handoff_audit.py --stage full --write-pins
"""

from __future__ import annotations

import argparse
import functools
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
PACK_REL = "docs/design/E34/E34-D05.md"
HAND_REL = "docs/design/E34/E34-D05-handoff.md"
DECK_REL = "docs/design/E34/E34-D05-copy-deck.jsonl"
TOOL_REL = "docs/design/_tools/e34_d05_handoff_audit.py"
PINS_REL = "docs/design/_tools/e34_d05_ruled_pins.txt"
DECK, FULL = "deck", "full"
DECK_PATHS = (DECK_REL, TOOL_REL)
OWN_PATHS = (PACK_REL, HAND_REL, PINS_REL, *DECK_PATHS)
BASE = "df125c269be0b014e9e0655b571468e1fb641d6c"  # origin/main when written
PINS = {
    "D02": "b80537a63b6d6e098cf7bccd59d4e27cae72cf55",  # #5621, if it merges as is
    "D03": "1108cc3d8c0a39a7f4e4857c153aed368843ba1d",  # #5622, if it merges as is
    "D04": "830d750b26e3d4996159013d1f979abac0ca3c9c",  # #5651, if it merges as is
}
BOARDS = {
    "D02": "b9bf0a142b8ac655d38875a56e53ef5fe71242d7",  # #5728, if it merges as is
    "D03": "ce852b1ceb0daba0a25102a006555ea6f6714aa5",  # #5729, if it merges as is
}
PARENT = {
    "D02": "docs/design/E34/E34-D02.md",
    "D03": "docs/design/E34/E34-D03.md",
    "D04": "docs/design/E34/E34-D04.md",
}
PATHS = {
    "02": "docs/plan/02-definition-of-ready-done.md",
    "05": "docs/plan/05-accessibility-standard.md",
    "11": "docs/plan/11-user-stories.md",
    "14": "docs/plan/14-screens-catalogue.md",
    "15": "docs/plan/15-component-catalogue.md",
    "16": "docs/plan/16-design-system-brief.md",
    "22": "docs/plan/22-api-openapi.yaml",
    "23": "docs/plan/23-ws-protocol.md",
    "24": "docs/plan/24-internal-schemas.md",
    "E09D09": "docs/design/E09/E09-D09.md",
    "E28D02": "docs/design/E28/E28-D02.md",
    "E28D03": "docs/design/E28/E28-D03.md",
    "E29D01": "docs/design/E29/E29-D01.md",
    "E30D02": "docs/design/E30/E30-D02.md",
    "E30D03": "docs/design/E30/E30-D03.md",
}
STATUSES = ["merged", "RULED", "PROPOSED"]
FIELDS = ["id", "screen", "kind", "text", "status", "owner", "source", "consumer", "frozen"]
KINDS = ["label", "word", "message", "error", "empty", "confirm", "reason", "name", "announce"]
SCREENS = ("SCR-061", "SCR-062", "both")
CONSUMER = {"SCR-061": "E34-S04", "SCR-062": "E34-S05", "both": "E34-S04, E34-S05"}
SLOTS = {
    "id", "id4", "n", "m", "account", "accounts", "reason", "qty", "group_qty", "min", "symbol",
    "side", "price", "legs", "value", "time", "hh:mm", "m:ss", "remaining", "word", "diff",
    "target", "filled", "ready", "total", "coin", "fee", "intent", "age", "user",
}  # fmt: skip
RULED_IDS = tuple(f"e34.shared.rc{n}.trigger" for n in range(1, 7))
ID_RX = re.compile(r"^e34\.(?:s061|s062|shared|cell|t2)(?:\.[a-z0-9_]+)+$")
OWNER_RX = re.compile(r"^E\d\d-[DSTQX]\d\d$")
DECK_ID = re.compile(r"`(e34\.[a-z0-9_.]*[a-z0-9_])`")
SLOT = re.compile(r"\{([^{}]+)\}")
CITE = re.compile(r"`(\d\d|E\d\dD\d\d)`:(\d+(?:–\d+)?)")
PARENT_SEC = re.compile(r"\bD0([234]) §(\d+(?:\.\d+)*)")
TICKET_CMPS = ("CMP-041", "CMP-049", "CMP-055", "CMP-075", "CMP-100", "CMP-101", "CMP-102",
               "CMP-105", "CMP-106", "CMP-107", "CMP-119", "CMP-121", "CMP-123", "CMP-124",
               "CMP-158", "CMP-229", "CMP-231", "CMP-232")  # fmt: skip
VERDICTS = ("reused", "new variant", "new", "composed", "not drawn")
REGION_CMPS = ("CMP-001", "CMP-019", "CMP-040", "CMP-043", "CMP-044", "CMP-079", "CMP-093")
GAP_OWNERS = ("E34-S03", "E34-T01", "E34-T02")
HANDOFF_BLOCKS = ("CMP-044 ConfirmDialog", "CMP-123 FlattenAllButton",
                  "CMP-124 TradeGroupSummaryCard", "CMP-229 ArmToggle", "CMP-232 LimitsChip",
                  "LegStatusCell (its CMP id at E34-D03's PR 2)")  # fmt: skip
A11Y_LINES = ("Keyboard table", "Accessible name / role table", "Motion pair",
              "Essential-exceptions log")  # fmt: skip
GUARDS = ("arm state", "SL presence", "override limits", "account scope")
SUPERSEDED = {"Send group {id} to {n} accounts: {intent}": "C-2"}  # D02 §11 vs D04 SR-04
T2_IDS = re.compile(r"`e34\.t2\.(?:lockout|frozen|view_as|account_read_only)`")
T2_NEEDS = ("T2 `", "D02 §5", "G-T2.4", "G-T2.6", "never T2 under lockout")
TICKET_ONLY = ("skipped_reason", "unwind_incomplete", "deferral_deadline", "divergence")
EVENT_RX = re.compile(r"^ui_(?:fanout|group_action)_[a-z_]+$")
EVENT_BANNED = ("account", "label", "qty", "quantity", "price")
STOP_OFF = re.compile(
    r"(?i)\b(?:remove|loosen|skip|disable|turn off|without)\s+(?:the\s+|its\s+|a\s+)?"
    r"(?:native\s+)?stop"
)
CLOSING = re.compile(r"\b(?:close[sd]?|fix(?:e[sd])?|resolve[sd]?)\s+#\d+", re.IGNORECASE)
LOCAL_PATH = re.compile(
    "|".join(re.escape(p) for p in ("/ho" + "me/", "/t" + "mp/", "/m" + "nt/"))
    + r"|\bno"
    + r"tes/|[A-Z]:\\\\"
)
URL_OR_HOST = re.compile(
    r"https?://|penpot\.[a-z]|" + "team" + "-id=|" + "file" + "-id=", re.IGNORECASE
)
AGENT_NAME = re.compile(r"\b[a-z]{2,4}-worker-\d\b")
DENY = tuple(
    a + b
    for a, b in (("le", "ak"), ("expo", "sed"), ("by", "pass"), ("expl", "oit"), ("att", "ack"),
                 ("ora", "cle"), ("rev", "eal"), ("unbou", "nded"), ("flo", "od"), ("st", "all"),
                 ("d", "os"), ("advi", "sory"), ("gh", "sa"), ("pre-", "auth"))
)  # fmt: skip  # the public-text deny list, assembled so this file never spells it


@dataclass(frozen=True)
class Texts:
    """Everything a gate reads from the working tree; the self-test mutates these only."""

    deck: str | None
    pack: str | None
    hand: str | None
    pins: str | None
    tool: str | None
    stage: str


@functools.cache
def show(rev: str, rel: str) -> str | None:
    try:
        out = subprocess.run(["git", "show", f"{rev}:{rel}"], cwd=ROOT, capture_output=True,
                             text=True, check=False, timeout=60)  # fmt: skip
    except (OSError, subprocess.SubprocessError):
        return None
    return out.stdout if out.returncode == 0 else None


def base_lines(key: str) -> list[str]:
    text = show(BASE, PATHS[key])
    return text.splitlines() if text is not None else []


def parent_text(key: str, boards: bool = False) -> str:
    rev = BOARDS[key] if boards else PINS[key]
    return show(rev, PARENT[key]) or ""


def slot_rx(text: str) -> re.Pattern[str]:
    return re.compile(".+?".join(re.escape(p) for p in SLOT.split(text)[::2]))


def section(doc: str, num: str) -> str:
    """The body under the heading `## num.` / `### num` until the next heading as deep or less."""
    lines = doc.splitlines()
    start, depth, fenced = -1, 0, False
    for i, ln in enumerate(lines):
        if ln.startswith("```"):
            fenced = not fenced
        if fenced:
            continue
        m = re.match(r"^(#{1,4}) (\d+(?:\.\d+)*)\.? ", ln)
        if m and start < 0 and m.group(2) == num:
            start, depth = i, len(m.group(1))
        elif start >= 0 and ln.startswith("#") and len(ln) - len(ln.lstrip("#")) <= depth:
            return "\n".join(lines[start:i])
    return "\n".join(lines[start:]) if start >= 0 else ""


def cells(ln: str) -> list[str]:
    return [c.strip() for c in ln.strip().strip("|").split("|")]


def rows(text: str, lead: str) -> list[list[str]]:
    return [cells(ln) for ln in text.splitlines() if re.match(rf"^\| {lead}\b", ln)]


def quoted(cell: str) -> list[str]:
    return re.findall(r'"([^"]+)"', cell)


def deck_rows(t: Texts) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    if not t.deck:
        return {}, []
    lines = [ln for ln in t.deck.splitlines() if ln.strip()]
    head = json.loads(lines[0])
    return head, [json.loads(ln) for ln in lines[1:]]


def g_deck(t: Texts) -> list[str]:
    try:
        head, body = deck_rows(t)
    except (json.JSONDecodeError, IndexError) as exc:
        return [f"the deck does not parse: {exc}"]
    if not body:
        return ["the deck is missing or empty"]
    out: list[str] = []
    want = {"pack": "E34-D05", "base": BASE[:10], "statuses": STATUSES, "fields": FIELDS,
            "kinds": KINDS, "inputs": {k: v[:10] for k, v in PINS.items()}}  # fmt: skip
    out += [f"header {k!r} is not {v!r}" for k, v in want.items() if head.get(k) != v]
    if not head.get("frozen") or not head.get("never"):
        out.append("header lacks the frozen statement or the never list")
    ids: Counter[str] = Counter(r.get("id", "") for r in body)
    texts: Counter[str] = Counter(r.get("text", "") for r in body)
    out += [f"id {i} appears {n} times" for i, n in ids.items() if n > 1]
    out += [f"text {x!r} appears {n} times" for x, n in texts.items() if n > 1]
    for r in body:
        rid = r.get("id", "?")
        if list(r) != FIELDS:
            out.append(f"{rid}: fields {list(r)}")
            continue
        if not ID_RX.match(rid):
            out.append(f"{rid}: not an e34 id")
        if r["screen"] not in SCREENS or r["consumer"] != CONSUMER.get(r["screen"]):
            out.append(f"{rid}: screen {r['screen']!r} or consumer {r['consumer']!r}")
        if r["kind"] not in KINDS or r["status"] not in STATUSES or r["frozen"] is not True:
            out.append(f"{rid}: kind, status or frozen")
        if not OWNER_RX.match(r["owner"]):
            out.append(f"{rid}: owner {r['owner']!r}")
        out += [f"{rid}: unknown slot {s!r}" for s in SLOT.findall(r["text"]) if s not in SLOTS]
        if (r["status"] == "RULED") != (rid in RULED_IDS):
            out.append(f"{rid}: RULED is the six recovery triggers only")
        out += source_fails(r)
    return out


def source_fails(r: dict[str, Any]) -> list[str]:
    rid, src, rx = r["id"], r["source"], slot_rx(r["text"])
    merged = re.fullmatch(r"([0-9A-Z]+):(\d+)", src)
    if r["status"] == "merged":
        if not merged or merged.group(1) not in PATHS:
            return [f"{rid}: a merged row cites a merged line, not {src!r}"]
        lines = base_lines(merged.group(1))
        n = int(merged.group(2))
        if not 0 < n <= len(lines) or not rx.search(lines[n - 1]):
            return [f"{rid}: its text is not on {src} at the base"]
        return []
    par = re.fullmatch(r"(D0[234]) §(\d+(?:\.\d+)*)", src)
    if not par:
        return [f"{rid}: a {r['status']} row cites its parent's section, not {src!r}"]
    body = section(parent_text(par.group(1)), par.group(2))
    if not body:
        return [f"{rid}: {src} is not a section at its pin"]
    return [] if rx.search(body) else [f"{rid}: its text is not in {src} at its pin"]


def parent_strings() -> dict[str, list[str]]:
    d02, d03 = parent_text("D02"), parent_text("D03")
    found: dict[str, list[str]] = {
        "D02 §11": [q for row in rows(section(d02, "11"), "`") for q in quoted(row[1])[:1]],
        "D03 §7": [q for row in rows(section(d03, "7"), "`") for q in quoted(row[1])[:1]],
        "D03 §3.5": [],
        "D03 §5.3": [],
    }
    for row in rows(section(d03, "3.5"), r"RC-\d"):
        found["D03 §3.5"] += quoted(row[2])[:1] + [q for q in quoted(row[3])[:1] if "{" in q]
    for row in rows(section(d03, "5.3"), r"(?:LS|GS)-\d\d"):
        found["D03 §5.3"] += [q for q in quoted(row[3]) if q != "—"]
    return found


def g_cover(t: Texts) -> list[str]:
    _, body = deck_rows(t)
    texts = {r.get("text") for r in body}
    out: list[str] = []
    for where, strings in parent_strings().items():
        if not strings:
            out.append(f"{where}: no strings read at its pin")
        out += [f"{where}: {s!r} is not a deck text" for s in strings
                if s not in texts and s not in SUPERSEDED]  # fmt: skip
    for s, row in SUPERSEDED.items():
        c_row = [r for r in rows(t.pack or "", row) if s in "|".join(r)]
        if t.stage == FULL and not c_row:
            out.append(f"{s!r} is superseded but {row} does not name it")
    return out


def g_safe(t: Texts) -> list[str]:
    head, body = deck_rows(t)
    out: list[str] = []
    for r in body:
        text = r.get("text", "")
        out += [f"{r.get('id')}: carries {w!r}" for w in head.get("never", []) if w in text]
        if STOP_OFF.search(text):
            out.append(f"{r.get('id')}: offers to take a stop away")
    if not any(r.get("id") == "e34.s061.notice.stop" for r in body):
        out.append("the native-stop notice is not in the deck")
    return out


def g_copy(t: Texts) -> list[str]:
    _, body = deck_rows(t)
    ids = {r["id"] for r in body}
    named = set(DECK_ID.findall((t.pack or "") + (t.hand or "")))
    out = [f"{i} is named but not in the deck" for i in sorted(named - ids)]
    c = Counter(r["status"] for r in body)
    want = f"{len(body)}/{c['merged']}/{c['RULED']}/{c['PROPOSED']}"
    prose = (f"{len(body)} rows, {c['merged']} merged, {c['RULED']} RULED, "
             f"{c['PROPOSED']} PROPOSED")  # fmt: skip
    pack = t.pack or ""
    if f"<!-- audit:deck={want} -->" not in pack or prose not in pack:
        out.append(f"§9's counts are not {want} ({prose})")
    return out


def sd_rows(t: Texts, sub: str) -> list[list[str]]:
    return rows(section(t.pack or "", sub), r"SD-\d\d")


def dg_ids(t: Texts) -> list[str]:
    return [r[0] for r in rows(section(t.pack or "", "2"), r"DG-\d\d")]


def register(key: str) -> set[str]:
    return set(re.findall(r"^\| (B\d\d) +\|", parent_text(key), re.MULTILINE))


def g_states(t: Texts) -> list[str]:
    out: list[str] = []
    dgs = set(dg_ids(t))
    n = 0
    for sub, key, rx in (("4.1", "D02", r"S061-\d\d"), ("4.2", "D03", r"M62-\d\d")):
        table = sd_rows(t, sub)
        want = set(re.findall(rf"^\| ({rx}) +\|", parent_text(key), re.MULTILINE))
        have = [m for r in table for m in re.findall(rx, r[1])]
        if not want or set(have) != want or len(have) != len(set(have)):
            out.append(f"§{sub}: the {key} state ids differ: {sorted(want ^ set(have))}")
        if key == "D02" and sum("(the cover)" in r[1] and r[2] == "B01" for r in table) != 1:
            out.append("§4.1 lacks the partial failure (the cover) on B01")
        frames = register(key)
        for r in table:
            n += 1
            if r[0] != f"SD-{n:02d}":
                out.append(f"§{sub}: {r[0]} out of order")
            out += [f"{r[0]}: frame {b} is not in {key}'s register"
                    for b in re.findall(r"B\d\d", r[2]) if b not in frames]  # fmt: skip
            if r[4] != "—" and r[4] not in dgs:
                out.append(f"{r[0]}: gap {r[4]} is not a DG row")
            if (r[4] == "—") != (r[5] == "—"):
                out.append(f"{r[0]}: 'Until served' must be filled exactly when a gap is named")
            if not DECK_ID.search(r[6]) and "as SD-" not in r[6]:
                out.append(f"{r[0]}: names no deck id")
            if T2_IDS.search(r[6]):
                out += [f"{r[0]}: a T2 row lacks {w!r}" for w in T2_NEEDS if w not in r[3]]
    return out


def enum_of(name: str) -> set[str]:
    text = show(BASE, PATHS["22"]) or ""
    head = "^    " + re.escape(name) + r":\n(?:.*\n){0,4}?.*?enum:\s*\n?\s*\[([^\]]+)\]"
    m = re.search(head, text, re.MULTILINE)
    return {v.strip() for v in m.group(1).split(",")} if m else set()


def preview_enum(field: str) -> set[str]:
    text = show(BASE, PATHS["22"]) or ""
    at = text.find("    TradeGroupPreview:")
    if field == "status":
        m = re.search(r"enum: \[(ready[^\]]+)\]", text[at:])
        return {v.strip() for v in m.group(1).split(",")} if m else set()
    m = re.search(r"enum:\s*\[([^\]]*cap_breached[^\]]*)\]", text[at:])
    return {v.strip() for v in m.group(1).split(",") if v.strip()} if m else set()


def g_data(t: Texts) -> list[str]:
    text = show(BASE, PATHS["22"]) or ""
    if not text:
        return ["`22` is not readable at the base"]
    sets = {"group": enum_of("TradeGroupStatus"), "leg": enum_of("LegStatus"),
            "preview leg": preview_enum("status")}  # fmt: skip
    codes = preview_enum("code")
    out = [f"no enum read for {k}" for k, v in sets.items() if not v]
    body = section(t.pack or "", "4")
    for who, val in re.findall(r"(preview leg|group|leg) `status` = `([a-z_]+)`", body):
        if val not in sets[who]:
            out.append(f"§4: {who} `status` = `{val}` is not in its enum")
    for val in re.findall(r"`rejection\.code` = `([a-z_]+)`", body):
        if val not in codes:
            out.append(f"§4: `rejection.code` = `{val}` is not a served code")
    e09 = show(BASE, PATHS["E09D09"]) or ""
    for tok in set(re.findall(r"`([a-z][a-zA-Z_.]*)`", body)):
        if tok.startswith("e34.") or tok in TICKET_ONLY:
            continue
        if tok.startswith("rbac.") and f"`{tok}`" in e09:
            continue  # a T2 reason key, owned by E09-D09 §3.1, not a `22` name
        leaf = tok.split(".")[-1]
        if re.search(rf"operationId: {re.escape(tok)}\b", text) or re.search(
            rf"\b{re.escape(leaf)}\b", text
        ):
            continue
        out.append(f"§4: `{tok}` is not in `22` at the base")
    out += [f"§4 serves the ticket-only name `{n}`" for n in TICKET_ONLY if f"`{n}`" in body]
    return out


def parent_gaps(key: str, sec: str) -> set[str]:
    return set(re.findall(r"^\| (G-\d+) +\|", section(parent_text(key), sec), re.MULTILINE))


def g_gap(t: Texts) -> list[str]:
    table = rows(section(t.pack or "", "2"), r"DG-\d\d")
    out = [f"{r[0]} out of order" for i, r in enumerate(table, 1) if r[0] != f"DG-{i:02d}"]
    if not table:
        return ["§2 has no DG rows"]
    for col, (key, sec) in enumerate((("D02", "9"), ("D03", "11.1")), 2):
        seen = Counter(g for r in table for g in re.findall(r"G-\d+", r[col]))
        want = parent_gaps(key, sec)
        if not want:
            out.append(f"{key} §{sec}: no gap rows read at its pin")
        out += [f"{key} {g}: in the crosswalk {seen[g]} times" for g in want if seen[g] != 1]
        out += [f"{key} {g}: not a gap of its parent" for g in seen if g not in want]
    for r in table:
        if sum(o in r[4] for o in GAP_OWNERS) != 1:
            out.append(f"{r[0]}: owner {r[4]!r} is not exactly one known ticket")
    named = set(re.findall(r"DG-\d\d", (t.pack or "") + (t.hand or "")))
    out += [f"{d} is named but not a DG row" for d in sorted(named - {r[0] for r in table})]
    return out


def headings_15() -> dict[str, str]:
    return {m.group(1): m.group(0)[4:] for m in
            re.finditer(r"^### (CMP-\d{3})\b.*$", show(BASE, PATHS["15"]) or "", re.MULTILINE)}  # fmt: skip


def g_map(t: Texts) -> list[str]:
    table = rows(section(t.pack or "", "3"), r"MP-\d\d")
    heads = headings_15()
    out = [f"{r[0]} out of order" for i, r in enumerate(table, 1) if r[0] != f"MP-{i:02d}"]
    first = [re.match(r"CMP-\d{3}", r[1]) for r in table[:18]]
    if sorted(m.group(0) for m in first if m) != sorted(TICKET_CMPS):
        out.append("MP-01 … MP-18 are not the ticket's eighteen ids")
    named = {m.group(0) for r in table for m in [re.match(r"CMP-\d{3}", r[1])] if m}
    out += [f"{c} of `14`'s Components lines is not mapped" for c in REGION_CMPS if c not in named]
    for r in table:
        m = re.match(r"CMP-\d{3}", r[1])
        if r[3] not in VERDICTS:
            out.append(f"{r[0]}: verdict {r[3]!r}")
        if m and m.group(0) in heads and not heads[m.group(0)].startswith(r[1]):
            out.append(f"{r[0]}: {r[1]!r} is not its `15` heading")
        if (not m or m.group(0) not in heads) and r[3] != "new":
            out.append(f"{r[0]}: not in `15` at the base, so it must be new")
        if (r[3] in ("new", "new variant")) != bool(re.match(r"E\d\d-D\d\d", r[4])):
            out.append(f"{r[0]}: the DS ticket cell does not fit verdict {r[3]!r}")
    return out


def g_recovery(t: Texts) -> list[str]:
    table = rows(section(t.pack or "", "5"), r"RC-\d")
    _, body = deck_rows(t)
    text_of = {r["id"]: r["text"] for r in body}
    d03 = {r[0]: quoted(r[2])[:1] for r in rows(section(parent_text("D03"), "3.5"), r"RC-\d")}
    arm = {1: "on LIVE", 2: "never", 3: "never", 4: "never", 5: "never", 6: "n/a"}
    out = [] if len(table) == 6 else [f"§5 has {len(table)} RC rows, not 6"]
    for i, r in enumerate(table, 1):
        trig = f"e34.shared.rc{i}.trigger"
        if r[0] != f"RC-{i}" or r[1] != f"`{trig}`" or r[4] != arm[i]:
            out.append(f"RC-{i}: id, trigger or arm cell")
        if i < 6 and r[2] != f"`e34.shared.rc{i}.confirm`":
            out.append(f"RC-{i}: confirm cell {r[2]!r}")
        if d03.get(f"RC-{i}") != [text_of.get(trig)]:
            out.append(f"RC-{i}: the trigger is not D03 §3.5's label")
    return out


def g_rules(t: Texts) -> list[str]:
    body = section(t.pack or "", "1")
    nums = re.findall(r"^(\d)\. \*\*", body, re.MULTILINE)
    out = [] if nums == [str(i) for i in range(1, 8)] else [f"§1's rules are {nums}"]
    six = re.search(r"^6\. (.*)$", body, re.MULTILINE)
    two = re.search(r"^2\. (.*)$", body, re.MULTILINE)
    if not six or "re-enforced server-side" not in six.group(1):
        out.append("rule 6 does not say re-enforced server-side")
    out += [f"rule 6 lacks the {g}" for g in GUARDS if not six or g not in six.group(1)]
    if not two or "`native_sl_confirmed`" not in two.group(1):
        out.append("rule 2 does not name `native_sl_confirmed`")
    return out


def g_budget(t: Texts) -> list[str]:
    table = rows(section(t.pack or "", "10"), r"(?!Budget\b)[a-zA-Z]\w*")
    out = [] if table else ["§10 has no budget rows"]
    lines = base_lines("14")
    for r in table:
        m = re.search(r"`14`:(\d+)", r[1])
        if not m or not lines:
            out.append(f"§10 {r[0]!r}: no `14` cite")
            continue
        line = lines[int(m.group(1)) - 1].replace(" ", "")
        for fig in re.findall(r"\d+(?:\.\d+)?\s?(?:ms|s|Hz)\b", r[0]):
            if fig.replace(" ", "") not in line:
                out.append(f"§10: {fig!r} is not on `14`:{m.group(1)}")
    return out


def g_event(t: Texts) -> list[str]:
    table = rows(section(t.pack or "", "11"), r"EV-\d\d")
    out = [f"{r[0]} out of order" for i, r in enumerate(table, 1) if r[0] != f"EV-{i:02d}"]
    names = [r[1].strip("`") for r in table]
    out += [f"{n}: not a ui_fanout_* or ui_group_action_* name" for n in names
            if not EVENT_RX.match(n)]  # fmt: skip
    for fam in ("ui_fanout_", "ui_group_action_"):
        if not any(n.startswith(fam) for n in names):
            out.append(f"no {fam}* event")
    for r in table:
        for f in re.findall(r"`([a-z_]+)`", r[3]):
            if any(b in f.split("_") for b in EVENT_BANNED):
                out.append(f"{r[0]}: field `{f}` names an account label, a quantity or a price")
    return out


def template_labels() -> list[str]:
    body = section(show(BASE, PATHS["16"]) or "", "11.4")
    return re.findall(r"^- \[ \] \*\*([^*]+)\*\*", body, re.MULTILINE)


def g_handoff(t: Texts) -> list[str]:
    labels = template_labels()
    if len(labels) != 13:
        return [f"`16` §11.4 gave {len(labels)} labels, not 13"]
    parts = re.split(r"^## Handoff checklist — ", t.hand or "", flags=re.MULTILINE)[1:]
    names = [p.split(" (E34-D05, #1043)")[0] for p in parts]
    out = [] if names == list(HANDOFF_BLOCKS) else [f"blocks {names}"]
    for name, part in zip(names, parts, strict=False):
        items = re.findall(r"^- \[([ x])\] \*\*([^*]+)\*\*(.*)$", part, re.MULTILINE)
        if [i[1] for i in items] != labels:
            out.append(f"{name}: the labels differ from `16` §11.4's")
        for box, label, rest in items:
            na = rest.startswith(" — N/A — ")
            if box == " " and not (na or rest.startswith(" — PENDING — ")) and "**" not in rest:
                out.append(f"{name} / {label}: open with no N/A or PENDING reason")
            if na and label in A11Y_LINES:
                out.append(f"{name} / {label}: an a11y line is never N/A")
    return out


def g_request(t: Texts) -> list[str]:
    pack, out = t.pack or "", []
    if re.search(r"`D0[234]`:\d", pack):
        out.append("a line cite into a parent; cite parents by section id")
    for key, sha in (*PINS.items(), *BOARDS.items()):
        if f"`{sha}`" not in pack:
            out.append(f"{key}: the pin {sha[:10]} is not in the R rows")
    for key, num in sorted(set(PARENT_SEC.findall(pack + (t.hand or "")))):
        if not section(parent_text(f"D0{key}"), num):
            out.append(f"D0{key} §{num} is not a section at its pin")
    for r in rows(section(pack, "0"), r"D[23]-0\d"):
        doc = parent_text(f"D0{r[0][1]}", boards=True)
        bid, png = r[2].strip("`"), r[3].split("`")[1] if "`" in r[3] else ""
        if not any(bid in ln and png in ln for ln in doc.splitlines()):
            out.append(f"{r[0]}: {bid} and {png} are not on one line of its parent")
    return out


def cites(text: str) -> list[tuple[str, int]]:
    out: list[tuple[str, int]] = []
    for key, span in CITE.findall(text):
        lo, _, hi = span.partition("–")
        out += [(key, n) for n in range(int(lo), int(hi or lo) + 1)]
    return out


def pin_line(key: str, n: int) -> str | None:
    lines = base_lines(key)
    if not 0 < n <= len(lines) or not lines[n - 1].strip():
        return None
    digest = hashlib.sha256(lines[n - 1].strip().encode()).hexdigest()[:12]
    return f"{key}:{n} {digest}"


def g_cite(t: Texts) -> list[str]:
    want: dict[str, str] = {}
    out: list[str] = []
    for key, n in sorted(set(cites((t.pack or "") + (t.hand or "")))):
        line = pin_line(key, n)
        if line is None:
            out.append(f"`{key}`:{n} is out of range or blank at the base")
        else:
            want[f"{key}:{n}"] = line
    have = {ln.split()[0]: ln for ln in (t.pins or "").splitlines() if ln and ln[0] != "#"}
    out += [f"pins lack or differ at {k}" for k, v in want.items() if have.get(k) != v]
    out += [f"pins hold {k}, which no cite names" for k in have if k not in want]
    return out


def g_hygiene(t: Texts) -> list[str]:
    out: list[str] = []
    for name, text in (("deck", t.deck), ("pack", t.pack), ("hand-off", t.hand),
                       ("pins", t.pins), ("tool", t.tool)):  # fmt: skip
        if not text:
            continue
        low = text.lower()
        for rx, what in ((CLOSING, "a closing keyword"), (LOCAL_PATH, "a local path"),
                         (URL_OR_HOST, "a URL or host"), (AGENT_NAME, "an agent name")):  # fmt: skip
            if rx.search(text):
                out.append(f"{name}: {what}")
        out += [f"{name}: a deny word" for w in DENY if w in low][:1]
        if "{" * 2 in text:
            out.append(f"{name}: a double-brace slot")
    return out


def changed_paths() -> list[str] | None:
    try:
        mb = subprocess.run(
            ["git", "merge-base", "HEAD", "origin/main"],
            cwd=ROOT,
            capture_output=True,
            text=True,
            check=True,
            timeout=60,
        ).stdout.strip()
        diff = subprocess.run(
            ["git", "diff", "--name-only", mb],
            cwd=ROOT,
            capture_output=True,
            text=True,
            check=True,
            timeout=60,
        ).stdout.split()
        new = subprocess.run(
            ["git", "ls-files", "-o", "--exclude-standard", "docs"],
            cwd=ROOT,
            capture_output=True,
            text=True,
            check=True,
            timeout=60,
        ).stdout.split()
    except (OSError, subprocess.SubprocessError):
        return None
    return sorted(set(diff) | set(new))  # fmt: skip


def g_scope(t: Texts) -> list[str]:
    need = {"deck": t.deck, "tool": t.tool}
    if t.stage == FULL:
        need |= {"pack": t.pack, "hand-off": t.hand, "pins": t.pins}
    out = [f"the {k} is missing" for k, v in need.items() if not v]
    if t.stage == DECK and (t.pack or t.hand or t.pins):
        out.append("a pack file is present in the deck stage")
    paths = changed_paths()
    if paths is None:
        return [*out, "the diff against origin/main is not readable"]
    own = DECK_PATHS if t.stage == DECK else OWN_PATHS
    return out + [f"{p} is outside this stage's files" for p in paths if p not in own]


GATES: dict[str, Callable[[Texts], list[str]]] = {
    "G-DECK": g_deck, "G-COVER": g_cover, "G-SAFE": g_safe, "G-COPY": g_copy,
    "G-STATES": g_states, "G-DATA": g_data, "G-GAP": g_gap, "G-MAP": g_map,
    "G-RECOVERY": g_recovery, "G-RULES": g_rules, "G-BUDGET": g_budget, "G-EVENT": g_event,
    "G-HANDOFF": g_handoff, "G-REQUEST": g_request, "G-CITE": g_cite, "G-HYGIENE": g_hygiene,
    "G-SCOPE": g_scope,
}  # fmt: skip
DECK_GATES = ("G-DECK", "G-COVER", "G-SAFE", "G-HYGIENE", "G-SCOPE")


def gates_for(stage: str) -> dict[str, Callable[[Texts], list[str]]]:
    return {k: v for k, v in GATES.items() if stage == FULL or k in DECK_GATES}


def audit(t: Texts) -> list[tuple[str, str]]:
    out: list[tuple[str, str]] = []
    for name, gate in gates_for(t.stage).items():
        try:
            out += [(name, msg) for msg in gate(t)]
        except (KeyError, IndexError, ValueError, AttributeError, TypeError) as exc:
            out.append((name, f"could not run: {type(exc).__name__}: {exc}"))
    return out


def read(rel: str) -> str | None:
    p = ROOT / rel
    return p.read_text(encoding="utf-8") if p.is_file() else None


def load(stage: str) -> Texts:
    return Texts(deck=read(DECK_REL), pack=read(PACK_REL), hand=read(HAND_REL),
                 pins=read(PINS_REL), tool=read(TOOL_REL), stage=stage)  # fmt: skip


def pins_text(t: Texts) -> str:
    keys = sorted(set(cites((t.pack or "") + (t.hand or ""))))
    lines = [pin_line(k, n) for k, n in keys]
    head = (f"# E34-D05 pins: one line per cite of the pack and the hand-off file at {BASE}\n"
            "# KEY:line sha256(stripped line)[:12]; rewritten by --write-pins, checked by G-CITE\n")  # fmt: skip
    return head + "".join(f"{ln}\n" for ln in lines if ln)


def summary(t: Texts) -> dict[str, Any]:
    _, body = deck_rows(t)
    return {"stage": t.stage, "base": BASE, "pins": PINS, "boards": BOARDS,
            "deck_rows": len(body), "statuses": dict(Counter(r["status"] for r in body)),
            "cites": len(set(cites((t.pack or "") + (t.hand or "")))),
            "fails": [f"{g}: {m}" for g, m in audit(t)]}  # fmt: skip


# --- self-test: each mutation must make its gate FAIL; texts are restored after each -------------


def sub(field: str, old: str, new: str) -> Callable[[Texts], Texts]:
    def go(t: Texts) -> Texts:
        text = getattr(t, field) or ""
        if old not in text:
            raise ValueError(f"self-test anchor missing in {field}: {old[:40]!r}")
        return replace(t, **{field: text.replace(old, new, 1)})

    return go


def resub(field: str, pattern: str, repl: str) -> Callable[[Texts], Texts]:
    """Like `sub`, by a pattern, so a re-aligned table column never moves the anchor."""

    def go(t: Texts) -> Texts:
        text, n = re.subn(pattern, repl, getattr(t, field) or "", count=1)
        if not n:
            raise ValueError(f"self-test pattern missing in {field}: {pattern[:40]!r}")
        return replace(t, **{field: text})

    return go


def deck_edit(rid: str, key: str, value: Any) -> Callable[[Texts], Texts]:
    def go(t: Texts) -> Texts:
        lines = (t.deck or "").splitlines()
        for i, ln in enumerate(lines[1:], 1):
            row = json.loads(ln)
            if row["id"] == rid:
                row[key] = value
                lines[i] = json.dumps(row, ensure_ascii=False)
                return replace(t, deck="\n".join(lines) + "\n")
        raise ValueError(f"self-test row missing: {rid}")

    return go


def deck_drop(rid: str) -> Callable[[Texts], Texts]:
    def go(t: Texts) -> Texts:
        keep = [ln for ln in (t.deck or "").splitlines() if f'"id": "{rid}"' not in ln]
        return replace(t, deck="\n".join(keep) + "\n")

    return go


MUTATIONS: list[tuple[str, str, str, Callable[[Texts], Texts]]] = [
    ("both", "G-DECK", "retype a merged string",
     deck_edit("e34.s061.notice.stop", "text", "Every order carries a stop-loss.")),
    ("both", "G-DECK", "mark a parent string merged",
     deck_edit("e34.shared.group.partial", "status", "merged")),
    ("both", "G-DECK", "drop a frozen flag", deck_edit("e34.cell.ls01", "frozen", False)),
    ("both", "G-DECK", "use an unknown slot",
     deck_edit("e34.s061.header.title", "text", "Trade group: {group}")),
    ("both", "G-DECK", "make a confirm label RULED",
     deck_edit("e34.shared.rc2.confirm", "status", "RULED")),
    ("both", "G-DECK", "cite a section the string is not in",
     deck_edit("e34.s062.list.empty", "source", "D03 §2.1")),
    ("both", "G-COVER", "drop a parent's string", deck_drop("e34.s062.close.dust")),
    (FULL, "G-COVER", "drop the superseded string from its C-row",
     sub("pack", "\"Send group {id} to {n} accounts: {intent}\"", "the old key")),
    ("both", "G-SAFE", "use a never word",
     deck_edit("e34.shared.rc4.trigger", "text", "Flatten group")),
    ("both", "G-SAFE", "offer to take a stop away",
     deck_edit("e34.s061.action.new_ticket", "text", "Send without the stop")),
    ("both", "G-HYGIENE", "put a local path into the deck",
     deck_edit("e34.s061.preview.draft", "text", "Draft /ho" + "me/x")),
    (FULL, "G-COPY", "name an id the deck lacks",
     sub("pack", "`e34.s061.preview.updating`", "`e34.s061.preview.updated`")),
    (FULL, "G-COPY", "miscount the deck", sub("pack", "24 merged", "25 merged")),
    (FULL, "G-STATES", "drop a D02 state id", sub("pack", "| S061-39 no account", "| no account")),
    (FULL, "G-STATES", "point at a frame no register has",
     resub("pack", r"(\| S061-01 loading +\| )B14", r"\1B44")),
    (FULL, "G-STATES", "drop the lockout statement from a T2 row",
     resub("pack", r"(\| SD-29 [^\n]*?)never T2 under lockout", r"\1enabled")),
    (FULL, "G-STATES", "name a gap and leave Until served empty",
     resub("pack", r"(\| DG-03 \| )\"sent\" until the leg answers", r"\1—")),
    (FULL, "G-DATA", "serve a group status the enum lacks",
     sub("pack", "group `status` = `submitting`", "group `status` = `sending`")),
    (FULL, "G-DATA", "serve a ticket-only name",
     resub("pack", r"(\| S061-27 unwind incomplete +\| B05 +\| )DG-05", r"\1`unwind_incomplete`")),
    (FULL, "G-GAP", "lose a parent gap from the crosswalk", resub("pack", r"(\| DG-01 \|[^|]+\| )G-1( +\| G-1)", r"\1—\2")),
    (FULL, "G-GAP", "give a gap two owners",
     resub("pack", r"(\| DG-05 \|[^\n]*\| )E34-T01 \(#1000\)", r"\1E34-T01 (#1000), E34-S03")),
    (FULL, "G-GAP", "give a gap an unknown owner",
     resub("pack", r"(\| DG-02 \|[^\n]*\| )E34-T02 \(#859\)", r"\1E99-T09 (#1)")),
    (FULL, "G-MAP", "drop a ticket id from MP-01 … MP-18",
     resub("pack", r"(\| MP-03 \| )CMP-055", r"\1CMP-056")),
    (FULL, "G-MAP", "drop CMP-019 `lock` from the map",
     resub("pack", r"(\| MP-\d\d \| )CMP-019 Icon", r"\1Icon")),
    (FULL, "G-MAP", "a new variant with no DS ticket",
     resub("pack", r"(\| new variant \| )E34-D02 \(#996\)", r"\1—")),
    (FULL, "G-RECOVERY", "arm a protective action",
     resub("pack", r"(\| RC-4 \|[^\n]*\| )never( +\| SCR-062)", r"\1on LIVE\2")),
    (FULL, "G-RECOVERY", "retype a trigger away from D03",
     deck_edit("e34.shared.rc6.trigger", "text", "Keep as is ({n} open)")),
    (FULL, "G-RULES", "drop a guard from rule 6", sub("pack", "the override limits", "the limits")),
    (FULL, "G-BUDGET", "change a budget", resub("pack", r"\| preview ≤ 300 ms", "| preview ≤ 350 ms")),
    (FULL, "G-EVENT", "carry a quantity in an event",
     sub("pack", "`group_id`, `legs`, `atomicity`", "`group_id`, `legs`, `leg_qty`")),
    (FULL, "G-HANDOFF", "drop a template line",
     sub("hand", "- [x] **Essential-exceptions log** — none\n", "")),
    (FULL, "G-HANDOFF", "mark an a11y line N/A",
     sub("hand", "- [x] **Motion pair** — unchanged in `15`; a cut",
         "- [ ] **Motion pair** — N/A — none")),
    (FULL, "G-REQUEST", "cite a parent by line", sub("pack", "(D02 §4.2; D03 §3.5)", "(`D02`:240)")),
    (FULL, "G-REQUEST", "move a pin", sub("pack", "`b80537a63b6d6e098cf7bccd59d4e27cae72cf55`",
                                          "`b80537a63b6d6e098cf7bccd59d4e27cae72cf56`")),
    (FULL, "G-REQUEST", "a board id off its parent",
     sub("pack", "`307e836f-d138-801c-8008-e448c2314fb9`", "`307e836f-d138-801c-8008-e448c2314fb0`")),
    (FULL, "G-CITE", "cite a blank or moved line", sub("pack", "(`14`:1523)", "(`14`:1522)")),
    (FULL, "G-HYGIENE", "a closing keyword in the pack", sub("pack", "**Ticket:** E34-D05 (#1043)",
                                                             "**Ticket:** E34-D05, clo" + "ses #1043")),
    (FULL, "G-SCOPE", "the pack missing", lambda t: replace(t, pack=None)),
    (DECK, "G-SCOPE", "a pack file in the deck stage", lambda t: replace(t, pack="x")),
    (DECK, "G-SCOPE", "the deck missing", lambda t: replace(t, deck=None)),
]  # fmt: skip


def self_test(stage: str) -> int:
    base = load(stage)
    baseline = audit(base)
    print(f"self-test: {stage} stage, baseline {len(baseline)} FAIL")
    if baseline:
        for g, m in baseline:
            print(f"  {g}: {m}")
        return 1
    bad = 0
    ran = 0
    for when, gate, what, fn in MUTATIONS:
        if when not in (stage, "both"):
            continue
        ran += 1
        try:
            fails = {g for g, _ in audit(fn(base))}
        except ValueError as exc:
            print(f"FAIL {gate}: {what} -> {exc}")
            bad += 1
            continue
        ok = gate in fails
        bad += not ok
        print(f"{'ok  ' if ok else 'FAIL'} {gate}: {what} -> {gate if ok else sorted(fails)}")
    covered = {g for w, g, _, _ in MUTATIONS if w in (stage, "both")}
    missing = sorted(set(gates_for(stage)) - covered)
    if missing:
        print(f"self-test: no mutation for {missing}")
        bad += 1
    print(f"self-test: {ran} mutations, texts restored: {audit(base) == baseline}")
    print(f"self-test: {'PASS' if not bad else 'FAIL'}")
    return 1 if bad else 0


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0] if __doc__ else None)
    ap.add_argument("--stage", choices=(DECK, FULL), required=True)
    act = ap.add_mutually_exclusive_group(required=True)
    act.add_argument("--check", action="store_true")
    act.add_argument("--json", action="store_true")
    act.add_argument("--self-test", action="store_true")
    act.add_argument("--write-pins", action="store_true")
    ns = ap.parse_args(argv)
    t = load(ns.stage)
    if ns.self_test:
        return self_test(ns.stage)
    if ns.json:
        print(json.dumps(summary(t), indent=2, ensure_ascii=False))
        return 0
    if ns.write_pins:
        if ns.stage != FULL or not t.pack:
            print("refused: --write-pins needs the full stage and the pack")
            return 1
        (ROOT / PINS_REL).write_text(pins_text(t), encoding="utf-8")
        print(f"wrote {PINS_REL}")
        return 0
    fails = audit(t)
    for gate, msg in fails:
        print(f"{gate}: {msg}")
    _, body = deck_rows(t)
    n_cites = len(set(cites((t.pack or "") + (t.hand or ""))))
    print(f"{len(fails)} FAIL ({len(gates_for(ns.stage))} gates, {ns.stage} stage; "
          f"{n_cites} cites; {len(body)} deck rows)")  # fmt: skip
    return 1 if fails else 0


if __name__ == "__main__":
    sys.exit(main())
