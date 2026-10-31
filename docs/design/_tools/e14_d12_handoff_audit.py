#!/usr/bin/env python3
"""E14-D12 (#355) audit: the engineering hand-off pack for the drawing tools (SCR-036's drawings
branch, SCR-037, SCR-045's drawing entry; CMP-191, CMP-223).

Standalone, offline, stdlib only; it runs under `python3 -I` and executes no repo code. It reads
AS TEXT at the pinned base `BASE` (`git show`): the plan texts, the merged E14 design docs (D02 ...
D09 and the hand-off twins), the constitution's C-14.2 row, the design-spec rule file, the
calendar and the E14 backlog JSON; then the pack (`E14-D12.md`), the deck (`E14-D12-copy.json`),
`14` and the pins from the working tree. E14-D10 (#354) is not on the base: nothing of it is read.

Values. Every `{{KIND:key}}` outside a code span is computed and `--fill` writes it as
`VALUE<!--=KIND:key-->`; a `{{COPY:key}}` line becomes a block between `<!-- COPY:key -->` and
`<!-- /COPY:key -->`: a source block byte-equal to its source at the base, or a derived table.
`--check` re-derives every anchored value and every block; no placeholder may remain.

Gates (one mutation each in `--self-test`):
  G-VALUES    the anchored SHA, STATUS, CITE, DPX, NAMES and plain COUNT values; a CITE value is
              read from its defining line (the line that states the figure), never a bare word.
  G-LIFT      every HASH anchor equals the sha256 (12 hex) of its lifted span, each line
              whitespace-normalised.
  G-COPY      every source COPY block equals its source block at the base, byte for byte.
  G-CITE      every `KEY`:line cite (and its `, :n` continuations) is in range at the base and the
              range's ends are non-blank; copied blocks are the source's own and are skipped.
  G-VERSION   every cited line's content stands at `origin/main` (moved = WARN, gone = FAIL).
  G-TOOLS     the derived behaviour table equals its derivation cell by cell (one row per `22`
              `DrawingTool` value), and the anchor count agrees at `22`, D02's registry, D04's
              schema and D07's templates.
  G-GLYPHS    the derived glyph register equals D03 §2.1 + §2.2 cell by cell; the `15` count.
  G-INDEX     one row per story E14-S01..S10; US-DRAW-001..009 each on its story; every frame
              cell a board whose PNG is on the base or "text only"; every § a heading of its doc.
  G-DECK      the deck equals the derivation from the five parents' copy tables (each entry
              anchored at its own row); every PROPOSED entry names an owner.
  G-ROWS      the register: ids unique, the four grades, an owner cell "<spec>; <area>" from the
              ruled sets, a due cell from the ruled forms, a cite on every row; the four ruled
              contradictions (C-1..C-4) and the E14-D10 G-row present; the counts.
  G-T2        the T2 table: the rendering, the §3.1 key and §3.2 verb per row, CMP-079 RbacGate on
              every role leg and the CMP-019 `lock` on every row; the stated attributes; the
              companions row names CMP-079 and CMP-019 (G-T2.1b, .1c, .1d, .6).
  G-MNR       the must-not-regress set: each budget row a CITE value and an owner; the 58-fps row
              names C-14.2 as its owner and cites `26`; "hard-disabled" only inside a quote of the
              ticket; the send-to-ticket sentence is the byte copy of D06 §6.4.
  G-EVENTS    every `drawing.*` name outside a copy is a D02 §14 name or a `14` analytics name.
  G-PENDING   E14-D10 is absent at the base and never cited; the chapter says so (a WARN once it
              is on `origin/main` and v1.1 has not folded it).
  G-AHEAD     the sprint, date and margin values from the calendar and the backlog JSON.
  G-UNTOUCHED PR-1 mode: the tree differs from the merge-base only in this pack's files and `14`,
              and `14` equals the merge-base with the three pointer lines and the SCR-037 ticks
              applied by content. Post-merge mode: `14` is untouched.
  G-TICKS     every SCR-037 tick's evidence resolves at its source: a `§n` to a heading of the
              named parent, a board to its PNG on the base; the pack's evidence table agrees.
  G-FROZEN    post-merge mode: every version row of the merge-base stands unchanged and a new
              row is v1.N with N above the last.
  G-RULED     the ruling stamp on the questions heading, the ruling id, BQ-01..BQ-16, no marker.
  G-HYGIENE   no placeholder left, no stray HTML comment, no closing keyword outside a code span,
              no local path, agent name, host or URL, none of the public-text words.
  G-RULED-PIN a default-deny pin set over every unit of the pack (values cut out, blocks
              collapsed), every deck entry and every cite's line hash; only `--repin-ruled`
              writes it. Its findings print as NOTE while another gate FAILs.

Usage (from the repo root):
  python3 -I docs/design/_tools/e14_d12_handoff_audit.py --check [--json] [--fill]
  python3 -I docs/design/_tools/e14_d12_handoff_audit.py --self-test
  python3 -I docs/design/_tools/e14_d12_handoff_audit.py --repin-ruled
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
import time
import unicodedata
from collections.abc import Callable
from dataclasses import dataclass, replace
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
BASE = "9518fe3cbd"  # the base of record: every cite was read here (the version line)
HEAD_REF = "origin/main"
VERSION_DATE = datetime.date(2026, 10, 31)  # v1's date: the design-ahead margins count from it
ISSUE = "355"
RULING_ID = "6547862678"
STAMP = "RULED (orchestrator, 2026-10-31, #355 ruling of record — 6547862678 on 6547452932)"
BQ_TOTAL = 16

SPEC_REL = "docs/design/E14/E14-D12.md"
DECK_REL = "docs/design/E14/E14-D12-copy.json"
TOOL_REL = "docs/design/_tools/e14_d12_handoff_audit.py"
PIN_REL = "docs/design/_tools/e14_d12_ruled_pins.txt"
PLAN14_REL = "docs/plan/14-screens-catalogue.md"
OWN_PATHS = (SPEC_REL, DECK_REL, TOOL_REL, PIN_REL, PLAN14_REL)
IMG_REL = "docs/design/E14/img"
D10_REL = "docs/design/E14/E14-D10.md"

PATHS: dict[str, str] = {
    "02": "docs/plan/02-definition-of-ready-done.md",
    "05": "docs/plan/05-accessibility-standard.md",
    "11": "docs/plan/11-user-stories.md",
    "14": PLAN14_REL,
    "15": "docs/plan/15-component-catalogue.md",
    "21": "docs/plan/21-database-schema.md",
    "22": "docs/plan/22-api-openapi.yaml",
    "26": "docs/plan/26-chart-engine-design.md",
    "30": "docs/plan/30-release-roadmap.md",
    "CON": "CONSTITUTION.md",
    "RULE": ".claude/rules/32-design-specs.md",
    "D02": "docs/design/E14/E14-D02.md",
    "D03": "docs/design/E14/E14-D03.md",
    "D03H": "docs/design/E14/E14-D03-handoff.md",
    "D04": "docs/design/E14/E14-D04.md",
    "D04H": "docs/design/E14/E14-D04-handoff.md",
    "D05": "docs/design/E14/E14-D05.md",
    "D05H": "docs/design/E14/E14-D05-handoff.md",
    "D06": "docs/design/E14/E14-D06.md",
    "D06H": "docs/design/E14/E14-D06-handoff.md",
    "D07": "docs/design/E14/E14-D07.md",
    "D07H": "docs/design/E14/E14-D07-handoff.md",
    "D08": "docs/design/E14/E14-D08.md",
    "D08H": "docs/design/E14/E14-D08-handoff.md",
    "D09": "docs/design/E14/E14-D09.md",
    "D10": D10_REL,
    "README": "docs/design/README.md",
    "E06-D03": "docs/design/E06/E06-D03.md",
    "CAL": "docs/plan/backlog/_tools/calendar_cv.py",
    "E14J": "docs/plan/backlog/E14.json",
}
# the parents a frame or a tick may name (ticket key -> PATHS key)
DOCS = {f"E14-D0{n}": f"D0{n}" for n in range(2, 10)}

# the blocks copied byte for byte (key -> the source and its heading prefix)
COPIES: dict[str, tuple[str, str]] = {
    "d06.s64": ("D06", "### 6.4 "),
    "d02.s14": ("D02", "## 14. "),
}
DERIVED = ("tools", "glyphs")  # the blocks the tool derives (G-TOOLS, G-GLYPHS)
# the blocks lifted by hash (key -> the source and its spans: (start heading, end heading or ""))
LIFTS: dict[str, tuple[str, tuple[tuple[str, str], ...]]] = {
    "d02.s22": ("D02", (("### 2.2 ", ""),)),
    "d02.s43": ("D02", (("### 4.3 ", ""),)),
    "d02.s44": ("D02", (("### 4.4 ", ""), ("### 4.5 ", ""))),
    "d02.s10": ("D02", (("## 10. ", ""),)),
    "d02.s131": ("D02", (("### 13.1 ", ""),)),
    "d02.s132": ("D02", (("### 13.2 ", ""),)),
    "d03.s21": ("D03", (("### 2.1 ", ""), ("### 2.2 ", ""))),
    "d04.s3": ("D04", (("## 3. ", ""),)),
    "d05.s2_6": ("D05", (("## 2. ", "## 7. "),)),
    "d06.s61": ("D06", (("### 6.1 ", ""),)),
    "d07.s22": ("D07", (("### 2.2 ", ""),)),
    "d08.s5_7": ("D08", (("## 5. ", "## 8. "),)),
    "d09.s2_3": ("D09", (("## 2. ", "## 4. "),)),
    "d09.s5": ("D09", (("## 5. ", ""),)),
    "d03h": ("D03H", (("", ""),)),
    "d04h": ("D04H", (("", ""),)),
    "d05h": ("D05H", (("", ""),)),
    "d06h": ("D06H", (("", ""),)),
    "d07h": ("D07H", (("", ""),)),
    "d08h": ("D08H", (("", ""),)),
    # E14-D10 (#354), merged with #5229: lifted at v1.1 (RULED BQ-09)
    "d10.s4": ("D10", (("## 4. ", ""),)),
    "d10.s52": ("D10", (("### 5.2 ", ""),)),
    "d10.s6": ("D10", (("## 6. ", ""),)),
    "d10.s7": ("D10", (("## 7. ", ""),)),
    "d10.s82": ("D10", (("### 8.2 ", ""),)),
    "d10.s11": ("D10", (("## 11. ", ""),)),
    "d10.s121": ("D10", (("### 12.1 ", ""),)),
    "d10.s14": ("D10", (("## 14. ", ""),)),
    "d10.s15": ("D10", (("## 15. ", ""),)),
}
CHIPS = "Two named forms, one rule set."  # D08 §7, the chip heights' defining line
NFR008 = "NFR: undo stack ≥50 operations per symbol"  # `11` US-DRAW-008's NFR line
# CITE values: key -> (source, the defining line's needle, the figure's pattern)
CITES: dict[str, tuple[str, str, str]] = {
    "b8.frame_ms": ("26", "| B8  | Drawing interaction", r"\|\s*≤ (\d+) ms\s*\|"),
    "b8.pick_ms": ("26", "| B8  | Drawing interaction", r"pick ≤ (\d+) ms"),
    "r5.pick_ms": ("26", "| R5  | Overlays", r"in ≤ (\d+) ms"),
    "tol.pointer": ("26", "Grab handles use an enlarged", r"enlarged (\d+) px tolerance"),
    "tol.touch": ("26", "Grab handles use an enlarged", r"touch input uses (\d+) px"),
    "text.calls": ("26", "Target ≤ 6 text draw calls", r"Target ≤ (\d+) text draw calls"),
    "scr037.fps": ("14", "target: drag at >=", r"drag at >=(\d+) fps"),
    "scr037.count": ("14", "target: drag at >=", r"with (\d+) drawings"),
    "con.fps": ("CON", "| C-14.2 |", r"^\| C-14\.2 \| (\d+) fps"),
    "vwap.ms": ("D05", "each new bar extends one polyline", r"\(≤ (\d+) ms"),
    "d08.glyph_px": ("D08", "| glyph ", r"(\d+) px two-tone"),
    "d08.target_px": ("D08", "| target and tolerance", r"(\d+) × \d+ CSS px"),
    "d08.snap_px": ("D08", "| snap ", r"the (\d+) px TP-13 ring"),
    "d08.magnet_px": ("D08", "| snap marker ", r"(\d+) px magnet radius"),
    "d08.fill": ("D08", "| fill ", r"`style\.fill_opacity`, default ([\d.]+)"),
    "d08.stroke.thin": ("D08", "| stroke ", r"= (\d+) / \d+ / \d+ "),
    "d08.stroke.regular": ("D08", "| stroke ", r"= \d+ / (\d+) / \d+ "),
    "d08.stroke.bold": ("D08", "| stroke ", r"= \d+ / \d+ / (\d+) "),
    "d08.chip1.compact": ("D08", CHIPS, r"— (\d+) compact / \d+ comfortable"),
    "d08.chip1.comfortable": ("D08", CHIPS, r"— \d+ compact / (\d+) comfortable"),
    "d08.chip1.dense": ("D08", CHIPS, r"comfortable / (\d+) dense for one line"),
    "d08.chip2.compact": ("D08", CHIPS, r"one line, (\d+) / \d+ / \d+ for two"),
    "d08.chip2.comfortable": ("D08", CHIPS, r"one line, \d+ / (\d+) / \d+ for two"),
    "d08.chip2.dense": ("D08", CHIPS, r"one line, \d+ / \d+ / (\d+) for two"),
    "d08.label_px": ("D08", CHIPS, r"minimum (\d+) px CSS at 100 %"),
    "d04.width": ("D04", "| trendline        | `trendline`", r"`style\.width` (\d+\.\.\d+)"),
    "tree.nfr": ("11", NFR008, r"virtualised for ≥(\d+) objects"),
    "tree.threshold": ("D07", "| Q13 | the virtualisation threshold", r"the shell's (\d+)"),
}  # fmt: skip
# the device-pixel values: key -> (the CITE key, the factor)
DPX = {"glyph": "d08.glyph_px", "target": "d08.target_px", "pointer": "tol.pointer",
       "touch": "tol.touch", "snap": "d08.snap_px", "magnet": "d08.magnet_px",
       "label": "d08.label_px"}  # fmt: skip
# the backlog keys whose sprints the design-ahead record reads
SPRINT_KEYS = {
    "E14-T02": "t02", "E14-T04": "t04", "E14-S10": "s10", "E14-S01": "s01", "E14-S02": "s02",
    "E14-S03": "s03", "E14-S04": "s04", "E14-S05": "s05", "E14-S06": "s06", "E14-S07": "s07",
    "E14-S08": "s08", "E14-S09": "s09", "E14-Q01": "q01", "E14-D11": "d11", "E14-D12": "d12",
    "E14-D10": "d10",
}  # fmt: skip
MARGINS = ("t02", "s10", "s01", "s05")
AHEAD_DAYS = 14  # two seven-day sprints (`02` §3.1's design-ahead rule; CAL's sprint length)
# the five parents' copy tables: id prefix -> (source, heading prefix, owner of a PROPOSED row)
DECKS: dict[str, tuple[str, str, str]] = {
    "d02": ("D02", "## 12. ", "E14-D02 (#247)"),
    "d04": ("D04", "### 9.5 ", "E14-D04 (#318)"),
    "d05": ("D05", "### 9.4 ", "E14-D05 (#349)"),
    "d06": ("D06", "## 10. ", "E14-D06 (#350)"),
    "d07": ("D07", "### 12.2 ", "E14-D07 (#351)"),
}
FINALISER = "E14-D10 (#354) §7, lifted at v1.1"
# a row whose key or string carries a word of the public-text list is cited by its source row only
CITED_ONLY = "cited only: read the row at its source"
STORIES = {f"E14-S{n:02d}": f"US-DRAW-{n:03d}" for n in range(1, 10)} | {"E14-S10": "—"}

# the `14` edits (RULED BQ-14): one pointer line per screen after its anchor line, and the SCR-037
# ticks with evidence, applied by content to the merge-base's `14`
POINTER = (
    "- **Hand-off pack (drawings):** [E14-D12.md](../design/E14/E14-D12.md) v1 (E14-D12; owner "
    "approval pending; the index, the redlines, the per-tool behaviour table, the contracts and "
    "the open-decisions register for the drawing tools{tail})"
)
SCREENS: dict[str, tuple[str, str]] = {
    "SCR-036": ("- **Hand-off pack:** [E13-D06.md]", "; the drawings branch rows"),
    "SCR-037": ("- **DS contribution (E14-D08):** [E14-D08.md]", "; the checklist ticks cite §15"),
    "SCR-045": ("- **Handoff pack (E11-D09):** [E11-D09.md]", "; the drawing entry only"),
}
CHECKLIST_PREFIX = "- **Design sign-off acceptance checklist:** "
# SCR-037's six items: index (1-based) -> the evidence of its tick; an item absent stays `[ ]`
TICKS: dict[int, str] = {
    3: "E14-D04 §2, §8, boards 01, 05; E14-D02 §7",
    4: "E14-D02 §6, board 05; E14-D03 §4, board 03",
    5: "E14-D02 §9.1, §9.2, §5.6, boards 11, 12",
    6: "E14-D07 §6, boards 07, 08",
}

SEVERITIES = ("Blocking", "Major", "Minor", "Info")
AREAS = ("charting-ui", "chart-engine", "design-system", "backend-platform", "frontend-platform",
         "docs", "auth-rbac")  # fmt: skip
OWNER_SPEC = re.compile(
    r"E\d\d-[DSTQKX]\d\d \(#\d+\)(?: §\d+(?:\.\d+)?)?"
    r"|CONSTITUTION C-\d+\.\d+"
    r"|`\d\d` (?:CMP|SCR)-\d{3}'s owner"
    r"|E05 \(`15`'s owner\)"
)
DUE = re.compile(r"Sprint (\d\d)|at #5229's merge|at once|before READY")
REQUIRED_ROWS = {"C-1": "token id", "C-2": "pitchfork", "C-3": "audit", "C-4": "glyph"}
ROLE_KEYS = ("rbac.view_as", "rbac.permission")
STATE_KEYS = ("drawing.locked", "v.risk.cap", "pos.profile.none", "pos.symbol.status",
              "pos.wallet.stale", "lockout", "refusal.kill_switch_engaged")  # fmt: skip
T2_KEYS = (*ROLE_KEYS, *STATE_KEYS)
# the §3.2 verb of each permission leg (E09-D09 §3.2, as the parents state it)
LEG_VERB = {"workspaces:write": "save workspaces", "settings:write": "change settings",
            "alerts:write": "change alerts"}  # fmt: skip
# the parents' gated-control lists: (the pack row's Control prefix, the parent, its line, the
# needle on that line that names the control) — every one must have a row in §6.2's table
T2_EXPECTED: tuple[tuple[str, str, int, str], ...] = (
    ("rail drawing tools", "D03", 297, "on the drawing tools, lock-all, delete-all"),
    ("rail magnet mode", "D03", 297, "for magnet mode, keep tool active"),
    ("`[Draw]` menu", "D03", 297, '"Show tool rail"'),
    ("context menu Set as default", "D03", 297, "for the context menu's Set as default"),
    ("SCR-045 row action", "D02", 424, "a session without `workspaces:write`, or under view-as"),
    ("popover fields and actions", "D04", 281, "`workspaces:write` for every drawing field"),
    ("popover alert toggle", "D04", 281, "the alert toggle, once live, `alerts:write`"),
    ("popover flatten switch", "D04", 281, "the flatten switch"),
    ("popover on a locked drawing", "D04", 281, "`drawing.locked`"),
    ("tree row writes", "D07", 380, "By row kind:"),
    ("a locked row", "D07", 380, "a locked drawing's Move up"),
    ("measure Pin", "D05", 277, "Pin under view-as"),
    ("position tool on a locked drawing", "D06", 226, "SCR-037/position-locked"),
    ("Send to ticket, risk over", "D06", 262, "risk over the headroom"),
    ("Send to ticket, no active profile", "D06", 263, "no active profile"),
)  # fmt: skip
T2_TERMS = ('`aria-disabled="true"`', "`aria-describedby`", "CMP-079 RbacGate", "CMP-019 `lock`",
            "`decorative={false}`", '"Not available"', "`readonly`")  # fmt: skip
# the budgets §9.2 must carry, each by its CITE value
BUDGET_KEYS = ("scr037.fps", "b8.frame_ms", "b8.pick_ms", "text.calls", "vwap.ms", "tree.nfr")
PENDING = "pending, cited from the ticket text only"
OWNER_PENDING = "owner approval pending (#2701)"

PLACEHOLDER = re.compile(r"\{\{([A-Z]+:[^{}]+?)\}\}")
# a value is one code span or one run of value characters: never a leading bracket or quote, so a
# refresh cannot eat the punctuation in front of a value
ANCHORED = re.compile(r"(`[^`\n]*`|[^\s<|`(\[\"']+)<!--=([A-Z]+:[^>]+?)-->")
COPY_LINE = re.compile(r"^\{\{COPY:([a-z0-9._]+)\}\}$")
COPY_BLOCK = re.compile(
    r"^<!-- COPY:([a-z0-9._]+) -->\n.*?\n<!-- /COPY:\1 -->$", re.MULTILINE | re.DOTALL
)
CODE = re.compile(r"`[^`\n]*`")
HEADING = re.compile(r"^(#{1,6}) (.+)$")
RULE = re.compile(r"^\s*\|?\s*:?-{3,}")
CITE = re.compile(r"`(" + "|".join(re.escape(k) for k in sorted(PATHS, key=len, reverse=True))
                  + r")`:(\d+)(?:[–-](\d+))?")  # fmt: skip
CONT = re.compile(r"^(?:,\s*|\s+and\s+):(\d+)(?:[–-](\d+))?")
EVENT = re.compile(r"`(drawing\.[a-z_]+)")
FULL_STOP = re.compile(r"(?<=[.!?])\s+(?=[*`\"(A-Z0-9§])")
CLOSING = re.compile(r"\b(?:close[sd]?|fix(?:e[sd])?|resolve[sd]?)\s+#\d+", re.IGNORECASE)
# assembled, so the patterns never spell the strings they refuse
LOCAL_PATH = re.compile("/" + "home/|/Users/|[A-Za-z]:\\\\|\\bwt-" + "notes\\b")
AGENT_NAME = re.compile(r"\b[a-z]{2,4}-" + "worker" + r"-\d\b")
URL_OR_HOST = re.compile(r"https?://|penpot\.[a-z]|team-id=|file-id=", re.IGNORECASE)
_W = ("le" + "ak", "expo" + "sed", "by" + "pass", "expl" + "oit", "att" + "ack", "ora" + "cle",
      "rev" + "eal", "unbou" + "nded", "flo" + "od", "sta" + "ll", "d" + "os", "advi" + "sory",
      "gh" + "sa", "pre-" + "auth")  # fmt: skip
WORDS = re.compile("|".join(_W), re.IGNORECASE)


# ---------------------------------------------------------------------------- git and caches


def git_raw(*args: str) -> str | None:
    try:
        r = subprocess.run(["git", "-C", str(ROOT), *args], capture_output=True, check=False)
    except OSError:
        return None
    return r.stdout.decode("utf-8", "surrogateescape") if r.returncode == 0 else None


def git_ok(*args: str) -> bool:
    try:
        r = subprocess.run(["git", "-C", str(ROOT), *args], capture_output=True, check=False)
    except OSError:
        return False
    return r.returncode == 0


def merge_base() -> str | None:
    out = git_raw("merge-base", "HEAD", HEAD_REF)
    return out.strip() if out and re.fullmatch(r"[0-9a-f]{40}\s*", out) else None


def changed_paths(base: str) -> list[str] | None:
    """Committed and uncommitted paths that differ from the merge-base; None when git fails."""
    a = git_raw("diff", "--name-only", base)
    b = git_raw("status", "--porcelain", "--untracked-files=all")
    if a is None or b is None:
        return None
    out = {p for p in a.split("\n") if p}
    for ln in b.split("\n"):
        if len(ln) > 3:
            out.add(ln[3:].split(" -> ")[-1].strip('"'))
    return sorted(out)


@dataclass
class Env:
    base: str  # the full sha of BASE
    mb: str  # the merge-base with origin/main
    memo: dict[str, object]

    def show(self, rev: str, rel: str) -> str | None:
        key = f"show:{rev}:{rel}"
        if key not in self.memo:
            self.memo[key] = git_raw("show", f"{rev}:{rel}")
        v = self.memo[key]
        return v if isinstance(v, str) else None

    def at_base(self, rel: str) -> str:
        t = self.show(self.base, rel)
        if t is None:
            raise SystemExit(f"{rel} is missing at the base {self.base[:10]}")
        return t

    def lines(self, rev: str, rel: str) -> list[str]:
        t = self.show(rev, rel)
        return t.split("\n") if t is not None else []

    def tree(self, rev: str, prefix: str) -> list[str]:
        key = f"tree:{rev}:{prefix}"
        if key not in self.memo:
            out = git_raw("ls-tree", "-r", "--name-only", rev, "--", prefix) or ""
            self.memo[key] = [p for p in out.split("\n") if p]
        v = self.memo[key]
        return v if isinstance(v, list) else []

    def grep(self, rev: str, pattern: str, paths: tuple[str, ...]) -> bool:
        key = f"grep:{rev}:{pattern}:{paths}"
        if key not in self.memo:
            out = git_raw("grep", "-l", "-F", "-e", pattern, rev, "--", *paths)
            self.memo[key] = bool(out and out.strip())
        return bool(self.memo[key])


def read_raw(rel: str) -> str:
    with open(ROOT / rel, encoding="utf-8", newline="") as f:
        return f.read()


def write_text(rel: str, text: str) -> None:
    with open(ROOT / rel, "w", encoding="utf-8", newline="") as f:
        f.write(text)


# ---------------------------------------------------------------------------- text helpers


def pin_norm(text: str) -> str:
    return " ".join(unicodedata.normalize("NFKC", text).split())


def sha12(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()[:12]


def split_row(line: str) -> list[str]:
    body = line.strip().removeprefix("|")
    if body.endswith("|") and not body.endswith("\\|"):
        body = body[:-1]
    return [c.strip() for c in re.split(r"(?<!\\)\|", body)]


def tables(block: str) -> list[list[tuple[int, list[str]]]]:
    """The tables of a block, each a list of (0-based line index in the block, cells), rule rows
    dropped, the header row kept first."""
    out: list[list[tuple[int, list[str]]]] = []
    cur: list[tuple[int, list[str]]] = []
    for i, ln in enumerate(block.split("\n")):
        if ln.lstrip().startswith("|"):
            if not RULE.match(ln):
                cur.append((i, split_row(ln)))
        elif cur:
            out.append(cur)
            cur = []
    if cur:
        out.append(cur)
    return out


def table_after(block: str, header0: str) -> list[tuple[int, list[str]]]:
    for t in tables(block):
        if t and t[0][1] and t[0][1][0] == header0:
            return t[1:]
    return []


def rows_of(block: str, header0: str) -> list[list[str]]:
    return [c for _, c in table_after(block, header0)]


def span(lines: list[str], head: str, end: str = "") -> tuple[int, int]:
    """[start, stop) of the section whose heading starts with `head`: up to `end`'s heading when
    given, else to the next heading of the same or a higher level; (-1, -1) when absent."""
    if not head:
        return 0, len(lines)
    for i, ln in enumerate(lines):
        m = HEADING.match(ln)
        if m and ln.startswith(head):
            level = len(m[1])
            j = i + 1
            while j < len(lines):
                m2 = HEADING.match(lines[j])
                if end and lines[j].startswith(end):
                    break
                if not end and m2 and len(m2[1]) <= level:
                    break
                j += 1
            return i, j
    return -1, -1


def section(text: str, head: str) -> str:
    ls = text.split("\n")
    a, b = span(ls, head)
    return "\n".join(ls[a:b]) if a >= 0 else ""


def body_of(text: str, head: str) -> str | None:
    """A section's body: the lines after its heading, leading and trailing blank lines cut."""
    ls = text.split("\n")
    a, b = span(ls, head)
    if a < 0:
        return None
    body = ls[a + 1 : b]
    while body and not body[0].strip():
        body.pop(0)
    while body and not body[-1].strip():
        body.pop()
    return "\n".join(body)


