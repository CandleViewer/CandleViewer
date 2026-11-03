#!/usr/bin/env python3
"""E24-D05 (#663) audit: the design hand-off pack for the derivatives panel (SCR-054).

Standalone, offline, stdlib only; it runs no repo code and is run with `python3 -I`. It reads the
pack, the hand-off, the copy deck and the pins file from the working tree, and every cited file AS
TEXT with `git show` at the pinned base (`BASE`, `main`; every parent is merged there). Default-deny:
a gate that cannot read its input FAILs. Shaped like the E24-D04 sibling tool (#5464); the stage
switch follows the E38-D06 tool (#1077).

Two stages, named by `--stage` (required; never guessed from the working tree). The deck stage is
PR 1a's: the copy deck and this tool land first, so it reads neither the pack, the hand-off nor the
pins file, and runs G-DECK, G-PROV, G-NAMED's deck part, G-HYGIENE and G-SCOPE. The full stage is
PR 1b's: it runs every gate, and any of the five files missing FAILs G-SCOPE.

Gates (each FAIL led by its name):
  G-DECK     the deck parses: the header line first, then one row per string with every field, a
             unique key, a known kind, status and provenance; a `merged` row cites a merged file, a
             `RULED` row names its ruling; each row's text, or its `quote`, is on its cited line,
             a text as a whole delimited span (never a cut prefix); every owner is a ticket key
             (a PROPOSED row's always).
  G-PROV     a predicted / estimated / approximate value says so in words ("≈" is not a word); a
             charge line holds "about" and, on screen, "predicted"; a row whose text says so is
             never `none` / `recorded`; none says the exchange published it (the provenance AC).
             Q-1 is the owner's: every charge line has a `words` row and a `symbol` twin holding
             the merged "≈" form, both PROPOSED; only a `symbol` row may hold "≈" without "about".
  G-NAMED    the deck header names `T` Scope's seven string groups T-1 ... T-7, and each has a
             row (T-5 with the `last_success_at` row); full stage: §8.2's keys per group are the
             deck's rows of that group, §9's name table has D04 A-16, A-19, A-20, and every key
             named there is a deck row.
  G-COMP     every component on `14` SCR-054's Components line has a §3.2 row, and each row's `15`
             cite is that component's heading.
  G-PROPS    every §4 prop is in D03's Props line for its component; every `23` / `22` Wire cite's
             line carries its field name.
  G-STATE    §6 has D02 §9's rows, in order, with the same frames.
  G-MOTION   §7's Duration, Easing and Reduced cells equal D04 §2's.
  G-SETTINGS §10's keys and defaults equal D02 §10's.
  G-EVENT    §12's events are the ones `14` SCR-054's Analytics line names.
  G-BUDGET   every BUD and COUNT anchor is computed from its source.
  G-AHEAD    every DATE and SPRINT anchor is computed from the calendar's constants and the ticket
             JSON.
  G-FILLED   no placeholder word in the pack, the hand-off or the deck.
  G-AROW     every hand-off §C row's Old text is on its cited line; A-n run without a gap; A-1
             sits on the last pointer line of `14` SCR-054 (found by content); CMP-126's `15`
             heading carries exactly two pending rows (E08-D06's base, E24-D03's extension).
  G-CITE     every cite in the pack and the hand-off is in range, on a non-blank line, and equal to
             the pins file's hash (a moved or edited line FAILs until re-pointed by content and
             `--repin-ruled` re-pins it); the SHA anchor is the pinned base.
  G-HYGIENE  no closing keyword, local path, URL or host, agent name, double-brace slot or
             public-text deny word in the stage's texts; no deny word in this tool or the pins
             file; no unknown anchor key.
  G-SCOPE    the stage's files are all present, and the diff against
             `git merge-base HEAD origin/main` touches only them.
  G-HANDOFF  the hand-off carries one `16` §11.4 block per changed component (CMP-186, CMP-126,
             CMP-127, CMP-227), with every line of the template, each `[x]` with its evidence or
             `[ ]` with `N/A — <reason>` or `PENDING — <reason>`.
  G-CHANGE   §15.3 carries `16` §11.5's mechanics (re-open #663, the §13.3 re-run, the
             "re-sync needed: <what changed>" cross-post), cited at its heading; §0 names the
             two-slice split and no one-PR form.

Usage (from the repo root):
  python3 -I docs/design/_tools/e24_d05_handoff_audit.py --stage deck --check
  python3 -I docs/design/_tools/e24_d05_handoff_audit.py --stage full --check
  python3 -I docs/design/_tools/e24_d05_handoff_audit.py --stage full --json
  python3 -I docs/design/_tools/e24_d05_handoff_audit.py --stage deck|full --self-test
  python3 -I docs/design/_tools/e24_d05_handoff_audit.py --stage full --repin-ruled
      (the pins file's only writer; refused in the deck stage or with the pack missing)
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

ROOT = Path(__file__).resolve().parents[3]
SPEC_REL = "docs/design/E24/E24-D05.md"
HAND_REL = "docs/design/E24/E24-D05-handoff.md"
DECK_REL = "docs/design/E24/E24-D05-copy-deck.jsonl"
TOOL_REL = "docs/design/_tools/e24_d05_handoff_audit.py"
PINS_REL = "docs/design/_tools/e24_d05_ruled_pins.txt"
OWN_PATHS = (SPEC_REL, HAND_REL, DECK_REL, TOOL_REL, PINS_REL)
DECK_PATHS = (DECK_REL, TOOL_REL)  # PR 1a
DECK, FULL = "deck", "full"
STAGES = (DECK, FULL)
BASE = "a7d659a5bee5d06a28950f324800f84dc3853e6f"  # origin/main; every parent merged, re-pinned by content
JSON_REL = "docs/plan/backlog/E24.json"
PATHS: dict[str, str] = {
    "02": "docs/plan/02-definition-of-ready-done.md",
    "14": "docs/plan/14-screens-catalogue.md",
    "15": "docs/plan/15-component-catalogue.md",
    "16": "docs/plan/16-design-system-brief.md",
    "22": "docs/plan/22-api-openapi.yaml",
    "23": "docs/plan/23-ws-protocol.md",
    "D02": "docs/design/E24/E24-D02.md",
    "D03": "docs/design/E24/E24-D03.md",
    "D04": "docs/design/E24/E24-D04.md",
    "CAL": "docs/plan/backlog/_tools/calendar_cv.py",
    "E08H": "docs/design/E08/E08-D06-handoff.md",
    "R01": "docs/design/research/e24-deriv-reading.md",
}
MERGED_KEYS = ("D02", "D03", "D04", "E08H")  # a `merged` deck row cites one of these
SOURCE = re.compile(r"(D0[234]|E08H|22):(\d+)")  # a deck row's source: a parent, or a `22` line
OWNER = re.compile(r"E\d\d-[DSTQXK]\d\d")  # a ticket key; `server` is the one other owner
HANDOFF_CMPS = ("CMP-186", "CMP-126", "CMP-127", "CMP-227")  # the contracts SCR-054 changes
SCR054_COMPONENTS = 1335  # `14`: SCR-054's Components line
SCR054_ANALYTICS = 1338  # `14`: SCR-054's Analytics line
SCOPE_GROUPS = (  # `T` Scope's seven named strings, pinned in the deck header
    "the partial-history chip",
    "the native-granularity note",
    "the imminent-funding warning",
    "the predicted-rate n/a state",
    "the backfill-retry state with last_success_at",
    "the zone acknowledgement dialog",
    "the unit column headers",
)
LAST_LOADED = "derivatives.retry.last_loaded"  # T-5's `last_success_at` row
D03_PROPS = {"4.1": 488, "4.2": 497, "4.3": 505}  # `D03`: the Props line per spec subsection
D02_EVENTS = 501  # `D02`: the line naming `methodology.opened`
CONSUMERS = ("E24-S01", "E24-S03", "E24-S05", "E24-S08")  # `T` Dependencies: what this unblocks
OWN_KEY = "E24-D05"
CITE = re.compile(r"`(\d\d|D0[234]|CAL|E08H|R01)`:(\d+(?:–\d+)?(?:, :\d+(?:–\d+)?)*)")
ANCHOR = re.compile(r"`?([^\s<|(`]+)`?<!--=([A-Z]+:[A-Za-z0-9.]+)-->")
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
KINDS = (
    "label",
    "value",
    "name",
    "chip",
    "dialog",
    "header",
    "announce",
    "message",
    "description",
    "tooltip",
    "reason",
)
STATUSES = ("merged", "RULED", "PROPOSED")
PROVENANCE = ("none", "recorded", "predicted", "estimated", "approximate")
WORDED_KINDS = ("label", "value", "name", "chip", "dialog", "header", "announce", "message")
PROV_WORDS = {
    "predicted": ("predicted",),
    "estimated": ("estimated", "estimate"),
    "approximate": ("about",),
}
SAYS = ("predicted", "estimate", "about", "≈")  # a row whose text holds one is not none / recorded
CHARGE = re.compile(r"\byou (?:pay|receive)\b")  # a charge, computed from the predicted rate
OPEN_DELIM = '`"“|·'  # what may stand before a text's span on its line (spaces skipped)
CLOSE_DELIM = '`"”|;'  # what may stand after it
CLAIMS = ("exchange-published", "published by bybit", "bybit's predicted")
FRAME_ID = re.compile(r"^[a-z0-9]+(?:-[a-z0-9]+)*$")


@dataclass(frozen=True)
class Texts:
    spec: str
    hand: str
    deck: str
    pins: str
    tool: str
    changed: list[str] | None
    memo: dict[str, str | None]
    stage: str = FULL
    present: tuple[str, ...] = OWN_PATHS


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
    text = show(t, BASE, PATHS[key])
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
    return [r for r in rows[2:]] if len(rows) > 2 else []


# ---------------------------------------------------------------------------- the deck


@dataclass(frozen=True)
class Deck:
    head: dict[str, object]
    rows: list[dict[str, str]]
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
        problems.append("the deck's first line is not the E24-D05 header")
        head = {}
    rows: list[dict[str, str]] = []
    for i, ln in enumerate(lines[1:], 2):
        try:
            row = json.loads(ln)
        except json.JSONDecodeError as e:
            problems.append(f"deck:{i} does not parse: {e}")
            continue
        if not isinstance(row, dict) or not all(isinstance(v, str) for v in row.values()):
            problems.append(f"deck:{i} is not an object of strings")
            continue
        rows.append(row)
    return Deck(head, rows, problems)


def deck_keys(t: Texts) -> set[str]:
    return {r.get("id", "") for r in parse_deck(t.deck).rows}


# ---------------------------------------------------------------------------- values


def find(t: Texts, key: str, rx: str) -> str:
    m = re.search(rx, at(t, key))
    if not m:
        raise LookupError(f"`{key}` no longer carries /{rx}/ at its base")
    return m[1]


def sprints(t: Texts) -> dict[str, int]:
    raw = show(t, BASE, JSON_REL)
    if raw is None:
        raise LookupError(f"{JSON_REL} does not resolve at the base")
    doc = json.loads(raw)
    items = doc if isinstance(doc, list) else doc.get("tickets", [])
    out: dict[str, int] = {}
    for it in items:
        m = re.fullmatch(r"Sprint (\d+)", str(it.get("sprint", "")))
        if m:
            out[str(it.get("key"))] = int(m[1])
    return out


def compute(t: Texts) -> dict[str, str]:
    v: dict[str, str] = {"SHA:BASE": BASE[:10]}
    deck = parse_deck(t.deck)
    v["COUNT:deck.rows"] = str(len(deck.rows))
    for s in STATUSES:
        v[f"COUNT:deck.{s.lower()}"] = str(sum(r.get("status") == s for r in deck.rows))
    rate = int(find(t, "14", r"target: (\d+) prints/s"))
    secs = int(find(t, "14", r"sustained for (\d+) s"))
    v.update({
        "BUD:bucket.ms": find(t, "14", r"coalesced into (\d+) ms buckets"),
        "BUD:script.ms": find(t, "14", r"exceed (\d+) ms scripting per frame"),
        "BUD:data.hz": find(t, "14", r"arrive at low frequency \(<=(\d+) Hz\)"),
        "BUD:cascade.rate": str(rate), "BUD:cascade.s": str(secs),
        "BUD:cascade.prints": str(rate * secs),
    })  # fmt: skip
    y, mo, d = (int(x) for x in re.findall(r"\d+", find(t, "CAL", r"SPRINT01_START = (.+)")))
    start = datetime.date(y, mo, d)
    days = int(find(t, "CAL", r"SPRINT_DAYS = (\d+)"))
    sp = sprints(t)
    if OWN_KEY not in sp or any(c not in sp for c in CONSUMERS):
        raise LookupError("the ticket JSON lacks a sprint for E24-D05 or a consumer")
    first = min(sp[c] for c in CONSUMERS)

    def s_start(n: int) -> datetime.date:
        return start + datetime.timedelta(days=(n - 1) * days)

    def s_end(n: int) -> datetime.date:
        return s_start(n) + datetime.timedelta(days=days - 1)

    v["DATE:s11.end"] = s_end(sp[OWN_KEY]).isoformat()
    v["DATE:s13.start"] = s_start(first).isoformat()
    v["DATE:s10.end"] = s_end(first - 3).isoformat()
    v["SPRINT:own"], v["SPRINT:first"] = str(sp[OWN_KEY]), str(first)
    v["SPRINT:ahead"] = str(first - 3)  # `02`: Done >= 2 sprints before the first story starts
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


def whole_span(text: str, ln: str) -> bool:
    """`text` stands on `ln` as a whole span: a delimiter before and after it (spaces skipped)."""
    for m in re.finditer(re.escape(text), ln):
        before, after = ln[: m.start()].rstrip(), ln[m.end() :].lstrip()
        if (not before or before[-1] in OPEN_DELIM) and (not after or after[0] in CLOSE_DELIM):
            return True
    return False


def g_deck(t: Texts, vals: dict[str, str]) -> list[str]:
    deck = parse_deck(t.deck)
    bad = list(deck.problems)
    if deck.head and deck.head.get("base") != BASE[:10]:
        bad.append("the deck's header names another base than the tool's")
    seen: set[str] = set()
    for r in deck.rows:
        k = r.get("id", "?")
        missing = [f for f in FIELDS if not r.get(f)]
        if missing:
            bad.append(f"{k}: no {', '.join(missing)}")
            continue
        if not re.fullmatch(r"derivatives\.[a-z0-9_.]+", k):
            bad.append(f"{k}: not a `derivatives.*` key")
        if k in seen:
            bad.append(f"{k}: a repeated key")
        seen.add(k)
        if r["kind"] not in KINDS:
            bad.append(f"{k}: kind {r['kind']!r} is not one of the deck's kinds")
        if r["status"] not in STATUSES:
            bad.append(f"{k}: status {r['status']!r} is not merged, RULED or PROPOSED")
        if r["provenance"] not in PROVENANCE:
            bad.append(f"{k}: provenance {r['provenance']!r} is unknown")
        if r["screen"] != "SCR-054":
            bad.append(f"{k}: screen {r['screen']!r} is not SCR-054")
        if not re.fullmatch(r"E24-[SQ]0\d", r.get("consumer", "")):
            bad.append(f"{k}: no consuming story")
        if not OWNER.fullmatch(r["owner"]) and (
            r["status"] == "PROPOSED" or r["owner"] != "server"
        ):
            bad.append(f"{k}: owner {r['owner']!r} is not a ticket key")
        m = SOURCE.fullmatch(r["source"])
        if not m:
            bad.append(f"{k}: source {r['source']!r} is not D02 / D03 / D04 / E08H / 22 and a line")
            continue
        if r["status"] == "merged" and m[1] not in MERGED_KEYS:
            bad.append(f"{k}: a merged row cites {m[1]}, which is not merged")
        if r["status"] == "RULED" and not r.get("ruling"):
            bad.append(f"{k}: a RULED row names no ruling")
        want, ln = r.get("quote") or r["text"], line(t, m[1], int(m[2]))
        if want not in ln:
            bad.append(f"{k}: {want[:40]!r} is not on {r['source']} at its ref")
        elif not r.get("quote") and not whole_span(want, ln):
            bad.append(f"{k}: the text is part of a span on {r['source']}, not the whole span")
    return bad


def q1_problems(r: dict[str, str], by: dict[str, dict[str, str]]) -> list[str]:
    """Q-1 is the owner's: a displayed charge line carries both readings, each PROPOSED."""
    k, q1, text = r.get("id", "?"), r.get("q1"), r.get("text", "")
    shown = CHARGE.search(text.lower()) and r.get("kind") != "announce"
    if q1 is None:
        return [f"{k}: a displayed charge line with no Q-1 reading"] if shown else []
    bad = [] if r.get("status") == "PROPOSED" else [f"{k}: a Q-1 reading that is not PROPOSED"]
    if q1 == "symbol":
        twin = by.get(k.removesuffix(".q1_symbol"), {})
        if twin.get("q1") != "words" or twin.get("quote") != text:
            bad.append(f"{k}: a symbol reading with no words twin quoting it")
    elif q1 != "words" or f"{k}.q1_symbol" not in by:
        bad.append(f"{k}: a words reading with no symbol twin")
    return bad


