"""E39-D03 token audit: WCAG contrast matrix, token bindings and the board counts over the tokens.

Standalone, offline, stdlib only, run with `python3 -I`. Resolves the three themes exactly as
`packages/ui/tokens/tests/verify_tokens.py` layers them (`themes.json`: dark = primitives +
semantic-dark; light adds semantic-light; high-contrast adds semantic-hc) with the same `{alias}`
resolver, re-implemented here so the tool imports nothing from that test module. The contrast
formula is the WCAG 2.x relative-luminance ratio of `docs/design/_tools/contrast_check.py`,
re-implemented identically (sRGB linearisation at the 0.03928 threshold, 0.05 flare), so the
numbers agree with E39-D01 section 9.4, E40-D01 CR-23..CR-25 and E11-D02.

It prints, with a source label on every row: (1) the ratio of every fg / bg pair SCR-072, SCR-134
and CMP-211 bind, dark / light / high-contrast, against the role's bar (text 4.5, non-text 3.0,
hc-text 7.0 only where the spec claims the 05 section 5 item 3 stretch), compared UNROUNDED (a
value that would round onto a bar is printed to four decimals), PASS / FAIL; `decorative`,
`exempt` and `rejected-*` rows are reported, never gated; (2) every token the spec, the `15`
CMP-211 entry and the handoff bind, resolved in every theme or MISSING, and the PROPOSED
`motion.duration.hold-confirm` as `CR:` with its value; (3) which pairs `tools/contrast/pairs.mjs`
registers (text scan) and which bound tokens `exemptions.json` exempts; (4) the counts the boards
quote, the caps and their bounds parsed from the `21` DDL text, and the E39-D01 / E40-D01 figures
re-derived here.

Usage: python3 -I docs/design/_tools/e39_d03_token_audit.py [--json]  (exit 1 only on a gated FAIL)
Stdout is forced to UTF-8. No network; no URL literal anywhere in this file.
"""

from __future__ import annotations

import json
import re
import sys
from pathlib import Path
from typing import TypedDict, cast

ROOT = Path(__file__).resolve().parents[3]
TOKENS = ROOT / "packages" / "ui" / "tokens"
PAIRS_MJS = ROOT / "tools" / "contrast" / "pairs.mjs"
EXEMPTIONS = ROOT / "tools" / "contrast" / "exemptions.json"
SCHEMA_DOC = ROOT / "docs" / "plan" / "21-database-schema.md"
PRIMITIVES = "primitives.tokens.json"
THEMES: dict[str, tuple[str, ...]] = {
    "dark": (PRIMITIVES, "semantic-dark.tokens.json"),
    "light": (PRIMITIVES, "semantic-dark.tokens.json", "semantic-light.tokens.json"),
    "high-contrast": (PRIMITIVES, "semantic-dark.tokens.json", "semantic-hc.tokens.json"),
}
THEME_ORDER = ("dark", "light", "high-contrast")
BAR: dict[str, float | None] = {
    "text": 4.5,
    "non-text": 3.0,
    "hc-text": 7.0,
    "decorative": None,
    "exempt": None,
    "rejected-text": 4.5,
    "rejected-non-text": 3.0,
    "rejected-hc-text": 7.0,
}
GATED = ("text", "non-text", "hc-text")
BARS = (3.0, 4.5, 7.0)
HEX6 = re.compile(r"^#[0-9A-Fa-f]{6}$")
Tokens = dict[str, dict[str, object]]