def without_code(text: str) -> str:
    return CODE.sub("`…`", text)


def collapse_copies(text: str) -> str:
    return COPY_BLOCK.sub(lambda m: "{{COPY:" + m[1] + "}}", text)


def unfill(text: str) -> str:
    """The text with every anchored value back to its placeholder and every block collapsed."""
    text = collapse_copies(text)
    return ANCHORED.sub(lambda m: "{{" + m[2] + "}}", text)


def anchored(text: str) -> list[tuple[str, str, int]]:
    text = collapse_copies(text)
    return [
        (m[1], m[2], i) for i, ln in enumerate(text.split("\n"), 1) for m in ANCHORED.finditer(ln)
    ]


def unfilled(text: str) -> list[str]:
    """Every placeholder outside a code span and outside a filled block (a COPY line included)."""
    text = COPY_BLOCK.sub("", text)
    return [m[1] for ln in text.split("\n") for m in PLACEHOLDER.finditer(without_code(ln))]


def block_body(text: str, key: str) -> str | None:
    """The body of the filled block `key` (between its markers, the blank lines cut)."""
    for m in COPY_BLOCK.finditer(text):
        if m[1] == key:
            return m[0].split("\n", 1)[1].rsplit("\n", 1)[0].strip("\n")
    return None


def pad_table(rows: list[list[str]]) -> str:
    """A markdown table padded the way prettier pads one (header, rule, rows)."""
    width = [max(len(r[i]) for r in rows) for i in range(len(rows[0]))]
    width = [max(w, 3) for w in width]

    def line(r: list[str]) -> str:
        return "| " + " | ".join(c.ljust(width[i]) for i, c in enumerate(r)) + " |"

    rule = "| " + " | ".join("-" * w for w in width) + " |"
    return "\n".join([line(rows[0]), rule, *(line(r) for r in rows[1:])])


