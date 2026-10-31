#!/usr/bin/env python3
"""E32-D07 (#927) audit: the accessibility review and the engineering hand-off pack for SCR-064,
SCR-065 and SCR-069's bracket half.

Standalone, offline, stdlib only; it runs under `python3 -I` and executes no repo code but the
sibling `contrast_check.py` (imported by function). It reads AS TEXT at the pinned base `BASE`
(`git show`): the plan texts, the merged E32 design docs (D02 ... D06 and the three hand-offs),
the precedents the files cite, `24`'s audited-action line, E30-D06's deck, the token JSON, the CVD
script, the calendar and the E32 backlog JSON; then the pack (`E32-D07.md`), the review
(`E32-D07-a11y.md`), the deck (`E32-D07-copy.json`), `14` and the pins from the working tree.

Values. Every `{{KIND:key}}` outside a code span is computed and `--fill` writes it as
`VALUE<!--=KIND:key-->`; a `{{COPY:key}}` line becomes the source block between
`<!-- COPY:key -->` and `<!-- /COPY:key -->`, byte-equal to its source at the base. `--check`
re-derives every anchored value and every copied block; no placeholder may remain.

Gates (one mutation each in `--self-test`):
  G-VALUES    the anchored SHA, STATUS, CITE, WIDTH and plain COUNT values. A CITE value is read
              from its defining line (the line that states the figure), never from a bare word.
  G-LIFT      every HASH anchor equals the sha256 (12 hex) of its lifted block, each line
              whitespace-normalised.
  G-COPY      every COPY block equals its source block at the base, byte for byte.
  G-CITE      every `KEY`:line cite (and its `, :n` continuations) is in range at the base and the
              range's ends are non-blank; copied blocks are the source's own and are skipped.
  G-VERSION   every cited line's content stands at `origin/main` (moved = WARN, gone = FAIL).
  G-CONTRAST  the review's §7.1 pairs in three themes through `themes.json`'s layering.
  G-CVD       the §7.2 pairs through `cvd_sim.py`'s greyscale weights and two matrices (parsed
              from its source) and this pack's own tritanopia matrix (Machado et al. 2009).
  G-DECK      the deck equals the derivation from the four parents' deck tables (each entry
              anchored at its own table row) plus the bound `e32.sl.required`, read from E30-D06's
              deck entry; every PROPOSED entry names an owner.
  G-SCRIPT    every `dNN:key` deck reference resolves; every script id a QA line names exists.
  G-FROWS     the findings: severity and p-scale paired (p0 Blocking ... p3 Info); each owner and
              target a spec or an area, never an agent; every story a row targets binds it in the
              pack's §3.1; the counts, the
              verdict vocabulary, every F id cited exists, and the "no p0, no p1" sentence stands
              exactly when no Blocking or Major row exists.
  G-SPEAKER   one region per announcement row; the placing-line simulation.
  G-EVENTS    every name in the Registered column stands on `24` §15.5's closed-set line (its
              definition line); every audit name in the plan that is not registered carries a gap.
  G-AHEAD     the sprint, date and margin values from the calendar and the backlog JSON.
  G-OPENROWS  every open-row range's first and last id is a table row of its parent in the cited
              lines.
  G-UNTOUCHED PR-1 mode: the tree differs from the merge-base only in this pack's files and `14`,
              and `14` equals the merge-base with the six lines applied by content. Post-merge
              mode: `14` is untouched.
  G-TICKS     every evidence cite of the six `14` ticks resolves at the base: a `§n` to a heading
              of the named parent, a board to its board list, a row id to a table row (the ticks are
              a Texts field, so the self-test moves them in the tool and in `14` together).
  G-T2        R-5 states a gated control's `aria-disabled="true"`, its `aria-describedby` reason
              node and its CMP-079 RbacGate wrap with the CMP-019 `lock`; NR-05 carries them; both
              component lists name CMP-079 and CMP-019 (G-T2.1c, G-T2.1d, G-T2.6).
  G-FROZEN    post-merge mode (the pack is on the merge-base): every version row of the merge-base
              stands unchanged and a new row is v1.N with N above the last.
  G-RULED     the ruling stamp in both question sections, the ruling id, BQ-01..BQ-19, no marker.
  G-HYGIENE   no placeholder left, no stray HTML comment, no closing keyword outside a code span,
              no local path, agent name, host or URL, none of the public-text words.
  G-RULED-PIN a default-deny pin set over every unit of the pack and the review (values cut out,
              copied blocks collapsed), every deck entry and every cite's line hash; only
              `--repin-ruled` writes it. Its findings print as NOTE while another gate FAILs.

Usage (from the repo root):
  python3 -I docs/design/_tools/e32_d07_handoff_audit.py --check [--json] [--fill]
  python3 -I docs/design/_tools/e32_d07_handoff_audit.py --self-test
  python3 -I docs/design/_tools/e32_d07_handoff_audit.py --repin-ruled
Exit 0 = no FAIL; 1 = at least one FAIL.
"""

from __future__ import annotations

import argparse
import datetime
import hashlib
import importlib.util
import itertools
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
BASE = "fd96d4bdb0"  # the base of record: every cite was read here (the version line)
HEAD_REF = "origin/main"
VERSION_DATE = datetime.date(2026, 10, 31)  # v1's date: the design-ahead margins count from it
ISSUE = "927"
RULING_ID = "6546356513"
STAMP = "RULED (orchestrator, 2026-10-31, #927 ruling of record — 6545787423's answer)"
BQ_TOTAL = 19

SPEC_REL = "docs/design/E32/E32-D07.md"
REVIEW_REL = "docs/design/E32/E32-D07-a11y.md"
DECK_REL = "docs/design/E32/E32-D07-copy.json"
TOOL_REL = "docs/design/_tools/e32_d07_handoff_audit.py"
PIN_REL = "docs/design/_tools/e32_d07_ruled_pins.txt"
PLAN14_REL = "docs/plan/14-screens-catalogue.md"
OWN_PATHS = (SPEC_REL, REVIEW_REL, DECK_REL, TOOL_REL, PIN_REL, PLAN14_REL)
CVD_REL = "docs/design/_tools/cvd_sim.py"
CONTRAST_REL = "docs/design/_tools/contrast_check.py"
DS_SRC = "packages/ui/tokens"
IMG_REL = "docs/design/E32/img"

PATHS: dict[str, str] = {
    "02": "docs/plan/02-definition-of-ready-done.md",
    "05": "docs/plan/05-accessibility-standard.md",
    "06": "docs/plan/06-performance-and-load-standard.md",
    "14": PLAN14_REL,
    "15": "docs/plan/15-component-catalogue.md",
    "22": "docs/plan/22-api-openapi.yaml",
    "24": "docs/plan/24-internal-schemas.md",
    "D02": "docs/design/E32/E32-D02.md",
    "D03": "docs/design/E32/E32-D03.md",
    "D03H": "docs/design/E32/E32-D03-handoff.md",
    "D04": "docs/design/E32/E32-D04.md",
    "D05": "docs/design/E32/E32-D05.md",
    "D05H": "docs/design/E32/E32-D05-handoff.md",
    "D06": "docs/design/E32/E32-D06.md",
    "D06H": "docs/design/E32/E32-D06-handoff.md",
    "E17D02": "docs/design/E17/E17-D02.md",
    "E22D04": "docs/design/E22/E22-D04.md",
    "E30D02": "docs/design/E30/E30-D02.md",
    "E30D06-copy": "docs/design/E30/E30-D06-copy.json",
    "E33D03": "docs/design/E33/E33-D03.md",
    "E33D05": "docs/design/E33/E33-D05.md",
    "CAL": "docs/plan/backlog/_tools/calendar_cv.py",
    "E32J": "docs/plan/backlog/E32.json",
}
THEMES = ("dark", "light", "hc")
BARS = {"text": 4.5, "non-text": 3.0}

