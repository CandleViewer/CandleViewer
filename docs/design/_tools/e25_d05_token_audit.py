#!/usr/bin/env python3
"""E25-D05 token audit: the detector components' contrast matrix, token bindings and counts.

Standalone, offline, stdlib only. Reads `packages/ui/tokens/primitives.tokens.json` and the three
semantic files, resolves `{alias}` references per theme with the layering `themes.json` declares
(dark = primitives + semantic-dark; light and high-contrast layer their file over dark), the way
`packages/ui/tokens/tests/verify_tokens.py` does (same loader shape, same WCAG 2.x luminance;
nothing is imported from it, so this tool stands alone), and prints, with a source label on
every row:

1. the WCAG 2.x contrast ratio of every foreground / background pair the six components of
   `docs/design/E25/E25-D05.md` render (CMP-227, CMP-131, CMP-187, CMP-132, CMP-133, CMP-134),
   in dark / light / high-contrast, against the role's bar (text 4.5:1, non-text 3:1, hc-text
   7:1 in the high-contrast theme only; `05-accessibility-standard.md` section 5 items 1, 2 and
   6) with PASS or FAIL. The UNROUNDED ratio is compared against the bar, as the CI gate does
   (`tools/contrast/generate.mjs`: `ratio >= threshold`); the display rounds to the hundredth,
   and a value that would round onto a bar is printed to four decimals so the display never
   implies a verdict it did not measure (the pre-PR lens round 1: `color.status.warning.default`
   on `color.surface.raised` is 2.9992 in light, below 3:1, and is now a `decorative` row).
   `rejected-*` rows are pairs the spec considered and designed around and `decorative` rows
   carry no meaning (`16-design-system-brief.md` section 6 rule 7): both are reported, never
   gated;
2. every token name the six `15-component-catalogue.md` entries and the spec bind, resolved in
   all three themes or MISSING (`font.mono`, `color.chip.*`, `pattern.hatch`, `color.marker.*`
   and `color.callout.*` are expected MISSING: catalogue drift, E25-D01 G1 / G2); a pattern
   registry id is reported as such, never as a token;
3. which of the spec's pairs are present in `tools/contrast/pairs.mjs` (a text scan of its
   `fg` / `bg` literals) and which are PROPOSED additions for the first implementation ticket,
   plus whether `tools/contrast/encodings.json` carries an `estimated` encoding row;
4. the counts the Penpot boards quote (components, variants, states, stories, pairs).

The data tables below are pipe-separated text, one row per line, parsed at import time.

Usage: python3 -I docs/design/_tools/e25_d05_token_audit.py         (Markdown; exit 1 on a FAIL)
       python3 -I docs/design/_tools/e25_d05_token_audit.py --json  (the boards' numbers)
"""

from __future__ import annotations

import json
import re
import sys
from pathlib import Path
from typing import TypedDict, cast

ROOT = Path(__file__).resolve().parents[3]
TOKENS = ROOT / "packages" / "ui" / "tokens"
PAIRS_MJS = ROOT / "tools" / "contrast" / "pairs.mjs"
ENCODINGS = ROOT / "tools" / "contrast" / "encodings.json"
PRIM, DARK, LIGHT, HC = (
    "primitives.tokens.json",
    "semantic-dark.tokens.json",
    "semantic-light.tokens.json",
    "semantic-hc.tokens.json",
)
THEMES: dict[str, tuple[str, ...]] = {
    "dark": (PRIM, DARK),
    "light": (PRIM, DARK, LIGHT),
    "high-contrast": (PRIM, DARK, HC),
}
THEME_ORDER = ("dark", "light", "high-contrast")
NON_TEXT_BAR = 3.0
BAR: dict[str, float | None] = {
    "text": 4.5,
    "non-text": NON_TEXT_BAR,
    "hc-text": 7.0,
    "decorative": None,
    "rejected-text": 4.5,
    "rejected-non-text": NON_TEXT_BAR,
}
BARS = (NON_TEXT_BAR, 4.5, 7.0)
GATED = ("text", "non-text", "hc-text")
HEX6 = re.compile(r"^#[0-9A-Fa-f]{6}$")

