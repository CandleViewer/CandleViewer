#!/usr/bin/env python3
"""E37-D05 (#950) audit: the design hand-off package for SCR-082 and the node-graph components.

Standalone, offline, stdlib only; it runs no repo code and is run with `python3 -I`. It reads the
pack (spec, hand-off, the copy deck's JSON Lines twin) and the pins file from the working tree, and every
cited file AS TEXT with `git show`: the plan docs, E37-D02, `ports.ts`, the keyboard core's
`copy.ts` and the E36-D05 deck at the pinned base (`BASE`); E37-D03 at #5448's head (`D03_REF`)
and E37-D04 at #5495's head (`D04_REF`) until they merge.
Default-deny: a gate that cannot read its input FAILs.

Two modes, chosen by what the working tree holds. With the spec, the hand-off or the pins file
present the tool runs every gate (full mode; a missing one of the three FAILs). With all three
absent it runs the deck gates alone (deck-only mode, the deck-first PR): G-DECK reads the rows,
the `cited` list and the slot samples from the JSON Lines twin itself; G-MATRIX, G-COVER (its
verbatim, copy.ts and E36-D05 parts), G-RAW, G-FROZEN, G-HYGIENE, G-SCOPE and G-STATUS read the
same rows; a row is a frozen (section 9) row when its status is FROZEN or its context carries the
PROPOSED freeze. The self-test runs the mutations of the mode it is in.

Gates (each FAIL led by its name):
  G-FRAME   every `14` SCR-082 state and indicator word has exactly one frame row; every row's
            frame is a D02 frame on its cited line; every D02 frame is indexed once.
  G-SHEET   every component of the set has a sheet with Props, States, Tokens, Name and Owner
            story, a hand-off contract row and a Storybook row; every token a sheet names is in
            the token map; every hand-off A-row's Old text or anchor stands once in its file.
  G-DECK    the JSON Lines twin (one row per line) equals the deck tables and its slot samples
            section 8.4; every row has every field and no other; keys, kinds and statuses are
            from their sets; each cap is its kind's, measured with the slot samples.
  G-MATRIX  the 36 `rules.graph.connect.*` rows equal ports.ts's PORT_COMPAT at the base.
  G-COVER   every quoted string of D02 sections 4, 14, 15, D04's script and announcements and
            the ticket's labels is covered; every copy.ts export is a row's source; a row sourced
            from a D02, D04 or `14` line is verbatim there; every E36-D05 key cited exists.
  G-RAW     no raw hex in the pack; a px value only beside a D02, D03 or D04 cite.
  G-MOTION  section 5 equals E37-D03's motion rows, their reduce cells and lines.
  G-FROZEN  every section 9 row is FROZEN, verbatim at its owner, its freeze PROPOSED, and free of
            the words that soften (undo, just, simply, anytime).
  G-EVENT   section 10 lists the six events in order, each named on its cited line, no property
            carrying an account or rule content.
  G-CITE    every cite in range and on a non-blank line at its ref, its content equal to the
            pins file's hash; the SHA anchors are the pinned refs.
  G-HYGIENE no closing keyword, local path, URL, agent name, double-brace slot or deny word in
            the pack, this tool or the pins file; no unknown anchor.
  G-SCOPE   the diff against `git merge-base HEAD origin/main` touches only the five files (the
            deck and this tool in deck-only mode).
  G-STATUS  a deck row whose source line marks its string PROPOSED stays PROPOSED; section 3.1
            keeps the `application` role PROPOSED until E37-Q05's run, never DECIDED.
  G-CHECKLIST section 13 holds DA-1 ... DA-17 in order: DA-1 ... DA-7 cite `14`'s seven boxes,
            DA-8 ... DA-17 cite D04's SC-1 ... SC-10, each on the line that starts with its SC id.

Usage (from the repo root):
  python3 -I docs/design/_tools/e37_d05_handoff_audit.py --check       (exit 1 on any FAIL;
      the first line names the mode)
  python3 -I docs/design/_tools/e37_d05_handoff_audit.py --json
  python3 -I docs/design/_tools/e37_d05_handoff_audit.py --self-test
  python3 -I docs/design/_tools/e37_d05_handoff_audit.py --repin-ruled
      (the pins file's only writer)
"""

from __future__ import annotations

import argparse
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
SPEC_REL = "docs/design/E37/E37-D05.md"
HAND_REL = "docs/design/E37/E37-D05-handoff.md"
DECK_REL = "docs/design/E37/E37-D05-copy-deck.jsonl"
TOOL_REL = "docs/design/_tools/e37_d05_handoff_audit.py"
PINS_REL = "docs/design/_tools/e37_d05_ruled_pins.txt"
OWN_PATHS = (SPEC_REL, HAND_REL, DECK_REL, TOOL_REL, PINS_REL)
DECK_PATHS = (DECK_REL, TOOL_REL)
PACK_PATHS = (SPEC_REL, HAND_REL, PINS_REL)  # all absent: deck-only mode
BASE = "1c4f51bb5dbeb167627749a04d6ad426e26bf5e6"  # origin/main, re-pinned (BQ-02)
D03_REF = "fa8121d1b9601727a77d9c5013f4c5bbcfb87951"  # #5448's head (E37-D03 PR 2)
D04_REF = (
    "19e002c0799086a77f7b007a1facbbd58928d3d4"  # #5495's head (E37-D04, its lens fold)
)
PATHS: dict[str, str] = {
    "14": "docs/plan/14-screens-catalogue.md",
    "15": "docs/plan/15-component-catalogue.md",
    "D02": "docs/design/E37/E37-D02.md",
    "D03": "docs/design/E37/E37-D03.md",
    "D04": "docs/design/E37/E37-D04.md",
    "PORTS": "packages/rule-graph/src/ports.ts",
    "COPY": "apps/web/src/features/rule-builder-graph/a11y/copy.ts",
    "E36D05": "docs/design/E36/E36-D05.md",
    "E36DECK": "docs/design/E36/E36-D05-copy-deck.json",
    "E09D09": "docs/design/E09/E09-D09.md",
    "CAL": "docs/plan/backlog/_tools/calendar_cv.py",
}
REF_OF = {"D03": D03_REF, "D04": D04_REF}
DASH = chr(0x2013)  # the en dash of a cited range
ARROW = chr(0x2192)
EM = chr(0x2014)
DOT = chr(0xB7)  # the middle dot of a list
SECT = chr(0xA7)
KEYS = r"14|15|D0[234]|PORTS|COPY|E36D05|E09D09|CAL"
CITE = re.compile(rf"`({KEYS})`:(\d+(?:{DASH}\d+)?(?:, :\d+(?:{DASH}\d+)?)*)")
ANCHOR = re.compile(r"`?([^\s<|(`]+)`?<!--=([A-Z]+:[A-Za-z0-9.]+)-->")
PIPE = re.compile(r"(?<!\\)\|")
SLOT = re.compile(r"\{([^{}]*)\}")
TOKEN = re.compile(
    r"`((?:color|space|radius|size|border|type|font|elevation|motion)\.[a-z0-9.]*[a-z0-9])`"
)
CLOSING = re.compile(
    r"\b(?:close[sd]?|fix(?:e[sd])?|resolve[sd]?)\s+#\d+", re.IGNORECASE
)
LOCAL_PATH = re.compile(
    "/" + "home/|/Us" + "ers/|/" + "tmp/|[A-Za-z]:\\\\|\\bw" + "t/|\\bno" + "tes/"
)  # assembled
AGENT_NAME = re.compile(r"\b[a-z]{2,4}-worker-\d\b")
URL_OR_HOST = re.compile(r"https?://|penpot\.[a-z]|team-id=|file-id=", re.IGNORECASE)
HEX = re.compile(r"#[0-9A-Fa-f]{6}(?:[0-9A-Fa-f]{2})?\b")
PX = re.compile(r"\b\d+(?:\.\d+)? ?px\b")
SOFT = re.compile(r"\b(?:undo|just|simply|anytime)\b", re.IGNORECASE)
COMPONENTS = (
    "CMP-146", "CMP-147", "CMP-148", "CMP-149", "CMP-150", "CMP-151", "CMP-152", "CMP-153",
    "CMP-158", "CMP-234", "CMP-235", "CMP-236", "CMP-237", "CMP-238", "CMP-254",
)  # fmt: skip
SHEET_FIELDS = ("Props", "States", "Tokens", "Name", "Owner story")
FIELDS = (
    "key",
    "text",
    "component",
    "state",
    "max_length",
    "context",
    "kind",
    "status",
    "source",
)
CAPS: dict[str, int | None] = {
    "label": 24,
    "reason": 80,
    "announce": 120,
    "message": 120,
    "tooltip": 120,
    "aria pattern": None,
}
STATUSES = ("DECIDED", "PROPOSED", "FROZEN")
KEY_RX = re.compile(r"rules\.graph\.[a-z_]+(?:\.[a-z0-9_]+)+")
PORT_TYPES = ("boolean", "number", "price", "side", "action", "trigger")
EVENTS = (
    "rule.graph_saved",
    "rule.roundtrip_verified",
    "rule.roundtrip_mismatch_resolved",
    "rule.graph_node_added",
    "rule.graph_autolayout_used",
    "rule.graph_keyboard_authoring_used",
)
PRIVATE_PROPS = re.compile(
    r"account|rule content|\bname\b|\btext\b|symbol", re.IGNORECASE
)
# ARIA role words D02 section 14 quotes; they name roles, not copy
ROLE_WORDS = {
    "region", "group", "status", "dialog", "log", "tree", "listbox", "alertdialog", "note",
}  # fmt: skip
# the ticket's action-bar labels (T Scope, BQ-14)
T_LABELS = ("Validate", "Simulate", "Save", "Arm" + chr(0x2026), "Discard changes")
COPY_OBJECTS = ("TYPE_LABEL", "PORT_LABEL", "REFUSAL", "copy")
FREEZE = "freeze PROPOSED, owner approval pending (#2701)"
# assembled with an explicit +, so the formatter keeps the split and the tool never spells a word
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
)


