"""E14-D02 drawing-interaction audit: every number the wireframes quote, computed from the repo.

Standalone, offline, stdlib only (run with ``python3 -I``). Six sections, each row labelled with its
source so a reviewer can re-grep it:

1. The tool registry: SCR-037's Type line in ``docs/plan/14-screens-catalogue.md``, the ``dr_tool``
   CHECK of ``docs/plan/21-database-schema.md`` 3.8.3, the ``DrawingTool`` enum and its per-tool
   point counts in ``docs/plan/22-api-openapi.yaml`` and the v1 list of
   ``docs/plan/26-chart-engine-design.md`` 3.10, joined to the spec's registry literal below
   (``docs/design/E14/E14-D02.md`` section 2). A name in one source without a registry row, or a
   point count that disagrees, is a gated FAIL.
2. The creation state machine (spec section 4): states x events from one literal; every pair must be
   a transition, an alias or an explicit ignore. Missing pairs must be 0 (gated).
3. The hotkey lint: ``scripts/keymap_lint.py``'s ``lint_keymap`` over the shipped
   ``apps/web/src/keymap/keymap.json`` plus the PROPOSED Chart commands added in memory (the file is
   never written): SCR-037's own set (expect the E14-D01 memo's two errors, three with the data
   table on Alt+T), scheme (a) and scheme (b) of E14-D01 OQ-1 (expect 0 for both; (a) is gated).
4. The greyscale contrast matrix: five neutral pairs x three surfaces from the real token JSON,
   resolved exactly as ``packages/ui/tokens/tests/verify_tokens.py`` does, measured with
   ``contrast_ratio()`` from ``docs/design/_tools/contrast_check.py`` (imported, never
   re-implemented). Dark is gated (the boards are dark); light and high-contrast are reported.
5. The geometry arithmetic of the selection model (target, pick tolerances, glyph, footprint rows).
6. The counts the boards quote, for the local check-nums cross-check (``--json``).

Usage: python3 -I docs/design/_tools/e14_d02_interaction_audit.py [--json]
Exit 1 only on a gated FAIL. Stdout is forced to UTF-8.
"""

from __future__ import annotations

import argparse
import copy
import importlib.util
import json
import re
import sys
from pathlib import Path
from types import ModuleType
from typing import Any

ROOT = Path(__file__).resolve().parents[3]
TOKENS = ROOT / "packages" / "ui" / "tokens"
PLAN = ROOT / "docs" / "plan"


def _load(path: Path, name: str) -> ModuleType:
    spec = importlib.util.spec_from_file_location(name, path)
    if spec is None or spec.loader is None:
        raise ImportError(f"cannot load {path}")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


sys.path.insert(0, str(TOKENS / "tests"))
verify = _load(TOKENS / "tests" / "verify_tokens.py", "verify_tokens")
contrast_check = _load(ROOT / "docs" / "design" / "_tools" / "contrast_check.py", "contrast_check")
keymap_lint = _load(ROOT / "scripts" / "keymap_lint.py", "keymap_lint")