# element | fg | bg | role | source  -- every pair the six components draw (spec section 12).
# A line indented by two spaces continues the record above it (so no physical line passes 100).
PAIRS_TABLE = """
CMP-227 word (estimated), every variant and size; CMP-133 label; callout sentence
  | color.text.primary | color.status.info.subtle | text | spec 4, 7; E24-D01 matrix
rejected: the hue-on-word reading (.strong text on the .subtle fill)
  | color.status.info.strong | color.status.info.subtle | rejected-text | E24-D01 (fails light)
CMP-227 word in the high-contrast theme (05 section 5 item 6 stretch)
  | color.text.primary | color.status.info.subtle | hc-text | spec 4
CMP-134 title, detector name, observed / inferred copy; CMP-133 evidence number
  | color.text.primary | color.surface.raised | text | spec 7, 8
CMP-134 parameter-snapshot labels; CMP-187 legend label; CMP-133 evidence labels; CMP-131 peak
  caption and tick, Delayed tag
  | color.text.secondary | color.surface.raised | text | spec 5, 7, 8
CMP-134 time and the unknown-size line; CMP-032 empty-dot caption
  | color.text.tertiary | color.surface.raised | text | spec 8; E24-D01 matrix
CMP-131 readout number and sentence; CMP-132 on-chart zone label (mirror-backed)
  | color.text.primary | color.surface.canvas | text | spec 5, 6
CMP-131 baseline sentence; CMP-187 window label
  | color.text.secondary | color.surface.canvas | text | spec 5
CMP-131 'over 5 s' window tag; CMP-187 axis caption
  | color.text.tertiary | color.surface.canvas | text | spec 5
CMP-131 band chip word 'extreme' on the warning tint
  | color.text.primary | color.status.warning.subtle | text | spec 5
rejected: warning.strong word on the warning tint
  | color.status.warning.strong | color.status.warning.subtle | rejected-text | spec 5
CMP-239 'Stale 12s' beside the chip (E08-D04 composition)
  | color.data-confidence.stale.text | color.data-confidence.stale.surface | text | 15 CMP-239
CMP-134 selected card text (the cross-highlighted card)
  | color.text.primary | color.surface.selected | text | spec 8
CMP-227 glyph on the chip fill (icon/estimated, 12 px)
  | color.status.info.default | color.status.info.subtle | non-text | spec 4
CMP-227 outline (border.hairline) on a card or panel; CMP-032 filled dots
  | color.status.info.default | color.surface.raised | non-text | spec 4, 7; E24-D01 matrix
CMP-227 outline on the app surface (rows, headers, alert rows)
  | color.status.info.default | color.surface.app | non-text | spec 4
CMP-227 marker variant: the hollow / dashed mark on the chart (and its 1 px pane-colour halo's
  adjacent pair, E06-D03 D10)
  | color.status.info.default | color.surface.canvas | non-text | spec 4, 6
CMP-227 section variant inside the SCR-058 drawer (overlay surface)
  | color.status.info.default | color.surface.overlay | non-text | spec 4
focus ring around the chip or card on a raised surface
  | color.focus.ring | color.surface.raised | non-text | spec 10
focus ring on the canvas (CMP-132 surrogate, CMP-227 marker)
  | color.focus.ring | color.surface.canvas | non-text | spec 10
focus ring on the app surface
  | color.focus.ring | color.surface.app | non-text | spec 10
CMP-132 active / tested zone outline, BUY; CMP-131 buy half of the side split
  | color.buy.default | color.surface.canvas | non-text | spec 5, 6
CMP-132 active / tested zone outline, SELL; CMP-131 sell half of the side split
  | color.sell.default | color.surface.canvas | non-text | spec 5, 6
CMP-134 side glyph and word, BUY, on a card
  | color.buy.default | color.surface.raised | non-text | spec 8
CMP-134 side glyph and word, SELL, on a card
  | color.sell.default | color.surface.raised | non-text | spec 8
CMP-132 broken-zone hatch lines (1 px, 6 px pitch); CMP-131 usual-rate tick
  | color.text.tertiary | color.surface.canvas | non-text | spec 5, 6
rejected as hatch ink: border.strong (E11-D02 D8 maintenance ink); decorative as the track
  | color.border.strong | color.surface.canvas | rejected-non-text | spec 5, 6
CMP-132 cross-highlight outline (the SCR-056 row selected)
  | color.border.selected | color.surface.canvas | non-text | spec 6
CMP-187 extreme band segment on the pane (canvas)
  | color.status.warning.default | color.surface.canvas | non-text | spec 5
CMP-131 extreme band segment and chip outline on the panel: 2.9992 in light, below 3:1, so
  decorative -- the word 'extreme' and the 2 px thicker segment carry the band (lens round 1)
  | color.status.warning.default | color.surface.raised | decorative | spec 5, 12
CMP-131 needle
  | color.text.primary | color.surface.canvas | non-text | spec 5
CMP-131 strip line (CMP-024) and the peak dot on it
  | color.text.secondary | color.surface.canvas | non-text | spec 5
CMP-239 stale indicator beside the chip
  | color.data-confidence.stale.indicator | color.data-confidence.stale.surface | non-text | 15
CMP-134 flat presentation border (structure is carried by space.stack.sm)
  | color.border.default | color.surface.raised | decorative | spec 8
"""

