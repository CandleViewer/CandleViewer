"""E19-D02 wireframe-spec audit: default-deny gates over `docs/design/E19/E19-D02.md`.

Standalone, offline, stdlib only (`python3 -I`). Every gate reads the spec, the ruled-pins sidecar,
the plan documents at the pinned base and the E19-D01 memo at its pinned PR head through `git show`;
nothing is fetched. A gate passes only when its positive evidence is found (default-deny): a missing
section, table or anchor is a FAIL, never a skip.

Usage:
  python3 -I docs/design/_tools/e19_d02_wires_audit.py --check        exit 1 on any FAIL
  python3 -I docs/design/_tools/e19_d02_wires_audit.py --json         the report as JSON
  python3 -I docs/design/_tools/e19_d02_wires_audit.py --self-test    every mutation must FAIL its gate
  python3 -I docs/design/_tools/e19_d02_wires_audit.py --repin-ruled  rewrite the BQ-section pins

The memo pin (MEMO_HEAD) is the memo PR's merge commit (re-pinned from its PR head in the boards
PR; the memo is byte-identical between them); BASE moves with a rebase. The BQ list (BQ_LIST_ID)
is ruled by RULING_ID (ACCEPT 15 of 16, OVERRIDE BQ-2): the spec's BQ heading reads RULED and
`--repin-ruled` refreshes the sidecar. The BQ-2 override lets this ticket
add exactly one pointer line under SCR-038 and one under SCR-039 in `14` (POINTER_REL); G-UNTOUCHED
checks that diff line by line against the merge-base with origin/main (BASE when that is absent),
so the gate holds on a rebased or merged tree, not only at the pinned base. The boards PR may also
add the board PNGs (IMG_PREFIX), the board kit (KIT_REL) and that kit's lines in ALLOWED_EXTRA.
G-BOARDS takes a §0 row as PENDING or as drawn with its board id and its own PNG at the stated
size; once every board is drawn, the §0 heading no longer says PENDING.
"""

from __future__ import annotations

import argparse
import difflib
import json
import re
import struct
import subprocess
import sys
from collections.abc import Callable
from dataclasses import dataclass, field, replace
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
SPEC_REL = "docs/design/E19/E19-D02.md"
TOOL_REL = "docs/design/_tools/e19_d02_wires_audit.py"
PIN_REL = "docs/design/_tools/e19_d02_ruled_pins.txt"
OWN_PATHS = (SPEC_REL, TOOL_REL, PIN_REL)
# The boards PR's files beside the three above (G-UNTOUCHED).
IMG_PREFIX = "docs/design/E19/img/E19-D02-"
KIT_REL = "docs/design/_tools/sheets/e19-d02/"
ALLOWED_EXTRA = frozenset({".prettierignore", "docs/design/_tools/sheets/MANIFEST.sha256"})
DRAWN = re.compile(
    r"drawn: board id `[0-9a-f]{8}(?:-[0-9a-f]{4}){3}-[0-9a-f]{12}`, "
    r"`(docs/design/E19/img/E19-D02-(\d{2})-[a-z0-9-]+\.png)`, (\d+) × (\d+)"
)
POINTER_REL = "docs/plan/14-screens-catalogue.md"
POINTER_LINE = re.compile(
    r"^- \*\*Wireframes \(E19-D02\):\*\* \[E19-D02\.md\]\(\.\./design/E19/E19-D02\.md\) "
)
POINTER_SCREENS = ("### SCR-038 ", "### SCR-039 ")
BASE = "67fe8b526"
MEMO_HEAD = "b005ce610"  # PR #5381's merge commit; the PR head 94975537511c holds the same memo
MEMO_REL = "docs/design/research/e19-profiles.md"
BQ_LIST_ID = "6576276164"
RULING_ID: str | None = "6576655478"
RULED_OVERRIDES = frozenset({2})
BOARD_CAP = 10
WALK_CAP = 10
BQ_COUNT = 16
PD_COUNT = 8
MODES = ("Session", "Fixed range", "Visible range", "Anchored", "Composite")
KINDS = {
    "Session": "`session`",
    "Fixed range": "`fixed_range`",
    "Visible range": "`visible_range`",
    "Anchored": "A-1",
    "Composite": "`composite`",
}
NAMED_DOCS = {
    "MEMO": (MEMO_REL, MEMO_HEAD),
    "D05E16": ("docs/design/E16/E16-D05.md", BASE),
    "D02E17": ("docs/design/E17/E17-D02.md", BASE),
    "D09E09": ("docs/design/E09/E09-D09.md", BASE),
    "D04E11": ("docs/design/E11/E11-D04.md", BASE),
    "D02E13": ("docs/design/E13/E13-D02.md", BASE),
    "R32": (".claude/rules/32-design-specs.md", BASE),
    "README": ("docs/design/README.md", BASE),
    "E19J": ("docs/plan/backlog/E19.json", BASE),
}
# (document, line, a substring that must be on that line at its pinned revision)
KEY_CITES: tuple[tuple[str, int, str], ...] = (
    ("14", 83, "History starts <ts>"),
    ("14", 84, "last-good timestamp"),
    ("14", 85, "RBAC denies server-side"),
    ("14", 995, "Profile: BTCUSDT"),
    ("14", 996, "Visible range"),
    ("14", 1010, "Session multiples"),
    ("14", 1013, "5 000 rows"),
    ("14", 1016, "profile.period_changed"),
    ("14", 1017, "Design sign-off acceptance checklist"),
    ("14", 1022, "VA % between 1 and 100"),
    ("14", 1027, "profile.settings_changed"),
    ("14", 1028, "Design sign-off acceptance checklist"),
    ("14", 2731, "profile.created"),
    ("22", 4843, "single-step"),
    ("22", 4854, "enum: [volume, delta, tpo]"),
    ("22", 4873, "maximum: 1000"),
    ("22", 4876, "minimum: 50, maximum: 95"),
    ("22", 4884, "marketdata:read"),
    ("22", 20291, "ProfileRow:"),
    ("22", 20299, "tpo_count"),
    ("22", 10760, "/indicator-presets:"),
    ("23", 753, "1 000 ms"),
    ("23", 1346, "1 000 ms"),
    ("23", 1368, "degraded_topics"),
    ("24", 921, "two_row_t"),
    ("24", 968, '"bar","rolling"'),
    ("24", 981, "trade_count"),
    ("24", 987, "tick_size"),
    ("24", 989, "aggregation_ticks"),
    ("24", 1002, "complete: bool"),
    ("24", 1009, "68 %"),
    ("26", 214, "priceLow, priceHigh"),
    ("26", 221, "log mode"),
    ("26", 228, "once per frame"),
    ("26", 229, "once per frame"),
    ("26", 238, "2 px"),
    ("26", 377, "shares the price scale"),
    ("26", 526, "ProfileOptions"),
    ("16", 129, "Compact"),
    ("16", 130, "Comfortable"),
    ("16", 141, "spacing-token resolution only"),
    ("16", 146, "`dense`"),
    ("16", 270, "1280×800"),
    ("05", 151, "1 update / 2s"),
    ("05", 179, "In VA"),
    ("05", 208, "10 px"),
    ("11", 1724, "55 fps"),
    ("11", 1730, "10 Hz"),
    ("11", 1747, "covered range"),
    ("11", 1821, "zero net delta"),
    ("11", 1859, "clamped to one tick"),
    ("20", 865, "demo has no separate public feed"),
    ("15", 2380, "periodType"),
    ("15", 2426, "percent"),
    ("15", 2948, '"footprint"|"heatmap"|"candles"|"theme"'),
    ("D05E16", 214, "Record this symbol"),
    ("D05E16", 417, "History starts {ts} — recording began then."),
    ("D05E16", 418, "recording has not begun yet."),
    ("D05E16", 424, "Nothing is missing or broken"),
    ("D05E16", 457, "Partial: {n} of {m} requested days recorded"),
    ("D05E16", 459, "Gaps excluded: {k} ranges, {duration}"),
    ("D02E17", 221, "1 s refresh"),
    ("D09E09", 90, "Only the owner can {verb}."),
    ("D09E09", 95, "Read-only while viewing as {user}."),
    ("MEMO", 163, "labelled-vs-implied"),
    ("MEMO", 177, "`rolling`"),
    ("MEMO", 209, "PD-1"),
    ("MEMO", 242, "50–95"),
    ("MEMO", 260, "A-1"),
    ("E19J", 68, '"E19-D02"'),
    ("R32", 79, "R6"),
    ("R32", 81, "R7"),
    ("README", 14, "boards"),
    ("README", 77, "SCR-nnn/<state>"),
)
UNTOUCHED_PREFIXES = ("docs/plan/", "docs/design/research/", ".claude/", "CONSTITUTION.md")

