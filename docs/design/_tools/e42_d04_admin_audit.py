"""E42-D04 admin hi-fi audit: WCAG contrast, follow-up pairs and colour vision over the token JSON.

Standalone, offline, stdlib only, on the method of `e42_d02_admin_audit.py`. Every theme
(`dark`, `light`, `high-contrast`) resolves exactly as `packages/ui/tokens/tests/verify_tokens.py`
resolves it (same loader, same alias resolution, same set layering, checked against
`themes.json`); the ratio is `contrast_ratio()` from `docs/design/_tools/contrast_check.py`
(imported, not re-implemented); ΔE76, L* and the deuteranopia, protanopia and tritanopia
projections are those of `docs/research/_tools/cvd_simulate.py`. It measures every pair the hi-fi
spec (`docs/design/E42/E42-D04.md` §15) binds for SCR-135, SCR-136, SCR-145 and SCR-148, the
follow-up pairs its verdicts point at (the high-contrast link aim, CG-24; the merged CMP-044
Confirm) and its colour-vision pairs, then regenerates the numbers of §15's two tables (its
Verdict column is hand-written; section D names each row's role) and the numbers §15 cites.

Usage: python3 -I docs/design/_tools/e42_d04_admin_audit.py
(prints Markdown; exit 1 on a FAIL, 2 on a tool error)

Exit codes: 0 every gated row passes; 1 a gated row FAILs; 2 the tool itself cannot run (a
helper that does not load, a theme layered unlike verify_tokens.py, a duplicate key, a table
cell with no pair, a token with no colour or not an opaque #RRGGBB), so a caller never reads a tool
error as a FAIL.

Roles. `text` (4.5:1, WCAG 1.4.3) and `non-text` (3:1, WCAG 1.4.11) rows are gated in every theme,
and one FAIL exits 1. Every gated text row is also measured against the high-contrast theme's 7:1
aim for body text (`05-accessibility-standard.md` §5 item 6): reported, not gated (CG-24).
`decorative` rows carry no meaning (a word, a glyph or a border is the carrier); `exempt` rows bound
inactive controls, which WCAG 1.4.3 and 1.4.11 exempt, and are reported so the design never relies
on them; `rejected-*` rows are pairs the spec measured and designed around (the `danger.default`
rule, `text.tertiary` on a selected row). None of those three is gated. A stand-in for a catalogued
token that does not exist (spec §15, "Stand-ins, never invented") is prefixed `CR:` and measured on
the token it aliases, never on an invented hex.
"""

from __future__ import annotations

import importlib.util
import json
import sys
from pathlib import Path
from types import ModuleType
from typing import NamedTuple, NoReturn

ROOT = Path(__file__).resolve().parents[3]
TOKENS = ROOT / "packages" / "ui" / "tokens"
TOOL_ERROR = 2  # distinct from a gated FAIL (exit 1)


def tool_error(message: str) -> NoReturn:
    """Stop with exit 2: the audit could not run, which is never a contrast FAIL."""
    print(f"e42_d04_admin_audit: tool error: {message}", file=sys.stderr)
    raise SystemExit(TOOL_ERROR)


def _load(path: Path, name: str) -> ModuleType:
    spec = importlib.util.spec_from_file_location(name, path)
    if spec is None or spec.loader is None:
        tool_error(f"cannot load {path}")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


verify = _load(TOKENS / "tests" / "verify_tokens.py", "verify_tokens")
contrast_check = _load(ROOT / "docs" / "design" / "_tools" / "contrast_check.py", "contrast_check")
cvd = _load(ROOT / "docs" / "research" / "_tools" / "cvd_simulate.py", "cvd_simulate")

THEMES = ("dark", "light", "high-contrast")
DASH = "\u2013"  # en dash for Markdown ranges (an escape keeps RUF001 quiet)
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
            tool_error(f"themes.json layers {name} as {sets.get(name)}, verify_tokens {want}")


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
PRIM = verify.load(verify.PRIMITIVES)
T = {n: resolve_theme(n) for n in THEMES}

