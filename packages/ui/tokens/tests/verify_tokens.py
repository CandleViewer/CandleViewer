"""Token proof verification for E05-D01 (design-system foundations).

Pure-stdlib (no numpy/PIL). Verifies, over the DTCG token JSON in
packages/ui/tokens/, the acceptance criteria from the ticket's Gherkin:

  1. Every Tier-2 semantic colour token resolves in all 3 modes
     (dark, light, high-contrast) with no unset/dangling reference.
  2. Naming matches code exactly (token key == code token name; enforced
     structurally, since both sides read the same JSON file).
  3. Light is tuned, not inverted (spot-checks candle/buy/sell hex values
     differ from a naive lightness inversion of the dark value).
  4. `color.status.danger.default` and `color.sell.default` are visibly
     distinct (CIE76 dE) in every mode; so are danger's rest fill and
     `color.sell.hover`, `color.status.danger.strong`, `.warning.default` and
     `.warning.strong` (#3896).
  5. #3896: the label-on-fill matrix of `tools/contrast/label-on-fill.json`
     (its `$comment` states the rules) holds in every mode, and its thresholds
     stay at or past `LABEL_ON_FILL_FLOORS`. A matrix token that does not resolve
     to an opaque hex colour fails each check that reads it; the other checks
     still report. The CI gate for the same registry is
     `packages/ui/test/contrast/label-on-fill.test.ts`, which also checks the
     labels in every chart colour mode.

Run: python packages/ui/tokens/tests/verify_tokens.py
Exit code 0 = pass, 1 = fail (see stderr for details).
"""
from __future__ import annotations

import json
import math
import re
import sys
from collections.abc import Callable
from pathlib import Path

TOKENS_DIR = Path(__file__).resolve().parent.parent
LABEL_ON_FILL = TOKENS_DIR.parents[2] / "tools" / "contrast" / "label-on-fill.json"
HEX6 = re.compile(r"#[0-9A-Fa-f]{6}")
# #3896: the floors the matrix thresholds never go below: WCAG 2.2 SC 1.4.3 (label) and
# SC 1.4.11 (glyph, boundary), the ticket's 5 L* state step, and the high-contrast ring's
# 20 dE76; `stateHue` is a ceiling (10 degrees). A registry-only edit cannot lower one.
LABEL_ON_FILL_FLOORS = {
    "label": 4.5,
    "glyph": 3,
    "boundary": 3,
    "stateLightness": 5,
    "ringDeltaE": 20,
}
LABEL_ON_FILL_HUE_CEILING = 10

PRIMITIVES = "primitives.tokens.json"
THEMES = {
    "dark": ["semantic-dark.tokens.json"],
    "light": ["semantic-dark.tokens.json", "semantic-light.tokens.json"],
    "high-contrast": ["semantic-dark.tokens.json", "semantic-hc.tokens.json"],
}


def load(name: str) -> dict:
    return json.loads((TOKENS_DIR / name).read_text(encoding="utf-8"))


def merged_set(files: list[str]) -> dict:
    """Later files override earlier ones (theme-set layering order)."""
    merged: dict = {}
    for f in files:
        merged.update(load(f))
    return merged


def resolve(value, all_tokens: dict, _seen: frozenset = frozenset()) -> object:
    """Resolve a DTCG `{token.path}` reference recursively."""
    if isinstance(value, str) and value.startswith("{") and value.endswith("}"):
        ref = value[1:-1]
        if ref in _seen:
            raise ValueError(f"circular reference: {ref}")
        if ref not in all_tokens:
            raise KeyError(f"unset variable: {ref}")
        return resolve(all_tokens[ref]["$value"], all_tokens, _seen | {ref})
    if isinstance(value, dict):
        return {k: resolve(v, all_tokens, _seen) for k, v in value.items()}
    if isinstance(value, list):
        return [resolve(v, all_tokens, _seen) for v in value]
    return value


def hex_to_rgb(h: str) -> tuple[int, int, int]:
    h = h.lstrip("#")[:6]
    return int(h[0:2], 16), int(h[2:4], 16), int(h[4:6], 16)


def relative_luminance(rgb: tuple[int, int, int]) -> float:
    def chan(c: int) -> float:
        c = c / 255.0
        return c / 12.92 if c <= 0.04045 else ((c + 0.055) / 1.055) ** 2.4

    r, g, b = rgb
    return 0.2126 * chan(r) + 0.7152 * chan(g) + 0.0722 * chan(b)


def contrast_ratio(hex_a: str, hex_b: str) -> float:
    la = relative_luminance(hex_to_rgb(hex_a))
    lb = relative_luminance(hex_to_rgb(hex_b))
    lighter, darker = max(la, lb), min(la, lb)
    return (lighter + 0.05) / (darker + 0.05)


