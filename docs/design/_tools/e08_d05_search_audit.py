"""E08-D05 symbol-search audit: WCAG contrast matrix + CVD simulation over the real token JSON.

Standalone, offline, stdlib only. Resolves the `dark`, `light` and `high-contrast` themes exactly as
`packages/ui/tokens/tests/verify_tokens.py` does (same loader, alias resolution and theme layering),
measures every foreground/background pair that `docs/design/E08/E08-D05.md` binds for SCR-102 (symbol
search) and SCR-041 (quick-switcher), and simulates protanopia, deuteranopia and tritanopia over the
state colours with the Brettel/Vienot projection of `docs/research/_tools/cvd_simulate.py`. The ratio
is `contrast_ratio()` from `docs/design/_tools/contrast_check.py` (imported, not re-implemented).

Usage: python3 -I docs/design/_tools/e08_d05_search_audit.py   (prints Markdown; exit 1 on a FAIL)

Bars (05 §5 items 1, 2 and 6): `text` 4.5:1 and `non-text` 3:1 in every theme; `hc-text` 7:1 in the
high-contrast theme only. `rejected-*` rows are pairs the spec measured and designed around, and
`decorative` rows carry no meaning (the words or a shape carry it): both are reported, never gated.
`CR:` names a design-system change request: it is measured on the existing token it would alias,
never on an invented value.
"""
from __future__ import annotations

import importlib.util
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
TOKENS = ROOT / "packages" / "ui" / "tokens"


def _load(path: Path, name: str):
    spec = importlib.util.spec_from_file_location(name, path)
    mod = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(mod)
    return mod


verify = _load(TOKENS / "tests" / "verify_tokens.py", "verify_tokens")
contrast_check = _load(ROOT / "docs" / "design" / "_tools" / "contrast_check.py", "contrast_check")
cvd = _load(ROOT / "docs" / "research" / "_tools" / "cvd_simulate.py", "cvd_simulate")

THEMES = ("dark", "light", "high-contrast")
BAR = {"text": 4.5, "non-text": 3.0, "hc-text": 7.0, "decorative": None,
       "rejected-text": 4.5, "rejected-non-text": 3.0}


def resolve_theme(name: str) -> dict[str, str]:
    allt = dict(verify.load(verify.PRIMITIVES))
    allt.update(verify.merged_set(verify.THEMES[name]))
    return {k: verify.resolve(v["$value"], allt) for k, v in allt.items() if v.get("$type") == "color"}


T = {n: resolve_theme(n) for n in THEMES}
# Change requests, measured on the token each would alias (same in every theme).
CR = {"CR:color.border.input": "color.text.tertiary"}  # E30-D02 CR-1, shared, not re-requested


def col(theme: str, token: str) -> str:
    return T[theme][CR.get(token, token)]


def rgb(h: str) -> tuple[int, int, int]:
    h = h.lstrip("#")
    return int(h[0:2], 16), int(h[2:4], 16), int(h[4:6], 16)


def ratio(fg: str, bg: str) -> float:
    return contrast_check.contrast_ratio(rgb(fg), rgb(bg))


