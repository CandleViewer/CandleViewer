"""E22-D04 (#577) audit: the entry table, the do-not-animate list, the announcement policy, the
focus table, the review's F rows and the cites.

Stdlib only, offline (`python3 -I -B`). It reads the spec from the working tree and every cited
file and the token JSON AS TEXT at the pinned base with `git show`; `contrast_check.py`'s
luminance is imported by function. Eleven gates, each FAIL led by its code:

- [G1-TABLE] section 2 holds D4-01 to D4-18 in order, every cell filled, no Carrier or reduce cell
  a dash, each row's layer the ruled one (RULED_LAYER); the owned rows (OWNED) read the cut form:
  Property `none`, the instant pair, "identical (a cut)", "static is not worse:"; the cited rows
  (CITED) read "cited:" in each of their CITED_COLS; every Source cell holds a cite.
- [G2-TOKEN] every backticked name in a token group exists in the token JSON at the base or is
  D03's PROPOSED `opacity.bubble.aged`; no motion token but the seven; each row's timing cell
  names its ruled motion tokens in order (RULED_TIMING; an owned row names the instant one only).
- [G3-PROPERTY] an owned canvas row costs "+0 draw calls" and "the bubbles layer only"; an owned
  row with a DOM layer says "no layout on the chart container".
- [G4-DNA] DNA-1 and DNA-2 stand byte for byte in `E22.json`:134 at the base; DNA-3 to DNA-7
  stand with their pinned sentences; each DNA id in DNA_ON is applied on its rows.
- [G5-ARITH] the announcement simulation (60 s at 2 000 prints/s, seeded, the A38 throttle:
  at most 12 writes, every one whale-class, none closer than 5 000 ms; and again with a row
  focused over SIM_HOLD: no write inside it, none closer than 5 000 ms), the tier-2 flash
  classification per theme from D03's resolved values, the burst count, the frame, byte and
  lateness figures, each recomputed and found in the spec.
- [G6-RULED] every A37, A38 and A28-applied stamp at every site (SITE_ROWS, SITE_LEADS) in its
  form and with its date, and no stamp elsewhere; the walkthrough line, never written as pending;
  R577's and the ledger rows' words (RULING_PINS), and with `--source NAME=FILE` in that saved
  copy too; AN-01's, AN-02's and AN-08's Gate cells read A38's suppression (AN_GATES).
- [G7-CITE] every `KEY`:line cite resolves to a declared key and an existing range at the base;
  pins and cited spans match both ways, so a cite moved to other lines fails; every cited span
  reads the same at the BQ list's base, bar the files re-read at the base (REREAD).
- [G8-HYGIENE] no local path, host, closing keyword or id in the spec, and no word or substring
  on the lane's public-text list or a host name in the spec or this tool.
- [G9-FROW] section 11's F rows: severity, owner (a spec and an area), target, `G-T2` only on a
  gated row, a cite in the merged sentence; the heading's counts and marker; the verdicts of
  sections 10.1 and 10.2 in R-3's vocabulary, each `at risk` with its path or a Major row, each
  `non-compliant` with a Blocking row; the cross-walk holds every SC in CROSSWALK.
- [G10-ASSERT] every D4, DNA, AN, KR, FP, layer-1 and F row names one assertion id with a
  statement, no id twice; section 14's counts per consumer match.
- [G11-BOARDS] "BOARDS: none, by A37" stands as section 0's own bold statement and nothing refers
  to a board, an export or a page.

`--json` prints the numbers and findings; `--check` exits 1 on any FAIL (0 FAIL, 0 WARN is the bar);
`--self-test` applies one mutation per gate (MUTATIONS) and the probes (PROBES) to an in-memory copy
of the spec and passes only when each adds exactly one new FAIL with its gate's code, a re-run on
the unmutated text reproduces the base result and no file on disk changed.

Usage: python3 -I -B docs/design/_tools/e22_d04_motion_a11y_audit.py [--check] [--json]
       [--self-test] [--source R577=FILE] [--source LA=FILE]
"""

from __future__ import annotations

import argparse
import codecs
import hashlib
import importlib.util
import itertools
import json
import math
import random
import re
import subprocess
import sys
from collections.abc import Callable
from pathlib import Path
from types import ModuleType
from typing import Any, NamedTuple

