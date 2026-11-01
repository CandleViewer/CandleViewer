"""E14-K01 (#356) audit: the keyboard-drawing spike, its results file and its two doc edits.

Stdlib only, offline (`python3 -I -B`). It reads the finding, the results file, the harness's page
script, the pins file, `05` and `14` from the working tree, and every cited file AS TEXT at the cite
base (`git show`). It imports, never copies: the E14-D07 label template engine (`template`,
`EXAMPLES`), the E14-D08 token resolver (`Env`, `resolve_any`, `contrast`, `show_ratio`, `THEMES`),
the E09-D07 colour-vision port (`simulate`, `lab`, `delta_e`, `SIMS`, `TRITAN`) and
`calendar_cv.sprint_range`. Default-deny: a gate that cannot read its input FAILs.

Two modes, chosen by content, never by branch name. PR-1 mode: the finding is absent at the
merge-base; the cite base is the merge-base, and `05` and `14` differ from it by exactly the two
content edits. Post-merge mode: the finding ships at the merge-base; the cite base is frozen at the
base the merged finding recorded (`audit:sha`, the base its pins were read at; the merge-base when
the marker is missing or unresolvable), every merged table row stands unchanged, and the two edits
must still stand in `05` and `14`.

Gates (each FAIL led by its code):

- [G01-FILLED] no `{{KIND:key}}` slot is left in the finding.
- [G02-AUDIT] every `<!-- audit:key=value -->` marker is a known key, equals the recomputed value
  and stands right after its visible value.
- [G03-CITE] every cited endpoint resolves at the cite base to a non-blank line, and its pin matches.
- [G04-PINS] the pins file and the finding's cited endpoints match both ways.
- [G05-RESULTS] the results file's `measures` equal what its raw rows give; the section 3.2 table
  equals the raw cells; every measure the finding quotes stands in it verbatim.
- [G06-RECOMMEND] the recommendation is the rule's, (c); its reason states the accessibility
  tie-break, not cost; section 4.3 states (b)'s cheaper cost from the results and why (b) loses.
- [G07-LIVE] every section 11.2 row has a host from the ruled set that is a region of D10's map, a
  politeness from the set (assertive only for RG-04's access row), a rate from the ruled
  vocabulary, a VC id defined on its cited line and a quoted text verbatim there; every section
  14.2 quote stands on its cited line; the session kept two writes per second and dropped no
  confirmation; CK-01 states "slot + 250 ms".
- [G08-FINDINGS] every FK row has a severity, a reason, one owner per spec in the ruled form, a
  target and `G-T2`, `Focus` and `Rate` from their sets; the hold sentence matches the Blocking rows.
- [G09-PROPOSED] every PROPOSED string has an owner: a CK row's owner cells are all in the ruled
  form, and every other line saying PROPOSED names an owner or a CK row.
- [G10-HYGIENE] no word from the private list in any own file; no URL, local path, uuid, agent
  name or closing keyword in the finding, the tool or the pins.
- [G11-KEYS] every harness-only key is labelled so on its line; the section 7.2 arming keys are
  D02's registry keys; the section 6.2 classes are D02's anchor counts; no ticket key survives in
  the `14` line.
- [G12-RULED] section R lists BQ-01..BQ-17 once each with the ruling stamp; no BQ marker is left;
  every "RULED BQ-nn" stamp names a listed BQ.
- [G13-SCOPE] the changed paths are the own files, the harness, `05` and `14` only.
- [G14-EDITS] `14` differs by the one SCR-037 Interactions line, `05` by the section 6.1.1 block
  alone, and each equals the text section 16 quotes.
- [G15-FREEZE] post-merge mode: every merged table row stands unchanged.
- [G16-CONTRAST] the focus ring against its halo is 3:1 or more in every theme; no candle ink
  defeats both; section 12.4 states the colour-vision method that ran, and the tritan matrix is
  the published Machado 2009 one.
- [G17-WINDOW] the cap is the largest swept K under both gates (K = 300 fails), stated with n and
  the evidence class; the natural window's medians are the results'.
- [G18-DEFS] every cited field, event, row id and code is cited at its own definition line.
- [G19-T2] section 6.5 states the T2 rule (CMP-079 RbacGate, CMP-019 `lock`, `aria-disabled`, the
  reason node at mount); every T2 row names its key, verb, component, rendering, Focus and Rate.
- [G20-GRAMMAR] the section 8.2 examples equal D07's engine output for all 25 tools.

`--json` prints the numbers and findings; `--check` exits 1 on any FAIL; `--fill` writes the
computed values into the finding's slots and markers; `--self-test` applies one mutation per gate
to an in-memory copy and passes only when each adds FAILs of its gate's code and the base run is
clean; `--repin-ruled` rewrites the pins file from the finding's cites and is its only writer.

Usage: python3 -I -B docs/design/_tools/e14_k01_spike_audit.py [--check] [--json] [--fill]
       [--self-test] [--repin-ruled]
"""

from __future__ import annotations

import argparse
import codecs
import dataclasses
import datetime
import difflib
import functools
import hashlib
import importlib.util
import json
import math
import re
import subprocess
import sys
from collections.abc import Callable
from pathlib import Path
from types import ModuleType
from typing import Any

ROOT = Path(__file__).resolve().parents[3]
TOOLS = ROOT / "docs" / "design" / "_tools"
SPEC_REL = "docs/plan/spikes/E14-K01.md"
RESULTS_REL = "docs/plan/spikes/E14-K01-results.json"
HARNESS_DIR = "docs/plan/spikes/E14-K01-harness/"
HARNESS_JS = HARNESS_DIR + "harness.mjs"
TOOL_REL = "docs/design/_tools/e14_k01_spike_audit.py"
PINS_REL = "docs/design/_tools/e14_k01_ruled_pins.txt"
P05_REL = "docs/plan/05-accessibility-standard.md"
P14_REL = "docs/plan/14-screens-catalogue.md"
CAL_REL = "docs/plan/backlog/_tools/calendar_cv.py"
D08_REL = "docs/design/E14/E14-D08.md"
OWN = {SPEC_REL, RESULTS_REL, TOOL_REL, PINS_REL}
UPSTREAM = "origin/main"
BQ_BASE = "2026a56ff48b4900eb2fe2c79888750202914f5e"  # where the BQ list read every cite
RULING_ID = "6551735268"
RULED_STAMP = f"RULED (orchestrator, 2026-11-01, #356 ruling of record {RULING_ID})"
BQ_COUNT = 17

DESIGN_KEYS = {k: f"docs/design/E14/E14-{k}.md" for k in ("D02", "D07", "D08", "D10")}
KEY_RE = r"D0[278]|D10|E\d\d-D\d\d|\d\d|KR|ENG/[\w./-]+"
MD_CITE = re.compile(
    rf"`(?P<key>{KEY_RE})`:(?P<a>\d+)(?:[–-](?P<b>\d+))?(?P<more>(?:, :\d+(?:[–-]\d+)?)*)"
)
MORE = re.compile(r":(\d+)(?:[–-](\d+))?")
SLOT = re.compile(r"(`?)\{\{([A-Z]+):([\w.-]+)\}\}(`?)")
AUDIT = re.compile(r"<!-- audit:([\w.-]+)=([^>]*?) -->")
QUOTE = re.compile(r'"([^"]*)"')