def g_prov(t: Texts, vals: dict[str, str]) -> list[str]:
    bad = []
    rows = parse_deck(t.deck).rows
    by = {r.get("id", ""): r for r in rows}
    for r in rows:
        prov, text, k = r.get("provenance", ""), r.get("text", ""), r.get("id", "?")
        low = text.lower()
        bad += q1_problems(r, by)
        if r.get("q1") == "symbol":
            continue  # the merged "≈" reading, held PROPOSED until the owner answers Q-1
        if CHARGE.search(low):
            if prov not in ("predicted", "approximate") or "about" not in low:
                bad.append(f"{k}: a charge line that is not predicted / approximate with 'about'")
            elif r.get("kind") != "announce" and (prov != "predicted" or "predicted" not in low):
                bad.append(f"{k}: a displayed charge line that does not say 'predicted'")
        words = PROV_WORDS.get(prov)
        if not words:
            said = [w for w in SAYS if w in low]
            if said:
                bad.append(f"{k}: a {prov} row whose text says {said[0]!r}")
            continue
        if r.get("kind") in WORDED_KINDS and not any(w in low for w in words):
            bad.append(f"{k}: a {prov} {r.get('kind')} that does not say so ({' / '.join(words)})")
        for c in CLAIMS:
            if c in text.lower():
                bad.append(f"{k}: a {prov} row that says {c!r}")
    return bad


