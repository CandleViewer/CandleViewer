#!/usr/bin/env python3
"""E47-D07 (#1306) audit: the live-region announcement spec (text first) and its transcripts.

Standalone, offline, stdlib only; it executes no repo code and runs under `python3 -I`. It reads,
AS TEXT at the pinned base (`git show`): the plan texts, the shipped announcer, ambient writer and
preferences model, the merged design texts the spec cites and the E47 audit catalogue; the in-flight
siblings (E47-D04, E47-D05, E47-D09) at their pinned PR heads and E47-D03 at its merge commit; and,
from the working tree, the spec `docs/design/E47/E47-D07.md`, its hand-off, the transcripts JSON and
the pins file. Its form follows the E47-D05 tool (the same modes, anchored values, default-deny pins
and mutations).

1. **Values.** Every `{{KIND:key}}` placeholder is written by `--fill` as `VALUE<!--=KIND:key-->`
   (COUNT: rows of the spec's and the hand-off's own tables; SIM: figures from the replay of the
   transcripts). `--check` re-derives each anchored value (G-ANCHOR) and FAILs a placeholder left
   behind or a stray HTML comment (G-MARKER). `--fill` also writes the mutation rows
   ({{MUTATIONS}}) and the annotated transcript tables ({{TRANSCRIPT:<id>}}).
2. **Cites.** Every `NN`:line and KEY:line cite resolves to a non-blank line at the base or at the
   pin (G-CITE); every "verbatim" copy string occurs on its cited line (G-QUOTE); every Old
   fragment of the hand-off's A-rows occurs verbatim on its cited line (G-AROW).
3. **Gates** (BQ-15 first, then the form): G-PIN (the start line names every pin with its PR; each
   commit holds its file; a merge pin is on origin/main; an in-flight branch that moved past its
   pin FAILs), G-CLASSES (one class per taxonomy row from the five of §3.1, ranks only on assertive
   rows; §3.2 opens with `05`:152's six verbatim, each with an assertive T-row, the rest PROPOSED;
   the fixed panel class is the safety group plus the auto-flatten (BQ-2); every announced row
   in exactly one panel class whose default matches its class), G-COPY (closed
   slots, no glyph sign, no secret slot, every Words id in the deck, the reason map covering `24`'s
   closed sets, W-36 the BQ-11 sentence), G-SIM (the replay of every script equals its expected
   lines; per field at most one write per cadence, the latest value; every assertive input spoken
   once or collapsed into its own order's later state; ranks hold; assertive lines identical in
   every setting cell; §10's tables equal the transcripts), G-LABELS (every handed label once,
   verbatim at its source, worded; an unpinned sibling's label names no source), G-FIND (§11 holds exactly CAT's E47-D07 rows, each at its CAT
   line, with a disposition; CAT:48's count equals the screen-mapped rows), G-T2 (the T2 paragraph
   once in §8.2 with every standing-gate element; every §0 / §4 / §8 line naming T2 cites §8.2; the
   hand-off's component line names CMP-079 and CMP-019), G-COMP, G-PUBLIC (no URL, host, local
   path, worker name or secret-shaped string), G-RULED (the heading names the ruling of record,
   comment 6570054100; BQ-0 … BQ-16 once each, "RULED, OVERRIDE" for BQ-2, BQ-7, BQ-8 and BQ-9,
   "RULED, ACCEPT" for the rest; no line reads as pending), G-BOARDS, G-HEUR, G-WALK, G-OWNER,
   G-UNTOUCHED, G-BUDGET, G-MUTLIST.
4. **Pins (G-RULED-PIN).** A whole-document default-deny pin set over every unit of both documents
   (heading, table row by lead cell, prose line, by heading path and occurrence, plus a line-shape
   unit per region) in `e47_d07_ruled_pins.txt`. Anchored values are cut out (G-ANCHOR owns them).
   `--repin-ruled` is the only writer and refuses while a placeholder is unfilled. A pin finding in
   a region another gate already FAILs prints as NOTE.
5. **--self-test** applies every mutation (M-n, spec §14) in memory with the values frozen at the
   filled baseline; each must add exactly one FAIL, from the gate it names; the texts on disk are
   checked byte-identical afterwards (sha256). Output is ASCII.

Usage (from the repo root):
  python3 -I docs/design/_tools/e47_d07_announcement_audit.py --check [--fill]
  python3 -I docs/design/_tools/e47_d07_announcement_audit.py --self-test
  python3 -I docs/design/_tools/e47_d07_announcement_audit.py --repin-ruled
  python3 -I docs/design/_tools/e47_d07_announcement_audit.py --write-transcripts
Exit 0 = no FAIL; 1 = at least one FAIL.
"""

from __future__ import annotations

import argparse
import functools
import hashlib
import itertools
import json
import math
import re
import subprocess
import sys
from collections.abc import Callable
from dataclasses import dataclass, field, replace
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
BASE = "85b6b6c1c"  # origin/main when the spec was written; every cite is read here

SPEC_REL = "docs/design/E47/E47-D07.md"
HAND_REL = "docs/design/E47/E47-D07-handoff.md"
JSON_REL = "docs/design/E47/E47-D07-transcripts.json"
TOOL_REL = "docs/design/_tools/e47_d07_announcement_audit.py"
PIN_REL = "docs/design/_tools/e47_d07_ruled_pins.txt"
OWN = (SPEC_REL, HAND_REL, JSON_REL, TOOL_REL, PIN_REL)
OWN_BOARDS = re.compile(r"docs/design/E47/img/E47-D07-\d\d-[a-z0-9-]+\.png")
SPEC_BUDGET = 700
HAND_BUDGET = 200


@dataclass(frozen=True)
class Pin:
    key: str
    ticket: str
    sha: str
    rel: str
    branch: str
    pr: int
    merged: bool  # a merge pin must be on origin/main; an in-flight pin must not be passed


# R6: the in-flight siblings at their PR heads, re-pinned to the merge commit at merge.
PINS = (
    Pin("D03", "E47-D03", "73fefc62b", "docs/design/E47/E47-D03.md", "", 5392, True),
    Pin(
        "D04",
        "E47-D04",
        "1ff5d8cb9",
        "docs/design/E47/E47-D04.md",
        "design/e47-d04-focus-landmarks",
        5387,
        False,
    ),
    Pin(
        "D05",
        "E47-D05",
        "3987edc89",
        "docs/design/E47/E47-D05.md",
        "design/e47-scr117-a11y-settings",
        5417,
        False,
    ),
    Pin(
        "D09",
        "E47-D09",
        "260bb0caf",
        "docs/design/E47/E47-D09.md",
        "design/e47-keyboard-operability",
        5418,
        False,
    ),
)

PLAN = {
    "05": "docs/plan/05-accessibility-standard.md",
    "06": "docs/plan/06-performance-and-load-standard.md",
    "11": "docs/plan/11-user-stories.md",
    "14": "docs/plan/14-screens-catalogue.md",
    "15": "docs/plan/15-component-catalogue.md",
    "16": "docs/plan/16-design-system-brief.md",
    "22": "docs/plan/22-api-openapi.yaml",
    "23": "docs/plan/23-ws-protocol.md",
    "24": "docs/plan/24-internal-schemas.md",
}
CITE_FILES = {
    "ANN": "apps/web/src/features/app-shell/announcer.tsx",
    "PW": "apps/web/src/chart/a11y/politeWriter.ts",
    "MODEL": "apps/web/src/features/a11y-preferences/model.ts",
    "D17": "docs/design/E17/E17-D02.md",
    "RA": "docs/design/research/e40-alert-attention.md",
    "LR": "docs/design/a11y/e40-alerts-a11y-review.md",
    "D02E40": "docs/design/E40/E40-D02.md",
    "D03E06": "docs/design/E06/E06-D03.md",
    "D09E09": "docs/design/E09/E09-D09.md",
    "D03E05": "docs/design/E05/E05-D03.md",
    "D07E11": "docs/design/E11/E11-D07.md",
    "DS": ".claude/rules/32-design-specs.md",
    "CAT": "docs/plan/a11y/47-audit-catalogue.md",
    "README": "docs/design/README.md",
    "D03": PINS[0].rel,
    "D04": PINS[1].rel,
    "D05": PINS[2].rel,
    "D09": PINS[3].rel,
}
FILE_BASE = {p.rel: p.sha for p in PINS}

BQ_COMMENT = "6569517412"  # the BQ list on #1306
RULING = "6570054100"  # the ruling of record on that list (2026-11-02 05:45Z)
BQ_HEAD = f"RULED (comment {RULING})"
BQ_IDS = tuple(f"BQ-{n}" for n in range(17))
OVERRIDDEN = frozenset({"BQ-2", "BQ-7", "BQ-8", "BQ-9"})  # the rest are accepted
PENDING_CELL = "pending: drawn later in this PR"
THEMES = ("dark", "light", "hc")

