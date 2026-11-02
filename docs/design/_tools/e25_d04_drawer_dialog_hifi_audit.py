"""E25-D04 hi-fi audit: every number the SCR-058 / SCR-059 hi-fi spec states, computed.

Standalone, offline, stdlib only (`python3 -I`). Themes resolve exactly as
`packages/ui/tokens/tests/verify_tokens.py` resolves them and contrast is `contrast_ratio()` from
`docs/design/_tools/contrast_check.py` (both imported with one loader, never re-implemented). The
greyscale and deuteranopia maths are `docs/design/_tools/cvd_sim.py`'s (Rec. 601 luma, the Machado
2009 matrix), re-stated here on single colours so the tool needs no numpy. Nothing here reads a
fixture or a network.

Sections: A the resolved tokens every binding names (a name that does not resolve is a FAIL);
B the contrast matrix, every pair in dark / light / high-contrast compared unrounded against its
bar, composited rows (`opacity.disabled`) by the E22-D03 `over()` method; C the `DetectorConfig`
field table — every bound, default, step and validation message the spec states, cross-read from
`docs/plan/22-api-openapi.yaml` (a bound the spec does not carry verbatim is a FAIL) — and the
unit forms this spec adds to the E25 number-format sheet; D the greyscale / deuteranopia
statement; E the board plan (<= 10 boards, light twins <= one third) in the mode §0's heading
names: PENDING (every row PENDING, no id, no export committed) or drawn (every row its export
path and board uuid, the page id, the exports table equal to the committed PNGs - their IHDR size
and sha256 - with the greyscale / deuteranopia renders of 01-09; uuids only inside §0); F the
spec's own tables and strings (the apply state machine never reaches "applied" before the 200 and
its unknown-outcome leg re-reads before any value is shown, the three confirmation variants and
the fetch point on the Apply press, the T2 matrix with every write locked for a Manager, Viewer and
view-as and the admin link omitted rather than locked, the motion pairs, the fixed sentences, the
E25-D02 strings carried verbatim, the hygiene patterns, the rule ids) and the two `14` pointer
lines, and §12's A-1 as applied (the CMP-069 Tokens line in `15` equal to its proposed text); H
every P-row's `pairs.mjs` registration claim cross-read from `tools/contrast/pairs.mjs`
(read, never written) and the counts the spec types in words.

Usage: python3 -I docs/design/_tools/e25_d04_drawer_dialog_hifi_audit.py [--json]
       python3 -I docs/design/_tools/e25_d04_drawer_dialog_hifi_audit.py --check [SPEC]
       python3 -I docs/design/_tools/e25_d04_drawer_dialog_hifi_audit.py --self-test [SPEC]
`--check` exits 1 on a gated FAIL, a lost reproduction, a failed table or string gate, or a number
the tool prints that the spec's own text does not carry (section G, drift). `--self-test` applies
MUTATIONS to the spec in memory (the file is never written): each must raise exactly one new FAIL,
no two the same, and the clean spec must pass before and after. The boards mutations run on the
drawn view: the committed state once §0 is drawn, or, while §0 is PENDING, one synthesised in
memory (made-up ids and PNG headers, never written), so the drawn gate is proven before the draw.
Stdout is UTF-8.
"""

from __future__ import annotations

import hashlib
import importlib.util
import io
import json
import re
import struct
import sys
import zlib
from collections.abc import Callable
from pathlib import Path
from types import ModuleType
from typing import Any

ROOT = Path(__file__).resolve().parents[3]
TOKENS = ROOT / "packages" / "ui" / "tokens"
TOOLS = ROOT / "docs" / "design" / "_tools"
SPEC = ROOT / "docs" / "design" / "E25" / "E25-D04.md"
OPENAPI = ROOT / "docs" / "plan" / "22-api-openapi.yaml"
SCREENS = ROOT / "docs" / "plan" / "14-screens-catalogue.md"
CATALOGUE = ROOT / "docs" / "plan" / "15-component-catalogue.md"
PAIRS_MJS = ROOT / "tools" / "contrast" / "pairs.mjs"
CONSTITUTION = ROOT / "CONSTITUTION.md"
IMG_REL = "docs/design/E25/img"
IMG = ROOT / IMG_REL
THEMES = ("dark", "light", "high-contrast")
BAR: dict[str, float | None] = {"text": 4.5, "non-text": 3.0}
BAR.update({"decorative": None, "reported": None, "rejected-text": 4.5, "rejected-non-text": 3.0})
GATED = {"text", "non-text"}


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
    return [[c.strip() for c in ln.split(sep)] for ln in txt.strip().splitlines()]


TOK = dict(rows_of("""overlay|color.surface.overlay
raised|color.surface.raised
sunken|color.surface.sunken
t1|color.text.primary
t2|color.text.secondary
t3|color.text.tertiary
t.disabled|color.text.disabled
link|color.text.link
on-action|color.text.on-action
b.default|color.border.default
b.selected|color.border.selected
ring|color.focus.ring
buy|color.buy.default
sell|color.sell.default
n.subtle|color.neutral.subtle
warn.subtle|color.status.warning.subtle
warn.strong|color.status.warning.strong
info.default|color.status.info.default
info.subtle|color.status.info.subtle
info.strong|color.status.info.strong
danger.default|color.status.danger.default
danger.subtle|color.status.danger.subtle
danger.strong|color.status.danger.strong
a.primary|color.action.primary.default
a.selected|color.action.selected
a.secondary|color.action.secondary.default"""))


def rgb(h: str) -> tuple[int, int, int]:
    h = h.lstrip("#")
    return int(h[0:2], 16), int(h[2:4], 16), int(h[4:6], 16)


def hexs(c: tuple[float, float, float]) -> str:
    return "#" + "".join(f"{min(255, max(0, round(v))):02X}" for v in c)


def ratio(fg: str, bg: str) -> float:
    return float(contrast_check.contrast_ratio(rgb(fg), rgb(bg)))


def col(theme: str, short: str) -> str:
    return str(T[theme][TOK.get(short, short)])


def over(theme: str, short: str, alpha: float, under: str) -> str:
    """Ink drawn at `alpha` over a surface: the colour the eye meets (E22-D03's method)."""
    top, base = rgb(col(theme, short)), rgb(col(theme, under))
    mix = [alpha * t + (1 - alpha) * u for t, u in zip(top, base, strict=True)]
    return hexs((mix[0], mix[1], mix[2]))


def fg_of(theme: str, spec: str, under: str) -> str:
    """`tok` or `tok@alpha` (composited over `under`)."""
    if "@" in spec:
        tok, a = spec.split("@")
        return over(theme, tok, float(a), under)
    return col(theme, spec)


def fmt3(vals: list[float], bar: float | None) -> str:
    """Two decimals; four where a value would round onto its bar (the unrounded compare)."""
    out = []
    shown = 3.0 if bar is None else bar
    for v in vals:
        if round(v, 2) == shown and abs(v - shown) > 1e-9:
            out.append(f"{v:.4f}")
        else:
            out.append(f"{v:.2f}")
    return " / ".join(out)


# A. the tokens the spec binds: every backticked token-like name must resolve in every theme
TOKEN_RX = re.compile(
    r"`((?:color|type|space|size|radius|border|motion|opacity|font|elevation)\.[a-z0-9.-]+)`"
)


def tokens(spec: str) -> dict[str, Any]:
    names = sorted(set(TOKEN_RX.findall(spec)))
    missing = [n for n in names if any(n not in T[t] for t in THEMES)]
    return {"named": len(names), "missing": missing}