# Public-text deny list, assembled from fragments so this file never carries the literals.
_KW = "|".join(("clo" + "se[sd]?", "fi" + "x(?:e[sd])?", "reso" + "lve[sd]?"))
CLOSING = re.compile(r"\b(?:" + _KW + r")\b\s*:?\s*#\d+", re.IGNORECASE)
WHAT_FIXES = re.compile(r"^#+\s*Wh" + r"at this\b.*\bfi" + r"xes\b", re.IGNORECASE | re.MULTILINE)
DENY_FRAGMENTS = (
    "/ho" + "me/",
    "/t" + "mp/",
    "pen" + "pot.candle",
    "rel" + "ay.candle",
    "hcl" + "-worker",
    "hpe" + "-worker",
    "An" + "vil",
    "scr" + "atch-an" + "vil",
)
URL = re.compile(r"\bhttps?://|\bwww\.[a-z]", re.IGNORECASE)
HEX40 = re.compile(r"\b[0-9a-f]{40}\b")
COMMENT = re.compile(r"<!--(.*?)-->", re.DOTALL)
COMMENT_OPEN = re.compile(r"<!--(?!.*?-->)", re.DOTALL)
ANCHOR_BODY = re.compile(r"^ audit:([a-z_]+)=([0-9a-f]+) $")
FENCE = re.compile(r"^```.*?^```[ \t]*$", re.DOTALL | re.MULTILINE)
DOC_TOKEN = r"(?:`(?P<nn>\d\d)`|(?P<named>" + "|".join(NAMED_DOCS) + r"))"
CITE = re.compile(
    DOC_TOKEN + r" ?:(?P<first>\d+)(?:–(?P<firstend>\d+))?(?P<more>(?:, :\d+(?:–\d+)?)*)"
)
MORE = re.compile(r":(\d+)(?:–(\d+))?")
FRAME = re.compile(r"`(SCR-03[89]/[a-z0-9-]+)`")
W_REF = re.compile(r"\bW-(\d+)\b")
ROW_ID = re.compile(r"\bD02-(C|G|A|OQ)(\d+)\b")
TICKET = re.compile(r"\bE\d\d-[A-Z]\d\d\b")


