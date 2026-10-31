"""E08-D12 (#180) audit: the accessibility design review of the E08 market-data surfaces.

Stdlib only, offline (`python3 -I -B`). It reads the spec and the pins file from the working tree,
and every cited file AS TEXT at `origin/main` with `git show`. It imports, never copies: the E11-D07
key-map engine (`nrm`, `expand_keys`, `load_keymap`, `shipped_bindings`, `load_reserved`,
`coactive`), the E08-D05 audit's theme resolver (`col`, `THEMES`, `PAIRS`), the E08-D08 audit's
`PAIRS`, `contrast_check.contrast_ratio`, and the CVD projections of `cvd_sim.py` (when NumPy is
present) or `docs/research/_tools/cvd_simulate.py` (always; it also gives ΔE76 and L*). Default-deny:
a gate that cannot read its input FAILs. Twenty-three gates, each FAIL led by its code:

- [G1-INVENTORY] section 2 lists the seven hi-fi surfaces as reviewed and the two structure-only
  ones as out of scope to E08-D09 / E08-D10; every component row has a verdict; the image counts
  equal the merged E08 images at the base.
- [G2-KEYS] section 3.1: every KB row has a scope, a status, a resolution and a source; a shipped
  row's binding equals the key map's; the engine markers are recomputed; section 14's KS steps name
  a key.
- [G3-FOCUS] section 4: FM-01..FM-24, every destination named (never the body), sourced, proven;
  section 11's `Focus` cells from the vocabulary.
- [G4-REGIONS] section 5.1: every RG row has a role and a source; section 5.2 states the vocabulary.
- [G5-SCRIPT] section 6.1: a politeness from the vocabulary, a queueing rule and a host on every
  live row; every quoted string stands verbatim in a file the row cites; section 13 holds the
  Gherkin blocks, the no-run sentence and the rendering table.
- [G6-BUDGET] section 7: BG-01..BG-14, a `max_rate` and an object per row; BG-11 states the
  coalescing rule and suppresses no assertive row; the AC2 sentence stands.
- [G7-T2] section 8.1: a class per row; a T2 row names a rendering and the 1a–d checks and carries
  no disabled token; every `key` "string" pair stands in a parent; section 8.2's SD rows carry a
  verdict.
- [G8-VERDICT] sections 10.1, 10.1b and 10.2: a verdict from R-3's list; `at risk` names an F row or
  an interim path, `non-compliant` a Blocking one.
- [G9-FINDINGS] section 11: the count marker against the rows; severity, owner (a spec and an area),
  target E08-D13 (#181) plus a consumer, the `G-T2`, `Focus` and `Rate` cells; the hold sentence
  iff a Blocking row stands; no dangling id; the row markers; section 16's counts.
- [G10-RULED] section R lists BQ-01..BQ-25 once each with the ruling stamp; every "RULED BQ-nn"
  stamp points at a listed BQ.
- [G11-CITE] every `KEY`:line cite resolves at the base to a non-blank line; the pins file and the
  cited endpoints match both ways and each pin's words stand on its line; no cited file other than
  `14` and `15` changed between the BQ list's base and this base.
- [G12-COLOUR] the union line, the DS-CR-1 ΔE, the CR rows and the CVD image count are recomputed.
- [G13-HYGIENE] no lane-private word, host, uuid, local path, URL, loopback port, advisory id or
  closing keyword in the spec, the tool or the pins; no fixture account in a quoted example.
- [G14-UNSTATED] R369 BQ-04's precise test stands in R-1; a PROPOSED destination is graded by
  whether the operation can remove the focused element; a removed element in a merged sentence is
  Blocking.
- [G15-CRITERIA] a section 10.1 or 10.2 row never reads `compliant` while a graded F row cites it;
  every cited clause and criterion lists its F rows.
- [G16-XREF] every SR id an FM or KS row names, or the spec uses anywhere, is defined.
- [G17-PARITY] every PP row has a keyboard path and a cite, none a pointer word; the no-Blocking
  sentence stands.
- [G18-STRUCT] every SCR-147 / SCR-151 cell is out of scope, structure or not yet decidable; none
  reads approved.
- [G19-DOM] no F-row replacement adds a DOM node per cell or row.
- [G20-RATE] every `Rate` / `max_rate` cell is from the vocabulary and every numeric rate stands on
  a line the row cites.
- [G21-EDIT-SET] the working-tree `14` differs from the base by exactly the nine pointer lines, each
  inside its entry; the parents, their hand-offs and `15` are untouched.
- [G22-CALENDAR] the sprint markers equal the dates computed from `CAL`.
- [G23-WALK] the owner walkthrough has at most ten items under its post-Done heading; the summary
  markers equal the primary ones.

`--json` prints the numbers and findings; `--check` exits 1 on any FAIL; `--fill` rewrites the
computed markers and the union / DS-CR-1 / CR numbers in the spec; `--self-test` applies at least one
mutation per gate to an in-memory copy and passes only when each adds new FAILs of its gate's code
only, a re-run reproduces the base result and no file on disk changed. `--repin-ruled` rewrites the
pins file from the spec's cites and is the only writer of that file.

Usage: python3 -I -B docs/design/_tools/e08_d12_a11y_review_audit.py [--check] [--json] [--fill]
       [--self-test] [--repin-ruled]
"""

from __future__ import annotations

import argparse
import codecs
import datetime
import functools
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
SPEC = ROOT / "docs" / "design" / "E08" / "E08-D12.md"
PINS = TOOLS / "e08_d12_ruled_pins.txt"
HEAD = "origin/main"
BQ_BASE = "b8575c6f1b71bbb480490768aaf439047a39c861"  # where the BQ list read every cite
MOVED = {"14", "15"}  # the two files that changed between the bases (section 1.5)
IMG_DIR = "docs/design/E08/img"
TICKET = "#180"
RULED_STAMP = "RULED (orchestrator, 2026-10-31, #180 ruling of record — 6536406500's answer)"
POINTER_MARK = "**A11y review (E08-D12):**"
POINTER_ENTRIES = (
    "SCR-041",
    "SCR-100",
    "SCR-101",
    "SCR-102",
    "SCR-103",
    "SCR-104",
    "SCR-147",
    "SCR-151",
    "SCR-152",
)
KEYS: dict[str, str] = {
    "02": "docs/plan/02-definition-of-ready-done.md",
    "05": "docs/plan/05-accessibility-standard.md",
    "11": "docs/plan/11-user-stories.md",
    "14": "docs/plan/14-screens-catalogue.md",
    "15": "docs/plan/15-component-catalogue.md",
    "16": "docs/plan/16-design-system-brief.md",
    "DS": ".claude/rules/32-design-specs.md",
    "KM": "apps/web/src/keymap/keymap.json",
    "PREF": "apps/web/src/features/a11y-preferences/model.ts",
    "TOK": "packages/ui/tokens/semantic-dark.tokens.json",
    "PKG": "apps/web/package.json",
    "CAL": "docs/plan/backlog/_tools/calendar_cv.py",
    "README": "docs/design/README.md",
    "D01": "docs/design/E08/E08-D01.md",
    "D02": "docs/design/E08/E08-D02.md",
    "D03": "docs/design/E08/E08-D03.md",
    "D04": "docs/design/E08/E08-D04.md",
    "D05": "docs/design/E08/E08-D05.md",
    "D05H": "docs/design/E08/E08-D05-handoff.md",
    "D06": "docs/design/E08/E08-D06.md",
    "D06H": "docs/design/E08/E08-D06-handoff.md",
    "D07": "docs/design/E08/E08-D07.md",
    "D08": "docs/design/E08/E08-D08.md",
    "D08H": "docs/design/E08/E08-D08-handoff.md",
    "D11": "docs/design/E08/E08-D11.md",
    "E17-D01": "docs/design/E17/E17-D01.md",
    "E17-D02": "docs/design/E17/E17-D02.md",
    "E09-D09": "docs/design/E09/E09-D09.md",
    "E16-D05": "docs/design/E16/E16-D05.md",
    "E16-D06": "docs/design/E16/E16-D06.md",
    "E15-D15": "docs/design/E15/E15-D15.md",
}
DECKS = (
    "D03",
    "D04",
    "D05",
    "D06",
    "D07",
    "D08",
    "D11",
    "E17-D01",
    "E17-D02",
    "E09-D09",
    "14",
    "15",
)
UNTOUCHED = (
    "D01",
    "D02",
    "D03",
    "D04",
    "D05",
    "D05H",
    "D06",
    "D06H",
    "D07",
    "D08",
    "D08H",
    "D11",
    "15",
)
IMAGE_PARENTS = ("D02", "D03", "D04", "D05", "D07", "D08", "D11")
SURFACES_REVIEWED = (
    "SCR-152",
    "SCR-102",
    "SCR-041",
    "SCR-103",
    "SCR-100",
    "SCR-101",
    "SCR-104",
)
SURFACES_OUT = {"SCR-147": "E08-D09 (#177)", "SCR-151": "E08-D10 (#178)"}
SCOPES = ("`global`", "`panel`", "`dialog`", "`component`", "`page`", "—")
RESOLUTION_RE = re.compile(
    r"shadow declared|context-scoped|context-exclusive|dropped|pending|none|withdrawn|"
    r"out of scope|in flight|pass-through"
)
POLITENESS = ("polite", "assertive", "none", "never", "— (G-")
FOCUS_RE = re.compile(r"^(kept · |moves to · |returns to · |restored to · |n/a)")
RATE_RE = re.compile(
    r"^(never|once per [a-z0-9 ()]+|≤ 1 per \d+(?:\.\d+)? s per (?:field|region|surface)|n/a)$"
)
RATE_NUM = re.compile(r"≤ 1 per (\d+(?:\.\d+)?) s")
OBJECTS = ("field", "region", "episode", "surface")
CLASSES = ("T2", "validity", "availability", "busy", "sentence", "absence", "n/a")
DISABLED_TOKENS = ("opacity.disabled", "color.text.disabled")
SEVERITIES = ("Blocking", "Major", "Minor", "Info")
VERDICT_RE = re.compile(
    r"^(compliant|at risk|non-compliant|out of scope — .+|"
    r"not yet decidable — routed to E08-Q05 \(#282\)|n/a — )"
)
OWNER_RE = re.compile(r"^(E08-D\d\d · area/ingestion|E17-D02 · area/backend-platform)$")
PERSON_RE = re.compile(r"\bagent\b|\bworker\b", re.IGNORECASE)
TARGET = "E08-D13 (#181)"
CONSUMER_RE = re.compile(r"E08-(?:S\d\d|Q05) \(#\d+\)")
HOLD = "cannot be Done until fixed or an exception is recorded on #180"
BQ_IDS = tuple(f"BQ-{i:02d}" for i in range(1, 26))
PENDING_LINE = "**Ruling status: PENDING.**"
UNSTATED_CLAUSE = "**no merged text _and no `05` rule_ yields the destination**"
COALESCE_RULE = '**"1 polite summary + any assertive safety row"**'
NO_RUN = "**Nothing here claims a screen-reader run.**"
WALK_HEAD = '**"owner walkthrough: post-Done (#2701)"**'
PROPOSED_FM = re.compile(r"PROPOSED \((F-\d\d)\)")
REMOVED_RE = re.compile(r"\bremov")
WCAG_RE = re.compile(r"WCAG (\d\.\d\.\d{1,2})\b")
CLAUSE_RE = re.compile(r"`05` (§\d+(?:\.\d+)?)(?: (?:item|rule) (\d+))?")
CLAUSE_HEAD = re.compile(r"(§\d+(?:\.\d+)?)(?: (?:items?|rules?) ([^—]*))?")
SR_ONE = re.compile(r"SR-(\d\d)")
SR_RANGE = re.compile(r"SR-(\d\d)\.\.(?:SR-)?(\d\d)")
ID_RE = re.compile(r"(?<!RULED )(?<!DS-)\b(KB|PP|FM|RG|BG|T2|SD|CR|KS|F|G|Q|A)-(\d\d?)\b")
SR_ANY = re.compile(r"(?<!E16-D06 )(?<!§6\.1 )\bSR-(\d\d)\b")
C_ID_RE = re.compile(r"\bC-([a-z])\b")
POINTER_WORDS = re.compile(r"pointer only|drag only|hover only|right-click only|not written")
DOM_RE = re.compile(
    r"\b(?:node|element|wrapper)\b[^|]{0,40}\bper (?:cell|row)\b|"
    r"\bper (?:cell|row)\b[^|]{0,40}\b(?:node|element|wrapper)\b"
)
BARS = {"text": 4.5, "non-text": 3.0, "hc-text": 7.0}
SIMS = ("protanopia", "deuteranopia", "tritanopia")
BG_SURFACES = ("raised", "hover", "selected", "sunken", "canvas", "overlay", "app")
# lane-private words, rot13 so that the tool never contains them in clear
BANNED_ROT13 = "ucr-jbexre upy-jbexre ggonfvy onfvygg Ntrag_P"
BANNED = [w.replace("_", " ") for w in codecs.decode(BANNED_ROT13, "rot13").split()]
HOST = re.compile(r"\b[a-z0-9-]+\.(?:com|net|io|dev|org|app)\b", re.IGNORECASE)
URL = re.compile(r"https?://|\bwww\.", re.IGNORECASE)
UUID = re.compile(r"\b[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}\b")
LOCAL_PATH = re.compile(r"/(?:ho[m]e|Users|tmp|mnt)/[^/\s]+/|[A-Z]:\\")
ADVISORY_ID = re.compile(
    r"\b(?:GH[S]A-[0-9a-z]{4}-[0-9a-z]{4}-[0-9a-z]{4}|C[V]E-\d{4}-\d{4,})\b", re.IGNORECASE
)
LOOPBACK = re.compile(r"(?:\blocalhost|\b(?:\d{1,3}\.){3}\d{1,3}):\d{2,5}\b", re.IGNORECASE)
CLOSING = re.compile(r"\b(?:close[sd]?|fix(?:e[sd])?|resolve[sd]?)\s+#\d", re.IGNORECASE)
FIXTURE = re.compile(r"\b(?:Main|Desk4|Core3|sub_00\d)\b")
QUOTED = re.compile(r'"([^"\n]*)"')
CITE = re.compile(r"`([A-Za-z0-9.\-]+)`:(\d+)(?:[–-]:?(\d+))?")
PAIR = re.compile(r'`([a-z_][a-z0-9_.]*)` "([^"]+)"')
STAMP = re.compile(r"RULED (BQ-\d\d)")
MARKER = re.compile(r"(\S+) <!-- audit:([a-z0-9\-_.]+)=([^ ]+) -->")
RULED_PIN_HEADER = (
    "# E08-D12 pins: KEY|line|words that stand on that line at origin/main (the tool's G11-CITE).\n"
    "# Written by `--repin-ruled` only; `--check` reads it (never hand-edit).\n"
)