def g_named(t: Texts, vals: dict[str, str]) -> list[str]:
    deck = parse_deck(t.deck)
    ids = [f"T-{i}" for i in range(1, 8)]
    head = deck.head.get("scope_groups") if deck.head else None
    bad = (
        []
        if head == dict(zip(ids, SCOPE_GROUPS, strict=True))
        else ["the deck header does not name `T` Scope's seven string groups T-1 ... T-7"]
    )
    group: dict[str, set[str]] = {i: set() for i in ids}
    for d in deck.rows:
        if d.get("scope") is not None:
            if d["scope"] not in group:
                bad.append(f"{d.get('key')}: scope {d['scope']!r} is not T-1 ... T-7")
            else:
                group[d["scope"]].add(d.get("id", ""))
    bad += [f"{i} ({SCOPE_GROUPS[n]}) has no deck row" for n, i in enumerate(ids) if not group[i]]
    if LAST_LOADED not in group["T-5"]:
        bad.append(f"T-5 lacks `{LAST_LOADED}`, the `last_success_at` row")
    if t.stage == DECK:
        return bad
    rows = table_rows(section(t.spec, "### 8.2"), "T-")
    if [r[0] for r in rows] != ids:
        bad.append(f"§8.2's rows are {[r[0] for r in rows]}, not T-1 ... T-7")
    for r in rows:
        named = set(re.findall(r"`(derivatives\.[a-z0-9_.]+)`", r[-1]))
        if r[0] in group and named != group[r[0]]:
            bad.append(f"{r[0]}: §8.2's keys are not the deck's {r[0]} rows")
    a_rows = table_rows(section(t.spec, "## 9."), "A-")
    if not {"A-16", "A-19", "A-20"} <= {r[0] for r in a_rows}:
        bad.append(f"§9's name table has {[r[0] for r in a_rows]}, not D04 A-16, A-19, A-20")
    keys = deck_keys(t)
    for r in rows + a_rows:
        named_l = re.findall(r"`(derivatives\.[a-z0-9_.]+)`", r[-1])
        if not named_l:
            bad.append(f"{r[0]}: no deck key")
        bad += [f"{r[0]}: `{n}` is not a deck row" for n in named_l if n not in keys]
    return bad