SEVERITIES = ("Blocking", "Major", "Minor", "Info")
RATE_UNITS = "action|press|release|episode|entry|focus|focus entry|key-down|arm"
RATE = re.compile(
    rf"^(?:never|once per (?:{RATE_UNITS})\b|≤ \d+ per \d+ s (?:per (?:key|region)\b"
    rf"|across RG-\d\d and RG-\d\d))"
)
G_T2 = re.compile(r"^(?:n/a|T2 · (?:2a|2b|sentence))$")
FOCUS = re.compile(r"^(?:n/a|(?:kept|moves to|restored to|returns to) · \S.*)$")
OWNER_TOKEN = r"`E\d\d-[DK]\d\d · area/[a-z-]+`"
OWNER = re.compile(rf"^{OWNER_TOKEN}$")
RULED_OWNERS = frozenset(
    f"`{o}`"
    for o in (
        "E14-D02 · area/charting-ui",
        "E14-D07 · area/charting-ui",
        "E14-D08 · area/charting-ui",
        "E14-D10 · area/charting-ui",
        "E14-K01 · area/charting-ui",
        "E06-D03 · area/chart-engine",
        "E17-D02 · area/backend-platform",
    )
)
CK_OWNERS = {
    "CK-01": ("`E14-D10 · area/charting-ui`", "`E06-D03 · area/chart-engine`"),
    "CK-02": ("`E17-D02 · area/backend-platform`",),
}
RULED_HOSTS = ("RG-03", "RG-04", "RG-14", "RG-15")
POLITENESS = ("polite", "polite, coalesced", 'assertive (`role="alert"`)')
HARNESS_ONLY = ("`Alt+C`", "`Alt+P`", "`Shift+Enter`")
TICKET_KEYS = ("Alt+T", "Alt+F", "Alt+M")
HTML_SETTERS = re.compile(
    r"innerHTML|outerHTML|insertAdjacentHTML|document\.write|DOMParser|createContextualFragment|srcdoc"
)
NODES_PER_DRAWING = {"a": True, "b": False, "c": True}
STRATEGY_NAMES = {
    "a": "(a) one surrogate per drawing",
    "b": "(b) one application host with a grid summary",
    "c": "(c) visible, selected and focused drawings only",
}
# Machado, Oliveira and Fernandes (2009), tritanopia at severity 1.0, linear RGB: the published
# numbers the E09-D07 port must carry (a check value, not a second port).
MACHADO_2009_TRITAN = (
    1.255528, -0.076749, -0.178779,
    -0.078411, 0.930809, 0.147602,
    0.004733, 0.691367, 0.303900,
)  # fmt: skip
CANDLE_INKS = ("color.candle.up", "color.candle.down", "color.candle.wick")
RING, HALO = "color.chart.focus.ring", "color.chart.pane.bg.default"
CONSUMER_SPRINTS = {"s05": 5, "s07": 7, "s08": 8, "s09": 9}
# The measures the finding quotes verbatim (G05); the table cells are checked separately.
MEASURE_USED = (
    "host_description",
    "run_order",
    "chromium_version",
    "n_samples",
    "recommended_strategy",
    "recommendation_reason",
    "window_cap",
    "window_cap_basis",
    "window_default",
    "focus_model",
    "seed",
    "fixture_hash",
    "fps_note",
    "reachability_a",
    "reachability_b",
    "reachability_c",
    "table_reading",
    "window_reach_check",
    "pointer_events",
    "script_result",
    "target_size_check",
    "sink_result",
    "sink_cases",
    "focus_reach_roving",
    "focus_reach_active",
    "focus_order_result",
    "obscured_result",
    "writes_per_second_max",
    "dropped_writes",
)
# Each cited identifier at its own definition line: (label, key, line, pattern on that line).
DEFS: tuple[tuple[str, str, int, str], ...] = (
    ("the crosshair event", "ENG/src/api/types.ts", 147, r"^\s*crosshair: \{"),
    ("the viewportChanged event", "ENG/src/api/types.ts", 151, r"^\s*viewportChanged: \{"),
    ("getVisibleWindow on the interface", "ENG/src/api/types.ts", 35, r"getVisibleWindow\(\)"),
    ("getFocusedUnit on the interface", "ENG/src/api/types.ts", 36, r"getFocusedUnit\(\)"),
    ("VisibleWindow", "ENG/src/api/types.ts", 505, r"^export interface VisibleWindow "),
    ("the FocusedUnit kind", "ENG/src/api/types.ts", 514, r'kind: "bar" \| "cell" \| "row"'),
    ("the null window", "ENG/src/api/chart.ts", 312, r"getVisibleWindow: .*=> null"),
    ("No data plane yet", "ENG/src/api/chart.ts", 311, r"No data plane yet"),
    ("C-21", "ENG/README.md", 417, r"^\| C-21 "),
    ("BQ-106", "ENG/README.md", 405, r"^\| BQ-106 "),
    ("G-22", "ENG/README.md", 525, r"^\| G-22 "),
    ("BQ-157", "ENG/README.md", 565, r"^\| BQ-157 "),
    ("R354 BQ-12", "D10", 61, r"^\| BQ-12 "),
    ("the combined rule", "D10", 129, r"^\|\s*1\s*\| The chart panel's polite writes"),
    ("RG-03", "D10", 300, r"^\| RG-03 "),
    ("RG-04", "D10", 301, r"^\| RG-04 "),
    ("BG-06", "D10", 585, r"^\| BG-06 "),
    ("T2-02 of D10", "D10", 697, r"^\| T2-02 "),
    ("F-04", "D10", 854, r"^\| F-04 "),
    ("F-09", "D10", 859, r"^\| F-09 "),
    ("C-i", "D10", 885, r"^\| C-i "),
    ("G-05", "D10", 913, r"^\| G-05 "),
    ("T27", "D02", 245, r"^\| T27 "),
    ("the anchor-count rule", "D02", 266, r"^\*\*Per anchor count"),
    ("the focused-handle ring", "D08", 173, r"^\| active / focused handle "),
    ("E06-D03 D1", "E06-D03", 87, r"^\*\*D1 Window and nodes\.\*\*"),
    ("E06-D03 D4", "E06-D03", 103, r"^\*\*D4 Structure and roles\.\*\*"),
    ("E06-D03 D5", "E06-D03", 105, r"^\*\*D5 Live-region policy\.\*\*"),
    ("E06-D03 D6", "E06-D03", 107, r"^\*\*D6 Keyboard model\.\*\*"),
    ("the shell pair", "E17-D02", 249, r"^One live-region pair"),
    ("E09-D09's T2", "E09-D09", 49, r"^- \*\*T2 Disabled with a visible reason"),
    ("the SCR-037 Interactions line", "14", 969, r"^- \*\*Interactions:\*\* keyboard tool"),
    ("the SCR-037 Performance line", "14", 974, r"^- \*\*Performance:\*\*"),
    ("2.4.11 in 05", "05", 99, r"SC 2\.4\.11"),
    ("the surrogate pattern in 05", "05", 140, r"canvas control surrogate"),
)
SEV_HOLD = "**No FK row is Blocking**"
# rot13 keeps the private list out of plain text; underscores stand for spaces.
BANNED_ROT13 = (
    "yrnx rkcbfrq olcnff rkcybvg nggnpx benpyr erirny haobhaqrq sybbq fgnyy qbf nqivfbel tufn "
    "cer-nhgu ucr-jbexre znva-bepurfgengbe"
)
BANNED = [w.replace("_", " ") for w in codecs.decode(BANNED_ROT13, "rot13").split()]
URL = re.compile(r"https?://|\bwww\.", re.IGNORECASE)
UUID = re.compile(r"\b[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}\b")
LOCAL_PATH = re.compile("|".join("/" + w + "/" for w in ("home", "mnt", "tmp")))
AGENT = re.compile(r"\b[a-z]{2,4}-worker-\d\b")
CLOSING = re.compile(r"\b(?:close[sd]?|fix(?:e[sd])?|resolve[sd]?) #\d+", re.IGNORECASE)


# --------------------------------------------------------------------------------------- git


def git(*args: str) -> str:
    out = subprocess.run(
        ["git", *args],
        cwd=ROOT,
        capture_output=True,
        text=True,
        encoding="utf-8",
        check=False,
        timeout=60,
    )
    return out.stdout if out.returncode == 0 else ""


@functools.cache
def merge_base() -> str:
    return git("merge-base", "HEAD", UPSTREAM).strip()


@functools.cache
def show(rev: str, rel: str) -> str | None:
    out = subprocess.run(
        ["git", "show", f"{rev}:{rel}"],
        cwd=ROOT,
        capture_output=True,
        text=True,
        encoding="utf-8",
        check=False,
        timeout=60,
    )
    return out.stdout if out.returncode == 0 else None


def cite_base(base: str, merged_spec: str | None) -> str:
    """PR-1: the merge-base. Post-merge: the base the merged finding recorded in its own
    `audit:sha` marker (the base its pins were read at), never the merge commit or moving main.
    Falls back to the merge-base when the marker is missing or does not resolve (G02 then FAILs).
    """
    if merged_spec is None:
        return base
    for m in AUDIT.finditer(merged_spec):
        if m[1] == "sha" and re.fullmatch(r"[0-9a-f]{40}", m[2]):
            probe = subprocess.run(
                ["git", "cat-file", "-e", m[2] + "^{commit}"],
                cwd=ROOT,
                check=False,
                stderr=subprocess.DEVNULL,
                timeout=60,
            )
            if probe.returncode == 0:
                return m[2]
    return base


@functools.cache
def plan_path(nn: str, rev: str) -> str | None:
    for name in git("ls-tree", "--name-only", rev, "docs/plan/").split():
        if Path(name).name.startswith(f"{nn}-") and name.endswith((".md", ".yaml")):
            return name
    return None


def key_path(key: str, rev: str) -> str | None:
    if key in DESIGN_KEYS:
        return DESIGN_KEYS[key]
    if key == "KR":
        return "docs/plan/spikes/E11-K01.md"
    if key.startswith("ENG/"):
        return "packages/chart-engine/" + key[4:]
    if re.fullmatch(r"\d\d", key):
        return plan_path(key, rev)
    m = re.fullmatch(r"(E\d\d)-(D\d\d)", key)
    return f"docs/design/{m[1]}/{key}.md" if m else None


def read(rel: str) -> str:
    p = ROOT / rel
    return p.read_text(encoding="utf-8") if p.exists() else ""


@functools.cache
def engine(name: str, rel: str = "") -> ModuleType:
    path = ROOT / (rel or f"docs/design/_tools/{name}.py")
    if str(TOOLS) not in sys.path:
        sys.path.insert(0, str(TOOLS))
    spec = importlib.util.spec_from_file_location(name, path)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"cannot import {name}")
    mod = importlib.util.module_from_spec(spec)
    sys.modules[name] = mod
    spec.loader.exec_module(mod)
    return mod


# ----------------------------------------------------------------------------------- parsing


def heading_level(line: str) -> int:
    m = re.match(r"(#{1,6}) ", line)
    return len(m[1]) if m else 0


