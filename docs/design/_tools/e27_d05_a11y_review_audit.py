"""E27-D05 (#818) audit: the accessibility review of the accounts and key-vault surfaces.

Stdlib only, offline (`python3 -I -B`). It reads the spec and the pins file from the working tree,
and every cited file AS TEXT at the pinned base with `git show`. It imports, never copies: the
E27-D03 audit (`e27_d03_hifi_audit.py`: `PAIRS_TXT`, `rows_txt`, `theme_colors`, `colour`,
`ratio`, `luma601`, `matrix`, `THEMES`, `DEFICIENCIES`, `JND` and its `cvd` module, which is
`docs/research/_tools/cvd_simulate.py` with `simulate`, `delta_e76`, `srgb_to_xyz`,
`xyz_to_lab`; `contrast_check.contrast_ratio()` is reached through its `ratio`) and the E27-D04
audit (`e27_d04_motion_audit.py`: `BOARDS`, its board count). It runs the E27-D03 audit once as a
subprocess to count how far that spec's own markers have drifted at the base. The token JSON is
read from the working tree through the E27-D03 audit, which is the base on this branch (the
review edits no token). Eleven gates, each FAIL led by its code:

- [G1-INVENTORY] section 2 lists the six surfaces, the two insets and the twenty-seven components
  as reviewed, and CMP-104 / CMP-106 with the ruled words; section 0's board counts equal the
  merged E27-D03 images at the base, and no E27-D04 board is merged.
- [G2-REQ] section 3: every catalogue clause the ticket names has an RQ row; a verdict from R-3's
  list; `at risk` or `non-compliant` names an F row, `compliant` names none.
- [G3-KEYS] section 4: every FO row fills open, Tab order, close, error and step change; section 5:
  the ten flows, each step a backticked key, no pointer word, an escape.
- [G4-T2] section 6: the view-as rows first, each led by `rbac.view_as` or recorded T3; a class per
  row; a T2 row's rendering 2a and its checks; no disabled token on a T2 row; an `rbac.*` string
  one sentence of at most 60 characters; the admin key actions recorded T3 for view-as in the
  ruled words (BQ-5); the G-T2.4 key check: every `accounts.*` key a leg names is a PROPOSED E27
  state key in E27-D03's register at the base, its string one sentence of at most 60 characters.
- [G5-LIVE] section 9: a politeness and a maximum rate on every LR row, a justification, assertive
  rows once per event, and the deliberately silent rows (heartbeat age, countdown ticks, staleness
  age, `wallet`, `system`, the 60 s health refresh) never spoken.
- [G6-COLOUR] section 10's CR rows (greyscale delta L*, the minimum delta E76 under three
  deficiencies) and section 11's CT rows and matrix line, all recomputed; section 11's drift line
  equals the E27-D03 audit's own count at the base.
- [G7-VERDICT] section 13: a verdict from R-3's list; `at risk` names a Major or Minor F row or an
  interim path, `non-compliant` a Blocking one, `ruled divergence` (BQ-8) an A row and no F row.
- [G8-FINDINGS] section 14: counts against the heading and the marker; severity, owner (a spec or
  a component and an area, never an agent), target E27-D06 (#819) plus a consuming story unless
  Info, a G-T2 cell; the hold sentence; no dangling F, RQ, FO, KS, T2, LR, CR, CT, SR, C, G, Q, A
  or H id.
- [G9-RULED] the BQ section is headed "RULED (orchestrator, comment 6573574102)" and lists
  BQ-0..BQ-16 in order, each led by its ruling (OVERRIDE exactly for BQ-4, BQ-8 and BQ-16, ACCEPT
  for the rest) and naming the section it is built in; the accepted defaults' words
  (STANDING_PINS) and the ruled words (RULING_PINS) stand in the spec, and with
  `--source R818=FILE` each ruled phrase also stands in that saved copy of the ruling (bold marks
  dropped); no superseded wording (SUPERSEDED) is left anywhere in the spec.
- [G10-CITE] every `KEY`:line cite resolves at the base to a non-blank line; the pins file and the
  cited endpoints match both ways, each pin's words on its line; E27-D04 at the base equals its
  pin (#5001's merge) and E27-D03 equals its last edit.
- [G11-HYGIENE] no word or substring on the lane's public-text list, host, uuid, local path, URL
  or closing keyword (with or without a space before the #); no fixture label or decimal amount in a quoted example (sections 5, 9, 16).

`--json` prints the numbers and findings; `--check` exits 1 on any FAIL (0 FAIL, 0 WARN is the
bar); `--self-test` applies one mutation per gate (MUTATIONS) and the probes (PROBES) to an
in-memory copy and passes only when each adds exactly one new FAIL with its gate's code, a re-run
reproduces the base result and no file on disk changed. `--repin` rewrites the pins file from the
spec's cites (keeping every hand-written pin still cited).

Usage: python3 -I -B docs/design/_tools/e27_d05_a11y_review_audit.py [--check] [--json]
       [--self-test] [--repin] [--source R818=FILE]
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
SPEC = ROOT / "docs" / "design" / "E27" / "E27-D05.md"
PINS = TOOLS / "e27_d05_ruled_pins.txt"
BASE = "e5b286ed50"  # origin/main; the BQ list (6573202169) and its ruling read every cite here
PIN_D04 = "0d63d2cadb"  # E27-D04 PR 1 (#5001) merged; PR 2 (the seven boards) not opened (R6)
PIN_D03 = "aef2cc150b"  # E27-D03's last edit (the 2026-10-31 token retune, #5161)
KEYS = {
    "05": "docs/plan/05-accessibility-standard.md",
    "11": "docs/plan/11-user-stories.md",
    "14": "docs/plan/14-screens-catalogue.md",
    "15": "docs/plan/15-component-catalogue.md",
    "16": "docs/plan/16-design-system-brief.md",
    "23": "docs/plan/23-ws-protocol.md",
    "DS": ".claude/rules/32-design-specs.md",
    "D02": "docs/design/E27/E27-D02.md",
    "D03": "docs/design/E27/E27-D03.md",
    "D04": "docs/design/E27/E27-D04.md",
    "E09-D09": "docs/design/E09/E09-D09.md",
    "E30-D05": "docs/design/E30/E30-D05.md",
    "E27.json": "docs/plan/backlog/E27.json",
}
IMG_DIR = "docs/design/E27/img"
D03_BOARDS = 10  # D03 section 0: ten boards, boards 01 and 02 with three renders each
D03_FILES = 16
SURFACES = ("SCR-125", "SCR-126", "SCR-127", "SCR-128", "SCR-129", "SCR-079")
INSETS = ("SCR-016 step 3", "SCR-019")
INSET_WORDS = "reviewed as an E27-D03 inset"
COMPONENTS = (
    "CMP-027", "CMP-028", "CMP-033", "CMP-034", "CMP-035", "CMP-036", "CMP-040", "CMP-043",
    "CMP-044", "CMP-046", "CMP-049", "CMP-055", "CMP-065", "CMP-066", "CMP-087", "CMP-093",
    "CMP-116", "CMP-128", "CMP-129", "CMP-175", "CMP-176", "CMP-178", "CMP-201", "CMP-079",
    "CMP-019",
)  # fmt: skip
CONTRACT_ONLY = ("CMP-104", "CMP-106")
CONTRACT_WORDS = "reviewed at its `15` contract only"
REQ_CITES = (  # the catalogue clauses the ticket's Scope names, each with an RQ row
    "`14`:2637", "`14`:2666", "`14`:2680", "`14`:2693", "`14`:2704", "`14`:1841",
    "`14`:474", "`14`:85",
)  # fmt: skip
VERDICTS = (
    "compliant",
    "at risk",
    "non-compliant",
    "out of scope",
    "not yet decidable",
    "ruled divergence",
)
FLOWS = ("KS-R", "KS-I", "KS-T", "KS-O", "KS-V", "KS-D", "KS-X", "KS-L", "KS-E", "KS-C")
POINTER = re.compile(r"pointer|click|mouse|hover|drag|tap\b", re.IGNORECASE)
T2_CLASSES = ("T2", "T3", "validity", "busy")
DISABLED_TOKENS = ("opacity.disabled", "color.text.disabled")
ADMIN_ACTIONS = ("Add", "Rotate", "Test", "Revoke", "Disable", "Delete")
POLITENESS = ("polite", "assertive", "off", "never spoken", "none")
RATE_RE = re.compile(r"once|per |never|≤|marks?|on focus|on demand")
SILENT = (  # deliberately silent events (BQ-11), each a "never spoken" LR row
    "heartbeat age", "countdown ticks", "staleness age", "`wallet`", "`system`",
    "60 s health refresh",
)  # fmt: skip
SEVERITIES = ("Blocking", "Major", "Minor", "Info")
OWNER_RE = re.compile(r"^(?:E\d\d-D\d\d|CMP-\d{3}) · area/[a-z-]+$")
VIEWAS = re.compile(r"\bview(?:ing)?[- ]as\b")
AGENT_RE = re.compile(r"worker|agent|session|lane", re.IGNORECASE)
TARGET = "E27-D06 (#819)"
STORY_RE = re.compile(r"E27-S0[1-5] \(#89[5-9]\)|E27-Q04|E27-D07")
HOLD = "E27-D06 (#819) is not signed off while a Blocking row stands"
RULING = "6573574102"  # the orchestrator's ruling of record on the BQ list 6573202169
BQ_HEAD = f"## The seventeen questions (BQ-0 to BQ-16) — RULED (orchestrator, comment {RULING})"
BQ_IDS = tuple(f"BQ-{i}" for i in range(17))  # as posted: BQ-0 to BQ-16
OVERRIDES = ("BQ-4", "BQ-8", "BQ-16")  # the ruling accepts every other default
STANDING_PINS = (  # the accepted defaults' words, each standing in the spec (G9)
    "Refs #818",
    "not drawn — the text is binding",
    "PENDING (PR 2)",
    "never as evidence",
    "T3 by step 1 — recorded, not a miss",
    "focused content replaced inside an open modal",
    "the re-review is this tool's F gate re-run on E27-D06",
    "`large-pr-approved`",
)
RULING_PINS = (  # the ruled words, verbatim from the ruling (bold dropped); G9, and --source
    "ACCEPT every default except BQ-4, BQ-8 and BQ-16",
    "a G-T2 miss stays Major",
    "Blocking = no compliant path, colour alone, or a destructive step not perceivable non-visually",
    "the route is T3 (E09-D09 §2.1 step 1; D03 §10.2 'who sees what'), so the controls never render",
    "the `accounts.*` keys are PROPOSED E27 state keys",
    'ruled divergence, not "compliant"',
    "keep announce-first and the A-row to `05` §3.4 item 3",
    "no new figure",
    "never gating Done",
    "the owner's explicit `approved` precedes Done for a design ticket (C-10.1)",
)
SUPERSEDED = (  # the defaults the ruling overrode, and the pre-ruling stamp
    "ruling pending",
    "defaults built",
    "post-Done",
    "compliant inside the open modal",
    "a G-T2 miss that hides the reason",
)
STATE_KEY = re.compile(
    r'^\| `(accounts\.[a-z_]+)` +\| "([^"]+)" +\| state, PROPOSED E27', re.MULTILINE
)
ID_KINDS = ("RQ", "FO", "T2", "LR", "CR", "CT", "SR", "C", "G", "Q", "A", "H")
SIMS = ("protanopia", "deuteranopia", "tritanopia")
BARS = {"text": 4.5, "non-text": 3.0, "hc-text": 7.0}
# The lane's public-text list, rot13-encoded so that no listed word stands in this file.
DENY_ROT13 = (
    "yrnx rkcbfrq olcnff rkcybvg nggnpx benpyr erirny haobhaqrq sybbq fgnyy nqivfbel "
    "TUFN cer-nhgu upy-jbexre ucr-jbexre Naivy ErynlEbbz fpengpu-naivy znva-bepurfgengbe fniil-sybj"
)
DENY = tuple(codecs.decode(DENY_ROT13, "rot13").split())
DENY_WORD = re.compile(r"\b" + codecs.decode("qbf", "rot13") + r"\b", re.IGNORECASE)
HOST = re.compile(
    r"\b[a-z0-9-]+(?:\.[a-z0-9-]+)*\.(?:com|net|org|io|dev|app|cloud)\b", re.IGNORECASE
)
UUID = re.compile(
    r"\b[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}\b", re.IGNORECASE
)
FIXTURE = re.compile(r"\b(?:Main|sub_00\d|demo-1|alex|bea)\b|(?<![\w.-])\d[\d,]*\.\d")
QUOTED = re.compile(r'"([^"\n]*)"')
CITE = re.compile(r"`([A-Za-z0-9.\-]+)`:(\d+)(?:–(\d+))?")
MARKER = re.compile(r"<!--\s*audit:f=(\d+)/(\d+)/(\d+)/(\d+)/(\d+)\s*-->", re.DOTALL)
COMMENT = re.compile(r"<!--.*?-->", re.DOTALL)


def _load(name: str) -> ModuleType:
    spec = importlib.util.spec_from_file_location(name, TOOLS / f"{name}.py")
    if spec is None or spec.loader is None:
        raise SystemExit(f"cannot load {name}")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


D03T: Any = _load("e27_d03_hifi_audit")
D04T: Any = _load("e27_d04_motion_audit")


def git(*args: str) -> str:
    out = subprocess.run(
        ["git", "-C", str(ROOT), *args],
        capture_output=True,
        check=False,
        text=True,
        encoding="utf-8",
    )
    return out.stdout if out.returncode == 0 else ""


def git_show(rev: str, rel: str) -> str:
    return git("show", f"{rev}:{rel}")


def d03_drift() -> str:
    """The E27-D03 audit's own verdict at the base: its last 'FAIL n · WARN m' line."""
    out = subprocess.run(
        [sys.executable, "-I", "-B", str(TOOLS / "e27_d03_hifi_audit.py"), "--check"],
        capture_output=True,
        check=False,
        text=True,
        encoding="utf-8",
    )
    lines = [ln for ln in out.stdout.splitlines() if re.fullmatch(r"FAIL \d+ · WARN \d+", ln)]
    return lines[-1] if lines else "unreadable"