def g_comp(t: Texts, vals: dict[str, str]) -> list[str]:
    need = re.findall(r"CMP-\d{3}", line(t, "14", SCR054_COMPONENTS))
    rows = {r[0]: r for r in table_rows(section(t.spec, "### 3.2"), "CMP-")}
    bad = [] if need else ["`14` SCR-054's Components line names no component"]
    bad += [f"{c} is on `14` SCR-054's Components line but has no §3.2 row" for c in need
            if c not in rows]  # fmt: skip
    for c, r in rows.items():
        m = re.fullmatch(r"`15`:(\d+)", r[2]) if len(r) > 2 else None
        if not m:
            bad.append(f"{c}: no `15` heading cite")
        elif not line(t, "15", int(m[1])).startswith(f"### {c} "):
            bad.append(f"{c}: `15`:{m[1]} is not its heading")
    return bad


def g_props(t: Texts, vals: dict[str, str]) -> list[str]:
    bad = []
    for sub, n in D03_PROPS.items():
        props_line = line(t, "D03", n)
        rows = table_rows(section(t.spec, f"### {sub}"), "`")
        if not rows:
            bad.append(f"§{sub} has no prop rows")
        for r in rows:
            prop = r[0].strip("`")
            if not re.search(r"[`{ ]" + re.escape(prop) + r"[`:?]", props_line):
                bad.append(f"§{sub}: `{prop}` is not in D03's Props line (`D03`:{n})")
            for key, ln_no, field in re.findall(r"`(2[23])`:(\d+) `([a-z_]+)`", r[-1]):
                ln = line(t, key, int(ln_no))
                ok = f'"{field}"' in ln if key == "23" else ln.strip().startswith(f"{field}:")
                if not ok:
                    bad.append(f"§{sub} `{prop}`: `{key}`:{ln_no} does not carry `{field}`")
    return bad


