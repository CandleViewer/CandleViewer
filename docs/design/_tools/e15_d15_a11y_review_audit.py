"""E15-D15 (#369) audit: the accessibility review of the layout keyboard model and screen-reader script.

Stdlib only, offline (`python3 -I -B`). It reads the spec and the pins file from the working tree,
and every cited file AS TEXT at the pinned base with `git show`. It imports, never copies: E11-D07's
key-map engine (`nrm`, `expand_keys`, `load_keymap`, `shipped_bindings`, `load_reserved`,
`coactive`) and the E15-D06 audit's `hx`, `ratio`, `grey`, `de`, `sim`, `THEMES` and `PAIRS`, plus
the E15-D05 audit's `PAIRS`; `contrast_check.py`'s ratio and `cvd_simulate.py`'s projection are
reached through them. Sixteen gates, each FAIL led by its code:

- [G1-INVENTORY] section 2 lists the fourteen surfaces (ten reviewed, four out of scope to their
  E15-D1n owner) and every component row has a verdict; section 0's image counts equal the merged
  E15 images at the base.
- [G2-KEYS] section 3.1: every KB row has a scope, a status, a resolution and a source; every
  shipped row's binding equals the key map's; the "what the engine computed" markers (commands,
  reserved entries, reserved rows with an override, undeclared co-active collisions) are recomputed;
  section 14: every KS step names a key.
- [G3-FOCUS] section 4: FM-01..FM-29 present, every destination named (never the body), every row
  sourced; section 11's `Focus` cells from the vocabulary.
- [G4-REGIONS] section 5.1: every RG row has a role and a source; the ring sentence and R-5 stand.
- [G5-SCRIPT] section 6.1: a politeness from the vocabulary, a queueing rule and a host on every
  row; every quoted string stands verbatim in a file the row cites; section 7 has BG-01..BG-08 and
  the AC4 number.
- [G6-T2] section 8.1: a class per row; a T2 row names a rendering and the 1a–d checks and carries
  no disabled token; every `key` "string" pair stands in a parent or E09-D09; the state-key length
  marker is recomputed from E15-D02 section 8.1; section 8.2's SD rows carry a verdict.
- [G7-VERDICT] sections 10.1 and 10.2: a verdict from R-3's list; `at risk` names an F row or an
  interim path, `non-compliant` a Blocking one.
- [G8-FINDINGS] section 11: the count marker against the rows; severity, owner (a spec and an
  area, never an agent), target E15-D16 (#370), the `G-T2` and `Focus` cells; the hold sentence
  while a Blocking row stands; no dangling id of any kind; section 16's counts.
- [G9-RULED] section R lists BQ-01..BQ-23 once each with a status from the list; every "RULED
  BQ-nn" stamp points at a listed BQ; the PENDING line stands while any row is pending.
- [G10-CITE] every `KEY`:line cite resolves at the base to a non-blank line; the pins file and the
  cited endpoints match both ways and each pin's words stand on its line; no cited file other than
  `14` and `15` changed between the BQ list's base and this base.
- [G11-COLOUR] section 10.3's union line and section 10.4's measured CR rows are recomputed, and the
  CVD image count.
- [G12-HYGIENE] no lane-private word, host, uuid, local path, URL or closing keyword in the spec,
  the tool or the pins; no fixture account in a quoted example string.
- [G13-UNSTATED] R369 BQ-04's test: R-1 states the precise reading; a PROPOSED destination in
  section 4 is Minor where the trigger survives and Blocking where the operation can remove the
  focused element; an F row whose merged sentence names a removed element is Blocking.
- [G14-CRITERIA] a section 10.1 or 10.2 row never reads `compliant` while an F row of severity
  Minor or higher cites that `05` clause or WCAG criterion or is listed against it; every cited
  clause and criterion lists its F row.
- [G15-XREF] every SR id an FM row names is defined, shares a word with the operation, and holds
  every string the FM row quotes (a ticked key stands in the SR string or a cited parent).
- [G16-BUDGET] BG-03 states R369 BQ-13's rule ("1 polite summary + any assertive safety row")
  and suppresses only polite rows; the apply scenario of section 13 names it.

`--json` prints the numbers and findings; `--check` exits 1 on any FAIL; `--self-test` applies at
least one mutation per gate to an in-memory copy and passes only when each adds exactly one new FAIL
with its gate's code, a re-run reproduces the base result and no file on disk changed.
`--repin-ruled` rewrites the pins file from the spec's cites and is the only writer of that file.

Usage: python3 -I -B docs/design/_tools/e15_d15_a11y_review_audit.py [--check] [--json]
       [--self-test] [--repin-ruled]
"""

from __future__ import annotations

import argparse
import codecs
import hashlib
import importlib.util
import json
import re
import subprocess
import sys
from collections.abc import Callable
from pathlib import Path
from types import ModuleType
from typing import Any, NamedTuple