# --- colour, computed once per run --------------------------------------------------------------
TH: dict[str, dict[str, str]] = {t: D03T.theme_colors(t) for t in D03T.THEMES}
PAIRS: dict[str, tuple[str, str, str]] = {
    r[0]: (r[2], r[3], r[4]) for r in D03T.rows_txt(D03T.PAIRS_TXT)
}


def pair_ratios(pid: str) -> list[float]:
    fg, bg, _ = PAIRS[pid]
    return [float(D03T.ratio(D03T.colour(TH, t, fg), D03T.colour(TH, t, bg))) for t in D03T.THEMES]


def passes(role: str, v: list[float]) -> bool:
    bar = BARS.get(role)
    return bar is None or (v[2] >= bar if role == "hc-text" else min(v) >= bar)


def lstar(hex6: str) -> float:
    y = D03T.luma601(hex6)
    grey = f"#{y:02X}{y:02X}{y:02X}"
    return float(D03T.cvd.xyz_to_lab(D03T.cvd.srgb_to_xyz(grey))[0])


def carrier_numbers(a: str, b: str) -> tuple[str, str]:
    dl: list[float] = []
    de: list[float] = []
    for t in D03T.THEMES:
        ha, hb = D03T.colour(TH, t, a), D03T.colour(TH, t, b)
        dl.append(abs(lstar(ha) - lstar(hb)))
        de += [
            float(D03T.cvd.delta_e76(D03T.cvd.simulate(ha, k), D03T.cvd.simulate(hb, k)))
            for k in SIMS
        ]
    return f"{min(dl):.1f}", f"{min(de):.1f}"