def table_cells(block: str) -> list[list[str]]:
    t = tables(block)
    return [c for _, c in t[0]] if t else []


# ---------------------------------------------------------------------------- the texts


@dataclass(frozen=True)
class Texts:
    env: Env
    spec: str
    deck: str
    pins: str
    plan14: str
    changed: list[str] | None
    values: dict[str, str]
    ticks: dict[int, str]  # SCR-037's ticks (TICKS), a field so a mutation can move them


def doc_text(t: Texts, key: str) -> str:
    return t.env.at_base(PATHS[key])


def both(t: Texts) -> tuple[tuple[str, str], ...]:
    return (("spec", t.spec),)


# ---------------------------------------------------------------------------- cites


def cites_in(text: str) -> list[tuple[str, int, int, int]]:
    """(key, first, last, 1-based line in the text) of every cite outside the copied blocks."""
    out: list[tuple[str, int, int, int]] = []
    text = collapse_copies(text)
    for n, ln in enumerate(text.split("\n"), 1):
        for m in CITE.finditer(ln):
            a = int(m[2])
            out.append((m[1], a, int(m[3]) if m[3] else a, n))
            pos = m.end()
            while True:
                c = CONT.match(ln[pos:])
                if not c:
                    break
                a2 = int(c[1])
                out.append((m[1], a2, int(c[2]) if c[2] else a2, n))
                pos += c.end()
    return out


def all_cites(t: Texts) -> list[tuple[str, str, int, int, int]]:
    return [(doc, k, a, b, n) for doc, text in both(t) for k, a, b, n in cites_in(text)]


# ---------------------------------------------------------------------------- values


def calendar(env: Env) -> tuple[datetime.date | None, int | None]:
    src = env.at_base(PATHS["CAL"])
    m = re.search(r"SPRINT01_START\s*=\s*datetime\.date\((\d+),\s*(\d+),\s*(\d+)\)", src)
    d = re.search(r"^SPRINT_DAYS\s*=\s*(\d+)", src, re.MULTILINE)
    return (datetime.date(int(m[1]), int(m[2]), int(m[3])) if m else None, int(d[1]) if d else None)


def sprints(env: Env) -> dict[str, int]:
    data = json.loads(env.at_base(PATHS["E14J"]))
    items = data if isinstance(data, list) else []
    out: dict[str, int] = {}
    for it in items:
        if isinstance(it, dict) and it.get("key") in SPRINT_KEYS:
            m = re.search(r"(\d+)", str(it.get("sprint", "")))
            if m:
                out[SPRINT_KEYS[str(it["key"])]] = int(m[1])
    return out


def ahead_values(env: Env) -> dict[str, str]:
    vals: dict[str, str] = {}
    start, days = calendar(env)
    sp = sprints(env)
    if not start or not days:
        return vals

    def first(n: int) -> datetime.date:
        return start + datetime.timedelta(days=(n - 1) * days)

    for k, n in sp.items():
        vals[f"SPRINT:{k}"] = f"{n:02d}"
    for k in MARGINS:
        if k in sp:
            margin = (first(sp[k]) - VERSION_DATE).days
            vals[f"DATE:{k}.start"] = first(sp[k]).isoformat()
            vals[f"DAYS:margin.{k}"] = str(margin)
            vals[f"DAYS:short.{k}"] = str(max(0, AHEAD_DAYS - margin))
    if "d12" in sp:
        vals["DATE:d12.end"] = (first(sp["d12"] + 1) - datetime.timedelta(days=1)).isoformat()
    return vals


def cite_values(env: Env) -> dict[str, str]:
    vals: dict[str, str] = {}
    for key, (src, needle, pat) in CITES.items():
        hits = [ln for ln in env.lines(env.base, PATHS[src]) if needle in ln]
        found = [m[1].strip() for ln in hits for m in [re.search(pat, ln)] if m]
        if len(found) == 1:
            vals[f"CITE:{key}"] = found[0].replace(" / ", "/")
    for key, ck in DPX.items():
        v = vals.get(f"CITE:{ck}")
        if v and v.isdigit():
            vals[f"DPX:{key}.2x"] = str(int(v) * 2)
    return vals


def status_values(env: Env) -> dict[str, str]:
    feats = [
        p.split("/")[4] for p in env.tree(env.base, "apps/web/src/features") if p.count("/") > 4
    ]
    vals = {"STATUS:web.e14": "present" if any("draw" in f for f in feats) else "absent"}
    for key, name in (("ui.cmp223", "DrawingToolbar"), ("ui.cmp191", "DrawingToolOverlay"),
                      ("ui.glyphs", "trendline")):  # fmt: skip
        vals[f"STATUS:{key}"] = "present" if env.grep(env.base, name, ("packages",)) else "absent"
    vals["STATUS:d10"] = "present" if D10_REL in env.tree(env.base, D10_REL) else "absent"
    return vals


def lift_hash(t: Texts, key: str) -> str | None:
    src, spans = LIFTS[key]
    ls = t.env.at_base(PATHS[src]).split("\n")
    parts: list[str] = []
    for head, end in spans:
        a, b = span(ls, head, end)
        if a < 0:
            return None
        parts.append("\n".join(pin_norm(x) for x in ls[a:b]))
    return sha12("\n".join(parts))  # whitespace-normalised: a table re-padded keeps its hash


# ---------------------------------------------------------------------------- `22` and the parents


def tool_block(env: Env) -> list[str]:
    """`22`'s `DrawingTool` schema: its lines up to the next schema."""
    ls = env.lines(env.base, PATHS["22"])
    a = next((i for i, ln in enumerate(ls) if ln == "    DrawingTool:"), -1)
    if a < 0:
        return []
    b = next((i for i in range(a + 1, len(ls)) if re.match(r"^    [A-Za-z]", ls[i])), len(ls))
    return ls[a:b]


def tool_enum(env: Env) -> list[str]:
    ls = tool_block(env)
    a = next((i for i, ln in enumerate(ls) if ln.strip() == "enum:"), -1)
    out: list[str] = []
    for ln in ls[a + 1 :] if a >= 0 else []:
        m = re.fullmatch(r"\s+- ([a-z_]+)", ln)
        if not m:
            break
        out.append(m[1])
    return out


def point_counts(env: Env) -> dict[str, str]:
    """Tool -> its required point count, read from `22`'s own bullet list (its definition)."""
    text = " ".join(x.strip() for x in tool_block(env))
    m = re.search(r"Required point count per tool.*?(?=Tool-specific)", text)
    out: dict[str, str] = {}
    for bullet in re.split(r"\s- ", m[0]) if m else []:
        e = re.match(r"exactly (\d+):", bullet)
        if e:
            for name in re.findall(r"`([a-z_]+)`", bullet):
                out[name] = e[1]
        for rng, name in re.findall(r"(\d+\.\.\d+): `([a-z_]+)`", bullet):
            out[name] = rng
    return out


def geometry_keys(env: Env) -> dict[str, list[str]]:
    """Tool -> the tool-specific `geometry` keys `22`'s key rules allow it."""
    text = " ".join(x.strip() for x in tool_block(env))
    out: dict[str, list[str]] = {}
    for key, tools in re.findall(
        r"`([a-z_]+)` (?:is required for|only for) ((?:`[a-z_]+`(?:,\s*|\s+and\s+)?)+)", text
    ):
        for name in re.findall(r"`([a-z_]+)`", tools):
            out.setdefault(name, []).append(key)
    return out


def keyed(rows: list[list[str]], col: int) -> dict[str, list[str]]:
    return {r[col].strip("`"): r for r in rows if len(r) > col and r[col].strip("`") != "—"}


def registry(env: Env) -> dict[str, list[str]]:
    """D02 §2.2 by `DrawingTool` value: id, name, tool, anchors, group, key, story, status."""
    return keyed(rows_of(section(env.at_base(PATHS["D02"]), "### 2.2 "), "id"), 2)