# the CVD pairs of the review's §7.2 (V id -> the two token names)
V_PAIRS: dict[str, tuple[str, str]] = {
    "v1": ("color.status.info.subtle", "color.status.success.subtle"),
    "v2": ("color.status.success.subtle", "color.status.danger.subtle"),
    "v3": ("color.status.warning.subtle", "color.status.danger.subtle"),
    "v4": ("color.status.info.subtle", "color.status.danger.subtle"),
}
# this pack's own tritanopia matrix (RULED BQ-09): Machado, Oliveira and Fernandes, "A
# Physiologically-based Model for Simulation of Color Vision Deficiency", IEEE TVCG 15(6), 2009,
# the tritanopia matrix at severity 1.0 (the table `cvd_sim.py`'s two matrices come from)
TRITANOPIA = (1.255528, -0.076749, -0.178779, -0.078411, 0.930809, 0.147602, 0.004733, 0.691367,
              0.303900)  # fmt: skip

# the blocks copied byte for byte (key -> the source and its heading prefix)
COPIES: dict[str, tuple[str, str]] = {
    "d02.s37": ("D02", "### 3.7 "),
    "d04.s41": ("D04", "### 4.1 "),
    "d05.s9": ("D05", "## 9. "),
    "d06.s8": ("D06", "## 8. "),
    "d06.s10": ("D06", "## 10. "),
}
# the blocks lifted by hash (key -> the source and its spans: (start heading, end heading or ""))
LIFTS: dict[str, tuple[str, tuple[tuple[str, str], ...]]] = {
    "d02.focus": ("D02", (("### 4.4 ", ""), ("### 5.5 ", ""), ("### 6.5 ", ""))),
    "d02.events": ("D02", (("### 4.6 ", ""), ("### 5.6 ", ""))),
    "d02.s45": ("D02", (("### 4.5 ", ""),)),
    "d03.s2_7": ("D03", (("## 2. ", "## 8. "),)),
    "d04.s2_9": ("D04", (("## 2. ", "## 10. "),)),
    "d05.s2_10": ("D05", (("## 2. ", "## 11. "),)),
    "d06.s3_6": ("D06", (("## 3. ", "## 7. "),)),
    "d03h": ("D03H", (("", ""),)),
    "d05h": ("D05H", (("", ""),)),
    "d06h": ("D06H", (("", ""),)),
    "review.s4": ("REVIEW", (("## 4. ", "## 5. "),)),
    "review.s6": ("REVIEW", (("## 6. ", "## 7. "),)),
    "review.s63": ("REVIEW", (("### 6.3 ", "## 7. "),)),
}
# CITE values: key -> (source, the defining line's needle, the figure's pattern)
CITES: dict[str, tuple[str, str, str]] = {
    "perf.frame_ms": ("06", "| 1 | Chart engine frame time |", r"≤(\d+(?:\.\d+)?)ms/frame"),
    "perf.amend_ms": ("14", "- **Performance:** Amend round-trip target", r"<=(\d+) ms p95"),
    "perf.ack_demo": ("06", "| 4 | Order submit → ack |", r"p95 < (\d+)ms \(demo"),
    "perf.ack_live": ("06", "| 4 | Order submit → ack |", r"p95 < (\d+)ms \(live"),
    "d05.dialog_px": ("D05", "<!-- audit:rows.dialog_px=", r"audit:rows\.dialog_px=(\d+)"),
    "d05.row_compact": ("D05", "<!-- audit:rows.compact_px=", r"audit:rows\.compact_px=(\d+)"),
    "d05.row_comfortable": ("D05", "<!-- audit:rows.comfortable_px=",
                            r"audit:rows\.comfortable_px=(\d+)"),
    "d03.dialog_px": ("D03", "<!-- audit:fixture.dialog_px=", r"audit:fixture\.dialog_px=(\d+)"),
    "d04.min_px": ("D04", "The widths are the tool's", r"minimum width \((\d+) px\)"),
    "d04.fit_px": ("D04", "The widths are the tool's", r"(\d+) px fit"),
}  # fmt: skip
# the backlog keys whose sprints the design-ahead record reads
SPRINT_KEYS = {
    "E32-S05": "s05", "E32-S06": "s06", "E32-S07": "s07", "E32-D08": "d08",
    "E32-Q07": "q07", "E32-Q08": "q08", "E32-T01": "t01", "E32-D07": "d07",
}  # fmt: skip
MARGINS = ("s05", "s06", "s07", "d08")
# the four parents' deck tables: id prefix -> (source, heading prefix, owner of a PROPOSED row)
DECKS: dict[str, tuple[str, str, str]] = {
    "d02": ("D02", "### 3.8 ", "E32-D02 (#855)"),
    "d03": ("D03", "## 10. ", "E32-D03 (#923)"),
    "d04": ("D04", "## 12. ", "E32-D04 (#924)"),
    "d05": ("D05", "## 13. ", "E32-D05 (#925)"),
}
NATIVE_KEY = re.compile(
    r"^(?:e32\.)?(?:sl|sltp|stop_pending|v\.sl)(?:[._]|$)|^(?:ladder|bkt|e32)\.stop"
)
BOUND_KEY = "ticket.order.v.sl.required"  # E30-D06's ruled entry (RULED BQ-12)
BOUND_ID = "e32:e32.sl.required"

# the six `14` lines (RULED BQ-14): the checklist line per screen and the pointer line after its
# anchor, applied by content to the merge-base's `14`
POINTER = (
    "- **Hand-off pack{half}:** [E32-D07.md](../design/E32/E32-D07.md) v1 (E32-D07; owner approval "
    "pending; a11y review: [E32-D07-a11y.md](../design/E32/E32-D07-a11y.md))"
)
CHECKLIST_PREFIX = "- **Design sign-off acceptance checklist:** "
SCREENS: dict[str, tuple[str, str, str]] = {
    "SCR-064": (
        "- **Design (hi-fi):** [E32-D05.md]",
        "",
        (
            "[x] price / ticks / % / R-multiple entry modes with the others recomputed live (E32-D05 §2, "
            "§15; board 02) [x] resulting risk in account currency and R shown before confirm (E32-D05 "
            "§2, §15; board 02) [x] 'SL cannot be removed, only moved' rule stated and enforced in the UI "
            "(E32-D05 §6, §15; E32-D06 §5; board 03) [x] invalid-side and beyond-liquidation validation "
            "messages drawn (E32-D05 §3, §15; board 03) [x] partial-quantity TP ladder variant drawn "
            "(E32-D05 §8, §15; board 06) [x] keyboard path equivalent to chart drag-to-modify (E32-D05 "
            "§9; E32-D07-a11y §4.1; board 09)"
        ),
    ),
    "SCR-065": (
        "- **Design (hi-fi):** [E32-D04.md]",
        "",
        (
            "[x] start/end price, level count and distribution (flat / linear / exponential / custom) "
            "drawn (E32-D04 §2, §5, §14; D04-C5; boards 01, 04) [x] full preview table with resulting "
            "average price (E32-D04 §4, §14; E32-D07-a11y §4.2; boards 02, 03) [x] rate-limit estimate "
            "shown before submit (E32-D04 §8, §14; board 09) [x] validation messages for tick/lot "
            "rounding and for a range crossing the mark (E32-D04 §6.3, §14; board 06) [x] mandatory "
            "native SL applied per level or per resulting position - drawn explicitly (E32-D04 §7.1, "
            "§14: per resulting position; board 07) [x] cancel-all-levels control (E32-D04 §7.3, §14; "
            "board 08)"
        ),
    ),
    "SCR-069": (
        "- **Hand-off pack (OCO half):** [E33-D06.md]",
        " (bracket half)",
        (
            "[x] entry+bracket and standalone-OCO variants drawn (E32-D03 §3, §12; E33-D03 §2–§4) [x] "
            "'emulated - Bybit has no OCO' stated prominently (E33-D03 §15; E32-D03 §12) [x] "
            "race-resolution behaviour explained in the dialog (E33-D03 §15; E32-D03 §12) [x] "
            "residual-risk "
            "state (app offline during a fill) drawn with what the user must do (E33-D03 §15; E32-D03 §3 "
            "row 19, §12) [x] the mandatory native SL floor is shown as always-present and "
            "non-removable (E32-D03 §4.1, §12; E32-D06 §5) [x] validation messages drawn (E32-D03 §4, "
            "§12; board 03)"
        ),
    ),
}

SEVERITIES = {"Blocking": "p0", "Major": "p1", "Minor": "p2", "Info": "p3"}
VERDICTS = ("compliant", "at risk", "non-compliant", "out of scope", "not yet decidable")
NO_P0 = "No p0, no p1; AC 3's failure path not triggered"
OWNER_PENDING = "owner approval pending (#2701)"

