#!/usr/bin/env python3
"""E38-D02 (#1003) audit: the hi-fi spec of the environment switcher SCR-074 and the demo / live
chrome SCR-075 (CMP-074, CMP-075, CMP-139).

Standalone and offline. It reads the spec and the pins file from the working tree, every cited
file AS TEXT with `git show` at the pinned base (`BASE`), except E38-D01, which is read at #5451's
approved head (`D01_REF`) until it merges. Colour maths imports, as the merged E10-D03 tool does,
`packages/ui/tokens/tests/verify_tokens.py` (the token loader and resolver),
`docs/design/_tools/contrast_check.py` (`contrast_ratio`) and
`docs/research/_tools/cvd_simulate.py` (`simulate`, `delta_e76`, `JND_FLOOR`) from the working
tree, and never re-implements them. Default-deny: a gate that cannot read its input FAILs.

Gates (each FAIL led by its name):
  G-STATE     every SCR-074 / SCR-075 state the ticket and `14` name has a §0 frame row;
              §4.3 holds the rows S74-01 ... S74-08 in order, each named as `STATES` names it
              (`14`:1777's four plus the dialogs' and the gate's), each with a Presentation, a
              Focus · announcement and an Audit cell; and every item of the two `14` sign-off
              checklists appears verbatim in §11's map with a frame.
  G-TOKEN     every design token the spec names (`color.*`, `font.*`, `border.*`, `radius.*`,
              `type.*`, `space.*`, `size.*`, `motion.*`, `opacity.*`) resolves in the token JSON
              at the base.
  G-CONTRAST  every §8.1 row is recomputed per theme (light = semantic-light over dark; hc =
              semantic-hc over dark) and equals the spec to two decimals; a `text` row is
              at least 4.5:1 and a `ui` row at least 3:1 in every theme.
  G-CVD       every §8.2 row's normal / protanopia / deuteranopia / tritanopia ΔE76 equals the
              spec to two decimals, and its JND column names the simulations under 5.0.
  G-HOTKEY    no key chord stands outside §13's rows and A-8: SCR-074 is click- and Tab-reachable
              only (C-2.11; the ticket's AC); and KEYMAP at the base binds no command to the
              environment switch and nothing to Ctrl+Shift+L.
  G-T2        every §4.3 row is classed: V (form validity: it names validity and carries no T2
              rendering and no lock look) or T2 (its reason a quoted sentence). A T2 reason that
              names an E09-D09 §3.1 key is that key's text at the base (its `{slot}` filled);
              any other is marked PROPOSED; S74-07 is `rbac.env` (ruling BQ-22). §4.3 states the
              T2 anatomy once (G-T2.1a-d, G-T2.2, G-T2.6: role and full label, `aria-disabled`,
              the reason node at mount by `aria-describedby`, CMP-079, the CMP-019 `lock`, the
              hi-fi pins), every T2 row cites it, and A-3 names CMP-079 and the `lock`.
  G-RULED     the rulings' texts hold (comment 6577247518): the demo statement verbatim from
              `14`:1787 with its em dash (BQ-10); DEMO `font.weight.medium` (BQ-07); the panel
              LIVE `border.thick` rule present and the word never underlined (BQ-08); "LIVE
              since" outside any live region (BQ-11); the typed match exact and case-sensitive
              (BQ-14); to demo a click-confirm only (BQ-16); the audit on the 200 only, in §4.3's
              prose and in S74-05's Audit cell (BQ-24); and the orchestrator's read: the pill a
              button inside the `role="status"` slot, never itself a status, in §3.1 and §9; the
              exports name all three CVD simulations.
  G-AROW      A-1 … A-9 are all present; every Old text, and A-8's row text, stands exactly once
              in its target at the base and on the line the row cites; A-9's anchor is A-6's
              New text. Applied mode (PR 2): the targets in the working tree read either every
              A-row pending (each Old once, no New, no inserted line, A-8's row present) or every
              A-row applied (each New once and its Old gone; A-1 / A-2 the line right after their
              screen's sign-off checklist, A-3 after CMP-074's Tests line, A-4 after CMP-075's
              As-built line, A-9 the row right after A-6's row; A-8's row gone), never a mix;
              once §0 is drawn (G-DRAWN), every A-row must be applied.
  G-CITE      every cite in range and on a non-blank line at its base, and equal to the pins.
  G-HYGIENE   no closing keyword, local path, URL or host, agent name, double-brace slot or
              deny word in the spec; no deny word in this tool's text or the pins.
  G-DRAWN     §0's frame rows are all pending ("to draw (PR 2)", PR 1) or all drawn (PR 2).
              Drawn: §0 names the page id; every frame row names a board of the board table;
              each board row's Status is `drawn (r<n>[, light])` with its board id and export,
              the export's number, slug and theme agree with the row, and on disk the PNG's
              IHDR width × height and sha256 equal the record; the eight simulations of
              boards 01 and 03 (greyscale, deuteranopia, protanopia, tritanopia) are listed
              with their sha256 and equal it on disk; and no other E38-D02-*.png sits in
              `docs/design/E38/img/`.
  G-SCOPE     the diff touches only the spec, this tool, the pins file, the E38-D02
              exports in `docs/design/E38/img/` and the A-rows' five targets (`14`, `15`,
              `17`, E30-D04, E29-D03).

Usage (from the repo root):
  python3 -I docs/design/_tools/e38_d02_env_chrome_audit.py --check
  python3 -I docs/design/_tools/e38_d02_env_chrome_audit.py --fill        (writes §8's figures)
  python3 -I docs/design/_tools/e38_d02_env_chrome_audit.py --self-test
  python3 -I docs/design/_tools/e38_d02_env_chrome_audit.py --repin-ruled (the pins' only writer)
"""

from __future__ import annotations

import argparse
import hashlib
import importlib.util
import json
import re
import subprocess
import sys
from collections.abc import Callable
from dataclasses import dataclass, replace
from pathlib import Path
from types import ModuleType
from typing import Any