def schema(env: Env) -> tuple[list[str], dict[str, list[str]]]:
    """D04 §3: the header and the rows by `DrawingTool` value."""
    t = tables(section(env.at_base(PATHS["D04"]), "## 3. "))
    if not t:
        return [], {}
    return t[0][0][1], keyed([c for _, c in t[0][1:]], 1)


def templates(env: Env) -> dict[str, list[str]]:
    """D07 §2.2 by `DrawingTool` value: #, tool, template, example, anchors, extras."""
    return keyed(rows_of(section(env.at_base(PATHS["D07"]), "### 2.2 "), "#"), 1)


ANCHOR_RULE = {
    "1": "T01 → T15 → T37 / T38",
    "2": "T01 → T16 → T26",
    "3": "T01 → T16 → T25 → T26",
    "2..100": "T01 → T16 → T25… → T27",
}
PROPS = ("colour", "width", "style", "extend L / R", "fill", "font size", "label", "lock / visible")
TOOL_HEADER = ["`DrawingTool`", "anchors (`22`)", "rail group · key (D02 §2.2)",
               "creation (D02 §4.4) · keyboard (D02 §9)", "properties (D04 §3)",
               "persistence (`22` key rules)", "label template = accessible name (D07 §2.1)",
               "story · sprint", "R1 / deferred"]  # fmt: skip


def creation(n: str) -> str:
    if n in ("1", "2", "3"):
        return f"{ANCHOR_RULE[n]} · `Enter` ×{n} on the plot stop"
    if n == "2..100":
        return f"{ANCHOR_RULE[n]} · `Enter` per point, `Shift+Enter` closes"
    return "pointer-up commits (deferred; no keyboard path drawn)"


def derive_tools(env: Env) -> list[list[str]]:
    pc, gk, reg, (hdr, d04), d07 = (point_counts(env), geometry_keys(env), registry(env),
                                    schema(env), templates(env))  # fmt: skip
    sp = sprints(env)
    rows = [TOOL_HEADER]
    for tool in tool_enum(env):
        n = pc.get(tool, "?")
        r = reg.get(tool, [""] * 8)
        s = d04.get(tool, [])
        props = [
            p
            for p in PROPS
            if p in hdr
            and len(s) > hdr.index(p)
            and not s[hdr.index(p)].startswith(("—", "no popover", "n/a"))
        ]
        slot = s[hdr.index("slot")] if "slot" in hdr and len(s) > hdr.index("slot") else "—"
        if slot != "—":
            props.append(slot)
        geo = [f"`geometry.points` ×{n}"] + [f"`geometry.{k}`" for k in gk.get(tool, [])]
        tp = d07.get(tool, ["?", "", "?"])
        story = r[6]
        m = re.fullmatch(r"E14-S(\d\d)", story)
        sk = f"s{m[1]}" if m else ""
        story_cell = f"{story} · Sprint {sp[sk]:02d}" if sk in sp else story
        rows.append([
            f"`{tool}`", n, f"{r[4]} · {r[5]}", creation(n), " · ".join(props) or "—",
            " · ".join(geo) + " · `style` (as served)", f"#{tp[0]} {tp[2]}", story_cell, r[7],
        ])  # fmt: skip
    return rows


def glyph_rows(env: Env) -> tuple[list[list[str]], list[list[str]]]:
    d03 = section(env.at_base(PATHS["D03"]), "## 2. ")
    return rows_of(section(d03, "### 2.1 "), "id"), rows_of(section(d03, "### 2.2 "), "id")


def derive_glyphs(env: Env) -> list[list[str]]:
    live, deferred = glyph_rows(env)
    rows = [["id", "`IconName`", "group", "tooltip label = accessible name", "drawn on"]]
    for r in live:
        rows.append([r[0], r[1], r[2], r[3], "E14-D03 board 02 (`E14-D03-02-icon-set.png`)"])
    for r in deferred:
        rows.append([r[0], r[1], r[2], r[3], "text item, no glyph (D03 §2.2)"])
    return rows


def icon_names_15(env: Env) -> list[str]:
    """CMP-019's E14-D08 Usage line: the PROPOSED drawing `IconName`s (its definition line)."""
    ls = env.lines(env.base, PATHS["15"])
    a, b = span(ls, "### CMP-019 ")
    line = next((ln for ln in ls[a:b] if ln.startswith("- **Usage (E14-D08)**")), "")
    head = line.split("(`lock` reused)")[0]
    tail = head.split("1.5 px stroke", 1)[1] if "1.5 px stroke" in head else ""
    return [n for n in re.findall(r"`([a-z][a-z-]*)`", tail) if n != "IconName"]


def storybook(env: Env, cmp_id: str) -> list[str]:
    ls = env.lines(env.base, PATHS["15"])
    a, b = span(ls, f"### {cmp_id} ")
    line = next((ln for ln in ls[a:b] if ln.startswith("- **Storybook**")), "")
    body = line.split("):", 1)[1] if "):" in line else ""
    return [x.strip().rstrip(".") for x in body.split(",") if x.strip()]


def d02_events(env: Env) -> list[str]:
    rows = rows_of(
        section(env.at_base(PATHS["D02"]), "## 14. "), "Event (canonical name, memo §11)"
    )
    return [m[1] for r in rows for m in [EVENT.search(r[0])] if m]


def scr_events(env: Env) -> list[str]:
    out: list[str] = []
    for ln in env.lines(env.base, PATHS["14"]):
        if ln.startswith("- **Analytics/audit:**"):
            out += EVENT.findall(ln)
    return out


# ---------------------------------------------------------------------------- the deck


def derive_deck(env: Env) -> dict[str, object]:
    key = "deck:derived"
    if key in env.memo:
        v = env.memo[key]
        return v if isinstance(v, dict) else {}
    entries: dict[str, dict[str, object]] = {}
    for prefix, (src, head, owner) in DECKS.items():
        text = env.at_base(PATHS[src])
        a, _ = span(text.split("\n"), head)
        for t in tables(section(text, head)):
            hdr = t[0][1]
            if "String" not in hdr:
                continue
            s_col = hdr.index("String")
            src_col = hdr.index("Source") if "Source" in hdr else None
            for n, (idx, cells) in enumerate(t[1:], 1):
                kc = cells[0] if s_col != 0 else ""
                keys = re.findall(r"`([^`]+)`", kc) or ([kc] if kc else [])
                sc = cells[src_col] if src_col is not None and src_col < len(cells) else ""
                if src_col is None or sc.startswith("PROPOSED"):
                    status, own = "proposed", owner
                elif sc.startswith("RULED"):
                    status, own = "ruled", owner
                else:
                    status, own = "cited", sc
                entry: dict[str, object] = {
                    "names": " · ".join(keys),
                    "text": cells[s_col].replace("\\|", "|"),
                    "source": f"{src}:{a + idx + 1}",
                    "status": status,
                    "owner": own,
                }
                if status == "proposed":
                    entry["finalised_by"] = FINALISER
                if WORDS.search(str(entry["names"]) + str(entry["text"])):
                    wcol = hdr.index("Where") if "Where" in hdr else None
                    wc = cells[wcol] if wcol is not None and wcol < len(cells) else ""
                    sec = "§" + head.strip("# ").rstrip(". ")
                    entry["names"] = " · ".join(k for k in keys if not WORDS.search(k))
                    entry["text"] = None
                    entry["where"] = f"{src} {sec}" + (
                        f": {wc}" if wc and not WORDS.search(wc) else ""
                    )
                    entry["copy"] = CITED_ONLY
                entries[f"{prefix}:{n:02d}"] = entry
            break
    out: dict[str, object] = {
        "pack": "E14-D12",
        "version": "v1.1",
        "base": BASE,
        "note": (
            "The copy deck of the E14-D12 hand-off pack: every row of the five parents' copy "
            "tables (E14-D02 §12, E14-D04 §9.5, E14-D05 §9.4, E14-D06 §10, E14-D07 §12.2) under "
            "the id `<parent>:<row number>`, with the row's keys, the String cell verbatim, the "
            "source row, the status (proposed: the parent's own proposal, owner the parent, "
            "finalised by E14-D10 at v1.1; ruled; cited: the owner its Source cell names) and the "
            "owner; a row whose key or string carries a word of the public-text list keeps its "
            "source and owner and is cited only. Checked by "
            "docs/design/_tools/e14_d12_handoff_audit.py (G-DECK)."
        ),
        "entries": entries,
    }
    env.memo[key] = out
    return out


def deck_entries(env: Env) -> dict[str, dict[str, object]]:
    ent = derive_deck(env).get("entries", {})
    out: dict[str, dict[str, object]] = {}
    for k, v in ent.items() if isinstance(ent, dict) else []:
        if isinstance(v, dict):
            out[str(k)] = v
    return out


# ---------------------------------------------------------------------------- the pack's tables


def d10_values(env: Env) -> dict[str, str]:
    """E14-D10's counts, read from its own tables and headings at the base."""
    d10 = env.at_base(PATHS["D10"])
    vals: dict[str, str] = {}
    f = rows_of(section(d10, "## 14. "), "Id")
    vals["COUNT:d10.f"] = str(len(f))
    for s in SEVERITIES:
        vals[f"COUNT:d10.f.{s.lower()}"] = str(sum(r[1] == s for r in f if len(r) > 1))
    vals["COUNT:d10.fm"] = str(len(rows_of(section(d10, "## 4. "), "Id")))
    vals["COUNT:d10.vc"] = str(len(rows_of(section(d10, "### 7.1 "), "Id")))
    vals["COUNT:d10.ts"] = str(len(rows_of(section(d10, "## 11. "), "Id")))
    vals["COUNT:d10.t2"] = str(len(rows_of(section(d10, "### 12.1 "), "Id")))
    vals["COUNT:d10.c"] = str(len(rows_of(section(d10, "### 15.1 "), "Id")))
    vals["COUNT:d10.g"] = str(len(rows_of(section(d10, "### 15.2 "), "Id")))
    vals["COUNT:d10.scenarios"] = str(
        len(re.findall(r"^### 6\.\d+ Scenario \d+ ", section(d10, "## 6. "), re.MULTILINE))
    )
    vals["COUNT:d10.q07"] = str(len(set(re.findall(r"\bQ07-\d+\b", section(d10, "## 6. ")))))
    return vals


def register(spec: str) -> list[list[str]]:
    return rows_of(section(spec, "## 12. "), "Id")


def budget_rows(spec: str) -> list[list[str]]:
    return rows_of(section(spec, "### 9.2 "), "Budget")


def t2_rows(spec: str) -> list[list[str]]:
    return rows_of(section(spec, "### 6.2 "), "Control")


def index_rows(spec: str) -> list[list[str]]:
    return rows_of(section(spec, "## 2. "), "Story")


def tick_rows(spec: str) -> list[list[str]]:
    return rows_of(section(spec, "### 15.1 "), "Item")


def version_rows(spec: str) -> list[list[str]]:
    return rows_of(section(spec, "## 14. "), "Version")


def walk_items(spec: str) -> int:
    return sum(1 for ln in section(spec, "### 13.1 ").split("\n") if re.match(r"^\d+\. ", ln))