PLACEHOLDER = re.compile(r"\{\{([A-Z]+:[^{}]+?)\}\}")
# a value is one code span or one run of value characters: never a leading bracket or quote, so a
# refresh cannot eat the punctuation in front of a value
ANCHORED = re.compile(r"(`[^`\n]*`|[^\s<|`(\[\"']+)<!--=([A-Z]+:[^>]+?)-->")
COPY_LINE = re.compile(r"^\{\{COPY:([a-z0-9._]+)\}\}$")
COPY_OPEN = re.compile(r"^<!-- COPY:([a-z0-9._]+) -->$")
COPY_BLOCK = re.compile(
    r"^<!-- COPY:([a-z0-9._]+) -->\n.*?\n<!-- /COPY:\1 -->$", re.MULTILINE | re.DOTALL
)
CODE = re.compile(r"`[^`\n]*`")
HEADING = re.compile(r"^(#{1,6}) (.+)$")
RULE = re.compile(r"^\s*\|?\s*:?-{3,}")
CITE = re.compile(r"`(" + "|".join(re.escape(k) for k in sorted(PATHS, key=len, reverse=True))
                  + r")`:(\d+)(?:[–-](\d+))?")  # fmt: skip
CONT = re.compile(r"^(?:,\s*|\s+and\s+):(\d+)(?:[–-](\d+))?")
DECK_REF = re.compile(r"`(d0[2-5]:[a-z0-9_.*]+(?:#\d+)?)`")
TOKEN_NAME = re.compile(
    r"^(?:color|size|space|radius|type|opacity|border|elevation|motion)\.[a-z0-9.\-]+$"
)
SCRIPT_ID = re.compile(r"\bSR-06[459]-\d\d\b")
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
    """The text with every anchored value back to its placeholder and every copy collapsed."""
    text = collapse_copies(text)
    return ANCHORED.sub(lambda m: "{{" + m[2] + "}}", text)


def anchored(text: str) -> list[tuple[str, str, int]]:
    text = collapse_copies(text)
    return [
        (m[1], m[2], i) for i, ln in enumerate(text.split("\n"), 1) for m in ANCHORED.finditer(ln)
    ]


def unfilled(text: str) -> list[str]:
    """Every placeholder outside a code span and outside a filled copy (a COPY line included)."""
    text = COPY_BLOCK.sub("", text)
    return [m[1] for ln in text.split("\n") for m in PLACEHOLDER.finditer(without_code(ln))]


# ---------------------------------------------------------------------------- colour math


_CONTRAST: object | None = None


def contrast(a: str, b: str) -> float:
    global _CONTRAST
    if _CONTRAST is None:
        spec = importlib.util.spec_from_file_location("cv_contrast_check", ROOT / CONTRAST_REL)
        if spec is None or spec.loader is None:
            raise SystemExit(f"{CONTRAST_REL} cannot be imported")
        mod = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(mod)
        _CONTRAST = mod
    fn = getattr(_CONTRAST, "contrast_ratio", None)
    if fn is None:
        raise SystemExit(f"{CONTRAST_REL} has no contrast_ratio")
    return float(fn(rgb(a), rgb(b)))


def rgb(hex6: str) -> tuple[int, int, int]:
    h = hex6.lstrip("#")
    return int(h[0:2], 16), int(h[2:4], 16), int(h[4:6], 16)


def show_ratio(r: float) -> str:
    return f"{int(r * 100) / 100:.2f}"


def clip_byte(v: float) -> int:
    return max(0, min(255, round(v)))


def cvd_matrices(env: Env) -> dict[str, tuple[float, ...]]:
    key = "cvd:matrices"
    if key not in env.memo:
        src = env.at_base(CVD_REL)
        out: dict[str, tuple[float, ...]] = {"trit": TRITANOPIA}
        for name, sim in (("DEUTERANOPIA_MATRIX", "deut"), ("PROTANOPIA_MATRIX", "prot")):
            m = re.search(name + r"\s*=\s*np\.array\(\s*\[(.*?)\]\s*\)", src, re.DOTALL)
            out[sim] = tuple(float(x) for x in re.findall(r"-?\d+\.\d+", m[1])) if m else ()
        g = re.search(r"\*\s*(\d\.\d+)\s*\+.*?\*\s*(\d\.\d+)\s*\+.*?\*\s*(\d\.\d+)", src)
        out["grey"] = tuple(float(x) for x in g.groups()) if g else ()
        env.memo[key] = out
    v = env.memo[key]
    return v if isinstance(v, dict) else {}


def simulate(env: Env, hex6: str, sim: str) -> str:
    r, g, b = rgb(hex6)
    mats = cvd_matrices(env)
    if sim == "grey":
        w = mats.get("grey", ())
        if len(w) != 3:
            raise SystemExit("cvd_sim.py: the greyscale weights were not found")
        y = clip_byte(r * w[0] + g * w[1] + b * w[2])
        return f"#{y:02X}{y:02X}{y:02X}"
    m = mats.get(sim, ())
    if len(m) != 9:
        raise SystemExit(f"cvd_sim.py: the {sim} matrix was not found")
    rr = clip_byte(m[0] * r + m[1] * g + m[2] * b)
    gg = clip_byte(m[3] * r + m[4] * g + m[5] * b)
    bb = clip_byte(m[6] * r + m[7] * g + m[8] * b)
    return f"#{rr:02X}{gg:02X}{bb:02X}"


def layering(env: Env) -> dict[str, tuple[str, ...]]:
    data = json.loads(env.at_base(f"{DS_SRC}/themes.json"))
    out: dict[str, tuple[str, ...]] = {}
    for th in data.get("themes", []) if isinstance(data, dict) else []:
        if isinstance(th, dict) and th.get("group") == "theme":
            name = {"high-contrast": "hc"}.get(str(th.get("name")), str(th.get("name")))
            out[name] = tuple(str(x) for x in th.get("sets", []))
    return out


def theme(env: Env, name: str) -> dict[str, str]:
    key = f"theme:{name}"
    if key not in env.memo:
        merged: dict[str, str] = {}
        for f in layering(env).get(name, ()):
            data = json.loads(env.at_base(f"{DS_SRC}/{f}.tokens.json"))
            for k, v in data.items() if isinstance(data, dict) else []:
                if isinstance(v, dict) and "$value" in v:
                    merged[k] = v["$value"] if isinstance(v["$value"], str) else "(composite)"
        env.memo[key] = merged
    out = env.memo[key]
    return out if isinstance(out, dict) else {}


def resolve(env: Env, t: str, name: str, depth: int = 0) -> str | None:
    if depth > 24:
        return None
    m = re.fullmatch(r"\{([^{}]+)\}", name)
    if m:
        name = m[1]
    if re.fullmatch(r"#[0-9A-Fa-f]{6}", name):
        return name.upper()
    v = theme(env, t).get(name)
    return resolve(env, t, v, depth + 1) if v is not None else None


def shipped_names(env: Env) -> set[str]:
    out: set[str] = set()
    for t in THEMES:
        out |= set(theme(env, t))
    return out


# ---------------------------------------------------------------------------- the texts


@dataclass(frozen=True)
class Texts:
    env: Env
    spec: str
    review: str
    deck: str
    pins: str
    plan14: str
    changed: list[str] | None
    values: dict[str, str]
    ticks: dict[str, str]  # the six ticks per screen (SCREENS), a field so a mutation can move them


def doc_text(t: Texts, key: str) -> str:
    return t.review if key == "REVIEW" else t.env.at_base(PATHS[key])


def both(t: Texts) -> tuple[tuple[str, str], ...]:
    return (("spec", t.spec), ("review", t.review))


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
    data = json.loads(env.at_base(PATHS["E32J"]))
    items = (
        data
        if isinstance(data, list)
        else data.get("tickets", []) if isinstance(data, dict) else []
    )
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
        vals[f"SPRINT:{k}"] = str(n)
    for n in (15, 17, 18):
        vals[f"DATE:s{n}.start"] = first(n).isoformat()
    vals["DATE:s15.end"] = (first(16) - datetime.timedelta(days=1)).isoformat()
    for k in MARGINS:
        if k in sp:
            vals[f"DAYS:margin.{k}"] = str((first(sp[k]) - VERSION_DATE).days)
    return vals