ROOT = Path(__file__).resolve().parents[3]
SPEC_REL = "docs/design/E38/E38-D02.md"
TOOL_REL = "docs/design/_tools/e38_d02_env_chrome_audit.py"
PINS_REL = "docs/design/_tools/e38_d02_ruled_pins.txt"
OWN_PATHS = (SPEC_REL, TOOL_REL, PINS_REL)
AROW_KEYS = (
    "14",
    "15",
    "17",
    "E30D04",
    "E29D03",
)  # the A-rows' targets, applied in PR 2
BASE = "67fe8b5265810d9d7928bdf4b56e4911f16fce54"  # origin/main when written; re-pinned by content
D01_REF = "4774b2f8cd7b67a1ee934fe88546568f7aa3e34c"  # #5451's approved head; re-pinned at merge
TOKENS = ROOT / "packages" / "ui" / "tokens"
CVD_PATH = ROOT / "docs" / "research" / "_tools" / "cvd_simulate.py"
CONTRAST_PATH = ROOT / "docs" / "design" / "_tools" / "contrast_check.py"
KEYMAP_REL = "apps/web/src/keymap/keymap.json"
IMG_REL = "docs/design/E38/img"
IMG = re.compile(r"docs/design/E38/img/E38-D02-\d\d-[a-z0-9-]+\.png")
PENDING = "to draw (PR 2)"
UUID = r"[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}"
DRAWN = re.compile(
    rf"drawn \(r\d+(, light)?\): board id `({UUID})`, "
    r"`docs/design/E38/img/(E38-D02-(\d\d)-([a-z0-9-]+)\.png)` "
    r"\((\d+) × (\d+), sha256 `([0-9a-f]{64})`\)"
)
RENDER = re.compile(
    r"^- `(E38-D02-(\d\d)-[a-z0-9-]+-(greyscale|deuteranopia|protanopia|tritanopia)\.png)` "
    r"\(sha256 `([0-9a-f]{64})`\)$",
    re.MULTILINE,
)
SIMULATED = ("01", "03")
SIMULATIONS = ("greyscale", "deuteranopia", "protanopia", "tritanopia")
PATHS: dict[str, str] = {
    "04": "docs/plan/04-security-program.md",
    "13": "docs/plan/13-user-flows.md",
    "14": "docs/plan/14-screens-catalogue.md",
    "15": "docs/plan/15-component-catalogue.md",
    "16": "docs/plan/16-design-system-brief.md",
    "17": "docs/plan/17-ux-diagrams.md",
    "22": "docs/plan/22-api-openapi.yaml",
    "E10D03": "docs/design/E10/E10-D03.md",
    "E10D04": "docs/design/E10/E10-D04.md",
    "E30D02": "docs/design/E30/E30-D02.md",
    "E30D04": "docs/design/E30/E30-D04.md",
    "E09D09": "docs/design/E09/E09-D09.md",
    "E15D03": "docs/design/E15/E15-D03.md",
    "E11D02": "docs/design/E11/E11-D02.md",
    "E29D03": "docs/design/E29/E29-D03.md",
    "E32D03": "docs/design/E32/E32-D03.md",
    "E33D03": "docs/design/E33/E33-D03.md",
    "D01": "docs/design/research/E38-paper-parity.md",
}
REF_OF = {"D01": D01_REF}
CITE = re.compile(
    r"`(\d\d|E10D03|E10D04|E30D02|E30D04|E09D09|E15D03|E11D02|E29D03|E32D03|E33D03|D01)`"
    r":(\d+(?:–\d+)?(?:, :\d+(?:–\d+)?)*)"
)
TOKEN_NAME = re.compile(
    r"`((?:color|font|border|radius|type|space|size|motion|opacity)\.[a-z0-9.-]*[a-z0-9])`"
)
CHORD = re.compile(r"\b(?:Ctrl|Alt|Meta|Cmd|Shift)\+[A-Za-z0-9]")
CLOSING = re.compile(
    r"\b(?:close[sd]?|fix(?:e[sd])?|resolve[sd]?)\s+#\d+", re.IGNORECASE
)
LOCAL_PATH = re.compile(
    "/" + "home/|/Users/|[A-Za-z]:\\\\|\\bwt-" + "notes\\b"
)  # assembled
AGENT_NAME = re.compile(r"\b[a-z]{2,4}-worker-\d\b")
URL_OR_HOST = re.compile(r"https?://|penpot\.[a-z]|team-id=|file-id=", re.IGNORECASE)
DENY = (
    "le" + "ak",
    "expo" + "sed",
    "by" + "pass",
    "ex" + "ploit",
    "att" + "ack",
    "ora" + "cle",
    "rev" + "eal",
    "unbou" + "nded",
    "flo" + "od",
    "st" + "all",
    "d" + "os",
    "advi" + "sory",
    "gh" + "sa",
    "pre-" + "auth",
)  # each entry an explicit join, so this tool's own text carries none of the words
THEMES = ("dark", "light", "high-contrast")
FLOOR = {"text": 4.5, "ui": 3.0}
DEFICIENCIES = ("protanopia", "deuteranopia", "tritanopia")
# §4.3's state rows, in order: `14`:1777's switching, switched, failed and not permitted, plus
# the idle pill, the two dialogs and the blocked gate
STATES = (
    "idle",
    "confirm-live",
    "confirm-demo",
    "switching",
    "switched",
    "failed",
    "not-permitted",
    "blocked",
)
# the states the ticket's Scope and `14` SCR-074 / SCR-075 name; each needs a §0 frame row
REQUIRED_FRAMES = (
    "SCR-074/idle",
    "SCR-074/confirm-live",
    "SCR-074/confirm-demo",
    "SCR-074/switching",
    "SCR-074/switched",
    "SCR-074/failed",
    "SCR-074/not-permitted",
    "SCR-074/blocked",
    "SCR-075/band-demo",
    "SCR-075/band-live",
    "SCR-075/panels",
    "SCR-075/floating-window",
    "SCR-075/under-modal",
    "SCR-075/demo-statement",
)


@dataclass(frozen=True)
class Texts:
    spec: str
    pins: str
    tool: str
    changed: list[str] | None
    memo: dict[str, str | None]
    files: dict[str, bytes]
    heads: dict[str, str]


def git(*args: str) -> str | None:
    try:
        r = subprocess.run(
            ["git", "-C", str(ROOT), *args], capture_output=True, check=False
        )
    except OSError:
        return None
    return r.stdout.decode("utf-8", "surrogateescape") if r.returncode == 0 else None


def show(t: Texts, rev: str, rel: str) -> str | None:
    key = f"{rev}:{rel}"
    if key not in t.memo:
        t.memo[key] = git("show", key)
    return t.memo[key]


def at(t: Texts, key: str) -> str:
    ref = REF_OF.get(key, BASE)
    text = show(t, ref, PATHS[key])
    if text is None:
        raise SystemExit(f"{PATHS[key]} does not resolve at {ref[:10]}; fetch first")
    return text


def _load(path: Path, name: str) -> ModuleType:
    spec = importlib.util.spec_from_file_location(name, path)
    if spec is None or spec.loader is None:
        raise SystemExit(f"cannot load {path}")
    mod = importlib.util.module_from_spec(spec)
    sys.modules[name] = mod
    spec.loader.exec_module(mod)
    return mod


_MODS: dict[str, ModuleType] = {}


def mod(name: str) -> ModuleType:
    if name not in _MODS:
        if name == "verify_tokens":
            sys.path.insert(0, str(TOKENS / "tests"))
            _MODS[name] = _load(TOKENS / "tests" / "verify_tokens.py", name)
        elif name == "contrast_check":
            _MODS[name] = _load(CONTRAST_PATH, name)
        else:
            _MODS[name] = _load(CVD_PATH, name)
    return _MODS[name]


def cvd() -> ModuleType:
    return mod("cvd_simulate")


def norm(s: str) -> str:
    return " ".join(s.split())


def table_rows(text: str, lead: str) -> list[list[str]]:
    out = []
    for ln in text.split("\n"):
        if ln.startswith("| " + lead):
            out.append([c.strip() for c in ln.strip().strip("|").split("|")])
    return out


def section(text: str, head: str) -> str:
    i = text.find("\n" + head)
    if i < 0:
        return ""
    depth = head.split(" ")[0]
    j = text.find("\n" + depth + " ", i + 1)
    return text[i : j if j > 0 else len(text)]


# ---------------------------------------------------------------------------- tokens


_THEMES: dict[str, dict[str, str]] = {}


