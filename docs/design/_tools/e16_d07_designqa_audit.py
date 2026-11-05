#!/usr/bin/env python3
"""E16-D07 (#565) audit: the design QA of the built recorder screens against E16-D06 (first pass).

Offline and default-deny. The shared gates (git, cites, BQ pins, G-T2 markers, closing keywords,
hygiene, public text, G-UNTOUCHED, the runner and the mutation harness) live in
`spec_audit_lib.py`; this file keeps only E16-D07's rows. It reads the run record, its pins and the
captures from the working tree, and every cited file AS TEXT at the merge-base with `origin/main`.
It runs no repo code and drives no browser: the capture run is scratch and its observations are the
record's rows.

Gates: G-CITE (every cite resolves to a non-blank line and its words match the pins, both ways),
G-AUDIT (every `audit` marker is known, recomputed and follows its visible value), G-STATUS (the
ruled status words; a story-owned open row names its story), G-STORIES (the SB rows are `15`'s
nineteen CMP-177 names in order plus the added stories, each a story of the file), G-STATES (the ST
rows are E16-D06 section 18's families in order, each citing its row; the TB rows are the thirteen
text-bound ids; no TB or SS row is closed while G-2 says the page is unmounted), G-CAPTURE (CA rows
and `E16-D07-*` PNGs agree; each PNG's size is its box), G-F15 (the six renders exist, each its
board's size), G-RAW (no raw colour in the built recorder files), G-REGISTER (DF and F rows well
formed), G-RERUN (every open story-owned row is in its story's RR row and RT row, and nothing else
is), G-LEDGER (every story cited with its issue number is that ticket; each RR sprint is its
story's), G-RULED (the BQ section RULED by comment 6652622956: each bullet its verdict, pinned),
G-RIDERS (the wording the ruling retired is gone and the wording it added is present), G-LEGS (the
twelve theme x density cells, each R and keyboard row citing its baseline, each contract row its
`22` rule), G-PRESTAGE (the open PR heads named with their reading), G-T2, G-WALK (at most ten
checklist items), G-NOCLOSE, G-PUBLIC, G-UNTOUCHED and G-MUTLIST (section 16's table is this
tool's list).

Usage (from the repo root):
  python3 -I -B docs/design/_tools/e16_d07_designqa_audit.py --check | --self-test | --repin-ruled
  | --fill
Exit 0 = no FAIL; 1 = at least one FAIL.
"""

from __future__ import annotations

import dataclasses
import functools
import hashlib
import json
import re
import struct
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import spec_audit_lib as L  # the shared helper sits beside this file

