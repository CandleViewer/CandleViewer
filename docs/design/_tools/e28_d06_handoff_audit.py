#!/usr/bin/env python3
"""E28-D06 (#842) audit: the design hand-off pack for the profile and trade-group screens.

Standalone, offline, stdlib only; it runs no repo code and is run with `python3 -I`. It reads the
pack (the spec, the hand-off, the copy deck) and the pins file from the working tree, and every
cited file AS TEXT with `git show` at the pinned base (`BASE`). E28-D04 and E28-D05 are merged
(#5618, #5619; both in `BASE`): their rows join PR 1b and cite their merged lines (the #842
ruling, 02). Default-deny: a gate that cannot read its input FAILs.

Two stages, named by an explicit `--stage deck|full` (default `full`; never chosen by which files
exist). `--stage full` runs every gate and needs the spec, the hand-off, the deck and the pins
file: a missing one FAILs G-STAGE and no other gate runs. `--stage deck` (PR 1a, deck-first, BQ-01
as ruled) needs the deck and the pins file and runs G-STAGE, G-DECK, G-STATUS, G-CODES, G-FROZEN,
G-CITE (the deck's cites), G-HYGIENE and G-SCOPE; the pack-side gates it does not run are named on
every run, never skipped silently.

Status words (BQ-12 as ruled on #950 and #1077): `merged`, `RULED`, `PROPOSED`. Whether a string
is frozen is a separate flag (`frozen`: FZ-n or null), never a status.

Gates (each FAIL led by its name):
  G-STAGE    every file the stage needs is in the working tree.
  G-DECK     the header line first; then rows with every field and no other; unique keys; known
             kinds, statuses and renders; every owner a ticket key; each cited line holds the
             row's `quote`, or its `text`; no placeholder word.
  G-STATUS   a merged row cites `22`, `14` or a D02 §10 row sourced (1) or (2); a RULED row cites
             D02 and never a D02 §10 row sourced (4); a row citing a (4) row is PROPOSED; an
             E28-D03, E28-D04, E28-D05 or E28-D06 row is PROPOSED, a D04 row names R-3 and cites
             `D04` lines only, a D05 row R-4 and `D05` lines only; at the full stage the spec's COUNT anchors equal the deck's counts.
  G-CODES    each of the ticket's eleven codes is a row's `code` or `rule`, or the header's alias
             of one (the deck is keyed by `22`'s served codes, C-6.1); spec section 8.2 lists them
             in order, each with a deck key that answers it.
  G-FROZEN   FZ-1 ... FZ-7 each flag at least one row; the header's freeze is PROPOSED.
  G-COMP     every component on the six `14` Components lines is in spec section 3.2 or named as
             not used; a section 3.2 id `15` lacks at the base names R-1.
  G-BIND     a backticked field or operation right before a `22` cite stands on that line; every
             `MX` cite is a route whose block says `state: executed`.
  G-BUDGET   every BUD anchor equals its `14` line.
  G-AHEAD    every DATE and SPRINT anchor is computed from the calendar's constants and the
             ticket JSON, and the SHA anchors are the pinned refs.
  G-EVENT    every action name in spec section 11, and every action name cited to `ACT` anywhere
             in the spec, stands on its cited lines.
  G-HIGH     spec section 7.3 lists F-01 ... F-05, each High, with an owner and R-6.
  G-HANDOFF  the hand-off has one `16` section 11.4 block per changed component, in order, every
             template line in order, each `[x]` with evidence or `[ ]` with `N/A -` or
             `PENDING -` and a reason; keyboard, name and exceptions are never N/A.
  G-AROW     hand-off section C runs A-1 ... A-6; each anchor is its entry's last pointer line at
             the base (re-found by content at the closing PR); each New line names its spec
             section and is not in `14`.
  G-FILLED   no placeholder word in the spec or the hand-off.
  G-CITE     every cite in range, on a non-blank line, and equal to the pins file's hash, and
             every pin cited (at the deck stage, the deck's cites only).
  G-RULED    the BQ rulings (comment 6601850682): spec section 6 carries the joint stale-preview
             sentence (its sha256 is JOINT_SHA, the same in #840, #841 and #842); section 7.2
             cites E47-D04's removed-row move and re-auth focus; section 7.3 says a 1b merge is
             not the owner's approval and dates every High; no "merges as is" wording.
  G-HYGIENE  no closing keyword, local path, URL or host, agent name or deny word in the texts,
             this tool or the pins file; no unknown anchor.
  G-SCOPE    the diff against `git merge-base HEAD origin/main` touches only this ticket's files:
             the deck, the tool and the pins at the deck stage; all five at the full stage.

Usage (from the repo root):
  python3 -I docs/design/_tools/e28_d06_handoff_audit.py --stage deck --check
  python3 -I docs/design/_tools/e28_d06_handoff_audit.py --stage full --check
  python3 -I docs/design/_tools/e28_d06_handoff_audit.py --stage full --json
  python3 -I docs/design/_tools/e28_d06_handoff_audit.py --stage full --self-test
  python3 -I docs/design/_tools/e28_d06_handoff_audit.py --stage deck --repin-ruled
  python3 -I docs/design/_tools/e28_d06_handoff_audit.py --stage full --repin-ruled
"""

from __future__ import annotations