# token | bound by  -- every token the six entries and the spec name; expected MISSING ones included
BINDINGS_TABLE = """
color.status.info.default | CMP-227 outline + glyph; CMP-133; CMP-032 dots
color.status.info.subtle | CMP-227 fill; CMP-133; callout
color.text.primary | every word
color.text.secondary | labels, baseline sentence
color.text.tertiary | captions, hatch ink, ticks
color.surface.app | host surface
color.surface.canvas | CMP-131 / 187 / 132 chart surfaces
color.surface.raised | CMP-134 card, panels
color.surface.overlay | SCR-058 drawer (section variant)
color.surface.selected | CMP-134 selected
color.border.default | CMP-134 flat border
color.border.selected | CMP-132 cross-highlight
color.focus.ring | focus ring, every component
color.buy.default | CMP-132 / 134 BUY glyph + outline
color.buy.subtle | CMP-132 BUY zone fill
color.sell.default | CMP-132 / 134 SELL glyph + outline
color.sell.subtle | CMP-132 SELL zone fill
color.status.warning.default | CMP-131 extreme band segment
color.status.warning.subtle | CMP-131 extreme band chip fill
color.data-confidence.stale.text | CMP-239 composition
color.data-confidence.stale.indicator | CMP-239 composition
color.data-confidence.stale.surface | CMP-239 composition
radius.badge | CMP-227 / CMP-133 pill
radius.card | CMP-134
type.ui.caption | CMP-227 sm word
type.ui.label | CMP-227 md word; CMP-134 labels
type.num.lg | CMP-131 number
type.num.base | CMP-134 price, CMP-133 confidence
type.num.sm | CMP-187 axis
font.family.mono | every number (15 section 0.3 rule 6)
font.family.ui | every word
font.size.xs | CMP-227 sm
font.size.sm | CMP-227 md
size.icon.sm | CMP-227 glyph 12 px
size.control.height | row height, both densities
size.target.min | the 24 px hit target
space.inset.xs | 4 px composition gap; chip padding
space.inset.sm | card padding compact
space.inset.md | card padding comfortable
space.stack.sm | card gap in a list
border.hairline | chip outline, tested dashed outline
border.thick | hover outline; extreme band track
border.focus | focus ring width
elevation.card | CMP-134 static presentation
motion.duration.instant | every state flip
opacity.muted | CMP-132 broken-zone fill weight
font.mono | CMP-131 (catalogue, pre-edit): expected MISSING, G1
color.chip.estimated | CMP-011 `color.chip.*`: expected MISSING, G1
pattern.hatch | CMP-132 (catalogue, pre-edit): expected MISSING, G2
color.marker.default | CMP-195 `color.marker.*`: expected MISSING, G1
color.callout.info | CMP-028 `color.callout.*`: expected MISSING, G1
elevation.1 | CMP-050: a primitive; the semantic alias is elevation.card
"""
PRIMITIVE_ONLY = ("elevation.1",)
PATTERN_IDS = (
    "pattern.hatch.estimated",
    "pattern.dashed.estimated",
    "pattern.dashed.tested",
    "pattern.hatch.absent",
    "pattern.hatch.gap",
)