def compute(t: Texts) -> dict[str, str]:
    env = t.env
    vals: dict[str, str] = {"SHA:base": env.base[:10]}
    vals.update(status_values(env))
    vals.update(cite_values(env))
    vals.update(ahead_values(env))
    for k in LIFTS:
        h = lift_hash(t, k)
        if h:
            vals[f"HASH:{k}"] = h
    enum = tool_enum(env)
    reg = registry(env)
    vals["COUNT:tools.rows"] = str(len(enum))
    vals["COUNT:tools.live"] = str(sum(reg.get(x, [""] * 8)[7].startswith("R1") for x in enum))
    vals["COUNT:tools.deferred"] = str(
        sum(reg.get(x, [""] * 8)[7].startswith("deferred") for x in enum)
    )
    vals["COUNT:reg.rows"] = str(len(rows_of(section(env.at_base(PATHS["D02"]), "### 2.2 "), "id")))
    live, deferred = glyph_rows(env)
    n15 = icon_names_15(env)
    vals["COUNT:glyphs.d03"] = str(len(live))
    vals["COUNT:glyphs.deferred"] = str(len(deferred))
    vals["COUNT:glyphs.15"] = str(len(n15))
    diff = sorted({r[1].strip("`") for r in live} - set(n15))
    vals["NAMES:glyphs.diff"] = "`" + "`, `".join(diff) + "`" if diff else "none"
    d02 = env.at_base(PATHS["D02"])
    vals["COUNT:d02.transitions"] = str(len(rows_of(section(d02, "### 4.3 "), "id")))
    vals["COUNT:d02.collisions"] = str(len(tables(section(d02, "## 10. "))[0][1:]))
    vals["COUNT:events"] = str(len(d02_events(env)))
    for cmp_id, k in (("CMP-191", "cmp191"), ("CMP-223", "cmp223")):
        vals[f"COUNT:stories.{k}"] = str(len(storybook(env, cmp_id)))
    vals["COUNT:pngs"] = str(sum(1 for p in env.tree(env.base, IMG_REL) if p.endswith(".png")))
    entries = deck_entries(env)
    vals["COUNT:deck.total"] = str(len(entries))
    vals["COUNT:deck.cited_only"] = str(sum("copy" in e for e in entries.values()))
    for s in ("proposed", "cited", "ruled"):
        vals[f"COUNT:deck.{s}"] = str(sum(e.get("status") == s for e in entries.values()))
    for p in DECKS:
        vals[f"COUNT:deck.{p}"] = str(sum(k.startswith(p + ":") for k in entries))
    reg_rows = register(t.spec)
    sev = [r[2] for r in reg_rows if len(r) > 2]
    vals["COUNT:rows.total"] = str(len(reg_rows))
    for s in SEVERITIES:
        vals[f"COUNT:rows.{s.lower()}"] = str(sev.count(s))
    for kind in ("C", "G", "D"):
        vals[f"COUNT:rows.{kind.lower()}"] = str(sum(r[0].startswith(kind + "-") for r in reg_rows))
    vals["COUNT:walk.items"] = str(walk_items(t.spec))
    vals["COUNT:ticks"] = str(len(t.ticks))
    if vals.get("STATUS:d10") == "present":
        vals.update(d10_values(env))
    vals["COUNT:index.text_only"] = str(sum("text only" in " ".join(r) for r in index_rows(t.spec)))
    return vals


# ---------------------------------------------------------------------------- placeholders


def fill(text: str, values: dict[str, str], copies: dict[str, str]) -> tuple[str, list[str]]:
    missing: list[str] = []
    out: list[str] = []
    for ln in collapse_copies(text).split("\n"):
        m = COPY_LINE.match(ln)
        if m:
            if m[1] in copies:
                out.append(f"<!-- COPY:{m[1]} -->\n\n{copies[m[1]]}\n\n<!-- /COPY:{m[1]} -->")
            else:
                missing.append(f"COPY:{m[1]}")
                out.append(ln)
            continue

        def refresh(mm: re.Match[str]) -> str:
            return f"{values[mm[2]]}<!--={mm[2]}-->" if mm[2] in values else mm[0]

        ln = ANCHORED.sub(refresh, ln)
        spans = [(c.start(), c.end()) for c in CODE.finditer(ln)]

        def ph(mm: re.Match[str], spans: list[tuple[int, int]] = spans) -> str:
            if any(a <= mm.start() < b for a, b in spans):
                return mm[0]
            if mm[1] not in values:
                missing.append(mm[1])
                return mm[0]
            return f"{values[mm[1]]}<!--={mm[1]}-->"

        out.append(PLACEHOLDER.sub(ph, ln))
    return "\n".join(out), missing


def copy_sources(env: Env) -> dict[str, str]:
    out: dict[str, str] = {}
    for k, (src, head) in COPIES.items():
        body = body_of(env.at_base(PATHS[src]), head)
        if body is not None:
            out[k] = body
    out["tools"] = pad_table(derive_tools(env))
    out["glyphs"] = pad_table(derive_glyphs(env))
    return out


def checklist(base_line: str, ticks: dict[int, str]) -> str:
    """SCR-037's checklist with the ruled items ticked and their evidence appended."""
    body = base_line.removeprefix(CHECKLIST_PREFIX)
    items = [x.strip() for x in body.split("[ ]") if x.strip()]
    out = []
    for i, item in enumerate(items, 1):
        out.append(f"[x] {item} ({ticks[i]})" if i in ticks else f"[ ] {item}")
    return CHECKLIST_PREFIX + " ".join(out)


def apply14(base14: str, ticks: dict[int, str]) -> tuple[str, list[str]]:
    """The merge-base's `14` with the three pointer lines and SCR-037's ticks applied."""
    ls = base14.split("\n")
    bad: list[str] = []
    for scr, (anchor, tail) in SCREENS.items():
        a = next((i for i, ln in enumerate(ls) if ln.startswith(f"### {scr} ")), -1)
        if a < 0:
            bad.append(f"`14` has no {scr} entry")
            continue
        b = next((i for i in range(a + 1, len(ls)) if ls[i].startswith("### ")), len(ls))
        an = [i for i in range(a, b) if ls[i].startswith(anchor)]
        ck = [i for i in range(a, b) if ls[i].startswith(CHECKLIST_PREFIX)]
        if len(an) != 1 or len(ck) != 1:
            bad.append(f"{scr}: the pointer's anchor or the checklist is not found once in `14`")
            continue
        if scr == "SCR-037":
            if "[x]" in ls[ck[0]]:
                bad.append("SCR-037's checklist already carries a tick at the merge-base")
            ls[ck[0]] = checklist(ls[ck[0]], ticks)
        ls.insert(an[0] + 1, POINTER.format(tail=tail))
    return "\n".join(ls), bad


# ---------------------------------------------------------------------------- pins

Unit = tuple[str, str, str]


def units(text: str, doc: str) -> list[Unit]:
    out: list[Unit] = []
    path: list[tuple[int, str]] = []
    seen: dict[str, int] = {}
    region, k, shape = f"{doc}:(top)#1", 0, ""
    rows: dict[str, int] = {}
    for raw in unfill(text).split("\n"):
        m = HEADING.match(raw)
        if m:
            out.append((region, "shape", shape))
            level = len(m[1])
            path = [p for p in path if p[0] < level] + [(level, pin_norm(m[2]))]
            key = f"{doc}:" + " > ".join(p[1] for p in path)
            seen[key] = seen.get(key, 0) + 1
            region, k, shape, rows = f"{key}#{seen[key]}", 0, "h", {}
            out.append((region, "heading", pin_norm(raw)))
            continue
        if not raw.strip():
            shape += "."
        elif RULE.match(raw):
            shape += "r"
        elif raw.lstrip().startswith("|"):
            shape += "t"
            cells = split_row(raw)
            lead = pin_norm(cells[0]) or "(blank)"
            rows[lead] = rows.get(lead, 0) + 1
            loc = f"row {lead}" + (f"#{rows[lead]}" if rows[lead] > 1 else "")
            out.append((region, loc, " | ".join(pin_norm(c) for c in cells)))
        else:
            sents = [x for x in FULL_STOP.split(raw.strip()) if x.strip()]
            shape += f"p{len(sents)}"
            for x in sents:
                k += 1
                out.append((region, f"s{k}", pin_norm(x)))
    out.append((region, "shape", shape))
    return out


def deck_units(deck: str) -> list[Unit]:
    try:
        data = json.loads(deck)
    except json.JSONDecodeError:
        return [("deck", "json", "unparseable")]
    out: list[Unit] = []
    if isinstance(data, dict):
        for k, v in data.items():
            if k != "entries":
                out.append(("deck", k, pin_norm(json.dumps(v, ensure_ascii=False, sort_keys=True))))
        ent = data.get("entries", {})
        for k, v in ent.items() if isinstance(ent, dict) else []:
            out.append(
                ("deck:entries", k, pin_norm(json.dumps(v, ensure_ascii=False, sort_keys=True)))
            )
    return out


def cite_units(t: Texts) -> list[Unit]:
    out: dict[str, str] = {}
    for _, key, a, b, _ in all_cites(t):
        ls = t.env.lines(t.env.base, PATHS[key])
        if 0 < a <= b <= len(ls):
            lab = f"{key}:{a}" if a == b else f"{key}:{a}-{b}"
            out[lab] = sha12(pin_norm(ls[a - 1]) + "\n" + pin_norm(ls[b - 1]))
    return [("cite", k, v) for k, v in sorted(out.items())]


def all_units(t: Texts) -> list[Unit]:
    return units(t.spec, "spec") + deck_units(t.deck) + cite_units(t)


def write_pins(us: list[Unit]) -> str:
    head = (
        f"# E14-D12 pins: {len(us)} units (region, location, the normalised text; values cut out, "
        "blocks collapsed), the deck entries and the cites' line hashes at the base.\n"
        "# Written by `--repin-ruled` only; `--check` reads it (G-RULED-PIN). Never hand-edit.\n"
    )
    return head + "".join("\t".join(u) + "\n" for u in us)


def parse_pins(text: str) -> list[Unit]:
    out: list[Unit] = []
    for ln in text.split("\n"):
        parts = ln.split("\t")
        if ln and not ln.startswith("#") and len(parts) == 3:
            out.append((parts[0], parts[1], parts[2]))
    return out


def pin_problems(pinned: list[Unit], current: list[Unit]) -> list[str]:
    bad: list[str] = []
    was = {(u[0], u[1]): u[2] for u in pinned}
    now = {(u[0], u[1]): u[2] for u in current}
    for k, v in now.items():
        if k not in was:
            bad.append(f"unpinned unit {k[0][-50:]} / {k[1]}: {v[:40]!r}")
        elif was[k] != v:
            bad.append(f"changed unit {k[0][-50:]} / {k[1]}: {v[:40]!r}")
    for k in was:
        if k not in now:
            bad.append(f"deleted unit {k[0][-50:]} / {k[1]}")
    if not bad and [u[:2] for u in pinned] != [u[:2] for u in current]:
        bad.append("the pinned units moved (the order changed)")
    return bad


# ---------------------------------------------------------------------------- findings


@dataclass(frozen=True)
class Finding:
    level: str
    gate: str
    msg: str


def one(gate: str, problems: list[str], level: str = "FAIL") -> list[Finding]:
    return [Finding(level, gate, p) for p in problems]


ANCHOR_GATE = (
    ("HASH:", "G-LIFT"),
    ("COUNT:deck", "G-DECK"),
    ("COUNT:rows", "G-ROWS"),
    ("COUNT:glyphs", "G-GLYPHS"), ("NAMES:glyphs", "G-GLYPHS"),
    ("COUNT:tools", "G-TOOLS"), ("COUNT:reg", "G-TOOLS"),
    ("COUNT:events", "G-EVENTS"),
    ("COUNT:ticks", "G-TICKS"),
    ("COUNT:index", "G-INDEX"),
    ("STATUS:d10", "G-PENDING"), ("COUNT:d10", "G-PENDING"),
    ("SPRINT:", "G-AHEAD"), ("DATE:", "G-AHEAD"), ("DAYS:", "G-AHEAD"),
)  # fmt: skip


def anchor_gate(key: str) -> str:
    for prefix, gate in ANCHOR_GATE:
        if key.startswith(prefix):
            return gate
    return "G-VALUES"


def anchor_problems(t: Texts, gate: str) -> list[str]:
    bad: list[str] = []
    for doc, text in both(t):
        for value, key, ln in anchored(text):
            if anchor_gate(key) != gate:
                continue
            want = t.values.get(key)
            if want is None:
                bad.append(f"{doc}:{ln} anchors `{key}`, which the tool does not compute")
            elif want != value:
                bad.append(f"{doc}:{ln} `{key}` reads {value}; the tool derives {want}")
    return bad


def has_section(text: str, n: str) -> bool:
    return bool(re.search(rf"^#{{2,4}} (?:§)?{re.escape(n)}[. ]", text, re.MULTILINE))


def has_png(t: Texts, ticket: str, board: str) -> bool:
    return any(
        p.rsplit("/", 1)[-1].startswith(f"{ticket}-{board}-") and p.endswith(".png")
        for p in t.env.tree(t.env.base, IMG_REL)
    )


def evidence_problems(t: Texts, label: str, cell: str) -> list[str]:
    """Every part of an evidence cell: a parent, its `§n` headings and its boards' PNGs."""
    bad: list[str] = []
    for part in [p.strip() for p in cell.split(";") if p.strip()]:
        if "text only" in part:
            continue
        m = re.match(r"(E14-D0\d)\b(.*)$", part)
        if not m or m[1] not in DOCS:
            bad.append(f"{label}: {part[:30]!r} names no E14 parent")
            continue
        text = doc_text(t, DOCS[m[1]])
        for n in re.findall(r"§(\d+(?:\.\d+)?)", m[2]):
            if not has_section(text, n):
                bad.append(f"{label}: {m[1]} has no §{n}")
        bm = re.search(r"\bboards? (\d\d(?:,\s*\d\d)*)", m[2])
        for b in re.findall(r"\d\d", bm[1]) if bm else []:
            if not has_png(t, m[1], b):
                bad.append(f"{label}: {m[1]} board {b} has no PNG at the base")
    return bad