def rgb_to_lab(rgb: tuple[int, int, int]) -> tuple[float, float, float]:
    def chan(c: int) -> float:
        c = c / 255.0
        return ((c + 0.055) / 1.055) ** 2.4 if c > 0.04045 else c / 12.92

    r, g, b = (chan(c) for c in rgb)
    x = (r * 0.4124 + g * 0.3576 + b * 0.1805) / 0.95047
    y = (r * 0.2126 + g * 0.7152 + b * 0.0722) / 1.0
    z = (r * 0.0193 + g * 0.1192 + b * 0.9505) / 1.08883

    def f(t: float) -> float:
        return t ** (1 / 3) if t > 0.008856 else (7.787 * t) + (16 / 116)

    fx, fy, fz = f(x), f(y), f(z)
    return (116 * fy) - 16, 500 * (fx - fy), 200 * (fy - fz)


def delta_e76(hex_a: str, hex_b: str) -> float:
    la, aa, ba = rgb_to_lab(hex_to_rgb(hex_a))
    lb, ab, bb = rgb_to_lab(hex_to_rgb(hex_b))
    return math.sqrt((la - lb) ** 2 + (aa - ab) ** 2 + (ba - bb) ** 2)


REQUIRED_TIER2_COLOUR_PREFIXES = (
    "color.text.",
    "color.surface.",
    "color.border.",
    "color.action.",
    "color.buy",
    "color.sell",
    "color.neutral",
    "color.status.",
    "color.env.",
    "color.focus.ring",
    "color.candle.",
    "color.footprint.",
    "color.profile.",
    "color.drawing.",
    "color.order.line",
    "color.position.",
    "color.node.",
    "color.heatmap.",
    "color.data-confidence.",
)

# E08-D04: data-confidence text/indicator pairs must clear AA contrast against
# their paired surface in every theme (WCAG 2.2 §1.4.3/1.4.11).
DATA_CONFIDENCE_STATES = (
    "live", "stale", "reconnecting", "disconnected",
    "resyncing", "gapped", "backfilling", "delisted",
)


def t3(x: float) -> str:
    """Truncated to three places, so a failing 2.9993 never prints as the 3 it misses."""
    return f"{math.floor(x * 1000) / 1000:.3f}"


def lab_hue(hex_: str) -> float:
    _, a, b = rgb_to_lab(hex_to_rgb(hex_))
    return math.degrees(math.atan2(b, a)) % 360


def over(fg: str, bg: str, alpha: float) -> str:
    """`fg` at `alpha` over opaque `bg`, mixed per sRGB channel and rounded half up, as painted."""
    mix = [
        math.floor(alpha * f + (1 - alpha) * b + 0.5)
        for f, b in zip(hex_to_rgb(fg), hex_to_rgb(bg), strict=True)
    ]
    return "#" + "".join(f"{c:02X}" for c in mix)


def label_on_fill_threshold_failures(t: dict) -> list[str]:
    """#3896: a registry threshold below its floor (or `stateHue` above its ceiling) fails."""
    out = [
        f"label-on-fill threshold {key} is {t.get(key)!r}, below the floor {floor}"
        for key, floor in LABEL_ON_FILL_FLOORS.items()
        if not (isinstance(t.get(key), (int, float)) and t[key] >= floor)
    ]
    hue = t.get("stateHue")
    if not (isinstance(hue, (int, float)) and hue <= LABEL_ON_FILL_HUE_CEILING):
        limit = LABEL_ON_FILL_HUE_CEILING
        out.append(f"label-on-fill threshold stateHue is {hue!r}, above {limit}")
    return out