def matrix_line() -> str:
    m = D03T.matrix(TH, set())
    n, ring = m["n"], m["ring_min"]
    return (
        f"**Matrix:** {n['rows']} pairs · gated {n['gated']} · FAIL {n['fail']} · E27-D03 "
        f"reproductions off {n['repro_fail']} of {n['repro']} · ring minima {ring['dark']} / "
        f"{ring['light']} / {ring['high-contrast']}"
    )


class Ctx(NamedTuple):
    spec: str
    tool: str
    pins: str
    base: dict[str, str]
    images: tuple[str, ...]
    d04_pin: str
    d03_pin: str
    matrix: str
    drift: str
    source: str = ""


class Result:
    def __init__(self) -> None:
        self.fails: list[str] = []
        self.warns: list[str] = []
        self.numbers: dict[str, object] = {}

    def fail(self, code: str, msg: str) -> None:
        self.fails.append(f"[{code}] {msg}")


def load_ctx(source: str = "") -> Ctx:
    return Ctx(
        spec=SPEC.read_text(encoding="utf-8"),
        tool=Path(__file__).read_text(encoding="utf-8"),
        pins=PINS.read_text(encoding="utf-8") if PINS.exists() else "",
        base={k: git_show(BASE, v) for k, v in KEYS.items()},
        images=tuple(
            Path(p).name for p in git("ls-tree", "--name-only", BASE, IMG_DIR + "/").split()
        ),
        d04_pin=git_show(PIN_D04, KEYS["D04"]),
        d03_pin=git_show(PIN_D03, KEYS["D03"]),
        matrix=matrix_line(),
        drift=d03_drift(),
        source=source,
    )