# element | fg | bg | role | source  -- one record per line; a line indented by two spaces
# continues the record above it; the roles are the BAR keys.
PAIRS_TABLE = """
Confirm label on the danger button (CMP-001 danger, SCR-072) | color.text.on-action
  | color.status.danger.default | text | spec s4, s12; E39-D01 s9.4
Primary button label (Review changes, Reload theirs) | color.text.on-action
  | color.action.primary.default | text | spec s6
Dialog title, consequence box, option labels | color.text.primary | color.surface.overlay
  | text | spec s4
Dialog subtitle, helper text, footer sentence | color.text.secondary | color.surface.overlay
  | text | spec s4
Dialog captions: as-of time, counter n / 280 | color.text.tertiary | color.surface.overlay
  | text | spec s4
Cluster button label; T2 full label | color.text.primary | color.surface.raised | text | spec s5
T2 reason sentence; status chip text | color.text.secondary | color.surface.raised | text
  | spec s5; E09-D09 T2
T2 lock glyph and label | color.text.tertiary | color.surface.raised | text | spec s5; E09-D09 T2
Fieldset legend, values (SCR-134) | color.text.primary | color.surface.app | text | spec s6
Helper and when-breached sentence (SCR-134) | color.text.secondary | color.surface.app | text
  | spec s6
As-of captions (SCR-134) | color.text.tertiary | color.surface.app | text | spec s6
Caption on a selected row -- REJECTED (the E39-D01 s9.4 ban) | color.text.tertiary
  | color.surface.selected | rejected-text | E39-D01 s9.4: 3.98 dark
Caption on a selected row -- adopted | color.text.secondary | color.surface.selected | text
  | spec s6, s12
Hovered cluster button label | color.text.primary | color.surface.hover | text | spec s5
Danger callout title (partial failure, 422 refusal) | color.text.primary
  | color.status.danger.subtle | text | E40-D01 CR-23
Danger callout body; locked-cancel reason | color.text.secondary | color.status.danger.subtle
  | text | E40-D01 CR-24; spec s4
Danger callout glyph | color.status.danger.strong | color.status.danger.subtle | non-text
  | E40-D01 CR-25
Warning callout text (validation warning, PROPOSED stamp) | color.text.primary
  | color.status.warning.subtle | text | spec s6
Warning callout glyph | color.status.warning.strong | color.status.warning.subtle | non-text
  | spec s6
Danger accent on the app chrome (cluster hue) | color.status.danger.default | color.surface.app
  | non-text | spec s5
Refused-field border on the dialog | color.status.danger.default | color.surface.overlay
  | non-text | spec s4, s6
Hold ring fill (danger hue; the percentage text is its twin) | color.status.danger.default
  | color.surface.raised | non-text | spec s5
State glyph strokes on the raised cluster (lock, check) | color.text.primary
  | color.surface.raised | non-text | spec s5; E39-D01 s9.4
Warning accent on the app chrome | color.status.warning.default | color.surface.app | non-text
  | spec s6
Warning accent on the dialog (reinforcement) | color.status.warning.default
  | color.surface.overlay | decorative | spec s4
Meter fill near cap on the raised fieldset (number + glyph carry it)
  | color.status.warning.default | color.surface.raised | decorative | spec s6; E39-D01 D8
LIVE badge border on the app chrome | color.env.live | color.surface.app | non-text
  | 14 s0.5 item 1
DEMO badge border on the app chrome | color.env.demo | color.surface.app | non-text
  | 14 s0.5 item 1
LIVE badge border on the raised row (CMP-075) | color.env.live | color.surface.raised | non-text
  | spec s4
DEMO badge border on the raised row (CMP-075) | color.env.demo | color.surface.raised | non-text
  | spec s4
LIVE / DEMO badge text (05 s5 item 3 stretch) | color.text.primary | color.surface.raised
  | hc-text | spec s9, s12
LIVE as coloured text -- REJECTED (the stretch would fail) | color.env.live | color.surface.app
  | rejected-hc-text | spec s12
DEMO as coloured text -- REJECTED | color.env.demo | color.surface.app | rejected-hc-text
  | spec s12
Focus ring on the app chrome | color.focus.ring | color.surface.app | non-text | 05 s3.4 item 6
Focus ring on the dialog | color.focus.ring | color.surface.overlay | non-text | 05 s3.4 item 6
Focus ring on the raised cluster | color.focus.ring | color.surface.raised | non-text
  | 05 s3.4 item 6
Focus ring against the danger fill inside the 2 px offset -- REJECTED | color.focus.ring
  | color.status.danger.default | rejected-non-text | spec s11: hence the offset
Dialog hairline, fieldset border (structure) | color.border.default | color.surface.overlay
  | decorative | spec s4
Dialog strong divider (structure) | color.border.strong | color.surface.overlay | decorative
  | spec s4
T2 hairline on the raised host (structure) | color.border.default | color.surface.raised
  | decorative | E09-D09 T2
Hold ring track (structure) | color.border.strong | color.surface.raised | decorative | spec s5
Disabled text -- EXEMPT; never used by CMP-211 T2 (dialog) | color.text.disabled
  | color.surface.overlay | exempt | WCAG 1.4.3; E09-D09 T2
Disabled text -- EXEMPT (raised) | color.text.disabled | color.surface.raised | exempt
  | WCAG 1.4.3
Disabled text -- EXEMPT (app) | color.text.disabled | color.surface.app | exempt | WCAG 1.4.3
"""

