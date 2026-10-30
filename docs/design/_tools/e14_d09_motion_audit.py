"""E14-D09 (#353) audit: the motion table, the do-not-animate list, the arithmetic, the cites.

Stdlib only, offline (`python3 -I -B`). It reads the spec from the working tree, and every cited
file and the token JSON AS TEXT at the pinned base with `git show`. Nine gates, each FAIL led by
its code, at most one G1 FAIL per table row:

- [G1-TABLE] section 2 holds D9-01 to D9-13 in order, every cell filled, no Carrier or reduce cell
  a dash; the moving rows are exactly MOVING; each row's layer is RULED_LAYER's; a cut reads the
  instant pair, Property `none`, "identical (a cut)", "static is not worse:" and no drag; a moving
  row's AC 1 cell starts "carries:"; only D9-03 runs during a drag; every other moving row cuts
  to rest at the drag threshold (DNA-4).
- [G2-TOKEN] every backticked name in a token group exists in the token JSON at the base or is
  one of R352's two ruled names; no motion token but the seven; each row's timing cell names its
  ruled motion tokens in order (RULED_TIMING; a cut names `motion.duration.instant` only).
- [G3-PROPERTY] a moving canvas half animates one instance alpha or one scale uniform; a DOM half
  only `opacity` or `transform`; a moving canvas row costs "+0 draw calls"; every canvas row says
  "the drawings layer only" and every row with a DOM layer "no layout on the chart container".
- [G4-DNA] DNA-1 to DNA-4 stand byte for byte in `E14.json`:675 at the base; DNA-5 to DNA-8 stand
  with their pinned sentences; each DNA id in DNA_ON is applied on its rows.
- [G5-ARITH] section 6's frames, instances, bytes and draw calls per moving row, and the HS-1,
  HS-1b and MR-1 figures (starts per window, the re-start gap, the ring's area, the region
  bound, the line, rectangle and ellipse halos, the bulk-restore split), recomputed from the
  token JSON and the rules.
- [G6-RULED] A28's stamp (in sections 1 and 8), the walkthrough line, CR-1's cite, the section
  7.5 title, the BQ-11 sentence, the Partial line and the R352 / R353 / A28 words (RULING_PINS)
  stand exactly; with `--source NAME=FILE` each pin is also found in that saved copy of the
  ruling.
- [G7-CITE] every `KEY`:line cite resolves to a declared key and an existing range at the base;
  each pinned cite still carries its words, and pins and cited spans match both ways (every pin
  cited, every in-range cited span pinned), so a cite moved to other lines fails; each cited
  file is identical at the BQ list's base and E05-D03 at its merge commit, whenever those
  commits are readable; no cite lands in `16` section 7's recipe lines (FORBIDDEN).
- [G8-HYGIENE] no local path, host, closing keyword, id or open-approval wording in the spec, and
  no word or substring on the lane's public-text list or a host name in the spec or this tool.
- [G9-BOARDS] section 10: six boards, 01 to 05 dark and 06 the light twin, names and exports in
  the ruled pattern, every board PENDING until PR 3.

`--json` prints the numbers and findings; `--check` exits 1 on any FAIL (0 FAIL, 0 WARN is the bar);
`--self-test` applies one mutation per gate (MUTATIONS) and the probes (PROBES) to an in-memory copy
of the spec and passes only when each adds exactly one new FAIL with its gate's code, a re-run on
the unmutated text reproduces the base result and no file on disk changed.

Usage: python3 -I -B docs/design/_tools/e14_d09_motion_audit.py [--check] [--json] [--self-test]
       [--source R352=FILE] [--source R353=FILE] [--source A28=FILE]
"""

from __future__ import annotations

import argparse
import codecs
import hashlib
import json
import math
import re
import subprocess
import sys
from collections.abc import Callable
from pathlib import Path
from typing import Any, NamedTuple