@dataclass
class Ctx:
    spec: str
    pins: str
    tool: str
    changed: list[str]
    sources: dict[str, list[str]] = field(default_factory=dict)
    keys: frozenset[str] = frozenset()
    pointer: tuple[list[str], list[str]] = field(default_factory=lambda: ([], []))


@dataclass
class Result:
    gate: str
    ok: bool
    detail: list[str]


def git(*args: str) -> tuple[int, str]:
    proc = subprocess.run(
        ["git", *args],
        cwd=ROOT,
        capture_output=True,
        text=True,
        encoding="utf-8",
        check=False,
    )
    return proc.returncode, proc.stdout


def show(rev: str, rel: str) -> str | None:
    code, out = git("show", f"{rev}:{rel}")
    return out if code == 0 else None


def plan_rel(nn: str) -> str | None:
    code, out = git("ls-tree", "--name-only", BASE, "docs/plan/")
    if code != 0:
        return None
    for line in out.splitlines():
        name = line.rsplit("/", 1)[-1]
        if name.startswith(nn + "-") and name.endswith((".md", ".yaml")):
            return line
    return None


def load_sources(doc_ids: set[str]) -> dict[str, list[str]]:
    out: dict[str, list[str]] = {}
    for doc in sorted(doc_ids):
        if doc in NAMED_DOCS:
            rel, rev = NAMED_DOCS[doc]
            text = show(rev, rel)
        else:
            prel = plan_rel(doc)
            text = show(BASE, prel) if prel else None
        if text is not None:
            out[doc] = text.splitlines()
    return out


def backlog_keys() -> frozenset[str]:
    code, out = git("grep", "-h", "-o", '"key": "E[0-9][0-9]-[A-Z][0-9][0-9]"', BASE, "--")
    if code != 0:
        return frozenset()
    return frozenset(TICKET.findall(out))


def diff_base() -> str:
    """The merge-base with origin/main, so a merged or rebased tree diffs only this branch's own
    changes; BASE when origin/main (or a merge-base with it) is absent."""
    code, out = git("merge-base", "HEAD", "origin/main")
    return out.strip() if code == 0 and out.strip() else BASE


def changed_paths(rev: str) -> list[str]:
    _, tracked = git("diff", "--name-only", rev, "--")
    _, untracked = git("ls-files", "--others", "--exclude-standard")
    return sorted({p for p in (tracked + untracked).splitlines() if p})


def read(rel: str) -> str:
    path = ROOT / rel
    return path.read_text(encoding="utf-8") if path.exists() else ""


def build_ctx() -> Ctx:
    spec = read(SPEC_REL)
    docs = {m.group("nn") or m.group("named") for m in CITE.finditer(spec)}
    docs |= {d for d, _, _ in KEY_CITES}
    rev = diff_base()
    return Ctx(
        spec=spec,
        pins=read(PIN_REL),
        tool=read(TOOL_REL),
        changed=changed_paths(rev),
        sources=load_sources(docs),
        keys=backlog_keys(),
        pointer=((show(rev, POINTER_REL) or "").splitlines(), read(POINTER_REL).splitlines()),
    )


# ---------------------------------------------------------------- parsing helpers


def section(text: str, heading_start: str) -> str:
    """The body under the first heading line starting with `heading_start`, to the next peer."""
    lines = text.splitlines()
    for i, line in enumerate(lines):
        if line.startswith(heading_start):
            level = len(line) - len(line.lstrip("#"))
            body: list[str] = []
            for nxt in lines[i + 1 :]:
                stripped = nxt.lstrip("#")
                if (
                    nxt.startswith("#")
                    and len(nxt) - len(stripped) <= level
                    and stripped[:1] == " "
                ):
                    break
                body.append(nxt)
            return "\n".join(body)
    return ""


def unfenced(text: str) -> str:
    return FENCE.sub("", text)


def table_rows(text: str) -> list[list[str]]:
    rows: list[list[str]] = []
    for line in unfenced(text).splitlines():
        if not line.startswith("|"):
            continue
        cells = [c.strip() for c in line.strip().strip("|").split("|")]
        if all(set(c) <= set("-: ") for c in cells):
            continue
        rows.append(cells)
    return rows[1:] if rows else rows  # drop the header


def anchors(text: str) -> dict[str, str]:
    out: dict[str, str] = {}
    for m in COMMENT.finditer(text):
        a = ANCHOR_BODY.match(m.group(1))
        if a:
            out[a.group(1)] = a.group(2)
    return out


def bq_section(spec: str) -> tuple[str, str]:
    for line in spec.splitlines():
        if line.startswith("## The questions BQ-0"):
            return line, section(spec, line)
    return "", ""


# ---------------------------------------------------------------- gates


def g_pin(c: Ctx) -> list[str]:
    bad: list[str] = []
    a = anchors(c.spec)
    if a.get("memo_head") != MEMO_HEAD:
        bad.append(f"memo_head anchor {a.get('memo_head')!r} != {MEMO_HEAD}")
    if a.get("base") != BASE:
        bad.append(f"base anchor {a.get('base')!r} != {BASE}")
    if f"`{MEMO_HEAD}`" not in c.spec or "re-pinned to its merge commit" not in c.spec:
        bad.append("the memo pin and its re-pinned-to-the-merge-commit sentence must be stated")
    if "MEMO" not in c.sources:
        bad.append(f"{MEMO_REL} not readable at {MEMO_HEAD} (fetch the memo PR head)")
    for text, name in ((c.spec, "spec"), (c.pins, "pins")):
        if HEX40.search(text):
            bad.append(f"a 40-hex sha in the {name}; pin short shas only")
    return bad