ROOT = Path(__file__).resolve().parents[3]
FALLBACK = "e7cc2dd2a1"  # origin/main the record was run against
BQ_LIST = "6649803322"
RULING = "6652622956"  # the ruling of record on #565
SPEC_REL = "docs/design/E16/E16-D07.md"
TOOL_REL = "docs/design/_tools/e16_d07_designqa_audit.py"
PIN_REL = "docs/design/_tools/e16_d07_ruled_pins.txt"
IMG = "docs/design/E16/img/"
OWN = (SPEC_REL, TOOL_REL, PIN_REL)
BOARDS = ("E16-D04-02-tiers-and-tables", "E16-D04-03-states-disk")
RENDERS = tuple(
    f"{IMG}{b}-{k}.png" for b in BOARDS for k in ("greyscale", "deuteranopia", "protanopia")
)
LEDGER_REL = "docs/plan/backlog/_tools/published.json"
TICKETS_REL = "docs/plan/backlog/all-tickets.json"
RECORDER = "apps/web/src/features/recorder/"
HEADING = "## The questions BQ-0 … BQ-9 — RULED (comment " + RULING + ")"
MUT_HEADING = "## 16. The audit tool"
PIN_HEAD = (
    "# E16-D07 pins: the BQ bullets (sha256[:16]) and every cited endpoint, `KEY:line` with the",
    "# sha256[:16] of its words at the base. Written only by `--repin-ruled`.",
)
KEYED_RELS = {
    "D02": "docs/design/E16/E16-D02.md",
    "D04": "docs/design/E16/E16-D04.md",
    "D06": "docs/design/E16/E16-D06.md",
    "E12D13": "docs/design/E12/E12-D13.md",
    "E42D04": "docs/design/E42/E42-D04.md",
    "E05D02": "docs/design/E05/E05-D02-a11y-audit.md",
    "README": "docs/design/README.md",
    "DS": ".claude/rules/32-design-specs.md",
    "CVD": "docs/design/_tools/cvd_sim.py",
    "MANIFEST": "apps/web/src/routes/manifest.ts",
    "CHROME": RECORDER + "RecorderChrome.tsx",
    "SCREENT": "apps/web/test/features/recorder/RecorderScreen.test.tsx",
    "CHROMET": "apps/web/test/features/recorder/chrome.test.tsx",
    "STORIES": "packages/ui/src/components/RecorderStatusRow.stories.tsx",
    "RSR": "packages/ui/src/components/RecorderStatusRow.tsx",
    "RSRT": "packages/ui/test/RecorderStatusRow.test.tsx",
    "GRIDT": "apps/web/test/features/recorder/RecorderGrid.test.tsx",
    "RSDT": "apps/web/test/features/recorder/RecordSymbolDialog.test.tsx",
    "RSRCSS": "packages/ui/src/components/recorderstatusrow.css",
    "PROGCSS": "packages/ui/src/components/progress.css",
    "BTNCSS": "packages/ui/src/components/button.css",
    "ADMINE2E": "apps/web/e2e/support/admin.ts",
    "BUDGET": "services/api/candleviewer/recorder/budget.py",
    "SV": "docs/qa/e07-d02-storageusage-verification.md",
}
_ALTS = "|".join(sorted(KEYED_RELS, key=len, reverse=True))
_DASH = "\u2013"  # the en dash of a line range
CITE_RE = re.compile(  # L.cite_regex's grammar with a backticked key: `D02`:98, a range
    rf"(?:`(?P<nn>\d\d)`|`(?P<named>{_ALTS})`):(?P<first>\d+)(?:{_DASH}(?P<firstend>\d+))?"
    rf"(?P<more>(?:, :\d+(?:{_DASH}\d+)?)*)"
)
MIN_CITES = 90
STATUSES = frozenset(
    {
        "compared",
        "compared-in-part",
        "pass",
        "fail",
        "deferred-owned",
        "owner-run",
        "not-comparable-yet",
        "known",
        "f-row",
    }
)
CLOSED = frozenset({"compared", "pass"})
FAMILIES: tuple[str, ...] = (
    "SU",
    "CA",
    "SB",
    "ST",
    "TB",
    "SS",
    "TK",
    "TD",
    "MO",
    "PF",
    "AX",
    "RF",
    "KR",
    "CT",
)
FAMILIES += ("CV",)
ROW_ID = re.compile(r"^(" + "|".join(FAMILIES) + r")-\d+$")
STORY_RE = re.compile(r"\b(E\d\d-[A-Z]\d\d) \(#(\d+)\)")
RULE_ROW = re.compile(r"^\|[\s:|-]+\|$")
STATUS_CELL = re.compile(r"^`([a-z-]+)`$")
MARK_RE = re.compile(r"(\S+) <!-- audit:([a-z0-9.\-]+)=(\S+?) -->", re.DOTALL)
MARK_ALLOW = re.compile(r" audit:[a-z0-9.\-]+=\S+? ", re.DOTALL)
RANGE_RE = re.compile(r"\b([A-Z]{1,3})-(\d+)\.\.(?:[A-Z]{1,3}-)?(\d+)")
SINGLE_RE = re.compile(r"\b([A-Z]{1,3})-(\d+)\b")
RAW_RE = re.compile(r"[\"'`(:\s]#[0-9a-fA-F]{3,8}\b|\brgba?\(|\bhsla?\(")
COMMENT_STRIP = re.compile(r"/\*.*?\*/|(?<![:\"'])//[^\n]*", re.DOTALL)
CLASSES = frozenset({"implementation defect", "accepted divergence", "specification gap"})
OWNER_RE = re.compile(r"^`(?:E\d\d-D\d\d|\d\d) · area/[a-z-]+`$")
UNMOUNTED = re.compile(r"^\| G-2 +\| the page is not mounted", re.MULTILINE)
SCOPE_STATES = ("disk warning", "disk critical", "purge in progress", "degraded", "empty")
PRESTAGE = (
    "#5894 at head `870ed1a6d`",
    'if #5894 merges as is"',
    "#5347, open, head `4dadddd3d`",
    "#5860 at `aed6b1182`",
    '"if #5860 merges as is"',
    "#5861 at `95e575e92`",
    "#5315 at head `c5021fa41`",
    '"if #5315 merges as is"',
)
VERDICTS: tuple[str, ...] = ("AGREE +rider", "AGREE +rider", "AGREE +rider", "AMEND")
VERDICTS += ("AGREE +rider", "AGREE", "AGREE +rider", "AMEND", "AGREE +rider", "AGREE")
RETIRED = (  # the wording the ruling replaced
    "`14`:2919",
    "`14`:2946",
    "or when the owning story has closed",
    "or a closed owning story",
    "no Penpot page",
)
REQUIRED = (  # the wording the ruling added
    "Penpot page: none",
    "comment 6552808644 on #450",
    "`14`:2920",
    "`14`:2947",
    "the ticket's four a floor",
    "a P0 or P1 on `main` the only Bug",
    "one private item, file:line",
    'PROPOSED ("QA agreement pending"',
    "never a locked control",
    "`forced-colors: active`",
)
THEMES = ("dark", "light", "high-contrast")
DENSITIES = ("comfortable", "compact")