# component | comma-separated variants   /   component | states   /   story group | stories
VARIANTS_TABLE = """
CMP-227 | inline, marker, section
CMP-131 | gauge, strip, number
CMP-187 | pane
CMP-132 | active, tested, broken
CMP-133 | trending_up, trending_down, ranging, volatile_expansion, compression
CMP-134 | iceberg, stop_run, absorption, exhaustion, unfinished_auction
"""
STATES_TABLE = """
CMP-227 | default, hover, focus-visible, active, tooltip-open, with-freshness, with-confidence,
  hc, greyscale
CMP-131 | loading, warming, live, delayed, idle-zero, stale, disconnected, error, calm, elevated,
  extreme, focus-visible, hc, reduced-motion
CMP-187 | default, warming, delayed, idle-zero, stale, table-alternative, hc, reduced-motion
CMP-132 | active, tested, broken, selected, inherited-estimated, focus-visible, hc, greyscale
CMP-133 | default, hover, focus-visible, confidence-absent, insufficient-data, hc, greyscale
CMP-134 | static, flat, stale, selected, focus-visible, detector-off-flag, detector-off-user,
  error, loading, empty, hc, reduced-motion
"""
STORIES_TABLE = """
Atoms/EstimatedBadge | Inline, Marker, Section, SizeSm, SizeMd, Hover, FocusVisible, Active,
  TooltipOpen, WithConfidenceWord, WithStaleFreshnessMarker, CalloutComposition,
  LongDetectorName, HighContrast, Greyscale, ReducedMotion, OutsideProviderThrows
Trading/SpeedOfTapeGauge | Gauge, Strip, Number, Composite, WindowOneSec, WindowFiveSec,
  WindowThirtySec, SideSplit, BandCalm, BandElevated, BandExtreme, WarmingUp, IdleZero, Loading,
  Stale, Delayed, Disconnected, DetectorError, HighWaterMarker, FocusVisible,
  AlertAffordanceDisabled, LongReadout, HighContrast, ReducedMotion, BandFlapGuard
ChartEngine/SpeedOfTapePane | Default, LegendRow, TableAlternative, WarmingUp, Delayed, IdleZero,
  Stale, HighContrast, ReducedMotion
ChartEngine/ImbalanceStackIndicator | ActiveBuy, ActiveSell, TestedBuy, TestedSell, BrokenBuy,
  BrokenSell, Selected, InheritedEstimated, FocusVisible, HighContrast, Greyscale
Trading/RegimeIndicatorChip | TrendingUp, TrendingDown, Ranging, Volatile, Calm, LowConfidence,
  MediumConfidence, HighConfidence, ConfidenceAbsent, InsufficientData, Hover, FocusVisible,
  LongLabelGuard, HighContrast, Greyscale
Trading/DetectorEventCard | Iceberg, StopRun, Absorption, Exhaustion, UnfinishedAuction, Flat,
  Static, Stale, DetectorOffFlag, DetectorOffUser, DetectorError, Loading, Empty, Selected,
  FocusVisible, LongText, HighContrast, ReducedMotion
"""
DIMENSIONS = (
    "font.size.xs",
    "font.size.sm",
    "size.icon.sm",
    "size.control.height",
    "size.control.compact",
    "size.control.comfortable",
    "size.target.min",
    "space.inset.xs",
    "space.inset.sm",
    "space.inset.md",
    "space.stack.sm",
    "radius.badge",
    "radius.card",
    "border.hairline",
    "border.thick",
    "border.focus",
    "motion.duration.instant",
    "motion.duration.fast",
    "opacity.muted",
)
PX_TYPES = ("sizing", "spacing", "borderRadius", "borderWidth", "fontSizes")