def _load(path: Path, name: str) -> ModuleType:
    spec = importlib.util.spec_from_file_location(name, path)
    if spec is None or spec.loader is None:
        raise SystemExit(f"cannot load {path}")
    mod = importlib.util.module_from_spec(spec)
    sys.modules[name] = mod
    spec.loader.exec_module(mod)
    return mod


E11: Any = _load(TOOLS / "e11_d07_a11y_review_audit.py", "e11_d07_a11y_review_audit")
D05T: Any = _load(TOOLS / "e08_d05_search_audit.py", "e08_d05_search_audit")
D08T: Any = _load(TOOLS / "e08_d08_scanner_audit.py", "e08_d08_scanner_audit")
CONTRAST: Any = _load(TOOLS / "contrast_check.py", "contrast_check")
CVD: Any = _load(ROOT / "docs" / "research" / "_tools" / "cvd_simulate.py", "cvd_simulate")
# `cvd_simulate.py` is the one engine of record for every projection, whether or not NumPy and
# Pillow import (D-6); `cvd_sim.py` is not used, so `--check` is the same under every interpreter.


# --- sources -------------------------------------------------------------------------------------
@functools.cache
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


def git_diff_names(rel: str) -> str:
    out = subprocess.run(
        ["git", "-C", str(ROOT), "diff", "--unified=0", HEAD, "--", rel],
        capture_output=True,
        check=False,
    )
    return out.stdout.decode("utf-8")


def norm(text: str) -> str:
    return re.sub(r"\s+", " ", text.replace("\\|", "|")).strip()


class Ctx(NamedTuple):
    spec: str
    tool: str
    pins: str
    base: dict[str, str]
    bq_base: dict[str, str]
    images: tuple[str, ...]
    work14: str


class Result:
    def __init__(self) -> None:
        self.fails: list[str] = []
        self.warns: list[str] = []
        self.numbers: dict[str, object] = {}

    def fail(self, code: str, msg: str) -> None:
        self.fails.append(f"[{code}] {msg}")

    def warn(self, code: str, msg: str) -> None:
        self.warns.append(f"[{code}] {msg}")


def source_lines(ctx: Ctx, key: str) -> list[str]:
    """The cited file at the base, 1-based; `14` without this PR's own pointer lines, so the
    numbers hold before and after the merge."""
    lines = ctx.base.get(key, "").split("\n")
    if key == "14":
        lines = [ln for ln in lines if POINTER_MARK not in ln]
    return [""] + lines


def load_ctx() -> Ctx:
    p14 = ROOT / KEYS["14"]
    return Ctx(
        spec=SPEC.read_text(encoding="utf-8"),
        tool=Path(__file__).read_text(encoding="utf-8"),
        pins=PINS.read_text(encoding="utf-8") if PINS.exists() else "",
        base={k: git_show(HEAD, v) for k, v in KEYS.items()},
        bq_base={k: git_show(BQ_BASE, v) for k, v in KEYS.items()},
        images=tuple(Path(p).name for p in git_ls(HEAD, IMG_DIR)),
        work14=p14.read_text(encoding="utf-8") if p14.exists() else "",
    )


# --- markdown helpers -----------------------------------------------------------------------------
def section(text: str, head: str) -> str:
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


def ticks(cell: str) -> list[str]:
    return re.findall(r"`([^`]+)`", cell)


def marker(spec: str, name: str) -> str:
    m = re.search(rf"<!-- audit:{re.escape(name)}=([^ ]+) -->", spec)
    return m.group(1) if m else ""


def cites(spec: str) -> list[tuple[str, int, int]]:
    return [(k, int(a), int(b or a)) for k, a, b in CITE.findall(spec)]


def endpoints(spec: str) -> set[tuple[str, int]]:
    return {e for k, a, b in cites(spec) for e in ((k, a), (k, b))}


def row_sources(row: list[str], ctx: Ctx) -> list[str]:
    keys = {k for k, _, _ in CITE.findall(" ".join(row))}
    return [ctx.base[k] for k in keys if k in ctx.base] or [ctx.base[k] for k in DECKS]


def row_source_lines(row: list[str], ctx: Ctx) -> str:
    """The text of every line the row cites (ranges expanded)."""
    out = []
    for k, a, b in CITE.findall(" ".join(row)):
        lines = source_lines(ctx, k)
        for n in range(int(a), int(b or a) + 1):
            if n < len(lines):
                out.append(lines[n])
    return norm(" ".join(out))


def quoted_in(strings: list[str], texts: list[str]) -> list[str]:
    hay = norm(" ".join(texts))
    bad = []
    for q in strings:
        if len(q) < 8 or "…" in q or "{" in q or q.startswith("("):
            continue
        if norm(q) not in hay:
            bad.append(q)
    return bad


def severities(spec: str) -> dict[str, str]:
    return {fid: row[1] for fid, row in by_id(section(spec, "11. Findings"), "F").items()}


# --- G1 ------------------------------------------------------------------------------------------
def image_parent(name: str) -> str:
    low = name.lower()
    if low.startswith("e08-d07"):
        return "D07"
    if low.startswith("e08-d08"):
        return "D08"
    if low.startswith("e08-d11"):
        return "D11"
    if low.startswith("e08-d04"):
        return "D04"
    if low.startswith(("scr-041", "scr-102", "cmp-", "f-search")):
        return "D05"
    if low.startswith("scr-152") and ("owner" in low or "viewer" in low):
        return "D03"
    return "D02"


