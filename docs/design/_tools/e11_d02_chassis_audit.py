"""E11-D02 chart-chassis audit: WCAG contrast matrix + CVD simulation over the real token JSON.

Standalone, offline, stdlib only. Resolves every theme (`dark`, `light`, `high-contrast`) exactly as
`packages/ui/tokens/tests/verify_tokens.py` does (same loader, same alias resolution, same theme
layering from `themes.json`), measures every foreground/background pair the chassis spec
(`docs/design/E11/E11-D02.md`) binds, and simulates deuteranopia, protanopia and tritanopia over
every state colour with the Brettel/Vienot projection of `docs/research/_tools/cvd_simulate.py`.
The contrast formula is `contrast_ratio()` from `docs/design/_tools/contrast_check.py` (imported,
not re-implemented), so the numbers agree with E30-D01's and E09-D03's.

Usage: python3 -I docs/design/_tools/e11_d02_chassis_audit.py   (prints Markdown; exit 1 on a FAIL)
Stdout is forced to UTF-8 (the tables carry `ΔE`, `≥`, `—`), so it also runs on a cp1252 Windows console
(the reference machine).

A PASS/FAIL verdict applies the role's bar (text 4.5:1, non-text 3:1, `hc-text` 7:1 per
`05-accessibility-standard.md` §5 item 6; every gated row counts, the hc-text rows included); rows marked
`decorative` carry no meaning (`16-design-system-brief.md` §6 rule 7) — the post-scrim rows are the frozen,
deliberately de-emphasised chart of the disconnected state — and `rejected-*` rows are pairs the spec considered
and designed around — both are reported, never gated. Candidate tokens that do not
exist yet (design-system change requests for E11-D05) are prefixed `CR:` and measured on the
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
    assert spec.loader is not None
    spec.loader.exec_module(mod)
    return mod


sys.path.insert(0, str(TOKENS / "tests"))
verify = _load(TOKENS / "tests" / "verify_tokens.py", "verify_tokens")
contrast_check = _load(ROOT / "docs" / "design" / "_tools" / "contrast_check.py", "contrast_check")
cvd = _load(ROOT / "docs" / "research" / "_tools" / "cvd_simulate.py", "cvd_simulate")

THEMES = ("dark", "light", "high-contrast")
BAR = {"text": 4.5, "non-text": 3.0, "hc-text": 7.0, "decorative": None, "rejected-text": 4.5, "rejected-non-text": 3.0, "rejected-hc-text": 7.0}
# `rejected-*` rows are pairs the spec considered and designed around; they are reported with their bar, never gated.


def hex_to_rgb(h: str) -> tuple[int, int, int]:
    h = h.lstrip("#")
    return int(h[0:2], 16), int(h[2:4], 16), int(h[4:6], 16)


def ratio(fg: str, bg: str) -> float:
    return contrast_check.contrast_ratio(hex_to_rgb(fg), hex_to_rgb(bg))


def resolve_theme(name: str) -> dict[str, str]:
    prim = verify.load(verify.PRIMITIVES)
    allt = dict(prim)
    allt.update(verify.merged_set(verify.THEMES[name]))
    return {k: verify.resolve(v["$value"], allt) for k, v in allt.items() if v.get("$type") == "color"}


T = {n: resolve_theme(n) for n in THEMES}
PRIM = {k: v for k, v in T["dark"].items() if k.startswith("palette.")}

# Candidate aliases for the E11-D05 change requests (CR:). Values are existing primitives per theme.
CR = {
    "CR:color.replay.border": {"dark": "palette.purple.400", "light": "palette.purple.600", "high-contrast": "palette.purple.400"},
    "CR:color.text.buy": {"dark": "palette.green.300", "light": "palette.light.green.700", "high-contrast": "palette.green.300"},
    "CR:color.text.sell": {"dark": "palette.red.300", "light": "palette.light.red.700", "high-contrast": "palette.red.300"},
}


def col(theme: str, token: str) -> str:
    if token in CR:
        return T[theme][CR[token][theme]]
    if token.startswith("dim85:"):  # the stale-state 15 % dim: data-ink multiplied by 0.85 (a uniform, no extra pass)
        r, g, b = hex_to_rgb(T[theme][token[6:]])
        return "#%02X%02X%02X" % (round(r * 0.85), round(g * 0.85), round(b * 0.85))
    if token.startswith("scrim60:") or token.startswith("scrim45:"):  # the disconnected scrim: surface.app at alpha over the token
        alpha = 0.6 if token.startswith("scrim60:") else 0.45
        app = hex_to_rgb(T[theme]["color.surface.app"]); under = hex_to_rgb(T[theme][token.split(":", 1)[1]])
        return "#%02X%02X%02X" % tuple(round(alpha * a + (1 - alpha) * u) for a, u in zip(app, under))
    return T[theme][token]


# (element, fg token, bg token, role)
PAIRS: list[tuple[str, str, str, str]] = [
    ("axis tick labels (CMP-188/189) — adopted: color.text.tertiary (D7, CR-2)", "color.text.tertiary", "color.surface.canvas", "text"),
    ("axis tick labels, hc AAA target (7:1) — adopted", "color.text.tertiary", "color.surface.canvas", "hc-text"),
    ("axis tick labels — REJECTED pair (E05 color.axis.text, 5.96:1 in hc)", "color.axis.text", "color.surface.canvas", "rejected-hc-text"),
    ("axis mode tag log / % / inv; time-strip zone tag (UTC)", "color.text.tertiary", "color.surface.canvas", "text"),
    ("legend label, focused pane label, readout values", "color.text.primary", "color.surface.canvas", "text"),
    ("legend value label, loading text", "color.text.secondary", "color.surface.canvas", "text"),
    ("unfocused pane label, hidden legend item", "color.text.tertiary", "color.surface.canvas", "text"),
    ("chip / badge text on neutral pill", "color.text.primary", "color.surface.raised", "text"),
    ("chip secondary text on neutral pill", "color.text.secondary", "color.surface.raised", "text"),
    ("countdown normal (header, raised)", "color.text.secondary", "color.surface.raised", "text"),
    ("countdown warn text — REJECTED pair (warning.strong as text)", "color.status.warning.strong", "color.surface.raised", "rejected-text"),
    ("countdown warn text — adopted (D11)", "color.text.primary", "color.status.warning.subtle", "text"),
    ("countdown warn glyph — adopted (D11)", "color.status.warning.strong", "color.status.warning.subtle", "non-text"),
    ("countdown closed text", "color.text.tertiary", "color.surface.raised", "text"),
    ("tooltip title / values", "color.text.primary", "color.surface.overlay", "text"),
    ("tooltip field labels", "color.text.secondary", "color.surface.overlay", "text"),
    ("tooltip up value — REJECTED pair (coloured number)", "color.candle.up", "color.surface.overlay", "rejected-text"),
    ("tooltip down value — REJECTED pair (coloured number)", "color.candle.down", "color.surface.overlay", "rejected-text"),
    ("CR: text.buy on overlay", "CR:color.text.buy", "color.surface.overlay", "text"),
    ("CR: text.sell on overlay", "CR:color.text.sell", "color.surface.overlay", "text"),
    ("CR: text.buy on canvas", "CR:color.text.buy", "color.surface.canvas", "text"),
    ("CR: text.sell on canvas", "CR:color.text.sell", "color.surface.canvas", "text"),
    ("crosshair axis pill text", "color.text.inverse", "color.crosshair", "text"),
    ("last-price pill text on up fill", "color.text.inverse", "color.candle.up", "text"),
    ("last-price pill text on down fill", "color.text.inverse", "color.candle.down", "text"),
    ("last-price neutral pill text", "color.text.primary", "color.surface.raised", "text"),
    ("mark-price pill text (M …)", "color.text.primary", "color.surface.raised", "text"),
    ("mark-price line (short-dashed, meaning-carrying)", "color.text.tertiary", "color.surface.canvas", "non-text"),
    ("left-gutter indicator last-value pill text (neutral pill)", "color.text.primary", "color.surface.raised", "text"),
    ("disconnected strip text (its own raised strip above the scrim)", "color.text.primary", "color.surface.raised", "text"),
    ("post-scrim candle up at opacity.scrim 0.6 (frozen chart, de-emphasised by design)", "scrim60:color.candle.up", "scrim60:color.surface.canvas", "decorative"),
    ("post-scrim candle down at 0.6", "scrim60:color.candle.down", "scrim60:color.surface.canvas", "decorative"),
    ("post-scrim wick at 0.6", "scrim60:color.candle.wick", "scrim60:color.surface.canvas", "decorative"),
    ("post-scrim candle up at opacity.disabled 0.45 (alternative; also below 3:1)", "scrim45:color.candle.up", "scrim45:color.surface.canvas", "decorative"),
    ("post-scrim candle down at 0.45 (alternative)", "scrim45:color.candle.down", "scrim45:color.surface.canvas", "decorative"),
    ("stale chip text", "color.data-confidence.stale.text", "color.data-confidence.stale.surface", "text"),
    ("stale chip indicator", "color.data-confidence.stale.indicator", "color.data-confidence.stale.surface", "non-text"),
    ("stale chip last-good timestamp text (`· last 13:42:05`)", "color.data-confidence.stale.text", "color.data-confidence.stale.surface", "text"),
    ("reconnecting / offline chip text (canvas-filled pill)", "color.data-confidence.reconnecting.text", "color.surface.canvas", "text"),
    ("reconnecting chip indicator on the canvas fill", "color.data-confidence.reconnecting.indicator", "color.surface.canvas", "non-text"),
    ("reconnecting indicator — REJECTED pair (on the raised row)", "color.data-confidence.reconnecting.indicator", "color.surface.raised", "rejected-non-text"),
    ("delayed 'Reduced rate' chip text", "color.text.primary", "color.surface.canvas", "text"),
    ("delayed 'Reduced rate' chip indicator", "color.status.info.strong", "color.surface.canvas", "non-text"),
    ("feed chip border on the raised row", "color.border.default", "color.surface.raised", "decorative"),
    ("paused badge text", "color.text.primary", "color.status.warning.subtle", "text"),
    ("paused badge icon", "color.status.warning.strong", "color.status.warning.subtle", "non-text"),
    ("disconnected label text", "color.data-confidence.disconnected.text", "color.surface.canvas", "text"),
    ("disconnected indicator", "color.data-confidence.disconnected.indicator", "color.surface.canvas", "non-text"),
    ("degraded / reduced-detail badge text", "color.text.primary", "color.surface.raised", "text"),
    ("degraded badge glyph — REJECTED pair (warning.default)", "color.status.warning.default", "color.surface.raised", "rejected-non-text"),
    ("degraded badge glyph — adopted (D16)", "color.status.warning.strong", "color.surface.raised", "non-text"),
    ("aggregation chip text", "color.text.primary", "color.surface.raised", "text"),
    ("env badge text (LIVE / DEMO)", "color.text.primary", "color.surface.raised", "hc-text"),
    ("env badge LIVE border on pill", "color.env.live", "color.surface.raised", "non-text"),
    ("env badge DEMO border on pill", "color.env.demo", "color.surface.raised", "non-text"),
    ("env LIVE band on canvas", "color.env.live", "color.surface.canvas", "non-text"),
    ("env DEMO band on canvas", "color.env.demo", "color.surface.canvas", "non-text"),
    ("cluster pressed `auto` — REJECTED pair (primary-action fill = color.env.demo's hue)", "color.text.on-action", "color.action.primary.default", "rejected-text"),
    ("cluster pressed `auto` text — adopted (D8)", "color.text.primary", "color.surface.selected", "text"),
    ("cluster pressed check glyph — the ≥3:1 state carrier (D8)", "color.text.primary", "color.surface.selected", "non-text"),
    ("cluster pressed border (reinforcement)", "color.border.strong", "color.surface.selected", "decorative"),
    ("cluster pressed fill vs the raised cluster (reinforcement)", "color.surface.selected", "color.surface.raised", "decorative"),
    ("pane focus accent bar", "color.action.primary.default", "color.surface.canvas", "non-text"),
    ("focus ring core (CMP-039)", "color.focus.ring", "color.surface.canvas", "non-text"),
    ("focus ring on raised chrome", "color.focus.ring", "color.surface.raised", "non-text"),
    ("crosshair line", "color.crosshair", "color.surface.canvas", "non-text"),
    ("crosshair over a major gridline", "color.crosshair", "color.border.default", "non-text"),
    ("crosshair over a minor gridline", "color.crosshair", "color.grid.line", "non-text"),
    ("session / day boundary line (dashed)", "color.text.tertiary", "color.surface.canvas", "non-text"),
    ("maintenance band edge (dashed)", "color.text.tertiary", "color.surface.canvas", "non-text"),
    ("maintenance band hatch (texture)", "color.border.strong", "color.surface.canvas", "decorative"),
    ("major gridline (round numbers)", "color.border.default", "color.surface.canvas", "decorative"),
    ("minor gridline", "color.grid.line", "color.surface.canvas", "decorative"),
    ("axis rule / pane divider hairline", "color.border.default", "color.surface.canvas", "decorative"),
    ("splitter grip at rest", "color.text.tertiary", "color.surface.canvas", "non-text"),
    ("splitter grip hover", "color.text.secondary", "color.surface.canvas", "non-text"),
    ("watermark text", "color.border.default", "color.surface.canvas", "decorative"),
    ("skeleton blocks", "color.surface.hover", "color.surface.canvas", "decorative"),
    ("collapsed-stub label", "color.text.primary", "color.surface.raised", "text"),
    ("CR: replay border", "CR:color.replay.border", "color.surface.canvas", "non-text"),
    ("replay chip text", "color.text.primary", "color.surface.raised", "text"),
    ("candle up body (data-ink)", "color.candle.up", "color.surface.canvas", "non-text"),
    ("candle down body (data-ink)", "color.candle.down", "color.surface.canvas", "non-text"),
    ("candle wick (data-ink)", "color.candle.wick", "color.surface.canvas", "non-text"),
    ("stale 15 % dim: candle up", "dim85:color.candle.up", "color.surface.canvas", "non-text"),
    ("stale 15 % dim: candle down", "dim85:color.candle.down", "color.surface.canvas", "non-text"),
    ("stale 15 % dim: wick", "dim85:color.candle.wick", "color.surface.canvas", "non-text"),
    ("stale 15 % dim: imbalance outline", "dim85:color.footprint.imbalance", "color.surface.canvas", "non-text"),
    ("legend swatch up", "color.candle.up", "color.surface.canvas", "non-text"),
    ("legend swatch down", "color.candle.down", "color.surface.canvas", "non-text"),
    ("diagnostics value text (E06-D02)", "color.text.primary", "color.surface.overlay", "text"),
    ("diagnostics 'above budget' chip — REJECTED pair (E06-D02 §2.3)", "color.status.danger.default", "color.status.danger.subtle", "rejected-text"),
    ("diagnostics 'above budget' chip text — adopted (D15)", "color.text.primary", "color.status.danger.subtle", "text"),
    ("diagnostics 'above budget' chip icon — adopted (D15)", "color.status.danger.strong", "color.status.danger.subtle", "non-text"),
    ("diagnostics 'below budget' chip text", "color.status.success.default", "color.status.success.subtle", "text"),
]

# CVD: colour pairs that must stay distinguishable without their text (ΔE76 ≥ 5.0 JND floor, tools/contrast).
CVD_PAIRS: list[tuple[str, str, str]] = [
    ("candle up vs down", "color.candle.up", "color.candle.down"),
    ("env LIVE vs DEMO", "color.env.live", "color.env.demo"),
    ("stale vs delayed indicator", "color.data-confidence.stale.indicator", "color.data-confidence.resyncing.indicator"),
    ("stale vs disconnected indicator", "color.data-confidence.stale.indicator", "color.data-confidence.disconnected.indicator"),
    ("disconnected vs delayed indicator", "color.data-confidence.disconnected.indicator", "color.data-confidence.resyncing.indicator"),
    ("countdown warn vs normal", "color.status.warning.strong", "color.text.secondary"),
    ("replay border vs env DEMO", "CR:color.replay.border", "color.env.demo"),
    ("replay border vs focus ring", "CR:color.replay.border", "color.focus.ring"),
    ("replay border vs env LIVE", "CR:color.replay.border", "color.env.live"),
    ("pane focus accent vs focus ring", "color.action.primary.default", "color.focus.ring"),
    ("cluster pressed fill (surface.selected) vs env DEMO border", "color.surface.selected", "color.env.demo"),
    ("paused icon vs stale indicator", "color.status.warning.strong", "color.data-confidence.stale.indicator"),
    ("last-price up vs down pill", "color.candle.up", "color.candle.down"),
]
JND = 5.0


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
                verdict = ("rejected by design — would " + verdict) if bad else "rejected by design (passes; not used — see the spec)"
            elif bad and not element.startswith("CR:"):
                failed += 1
        print(f"| {element} | `{fg}` | `{bg}` | {role} | {vals[0]:.2f} | {vals[1]:.2f} | {vals[2]:.2f} | {verdict} |")

    print("\n## B. Resolved values used above\n")
    print("| token | dark | light | hc |")
    print("|---|---|---|---|")
    seen: list[str] = []
    for _, fg, bg, _ in PAIRS:
        for tok in (fg, bg):
            if tok not in seen:
                seen.append(tok)
    for tok in seen:
        print(f"| `{tok}` | {col('dark', tok)} | {col('light', tok)} | {col('high-contrast', tok)} |")

    print("\n## C. CVD simulation (ΔE76 between the two colours under each deficiency; JND floor 5.0)\n")
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
            print(f"| {name} | {t} | {d[0]:.1f} | {d[1]:.1f} | {d[2]:.1f} | {d[3]:.1f} | {verdict} |")

    print("\n## D. State colours under simulation (hex), for the board annotations\n")
    print("| token | theme | normal | protan | deutan | tritan |")
    print("|---|---|---|---|---|---|")
    for tok in [
        "color.candle.up", "color.candle.down", "color.env.live", "color.env.demo",
        "color.data-confidence.stale.indicator", "color.data-confidence.resyncing.indicator",
        "color.data-confidence.disconnected.indicator", "color.status.warning.strong",
        "color.focus.ring", "color.action.primary.default", "CR:color.replay.border",
    ]:
        for t in THEMES:
            h = col(t, tok)
            print(f"| `{tok}` | {t} | {h} | {cvd.simulate(h, 'protanopia')} | {cvd.simulate(h, 'deuteranopia')} | {cvd.simulate(h, 'tritanopia')} |")

    print(f"\nFAIL count (gated rows only): {failed}")
    return 1 if failed else 0


if __name__ == "__main__":
    raise SystemExit(main())