# --- 1. the registry (spec section 2), one row per line: id | SCR-037 name (alias) | DrawingTool
# value | anchors | group | key (OQ-1a, PROPOSED) | story | status
ALIAS = {"fib*": "Fibonacci retracement/extension/time zones", "pos*": "long/short position tool"}
DEFER = "deferred - API value, no story; unscheduled"
REG_TXT = """
cursor|cursor|-|-|cursor|Esc ladder|-|R1 (not a drawing)
crosshair|crosshair|-|-|cursor|rail|-|R1 (cursor style; E11-D02 D9)
select_area|-|-|-|cursor|rail / palette|E14-S10|R1 PROPOSED (Q-4)
trendline|trendline|trendline|2|lines|Alt+L|E14-S02|R1
ray|ray|ray|2|lines|rail / palette|E14-S02|R1
extended_line|extended line|extended_line|2|lines|rail / palette|E14-S02|R1
horizontal_line|horizontal line/level|horizontal_line|1|lines|Alt+H|E14-S01|R1
vertical_line|vertical line|vertical_line|1|lines|rail / palette|E14-S01|R1
rectangle|rectangle|rectangle|2|shapes|Alt+R|E14-S03|R1
ellipse|ellipse|ellipse|2|shapes|rail / palette|E14-S03|R1
triangle|triangle|triangle|3|shapes|rail / palette|E14-S03|R1
parallel_channel|-|parallel_channel|3|shapes|rail / palette|E14-S03|R1
fib_retracement|fib*|fib_retracement|2|fibonacci|Alt+O|E14-S04|R1
fib_extension|fib*|fib_extension|3|fibonacci|rail / palette|E14-S04|R1
fib_timezone|fib*|fib_timezone|2|fibonacci|rail / palette|E14-S04|R1
anchored_vwap|anchored VWAP|anchored_vwap|1|analysis|rail / palette|E14-S05|R1
measure|measure|measure|2|analysis|Alt+D|E14-S06|R1 (transient until pinned)
long_position|pos*|long_position|3|analysis|rail / palette|E14-S07|R1
short_position|pos*|short_position|3|analysis|rail / palette|E14-S07|R1
text|text note|text|1|annotation|rail / palette|E14-S06|R1
callout|-|callout|2|annotation|rail / palette|E14-S06|R1
arrow|arrow|arrow|2|annotation|rail / palette|E14-S06|R1
polyline|-|polyline|2..100|annotation|rail / palette|none (PROPOSED: E14-S06)|R1 PROPOSED (Q-5)
brush|brush|brush|2..500|overflow|-|-|DEFER
pitchfork|pitchfork|pitchfork|3|overflow|-|-|DEFER
gann_fan|-|gann_fan|2|overflow|-|-|DEFER
price_range|-|price_range|2|overflow|-|-|DEFER
date_range|-|date_range|2|overflow|-|-|DEFER
emoji_marker|emoji marker|-|-|overflow|-|-|deferred - no DrawingTool value; unscheduled (G1)
magnet|magnet toggle|-|-|controls|Ctrl+M|E14-S02|R1
keep_active|-|-|-|controls|rail|E14-S10|R1 (AM-5)
lock_all|lock-all|-|-|controls|rail|E14-S08|R1
hide_all|hide-all|-|-|controls|rail|E14-S08|R1
delete_all|delete-all|-|-|controls (apart)|rail|E14-S10|R1
"""
REG = [
    [ALIAS.get(c, DEFER if c == "DEFER" else c) for c in ln.split("|")]
    for ln in REG_TXT.strip().splitlines()
]
# 26 section 3.10 names -> DrawingTool values (the v1 list predates the API enum)
V1_TXT = (
    "trendline>trendline|ray>ray|extended line>extended_line|horizontal line/ray>horizontal_line|"
    "vertical line>vertical_line|rectangle>rectangle|ellipse>ellipse|"
    "Fibonacci retracement>fib_retracement|Fibonacci extension>fib_extension|"
    "measurement tool (price/%/bars/time)>measure|text note>text|arrow>arrow|"
    "price range>price_range|position tool (entry/SL/TP with R:R readout)>long_position|"
    "a brush/freehand for annotations>brush"
)
V1_MAP = dict(p.split(">") for p in V1_TXT.split("|"))