# token | bound by
BINDINGS_TABLE = """
color.status.danger.default | CMP-211, CMP-001 danger, SCR-072 Confirm, the hold ring
color.status.danger.subtle | SCR-072 failure callouts, SCR-134 refusal callout
color.status.danger.strong | callout glyphs (E40 CR-25)
color.status.warning.default | CMP-138 meter near cap (reinforcement)
color.status.warning.subtle | SCR-134 validation warning, PROPOSED stamp
color.status.warning.strong | warning glyph
color.env.demo | CMP-075 badge border
color.env.live | CMP-075 badge border
color.text.primary | every title, label, value; state glyph strokes
color.text.secondary | subtitles, helpers, T2 reason
color.text.tertiary | captions, T2 label
color.text.disabled | reported only; never on CMP-211 T2 (E09-D09)
color.text.inverse | none here (reported)
color.text.on-action | danger / primary button labels
color.surface.app | SCR-134 page, shell
color.surface.raised | cluster, badges, T2 host, fieldsets
color.surface.overlay | the SCR-072 card
color.surface.canvas | the shell content area behind the scrim
color.surface.hover | hovered cluster button
color.surface.selected | selected rows, nav-active
color.surface.sunken | none here (reported; E09-D08 C-12)
color.border.subtle | row separators
color.border.default | hairlines
color.border.strong | dividers, ring track
color.focus.ring | the 2 px ring
color.action.primary.default | Review changes, Reload theirs
color.action.primary.hover | hover of the same
color.action.primary.active | active of the same
color.action.selected | checked box / radio fill (CMP-005 / CMP-006)
space.2 | cluster gap
space.inset.xs | pill x inset
space.inset.sm | compact row inset
space.inset.md | comfortable row inset, dialog inner
space.inset.lg | dialog outer inset
size.control.height | cluster button height
size.target.min | 24 px floor
radius.control | buttons, fields
radius.card | fieldsets, callouts
radius.dialog | the SCR-072 card
radius.badge | CMP-075 badge
radius.pill | chips, Kbd caps
border.focus | ring width
opacity.scrim | the scrim (black in every theme, E09-D08 D2)
opacity.disabled | the disabled box only (confirm-manager)
opacity.muted | de-emphasised captions
elevation.dialog | the card
elevation.scrim | the scrim layer
elevation.4 | primitive behind elevation.dialog
elevation.5 | primitive behind elevation.scrim
motion.duration.instant | reduce twin
motion.duration.fast | scrim fade, Confirm-label swap
motion.duration.normal | SCR-006 chassis (E09-D08 D2)
motion.duration.slow | none here (reported)
type.ui.caption | captions
type.ui.body | body copy
type.ui.body-strong | the positions line, legends
type.ui.label | option labels
type.ui.heading-sm | dialog title
type.ui.heading-md | SCR-134 h1
type.num.sm | counts in rows
type.num.base | limit values, measured figures
type.num.md | the blast-radius totals
color.surface.admin-tint | CMP-087 (MISSING; E42-D02 DS-1 aliases color.surface.raised)
font.mono | CMP-008, CMP-022, CMP-035 (MISSING; type.num.* carries the mono family)
color.surface.scrim | E09-D08 A-2 PROPOSED (MISSING here; cited, not re-proposed)
color.callout.danger | CMP-028 (MISSING; danger.subtle + strong used instead)
color.action.danger | CMP-001 danger variant (MISSING; status.danger.default used)
"""

# name | value | owner
PROPOSED_TABLE = """
motion.duration.hold-confirm | 800ms | E05-D02 lane (Q4; US-SET-003 range 300-2000 ms)
"""