# Stand-ins (`CR:`) for catalogued tokens that exist in no set (§15, CG-24), per theme: existing
# tokens only, exactly the alias the spec names.
CR: dict[str, dict[str, str]] = {
    # SCR-136's raw record: `color.surface.code` → `color.surface.sunken`.
    "CR:color.surface.code": {t: "color.surface.sunken" for t in THEMES},
    # CMP-023's export bar track: `color.track` → `color.surface.hover`.
    "CR:color.track": {t: "color.surface.hover" for t in THEMES},
    # CMP-095's chip: `color.chip.dev` → `color.status.info.subtle` (D02 DS-4).
    "CR:color.chip.dev": {t: "color.status.info.subtle" for t in THEMES},
}


def col(theme: str, token: str) -> str:
    if token in CR:
        return col(theme, CR[token][theme])
    if token not in T[theme]:
        tool_error(f"{token} resolves to no colour in {theme}")
    value = T[theme][token]
    if len(value) != 7 or not value.startswith("#"):
        tool_error(f"{token} is {value} in {theme}: not an opaque #RRGGBB colour")
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


def tok(name: str) -> str:
    """A token from its name after `color.`; a `CR:` stand-in is passed through whole."""
    return name if name.startswith("CR:") else f"color.{name}"


def P(key: str, element: str, fg: str, bg: str, role: str) -> Pair:
    """Short constructor for the long matrix below: the tokens without their `color.` prefix."""
    return Pair(key, element, tok(fg), tok(bg), role)