@dataclass(frozen=True)
class Texts:
    spec: str
    hand: str
    deck: str
    pins: str
    tool: str
    changed: list[str] | None
    memo: dict[str, str | None]
    full: bool = True


def git(*args: str) -> str | None:
    try:
        # git with fixed arguments and no shell; the only external program the audit runs
        r = subprocess.run(
            ["git", "-C", str(ROOT), *args],
            capture_output=True,
            check=False,
        )
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
        raise SystemExit(
            f"{PATHS[key]} does not resolve at {ref[:10]}; fetch #5448's and #5495's heads"
        )
    return text


def lines(t: Texts, key: str) -> list[str]:
    return at(t, key).split("\n")


def norm(s: str) -> str:
    return " ".join(s.split())


def cells(line: str) -> list[str]:
    return [c.strip() for c in PIPE.split(line.strip())[1:-1]]


def unesc(s: str) -> str:
    return s.replace("\\|", "|")


def unquote(s: str) -> str:
    return s[1:-1] if len(s) >= 2 and s[0] == s[-1] == '"' else s


def unkey(s: str) -> str:
    return s[1:-1] if len(s) >= 2 and s[0] == s[-1] == "`" else s


def section(text: str, head: str) -> str:
    i = text.find("\n" + head)
    if i < 0:
        return ""
    j = text.find("\n## ", i + 1)
    return text[i : j if j > 0 else len(text)]


def subsection(text: str, head: str) -> str:
    i = text.find("\n" + head)
    if i < 0:
        return ""
    j = text.find("\n#", i + 1)
    return text[i : j if j > 0 else len(text)]


def rows(text: str, lead: str) -> list[list[str]]:
    return [cells(ln) for ln in text.split("\n") if re.match(rf"\| {lead}-\d+ ", ln)]


def first_cite(s: str) -> tuple[str, int] | None:
    m = CITE.match(s)
    return (m[1], int(m[2].split(DASH)[0].split(",")[0])) if m else None


def line_at(t: Texts, key: str, n: int) -> str:
    ls = lines(t, key)
    return ls[n - 1] if 0 < n <= len(ls) else ""


def slots_to_braces(s: str) -> str:
    return s.replace("${", "{")


def collapse(s: str) -> str:
    """The string with every slot (nested ones included) read as `{}`, for coverage."""
    s = norm(unesc(slots_to_braces(s)))
    prev = None
    while prev != s:
        prev, s = s, SLOT.sub("\x00", s)
    return s.replace("\x00", "{}").strip()


def quoted(s: str) -> list[str]:
    return re.findall(r'"([^"\n]+)"', s)


# ---------------------------------------------------------------------------- the pack's tables


def deck_record(c: list[str]) -> dict[str, Any]:
    mx = c[4]
    return {
        "key": unkey(c[0]),
        "text": unesc(unquote(c[1])),
        "component": unesc(c[2]),
        "state": unesc(c[3]),
        "max_length": None if mx == EM else int(mx) if mx.isdigit() else mx,
        "context": unesc(c[8]),
        "kind": c[5],
        "status": c[6],
        "source": unesc(c[7]),
    }


def parse_deck(text: str) -> dict[str, Any]:
    """The JSON Lines twin: a head line (pack, version, base, fields, samples), then a row per line."""
    objs = [json.loads(ln) for ln in text.split("\n") if ln.strip()]
    if not objs or "list" in objs[0]:
        raise ValueError("no head line")
    out: dict[str, Any] = {**objs[0], "rows": [], "cited": []}
    for o in objs[1:]:
        lst = o.pop("list", None)
        if lst not in ("rows", "cited"):
            raise ValueError(f"a line with list {lst!r}")
        out[lst].append(o)
    return out


def dump_deck(data: dict[str, Any]) -> str:
    head = {k: v for k, v in data.items() if k not in ("rows", "cited")}
    out = [json.dumps(head, ensure_ascii=False)]
    for lst in ("rows", "cited"):
        out += [json.dumps({"list": lst, **r}, ensure_ascii=False) for r in data[lst]]
    return "\n".join(out) + "\n"


def jdeck(t: Texts) -> dict[str, Any] | None:
    try:
        return parse_deck(t.deck)
    except ValueError:
        return None


def frozen_like(r: dict[str, Any]) -> bool:
    return r.get("status") == "FROZEN" or FREEZE in str(r.get("context", ""))


def jrows(t: Texts) -> list[dict[str, Any]]:
    data = jdeck(t)
    out = data.get("rows") if data else None
    return [r for r in out if isinstance(r, dict)] if isinstance(out, list) else []