ROOT = Path(__file__).resolve().parents[3]
TOOLS = ROOT / "docs" / "design" / "_tools"
SPEC = ROOT / "docs" / "design" / "E15" / "E15-D15.md"
PINS = TOOLS / "e15_d15_ruled_pins.txt"
BASE = "7e23e4667ceb97e99943bdde834268809f7719a9"  # origin/main; every cite is read here
BQ_BASE = "7629519069a7cfeebaf68153fb4d1003cb12b41e"  # where the BQ list read every cite
MOVED = {"14", "15"}  # the two files that changed between the bases (section 1.5)
KEYS = {
    "05": "docs/plan/05-accessibility-standard.md",
    "11": "docs/plan/11-user-stories.md",
    "14": "docs/plan/14-screens-catalogue.md",
    "15": "docs/plan/15-component-catalogue.md",
    "02": "docs/plan/02-definition-of-ready-done.md",
    "DS": ".claude/rules/32-design-specs.md",
    "KM": "apps/web/src/keymap/keymap.json",
    "RK": "apps/web/src/keymap/reserved-keys.json",
    "PREF": "apps/web/src/features/a11y-preferences/model.ts",
    "CAL": "docs/plan/backlog/_tools/calendar_cv.py",
    "README": "docs/design/README.md",
    "D01": "docs/design/research/e15-layouts/findings.md",
    "D02": "docs/design/E15/E15-D02.md",
    "D03": "docs/design/E15/E15-D03.md",
    "D04": "docs/design/E15/E15-D04.md",
    "D05": "docs/design/E15/E15-D05.md",
    "D06": "docs/design/E15/E15-D06.md",
    "D07": "docs/design/E15/E15-D07.md",
    "D08": "docs/design/E15/E15-D08.md",
    "D09": "docs/design/E15/E15-D09.md",
    "D04H": "docs/design/E15/E15-D04-handoff.md",
    "E09-D09": "docs/design/E09/E09-D09.md",
    "E29-D05": "docs/design/E29/E29-D05.md",
}
DECKS = ("D02", "D03", "D04", "D05", "D06", "D07", "D08", "D09", "E09-D09")
IMG_DIR = "docs/design/E15/img"
PARENTS = ("D01", "D02", "D03", "D04", "D05", "D06", "D07", "D08")
SURFACES_REVIEWED = (
    "SCR-011",
    "SCR-020",
    "SCR-021",
    "SCR-022",
    "SCR-023",
    "SCR-024",
    "SCR-025",
    "SCR-026",
    "SCR-028",
    "SCR-029",
)
SURFACES_OUT = {
    "SCR-027": "E15-D10",
    "SCR-049": "E15-D11",
    "SCR-150": "E15-D12",
    "SCR-153": "E15-D12",
}
SCOPES = ("`global`", "`workspace`", "`panel`", "`mode`", "`component`", "—")
RESOLUTION_RE = re.compile(
    r"shadow declared|context-scoped|dropped|pending|none|withdrawn|desktop-only|out of scope"
)
POLITENESS = (
    "polite",
    "assertive",
    "none",
    "never",
    "**assertive**",
)
FOCUS_RE = re.compile(r"^(kept · |moves to · |returns to · |n/a)")
CLASSES = ("T2", "validity", "availability", "busy", "sentence", "absence", "outcome")
DISABLED_TOKENS = ("opacity.disabled", "color.text.disabled")
SEVERITIES = ("Blocking", "Major", "Minor", "Info")
VERDICT_RE = re.compile(
    r"^(compliant|at risk|non-compliant|out of scope — .+|not yet decidable — routed to E15-Q06)"
)
OWNER_RE = re.compile(r"^E15-D\d\d · area/charting-ui$")
AGENT_RE = re.compile(r"worker|agent|session", re.IGNORECASE)
TARGET = "E15-D16 (#370)"
HOLD = "cannot be Done until fixed or an exception is recorded on #369"
BQ_IDS = tuple(f"BQ-{i:02d}" for i in range(1, 24))
BQ_STATUS = ("pending", "RULED")
PENDING_LINE = "**Ruling status: PENDING.**"
UNSTATED_CLAUSE = "no merged text _and no `05` rule_ yields the destination"
COALESCE_RULE = '**"1 polite summary + any assertive safety row"**'
PROPOSED_FM = re.compile(r"PROPOSED \((F-\d\d)\)")
REMOVED_RE = re.compile(r"\bremov")
WCAG_RE = re.compile(r"WCAG (\d\.\d\.\d{1,2})\b")
CLAUSE_RE = re.compile(r"`05` (§\d+(?:\.\d+)?)(?: (?:item|rule) (\d+))?")  # an F row's clause cite
CLAUSE_HEAD = re.compile(r"(§\d+(?:\.\d+)?)(?: (?:items?|rules?) ([^—]*))?")  # a section 10.1 head
SR_RANGE = re.compile(r"SR-(\d\d)\.\.(?:SR-)?(\d\d)")
SR_ONE = re.compile(r"SR-(\d\d)")
WORD = re.compile(r"[A-Za-z][A-Za-z\-]{3,}")
STOP = frozenset(
    (
        "polite",
        "assertive",
        "once",
        "never",
        "with",
        "from",
        "that",
        "this",
        "then",
        "when",
        "after",
        "read",
        "role",
        "none",
        "layout",
        "panel",
        "panels",
    )
)
ID_KINDS = ("KB", "FM", "RG", "SR", "BG", "T2", "SD", "CR", "KS", "F", "G", "Q")
BARS = {"text": 4.5, "non-text": 3.0, "hc-text": 7.0}
SIMS = ("protanopia", "deuteranopia", "tritanopia")
SURFACE_TOKENS = (
    "color.surface.sunken",
    "color.surface.app",
    "color.surface.canvas",
    "color.surface.raised",
    "color.surface.overlay",
)
# lane-private words, rot13 so that the tool never contains them in clear
BANNED_ROT13 = "ucr-jbexre ggonfvy onfvygg Ntrag_P"
BANNED = [w.replace("_", " ") for w in codecs.decode(BANNED_ROT13, "rot13").split()]
HOST = re.compile(r"\b[a-z0-9-]+\.(?:com|net|io|dev|org)\b")
UUID = re.compile(r"\b[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}\b")
FIXTURE = re.compile(r"\b(?:Main|Desk4|Core3|sub_00\d)\b")
QUOTED = re.compile(r'"([^"\n]*)"')
CITE = re.compile(r"`([A-Za-z0-9.\-]+)`:(\d+)(?:–:(\d+))?")
PAIR = re.compile(r'`([a-z_][a-z0-9_.]*)` "([^"]+)"')
STAMP = re.compile(r"RULED (BQ-\d\d)")
MARKER = re.compile(r"<!-- audit:([a-z-]+)=([^ ]+) -->")


def _load(name: str) -> ModuleType:
    spec = importlib.util.spec_from_file_location(name, TOOLS / f"{name}.py")
    if spec is None or spec.loader is None:
        raise SystemExit(f"cannot load {name}")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


E11: Any = _load("e11_d07_a11y_review_audit")
D05T: Any = _load("e15_d05_presets_audit")
D06T: Any = _load("e15_d06_sync_audit")


def git_show(rev: str, rel: str) -> str:
    out = subprocess.run(
        ["git", "-C", str(ROOT), "show", f"{rev}:{rel}"], capture_output=True, check=False
    )
    return out.stdout.decode("utf-8") if out.returncode == 0 else ""


def git_ls(rev: str, rel: str) -> list[str]:
    out = subprocess.run(
        ["git", "-C", str(ROOT), "ls-tree", "--name-only", rev, rel + "/"],
        capture_output=True,
        check=False,
    )
    return out.stdout.decode("utf-8").split() if out.returncode == 0 else []


class Ctx(NamedTuple):
    spec: str
    tool: str
    pins: str
    base: dict[str, str]
    bq_base: dict[str, str]
    images: tuple[str, ...]


class Result:
    def __init__(self) -> None:
        self.fails: list[str] = []
        self.warns: list[str] = []
        self.numbers: dict[str, object] = {}

    def fail(self, code: str, msg: str) -> None:
        self.fails.append(f"[{code}] {msg}")


def load_ctx() -> Ctx:
    return Ctx(
        spec=SPEC.read_text(encoding="utf-8"),
        tool=Path(__file__).read_text(encoding="utf-8"),
        pins=PINS.read_text(encoding="utf-8") if PINS.exists() else "",
        base={k: git_show(BASE, v) for k, v in KEYS.items()},
        bq_base={k: git_show(BQ_BASE, v) for k, v in KEYS.items()},
        images=tuple(Path(p).name for p in git_ls(BASE, IMG_DIR)),
    )


# --- markdown helpers ---------------------------------------------------------------------------
def section(text: str, head: str) -> str:
    """The body under `## {head}` (or `### {head}`) up to the next heading of that level or above."""
    m = re.search(rf"^(#{{2,3}}) {re.escape(head)}", text, re.MULTILINE)
    if not m:
        return ""
    level = len(m.group(1))
    rest = text[m.end() :]
    end = re.search(rf"^#{{2,{level}}} ", rest, re.MULTILINE)
    return rest[: end.start()] if end else rest


def cells(line: str) -> list[str]:
    body = line.strip()[1:-1]
    out, cur, code = [], "", False
    for ch in body:
        if ch == "`":
            code = not code
        if ch == "|" and not code:
            out.append(cur.strip())
            cur = ""
        else:
            cur += ch
    out.append(cur.strip())
    return out


def rows(block: str) -> list[list[str]]:
    lines = block.splitlines()
    out: list[list[str]] = []
    for i, ln in enumerate(lines):
        if not ln.startswith("|") or re.match(r"^\|\s*:?-", ln):
            continue
        if i + 1 < len(lines) and re.match(r"^\|\s*:?-", lines[i + 1]):
            continue
        out.append(cells(ln))
    return out


def by_id(block: str, prefix: str) -> dict[str, list[str]]:
    return {r[0]: r for r in rows(block) if re.fullmatch(prefix + r"-\w+", r[0])}


def norm(text: str) -> str:
    return re.sub(r"\s+", " ", text).strip()


def ticks(cell: str) -> list[str]:
    return re.findall(r"`([^`]+)`", cell)


def marker(spec: str, name: str) -> str:
    m = re.search(rf"<!-- audit:{re.escape(name)}=([^ ]+) -->", spec)
    return m.group(1) if m else ""