# ---------- sources -------------------------------------------------------------------------------
@functools.cache
def repo() -> L.Repo:
    return L.Repo(ROOT)


@functools.cache
def base() -> str:
    return repo().diff_base(FALLBACK)


@functools.cache
def docs() -> L.Docs:
    keyed = {k: L.DocRef(v, base()) for k, v in KEYED_RELS.items()}
    return L.Docs(repo(), base(), keyed)


def short_base() -> str:
    return repo().git("rev-parse", "--short=10", base()).strip()


def png_size(path: Path) -> tuple[int, int] | None:
    if not path.exists():
        return None
    head = path.read_bytes()[:24]
    if head[:8] != b"\x89PNG\r\n\x1a\n":
        return None
    w, h = struct.unpack(">II", head[16:24])
    return int(w), int(h)


# ---------- record helpers ------------------------------------------------------------------------
def rows(spec: str, family: str) -> list[list[str]]:
    out: list[list[str]] = []
    for ln in spec.split("\n"):
        if ln.startswith("| ") and not RULE_ROW.match(ln.strip()):
            c = L.cells(ln)
            if re.fullmatch(rf"{family}-\d+", c[0]):
                out.append(c)
    return out


def status_of(row: list[str]) -> str:
    """The row's status: its backticked cell from the vocabulary, else its last backticked cell."""
    words = [m.group(1) for c in row[1:] if (m := STATUS_CELL.match(c))]
    return next((w for w in words if w in STATUSES), words[-1] if words else "")


def expand(cell: str) -> set[str]:
    out: set[str] = set()
    for fam, a, b in RANGE_RE.findall(cell):
        width = len(a)
        out |= {f"{fam}-{n:0{width}d}" for n in range(int(a), int(b) + 1)}
    for fam, n in SINGLE_RE.findall(RANGE_RE.sub("", cell)):
        out.add(f"{fam}-{n}")
    return out


def story_rows(spec: str, family: str) -> dict[str, set[str]]:
    """The RR or RT table: story key -> the ids it names."""
    out: dict[str, set[str]] = {}
    for r in rows(spec, family):
        story, ids = (r[2], r[1]) if family == "RR" else (r[1], r[2])
        m = STORY_RE.search(story)
        if m:
            out[m.group(1)] = expand(ids)
    return out


def open_story_rows(spec: str) -> dict[str, set[str]]:
    out: dict[str, set[str]] = {}
    for fam in FAMILIES:
        for r in rows(spec, fam):
            if status_of(r) in CLOSED:
                continue
            for key, _ in STORY_RE.findall(r[-1]):
                out.setdefault(key, set()).add(r[0])
    return out


def d06_families() -> list[int]:
    lines = docs().lines("D06") or ()
    start = next((i for i, ln in enumerate(lines) if ln.startswith("## 18. ")), -1)
    out: list[int] = []
    seen_rule = False
    for i in range(start + 1, len(lines)):
        ln = lines[i]
        if ln.startswith("## "):
            break
        if ln.startswith("|"):
            if RULE_ROW.match(ln.strip()):
                seen_rule = True
            elif seen_rule:
                out.append(i + 1)
        elif seen_rule and out:
            break
    return out


def d06_family_count() -> int:
    m = re.search(r"audit:state-families=(\d+)", "\n".join(docs().lines("D06") or ()))
    return int(m.group(1)) if m else -1


def text_bound_ids() -> list[str]:
    fam = d06_families()
    line = docs().line("D06", fam[1]) if len(fam) > 1 else ""
    return re.findall(r"`([a-z-]+)`", L.cells(line or "|")[0])


