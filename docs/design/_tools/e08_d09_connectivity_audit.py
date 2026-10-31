#!/usr/bin/env python3
"""E08-D09 (#177) audit: the SCR-147 connectivity and limits spec and its hand-off.

Stdlib only, offline (`python3 -I -B`). It reads AS TEXT at the pinned base (`git show BASE:<path>`)
the plan texts, the merged design texts, the backend sources the spec cites and the token JSON;
then the spec (`E08-D09.md`), the hand-off and the pins from the working tree. The gates, each FAIL
led by its code:

- [G-CITE] every `KEY`:line cite (and every `C-x.y`:line cite) resolves at the base to a non-blank
  line inside its file (a rule cite inside its rule); every cite's line is pinned by its words in
  the pins file (cites by content: a moved line FAILs, naming where its words now stand); the
  load-bearing cites (CITED) hold their words. Limit: outside CITED the gate proves a cite resolves
  and is pinned, not that it names the right line; a re-pointed cite passes after `--repin-ruled`,
  so the reviewer reads the pins diff.
- [G-QUOTE] every copy-deck row is PROPOSED or verbatim; each verbatim fragment (VERBATIM) stands
  in its string and on its cited line; the ruled and pinned strings (EXACT) equal their deck rows.
- [G-CARVE] the C-2.6 / C-12.7 carve-out: the two carve-out sentences verbatim; the two-condition
  sentences, each under its own state (a per-account throttle and an exchange IP hold); over every
  line of both documents, no sentence presents a protective action (cancel, close, `closePosition`,
  flatten, setting or tightening a stop) near a gating word (disabled, greyed, gated, refused,
  hidden, `aria-disabled`, T2, blocked) and no sentence promises one succeeds ("will go through",
  "will still succeed", "still works" and the like), unless the sentence is a negation (never,
  no, not, none); no protective control in the T2 table; the reserve never given a percentage of
  its own; the stop-loss always counted by the simulator.
- [G-NEVER] the never-show rules stand in §13.2 (the served `detail` never printed verbatim among
  them); no displayed string (a deck string, an SR string, any quoted string in either document)
  carries key material, a UID, a host, an address or a request or trace id; no sentence outside
  §13.2 names such content without a negation; S-17 shows a page-owned sentence, never the served
  `detail`.
- [G-STATE] the register S-01 ... S-20: in order, each with a trigger, an exit, a known glyph that
  matches its tone (TONE_GLYPHS), a token, an announcement and a numeric `max_rate`; only S-06 is
  assertive; every SR row writes into the shell's region pair (E17-D02 §11), only SR-5 into the
  assertive one, and no section-level live region is named; never-announced states rate `never`; every SR
  row of §17.4 carries a numeric rate.
- [G-TOKEN] every token named in the two documents is shipped in `packages/ui/tokens` at the base.
- [G-D12] E08-D12's pre-condition (G-01) answered by id: the ten §10.1b items with a verdict each,
  KB-30 / PP-11 / T2-19 / SR-45 mapped to this spec's rows that exist, BG-01 / 09 / 11 / 13 / 14,
  the naming rule, R1 and R2.
- [G-LEDGER] §1.5's inbound ledger (BQ-03): L-1 ... L-n in order, four cells, a disposition from
  the vocabulary, every "Here" section present, the stated counts equal to the tool's, every
  required source (LEDGER_SOURCES) present; the C-, G- and Q-rows in order, each with a reading or
  an owner; every G-row with an owner and no shape; every D09-Cn / D09-Gn / D09-Qn named exists.
- [G-T2] R-9 (G-T2.1b and G-T2.1d) stands verbatim in §1.4, and every section that shows a T2
  control (T2_SECTIONS) cites R-9.
- [G-UNTOUCHED] by content, three modes. PR 1 (the spec is not at the merge-base): only the four
  own paths differ. PR 2 (the spec is at the merge-base and `14` or `15` differs): `14` and `15`
  equal the merge-base with every §C row applied, re-pointed by content, plus at most a byte-exact
  pins rewrite; nothing else. Later (post-merge, e.g. the boards): the own paths, the board PNGs and
  sheets only; `14` and `15` untouched. Fails closed when git cannot answer.
- [G-AROW] §C (in the hand-off): A-1 ... A-n in order, each with a target file, line and known op,
  its Old (or anchor) equal to that line at the base and unique in its scope (or already applied).
- [G-RULED] no BQ marker left; the twenty-six stamps in their exact form; the ruled words
  (RULING_PINS) stand in the spec.
- [G-RULED-PIN] a default-deny pin set over every unit of the two documents in
  `e08_d09_ruled_pins.txt`. `--repin-ruled` is its only writer. When another gate FAILs, every
  G-RULED-PIN finding prints as a NOTE; the exit status stays 1.
- [G-PUBLIC] no word on the public-text list (matched by pattern), no local path, host, uuid, URL,
  agent name or closing keyword in the documents; the public-text list also over the tool and pins.
- [G-PIN] every sha and comment id in the documents is a known one.

`--a-rows` prints §C as JSON, one record per row with its target file; `--self-test` applies at
least one mutation per gate (MUTATIONS) and the mode probes (PROBES) to an in-memory copy and passes
only when each mutation adds new FAILs from its own gate only, each probe gives its expected result, a re-run
reproduces the base result and no file on disk changed.

Usage (from the repo root):
  python3 -I -B docs/design/_tools/e08_d09_connectivity_audit.py --check [--json]
  python3 -I -B docs/design/_tools/e08_d09_connectivity_audit.py --self-test
  python3 -I -B docs/design/_tools/e08_d09_connectivity_audit.py --repin-ruled
  python3 -I -B docs/design/_tools/e08_d09_connectivity_audit.py --a-rows
Exit 0 = no FAIL; 1 = at least one FAIL.
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
from functools import cache
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
BASE = "03ee085982"  # `git merge-base HEAD origin/main` at PR 1
BQ_BASE = "b148ca4703"  # the BQ list's base
SPEC_REL = "docs/design/E08/E08-D09.md"
HAND_REL = "docs/design/E08/E08-D09-handoff.md"
TOOL_REL = "docs/design/_tools/e08_d09_connectivity_audit.py"
PINS_REL = "docs/design/_tools/e08_d09_ruled_pins.txt"
OWN_PATHS = (SPEC_REL, HAND_REL, TOOL_REL, PINS_REL)
LATER_PREFIXES = ("docs/design/E08/img/E08-D09-", "docs/design/_tools/sheets/e08-d09/")
SCREENS_REL = "docs/plan/14-screens-catalogue.md"
CAT_REL = "docs/plan/15-component-catalogue.md"
TARGETS = {"14": SCREENS_REL, "15": CAT_REL}
RULING_ID = "6541924006"  # #177's ruling of record
BQ_ID = "6538955219"  # #177's BQ list
DELEGATION_ID = "6490317249"  # the 2026-10-29 delegation directive on #2701
D12_PRE_ID = "6538794044"  # E08-D12's pre-condition comment on #177 (G-01)
D12_SHA = "22f9cabffc"  # E08-D12's merge (#5148)
ORCH_R1_ID = "6542806383"  # the orchestrator's round-1 read on #5179
STAMP = "RULED (orchestrator, 2026-10-31, #177 ruling of record — 6538955219's answer)"
SVC = "services/api/candleviewer/"
E08 = "docs/design/E08/E08-"
KEYS: dict[str, str] = {
    "04": "docs/plan/04-security-program.md",
    "05": "docs/plan/05-accessibility-standard.md",
    "11": "docs/plan/11-user-stories.md",
    "12": "docs/plan/12-sitemap.md",
    "14": SCREENS_REL,
    "15": CAT_REL,
    "20": "docs/plan/20-architecture.md",
    "22": "docs/plan/22-api-openapi.yaml",
    "23": "docs/plan/23-ws-protocol.md",
    "24": "docs/plan/24-internal-schemas.md",
    "D01": E08 + "D01.md",
    "D02": E08 + "D02.md",
    "D04": E08 + "D04.md",
    "D07": E08 + "D07.md",
    "D08": E08 + "D08.md",
    "D11": E08 + "D11.md",
    "D12": E08 + "D12.md",
    "DS": ".claude/rules/32-design-specs.md",
    "E04-D01": "docs/design/E04/E04-D01.md",
    "E17-D02": "docs/design/E17/E17-D02.md",
    "E42J": "docs/plan/backlog/E42.json",
    "cal": "docs/plan/backlog/_tools/calendar_cv.py",
    "E30-D03": "docs/design/E30/E30-D03.md",
    "E42-D02": "docs/design/E42/E42-D02.md",
    "E42-D05": "docs/design/E42/E42-D05.md",
    "admin_ops": SVC + "api/admin_ops.py",
    "bybit-metrics": SVC + "exchange/bybit/metrics.py",
    "capacity": SVC + "admin/overview/capacity.py",
    "clock": SVC + "ingestion/clock.py",
    "config": SVC + "exchange/bybit/config.py",
    "ing-metrics": SVC + "ingestion/metrics.py",
    "planner": SVC + "ingestion/planner.py",
    "rate_limit": SVC + "exchange/bybit/rate_limit.py",
    "rest": SVC + "exchange/bybit/rest.py",
    "seed": SVC + "auth/rbac_seed.json",
}
CONSTITUTION = "CONSTITUTION.md"
TOKENS_DIR = "packages/ui/tokens"
TOKEN_FILES = (
    "primitives.tokens.json",
    "semantic-dark.tokens.json",
    "semantic-light.tokens.json",
    "semantic-hc.tokens.json",
)

# The load-bearing cites: their words must stand on the cited line at the base.
CITED: dict[tuple[str, int], str] = {
    ("24", 2237): "`10018`",
    ("24", 2234): "`10006`",
    ("24", 2230): "`10002`",
    ("24", 2316): "reserved_for_protective",
    ("24", 2305): "80 %",
    ("20", 617): "sl_cost",
    ("22", 800): "Order entry halted until the server clock is back in sync with the exchange",
    ("22", 22774): "never a fabricated 0",
    ("clock", 129): "warn_threshold_ms: int = 500",
    ("clock", 130): "hard_threshold_ms: int = 2_000",
    ("clock", 175): "server - local",
    ("planner", 15): "MAX_TOPICS_PER_FRAME = 10",
    ("15", 2229): "Native stops on the exchange are unaffected.",
    ("D04", 67): "Connection unstable",
    ("E30-D03", 268): "`critical` lane",
    ("E42-D02", 131): "Recorded in the audit log",
    ("14", 2988): "connectivity.reconnect_forced",
    ("D12", 197): "KB-30",
    ("E04-D01", 168): "rule with SCR-147",
    ("E17-D02", 249): "One live-region pair (polite + assertive)",
    ("E42J", 260): "Sprint 15",
    ("cal", 13): "datetime.date(2026, 9, 25)",
}

# (deck fragment, cite key, line, words on that line) for every verbatim fragment of the deck.
VERBATIM: dict[str, tuple[tuple[str, str, int, str], ...]] = {
    "W-01": (("illustrative values, not a market capture", "D07", 626, "not a market capture"),),
    "W-03": (("All times UTC · as of", "15", 979, "All times UTC · as of"),),
    "W-04": (
        ("as of {", "E42-D02", 130, "as of HH:MM:SS"),
        ("stale since {", "E42-D02", 130, "stale since HH:MM:SS"),
        ("Stale {", "D04", 42, '"Stale 4s"'),
    ),
    "W-14": (("Attention:", "15", 2230, '"Attention:"'),),
    "W-18": (
        ("Disconnected —", "D04", 44, '"Disconnected —'),
        ("Disconnected — last data {", "D02", 32, "Disconnected — last data 00:12 ago"),
    ),
    "W-19": (("Reconnecting…", "D04", 43, '"Reconnecting…"'),),
    "W-20": (("Connection unstable", "D04", 67, "Connection unstable"),),
    "W-22": (
        (
            "Order entry halted until the server clock is back in sync with the exchange",
            "22",
            800,
            "Order entry halted until the server clock is back in sync with the exchange",
        ),
    ),
    "W-23": (("Clock offset has not been measured yet.", "clock", 303, "not been measured yet."),),
    "W-24": (("Degraded", "E42-D02", 130, "`Degraded`"),),
    "W-25": (("Error", "E42-D02", 130, "`Error`"),),
    "W-26": (("Unavailable", "E42-D02", 130, "`Unavailable`"),),
    "W-31": (("Native stops on the exchange are unaffected.", "15", 2229, "are unaffected."),),
    "W-46": (
        ("of 10 topics", "planner", 15, "MAX_TOPICS_PER_FRAME = 10"),
        ("of 21 000 characters", "planner", 16, "MAX_ARGS_CHARS = 21_000"),
        ("of 500 topics", "planner", 32, "max_topics_per_socket: int = 500"),
    ),
    "W-51": (("Native stops on the exchange are unaffected.", "15", 2229, "are unaffected."),),
    "W-55": (
        ("Recorded in the audit log ·", "E42-D02", 131, "Recorded in the audit log · <label>"),
    ),
    "W-63": (
        ("Recorded in the audit log ·", "E42-D02", 131, "Recorded in the audit log · <label>"),
    ),
    "W-71": (("View as table", "15", 2230, '"View as table"'),),
    "W-74": (("Read-only while viewing as {user}.", "D12", 384, "viewing as {user}."),),
}

# The ruled and pinned strings: each deck row's string, exactly.
EXACT: dict[str, str] = {
    "W-06a": "Reserved for stops and cancels · Not connected yet",
    "W-25": (
        "Error · Our rate-limit counters did not report. · last good {14:01:58} · Usage is unknown "
        "until our counters report again."
    ),
    "W-36": "All requests are on hold.",
    "W-55": "Recorded in the audit log · Reconnect forced (pending registration)",
    "W-57": "Wait {40} s. The connection budget allows no new connection yet.",
    "W-63": "Recorded in the audit log · Request budget changed (pending registration)",
    "W-64": (
        "The exchange's limit for this account is the ceiling. · Raising this never raises the "
        "exchange's limit. · The reserve for stops and cancels is kept out of this budget. · This "
        "changes this account only."
    ),
}

# The carve-out sentences (spec §7), verbatim.
CARVE = (
    (
        "> **C-12.7.** A share of each account's request budget is reserved for stop placement, "
        "cancel and flatten. It is never spent on chart or backfill traffic, and no figure on this "
        "page counts it as spendable. Its size is set by C-12.7 and read from the server."
    ),
    (
        "> **C-2.6.** Every position-opening order carries a native stop-loss on the exchange. The "
        "simulator always includes the stop: per account the cost is `1 + sl_cost`, where `sl_cost` "
        "is 0 when the stop rides on the entry order and 1 when a separate stop request is needed "
        "(`20`:617). Nothing on this page can switch the stop off."
    ),
)
# The two conditions (RULED BQ-10): (deck row, its words, words it must never carry).
THROTTLE_LINE = (
    "Cancel, close, flatten and stop placement use the reserved budget once it is connected."
)
HOLD_LINE = (
    "While the hold lasts, no request from this server reaches the exchange, protective ones "
    "included. Native stops on the exchange stay active. The kill switch is a synchronous local "
    "check, not a request to the exchange."
)
CONDITIONS = (("W-31", THROTTLE_LINE, "reaches the exchange"), ("W-33", HOLD_LINE, "reserved"))
CONDITION_BULLET = (
    "Under a **per-account throttle** (S-03), cancel, close, flatten and stop placement ride the "
    "governor's `critical` lane when it exists (`E30-D03`:268; W-31). Under an **exchange IP hold** "
    "(S-04, and S-05 as held), no REST path reaches the venue, protective ones included; the native "
    "stops on the exchange stay active, and the kill switch is a synchronous local check, never a "
    "REST call (`24`:2237; C-2.21; W-33)."
)
PROTECTIVE = re.compile(
    r"\b(?:cancel|close|closePosition|flatten|stop[- ]loss|stops?)\b", re.IGNORECASE
)
PROT_WORD = re.compile(
    r"\b(?:cancel(?:s|led|ling)?|closePosition|close(?: (?:a|the|all) positions?)?|flatten\w*"
    r"|stop[- ]loss(?:es)?|stops?|tighten\w*)\b",
    re.IGNORECASE,
)
GATING = re.compile(
    r"\b(?:disabled?|disabling|greye?d?(?: out)?|greys out|gated?|gating|refused?|refuses|hidden"
    r"|hides?|aria-disabled|T2|blocked|blocks)\b",
    re.IGNORECASE,
)
PROMISE = re.compile(
    r"\b(?:will|would|shall) (?:still |always )?(?:succeed|work|go through|get through"
    r"|be (?:accepted|placed|sent|filled|honou?red))\b|\bstill (?:works?|succeeds?|goes through"
    r"|go through|gets? through|accepted|placed)\b|\bgo(?:es)? through\b|\bguaranteed\b",
    re.IGNORECASE,
)
NEGATION = re.compile(r"\b(?:never|no|not|none|nothing)\b", re.IGNORECASE)
SENTENCE = re.compile(r"(?<=[.!?;])\s+|\s+·\s+|\s*\|\s*")
NEVER_SHOW = (
    "No API key, secret, signature, signed request content, or key id beyond a masked label.",
    "never a UID",
    "No raw exchange body.",
    "is never printed verbatim",
    "No hostname, egress address, request id or trace id as text",
    "**The served `detail` is never printed verbatim**",
)
SENSITIVE = re.compile(
    r"\brequest id\b|\btrace id\b|\bapi[ _-]?key\b|\bsecret\b|\bsignature\b|\bhostname\b"
    r"|\begress address\b|\bUID\b|served `?detail`?",
    re.IGNORECASE,
)
SHOWING = re.compile(
    r"\b(?:show|shows|shown|display|displays|print|prints|printed|render|renders"
    r"|rendered|label|labelled|may|appear|appears|as text)\b",
    re.IGNORECASE,
)
QUOTED = re.compile(r'"([^"\n]{2,})"')
DECK_FORBIDDEN = re.compile(
    r"\buid\b|api[ _-]?key|secret|trace id|request id|\b\d{1,3}(?:\.\d{1,3}){3}\b"
    r"|\b[a-z0-9-]+\.(?:com|net|org|io)\b",
    re.IGNORECASE,
)
GLYPHS = ("check", "triangle", "octagon", "clock", "ring", "—")
# Each tone's glyphs (CMP-178's shapes, `15`:2230): a tone never wears another tone's glyph.
TONE_GLYPHS: dict[str, tuple[str, ...]] = {
    "color.status.success.strong": ("check",),
    "color.status.warning.strong": ("triangle",),
    "color.status.danger.strong": ("octagon", "clock"),
    "color.neutral.default": ("ring",),
    "color.data-confidence.disconnected.*": ("octagon",),
    "color.data-confidence.reconnecting.*": ("ring",),
    "color.data-confidence.stale.*": ("clock",),
    "CMP-015": ("—",),
}
ANNOUNCE = ("never", "polite, on entry", "assertive, on entry")
ASSERTIVE_STATES = ("S-06",)  # E08-D04's one assertive state, entering Disconnected
ASSERTIVE_SR = ("SCR-147-SR-5",)
SHELL_HOSTS = ("the shell's polite region", "the shell's assertive region")
SECTION_REGION = re.compile(
    r"region per section|page-level `role=\"alert\"`|per section, pre-rendered|"
    r"the section's status|the clock section's status|the simulator's status",
    re.IGNORECASE,
)
R9 = (
    "- **R-9 T2, stated once** (G-T2.1b, G-T2.1d; `DS`:29–:39). A T2 control takes "
    '`aria-disabled="true"`, never the `disabled` attribute: it stays in the Tab order, and a menu '
    "item stays arrow-reachable. CMP-079 RbacGate wraps it, and the CMP-019 `lock`, "
    '`decorative={false}`, accessible name "Not available", leads the full label. Every section '
    "that shows a T2 control cites R-9."
)
T2_SECTIONS = (
    ("6. Throttled", 2),
    ("10. Clock skew", 2),
    ("11. Force reconnect", 2),
    ("12. The budget change", 2),
    ("13.1", 3),
    ("17.5", 3),
)
DISPOSITIONS = ("applied as amended", "applied", "routed", "closed")
LEDGER_SOURCES = (
    "`E04-D01`:165–:168",
    "`D01`:16",
    "`D02`:125–:127",
    "`E30-D03`:275",
    "`E42-D05`:390",
)
RATE = re.compile(
    r"^(?:never|once per episode(?: \(§5\.2\))?|once per press|once per change"
    r"|≤ 1 per \d+ s per region(?: \(.+\))?)$"
)
STATES = 20
D12_ITEMS = (
    "Semantic structure (grid vs table vs list)",
    "Accessible names and descriptions",
    "Focus order and visible focus",
    "Keyboard equivalents for every pointer path",
    "Live-region strategy and announcement-rate control",
    "Contrast in the themes at all states",
    "Non-colour redundancy",
    "Reduced motion",
    "Target sizes",
    'SCR-151\'s no-bare-"No data" rule',
)
R3_VERDICTS = ("compliant", "at risk", "non-compliant", "out of scope", "not yet decidable")
D12_ROWS = ("KB-30", "PP-11", "T2-19", "SR-45")
D12_BG = ("BG-01", "BG-09", "BG-11", "BG-13", "BG-14")
SHAPE = re.compile(r"[{}]|\btype:|: \{|field `", re.IGNORECASE)
RULING_PINS = (
    "The contract's `RateBudget.endpoint_class` is the vocabulary of record",
    "ride the governor's `critical` lane when it exists",
    "no REST path reaches the venue, protective ones included",
    "The page never says a protective action will succeed during a hold",
    "E30-D03's `ratelimit.permitted` sentence is not reused on this page",
    "ladder rung 2, reversible with a cascade",
    "Recorded in the audit log · Reconnect forced (pending registration)",
    'the trigger is T2 with W-36 "All requests are on hold."',
    "The control is **drawn whole and contract-first** (D09-G8)",
    "**Manager and Viewer:** no navigation entry and no disabled item",
    "the orchestrator files an E42 Story",
    "**Stop-loss: always counted**",
)


# ---------------------------------------------------------------------------- git and text


def git(*args: str) -> str | None:
    try:
        out = subprocess.run(
            ["git", "-C", str(ROOT), *args], capture_output=True, check=False, timeout=60
        )
    except (OSError, subprocess.TimeoutExpired):
        return None
    if out.returncode != 0:
        return None
    return out.stdout.decode("utf-8")


@cache
def at_rev(rev: str, rel: str) -> str | None:
    return git("show", f"{rev}:{rel}")


def at_base(rel: str) -> str | None:
    return at_rev(BASE, rel)


@cache
def key_text(key: str) -> str:
    return at_base(CONSTITUTION if key == "C" else KEYS[key]) or ""


def read(rel: str) -> str:
    p = ROOT / rel
    return p.read_text(encoding="utf-8") if p.exists() else ""


def lines(text: str) -> list[str]:
    return text.split("\n")


HEADING = re.compile(r"^(#{1,6}) (.*)$")
RULE_ROW = re.compile(r"^\|(?:\s*:?-+:?\s*\|)+\s*$")
FENCE = re.compile(r"^```")


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


def section(text: str, title: str, level: int = 2) -> str:
    """The body of the section of `level` whose heading starts with `title` (to the next heading
    of that level or higher)."""
    out: list[str] = []
    on, fenced = False, False
    for ln in lines(text):
        if FENCE.match(ln):
            fenced = not fenced
        m = HEADING.match(ln) if not fenced else None
        if m and len(m.group(1)) <= level:
            on = len(m.group(1)) == level and m.group(2).startswith(title)
            continue
        if on:
            out.append(ln)
    return "\n".join(out)


def table_rows(block: str) -> list[list[str]]:
    rows = []
    for ln in lines(block):
        if ln.startswith("|") and not RULE_ROW.match(ln):
            rows.append(split_row(ln))
    return rows[1:] if rows else []


def norm(text: str) -> str:
    return " ".join(text.split())


@cache
def token_names() -> frozenset[str]:
    names: set[str] = set()

    def walk(obj: object, path: str) -> None:
        if isinstance(obj, dict):
            if "$value" in obj:
                names.add(path)
                return
            for k, v in obj.items():
                if not str(k).startswith("$"):
                    walk(v, f"{path}.{k}" if path else str(k))

    for f in TOKEN_FILES:
        raw = at_base(f"{TOKENS_DIR}/{f}")
        if raw:
            walk(json.loads(raw), "")
    return frozenset(names)


# ---------------------------------------------------------------------------- the texts


@dataclass(frozen=True)
class Texts:
    spec: str
    hand: str
    pins: str
    tool: str
    changed: tuple[str, ...] | None  # paths that differ from the merge-base (None: git failed)
    now: tuple[tuple[str, str], ...]  # `14`, `15` in the working tree
    mbase: tuple[tuple[str, str], ...]  # `14`, `15` at the merge-base
    mbase_spec: str  # the spec at the merge-base ("" before PR 1 merges)


def docs(t: Texts) -> list[tuple[str, str]]:
    return [("spec", t.spec), ("hand-off", t.hand)]


def deck(spec: str) -> dict[str, list[str]]:
    rows = table_rows(section(spec, "15. Copy deck"))
    return {r[0]: r for r in rows if r and r[0].startswith("W-")}


# ---------------------------------------------------------------------------- G-CITE

CITE = re.compile(r"`([A-Za-z0-9_-]+)`:(\d+)(?:–:(\d+))?((?:, :\d+(?:–:\d+)?)*)")
CONT = re.compile(r":(\d+)(?:–:(\d+))?")
RULE_CITE = re.compile(r"\bC-(\d+\.\d+):(\d+)(?:–:(\d+))?")


def cites_in(text: str) -> list[tuple[str, int, int]]:
    out: list[tuple[str, int, int]] = []
    for m in CITE.finditer(text):
        key = m.group(1)
        if key not in KEYS:
            continue
        a, b = int(m.group(2)), int(m.group(3) or m.group(2))
        out.append((key, a, b))
        for c in CONT.finditer(m.group(4) or ""):
            out.append((key, int(c.group(1)), int(c.group(2) or c.group(1))))
    return out


def cite_lines(t: Texts) -> list[tuple[str, int]]:
    seen: set[tuple[str, int]] = set()
    for _, text in docs(t):
        prose = "\n".join("" if ROW_META.match(ln) else ln for ln in lines(unfence(text)))
        for key, a, b in cites_in(prose):
            seen.update({(key, a), (key, b)})
    return sorted(seen)


def line_digest(line: str) -> str:
    """A cited line's words, as a digest (the pins never copy a source's text)."""
    return "sha256:" + hashlib.sha256(norm(line).encode("utf-8")).hexdigest()[:16]


def cite_units(t: Texts) -> list[Unit]:
    out: list[Unit] = []
    for key, n in cite_lines(t):
        bl = lines(key_text(key))
        words = line_digest(bl[n - 1]) if 1 <= n <= len(bl) else "(past the end)"
        out.append((f"cite:{key}", f":{n}", words))
    return out


def cite_problems(t: Texts) -> list[str]:
    bad: list[str] = []
    for name, text in docs(t):
        prose = "\n".join("" if ROW_META.match(ln) else ln for ln in lines(unfence(text)))
        for key, a, b in cites_in(prose):
            bl = lines(key_text(key))
            if len(bl) < 2:
                bad.append(f"{name}: `{key}` is unreadable at {BASE}")
                continue
            for n in sorted({a, b}):
                if not 1 <= n <= len(bl) or not bl[n - 1].strip() or b < a:
                    bad.append(f"{name}: `{key}`:{n} is past the end or blank")
        cl = lines(key_text("C"))
        for m in RULE_CITE.finditer(prose):
            rule, a = m.group(1), int(m.group(2))
            b = int(m.group(3) or a)
            start = next((k + 1 for k, ln in enumerate(cl) if ln.startswith(f"**C-{rule} ")), 0)
            nxt = next(
                (k + 1 for k, ln in enumerate(cl) if k + 1 > start and ln.startswith("**C-")),
                len(cl) + 1,
            )
            if not start or not start <= a <= b < nxt:
                bad.append(f"{name}: C-{rule}:{a} is not inside rule C-{rule}")
    pinned = {(r, loc): txt for r, loc, txt in parse_pins(t.pins) if r.startswith("cite:")}
    for region, loc, words in cite_units(t):
        was = pinned.get((region, loc))
        key, n = region[5:], int(loc[1:])
        if was is None:
            bad.append(f"`{key}`:{n} is not pinned by its words (--repin-ruled after checking it)")
        elif was != words:
            bl = [line_digest(x) for x in lines(key_text(key))]
            now = [k + 1 for k, x in enumerate(bl) if x == was]
            where = f"now at :{now[0]}" if len(now) == 1 else "found nowhere once"
            bad.append(f"`{key}`:{n} no longer holds its pinned words ({where})")
    cited = set(cite_lines(t))
    for (key, n), words in CITED.items():
        bl = lines(key_text(key))
        if (key, n) not in cited:
            bad.append(f"the load-bearing cite `{key}`:{n} is not in the documents")
        elif not 1 <= n <= len(bl) or words not in bl[n - 1]:
            now = [k + 1 for k, ln in enumerate(bl) if words in ln]
            where = f"now at :{now[0]}" if len(now) == 1 else "found nowhere once"
            bad.append(f"`{key}`:{n} no longer holds {words!r} ({where})")
    return bad


# ---------------------------------------------------------------------------- G-QUOTE


def quote_problems(t: Texts) -> list[str]:
    bad: list[str] = []
    rows = deck(t.spec)
    if not rows:
        return ["§15's copy deck is missing"]
    for wid, row in rows.items():
        if len(row) != 4:
            bad.append(f"{wid}: not four cells")
            continue
        source = row[3]
        if "PROPOSED" not in source and wid not in VERBATIM:
            bad.append(f"{wid}: neither PROPOSED nor a verbatim string with its cite")
        if "verbatim" in (row[1] + source).lower() and wid not in VERBATIM:
            bad.append(f"{wid}: says verbatim but has no verbatim fragment pinned")
    for wid, want in EXACT.items():
        erow = rows.get(wid)
        if erow is None or len(erow) < 3 or erow[2] != want:
            bad.append(f"{wid}: its string is not the ruled one exactly")
    for wid, frags in VERBATIM.items():
        vrow = rows.get(wid)
        if vrow is None:
            bad.append(f"{wid}: a pinned verbatim row is missing from the deck")
            continue
        for frag, key, n, words in frags:
            bl = lines(key_text(key))
            if frag not in vrow[2]:
                bad.append(f"{wid}: {frag!r} is not in its string")
            if not 1 <= n <= len(bl) or words not in bl[n - 1]:
                bad.append(f"{wid}: `{key}`:{n} does not hold {words!r}")
            if f"`{key}`:{n}" not in vrow[3] and not re.search(
                rf"`{re.escape(key)}`:[\d–:, ]*\b{n}\b", vrow[3]
            ):
                bad.append(f"{wid}: its source does not cite `{key}`:{n}")
    return bad


# ---------------------------------------------------------------------------- G-CARVE and G-NEVER


def carve_problems(t: Texts) -> list[str]:
    bad: list[str] = []
    s7 = section(t.spec, "7. The reserve")
    for c in CARVE:
        if c not in s7:
            bad.append(f"§7 lacks the carve-out sentence {c[6:26]!r}… verbatim")
    if "**Protective paths are never gated here.**" not in s7:
        bad.append("§7 lacks the 'Protective paths are never gated here' rule")
    s6 = section(t.spec, "6. Throttled")
    if CONDITION_BULLET not in s6:
        bad.append("§6 lacks the two-condition bullet (RULED BQ-10) verbatim")
    rows = deck(t.spec)
    for wid, words, never in CONDITIONS:
        row = rows.get(wid)
        if row is None or words not in row[2]:
            bad.append(f"{wid}: its condition sentence is not its string")
        elif never in row[2]:
            bad.append(f"{wid}: carries the other condition's words ({never!r})")
    for name, text in docs(t):
        for n, ln in enumerate(lines(text), 1):
            for sent in SENTENCE.split(ln):
                if NEGATION.search(sent):
                    continue
                m = PROT_WORD.search(sent)
                if m and GATING.search(sent):
                    bad.append(f"{name}:{n}: a protective action presented as gated: {sent[:60]!r}")
                p = PROMISE.search(sent)
                if p:
                    bad.append(f"{name}:{n}: a promise that an action succeeds ({p.group(0)!r})")
    t2 = table_rows(section(section(t.spec, "17. Accessibility"), "17.5", 3))
    for r in t2:
        if r and len(r) > 1 and PROTECTIVE.search(r[1]):
            bad.append(f"{r[0]}: a protective control is gated ({r[1]!r})")
    for name, text in docs(t):
        for ln in lines(text):
            if re.search(r"\breserve", ln, re.IGNORECASE) and re.search(r"\{?\d+\}?\s?%", ln):
                bad.append(f"{name}: the reserve is given a percentage: {norm(ln)[:60]!r}")
    if "**Stop-loss: always counted**" not in section(t.spec, "8. The fan-out"):
        bad.append("§8: the simulator does not count the stop-loss always")
    return bad


def shown_strings(t: Texts) -> list[tuple[str, str]]:
    """Every string the page may display: the deck's, the SR rows', any quoted string."""
    out = [(wid, r[2]) for wid, r in deck(t.spec).items() if len(r) > 2]
    sr = table_rows(section(section(t.spec, "17. Accessibility"), "17.4", 3))
    out += [(r[0], r[2]) for r in sr if len(r) > 2]
    for name, text in docs(t):
        out += [
            (f"{name} quote", m.group(1))
            for m in QUOTED.finditer(text)
            if not NEGATION.search(m.group(1))  # a quoted rule ("never a UID") is not shown text
        ]
    return out


def never_problems(t: Texts) -> list[str]:
    s132 = section(section(t.spec, "13. Roles"), "13.2", 3)
    bad = [f"§13.2 lacks {p!r}" for p in NEVER_SHOW if p not in s132]
    for where, text in shown_strings(t):
        for m in DECK_FORBIDDEN.finditer(text):
            bad.append(f"{where}: a displayed string carries barred content ({m.group(0)!r})")
    for name, text in docs(t):
        body = text.replace(s132, "") if name == "spec" else text
        for n, ln in enumerate(lines(body), 1):
            for sent in SENTENCE.split(ln):
                if SENSITIVE.search(sent) and SHOWING.search(sent) and not NEGATION.search(sent):
                    bad.append(f"{name}:{n}: barred content named as shown: {sent[:60]!r}")
    s17 = next((r for r in register(t.spec) if r and r[0] == "S-17"), [])
    if len(s17) < 4 or "never the served `detail`" not in s17[3]:
        bad.append("S-17: its word cell does not say it never shows the served `detail`")
    return bad


# ---------------------------------------------------------------------------- G-STATE and G-TOKEN

TOKEN_REF = re.compile(r"`((?:color|space|type|size|radius|motion|border|opacity)\.[^`\s]+)`")


def expand(name: str) -> list[str]:
    m = re.search(r"\{([^{}]+)\}", name)
    if not m:
        return [name]
    out: list[str] = []
    for part in m.group(1).split(","):
        out += expand(name[: m.start()] + part.strip() + name[m.end() :])
    return out


def token_ok(name: str) -> bool:
    names = token_names()
    if name.endswith(".*"):
        return any(n.startswith(name[:-1]) for n in names)
    return name in names


def token_problems(t: Texts) -> list[str]:
    bad: list[str] = []
    if not token_names():
        return [f"the token JSON is unreadable at {BASE}"]
    for name, text in docs(t):
        for m in TOKEN_REF.finditer(text):
            for tok in expand(m.group(1)):
                if not token_ok(tok):
                    bad.append(f"{name}: `{tok}` is not a shipped token")
    return bad


def register(spec: str) -> list[list[str]]:
    return table_rows(section(section(spec, "5. Failure origins"), "5.2", 3))


def state_problems(t: Texts) -> list[str]:
    bad: list[str] = []
    rows = register(t.spec)
    if len(rows) != STATES:
        bad.append(f"the register has {len(rows)} states, not {STATES}")
    for n, r in enumerate(rows, 1):
        sid = f"S-{n:02d}"
        if len(r) != 11 or r[0] != sid:
            bad.append(f"{r[0] if r else '?'}: not {sid} with eleven cells")
            continue
        _, _, _, word, glyph, tone, trig, exit_, ann, rate, board = r
        if not word or word == "—":
            bad.append(f"{sid}: no word")
        if glyph not in GLYPHS or (glyph == "—" and ann != "never"):
            bad.append(f"{sid}: glyph {glyph!r} is not a known one")
        if not TOKEN_REF.search(tone) and "CMP-" not in tone:
            bad.append(f"{sid}: no token")
        tone_key = tone.strip("`")
        if glyph not in TONE_GLYPHS.get(tone_key, ()):
            bad.append(f"{sid}: glyph {glyph!r} does not match its tone {tone_key!r}")
        for what, cell in (("trigger", trig), ("exit", exit_)):
            if len(cell) < 6 or cell == "—":
                bad.append(f"{sid}: no {what}")
        if ann not in ANNOUNCE:
            bad.append(f"{sid}: announcement {ann!r} is not a known one")
        if (ann.startswith("assertive")) != (sid in ASSERTIVE_STATES):
            bad.append(f"{sid}: only S-06 is assertive (E08-D04; the shell's pair)")
        if not RATE.match(rate) or (ann == "never") != (rate == "never"):
            bad.append(
                f"{sid}: max_rate {rate!r} is not numeric or disagrees with the announcement"
            )
        if not re.fullmatch(r"\d\d(?:, \d\d)*", board):
            bad.append(f"{sid}: no board")
    sr = table_rows(section(section(t.spec, "17. Accessibility"), "17.4", 3))
    if not sr:
        bad.append("§17.4 has no SR rows")
    for r in sr:
        if len(r) != 7 or not RATE.match(r[6]):
            bad.append(f"{r[0] if r else '?'}: no numeric max_rate")
            continue
        if r[3] != "never" and r[4] not in SHELL_HOSTS:
            bad.append(f"{r[0]}: not hosted on the shell's region pair ({r[4]!r})")
        if (r[3] == "assertive") != (r[0] in ASSERTIVE_SR) or (r[3] == "assertive") != (
            r[4] == SHELL_HOSTS[1]
        ):
            bad.append(f"{r[0]}: only SR-5 is assertive, in the shell's assertive region")
    for name, text in docs(t):
        for m in SECTION_REGION.finditer(text):
            bad.append(f"{name}: a section-level live region is named ({m.group(0)!r})")
    return bad


# ---------------------------------------------------------------------------- G-D12 and G-LEDGER

ROW_ID = re.compile(r"\bSCR-147-(?:KB|PP|SR|T2)-\d+\b")


def d12_problems(t: Texts) -> list[str]:
    bad: list[str] = []
    s18 = section(t.spec, "18. E08-D12")
    items = table_rows(s18)
    if [r[0] for r in items] != list(D12_ITEMS):
        bad.append("§18 condition 1 does not list E08-D12's ten §10.1b items in order")
    for r in items:
        if len(r) < 3 or not r[1].startswith(R3_VERDICTS) or not r[2]:
            bad.append(f"§18: {r[0][:30]!r} has no R-3 verdict or no pointer")
    s17 = section(t.spec, "17. Accessibility")
    defined = {r[0] for r in table_rows(s17) if r and ROW_ID.fullmatch(r[0])}
    for rid in D12_ROWS + D12_BG:
        if f"**{rid}**" not in s18 and rid not in s18:
            bad.append(f"§18 does not answer {rid}")
    for rid in ROW_ID.findall(s18):
        if rid not in defined and not rid.startswith("SCR-147-PP"):
            bad.append(f"§18 names {rid}, which §17 does not define")
    pp = {r[0] for r in table_rows(section(s17, "17.3", 3)) if r and r[0].startswith("SCR-147-PP")}
    for rid in re.findall(r"\bSCR-147-PP-\d+\b", s18):
        if rid not in pp:
            bad.append(f"§18 names {rid}, which §17.3 does not define")
    for cond in ("**Condition 4", "**Condition 5"):
        if cond not in s18:
            bad.append(f"§18 lacks {cond[2:]}")
    s176 = section(s17, "17.6", 3)
    for rr in ("**R1 text resize**", "**R2 forced colours**"):
        if rr not in s176:
            bad.append(f"§17.6 does not answer {rr.strip('*')}")
    return bad


def rows_of(spec: str, title: str, prefix: str) -> list[list[str]]:
    return [r for r in table_rows(section(section(spec, "21. Rows"), title, 3)) if r]


def ledger(spec: str) -> list[list[str]]:
    s15 = section(section(spec, "1. Purpose"), "1.5", 3)
    return [r for r in table_rows(s15) if r and re.fullmatch(r"L-\d+", r[0])]


def disposition(cell: str) -> str:
    return next((d for d in DISPOSITIONS if cell.startswith(d)), "")


def ledger_counts(spec: str) -> dict[str, int]:
    rows = ledger(spec)
    out = {"ledger": len(rows)}
    for d in DISPOSITIONS:
        out[d] = sum(disposition(r[2]) == d for r in rows)
    return out


def inbound_problems(t: Texts) -> list[str]:
    bad: list[str] = []
    rows = ledger(t.spec)
    if not rows:
        return ["§1.5: the inbound ledger is missing"]
    heads = {m.group(1) for m in re.finditer(r"(?m)^#{2,3} (\d+(?:\.\d+)?)\.? ", t.spec)}
    for n, r in enumerate(rows, 1):
        if r[0] != f"L-{n}" or len(r) != 4:
            bad.append(f"{r[0]}: out of order or not four cells")
            continue
        if not disposition(r[2]):
            bad.append(f"{r[0]}: the disposition {r[2][:30]!r} is not in the vocabulary")
        refs = re.findall(r"§(\d+(?:\.\d+)?)", r[3])
        if not refs or any(x not in heads for x in refs):
            bad.append(f"{r[0]}: a 'Here' section is missing ({r[3]!r})")
    c = ledger_counts(t.spec)
    want = (
        f"{c['ledger']} rows: {c['applied']} applied, {c['applied as amended']} applied as "
        f"amended, {c['routed']} routed and {c['closed']} closed"
    )
    if want not in section(section(t.spec, "1. Purpose"), "1.5", 3):
        bad.append(f"§1.5's counts are not the tool's ({want!r})")
    body = "\n".join(" | ".join(r) for r in rows)
    for src in LEDGER_SOURCES:
        if src not in body:
            bad.append(f"§1.5 lacks the source {src}")
    return bad


def t2_problems(t: Texts) -> list[str]:
    bad: list[str] = []
    if R9 not in section(section(t.spec, "1. Purpose"), "1.4", 3):
        bad.append("§1.4 lacks R-9 (G-T2.1b, G-T2.1d) verbatim")
    for title, level in T2_SECTIONS:
        body = section(t.spec, title, 2) if level == 2 else ""
        if level == 3:
            for top in ("13. Roles", "17. Accessibility"):
                body += section(section(t.spec, top), title, 3)
        if not re.search(r"\bT2\b", body):
            bad.append(f"§{title}: shows no T2 control (update T2_SECTIONS)")
        elif "R-9" not in body:
            bad.append(f"§{title}: shows a T2 control without citing R-9")
    return bad


def ledger_problems(t: Texts) -> list[str]:
    bad: list[str] = inbound_problems(t)
    cs = rows_of(t.spec, "21.1", "C")
    gs = rows_of(t.spec, "21.2", "G")
    for kind, rows, width in (("C", cs, 4), ("G", gs, 3)):
        if not rows:
            bad.append(f"§21: no {kind}-rows")
        for n, r in enumerate(rows, 1):
            rid = f"D09-{kind}{n}"
            if r[0] != rid or len(r) != width or not all(c.strip() for c in r):
                bad.append(f"{r[0]}: not {rid} with {width} filled cells")
            shape = SHAPE.search(r[1]) if kind == "G" and len(r) == width else None
            if shape:
                bad.append(f"{rid}: the gap proposes a shape ({shape.group(0)!r})")
    qs = re.findall(r"^- \*\*(D09-Q\d+)\*\* (.*)$", section(t.spec, "21. Rows"), re.MULTILINE)
    for n, (qid, body) in enumerate(qs, 1):
        if qid != f"D09-Q{n}" or not re.search(r"\bowner\b|orchestrator", body):
            bad.append(f"{qid}: out of order or without an owner")
    have = {r[0] for r in cs + gs} | {q for q, _ in qs}
    for name, text in docs(t):
        for rid in sorted(set(re.findall(r"\bD09-[CGQ]\d+\b", text))):
            if rid not in have:
                bad.append(f"{name}: {rid} is named but not defined in §21")
    return bad


# ---------------------------------------------------------------------------- §C rows


@dataclass(frozen=True)
class ARow:
    aid: str
    entry: str
    fld: str
    file: str  # "14" or "15"
    line: int
    op: str
    src: str
    old: str  # the line (replace) or the anchor line (insert after)
    new: str


OPS = ("replace", "insert after")
ROW_HEAD = re.compile(r"^#### (A-\d+) · (.+?) · (.+)$")
ROW_META = re.compile(r"^`(14|15)`:(\d+) · ([a-z ]+?) · from (.+)$")


def a_rows(hand: str) -> tuple[list[ARow], list[str]]:
    """§C's rows and the parse problems."""
    body = section(hand, "§C")
    rows: list[ARow] = []
    bad: list[str] = []
    ls = lines(body)
    i = 0
    while i < len(ls):
        m = ROW_HEAD.match(ls[i])
        if not m:
            i += 1
            continue
        aid, entry, fld = m.groups()
        meta = ROW_META.match(ls[i + 2]) if i + 2 < len(ls) else None
        blocks: list[tuple[str, list[str]]] = []
        j = i + 3
        while j < len(ls) and not ROW_HEAD.match(ls[j]) and len(blocks) < 2:
            if ls[j].startswith("```") and len(ls[j]) > 3:
                kind, k = ls[j][3:], j + 1
                buf: list[str] = []
                while k < len(ls) and ls[k] != "```":
                    buf.append(ls[k])
                    k += 1
                blocks.append((kind, buf))
                j = k
            j += 1
        if not meta or len(blocks) != 2:
            bad.append(f"{aid}: no meta line or not two fenced blocks")
            i = j
            continue
        file, line, op, src = meta.groups()
        (k1, old), (k2, new) = blocks
        want = "anchor" if op == "insert after" else "old"
        if k1 != want or k2 != "new" or len(old) != 1:
            bad.append(f"{aid}: the blocks are not ```{want} (one line) then ```new")
        rows.append(
            ARow(aid, entry, fld, file, int(line), op, src, old[0] if old else "", "\n".join(new))
        )
        i = j
    return rows, bad