# group | comma-separated story names (one record per group)
STORIES_TABLE = """
CMP-211 | AccountScope, GroupScope, GlobalScope, KillSwitchArmed, KillSwitchEngaged,
  HoldInProgress, DiscretePressArmed, TypedConfirmError, DisabledViewer, DisabledManagerGlobal,
  Disconnected, ReducedMotion
SCR-072 | ConfirmAccount, ConfirmFlattenTicked, ConfirmGlobal, ConfirmManager, ConfirmDemo,
  ConfirmDisconnected, Executing, Completed, EngagedNotDurable, EngagedBySystem, PartialFailure,
  CancelNotVerified, Release
SCR-134 | Clean, NeverOwnerConfirmed, ValidationWarning, ChangeSummary, StepUpRequired,
  SaveRefusedPolicyFloor, SaveConflict
"""
CMP211_STATES = (
    "default, hover, focus-visible, active, holding, armed, disabled-with-reason, engaged"
)
CMP211_MODES = "single, hold, typed"
CMP211_BUTTONS = "Flatten all, Cancel all, Kill switch"
CAP_COLUMNS = (
    "max_total_notional_usd, max_daily_loss_usd, max_drawdown_pct, max_open_positions, "
    "max_leverage, max_orders_per_minute, per_symbol_concentration_pct"
)

# label | fg | bg | theme | expected  -- figures published elsewhere, re-derived here
EXPECTED_TABLE = """
E39-D01 s9.4 on-action on danger, dark | color.text.on-action | color.status.danger.default
  | dark | 5.05
E39-D01 s9.4 on-action on danger, hc | color.text.on-action | color.status.danger.default
  | high-contrast | 4.54
E39-D01 s9.4 tertiary on selected, dark | color.text.tertiary | color.surface.selected | dark
  | 3.98
E40-D01 CR-23 dark | color.text.primary | color.status.danger.subtle | dark | 12.06
E40-D01 CR-23 light | color.text.primary | color.status.danger.subtle | light | 14.64
E40-D01 CR-23 hc | color.text.primary | color.status.danger.subtle | high-contrast | 13.66
E40-D01 CR-24 dark | color.text.secondary | color.status.danger.subtle | dark | 7.40
E40-D01 CR-24 light | color.text.secondary | color.status.danger.subtle | light | 8.42
E40-D01 CR-24 hc | color.text.secondary | color.status.danger.subtle | high-contrast | 12.06
E40-D01 CR-25 dark | color.status.danger.strong | color.status.danger.subtle | dark | 7.83
E40-D01 CR-25 light | color.status.danger.strong | color.status.danger.subtle | light | 3.85
E40-D01 CR-25 hc | color.status.danger.strong | color.status.danger.subtle | high-contrast | 7.83
"""

# key | value  -- the anatomy constants the boards quote (the computed counts are added in code)
CONSTANTS_TABLE = """
boards | 14
handoff_lines | 13
hold_confirm_ms | 800
hold_range_min_ms | 300
hold_range_max_ms | 2000
discrete_window_s | 5
dialog_width_px | 560
hit_target_px | 24
cluster_row_px | 32
reason_min | 3
reason_max | 280
lockout_min | 1
lockout_max | 1440
"""


class PairRow(TypedDict):
    element: str
    fg: str
    bg: str
    role: str
    bar: float | None
    ratios: dict[str, float | None]
    verdict: str
    registered: bool
    source: str


class TokenRow(TypedDict):
    token: str
    bound_by: str
    status: str
    values: dict[str, str]


class RepRow(TypedDict):
    label: str
    expected: float
    computed: float | None
    reproduced: bool


def rows(table: str) -> list[list[str]]:
    """One record per line; a line indented by two spaces continues the record above it."""
    records: list[str] = []
    for ln in table.strip("\n").splitlines():
        if not ln:
            continue
        if ln.startswith("  ") and records:
            records[-1] += " " + ln.strip()
        else:
            records.append(ln.strip())
    return [[c.strip() for c in rec.split(" | ")] for rec in records]


def words(csv: str) -> tuple[str, ...]:
    return tuple(x.strip() for x in csv.split(","))


PAIRS = rows(PAIRS_TABLE)
BINDINGS = rows(BINDINGS_TABLE)
PROPOSED = rows(PROPOSED_TABLE)
STORIES = {k: words(v) for k, v in rows(STORIES_TABLE)}
EXPECTED = rows(EXPECTED_TABLE)
CONSTANTS = {k: int(v) for k, v in rows(CONSTANTS_TABLE)}


def load(name: str) -> Tokens:
    return cast(Tokens, json.loads((TOKENS / name).read_text(encoding="utf-8")))