def catalogue_names() -> list[str]:
    line = docs().line("15", 2270) or ""
    tail = line.split("**Storybook**:", 1)[-1].strip().rstrip(".")
    return [n.strip() for n in tail.split(",") if n.strip()]


@functools.cache
def raw_hits() -> tuple[str, ...]:
    out = repo().git("ls-tree", "-r", "--name-only", base(), RECORDER).split()
    files = [p for p in out if p.endswith((".ts", ".tsx", ".css"))] + [KEYED_RELS["RSRCSS"]]
    hits: list[str] = []
    for p in files:
        text = COMMENT_STRIP.sub("", repo().show(base(), p) or "")
        hits += [f"{p}: {m.group(0).strip()}" for m in RAW_RE.finditer(text)]
    return tuple(hits)


@functools.cache
def ledger() -> tuple[dict[str, int], dict[str, str]]:
    pub = json.loads(repo().show(base(), LEDGER_REL) or "{}")
    nums = {k: int(v["number"]) for k, v in pub.items() if isinstance(v, dict) and "number" in v}
    tix = json.loads(repo().show(base(), TICKETS_REL) or "[]")
    sprints = {str(t["key"]): str(t.get("sprint", "")) for t in tix}
    return nums, sprints


def cite_endpoints(spec: str) -> list[tuple[str, int]]:
    seen: dict[tuple[str, int], None] = {}
    for c in L.extract_cites(spec, CITE_RE):
        seen[(c.doc, c.lo)] = None
        seen[(c.doc, c.hi)] = None
    return sorted(seen)


def line_hash(s: str) -> str:
    return hashlib.sha256(s.strip().encode("utf-8")).hexdigest()[:16]


def pins_text(spec: str) -> str:
    cites = [f"{d}:{n} {line_hash(docs().line(d, n) or '')}" for d, n in cite_endpoints(spec)]
    return "\n".join([*PIN_HEAD, *L.bq_hash_pins(spec, HEADING), *cites]) + "\n"


# ---------- numbers -------------------------------------------------------------------------------
def compute(spec: str) -> dict[str, str]:
    def n(fam: str, *st: str) -> int:
        return sum(1 for r in rows(spec, fam) if not st or status_of(r) in st)

    df = rows(spec, "DF")
    sev = [r[2].split(" ")[0] for r in df]
    return {
        "sha": short_base(),
        "st": str(n("ST")),
        "st.compared": str(n("ST", "compared", "compared-in-part")),
        "st.deferred": str(n("ST", "deferred-owned")),
        "su.compared": str(n("SU", "compared")),
        "su.part": str(n("SU", "compared-in-part")),
        "su.deferred": str(n("SU", "deferred-owned")),
        "sb": str(n("SB")),
        "sb.catalogue": str(len(catalogue_names())),
        "tb": str(n("TB")),
        "ss": str(n("SS")),
        "tk": str(n("TK")),
        "tk.raw": str(len(raw_hits())),
        "mo": str(n("MO")),
        "pf": str(n("PF")),
        "ax": str(n("AX")),
        "cv": str(n("CV")),
        "ca": str(n("CA")),
        "df": str(len(df)),
        "df.blocking": str(sev.count("Blocking")),
        "df.major": str(sev.count("Major")),
        "df.minor": str(sev.count("Minor")),
        "df.info": str(sev.count("Info")),
        "f": str(len(rows(spec, "F"))),
        "td": str(n("TD")),
        "rf": str(n("RF")),
        "kr": str(n("KR")),
        "ct": str(n("CT")),
    }


# ---------- gates ---------------------------------------------------------------------------------
def g_cite(t: L.Tree) -> list[str]:
    spec = t.text("spec")
    bad = L.check_cites(L.extract_cites(spec, CITE_RE), docs(), min_count=MIN_CITES)
    want = [r for r in L.pin_rows(pins_text(spec)) if not r.startswith("BQ-")]
    got = [r for r in L.pin_rows(t.text("pins")) if not r.startswith("BQ-")]
    if want != got:
        bad.append(f"pins differ: {sorted(set(want) ^ set(got))[:4]}")
    return bad


def g_audit(t: L.Tree) -> list[str]:
    spec, vals = t.text("spec"), compute(t.text("spec"))
    bad = []
    for vis, key, val in MARK_RE.findall(spec):
        if key not in vals:
            bad.append(f"unknown {key}")
        elif val != vals[key] or vis != val:
            bad.append(f"{key}: {vis}/{val} != {vals[key]}")
    if spec.count("<!-- audit:") != len(MARK_RE.findall(spec)):
        bad.append("a marker without its visible value")
    return bad