# Every pair the frames bind, in the order of the rows of §15's contrast table (one pair per item
# of a table cell; an item the table repeats is measured once), then the decorative and exempt
# edges §15 names outside the table.
PAIRS: list[Pair] = [
    # --- SCR-135 rows (D2, D14, §4): words, meta and the high rule ---
    P(
        "word.raised",
        "severity and outcome words on raised",
        "text.primary",
        "surface.raised",
        "text",
    ),
    P(
        "word.hover",
        "severity and outcome words on hover",
        "text.primary",
        "surface.hover",
        "text",
    ),
    P(
        "word.selected",
        "severity and outcome words on the selected row",
        "text.primary",
        "surface.selected",
        "text",
    ),
    P("meta.raised", "row meta on raised", "text.secondary", "surface.raised", "text"),
    P("meta.hover", "row meta on hover", "text.secondary", "surface.hover", "text"),
    P(
        "meta.selected",
        "row meta on the selected row",
        "text.secondary",
        "surface.selected",
        "text",
    ),
    P(
        "rule.raised",
        "the high rule (2 px, a carrier with the word, AC-4) vs raised",
        "status.danger.strong",
        "surface.raised",
        "non-text",
    ),
    P(
        "rule.hover",
        "the high rule vs hover",
        "status.danger.strong",
        "surface.hover",
        "non-text",
    ),
    P(
        "rule.selected",
        "the high rule vs the selected row",
        "status.danger.strong",
        "surface.selected",
        "non-text",
    ),
    P(
        "rule.default.hover",
        "the rejected rule `danger.default` vs hover",
        "status.danger.default",
        "surface.hover",
        "rejected-non-text",
    ),
    P(
        "rule.default.selected",
        "the rejected rule `danger.default` vs the selected row",
        "status.danger.default",
        "surface.selected",
        "rejected-non-text",
    ),
    # --- tone glyphs (CMP-019) ---
    P(
        "glyph.octagon",
        "octagon on raised",
        "status.danger.strong",
        "surface.raised",
        "non-text",
    ),
    P(
        "glyph.triangle",
        "triangle on raised",
        "status.warning.strong",
        "surface.raised",
        "non-text",
    ),
    P(
        "glyph.check",
        "check on raised",
        "status.success.strong",
        "surface.raised",
        "non-text",
    ),
    P(
        "glyph.check.app",
        "check on the page",
        "status.success.strong",
        "surface.app",
        "non-text",
    ),
    P(
        "glyph.triangle.app",
        "triangle on the page",
        "status.warning.strong",
        "surface.app",
        "non-text",
    ),
    # --- tertiary text, the search field ---
    P(
        "tertiary.app",
        "page text and marker on app",
        "text.tertiary",
        "surface.app",
        "text",
    ),
    P(
        "tertiary.raised",
        "marker and T2 label on raised",
        "text.tertiary",
        "surface.raised",
        "text",
    ),
    P(
        "tertiary.overlay",
        "marker on the drawer / dialog",
        "text.tertiary",
        "surface.overlay",
        "text",
    ),
    P(
        "tertiary.sunken",
        "placeholder on the field",
        "text.tertiary",
        "surface.sunken",
        "text",
    ),
    P(
        "search.glyph",
        "the search glyph on the field",
        "text.secondary",
        "surface.sunken",
        "non-text",
    ),
    P(
        "tertiary.selected",
        "tertiary meta on the selected row (designed around: `text.secondary`)",
        "text.tertiary",
        "surface.selected",
        "rejected-text",
    ),
    # --- the selected row (D14) ---
    P(
        "selected.check",
        "the selected row's `check` glyph",
        "text.primary",
        "surface.selected",
        "non-text",
    ),
    P(
        "selected.fill",
        "the selected fill vs raised (no carrier: check, aria-selected, the drawer)",
        "surface.selected",
        "surface.raised",
        "decorative",
    ),
    # --- the incident banner (§7) on danger.subtle ---
    P(
        "incident.text",
        "incident banner text",
        "text.primary",
        "status.danger.subtle",
        "text",
    ),
    P(
        "incident.octagon",
        "incident banner octagon",
        "status.danger.strong",
        "status.danger.subtle",
        "non-text",
    ),
    P(
        "incident.link",
        "incident banner link",
        "text.link",
        "status.danger.subtle",
        "text",
    ),
    P(
        "incident.ring",
        "focus ring on the incident banner",
        "focus.ring",
        "status.danger.subtle",
        "non-text",
    ),
    # --- maintenance and fail-closed banners (§9, §10) on warning.subtle ---
    P(
        "maint.text",
        "maintenance banner text",
        "text.primary",
        "status.warning.subtle",
        "text",
    ),
    P(
        "maint.triangle",
        "maintenance banner triangle",
        "status.warning.strong",
        "status.warning.subtle",
        "non-text",
    ),
    P(
        "maint.link",
        "maintenance banner link",
        "text.link",
        "status.warning.subtle",
        "text",
    ),
    P(
        "maint.ring",
        "focus ring on the maintenance banner",
        "focus.ring",
        "status.warning.subtle",
        "non-text",
    ),
    # --- the new-entries pill (§4) on info.subtle ---
    P(
        "pill.text",
        "new-entries pill text",
        "text.primary",
        "status.info.subtle",
        "text",
    ),
    P(
        "pill.glyph",
        "new-entries pill glyph",
        "status.info.strong",
        "status.info.subtle",
        "non-text",
    ),
    # --- SCR-136 drawer (§5) ---
    P("drawer.primary", "drawer text", "text.primary", "surface.overlay", "text"),
    P(
        "drawer.secondary",
        "drawer secondary text, T2 reason",
        "text.secondary",
        "surface.overlay",
        "text",
    ),
    P(
        "raw.text",
        "raw record text on `color.surface.code` (stand-in `surface.sunken`)",
        "text.primary",
        "CR:color.surface.code",
        "text",
    ),
    P(
        "raw.ring",
        "focus ring on the raw record",
        "focus.ring",
        "CR:color.surface.code",
        "non-text",
    ),
    # --- the export bar (§8, CMP-023): the "{n} %" text carries it ---
    P(
        "export.track",
        "export bar fill on its track (`color.track` stand-in `surface.hover`)",
        "action.primary.default",
        "CR:color.track",
        "non-text",
    ),
    P(
        "export.raised",
        "export bar fill on raised",
        "action.primary.default",
        "surface.raised",
        "non-text",
    ),
    # --- the focus ring ---
    P(
        "focus.raised",
        "focus ring on raised",
        "focus.ring",
        "surface.raised",
        "non-text",
    ),
    P("focus.hover", "focus ring on hover", "focus.ring", "surface.hover", "non-text"),
    P(
        "focus.selected",
        "focus ring on the selected row",
        "focus.ring",
        "surface.selected",
        "non-text",
    ),
    P(
        "focus.overlay",
        "focus ring on the drawer / dialog",
        "focus.ring",
        "surface.overlay",
        "non-text",
    ),
    # --- the danger confirm (§11; D02 D3's adopted look) ---
    P(
        "confirm.border",
        "the danger confirm's `danger.strong` border vs the dialog",
        "status.danger.strong",
        "surface.overlay",
        "non-text",
    ),
    # --- T2 (§12.1) and the drawer's links ---
    P(
        "t2.reason.app",
        "T2 reason on the page",
        "text.secondary",
        "surface.app",
        "text",
    ),
    P("link.overlay", "the drawer's links", "text.link", "surface.overlay", "text"),
    # --- the LIVE chip (C-2.11) ---
    P(
        "live.app",
        "the LIVE chip's border on the page",
        "env.live",
        "surface.app",
        "non-text",
    ),
    P(
        "live.selected",
        "the LIVE chip's border on the selected row",
        "env.live",
        "surface.selected",
        "non-text",
    ),
    # --- named outside the table: never used, reported so the design never relies on them ---
    P(
        "disabled.raised",
        "`text.disabled` on raised (T2 never uses it, D09:286)",
        "text.disabled",
        "surface.raised",
        "exempt",
    ),
    P(
        "disabled.selected",
        "`text.disabled` on the selected row",
        "text.disabled",
        "surface.selected",
        "exempt",
    ),
    P(
        "disabled.overlay",
        "`text.disabled` on the dialog",
        "text.disabled",
        "surface.overlay",
        "exempt",
    ),
    P("disabled.app", "`text.disabled` on the page", "text.disabled", "surface.app", "exempt"),
    *(
        P(
            f"faded.{bg.split('.')[1]}",
            f"`text.primary` at `opacity.disabled` on `{bg}` (never used, D09:286)",
            "text.primary@opacity.disabled",
            bg,
            "exempt",
        )
        for bg in ("surface.app", "surface.raised", "surface.selected", "surface.overlay")
    ),
]