ROOT = Path(__file__).resolve().parents[3]
TOOLS = ROOT / "docs" / "design" / "_tools"
SPEC = ROOT / "docs" / "design" / "E22" / "E22-D04.md"
BASE = "595be3eff9"  # origin/main; every cite is read here
BQ_BASE = "7e23e4667c"  # where the BQ list (6516622879) read every cite
REREAD = {"E05-D03"}  # changed by its PR 2 (#5036) after BQ_BASE; cited by id, lines re-read
KEYS = {
    "05": "docs/plan/05-accessibility-standard.md",
    "06": "docs/plan/06-performance-and-load-standard.md",
    "11": "docs/plan/11-user-stories.md",
    "14": "docs/plan/14-screens-catalogue.md",
    "15": "docs/plan/15-component-catalogue.md",
    "21": "docs/plan/21-database-schema.md",
    "22": "docs/plan/22-api-openapi.yaml",
    "26": "docs/plan/26-chart-engine-design.md",
    "D02": "docs/design/E22/E22-D02.md",
    "D03": "docs/design/E22/E22-D03.md",
    "D03H": "docs/design/E22/E22-D03-handoff.md",
    "memo": "docs/design/research/e22-tape-reading.md",
    "E05-D03": "docs/design/E05/E05-D03.md",
    "E06-D03": "docs/design/E06/E06-D03.md",
    "E11-D06": "docs/design/E11/E11-D06.md",
    "E22.json": "docs/plan/backlog/E22.json",
    "flags.ts": "packages/chart-engine/src/core/flags.ts",
    "types.ts": "packages/chart-engine/src/api/types.ts",
    "limits.py": "services/api/candleviewer/orderflow/limits.py",
    "model.ts": "apps/web/src/features/a11y-preferences/model.ts",
    "popover.css": "packages/ui/src/components/popover.css",
    "AGENTS.md": "AGENTS.md",
    "CONSTITUTION.md": "CONSTITUTION.md",
}
TOKEN_FILES = (
    "packages/ui/tokens/primitives.tokens.json",
    "packages/ui/tokens/semantic-dark.tokens.json",
)
# key|line|words that must stand on that line at the base (the load-bearing cites), split on ' ¦ '
CITE_PINS = """\
05|55|Cycle timeframe ¦ 05|56|`F` / `H` / `P` ¦ 05|96|**Focus is never silently stolen**
05|99|Focus Not Obscured ¦ 05|100|SC 2.5.8 (Target Size, Minimum, AA) ¦ 05|131|200% browser/OS zoom
05|140|"canvas control surrogate" pattern ¦ 05|147|default 1 update / 2s per field
05|149|a master "reduce announcements" toggle ¦ 05|206|big-trade-bubble pop/scale-in
05|206|a single low-amplitude cross-fade ¦ 05|207|remain functional
05|208|No content flashes more than 3 times per second ¦ 06|25|≤16.6ms/frame (60fps)
06|91|Coalesce big-trade-bubble/CVD/indicator pane redraws to every 2nd frame
11|2189|accessible as a live-region-throttled table
14|1256|opt-in polite announcements for whale prints only ¦ 14|1262|**Motion spec:**
14|2410|screen-reader verbosity for the tape ¦ 15|1286|### CMP-112 BigTradeBubble
15|1290|"Big sell, 42,000 USDT, 65,410, 14:32:01" ¦ 21|3606|st_key_fmt ¦ 22|22233|accessibility:
22|22243|verbosity: { type: string, enum: [low, normal, high] }
26|148|bubble clustering (ruling BQ-S5; `06` names bubbles in rung 3)
26|326|Radius by notional, alpha by age ¦ AGENTS.md|455|(rAF/`bufferTime`) before it touches React
CONSTITUTION.md|207|**C-2.20 Hot paths are never statecharts.** ¦ D02|70|motion otherwise E22-D04's
D02|101|Tier 2 ('whale', ≥ 4× ¦ D02|123|**Hard paused** ¦ D02|124|**Resumed**
D02|125|**Click-to-locate** ¦ D02|127|**Stale T1** ¦ D02|141|**Paused, buffer full**
D02|167|so the list never resumes under a focused row ¦ D02|171|live → soft paused
D02|174|live → scroll paused ¦ D02|175|scroll paused → live ¦ D02|176|any → hard paused
D02|178|→ focus paused ¦ D02|181|the count ticks as a text swap ¦ D02|182|resume insertion
D02|184|paused (any) → paused, buffer full ¦ D02|249|**3.0 / 10.2 / 14.1 / 19.7 / 24.0 px
D02|251|**D24 alpha by age** ¦ D02|251|appear is a 0 ms flip, identical under reduced motion
D02|262|`Enter` on a mirror node
D02|279|so at r 3 px only the row, the tooltip and the mirror carry it
D02|287|header controls → status-row buttons ¦ D02|290|**Jump to live**
D02|291|locate on synced charts ¦ D02|292|innermost cancel ¦ D02|295|`Shift+F10` / `Menu`
D02|301|| K15 | ¦ D02|309|The a11y tree ¦ D02|313|"3 whale sells in 5 s, largest 410k at 64,012.0"
D02|314|on-demand summary ¦ D02|315|"Resumed, 412 prints inserted" ¦ D02|317|the chip is visible; the list stops
D02|321|over-threshold strip ¦ D02|322|"Filter applied: 2 filters active"
D02|325|the readout, the buffered count, every row arrival
D02|327|E22-D04 owns the announcement policy
D02|370|N rows per rAF in one fragment write, the readout at ≤ 2 Hz
D02|348|(tooltip "Side (taker): Buy / Sell") ¦ D02|412|**Contradictions — inherited from the memo ¦ D02|416|"live-region-throttled table"
D02|432|the pulse is 0 (E22-D04) ¦ D02|456|| D02-C14 | ¦ D02|479|| D02-G1 | ¦ D02|481|| D02-G3 |
D02|485|| D02-G7 | ¦ D02|498|≤1 whale announcement per 5 s is tolerable
D03|202|**aged = the PROPOSED token `opacity.bubble.aged` = 0.8**
D03|253|One instanced SDF-disc draw call for every visible mark
D03|269|The whale announcement policy, the throttle and the opt-in are E22-D04's
D03|315|`.raised` #161B22 / #EDEFF2 / #161B22 ¦ D03|319|- **Simulated (dark
D03|331|`ageBands` (the fresh / aged boundary, E22-D04's value)
D03|338|0 ms flip — **no pop, no scale-in** ¦ D03|339|the boundary's value is E22-D04's
D03|340|capped label ↔ cap outline ¦ D03|342|stale dimming of the pane
D03|344|tooltip show / hide ¦ D03|345|legend eye toggle; scale switch ¦ D03|348|crosshair jump
D03|349|**0 flashes** ¦ D03|423|| D03-C3  | ¦ D03|451|| D03-Q2 |
D03H|154|the boundary is `BubbleOptions.ageBands` (E22-D04)
E05-D03|22|The seven motion primitives only ¦ E05-D03|62|Every reduce cell is `none`
E05-D03|83|**One rule.** Every reduce cell in §2 is `none`. ¦ E05-D03|100|**MR-1
E05-D03|109|**HS-1b ¦ E05-D03|118|**MR-3 ¦ E05-D03|168||ΔL| ≥ 0.1 with the darker state below 0.80
E05-D03|227|a running transition completes on its clock ¦ E05-D03|247|### 6.7 The chart engine
E06-D03|105|**D5 Live-region policy.** ¦ E11-D06|89|**Stale dimming:**
E22.json|134|"body": "## Context ¦ flags.ts|4|readonly animate: boolean
flags.ts|34|With a flag off the effect snaps to its resting value
limits.py|30|VISIBLE_BUBBLES_MAX: Final = 5000 ¦ limits.py|31|BUBBLE_FLASH_MAX_HZ: Final = 3
memo|89|| F22 | ¦ memo|91|Nothing on the tape may flash ¦ memo|260|at ≤2 Hz
memo|290|0 ms, in place; no slide, no flash; tier emphasis persistent ¦ memo|291|| Reduced motion
memo|389|| C16 | ¦ memo|390|"whale-print emphasis pulse"
model.ts|87|export function shouldAnnounce( ¦ model.ts|93|p.verbosity === "low") return false
popover.css|6|it appears at once (no enter fade) ¦ popover.css|67|Out over `fast` / `accelerate`
popover.css|82|the exit is a cut ¦ types.ts|280|export interface BubbleOptions {
types.ts|281|minSizeQty: number ¦ types.ts|300|export interface BubbleData {"""
STAMPS = {
    "A37": "RULED (orchestrator, 2026-10-30, #2701 ledger addendum A row A37)",
    "A38": "RULED (orchestrator, 2026-10-30, #2701 ledger addendum A row A38)",
    "A28": "RULED (orchestrator, 2026-10-30, #577 ruling — A28 applied)",
}
# any stamp but the ruling of record's own "RULED (orchestrator, 2026-10-30, R577)"
STAMP_RE = re.compile(r"RULED \(orchestrator, (?!2026-10-30, R577\))[^)]*\)")
# every stamp site: a table row by its opening cell, or a paragraph by the words before the stamp
SITE_ROWS = {
    "| BQ-04 ": "A37",
    "| BQ-09 ": "A38",
    "| BQ-17 ": "A28",
    "| C-1 ": "A37",
    "| C-2 ": "A37",
    "| C-7 ": "A37",
    "| A-1 ": "A37",
}
SITE_LEADS = {"Every cut is ": "A37", "The policy is ": "A38", "The sign-off is ": "A28"}
WALK = "owner walkthrough: post-Done (#2701)"
# A38's gates, per announcement row's Gate cell (section 7): the suppression may not be weakened
AN_GATES = {
    "AN-01": "the opt-in on; no tape row focused; `verbosity` not `low`",
    "AN-02": "as AN-01",
    "AN-08": "suppressed: a tape row focused, or `verbosity` `low`; `announce_prices` not read",
}
# The ruled words, by ruling (R577 = #577 6516721939; LA = the #2701 ledger addendum A rows A37 and
# A38, 6516702193); each stands in the spec, and in the saved copy given with --source. Compared
# case-blind with backticks and bold marks removed.
RULING_PINS: dict[str, tuple[str, ...]] = {
    "R577": (
        "row owned by this ticket moves",
        "insertion-animation threshold = 0 prints / s — no insertion animation at any rate",
        "60 s after `ts_event` on the engine's data clock",
        "`ageBands: { freshMs: 60000 }`",
        "throttle 5 s, half-open, leading + trailing",
        "suppressed while a tape row holds focus and while `verbosity` is `low`",
        "`announce_prices` does not gate whales",
        "the focused print is never evicted while focused",
        "focus never sits on a moving row",
        "no prototype while A37 stands",
        "the prototype is not the engine",
        "BOARDS: none, by A37",
        "not yet decidable — routed to E22-Q04 (#754)",
        "no in-motion review while A37 stands",
        "no participant, timing or quote",
        WALK,
    ),
    "LA": (
        "Tape and bubble motion is cuts only (C17 closed).",
        "bubble appears as a 0 ms flip in both modes",
        "fresh 1.0 → aged `opacity.bubble.aged` 0.8 at the boundary",
        "no insertion animation at any rate",
        "no boards and no new Penpot page",
        "whale prints only",
        "opt-in, off by default",
        "the latest window replaces, nothing queues",
        "Announce whale prints (tape)",
        "with announcements on, follow the tape for one minute — what did you hear?",
    ),
}
DNA_TEXT = {
    "DNA-3": "Nothing on the tape or the bubble overlay flashes.",
    "DNA-4": "A resume inserts the buffered prints; it never replays them.",
    "DNA-5": "The viewport never scrolls smoothly.",
    "DNA-6": "No bubble scales, pops or eases its radius or position.",
    "DNA-7": "A counter never counts up; it swaps its text at ≤ 2 Hz.",
}
DNA_IDS = ("DNA-1", "DNA-2")
DNA_ON = {
    "DNA-1": ("D4-01",),
    "DNA-2": ("D4-01", "D4-02", "D4-03", "D4-12"),
    "DNA-3": ("D4-01", "D4-02", "D4-03", "D4-11", "D4-14"),
    "DNA-4": ("D4-05",),
    "DNA-5": ("D4-06",),
    "DNA-6": ("D4-11", "D4-12", "D4-13"),
    "DNA-7": ("D4-04", "D4-07"),
}
ROWS = tuple(f"D4-{i:02d}" for i in range(1, 19))
OWNED = frozenset(ROWS[:14])
CITED = frozenset(ROWS[14:])
RULED_LAYER = {
    **{r: "DOM" for r in ROWS[:10]},
    **{r: "canvas" for r in ("D4-11", "D4-12", "D4-14", "D4-15", "D4-17")},
    "D4-13": "canvas + DOM",
    "D4-16": "DOM",
    "D4-18": "DOM",
}
D, E = "motion.duration.", "motion.easing."
RULED_TIMING: dict[str, tuple[str, ...]] = {
    "D4-15": (D + "normal", E + "standard"),  # E11-D06 D13
    "D4-16": (D + "fast",),  # CMP-197
    "D4-17": (),  # E11-D06's crosshair, no token named
    "D4-18": (D + "fast", E + "accelerate"),  # CMP-017's shipped exit
}
MOTION7 = frozenset(
    [D + x for x in ("instant", "fast", "normal", "slow")]
    + [E + x for x in ("standard", "decelerate", "accelerate")]
)
PROPOSED = frozenset({"opacity.bubble.aged"})  # D03 CR-1
CUT_TIMING = "`motion.duration.instant` · `—`"
CITED_COLS = ("property", "fromto", "timing", "ac1", "reduce", "cost")
DASHES = {"—", "-", "–", "n/a", "N/A"}
# the announcement simulation (A38; L577 BQ-09): seconds, prints/s, whale share, seed, window ms
SIM_S, SIM_RATE, SIM_SHARE, SIM_SEED, WINDOW_MS, SIM_MAX = 60, 2000, 0.0016, 577, 5000, 12
SIM_HOLD = (20_000.0, 30_000.0)  # the second run: a row focused (or `verbosity` `low`), ms
HZ, RUNG_HZ, BYTES, AGED_MS = 60, 30, 4, 60_000
THEMES = ("dark", "light", "hc")
FLASH_DL, FLASH_DARK = 0.1, 0.8  # WCAG 2.3.1's general flash, as E05-D03 applies it
SEVERITIES = ("Blocking", "Major", "Minor", "Info")
VERDICTS = (
    "compliant",
    "at risk",
    "non-compliant",
    "not yet decidable — routed to E22-Q04 (#754)",
)
OWNER_RE = re.compile(r"^E\d\d-D\d\d · area/[a-z-]+$")
AGENT_RE = re.compile(r"worker|agent|hpe-|session", re.IGNORECASE)
TARGETS = ("E22-S01 (#714)", "E22-S03 (#716)", "E22-Q04 (#754)", "E22-D05 (#578)")
GATED = re.compile(r"\bS(?:10|21|23)\b")
CROSSWALK: tuple[str, ...] = ("1.4.1", "1.4.3", "2.1.1", "2.2.2", "2.3.1", "2.4.3", "2.4.7")
CROSSWALK += ("2.4.11", "2.5.8", "4.1.3")
CONSUMERS = {
    "Q02": "E22-Q02 (#752)",
    "Q04": "E22-Q04 (#754)",
    "S01-u": "E22-S01 (#714)",
    "S03-u": "E22-S03 (#716)",
    "K01-b": "E22-K01 (#608)",
}
ASSERT = re.compile(r"\b(Q02|Q04|S01-u|S03-u|K01-b)-(\d\d): \S")
BOARDS_LINE = "BOARDS: none, by A37"
BOARD_REFS = (r"\.png\b", r"\bimg/", r"\bPENDING\b", r"\bboards? \d", r"Penpot page `")
BANNED_ROT13 = (
    "yrnx rkcbfrq olcnff rkcybvg nggnpx benpyr erirny haobhaqrq sybbq fgnyy nqivfbel TUFN cer-nhgu"
)
BANNED = codecs.decode(BANNED_ROT13, "rot13").split()
BANNED_WORD = re.compile(r"\b" + codecs.decode("qbf", "rot13") + r"\b", re.IGNORECASE)
HOST = re.compile(
    r"\b[a-z0-9-]+(?:\.[a-z0-9-]+)*\.(?:com|net|org|io|dev|app|cloud)\b", re.IGNORECASE
)
UUID = re.compile(
    r"\b[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}\b", re.IGNORECASE
)