def g_cite(c: Ctx) -> list[str]:
    bad: list[str] = []
    found = 0
    for m in CITE.finditer(c.spec):
        doc = m.group("nn") or m.group("named")
        lines = c.sources.get(doc)
        spans = [(int(m.group("first")), int(m.group("firstend") or m.group("first")))]
        spans += [(int(a), int(b or a)) for a, b in MORE.findall(m.group("more"))]
        for lo, hi in spans:
            found += 1
            if lines is None:
                bad.append(f"{doc}:{lo} — document not readable at its pin")
            elif not 1 <= lo <= hi <= len(lines):
                bad.append(f"{doc}:{lo}–{hi} — outside the document ({len(lines)} lines)")
    if found < 100:
        bad.append(f"only {found} cites parsed; the cite grammar is broken")
    for doc, n, needle in KEY_CITES:
        lines = c.sources.get(doc)
        if lines is None or n > len(lines) or needle not in lines[n - 1]:
            bad.append(f"{doc}:{n} no longer carries {needle!r} (re-pin the cite)")
    return bad


def g_bq(c: Ctx) -> list[str]:
    bad: list[str] = []
    head, body = bq_section(c.spec)
    if RULING_ID is None:
        want = (
            "## The questions BQ-0 … BQ-15 — defaults built; ruling pending "
            f"(comment {BQ_LIST_ID})"
        )
    else:
        want = f"## The questions BQ-0 … BQ-15 — RULED (comment {RULING_ID})"
    if head != want:
        bad.append(f"BQ heading must read {want!r}")
    bullets = re.findall(r"^- \*\*BQ-(\d+) — [^*]+\.\*\* (.*)$", body, re.MULTILINE)
    if [int(n) for n, _ in bullets] != list(range(BQ_COUNT)):
        bad.append(f"BQ bullets must be BQ-0 … BQ-{BQ_COUNT - 1} in order")
    if RULING_ID is not None and (BQ_LIST_ID not in body or f"comment {RULING_ID}" not in body):
        bad.append(f"the BQ section must cite the list {BQ_LIST_ID} and the ruling {RULING_ID}")
    for n, text in bullets:
        if RULING_ID is None and not text.startswith("ORCH-default:"):
            bad.append(f"BQ-{n} must state its ORCH-default")
        if RULING_ID is not None:
            verdict = "OVERRIDE" if int(n) in RULED_OVERRIDES else "ACCEPT"
            if not text.startswith(f"RULED: {verdict}."):
                bad.append(f"BQ-{n} must open with 'RULED: {verdict}.' (comment {RULING_ID})")
        if "Built as:" not in text:
            bad.append(f"BQ-{n} must say what is built")
    return bad


def pins_text(spec: str) -> str:
    head, body = bq_section(spec)
    lines = [
        "# E19-D02 pins: the BQ section of the spec, verbatim (heading + body).",
        "# Written by `--repin-ruled` only; `--check` reads it (never hand-edit; G-RULED).",
        head,
        body.strip("\n"),
    ]
    return "\n".join(lines) + "\n"


def g_ruled(c: Ctx) -> list[str]:
    if not bq_section(c.spec)[0]:
        return ["no BQ section to pin"]
    if c.pins != pins_text(c.spec):
        return [f"{PIN_REL} differs from the spec's BQ section (run --repin-ruled after a ruling)"]
    return []


def board_rows(spec: str) -> list[list[str]]:
    return [r for r in table_rows(section(spec, "## 0.")) if len(r) == 4]


def not_drawn(spec: str) -> list[str]:
    for line in section(spec, "## 0.").splitlines():
        if line.startswith("**Not drawn — the text is binding**"):
            return FRAME.findall(line)
    return []


def g_boards(c: Ctx) -> list[str]:
    bad: list[str] = []
    rows = board_rows(c.spec)
    if not rows:
        return ["no board table in §0"]
    if len(rows) > BOARD_CAP:
        bad.append(f"{len(rows)} boards > cap {BOARD_CAP}")
    if anchors(c.spec).get("boards") != str(len(rows)):
        bad.append(f"boards anchor != {len(rows)} table rows")
    for i, row in enumerate(rows, 1):
        if row[0] != f"{i:02d}":
            bad.append(f"board number {row[0]} out of sequence")
        if not row[1].startswith(f"`E19-D02 / {i:02d} "):
            bad.append(f"board {row[0]} name must be `E19-D02 / NN slug`")
        if row[3] == "PENDING":
            continue
        m = DRAWN.fullmatch(row[3])
        if not m:
            bad.append(f"board {row[0]} status {row[3]!r}; PENDING or drawn with its PNG")
            continue
        rel, nn, w, h = m.group(1), m.group(2), int(m.group(3)), int(m.group(4))
        slug = row[1].strip("`").split(" ", 3)[-1]
        png = ROOT / rel
        if nn != row[0] or not rel.endswith(f"-{slug}.png") or not png.is_file():
            bad.append(f"board {row[0]}: no PNG {rel} for {row[1]}")
            continue
        head = png.read_bytes()[:24]
        if head[:8] != b"\x89PNG\r\n\x1a\n" or struct.unpack(">II", head[16:24]) != (w, h):
            bad.append(f"board {row[0]}: {rel} is not a {w} × {h} PNG")
    heading = next((ln for ln in c.spec.splitlines() if ln.startswith("## 0.")), "")
    if all(r[3] != "PENDING" for r in rows) and "PENDING" in heading:
        bad.append("every board is drawn but the §0 heading says PENDING")
    twins = sum(1 for r in rows if "light" in r[1])
    if twins * 3 > len(rows):
        bad.append("light twins exceed one third")
    if "Not drawn — the text is binding" not in c.spec:
        bad.append("the not-drawn line is missing")
    return bad