# B. the matrix: id | element | fg | bg | role | pairs.mjs status. Both surfaces sit on overlay.
PAIRS = rows_of(
    """P1|drawer prose, section headings, dialog title, field values, legend text (t1 on overlay)|t1|overlay|text|registered
P2|template labels, captions, T2 reasons, footer audit sentence, changed-marker word and glyph (t2 on overlay)|t2|overlay|text|registered
P3|T2 labels, key captions, Toggle off track, disclosure chevrons (t3 on overlay)|t3|overlay|text|registered
P4|CMP-021 links: Detector settings, Methodology docs, glossary, the audit link (link on overlay)|link|overlay|text|held out (E47-D03)
P5|CMP-227 section and inline badge outline and glyph on the overlay (the word carries)|info.default|overlay|non-text|PROPOSED (D05 CR-5)
P6|callout sentence, badge word (t1 on info.subtle)|t1|info.subtle|text|registered
P7|callout body copy (t2 on info.subtle)|t2|info.subtle|text|PROPOSED (CR-1)
P8|info callout edge and glyph (info.strong on info.subtle)|info.strong|info.subtle|non-text|registered
P9|inline badge glyph inside the callout (info.default on info.subtle)|info.default|info.subtle|non-text|PROPOSED (D03 CR-1)
P10|armed-rule warning title, rule names (t1 on warning.subtle)|t1|warn.subtle|text|registered
P11|armed-rule warning body (t2 on warning.subtle)|t2|warn.subtle|text|PROPOSED (CR-1)
P12|warning callout edge and glyph (warning.strong on warning.subtle)|warn.strong|warn.subtle|non-text|registered
P13|failed-apply title "Not applied" (t1 on danger.subtle)|t1|danger.subtle|text|registered
P14|failed-apply before → after body (t2 on danger.subtle)|t2|danger.subtle|text|PROPOSED (CR-1)
P15|danger callout edge and glyph; the CMP-040 error glyph (danger.strong on danger.subtle)|danger.strong|danger.subtle|non-text|registered
P16|focus ring on the overlay (every stop)|ring|overlay|non-text|registered
P17|Apply, Confirm "Apply changes", the recording CTA: CMP-001 primary label; the Toggle knob on its on track (on-action on action.primary)|on-action|a.primary|text|registered
P18|Toggle on track, the primary fill against the overlay|a.primary|overlay|non-text|PROPOSED (CR-1)
P19|Cancel, Reset to default, Retry, Try again, Keep editing: CMP-001 secondary label|t1|a.secondary|text|PROPOSED (D03 CR-1)
P20|mode selected segment label (CMP-003)|t1|a.selected|text|registered
P21|mode selected 2 px inner outline (CMP-003)|b.selected|a.selected|non-text|PROPOSED (D03 CR-1)
P22|the thresholds block, the restatement box, the T2 fill: primary text (t1 on raised)|t1|raised|text|registered
P23|T2 reason on the raised fill; the Default column (t2 on raised)|t2|raised|text|registered
P24|T2 label and lock glyph on the raised fill; the key captions in the block (t3 on raised)|t3|raised|text|registered
P25|CMP-228-look preview value (t1 on sunken)|t1|sunken|text|PROPOSED (CR-1)
P26|CMP-228-look preview caption and "Preview unavailable" (t2 on sunken)|t2|sunken|text|registered
P27|override tag word (CMP-011 neutral: t2 on neutral.subtle)|t2|n.subtle|text|unregistered (E05)
P28|invalid field edge (danger.default on overlay; the message and glyph carry)|danger.default|overlay|non-text|PROPOSED (CR-1)
P29|CMP-134 card chip ▲ BUY glyph on the overlay (boards 03 / 04 / 09 specimens)|buy|overlay|non-text|PROPOSED (CR-1)
P30|CMP-134 card chip ▼ SELL glyph on the overlay (boards 03 / 04 / 09 specimens)|sell|overlay|non-text|PROPOSED (CR-1)
P31|hairlines: header rule, fieldset dividers, T2 hairline, inset outlines (decorative)|b.default|overlay|decorative|—
P32|validity look: Apply label at opacity.disabled on the overlay (the reason carries)|t1@0.45|overlay|reported|—
P33|rejected: color.text.disabled on the overlay (never on a T2 label, glyph or reason)|t.disabled|overlay|rejected-text|—
P34|rejected: a hued callout word (info.strong on info.subtle)|info.strong|info.subtle|rejected-text|—
P35|rejected: a hued warning word (warning.strong on warning.subtle)|warn.strong|warn.subtle|rejected-text|—
P36|rejected: a hued danger word (danger.strong on danger.subtle)|danger.strong|danger.subtle|rejected-text|—"""
)

# Reproductions (to the hundredth): E25-D02 §16 (overlay, sunken, the dimmed label, text.disabled),
# E25-D05 §12.1 (the section badge on overlay), E25-D03 §8.1 (the shared fills and actions).
# P8, P12, P15 and P34 are re-pinned at the refresh base (4c662fd5b): the light status tokens moved on
# main (#5140, #5161) and the sibling specs keep the earlier light values (D04-C9).
REPRO: dict[str, tuple[float, float, float]] = {
    "P1": (13.27, 14.37, 15.02),
    "P2": (8.14, 8.26, 13.27),
    "P3": (5.20, 5.44, 10.36),
    "P5": (5.73, 3.20, 5.73),
    "P6": (10.74, 15.44, 12.16),
    "P8": (7.30, 5.30, 7.30),
    "P9": (4.64, 3.44, 4.64),
    "P10": (9.86, 15.62, 11.16),
    "P12": (7.56, 4.90, 7.56),
    "P13": (12.06, 14.64, 13.66),
    "P15": (7.83, 6.33, 7.83),
    "P19": (10.17, 12.82, 11.51),
    "P20": (12.33, 14.58, 13.96),
    "P21": (4.20, 3.86, 5.72),
    "P22": (14.35, 15.62, 16.25),
    "P23": (8.81, 8.98, 14.35),
    "P24": (5.62, 5.92, 11.21),
    "P25": (17.42, 12.82, 19.73),
    "P26": (10.69, 7.37, 17.42),
    "P27": (7.50, 8.26, 12.22),
    "P32": (3.81, 2.81, 4.14),
    "P33": (2.64, 3.44, 2.64),
    "P34": (7.30, 5.30, 7.30),
}


def matrix(problems: list[str]) -> dict[str, Any]:
    rows: list[dict[str, Any]] = []
    fails = gated = 0
    repro_ok = repro_n = 0
    for pid, element, fg, bg, role, reg in PAIRS:
        bar = BAR[role]
        vals = [ratio(fg_of(t, fg, bg), col(t, bg)) for t in THEMES]
        verdict = "—"
        if role in GATED:
            gated += 1
            bad = [t for t, v in zip(THEMES, vals, strict=True) if v < (bar or 0)]
            verdict = "PASS" if not bad else "FAIL " + ", ".join(bad)
            if bad:
                fails += 1
                problems.append(f"contrast FAIL {pid} {element}: {fmt3(vals, bar)}")
        elif role.startswith("rejected"):
            bad = [t for t, v in zip(THEMES, vals, strict=True) if v < (bar or 0)]
            verdict = "rejected: fails " + ", ".join(bad) if bad else "rejected by design"
        else:
            verdict = role
        if pid in REPRO:
            repro_n += 1
            exp = REPRO[pid]
            ok = all(abs(round(v, 2) - e) < 1e-9 for v, e in zip(vals, exp, strict=True))
            repro_ok += int(ok)
            if not ok:
                problems.append(f"reproduction lost {pid}: {fmt3(vals, bar)} vs {exp}")
        rows.append(
            {
                "id": pid,
                "element": element,
                "fg": TOK.get(fg.split("@")[0], fg)
                + (("@" + fg.split("@")[1]) if "@" in fg else ""),
                "bg": TOK[bg],
                "role": role,
                "dark": vals[0],
                "light": vals[1],
                "hc": vals[2],
                "text": fmt3(vals, bar),
                "verdict": verdict,
                "pairs_mjs": reg,
            }
        )
    return {
        "pairs": len(rows),
        "gated": gated,
        "fail": fails,
        "repro_ok": repro_ok,
        "repro_n": repro_n,
        "rows": rows,
    }


# C. the DetectorConfig field table (BQ-05 RULED) and the unit forms added to the E25 sheet
def fmt_num(v: float, precision: int) -> str:
    """Comma-grouped from four digits; at most `precision` decimals, trailing zeros dropped."""
    s = f"{v:,.{precision}f}"
    if precision:
        s = s.rstrip("0").rstrip(".")
    return s


