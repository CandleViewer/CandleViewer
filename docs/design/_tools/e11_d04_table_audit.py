"""E11-D04 data-table / empty / error audit: WCAG contrast matrix, CVD simulation and the
200 % column-width arithmetic, all over the real token JSON.

Standalone, offline, stdlib only. Resolves every theme (`dark`, `light`, `high-contrast`) exactly
as `packages/ui/tokens/tests/verify_tokens.py` does (same loader, same alias resolution, same theme
layering from `themes.json`), measures every foreground/background pair the SCR-045 / SCR-047 /
SCR-048 spec (`docs/design/E11/E11-D04.md`) binds, simulates deuteranopia, protanopia and
tritanopia over every state colour with the Brettel/Vienot projection of
`docs/research/_tools/cvd_simulate.py`, and computes the primary column set's width from the
`font.size.*` / `space.*` tokens (the E11-D01 D5 rule, measured on the real tokens here).
The contrast formula is `contrast_ratio()` from `docs/design/_tools/contrast_check.py` (imported,
not re-implemented), so the numbers agree with E11-D02's, E30-D01's and E09-D03's.

Usage: python3 -I docs/design/_tools/e11_d04_table_audit.py   (prints Markdown; exit 1 on a FAIL)
Stdout is forced to UTF-8 (the tables carry a few non-ASCII glyphs), so it also runs on a cp1252
Windows console (the reference machine).

A PASS/FAIL verdict applies the role's bar (text 4.5:1, non-text 3:1, `hc-text` 7:1 per
`05-accessibility-standard.md` section 5 item 6; every gated row counts). Rows marked
`decorative` carry no meaning (zebra fills, dividers, skeleton blocks) and are reported, never
gated; `rejected-*` rows are pairs the spec considered and designed around, reported with the
verdict they would have had. Candidate tokens that do not exist yet (design-system change
requests for E11-D05) are prefixed `CR:` and measured on the primitive they would alias, never on
an invented hex.
"""

from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
TOKENS = ROOT / "packages" / "ui" / "tokens"


def _load(path: Path, name: str):
    spec = importlib.util.spec_from_file_location(name, path)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"cannot load {path}")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


sys.path.insert(0, str(TOKENS / "tests"))
verify = _load(TOKENS / "tests" / "verify_tokens.py", "verify_tokens")
contrast_check = _load(ROOT / "docs" / "design" / "_tools" / "contrast_check.py", "contrast_check")
cvd = _load(ROOT / "docs" / "research" / "_tools" / "cvd_simulate.py", "cvd_simulate")