def quoted_in(strings: list[str], texts: list[str]) -> list[str]:
    """The quoted strings that stand verbatim in none of the texts (short and elided ones skipped)."""
    hay = norm(" ".join(texts))
    bad = []
    for q in strings:
        if len(q) < 8 or "…" in q or "{maximise key}" in q:
            continue
        if norm(q) not in hay:
            bad.append(q)
    return bad


def row_sources(row: list[str], ctx: Ctx) -> list[str]:
    keys = {k for k, _, _ in CITE.findall(" ".join(row))}
    return [ctx.base[k] for k in keys if k in ctx.base] or [ctx.base[k] for k in DECKS]


# --- G1: inventory and images --------------------------------------------------------------------
def gate_inventory(ctx: Ctx, r: Result) -> None:
    body = section(ctx.spec, "2. Inventory")
    table = rows(body)
    items = {row[0].split(" ")[0]: row for row in table}
    for s in SURFACES_REVIEWED:
        row = items.get(s)
        if not row or not row[2].startswith("reviewed"):
            r.fail("G1-INVENTORY", f"{s}: not listed as reviewed")
    for s, owner in SURFACES_OUT.items():
        row = items.get(s)
        if not row or f"out of scope — {owner}" not in row[2]:
            r.fail("G1-INVENTORY", f"{s}: not out of scope to {owner}")
    for row in table:
        if row[1] == "component" and not row[2]:
            r.fail("G1-INVENTORY", f"{row[0]!r}: a component without a verdict")
    n = len(ctx.images)
    if marker(ctx.spec, "images") != str(n):
        r.fail(
            "G1-INVENTORY",
            f"section 0 counts {marker(ctx.spec, 'images')!r} images, the base has {n}",
        )
    per = "/".join(str(sum(f"E15-{p}-" in i for i in ctx.images)) for p in PARENTS)
    if marker(ctx.spec, "images-by-parent") != per:
        r.fail("G1-INVENTORY", f"images by parent {per} against the marker")
    r.numbers["surfaces"] = sum(row[1] == "surface" for row in table)
    r.numbers["components"] = sum(row[1] == "component" for row in table)
    r.numbers["images"] = n


# --- G2: the keyboard model -----------------------------------------------------------------------
def gate_keys(ctx: Ctx, r: Result) -> None:
    body = section(ctx.spec, "3.1 One table")
    kb = by_id(body, "KB")
    if len(kb) < 24:
        r.fail("G2-KEYS", f"section 3.1 has {len(kb)} KB rows (24 expected)")
    km = {c["id"]: c for c in E11.load_keymap()["commands"]}
    shipped_ids: list[str] = []
    reserved = E11.load_reserved()
    reserved_rows = 0
    for kid, row in kb.items():
        scope, status, resolution, source = row[3], row[4], row[6], row[7]
        if scope not in SCOPES:
            r.fail("G2-KEYS", f"{kid}: scope {scope!r} is not one of the five")
        if not status or not resolution or not CITE.search(source):
            r.fail("G2-KEYS", f"{kid}: status, resolution or source missing")
        if not RESOLUTION_RE.search(resolution):
            r.fail("G2-KEYS", f"{kid}: resolution {resolution!r} is not one of the vocabulary")
        if status.startswith("shipped"):
            ids = [t for t in ticks(status) if t in km]
            if not ids:
                r.fail("G2-KEYS", f"{kid}: a shipped row names no key-map command")
                continue
            shipped_ids += ids
            keys = ticks(row[2])
            if keys:
                want = {E11.nrm(k) for i in ids for k in E11.expand_keys(km[i]["defaultBinding"])}
                got = {E11.nrm(k) for raw in keys for k in E11.expand_keys(raw.replace(" / ", "/"))}
                got = {g for g in got if "/" not in g} or got
                if not got <= want:
                    r.fail(
                        "G2-KEYS",
                        f"{kid}: the spec binds {sorted(got)}, the key map ships {sorted(want)}",
                    )
                hit = [k for k in want if k in reserved]
                if hit:
                    reserved_rows += 1
                    if not all(km[i].get("reservedOverride") for i in ids):
                        r.fail("G2-KEYS", f"{kid}: a reserved key without a `reservedOverride`")
    allb = E11.shipped_bindings(E11.load_keymap())
    mine = [b for b in allb if b["id"] in shipped_ids]
    undeclared = 0
    for b in mine:
        for o in allb:
            same = o["key"] == b["key"] and o["id"] != b["id"]
            if same and E11.coactive(o["context"], b["context"]):
                undeclared += o["id"] not in b["shadows"] and b["id"] not in o["shadows"]
    checks = {
        "km-commands": str(len(km)),
        "rk-entries": str(len(json.loads(ctx.base["RK"]))),
        "kb-reserved-rows": str(reserved_rows),
        "kb-undeclared": str(undeclared),
    }
    for name, want in checks.items():
        if marker(ctx.spec, name) != want:
            r.fail(
                "G2-KEYS",
                f"marker {name}: the spec says {marker(ctx.spec, name)!r}, the engine {want}",
            )
    ks = by_id(section(ctx.spec, "14. The keyboard-only"), "KS")
    if len(ks) < 8:
        r.fail("G2-KEYS", f"section 14 has {len(ks)} KS steps (8 expected)")
    for sid, row in ks.items():
        if not ticks(row[2]):
            r.fail("G2-KEYS", f"{sid}: the step names no key")
    r.numbers["kb_rows"] = len(kb)
    r.numbers["kb_shipped_commands"] = len(set(shipped_ids))
    r.numbers.update({k: int(v) for k, v in checks.items()})
    r.numbers["ks_steps"] = len(ks)


# --- G3: the focus model --------------------------------------------------------------------------
def gate_focus(ctx: Ctx, r: Result) -> None:
    fm = by_id(section(ctx.spec, "4. The focus model"), "FM")
    want = [f"FM-{i:02d}" for i in range(1, 30)]
    missing = [w for w in want if w not in fm]
    if missing:
        r.fail("G3-FOCUS", f"FM rows missing: {missing}")
    for fid, row in fm.items():
        dest, source = row[4], row[6]
        if not dest or re.search(r"\bbody\b", dest):
            r.fail("G3-FOCUS", f"{fid}: no destination, or the body")
        if not CITE.search(source):
            r.fail("G3-FOCUS", f"{fid}: no source cite")
        if not row[7]:
            r.fail("G3-FOCUS", f"{fid}: no proof")
    for fid, row in by_id(section(ctx.spec, "11. Findings"), "F").items():
        if not FOCUS_RE.match(row[7]):
            r.fail("G3-FOCUS", f"{fid}: the Focus cell {row[7][:30]!r} is not from the vocabulary")
    r.numbers["fm_rows"] = len(fm)


# --- G4: regions ---------------------------------------------------------------------------------
def gate_regions(ctx: Ctx, r: Result) -> None:
    body = section(ctx.spec, "5. The region")
    rg = by_id(body, "RG")
    if len(rg) < 14:
        r.fail("G4-REGIONS", f"section 5.1 has {len(rg)} RG rows (14 expected)")
    for rid, row in rg.items():
        if not row[2] or not CITE.search(row[5]):
            r.fail("G4-REGIONS", f"{rid}: no role or no source")
    ring = "TopBar → NavRail → the tab strip → the panels in reading order → the minimised tray → RightRail → StatusBar"
    if ring not in body:
        r.fail("G4-REGIONS", "the ring sentence is missing")
    if "**Name** = `{Kind}, {symbol} {interval spelled}`" not in body:
        r.fail("G4-REGIONS", "R-5's name form (E15-D03 D-5's) is missing from section 5.2")
    r.numbers["rg_rows"] = len(rg)