import argparse
import datetime
import hashlib
import json
import re
import subprocess
import sys
from collections.abc import Callable
from dataclasses import dataclass, replace
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[3]
SPEC_REL = "docs/design/E28/E28-D06.md"
HAND_REL = "docs/design/E28/E28-D06-handoff.md"
DECK_REL = "docs/design/E28/E28-D06-copy-deck.jsonl"
TOOL_REL = "docs/design/_tools/e28_d06_handoff_audit.py"
PINS_REL = "docs/design/_tools/e28_d06_ruled_pins.txt"
OWN_FULL = (SPEC_REL, HAND_REL, DECK_REL, TOOL_REL, PINS_REL)
OWN_DECK = (DECK_REL, TOOL_REL, PINS_REL)
BASE = "ebe5c747bf43e9e8176cf586bc9d1519ba57d6e7"  # main with E28-D03 PR 2, D04 and D05 merged
D03_TEXT = "0af333fa0"  # E28-D03 PR 1 (#5463), merged in BASE
BOARDS = "ebe5c747b"  # E28-D03 PR 2 (#5482), merged as BASE: R-1, re-pinned by content
D04_MERGE = "bc7788eba"  # E28-D04 (#840), merged as #5618
D05_MERGE = "6170d577d"  # E28-D05 (#841), merged as #5619, in BASE unchanged
SHAS = {"BASE": BASE[:10], "D03": D03_TEXT, "BOARDS": BOARDS}
SHAS |= {"D04": D04_MERGE, "D05": D05_MERGE}
PATHS: dict[str, str] = {
    "02": "docs/plan/02-definition-of-ready-done.md",
    "14": "docs/plan/14-screens-catalogue.md",
    "15": "docs/plan/15-component-catalogue.md",
    "16": "docs/plan/16-design-system-brief.md",
    "22": "docs/plan/22-api-openapi.yaml",
    "23": "docs/plan/23-ws-protocol.md",
    "D02": "docs/design/E28/E28-D02.md",
    "D03": "docs/design/E28/E28-D03.md",
    "D04": "docs/design/E28/E28-D04.md",
    "D05": "docs/design/E28/E28-D05.md",
    "MX": "services/api/tests/contract/rbac/matrix.yaml",
    "ACT": "services/api/candleviewer/audit/actions.py",
    "CAL": "docs/plan/backlog/_tools/calendar_cv.py",
    "E28J": "docs/plan/backlog/E28.json",
    "05": "docs/plan/05-accessibility-standard.md",
    "E09-D09": "docs/design/E09/E09-D09.md",
    "E47-D04": "docs/design/E47/E47-D04.md",
    "E17-D01": "docs/design/E17/E17-D01.md",
    "README": "docs/design/README.md",
}
# a deck row's source may cite these only
COPY_KEYS = ("D02", "D03", "D04", "D05", "14", "22", "E09-D09")
CITE = re.compile(
    r"`(\d\d|D02|D03|D04|D05|MX|ACT|CAL|E28J|E09-D09|E47-D04|E17-D01|README)`"
    r":(\d+(?:–\d+)?(?:, :\d+(?:–\d+)?)*)"
)
ANCHOR = re.compile(r"(\S+?)<!--=([A-Z]+):([A-Za-z0-9]+)-->")
D02_DECK = (574, 643)  # D02 section 10, rows 1 ... 70
COMPONENT_LINES = {"SCR-061": 1512, "SCR-062": 1525, "SCR-130": 2750, "SCR-131": 2785}
COMPONENT_LINES |= {"SCR-132": 2795, "SCR-133": 2808}
BUDGETS = {
    "SCR133": (2810, r"<=\s*(\d+)\s*ms"),
    "SCR062": (1524, r"under (\d+) ms scripting"),
    "SCR061": (1509, r"preview ≤(\d+) ms"),
    "SCR131": (2784, r"targets <=(\d+) s"),
}
HANDOFF_CMPS: tuple[str, ...] = (
    "CMP-254",
    "CMP-255",
    "CMP-256",
    "CMP-138",
    "CMP-049",
    "CMP-028",
    "CMP-044",
)
HANDOFF_CMPS += ("CMP-050",)
TEMPLATE = (
    "Final Penpot link",
    "Variants × States matrix",
    "Keyboard table",
    "Accessible name / role table",
    "Live data",
    "Motion pair",
    "Density notes",
    "Essential-exceptions log",
    "Tokens used",
    "Data contract confirmed",
    "Contrast and CVD",
    "Design QA checklist (16 §12)",
    "Sign-off",
)
NEVER_NA = ("Keyboard table", "Accessible name / role table", "Essential-exceptions log")
AC_CODES = (
    "validation_failed",
    "native_stop_mandatory",
    "conflict",
    "precondition_failed",
    "step_up_required",
    "forbidden",
    "account_scope_denied",
    "env_mismatch",
    "rate_limited",
    "profile_forbidden",
    "risk_limit_breached",
)
HIGHS = ("F-01", "F-02", "F-03", "F-04", "F-05")
SCREENS = ("SCR-130", "SCR-131", "SCR-132", "SCR-133", "SCR-062", "SCR-061")
SECTION_OF = {"SCR-130": "4.1", "SCR-131": "4.2", "SCR-132": "4.3", "SCR-133": "4.4"}
SECTION_OF |= {"SCR-062": "4.5", "SCR-061": "4.6"}
FIELDS: tuple[str, ...] = (
    "id",
    "text",
    "screen",
    "kind",
    "code",
    "rule",
    "render",
    "status",
    "owner",
)
FIELDS += ("consumer", "source", "quote", "note")
ROW_FIELDS = frozenset(("list", *FIELDS, "frozen"))
HEAD_FIELDS = ("pack", "version", "base", "fields", "flags", "statuses", "render", "freeze")
ALIASES = {
    "precondition_failed": "version_conflict",
    "env_mismatch": "environment_mismatch",
    "profile_forbidden": "risk_limit_breached",
}  # the ticket's names -> `22`'s served codes (C-1 ... C-3)
JOINT_SHA = "0f6f2a95fc688dbc81f1e001a18bd0896bf1546b29dd4376ecbb4bee4b2d86d2"
JOINT_RX = re.compile(r"\*\*Stale preview \(joint ruling: .*?#5550\.")
POINTER = re.compile(r"^- \*\*[^*]*\(E\d\d-D\d\d\):\*\*")
KINDS: tuple[str, ...] = (
    "label",
    "unit",
    "helper",
    "message",
    "empty",
    "warning",
    "confirm",
    "reason",
    "announce",
)
KINDS += ("name", "status", "value", "description")
STATUSES = ("merged", "RULED", "PROPOSED")
RENDERS = ("deck", "served", "deck+served", "served+deck")
OWNER = re.compile(r"^E(?:28|09)-[DSTQXK]\d\d$")
CONSUMER = re.compile(r"^E28-S0[1-5]$")
KEY = re.compile(r"^e28\.[a-z0-9_]+(?:\.[a-z0-9_]+)*$")
FROZEN = re.compile(r"^FZ-(\d+)$")
FZ_COUNT = 7
CLOSING = re.compile(r"\b(?:close[sd]?|fix(?:e[sd])?|resolve[sd]?)\s+#\d+", re.IGNORECASE)
LOCAL_PATH = re.compile("/" + "home/|/" + "tmp/|/Users/|[A-Za-z]:\\\\|\\bnotes" + "/")
AGENT_NAME = re.compile(r"\b[a-z]{2,4}-worker-\d\b")
URL_OR_HOST = re.compile(r"https?://|penpot\.[a-z]|team-id=|file-id=", re.IGNORECASE)
PLACEHOLDER = re.compile(r"\bT" + r"BD\b|\bTO" + r"DO\b|\bFIX" + r"ME\b|\?\?\?|\bXX" + r"X\b")
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