THEMES = ("dark", "light", "high-contrast")
BAR: dict[str, float | None] = {
    "text": 4.5,
    "non-text": 3.0,
    "hc-text": 7.0,
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

# Candidate aliases for the E11-D05 change requests (CR:). Values are existing primitives per
# theme; `CR:color.text.buy` / `.sell` are E11-D02 CR-5 (already measured there on canvas and
# overlay; measured here on every row surface the table uses).
CR = {
    "CR:color.text.buy": {
        "dark": "palette.green.300",
        "light": "palette.light.green.700",
        "high-contrast": "palette.green.300",
    },
    "CR:color.text.sell": {
        "dark": "palette.red.300",
        "light": "palette.light.red.700",
        "high-contrast": "palette.red.300",
    },
}


def col(theme: str, token: str) -> str:
    if token in CR:
        return T[theme][CR[token][theme]]
    return T[theme][token]


# (element, fg token, bg token, role)
PAIRS: list[tuple[str, str, str, str]] = [
    # --- SCR-045 table: header, rows, zebra, focus ------------------------------------------
    ("header cell text (sticky header row)", "color.text.primary", "color.surface.hover", "text"),
    (
        "header sort glyph (asc / desc / none)",
        "color.text.secondary",
        "color.surface.hover",
        "non-text",
    ),
    ("time row header, numbers (odd row)", "color.text.primary", "color.surface.canvas", "text"),
    ("time row header, numbers (even row)", "color.text.primary", "color.surface.raised", "text"),
    ("numbers on the hovered row", "color.text.primary", "color.surface.hover", "text"),
    ("numbers on the focused row", "color.text.primary", "color.surface.selected", "text"),
    ("numbers on the expanded level sub-table", "color.text.primary", "color.surface.app", "text"),
    (
        "secondary cell text: forming bar, caption, counts (canvas)",
        "color.text.secondary",
        "color.surface.canvas",
        "text",
    ),
    ("secondary cell text (raised row)", "color.text.secondary", "color.surface.raised", "text"),
    ("secondary cell text (focused row)", "color.text.secondary", "color.surface.selected", "text"),
    ("secondary text on the level sub-table", "color.text.secondary", "color.surface.app", "text"),
    (
        "zebra: even row fill vs odd row fill",
        "color.surface.raised",
        "color.surface.canvas",
        "decorative",
    ),
    ("row divider hairline", "color.border.subtle", "color.surface.canvas", "decorative"),
    ("focused row fill vs canvas", "color.surface.selected", "color.surface.canvas", "decorative"),
    ("focus ring on an odd row", "color.focus.ring", "color.surface.canvas", "non-text"),
    ("focus ring on an even row", "color.focus.ring", "color.surface.raised", "non-text"),
    (
        "focus ring on the hovered row / header (unregistered in pairs.mjs)",
        "color.focus.ring",
        "color.surface.hover",
        "non-text",
    ),
    (
        "focus ring on the focused row fill (unregistered in pairs.mjs)",
        "color.focus.ring",
        "color.surface.selected",
        "non-text",
    ),
    ("focus ring on the level sub-table", "color.focus.ring", "color.surface.app", "non-text"),
    (
        "expander chevron, row-action button glyph (canvas)",
        "color.text.secondary",
        "color.surface.canvas",
        "non-text",
    ),
    (
        "expander chevron, row-action button glyph (raised)",
        "color.text.secondary",
        "color.surface.raised",
        "non-text",
    ),
    # --- signed numbers: delta, CVD, level delta --------------------------------------------
    (
        "CR: delta / CVD positive number (odd row)",
        "CR:color.text.buy",
        "color.surface.canvas",
        "text",
    ),
    (
        "CR: delta / CVD positive number (even row)",
        "CR:color.text.buy",
        "color.surface.raised",
        "text",
    ),
    (
        "CR: delta / CVD positive number (hovered row)",
        "CR:color.text.buy",
        "color.surface.hover",
        "text",
    ),
    (
        "CR: delta / CVD positive number (focused row)",
        "CR:color.text.buy",
        "color.surface.selected",
        "text",
    ),
    ("CR: level delta positive (sub-table)", "CR:color.text.buy", "color.surface.app", "text"),
    (
        "CR: delta / CVD negative number (odd row)",
        "CR:color.text.sell",
        "color.surface.canvas",
        "text",
    ),
    (
        "CR: delta / CVD negative number (even row)",
        "CR:color.text.sell",
        "color.surface.raised",
        "text",
    ),
    (
        "CR: delta / CVD negative number (hovered row)",
        "CR:color.text.sell",
        "color.surface.hover",
        "text",
    ),
    (
        "CR: delta / CVD negative number (focused row)",
        "CR:color.text.sell",
        "color.surface.selected",
        "text",
    ),
    ("CR: level delta negative (sub-table)", "CR:color.text.sell", "color.surface.app", "text"),
    (
        "candle token as a delta number -- REJECTED pair (coloured number, E11-D02 D10 lineage)",
        "color.candle.up",
        "color.surface.canvas",
        "rejected-text",
    ),
    (
        "candle token as a delta number -- REJECTED pair",
        "color.candle.down",
        "color.surface.canvas",
        "rejected-text",
    ),
    # --- flags and chips in cells -----------------------------------------------------------
    (
        "imbalance flag word (Bid-stacked / Ask-stacked), odd row",
        "color.text.primary",
        "color.surface.canvas",
        "text",
    ),
    (
        "imbalance flag bar (3 px left rule) on canvas",
        "color.footprint.imbalance",
        "color.surface.canvas",
        "non-text",
    ),
    (
        "imbalance flag bar on a raised row",
        "color.footprint.imbalance",
        "color.surface.raised",
        "non-text",
    ),
    (
        "imbalance flag bar on the focused row",
        "color.footprint.imbalance",
        "color.surface.selected",
        "non-text",
    ),
    (
        "imbalance flag bar on the level sub-table",
        "color.footprint.imbalance",
        "color.surface.app",
        "non-text",
    ),
    (
        "(estimated) chip -- REJECTED pair (status.info.strong as text on canvas)",
        "color.status.info.strong",
        "color.surface.canvas",
        "rejected-text",
    ),
    (
        "(estimated) chip -- REJECTED pair (status.info.strong as text on raised)",
        "color.status.info.strong",
        "color.surface.raised",
        "rejected-text",
    ),
    (
        "(estimated) chip text -- adopted (text.primary on info.subtle)",
        "color.text.primary",
        "color.status.info.subtle",
        "text",
    ),
    (
        "(estimated) chip glyph -- adopted (info.strong on info.subtle)",
        "color.status.info.strong",
        "color.status.info.subtle",
        "non-text",
    ),
    (
        "(estimated) chip fill vs canvas (reinforcement)",
        "color.status.info.subtle",
        "color.surface.canvas",
        "decorative",
    ),
    (
        "filter chip / sort-status chip text (neutral pill)",
        "color.text.primary",
        "color.surface.raised",
        "text",
    ),
    ("filter chip border on canvas", "color.border.default", "color.surface.canvas", "decorative"),
    ("sort-status chip glyph", "color.text.secondary", "color.surface.raised", "non-text"),
    ("'N new bars' pill text (neutral)", "color.text.primary", "color.surface.raised", "text"),
    ("Kbd (Alt+T) text on its raised key", "color.text.primary", "color.surface.raised", "text"),
    # --- stale banner, loading bands --------------------------------------------------------
    ("stale banner text", "color.text.primary", "color.status.warning.subtle", "text"),
    ("stale banner icon", "color.status.warning.strong", "color.status.warning.subtle", "non-text"),
    (
        "stale banner Kbd key on the banner (raised key)",
        "color.surface.raised",
        "color.status.warning.subtle",
        "decorative",
    ),
    (
        "stale banner -- REJECTED pair (warning.strong as text)",
        "color.status.warning.strong",
        "color.status.warning.subtle",
        "rejected-text",
    ),
    ("'Loading older bars...' band text", "color.text.secondary", "color.surface.hover", "text"),
    ("skeleton row blocks", "color.surface.hover", "color.surface.canvas", "decorative"),
    ("'Loading 5,000 bars...' text", "color.text.secondary", "color.surface.canvas", "text"),
    # --- SCR-047 empty state ----------------------------------------------------------------
    ("empty-state heading", "color.text.primary", "color.surface.canvas", "text"),
    ("empty-state heading, hc 7:1 bar", "color.text.primary", "color.surface.canvas", "hc-text"),
    ("empty-state cause sentence", "color.text.secondary", "color.surface.canvas", "text"),
    (
        "empty-state recording-start timestamp (mono)",
        "color.text.primary",
        "color.surface.canvas",
        "text",
    ),
    (
        "empty-state primary CTA text (Record this symbol)",
        "color.text.on-action",
        "color.action.primary.default",
        "text",
    ),
    (
        "empty-state primary CTA fill vs canvas",
        "color.action.primary.default",
        "color.surface.canvas",
        "non-text",
    ),
    (
        "empty-state secondary button text (Pick another symbol)",
        "color.text.primary",
        "color.action.secondary.default",
        "text",
    ),
    (
        "empty-state 'Learn more' link (underlined)",
        "color.text.link",
        "color.surface.canvas",
        "text",
    ),
    (
        "link vs body text (1.4.1 reinforcement; underline is the carrier)",
        "color.text.link",
        "color.text.secondary",
        "decorative",
    ),
    (
        "not-trading status word (data-confidence delisted text)",
        "color.data-confidence.delisted.text",
        "color.surface.canvas",
        "text",
    ),
    (
        "not-trading status dot (data-confidence delisted indicator)",
        "color.data-confidence.delisted.indicator",
        "color.surface.canvas",
        "non-text",
    ),
    ("'Live data is streaming now' sentence", "color.text.primary", "color.surface.canvas", "text"),
    (
        "live glyph (data-confidence live indicator)",
        "color.data-confidence.live.indicator",
        "color.surface.canvas",
        "non-text",
    ),
    ("non-owner explanatory sentence", "color.text.secondary", "color.surface.canvas", "text"),
    # --- SCR-048 error state ----------------------------------------------------------------
    ("error card heading", "color.text.primary", "color.surface.raised", "text"),
    ("error card body", "color.text.secondary", "color.surface.raised", "text"),
    (
        "error card left rule / alert icon on the card",
        "color.status.danger.strong",
        "color.surface.raised",
        "non-text",
    ),
    (
        "error card left rule against the canvas edge",
        "color.status.danger.strong",
        "color.surface.canvas",
        "non-text",
    ),
    (
        "error card -- REJECTED pair (danger.default as text on the card)",
        "color.status.danger.default",
        "color.surface.raised",
        "rejected-text",
    ),
    (
        "error card -- REJECTED pair (danger.default on danger.subtle, E06-D02 lineage)",
        "color.status.danger.default",
        "color.status.danger.subtle",
        "rejected-text",
    ),
    (
        "error code / correlation id (mono) on the sunken code chip",
        "color.text.primary",
        "color.surface.sunken",
        "text",
    ),
    ("code chip fill vs card", "color.surface.sunken", "color.surface.raised", "decorative"),
    (
        "copy button glyph (CMP-033) on the card",
        "color.text.secondary",
        "color.surface.raised",
        "non-text",
    ),
    ("Retry button text (primary)", "color.text.on-action", "color.action.primary.default", "text"),
    (
        "Open diagnostics button text (secondary)",
        "color.text.primary",
        "color.action.secondary.default",
        "text",
    ),
    ("renderer-settings link on the card", "color.text.link", "color.surface.raised", "text"),
    ("attempt / next-try line", "color.text.secondary", "color.surface.raised", "text"),
    (
        "restoring strip text (context lost)",
        "color.text.primary",
        "color.status.warning.subtle",
        "text",
    ),
    (
        "restoring strip icon",
        "color.status.warning.strong",
        "color.status.warning.subtle",
        "non-text",
    ),
    (
        "deferred-to-banner variant: disconnected dot on a canvas-filled pill",
        "color.data-confidence.disconnected.indicator",
        "color.surface.canvas",
        "non-text",
    ),
    (
        "disconnected dot -- REJECTED pair (on the raised card)",
        "color.data-confidence.disconnected.indicator",
        "color.surface.raised",
        "rejected-non-text",
    ),
    (
        "degraded-2d badge text (E11-D02 D16, repeated here)",
        "color.text.primary",
        "color.surface.raised",
        "text",
    ),
    (
        "degraded-2d badge glyph (E11-D02 D16, repeated here)",
        "color.status.warning.strong",
        "color.surface.raised",
        "non-text",
    ),
    # --- entry point -----------------------------------------------------------------------
    (
        "view switch: selected segment text (Chart | Table)",
        "color.text.primary",
        "color.surface.selected",
        "text",
    ),
    ("view switch: unselected segment text", "color.text.primary", "color.surface.raised", "text"),
    (
        "view switch: selected check glyph",
        "color.text.primary",
        "color.surface.selected",
        "non-text",
    ),
    (
        "view switch: selected fill vs the toolbar (reinforcement)",
        "color.surface.selected",
        "color.surface.raised",
        "decorative",
    ),
    (
        "view switch focus ring on the toolbar",
        "color.focus.ring",
        "color.surface.raised",
        "non-text",
    ),
]

# CVD: colour pairs that must stay distinguishable without their text (dE76 >= 5.0 JND floor).
CVD_PAIRS: list[tuple[str, str, str]] = [
    ("delta positive vs negative (CR text tokens)", "CR:color.text.buy", "CR:color.text.sell"),
    (
        "imbalance bar vs stale/restoring icon",
        "color.footprint.imbalance",
        "color.status.warning.strong",
    ),
    ("imbalance bar vs delta positive text", "color.footprint.imbalance", "CR:color.text.buy"),
    ("imbalance bar vs delta negative text", "color.footprint.imbalance", "CR:color.text.sell"),
    (
        "error rule (danger.strong) vs restoring icon (warning.strong)",
        "color.status.danger.strong",
        "color.status.warning.strong",
    ),
    (
        "not-trading dot vs stale icon",
        "color.data-confidence.delisted.indicator",
        "color.data-confidence.stale.indicator",
    ),
    ("(estimated) glyph vs delta positive text", "color.status.info.strong", "CR:color.text.buy"),
    ("primary CTA fill vs focus ring", "color.action.primary.default", "color.focus.ring"),
    ("link vs delta positive text", "color.text.link", "CR:color.text.buy"),
    ("focused row fill vs hovered row fill", "color.surface.selected", "color.surface.hover"),
]
JND = 5.0

# --- column-width arithmetic (E11-D01 D5, measured on the real tokens) -----------------------
MONO_ADVANCE_EM = 0.6  # JetBrains Mono advance width (E11-D01 Q5-a, jetbrains.com/lp/mono)
PRIMARY_COLUMNS: list[tuple[str, int]] = [  # (column, character budget incl. sign and separators)
    ("time", 8),
    ("open", 9),
    ("high", 9),
    ("low", 9),
    ("close", 9),
    ("volume", 8),
    ("delta", 8),
]
EXTENDED_FIRST: tuple[str, int] = ("CVD", 9)
FIXED_CSS_PX = {"expander": 24, "actions": 24, "scrollbar": 12}  # size.target.min x2 + a scrollbar
DENSITY = {  # type token -> font.size token; cell pad token (each side); panel inset token
    "compact": ("type.num.sm", "font.size.xs", "space.2", "space.2"),
    "comfortable": ("type.num.base", "font.size.base", "space.3", "space.3"),
}
TEXT_SCALES = (1.0, 1.12, 1.25, 1.5)  # 16 section 4 data-text-scale 100 / 112 / 125 / 150
VIEWPORTS = {"200 % on 1280 px (640 CSS px)": 640, "400 % / 320 CSS px reflow point": 320}


def _dim(name: str) -> float:
    prim = verify.load(verify.PRIMITIVES)
    v = prim[name]["$value"]
    return float(str(v).replace("px", ""))


def fit_table() -> list[str]:
    out = [
        "| density | text scale | font px | cell pad | primary 7 cols | + CVD "
        "| 640 CSS px | 320 CSS px |",
        "|---|---|---|---|---|---|---|---|",
    ]
    for dens, (_type_tok, size_tok, pad_tok, inset_tok) in DENSITY.items():
        size = _dim(size_tok)
        pad = _dim(pad_tok)
        inset = _dim(inset_tok)
        for sc in TEXT_SCALES:
            px = size * sc
            per_char = px * MONO_ADVANCE_EM
            fixed = sum(FIXED_CSS_PX.values()) + 2 * inset
            primary = fixed + sum(ch * per_char + 2 * pad for _, ch in PRIMARY_COLUMNS)
            with_cvd = primary + EXTENDED_FIRST[1] * per_char + 2 * pad
            v640 = (
                "primary + CVD fit"
                if with_cvd <= 640
                else ("primary fits, CVD extended" if primary <= 640 else "REFLOW (stacked)")
            )
            v320 = "fits" if primary <= 320 else "REFLOW (stacked)"
            out.append(
                f"| {dens} | {int(sc * 100)} % | {px:.2f} | {pad:.0f} | {primary:.0f} px "
                f"({primary * 2:.0f} at 200 %) | {with_cvd:.0f} px | {v640} | {v320} |"
            )
    return out


def main() -> int:
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")  # the reference machine's console is cp1252
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
            if role.endswith("hc-text"):
                bad = ["high-contrast"] if vals[2] < bar else []
            else:
                bad = [THEMES[i] for i, v in enumerate(vals) if v < bar]
            verdict = "PASS" if not bad else "FAIL: " + ", ".join(bad)
            if role.startswith("rejected"):
                verdict = (
                    ("rejected by design -- would " + verdict)
                    if bad
                    else "rejected by design (passes; not used -- see the spec)"
                )
            elif bad:
                failed += 1
        print(
            f"| {element} | `{fg}` | `{bg}` | {role} | {vals[0]:.2f} | {vals[1]:.2f} | "
            f"{vals[2]:.2f} | {verdict} |"
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

    print(
        "\n## C. CVD simulation (ΔE76 between the two colours under each deficiency; "
        "JND floor 5.0)\n"
    )
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
    for tok in [
        "CR:color.text.buy",
        "CR:color.text.sell",
        "color.footprint.imbalance",
        "color.status.warning.strong",
        "color.status.danger.strong",
        "color.status.info.strong",
        "color.data-confidence.delisted.indicator",
        "color.action.primary.default",
        "color.focus.ring",
        "color.text.link",
    ]:
        for t in THEMES:
            h = col(t, tok)
            print(
                f"| `{tok}` | {t} | {h} | {cvd.simulate(h, 'protanopia')} | "
                f"{cvd.simulate(h, 'deuteranopia')} | {cvd.simulate(h, 'tritanopia')} |"
            )

    print(
        "\n## E. Primary column set width from the tokens (JetBrains Mono advance "
        f"{MONO_ADVANCE_EM} em; fixed columns expander 24 + actions 24 + scrollbar 12 CSS px "
        "+ 2 x panel inset)\n"
    )
    for line in fit_table():
        print(line)

    print(f"\nFAIL count (gated rows only): {failed}")
    return 1 if failed else 0


if __name__ == "__main__":
    raise SystemExit(main())