ROOT = Path(__file__).resolve().parents[3]
SPEC = ROOT / "docs" / "design" / "E14" / "E14-D09.md"
BASE = "7cb279c542"  # origin/main; every cite is read here
BQ_BASE = "3bac78e344"  # where the BQ list (6511707123) read every cite
E05_PIN = "29fe3d5b2e"  # the merge commit of E05-D03 (#4990), cited by row, rule and section id
KEYS = {
    "05": "docs/plan/05-accessibility-standard.md",
    "14": "docs/plan/14-screens-catalogue.md",
    "16": "docs/plan/16-design-system-brief.md",
    "26": "docs/plan/26-chart-engine-design.md",
    "D02": "docs/design/E14/E14-D02.md",
    "D03": "docs/design/E14/E14-D03.md",
    "D04": "docs/design/E14/E14-D04.md",
    "D07": "docs/design/E14/E14-D07.md",
    "D04H": "docs/design/E14/E14-D04-handoff.md",
    "D05H": "docs/design/E14/E14-D05-handoff.md",
    "D06H": "docs/design/E14/E14-D06-handoff.md",
    "D07H": "docs/design/E14/E14-D07-handoff.md",
    "E05-D03": "docs/design/E05/E05-D03.md",
    "E08-D11": "docs/design/E08/E08-D11.md",
    "E14.json": "docs/plan/backlog/E14.json",
    "README.md": "docs/design/README.md",
    "flags.ts": "packages/chart-engine/src/core/flags.ts",
    "handle.ts": "packages/chart-engine/src/core/handle.ts",
    "types.ts": "packages/chart-engine/src/api/types.ts",
    "index.ts": "packages/chart-engine/src/layers/index.ts",
    "m0-report.mjs": "packages/chart-engine/bench/matrix/m0-report.mjs",
    "SUMMARY.md": "packages/chart-engine/bench/matrix/results/2026-10-29-win11-i7-8550u/SUMMARY.md",
    "keymap.json": "apps/web/src/keymap/keymap.json",
    "popover.css": "packages/ui/src/components/popover.css",
    "run-proto.mjs": "docs/design/E08/E08-D11-proto/run-proto.mjs",
    "suppression-paths.json": "tools/ci/no-inline-suppression-paths.json",
}
TOKEN_FILES = (
    "packages/ui/tokens/primitives.tokens.json",
    "packages/ui/tokens/semantic-dark.tokens.json",
)
FORBIDDEN = ("16", 180, 186)  # `16` section 7's pre-E05-D03 recipe lines (R353 BQ-02)
# key|line|words that must stand on that line at the base (the load-bearing cites)
CITE_PINS = """\
05|208|No content flashes more than 3 times per second;14|954|>=58 fps with 200 drawings
14|1080|SCR-046;16|104|motion.duration.{instant,fast,normal,slow};26|130|Time-based animation
26|133|Render on demand;26|224|drawing labels a third;26|262|optimistic local writes
26|682|Drawing interaction: 200 drawings, drag one;D02|283|a count chip "7 selected"
D02|291|small travel threshold;D02|326|`aria-pressed` for selected;D02|332|**Nudges never snap.**
D02|332|a 10 px ring with the value text "High 65,400";D02|428|an undo that restores one focuses it
D02|453|nothing here animates by design;D02|500|"changes not saved" chip
D02|506|live updates are not undo steps;D02|507|static emphasis for snap, selection and undo
D02|525|"High 65,400.";D02|535|"Undone: moved trendline.";D02|537|"497 drawings deleted.
D02|553|dirties the drawings layer only;D03|252|E14-D09 owns any transition
D04H|103|dialog recipe (scale + fade);D07|21|never an auto-scroll
D07|216|one decorative flash from `color.surface.selected`;D07H|104|E14-D09 owns the curve
E05-D03|60|names only what animates;E05-D03|67|Dialog open / close;E05-D03|69|Value flash
E05-D03|70|Toast enter / exit;E05-D03|100|**MR-1;E05-D03|105|**HS-1 ;E05-D03|109|**HS-1b
E05-D03|117|**MR-3;E05-D03|226|a running transition completes on its clock
E05-D03|246|6.7 The chart engine;E14.json|675|except the snap indicator
flags.ts|4|readonly animate: boolean
flags.ts|34|With a flag off the effect snaps to its resting value
handle.ts|12|readonly colors:;types.ts|150|drawingChanged;types.ts|363|export interface Drawing
index.ts|1|Placeholder for render layers;m0-report.mjs|733|B8 (not in the matrix)
SUMMARY.md|9|**met** here is conservative evidence;SUMMARY.md|10|is **inconclusive**
keymap.json|251|chart.delete_drawing;keymap.json|266|chart.undo;keymap.json|275|chart.redo
popover.css|6|it appears at once (no enter fade);popover.css|67|Out over `fast` / `accelerate`
popover.css|82|the exit is a cut;run-proto.mjs|2|Usage: node;run-proto.mjs|52|Page.navigate
suppression-paths.json|7|layers/drawings;README.md|78|docs/design/<epic>/<ticket>.md
E08-D11|11|E08-D11-proto/motion-proto.html;E08-D11|39|No participants, no sessions
E05-D03|22|The seven motion primitives only;E05-D03|69|`motion.easing.accelerate`
E05-D03|106|the focused symbol and open positions first;E05-D03|109|In the light theme
E05-D03|121|One-shot rows start only on a state change, a user action
D02|521|armed, first time in session;D02|522|"Horizontal line tool on."
D02|523|"Horizontal line tool off.";D02|524|"Anchor 1 of 2 at 13:40, 64,012.5."
D02|526|"Horizontal line at 64,210.5 created on all BTCUSDT panes. Selected."
D02|530|"Selection cleared.";D02|534|"Trendline removed. Undo available."
D02|536|"200 drawings hidden." / "All drawings locked.";D02|723|motion: creation, selection
D04|299|`save-failed`;D04H|15|the popover's open / close is `16` §7's dialog recipe
D05H|15|E14-D09 owns motion;D06H|107|(E14-D09 owns motion
D07|21|| mark + ;D07|227|the restore flash is omitted;D07|313|**never moves the viewport**
D07|313|the row menu's **;D07|317|with the **"restored"** tag for 10 s
D07H|15|the restore flash `motion.duration.normal`"""
STAMP = "RULED (orchestrator, 2026-10-30, #2701 ledger addendum A row A28)"
WALK = "owner walkthrough: post-Done (#2701)"
PARTIAL = "Partial: PR 1 of 3"
# The ruled words, by ruling (R352 = #352 6510321645, R353 = #353 6511761951, A28 = #2701
# 6511768701); each stands in the spec, and in the saved copy given with --source.
RULING_PINS: dict[str, tuple[str, ...]] = {
    "R352": (
        "TP-13 `color.drawing.snap`",
        "the 10 px ring + value text vs the 8 px dot keeps the two apart by shape",
        (
            "the 8 / 10 / 24 px handle numbers and the 12 px magnet radius travel as "
            "`EngineTheme.metrics` (routed to E14-T04 #359)"
        ),
        "the engine card with the implementer's acknowledgement",
        "band `ChartEngine/DrawingToolOverlay`",
        "none by design; the pairs are E14-D09's (#353) and will append here",
    ),
    "R353": (
        "E05-D03 row 3, restored-row use (RULED #353 BQ-08)",
        (
            'a budget missed is "inconclusive" and the entry is then written in its minimal form '
            "(one property, ≤ `motion.duration.fast`) with the full form restored only if "
            "E14-T04's reference-machine B8 bench passes"
        ),
        "### 7.5 Drawing-kit motion (E14-D09)",
        WALK,
    ),
    "A28": (WALK, "No participant, timing or quote is invented."),
}
DNA_TEXT = {
    "DNA-5": "No drawing animates into existence or away.",
    "DNA-6": "The tree never scrolls smoothly to a coupled row.",
    "DNA-7": "A scale, interval or theme change re-projects every drawing in one frame.",
    "DNA-8": "An anchored VWAP's live update is a cut and not an undo step.",
}
DNA_IDS = ("DNA-1", "DNA-2", "DNA-3", "DNA-4")
DNA_ON = {
    "DNA-1": ("D9-02", "D9-09"),
    "DNA-4": ("D9-02", "D9-03", "D9-04", "D9-05", "D9-09"),
    "DNA-5": ("D9-10", "D9-11"),
    "DNA-6": ("D9-13",),
}
ROWS = tuple(f"D9-{i:02d}" for i in range(1, 14))
MOVING = frozenset({"D9-03", "D9-05", "D9-09"})
RULED_LAYER = {
    **{r: "canvas" for r in ("D9-02", "D9-03", "D9-04", "D9-05", "D9-06")},
    **{r: "DOM" for r in ("D9-01", "D9-12", "D9-13")},
    **{r: "canvas + DOM" for r in ("D9-07", "D9-08", "D9-09", "D9-10", "D9-11")},
}
D, E = "motion.duration.", "motion.easing."
RULED_TIMING: dict[str, tuple[str, ...]] = {
    "D9-03": (D + "fast", E + "decelerate"),
    "D9-05": (D + "normal", E + "standard"),
    "D9-09": (D + "slow", E + "standard", D + "normal", E + "accelerate"),  # tree: E05-D03 row 3
}
MOTION7 = frozenset(
    [D + x for x in ("instant", "fast", "normal", "slow")]
    + [E + x for x in ("standard", "decelerate", "accelerate")]
)
PROPOSED = frozenset({"color.drawing.snap", "color.drawing.handle.active"})  # R352 TP-13, TP-11
CUT_TIMING = "`motion.duration.instant` · `—`"
GL_FORMS = ("instance alpha", "scale uniform")
HZ, HS1_GAP_MS, MR1_MAX, HS1_CAP = 60, 500, 3, 20  # HS-1: 500 ms, 20 per frame; MR-1: 3 per 1 s
REGION, AREA_SHARE, BAND_PX, RING_START_PX, BYTES = (341, 256), 0.25, 4, 14, 4
DRAG_STOP = ("drag threshold", "to rest")  # DNA-4's stop rule on D9-05 and D9-09
BULK = 497  # D02's delete-all example ("497 drawings deleted")
BOARDS = tuple((f"{i:02d}", "dark") for i in range(1, 6)) + (("06", "light"),)  # 06 twins 03
BANNED_ROT13 = (
    "yrnx rkcbfrq olcnff rkcybvg nggnpx benpyr erirny haobhaqrq sybbq fgnyy nqivfbel TUFN "
    "cer-nhgu"
)
BANNED = codecs.decode(BANNED_ROT13, "rot13").split()
BANNED_WORD = re.compile(r"\b" + codecs.decode("qbf", "rot13") + r"\b", re.IGNORECASE)
DASHES = {"—", "-", "–", "n/a", "N/A"}
HOST = re.compile(
    r"\b[a-z0-9-]+(?:\.[a-z0-9-]+)*\.(?:com|net|org|io|dev|app|cloud)\b", re.IGNORECASE
)
UUID = re.compile(
    r"\b[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}\b", re.IGNORECASE
)


