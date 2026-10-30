#!/usr/bin/env python3
"""E15-D14 (#368) audit: the motion spec for docking, layout transitions, workspace switching and
reduced motion.

Standalone, offline, stdlib only; it runs under `python3 -I`. It reads AS TEXT at the pinned base
(`git merge-base HEAD origin/main`, via `git show BASE:<path>`) the plan texts (`02`, `05`, `11`,
`14`, `15`, `16`), the constitution, the design rule file and the design README, the merged E15
design docs (D02 ... D09, D13, D15 and the hand-offs), the E15 usage document, E05-D03 (the motion
vocabulary), the primitive token JSON, the sprint calendar and the E15 backlog JSON — every input
is merged (E15-D13's pack with #5055, its `15` rows with #367's PR 2, #5073); then the pack
(`E15-D14.md`) and the pins from the working tree. Every source it normalises is cached once per
(revision, path). Token values (ms, cubic-bezier) and E05-D03's enter / exit pairs are read from
their files, never typed; every number the spec carries is a placeholder the tool fills and
re-derives (the merge shas of #5055 and #5073 among them, from `git log`).

Gates (one mutation each in `--self-test`; the pins gate besides):
  (a) G-TABLE     every §2 inventory row well-formed: twelve cells, a verdict from the vocabulary
                  (cut / fade / follow / routed), a content-box word, a source; §R lists BQ-01 ...
                  BQ-22 once each with a status; every "RULED BQ-nn" stamp names a listed BQ.
  (b) G-PROPERTY  the animated property is `opacity`, `transform` or `none` — never a box property;
                  a cut is `none`, a fade is `opacity`, a follow is `transform` or a layout write;
                  no fade changes a content box per pointer frame.
  (c) G-TOKEN     every `motion.*` name in the pack is one of the shipped primitives; the ms and
                  easing values are the token file's; `motion.duration.normal` appears in §2 only on
                  a row bound to the dialog scrim (B-4) and in a §C line only beside row 2a;
                  `motion.duration.slow` on no §2, §3 or §C row ("no dock transition is longer than
                  `fast`").
  (d) G-REDUCE    every §2 reduce cell is `none` (E05-D03 §3); §5 carries one proof row per
                  inventory row.
  (e) G-BINDING   every fade names a §3 binding row, every follow its D04 rule, every routed row
                  its candidate or its owner's cited binding (the rail: E10-D04 T-01 / T-02); every
                  binding row names an E05-D03 row or a candidate row; the
                  pairs in §3 equal E05-D03's at the base, and the binding rule's premise holds
                  there (rows 1 and 4a share the enter pair; rows 2a, 2b, 3 and 4a the exit pair).
  (f) G-SAFETY    every §4 never-animates row is a cut in both modes; no inventory row that names a
                  safety carrier (the badge, the arm state, the tray, a tab, a banner, a chip, the
                  reason pill, the `alertdialog` ...) animates — an `alertdialog` row only when its
                  safe and reduce cells say the card is at frame 0; every fade on CMP-080 (§2, §3,
                  §6.3's mount row, a §C line) states the header exclusion — "outside the fading
                  layer" — or I-15's exemption, which is I-15's alone and holds one way (its binding
                  the exit pair B-2 alone; the restore row a cut); a non-cut row whose carrier cell
                  names a safety carrier puts it at frame 0 or outside the fading layer; §4 states
                  the rule; the outline areas are the tool's.
  (g) G-STRING    every §5 quoted string equals its source line's text at the base, verbatim.
  (h) G-CITE      every cite in range, non-blank and content-pinned (a moved cite is a WARN until
                  `--repin-ruled` records it or the spec re-points it; an edited one a FAIL).
  (i) G-VERSION   values, never a sha: the calendar's sprint-1 start and length and the sprint
                  fields at `origin/main` equal the base; each cite's content at the base stands at
                  `origin/main`, re-found inside the cited entry alone (moved once = WARN; gone or
                  ambiguous = FAIL).
  (j) G-AROW      every §C row well-formed; an insert's anchor is its entry's last bullet in `15`
                  at the base, a replace's or a confirmation's Old the Motion line #5073 wrote,
                  standing once inside its entry at the Field's number (PR-1 mode; by content alone
                  in PR-2 mode); Via names #5073 for those and `—` for a new line; every New is one
                  `- **Motion spec**:` line in `15`:523's form, marked PROPOSED — except the one
                  ruled replacement (Via `#2701`, the owner's ledger): its Old is the CMP-212
                  E40-D02 line as it stands at the base, its New that line with the ruled span
                  alone swapped (A47's two spans, typed once below as RULED_A47), its From carrying
                  A47's RULED stamp.
  (k) G-HYGIENE   placeholders filled and re-derived, no `{{` left, no closing keyword, no local
                  path, no agent name, no URL or host; the tree against the merge-base: PR 1 may
                  differ only in the pack's three files; PR 2 (`15` changed, the spec and the tool
                  unchanged) must equal the merge-base with §C applied exactly, every Old found by
                  content inside its entry (so PR 2 cannot open over a line a later PR edited), and
                  may differ in the pins alone, by recorded cite moves only (BQ-03), its `SHA:`
                  anchors PR 1's record (`SHA:BASE` an ancestor of the merge-base, the rest not
                  re-derived: PR 2's merge-base can never equal PR 1's); the §M list equal to the
                  tool's.
  G-RULED-PIN     a default-deny pin set over every unit of the pack (`e15_d14_ruled_pins.txt`);
                  `--repin-ruled` is the only writer.

Usage (from the repo root):
  python3 -I docs/design/_tools/e15_d14_motion_audit.py --check [--json] [--fill]
  python3 -I docs/design/_tools/e15_d14_motion_audit.py --self-test
  python3 -I docs/design/_tools/e15_d14_motion_audit.py --repin-ruled
  python3 -I docs/design/_tools/e15_d14_motion_audit.py --a-rows
Exit 0 = no FAIL; 1 = at least one FAIL. `--check` ends with the per-gate timings; the `--json` dump
carries values, findings and timings only.
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
from collections.abc import Callable
from dataclasses import dataclass, replace
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
SPEC_REL = "docs/design/E15/E15-D14.md"
PINS_REL = "docs/design/_tools/e15_d14_ruled_pins.txt"
TOOL_REL = "docs/design/_tools/e15_d14_motion_audit.py"
OWN_PATHS = (SPEC_REL, PINS_REL, TOOL_REL)
PACK_TEXTS = (SPEC_REL, TOOL_REL)  # PR 2 may touch neither (BQ-03)
CAT_REL = "docs/plan/15-component-catalogue.md"
TOK_REL = "packages/ui/tokens/primitives.tokens.json"
CAL_REL = "docs/plan/backlog/_tools/calendar_cv.py"
E15J_REL = "docs/plan/backlog/E15.json"
HEAD_REF = "origin/main"
ISSUE = "368"
# E15-D13's pack (PR 1 of 4 for #367) and its `15` rows (PR 2 of 4): both merged before the base;
# their merge shas are read from `git log`, never typed
PR_NUMBER = 5055
PR2_NUMBER = 5073
PATHS: dict[str, str] = {
    "02": "docs/plan/02-definition-of-ready-done.md",
    "05": "docs/plan/05-accessibility-standard.md",
    "11": "docs/plan/11-user-stories.md",
    "14": "docs/plan/14-screens-catalogue.md",
    "15": CAT_REL,
    "16": "docs/plan/16-design-system-brief.md",
    "CONST": "CONSTITUTION.md",
    "RULE": ".claude/rules/32-design-specs.md",
    "README": "docs/design/README.md",
    "TOK": TOK_REL,
    "CAL": CAL_REL,
    "E05D03": "docs/design/E05/E05-D03.md",
    "E10D04": "docs/design/E10/E10-D04.md",
    "D02": "docs/design/E15/E15-D02.md",
    "D03": "docs/design/E15/E15-D03.md",
    "D03H": "docs/design/E15/E15-D03-handoff.md",
    "D04": "docs/design/E15/E15-D04.md",
    "D04H": "docs/design/E15/E15-D04-handoff.md",
    "D05": "docs/design/E15/E15-D05.md",
    "D05H": "docs/design/E15/E15-D05-handoff.md",
    "D06": "docs/design/E15/E15-D06.md",
    "D06H": "docs/design/E15/E15-D06-handoff.md",
    "D07": "docs/design/E15/E15-D07.md",
    "D07H": "docs/design/E15/E15-D07-handoff.md",
    "D08": "docs/design/E15/E15-D08.md",
    "D09": "docs/design/E15/E15-D09.md",
    "D15": "docs/design/E15/E15-D15.md",
    "D13": "docs/design/E15/E15-D13.md",
    "USAGE": "docs/design/specs/e15-design-system-contributions.md",
}
SHA_INPUTS: dict[str, tuple[str, ...]] = {
    "E05D03": (PATHS["E05D03"],),
    "E10D04": (PATHS["E10D04"],),
    "D02": (PATHS["D02"],),
    "D03": (PATHS["D03"], PATHS["D03H"]),
    "D04": (PATHS["D04"], PATHS["D04H"]),
    "D05": (PATHS["D05"], PATHS["D05H"]),
    "D15": (PATHS["D15"],),
    "15": (CAT_REL,),
    "14": (PATHS["14"],),
    "16": (PATHS["16"],),
    "TOK": (TOK_REL,),
    "CAL": (CAL_REL,),
}
VERDICTS = ("cut", "fade", "follow", "routed")
PROPERTIES = ("`none`", "`opacity`", "`transform`", "`opacity`, `transform`", "—")
BOX_WORDS = ("never", "once", "per pointer frame")
BOX_PROPERTY = re.compile(
    r"\b(width|height|left|top|right|bottom|inset|flex|grid|size)\b", re.IGNORECASE
)
# an inventory row naming one of these carriers in its transition or surface must be a cut (§4);
# whole words, so "tab" never matches "WorkspaceTabStrip" or "tabify"
SAFETY_WORDS = ("focus frame", "env badge", "environment badge", "CMP-075", "arm state", "CMP-229",
                "compact view", "status words", "dirty", "hatch", "T2 lock", "error line", "banner",
                "chip", "reason pill", "`alertdialog`", "tray", "tab")  # fmt: skip
# the one safety word a fade may carry: a dialog whose scrim fades while its card is a cut, stated
# in both motion cells
DIALOG_WORD = "`alertdialog`"
CARD_AT_0 = re.compile(r"\bthe card\b.*\bat frame 0\b")
# every fade on CMP-080 states the header exclusion (the badge and the arm state paint at frame 0
# outside the fading body layer) — or I-15's exemption (beneath an opaque maximised panel, C-p)
PANEL_ID = "CMP-080"
HEADER_OUT = "outside the fading layer"
EXEMPT = "not perceivable (C-p"
EXEMPT_ROW = "I-15"  # the one row that may write EXEMPT; its binding is the exit pair alone
RESTORE_ROW = "I-16"  # the restore: a cut, never a fade-in of the panels beneath
CARRIER_AT_0 = re.compile(r"\bat frame 0\b")
DISPOSITIONS = ("applied-as-amended", "applied", "routed", "held", "confirmed", "superseded by #")
E05_ROWS = ("1", "2a", "4a")  # the rows the §3 pairs are read from
# the sprint values §10 anchors (key in the backlog JSON -> anchor id)
SPRINT_KEYS = {
    "E15-D14": "d14", "E15-D16": "d16", "E15-T02": "t02", "E15-S01": "s01", "E15-S02": "s02",
    "E15-S03": "s03", "E15-S04": "s04", "E15-S06": "s06", "E15-S08": "s08", "E15-Q02": "q02",
    "E15-Q04": "q04", "E15-Q06": "q06",
}  # fmt: skip
CONSUMERS = ("t02", "s01", "s02", "s03", "s04")
PANELS = ("chart", "dom", "tape", "positions")
NEW_LINE_HEAD = "- **Motion spec**: [E15-D14.md](../design/E15/E15-D14.md) (E15-D14"
# the one ruled replacement in §C (C-e): #2701's ledger row A47 (comment 6524798809) over the
# CMP-212 E40-D02 line — the Via, the span the line loses, the span it gains, the From's stamp
RULED_VIA = "#2701"
RULED_A47 = (
    "fade only under motion-reduce (X-9, X-20)",
    (
        "none under motion-reduce — the end state at frame 0 (E05-D03 §2 row 4a, `16` §7 "
        '"reduce → instant"; E15-D14 §5 C-e)'
    ),
    "RULED (orchestrator, 2026-10-30, #2701 ledger row A47 — 6524798809)",
)

PLACEHOLDER = re.compile(r"\{\{([A-Z0-9]+:[^{}]+?)\}\}")
# a value never starts with "(": a parenthesis in front of an anchored number stays in the text
ANCHORED = re.compile(r"(`[^`\n]*`|[^\s<|`(]+)<!--=([A-Z0-9]+:[^>]+?)-->")
CODE = re.compile(r"`[^`\n]*`")
HEADING = re.compile(r"^(#{1,6}) (.+)$")
RULE = re.compile(r"^\s*\|?\s*:?-{3,}")
MOTION_NAME = re.compile(r"`(motion\.[a-z.]+)`")
CITE = re.compile(
    r"(?:`([0-9]{2})`|`?\b(D0[2-9]H?|D1[35]|USAGE|E05D03|E10D04|CAL|CONST|RULE|README|TOK)`?)"
    r":(\d+)(?:[–-](\d+))?"
)
FIELD_BASE = re.compile(r"`15`:(\d+)")
CLOSING = re.compile(r"\b(?:close[sd]?|fix(?:e[sd])?|resolve[sd]?)\s+#\d+", re.IGNORECASE)
# assembled, so the deny pattern never spells the strings it refuses
LOCAL_PATH = re.compile("/" + "home/|/Users/|[A-Za-z]:\\\\|\\bwt-" + "notes\\b")
AGENT_NAME = re.compile(r"\b[a-z]{2,4}-worker-\d\b")
URL_OR_HOST = re.compile(r"https?://|penpot\.[a-z]|team-id=|file-id=", re.IGNORECASE)
FULL_STOP = re.compile(r"(?<=[.!?])\s+(?=[*`\"(A-Z0-9§])")


# ---------------------------------------------------------------------------- git and caches


def git_raw(*args: str) -> str | None:
    try:
        r = subprocess.run(["git", "-C", str(ROOT), *args], capture_output=True, check=False)
    except OSError:
        return None
    return r.stdout.decode("utf-8", "surrogateescape") if r.returncode == 0 else None


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


def pin_norm(text: str) -> str:
    return " ".join(text.split())


def line_hash(first: str, last: str) -> str:
    return hashlib.sha256((pin_norm(first) + "\n" + pin_norm(last)).encode()).hexdigest()[:12]


@dataclass
class Env:
    base: str
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
        key = f"lines:{rev}:{rel}"
        if key not in self.memo:
            t = self.show(rev, rel)
            self.memo[key] = t.split("\n") if t is not None else []
        v = self.memo[key]
        return v if isinstance(v, list) else []

    def hash_index(self, rev: str, rel: str, span: int) -> dict[str, list[int]]:
        """Content hash of (line i, line i + span) -> the 1-based line numbers i; cached once."""
        key = f"hidx:{rev}:{rel}:{span}"
        if key not in self.memo:
            ls = self.lines(rev, rel)
            idx: dict[str, list[int]] = {}
            for i in range(len(ls) - span):
                if ls[i].strip():
                    idx.setdefault(line_hash(ls[i], ls[i + span]), []).append(i + 1)
            self.memo[key] = idx
        v = self.memo[key]
        return v if isinstance(v, dict) else {}

    def log_subjects(self, rel: str) -> str:
        key = f"log:{rel}"
        if key not in self.memo:
            self.memo[key] = git_raw("log", "--format=%s", HEAD_REF, "--", rel) or ""
        v = self.memo[key]
        return v if isinstance(v, str) else ""

    def pr_sha(self, number: int) -> str:
        """The abbreviated sha of the squash merge of PR `number` on the base's history: the
        earliest commit whose SUBJECT ends with `(#number)` — `--grep` alone also matches a later
        PR's body that names the number (#5071's names #5073) — or zeros when none does."""
        key = f"prsha:{number}"
        if key not in self.memo:
            out = git_raw(
                "log", "--reverse", "--format=%h%x09%s", "--abbrev=10", "--fixed-strings",
                f"--grep=(#{number})", self.base,
            )  # fmt: skip
            sha = "0000000000"
            for ln in (out or "").split("\n"):
                h, _, subject = ln.partition("\t")
                if subject.rstrip().endswith(f"(#{number})"):
                    sha = h
                    break
            self.memo[key] = sha
        v = self.memo[key]
        return v if isinstance(v, str) else "0000000000"