def section(text: str, prefix: str) -> str:
    lines = text.split("\n")
    for i, line in enumerate(lines):
        lvl = heading_level(line)
        if lvl and line[lvl + 1 :].startswith(prefix):
            out = []
            for nxt in lines[i + 1 :]:
                n = heading_level(nxt)
                if n and n <= lvl:
                    break
                out.append(nxt)
            return "\n".join(out)
    return ""


def cells(line: str) -> list[str]:
    """Split a table row on unescaped pipes."""
    body = line.strip()
    body = body.removeprefix("|")
    body = body[:-1] if body.endswith("|") and not body.endswith("\\|") else body
    return [c.strip().replace("\\|", "|") for c in re.split(r"(?<!\\)\|", body)]


def table_body(block: str) -> list[list[str]]:
    """The body rows of the first table in a block (the separator excluded)."""
    lines = block.split("\n")
    for i, ln in enumerate(lines):
        if re.match(r"^\|\s*:?-{3,}", ln):
            out = []
            for nxt in lines[i + 1 :]:
                if not nxt.startswith("|"):
                    break
                out.append(cells(nxt))
            return out
    return []


def rows(block: str, family: str) -> list[list[str]]:
    pat = re.compile(rf"^\|\s*{re.escape(family)}-\d+\s*\|")
    return [cells(ln) for ln in block.split("\n") if pat.match(ln)]


def norm(s: str) -> str:
    return re.sub(r"\s+", " ", s.replace("`", "").replace("*", "").replace("_", " ")).strip()


def line_hash(s: str) -> str:
    return hashlib.sha1(norm(s).encode("utf-8")).hexdigest()[:16]


def strip_markers(s: str) -> str:
    return AUDIT.sub("", s).replace("  ", " ").strip()


def cite_spans(text: str) -> list[tuple[str, int, int]]:
    out: list[tuple[str, int, int]] = []
    for m in MD_CITE.finditer(text):
        key = m["key"]
        a = int(m["a"])
        out.append((key, a, int(m["b"]) if m["b"] else a))
        for mm in MORE.finditer(m["more"] or ""):
            x = int(mm[1])
            out.append((key, x, int(mm[2]) if mm[2] else x))
    return out


def endpoints(spec: str) -> set[tuple[str, int]]:
    out: set[tuple[str, int]] = set()
    for key, a, b in cite_spans(spec):
        out.add((key, a))
        out.add((key, b))
    return out


def parse_pins(pins: str) -> dict[tuple[str, int], str]:
    out: dict[tuple[str, int], str] = {}
    for ln in pins.split("\n"):
        m = re.fullmatch(rf"({KEY_RE}):(\d+) ([0-9a-f]{{16}})", ln.strip())
        if m:
            out[(m[1], int(m[2]))] = m[3]
    return out


def quoted_ok(quote: str, hay: list[str]) -> bool:
    """A quote stands on a cited line: a `{...}` slot matches any text; short ones as whole words."""
    parts = [re.escape(norm(p)) for p in re.split(r"\{[^{}]*\}", quote)]
    pat = r".*?".join(parts)
    if len(norm(quote)) < 10:
        pat = rf"(?<![\w,.]){pat}(?![\w,])"
    return any(re.search(pat, h) for h in hay)


# ------------------------------------------------------------------------------------ context


@dataclasses.dataclass
class Ctx:
    spec: str
    pins: str
    tool: str
    results: dict[str, Any]
    harness: dict[str, str]  # own harness files, path → text
    p05: str
    p05_base: str
    p14: str
    p14_base: str
    changed: list[str]
    merged_spec: str | None
    base: str
    cbase: str
    base_date: datetime.date
    tritan: tuple[float, ...] = ()

    def base_line(self, key: str, n: int) -> str | None:
        rel = key_path(key, self.cbase)
        text = show(self.cbase, rel) if rel else None
        if text is None:
            return None
        lines = text.split("\n")
        return lines[n - 1] if 0 < n <= len(lines) else None

    def hay(self, cell: str) -> list[str]:
        out = []
        for key, a, b in cite_spans(cell):
            span = [self.base_line(key, n) or "" for n in range(a, b + 1)]
            out.append(norm(" ".join(span)))
        return out


def build_ctx() -> Ctx:
    base = merge_base()
    merged = show(base, SPEC_REL)
    cb = cite_base(base, merged)
    changed = sorted(
        {
            *git("diff", "--name-only", base).split(),
            *git("ls-files", "-o", "--exclude-standard").split(),
        }
    )
    date_s = git("show", "-s", "--format=%cs", cb).strip() or "1970-01-01"
    harness = {
        str(p.relative_to(ROOT)): p.read_text(encoding="utf-8")
        for p in sorted((ROOT / HARNESS_DIR).glob("*"))
        if p.is_file()
    }
    raw = read(RESULTS_REL)
    return Ctx(
        spec=read(SPEC_REL),
        pins=read(PINS_REL),
        tool=read(TOOL_REL),
        results=json.loads(raw) if raw else {},
        harness=harness,
        p05=read(P05_REL),
        p05_base=show(cb, P05_REL) or "",
        p14=read(P14_REL),
        p14_base=show(cb, P14_REL) or "",
        changed=changed,
        merged_spec=merged,
        base=base,
        cbase=cb,
        base_date=datetime.date.fromisoformat(date_s),
        tritan=tuple(float(x) for x in engine("e09_d07_ds_audit").TRITAN),
    )


# ------------------------------------------------------------------------------- the numbers


def fmt(x: float | None, d: int = 2) -> str:
    """The harness's `f()`: fixed decimals, "n/a" for none."""
    return "n/a" if x is None else f"{x:.{d}f}"


def cell(res: dict[str, Any], s: str, n: int) -> dict[str, Any]:
    for c in res["cells"]:
        if c["strategy"] == s and c["n"] == n:
            return dict(c)
    raise KeyError(f"no cell {s}-{n}")


def gate_ok(res: dict[str, Any], c: dict[str, Any]) -> tuple[bool, bool]:
    g = res["params"]["gates"]
    return c["at"]["p95"] <= g["atMs"], c["drag"]["p95"] <= g["dragMs"]


def verdict(res: dict[str, Any], c: dict[str, Any]) -> str:
    at, drag = gate_ok(res, c)
    return f"{'AT ok' if at else 'AT over'}, {'drag ok' if drag else 'drag over'}"


def decide(res: dict[str, Any]) -> dict[str, Any]:
    """The rule of section 4.1, re-run on the raw rows (BQ-06 as ruled)."""
    survivors = [s for s in "abc" if all(gate_ok(res, cell(res, s, 500)))]
    reachable = [s for s in survivors if res["reach"][s]["all"]]
    pool = [s for s in reachable if NODES_PER_DRAWING[s]] or reachable
    pool.sort(key=lambda s: cell(res, s, 500)["at"]["p95"])
    cap = 0
    for sw in sorted(res["sweep"], key=lambda x: x["k"]):
        if all(gate_ok(res, sw)):
            cap = sw["k"]
        else:
            break
    return {
        "survivors": survivors,
        "reachable": reachable,
        "losers": [s for s in reachable if not NODES_PER_DRAWING[s]],
        "recommended": pool[0] if pool else "c",
        "fellBack": not pool,
        "cap": cap,
        "capAdopted": min(cap, res["params"]["adoptCapMax"]),
    }


def cost_cell(res: dict[str, Any], s: str) -> str:
    c = cell(res, s, 500)
    return f"{c['nodes']}; {fmt(c['at']['p95'])}; {fmt(c['drag']['p95'], 3)}"


def ring_values(base: str) -> dict[str, str]:
    mod = engine("e14_d08_ds_audit")
    env = mod.Env(base, {})
    spec = env.at_base(D08_REL)
    out: dict[str, str] = {}

    def hexof(theme: str, tok: str) -> str:
        h = mod.resolve_any(env, spec, theme, tok)
        if not h:
            raise ValueError(f"{tok} does not resolve in {theme}")
        return str(h)

    halo = []
    for th in mod.THEMES:
        halo.append(float(mod.contrast(hexof(th, RING), hexof(th, HALO))))
    out["ring.halo"] = " / ".join(str(mod.show_ratio(r)) for r in halo)
    out["ring.halo-min"] = str(mod.show_ratio(min(halo)))
    both = 0
    for ink in CANDLE_INKS:
        rr, hh = [], []
        for th in mod.THEMES:
            rr.append(float(mod.contrast(hexof(th, RING), hexof(th, ink))))
            hh.append(float(mod.contrast(hexof(th, HALO), hexof(th, ink))))
        name = ink.removeprefix("color.")
        out[f"ink.ring.{name}"] = " / ".join(str(mod.show_ratio(r)) for r in rr)
        out[f"ink.halo.{name}"] = " / ".join(str(mod.show_ratio(r)) for r in hh)
        both += sum(1 for a, b in zip(rr, hh, strict=True) if a < 3.0 and b < 3.0)
    out["ring.both-low"] = str(both)
    short = {"color.candle.up": "up", "color.candle.down": "down", "color.candle.wick": "wick"}
    themes = {"dark": "dark", "light": "light", "high-contrast": "hc"}
    parts = []
    for ink in CANDLE_INKS:
        low = [
            themes.get(th, th)
            for th in mod.THEMES
            if float(mod.contrast(hexof(th, RING), hexof(th, ink))) < 3.0
        ]
        if low:
            parts.append(f"{short.get(ink, ink)}: {', '.join(low)}")
    out["ring.under3"] = "; ".join(parts)
    port = engine("e09_d07_ds_audit")
    ring, hal = hexof("dark", RING), hexof("dark", HALO)
    des = [float(port.delta_e(port.simulate(ring, s), port.simulate(hal, s))) for s in port.SIMS]
    out["cvd.ring"] = " / ".join(f"{x:.1f}" for x in des)
    return out