def g_status(t: L.Tree) -> list[str]:
    spec, bad = t.text("spec"), []
    for fam in FAMILIES:
        for r in rows(spec, fam):
            st = status_of(r)
            if st not in STATUSES:
                bad.append(f"{r[0]} status {st!r}")
            elif st in ("deferred-owned", "compared-in-part") and not STORY_RE.search(r[-1]):
                bad.append(f"{r[0]} names no owner story")
            elif st == "owner-run" and not re.search(r"\bOR-\d+", r[-1]):
                bad.append(f"{r[0]} names no OR leg")
    return bad


def g_stories(t: L.Tree) -> list[str]:
    spec, names = t.text("spec"), catalogue_names()
    src = docs().lines("STORIES") or ()
    sb = rows(spec, "SB")
    got = [r[1] for r in sb[: len(names)]]
    bad = [] if got == names and len(names) == 19 else [f"SB names {got} != {names}"]
    exported = set(re.findall(r"^export const (\w+)", "\n".join(src), re.MULTILINE))
    labelled = set(re.findall(r'name: "(\w+)"', "\n".join(src)))
    for i, r in enumerate(sb):
        name = r[1].replace(" (added)", "")
        if name not in exported | labelled:
            bad.append(f"{r[0]} {name} is no story")
        if r[1].endswith("(added)") != (i >= len(names)):
            bad.append(f"{r[0]} added mark")
    return bad


def g_states(t: L.Tree) -> list[str]:
    spec, fam = t.text("spec"), d06_families()
    st = rows(spec, "ST")
    bad = [] if len(st) == len(fam) == d06_family_count() else [f"{len(st)} ST rows"]
    for r, line in zip(st, fam, strict=False):
        if f"`D06`:{line}" != r[2]:
            bad.append(f"{r[0]} does not cite `D06`:{line}")
    tb = [L.unquote(r[1]).strip("`") for r in rows(spec, "TB")]
    if tb != text_bound_ids() or len(tb) != 13:
        bad.append(f"TB ids {tb}")
    ss = [r[1] for r in rows(spec, "SS")]
    if ss != list(SCOPE_STATES):
        bad.append(f"SS states {ss}")
    shut = [r[0] for r in rows(spec, "TB") + rows(spec, "SS") if status_of(r) in CLOSED]
    if shut and UNMOUNTED.search(spec):
        bad.append(f"closed on the unmounted page (G-2): {shut}")
    return bad


def g_capture(t: L.Tree) -> list[str]:
    spec, bad = t.text("spec"), []
    named = set()
    for r in rows(spec, "CA"):
        name = r[1].strip("`")
        named.add(IMG + name)
        if f"{IMG}{name}" not in t.changed:
            bad.append(f"{r[0]} {name} not in the change")
        size = png_size(ROOT / IMG / name)
        w, _, h = r[3].partition("x")
        if size is None or r[5] != "1" or size != (int(w or 0), int(h or 0)):
            bad.append(f"{r[0]} size {size} != {r[3]} at DPR {r[5]}")
        if r[6] != "emulated":
            bad.append(f"{r[0]} run {r[6]}")
    extra = [p for p in t.changed if p.startswith(IMG + "E16-D07-") and p not in named]
    return bad + [f"unnamed capture {p}" for p in extra]


def g_f15(t: L.Tree) -> list[str]:
    spec, bad = t.text("spec"), []
    got = [IMG + r[1].strip("`") for r in rows(spec, "CV")]
    if got != list(RENDERS):
        bad.append("CV rows are not the six renders")
    for rel in RENDERS:
        src = ROOT / IMG / (rel.rsplit("/", 1)[1].rsplit("-", 1)[0] + ".png")
        if rel not in t.changed or png_size(ROOT / rel) != png_size(src) or png_size(src) is None:
            bad.append(f"{rel} missing or not its board's size")
    return bad


def g_raw(t: L.Tree) -> list[str]:
    tk = {r[0]: r for r in rows(t.text("spec"), "TK")}
    bad = list(raw_hits())
    for rid in ("TK-1", "TK-2"):
        if rid not in tk or status_of(tk[rid]) != "pass":
            bad.append(f"{rid} is not the scan's pass row")
    return bad