def read_raw(rel: str) -> str:
    with open(ROOT / rel, encoding="utf-8", newline="") as f:
        return f.read()


def write_text(rel: str, text: str) -> None:
    with open(ROOT / rel, "w", encoding="utf-8", newline="") as f:
        f.write(text)


# ---------------------------------------------------------------------------- text helpers


def lines_of(text: str) -> list[str]:
    return text.split("\n")


def split_row(line: str) -> list[str]:
    body = line.strip().removeprefix("|")
    if body.endswith("|") and not body.endswith("\\|"):
        body = body[:-1]
    return [c.strip() for c in re.split(r"(?<!\\)\|", body)]


def unescape(cell: str) -> str:
    return cell.replace("\\|", "|")


def tables(block: str) -> list[list[list[str]]]:
    out: list[list[list[str]]] = []
    cur: list[list[str]] = []
    for ln in lines_of(block):
        if ln.lstrip().startswith("|"):
            if RULE.match(ln):
                continue
            cur.append(split_row(ln))
        elif cur:
            out.append(cur)
            cur = []
    if cur:
        out.append(cur)
    return out


def table_after(block: str, header0: str) -> list[list[str]]:
    for t in tables(block):
        if t and t[0] and t[0][0] == header0:
            return t[1:]
    return []


def section(text: str, head_prefix: str) -> str:
    ls = lines_of(text)
    for i, ln in enumerate(ls):
        m = HEADING.match(ln)
        if m and (ln.startswith(head_prefix + " ") or ln == head_prefix):
            level = len(m[1])
            j = i + 1
            while j < len(ls):
                m2 = HEADING.match(ls[j])
                if m2 and len(m2[1]) <= level:
                    break
                j += 1
            return "\n".join(ls[i:j])
    return ""


def without_code(text: str) -> str:
    return CODE.sub("`…`", text)


def strip_anchors(text: str) -> str:
    return re.sub(r"<!--=[A-Z0-9]+:[^>]+?-->", "", text)


def cites_in(text: str) -> list[tuple[str, int, int]]:
    out = []
    for ln in lines_of(text):
        for m in CITE.finditer(ln):
            key = m[1] or m[2]
            if key in PATHS:
                a = int(m[3])
                out.append((key, a, int(m[4]) if m[4] else a))
    return out


def label_of(key: str, a: int, b: int) -> str:
    return f"{key}:{a}" if a == b else f"{key}:{a}–{b}"


# ---------------------------------------------------------------------------- tokens and E05-D03


def token_json(env: Env) -> dict[str, dict[str, object]]:
    key = "tok:json"
    if key not in env.memo:
        env.memo[key] = json.loads(env.at_base(TOK_REL))
    v = env.memo[key]
    return v if isinstance(v, dict) else {}


def shipped_motion(env: Env) -> dict[str, str]:
    """`motion.*` primitive -> its value as a whitespace-free string (`100ms`; `[0.2, 0, 0, 1]`
    kept with its spaces, filled as one code span)."""
    out: dict[str, str] = {}
    for name, entry in token_json(env).items():
        if not name.startswith("motion.") or not isinstance(entry, dict):
            continue
        val = entry.get("$value")
        if isinstance(val, list):
            out[name] = "[" + ", ".join(str(x) for x in val) + "]"
        else:
            out[name] = str(val)
    return out


def e05_table(env: Env) -> dict[str, list[str]]:
    """E05-D03 §2's rows by their `#` cell (the cells unescaped), read at the base."""
    key = "e05:table"
    if key not in env.memo:
        rows = table_after(section(env.at_base(PATHS["E05D03"]), "## 2."), "#")
        env.memo[key] = {r[0]: r for r in rows if r and len(r) >= 10}
    v = env.memo[key]
    return v if isinstance(v, dict) else {}


def pair_of(cell: str) -> tuple[str, str] | None:
    """(duration, easing) — the first `motion.duration.*` and `motion.easing.*` of a cell."""
    names = MOTION_NAME.findall(cell)
    d = next((n for n in names if n.startswith("motion.duration.")), None)
    e = next((n for n in names if n.startswith("motion.easing.")), None)
    return (d, e) if d and e else None


def e05_values(env: Env) -> dict[str, str]:
    vals: dict[str, str] = {}
    for rid in E05_ROWS:
        row = e05_table(env).get(rid)
        if not row:
            continue
        for side, idx in (("enter", 5), ("exit", 6)):
            p = pair_of(row[idx])
            if p:
                vals[f"E05:{rid}.{side}.duration"] = f"`{p[0]}`"
                vals[f"E05:{rid}.{side}.easing"] = f"`{p[1]}`"
    return vals


def token_values(env: Env) -> dict[str, str]:
    vals: dict[str, str] = {}
    for name, val in shipped_motion(env).items():
        short = name.rsplit(".", 1)[-1]
        if name.startswith("motion.duration."):
            vals[f"TOKMS:{short}"] = val
        elif name.startswith("motion.easing."):
            vals[f"EASE:{short}"] = f"`{val}`"
    return vals


# ---------------------------------------------------------------------------- cites and pins


# (the line hash, the recorded move, the hash of the entry heading it sits under)
CitePin = tuple[str, tuple[int, int] | None, str]


def heading_hash(heading: str) -> str:
    return hashlib.sha256(pin_norm(heading).encode()).hexdigest()[:12]


@dataclass(frozen=True)
class Texts:
    env: Env
    spec: str
    pins: str
    cat15: str
    changed: list[str] | None
    values: dict[str, str]


def cite_pins(pins: str) -> dict[str, CitePin]:
    out: dict[str, CitePin] = {}
    for ln in pins.split("\n"):
        parts = ln.split("\t")
        if len(parts) >= 3 and parts[0] == "cite":
            at = None
            hh = ""
            for extra in parts[3:]:
                m = re.fullmatch(r"@(\d+)(?:–(\d+))?", extra)
                if m:
                    at = (int(m[1]), int(m[2]) if m[2] else int(m[1]))
                elif extra.startswith("h:"):
                    hh = extra[2:]
            out[parts[1]] = (parts[2], at, hh)
    return out


def heading_before(ls: list[str], n: int) -> str:
    for i in range(min(n, len(ls)) - 1, -1, -1):
        if ls[i].startswith("#"):
            return ls[i]
    return ""


def found_under(env: Env, rev: str, rel: str, h: str, span: int, hh: str) -> list[int]:
    """The 1-based lines at `rev` whose content hashes to `h`, kept only under the entry heading
    whose hash is `hh` (the heading recorded with the pin, so a re-find never crosses into another
    entry even when the entry itself moved); every hit when no heading is recorded."""
    ls = env.lines(rev, rel)
    hits = env.hash_index(rev, rel, span).get(h, [])
    return [n for n in hits if not hh or heading_hash(heading_before(ls, n)) == hh]


