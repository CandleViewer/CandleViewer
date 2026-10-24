"""E42-D03 admin hi-fi audit: WCAG contrast, follow-up pairs and colour vision over the token JSON.

Standalone, offline, stdlib only, on the method of `e42_d02_admin_audit.py`. Every theme
(`dark`, `light`, `high-contrast`) resolves exactly as `packages/ui/tokens/tests/verify_tokens.py`
resolves it (same loader, same alias resolution, same set layering, checked against
`themes.json`); the ratio is `contrast_ratio()` from `docs/design/_tools/contrast_check.py`
(imported, not re-implemented); ΔE76, L* and the deuteranopia, protanopia and tritanopia
projections are those of `docs/research/_tools/cvd_simulate.py`. It measures every pair the hi-fi
spec (`docs/design/E42/E42-D03.md` §15) groups, the follow-up pairs beside its findings F2 to F4 and
its colour-vision pairs, then regenerates §15's two tables and the numbers §2, §4, §15 and §22 cite.

Usage: python3 -I docs/design/_tools/e42_d03_admin_audit.py   (prints Markdown; exit 1 on a FAIL)

Roles. `text` (4.5:1, WCAG 1.4.3) and `non-text` (3:1, WCAG 1.4.11) rows are gated in every theme,
and one FAIL exits 1. Every gated text row is also measured against the high-contrast theme's 7:1
aim for body text (`05-accessibility-standard.md` §5 item 6): reported, not gated (finding F3).
`decorative` rows carry no meaning (a word, a glyph or a border is the carrier); `exempt` rows bound
inactive (T2 and validity-form) controls, which WCAG 1.4.3 and 1.4.11 exempt, and are reported so
the design never relies on them; `rejected-*` rows are pairs the spec measured and designed around
(F1, F2, F4 and D2's alternative). None of those three is gated. A token that does not exist yet (a
design-system change request for the E05 token owner, spec §15) is prefixed `CR:` and measured on
the token or primitive it would alias, never on an invented hex.
"""

from __future__ import annotations

import importlib.util
import json
from pathlib import Path
from types import ModuleType
from typing import NamedTuple

ROOT = Path(__file__).resolve().parents[3]
TOKENS = ROOT / "packages" / "ui" / "tokens"


def _load(path: Path, name: str) -> ModuleType:
    spec = importlib.util.spec_from_file_location(name, path)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"cannot load {path}")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


verify = _load(TOKENS / "tests" / "verify_tokens.py", "verify_tokens")
contrast_check = _load(ROOT / "docs" / "design" / "_tools" / "contrast_check.py", "contrast_check")
cvd = _load(ROOT / "docs" / "research" / "_tools" / "cvd_simulate.py", "cvd_simulate")

THEMES = ("dark", "light", "high-contrast")
GATED = ("text", "non-text")
BAR: dict[str, float | None] = {
    "text": 4.5,
    "non-text": 3.0,
    "decorative": None,
    "exempt": None,
    "rejected-text": 4.5,
    "rejected-non-text": 3.0,
}
HC_AIM = 7.0  # `05:130`: the high-contrast theme leans to 7:1 for body text (reported, not gated)
JND: float = cvd.JND_FLOOR  # ΔE76 5.0: under it, two colours read as one at a glance
DEFICIENCIES = ("protanopia", "deuteranopia", "tritanopia")


def read_text(path: Path) -> str:
    return path.read_text(encoding="utf-8")


def check_layering() -> None:
    """Fail loudly if `themes.json` and verify_tokens.py ever layer a theme's sets differently."""
    data = json.loads(read_text(TOKENS / "themes.json"))
    sets = {t["name"]: t["sets"] for t in data["themes"] if t.get("group") == "theme"}
    for name in THEMES:
        files = [verify.PRIMITIVES, *verify.THEMES[name]]
        want = [str(f).removesuffix(".tokens.json") for f in files]
        if sets.get(name) != want:
            raise SystemExit(f"themes.json layers {name} as {sets.get(name)}, verify_tokens {want}")


def resolve_theme(name: str) -> dict[str, str]:
    prim = verify.load(verify.PRIMITIVES)
    allt = dict(prim)
    allt.update(verify.merged_set(verify.THEMES[name]))
    return {
        k: str(verify.resolve(v["$value"], allt))
        for k, v in allt.items()
        if v.get("$type") == "color"
    }


check_layering()
T = {n: resolve_theme(n) for n in THEMES}

# Candidate aliases for the change requests (`CR:`), per theme: existing tokens or primitives only.
CR: dict[str, dict[str, str]] = {
    # DS-1 (D2): CMP-087's catalogued `color.surface.admin-tint` exists in no token set; the band is
    # neutral, the raised surface, and its distinctness rides on the words, the rule, the density
    # and the `h1`.
    "CR:color.surface.admin-tint": {t: "color.surface.raised" for t in THEMES},
    # DS-2 (D2): the 4 px admin rule under the band, on the tertiary text token.
    "CR:color.border.admin": {t: "color.text.tertiary" for t in THEMES},
    # DS-3 (deviation (7)): the text-field boundary; `color.border.default` fails it today (F1).
    "CR:color.border.input": {t: "color.text.tertiary" for t in THEMES},
    # D2's measured alternative, a teal rule (Q4): passes, rejected as a new hue meaning.
    "CR:color.border.admin.teal": {
        "dark": "palette.teal.400",
        "light": "palette.teal.600",
        "high-contrast": "palette.teal.400",
    },
}