class PairRow(TypedDict):
    element: str
    fg: str
    bg: str
    role: str
    bar: float | None
    ratios: dict[str, float | None]
    verdict: str
    registered: bool
    source: str


class TokenRow(TypedDict):
    token: str
    bound_by: str
    status: str
    values: dict[str, str]


Tokens = dict[str, dict[str, object]]


def rows(table: str) -> list[list[str]]:
    """One record per line; a line indented by two spaces continues the record above it."""
    records: list[str] = []
    for ln in table.strip("\n").splitlines():
        if not ln:
            continue
        if ln.startswith("  ") and records:
            records[-1] += " " + ln.strip()
        else:
            records.append(ln.strip())
    return [[c.strip() for c in rec.split(" | ")] for rec in records]


def listed(table: str) -> dict[str, tuple[str, ...]]:
    return {k: tuple(x.strip() for x in v.split(",")) for k, v in rows(table)}


PAIRS = rows(PAIRS_TABLE)
BINDINGS = rows(BINDINGS_TABLE)
VARIANTS = listed(VARIANTS_TABLE)
STATES = listed(STATES_TABLE)
STORIES = listed(STORIES_TABLE)


def load(name: str) -> Tokens:
    return cast(Tokens, json.loads((TOKENS / name).read_text(encoding="utf-8")))


def merged(files: tuple[str, ...]) -> Tokens:
    out: Tokens = {}
    for f in files:
        out.update(load(f))
    return out


def resolve(value: object, tokens: Tokens, seen: frozenset[str] = frozenset()) -> object:
    if isinstance(value, str) and value.startswith("{") and value.endswith("}"):
        ref = value[1:-1]
        if ref in seen:
            raise ValueError(f"circular reference: {ref}")
        if ref not in tokens:
            raise KeyError(ref)
        return resolve(tokens[ref]["$value"], tokens, seen | {ref})
    if isinstance(value, dict):
        return {k: resolve(v, tokens, seen) for k, v in cast(dict[str, object], value).items()}
    if isinstance(value, list):
        return [resolve(v, tokens, seen) for v in cast(list[object], value)]
    return value


def hex_of(name: str, tokens: Tokens) -> str | None:
    if name not in tokens:
        return None
    value = resolve(tokens[name]["$value"], tokens)
    return value if isinstance(value, str) and HEX6.match(value) else None


def luminance(hex6: str) -> float:
    def chan(c: int) -> float:
        x = c / 255.0
        return x / 12.92 if x <= 0.04045 else ((x + 0.055) / 1.055) ** 2.4

    r, g, b = (int(hex6[i : i + 2], 16) for i in (1, 3, 5))
    return 0.2126 * chan(r) + 0.7152 * chan(g) + 0.0722 * chan(b)


def contrast(a: str, b: str) -> float:
    la, lb = luminance(a), luminance(b)
    return (max(la, lb) + 0.05) / (min(la, lb) + 0.05)


def registered_pairs() -> set[tuple[str, str]]:
    text = PAIRS_MJS.read_text(encoding="utf-8")
    return set(re.findall(r'fg:\s*"([^"]+)",\s*bg:\s*"([^"]+)"', text))


def encodings_has_estimated() -> bool:
    data = cast(dict[str, object], json.loads(ENCODINGS.read_text(encoding="utf-8")))
    return "estimated" in cast(dict[str, object], data.get("encodings", {}))