def scope_heading(base_lines: list[str], idx: int) -> str:
    for k in range(min(idx, len(base_lines) - 1), -1, -1):
        if HEADING.match(base_lines[k]):
            return base_lines[k]
    return ""


def locate(cur: list[str], base_lines: list[str], row: ARow) -> int | None:
    """Re-point a row by content: its scope heading (the heading above it in the text its line
    names), then the one line equal to its Old (or anchor) inside that scope."""
    head = scope_heading(base_lines, row.line - 1)
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
        if cur[k] == row.old:
            hits.append(k)
    return hits[0] if len(hits) == 1 else None


def apply_rows(text: str, named: str, rows: list[ARow], file: str) -> str | None:
    """`text` with every row for `file` applied, each re-pointed by content against `named` (the
    text its line numbers name); None when a row cannot be re-pointed."""
    cur, base_lines = lines(text), lines(named)
    edits: list[tuple[int, int, ARow]] = []
    for r in rows:
        if r.file != file:
            continue
        k = locate(cur, base_lines, r)
        if k is None:
            return None
        edits.append((k, 0 if r.op == "insert after" else 1, r))
    for k, _, r in sorted(edits, key=lambda e: (e[0], e[1]), reverse=True):
        if r.op == "replace":
            cur[k : k + 1] = lines(r.new)
        else:
            cur[k + 1 : k + 1] = lines(r.new)
    return "\n".join(cur)


