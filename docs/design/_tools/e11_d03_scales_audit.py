"""E11-D03 scale menus / Scales tab / go-to-date audit: WCAG contrast matrix + CVD simulation.

Standalone, offline, stdlib only. Resolves every theme (`dark`, `light`, `high-contrast`) exactly as
`packages/ui/tokens/tests/verify_tokens.py` does (same loader, same alias resolution, same theme
layering from `themes.json`), measures every foreground/background pair the spec
(`docs/design/E11/E11-D03.md`) binds for SCR-043, SCR-044, the SCR-031 Scales tab and the
scale-lock badge, and simulates deuteranopia, protanopia and tritanopia over every state colour with
the Brettel/Vienot projection of `docs/research/_tools/cvd_simulate.py`. The contrast formula is
`contrast_ratio()` from `docs/design/_tools/contrast_check.py` (imported, not reimplemented), so the
numbers agree with E11-D02's, E30-D01's and E09-D03's.

Usage: python3 -I docs/design/_tools/e11_d03_scales_audit.py   (prints Markdown; exit 1 on a FAIL)
Stdout is forced to UTF-8 (the tables carry `ΔE`, `≥`, `—`), so it also runs on a cp1252 console.

Roles and bars: `text` 4.5:1 in every theme AND 7:1 in the high-contrast column (`05` §5 item 6 —
the high-contrast theme's AAA-leaning bar, applied to every text row, not only to rows marked
`hc-text`), `non-text` 3:1. `disabled` rows are the label of a disabled control
(WCAG 1.4.3 exempts inactive components) — reported, never gated; the inline REASON attached to a
disabled item is a `text` row and IS gated, because the explanation is not a control. `decorative`
rows carry no meaning (`16-design-system-brief.md` §6 rule 7); `rejected-*` rows are pairs the spec
considered and designed around — both reported, never gated. Candidate tokens that do not exist yet
(design-system change requests for E11-D05) are prefixed `CR:` and measured on the existing token or
primitive they would alias, never on an invented hex.
"""

from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
TOKENS = ROOT / "packages" / "ui" / "tokens"


def _load(path: Path, name: str):
    spec = importlib.util.spec_from_file_location(name, path)
    mod = importlib.util.module_from_spec(spec)
    if spec is None or spec.loader is None:
        raise ImportError(str(path))
    spec.loader.exec_module(mod)
    return mod


sys.path.insert(0, str(TOKENS / "tests"))
verify = _load(TOKENS / "tests" / "verify_tokens.py", "verify_tokens")
contrast_check = _load(ROOT / "docs" / "design" / "_tools" / "contrast_check.py", "contrast_check")
cvd = _load(ROOT / "docs" / "research" / "_tools" / "cvd_simulate.py", "cvd_simulate")

THEMES = ("dark", "light", "high-contrast")
HC_TEXT_BAR = (
    7.0  # 05 §5 item 6: the high-contrast theme's body-text bar, applied to every `text` row
)
BAR: dict[str, float | None] = {
    "text": 4.5,
    "non-text": 3.0,
    "hc-text": 7.0,
    "disabled": None,
    "decorative": None,
    "rejected-text": 4.5,
    "rejected-non-text": 3.0,
}


def hex_to_rgb(h: str) -> tuple[int, int, int]:
    h = h.lstrip("#")
    return int(h[0:2], 16), int(h[2:4], 16), int(h[4:6], 16)


def ratio(fg: str, bg: str) -> float:
    return contrast_check.contrast_ratio(hex_to_rgb(fg), hex_to_rgb(bg))


def resolve_theme(name: str) -> dict[str, str]:
    prim = verify.load(verify.PRIMITIVES)
    allt = dict(prim)
    allt.update(verify.merged_set(verify.THEMES[name]))
    return {
        k: verify.resolve(v["$value"], allt) for k, v in allt.items() if v.get("$type") == "color"
    }


T = {n: resolve_theme(n) for n in THEMES}