def gate_inventory(ctx: Ctx, r: Result) -> None:
    table = rows(section(ctx.spec, "2. Inventory"))
    items = {row[0].split(" ")[0]: row for row in table}
    for s in SURFACES_REVIEWED:
        row = items.get(s)
        if not row or not row[2].startswith("reviewed at hi-fi"):
            r.fail("G1-INVENTORY", f"{s}: not listed as reviewed at hi-fi")
    for s, owner in SURFACES_OUT.items():
        row = items.get(s)
        if not row or f"out of scope — {owner}" not in row[2]:
            r.fail("G1-INVENTORY", f"{s}: not out of scope to {owner}")
    for row in table:
        if row[1] == "component" and not row[2]:
            r.fail("G1-INVENTORY", f"{row[0]!r}: a component without a verdict")
    n = len(ctx.images)
    if not n:
        r.fail("G1-INVENTORY", "no images readable at the base")
    for name in ("images", "inventory-images"):
        if marker(ctx.spec, name) != str(n):
            r.fail(
                "G1-INVENTORY", f"marker {name} says {marker(ctx.spec, name)!r}, the base has {n}"
            )
    per = "/".join(str(sum(image_parent(i) == p for i in ctx.images)) for p in IMAGE_PARENTS)
    if marker(ctx.spec, "images-by-parent") != per:
        r.fail("G1-INVENTORY", f"images by parent {per} against the marker")
    r.numbers["surfaces"] = sum(row[1] == "surface" for row in table)
    r.numbers["components"] = sum(row[1] == "component" for row in table)
    r.numbers["images"] = n
    r.numbers["images_by_parent"] = per


# --- G2 ------------------------------------------------------------------------------------------
def gate_keys(ctx: Ctx, r: Result) -> None:
    body = section(ctx.spec, "3.1 One table")
    kb = by_id(body, "KB")
    if len(kb) < 28:
        r.fail("G2-KEYS", f"section 3.1 has {len(kb)} KB rows (28 expected)")
    km = {c["id"]: c for c in E11.load_keymap()["commands"]}
    reserved = E11.load_reserved()
    shipped_ids: list[str] = []
    for kid, row in kb.items():
        scope, status, resolution, source = row[3], row[4], row[6], row[7]
        if scope not in SCOPES:
            r.fail("G2-KEYS", f"{kid}: scope {scope!r} is not one of the vocabulary")
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
            want = {E11.nrm(k) for i in ids for k in E11.expand_keys(km[i]["defaultBinding"])}
            got = {E11.nrm(k) for raw in keys for k in E11.expand_keys(raw.replace(" / ", "/"))}
            if keys and not got <= want:
                r.fail(
                    "G2-KEYS", f"{kid}: the spec binds {sorted(got)}, the key map {sorted(want)}"
                )
            if any(k in reserved for k in want) and not all(
                km[i].get("reservedOverride") for i in ids
            ):
                r.fail("G2-KEYS", f"{kid}: a reserved key without a `reservedOverride`")
    allb = E11.shipped_bindings(E11.load_keymap())
    mine = [b for b in allb if b["id"] in shipped_ids]
    undeclared = 0
    for b in mine:
        for o in allb:
            same = o["key"] == b["key"] and o["id"] != b["id"]
            if same and E11.coactive(o["context"], b["context"]):
                undeclared += o["id"] not in b["shadows"] and b["id"] not in o["shadows"]
    rk = ctx.base.get("KM") and json.loads(git_show(HEAD, "apps/web/src/keymap/reserved-keys.json"))
    checks = {
        "km-commands": str(len(km)),
        "rk-entries": str(len(rk) if rk else 0),
        "kb-undeclared": str(undeclared),
        "kb": str(len(kb)),
    }
    for name, want_s in checks.items():
        if marker(ctx.spec, name) != want_s:
            r.fail(
                "G2-KEYS",
                f"marker {name}: the spec says {marker(ctx.spec, name)!r}, the engine {want_s}",
            )
    ks = by_id(section(ctx.spec, "14. The keyboard-only"), "KS")
    if len(ks) < 8:
        r.fail("G2-KEYS", f"section 14 has {len(ks)} KS steps (8 expected)")
    for sid, row in ks.items():
        if not ticks(row[2]) and "no key" not in row[2]:
            r.fail("G2-KEYS", f"{sid}: the step names no key")
    if marker(ctx.spec, "ks") != str(len(ks)):
        r.fail("G2-KEYS", f"marker ks says {marker(ctx.spec, 'ks')!r}, the table {len(ks)}")
    r.numbers["kb_rows"] = len(kb)
    r.numbers["kb_shipped_commands"] = sorted(set(shipped_ids))
    r.numbers.update({k: int(v) for k, v in checks.items()})
    r.numbers["ks_steps"] = len(ks)


# --- G3 ------------------------------------------------------------------------------------------
def gate_focus(ctx: Ctx, r: Result) -> None:
    fm = by_id(section(ctx.spec, "4. The focus model"), "FM")
    want = [f"FM-{i:02d}" for i in range(1, 25)]
    missing = [w for w in want if w not in fm]
    if missing:
        r.fail("G3-FOCUS", f"FM rows missing: {missing}")
    for fid, row in fm.items():
        dest, source, proof = row[3], row[5], row[6]
        if not dest or re.search(r"\bbody\b", dest):
            r.fail("G3-FOCUS", f"{fid}: no destination, or the body")
        if not CITE.search(source):
            r.fail("G3-FOCUS", f"{fid}: no source cite")
        if not proof:
            r.fail("G3-FOCUS", f"{fid}: no proof")
    for fid, row in by_id(section(ctx.spec, "11. Findings"), "F").items():
        if not FOCUS_RE.match(row[7]):
            r.fail("G3-FOCUS", f"{fid}: the Focus cell {row[7][:30]!r} is not from the vocabulary")
    if marker(ctx.spec, "fm") != str(len(fm)):
        r.fail("G3-FOCUS", f"marker fm says {marker(ctx.spec, 'fm')!r}, the table {len(fm)}")
    r.numbers["fm_rows"] = len(fm)


# --- G4 ------------------------------------------------------------------------------------------
def gate_regions(ctx: Ctx, r: Result) -> None:
    body = section(ctx.spec, "5.1 The map")
    rg = by_id(body, "RG")
    if len(rg) < 12:
        r.fail("G4-REGIONS", f"section 5.1 has {len(rg)} RG rows (12 expected)")
    for rid, row in rg.items():
        if not row[2] or not CITE.search(row[5]):
            r.fail("G4-REGIONS", f"{rid}: no role or no source")
    vocab = section(ctx.spec, "5.2 The confidence vocabulary")
    if "**Every non-`live` state has a mandatory text label**" not in vocab:
        r.fail("G4-REGIONS", "section 5.2 does not state the vocabulary's mandatory-label rule")
    if "no environment word" not in vocab:
        r.fail("G4-REGIONS", "section 5.2 does not state the naming rule's reading")
    if marker(ctx.spec, "rg") != str(len(rg)):
        r.fail("G4-REGIONS", f"marker rg says {marker(ctx.spec, 'rg')!r}, the table {len(rg)}")
    r.numbers["rg_rows"] = len(rg)


# --- G5 ------------------------------------------------------------------------------------------
def gate_script(ctx: Ctx, r: Result) -> None:
    body = section(ctx.spec, "6.1 The script table")
    sr = by_id(body, "SR")
    if len(sr) < 40:
        r.fail("G5-SCRIPT", f"section 6.1 has {len(sr)} SR rows (40 expected)")
    for sid, row in sr.items():
        string, pol, host, queue = row[2], row[3], row[4], row[5]
        if not any(pol.startswith(p) for p in POLITENESS):
            r.fail("G5-SCRIPT", f"{sid}: politeness {pol!r} is not from the vocabulary")
        if pol in ("polite", "assertive") and (not host or queue in ("", "—")):
            r.fail("G5-SCRIPT", f"{sid}: a live row without a host or a queueing rule")
        bad = quoted_in(QUOTED.findall(string), row_sources(row, ctx))
        if bad:
            r.fail("G5-SCRIPT", f"{sid}: not verbatim in a cited file: {bad[:2]}")
    if marker(ctx.spec, "sr") != str(len(sr)):
        r.fail("G5-SCRIPT", f"marker sr says {marker(ctx.spec, 'sr')!r}, the table {len(sr)}")
    s13 = section(ctx.spec, "13. The screen-reader script")
    blocks = s13.count("```gherkin")
    if blocks < 4:
        r.fail("G5-SCRIPT", f"section 13 has {blocks} Gherkin blocks (4 expected)")
    if NO_RUN not in s13:
        r.fail("G5-SCRIPT", "section 13 does not state that nothing was run")
    rendering = rows(section(ctx.spec, "13.1 Expected rendering"))
    if len(rendering) < 10:
        r.fail("G5-SCRIPT", f"section 13.1 has {len(rendering)} rows (10 expected)")
    r.numbers["sr_rows"] = len(sr)
    r.numbers["gherkin_blocks"] = blocks
    r.numbers["rendering_rows"] = len(rendering)