# --- markdown helpers ---------------------------------------------------------------------------
def section(text: str, head: str) -> str:
    """The body under the `##` or `###` heading `head`, to the next heading at its level."""
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
    """Every table body row in the block (header and rule lines dropped)."""
    lines = block.splitlines()
    out: list[list[str]] = []
    for i, ln in enumerate(lines):
        if not ln.startswith("|") or re.match(r"^\|\s*:?-", ln):
            continue
        if i + 1 < len(lines) and re.match(r"^\|\s*:?-", lines[i + 1]):
            continue  # a header
        out.append(cells(ln))
    return out


def by_id(block: str, prefix: str) -> dict[str, list[str]]:
    return {r[0]: r for r in rows(block) if re.fullmatch(prefix + r"-[\w-]+", r[0])}


def norm(text: str) -> str:
    return re.sub(r"\s+", " ", text).strip()


def ticks(cell: str) -> list[str]:
    return re.findall(r"`([^`]+)`", cell)


def verdict_ok(cell: str) -> bool:
    return any(cell == v or cell.startswith(v + " — ") for v in VERDICTS)


# --- G1: inventory and boards -------------------------------------------------------------------
def gate_inventory(ctx: Ctx, r: Result) -> None:
    table = rows(section(ctx.spec, "2. Inventory"))
    seen: dict[str, str] = {}
    for row in table:
        for name in (*SURFACES, *INSETS, *COMPONENTS, *CONTRACT_ONLY):
            if row[0].startswith(name + " ") or row[0] == name:
                seen[name] = row[2] if len(row) > 2 else ""
    for name in SURFACES + COMPONENTS:
        if seen.get(name) != "reviewed":
            r.fail("G1-INVENTORY", f"{name}: not listed as reviewed in section 2")
    for name in INSETS:
        if seen.get(name) != INSET_WORDS:
            r.fail("G1-INVENTORY", f"{name}: not {INSET_WORDS!r}")
    for name in CONTRACT_ONLY:
        if seen.get(name) != CONTRACT_WORDS:
            r.fail("G1-INVENTORY", f"{name}: not {CONTRACT_WORDS!r}")
    d03 = [i for i in ctx.images if i.startswith("E27-D03-")]
    boards = {i[:10] for i in d03}
    d04 = [i for i in ctx.images if i.startswith("E27-D04-")]
    zero = section(ctx.spec, "0. Status")
    words = f"{len(boards)} boards, {len(d03)} files"
    if len(boards) != D03_BOARDS or len(d03) != D03_FILES or words not in zero:
        r.fail("G1-INVENTORY", f"section 0 does not read {words!r} (merged at the base)")
    if d04 or "seven boards" not in zero or int(D04T.BOARDS) != 7:
        r.fail("G1-INVENTORY", "E27-D04's boards: merged at the base, or section 0 omits them")
    r.numbers["inventory"] = len(seen)
    r.numbers["d03_images"] = words


# --- G2: catalogue requirements -----------------------------------------------------------------
def gate_req(ctx: Ctx, r: Result) -> None:
    table = by_id(section(ctx.spec, "3. The catalogue requirements"), "RQ")
    blob = " ".join(" ".join(row) for row in table.values())
    for cite in REQ_CITES:
        if cite not in blob:
            r.fail("G2-REQ", f"no RQ row cites {cite}")
    for rid, row in table.items():
        verdict, ref = row[3], row[5]
        if not verdict_ok(verdict):
            r.fail("G2-REQ", f"{rid}: verdict {verdict!r} is not one of R-3's")
        elif verdict.startswith(("at risk", "non-compliant")) and not re.search(r"F-\d\d", ref):
            r.fail("G2-REQ", f"{rid}: {verdict} names no F row")
        elif verdict == "compliant" and ref != "none":
            r.fail("G2-REQ", f"{rid}: compliant but names {ref!r}")
    r.numbers["rq"] = len(table)


# --- G3: focus maps and keyboard flows -----------------------------------------------------------
def gate_keys(ctx: Ctx, r: Result) -> None:
    fo = by_id(section(ctx.spec, "4. Focus-order maps"), "FO")
    for fid, row in fo.items():
        if len(row) < 7 or not all(c.strip() for c in row[1:7]):
            r.fail("G3-KEYS", f"{fid}: an empty open / order / close / error / step cell")
    if len(fo) < 11:
        r.fail("G3-KEYS", f"section 4 maps {len(fo)} surfaces and dialogs, under eleven")
    ks = by_id(section(ctx.spec, "5. The keyboard-only flows"), "KS")
    for flow in FLOWS:
        steps = [k for k in ks if k.startswith(flow + "-")]
        if len(steps) < 2:
            r.fail("G3-KEYS", f"{flow}: fewer than two steps")
    for kid, row in ks.items():
        key, lands, out = row[1], row[2], row[4] if len(row) > 4 else ""
        if not ticks(key) or POINTER.search(key) or POINTER.search(lands):
            r.fail("G3-KEYS", f"{kid}: no key, or a pointer word")
        if not out.strip():
            r.fail("G3-KEYS", f"{kid}: no escape")
    r.numbers["fo"] = len(fo)
    r.numbers["ks"] = len(ks)