def table81(t: Texts) -> list[dict[str, Any]]:
    """Section 8.1's rows (full mode) or the twin's rows that are not frozen (deck-only)."""
    if t.full:
        return deck_rows(t.spec)
    return [r for r in jrows(t) if not frozen_like(r)]


def table9(t: Texts) -> list[dict[str, Any]]:
    """Section 9's rows (full mode) or the twin's frozen rows (deck-only)."""
    if t.full:
        return frozen_rows(t.spec)
    return [r for r in jrows(t) if frozen_like(r)]


def cited_of(t: Texts) -> list[dict[str, Any]]:
    if t.full:
        return list(cited_rows(t.spec))
    data = jdeck(t)
    out = data.get("cited") if data else None
    return [c for c in out if isinstance(c, dict)] if isinstance(out, list) else []


def samples_of(t: Texts) -> dict[str, str]:
    if t.full:
        return samples(t.spec)
    data = jdeck(t)
    out = data.get("samples") if data else None
    return {str(k): str(v) for k, v in out.items()} if isinstance(out, dict) else {}


def deck_rows(spec: str) -> list[dict[str, Any]]:
    block = subsection(spec, "### 8.1")
    return [deck_record(cells(ln)) for ln in block.split("\n") if ln.startswith("| `")]


def frozen_rows(spec: str) -> list[dict[str, Any]]:
    return [deck_record(c[1:]) for c in rows(section(spec, "## 9."), "FZ")]


def cited_rows(spec: str) -> list[dict[str, str]]:
    block = subsection(spec, "### 8.2")
    out = []
    for ln in block.split("\n"):
        if ln.startswith("| `"):
            c = cells(ln)
            out.append(
                {"key": unkey(c[0]), "text": unesc(unquote(c[1])), "where": unesc(c[2])}
            )
    return out


def notkeyed_rows(spec: str) -> list[str]:
    block = subsection(spec, "### 8.3")
    return [
        unesc(unquote(cells(ln)[0])) for ln in block.split("\n") if ln.startswith('| "')
    ]


def samples(spec: str) -> dict[str, str]:
    block = subsection(spec, "### 8.4")
    return dict(re.findall(r'`\{([^}]+)\}` = "([^"]*)"', block))


def e36_deck(t: Texts) -> dict[str, Any]:
    data = json.loads(at(t, "E36DECK"))
    strings = data.get("strings", {})
    return strings if isinstance(strings, dict) else {}


def fill(text: str, sample: dict[str, str]) -> tuple[str, list[str]]:
    missing = [s for s in SLOT.findall(text) if s not in sample]
    return SLOT.sub(lambda m: sample.get(m[1], m[0]), text), missing


def scr082(t: Texts) -> list[str]:
    ls = lines(t, "14")
    start = next((i for i, ln in enumerate(ls) if ln.startswith("### SCR-082 ")), -1)
    if start < 0:
        return []
    end = next(
        (i for i in range(start + 1, len(ls)) if ls[i].startswith("### ")), len(ls)
    )
    return ls[start:end]


def states_14(t: Texts) -> list[str]:
    head = "- **States:** "
    line = next((ln for ln in scr082(t) if ln.startswith(head)), "")
    return [p.strip() for p in line[len(head) :].split(f" {DOT} ")] if line else []


def words_14(t: Texts) -> list[str]:
    return [
        m[1] for ln in scr082(t) if (m := re.match(r"\s+\d\. \*\*`([^`]+)`\*\*", ln))
    ]


def d02_frames(t: Texts) -> list[str]:
    d02 = at(t, "D02")
    out = []
    for head in ("## 3. ", "## 4. "):
        for ln in section(d02, head).split("\n"):
            m = re.match(r"\| `(SCR-082 / [a-z-]+)`", ln)
            if m:
                out.append(m[1])
    return out


def motion_rows(t: Texts) -> list[tuple[str, str, int]]:
    out = []
    for n, ln in enumerate(lines(t, "D03"), 1):
        if re.match(r"\| M-\d+ ", ln):
            c = cells(ln)
            out.append((c[0], c[3], n))
    return out


def port_compat(t: Texts) -> dict[tuple[str, str], tuple[str | bool, int]]:
    out: dict[tuple[str, str], tuple[str | bool, int]] = {}
    inside, src = False, ""
    for n, ln in enumerate(lines(t, "PORTS"), 1):
        if ln.startswith("export const PORT_COMPAT"):
            inside = True
        elif inside and ln.startswith("} as const"):
            break
        elif inside and (m := re.match(r"  (\w+): \{$", ln)):
            src = m[1]
        elif inside and (m := re.match(r'    (\w+): (?:(true)|"(.*)"),$', ln)):
            out[(src, m[1])] = (True if m[2] else m[3], n)
    return out


def copy_exports(t: Texts) -> list[str]:
    out, obj = [], ""
    for ln in lines(t, "COPY"):
        m = re.match(r"export const (\w+)(?::[^=]*)? = \{", ln)
        if m:
            obj = m[1] if m[1] in COPY_OBJECTS else ""
        elif ln.startswith("}"):
            obj = ""
        elif obj and (m := re.match(r"  (\w+): ", ln)):
            out.append(f"{obj}.{m[1]}")
    return out


def compute(t: Texts) -> dict[str, str]:
    v = {"SHA:BASE": BASE[:10], "SHA:D03": D03_REF[:10], "SHA:D04": D04_REF[:10]}
    pc = port_compat(t)
    v["MATRIX:connects"] = str(sum(1 for c, _ in pc.values() if c is True))
    v["MATRIX:reasons"] = str(sum(1 for c, _ in pc.values() if c is not True))
    v["DECK:rows"], v["DECK:frozen"] = str(len(table81(t))), str(len(table9(t)))
    if not t.full:
        return v
    ms = motion_rows(t)
    v["MOT:rows"], v["MOT:reduce"] = str(len(ms)), str(sum(1 for m in ms if m[1]))
    v["FRAME:rows"] = str(len(rows(section(t.spec, "## 2."), "FI")))
    v["FRAME:states"], v["FRAME:words"] = str(len(states_14(t))), str(len(words_14(t)))
    v["SHEET:rows"] = str(len(re.findall(r"\n### 3\.\d+ CMP-", t.spec)))
    v["EVENT:rows"] = str(len(event_rows(t.spec)))
    return v


def anchor_problems(t: Texts, vals: dict[str, str], prefix: str) -> list[str]:
    return [
        f"`{key}` reads {value}; the tool derives {vals[key]}"
        for value, key in ANCHOR.findall(t.spec)
        if key.startswith(prefix) and key in vals and vals[key] != value
    ]


# ---------------------------------------------------------------------------- cites


def cites(text: str) -> list[tuple[str, int, int]]:
    out = []
    for m in CITE.finditer(text):
        for part in m[2].split(", :"):
            a, _, b = part.partition(DASH)
            out.append((m[1], int(a), int(b or a)))
    return out