def merged(files: tuple[str, ...]) -> Tokens:
    out: Tokens = {}
    for f in files:  # later files override earlier ones, as verify_tokens.merged_set does
        out.update(load(f))
    return out


def resolve(value: object, tokens: Tokens, seen: frozenset[str] = frozenset()) -> object:
    if isinstance(value, str) and value.startswith("{") and value.endswith("}"):
        ref = value[1:-1]
        if ref in seen:
            raise ValueError(f"circular reference: {ref}")
        if ref not in tokens:
            raise KeyError(ref)
        return resolve(tokens[ref]["$value"], tokens, seen | {ref})
    if isinstance(value, dict):
        return {k: resolve(v, tokens, seen) for k, v in cast(dict[str, object], value).items()}
    if isinstance(value, list):
        return [resolve(v, tokens, seen) for v in cast(list[object], value)]
    return value


def hex_of(name: str, tokens: Tokens) -> str | None:
    if name not in tokens:
        return None
    value = resolve(tokens[name]["$value"], tokens)
    return value if isinstance(value, str) and HEX6.match(value) else None


def luminance(hex6: str) -> float:  # identical to contrast_check.relative_luminance
    def chan(c: int) -> float:
        x = c / 255
        return x / 12.92 if x <= 0.03928 else ((x + 0.055) / 1.055) ** 2.4

    r, g, b = (int(hex6[i : i + 2], 16) for i in (1, 3, 5))
    return 0.2126 * chan(r) + 0.7152 * chan(g) + 0.0722 * chan(b)


def contrast(a: str, b: str) -> float:
    la, lb = luminance(a), luminance(b)
    return (max(la, lb) + 0.05) / (min(la, lb) + 0.05)


def registered_pairs() -> set[tuple[str, str]]:
    text = PAIRS_MJS.read_text(encoding="utf-8")
    return set(re.findall(r'fg:\s*"([^"]+)",\s*bg:\s*"([^"]+)"', text))


def exempt_tokens() -> set[str]:
    data = cast(dict[str, object], json.loads(EXEMPTIONS.read_text(encoding="utf-8")))
    found: set[str] = set()
    for item in cast(list[object], data.get("exemptions", [])):
        tok = cast(dict[str, object], item).get("token") if isinstance(item, dict) else None
        if isinstance(tok, str):
            found.add(tok)
    return found


def measure(themes: dict[str, Tokens], reg: set[tuple[str, str]]) -> list[PairRow]:
    out: list[PairRow] = []
    for element, fg, bg, role, source in PAIRS:
        bar = BAR[role]
        ratios: dict[str, float | None] = {}
        fails: list[str] = []
        for theme in THEME_ORDER:
            a, b = hex_of(fg, themes[theme]), hex_of(bg, themes[theme])
            exact = contrast(a, b) if a and b else None  # compared unrounded
            ratios[theme] = None if exact is None else round(exact, 4)
            gated_here = role in GATED and (role != "hc-text" or theme == "high-contrast")
            if gated_here and bar is not None and (exact is None or exact < bar):
                fails.append(theme)
        low = [t for t in THEME_ORDER if bar is not None and (ratios[t] or 0) < bar]
        low3 = [t for t in THEME_ORDER if (ratios[t] or 0) < 3.0]
        if role in ("decorative", "exempt"):
            below = "; below 3:1 in " + ", ".join(low3) if low3 else ""
            verdict = f"{role} (reported{below})"
        elif role.startswith("rejected"):
            verdict = "rejected: fails " + ", ".join(low) if low else "rejected: passes, not used"
        else:
            verdict = "PASS" if not fails else "FAIL " + ", ".join(fails)
        row: PairRow = {
            "element": element,
            "fg": fg,
            "bg": bg,
            "role": role,
            "bar": bar,
            "ratios": ratios,
            "verdict": verdict,
            "registered": (fg, bg) in reg,
            "source": source,
        }
        out.append(row)
    return out


def shown(name: str, tokens: Tokens) -> str:
    value = resolve(tokens[name]["$value"], tokens)
    if isinstance(value, str):
        return value
    if isinstance(value, dict) and "fontFamily" in value:
        return "typography (" + json.dumps(cast(dict[str, object], value)["fontFamily"]) + ")"
    return json.dumps(value)