def g_states(c: Ctx) -> list[str]:
    bad: list[str] = []
    planned: list[str] = []
    for row in board_rows(c.spec):
        planned += FRAME.findall(row[2])
    planned += not_drawn(c.spec)
    dupes = sorted({f for f in planned if planned.count(f) > 1})
    if dupes:
        bad.append(f"frames planned twice: {dupes}")
    zero = c.spec.split("## 0.", 1)
    rest = zero[1].split("## 1.", 1)[1] if len(zero) == 2 and "## 1." in zero[1] else ""
    used = set(FRAME.findall(rest))
    if not used:
        bad.append("no frame named outside §0")
    for f in sorted(used - set(planned)):
        bad.append(f"{f} is specified but on no board and not in the not-drawn list (R4)")
    for f in sorted(set(planned) - used):
        bad.append(f"{f} is planned in §0 but specified nowhere (R4)")
    return bad


def g_pd(c: Ctx) -> list[str]:
    bad: list[str] = []
    rows = table_rows(section(c.spec, "## 14."))
    ids = [r[0] for r in rows]
    if ids != [f"PD-{i}" for i in range(1, PD_COUNT + 1)]:
        bad.append(f"PD trace rows {ids} != PD-1 … PD-{PD_COUNT}")
    for r in rows:
        if len(r) != 4 or "§" not in r[1] or not r[3].startswith("PASS"):
            bad.append(f"{r[0]}: needs a § location and a PASS status")
    memo = "\n".join(c.sources.get("MEMO", []))
    for i in range(1, PD_COUNT + 1):
        if f"| PD-{i} |" not in memo:
            bad.append(f"PD-{i} not in the memo at {MEMO_HEAD}")
    return bad


def g_modes(c: Ctx) -> list[str]:
    rows = table_rows(section(c.spec, "### 5.1"))
    words = tuple(r[0] for r in rows)
    bad: list[str] = []
    if words != MODES:
        bad.append(f"mode words {words} != {MODES} (PD-6)")
    for r in rows:
        if r[0] in KINDS and KINDS[r[0]] not in r[1]:
            bad.append(f"{r[0]} must carry its kind {KINDS[r[0]]}")
    return bad


def copy_rows(spec: str) -> list[list[str]]:
    return [r for r in table_rows(section(spec, "## 12.")) if r and r[0].startswith("W-")]


def g_copy(c: Ctx) -> list[str]:
    bad: list[str] = []
    rows = copy_rows(c.spec)
    ids = [int(r[0][2:]) for r in rows]
    if ids != list(range(1, len(ids) + 1)) or not ids:
        bad.append("W ids must run W-1 … W-n without gaps")
    defined = set(ids)
    outside = c.spec.replace(section(c.spec, "## 12."), "")
    referenced = {int(n) for n in W_REF.findall(outside)}
    for n in sorted(referenced - defined):
        bad.append(f"W-{n} referenced but not in the deck")
    for n in sorted(defined - referenced):
        bad.append(f"W-{n} defined but used nowhere")
    for r in rows:
        if len(r) != 4 or not r[3].startswith("verbatim"):
            continue
        m = CITE.match(r[2])
        quoted = re.match(r'"([^"]+)"', r[1])
        if not m or not quoted:
            bad.append(f"{r[0]}: a verbatim row needs one cite and one quoted string")
            continue
        lines = c.sources.get(m.group("nn") or m.group("named"), [])
        n = int(m.group("first"))
        if n > len(lines) or quoted.group(1) not in lines[n - 1]:
            bad.append(f"{r[0]}: {quoted.group(1)!r} is not verbatim on its cited line")
    return bad


def g_t2(c: Ctx) -> list[str]:
    bad: list[str] = []
    body = section(c.spec, "### 1.4")
    d09 = c.sources.get("D09E09", [])
    keys = {m for line in d09[80:100] for m in re.findall(r"^\| `(rbac\.[a-z_]+)`", line)}
    verbs = "\n".join(d09[98:120])
    used = re.findall(r"`(rbac\.[a-z_]+)`", body)
    if not used:
        bad.append("§1.4 names no reason key")
    for k in used:
        if k not in keys:
            bad.append(f"{k} is not a D09E09 §3.1 key")
    for verb in re.findall(r'verb "([^"]+)"', body):
        if f'`recording:write` → "{verb}"' not in verbs:
            bad.append(f"verb {verb!r} is not D09E09 §3.2's for recording:write")
        w14 = [r for r in copy_rows(c.spec) if r[0] == "W-14"]
        if not w14 or w14[0][1] != f'"Only the owner can {verb}."':
            bad.append("W-14 must be rbac.owner_only with the §3.2 verb")
    for need in ('aria-disabled="true"', "never `disabled`", "aria-describedby", "G-T2.5"):
        if need not in body:
            bad.append(f"§1.4 lacks {need!r}")
    for frame in ("SCR-038/no-history-sentence", "SCR-038/no-history-view-as"):
        row = [r for r in table_rows(section(c.spec, "## 6.")) if r[0] == f"`{frame}`"]
        if not row or "T2 (§1.4)" not in row[0][2]:
            bad.append(f"{frame} must name T2 (§1.4) (G-T2.6)")
    nine = section(c.spec, "## 9.")
    if not re.search(r"`SCR-039/view-as`\): \*\*T2 \(§1\.4\)\*\*", nine):
        bad.append("SCR-039/view-as must name T2 (§1.4) (G-T2.6)")
    return bad


