"""E13-D04 indicator design-system and motion audit: the palette reproduced through the E13-D03
tool, the band-fill alpha, the CVD and greyscale tables, the motion register with its kinematics,
flash and twin coverage, the closed style vocabulary, the copy-deck string gates, the structure and
the hygiene.

Standalone, offline, stdlib only:
    python3 -I docs/design/_tools/e13_d04_palette_motion_audit.py [--json] [--check]
        [--spec docs/design/E13/E13-D04.md] [--handoff docs/design/E13/E13-D04-handoff.md]
        [--draft <pr-draft.md>]
Nothing is re-implemented (the LANE-47 rider: E13-D04 regenerates E13-D03's numbers): the slots, the
ratios, the CIE76 distances, the dichromacy projections, the L* steps, the alpha and the draw-call
arithmetic come from `docs/design/_tools/e13_d03_palette_audit.py`, imported and called, so every
number here is the same object that tool printed; the easing kinematics (`ease`, the first-frame
fraction) come from `docs/design/_tools/e11_d06_motion_audit.py` the same way. The E13-D03 tool's
own `--json` is run in-process as the reference and every reproduced number is compared with it to
0.01 (`--check`: drift is any such difference, or any number the E13-D04 spec quotes that differs
from the computed one). The motion rows are a data literal below; their frame counts, first-frame
fractions, the old draw's alpha curve, the draw-call transient and the sub-pane ratio arithmetic are
computed. Exit 1 on a gated FAIL or a failed string gate; `--check` also exits 1 on drift; `--json`
prints only the scalars and counts the board check script consumes. No network, no write outside a
temporary.
"""

from __future__ import annotations

import importlib.util
import io
import json
import re
import sys
from contextlib import redirect_stdout
from pathlib import Path
from types import ModuleType
from typing import Any

ROOT = Path(__file__).resolve().parents[3]
TOOLS = ROOT / "docs" / "design" / "_tools"
TOKENS = ROOT / "packages" / "ui" / "tokens"
DESIGN = ROOT / "docs" / "design"
SPEC = DESIGN / "E13" / "E13-D04.md"
HANDOFF = DESIGN / "E13" / "E13-D04-handoff.md"
D02_SPEC = DESIGN / "E13" / "E13-D02.md"
D03_SPEC = DESIGN / "E13" / "E13-D03.md"
PLAN14 = ROOT / "docs" / "plan" / "14-screens-catalogue.md"


def _load(path: Path, name: str) -> ModuleType:
    spec = importlib.util.spec_from_file_location(name, path)
    if spec is None or spec.loader is None:
        raise ImportError(f"cannot load {path}")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def read(path: Path) -> str:
    return path.read_text(encoding="utf-8")


def section(text: str, start: str, end: str) -> str:
    i = text.find(start)
    if i < 0:
        return ""
    j = text.find(end, i + len(start))
    return text[i:] if j < 0 else text[i:j]


def rows_of(table_text: str) -> list[list[str]]:
    """The body rows of the first Markdown table in `table_text`, cell by cell (pipes inside
    backticks or escaped as `\\|` are not separators)."""
    out: list[list[str]] = []
    seen_header = False
    for line in table_text.splitlines():
        if not line.startswith("|"):
            if out:
                break
            continue
        if re.fullmatch(r"\|(?:\s*:?-+:?\s*\|)+", line.strip()):
            seen_header = True
            continue
        cells = [c.strip() for c in re.split(r"(?<!\\)\|(?=(?:[^`]*`[^`]*`)*[^`]*$)", line)[1:-1]]
        if seen_header:
            out.append(cells)
    return out


# The two upstream tools, imported (never re-implemented); their module-level code resolves the
# three themes from packages/ui/tokens exactly as verify_tokens.py does.
d03 = _load(TOOLS / "e13_d03_palette_audit.py", "e13_d03_palette_audit")
d06 = _load(TOOLS / "e11_d06_motion_audit.py", "e11_d06_motion_audit")

THEMES: tuple[str, ...] = tuple(d03.THEMES)
CVDS: tuple[str, ...] = tuple(d03.CVDS)
T: dict[str, dict[str, object]] = d03.T
FPS = (30, 60, 144)
OUT: list[str] = []
FAILS: list[str] = []
DRIFT: list[str] = []


def p(line: str) -> None:
    OUT.append(line)


def row(*cells: object) -> None:
    OUT.append("| " + " | ".join(str(c) for c in cells) + " |")


def fmt(x: float) -> str:
    return f"{x:.2f}"


def token_value(theme: str, name: str) -> object:
    return T[theme].get(name)


def duration_ms(name: str) -> int:
    v = token_value("dark", f"motion.duration.{name}")
    if not isinstance(v, str) or not v.endswith("ms"):
        raise TypeError(f"motion.duration.{name} is not a duration token: {v!r}")
    return int(v[:-2])


# The seven motion tokens, read from the files (never typed); the easing curve the kinematics use is
# checked equal to the token's control points.
DURATIONS: dict[str, int] = {k: duration_ms(k) for k in ("instant", "fast", "normal", "slow")}
EASINGS: dict[str, list[float]] = {}
for _k in ("standard", "decelerate", "accelerate"):
    _v = token_value("dark", f"motion.easing.{_k}")
    if not isinstance(_v, list):
        raise TypeError(f"motion.easing.{_k} is not a cubicBezier token: {_v!r}")
    EASINGS[_k] = [float(x) for x in _v]
    if [float(x) for x in d06.EASING[_k]] != EASINGS[_k]:
        FAILS.append(f"motion.easing.{_k} differs between the tokens and e11_d06_motion_audit.py")