def resolve_cite(t: Texts, key: str, a: int, b: int) -> tuple[int, int, str]:
    """The effective lines of a cite and its status: `ok`, `recorded` (moved, the move recorded
    in the pins), `moved` (found by content once, inside the cited entry), `gone`, `unpinned` or
    `range`."""
    rev = t.env.base
    ls = t.env.lines(rev, PATHS[key])
    if not (0 < a <= b <= len(ls)):
        return a, b, "range"
    pinned = cite_pins(t.pins).get(label_of(key, a, b))
    here = line_hash(ls[a - 1], ls[b - 1])
    if pinned is None:
        return a, b, "unpinned"
    h, at, hh = pinned
    if h == here:
        return a, b, "ok"
    if at and 0 < at[0] <= at[1] <= len(ls) and line_hash(ls[at[0] - 1], ls[at[1] - 1]) == h:
        return at[0], at[1], "recorded"
    found = found_under(t.env, rev, PATHS[key], h, b - a, hh)
    if len(found) == 1:
        return found[0], found[0] + (b - a), "moved"
    return a, b, "gone"


def cite_line(t: Texts, key: str, n: int) -> str:
    """The cited line's text (content-resolved) at the base."""
    a, _, status = resolve_cite(t, key, n, n)
    ls = t.env.lines(t.env.base, PATHS[key])
    return ls[a - 1] if status != "range" and 0 < a <= len(ls) else ""


def all_cites(t: Texts) -> list[tuple[str, int, int]]:
    """Every distinct cite of the pack, the §C rows' Field cells excepted (G-AROW verifies those
    lines itself, by content, against the base or #5055's head)."""
    seen: list[tuple[str, int, int]] = []
    text = "\n".join(ln for ln in lines_of(t.spec) if not ln.startswith("| A-"))
    for c in cites_in(text):
        if c not in seen:
            seen.append(c)
    return seen


def cite_problems(t: Texts) -> tuple[list[str], list[str]]:
    """(FAILs, WARNs) over every distinct cite: range, blank, unpinned, gone, moved."""
    bad: list[str] = []
    warn: list[str] = []
    for key, a, b in all_cites(t):
        label = label_of(key, a, b)
        a2, b2, status = resolve_cite(t, key, a, b)
        ls = t.env.lines(t.env.base, PATHS[key])
        if status == "range":
            bad.append(f"{label} is past the end of the file ({len(ls)} lines)")
            continue
        for n in (a2, b2):
            if not ls[n - 1].strip():
                bad.append(f"{label} is a blank line")
        if status == "unpinned":
            bad.append(f"cite {label} is unpinned: verify it by content, then --repin-ruled")
        elif status == "gone":
            bad.append(
                f"cite {label}: the pinned content stands nowhere once inside its entry "
                "(edited, or ambiguous)"
            )
        elif status == "moved":
            warn.append(
                f"cite {label}: the pinned content moved to :{a2} — re-point it (PR 1) or "
                "--repin-ruled records the move (PR 2)"
            )
    return bad, warn


# ---------------------------------------------------------------------------- the pack's rows


def sec(spec: str, prefix: str) -> str:
    return section(spec, prefix)


def rows_with(spec: str, prefix: str, header0: str, idp: str) -> list[list[str]]:
    return [r for r in table_after(sec(spec, prefix), header0) if r and r[0].startswith(idp)]


def inv_rows(spec: str) -> list[list[str]]:
    return rows_with(spec, "## 2.", "I", "I-")


def b_rows(spec: str) -> list[list[str]]:
    return rows_with(spec, "## 3.", "B", "B-")


def n_rows(spec: str) -> list[list[str]]:
    return rows_with(spec, "## 4.", "N", "N-")


def p_rows(spec: str) -> list[list[str]]:
    return rows_with(spec, "## 5.", "P", "P-")


def s_rows(spec: str) -> list[list[str]]:
    return rows_with(spec, "## 5.", "S", "S-")


def ledger_rows(spec: str) -> list[list[str]]:
    return rows_with(spec, "## 9.", "L", "L-")


def cr_rows(spec: str) -> list[list[str]]:
    return rows_with(spec, "## 9.", "CR", "CR-")


def c_rows(spec: str) -> list[list[str]]:
    return rows_with(spec, "## 9.", "C", "C-")


def g_rows(spec: str) -> list[list[str]]:
    return rows_with(spec, "## 9.", "G", "G-")


def bq_rows(spec: str) -> list[list[str]]:
    return rows_with(spec, "## R.", "BQ", "BQ-")


def a_rows(spec: str) -> list[list[str]]:
    return rows_with(spec, "## §C", "A", "A-")


def consumer_rows(spec: str) -> list[list[str]]:
    return rows_with(spec, "## 10.", "Consumer", "E15-")


def walk_items(spec: str) -> list[str]:
    return [ln for ln in lines_of(sec(spec, "## 12.")) if re.match(r"^\s+\d+\. ", ln)]


def verdict_of(cell: str) -> str:
    return cell.split(" ", 1)[0].strip()


def disposition(cell: str) -> str:
    for d in DISPOSITIONS:
        if cell.startswith(d):
            return d
    return ""


def a_row_line(r: list[str]) -> int | None:
    """The `15` line (at the base) a §C row's Field cell names."""
    m = FIELD_BASE.fullmatch(r[2])
    return int(m[1]) if m else None


def entry_id(target: str) -> str:
    m = re.match(r"(CMP-\d{3})", target)
    return m[1] if m else ""


# ---------------------------------------------------------------------------- values


def sha_of(env: Env, paths: tuple[str, ...]) -> str:
    out = git_raw("log", "-1", "--format=%h", "--abbrev=10", env.base, "--", *paths)
    return out.strip() if out and out.strip() else "0000000000"


def calendar_values(src: str) -> tuple[datetime.date | None, int | None]:
    m = re.search(r"SPRINT01_START\s*=\s*datetime\.date\((\d+),\s*(\d+),\s*(\d+)\)", src)
    d = re.search(r"^SPRINT_DAYS\s*=\s*(\d+)", src, re.MULTILINE)
    start = datetime.date(int(m[1]), int(m[2]), int(m[3])) if m else None
    return start, int(d[1]) if d else None


def sprint_fields(src: str) -> dict[str, int]:
    data = json.loads(src)
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


def date_values(env: Env) -> dict[str, str]:
    vals: dict[str, str] = {}
    start, days = calendar_values(env.at_base(CAL_REL))
    sprints = sprint_fields(env.at_base(E15J_REL))
    for k, n in sprints.items():
        vals[f"SPRINT:{k}"] = str(n)
        if start and days:
            s0 = start + datetime.timedelta(days=(n - 1) * days)
            vals[f"DATE:{k}.start"] = s0.isoformat()
            vals[f"DATE:{k}.end"] = (s0 + datetime.timedelta(days=days - 1)).isoformat()
    if "d14" in sprints and all(c in sprints for c in CONSUMERS):
        vals["COUNT:ahead.min"] = str(min(sprints[c] for c in CONSUMERS) - sprints["d14"])
    return vals


def area_values(env: Env) -> dict[str, str]:
    """The ring a w px outline adds around each panel `D04`:133 draws at 1280×800, and HS-1b's
    area bound from `E05D03`:110 — read from the cited lines, never typed."""
    vals: dict[str, str] = {}
    d04 = env.lines(env.base, PATHS["D04"])
    e05 = env.lines(env.base, PATHS["E05D03"])
    line = d04[132] if len(d04) > 132 else ""
    m = re.search(r"(\d+) px `color\.focus\.ring` outline", line)
    width = int(m[1]) if m else 0
    head = line.split(";")[0]  # the 1280×800 clause
    for name in PANELS:
        mm = re.search(rf"\b{name}\s+(\d+)×(\d+)", head, re.IGNORECASE)
        if mm and width:
            w, h = int(mm[1]), int(mm[2])
            vals[f"AREA:outline.{name}"] = str((w + 2 * width) * (h + 2 * width) - w * h)
    bound = re.search(r"(\d[\d ]*\d) px²", e05[109] if len(e05) > 109 else "")
    if bound:
        vals["AREA:bound"] = bound[1].replace(" ", "")
    return vals


def count_values(t: Texts) -> dict[str, str]:
    spec = t.spec
    vals: dict[str, str] = {}
    inv = inv_rows(spec)
    verdicts = [verdict_of(r[3]) for r in inv if len(r) > 3]
    vals["COUNT:inventory"] = str(len(inv))
    for v in VERDICTS:
        vals[f"COUNT:inventory.{v}"] = str(verdicts.count(v))
    vals["COUNT:binding"] = str(len(b_rows(spec)))
    vals["COUNT:never"] = str(len(n_rows(spec)))
    vals["COUNT:proof"] = str(len(p_rows(spec)))
    vals["COUNT:strings"] = str(len(s_rows(spec)))
    led = ledger_rows(spec)
    disp = [disposition(r[2]) for r in led if len(r) > 2]
    vals["COUNT:ledger"] = str(len(led))
    vals["COUNT:ledger.applied"] = str(disp.count("applied"))
    vals["COUNT:ledger.amended"] = str(disp.count("applied-as-amended"))
    vals["COUNT:ledger.routed"] = str(disp.count("routed"))
    vals["COUNT:ledger.held"] = str(disp.count("held"))
    vals["COUNT:ledger.confirmed"] = str(disp.count("confirmed"))
    vals["COUNT:ledger.superseded"] = str(disp.count("superseded by #"))
    vals["COUNT:candidates"] = str(len(cr_rows(spec)))
    vals["COUNT:crows"] = str(len(c_rows(spec)))
    vals["COUNT:grows"] = str(len(g_rows(spec)))
    ar = a_rows(spec)
    vals["COUNT:arows"] = str(len(ar))
    vals["COUNT:arows.replace"] = str(
        sum(len(r) > 4 and r[3] == "replace" and r[4] != RULED_VIA for r in ar)
    )
    vals["COUNT:arows.ruled"] = str(sum(len(r) > 4 and r[4] == RULED_VIA for r in ar))
    vals["COUNT:arows.confirm"] = str(sum(len(r) > 3 and r[3] == "confirm" for r in ar))
    vals["COUNT:arows.new"] = str(sum(len(r) > 3 and r[3] == "insert after" for r in ar))
    bq = bq_rows(spec)
    vals["COUNT:bq"] = str(len(bq))
    vals["COUNT:bq.ruled"] = str(sum(len(r) > 2 and r[2] == "RULED" for r in bq))
    vals["COUNT:consumers"] = str(len(consumer_rows(spec)))
    vals["COUNT:walk"] = str(len(walk_items(spec)))
    vals["COUNT:mutations"] = str(len(MUTATIONS))
    return vals


def compute(t: Texts) -> dict[str, str]:
    env = t.env
    vals: dict[str, str] = {
        "SHA:BASE": env.base[:10],
        f"SHA:PR{PR_NUMBER}": env.pr_sha(PR_NUMBER),
        f"SHA:PR{PR2_NUMBER}": env.pr_sha(PR2_NUMBER),
    }
    for k, paths in SHA_INPUTS.items():
        vals[f"SHA:{k}"] = sha_of(env, paths)
    vals.update(token_values(env))
    vals.update(e05_values(env))
    vals.update(date_values(env))
    vals.update(area_values(env))
    vals.update(count_values(t))
    return vals


# ---------------------------------------------------------------------------- placeholders