def grammar_rows(spec: str) -> list[tuple[str, str]]:
    out = []
    for r in table_body(section(spec, "8.2 ")):
        if len(r) >= 4 and re.fullmatch(r"`[a-z_]+`", r[1]):
            out.append((r[1].strip("`"), r[3]))
    return out


def grammar_equal(spec: str) -> int:
    d07 = engine("e14_d07_tree_audit")
    return sum(
        1
        for tool, example in grammar_rows(spec)
        if tool in d07.EXAMPLES and d07.template(tool, d07.EXAMPLES[tool]) == example
    )


def sink_setters(ctx: Ctx) -> int:
    return len(HTML_SETTERS.findall(ctx.harness.get(HARNESS_JS, "")))


def sprint_values(ctx: Ctx) -> dict[str, str]:
    cal = engine("calendar_cv", CAL_REL)
    out: dict[str, str] = {}
    for key, n in CONSUMER_SPRINTS.items():
        start, _ = cal.sprint_range(n)
        ahead = start - datetime.timedelta(days=14)
        out[f"start.{key}"] = start.isoformat()
        out[f"ahead.{key}"] = ahead.isoformat()
        out[f"state.{key}"] = "open" if ahead >= ctx.base_date else "missed"
    return out


def diff_lines(base: str, now: str) -> tuple[list[str], list[str]]:
    """The lines added and removed between two texts, by difflib's opcodes."""
    b, n = base.split("\n"), now.split("\n")
    added: list[str] = []
    removed: list[str] = []
    for op, i1, i2, j1, j2 in difflib.SequenceMatcher(None, b, n, autojunk=False).get_opcodes():
        if op in ("replace", "delete"):
            removed += b[i1:i2]
        if op in ("replace", "insert"):
            added += n[j1:j2]
    return added, removed


def fk_rows(spec: str) -> list[list[str]]:
    return rows(section(spec, "13.2 "), "FK")


def compute(ctx: Ctx) -> dict[str, str]:
    res = ctx.results
    v: dict[str, str] = {"sha": ctx.cbase, "pins": str(len(endpoints(ctx.spec)))}
    changed = set(git("diff", "--name-only", BQ_BASE, ctx.cbase).split())
    cited = {key_path(k, ctx.cbase) for k, _, _ in cite_spans(ctx.spec)}
    v["bq-moved"] = str(len({p for p in cited if p} & changed))
    for s in "abc":
        for n in res["params"]["sizes"]:
            v[f"verdict.{s}_{n}"] = verdict(res, cell(res, s, n))
    dec = decide(res)
    v["fellback"] = "true" if dec["fellBack"] else "false"
    for sw in res["sweep"]:
        v[f"sweep.{sw['k']}.drag"] = fmt(sw["drag"]["p95"], 3)
    v["grammar"] = str(grammar_equal(ctx.spec))
    v["sink.setters"] = str(sink_setters(ctx))
    v.update(ring_values(ctx.cbase))
    lr = res["liveRegion"]
    v["live.value-p50"] = str(round(lr["valueLatencyMs"]["p50"]))
    v["live.value-p95"] = str(round(lr["valueLatencyMs"]["p95"]))
    fk = fk_rows(ctx.spec)
    v["fk"] = str(len(fk))
    for sev in SEVERITIES:
        v[f"fk.{sev.lower()}"] = str(sum(1 for r in fk if len(r) > 1 and r[1] == sev))
    v.update(sprint_values(ctx))
    if ctx.merged_spec is None:
        v["edit.14"] = str(len(diff_lines(ctx.p14_base, ctx.p14)[1]))
        v["edit.05"] = str(len(diff_lines(ctx.p05_base, ctx.p05)[0]))
    else:  # frozen at the first commit's counts: the edits are merged text by then
        v["edit.14"], v["edit.05"] = "1", "4"
    return v


# ------------------------------------------------------------------------------------- gates


Findings = list[tuple[str, str]]
RUN_ERRORS = (
    OSError,
    ValueError,
    KeyError,
    IndexError,
    TypeError,
    AttributeError,
    RuntimeError,
    SystemExit,
    subprocess.SubprocessError,
)


def g_filled(ctx: Ctx, vals: dict[str, str], f: Findings) -> None:
    for m in SLOT.finditer(ctx.spec):
        f.append(("G01-FILLED", f"slot {m[0]} is not filled"))


def g_audit(ctx: Ctx, vals: dict[str, str], f: Findings) -> None:
    for m in AUDIT.finditer(ctx.spec):
        key, val = m[1], m[2]
        if key not in vals:
            f.append(("G02-AUDIT", f"marker {key!r} is not a key the tool computes"))
            continue
        if vals[key] != val:
            f.append(("G02-AUDIT", f"{key}: the marker says {val!r}, the tool {vals[key]!r}"))
        if not ctx.spec[: m.start()].rstrip().rstrip("`").endswith(val):
            f.append(("G02-AUDIT", f"{key}: the visible value before the marker is not {val!r}"))
    # an independent count, not the helper `compute` uses: FK ids in the 13.2 table body
    body = [r[0] for r in table_body(section(ctx.spec, "13.2 ")) if r and r[0].startswith("FK-")]
    shown = re.search(r"FK (\d+) <!-- audit:fk=", ctx.spec)
    if not shown or int(shown[1]) != len(body):
        f.append(("G02-AUDIT", f"fk: the table holds {len(body)} rows, not the marker's"))


def g_cite(ctx: Ctx, vals: dict[str, str], f: Findings) -> None:
    pins = parse_pins(ctx.pins)
    for key, n in sorted(endpoints(ctx.spec)):
        line = ctx.base_line(key, n)
        if line is None or not line.strip():
            f.append(("G03-CITE", f"{key}:{n} does not resolve to a non-blank line at the base"))
            continue
        if (key, n) in pins and pins[(key, n)] != line_hash(line):
            f.append(("G03-CITE", f"{key}:{n} moved: its pin no longer matches the base line"))


def g_pins(ctx: Ctx, vals: dict[str, str], f: Findings) -> None:
    pins = set(parse_pins(ctx.pins))
    ends = endpoints(ctx.spec)
    for k, n in sorted(ends - pins):
        f.append(("G04-PINS", f"{k}:{n} is cited but not pinned"))
    for k, n in sorted(pins - ends):
        f.append(("G04-PINS", f"{k}:{n} is pinned but no longer cited"))


def g_results(ctx: Ctx, vals: dict[str, str], f: Findings) -> None:
    res = ctx.results
    m = res.get("measures", {})
    dec = decide(res)
    for c in res["cells"]:
        p = f"{c['strategy']}_{c['n']}"
        want = {
            f"{p}_nodes": str(c["nodes"]),
            f"{p}_at_p50": fmt(c["at"]["p50"]),
            f"{p}_at_p95": fmt(c["at"]["p95"]),
            f"{p}_drag_p50": fmt(c["drag"]["p50"], 3),
            f"{p}_drag_p95": fmt(c["drag"]["p95"], 3),
        }
        for k, w in want.items():
            if m.get(k) != w:
                f.append(("G05-RESULTS", f"measures.{k} is {m.get(k)!r}, the raw row gives {w!r}"))
    if (
        m.get("window_cap") != str(dec["capAdopted"])
        or res["decision"]["capAdopted"] != dec["capAdopted"]
    ):
        f.append(("G05-RESULTS", "the cap in the results is not the sweep's"))
    if res["decision"]["recommended"] != dec["recommended"]:
        f.append(("G05-RESULTS", "the results' decision is not the rule re-run on the raw rows"))
    if m.get("recommended_strategy") != STRATEGY_NAMES[dec["recommended"]]:
        f.append(("G05-RESULTS", "measures.recommended_strategy is not the decision's"))
    table = table_body(section(ctx.spec, "3.2 "))
    seen = 0
    for r in table:
        if len(r) < 6 or not re.fullmatch(r"\([abc]\)", r[0]):
            continue
        s, n = r[0][1], int(r[1])
        c = cell(res, s, n)
        want_row = [
            str(c["nodes"]),
            f"{fmt(c['at']['p50'])} / {fmt(c['at']['p95'])}",
            f"{fmt(c['drag']['p50'], 3)} / {fmt(c['drag']['p95'], 3)}",
            verdict(res, c),
        ]
        got = [strip_markers(x) for x in r[2:6]]
        if got != want_row:
            f.append(("G05-RESULTS", f"the 3.2 row ({s}) {n} reads {got}, the results {want_row}"))
        seen += 1
    if seen != len(res["cells"]):
        f.append(("G05-RESULTS", f"the 3.2 table has {seen} rows, the results {len(res['cells'])}"))
    for k in MEASURE_USED:
        if k not in m or str(m[k]) not in ctx.spec:
            f.append(("G05-RESULTS", f"measures.{k} does not stand verbatim in the finding"))