def cite_hashes(t: Texts) -> tuple[dict[str, str], list[str]]:
    hashes: dict[str, str] = {}
    bad: list[str] = []
    for key, a, b in cites(t.spec + "\n" + t.hand):
        label = f"{key}:{a}" if a == b else f"{key}:{a}{DASH}{b}"
        if label in hashes:
            continue
        ls = lines(t, key)
        if not 0 < a <= b <= len(ls):
            bad.append(f"{label} is past the end of {PATHS[key]} ({len(ls)} lines)")
            continue
        blank = [n for n in (a, b) if not ls[n - 1].strip()]
        if blank:
            bad.append(f"{label}: line {blank[0]} is blank at its ref")
            continue
        hashes[label] = hashlib.sha256(
            (norm(ls[a - 1]) + "\n" + norm(ls[b - 1])).encode()
        ).hexdigest()[:12]
    return hashes, bad


def parse_pins(text: str) -> dict[str, str]:
    out = {}
    for ln in text.split("\n"):
        parts = ln.split("\t")
        if len(parts) == 2 and not ln.startswith("#"):
            out[parts[0]] = parts[1]
    return out


# ---------------------------------------------------------------------------- gates


def g_frame(t: Texts, vals: dict[str, str]) -> list[str]:
    fis = rows(section(t.spec, "## 2."), "FI")
    bad = []
    if [r[0] for r in fis] != [f"FI-{i}" for i in range(1, len(fis) + 1)]:
        bad.append("section 2's rows are not FI-1 ... FI-n in order")
    parts, words = states_14(t), words_14(t)
    if not parts or len(words) != 4:
        bad.append(
            "cannot read SCR-082's States line and four indicator words at the base"
        )
    by_kind: dict[str, list[list[str]]] = {}
    for r in fis:
        if len(r) != 6:
            bad.append(f"{r[0]}: {len(r)} cells, not 6")
            continue
        by_kind.setdefault(r[2], []).append(r)
    states = by_kind.get("`14` state", [])
    for p in parts:
        hit = [r for r in states if p.startswith(unquote(r[1]))]
        if len(hit) != 1:
            bad.append(f"the `14` state {p[:40]!r} has {len(hit)} frame rows (R-6)")
    if len(states) != len(parts):
        bad.append(f"{len(states)} `14` state rows for {len(parts)} `14` states")
    ind = by_kind.get("indicator", [])
    for w in words:
        if sum(1 for r in ind if unquote(r[1]) == w) != 1:
            bad.append(f"the indicator word {w!r} has no single frame row")
    if len(ind) != len(words):
        bad.append(f"{len(ind)} indicator rows for {len(words)} words")
    frames = [r[3].strip("`") for r in fis if len(r) == 6]
    d02 = d02_frames(t)
    for f in d02:
        if frames.count(f) != 1:
            bad.append(f"the D02 frame {f!r} is indexed {frames.count(f)} times")
    for r in fis:
        if len(r) != 6:
            continue
        f = r[3].strip("`")
        if f not in d02:
            bad.append(f"{r[0]}: {f!r} is not a D02 frame")
        c = first_cite(r[5])
        if not c or c[0] != "D02" or f"`{f}`" not in line_at(t, "D02", c[1]):
            bad.append(f"{r[0]}: its cite is not the D02 line that draws {f!r}")
    return bad + anchor_problems(t, vals, "FRAME:")


def a_rows(hand: str) -> list[tuple[str, str, list[str]]]:
    out = []
    for ln in section(hand, f"## {SECT}C").split("\n"):
        m = re.match(rf"- \*\*(A-\d+) {ARROW} `(1[45])`", ln)
        if not m:
            continue
        body = ln[m.end() :]
        anchors = re.findall(r'Old: "(.+?)"\.? New:', body)
        anchors += re.findall(
            r'(?:[Aa]fter|[Bb]efore) "(.+?)"(?: \([^)]*\))? add', body
        )
        out.append((m[1], m[2], anchors))
    return out


def g_sheet(t: Texts, vals: dict[str, str]) -> list[str]:
    bad = []
    three = section(t.spec, "## 3.")
    sheets = re.split(r"\n### 3\.\d+ ", three)[1:]
    named = {s.split(" ", 1)[0]: s for s in sheets}
    tmap = {unkey(c[0]) for c in (cells(ln) for ln in section(t.spec, "## 4.").split("\n")
                                  if ln.startswith("| `"))}  # fmt: skip
    contract = {cells(ln)[0] for ln in section(t.hand, f"## {SECT}B").split("\n")
                if ln.startswith("| CMP-")}  # fmt: skip
    stories = {cells(ln)[0] for ln in section(t.hand, f"## {SECT}D").split("\n")
               if ln.startswith("| CMP-")}  # fmt: skip
    for cmp in COMPONENTS:
        body = named.get(cmp)
        if body is None:
            bad.append(f"{cmp} has no sheet in section 3")
            continue
        for f in SHEET_FIELDS:
            if not re.search(rf"\n- \*\*{f}\*\*: \S", body):
                bad.append(f"{cmp}'s sheet has no {f}")
        bad += [f"{cmp}'s sheet names `{tok}`, absent from the token map"
                for tok in sorted(set(TOKEN.findall(body))) if tok not in tmap]  # fmt: skip
        if cmp not in contract:
            bad.append(f"{cmp} has no hand-off contract row")
        if cmp not in stories:
            bad.append(f"{cmp} has no hand-off Storybook row")
    bad += [f"a sheet for {c} outside the set" for c in named if c not in COMPONENTS]
    ar = a_rows(t.hand)
    if [a for a, _, _ in ar] != [f"A-{i}" for i in range(1, len(ar) + 1)]:
        bad.append("the hand-off's A-rows are not A-1 ... A-n in order")
    for aid, key, anchors in ar:
        if not anchors:
            bad.append(f"{aid}: names neither an Old text nor an anchor")
        for a in anchors:
            n = at(t, key).count(a)
            if n != 1:
                bad.append(f"{aid}: {a[:40]!r} stands {n} times in `{key}` at the base")
    return bad + anchor_problems(t, vals, "SHEET:")