def cite_values(env: Env) -> dict[str, str]:
    vals: dict[str, str] = {}
    for key, (src, needle, pat) in CITES.items():
        hits = [ln for ln in env.lines(env.base, PATHS[src]) if needle in ln]
        found = [m[1] for ln in hits for m in [re.search(pat, ln)] if m]
        if len(found) == 1:
            vals[f"CITE:{key}"] = found[0]
    return vals


def status_values(env: Env) -> dict[str, str]:
    feats = [
        p.split("/")[4] for p in env.tree(env.base, "apps/web/src/features") if p.count("/") > 4
    ]
    e32 = any(re.search(r"e32|sltp|ladder|bracket|position-sl", f) for f in feats)
    vals = {"STATUS:web.e32": "present" if e32 else "absent"}
    for key, name in (("ui.cmp119", "BracketEditor"), ("ui.cmp120", "TrailingStopEditor"),
                      ("ui.cmp158", "SafetyInvariantNotice")):  # fmt: skip
        vals[f"STATUS:{key}"] = (
            "present" if env.grep(env.base, name, ("packages/ui",)) else "absent"
        )
    contract = (PATHS["22"], "docs/plan/23-ws-protocol.md", PATHS["24"])
    vals["STATUS:contract.native_sl_required"] = (
        "present" if env.grep(env.base, "NATIVE_SL_REQUIRED", contract) else "absent"
    )
    return vals


def lift_hash(t: Texts, key: str) -> str | None:
    src, spans = LIFTS[key]
    text = unfill(t.review) if src == "REVIEW" else t.env.at_base(PATHS[src])
    ls = text.split("\n")
    parts: list[str] = []
    for head, end in spans:
        a, b = span(ls, head, end)
        if a < 0:
            return None
        parts.append("\n".join(pin_norm(x) for x in ls[a:b]))
    return sha12("\n".join(parts))  # whitespace-normalised: a table re-padded keeps its hash


def frames(env: Env, head: str) -> int:
    rows = tables(section(env.at_base(PATHS["D02"]), head))
    return sum(1 for r in (rows[0][1:] if rows else []) if r[1] and r[1][0].isdigit())


def contrast_rows(review: str) -> list[list[str]]:
    return [c for _, c in table_after(section(review, "### 7.1 "), "CT")]


def contrast_values(env: Env, review: str) -> dict[str, str]:
    vals: dict[str, str] = {}
    failing = 0
    rows = contrast_rows(review)
    for r in rows:
        if len(r) < 9:
            continue
        cid = r[0].lower().replace("-", "")
        fg, bg, kind = r[2].strip("`"), r[3].strip("`"), r[4]
        below: list[str] = []
        for th in THEMES:
            a, b = resolve(env, th, fg), resolve(env, th, bg)
            if a and b:
                ratio = contrast(a, b)
                vals[f"CONTRAST:{cid}.{th}"] = show_ratio(ratio)
                if kind in BARS and ratio < BARS[kind]:
                    below.append(th)
        failing += bool(below)
        vals[f"PAIR:{cid}"] = "`meets`" if not below else "`below:" + "+".join(below) + "`"
    vals["COUNT:contrast.pairs"] = str(len(rows))
    vals["COUNT:contrast.failing"] = str(failing)
    return vals


def cvd_values(env: Env) -> dict[str, str]:
    vals: dict[str, str] = {}
    for vid, (a, b) in V_PAIRS.items():
        for th in THEMES:
            ha, hb = resolve(env, th, a), resolve(env, th, b)
            if ha and hb:
                for sim in ("grey", "deut", "prot", "trit"):
                    vals[f"CVD:{vid}.{sim}.{th}"] = show_ratio(
                        contrast(simulate(env, ha, sim), simulate(env, hb, sim))
                    )
    return vals


def f_rows(review: str) -> list[list[str]]:
    return [c for _, c in table_after(section(review, "## 11. "), "Id")]


def an_rows(review: str) -> list[list[str]]:
    return [c for _, c in table_after(section(review, "### 6.2 "), "AN")]


def throttle_writes(window: float, n: int = 50, step: float = 0.2) -> tuple[int, float]:
    """A latest-value throttle (leading + trailing) over n events `step` s apart: the writes and
    the smallest gap between two writes."""
    events = [round(i * step, 6) for i in range(n)]
    writes: list[float] = []
    pending = False
    nxt = 0.0
    for e in events:
        while pending and nxt <= e:
            writes.append(nxt)
            pending = False
            nxt = writes[-1] + window
        if not writes or e >= nxt:
            writes.append(e)
            nxt = e + window
        else:
            pending = True
    if pending:
        writes.append(nxt)
    gaps = [b - a for a, b in itertools.pairwise(writes)]
    return len(writes), min(gaps) if gaps else 0.0


def event_rows(spec: str) -> list[list[str]]:
    return [c for _, c in table_after(section(spec, "## 7. "), "EV")]


def registered_line(env: Env) -> str:
    """`24` §15.5's closed-set line: the first non-blank line after its heading (its definition)."""
    ls = env.lines(env.base, PATHS["24"])
    a, _ = span(ls, "### 15.5 ")
    for ln in ls[a + 1 :] if a >= 0 else []:
        if ln.strip():
            return ln
    return ""


def event_counts(env: Env, spec: str) -> tuple[int, int, int, list[str]]:
    line = registered_line(env)
    reg_names: set[str] = set()
    unreg_audit = 0
    bad: list[str] = []
    for r in event_rows(spec):
        if len(r) < 7:
            continue
        for name in re.findall(r"`([a-z_]+\.[a-z_.]+)`", r[4]):
            reg_names.add(name)
            if f"`{name}`" not in line:
                bad.append(f"{r[0]}: `{name}` is not on `24` §15.5's closed-set line")
        registered = any(f"`{n}`" in line for n in re.findall(r"`([a-z_]+\.[a-z_.]+)`", r[4]))
        if r[3].startswith("audit"):
            for name in re.findall(r"`([a-z_]+\.[a-z_.]+)`", r[3]):
                if f"`{name}`" not in line:
                    unreg_audit += 1
                    if not registered and r[6].strip() in ("", "none", "—"):
                        bad.append(f"{r[0]}: the unregistered audit name `{name}` has no gap")
    return len(event_rows(spec)), len(reg_names), unreg_audit, bad


def token_names(t: Texts) -> list[str]:
    names: list[str] = []
    for _, text in both(t):
        for m in re.finditer(r"`([a-z][a-z0-9.\-]+)`", collapse_copies(text)):
            if TOKEN_NAME.match(m[1]):
                names.append(m[1])
    return list(dict.fromkeys(names))


def walk_items(spec: str) -> int:
    return sum(1 for ln in section(spec, "### 13.2 ").split("\n") if re.match(r"^\d+\. ", ln))


def d04_rows(env: Env, head: str, header0: str) -> list[list[str]]:
    return [c for _, c in table_after(section(env.at_base(PATHS["D04"]), head), header0)]


def width_values(env: Env) -> dict[str, str]:
    cols = d04_rows(env, "### 4.1 ", "Column")
    never = sum(int(r[1]) for r in cols if len(r) > 2 and r[2] == "never" and r[1].isdigit())
    vals = {"WIDTH:d04q3.never100": str(never), "WIDTH:d04q3.never200": str(never * 2)}
    cv = cite_values(env)
    if "CITE:d04.min_px" in cv:
        vals["WIDTH:d04q3.dialog_min"] = cv["CITE:d04.min_px"]
    return vals


def deck_entries(env: Env) -> dict[str, dict[str, object]]:
    ent = derive_deck(env).get("entries", {})
    out: dict[str, dict[str, object]] = {}
    for k, v in ent.items() if isinstance(ent, dict) else []:
        if isinstance(v, dict):
            out[str(k)] = v
    return out