# Names the spec binds that do not exist yet: the published set (CR rows), E13-D02 A-7's boundary
# alias (cited), and two catalogue drifts the spec records as C-rows (printed as absent, never
# failing).
CR_NAMES = frozenset(
    [f"color.indicator.palette.{i}" for i in range(1, 9)]
    + ["opacity.indicator.fill", "size.stroke.thin", "size.stroke.regular", "size.stroke.bold"]
)
CITED_ABSENT = frozenset(["color.border.control"])
DRIFT_NAMES = frozenset(["motion.slide", "font.mono"])
TOKEN_RE = re.compile(
    r"`((?:color|opacity|size|radius|font|type|elevation|motion|space|border)"
    r"\.[a-z0-9][a-z0-9.\-]*)`"
)
LOCAL_PATH_RE = re.compile(r"/(?:home|Users)/[^/\s]+/")
PENPOT_HOST_RE = re.compile(r"penpot\.[a-z0-9-]+\.[a-z]{2,}", re.IGNORECASE)
# Emoji and pictographs are forbidden (U+1F300-1FAFF, U+2600-27BF); the dingbat check mark U+2713 is
# a UI glyph E13-D02 §12 quotes verbatim (the word Disabled with the check glyph) and is excluded.
EMOJI_RE = re.compile(
    "["
    + chr(0x1F300)
    + "-"
    + chr(0x1FAFF)
    + chr(0x2600)
    + "-"
    + chr(0x2712)
    + chr(0x2714)
    + "-"
    + chr(0x27BF)
    + "]"
)
CLOSING_RE = re.compile(r"\b(?:close[sd]?|fix(?:e[sd])?|resolve[sd]?)\s+#\d+", re.IGNORECASE)
VOCAB_VALUE_RE = re.compile(
    r"^(color\.indicator\.palette\.[1-8]|dash\.[a-z0-9-]+|size\.stroke\.(thin|regular|bold)"
    r"|opacity\.indicator\.fill|glyph\.(diamond|disc|square)|bar\.(full|narrow|outline))$"
)
VOCAB_COUNTS = {"color": 8, "dash": 3, "width": 3, "fill_opacity": 1, "marker": 6}
# The motion rows (spec section 6): id, element, animated property (opacity / transform / clip /
# none, joined by +), duration token, easing token, the reduce twin's kind, the static carrier the
# twin keeps, loops?, maximum luminance changes per second, extra draws while active, carries
# information? M6's one luminance change per second holds by rule (spec section 6 M6): a commit
# within 1 s of the previous M6 start is a cut, so the fade never repeats inside a second.
M_ROWS: tuple[tuple[str, str, str, str, str, str, str, bool, int, int, bool], ...] = (
    (
        "M1",
        "SCR-034 open / close",
        "transform+opacity",
        "normal",
        "standard",
        "instant",
        "the dialog itself; focus on the search field, returned to the invoker (E13-D02 §11.2)",
        False,
        1,
        0,
        False,
    ),
    (
        "M2",
        "SCR-035 open / close",
        "transform+opacity",
        "normal",
        "standard",
        "instant",
        "the dialog itself; focus on the first field, returned to the invoker (E13-D02 §11.2)",
        False,
        1,
        0,
        False,
    ),
    (
        "M3",
        "SCR-036 open / close (docked drawer)",
        "opacity",
        "fast",
        "standard",
        "instant",
        (
            "the drawer and the chart reflowed by its width in one frame (E13-D02 D20); focus per "
            "§11.2"
        ),
        False,
        1,
        0,
        False,
    ),
    (
        "M4",
        "sub-pane create (the first indicator added to a sub-pane target)",
        "transform+clip",
        "normal",
        "standard",
        "instant",
        (
            "the new pane's header row and legend row with computing… (D6); the SCR-036 pane row;"
            " the add announcement"
        ),
        False,
        1,
        0,
        True,
    ),
    (
        "M5",
        "sub-pane collapse (the last indicator removed from a sub-pane)",
        "transform+clip",
        "normal",
        "standard",
        "instant",
        (
            "the SCR-036 pane row leaves with its child; the toast EMA 21 removed. with Undo; the"
            " removal announcement (D21)"
        ),
        False,
        1,
        0,
        True,
    ),
    (
        "M6",
        "series re-compute on a committed parameter change",
        "opacity",
        "fast",
        "standard",
        "cut",
        (
            "the new draw at full alpha from frame 0; the legend value; Updating… / Applying…"
            " (D13); computing… (D27); the once-per-commit announcement (E13-D02 §11.4)"
        ),
        False,
        1,
        1,
        True,
    ),
    (
        "M7",
        "legend row add",
        "opacity",
        "fast",
        "standard",
        "instant",
        "the row itself with value — and computing… (D6); the add announcement",
        False,
        1,
        0,
        True,
    ),
    (
        "M8",
        "legend row remove",
        "none",
        "instant",
        "—",
        "identical",
        (
            "the row leaves at frame 0; the toast EMA 21 removed. with Undo; the removal"
            " announcement (D21)"
        ),
        False,
        1,
        0,
        True,
    ),
    (
        "M9",
        "count chip and status suffix (CMP-224)",
        "none",
        "instant",
        "—",
        "identical",
        "the word Ind n and its one suffix (E11-D06 D15)",
        False,
        1,
        0,
        True,
    ),
)
INHERITED = ("12", "38", "39", "42", "43")  # E11-D06 section 7 rows cited, not re-specified
NEVER_ANIMATES = (
    "the preview tile and the chart-behind preview between curves (E13-D02 §11.6, D12)",
    "a theme, density or text-scale switch (E11-D06 §6.8: one frame, a LUT upload)",
    "the keyboard cursor and the crosshair position (E11-D06 D9, D11)",
    "a value, a status word, a glyph, a swatch (state flips, E11-D06 D15)",
    "the Style tab's token controls leaving T2 when the set ships (a state flip)",
    "the DEMO / LIVE badge and the replay frame (E11-D06 D20)",
)
TWIN_KINDS = frozenset(["instant", "cut", "identical"])
PROPERTIES = frozenset(["opacity", "transform", "clip", "none"])


def reference_run() -> dict[str, Any]:
    """E13-D03's own `--json`, run in-process (never a subprocess): the numbers to equal."""
    buf = io.StringIO()
    with redirect_stdout(buf):
        rc = d03.main(["--json"])
    ref: dict[str, Any] = json.loads(buf.getvalue())
    if rc != 0 or ref.get("fails"):
        FAILS.append(f"the E13-D03 tool itself fails at this base: {ref.get('fails')}")
    del d03.OUT[:]
    del d03.FAILS[:]
    return ref


def near(a: float, b: float, eps: float = 0.0051) -> bool:
    return abs(float(a) - float(b)) <= eps