def g_register(t: L.Tree) -> list[str]:
    spec, bad = t.text("spec"), []
    for r in rows(spec, "DF"):
        if (
            r[1] not in CLASSES
            or r[2].split(" ")[0] not in ("Blocking", "Major", "Minor", "Info")
            or not L.extract_cites(r[3], CITE_RE)
            or not OWNER_RE.match(r[4])
            or not STORY_RE.search(r[5])
        ):
            bad.append(r[0])
        if r[2].startswith("Blocking") and "| none | none |" in L.section(spec, "### 11.2"):
            bad.append(f"{r[0]} Blocking without a Bug")
    for r in rows(spec, "F"):
        if len({c.doc for c in L.extract_cites(r[1], CITE_RE)}) < 2:
            bad.append(f"{r[0]} lacks both cites")
    return bad


def g_rerun(t: L.Tree) -> list[str]:
    spec, bad = t.text("spec"), []
    want, rr, rt = open_story_rows(spec), story_rows(spec, "RR"), story_rows(spec, "RT")
    for key in sorted(set(want) | set(rr)):
        if want.get(key, set()) != rr.get(key, set()):
            diff = want.get(key, set()) ^ rr.get(key, set())
            bad.append(f"{key} RR differs: {sorted(diff)}")
        if not rr.get(key, set()) <= rt.get(key, set()):
            bad.append(f"{key} RT lacks {sorted(rr.get(key, set()) - rt.get(key, set()))}")
    return bad


def g_ledger(t: L.Tree) -> list[str]:
    spec, (nums, sprints) = t.text("spec"), ledger()
    bad = sorted({f"{k} (#{n})" for k, n in STORY_RE.findall(spec) if nums.get(k) != int(n)})
    for r in rows(spec, "RR"):
        m = STORY_RE.search(r[2])
        if not m or sprints.get(m.group(1)) != r[3]:
            bad.append(f"{r[0]} sprint")
    return bad


def verdict(n: int) -> str:
    built = "Built as amended:" if VERDICTS[n] == "AMEND" else "Built:"
    return f"**RULED: {VERDICTS[n]}.** {built}"


def g_ruled(t: L.Tree) -> list[str]:
    spec = t.text("spec")
    bad = L.check_ruling(
        spec,
        heading_line=HEADING,
        list_ref=f"comment {BQ_LIST} on #565",
        count=10,
        verdict=verdict,
        forbid=("ORCH-default", "ruling pending"),
        heading=HEADING,
    )
    want = [r for r in L.pin_rows(t.text("pins")) if r.startswith("BQ-")]
    if want != L.bq_hash_pins(spec, HEADING):
        bad.append("BQ bullets differ from the pins (run --repin-ruled after a ruling)")
    return bad


def g_riders(t: L.Tree) -> list[str]:
    """Outside the BQ section, whose bullets G-RULED pins."""
    spec = t.text("spec").replace(L.section(t.text("spec"), HEADING), "")
    bad = [f"retired: {w!r}" for w in RETIRED if w in spec]
    return bad + [f"missing: {w!r}" for w in REQUIRED if w not in spec]


def g_legs(t: L.Tree) -> list[str]:
    spec, bad = t.text("spec"), []
    want = [(s, th, d) for s in ("SCR-140", "CMP-177") for d in DENSITIES for th in THEMES]
    got = [(r[1], r[2], r[3]) for r in rows(spec, "TD")]
    if sorted(got) != sorted(want) or len(got) != len(want):
        bad.append(f"TD cells {len(got)} are not the {len(want)} of DQ-TV-2")
    for fam, keys in (("RF", ("D02", "D06")), ("KR", ("D06",)), ("CT", ("22",))):
        for r in rows(spec, fam):
            if not {c.doc for c in L.extract_cites(r[2], CITE_RE)} & set(keys):
                bad.append(f"{r[0]} cites no {'/'.join(keys)} baseline")
    return bad


def g_prestage(t: L.Tree) -> list[str]:
    return [f"missing {p!r}" for p in PRESTAGE if p not in t.text("spec")]


def g_t2(t: L.Tree) -> list[str]:
    return L.t2_markers(L.section(t.text("spec"), "### 8.2"))


def g_walk(t: L.Tree) -> list[str]:
    block = L.section(t.text("spec"), "## 13.")
    items = re.findall(r"^(\d+)\. ", block, re.MULTILINE)
    ok = items == [str(i) for i in range(1, len(items) + 1)] and 0 < len(items) <= 10
    return [] if ok else [f"{len(items)} checklist items"]


def g_noclose(t: L.Tree) -> list[str]:
    named = t.named("spec", "pins", "tool")
    return L.closing_keywords(t.named("spec", "pins")) + L.whitespace_hygiene(named)