# --- 2. the state machine (spec section 4): "state: event NNk ..." with k = T transition,
# I ignored, = alias of an arm row; "entry" = the transient state's entry action, "*" = any event.
STATES = ("cursor", "armed", "placing", "committed")
INTERRUPTS = ("focus_loss", "symbol_switch", "interval_switch", "tool_switch", "disconnect")
EVENTS = ("arm", "place", "snapCycle", "cancel", *INTERRUPTS, "undo")
MACHINE_TXT = """
cursor: arm 01T 02T | place 03I | snapCycle 04I | cancel 05T 06I | focus_loss 07I
cursor: symbol_switch 08T | interval_switch 09I | tool_switch 10= | disconnect 11I | undo 12T
armed: arm 13T 14T | place 15T 16T | snapCycle 17T | cancel 18T | focus_loss 19T | symbol_switch 20T
armed: interval_switch 21I | tool_switch 22= | disconnect 23I | undo 24T
placing: place 25T 26T 27T | snapCycle 28T | cancel 29T | tool_switch 30T | arm 30T 31I
placing: focus_loss 32T | symbol_switch 33T | interval_switch 34T | disconnect 35T | undo 36T
committed: entry 37T 38T | * 39I
"""
MACHINE: list[tuple[str, str, str, str]] = []  # (row id, state, event, kind)
for _ln in MACHINE_TXT.strip().splitlines():
    _state, _rest = _ln.split(": ", 1)
    for _chunk in _rest.split(" | "):
        _event, *_cells = _chunk.split()
        MACHINE += [("T" + c[:2], _state, _event, c[2]) for c in _cells]

# --- 3. the PROPOSED Chart commands (registered by E14-S10; added in memory only)
AD1_TXT = (
    "chart.draw_trendline=Alt+L chart.draw_hline=Alt+H chart.draw_fib=Alt+O chart.draw_rect=Alt+R "
    "chart.draw_measure=Alt+D chart.magnet_toggle=Ctrl+M chart.snap_cycle_up=Ctrl+↑ "
    "chart.snap_cycle_down=Ctrl+↓"
)
AD1 = dict(p.split("=") for p in AD1_TXT.split())
SCR037 = {k: v for k, v in AD1.items() if "snap" not in k} | {"chart.draw_trendline": "Alt+T"}
SCR037 |= {"chart.draw_fib": "Alt+F", "chart.draw_measure": "Alt+M"}


def _cmd(cid: str, binding: str, **more: Any) -> dict[str, Any]:
    label = cid.split(".")[1].replace("_", " ")
    valid = "anchor pending" if "snap" in cid else "always"
    base = {"id": cid, "label": label, "context": "Chart", "defaultBinding": binding}
    return base | {"destructive": False, "validWhen": valid, "visibleControl": True} | more


TABLE = _cmd("global.data_table", "Alt+T", context="Global", label="Data table (SCR-045)")

# --- 4./5. contrast pairs and geometry
SURFACES = tuple(f"color.surface.{s}" for s in ("canvas", "raised", "sunken"))
FG = [(f"color.text.{n}", "text") for n in ("primary", "secondary", "tertiary")]
FG += [(f"color.border.{n}", "decorative") for n in ("default", "strong")]
THEMES = ("dark", "light", "high-contrast")
ROWS = (12, 10, 6)
GEOM: dict[str, Any] = {"target_px": 24, "tolerance_px": 10, "touch_px": 16, "glyph_px": 8}
GEOM |= {"rows_px": ROWS, "rail_px": (32, 24, 24), "popover_px": (280, 320), "magnet_px": 12}
GEOM |= {"nudge_ticks": (1, 10), "target_over_rows": [round(24 / r, 2) for r in ROWS]}
GEOM |= {"glyph_over_rows": [round(8 / r, 2) for r in ROWS]}
GEOM |= {"tol_over_rows": [round(10 / r, 2) for r in ROWS]}


def read(name: str) -> str:
    return (PLAN / name).read_text(encoding="utf-8")


def scr037_names() -> list[str]:
    text = read("14-screens-catalogue.md")
    m = re.search(r"Tools: (.+?)\.\n", text[text.index("### SCR-037") :])
    return [n.strip() for n in m.group(1).split(", ")] if m else []


def dr_tool_values() -> list[str]:
    text = read("21-database-schema.md")
    block = text[text.index("CONSTRAINT dr_tool CHECK") :]
    return re.findall(r"'([a-z_]+)'", block[: block.index("))")])