CLASSES = ("significant-assertive", "status-polite", "ambient-polite", "echo-polite", "silent")
RANKS = ("1", "2", "3", "4", "local")
SIX_LINE = 152  # `05`:152, the assertive classes
SIX = (
    "order filled",
    "order rejected",
    "position auto-flattened by risk engine",
    "rule triggered",
    "WS disconnected/reconnected",
    "Demo/Live environment switch confirmed",
)
SLOTS = frozenset(
    (
        "type",
        "side",
        "qty",
        "filled",
        "symbol",
        "price",
        "bid",
        "ask",
        "reason",
        "account",
        "accounts",
        "position_side",
        "name",
        "n",
        "m",
        "env",
        "metric",
        "value",
        "time",
        "amount",
        "pnl_word",
        "cvd_word",
        "trades",
        "net",
        "label",
        "minutes",
        "seconds",
        "state",
    )
)
SECRET_RE = re.compile(r"key|secret|token|totp|otp|code|password|passphrase", re.IGNORECASE)
SIGN_RE = re.compile(r"[+−±]|(?<![\w])-\s*[{0-9]")
UNKNOWN_SENTENCE = "Reason not recognised. See Notifications."  # BQ-11 rider: CMP-060's label
OMS_PICK = ("NATIVE_STOP_REQUIRED", "EXPIRED_UNSENT")
REASON_SPANS = {  # `24` lines holding the closed sets the reason map covers
    "oms": (2205, 2225),
    "omsx": (2228, 2228),
    "refusal": (2392, 2396),
    "risk": (2425, 2425),
    "lockout": (2427, 2427),
}
HANDED = (
    ("D04 W-3", "D04:379"),
    ("D04 W-4", "D04:380"),
    ("D04 W-5", "D04:381"),
    ("D04 W-6", "D04:382"),
    ("D05 W-15", "D05:298"),
    ("D05 W-19", "D05:302"),
    ("D05 W-28", "D05:311"),
    ("D05 W-29", "D05:312"),
    ("D09 W-1", "D09:306"),
    ("D09 W-5", "D09:310"),
    ("D09 W-15", "D09:320"),
    ("D09 W-21", "D09:326"),
    ("D09 W-22", "D09:327"),
    ("D06 W-3", ""),  # E47-D06 has no PR yet: "—" until it is pinned at its PR head
    ("D08 BQ-9", "D03E05:232–233"),  # the words E05-D03 ruled, handed by E47-D08's BQ-9
)
CAT_COUNT_LINE = 48  # CAT:48, "| E47-D07 | 34 |"
T2_LEAD = "**The T2 paragraph"
T2_NAMES = (
    "CMP-079 RbacGate",
    "CMP-019 Icon `lock`",
    "rendering 2a",
    "full label",
    '`aria-disabled="true"`',
    "never `disabled`",
    "in the DOM at mount",
    "`aria-describedby`",
    "one polite announcement",
    "`Ctrl+Shift+M`",
    "`↑` / `↓`",
)
T2_CITERS = ("## 0.", "## 4.", "### 8.1", "### 8.3")

AGENT_RE = re.compile(r"worker|orchestrator|\bagent\b|\blane\b", re.IGNORECASE)
OWNER_OK_RE = re.compile(r"\bE\d\d-[A-Z]+\d\d \(#\d+\)|\bowner")
PUBLIC_RE = re.compile(
    r"https?://|www\.|/home/|/tmp/|localhost|\.local\b|\b[a-z0-9-]+\.(?:com|io|org|net|dev)\b"
    r"|hcl-worker|hpe-worker|\bAnvil\b|main-orchestrator|scratch-anvil|relayroom"
    r"|ghp_|github_pat_|\bsk-[A-Za-z0-9]{8}|\bAKIA[0-9A-Z]{8}",
    re.IGNORECASE,
)

Finding = tuple[str, str, str, str]  # gate, message, doc, region
Values = dict[str, str]


# ---------------------------------------------------------------------------- git and files


def git(*args: str, check: bool = True) -> str:
    return subprocess.run(
        ["git", *args],
        cwd=ROOT,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="strict",
        check=check,
    ).stdout


def git_ok(*args: str) -> bool:
    return (
        subprocess.run(
            ["git", *args],
            cwd=ROOT,
            capture_output=True,
            text=True,
            encoding="utf-8",
            check=False,
        ).returncode
        == 0
    )


@functools.lru_cache(maxsize=64)
def at_base(rel: str) -> str:
    return git("show", f"{FILE_BASE.get(rel, BASE)}:{rel}")


@functools.lru_cache(maxsize=64)
def base_lines(rel: str) -> tuple[str, ...]:
    return tuple(at_base(rel).split("\n"))


def changed_paths() -> tuple[str, ...]:
    fork = git("merge-base", "HEAD", "origin/main").strip()
    tracked = git("diff", "--name-only", fork).split()
    untracked = git("ls-files", "--others", "--exclude-standard").split()
    return tuple(sorted(set(tracked) | set(untracked)))


# ---------------------------------------------------------------------------- markdown model


@dataclass(frozen=True)
class Texts:
    spec: str
    hand: str
    json: str
    changed: tuple[str, ...]

    def doc(self, name: str) -> str:
        return {"spec": self.spec, "hand": self.hand, "json": self.json}[name]


def line_regions(text: str) -> list[str]:
    """The heading path (with an occurrence suffix) of every line; a heading belongs to itself."""
    stack: list[tuple[int, str]] = []
    seen: dict[str, int] = {}
    current = "(top)#1"
    out: list[str] = []
    for line in text.split("\n"):
        m = re.match(r"^(#{1,6}) (.*)$", line)
        if m:
            level = len(m.group(1))
            while stack and stack[-1][0] >= level:
                stack.pop()
            stack.append((level, m.group(2).strip()))
            path = " > ".join(t for _, t in stack)
            seen[path] = seen.get(path, 0) + 1
            current = f"{path}#{seen[path]}"
        out.append(current)
    return out


def section(text: str, prefix: str) -> tuple[int, int, str]:
    """(first body line index, end index, region) of the heading starting with `prefix`."""
    lines = text.split("\n")
    regions = line_regions(text)
    for i, line in enumerate(lines):
        if line.startswith(prefix):
            level = len(line) - len(line.lstrip("#"))
            end = len(lines)
            for j in range(i + 1, len(lines)):
                m = re.match(r"^(#{1,6}) ", lines[j])
                if m and len(m.group(1)) <= level:
                    end = j
                    break
            return i + 1, end, regions[i]
    return 0, 0, f"(missing {prefix})"


def body(text: str, prefix: str) -> list[str]:
    s, e, _ = section(text, prefix)
    return text.split("\n")[s:e]


def cells(line: str) -> list[str]:
    inner = line.strip().removeprefix("|").removesuffix("|")
    return [c.strip() for c in re.split(r"(?<!\\)\|", inner)]


def is_rule_row(line: str) -> bool:
    return bool(re.fullmatch(r"\|[\s:|-]+\|", line.strip()))


def tables(text: str, prefix: str) -> list[list[list[str]]]:
    out: list[list[list[str]]] = []
    cur: list[list[str]] = []
    for line in body(text, prefix):
        if line.strip().startswith("|"):
            if not is_rule_row(line):
                cur.append(cells(line))
        elif cur:
            out.append(cur)
            cur = []
    if cur:
        out.append(cur)
    return out


def first_table(text: str, prefix: str) -> list[list[str]]:
    ts = tables(text, prefix)
    return ts[0] if ts else []


def rows(text: str, prefix: str, width: int) -> list[list[str]]:
    return [r for r in first_table(text, prefix)[1:] if len(r) >= width]


def plain(cell: str) -> str:
    return cell.replace("`", "").strip()


def quoted(cell: str) -> list[str]:
    return re.findall(r'"([^"]*)"', cell.replace("\\|", "|"))


# ---------------------------------------------------------------------------- anchors

ANCHOR_RE = re.compile(
    r"(?<![0-9A-Za-z.,])([0-9A-Za-z.,]+)<!--=([A-Z]+):([a-z0-9.\-]+)-->", re.DOTALL
)
PLACEHOLDER_RE = re.compile(r"\{\{([A-Z]+):([a-z0-9.\-]+)\}\}")
TRANSCRIPT_RE = re.compile(r"\{\{TRANSCRIPT:([a-z]+)\}\}")
ANCHOR_TAG_RE = re.compile(r"<!--=[A-Z]+:[a-z0-9.\-]+-->", re.DOTALL)


def cut_anchors(text: str) -> str:
    return ANCHOR_RE.sub(lambda m: f"<!--={m.group(2)}:{m.group(3)}-->", text)


# ---------------------------------------------------------------------------- spec tables


@dataclass(frozen=True)
class TaxRow:
    tid: str
    cls: str
    rank: str
    panel: str
    words: tuple[str, ...]
    read_at: str


def taxonomy(spec: str) -> dict[str, TaxRow]:
    out: dict[str, TaxRow] = {}
    for r in rows(spec, "## 4.", 9):
        words = () if re.search(r"\bD0\d W-", r[7]) else tuple(re.findall(r"\bW-\d+", r[7]))
        out[r[0]] = TaxRow(r[0], r[3], r[4], r[6], words, r[8])
    return out


def copy_deck(spec: str) -> dict[str, list[str]]:
    return {r[0]: r for r in rows(spec, "### 7.2", 4)}


def template(spec: str, wid: str) -> str:
    row = copy_deck(spec).get(wid)
    if row is None:
        return ""
    qs = quoted(row[1])
    return qs[0] if qs else ""


def reason_map(spec: str) -> dict[str, str]:
    return {plain(r[0]): r[1] for r in rows(spec, "### 7.3", 2)}


def board_rows(spec: str) -> list[list[str]]:
    return rows(spec, "## 0.", 5)


# ---------------------------------------------------------------------------- the model


def lcg(seed: int) -> Callable[[], int]:
    state = [seed % 2**31]

    def nxt() -> int:
        state[0] = (1103515245 * state[0] + 12345) % 2**31
        return state[0] >> 16

    return nxt


def price(ticks: int) -> str:
    whole, frac = divmod(ticks, 10)
    return f"{whole:,}.{frac}"


def estimate(text: str, chars_per_s: int, floor_ms: int) -> int:
    return max(floor_ms, math.ceil(len(text) * 1000 / chars_per_s))


# BQ-7 RULED: the tape is never narrated (prints are silent inputs); whale prints are opt-in
FIELD_ORDER = ("quote", "mark", "pnl", "cvd", "big")
FIELD_ROW = {"quote": "T-30", "mark": "T-31", "pnl": "T-32", "cvd": "T-33", "big": "T-36"}
POLITE_SHARE = 2  # a composite waits >= this many times the previous one's speech estimate (§6.1)
DIALOG_ROW = "T-17"  # its `alertdialog` is the event's one speaker, on focus (§9)