# --- G4: T2 ---------------------------------------------------------------------------------------
def gate_t2(ctx: Ctx, r: Result) -> None:
    six = section(ctx.spec, "6. Gated controls")
    table = by_id(six, "T2")
    order = list(table)
    viewas = [k for k in order if VIEWAS.search(table[k][1])]
    if not viewas or order[: len(viewas)] != viewas:
        r.fail("G4-T2", "the view-as rows do not come first")
    for tid, row in table.items():
        control, leg, cls, rend, r5, checks = row[1], row[2], row[3], row[4], row[5], row[6]
        if cls not in T2_CLASSES:
            r.fail("G4-T2", f"{tid}: class {cls!r}")
            continue
        if VIEWAS.search(control) and not (leg.startswith("`rbac.view_as`") or cls == "T3"):
            r.fail("G4-T2", f"{tid}: a view-as row not led by `rbac.view_as` nor recorded T3")
        if cls == "T2":
            if not rend.startswith("2a") or not checks.startswith("1a–d · 2 · 3 · 4"):
                r.fail("G4-T2", f"{tid}: rendering {rend!r} or checks {checks!r}")
            if any(t in " ".join(row) for t in DISABLED_TOKENS):
                r.fail("G4-T2", f"{tid}: a disabled token on a T2 row")
        if not r5:
            r.fail("G4-T2", f"{tid}: no R5 cell")
        for key, text in re.findall(r'`(rbac\.[a-z_]+)` "([^"]+)"', leg):
            if len(text) > 60 or not text.endswith(".") or text.count(". ") > 0:
                r.fail("G4-T2", f"{tid}: {key} {text!r} is not one sentence of ≤ 60 characters")
    admin = [row for row in table.values() if all(a in row[1] for a in ADMIN_ACTIONS)]
    if (
        not admin
        or admin[0][3] != "T3"
        or "T3 by step 1 — recorded, not a miss" not in admin[0][6]
        or RULING_PINS[3] not in admin[0][2]
    ):
        r.fail("G4-T2", "the admin key actions are not recorded T3 for view-as in the ruled words")
    registered = dict(STATE_KEY.findall(ctx.base["D03"]))
    named = set(re.findall(r"`(accounts\.[a-z_]+)`", " ".join(" ".join(v) for v in table.values())))
    bad = sorted(k for k in named if k not in registered)
    long = sorted(
        k for k, s in registered.items() if len(s) > 60 or not s.endswith(".") or ". " in s
    )
    if not registered or bad or long or RULING_PINS[4] not in six:
        r.fail("G4-T2", f"G-T2.4: unregistered {bad[:3]}, not one sentence ≤ 60 {long[:3]}")
    r.numbers["t2"] = len(table)
    r.numbers["state_keys"] = len(registered)


# --- G5: live regions ---------------------------------------------------------------------------
def gate_live(ctx: Ctx, r: Result) -> None:
    table = by_id(section(ctx.spec, "9. The live-region plan"), "LR")
    for lid, row in table.items():
        event, pol, rate, why = row[1], row[3], row[4], row[5]
        if not any(pol == p or pol.startswith(p + ";") for p in POLITENESS):
            r.fail("G5-LIVE", f"{lid}: politeness {pol!r}")
        if not RATE_RE.search(rate):
            r.fail("G5-LIVE", f"{lid}: no maximum rate")
        if not why.strip():
            r.fail("G5-LIVE", f"{lid}: no justification")
        if pol == "assertive" and "once" not in rate:
            r.fail("G5-LIVE", f"{lid}: an assertive row not once per event")
        del event
    for word in SILENT:
        hit = [row for row in table.values() if word in row[1]]
        if not hit or any(row[3] != "never spoken" for row in hit):
            r.fail("G5-LIVE", f"the silent event {word!r} has no never-spoken row")
    r.numbers["lr"] = len(table)


# --- G6: carriers, contrast and drift -----------------------------------------------------------
def gate_colour(ctx: Ctx, r: Result) -> None:
    table = by_id(section(ctx.spec, "10. Colour never"), "CR")
    for cid, row in table.items():
        carrier, toks, dl, de, verdict = row[2], ticks(row[3]), row[4], row[5], row[6]
        if not carrier or verdict != "distinguishable by carrier":
            r.fail("G6-COLOUR", f"{cid}: carrier or verdict off the rule")
        want = carrier_numbers(*toks[:2]) if len(toks) == 2 else ("?", "?")
        if (dl, de) != want:
            r.fail("G6-COLOUR", f"{cid}: ΔL* / ΔE {dl} / {de}, computed {want}")
    eleven = section(ctx.spec, "11. Contrast")
    if ctx.matrix not in eleven:
        r.fail("G6-COLOUR", f"section 11 does not read {ctx.matrix!r}")
    drift = f"the E27-D03 audit reads {ctx.drift} at the base"
    if drift not in eleven:
        r.fail("G6-COLOUR", f"section 11 does not say {drift!r}")
    for tid, row in by_id(eleven, "CT").items():
        pid = ticks(row[2])[0] if ticks(row[2]) else ""
        if pid not in PAIRS or row[3] != PAIRS[pid][2]:
            r.fail("G6-COLOUR", f"{tid}: pair {pid!r} or its role is not E27-D03's")
            continue
        v = pair_ratios(pid)
        got = [f"{x:.2f}" for x in v] + ["PASS" if passes(row[3], v) else "FAIL"]
        if row[4:8] != got:
            r.fail("G6-COLOUR", f"{tid}: {row[4:8]}, computed {got}")
    r.numbers["carriers"] = len(table)
    r.numbers["matrix"] = ctx.matrix.removeprefix("**Matrix:** ")
    r.numbers["d03_drift"] = ctx.drift


# --- G7: verdicts -------------------------------------------------------------------------------
def severities(spec: str) -> dict[str, str]:
    return {k: v[1] for k, v in by_id(section(spec, "14. Findings"), "F").items()}