def compute(t: Texts) -> dict[str, str]:
    env = t.env
    vals: dict[str, str] = {"SHA:base": env.base[:10]}
    vals.update(status_values(env))
    vals.update(cite_values(env))
    vals.update(width_values(env))
    vals.update(ahead_values(env))
    vals.update(contrast_values(env, t.review))
    vals.update(cvd_values(env))
    for k in LIFTS:
        h = lift_hash(t, k)
        if h:
            vals[f"HASH:{k}"] = h
    for k, head in (("scr064", "### 4.3 "), ("scr065", "### 5.4 "), ("scr069", "### 6.3 ")):
        vals[f"COUNT:frames.{k}"] = str(frames(env, head))
    vals["COUNT:pngs"] = str(sum(1 for p in env.tree(env.base, IMG_REL)
                                 if re.fullmatch(r"E32-D0[2-5]-.*\.png", p.rsplit("/", 1)[-1])))  # fmt: skip
    vals["COUNT:d04.columns"] = str(len(d04_rows(env, "### 4.1 ", "Column")))
    vals["COUNT:d04.tiles"] = str(len(d04_rows(env, "## 8. ", "Tile key")))
    names = token_names(t)
    shipped = shipped_names(env)
    vals["COUNT:tokens.used"] = str(len(names))
    vals["COUNT:tokens.missing"] = str(sum(n not in shipped for n in names))
    vals["COUNT:walk.items"] = str(walk_items(t.spec))
    d06 = [c for _, c in table_after(section(env.at_base(PATHS["D06"]), "## 8. "), "M")]
    vals["COUNT:motion.rows"] = str(len(d06))
    vals["COUNT:motion.timed"] = str(
        sum(
            bool(re.search(r"infinite|repeat|loop|iteration", " ".join(r), re.IGNORECASE))
            for r in d06
        )
    )
    entries = deck_entries(env)
    vals["COUNT:deck.total"] = str(len(entries))
    vals["COUNT:deck.native_sl"] = str(sum(bool(e.get("native_sl")) for e in entries.values()))
    vals["COUNT:deck.proposed"] = str(sum(e.get("status") == "proposed" for e in entries.values()))
    for p, scr in (("d05", "scr064"), ("d04", "scr065"), ("d03", "scr069")):
        vals[f"COUNT:deck.{scr}"] = str(sum(k.startswith(p + ":") for k in entries))
    fr = f_rows(t.review)
    sev = [r[1].split(" ")[0] for r in fr if len(r) > 1]
    vals["COUNT:f.total"] = str(len(fr))
    for s in ("Blocking", "Major", "Minor", "Info"):
        vals[f"COUNT:f.{s.lower()}"] = str(sev.count(s))
    ar = an_rows(t.review)
    vals["COUNT:an.rows"] = str(len(ar))
    vals["COUNT:an.multi"] = str(sum(region_count(r) != 1 for r in ar))
    w5, g5 = throttle_writes(5.0)
    w2, _ = throttle_writes(2.0)
    vals["SIM:placing.writes5"] = str(w5)
    vals["SIM:placing.writes2"] = str(w2)
    vals["SIM:placing.gap5"] = f"{g5:.1f}"
    n, reg, unreg, _ = event_counts(env, t.spec)
    vals["COUNT:events.rows"] = str(n)
    vals["COUNT:events.registered"] = str(reg)
    vals["COUNT:events.unregistered"] = str(unreg)
    return vals


def region_count(r: list[str]) -> int:
    if len(r) < 4:
        return 0
    cell = r[3]
    return 1 + len(re.findall(r"\s(?:and|plus)\s|;\s", cell))


# ---------------------------------------------------------------------------- the deck


def derive_deck(env: Env) -> dict[str, object]:
    key = "deck:derived"
    if key in env.memo:
        v = env.memo[key]
        return v if isinstance(v, dict) else {}
    entries: dict[str, dict[str, object]] = {}
    for prefix, (src, head, owner) in DECKS.items():
        text = env.at_base(PATHS[src])
        ls = text.split("\n")
        a, _ = span(ls, head)
        block = section(text, head)
        for t in tables(block):
            hdr = t[0][1]
            if not hdr or hdr[0] != "Key":
                continue
            src_col = next((i for i, h in enumerate(hdr) if h == "Source"), None)
            for idx, cells in t[1:]:
                keys = re.findall(r"`([^`]+)`", cells[0]) or [cells[0]]
                srccell = cells[src_col] if src_col is not None and src_col < len(cells) else ""
                proposed = prefix == "d02" or "PROPOSED" in srccell or srccell.startswith("new")
                entry: dict[str, object] = {
                    "names": " · ".join(keys),
                    "text": cells[1].replace("\\|", "|"),
                    "source": f"{src}:{a + idx + 1}",
                    "status": "proposed" if proposed else "reused",
                    "owner": owner if proposed else (srccell or owner),
                    "native_sl": any(NATIVE_KEY.search(k) for k in keys),
                }
                ident, n = f"{prefix}:{keys[0]}", 1
                while ident in entries:  # a first key a parent repeats on a second row
                    n += 1
                    ident = f"{prefix}:{keys[0]}#{n}"
                entries[ident] = entry
            break
    b = bound_entry(env) or {}
    bline = next((i + 1 for i, ln in enumerate(env.lines(env.base, PATHS["E30D06-copy"]))
                  if ln.strip().startswith(f'"{BOUND_KEY}"')), 0)  # fmt: skip
    entries[BOUND_ID] = {
        "names": "e32.sl.required",
        "text": str(b.get("string", "")) if isinstance(b, dict) else "",
        "source": f"E30D06-copy:{bline}",
        "status": "bound",
        "owner": "E30-D02's owner (E30-D02 §14); ruled as A50 item 10",
        "native_sl": True,
        "code": "NATIVE_SL_REQUIRED",
        "code_status": "pending #931",
    }
    out: dict[str, object] = {
        "pack": "E32-D07",
        "version": "v1",
        "base": BASE,
        "note": (
            "The copy deck of the E32-D07 hand-off pack: every row of the four parents' decks "
            "(E32-D02 §3.8, E32-D03 §10, E32-D04 §12, E32-D05 §13) under the id `<parent>:<first "
            "key>` (`#2` on a first key the parent repeats), the row's names, the String cell verbatim, the source row, the status (proposed: the parent's "
            "own proposal, owner the parent; reused: the owner its Source cell names), the "
            "native-SL flag; and the bound `e32.sl.required` (RULED BQ-12). Checked by "
            "docs/design/_tools/e32_d07_handoff_audit.py (G-DECK)."
        ),
        "entries": entries,
    }
    env.memo[key] = out
    return out


def bound_entry(env: Env) -> dict[str, object] | None:
    """E30-D06's ruled entry: `strings` -> the key (its own definition, never a bare word)."""
    data = json.loads(env.at_base(PATHS["E30D06-copy"]))
    strings = data.get("strings", {}) if isinstance(data, dict) else {}
    b = strings.get(BOUND_KEY) if isinstance(strings, dict) else None
    return b if isinstance(b, dict) else None


def bound_problems(env: Env) -> list[str]:
    b = bound_entry(env)
    if b is None:
        return [f"E30-D06's deck has no `{BOUND_KEY}` entry at the base"]
    bad = []
    if b.get("string") != "Every position-opening order requires a stop-loss.":
        bad.append(f"`{BOUND_KEY}` does not read the bound sentence at the base")
    if b.get("status") != "ruled":
        bad.append(f"`{BOUND_KEY}` is not `ruled` at the base: bind it as this pack's proposal")
    return bad


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
    return out


def apply14(base14: str, tick_text: dict[str, str]) -> tuple[str, list[str]]:
    """The merge-base's `14` with the six lines applied by content."""
    ls = base14.split("\n")
    bad: list[str] = []
    for scr, (anchor, half, _) in SCREENS.items():
        ticks = tick_text[scr]
        a = next((i for i, ln in enumerate(ls) if ln.startswith(f"### {scr} ")), -1)
        if a < 0:
            bad.append(f"`14` has no {scr} entry")
            continue
        b = next((i for i in range(a + 1, len(ls)) if ls[i].startswith("### ")), len(ls))
        ck = [i for i in range(a, b) if ls[i].startswith(CHECKLIST_PREFIX)]
        an = [i for i in range(a, b) if ls[i].startswith(anchor)]
        if len(ck) != 1 or len(an) != 1:
            bad.append(f"{scr}: the checklist or the pointer's anchor is not found once in `14`")
            continue
        ls[ck[0]] = CHECKLIST_PREFIX + ticks
        ls.insert(an[0] + 1, POINTER.format(half=half))
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
    return units(t.spec, "spec") + units(t.review, "review") + deck_units(t.deck) + cite_units(t)