def focus_speech(spec: str, text: str) -> str:
    """What a reader says when the auto-flatten dialog takes focus: name, role, description, button."""
    return f"{template(spec, 'W-40')}, dialog. {text} {template(spec, 'W-41')}, button."


@dataclass
class Item:
    t: int
    seq: int
    kind: str  # "field" | "print" | "event"
    fld: str = ""
    text: str = ""
    side: str = ""
    ticks: int = 0
    tid: str = ""
    entity: str = ""


@dataclass
class Queued:
    rank: int
    seq: int
    t: int
    not_before: int
    tid: str
    entity: str
    text: str


@dataclass(frozen=True)
class Line:
    t: int
    channel: str
    cls: str
    rows: str
    text: str


@dataclass
class Replay:
    lines: list[Line] = field(default_factory=list)
    collapsed: list[tuple[int, str]] = field(default_factory=list)  # (event seq, tid)
    events: list[Item] = field(default_factory=list)
    written: dict[int, int] = field(default_factory=dict)  # event seq -> write time


def render(spec: str, wid: str, slots: dict[str, str]) -> str:
    text = template(spec, wid)
    if "reason" in slots:
        words = reason_map(spec).get(slots["reason"], "(W-36)")
        if words.startswith("(W-36") or not words:
            text = text.replace("Reason: {reason}.", UNKNOWN_SENTENCE)
        else:
            slots = {**slots, "reason": words}
    for k, v in slots.items():
        text = text.replace("{" + k + "}", v)
    return text


def expand(spec: str, script: dict[str, object], seed: int) -> list[Item]:
    items: list[Item] = []
    seq = 0
    duration = int(str(script["duration_ms"]))
    streams = script.get("streams", [])
    assert isinstance(streams, list)
    for k, st in enumerate(streams):
        assert isinstance(st, dict)
        nxt = lcg(seed * 100 + k)
        ticks = int(st["start_ticks"])
        every = int(st["every_ms"])
        to = int(st.get("to_ms", duration))
        t = every  # the first value arrives one period in
        while t < to:
            r = nxt()
            if st["field"] == "tape":
                ticks += (r >> 1) % 3 - 1
                side = "buy" if r % 2 == 0 else "sell"
                items.append(Item(t, seq, "print", "tape", side=side, ticks=ticks))
            else:
                ticks += r % 3 - 1
                if st["field"] == "quote":
                    text = render(spec, "W-28", {"bid": price(ticks), "ask": price(ticks + 1)})
                else:
                    text = render(spec, "W-29", {"price": price(ticks)})
                items.append(Item(t, seq, "field", str(st["field"]), text=text))
            seq += 1
            t += every
    events = script.get("events", [])
    assert isinstance(events, list)
    for ev in events:
        assert isinstance(ev, dict)
        slots = {str(a): str(b) for a, b in dict(ev.get("slots", {})).items()}
        text = render(spec, str(ev["words"]), slots)
        if ev.get("field"):
            items.append(Item(int(ev["t"]), seq, "field", str(ev["field"]), text=text))
        else:
            items.append(
                Item(
                    int(ev["t"]),
                    seq,
                    "event",
                    text=text,
                    tid=str(ev["taxonomy"]),
                    entity=str(ev.get("entity", "")),
                )
            )
        seq += 1
    # within one instant: fields and prints first, then events (stable by seq)
    return sorted(items, key=lambda i: (i.t, i.kind == "event", i.seq))


def eligible(fld: str, s: dict[str, object]) -> bool:
    if s.get("reduce") or s.get("announce_prices") != "always" or s.get("verbosity") == "low":
        return False
    return fld != "big" or s.get("whale") is True  # Normal = High until the owner splits them


def replay(
    spec: str, doc: dict[str, object], script: dict[str, object], s: dict[str, object]
) -> Replay:
    tax = taxonomy(spec)
    seed = int(str(doc["seed"]))
    cps = int(str(doc["speech_chars_per_s"]))
    floor_ms = int(str(doc["speech_floor_ms"]))
    cadence = int(str(s["cadence_ms"]))
    items = expand(spec, script, seed)
    out = Replay(events=[i for i in items if i.kind == "event"])
    never = -(10**9)
    latest: dict[str, str | None] = {f: None for f in FIELD_ORDER}
    spoken: dict[str, str | None] = {f: None for f in FIELD_ORDER}
    last_own, busy_until, gap = never, never, cadence
    due: int | None = None
    queue: list[Queued] = []
    last_partial: dict[str, int] = {}
    k = 0
    while True:
        wake = [items[k].t] if k < len(items) else []
        if due is not None:
            wake.append(max(due, busy_until))
        if queue:
            wake.append(max(busy_until, min(q.not_before for q in queue)))
        if not wake:
            break
        now = min(wake)
        while k < len(items) and items[k].t == now:
            it = items[k]
            k += 1
            if it.kind == "field" and eligible(it.fld, s):
                latest[it.fld] = None if it.text == spoken[it.fld] else it.text
            elif it.kind == "event":
                for f in FIELD_ORDER:
                    latest[f], spoken[f] = None, None
                due = None
                rank = rank_of(tax, it.tid)
                waiting = [q for q in queue if q.entity and q.entity == it.entity]
                if it.tid == "T-2" and any(q.tid == "T-2" for q in waiting):
                    q = next(q for q in waiting if q.tid == "T-2")
                    out.collapsed.append((q.seq, q.tid))
                    q.seq, q.text, q.t = it.seq, it.text, it.t
                    continue
                if it.tid == "T-1":
                    for q in waiting:
                        if q.tid == "T-2":
                            queue.remove(q)
                            out.collapsed.append((q.seq, q.tid))
                nb = last_partial.get(it.entity, never) + cadence if it.tid == "T-2" else never
                queue.append(Queued(rank, it.seq, it.t, nb, it.tid, it.entity, it.text))
        while queue and busy_until <= now:
            ready = [q for q in queue if q.not_before <= now]
            if not ready:
                break
            q = min(ready, key=lambda x: (x.rank, x.seq))
            queue.remove(q)
            channel, text = "assertive", q.text
            if q.tid == DIALOG_ROW:
                channel, text = "focus", focus_speech(spec, q.text)
            out.lines.append(Line(now, channel, "significant-assertive", q.tid, text))
            out.written[q.seq] = now
            busy_until = now + estimate(text, cps, floor_ms)
            if q.tid == "T-2":
                last_partial[q.entity] = now
        pending = any(latest[f] is not None for f in FIELD_ORDER)
        if pending and due is None:
            due = max(last_own + gap, now)
        if due is not None and due <= now and busy_until <= now:
            parts: list[tuple[str, str]] = []
            for f in FIELD_ORDER:
                if latest[f] is not None:
                    parts.append((f, str(latest[f])))
                    spoken[f] = latest[f]
                latest[f] = None
            due = None
            if parts:
                tids = " ".join(FIELD_ROW[f] for f, _ in parts)
                text = ". ".join(p for _, p in parts)
                out.lines.append(Line(now, "polite", "ambient-polite", tids, text))
                last_own = now
                gap = max(cadence, POLITE_SHARE * estimate(text, cps, floor_ms))
    return out


CELLS: dict[str, dict[str, object]] = {
    "off": {"announce_prices": "off", "verbosity": "normal"},
    "significant": {"announce_prices": "significant", "verbosity": "normal"},
    "always-low": {"announce_prices": "always", "verbosity": "low"},
    "always-normal": {"announce_prices": "always", "verbosity": "normal"},
    "always-high": {"announce_prices": "always", "verbosity": "high"},
    "always-whale": {"announce_prices": "always", "verbosity": "normal", "whale": True},
    "reduce": {"announce_prices": "always", "verbosity": "normal", "reduce": True},
}


def load_json(t: Texts) -> dict[str, object] | None:
    try:
        doc = json.loads(t.json)
    except json.JSONDecodeError:
        return None
    return doc if isinstance(doc, dict) else None


def scripts(doc: dict[str, object]) -> list[dict[str, object]]:
    s = doc.get("scripts", [])
    return [x for x in s if isinstance(x, dict)] if isinstance(s, list) else []


def line_dict(ln: Line) -> dict[str, object]:
    return {"t": ln.t, "channel": ln.channel, "class": ln.cls, "rows": ln.rows, "text": ln.text}


def transcript_rows(script: dict[str, object]) -> str:
    head = "| t (s) | Channel | Rows | Line |\n| ----- | ------- | ---- | ---- |\n"
    exp = script.get("expected", [])
    lines = [x for x in exp if isinstance(x, dict)] if isinstance(exp, list) else []
    return head + "\n".join(
        f"| {int(str(x['t'])) / 1000:.3f} | {x['channel']} | {x['rows']} | {x['text']} |"
        for x in lines
    )


# ---------------------------------------------------------------------------- values


def count_values(t: Texts) -> Values:
    tax = taxonomy(t.spec)
    boards = board_rows(t.spec)
    return {
        "COUNT:boards": str(len(boards)),
        "COUNT:boards.twins": str(sum(1 for r in boards if r[3] != "dark")),
        "COUNT:taxonomy": str(len(tax)),
        "COUNT:taxonomy.assertive": str(
            sum(1 for r in tax.values() if r.cls == "significant-assertive")
        ),
        "COUNT:taxonomy.silent": str(sum(1 for r in tax.values() if r.cls == "silent")),
        "COUNT:assertive-set": str(len(rows(t.spec, "### 3.2", 4))),
        "COUNT:slots": str(len(SLOTS)),
        "COUNT:copy": str(len(copy_deck(t.spec))),
        "COUNT:reasons": str(len(reason_map(t.spec))),
        "COUNT:labels": str(len(rows(t.spec, "### 7.4", 5))),
        "COUNT:panel": str(len(rows(t.spec, "### 8.1", 4))),
        "COUNT:findings": str(len(rows(t.spec, "## 11.", 3))),
        "COUNT:heuristics": str(len(rows(t.spec, "## 13.", 3))),
        "COUNT:walkthrough": str(sum(1 for ln in body(t.hand, "## §E") if ln.startswith("- ["))),
    }