def export(rows: list[ARow]) -> list[dict[str, object]]:
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


def arow_problems(t: Texts) -> list[str]:
    rows, parse_bad = a_rows(t.hand)
    bad = list(parse_bad)
    if not rows:
        bad.append("§C has no rows")
    for n, r in enumerate(rows, 1):
        if r.aid != f"A-{n}":
            bad.append(f"{r.aid}: out of order (expected A-{n})")
        if r.op not in OPS or r.file not in TARGETS:
            bad.append(f"{r.aid}: unknown op {r.op!r} or a target outside `14` / `15`")
            continue
        named = at_base(TARGETS[r.file])
        if named is None:
            bad.append(f"{r.aid}: `{r.file}` is unreadable at {BASE}")
            continue
        bl = lines(named)
        if lines(r.new)[0] in bl and r.old not in bl:  # applied (post-merge, after PR 2)
            continue
        at = bl[r.line - 1] if 1 <= r.line <= len(bl) else ""
        if at != r.old:
            bad.append(f"{r.aid}: the Old is not `{r.file}`:{r.line}")
            continue
        if locate(bl, bl, r) != r.line - 1:
            bad.append(f"{r.aid}: the Old is not unique in its scope")
        if r.new == r.old:
            bad.append(f"{r.aid}: the New equals the Old")
    return bad