# --- G5: the script and the budget ---------------------------------------------------------------
def gate_script(ctx: Ctx, r: Result) -> None:
    body = section(ctx.spec, "6.1 The script table")
    sr = by_id(body, "SR")
    if len(sr) < 50:
        r.fail("G5-SCRIPT", f"section 6.1 has {len(sr)} SR rows (50 expected)")
    for sid, row in sr.items():
        string, pol, queue, host = row[2], row[3], row[4], row[5]
        if not any(pol.startswith(p) for p in POLITENESS):
            r.fail("G5-SCRIPT", f"{sid}: politeness {pol!r} is not from the vocabulary")
        if pol not in ("none", "never") and pol[0] != "`" and (not queue or queue == "n/a"):
            r.fail("G5-SCRIPT", f"{sid}: a live row without a queueing rule")
        if pol in ("polite", "assertive") and not host:
            r.fail("G5-SCRIPT", f"{sid}: a live row without a host")
        if "no merged string" in string or "E09-D09 §4.4" in string:
            continue
        bad = quoted_in(QUOTED.findall(string), row_sources(row, ctx))
        if bad:
            r.fail("G5-SCRIPT", f"{sid}: not verbatim in a cited file: {bad[:2]}")
    bg = by_id(section(ctx.spec, "7. The announcement budget"), "BG")
    missing = [f"BG-{i:02d}" for i in range(1, 9) if f"BG-{i:02d}" not in bg]
    if missing:
        r.fail("G5-SCRIPT", f"BG rows missing: {missing}")
    if "**AC4's number: 1**" not in section(ctx.spec, "7. The announcement budget"):
        r.fail("G5-SCRIPT", "section 7 does not fix AC4's number")
    r.numbers["sr_rows"] = len(sr)
    r.numbers["bg_rows"] = len(bg)


# --- G6: T2 and the safety disclosures ----------------------------------------------------------
def state_key_chars(ctx: Ctx) -> tuple[int, int]:
    lines = ctx.base["D02"].splitlines()[668:677]
    lens = []
    for ln in lines:
        c = cells(ln)
        if len(c) > 2 and c[1].startswith('"'):
            lens.append(len(c[1].strip('"')))
    return (max(lens), min(lens)) if lens else (0, 0)


def gate_t2(ctx: Ctx, r: Result) -> None:
    body = section(ctx.spec, "8.1 The T2 table")
    t2 = by_id(body, "T2")
    if len(t2) < 20:
        r.fail("G6-T2", f"section 8.1 has {len(t2)} T2 rows (20 expected)")
    decks = [ctx.base[k] for k in DECKS]
    for tid, row in t2.items():
        cls, rendering, focus, checks = row[4], row[5], row[6], row[7]
        if cls not in CLASSES:
            r.fail("G6-T2", f"{tid}: class {cls!r} is not one of {CLASSES}")
        if cls == "T2":
            if not rendering or not re.search(r"2a|2b|sentence|one notice", rendering):
                r.fail("G6-T2", f"{tid}: a T2 row without a rendering")
            if "1a–d" not in checks:
                r.fail("G6-T2", f"{tid}: a T2 row without the 1a–d checks")
            if any(tok in " ".join(row) for tok in DISABLED_TOKENS):
                r.fail("G6-T2", f"{tid}: a disabled token on a T2 row")
        if not focus:
            r.fail("G6-T2", f"{tid}: no Focus cell")
        if "PROPOSED" in row[3]:
            continue
        for key, string in PAIR.findall(row[3]):
            if norm(string) not in norm(" ".join(decks)):
                r.fail("G6-T2", f"{tid}: `{key}` {string!r} stands in no parent")
    mx, mn = state_key_chars(ctx)
    if marker(ctx.spec, "state-key-chars") != f"{mx}/{mn}":
        r.fail(
            "G6-T2",
            f"the state keys measure {mx}/{mn} characters, not {marker(ctx.spec, 'state-key-chars')!r}",
        )
    sd = by_id(section(ctx.spec, "8.2 The safety disclosures"), "SD")
    if len(sd) < 8:
        r.fail("G6-T2", f"section 8.2 has {len(sd)} SD rows (8 expected)")
    for sid, row in sd.items():
        if not VERDICT_RE.match(row[3]):
            r.fail("G6-T2", f"{sid}: verdict {row[3]!r} is not from R-3")
    r.numbers["t2_rows"] = len(t2)
    r.numbers["t2_gated"] = sum(row[4] == "T2" for row in t2.values())
    r.numbers["state_key_chars"] = f"{mx}/{mn}"
    r.numbers["sd_rows"] = len(sd)


# --- G7: verdicts -------------------------------------------------------------------------------
def severities(spec: str) -> dict[str, str]:
    return {fid: row[1] for fid, row in by_id(section(spec, "11. Findings"), "F").items()}


def gate_verdict(ctx: Ctx, r: Result) -> None:
    sev = severities(ctx.spec)
    for head in ("10.1 `05` clauses", "10.2 WCAG 2.2 cross-walk"):
        for row in rows(section(ctx.spec, head)):
            verdict, evidence, ref = row[1], row[2], row[3]
            if not VERDICT_RE.match(verdict):
                r.fail("G7-VERDICT", f"{row[0]!r}: verdict {verdict!r} is not from R-3")
            fids = re.findall(r"F-\d\d", ref)
            if verdict == "at risk" and not (
                any(sev.get(f) in ("Major", "Blocking", "Minor") for f in fids)
                or "interim path" in evidence
            ):
                r.fail("G7-VERDICT", f"{row[0]!r}: at risk with no F row and no interim path")
            if verdict == "non-compliant" and not any(sev.get(f) == "Blocking" for f in fids):
                r.fail("G7-VERDICT", f"{row[0]!r}: non-compliant without a Blocking F row")
    r.numbers["clauses"] = len(rows(section(ctx.spec, "10.1 `05` clauses")))
    r.numbers["criteria"] = len(rows(section(ctx.spec, "10.2 WCAG 2.2 cross-walk")))


# --- G8: findings -------------------------------------------------------------------------------
def defined_ids(spec: str) -> set[str]:
    out: set[str] = set()
    for head, kinds in (
        ("3.1 One table", ("KB",)),
        ("4. The focus model", ("FM",)),
        ("5. The region", ("RG",)),
        ("6.1 The script table", ("SR",)),
        ("7. The announcement budget", ("BG",)),
        ("8.1 The T2 table", ("T2",)),
        ("8.2 The safety disclosures", ("SD",)),
        ("10.4 Colour never", ("CR",)),
        ("11. Findings", ("F",)),
        ("12.1 Contradictions", ("C",)),
        ("12.2 Gaps", ("G",)),
        ("12.3 Open questions", ("Q",)),
        ("12.4 Copy-ready", ("A",)),
        ("14. The keyboard-only", ("KS",)),
    ):
        for k in kinds:
            out.update(by_id(section(spec, head), k))
    out.update(re.findall(r"\*\*(HR-\d)\*\*", section(spec, "12.5 Heuristic")))
    return out