def sim_values(t: Texts) -> Values:
    doc = load_json(t)
    if doc is None:
        return {}
    out: Values = {}
    for sc in scripts(doc):
        sid = str(sc["id"])
        settings = sc.get("settings")
        if not isinstance(settings, dict):
            continue
        rp = replay(t.spec, doc, sc, settings)
        out[f"SIM:{sid}.lines"] = str(len(rp.lines))
        out[f"SIM:{sid}.polite"] = str(sum(1 for ln in rp.lines if ln.channel == "polite"))
        out[f"SIM:{sid}.assertive"] = str(sum(1 for ln in rp.lines if ln.channel == "assertive"))
        per = [sum(1 for ln in rp.lines if FIELD_ROW[f] in ln.rows.split()) for f in FIELD_ORDER]
        out[f"SIM:{sid}.max-per-field"] = str(max(per))
        cps, floor_ms = int(str(doc["speech_chars_per_s"])), int(str(doc["speech_floor_ms"]))
        pol = [ln for ln in rp.lines if ln.channel == "polite"]
        said = [estimate(ln.text, cps, floor_ms) for ln in pol]
        cad = int(str(settings["cadence_ms"]))
        spans = [b.t - a.t for a, b in itertools.pairwise(pol)]
        spans += [max(cad, POLITE_SHARE * said[-1])] if said else []
        out[f"SIM:{sid}.polite-share"] = str(round(100 * sum(said) / max(1, sum(spans))))
        if sid == "fast":
            minutes = int(str(sc["duration_ms"])) / 60000
            for cell, cs in CELLS.items():
                c = {**settings, "reduce": False, **cs}
                polite = [ln for ln in replay(t.spec, doc, sc, c).lines if ln.channel == "polite"]
                n = sum(len(ln.rows.split()) for ln in polite)
                out[f"SIM:cell.{cell}"] = str(round(n / minutes))
    return out


def compute_values(t: Texts) -> Values:
    return {**count_values(t), **sim_values(t)}


# ---------------------------------------------------------------------------- mutations


@dataclass(frozen=True)
class Mutation:
    mid: str
    what: str
    gate: str
    doc: str  # spec | hand | json | changed
    where: str  # a heading prefix, "" for the whole text, "<eof>" to append
    old: str
    new: str


def _m(mid: str, what: str, gate: str, doc: str, where: str, old: str, new: str) -> Mutation:
    return Mutation(mid, what, gate, doc, where, old, new)


MUTATIONS: tuple[Mutation, ...] = (
    _m(
        "M-1",
        "mark board 01 drawn in §0",
        "G-BOARDS",
        "spec",
        "## 0.",
        "| dark  | pending: drawn later in this PR |",
        "| dark  | drawn |",
    ),
    _m(
        "M-2",
        "give T-11 the class status-polite",
        "G-CLASSES",
        "spec",
        "## 4.",
        "| `positions` (`23`:859) | significant-assertive",
        "| `positions` (`23`:859) | status-polite",
    ),
    _m(
        "M-3",
        "re-word an assertive-set entry from `05`:152",
        "G-CLASSES",
        "spec",
        "### 3.2",
        "| order rejected ",
        "| order refused ",
    ),
    _m(
        "M-4",
        "move T-30 into the Alerts panel class",
        "G-CLASSES",
        "spec",
        "### 8.1",
        "| T-29                           |",
        "| T-29, T-30                     |",
    ),
    _m(
        "M-5",
        "write a glyph sign into W-30",
        "G-COPY",
        "spec",
        "### 7.2",
        '"{symbol} position {pnl_word} {amount} USDT"',
        '"{symbol} position +{amount} USDT"',
    ),
    _m(
        "M-6",
        "give W-27 a secret slot",
        "G-COPY",
        "spec",
        "### 7.2",
        '"Not sent. {reason}."',
        '"Not sent. {totp_code}."',
    ),
    _m(
        "M-7",
        "drop LEVERAGE_ERROR from the reason map",
        "G-COPY",
        "spec",
        "### 7.3",
        "| `LEVERAGE_ERROR`             | leverage not accepted                         |\n",
        "",
    ),
    _m(
        "M-8",
        "re-word a line of §10.3's table",
        "G-SIM",
        "spec",
        "### 10.3",
        "closed by the risk engine",
        "closed by risk",
    ),
    _m(
        "M-9",
        "re-word an expected line in the JSON",
        "G-SIM",
        "json",
        "",
        "Auto-flattened.",
        "Auto flattened.",
    ),
    _m(
        "M-10",
        "set the quiet script's cadence to 5 s in the JSON",
        "G-SIM",
        "json",
        "",
        '"cadence_ms": 2000',
        '"cadence_ms": 5000',
    ),
    _m(
        "M-11",
        "re-word D04 W-4's source string in §7.4",
        "G-LABELS",
        "spec",
        "### 7.4",
        '"{price} gone, focused {price}"',
        '"{price} gone, focus on {price}"',
    ),
    _m(
        "M-12",
        "drop A11Y-F-0015 from §11",
        "G-FIND",
        "spec",
        "## 11.",
        "| A11Y-F-0015 ",
        "| A11Y-F-9015 ",
    ),
    _m(
        "M-13",
        "drop CMP-079 from §8.2's T2 paragraph",
        "G-T2",
        "spec",
        "### 8.2",
        "wrapped by CMP-079 RbacGate",
        "wrapped by RbacGate",
    ),
    _m(
        "M-14",
        "drop §8.2's cite from §8.1's safety row",
        "G-T2",
        "spec",
        "### 8.1",
        "fixed: T2 per §8.2",
        "fixed: T2",
    ),
    _m(
        "M-15",
        "drop CMP-019 from the hand-off's component line",
        "G-T2",
        "hand",
        "",
        "with the **CMP-019 Icon** `lock` glyph",
        "with the `lock` glyph",
    ),
    _m(
        "M-16",
        "write a host beside the Penpot file in §0",
        "G-PUBLIC",
        "spec",
        "## 0.",
        "Penpot file `E47-D07 boards` (README:14)",
        "Penpot file `E47-D07 boards` at design.example.com (README:14)",
    ),
    _m(
        "M-17",
        "mark BQ-4 overridden",
        "G-RULED",
        "spec",
        "## The questions",
        "- **BQ-4** RULED, ACCEPT:",
        "- **BQ-4** RULED, OVERRIDE:",
    ),
    _m(
        "M-18",
        "point a cite past the end of ANN",
        "G-CITE",
        "spec",
        "## 2.",
        "renders `ShellAnnouncer` once (ANN:4)",
        "renders `ShellAnnouncer` once (ANN:4000)",
    ),
    _m(
        "M-19",
        "re-word W-23",
        "G-QUOTE",
        "spec",
        "### 7.2",
        '"Connection unstable."',
        '"Connection is unstable."',
    ),
    _m(
        "M-20",
        "re-word D07-A8's Old fragment",
        "G-AROW",
        "hand",
        "## §C",
        "| announcements come from CMP-212's two regions ",
        "| announcements come from CMP-212's regions ",
    ),
    _m(
        "M-21",
        "change the D05 pin in the start line",
        "G-PIN",
        "spec",
        "",
        "`3987edc89` (E47-D05, PR #5417)",
        "`3987edc88` (E47-D05, PR #5417)",
    ),
    _m(
        "M-22",
        "drop `(heuristic)` from H-3",
        "G-HEUR",
        "spec",
        "## 13.",
        "| H-3 | (heuristic) Error",
        "| H-3 | Error",
    ),
    _m(
        "M-23",
        "add two walkthrough items in the hand-off's §E",
        "G-WALK",
        "hand",
        "## §E",
        "- [ ] Record `approved`",
        "- [ ] extra one.\n- [ ] extra two.\n- [ ] Record `approved`",
    ),
    _m(
        "M-24",
        "name an agent as D07-G6's owner",
        "G-OWNER",
        "spec",
        "### 15.2",
        "| E47-Q01 (#1314)                               | E47-Q02 (#1355) |",
        "| the design worker                             | E47-Q02 (#1355) |",
    ),
    _m(
        "M-25",
        "name CMP-060 a Toast",
        "G-COMP",
        "hand",
        "",
        "**CMP-060 NotificationCenter**",
        "**CMP-060 Toast**",
    ),
    _m("M-26", "touch `24` in the working tree", "G-UNTOUCHED", "changed", "", "", PLAN["24"]),
    _m("M-27", "pad the spec past its line budget", "G-BUDGET", "spec", "<eof>", "", "\n" * 200),
    _m(
        "M-28",
        "change the boards count in the header",
        "G-ANCHOR",
        "spec",
        "",
        "10<!--=COUNT:boards--> boards of §0",
        "9<!--=COUNT:boards--> boards of §0",
    ),
    _m(
        "M-29",
        "leave a placeholder unfilled",
        "G-MARKER",
        "spec",
        "### 7.3",
        "<!--=COUNT:reasons--> codes",
        "{{COUNT:reasons}} codes",
    ),
    _m(
        "M-30",
        "replace a mutation row's gate in §14",
        "G-MUTLIST",
        "spec",
        "## 14.",
        "| M-1  | mark board 01 drawn in §0 | G-BOARDS |",
        "| M-1  | mark board 01 drawn in §0 | G-HEUR |",
    ),
    _m(
        "M-31",
        "flip a prose sentence in §9",
        "G-RULED-PIN",
        "spec",
        "## 9.",
        "An announcement never moves focus",
        "An announcement rarely moves focus",
    ),
)


def mutation_rows(ms: tuple[Mutation, ...] = MUTATIONS) -> str:
    head = "| M    | Mutation | Gate |\n| ---- | -------- | ---- |\n"
    return head + "\n".join(f"| {m.mid} | {m.what} | {m.gate} |" for m in ms)