def palette_section(ref: dict[str, Any]) -> tuple[list[dict[str, Any]], dict[str, list[str]]]:
    pal: list[dict[str, Any]] = []
    words: dict[str, list[str]] = {}
    pal, words = d03.palette()
    p("")
    p("## 2. The palette reproduced through the E13-D03 tool (gated equal to its own --json)")
    p("")
    row(
        "slot",
        "theme",
        "alias",
        "hex",
        "canvas",
        "overlay",
        "raised",
        "L*",
        "min dE (nearest)",
        "pill",
    )
    row(*["---"] * 10)
    ref_pal: list[dict[str, Any]] = ref["palette"]
    ref_pill: dict[str, list[str]] = ref["pill"]
    for i, rec in enumerate(pal):
        for ti, t in enumerate(THEMES):
            r: dict[str, Any] = rec[t]
            rr: dict[str, Any] = ref_pal[i][t]
            for key in ("canvas", "overlay", "raised", "dE", "L"):
                if not near(r[key], rr[key]):
                    DRIFT.append(f"slot {i + 1} {t} {key}: {r[key]} vs E13-D03 {rr[key]}")
            if r["hex"] != rr["hex"] or r["alias"] != rr["alias"]:
                DRIFT.append(f"slot {i + 1} {t}: {r['alias']} {r['hex']} vs E13-D03 {rr}")
            if float(r["canvas"]) < 3.0 or float(r["dE"]) < float(d03.DE_FLOOR):
                FAILS.append(
                    f"slot {i + 1} {t}: canvas {r['canvas']} or dE {r['dE']} under the floor"
                )
            row(
                i + 1,
                t,
                f"`{r['alias']}`",
                r["hex"],
                fmt(r["canvas"]),
                fmt(r["overlay"]),
                fmt(r["raised"]),
                f"{r['L']:.1f}",
                f"{r['dE']:.1f} (`{r['nearest']}`)",
                ref_pill[f"s{i + 1}"][ti],
            )
    p("")
    p(
        "PASS x 24 restated: every slot >= 3:1 on the canvas and >= 8 dE from every reserved token "
        "in all three themes; the price-scale pill per slot is E13-D03's (inverse where >= 4.5:1, "
        "else "
        "neutral). Family words: " + "; ".join(f"{t}: " + " / ".join(words[t]) for t in THEMES)
    )
    return pal, words


def cvd_section(ref: dict[str, Any]) -> dict[str, Any]:
    n_pairs, collapses, grey, min_adj, min_de = d03.cvd_pairs()
    n_proj, proj_counts, _listed = d03.slot_vs_reserved()
    out: dict[str, Any] = {
        "cvdPairs": int(n_pairs),
        "collapses": list(collapses),
        "grey": list(grey),
        "minAdjacentDL": {t: round(float(min_adj[t]), 1) for t in THEMES},
        "minSlotPairDE": {t: round(float(min_de[t]), 1) for t in THEMES},
        "projectionRows": int(n_proj),
        "projCollapses": {k: int(proj_counts[k]) for k in CVDS},
    }
    c = ref["counts"]
    for key, mine in (
        ("cvdPairs", out["cvdPairs"]),
        ("projectionRows", out["projectionRows"]),
        ("cvdCollapses", len(collapses)),
        ("greyPairsUnderJnd", len(grey)),
        ("protanCollapses", out["projCollapses"]["protanopia"]),
        ("deutanCollapses", out["projCollapses"]["deuteranopia"]),
        ("tritanCollapses", out["projCollapses"]["tritanopia"]),
        ("minAdjacentDL", min(out["minAdjacentDL"].values())),
        ("minSlotPairDE", min(out["minSlotPairDE"].values())),
    ):
        if not near(float(mine), float(c[key])):
            DRIFT.append(f"{key}: {mine} vs E13-D03 {c[key]}")
    if list(collapses) != list(ref["collapses"]) or list(grey) != list(ref["grey"]):
        DRIFT.append("the CVD collapses or the greyscale pairs differ from E13-D03's")
    p("")
    p(
        "## 3. CVD and greyscale (the adjacent slot pairs the assignment hands out in sequence; "
        "Brettel / Vienot through the E13-D03 tool; JND " + f"{float(d03.JND)})"
    )
    p("")
    row("pair", "normal", "protanopia", "deuteranopia", "tritanopia", "dL*")
    row(*["---"] * 6)
    adj: list[dict[str, Any]] = []
    for a, b in ((1, 2), (2, 3), (3, 4), (4, 5), (5, 6), (6, 7), (7, 8), (8, 1)):
        cells: dict[str, list[float]] = {"normal": [], "dL": []}
        for k in CVDS:
            cells[k] = []
        for t in THEMES:
            ha, hb = str(d03.slot(t, a)), str(d03.slot(t, b))
            cells["normal"].append(round(float(d03.de(ha, hb)), 1))
            for k in CVDS:
                cells[k].append(round(float(d03.de(d03.sim(ha, k), d03.sim(hb, k))), 1))
            cells["dL"].append(round(abs(float(d03.lstar(ha)) - float(d03.lstar(hb))), 1))
        adj.append({"pair": f"{a}-{b}", **cells})
        row(
            f"{a} vs {b}" + (" (wrap)" if (a, b) == (8, 1) else ""),
            *[" / ".join(f"{v:.1f}" for v in cells[k]) for k in ("normal", *CVDS, "dL")],
        )
    out["adjacent"] = adj
    p("")
    p(
        f"{out['cvdPairs']} slot-pair rows (28 pairs x 3 themes): {len(collapses)} collapses, all "
        "tritanopia, none adjacent (" + "; ".join(collapses) + "); greyscale pairs under 5 L*: "
        f"{len(grey)} (carried by the tier and the label, E13-D03 C-26); smallest adjacent dL* "
        + ", ".join(f"{t} {out['minAdjacentDL'][t]}" for t in THEMES)
        + "; smallest slot pair dE "
        + ", ".join(f"{t} {out['minSlotPairDE'][t]}" for t in THEMES)
        + f". {out['projectionRows']} slot x reserved x projection rows: "
        + ", ".join(f"{k} {out['projCollapses'][k]}" for k in CVDS)
        + " collapses (the protanopia / deuteranopia rows are E13-D03's four recorded residuals,"
        " C-28)."
    )
    return out