# --- G6 ------------------------------------------------------------------------------------------
def gate_budget(ctx: Ctx, r: Result) -> None:
    body = section(ctx.spec, "7. The announcement budget")
    bg = by_id(body, "BG")
    missing = [f"BG-{i:02d}" for i in range(1, 15) if f"BG-{i:02d}" not in bg]
    if missing:
        r.fail("G6-BUDGET", f"BG rows missing: {missing}")
    for bid, row in bg.items():
        if row[4] not in OBJECTS:
            r.fail("G6-BUDGET", f"{bid}: object {row[4]!r} is not one of {OBJECTS}")
        if not CITE.search(row[5]):
            r.fail("G6-BUDGET", f"{bid}: no source cite")
        if row[3].strip() == "n/a" or not RATE_RE.match(row[3].strip()):
            r.fail(
                "G6-BUDGET", f"{bid}: max_rate {row[3].strip()[:30]!r} is not an enforceable rate"
            )
    rule = bg.get("BG-11", ["", "", ""])[2]
    if COALESCE_RULE not in rule or "never swallows an assertive row" not in rule:
        r.fail("G6-BUDGET", "BG-11 does not state R369 BQ-13's rule")
    m = re.search(r"\(((?:SR-\d\d(?:, )?)+) coalesce to the latest\)", rule)
    coalesced = re.findall(r"SR-\d\d", m.group(1)) if m else []
    if not coalesced:
        r.fail("G6-BUDGET", "BG-11 names no coalescing SR rows")
    sr = by_id(section(ctx.spec, "6.1 The script table"), "SR")
    swallowed = [s for s in coalesced if s in sr and sr[s][3].startswith("assertive")]
    if swallowed:
        r.fail("G6-BUDGET", f"BG-11 coalesces assertive rows {swallowed}")
    if "**AC2's numbers per surface:**" not in body:
        r.fail("G6-BUDGET", "section 7 does not state AC2's numbers per surface")
    if marker(ctx.spec, "bg") != str(len(bg)):
        r.fail("G6-BUDGET", f"marker bg says {marker(ctx.spec, 'bg')!r}, the table {len(bg)}")
    r.numbers["bg_rows"] = len(bg)
    r.numbers["bg_coalesced"] = coalesced


# --- G7 ------------------------------------------------------------------------------------------
def gate_t2(ctx: Ctx, r: Result) -> None:
    body = section(ctx.spec, "8.1 The T2 table")
    t2 = by_id(body, "T2")
    if len(t2) < 18:
        r.fail("G7-T2", f"section 8.1 has {len(t2)} T2 rows (18 expected)")
    decks = norm(" ".join(ctx.base[k] for k in DECKS))
    for tid, row in t2.items():
        cls, rendering, focus, rate, checks = row[4], row[5], row[6], row[7], row[8]
        if cls not in CLASSES:
            r.fail("G7-T2", f"{tid}: class {cls!r} is not one of {CLASSES}")
        if cls == "T2":
            if not re.search(r"2a|2b|sentence|one notice|inline", rendering):
                r.fail("G7-T2", f"{tid}: a T2 row without a rendering")
            if "1a–d" not in checks:
                r.fail("G7-T2", f"{tid}: a T2 row without the 1a–d checks")
            if any(tok in " ".join(row) for tok in DISABLED_TOKENS):
                r.fail("G7-T2", f"{tid}: a disabled token on a T2 row")
        if not focus or not rate:
            r.fail("G7-T2", f"{tid}: no Focus or Rate cell")
        for key, string in PAIR.findall(row[3]):
            if norm(string) not in decks:
                r.fail("G7-T2", f"{tid}: `{key}` {string!r} stands in no parent")
    sd = by_id(section(ctx.spec, "8.2 The safety disclosures"), "SD")
    if len(sd) < 6:
        r.fail("G7-T2", f"section 8.2 has {len(sd)} SD rows (6 expected)")
    for sid, row in sd.items():
        if not VERDICT_RE.match(row[3]):
            r.fail("G7-T2", f"{sid}: verdict {row[3]!r} is not from R-3")
    if marker(ctx.spec, "t2") != str(len(t2)):
        r.fail("G7-T2", f"marker t2 says {marker(ctx.spec, 't2')!r}, the table {len(t2)}")
    r.numbers["t2_rows"] = len(t2)
    r.numbers["t2_gated"] = sum(row[4] == "T2" for row in t2.values())
    r.numbers["sd_rows"] = len(sd)


# --- G8 ------------------------------------------------------------------------------------------
def gate_verdict(ctx: Ctx, r: Result) -> None:
    sev = severities(ctx.spec)
    for head in ("10.1 `05` clauses", "10.2 WCAG 2.2 cross-walk"):
        for row in rows(section(ctx.spec, head)):
            verdict, ref = row[1], row[3]
            if not VERDICT_RE.match(verdict):
                r.fail("G8-VERDICT", f"{row[0][:40]!r}: verdict {verdict!r} is not from R-3")
            fids = re.findall(r"F-\d\d", ref)
            graded = any(sev.get(f) in ("Major", "Blocking", "Minor") for f in fids)
            if verdict.startswith("at risk") and not (graded or "interim path" in verdict):
                r.fail("G8-VERDICT", f"{row[0][:40]!r}: at risk with no F row and no interim path")
            if verdict.startswith("non-compliant") and not any(
                sev.get(f) == "Blocking" for f in fids
            ):
                r.fail("G8-VERDICT", f"{row[0][:40]!r}: non-compliant without a Blocking F row")
    matrix = rows(section(ctx.spec, "10.1b The per-surface checklist"))
    for row in matrix:
        for cell in row[1:]:
            if not VERDICT_RE.match(cell):
                r.fail("G8-VERDICT", f"10.1b {row[0][:30]!r}: cell {cell[:30]!r} is not from R-3")
            if cell.startswith("at risk") and not re.search(r"F-\d\d", cell):
                r.fail("G8-VERDICT", f"10.1b {row[0][:30]!r}: at risk names no F row")
    clauses = len(rows(section(ctx.spec, "10.1 `05` clauses")))
    if marker(ctx.spec, "clauses") != str(clauses):
        r.fail(
            "G8-VERDICT",
            f"marker clauses says {marker(ctx.spec, 'clauses')!r}, the table {clauses}",
        )
    if marker(ctx.spec, "checklist-items") != str(len(matrix)):
        r.fail("G8-VERDICT", f"marker checklist-items against {len(matrix)} rows")
    r.numbers["clauses"] = clauses
    r.numbers["criteria"] = len(rows(section(ctx.spec, "10.2 WCAG 2.2 cross-walk")))
    r.numbers["checklist_items"] = len(matrix)


# --- G9 ------------------------------------------------------------------------------------------
def defined_ids(spec: str) -> set[str]:
    out: set[str] = set()
    for head, kind in (
        ("3.1 One table", "KB"),
        ("3.2 The pointer-parity table", "PP"),
        ("4. The focus model", "FM"),
        ("5.1 The map", "RG"),
        ("6.1 The script table", "SR"),
        ("7. The announcement budget", "BG"),
        ("8.1 The T2 table", "T2"),
        ("8.2 The safety disclosures", "SD"),
        ("10.4 Colour never", "CR"),
        ("11. Findings", "F"),
        ("12.2 Gaps", "G"),
        ("12.3 Open questions", "Q"),
        ("12.4 Copy-ready", "A"),
        ("14. The keyboard-only", "KS"),
    ):
        out.update(by_id(section(spec, head), kind))
    out.update(by_id(section(spec, "12.1 Contradictions"), "C"))
    out.update(re.findall(r"\*\*(HR-\d)\*\*", section(spec, "12.5 Heuristic")))
    return out


def gate_findings(ctx: Ctx, r: Result) -> None:
    body = section(ctx.spec, "11. Findings")
    f = by_id(body, "F")
    counts = [len(f)] + [sum(row[1] == s for row in f.values()) for s in SEVERITIES]
    want = "/".join(map(str, counts))
    if marker(ctx.spec, "f") != want:
        r.fail("G9-FINDINGS", f"the marker says {marker(ctx.spec, 'f')!r}, the table {want}")
    head = re.search(
        r"## 11\. Findings — F (\d+) \(Blocking (\d+) · Major (\d+) · Minor (\d+) · Info (\d+)\)",
        ctx.spec,
    )
    if not head or [int(x) for x in head.groups()] != counts:
        r.fail("G9-FINDINGS", f"the heading does not read the counts {counts}")
    for fid, row in f.items():
        sev, owner, target, gt2, focus, rate = row[1], row[4], row[5], row[6], row[7], row[8]
        if sev not in SEVERITIES:
            r.fail("G9-FINDINGS", f"{fid}: severity {sev!r}")
        if not OWNER_RE.match(owner) or PERSON_RE.search(owner):
            r.fail("G9-FINDINGS", f"{fid}: owner {owner!r} is not a spec and an area")
        if TARGET not in target:
            r.fail("G9-FINDINGS", f"{fid}: target lacks {TARGET}")
        if sev != "Info" and not CONSUMER_RE.search(target):
            r.fail("G9-FINDINGS", f"{fid}: a graded row without a consuming story or E08-Q05")
        if not gt2 or not focus or not rate:
            r.fail("G9-FINDINGS", f"{fid}: the G-T2, Focus or Rate cell is empty")
    blocking = [fid for fid, row in f.items() if row[1] == "Blocking"]
    if blocking and HOLD not in body:
        r.fail("G9-FINDINGS", "a Blocking row stands and the hold sentence is missing")
    if not blocking and ("hold of R-2 is **not armed**" not in body or HOLD in body):
        r.fail("G9-FINDINGS", "no Blocking row stands and the not-armed sentence is missing")
    defined = defined_ids(ctx.spec)
    used = {f"{k}-{n}" for k, n in ID_RE.findall(ctx.spec)}
    used |= {f"C-{c}" for c in C_ID_RE.findall(ctx.spec)}
    dangling = sorted(u for u in used if u not in defined)
    if dangling:
        r.fail("G9-FINDINGS", f"ids used and defined nowhere: {dangling[:8]}")
    c_rows = by_id(section(ctx.spec, "12.1 Contradictions"), "C")
    g_rows = by_id(section(ctx.spec, "12.2 Gaps"), "G")
    q_rows = by_id(section(ctx.spec, "12.3 Open questions"), "Q")
    a_rows = by_id(section(ctx.spec, "12.4 Copy-ready"), "A")
    h_rows = re.findall(r"\*\*(HR-\d)\*\*", section(ctx.spec, "12.5 Heuristic"))
    for name, n in (
        ("c", len(c_rows)),
        ("g", len(g_rows)),
        ("q", len(q_rows)),
        ("a", len(a_rows)),
        ("hr", len(h_rows)),
    ):
        if marker(ctx.spec, name) != str(n):
            r.fail("G9-FINDINGS", f"marker {name} says {marker(ctx.spec, name)!r}, the rows {n}")
    line = (
        f"F {counts[0]} (Blocking {counts[1]} · Major {counts[2]} · Minor {counts[3]} · Info {counts[4]}); "
        f"C {len(c_rows)} · G {len(g_rows)} · Q {len(q_rows)} · A {len(a_rows)} · HR {len(h_rows)}"
    )
    if line not in section(ctx.spec, "16. Summary"):
        r.fail("G9-FINDINGS", f"section 16 does not read {line!r}")
    r.numbers["findings"] = want
    r.numbers["blocking"] = blocking
    r.numbers["rows"] = {
        "C": len(c_rows),
        "G": len(g_rows),
        "Q": len(q_rows),
        "A": len(a_rows),
        "HR": len(h_rows),
    }