def code_spans(line: str) -> list[tuple[int, int]]:
    return [(m.start(), m.end()) for m in CODE.finditer(line)]


def fill(text: str, values: dict[str, str]) -> tuple[str, list[str]]:
    missing: list[str] = []
    out_lines = []
    for ln in text.split("\n"):
        spans = code_spans(ln)

        def ph(m: re.Match[str], spans: list[tuple[int, int]] = spans) -> str:
            if any(a <= m.start() < b for a, b in spans):
                return m[0]
            if m[1] not in values:
                missing.append(m[1])
                return m[0]
            return f"{values[m[1]]}<!--={m[1]}-->"

        out_lines.append(PLACEHOLDER.sub(ph, ln))
    text = "\n".join(out_lines)

    def refresh(m: re.Match[str]) -> str:
        return f"{values[m[2]]}<!--={m[2]}-->" if m[2] in values else m[0]

    return ANCHORED.sub(refresh, text), missing


def unfill(text: str) -> str:
    return ANCHORED.sub(r"<!--=\2-->", text)


def anchored(text: str) -> list[tuple[str, str, int]]:
    return [
        (m[1], m[2], i) for i, ln in enumerate(text.split("\n"), 1) for m in ANCHORED.finditer(ln)
    ]


def unfilled(text: str) -> list[str]:
    return [m[1] for ln in lines_of(text) for m in PLACEHOLDER.finditer(without_code(ln))]


# ---------------------------------------------------------------------------- pins

Unit = tuple[str, str, str]


def line_form(line: str) -> str:
    if re.match(r"^\s*[-*+] ", line):
        return "b"
    if re.match(r"^\s*\d+\. ", line):
        return "n"
    return "p"


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
            key = f"{doc}:" + " › ".join(p[1] for p in path)
            seen[key] = seen.get(key, 0) + 1
            region, k, shape, rows = f"{key}#{seen[key]}", 0, "h", {}
            out.append((region, "heading", pin_norm(raw)))
            continue
        if not raw.strip():
            shape += "."
        elif RULE.match(raw):
            shape += "r"
            out.append((region, f"rule {shape.count('r')}", pin_norm(re.sub(r"-+", "-", raw))))
        elif raw.lstrip().startswith("|"):
            shape += "t"
            cells = split_row(raw)
            lead = pin_norm(cells[0]) or "(blank)"
            rows[lead] = rows.get(lead, 0) + 1
            loc = f"row {lead}" + (f"#{rows[lead]}" if rows[lead] > 1 else "")
            out.append((region, loc, " | ".join(pin_norm(c) for c in cells)))
        else:
            indent = len(raw) - len(raw.lstrip())
            sents = [x for x in FULL_STOP.split(raw.strip()) if x.strip()]
            shape += (f">{indent}" if indent else "") + f"{line_form(raw)}{len(sents)}"
            for x in sents:
                k += 1
                out.append((region, f"s{k}", pin_norm(x)))
    out.append((region, "shape", shape))
    return out


def fresh_cite_pins(t: Texts) -> dict[str, CitePin]:
    """Every distinct cite -> the hash of its line(s) at its own number at the base (PR 1's
    pins)."""
    out: dict[str, CitePin] = {}
    for key, a, b in all_cites(t):
        ls = t.env.lines(t.env.base, PATHS[key])
        if 0 < a <= b <= len(ls):
            hh = heading_hash(heading_before(ls, a))
            out[label_of(key, a, b)] = (line_hash(ls[a - 1], ls[b - 1]), None, hh)
    return out


def write_pins(us: list[Unit], cites: dict[str, CitePin]) -> str:
    head = (
        "# E15-D14 pins (every unit of the pack): region, location, the exact normalised text; "
        f"{len(us)} units, then {len(cites)} cite pins (`cite`, the cite, a hash of the cited line "
        "at the base, `h:` the hash of the entry heading it sits under, and `@n` once a move was "
        "recorded in PR 2).\n# Written by `--repin-ruled` only; `--check` reads it (never "
        "hand-edit; see the tool's G-RULED-PIN and G-HYGIENE).\n"
    )
    body = "".join("\t".join(u) + "\n" for u in us)
    for label, (h, at, hh) in cites.items():
        tail = (
            "" if at is None else ("\t@" + (str(at[0]) if at[0] == at[1] else f"{at[0]}–{at[1]}"))
        )
        tail += f"\th:{hh}" if hh else ""
        body += f"cite\t{label}\t{h}{tail}\n"
    return head + body


def parse_pins(text: str) -> list[Unit]:
    out: list[Unit] = []
    for ln in text.split("\n"):
        parts = ln.split("\t")
        if ln and not ln.startswith("#") and len(parts) == 3 and parts[0] != "cite":
            out.append((parts[0], parts[1], parts[2]))
    return out


def pin_problems(pinned: list[Unit], current: list[Unit]) -> list[str]:
    bad: list[str] = []
    old_r = list(dict.fromkeys(u[0] for u in pinned))
    new_r = list(dict.fromkeys(u[0] for u in current))
    for r in new_r:
        if r not in old_r:
            bad.append(f"region '{r[-60:]}' is unpinned (new)")
    for r in old_r:
        if r not in new_r:
            bad.append(f"region '{r[-60:]}' deleted or renamed")
    common = [r for r in new_r if r in old_r]
    if common != [r for r in old_r if r in new_r]:
        bad.append("a pinned region moved (the heading order changed)")
    for r in common:
        was = [(u[1], u[2]) for u in pinned if u[0] == r]
        now = [(u[1], u[2]) for u in current if u[0] == r]
        if was == now:
            continue
        wd = dict(was)
        what = "units moved or reordered"
        for loc, txt in now:
            if loc not in wd:
                what = f"{loc} unpinned (new): {txt[:40]!r}"
                break
            if wd[loc] != txt:
                what = f"{loc} changed: {txt[:40]!r}"
                break
        else:
            gone = [loc for loc, _ in was if loc not in dict(now)]
            if gone:
                what = f"{gone[0]} deleted"
        bad.append(f"'{r[-48:]}' {what}")
    return bad


def pins_diff_problems(t: Texts, mb: str) -> list[str]:
    """PR 2's one tolerated pack change: the pins differ from the merge-base by recorded cite moves
    alone — the same units in the same order, the same cite labels, hashes and heading hashes,
    every new `@n` the place where the pinned content stands, and the file byte for byte what
    `--repin-ruled` writes from those (BQ-03)."""
    old = t.env.show(mb, PINS_REL)
    if old is None:
        return [f"{PINS_REL} is absent at the merge-base; PR 2 cannot rewrite it"]
    bad: list[str] = []
    if parse_pins(old) != parse_pins(t.pins):
        bad.append("PR 2 rewrote a pinned unit; the pins may record cite moves alone")
    oc, nc = cite_pins(old), cite_pins(t.pins)
    if list(oc) != list(nc):
        bad.append("PR 2 added, dropped or reordered a cite pin")
    for label, (h, at, hh) in nc.items():
        if label not in oc:
            continue
        if oc[label][0] != h or oc[label][2] != hh:
            bad.append(f"PR 2 changed the pinned content of cite {label}")
        elif at != oc[label][1]:
            m = re.fullmatch(r"([A-Z0-9]+):(\d+)(?:–(\d+))?", label)
            key = m[1] if m else ""
            ls = t.env.lines(t.env.base, PATHS[key]) if key in PATHS else []
            ok = (
                at is not None
                and 0 < at[0] <= at[1] <= len(ls)
                and line_hash(ls[at[0] - 1], ls[at[1] - 1]) == h
            )
            if not ok:
                bad.append(
                    f"PR 2 recorded a move for cite {label} that its content does not stand at"
                )
    if not bad and t.pins != write_pins(parse_pins(old), nc):
        bad.append(
            "PR 2's pins are not the merge-base's units with the cite moves re-serialised byte for "
            "byte (a stray or re-ordered line; `--repin-ruled` is the only writer)"
        )
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
    ("COUNT:inventory", "G-TABLE"), ("COUNT:bq", "G-TABLE"), ("COUNT:consumers", "G-TABLE"),
    ("COUNT:walk", "G-TABLE"), ("COUNT:ledger", "G-TABLE"), ("COUNT:candidates", "G-TABLE"),
    ("COUNT:crows", "G-TABLE"), ("COUNT:grows", "G-TABLE"),
    ("TOKMS:", "G-TOKEN"), ("EASE:", "G-TOKEN"),
    ("COUNT:proof", "G-REDUCE"),
    ("E05:", "G-BINDING"), ("COUNT:binding", "G-BINDING"),
    ("AREA:", "G-SAFETY"), ("COUNT:never", "G-SAFETY"),
    ("COUNT:strings", "G-STRING"),
    ("DATE:", "G-VERSION"), ("SPRINT:", "G-VERSION"), ("COUNT:ahead", "G-VERSION"),
    ("COUNT:arows", "G-AROW"),
)  # fmt: skip


def anchor_gate(key: str) -> str:
    for prefix, gate in ANCHOR_GATE:
        if key.startswith(prefix):
            return gate
    return "G-HYGIENE"


def anchor_problems(t: Texts, gate: str) -> list[str]:
    bad: list[str] = []
    pr2 = pr2_mode(t)
    for value, key, ln in anchored(t.spec):
        if anchor_gate(key) != gate:
            continue
        if pr2 and key.startswith("SHA:"):
            continue  # PR 1's record of its inputs; G-HYGIENE checks `SHA:BASE`'s ancestry
        want = t.values.get(key)
        if want is None:
            bad.append(f"spec:{ln} anchors `{key}`, which the tool does not compute")
        elif want != value:
            bad.append(f"spec:{ln} `{key}` reads {value}; the tool derives {want}")
    bad += residue_problems(t.spec, gate)
    return bad


def residue_problems(text: str, gate: str) -> list[str]:
    """In a table cell nothing stands in front of an anchored value but the cell's start, the end
    of the previous anchor or a bare separator: the tail of an earlier fill is a FAIL."""
    bad: list[str] = []
    for i, ln in enumerate(text.split("\n"), 1):
        if not ln.lstrip().startswith("|"):
            continue
        for cell in split_row(ln):
            pos = 0
            for m in ANCHORED.finditer(cell):
                if anchor_gate(m[2]) == gate and cell[pos : m.start()].strip() not in (
                    "",
                    "/",
                    "·",
                    "(",
                ):
                    bad.append(
                        f"spec:{i} `{m[2]}`: the cell carries text in front of its value "
                        f"({cell[pos : m.start()].strip()[:40]!r}); re-fill the cell"
                    )
                pos = m.end()
    return bad


# ---------------------------------------------------------------------------- the gates


NEEDLE = re.compile(r"^`([^`]+)` \((?:`([0-9]{2})`|`?([A-Z0-9]+)`?):(\d+)")