def alpha_section(ref: dict[str, Any]) -> dict[str, float]:
    alpha, worst_at, stacked = d03.band_alpha()
    out = {
        "alpha": float(alpha),
        "worstUnder": round(float(worst_at["under"]), 2),
        "worstOver": round(float(worst_at["over"]), 2),
        "worstCvd": round(min(float(worst_at["cvd-under"]), float(worst_at["cvd-over"])), 2),
        "twoFills": round(float(stacked["2 fills"]), 2),
        "threeFills": round(float(stacked["3 fills"]), 2),
    }
    c = ref["counts"]
    for key, rk in (
        ("alpha", "alpha"),
        ("worstUnder", "worstCandleAtAlpha"),
        ("worstOver", "worstCandleOverFill"),
        ("worstCvd", "worstCandleCvdSafe"),
        ("twoFills", "worstTwoFills"),
        ("threeFills", "worstThreeFills"),
    ):
        if not near(out[key], float(c[rk])):
            DRIFT.append(f"{key}: {out[key]} vs E13-D03 {c[rk]}")
    p("")
    p("## 4. The band-fill alpha reproduced")
    p("")
    p(
        f"opacity.indicator.fill = {out['alpha']:.2f}; the worst candle ratio over one fill: "
        f"{out['worstUnder']:.2f}:1 with the fill under the candles, {out['worstOver']:.2f}:1 over "
        f"them, {out['worstCvd']:.2f}:1 in the CVD-safe palette; two fills on one pixel "
        f"{out['twoFills']:.2f}:1, "
        f"three {out['threeFills']:.2f}:1 - fills never compound (E13-D03 §4.3)."
    )
    return out


def composite_section() -> dict[str, Any]:
    """Section 11.1's decorative composites: the half-faded old draw (M6) and the half-faded row
    label (M7) over the canvas, and the validity look (the primary fill and its label at
    opacity.disabled over the overlay); reported, never gated — the information is carried by the
    new draw, the row's words and the reason sentence."""
    dis = token_value("dark", "opacity.disabled")
    a_dis = float(str(dis))
    out: dict[str, Any] = {"opacityDisabled": a_dis}
    p("")
    p(
        "## 4b. Decorative composites (reported, not gated): the M6 old draw and the M7 row at 0.5 "
        "alpha "
        f"over the canvas; the validity look at opacity.disabled {a_dis}"
    )
    p("")
    row("composite", "dark", "light", "hc")
    row("---", "---", "---", "---")
    canvas = {t: str(d03.canvas(t)) for t in THEMES}
    half = {
        t: [
            round(float(d03.ratio(d03.blend(d03.slot(t, i), canvas[t], 0.5), canvas[t])), 2)
            for i in range(1, 9)
        ]
        for t in THEMES
    }
    out["halfSlotMin"] = {t: min(half[t]) for t in THEMES}
    out["halfSlotMax"] = {t: max(half[t]) for t in THEMES}
    row(
        "a slot at 0.5 over the canvas vs the canvas (min to max over the eight slots)",
        *[f"{out['halfSlotMin'][t]:.2f} to {out['halfSlotMax'][t]:.2f}" for t in THEMES],
    )
    label = {
        t: round(
            float(d03.ratio(d03.blend(str(T[t]["color.text.primary"]), canvas[t], 0.5), canvas[t])),
            2,
        )
        for t in THEMES
    }
    out["halfLabel"] = label
    row(
        "color.text.primary at 0.5 over the canvas vs the canvas (M7 mid-fade)",
        *[f"{label[t]:.2f}" for t in THEMES],
    )
    valid = {}
    for t in THEMES:
        overlay = str(T[t]["color.surface.overlay"])
        fill = d03.blend(str(T[t]["color.action.primary.default"]), overlay, a_dis)
        text = d03.blend(str(T[t]["color.text.on-action"]), overlay, a_dis)
        valid[t] = round(float(d03.ratio(text, fill)), 2)
    out["validityLabel"] = valid
    row(
        f"color.text.on-action on color.action.primary.default, both at {a_dis} over the overlay "
        "(Apply disabled by validity; the reason carries the state)",
        *[f"{valid[t]:.2f}" for t in THEMES],
    )
    return out


def frames(duration: int, fps: int) -> float:
    return round(duration / 1000 * fps, 1)


def redistribute_remove(ratios: list[float], idx: int) -> list[float]:
    """The leaving pane's ratio goes to the remaining panes in proportion to their ratios."""
    rest = [r for i, r in enumerate(ratios) if i != idx]
    total = sum(rest)
    return [r / total for r in rest]


def add_pane(ratios: list[float], new: float, floor: float) -> list[float]:
    """A new sub-pane takes `new` of the whole from the price pane (index 0) first, while the price
    pane stays above the floor; only the remainder is taken proportionally from the sub-panes, a
    sub-pane the take would push below the floor held there and its shortfall taken from the
    others (BQ-7 as ruled, issuecomment-6364739361 on #315: 26 section 8's 0.6 / 0.2 / 0.2 example
    reproduced exactly, the existing sub-panes stable).
    """
    out = list(ratios)
    give = max(0.0, min(new, out[0] - floor))
    out[0] -= give
    rest = new - give
    if rest > 1e-12 and len(out) > 1:
        subs = list(range(1, len(out)))
        sub_total = sum(out[i] for i in subs)
        for i in subs:
            out[i] -= rest * out[i] / sub_total
        for _ in range(len(subs)):
            short = sum(floor - out[i] for i in subs if out[i] < floor)
            if short <= 1e-12:
                break
            held = {i for i in subs if out[i] <= floor + 1e-12}
            free = [i for i in subs if i not in held]
            if not free:
                break
            free_total = sum(out[i] for i in free)
            for i in subs:
                out[i] = floor if i in held else out[i] - short * out[i] / free_total
    return [*out, new]


def r2(xs: list[float]) -> str:
    return " / ".join(
        f"{x:.2f}".rstrip("0").rstrip(".") if abs(x - round(x, 2)) < 1e-9 else f"{x:.3f}"
        for x in xs
    )