def _load(name: str) -> ModuleType:
    spec = importlib.util.spec_from_file_location(name, TOOLS / f"{name}.py")
    if spec is None or spec.loader is None:
        raise SystemExit(f"cannot load {name}")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


CONTRAST: Any = _load("contrast_check")


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
    sources: dict[str, str]


class Result:
    def __init__(self) -> None:
        self.fails: list[str] = []
        self.warns: list[str] = []
        self.numbers: dict[str, object] = {}

    def fail(self, code: str, msg: str) -> None:
        self.fails.append(f"[{code}] {msg}")


def load_ctx(sources: dict[str, str]) -> Ctx:
    return Ctx(
        spec=SPEC.read_text(encoding="utf-8"),
        tool=Path(__file__).read_text(encoding="utf-8"),
        base={k: git_show(BASE, p) for k, p in KEYS.items()},
        tokens=token_values([git_show(BASE, p) for p in TOKEN_FILES]),
        bq_base={k: git_show(BQ_BASE, p) for k, p in KEYS.items()},
        sources=sources,
    )


def flat(text: str) -> str:
    return " ".join(text.split())


def norm(text: str) -> str:
    return flat(text.replace("`", "").replace("**", "")).lower()


def section(spec: str, num: str) -> str:
    """Section `num` ("2", "10.1") of the spec: from its heading to the next of its level."""
    level = "###" if "." in num else "##"
    out: list[str] = []
    inside = False
    for line in spec.splitlines(keepends=True):
        m = re.match(r"(#{2,3}) (\d+(?:\.\d+)?)\.? ", line)
        if m and (m.group(1) == level or (level == "###" and m.group(1) == "##")):
            inside = m.group(2) == num
        if inside:
            out.append(line)
    return "".join(out)