def col(theme: str, token: str) -> str:
    if token in CR:
        return col(theme, CR[token][theme])
    value = T[theme][token]
    if len(value) != 7 or not value.startswith("#"):
        raise SystemExit(f"{token} is {value} in {theme}: not an opaque #RRGGBB colour")
    return value


def hex_to_rgb(h: str) -> tuple[int, int, int]:
    h = h.lstrip("#")
    return int(h[0:2], 16), int(h[2:4], 16), int(h[4:6], 16)


def ratio(fg: str, bg: str) -> float:
    return float(contrast_check.contrast_ratio(hex_to_rgb(fg), hex_to_rgb(bg)))


class Pair(NamedTuple):
    """One measured pair: what the frames draw, the two tokens and the role that sets its bar."""

    key: str
    element: str
    fg: str
    bg: str
    role: str


# Every pair the frames bind, in the order of the rows of §15's contrast table (one row per item of
# a table cell), then the pairs the table's verdicts and §2 cite, then the decorative and exempt
# edges the text binds outside the table.
PAIRS: list[Pair] = [
    # --- CMP-087 shell (§4): the band, the rule, the (a) badge and the strip ---
    Pair(
        "band.label",
        'band label "◆ Admin area · Users" on DS-1',
        "color.text.primary",
        "CR:color.surface.admin-tint",
        "text",
    ),
    Pair(
        "band.route",
        "band route and the (b) grace line, secondary (SH-5)",
        "color.text.secondary",
        "CR:color.surface.admin-tint",
        "text",
    ),
    Pair(
        "rule.page",
        "DS-2 4 px rule vs the page (a carrier, AC-4)",
        "CR:color.border.admin",
        "color.surface.app",
        "non-text",
    ),
    Pair(
        "rule.band",
        "DS-2 rule vs the band fill above it",
        "CR:color.border.admin",
        "CR:color.surface.admin-tint",
        "non-text",
    ),
    Pair(
        "band.fill",
        "band fill vs the page (not a carrier, D2)",
        "CR:color.surface.admin-tint",
        "color.surface.app",
        "decorative",
    ),
    Pair(
        "badge.unlocked",
        '(a) badge "Admin unlocked · 12:40 left" on its hover pill (SH-1)',
        "color.text.secondary",
        "color.surface.hover",
        "text",
    ),
    Pair(
        "badge.warning",
        "5 min badge and warning strip items: text (SH-2)",
        "color.text.primary",
        "color.status.warning.subtle",
        "text",
    ),
    Pair(
        "badge.danger",
        "1 min and expired badge, critical strip items: text (SH-3, SH-4)",
        "color.text.primary",
        "color.status.danger.subtle",
        "text",
    ),
    Pair(
        "badge.triangle",
        "badge and strip triangle",
        "color.status.warning.strong",
        "color.status.warning.subtle",
        "non-text",
    ),
    Pair(
        "badge.octagon",
        "badge and strip octagon",
        "color.status.danger.strong",
        "color.status.danger.subtle",
        "non-text",
    ),
    Pair(
        "env.live.raised",
        "env badge LIVE border on raised (tiles, strip items)",
        "color.env.live",
        "color.surface.raised",
        "non-text",
    ),
    Pair(
        "env.demo.raised",
        "env badge DEMO border on raised",
        "color.env.demo",
        "color.surface.raised",
        "non-text",
    ),
    Pair(
        "env.live.overlay",
        "env badge LIVE border on overlay (dialogs)",
        "color.env.live",
        "color.surface.overlay",
        "non-text",
    ),
    Pair(
        "env.demo.overlay",
        "env badge DEMO border on overlay (dialogs)",
        "color.env.demo",
        "color.surface.overlay",
        "non-text",
    ),
    # --- the page: CMP-088 PageHeader, links, SCR-154/155 (§4, §11) ---
    Pair("page.h1", "PageHeader `h1`", "color.text.primary", "color.surface.app", "text"),
    Pair(
        "page.meta",
        'meta "All times UTC · as of" and the footer marker (tertiary)',
        "color.text.tertiary",
        "color.surface.app",
        "text",
    ),
    Pair("page.link", "link on the page", "color.text.link", "color.surface.app", "text"),
    Pair(
        "page.body",
        'SCR-154/155 body and the strip\'s "Nothing needs your action" (secondary)',
        "color.text.secondary",
        "color.surface.app",
        "text",
    ),
    Pair(
        "button.primary",
        "primary button, skip link and Exit: on-action on the primary fill",
        "color.text.on-action",
        "color.action.primary.default",
        "text",
    ),
    # --- the focus ring (CMP-039, §13) on every surface tier the frames draw ---
    Pair(
        "focus.app", "focus ring on the page", "color.focus.ring", "color.surface.app", "non-text"
    ),
    Pair(
        "focus.raised",
        "focus ring on raised (tiles, rows)",
        "color.focus.ring",
        "color.surface.raised",
        "non-text",
    ),
    Pair(
        "focus.overlay",
        "focus ring on overlay (dialogs)",
        "color.focus.ring",
        "color.surface.overlay",
        "non-text",
    ),
    Pair(
        "focus.hover",
        "focus ring on hover (a focused menu item)",
        "color.focus.ring",
        "color.surface.hover",
        "non-text",
    ),
    Pair(
        "focus.selected",
        "focus ring on selected (a selected row)",
        "color.focus.ring",
        "color.surface.selected",
        "non-text",
    ),
    Pair(
        "focus.sunken",
        "focus ring on sunken (field values)",
        "color.focus.ring",
        "color.surface.sunken",
        "non-text",
    ),
    Pair(
        "focus.info",
        "focus ring on info.subtle (Exit on the view-as banner)",
        "color.focus.ring",
        "color.status.info.subtle",
        "non-text",
    ),
    Pair(
        "focus.warning",
        "focus ring on warning.subtle (a warning strip item)",
        "color.focus.ring",
        "color.status.warning.subtle",
        "non-text",
    ),
    Pair(
        "focus.danger",
        "focus ring on danger.subtle (a critical strip item, the danger confirm)",
        "color.focus.ring",
        "color.status.danger.subtle",
        "non-text",
    ),
    # --- SCR-120 tiles (§6), CMP-178 ---
    Pair(
        "tile.value",
        "tile value and env badge text",
        "color.text.primary",
        "color.surface.raised",
        "text",
    ),
    Pair("tile.label", "tile label", "color.text.secondary", "color.surface.raised", "text"),
    Pair(
        "tile.asof",
        'tile "as of"; a T2 label and lock on raised (§13); the validity-form label (§12)',
        "color.text.tertiary",
        "color.surface.raised",
        "text",
    ),
    Pair(
        "tile.link",
        "tile heading link (its hc 7:1 aim is F3)",
        "color.text.link",
        "color.surface.raised",
        "text",
    ),
    Pair(
        "tile.retry",
        "Retry on the secondary fill",
        "color.text.primary",
        "color.action.secondary.default",
        "text",
    ),
    Pair(
        "tile.check",
        "tile check (ok)",
        "color.status.success.strong",
        "color.surface.raised",
        "non-text",
    ),
    Pair(
        "tile.triangle",
        "tile triangle (warning)",
        "color.status.warning.strong",
        "color.surface.raised",
        "non-text",
    ),
    Pair(
        "tile.octagon",
        "tile octagon (down)",
        "color.status.danger.strong",
        "color.surface.raised",
        "non-text",
    ),
    Pair(
        "tile.stale",
        "tile stale clock (CMP-239's indicator)",
        "color.data-confidence.stale.indicator",
        "color.surface.raised",
        "non-text",
    ),
    # --- SCR-121 table (§7), CMP-049 ---
    Pair(
        "table.header",
        "table header on its hover fill",
        "color.text.secondary",
        "color.surface.hover",
        "text",
    ),
    Pair(
        "table.sort",
        "sort glyph and the busy spinner on the header (§7)",
        "color.text.tertiary",
        "color.surface.hover",
        "non-text",
    ),
    Pair(
        "table.selected",
        "selected-row text",
        "color.text.primary",
        "color.surface.selected",
        "text",
    ),
    # --- T2 (§13): label and lock glyph on a focused menu item; never on `selected` (F4) ---
    Pair(
        "t2.hover",
        "T2 label and lock on a focused menu item (CMP-041, DJ)",
        "color.text.tertiary",
        "color.surface.hover",
        "text",
    ),
    Pair(
        "t2.selected",
        "T2 label and lock on selected: never drawn, the label takes secondary (F4)",
        "color.text.tertiary",
        "color.surface.selected",
        "rejected-text",
    ),
    # --- status chips (§7, §8): text, then the glyph that carries the state with the word ---
    Pair(
        "chip.active",
        "chip Active text",
        "color.text.primary",
        "color.status.success.subtle",
        "text",
    ),
    Pair(
        "chip.invited",
        "chip Invited text",
        "color.text.primary",
        "color.status.info.subtle",
        "text",
    ),
    Pair(
        "chip.disabled",
        "chip Disabled text",
        "color.text.primary",
        "color.neutral.subtle",
        "text",
    ),
    Pair(
        "chip.locked",
        "chip Locked out and Invite expired text",
        "color.text.primary",
        "color.status.warning.subtle",
        "text",
    ),
    Pair(
        "chip.trading",
        "chip Trading locked text",
        "color.text.primary",
        "color.status.danger.subtle",
        "text",
    ),
    Pair(
        "chip.check",
        "chip check (Active)",
        "color.status.success.strong",
        "color.status.success.subtle",
        "non-text",
    ),
    Pair(
        "chip.ring",
        "chip ring (Invited)",
        "color.status.info.strong",
        "color.status.info.subtle",
        "non-text",
    ),
    Pair(
        "chip.slashed",
        "chip slashed circle (Disabled), secondary",
        "color.text.secondary",
        "color.neutral.subtle",
        "non-text",
    ),
    Pair(
        "chip.triangle",
        "chip triangle (Locked out, Invite expired)",
        "color.status.warning.strong",
        "color.status.warning.subtle",
        "non-text",
    ),
    Pair(
        "chip.octagon",
        "chip octagon (Trading locked)",
        "color.status.danger.strong",
        "color.status.danger.subtle",
        "non-text",
    ),
    # --- meters on raised: CMP-023 capacity, CMP-138 caps (§6, §8) ---
    Pair(
        "meter.fill",
        "meter fill",
        "color.action.primary.default",
        "color.surface.raised",
        "non-text",
    ),
    Pair(
        "meter.near",
        "meter fill near the cap",
        "color.status.warning.strong",
        "color.surface.raised",
        "non-text",
    ),
    Pair(
        "meter.breached",
        "meter fill breached and tightened",
        "color.status.danger.strong",
        "color.surface.raised",
        "non-text",
    ),
    Pair(
        "meter.tick",
        "meter cap tick",
        "color.text.primary",
        "color.surface.raised",
        "non-text",
    ),
    # --- CMP-028 notices (§8, §9) ---
    Pair(
        "notice.text",
        "info notice text (the tightening notice, D22)",
        "color.text.primary",
        "color.status.info.subtle",
        "text",
    ),
    Pair(
        "notice.glyph",
        "info notice glyph",
        "color.status.info.strong",
        "color.status.info.subtle",
        "non-text",
    ),
    Pair(
        "notice.once",
        "shown-once note text (§9)",
        "color.text.primary",
        "color.status.warning.subtle",
        "text",
    ),
    # --- dialogs on overlay: SCR-149 and the ladder (§5, §12) ---
    Pair(
        "dialog.title",
        "dialog title and body",
        "color.text.primary",
        "color.surface.overlay",
        "text",
    ),
    Pair(
        "dialog.secondary",
        "dialog secondary text and a T2 reason",
        "color.text.secondary",
        "color.surface.overlay",
        "text",
    ),
    Pair(
        "dialog.tertiary",
        "dialog marker, hint, T2 label and lock (choice B)",
        "color.text.tertiary",
        "color.surface.overlay",
        "text",
    ),
    Pair(
        "dialog.value",
        "field value on sunken",
        "color.text.primary",
        "color.surface.sunken",
        "text",
    ),
    Pair(
        "dialog.cancel",
        "Cancel on the secondary fill",
        "color.text.primary",
        "color.action.secondary.default",
        "text",
    ),
    Pair(
        "confirm.text",
        "danger confirm label (D02 D3)",
        "color.text.primary",
        "color.status.danger.subtle",
        "text",
    ),
    Pair(
        "confirm.border",
        "danger confirm border vs its fill",
        "color.status.danger.strong",
        "color.status.danger.subtle",
        "non-text",
    ),
    Pair(
        "confirm.overlay",
        "danger confirm border vs the dialog",
        "color.status.danger.strong",
        "color.surface.overlay",
        "non-text",
    ),
    Pair(
        "confirm.match",
        "typed-token match check on the dialog",
        "color.status.success.strong",
        "color.surface.overlay",
        "non-text",
    ),
    # --- DS-3: the text-field boundary on `color.text.tertiary` (deviation (7)) ---
    Pair(
        "field.overlay",
        "DS-3 field boundary vs the dialog",
        "CR:color.border.input",
        "color.surface.overlay",
        "non-text",
    ),
    Pair(
        "field.page",
        "DS-3 field boundary vs the page",
        "CR:color.border.input",
        "color.surface.app",
        "non-text",
    ),
    Pair(
        "field.raised",
        "DS-3 field boundary vs raised",
        "CR:color.border.input",
        "color.surface.raised",
        "non-text",
    ),
    Pair(
        "field.sunken",
        "DS-3 field boundary vs its sunken fill",
        "CR:color.border.input",
        "color.surface.sunken",
        "non-text",
    ),
    # --- SCR-124 view-as banner (§10, D24) ---
    Pair(
        "banner.text",
        "view-as banner text",
        "color.text.primary",
        "color.status.info.subtle",
        "text",
    ),
    Pair(
        "banner.eye",
        "view-as eye glyph",
        "color.status.info.strong",
        "color.status.info.subtle",
        "non-text",
    ),
    Pair(
        "banner.rule",
        "view-as 2 px rule vs the page",
        "color.status.info.strong",
        "color.surface.app",
        "non-text",
    ),
    Pair(
        "countdown.triangle",
        "view-as countdown triangle (5 min); never as text",
        "color.status.warning.strong",
        "color.status.info.subtle",
        "non-text",
    ),
    Pair(
        "countdown.octagon",
        "view-as countdown octagon (1 min); never as text",
        "color.status.danger.strong",
        "color.status.info.subtle",
        "non-text",
    ),
    # --- findings F1, F2, F4: the failing pairs and the pairs that replace them ---
    Pair(
        "f1.field",
        "F1: field boundary today, `border.default` on the dialog; DS-3 replaces it",
        "color.border.default",
        "color.surface.overlay",
        "rejected-non-text",
    ),
    Pair(
        "f2.fill",
        "F2: the Exit's primary fill vs the banner; its border carries the edge",
        "color.action.primary.default",
        "color.status.info.subtle",
        "rejected-non-text",
    ),
    Pair(
        "f2.border",
        "F2 fix: the Exit's 1 px `text.primary` border vs the banner (D24)",
        "color.text.primary",
        "color.status.info.subtle",
        "non-text",
    ),
    Pair(
        "f4.selected",
        "F4: tertiary text in a selected row; never drawn",
        "color.text.tertiary",
        "color.surface.selected",
        "rejected-text",
    ),
    Pair(
        "f4.banner",
        "F4: tertiary text on the view-as banner; never drawn",
        "color.text.tertiary",
        "color.status.info.subtle",
        "rejected-text",
    ),
    Pair(
        "f4.selected.fix",
        "F4 fix: secondary text in a selected row, a T2 label there included",
        "color.text.secondary",
        "color.surface.selected",
        "text",
    ),
    Pair(
        "f4.banner.fix",
        "F4 fix: secondary text on the view-as banner",
        "color.text.secondary",
        "color.status.info.subtle",
        "text",
    ),
    # --- §2 D2's measured alternative, and the edges the text binds outside the table ---
    Pair(
        "d2.teal",
        "D2's alternative: a teal rule vs the page (a new hue meaning; Q4)",
        "CR:color.border.admin.teal",
        "color.surface.app",
        "rejected-non-text",
    ),
    Pair(
        "meter.track",
        "meter track (Appendix A, CMP-138): the fill, the tick and the words carry",
        "color.surface.hover",
        "color.surface.raised",
        "decorative",
    ),
    Pair(
        "t2.edge.page",
        "T2 filled control: `border.default` hairline vs the page (§13)",
        "color.border.default",
        "color.surface.app",
        "exempt",
    ),
    Pair(
        "t2.edge.raised",
        "T2 filled control: the hairline vs raised (§13)",
        "color.border.default",
        "color.surface.raised",
        "exempt",
    ),
    Pair(
        "t2.edge.overlay",
        "T2 control and the validity-form confirm: the hairline vs the dialog (§12, §13)",
        "color.border.default",
        "color.surface.overlay",
        "exempt",
    ),
]