def motion_section() -> dict[str, Any]:
    out: dict[str, Any] = {}
    p("")
    p("## 5. The motion register (spec section 6 rows; every number computed)")
    p("")
    row("#", "element", "property", "duration", "easing", "twin", "loop", "lum/s", "+draws", "info")
    row(*["---"] * 10)
    animate = 0
    for mid, el, prop, dur, eas, twin, _carrier, loop, lum, extra, info in M_ROWS:
        props = prop.split("+")
        if any(x not in PROPERTIES for x in props):
            FAILS.append(f"{mid}: property {prop!r} is not opacity / transform / clip / none")
        if dur not in DURATIONS or (eas != "—" and eas not in EASINGS):
            FAILS.append(f"{mid}: duration {dur!r} or easing {eas!r} is not a token")
        if twin not in TWIN_KINDS:
            FAILS.append(f"{mid}: twin kind {twin!r}")
        if loop or lum > 1:
            FAILS.append(f"{mid}: loops or exceeds one luminance change per second")
        if DURATIONS[dur] > 0:
            animate += 1
        row(
            mid,
            el,
            prop,
            f"`motion.duration.{dur}` {DURATIONS[dur]} ms",
            "—" if eas == "—" else f"`motion.easing.{eas}`",
            twin,
            "no",
            lum,
            extra,
            "yes" if info else "no",
        )
    twins = sum(1 for r in M_ROWS if r[5] in TWIN_KINDS)
    out["mRows"], out["mAnimate"], out["mTwins"] = len(M_ROWS), animate, twins
    out["inheritedRows"] = len(INHERITED)
    p("")
    p(
        f"Coverage: {len(M_ROWS)} rows; {animate} animate under motion-safe; {twins} reduce twins "
        f"(= rows); {len(M_ROWS) - animate} rows have no motion in either mode; inherited E11-D06 "
        "rows " + ", ".join(INHERITED) + ". Never animates: " + "; ".join(NEVER_ANIMATES) + "."
    )
    # kinematics
    fast, normal = DURATIONS["fast"], DURATIONS["normal"]
    out["framesFast"] = [frames(fast, f) for f in FPS]
    out["framesNormal"] = [frames(normal, f) for f in FPS]
    out["firstFrameStandard"] = {
        str(d): [round(float(d06.first_frame_fraction("standard", d, f)), 3) for f in FPS]
        for d in (fast, normal)
    }
    n60 = round(fast / 1000 * 60)
    out["m6AlphaAt50"] = round(1 - float(d06.ease("standard", 50 / fast)), 2)
    out["m6Alphas60"] = [
        round(1 - float(d06.ease("standard", k / n60)), 2) for k in range(1, n60 + 1)
    ]
    p("")
    p(
        f"Kinematics: `fast` {fast} ms = "
        + " / ".join(f"{x:g}" for x in out["framesFast"])
        + f" frames at 30 / 60 / 144 fps; `normal` {normal} ms = "
        + " / ".join(f"{x:g}" for x in out["framesNormal"])
        + "; `standard` covers "
        + " / ".join(f"{x:.3f}" for x in out["firstFrameStandard"][str(normal)])
        + f" of the travel in the first frame at {normal} ms and "
        + " / ".join(f"{x:.3f}" for x in out["firstFrameStandard"][str(fast)])
        + f" at {fast} ms (30 / 60 / 144 fps). M6: the old draw's alpha 1 - standard(t): "
        + ", ".join(f"{a:.2f}" for a in out["m6Alphas60"])
        + f" over the {n60} frames at 60 fps; "
        f"{out['m6AlphaAt50']:.2f} at 50 ms."
    )
    # draw-call transient (E13-D03 section 11's scenes through its draw_calls())
    draws: dict[str, int] = {str(k): int(v) for k, v in d03.draw_calls().items()}
    scenes = (
        ("B5 price pane", draws["B5 price pane"]),
        ("nominal pane + 3", draws["nominal pane + 3"]),
        ("stress price pane", draws["stress price pane"]),
        ("stress sub-pane A", draws["stress sub-pane A"]),
        ("stress sub-pane B", draws["stress sub-pane B"]),
    )
    out["transient"] = {
        name: {
            "steady": n,
            "line": n + 1,
            "band": n + 2,
            "shed": "rung 0 first" if n + 1 > 18 else "within 18",
        }
        for name, n in scenes
    }
    out["transientFrames60"] = n60
    p("")
    p(
        "M6 draw-call transient (E13-D03 section 11's scenes, merged rule): a recomputing line "
        "series "
        "retains one instanced batch (+1), a band its fill pass and edge batch (+2), for <= "
        f"{n60} frames at 60 fps — "
        + "; ".join(
            f"{k} {v['steady']} -> {v['line']} (line) / {v['band']} (band), {v['shed']}"
            for k, v in out["transient"].items()
        )
        + ". A pane at the 18 ceiling exceeds it for the fade only and sheds M6 first (rung 0)."
    )
    # sub-pane ratio arithmetic (26 section 8's example; the floor E11-D06 section 6.4 names;
    # the price pane gives the new 0.2 first -- BQ-7 RULED, issuecomment-6364739361)
    size_2xs = token_value("dark", "font.size.2xs")
    tight = token_value("dark", "font.lineheight.tight")
    label_h = float(str(size_2xs)) * float(str(tight))
    floor_px = max(48.0, 3 * label_h)
    heights = [int(h) for _, h, _, _ in d03.STRESS]
    plot_h = sum(heights)
    example = [0.6, 0.2, 0.2]
    removed = redistribute_remove(example, 2)
    added = add_pane(example, 0.2, floor_px / plot_h)
    seq: list[list[float]] = [[1.0]]
    for _ in range(6):
        seq.append(add_pane(seq[-1], 0.2, floor_px / plot_h))
    out["ratios"] = {
        "example": example,
        "removeLast": [round(x, 4) for x in removed],
        "addPane": [round(x, 4) for x in added],
        "sixAddsPx": [round(x * plot_h) for x in seq[-1]],
        "floorPx": floor_px,
        "plotPx": plot_h,
        "labelPx": label_h,
        "newPane": 0.2,
    }
    p("")
    p(
        f"M4 / M5 ratios (26 section 8's example {r2(example)}): remove the last pane -> "
        f"{r2(removed)}; "
        f"add a 0.2 pane -> {r2(added)}. Floor max(48 px, 3 x axis label height): the label is "
        f"{label_h:g} px (type.num.xs: font.size.2xs {size_2xs} x line-height {tight}), so the "
        "floor "
        f"is {floor_px:g} px; on the {plot_h} px plot of E13-D03 section 11 "
        f"({' + '.join(str(h) for h in heights)})"
        f" six adds from one price pane give "
        + " / ".join(str(x) for x in out["ratios"]["sixAddsPx"])
        + " px, every pane >= the floor (the price pane reaches it on the fifth add and gives "
        "nothing on the sixth; the new 0.2 comes from the price pane first, then proportionally "
        "from the sub-panes -- BQ-7 as ruled)."
    )
    # flash audit and vestibular rows (E11-D06 section 9.3 / 9.4 shapes)
    p("")
    p(
        "Flash audit: every row <= 1 luminance change per second, nothing loops ("
        + ", ".join(f"{r[0]} {r[8]}/s" for r in M_ROWS)
        + "); M6 holds its 1 / s by rule (a commit within 1 s of the previous M6 start is a cut);"
        " the inherited rows keep E11-D06 section 9.3's verdicts."
    )
    out["flashMax"] = max(r[8] for r in M_ROWS)
    out["loops"] = sum(1 for r in M_ROWS if r[7])
    return out