# --- G10 -----------------------------------------------------------------------------------------
def gate_ruled(ctx: Ctx, r: Result) -> None:
    body = section(ctx.spec, "R. Rulings applied")
    table = {row[0]: row for row in rows(body) if row[0].startswith("BQ-")}
    missing = [b for b in BQ_IDS if b not in table]
    extra = sorted(set(table) - set(BQ_IDS))
    if missing or extra:
        r.fail("G10-RULED", f"the rulings table: missing {missing}, extra {extra}")
    for bq, row in table.items():
        if not row[1] or not row[2]:
            r.fail("G10-RULED", f"{bq}: no default or no section")
        if row[3] != RULED_STAMP and not row[3].startswith("pending"):
            r.fail("G10-RULED", f"{bq}: status {row[3][:40]!r} is not the ruling stamp")
    stamps = set(STAMP.findall(ctx.spec))
    bad = sorted(s for s in stamps if s not in table)
    if bad:
        r.fail("G10-RULED", f"stamps pointing at no table row: {bad}")
    pending = any(row[3].startswith("pending") for row in table.values())
    if pending != (PENDING_LINE in ctx.spec):
        r.fail("G10-RULED", "the PENDING line and the table's statuses disagree")
    r.numbers["bq_rows"] = len(table)
    r.numbers["stamps"] = len(stamps)


# --- G11 -----------------------------------------------------------------------------------------
def parse_pins(text: str) -> dict[tuple[str, int], str]:
    out: dict[tuple[str, int], str] = {}
    for ln in text.splitlines():
        if ln.strip() and not ln.startswith("#"):
            key, line, words = ln.split("|", 2)
            out[(key, int(line))] = words
    return out


def gate_cite(ctx: Ctx, r: Result) -> None:
    found = cites(ctx.spec)
    for key, a, b in found:
        if key not in KEYS:
            r.fail("G11-CITE", f"`{key}`:{a}: an undeclared key")
            continue
        lines = source_lines(ctx, key)
        if not (0 < a <= b < len(lines)) or not lines[a].strip() or not lines[b].strip():
            r.fail("G11-CITE", f"`{key}`:{a}-{b}: out of range or blank at the base")
    pins = parse_pins(ctx.pins)
    if not pins:
        r.fail("G11-CITE", "no pins (run --repin-ruled deliberately)")
    for (key, n), words in pins.items():
        lines = source_lines(ctx, key) if key in KEYS else [""]
        line = lines[n] if 0 < n < len(lines) else ""
        if not words.strip() or not norm(line).startswith(norm(words)):
            r.fail("G11-CITE", f"pin {key}:{n}: {words[:40]!r} is not on that line at the base")
    ends = {e for e in endpoints(ctx.spec) if e[0] in KEYS}
    uncited, unpinned = sorted(set(pins) - ends), sorted(ends - set(pins))
    if uncited or unpinned:
        r.fail(
            "G11-CITE", f"pins and cites disagree: uncited {uncited[:4]}; unpinned {unpinned[:4]}"
        )
    used = {k for k, _, _ in found}
    moved = sorted(k for k in used if k in KEYS and ctx.bq_base.get(k) != ctx.base.get(k))
    if set(moved) - MOVED:
        r.fail("G11-CITE", f"cited files changed between the bases beyond {sorted(MOVED)}: {moved}")
    r.numbers["cites"] = len(found)
    r.numbers["endpoints"] = len(ends)
    r.numbers["pins"] = len(pins)
    r.numbers["moved_files"] = moved


def repin(ctx: Ctx) -> int:
    lines = [RULED_PIN_HEADER.rstrip("\n")]
    count = 0
    for key, n in sorted(endpoints(ctx.spec)):
        if key not in KEYS:
            continue
        src = source_lines(ctx, key)
        if 0 < n < len(src) and src[n].strip():
            lines.append(f"{key}|{n}|{norm(src[n])[:70]}")
            count += 1
    PINS.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return count


# --- G12 -----------------------------------------------------------------------------------------
def hx(token: str, th: str) -> str | None:
    try:
        v = D05T.col(th, token)
    except KeyError:
        return None
    return v if isinstance(v, str) and re.fullmatch(r"#[0-9A-Fa-f]{6}", v) else None


def rgb(h: str) -> tuple[int, int, int]:
    return (int(h[1:3], 16), int(h[3:5], 16), int(h[5:7], 16))


def ratio(a: str, b: str) -> float:
    return float(CONTRAST.contrast_ratio(rgb(a), rgb(b)))


def grey(h: str) -> str:
    rr, gg, bb = rgb(h)  # Rec. 601 weights: cvd_sim.to_greyscale needs NumPy at import (D-6)
    y = round(0.299 * rr + 0.587 * gg + 0.114 * bb)
    return f"#{y:02x}{y:02x}{y:02x}"


def sim(h: str, kind: str) -> str:
    return str(CVD.simulate(h, kind))


def lstar(h: str) -> float:
    return float(CVD.xyz_to_lab(CVD.srgb_to_xyz(h))[0])


def full(token: str) -> str:
    """A D07 table token: `.stale.text` → `color.data-confidence.stale.text`; `raised` → the surface."""
    t = token.strip("`")
    if t.startswith("."):
        return "color.data-confidence" + t
    if t in BG_SURFACES:
        return "color.surface." + t
    return t


def d07_pairs(ctx: Ctx) -> tuple[list[tuple[str, str, str, bool]], int]:
    """E08-D07 §7.2's rows, read from the merged table; a row D07 marks ✗ is reported, not gated."""
    out: list[tuple[str, str, str, bool]] = []
    skipped = 0
    for row in rows(section(ctx.base["D07"], "7.2 Computed contrast")):
        if len(row) < 8 or not re.fullmatch(r"\d+", row[0]):
            continue
        fg_tokens = [full(t) for t in ticks(row[2])]
        bg_tokens = [full(t) for t in re.split(r"\s*[/;]\s*", row[3].replace("`", ""))]
        if len(fg_tokens) != 1 or "at" in row[2] or row[7] == "—":
            skipped += 1
            continue
        role = "text" if row[7] == "4.5" else "non-text"
        gated = "✗" not in " ".join(row)
        for bg in bg_tokens:
            if not bg.startswith("color."):
                skipped += 1
                continue
            out.append((fg_tokens[0], bg, role, gated))
    return out, skipped


D03_PAIRS = (
    ("color.text.on-action", "color.action.primary.default", "non-text", True),
    ("color.action.primary.default", "color.status.danger.subtle", "non-text", True),
    ("color.status.danger.strong", "color.status.danger.subtle", "non-text", True),
)


def union_pairs(ctx: Ctx) -> tuple[list[tuple[str, str, str, bool]], int]:
    out: list[tuple[str, str, str, bool]] = []
    skipped = 0
    for _, fg, bg, role in D05T.PAIRS:
        bar = D05T.BAR.get(role)
        if role.startswith("rejected") or bar is None:
            skipped += 1
            continue
        out.append(
            (fg, bg, "text" if role.startswith("text") or role == "hc-text" else "non-text", True)
        )
    for fg, bg, role in D08T.PAIRS.values():
        out.append((f"color.{fg}", f"color.{bg}", "text" if role == "text" else "non-text", True))
    d07, sk = d07_pairs(ctx)
    out += d07
    skipped += sk
    out += list(D03_PAIRS)
    return out, skipped


def union_line(ctx: Ctx) -> tuple[str, dict[str, object]]:
    pairs, skipped = union_pairs(ctx)
    n = fail = reported = 0
    under7: list[str] = []
    minima = {"text": 99.0, "non-text": 99.0, "hc-text": 99.0}
    for fg, bg, role, gated in pairs:
        cols = [(hx(fg, th), hx(bg, th), th) for th in D05T.THEMES]
        if any(c[0] is None or c[1] is None for c in cols):
            skipped += 1
            continue
        n += 1
        if not gated:
            reported += 1
            continue
        for f_hex, b_hex, th in cols:
            v = ratio(f_hex, b_hex)
            key = "hc-text" if (role == "text" and th == "high-contrast") else role
            minima[key] = min(minima[key], v)
            if v < BARS["text" if key == "hc-text" else key]:
                fail += 1
            if key == "hc-text" and v < BARS["hc-text"]:
                under7.append(f"`{fg}` on `{bg}` ({v:.2f})")
    line = (
        f"**Union:** {n} token pairs · gated FAIL {fail} at 4.5 / 3 · gated minima text "
        f"{minima['text']:.2f}, non-text {minima['non-text']:.2f}, hc-text {minima['hc-text']:.2f} · "
        f"under the 7:1 AAA-leaning bar in high contrast: {len(under7)} "
        f"({'; '.join(under7) or 'none'}), reported · {reported + skipped} rows reported, not gated "
        f"(the parents' rejected or non-token rows) <!-- audit:contrast -->"
    )
    return line, {
        "union_pairs": n,
        "union_fail": fail,
        "union_under7": len(under7),
        "union_reported": reported + skipped,
        "minima": {k: round(v, 2) for k, v in minima.items()},
    }


def dscr1() -> str:
    vals = []
    for th in D05T.THEMES:
        a, b = hx("color.data-confidence.disconnected.text", th), hx(
            "color.data-confidence.live.text", th
        )
        vals.append(f"{float(CVD.delta_e76(a, b)):.1f}" if a and b else "n/a")
    return "/".join(vals)