def api_tools() -> tuple[list[str], dict[str, str]]:
    text = read("22-api-openapi.yaml")
    block = text[text.index("    DrawingTool:") :]
    block = block[: block.index("    DrawingPoint:")]
    enum = re.findall(r"^        - ([a-z_]+)$", block, re.MULTILINE)
    flat = " ".join(block.split())
    counts: dict[str, str] = {}
    for n, names in re.findall(r"exactly (\d): ((?:`[a-z_]+`,? ?)+)", flat):
        counts.update({v: n for v in re.findall(r"`([a-z_]+)`", names)})
    counts.update({v: rng for rng, v in re.findall(r"(\d+\.\.\d+): `([a-z_]+)`", flat)})
    return enum, counts


def v1_tools() -> list[str]:
    m = re.search(r"\*\*Tools in v1\*\*: (.+?)\.\n", read("26-chart-engine-design.md"))
    return [i.strip().removeprefix("and ") for i in m.group(1).split(", ")] if m else []


def registry_report(fails: list[str]) -> dict[str, Any]:
    by_api = {r[2]: r for r in REG if r[2] != "-"}
    names = scr037_names()
    split = names.index("magnet toggle")
    have, ok = {r[1] for r in REG}, [*names, "-"]
    fails += [f"SCR-037 name without a registry row: {n}" for n in names if n not in have]
    fails += [f"row {r[0]}: {r[1]} is not on SCR-037's Type line" for r in REG if r[1] not in ok]
    enum, counts = api_tools()
    for v in enum:
        if v not in by_api:
            fails.append(f"DrawingTool value without a registry row: {v}")
        elif counts.get(v) != by_api[v][3]:
            fails.append(f"anchor count for {v}: registry {by_api[v][3]} vs 22 {counts.get(v)}")
    fails += [f"registry value not in DrawingTool: {v}" for v in by_api if v not in enum]
    db = dr_tool_values()
    if sorted(db) != sorted(enum):
        fails.append("21 dr_tool and 22 DrawingTool differ: " + str(sorted(set(db) ^ set(enum))))
    v1 = v1_tools()
    bad = [i for i in v1 if V1_MAP.get(i) not in by_api]
    fails += [f"26 section 3.10 tool without a registry row: {i}" for i in bad]
    classes = {k: sorted(v for v, n in counts.items() if n == k) for k in ("1", "2", "3")}
    classes["n"] = sorted(v for v, n in counts.items() if ".." in n)
    deferred = [r[0] for r in REG if r[7].startswith("deferred")]
    out: dict[str, Any] = {"scr037_tools": split, "scr037_controls": len(names) - split}
    out |= {"api_values": len(enum), "db_values": len(db), "v1_values": len(v1)}
    out["reg_rows"] = len(REG)
    out["rail_api"] = len([r for r in REG if r[2] != "-" and r[7].startswith("R1")])
    out["cursor_group"] = len([r for r in REG if r[4] == "cursor"])
    out["controls"] = len([r for r in REG if r[4].startswith("controls")])
    out |= {"deferred": len(deferred), "deferred_ids": deferred, "classes": classes}
    out["api_only_values"] = [v for v in enum if by_api[v][1] == "-"]
    out["scr037_no_story"] = [r[0] for r in REG if r[1] != "-" and r[7].startswith("deferred")]
    out["anchor_classes"] = {k: len(v) for k, v in classes.items()}
    return out


def machine_report(fails: list[str]) -> dict[str, Any]:
    covered = {(s, e) for _, s, e, _ in MACHINE if e in EVENTS}
    covered |= {(s, e) for _, s, ev, _ in MACHINE if ev == "*" for e in EVENTS}
    missing = [f"{s} x {e}" for s in STATES for e in EVENTS if (s, e) not in covered]
    fails += [f"state machine: no row for {m}" for m in missing]
    kinds = {k: len([r for r in MACHINE if r[3] == k]) for k in ("T", "I", "=")}
    out: dict[str, Any] = {"states": len(STATES), "events": len(EVENTS)}
    out["pairs"] = len(STATES) * len(EVENTS)
    out |= {"machine_rows": len({r[0] for r in MACHINE}), "transitions": kinds["T"] + kinds["="]}
    out |= {"aliases": kinds["="], "ignored": kinds["I"], "missing": len(missing)}
    return out | {"interrupts": len(INTERRUPTS), "esc_levels": 3}