def token_section(texts: dict[str, str]) -> dict[str, Any]:
    joined = "\n".join(texts.values())
    found = sorted(set(TOKEN_RE.findall(joined)))
    bound = [n for n in found if not n.endswith((".*", ".", ".n")) and ".." not in n]
    cr, absent, exists = [], [], []
    for name in bound:
        if token_value("dark", name) is not None:
            exists.append(name)
        elif name in CR_NAMES or name in CITED_ABSENT:
            cr.append(name)
        elif name in DRIFT_NAMES:
            absent.append(name)
        else:
            FAILS.append(f"token `{name}` is bound but exists in no token file and is not a CR row")
    for label, txt in texts.items():
        for line in txt.splitlines():
            if "color.text.disabled" in line and "never" not in line.lower():
                FAILS.append(f"{label}: color.text.disabled bound outside the forbidding sentence")
    p("")
    p("## 1. Token existence")
    p("")
    p(
        f"{len(bound)} names bound in the spec and the handoff: {len(exists)} exist in "
        f"packages/ui/tokens, {len(cr)} are CR rows (absent as expected: {', '.join(cr)}), "
        f"{len(absent)} recorded drifts "
        f"(absent, the C-rows' evidence: {', '.join(absent) or 'none'}). Motion tokens: "
        + ", ".join(f"motion.duration.{k} {v} ms" for k, v in DURATIONS.items())
        + "; "
        + ", ".join(f"motion.easing.{k} {v}" for k, v in EASINGS.items())
        + f". motion.slide exists: {token_value('dark', 'motion.slide') is not None}."
    )
    return {
        "tokensBound": len(bound),
        "tokensExist": len(exists),
        "tokensCR": len(cr),
        "tokensDrift": len(absent),
    }


def vocabulary_section(spec: str) -> dict[str, Any]:
    table = rows_of(section(spec, "## 4.", "## 5."))
    keys: dict[str, list[str]] = {}
    for cells in table:
        if len(cells) < 2 or not re.fullmatch(r"`[a-z_]+`", cells[0]):
            continue
        keys[cells[0].strip("`")] = re.findall(r"`([^`]+)`", cells[1])
    bad = [v for vs in keys.values() for v in vs if not VOCAB_VALUE_RE.match(v)]
    counts = {k: len(v) for k, v in keys.items()}
    if set(keys) != set(VOCAB_COUNTS) or bad or counts != VOCAB_COUNTS:
        FAILS.append(f"vocabulary: keys {sorted(keys)} counts {counts} bad values {bad}")
    p("")
    p("## 6. The closed style vocabulary (spec section 4)")
    p("")
    p(
        f"{len(keys)} keys; values per key "
        + " / ".join(str(counts.get(k, 0)) for k in VOCAB_COUNTS)
        + f" ({', '.join(VOCAB_COUNTS)}); every value a token or registry id: {not bad}."
    )
    return {
        "vocabularyKeys": len(keys),
        "vocabularyCounts": [counts.get(k, 0) for k in VOCAB_COUNTS],
    }


def quoted(cells: list[list[str]]) -> list[str]:
    out: list[str] = []
    for c in cells:
        if len(c) >= 2:
            out.extend(re.findall(r'"([^"]+)"', c[1]))
    return out


def string_section(texts: dict[str, str], constitution: str) -> dict[str, Any]:
    spec = texts["spec"]
    deck = section(spec, "## 10.", "## 11.")
    d02 = rows_of(section(read(D02_SPEC), "## 12. Copy deck", "## 13."))
    d03_rows = rows_of(section(read(D03_SPEC), "## 13. Copy deck delta", "## 14."))
    missing: list[str] = []
    for src, rows_ in (("E13-D02 §12", d02), ("E13-D03 §13", d03_rows)):
        for s in quoted(rows_):
            if s not in deck:
                missing.append(f"{src}: {s!r}")
    if missing:
        FAILS.append(f"copy deck: {len(missing)} upstream strings missing: {missing[:5]}")
    deck_rows = rows_of(deck)
    d04_rows = [r for r in deck_rows if len(r) >= 3 and r[2].startswith("D04")]
    keys: list[tuple[str, str]] = []
    for cells in rows_of(section(spec, "### 10.2", "## 11.")):
        if len(cells) >= 3 and cells[0].startswith("`indicator."):
            sentence = re.findall(r'"([^"]+)"', cells[2])
            keys.append((cells[0].strip("`"), sentence[0] if sentence else ""))
    key_lines = [
        f"{k} ({len(s)} chars{'' if s.endswith('.') else ', no full stop'})" for k, s in keys
    ]
    gate: list[str] = []
    for label, txt in texts.items():
        if label in ("spec", "draft") and "Period must be between 1 and 5000." not in txt:
            gate.append(f"{label}: the IR-07 string is missing")
        for m in re.findall(r"between 1 and (\d+)", txt):
            if m != "5000":
                gate.append(f"{label}: 'between 1 and {m}'")
        if re.search(r"\(est(?!imated\))", txt) or "Est." in txt:
            gate.append(f"{label}: an abbreviated '(estimated)'")
        for line in txt.splitlines():
            if (
                re.search(r"dash", line, re.IGNORECASE)
                and re.search(r"\bleg\b", line)
                and "provisional" not in line
            ):
                gate.append(f"{label}: a dashed leg without 'provisional': {line[:60]!r}")
        if LOCAL_PATH_RE.search(txt):
            gate.append(f"{label}: a local path")
        if PENPOT_HOST_RE.search(txt):
            gate.append(f"{label}: a Penpot hostname")
        if "SET-" + "ME" in txt:
            gate.append(f"{label}: a placeholder constant left in")
        if CLOSING_RE.search(txt):
            gate.append(f"{label}: a closing keyword")
        scan = txt
        if (
            label == "draft"
        ):  # the harness's mandated generated-with line is not the draft's own text
            scan = "\n".join(
                ln for ln in txt.splitlines() if "Generated with [Claude Code]" not in ln
            )
        for m2 in EMOJI_RE.finditer(scan):
            gate.append(f"{label}: emoji U+{ord(m2.group(0)):04X}")
        for c in sorted(set(re.findall(r"C-\d+\.\d+", txt))):
            if not re.search(rf"(?<![\w.]){re.escape(c)}(?!\d)", constitution):
                gate.append(f"{label}: {c} is not in CONSTITUTION.md")
    FAILS.extend(gate)
    p("")
    p("## 7. String gates")
    p("")
    p(
        f"Copy deck: {len(deck_rows)} rows; E13-D02 §12 {len(d02)} rows / {len(quoted(d02))} "
        "strings "
        "and "
        f"E13-D03 §13 {len(d03_rows)} rows / {len(quoted(d03_rows))} strings present verbatim: "
        f"{len(missing)} missing; E13-D04 rows {len(d04_rows)}. PROPOSED indicator.* keys "
        "(printed, "
        "not "
        "gated): "
        + ("; ".join(key_lines) or "none")
        + ". Gates: "
        + ("all pass" if not gate else "; ".join(gate))
    )
    return {
        "deckRows": len(deck_rows),
        "deckD02": len(d02),
        "deckD03": len(d03_rows),
        "deckD04": len(d04_rows),
        "deckMissing": len(missing),
        "indicatorKeys": len(keys),
    }