CR_TOKENS: dict[str, tuple[list[str], list[str]]] = {
    "CR-01": (["color.data-confidence.stale.indicator"], ["color.surface.raised"]),
    "CR-02": (["color.buy.default"], ["color.sell.default"]),
    "CR-03": (
        ["color.data-confidence.delisted.indicator"],
        ["color.data-confidence.stale.indicator"],
    ),
    "CR-04": (["color.data-confidence.disconnected.indicator"], ["color.status.success.strong"]),
    "CR-05": (["color.status.info.default"], ["color.data-confidence.stale.indicator"]),
    "CR-06": (["color.border.selected"], ["color.focus.ring"]),
    "CR-07": (["color.status.warning.strong"], ["color.text.primary"]),
}


def carrier(a_tokens: list[str], b_tokens: list[str]) -> tuple[str, str]:
    dl = dee = 999.0
    for th in D05T.THEMES:
        for a in a_tokens:
            for b in b_tokens:
                ha, hb = hx(a, th), hx(b, th)
                if ha is None or hb is None or a == b:
                    continue
                dl = min(dl, abs(lstar(grey(ha)) - lstar(grey(hb))))
                for kind in SIMS:
                    dee = min(dee, float(CVD.delta_e76(sim(ha, kind), sim(hb, kind))))
    return f"{dl:.1f}", f"{dee:.1f}"


def gate_colour(ctx: Ctx, r: Result) -> None:
    line, nums = union_line(ctx)
    if line not in ctx.spec:
        r.fail("G12-COLOUR", f"section 10.3 does not read {line[:90]!r}…")
    if nums["union_fail"]:
        r.fail("G12-COLOUR", f"the contrast union has {nums['union_fail']} gated FAIL")
    r.numbers.update(nums)
    de = dscr1()
    if marker(ctx.spec, "dscr1") != de:
        r.fail(
            "G12-COLOUR", f"DS-CR-1 measures ΔE {de}, the marker says {marker(ctx.spec, 'dscr1')!r}"
        )
    cr = by_id(section(ctx.spec, "10.4 Colour never"), "CR")
    for cid, (a, b) in CR_TOKENS.items():
        dl, dee = carrier(a, b)
        row = cr.get(cid)
        if not row or row[4] != dl or row[5] != dee:
            r.fail(
                "G12-COLOUR",
                f"{cid}: measured {dl} / {dee}, the row says {row[4:6] if row else None}",
            )
        r.numbers[cid] = {"dL": dl, "dE76": dee}
    for cid, row in cr.items():
        if cid not in CR_TOKENS:
            r.fail("G12-COLOUR", f"{cid}: a family the tool does not measure")
        if "distinguishable by carrier" not in row[6]:
            r.fail("G12-COLOUR", f"{cid}: verdict is not 'distinguishable by carrier'")
    cvd = sum(("greyscale" in i or "deuteranopia" in i or "protanopia" in i) for i in ctx.images)
    if marker(ctx.spec, "cvd-images") != str(cvd):
        r.fail(
            "G12-COLOUR",
            f"the base holds {cvd} CVD renders, the marker says {marker(ctx.spec, 'cvd-images')!r}",
        )
    if marker(ctx.spec, "cr") != str(len(cr)):
        r.fail("G12-COLOUR", f"marker cr says {marker(ctx.spec, 'cr')!r}, the table {len(cr)}")
    r.numbers["dscr1"] = de
    r.numbers["cr_rows"] = len(cr)
    r.numbers["cvd_images"] = cvd
    r.numbers["cvd_engine"] = "cvd_simulate.py (the engine of record)"


# --- G13 -----------------------------------------------------------------------------------------
def gate_hygiene(ctx: Ctx, r: Result) -> None:
    for name, text in (("the spec", ctx.spec), ("the tool", ctx.tool), ("the pins", ctx.pins)):
        low = text.lower()
        for word in BANNED:
            if word.lower() in low:
                r.fail("G13-HYGIENE", f"{name}: a word from the lane-private list")
        for pat, what in (
            (HOST, "a host name"),
            (URL, "a URL"),
            (UUID, "an id in the uuid form"),
            (LOCAL_PATH, "a local path"),
            (ADVISORY_ID, "an advisory-style identifier"),
            (LOOPBACK, "a loopback host or a port"),
        ):
            m = pat.search(text)
            if m:
                r.fail("G13-HYGIENE", f"{name}: {what} {m.group(0)[:30]!r}")
        if name != "the tool" and PERSON_RE.search(text):
            m = PERSON_RE.search(text)
            r.fail("G13-HYGIENE", f"{name}: names a person, a lane or a role word {m.group(0)!r}")
    if CLOSING.search(ctx.spec):
        r.fail("G13-HYGIENE", "the spec carries a closing keyword before an issue number")
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
        r.fail("G13-HYGIENE", f"an example string with a fixture account: {bad[:2]}")


# --- G14 -----------------------------------------------------------------------------------------
def gate_unstated(ctx: Ctx, r: Result) -> None:
    if UNSTATED_CLAUSE not in section(ctx.spec, "1.4 Rules stated once"):
        r.fail("G14-UNSTATED", "R-1 does not state BQ-04's precise reading of 'unstated'")
    sev = severities(ctx.spec)
    proposed = 0
    for fid, row in by_id(section(ctx.spec, "4. The focus model"), "FM").items():
        dest = row[3]
        for f in PROPOSED_FM.findall(dest):
            proposed += 1
            removed = "else moves to" in dest or "removed element" in dest
            want = "Blocking" if removed else "Minor"
            if sev.get(f) != want:
                r.fail(
                    "G14-UNSTATED",
                    f"{fid}: the PROPOSED destination for {f} wants {want}, the F row is {sev.get(f)!r}",
                )
    for fid, row in by_id(section(ctx.spec, "11. Findings"), "F").items():
        focus_row = row[7] != "n/a" and row[1] != "Info"
        if focus_row and REMOVED_RE.search(row[2]) and row[1] != "Blocking":
            r.fail("G14-UNSTATED", f"{fid}: a removed element in the merged sentence, {row[1]}")
    r.numbers["fm_proposed"] = proposed


# --- G15 -----------------------------------------------------------------------------------------
def clause(head: str) -> tuple[str, frozenset[int] | None] | None:
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
        seen.add(number)
        listed = set(re.findall(r"F-\d\d", row[3])) & graded
        cs = citing.get(number, set())
        if row[1].startswith("compliant") and (listed or cs):
            r.fail(
                "G15-CRITERIA", f"{number}: compliant while {sorted(listed | cs)} stand against it"
            )
        elif cs - listed:
            r.fail("G15-CRITERIA", f"{number}: {sorted(cs - listed)} cite it and are not listed")
    for number in sorted(set(citing) - seen):
        r.fail("G15-CRITERIA", f"{sorted(citing[number])} cite WCAG {number}, which has no row")
    f_clauses: dict[str, set[tuple[str, int | None]]] = {}
    for fid in graded:
        for sec, item in CLAUSE_RE.findall(f_rows[fid][2]):
            f_clauses.setdefault(fid, set()).add((sec, int(item) if item else None))
    matched: set[str] = set()
    for row in rows(section(ctx.spec, "10.1 `05` clauses")):
        parsed = clause(row[0])
        label = row[0].split(" — ")[0]
        listed = set(re.findall(r"F-\d\d", row[3])) & graded
        cs = {
            fid
            for fid, c in f_clauses.items()
            if parsed is not None and any(clause_hit(x, parsed) for x in c)
        }
        matched |= cs
        if row[1].startswith("compliant") and (listed or cs):
            r.fail(
                "G15-CRITERIA",
                f"`05` {label}: compliant while {sorted(listed | cs)} stand against it",
            )
        elif cs - listed:
            r.fail(
                "G15-CRITERIA", f"`05` {label}: {sorted(cs - listed)} cite it and are not listed"
            )
    for fid in sorted(set(f_clauses) - matched):
        r.fail("G15-CRITERIA", f"{fid} cites a `05` clause with no section 10.1 row")
    r.numbers["criteria_cited"] = {k: sorted(v) for k, v in sorted(citing.items())}
    r.numbers["clauses_cited"] = {
        fid: sorted(f"{s} item {i}" if i else s for s, i in c)
        for fid, c in sorted(f_clauses.items())
    }


# --- G16 -----------------------------------------------------------------------------------------
def sr_ids(cell: str) -> set[str]:
    ids = {f"SR-{i:02d}" for a, b in SR_RANGE.findall(cell) for i in range(int(a), int(b) + 1)}
    ids.update(f"SR-{n}" for n in SR_ONE.findall(SR_RANGE.sub(" ", cell)))
    return ids


def gate_xref(ctx: Ctx, r: Result) -> None:
    sr = by_id(section(ctx.spec, "6.1 The script table"), "SR")
    checked = 0
    for fid, row in by_id(section(ctx.spec, "4. The focus model"), "FM").items():
        ids = sr_ids(row[4])
        if not ids:
            continue
        checked += 1
        missing = sorted(i for i in ids if i not in sr)
        if missing:
            r.fail("G16-XREF", f"{fid}: undefined {missing}")
    for kid, row in by_id(section(ctx.spec, "14. The keyboard-only"), "KS").items():
        missing = sorted(i for i in sr_ids(row[4]) if i not in sr)
        if missing:
            r.fail("G16-XREF", f"{kid}: undefined {missing}")
    used = sorted({f"SR-{n}" for n in SR_ANY.findall(ctx.spec)} - set(sr))
    if used:
        r.fail("G16-XREF", f"SR ids used and defined nowhere: {used[:6]}")
    r.numbers["fm_sr_xref"] = checked


# --- G17 -----------------------------------------------------------------------------------------
def gate_parity(ctx: Ctx, r: Result) -> None:
    body = section(ctx.spec, "3.2 The pointer-parity table")
    pp = by_id(body, "PP")
    if len(pp) < 10:
        r.fail("G17-PARITY", f"section 3.2 has {len(pp)} PP rows (10 expected)")
    for pid, row in pp.items():
        if not row[3] or POINTER_WORDS.search(row[3]):
            r.fail("G17-PARITY", f"{pid}: no keyboard path, or a pointer word")
        if not CITE.search(row[4]):
            r.fail("G17-PARITY", f"{pid}: no source cite")
    if "**Result: no Blocking AC3 row among the seven hi-fi surfaces**" not in body:
        r.fail("G17-PARITY", "section 3.2 does not state the AC3 result")
    if marker(ctx.spec, "pp") != str(len(pp)):
        r.fail("G17-PARITY", f"marker pp says {marker(ctx.spec, 'pp')!r}, the table {len(pp)}")
    r.numbers["pp_rows"] = len(pp)