def rows(block: str) -> list[list[str]]:
    out = []
    for line in block.splitlines():
        if line.startswith("|") and not re.match(r"^\|[\s:|-]+\|$", line):
            out.append([c.strip() for c in line.strip().strip("|").split("|")])
    return out[1:]  # drop the header


def by_id(block: str, prefix: str) -> dict[str, list[str]]:
    return {r[0]: r for r in rows(block) if re.fullmatch(prefix + r"-\d+", r[0])}


COLS: tuple[str, ...] = (
    "d4",
    "moment",
    "surface",
    "layer",
    "property",
    "fromto",
    "timing",
    "ac1",
    "reduce",
)
COLS += ("carrier", "cost", "rules", "source", "assertion")


def table(spec: str) -> list[dict[str, str]]:
    first = section(spec, "2").split("\n**What A37 rules")[0]
    return [dict(zip(COLS, r, strict=False)) for r in rows(first)]


CITE = re.compile(r"`([A-Za-z0-9.-]+)`((?::\d+(?:-\d+)?)(?:, :\d+(?:-\d+)?)*)")
TOKEN = re.compile(r"`([a-z]+(?:\.[a-z0-9_-]+)+)`")


# --- G1: the entry table ----------------------------------------------------------------------
def row_problem(row: dict[str, str]) -> str:
    rid = row.get("d4", "")
    if len(row) != len(COLS) or not all(row.get(c) for c in COLS):
        return "a cell is missing or empty"
    if row["carrier"] in DASHES or row["reduce"] in DASHES:
        return "the Carrier or the motion-reduce cell is a dash"
    if RULED_LAYER.get(rid) != row["layer"]:
        return f"layer {row['layer']!r}, ruled {RULED_LAYER.get(rid)!r}"
    if rid in OWNED:
        cut = (
            row["property"].startswith("none")
            and row["timing"].startswith(CUT_TIMING)
            and row["reduce"].startswith("identical (a cut)")
            and row["ac1"].startswith("static is not worse:")
        )
        if not cut:
            return "an owned row is not a cut: Property none, the instant pair, identical, 'static'"
    elif missing := [c for c in CITED_COLS if not row[c].startswith("cited:")]:
        return f"a cited row's {missing} do not start 'cited:'"
    if not CITE.search(row["source"]):
        return "the Source cell holds no cite"
    return ""


def gate_table(ctx: Ctx, r: Result) -> None:
    rs = table(ctx.spec)
    if tuple(x.get("d4") for x in rs) != ROWS:
        r.fail("G1-TABLE", f"rows {[x.get('d4') for x in rs]}, ruled D4-01 to D4-18 in order")
    for row in rs:
        if problem := row_problem(row):
            r.fail("G1-TABLE", f"{row.get('d4')}: {problem}")
    r.numbers["rows"] = len(rs)
    r.numbers["cuts"] = sum(x.get("d4") in OWNED and not row_problem(x) for x in rs)