@dataclass(frozen=True)
class Texts:
    spec: str | None
    hand: str | None
    deck: str | None
    pins: str | None
    tool: str
    changed: list[str] | None
    memo: dict[str, str | None]


Finding = tuple[str, str]


def git(*args: str) -> str | None:
    try:
        r = subprocess.run(["git", "-C", str(ROOT), *args], capture_output=True, check=False)
    except OSError:
        return None
    return r.stdout.decode("utf-8", "surrogateescape") if r.returncode == 0 else None


SPLIT: dict[str, list[str]] = {}


def at(t: Texts, key: str) -> list[str]:
    memo_key = f"{BASE}:{PATHS[key]}"
    if memo_key not in t.memo:
        t.memo[memo_key] = git("show", memo_key)
    text = t.memo[memo_key]
    if text is None:
        raise SystemExit(f"{PATHS[key]} does not resolve at {BASE[:10]}; fetch first")
    if memo_key not in SPLIT:
        SPLIT[memo_key] = text.split("\n")
    return SPLIT[memo_key]


def line(t: Texts, key: str, n: int) -> str:
    ls = at(t, key)
    return ls[n - 1] if 0 < n <= len(ls) else ""


def norm(s: str) -> str:
    return " ".join(s.split())


def cells(ln: str) -> list[str]:
    return [c.strip() for c in re.split(r"(?<!\\)\|", ln.strip().strip("|"))]


def numbers(spec: str) -> list[int]:
    out: list[int] = []
    for part in spec.split(", "):
        part = part.lstrip(":")
        if "–" in part:
            a, b = part.split("–")
            out.extend(range(int(a), int(b) + 1))
        else:
            out.append(int(part))
    return out


def cites(text: str) -> list[tuple[str, int]]:
    return [(m.group(1), n) for m in CITE.finditer(text) for n in numbers(m.group(2))]


def section(text: str, head: str) -> str:
    """The body under a heading that starts with `head`, up to the next heading of its level."""
    ls = text.split("\n")
    for i, ln in enumerate(ls):
        if ln.startswith(head):
            level = len(ln) - len(ln.lstrip("#"))
            out = []
            for nxt in ls[i + 1 :]:
                lead = len(nxt) - len(nxt.lstrip("#"))
                if nxt.startswith("#") and 0 < lead <= level:
                    break
                out.append(nxt)
            return "\n".join(out)
    return ""


def deck_rows(t: Texts) -> tuple[dict[str, Any] | None, list[dict[str, Any]], list[Finding]]:
    bad: list[Finding] = []
    if t.deck is None:
        return None, [], [("G-DECK", "no deck")]
    ls = [x for x in t.deck.split("\n") if x.strip()]
    try:
        parsed = [json.loads(x) for x in ls]
    except json.JSONDecodeError as e:
        return None, [], [("G-DECK", f"the deck does not parse: {e}")]
    if not parsed or "pack" not in parsed[0]:
        return None, [], [("G-DECK", "the header line is not first")]
    head = parsed[0]
    for f in HEAD_FIELDS:
        if f not in head:
            bad.append(("G-DECK", f"the header lacks `{f}`"))
    return head, parsed[1:], bad


def src_cites(row: dict[str, Any]) -> list[tuple[str, int]]:
    out: list[tuple[str, int]] = []
    for s in row.get("source") or []:
        out.extend(cites(str(s)))
    return out


def d02_source_cell(t: Texts, n: int) -> str:
    if not D02_DECK[0] <= n <= D02_DECK[1]:
        return ""
    c = cells(line(t, "D02", n))
    return c[3] if len(c) > 3 else ""


# ------------------------------------------------------------------------------------------ gates