def bindings(themes: dict[str, Tokens]) -> list[TokenRow]:
    out: list[TokenRow] = []
    for token, bound_by in BINDINGS:
        values = {t: shown(token, themes[t]) for t in THEME_ORDER if token in themes[t]}
        status = "resolved" if len(values) == len(THEME_ORDER) else "MISSING"
        out.append({"token": token, "bound_by": bound_by, "status": status, "values": values})
    for name, value, owner in PROPOSED:
        values = {"proposed": value}
        out.append(
            {"token": "CR:" + name, "bound_by": owner, "status": "PROPOSED", "values": values}
        )
    return out


def caps_from_ddl() -> list[dict[str, object]]:
    text = SCHEMA_DOC.read_text(encoding="utf-8")
    start = text.index("CREATE TABLE risk_policy (")
    block = text[start : text.index(");", start)]
    extra = ("lockout_minutes_default", "day_boundary_utc_offset_minutes")
    out: list[dict[str, object]] = []
    for col in words(CAP_COLUMNS) + extra:
        m = re.search(col + r" BETWEEN (-?\d+) AND (-?\d+)", block)
        if m:
            out.append({"column": col, "low": int(m.group(1)), "high": int(m.group(2))})
        elif re.search(col + r" >= 0", block):
            out.append({"column": col, "low": 0, "high": None})
    for c in out:
        if c["column"] == "lockout_minutes_default":
            c["note"] = "D-5 forbids 0 above the CHECK: the UI shows 1..1440"
    return out


def fmt(ratio: float | None) -> str:
    """Two decimals; four when the two-decimal form would land exactly on a bar."""
    if ratio is None:
        return "n/a"
    if round(ratio, 2) in BARS and round(ratio, 2) != round(ratio, 4):
        return f"{ratio:.4f}"
    return f"{ratio:.2f}"


def counts(pairs: list[PairRow], tokens: list[TokenRow], exempt: set[str]) -> dict[str, int]:
    gated = [p for p in pairs if p["role"] in GATED]
    distinct = {(p["fg"], p["bg"]) for p in gated}
    proposed = {(p["fg"], p["bg"]) for p in gated if not p["registered"]}
    bound = {t["token"] for t in tokens if t["status"] == "resolved"}
    n = dict(CONSTANTS)
    n["frames_scr072"], n["frames_scr134"] = len(STORIES["SCR-072"]), len(STORIES["SCR-134"])
    n["cmp211_buttons"], n["cmp211_modes"] = len(words(CMP211_BUTTONS)), len(words(CMP211_MODES))
    n["cmp211_states"], n["stories_cmp211"] = len(words(CMP211_STATES)), len(STORIES["CMP-211"])
    n["stories_total"], n["story_groups"] = sum(len(v) for v in STORIES.values()), len(STORIES)
    n["pairs_rows"], n["pairs_gated"], n["pairs_distinct"] = len(pairs), len(gated), len(distinct)
    n["pairs_registered"], n["pairs_proposed"] = len(distinct) - len(proposed), len(proposed)
    n["pairs_failing"] = sum(1 for p in gated if p["verdict"] != "PASS")
    n["pairs_decorative"] = sum(1 for p in pairs if p["role"] == "decorative")
    n["pairs_exempt"] = sum(1 for p in pairs if p["role"] == "exempt")
    n["pairs_rejected"] = sum(1 for p in pairs if p["role"].startswith("rejected"))
    n["tokens_bound"], n["tokens_proposed"] = len(bound), len(PROPOSED)
    n["tokens_missing"] = sum(1 for t in tokens if t["status"] == "MISSING")
    n["tokens_exempt"], n["themes"], n["caps"] = len(bound & exempt), len(THEME_ORDER), 7
    return n


def reproduce(pairs: list[PairRow]) -> list[RepRow]:
    out: list[RepRow] = []
    for label, fg, bg, theme, want in EXPECTED:
        got = next((p["ratios"][theme] for p in pairs if p["fg"] == fg and p["bg"] == bg), None)
        ok = got is not None and abs(round(got, 2) - float(want)) < 1e-9
        out.append({"label": label, "expected": float(want), "computed": got, "reproduced": ok})
    return out


