"""E25-D02 detector-wireframe audit: every number the SCR-055..059 greyscale wireframes claim.

Standalone, offline, stdlib only (`python3 -I`). Themes resolve exactly as
`packages/ui/tokens/tests/verify_tokens.py` resolves them and contrast is `contrast_ratio()` from
`docs/design/_tools/contrast_check.py` (both imported with one loader, never re-implemented); the
panel geometry is re-derived from the px literals of `docs/design/E25/E25-D02.md` (PROPOSED
inputs, printed, never asserted); the label widths use the lane's shared pill-label rule (an
upper bound per glyph class on Inter's advance, the flat 0.62 em floor; mono 0.62 em); the spec's
id tables are counted and reconciled (every state row names a board that exists, every state id a
board names exists); the strings are gated (the catalogue strings, the T2 reasons, the shared
contract-gap sentence, the `(estimated)` word, the regime copy lint, the public-repo hygiene
patterns). Nothing here reads a fixture or a network.

Usage: python3 -I docs/design/_tools/e25_d02_detector_wires_audit.py [--json] [--check]
       [--spec P] [--draft P]
Exit 1 on a gated contrast FAIL, a reconciliation miss, a failed string gate or (with `--check`)
a printed number the spec's own sentences do not carry. Stdout is UTF-8.
"""

from __future__ import annotations

import argparse
import importlib.util
import json
import math
import re
import sys
from functools import partial
from pathlib import Path
from types import ModuleType
from typing import Any

ROOT = Path(__file__).resolve().parents[3]
TOKENS = ROOT / "packages" / "ui" / "tokens"
TOOLS = ROOT / "docs" / "design" / "_tools"
THEMES = ("dark", "light", "high-contrast")
BAR: dict[str, float | None] = {"text": 4.5, "non-text": 3.0, "decorative": None, "rejected": 4.5}
BAR["validity"] = 4.5  # the validity look's dimmed label: reported against the text bar, not gated


def _load(path: Path, name: str) -> ModuleType:
    spec = importlib.util.spec_from_file_location(name, path)
    if spec is None or spec.loader is None:
        raise ImportError(f"cannot load {path}")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


sys.path.insert(0, str(TOKENS / "tests"))
verify = _load(TOKENS / "tests" / "verify_tokens.py", "verify_tokens")
contrast_check = _load(TOOLS / "contrast_check.py", "contrast_check")


def resolve_theme(name: str) -> dict[str, Any]:
    allt: dict[str, Any] = dict(verify.load(verify.PRIMITIVES))
    allt.update(verify.merged_set(verify.THEMES[name]))
    out: dict[str, Any] = {}
    for k, v in allt.items():
        if isinstance(v, dict) and "$value" in v:
            raw = v["$value"]
            out[k] = verify.resolve(raw, allt) if isinstance(raw, str) else "composite"
    return out


T = {n: resolve_theme(n) for n in THEMES}


def rows_of(txt: str, sep: str = "|") -> list[list[str]]:
    return [ln.split(sep) for ln in txt.strip().splitlines()]


TOK = dict(rows_of("""canvas|color.surface.canvas
raised|color.surface.raised
overlay|color.surface.overlay
sunken|color.surface.sunken
hover|color.surface.hover
selected|color.surface.selected
app|color.surface.app
t1|color.text.primary
t2|color.text.secondary
t3|color.text.tertiary
t.disabled|color.text.disabled
b.default|color.border.default
b.strong|color.border.strong"""))


def rgb(h: str) -> tuple[int, int, int]:
    h = h.lstrip("#")
    return int(h[0:2], 16), int(h[2:4], 16), int(h[4:6], 16)


def ratio(fg: str, bg: str) -> float:
    return float(contrast_check.contrast_ratio(rgb(fg), rgb(bg)))


def col(theme: str, short: str) -> str:
    return str(T[theme][TOK.get(short, short)])


def dimmed(theme: str, fg: str, bg: str) -> str:
    """The label colour seen at `opacity.disabled` over its surface (E30-D02 D3 validity look)."""
    a, top, under = float(T[theme]["opacity.disabled"]), rgb(col(theme, fg)), rgb(col(theme, bg))
    return "#" + "".join(
        f"{round(a * t + (1 - a) * u):02X}" for t, u in zip(top, under, strict=True)
    )