# Follow-up pairs measured beside F2 to F4 that no frame binds: alternatives to the fixes and the
# surfaces a glyph, a link or a border could reach next. Reported against the role's bar, never
# gated.
FOLLOW_UPS: list[Pair] = [
    Pair(
        "fu.exit.edge",
        "F2: the Exit's border vs its own primary fill",
        "color.text.primary",
        "color.action.primary.default",
        "non-text",
    ),
    Pair(
        "fu.exit.secondary",
        "F2 alternative: a secondary-fill Exit vs the banner",
        "color.action.secondary.default",
        "color.status.info.subtle",
        "non-text",
    ),
    Pair(
        "fu.link.overlay",
        "F3: a link on the dialog",
        "color.text.link",
        "color.surface.overlay",
        "text",
    ),
    Pair("fu.link.hover", "F3: a link on hover", "color.text.link", "color.surface.hover", "text"),
    Pair(
        "fu.secondary.warning",
        "F4: secondary text on warning.subtle",
        "color.text.secondary",
        "color.status.warning.subtle",
        "text",
    ),
    Pair(
        "fu.secondary.danger",
        "F4: secondary text on danger.subtle",
        "color.text.secondary",
        "color.status.danger.subtle",
        "text",
    ),
    Pair(
        "fu.focus.success",
        "focus ring on success.subtle",
        "color.focus.ring",
        "color.status.success.subtle",
        "non-text",
    ),
    Pair(
        "fu.warning.overlay",
        "triangle on the dialog",
        "color.status.warning.strong",
        "color.surface.overlay",
        "non-text",
    ),
    Pair(
        "fu.info.overlay",
        "info glyph on the dialog",
        "color.status.info.strong",
        "color.surface.overlay",
        "non-text",
    ),
    Pair(
        "fu.info.raised",
        "info glyph on raised",
        "color.status.info.strong",
        "color.surface.raised",
        "non-text",
    ),
    Pair(
        "fu.live.page",
        "env badge LIVE border on the page",
        "color.env.live",
        "color.surface.app",
        "non-text",
    ),
    Pair(
        "fu.demo.page",
        "env badge DEMO border on the page",
        "color.env.demo",
        "color.surface.app",
        "non-text",
    ),
]