# ---------------------------------------------------------------------------- pins

Unit = tuple[str, str, str]
FULL_STOP = re.compile(r"(?<=[.!?])\s+(?=[*`\"(A-Z0-9§])")


def units(text: str, doc: str) -> list[Unit]:
    out: list[Unit] = []
    path: list[tuple[int, str]] = []
    seen: dict[str, int] = {}
    region, k, fence = f"{doc}:(top)#1", 0, -1
    rows: dict[str, int] = {}
    buf: list[str] = []
    for raw in lines(text):
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
            path = [p for p in path if p[0] < level] + [(level, norm(m.group(2)))]
            key = f"{doc}:" + " › ".join(p[1] for p in path)
            seen[key] = seen.get(key, 0) + 1
            region, k, rows = f"{key}#{seen[key]}", 0, {}
            out.append((region, "heading", norm(raw)))
            continue
        if not raw.strip() or RULE_ROW.match(raw):
            continue
        if raw.lstrip().startswith("|"):
            cells = split_row(raw)
            lead = norm(cells[0]) if cells else "(blank)"
            rows[lead] = rows.get(lead, 0) + 1
            loc = f"row {lead}" + (f"#{rows[lead]}" if rows[lead] > 1 else "")
            out.append((region, loc, " | ".join(norm(c) for c in cells)))
            continue
        for x in FULL_STOP.split(raw.strip()):
            if x.strip():
                k += 1
                out.append((region, f"s{k}", norm(x)))
    return out