def structure_section(spec: str, handoff: str, plan14: str) -> dict[str, Any]:
    boards = [
        r for r in rows_of(section(spec, "## 0.", "## 1.")) if r and re.fullmatch(r"0\d", r[0])
    ]
    light = [r for r in boards if len(r) > 1 and "-light" in r[1]]
    m_rows = re.findall(r"^\| (M\d+) ", section(spec, "## 6.", "## 7."), re.MULTILINE)
    inherited = "Inherited rows" in section(spec, "## 6.", "## 7.")
    ledger = [
        r for r in rows_of(section(spec, "### 1.4", "### 1.5")) if r and re.fullmatch(r"L\d+", r[0])
    ]
    unanswered = [r[0] for r in ledger if len(r) < 5 or not r[3].strip()]
    counts = {
        "aRows": len(re.findall(r"^\| A-\d+ ", section(spec, "## 17.", "## 18."), re.MULTILINE)),
        "crRows": len(re.findall(r"^\| CR-\d+ ", section(spec, "## 17.", "## 18."), re.MULTILINE)),
        "cRows": len(re.findall(r"^\| C-\d+ ", section(spec, "## 18.", "## 19."), re.MULTILINE)),
        "gRows": len(re.findall(r"^\| G-\d+ ", section(spec, "## 19.", "## 20."), re.MULTILINE)),
        "qRows": len(re.findall(r"^\| BQ-\d+ ", section(spec, "## 20.", "## 21."), re.MULTILINE)),
        "dRows": len(re.findall(r"^\| D\d+ ", section(spec, "### 1.5", "## 2."), re.MULTILINE)),
    }
    fenced = re.findall(
        r"```text\n(### CMP-(?:194|195|199|224) [^\n]*)", section(spec, "## 17.", "## 18.")
    )
    lines14 = [
        ln
        for ln in plan14.splitlines()
        if ln.startswith("- **DS and motion:**") and "E13-D04.md" in ln
    ]
    placed = 0
    all14 = plan14.splitlines()
    for i, ln in enumerate(all14):
        if (
            ln in lines14
            and i > 0
            and all14[i - 1].startswith("- **Hi-fi:**")
            and "E13-D03" in all14[i - 1]
            and i + 1 < len(all14)
            and all14[i + 1].startswith("- **Design sign-off")
        ):
            placed += 1
    blocks = handoff.count("## Handoff checklist")
    blank = bool(re.search(r"^- \[ \] \*\*[^*]+\*\*\s*$", handoff, re.MULTILINE))
    stories = sum(
        int(r[1])
        for r in rows_of(section(spec, "## 12.", "## 13."))
        if len(r) > 1 and r[1].isdigit()
    )
    problems: list[str] = []
    if len(boards) != 8 or len(light) != 2:
        problems.append(f"boards {len(boards)}, light twins {len(light)}")
    if len(m_rows) < 9 or not inherited:
        problems.append(f"M rows {len(m_rows)}, inherited block {inherited}")
    if len(ledger) != 38 or unanswered:
        problems.append(f"ledger rows {len(ledger)}, unanswered {unanswered}")
    if len(fenced) != 4:
        problems.append(f"15 A-row fenced entries {len(fenced)}")
    if len(lines14) != 3 or placed != 3 or sum(1 for ln in all14 if "E13-D04.md" in ln) != 3:
        problems.append(f"14 lines {len(lines14)}, placed {placed}")
    if blocks != 4 or blank:
        problems.append(f"handoff blocks {blocks}, blank line {blank}")
    FAILS.extend("structure: " + x for x in problems)
    p("")
    p("## 8. Structure")
    p("")
    p(
        f"{len(boards)} boards in section 0 ({len(light)} light twins: "
        + ", ".join(r[0] for r in light)
        + f"); {len(m_rows)} M rows + the inherited block; ledger L1 to L{len(ledger)}"
        f" each answered; D rows {counts['dRows']}; A {counts['aRows']} / CR {counts['crRows']} / "
        f"C {counts['cRows']} / G {counts['gRows']} / BQ {counts['qRows']}; `15` entries as fenced "
        f"A-rows: {len(fenced)}; `14` pointer lines: {len(lines14)} ({placed} directly after the "
        f"Hi-fi line, before the checklist); handoff blocks "
        f"{blocks}, blank checklist line {blank}; Storybook stories {stories}."
    )
    out: dict[str, Any] = {
        "boards": len(boards),
        "lightTwins": len(light),
        "mRowsInSpec": len(m_rows),
        "ledgerRows": len(ledger),
        "fifteenEntries": len(fenced),
        "lines14": len(lines14),
        "handoffBlocks": blocks,
        "stories": stories,
    }
    out.update(counts)
    return out