def g_ann(c: Ctx) -> list[str]:
    bad: list[str] = []
    if "R-4 Announcements ≤ 1 Hz" not in c.spec:
        bad.append("R-4 (announcements ≤ 1 Hz) missing")
    cells = [r[-1] for r in table_rows(section(c.spec, "## 6."))]
    cells += [r[-1] for r in table_rows(section(c.spec, "### 8.3"))]
    if len(cells) < 10:
        bad.append("announcement columns not found")
    for cell in cells:
        if not (cell.startswith("none") or "once" in cell):
            bad.append(f"announcement {cell!r} is neither none nor once (R-4)")
    return bad


def g_c211(c: Ctx) -> list[str]:
    body = section(c.spec, "### 1.3")
    need = ("C-2.11", "no DEMO / LIVE badge", "no environment control", "no account context")
    return [f"R-1 lacks {n!r}" for n in need if n not in body]


def g_rows(c: Ctx) -> list[str]:
    bad: list[str] = []
    defined: dict[str, int] = {}
    for sub, kind in (("### 13.1", "C"), ("### 13.2", "G"), ("### 13.3", "A"), ("### 13.4", "OQ")):
        rows = table_rows(section(c.spec, sub))
        ids = [r[0] for r in rows]
        if ids != [f"D02-{kind}{i}" for i in range(1, len(ids) + 1)] or not ids:
            bad.append(f"{sub} ids {ids} are not D02-{kind}1 … in order")
        for r in rows:
            defined[r[0]] = defined.get(r[0], 0) + 1
            owner = r[-1]
            tickets = TICKET.findall(owner)
            if not tickets and "owner" not in owner:
                bad.append(f"{r[0]}: owner {owner!r} names no ticket and not the owner")
            for t in tickets:
                if t not in c.keys:
                    bad.append(f"{r[0]}: {t} is not a backlog ticket")
    for kind, n in ROW_ID.findall(c.spec):
        if f"D02-{kind}{n}" not in defined:
            bad.append(f"D02-{kind}{n} referenced but not defined")
    return bad


def g_walk(c: Ctx) -> list[str]:
    items = re.findall(r"^(\d+)\. ", section(c.spec, "### 16.2"), re.MULTILINE)
    if not items or len(items) > WALK_CAP:
        return [f"walkthrough has {len(items)} items (1 … {WALK_CAP})"]
    return []


def g_heur(c: Ctx) -> list[str]:
    rows = table_rows(section(c.spec, "### 16.1"))
    bad = [f"{r[0]} is not marked (heuristic)" for r in rows if not r[1].startswith("(heuristic)")]
    return bad if rows else ["no heuristic table"]


def pointer_diff(c: Ctx) -> list[str]:
    """The BQ-2 override: exactly one inserted pointer line under SCR-038 and one under SCR-039."""
    base, cur = c.pointer
    if not base or not cur:
        return [f"{POINTER_REL} not readable at the diff base and in the worktree"]
    bad: list[str] = []
    inserted: list[int] = []
    for op, i1, i2, j1, j2 in difflib.SequenceMatcher(
        None, base, cur, autojunk=False
    ).get_opcodes():
        if op == "insert":
            inserted += range(j1, j2)
        elif op != "equal":
            bad.append(
                f"{POINTER_REL}: base lines {i1 + 1}–{i2} {op}d; only insertions are allowed"
            )
    screens: list[str] = []
    for j in inserted:
        if not POINTER_LINE.match(cur[j]):
            bad.append(f"{POINTER_REL}:{j + 1} is not an E19-D02 pointer line")
        heads = [ln for ln in cur[:j] if ln.startswith("### ")]
        screens.append(heads[-1] if heads else "")
    got = [next((s for s in POINTER_SCREENS if h.startswith(s)), h) for h in screens]
    if got != list(POINTER_SCREENS):
        bad.append(f"{POINTER_REL}: the pointer lines must be one under SCR-038, one under SCR-039")
    return bad


def g_untouched(c: Ctx) -> list[str]:
    bad: list[str] = []
    for p in c.changed:
        if p == POINTER_REL:
            bad += pointer_diff(c)
        elif p in ALLOWED_EXTRA or p.startswith((IMG_PREFIX, KIT_REL)):
            continue
        elif p not in OWN_PATHS:
            bad.append(f"{p} changed; this ticket writes only {', '.join(OWN_PATHS)}")
        elif p.startswith(UNTOUCHED_PREFIXES):
            bad.append(f"{p} is an owner document")
    return bad