def gate_findings(ctx: Ctx, r: Result) -> None:
    body = section(ctx.spec, "11. Findings")
    f = by_id(body, "F")
    counts = [len(f)] + [sum(row[1] == s for row in f.values()) for s in SEVERITIES]
    want = "/".join(map(str, counts))
    if marker(ctx.spec, "f") != want:
        r.fail("G8-FINDINGS", f"the marker says {marker(ctx.spec, 'f')!r}, the table {want}")
    head = re.search(
        r"## 11\. Findings — F (\d+) \(Blocking (\d+) · Major (\d+) · Minor (\d+) · Info (\d+)\)",
        ctx.spec,
    )
    if not head or [int(x) for x in head.groups()] != counts:
        r.fail("G8-FINDINGS", f"the heading does not read the counts {counts}")
    for fid, row in f.items():
        sev, owner, target, gt2, focus = row[1], row[4], row[5], row[6], row[7]
        if sev not in SEVERITIES:
            r.fail("G8-FINDINGS", f"{fid}: severity {sev!r}")
        if not OWNER_RE.match(owner) or AGENT_RE.search(owner):
            r.fail("G8-FINDINGS", f"{fid}: owner {owner!r} is not a spec and an area")
        if TARGET not in target:
            r.fail("G8-FINDINGS", f"{fid}: target lacks {TARGET}")
        if sev != "Info" and not re.search(r"E15-S0\d \(#\d+\)", target):
            r.fail("G8-FINDINGS", f"{fid}: a non-Info row without a consuming story")
        if not gt2 or not focus:
            r.fail("G8-FINDINGS", f"{fid}: the G-T2 or the Focus cell is empty")
    blocking = [fid for fid, row in f.items() if row[1] == "Blocking"]
    if blocking and HOLD not in body:
        r.fail("G8-FINDINGS", "a Blocking row stands and the hold sentence is missing")
    if not blocking and HOLD in body:
        r.fail("G8-FINDINGS", "the hold sentence stands with no Blocking row")
    defined = defined_ids(ctx.spec)
    used = set(re.findall(r"(?<!RULED )\b(KB|FM|RG|SR|BG|T2|SD|CR|KS|F|G|Q)-(\d\d)\b", ctx.spec))
    dangling = sorted(f"{k}-{n}" for k, n in used if f"{k}-{n}" not in defined)
    if dangling:
        r.fail("G8-FINDINGS", f"ids used and defined nowhere: {dangling[:6]}")
    c_rows = by_id(section(ctx.spec, "12.1 Contradictions"), "C")
    g_rows = by_id(section(ctx.spec, "12.2 Gaps"), "G")
    q_rows = by_id(section(ctx.spec, "12.3 Open questions"), "Q")
    a_rows = by_id(section(ctx.spec, "12.4 Copy-ready"), "A")
    h_rows = re.findall(r"\*\*(HR-\d)\*\*", section(ctx.spec, "12.5 Heuristic"))
    line = (
        f"F {counts[0]} (Blocking {counts[1]} · Major {counts[2]} · Minor {counts[3]} · Info {counts[4]}); "
        f"C {len(c_rows)} · G {len(g_rows)} · Q {len(q_rows)} · A {len(a_rows)} · HR {len(h_rows)}"
    )
    if line not in section(ctx.spec, "16. Summary"):
        r.fail("G8-FINDINGS", f"section 16 does not read {line!r}")
    r.numbers["findings"] = want
    r.numbers["rows"] = {
        "C": len(c_rows),
        "G": len(g_rows),
        "Q": len(q_rows),
        "A": len(a_rows),
        "HR": len(h_rows),
    }


# --- G9: the rulings table ----------------------------------------------------------------------
def gate_ruled(ctx: Ctx, r: Result) -> None:
    body = section(ctx.spec, "R. Rulings applied")
    table = {row[0]: row for row in rows(body) if row[0].startswith("BQ-")}
    missing = [b for b in BQ_IDS if b not in table]
    extra = sorted(set(table) - set(BQ_IDS))
    if missing or extra:
        r.fail("G9-RULED", f"the rulings table: missing {missing}, extra {extra}")
    for bq, row in table.items():
        if not row[1] or not row[2]:
            r.fail("G9-RULED", f"{bq}: no default or no section")
        if row[3].split(" ")[0] not in BQ_STATUS:
            r.fail("G9-RULED", f"{bq}: status {row[3]!r} is not one of {BQ_STATUS}")
    stamps = set(STAMP.findall(ctx.spec))
    bad = sorted(s for s in stamps if s not in table)
    if bad:
        r.fail("G9-RULED", f"stamps pointing at no table row: {bad}")
    pending = any(row[3].startswith("pending") for row in table.values())
    if pending != (PENDING_LINE in ctx.spec):
        r.fail("G9-RULED", "the PENDING line and the table's statuses disagree")
    r.numbers["bq_rows"] = len(table)
    r.numbers["bq_pending"] = sum(row[3].startswith("pending") for row in table.values())
    r.numbers["stamps"] = len(stamps)


# --- G10: cites and pins ------------------------------------------------------------------------
def cites(spec: str) -> list[tuple[str, int, int]]:
    return [(k, int(a), int(b or a)) for k, a, b in CITE.findall(spec)]


def parse_pins(text: str) -> dict[tuple[str, int], str]:
    out: dict[tuple[str, int], str] = {}
    for ln in text.splitlines():
        if ln.strip() and not ln.startswith("#"):
            key, line, words = ln.split("|", 2)
            out[(key, int(line))] = words
    return out


def endpoints(spec: str) -> set[tuple[str, int]]:
    return {e for k, a, b in cites(spec) for e in ((k, a), (k, b))}


def gate_cite(ctx: Ctx, r: Result) -> None:
    found = cites(ctx.spec)
    for key, a, b in found:
        lines = ctx.base.get(key, "").splitlines()
        if key not in KEYS:
            r.fail("G10-CITE", f"`{key}`:{a}: an undeclared key")
        elif not (0 < a <= b <= len(lines)) or not lines[a - 1].strip() or not lines[b - 1].strip():
            r.fail("G10-CITE", f"`{key}`:{a}-{b}: out of range or blank at the base")
    pins = parse_pins(ctx.pins)
    for (key, n), words in pins.items():
        lines = ctx.base.get(key, "").splitlines()
        line = lines[n - 1] if 0 < n <= len(lines) else ""
        if not words.strip() or norm(words) not in norm(line):
            r.fail("G10-CITE", f"pin {key}:{n}: {words[:40]!r} is not on that line at the base")
    ends = endpoints(ctx.spec)
    uncited, unpinned = sorted(set(pins) - ends), sorted(ends - set(pins))
    if uncited or unpinned:
        r.fail(
            "G10-CITE", f"pins and cites disagree: uncited {uncited[:4]}; unpinned {unpinned[:4]}"
        )
    used = {k for k, _, _ in found}
    moved = sorted(k for k in used if ctx.bq_base.get(k) != ctx.base.get(k))
    if set(moved) - MOVED:
        r.fail("G10-CITE", f"cited files changed between the bases beyond {sorted(MOVED)}: {moved}")
    r.numbers["cites"] = len(found)
    r.numbers["endpoints"] = len(ends)
    r.numbers["pins"] = len(pins)
    r.numbers["moved_files"] = moved


def repin(ctx: Ctx) -> int:
    old = parse_pins(ctx.pins)
    lines = []
    for key, n in sorted(endpoints(ctx.spec), key=lambda e: (e[0], e[1])):
        text = norm(ctx.base[key].splitlines()[n - 1])
        lines.append(f"{key}|{n}|{old.get((key, n)) or text[:72].rstrip()}")
    head = (
        "# E15-D15 pins: KEY|line|words that stand on that line at the base (the tool's G10).\n"
        "# Written by `--repin-ruled` only; `--check` reads it (never hand-edit).\n"
    )
    PINS.write_text(head + "\n".join(lines) + "\n", encoding="utf-8")
    return len(lines)