# --- G18 -----------------------------------------------------------------------------------------
STRUCT_OK = re.compile(
    r"^(out of scope — E08-D(?:09 \(#177\)|10 \(#178\))|compliant \(structure|compliant \(the pattern|not yet decidable|n/a — )"
)


def gate_struct(ctx: Ctx, r: Result) -> None:
    matrix = rows(section(ctx.spec, "10.1b The per-surface checklist"))
    if not matrix:
        r.fail("G18-STRUCT", "no per-surface matrix")
    out_cells = 0
    for row in matrix:
        for col, owner in ((8, "E08-D09 (#177)"), (9, "E08-D10 (#178)")):
            cell = row[col] if len(row) > col else ""
            if not STRUCT_OK.match(cell):
                r.fail(
                    "G18-STRUCT",
                    f"10.1b {row[0][:30]!r} column {col}: {cell[:40]!r} is a hi-fi verdict",
                )
            if "approved" in cell:
                r.fail("G18-STRUCT", f"10.1b {row[0][:30]!r}: a structure-only cell reads approved")
            out_cells += cell.startswith("out of scope — " + owner)
    if out_cells < 12:
        r.fail("G18-STRUCT", f"only {out_cells} cells are out of scope to E08-D09 / E08-D10")
    for sid, owner in SURFACES_OUT.items():
        blk = section(ctx.spec, "2. Inventory")
        for row in rows(blk):
            if row[0].startswith(sid) and "approved" in " ".join(row):
                r.fail("G18-STRUCT", f"{sid}: the inventory row reads approved")
    r.numbers["struct_out_cells"] = out_cells


# --- G19 -----------------------------------------------------------------------------------------
def gate_dom(ctx: Ctx, r: Result) -> None:
    for fid, row in by_id(section(ctx.spec, "11. Findings"), "F").items():
        repl = row[3]
        if DOM_RE.search(repl) and "no extra" not in repl:
            r.fail("G19-DOM", f"{fid}: the replacement adds a DOM node per cell or row")
    if "No replacement adds a DOM node per cell (G19-DOM)" not in section(ctx.spec, "11. Findings"):
        r.fail("G19-DOM", "section 11 does not state the per-cell DOM gate")


# --- G20 -----------------------------------------------------------------------------------------
def gate_rate(ctx: Ctx, r: Result) -> None:
    numeric = 0
    tables = (
        ("6.1 The script table", "SR", 6),
        ("7. The announcement budget", "BG", 3),
        ("8.1 The T2 table", "T2", 7),
        ("11. Findings", "F", 8),
    )
    for head, kind, col in tables:
        for rid, row in by_id(section(ctx.spec, head), kind).items():
            cell = row[col] if len(row) > col else ""
            if not RATE_RE.match(cell):
                r.fail("G20-RATE", f"{rid}: rate {cell[:30]!r} is not from the vocabulary")
                continue
            m = RATE_NUM.search(cell)
            if m:
                numeric += 1
                n = m.group(1)
                src = row_source_lines(row, ctx)
                if not re.search(rf"(?<![\d.]){re.escape(n)}(?:<!--[^>]*-->)?\s?s\b", src):
                    r.fail("G20-RATE", f"{rid}: the number {n} s stands on no line the row cites")
    r.numbers["numeric_rates"] = numeric


# --- G21 -----------------------------------------------------------------------------------------
def gate_edit_set(ctx: Ctx, r: Result) -> None:
    diff = git_diff_names(KEYS["14"])
    added = [ln[1:] for ln in diff.splitlines() if ln.startswith("+") and not ln.startswith("+++")]
    removed = [ln for ln in diff.splitlines() if ln.startswith("-") and not ln.startswith("---")]
    if removed:
        r.fail("G21-EDIT-SET", f"`14` loses {len(removed)} line(s)")
    if len(added) != 9 or any(POINTER_MARK not in ln for ln in added):
        r.fail("G21-EDIT-SET", f"`14` gains {len(added)} line(s); nine pointer lines expected")
    if marker(ctx.spec, "pointer-lines") != "9":
        r.fail("G21-EDIT-SET", "the pointer-lines marker is not 9")
    work = ctx.work14.split("\n")
    heads = [(i, ln[4:11]) for i, ln in enumerate(work) if ln.startswith("### SCR-")]
    for sid in POINTER_ENTRIES:
        idx = [i for i, ln in enumerate(work) if POINTER_MARK in ln and "(E08-D12; " in ln]
        start = next((i for i, h in heads if h == sid), None)
        end = next((i for i, _ in heads if start is not None and i > start), len(work))
        inside = [i for i in idx if start is not None and start < i < end]
        if len(inside) != 1:
            r.fail("G21-EDIT-SET", f"{sid}: {len(inside)} pointer line(s) inside its entry")
        elif "[x]" in work[inside[0]] or "[ ]" in work[inside[0]]:
            r.fail("G21-EDIT-SET", f"{sid}: the pointer line carries a tick box")
    for key in UNTOUCHED:
        if git_diff_names(KEYS[key]).strip():
            r.fail("G21-EDIT-SET", f"{key} differs from the base")
    r.numbers["pointer_lines"] = len(added)


# --- G22 -----------------------------------------------------------------------------------------
def sprint_dates(ctx: Ctx) -> dict[str, str]:
    m = re.search(r"SPRINT01_START = datetime\.date\((\d+), (\d+), (\d+)\)", ctx.base["CAL"])
    d = re.search(r"SPRINT_DAYS = (\d+)", ctx.base["CAL"])
    if not m or not d:
        return {}
    start = datetime.date(int(m.group(1)), int(m.group(2)), int(m.group(3)))
    days = int(d.group(1))
    out = {}
    for k in range(1, 27):
        a = start + datetime.timedelta(days=days * (k - 1))
        out[f"sprint.s{k:02d}.start"] = a.isoformat()
        out[f"sprint.s{k:02d}.end"] = (a + datetime.timedelta(days=days - 1)).isoformat()
    return out


def gate_calendar(ctx: Ctx, r: Result) -> None:
    dates = sprint_dates(ctx)
    if not dates:
        r.fail("G22-CALENDAR", "cannot read the sprint calendar at the base")
    found = 0
    for _, name, value in MARKER.findall(ctx.spec):
        if name.startswith("sprint."):
            found += 1
            if dates.get(name) != value:
                r.fail(
                    "G22-CALENDAR", f"{name}: the spec says {value}, the calendar {dates.get(name)}"
                )
    if found < 6:
        r.fail("G22-CALENDAR", f"only {found} sprint markers")
    if "**reports and promises nothing**" not in section(ctx.spec, "15.5 The calendar"):
        r.fail("G22-CALENDAR", "section 15.5 does not say it reports and promises nothing")
    r.numbers["sprint_markers"] = found


# --- G23 -----------------------------------------------------------------------------------------
def gate_walk(ctx: Ctx, r: Result) -> None:
    body = section(ctx.spec, "15.3 Sign-off")
    if WALK_HEAD not in body:
        r.fail("G23-WALK", "the owner walkthrough is not headed post-Done (#2701)")
    items = re.findall(r"\((\d+)\) ", body)
    n = max((int(i) for i in items), default=0)
    if not items or n > 10 or sorted({int(i) for i in items}) != list(range(1, n + 1)):
        r.fail("G23-WALK", f"the walkthrough numbers {items[:12]} are not 1..n with n ≤ 10")
    if "`wcag2a`, `wcag2aa` and `wcag22aa`" not in body:
        r.fail("G23-WALK", "the axe tags are not the three named")
    for name in ("kb", "fm", "sr", "bg", "t2"):
        if marker(ctx.spec, f"{name}-summary") != marker(ctx.spec, name):
            r.fail("G23-WALK", f"the summary marker {name}-summary differs from {name}")
    r.numbers["walk_items"] = n


GATE_FNS: tuple[tuple[str, Callable[[Ctx, Result], None]], ...] = (
    ("G1-INVENTORY", gate_inventory),
    ("G2-KEYS", gate_keys),
    ("G3-FOCUS", gate_focus),
    ("G4-REGIONS", gate_regions),
    ("G5-SCRIPT", gate_script),
    ("G6-BUDGET", gate_budget),
    ("G7-T2", gate_t2),
    ("G8-VERDICT", gate_verdict),
    ("G9-FINDINGS", gate_findings),
    ("G10-RULED", gate_ruled),
    ("G11-CITE", gate_cite),
    ("G12-COLOUR", gate_colour),
    ("G13-HYGIENE", gate_hygiene),
    ("G14-UNSTATED", gate_unstated),
    ("G15-CRITERIA", gate_criteria),
    ("G16-XREF", gate_xref),
    ("G17-PARITY", gate_parity),
    ("G18-STRUCT", gate_struct),
    ("G19-DOM", gate_dom),
    ("G20-RATE", gate_rate),
    ("G21-EDIT-SET", gate_edit_set),
    ("G22-CALENDAR", gate_calendar),
    ("G23-WALK", gate_walk),
)


def run(ctx: Ctx) -> Result:
    r = Result()
    for _, fn in GATE_FNS:
        fn(ctx, r)
    return r


# --- fill ----------------------------------------------------------------------------------------
def fill(ctx: Ctx) -> int:
    changed = 0
    spec = ctx.spec
    line, _ = union_line(ctx)
    spec2 = re.sub(r"^\*\*Union:\*\* .*<!-- audit:contrast -->$", line, spec, flags=re.MULTILINE)
    changed += spec2 != spec
    spec = spec2
    de = dscr1()
    spec2 = re.sub(
        r"ΔE76 [0-9./an]+ <!-- audit:dscr1=[^ ]+ -->",
        f"ΔE76 {de.replace('/', ' / ')} <!-- audit:dscr1={de} -->",
        spec,
    )
    changed += spec2 != spec
    spec = spec2
    for cid, (a, b) in CR_TOKENS.items():
        dl, dee = carrier(a, b)
        pat = re.compile(rf"^(\| {cid} \|(?:[^|]*\|){{3}}) ([^|]*)\| ([^|]*)\|", re.MULTILINE)
        spec2 = pat.sub(
            lambda m, dl=dl, dee=dee: f"{m.group(1)} {dl:<9} | {dee:<8} |", spec, count=1
        )
        changed += spec2 != spec
        spec = spec2
    SPEC.write_text(spec, encoding="utf-8")
    return changed