def g_public(c: Ctx) -> list[str]:
    bad: list[str] = []
    for name, text in (("spec", c.spec), ("pins", c.pins), ("tool", c.tool)):
        if CLOSING.search(text):
            bad.append(f"{name}: a closing keyword followed by an issue number")
        if WHAT_FIXES.search(text):
            bad.append(f"{name}: a 'What this … fixes' heading")
        for frag in DENY_FRAGMENTS:
            if frag in text:
                bad.append(f"{name}: a denied fragment (host, path or worker name)")
        if name != "tool" and URL.search(text):
            bad.append(f"{name}: a URL")
    return bad


def g_comment(c: Ctx) -> list[str]:
    bad: list[str] = []
    for m in COMMENT.finditer(c.spec):
        if not ANCHOR_BODY.match(m.group(1)):
            bad.append(f"hidden comment {m.group(0)[:40]!r}; only audit anchors are allowed")
    if COMMENT_OPEN.search(COMMENT.sub("", c.spec)):
        bad.append("an unterminated comment")
    if re.search("[\\u00ad\\u200b-\\u200d\\u2060\\ufeff]", c.spec):
        bad.append("an invisible character")
    return bad


GATES: dict[str, Callable[[Ctx], list[str]]] = {
    "G-PIN": g_pin,
    "G-CITE": g_cite,
    "G-BQ": g_bq,
    "G-RULED": g_ruled,
    "G-BOARDS": g_boards,
    "G-STATES": g_states,
    "G-PD": g_pd,
    "G-MODES": g_modes,
    "G-COPY": g_copy,
    "G-T2": g_t2,
    "G-ANN": g_ann,
    "G-C211": g_c211,
    "G-ROWS": g_rows,
    "G-WALK": g_walk,
    "G-HEUR": g_heur,
    "G-UNTOUCHED": g_untouched,
    "G-PUBLIC": g_public,
    "G-COMMENT": g_comment,
}


def run(c: Ctx) -> list[Result]:
    out: list[Result] = []
    for name, gate in GATES.items():
        try:
            detail = gate(c)
        except (IndexError, KeyError, ValueError) as exc:  # default-deny: a crash is a FAIL
            detail = [f"gate raised {type(exc).__name__}: {exc}"]
        out.append(Result(name, not detail, detail))
    return out


# ---------------------------------------------------------------- self-test


def sub_spec(old: str, new: str) -> Callable[[Ctx], Ctx]:
    def apply(c: Ctx) -> Ctx:
        if old not in c.spec:
            raise ValueError(f"mutation anchor missing: {old[:50]!r}")
        return replace(c, spec=c.spec.replace(old, new, 1))

    return apply


def sub_re(pattern: str, new: str) -> Callable[[Ctx], Ctx]:
    def apply(c: Ctx) -> Ctx:
        spec, n = re.subn(pattern, new, c.spec, count=1)
        if not n:
            raise ValueError(f"mutation pattern missing: {pattern[:50]!r}")
        return replace(c, spec=spec)

    return apply


def sub_both(old: str, new: str) -> Callable[[Ctx], Ctx]:
    def apply(c: Ctx) -> Ctx:
        spec = sub_spec(old, new)(c).spec
        return replace(c, spec=spec, pins=pins_text(spec))

    return apply


def set_pins(c: Ctx) -> Ctx:
    return replace(c, pins=c.pins + "x\n")


def add_changed(c: Ctx) -> Ctx:
    return replace(c, changed=[*c.changed, "docs/plan/22-api-openapi.yaml"])


def other_png(c: Ctx) -> Ctx:
    return replace(c, changed=[*c.changed, "docs/design/E19/img/E19-D03-01-x.png"])


def extra_pointer(c: Ctx) -> Ctx:
    base, cur = c.pointer
    if not cur:
        raise ValueError(f"{POINTER_REL} not loaded")
    return replace(
        c,
        changed=sorted({*c.changed, POINTER_REL}),
        pointer=(base, [*cur, "- **Wireframes (E19-D02):** a requirement change"]),
    )


def drift_source(c: Ctx) -> Ctx:
    lines = list(c.sources["22"])
    lines[4875] = lines[4875].replace("maximum: 95", "maximum: 99")
    return replace(c, sources={**c.sources, "22": lines})


_CLOSE = "Clo" + "ses #" + "416"
_HOST = "pen" + "pot.candle" + "viewer.example"
_HEAD = "\n## Wh" + "at this PR fi" + "xes\n"