def g_table(t: Texts) -> list[Finding]:
    bad = anchor_problems(t, "G-TABLE")
    warn: list[str] = []
    for k, r in enumerate(inv_rows(t.spec), 1):
        if len(r) != 12:
            bad.append(f"{r[0]} has {len(r)} cells, not 12")
            continue
        if r[0] != f"I-{k}":
            bad.append(f"inventory row {k} is numbered {r[0]}")
        if verdict_of(r[3]) not in VERDICTS:
            bad.append(f"{r[0]}: the verdict {r[3]!r} is not cut / fade / follow / routed")
        for i, name in ((1, "transition"), (2, "surface"), (5, "motion-safe"), (6, "reduce"),
                        (7, "carrier"), (11, "source")):  # fmt: skip
            if r[i] in ("", "—"):
                bad.append(f"{r[0]}: an empty {name} cell")
        if not any(r[8].startswith(w) for w in BOX_WORDS):
            bad.append(
                f"{r[0]}: the content-box cell does not start with never / once / per pointer frame"
            )
        if not CITE.search(r[11]):
            bad.append(f"{r[0]}: the source cell carries no cite")
    bq = bq_rows(t.spec)
    ids = [r[0] for r in bq]
    want = [f"BQ-{n:02d}" for n in range(1, 23)]
    if ids != want:
        bad.append("§R does not list BQ-01 … BQ-22 once each, in order")
    for r in bq:
        if len(r) != 3 or r[2] not in ("RULED", "pending"):
            bad.append(f"§R {r[0]}: the status is not RULED / pending")
    for m in re.finditer(r"RULED BQ-(\d\d)", t.spec):
        if f"BQ-{m[1]}" not in ids:
            bad.append(f"a row is stamped RULED BQ-{m[1]}, which §R does not list")
    for r in ledger_rows(t.spec):
        if len(r) != 4:
            bad.append(f"{r[0]} has {len(r)} cells, not 4")
            continue
        d = disposition(r[2])
        if not d:
            bad.append(f"{r[0]}: the disposition {r[2][:30]!r} is not in the ruled set")
        m = NEEDLE.match(r[1])
        if not m:
            bad.append(f"{r[0]}: the row of record is not `needle` (`KEY`:line)")
            continue
        key = m[2] or m[3]
        if key not in PATHS:
            bad.append(f"{r[0]}: the cite key {key} is unknown")
            continue
        if m[1] not in cite_line(t, key, int(m[4])):
            bad.append(f"{r[0]}: `{m[1]}` is not in {key}:{m[4]}")
        if d == "superseded by #":
            mm = re.match(r"superseded by #(\d+): (?:`([0-9]{2})`|`?([A-Z0-9]+)`?):\d+", r[2])
            k2 = (mm[2] or mm[3]) if mm else ""
            if not mm or k2 not in PATHS or f"#{mm[1]}" not in t.env.log_subjects(PATHS[k2]):
                bad.append(f"{r[0]}: the superseding PR is not in the target file's history")
    if not consumer_rows(t.spec):
        bad.append("§10 lists no consumer")
    if len(walk_items(t.spec)) > 10:
        bad.append("§12's walkthrough exceeds ten items")
    return one("G-TABLE", bad) + one("G-TABLE", warn, "WARN")


def g_property(t: Texts) -> list[Finding]:
    bad: list[str] = []
    for r in inv_rows(t.spec):
        if len(r) != 12:
            continue
        v, prop, box = verdict_of(r[3]), r[4], r[8]
        if prop not in PROPERTIES or BOX_PROPERTY.search(prop):
            bad.append(f"{r[0]}: the property {prop!r} is not `opacity`, `transform` or `none`")
            continue
        if v == "cut" and prop != "`none`":
            bad.append(f"{r[0]}: a cut must be `none`")
        if v == "fade" and "`opacity`" not in prop:
            bad.append(f"{r[0]}: a fade must animate `opacity`")
        if v == "follow" and prop not in ("`transform`", "`none`"):
            bad.append(f"{r[0]}: a follow is `transform` or a layout write (`none`)")
        if v == "routed" and prop != "—":
            bad.append(f"{r[0]}: a routed row binds no property here")
        if box.startswith("per pointer frame") and v != "follow":
            bad.append(f"{r[0]}: only a follow changes a box per pointer frame")
        if v == "fade" and not box.startswith(("never", "once")):
            bad.append(f"{r[0]}: a fade's content box is never or once")
    return one("G-PROPERTY", bad)


def g_token(t: Texts) -> list[Finding]:
    bad = anchor_problems(t, "G-TOKEN")
    shipped = shipped_motion(t.env)
    for i, ln in enumerate(lines_of(t.spec), 1):
        scan = ln
        if ln.startswith("| A-"):  # a §C row's Old quotes another owner's line verbatim
            cells = split_row(ln)
            scan = cells[6] if len(cells) == 8 else ln
            if len(cells) == 8 and cells[4] == RULED_VIA:  # the ruled New is the owner's line too
                scan = RULED_A47[1]
        for name in MOTION_NAME.findall(scan):
            if name not in shipped:
                bad.append(f"spec:{i}: `{name}` is not a shipped primitive")
    for r in inv_rows(t.spec):
        if len(r) != 12 or "B-4" in r[10]:
            continue
        text = " ".join(r)
        for slow in ("motion.duration.normal", "motion.duration.slow"):
            if f"`{slow}`" in text:
                bad.append(
                    f"{r[0]}: `{slow}` on a dock row (no dock transition is longer than fast)"
                )
    for r in b_rows(t.spec):
        if "`motion.duration.slow`" in " ".join(r):
            bad.append(f"{r[0]}: `motion.duration.slow` on a binding row")
    for r in a_rows(t.spec):
        if len(r) == 8 and "`motion.duration.slow`" in r[6]:
            bad.append(f"{r[0]}: `motion.duration.slow` in a New cell")
        if len(r) == 8 and "`motion.duration.normal`" in r[6] and "row 2a" not in r[6]:
            bad.append(f"{r[0]}: `motion.duration.normal` in a New cell outside row 2a's scrim")
    return one("G-TOKEN", bad)


def g_reduce(t: Texts) -> list[Finding]:
    bad = anchor_problems(t, "G-REDUCE")
    inv = inv_rows(t.spec)
    for r in inv:
        if len(r) == 12 and not r[6].startswith("`none`"):
            bad.append(f"{r[0]}: the reduce cell is not `none` (E05-D03 §3)")
    pr = p_rows(t.spec)
    for r in pr:
        if len(r) != 6:
            bad.append(f"{r[0]} has {len(r)} cells, not 6")
        elif any(r[i] in ("", "—") for i in (2, 3, 4)):
            bad.append(f"{r[0]}: an empty proof cell")
    if [r[1] for r in pr if len(r) > 1] != [r[0] for r in inv]:
        bad.append("§5's proof rows do not cover the inventory rows once each, in order")
    return one("G-REDUCE", bad)


def g_binding(t: Texts) -> list[Finding]:
    bad = anchor_problems(t, "G-BINDING")
    e05 = e05_table(t.env)
    brows = b_rows(t.spec)
    bids = {r[0] for r in brows}
    for r in brows:
        if len(r) != 9:
            bad.append(f"{r[0]} has {len(r)} cells, not 9")
            continue
        m = re.search(r"\brow (\d[ab]?)\b", r[6])
        if not ((m and m[1] in e05) or "CR-" in r[7]):
            bad.append(f"{r[0]}: names neither an E05-D03 row nor a candidate row")
    for r in inv_rows(t.spec):
        if len(r) != 12:
            continue
        v, binding = verdict_of(r[3]), r[10]
        if v == "fade":
            m = re.match(r"(B-\d)", binding)
            if not m or m[1] not in bids:
                bad.append(f"{r[0]}: a fade names no §3 binding row")
        elif v == "follow" and "D04" not in binding:
            bad.append(f"{r[0]}: a follow names no D04 rule")
        elif v == "routed" and "CR-" not in binding and not cites_in(binding):
            bad.append(
                f"{r[0]}: a routed row names neither a candidate row nor its owner's binding"
            )
    enter = {k: pair_of(e05[k][5]) for k in ("1", "4a") if k in e05}
    exit_ = {k: pair_of(e05[k][6]) for k in ("2a", "2b", "3", "4a") if k in e05}
    if len(enter) != 2 or len(set(enter.values())) != 1:
        bad.append("E05-D03 rows 1 and 4a do not share an enter pair at the base")
    if len(exit_) != 4 or len(set(exit_.values())) != 1:
        bad.append("E05-D03 rows 2a, 2b, 3 and 4a do not share an exit pair at the base")
    return one("G-BINDING", bad)


def g_safety(t: Texts) -> list[Finding]:
    bad = anchor_problems(t, "G-SAFETY")
    for r in n_rows(t.spec):
        if len(r) != 6:
            bad.append(f"{r[0]} has {len(r)} cells, not 6")
        elif not r[3].startswith("cut"):
            bad.append(f"{r[0]}: a never-animates carrier that is not a cut")
    for r in inv_rows(t.spec):
        if len(r) != 12:
            continue
        where = f"{r[1]} {r[2]}"
        hits = [w for w in SAFETY_WORDS if safety_word(w).search(where)]
        verdict = verdict_of(r[3])
        if hits and verdict != "cut":
            if hits == [DIALOG_WORD] and verdict == "fade":
                # the scrim fades, the card is a cut: both motion cells must say so
                if not (CARD_AT_0.search(r[5]) and CARD_AT_0.search(r[6])):
                    bad.append(
                        f"{r[0]}: an `alertdialog` row whose cells do not put the card at frame 0"
                    )
            else:
                bad.append(f"{r[0]}: a safety carrier animates ({', '.join(hits)}; §4's rule)")
        carried = [w for w in SAFETY_WORDS if safety_word(w).search(r[7])]
        if verdict != "cut" and carried and not (CARRIER_AT_0.search(r[7]) or HEADER_OUT in r[7]):
            bad.append(
                f"{r[0]}: the carrier cell names {', '.join(carried)} without frame 0 or the "
                "header exclusion (a carrier never lives in a fading layer)"
            )
        if EXEMPT in r[5] and r[0] != EXEMPT_ROW:
            bad.append(f"{r[0]}: the maximise exemption is {EXEMPT_ROW}'s alone")
        if r[0] == EXEMPT_ROW and ("B-1" in r[10] or not r[10].startswith("B-2")):
            bad.append(
                f"{r[0]}: the exemption holds one way — the exit pair B-2 alone; the restore is a cut"
            )
        if r[0] == RESTORE_ROW and verdict != "cut":
            bad.append(f"{r[0]}: the restore from a maximise is a cut (no fade-in on screen)")
        if verdict == "fade" and PANEL_ID in r[2] and not header_excluded(r[5]):
            bad.append(f"{r[0]}: a fade on {PANEL_ID} that does not state the header exclusion")
    for r in b_rows(t.spec):
        if len(r) == 9 and PANEL_ID in r[2] and not header_excluded(r[2]):
            bad.append(f"{r[0]}: a binding on {PANEL_ID} that does not state the header exclusion")
    for r in table_after(sec(t.spec, "### 6.3"), "Frame"):
        if len(r) == 4 and "B-3" in r[1] and not header_excluded(r[1]):
            bad.append(f"§6.3 frame {r[0]!r}: the mount row does not state the header exclusion")
    for r in a_rows(t.spec):
        if (
            len(r) == 8
            and entry_id(r[1]) == PANEL_ID
            and "`opacity`" in r[6]
            and not header_excluded(r[6])
        ):
            bad.append(f"{r[0]}: a {PANEL_ID} line with a fade that omits the header exclusion")
    s4 = sec(t.spec, "## 4.")
    if "a safety carrier never lives in a fading layer" not in s4:
        bad.append("§4 does not state that a safety carrier never lives in a fading layer")
    if HEADER_OUT not in s4:
        bad.append(f"§4 does not state the header exclusion ({HEADER_OUT!r})")
    return one("G-SAFETY", bad)


def safety_word(word: str) -> re.Pattern[str]:
    return re.compile(r"(?<!\w)" + re.escape(word) + r"(?:e?s)?(?!\w)", re.IGNORECASE)


def header_excluded(cell: str) -> bool:
    return HEADER_OUT in cell or EXEMPT in cell