def theme(name: str) -> dict[str, str]:
    """The colour tokens of one theme, resolved as E10-D03's tool does."""
    if name not in _THEMES:
        v = mod("verify_tokens")
        allt: dict[str, Any] = dict(v.load(v.PRIMITIVES))
        allt.update(v.merged_set(v.THEMES[name]))
        _THEMES[name] = {
            k: str(v.resolve(tok["$value"], allt)).upper()
            for k, tok in allt.items()
            if isinstance(tok, dict) and tok.get("$type") == "color"
        }
    return _THEMES[name]


def known_tokens() -> set[str]:
    v = mod("verify_tokens")
    names: set[str] = set(v.load(v.PRIMITIVES))
    for th in THEMES:
        names |= set(v.merged_set(v.THEMES[th]))
    return names


def hex_rgb(h: str) -> tuple[int, int, int]:
    h = h.lstrip("#")
    return int(h[0:2], 16), int(h[2:4], 16), int(h[4:6], 16)


def color(th: str, name: str) -> str:
    t = theme(th)
    if name not in t:
        raise LookupError(f"`{name}` does not resolve in {th}")
    return t[name][:7]


# ---------------------------------------------------------------------------- figures


def contrast_rows(t: Texts) -> list[list[str]]:
    return table_rows(section(t.spec, "### 8.1"), "P-")


def cvd_rows(t: Texts) -> list[list[str]]:
    return table_rows(section(t.spec, "### 8.2"), "V-")


def tok(cell: str) -> str:
    m = re.fullmatch(r"`([a-z0-9.-]+)`", cell)
    if not m:
        raise LookupError(f"{cell!r} is not one token")
    return m[1]


def contrast_values(t: Texts, row: list[str]) -> list[str]:
    cc = mod("contrast_check")
    fg, bg = tok(row[1]), tok(row[2])
    return [
        f"{cc.contrast_ratio(hex_rgb(color(th, fg)), hex_rgb(color(th, bg))):.2f}"
        for th in THEMES
    ]


def cvd_values(t: Texts, row: list[str]) -> tuple[str, str]:
    cv = cvd()
    th = {"hc": "high-contrast"}.get(row[3], row[3])
    a, b = tok(row[1]), tok(row[2])
    ha, hb = color(th, a), color(th, b)
    ds = [cv.delta_e76(ha, hb)] + [
        cv.delta_e76(cv.simulate(ha, d), cv.simulate(hb, d)) for d in DEFICIENCIES
    ]
    under = [
        n
        for n, d in zip(("normal", *DEFICIENCIES), ds, strict=True)
        if d < cv.JND_FLOOR
    ]
    return " / ".join(f"{d:.2f}" for d in ds), (", ".join(under) if under else "none")


# ---------------------------------------------------------------------------- cites


def cites(text: str) -> list[tuple[str, int, int]]:
    out = []
    for m in CITE.finditer(text):
        for part in m[2].split(", :"):
            a, _, b = part.partition("–")
            out.append((m[1], int(a), int(b or a)))
    return out


def cite_hashes(t: Texts) -> tuple[dict[str, str], list[str]]:
    hashes: dict[str, str] = {}
    bad: list[str] = []
    for key, a, b in cites(t.spec):
        label = f"{key}:{a}" if a == b else f"{key}:{a}–{b}"
        if label in hashes:
            continue
        ls = at(t, key).split("\n")
        if not 0 < a <= b <= len(ls):
            bad.append(f"{label} is past the end of {PATHS[key]} ({len(ls)} lines)")
            continue
        blank = [n for n in (a, b) if not ls[n - 1].strip()]
        if blank:
            bad.append(f"{label}: line {blank[0]} is blank at its base")
            continue
        joined = norm(ls[a - 1]) + "\n" + norm(ls[b - 1])
        hashes[label] = hashlib.sha256(joined.encode()).hexdigest()[:12]
    return hashes, bad


def parse_pins(text: str) -> dict[str, str]:
    out = {}
    for ln in text.split("\n"):
        parts = ln.split("\t")
        if len(parts) == 2 and not ln.startswith("#"):
            out[parts[0]] = parts[1]
    return out


# ---------------------------------------------------------------------------- gates


def checklist(t: Texts, scr: str) -> list[str]:
    body = at(t, "14")
    i = body.find(f"### {scr} ")
    j = body.find("\n### ", i + 1)
    block = body[i:j]
    m = re.search(r"Design sign-off acceptance checklist:\*\* (.*)", block)
    if not m:
        raise LookupError(f"`14` {scr} has no sign-off checklist at the base")
    return [norm(x) for x in m[1].split("[ ]") if x.strip()]


def g_state(t: Texts) -> list[str]:
    bad = []
    frames = {
        r[1].strip("`") for r in table_rows(section(t.spec, "## 0."), "B") if len(r) > 1
    }
    for f in REQUIRED_FRAMES:
        if f not in frames:
            bad.append(f"no §0 frame row for `{f}`")
    srows = table_rows(section(t.spec, "### 4.3"), "S74-")
    if [r[0] for r in srows] != [f"S74-{i:02d}" for i in range(1, len(STATES) + 1)]:
        bad.append(
            f"§4.3's rows are {[r[0] for r in srows]}, not S74-01 ... S74-08 in order"
        )
    for r, name in zip(srows, STATES):
        if len(r) != 6:
            bad.append(f"{r[0]}: {len(r)} cells, not 6")
            continue
        if r[1] != name:
            bad.append(f"{r[0]}: named {r[1]!r}, not {name!r}")
        for col, what in (
            (3, "Presentation"),
            (4, "Focus · announcement"),
            (5, "Audit"),
        ):
            if not r[col].strip():
                bad.append(f"{r[0]}: an empty {what} cell")
    rows = table_rows(section(t.spec, "## 11."), "K")
    mapped = {norm(r[1].strip('"')): r[2] for r in rows if len(r) > 2}
    for scr in ("SCR-074", "SCR-075"):
        for item in checklist(t, scr):
            if item not in mapped:
                bad.append(f"{scr} checklist item not mapped verbatim: {item[:60]!r}")
            elif not re.search(r"SCR-07[45]/[a-z-]+", mapped[item]):
                bad.append(f"{scr} checklist item mapped to no frame: {item[:60]!r}")
    return bad


def g_token(t: Texts) -> list[str]:
    known = known_tokens()
    names = sorted(set(TOKEN_NAME.findall(t.spec)))
    return [
        f"`{n}` does not resolve in the token JSON at the base"
        for n in names
        if n not in known
    ]


def g_contrast(t: Texts) -> list[str]:
    bad = []
    rows = contrast_rows(t)
    if not rows:
        return ["§8.1 has no contrast rows"]
    for r in rows:
        if len(r) != 8:
            bad.append(f"{r[0]}: {len(r)} cells, not 8")
            continue
        want = contrast_values(t, r)
        if r[4:7] != want:
            bad.append(f"{r[0]}: reads {r[4:7]}, the tokens give {want}")
        floor = FLOOR.get(r[3])
        if floor is not None and min(float(x) for x in want) < floor:
            bad.append(f"{r[0]}: below {floor}:1 for a `{r[3]}` pair")
    return bad


def g_cvd(t: Texts) -> list[str]:
    bad = []
    rows = cvd_rows(t)
    if not rows:
        return ["§8.2 has no CVD rows"]
    for r in rows:
        if len(r) != 6:
            bad.append(f"{r[0]}: {len(r)} cells, not 6")
            continue
        ds, under = cvd_values(t, r)
        if r[4] != ds or r[5] != under:
            bad.append(f"{r[0]}: reads {r[4]} / {r[5]}, the tool gives {ds} / {under}")
    return bad