# --- G11: colour --------------------------------------------------------------------------------
def lstar(hex6: str) -> float:
    def lin(c: int) -> float:
        v = c / 255
        return v / 12.92 if v <= 0.04045 else ((v + 0.055) / 1.055) ** 2.4

    y = (
        0.2126 * lin(int(hex6[1:3], 16))
        + 0.7152 * lin(int(hex6[3:5], 16))
        + 0.0722 * lin(int(hex6[5:7], 16))
    )
    return 116 * (y ** (1 / 3)) - 16 if y > 0.008856 else 903.3 * y


def hx(name: str, th: str) -> str | None:
    try:
        return str(D06T.hx(name, th))
    except (KeyError, ValueError, TypeError):
        return None


def union() -> list[tuple[str, str, str, bool]]:
    out: list[tuple[str, str, str, bool]] = []
    for p in D05T.PAIRS:
        out.append((p[1], p[2], p[3], bool(p[4])))
    for p in D06T.PAIRS:
        out.append((p[1], p[2], p[3], str(p[4]) == "gated"))
    return out


def union_line() -> tuple[str, dict[str, object]]:
    themes = list(D06T.THEMES)
    n = fail = 0
    minima = {"text": 99.0, "non-text": 99.0, "hc-text": 99.0}
    for fg, bg, role, gated in union():
        cols = [(hx(fg, th), hx(bg, th), th) for th in themes]
        if any(c[0] is None or c[1] is None for c in cols):
            continue
        n += 1
        kind = "text" if role.startswith("text") else "non-text"
        for f_hex, b_hex, th in cols:
            v = float(D06T.ratio(f_hex, b_hex))
            key = "hc-text" if (kind == "text" and th == "high-contrast") else kind
            if gated:
                minima[key] = min(minima[key], v)
                if v < BARS[key]:
                    fail += 1
    line = (
        f"**Union:** {n} token pairs · gated FAIL {fail} · gated minima text {minima['text']:.2f}, "
        f"non-text {minima['non-text']:.2f}, hc-text {minima['hc-text']:.2f} <!-- audit:contrast -->"
    )
    return line, {
        "union_pairs": n,
        "union_fail": fail,
        "minima": {k: round(v, 2) for k, v in minima.items()},
    }


def carrier(a_tokens: list[str], b_tokens: list[str]) -> tuple[str, str]:
    dl = 999.0
    dee = 999.0
    for th in D06T.THEMES:
        for a in a_tokens:
            for b in b_tokens:
                ha, hb = hx(a, th), hx(b, th)
                if ha is None or hb is None or a == b:
                    continue
                dl = min(dl, abs(lstar(str(D06T.grey(ha))) - lstar(str(D06T.grey(hb)))))
                for kind in SIMS:
                    dee = min(dee, float(D06T.de(str(D06T.sim(ha, kind)), str(D06T.sim(hb, kind)))))
    return f"{dl:.1f}", f"{dee:.1f}"


CR_TOKENS = {
    "CR-01": (["color.focus.ring"], list(SURFACE_TOKENS)),
    "CR-02": (
        ["color.sync.a", "color.sync.b", "color.sync.c"],
        ["color.sync.a", "color.sync.b", "color.sync.c"],
    ),
    "CR-03": (["color.focus.ring"], ["color.text.primary"]),
    "CR-04": (["color.env.demo"], ["color.env.live"]),
}


def gate_colour(ctx: Ctx, r: Result) -> None:
    line, nums = union_line()
    if line not in ctx.spec:
        r.fail("G11-COLOUR", f"section 10.3 does not read {line!r}")
    r.numbers.update(nums)
    cr = by_id(section(ctx.spec, "10.4 Colour never"), "CR")
    for cid, (a, b) in CR_TOKENS.items():
        dl, dee = carrier(a, b)
        row = cr.get(cid)
        if not row or row[4] != dl or row[5] != dee:
            r.fail(
                "G11-COLOUR",
                f"{cid}: measured {dl} / {dee}, the row says {row[4:6] if row else None}",
            )
        r.numbers[cid] = {"dL": dl, "dE76": dee}
    for cid, row in cr.items():
        if cid not in CR_TOKENS and (row[4], row[5]) != ("not measured", "not measured"):
            r.fail("G11-COLOUR", f"{cid}: an unmeasured family with numbers")
    cvd = sum("-cvd-" in i for i in ctx.images)
    if marker(ctx.spec, "cvd-images") != str(cvd):
        r.fail(
            "G11-COLOUR",
            f"the base holds {cvd} CVD renders, the marker says {marker(ctx.spec, 'cvd-images')!r}",
        )
    r.numbers["cr_rows"] = len(cr)
    r.numbers["cvd_images"] = cvd


# --- G12: hygiene -------------------------------------------------------------------------------
def gate_hygiene(ctx: Ctx, r: Result) -> None:
    for name, text in (("the spec", ctx.spec), ("the tool", ctx.tool), ("the pins", ctx.pins)):
        low = text.lower()
        for word in BANNED:
            if word.lower() in low:
                r.fail("G12-HYGIENE", f"{name}: a word from the lane-private list")
        if host := HOST.search(text):
            r.fail("G12-HYGIENE", f"{name}: a host name {host.group(0)!r}")
        if UUID.search(text):
            r.fail("G12-HYGIENE", f"{name}: an id in the uuid form")
    local = "/" + "home/|/tmp/|/mnt/|[A-Z]:\\\\"
    for pat, what in (
        (local, "a local path"),
        (r"https?://", "a URL"),
        (r"\b(?:close[sd]?|fix(?:e[sd])?|resolve[sd]?) #\d", "a closing keyword"),
    ):
        if re.search(pat, ctx.spec, re.IGNORECASE):
            r.fail("G12-HYGIENE", f"the spec: {what}")
    examples = "".join(
        section(ctx.spec, h)
        for h in (
            "6.1 The script table",
            "8.1 The T2 table",
            "11. Findings",
            "13. The screen-reader",
            "14. The keyboard-only",
        )
    )
    bad = [q for q in QUOTED.findall(examples) if FIXTURE.search(q)]
    if bad:
        r.fail("G12-HYGIENE", f"an example string with a fixture account: {bad[:2]}")


# --- G13: the BQ-04 unstated test -----------------------------------------------------------------
def gate_unstated(ctx: Ctx, r: Result) -> None:
    """R369 BQ-04: a PROPOSED destination is Minor where the trigger survives (`05`:96 yields it)
    and Blocking where the operation can remove the focused element; an F row whose merged
    sentence names a removed element is Blocking."""
    if UNSTATED_CLAUSE not in section(ctx.spec, "1.4 Rules stated once"):
        r.fail("G13-UNSTATED", "R-1 does not state BQ-04's precise reading of 'unstated'")
    sev = severities(ctx.spec)
    proposed = 0
    for fid, row in by_id(section(ctx.spec, "4. The focus model"), "FM").items():
        dest = row[4]
        for f in PROPOSED_FM.findall(dest):
            proposed += 1
            removed = "else moves to" in dest or "removed element" in dest
            want = "Blocking" if removed else "Minor"
            if sev.get(f) != want:
                why = "the focused element can be removed" if removed else "the trigger survives"
                r.fail(
                    "G13-UNSTATED",
                    f"{fid}: the PROPOSED destination for {f} ({why}) wants {want}, "
                    f"the F row is {sev.get(f)!r}",
                )
    for fid, row in by_id(section(ctx.spec, "11. Findings"), "F").items():
        focus_row = row[7] != "n/a" and row[1] != "Info"
        if focus_row and REMOVED_RE.search(row[2]) and row[1] != "Blocking":
            r.fail("G13-UNSTATED", f"{fid}: a removed element in the merged sentence, {row[1]}")
    r.numbers["fm_proposed"] = proposed