def g_values(t: Texts) -> list[Finding]:
    bad = anchor_problems(t, "G-VALUES")
    for key in CITES:
        if f"CITE:{key}" not in t.values:
            bad.append(f"CITE:{key}: its defining line is not found once at the base")
    return one("G-VALUES", bad)


def g_lift(t: Texts) -> list[Finding]:
    bad = anchor_problems(t, "G-LIFT")
    for k in LIFTS:
        if f"HASH:{k}" not in t.values:
            bad.append(f"HASH:{k}: a lifted span is missing")
    return one("G-LIFT", bad)


def g_copy(t: Texts) -> list[Finding]:
    bad: list[str] = []
    want = copy_sources(t.env)
    keys = [m[1] for m in COPY_BLOCK.finditer(t.spec)]
    for key in keys:
        if key in DERIVED:
            continue
        body = block_body(t.spec, key)
        if key not in want:
            bad.append(f"COPY:{key} has no source")
        elif body != want[key]:
            bad.append(f"COPY:{key} differs from its source at the base")
    for k in (*COPIES, *DERIVED):
        if keys.count(k) != 1:
            bad.append(f"COPY:{k} appears {keys.count(k)} times (once expected)")
    return one("G-COPY", bad)


def g_cite(t: Texts) -> list[Finding]:
    bad: list[str] = []
    if not git_ok("merge-base", "--is-ancestor", t.env.base, "HEAD"):
        bad.append(f"the base {BASE} is not an ancestor of HEAD")
    for doc, key, a, b, n in all_cites(t):
        ls = t.env.lines(t.env.base, PATHS[key])
        if not (0 < a <= b <= len(ls)):
            bad.append(f"{doc}:{n} `{key}`:{a}-{b} is out of range ({len(ls)} lines)")
        elif not ls[a - 1].strip() or not ls[b - 1].strip():
            bad.append(f"{doc}:{n} `{key}`:{a}-{b} ends on a blank line")
    return one("G-CITE", bad)


def g_version(t: Texts) -> list[Finding]:
    out: list[Finding] = []
    seen: set[tuple[str, int]] = set()
    for doc, key, a, b, n in all_cites(t):
        base = t.env.lines(t.env.base, PATHS[key])
        head = t.env.lines(HEAD_REF, PATHS[key])
        for k in sorted({a, b}):
            if (key, k) in seen or not (0 < k <= len(base)):
                continue
            seen.add((key, k))
            line = base[k - 1]
            if k <= len(head) and head[k - 1] == line:
                continue
            if line in head:
                out.append(Finding("WARN", "G-VERSION", f"`{key}`:{k} moved at {HEAD_REF}"))
            else:
                out.append(
                    Finding("FAIL", "G-VERSION", f"{doc}:{n} `{key}`:{k} is gone at {HEAD_REF}")
                )
    return out


def cells_equal(block: str | None, want: list[list[str]]) -> list[str]:
    if block is None:
        return ["the block is missing"]
    got = [[pin_norm(c) for c in r] for r in table_cells(block)]
    exp = [[pin_norm(c) for c in r] for r in want]
    if len(got) != len(exp):
        return [f"{len(got) - 1} rows; the derivation has {len(exp) - 1}"]
    return [
        f"row {i}: {' | '.join(g)[:60]!r} differs"
        for i, (g, e) in enumerate(zip(got, exp))
        if g != e
    ]


def g_tools(t: Texts) -> list[Finding]:
    env = t.env
    bad = anchor_problems(t, "G-TOOLS")
    bad += [
        f"the tools table: {p}" for p in cells_equal(block_body(t.spec, "tools"), derive_tools(env))
    ]
    pc, reg, (_, d04), d07 = point_counts(env), registry(env), schema(env), templates(env)
    enum = tool_enum(env)
    if len(enum) != len(pc):
        bad.append(f"`22` lists {len(enum)} values and {len(pc)} point counts")
    for tool in enum:
        n = pc.get(tool)
        if n is None:
            bad.append(f"`{tool}`: no point count in `22`")
            continue
        if reg.get(tool, ["", "", "", ""])[3] != n:
            bad.append(f"`{tool}`: D02 §2.2 reads {reg.get(tool, ['', '', '', '?'])[3]}, `22` {n}")
        x = re.search(r"× (\S+)", d04.get(tool, ["", "", ""])[2])
        if not x or x[1] != n:
            bad.append(f"`{tool}`: D04 §3's anchors disagree with `22` ({n})")
        want7 = "n" if ".." in n else n
        if d07.get(tool, ["", "", "", "", "?"])[4] != want7:
            bad.append(f"`{tool}`: D07 §2.2's anchors disagree with `22` ({n})")
    rule = section(env.at_base(PATHS["D02"]), "### 4.4 ")
    for n, seq in ANCHOR_RULE.items():
        if seq not in rule:
            bad.append(f"D02 §4.4 does not state {seq} ({n} anchors)")
    return one("G-TOOLS", bad)


def g_glyphs(t: Texts) -> list[Finding]:
    bad = anchor_problems(t, "G-GLYPHS")
    bad += [
        f"the glyph register: {p}"
        for p in cells_equal(block_body(t.spec, "glyphs"), derive_glyphs(t.env))
    ]
    live, _ = glyph_rows(t.env)
    extra = {r[1].strip("`") for r in live} - set(icon_names_15(t.env))
    if extra - {"lock"}:
        bad.append(f"D03 §2.1 names {sorted(extra)} that `15`'s CMP-019 line does not")
    return one("G-GLYPHS", bad)


def g_index(t: Texts) -> list[Finding]:
    bad = anchor_problems(t, "G-INDEX")
    seen: list[str] = []
    for r in index_rows(t.spec):
        m = re.match(r"(E14-S\d\d) \(#\d+\)$", r[0])
        if not m or len(r) < 7:
            bad.append(f"index row {r[0][:20]!r}: not `E14-Snn (#n)` with seven cells")
            continue
        sid = m[1]
        seen.append(sid)
        if r[1] != STORIES.get(sid, "?"):
            bad.append(f"{sid}: the story cell reads {r[1]!r}, not {STORIES.get(sid)}")
        if "board" not in r[3] and "text only" not in r[3]:
            bad.append(f"{sid}: no frame and no 'text only' mark")
        bad += evidence_problems(t, f"{sid} frames", r[3])
        bad += evidence_problems(t, f"{sid} spec", r[4])
        if not re.search(r"CMP-(?:191|223)", r[5]):
            bad.append(f"{sid}: no component contract")
        if "figma" in " ".join(r).lower():
            bad.append(f"{sid}: maps to the Figma file")
    for sid in STORIES:
        if seen.count(sid) != 1:
            bad.append(f"{sid} appears {seen.count(sid)} times in the index")
    return one("G-INDEX", bad)


def g_deck(t: Texts) -> list[Finding]:
    bad = anchor_problems(t, "G-DECK")
    try:
        data = json.loads(t.deck)
    except json.JSONDecodeError as e:
        return one("G-DECK", [f"the deck is not JSON: {e}"])
    want = derive_deck(t.env)
    ent = data.get("entries", {}) if isinstance(data, dict) else {}
    wnt = deck_entries(t.env)
    for k, v in ent.items() if isinstance(ent, dict) else []:
        if isinstance(v, dict) and v.get("status") == "proposed" and not v.get("owner"):
            bad.append(f"deck {k}: a proposed entry with no owner")
        if k not in wnt:
            bad.append(f"deck {k}: no such row in the parents' tables")
        elif v != wnt[k]:
            bad.append(f"deck {k}: differs from its source row ({wnt[k].get('source')})")
    for k in wnt:
        if not isinstance(ent, dict) or k not in ent:
            bad.append(f"deck {k}: missing")
    if isinstance(data, dict):
        for k in ("pack", "version", "base", "note"):
            if data.get(k) != want.get(k):
                bad.append(f"deck field `{k}` differs from the derivation")
    return one("G-DECK", bad)


def owner_problems(rid: str, cell: str) -> list[str]:
    parts = [p.strip() for p in cell.split(";")]
    if len(parts) != 2:
        return [f"{rid}: the owner cell is not '<spec>; <area>'"]
    specs = re.split(r",\s*(?=E\d|C|`|E05)", parts[0])
    bad = [f"{rid}: owner {s.strip()!r} is not a spec" for s in specs
           if not OWNER_SPEC.fullmatch(s.strip())]  # fmt: skip
    if parts[1] not in AREAS:
        bad.append(f"{rid}: area {parts[1]!r} is not a ruled area")
    return bad


def first_consumer(t: Texts) -> int:
    sp = sprints(t.env)
    return min((sp[k] for k in MARGINS if k in sp), default=0)


def g_rows(t: Texts) -> list[Finding]:
    bad = anchor_problems(t, "G-ROWS")
    ids: list[str] = []
    raw = {
        split_row(ln)[0]: ln for ln in section(t.spec, "## 12. ").split("\n") if ln.startswith("| ")
    }
    for r in register(t.spec):
        rid = r[0]
        ids.append(rid)
        if not re.fullmatch(r"[CGD]-\d+", rid) or len(r) < 7:
            bad.append(f"{rid}: not a C-, G- or D- id with seven cells")
            continue
        if r[2] not in SEVERITIES:
            bad.append(f"{rid}: grade {r[2]!r} is not one of the four")
        bad += owner_problems(rid, r[4])
        due = DUE.match(r[5])
        if not due:
            bad.append(f"{rid}: due {r[5]!r} is not a ruled form")
        elif due[1] and int(due[1]) < first_consumer(t):
            bad.append(f"{rid}: due Sprint {due[1]} is before the first consumer's sprint")
        if not cites_in(raw.get(rid, "")):
            bad.append(f"{rid}: no cite")
    if len(set(ids)) != len(ids):
        bad.append("a register id repeats")
    rows = {r[0]: r for r in register(t.spec)}
    for rid, needle in REQUIRED_ROWS.items():
        if rid not in rows or needle not in rows[rid][3].lower():
            bad.append(f"{rid} (the ruled contradiction on '{needle}') is missing")
    if not any(
        "#5229" in r[3] and "E14-D10" in r[3] for r in rows.values() if r[0].startswith("G-")
    ):
        bad.append("no G-row carries E14-D10's chapter (#5229)")
    return one("G-ROWS", bad)


def g_t2(t: Texts) -> list[Finding]:
    bad: list[str] = []
    sec = " ".join(section(t.spec, "### 6.2 ").split())
    for term in T2_TERMS:
        if term not in sec:
            bad.append(f"§6.2 does not state {term}")
    rows = t2_rows(t.spec)
    if not rows:
        bad.append("§6.2 has no T2 table")
    for r in rows:
        if len(r) < 7:
            bad.append(f"T2 row {r[0][:20]!r}: seven cells expected")
            continue
        if not r[2].startswith(("2a", "2b", "sentence")):
            bad.append(f"T2 row {r[0][:20]!r}: rendering {r[2]!r} is not 2a, 2b or sentence")
        keys = [k for k in re.findall(r"`([a-z_.]+)`", r[3]) if k in T2_KEYS]
        if not keys:
            bad.append(f"T2 row {r[0][:20]!r}: no ruled §3.1 key")
        legs = {LEG_VERB[x] for x in re.findall(r"`([a-z]+:write)`", r[1]) if x in LEG_VERB}
        verbs = {v for v in LEG_VERB.values() if v in r[4]}
        if "rbac.permission" in keys and (not legs or verbs != legs):
            bad.append(f"T2 row {r[0][:20]!r}: the §3.2 verb is not its leg's ({sorted(legs)})")
        if "rbac.permission" not in keys and verbs:
            bad.append(f"T2 row {r[0][:20]!r}: a verb with no permission leg")
        if any(k in STATE_KEYS for k in keys) and "PROPOSED" in r[3] and "owner" not in r[3]:
            bad.append(f"T2 row {r[0][:20]!r}: a PROPOSED key with no owner")
        if "CMP-019 `lock`" not in r[5]:
            bad.append(f"T2 row {r[0][:20]!r}: no CMP-019 `lock`")
        role = any(k.startswith("rbac.") for k in keys)
        if role != ("CMP-079 RbacGate" in r[5]):
            bad.append(f"T2 row {r[0][:20]!r}: CMP-079 RbacGate must wrap role legs only")
        if not cites_in(r[6]):
            bad.append(f"T2 row {r[0][:20]!r}: no source cite")
    for prefix, key, line, needle in T2_EXPECTED:
        ls = t.env.lines(t.env.base, PATHS[key])
        if not (0 < line <= len(ls)) or needle not in ls[line - 1]:
            bad.append(f"`{key}`:{line} no longer names {needle[:30]!r}: re-derive the T2 rows")
        if not any(r[0].startswith(prefix) for r in rows):
            bad.append(f"the gated control {prefix!r} (`{key}`:{line}) has no T2 row")
    comp = next(
        (ln for ln in section(t.spec, "### 6.1 ").split("\n") if ln.startswith("| companions ")), ""
    )
    for cmp_id in ("CMP-079 RbacGate", "CMP-019 `lock`"):
        if cmp_id not in comp:
            bad.append(f"§6.1's companions row does not name {cmp_id}")
    return one("G-T2", bad)