def g_hotkey(t: Texts) -> list[str]:
    allowed = section(t.spec, "## 13.")
    bad = []
    for i, ln in enumerate(t.spec.split("\n"), 1):
        if CHORD.search(ln) and ln not in allowed and not ln.startswith("- **A-8,"):
            bad.append(f"spec:{i} names a key chord outside §13's rows and A-8")
    raw = show(t, BASE, KEYMAP_REL)
    if raw is None:
        return [*bad, f"{KEYMAP_REL} does not resolve at the base"]
    for c in json.loads(raw).get("commands", []):
        cid, label = str(c.get("id", "")), str(c.get("label", ""))
        if c.get("defaultBinding") == "Ctrl+Shift+L":
            bad.append(f"KEYMAP binds Ctrl+Shift+L to `{cid}`")
        if re.search(
            r"environment|demo\s*/\s*live|switch.*(demo|live)", label, re.IGNORECASE
        ):
            bad.append(f"KEYMAP binds `{cid}` ({label!r}) to the environment switch")
    return bad


def g_t2(t: Texts) -> list[str]:
    bad = []
    rows = table_rows(section(t.spec, "### 4.3"), "S74-")
    if not rows:
        return ["§4.3 has no state rows"]
    for r in rows:
        if len(r) < 4:
            continue
        cell = r[3]
        if "validity" in cell:
            if "T2" in cell or "lock look)" not in cell and "lock" in cell:
                bad.append(f"{r[0]}: a validity state (V) drawn with a T2 rendering")
        elif "T2" in cell and not re.search(r"\"[^\"]{8,}\"", cell):
            bad.append(f"{r[0]}: a T2 presentation with no quoted reason")
        if "T2" in cell and "validity" not in cell and "T2 anatomy" not in cell:
            bad.append(f"{r[0]}: a T2 row that does not cite the T2 anatomy")
    sec = section(t.spec, "### 4.3")
    start = sec.find("- **T2 anatomy")
    if start < 0:
        return [*bad, "§4.3 states no T2 anatomy (G-T2.1a-d, G-T2.2, G-T2.6)"]
    end = sec.find("\n- **", start + 1)
    body = sec[start : end if end > 0 else len(sec)]
    bad += [f"the T2 anatomy drops {p!r}" for p in T2_ANATOMY if p not in body]
    a3 = next((ln for ln in t.spec.split("\n") if ln.startswith("- **A-3,")), "")
    bad += [
        f"A-3 does not name {p!r} (G-T2.6)"
        for p in ("CMP-079", "CMP-019 `lock`")
        if p not in a3
    ]
    return bad


T2_ANATOMY = (
    "native role",
    "full label",
    'aria-disabled="true"',
    "never the `disabled` attribute",
    "in the DOM at mount",
    "`aria-describedby`",
    "CMP-079 RbacGate",
    "`rbac.env`",
    "CMP-019 `lock`",
    '"Not available"',
    "`color.text.tertiary`",
    "`color.text.secondary`",
    "`color.surface.raised` with a `color.border.default` hairline",
    "never `color.text.disabled`, never `opacity.disabled`",
)


def g_cite(t: Texts) -> list[str]:
    hashes, bad = cite_hashes(t)
    pinned = parse_pins(t.pins)
    for label, h in hashes.items():
        if label not in pinned:
            bad.append(
                f"cite {label} is unpinned: verify it by content, then --repin-ruled"
            )
        elif pinned[label] != h:
            bad.append(f"cite {label}: the line at its base is not the pinned content")
    return bad


def g_hygiene(t: Texts) -> list[str]:
    bad = []
    checks = ((CLOSING, "a closing keyword (PR 2 alone closes #1003)"), (LOCAL_PATH, "a local path"),
              (AGENT_NAME, "an agent name"), (URL_OR_HOST, "a URL or a host"))  # fmt: skip
    for i, ln in enumerate(t.spec.split("\n"), 1):
        for rx, what in checks:
            if rx.search(ln):
                bad.append(f"spec:{i} carries {what}")
        if "{{" in ln:
            bad.append(f"spec:{i} carries a double-brace slot")
        if any(d in ln.lower() for d in DENY):
            bad.append(f"spec:{i} carries a public-text deny word")
    for label, text in (("tool", t.tool), ("pins", t.pins)):
        for i, ln in enumerate(text.split("\n"), 1):
            if any(d in ln.lower() for d in DENY):
                bad.append(f"{label}:{i} carries a public-text deny word")
    return bad


def g_scope(t: Texts) -> list[str]:
    if t.changed is None:
        return ["cannot list the changed paths (git failed)"]
    own = ", ".join(OWN_PATHS)
    targets = {PATHS[k] for k in AROW_KEYS}
    return [
        f"{p} is touched; this ticket owns {own}, the E38-D02 exports and the A-row targets"
        for p in t.changed
        if p not in OWN_PATHS and p not in targets and not IMG.fullmatch(p)
    ]


def png_size(data: bytes) -> tuple[int, int] | None:
    if data[:8] != b"\x89PNG\r\n\x1a\n" or data[12:16] != b"IHDR" or len(data) < 24:
        return None
    return int.from_bytes(data[16:20], "big"), int.from_bytes(data[20:24], "big")


def on_disk(t: Texts, name: str, sha: str, size: tuple[int, int] | None = None) -> bool:
    data = t.files.get(name)
    if data is None or hashlib.sha256(data).hexdigest() != sha:
        return False
    return size is None or png_size(data) == size


def g_drawn(t: Texts) -> list[str]:
    s0 = section(t.spec, "## 0.")
    frames = [r for r in table_rows(s0, "B") if len(r) == 5 and r[0] != "B"]
    boards = [
        r for r in table_rows(s0, "") if len(r) == 5 and re.fullmatch(r"\d\d", r[0])
    ]
    if not frames:
        return ["§0 has no frame rows"]
    pending = [r for r in frames if r[4] == PENDING]
    if len(pending) == len(frames) and not boards:
        return []  # PR 1: nothing drawn yet
    bad = []
    if pending:
        bad.append(f"a mix: {len(pending)} frame rows still {PENDING!r}")
    if not re.search(rf"page id `{UUID}`", s0):
        bad.append("drawn, but §0 names no page id")
    nos = {r[0] for r in boards}
    for r in frames:
        m = re.fullmatch(r"drawn, board (\d\d)", r[4])
        if r[4] != PENDING and (m is None or m[1] not in nos):
            bad.append(f"{r[0]}: Status {r[4]!r} names no board of the board table")
    listed: set[str] = set()
    for r in boards:
        m = DRAWN.fullmatch(r[4])
        if m is None:
            bad.append(f"board {r[0]}: Status is not the drawn form")
            continue
        light, name, no, slug = m[1], m[3], m[4], m[5]
        listed.add(name)
        if no != r[0] or r[1] != f"`E38-D02 / {no} {slug}`":
            bad.append(f"board {r[0]}: the export names another board or slug")
        if bool(light) != (r[2] == "light") or slug.endswith("-light") != (
            r[2] == "light"
        ):
            bad.append(
                f"board {r[0]}: the theme does not agree with its Status and slug"
            )
        if not on_disk(t, name, m[8], (int(m[6]), int(m[7]))):
            bad.append(f"board {r[0]}: {name} is missing or not its W × H and sha256")
    renders = RENDER.findall(s0)
    for name, _, _, sha in renders:
        listed.add(name)
        if not on_disk(t, name, sha):
            bad.append(f"{name} is missing or not its sha256")
    got = sorted(f"{no}-{k}" for _, no, k, _ in renders)
    want = sorted(f"{no}-{k}" for no in SIMULATED for k in SIMULATIONS)
    if got != want:
        bad.append(
            f"the simulations listed are {got}, not boards 01 and 03 × {SIMULATIONS}"
        )
    stray = sorted(set(t.files) - listed)
    if stray:
        bad.append(f"E38-D02 PNGs on disk that §0 does not list: {stray}")
    return bad