def g_deck(t: Texts, vals: dict[str, str]) -> list[str]:
    bad = []
    try:
        data = parse_deck(t.deck)
    except (ValueError, AttributeError) as e:
        return [f"the JSON Lines twin does not parse: {e}"]
    table = table81(t) + table9(t)
    if data.get("fields") != list(FIELDS):
        bad.append("the JSON twin's field list is not the deck's nine fields")
    if t.full:
        if data.get("rows") != table:
            drift = [
                r.get("key") for r, s in zip(data.get("rows", []), table) if r != s
            ]
            bad.append(
                f"the JSON rows differ from sections 8.1 and 9 (first: {drift[:1]})"
            )
        if data.get("cited") != cited_rows(t.spec):
            bad.append("the JSON `cited` list differs from section 8.2")
        if data.get("samples") != samples(t.spec):
            bad.append("the JSON slot samples differ from section 8.4")
    else:
        if data.get("pack") != "E37-D05" or data.get("base") != BASE[:10]:
            bad.append(f"the head line is not E37-D05's at the base {BASE[:10]}")
        if table != data.get("rows"):
            bad.append(
                "the twin's rows are not its non-frozen rows, then its frozen ones"
            )
        bad += [f"{r.get('key')}: fields {sorted(r)}, not the nine" for r in table
                if sorted(r) != sorted(FIELDS)]  # fmt: skip
        bad += [f"a cited row with fields {sorted(c)}" for c in cited_of(t)
                if sorted(c) != ["key", "text", "where"]]  # fmt: skip
        if not samples_of(t):
            bad.append("the head line carries no slot samples")
    if any(sorted(r) != sorted(FIELDS) for r in table):
        return bad
    sample = samples_of(t)
    keys = [r["key"] for r in table]
    bad += [
        f"{k} is keyed twice" for k in sorted({k for k in keys if keys.count(k) > 1})
    ]
    for r in table:
        k = r["key"]
        for f in FIELDS:
            if f != "max_length" and not str(r.get(f, "")).strip():
                bad.append(f"{k}: no {f}")
        if r["kind"] not in CAPS:
            bad.append(f"{k}: kind {r['kind']!r} is not one of the six")
        if r["status"] not in STATUSES:
            bad.append(
                f"{k}: status {r['status']!r} is not one of {', '.join(STATUSES)}"
            )
        if not k.startswith("rules.graph."):
            continue
        if not KEY_RX.fullmatch(k):
            bad.append(f"{k}: not `rules.graph.<area>.<name>`")
        if r["max_length"] != CAPS.get(r["kind"]):
            bad.append(f"{k}: cap {r['max_length']} is not the {r['kind']} cap (R-4)")
        if isinstance(r["max_length"], int):
            text, missing = fill(r["text"], sample)
            bad += [f"{k}: slot {{{s}}} has no sample in section 8.4" for s in missing]
            if len(text) > r["max_length"]:
                bad.append(
                    f"{k}: {len(text)} characters filled, over {r['max_length']}"
                )
    bad += [f"{k}: an 8.1 row marked FROZEN (section 9 holds them)"
            for k in (r["key"] for r in table81(t) if r["status"] == "FROZEN")]  # fmt: skip
    return bad + anchor_problems(t, vals, "DECK:")


def g_matrix(t: Texts, vals: dict[str, str]) -> list[str]:
    pc = port_compat(t)
    bad = []
    if len(pc) != len(PORT_TYPES) ** 2:
        bad.append(f"PORT_COMPAT reads {len(pc)} cells at the base, not 36")
    deck = {
        r["key"]: r for r in table81(t) if r["key"].startswith("rules.graph.connect.")
    }
    want = {
        f"rules.graph.connect.{a}.{b}": (a, b) for a in PORT_TYPES for b in PORT_TYPES
    }
    bad += [f"{k} is not a port pair" for k in deck if k not in want]
    for k, pair in want.items():
        r = deck.get(k)
        if r is None:
            bad.append(f"{k} is missing")
            continue
        cell, n = pc.get(pair, ("", 0))
        text = "connects" if cell is True else cell
        if r["text"] != text:
            bad.append(f"{k}: {r['text']!r}, PORTS reads {text!r}")
        if r["status"] != ("DECIDED" if cell is True else "PROPOSED"):
            bad.append(f"{k}: status {r['status']}")
        if first_cite(r["source"]) != ("PORTS", n):
            bad.append(f"{k}: its source is not `PORTS`:{n}")
    return bad + anchor_problems(t, vals, "MATRIX:")


def coverage_sources(t: Texts) -> list[tuple[str, str]]:
    d02, d04 = at(t, "D02"), at(t, "D04")
    out = [("D02 section 15", q) for q in quoted(section(d02, "## 15. "))]
    out += [
        ("D02 section 14", q)
        for q in quoted(section(d02, "## 14. "))
        if q not in ROLE_WORDS
    ]
    for ln in section(d02, "## 4. ").split("\n"):
        if ln.startswith("| `SCR-082 / "):
            out += [("D02 section 4 tooltip", q) for q in quoted(cells(ln)[3])]
    out += [
        ("D04 script", unquote(r[2]))
        for r in rows(section(d04, "## 5. "), "S")
        if len(r) > 2
    ]
    for r in rows(section(d04, "## 4. "), "K"):
        out += [("D04 announcement", q) for q in quoted(r[4] if len(r) > 4 else "")]
    out += [("T labels", label) for label in T_LABELS]
    return out


def g_cover(t: Texts, vals: dict[str, str]) -> list[str]:
    bad = []
    table, fz, cited = table81(t), table9(t), cited_of(t)
    if t.full:
        nk = notkeyed_rows(t.spec)
        have = {collapse(r["text"]) for r in table + fz} | {
            collapse(c["text"]) for c in cited
        }
        have |= {collapse(s) for s in nk}
        srcs = coverage_sources(t)
        for where, s in srcs:
            if collapse(s) not in have:
                bad.append(f"{where}: {s[:50]!r} is in no deck row (BQ-13)")
        seen = {collapse(s) for _, s in srcs}
        bad += [f"section 8.3 lists {s[:40]!r}, which no source quotes" for s in nk
                if collapse(s) not in seen]  # fmt: skip
    sources = " ".join(r["source"] for r in table + fz)
    for ex in copy_exports(t):
        if not re.search(rf"(?<![\w.]){re.escape(ex)}\b", sources):
            bad.append(f"the copy.ts export {ex} is no row's source")
    for r in table:
        c = first_cite(r["source"])
        if c and c[0] in ("D02", "D04", "14"):
            line = unesc(slots_to_braces(norm(line_at(t, c[0], c[1]))))
            if norm(r["text"]) not in line:
                bad.append(
                    f"{r['key']}: {r['text'][:40]!r} is not verbatim on `{c[0]}`:{c[1]}"
                )
        elif not c and not r["source"].startswith("new ("):
            bad.append(f"{r['key']}: its source is neither a cite nor `new (...)`")
    e36 = e36_deck(t)
    for row in cited:
        entry = e36.get(row["key"])
        if not isinstance(entry, dict):
            bad.append(f"{row['key']} is not an E36-D05 key at the base")
        elif entry.get("text") != row["text"]:
            bad.append(f"{row['key']}: the text differs from E36-D05's")
    return bad


def g_raw(t: Texts, vals: dict[str, str]) -> list[str]:
    bad = []
    for name, text in (("spec", t.spec), ("hand-off", t.hand), ("deck", t.deck)):
        for i, ln in enumerate(text.split("\n"), 1):
            if HEX.search(ln):
                bad.append(f"{name}:{i} carries a raw hex value (raise it to E37-D03)")
            if PX.search(ln) and not re.search(r"`D0[234]`:\d", ln):
                bad.append(
                    f"{name}:{i} carries a px value beside no D02 / D03 / D04 cite"
                )
    return bad


def g_motion(t: Texts, vals: dict[str, str]) -> list[str]:
    bad = anchor_problems(t, vals, "MOT:")
    d03 = {m: (red, n) for m, red, n in motion_rows(t)}
    mine = rows(section(t.spec, "## 5."), "M")
    if [r[0] for r in mine] != list(d03):
        bad.append("section 5's M rows are not D03's M rows in order")
    for r in mine:
        if len(r) != 4 or r[0] not in d03:
            bad.append(f"{r[0]}: not a D03 row of four cells")
            continue
        red, n = d03[r[0]]
        if r[2] != red:
            bad.append(f"{r[0]}: reduce {r[2]!r}, D03 reads {red!r}")
        if first_cite(r[3]) != ("D03", n):
            bad.append(f"{r[0]}: its cite is not `D03`:{n}")
    if vals["MOT:rows"] != vals["MOT:reduce"]:
        bad.append(
            f"D03: {vals['MOT:rows']} motion rows, {vals['MOT:reduce']} with a reduce cell"
        )
    for key in ("MOT:rows", "MOT:reduce"):
        if f"<!--={key}-->" not in t.spec:
            bad.append(f"the spec drops the {key} anchor")
    return bad