def fmt_unit(v: float, unit: str, precision: int) -> str:
    return fmt_num(v, precision) + (f" {unit}" if unit else "")


def message(noun: str, lo: float | None, hi: float | None, unit: str, precision: int) -> str:
    """The BQ-05 template: "Enter {noun} between {min} and {max}{ unit}."; no maximum → "of {min} or more"."""
    tail = f" {unit}" if unit else ""
    if hi is None:
        return f"Enter {noun} of {fmt_num(lo or 0, precision)} or more."
    return f"Enter {noun} between {fmt_num(lo or 0, precision)} and {fmt_num(hi, precision)}{tail}."


# fieldset | key | kind | min | max | default | unit | step | large step | precision | label | noun
FIELDS = rows_of("""iceberg|enabled|toggle|||true|||||Enable iceberg|
iceberg|min_reloads|integer|2|50|3||1|10|0|Minimum reloads|a reload count
iceberg|price_tolerance_ticks|integer|0|10|0|ticks|1|10|0|Price tolerance|a tolerance
iceberg|window_ms|integer|200|60000|5000|ms|100|1000|0|Window|a window
stop_run|enabled|toggle|||true|||||Enable stop run|
stop_run|lookback_bars|integer|2|500|20|bars|1|10|0|Look-back|a look-back
stop_run|penetration_ticks|integer|1|100|2|ticks|1|10|0|Penetration|a penetration
stop_run|reversal_pct|number|0|100|60|%|1|10|0|Reversal|a reversal
absorption|enabled|toggle|||true|||||Enable absorption|
absorption|min_volume_multiple|number|1|50|3|×|0.5|5|1|Minimum volume multiple|a multiple
absorption|max_price_move_ticks|integer|0|50|1|ticks|1|10|0|Maximum price move|a price move
exhaustion|enabled|toggle|||true|||||Enable exhaustion|
exhaustion|min_delta_divergence|number|0||0.5||0.1|1|1|Minimum delta divergence|a divergence
big_trade|mode|segment|||percentile|||||Mode|
big_trade|absolute_usd|decimal|||—|USDT|1000|10000|0|Absolute threshold|an amount in USDT greater than 0
big_trade|percentile|number|50|99.99|99||0.5|5|2|Percentile|a percentile""")
NO_BOUND_MESSAGE = "Enter an amount in USDT greater than 0."  # absolute_usd: no bound in `22` (G2)
SUMMARY = ("Fix 1 field to apply.", "Fix 2 fields to apply.")
YAML_RX = re.compile(
    r"^\s+(?P<key>[a-z_]+): \{ type: (?P<type>\w+)"
    r"(?:, minimum: (?P<min>[\d.]+))?(?:, maximum: (?P<max>[\d.]+))?"
    r"(?:, default: (?P<default>[\w.]+))?",
    re.MULTILINE,
)


def _num(s: str | None) -> float | None:
    return None if s in (None, "", "—") else float(s)


def yaml_bounds() -> dict[str, dict[str, Any]]:
    """The `DetectorConfig` block of `22`, key by key (the contract is the source, never a copy)."""
    text = OPENAPI.read_text(encoding="utf-8")
    i = text.find("\n    DetectorConfig:\n")
    j = text.find("\n    DetectorMethodology:\n")
    block = text[i:j] if 0 <= i < j else ""
    out: dict[str, dict[str, Any]] = {}
    for m in YAML_RX.finditer(block):
        out[m["key"]] = {
            "type": m["type"],
            "min": _num(m["min"]),
            "max": _num(m["max"]),
            "default": m["default"],
        }
    if "absolute_usd" not in out and "absolute_usd: { $ref:" in block:
        out["absolute_usd"] = {"type": "Decimal", "min": None, "max": None, "default": None}
    return out


def field_rows() -> list[dict[str, Any]]:
    rows = []
    for n, (fs, key, kind, lo, hi, dflt, unit, step, large, prec, label, noun) in enumerate(
        FIELDS, start=1
    ):
        p = int(prec) if prec else 0
        lo_f, hi_f = _num(lo), _num(hi)
        if kind in ("toggle", "segment"):
            rng, msg, default_txt, step_txt = "—", "—", dflt, "—"
        elif kind == "decimal":
            rng, msg, default_txt = "> 0 (no bound in `22`)", NO_BOUND_MESSAGE, "—"
            step_txt = f"{fmt_num(float(step), 0)} / {fmt_num(float(large), 0)}"
        else:
            rng = (
                f"{fmt_num(lo_f or 0, p)}–{fmt_num(hi_f, p)}"
                if hi_f is not None
                else f"≥ {fmt_num(lo_f or 0, p)}"
            )
            msg = message(noun, lo_f, hi_f, unit, p)
            default_txt = fmt_num(float(dflt), p)
            step_txt = f"{fmt_num(float(step), p)} / {fmt_num(float(large), p)}"
        rows.append(
            {
                "id": f"F-{n}",
                "fieldset": fs,
                "key": key,
                "kind": kind,
                "min": lo_f,
                "max": hi_f,
                "default": dflt,
                "unit": unit or "—",
                "range": rng,
                "default_txt": default_txt,
                "step": step_txt,
                "precision": prec or "—",
                "label": label,
                "message": msg,
            }
        )
    return rows


UNIT_SAMPLES: list[tuple[str, str]] = [
    ("ms 5000", fmt_unit(5000, "ms", 0)),
    ("ms 60000", fmt_unit(60000, "ms", 0)),
    ("ticks 2", fmt_unit(2, "ticks", 0)),
    ("bars 20", fmt_unit(20, "bars", 0)),
    ("percent 60", fmt_unit(60, "%", 0)),
    ("multiple 3", fmt_unit(3, "×", 1)),
    ("multiple 2.5", fmt_unit(2.5, "×", 1)),
    ("divergence 0.5", fmt_unit(0.5, "", 1)),
    ("percentile 99", fmt_unit(99, "", 2)),
    ("percentile 99.99", fmt_unit(99.99, "", 2)),
    ("USDT 25000", fmt_unit(25000, "USDT", 0)),
    ("USDT 1000000", fmt_unit(1_000_000, "USDT", 0)),
]


DRAWER_PX = 420  # E25-D02 D18 (host data; CMP-046's built default 480 is overridden)
UI_EM = 0.5  # the lane's average Inter advance at body size