OV, SEL, HOV = "color.surface.overlay", "color.surface.selected", "color.surface.hover"
# (element, fg token, bg token, role). The dialog (CMP-043) and popover surface is surface.overlay.
PAIRS: list[tuple[str, str, str, str]] = [
    ("matched symbol characters (semibold); idle symbol; metadata numbers; state heading", "color.text.primary", OV, "text"),
    ("unmatched symbol characters (regular); base / quote; status sentences; footer", "color.text.secondary", OV, "text"),
    ("matched characters on the active option", "color.text.primary", SEL, "text"),
    ("unmatched characters, base / quote on the active option", "color.text.secondary", SEL, "text"),
    ("matched characters on a hovered option", "color.text.primary", HOV, "text"),
    ("unmatched characters on a hovered option", "color.text.secondary", HOV, "text"),
    ("group header (Recent, Favourites); column captions; T2 menu label", "color.text.tertiary", OV, "text"),
    ("text.tertiary on the active option: never used there", "color.text.tertiary", SEL, "rejected-text"),
    ("input value (mono)", "color.text.primary", "color.surface.app", "text"),
    ("input placeholder 'Search symbols'", "color.text.tertiary", "color.surface.app", "text"),
    ("recording chips; target chip; Kbd label", "color.text.secondary", "color.surface.raised", "text"),
    ("Kbd glyph text (CMP-022)", "color.text.primary", "color.surface.raised", "text"),
    ("delisted symbol (struck) and its chip word", "color.data-confidence.delisted.text", OV, "text"),
    ("delisted symbol on the active option", "color.data-confidence.delisted.text", SEL, "text"),
    ("links: Clear search, View symbol info", "color.text.link", OV, "text"),
    ("links on the active option row", "color.text.link", SEL, "text"),
    ("primary button label (Retry now)", "color.text.on-action", "color.action.primary.default", "text"),
    ("secondary button label (Refresh from Bybit)", "color.text.primary", "color.action.secondary.default", "text"),
    ("ARMED target pill text (E30-D02 D15 pill)", "color.text.primary", "color.status.warning.subtle", "text"),
    ("checked interval in the SCR-041 strip", "color.text.primary", "color.action.selected", "text"),
    ("HC stretch: symbol text on the surface", "color.text.primary", OV, "hc-text"),
    ("HC stretch: secondary text on the surface", "color.text.secondary", OV, "hc-text"),
    ("HC stretch: secondary text on the active option", "color.text.secondary", SEL, "hc-text"),
    ("active option left bar 2 px vs the active fill", "color.border.selected", SEL, "non-text"),
    ("active option left bar 2 px vs the surface", "color.border.selected", OV, "non-text"),
    ("focus ring (input, menu items, buttons) on the surface", "color.focus.ring", OV, "non-text"),
    ("focus ring on the checked interval", "color.focus.ring", "color.action.selected", "non-text"),
    ("input boundary at rest: adopted CR-1 color.border.input", "CR:color.border.input", OV, "non-text"),
    ("input boundary at rest: border.default", "color.border.default", OV, "rejected-non-text"),
    ("input boundary at rest: border.strong", "color.border.strong", OV, "rejected-non-text"),
    ("delisted glyph (CMP-239) on the surface", "color.data-confidence.delisted.indicator", OV, "non-text"),
    ("delisted glyph on the active option", "color.data-confidence.delisted.indicator", SEL, "non-text"),
    ("stale-list glyph in the footer notice", "color.data-confidence.stale.indicator", OV, "non-text"),
    ("load-failed glyph (CMP-026 error)", "color.status.danger.strong", OV, "non-text"),
    ("ARMED pill glyph", "color.status.warning.strong", "color.status.warning.subtle", "non-text"),
    ("checked interval 2 px inner outline vs its fill", "color.border.selected", "color.action.selected", "non-text"),
    ("primary button fill vs the surface", "color.action.primary.default", OV, "non-text"),
    ("tone step matched vs unmatched (weight 600 / 400 carries it)", "color.text.primary", "color.text.secondary", "decorative"),
    ("active option fill vs the surface (the bar carries it)", SEL, OV, "decorative"),
    ("hover fill vs the surface (1.00 in light: CR, section D)", HOV, OV, "decorative"),
    ("skeleton bar (CR color.surface.skeleton) vs the surface", SEL, OV, "decorative"),
    ("chip fill vs the surface (the word carries it)", "color.surface.raised", OV, "decorative"),
]

# Colours that must stay apart without their words (ΔE76 >= 5.0, the tools/contrast JND floor).
CVD_PAIRS: list[tuple[str, str, str]] = [
    ("delisted glyph vs stale glyph (never on one row: precedence)", "color.data-confidence.delisted.indicator", "color.data-confidence.stale.indicator"),
    ("ARMED glyph vs delisted glyph", "color.status.warning.strong", "color.data-confidence.delisted.indicator"),
    ("active option bar vs focus ring", "color.border.selected", "color.focus.ring"),
    ("checked interval fill vs active option fill", "color.action.selected", SEL),
    ("load-failed glyph vs stale glyph", "color.status.danger.strong", "color.data-confidence.stale.indicator"),
]
JND = 5.0

