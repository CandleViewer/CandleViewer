"""E42-D05 admin hi-fi audit: WCAG contrast, colour vision and §16's tables over the token JSON.

Standalone, offline, stdlib only, on the method of `e42_d02_admin_audit.py`. Every theme
(`dark`, `light`, `high-contrast`) resolves exactly as `packages/ui/tokens/tests/verify_tokens.py`
resolves it (same loader, same alias resolution, same set layering, checked against
`themes.json`); the ratio is `contrast_ratio()` from `docs/design/_tools/contrast_check.py`
(imported, not re-implemented); ΔE76, L* and the deuteranopia, protanopia and tritanopia
projections are those of `docs/research/_tools/cvd_simulate.py`. It measures every pair the hi-fi
spec (`docs/design/E42/E42-D05.md` §16) binds for SCR-143, SCR-144, SCR-146 with its restore
wizard, the onboarding wizard, SCR-017, SCR-062's governance layer and the statechart inspector,
the follow-up pairs its rows point at (the merged CMP-024 stroke, §21's C-row; the high-contrast
link aim, CG-30) and its colour-vision pairs, then regenerates the numbers of §16's two tables and
compares them, cell by cell, with the tables in the spec (its Verdict column is hand-written;
section D names each row's role).

Usage: python3 -I docs/design/_tools/e42_d05_admin_audit.py
(prints Markdown; exit 1 on a FAIL, 2 on a tool error)

Exit codes: 0 every gated row passes and every §16 number matches; 1 a gated row FAILs or a
number §16 states differs from this audit; 2 the tool itself cannot run (a helper that does not
load, a theme layered unlike verify_tokens.py, a duplicate key, a table cell with no pair, a token
with no colour or not an opaque #RRGGBB, a §16 row the spec no longer holds), so a caller never
reads a tool error as a FAIL.

Roles. `text` (4.5:1, WCAG 1.4.3) and `non-text` (3:1, WCAG 1.4.11) rows are gated in every theme,
and one FAIL exits 1. Every gated text row is also measured against the high-contrast theme's 7:1
aim for body text (`05-accessibility-standard.md` §5 item 6): reported, not gated (CG-30).
`exempt` rows bound inactive controls, which WCAG 1.4.3 and 1.4.11 exempt, and are reported so the
design never relies on them (T2 never uses `text.disabled`); `rejected-*` rows are pairs the spec
measured and designed around (`text.tertiary` on a selected row or a warning notice, the
`action.primary.default` current-step border, the `border.strong` sparkline). Neither is gated. A
stand-in for a catalogued token that does not exist (spec §16, "stand-ins, never inventions") is
prefixed `CR:` and measured on the token it aliases, never on an invented hex.
"""

from __future__ import annotations

import importlib.util
import json
import re
import sys
from pathlib import Path
from types import ModuleType
from typing import NamedTuple, NoReturn

ROOT = Path(__file__).resolve().parents[3]
TOKENS = ROOT / "packages" / "ui" / "tokens"
SPEC = ROOT / "docs" / "design" / "E42" / "E42-D05.md"
TOOL_ERROR = 2  # distinct from a gated FAIL (exit 1)