# Candidate aliases for the E11-D05 change requests (CR:). Values are existing tokens per theme.
CR = {
    # D03-CR-5: a field-boundary token for inputs on the overlay surface; aliases text.tertiary.
    "CR:color.border.field": {t: "color.text.tertiary" for t in THEMES},
    # D03-CR-7: a distinct light danger hue (light danger.strong == warning.strong today).
    "CR:color.status.danger.strong": {
        "dark": "color.status.danger.strong",
        "light": "palette.light.red.700",
        "high-contrast": "color.status.danger.strong",
    },
}


def col(theme: str, token: str) -> str:
    if token in CR:
        return T[theme][CR[token][theme]]
    return T[theme][token]


# (element, fg token, bg token, role)
PAIRS: list[tuple[str, str, str, str]] = [
    # --- SCR-043 menus (CMP-041 on color.surface.overlay) --------------------------------------
    ("menu item label (rest)", "color.text.primary", "color.surface.overlay", "text"),
    ("menu item label (hover / focused row)", "color.text.primary", "color.surface.hover", "text"),
    (
        "menu group heading (Scale mode / Scale / Bar spacing / Markers / Time zone)",
        "color.text.tertiary",
        "color.surface.overlay",
        "text",
    ),
    ("menu shortcut hint (CMP-022 Kbd)", "color.text.tertiary", "color.surface.overlay", "text"),
    (
        "menu checked glyph (radio dot / check)",
        "color.text.primary",
        "color.surface.overlay",
        "non-text",
    ),
    (
        "menu checked glyph on the focused row",
        "color.text.primary",
        "color.surface.hover",
        "non-text",
    ),
    (
        "disabled item label (Logarithmic, unavailable) — exempt",
        "color.text.disabled",
        "color.surface.overlay",
        "disabled",
    ),
    (
        "disabled item INLINE REASON — adopted (D4)",
        "color.text.secondary",
        "color.surface.overlay",
        "text",
    ),
    (
        "disabled item inline reason — REJECTED pair (text.disabled as the reason)",
        "color.text.disabled",
        "color.surface.overlay",
        "rejected-text",
    ),
    (
        "disabled item unavailable glyph (ⓘ) beside the reason",
        "color.text.secondary",
        "color.surface.overlay",
        "non-text",
    ),
    ("menu separator", "color.border.default", "color.surface.overlay", "decorative"),
    ("menu border on the canvas", "color.border.default", "color.surface.canvas", "decorative"),
    (
        "menu focus ring (CMP-039) on the overlay",
        "color.focus.ring",
        "color.surface.overlay",
        "non-text",
    ),
    ("menu focus ring on the hover fill", "color.focus.ring", "color.surface.hover", "non-text"),
    # --- scale-lock badge (CMP-188, DOM overlay on the canvas) -----------------------------------
    ("lock badge text — resting", "color.text.primary", "color.surface.raised", "text"),
    (
        "lock badge glyph (icon/lock) — resting, the ≥3:1 non-text carrier",
        "color.text.primary",
        "color.surface.raised",
        "non-text",
    ),
    ("lock badge text — hover", "color.text.primary", "color.surface.hover", "text"),
    ("lock badge text — active / pressed", "color.text.primary", "color.surface.selected", "text"),
    (
        "lock badge border on the canvas (reinforcement)",
        "color.border.strong",
        "color.surface.canvas",
        "decorative",
    ),
    ("lock badge focus ring on the canvas", "color.focus.ring", "color.surface.canvas", "non-text"),
    ("lock badge tooltip text", "color.text.primary", "color.surface.overlay", "text"),
    # --- SCR-044 go-to-date dialog (CMP-043 on color.surface.overlay) ----------------------------
    (
        "dialog title / body / input value text",
        "color.text.primary",
        "color.surface.overlay",
        "text",
    ),
    (
        "field label (Date, Time) and the twin-zone line",
        "color.text.secondary",
        "color.surface.overlay",
        "text",
    ),
    (
        "format hint / helper text (YYYY-MM-DD HH:MM, 24-hour)",
        "color.text.tertiary",
        "color.surface.overlay",
        "text",
    ),
    ("input value text on the input fill", "color.text.primary", "color.surface.app", "text"),
    (
        "input boundary — REJECTED pair (DS color.border.strong on the overlay)",
        "color.border.strong",
        "color.surface.overlay",
        "rejected-non-text",
    ),
    (
        "input boundary — adopted (D03-CR-5: CR:color.border.field = text.tertiary)",
        "CR:color.border.field",
        "color.surface.overlay",
        "non-text",
    ),
    ("input invalid boundary", "color.status.danger.strong", "color.surface.overlay", "non-text"),
    ("input focus ring", "color.focus.ring", "color.surface.overlay", "non-text"),
    (
        "error block text (before recorded history / after latest bar / invalid)",
        "color.text.primary",
        "color.status.danger.subtle",
        "text",
    ),
    ("error block icon", "color.status.danger.strong", "color.status.danger.subtle", "non-text"),
    (
        "error block text — REJECTED pair (danger.default as text)",
        "color.status.danger.default",
        "color.status.danger.subtle",
        "rejected-text",
    ),
    (
        "warning block text (no recorded data at the target)",
        "color.text.primary",
        "color.status.warning.subtle",
        "text",
    ),
    (
        "warning block icon",
        "color.status.warning.strong",
        "color.status.warning.subtle",
        "non-text",
    ),
    (
        "zone switch pressed segment text (UTC / Local)",
        "color.text.primary",
        "color.surface.selected",
        "text",
    ),
    ("zone switch pressed check glyph", "color.text.primary", "color.surface.selected", "non-text"),
    ("zone switch unpressed segment text", "color.text.secondary", "color.surface.raised", "text"),
    ("primary button text (Jump)", "color.text.on-action", "color.action.primary.default", "text"),
    (
        "primary button fill vs the overlay (component boundary)",
        "color.action.primary.default",
        "color.surface.overlay",
        "non-text",
    ),
    (
        "secondary button text (Cancel, quick jumps)",
        "color.text.primary",
        "color.action.secondary.default",
        "text",
    ),
    (
        "secondary button boundary on the overlay — REJECTED pair (fill alone)",
        "color.action.secondary.default",
        "color.surface.overlay",
        "rejected-non-text",
    ),
    (
        "secondary button boundary — adopted (1 px CR:color.border.field)",
        "CR:color.border.field",
        "color.surface.overlay",
        "non-text",
    ),
    (
        "quick jump disabled label — exempt",
        "color.text.disabled",
        "color.action.secondary.default",
        "disabled",
    ),
    (
        "quick jump disabled REASON (role-denied / empty / before history)",
        "color.text.secondary",
        "color.surface.overlay",
        "text",
    ),
    (
        "calendar selected day text (CMP-047)",
        "color.text.on-action",
        "color.action.primary.default",
        "text",
    ),
    ("calendar day text", "color.text.primary", "color.surface.overlay", "text"),
    (
        "calendar out-of-range day — exempt (before recording start)",
        "color.text.disabled",
        "color.surface.overlay",
        "disabled",
    ),
    (
        "feed-state chip in the dialog (Stale / Disconnected) text",
        "color.text.primary",
        "color.surface.raised",
        "text",
    ),
    # --- SCR-031 Scales tab (on color.surface.overlay) --------------------------------------------
    ("section heading (CMP-065 legend)", "color.text.primary", "color.surface.overlay", "text"),
    (
        "field label with unit (Precision, decimals)",
        "color.text.secondary",
        "color.surface.overlay",
        "text",
    ),
    (
        "scope helper text under the segmented control",
        "color.text.tertiary",
        "color.surface.overlay",
        "text",
    ),
    (
        "toggle ON track vs the overlay",
        "color.action.primary.default",
        "color.surface.overlay",
        "non-text",
    ),
    (
        "toggle ON knob on the track",
        "color.text.on-action",
        "color.action.primary.default",
        "non-text",
    ),
    (
        "toggle OFF track — REJECTED pair (border.strong)",
        "color.border.strong",
        "color.surface.overlay",
        "rejected-non-text",
    ),
    (
        "toggle OFF track — adopted (text.tertiary)",
        "color.text.tertiary",
        "color.surface.overlay",
        "non-text",
    ),
    ("toggle OFF knob on the track", "color.surface.overlay", "color.text.tertiary", "non-text"),
    (
        "toggle state word (On / Off) beside the switch",
        "color.text.secondary",
        "color.surface.overlay",
        "text",
    ),
    (
        "radio selected dot (CMP-006)",
        "color.action.primary.default",
        "color.surface.overlay",
        "non-text",
    ),
    ("radio unselected ring", "color.text.tertiary", "color.surface.overlay", "non-text"),
    ("numeric stepper value", "color.text.primary", "color.surface.app", "text"),
    (
        "preview tile boundary (border.default on the overlay)",
        "color.border.default",
        "color.surface.overlay",
        "decorative",
    ),
    ("preview tile empty / error text", "color.text.secondary", "color.surface.sunken", "text"),
    ("preview tile error icon", "color.status.danger.strong", "color.surface.sunken", "non-text"),
    ("preview tile miniature axis labels", "color.text.tertiary", "color.surface.sunken", "text"),
    ("reset confirm dialog text (CMP-044)", "color.text.primary", "color.surface.overlay", "text"),
    (
        "'Requires reload' note beside a data-affecting field",
        "color.text.secondary",
        "color.surface.overlay",
        "text",
    ),
    # --- D03-CR-7 candidates (light: palette.light.red.700 / .500; dark, hc unchanged) -----------
    (
        "CR-7 error block icon",
        "CR:color.status.danger.strong",
        "color.status.danger.subtle",
        "non-text",
    ),
    (
        "CR-7 input invalid boundary",
        "CR:color.status.danger.strong",
        "color.surface.overlay",
        "non-text",
    ),
    (
        "CR-7 preview tile error icon",
        "CR:color.status.danger.strong",
        "color.surface.sunken",
        "non-text",
    ),
    # --- go-to-date landing on the chart ---------------------------------------------------------
    (
        "go-to-date marker (dashed, E11-D02 D8) on the canvas",
        "color.action.primary.default",
        "color.surface.canvas",
        "non-text",
    ),
    ("go-to-date marker pill text", "color.text.on-action", "color.action.primary.default", "text"),
    (
        "announcement / status chip text on the raised row",
        "color.text.primary",
        "color.surface.raised",
        "text",
    ),
]