# --- G14: findings against the `05` clause and WCAG rows ----------------------------------------
def clause(head: str) -> tuple[str, frozenset[int] | None] | None:
    """A section 10.1 row head: `§3.4 item 4 — …` → ("§3.4", {4}); `§3.3 items 1–4 — …` →
    ("§3.3", {1, 2, 3, 4}); `§5 items 1, 2 and 6 — …` → ("§5", {1, 2, 6}); `§6.2 — …` → no items."""
    m = CLAUSE_HEAD.match(head)
    if not m:
        return None
    sec, items = m.group(1), m.group(2)
    if not items:
        return (sec, None)
    nums: set[int] = set()
    for a, b in re.findall(r"(\d+)(?:–(\d+))?", items):
        nums.update(range(int(a), int(b or a) + 1))
    return (sec, frozenset(nums))


def clause_hit(cite: tuple[str, int | None], row: tuple[str, frozenset[int] | None]) -> bool:
    """A `05` § cite names a row when the sections agree and the cite's item, if any, is in the row's."""
    sec, item = cite
    return sec == row[0] and (item is None or (row[1] is not None and item in row[1]))


def gate_criteria(ctx: Ctx, r: Result) -> None:
    f_rows = by_id(section(ctx.spec, "11. Findings"), "F")
    graded = {fid for fid, row in f_rows.items() if row[1] in ("Blocking", "Major", "Minor")}
    citing: dict[str, set[str]] = {}
    for fid in graded:
        for c in WCAG_RE.findall(f_rows[fid][2]):
            citing.setdefault(c, set()).add(fid)
    seen: set[str] = set()
    for row in rows(section(ctx.spec, "10.2 WCAG 2.2 cross-walk")):
        number = row[0].split(" ")[0]
        if number in seen:
            continue
        seen.add(number)
        listed = set(re.findall(r"F-\d\d", row[3])) & graded
        cites = citing.get(number, set())
        if row[1].startswith("compliant") and (listed or cites):
            r.fail(
                "G14-CRITERIA",
                f"{number}: compliant while {sorted(listed | cites)} stand against it",
            )
        elif cites - listed:
            r.fail("G14-CRITERIA", f"{number}: {sorted(cites - listed)} cite it and are not listed")
    for number in sorted(set(citing) - seen):
        r.fail("G14-CRITERIA", f"{sorted(citing[number])} cite WCAG {number}, which has no row")
    # the same check over section 10.1: an F row's merged sentence cites a `05` clause by its label
    f_clauses: dict[str, set[tuple[str, int | None]]] = {}
    for fid in graded:
        for sec, item in CLAUSE_RE.findall(f_rows[fid][2]):
            f_clauses.setdefault(fid, set()).add((sec, int(item) if item else None))
    matched: set[str] = set()
    for row in rows(section(ctx.spec, "10.1 `05` clauses")):
        parsed = clause(row[0])
        label = row[0].split(" — ")[0]
        listed = set(re.findall(r"F-\d\d", row[3])) & graded
        cites = {
            fid
            for fid, cs in f_clauses.items()
            if parsed is not None and any(clause_hit(c, parsed) for c in cs)
        }
        matched |= cites
        if row[1].startswith("compliant") and (listed or cites):
            r.fail(
                "G14-CRITERIA",
                f"`05` {label}: compliant while {sorted(listed | cites)} stand against it",
            )
        elif cites - listed:
            r.fail(
                "G14-CRITERIA", f"`05` {label}: {sorted(cites - listed)} cite it and are not listed"
            )
    for fid in sorted(set(f_clauses) - matched):
        r.fail("G14-CRITERIA", f"{fid} cites a `05` clause with no section 10.1 row")
    r.numbers["criteria_cited"] = {k: sorted(v) for k, v in sorted(citing.items())}
    r.numbers["clauses_cited"] = {
        fid: sorted(f"{s} item {i}" if i else s for s, i in cs)
        for fid, cs in sorted(f_clauses.items())
    }


# --- G15: the FM rows' SR ids against the SR rows -------------------------------------------------
def sr_ids(cell: str) -> set[str]:
    ids = {f"SR-{i:02d}" for a, b in SR_RANGE.findall(cell) for i in range(int(a), int(b) + 1)}
    ids.update(f"SR-{n}" for n in SR_ONE.findall(SR_RANGE.sub(" ", cell)))
    return ids


def words(text: str) -> set[str]:
    return {w.lower() for w in WORD.findall(text)} - STOP


def overlap(a: set[str], b: set[str]) -> bool:
    return any(x == y or x[:4] == y[:4] for x in a for y in b)


def gate_xref(ctx: Ctx, r: Result) -> None:
    sr = by_id(section(ctx.spec, "6.1 The script table"), "SR")
    checked = 0
    for fid, row in by_id(section(ctx.spec, "4. The focus model"), "FM").items():
        cell = row[5]
        ids = sr_ids(cell)
        if not ids:
            continue
        checked += 1
        problems: list[str] = []
        missing = sorted(i for i in ids if i not in sr)
        if missing:
            problems.append(f"undefined {missing}")
        targets = [sr[i] for i in sorted(ids) if i in sr]
        hay = norm(" ".join(t[2] for t in targets))
        parents = norm(" ".join(row_sources(row, ctx)))
        for q in QUOTED.findall(cell):
            if len(q) >= 8 and "…" not in q and norm(q) not in hay:
                problems.append(f"{q!r} is in no cited SR string")
        for key in ticks(cell):
            if not key.startswith("e15."):
                continue
            pat = re.compile(re.escape(key).replace(r"\*", r"[a-z_.]+"))
            if not any(pat.search(t[2]) for t in targets) and key not in parents:
                problems.append(f"`{key}` is in no cited SR string or parent")
        mine = words(" ".join((row[1], row[2], row[3], SR_ONE.sub(" ", SR_RANGE.sub(" ", cell)))))
        for t in targets:
            if not overlap(mine, words(t[1] + " " + t[2])):
                problems.append(f"{t[0]} ({t[1][:32]!r}) shares no word with the operation")
        if problems:
            r.fail("G15-XREF", f"{fid}: " + "; ".join(problems)[:220])
    r.numbers["fm_sr_xref"] = checked


# --- G16: the budget's coalescing rule ------------------------------------------------------------
def gate_budget(ctx: Ctx, r: Result) -> None:
    bg = by_id(section(ctx.spec, "7. The announcement budget"), "BG")
    sr = by_id(section(ctx.spec, "6.1 The script table"), "SR")
    rule = bg.get("BG-03", ["", ""])[1]
    if COALESCE_RULE not in rule or "never swallows an assertive row" not in rule:
        r.fail("G16-BUDGET", "BG-03 does not state R369 BQ-13's rule")
    m = re.search(r"\(([^)]*)\) are \*\*suppressed\*\*", rule)
    suppressed = re.findall(r"SR-\d\d", m.group(1)) if m else []
    if not suppressed:
        r.fail("G16-BUDGET", "BG-03 names no suppressed SR rows")
    swallowed = [s for s in suppressed if s in sr and "assertive" in sr[s][3][:14]]
    if swallowed:
        r.fail("G16-BUDGET", f"BG-03 suppresses assertive rows {swallowed}")
    if "never swallowed" not in section(ctx.spec, "13. The screen-reader"):
        r.fail("G16-BUDGET", "section 13's apply scenario does not name the rule")
    r.numbers["bg_suppressed"] = suppressed