def apply_mutation(t: Texts, m: Mutation) -> Texts:
    if m.doc == "changed":
        return replace(t, changed=(*t.changed, m.new))
    text = t.doc(m.doc)
    if m.where == "<eof>":
        new_text = text + m.new
    else:
        if m.where:
            s, e, _ = section(text, m.where)
            lines = text.split("\n")
            offset = len("\n".join(lines[:s])) + (1 if s else 0)
            span = "\n".join(lines[s:e])
        else:
            offset, span = 0, text
        # runs of spaces match any run, so table padding from the formatter never breaks a target
        found = re.search(re.sub(r"(?:\\ )+", "[ ]+", re.escape(m.old)), span)
        if found is None:
            raise SystemExit(f"FAIL {m.mid}: its target text is not in {m.doc} {m.where!r}")
        k = found.start() + offset
        new_text = text[:k] + m.new + text[k + len(found.group(0)) :]
    if m.doc == "spec":
        return replace(t, spec=new_text)
    if m.doc == "hand":
        return replace(t, hand=new_text)
    return replace(t, json=new_text)


# ---------------------------------------------------------------------------- form gates


def g_anchor(t: Texts, values: Values) -> list[Finding]:
    out: list[Finding] = []
    for doc in ("spec", "hand"):
        text = t.doc(doc)
        regions = line_regions(text)
        for i, line in enumerate(text.split("\n")):
            for m in ANCHOR_RE.finditer(line):
                key = f"{m.group(2)}:{m.group(3)}"
                want = values.get(key)
                if want is None:
                    out.append(("G-ANCHOR", f"unknown anchor {key}", doc, regions[i]))
                elif m.group(1) != want:
                    out.append(
                        ("G-ANCHOR", f"{key} reads {m.group(1)}, derives {want}", doc, regions[i])
                    )
    return out


def g_marker(t: Texts) -> list[Finding]:
    out: list[Finding] = []
    for doc in ("spec", "hand"):
        text = t.doc(doc)
        regions = line_regions(text)
        for i, line in enumerate(text.split("\n")):
            if "{{" in line:
                out.append(("G-MARKER", f"unfilled placeholder on line {i + 1}", doc, regions[i]))
            if "<!--" in ANCHOR_TAG_RE.sub("", line):
                out.append(("G-MARKER", f"a stray HTML comment on line {i + 1}", doc, regions[i]))
    return out


CITE_KEYS = sorted(CITE_FILES, key=len, reverse=True)
CITE_RE = re.compile(
    r"(?:`(\d\d)`|\b(" + "|".join(CITE_KEYS) + r"))(:\d+(?:–\d+)?(?:, :\d+(?:–\d+)?)*)"
)


def cite_targets(line: str) -> list[tuple[str, int]]:
    out: list[tuple[str, int]] = []
    for m in CITE_RE.finditer(line):
        rel = PLAN.get(m.group(1) or "") or CITE_FILES.get(m.group(2) or "")
        if rel is None:
            out.append((f"?{m.group(1)}", 0))
            continue
        for a, b in re.findall(r":(\d+)(?:–(\d+))?", m.group(3)):
            out.append((rel, int(a)))
            if b:
                out.append((rel, int(b)))
    return out


def g_cite(t: Texts) -> list[Finding]:
    out: list[Finding] = []
    for doc in ("spec", "hand"):
        text = t.doc(doc)
        regions = line_regions(text)
        for i, line in enumerate(text.split("\n")):
            for rel, n in cite_targets(line):
                if rel.startswith("?"):
                    out.append(("G-CITE", f"unknown cite key {rel[1:]}", doc, regions[i]))
                    continue
                lines = base_lines(rel)
                if not (1 <= n <= len(lines)) or not lines[n - 1].strip():
                    out.append(("G-CITE", f"{rel}:{n} is not a non-blank line", doc, regions[i]))
    return out


def cited_text(cite_cell: str) -> str:
    return "\n".join(
        base_lines(rel)[n - 1]
        for rel, n in cite_targets(cite_cell)
        if not rel.startswith("?") and 1 <= n <= len(base_lines(rel))
    )


def g_quote(t: Texts) -> list[Finding]:
    out: list[Finding] = []
    _, _, region = section(t.spec, "### 7.2")
    for r in rows(t.spec, "### 7.2", 4):
        if not r[3].startswith("verbatim"):
            continue
        src = cited_text(r[2])
        if not quoted(r[1]) or any(q not in src for q in quoted(r[1])):
            out.append(("G-QUOTE", f"{r[0]} is not verbatim on {r[2]}", "spec", region))
    return out


def g_arow(t: Texts) -> list[Finding]:
    out: list[Finding] = []
    _, _, region = section(t.hand, "## §C")
    for r in rows(t.hand, "## §C", 5):
        if r[3].replace("\\|", "|") not in cited_text(r[2]):
            out.append(("G-AROW", f"{r[0]}'s Old is not verbatim on its line", "hand", region))
    return out


def g_pin(t: Texts) -> list[Finding]:
    lines, regions = t.spec.split("\n"), line_regions(t.spec)
    start = [i for i, ln in enumerate(lines) if ln.startswith("**Start.**")]
    region = regions[start[0]] if len(start) == 1 else "(top)#1"
    line = lines[start[0]] if len(start) == 1 else ""
    bad: list[str] = []
    for p in PINS:
        if f"`{p.sha}` ({p.ticket}, PR #{p.pr})" not in line:
            bad.append(f"the start line does not pin {p.key} at {p.sha} (PR #{p.pr})")
        if not git_ok("cat-file", "-e", f"{p.sha}:{p.rel}"):
            bad.append(f"{p.sha}:{p.rel} is not readable")
            continue
        merged = git_ok("merge-base", "--is-ancestor", p.sha, "origin/main")
        if p.merged and not merged:
            bad.append(f"{p.key}'s merge pin {p.sha} is not on origin/main")
        for ref in (f"refs/remotes/origin/{p.branch}", f"refs/heads/{p.branch}"):
            if not p.branch:
                break
            tip = git("rev-parse", "--verify", "-q", ref, check=False).strip()
            if tip and not tip.startswith(p.sha) and not merged:
                bad.append(f"{p.key}'s branch moved past {p.sha}; re-pin (R6)")
                break
    if "E47-D06 (#1305) is in flight" not in line:
        bad.append("the start line does not name E47-D06 as in flight")
    return [("G-PIN", b, "spec", region) for b in bad]


# ---------------------------------------------------------------------------- content gates


def g_classes(t: Texts) -> list[Finding]:
    bad: list[tuple[str, str]] = []
    _, _, r31 = section(t.spec, "### 3.1")
    _, _, r32 = section(t.spec, "### 3.2")
    _, _, r4 = section(t.spec, "## 4.")
    _, _, r81 = section(t.spec, "### 8.1")
    if tuple(plain(r[0]) for r in rows(t.spec, "### 3.1", 3)) != CLASSES:
        bad.append(("§3.1's classes are not the five", r31))
    tax = taxonomy(t.spec)
    if [k for k in tax] != [f"T-{n}" for n in range(1, len(tax) + 1)]:
        bad.append(("the T-rows are not numbered T-1 onward", r4))
    for tr in tax.values():
        if tr.cls not in CLASSES:
            bad.append((f"{tr.tid} has class {tr.cls!r}", r4))
        elif (tr.cls == "significant-assertive") != (tr.rank in RANKS):
            bad.append((f"{tr.tid}'s rank {tr.rank!r} does not fit {tr.cls}", r4))
        elif tr.cls != "significant-assertive" and tr.rank != "—":
            bad.append((f"{tr.tid} has a rank but is not assertive", r4))
    aset = rows(t.spec, "### 3.2", 4)
    six = base_lines(PLAN["05"])[SIX_LINE - 1]
    if tuple(r[0] for r in aset[: len(SIX)]) != SIX:
        bad.append(("§3.2 does not open with `05`:152's six", r32))
    bad += [(f"{c!r} is not on `05`:152", r32) for c in SIX if c not in six]
    for i, r in enumerate(aset):
        ids = re.findall(r"T-\d+", r[2])
        if not ids or any(tax.get(x, TaxRow(x, "", "", "", (), "")).cls != CLASSES[0] for x in ids):
            bad.append((f"{r[0]!r} has no assertive T-row", r32))
        if i >= len(SIX) and not r[3].startswith("PROPOSED"):
            bad.append((f"{r[0]!r} is an addition not marked PROPOSED", r32))
    panel = {r[0]: r for r in rows(t.spec, "### 8.1", 4)}
    seen: dict[str, str] = {}
    for name, r in panel.items():
        for x in re.findall(r"T-\d+", r[1]):
            if x in seen:
                bad.append((f"{x} is in two panel classes", r81))
            seen[x] = name
            row = tax.get(x)
            if row is None or row.panel != name:
                bad.append((f"{x} is under {name!r} but its row says otherwise", r81))
            elif (row.cls == CLASSES[0]) != (r[2] == "Assertive"):
                bad.append((f"{name!r}'s default does not fit {x}'s class", r81))
    safety = {x for r in aset if "fixed safety group" in r[3] for x in re.findall(r"T-\d+", r[2])}
    fixed = [r for r in panel.values() if r[3].startswith("fixed")]
    if len(fixed) != 1 or set(re.findall(r"T-\d+", fixed[0][1])) != safety | {DIALOG_ROW}:
        bad.append(("the fixed panel class is not the safety group plus the auto-flatten", r81))
    for tr in tax.values():
        announced = tr.cls != "silent" and tr.rank != "local"
        if announced and tr.tid not in seen:
            bad.append((f"{tr.tid} is announced but in no panel class", r81))
    return [("G-CLASSES", b, "spec", reg) for b, reg in bad]