# CVD: colour pairs that must stay distinguishable without their text (ΔE76 ≥ 5.0 JND floor).
CVD_PAIRS: list[tuple[str, str, str]] = [
    (
        "error block fill vs warning block fill",
        "color.status.danger.subtle",
        "color.status.warning.subtle",
    ),
    ("error icon vs warning icon", "color.status.danger.strong", "color.status.warning.strong"),
    ("toggle ON track vs OFF track", "color.action.primary.default", "color.text.tertiary"),
    ("pressed segment vs unpressed segment", "color.surface.selected", "color.surface.raised"),
    ("lock badge resting vs hover fill", "color.surface.raised", "color.surface.hover"),
    ("go-to-date marker vs crosshair line", "color.action.primary.default", "color.crosshair"),
    (
        "go-to-date marker vs session boundary line",
        "color.action.primary.default",
        "color.text.tertiary",
    ),
    (
        "go-to-date marker vs cursor column (focus ring)",
        "color.action.primary.default",
        "color.focus.ring",
    ),
    (
        "go-to-date marker vs last-price line (up)",
        "color.action.primary.default",
        "color.candle.up",
    ),
    (
        "go-to-date marker vs last-price line (down)",
        "color.action.primary.default",
        "color.candle.down",
    ),
    ("disabled label vs enabled label", "color.text.disabled", "color.text.primary"),
    ("inline reason vs disabled label", "color.text.secondary", "color.text.disabled"),
    (
        "invalid input boundary vs rest boundary",
        "color.status.danger.strong",
        "CR:color.border.field",
    ),
    (
        "CR-7 error icon vs warning icon",
        "CR:color.status.danger.strong",
        "color.status.warning.strong",
    ),
]
JND = 5.0