def measure(themes: dict[str, Tokens], reg: set[tuple[str, str]]) -> list[PairRow]:
    out: list[PairRow] = []
    for element, fg, bg, role, source in PAIRS:
        bar = BAR[role]
        ratios: dict[str, float | None] = {}
        fails: list[str] = []
        for theme in THEME_ORDER:
            a, b = hex_of(fg, themes[theme]), hex_of(bg, themes[theme])
            exact = contrast(a, b) if a and b else None  # compared unrounded, as generate.mjs
            ratios[theme] = None if exact is None else round(exact, 4)
            gated_here = role in GATED and (role != "hc-text" or theme == "high-contrast")
            if gated_here and bar is not None and (exact is None or exact < bar):
                fails.append(theme)
        if role == "decorative":
            low = [t for t in THEME_ORDER if (ratios[t] or 0) < NON_TEXT_BAR]
            below = "; below 3:1 in " + ", ".join(low) if low else ""
            verdict = f"decorative (reported{below})"
        elif role.startswith("rejected"):
            low = [t for t in THEME_ORDER if bar is not None and (ratios[t] or 0) < bar]
            verdict = "rejected: fails " + ", ".join(low) if low else "rejected: passes, not used"
        else:
            verdict = "PASS" if not fails else "FAIL " + ", ".join(fails)
        out.append(
            {
                "element": element,
                "fg": fg,
                "bg": bg,
                "role": role,
                "bar": bar,
                "ratios": ratios,
                "verdict": verdict,
                "registered": (fg, bg) in reg,
                "source": source,
            }
        )
    return out


def bindings(themes: dict[str, Tokens]) -> list[TokenRow]:
    out: list[TokenRow] = []
    for name, bound_by in BINDINGS:
        values: dict[str, str] = {}
        for theme in THEME_ORDER:
            tokens = themes[theme]
            if name in tokens:
                resolved = resolve(tokens[name]["$value"], tokens)
                values[theme] = json.dumps(resolved, separators=(",", ":"))
        if not values:
            status = "MISSING"
        elif name in PRIMITIVE_ONLY:
            status = "primitive (alias elevation.card)"
        else:
            status = "resolved"
        out.append({"token": name, "bound_by": bound_by, "status": status, "values": values})
    return out


def dimension(name: str, tokens: Tokens) -> str:
    if name not in tokens:
        return "MISSING"
    value = resolve(tokens[name]["$value"], tokens)
    unit = " px" if str(tokens[name].get("$type")) in PX_TYPES else ""
    return f"{value}{unit}" if isinstance(value, str) else json.dumps(value)


def fmt(ratio: float | None) -> str:
    """Two decimals; four when the two-decimal form would land exactly on a bar."""
    if ratio is None:
        return "n/a"
    if round(ratio, 2) in BARS and round(ratio, 2) != round(ratio, 4):
        return f"{ratio:.4f}"
    return f"{ratio:.2f}"


def counts(pairs: list[PairRow], tokens: list[TokenRow]) -> dict[str, int]:
    gated = [p for p in pairs if p["role"] in GATED]
    distinct = {(p["fg"], p["bg"]) for p in gated}
    proposed = {(p["fg"], p["bg"]) for p in gated if not p["registered"]}
    return {
        "components": len(VARIANTS),
        "confirmations": 1,
        "boards": 9,
        "badge_variants": len(VARIANTS["CMP-227"]),
        "badge_sizes": 2,
        "variants_total": sum(len(v) for v in VARIANTS.values()),
        "states_total": sum(len(v) for v in STATES.values()),
        "stories_total": sum(len(v) for v in STORIES.values()),
        "story_groups": len(STORIES),
        "pairs_rows": len(pairs),
        "pairs_gated": len(gated),
        "pairs_distinct": len(distinct),
        "pairs_registered": len(distinct) - len(proposed),
        "pairs_proposed": len(proposed),
        "pairs_failing": sum(1 for p in gated if p["verdict"] != "PASS"),
        "pairs_decorative": sum(1 for p in pairs if p["role"] == "decorative"),
        "tokens_bound": sum(1 for t in tokens if t["status"] == "resolved"),
        "tokens_missing": sum(1 for t in tokens if t["status"] == "MISSING"),
        "themes": len(THEME_ORDER),
        "hit_target_px": 24,
        "gap_px": 4,
        "chip_max_chars": 40,
    }