def g_public(t: L.Tree) -> list[str]:
    named = t.named("spec", "pins", "tool")
    return L.scan_public(named) + L.comment_findings(t.named("spec"), MARK_ALLOW)


def g_untouched(t: L.Tree) -> list[str]:
    return L.untouched(t.changed, OWN + RENDERS, (IMG + "E16-D07-[01][0-9]-*.png",))


def g_mutlist(t: L.Tree) -> list[str]:
    return L.check_mutlist(t.text("spec"), MUT_HEADING, MUTATIONS)


GATES = tuple(
    L.Gate("G-" + f.__name__[2:].upper().replace("_", "-"), f)
    for f in (
        g_cite,
        g_audit,
        g_status,
        g_stories,
        g_states,
        g_capture,
        g_f15,
        g_raw,
        g_register,
        g_rerun,
        g_ledger,
        g_ruled,
        g_riders,
        g_legs,
        g_prestage,
        g_t2,
        g_walk,
        g_noclose,
        g_public,
        g_untouched,
        g_mutlist,
    )
)


def _drop_render(t: L.Tree) -> L.Tree:
    return dataclasses.replace(t, changed=tuple(p for p in t.changed if p != RENDERS[0]))


def _close_tb(t: L.Tree) -> L.Tree:
    """TB-01 closed on the unmounted page, its re-run entries moved with it: only G-STATES."""
    spec = re.sub(
        r"(\| TB-01 \|.*?\| )`compared-in-part` \| E16-S01 \(#484\) \|",
        r"\1`compared`         | this pass      |",
        t.text("spec"),
        count=1,
    )
    spec = spec.replace("TB-01..TB-11,", "TB-02..TB-11,")
    return dataclasses.replace(t, files={**t.files, "spec": spec})


_M = L.Mutation
_S = "## 17. Summary for #565\n"
# fmt: off
MUTATIONS: tuple[L.Mutation, ...] = (
    _M("M-1", "G-CITE", "a cite past the end of `D02`", "spec", r"(\| `D02`):98( +\|)",
       r"\1:99999\2", regex=True),
    _M("M-2", "G-CITE", "a pin's words drift", "pins", "D02:72 ", "D02:72 0"),
    _M("M-3", "G-AUDIT", "a count typed wrong", "spec", "3 <!-- audit:df=3 --> findings: 0",
       "4 <!-- audit:df=4 --> findings: 0"),
    _M("M-4", "G-STATUS", "an unknown status word", "spec", r"\| `compared` (\s*)\| this pass",
       r"| `checked`  \1| this pass", regex=True),
    _M("M-5", "G-STATUS", "an open row without a story", "spec",
       r"(its reduce pair\) +\| )`pass`", r"\1`deferred-owned`", regex=True),
    _M("M-6", "G-STORIES", "a catalogue state dropped", "spec", r"\| SB-14 \| Silent",
       "| SB-14 | Quiet ", regex=True),
    _M("M-7", "G-STATES", "two families swap their D06 rows", "spec",
       r"(\| ST-14 \|[^|]*\| )`D06`:960( \|.*\n\| ST-15 \|[^|]*\| )`D06`:961",
       r"\1`D06`:961\2`D06`:960", regex=True),
    _M("M-8", "G-STATES", "a text-bound state renamed", "spec", r"\| TB-13 \| `motion`",
       "| TB-13 | `animate`", regex=True),
    _M("M-9", "G-CAPTURE", "a capture's box misstated", "spec", "| 1200x127 |", "| 1200x128 |"),
    _M("M-10", "G-F15", "a render dropped", fn=_drop_render),
    _M("M-11", "G-RAW", "the scan row no longer passes", "spec", r"(\| `RSRCSS` +\| )`pass`",
       r"\1`fail`", regex=True),
    _M("M-12", "G-REGISTER", "a DF row without an owner", "spec",
       "| `16 · area/design-system` ", "| the DS "),
    _M("M-13", "G-RERUN", "a deferred row missing from its RR row", "spec",
       r"(\| RR-2 +\| SU-2; ST-06\.\.ST-13; )TB-12; ", r"\1", regex=True),
    _M("M-14", "G-LEDGER", "a story with another's issue number", "spec",
       "| RT-6 | E16-D06 (#374) |", "| RT-6 | E16-D06 (#375) |"),
    _M("M-15", "G-RULED", "a BQ default edited without a re-pin", "spec",
       "ten fixture-only captures checked by eye", "nine fixture-only captures checked by eye"),
    _M("M-16", "G-RULED", "an AMEND verdict misstated", "spec",
       "**RULED: AMEND.** Built as amended: E12-D13's statuses",
       "**RULED: AGREE.** Built: E12-D13's statuses"),
    _M("M-17", "G-PRESTAGE", "a head sha drifts", "spec", "`95e575e92`", "`95e575e90`"),
    _M("M-18", "G-T2", "the T2 statement loses the opacity ban", "spec",
       "never `color.text.disabled`, never `opacity.disabled` on the label",
       "never `color.text.disabled` on the label"),
    _M("M-19", "G-WALK", "an eleventh checklist item", "spec", "10. Record approval on #565.",
       "10. Record approval on #565.\n11. Celebrate."),
    _M("M-20", "G-NOCLOSE", "a closing keyword", "spec", _S, _S + "\n" + "Clo" + "ses #565.\n"),
    _M("M-21", "G-PUBLIC", "a stray HTML comment", "spec", "## 2. The pass",
       "<!-- x -->\n## 2. The pass"),
    _M("M-22", "G-PUBLIC", "a URL", "spec", "on 127.0.0.1.", "on " + "http" + "s://example.org."),
    _M("M-23", "G-UNTOUCHED", "an owner document edited", "@changed", "",
       "docs/plan/14-screens-catalogue.md"),
    _M("M-24", "G-MUTLIST", "the list drifts", "spec", "| M-1  | G-CITE ", "| M-1  | G-AUDIT"),
    _M("M-25", "G-STATES", "a text-bound row closed while unmounted", fn=_close_tb),
    _M("M-26", "G-RIDERS", "a retired filing trigger comes back", "spec",
       "only a P0 or P1 on `main` is filed (BQ-7).",
       "only a P0 or P1 on `main` is filed, or when the owning story has closed (BQ-7)."),
    _M("M-27", "G-RIDERS", "the waiver loses its ruling id", "spec",
       "comment 6552808644 on #450).", "comment on #450)."),
    _M("M-28", "G-LEGS", "a theme x density cell renamed", "spec",
       "| TD-8  | CMP-177 | light ", "| TD-8  | CMP-177 | sepia "),
    _M("M-29", "G-LEGS", "a contract row's `22` rule moves out of its column", "spec",
       r"(\| CT-6 \| Compact now +\| `compactRecorder`) \(`22`:16918\)( +\| posts the job)",
       r"\1               \2 (`22`:16918)", regex=True),
)
# fmt: on