def closed_sets() -> dict[str, tuple[str, ...]]:
    lines = base_lines(PLAN["24"])

    def span(key: str) -> list[str]:
        a, b = REASON_SPANS[key]
        return list(lines[a - 1 : b])

    oms = tuple(m.group(1) for ln in span("oms") if (m := re.match(r"^\s+(\w+) = \"", ln)))
    refusal = tuple(m.group(1) for ln in span("refusal") if (m := re.match(r"^\| `(\w+)`", ln)))
    risk = tuple(re.findall(r"`(\w+)`", cells(span("risk")[0])[1]))
    lockout = tuple(re.findall(r"`(\w+)`", cells(span("lockout")[0])[1]))
    omsx = tuple(c for c in OMS_PICK if f"`{c}`" in span("omsx")[0])
    return {"oms": oms, "omsx": omsx, "refusal": refusal, "risk": risk, "lockout": lockout}


def g_copy(t: Texts) -> list[Finding]:
    bad: list[tuple[str, str]] = []
    _, _, r72 = section(t.spec, "### 7.2")
    _, _, r73 = section(t.spec, "### 7.3")
    _, _, r4 = section(t.spec, "## 4.")
    deck = copy_deck(t.spec)
    for wid, r in deck.items():
        qs = quoted(r[1])
        if not qs:
            bad.append((f"{wid} has no quoted string", r72))
        for q in qs:
            for slot in re.findall(r"\{([^}]*)\}", q):
                if slot not in SLOTS or SECRET_RE.search(slot):
                    bad.append((f"{wid} has the slot {{{slot}}} outside the closed set", r72))
            if SIGN_RE.search(q):
                bad.append((f"{wid} speaks a sign glyph", r72))
    if template(t.spec, "W-36") != UNKNOWN_SENTENCE:
        bad.append(("W-36 is not BQ-11's unknown-reason sentence", r72))
    for tr in taxonomy(t.spec).values():
        if tr.cls == "silent" and (tr.words or tr.read_at in ("", "—")):
            bad.append((f"{tr.tid} is silent without a place to read it", r4))
        for w in tr.words:
            if w not in deck:
                bad.append((f"{tr.tid} names {w}, not in the deck", r4))
    rmap = reason_map(t.spec)
    want = [c for cs in closed_sets().values() for c in cs]
    if len(closed_sets()["oms"]) != 21 or len(closed_sets()["refusal"]) != 5:
        bad.append(("`24`'s closed sets did not read as 21 + 5 codes; re-pin REASON_SPANS", r73))
    for c in want:
        if c not in rmap:
            bad.append((f"`24`'s {c} has no words", r73))
    for c, w in rmap.items():
        if c not in want:
            bad.append((f"{c} is not a `24` code", r73))
        if not w or len(w) > 60 or SIGN_RE.search(w):
            bad.append((f"{c}'s words are empty, long or signed", r73))
    return [("G-COPY", b, "spec", reg) for b, reg in bad]


def rank_of(tax: dict[str, TaxRow], tid: str) -> int:
    row = tax.get(tid)
    return int(row.rank) if row is not None and row.rank.isdigit() else 9


def truth_latest(spec: str, doc: dict[str, object], script: dict[str, object]) -> list[Item]:
    return [i for i in expand(spec, script, int(str(doc["seed"]))) if i.kind == "field"]


def g_sim(t: Texts) -> list[Finding]:
    bad: list[tuple[str, str]] = []
    _, _, r10 = section(t.spec, "## 10.")
    doc = load_json(t)
    if doc is None:
        return [("G-SIM", "the transcripts JSON does not parse", "spec", r10)]
    cps, floor_ms = int(str(doc["speech_chars_per_s"])), int(str(doc["speech_floor_ms"]))
    tax = taxonomy(t.spec)
    ids = []
    for sc in scripts(doc):
        sid = str(sc.get("id"))
        ids.append(sid)
        settings = sc.get("settings")
        if not isinstance(settings, dict):
            bad.append((f"{sid} has no settings", r10))
            continue
        rp = replay(t.spec, doc, sc, settings)
        got = [line_dict(ln) for ln in rp.lines]
        if got != sc.get("expected"):
            bad.append((f"{sid}: the replay differs from the expected lines", r10))
        cadence = int(str(settings["cadence_ms"]))
        fields = truth_latest(t.spec, doc, sc)
        for f in FIELD_ORDER:
            times = [ln.t for ln in rp.lines if FIELD_ROW[f] in ln.rows.split()]
            if any(b - a < cadence for a, b in itertools.pairwise(times)):
                bad.append((f"{sid}: {f} written twice inside one cadence", r10))
        for ln in rp.lines:
            if ln.channel != "polite":
                continue
            parts = dict(zip(ln.rows.split(), ln.text.split(". "), strict=False))
            for f in ("quote", "mark", "big"):
                said = parts.get(FIELD_ROW[f])
                prior = [i.text for i in fields if i.fld == f and i.t <= ln.t]
                if said is not None and (not prior or said != prior[-1]):
                    bad.append((f"{sid}: {f} at {ln.t} ms is not the latest value", r10))
        done = set(rp.written) | {s for s, _ in rp.collapsed}
        for ev in rp.events:
            if ev.seq not in done:
                bad.append((f"{sid}: {ev.tid} at {ev.t} ms was dropped", r10))
            if ev.tid != "T-2" and ev.seq in {s for s, _ in rp.collapsed}:
                bad.append((f"{sid}: {ev.tid} collapsed, only a partial may", r10))
        ass = [ln for ln in rp.lines if ln.channel in ("assertive", "focus")]
        for a, b in itertools.pairwise(ass):
            if b.t - a.t < estimate(a.text, cps, floor_ms):
                bad.append((f"{sid}: an assertive line cut the one before it", r10))
        pol = [ln for ln in rp.lines if ln.channel == "polite"]
        for a, b in itertools.pairwise(pol):
            if b.t - a.t < max(cadence, POLITE_SHARE * estimate(a.text, cps, floor_ms)):
                bad.append((f"{sid}: a composite at {b.t} ms talks over the speech share", r10))
        if any(ln.channel == "focus" and ln.rows != DIALOG_ROW for ln in rp.lines):
            bad.append((f"{sid}: a focus line is not the auto-flatten dialog", r10))
        for ev in rp.events:
            w = rp.written.get(ev.seq)
            if w is None or ev.tid == "T-2":
                continue
            for other in rp.events:
                ow = rp.written.get(other.seq)
                if other.tid == "T-2" or ow is None or other.seq == ev.seq:
                    continue
                if other.t <= w < ow and rank_of(tax, other.tid) < rank_of(tax, ev.tid):
                    bad.append((f"{sid}: {ev.tid} spoken before the higher {other.tid}", r10))
        if sid in ("fast", "incident"):
            base = [ln for ln in rp.lines if ln.channel in ("assertive", "focus")]
            for cell, cs in CELLS.items():
                c = {**settings, "reduce": False, **cs}
                other_ass = [
                    ln
                    for ln in replay(t.spec, doc, sc, c).lines
                    if ln.channel in ("assertive", "focus")
                ]
                if other_ass != base:
                    bad.append((f"{sid}: the assertive lines change under {cell}", r10))
        s, e, reg = section(t.spec, TRANSCRIPT_SECTIONS.get(sid, "### 10.3"))
        table = [
            cells(x) for x in t.spec.split("\n")[s:e] if x.startswith("|") and not is_rule_row(x)
        ]
        want = [cells(x) for x in transcript_rows(sc).split("\n") if not is_rule_row(x)]
        if table != want:
            bad.append((f"{sid}: the annotated table differs from the transcript", reg))
    if ids != ["quiet", "fast", "incident"]:
        bad.append((f"the scripts are {ids}, not quiet, fast, incident", r10))
    return [("G-SIM", b, "spec", reg) for b, reg in bad]


def g_labels(t: Texts) -> list[Finding]:
    _, _, region = section(t.spec, "### 7.4")
    got = {r[0]: r for r in rows(t.spec, "### 7.4", 5)}
    bad: list[str] = []
    if tuple(got) != tuple(h for h, _ in HANDED):
        bad.append(f"the handed labels are {tuple(got)}")
    for label, cite in HANDED:
        r = got.get(label)
        if r is None:
            continue
        if not cite:  # an unpinned sibling: no line to check until its PR opens
            if r[2] != "—" or not quoted(r[1]):
                bad.append(f"{label} is unpinned but names a source")
        else:
            src = " ".join(cited_text(cite).split("\n")).replace("\\|", "|")
            if r[2] != cite or not quoted(r[1]) or any(q not in src for q in quoted(r[1])):
                bad.append(f"{label} is not verbatim at {cite}")
        if not r[3] or r[4] not in CLASSES:
            bad.append(f"{label} is not worded with a class")
    return [("G-LABELS", b, "spec", region) for b in bad]


def cat_owned() -> tuple[dict[str, int], dict[str, int]]:
    """CAT's E47-D07 rows: (screen-mapped id -> first line, unmapped id -> first line)."""
    mapped: dict[str, int] = {}
    unmapped: dict[str, int] = {}
    for n, ln in enumerate(base_lines(CITE_FILES["CAT"]), 1):
        if not ln.startswith("| A11Y"):
            continue
        c = cells(ln)
        if len(c) >= 10 and c[-2].split(":")[0].strip() == "E47-D07":
            mapped.setdefault(c[0], n)
        elif len(c) == 5 and c[3] == "E47-D07":
            unmapped.setdefault(c[0], n)
    return mapped, unmapped


def g_find(t: Texts) -> list[Finding]:
    _, _, region = section(t.spec, "## 11.")
    mapped, unmapped = cat_owned()
    want = {**mapped, **{k: v for k, v in unmapped.items() if k not in mapped}}
    got = {r[0]: r for r in rows(t.spec, "## 11.", 3)}
    bad: list[str] = []
    if set(got) != set(want):
        bad.append(f"§11 differs from CAT: {sorted(set(got) ^ set(want))[:3]}")
    for fid, r in got.items():
        if fid in want and r[1] != f":{want[fid]}":
            bad.append(f"{fid} is at CAT:{want[fid]}, not {r[1]}")
        if not re.match(r"^(R|R-\d+|owner \()", r[2]):
            bad.append(f"{fid} has no disposition")
    count = cells(base_lines(CITE_FILES["CAT"])[CAT_COUNT_LINE - 1])
    if count[:1] != ["E47-D07"] or count[1:2] != [str(len(mapped))]:
        bad.append("CAT:48's count is not the screen-mapped rows")
    return [("G-FIND", b, "spec", region) for b in bad]