def g_deck(t: Texts) -> list[Finding]:
    head, rows, bad = deck_rows(t)
    if head is None:
        return bad
    if list(head.get("statuses", [])) != list(STATUSES):
        bad.append(("G-DECK", "the header's statuses are not merged, RULED, PROPOSED"))
    seen: set[str] = set()
    for r in rows:
        k = str(r.get("id"))
        if set(r) != ROW_FIELDS:
            bad.append(("G-DECK", f"{k}: fields {sorted(set(r) ^ ROW_FIELDS)} differ"))
            continue
        if not KEY.match(k) or k in seen:
            bad.append(("G-DECK", f"{k}: a bad or repeated key"))
        seen.add(k)
        if r["kind"] not in KINDS or r["status"] not in STATUSES or r["render"] not in RENDERS:
            bad.append(("G-DECK", f"{k}: an unknown kind, status or render"))
        if not isinstance(r["owner"], str) or not OWNER.match(r["owner"]):
            bad.append(("G-DECK", f"{k}: owner {r['owner']!r} is not a ticket key"))
        if not r["consumer"] or not all(CONSUMER.match(str(c)) for c in r["consumer"]):
            bad.append(("G-DECK", f"{k}: consumer {r['consumer']!r}"))
        if not r["screen"] or not set(r["screen"]) <= set(SCREENS):
            bad.append(("G-DECK", f"{k}: screen {r['screen']!r}"))
        if r["frozen"] is not None and not FROZEN.match(str(r["frozen"])):
            bad.append(("G-DECK", f"{k}: frozen {r['frozen']!r}"))
        if not str(r["text"]).strip() or PLACEHOLDER.search(str(r["text"])):
            bad.append(("G-DECK", f"{k}: an empty or placeholder text"))
        if not r["source"]:
            bad.append(("G-DECK", f"{k}: no source"))
        span = norm(str(r["quote"] if r["quote"] is not None else r["text"]))
        for key, n in src_cites(r):
            if key not in COPY_KEYS:
                bad.append(("G-DECK", f"{k}: cites `{key}`, not a copy source"))
            elif span not in norm(line(t, key, n)):
                bad.append(("G-DECK", f"{k}: its words are not on `{key}`:{n}"))
    return bad


def g_status(t: Texts) -> list[Finding]:
    _, rows, bad0 = deck_rows(t)
    if bad0:
        return [("G-STATUS", "no deck rows to judge")]
    bad: list[Finding] = []
    for r in rows:
        k, st, owner = r.get("id"), r.get("status"), r.get("owner")
        cs = src_cites(r)
        d02_cells = [d02_source_cell(t, n) for key, n in cs if key == "D02"]
        if st == "merged":
            ok = any(key in ("22", "14", "E09-D09") for key, _ in cs)
            ok = ok or any(c.startswith(("(1)", "(2)")) for c in d02_cells)
            if not ok:
                bad.append(("G-STATUS", f"{k}: merged with no merged source"))
        if st == "RULED" and not any(key == "D02" for key, _ in cs):
            bad.append(("G-STATUS", f"{k}: RULED with no D02 cite"))
        if any(c.startswith("(4)") for c in d02_cells) and st != "PROPOSED":
            bad.append(("G-STATUS", f"{k}: cites a D02 row sourced (4) but is {st}"))
        if owner in ("E28-D03", "E28-D04", "E28-D05", "E28-D06") and st != "PROPOSED":
            bad.append(("G-STATUS", f"{k}: {owner}'s string is {st}, not PROPOSED"))
        joined = " ".join(str(s) for s in r.get("source") or [])
        keys = {key for key, _ in cs}
        if owner == "E28-D04" and ("(R-3)" not in joined or keys != {"D04"}):
            bad.append(("G-STATUS", f"{k}: a D04 row names R-3 and cites `D04` lines only"))
        if owner == "E28-D05" and ("(R-4)" not in joined or keys != {"D05"}):
            bad.append(("G-STATUS", f"{k}: a D05 row names R-4 and cites `D05` lines only"))
    return bad


def g_codes(t: Texts, full: bool) -> list[Finding]:
    head, rows, bad0 = deck_rows(t)
    if head is None or bad0:
        return [("G-CODES", "no deck to read")]
    bad: list[Finding] = []
    if tuple(head.get("ac_codes", ())) != AC_CODES:
        bad.append(("G-CODES", "the header's ac_codes are not the ticket's eleven"))
    if head.get("aliases") != ALIASES:
        bad.append(("G-CODES", "the header's aliases are not the ticket's three names"))
    answered = {r.get("code") for r in rows} | {r.get("rule") for r in rows}
    for c in AC_CODES:
        if ALIASES.get(c, c) not in answered:
            bad.append(("G-CODES", f"`{c}` has no row"))
    if not full or t.spec is None:
        return bad
    by_key = {r.get("id"): r for r in rows}
    body = section(t.spec, "### 8.2")
    listed = []
    for ln in body.split("\n"):
        cc = cells(ln) if ln.startswith("| `") else []
        if len(cc) < 3:
            continue
        code = cc[0].strip("`")
        listed.append(code)
        key = re.search(r"`(e28\.[a-z0-9_.]+)`", cc[2])
        row = by_key.get(key.group(1)) if key else None
        if row is None or ALIASES.get(code, code) not in (row.get("code"), row.get("rule")):
            bad.append(("G-CODES", f"section 8.2's `{code}` names no deck row answering it"))
    if tuple(listed) != AC_CODES:
        bad.append(("G-CODES", "section 8.2 does not list the eleven codes in order"))
    return bad


def g_frozen(t: Texts) -> list[Finding]:
    head, rows, bad0 = deck_rows(t)
    if head is None or bad0:
        return [("G-FROZEN", "no deck to read")]
    bad: list[Finding] = []
    if "PROPOSED" not in str(head.get("freeze", "")):
        bad.append(("G-FROZEN", "the header's freeze is not PROPOSED"))
    ids = {int(m.group(1)) for r in rows if (m := FROZEN.match(str(r.get("frozen") or "")))}
    if ids != set(range(1, FZ_COUNT + 1)):
        bad.append(("G-FROZEN", f"frozen ids {sorted(ids)} are not FZ-1 ... FZ-{FZ_COUNT}"))
    return bad


def g_comp(t: Texts) -> list[Finding]:
    assert t.spec is not None
    bad: list[Finding] = []
    body = section(t.spec, "### 3.2")
    rows = {c[0]: c for ln in body.split("\n") if (c := cells(ln)) and c[0].startswith("CMP-")}
    tail = body.split("Not used:")[-1] if "Not used:" in body else ""
    for scr, n in COMPONENT_LINES.items():
        for cmp_id in sorted(set(re.findall(r"CMP-\d{3}", line(t, "14", n)))):
            if cmp_id not in rows and cmp_id not in tail:
                bad.append(("G-COMP", f"{scr}'s {cmp_id} (`14`:{n}) is not in section 3.2"))
    cat = "\n".join(at(t, "15"))
    for cmp_id, c in rows.items():
        if f"### {cmp_id}" not in cat and f"{cmp_id} " not in cat and "R-1" not in c[-1]:
            bad.append(("G-COMP", f"{cmp_id} is not in `15` at the base and names no R-1"))
    return bad