def git_show(rev: str, rel: str) -> str:
    out = subprocess.run(
        ["git", "-C", str(ROOT), "show", f"{rev}:{rel}"], capture_output=True, check=False
    )
    return out.stdout.decode("utf-8") if out.returncode == 0 else ""


def token_values(texts: list[str]) -> dict[str, Any]:
    values: dict[str, Any] = {}

    def walk(node: dict[str, Any], prefix: str) -> None:
        for k, v in node.items():
            if k.startswith("$") or not isinstance(v, dict):
                continue
            name = f"{prefix}.{k}" if prefix else k
            if "$value" in v:
                values[name] = v["$value"]
            else:
                walk(v, name)

    for text in texts:
        if text:
            walk(json.loads(text), "")
    return values


class Ctx(NamedTuple):
    """The texts the gates read; the self-test swaps `spec` for a mutated copy."""

    spec: str
    tool: str
    base: dict[str, str]
    tokens: dict[str, Any]
    bq_base: dict[str, str]
    e05_pin: str
    sources: dict[str, str]


class Result:
    def __init__(self) -> None:
        self.fails: list[str] = []
        self.warns: list[str] = []
        self.numbers: dict[str, object] = {}

    def fail(self, code: str, msg: str) -> None:
        self.fails.append(f"[{code}] {msg}")