def g_t2(t: Texts) -> list[Finding]:
    out: list[Finding] = []
    s, e, region = section(t.spec, "### 8.2")
    para = [ln for ln in t.spec.split("\n") if T2_LEAD in ln]
    inside = [ln for ln in t.spec.split("\n")[s:e] if T2_LEAD in ln]
    if len(para) != 1 or len(inside) != 1:
        out.append(("G-T2", f"the T2 paragraph is stated {len(para)} times", "spec", region))
    else:
        out += [
            ("G-T2", f"the T2 paragraph does not name {n}", "spec", region)
            for n in T2_NAMES
            if n not in para[0]
        ]
    for prefix in T2_CITERS:
        s2, e2, reg = section(t.spec, prefix)
        for ln in t.spec.split("\n")[s2:e2]:
            # E17-D02's stale threshold ("Stale ≥ T2", "Stale < T2") is not the T2 gate
            if re.search(r"\bT2\b", re.sub(r"[<≥] T2\b", "", ln)) and "§8.2" not in ln:
                out.append(("G-T2", f"a {prefix} line shows T2 without citing §8.2", "spec", reg))
    lines, regions = t.hand.split("\n"), line_regions(t.hand)
    comp = [i for i, ln in enumerate(lines) if ln.startswith("Components: ")]
    if len(comp) != 1 or not all(x in lines[comp[0]] for x in ("CMP-079 RbacGate", "CMP-019")):
        reg = regions[comp[0]] if len(comp) == 1 else ""
        out.append(("G-T2", "the hand-off's component line omits CMP-079 or CMP-019", "hand", reg))
    return out


@functools.lru_cache(maxsize=1)
def cmp_names() -> dict[str, str]:
    out: dict[str, str] = {}
    for ln in base_lines(PLAN["15"]):
        m = re.match(r"^### (CMP-\d{3}) (\S+)", ln)
        if m:
            out[m.group(1)] = m.group(2)
    return out


def g_comp(t: Texts) -> list[Finding]:
    names = cmp_names()
    out: list[Finding] = []
    for doc in ("spec", "hand"):
        text = t.doc(doc)
        regions = line_regions(text)
        for i, line in enumerate(text.split("\n")):
            for m in re.finditer(r"\b(CMP-\d{3})(?:(?:\*\*)? (?:\*\*)?([A-Z][A-Za-z]+))?", line):
                cid, name = m.group(1), m.group(2)
                if cid not in names:
                    out.append(("G-COMP", f"{cid} has no `15` heading", doc, regions[i]))
                elif name and not (names[cid].startswith(name) or name.startswith(names[cid])):
                    out.append(("G-COMP", f"{cid} is {names[cid]}, not {name}", doc, regions[i]))
    return out


def g_ruled(t: Texts) -> list[Finding]:
    s, e, region = section(t.spec, "## The questions")
    head = t.spec.split("\n")[s - 1] if s else ""
    lines = t.spec.split("\n")[s:e]
    bad: list[str] = []
    if BQ_HEAD not in head:
        bad.append("the heading does not name the ruling of record")
    if not any(BQ_COMMENT in ln and RULING in ln for ln in lines):
        bad.append("the lead does not name the BQ list and the ruling")
    for bq in BQ_IDS:
        found = [ln for ln in lines if ln.startswith(f"- **{bq}**")]
        verdict = "OVERRIDE" if bq in OVERRIDDEN else "ACCEPT"
        if len(found) != 1:
            bad.append(f"{bq} appears {len(found)} times")
        elif not found[0].startswith(f"- **{bq}** RULED, {verdict}"):
            bad.append(f"{bq} is not marked 'RULED, {verdict}'")
    if any("ruling pending" in ln or "default built" in ln for ln in t.spec.split("\n")):
        bad.append("a line still reads as pending")
    return [("G-RULED", b, "spec", region) for b in bad]


def g_boards(t: Texts) -> list[Finding]:
    _, _, region = section(t.spec, "## 0.")
    rs = board_rows(t.spec)
    bad: list[str] = []
    if not 1 <= len(rs) <= 10:
        bad.append(f"{len(rs)} boards")
    if [r[0] for r in rs] != [f"{n:02d}" for n in range(1, len(rs) + 1)]:
        bad.append("the boards are not numbered 01 onward")
    for r in rs:
        if r[3] not in THEMES or r[4] != PENDING_CELL or not r[2]:
            bad.append(f"board {r[0]} is not a pending board with a theme and a draw list")
    if 3 * sum(1 for r in rs if r[3] != "dark") > len(rs):
        bad.append("twins exceed a third")
    if not any(
        ln.startswith("**Not drawn — the text is binding**") for ln in body(t.spec, "## 0.")
    ):
        bad.append("the not-drawn paragraph is missing")
    plan = [r[0] for r in first_table(t.hand, "## §H")[1:]]
    if plan != [r[0] for r in rs]:
        bad.append("the hand-off's board plan differs from §0")
    return [("G-BOARDS", b, "spec", region) for b in bad]


def g_heur(t: Texts) -> list[Finding]:
    _, _, region = section(t.spec, "## 13.")
    return [
        ("G-HEUR", f"{r[0]} is not marked (heuristic)", "spec", region)
        for r in rows(t.spec, "## 13.", 2)
        if not r[1].startswith("(heuristic)")
    ]


def g_walk(t: Texts) -> list[Finding]:
    _, _, region = section(t.hand, "## §E")
    n = sum(1 for ln in body(t.hand, "## §E") if ln.startswith("- ["))
    return [] if 1 <= n <= 10 else [("G-WALK", f"{n} walkthrough items", "hand", region)]


def g_owner(t: Texts) -> list[Finding]:
    _, _, region = section(t.spec, "### 15.2")
    out: list[Finding] = []
    for r in rows(t.spec, "### 15.2", 4):
        if AGENT_RE.search(r[3]) or not OWNER_OK_RE.search(r[3]):
            out.append(("G-OWNER", f"{r[0]}'s owner {r[3]!r}", "spec", region))
    return out


def g_lines(t: Texts, gate: str, test: Callable[[str], bool], what: str) -> list[Finding]:
    out: list[Finding] = []
    for doc in ("spec", "hand", "json"):
        text = t.doc(doc)
        regions = line_regions(text)
        for i, line in enumerate(text.split("\n")):
            if test(line):
                out.append((gate, f"{what} on line {i + 1}", doc, regions[i]))
    return out


def g_untouched(t: Texts) -> list[Finding]:
    extra = [p for p in t.changed if p not in OWN and not OWN_BOARDS.fullmatch(p)]
    return [("G-UNTOUCHED", f"{p} differs from the base", "", "") for p in extra]


def g_budget(t: Texts) -> list[Finding]:
    out: list[Finding] = []
    for doc, cap in (("spec", SPEC_BUDGET), ("hand", HAND_BUDGET)):
        if t.doc(doc).count("\n") > cap:
            out.append(("G-BUDGET", f"{doc} has more than {cap} lines", "", ""))
    return out


def g_mutlist(t: Texts) -> list[Finding]:
    _, _, region = section(t.spec, "## 14.")
    got = [(r[0], r[1], r[2]) for r in rows(t.spec, "## 14.", 3)]
    if got != [(m.mid, m.what, m.gate) for m in MUTATIONS]:
        return [("G-MUTLIST", "§14 differs from the tool's list", "spec", region)]
    return []


# ---------------------------------------------------------------------------- pins


def units(doc: str, text: str) -> list[tuple[str, str, str, str]]:
    """(doc, region, location, normalised text) for every unit; one shape unit per region."""
    out: list[tuple[str, str, str, str]] = []
    regions = line_regions(text)
    shape: dict[str, str] = {}
    prose: dict[str, int] = {}
    leads: dict[tuple[str, str], int] = {}
    order: list[str] = []
    for i, line in enumerate(text.split("\n")):
        reg = regions[i]
        if reg not in shape:
            shape[reg] = ""
            order.append(reg)
        text_line = re.sub(r"\s+", " ", cut_anchors(line)).strip()
        if not text_line:
            continue
        if re.match(r"^#{1,6} ", line):
            shape[reg] += "h"
            out.append((doc, reg, "heading", text_line))
        elif line.strip().startswith("|"):
            if is_rule_row(line):
                shape[reg] += "r"
                continue
            shape[reg] += "t"
            c = cells(cut_anchors(line))
            lead = re.sub(r"\s+", " ", c[0]) if c else ""
            leads[(reg, lead)] = leads.get((reg, lead), 0) + 1
            loc = f"row {lead}" + (f" #{leads[(reg, lead)]}" if leads[(reg, lead)] > 1 else "")
            out.append((doc, reg, loc, " | ".join(re.sub(r"\s+", " ", x) for x in c)))
        else:
            shape[reg] += "p"
            prose[reg] = prose.get(reg, 0) + 1
            out.append((doc, reg, f"l{prose[reg]}", text_line))
    for reg in order:
        out.append((doc, reg, "shape", shape[reg] or "(empty)"))
    return out


def all_units(t: Texts) -> list[tuple[str, str, str, str]]:
    return units("spec", t.spec) + units("hand", t.hand)


def read_pins() -> dict[tuple[str, str, str], str]:
    path = ROOT / PIN_REL
    if not path.exists():
        return {}
    pins: dict[tuple[str, str, str], str] = {}
    for line in path.read_text(encoding="utf-8").split("\n"):
        if not line or line.startswith("#"):
            continue
        doc, reg, loc, text = line.split("\t", 3)
        pins[(doc, reg, loc)] = text
    return pins


