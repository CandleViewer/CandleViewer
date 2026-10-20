"""E30-D02 order-ticket audit: WCAG contrast matrix + CVD simulation over the real token JSON.

Standalone, offline, stdlib only. Resolves every theme (`dark`, `light`, `high-contrast`) exactly as
`packages/ui/tokens/tests/verify_tokens.py` does (same loader, same alias resolution, same theme
layering from `themes.json`), measures every foreground/background pair the SCR-060 spec
(`docs/design/E30/E30-D02.md`) binds, and simulates deuteranopia, protanopia and tritanopia over
every state colour with the Brettel/Vienot projection of `docs/research/_tools/cvd_simulate.py`.
The contrast formula is `contrast_ratio()` from `docs/design/_tools/contrast_check.py` (imported,
not re-implemented), so the numbers agree with E30-D01's badge matrix, E11-D02's chassis audit and
E09-D03's.

Usage: python3 -I docs/design/_tools/e30_d02_ticket_audit.py   (prints Markdown; exit 1 on a FAIL)

A PASS/FAIL verdict applies the role's bar (text 4.5:1, non-text 3:1, `hc-text` 7:1 per
`05-accessibility-standard.md` §5 items 1, 2, 3 and 6; the hc-text rows are gated in the
high-contrast theme only, the AAA stretch of §5 item 3 is reported per theme). Rows marked
`decorative` carry no meaning (`16-design-system-brief.md` §6 rule 7) and `rejected-*` rows are
pairs the spec considered and designed around — both are reported, never gated. `exempt` rows are
inactive controls (WCAG 1.4.3 exception); the reason text beside them is gated as text. Candidate
tokens that do not exist yet (design-system change requests for E30-D04) are prefixed `CR:` and
measured on the primitive or token they would alias, never on an invented hex. The hpe Fable lens round 1 (F-6) added the light `danger.default` candidates and the boundary-vs-ARMED CVD row.
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
BAR = {
    "text": 4.5,
    "non-text": 3.0,
    "hc-text": 7.0,
    "decorative": None,
    "exempt": None,
    "rejected-text": 4.5,
    "rejected-non-text": 3.0,
    "rejected-hc-text": 7.0,
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
    return {k: verify.resolve(v["$value"], allt) for k, v in allt.items() if v.get("$type") == "color"}


T = {n: resolve_theme(n) for n in THEMES}

# Candidate aliases for the E30-D04 change requests (CR:). Values are existing primitives or tokens per theme.
CR = {
    # a text-role danger token: the field-error text and the rejected class line, if the owner prefers a red
    # error text to the adopted text.primary + glyph pair (CR-2 of the spec)
    "CR:color.text.danger": {"dark": "palette.red.300", "light": "palette.light.red.700", "high-contrast": "palette.red.300"},
    # the input-field boundary at rest: the quietest existing token that clears 3:1 on the panel surface in every
    # theme (CR-1 of the spec); `color.border.default` / `.strong` are measured beside it as the rejected pairs
    "CR:color.border.input": {"dark": "color.text.tertiary", "light": "color.text.tertiary", "high-contrast": "color.text.tertiary"},
    "CR:color.border.input (alt: text.disabled)": {"dark": "color.text.disabled", "light": "color.text.disabled", "high-contrast": "color.text.disabled"},
    # the light theme resolves `status.danger.strong` and `status.warning.strong` to the same primitive
    # (`palette.light.amber.300`), so a danger glyph and an attention glyph are one colour there; CR-3 proposes
    # the existing dark-red primitive for the light danger glyph (dark and hc unchanged)
    "CR:color.status.danger.strong (light = light.red.700)": {"dark": "color.status.danger.strong", "light": "palette.light.red.700", "high-contrast": "color.status.danger.strong"},
    # the light theme also resolves `status.danger.default` to an amber (`palette.light.amber.500`), so the 2 px invalid
    # field boundary shares its hue with the ARMED pill border; CR-3 extends to it with an existing light red that is
    # not the SELL primitive (`palette.light.red.500`): both candidates the review named are measured, the adopted one
    # is the darker `.350` (dark and hc unchanged: `palette.red.600`)
    "CR:color.status.danger.default (light = light.red.350)": {"dark": "color.status.danger.default", "light": "palette.light.red.350", "high-contrast": "color.status.danger.default"},
    "CR:color.status.danger.default (light = light.red.400)": {"dark": "color.status.danger.default", "light": "palette.light.red.400", "high-contrast": "color.status.danger.default"},
}


def col(theme: str, token: str) -> str:
    if token in CR:
        return T[theme][CR[token][theme]]
    return T[theme][token]


# (element, fg token, bg token, role)
PAIRS: list[tuple[str, str, str, str]] = [
    # --- text on the panel and in the input wells -------------------------------------------------------------
    ("fieldset legend / section heading; full-intent submit line in the footer", "color.text.primary", "color.surface.canvas", "text"),
    ("field label (Type, Price, Size, Stop-loss …); the reason text under a disabled control", "color.text.secondary", "color.surface.canvas", "text"),
    ("input value (mono) and read-out numbers in the input well", "color.text.primary", "color.surface.app", "text"),
    ("input caption: '(rounded to nearest tick)', unit suffix, placeholder", "color.text.tertiary", "color.surface.app", "text"),
    ("computed read-out line (= notional · % equity · risk USDT · R); opens-vs-reduces line", "color.text.primary", "color.surface.canvas", "text"),
    ("read-out unit words, helper labels (bid / ask / mid), footer est. fee · slip · margin", "color.text.secondary", "color.surface.canvas", "text"),
    ("chip / pill text: env badge, presets, price-helper chips, kbd hints", "color.text.primary", "color.surface.raised", "text"),
    ("chip secondary text: '(estimated)', kbd hint, non-binding limit", "color.text.secondary", "color.surface.raised", "text"),
    ("popover option text (TIF select, trigger-by select, account select)", "color.text.primary", "color.surface.overlay", "text"),
    ("popover disabled-option reason ('PostOnly is unavailable for market orders')", "color.text.secondary", "color.surface.overlay", "text"),
    ("selected preset / selected order-type tab text", "color.text.primary", "color.surface.selected", "text"),
    # --- the arm indicator, chips and banners ---------------------------------------------------------------------
    ("ARMED pill: 'ARMED 4:32 · Main · 0.250 BTC' and the hotkeys-paused line", "color.text.primary", "color.status.warning.subtle", "text"),
    ("LOCKED / UNKNOWN pill text; disconnected banner text", "color.text.primary", "color.surface.raised", "text"),
    ("binding LimitsChip text; clamp message ('reduced from 1.2 to 0.8 by max_position_notional')", "color.text.primary", "color.status.warning.subtle", "text"),
    ("non-binding LimitsChip text", "color.text.secondary", "color.surface.raised", "text"),
    ("rejected inline (CMP-027 role=alert) text; lockout / frozen banner text", "color.text.primary", "color.status.danger.subtle", "text"),
    ("protective-stop-pending banner text (sustained, role=alert)", "color.text.primary", "color.status.danger.subtle", "text"),
    ("accepted banner text ('Accepted — stop 63 900.0 held by the exchange')", "color.text.primary", "color.status.success.subtle", "text"),
    ("SafetyInvariantNotice (role=note) text; pending-key notice; value-change highlight", "color.text.primary", "color.status.info.subtle", "text"),
    ("stale field value under the CMP-078 shade", "color.data-confidence.stale.text", "color.data-confidence.stale.surface", "text"),
    ("disconnected banner text (token name)", "color.data-confidence.disconnected.text", "color.surface.raised", "text"),
    # --- the submit button: side colour as fill, label in the inverse text token ----------------------------------
    ("BUY submit / side-toggle label — adopted (D3): text.inverse on the buy fill", "color.text.inverse", "color.buy.default", "text"),
    ("SELL submit / side-toggle label — adopted (D3)", "color.text.inverse", "color.sell.default", "text"),
    ("BUY label — REJECTED pair (text.on-action, white, on the buy fill)", "color.text.on-action", "color.buy.default", "rejected-text"),
    ("SELL label — REJECTED pair (white on the sell fill)", "color.text.on-action", "color.sell.default", "rejected-text"),
    ("BUY label, 05 §5 item 3 AAA target (7:1) — reported per theme, gated in hc", "color.text.inverse", "color.buy.default", "hc-text"),
    ("SELL label, 05 §5 item 3 AAA target (7:1) — reported per theme, gated in hc", "color.text.inverse", "color.sell.default", "hc-text"),
    ("env badge text (LIVE / DEMO), 05 §5 item 3 AAA target", "color.text.primary", "color.surface.raised", "hc-text"),
    # --- field errors ---------------------------------------------------------------------------------------------
    ("field error text — REJECTED pair (status.danger.default as text)", "color.status.danger.default", "color.surface.canvas", "rejected-text"),
    ("field error text — adopted (D16): text.primary + danger glyph + danger boundary", "color.text.primary", "color.surface.canvas", "text"),
    ("CR-2: color.text.danger on the panel", "CR:color.text.danger", "color.surface.canvas", "text"),
    ("CR-2: color.text.danger in the input well", "CR:color.text.danger", "color.surface.app", "text"),
    ("disabled control label — exempt (WCAG 1.4.3 inactive); the reason text is gated above", "color.text.disabled", "color.surface.raised", "exempt"),
    # --- component boundaries and glyphs (non-text 3:1) ----------------------------------------------------------
    ("input boundary at rest — REJECTED pair (border.default)", "color.border.default", "color.surface.canvas", "rejected-non-text"),
    ("input boundary at rest — REJECTED pair (border.strong)", "color.border.strong", "color.surface.canvas", "rejected-non-text"),
    ("input boundary at rest — adopted (CR-1): color.border.input = {color.text.tertiary}, 1 px", "CR:color.border.input", "color.surface.canvas", "non-text"),
    ("input boundary at rest — alternative measured (text.disabled)", "CR:color.border.input (alt: text.disabled)", "color.surface.canvas", "non-text"),
    ("input boundary focused: CMP-039 ring 2 px on the panel", "color.focus.ring", "color.surface.canvas", "non-text"),
    ("focus ring on raised chrome (chips, presets, pills)", "color.focus.ring", "color.surface.raised", "non-text"),
    ("focus ring on the BUY button — REJECTED pair (ring directly on the fill)", "color.focus.ring", "color.buy.default", "rejected-non-text"),
    ("focus ring on the SELL button — REJECTED pair", "color.focus.ring", "color.sell.default", "rejected-non-text"),
    ("focus ring on the submit button — adopted (D3): ring outside a 1 px surface.canvas halo; ring vs canvas", "color.focus.ring", "color.surface.canvas", "non-text"),
    ("invalid input boundary 2 px (danger.default) — amber in light until CR-3", "color.status.danger.default", "color.surface.canvas", "non-text"),
    ("CR-3: light invalid boundary candidate light.red.350 on the panel — adopted", "CR:color.status.danger.default (light = light.red.350)", "color.surface.canvas", "non-text"),
    ("CR-3: light invalid boundary candidate light.red.350 in the input well — adopted", "CR:color.status.danger.default (light = light.red.350)", "color.surface.app", "non-text"),
    ("CR-3: light invalid boundary candidate light.red.400 on the panel — measured, not adopted", "CR:color.status.danger.default (light = light.red.400)", "color.surface.canvas", "non-text"),
    ("CR-3: light invalid boundary candidate light.red.400 in the input well — measured, not adopted", "CR:color.status.danger.default (light = light.red.400)", "color.surface.app", "non-text"),
    ("field error glyph; invalid boundary alternative (danger.strong)", "color.status.danger.strong", "color.surface.canvas", "non-text"),
    ("ARMED pill glyph (unlock / bolt) and 1 px border", "color.status.warning.strong", "color.status.warning.subtle", "non-text"),
    ("LOCKED pill lock glyph", "color.text.secondary", "color.surface.raised", "non-text"),
    ("UNKNOWN pill '?' glyph", "color.status.warning.strong", "color.surface.raised", "non-text"),
    ("rejected / lockout glyph; pending-stop shield-off glyph and hatched edge", "color.status.danger.strong", "color.status.danger.subtle", "non-text"),
    ("accepted check glyph", "color.status.success.strong", "color.status.success.subtle", "non-text"),
    ("SafetyInvariantNotice / pending-key info glyph", "color.status.info.strong", "color.status.info.subtle", "non-text"),
    ("env LIVE border + dot on the neutral pill (E30-D01 default)", "color.env.live", "color.surface.raised", "non-text"),
    ("env DEMO border + dot on the neutral pill", "color.env.demo", "color.surface.raised", "non-text"),
    ("LIVE chrome accent: 2 px rule under the panel header", "color.env.live", "color.surface.canvas", "non-text"),
    ("DEMO chrome accent: 2 px rule under the panel header", "color.env.demo", "color.surface.canvas", "non-text"),
    ("order-type tab selected underline — REJECTED pair (action.primary.default = color.env.demo's primitive in dark and light)", "color.action.primary.default", "color.surface.canvas", "rejected-non-text"),
    ("order-type tab selected underline — adopted (D5): 2 px text.primary rule + surface.selected fill", "color.text.primary", "color.surface.canvas", "non-text"),
    ("CR-3: light danger glyph on the rejected / lockout / pending-stop fill", "CR:color.status.danger.strong (light = light.red.700)", "color.status.danger.subtle", "non-text"),
    ("CR-3: light danger glyph on raised chrome (disconnected banner)", "CR:color.status.danger.strong (light = light.red.700)", "color.surface.raised", "non-text"),
    ("CR-3: light danger glyph on the panel (field error glyph)", "CR:color.status.danger.strong (light = light.red.700)", "color.surface.canvas", "non-text"),
    ("BUY side-toggle selected fill vs the panel", "color.buy.default", "color.surface.canvas", "non-text"),
    ("SELL side-toggle selected fill vs the panel", "color.sell.default", "color.surface.canvas", "non-text"),
    ("stale indicator (CMP-078) on the shaded field", "color.data-confidence.stale.indicator", "color.data-confidence.stale.surface", "non-text"),
    ("disconnected glyph on the banner — REJECTED pair (danger.default)", "color.data-confidence.disconnected.indicator", "color.surface.raised", "rejected-non-text"),
    ("disconnected glyph on the banner — adopted (danger.strong)", "color.status.danger.strong", "color.surface.raised", "non-text"),
    ("selected preset border (reinforcement beside the check glyph)", "color.border.strong", "color.surface.selected", "decorative"),
    ("input well fill vs the panel (reinforcement only; the boundary carries 1.4.11)", "color.surface.app", "color.surface.canvas", "decorative"),
    ("section divider hairline", "color.border.default", "color.surface.canvas", "decorative"),
    ("(estimated) hatch over the greyed preview (texture)", "color.border.strong", "color.surface.canvas", "decorative"),
]

# CVD: colour pairs that must stay distinguishable without their text (ΔE76 ≥ 5.0 JND floor, tools/contrast).
CVD_PAIRS: list[tuple[str, str, str]] = [
    ("BUY fill vs SELL fill", "color.buy.default", "color.sell.default"),
    ("env LIVE vs DEMO (border / accent)", "color.env.live", "color.env.demo"),
    ("ARMED glyph (warning.strong) vs LIVE border (env.live)", "color.status.warning.strong", "color.env.live"),
    ("ARMED glyph (warning.strong) vs danger glyph (danger.strong)", "color.status.warning.strong", "color.status.danger.strong"),
    ("ARMED fill (warning.subtle) vs rejected fill (danger.subtle)", "color.status.warning.subtle", "color.status.danger.subtle"),
    ("accepted fill (success.subtle) vs ARMED fill (warning.subtle)", "color.status.success.subtle", "color.status.warning.subtle"),
    ("accepted glyph (success.strong) vs BUY fill", "color.status.success.strong", "color.buy.default"),
    ("invalid boundary (danger.default) vs SELL fill", "color.status.danger.default", "color.sell.default"),
    ("env LIVE vs SELL fill (E30-D01 F5)", "color.env.live", "color.sell.default"),
    ("focus ring vs tab underline (action.primary)", "color.focus.ring", "color.action.primary.default"),
    ("env DEMO vs tab underline (action.primary)", "color.env.demo", "color.action.primary.default"),
    ("stale indicator vs ARMED glyph (same token in dark)", "color.data-confidence.stale.indicator", "color.status.warning.strong"),
    ("CR-2 text.danger vs SELL fill", "CR:color.text.danger", "color.sell.default"),
    ("CR-3 light danger glyph vs ARMED glyph (warning.strong)", "CR:color.status.danger.strong (light = light.red.700)", "color.status.warning.strong"),
    ("invalid boundary (danger.default) vs ARMED border / glyph (warning.strong)", "color.status.danger.default", "color.status.warning.strong"),
    ("CR-3 light boundary candidate light.red.350 vs ARMED glyph (warning.strong)", "CR:color.status.danger.default (light = light.red.350)", "color.status.warning.strong"),
    ("CR-3 light boundary candidate light.red.350 vs SELL fill", "CR:color.status.danger.default (light = light.red.350)", "color.sell.default"),
    ("CR-3 light boundary candidate light.red.400 vs SELL fill", "CR:color.status.danger.default (light = light.red.400)", "color.sell.default"),
]
JND = 5.0


def main() -> int:
    failed = 0
    print("## A. Contrast matrix (ratio per theme; bar per role)\n")
    print("| Element | fg | bg | role | dark | light | hc | verdict |")
    print("|---|---|---|---|---|---|---|---|")
    for element, fg, bg, role in PAIRS:
        vals = [ratio(col(t, fg), col(t, bg)) for t in THEMES]
        bar = BAR[role]
        if bar is None:
            verdict = "decorative (not gated)" if role == "decorative" else "exempt (not gated)"
        else:
            if role.endswith("hc-text"):
                bad = ["high-contrast"] if vals[2] < bar else []
                below7 = [THEMES[i] for i, v in enumerate(vals[:2]) if v < bar]
            else:
                bad = [THEMES[i] for i, v in enumerate(vals) if v < bar]
                below7 = []
            verdict = "PASS" if not bad else "FAIL: " + ", ".join(bad)
            if role.endswith("hc-text") and below7 and not bad:
                verdict = "PASS (hc); AAA stretch not met in " + ", ".join(below7)
            if role.startswith("rejected"):
                verdict = ("rejected by design — would " + verdict) if bad else "rejected by design (passes; not used — see the spec)"
            elif bad and not element.startswith("CR") and "alternative measured" not in element:
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
            worst = min(d)
            verdict = "distinct" if worst >= JND else "COLLAPSES (text/shape carries it)"
            print(f"| {name} | {t} | {d[0]:.1f} | {d[1]:.1f} | {d[2]:.1f} | {d[3]:.1f} | {verdict} |")

    print("\n## D. State colours under simulation (hex), for the board annotations\n")
    print("| token | theme | normal | protan | deutan | tritan |")
    print("|---|---|---|---|---|---|")
    for tok in [
        "color.buy.default", "color.sell.default", "color.env.live", "color.env.demo",
        "color.status.warning.strong", "color.status.warning.subtle", "color.status.danger.strong", "color.status.danger.default",
        "color.status.danger.subtle", "color.status.success.strong", "color.status.info.strong",
        "color.focus.ring", "color.action.primary.default", "color.data-confidence.stale.indicator",
    ]:
        for t in THEMES:
            h = col(t, tok)
            print(f"| `{tok}` | {t} | {h} | {cvd.simulate(h, 'protanopia')} | {cvd.simulate(h, 'deuteranopia')} | {cvd.simulate(h, 'tritanopia')} |")

    print(f"\nFAIL count (gated rows only): {failed}")
    return 1 if failed else 0


if __name__ == "__main__":
    raise SystemExit(main())