# --- self-test -----------------------------------------------------------------------------------
Mut = Callable[[Ctx], Ctx]


def sub(old: str, new: str) -> Mut:
    return lambda c: c._replace(spec=c.spec.replace(old, new, 1))


def regex(pattern: str, repl: str) -> Mut:
    return lambda c: c._replace(spec=re.sub(pattern, repl, c.spec, count=1, flags=re.MULTILINE))


def pin_sub(pattern: str, repl: str) -> Mut:
    return lambda c: c._replace(pins=re.sub(pattern, repl, c.pins, count=1, flags=re.MULTILINE))


MUTATIONS: tuple[tuple[str, Mut], ...] = (
    (
        "G1-INVENTORY",
        regex(
            r"(\| SCR-103 Symbol info drawer\s+\| surface\s+\| )reviewed at hi-fi",
            r"\1pending          ",
        ),
    ),
    ("G1-INVENTORY", sub("<!-- audit:images=93 -->", "<!-- audit:images=92 -->")),
    ("G2-KEYS", regex(r"(\| KB-02 \|[^\n]*?\| )`Ctrl\+K`", r"\1`Ctrl+J`")),
    ("G2-KEYS", regex(r"(\| KB-19 \|[^\n]*?\| )`panel`", r"\1`sheet`")),
    (
        "G3-FOCUS",
        regex(
            r"(\| FM-11 \|[^\n]*?\| )kept · the same symbol's cell",
            r"\1moves to · the body          ",
        ),
    ),
    (
        "G4-REGIONS",
        regex(
            r"(\| RG-03 \|[^\n]*?\| )`tablist`, manual activation",
            r"\1                            ",
        ),
    ),
    (
        "G5-SCRIPT",
        sub(
            '"Reconnected. 1 order filled while offline."',
            '"Reconnected. 1 order was filled while offline."',
        ),
    ),
    ("G5-SCRIPT", regex(r"(\| SR-21 \|[^\n]*?\| )polite ", r"\1loudly ")),
    (
        "G6-BUDGET",
        sub(
            "SR-27, SR-34, SR-37, SR-38 coalesce to the latest",
            "SR-27, SR-34, SR-37, SR-04 coalesce to the latest",
        ),
    ),
    ("G6-BUDGET", regex(r"(\| BG-06 \|[^\n]*?\| )surface(\s+\|)", r"\1drawer \2")),
    (
        "G6-BUDGET",
        regex(r"(\| BG-11 \|[^\n]*?\| )≤ 1 per 5 s per region", r"\1n/a                    "),
    ),
    ("G7-T2", regex(r"(\| T2-09 \|[^\n]*?\| )T2 (\s+\| 2a: beside)", r"\1T9 \2")),
    ("G7-T2", sub('`watchlist.first` "Already first."', '`watchlist.first` "Already the first."')),
    (
        "G8-VERDICT",
        regex(
            r"(\| §3\.4 item 2 — roving tabindex in composite widgets\s+\| )compliant",
            r"\1at risk  ",
        ),
    ),
    (
        "G9-FINDINGS",
        regex(r"(\| F-02 \|[^\n]*?\| )E08-D08 · area/ingestion", r"\1the scanner lane        "),
    ),
    ("G9-FINDINGS", sub("<!-- audit:c=21 -->", "<!-- audit:c=20 -->")),
    (
        "G10-RULED",
        regex(
            r"(\| BQ-18 \|[^\n]*\| )RULED \(orchestrator, 2026-10-31",
            r"\1RULED (someone, 2026-10-31",
        ),
    ),
    ("G11-CITE", pin_sub(r"^(CAL\|13\|)(.*)$", r"\1NOT THE WORDS \2")),
    ("G11-CITE", sub("`CAL`:13–:14 (Sprint 01", "`CAL`:12–:14 (Sprint 01")),
    ("G12-COLOUR", sub("<!-- audit:cvd-images=12 -->", "<!-- audit:cvd-images=11 -->")),
    (
        "G12-COLOUR",
        regex(r"(\| CR-02 \|[^\n]*?\| )(\d+\.\d)(\s+\| )(\d+\.\d)", r"\g<1>0.0\g<3>\g<4>"),
    ),
    (
        "G13-HYGIENE",
        sub(
            "## 16. Summary for #180",
            "## 16. Summary for #180 (see " + "http" + "s://" + "example.invalid)",
        ),
    ),
    (
        "G13-HYGIENE",
        sub("## 16. Summary for #180", "## 16. Summary for #180 (" + "GH" + "SA-abcd-ef12-3456)"),
    ),
    (
        "G13-HYGIENE",
        sub("## 16. Summary for #180", "## 16. Summary for #180 (" + "local" + "host:9000)"),
    ),
    (
        "G14-UNSTATED",
        sub(
            "kept · the same symbol's cell; if it leaves the set, restored to · the row now at its index, after W-20",
            "PROPOSED (F-02): kept · the same symbol's cell; else moves to · the first row",
        ),
    ),
    (
        "G15-CRITERIA",
        regex(
            r"(\| 4\.1\.3 Status messages\s+\| )at risk — interim path: [^|]*\|", r"\1compliant |"
        ),
    ),
    (
        "G15-CRITERIA",
        regex(
            r"(\| §6\.2 — live regions throttled and summarised; region hygiene\s+\| )at risk — interim path: [^|]*\|",
            r"\1compliant |",
        ),
    ),
    ("G16-XREF", regex(r"(\| FM-13 \|[^\n]*?\| )SR-34 ", r"\1SR-99 ")),
    (
        "G17-PARITY",
        regex(
            r"(\| PP-07 \|[^\n]*?\| )the native `<input type=file>`; dropping is additive, never the only path",
            r"\1drag only                                                                     ",
        ),
    ),
    (
        "G18-STRUCT",
        regex(
            r"(\| Focus order and visible focus\s+\|(?:[^|]*\|){7}) out of scope — E08-D09 \(#177\)",
            r"\1 compliant (FM-01)              ",
        ),
    ),
    (
        "G19-DOM",
        regex(
            r"(\| F-01 \|[^\n]*?\| )the DS change request D07 raised",
            r"\1a wrapper element per cell for the chip, plus the DS change request D07 raised",
        ),
    ),
    (
        "G20-RATE",
        regex(r"(\| BG-05 \|[^\n]*?\| )≤ 1 per 5 s per surface", r"\1≤ 1 per 6 s per surface"),
    ),
    (
        "G20-RATE",
        regex(
            r"(\| SR-11 \|[^\n]*?\| )once per settled query \(300 ms rest\)",
            r"\1twice per settled query             ",
        ),
    ),
    ("G21-EDIT-SET", sub("<!-- audit:pointer-lines=9 -->", "<!-- audit:pointer-lines=8 -->")),
    (
        "G22-CALENDAR",
        sub(
            "<!-- audit:sprint.s08.start=2026-11-13 -->",
            "<!-- audit:sprint.s08.start=2026-11-14 -->",
        ),
    ),
    (
        "G23-WALK",
        sub(
            "(10) the cheat sheet's key as shipped against `05`:48 (C-s)",
            "(10) the cheat sheet's key as shipped against `05`:48 (C-s); (11) one more",
        ),
    ),
)


def digests() -> dict[str, str]:
    paths = (SPEC, PINS, Path(__file__), ROOT / KEYS["14"])
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
        if not new or not all(x.startswith(f"[{code}]") for x in new):
            bad.append(f"self-test {code}: expected new [{code}] FAILs only, got {new[:3]}")
    again = run(ctx)
    if again.fails != base.fails:
        bad.append("self-test: a re-run does not reproduce the base result")
    if digests() != before:
        bad.append("self-test: a file on disk changed")
    return bad


def main(argv: list[str]) -> int:
    ap = argparse.ArgumentParser(description=(__doc__ or "").splitlines()[0])
    ap.add_argument("--check", action="store_true", help="exit 1 on any FAIL (a bare run does too)")
    ap.add_argument("--json", action="store_true", help="print the numbers and findings as JSON")
    ap.add_argument("--fill", action="store_true", help="rewrite the computed numbers in the spec")
    ap.add_argument("--self-test", "--selftest", action="store_true", help="the mutation self-test")
    ap.add_argument(
        "--repin-ruled", action="store_true", help="rewrite the pins file (the only writer)"
    )
    args = ap.parse_args(argv)
    missing = [k for k, rel in KEYS.items() if not git_show(HEAD, rel)]
    if missing:
        print(f"FAIL [G11-CITE] cannot read {missing} at {HEAD} (fetch first)")
        return 1
    ctx = load_ctx()
    if args.fill:
        print(f"numbers filled: {fill(ctx)}")
        ctx = load_ctx()
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
        print(json.dumps(payload, ensure_ascii=False, indent=1, sort_keys=True, default=str))
    else:
        out = [f"FAIL {line}" for line in res.fails] + [f"WARN {line}" for line in res.warns]
        out += [f"{k}: {v}" for k, v in res.numbers.items()]
        out.append(f"gates: {len(GATE_FNS)}; FAIL {len(res.fails)}, WARN {len(res.warns)}")
        if args.self_test:
            out += [f"FAIL {line}" for line in st]
            out.append(
                f"self-test: {'ok' if not st else 'FAILED'}: {len(MUTATIONS)} mutations (at least one "
                f"per gate, {len(GATE_FNS)} gates), each its own FAIL; a re-run reproduces the base "
                "result; files on disk unchanged"
            )
        print("\n".join(out))
    failed = bool(res.fails or st)
    return 1 if failed else 0


if __name__ == "__main__":
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")
    raise SystemExit(main(sys.argv[1:]))