DEMO_STATEMENT = (
    "Demo uses Bybit's demo matching engine \u2014 REST order entry only, "
    "no private WS order entry."
)
# (ruling, what must stand in the spec, what must not)
RULED: tuple[tuple[str, str, str | None], ...] = (
    (
        "BQ-07 DEMO medium",
        "DEMO `font.weight.medium` on CMP-074",
        "DEMO `font.weight.regular` on",
    ),
    (
        "BQ-08 the panel rule",
        "On panel badges LIVE keeps E15-D03 D-4's `border.thick` rule",
        None,
    ),
    ("BQ-08 no underline", "the word itself is never underlined", None),
    ("BQ-11 LIVE since", "never inside the pill and never in a live region", None),
    (
        "BQ-14 exact match",
        "Until the field equals `LIVE` exactly (case-sensitive",
        "case-insensitive",
    ),
    ("BQ-16 to demo", "**To demo:** one Confirm, no typed word and no step-up", None),
    (
        "BQ-24 audit",
        "on the 200 of `POST /session/environment`, at S74-05, never on intent",
        None,
    ),
    (
        "the pill's role (§3.1)",
        (
            'the pill inside it is a button, CMP-017\'s anchor (`aria-haspopup="dialog"`, '
            '`aria-expanded`, `aria-controls`), never itself `role="status"`'
        ),
        'The pill is a `role="status"`',
    ),
    (
        "the pill's role (§9)",
        "- **The pill:** a button named",
        '- **The pill:** `role="status"`',
    ),
    (
        "the exports (AC 2)",
        "greyscale, deuteranopia, protanopia and tritanopia renders",
        None,
    ),
)


def e09_keys(t: Texts) -> dict[str, re.Pattern[str]]:
    out: dict[str, re.Pattern[str]] = {}
    for ln in at(t, "E09D09").split("\n"):
        m = re.match(r'\| `(rbac\.[a-z_]+)` +\| "([^"]+)"', ln)
        if m and m[1] not in out:
            parts = re.split(r"\{[a-z_]+\}", m[2])
            out[m[1]] = re.compile(".+?".join(re.escape(x) for x in parts) + "$")
    return out


def g_t2_keys(t: Texts) -> list[str]:
    keys = e09_keys(t)
    bad = []
    for r in table_rows(section(t.spec, "### 4.3"), "S74-"):
        if len(r) < 4 or "T2" not in r[3] or "validity" in r[3]:
            continue
        quote = re.search(r'"([^"]{8,})"', r[3])
        named = re.findall(r"`(rbac\.[a-z_]+)`", r[3])
        if not quote:
            continue
        if named:
            for k in named:
                if k not in keys or not keys[k].match(quote[1]):
                    bad.append(f"{r[0]}: {quote[1]!r} is not `{k}`'s text at the base")
        elif "PROPOSED" not in r[3]:
            bad.append(
                f"{r[0]}: a T2 reason that is neither an E09-D09 key nor PROPOSED"
            )
        if r[0] == "S74-07" and named != ["rbac.env"]:
            bad.append("S74-07: not-permitted is `rbac.env` (ruling BQ-22)")
    return bad


def g_ruled(t: Texts) -> list[str]:
    bad = []
    if DEMO_STATEMENT not in at(t, "14").split("\n")[1786]:
        bad.append("the demo statement is not on `14`:1787 at the base")
    n = t.spec.count(f'"{DEMO_STATEMENT}"')
    if n != 1 or "engine - REST" in t.spec:
        bad.append("BQ-10: the demo statement is not verbatim from `14`:1787")
    for what, must, never in RULED:
        if must not in t.spec:
            bad.append(f"{what}: {must[:50]!r} no longer stands")
        if never is not None and never in t.spec:
            bad.append(f"{what}: {never!r} stands")
    s05 = [
        r for r in table_rows(section(t.spec, "### 4.3"), "S74-") if r[0] == "S74-05"
    ]
    if s05 and (len(s05[0]) < 6 or "on the 200" not in s05[0][5]):
        bad.append("BQ-24: S74-05's Audit cell is not on the 200")
    since = next(
        (ln for ln in t.spec.split("\n") if ln.startswith("- **LIVE since")), ""
    )
    if re.search(
        r"aria-live=\"(polite|assertive)\"|role=\"(status|alert|log)\"", since
    ):
        bad.append("BQ-11: LIVE since is placed in a live region")
    return bad


def g_arow(t: Texts) -> list[str]:
    bad = []
    lines = [
        ln for ln in section(t.spec, "## 11.").split("\n") if ln.startswith("- **A-")
    ]
    ids = [re.match(r"- \*\*(A-\d+),", ln) for ln in lines]
    got = [m[1] for m in ids if m]
    if got != [f"A-{i}" for i in range(1, 10)]:
        bad.append(f"the A-rows are {got}, not A-1 … A-9")
    news: dict[str, list[str]] = {}
    for ln in lines:
        m = re.match(r"- \*\*(A-\d+),", ln)
        if not m:
            continue
        aid = m[1]
        news[aid] = re.findall(r'New: "(.+?)"(?:\.|$)', ln)
        cite = CITE.search(ln)
        olds = re.findall(r'Old: "(.+?)"\. New:', ln)
        olds += re.findall(r'Delete the row whose action is "(.+?)"', ln)
        if not olds:
            continue
        if cite is None:
            bad.append(f"{aid}: names no line at the base")
            continue
        key = cite[1]
        text = at(t, key)
        ls = text.split("\n")
        cited = [int(x.split("\u2013")[0]) for x in cite[2].split(", :")]
        for o in olds:
            if text.count(o) != 1:
                bad.append(f"{aid}: {o[:40]!r} stands {text.count(o)} times in `{key}`")
            elif not any(0 < n <= len(ls) and o in ls[n - 1] for n in cited):
                bad.append(f"{aid}: {o[:40]!r} is not on its cited line")
    a9 = next((ln for ln in lines if ln.startswith("- **A-9,")), "")
    anchor = re.search(r'After "(.+?)" \(A-6', a9)
    if anchor is None or not any(anchor[1] in n for n in news.get("A-6", [])):
        bad.append("A-9: its anchor is not A-6's New text")
    return bad + g_arow_applied(t, {m[1]: ln for m, ln in zip(ids, lines) if m})


def copy_ready(ln: str) -> str:
    """An insertion row's quoted text, its `\\"` escapes read as the quote they stand for."""
    i, j = ln.find('): "'), ln.rfind('"')
    return ln[i + 4 : j].replace('\\"', '"') if 0 <= i < j else ""