def g_frozen(t: Texts, vals: dict[str, str]) -> list[str]:
    bad = []
    e36 = e36_deck(t)
    recs: list[tuple[str, dict[str, Any]]] = []
    if t.full:
        fz = rows(section(t.spec, "## 9."), "FZ")
        if [r[0] for r in fz] != [f"FZ-{i}" for i in range(1, len(fz) + 1)]:
            bad.append("section 9's rows are not FZ-1 ... FZ-n in order")
        for c in fz:
            if len(c) != 10:
                bad.append(f"{c[0]}: {len(c)} cells, not 10")
                continue
            recs.append((c[0], deck_record(c[1:])))
    else:
        recs = [(str(r.get("key")), r) for r in table9(t)]
        if not recs:
            bad.append("the twin holds no frozen row")
    for label, r in recs:
        if r["status"] != "FROZEN":
            bad.append(f"{label}: status {r['status']}, not FROZEN")
        soft = SOFT.search(r["text"])
        if soft:
            bad.append(f"{label}: {soft[0]!r} softens a safety string (R-7)")
        if FREEZE not in r["context"]:
            bad.append(f"{label}: the context does not say the freeze is PROPOSED")
        if r["key"].startswith("rules.graph."):
            cite = first_cite(r["source"])
            line = norm(line_at(t, cite[0], cite[1])) if cite else ""
            if not cite or norm(r["text"]) not in line:
                bad.append(f"{label}: not verbatim on its first cite")
        else:
            entry = e36.get(r["key"])
            if not isinstance(entry, dict) or entry.get("text") != r["text"]:
                bad.append(f"{label}: {r['key']} is not E36-D05's key with this text")
    return bad


def event_rows(spec: str) -> list[list[str]]:
    return [
        cells(ln)
        for ln in section(spec, "## 10.").split("\n")
        if ln.startswith("| `rule.")
    ]


def g_event(t: Texts, vals: dict[str, str]) -> list[str]:
    bad = []
    ev = event_rows(t.spec)
    names = [unkey(r[0]) for r in ev]
    if names != list(EVENTS):
        bad.append(f"section 10 lists {names}, not the six events in order")
    for r in ev:
        if len(r) != 7:
            bad.append(f"{r[0]}: {len(r)} cells, not 7")
            continue
        if PRIVATE_PROPS.search(r[3]):
            bad.append(f"{r[0]}: a property names an account or rule content")
        c = first_cite(r[6])
        if not c or unkey(r[0]) not in line_at(t, c[0], c[1]):
            bad.append(f"{r[0]}: not named on its cited line")
    return bad + anchor_problems(t, vals, "EVENT:")


def g_cite(t: Texts, vals: dict[str, str]) -> list[str]:
    hashes, bad = cite_hashes(t)
    pinned = parse_pins(t.pins)
    for label, h in hashes.items():
        if label not in pinned:
            bad.append(
                f"cite {label} is unpinned: verify it by content, then --repin-ruled"
            )
        elif pinned[label] != h:
            bad.append(f"cite {label}: the line at its ref is not the pinned content")
    return bad + anchor_problems(t, vals, "SHA:")


def g_hygiene(t: Texts, vals: dict[str, str]) -> list[str]:
    bad = []
    checks = (
        (CLOSING, "a closing keyword (the closing line waits for the re-pin commit)"),
        (LOCAL_PATH, "a local path"),
        (AGENT_NAME, "an agent name"),
        (URL_OR_HOST, "a URL or a host"),
    )
    for name, text in (("spec", t.spec), ("hand-off", t.hand), ("deck", t.deck)):
        for i, ln in enumerate(text.split("\n"), 1):
            bad += [
                f"{name}:{i} carries {what}" for rx, what in checks if rx.search(ln)
            ]
            if "{{" in ln:
                bad.append(f"{name}:{i} carries a double-brace slot")
    texts = (("spec", t.spec), ("hand-off", t.hand), ("deck", t.deck), ("tool", t.tool),
             ("pins", t.pins))  # fmt: skip
    for name, text in texts:
        for i, ln in enumerate(text.split("\n"), 1):
            if any(d in ln.lower() for d in DENY):
                bad.append(f"{name}:{i} carries a public-text deny word")
    for _, key in ANCHOR.findall(t.spec):
        if key not in vals:
            bad.append(f"an anchor `{key}` the tool does not compute")
    return bad


def g_scope(t: Texts, vals: dict[str, str]) -> list[str]:
    if t.changed is None:
        return ["cannot list the changed paths (git failed)"]
    own = OWN_PATHS if t.full else DECK_PATHS
    return [
        f"{p} is touched; this ticket owns {', '.join(own)}"
        for p in t.changed
        if p not in own
    ]


def g_status(t: Texts, vals: dict[str, str]) -> list[str]:
    bad = []
    for r in table81(t):
        src = first_cite(r["source"])
        if r["status"] == "PROPOSED" or src is None or src[0] not in ("D02", "D04"):
            continue
        line = line_at(t, src[0], src[1])
        i = line.find(f'"{r["text"]}"')
        if i < 0:
            continue
        after = re.match(r"\s*\(([^)]*)\)", line[i + len(r["text"]) + 2 :])
        if after and "PROPOSED" in after[1]:
            bad.append(
                f"{r['key']}: {r['status']}, but `{src[0]}`:{src[1]} marks it PROPOSED"
            )
    if not t.full:
        return bad
    role = next(
        (
            ln
            for ln in t.spec.split("\n")
            if ln.startswith("- **Name**: `rules.graph.aria.region`")
        ),
        "",
    )
    if "PROPOSED until E37-Q05's run" not in role or "DECIDED" in role:
        bad.append(
            "§3.1: the `application` role is not PROPOSED until E37-Q05's run (D04 Q-1)"
        )
    return bad


def g_checklist(t: Texts, vals: dict[str, str]) -> list[str]:
    da = rows(section(t.spec, "## 13."), "DA")
    ids = [r[0] for r in da]
    want = [f"DA-{n}" for n in range(1, 18)]
    if ids != want:
        return [f"§13 holds {ids}, not DA-1 ... DA-17 in order"]
    bad = []
    for n, r in enumerate(da, 1):
        if n <= 7:
            if r[2] != f"`14` box {n}":
                bad.append(f"DA-{n}: its source is not `14` box {n}")
            continue
        sc = f"SC-{n - 7}"
        cite = first_cite(r[3])
        if r[2] != sc or cite is None or cite[0] != "D04":
            bad.append(f"DA-{n}: it does not cite D04's {sc}")
        elif not line_at(t, "D04", cite[1]).startswith(f"- **{sc}**"):
            bad.append(f"DA-{n}: `D04`:{cite[1]} is not {sc}'s line")
    return bad


GATES: dict[str, Callable[[Texts, dict[str, str]], list[str]]] = {
    "G-FRAME": g_frame,
    "G-SHEET": g_sheet,
    "G-DECK": g_deck,
    "G-MATRIX": g_matrix,
    "G-COVER": g_cover,
    "G-RAW": g_raw,
    "G-MOTION": g_motion,
    "G-FROZEN": g_frozen,
    "G-EVENT": g_event,
    "G-CITE": g_cite,
    "G-HYGIENE": g_hygiene,
    "G-SCOPE": g_scope,
    "G-STATUS": g_status,
    "G-CHECKLIST": g_checklist,
}