GATE_FNS: tuple[tuple[str, Callable[[Ctx, Result], None]], ...] = (
    ("G1-INVENTORY", gate_inventory),
    ("G2-KEYS", gate_keys),
    ("G3-FOCUS", gate_focus),
    ("G4-REGIONS", gate_regions),
    ("G5-SCRIPT", gate_script),
    ("G6-T2", gate_t2),
    ("G7-VERDICT", gate_verdict),
    ("G8-FINDINGS", gate_findings),
    ("G9-RULED", gate_ruled),
    ("G10-CITE", gate_cite),
    ("G11-COLOUR", gate_colour),
    ("G12-HYGIENE", gate_hygiene),
    ("G13-UNSTATED", gate_unstated),
    ("G14-CRITERIA", gate_criteria),
    ("G15-XREF", gate_xref),
    ("G16-BUDGET", gate_budget),
)


def run(ctx: Ctx) -> Result:
    r = Result()
    for _, fn in GATE_FNS:
        fn(ctx, r)
    return r


# --- self-test ----------------------------------------------------------------------------------
Mut = Callable[[Ctx], Ctx]


def sub(old: str, new: str) -> Mut:
    return lambda c: c._replace(spec=c.spec.replace(old, new, 1))


def regex(pattern: str, repl: str) -> Mut:
    return lambda c: c._replace(spec=re.sub(pattern, repl, c.spec, count=1, flags=re.MULTILINE))


def pin_sub(old: str, new: str) -> Mut:
    return lambda c: c._replace(pins=c.pins.replace(old, new, 1))


MUTATIONS: tuple[tuple[str, Mut], ...] = (
    (
        "G1-INVENTORY",
        regex(r"(\| SCR-021 Dock / panel system\s+\| surface\s+\| )reviewed", r"\1pending "),
    ),
    (
        "G2-KEYS",
        regex(r"(\| KB-03 \| Save as new layout\s+\| )`Ctrl\+Shift\+S`", r"\1`Ctrl+Alt+S`  "),
    ),
    (
        "G3-FOCUS",
        regex(r"(\| FM-08 \| Maximise; Restore[^\n]*?\| )kept · the panel( +\|)", r"\1the body\2"),
    ),
    ("G4-REGIONS", regex(r"(\| RG-03 \| The workspace toolbar\s+\| )`toolbar`", r"\1         ")),
    (
        "G5-SCRIPT",
        regex(
            r"(\| SR-36 \| An axis switch toggled\s+\| )\"Interval sync on for group A\.",
            r"\1\"Interval sync up for group A.",
        ),
    ),
    ("G6-T2", regex(r"(\| T2-04 \|[^\n]*?\| )T2( +\| 2a)", r"\1gated\2")),
    (
        "G7-VERDICT",
        regex(
            r"(\| §3\.1 rule 2 — one global hotkey layer, view keys additive\s+\| )compliant",
            r"\1at risk  ",
        ),
    ),
    (
        "G8-FINDINGS",
        regex(
            r"(\| F-04 \|[^\n]*?\| )E15-D05 · area/charting-ui( +\| E15-D16)",
            r"\1the dock session\2",
        ),
    ),
    ("G9-RULED", regex(r"(\| BQ-17 \|[^\n]*\| )RULED · confirmed", r"\1maybe · confirmed")),
    ("G10-CITE", pin_sub("CAL|13|SPRINT01_START", "CAL|13|SPRINT99_START")),
    ("G11-COLOUR", sub("<!-- audit:cvd-images=", "<!-- audit:cvd-images=1")),
    (
        "G12-HYGIENE",
        sub("## 16. Summary for #369", "## 16. Summary for #369 (see https://example.test)"),
    ),
    (
        "G13-UNSTATED",
        sub(
            "kept · the activated tab or tree item (APG manual activation)",
            "kept · the activated tab or tree item (APG manual activation); else moves to · the first tab",
        ),
    ),
    ("G14-CRITERIA", regex(r"(\| 2\.4\.3 Focus order\s+\| )non-compliant", r"\1compliant    ")),
    (
        "G14-CRITERIA",
        regex(
            r"(\| §3\.4 item 4 — modals trap, return focus, `Esc` cancels\s+\| )non-compliant",
            r"\1compliant    ",
        ),
    ),
    (
        "G15-XREF",
        regex(
            r"(\| FM-24 \|[^\n]*?\| )SR-18 \"Renamed to Swing 1D\.\"",
            r"\1SR-19 \"Renamed to Swing 1D.\"",
        ),
    ),
    (
        "G16-BUDGET",
        sub(
            "(SR-10, SR-11, SR-30, SR-31) are **suppressed**",
            "(SR-10, SR-11, SR-30, SR-33) are **suppressed**",
        ),
    ),
)


def digests() -> dict[str, str]:
    paths = (SPEC, PINS, Path(__file__))
    return {str(p): hashlib.sha256(p.read_bytes()).hexdigest() for p in paths if p.exists()}


def self_test(ctx: Ctx, base: Result) -> list[str]:
    bad: list[str] = []
    before = digests()
    covered = {code for code, _ in MUTATIONS}
    bad += [f"self-test: gate {g} has no mutation" for g, _ in GATE_FNS if g not in covered]
    for code, fn in MUTATIONS:
        mutated = fn(ctx)
        if mutated == ctx:
            bad.append(f"self-test {code}: the mutation did not apply")
            continue
        new = sorted(set(run(mutated).fails) - set(base.fails))
        if len(new) != 1 or not new[0].startswith(f"[{code}]"):
            bad.append(f"self-test {code}: expected one new [{code}] FAIL, got {new[:3]}")
    again = run(ctx)
    if again.fails != base.fails or again.numbers != base.numbers:
        bad.append("self-test: a re-run does not reproduce the base result")
    if digests() != before:
        bad.append("self-test: a file on disk changed")
    return bad


def main(argv: list[str]) -> int:
    ap = argparse.ArgumentParser(description=(__doc__ or "").splitlines()[0])
    ap.add_argument("--check", action="store_true", help="exit 1 on any FAIL")
    ap.add_argument("--json", action="store_true", help="print the numbers and findings as JSON")
    ap.add_argument("--self-test", "--selftest", action="store_true", help="the mutation self-test")
    ap.add_argument(
        "--repin-ruled", action="store_true", help="rewrite the pins file from the cites"
    )
    args = ap.parse_args(argv)
    ctx = load_ctx()
    if not all(ctx.base.values()):
        missing = [k for k, v in ctx.base.items() if not v]
        print(f"FAIL [G10-CITE] cannot read {missing} at the base (fetch first)")
        return 1
    if args.repin_ruled:
        print(f"pins written: {repin(ctx)}")
        ctx = load_ctx()
    res = run(ctx)
    st = self_test(ctx, res) if args.self_test else []
    if args.json:
        payload: dict[str, object] = {
            "numbers": res.numbers,
            "fails": res.fails,
            "warns": res.warns,
        }
        if args.self_test:
            payload["self_test"] = st
        print(json.dumps(payload, ensure_ascii=False, indent=1, sort_keys=True))
    else:
        out = [f"FAIL {line}" for line in res.fails] + [f"WARN {line}" for line in res.warns]
        out += [f"{k}: {v}" for k, v in res.numbers.items()]
        out.append(f"gates: {len(GATE_FNS)}; FAIL {len(res.fails)}, WARN {len(res.warns)}")
        if args.self_test:
            out += [f"FAIL {line}" for line in st]
            out.append(
                f"self-test: {'ok' if not st else 'FAILED'}: {len(MUTATIONS)} mutations (at least one "
                "per gate), each one new FAIL; a re-run reproduces the base result; files on disk unchanged"
            )
        print("\n".join(out))
    failed = bool(res.fails or st)
    return 1 if (failed and (args.check or args.self_test)) else 0


if __name__ == "__main__":
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")
    raise SystemExit(main(sys.argv[1:]))