# --- G2: tokens -------------------------------------------------------------------------------
def gate_token(ctx: Ctx, r: Result) -> None:
    groups = {n.split(".")[0] for n in ctx.tokens}
    named = {t for t in TOKEN.findall(ctx.spec) if t.split(".")[0] in groups}
    if missing := sorted(named - set(ctx.tokens) - PROPOSED):
        r.fail("G2-TOKEN", f"token names not in the token JSON at the base: {missing}")
    if extra := sorted(t for t in named if t.startswith("motion.") and t not in MOTION7):
        r.fail("G2-TOKEN", f"motion names outside the seven: {extra}")
    for row in table(ctx.spec):
        rid = row.get("d4", "")
        said = tuple(t for t in TOKEN.findall(row.get("timing", "")) if t.startswith("motion."))
        want = RULED_TIMING.get(rid, (D + "instant",))
        if said != want:
            r.fail("G2-TOKEN", f"{rid}: timing names {list(said)}, ruled {list(want)}")
    r.numbers["tokens_named"] = len(named)


# --- G3: cost and property --------------------------------------------------------------------
def gate_property(ctx: Ctx, r: Result) -> None:
    for row in table(ctx.spec):
        rid, layer, cost = row.get("d4", ""), row.get("layer", ""), row.get("cost", "")
        if rid not in OWNED:
            continue
        need = []
        if "canvas" in layer:
            need += ["+0 draw calls", "the bubbles layer only"]
        if "DOM" in layer:
            need.append("no layout on the chart container")
        if lacks := [w for w in need if w not in cost]:
            r.fail("G3-PROPERTY", f"{rid}: the Cost cell lacks {lacks}")


# --- G4: the do-not-animate list --------------------------------------------------------------
QUOTE = re.compile(r'^- (DNA-\d): "(.+)" — ', re.MULTILINE)


def gate_dna(ctx: Ctx, r: Result) -> None:
    lines = ctx.base["E22.json"].splitlines()
    body = lines[133] if len(lines) > 133 else ""
    sec3, rs = section(ctx.spec, "3"), {x.get("d4"): x for x in table(ctx.spec)}
    found = QUOTE.findall(sec3)
    if tuple(q for q, _ in found) != DNA_IDS:
        r.fail("G4-DNA", f"quoted clauses {[q for q, _ in found]}, ruled {list(DNA_IDS)}")
    for qid, text in found:
        if text not in body:
            r.fail("G4-DNA", f"{qid} is not byte for byte in `E22.json`:134 at {BASE}")
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


class Sim(NamedTuple):
    prints: int
    whales: int
    dropped: int
    writes: list[float]


def simulate(hold: tuple[float, float] | None = None) -> Sim:
    """A38's throttle over SIM_S s of prints at SIM_RATE /s, suppressed over `hold` (ms, half-open).

    Every print reaches the announcer; only a whale enters it. A whale after a quiet is written at
    once and opens a half-open window; whales inside it are summed and written at its close, which
    opens the next; a window that closes empty ends the run. The latest window replaces. While
    suppressed (a row focused, or `verbosity` `low`) a whale is dropped, not held; when suppression
    begins the open window's pending sum is dropped and the window keeps its clock."""
    rng, step, horizon = random.Random(SIM_SEED), 1000 / SIM_RATE, SIM_S * 1000
    writes: list[float] = []
    pending, end, whales, prints, dropped = 0, -1.0, 0, SIM_S * SIM_RATE, 0
    begun = hold is None

    def close_until(t: float) -> float:
        nonlocal pending
        e = end
        while e >= 0 and e <= t:
            if pending:
                writes.append(e)
                pending, e = 0, e + WINDOW_MS
            else:
                e = -1.0
        return e

    for i in range(prints):
        t = i * step
        whale = rng.random() < SIM_SHARE
        if hold is not None and not begun and t >= hold[0]:
            end, pending, begun = close_until(hold[0] - 1e-6), 0, True  # the pending sum dropped
        if not whale:
            continue  # not a whale: never announced
        whales += 1
        end = close_until(t)
        if hold is not None and hold[0] <= t < hold[1]:
            dropped += 1  # suppressed: dropped, not held
        elif end < 0:
            writes.append(t)
            end = t + WINDOW_MS
        else:
            pending += 1
    close_until(horizon - 1e-6)
    return Sim(prints, whales, dropped, [w for w in writes if w < horizon])


def lum(hex6: str) -> float:
    rgb = tuple(int(hex6[i : i + 2], 16) for i in (0, 2, 4))
    return float(CONTRAST.relative_luminance(rgb))


def flash_rows(d03_line: str) -> list[tuple[str, ...]]:
    """Section 5's table from D03 section 8.2's resolved values (dark / light / hc)."""
    hexes = {}
    for name in ("`.raised`", "`color.buy.subtle`", "`color.sell.subtle`"):
        m = re.search(re.escape(name) + r" #(\w{6}) / #(\w{6}) / #(\w{6})", d03_line)
        hexes[name] = m.groups() if m else ("000000",) * 3
    out = []
    for i, theme in enumerate(THEMES):
        a, b, s = (lum(hexes[n][i]) for n in hexes)
        moves = [abs(a - x) >= FLASH_DL and min(a, x) < FLASH_DARK for x in (b, s)]
        cells = (a, b, abs(a - b), s, abs(a - s), min(a, b, s))
        out.append((theme, *(f"{x:.4f}" for x in cells), "yes" if any(moves) else "no"))
    return out