def cells(ln: str) -> list[str]:
    return [c.strip() for c in ln.strip().strip("|").split("|")]


def after(text: str, head: str, starts: str) -> tuple[str, str] | None:
    """The line in `head`'s `###` block that starts with `starts`, and the line after it."""
    ls = text.split("\n")
    i = next((k for k, ln in enumerate(ls) if ln.startswith(head)), -1)
    for k in range(i + 1, len(ls) - 1) if i >= 0 else ():
        if ls[k].startswith("### "):
            return None
        if ls[k].startswith(starts):
            return ls[k], ls[k + 1]
    return None


INSERTS = (  # (A-row, target, block, the line the insertion follows)
    ("A-1", "14", "### SCR-074 ", "- **Design sign-off acceptance checklist:**"),
    ("A-2", "14", "### SCR-075 ", "- **Design sign-off acceptance checklist:**"),
    ("A-3", "15", "### CMP-074 ", "- **Tests**:"),
    ("A-4", "15", "### CMP-075 ", "- **As built"),
)


def g_arow_applied(t: Texts, rows: dict[str, str]) -> list[str]:
    bad: list[str] = []
    state: dict[str, set[str]] = {}

    def mark(aid: str, applied: bool | None, why: str) -> None:
        state.setdefault(aid, set()).add(
            "applied" if applied else "pending" if applied is False else "neither"
        )
        if applied is None:
            bad.append(f"{aid}: {why}")

    for aid, key, head, starts in INSERTS:
        text, ins = t.heads.get(key, ""), copy_ready(rows.get(aid, ""))
        n, pair = text.count(ins), after(text, head, starts)
        if not ins or pair is None:
            mark(
                aid, None, f"no copy-ready text or no `{starts}` line in {head.strip()}"
            )
        elif n == 0:
            mark(aid, False, "")
        elif n == 1 and pair[1] == ins:
            mark(aid, True, "")
        else:
            mark(aid, None, f"its line stands {n} times or not right after `{starts}`")
    for aid in ("A-5", "A-6", "A-7"):
        key = {"A-5": "E30D04", "A-6": "E30D04", "A-7": "E29D03"}[aid]
        text = t.heads.get(key, "")
        for old, new in re.findall(
            r'Old: "(.+?)"\. New: "(.+?)"(?:\.|$)', rows.get(aid, "")
        ):
            o, n = text.count(old), text.count(new)
            if (o, n) == (1, 0):
                mark(aid, False, "")
            elif (o, n) == (0, 1):
                mark(aid, True, "")
            else:
                mark(aid, None, f"{old[:30]!r} stands {o} and its New {n} times")
    act = re.search(r'Delete the row whose action is "(.+?)"', rows.get("A-8", ""))
    n8 = t.heads.get("17", "").count(act[1]) if act else -1
    mark(
        "A-8",
        True if n8 == 0 else False if n8 == 1 else None,
        f"its row stands {n8} times",
    )
    m9 = re.search(r'After "(.+?)" \(A-6.*?add the row: "(.+)"\.$', rows.get("A-9", ""))
    if m9 is None:
        mark("A-9", None, "no anchor or row text")
    else:
        ls = t.heads.get("E30D04", "").split("\n")
        want = cells(m9[2])
        hits = [
            k for k, ln in enumerate(ls) if ln.startswith("|") and cells(ln) == want
        ]
        anchor = [k for k, ln in enumerate(ls) if m9[1] in ln]
        if not hits:
            mark("A-9", False, "")
        elif len(hits) == 1 and len(anchor) == 1 and hits[0] == anchor[0] + 1:
            mark("A-9", True, "")
        else:
            mark("A-9", None, "its row stands twice or not right after A-6's row")
    seen = {a: s for a, s in state.items() if "neither" not in s}
    mixed = sorted(a for a, s in seen.items() if len(s) > 1)
    if mixed:
        bad.append(f"A-rows half applied inside the row: {mixed}")
    modes = {next(iter(s)) for s in seen.values() if len(s) == 1}
    if len(modes) > 1:
        done = sorted(a for a, s in seen.items() if s == {"applied"})
        bad.append(f"a mix: {done} applied, the other A-rows pending")
    elif modes == {"pending"} and g_drawn_mode(t):
        bad.append("§0 is drawn but the A-rows are pending (PR 2 applies them)")
    return bad


def g_drawn_mode(t: Texts) -> bool:
    rows = table_rows(section(t.spec, "## 0."), "B")
    return any(len(r) == 5 and r[0] != "B" and r[4] != PENDING for r in rows)


GATES: dict[str, Callable[[Texts], list[str]]] = {
    "G-STATE": g_state, "G-TOKEN": g_token, "G-CONTRAST": g_contrast, "G-CVD": g_cvd,
    "G-HOTKEY": g_hotkey, "G-T2": lambda t: g_t2(t) + g_t2_keys(t),
    "G-RULED": g_ruled, "G-AROW": g_arow, "G-CITE": g_cite, "G-HYGIENE": g_hygiene,
    "G-DRAWN": g_drawn, "G-SCOPE": g_scope,
}  # fmt: skip


def audit(t: Texts) -> list[tuple[str, str]]:
    out = []
    for g, fn in GATES.items():
        try:
            out += [(g, m) for m in fn(t)]
        except LookupError as e:
            out.append((g, str(e)))
    return out


# ---------------------------------------------------------------------------- load, fill, self-test


def changed_paths() -> list[str] | None:
    mb = git("merge-base", "HEAD", "origin/main")
    if not mb:
        return None
    a = git("diff", "--name-only", mb.strip())
    b = git("status", "--porcelain", "--untracked-files=all")
    if a is None or b is None:
        return None
    out = {p for p in a.split("\n") if p}
    out |= {ln[3:].split(" -> ")[-1].strip('"') for ln in b.split("\n") if len(ln) > 3}
    return sorted(out)


def load() -> Texts:
    spec = (ROOT / SPEC_REL).read_text(encoding="utf-8")
    pins = (
        (ROOT / PINS_REL).read_text(encoding="utf-8")
        if (ROOT / PINS_REL).exists()
        else ""
    )
    tool = (ROOT / TOOL_REL).read_text(encoding="utf-8")
    img = ROOT / IMG_REL
    files = (
        {f.name: f.read_bytes() for f in sorted(img.glob("E38-D02-*.png"))}
        if img.is_dir()
        else {}
    )
    heads = {}
    for k in AROW_KEYS:
        f = ROOT / PATHS[k]
        heads[k] = f.read_text(encoding="utf-8") if f.exists() else ""
    return Texts(spec, pins, tool, changed_paths(), {}, files, heads)


def fill(t: Texts) -> str:
    out = []
    for ln in t.spec.split("\n"):
        cells = [c.strip() for c in ln.strip().strip("|").split("|")]
        if ln.startswith("| P-") and len(cells) == 8:
            v = contrast_values(t, cells)
            floor = FLOOR.get(cells[3])
            verdict = (
                "structure"
                if floor is None
                else ("pass" if min(map(float, v)) >= floor else "FAIL")
            )
            cells[4:8] = [*v, verdict]
            ln = "| " + " | ".join(cells) + " |"
        elif ln.startswith("| V-") and len(cells) == 6:
            cells[4], cells[5] = cvd_values(t, cells)
            ln = "| " + " | ".join(cells) + " |"
        out.append(ln)
    return "\n".join(out)