# Tokens a catalogue entry or this spec needs that do not exist: design-system change requests (16 §11.3).
MISSING = [
    ("color.text.accent", "CMP-213 Tokens field", "dropped: highlight is weight + tone (text.primary 600 / text.secondary 400)"),
    ("color.chip.*", "CMP-011 Tokens field", "color.surface.raised fill + color.text.secondary word"),
    ("color.surface.skeleton, motion.shimmer", "CMP-015 / CMP-029 Tokens", "color.surface.selected bars, static (no shimmer exists)"),
    ("color.surface.scrim", "CMP-077; the SCR-102 scrim", "color.surface.sunken at opacity.scrim (0.6)"),
    ("color.border.input", "E30-D02 CR-1 (shared)", "measured above as CR:color.border.input = color.text.tertiary"),
    ("space.emptystate.*", "CMP-026 Tokens field", "space.inset.md padding, space.stack.sm gaps"),
    ("font.mono", "CMP-022 / CMP-219 / CMP-220 Tokens", "the token is font.family.mono (a naming fix)"),
    ("color.surface.hover (light value)", "the row hover (= surface.overlay in light)", "in light, until the CR lands: color.surface.selected, no bar"),
]


def main() -> int:
    failed = 0
    print("## A. Contrast matrix (ratio per theme; bar per role)\n")
    print("| Element | fg | bg | role | dark | light | hc | verdict |")
    print("|---|---|---|---|---|---|---|---|")
    for element, fg, bg, role in PAIRS:
        vals = [ratio(col(t, fg), col(t, bg)) for t in THEMES]
        bar = BAR[role]
        if bar is None:
            verdict = "decorative (not gated)"
        else:
            gated = [2] if role == "hc-text" else [0, 1, 2]
            bad = [THEMES[i] for i in gated if vals[i] < bar]
            verdict = "PASS" if not bad else "FAIL: " + ", ".join(bad)
            if role.startswith("rejected"):
                verdict = "rejected by design" + (" (" + verdict + ")" if bad else " (passes; not used)")
            elif bad:
                failed += 1
        cells = " | ".join(f"{v:.2f}" for v in vals)
        print(f"| {element} | `{fg}` | `{bg}` | {role} | {cells} | {verdict} |")

    print("\n## B. Resolved values used above\n")
    print("| token | dark | light | hc |")
    print("|---|---|---|---|")
    seen: list[str] = []
    for _, fg, bg, _ in PAIRS:
        seen += [t for t in (fg, bg) if t not in seen]
    for tok in seen:
        print(f"| `{tok}` | " + " | ".join(col(t, tok) for t in THEMES) + " |")

    print("\n## C. CVD simulation (ΔE76 under each deficiency; JND floor 5.0)\n")
    print("| Pair | theme | normal | protan | deutan | tritan | verdict |")
    print("|---|---|---|---|---|---|---|")
    for name, a, b in CVD_PAIRS:
        for t in THEMES:
            ha, hb = col(t, a), col(t, b)
            d = [cvd.delta_e76(ha, hb)] + [
                cvd.delta_e76(cvd.simulate(ha, k), cvd.simulate(hb, k))
                for k in ("protanopia", "deuteranopia", "tritanopia")
            ]
            verdict = "distinct" if min(d) >= JND else "COLLAPSES (words or shape carry it)"
            print(f"| {name} | {t} | " + " | ".join(f"{x:.1f}" for x in d) + f" | {verdict} |")

    print("\n## D. Missing tokens (design-system change requests; never invented here)\n")
    print("| Name | Cited by | Bound meanwhile |")
    print("|---|---|---|")
    for name, where, meanwhile in MISSING:
        print(f"| `{name}` | {where} | {meanwhile} |")

    print(f"\nFAIL count (gated rows only): {failed}")
    return 1 if failed else 0


if __name__ == "__main__":
    raise SystemExit(main())