# A. the matrix (spec 16): text tokens on every neutral surface, the focus stand-in, the hairlines,
# the validity look's dimmed label (reported), color.text.disabled (rejected, E13-D02 13).
SURF = ("canvas", "raised", "overlay", "hover", "selected", "sunken")
USE = {
    "t1": "values, labels, headings",
    "t2": "reasons, notices, evidence",
    "t3": "T2 labels, kickers",
}
PAIRS = [[f"{u} on {s}", t, s, "text"] for s in SURF for t, u in USE.items()]
PAIRS = [p for p in PAIRS if (p[1], p[2]) != ("t3", "selected")]
PAIRS += [[f"focus stand-in on {s}", "t1", s, "non-text"] for s in SURF]
PAIRS += rows_of(
    """REJECTED: T2 label (tertiary) on the selected fill (E22-D02 D7)|t3|selected|rejected
REJECTED: color.text.disabled on raised (E13-D02 13)|t.disabled|raised|rejected
REJECTED: color.text.disabled on overlay|t.disabled|overlay|rejected
validity look: the label at opacity.disabled on raised|t1|raised|validity
validity look: the label at opacity.disabled on overlay|t1|overlay|validity
card outline, divider hairline on raised|b.default|raised|decorative
dialog edge on the app shell|b.strong|app|decorative
T2 hairline on raised|b.default|raised|decorative
hover band on raised|hover|raised|decorative"""
)
E13_DARK: dict[str, float] = json.loads(  # docs/design/E13/E13-D02.md 13 (dark), to the hundredth
    '{"t1|canvas": 15.20, "t2|canvas": 9.33, "t3|canvas": 5.96, "t1|raised": 14.35,'
    ' "t2|raised": 8.81, "t2|sunken": 10.69, "t3|sunken": 6.83, "t1|hover": 12.22,'
    ' "t2|hover": 7.50, "t1|selected": 10.17, "t2|selected": 6.24}'
)

# B. geometry: the spec's px literals (3, 4 - PROPOSED inputs). Shells from E22-D02 2 (40 top, 24
# bottom); the order-flow band of `14` 499 and the five cell widths are this spec's inputs; row
# heights and the step per density from the tokens (16 3); pill rows = 20 px pills + the step.
FRAMES = {"1280x800": (1280, 800, 40, 24), "2560x1440": (2560, 1440, 40, 24)}
BAND_PX = {"1280x800": 256, "2560x1440": 448}  # the bottom band holding 052 | 054 | 057 | 056 | 055
CELLS = {
    "1280x800": {"SCR-052": 176, "SCR-054": 176, "SCR-057": 280, "SCR-056": 440, "SCR-055": 208},
    "2560x1440": {"SCR-052": 352, "SCR-054": 352, "SCR-057": 560, "SCR-056": 880, "SCR-055": 416},
}
DIALOG = {"1280x800": (760, 560), "1920x1080": (880, 600)}  # CMP-043 sizes E15-D02 draws (line 466)
DRAWER_W = 420  # SCR-058 (CMP-046) width, PROPOSED
ZOOM = 2  # 200 % (05 5 item 7)
GAP_TOKEN = {"compact": "space.2", "comfortable": "space.3"}
FONT_UI = {"compact": "font.size.sm", "comfortable": "font.size.sm"}  # 12 px UI text (16 3 rule 1)
FONT_MONO = {"compact": "font.size.xs", "comfortable": "font.size.xs"}  # 11 px mono cells, both
PILL_PX, ICON_PX, INSET_TOKEN = 20, 24, "space.3"
# SCR-056 row columns in ch (spec 5, R2): time, side glyph + word, price range, depth, ratio, age,
# status word, distance.
CH56 = {
    "time": 5,
    "side": 6,
    "price range": 13,
    "depth": 2,
    "ratio": 5,
    "age": 4,
    "status": 6,
    "distance": 15,
}
MONO_EM = 0.62
# the SCR-056 column ladder below the minimum (spec 11, PROPOSED): step 1 folds the age column into
# the time cell's accessible name; step 2 folds the depth column into the side cell (glyph, word).
LADDER56: list[set[str]] = [set(), {"age"}, {"age", "depth"}]
PILL_EM = {
    "upper": 0.84,
    "wideLower": 0.95,
    "lower": 0.56,
    "digit": 0.68,
    "thin": 0.34,
    "symbol": 1.0,
}
THIN = set(" .,:;\u00b7'\u2019|-")