def g_recommend(ctx: Ctx, vals: dict[str, str], f: Findings) -> None:
    res = ctx.results
    dec = decide(res)
    sec = section(ctx.spec, "4.2 ")
    name = STRATEGY_NAMES[dec["recommended"]]
    if dec["recommended"] != "c" or f"**Recommended: {name}.**" not in sec:
        f.append(("G06-RECOMMEND", "section 4.2 does not recommend (c), the rule's choice"))
    reason = str(res["measures"].get("recommendation_reason", ""))
    if dec["losers"] and ("accessibility, not cost" not in reason or "lower AT-tree p95" in reason):
        f.append(
            ("G06-RECOMMEND", "the results' reason does not state the accessibility tie-break")
        )
    if "accessibility, not cost" not in sec or "`E06-D03`:103" not in sec:
        f.append(("G06-RECOMMEND", "section 4.2 does not state the tie-break and (b)'s nesting"))
    table = table_body(section(ctx.spec, "4.3 "))
    cost = [r for r in table if r and r[0].startswith("Cost at 500")]
    if not cost or len(cost[0]) < 3:
        f.append(("G06-RECOMMEND", "section 4.3 has no cost row"))
    else:
        if strip_markers(cost[0][1]) != cost_cell(res, "b"):
            f.append(("G06-RECOMMEND", "section 4.3's (b) cost is not the results'"))
        if strip_markers(cost[0][2]) != cost_cell(res, "c"):
            f.append(("G06-RECOMMEND", "section 4.3's (c) cost is not the results'"))
    nest = [r for r in table if r and r[0] == "Role nesting"]
    if not nest or 'second `role="application"`' not in nest[0][1] or "E06-D03" not in nest[0][1]:
        f.append(("G06-RECOMMEND", "section 4.3 does not state why (b) loses (the nested role)"))


def g_live(ctx: Ctx, vals: dict[str, str], f: Findings) -> None:
    table = table_body(section(ctx.spec, "11.2 "))
    region_map = {
        r[0] for r in rows(section(show(ctx.cbase, DESIGN_KEYS["D10"]) or "", "5.1 "), "RG")
    }
    if not table:
        f.append(("G07-LIVE", "section 11.2 has no rows"))
    for r in table:
        if len(r) < 7:
            f.append(("G07-LIVE", f"{r[0]!r}: {len(r)} cells, not 7"))
            continue
        event, vc, host, pol, text, rate, src = r[:7]
        hosts = re.findall(r"RG-\d\d", host)
        if not hosts or any(h not in RULED_HOSTS or h not in region_map for h in hosts):
            f.append(("G07-LIVE", f"{event}: host {host!r} is not from the ruled set of regions"))
        if pol not in POLITENESS:
            f.append(("G07-LIVE", f"{event}: politeness {pol!r} is not from the set"))
        if pol.startswith("assertive") != (hosts == ["RG-04"]) or (
            pol.startswith("assertive") and "access" not in event.lower()
        ):
            f.append(("G07-LIVE", f"{event}: only RG-04's access row is assertive"))
        if not RATE.match(rate):
            f.append(("G07-LIVE", f"{event}: rate {rate!r} is not from the ruled vocabulary"))
        if "coalesced" in pol and "latest wins" not in rate:
            f.append(("G07-LIVE", f"{event}: a coalesced row does not say latest wins"))
        hay = ctx.hay(src)
        if not any(h.startswith(f"| {vc} ") for h in hay):
            f.append(("G07-LIVE", f"{event}: {vc} is not defined on the cited line"))
        quotes = QUOTE.findall(text)
        if not quotes:
            f.append(("G07-LIVE", f"{event}: no quoted text"))
        for q in quotes:
            if not quoted_ok(q, hay):
                f.append(("G07-LIVE", f"{event}: {q[:40]!r} is not on the cited line"))
    for r in table_body(section(ctx.spec, "14.2 ")):
        if len(r) < 6:
            continue
        for q in QUOTE.findall(r[3]):
            if not quoted_ok(q, ctx.hay(r[5])):
                f.append(("G07-LIVE", f"14.2 step {r[0]}: {q[:40]!r} is not on the cited line"))
    lr = ctx.results["liveRegion"]
    if lr["maxPerSlidingSecond"] > 2 or lr["confirmationsPending"] != 0:
        f.append(("G07-LIVE", "the harness session broke the budget or dropped a confirmation"))
    ck = rows(section(ctx.spec, "11.4 "), "CK")
    if not ck or '"slot + 250 ms"' not in ck[0][2] or "latest-wins" not in ck[0][2]:
        f.append(("G07-LIVE", "CK-01 does not state the latest-wins, slot + 250 ms restatement"))


def g_findings(ctx: Ctx, vals: dict[str, str], f: Findings) -> None:
    sec = section(ctx.spec, "13.")
    fr = fk_rows(ctx.spec)
    if not fr:
        f.append(("G08-FINDINGS", "no FK row found"))
    for r in fr:
        if len(r) < 10:
            f.append(("G08-FINDINGS", f"{r[0]}: {len(r)} cells, not 10"))
            continue
        if r[1] not in SEVERITIES:
            f.append(("G08-FINDINGS", f"{r[0]}: severity {r[1]!r}"))
        if not r[4] or r[4] in ("—", "n/a"):
            f.append(("G08-FINDINGS", f"{r[0]}: no reason"))
        if not OWNER.match(r[5]):
            f.append(("G08-FINDINGS", f"{r[0]}: the owner is not one spec and its area"))
        elif r[5] not in RULED_OWNERS:
            f.append(("G08-FINDINGS", f"{r[0]}: the owner is not one of the ruled owners"))
        if not r[6]:
            f.append(("G08-FINDINGS", f"{r[0]}: the target cell is empty"))
        if not G_T2.match(r[7]):
            f.append(("G08-FINDINGS", f"{r[0]}: G-T2 {r[7]!r} is not from the set"))
        if not FOCUS.match(r[8]):
            f.append(("G08-FINDINGS", f"{r[0]}: Focus {r[8]!r} is not from the set"))
        if r[9] != "n/a" and not RATE.match(r[9]):
            f.append(("G08-FINDINGS", f"{r[0]}: Rate {r[9]!r} is not from the set"))
    blocking = any(len(r) > 1 and r[1] == "Blocking" for r in fr)
    if blocking == (SEV_HOLD in sec):
        f.append(("G08-FINDINGS", "the hold sentence does not match the Blocking rows"))


def g_proposed(ctx: Ctx, vals: dict[str, str], f: Findings) -> None:
    ck = rows(section(ctx.spec, "11.4 "), "CK")
    ids = {r[0] for r in ck}
    for r in ck:
        owners = re.findall(r"`[^`]+`", r[3]) if len(r) > 3 else []
        spec_owners = [o for o in owners if re.match(r"`E\d\d-", o)]
        if not spec_owners or any(not OWNER.match(o) for o in spec_owners):
            f.append(("G09-PROPOSED", f"{r[0]}: the owner is not in the ruled form"))
        for need in CK_OWNERS.get(r[0], ()):
            if need not in spec_owners:
                f.append(("G09-PROPOSED", f"{r[0]}: the ruled owner {need} is missing"))
        for o in spec_owners:
            if o not in RULED_OWNERS:
                f.append(("G09-PROPOSED", f"{r[0]}: {o} is not one of the ruled owners"))
    for i, ln in enumerate(ctx.spec.split("\n"), 1):
        if "PROPOSED" not in ln or ln.startswith("| CK-"):
            continue
        named = re.findall(r"CK-\d\d", ln)
        if named and all(n in ids for n in named):
            continue
        if re.search(r"owner|owned by", ln):
            continue
        f.append(("G09-PROPOSED", f"line {i}: a PROPOSED string with no owner"))


def g_hygiene(ctx: Ctx, vals: dict[str, str], f: Findings) -> None:
    own = {"the finding": ctx.spec, "the tool": ctx.tool, "the pins": ctx.pins}
    every = {**own, **ctx.harness, "the results": json.dumps(ctx.results)}
    for name, text in every.items():
        low = text.lower()
        for word in BANNED:
            if word in low:
                f.append(("G10-HYGIENE", f"{name}: a word from the private list"))
    for name, text in own.items():
        for pat, what in (
            (URL, "a URL"),
            (UUID, "a uuid"),
            (LOCAL_PATH, "a local path"),
            (AGENT, "an agent name"),
        ):
            m = pat.search(text)
            if m:
                f.append(("G10-HYGIENE", f"{name}: {what} {m[0][:24]!r}"))
    if CLOSING.search(ctx.spec):
        f.append(("G10-HYGIENE", "the finding carries a closing keyword before an issue number"))


def d02_keys(ctx: Ctx) -> set[str]:
    out: set[str] = set()
    for n in range(111, 125):
        m = re.search(r"\|\s*`(Alt\+[A-Z])`", ctx.base_line("D02", n) or "")
        if m:
            out.add(m[1])
    return out