def frames(cell: str) -> list[str]:
    """The frame ids a §9 cell names; a component's state word after its CMP id is not one."""
    cell = re.sub(r"CMP-\d{3} `[^`]+`", "", cell)
    return [f for f in re.findall(r"`([^`]+)`", cell) if FRAME_ID.match(f)]


def g_state(t: Texts, vals: dict[str, str]) -> list[str]:
    theirs = first_table(section(at(t, "D02"), "## 9."))
    ours = table_rows(section(t.spec, "## 6."), "")
    ours = [r for r in ours if r and r[0].isdigit()]
    bad = []
    if len(ours) != len(theirs) or not theirs:
        bad.append(f"§6 has {len(ours)} rows; D02 §9 has {len(theirs)}")
    for i, (o, d) in enumerate(zip(ours, theirs, strict=False), 1):
        if o[0] != str(i):
            bad.append(f"§6 row {o[0]} is out of order")
        if len(o) < 3 or frames(o[2]) != frames(d[1]):
            bad.append(f"§6 row {i}: frames differ from D02 §9's {frames(d[1])}")
    return bad


def g_motion(t: Texts, vals: dict[str, str]) -> list[str]:
    theirs = {r[0]: r for r in table_rows(section(at(t, "D04"), "## 2."), "M-0")}
    ours = table_rows(section(t.spec, "## 7."), "M-0")
    bad = []
    if [r[0] for r in ours] != sorted(theirs):
        bad.append(f"§7's rows are {[r[0] for r in ours]}, not D04 §2's {sorted(theirs)}")
    for r in ours:
        d = theirs.get(r[0])
        if d is None or len(r) != 5 or len(d) != 9:
            continue
        for mine, their, what in ((r[2], d[3], "Duration"), (r[3], d[4], "Easing"),
                                  (r[4], d[5], "Reduced motion")):  # fmt: skip
            if mine != their:
                bad.append(f"{r[0]}: {what} {mine!r} is not D04's {their!r}")
    return bad


def g_settings(t: Texts, vals: dict[str, str]) -> list[str]:
    theirs = [(r[0], r[2]) for r in first_table(section(at(t, "D02"), "## 10."))]
    ours = [(r[0], r[1]) for r in table_rows(section(t.spec, "## 10."), "`deriv.")]
    if not theirs or ours != theirs:
        diff = [f"{a}: {b!r}" for a, b in ours if (a, b) not in theirs]
        return [f"§10 differs from D02 §10 ({'; '.join(diff) or 'rows or order'})"]
    return []


def g_event(t: Texts, vals: dict[str, str]) -> list[str]:
    theirs = set(re.findall(r"`([a-z_]+\.[a-z_]+)`", line(t, "14", SCR054_ANALYTICS)))
    ours = {r[0].strip("`") for r in table_rows(section(t.spec, "## 12."), "`")}
    bad = [] if theirs else ["`14` SCR-054's Analytics line names no event"]
    if ours != theirs:
        bad.append(f"§12's events {sorted(ours)} are not `14`'s {sorted(theirs)}")
    if "methodology.opened" not in line(t, "D02", D02_EVENTS):
        bad.append("`D02` no longer names `methodology.opened` where §12 says")
    return bad


def g_budget(t: Texts, vals: dict[str, str]) -> list[str]:
    return anchor_problems(t, vals, ("BUD:", "COUNT:"))


def g_ahead(t: Texts, vals: dict[str, str]) -> list[str]:
    return anchor_problems(t, vals, ("DATE:", "SPRINT:"))


def g_filled(t: Texts, vals: dict[str, str]) -> list[str]:
    bad = []
    for label, text in (("spec", t.spec), ("hand-off", t.hand), ("deck", t.deck)):
        for i, ln in enumerate(text.split("\n"), 1):
            if PLACEHOLDER.search(ln):
                bad.append(f"{label}:{i} carries a placeholder")
    return bad


def g_arow(t: Texts, vals: dict[str, str]) -> list[str]:
    rows = table_rows(section(t.hand, "## §C"), "A-")
    bad = []
    if [r[0] for r in rows] != [f"A-{i}" for i in range(1, len(rows) + 1)] or not rows:
        bad.append(f"§C's rows are {[r[0] for r in rows]}: a gap or none")
    for r in rows:
        m = re.match(r"`(\d\d|D0[234]|E08H)`:(\d+)", r[1])
        if not m:
            bad.append(f"{r[0]}: no file and line")
            continue
        old = r[2]
        if old != "—" and old.strip('"') not in line(t, m[1], int(m[2])):
            bad.append(f"{r[0]}: the Old text is not on `{m[1]}`:{m[2]} at the base")
    ls = at(t, "14").split("\n")
    top = next((i for i, ln in enumerate(ls) if ln.startswith("### SCR-054 ")), len(ls))
    end = next((i for i in range(top + 1, len(ls)) if ls[i].startswith("### ")), len(ls))
    last = max((i + 1 for i in range(top, end) if ls[i].startswith("- **")), default=0)
    a1 = [c for c in rows if c[0] == "A-1"]
    if not a1 or not a1[0][1].startswith(f"`14`:{last},"):
        bad.append(f"A-1 is not on the last pointer line of `14` SCR-054 (`14`:{last})")
    head = next((i for i, ln in enumerate(at(t, "15").split("\n"), 1)
                 if ln.startswith("### CMP-126 ")), 0)  # fmt: skip
    pend = [c for c in rows if c[1].startswith(f"`15`:{head}") and "pending" in c[3]]
    owners = sorted(o for c in pend for o in ("E08-D06", "E24-D03") if o in c[-1])
    if owners != ["E08-D06", "E24-D03"] or len(pend) != 2:
        bad.append(f"CMP-126 (`15`:{head}) lacks its two pending rows, E08-D06's and E24-D03's")
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