def g_string(t: Texts) -> list[Finding]:
    bad = anchor_problems(t, "G-STRING")
    for r in s_rows(t.spec):
        if len(r) != 4:
            bad.append(f"{r[0]} has {len(r)} cells, not 4")
            continue
        text = unescape(r[1]).strip().strip('"')
        cites = cites_in(r[3])
        if not cites:
            bad.append(f"{r[0]}: no source cite")
            continue
        key, a, _ = cites[0]
        if text not in cite_line(t, key, a):
            bad.append(f"{r[0]}: {text[:40]!r} is not in {key}:{a}")
    return one("G-STRING", bad)


def g_cite(t: Texts) -> list[Finding]:
    fails, warns = cite_problems(t)
    return one("G-CITE", fails) + one("G-CITE", warns, "WARN")


def g_version(t: Texts) -> list[Finding]:
    bad = anchor_problems(t, "G-VERSION")
    warn: list[str] = []
    env = t.env
    head_cal = env.show(HEAD_REF, CAL_REL)
    if head_cal is None:
        bad.append(f"{HEAD_REF} does not resolve or lacks {CAL_REL}; fetch origin first")
    elif calendar_values(head_cal) != calendar_values(env.at_base(CAL_REL)):
        bad.append(f"the calendar's sprint-1 start or length changed at {HEAD_REF}")
    head_j = env.show(HEAD_REF, E15J_REL)
    if head_j is not None:
        a, b = sprint_fields(env.at_base(E15J_REL)), sprint_fields(head_j)
        for k in SPRINT_KEYS.values():
            if a.get(k) != b.get(k):
                bad.append(
                    f"the sprint field of {k} changed at {HEAD_REF} ({a.get(k)} → {b.get(k)})"
                )
    for key, a0, b0 in all_cites(t):
        rel = PATHS[key]
        if env.show(HEAD_REF, rel) == env.show(env.base, rel):
            continue
        a2, b2, status = resolve_cite(t, key, a0, b0)
        if status in ("range", "unpinned", "gone"):
            continue
        ls = env.lines(env.base, rel)
        h = line_hash(ls[a2 - 1], ls[b2 - 1])
        hl = env.lines(HEAD_REF, rel)
        label = label_of(key, a0, b0)
        if 0 < a2 <= b2 <= len(hl) and line_hash(hl[a2 - 1], hl[b2 - 1]) == h:
            continue
        at = found_under(env, HEAD_REF, rel, h, b2 - a2, heading_hash(heading_before(ls, a2)))
        if len(at) == 1:
            warn.append(
                f"cite {label} stands at :{at[0]} at {HEAD_REF} (moved; re-pin at the next edit)"
            )
        elif at:
            bad.append(
                f"cite {label}: its content stands {len(at)} times in its entry at {HEAD_REF}"
            )
        else:
            bad.append(
                f"cite {label}: its content stands nowhere in its entry at {HEAD_REF} (edited)"
            )
    return one("G-VERSION", bad) + one("G-VERSION", warn, "WARN")


def entry_heading(lines: list[str], cmp: str) -> list[int]:
    return [i for i, ln in enumerate(lines) if ln.startswith(f"### {cmp} ")]


def entry_span(lines: list[str], start: int) -> int:
    return next((i for i in range(start + 1, len(lines)) if lines[i].startswith("#")), len(lines))


def g_arow(t: Texts) -> list[Finding]:
    bad = anchor_problems(t, "G-AROW")
    base15 = t.env.lines(t.env.base, CAT_REL)
    # a PR that changes `15` sits on PR 2's merge-base, not PR 1's: the numbers are checked by content
    pr2 = bool(t.changed) and CAT_REL in (t.changed or [])
    if f"(#{PR2_NUMBER})" not in t.env.log_subjects(CAT_REL):
        bad.append(f"#{PR2_NUMBER} (E15-D13's PR 2) is not in `15`'s history at {HEAD_REF}")
    for r in a_rows(t.spec):
        if len(r) != 8:
            bad.append(f"{r[0]} has {len(r)} cells, not 8")
            continue
        aid, target, _, op, via, old, new, _ = r
        cmp = entry_id(target)
        n = a_row_line(r)
        if op not in ("replace", "insert after", "confirm") or n is None or not cmp or old == "—":
            bad.append(f"{aid}: the op, the Field, the target or the Old is malformed")
            continue
        heads = entry_heading(base15, cmp)
        if len(heads) != 1:
            bad.append(f"{aid}: the entry {cmp} stands {len(heads)} times at the base")
            continue
        end = entry_span(base15, heads[0])
        want = unescape(old)
        hits = [i for i in range(heads[0], end) if base15[i] == want]
        if op == "insert after":
            if via != "—":
                bad.append(f"{aid}: a new line's Via is `—`")
            bullets = [i for i in range(heads[0], end) if base15[i].startswith("- **")]
            if not bullets or base15[bullets[-1]] != want:
                bad.append(f"{aid}: Old is not {cmp}'s last bullet at the base")
            elif not pr2 and bullets[-1] != n - 1:
                bad.append(
                    f"{aid}: Old stands at `15`:{bullets[-1] + 1}, not at `15`:{n} (PR 1's base)"
                )
        else:
            ruled = via == RULED_VIA
            if not ruled and via != f"#{PR2_NUMBER}":
                bad.append(
                    f"{aid}: a replace or a confirmation names #{PR2_NUMBER} as its Via "
                    f"({RULED_VIA} for the ruled replacement alone)"
                )
            if len(hits) != 1:
                bad.append(f"{aid}: Old stands {len(hits)} times inside {cmp} at the base")
            elif not pr2 and hits[0] != n - 1:
                bad.append(
                    f"{aid}: Old stands at `15`:{hits[0] + 1}, not at `15`:{n} (PR 1's base)"
                )
            if ruled:
                lose, gain, stamp = RULED_A47
                old_text = unescape(old)
                new_text = strip_anchors(unescape(new))
                if op != "replace":
                    bad.append(f"{aid}: the ruled row is a replace")
                if old_text.count(lose) != 1:
                    bad.append(f"{aid}: the ruled row's Old does not carry A47's span once")
                elif new_text != old_text.replace(lose, gain):
                    bad.append(
                        f"{aid}: the ruled row's New is not its Old with A47's span alone swapped"
                    )
                if stamp not in r[7]:
                    bad.append(f"{aid}: the ruled row's From lacks A47's RULED stamp")
                if "<br>" in new_text or "\n" in new_text:
                    bad.append(f"{aid}: New is more than one line")
                continue
        if op == "confirm":
            if new != "—":
                bad.append(f"{aid}: a confirmation writes nothing")
            continue
        text = strip_anchors(unescape(new))
        if not text.startswith(NEW_LINE_HEAD) or not text.endswith(".") or "PROPOSED" not in text:
            bad.append(
                f"{aid}: New is not one `- **Motion spec**:` line in `15`:523's form, marked PROPOSED"
            )
        if "<br>" in text or "\n" in text:
            bad.append(f"{aid}: New is more than one line")
    rows = [r for r in a_rows_export(t) if r["op"] != "confirm"]
    _, problems = apply_rows(t.env.at_base(CAT_REL), rows)
    bad += problems
    return one("G-AROW", bad)


def mutation_paragraph(spec: str) -> str:
    block = sec(spec, "## §M")
    return next((ln for ln in lines_of(block) if "M-1 " in ln), "")


def g_hygiene(t: Texts) -> list[Finding]:
    bad = anchor_problems(t, "G-HYGIENE")
    for key in unfilled(t.spec):
        bad.append(f"the placeholder `{key}` is unfilled (run --check --fill)")
    for i, ln in enumerate(lines_of(t.spec), 1):
        if "{{" in ln:
            bad.append(f"spec:{i} carries `{{{{` (a placeholder outside the fill, or a stray)")
        if CLOSING.search(ln):
            bad.append(f"spec:{i} carries a closing keyword (PR 2 alone closes #{ISSUE})")
        if LOCAL_PATH.search(ln):
            bad.append(f"spec:{i} carries a local filesystem path or a notes-folder name")
        if AGENT_NAME.search(ln):
            bad.append(f"spec:{i} carries an agent name")
        if URL_OR_HOST.search(ln):
            bad.append(f"spec:{i} carries a URL, a host or a Penpot id parameter")
    if t.changed is None:
        bad.append("cannot list the changed paths (`git diff` / `git status` failed)")
    else:
        other = [p for p in t.changed if p not in OWN_PATHS]
        if CAT_REL not in t.changed:
            for p in other:
                bad.append(f"PR 1 changes {p}, outside the pack's three files")
        else:
            for p in t.changed:
                if p in PACK_TEXTS:
                    bad.append(
                        f"PR 2 changes {p}: the pack is byte-identical to the merged PR 1 (BQ-03)"
                    )
                elif p not in OWN_PATHS and p != CAT_REL:
                    bad.append(f"PR 2 changes {p}, outside `15` and the pins")
            rows = [r for r in a_rows_export(t) if r["op"] != "confirm"]
            want15, problems = apply_rows(t.env.at_base(CAT_REL), rows)
            for p in problems:
                bad.append(
                    f"PR 2: {p} (a target line is absent from `15` at the merge-base: edited or "
                    "moved out of its entry by a later PR)"
                )
            if not problems and t.cat15 != want15:
                bad.append(
                    "PR 2: `15` is not the merge-base with §C applied exactly (an extra byte)"
                )
            for value, key, _ in anchored(t.spec):
                if key == "SHA:BASE" and (
                    git_raw("merge-base", "--is-ancestor", value, t.env.base) is None
                ):
                    bad.append(
                        f"PR 2: the recorded `SHA:BASE` {value} is no ancestor of the merge-base "
                        "(the pack was pinned on another line)"
                    )
                    break
            if PINS_REL in t.changed:
                bad += pins_diff_problems(t, t.env.base)
    para = mutation_paragraph(t.spec)
    gates_named = re.findall(r"\*\*(G-[A-Z-]+)\*\*", para)
    n_listed = len(set(re.findall(r"\bM-\d+\b", para)))
    if n_listed != len(MUTATIONS):
        bad.append(f"§M lists {n_listed} mutations; the tool has {len(MUTATIONS)}")
    if gates_named != [g.__name__.upper().replace("G_", "G-") for g in GATES] + ["G-RULED-PIN"]:
        bad.append("§M does not name each gate once, in the tool's order")
    return one("G-HYGIENE", bad)


def g_pins(t: Texts) -> list[Finding]:
    pinned = parse_pins(t.pins)
    if not pinned:
        return one("G-RULED-PIN", [f"{PINS_REL} is empty or missing (run --repin-ruled)"])
    return one("G-RULED-PIN", pin_problems(pinned, units(t.spec, "spec")))


GATES: tuple[Callable[[Texts], list[Finding]], ...] = (
    g_table, g_property, g_token, g_reduce, g_binding, g_safety, g_string, g_cite, g_version,
    g_arow, g_hygiene,
)  # fmt: skip


def audit(t: Texts, timings: dict[str, float] | None = None) -> list[Finding]:
    found: list[Finding] = []
    for g in GATES:
        t0 = time.perf_counter()
        found += g(t)
        if timings is not None:
            timings[g.__name__.upper().replace("G_", "G-")] = time.perf_counter() - t0
    t0 = time.perf_counter()
    pins = g_pins(t)
    if timings is not None:
        timings["G-RULED-PIN"] = time.perf_counter() - t0
    if any(f.level == "FAIL" for f in found):
        pins = [replace(f, level="NOTE") for f in pins]
    return found + pins


# ---------------------------------------------------------------------------- §C export and PR 2