# ---------- modes ---------------------------------------------------------------------------------
def read_tree() -> L.Tree:
    pins = ROOT / PIN_REL
    return L.Tree(
        files={
            "spec": (ROOT / SPEC_REL).read_text(encoding="utf-8"),
            "pins": pins.read_text(encoding="utf-8") if pins.exists() else "",
            "tool": (ROOT / TOOL_REL).read_text(encoding="utf-8"),
        },
        changed=repo().changed_paths(base()),
    )


def check() -> int:
    return L.report(L.run_gates(GATES, read_tree()))


def self_test() -> int:
    disk = [ROOT / rel for rel in OWN]
    return L.self_test(read_tree(), GATES, MUTATIONS, disk, namespace=globals())


def repin() -> int:
    spec = (ROOT / SPEC_REL).read_text(encoding="utf-8")
    L.write_pins(ROOT / PIN_REL, pins_text(spec))
    print(f"pinned {len(L.pin_rows(pins_text(spec)))} rows")
    return 0


def fill() -> int:
    path = ROOT / SPEC_REL
    spec = path.read_text(encoding="utf-8")
    vals = compute(spec)

    def sub(m: re.Match[str]) -> str:
        v = vals.get(m.group(2), m.group(3))
        return f"{v} <!-- audit:{m.group(2)}={v} -->"

    spec = MARK_RE.sub(sub, spec)
    block = L.section(spec, MUT_HEADING)
    table = L.mutation_table(MUTATIONS, (4, 11, 44))
    old = "\n".join(ln for ln in block.split("\n") if ln.startswith("|"))
    spec = spec.replace(old, table, 1) if old else spec
    path.write_text(spec, encoding="utf-8", newline="\n")
    print("filled")
    return 0


def main(argv: list[str]) -> int:
    modes = {"check": check, "self-test": self_test, "repin-ruled": repin, "fill": fill}
    return L.cli(argv, modes, __doc__)


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