def g_hygiene(t: Texts, vals: dict[str, str]) -> list[str]:
    bad = []
    checks = ((CLOSING, "a closing keyword (the closing PR alone closes #663)"),
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


def owned(stage: str) -> tuple[str, ...]:
    return DECK_PATHS if stage == DECK else OWN_PATHS


def g_scope(t: Texts, vals: dict[str, str]) -> list[str]:
    own = owned(t.stage)
    bad = [f"{p} is missing ({t.stage} stage)" for p in own if p not in t.present]
    if t.changed is None:
        return [*bad, "cannot list the changed paths (git failed)"]
    return bad + [f"{p} is touched; the {t.stage} stage owns {', '.join(own)}"
                  for p in t.changed if p not in own]  # fmt: skip


CHANGE_WORDS = ("re-open #663", "§13.3", "re-sync needed: what changed")


def g_change(t: Texts, vals: dict[str, str]) -> list[str]:
    sec = section(t.spec, "### 15.3")
    bad = [f"§15.3 does not say {w!r}" for w in CHANGE_WORDS if w not in sec]
    cited = [a for k, a, _ in cites(sec) if k == "16"]
    if not any(line(t, "16", a).startswith("### 11.5 ") for a in cited):
        bad.append("§15.3 does not cite `16` §11.5 at its heading")
    zero = section(t.spec, "## 0.")
    if (
        "PR 1a" not in zero
        or "PR 1b" not in zero
        or re.search(r"\bone (?:docs-only )?PR\b", zero, re.IGNORECASE)
    ):
        bad.append("§0 does not name the two-slice split (PR 1a, PR 1b) alone")
    return bad


def template_labels(t: Texts) -> list[str]:
    """The line labels of `16` §11.4's template block, in order."""
    block = section(at(t, "16"), "### 11.4")
    return re.findall(r"^- \[ \] \*\*([^*]+)\*\*", block, re.MULTILINE)


def g_handoff(t: Texts, vals: dict[str, str]) -> list[str]:
    labels = template_labels(t)
    bad = [] if labels else ["`16` §11.4 carries no template lines"]
    heads = {r[0]: r[2] for r in table_rows(section(t.spec, "### 3.2"), "CMP-")}
    for c in HANDOFF_CMPS:
        m = re.fullmatch(r"`15`:(\d+)", heads.get(c, ""))
        name = re.sub(r" \(.*\)$", "", line(t, "15", int(m[1])).removeprefix("### ")) if m else c
        block = section(t.hand, f"## Handoff checklist — {name} (E24-D05, #663)")
        items = [ln for ln in block.split("\n") if ln.startswith("- [")]
        got = [re.sub(r"^- \[[x ]\] \*\*([^*]+)\*\*.*", r"\1", ln) for ln in items]
        if not block:
            bad.append(f"{c}: no `16` §11.4 block headed {name!r}")
        elif got != labels:
            bad.append(f"{c}: the block's lines are not `16` §11.4's ({len(got)} of {len(labels)})")
        for ln in items:
            if ln.startswith("- [x] ") and not re.search(r"\*\* [^—]*— \S.{2,}", ln):
                bad.append(f"{c}: a ticked line with no evidence: {ln[:50]!r}")
            elif ln.startswith("- [ ] ") and not re.search(r"(?:N/A|PENDING) — \S.{2,}", ln):
                bad.append(f"{c}: an open line with no N/A or PENDING reason: {ln[:50]!r}")
    return bad


GATES: dict[str, Callable[[Texts, dict[str, str]], list[str]]] = {
    "G-DECK": g_deck, "G-PROV": g_prov, "G-NAMED": g_named, "G-COMP": g_comp,
    "G-PROPS": g_props, "G-STATE": g_state, "G-MOTION": g_motion, "G-SETTINGS": g_settings,
    "G-EVENT": g_event, "G-BUDGET": g_budget, "G-AHEAD": g_ahead, "G-FILLED": g_filled,
    "G-AROW": g_arow, "G-CITE": g_cite, "G-HYGIENE": g_hygiene, "G-SCOPE": g_scope,
    "G-HANDOFF": g_handoff, "G-CHANGE": g_change,
}  # fmt: skip
DECK_GATES = ("G-DECK", "G-PROV", "G-NAMED", "G-HYGIENE", "G-SCOPE")


def gates_of(stage: str) -> list[str]:
    return [g for g in GATES if stage == FULL or g in DECK_GATES]


def audit(t: Texts) -> list[tuple[str, str]]:
    missing = [p for p in owned(t.stage) if p not in t.present]
    if missing:
        return [("G-SCOPE", m) for m in g_scope(t, {})]
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
    """The deck stage never reads the pack, the hand-off or the pins file, present or not."""
    full = stage == FULL
    return Texts(
        read(SPEC_REL) if full else "", read(HAND_REL) if full else "", read(DECK_REL),
        read(PINS_REL) if full else "", read(TOOL_REL), changed_paths(), {}, stage,
        tuple(p for p in owned(stage) if (ROOT / p).exists()),
    )  # fmt: skip


def sub(field: str, old: str, new: str) -> Callable[[Texts], Texts]:
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


def set_cell(row: str, col: int, value: str) -> Callable[[Texts], Texts]:
    def f(t: Texts) -> Texts:
        ls = t.spec.split("\n")
        i = next(k for k, ln in enumerate(ls) if ln.startswith(f"| {row} "))
        cs = cells(ls[i])
        cs[col] = value
        ls[i] = "| " + " | ".join(cs) + " |"
        return replace(t, spec="\n".join(ls))

    return f


def deck_set(key: str, **fields: str) -> Callable[[Texts], Texts]:
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


Mutation = Callable[[Texts], Texts]
BOTH, FULL_ONLY = (DECK, FULL), (FULL,)


def absent(rel: str) -> Mutation:
    return lambda t: replace(t, present=tuple(p for p in t.present if p != rel))


MUTATIONS: tuple[tuple[str, str, Mutation, tuple[str, ...]], ...] = (
    ("G-DECK", "blank a deck row's owner", deck_set("derivatives.group.label", owner=""), BOTH),
    ("G-PROV", "mark a row predicted that does not say so", deck_set("derivatives.oi.forming", provenance="predicted"), BOTH),
    ("G-NAMED", "name a key the deck lacks in §8.2", sub("spec", "`derivatives.oi.native_granularity`", "`derivatives.oi.native_grain`"), FULL_ONLY),
    ("G-COMP", "point CMP-126's heading cite at CMP-127's", set_cell("CMP-126", 2, "`15`:1574"), FULL_ONLY),
    ("G-PROPS", "add a prop D03 does not have", sub("spec", "| `anchor`          |", "| `anchorAt`        |"), FULL_ONLY),
    ("G-STATE", "drop a frame from §6's first row", sub("spec", "`loading`, `backfilling`", "`loading`"), FULL_ONLY),
    ("G-MOTION", "give M-05 the fast token", set_cell("M-05", 2, "`motion.duration.fast`"), FULL_ONLY),
    ("G-SETTINGS", "change a default", set_cell("`deriv.liq.mode`", 1, "`heatmap`"), FULL_ONLY),
    ("G-EVENT", "rename an event", set_cell("`liquidation.print_clicked`", 0, "`liquidation.row_clicked`"), FULL_ONLY),
    ("G-BUDGET", "type a wrong bucket budget", sub("spec", "250<!--=BUD:bucket.ms-->", "500<!--=BUD:bucket.ms-->"), FULL_ONLY),
    ("G-AHEAD", "type a wrong date", sub("spec", "2026-12-10<!--=DATE:s11.end-->", "2026-12-11<!--=DATE:s11.end-->"), FULL_ONLY),
    ("G-FILLED", "write a placeholder", sub("spec", "The table is empty until the READY dry run.", "The table is TBD."), FULL_ONLY),
    ("G-AROW", "change an A-row's Old text", sub("hand", '"Cluster (×N)"', '"Cluster (count)"'), FULL_ONLY),
    ("G-CITE", "re-point a `D02` cite to an unpinned line", sub("spec", "The order is D02's (`D02`:106).", "The order is D02's (`D02`:107)."), FULL_ONLY),
    ("G-HYGIENE", "write a closing keyword against #663", sub("spec", "carries the closing line for #663.", "carries the closing line. Closes #663."), FULL_ONLY),
    ("G-SCOPE", "touch `14` in the diff", lambda t: replace(t, changed=[*owned(t.stage), PATHS["14"]]), BOTH),
    ("G-DECK", "give a row a text not on its line", deck_set("derivatives.oi.forming", text="forming span"), BOTH),
    ("G-PROV", "make an approximate row claim publication", deck_set("derivatives.announce.cascade.shorts", provenance="approximate", text="Liquidations: about 1,240 per second, published by Bybit."), BOTH),
    ("G-HYGIENE", "put a deny word into the tool's own text", lambda t: replace(t, tool=t.tool + "\n# " + DENY[6] + "\n"), BOTH),
    ("G-HANDOFF", "drop CMP-127's keyboard line", sub("hand", "- [x] **Keyboard table** — D04 A-02", "D04 A-02"), FULL_ONLY),
    ("G-HANDOFF", "leave an N/A without a reason", sub("hand", "N/A — static chips", "N/A —"), FULL_ONLY),
    ("G-DECK", "cut a merged text to a prefix still on its line", deck_set("derivatives.zones.dialog.callout", text="This is an estimate"), BOTH),
    ("G-PROV", "set a charge line's provenance to none", deck_set("derivatives.countdown.imminent.pay", provenance="none"), BOTH),
    ("G-AHEAD", "drift a sprint number", sub("spec", "Sprint 13<!--=SPRINT:first-->", "Sprint 12<!--=SPRINT:first-->"), FULL_ONLY),
    ("G-DECK", "give a PROPOSED row a free-word owner", deck_set("derivatives.name.oi.menu", owner="design"), BOTH),
    ("G-PROPS", "rename a `22` Wire field", sub("spec", "`22`:20716 `source`", "`22`:20716 `origin`"), FULL_ONLY),
    ("G-PROV", "write ≈ for 'about' in a charge line", deck_set("derivatives.countdown.imminent.pay", text="Funding settles in 00:04:12 — you pay ≈ 12.40 USDT, predicted, on Demo 1 · DEMO"), BOTH),
    ("G-PROV", "relabel Q-1's symbol reading as words", deck_set("derivatives.countdown.imminent.pay.q1_symbol", q1="words"), BOTH),
    ("G-PROV", "detach a charge line's symbol twin", lambda t: replace(t, deck=t.deck.replace("imminent.live_line.q1_symbol", "imminent.live_line.q1_sym", 1)), BOTH),
    ("G-NAMED", "drop T-2's only scope row", deck_set("derivatives.oi.native_granularity", scope="T-9"), BOTH),
    ("G-NAMED", "drop a group from the deck header", lambda t: replace(t, deck=t.deck.replace('"T-7": "the unit column headers"', '"T-7": "the column headers"', 1)), BOTH),
    ("G-NAMED", "list a symbol twin under T-3 in §8.2 that the deck lacks", sub("spec", "`derivatives.countdown.imminent.pay.q1_symbol`", "`derivatives.countdown.imminent.no_position.q1_symbol`"), FULL_ONLY),
    ("G-AROW", "anchor A-1 on the Components line, not the last pointer", sub("hand", "| `14`:1343, a line after |", "| `14`:1335, a line after |"), FULL_ONLY),
    ("G-AROW", "drop E24-D03's pending CMP-126 row", sub("hand", "pending: E24-D03's `predicted: boolean`", "E24-D03's `predicted: boolean`"), FULL_ONLY),
    ("G-CHANGE", "drop the re-sync cross-post line", sub("spec", '"re-sync needed: what changed"', '"what changed"'), FULL_ONLY),
    ("G-CHANGE", "bring back a single-PR form in §0", sub("spec", "**PR form (BQ-19, ruled).** Two slices", "**PR form (BQ-19, ruled).** One docs-only PR, two slices"), FULL_ONLY),
    ("G-SCOPE", "the pins file missing in the full stage", absent(PINS_REL), FULL_ONLY),
    ("G-SCOPE", "the deck missing", absent(DECK_REL), BOTH),
    ("G-SCOPE", "a pack file in the deck stage's diff", lambda t: replace(t, changed=[*DECK_PATHS, SPEC_REL]), (DECK,)),
    ("G-HYGIENE", "a deny word in the deck", deck_set("derivatives.oi.forming", where="forming " + DENY[2]), BOTH),
)  # fmt: skip


def repin_refusal(t: Texts) -> str | None:
    """Why --repin-ruled must not write: the deck stage, or the pack missing."""
    if t.stage != FULL:
        return "the deck stage has no pack to pin"
    if SPEC_REL not in t.present or not t.spec:
        return f"{SPEC_REL} is missing: no pack to pin"
    return None


def selftest(stage: str) -> tuple[bool, list[str]]:
    loaded = load(stage)
    base = replace(loaded, changed=list(owned(stage)))
    before = (loaded.spec, loaded.hand, loaded.deck, loaded.pins)
    found = audit(base)
    out = [f"self-test: {stage} stage, baseline {len(found)} FAIL"]
    out += [f"  baseline {g}: {m}" for g, m in found]
    ok = not found
    for i, (gate, what, fn, stages) in enumerate(MUTATIONS, 1):
        if stage not in stages:
            continue
        gates = sorted({g for g, _ in audit(fn(base))})
        good = gates == [gate]
        ok &= good
        out.append(
            f"{'ok  ' if good else 'FAIL'} MU-{i} {gate}: {what} -> {', '.join(gates) or 'none'}"
        )
    hit = {m[0] for m in MUTATIONS if stage in m[3]}
    missing = [g for g in gates_of(stage) if g not in hit]
    ok &= not missing
    if missing:
        out.append(f"FAIL no mutation for {', '.join(missing)}")
    probes = [("P-1 --repin-ruled refuses in the deck stage", repin_refusal(replace(base, stage=DECK)) is not None),
              ("P-2 --repin-ruled refuses with the pack missing", repin_refusal(replace(base, stage=FULL, present=(), spec="")) is not None)]  # fmt: skip
    for name, good in probes:
        ok &= good
        out.append(f"{'ok  ' if good else 'FAIL'} {name}")
    now = load(stage)
    restored = (now.spec, now.hand, now.deck, now.pins) == before
    ok &= restored
    n = sum(stage in m[3] for m in MUTATIONS)
    out.append(f"self-test: {n} mutations, texts restored: {'yes' if restored else 'NO'}")
    out.append(f"self-test: {'PASS' if ok else 'FAIL'}")
    return ok, out


def main(argv: list[str]) -> int:
    ap = argparse.ArgumentParser(description="E24-D05 hand-off pack audit")
    ap.add_argument("--stage", choices=STAGES, required=True)
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
        why = repin_refusal(t)
        hashes, bad = cite_hashes(t) if why is None else ({}, [why])
        if bad:
            print(f"refused: {bad[0]}")
            return 1
        head = "# E24-D05 cite pins: the cite, a hash of its cited line(s) at its ref. Written by --repin-ruled only.\n"
        body = "".join(f"{k}\t{h}\n" for k, h in hashes.items())
        (ROOT / PINS_REL).write_text(head + body, encoding="utf-8")
        print(f"wrote {PINS_REL} ({len(hashes)} cites)")
        return 0
    found = audit(t)
    if a.json:
        doc = {"base": BASE, "stage": t.stage, "values": compute(t),
               "findings": [{"gate": g, "msg": m} for g, m in found]}  # fmt: skip
        print(json.dumps(doc, ensure_ascii=False, indent=2))
    else:
        for gate, msg in found:
            print(f"FAIL {gate}: {msg}")
        n = len(cite_hashes(t)[0]) if t.stage == FULL else 0
        rows = len(parse_deck(t.deck).rows)
        print(
            f"{len(found)} FAIL ({len(gates_of(t.stage))} gates, {t.stage} stage; {n} cites; {rows} deck rows)"
        )
    return 1 if found else 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