def sub(old: str, new: str) -> Callable[[Texts], Texts]:
    def f(t: Texts) -> Texts:
        if t.spec.count(old) != 1:
            raise SystemExit(
                f"self-test: the spec carries {old[:50]!r} {t.spec.count(old)} times"
            )
        return replace(t, spec=t.spec.replace(old, new))

    return f


def set_cell(row: str, col: int, value: str) -> Callable[[Texts], Texts]:
    def f(t: Texts) -> Texts:
        ls = t.spec.split("\n")
        i = next(k for k, ln in enumerate(ls) if ln.startswith(f"| {row} "))
        cells = [c.strip() for c in ls[i].strip().strip("|").split("|")]
        cells[col] = value
        ls[i] = "| " + " | ".join(cells) + " |"
        return replace(t, spec="\n".join(ls))

    return f


def with_file(name: str, data: bytes | None) -> Callable[[Texts], Texts]:
    def f(t: Texts) -> Texts:
        files = {k: v for k, v in t.files.items() if k != name}
        if data is not None:
            files[name] = data
        return replace(t, files=files)

    return f


def head_sub(key: str, old: str, new: str) -> Callable[[Texts], Texts]:
    def f(t: Texts) -> Texts:
        if t.heads[key].count(old) != 1:
            raise SystemExit(f"self-test: `{key}` carries {old[:40]!r} not once")
        return replace(t, heads={**t.heads, key: t.heads[key].replace(old, new)})

    return f


def one_pixel_wider(t: Texts) -> Texts:
    """Board 05's IHDR width plus one; the record's sha256 is moved to match, so only the size is off."""
    name = "E38-D02-05-scr-075-modal-and-banners.png"
    data = bytearray(t.files[name])
    data[16:20] = (int.from_bytes(data[16:20], "big") + 1).to_bytes(4, "big")
    old = hashlib.sha256(t.files[name]).hexdigest()
    new = hashlib.sha256(bytes(data)).hexdigest()
    return replace(
        t, spec=t.spec.replace(old, new, 1), files={**t.files, name: bytes(data)}
    )


def swap_twins(t: Texts) -> Texts:
    """Board 01's greyscale and deuteranopia simulations share a size; swapping their bytes keeps it."""
    a = "E38-D02-01-scr-074-switch-to-live-greyscale.png"
    b = "E38-D02-01-scr-074-switch-to-live-deuteranopia.png"
    return replace(t, files={**t.files, a: t.files[b], b: t.files[a]})


def swap_boards(t: Texts) -> Texts:
    """Two dark boards' bytes swapped: both sizes and sha256 then disagree with the record."""
    a = "E38-D02-04-scr-075-panel-placements.png"
    b = "E38-D02-06-switch-diagram-and-matrix.png"
    return replace(t, files={**t.files, a: t.files[b], b: t.files[a]})


def drop_row(lead: str) -> Callable[[Texts], Texts]:
    def f(t: Texts) -> Texts:
        return replace(
            t,
            spec="\n".join(ln for ln in t.spec.split("\n") if not ln.startswith(lead)),
        )

    return f