def print_markdown(
    pairs: list[PairRow],
    tokens: list[TokenRow],
    dims: dict[str, str],
    nums: dict[str, int],
    proposed: list[tuple[str, str]],
    reg_count: int,
) -> None:
    print("# E25-D05 token audit (packages/ui/tokens; WCAG 2.x; ratios to the hundredth)\n")
    print("## 1. Contrast matrix\n")
    print("| Element | fg | bg | role | bar | dark | light | hc | verdict | pairs.mjs | source |")
    print("| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |")
    for p in pairs:
        bar = "-" if p["bar"] is None else f"{p['bar']:g}:1"
        reg = "registered" if p["registered"] else ("PROPOSED" if p["role"] in GATED else "-")
        r = p["ratios"]
        cells = [
            p["element"],
            f"`{p['fg']}`",
            f"`{p['bg']}`",
            p["role"],
            bar,
            fmt(r["dark"]),
            fmt(r["light"]),
            fmt(r["high-contrast"]),
            p["verdict"],
            reg,
            p["source"],
        ]
        print("| " + " | ".join(cells) + " |")
    print("\n## 2. Token bindings\n")
    print("| Token | Bound by | Status | dark | light | hc |")
    print("| --- | --- | --- | --- | --- | --- |")
    for t in tokens:
        v = t["values"]
        cells = [f"`{t['token']}`", t["bound_by"], t["status"]]
        cells += [v.get(theme, "-") for theme in THEME_ORDER]
        print("| " + " | ".join(cells) + " |")
    for pid in PATTERN_IDS:
        where = "pattern registry id (26 section 10; E11-D02 CR-6)"
        print(f"| `{pid}` | {where} | registry id, not a token | - | - | - |")
    print("\n## 3. Dimensions bound by the anatomy (identical in every theme)\n")
    print("| Token | Value |")
    print("| --- | --- |")
    for name, value in dims.items():
        print(f"| `{name}` | {value} |")
    print("\n## 4. pairs.mjs and encodings.json\n")
    listing = ", ".join(f"`{a}` on `{b}`" for a, b in proposed)
    print(f"- registered pairs scanned: {reg_count}; PROPOSED additions ({len(proposed)}):")
    print(f"  {listing}")
    print(f"- `encodings.json` has an `estimated` row: {encodings_has_estimated()}")
    print("\n## 5. Counts the boards quote\n")
    for key, number in nums.items():
        print(f"- {key}: {number}")


def main(argv: list[str]) -> int:
    themes = {name: merged(files) for name, files in THEMES.items()}
    reg = registered_pairs()
    pairs = measure(themes, reg)
    tokens = bindings(themes)
    dims = {d: dimension(d, themes["dark"]) for d in DIMENSIONS}
    nums = counts(pairs, tokens)
    proposed = sorted(
        {(p["fg"], p["bg"]) for p in pairs if p["role"] in GATED and not p["registered"]}
    )
    failing = [p for p in pairs if p["role"] in GATED and p["verdict"] != "PASS"]
    if "--json" in argv:
        out = {
            "pairs": pairs,
            "tokens": tokens,
            "dimensions": dims,
            "counts": nums,
            "proposed_pairs": [list(p) for p in proposed],
            "encodings_has_estimated": encodings_has_estimated(),
            "variants": VARIANTS,
            "states": STATES,
            "stories": STORIES,
            "pattern_ids": list(PATTERN_IDS),
        }
        print(json.dumps(out, indent=2, ensure_ascii=False))
        return 1 if failing else 0
    print_markdown(pairs, tokens, dims, nums, proposed, len(reg))
    print("\n## 6. Verdict\n")
    if failing:
        print("FAIL: " + "; ".join(f"{p['fg']} on {p['bg']} ({p['verdict']})" for p in failing))
        return 1
    gated, themes_n, missing = nums["pairs_gated"], nums["themes"], nums["tokens_missing"]
    deco = nums["pairs_decorative"]
    print(
        f"OK: {gated} gated rows over {themes_n} themes pass (unrounded compare); "
        f"{missing} names MISSING (expected); {deco} decorative rows reported"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