def lint_report(fails: list[str]) -> dict[str, Any]:
    km = json.loads((ROOT / "apps/web/src/keymap/keymap.json").read_text(encoding="utf-8"))

    def run(extra: dict[str, str], table: bool, fib_alt_p: bool = False) -> list[str]:
        k = copy.deepcopy(km)
        for c in k["commands"]:
            if c["id"] == "chart.cancel_drawing":
                c["validWhen"] = "a drawing in progress or a tool armed"  # AM-2, in memory
            if fib_alt_p and c["id"] == "chart.footprint_mode":
                c["defaultBinding"] = "Alt+P"  # OQ-1 (b)
        k["commands"] += [_cmd(i, b) for i, b in extra.items()] + ([TABLE] if table else [])
        errs: list[str] = keymap_lint.lint_keymap(k)
        return errs

    base: list[str] = keymap_lint.lint_keymap(km)
    out: dict[str, Any] = {"base": base, "scr037": run(SCR037, False)}
    out["scr037_table"] = run(SCR037, True)
    out |= {"a": run(AD1, True), "b": run(dict(AD1, **{"chart.draw_fib": "Alt+F"}), True, True)}
    if out["a"]:
        fails.append(f"scheme (a) lint errors: {len(out['a'])}")
    try:
        keymap_lint.expand("Backspace")
        out["backspace"] = "recognised"
    except keymap_lint.KeymapError as exc:
        out["backspace"] = f"not recognised by keymap_lint ({exc})"
    return out


def resolve_theme(name: str) -> dict[str, str]:
    allt = dict(verify.load(verify.PRIMITIVES))
    allt.update(verify.merged_set(verify.THEMES[name]))
    colours = {k: v for k, v in allt.items() if v.get("$type") == "color"}
    return {k: str(verify.resolve(v["$value"], allt)) for k, v in colours.items()}


def hex_rgb(h: str) -> tuple[int, int, int]:
    h = h.lstrip("#")
    return int(h[0:2], 16), int(h[2:4], 16), int(h[4:6], 16)


def contrast_report(fails: list[str]) -> dict[str, Any]:
    themes = {t: resolve_theme(t) for t in THEMES}
    pairs: list[dict[str, Any]] = []
    for fg, role in FG:
        for bg in SURFACES:
            rgb = {t: (hex_rgb(themes[t][fg]), hex_rgb(themes[t][bg])) for t in THEMES}
            ratios = {t: float(contrast_check.contrast_ratio(*rgb[t])) for t in THEMES}
            verdict = "FAIL" if role == "text" and ratios["dark"] < 4.5 else "PASS"
            if verdict == "FAIL":
                fails.append(f"contrast {fg} on {bg} dark {ratios['dark']:.4f} < 4.5")
            pairs.append({"fg": fg, "bg": bg, "role": role, "ratios": ratios, "verdict": verdict})
    used = sorted({fg for fg, _ in FG} | set(SURFACES))
    tokens = {t: {k: themes[t][k] for k in used} for t in THEMES}
    gated = len([p for p in pairs if p["role"] == "text"])
    fail = len([p for p in pairs if p["verdict"] == "FAIL"])
    return {"pairs": pairs, "tokens": tokens, "rows": len(pairs), "gated": gated, "failing": fail}