SIM_TOKENS = [
    "color.action.primary.default",
    "color.focus.ring",
    "color.crosshair",
    "color.text.tertiary",
    "color.text.disabled",
    "color.status.danger.strong",
    "color.status.warning.strong",
    "color.status.danger.subtle",
    "color.status.warning.subtle",
    "color.surface.selected",
]


def main() -> int:
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")  # the reference machine's console is cp1252
    failed = 0
    hc_text_rows, hc_text_min = 0, 99.0
    print("## A. Contrast matrix (ratio per theme; bar per role)\n")
    print("| Element | fg | bg | role | dark | light | hc | verdict |")
    print("|---|---|---|---|---|---|---|---|")
    for element, fg, bg, role in PAIRS:
        vals = [ratio(col(t, fg), col(t, bg)) for t in THEMES]
        bar = BAR[role]
        if bar is None:
            verdict = (
                "disabled control — exempt (reported)"
                if role == "disabled"
                else "decorative (not gated)"
            )
        else:
            if role.endswith("hc-text"):
                bad = ["high-contrast"] if vals[2] < bar else []
            else:
                bad = [THEMES[i] for i, v in enumerate(vals) if v < bar]
            if role == "text":
                hc_text_rows += 1
                hc_text_min = min(hc_text_min, vals[2])
                if vals[2] < HC_TEXT_BAR:
                    bad.append("hc 7:1")
            verdict = "PASS" if not bad else "FAIL: " + ", ".join(bad)
            if role.startswith("rejected"):
                verdict = (
                    ("rejected by design — would " + verdict)
                    if bad
                    else "rejected by design (passes; not used — see the spec)"
                )
            elif bad:
                failed += 1
        print(
            f"| {element} | `{fg}` | `{bg}` | {role} | {vals[0]:.2f} | {vals[1]:.2f} |"
            f" {vals[2]:.2f} | {verdict} |"
        )

    hc_ok = hc_text_min >= HC_TEXT_BAR
    print(
        f"\nhc 7:1 gate (05 §5 item 6): applied to {hc_text_rows} text rows; minimum high-contrast"
        f" text ratio {hc_text_min:.2f}:1 → {'PASS' if hc_ok else 'FAIL'}"
    )
    print("\n## B. Resolved values used above\n")
    print("| token | dark | light | hc |")
    print("|---|---|---|---|")
    seen: list[str] = []
    for _, fg, bg, _ in PAIRS:
        for tok in (fg, bg):
            if tok not in seen:
                seen.append(tok)
    for tok in seen:
        print(
            f"| `{tok}` | {col('dark', tok)} | {col('light', tok)} | {col('high-contrast', tok)} |"
        )

    print("\n## C. CVD simulation (ΔE76 between the two colours per deficiency; JND floor 5.0)\n")
    print("| Pair | theme | normal | protan | deutan | tritan | verdict |")
    print("|---|---|---|---|---|---|---|")
    for name, a, b in CVD_PAIRS:
        for t in THEMES:
            ha, hb = col(t, a), col(t, b)
            d = [cvd.delta_e76(ha, hb)]
            for k in ("protanopia", "deuteranopia", "tritanopia"):
                d.append(cvd.delta_e76(cvd.simulate(ha, k), cvd.simulate(hb, k)))
            worst = min(d[1:])
            verdict = "distinct" if worst >= JND else "COLLAPSES (text/shape carries it)"
            print(
                f"| {name} | {t} | {d[0]:.1f} | {d[1]:.1f} | {d[2]:.1f} | {d[3]:.1f} | {verdict} |"
            )

    print("\n## D. State colours under simulation (hex), for the board annotations\n")
    print("| token | theme | normal | protan | deutan | tritan |")
    print("|---|---|---|---|---|---|")
    for tok in SIM_TOKENS:
        for t in THEMES:
            h = col(t, tok)
            print(
                f"| `{tok}` | {t} | {h} | {cvd.simulate(h, 'protanopia')} |"
                f" {cvd.simulate(h, 'deuteranopia')} | {cvd.simulate(h, 'tritanopia')} |"
            )

    print(f"\nFAIL count (gated rows only): {failed}")
    return 1 if failed else 0


if __name__ == "__main__":
    raise SystemExit(main())