def label_on_fill_failures(theme: str, tokens: dict) -> list[str]:
    """#3896: the label-on-fill matrix of tools/contrast/label-on-fill.json for one theme."""
    reg = json.loads(LABEL_ON_FILL.read_text(encoding="utf-8"))
    t = reg["thresholds"]
    out: list[str] = []

    def hx(name: str) -> str:
        value = tokens.get(name)
        if not (isinstance(value, str) and HEX6.fullmatch(value)):
            raise KeyError(f"[{theme}] label-on-fill: {name} is not an opaque hex colour")
        return value

    def guarded(check: Callable[..., None]) -> Callable[..., None]:
        """A check whose token does not resolve fails once, by name; the other checks still run."""

        def run(*args: object) -> None:
            try:
                check(*args)
            except KeyError as exc:
                if exc.args[0] not in out:
                    out.append(exc.args[0])

        return run

    def lightness(name: str) -> float:
        return rgb_to_lab(hex_to_rgb(hx(name)))[0]

    @guarded
    def pair(fg: str, bg: str, minimum: float, what: str) -> None:
        cr = contrast_ratio(hx(fg), hx(bg))
        if cr < minimum:
            out.append(f"[{theme}] {what}: {fg} on {bg} {t3(cr)} < {minimum}")

    @guarded
    def apart(role: str, a: str, b: str) -> None:
        d = abs(lightness(a) - lightness(b))
        if d < t["stateLightness"]:
            out.append(f"[{theme}] {role}: {a} vs {b} dL* {t3(d)} < {t['stateLightness']}")

    @guarded
    def same_hue(role: str, fill: str, rest: str) -> None:
        gap = abs((lab_hue(hx(fill)) - lab_hue(hx(rest)) + 540) % 360 - 180)
        if gap > t["stateHue"]:
            out.append(f"[{theme}] {role}: {fill} hue {t3(gap)} deg from rest > {t['stateHue']}")

    @guarded
    def gated_pair(role: str, rest: str, surface: str, fg: str, minimum: float, what: str) -> None:
        cr = contrast_ratio(hx(fg), over(hx(rest), hx(surface), alpha))
        if cr < minimum:
            out.append(
                f"[{theme}] gated {role} {what}: {fg} on {rest} at {alpha} over "
                f"{surface} {t3(cr)} < {minimum}"
            )

    @guarded
    def ring_apart(ring: str, fill: str) -> None:
        d = delta_e76(hx(ring), hx(fill))
        if d < t["ringDeltaE"]:
            out.append(f"[{theme}] {ring} vs {fill} dE76 {t3(d)} < {t['ringDeltaE']}")

    gated = reg["disabledWithReason"]["gated"]
    try:
        alpha = float(tokens.get(gated["opacity"], "nan"))
    except (TypeError, ValueError):
        alpha = math.nan
    if not 0 < alpha <= 1:  # the gated composites cannot run; every other check still does
        out.append(f"[{theme}] label-on-fill: {gated['opacity']} is not an opacity in (0, 1]")

    for role, r in reg["roles"].items():
        states = r["states"]
        rest = states["default"]
        for state, fill in states.items():
            pair(r["label"], fill, t["label"], f"{role}.{state} label")
        fills = list(states.values())
        for i, a in enumerate(fills):
            for b in fills[i + 1 :]:
                apart(role, a, b)
        for other in r.get("distinctFrom", []):
            apart(role, rest, other)
        if r["hue"]:
            for fill in fills:
                same_hue(role, fill, rest)
        if r["boundary"]:
            for surface in reg["surfaces"]:
                pair(rest, surface, t["boundary"], f"{role} rest boundary")
        if "outline" in r:
            for bg in [*reg["surfaces"], *fills]:
                pair(r["outline"], bg, t["boundary"], f"{role} outline")
        # Disabled with reason: the label and glyph stay at full opacity on the dimmed rest fill.
        if 0 < alpha <= 1:
            for surface in reg["surfaces"]:
                gated_pair(role, rest, surface, gated["label"], t["label"], "label")
                gated_pair(role, rest, surface, gated["glyph"], t["glyph"], "locked glyph")
        prefix = rest.removesuffix("default") if rest.endswith(".default") else rest + "."
        for suffix in reg["stateSuffixes"]:
            if prefix + suffix in tokens and prefix + suffix not in fills:
                out.append(f"[{theme}] {role}: {prefix + suffix} is not in {LABEL_ON_FILL.name}")
    for fg, bg in reg["disabledWithReason"]["text"]:
        pair(fg, bg, t["label"], "reason text")
    for fg, bg in reg["disabledWithReason"]["glyph"]:
        pair(fg, bg, t["glyph"], "ghost locked glyph")
    ring = reg["focusRing"]
    for surface in ring["surfaces"]:
        pair(ring["ring"], surface, t["boundary"], "focus ring")
    if theme in ring["distinctThemes"]:
        for fill in ring["distinctFrom"]:
            ring_apart(ring["ring"], fill)
    return out