def gate_verdict(ctx: Ctx, r: Result) -> None:
    sev = severities(ctx.spec)
    table = rows(section(ctx.spec, "13. Clause verdicts"))
    n = 0
    for row in table:
        if len(row) < 4 or not re.match(r"^(?:`05`|\d\.\d)", row[0]):
            continue
        n += 1
        verdict, ref = row[1], row[3]
        refs = re.findall(r"F-\d\d", ref)
        if not verdict_ok(verdict):
            r.fail("G7-VERDICT", f"{row[0]}: verdict {verdict!r}")
        elif verdict == "non-compliant" and not any(sev.get(f) == "Blocking" for f in refs):
            r.fail("G7-VERDICT", f"{row[0]}: non-compliant without a Blocking F row")
        elif verdict.startswith("at risk") and not (
            any(sev.get(f) in ("Major", "Minor") for f in refs) or "interim" in ref
        ):
            r.fail("G7-VERDICT", f"{row[0]}: at risk without an F row or an interim path")
        elif verdict == "compliant" and refs:
            r.fail("G7-VERDICT", f"{row[0]}: compliant but names {refs}")
        elif verdict.startswith("ruled divergence") and (refs or not re.search(r"A-\d\d", row[2])):
            r.fail(
                "G7-VERDICT", f"{row[0]}: a ruled divergence without its A row, or with an F row"
            )
    if n < 15:
        r.fail("G7-VERDICT", f"section 13 has {n} clause rows, under fifteen")
    r.numbers["clauses"] = n


# --- G8: findings ---------------------------------------------------------------------------------
def gate_findings(ctx: Ctx, r: Result) -> None:
    fourteen = section(ctx.spec, "14. Findings")
    table = by_id(fourteen, "F")
    counts = {s: sum(1 for row in table.values() if row[1] == s) for s in SEVERITIES}
    head = re.search(r"^## 14\. Findings — F (\d+) \(([^)]*)\)(.*)$", ctx.spec, re.MULTILINE)
    want = (
        f"Blocking {counts['Blocking']} · Major {counts['Major']} · Minor {counts['Minor']} · "
        + (f"Info {counts['Info']}")
    )
    if not head or int(head.group(1)) != len(table) or head.group(2) != want:
        r.fail("G8-FINDINGS", f"the heading does not read F {len(table)} ({want})")
    mk = MARKER.search(head.group(3) if head else "")
    nums = (len(table), *(counts[s] for s in SEVERITIES))
    if not mk or tuple(int(x) for x in mk.groups()) != nums:
        r.fail("G8-FINDINGS", f"the audit marker is not f={'/'.join(map(str, nums))}")
    for fid, row in table.items():
        sev, owner, target, gt2 = row[1], row[4], row[5], row[6]
        if sev not in SEVERITIES:
            r.fail("G8-FINDINGS", f"{fid}: severity {sev!r}")
        if not OWNER_RE.match(owner) or AGENT_RE.search(owner):
            r.fail("G8-FINDINGS", f"{fid}: owner {owner!r} is not a spec or component and area")
        if TARGET not in target or (sev != "Info" and not STORY_RE.search(target)):
            r.fail("G8-FINDINGS", f"{fid}: target {target!r}")
        if not gt2.strip():
            r.fail("G8-FINDINGS", f"{fid}: no G-T2 cell")
    if HOLD not in fourteen:
        r.fail("G8-FINDINGS", "the hold sentence is missing")
    body = COMMENT.sub("", ctx.spec)
    defined = set(table)
    for kind in ID_KINDS:
        defined |= set(by_id(ctx.spec, kind))
    defined |= {k for k in re.findall(r"^\| (KS-[A-Z]-\d\d) ", ctx.spec, re.MULTILINE)}
    used = set(re.findall(r"\b((?:F|RQ|FO|T2|LR|CR|CT|SR|C|G|Q|A|H)-\d\d)\b(?!\.\d)", body))
    used |= set(re.findall(r"\b(KS-[A-Z]-\d\d)\b", body))
    dangling = sorted(used - defined)
    if dangling:
        r.fail("G8-FINDINGS", f"ids used but defined in no table: {dangling[:6]}")
    r.numbers["findings"] = dict(counts, total=len(table))


# --- G9: the BQ list, ruled -----------------------------------------------------------------------
def unbold(text: str) -> str:
    return norm(text.replace("**", ""))


def gate_ruled(ctx: Ctx, r: Result) -> None:
    if BQ_HEAD not in ctx.spec:
        r.fail("G9-RULED", "the BQ section heading is not the ruled form")
        return
    bq = section(ctx.spec, BQ_HEAD.removeprefix("## "))
    table = {row[0]: row for row in rows(bq) if row[0].startswith("BQ-")}
    if tuple(table) != BQ_IDS:
        r.fail("G9-RULED", f"the BQ rows are {list(table)[:3]}…, not BQ-0..BQ-16 in order")
    for bid, row in table.items():
        want = "OVERRIDE:" if bid in OVERRIDES else "ACCEPT"
        if not row[-1].startswith(want) or not re.search(r"§\d", row[-1]):
            r.fail("G9-RULED", f"{bid}: not led by {want!r} with the section it is built in")
    flat = unbold(ctx.spec)
    for pin in (*STANDING_PINS, *RULING_PINS):
        if norm(pin) not in flat:
            r.fail("G9-RULED", f"the words {pin!r} are not in the spec")
    if ctx.source:
        saved = unbold(ctx.source)
        for pin in RULING_PINS:
            if norm(pin) not in saved:
                r.fail("G9-RULED", f"{pin!r} is not in the saved copy of the ruling")
    for old in SUPERSEDED:
        if old.lower() in flat.lower():
            r.fail("G9-RULED", f"superseded wording {old!r} is still in the spec")
    r.numbers["bq_rows"] = len(table)
    r.numbers["ruling_pins"] = len(RULING_PINS)


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
            r.fail("G10-CITE", f"`{key}`:{a}-{b}: out of range or blank at {BASE}")
    pins = parse_pins(ctx.pins)
    for (key, n), words in pins.items():
        lines = ctx.base.get(key, "").splitlines()
        line = lines[n - 1] if 0 < n <= len(lines) else ""
        if not words.strip() or norm(words) not in norm(line):
            r.fail("G10-CITE", f"pin {key}:{n}: {words[:40]!r} is not on that line at {BASE}")
    ends = endpoints(ctx.spec)
    uncited, unpinned = sorted(set(pins) - ends), sorted(ends - set(pins))
    if uncited or unpinned:
        r.fail(
            "G10-CITE", f"pins and cites disagree: uncited {uncited[:4]}; unpinned {unpinned[:4]}"
        )
    if not ctx.d04_pin or ctx.d04_pin != ctx.base["D04"]:
        r.fail("G10-CITE", f"E27-D04 at {BASE} differs from its pin {PIN_D04} (R6: re-pin)")
    if not ctx.d03_pin or ctx.d03_pin != ctx.base["D03"]:
        r.fail("G10-CITE", f"E27-D03 at {BASE} differs from its last edit {PIN_D03}")
    r.numbers["cites"] = len(found)
    r.numbers["pins"] = len(pins)