def g_mnr(t: Texts) -> list[Finding]:
    bad: list[str] = []
    for ln in section(t.spec, "### 9.2 ").split("\n"):
        if not ln.startswith("| ") or RULE.match(ln) or ln.startswith("| Budget"):
            continue
        c = split_row(ln)
        if len(c) < 4 or "<!--=CITE:" not in c[1] or not c[2].strip() or not cites_in(ln):
            bad.append(f"budget {c[0][:30]!r}: no CITE value, owner or cite")
        if "CITE:scr037.fps" in ln and ("C-14.2" not in c[2] or "`26`:" not in ln):
            bad.append("the 58-fps row does not name C-14.2 as its owner and cite `26`")
    s92 = section(t.spec, "### 9.2 ")
    for key in BUDGET_KEYS:
        if f"<!--=CITE:{key}-->" not in s92:
            bad.append(f"§9.2 has no budget row carrying CITE:{key}")
    for n, ln in enumerate(t.spec.split("\n"), 1):
        if "hard-disabled" in re.sub(r"\"[^\"]*\"", "", ln):
            bad.append(f"spec:{n}: 'hard-disabled' outside a quote of the ticket")
    s91 = collapse_copies(section(t.spec, "### 9.1 "))
    if "{{COPY:d06.s64}}" not in s91:
        bad.append("§9.1 does not carry D06 §6.4's sentence as a byte copy")
    if "`/trade-groups/preview`" not in s91 or "`D06`:316" not in s91:
        bad.append("§9.1 does not read the ticket's preview re-run on open (D06 §6.5)")
    mnr2 = next((ln for ln in s91.split("\n") if ln.startswith("| MNR-2 ")), "")
    if '`aria-disabled="true"`' not in mnr2 or "T2" not in mnr2:
        bad.append('MNR-2 does not read the over-cap send as T2 `aria-disabled="true"`')
    return one("G-MNR", bad)


def g_events(t: Texts) -> list[Finding]:
    bad = anchor_problems(t, "G-EVENTS")
    known = set(d02_events(t.env)) | set(scr_events(t.env))
    for name in sorted(set(EVENT.findall(collapse_copies(t.spec))) - set(T2_KEYS)):
        if name not in known:
            bad.append(f"`{name}` is neither a D02 §14 name nor a `14` analytics name")
    return one("G-EVENTS", bad)


def g_pending(t: Texts) -> list[Finding]:
    """Before E14-D10 merges: it is absent, never cited and §8 says the chapter is pending.
    Once it is on the base (v1.1): every D10 block is lifted by hash in §8, the pending sentence is
    gone and a v1.1 version row stands."""
    bad = anchor_problems(t, "G-PENDING")
    s8 = " ".join(section(t.spec, "## 8. ").split())
    folded = any(r[0].startswith("v1.1") for r in version_rows(t.spec))
    if t.values.get("STATUS:d10") == "present":
        for k in LIFTS:
            if k.startswith("d10.") and f"<!--=HASH:{k}-->" not in s8:
                bad.append(f"§8 does not lift E14-D10's block {k} by hash")
        if PENDING in s8:
            bad.append("§8 still says the chapter is pending, but E14-D10 is on the base")
        if not folded:
            bad.append("E14-D10 is on the base and no v1.1 version row stands")
        return one("G-PENDING", bad)
    if "E14-D10.md" in t.spec:
        bad.append("the pack names E14-D10's file, which is not merged")
    if PENDING not in s8:
        bad.append(f'§8 does not say "{PENDING}"')
    out = one("G-PENDING", bad)
    if t.env.show(HEAD_REF, D10_REL) is not None and not folded:
        out.append(Finding("WARN", "G-PENDING", f"E14-D10 is on {HEAD_REF}: v1.1 is due"))
    return out


def g_ahead(t: Texts) -> list[Finding]:
    bad = anchor_problems(t, "G-AHEAD")
    for k in MARGINS:
        if f"DAYS:margin.{k}" not in t.values:
            bad.append(f"no sprint for {k} in the backlog JSON")
    if "promises nothing" not in section(t.spec, "## 11. "):
        bad.append("§11 does not say it reports and promises nothing")
    return one("G-AHEAD", bad)


def post_merge(t: Texts) -> bool:
    return t.env.show(t.env.mb, SPEC_REL) is not None


def g_untouched(t: Texts) -> list[Finding]:
    bad: list[str] = []
    if t.changed is None:
        return one("G-UNTOUCHED", ["git did not list the changed paths"])
    for p in t.changed:
        if p not in OWN_PATHS:
            bad.append(f"{p} differs from the merge-base (not this pack's)")
    base14 = t.env.show(t.env.mb, PLAN14_REL) or ""
    if post_merge(t):
        if t.plan14 != base14:
            bad.append("`14` changed after the pack merged")
    else:
        want, problems = apply14(base14, t.ticks)
        bad += problems
        if t.plan14 != want:
            bad.append("`14` differs from the merge-base with the pointer lines and ticks applied")
    return one("G-UNTOUCHED", bad)


def g_ticks(t: Texts) -> list[Finding]:
    bad = anchor_problems(t, "G-TICKS")
    for i, ev in sorted(t.ticks.items()):
        bad += evidence_problems(t, f"SCR-037 item {i}", ev)
    rows = tick_rows(t.spec)
    if len(rows) != 6:
        bad.append(f"§15.1 holds {len(rows)} SCR-037 items, six expected")
    for r in rows:
        if len(r) < 4 or not r[0].isdigit():
            bad.append(f"§15.1 row {r[0][:10]!r}: malformed")
            continue
        i = int(r[0])
        if r[2] == "[x]" and (i not in t.ticks or r[3] != t.ticks[i]):
            bad.append(f"§15.1 item {i}: ticked here, not with the same evidence in `14`")
        if r[2] == "[ ]" and (i in t.ticks or not r[3].strip()):
            bad.append(f"§15.1 item {i}: unticked here but ticked in `14`, or no reason")
    return one("G-TICKS", bad)


def g_frozen(t: Texts) -> list[Finding]:
    if not post_merge(t):
        return []
    merged = t.env.show(t.env.mb, SPEC_REL) or ""
    old = [" | ".join(r) for r in version_rows(unfill(merged))]
    now = [" | ".join(r) for r in version_rows(unfill(t.spec))]
    bad = [f"a merged version row changed or went: {r[:50]!r}" for r in old if r not in now]
    last = max((int(m[1]) for r in old for m in [re.match(r"v1\.(\d+)", r)] if m), default=0)
    for r in now:
        if r not in old:
            m = re.match(r"v1\.(\d+) ", r)
            if not m or int(m[1]) <= last:
                bad.append(f"a new version row is not v1.N above v1.{last}: {r[:40]!r}")
    return one("G-FROZEN", bad)


def g_ruled(t: Texts) -> list[Finding]:
    bad: list[str] = []
    heads = [ln for ln in t.spec.split("\n") if ln.startswith("## ") and "The questions" in ln]
    if len(heads) != 1 or STAMP not in heads[0]:
        bad.append("the questions heading does not carry the ruling stamp")
    if RULING_ID not in t.spec:
        bad.append(f"the ruling id {RULING_ID} is not named")
    if "<!-- BQ-" in t.spec:
        bad.append("a BQ marker is left")
    if OWNER_PENDING not in t.spec.lower():
        bad.append(f'"{OWNER_PENDING}" is not stated')
    for n in range(1, BQ_TOTAL + 1):
        if f"BQ-{n:02d}" not in t.spec:
            bad.append(f"BQ-{n:02d} is not named")
    return one("G-RULED", bad)


def g_hygiene(t: Texts) -> list[Finding]:
    bad: list[str] = []
    for doc, text in (*both(t), ("deck", t.deck)):
        for k in unfilled(text) if doc != "deck" else []:
            bad.append(f"{doc}: `{{{{{k}}}}}` is unfilled")
        plain = collapse_copies(text)
        for m in re.finditer(r"<!--(.*?)-->", plain, re.DOTALL):
            if not re.fullmatch(r"=[A-Z]+:[^>]+", m[1]):
                bad.append(f"{doc}: a stray HTML comment {m[0][:40]!r}")
        for ln in plain.split("\n"):
            if CLOSING.search(without_code(ln)):
                bad.append(f"{doc}: a closing keyword outside a code span: {ln[:50]!r}")
        checks = ((LOCAL_PATH, "a local path"), (AGENT_NAME, "an agent name"),
                  (URL_OR_HOST, "a URL or host"), (WORDS, "a public-text word"))  # fmt: skip
        for rx, what in checks:
            m2 = rx.search(text)
            if m2:
                bad.append(f"{doc}: {what} ({m2[0]!r})")
    return one("G-HYGIENE", bad)


def g_pins(t: Texts) -> list[Finding]:
    pinned = parse_pins(t.pins)
    if not pinned:
        return one("G-RULED-PIN", [f"{PIN_REL} is empty or missing (run --repin-ruled)"])
    return one("G-RULED-PIN", pin_problems(pinned, all_units(t)))


GATES: tuple[Callable[[Texts], list[Finding]], ...] = (
    g_values, g_lift, g_copy, g_cite, g_version, g_tools, g_glyphs, g_index, g_deck, g_rows,
    g_t2, g_mnr, g_events, g_pending, g_ahead, g_untouched, g_ticks, g_frozen, g_ruled,
    g_hygiene,
)  # fmt: skip


def gate_name(g: Callable[[Texts], list[Finding]]) -> str:
    return "G-" + g.__name__[2:].upper()


def audit(t: Texts, timings: dict[str, float] | None = None) -> list[Finding]:
    found: list[Finding] = []
    for g in GATES:
        t0 = time.perf_counter()
        found += g(t)
        if timings is not None:
            timings[gate_name(g)] = time.perf_counter() - t0
    pins = g_pins(t)
    if any(f.level == "FAIL" for f in found):
        pins = [replace(f, level="NOTE") for f in pins]
    return found + pins


def load() -> Texts:
    mb = merge_base()
    full = (git_raw("rev-parse", "--verify", f"{BASE}^{{commit}}") or "").strip()
    if mb is None or not full:
        raise SystemExit(f"`git merge-base HEAD {HEAD_REF}` or the base {BASE} does not resolve")
    env = Env(full, mb, {})
    pins = read_raw(PIN_REL) if (ROOT / PIN_REL).exists() else ""
    deck = read_raw(DECK_REL) if (ROOT / DECK_REL).exists() else "{}"
    t = Texts(env, read_raw(SPEC_REL), deck, pins, read_raw(PLAN14_REL), changed_paths(mb), {},
              dict(TICKS))  # fmt: skip
    return replace(t, values=compute(t))


# ---------------------------------------------------------------------------- self-test


@dataclass(frozen=True)
class Mutation:
    gate: str
    what: str
    apply: Callable[[Texts], Texts]


def flex(old: str) -> re.Pattern[str]:
    """`old` with every run of spaces matching any run of spaces (prettier re-pads tables)."""
    return re.compile(r"\s+".join(re.escape(p) for p in old.split(" ") if p != ""))


def subst(old: str, new: str, doc: str = "spec") -> Callable[[Texts], Texts]:
    def f(t: Texts) -> Texts:
        text = getattr(t, doc)
        m = flex(old).search(text)
        if not m:
            raise SystemExit(f"self-test: {doc} lacks {old[:60]!r}")
        return replace(t, **{doc: text[: m.start()] + new + text[m.end() :]})

    return f


def anchor_edit(key: str, new_value: str, doc: str = "spec") -> Callable[[Texts], Texts]:
    def f(t: Texts) -> Texts:
        text = getattr(t, doc)
        m = re.search(rf"([^\s<|`(\[\"']+|`[^`\n]*`)<!--={re.escape(key)}-->", text)
        if not m:
            raise SystemExit(f"self-test: {doc} has no anchored {key}")
        return replace(
            t, **{doc: text[: m.start()] + f"{new_value}<!--={key}-->" + text[m.end() :]}
        )

    return f


def with_text(t: Texts, rev: str, rel: str, text: str) -> Texts:
    memo = {k: v for k, v in t.env.memo.items() if k != f"show:{rev}:{rel}"}
    memo[f"show:{rev}:{rel}"] = text
    return replace(t, env=Env(t.env.base, t.env.mb, memo))