def main() -> int:
    failures: list[str] = []
    primitives = load(PRIMITIVES)

    resolved_by_theme: dict[str, dict] = {}
    for theme, files in THEMES.items():
        all_tokens = {**primitives, **merged_set(files)}
        resolved: dict[str, object] = {}
        for name, entry in all_tokens.items():
            try:
                resolved[name] = resolve(entry["$value"], all_tokens)
            except (KeyError, ValueError) as exc:
                failures.append(f"[{theme}] {name}: {exc}")
        resolved_by_theme[theme] = resolved

    # 1. every colour-ish semantic token must resolve (already enforced above)
    #    plus: must exist identically (same key set) across all 3 themes.
    dark_keys = {k for k in resolved_by_theme["dark"] if k.startswith("color.")}
    for theme in ("light", "high-contrast"):
        missing = dark_keys - set(resolved_by_theme[theme])
        if missing:
            failures.append(f"[{theme}] missing keys present in dark: {sorted(missing)[:5]}")

    # 3. light is tuned, not inverted: spot-check candle/buy/sell hexes differ
    #    from dark AND are not a naive value-inversion of the dark hex.
    for key in ("color.candle.up", "color.candle.down", "color.buy.default", "color.sell.default"):
        dark_hex = resolved_by_theme["dark"][key]
        light_hex = resolved_by_theme["light"][key]
        if dark_hex == light_hex:
            failures.append(f"light theme did not retune {key} (identical to dark)")
        inv = "#" + "".join(f"{255 - c:02X}" for c in hex_to_rgb(dark_hex))
        if light_hex.upper() == inv:
            failures.append(f"light theme value for {key} is a naive inversion of dark")

    # 4. danger vs sell hue separation, every mode
    for theme in THEMES:
        danger = resolved_by_theme[theme]["color.status.danger.default"]
        sell = resolved_by_theme[theme]["color.sell.default"]
        de = delta_e76(danger, sell)
        if de < 8.0:
            failures.append(f"[{theme}] danger/sell hues too close (dE76={de:.2f} < 8.0): {danger} vs {sell}")
        # #3896 (E05-D02 A6): danger's rest fill is never the hovered sell fill or a warning
        # colour, and the liquidation-intensity ramp from it to danger.strong keeps a visible step.
        for other in (
            "color.sell.hover",
            "color.status.danger.strong",
            "color.status.warning.default",
            "color.status.warning.strong",
        ):
            de = delta_e76(danger, resolved_by_theme[theme][other])
            if de < 8.0:
                failures.append(f"[{theme}] danger.default vs {other} dE76={de:.2f} < 8.0")

    # focus ring contrast >=3:1 against every surface tier, every theme
    surfaces = ("color.surface.app", "color.surface.canvas", "color.surface.raised", "color.surface.overlay")
    for theme in THEMES:
        ring = resolved_by_theme[theme]["color.focus.ring"]
        for surf in surfaces:
            cr = contrast_ratio(ring, resolved_by_theme[theme][surf])
            if cr < 3.0:
                failures.append(f"[{theme}] focus.ring vs {surf} contrast {cr:.2f} < 3.0")

    # primary text contrast >=4.5:1 on its intended surfaces
    for theme in THEMES:
        text = resolved_by_theme[theme]["color.text.primary"]
        for surf in ("color.surface.app", "color.surface.canvas"):
            cr = contrast_ratio(text, resolved_by_theme[theme][surf])
            if cr < 4.5:
                failures.append(f"[{theme}] text.primary vs {surf} contrast {cr:.2f} < 4.5")

    # E08-D04: every data-confidence text/indicator pair clears AA against its
    # own surface (text.*.surface where defined, else the ambient app surface),
    # and every indicator clears the non-text 3:1 minimum against that surface.
    for theme in THEMES:
        tokens = resolved_by_theme[theme]
        ambient = tokens["color.surface.app"]
        for state in DATA_CONFIDENCE_STATES:
            text_key = f"color.data-confidence.{state}.text"
            indicator_key = f"color.data-confidence.{state}.indicator"
            surface_key = f"color.data-confidence.{state}.surface"
            if text_key not in tokens:
                failures.append(f"[{theme}] missing {text_key}")
                continue
            surf = tokens.get(surface_key, ambient)
            text_cr = contrast_ratio(tokens[text_key], surf)
            if text_cr < 4.5:
                failures.append(
                    f"[{theme}] {text_key} vs {surface_key if surface_key in tokens else 'ambient'} "
                    f"contrast {text_cr:.2f} < 4.5"
                )
            if indicator_key in tokens:
                ind_cr = contrast_ratio(tokens[indicator_key], surf)
                if ind_cr < 3.0:
                    failures.append(f"[{theme}] {indicator_key} vs surface contrast {ind_cr:.2f} < 3.0")

    # 5. #3896: label-on-fill matrix (tools/contrast/label-on-fill.json), every theme. A matrix
    # token that is missing or not a colour fails each check that reads it, never skips one.
    registry = json.loads(LABEL_ON_FILL.read_text(encoding="utf-8"))
    failures.extend(label_on_fill_threshold_failures(registry["thresholds"]))
    for theme in THEMES:
        failures.extend(label_on_fill_failures(theme, resolved_by_theme[theme]))

    if failures:
        for f in failures:
            print(f"FAIL: {f}", file=sys.stderr)
        print(f"\n{len(failures)} failure(s).", file=sys.stderr)
        return 1

    total_tokens = sum(len(r) for r in resolved_by_theme.values())
    print(f"OK: 3 themes resolved, {total_tokens} token instances, zero unset variables, all contrast checks pass.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