def doc_units(t: Texts) -> list[Unit]:
    return units(t.spec, "spec") + units(t.hand, "hand")


def write_pins(t: Texts) -> str:
    us = doc_units(t) + cite_units(t)
    head = (
        "# E08-D09 pins (every unit of the spec and the hand-off, then every cited line's words "
        f"at {BASE}): region, location, the exact normalised text; {len(us)} units.\n"
        "# Written by `--repin-ruled` only; `--check` reads it (never hand-edit; see the tool's "
        "G-RULED-PIN and G-CITE).\n"
    )
    return head + "".join("\t".join(u) + "\n" for u in us)


def parse_pins(text: str) -> list[Unit]:
    out: list[Unit] = []
    for ln in lines(text):
        parts = ln.split("\t")
        if ln and not ln.startswith("#") and len(parts) == 3:
            out.append((parts[0], parts[1], parts[2]))
    return out


def pin_problems(t: Texts) -> list[str]:
    """One message per region that differs (the cite pins are G-CITE's)."""
    pinned = [u for u in parse_pins(t.pins) if not u[0].startswith("cite:")]
    if not pinned:
        return ["the pins file is empty or missing (run --repin-ruled)"]
    bad: list[str] = []
    by_old: dict[str, list[tuple[str, str]]] = {}
    by_new: dict[str, list[tuple[str, str]]] = {}
    for r, loc, txt in pinned:
        by_old.setdefault(r, []).append((loc, txt))
    for r, loc, txt in doc_units(t):
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
                    what = f"{loc} changed: {txt[:40]!r}"
                    break
            bad.append(f"'{r[-48:]}' {what}")
    return bad