class CvdPair(NamedTuple):
    """Two colours that must not be the only thing telling two states apart."""

    key: str
    label: str
    a: str
    b: str


CVD_PAIRS: list[CvdPair] = [
    CvdPair(
        "cvd.band", "the band fill vs the page", "CR:color.surface.admin-tint", "color.surface.app"
    ),
    CvdPair("cvd.rule", "the 4 px rule vs the page", "CR:color.border.admin", "color.surface.app"),
    CvdPair(
        "cvd.rule.ring", "the rule vs the focus ring", "CR:color.border.admin", "color.focus.ring"
    ),
    CvdPair("cvd.rule.live", "the rule vs env LIVE", "CR:color.border.admin", "color.env.live"),
    CvdPair("cvd.rule.demo", "the rule vs env DEMO", "CR:color.border.admin", "color.env.demo"),
    CvdPair(
        "cvd.rule.info",
        "the rule vs the view-as rule",
        "CR:color.border.admin",
        "color.status.info.strong",
    ),
    CvdPair(
        "cvd.strong.warning-danger",
        "`warning.strong` vs `danger.strong`",
        "color.status.warning.strong",
        "color.status.danger.strong",
    ),
    CvdPair(
        "cvd.strong.success-warning",
        "`success.strong` vs `warning.strong`",
        "color.status.success.strong",
        "color.status.warning.strong",
    ),
    CvdPair(
        "cvd.strong.success-danger",
        "`success.strong` vs `danger.strong`",
        "color.status.success.strong",
        "color.status.danger.strong",
    ),
    CvdPair(
        "cvd.subtle.success-warning",
        "`success.subtle` vs `warning.subtle`",
        "color.status.success.subtle",
        "color.status.warning.subtle",
    ),
    CvdPair(
        "cvd.subtle.success-danger",
        "`success.subtle` vs `danger.subtle`",
        "color.status.success.subtle",
        "color.status.danger.subtle",
    ),
    CvdPair(
        "cvd.subtle.warning-danger",
        "`warning.subtle` vs `danger.subtle`",
        "color.status.warning.subtle",
        "color.status.danger.subtle",
    ),
    CvdPair(
        "cvd.subtle.info-warning",
        "`info.subtle` vs `warning.subtle`",
        "color.status.info.subtle",
        "color.status.warning.subtle",
    ),
    CvdPair(
        "cvd.subtle.info-danger",
        "`info.subtle` vs `danger.subtle`",
        "color.status.info.subtle",
        "color.status.danger.subtle",
    ),
    CvdPair(
        "cvd.subtle.neutral-danger",
        "`neutral.subtle` vs `danger.subtle`",
        "color.neutral.subtle",
        "color.status.danger.subtle",
    ),
    CvdPair(
        "cvd.subtle.neutral-info",
        "`neutral.subtle` vs `info.subtle`",
        "color.neutral.subtle",
        "color.status.info.subtle",
    ),
    CvdPair("cvd.env", "`env.live` vs `env.demo`", "color.env.live", "color.env.demo"),
    CvdPair(
        "cvd.banner",
        "the view-as banner vs the page",
        "color.status.info.subtle",
        "color.surface.app",
    ),
    CvdPair(
        "cvd.stale",
        "stale clock vs warning triangle",
        "color.data-confidence.stale.indicator",
        "color.status.warning.strong",
    ),
]