def g_bind(t: Texts) -> list[Finding]:
    assert t.spec is not None and t.hand is not None
    bad: list[Finding] = []
    for text in (t.spec, t.hand):
        for m in re.finditer(r"`([^`]+)` \(`22`:(\d+)\)", text):
            word = m.group(1).replace("[]", "").split(".")[-1]
            if word not in line(t, "22", int(m.group(2))):
                bad.append(("G-BIND", f"`{m.group(1)}` is not on `22`:{m.group(2)}"))
        for key, n in cites(text):
            if key != "MX":
                continue
            head = line(t, "MX", n).strip()
            block = "\n".join(line(t, "MX", n + i) for i in range(1, 7))
            if (
                not re.match(r"(GET|POST|PUT|DELETE|PATCH) /", head)
                or "state: executed" not in block
            ):
                bad.append(("G-BIND", f"`MX`:{n} is not an executed route"))
    return bad


def cal_dates(t: Texts) -> tuple[datetime.date, int]:
    text = "\n".join(at(t, "CAL"))
    m = re.search(r"SPRINT01_START = datetime\.date\((\d+), (\d+), (\d+)\)", text)
    d = re.search(r"SPRINT_DAYS = (\d+)", text)
    if not m or not d:
        raise SystemExit("the calendar's constants are not readable")
    return datetime.date(int(m.group(1)), int(m.group(2)), int(m.group(3))), int(d.group(1))


def sprint_of(t: Texts, key: str) -> int:
    for item in json.loads("\n".join(at(t, "E28J"))):
        if item.get("key") == key:
            m = re.search(r"\d+", str(item.get("sprint")))
            return int(m.group(0)) if m else -1
    return -1


def expected_anchors(t: Texts) -> dict[str, str]:
    start, days = cal_dates(t)

    def rng(n: int) -> tuple[datetime.date, datetime.date]:
        s = start + datetime.timedelta(days=(n - 1) * days)
        return s, s + datetime.timedelta(days=days - 1)

    d06, s01, s05 = sprint_of(t, "E28-D06"), sprint_of(t, "E28-S01"), sprint_of(t, "E28-S05")
    want = {
        "SPRINT:D06": str(d06),
        "SPRINT:S01": str(s01),
        "SPRINT:S05": str(s05),
        "DATE:S14END": rng(d06)[1].isoformat(),
        "DATE:S16START": rng(s01)[0].isoformat(),
        "DATE:AHEAD": rng(s01 - 3)[1].isoformat(),
    }
    for name, (n, pat) in BUDGETS.items():
        m = re.search(pat, line(t, "14", n))
        want[f"BUD:{name}"] = m.group(1) if m else "unreadable"
    _, rows, _ = deck_rows(t)
    want["COUNT:ROWS"] = str(len(rows))
    for st in STATUSES:
        want[f"COUNT:{st.upper()}"] = str(sum(1 for r in rows if r.get("status") == st))
    for name, sha in SHAS.items():
        want[f"SHA:{name}"] = sha
    return want


def g_anchors(t: Texts) -> list[Finding]:
    assert t.spec is not None and t.hand is not None
    want = expected_anchors(t)
    bad: list[Finding] = []
    for text in (t.spec, t.hand):
        for m in ANCHOR.finditer(text):
            name = f"{m.group(2)}:{m.group(3)}"
            gate = {"BUD": "G-BUDGET", "COUNT": "G-STATUS"}.get(m.group(2), "G-AHEAD")
            got = m.group(1).strip("`").rstrip(".,;)")
            got = re.sub(r"^[^0-9a-f]*", "", got) if m.group(2) == "SHA" else got
            if name not in want:
                bad.append(("G-HYGIENE", f"unknown anchor {name}"))
            elif not got.endswith(want[name]) and got != want[name]:
                bad.append((gate, f"{name} reads {got}, computed {want[name]}"))
    if want["SPRINT:S01"] != str(sprint_of(t, "E28-S04")):
        bad.append(("G-AHEAD", "E28-S01 and E28-S04 start in different sprints"))
    return bad


def g_event(t: Texts) -> list[Finding]:
    assert t.spec is not None
    bad: list[Finding] = []
    for m in re.finditer(r"`([a-z_]+\.[a-z_]+)` \(`ACT`:(\d+)\)", t.spec):
        if m.group(1) not in line(t, "ACT", int(m.group(2))):
            bad.append(("G-EVENT", f"`{m.group(1)}` is not on `ACT`:{m.group(2)}"))
    for ln in section(t.spec, "## 11.").split("\n"):
        if not ln.startswith("| SCR") and not ln.startswith("| all"):
            continue
        for cell in cells(ln)[1:3]:
            got = cites(cell)
            if not got:
                continue
            text = "\n".join(line(t, key, n) for key, n in got)
            for name in re.findall(r"`([a-z_]*\.[a-z_]+)`", cell):
                if name not in text:
                    bad.append(("G-EVENT", f"`{name}` is not on its cited lines"))
    return bad


def g_high(t: Texts) -> list[Finding]:
    assert t.spec is not None
    body = section(t.spec, "### 7.3")
    rows = [c for ln in body.split("\n") if (c := cells(ln)) and re.match(r"F-\d\d$", c[0])]
    bad: list[Finding] = []
    if tuple(c[0] for c in rows) != HIGHS:
        bad.append(("G-HIGH", f"section 7.3 lists {[c[0] for c in rows]}, not F-01 ... F-05"))
    for c in rows:
        if len(c) < 6 or c[1] != "High" or not c[4] or c[5] != "R-6":
            bad.append(("G-HIGH", f"{c[0]}: not High with an owner and R-6"))
    if "H-1" not in body:
        bad.append(("G-HIGH", "section 7.3 names no hold"))
    return bad