def fmt(v: float, bar: float | None) -> str:
    return f"{v:.4f}" if bar is not None and abs(round(v, 2) - bar) < 0.005 else f"{v:.2f}"


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="E14-D02 interaction audit")
    ap.add_argument("--json", action="store_true")
    a = ap.parse_args(argv)
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")
    fails: list[str] = []
    reg, mach = registry_report(fails), machine_report(fails)
    lint, con = lint_report(fails), contrast_report(fails)
    counts: dict[str, Any] = {"boards": 14, "themes": len(THEMES)}
    counts |= {k: v for k, v in (reg | mach).items() if isinstance(v, int) or k == "anchor_classes"}
    counts |= {f"lint_{k}": len(lint[k]) for k in ("scr037", "scr037_table", "a", "b")}
    counts |= {f"contrast_{k}": con[k] for k in ("rows", "gated", "failing")}
    counts["api_only"] = len(reg["api_only_values"])
    if a.json:
        out = {"counts": counts, "registry": reg, "machine": mach, "lint": lint, "contrast": con}
        print(json.dumps(out | {"geometry": GEOM, "fails": fails}, ensure_ascii=False, indent=1))
        return 1 if fails else 0
    print("## 1. Registry (14 SCR-037 Type line | 21 dr_tool | 22 DrawingTool | 26 section 3.10)\n")
    print(f"SCR-037: {reg['scr037_tools']} tools + {reg['scr037_controls']} controls")
    print(f"21: {reg['db_values']} | 22: {reg['api_values']} | 26: {reg['v1_values']}")
    print(f"registry rows: {reg['reg_rows']} | rail (R1 API values): {reg['rail_api']}")
    print(f"cursor group: {reg['cursor_group']} | controls: {reg['controls']}")
    print(f"deferred: {reg['deferred']} {reg['deferred_ids']}")
    print(f"API values not on SCR-037: {counts['api_only']} {reg['api_only_values']}")
    print(f"SCR-037 names without a story: {reg['scr037_no_story']}")
    print(f"anchor classes: {reg['anchor_classes']}")
    print("\n| id | SCR-037 | DrawingTool | n | group | key (OQ-1a, PROPOSED) | story | status |")
    print("|---|---|---|---|---|---|---|---|")
    for r in REG:
        print("| " + " | ".join(r) + " |")
    print("\n## 2. State machine (spec section 4)\n")
    s = f"states {mach['states']} x events {mach['events']} = {mach['pairs']} pairs | rows "
    s += (
        f"{mach['machine_rows']} | transitions {mach['transitions']} (aliases {mach['aliases']}) | "
    )
    s += f"ignored {mach['ignored']} | missing pairs {mach['missing']}"
    print(s + f" | interrupts {mach['interrupts']} | Esc levels {mach['esc_levels']}")
    print("\n## 3. Hotkey lint (scripts/keymap_lint.py lint_keymap; keymap.json never written)\n")
    labels = {"base": "shipped keymap", "scr037": "SCR-037 set", "scr037_table": "SCR-037 + table"}
    labels |= {"a": "scheme (a) AD-1 + snap-cycle + table", "b": "scheme (b) + table"}
    for key, label in labels.items():
        print(f"- {label}: {len(lint[key])} error(s)")
        for e in lint[key]:
            print(f"    - {e}")
    print(f"- Backspace as a binding: {lint['backspace']}")
    print("\n## 4. Greyscale contrast (dark gated for text; light / hc reported)\n")
    print("| fg | bg | role | dark | light | hc | verdict |\n|---|---|---|---|---|---|---|")
    for p in con["pairs"]:
        bar = 4.5 if p["role"] == "text" else None
        cells = " | ".join(fmt(p["ratios"][t], bar) for t in THEMES)
        print(f"| `{p['fg']}` | `{p['bg']}` | {p['role']} | {cells} | {p['verdict']} |")
    print("\n| token | dark | light | hc |\n|---|---|---|---|")
    for k in con["tokens"]["dark"]:
        print(f"| `{k}` | " + " | ".join(con["tokens"][t][k] for t in THEMES) + " |")
    print("\n## 5. Geometry (CSS px; 26 section 3.6 rows 12 / 10 / 6)\n")
    print(json.dumps(GEOM))
    print("\n## 6. Counts\n")
    print(json.dumps(counts, ensure_ascii=False))
    print(f"\nFAIL count (gated): {len(fails)}")
    for f in fails:
        print(f"- {f}")
    return 1 if fails else 0


if __name__ == "__main__":
    raise SystemExit(main())