def tool_error(message: str) -> NoReturn:
    """Stop with exit 2: the audit could not run, which is never a contrast FAIL."""
    print(f"e42_d05_admin_audit: tool error: {message}", file=sys.stderr)
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
GATED = ("text", "non-text")
BAR: dict[str, float | None] = {
    "text": 4.5,
    "non-text": 3.0,
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
T = {n: resolve_theme(n) for n in THEMES}

# Stand-ins (`CR:`) for catalogued tokens that exist in no set (§16, CG-30), per theme: existing
# tokens only, exactly the alias the spec names.
CR: dict[str, dict[str, str]] = {
    # CMP-023's track: `color.track` → `color.surface.hover` (D04 §15; the track `main`'s CMP-023
    # now names).
    "CR:color.track": {t: "color.surface.hover" for t in THEMES},
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
    """Short constructor for the matrix below: the tokens without their `color.` prefix."""
    return Pair(key, element, tok(fg), tok(bg), role)


STALE = "data-confidence.stale"

# Every pair the frames bind, in the order of the rows of §16's contrast table (one pair per item
# of a table cell; an item the table repeats is measured once), then the exempt edge §16 names.
PAIRS: list[Pair] = [
    # --- T2 (§4.1): label and `lock`, then the reason ---
    P(
        "t2.label.raised",
        "T2 label and `lock` on raised",
        "text.tertiary",
        "surface.raised",
        "text",
    ),
    P(
        "t2.label.overlay",
        "T2 label and `lock` on a dialog",
        "text.tertiary",
        "surface.overlay",
        "text",
    ),
    P("t2.reason.raised", "T2 reason on raised", "text.secondary", "surface.raised", "text"),
    P(
        "t2.reason.overlay",
        "T2 reason on a dialog",
        "text.secondary",
        "surface.overlay",
        "text",
    ),
    # --- words and values ---
    P("word.raised", "words and values on raised", "text.primary", "surface.raised", "text"),
    P("word.hover", "words and values on hover", "text.primary", "surface.hover", "text"),
    P(
        "word.selected",
        "words and values on the selected row",
        "text.primary",
        "surface.selected",
        "text",
    ),
    P("word.app", "words and values on the page", "text.primary", "surface.app", "text"),
    # --- "as of", probe, meta ---
    P("meta.app", '"as of", probe and meta on the page', "text.tertiary", "surface.app", "text"),
    P(
        "meta.selected",
        "meta on the selected row (`text.secondary`)",
        "text.secondary",
        "surface.selected",
        "text",
    ),
    # --- rejected: `text.tertiary` where it misses 4.5 in dark ---
    P(
        "tertiary.selected",
        "the rejected `text.tertiary` on the selected row",
        "text.tertiary",
        "surface.selected",
        "rejected-text",
    ),
    P(
        "tertiary.warning",
        "the rejected `text.tertiary` on a warning notice",
        "text.tertiary",
        "status.warning.subtle",
        "rejected-text",
    ),
    P(
        "secondary.warning",
        "secondary text on a warning notice (the rule's replacement)",
        "text.secondary",
        "status.warning.subtle",
        "text",
    ),
    # --- status glyphs on raised (CMP-178's tile, CMP-210's chip) ---
    P(
        "glyph.check",
        "check on raised",
        "status.success.strong",
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
        "glyph.octagon",
        "octagon on raised",
        "status.danger.strong",
        "surface.raised",
        "non-text",
    ),
    P("glyph.clock", "clock (stale) on raised", f"{STALE}.indicator", "surface.raised", "non-text"),
    P("glyph.ring", "ring (not built) on raised", "neutral.default", "surface.raised", "non-text"),
    # --- stepper glyphs (CMP-066) on the page ---
    P(
        "step.done",
        "stepper check on the page",
        "status.success.strong",
        "surface.app",
        "non-text",
    ),
    P(
        "step.blocked",
        "stepper clock (blocked) on the page",
        "status.warning.strong",
        "surface.app",
        "non-text",
    ),
    P(
        "step.error",
        "stepper octagon on the page",
        "status.danger.strong",
        "surface.app",
        "non-text",
    ),
    P(
        "step.current",
        "stepper dot (current) on the page",
        "status.info.strong",
        "surface.app",
        "non-text",
    ),
    P(
        "step.todo",
        "stepper ring (not started) on the page",
        "neutral.default",
        "surface.app",
        "non-text",
    ),
    # --- the current step and the diagram's current state ---
    P(
        "current.app",
        "the current-step border on the page",
        "border.selected",
        "surface.app",
        "non-text",
    ),
    P(
        "current.raised",
        "the diagram's current-state border on raised",
        "border.selected",
        "surface.raised",
        "non-text",
    ),
    P(
        "current.selected",
        "the current-state border on a selected row",
        "border.selected",
        "surface.selected",
        "non-text",
    ),
    P(
        "current.rejected",
        "the rejected `action.primary.default` border on a selected row",
        "action.primary.default",
        "surface.selected",
        "rejected-non-text",
    ),
    # --- banners and notices ---
    P(
        "banner.danger",
        "banner and confirm text on `danger.subtle`",
        "text.primary",
        "status.danger.subtle",
        "text",
    ),
    P(
        "banner.warning",
        "banner text on `warning.subtle` (the secret-once notice)",
        "text.primary",
        "status.warning.subtle",
        "text",
    ),
    P(
        "banner.info",
        "banner text on `info.subtle`",
        "text.primary",
        "status.info.subtle",
        "text",
    ),
    P(
        "link.warning",
        "a link on `warning.subtle`",
        "text.link",
        "status.warning.subtle",
        "text",
    ),
    P("link.danger", "a link on `danger.subtle`", "text.link", "status.danger.subtle", "text"),
    # --- the stale chip (CMP-239) ---
    P("stale.chip", "stale chip text on its surface", f"{STALE}.text", f"{STALE}.surface", "text"),
    # --- the danger confirm (D02 §4.1 by reference) ---
    P(
        "confirm.border.subtle",
        "the confirm's `danger.strong` border vs `danger.subtle`",
        "status.danger.strong",
        "status.danger.subtle",
        "non-text",
    ),
    P(
        "confirm.border.overlay",
        "the confirm's `danger.strong` border vs the dialog",
        "status.danger.strong",
        "surface.overlay",
        "non-text",
    ),
    # --- progress (CMP-023) ---
    P(
        "progress.track",
        "progress fill on its track (`color.track` stand-in `surface.hover`)",
        "action.primary.default",
        "CR:color.track",
        "non-text",
    ),
    P(
        "progress.raised",
        "progress fill on raised",
        "action.primary.default",
        "surface.raised",
        "non-text",
    ),
    # --- sparkline (CMP-024) and the diagram's edges (CMP-146) ---
    P(
        "spark.raised",
        "the sparkline stroke `text.secondary` on raised",
        "text.secondary",
        "surface.raised",
        "non-text",
    ),
    P(
        "edges.raised",
        "the diagram's edges `text.tertiary` on raised",
        "text.tertiary",
        "surface.raised",
        "non-text",
    ),
    P(
        "spark.rejected",
        "the rejected `border.strong` stroke on raised",
        "border.strong",
        "surface.raised",
        "rejected-non-text",
    ),
    # --- the focus ring ---
    P("ring.raised", "focus ring on raised", "focus.ring", "surface.raised", "non-text"),
    P("ring.overlay", "focus ring on a dialog", "focus.ring", "surface.overlay", "non-text"),
    P("ring.app", "focus ring on the page", "focus.ring", "surface.app", "non-text"),
    P("ring.hover", "focus ring on hover", "focus.ring", "surface.hover", "non-text"),
    P(
        "ring.selected",
        "focus ring on a selected row",
        "focus.ring",
        "surface.selected",
        "non-text",
    ),
    P(
        "ring.danger",
        "focus ring on `danger.subtle`",
        "focus.ring",
        "status.danger.subtle",
        "non-text",
    ),
    P(
        "ring.warning",
        "focus ring on `warning.subtle`",
        "focus.ring",
        "status.warning.subtle",
        "non-text",
    ),
    # --- exempt: T2 never uses `text.disabled` (§4.1, D09) ---
    P(
        "disabled.raised",
        "`text.disabled` on raised (never used: T2 is `text.tertiary`)",
        "text.disabled",
        "surface.raised",
        "exempt",
    ),
]

# Follow-up pairs that no frame binds today: the merged CMP-024 stroke (§21's C-row: `15`'s
# CMP-024 Tokens draw a sign-less sparkline in `text.tertiary`, where §16 draws `text.secondary`)
# and a link on raised and on a dialog (CG-30's high-contrast link aim). Reported, never gated.
FOLLOW_UPS: list[Pair] = [
    P(
        "fu.spark.tertiary",
        "the merged CMP-024 stroke `text.tertiary` on raised",
        "text.tertiary",
        "surface.raised",
        "non-text",
    ),
    P("fu.link.raised", "a link on raised", "text.link", "surface.raised", "text"),
    P("fu.link.overlay", "a link on a dialog", "text.link", "surface.overlay", "text"),
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
        "cvd.success-warning",
        "`success.strong` vs `warning.strong`",
        "status.success.strong",
        "status.warning.strong",
    ),
    C(
        "cvd.success-danger",
        "`success.strong` vs `danger.strong`",
        "status.success.strong",
        "status.danger.strong",
    ),
    C(
        "cvd.warning-danger",
        "`warning.strong` vs `danger.strong`",
        "status.warning.strong",
        "status.danger.strong",
    ),
    C(
        "cvd.stale-warning",
        "`stale.indicator` vs `warning.strong`",
        f"{STALE}.indicator",
        "status.warning.strong",
    ),
    C(
        "cvd.neutral-success",
        "`neutral.default` vs `success.strong`",
        "neutral.default",
        "status.success.strong",
    ),
    C(
        "cvd.subtle.success-danger",
        "`success.subtle` vs `danger.subtle`",
        "status.success.subtle",
        "status.danger.subtle",
    ),
    C(
        "cvd.info-warning",
        "`info.strong` vs `warning.strong` (current vs blocked step)",
        "status.info.strong",
        "status.warning.strong",
    ),
    C(
        "cvd.info-success",
        "`info.strong` vs `success.strong` (current vs done step)",
        "status.info.strong",
        "status.success.strong",
    ),
]


class TableRow(NamedTuple):
    """A §16 table row: its label and its cell items (" · " in a group, "; " between groups)."""

    label: str
    groups: list[list[str]]


def R(label: str, *groups: list[str]) -> TableRow:
    return TableRow(label, list(groups))


# §16's contrast table, row for row: the spec's labels verbatim, every number regenerated.
CONTRAST_TABLE: list[TableRow] = [
    R(
        "T2: label and `lock` `text.tertiary` on raised · overlay; reason `text.secondary` on "
        "raised · overlay",
        ["t2.label.raised", "t2.label.overlay"],
        ["t2.reason.raised", "t2.reason.overlay"],
    ),
    R(
        "words and values `text.primary` on raised · hover · selected · app",
        ["word.raised", "word.hover", "word.selected", "word.app"],
    ),
    R(
        '"as of", probe, meta `text.tertiary` on raised · app; `text.secondary` on selected',
        ["t2.label.raised", "meta.app"],
        ["meta.selected"],
    ),
    R(
        "`text.tertiary` on selected · on `warning.subtle`",
        ["tertiary.selected", "tertiary.warning"],
    ),
    R(
        "glyphs on raised: check `success.strong` · triangle `warning.strong` · octagon "
        "`danger.strong` · clock `stale.indicator` · ring `neutral.default`",
        ["glyph.check", "glyph.triangle", "glyph.octagon", "glyph.clock", "glyph.ring"],
    ),
    R(
        "stepper glyphs on app: `success.strong` · `warning.strong` · `danger.strong` · "
        "`info.strong` · `neutral.default`",
        ["step.done", "step.blocked", "step.error", "step.current", "step.todo"],
    ),
    R(
        "current step and the diagram's current state: `border.selected` on app · raised · "
        "selected; rejected `action.primary.default` on selected",
        ["current.app", "current.raised", "current.selected"],
        ["current.rejected"],
    ),
    R(
        "banners: `text.primary` on `danger.subtle` · `warning.subtle` · `info.subtle`; link on "
        "`warning.subtle` · `danger.subtle`",
        ["banner.danger", "banner.warning", "banner.info"],
        ["link.warning", "link.danger"],
    ),
    R("stale chip `stale.text` on `stale.surface`", ["stale.chip"]),
    R(
        "confirm: text on `danger.subtle`; `danger.strong` border vs `danger.subtle` · vs overlay",
        ["banner.danger"],
        ["confirm.border.subtle", "confirm.border.overlay"],
    ),
    R(
        'progress: fill on the `surface.hover` track · on raised; "{n} %" `text.secondary` on '
        "raised",
        ["progress.track", "progress.raised"],
        ["t2.reason.raised"],
    ),
    R(
        "sparkline `text.secondary` and diagram edges `text.tertiary` on raised (`border.strong` "
        "rejected: 1.80 / 1.46 / 1.80)",
        ["spark.raised", "edges.raised"],
    ),
    R(
        "focus ring on raised · overlay · app · hover · selected · `danger.subtle` · "
        "`warning.subtle`",
        [
            "ring.raised",
            "ring.overlay",
            "ring.app",
            "ring.hover",
            "ring.selected",
            "ring.danger",
            "ring.warning",
        ],
    ),
]

# §16's greyscale and colour-vision table (Dark and Light; the cells read "ΔE76 normal / deutan;
# ΔL*").
CVD_TABLE: list[TableRow] = [
    R(
        "`success.strong` vs `warning.strong` · vs `danger.strong`",
        ["cvd.success-warning", "cvd.success-danger"],
    ),
    R("`warning.strong` vs `danger.strong`", ["cvd.warning-danger"]),
    R("`stale.indicator` vs `warning.strong`", ["cvd.stale-warning"]),
    R("`neutral.default` vs `success.strong`", ["cvd.neutral-success"]),
    R("`success.subtle` vs `danger.subtle`", ["cvd.subtle.success-danger"]),
]
CVD_THEMES = ("dark", "light")

ROLE = {p.key: p.role for p in PAIRS + FOLLOW_UPS}


def check_keys() -> None:
    """Every key is unique and every table cell names a measured pair."""
    keys = [p.key for p in PAIRS + FOLLOW_UPS] + [c.key for c in CVD_PAIRS]
    dupes = sorted({k for k in keys if keys.count(k) > 1})
    if dupes:
        tool_error(f"duplicate keys: {dupes}")
    for rows, known in (
        (CONTRAST_TABLE, {p.key for p in PAIRS}),
        (CVD_TABLE, {c.key for c in CVD_PAIRS}),
    ):
        missing = [k for r in rows for g in r.groups for k in g if k not in known]
        if missing:
            tool_error(f"table cells without a pair: {missing}")


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
    keys = list(dict.fromkeys(k for g in row.groups for k in g))
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
    """The numbers §16 cites in its verdicts and labels, each from a pair."""

    def r(key: str, *themes: str, sep: str = " / ") -> str:
        return sep.join(f"{vals[key][THEMES.index(t)]:.2f}" for t in themes or THEMES)

    return [
        [
            "§16 T2 row",
            "`text.disabled` never used: on raised, dark / light / hc",
            r("disabled.raised"),
        ],
        [
            "§16 `text.tertiary` row",
            "selected rows and warning notices use `text.secondary`, dark",
            r("meta.selected", "dark") + " · " + r("secondary.warning", "dark"),
        ],
        [
            "§16 glyph row",
            "never as text: the light check on raised",
            r("glyph.check", "light"),
        ],
        [
            "§16 sparkline row",
            "`border.strong` rejected: dark / light / hc",
            r("spark.rejected"),
        ],
        [
            "§16 banner row, CG-30",
            "hc links on `warning.subtle` · `danger.subtle` (aim 7)",
            r("link.warning", "high-contrast") + " · " + r("link.danger", "high-contrast"),
        ],
    ]


# The spec side: §16's two tables as the spec states them, and the numbers its labels and
# verdicts cite. A row is found by its first cell, verbatim; its cells are compared as text.
NUM = re.compile(r"\d+\.\d+")


def spec_rows() -> dict[str, list[str]]:
    """Every row of §16's tables in the spec: first cell → the other cells, stripped."""
    text = read_text(SPEC)
    start = text.find("\n## 16. ")
    end = text.find("\n## 17. ")
    if start < 0 or end < start:
        tool_error(f"{SPEC.name}: no §16")
    rows: dict[str, list[str]] = {}
    for line in text[start:end].split("\n"):
        if not line.startswith("| ") or set(line) <= set("|- "):
            continue
        parts = [c.strip() for c in re.split(r"(?<!\\)\|", line)[1:-1]]
        rows[parts[0]] = parts[1:]
    return rows


def compare(
    rows: list[TableRow], regenerated: dict[str, list[str]], spec: dict[str, list[str]]
) -> list[list[str]]:
    """One line per cell: the spec's text, this audit's, and whether they agree."""
    out = []
    for row in rows:
        if row.label not in spec:
            tool_error(f"§16 holds no row {row.label!r}")
        for theme, mine, theirs in zip(
            ("dark", "light", "high-contrast"),
            regenerated[row.label],
            spec[row.label],
            strict=False,
        ):
            out.append([row.label[:48], theme, theirs, mine, "match" if mine == theirs else "DIFF"])
    return out


def cited_in_spec(spec: dict[str, list[str]], vals: dict[str, list[float]]) -> list[list[str]]:
    """The cited numbers, each looked up where §16 states it."""
    disabled = " / ".join(f"{v:.2f}" for v in vals["disabled.raised"])
    rejected = " / ".join(f"{v:.2f}" for v in vals["spark.rejected"])
    selected = f"({vals['meta.selected'][0]:.2f} · {vals['secondary.warning'][0]:.2f})"
    t2 = CONTRAST_TABLE[0].label
    tert = CONTRAST_TABLE[3].label
    glyph = CONTRAST_TABLE[4].label
    spark = CONTRAST_TABLE[11].label
    checks = [
        ("`text.disabled` (T2 verdict)", f"({disabled})", spec[t2][-1]),
        ("`text.secondary` instead (verdict)", selected, spec[tert][-1]),
        ("light check, never as text", f"(light {vals['glyph.check'][1]:.2f})", spec[glyph][-1]),
        ("`border.strong` rejected (label)", f"rejected: {rejected}", spark),
    ]
    return [[w, want, "match" if want in where else "DIFF"] for w, want, where in checks]


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
        row = [p.key, p.element, f"`{p.fg}`", f"`{p.bg}`", p.role, *nums, verdict]
        rows.append([*row, aim(p.role, vals[p.key])])
    head = ["key", "element", "fg", "bg", "role", "dark", "light", "hc", "verdict", "hc 7:1 aim"]
    table(head, rows)

    print("## B. Follow-up pairs (no frame binds them; not gated)\n")
    rows = []
    for p in FOLLOW_UPS:
        verdict, _ = judge(p.role, follow[p.key])
        nums = [f"{v:.2f}" for v in follow[p.key]]
        row = [p.key, p.element, f"`{p.fg}`", f"`{p.bg}`", p.role, *nums, "would " + verdict]
        rows.append([*row, aim(p.role, follow[p.key])])
    table(
        ["key", "element", "fg", "bg", "as", "dark", "light", "hc", "verdict", "hc 7:1 aim"], rows
    )

    print(f"## C. Colour vision and greyscale (ΔE76; JND floor {JND:.1f}; ΔL* for greyscale)\n")
    rows = []
    for c in CVD_PAIRS:
        for t in THEMES:
            m = cv[(c.key, t)]
            ok = min(m[0:4]) >= JND
            verdict = "distinct" if ok else "collapses: a glyph or a word carries it"
            rows.append([c.key, c.label, t, *(f"{x:.1f}" for x in m), verdict])
    head = ["key", "pair", "theme", "normal", "protan", "deutan", "tritan", "ΔL*", "verdict"]
    table(head, rows)

    print("## D. §16's tables, regenerated (the spec's labels; every number from A and C)\n")
    text = {k: [f"{v:.2f}" for v in vs] for k, vs in vals.items()}
    contrast = {r.label: cells(r, text, THEMES) for r in CONTRAST_TABLE}
    rows = [[r.label, *contrast[r.label], row_verdict(r, vals)] for r in CONTRAST_TABLE]
    table(["Pair (fg on bg)", "Dark", "Light", "HC", "Verdict (this audit)"], rows)
    grey = {
        c.key: [f"{m[0]:.1f} / {m[2]:.1f}; {m[4]:.1f}" for m in (cv[(c.key, t)] for t in THEMES)]
        for c in CVD_PAIRS
    }
    colour = {r.label: cells(r, grey, CVD_THEMES) for r in CVD_TABLE}
    rows = [[r.label, *colour[r.label]] for r in CVD_TABLE]
    table(["Pair (ΔE76 normal / deutan; ΔL*)", "Dark", "Light"], rows)
    table(["Where", "Number", "Value"], cited(vals))

    print("## E. §16 as the spec states it, cell by cell against D\n")
    spec = spec_rows()
    rows = compare(CONTRAST_TABLE, contrast, spec) + compare(CVD_TABLE, colour, spec)
    table(["row", "theme", "spec", "this audit", "check"], rows)
    cites = cited_in_spec(spec, vals)
    table(["cited number", "this audit", "check"], cites)
    drift = sum(r[-1] == "DIFF" for r in rows + cites)

    print("## F. Resolved values used above\n")
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
    print(f"  ({', '.join(collapse) or 'none'}: a glyph or a word carries each)")
    print(
        f"- §16 against this audit: {len(rows) + len(cites)} cells and cited numbers; {drift} differ"
    )
    print(f"\nFAIL count (gated rows and differing §16 numbers): {failed + drift}")
    return 1 if failed + drift else 0


if __name__ == "__main__":
    try:
        code = main()
    except (KeyError, OSError, ValueError) as exc:  # a broken input, never a contrast FAIL
        tool_error(f"{type(exc).__name__}: {exc}")
    raise SystemExit(code)