def a_rows_export(t: Texts) -> list[dict[str, object]]:
    """§C as data for PR 2: each row carries its file, its entry (the `### CMP-nnn` heading
    prefix), its anchor line (the line replaced or confirmed, or the last bullet an insert
    follows), its Old and New, and `via` — the PR that wrote the line a replace or a confirmation
    targets (#5073), null for a new line. Every number is PR 1's base's; PR 2 re-points by
    content."""
    out: list[dict[str, object]] = []
    for r in a_rows(t.spec):
        n = a_row_line(r) if len(r) == 8 else None
        if n is None:
            continue
        aid, target, _, op, via, old, new, frm = r
        cmp = entry_id(target)
        out.append(
            {
                "id": aid,
                "target": target,
                "file": CAT_REL,
                "entry": cmp,
                "line": n,
                "anchor": unescape(old),
                "op": op,
                "via": via if via.startswith("#") else None,
                "old": [] if old == "—" or op != "replace" else [unescape(old)],
                "new": [] if new == "—" else [strip_anchors(unescape(new))],
                "from": frm,
            }
        )
    return out


def apply_rows(text: str, rows: list[dict[str, object]]) -> tuple[str, list[str]]:
    """`text` with every row applied, re-pointed by content: the entry's `### CMP-nnn` heading,
    then — inside that entry — the Old line (replace) or the anchor line (insert), each found
    once; (result, problems)."""
    lines = lines_of(text)
    bad: list[str] = []
    plan: list[tuple[int, int, dict[str, object]]] = []
    for k, r in enumerate(rows):
        heads = entry_heading(lines, str(r["entry"]))
        if len(heads) != 1:
            bad.append(f"{r['id']}: the entry {r['entry']} stands {len(heads)} times")
            continue
        end = entry_span(lines, heads[0])
        hits = [i for i in range(heads[0], end) if lines[i] == r["anchor"]]
        if len(hits) != 1:
            bad.append(f"{r['id']}: its target line stands {len(hits)} times in its entry")
            continue
        plan.append((hits[0], k, r))
    for i, _, r in sorted(plan, key=lambda p: (-p[0], -p[1])):
        new = [str(x) for x in r["new"]] if isinstance(r["new"], list) else []
        if str(r["op"]) == "replace":
            lines[i : i + 1] = new
        else:
            lines[i + 1 : i + 1] = new
    return "\n".join(lines), bad


# ---------------------------------------------------------------------------- load, mutations, self-test


def load() -> Texts:
    base = merge_base()
    if base is None:
        raise SystemExit(f"`git merge-base HEAD {HEAD_REF}` does not resolve; fetch origin first")
    env = Env(base, {})
    pins = read_raw(PINS_REL) if (ROOT / PINS_REL).exists() else ""
    t = Texts(env, read_raw(SPEC_REL), pins, read_raw(CAT_REL), changed_paths(base), {})
    return replace(t, values=compute(t))


@dataclass(frozen=True)
class Mutation:
    gate: str
    what: str
    apply: Callable[[Texts], Texts]


def flex(old: str) -> re.Pattern[str]:
    return re.compile(r"\s+".join(re.escape(p) for p in old.split(" ") if p != ""))


def subst(old: str, new: str) -> Callable[[Texts], Texts]:
    def f(t: Texts) -> Texts:
        m = flex(old).search(t.spec)
        if not m:
            raise SystemExit(f"self-test: the spec lacks {old[:60]!r}")
        return replace(t, spec=t.spec[: m.start()] + new + t.spec[m.end() :])

    return f


def anchor_edit(key: str, new_value: str) -> Callable[[Texts], Texts]:
    def f(t: Texts) -> Texts:
        rx = re.compile(rf"(`[^`\n]*`|[^\s<|`]+)<!--={re.escape(key)}-->")
        m = rx.search(t.spec)
        if not m:
            raise SystemExit(f"self-test: the spec has no anchored {key}")
        return replace(
            t, spec=t.spec[: m.start()] + f"{new_value}<!--={key}-->" + t.spec[m.end() :]
        )

    return f


def with_text(t: Texts, rev: str, rel: str, text: str) -> Texts:
    """`t` with `rel` at `rev` replaced in a copy of the env (never the shared one)."""
    stale = re.compile(rf"(?:show|lines|hidx):{re.escape(rev)}:{re.escape(rel)}(?::\d+)?")
    memo = {k: v for k, v in t.env.memo.items() if not stale.fullmatch(k)}
    memo[f"show:{rev}:{rel}"] = text
    return replace(t, env=Env(t.env.base, memo))


def head_sprint_days(t: Texts) -> Texts:
    src = t.env.at_base(CAL_REL)
    return with_text(
        t, HEAD_REF, CAL_REL,
        re.sub(r"^SPRINT_DAYS = (\d+)", lambda m: f"SPRINT_DAYS = {int(m[1]) + 1}", src, count=1,
               flags=re.MULTILINE),
    )  # fmt: skip


def record_moves(t: Texts) -> tuple[str, int]:
    """The pins with every `moved` cite's new place recorded (`--repin-ruled`'s PR-2 write), and
    how many moves were recorded."""
    pins = cite_pins(t.pins)
    n = 0
    for key, a0, b0 in all_cites(t):
        a2, b2, status = resolve_cite(t, key, a0, b0)
        if status == "moved":
            h, _, hh = pins[label_of(key, a0, b0)]
            pins[label_of(key, a0, b0)] = (h, (a2, b2), hh)
            n += 1
    return write_pins(parse_pins(t.pins), pins), n


def pr2_texts(
    t: Texts, edited: str = "", extra15: str = "", extra_changed: tuple[str, ...] = ()
) -> Texts:
    """PR 2's view: the merge-base holds `15` as at the base (with the §C row `edited`'s target
    line altered by a later PR, when named) and PR 1's pins; the working tree has §C applied, the
    `15` cite moves recorded by `--repin-ruled`, and only `15` (plus the pins, plus
    `extra_changed`) differs."""
    t2 = t
    if edited:
        row = next(r for r in a_rows_export(t) if r["id"] == edited)
        sim = t.env.at_base(CAT_REL).replace(str(row["anchor"]), str(row["anchor"]) + " x", 1)
        t2 = with_text(with_text(t, t.env.base, CAT_REL, sim), HEAD_REF, CAT_REL, sim)
    memo = dict(t2.env.memo)
    memo[f"show:{t.env.base}:{PINS_REL}"] = t.pins
    t2 = replace(t2, env=Env(t.env.base, memo))
    rows = [r for r in a_rows_export(t2) if r["op"] != "confirm"]
    c15, _ = apply_rows(t2.env.at_base(CAT_REL), rows)
    pins, moves = record_moves(t2)
    changed = [CAT_REL, *extra_changed] + (
        [PINS_REL] if moves and PINS_REL not in extra_changed else []
    )
    return replace(t2, cat15=c15 + extra15, pins=pins, changed=changed)


def pr2_moved(
    t: Texts,
    unit_edit: bool = False,
    stray: bool = False,
    wrong_at: bool = False,
    hash_edit: str = "",
    drop: str = "",
) -> Texts:
    """PR 2 after a rebase that moved every D04 line down by one: the pins carry `@n` moves for
    the D04 cites (a `--repin-ruled` rewrite); the merge-base holds PR 1's pins. The flags plant
    one defect each."""
    shifted = "added line\n" + t.env.at_base(PATHS["D04"])
    t2 = with_text(t, t.env.base, PATHS["D04"], shifted)
    t2 = with_text(t2, HEAD_REF, PATHS["D04"], shifted)
    t2 = pr2_texts(t2, extra_changed=(PINS_REL,))  # the `15` moves recorded as PR 2 would
    moved: dict[str, CitePin] = {}
    first = True
    for label, (h, at, hh) in cite_pins(t2.pins).items():
        m = re.fullmatch(r"D04:(\d+)(?:–(\d+))?", label)
        if m:
            a = int(m[1]) + 1
            b = (int(m[2]) if m[2] else int(m[1])) + 1
            if wrong_at and first:
                a, b, first = a + 1, b + 1, False
            moved[label] = (h, (a, b), hh)
        elif label == hash_edit:
            moved[label] = (h[::-1] if h[::-1] != h else "0" * len(h), at, hh)
        elif label == drop:
            continue
        else:
            moved[label] = (h, at, hh)
    us = parse_pins(t2.pins)
    if unit_edit and us:
        us[0] = (us[0][0], us[0][1], us[0][2] + " x")
    pins = write_pins(us, moved) + ("# a stray line\n" if stray else "")
    return replace(t2, pins=pins)