def gate_arith(ctx: Ctx, r: Result) -> None:
    limits = ctx.base["limits.py"]
    vis = int((re.search(r"VISIBLE_BUBBLES_MAX: Final = (\d+)", limits) or [0, 0])[1])
    cap = int((re.search(r"BUBBLE_FLASH_MAX_HZ: Final = (\d+)", limits) or [0, 0])[1])
    prints, whales, _, writes = simulate()
    gap = min((b - a for a, b in itertools.pairwise(writes)), default=0.0)
    if len(writes) > SIM_MAX or gap < WINDOW_MS:
        r.fail("G5-ARITH", f"the throttle wrote {len(writes)} times, closest {gap} ms apart")
    held = simulate(SIM_HOLD)
    hgap = min((b - a for a, b in itertools.pairwise(held.writes)), default=0.0)
    inside = [w for w in held.writes if SIM_HOLD[0] <= w < SIM_HOLD[1]]
    if len(held.writes) > SIM_MAX or hgap < WINDOW_MS or inside:
        r.fail("G5-ARITH", f"the suppressed run wrote {inside} inside the span, closest {hgap} ms")
    lo, hi = (trunc(x, 0) for x in SIM_HOLD)
    late, vs = trunc(1000 / RUNG_HZ, 1), trunc(vis, 0)
    sentences = [
        (
            f"{SIM_S} s at {trunc(SIM_RATE, 0)} prints/s, {trunc(prints, 0)} prints with a seeded "
            f"whale share of {SIM_SHARE * 100:.2f} % (seed {SIM_SEED}, L577 BQ-09), the opt-in on "
            f"and no row focused: {whales} whales, {len(writes)} announcements, every one "
            f"whale-class, the closest two {trunc(gap, 0)} ms apart."
        ),
        (
            f"A second run with the same prints and a row focused from {lo} ms up to {hi} ms "
            f"(`verbosity` `low` is the same input): {held.dropped} whales seen while suppressed "
            f"and dropped, {len(held.writes)} announcements, none inside the focused span, the "
            f"closest two {trunc(hgap, 0)} ms apart."
        ),
        f"At {HZ} Hz one frame is {trunc(1000 / HZ, 1)} ms.",
        f"{trunc(SIM_RATE, 0)} prints/s is {SIM_RATE // HZ} prints a frame.",
        f"so a frame writes at most {trunc(vis * BYTES, 0)} B.",
        f"a change lands at most {late} ms late.",
        f"rows land {SIM_RATE // HZ} to a frame",
        f"0 flashes; the engine's cap is {cap} a second",
        (
            f"{trunc(AGED_MS, 0)} ms later it turns aged. In any half-open 1 000 ms window it "
            "changes at most once, so it makes no flash; a synthetic burst of "
            f"{vs} marks appearing in one frame is {vs} single changes in that frame and 0 flashes"
        ),
    ]
    text = flat(ctx.spec)
    for s in sentences:
        if flat(s) not in text:
            r.fail("G5-ARITH", f"the spec does not carry the recomputed {s[:70]!r}")
    want = flash_rows(ctx.base["D03"].splitlines()[314])
    if [tuple(x) for x in rows(section(ctx.spec, "5"))] != want:
        r.fail("G5-ARITH", f"section 5's flash table differs from the recomputed {want}")
    cells = ("1", f"≤ {vs}", f"≤ {trunc(vis * BYTES, 0)}", "+0", f"≤ {late} ms")
    got = {x[0]: tuple(x[1:6]) for x in rows(section(ctx.spec, "6"))}
    for rid in ("D4-11", "D4-12"):
        if got.get(rid) != cells:
            r.fail("G5-ARITH", f"{rid}: section 6 reads {got.get(rid)}, recomputed {cells}")
    r.numbers["simulation"] = {"prints": prints, "whales": whales, "writes": len(writes)}
    r.numbers["suppressed_run"] = {"dropped": held.dropped, "writes": len(held.writes)}
    r.numbers["flash"] = [x[-1] for x in want]


# --- G6: stamps and the ruled words -----------------------------------------------------------
def units(spec: str) -> list[str]:
    """Each table row, and each paragraph or bullet, as one flat line."""
    out: list[str] = []
    for block in re.split(r"\n\s*\n", spec):
        lines = block.splitlines()
        if lines and all(ln.startswith("|") for ln in lines):
            out += lines
        else:
            out += [flat(b) for b in re.split(r"\n(?=- )", block)]
    return out


def gate_ruled(ctx: Ctx, r: Result) -> None:
    seen: dict[str, int] = {}
    for unit in units(ctx.spec):
        site = next((k for k in SITE_ROWS if unit.startswith(k)), "")
        for m in STAMP_RE.finditer(unit):
            lead = site or next((k for k in SITE_LEADS if unit[: m.start()].endswith(k)), "")
            want = SITE_ROWS.get(lead) or SITE_LEADS.get(lead)
            if not want:
                r.fail("G6-RULED", f"a stamp at an unchecked site: {unit[:48]!r}")
            elif m.group(0) != STAMPS[want]:
                r.fail("G6-RULED", f"{lead.strip()!r} carries {m.group(0)!r}, not {want}'s stamp")
            seen[lead] = seen.get(lead, 0) + 1
    if missing := sorted(k.strip() for k in (*SITE_ROWS, *SITE_LEADS) if k not in seen):
        r.fail("G6-RULED", f"no stamp at {missing}")
    an = by_id(section(ctx.spec, "7"), "AN")
    for rid, gate in AN_GATES.items():
        if len(an.get(rid, [])) != 8 or an[rid][6] != gate:
            r.fail("G6-RULED", f"{rid}'s Gate cell does not read A38's {gate!r}")
    text = norm(ctx.spec)
    for name, pins in RULING_PINS.items():
        for pin in pins:
            if norm(pin) not in text:
                r.fail("G6-RULED", f"{name}'s words {pin[:48]!r} are not in the spec")
            if name in ctx.sources and norm(pin) not in norm(ctx.sources[name]):
                r.fail("G6-RULED", f"{name}'s words {pin[:48]!r} are not in its saved copy")
    if re.search(r"walkthrough[^.]{0,60}pending|pending[^.]{0,60}walkthrough", text):
        r.fail("G6-RULED", "the owner walkthrough is written as pending")
    r.numbers["stamps"] = sum(seen.values())
    r.numbers["ruling_pins"] = sum(len(p) for p in RULING_PINS.values())
    r.numbers["sources_checked"] = sorted(ctx.sources)