def g_keys(ctx: Ctx, vals: dict[str, str], f: Findings) -> None:
    for i, ln in enumerate(ctx.spec.split("\n"), 1):
        if any(k in ln for k in HARNESS_ONLY) and "harness-only" not in ln:
            f.append(("G11-KEYS", f"line {i}: a harness-only key without its label"))
    arm = [r for r in table_body(section(ctx.spec, "7.2 ")) if r and "arm trendline" in r[2]]
    keys = set(re.findall(r"`(Alt\+[A-Z])`", arm[0][1])) if arm else set()
    if not keys or keys != d02_keys(ctx):
        f.append(("G11-KEYS", f"the 7.2 arming keys {sorted(keys)} are not D02's registry keys"))
    reg = ctx.base_line("D02", 96) or ""
    want: dict[str, set[str]] = {}
    for label, pat in (
        ("One anchor", r"exactly 1 anchor (.*?); 2 for"),
        ("Two anchors", r"; 2 for (.*?); 3 for"),
        ("Three anchors", r"; 3 for (.*?); 2\.\.500"),
    ):
        m = re.search(pat, reg)
        want[label] = set(re.findall(r"`([a-z_]+)`", m[1])) if m else set()
    for r in table_body(section(ctx.spec, "6.2 ")):
        if r and r[0] in want and set(re.findall(r"`([a-z_]+)`", r[1])) != want[r[0]]:
            f.append(("G11-KEYS", f"6.2 {r[0]}: the tools are not D02's anchor class"))
    line14 = [
        ln for ln in ctx.p14.split("\n") if ln.startswith("- **Interactions:** keyboard tool")
    ]
    if not line14 or any(f"`{k}`" in line14[0] for k in TICKET_KEYS):
        f.append(("G11-KEYS", "a ticket key survives in the SCR-037 Interactions line"))


def g_ruled(ctx: Ctx, vals: dict[str, str], f: Findings) -> None:
    sec = section(ctx.spec, "R. ")
    listed = [r[0] for r in rows(sec, "BQ")]
    if listed != [f"BQ-{n:02d}" for n in range(1, BQ_COUNT + 1)]:
        f.append(("G12-RULED", f"section R lists {len(listed)} BQ rows, not BQ-01..BQ-{BQ_COUNT}"))
    for r in rows(sec, "BQ"):
        if r[-1] != RULED_STAMP:
            f.append(("G12-RULED", f"{r[0]}: the status is not the ruling stamp"))
    if "<!-- BQ-" in ctx.spec or RULED_STAMP not in ctx.spec.split("## Read first")[0]:
        f.append(("G12-RULED", "a BQ marker is left, or the header does not carry the ruling"))
    for m in re.finditer(r"RULED (BQ-\d\d)((?:, BQ-\d\d)*)", ctx.spec):
        for bq in [m[1], *re.findall(r"BQ-\d\d", m[2])]:
            if bq not in listed:
                f.append(("G12-RULED", f"a stamp names {bq}, which section R does not list"))


def g_scope(ctx: Ctx, vals: dict[str, str], f: Findings) -> None:
    for p in ctx.changed:
        # post-merge, a fix to this tool may ship in one bundle with its sibling design tools
        sibling = ctx.merged_spec is not None and p.startswith("docs/design/_tools/")
        own = p in OWN or p in (P05_REL, P14_REL) or p.startswith(HARNESS_DIR)
        if not own and not sibling:
            f.append(("G13-SCOPE", f"{p} is outside the edit set"))


def quoted_block(spec: str, prefix: str) -> list[str]:
    return [ln[2:] for ln in section(spec, prefix).split("\n") if ln.startswith("> ")]


def g_edits(ctx: Ctx, vals: dict[str, str], f: Findings) -> None:
    q14 = quoted_block(ctx.spec, "16.2 ")
    q05 = quoted_block(ctx.spec, "16.1 ")
    now14 = ctx.p14.split("\n")
    if not q14 or q14[0] not in now14:
        f.append(("G14-EDITS", "the 16.2 quote is not the `14` line"))
    else:
        i = now14.index(q14[0])
        entry = next((ln for ln in reversed(now14[:i]) if ln.startswith("### ")), "")
        if not entry.startswith("### SCR-037 ") or "(spikes/E14-K01.md)" not in q14[0]:
            f.append(("G14-EDITS", "the `14` line is not in SCR-037 or does not point here"))
    if len(q05) < 2 or not q05[0].startswith("#### 6.1.1 ") or "\n".join(q05[1:]).strip() == "":
        f.append(("G14-EDITS", "the 16.1 quote is not the 6.1.1 subsection"))
    else:
        block = "\n".join(q05[1:]).strip()
        sub = section(ctx.p05, "6.1.1 ").strip()
        if sub != block:
            f.append(("G14-EDITS", "`05` section 6.1.1 is not the text section 16.1 quotes"))
        cap = str(decide(ctx.results)["capAdopted"])
        if f"up to {cap} surrogates" not in block or "strategy (c)" not in block:
            f.append(("G14-EDITS", "`05` section 6.1.1 does not state (c) and the measured cap"))
    if ctx.merged_spec is not None:
        return
    a14, r14 = diff_lines(ctx.p14_base, ctx.p14)
    if len(r14) != 1 or len(a14) != 1 or not r14[0].startswith("- **Interactions:** keyboard"):
        f.append(("G14-EDITS", f"`14` changes {len(r14)} / {len(a14)} lines, not the one line"))
    a05, r05 = diff_lines(ctx.p05_base, ctx.p05)
    if r05 or [x for x in a05 if x.strip()] != [q05[0], *[x for x in q05[1:] if x.strip()]]:
        f.append(("G14-EDITS", "`05` changes more than the 6.1.1 block"))


def g_freeze(ctx: Ctx, vals: dict[str, str], f: Findings) -> None:
    if ctx.merged_spec is None:
        return
    now = set(ctx.spec.split("\n"))
    for ln in ctx.merged_spec.split("\n"):
        if ln.startswith("|") and not re.match(r"^\|\s*:?-{3,}", ln) and ln not in now:
            f.append(("G15-FREEZE", f"a merged row changed: {ln[:48]!r}"))


def g_contrast(ctx: Ctx, vals: dict[str, str], f: Findings) -> None:
    if float(vals["ring.halo-min"]) < 3.0:
        f.append(("G16-CONTRAST", f"the ring against its halo falls to {vals['ring.halo-min']}:1"))
    if vals["ring.both-low"] != "0":
        f.append(("G16-CONTRAST", "a candle ink defeats both the ring and its halo"))
    method = section(ctx.spec, "12.4 ")
    for need in ("Brettel (1997) / Viénot", "Machado, Oliveira and Fernandes 2009", "CIELAB"):
        if need not in method:
            f.append(("G16-CONTRAST", f"section 12.4 does not state what ran ({need!r})"))
    if len(ctx.tritan) != 9 or any(
        not math.isclose(a, b, abs_tol=1e-9) for a, b in zip(ctx.tritan, MACHADO_2009_TRITAN)
    ):
        f.append(("G16-CONTRAST", "the imported tritan matrix is not the published Machado one"))


def g_window(ctx: Ctx, vals: dict[str, str], f: Findings) -> None:
    res = ctx.results
    dec = decide(res)
    sec = section(ctx.spec, "5.3 ")
    nxt = [sw for sw in res["sweep"] if sw["k"] > dec["cap"]]
    if not nxt or all(gate_ok(res, min(nxt, key=lambda x: x["k"]))):
        f.append(("G17-WINDOW", "the swept K above the cap does not fail a gate"))
    if f"**{dec['capAdopted']}**" not in sec or "n = 40" not in sec or "contended" not in sec:
        f.append(("G17-WINDOW", "section 5.3 does not state the cap with n and evidence class"))
    for n in res["params"]["sizes"]:
        p50 = cell(res, "c", n)["window"]["p50"]
        if f"p50 {p50} of {n}" not in sec:
            f.append(("G17-WINDOW", f"the natural window at {n} is not the results' median"))


def g_defs(ctx: Ctx, vals: dict[str, str], f: Findings) -> None:
    for label, key, n, pat in DEFS:
        line = ctx.base_line(key, n) or ""
        if not re.search(pat, line):
            f.append(("G18-DEFS", f"{label}: {key}:{n} is not its definition line"))
        if (key, n) not in endpoints(ctx.spec):
            f.append(("G18-DEFS", f"{label}: the finding does not cite it at {key}:{n}"))


T2_KEY = re.compile(r'^`rbac\.view_as` · `rbac\.permission` "save workspaces"$')