M = Mutation
# grouped by gate, in the tool's order; §M lists them under the same numbers
MUTATIONS: tuple[Mutation, ...] = (
    M("G-TABLE", "give an inventory row a verdict outside the vocabulary",
      subst("| cut (RULED BQ-06) | `none` | one mutation from the pre-drop tree",
            "| snap (RULED BQ-06) | `none` | one mutation from the pre-drop tree")),
    M("G-TABLE", "drop BQ-22 from §R",
      subst("| BQ-22 | the nineteen contradictions", "| BQ-XX | the nineteen contradictions")),
    M("G-TABLE", "swap a ledger row's needle for one its cited line does not carry",
      subst("| L-2 | `E15-D14 fixes the curve` (`D04H`:88)", "| L-2 | `E15-D14 fixes the easing` (`D04H`:88)")),
    M("G-PROPERTY", "give the drop commit the property `width`",
      subst("| cut (RULED BQ-06) | `none` | one mutation from the pre-drop tree",
            "| cut (RULED BQ-06) | `width` | one mutation from the pre-drop tree")),
    M("G-PROPERTY", "make the ghost's fade a `transform`",
      subst("| fade | `opacity` | 0 → 1 over the B-1 pair; the rectangle",
            "| fade | `transform` | 0 → 1 over the B-1 pair; the rectangle")),
    M("G-TOKEN", "name a primitive no token file ships",
      subst("and `motion.duration.slow` nowhere (the §7.2 form",
            "and `motion.duration.quick` nowhere (the §7.2 form")),
    M("G-TOKEN", "put `motion.duration.normal` on a dock row",
      subst("| 0 → 1 over the B-1 pair; the rectangle is complete at frame 0",
            "| 0 → 1 over `motion.duration.normal` and the B-1 pair; the rectangle is complete at frame 0")),
    M("G-REDUCE", "keep an opacity change in the toast's reduce cell",
      subst("| `none` — the sentence in the region at frame 0 (D04's",
            "| fade only — the sentence in the region at frame 0 (D04's")),
    M("G-REDUCE", "point a proof row at a row the inventory lacks",
      subst("| P-40 | I-40 |", "| P-40 | I-41 |")),
    M("G-BINDING", "blank the MoveModeBar fade's binding cell",
      subst("| B-1 / B-2 (CR-1) | `D04`:397; `D04H`:91;", "| — | `D04`:397; `D04H`:91;")),
    M("G-BINDING", "type a pair by hand in B-1", anchor_edit("E05:4a.enter.duration", "`motion.duration.normal`")),
    M("G-SAFETY", "fade the environment badge in",
      subst("| cut (0 ms) in both modes | it moves inside the header",
            "| fade over `motion.duration.fast` | it moves inside the header")),
    M("G-SAFETY", "put the environment badge in the ghost's fading layer",
      subst("| CMP-214's ghost (the overlay layer) | fade |",
            "| CMP-214's ghost and the env badge (the overlay layer) | fade |")),
    M("G-SAFETY", "name the tray's tab in a fading row's surface",
      subst("| CMP-249 in the WorkspaceTabStrip's row (CMP-252; `D02`:777) | fade |",
            "| CMP-249 and the tray's tab in the WorkspaceTabStrip's row (CMP-252; `D02`:777) | fade |")),
    M("G-SAFETY", "drop the header exclusion from I-12's mount cell",
      subst("paints at frame 0 outside the fading layer | `none` — the panel at its place at frame 0",
            "paints at frame 0 with the body | `none` — the panel at its place at frame 0")),
    M("G-SAFETY", "let the refusal's card fade in with its scrim (I-30)",
      subst("the card and its focused control at frame 0, so the refusal never reads as lag",
            "the card and its focused control fade in with the scrim, so the refusal never reads as lag")),
    M("G-STRING", "alter one word of S-1",
      subst("| S-1 | \"Layout changed to Order-flow, 4 panels.\"", "| S-1 | \"Layout changed to Order-flow, 4 panel.\"")),
    M("G-CITE", "cite a line past the end of D04",
      subst("`D04`:133 (the 4 px outline and the panel sizes)", "`D04`:9999 (the 4 px outline and the panel sizes)")),
    M("G-CITE", "cite an unpinned line",
      subst("`D04`:133 (the 4 px outline and the panel sizes)", "`D04`:134 (the 4 px outline and the panel sizes)")),
    M("G-VERSION", "move the calendar's sprint length by one day at origin/main", head_sprint_days),
    M("G-AROW", "misquote a replace row's Old by one letter",
      subst("the timings are E15-D14's — PROPOSED): enter and leave as an `opacity` fade over `motion.duration.fast`, the move itself a cut;",
            "the timings are E15-D14's — PROPOSED): enter and leave as an `opacity` fade over `motion.duration.fast`, the move itself a cutt;")),
    M("G-AROW", "point a new-line row at a bullet that is not its entry's last",
      subst("| `15`:2787 | insert after |", "| `15`:2786 | insert after |")),
    M("G-AROW", "drop PROPOSED from a New line",
      subst("a menu that takes focus on opening is a cut, `16` §7.2 — PROPOSED): none; open and close",
            "a menu that takes focus on opening is a cut, `16` §7.2): none; open and close")),
    M("G-HYGIENE", "write a closing keyword against #368",
      subst("The closing line rides on PR 2 alone", "Closes #368")),
    M("G-HYGIENE", "leave a `{{` placeholder inside a code span of §0",
      subst("**Nothing here is built or published.**", "**Nothing here is built or published.** (`{{SHA:BASE}}`)")),
    M("G-HYGIENE", "simulate PR 2 with one byte more than §C in `15`", lambda t: pr2_texts(t, extra15="x")),
    M("G-HYGIENE", "simulate PR 2 with the spec changed beside the pins",
      lambda t: pr2_texts(t, extra_changed=(SPEC_REL, PINS_REL))),
    M("G-AROW+G-HYGIENE", "simulate PR 2 against a merge-base where a later PR edited a replace row's line",
      lambda t: pr2_texts(t, edited="A-1")),
    M("G-HYGIENE", "simulate PR 2 with a pins rewrite that alters a unit, not a cite move",
      lambda t: pr2_moved(t, unit_edit=True)),
    M("G-HYGIENE", "simulate PR 2 with a stray line in the pins beside the recorded moves",
      lambda t: pr2_moved(t, stray=True)),
    M("G-HYGIENE", "simulate PR 2 with a recorded @n the cite's content does not stand at",
      lambda t: pr2_moved(t, wrong_at=True)),
    M("G-HYGIENE+G-CITE", "simulate PR 2 with one cite pin's hash changed",
      lambda t: pr2_moved(t, hash_edit="E05D03:83")),
    M("G-HYGIENE+G-CITE", "simulate PR 2 with one cite pin dropped",
      lambda t: pr2_moved(t, drop="CONST:930")),
    M("G-RULED-PIN", "re-word one pinned sentence of §3",
      subst("E05-D03 is not edited. **Which mounts take B-3", "E05-D03 is never edited. **Which mounts take B-3")),
    M("G-AROW", "alter the ruled row's New outside A47's span",
      subst("E15-D14 §5 C-e). AM-8's \"Toasts\" landmark name rides DF-19;",
            "E15-D14 §5 C-e). AM-8's \"Toast\" landmark name rides DF-19;")),
    M("G-AROW", "drop A47's RULED stamp from the ruled row's From",
      subst("| C-e; RULED (orchestrator, 2026-10-30, #2701 ledger row A47 — 6524798809) |",
            "| C-e; ruled on #2701 |")),
    M("G-SAFETY", "bind the hidden panels' restore to B-1 (I-15 both pairs)",
      subst("| B-2 (CR-1)       | `D04`:397; `D04`:227; `D02`:387", "| B-1 / B-2 (CR-1) | `D04`:397; `D04`:227; `D02`:387")),
    M("G-SAFETY", "name the arm state in I-12's carrier cell without frame 0",
      subst("the header — heading, badge, arm state — and focus at frame 0, outside the fading layer; SR-11",
            "the header — heading, badge, arm state — and focus, with the body; SR-11")),
    M("G-HYGIENE", "simulate PR 2 with a `SHA:BASE` record that is no ancestor of its base",
      lambda t: anchor_edit("SHA:BASE", "0000000000")(pr2_texts(t))),
)  # fmt: skip

NEGATIVES: tuple[tuple[str, Callable[[Texts], Texts]], ...] = (
    ("N-1 PR 2 with §C applied exactly on the base", lambda t: pr2_texts(t)),
    ("N-2 PR 2 after a rebase moved D04, the pins recording the moves", lambda t: pr2_moved(t)),
)


def digest(t: Texts) -> str:
    return hashlib.sha256((t.spec + "\0" + t.pins).encode()).hexdigest()


def ascii_line(s: str) -> str:
    for a, b in (("→", "->"), ("›", ">"), ("…", "..."), ("—", "-"), ("–", "-"), ("×", "x"),
                 ("§", "S"), ("·", "|"), ("≤", "<="), ("≥", ">=")):  # fmt: skip
        s = s.replace(a, b)
    return s.encode("ascii", "replace").decode()[:110]


def selftest() -> tuple[bool, list[str]]:
    t0 = time.perf_counter()
    base = replace(load(), changed=[SPEC_REL])  # the PR-1 view; the PR-2 scenarios plant theirs
    disk = [hashlib.sha256(read_raw(r).encode()).hexdigest() for r in OWN_PATHS]
    before = digest(base)
    base_all = audit(base)
    base_found = [f for f in base_all if f.level == "FAIL"]
    # the head's own drift (a cited line moved at origin/main; #5055 not fetched) is a WARN on the
    # baseline too, so the negatives subtract it — never a FAIL, never another gate
    drift = {(f.gate, f.msg) for f in base_all if f.level == "WARN"}
    out = [
        f"self-test: baseline {len(base_found)} FAIL, {len(drift)} WARN (drift, subtracted from the negatives)"
    ]
    ok = not base_found
    for f in base_found:
        out.append(ascii_line(f"  baseline {f.gate}: {f.msg}"))
    for i, m in enumerate(MUTATIONS, 1):
        fails = [f for f in audit(m.apply(base)) if f.level == "FAIL"]
        gates = sorted({f.gate for f in fails})
        good = bool(fails) and gates == sorted(m.gate.split("+"))
        ok &= good
        out.append(
            ascii_line(
                f"{'ok  ' if good else 'FAIL'} M-{i} {m.gate}: {m.what} -> {', '.join(gates) or 'none'}"
            )
        )
    for name, scenario in NEGATIVES:
        extra = [
            f
            for f in audit(scenario(base))
            if f.level in ("FAIL", "WARN") and (f.gate, f.msg) not in drift
        ]
        ok &= not extra
        shown = ", ".join(sorted({f"{f.gate} ({f.level})" for f in extra})) or "none"
        out.append(ascii_line(f"{'ok  ' if not extra else 'FAIL'} {name} -> {shown}"))
        for f in extra[:3]:
            out.append(ascii_line(f"      {f.gate}: {f.msg}"))
    restored = digest(base) == before and disk == [
        hashlib.sha256(read_raw(r).encode()).hexdigest() for r in OWN_PATHS
    ]
    ok &= restored
    out.append(
        f"self-test: {len(MUTATIONS)} mutations, {len(NEGATIVES)} negatives, texts restored: {'yes' if restored else 'NO'}"
    )
    out.append(f"self-test: {'PASS' if ok else 'FAIL'} in {time.perf_counter() - t0:.1f} s")
    return ok, out


def render(found: list[Finding]) -> list[str]:
    return [ascii_line(f"{f.level} {f.gate}: {f.msg}") for f in found]


def pr2_mode(t: Texts) -> bool:
    return (
        bool(t.changed)
        and CAT_REL in (t.changed or [])
        and not any(p in PACK_TEXTS for p in t.changed or [])
    )


def main(argv: list[str]) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0] if __doc__ else "")
    g = ap.add_mutually_exclusive_group()
    g.add_argument("--check", action="store_true", help="the default mode")
    g.add_argument("--self-test", action="store_true")
    g.add_argument("--repin-ruled", action="store_true")
    g.add_argument("--a-rows", action="store_true")
    ap.add_argument("--json", action="store_true", help="--check's dump; alone it implies --check")
    ap.add_argument("--fill", action="store_true")
    a = ap.parse_args(argv)
    if a.self_test:
        ok, lines = selftest()
        print("\n".join(lines))
        return 0 if ok else 1
    t = load()
    if a.a_rows:
        print(json.dumps(a_rows_export(t), ensure_ascii=False, indent=2))
        return 0
    if a.repin_ruled:
        if unfilled(t.spec):
            print("refused: the spec has an unfilled placeholder (run --check --fill)")
            return 1
        other = [
            f
            for f in audit(t)
            if f.level == "FAIL"
            and f.gate not in ("G-RULED-PIN", "G-CITE")
            and not f.msg.startswith("cite ")
        ]
        if other:
            print(
                f"refused: {len(other)} FAIL outside the pins (first: {other[0].gate}: {other[0].msg[:80]}); fix them"
            )
            return 1
        if pr2_mode(t):
            pins, moves = record_moves(t)
            write_text(PINS_REL, pins)
            print(f"wrote {PINS_REL} (PR 2: {moves} cite move(s) recorded, units untouched)")
            return 0
        moved = [
            label_of(k, x, y) for k, x, y in all_cites(t) if resolve_cite(t, k, x, y)[2] == "moved"
        ]
        if moved:
            print(
                f"refused: {len(moved)} cite(s) moved; re-point them by content first ({moved[0]} ...)"
            )
            return 1
        write_text(PINS_REL, write_pins(units(t.spec, "spec"), fresh_cite_pins(t)))
        print(f"wrote {PINS_REL}")
        return 0
    if a.fill:
        spec, miss = fill(t.spec, t.values)
        write_text(SPEC_REL, spec)
        for m in miss:
            print(f"unfilled: {m}")
        t = load()
    timings: dict[str, float] = {}
    found = audit(t, timings)
    fails = [f for f in found if f.level == "FAIL"]
    if a.json:
        dump = {"base": t.env.base,
                "merged": {f"#{PR_NUMBER}": t.env.pr_sha(PR_NUMBER), f"#{PR2_NUMBER}": t.env.pr_sha(PR2_NUMBER)},
                "values": t.values,
                "findings": [{"level": f.level, "gate": f.gate, "msg": f.msg} for f in found],
                "timings_ms": {k: round(v * 1000, 1) for k, v in timings.items()}}  # fmt: skip
        print(json.dumps(dump, ensure_ascii=False, indent=2, sort_keys=True))
    else:
        for ln in render(found):
            print(ln)
        notes = sum(f.level == "NOTE" for f in found)
        warns = sum(f.level == "WARN" for f in found)
        print(f"{len(fails)} FAIL / {warns} WARN / {notes} NOTE ({len(GATES) + 1} gates)")
        print("timings: " + " ".join(f"{k}={v * 1000:.0f}ms" for k, v in timings.items())
              + f" total={sum(timings.values()) * 1000:.0f}ms")  # fmt: skip
    return 1 if fails else 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