def load_ctx(sources: dict[str, str]) -> Ctx:
    base = {k: git_show(BASE, p) for k, p in KEYS.items()}
    bq = {k: git_show(BQ_BASE, p) for k, p in KEYS.items()}
    tokens = token_values([git_show(BASE, p) for p in TOKEN_FILES])
    tool = Path(__file__).read_text(encoding="utf-8")
    e05 = git_show(E05_PIN, KEYS["E05-D03"])
    return Ctx(SPEC.read_text(encoding="utf-8"), tool, base, tokens, bq, e05, sources)


def flat(text: str) -> str:
    return " ".join(text.split())


def section(spec: str, num: int) -> str:
    """Section `num` of the spec: from its `## n.` heading to the next one outside a fence."""
    out: list[str] = []
    fenced = inside = False
    for line in spec.splitlines(keepends=True):
        if line.startswith("```"):
            fenced = not fenced
        if not fenced and re.match(r"## \d+\. ", line):
            inside = line.startswith(f"## {num}. ")
        if inside:
            out.append(line)
    return "".join(out)


def rows(sec: str) -> list[list[str]]:
    out = []
    for line in sec.splitlines():
        if line.startswith("|") and not re.match(r"^\|[\s:|-]+\|$", line):
            out.append([c.strip() for c in line.strip().strip("|").split("|")])
    return out[1:]  # drop the header


COLS = (
    "d9",
    "moment",
    "surface",
    "layer",
    "property",
    "fromto",
    "timing",
    "drag",
    "ac1",
    "reduce",
    "carrier",
    "cost",
    "rules",
    "source",
)


def table(spec: str) -> list[dict[str, str]]:
    first = section(spec, 2).split("\n\nWhat the three moving rows mean")[0]
    return [dict(zip(COLS, r, strict=False)) for r in rows(first)]


CITE = re.compile(r"`([A-Za-z0-9.-]+)`((?::\d+(?:-\d+)?)(?:, :\d+(?:-\d+)?)*)")
TOKEN = re.compile(r"`([a-z]+(?:\.[a-z0-9_-]+)+)`")


# --- G1: the table ----------------------------------------------------------------------------
def row_problem(row: dict[str, str]) -> str:
    rid = row.get("d9", "")
    if len(row) != len(COLS) or not all(row.get(c) for c in COLS):
        return "a cell is missing or empty"
    if row["carrier"] in DASHES or row["reduce"] in DASHES:
        return "the Carrier or the motion-reduce cell is a dash"
    if RULED_LAYER.get(rid) != row["layer"]:
        return f"layer {row['layer']!r}, ruled {RULED_LAYER.get(rid)!r}"
    if rid in MOVING:
        if not row["ac1"].startswith("carries:"):
            return "a moving row's AC 1 cell does not start 'carries:'"
        if row["reduce"].startswith("identical") or row["property"].startswith("none"):
            return "a moving row is written as a cut"
    else:
        cut = (
            row["property"].startswith("none")
            and row["timing"].startswith(CUT_TIMING)
            and row["reduce"].startswith("identical (a cut)")
            and row["ac1"].startswith("static is not worse:")
        )
        if not cut:
            return "a cut is not the instant pair, Property none, identical, 'static is not worse:'"
    if (row["drag"] == "yes") != (rid == "D9-03") or not row["drag"].startswith(("yes", "no")):
        return f"'during a drag' is {row['drag']!r}; only D9-03 runs during a drag"
    if rid in MOVING - {"D9-03"} and not all(w in row["drag"] for w in DRAG_STOP):
        return "a moving row does not cut to rest at the drag threshold (DNA-4)"
    if not CITE.search(row["source"]):
        return "the Source cell holds no cite"
    return ""


def gate_table(ctx: Ctx, r: Result) -> None:
    rs = table(ctx.spec)
    if tuple(x.get("d9") for x in rs) != ROWS:
        r.fail("G1-TABLE", f"rows {[x.get('d9') for x in rs]}, ruled D9-01 to D9-13 in order")
    for row in rs:
        if problem := row_problem(row):
            r.fail("G1-TABLE", f"{row.get('d9')}: {problem}")
    r.numbers["rows"] = len(rs)
    r.numbers["moving"] = sorted(x["d9"] for x in rs if x.get("ac1", "").startswith("carries:"))


# --- G2: tokens -------------------------------------------------------------------------------
def gate_token(ctx: Ctx, r: Result) -> None:
    groups = {n.split(".")[0] for n in ctx.tokens}
    named = {t for t in TOKEN.findall(ctx.spec) if t.split(".")[0] in groups}
    if missing := sorted(named - set(ctx.tokens) - PROPOSED):
        r.fail("G2-TOKEN", f"token names not in the token JSON at the base: {missing}")
    if extra := sorted(t for t in named if t.startswith("motion.") and t not in MOTION7):
        r.fail("G2-TOKEN", f"motion names outside the seven: {extra}")
    for row in table(ctx.spec):
        said = tuple(t for t in TOKEN.findall(row.get("timing", "")) if t.startswith("motion."))
        want = RULED_TIMING.get(row.get("d9", ""), (D + "instant",))
        if said != want:
            r.fail("G2-TOKEN", f"{row.get('d9')}: timing names {list(said)}, ruled {list(want)}")
    r.numbers["tokens_named"] = sorted(named)