def copy_edit(t: Texts) -> Texts:
    m = re.search(r"<!-- COPY:d06\.s64 -->\n+(.)", t.spec)
    if not m:
        raise SystemExit("self-test: the spec has no COPY:d06.s64 block")
    i = m.start(1)
    return replace(t, spec=t.spec[:i] + ("X" if t.spec[i] != "X" else "Y") + t.spec[i + 1 :])


def head_gone(t: Texts) -> Texts:
    rel = PATHS["D04"]
    ls = t.env.lines(t.env.base, rel)
    ls[530] = ls[530] + " (edited)"
    return with_text(t, HEAD_REF, rel, "\n".join(ls))


def deck_edit(t: Texts) -> Texts:
    data = json.loads(t.deck)
    k = "d06:01"
    data["entries"][k]["text"] = data["entries"][k]["text"] + " "
    return replace(t, deck=json.dumps(data, ensure_ascii=False, indent=2) + "\n")


def parent_changed(t: Texts) -> Texts:
    return replace(t, changed=[*(t.changed or []), PATHS["D04"]])


def tick_moved(t: Texts) -> Texts:
    """One tick's evidence pointed at a section its parent lacks, in the tool's ticks, `14` and
    §15.1 alike (so the three still agree and only the evidence is wrong)."""
    old, new = "E14-D07 §6, boards 07, 08", "E14-D07 §19, boards 07, 08"
    if old not in t.plan14 or old not in t.spec:
        raise SystemExit("self-test: the item-6 tick evidence is not found")
    ticks = dict(t.ticks)
    ticks[6] = new
    return replace(t, ticks=ticks, plan14=t.plan14.replace(old, new),
                   spec=t.spec.replace(old, new))  # fmt: skip


def merged_and_edited(t: Texts) -> Texts:
    """A merge-base that already holds this pack and its `14` lines (a simulated later PR)."""
    sim = "simulated-merge-base"
    memo = dict(t.env.memo)
    memo[f"show:{sim}:{SPEC_REL}"] = t.spec
    memo[f"show:{sim}:{PLAN14_REL}"] = t.plan14
    t2 = replace(t, env=Env(t.env.base, sim, memo))
    row = next(ln for ln in t.spec.split("\n") if ln.startswith("| v1 "))
    return replace(
        t2, spec=t.spec.replace(row, row.replace("on the merged parents", "on merged parents"), 1)
    )


def drop_row(lead: str) -> Callable[[Texts], Texts]:
    def f(t: Texts) -> Texts:
        ls = t.spec.split("\n")
        hits = [i for i, ln in enumerate(ls) if ln.startswith(lead)]
        if len(hits) != 1:
            raise SystemExit(f"self-test: {len(hits)} rows start with {lead!r}")
        del ls[hits[0]]
        return replace(t, spec="\n".join(ls))

    return f


def repinned(f: Callable[[Texts], Texts]) -> Callable[[Texts], Texts]:
    """The mutation with the pins re-derived after it, so the frozen-text pin cannot be the gate
    that catches it (a completeness gate must)."""

    def g(t: Texts) -> Texts:
        t2 = f(t)
        t2 = replace(t2, values=compute(t2))
        return replace(t2, pins=write_pins(all_units(t2)))

    return g


def defining_row_moved(t: Texts) -> Texts:
    """D08's fill row (the definition of the default opacity) changes at the base and at
    origin/main alike: G-VALUES must re-read it there, not at a restating line."""
    rel = PATHS["D08"]
    ls = t.env.lines(t.env.base, rel)
    i = next(k for k, ln in enumerate(ls) if ln.startswith("| fill "))
    ls[i] = ls[i].replace("default 0.05", "default 0.07")
    t2 = with_text(t, t.env.base, rel, "\n".join(ls))
    t2 = with_text(t2, HEAD_REF, rel, "\n".join(ls))
    return replace(t2, values=compute(t2))


MUTATIONS: tuple[Mutation, ...] = (
    Mutation("G-VALUES", "type a handle size by hand", anchor_edit("CITE:d08.glyph_px", "9")),
    Mutation("G-VALUES", "change the fill default at its defining row (base and origin/main)",
             defining_row_moved),
    Mutation("G-LIFT", "alter a lifted block's hash", anchor_edit("HASH:d08.s5_7", "000000000000")),
    Mutation("G-COPY", "change one byte inside the copied D06 §6.4", copy_edit),
    Mutation("G-CITE", "point a cite past the end of its file",
             subst("(`D02`:422); its table", "(`D02`:99999); its table")),
    Mutation("G-VERSION", "edit a cited D04 line at origin/main", head_gone),
    Mutation("G-TOOLS", "give the trendline three anchors in the behaviour table",
             subst("| `trendline` | 2 |", "| `trendline` | 3 |")),
    Mutation("G-GLYPHS", "rename a glyph in the register",
             subst("| ray | `ray` |", "| ray | `ray-line` |")),
    Mutation("G-INDEX", "map E14-S04 to the wrong user story",
             subst("| E14-S04 (#473) | US-DRAW-004 |", "| E14-S04 (#473) | US-DRAW-005 |")),
    Mutation("G-DECK", "alter one deck string", deck_edit),
    Mutation("G-ROWS", "a due sprint before the first consumer's (re-pinned)",
             repinned(subst("| Sprint 06<!--=SPRINT:t02--> | open; routed by D08 G-1",
                            "| Sprint 02 | open; routed by D08 G-1"))),
    Mutation("G-ROWS", "grade a row outside the four",
             subst("| C-8 | contradiction | Info ", "| C-8 | contradiction | Note ")),
    Mutation("G-T2", "drop the measure Pin row (re-pinned)", repinned(drop_row("| measure Pin "))),
    Mutation("G-T2", "give the settings row the workspaces verb (re-pinned)",
             repinned(subst('| "change settings" |', '| "save workspaces" |'))),
    Mutation("G-T2", "drop the lock glyph's `decorative={false}`",
             subst("glyph (`decorative={false}`, accessible name", "glyph (accessible name")),
    Mutation("G-MNR", "drop the anchored-VWAP budget row (re-pinned)",
             repinned(drop_row("| anchored VWAP update "))),
    Mutation("G-MNR", "own the 58-fps row by `14` instead of C-14.2",
             subst("| CONSTITUTION C-14.2 (", "| `14` SCR-037 (")),
    Mutation("G-EVENTS", "name an event no source defines",
             subst("and `drawing.removed` for SCR-036", "and `drawing.erased` for SCR-036")),
    Mutation("G-PENDING", "drop the v1.1 version row (re-pinned)", repinned(drop_row("| v1.1 "))),
    Mutation("G-AHEAD", "type a margin by hand", anchor_edit("DAYS:margin.s10", "99")),
    Mutation("G-UNTOUCHED", "edit a parent in the same tree", parent_changed),
    Mutation("G-TICKS", "point a tick's evidence at a missing section (tool, 14 and §15.1)",
             tick_moved),
    Mutation("G-FROZEN", "post-merge: edit the merged v1 row", merged_and_edited),
    Mutation("G-RULED", "drop the stamp's date from the questions heading",
             subst("## The questions BQ-01..BQ-16 — RULED (orchestrator, 2026-10-31,",
                   "## The questions BQ-01..BQ-16 — RULED (orchestrator,")),
    Mutation("G-HYGIENE", "write a closing keyword outside a code span",
             subst("The PR body carries `Closes #355`.", "The PR body carries Closes #355.")),
    Mutation("G-RULED-PIN", "re-word a pinned sentence no other gate reads",
             subst("Nothing on these screens is built: the pack is the build's input.",
                   "Nothing on these screens is built yet: the pack is the build's input.")),
)  # fmt: skip


def digest(t: Texts) -> str:
    return hashlib.sha256(f"{t.spec}\0{t.deck}\0{t.pins}\0{t.plan14}".encode()).hexdigest()


def ascii_line(s: str) -> str:
    for a, b in (("→", "->"), ("…", "..."), ("—", "-"), ("–", "-"), ("×", "x"), ("§", "S"),
                 ("·", "|"), ("≤", "<="), ("≥", ">=")):  # fmt: skip
        s = s.replace(a, b)
    return s.encode("ascii", "replace").decode()[:100]


def selftest() -> tuple[bool, list[str]]:
    t0 = time.perf_counter()
    base = load()
    disk = [
        hashlib.sha256(read_raw(r).encode()).hexdigest() for r in OWN_PATHS if (ROOT / r).exists()
    ]
    before = digest(base)
    base_fails = [f for f in audit(base) if f.level == "FAIL"]
    out = [f"self-test: baseline {len(base_fails)} FAIL"]
    ok = not base_fails
    for f in base_fails:
        out.append(ascii_line(f"  baseline {f.gate}: {f.msg}"))
    gates_hit: set[str] = set()
    for i, m in enumerate(MUTATIONS, 1):
        found = audit(m.apply(base))
        fails = sorted({f.gate for f in found if f.level == "FAIL"})
        good = fails == [m.gate]
        ok &= good
        if good:
            gates_hit.add(m.gate)
        out.append(ascii_line(f"{'ok  ' if good else 'FAIL'} M-{i} {m.gate}: {m.what} -> "
                              f"{', '.join(fails) or 'none'}"))  # fmt: skip
    every = {gate_name(g) for g in GATES} | {"G-RULED-PIN"}
    missed = sorted(every - gates_hit)
    ok &= not missed
    restored = digest(base) == before and disk == [
        hashlib.sha256(read_raw(r).encode()).hexdigest() for r in OWN_PATHS if (ROOT / r).exists()
    ]
    ok &= restored
    out.append(f"self-test: {len(MUTATIONS)} mutations over {len(every)} gates, caught "
               f"{len(gates_hit)}, missed {', '.join(missed) or 'none'}; texts restored: "
               f"{'yes' if restored else 'NO'}")  # fmt: skip
    out.append(f"self-test: {'PASS' if ok else 'FAIL'} in {time.perf_counter() - t0:.1f} s")
    return ok, out


# ---------------------------------------------------------------------------- main


def main(argv: list[str]) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0] if __doc__ else "")
    g = ap.add_mutually_exclusive_group()
    g.add_argument("--check", action="store_true", help="the default mode")
    g.add_argument("--self-test", action="store_true")
    g.add_argument("--repin-ruled", action="store_true")
    ap.add_argument("--json", action="store_true", help="--check's dump")
    ap.add_argument("--fill", action="store_true", help="fill the values, the blocks and the deck")
    a = ap.parse_args(argv)
    if a.self_test:
        ok, lines = selftest()
        print("\n".join(lines))
        return 0 if ok else 1
    t = load()
    if a.repin_ruled:
        if unfilled(t.spec):
            print("refused: the pack has an unfilled placeholder (run --check --fill)")
            return 1
        other = [f for f in audit(t) if f.level == "FAIL" and f.gate != "G-RULED-PIN"]
        if other:
            print(f"refused: {len(other)} FAIL outside the pins (first: {other[0].gate}); fix them")
            return 1
        write_text(PIN_REL, write_pins(all_units(t)))
        print(f"wrote {PIN_REL}")
        return 0
    if a.fill:
        copies = copy_sources(t.env)
        deck = json.dumps(derive_deck(t.env), ensure_ascii=False, indent=2) + "\n"
        write_text(DECK_REL, deck)
        t = replace(t, deck=deck)
        missing: list[str] = []
        for _ in range(2):  # the counts over this file settle once its own tables are filled
            t = replace(t, values=compute(t))
            spec, missing = fill(t.spec, t.values, copies)
            write_text(SPEC_REL, spec)
            t = replace(t, spec=spec)
        want14, _ = apply14(t.env.show(t.env.mb, PLAN14_REL) or "", t.ticks)
        if not post_merge(t) and t.plan14 != want14:
            write_text(PLAN14_REL, want14)
        for m in missing:
            print(f"unfilled: {m}")
        t = load()
    timings: dict[str, float] = {}
    found = audit(t, timings)
    fails = [f for f in found if f.level == "FAIL"]
    if a.json:
        dump = {"base": t.env.base, "merge_base": t.env.mb, "post_merge": post_merge(t),
                "values": t.values,
                "findings": [{"level": f.level, "gate": f.gate, "msg": f.msg}
                             for f in found]}  # fmt: skip
        print(json.dumps(dump, ensure_ascii=False, indent=2, sort_keys=True))
    else:
        for f in found:
            print(ascii_line(f"{f.level} {f.gate}: {f.msg}"))
        warns = sum(f.level == "WARN" for f in found)
        notes = sum(f.level == "NOTE" for f in found)
        mode = "post-merge" if post_merge(t) else "PR-1"
        print(
            f"{len(fails)} FAIL / {warns} WARN / {notes} NOTE ({len(GATES) + 1} gates, "
            f"{len(all_cites(t))} cites, {mode} mode)"
        )
    return 1 if fails else 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