# Follow-up pairs that no frame binds: the surfaces a link or a glyph could reach next (CG-24's
# high-contrast link aim), the merged CMP-044 Confirm (#4414) beside D02 D3's look that §15
# measures, and CMP-095's chip, which SCR-145 does not draw. Reported against the role's bar,
# never gated. The CMP-044 pair is `15`'s merged text (origin/main 43d1145e6): Tokens "Confirm a
# CMP-001 `danger` (`color.status.danger.default`, `color.text.on-action`)" on CMP-043's card
# `color.surface.overlay`; D04 composes no CMP-138 (the 2026-10-25 R-1/R-2 rulings).
FOLLOW_UPS: list[Pair] = [
    P("fu.link.raised", "a link on raised", "text.link", "surface.raised", "text"),
    P(
        "fu.link.info",
        "a link on the pill's `info.subtle`",
        "text.link",
        "status.info.subtle",
        "text",
    ),
    P("fu.link.hover", "a link on a hovered row", "text.link", "surface.hover", "text"),
    P(
        "fu.cmp044.text",
        "merged CMP-044 Confirm: `text.on-action` on `danger.default`",
        "text.on-action",
        "status.danger.default",
        "text",
    ),
    P(
        "fu.cmp044.edge",
        "merged CMP-044 Confirm fill vs the dialog",
        "status.danger.default",
        "surface.overlay",
        "non-text",
    ),
    P(
        "fu.secondary.danger",
        "secondary text on `danger.subtle`",
        "text.secondary",
        "status.danger.subtle",
        "text",
    ),
    P(
        "fu.secondary.warning",
        "secondary text on `warning.subtle`",
        "text.secondary",
        "status.warning.subtle",
        "text",
    ),
    P(
        "fu.chip.text",
        "CMP-095 'Flag: {key}' on `color.chip.dev` (stand-in `info.subtle`)",
        "text.primary",
        "CR:color.chip.dev",
        "text",
    ),
    P(
        "fu.chip.glyph",
        "CMP-095 glyph on its chip",
        "status.info.strong",
        "CR:color.chip.dev",
        "non-text",
    ),
    P(
        "fu.demo.app",
        "the DEMO chip's border on the page",
        "env.demo",
        "surface.app",
        "non-text",
    ),
]