class TableRow(NamedTuple):
    """A §15 table row: its label and its cell items (" · " in a group, "; " between groups)."""

    label: str
    groups: list[list[str]]
    themes: tuple[str, ...] = THEMES


# §15's contrast table, row for row: the spec's labels, every number regenerated from PAIRS.
CONTRAST_TABLE: list[TableRow] = [
    TableRow("band: `text.primary` · `text.secondary` on DS-1", [["band.label", "band.route"]]),
    TableRow(
        "rule DS-2 vs the page · vs the band; band fill vs the page (not a carrier)",
        [["rule.page", "rule.band"], ["band.fill"]],
    ),
    TableRow(
        "badge and strip: secondary on `surface.hover` · text on `warning.subtle` · on "
        "`danger.subtle`",
        [["badge.unlocked", "badge.warning", "badge.danger"]],
    ),
    TableRow(
        "badge glyphs: triangle on `warning.subtle` · octagon on `danger.subtle`; env LIVE · DEMO "
        "border on raised · on overlay (dialogs)",
        [
            ["badge.triangle", "badge.octagon"],
            ["env.live.raised", "env.demo.raised", "env.live.overlay", "env.demo.overlay"],
        ],
    ),
    TableRow(
        "page: `h1` · meta and footer (tertiary) · link · SCR-154/155 body (secondary)",
        [["page.h1", "page.meta", "page.link", "page.body"]],
    ),
    TableRow(
        "primary button, skip link, Exit: `text.on-action` on `action.primary.default`",
        [["button.primary"]],
    ),
    TableRow(
        "focus ring on app · raised · overlay · hover · selected · sunken · `info.subtle` · "
        "`warning.subtle` · `danger.subtle`",
        [
            [
                "focus.app",
                "focus.raised",
                "focus.overlay",
                "focus.hover",
                "focus.selected",
                "focus.sunken",
                "focus.info",
                "focus.warning",
                "focus.danger",
            ]
        ],
    ),
    TableRow(
        'tiles: value · label · "as of" · heading link; Retry on the secondary fill',
        [["tile.value", "tile.label", "tile.asof", "tile.link"], ["tile.retry"]],
    ),
    TableRow(
        "tile glyphs on raised: check · triangle · octagon · stale clock",
        [["tile.check", "tile.triangle", "tile.octagon", "tile.stale"]],
    ),
    TableRow(
        "table: header on hover · sort glyph (and the busy spinner, §7) · selected-row text",
        [["table.header", "table.sort", "table.selected"]],
    ),
    TableRow(
        "T2 label and lock (tertiary) on `surface.hover` (CMP-041's focused item, DJ) · on "
        "`selected`",
        [["t2.hover", "t2.selected"]],
    ),
    TableRow(
        "chips, text: Active · Invited · Disabled · Locked out and Invite expired · Trading locked",
        [["chip.active", "chip.invited", "chip.disabled", "chip.locked", "chip.trading"]],
    ),
    TableRow(
        "chips, glyphs: check · ring · slashed circle · triangle · octagon",
        [["chip.check", "chip.ring", "chip.slashed", "chip.triangle", "chip.octagon"]],
    ),
    TableRow(
        "meters on raised: fill · near · breached and tightened · cap tick",
        [["meter.fill", "meter.near", "meter.breached", "meter.tick"]],
    ),
    TableRow(
        "notices: text on `info.subtle` · info glyph · text on `warning.subtle` (shown-once note)",
        [["notice.text", "notice.glyph", "notice.once"]],
    ),
    TableRow(
        "dialogs on overlay: title · secondary and T2 reason · tertiary marker, hint, T2 label and "
        "lock (choice B) · value on sunken · Cancel",
        [
            [
                "dialog.title",
                "dialog.secondary",
                "dialog.tertiary",
                "dialog.value",
                "dialog.cancel",
            ]
        ],
    ),
    TableRow(
        "confirm: text on `danger.subtle` · border vs its fill · vs overlay; token-match check on "
        "overlay",
        [["confirm.text", "confirm.border", "confirm.overlay"], ["confirm.match"]],
    ),
    TableRow(
        "DS-3 field boundary (`text.tertiary`) vs overlay · page · raised · sunken",
        [["field.overlay", "field.page", "field.raised", "field.sunken"]],
    ),
    TableRow(
        "view-as: text · eye glyph on `info.subtle`; its 2 px rule vs the page",
        [["banner.text", "banner.eye"], ["banner.rule"]],
    ),
    TableRow(
        "view-as countdown glyphs on `info.subtle`: triangle (`warning.strong`) · octagon "
        "(`danger.strong`)",
        [["countdown.triangle", "countdown.octagon"]],
    ),
    TableRow("F1 field boundary today: `border.default` on overlay", [["f1.field"]]),
    TableRow("F2 Exit fill vs the banner", [["f2.fill"]]),
    TableRow("F3 hc 7:1 aim: tile heading link on raised", [["tile.link"]], ("high-contrast",)),
    TableRow(
        "F4 tertiary on `surface.selected` · on `info.subtle`", [["f4.selected", "f4.banner"]]
    ),
]