MUTATIONS: tuple[tuple[str, str, Callable[[Ctx], Ctx]], ...] = (
    ("M-1", "G-PIN", sub_spec("memo_head=b005ce610", "memo_head=94975537511c")),
    ("M-2", "G-PIN", sub_spec("re-pinned to its merge commit", "stays pinned")),
    ("M-3", "G-PIN", sub_spec("**Inputs pinned.**", "**Inputs pinned.** " + "ab" * 20 + ".")),
    ("M-4", "G-CITE", sub_spec("(`22`:4876; MEMO C-2)", "(`22`:99999; MEMO C-2)")),
    ("M-5", "G-CITE", drift_source),
    ("M-6", "G-BQ", sub_both("Built as: §2; D02-C5.", "Then §2; D02-C5.")),
    ("M-7", "G-RULED", set_pins),
    ("M-8", "G-BOARDS", sub_re(r"(`SCR-038/table`\s+\| )drawn: board id", r"\1DRAWN: board id")),
    ("M-9", "G-BOARDS", sub_spec("audit:boards=10 ", "audit:boards=11 ")),
    ("M-10", "G-STATES", sub_spec("`SCR-038/load-failed`, ", "")),
    (
        "M-11",
        "G-STATES",
        sub_spec("### 10.5 The E40 slot\n", "### 10.5 The E40 slot\n\n`SCR-038/ghost`\n"),
    ),
    ("M-12", "G-PD", sub_spec("| PD-6 |", "| PD-9 |")),
    ("M-13", "G-MODES", sub_spec("| Anchored ", "| Swing-anchored ")),
    (
        "M-14",
        "G-COPY",
        sub_spec('"Partial: {n} of {m} requested', '"Partial: only {n} of {m} requested'),
    ),
    ("M-15", "G-COPY", sub_spec("### 10.5 The E40 slot\n", "### 10.5 The E40 slot\n\nSee W-77.\n")),
    ("M-16", "G-T2", sub_spec("| `rbac.view_as`: W-15, one", "| `rbac.viewas`: W-15, one")),
    ("M-17", "G-T2", sub_spec('verb "change recording"', 'verb "manage recording"')),
    (
        "M-18",
        "G-T2",
        sub_spec("| **T2 (§1.4)**, the sentence form: heading", "| the sentence form: heading"),
    ),
    ("M-19", "G-ANN", sub_spec("| W-23 once ", "| per keystroke ")),
    ("M-20", "G-C211", sub_spec("carries **no DEMO / LIVE badge", "carries **a small badge")),
    ("M-21", "G-ROWS", sub_spec("| D02-C4  |", "| D02-C3  |")),
    ("M-22", "G-ROWS", sub_spec("| E19-T04 (the `26` owner) |", "| E19-Z99 (the `26` owner) |")),
    (
        "M-23",
        "G-WALK",
        sub_spec("10. Review the ten boards", "10. Review.\n11. Review the ten boards"),
    ),
    ("M-24", "G-HEUR", sub_spec("| (heuristic) Error prevention", "| Error prevention")),
    ("M-25", "G-UNTOUCHED", add_changed),
    ("M-26", "G-PUBLIC", sub_spec("**Inputs pinned.**", _CLOSE + " **Inputs pinned.**")),
    ("M-27", "G-PUBLIC", sub_spec("**Inputs pinned.**", _HOST + " **Inputs pinned.**")),
    ("M-28", "G-PUBLIC", sub_spec("\n## 1. Purpose", _HEAD + "\n## 1. Purpose")),
    ("M-29", "G-COMMENT", sub_spec("**Inputs pinned.**", "<!-- a\nnote --> **Inputs pinned.**")),
    ("M-30", "G-UNTOUCHED", extra_pointer),
    (
        "M-31",
        "G-BQ",
        sub_both(
            "**BQ-2 — files, tool, owner documents.** RULED: OVERRIDE.",
            "**BQ-2 — files, tool, owner documents.** RULED: ACCEPT.",
        ),
    ),
    (
        "M-32",
        "G-BOARDS",
        sub_spec("-07-table-and-focus.png`, 1920 × 1011", "-07-table-and-focus.png`, 1920 × 1012"),
    ),
    (
        "M-33",
        "G-BOARDS",
        sub_spec("E19-D02-05-no-history.png`, ", "E19-D02-05-no-histories.png`, "),
    ),
    (
        "M-34",
        "G-BOARDS",
        sub_spec("## 0. Status and the boards (drawn", "## 0. Status and the boards (PENDING"),
    ),
    ("M-35", "G-UNTOUCHED", other_png),
)


def self_test(c: Ctx) -> list[str]:
    errors: list[str] = []
    base_fail = [r.gate for r in run(c) if not r.ok]
    if base_fail:
        errors.append(f"baseline is not clean: {base_fail}")
    covered = {g for _, g, _ in MUTATIONS}
    for g in sorted(set(GATES) - covered):
        errors.append(f"{g} has no mutation")
    for mid, gate, mutate in MUTATIONS:
        try:
            mutated = mutate(c)
        except ValueError as exc:
            errors.append(f"{mid}: {exc}")
            continue
        failed = sorted(r.gate for r in run(mutated) if not r.ok)
        if failed != [gate]:
            errors.append(f"{mid}: expected exactly [{gate}] to FAIL, got {failed}")
    return errors


# ---------------------------------------------------------------- main


def main(argv: list[str] | None = None) -> int:
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0] if __doc__ else "")
    mode = ap.add_mutually_exclusive_group(required=True)
    mode.add_argument("--check", action="store_true")
    mode.add_argument("--json", action="store_true")
    mode.add_argument("--self-test", action="store_true")
    mode.add_argument("--repin-ruled", action="store_true")
    args = ap.parse_args(argv)
    if args.repin_ruled:
        (ROOT / PIN_REL).write_text(pins_text(read(SPEC_REL)), encoding="utf-8", newline="\n")
        print(f"wrote {PIN_REL}")
        return 0
    c = build_ctx()
    if args.self_test:
        errors = self_test(c)
        for e in errors:
            print(f"FAIL {e}")
        print(f"self-test: {len(MUTATIONS)} mutations, {len(errors)} errors")
        return 1 if errors else 0
    results = run(c)
    if args.json:
        print(json.dumps([r.__dict__ for r in results], ensure_ascii=False, indent=1))
    else:
        for r in results:
            print(f"{'PASS' if r.ok else 'FAIL'} {r.gate}")
            for d in r.detail:
                print(f"     {d}")
    fails = sum(not r.ok for r in results)
    if not args.json:
        print(f"FAIL {fails} of {len(results)} gates")
    return 1 if fails else 0


if __name__ == "__main__":
    raise SystemExit(main())