def g_t2(ctx: Ctx, vals: dict[str, str], f: Findings) -> None:
    sec = section(ctx.spec, "6.5 ")
    flat = re.sub(r"\s+", " ", sec)
    for need in (
        "CMP-079 RbacGate",
        "CMP-019 `lock`",
        "`decorative={false}`",
        '"Not available"',
        '`aria-disabled="true"`, never `disabled`',
        "in the DOM at mount",
        "`aria-describedby`",
    ):
        if need not in flat:
            f.append(("G19-T2", f"section 6.5 does not state {need!r}"))
    t2 = rows(sec, "T2")
    if not t2:
        f.append(("G19-T2", "no T2 row found"))
    for r in t2:
        if len(r) < 8:
            f.append(("G19-T2", f"{r[0]}: {len(r)} cells"))
            continue
        if not T2_KEY.match(r[2]):
            f.append(("G19-T2", f"{r[0]}: the key and verb are not the T2 legs"))
        if "CMP-079 RbacGate" not in r[3] or "CMP-019 `lock`" not in r[3]:
            f.append(("G19-T2", f"{r[0]}: the component is not CMP-079 with CMP-019"))
        if not re.match(r"^T2 · 2[ab]\b", r[4]):
            f.append(("G19-T2", f"{r[0]}: no T2 rendering"))
        if not FOCUS.match(r[5]) or not RATE.match(r[6]):
            f.append(("G19-T2", f"{r[0]}: Focus or Rate is not from its set"))


def g_grammar(ctx: Ctx, vals: dict[str, str], f: Findings) -> None:
    d07 = engine("e14_d07_tree_audit")
    got = grammar_rows(ctx.spec)
    if [t for t, _ in got] != list(d07.EXAMPLES):
        f.append(("G20-GRAMMAR", "the 8.2 tools are not D07's 25, in D07's order"))
    for tool, example in got:
        want = d07.template(tool, d07.EXAMPLES[tool]) if tool in d07.EXAMPLES else None
        if example != want:
            f.append(("G20-GRAMMAR", f"{tool}: {example!r} is not D07's {want!r}"))


GATES: list[tuple[str, Callable[[Ctx, dict[str, str], Findings], None]]] = [
    ("G01-FILLED", g_filled),
    ("G02-AUDIT", g_audit),
    ("G03-CITE", g_cite),
    ("G04-PINS", g_pins),
    ("G05-RESULTS", g_results),
    ("G06-RECOMMEND", g_recommend),
    ("G07-LIVE", g_live),
    ("G08-FINDINGS", g_findings),
    ("G09-PROPOSED", g_proposed),
    ("G10-HYGIENE", g_hygiene),
    ("G11-KEYS", g_keys),
    ("G12-RULED", g_ruled),
    ("G13-SCOPE", g_scope),
    ("G14-EDITS", g_edits),
    ("G15-FREEZE", g_freeze),
    ("G16-CONTRAST", g_contrast),
    ("G17-WINDOW", g_window),
    ("G18-DEFS", g_defs),
    ("G19-T2", g_t2),
    ("G20-GRAMMAR", g_grammar),
]


def run(ctx: Ctx) -> tuple[dict[str, str], Findings]:
    f: Findings = []
    try:
        vals = compute(ctx)
    except RUN_ERRORS as e:  # default-deny: an unreadable input is a FAIL of every gate
        return {}, [(code, f"the numbers could not be computed: {e}") for code, _ in GATES]
    for code, gate in GATES:
        try:
            gate(ctx, vals, f)
        except RUN_ERRORS as e:  # default-deny: an unreadable input is a FAIL
            f.append((code, f"the gate could not run: {type(e).__name__}: {e}"))
    return vals, f


# ---------------------------------------------------------------------------------- writers


def fill(ctx: Ctx) -> str:
    vals = compute(ctx)
    measures = {k: str(v) for k, v in ctx.results.get("measures", {}).items()}

    def slot(m: re.Match[str]) -> str:
        tick_a, kind, key, tick_b = m[1], m[2], m[3], m[4]
        if kind == "MEASURE":
            return f"{tick_a}{measures[key]}{tick_b}" if key in measures else m[0]
        if key not in vals:
            return m[0]
        return f"{tick_a}{vals[key]}{tick_b} <!-- audit:{key}={vals[key]} -->"

    spec = SLOT.sub(slot, ctx.spec)
    out = []
    for ln in spec.split("\n"):
        for m in list(AUDIT.finditer(ln)):
            key, old = m[1], m[2]
            if key in vals and old != vals[key]:
                new = vals[key]
                for tick in ("", "`"):
                    ln = ln.replace(
                        f"{old}{tick} <!-- audit:{key}={old} -->",
                        f"{new}{tick} <!-- audit:{key}={new} -->",
                    )
        out.append(ln)
    return "\n".join(out)


def repin(ctx: Ctx) -> str:
    lines = [
        "# E14-K01 pins: one cited endpoint per line, `KEY:line sha1-16` of its words at the cite base.",
        "# Written only by `e14_k01_spike_audit.py --repin-ruled`.",
    ]
    for key, n in sorted(endpoints(ctx.spec), key=lambda x: (x[0], x[1])):
        line = ctx.base_line(key, n) or ""
        lines.append(f"{key}:{n} {line_hash(line)}")
    return "\n".join(lines) + "\n"


# -------------------------------------------------------------------------------- self-test


def _swap(text: str, old: str, new: str) -> str:
    if old not in text:
        raise ValueError(f"mutation anchor missing: {old[:40]!r}")
    return text.replace(old, new, 1)


def set_cell(text: str, row_id: str, index: int, value: str) -> str:
    out = []
    done = False
    for ln in text.split("\n"):
        if not done and re.match(rf"^\|\s*{re.escape(row_id)}\s*\|", ln):
            parts = ln.split("|")
            parts[index + 1] = f" {value} "
            ln = "|".join(parts)
            done = True
        out.append(ln)
    if not done:
        raise ValueError(f"mutation anchor missing: row {row_id}")
    return "\n".join(out)


def _resub(text: str, pattern: str, repl: str) -> str:
    out, n = re.subn(pattern, repl, text, count=1, flags=re.MULTILINE)
    if not n:
        raise ValueError(f"mutation anchor missing: {pattern}")
    return out


def first(pattern: str, text: str) -> str:
    m = re.search(pattern, text, re.MULTILINE)
    if not m:
        raise ValueError(f"mutation anchor missing: {pattern}")
    return m[0]


def with_results(c: Ctx, edit: Callable[[dict[str, Any]], None]) -> Ctx:
    res = json.loads(json.dumps(c.results))
    edit(res)
    return dataclasses.replace(c, results=res)


def _measure(key: str, value: str) -> Callable[[dict[str, Any]], None]:
    def edit(res: dict[str, Any]) -> None:
        res["measures"][key] = value

    return edit


def _session(res: dict[str, Any]) -> None:
    res["liveRegion"]["maxPerSlidingSecond"] = 3


def _sweep300(res: dict[str, Any]) -> None:
    for sw in res["sweep"]:
        if sw["k"] >= 300:
            sw["drag"]["p95"] = 1.5
            sw["at"]["p95"] = 50.0