def inter_w(label: str, size: float) -> int:
    """The box a one-line Inter label needs (the shared pill rule; never under 0.62 em flat)."""
    flat = math.ceil(len(label) * size * MONO_EM)
    em = 0.0
    for ch in label:
        if ch.isupper():
            em += PILL_EM["upper"]
        elif ch in "mw":
            em += PILL_EM["wideLower"]
        elif ch.islower():
            em += PILL_EM["lower"]
        elif ch.isdigit():
            em += PILL_EM["digit"]
        elif ch in THIN:
            em += PILL_EM["thin"]
        else:
            em += PILL_EM["symbol"]
    return max(flat, math.ceil(em * size))


def mono_w(label: str, size: float) -> int:
    return math.ceil(len(label) * size * MONO_EM)


# C. the one-line strings each panel must hold without wrapping (spec 4-8, 11): per screen, the
# widest row of pills / segments / cells at the default layout, and the same row after the panel's
# collapse ladder (spec 11: the alert affordance folds to an icon-only CMP-002 with the 2b echo, a
# pill row wraps to a second row, the Delayed tag moves under the readout, the evidence row wraps,
# the SCR-056 age column folds into the time cell's accessible name). The readout may always wrap.
ONE_LINE: dict[str, list[dict[str, Any]]] = {
    "SCR-055": [
        {
            "kind": "pills",
            "items": ["1 s", "5 s", "30 s", "Create alert from this threshold"],
            "fold": "icon-last",
        },
        {
            "kind": "pills",
            "items": ["elevated", "Stale 12s", "Updates every 1 s, \u00d74 slower"],
            "fold": "drop-last",
        },
        {"kind": "text", "items": ["Tape speed BTCUSDT"], "fold": "keep"},
    ],
    "SCR-056": [
        {
            "kind": "pills",
            "items": ["Ratio ≥ 300 %", "Stack ≥ 3", "Sync footprint", "Create alert at this level"],
            "fold": "wrap",
        },
        {"kind": "row56", "items": [], "fold": "drop-age"},
        {"kind": "text", "items": ["Imbalances BTCUSDT 1m"], "fold": "keep"},
    ],
    "SCR-057": [
        {"kind": "pills", "items": ["Trending down (estimated) · medium"], "fold": "keep"},
        {"kind": "text", "items": ["Confidence 0.71 (sub-signal agreement)"], "fold": "wrap"},
        {"kind": "text", "items": ["Regime (estimated) BTCUSDT"], "fold": "keep"},
    ],
    "SCR-058": [
        {"kind": "text", "items": ["Stop run (estimated)"], "fold": "keep"},
        {"kind": "pills", "items": ["Detector settings", "Methodology docs"], "fold": "keep"},
    ],
    "SCR-059": [
        {"kind": "pills", "items": ["Reset to default", "Cancel", "Apply"], "fold": "keep"},
        {
            "kind": "text",
            "items": ["min_volume_multiple \u00b7 1\u201350 \u00b7 default 3"],
            "fold": "keep",
        },
    ],
}
# D. the id tables the spec carries (counted; the boards and the draft quote them)
COUNT_RX = rows_of(
    r"""boards=^\| (?:0[1-9]|1[0-4]) +\| `
s55=^\| S55-\d+
s56=^\| S56-\d+
s57=^\| S57-\d+
s58=^\| S58-\d+
s59=^\| S59-\d+
copy=^\| CP\d+
keys=^\| K5[5-9]-\d+
flow=^\| F[AB]-\d+
bindings=^\| DB-\d+
c_inherited=^\| C\d+ +\|
c_own=^\| D02-C\d+
g_inherited=^\| G\d+ +\|
g_own=^\| D02-G\d+
x=^\| X\d+ +\|
q=^\| Q\d+ +\|
bq=^\| BQ-\d+
qp=^\| Q-[A-Z0-9]+ +\|
a14=^\| A14-\d+
a15=^\| A15-\d+
h=^\| H-\d+
ho=^\| HO-\d+""",
    "=",
)
# E. string gates
MUST = (
    "Warming up — 4 min 52 s to go",
    "42 trades/s over 5 s \u00b7 3.1 \u03c3 above the 5-min mean",
    "Updates every 1 s, \u00d74 slower",
    "0 /s · quiet",
    "Detector error — last value 13:58:02",
    "no imbalances above 3:1 in this range",
    "Trending up (estimated) · medium",
    "Confidence 0.71 (sub-signal agreement)",
    "Confidence — not supplied",
    "Insufficient data (estimated)",
    "210 of 512 bars",
    "Not available on this server — the stop-run detector is behind a feature flag",
    "Off — turn on in Detector settings",
    "this is an estimate, not exchange-provided fact",
    "Sensitivity high may produce many false positives",
    "Read-only while viewing as {user}.",
    "Your role can't change settings.",
    "Your role can't change alerts.",
    "Only the owner can start recording.",
    "Only the owner can change recording.",
    "Recompute history",
    "Read-only — your role can't change settings.",
    "(estimated)",
)
RBAC_RX = re.compile(
    r"\"((?:Your role can't|Only the owner can|Read-only while viewing as)[^\"]*)\""
)
SHARED = "Research PRs never edit `22`."
FORBIDDEN = {
    "local path": re.compile(r"/(?:home|Users)/[^/\s]+/"),
    "Penpot host": re.compile(r"penpot\.[a-z0-9-]+\.[a-z]{2,}", re.IGNORECASE),
    "Penpot team / file / workspace ref": re.compile(r"team[-_]id=|file[-_]id=|#/work[s]pace"),
    # every rule is cited from its owners (C-16.5): no copied gate block, thread or lane tag,
    # agent name or timestamped ruling ("the 02:13Z ruling", "ruled lane-wide 02:13Z")
    "lane provenance": re.compile(
        r"\[[A-Z0-9]+-GATE\]|^# Standing gates|\b[a-z]{2,5}-worker-\d+\b|\bLANE-\d+\b"
        r"|\[DESIGN-FLOW|\b\d{2}:\d{2}Z ruling\b|\bruled\b[^|\n]{0,40}\b\d{2}:\d{2}Z",
        re.MULTILINE | re.IGNORECASE,
    ),
}
CLOSING_RX = re.compile(
    r"\b(?:clos(?:e|es|ed|ing)|fix(?:es|ed|ing)?|resolv(?:e|es|ed|ing))\b[:\s]*#?\d{2,}",
    re.IGNORECASE,
)
VERB_LINT = (
    "buy",
    "sell",
    "long",
    "short",
    "enter",
    "exit",
    "fade",
    "follow",
    "add",
    "reduce",
    "hold",
    "wait",
    "trade",
)
REGIME_WORDS = re.compile(r"Trending up|Trending down|Ranging|Volatile|Calm", re.IGNORECASE)
NAMED = (
    "color.surface.app",
    "color.surface.canvas",
    "color.surface.raised",
    "color.surface.overlay",
    "color.surface.sunken",
    "color.surface.hover",
    "color.surface.selected",
    "color.text.primary",
    "color.text.secondary",
    "color.text.tertiary",
    "color.text.disabled",
    "color.border.default",
    "color.border.strong",
    "size.row.compact",
    "size.row.comfortable",
    "size.control.compact",
    "size.control.comfortable",
    "space.1",
    "space.2",
    "space.3",
    "font.size.xs",
    "font.size.sm",
    "font.size.base",
    "opacity.disabled",
    "opacity.muted",
)