# --- G3: properties and cost ------------------------------------------------------------------
def gate_property(ctx: Ctx, r: Result) -> None:
    for row in table(ctx.spec):
        rid, layer, cost = row.get("d9", ""), row.get("layer", ""), row.get("cost", "")
        prop = re.sub(r"\(the GL form of `\w+`\)", "", row.get("property", ""))
        css = {t for t in re.findall(r"`([a-z-]+)`", prop)}
        problem = ""
        if rid in MOVING:
            if "canvas" in layer and sum(prop.count(f) for f in GL_FORMS) != 1:
                problem = "a canvas half does not animate exactly one instance alpha or scale"
            elif "DOM" in layer and not css:
                problem = "a DOM half names no animated property"
            elif not css <= {"opacity", "transform"}:
                problem = f"a DOM half animates {sorted(css)}"
            elif "canvas" in layer and "+0 draw calls" not in cost:
                problem = "a moving canvas row does not cost '+0 draw calls'"
        if not problem and "canvas" in layer and "the drawings layer only" not in cost:
            problem = "a canvas row does not say 'the drawings layer only'"
        if not problem and "DOM" in layer and "no layout on the chart container" not in cost:
            problem = "a DOM row does not say 'no layout on the chart container'"
        if problem:
            r.fail("G3-PROPERTY", f"{rid}: {problem}")


# --- G4: the do-not-animate list --------------------------------------------------------------
QUOTE = re.compile(r'^- (DNA-\d): "(.+)"$', re.MULTILINE)


def gate_dna(ctx: Ctx, r: Result) -> None:
    lines = ctx.base["E14.json"].splitlines()
    body = lines[674] if len(lines) > 674 else ""
    sec3, rs = section(ctx.spec, 3), {x.get("d9"): x for x in table(ctx.spec)}
    found = QUOTE.findall(sec3)
    if tuple(q for q, _ in found) != DNA_IDS:
        r.fail("G4-DNA", f"quoted clauses {[q for q, _ in found]}, ruled {list(DNA_IDS)}")
    for qid, text in found:
        if text not in body:
            r.fail("G4-DNA", f"{qid} is not byte for byte in `E14.json`:675 at {BASE}")
    for dna, text in DNA_TEXT.items():
        if f"**{dna}. {text}**" not in sec3:
            r.fail("G4-DNA", f"{dna}'s pinned sentence is not in section 3")
    for dna, on in DNA_ON.items():
        if missing := [m for m in on if dna not in rs.get(m, {}).get("rules", "")]:
            r.fail("G4-DNA", f"{dna} is not applied on {missing}")
    r.numbers["dna"] = len(found) + sum(f"**{d}." in sec3 for d in DNA_TEXT)


# --- G5: the arithmetic -----------------------------------------------------------------------
def trunc(x: float, nd: int) -> str:
    v = math.floor(x * 10**nd + 1e-9) / 10**nd
    return f"{v:,.{nd}f}".replace(",", " ")