MUTATIONS: list[tuple[str, Callable[[Ctx], Ctx]]] = [
    ("G01-FILLED", lambda c: dataclasses.replace(c, spec=c.spec + "\n{{TOOL:fk}}\n")),
    (
        "G02-AUDIT",
        lambda c: dataclasses.replace(
            c, spec=_swap(c.spec, first(r"<!-- audit:fk=\d+ -->", c.spec), "<!-- audit:fk=99 -->")
        ),
    ),
    (
        "G02-AUDIT",
        lambda c: dataclasses.replace(
            c,
            spec=_swap(
                c.spec,
                "\n| FK-08 |",
                "\n| FK-09 | Info | x | y | z | w | v | n/a | n/a | n/a |\n| FK-08 |",
            ),
        ),
    ),
    (
        "G03-CITE",
        lambda c: dataclasses.replace(
            c,
            pins=re.sub(
                r"^(D02:\d+) [0-9a-f]{16}$",
                r"\1 0000000000000000",
                c.pins,
                count=1,
                flags=re.MULTILINE,
            ),
        ),
    ),
    ("G04-PINS", lambda c: dataclasses.replace(c, spec=c.spec + "\nSee `D02`:5.\n")),
    ("G05-RESULTS", lambda c: with_results(c, _measure("c_500_nodes", "210"))),
    (
        "G05-RESULTS",
        lambda c: dataclasses.replace(
            c, spec=_resub(c.spec, r"^(\|\s*\(a\)\s*\|\s*500\s*\|\s*)\d+", r"\g<1>999")
        ),
    ),
    (
        "G06-RECOMMEND",
        lambda c: with_results(
            c,
            _measure(
                "recommendation_reason",
                "survivors (b), (c); then the lower AT-tree p95 at 500: (c)",
            ),
        ),
    ),
    (
        "G06-RECOMMEND",
        lambda c: dataclasses.replace(
            c,
            spec=set_cell(
                c.spec, "Cost at 500 (nodes; AT p95 ms; drag p95 ms)", 1, "70; 6.00; 0.080"
            ),
        ),
    ),
    (
        "G07-LIVE",
        lambda c: dataclasses.replace(c, spec=set_cell(c.spec, "Snap candidate", 2, "RG-02")),
    ),
    (
        "G07-LIVE",
        lambda c: dataclasses.replace(
            c, spec=set_cell(c.spec, "Lock refusal", 4, '"This drawing is now locked."')
        ),
    ),
    (
        "G07-LIVE",
        lambda c: dataclasses.replace(c, spec=set_cell(c.spec, "Mode change", 5, "whenever")),
    ),
    (
        "G07-LIVE",
        lambda c: dataclasses.replace(
            c, spec=set_cell(c.spec, "Cancel", 3, 'assertive (`role="alert"`)')
        ),
    ),
    ("G07-LIVE", lambda c: with_results(c, _session)),
    ("G08-FINDINGS", lambda c: dataclasses.replace(c, spec=set_cell(c.spec, "FK-02", 1, "Severe"))),
    (
        "G08-FINDINGS",
        lambda c: dataclasses.replace(c, spec=set_cell(c.spec, "FK-06", 5, "the design lead")),
    ),
    (
        "G08-FINDINGS",
        lambda c: dataclasses.replace(c, spec=set_cell(c.spec, "FK-03", 9, "sometimes")),
    ),
    (
        "G09-PROPOSED",
        lambda c: dataclasses.replace(c, spec=set_cell(c.spec, "CK-01", 3, "the review team")),
    ),
    (
        "G09-PROPOSED",
        lambda c: dataclasses.replace(c, spec=c.spec + "\nA new rule is PROPOSED here.\n"),
    ),
    (
        "G09-PROPOSED",
        lambda c: dataclasses.replace(
            c, spec=set_cell(c.spec, "CK-01", 3, "`E14-D10 · area/charting-ui`")
        ),
    ),
    (
        "G09-PROPOSED",
        lambda c: dataclasses.replace(
            c, spec=set_cell(c.spec, "CK-01", 3, "`E06-D03 · area/chart-engine`")
        ),
    ),
    (
        "G08-FINDINGS",
        lambda c: dataclasses.replace(
            c, spec=set_cell(c.spec, "FK-03", 5, "`E14-D99 · area/nonsense`")
        ),
    ),
    (
        "G02-AUDIT",
        lambda c: dataclasses.replace(
            c, spec=_swap(c.spec, "audit:ring.under3=", "audit:ring.under3=none ")
        ),
    ),
    (
        "G10-HYGIENE",
        lambda c: dataclasses.replace(c, spec=c.spec + "\n" + BANNED[8].upper() + "\n"),
    ),
    (
        "G10-HYGIENE",
        lambda c: dataclasses.replace(
            c,
            harness={**c.harness, HARNESS_JS: c.harness.get(HARNESS_JS, "") + "\n// " + BANNED[0]},
        ),
    ),
    (
        "G11-KEYS",
        lambda c: dataclasses.replace(
            c, spec=c.spec + "\nThe polyline closes with `Shift+Enter`.\n"
        ),
    ),
    (
        "G11-KEYS",
        lambda c: dataclasses.replace(
            c, spec=_swap(c.spec, "`Alt+L` / `Alt+H` / `Alt+R`", "`Alt+T` / `Alt+H` / `Alt+R`")
        ),
    ),
    (
        "G11-KEYS",
        lambda c: dataclasses.replace(
            c,
            spec=_resub(
                c.spec,
                r"^(\|\s*One anchor\s*\|\s*)`horizontal_line`",
                r"\g<1>`ray`, `horizontal_line`",
            ),
        ),
    ),
    (
        "G12-RULED",
        lambda c: dataclasses.replace(c, spec=_swap(c.spec, f"| {RULED_STAMP} |", "| pending |")),
    ),
    ("G12-RULED", lambda c: dataclasses.replace(c, spec=c.spec + "\n<!-- BQ-07 -->\n")),
    ("G13-SCOPE", lambda c: dataclasses.replace(c, changed=[*c.changed, "docs/plan/15-x.md"])),
    (
        "G14-EDITS",
        lambda c: dataclasses.replace(c, p14=_swap(c.p14, "`Alt+O` fib", "`Alt+F` fib")),
    ),
    (
        "G14-EDITS",
        lambda c: dataclasses.replace(
            c, p05=_swap(c.p05, "up to 200 surrogates", "up to 300 surrogates")
        ),
    ),
    (
        "G15-FREEZE",
        lambda c: dataclasses.replace(c, merged_spec="| FK-99 | a merged row since changed |\n"),
    ),
    (
        "G16-CONTRAST",
        lambda c: dataclasses.replace(
            c, spec=_swap(c.spec, "Machado, Oliveira and Fernandes 2009", "Machado 2010")
        ),
    ),
    ("G16-CONTRAST", lambda c: dataclasses.replace(c, tritan=(1.0, 0.0, 0.0) * 3)),
    ("G17-WINDOW", lambda c: with_results(c, _sweep300)),
    (
        "G17-WINDOW",
        lambda c: dataclasses.replace(c, spec=_swap(c.spec, "n = 40 builds", "n = 4 builds")),
    ),
    (
        "G18-DEFS",
        lambda c: dataclasses.replace(c, spec=c.spec.replace("`D10`:854", "`D10`:855")),
    ),
    (
        "G19-T2",
        lambda c: dataclasses.replace(c, spec=set_cell(c.spec, "T2-02", 3, "CMP-041 Menu")),
    ),
    (
        "G19-T2",
        lambda c: dataclasses.replace(
            c, spec=_swap(c.spec, "in the\nDOM at mount", "in the\nDOM later")
        ),
    ),
    (
        "G20-GRAMMAR",
        lambda c: dataclasses.replace(
            c,
            spec=_resub(
                c.spec, r"(\|\s*)Vertical line 14:10(\s*\|)", r"\g<1>Vertical line 14:15\g<2>"
            ),
        ),
    ),
]


def frozen_base_problems(ctx: Ctx) -> list[str]:
    """Post-merge cites freeze at the recorded base: a moved merge-base must not move them."""
    out: list[str] = []
    moved = "f" * 40  # stands for a main that has moved on since the finding merged
    if cite_base(moved, None) != moved:
        out.append("PR-1 mode must read at the merge-base")
    if ctx.merged_spec is not None:
        if cite_base(moved, ctx.merged_spec) != ctx.cbase:
            out.append("post-merge mode follows the merge-base, not the recorded base")
        no_marker = ctx.merged_spec.replace("audit:sha=", "audit:unused=")
        if cite_base(moved, no_marker) != moved:
            out.append("post-merge mode with no recorded base must fall back, which G02 then fails")
        stale = re.sub(r"(audit:sha=)[0-9a-f]{40}", r"\g<1>" + "0" * 40, ctx.merged_spec)
        if cite_base(moved, stale) != moved:
            out.append("an unresolvable recorded base was accepted")
    return out


def self_test(ctx: Ctx) -> tuple[int, int, list[str]]:
    _, base = run(ctx)
    problems: list[str] = []
    if base:
        problems.append(f"the base run is not clean: {len(base)} FAIL(s)")
    before = {code for code, _ in base}
    passed = 0
    for code, mutate in MUTATIONS:
        try:
            _, got = run(mutate(ctx))
        except RUN_ERRORS as e:
            problems.append(f"{code}: the mutation could not apply: {e}")
            continue
        hit = [msg for c, msg in got if c == code]
        if hit and code not in before and not any("could not" in m for m in hit):
            passed += 1
        else:
            problems.append(f"{code}: the mutation added no content FAIL of its gate")
    gates = {code for code, _ in GATES}
    if gates - {code for code, _ in MUTATIONS}:
        problems.append("a gate has no mutation")
    problems += frozen_base_problems(ctx)
    return passed, len(MUTATIONS), problems


# ------------------------------------------------------------------------------------- main


def main(argv: list[str]) -> int:
    ap = argparse.ArgumentParser(description=(__doc__ or "").splitlines()[0])
    ap.add_argument("--check", action="store_true", help="exit 1 on any FAIL (a bare run does too)")
    ap.add_argument("--json", action="store_true", help="print the numbers and findings as JSON")
    ap.add_argument(
        "--fill", action="store_true", help="write the computed values into the finding"
    )
    ap.add_argument("--self-test", action="store_true", help="the mutation self-test")
    ap.add_argument("--repin-ruled", action="store_true", help="rewrite the pins file")
    args = ap.parse_args(argv)
    ctx = build_ctx()
    mode = "post-merge" if ctx.merged_spec is not None else "PR-1"
    if args.repin_ruled:
        (ROOT / PINS_REL).write_text(repin(ctx), encoding="utf-8")
        print(f"pins rewritten: {len(endpoints(ctx.spec))} cited endpoints")
        return 0
    if args.fill:
        (ROOT / SPEC_REL).write_text(fill(ctx), encoding="utf-8")
        print("finding filled")
        return 0
    if args.self_test:
        passed, total, problems = self_test(ctx)
        for p in problems:
            print(f"SELF-TEST FAIL {p}")
        print(f"self-test: {passed}/{total} mutations caught; {len(GATES)} gates; mode {mode}")
        return 0 if passed == total and not problems else 1
    vals, f = run(ctx)
    if args.json:
        print(
            json.dumps(
                {
                    "mode": mode,
                    "base": ctx.base,
                    "cite_base": ctx.cbase,
                    "numbers": vals,
                    "findings": f,
                },
                indent=2,
                ensure_ascii=False,
            )
        )
    else:
        for code, msg in f:
            print(f"FAIL [{code}] {msg}")
        print(f"mode {mode}; base {ctx.base[:12]}; {len(GATES)} gates; FAIL {len(f)} / WARN 0")
    return 1 if f else 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