# ---------------------------------------------------------------------------- G-PUBLIC and G-PIN

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
    "|".join(re.escape(w[::-1]) for w in _HIDDEN) + "|" + "sod"[::-1], re.IGNORECASE
)
LOCAL_PATH = re.compile("/" + "(?:home|Users|mnt|tmp)" + r"/[^\s`)]+")
HOSTNAME = re.compile(r"\b[a-z0-9-]+\.(?:com|net|org|io)\b|\bpenpot\.[a-z0-9-]+\.", re.IGNORECASE)
UUID = re.compile(r"\b[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}\b")
URL = re.compile(r"https?://", re.IGNORECASE)
CLOSING = re.compile(
    r"\b(?:close[sd]?|fix(?:e[sd])?|resolve[sd]?)\s*:?\s*(?:[\w-]+/[\w-]+)?#\d+", re.IGNORECASE
)
AGENTS = re.compile(
    r"\b(?:" + "lch|eph"[::-1] + r")-" + "rekrow"[::-1] + r"-\d\b|\bsession [0-9a-f]{8}",
    re.IGNORECASE,
)


def public_problems(t: Texts) -> list[str]:
    bad: list[str] = []
    checks = (
        (BANNED, "a word on the public-text list"),
        (LOCAL_PATH, "a local path"),
        (HOSTNAME, "a host name"),
        (UUID, "a uuid"),
        (URL, "a URL"),
        (CLOSING, "a closing keyword"),
        (AGENTS, "an agent or session name"),
    )
    for name, text in docs(t):
        for rx, what in checks:
            for m in rx.finditer(text):
                bad.append(f"{name}: {what} ({m.group(0)[:3]}…, offset {m.start()})")
    for name, text in (("tool", t.tool), ("pins", t.pins)):
        for rx, what in (checks[0], checks[6]):
            for m in rx.finditer(text):
                bad.append(f"{name}: {what} ({m.group(0)[:3]}…, offset {m.start()})")
    return bad