class CvdPair(NamedTuple):
    """Two colours that must not be the only thing telling two states apart."""

    key: str
    label: str
    a: str
    b: str


def C(key: str, label: str, a: str, b: str) -> CvdPair:
    return CvdPair(key, label, tok(a), tok(b))


CVD_PAIRS: list[CvdPair] = [
    C(
        "cvd.strong.danger-warning",
        "`danger.strong` vs `warning.strong`",
        "status.danger.strong",
        "status.warning.strong",
    ),
    C(
        "cvd.strong.success-danger",
        "`success.strong` vs `danger.strong`",
        "status.success.strong",
        "status.danger.strong",
    ),
    C(
        "cvd.subtle.danger-raised",
        "`danger.subtle` vs raised",
        "status.danger.subtle",
        "surface.raised",
    ),
    C(
        "cvd.subtle.warning-raised",
        "`warning.subtle` vs raised",
        "status.warning.subtle",
        "surface.raised",
    ),
    C("cvd.rule", "the high rule vs raised", "status.danger.strong", "surface.raised"),
    C(
        "cvd.strong.success-warning",
        "`success.strong` vs `warning.strong`",
        "status.success.strong",
        "status.warning.strong",
    ),
    C(
        "cvd.strong.info-warning",
        "`info.strong` vs `warning.strong` (pill vs maintenance glyph)",
        "status.info.strong",
        "status.warning.strong",
    ),
    C(
        "cvd.strong.info-danger",
        "`info.strong` vs `danger.strong` (pill vs incident glyph)",
        "status.info.strong",
        "status.danger.strong",
    ),
    C(
        "cvd.subtle.warning-danger",
        "`warning.subtle` vs `danger.subtle` (maintenance vs incident banner)",
        "status.warning.subtle",
        "status.danger.subtle",
    ),
    C(
        "cvd.subtle.info-warning",
        "`info.subtle` vs `warning.subtle` (pill vs maintenance banner)",
        "status.info.subtle",
        "status.warning.subtle",
    ),
    C(
        "cvd.subtle.info-danger",
        "`info.subtle` vs `danger.subtle` (pill vs incident banner)",
        "status.info.subtle",
        "status.danger.subtle",
    ),
    C(
        "cvd.selected",
        "the selected fill vs raised",
        "surface.selected",
        "surface.raised",
    ),
    C("cvd.env", "`env.live` vs `env.demo`", "env.live", "env.demo"),
    C(
        "cvd.live.rule",
        "`env.live` vs the high rule (a LIVE chip on a high row)",
        "env.live",
        "status.danger.strong",
    ),
    C(
        "cvd.ring.rule",
        "the focus ring vs the high rule (a focused high row)",
        "focus.ring",
        "status.danger.strong",
    ),
]


class TableRow(NamedTuple):
    """A §15 table row: its label and its cell items (" · " in a group, "; " between groups)."""

    label: str
    groups: list[list[str]]