def write_pins(us: list[Unit]) -> str:
    head = (
        f"# E32-D07 pins: {len(us)} units (region, location, the normalised text; values cut out, "
        "copied blocks collapsed), the deck entries and the cites' line hashes at the base.\n"
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
    ("CONTRAST:", "G-CONTRAST"), ("PAIR:", "G-CONTRAST"), ("COUNT:contrast", "G-CONTRAST"),
    ("CVD:", "G-CVD"),
    ("COUNT:deck", "G-DECK"),
    ("COUNT:f.", "G-FROWS"),
    ("COUNT:an.", "G-SPEAKER"), ("SIM:", "G-SPEAKER"),
    ("COUNT:events", "G-EVENTS"),
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
    for doc, text in both(t):
        for m in COPY_BLOCK.finditer(text):
            key = m[1]
            body = m[0].split("\n", 1)[1].rsplit("\n", 1)[0].strip("\n")
            if key not in want:
                bad.append(f"{doc}: COPY:{key} has no source")
            elif body != want[key]:
                bad.append(f"{doc}: COPY:{key} differs from its source at the base")
    keys = [m[1] for _, text in both(t) for m in COPY_BLOCK.finditer(text)]
    for k in COPIES:
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


def g_contrast(t: Texts) -> list[Finding]:
    bad = anchor_problems(t, "G-CONTRAST")
    for r in contrast_rows(t.review):
        if len(r) < 9 or r[4] not in BARS:
            bad.append(f"§7.1 row {r[0]}: malformed or an unknown kind")
            continue
        for tok in (r[2].strip("`"), r[3].strip("`")):
            if any(resolve(t.env, th, tok) is None for th in THEMES):
                bad.append(f"§7.1 row {r[0]}: `{tok}` does not resolve in every theme")
    if t.values.get("COUNT:contrast.failing") not in ("0", None):
        bad.append(f"{t.values['COUNT:contrast.failing']} pair(s) below the bar: a finding is due")
    return one("G-CONTRAST", bad)


def g_cvd(t: Texts) -> list[Finding]:
    bad = anchor_problems(t, "G-CVD")
    mats = cvd_matrices(t.env)
    for sim, n in (("grey", 3), ("deut", 9), ("prot", 9), ("trit", 9)):
        if len(mats.get(sim, ())) != n:
            bad.append(f"the {sim} matrix is incomplete")
    sec = section(t.review, "### 7.2 ")
    if "Machado" not in sec or "this pack's matrix, not `cvd_sim.py`'s" not in sec:
        bad.append("§7.2 does not name the tritanopia matrix's source and its label")
    return one("G-CVD", bad)


def g_deck(t: Texts) -> list[Finding]:
    bad = anchor_problems(t, "G-DECK") + bound_problems(t.env)
    try:
        data = json.loads(t.deck)
    except json.JSONDecodeError as e:
        return one("G-DECK", [f"the deck is not JSON: {e}"])
    want = derive_deck(t.env)
    ent = data.get("entries", {}) if isinstance(data, dict) else {}
    wnt = deck_entries(t.env)
    for k, v in ent.items() if isinstance(ent, dict) else []:
        if isinstance(v, dict) and v.get("status") in ("proposed", "bound") and not v.get("owner"):
            bad.append(f"deck {k}: a {v.get('status')} entry with no owner")
        if k not in wnt:
            bad.append(f"deck {k}: no such row in the parents' decks")
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


def g_script(t: Texts) -> list[Finding]:
    bad: list[str] = []
    ent = deck_entries(t.env)
    for doc, text in both(t):
        for m in DECK_REF.finditer(collapse_copies(text)):
            if m[1] not in ent:
                bad.append(f"{doc}: `{m[1]}` is not a deck row")
    steps = set(SCRIPT_ID.findall(section(t.review, "### 6.3 ")))
    for ref in SCRIPT_ID.findall(section(t.spec, "## 10. ")):
        if ref not in steps:
            bad.append(f"pack §10 names {ref}, which REVIEW §6.3 does not hold")
    return one("G-SCRIPT", bad)


# the ruled owner form (RULED BQ-05): a spec or an area, never an agent; one token per comma
OWNER_TOKEN = re.compile(
    r"E\d\d-[DSQTK]\d\d(?:\.\.S\d\d)?(?:'s owner)?"
    r"|(?:SCR|CMP)-\d{3}'s (?:`15` )?owner"
    r"|the script's owner \(E\d\d\)"
)


def owner_problems(fid: str, cell: str) -> list[str]:
    bad: list[str] = []
    for part in re.split(r";\s*|,\s*", cell):
        if part.strip() and not OWNER_TOKEN.fullmatch(part.strip()):
            bad.append(f"{fid}: owner or target {part.strip()!r} is not a spec or an area (R-4)")
    return bad


def story_targets(cell: str) -> set[str]:
    """The E32 stories an owner cell targets, `E32-S05..S07` expanded."""
    out: set[str] = set()
    for a, b in re.findall(r"E32-S(\d\d)(?:\.\.S(\d\d))?", cell):
        for n in range(int(a), int(b or a) + 1):
            out.add(f"E32-S{n:02d}")
    return out


def story_rows(spec: str) -> dict[str, str]:
    """Pack §3.1: story id -> its Binding rows cell."""
    out: dict[str, str] = {}
    for _, c in table_after(section(spec, "### 3.1 "), "Story"):
        m = re.match(r"(E32-S\d\d)", c[0])
        if m and len(c) > 3:
            out[m[1]] = c[3]
    return out


def g_frows(t: Texts) -> list[Finding]:
    bad = anchor_problems(t, "G-FROWS")
    ids: list[str] = []
    for r in f_rows(t.review):
        ids.append(r[0])
        m = re.fullmatch(r"(Blocking|Major|Minor|Info) \((p[0-3])\)", r[1] if len(r) > 1 else "")
        if not m or SEVERITIES[m[1]] != m[2]:
            bad.append(f"{r[0]}: severity {r[1]!r} is not paired with its p-scale")
        if len(r) < 8 or not r[7].strip():
            bad.append(f"{r[0]}: no owner and target")
            continue
        bad += owner_problems(r[0], r[7])
        stories = story_targets(r[7])
        for sid, cell in story_rows(t.spec).items():
            if sid in stories and r[0] not in re.findall(r"\bF-\d\d\b", cell):
                bad.append(f"{r[0]} targets {sid}, whose pack §3.1 row does not bind it")
    if len(set(ids)) != len(ids):
        bad.append("an F id repeats")
    for doc, text in both(t):
        for ref in set(re.findall(r"\bF-\d\d\b", collapse_copies(text))):
            if ref not in ids:
                bad.append(f"{doc} cites {ref}, which §11 does not hold")
    for head in ("### 10.1 ", "### 10.2 "):
        for _, c in (tables(section(t.review, head)) or [[]])[0][1:]:
            v = c[1] if len(c) > 1 else ""
            if not v.startswith(VERDICTS):
                bad.append(f"REVIEW {head.strip()} {c[0][:30]}: verdict {v!r} outside R-3")
            elif v.startswith("at risk") and "interim path" not in c[2] and c[3] in ("", "none"):
                bad.append(f"REVIEW {head.strip()} {c[0][:30]}: `at risk` with no path or row")
    sev = [r[1].split(" ")[0] for r in f_rows(t.review)]
    held = "Blocking" in sev or "Major" in sev
    for doc, text in both(t):
        has = NO_P0.lower() in text.lower()
        if held and has:
            bad.append(f"{doc} says no p0 / p1 while §11 holds one")
        if not held and not has:
            bad.append(f'{doc} does not state "{NO_P0}"')
    return one("G-FROWS", bad)


def g_speaker(t: Texts) -> list[Finding]:
    bad = anchor_problems(t, "G-SPEAKER")
    for r in an_rows(t.review):
        if region_count(r) != 1:
            bad.append(f"{r[0]}: names {region_count(r)} regions (one speaker per event)")
    return one("G-SPEAKER", bad)


def g_events(t: Texts) -> list[Finding]:
    bad = anchor_problems(t, "G-EVENTS")
    if "`sl.modified`" not in registered_line(t.env):
        bad.append("`24` §15.5's closed-set line is not found at the base")
    bad += event_counts(t.env, t.spec)[3]
    return one("G-EVENTS", bad)


def g_ahead(t: Texts) -> list[Finding]:
    bad = anchor_problems(t, "G-AHEAD")
    for k in MARGINS:
        if f"DAYS:margin.{k}" not in t.values:
            bad.append(f"no sprint for {k} in the backlog JSON")
    sec = section(t.spec, "## 11. ")
    if "both readings" not in sec.lower() and "both readings" not in sec:
        bad.append("§11 does not state the rule's two readings")
    return one("G-AHEAD", bad)


def g_openrows(t: Texts) -> list[Finding]:
    bad: list[str] = []
    for _, c in table_after(section(t.spec, "### 12.1 "), "Ids"):
        cites = cites_in(c[1])
        if not cites:
            bad.append(f"{c[0][:30]}: no parent cite")
            continue
        key, a, b, _ = cites[0]
        ls = t.env.lines(t.env.base, PATHS[key])[a - 1 : b]
        leads = {split_row(ln)[0] for ln in ls if ln.lstrip().startswith("|")}
        for lo, hi in re.findall(r"([A-Z][A-Z0-9-]*\d+)\.\.([A-Z][A-Z0-9-]*\d+)", c[0]):
            for ident in (lo, hi):
                if ident not in leads:
                    bad.append(f"{ident} is not a row of `{key}`:{a}-{b}")
    return one("G-OPENROWS", bad)


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
            bad.append("`14` differs from the merge-base with the six lines applied")
    return one("G-UNTOUCHED", bad)


def version_rows(spec: str) -> list[list[str]]:
    return [c for _, c in table_after(section(spec, "## 14. "), "Version")]


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
    for doc, text in both(t):
        heads = [ln for ln in text.split("\n") if ln.startswith("## ") and "The questions" in ln]
        if len(heads) != 1 or STAMP not in heads[0]:
            bad.append(f"{doc}: the questions heading does not carry the ruling stamp")
        if RULING_ID not in text:
            bad.append(f"{doc}: the ruling id {RULING_ID} is not named")
        if "<!-- BQ-" in text:
            bad.append(f"{doc}: a BQ marker is left")
        if OWNER_PENDING not in text.lower():
            bad.append(f'{doc}: "{OWNER_PENDING}" is not stated')
    joined = t.spec + t.review
    for n in range(1, BQ_TOTAL + 1):
        if f"BQ-{n:02d}" not in joined:
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
        for rx, what in ((LOCAL_PATH, "a local path"), (AGENT_NAME, "an agent name"),
                         (URL_OR_HOST, "a URL or host"), (WORDS, "a public-text word")):  # fmt: skip
            m2 = rx.search(text)
            if m2:
                bad.append(f"{doc}: {what} ({m2[0]!r})")
    return one("G-HYGIENE", bad)


TICK_DOCS = {
    "E32-D02": "D02", "E32-D03": "D03", "E32-D04": "D04", "E32-D05": "D05", "E32-D06": "D06",
    "E33-D03": "E33D03", "E32-D07-a11y": "REVIEW",
}  # fmt: skip


def has_section(text: str, n: str) -> bool:
    return bool(re.search(rf"^#{{2,3}} (?:§)?{re.escape(n)}[. ]", text, re.MULTILINE))


def has_board(text: str, n: str) -> bool:
    ls = text.split("\n")
    a, b = span(ls, "## 0. ")
    return a >= 0 and any(re.match(rf"^\|\s*{n}\s*\|", ln) for ln in ls[a:b])


def tick_problems(t: Texts, scr: str, ticks: str) -> list[str]:
    """Every evidence cite of a tick: a `§n` is a heading of the named doc at the base, a board a
    row of its board list, a row id a table row of the doc."""
    bad: list[str] = []
    for raw in ticks.split("[x] ")[1:]:
        last = re.search(r"\(([^()]*)\)\s*$", raw)
        item = raw[: last.start()] if last else raw
        if not last:
            bad.append(f"{scr} '{item.strip()[:30]}': no evidence cite")
            continue
        doc: str | None = None
        first: str | None = None  # boards are the item's first parent's
        for part in re.split(r";\s*|,\s*", last[1]):
            part = part.split(":")[0].strip()
            m = re.match(r"(E3\d-D0\d(?:-a11y)?)\s*(.*)$", part)
            if m:
                doc, part = TICK_DOCS.get(m[1]), m[2].strip()
                first = first or doc
                if doc is None:
                    bad.append(f"{scr}: {m[1]} is not a known evidence source")
                    continue
                if not part:
                    continue
            if doc is None:
                bad.append(f"{scr}: {part!r} names no source")
                continue
            text = doc_text(t, doc)
            secs = re.findall(r"§(\d+(?:\.\d+)?)", part)
            boards = re.findall(r"\b(\d\d)\b", part) if part.startswith(("board", "0")) else []
            rows = re.findall(r"\b(D0\d-[A-Z]\d+)\b", part)
            for n in secs:
                if not has_section(text, n):
                    bad.append(f"{scr} '{item.strip()[:30]}': {doc} has no §{n}")
            for n in boards:
                if not has_board(doc_text(t, first or doc), n):
                    bad.append(f"{scr} '{item.strip()[:30]}': {first} has no board {n}")
            for rid in rows:
                if not re.search(rf"^\|\s*{re.escape(rid)}\s*\|", text, re.MULTILINE):
                    bad.append(f"{scr} '{item.strip()[:30]}': {doc} has no row {rid}")
    return bad


def g_ticks(t: Texts) -> list[Finding]:
    bad: list[str] = []
    for scr, ticks in t.ticks.items():
        if ticks.count("[x]") != 6:
            bad.append(f"{scr}: {ticks.count('[x]')} ticks, six expected")
        bad += tick_problems(t, scr, ticks)
    return one("G-TICKS", bad)


T2_TERMS = ('`aria-disabled="true"`', "`aria-describedby`", "CMP-079 RbacGate", "CMP-019 `lock`",
            "`decorative={false}`", '"Not available"')  # fmt: skip


def g_t2(t: Texts) -> list[Finding]:
    """G-T2.1c / .1d / .6 (the design-spec rules): R-5 states the gated control's attributes, its
    reason node and its wrap; NR-05 carries them; both component lists name CMP-079 and CMP-019."""
    bad: list[str] = []
    m = re.search(r"^- \*\*R-5 .*?(?=^- \*\*|^\S|\Z)", t.review, re.MULTILINE | re.DOTALL)
    r5 = " ".join(m[0].split()) if m else ""
    for term in T2_TERMS:
        if term not in r5:
            bad.append(f"R-5 does not state {term}")
    nr05 = next((ln for ln in t.review.split("\n") if ln.startswith("| NR-05 ")), "")
    for term in ("`aria-describedby`", "CMP-079", "CMP-019 `lock`"):
        if term not in nr05:
            bad.append(f"NR-05 does not carry {term}")
    for doc, text, lead in (("review", t.review, "| companions as the screens bind"),
                            ("spec", t.spec, "| companions ")):  # fmt: skip
        row = next((ln for ln in text.split("\n") if ln.startswith(lead)), "")
        for cmp_id in ("CMP-019", "-079"):
            if cmp_id not in row:
                bad.append(f"{doc}: the component list does not name {cmp_id.lstrip('-')}")
    return one("G-T2", bad)


def g_pins(t: Texts) -> list[Finding]:
    pinned = parse_pins(t.pins)
    if not pinned:
        return one("G-RULED-PIN", [f"{PIN_REL} is empty or missing (run --repin-ruled)"])
    return one("G-RULED-PIN", pin_problems(pinned, all_units(t)))


GATES: tuple[Callable[[Texts], list[Finding]], ...] = (
    g_values, g_lift, g_copy, g_cite, g_version, g_contrast, g_cvd, g_deck, g_script, g_frows,
    g_speaker, g_events, g_ahead, g_openrows, g_untouched, g_ticks, g_t2, g_frozen, g_ruled,
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
    t = Texts(env, read_raw(SPEC_REL), read_raw(REVIEW_REL), deck, pins, read_raw(PLAN14_REL),
              changed_paths(mb), {}, {k: v[2] for k, v in SCREENS.items()})  # fmt: skip
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
    m = re.search(r"<!-- COPY:d06\.s8 -->\n+(.)", t.spec)
    if not m:
        raise SystemExit("self-test: the spec has no COPY:d06.s8 block")
    i = m.start(1)
    return replace(t, spec=t.spec[:i] + ("X" if t.spec[i] != "X" else "Y") + t.spec[i + 1 :])


def head_gone(t: Texts) -> Texts:
    rel = PATHS["D04"]
    ls = t.env.lines(t.env.base, rel)
    ls[442] = ls[442] + " (edited)"
    return with_text(t, HEAD_REF, rel, "\n".join(ls))


def deck_edit(t: Texts) -> Texts:
    data = json.loads(t.deck)
    k = "d05:sl.loosen.refused"
    data["entries"][k]["text"] = data["entries"][k]["text"] + " "
    return replace(t, deck=json.dumps(data, ensure_ascii=False, indent=2) + "\n")


def parent_changed(t: Texts) -> Texts:
    return replace(t, changed=[*(t.changed or []), PATHS["D04"]])


def f05_agent(t: Texts) -> Texts:
    ls = t.review.split("\n")
    i = next(k for k, ln in enumerate(ls) if ln.startswith("| F-05 "))
    cells = ls[i].split("|")
    cells[-2] = " the build agent; E32-S06 "
    ls[i] = "|".join(cells)
    return replace(t, review="\n".join(ls))


def tick_moved(t: Texts) -> Texts:
    """One tick's evidence pointed at a section and a board its parent lacks, in the tool's ticks
    and in `14` alike (so the two still agree and only the evidence is wrong)."""
    old, new = "(E32-D05 §8, §15; board 06)", "(E32-D05 §19, §15; board 16)"
    ticks = dict(t.ticks)
    if old not in ticks["SCR-064"] or old not in t.plan14:
        raise SystemExit("self-test: the SCR-064 tick evidence is not found")
    ticks["SCR-064"] = ticks["SCR-064"].replace(old, new)
    return replace(t, ticks=ticks, plan14=t.plan14.replace(old, new))


def merged_and_edited(t: Texts) -> Texts:
    """A merge-base that already holds this pack and its `14` lines (a simulated later PR)."""
    sim = "simulated-merge-base"
    memo = dict(t.env.memo)
    memo[f"show:{sim}:{SPEC_REL}"] = t.spec
    memo[f"show:{sim}:{PLAN14_REL}"] = t.plan14
    t2 = replace(t, env=Env(t.env.base, sim, memo))
    row = next(ln for ln in t.spec.split("\n") if ln.startswith("| v1 ") and "loosen flow" in ln)
    return replace(t2, spec=t.spec.replace(row, row.replace("loosen flow", "loosen path"), 1))


MUTATIONS: tuple[Mutation, ...] = (
    Mutation("G-VALUES", "type a frame count by hand", anchor_edit("COUNT:frames.scr064", "99")),
    Mutation("G-LIFT", "alter a lifted block's hash", anchor_edit("HASH:d06.s3_6", "000000000000")),
    Mutation("G-COPY", "change one byte inside the copied D06 §8", copy_edit),
    Mutation("G-CITE", "point a cite past the end of its file",
             subst("(`D04`:443; inbound item 3)", "(`D04`:99999; inbound item 3)", "review")),
    Mutation("G-VERSION", "edit D04-Q3's line at origin/main", head_gone),
    Mutation("G-CONTRAST", "type a contrast ratio by hand",
             anchor_edit("CONTRAST:ct01.dark", "9.99", "review")),
    Mutation("G-CVD", "type a simulated ratio by hand",
             anchor_edit("CVD:v1.grey.dark", "9.99", "review")),
    Mutation("G-DECK", "alter one deck string", deck_edit),
    Mutation("G-SCRIPT", "cite a deck row that does not exist",
             subst("`d05:sl.loosen.refused` once", "`d05:sl.loosen.refusedx` once", "review")),
    Mutation("G-FROWS", "pair Info with p2",
             subst("| F-11 | Info (p3) ", "| F-11 | Info (p2) ", "review")),
    Mutation("G-FROWS", "give F-05 an agent for its owner", f05_agent),
    Mutation("G-FROWS", "drop F-04 from S05's binding rows", subst("| F-02, F-03, F-04, F-10; HG-1",
                                                                   "| F-02, F-03, F-10; HG-1")),
    Mutation("G-SPEAKER", "give one announcement two regions",
             subst("| AN-01 | a read-out or readout after an edit                      | 064, 065, 069 | dialog `status` (1) ",
                   "| AN-01 | a read-out or readout after an edit                      | 064, 065, 069 | dialog `status` and the shell (1) ",
                   "review")),
    Mutation("G-EVENTS", "name an action the closed set does not hold",
             subst("| `sl.modified`  ", "| `sl.modify`    ")),
    Mutation("G-AHEAD", "type a margin by hand", anchor_edit("DAYS:margin.s05", "1")),
    Mutation("G-OPENROWS", "widen a parent's range past its last row",
             subst("| G-1..G-23 ", "| G-1..G-24 ")),
    Mutation("G-UNTOUCHED", "edit a parent in the same tree", parent_changed),
    Mutation("G-TICKS", "point a tick's evidence at a missing section and board (tool and 14)",
             tick_moved),
    Mutation("G-T2", "drop the reason node's `aria-describedby` link from R-5",
             subst("and an `aria-describedby` link to its reason", "and a link to its reason", "review")),
    Mutation("G-FROZEN", "post-merge: edit a merged v1 row", merged_and_edited),
    Mutation("G-RULED", "drop the stamp's date from the review's questions heading",
             subst("## 1. The questions BQ-01..BQ-19 — RULED (orchestrator, 2026-10-31,",
                   "## 1. The questions BQ-01..BQ-19 — RULED (orchestrator,", "review")),
    Mutation("G-HYGIENE", "write a closing keyword outside a code span",
             subst("The PR body carries `Closes #927`.", "The PR body carries Closes #927.")),
    Mutation("G-RULED-PIN", "re-word a pinned sentence no other gate reads",
             subst("Nothing on these screens is built: the pack is the build's input.",
                   "Nothing on these screens is built yet: the pack is the build's input.")),
)  # fmt: skip


def digest(t: Texts) -> str:
    return hashlib.sha256(
        f"{t.spec}\0{t.review}\0{t.deck}\0{t.pins}\0{t.plan14}".encode()
    ).hexdigest()


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
    ap.add_argument("--fill", action="store_true", help="fill the values, the copies and the deck")
    a = ap.parse_args(argv)
    if a.self_test:
        ok, lines = selftest()
        print("\n".join(lines))
        return 0 if ok else 1
    t = load()
    if a.repin_ruled:
        for doc, text in both(t):
            if unfilled(text):
                print(f"refused: {doc} has an unfilled placeholder (run --check --fill)")
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
        t = replace(t, values=compute(t))
        missing: list[str] = []
        for _ in range(2):  # the review's hashes settle once its own values are filled
            spec, m1 = fill(t.spec, t.values, copies)
            review, m2 = fill(t.review, t.values, copies)
            write_text(SPEC_REL, spec)
            write_text(REVIEW_REL, review)
            t = replace(t, spec=spec, review=review)
            t = replace(t, values=compute(t))
            missing = m1 + m2
        for m in missing:
            print(f"unfilled: {m}")
        t = load()
    timings: dict[str, float] = {}
    found = audit(t, timings)
    fails = [f for f in found if f.level == "FAIL"]
    if a.json:
        dump = {"base": t.env.base, "merge_base": t.env.mb, "post_merge": post_merge(t),
                "values": t.values,
                "findings": [{"level": f.level, "gate": f.gate, "msg": f.msg} for f in found]}  # fmt: skip
        print(json.dumps(dump, ensure_ascii=False, indent=2, sort_keys=True))
    else:
        for f in found:
            print(ascii_line(f"{f.level} {f.gate}: {f.msg}"))
        warns = sum(f.level == "WARN" for f in found)
        notes = sum(f.level == "NOTE" for f in found)
        mode = "post-merge" if post_merge(t) else "PR-1"
        print(
            f"{len(fails)} FAIL / {warns} WARN / {notes} NOTE ({len(GATES) + 1} gates, {mode} mode)"
        )
    return 1 if fails else 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