def expected_figures(ctx: Ctx) -> tuple[dict[str, tuple[str, ...]], list[str]]:
    """Section 6's table cells per moving row, and the sentences its prose must carry."""
    ms = {t: int(str(ctx.tokens.get(t, "0ms")).removesuffix("ms")) for t in MOTION7 if D in t}
    cells: dict[str, tuple[str, ...]] = {}
    for rid in sorted(MOVING):
        dur = RULED_TIMING[rid][0]
        many = rid == "D9-09"  # the bulk restore: up to HS-1's per-frame cap
        inst = f"≤ {HS1_CAP}" if many else "1"
        byt = f"≤ {HS1_CAP * BYTES}" if many else str(BYTES)
        cells[rid] = (f"`{dur}`", str(ms[dur] * HZ // 1000), inst, byt, "+0")
    w, h = REGION
    area, bound = w * h, w * h * AREA_SHARE
    diag = math.hypot(w, h)
    band = BAND_PX * diag
    fit = int(bound // band)
    a, b = w / 2, h / 2
    ellipse = math.pi * (3 * (a + b) - math.sqrt((3 * a + b) * (a + 3 * b)))  # Ramanujan
    outlines = {"rect": 2.0 * (w + h), "ellipse": ellipse}
    fits = {k: int(bound // (BAND_PX * v)) for k, v in outlines.items()}
    ring = math.pi * (RING_START_PX / 2) ** 2
    starts = math.ceil(1000 / HS1_GAP_MS)  # starts at 0, gap, 2*gap ... inside [0, 1000)
    shown, share = min(BULK, HS1_CAP), round(AREA_SHARE * 100)
    sel, rst = ms[RULED_TIMING["D9-05"][0]], ms[RULED_TIMING["D9-09"][0]]
    sentences = [
        f"At {HZ} Hz one frame is {trunc(1000 / HZ, 1)} ms.",
        f"any half-open 1 000 ms window holds at most {starts} starts, under MR-1's {MR1_MAX}.",
        f"A settle lasts {ms[D + 'fast']} ms, so it always ends before the next start is allowed",
        f"covers {trunc(ring, 1)} px², {trunc(ring / area * 100, 2)} % of a {w} × {h} px region.",
        (
            f"D9-05 lasts {sel} ms and D9-09 {rst} ms, both under the {HS1_GAP_MS} ms gap, so a "
            "start that lands on a running entry is always drawn at rest."
        ),
        f"window holds at most {starts} starts per element, under MR-1's {MR1_MAX}.",
        (
            f"A bulk undo of {BULK} drawings emphasises at most {shown} and leaves at least "
            f"{BULK - shown} to"
        ),
        f"({trunc(area, 0)} px²) to {trunc(bound, 0)} px² of emphasised area ({share} %).",
        (
            f"diagonal ({trunc(diag, 1)} px): a line halo covers at most {trunc(band, 1)} px², so "
            f"{fit} fit ({trunc(fit * band, 1)} px²) and a {fit + 1}th does not "
            f"({trunc((fit + 1) * band, 1)} px²); {HS1_CAP} would cover "
            f"{trunc(HS1_CAP * band, 1)} px²."
        ),
    ]
    for kind, length in outlines.items():
        n, hb = fits[kind], BAND_PX * length
        sentences.append(
            f"{trunc(length, 1)} px outline: its halo covers {trunc(hb, 1)} px², so {n} fit "
            f"({trunc(n * hb, 1)} px²) and a {n + 1}th does not ({trunc((n + 1) * hb, 1)} px²)."
        )
    held = max(sel, rst) < HS1_GAP_MS and all(n < fit for n in fits.values())
    if starts > MR1_MAX or ms[D + "fast"] >= HS1_GAP_MS or fit >= HS1_CAP or not held:
        sentences.append("(the rules no longer hold: a start cap, a settle or the area cap)")
    return cells, sentences


def gate_arith(ctx: Ctx, r: Result) -> None:
    sec6 = section(ctx.spec, 6)
    cells, sentences = expected_figures(ctx)
    got = {x[0]: tuple(x[1:6]) for x in rows(sec6) if x}
    for rid, want in cells.items():
        if got.get(rid) != want:
            r.fail("G5-ARITH", f"{rid}: section 6 reads {got.get(rid)}, recomputed {want}")
    text = flat(sec6).replace("\\", "")
    for s in sentences:
        if s not in text:
            r.fail("G5-ARITH", f"section 6 does not carry the recomputed {s!r}")
    r.numbers["arith"] = {k: list(v[1:]) for k, v in cells.items()}


# --- G6: the ruled words ----------------------------------------------------------------------
def gate_ruled(ctx: Ctx, r: Result) -> None:
    text = flat(ctx.spec)
    for what in (STAMP, WALK, PARTIAL):
        if what not in text:
            r.fail("G6-RULED", f"{what!r} is not in the spec")
    for name, pins in RULING_PINS.items():
        for pin in pins:
            if flat(pin) not in text:
                r.fail("G6-RULED", f"{name}'s words {pin[:48]!r}… are not in the spec")
            if name in ctx.sources and flat(pin) not in flat(ctx.sources[name]):
                r.fail("G6-RULED", f"{name}'s words {pin[:48]!r}… are not in its saved copy")
    if missing := [n for n in (1, 8) if STAMP not in flat(section(ctx.spec, n))]:
        r.fail("G6-RULED", f"A28's stamp is not in section(s) {missing}")
    open_walk = r"walkthrough[^.]{0,60}pending|pending[^.]{0,60}walkthrough"
    if re.search(open_walk, text, re.IGNORECASE):
        r.fail("G6-RULED", "the owner walkthrough is written as pending")
    r.numbers["ruling_pins"] = sum(len(p) for p in RULING_PINS.values())
    r.numbers["sources_checked"] = sorted(ctx.sources)


# --- G7: cites --------------------------------------------------------------------------------
def gate_cite(ctx: Ctx, r: Result) -> None:
    cited: list[tuple[str, int, int]] = []
    body = re.sub(r"```.*?```", "", ctx.spec, flags=re.DOTALL)
    for key, spans in CITE.findall(body):
        if key not in KEYS:
            r.fail("G7-CITE", f"`{key}`{spans}: an undeclared key")
            continue
        size = len(ctx.base[key].splitlines())
        for a, b in re.findall(r":(\d+)(?:-(\d+))?", spans):
            lo, hi = int(a), int(b or a)
            cited.append((key, lo, hi))
            if not 0 < lo <= hi <= size:
                r.fail("G7-CITE", f"`{key}`:{a}{'-' + b if b else ''} is outside the file")
            if key == FORBIDDEN[0] and lo <= FORBIDDEN[2] and hi >= FORBIDDEN[1]:
                r.fail("G7-CITE", f"`{key}`:{a}: a cite into `16` section 7's recipe lines")
    pins = [p.split("|", 2) for p in CITE_PINS.replace("\n", ";").split(";")]
    for key, line, words in pins:
        lines = ctx.base[key].splitlines()
        if int(line) > len(lines) or words not in lines[int(line) - 1]:
            r.fail("G7-CITE", f"`{key}`:{line} no longer carries {words!r}")
    at = {(k, int(n)) for k, n, _ in pins}
    uncited = sorted(
        {f"{k}:{n}" for k, n in at if not any(c == k and a <= n <= b for c, a, b in cited)}
    )
    spans = {
        (k, a, b)
        for k, a, b in cited
        if 0 < a <= b <= len(ctx.base[k].splitlines())
        and not (k == FORBIDDEN[0] and a <= FORBIDDEN[2] and b >= FORBIDDEN[1])
    }
    unpinned = sorted(
        f"{k}:{a}-{b}" for k, a, b in spans if not any(p == k and a <= n <= b for p, n in at)
    )
    if uncited or unpinned:
        r.fail(
            "G7-CITE",
            f"pins and cites disagree: pinned, not cited {uncited}; cited, not pinned {unpinned}",
        )
    moved = [k for k, v in ctx.bq_base.items() if v and v != ctx.base[k]]
    if moved:
        r.fail("G7-CITE", f"cited files changed between {BQ_BASE} and {BASE}: {moved}")
    if ctx.e05_pin and ctx.e05_pin != ctx.base["E05-D03"]:
        r.fail("G7-CITE", f"E05-D03 at {BASE} differs from its merge commit {E05_PIN}")
    r.numbers["cites"] = len(cited)
    r.numbers["pins"] = len(pins)
    r.numbers["spans"] = len(spans)
    r.numbers["bq_base"] = (
        f"{BQ_BASE} -> {BASE}: identical" if any(ctx.bq_base.values()) else "not readable"
    )


# --- G8, G9: hygiene and boards ---------------------------------------------------------------
def gate_hygiene(ctx: Ctx, r: Result) -> None:
    for name, text in (("the spec", ctx.spec), ("the tool", ctx.tool)):
        low = text.lower()
        for word in BANNED:
            if word.lower() in low:
                r.fail("G8-HYGIENE", f"{name}: a word from the public-text list: {word!r}")
        if BANNED_WORD.search(text):
            r.fail("G8-HYGIENE", f"{name}: a word from the public-text list")
        if host := HOST.search(text):
            r.fail("G8-HYGIENE", f"{name}: a host name {host.group(0)!r}")
        if UUID.search(text):
            r.fail("G8-HYGIENE", f"{name}: an id in the uuid form")
    for pat, what in (
        (r"/home/|/tmp/|/mnt/|[A-Z]:\\", "a local path"),
        (r"https?://", "a host"),
        (r"\b(?:close[sd]?|fix(?:e[sd])?|resolve[sd]?) #\d", "a closing keyword"),
        (r"approval (?:pending|needed|required)|pending (?:owner )?approval", "approval pending"),
    ):
        if re.search(pat, ctx.spec, re.IGNORECASE):
            r.fail("G8-HYGIENE", what)


def gate_boards(ctx: Ctx, r: Result) -> None:
    bs = rows(section(ctx.spec, 10))
    for i, b in enumerate(bs):
        m = re.fullmatch(r"`E14-D09 / (\d\d) ([a-z0-9-]+)`", b[1] if len(b) > 1 else "")
        exp = f"`docs/design/E14/img/E14-D09-{m.group(1)}-{m.group(2)}.png`" if m else ""
        no, theme = BOARDS[i] if i < len(BOARDS) else ("", "")
        ok = m and len(b) == 6 and b[0] == m.group(1) == no and b[2] == exp
        if not ok or b[3] != theme or b[5] != "PENDING (PR 3)":
            r.fail("G9-BOARDS", f"board row {b[:2]}: name, export, theme or status off the pattern")
    if len(bs) != len(BOARDS):
        r.fail("G9-BOARDS", f"{len(bs)} boards (ruled {len(BOARDS)}: five dark, one light twin)")
    r.numbers["boards"] = len(bs)


GATE_FNS: tuple[tuple[str, Callable[[Ctx, Result], None]], ...] = (
    ("G1-TABLE", gate_table),
    ("G2-TOKEN", gate_token),
    ("G3-PROPERTY", gate_property),
    ("G4-DNA", gate_dna),
    ("G5-ARITH", gate_arith),
    ("G6-RULED", gate_ruled),
    ("G7-CITE", gate_cite),
    ("G8-HYGIENE", gate_hygiene),
    ("G9-BOARDS", gate_boards),
)


def run(ctx: Ctx) -> Result:
    r = Result()
    for _, fn in GATE_FNS:
        fn(ctx, r)
    return r


# --- self-test --------------------------------------------------------------------------------
def sub(old: str, new: str) -> Callable[[Ctx], Ctx]:
    return lambda ctx: ctx._replace(spec=ctx.spec.replace(old, new, 1))


def regex(pattern: str, repl: str) -> Callable[[Ctx], Ctx]:
    return lambda ctx: ctx._replace(
        spec=re.sub(pattern, repl, ctx.spec, count=1, flags=re.MULTILINE)
    )


MUTATIONS: tuple[tuple[str, Callable[[Ctx], Ctx]], ...] = (
    ("G1-TABLE", regex(r"^(\| D9-06 .*?)static is not worse:", r"\1static is fine:")),
    (
        "G2-TOKEN",
        regex(r"^(\| D9-05 .*?)`motion\.duration\.normal` · ", r"\1`motion.duration.slow` · "),
    ),
    ("G3-PROPERTY", regex(r"^(\| D9-03 .*?)\+0 draw calls", r"\1+1 draw call")),
    ("G4-DNA", sub('"drag never has inertia"', '"drag never has momentum"')),
    ("G5-ARITH", regex(r"^(\| D9-05 +\| `motion\.duration\.normal` +\| )12 ", r"\g<1>13 ")),
    ("G6-RULED", lambda ctx: ctx._replace(spec=ctx.spec.replace(PARTIAL, "Partial: PR 1 of 2"))),
    ("G7-CITE", sub("`m0-report.mjs`:733;", "`m0-report.mjs`:9733;")),
    ("G8-HYGIENE", sub("(a spec cannot split from its tool;", "(a spec cannot split, /tmp/x;")),
    ("G9-BOARDS", regex(r"^(\| 06 .*?\| )light( +\|)", r"\1dark \2")),
)

# Probes: edits a weaker gate would let through; each must add one FAIL.
PROBES: tuple[tuple[str, Callable[[Ctx], Ctx]], ...] = (
    ("G1-TABLE", regex(r"^(\| D9-13 (?:\|[^|]+){6}\| )no ", r"\1yes ")),
    ("G1-TABLE", regex(r"^(\| D9-05 .*?)carries:", r"\1static is not worse:")),
    ("G2-TOKEN", sub("`color.surface.selected` overlay", "`color.surface.chosen` overlay")),
    ("G3-PROPERTY", regex(r"^(\| D9-05 .*?)instance alpha", r"\1instance alpha, scale uniform")),
    ("G4-DNA", regex(r"^(\| D9-13 .*?\| )DNA-6( +\|)", r"\1MR-3 \2")),
    ("G4-DNA", sub("HS-1; HS-1b; DNA-1; DNA-4; CR-1", "HS-1; HS-1b; DNA-1; CR-1")),
    (
        "G1-TABLE",
        sub(
            "no: a press that crosses D02's drag threshold cuts the halo and the overlay to rest",
            "no",
        ),
    ),
    ("G5-ARITH", sub("at most 2 starts", "at most 3 starts")),
    ("G6-RULED", sub("- **Hand-offs.**", "- **Hand-offs.** The owner walkthrough stays pending.")),
    ("G7-CITE", sub("(`14`:954)", "(`14`:954; `16`:182)")),
    ("G7-CITE", sub("`D02`:521-523", "`D02`:100-101")),
    ("G6-RULED", sub(STAMP, "RULED (orchestrator, 2026-10-30)")),
    ("G5-ARITH", sub("so 4 fit", "so 5 fit")),
    (
        "G8-HYGIENE",
        sub("- **Hand-offs.**", "- **Hand-offs.** " + codecs.decode("Nggnpx", "rot13") + "."),
    ),
)


def digests() -> dict[str, str]:
    return {str(p): hashlib.sha256(p.read_bytes()).hexdigest() for p in (SPEC, Path(__file__))}


def self_test(ctx: Ctx, base: Result) -> list[str]:
    bad: list[str] = []
    before, spec_sha = digests(), hashlib.sha256(ctx.spec.encode()).hexdigest()
    covered = {code for code, _ in MUTATIONS}
    bad += [f"self-test: gate {g} has no mutation" for g, _ in GATE_FNS if g not in covered]
    for code, fn in (*MUTATIONS, *PROBES):
        mutated = fn(ctx)
        if mutated.spec == ctx.spec:
            bad.append(f"self-test {code}: the mutation did not apply")
            continue
        new = sorted(set(run(mutated).fails) - set(base.fails))
        if len(new) != 1 or not new[0].startswith(f"[{code}]"):
            bad.append(f"self-test {code}: expected one new [{code}] FAIL, got {new[:3]}")
    again = run(ctx)
    if hashlib.sha256(ctx.spec.encode()).hexdigest() != spec_sha:
        bad.append("self-test: the spec text in memory changed")
    if again.fails != base.fails or again.numbers != base.numbers:
        bad.append("self-test: a re-run does not reproduce the base result")
    if digests() != before:
        bad.append("self-test: a file on disk changed")
    return bad


def parse_sources(items: list[str]) -> dict[str, str]:
    out: dict[str, str] = {}
    for item in items:
        name, _, path = item.partition("=")
        if name not in RULING_PINS or not path:
            raise SystemExit(f"--source takes NAME=FILE with NAME one of {sorted(RULING_PINS)}")
        out[name] = Path(path).read_text(encoding="utf-8")
    return out


def main(argv: list[str]) -> int:
    ap = argparse.ArgumentParser(description=(__doc__ or "").splitlines()[0])
    ap.add_argument("--check", action="store_true", help="exit 1 on any FAIL")
    ap.add_argument("--json", action="store_true", help="print the numbers and findings as JSON")
    ap.add_argument("--self-test", "--selftest", action="store_true", help="the mutation self-test")
    ap.add_argument("--source", action="append", default=[], help="NAME=FILE, a saved ruling")
    args = ap.parse_args(argv)
    ctx = load_ctx(parse_sources(args.source))
    if not all(ctx.base.values()) or not ctx.tokens:
        missing = [k for k, v in ctx.base.items() if not v]
        print(f"FAIL [G7-CITE] cannot read {missing or 'the tokens'} at {BASE} (fetch first)")
        return 1
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
        n = res.numbers
        out.append(
            f"rows {n.get('rows')} (moving {n.get('moving')}); DNA {n.get('dna')}; cites "
            f"{n.get('cites')} ({n.get('spans')} distinct spans, {n.get('pins')} pins); ruling "
            f"pins {n.get('ruling_pins')} "
            f"(saved copies {n.get('sources_checked')}); boards {n.get('boards')}; "
            f"{n.get('bq_base')}"
        )
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