# --- G7: cites --------------------------------------------------------------------------------
def gate_cite(ctx: Ctx, r: Result) -> None:
    cited: list[tuple[str, int, int]] = []
    for key, spans in CITE.findall(ctx.spec):
        if key not in KEYS:
            r.fail("G7-CITE", f"`{key}`{spans}: an undeclared key")
            continue
        size = len(ctx.base[key].splitlines())
        for a, b in re.findall(r":(\d+)(?:-(\d+))?", spans):
            lo, hi = int(a), int(b or a)
            cited.append((key, lo, hi))
            if not 0 < lo <= hi <= size:
                r.fail("G7-CITE", f"`{key}`:{a}{'-' + b if b else ''} is outside the file")
    pins = [p.split("|", 2) for p in CITE_PINS.replace("\n", " ¦ ").split(" ¦ ")]
    for key, line, words in pins:
        lines = ctx.base[key].splitlines()
        if int(line) > len(lines) or words not in lines[int(line) - 1]:
            r.fail("G7-CITE", f"`{key}`:{line} no longer carries {words!r}")
    at = {(k, int(n)) for k, n, _ in pins}
    spans = {(k, a, b) for k, a, b in cited if 0 < a <= b <= len(ctx.base[k].splitlines())}
    uncited = sorted(
        f"{k}:{n}" for k, n in at if not any(c == k and a <= n <= b for c, a, b in spans)
    )
    unpinned = sorted(
        f"{k}:{a}-{b}" for k, a, b in spans if not any(p == k and a <= n <= b for p, n in at)
    )
    if uncited or unpinned:
        r.fail(
            "G7-CITE",
            f"pins and cites disagree: pinned, not cited {uncited}; cited, not pinned {unpinned}",
        )
    moved = sorted(
        {
            f"{k}:{a}-{b}"
            for k, a, b in spans
            if k not in REREAD
            and ctx.bq_base[k]
            and ctx.bq_base[k].splitlines()[a - 1 : b] != ctx.base[k].splitlines()[a - 1 : b]
        }
    )
    if moved:
        r.fail("G7-CITE", f"cited spans that read otherwise at {BQ_BASE}: {moved}")
    r.numbers["cites"] = len(cited)
    r.numbers["spans"] = len(spans)
    r.numbers["pins"] = len(pins)
    r.numbers["bq_base"] = "readable" if any(ctx.bq_base.values()) else "not readable"


# --- G8: hygiene ------------------------------------------------------------------------------
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
    ):
        if re.search(pat, ctx.spec, re.IGNORECASE):
            r.fail("G8-HYGIENE", what)


# --- G9: the review's verdicts and F rows -----------------------------------------------------
def gate_frow(ctx: Ctx, r: Result) -> None:
    body = section(ctx.spec, "11")
    table_ = by_id(body, "F")
    counts = {s: sum(v[1] == s for v in table_.values()) for s in SEVERITIES}
    head = re.search(
        r"^## 11\. Findings — F (\d+) \((.*?)\) <!-- audit:f=([\d/]+) -->$", ctx.spec, re.MULTILINE
    )
    want = f"{len(table_)} (" + " · ".join(f"{s} {counts[s]}" for s in SEVERITIES) + ")"
    marker = "/".join(str(x) for x in (len(table_), *counts.values()))
    if not head or f"{head.group(1)} ({head.group(2)})" != want or head.group(3) != marker:
        r.fail("G9-FROW", f"the heading or its marker does not read F {want} ({marker})")
    for fid, row in table_.items():
        if len(row) != 10:
            r.fail("G9-FROW", f"{fid}: {len(row)} cells, ruled 10")
            continue
        sev, merged, owner, target, gt2 = row[1], row[4], row[6], row[7], row[8]
        problem = ""
        if sev not in SEVERITIES:
            problem = f"severity {sev!r}"
        elif not OWNER_RE.match(owner) or AGENT_RE.search(owner):
            problem = f"owner {owner!r} is not a spec and an area"
        elif not any(t in target for t in TARGETS):
            problem = f"target {target!r} names none of {TARGETS}"
        elif (gt2 in DASHES) == bool(GATED.search(" ".join(row))):
            problem = f"G-T2 {gt2!r} on a row that is {'' if GATED.search(merged) else 'not '}gated"
        elif not CITE.search(merged):
            problem = "the merged sentence holds no cite"
        if problem:
            r.fail("G9-FROW", f"{fid}: {problem}")
    n = 0
    for sub in ("10.1", "10.2"):
        for row in rows(section(ctx.spec, sub)):
            n += 1
            verdict, ref, text = row[1], row[3], " ".join(row)
            fids = re.findall(r"\bF-\d\d\b", ref)
            sevs = {table_.get(f, ["", ""])[1] for f in fids}
            if verdict not in VERDICTS:
                r.fail("G9-FROW", f"{sub} {row[0]!r}: verdict {verdict!r}")
            elif verdict == "at risk" and "interim path" not in text and "Major" not in sevs:
                r.fail("G9-FROW", f"{sub} {row[0]!r}: at risk with no interim path or Major row")
            elif verdict == "non-compliant" and "Blocking" not in sevs:
                r.fail("G9-FROW", f"{sub} {row[0]!r}: non-compliant with no Blocking row")
    walk = [x[0].split()[0] for x in rows(section(ctx.spec, "10.2"))]
    if missing := [sc for sc in CROSSWALK if sc not in walk]:
        r.fail("G9-FROW", f"the cross-walk lacks {missing}")
    if dangling := sorted(set(re.findall(r"\bF-\d\d\b", ctx.spec)) - set(table_)):
        r.fail("G9-FROW", f"F ids cited but not in section 11: {dangling}")
    r.numbers["findings"] = counts
    r.numbers["verdicts"] = n


# --- G10: assertions --------------------------------------------------------------------------
def assertion_sites(spec: str) -> dict[str, str]:
    """Row id -> the text that must name its assertion (a table's last cell, a DNA bullet)."""
    out: dict[str, str] = {x.get("d4", ""): x.get("assertion", "") for x in table(spec)}
    for sec, prefix in (("6", "D4"), ("7", "AN"), ("8", "KR"), ("9", "FP"), ("11", "F")):
        for rid, row in by_id(section(spec, sec), prefix).items():
            out[f"{sec}:{rid}" if sec == "6" else rid] = row[-1]
    for bullet in units(section(spec, "3")):
        if m := re.match(r"- (?:\*\*)?(DNA-\d)[:.](.*)$", bullet):
            out[m.group(1)] = m.group(2)
    return out


def gate_assert(ctx: Ctx, r: Result) -> None:
    ids: dict[str, str] = {}
    before = len(r.fails)
    for site, text in assertion_sites(ctx.spec).items():
        found = ASSERT.findall(text)
        if len(found) != 1:
            r.fail("G10-ASSERT", f"{site}: {len(found)} assertion ids, ruled one with a statement")
            continue
        aid = "-".join(found[0])
        if aid in ids:
            r.fail("G10-ASSERT", f"{aid} names both {ids[aid]} and {site}")
        ids[aid] = site
    per = {c: sorted(a for a in ids if a.rsplit("-", 1)[0] == c) for c in CONSUMERS}
    line = " · ".join(f"{c} {len(v)} to {CONSUMERS[c]}" for c, v in per.items())
    if len(r.fails) == before and line not in flat(section(ctx.spec, "14")):
        r.fail("G10-ASSERT", f"section 14 does not read the counts {line!r}")
    r.numbers["assertions"] = {c: len(v) for c, v in per.items()}
    r.numbers["assertion_ids"] = per