# §15's greyscale and colour-vision table (the cells read "ΔE76 normal / deutan; ΔL*").
CVD_TABLE: list[TableRow] = [
    TableRow("the 4 px rule vs the page", [["cvd.rule"]]),
    TableRow("the band fill vs the page", [["cvd.band"]]),
    TableRow("`warning.strong` vs `danger.strong`", [["cvd.strong.warning-danger"]]),
    TableRow("`success.subtle` vs `danger.subtle`", [["cvd.subtle.success-danger"]]),
    TableRow("`neutral.subtle` vs `danger.subtle`", [["cvd.subtle.neutral-danger"]]),
    TableRow("stale clock vs warning triangle (same hex in every theme)", [["cvd.stale"]]),
    TableRow("`env.live` vs `env.demo`", [["cvd.env"]]),
    TableRow("the view-as banner vs the page", [["cvd.banner"]]),
]

ROLE = {p.key: p.role for p in PAIRS + FOLLOW_UPS}


def check_keys() -> None:
    """Every key is unique and every table cell names a measured pair."""
    keys = [p.key for p in PAIRS + FOLLOW_UPS] + [c.key for c in CVD_PAIRS]
    dupes = sorted({k for k in keys if keys.count(k) > 1})
    if dupes:
        raise SystemExit(f"duplicate keys: {dupes}")
    for rows, known in ((CONTRAST_TABLE, {p.key for p in PAIRS}), (CVD_TABLE, set(keys))):
        missing = [k for r in rows for g in r.groups for k in g if k not in known]
        if missing:
            raise SystemExit(f"table cells without a pair: {missing}")