SHA_OR_ID = re.compile(r"(?<![\w#/-])([0-9a-f]{10})(?![\w-])")
KNOWN_SHAS = frozenset({BASE, BQ_BASE, D12_SHA})
KNOWN_IDS = frozenset({RULING_ID, BQ_ID, DELEGATION_ID, D12_PRE_ID, ORCH_R1_ID})


def pin_ref_problems(t: Texts) -> list[str]:
    bad: list[str] = []
    for name, text in docs(t):
        for m in SHA_OR_ID.finditer(text):
            ref = m.group(1)
            if ref not in (KNOWN_IDS if ref.isdigit() else KNOWN_SHAS):
                bad.append(f"{name}: {ref} is not a pinned sha or comment id")
    return bad


# ---------------------------------------------------------------------------- G-RULED

BQS = tuple(f"BQ-{n:02d}" for n in range(1, 27))


def ruled_problems(t: Texts) -> list[str]:
    bad: list[str] = []
    for name, text in docs(t):
        if "<!-- BQ-" in text:
            bad.append(f"{name}: a BQ marker is left")
        for n in re.findall(r"\(RULED BQ-(\d+)\)", text):
            if f"BQ-{n}" not in BQS:
                bad.append(f"{name}: (RULED BQ-{n}) names no question")
    head = "\n".join(lines(t.spec)[:12])
    for ref in (RULING_ID, BQ_ID):
        if ref not in head:
            bad.append(f"the spec's header does not name {ref}")
    qsec = section(t.spec, "The questions BQ-01")
    got = re.findall(r"^- \*\*(BQ-\d\d)\.\*\* (.{0,90})", qsec, re.MULTILINE)
    if [b for b, _ in got] != list(BQS):
        bad.append("the questions section does not list BQ-01 … BQ-26 in order")
    for b, rest in got:
        if not rest.startswith(STAMP + ":"):
            bad.append(f"{b}: its stamp is not {STAMP!r}")
    for p in RULING_PINS:
        if p not in t.spec:
            bad.append(f"a ruled phrase is missing from the spec: {p[:50]!r}")
    return bad


# ---------------------------------------------------------------------------- G-UNTOUCHED


def pr2_text(t: Texts, file: str) -> str | None:
    named = at_base(TARGETS[file])
    if named is None:
        return None
    return apply_rows(dict(t.mbase).get(file, ""), named, a_rows(t.hand)[0], file)


def untouched_problems(t: Texts) -> list[str]:
    if t.changed is None or not t.mbase:
        return ["git cannot name the changed paths or the merge-base (fail closed)"]
    if not t.mbase_spec:  # PR 1: the spec is not at the merge-base yet
        return [
            f"PR 1 changes {p}, not one of the own paths" for p in t.changed if p not in OWN_PATHS
        ]
    targets = [k for k, rel in TARGETS.items() if rel in t.changed]
    if not targets:  # post-merge, a later PR (the boards): own paths, PNGs and sheets only
        return [
            f"post-merge: {p} is not an own path, a board PNG or a sheet"
            for p in t.changed
            if p not in OWN_PATHS and not p.startswith(LATER_PREFIXES)
        ]
    allowed = (*TARGETS.values(), PINS_REL)
    bad = [f"PR 2 changes {p}, not `14`, `15` or the pins" for p in t.changed if p not in allowed]
    now = dict(t.now)
    for key in targets:
        want = pr2_text(t, key)
        if want is None:
            bad.append(f"PR 2: a §C row for `{key}` cannot be re-pointed at the merge-base")
        elif now.get(key) != want:
            bad.append(f"PR 2: `{key}` is not the merge-base with §C applied, byte for byte")
    if PINS_REL in t.changed and t.pins != write_pins(t):
        bad.append("PR 2: the pins rewrite is not byte-exact (--repin-ruled)")
    return bad


# ---------------------------------------------------------------------------- findings and gates


@dataclass(frozen=True)
class Finding:
    gate: str
    level: str
    msg: str


GATES: tuple[tuple[str, Callable[[Texts], list[str]]], ...] = (
    ("G-CITE", cite_problems),
    ("G-QUOTE", quote_problems),
    ("G-CARVE", carve_problems),
    ("G-NEVER", never_problems),
    ("G-STATE", state_problems),
    ("G-TOKEN", token_problems),
    ("G-D12", d12_problems),
    ("G-LEDGER", ledger_problems),
    ("G-T2", t2_problems),
    ("G-UNTOUCHED", untouched_problems),
    ("G-AROW", arow_problems),
    ("G-RULED", ruled_problems),
    ("G-RULED-PIN", pin_problems),
    ("G-PUBLIC", public_problems),
    ("G-PIN", pin_ref_problems),
)


def run(t: Texts) -> list[Finding]:
    out: list[Finding] = []
    for gate, fn in GATES:
        out += [Finding(gate, "FAIL", m) for m in fn(t)]
    if any(f.level == "FAIL" and f.gate != "G-RULED-PIN" for f in out):
        out = [replace(f, level="NOTE") if f.gate == "G-RULED-PIN" else f for f in out]
    return out


def values(t: Texts) -> dict[str, int]:
    rows = a_rows(t.hand)[0]
    return {
        "states": len(register(t.spec)),
        "ledger": len(ledger(t.spec)),
        "deck_rows": len(deck(t.spec)),
        "c_rows": len(rows_of(t.spec, "21.1", "C")),
        "g_rows": len(rows_of(t.spec, "21.2", "G")),
        "q_rows": len(re.findall(r"^- \*\*D09-Q\d+\*\*", t.spec, re.MULTILINE)),
        "a_rows": len(rows),
        "a_rows_14": sum(r.file == "14" for r in rows),
        "a_rows_15": sum(r.file == "15" for r in rows),
        "cites": len(cite_lines(t)),
        "gates": len(GATES),
        "mutations": len(MUTATIONS),
        "probes": len(PROBES),
    }


def changed_paths() -> tuple[str, ...] | None:
    mb = git("merge-base", "HEAD", "origin/main")
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


def load() -> Texts:
    mb = git("merge-base", "HEAD", "origin/main")
    ref = mb.strip() if mb else ""
    mbase = (
        tuple((k, git("show", f"{ref}:{rel}") or "") for k, rel in TARGETS.items()) if ref else ()
    )
    return Texts(
        spec=read(SPEC_REL),
        hand=read(HAND_REL),
        pins=read(PINS_REL),
        tool=read(TOOL_REL),
        changed=changed_paths(),
        now=tuple((k, read(rel)) for k, rel in TARGETS.items()),
        mbase=mbase,
        mbase_spec=(git("show", f"{ref}:{SPEC_REL}") or "") if ref else "",
    )


# ---------------------------------------------------------------------------- the self-test

Lever = Callable[[Texts], Texts]


def _sub(field_name: str, old: str, new: str) -> Lever:
    def f(t: Texts) -> Texts:
        text = getattr(t, field_name)
        if old not in text:
            raise SystemExit(f"self-test: {old[:50]!r} not found in {field_name}")
        return replace(t, **{field_name: text.replace(old, new, 1)})

    return f


def _row(rid: str, old: str, new: str) -> Lever:
    """Change `old` to `new` on the spec's table row whose first cell is `rid` only."""

    def f(t: Texts) -> Texts:
        ls = lines(t.spec)
        k = next(i for i, ln in enumerate(ls) if re.match(rf"\| {re.escape(rid)} +\|", ln))
        if old not in ls[k]:
            raise SystemExit(f"self-test: {old!r} not on row {rid}")
        ls[k] = ls[k][::-1].replace(old[::-1], new[::-1], 1)[::-1]
        return replace(t, spec="\n".join(ls))

    return f


def _cell(rid: str, k: int, new: str) -> Lever:
    """Set cell `k` of the spec's table row whose first cell is `rid`."""

    def f(t: Texts) -> Texts:
        ls = lines(t.spec)
        i = next(i for i, ln in enumerate(ls) if re.match(rf"\| {re.escape(rid)} +\|", ln))
        cells = split_row(ls[i])
        cells[k] = new
        ls[i] = "| " + " | ".join(cells) + " |"
        return replace(t, spec="\n".join(ls))

    return f