def g_handoff(t: Texts) -> list[Finding]:
    assert t.hand is not None
    bad: list[Finding] = []
    whole = "\n".join(at(t, "16"))
    tpl = whole[whole.find("### 11.4") : whole.find("### 11.5")]
    pos = [tpl.find(f"**{lbl}**") for lbl in TEMPLATE]
    if -1 in pos or pos != sorted(pos):
        bad.append(
            ("G-HANDOFF", "`16` section 11.4's template lines are not as this tool reads them")
        )
    blocks = re.split(r"\n## Handoff checklist — ", t.hand)[1:]
    got = [b.split(" ", 1)[0] for b in blocks]
    if tuple(got) != HANDOFF_CMPS:
        bad.append(("G-HANDOFF", f"the blocks are {got}, not {list(HANDOFF_CMPS)}"))
    for b in blocks:
        cmp_id = b.split(" ", 1)[0]
        items = [x for x in b.split("\n") if x.startswith("- [")]
        labels = [m.group(1) for x in items if (m := re.match(r"- \[[ x]\] \*\*(.+?)\*\*", x))]
        if tuple(labels) != TEMPLATE:
            bad.append(("G-HANDOFF", f"{cmp_id}: the lines are not the template's, in order"))
        for x in items:
            m = re.match(r"- \[([ x])\] \*\*(.+?)\*\*(.*)$", x)
            if not m:
                continue
            mark, lbl, rest = m.groups()
            rest = re.sub(r"^ and the \*\*.+?\*\*", "", rest)
            if mark == "x" and not re.match(r" — \S", rest):
                bad.append(("G-HANDOFF", f"{cmp_id} {lbl}: ticked with no evidence"))
            if mark == " " and not re.match(r" — (N/A|PENDING) — \S", rest):
                bad.append(("G-HANDOFF", f"{cmp_id} {lbl}: open with no N/A or PENDING reason"))
            if lbl in NEVER_NA and rest.startswith(" — N/A"):
                bad.append(("G-HANDOFF", f"{cmp_id} {lbl}: never N/A"))
    return bad


def g_arow(t: Texts) -> list[Finding]:
    assert t.hand is not None
    bad: list[Finding] = []
    body = section(t.hand, "## §C")
    rows = [c for ln in body.split("\n") if (c := cells(ln)) and re.match(r"A-\d+$", c[0])]
    if [c[0] for c in rows] != [f"A-{i}" for i in range(1, 7)]:
        bad.append(("G-AROW", "section C does not run A-1 ... A-6"))
    cat = "\n".join(at(t, "14"))
    for c in rows:
        if len(c) < 4:
            continue
        got = cites(c[2])
        n = got[0][1] if got else 0
        heads = [i for i in range(n, 0, -1) if line(t, "14", i).startswith("### SCR-")]
        entry = line(t, "14", heads[0]).split(" ")[1] if heads else ""
        nxt = next((i for i in range(n + 1, n + 60) if line(t, "14", i).startswith("### ")), n)
        later = [i for i in range(n + 1, nxt) if POINTER.match(line(t, "14", i))]
        if not POINTER.match(line(t, "14", n)) or later or entry != c[1]:
            bad.append(("G-AROW", f"{c[0]}: `14`:{n} is not {c[1]}'s last pointer line"))
        new = c[3].strip('"')
        if f"§{SECTION_OF.get(c[1], '?')} " not in new or norm(new) in norm(cat):
            bad.append(("G-AROW", f"{c[0]}: the New line names another section or is applied"))
    return bad


def g_filled(t: Texts) -> list[Finding]:
    bad: list[Finding] = []
    for name, text in (("spec", t.spec), ("hand-off", t.hand)):
        for m in PLACEHOLDER.finditer(text or ""):
            bad.append(("G-FILLED", f"the {name} holds the placeholder {m.group(0)!r}"))
    return bad


def pin_hash(s: str) -> str:
    return hashlib.sha256(norm(s).encode("utf-8")).hexdigest()[:12]


def all_cites(t: Texts, full: bool = True) -> set[tuple[str, int]]:
    out: set[tuple[str, int]] = set()
    for text in (t.spec, t.hand) if full else ():
        out.update(cites(text or ""))
    _, rows, _ = deck_rows(t)
    for r in rows:
        out.update(src_cites(r))
    return out


def g_cite(t: Texts, full: bool = True) -> list[Finding]:
    bad: list[Finding] = []
    pins: dict[tuple[str, int], str] = {}
    for ln in (t.pins or "").split("\n"):
        m = re.match(r"^([\w-]+):(\d+) ([0-9a-f]{12})$", ln.strip())
        if m:
            pins[(m.group(1), int(m.group(2)))] = m.group(3)
    used = all_cites(t, full)
    for key, n in sorted(used):
        text = line(t, key, n)
        if not text.strip():
            bad.append(("G-CITE", f"`{key}`:{n} is out of range or blank"))
        elif pins.get((key, n)) != pin_hash(text):
            bad.append(("G-CITE", f"`{key}`:{n} differs from its pin"))
    for key, n in sorted(set(pins) - used):
        bad.append(("G-CITE", f"the pin {key}:{n} is cited nowhere"))
    return bad


def g_ruled(t: Texts) -> list[Finding]:
    assert t.spec is not None and t.hand is not None
    bad: list[Finding] = []
    hit = JOINT_RX.search(section(t.spec, "## 6."))
    if not hit or hashlib.sha256(hit.group(0).encode()).hexdigest() != JOINT_SHA:
        bad.append(("G-RULED", "section 6 lacks the joint stale-preview sentence verbatim"))
    s72, s73 = section(t.spec, "### 7.2"), section(t.spec, "### 7.3")
    if "`E47-D04`:285" not in s72 or "`E47-D04`:302" not in s72:
        bad.append(("G-RULED", "section 7.2 does not cite E47-D04 as the focus owner"))
    if "is not the owner's approval" not in s73:
        bad.append(("G-RULED", "section 7.3 does not say a 1b merge is not the owner's approval"))
    for c in (c for ln in s73.split("\n") if (c := cells(ln)) and re.match(r"F-\d\d$", c[0])):
        if not re.fullmatch(r"\d{4}-\d\d-\d\d", c[-1]):
            bad.append(("G-RULED", f"{c[0]}: a High with no date"))
    if re.search(r"merges? as is", t.spec + t.hand):
        bad.append(("G-RULED", "pre-stage 'merges as is' wording is left"))
    return bad