def lightness(h: str) -> float:
    return float(cvd.xyz_to_lab(cvd.srgb_to_xyz(h))[0])


def measure(pairs: list[Pair]) -> dict[str, list[float]]:
    return {p.key: [ratio(col(t, p.fg), col(t, p.bg)) for t in THEMES] for p in pairs}


def judge(role: str, vals: list[float]) -> tuple[str, bool]:
    """The verdict of one row and whether it is a gated FAIL."""
    bar = BAR[role]
    if bar is None:
        return f"{role} (not gated)", False
    bad = [t for t, v in zip(THEMES, vals, strict=True) if v < bar]
    if role.startswith("rejected"):
        if bad:
            return "rejected by design (would FAIL: " + ", ".join(bad) + ")", False
        return "rejected by design (passes; not used)", False
    if bad:
        return "FAIL: " + ", ".join(bad), True
    return "PASS", False


def aim(role: str, vals: list[float]) -> str:
    """The high-contrast 7:1 aim for body text: gated text rows only, never gated itself."""
    if role != "text":
        return "—"
    return "met" if vals[2] >= HC_AIM else f"below ({vals[2]:.2f})"


def cvd_measure(theme: str, pair: CvdPair) -> tuple[float, float, float, float, float]:
    """ΔE76 normal, protan, deutan, tritan, then ΔL* (the greyscale distance)."""
    ha, hb = col(theme, pair.a), col(theme, pair.b)
    p, d, t = (cvd.delta_e76(cvd.simulate(ha, k), cvd.simulate(hb, k)) for k in DEFICIENCIES)
    return float(cvd.delta_e76(ha, hb)), p, d, t, abs(lightness(ha) - lightness(hb))


def table(header: list[str], rows: list[list[str]]) -> None:
    print("| " + " | ".join(header) + " |")
    print("|" + "---|" * len(header))
    for row in rows:
        print("| " + " | ".join(row) + " |")
    print()


def cells(row: TableRow, value: dict[str, list[str]]) -> list[str]:
    """One cell per theme: items joined by " · " within a group and groups by "; "."""
    out = []
    for i, theme in enumerate(THEMES):
        if theme not in row.themes:
            out.append("—")
            continue
        out.append("; ".join(" · ".join(value[k][i] for k in g) for g in row.groups))
    return out


def row_verdict(row: TableRow, vals: dict[str, list[float]]) -> str:
    keys = [k for g in row.groups for k in g]
    gated = [k for k in keys if ROLE[k] in GATED]
    parts = []
    if gated:
        fails = [k for k in gated if judge(ROLE[k], vals[k])[1]]
        parts.append("FAIL: " + ", ".join(fails) if fails else "pass")
    parts += [f"{ROLE[k]}: {k}" for k in keys if ROLE[k] not in GATED]
    if row.themes == ("high-contrast",):
        parts += [f"hc 7:1 aim {aim(ROLE[k], vals[k])}: {k}" for k in keys]
    return "; ".join(parts)