def print_markdown(
    pairs: list[PairRow],
    tokens: list[TokenRow],
    nums: dict[str, int],
    caps: list[dict[str, object]],
    rep: list[RepRow],
    exempt: set[str],
) -> None:
    print("# E39-D03 token audit (packages/ui/tokens; WCAG 2.x; unrounded compare)\n")
    print("## 1. Contrast matrix\n")
    print("| Element | fg | bg | role | bar | dark | light | hc | verdict | pairs.mjs | source |")
    print("| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |")
    for p in pairs:
        bar = "-" if p["bar"] is None else f"{p['bar']:g}:1"
        reg = "registered" if p["registered"] else ("PROPOSED" if p["role"] in GATED else "-")
        r = p["ratios"]
        cells = [p["element"], f"`{p['fg']}`", f"`{p['bg']}`", p["role"], bar]
        cells += [fmt(r[t]) for t in THEME_ORDER] + [p["verdict"], reg, p["source"]]
        print("| " + " | ".join(cells) + " |")
    print("\n## 2. Token bindings\n")
    print("| Token | Bound by | Status | dark | light | hc | exemptions.json |")
    print("| --- | --- | --- | --- | --- | --- | --- |")
    for t in tokens:
        v = t["values"]
        cells = [f"`{t['token']}`", t["bound_by"], t["status"]]
        cells += [v.get(theme, v.get("proposed", "-")) for theme in THEME_ORDER]
        cells.append("exempt" if t["token"] in exempt else "-")
        print("| " + " | ".join(cells) + " |")
    print("\n## 3. The caps and their bounds (parsed from 21 section 3.11)\n")
    for c in caps:
        high = "open" if c["high"] is None else str(c["high"])
        note = f" ({c['note']})" if "note" in c else ""
        print(f"- `{c['column']}`: {c['low']} .. {high}{note}")
    print("\n## 4. Figures re-derived\n")
    for row in rep:
        state = "reproduced" if row["reproduced"] else "DIFFERS"
        got = fmt(row["computed"])
        print(f"- {row['label']}: expected {row['expected']}, computed {got} -> {state}")
    print("\n## 5. Counts the boards quote\n")
    for key, number in nums.items():
        print(f"- {key}: {number}")
    print(
        "\nFinding (16 / E05 owner, not a change here): `color.status.danger.strong` aliases "
        "`palette.amber.400` (dark) and `palette.light.amber.300` (light): an amber in a danger "
        "ramp."
    )


def main(argv: list[str]) -> int:
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")
    themes = {name: merged(files) for name, files in THEMES.items()}
    reg, exempt = registered_pairs(), exempt_tokens()
    pairs, tokens = measure(themes, reg), bindings(themes)
    nums, caps, rep = counts(pairs, tokens, exempt), caps_from_ddl(), reproduce(pairs)
    proposed = sorted(
        {(p["fg"], p["bg"]) for p in pairs if p["role"] in GATED and not p["registered"]}
    )
    failing = [p for p in pairs if p["role"] in GATED and p["verdict"] != "PASS"]
    if "--json" in argv:
        out: dict[str, object] = {"pairs": pairs, "tokens": tokens, "counts": nums, "caps": caps}
        out["reproduced"], out["proposed_pairs"] = rep, [list(p) for p in proposed]
        out["exempt_tokens_bound"] = sorted({t["token"] for t in tokens} & exempt)
        out["stories"], out["cmp211_states"] = STORIES, words(CMP211_STATES)
        out["cmp211_modes"], out["cmp211_buttons"] = words(CMP211_MODES), words(CMP211_BUTTONS)
        print(json.dumps(out, indent=2, ensure_ascii=False))
        return 1 if failing else 0
    print_markdown(pairs, tokens, nums, caps, rep, exempt)
    print("\n## 6. Verdict\n")
    if failing:
        print("FAIL: " + "; ".join(f"{p['fg']} on {p['bg']} ({p['verdict']})" for p in failing))
        return 1
    g, th, miss = nums["pairs_gated"], nums["themes"], nums["tokens_missing"]
    deco, exe, rej = nums["pairs_decorative"], nums["pairs_exempt"], nums["pairs_rejected"]
    print(
        f"OK: {g} gated rows over {th} themes pass (unrounded compare); {miss} names MISSING "
        f"(expected); {deco} decorative, {exe} exempt and {rej} rejected rows reported; "
        f"PROPOSED pairs.mjs rows: {len(proposed)}"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