def g_pins(t: Texts) -> list[Finding]:
    pins = read_pins()
    if not pins:
        return [("G-RULED-PIN", "no pins file; run --repin-ruled", "", "")]
    have = {(d, r, loc): x for d, r, loc, x in all_units(t)}
    out: list[Finding] = []
    for key in sorted(set(pins) | set(have)):
        if key not in have:
            out.append(("G-RULED-PIN", f"unit removed: {key[2]}", key[0], key[1]))
        elif key not in pins:
            out.append(("G-RULED-PIN", f"unit added: {key[2]}", key[0], key[1]))
        elif pins[key] != have[key]:
            out.append(("G-RULED-PIN", f"unit changed: {key[2]}", key[0], key[1]))
    return out


def repin(t: Texts) -> int:
    if PLACEHOLDER_RE.search(t.spec + t.hand) or "{{MUTATIONS" in t.spec or "{{TRANS" in t.spec:
        print("FAIL --repin-ruled refuses while a placeholder is unfilled")
        return 1
    units_ = all_units(t)
    head = (
        "# E47-D07 pins (every unit of the spec and the hand-off): doc, region (heading path"
        f" #occurrence), location, exact normalised text; {len(units_)} units.\n"
        "# Written by `--repin-ruled` only; `--check` reads it (never hand-edit; G-RULED-PIN).\n"
    )
    text = "".join(f"{d}\t{r}\t{loc}\t{x}\n" for d, r, loc, x in units_)
    old = read_pins()
    new = {(d, r, loc): x for d, r, loc, x in units_}
    for key in sorted(set(old) | set(new)):
        if old.get(key) != new.get(key):
            print(f"REPIN {key[0]} {key[2]} in {key[1][:60]}".encode("ascii", "replace").decode())
    (ROOT / PIN_REL).write_text(head + text, encoding="utf-8")
    print(f"wrote {PIN_REL}: {len(units_)} units")
    return 0


# ---------------------------------------------------------------------------- run


def findings(t: Texts, values: Values) -> list[Finding]:
    out: list[Finding] = []
    out += g_anchor(t, values) + g_marker(t) + g_cite(t) + g_quote(t) + g_arow(t) + g_pin(t)
    out += g_classes(t) + g_copy(t) + g_sim(t) + g_labels(t) + g_find(t) + g_t2(t) + g_comp(t)
    out += g_lines(t, "G-PUBLIC", lambda ln: bool(PUBLIC_RE.search(ln)), "a host, path or name")
    out += g_ruled(t) + g_boards(t) + g_heur(t) + g_walk(t) + g_owner(t)
    out += g_untouched(t) + g_budget(t) + g_mutlist(t) + g_pins(t)
    return out


def related(a: str, b: str) -> bool:
    if not a or not b:
        return False
    a0, b0 = a.rsplit("#", 1)[0], b.rsplit("#", 1)[0]
    return a0 == b0 or a0.startswith(b0 + " > ") or b0.startswith(a0 + " > ")


def report(fs: list[Finding], quiet: bool = False) -> list[str]:
    """One FAIL line per gate; pin findings in a region another gate FAILs become NOTE."""
    other = [(d, r) for g, _, d, r in fs if g != "G-RULED-PIN"]
    lines: list[str] = []
    gates: dict[str, list[Finding]] = {}
    for f in fs:
        if f[0] == "G-RULED-PIN" and any(d == f[2] and related(r, f[3]) for d, r in other):
            if not quiet:
                lines.append(f"NOTE G-RULED-PIN {f[1]} ({f[2]}; another gate FAILs here)")
            continue
        gates.setdefault(f[0], []).append(f)
    for gate, items in gates.items():
        lines.append(
            f"FAIL {gate}: {len(items)} finding(s); first: {items[0][1]} [{items[0][3][:70]}]"
        )
    return [ln.encode("ascii", "replace").decode() for ln in lines]


def read_texts() -> Texts:
    return Texts(
        spec=(ROOT / SPEC_REL).read_text(encoding="utf-8"),
        hand=(ROOT / HAND_REL).read_text(encoding="utf-8"),
        json=(ROOT / JSON_REL).read_text(encoding="utf-8"),
        changed=changed_paths(),
    )


TRANSCRIPT_SECTIONS = {"quiet": "### 10.1", "fast": "### 10.2", "incident": "### 10.3"}


def put_table(text: str, prefix: str, table: str) -> str:
    """Replaces the first table of the section (the --fill writer of §10's annotated tables)."""
    s, e, _ = section(text, prefix)
    lines = text.split("\n")
    idx = [i for i in range(s, e) if lines[i].startswith("|")]
    if not idx:
        return text
    a = idx[0]
    b = a
    while b < e and lines[b].startswith("|"):
        b += 1
    return "\n".join([*lines[:a], table, *lines[b:]])


def fill(t: Texts) -> Texts:
    spec = t.spec.replace("{{MUTATIONS}}", mutation_rows())
    doc = load_json(t)
    if doc is not None:
        by_id = {str(sc.get("id")): sc for sc in scripts(doc)}
        spec = TRANSCRIPT_RE.sub(
            lambda m: transcript_rows(by_id[m.group(1)]) if m.group(1) in by_id else m.group(0),
            spec,
        )
        for sid, prefix in TRANSCRIPT_SECTIONS.items():
            if sid in by_id:
                spec = put_table(spec, prefix, transcript_rows(by_id[sid]))
    t = replace(t, spec=spec)
    values = compute_values(t)

    def placeholder(m: re.Match[str]) -> str:
        key = f"{m.group(1)}:{m.group(2)}"
        return f"{values[key]}<!--={key}-->" if key in values else m.group(0)

    def anchor(m: re.Match[str]) -> str:
        key = f"{m.group(2)}:{m.group(3)}"
        return f"{values.get(key, m.group(1))}<!--={key}-->"

    def sub(text: str) -> str:
        return ANCHOR_RE.sub(anchor, PLACEHOLDER_RE.sub(placeholder, text))

    t = replace(t, spec=sub(t.spec), hand=sub(t.hand))
    (ROOT / SPEC_REL).write_text(t.spec, encoding="utf-8")
    (ROOT / HAND_REL).write_text(t.hand, encoding="utf-8")
    return t


def write_transcripts() -> int:
    """Writes each script's expected lines from the replay: the oracle's only writer."""
    t = read_texts()
    doc = load_json(t)
    if doc is None:
        print("FAIL the transcripts JSON does not parse")
        return 1
    for sc in scripts(doc):
        settings = sc.get("settings")
        if isinstance(settings, dict):
            sc["expected"] = [line_dict(ln) for ln in replay(t.spec, doc, sc, settings).lines]
    (ROOT / JSON_REL).write_text(json.dumps(doc, indent=2, ensure_ascii=False) + "\n", "utf-8")
    print(f"wrote {JSON_REL}")
    return 0


def check(do_fill: bool) -> int:
    t = read_texts()
    if do_fill:
        t = fill(t)
    lines = report(findings(t, compute_values(t)))
    for ln in lines:
        print(ln)
    fails = sum(1 for ln in lines if ln.startswith("FAIL"))
    print(f"{fails} FAIL")
    return 1 if fails else 0


def self_test() -> int:
    t = read_texts()
    digest = hashlib.sha256((t.spec + t.hand + t.json).encode()).hexdigest()
    values = compute_values(t)
    base = [ln for ln in report(findings(t, values), quiet=True) if ln.startswith("FAIL")]
    if base:
        print("FAIL self-test: the baseline is not clean:", *base, sep="\n  ")
        return 1
    bad = 0
    for m in MUTATIONS:
        mt = apply_mutation(t, m)
        got = [ln for ln in report(findings(mt, values), quiet=True) if ln.startswith("FAIL")]
        ok = len(got) == 1 and got[0].startswith(f"FAIL {m.gate}:")
        print(
            f"{'ok  ' if ok else 'BAD '} {m.mid} {m.gate} <- {m.what}".encode(
                "ascii", "replace"
            ).decode()
        )
        if not ok:
            bad += 1
            for g in got:
                print(f"       {g}")
    gates = {m.gate for m in MUTATIONS}
    missing = sorted(
        {
            "G-ANCHOR",
            "G-MARKER",
            "G-CITE",
            "G-QUOTE",
            "G-AROW",
            "G-PIN",
            "G-CLASSES",
            "G-COPY",
            "G-SIM",
            "G-LABELS",
            "G-FIND",
            "G-T2",
            "G-COMP",
            "G-PUBLIC",
            "G-RULED",
            "G-BOARDS",
            "G-HEUR",
            "G-WALK",
            "G-OWNER",
            "G-UNTOUCHED",
            "G-BUDGET",
            "G-MUTLIST",
            "G-RULED-PIN",
        }
        - gates
    )
    if missing:
        print(f"FAIL self-test: no mutation for {missing}")
        bad += 1
    after = read_texts()
    if hashlib.sha256((after.spec + after.hand + after.json).encode()).hexdigest() != digest:
        print("FAIL self-test: the texts on disk changed")
        return 1
    print(f"self-test: {len(MUTATIONS) - bad} of {len(MUTATIONS)} ok")
    return 1 if bad else 0


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0] if __doc__ else None)
    mode = ap.add_mutually_exclusive_group(required=True)
    mode.add_argument("--check", action="store_true")
    mode.add_argument("--self-test", action="store_true")
    mode.add_argument("--repin-ruled", action="store_true")
    mode.add_argument("--write-transcripts", action="store_true")
    ap.add_argument("--fill", action="store_true", help="with --check: write values first")
    args = ap.parse_args()
    if args.self_test:
        return self_test()
    if args.repin_ruled:
        return repin(read_texts())
    if args.write_transcripts:
        return write_transcripts()
    return check(args.fill)


if __name__ == "__main__":
    sys.exit(main())