# --- G11: no boards ---------------------------------------------------------------------------
def gate_boards(ctx: Ctx, r: Result) -> None:
    hits = [p for p in BOARD_REFS if re.search(p, ctx.spec)]
    if f"**{BOARDS_LINE}.**" not in section(ctx.spec, "0") or hits:
        r.fail("G11-BOARDS", f"{BOARDS_LINE!r} does not stand alone; board references {hits}")


GATE_FNS: tuple[tuple[str, Callable[[Ctx, Result], None]], ...] = (
    ("G1-TABLE", gate_table),
    ("G2-TOKEN", gate_token),
    ("G3-PROPERTY", gate_property),
    ("G4-DNA", gate_dna),
    ("G5-ARITH", gate_arith),
    ("G6-RULED", gate_ruled),
    ("G7-CITE", gate_cite),
    ("G8-HYGIENE", gate_hygiene),
    ("G9-FROW", gate_frow),
    ("G10-ASSERT", gate_assert),
    ("G11-BOARDS", gate_boards),
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
    ("G1-TABLE", regex(r"^(\| D4-06 .*?)static is not worse:", r"\1static is fine:")),
    ("G2-TOKEN", regex(r"^(\| D4-15 .*?)`motion\.duration\.normal`", r"\1`motion.duration.slow`")),
    ("G3-PROPERTY", regex(r"^(\| D4-11 .*?)\+0 draw calls", r"\1+1 draw call")),
    ("G4-DNA", sub("both invisible and expensive.", "both invisible and costly.")),
    ("G5-ARITH", regex(r"^(\| D4-11 +\| 1 +\| ≤ 5 000 +\| )≤ 20 000", r"\1≤ 20 001")),
    ("G6-RULED", sub("The policy is " + STAMPS["A38"], "The policy is " + STAMPS["A38"][:-5])),
    ("G7-CITE", sub("`D03H`:154", "`D03H`:9154")),
    ("G8-HYGIENE", sub("(a spec cannot split from its tool)", "(a spec cannot split, /tmp/x)")),
    ("G9-FROW", regex(r"^(\| F-03 .*?\| )E22-D04 · area/order-flow", r"\1the spec author")),
    ("G10-ASSERT", regex(r"^(\| D4-03 .*?)Q02-01:", r"\1Q02-02:")),
    ("G11-BOARDS", sub("tables below are the record", "tables below are the record (board 01)")),
)

# Probes: edits a weaker gate would let through; each must add one FAIL.
PROBES: tuple[tuple[str, Callable[[Ctx], Ctx]], ...] = (
    ("G1-TABLE", regex(r"^(\| D4-17 +(?:\|[^|]+){3}\| )cited:", r"\1none:")),
    ("G1-TABLE", regex(r"^(\| D4-16 (?:\|[^|]+){2}\| )DOM   ", r"\1canvas")),
    ("G2-TOKEN", sub("swaps `color.surface.raised` for", "swaps `color.surface.lifted` for")),
    ("G4-DNA", regex(r"^(\| D4-06 .*?\| )DNA-5( +\|)", r"\1MR-3 \2")),
    ("G5-ARITH", sub("188 whales, 12 announcements", "188 whales, 11 announcements")),
    ("G5-ARITH", regex(r"^(\| light +\| 0\.8615 +\| )0\.8492", r"\g<1>0.8491")),
    ("G6-RULED", regex(r"^(\| C-7 .*?)" + re.escape(STAMPS["A37"]), r"\1RULED (orchestrator)")),
    ("G6-RULED", sub("- **Hand-offs.**", "- **Hand-offs.** The owner walkthrough stays pending.")),
    ("G6-RULED", sub("focus never sits on a moving row", "focus rarely sits on a moving row")),
    ("G7-CITE", sub("(`06`:91)", "(`06`:92)")),
    ("G8-HYGIENE", sub("- **Hand-offs.**", "- **Hand-offs.** " + codecs.decode("Yrnx", "rot13"))),
    ("G9-FROW", sub("<!-- audit:f=8/0/0/4/4 -->", "<!-- audit:f=8/0/1/3/4 -->")),
    ("G9-FROW", regex(r"^(\| §3\.4 item 7: .*?\| at risk +\| )interim path: ", r"\1")),
    ("G10-ASSERT", regex(r"^(\| FP-07 .*?)Q02-24: ", r"\1")),
    ("G11-BOARDS", sub(BOARDS_LINE + ".**", BOARDS_LINE + ".** PENDING.")),
    ("G11-BOARDS", sub("**" + BOARDS_LINE + ".**", "**Boards.**")),
    ("G6-RULED", regex(r"^(\| AN-01 .*?)`verbosity` not `low`", r"\1any verbosity")),
    ("G6-RULED", regex(r"^(\| AN-01 .*?)no tape row focused; ", r"\1")),
    ("G6-RULED", regex(r"^(\| AN-08 .*?); `announce_prices` not read", r"\1")),
    ("G5-ARITH", sub("none inside the focused span", "one inside the focused span")),
    ("G10-ASSERT", regex(r"^(\| AN-08 .*?)Q04-17: ", r"\1")),
)


def digests() -> dict[str, str]:
    return {str(p): hashlib.sha256(p.read_bytes()).hexdigest() for p in (SPEC, Path(__file__))}


def self_test(ctx: Ctx, base: Result) -> list[str]:
    bad: list[str] = []
    before = digests()
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
        n = res.numbers
        out = [f"FAIL {line}" for line in res.fails] + [f"WARN {line}" for line in res.warns]
        out.append(
            f"rows {n.get('rows')} (cuts {n.get('cuts')}); DNA {n.get('dna')}; simulation "
            f"{n.get('simulation')} (suppressed run {n.get('suppressed_run')}); flash "
            f"{n.get('flash')}; stamps {n.get('stamps')}; cites "
            f"{n.get('cites')} ({n.get('spans')} spans, {n.get('pins')} pins; BQ base "
            f"{n.get('bq_base')}); ruling pins {n.get('ruling_pins')} (saved copies "
            f"{n.get('sources_checked')}); findings {n.get('findings')}; verdicts "
            f"{n.get('verdicts')}; assertions {n.get('assertions')}"
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