MUTATIONS: tuple[tuple[str, str, Callable[[Texts], Texts]], ...] = (
    ("G-STATE", "drop the blocked frame row", drop_row("| B08 ")),
    ("G-STATE", "drop a SCR-075 checklist mapping", drop_row("| K75-4 ")),
    ("G-STATE", "delete the switched state row", drop_row("| S74-05 ")),
    ("G-STATE", "rename the failed state", set_cell("S74-06", 1, "failure")),
    ("G-STATE", "empty the not-permitted row's announcement", set_cell("S74-07", 4, "")),
    ("G-TOKEN", "misspell an env token", sub("`color.env.live` (border, dot)", "`color.env.lives` (border, dot)")),
    ("G-CONTRAST", "type a contrast figure one step off", set_cell("P-01", 4, "14.36")),
    ("G-CONTRAST", "gate a structure pair as text", set_cell("P-09", 3, "text")),
    ("G-CVD", "type a ΔE figure off", set_cell("V-01", 4, "107.06 / 91.86 / 121.11 / 115.66")),
    ("G-HOTKEY", "bind a hotkey to the switcher in §4", sub("there is no other path to SCR-074.", "there is no other path to SCR-074 but Ctrl+Shift+L.")),
    ("G-T2", "drop the not-permitted reason", set_cell("S74-07", 3, "T2 2a on Switch to LIVE")),
    ("G-T2", "S74-07 given `14`'s string", sub("`rbac.env`, \"Live trading isn't enabled for you.\"", "`rbac.env`, \"The owner hasn't enabled Live for your account.\"")),
    ("G-T2", "S74-07 given the key `rbac.permission`", sub("T2 2a `rbac.env`,", "T2 2a `rbac.permission`,")),
    ("G-RULED", "the demo statement with a hyphen", sub("matching engine \u2014 REST order entry only, no private WS order entry.\" (`14`:1787)", "matching engine - REST order entry only, no private WS order entry.\" (`14`:1787)")),
    ("G-RULED", "DEMO made regular", sub("DEMO `font.weight.medium` on CMP-074", "DEMO `font.weight.regular` on CMP-074")),
    ("G-RULED", "the panel LIVE rule dropped", sub("On panel badges LIVE keeps E15-D03 D-4's `border.thick` rule", "On panel badges LIVE drops E15-D03 D-4's `border.thick` rule")),
    ("G-RULED", "the word underlined", sub("the word itself is never underlined", "the word itself is underlined")),
    ("G-RULED", "LIVE since in a live region", sub("never inside the pill and never in a live region", "inside a `role=\"status\"` region")),
    ("G-RULED", "the match made case-insensitive", sub("exactly (case-sensitive, `14`:264)", "(case-insensitive, `14`:264)")),
    ("G-RULED", "to demo given a typed word and step-up", sub("**To demo:** one Confirm, no typed word and no step-up", "**To demo:** a typed word and a step-up")),
    ("G-RULED", "the audit moved to intent", sub("at S74-05, never on intent", "at S74-03, on intent")),
    ("G-AROW", "A-5's Old text off by one character", sub('Old: "1 px border, 24 px tall in compact', 'Old: "1px border, 24 px tall in compact')),
    ("G-AROW", "A-8's row text changed", sub('whose action is "Toggle Demo/Live switch flow', 'whose action is "Toggle the Demo/Live switch flow')),
    ("G-AROW", "A-9 dropped", lambda t: replace(t, spec="\n".join(ln for ln in t.spec.split("\n") if not ln.startswith("- **A-9,")))),
    ("G-T2", "draw the typed gate as T2", set_cell("S74-02", 3, "Continue T2 2a until the field equals `LIVE` (form validity)")),
    ("G-HOTKEY", "a KEYMAP command bound to the switch", lambda t: replace(t, memo={**t.memo, f"{BASE}:{KEYMAP_REL}": json.dumps({"commands": [{"id": "session.env_switch", "label": "Switch Demo/Live", "defaultBinding": "Ctrl+Shift+L"}]})})),
    ("G-CITE", "re-point a `14` cite to an unpinned line", sub("(`14`:1767)", "(`14`:1766)")),
    ("G-HYGIENE", "write a closing keyword against #1003", sub("carries the closing line.", "carries the closing line. Closes #1003.")),
    ("G-HYGIENE", "put a deny word into the tool's own text", lambda t: replace(t, tool=t.tool + "\n# " + DENY[6] + "\n")),
    ("G-SCOPE", "touch `16` in the diff", lambda t: replace(t, changed=[*OWN_PATHS, PATHS["16"]])),
    ("G-RULED", "S74-05's Audit cell moved to intent", sub("`session.environment_switched`, high, on the 200 (`14`:1779)", "`session.environment_switched`, high, on press (`14`:1779)")),
    ("G-T2", "the T2 anatomy drops the describedby link", sub("in the DOM at mount and linked by `aria-describedby`", "in the DOM at mount")),
    ("G-T2", "the T2 anatomy drops the hi-fi pins", sub("never `color.text.disabled`, never `opacity.disabled` on the label", "on the label")),
    ("G-T2", "S74-08 stops citing the T2 anatomy", sub("`E33D03`:317; the T2 anatomy below)", "`E33D03`:317)")),
    ("G-T2", "A-3 drops CMP-079 (in the spec and as applied)", lambda t: head_sub("15", "(S74-07, S74-08) CMP-079 RbacGate wraps the popover's action", "(S74-07, S74-08) the popover's action is gated")(sub("(S74-07, S74-08) CMP-079 RbacGate wraps the popover's action", "(S74-07, S74-08) the popover's action is gated")(t))),
    ("G-RULED", "the pill made a status again (§3.1)", sub("the pill inside it is a button, CMP-017's anchor", "the pill inside it is a `role=\"status\"` element, CMP-017's anchor")),
    ("G-RULED", "the pill made a status again (§9)", sub("- **The pill:** a button named", "- **The pill:** `role=\"status\"`, named")),
    ("G-RULED", "the exports drop tritanopia", sub("protanopia and tritanopia renders", "protanopia renders")),
    ("G-DRAWN", "board 05's PNG one pixel wider than its record", one_pixel_wider),
    ("G-DRAWN", "two same-size simulations of board 01 swap bytes", swap_twins),
    ("G-DRAWN", "two dark boards swap bytes", swap_boards),
    ("G-DRAWN", "a simulation missing on disk", with_file("E38-D02-03-scr-075-band-and-signal-tritanopia.png", None)),
    ("G-DRAWN", "an extra E38-D02 PNG on disk", with_file("E38-D02-09-extra.png", b"\x89PNG\r\n\x1a\n")),
    ("G-DRAWN", "a frame row back to pending (a mix)", set_cell("B11", 4, PENDING)),
    ("G-DRAWN", "a frame row names a board not drawn", set_cell("B15", 4, "drawn, board 09")),
    ("G-DRAWN", "a light twin recorded as dark", set_cell("07", 2, "dark")),
    ("G-DRAWN", "the page id dropped", lambda t: replace(t, spec=re.sub(rf"page id `{UUID}`", "page id pending", t.spec))),
    ("G-DRAWN", "a simulation unlisted", drop_row("- `E38-D02-01-scr-074-switch-to-live-protanopia.png`")),
    ("G-AROW", "A-5's second change reverted at HEAD (half a row)", head_sub("E30D04", "DEMO `font.weight.medium` with an outline dot (E10-D03 §1.2)", "DEMO regular with an outline dot")),
    ("G-AROW", "A-8's row back in `17` (a mix)", head_sub("17", "| `Ctrl+Shift+K`", "| `Ctrl+Shift+L` | Toggle Demo/Live switch flow (opens M-005, never switches without confirm) | Global |\n| `Ctrl+Shift+K`")),
    ("G-AROW", "A-1's line moved below a blank line", head_sub("14", "with the reason listed\n- **Hi-fi (E38-D02):**", "with the reason listed\n\n- **Hi-fi (E38-D02):**")),
    ("G-AROW", "A-4's line inserted twice", lambda t: replace(t, heads={**t.heads, "15": t.heads["15"].replace("the placements per host are E38-D02 §3.2 (PROPOSED).", "the placements per host are E38-D02 §3.2 (PROPOSED).\n- **Hi-fi (E38-D02)**: the same grammar as CMP-074 (2 px border on every host, and LIVE's `border.thick` rule on panel badges; a denser row variant is R-1, PROPOSED to the E10-D03 owner), `role=\"img\"` with a static label; the placements per host are E38-D02 §3.2 (PROPOSED).")})),
    ("G-AROW", "A-9's row dropped from E30-D04", lambda t: replace(t, heads={**t.heads, "E30D04": "\n".join(ln for ln in t.heads["E30D04"].split("\n") if not ln.startswith("| submit word"))})),
    ("G-AROW", "A-3 worded off by one character at HEAD", head_sub("15", "the word never underlined.", "the word never underlined")),
    ("G-AROW", "every A-row reverted while §0 is drawn", lambda t: replace(t, heads={k: show(t, BASE, PATHS[k]) or "" for k in AROW_KEYS})),
)  # fmt: skip


def selftest() -> tuple[bool, list[str]]:
    base = replace(load(), changed=list(OWN_PATHS))
    before = base.spec
    found = audit(base)
    out = [f"self-test: baseline {len(found)} FAIL"] + [
        f"  baseline {g}: {m}" for g, m in found
    ]
    ok = not found
    for i, (gate, what, fn) in enumerate(MUTATIONS, 1):
        gates = sorted({g for g, _ in audit(fn(base))})
        good = gates == [gate]
        ok &= good
        out.append(
            f"{'ok  ' if good else 'FAIL'} M-{i} {gate}: {what} -> {', '.join(gates) or 'none'}"
        )
    restored = load().spec == before
    ok &= restored
    out.append(
        f"self-test: {len(MUTATIONS)} mutations, text restored: {'yes' if restored else 'NO'}"
    )
    out.append(f"self-test: {'PASS' if ok else 'FAIL'}")
    return ok, out


def main(argv: list[str]) -> int:
    ap = argparse.ArgumentParser(description="E38-D02 environment chrome audit")
    g = ap.add_mutually_exclusive_group()
    g.add_argument("--check", action="store_true")
    g.add_argument("--fill", action="store_true")
    g.add_argument("--self-test", action="store_true")
    g.add_argument("--repin-ruled", action="store_true")
    a = ap.parse_args(argv)
    if a.self_test:
        ok, lines = selftest()
        print("\n".join(lines))
        return 0 if ok else 1
    t = load()
    if a.fill:
        (ROOT / SPEC_REL).write_text(fill(t), encoding="utf-8")
        print(f"filled §8 in {SPEC_REL}")
        return 0
    if a.repin_ruled:
        hashes, bad = cite_hashes(t)
        if bad:
            print(f"refused: {bad[0]}")
            return 1
        head = "# E38-D02 cite pins: the cite, a hash of its cited line(s) at its base. Written by --repin-ruled only.\n"
        body = "".join(f"{k}\t{h}\n" for k, h in hashes.items())
        (ROOT / PINS_REL).write_text(head + body, encoding="utf-8")
        print(f"wrote {PINS_REL} ({len(hashes)} cites)")
        return 0
    found = audit(t)
    for gate, msg in found:
        print(f"FAIL {gate}: {msg}")
    print(f"{len(found)} FAIL ({len(GATES)} gates)")
    return 1 if found else 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