def repin(ctx: Ctx) -> int:
    old = parse_pins(ctx.pins)
    lines = []
    for key, n in sorted(endpoints(ctx.spec), key=lambda e: (e[0], e[1])):
        text = norm(ctx.base[key].splitlines()[n - 1])
        lines.append(f"{key}|{n}|{old.get((key, n)) or text[:72].rstrip()}")
    head = (
        "# E27-D05 pins: KEY|line|words that stand on that line at the base (the tool's G10).\n"
        "# `--repin` keeps every hand-written pin still cited and adds the line's opening words.\n"
    )
    PINS.write_text(head + "\n".join(lines) + "\n", encoding="utf-8")
    return len(lines)


# --- G11: hygiene -------------------------------------------------------------------------------
def gate_hygiene(ctx: Ctx, r: Result) -> None:
    for name, text in (("the spec", ctx.spec), ("the tool", ctx.tool), ("the pins", ctx.pins)):
        low = text.lower()
        for word in DENY:
            if word.lower() in low:
                r.fail("G11-HYGIENE", f"{name}: a word from the public-text list")
        if DENY_WORD.search(text):
            r.fail("G11-HYGIENE", f"{name}: a word from the public-text list")
        if HOST.search(text):
            r.fail("G11-HYGIENE", f"{name}: a host name")
        if UUID.search(text):
            r.fail("G11-HYGIENE", f"{name}: an id in the uuid form")
    local = "/" + "home/|/tmp/|/mnt/|[A-Z]:\\\\"
    closing = r"\b(?:close[sd]?|fix(?:e[sd])?|resolve[sd]?)\s*#\d"
    for pat, what in (
        (local, "a local path"),
        (r"https?://", "a URL"),
        (closing, "a closing keyword"),
    ):
        if re.search(pat, ctx.spec, re.IGNORECASE):
            r.fail("G11-HYGIENE", f"the spec: {what}")
    if re.search(r"^#+ What this .* fixes", ctx.spec, re.MULTILINE | re.IGNORECASE):
        r.fail("G11-HYGIENE", "the spec: a heading in the closing-summary form")
    examples = "".join(
        section(ctx.spec, h)
        for h in ("5. The keyboard-only", "9. The live-region", "16. The screen")
    )
    bad = [q for q in QUOTED.findall(examples) if FIXTURE.search(q)]
    if bad:
        r.fail("G11-HYGIENE", f"an example string with a fixture label or amount: {bad[:2]}")


GATE_FNS: tuple[tuple[str, Callable[[Ctx, Result], None]], ...] = (
    ("G1-INVENTORY", gate_inventory),
    ("G2-REQ", gate_req),
    ("G3-KEYS", gate_keys),
    ("G4-T2", gate_t2),
    ("G5-LIVE", gate_live),
    ("G6-COLOUR", gate_colour),
    ("G7-VERDICT", gate_verdict),
    ("G8-FINDINGS", gate_findings),
    ("G9-RULED", gate_ruled),
    ("G10-CITE", gate_cite),
    ("G11-HYGIENE", gate_hygiene),
)


def run(ctx: Ctx) -> Result:
    r = Result()
    for _, fn in GATE_FNS:
        fn(ctx, r)
    return r


# --- self-test ----------------------------------------------------------------------------------
Mut = Callable[[Ctx], Ctx]


def sub(old: str, new: str) -> Mut:
    return lambda ctx: ctx._replace(spec=ctx.spec.replace(old, new, 1))


def regex(pattern: str, repl: str) -> Mut:
    return lambda ctx: ctx._replace(
        spec=re.sub(pattern, repl, ctx.spec, count=1, flags=re.MULTILINE)
    )


def pin_regex(pattern: str, repl: str) -> Mut:
    return lambda ctx: ctx._replace(
        pins=re.sub(pattern, repl, ctx.pins, count=1, flags=re.MULTILINE)
    )