DECK_GATES = (
    "G-DECK", "G-MATRIX", "G-COVER", "G-RAW", "G-FROZEN", "G-HYGIENE", "G-SCOPE", "G-STATUS",
)  # fmt: skip


def gates_of(t: Texts) -> dict[str, Callable[[Texts, dict[str, str]], list[str]]]:
    return GATES if t.full else {g: GATES[g] for g in DECK_GATES}


def audit(t: Texts) -> list[tuple[str, str]]:
    vals = compute(t)
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


def load() -> Texts:
    full = any((ROOT / rel).exists() for rel in PACK_PATHS)
    return Texts(
        read(SPEC_REL), read(HAND_REL), read(DECK_REL), read(PINS_REL), read(TOOL_REL),
        changed_paths(), {}, full,
    )  # fmt: skip


Mutation = Callable[[Texts], Texts]


def once(text: str, old: str, where: str) -> None:
    if text.count(old) != 1:
        raise SystemExit(
            f"self-test: the {where} carries {old[:50]!r} {text.count(old)} times"
        )


def sub(old: str, new: str) -> Mutation:
    def f(t: Texts) -> Texts:
        once(t.spec, old, "spec")
        return replace(t, spec=t.spec.replace(old, new))

    return f


def sub_hand(old: str, new: str) -> Mutation:
    def f(t: Texts) -> Texts:
        once(t.hand, old, "hand-off")
        return replace(t, hand=t.hand.replace(old, new))

    return f


def deck_set(key: str, field: str, value: object) -> Mutation:
    """Changes one row field in the JSON twin only."""

    def f(t: Texts) -> Texts:
        data = parse_deck(t.deck)
        for r in data["rows"]:
            if r["key"] == key:
                r[field] = value
        return replace(t, deck=dump_deck(data))

    return f


def deck_head(field: str, value: object) -> Mutation:
    """Changes one field of the twin's head line."""

    def f(t: Texts) -> Texts:
        data = parse_deck(t.deck)
        data[field] = value
        return replace(t, deck=dump_deck(data))

    return f


def deck_cited(key: str, field: str, value: object) -> Mutation:
    """Changes one field of a `cited` row in the twin."""

    def f(t: Texts) -> Texts:
        data = parse_deck(t.deck)
        for r in data["cited"]:
            if r["key"] == key:
                r[field] = value
        return replace(t, deck=dump_deck(data))

    return f


def row_set(key: str, col: int, value: str, field: str, jvalue: object) -> Mutation:
    """Changes one cell of a deck row (section 8.1 or 9) and its JSON twin together."""

    def f(t: Texts) -> Texts:
        fz = 1 if key in {r["key"] for r in frozen_rows(t.spec)} else 0
        t = set_cell(f"`{key}`", col + fz, value, lead_col=fz)(t)
        return deck_set(key, field, jvalue)(t)

    return f


def set_cell(lead: str, col: int, value: str, lead_col: int = 0) -> Mutation:
    """Sets one cell of the spec's table row whose cell `lead_col` reads `lead`."""

    def f(t: Texts) -> Texts:
        ls = t.spec.split("\n")
        hit = [i for i, ln in enumerate(ls) if ln.startswith("| ") and
               len(c := cells(ln)) > lead_col and c[lead_col] == lead]  # fmt: skip
        if len(hit) != 1:
            raise SystemExit(f"self-test: {lead} leads {len(hit)} rows")
        c = cells(ls[hit[0]])
        c[col] = value
        ls[hit[0]] = "| " + " | ".join(c) + " |"
        return replace(t, spec="\n".join(ls))

    return f


def drop_hand(lead: str, has: str) -> Mutation:
    def f(t: Texts) -> Texts:
        ls = t.hand.split("\n")
        keep = [x for x in ls if not (x.startswith(f"| {lead} ") and has in x)]
        if len(keep) != len(ls) - 1:
            raise SystemExit(f"self-test: {lead} with {has!r} is not one hand-off row")
        return replace(t, hand="\n".join(keep))

    return f


def drop_row(lead: str) -> Mutation:
    def f(t: Texts) -> Texts:
        ls = t.spec.split("\n")
        return replace(
            t, spec="\n".join(x for x in ls if not x.startswith(f"| {lead} "))
        )

    return f


# fmt: off
MUTATIONS: tuple[tuple[str, str, Mutation], ...] = (
    ("G-FRAME", "the cycle-detected frame row dropped", drop_row("FI-4")),
    ("G-FRAME", "FI-1 quotes a state `14` does not have", sub('"empty canvas"', '"empty graph"')),
    ("G-FRAME", "FI-12 cited one line off its frame", set_cell("FI-12", 5, "`D02`:136")),
    ("G-SHEET", "CMP-237's Tokens line dropped", sub("- **Tokens**: `color.port.ring`", "- Tok:")),
    ("G-SHEET", "A-15's Old text off by one word",
     sub_hand('Old: "the node list in CMP-153 NodeInspectorDrawer"',
              'Old: "the node list in CMP-153 Node InspectorDrawer"')),
    ("G-SHEET", "CMP-254's Storybook row dropped", drop_hand("CMP-254", "Tab1280")),
    ("G-DECK", "the JSON twin drifts on one text", deck_set("rules.graph.canvas.fit", "text", "Fit")),
    ("G-DECK", "a label cap typed below its kind's",
     row_set("rules.graph.canvas.fit", 4, "8", "max_length", 8)),
    ("G-DECK", "the twin's slot samples drift from 8.4", deck_head("samples", {"n": "120"})),
    ("G-MATRIX", "one PORT_COMPAT reason reworded in the deck",
     row_set("rules.graph.connect.price.side", 1, '"A price can\'t be a side."', "text",
             "A price can't be a side.")),
    ("G-COVER", "a D02 announcement reworded in the deck",
     row_set("rules.graph.announce.renamed", 1, '"Renamed as {name}"', "text", "Renamed as {name}")),
    ("G-COVER", "the copy.position export left unsourced",
     row_set("rules.graph.aria.position", 7, "`COPY`:144", "source", "`COPY`:144")),
    ("G-RAW", "a raw hex beside a token name",
     sub("No raw value is written here;", "No raw value (#11151A) is written here;")),
    ("G-RAW", "a raw px value with no cite",
     sub_hand("one roving stop, type-ahead;", "one roving stop, 40 px rows;")),
    ("G-MOTION", "M-13's reduce cell retyped", set_cell("M-13", 2, "identical")),
    ("G-MOTION", "the motion row count typed by hand", sub("19<!--=MOT:rows-->", "18<!--=MOT:rows-->")),
    ("G-FROZEN", "FZ-17 no longer FROZEN",
     row_set("rules.graph.badge.graph_only", 6, "PROPOSED", "status", "PROPOSED")),
    ("G-FROZEN", "FZ-10's freeze stated as decided",
     row_set("rules.graph.node.only_tighten", 8, "the ratchet line", "context", "the ratchet line")),
    ("G-EVENT", "an event renamed",
     set_cell("`rule.graph_autolayout_used`", 0, "`rule.graph_layout_used`")),
    ("G-EVENT", "an account id among the properties",
     sub("`{operation, surface}`, surface", "`{operation, surface, accountId}`, surface")),
    ("G-CITE", "a `D04` cite one line off its pinned content", sub("(`D04`:308)", "(`D04`:309)")),
    ("G-HYGIENE", "a closing keyword against #950",
     sub("This pack designs nothing new:", "Closes #950. This pack designs nothing new:")),
    ("G-HYGIENE", "a deny word in the tool's own text",
     lambda t: replace(t, tool=t.tool + "\n# " + "fl" + "ood\n")),
    ("G-SCOPE", "a parent file in the diff",
     lambda t: replace(t, changed=[*OWN_PATHS, PATHS["D02"]])),
    ("G-STATUS", "the hint, PROPOSED at its source, made DECIDED",
     row_set("rules.graph.aria.hint", 6, "DECIDED", "status", "DECIDED")),
    ("G-STATUS", "the `application` role made DECIDED in §3.1",
     sub("PROPOSED until E37-Q05's run (`D04`:308)", "DECIDED (`D04`:308)")),
    ("G-CHECKLIST", "DA-17 dropped", drop_row("DA-17")),
    ("G-CHECKLIST", "DA-17 cites SC-9's line", set_cell("DA-17", 3, "`D04`:320")),
)