def _changed(*extra: str) -> Lever:
    def f(t: Texts) -> Texts:
        return replace(t, changed=(*(t.changed or ()), *extra))

    return f


MUTATIONS: tuple[tuple[str, str, Lever], ...] = (
    ("G-CITE", "a load-bearing cite moved by one line", _sub("spec", "`clock`:129", "`clock`:128")),
    ("G-QUOTE", "a verbatim string reworded", _row("W-20", "Connection unstable", "Unstable link")),
    (
        "G-CARVE",
        "a protective action said to go through",
        _sub("spec", "**Bars step.**", "**Bars step.** Stops go through."),
    ),
    ("G-NEVER", "a UID in a string", _row("W-45", "socket {1}", "socket {1} · UID {1}")),
    ("G-STATE", "a state's rate made non-numeric", _row("S-12", "≤ 1 per 5 s per region", "often")),
    (
        "G-TOKEN",
        "an unshipped token",
        _sub("spec", "`type.num.base`, end-aligned", "`type.num.nonesuch`, end-aligned"),
    ),
    ("G-D12", "a checklist verdict outside R-3", _row("Target sizes", "compliant", "fine")),
    ("G-LEDGER", "a G-row without an owner", _row("D09-G12", "E09", " ")),
    ("G-UNTOUCHED", "PR 1 edits a plan doc", _changed("docs/plan/12-sitemap.md")),
    (
        "G-AROW",
        "an Old no longer its line",
        _sub("hand", "recent 10018 events, the fan-out", "recent 10018 events,  the fan-out"),
    ),
    (
        "G-RULED",
        "a stamp shortened",
        _sub("spec", STAMP + ": the paths", "RULED (orchestrator): the paths"),
    ),
    (
        "G-RULED-PIN",
        "an unpinned sentence edit",
        _sub("spec", "Desk work at the base", "Desk work at this base"),
    ),
    ("G-PUBLIC", "a host name", _sub("hand", "Rule: every line", "Rule (example.com): every line")),
    ("G-PIN", "an unknown sha", _sub("spec", "`b148ca4703`", "`b148ca4704`")),
    # Round 1's mutations: each slipped past the content gates before the fold.
    (
        "G-CARVE",
        "a protective control said to be disabled (prose)",
        _sub(
            "spec", "**Bars step.**", "**Bars step.** While a hold lasts, Cancel order is disabled."
        ),
    ),
    (
        "G-CARVE",
        "a promise that protective stops succeed during a hold",
        _sub("spec", "**Bars step.**", "**Bars step.** Protective stops will still succeed then."),
    ),
    (
        "G-NEVER",
        "the request id named as shown (prose)",
        _sub("spec", "**Bars step.**", "**Bars step.** Rows may show the request id."),
    ),
    (
        "G-NEVER",
        "a trace id inside an SR string",
        _row("SCR-147-SR-3", "All requests on hold", "Trace id 7, all requests on hold"),
    ),
    (
        "G-NEVER",
        "the served detail on S-17",
        _row("S-17", "never the served `detail`", "the served `detail`"),
    ),
    (
        "G-QUOTE",
        "a ruled string reworded",
        _row("W-36", "All requests are on hold.", "Requests are paused."),
    ),
    ("G-STATE", "a danger state wearing the neutral glyph", _row("S-05", "octagon", "ring")),
    # The orchestrator's round-1 read: the inbound ledger, the shell's pair, R-9.
    (
        "G-LEDGER",
        "a required ledger source dropped",
        _row("L-15", "`E30-D03`:275", "`E30-D03`:276"),
    ),
    ("G-LEDGER", "a ledger disposition outside the vocabulary", _row("L-1", "applied", "taken")),
    ("G-STATE", "a throttle announced assertively", _cell("SCR-147-SR-2", 3, "assertive")),
    (
        "G-STATE",
        "a section-level live region",
        _row("SCR-147-SR-8", "the shell's polite region", "the clock section's status"),
    ),
    (
        "G-T2",
        "R-9 lost from §12",
        _sub("spec", "(§13.1; R-9)", "(§13.1)"),
    ),
    (
        "G-T2",
        "R-9's `disabled` clause weakened",
        _sub("spec", "never the `disabled` attribute", "or the `disabled` attribute"),
    ),
)


def _pr2(t: Texts, extra: str = "") -> Texts:
    now = []
    for k in TARGETS:
        want = pr2_text(replace(t, mbase_spec=t.spec), k) or ""
        now.append((k, want + extra if k == "14" else want))
    return replace(t, mbase_spec=t.spec, changed=tuple(TARGETS.values()), now=tuple(now))


# (name, lever, the number of G-UNTOUCHED FAILs expected: 0 or "at least one" as -1)
PROBES: tuple[tuple[str, Lever, int], ...] = (
    ("PR 2: §C applied byte for byte", lambda t: _pr2(t), 0),
    ("PR 2: one stray line in `14`", lambda t: _pr2(t, "\nstray"), -1),
    (
        "post-merge: the boards PR",
        lambda t: replace(t, mbase_spec=t.spec, changed=(SPEC_REL, LATER_PREFIXES[0] + "01.png")),
        0,
    ),
    (
        "post-merge: a plan doc edited",
        lambda t: replace(
            t, mbase_spec=t.spec, changed=(SPEC_REL, "docs/plan/05-accessibility-standard.md")
        ),
        -1,
    ),
    ("git cannot answer", lambda t: replace(t, changed=None), -1),
)


def digests() -> dict[str, str]:
    rels = (*OWN_PATHS, *TARGETS.values())
    return {r: hashlib.sha256(read(r).encode("utf-8")).hexdigest() for r in rels}


def self_test(t: Texts) -> list[str]:
    before = digests()
    base = run(t)
    base_fails = {(f.gate, f.msg) for f in base if f.level == "FAIL"}
    bad: list[str] = []
    gates = [g for g, _ in GATES]
    if {g for g, _, _ in MUTATIONS} != set(gates):
        bad.append("self-test: a gate has no mutation")
    for gate, desc, lever in MUTATIONS:
        found = run(lever(t))
        new = {(f.gate, f.msg) for f in found if f.level == "FAIL"} - base_fails
        if not new or any(g != gate for g, _ in new):
            got = sorted({g for g, _ in new}) or ["none"]
            bad.append(f"self-test: {gate} mutation ({desc}) gave {', '.join(got)}")
    for name, lever, want in PROBES:
        n_got = len(untouched_problems(lever(t)))
        if (want == 0 and n_got) or (want < 0 and not n_got):
            bad.append(f"self-test: probe {name!r} gave {n_got} G-UNTOUCHED FAIL(s)")
    if {(f.gate, f.msg) for f in run(t) if f.level == "FAIL"} != base_fails:
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
    ap.add_argument("--self-test", action="store_true", help="one mutation per gate, the probes")
    ap.add_argument("--repin-ruled", action="store_true", help="rewrite the pins file")
    ap.add_argument("--a-rows", action="store_true", help="print §C as JSON, a target per row")
    args = ap.parse_args(argv)
    if any(not key_text(k) for k in KEYS) or not key_text("C"):
        print(f"FAIL [G-CITE] the inputs are unreadable at {BASE} (fetch first)")
        return 1
    t = load()
    if args.a_rows:
        print(json.dumps(export(a_rows(t.hand)[0]), ensure_ascii=False, indent=1))
        return 0
    if args.repin_ruled:
        write_if_changed(PINS_REL, write_pins(t))
        t = load()
    found = run(t)
    st = self_test(t) if args.self_test else []
    n_fail = sum(f.level == "FAIL" for f in found)
    n_warn = sum(f.level == "WARN" for f in found)
    if args.json:
        payload: dict[str, object] = {
            "values": values(t),
            "findings": [f"{f.level} [{f.gate}] {f.msg}" for f in found],
        }
        if args.self_test:
            payload["self_test"] = st
        print(json.dumps(payload, ensure_ascii=False, indent=1, sort_keys=True))
    else:
        out = [f"{f.level} [{f.gate}] {f.msg}" for f in found]
        v = values(t)
        out.append(
            f"gates: {v['gates']}; FAIL {n_fail}, WARN {n_warn}; states {v['states']}; ledger "
            f"{v['ledger']}; deck rows "
            f"{v['deck_rows']}; C/G/Q rows {v['c_rows']}/{v['g_rows']}/{v['q_rows']}; §C rows "
            f"{v['a_rows']} ({v['a_rows_14']} to `14`, {v['a_rows_15']} to `15`); cites {v['cites']}"
        )
        if args.self_test:
            out += [f"FAIL [self-test] {x}" for x in st]
            out.append(
                f"self-test: {'ok' if not st else 'FAILED'}: {len(MUTATIONS)} mutations (at least "
                f"one per gate) and {len(PROBES)} mode probes; each mutation adds FAILs from its own gate "
                "only; a re-run reproduces the base result; files on disk unchanged"
            )
        print("\n".join(out))
    failed = n_fail > 0 or bool(st)
    return 1 if failed and (args.check or args.self_test) else 0


if __name__ == "__main__":
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")
    raise SystemExit(main(sys.argv[1:]))