MUTATIONS: tuple[tuple[str, Mut], ...] = (
    ("G1-INVENTORY", regex(r"^(\| CMP-178 [^|]*\| component \| )reviewed ", r"\1skipped  ")),
    ("G2-REQ", regex(r"^(\| RQ-01 (?:[^|]*\|){3} )compliant", r"\1fine")),
    ("G3-KEYS", regex(r"^(\| KS-V-02 \| )`[^`]+`", r"\1click")),
    ("G4-T2", regex(r"^(\| T2-06 (?:[^|]*\|){4} )2a", r"\1tip")),
    (
        "G5-LIVE",
        regex(r"^(\| LR-\d\d \| heartbeat age[^|]*\|[^|]*\| )never spoken", r"\1polite      "),
    ),
    ("G6-COLOUR", regex(r"^(\| CR-01 (?:[^|]*\|){4} )(\d+)\.", r"\g<1>9\2.")),
    ("G7-VERDICT", regex(r"^(\| 1\.4\.1 [^|]*\| )compliant", r"\1compliance")),
    (
        "G8-FINDINGS",
        regex(r"^(\| F-01 (?:[^|]*\|){4} )E27-D03 · area/accounts-admin", r"\1a worker"),
    ),
    ("G9-RULED", sub(f"RULED (orchestrator, comment {RULING})", "ruling pending (comment x)")),
    ("G10-CITE", pin_regex(r"^(05\|\d+\|)", r"\1zz ")),
    ("G11-HYGIENE", sub("## 19. Summary", "## 19. Summary " + codecs.decode("ErynlEbbz", "rot13"))),
)

# Probes: edits a weaker gate would let through; each must add one FAIL.
PROBES: tuple[tuple[str, Mut], ...] = (
    (
        "G2-REQ",
        regex(
            r"^(\| RQ-\d\d (?:[^|]*\|){3} )at risk([^|]*\| (?:[^|]*\| )?)F-\d\d", r"\1at risk\2none"
        ),
    ),
    ("G3-KEYS", regex(r"^(\| KS-L-01 \| [^|]*\| )", r"\1hover, then ")),
    ("G4-T2", regex(r"^(\| T2-01 (?:[^|]*\|){2} )`rbac\.view_as`", r"\1`rbac.permission`")),
    (
        "G4-T2",
        regex(r"^(\| T2-04 .*?)T3 by step 1 — recorded, not a miss", r"\1T2 on the view-as leg"),
    ),
    (
        "G5-LIVE",
        regex(r"^(\| LR-\d\d (?:[^|]*\|){3} )assertive(\s*\| )once per", r"\1assertive\2≤ 1 per"),
    ),
    ("G6-COLOUR", sub("gated 57 · FAIL 0", "gated 57 · FAIL 1")),
    ("G6-COLOUR", regex(r"^(\| CT-01 (?:[^|]*\|){4} )(\d)", r"\g<1>0")),
    ("G7-VERDICT", regex(r"^(\| 4\.1\.3 [^|]*\| )at risk", r"\1non-compliant")),
    ("G8-FINDINGS", regex(r"^(Most severe first.*?)" + re.escape(HOLD), r"\1E27-D06 may sign off")),
    ("G8-FINDINGS", regex(r"^(\| F-02 (?:[^|]*\|){5} )([^|]*?)E27-S0\d \(#89\d\)", r"\1\2")),
    (
        "G9-RULED",
        sub("the re-review is this tool's F gate re-run on E27-D06", "the re-review is optional"),
    ),
    ("G9-RULED", regex(r"^(\| BQ-8 +\| [^|]*\| )OVERRIDE:", r"\1ACCEPT:")),
    (
        "G9-RULED",
        sub("Owner approval pending (#2701): the", "Owner walkthrough post-Done (#2701): the"),
    ),
    ("G4-T2", sub(RULING_PINS[4] + " (`D03`", "the keys (`D03`")),
    (
        "G7-VERDICT",
        regex(r"^(\| `05` §3\.4 item 3 [^|]*\| ruled divergence[^|]*\| [^|]*?)A-01", r"\1"),
    ),
    ("G11-HYGIENE", sub("## 19. Summary", "## 19. Summary " + "Closes" + "#818")),
    ("G10-CITE", lambda ctx: ctx._replace(d04_pin=ctx.d04_pin + "\n")),
    ("G11-HYGIENE", regex(r'^(\| SR-01 (?:[^|]*\|){2} )"', r'\1"sub_002 ')),
)


def digests() -> dict[str, str]:
    paths = (SPEC, PINS, Path(__file__))
    return {str(p): hashlib.sha256(p.read_bytes()).hexdigest() for p in paths if p.exists()}


def self_test(ctx: Ctx, base: Result) -> list[str]:
    bad: list[str] = []
    before = digests()
    covered = {code for code, _ in MUTATIONS}
    bad += [f"self-test: gate {g} has no mutation" for g, _ in GATE_FNS if g not in covered]
    for code, fn in (*MUTATIONS, *PROBES):
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
    ap.add_argument("--repin", action="store_true", help="rewrite the pins file from the cites")
    ap.add_argument("--source", default="", help="R818=FILE, a saved copy of the ruling")
    args = ap.parse_args(argv)
    source = ""
    if args.source:
        name, _, path = args.source.partition("=")
        if name != "R818" or not path:
            raise SystemExit("--source takes R818=FILE")
        source = Path(path).read_text(encoding="utf-8")
    ctx = load_ctx(source)
    if not all(ctx.base.values()):
        missing = [k for k, v in ctx.base.items() if not v]
        print(f"FAIL [G10-CITE] cannot read {missing} at {BASE} (fetch first)")
        return 1
    if args.repin:
        print(f"pins written: {repin(ctx)}")
        ctx = load_ctx(source)
    res = run(ctx)
    st = self_test(ctx, res) if args.self_test else []
    if args.json:
        payload: dict[str, object] = {"numbers": res.numbers, "fails": res.fails}
        payload["warns"] = res.warns
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
                f"self-test: {'ok' if not st else 'FAILED'}: {len(MUTATIONS)} mutations (one per "
                f"gate) and {len(PROBES)} probes, each one new FAIL; a re-run reproduces the base "
                "result; files on disk unchanged"
            )
        print("\n".join(out))
    failed = bool(res.fails or st)
    return 1 if (failed and (args.check or args.self_test)) else 0


if __name__ == "__main__":
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")
    raise SystemExit(main(sys.argv[1:]))