def g_hygiene(t: Texts, full: bool) -> list[Finding]:
    bad: list[Finding] = []
    texts = [("deck", t.deck or ""), ("tool", t.tool)]
    if full:
        texts += [("spec", t.spec or ""), ("hand-off", t.hand or ""), ("pins", t.pins or "")]
    for name, text in texts:
        if name != "tool":
            for rx in (CLOSING, LOCAL_PATH, AGENT_NAME, URL_OR_HOST):
                if m := rx.search(text):
                    bad.append(("G-HYGIENE", f"the {name} holds {m.group(0)!r}"))
        low = text.lower()
        for w in DENY:
            if w in low:
                bad.append(("G-HYGIENE", f"the {name} holds a deny word ({w[:2]}…)"))
    return bad


def g_scope(t: Texts, full: bool) -> list[Finding]:
    if t.changed is None:
        return [("G-SCOPE", "git could not list the diff")]
    own = OWN_FULL if full else OWN_DECK
    return [("G-SCOPE", f"{p} is not this ticket's") for p in t.changed if p not in own]


# ------------------------------------------------------------------------------------------ runner

DECK_GATES: tuple[str, ...] = ("G-STAGE", "G-DECK", "G-STATUS", "G-CODES", "G-FROZEN", "G-CITE")
DECK_GATES += ("G-HYGIENE", "G-SCOPE")
FULL_ONLY: tuple[str, ...] = (
    "G-COMP",
    "G-BIND",
    "G-BUDGET",
    "G-AHEAD",
    "G-EVENT",
    "G-HIGH",
    "G-HANDOFF",
)
FULL_ONLY += ("G-AROW", "G-FILLED", "G-RULED")


def run(t: Texts, full: bool) -> list[Finding]:
    need = [("spec", t.spec), ("hand-off", t.hand)] if full else []
    missing = [n for n, v in [("deck", t.deck), ("pins", t.pins), *need] if v is None]
    if missing:
        return [("G-STAGE", f"missing for this stage: {', '.join(missing)}")]
    out = g_deck(t) + g_status(t) + g_codes(t, full) + g_frozen(t)
    out += g_cite(t, full) + g_hygiene(t, full) + g_scope(t, full)
    if full:
        out += g_comp(t) + g_bind(t) + g_anchors(t) + g_event(t) + g_high(t)
        out += g_handoff(t) + g_arow(t) + g_filled(t) + g_ruled(t)
    return out


def read(rel: str) -> str | None:
    p = ROOT / rel
    return p.read_text(encoding="utf-8") if p.is_file() else None


def changed_paths() -> list[str] | None:
    base = git("merge-base", "HEAD", "origin/main")
    if base is None:
        return None
    diff = git("diff", "--name-only", base.strip())
    status = git("status", "--porcelain", "--untracked-files=all")
    if diff is None or status is None:
        return None
    paths = set(diff.split()) | {ln[3:].strip() for ln in status.split("\n") if ln.strip()}
    return sorted(p for p in paths if p)


def load() -> Texts:
    tool = read(TOOL_REL) or ""
    return Texts(
        read(SPEC_REL), read(HAND_REL), read(DECK_REL), read(PINS_REL), tool, changed_paths(), {}
    )


def sub(field: str, old: str, new: str) -> Callable[[Texts], Texts]:
    def f(t: Texts) -> Texts:
        text = getattr(t, field)
        if text is None or old not in text:
            raise SystemExit(f"self-test: {old!r} not in {field}")
        return replace(t, **{field: text.replace(old, new, 1)})

    return f


def deck_edit(key: str, change: Callable[[dict[str, Any]], None]) -> Callable[[Texts], Texts]:
    def f(t: Texts) -> Texts:
        assert t.deck is not None
        out = []
        for ln in t.deck.split("\n"):
            if ln.strip() and json.loads(ln).get("id") == key:
                r = json.loads(ln)
                change(r)
                ln = json.dumps(r, ensure_ascii=False)
            out.append(ln)
        return replace(t, deck="\n".join(out))

    return f


def setter(field: str, value: Any) -> Callable[[dict[str, Any]], None]:
    def f(r: dict[str, Any]) -> None:
        r[field] = value

    return f


