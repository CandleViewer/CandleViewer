"""E42-D02 admin-area audit: WCAG contrast matrix + CVD simulation over the real token JSON.

Standalone, offline, stdlib only. Resolves every theme (`dark`, `light`, `high-contrast`) exactly as
`packages/ui/tokens/tests/verify_tokens.py` does (same loader, same alias resolution, same theme
layering from `themes.json`), measures every foreground/background pair the admin wireframe spec
(`docs/design/E42/E42-D02.md`) binds, and simulates deuteranopia, protanopia and tritanopia over
every state colour with the Brettel/Vienot projection of `docs/research/_tools/cvd_simulate.py`.
The contrast formula is `contrast_ratio()` from `docs/design/_tools/contrast_check.py` (imported,
not re-implemented), so the numbers agree with E11-D02's, E30-D01's and E09-D03's.

Usage: python3 -I docs/design/_tools/e42_d02_admin_audit.py   (prints Markdown; exit 1 on a FAIL)

A PASS/FAIL verdict applies the role's bar (text 4.5:1, non-text 3:1, `hc-text` 7:1 per
`05-accessibility-standard.md` §5 item 6; every gated row counts, the hc-text rows included); rows
marked `decorative` carry no meaning (`16-design-system-brief.md` §6 rule 7), `exempt` rows are
disabled controls (WCAG 1.4.3 / 1.4.11 exempt them; reported so the design does not rely on them)
and `rejected-*` rows are pairs the spec considered and designed around — none of those three is
gated. Candidate tokens that do not exist yet (design-system change requests for the E05 token
owner, spec §11.4) are prefixed `CR:` and
measured on the primitive they would alias, never on an invented hex.
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
        raise RuntimeError(f"cannot load {path}")
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
    return {
        k: verify.resolve(v["$value"], allt) for k, v in allt.items() if v.get("$type") == "color"
    }


T = {n: resolve_theme(n) for n in THEMES}

# Candidate aliases for the change requests (CR:).
# Values are existing primitives or tokens per theme.
CR = {
    # CMP-087's catalogued `color.surface.admin-tint` does not exist in any token set:
    # the admin header band.
    "CR:color.surface.admin-tint": {
        "dark": "palette.purple.900",
        "light": "palette.purple.400",
        "high-contrast": "palette.purple.900",
    },
    # The 4 px admin accent rule on the band and the active admin nav entry.
    "CR:color.border.admin": {
        "dark": "palette.purple.400",
        "light": "palette.purple.600",
        "high-contrast": "palette.purple.400",
    },
    # CMP-095's catalogued `color.chip.dev` does not exist: the flag chip takes the info tone.
    "CR:color.chip.dev": {
        "dark": "color.status.info.subtle",
        "light": "color.status.info.subtle",
        "high-contrast": "color.status.info.subtle",
    },
    # Text-field boundary (password, TOTP, typed-token, reason fields): no input-border token
    # exists and
    # `color.border.default` measures far under 3:1 on the dialog surface (reported below).
    "CR:color.border.input": {
        "dark": "palette.neutral.600",
        "light": "palette.light.neutral.500",
        "high-contrast": "palette.neutral.600",
    },
}


def col(theme: str, token: str) -> str:
    if token in CR:
        return col(theme, CR[token][theme])
    return T[theme][token]


# (element, fg token, bg token, role)
PAIRS: list[tuple[str, str, str, str]] = [
    # --- shell (CMP-087), §2 ---
    (
        "page title, body text, table cells on the page surface",
        "color.text.primary",
        "color.surface.app",
        "text",
    ),
    (
        "secondary text on the page surface (descriptions, empty-state cause sentence)",
        "color.text.secondary",
        "color.surface.app",
        "text",
    ),
    (
        "tertiary text on the page surface (as-of clocks, audit markers, footers)",
        "color.text.tertiary",
        "color.surface.app",
        "text",
    ),
    ("tertiary text on tiles and cards", "color.text.tertiary", "color.surface.raised", "text"),
    (
        "CR: admin header band — 'Admin' label and route title on the tint",
        "color.text.primary",
        "CR:color.surface.admin-tint",
        "text",
    ),
    (
        "CR: admin header band — hc AAA target (7:1)",
        "color.text.primary",
        "CR:color.surface.admin-tint",
        "hc-text",
    ),
    (
        "CR: admin header band — REJECTED pair (secondary text directly on the tint; "
        "the badge is a raised pill instead)",
        "color.text.secondary",
        "CR:color.surface.admin-tint",
        "rejected-text",
    ),
    (
        "CR: admin accent rule (4 px): the band's bottom edge against the page surface",
        "CR:color.border.admin",
        "color.surface.app",
        "non-text",
    ),
    (
        "CR: admin accent rule against the band — REJECTED as a carrier "
        "(the edge against the page is the carrier)",
        "CR:color.border.admin",
        "CR:color.surface.admin-tint",
        "rejected-non-text",
    ),
    (
        "unlock badge pill on the band (raised pill, secondary text)",
        "color.text.secondary",
        "color.surface.raised",
        "text",
    ),
    (
        "unlock badge pill fill against the band",
        "color.surface.raised",
        "CR:color.surface.admin-tint",
        "decorative",
    ),
    ("admin nav / user-menu entry text", "color.text.primary", "color.surface.raised", "text"),
    (
        "admin nav entry, current (aria-current) on the selected surface",
        "color.text.primary",
        "color.surface.selected",
        "text",
    ),
    (
        "unlock badge text, normal (variant a)",
        "color.text.secondary",
        "color.surface.raised",
        "text",
    ),
    (
        "unlock badge, 5 min left — text",
        "color.text.primary",
        "color.status.warning.subtle",
        "text",
    ),
    (
        "unlock badge, 5 min left — glyph",
        "color.status.warning.strong",
        "color.status.warning.subtle",
        "non-text",
    ),
    (
        "unlock badge, 1 min left / expired — text",
        "color.text.primary",
        "color.status.danger.subtle",
        "text",
    ),
    (
        "unlock badge, 1 min left / expired — glyph",
        "color.status.danger.strong",
        "color.status.danger.subtle",
        "non-text",
    ),
    ("link text on the page surface", "color.text.link", "color.surface.app", "text"),
    (
        "link text on tiles (tile deep links, 'Open user')",
        "color.text.link",
        "color.surface.raised",
        "text",
    ),
    ("focus ring on the page surface", "color.focus.ring", "color.surface.app", "non-text"),
    ("focus ring on tiles / rows", "color.focus.ring", "color.surface.raised", "non-text"),
    ("focus ring on dialogs", "color.focus.ring", "color.surface.overlay", "non-text"),
    (
        "skip link / 'Exit view-as' button text",
        "color.text.on-action",
        "color.action.primary.default",
        "text",
    ),
    # --- tiles, strips, tables (SCR-120, SCR-121, SCR-135, SCR-143, SCR-144, SCR-145, SCR-146),
    # §4.2, §6 ---
    ("tile value / row text on tiles", "color.text.primary", "color.surface.raised", "text"),
    ("tile label / unit text", "color.text.secondary", "color.surface.raised", "text"),
    (
        "tile tone ok — glyph (check)",
        "color.status.success.strong",
        "color.surface.raised",
        "non-text",
    ),
    (
        "tile tone ok — REJECTED pair (success.default as the glyph)",
        "color.status.success.default",
        "color.surface.raised",
        "rejected-non-text",
    ),
    (
        "tile tone warning — glyph (triangle)",
        "color.status.warning.strong",
        "color.surface.raised",
        "non-text",
    ),
    (
        "tile tone warning — REJECTED pair (warning.default as the glyph)",
        "color.status.warning.default",
        "color.surface.raised",
        "rejected-non-text",
    ),
    (
        "tile tone down / error — glyph (octagon)",
        "color.status.danger.strong",
        "color.surface.raised",
        "non-text",
    ),
    (
        "tile tone down / error — REJECTED pair (danger.default as the glyph)",
        "color.status.danger.default",
        "color.surface.raised",
        "rejected-non-text",
    ),
    (
        "tile 'stale since' — clock glyph (CMP-239 stale indicator)",
        "color.data-confidence.stale.indicator",
        "color.surface.raised",
        "non-text",
    ),
    (
        "tile 'stale since' / 'unavailable' word",
        "color.text.primary",
        "color.surface.raised",
        "text",
    ),
    ("tile 'as of HH:MM:SS' clock text", "color.text.tertiary", "color.surface.raised", "text"),
    (
        "'Needs your action' strip item text",
        "color.text.primary",
        "color.status.warning.subtle",
        "text",
    ),
    (
        "'Needs your action' strip — critical item text (tamper check failed)",
        "color.text.primary",
        "color.status.danger.subtle",
        "text",
    ),
    ("table header text", "color.text.secondary", "color.surface.hover", "text"),
    (
        "table sort glyph (aria-sort carrier is the header text; glyph reinforces)",
        "color.text.tertiary",
        "color.surface.hover",
        "non-text",
    ),
    ("zebra row text (raised)", "color.text.primary", "color.surface.raised", "text"),
    ("selected / focused row text", "color.text.primary", "color.surface.selected", "text"),
    ("row hover text", "color.text.primary", "color.surface.hover", "text"),
    ("status chip 'Active' text", "color.text.primary", "color.status.success.subtle", "text"),
    (
        "status chip 'Active' glyph",
        "color.status.success.strong",
        "color.status.success.subtle",
        "non-text",
    ),
    ("status chip 'Invited' text", "color.text.primary", "color.status.info.subtle", "text"),
    (
        "status chip 'Invited' glyph",
        "color.status.info.strong",
        "color.status.info.subtle",
        "non-text",
    ),
    ("status chip 'Disabled' text (neutral)", "color.text.primary", "color.neutral.subtle", "text"),
    (
        "status chip 'Locked out (sign-in)' text",
        "color.text.primary",
        "color.status.warning.subtle",
        "text",
    ),
    (
        "status chip 'Trading locked (risk)' text",
        "color.text.primary",
        "color.status.danger.subtle",
        "text",
    ),
    (
        "severity chip HIGH / CRITICAL text",
        "color.text.primary",
        "color.status.danger.subtle",
        "text",
    ),
    (
        "severity chip HIGH / CRITICAL glyph",
        "color.status.danger.strong",
        "color.status.danger.subtle",
        "non-text",
    ),
    ("severity chip MED text", "color.text.primary", "color.status.warning.subtle", "text"),
    ("severity chip LOW / INFO text", "color.text.primary", "color.surface.hover", "text"),
    (
        "CR: CMP-095 flag chip text (`color.chip.dev` → info.subtle)",
        "color.text.primary",
        "CR:color.chip.dev",
        "text",
    ),
    ("CR: CMP-095 flag chip glyph", "color.status.info.strong", "CR:color.chip.dev", "non-text"),
    (
        "flag toggle ON track (CMP-004) — state carried by the label word; track is reinforcement",
        "color.action.primary.default",
        "color.surface.raised",
        "non-text",
    ),
    (
        "disabled control text (gated flag toggle, disabled confirm) — exempt",
        "color.text.disabled",
        "color.surface.raised",
        "exempt",
    ),
    (
        "disabled confirm button text on the dialog — exempt",
        "color.text.disabled",
        "color.surface.selected",
        "exempt",
    ),
    ("empty-state heading", "color.text.primary", "color.surface.app", "text"),
    (
        "progress bar fill (backup / restore job)",
        "color.action.primary.default",
        "color.surface.raised",
        "non-text",
    ),
    ("progress bar track", "color.surface.hover", "color.surface.raised", "decorative"),
    (
        "sparkline line (CMP-024; table alternative carries the data)",
        "color.text.secondary",
        "color.surface.raised",
        "non-text",
    ),
    ("skeleton blocks (loading)", "color.surface.hover", "color.surface.raised", "decorative"),
    ("tile / card border", "color.border.default", "color.surface.app", "decorative"),
    # --- dialogs (the ladder, §4.1), gate (SCR-149), §6.2 ---
    ("dialog title / body text", "color.text.primary", "color.surface.overlay", "text"),
    (
        "dialog secondary text (consequence list lead-in, step-up state line)",
        "color.text.secondary",
        "color.surface.overlay",
        "text",
    ),
    (
        "dialog audit marker text ('Recorded in the audit log · users.disable')",
        "color.text.tertiary",
        "color.surface.overlay",
        "text",
    ),
    ("primary button text", "color.text.on-action", "color.action.primary.default", "text"),
    (
        "destructive confirm button — candidate A (on-action on danger.default)",
        "color.text.on-action",
        "color.status.danger.default",
        "rejected-text",
    ),
    (
        "destructive confirm button — candidate B (inverse on danger.strong)",
        "color.text.inverse",
        "color.status.danger.strong",
        "rejected-text",
    ),
    (
        "destructive confirm button — adopted (D3): text on danger.subtle fill",
        "color.text.primary",
        "color.status.danger.subtle",
        "text",
    ),
    (
        "destructive confirm button — adopted (D3): danger.strong border / glyph",
        "color.status.danger.strong",
        "color.status.danger.subtle",
        "non-text",
    ),
    (
        "destructive confirm button — adopted (D3): fill against the dialog surface",
        "color.status.danger.subtle",
        "color.surface.overlay",
        "decorative",
    ),
    (
        "secondary / Cancel button text",
        "color.text.primary",
        "color.action.secondary.default",
        "text",
    ),
    (
        "text-field value (password, TOTP, typed token, reason)",
        "color.text.primary",
        "color.surface.sunken",
        "text",
    ),
    (
        "text-field boundary — REPORTED pair (border.default on the dialog surface)",
        "color.border.default",
        "color.surface.overlay",
        "rejected-non-text",
    ),
    (
        "text-field boundary — REPORTED pair (border.strong on the dialog surface)",
        "color.border.strong",
        "color.surface.overlay",
        "rejected-non-text",
    ),
    (
        "CR: text-field boundary (`color.border.input`)",
        "CR:color.border.input",
        "color.surface.overlay",
        "non-text",
    ),
    (
        "CR: text-field boundary on the page surface (inline filters)",
        "CR:color.border.input",
        "color.surface.app",
        "non-text",
    ),
    (
        "inline error text (CMP-027) — adopted: text on danger.subtle",
        "color.text.primary",
        "color.status.danger.subtle",
        "text",
    ),
    (
        "inline error text — REJECTED pair (danger.strong as text on the dialog)",
        "color.status.danger.strong",
        "color.surface.overlay",
        "rejected-text",
    ),
    (
        "typed-token field 'matches' check glyph",
        "color.status.success.strong",
        "color.surface.overlay",
        "non-text",
    ),
    (
        "blast-radius counts (type.num) in the dialog",
        "color.text.primary",
        "color.surface.overlay",
        "text",
    ),
    (
        "'Step-up spent' / 'This always needs a fresh code.' line",
        "color.text.secondary",
        "color.surface.overlay",
        "text",
    ),
    (
        "SCR-149 gate scrim over the page (60 %, decorative)",
        "color.surface.sunken",
        "color.surface.app",
        "decorative",
    ),
    # --- banners (SCR-124, SCR-135, SCR-148, SCR-152/153 consumed), §6 ---
    ("view-as banner text", "color.text.primary", "color.status.info.subtle", "text"),
    (
        "view-as banner text — hc AAA target (7:1)",
        "color.text.primary",
        "color.status.info.subtle",
        "hc-text",
    ),
    (
        "view-as banner glyph (eye) and top rule",
        "color.status.info.strong",
        "color.status.info.subtle",
        "non-text",
    ),
    (
        "view-as banner top rule against the page",
        "color.status.info.strong",
        "color.surface.app",
        "non-text",
    ),
    (
        "view-as countdown, 5 min left — text",
        "color.text.primary",
        "color.status.warning.subtle",
        "text",
    ),
    ("tamper-check FAILED banner text", "color.text.primary", "color.status.danger.subtle", "text"),
    (
        "tamper-check FAILED banner glyph",
        "color.status.danger.strong",
        "color.status.danger.subtle",
        "non-text",
    ),
    (
        "tamper-check verified line (page footer)",
        "color.text.secondary",
        "color.surface.app",
        "text",
    ),
    (
        "maintenance-on banner text (CMP-028 warning)",
        "color.text.primary",
        "color.status.warning.subtle",
        "text",
    ),
    (
        "maintenance-on banner glyph",
        "color.status.warning.strong",
        "color.status.warning.subtle",
        "non-text",
    ),
    ("degraded banner text (CMP-092)", "color.text.primary", "color.status.warning.subtle", "text"),
    (
        "env badge text (LIVE / DEMO) on the trading tile and strip items",
        "color.text.primary",
        "color.surface.raised",
        "hc-text",
    ),
    ("env badge LIVE border on the pill", "color.env.live", "color.surface.raised", "non-text"),
    ("env badge DEMO border on the pill", "color.env.demo", "color.surface.raised", "non-text"),
    ("404 / 403 page heading and body", "color.text.primary", "color.surface.app", "text"),
    (
        "403 correlation id (type.num, selectable)",
        "color.text.secondary",
        "color.surface.app",
        "text",
    ),
    (
        "hash view (entry_hash / prev_hash, type.num) in the drawer",
        "color.text.primary",
        "color.surface.overlay",
        "text",
    ),
]

# CVD: colour pairs that must stay distinguishable without their text
# (ΔE76 ≥ 5.0 JND floor, tools/contrast).
CVD_PAIRS: list[tuple[str, str, str]] = [
    ("tile warning vs down glyph", "color.status.warning.strong", "color.status.danger.strong"),
    ("tile ok vs warning glyph", "color.status.success.strong", "color.status.warning.strong"),
    ("tile ok vs down glyph", "color.status.success.strong", "color.status.danger.strong"),
    (
        "view-as (info) vs maintenance (warning) banner glyph",
        "color.status.info.strong",
        "color.status.warning.strong",
    ),
    (
        "view-as (info) vs tamper-failed (danger) banner glyph",
        "color.status.info.strong",
        "color.status.danger.strong",
    ),
    ("env LIVE vs DEMO", "color.env.live", "color.env.demo"),
    ("CR: admin accent vs env LIVE", "CR:color.border.admin", "color.env.live"),
    ("CR: admin accent vs env DEMO", "CR:color.border.admin", "color.env.demo"),
    ("CR: admin accent vs focus ring", "CR:color.border.admin", "color.focus.ring"),
    ("CR: admin accent vs primary action", "CR:color.border.admin", "color.action.primary.default"),
    ("CR: admin band vs page surface", "CR:color.surface.admin-tint", "color.surface.app"),
    ("CR: admin band vs raised surface", "CR:color.surface.admin-tint", "color.surface.raised"),
    (
        "status chip Active (success.subtle) vs Trading locked (danger.subtle) fill",
        "color.status.success.subtle",
        "color.status.danger.subtle",
    ),
    (
        "status chip Locked out (warning.subtle) vs Trading locked (danger.subtle) fill",
        "color.status.warning.subtle",
        "color.status.danger.subtle",
    ),
    (
        "stale clock glyph vs down glyph",
        "color.data-confidence.stale.indicator",
        "color.status.danger.strong",
    ),
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
            verdict = f"{role} (not gated)"
        else:
            if role.endswith("hc-text"):
                bad = ["high-contrast"] if vals[2] < bar else []
            else:
                bad = [THEMES[i] for i, v in enumerate(vals) if v < bar]
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
            f"| {element} | `{fg}` | `{bg}` | {role} "
            f"| {vals[0]:.2f} | {vals[1]:.2f} | {vals[2]:.2f} | {verdict} |"
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
        "\n## C. CVD simulation "
        "(ΔE76 between the two colours under each deficiency; JND floor 5.0)\n"
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
        "color.status.success.strong",
        "color.status.warning.strong",
        "color.status.danger.strong",
        "color.status.info.strong",
        "color.data-confidence.stale.indicator",
        "color.env.live",
        "color.env.demo",
        "color.focus.ring",
        "color.action.primary.default",
        "CR:color.surface.admin-tint",
        "CR:color.border.admin",
    ]:
        for t in THEMES:
            h = col(t, tok)
            print(
                f"| `{tok}` | {t} | {h} | {cvd.simulate(h, 'protanopia')} "
                f"| {cvd.simulate(h, 'deuteranopia')} | {cvd.simulate(h, 'tritanopia')} |"
            )

    print(f"\nFAIL count (gated rows only): {failed}")
    return 1 if failed else 0


if __name__ == "__main__":
    raise SystemExit(main())