def main(argv: list[str]) -> int:
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")
    spec_path = Path(argv[argv.index("--spec") + 1]) if "--spec" in argv else SPEC
    handoff_path = Path(argv[argv.index("--handoff") + 1]) if "--handoff" in argv else HANDOFF
    spec, handoff, plan14 = read(spec_path), read(handoff_path), read(PLAN14)
    texts = {
        "spec": spec,
        "handoff": handoff,
        "14 lines": "\n".join(ln for ln in plan14.splitlines() if "E13-D04" in ln),
    }
    if "--draft" in argv:
        texts["draft"] = read(Path(argv[argv.index("--draft") + 1]))
    ref = reference_run()
    tok = token_section({"spec": spec, "handoff": handoff})
    pal, words = palette_section(ref)
    cvd = cvd_section(ref)
    alpha = alpha_section(ref)
    composites = composite_section()
    motion = motion_section()
    vocab = vocabulary_section(spec)
    strings = string_section(texts, read(ROOT / "CONSTITUTION.md"))
    structure = structure_section(spec, handoff, plan14)
    # the numbers the spec quotes must be the computed ones (--check drift)
    quotes = {
        "alpha": f"`opacity.indicator.fill` = {alpha['alpha']:.2f}",
        "worst": f"{alpha['worstUnder']:.2f}:1",
        "over": f"{alpha['worstOver']:.2f}:1",
        "cvd": f"{alpha['worstCvd']:.2f}:1",
        "remove": r2(motion["ratios"]["removeLast"]),
        "add": r2(motion["ratios"]["addPane"]),
        "tally": f"{motion['mRows']} rows; {motion['mAnimate']} animate under motion-safe; "
        f"{motion['mTwins']} twins",
        "frames": f"{motion['framesFast'][1]:g} frames",
        "alpha50": f"{motion['m6AlphaAt50']:.2f}",
    }
    for k, q in quotes.items():
        if q not in spec:
            DRIFT.append(f"spec does not quote {k}: {q!r}")
    table = rows_of(section(spec, "### 2.1", "### 2.2"))
    for i, rec in enumerate(pal):
        cells = next((r for r in table if r and r[0] == f"`color.indicator.palette.{i + 1}`"), None)
        if cells is None:
            DRIFT.append(f"section 2.1 has no row for slot {i + 1}")
            continue
        line = " | ".join(cells)
        for t in THEMES:
            r: dict[str, Any] = rec[t]
            for val in (r["hex"], fmt(r["canvas"]), f"{r['dE']:.1f}"):
                if str(val) not in line:
                    DRIFT.append(f"section 2.1 slot {i + 1} {t}: {val} not quoted")
    if d03.FAILS:
        FAILS.extend(f"E13-D03 function: {x}" for x in d03.FAILS)
    hygiene_ok = not any(x.startswith(("spec:", "handoff:", "14 lines:", "draft:")) for x in FAILS)
    counts: dict[str, Any] = {
        "slots": 8,
        "lineTiers": int(d03.TIERS),
        "barTiers": 3,
        "bandTiers": 3,
        "glyphTiers": 3,
        "reservedDash": len(d03.RESERVED_DASH),
        **tok,
        **vocab,
        **strings,
        **structure,
        "mRows": motion["mRows"],
        "mAnimate": motion["mAnimate"],
        "mTwins": motion["mTwins"],
        "inheritedRows": motion["inheritedRows"],
        "flashMax": motion["flashMax"],
        "loops": motion["loops"],
        "framesFast": motion["framesFast"],
        "framesNormal": motion["framesNormal"],
        "firstFrameStandard": motion["firstFrameStandard"],
        "m6AlphaAt50": motion["m6AlphaAt50"],
        "m6Alphas60": motion["m6Alphas60"],
        "transient": motion["transient"],
        "ratios": motion["ratios"],
        "alpha": alpha["alpha"],
        "worstCandleAtAlpha": alpha["worstUnder"],
        "worstCandleOverFill": alpha["worstOver"],
        "worstCandleCvdSafe": alpha["worstCvd"],
        "worstTwoFills": alpha["twoFills"],
        "worstThreeFills": alpha["threeFills"],
        "cvdPairs": cvd["cvdPairs"],
        "cvdCollapses": len(cvd["collapses"]),
        "greyPairsUnderJnd": len(cvd["grey"]),
        "minAdjacentDL": min(cvd["minAdjacentDL"].values()),
        "minSlotPairDE": min(cvd["minSlotPairDE"].values()),
        "projectionRows": cvd["projectionRows"],
        "protanCollapses": cvd["projCollapses"]["protanopia"],
        "deutanCollapses": cvd["projCollapses"]["deuteranopia"],
        "tritanCollapses": cvd["projCollapses"]["tritanopia"],
        "durations": DURATIONS,
        "composites": composites,
        "drift": len(DRIFT),
        "d03Counts": ref["counts"],
    }
    slot_hex = {t: [str(rec[t]["hex"]) for rec in pal] for t in THEMES}
    canvas = {t: [fmt(float(rec[t]["canvas"])) for rec in pal] for t in THEMES}
    min_de = {t: [f"{float(rec[t]['dE']):.1f}" for rec in pal] for t in THEMES}
    if "--json" in argv:
        print(
            json.dumps(
                {
                    "counts": counts,
                    "palette": pal,
                    "familyWords": words,
                    "slotHex": slot_hex,
                    "canvas": canvas,
                    "minDE": min_de,
                    "adjacent": cvd["adjacent"],
                    "collapses": cvd["collapses"],
                    "grey": cvd["grey"],
                    "drift": DRIFT,
                    "fails": FAILS,
                },
                indent=1,
                ensure_ascii=False,
            )
        )
        return 1 if FAILS or ("--check" in argv and DRIFT) else 0
    print("\n".join(OUT))
    print(
        f"\n## 9. Hygiene {'OK' if hygiene_ok else 'FAIL'}; drift {len(DRIFT)}"
        + ("" if not DRIFT else ": " + "; ".join(DRIFT))
    )
    print("\n## 10. Counts\n" + json.dumps(counts, ensure_ascii=False))
    print(
        "\nGATED FAILURES: "
        + ("; ".join(FAILS) if FAILS else "none")
        + f"\nexit {1 if FAILS or ('--check' in argv and DRIFT) else 0}"
    )
    return 1 if FAILS or ("--check" in argv and DRIFT) else 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