def cited(vals: dict[str, list[float]], dl_band_dark: float) -> list[list[str]]:
    """The numbers the spec cites in prose and in the table's verdicts, each from a pair."""

    def r(key: str, *themes: str) -> str:
        return " / ".join(f"{vals[key][THEMES.index(t)]:.2f}" for t in themes or THEMES)

    def hexes(token: str) -> str:
        return " / ".join(col(t, token) for t in THEMES)

    return [
        ["§2 D2, §4", "band fill vs the page (`band.fill`)", r("band.fill")],
        ["§2 D2", "the teal rule vs the page (`d2.teal`)", r("d2.teal")],
        ["§2 D24", "Exit fill vs the banner, dark (`f2.fill`)", r("f2.fill", "dark")],
        ["§4, §22", "the 4 px rule vs the page (`rule.page`)", r("rule.page")],
        ["§4", "the band fill vs the page, ΔL* dark (`cvd.band`)", f"{dl_band_dark:.1f}"],
        [
            "§15 T2 row",
            "the label on selected takes `text.secondary`, dark (`f4.selected.fix`)",
            r("f4.selected.fix", "dark"),
        ],
        [
            "§15 countdown row",
            "the glyph colours as text, light (`countdown.triangle` · `countdown.octagon`)",
            r("countdown.triangle", "light") + " · " + r("countdown.octagon", "light"),
        ],
        ["§15 F2", "the Exit's 1 px `text.primary` border (`f2.border`)", r("f2.border")],
        [
            "§15 F4",
            "`text.secondary` on selected · on `info.subtle`, dark (`f4.*.fix`)",
            r("f4.selected.fix", "dark") + " · " + r("f4.banner.fix", "dark"),
        ],
        [
            "§15 token proposals",
            "`color.surface.admin-tint` → `{color.surface.raised}`",
            hexes("CR:color.surface.admin-tint"),
        ],
        [
            "§15 token proposals",
            "`color.border.admin` → `{color.text.tertiary}`",
            hexes("CR:color.border.admin"),
        ],
    ]


def main() -> int:
    check_keys()
    vals = measure(PAIRS)
    follow = measure(FOLLOW_UPS)
    cv = {(c.key, t): cvd_measure(t, c) for c in CVD_PAIRS for t in THEMES}

    failed = 0
    print("## A. Contrast matrix (ratio per theme; the role sets the bar)\n")
    rows = []
    for p in PAIRS:
        verdict, fail = judge(p.role, vals[p.key])
        failed += fail
        nums = [f"{v:.2f}" for v in vals[p.key]]
        aim_cell = aim(p.role, vals[p.key])
        rows.append([p.key, p.element, f"`{p.fg}`", f"`{p.bg}`", p.role, *nums, verdict, aim_cell])
    head = ["key", "element", "fg", "bg", "role", "dark", "light", "hc", "verdict", "hc 7:1 aim"]
    table(head, rows)

    print("## B. Follow-up pairs beside F2 to F4 (no frame binds them; not gated)\n")
    rows = []
    for p in FOLLOW_UPS:
        verdict, _ = judge(p.role, follow[p.key])
        nums = [f"{v:.2f}" for v in follow[p.key]]
        rows.append([p.key, p.element, f"`{p.fg}`", f"`{p.bg}`", p.role, *nums, "would " + verdict])
    table(["key", "element", "fg", "bg", "as", "dark", "light", "hc", "verdict"], rows)

    print(f"## C. Colour vision and greyscale (ΔE76; JND floor {JND:.1f}; ΔL* for greyscale)\n")
    rows = []
    for c in CVD_PAIRS:
        for t in THEMES:
            m = cv[(c.key, t)]
            ok = min(m[0:4]) >= JND
            verdict = "distinct" if ok else "collapses: a glyph or a word carries it"
            rows.append([c.key, c.label, t, *(f"{x:.1f}" for x in m), verdict])
    table(["key", "pair", "theme", "normal", "protan", "deutan", "tritan", "ΔL*", "verdict"], rows)

    print("## D. §15's tables, regenerated (the spec's labels; every number from A and C)\n")
    text = {k: [f"{v:.2f}" for v in vs] for k, vs in vals.items()}
    rows = [[r.label, *cells(r, text), row_verdict(r, vals)] for r in CONTRAST_TABLE]
    table(["Surface (pairs)", "Dark", "Light", "HC", "Verdict (this audit)"], rows)
    grey = {
        c.key: [f"{m[0]:.1f} / {m[2]:.1f}; {m[4]:.1f}" for m in (cv[(c.key, t)] for t in THEMES)]
        for c in CVD_PAIRS
    }
    rows = [[r.label, *cells(r, grey)] for r in CVD_TABLE]
    table(["Pair (ΔE76 normal / deutan; ΔL*)", "Dark", "Light", "HC"], rows)
    table(["Where", "Number", "Value"], cited(vals, cv[("cvd.band", "dark")][4]))

    print("## E. Resolved values used above\n")
    seen: list[str] = []
    for a, b in [(p.fg, p.bg) for p in PAIRS + FOLLOW_UPS] + [(c.a, c.b) for c in CVD_PAIRS]:
        seen += [x for x in (a, b) if x not in seen]
    table(
        ["token", "dark", "light", "hc"], [[f"`{x}`", *(col(t, x) for t in THEMES)] for x in seen]
    )

    texts = [p for p in PAIRS if p.role == "text"]
    below = [p.key for p in texts if vals[p.key][2] < HC_AIM]
    collapse = [c.key for c in CVD_PAIRS if any(min(cv[(c.key, t)][0:4]) < JND for t in THEMES)]
    counts = {role: sum(p.role == role for p in PAIRS) for role in BAR}
    print("## Summary\n")
    print(f"- Matrix: {len(PAIRS)} pairs; " + ", ".join(f"{n} {r}" for r, n in counts.items()))
    met = len(texts) - len(below)
    print(
        f"- hc 7:1 aim: {met} of {len(texts)} text pairs met; below: {', '.join(below) or 'none'}"
    )
    print(f"- Follow-up pairs: {len(FOLLOW_UPS)}")
    print(f"- Colour vision: {len(CVD_PAIRS)} pairs; under {JND:.1f} in a theme: {len(collapse)}")
    print(f"  ({', '.join(collapse)}: a glyph or a word carries each)")
    print(f"\nFAIL count (gated rows only): {failed}")
    return 1 if failed else 0


if __name__ == "__main__":
    raise SystemExit(main())