def px(theme: str, name: str) -> int:
    return int(T[theme][name])


def geometry() -> dict[str, Any]:
    out: dict[str, Any] = {
        "inputs": {"band_px": BAND_PX, "cells": CELLS, "dialog": DIALOG, "drawer_w": DRAWER_W}
    }
    per: dict[str, Any] = {}
    for density in ("compact", "comfortable"):
        row = px("dark", f"size.row.{density}")
        ctl = px("dark", f"size.control.{density}")
        step = px("dark", GAP_TOKEN[density])
        slots56 = {
            "header": ctl + 2 * px("dark", "space.1") if density == "compact" else ctl + step,
            "controls": PILL_PX + step,
            "filters": PILL_PX + step,
            "column header": (16 if density == "compact" else 20) + px("dark", "space.1"),
        }
        slots55 = {
            "header": slots56["header"],
            "controls": PILL_PX + step,
            "readout": 2 * row,
            "status": PILL_PX + step,
        }
        slots57 = {
            "header": slots56["header"],
            "chip row": PILL_PX + step + row,
            "evidence": row,
            "breakdown header": PILL_PX + step,
        }
        frames: dict[str, Any] = {}
        for key, (w, h, top, bottom) in FRAMES.items():
            band = BAND_PX[key]
            list56 = band - sum(slots56.values())
            rows56 = list56 // row  # one of them is the last-price divider row (R2)
            strip55 = band - sum(slots55.values())
            signals57 = (band - sum(slots57.values())) // row
            frames[key] = {
                "workspace_px": h - top - bottom,
                "band_px": band,
                "scr056": {
                    "list_px": list56,
                    "rows": rows56,
                    "zone_rows": rows56 - 1,
                    "divider_rows": 1,
                    "rows_with_notice": (list56 - (PILL_PX + step)) // row - 1,
                },
                "scr055": {"strip_px": strip55},
                "scr057": {"signal_rows": signals57},
                "zoom200_css_px": [w // ZOOM, h // ZOOM],
            }
        per[density] = {
            "row_px": row,
            "control_px": ctl,
            "step_px": step,
            "slots": {"SCR-056": slots56, "SCR-055": slots55, "SCR-057": slots57},
            "frames": frames,
        }
    out["densities"] = per
    out["dialog_zoom200"] = {
        k: {
            "viewport_css_px": [v[0] // ZOOM, v[1] // ZOOM],
            "fills_viewport": DIALOG["1280x800"][0] > v[0] // ZOOM
            or DIALOG["1280x800"][1] > v[1] // ZOOM,
        }
        for k, v in {"1280x800": (1280, 800)}.items()
    }
    return out


def pills_w(items: list[str], ui: int, pad: int, step: int) -> int:
    return sum(inter_w(p, ui - 1) + 2 * pad for p in items) + step * (len(items) - 1)


def row56_w(drop: set[str], mono: int, step: int) -> int:
    cols = [ch for k, ch in CH56.items() if k not in drop]
    return sum(mono_w("x" * ch, mono) for ch in cols) + step * (len(cols) - 1) + 2


def min_widths() -> dict[str, Any]:
    out: dict[str, Any] = {}
    for density in ("compact", "comfortable"):
        ui, mono = px("dark", FONT_UI[density]), px("dark", FONT_MONO[density])
        step, inset = px("dark", GAP_TOKEN[density]), px("dark", INSET_TOKEN)
        pad = 8  # pill padX (the board script's default)

        pills = partial(pills_w, ui=ui, pad=pad, step=step)
        row56 = partial(row56_w, mono=mono, step=step)

        per: dict[str, Any] = {}
        for scr, rows in ONE_LINE.items():
            widest, folded, which, which_f = 0, 0, "", ""
            for r in rows:
                kind, items, fold = str(r["kind"]), list(r["items"]), str(r["fold"])
                if kind == "pills":
                    w = pills(items)
                    wf = {
                        "icon-last": pills(items[:-1]) + step + ICON_PX,
                        "drop-last": pills(items[:-1]),
                        "wrap": max(pills([p]) for p in items),
                    }.get(fold, w)
                elif kind == "row56":
                    w, wf = row56(LADDER56[0]), row56(LADDER56[-1])
                else:
                    w = inter_w(items[0], ui)
                    wf = 0 if fold == "wrap" else w
                if w > widest:
                    widest, which = w, " · ".join(items) or kind
                if wf > folded:
                    folded, which_f = wf, (" · ".join(items) or kind) + f" ({fold})"
            entry = {
                "min_width_px": widest + 2 * inset,
                "widest": which,
                "min_width_folded_px": folded + 2 * inset,
                "widest_folded": which_f,
            }
            if scr == "SCR-056":
                entry["ladder_px"] = [row56(st) + 2 * inset for st in LADDER56]
            per[scr] = entry
        out[density] = {"ui_px": ui, "mono_px": mono, "panels": per}
    fits: dict[str, Any] = {}
    for key, cells in CELLS.items():
        fits[key] = {}
        for scr in ("SCR-055", "SCR-056", "SCR-057"):
            fits[key][scr] = {}
            for d in ("compact", "comfortable"):
                p = out[d]["panels"][scr]
                steps = p.get("ladder_px", [p["min_width_px"], p["min_width_folded_px"]])
                first = next((i for i, v in enumerate(steps) if cells[scr] >= v), None)
                fits[key][scr][d] = {
                    "cell_px": cells[scr],
                    "min_px": p["min_width_px"],
                    "folded_px": p["min_width_folded_px"],
                    "fits_default": cells[scr] >= p["min_width_px"],
                    "fits_folded": cells[scr] >= p["min_width_folded_px"],
                    "ladder_step": first,
                }
    out["fits"] = fits
    out["fixed"] = {
        "SCR-058": {
            "drawer_px": DRAWER_W,
            "widest_px": {
                d: out[d]["panels"]["SCR-058"]["min_width_px"] for d in ("compact", "comfortable")
            },
        },
        "SCR-059": {
            "dialog_px": DIALOG["1280x800"][0],
            "widest_px": {
                d: out[d]["panels"]["SCR-059"]["min_width_px"] for d in ("compact", "comfortable")
            },
        },
    }
    return out


def counts(spec: str) -> dict[str, Any]:
    out: dict[str, Any] = {}
    for name, rx in COUNT_RX:
        out[name] = sum(1 for ln in spec.splitlines() if re.match(rx, ln))
    out["states"] = sum(out[k] for k in ("s55", "s56", "s57", "s58", "s59"))
    return out


def reconcile(spec: str, problems: list[str]) -> dict[str, Any]:
    boards = {m.group(1) for m in re.finditer(r"^\| (0[1-9]|1[0-4]) +\| `", spec, re.MULTILINE)}
    state_rows = [ln for ln in spec.splitlines() if re.match(r"^\| S5[5-9]-\d+ ", ln)]
    ids = {ln.split("|")[1].strip() for ln in state_rows}
    orphan_rows, missing_ids = [], []
    for ln in state_rows:
        cells = [c.strip() for c in ln.strip().strip("|").split("|")]
        refs = re.findall(r"\b(0[1-9]|1[0-4])\b", cells[-1])
        if not refs or any(r not in boards for r in refs):
            orphan_rows.append(cells[0])
    board_rows = [ln for ln in spec.splitlines() if re.match(r"^\| (?:0[1-9]|1[0-4]) +\| `", ln)]
    named = set()
    for ln in board_rows:
        named |= set(re.findall(r"\bS5[5-9]-\d+\b", ln))
    missing_ids = sorted(i for i in named if i not in ids)
    problems += [f"state row {i} names no board of 01..14" for i in orphan_rows]
    problems += [f"board table names state {i}, which has no row" for i in missing_ids]
    return {
        "boards": sorted(boards),
        "state_ids": len(ids),
        "states_named_on_boards": len(named),
        "orphan_rows": orphan_rows,
        "missing_ids": missing_ids,
    }


def gates(text: str, label: str, constitution: str, problems: list[str]) -> dict[str, Any]:
    missing = [s for s in MUST if s not in text] if label == "spec" else []
    problems += [f"{label}: missing {s!r}" for s in missing]
    long_reasons = sorted({s for s in RBAC_RX.findall(text) if len(s) > 60})
    problems += [f"{label}: T2 reason over 60 characters {s!r}" for s in long_reasons]
    for ln in text.splitlines():
        if "Est." in ln and not re.search(r"E11-D04|E25-D05|C15|Q4|never", ln):
            problems.append(f"{label}: 'Est.' outside a sibling citation")
        g_row = re.match(r"^\| (?:G\d+|D02-G\d+) ", ln) and re.search(r"`2[23]`", ln)
        if g_row and SHARED not in ln:
            problems.append(f"{label}: a G-row names `22` / `23` without the shared sentence")
        if re.match(r"^\| CP\d+ ", ln) and "SCR-057" in ln and REGIME_WORDS.search(ln):
            words = set(re.findall(r"[a-z]+", ln.lower()))
            verbs = sorted(words & set(VERB_LINT))
            if verbs:
                problems.append(f"{label}: regime copy row carries an imperative verb {verbs}")
    # lane provenance is a spec-only gate: the PR body keeps its publisher's signature
    rules = {n: rx for n, rx in FORBIDDEN.items() if label == "spec" or n != "lane provenance"}
    hits = {name: sorted(set(rx.findall(text))) for name, rx in rules.items()}
    problems += [f"{label}: {name} {h!r}" for name, hs in hits.items() for h in hs]
    ids = sorted(set(re.findall(r"\bC-\d+\.\d+\b", text)))
    absent = [i for i in ids if not re.search(rf"\b{re.escape(i)}\b", constitution)]
    problems += [f"{label}: {i} not in CONSTITUTION.md" for i in absent]
    return {
        "missing": missing,
        "forbidden": {k: len(v) for k, v in hits.items()},
        "rule_ids": len(ids),
        "long_reasons": long_reasons,
    }


def drift(
    spec: str, geo: dict[str, Any], mw: dict[str, Any], cnt: dict[str, Any], mx: dict[str, Any]
) -> list[str]:
    """The sentences the spec must carry for the tool's numbers (sections 3-5, 9, 11, 16, 22)."""
    pairs, fails, ok, tot = len(PAIRS), mx["fail"], mx["repro_ok"], mx["repro_n"]
    pt = "pairs \u00d7 3 themes"
    need: list[str] = [f"{pairs} {pt}", f"FAIL count {fails}", f"FAIL {fails};"]
    need += [f"({ok} of {tot})", f"{ok} / {tot}"]
    # every stated pair / FAIL count must equal the matrix, not only one of the statements
    stated = set(re.findall(rf"(\d+) {pt}", spec)) - {str(pairs)}
    need += [f"{pairs} {pt} (it also states {m})" for m in sorted(stated)]
    stated = set(re.findall(r"\bFAIL (?:count )?(\d+)\b", spec)) - {str(fails)}
    need += [f"FAIL count {fails} (it also states {m})" for m in sorted(stated)]
    # the binding split: the gap list's DB ids are counted, bound = the DB-rows less the gaps
    gx = re.search(r"(\d+) name a gap \(([^)]*)\)", spec)
    gaps = len(set(re.findall(r"\bDB-\d+\b", gx.group(2)))) if gx else -1
    rows = cnt["bindings"]
    need += [f"{rows - gaps} of the {rows} DB-rows", f"{gaps} name a gap ("]
    for d in ("compact", "comfortable"):
        for key in FRAMES:
            z = geo["densities"][d]["frames"][key]["scr056"]["zone_rows"]
            need.append(f"{z} zone rows")
        for scr in ("SCR-055", "SCR-056", "SCR-057"):
            need.append(f"{mw[d]['panels'][scr]['min_width_px']} px")
            need.append(f"{mw[d]['panels'][scr]['min_width_folded_px']} px")
    for k in ("s55", "s56", "s57", "s58", "s59"):
        need.append(f"{cnt[k]} frames")
    need.append(f"{cnt['states']} state rows")
    return [n for n in need if n not in spec]


def main(argv: list[str] | None = None) -> int:
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")
    ap = argparse.ArgumentParser()
    ap.add_argument("--json", action="store_true")
    ap.add_argument("--check", action="store_true", help="fail on drift vs the spec's sentences")
    ap.add_argument("--spec", default=str(ROOT / "docs" / "design" / "E25" / "E25-D02.md"))
    ap.add_argument("--draft", default=None)
    a = ap.parse_args(argv)
    quiet, problems, out = bool(a.json), [], {}  # type: bool, list[str], dict[str, Any]

    def say(s: str) -> None:
        if not quiet:
            print(s)

    say("## A. Greyscale matrix (packages/ui/tokens; unrounded compare; 4 decimals on a bar)\n")
    say("| Element | fg | bg | role | dark | light | hc | verdict |")
    say("|---|---|---|---|---|---|---|---|")
    fails, rows, repro = 0, [], []  # type: int, list[dict[str, Any]], list[list[Any]]
    for element, fg, bg, role in PAIRS:
        if role == "validity":
            vals = [ratio(dimmed(t, fg, bg), col(t, bg)) for t in THEMES]
        else:
            vals = [ratio(col(t, fg), col(t, bg)) for t in THEMES]
        bar = BAR[role]
        bad = [THEMES[i] for i, v in enumerate(vals) if bar is not None and v < bar]
        verdict = "PASS" if not bad else "FAIL: " + ", ".join(bad)
        if bar is None:
            verdict = "decorative (not gated)"
        elif role == "rejected":
            verdict = "rejected by design; would " + verdict
        elif role == "validity":
            verdict = (
                "reported, not gated (the full-opacity reason carries; E30-D02 D3): would "
                + verdict
            )
        elif bad:
            fails += 1
        cells = " | ".join(f"{v:.4f}" if bar and abs(v - bar) < 0.005 else f"{v:.2f}" for v in vals)
        say(f"| {element} | `{TOK[fg]}` | `{TOK[bg]}` | {role} | {cells} | {verdict} |")
        r2, key = [round(v, 2) for v in vals], f"{fg}|{bg}"
        rows.append({"element": element, "fg": TOK[fg], "bg": TOK[bg], "role": role, "ratio": r2})
        if role == "text" and key in E13_DARK:
            repro.append(["E13-D02", key, r2[0], E13_DARK[key], r2[0] == E13_DARK[key]])
    n_ok = sum(1 for e in repro if e[4])
    say(f"\nFAIL count (gated rows only): {fails}; reproductions {n_ok}/{len(repro)} match")
    out["matrix"] = {
        "rows": rows,
        "fail": fails,
        "reproductions": repro,
        "resolved": {t: {TOK[k]: col(t, k) for k in TOK} for t in THEMES},
        "opacity_disabled": float(T["dark"]["opacity.disabled"]),
    }

    geo = geometry()
    say("\n## B. Geometry (spec 3 / 4 px inputs, PROPOSED; row counts printed, never asserted)\n")
    for d, g in geo["densities"].items():
        for key, fr in g["frames"].items():
            say(
                f"- {d} {key}: band {fr['band_px']} px; SCR-056 list {fr['scr056']['list_px']} px"
                f" → {fr['scr056']['rows']} rows ({fr['scr056']['zone_rows']} zone rows + the"
                f" last-price divider; {fr['scr056']['rows_with_notice']} zone rows under a"
                f" notice); SCR-055 strip {fr['scr055']['strip_px']} px; SCR-057"
                f" {fr['scr057']['signal_rows']} signal rows; 200 % zoom viewport"
                f" {fr['zoom200_css_px'][0]}\u00d7{fr['zoom200_css_px'][1]} CSS px"
            )
    out["geometry"] = geo

    mw = min_widths()
    say(
        "\n## C. Minimum panel widths (the widest one-line string per panel; Inter upper-bound"
        " advances, mono 0.62 em)\n"
    )
    for d in ("compact", "comfortable"):
        for scr, v in mw[d]["panels"].items():
            say(
                f"- {d} {scr}: {v['min_width_px']} px minimum (folded"
                f" {v['min_width_folded_px']} px) — widest: {v['widest']}; folded:"
                f" {v['widest_folded']}"
            )
    for key, f in mw["fits"].items():
        for scr, dd in f.items():
            verdicts = []
            for d in ("compact", "comfortable"):
                v = dd[d]
                state = (
                    "fits"
                    if v["fits_default"]
                    else (
                        "folds, ladder step " + str(v["ladder_step"])
                        if v["fits_folded"]
                        else "BELOW the folded minimum"
                    )
                )
                verdicts.append(f"{d} {state}")
            say(f"- {key} {scr}: cell {dd['compact']['cell_px']} px; " + "; ".join(verdicts))
    out["min_widths"] = mw

    spec_path = Path(a.spec)
    spec = spec_path.read_text(encoding="utf-8") if spec_path.exists() else ""
    constitution = (ROOT / "CONSTITUTION.md").read_text(encoding="utf-8")
    cnt = counts(spec)
    say("\n## D. Counts (the spec's id tables)\n")
    say(json.dumps(cnt))
    out["counts"] = cnt
    if spec:
        out["reconcile"] = reconcile(spec, problems)
        say(
            f"\n## E. Frame reconciliation: {out['reconcile']['state_ids']} state rows,"
            f" {out['reconcile']['states_named_on_boards']} named on boards, orphans"
            f" {out['reconcile']['orphan_rows']}, missing {out['reconcile']['missing_ids']}"
        )
        out["gates"] = {"spec": gates(spec, "spec", constitution, problems)}
    else:
        problems.append(f"spec not found: {spec_path}")
    if a.draft:
        draft = Path(a.draft).read_text(encoding="utf-8")
        g = gates(draft, "draft", constitution, problems)
        closing = CLOSING_RX.findall(draft)
        problems += [f"draft: closing keyword {c!r}" for c in closing]
        g["closing"] = closing
        out.setdefault("gates", {})["draft"] = g

    say("\n## F. Tokens named by the spec (all must exist)\n")
    missing_tok = [n for n in NAMED if n not in T["dark"]]
    problems += [f"token missing: {n}" for n in missing_tok]
    out["tokens"] = {
        "named": len(NAMED),
        "missing": missing_tok,
        "font_size_scale": sorted(
            int(v) for k, v in T["dark"].items() if k.startswith("font.size.") and str(v).isdigit()
        ),
    }

    if a.check and spec:
        mx = {"fail": fails, "repro_ok": n_ok, "repro_n": len(repro)}
        out["drift"] = drift(spec, geo, mw, cnt, mx)
        problems += [f"drift: the spec does not carry {n!r}" for n in out["drift"]]
    out["problems"] = problems
    if quiet:
        print(json.dumps(out, ensure_ascii=False))
    elif problems:
        print("\nPROBLEMS:\n- " + "\n- ".join(problems))
    else:
        print("\nOK: no gated failure; every state row names a board; every gate passed")
    return 1 if problems or fails else 0


if __name__ == "__main__":
    raise SystemExit(main())