def R(label: str, *groups: list[str]) -> TableRow:
    return TableRow(label, list(groups))


# §15's contrast table, row for row: the spec's labels, every number regenerated from PAIRS.
CONTRAST_TABLE: list[TableRow] = [
    R(
        "severity and outcome words, `text.primary` on raised · hover · selected",
        ["word.raised", "word.hover", "word.selected"],
    ),
    R(
        "row meta `text.secondary` on raised · hover · selected",
        ["meta.raised", "meta.hover", "meta.selected"],
    ),
    R(
        "the high rule `status.danger.strong` vs raised · hover · selected",
        ["rule.raised", "rule.hover", "rule.selected"],
    ),
    R(
        "rejected rule `status.danger.default` vs hover · selected",
        ["rule.default.hover", "rule.default.selected"],
    ),
    R(
        "octagon on raised · triangle on raised · check `success.strong` on raised",
        ["glyph.octagon", "glyph.triangle", "glyph.check"],
    ),
    R(
        "check `success.strong` · triangle `warning.strong` on app",
        ["glyph.check.app", "glyph.triangle.app"],
    ),
    R(
        "page text and marker `text.tertiary` on app · raised · overlay",
        ["tertiary.app", "tertiary.raised", "tertiary.overlay"],
    ),
    R(
        "`text.tertiary` on sunken · the search glyph `text.secondary` on sunken",
        ["tertiary.sunken", "search.glyph"],
    ),
    R("`text.tertiary` on selected (a focused row's meta)", ["tertiary.selected"]),
    R(
        "the selected row (D14): its `check` `text.primary` on selected · the fill "
        "`surface.selected` vs raised",
        ["selected.check", "selected.fill"],
    ),
    R(
        "incident banner: text · octagon · link · focus ring on `danger.subtle`",
        ["incident.text", "incident.octagon", "incident.link", "incident.ring"],
    ),
    R(
        "maintenance and fail-closed banners: text · triangle · link · ring on `warning.subtle`",
        ["maint.text", "maint.triangle", "maint.link", "maint.ring"],
    ),
    R("new-entries pill: text · glyph on `info.subtle`", ["pill.text", "pill.glyph"]),
    R(
        "drawer: `text.primary` · `.secondary` on overlay; raw record text · ring on sunken",
        ["drawer.primary", "drawer.secondary"],
        ["raw.text", "raw.ring"],
    ),
    R(
        "export bar: fill on the hover track · on raised",
        ["export.track", "export.raised"],
    ),
    R(
        "focus ring on raised · hover · selected · overlay",
        ["focus.raised", "focus.hover", "focus.selected", "focus.overlay"],
    ),
    R(
        "confirm: text on `danger.subtle` · its border vs overlay",
        ["incident.text", "confirm.border"],
    ),
    R(
        "T2 (§12.1): label and `lock` `text.tertiary` on raised · reason `text.secondary` on "
        "raised · selected · overlay",
        ["tertiary.raised", "meta.raised", "meta.selected", "drawer.secondary"],
    ),
    R(
        "T2 reason `text.secondary` on app · `text.link` on overlay (the drawer's links)",
        ["t2.reason.app", "link.overlay"],
    ),
    R(
        "the LIVE chip's border `env.live` on app · selected",
        ["live.app", "live.selected"],
    ),
]

# §15's greyscale and colour-vision table (Dark and Light; the cells read "ΔE76 normal / deutan;
# ΔL*"). Its forced-colours row is a construction, not a measurement: board 66's column.
CVD_TABLE: list[TableRow] = [
    R("`danger.strong` vs `warning.strong`", ["cvd.strong.danger-warning"]),
    R("`success.strong` vs `danger.strong`", ["cvd.strong.success-danger"]),
    R(
        "`danger.subtle` vs raised · `warning.subtle` vs raised",
        ["cvd.subtle.danger-raised", "cvd.subtle.warning-raised"],
    ),
    R("the high rule vs raised", ["cvd.rule"]),
]
CVD_THEMES = ("dark", "light")