# deck-only mode: the twin alone, so every mutation edits the JSON Lines rows or head
DECK_MUTATIONS: tuple[tuple[str, str, Mutation], ...] = (
    ("G-DECK", "a label cap typed below its kind's", deck_set("rules.graph.canvas.fit", "max_length", 8)),
    ("G-DECK", "a key typed twice",
     deck_set("rules.graph.canvas.zoom_in", "key", "rules.graph.canvas.zoom_out")),
    ("G-DECK", "a kind outside the six", deck_set("rules.graph.canvas.fit", "kind", "button")),
    ("G-DECK", "the slot samples dropped from the head", deck_head("samples", {})),
    ("G-DECK", "the head line's base re-typed", deck_head("base", "0000000000")),
    ("G-MATRIX", "one PORT_COMPAT reason reworded",
     deck_set("rules.graph.connect.price.side", "text", "A price can't be a side.")),
    ("G-COVER", "a D02 announcement reworded",
     deck_set("rules.graph.announce.renamed", "text", "Renamed as {name}")),
    ("G-COVER", "the copy.position export left unsourced",
     deck_set("rules.graph.aria.position", "source", "`COPY`:144")),
    ("G-COVER", "a cited E36-D05 string drifts",
     deck_cited("rules.editor.roundtrip.mismatch", "text", "Round-trip differs")),
    ("G-RAW", "a raw hex in a context",
     deck_set("rules.graph.canvas.fit", "context", "a foot-row button (L-4), #11151A")),
    ("G-RAW", "a raw px value in a row with no D0x cite",
     deck_set("rules.graph.aria.position", "context", "the node's place, 40 px")),
    ("G-FROZEN", "a frozen row no longer FROZEN",
     deck_set("rules.graph.badge.graph_only", "status", "PROPOSED")),
    ("G-FROZEN", "a frozen row's freeze stated as decided",
     deck_set("rules.graph.node.only_tighten", "context", "the ratchet line")),
    ("G-FROZEN", "a frozen E36-D05 string reworded",
     deck_set("rules.editor.stop.kept", "text", "The stop is kept.")),
    ("G-HYGIENE", "a closing keyword in a context",
     deck_set("rules.graph.canvas.fit", "context", "Closes #950")),
    ("G-HYGIENE", "a deny word in the tool's own text",
     lambda t: replace(t, tool=t.tool + "\n# " + "fl" + "ood\n")),
    ("G-SCOPE", "a parent file in the diff",
     lambda t: replace(t, changed=[*DECK_PATHS, PATHS["D02"]])),
    ("G-SCOPE", "the spec in the deck-first diff", lambda t: replace(t, changed=[*DECK_PATHS, SPEC_REL])),
    ("G-STATUS", "the hint, PROPOSED at its source, made DECIDED",
     deck_set("rules.graph.aria.hint", "status", "DECIDED")),
)
# fmt: on


def mode(t: Texts) -> str:
    return "full" if t.full else "deck-only (spec, hand-off and pins absent)"


def selftest() -> tuple[bool, list[str]]:
    first = load()
    base = replace(first, changed=list(OWN_PATHS if first.full else DECK_PATHS))
    muts = MUTATIONS if base.full else DECK_MUTATIONS
    before = (base.spec, base.hand, base.deck)
    found = audit(base)
    out = [f"self-test: mode {mode(base)}", f"self-test: baseline {len(found)} FAIL"]
    out += [f"  baseline {g}: {m}" for g, m in found]
    ok = not found
    for i, (gate, what, fn) in enumerate(muts, 1):
        gates = sorted({g for g, _ in audit(fn(base))})
        good = gates == [gate]
        ok &= good
        out.append(
            f"{'ok  ' if good else 'FAIL'} MU-{i} {gate}: {what} -> {', '.join(gates) or 'none'}"
        )
    seen = {g for g, _, _ in muts}
    missing = [g for g in gates_of(base) if g not in seen]
    ok &= not missing
    if missing:
        out.append(f"FAIL no mutation for {', '.join(missing)}")
    after = load()
    restored = (after.spec, after.hand, after.deck) == before
    ok &= restored
    out.append(
        f"self-test: {len(muts)} mutations, texts restored: {'yes' if restored else 'NO'}"
    )
    out.append(f"self-test: {'PASS' if ok else 'FAIL'}")
    return ok, out


def main(argv: list[str]) -> int:
    ap = argparse.ArgumentParser(description="E37-D05 hand-off audit")
    g = ap.add_mutually_exclusive_group()
    g.add_argument("--check", action="store_true")
    g.add_argument("--self-test", action="store_true")
    g.add_argument("--repin-ruled", action="store_true")
    ap.add_argument("--json", action="store_true")
    a = ap.parse_args(argv)
    if a.self_test:
        ok, out = selftest()
        print("\n".join(out))
        return 0 if ok else 1
    t = load()
    if a.repin_ruled:
        if not t.full:
            print(
                "refused: deck-only mode has no pins file to write (the pack PR adds it)"
            )
            return 1
        hashes, bad = cite_hashes(t)
        if bad:
            print(f"refused: {bad[0]}")
            return 1
        head = (
            "# E37-D05 cite pins: the cite, a hash of its cited line(s) at its ref."
            " Written by --repin-ruled only.\n"
        )
        (ROOT / PINS_REL).write_text(
            head + "".join(f"{k}\t{h}\n" for k, h in hashes.items()), encoding="utf-8"
        )
        print(f"wrote {PINS_REL} ({len(hashes)} cites)")
        return 0
    found = audit(t)
    if a.json:
        print(
            json.dumps(
                {
                    "mode": "full" if t.full else "deck-only",
                    "base": BASE,
                    "d03": D03_REF,
                    "d04": D04_REF,
                    "values": compute(t),
                    "findings": [{"gate": g, "msg": m} for g, m in found],
                },
                ensure_ascii=False,
                indent=2,
            )
        )
    else:
        print(f"mode: {mode(t)}")
        for gate, msg in found:
            print(f"FAIL {gate}: {msg}")
        print(f"{len(found)} FAIL ({len(gates_of(t))} gates)")
    return 1 if found else 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