def measure() -> dict[str, int]:
    """The SCR-058 prose measure: the drawer's inner width over the body advance (BQ-08)."""
    pad = int(T["dark"]["space.panel.padding"])
    body = int(T["dark"]["font.size.base"])
    inner = DRAWER_PX - 2 * pad
    return {"inner_px": inner, "chars": int(inner // (body * UI_EM))}


def fields(problems: list[str]) -> dict[str, Any]:
    rows = field_rows()
    y = yaml_bounds()
    for r in rows:
        if r["kind"] in ("toggle", "segment"):
            continue
        yk = y.get(r["key"])
        if yk is None:
            problems.append(f"22 has no DetectorConfig key {r['key']}")
            continue
        if (yk["min"], yk["max"]) != (r["min"], r["max"]):
            problems.append(f"bound drift {r['key']}: 22 says {yk['min']}–{yk['max']}")
        if r["kind"] != "decimal" and float(yk["default"]) != float(r["default"]):
            problems.append(f"default drift {r['key']}: 22 says {yk['default']}")
    return {
        "rows": rows,
        "yaml_keys": len(y),
        "unit_samples": UNIT_SAMPLES,
        "summary": SUMMARY,
        "measure": measure(),
    }


# D. greyscale and deuteranopia (cvd_sim.py's maths on single colours)
DEUT = (
    (0.367322, 0.860646, -0.227968),
    (0.280085, 0.672501, 0.047413),
    (-0.011820, 0.042940, 0.968881),
)


def grey(h: str) -> str:
    r, g, b = rgb(h)
    y = r * 0.299 + g * 0.587 + b * 0.114
    return hexs((y, y, y))


def deut(h: str) -> str:
    c = rgb(h)
    out = tuple(sum(m * v for m, v in zip(row, c, strict=True)) for row in DEUT)
    return hexs((out[0], out[1], out[2]))


CVD_PAIRS = rows_of(
    """buy vs sell (the card chip specimens; glyph + word carry)|buy|sell
warning vs danger edge (one hue family; the glyph, the title and the word carry)|warn.strong|danger.strong
info badge vs the changed marker (outline + glyph vs the edit glyph + the word)|info.default|t2
primary fill vs the overlay (the Toggle on / off by knob position and aria-checked)|a.primary|overlay"""
)
E22_D03_CVD = {  # E22-D03 §8.3 dark: hexes and the hue separation normal / greyscale / deuteranopia
    "buy": ("#878787", "#9F905E"),
    "sell": ("#787878", "#81744B"),
    "sep": (1.59, 1.23, 1.46),
}


def cvd(problems: list[str]) -> dict[str, Any]:
    out: dict[str, Any] = {"pairs": []}
    for label, a, b in CVD_PAIRS:
        per_theme = {}
        for t in THEMES:
            ha, hb = col(t, a), col(t, b)
            per_theme[t] = {
                "a": ha,
                "b": hb,
                "a_grey": grey(ha),
                "a_deut": deut(ha),
                "b_grey": grey(hb),
                "b_deut": deut(hb),
                "sep": (ratio(ha, hb), ratio(grey(ha), grey(hb)), ratio(deut(ha), deut(hb))),
            }
        out["pairs"].append({"pair": label, "a": TOK[a], "b": TOK[b], "themes": per_theme})
    d = out["pairs"][0]["themes"]["dark"]
    got = (d["a_grey"], d["a_deut"], d["b_grey"], d["b_deut"])
    exp = E22_D03_CVD["buy"] + E22_D03_CVD["sell"]
    sep = tuple(round(v, 2) for v in d["sep"])
    ok = got == exp and sep == E22_D03_CVD["sep"]
    out["e22_d03_reproduced"] = ok
    if not ok:
        problems.append(f"E22-D03 §8.3 greyscale / deuteranopia not reproduced: {got} {sep}")
    return out


# E. the board plan and the spec's id tables
BOARD_RX = re.compile(r"^\| (0[1-9]|1[0-9]) +\| `")
S_RX = {"S58": re.compile(r"^\| S58-\d+ "), "S59": re.compile(r"^\| S59-\d+ ")}
EXPECT_STATES = {"S58": 8, "S59": 17}  # E25-D02 §9 (the frame counts, carried)
MAX_BOARDS = 10


def cells(ln: str) -> list[str]:
    return [c.strip() for c in ln.strip().strip("|").split("|")]


def section(spec: str, start: str, end: str) -> str:
    i = spec.find(start)
    j = spec.find(end, i + 1) if i >= 0 else -1
    return spec[i:j] if i >= 0 and j > i else ""


# §0's two modes: PENDING (the text PR and PR 2 before the draw) and drawn (PR 2 after it)
PENDING_HEAD = "## 0. The boards (Penpot) — PENDING"
DRAWN_HEAD = "## 0. The boards (Penpot) — drawn"
UUID_RX = re.compile(r"\b[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}\b")
PAGE_RX = re.compile(r"page id `([0-9a-f-]{36})`")
EXPORT_RX = re.compile(r"^\| `(docs/design/E25/img/E25-D04-\d\d-[a-z0-9-]+\.png)` +\|")
CVD_SUFFIXES = ("-greyscale", "-deuteranopia")
SWATCH_BOARD = "10"  # the swatch board: no greyscale / deuteranopia render (§0)
PNG_SIG = b"\x89PNG\r\n\x1a\n"
Files = dict[str, bytes]


def read_exports() -> Files:
    """Every committed E25-D04 PNG, by its repo path."""
    if not IMG.is_dir():
        return {}
    return {f"{IMG_REL}/{f.name}": f.read_bytes() for f in sorted(IMG.glob("E25-D04-*.png"))}


def png_size(data: bytes) -> tuple[int, int] | None:
    if data[:8] != PNG_SIG or data[12:16] != b"IHDR":
        return None
    w, h = struct.unpack(">II", data[16:24])
    return int(w), int(h)


def s0_of(spec: str) -> str:
    return section(spec, "\n## 0.", "\n## 1.")


def export_base(row: list[str]) -> str:
    return f"{IMG_REL}/E25-D04-{row[0]}-{row[1].strip('`')}"


def expected_exports(rows: list[list[str]]) -> dict[str, str]:
    out: dict[str, str] = {}
    for r in rows:
        out[export_base(r) + ".png"] = r[0]
        if r[0] != SWATCH_BOARD:
            out.update({export_base(r) + sfx + ".png": r[0] for sfx in CVD_SUFFIXES})
    return out


def drawn_gate(rows: list[list[str]], s0: str, files: Files, problems: list[str]) -> int:
    expected = expected_exports(rows)
    ids: list[str] = []
    for r in rows:
        main = export_base(r) + ".png"
        if len(r) < 6 or r[4] != f"`{main}`":
            problems.append(f"board {r[0]}: the Export cell is not `{main}`")
        m = re.fullmatch(r"`([0-9a-f-]{36})`", r[5] if len(r) > 5 else "")
        if not m or not UUID_RX.fullmatch(m.group(1)):
            problems.append(f"board {r[0]}: the Id cell is not a board uuid")
        else:
            ids.append(m.group(1))
    if len(set(ids)) != len(ids):
        problems.append("board plan: a board id repeats")
    page = PAGE_RX.search(s0)
    if not page or not UUID_RX.fullmatch(page.group(1)) or page.group(1) in ids:
        problems.append("board plan: §0 does not pin the page id (one uuid, not a board's)")
    table = {
        m.group(1): cells(ln) for ln in s0.splitlines() if (m := EXPORT_RX.match(ln)) is not None
    }
    lacks = sorted(set(expected) - set(table))
    extra = sorted(set(table) - set(expected))
    if lacks or extra:
        problems.append(f"exports table: lacks {lacks}, extra {extra}")
    for path, row in table.items():
        name = path.rsplit("/", 1)[1]
        data = files.get(path)
        size = png_size(data) if data is not None else None
        if data is None:
            problems.append(f"export {name}: no such file")
        elif size is None:
            problems.append(f"export {name}: not a PNG")
        elif len(row) < 3 or row[1] != f"{size[0]} × {size[1]}":
            problems.append(f"export {name}: the size cell is not the PNG's {size[0]} × {size[1]}")
        elif row[2] != f"`{hashlib.sha256(data).hexdigest()}`":
            problems.append(f"export {name}: the sha256 is not the file's")
    stray = sorted(set(files) - set(table))
    if stray:
        problems.append(f"exports: committed but not in §0's table: {stray}")
    return len(table)


def boards(spec: str, problems: list[str], files: Files) -> dict[str, Any]:
    rows = [cells(ln) for ln in spec.splitlines() if BOARD_RX.match(ln)]
    slugs = [r[1] for r in rows]
    themes = [r[3].lower() for r in rows]
    twins = sum(1 for t in themes if t.startswith("light"))
    s0 = s0_of(spec)
    mode = "drawn" if s0.startswith("\n" + DRAWN_HEAD) else "pending"
    out: dict[str, Any] = {"boards": len(rows), "light_twins": twins, "slugs": slugs, "mode": mode}
    if len(rows) > MAX_BOARDS:  # the plan itself is wrong: the per-row gates would only echo it
        problems.append(f"board plan: {len(rows)} boards, over {MAX_BOARDS}")
        return out
    if twins > len(rows) // 3:
        problems.append(f"board plan: {twins} light twins of {len(rows)}, over one third")
    if len(set(slugs)) != len(slugs):
        problems.append("board plan: a slug repeats")
    if f"{len(rows)} boards" not in spec:
        problems.append(f"board plan: the spec does not state {len(rows)} boards")
    if twins <= len(rows) // 3 and f"{twins} light twins" not in spec:
        problems.append(f"board plan: the spec does not state {twins} light twins")
    out["exports"] = 0
    if mode == "drawn":
        out["exports"] = drawn_gate(rows, s0, files, problems)
        return out
    if not s0.startswith("\n" + PENDING_HEAD):
        problems.append("board plan: §0's heading names neither PENDING nor drawn")
    if any(len(r) < 6 or r[4] != "—" or r[5] != "PENDING" for r in rows):
        problems.append("board plan: a board row is not PENDING while §0 is PENDING")
    if UUID_RX.search(s0):
        problems.append("board plan: a page id or uuid in a PENDING §0")
    if files:
        problems.append(f"board plan: {len(files)} E25-D04 export(s) committed while §0 is PENDING")
    return out


def counts(spec: str, problems: list[str]) -> dict[str, Any]:
    out: dict[str, Any] = {}
    for k, rx in S_RX.items():
        out[k] = sum(1 for ln in spec.splitlines() if rx.match(ln))
        if out[k] != EXPECT_STATES[k]:
            problems.append(f"{k} rows: {out[k]} (E25-D02 carries {EXPECT_STATES[k]})")
    for k, pat in (
        ("F", r"^\| F-\d+ "),
        ("AP", r"^\| AP-\d+ "),
        ("CF", r"^\| CF-\d+ "),
        ("T2", r"^\| T2-\d+ "),
        ("M", r"^\| M-\d+ "),
        ("A", r"^\| A-\d+ "),
        ("A14", r"^\| A14-\d+ "),
        ("CR", r"^\| CR-\d+ "),
        ("HO", r"^\| HO-\d+ "),
        ("C", r"^\| D04-C\d+ "),
        ("G", r"^\| D04-G\d+ "),
        ("H", r"^\| H-\d+ "),
        ("CP", r"^\| CP-\d+ "),
    ):
        out[k] = sum(1 for ln in spec.splitlines() if re.match(pat, ln))
    return out


# F. the spec's tables and strings
ESTIMATE_SENTENCE = "this is an estimate, not exchange-provided fact"
NO_L3 = (
    "Bybit's public feed is anonymous and aggregated, so iceberg, stop-run, absorption "
    "and exhaustion are inferences, not observations"
)
CONFIRM = {  # the three variants' fixed strings (BQ-02 RULED)
    "CF-1": (
        "Apply detector changes?",
        "Apply changes",
        "and will evaluate with the new thresholds on the next window:",
    ),
    "CF-2": (
        "Dependent rules could not be checked — treat every armed rule as affected.",
        "Armed rules (dependency unknown)",
        "Rules outside your account scope are not shown.",
    ),
    "CF-3": ("No armed rule uses this detector right now.",),
}
MUST = (  # E25-D02 strings the hi-fi carries verbatim, and the strings the rulings fix
    "Why estimated?",
    "Detector settings",
    "Methodology docs",
    "(copy: E25-T07)",
    "Methodology unavailable — try again.",
    "Retry",
    "Loading…",
    "Reset to default",
    "Cancel",
    "Apply",
    "Applying…",
    "Applied — takes effect within 2 s",
    "Discard unsaved changes?",
    "Defaults restored",
    "Sensitivity high may produce many false positives",
    "Armed rules depend on this detector — a change is audited and takes effect on the next evaluation window.",
    "Break-even at +1R · armed",
    "Sensitivity preset — not in the contract",
    "Symbol scope — not in the contract",
    "Backtest preview — not in the contract",
    "Alert routing — not in the contract",
    "Minimum confidence — not in the contract",
    "Not available on this server — the stop-run detector is behind a feature flag",
    "Off — turn on in Detector settings",
    "Read-only while viewing as {user}.",
    "Read-only — your role can't change settings.",
    "Your role can't change settings.",
    "Only the owner can start recording.",
    "Only the owner can change detector settings.",
    "Read-only — only the owner can change detector settings.",
    "Applies to every account on this server.",
    "Changes are recorded in the audit log.",
    "Start recording ETHUSDT",
    "Recording started — the detector turns on once enough history exists.",
    "Thresholds in force unavailable — showing defaults only.",
    "No tunable thresholds in the contract.",
    "Your values were restored.",
    "Try again",
    "sample — E25-T07 owns the text",
    "Preview unavailable",
    "Every armed rule on this server is listed.",
    "The server did not answer — showing the values now in force.",
    "Detector settings applied",
    "Detector settings not applied — reopen to retry",
)
FETCH_POINT = (
    "`GET /rules?mode=armed` is (re)issued on the Apply press and the variant is decided from "
    "that response alone"
)
CF2_UNTIL = "200 with ≥ 1 armed → CF-2 until D02-G6 adds a detector filter"  # M-1: no filter yet
UNKNOWN_LEG = "before any value is shown"  # AP-5: the re-read precedes any value (M-4)
FORBIDDEN_LEG = "Not sent — your access changed. Only the owner can change detector settings."
ADMIN_LINK = "only for a session holding `admin:read` and `audit:read`"  # the audit link (M-2)
NEGATED = re.compile(r"\b(no|never|not|without|nothing)\b", re.IGNORECASE)
# the patterns are assembled so that this file does not itself carry the words it forbids
FORBIDDEN = {
    "local path": re.compile("/ho" + r"me/\w+|/Us" + r"ers/\w+|C:\\\\"),
    "worker name": re.compile(r"\b[a-z]{2,5}-worker-\d+\b|wt-no" + r"tes|\bAgent [A-C]\b"),
    "host or url": re.compile(r"https?://|penpot\.[a-z]|\.candleviewer\.com"),
    "colour emoji": re.compile("[\U0001f300-\U0001faff\u2600-\u26ff]"),
    "page id or uuid": re.compile(
        r"\b[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}\b"
    ),
}
RULE_RX = re.compile(r"\bC-\d+\.\d+\b")
T2_WRITE_COLS = {
    "Manager": 3,
    "Viewer": 4,
    "view-as": 5,
}  # id | control | Owner | Manager | Viewer | view-as | validity | applying
T2_EXITS = ("Cancel", "Close", "Esc", "Detector settings", "Methodology docs", "Retry")
T2_OMITTED = (
    "the audit-log link",
)  # a bare link to /admin/** is dropped, never locked (rule 5 step 1)
POINTER = "**Hi-fi (E25-D04):**"


A1_FIELD = "- **Tokens**: "


def a1_applied(spec: str, problems: list[str]) -> bool:
    """§12's A-1 is applied verbatim: the Tokens line after CMP-069's heading in `15` is its text."""
    row = next((ln for ln in spec.splitlines() if ln.startswith("| A-1 ")), None)
    prop = cells(row)[4] if row and len(cells(row)) > 4 else ""
    want = prop[1:-1] if len(prop) > 1 and prop[0] == prop[-1] == '"' else ""
    cat = CATALOGUE.read_text(encoding="utf-8") if CATALOGUE.exists() else ""
    blk = section(cat, "### CMP-069 ", "\n### ")
    got = next((ln[len(A1_FIELD) :] for ln in blk.splitlines() if ln.startswith(A1_FIELD)), None)
    if not want or got != want:
        problems.append("15 CMP-069 Tokens is not §12's A-1 proposed text verbatim")
        return False
    return True


def window(text: str, i: int, j: int, span: int = 60) -> str:
    return text[max(0, i - span) : j + span]


def table_gates(spec: str, fl: dict[str, Any], problems: list[str]) -> dict[str, Any]:
    lines = spec.splitlines()
    out: dict[str, Any] = {}
    # C. every bound, default, step and message of the field table, verbatim in the spec's F-rows
    f_rows = {cells(ln)[0]: cells(ln) for ln in lines if re.match(r"^\| F-\d+ ", ln)}
    for r in fl["rows"]:
        row = f_rows.get(r["id"])
        if row is None:
            problems.append(f"field table: {r['id']} ({r['key']}) missing")
            continue
        want = (r["key"], r["range"], r["default_txt"], r["step"])
        plain = [c.strip("`") for c in row]
        lost = [w for w in want if w not in plain]
        if lost:
            problems.append(f"field table {r['id']} {r['key']} lacks {lost}")
        if r["message"] != "—" and r["message"] not in spec:
            problems.append(f"validation message missing: {r['message']!r}")
    for s in SUMMARY:
        if s not in spec:
            problems.append(f"error summary missing: {s!r}")
    # the apply machine: five AP rows (failed in two legs); "applied" only on the 200; the refused
    # leg restores; the unknown leg re-reads before any value is shown; the forbidden leg (D04-G3)
    ap = {cells(ln)[0]: cells(ln) for ln in lines if re.match(r"^\| AP-\d+ ", ln)}
    out["apply_rows"] = len(ap)
    if len(ap) != 5:
        problems.append(f"apply machine: {len(ap)} rows, the machine has five")
    applied = ap.get("AP-3", [])
    if applied and ("200" not in applied[2] or "before" in applied[2].lower()):
        problems.append("apply machine: applied is not entered on the 200 alone")
    failed = ap.get("AP-4", [])
    if failed and "restored" not in " ".join(failed).lower():
        problems.append("apply machine: the failed state does not restore the confirmed values")
    if failed and ("`forbidden`" not in " ".join(failed) or FORBIDDEN_LEG not in " ".join(failed)):
        problems.append("apply machine: the refused leg lacks the 403 `forbidden` leg (D04-G3)")
    unknown = ap.get("AP-5", [])
    if unknown and (UNKNOWN_LEG not in unknown[3] or "`GET /detectors/config`" not in unknown[3]):
        problems.append("apply machine: the unknown-outcome leg shows a value before the re-read")
    # the three confirmation variants carry their fixed strings; the variant is decided on the press
    for cf, strings in CONFIRM.items():
        cf_row = next((ln for ln in lines if ln.startswith(f"| {cf} ")), None)
        if cf_row is None:
            problems.append(f"confirmation variant {cf} missing")
            continue
        lost = [s for s in strings if s not in cf_row]
        if lost:
            problems.append(f"confirmation {cf} lacks {lost}")
    if FETCH_POINT not in spec:
        problems.append("confirmation: the fetch point (re-issued on the Apply press) is lost")
    # M-1: with no detector filter on listRules a 200 with armed rules is CF-2, in §4.4 and HO-4
    if spec.count(CF2_UNTIL) < 2 or "→ CF-1;" in spec:
        problems.append("confirmation: a 200 with armed rules must go to CF-2 until D02-G6")
    # m-1: the list is paged; a failed page is CF-2
    if spec.count("failed page → CF-2") < 2:
        problems.append("confirmation: the paged list's failed page is not sent to CF-2")
    # the audit link: offered only with admin:read + audit:read in the §4.1 anatomy, dropped
    # otherwise (rule 5 step 1)
    if ADMIN_LINK not in section(spec, "### 4.1 ", "\n### 4.2"):
        problems.append("the audit-log link is not gated on `admin:read` and `audit:read`")
    # the T2 matrix: every write locked for a Manager, a Viewer and view-as; exits never locked;
    # the admin link omitted, never locked
    t2 = [cells(ln) for ln in lines if re.match(r"^\| T2-\d+ ", ln)]
    out["t2_rows"] = len(t2)
    for r in t2:
        name = r[1]
        is_exit = any(name.startswith(e) for e in T2_EXITS)
        is_omitted = any(name.startswith(o) for o in T2_OMITTED)
        for role, i in T2_WRITE_COLS.items():
            locked = r[i].startswith("T2")
            if is_omitted:
                if not r[i].startswith("omitted"):
                    problems.append(f"T2 matrix: the admin link is not omitted for {role}")
                continue
            if is_exit and locked:
                problems.append(f"T2 matrix: exit {name} locked for {role}")
            if not is_exit and not locked:
                problems.append(f"T2 matrix: write {name} not locked for {role}")
    # motion: every row has both cells; the timed rows are named; the flash row reads 0
    m_rows = [cells(ln) for ln in lines if re.match(r"^\| M-\d+ ", ln)]
    timed = [r[0] for r in m_rows if "motion.duration." in r[2]]
    out["motion_rows"], out["timed_rows"] = len(m_rows), timed
    if any(not r[2] or not r[3] for r in m_rows):
        problems.append("motion table: a row lacks its motion-safe or motion-reduce cell")
    if len(timed) != 5:
        problems.append(f"motion table: {len(timed)} timed transitions, the spec names five")
    flash = [r for r in m_rows if "flash" in r[1].lower()]
    if not flash or not all(r[2].startswith("0 flashes") for r in flash):
        problems.append("motion table: the flash row does not read 0 flashes")
    # the fixed sentences and the strings
    if spec.count(ESTIMATE_SENTENCE) < 3:
        problems.append("the estimate sentence appears fewer than three times")
    if NO_L3 not in spec:
        problems.append("the `22` no-L3 sentence is not quoted verbatim")
    problems += [f"string missing: {s!r}" for s in MUST if s not in spec]
    out["must"] = len(MUST)
    arm = [m for m in re.finditer("X-Arm-Token", spec)]
    if not arm or any(not NEGATED.search(window(spec, m.start(), m.end())) for m in arm):
        problems.append("a settings write is drawn with an `X-Arm-Token`, or the negation is lost")
    # the `14` pointer lines, one after each Wireframes line of SCR-058 and SCR-059
    screens = SCREENS.read_text(encoding="utf-8") if SCREENS.exists() else ""
    for scr in ("SCR-058", "SCR-059"):
        blk = section(screens, f"### {scr} ", "\n### ")
        wl = [i for i, ln in enumerate(blk.splitlines()) if "**Wireframes (E25-D02):**" in ln]
        hl = [i for i, ln in enumerate(blk.splitlines()) if POINTER in ln]
        if not (wl and hl and hl[0] == wl[0] + 1):
            problems.append(
                f"14 {scr}: no `Hi-fi (E25-D04)` pointer line after the Wireframes line"
            )
    out["pointer_lines"] = screens.count(POINTER)
    # A-1 as applied: the CMP-069 Tokens line in `15` equals §12's A-1 proposed text verbatim
    out["a1_applied"] = a1_applied(spec, problems)
    # hygiene and rule ids
    outside_s0 = spec.replace(s0_of(spec), "")  # §0 alone may pin the page id and board ids
    for name, rx in FORBIDDEN.items():
        if rx.search(outside_s0 if name == "page id or uuid" else spec):
            problems.append(f"hygiene: {name}")
    constitution = CONSTITUTION.read_text(encoding="utf-8")
    ids = sorted(set(RULE_RX.findall(spec)))
    absent = [i for i in ids if not re.search(rf"\b{re.escape(i)}\b", constitution)]
    problems += [f"{i} not in CONSTITUTION.md" for i in absent]
    out["rule_ids"] = len(ids)
    return out


# G. drift: every number the tool prints that the spec must carry, and the counts it types in words
WORDS = {
    5: "five",
    6: "six",
    7: "seven",
    8: "eight",
    9: "nine",
    10: "ten",
    11: "eleven",
    12: "twelve",
    13: "thirteen",
    14: "fourteen",
    15: "fifteen",
    16: "sixteen",
    17: "seventeen",
    18: "eighteen",
    19: "nineteen",
    20: "twenty",
}
CR1_CLAIMS = {"PROPOSED (CR-1)", "PROPOSED (D05 CR-5)"}  # the rows CR-1 lists for E25-S01


def drift(
    spec: str, mx: dict[str, Any], fl: dict[str, Any], cv: dict[str, Any], ct: dict[str, Any]
) -> list[str]:
    need: list[str] = [r["text"] for r in mx["rows"]]
    need += [f"{mx['pairs']} pairs × 3 themes", f"{mx['gated']} gated", f"FAIL {mx['fail']}"]
    need.append(f"{mx['repro_ok']} of {mx['repro_n']} reproductions")
    need += [f"`{s}`" for _, s in fl["unit_samples"]]
    need.append(f"≈ {fl['measure']['chars']} characters")
    need.append(f"{fl['measure']['inner_px']} px inner width")
    for p in cv["pairs"]:
        sep = p["themes"]["dark"]["sep"]
        need.append(f"{sep[0]:.2f} / {sep[1]:.2f} / {sep[2]:.2f}")
    cr1 = sum(1 for r in mx["rows"] if r["pairs_mjs"] in CR1_CLAIMS)
    need += [
        f"{WORDS[ct['C']]} C-rows",
        f"{WORDS[ct['G']]} G-rows",
        f"{WORDS[ct['HO']]} hand-offs",
        f"{WORDS[ct['CP']]} copy rows",
        f"{WORDS[cr1]} `pairs.mjs` rows",
        f"AP-1 … AP-{ct['AP']}, CF-1 … CF-{ct['CF']}, T2-1 … T2-{ct['T2']}",
    ]
    return [n for n in need if n not in spec]


# H. the pairs.mjs registration claims: read-only; a claim the registry disagrees with is a FAIL
PAIR_RX = re.compile(r'fg:\s*"([^"]+)"\s*,\s*bg:\s*"([^"]+)"', re.DOTALL)


def registry() -> set[tuple[str, str]]:
    text = PAIRS_MJS.read_text(encoding="utf-8") if PAIRS_MJS.exists() else ""
    text = re.sub(r"//[^\n]*", "", text)
    return set(PAIR_RX.findall(text))


def registration(spec: str, problems: list[str]) -> dict[str, Any]:
    reg = registry()
    checked = 0
    for ln in spec.splitlines():
        if not re.match(r"^\| P\d+ ", ln):
            continue
        c = cells(ln)
        if len(c) < 8 or c[7] == "—":
            continue
        pid, fg, bg, claim = c[0], c[2].strip("`").split(" @")[0], c[3].strip("`"), c[7]
        checked += 1
        listed = (fg, bg) in reg
        if listed != (claim == "registered"):
            problems.append(
                f"registration claim wrong {pid}: {fg} on {bg} is "
                f"{'' if listed else 'not '}in pairs.mjs, the spec says {claim!r}"
            )
    return {"registry_pairs": len(reg), "claims_checked": checked}


def evaluate(spec: str, files: Files) -> tuple[list[str], dict[str, Any]]:
    problems: list[str] = []
    out: dict[str, Any] = {}
    out["tokens"] = tokens(spec)
    problems += [f"token does not resolve: {n}" for n in out["tokens"]["missing"]]
    out["matrix"] = matrix(problems)
    out["fields"] = fields(problems)
    out["cvd"] = cvd(problems)
    out["boards"] = boards(spec, problems, files)
    out["counts"] = counts(spec, problems)
    out["gates"] = table_gates(spec, out["fields"], problems)
    out["registration"] = registration(spec, problems)
    out["drift"] = drift(spec, out["matrix"], out["fields"], out["cvd"], out["counts"])
    problems += [f"drift: the spec does not carry {n!r}" for n in out["drift"]]
    out["problems"] = problems
    return problems, out


# ------------------------------------------------------------------ self-test -------------------
MUTATIONS: tuple[tuple[str, str, str], ...] = (
    ("a contrast value drifts", "13.27 / 14.37 / 15.02", "13.28 / 14.37 / 15.02"),
    ("a token name is invented", "`font.lineheight.relaxed`", "`font.lineheight.relaxing`"),
    ("a published bound changes", "| 2–50 ", "| 2–60 "),
    (
        "a validation message changes",
        "Enter a reload count between 2 and 50.",
        "Enter a reload count between 2 and 51.",
    ),
    ("the summary loses its plural", "Fix 2 fields to apply.", "Fix 2 field to apply."),
    (
        "an eleventh board",
        "| 10  | `contrast-cvd-motion-ds-requests`",
        "| 11  | `extra` | x | dark | — | PENDING |\n| 10  | `contrast-cvd-motion-ds-requests`",
    ),
    ("a state row is lost", "| S59-17 |", "| S59-17x |"),
    ("applied before the 200", "the 200 alone", "the press alone"),
    (
        "a confirmation string changes",
        "Rules outside your account scope are not shown.",
        "Rules outside your account scope are hidden.",
    ),
    (
        "a Manager write unlocked",
        "T2 — `rbac.owner_only`, Apply locked",
        "T1 — `rbac.owner_only`, Apply locked",
    ),
    (
        "an exit locked for a Viewer",
        "T1 — never locked for a Viewer",
        "T2 — never locked for a Viewer",
    ),
    (
        "a sixth timed transition",
        "content at 0 ms, in one frame",
        "`motion.duration.fast` fade, in one frame",
    ),
    ("a flash appears", "| 0 flashes (", "| 1 flash ("),
    ("an arm token on the settings write", "no `X-Arm-Token`", "an `X-Arm-Token`"),
    ("a local path leaks", "## 20. Summary", "## 20. Summary (/ho" + "me/someone/notes)"),
    ("an unknown rule id", "C-2.9", "C-2.999"),
    ("a unit sample drifts", "`60,000 ms`", "`60000 ms`"),
    (
        "the fetch point is lost",
        "the variant is decided from that response alone",
        "the variant is decided from the open-time list",
    ),
    (
        "an unknown outcome shown before the re-read",
        "before any value is shown and never re-sends (E09-D09 §4.2; D04-G7)",
        "after the attempted values are shown and never re-sends (E09-D09 §4.2; D04-G7)",
    ),
    (
        "the 403 forbidden leg is lost",
        'Not sent — your access changed. Only the owner can change detector settings."** (E09-D09 §4.2',
        'Not sent — only the owner can change detector settings."** (E09-D09 §4.2',
    ),
    (
        "the audit link offered without admin:read",
        "**only for a session holding `admin:read` and `audit:read`**",
        "**only for a session holding `audit:read`**",
    ),
    (
        "the admin link locked, not dropped",
        "| omitted, not locked — the plain sentence (`14` rule 5 step 1)",
        "| T2 — the plain sentence (`14` rule 5 step 1)",
    ),
    (
        "a 200 with armed rules goes to CF-1 before D02-G6",
        "the variant is decided from that response alone: every page of the paged list is read",
        "the variant is decided from that response alone: 200 with ≥ 1 armed → CF-1; every page of the paged list is read",
    ),
    (
        "a failed page is not sent to CF-2",
        "timeout or failed page → CF-2 — ",
        "timeout → CF-2 — ",
    ),
    ("a registration claim is wrong", "unregistered (E05)", "registered"),
    (
        "the applied A-1 drifts from §12",
        "the dialog it links to keeps `font.lineheight.normal`.",
        "the dialog it opens keeps `font.lineheight.normal`.",
    ),
)


View = tuple[str, Files]
Mutation = tuple[str, bool, Callable[[View], View | None]]  # (name, on the drawn view, apply)


def literal(old: str, new: str) -> Callable[[View], View | None]:
    def apply(view: View) -> View | None:
        spec, files = view
        return None if old not in spec else (spec.replace(old, new, 1), files)

    return apply


def row_pending(view: View) -> View | None:
    spec, n = re.subn(
        r"^(\| 02 +\|.*\| )`[0-9a-f-]{36}`( +\|)$", r"\1PENDING\2", view[0], flags=re.MULTILINE
    )
    return (spec, view[1]) if n == 1 else None


def first_export(spec: str) -> re.Match[str] | None:
    rx = r"^(\| `[^`]+\.png` +\| )(\d+) × (\d+)( +\| `)([0-9a-f]{64})(` +\|)$"
    return re.search(rx, spec, flags=re.MULTILINE)


def sha_drifts(view: View) -> View | None:
    m = first_export(view[0])
    if not m:
        return None
    sha = m.group(5)[:-1] + ("0" if m.group(5)[-1] != "0" else "1")
    return view[0][: m.start(5)] + sha + view[0][m.end(5) :], view[1]


def size_drifts(view: View) -> View | None:
    m = first_export(view[0])
    if not m:
        return None
    return view[0][: m.start(3)] + str(int(m.group(3)) + 1) + view[0][m.end(3) :], view[1]


def render_missing(view: View) -> View | None:
    gone = next((k for k in sorted(view[1]) if k.endswith(CVD_SUFFIXES[1] + ".png")), None)
    return None if gone is None else (view[0], {k: v for k, v in view[1].items() if k != gone})


def uuid_outside(view: View) -> View | None:
    old = "## 20. Summary"
    tag = f" (`{synth_uuid(999)}`)"
    return None if old not in view[0] else (view[0].replace(old, old + tag, 1), view[1])


def plan() -> list[Mutation]:
    return [
        *[(m[0], False, literal(m[1], m[2])) for m in MUTATIONS],
        ("a drawn board row is left PENDING (the drawn view)", True, row_pending),
        ("an export's sha256 drifts (the drawn view)", True, sha_drifts),
        ("an export's size cell drifts (the drawn view)", True, size_drifts),
        ("a greyscale / deuteranopia render is missing (the drawn view)", True, render_missing),
        ("a uuid outside §0 (the drawn view)", True, uuid_outside),
    ]


def synth_uuid(i: int) -> str:
    return f"{i:08x}-0000-4000-8000-{i:012x}"


def fake_png(w: int, h: int) -> bytes:
    ihdr = b"IHDR" + struct.pack(">IIBBBBB", w, h, 8, 2, 0, 0, 0)
    return PNG_SIG + struct.pack(">I", 13) + ihdr + struct.pack(">I", zlib.crc32(ihdr))


def drawn_view(spec: str, files: Files) -> tuple[View, bool]:
    """The drawn state: the committed one, or (§0 PENDING) one synthesised in memory."""
    s0 = s0_of(spec)
    if s0.startswith("\n" + DRAWN_HEAD):
        return (spec, files), False
    rows = [cells(ln) for ln in s0.splitlines() if BOARD_RX.match(ln)]
    fake: Files = {}
    table = ["", "| Export | Size | sha256 |", "| --- | --- | --- |"]
    for k, path in enumerate(expected_exports(rows)):
        fake[path] = fake_png(2032, 1000 + k)
        sha = hashlib.sha256(fake[path]).hexdigest()
        table.append(f"| `{path}` | 2032 × {1000 + k} | `{sha}` |")
    lines = s0.split("\n")
    last = 0
    for k, ln in enumerate(lines):
        if BOARD_RX.match(ln):
            r = cells(ln)
            lines[k] = f"| {r[0]} | {r[1]} | {r[2]} | {r[3]} | `{export_base(r)}.png` | "
            lines[k] += f"`{synth_uuid(int(r[0]))}` |"
            last = k
    lines[last + 1 : last + 1] = table
    lines[1] = DRAWN_HEAD + f" (PR 2; page id `{synth_uuid(100)}`)"
    return (spec.replace(s0, "\n".join(lines), 1), fake), True


def read(path: Path) -> str:
    return path.read_text(encoding="utf-8")


def self_test(spec_path: Path) -> int:
    spec = read(spec_path)
    before = spec_path.read_bytes()
    files = read_exports()
    base, _ = evaluate(spec, files)
    ok = not base
    print(f"clean spec: rc {1 if base else 0} ({len(base)} problem(s))")
    for p in base:
        print(f"  {p}")
    dview, synth = drawn_view(spec, files)
    dbase, _ = evaluate(*dview)
    ok = ok and not dbase
    kind = "synthesised in memory (§0 PENDING)" if synth else "the committed state"
    print(f"drawn view, {kind}: rc {1 if dbase else 0} ({len(dbase)} problem(s))")
    for p in dbase:
        print(f"  {p}")
    seen: dict[str, str] = {}
    muts = plan()
    for no, (name, on_drawn, apply) in enumerate(muts, start=1):
        start, ref = (dview, dbase) if on_drawn else ((spec, files), base)
        view = apply(start)
        if view is None:
            ok = False
            print(f"mutation {no:02d} {name}: DOES NOT APPLY (the text to mutate is gone)")
            continue
        got, _ = evaluate(*view)
        fresh = [p for p in got if p not in ref]
        rc = 1 if got else 0
        dup = [p for p in fresh if p in seen]
        caught = rc == 1 and len(fresh) == 1 and not dup
        ok = ok and caught
        flag = "" if caught else (" - DUPLICATE FAIL" if dup else " - NOT CAUGHT EXACTLY ONCE")
        print(f"mutation {no:02d} {name}: rc {rc}, {len(fresh)} new FAIL{flag}")
        for p in fresh:
            print(f"  {p}")
            seen.setdefault(p, name)
    restored, _ = evaluate(spec, read_exports())
    same = spec_path.read_bytes() == before
    ok = ok and not restored and same
    print(
        f"restore: rc {1 if restored else 0}; spec file byte-identical: {same}; "
        f"--self-test: {'ok' if ok else 'FAIL'} - {len(muts)} mutations in memory, "
        f"{len(seen)} distinct FAILs"
    )
    return 0 if ok else 1


def main(argv: list[str] | None = None) -> int:
    if isinstance(sys.stdout, io.TextIOWrapper):
        sys.stdout.reconfigure(encoding="utf-8")
    argv = sys.argv[1:] if argv is None else argv
    spec_path = SPEC
    for flag in ("--check", "--self-test"):
        if flag in argv:
            i = argv.index(flag)
            if i + 1 < len(argv) and not argv[i + 1].startswith("--"):
                spec_path = Path(argv[i + 1])
    if "--self-test" in argv:
        return self_test(spec_path)
    spec = read(spec_path) if spec_path.exists() else ""
    problems, out = evaluate(spec, read_exports())
    if "--json" in argv:
        print(json.dumps(out, ensure_ascii=False, indent=1, default=str))
    else:
        mx = out["matrix"]
        print(f"A. tokens named {out['tokens']['named']}, missing {out['tokens']['missing']}")
        print(
            f"B. matrix: {mx['pairs']} pairs × 3 themes, {mx['gated']} gated, FAIL {mx['fail']}, "
            f"{mx['repro_ok']} of {mx['repro_n']} reproductions"
        )
        for r in mx["rows"]:
            print(
                f"   {r['id']:<4} {r['role']:<17} {r['text']:<24} {r['verdict']:<24} {r['element']}"
            )
        print(f"C. fields ({out['fields']['yaml_keys']} keys read from 22):")
        for r in out["fields"]["rows"]:
            print(
                f"   {r['id']:<5} {r['fieldset']:<10} {r['key']:<22} {r['range']:<24} "
                f"{r['default_txt']:<6} {r['step']:<14} {r['message']}"
            )
        for k, s in out["fields"]["unit_samples"]:
            print(f"   {k:<18} {s}")
        ms = out["fields"]["measure"]
        print(f"   measure: {ms['inner_px']} px inner width, ≈ {ms['chars']} characters")
        print("D. CVD (dark):")
        for p in out["cvd"]["pairs"]:
            d = p["themes"]["dark"]
            sep = d["sep"]
            print(
                f"   {p['pair']}: {d['a']} -> {d['a_grey']} / {d['a_deut']}; {d['b']} -> "
                f"{d['b_grey']} / {d['b_deut']}; separation {sep[0]:.2f} / {sep[1]:.2f} / {sep[2]:.2f}"
            )
        bd = out["boards"]
        print(
            f"E. boards {bd['boards']}, light twins {bd['light_twins']}, §0 {bd['mode']}, "
            f"exports {bd.get('exports', 0)}"
        )
        print(f"F. counts {out['counts']}; gates {out['gates']}")
        print(f"G. drift {len(out['drift'])}")
        print(f"H. registration {out['registration']}")
        for p in problems:
            print(f"FAIL {p}")
        print(f"rc {1 if problems else 0}")
    if "--check" in argv or "--json" in argv:
        return 1 if problems else 0
    own = (
        "contrast FAIL",
        "reproduction lost",
        "bound drift",
        "default drift",
        "E22-D03",
        "registration claim wrong",
    )
    return 1 if [p for p in problems if p.startswith(own)] else 0


if __name__ == "__main__":
    raise SystemExit(main())