ROLE = {p.key: p.role for p in PAIRS + FOLLOW_UPS}


def check_keys() -> None:
    """Every key is unique and every table cell names a measured pair."""
    keys = [p.key for p in PAIRS + FOLLOW_UPS] + [c.key for c in CVD_PAIRS]
    dupes = sorted({k for k in keys if keys.count(k) > 1})
    if dupes:
        tool_error(f"duplicate keys: {dupes}")
    cvd_keys = {c.key for c in CVD_PAIRS}
    for rows, known in (
        (CONTRAST_TABLE, {p.key for p in PAIRS}),
        (CVD_TABLE, cvd_keys),
    ):
        missing = [k for r in rows for g in r.groups for k in g if k not in known]
        if missing:
            tool_error(f"table cells without a pair: {missing}")


def lightness(h: str) -> float:
    return float(cvd.xyz_to_lab(cvd.srgb_to_xyz(h))[0])


def fg_on(theme: str, fg: str, bg: str) -> str:
    """The foreground as drawn: a `<token>@<opacity token>` fg is composited over its bg."""
    if "@" not in fg:
        return col(theme, fg)
    token, opacity = fg.split("@")
    alpha = float(PRIM[opacity]["$value"])
    front, back = hex_to_rgb(col(theme, token)), hex_to_rgb(col(theme, bg))
    mixed = (round(alpha * f + (1 - alpha) * b) for f, b in zip(front, back, strict=True))
    return "#" + "".join(f"{c:02X}" for c in mixed)


def measure(pairs: list[Pair]) -> dict[str, list[float]]:
    return {p.key: [ratio(fg_on(t, p.fg, p.bg), col(t, p.bg)) for t in THEMES] for p in pairs}


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
    """The high-contrast 7:1 aim for body text: text rows only, never gated itself."""
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


def cells(row: TableRow, value: dict[str, list[str]], themes: tuple[str, ...]) -> list[str]:
    """One cell per theme: items joined by " · " within a group and groups by "; "."""
    return [
        "; ".join(" · ".join(value[k][THEMES.index(t)] for k in g) for g in row.groups)
        for t in themes
    ]


def row_verdict(row: TableRow, vals: dict[str, list[float]]) -> str:
    keys = [k for g in row.groups for k in g]
    gated = [k for k in keys if ROLE[k] in GATED]
    parts = []
    if gated:
        fails = [k for k in gated if judge(ROLE[k], vals[k])[1]]
        parts.append("FAIL: " + ", ".join(fails) if fails else "pass")
    parts += [
        f"{ROLE[k]}: {k} ({judge(ROLE[k], vals[k])[0]})" for k in keys if ROLE[k] not in GATED
    ]
    below = [k for k in gated if aim(ROLE[k], vals[k]).startswith("below")]
    if below:
        parts.append("hc 7:1 aim below: " + ", ".join(below))
    return "; ".join(parts)