MUTATIONS: list[tuple[str, str, Callable[[Texts], Texts]]] = [
    ("MU-1", "G-STAGE", lambda t: replace(t, deck=None)),
    ("MU-2", "G-DECK", deck_edit("e28.code.precision", setter("owner", "the copy owner"))),
    ("MU-3", "G-DECK", deck_edit("e28.code.ladder_sum", setter("text", "Rungs over 100 %."))),
    ("MU-4", "G-STATUS", deck_edit("e28.code.range", setter("status", "RULED"))),
    ("MU-5", "G-STATUS", deck_edit("e28.menu.block_on", setter("status", "RULED"))),
    ("MU-6", "G-CODES", deck_edit("e28.code.version_conflict", setter("code", "conflict"))),
    ("MU-7", "G-FROZEN", deck_edit("e28.code.risk_limit_breached", setter("frozen", None))),
    ("MU-8", "G-HYGIENE", lambda t: replace(t, tool=t.tool + "\n# " + "flo" + "od\n")),
    ("MU-9", "G-SCOPE", lambda t: replace(t, changed=[*(t.changed or []), PATHS["14"]])),
    ("MU-10", "G-DECK", deck_edit("e28.code.write_once", setter("id", "e28.code.write_ONCE"))),
    ("MU-11", "G-COMP", sub("spec", "| CMP-232 | LimitsChip", "| CMP-23x | LimitsChip")),
    ("MU-12", "G-BIND", sub("spec", "`updated_at` (`22`:20367)", "`updated_on` (`22`:20367)")),
    ("MU-13", "G-BUDGET", sub("spec", "600<!--=BUD:SCR133-->", "650<!--=BUD:SCR133-->")),
    (
        "MU-14",
        "G-AHEAD",
        sub("spec", "2027-01-08<!--=DATE:S16START-->", "2027-01-09<!--=DATE:S16START-->"),
    ),
    (
        "MU-15",
        "G-EVENT",
        sub("spec", "`profile.save_refused` (`ACT`", "`profile.save_failed` (`ACT`"),
    ),
    ("MU-16", "G-HIGH", sub("spec", "| F-04 | High", "| F-04 | Medium")),
    (
        "MU-17",
        "G-HANDOFF",
        sub(
            "hand",
            "- [x] **Keyboard table** — not focusable; focus belongs",
            "- focusable; focus belongs",
        ),
    ),
    (
        "MU-18",
        "G-HANDOFF",
        sub("hand", "**Live data** — N/A — a static marker", "**Live data** — N/A"),
    ),
    ("MU-19", "G-AROW", sub("hand", "| A-1 | SCR-130 |", "| A-1 | SCR-131 |")),
    ("MU-20", "G-FILLED", sub("hand", "## §E Test hooks", "## §E Test hooks (T" + "BD)")),
    ("MU-21", "G-CITE", sub("hand", "`D03`:388", "`D03`:389")),
    (
        "MU-22",
        "G-HYGIENE",
        sub("spec", "Nothing here edits a parent", "Clos" + "es #842. Nothing here edits a parent"),
    ),
    ("MU-23", "G-STATUS", deck_edit("e28.helper.default_ceiling", setter("status", "merged"))),
    ("MU-24", "G-CODES", sub("spec", "| `rate_limited`          |", "| `rate_limit`            |")),
    ("MU-25", "G-CITE", sub("pins", "\nD02:", "\nD02:9")),
    ("MU-26", "G-RULED", sub("spec", "decoration only, never", "decoration, never")),
    (
        "MU-27",
        "G-RULED",
        sub("spec", "not the owner's approval (`README`", "the approval (`README`"),
    ),
    (
        "MU-28",
        "G-CODES",
        lambda t: replace(t, deck=(t.deck or "").replace('"aliases": {', '"x": {', 1)),
    ),
    ("MU-29", "G-STATUS", deck_edit("e28.busy.saving", setter("owner", "E28-D05"))),
]


DECK_MUTATIONS: tuple[str, ...] = (
    "MU-1",
    "MU-2",
    "MU-3",
    "MU-4",
    "MU-5",
    "MU-6",
    "MU-7",
    "MU-8",
    "MU-9",
    "MU-10",
)
DECK_MUTATIONS += ("MU-23", "MU-25", "MU-28")


def self_test(t: Texts, full: bool) -> int:
    base = {f for f in run(t, full)}
    if base:
        print("SELF-TEST: the pack must pass before mutating")
        return 1
    failures = 0
    gates = DECK_GATES if not full else DECK_GATES + FULL_ONLY
    for mid, gate, mutate in MUTATIONS:
        if gate not in gates or (not full and mid not in DECK_MUTATIONS):
            continue
        got = run(mutate(t), full)
        names = {g for g, _ in got}
        ok = names == {gate}
        failures += 0 if ok else 1
        print(f"{'ok  ' if ok else 'FAIL'} {mid} -> {gate}: {sorted(names) or 'no FAIL'}")
    on_disk = load()
    same = (on_disk.spec, on_disk.hand, on_disk.deck) == (t.spec, t.hand, t.deck)
    if not same:
        print("FAIL the texts on disk changed")
        failures += 1
    print(f"self-test: {failures} failing mutation(s)")
    return 1 if failures else 0


def repin(t: Texts, full: bool) -> int:
    out = [
        "# E28-D06 pins: one line per cited line, `KEY:line sha256[:12]` of its whitespace-",
        f"# normalised text at {BASE[:10]}. Written only by --repin-ruled.",
    ]
    out += [f"{k}:{n} {pin_hash(line(t, k, n))}" for k, n in sorted(all_cites(t, full))]
    (ROOT / PINS_REL).write_text("\n".join(out) + "\n", encoding="utf-8")
    print(f"wrote {len(out) - 2} pins")
    return 0


def main(argv: list[str]) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--stage", choices=("deck", "full"), default="full")
    mode = ap.add_mutually_exclusive_group(required=True)
    mode.add_argument("--check", action="store_true")
    mode.add_argument("--json", action="store_true")
    mode.add_argument("--self-test", action="store_true")
    mode.add_argument("--repin-ruled", action="store_true")
    a = ap.parse_args(argv)
    full = a.stage == "full"
    t = load()
    if a.repin_ruled:
        return repin(t, full)
    if a.self_test:
        return self_test(t, full)
    found = run(t, full)
    if a.json:
        _, rows, _ = deck_rows(t)
        counts = {s: sum(1 for r in rows if r.get("status") == s) for s in STATUSES}
        print(
            json.dumps(
                {"stage": a.stage, "rows": len(rows), "status": counts, "findings": found},
                indent=2,
                ensure_ascii=False,
            )
        )
        return 1 if found else 0
    print(f"stage: {a.stage}")
    if not full:
        print(f"not run at this stage: {', '.join(FULL_ONLY)}")
    for gate, msg in found:
        print(f"FAIL {gate}: {msg}")
    ran = DECK_GATES + (FULL_ONLY if full else ())
    for gate in ran:
        if not any(g == gate for g, _ in found):
            print(f"PASS {gate}")
    return 1 if found else 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