def cited(vals: dict[str, list[float]]) -> list[list[str]]:
    """The numbers §15 cites in its verdicts and prose, each from a pair."""

    def r(key: str, *themes: str) -> str:
        return " / ".join(f"{vals[key][THEMES.index(t)]:.2f}" for t in themes or THEMES)

    surfaces = ("app", "raised", "selected", "overlay")
    disabled = [v for s in surfaces for v in vals[f"disabled.{s}"]]
    faded = [v for s in surfaces for v in vals[f"faded.{s}"]]
    links = ("incident.link", "maint.link", "link.overlay")
    return [
        [
            "§15 `text.tertiary` on selected",
            "selected rows use `text.secondary`, dark (`meta.selected`)",
            r("meta.selected", "dark"),
        ],
        [
            "§15 T2 row",
            "`text.disabled` · `opacity.disabled` on app, raised, selected, overlay (ranges)",
            f"{min(disabled):.2f}{DASH}{max(disabled):.2f} · "
            f"{min(faded):.2f}{DASH}{max(faded):.2f}",
        ],
        [
            "§15, CG-24",
            "the hc link on `danger.subtle` · `warning.subtle` · overlay (aim 7)",
            " · ".join(r(k, "high-contrast") for k in links),
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
        rows.append(
            [
                p.key,
                p.element,
                f"`{p.fg}`",
                f"`{p.bg}`",
                p.role,
                *nums,
                verdict,
                aim_cell,
            ]
        )
    head = [
        "key",
        "element",
        "fg",
        "bg",
        "role",
        "dark",
        "light",
        "hc",
        "verdict",
        "hc 7:1 aim",
    ]
    table(head, rows)

    print("## B. Follow-up pairs (no frame binds them; not gated)\n")
    rows = []
    for p in FOLLOW_UPS:
        verdict, _ = judge(p.role, follow[p.key])
        nums = [f"{v:.2f}" for v in follow[p.key]]
        aim_cell = aim(p.role, follow[p.key])
        row = [
            p.key,
            p.element,
            f"`{p.fg}`",
            f"`{p.bg}`",
            p.role,
            *nums,
            "would " + verdict,
        ]
        rows.append([*row, aim_cell])
    table(
        [
            "key",
            "element",
            "fg",
            "bg",
            "as",
            "dark",
            "light",
            "hc",
            "verdict",
            "hc 7:1 aim",
        ],
        rows,
    )

    print(f"## C. Colour vision and greyscale (ΔE76; JND floor {JND:.1f}; ΔL* for greyscale)\n")
    rows = []
    for c in CVD_PAIRS:
        for t in THEMES:
            m = cv[(c.key, t)]
            ok = min(m[0:4]) >= JND
            verdict = "distinct" if ok else "collapses: a glyph or a word carries it"
            rows.append([c.key, c.label, t, *(f"{x:.1f}" for x in m), verdict])
    table(
        [
            "key",
            "pair",
            "theme",
            "normal",
            "protan",
            "deutan",
            "tritan",
            "ΔL*",
            "verdict",
        ],
        rows,
    )

    print("## D. §15's tables, regenerated (the spec's labels; every number from A and C)\n")
    text = {k: [f"{v:.2f}" for v in vs] for k, vs in vals.items()}
    rows = [[r.label, *cells(r, text, THEMES), row_verdict(r, vals)] for r in CONTRAST_TABLE]
    table(["Pair (fg on bg)", "Dark", "Light", "HC", "Verdict (this audit)"], rows)
    grey = {
        c.key: [f"{m[0]:.1f} / {m[2]:.1f}; {m[4]:.1f}" for m in (cv[(c.key, t)] for t in THEMES)]
        for c in CVD_PAIRS
    }
    rows = [[r.label, *cells(r, grey, CVD_THEMES)] for r in CVD_TABLE]
    table(["Pair (ΔE76 normal / deutan; ΔL*)", "Dark", "Light"], rows)
    table(["Where", "Number", "Value"], cited(vals))

    print("## E. Resolved values used above\n")
    seen: list[str] = []
    for a, b in [(p.fg, p.bg) for p in PAIRS + FOLLOW_UPS] + [(c.a, c.b) for c in CVD_PAIRS]:
        seen += [x for x in (a.split("@")[0], b) if x not in seen]
    table(
        ["token", "dark", "light", "hc"],
        [[f"`{x}`", *(col(t, x) for t in THEMES)] for x in seen],
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
    print(f"  ({', '.join(collapse) or 'none'}: a glyph or a word carries each)")
    print(f"\nFAIL count (gated rows only): {failed}")
    return 1 if failed else 0


if __name__ == "__main__":
    try:
        code = main()
    except (
        KeyError,
        OSError,
        ValueError,
    ) as exc:  # a broken input, never a contrast FAIL
        tool_error(f"{type(exc).__name__}: {exc}")
    raise SystemExit(code)
