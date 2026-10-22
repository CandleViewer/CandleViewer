"""E39-D02 token audit: WCAG contrast matrix, token bindings and the board counts over the tokens.

Standalone, offline, stdlib only, run with `python3 -I`. Resolves the three themes exactly as
`packages/ui/tokens/tests/verify_tokens.py` layers them (`themes.json`: dark = primitives +
semantic-dark; light adds semantic-light; high-contrast adds semantic-hc) with the same `{alias}`
resolver, re-implemented here so the tool imports nothing from that test module. The contrast
formula is the WCAG 2.x relative-luminance ratio of `docs/design/_tools/contrast_check.py`,
re-implemented identically (sRGB linearisation at the 0.03928 threshold, 0.05 flare), so the
numbers agree with E39-D01 section 9.4, E39-D03 section 12, E40-D01 CR-23..CR-25 and E11-D02.
The loader, resolver and measure are the E39-D03 tool's shape (copied, not imported: that tool is
not on `main`), so the two tools agree digit for digit on every pair both measure.

It prints, with a source label on every row: (1) the ratio of every fg / bg pair SCR-071, SCR-073,
CMP-117 and CMP-138 bind, dark / light / high-contrast, against the role's bar (text 4.5, non-text
3.0, hc-text 7.0 only where the spec claims the 05 section 5 item 3 stretch), compared UNROUNDED (a
value that would round onto a bar is printed to four decimals - the 2.9992 lesson), PASS / FAIL;
`decorative`, `exempt` and `rejected-*` rows are reported, never gated; (2) every token the spec,
the two `15` entries and the handoff bind, resolved in every theme or MISSING, and the PROPOSED
light `color.status.warning.default` candidates as `CR:` rows measured on the primitive they would
alias, never as existing; (3) which pairs `tools/contrast/pairs.mjs` registers (text scan) and which
bound tokens `exemptions.json` exempts; (4) the counts the boards quote, the four lockout reasons
parsed from the `21` DDL and cross-checked against the `22` enum, the `RiskCaps` bounds and the
override reason bounds parsed from `22`, and the published figures re-derived here.

Usage: python3 -I docs/design/_tools/e39_d02_token_audit.py [--json]  (exit 1 only on a gated FAIL)
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
API_DOC = ROOT / "docs" / "plan" / "22-api-openapi.yaml"
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
DIM = 0.85  # E11-D06 D13: the stale figures are data-ink multiplied by 0.85 (a uniform)
# CR: candidates for the PROPOSED light `color.status.warning.default` (Q-D02-4): measured on the
# primitive they would alias in light; dark and hc keep the shipped alias (palette.amber.500).
CR: dict[str, dict[str, str]] = {
    "CR:color.status.warning.default@light.amber.300": {
        "dark": "palette.amber.500",
        "light": "palette.light.amber.300",
        "high-contrast": "palette.amber.500",
    },
    "CR:color.status.warning.default@amber.700": {
        "dark": "palette.amber.500",
        "light": "palette.amber.700",
        "high-contrast": "palette.amber.500",
    },
}

# element | fg | bg | role | source  -- one record per line; a line indented by two spaces
# continues the record above it; the roles are the BAR keys.
PAIRS_TABLE = """
KPI figures, table cells, banner titles on the page | color.text.primary | color.surface.app
  | text | E39-D01 s9.4; spec s4
KPI group labels LIVE / DEMO, secondary cells (the DEMO group) | color.text.secondary
  | color.surface.app | text | E39-D01 s9.4; spec s4 (Q-D02-2 rider)
As-of line, captions, T2 lock glyph + label on the page | color.text.tertiary | color.surface.app
  | text | E39-D01 s9.4; E09-D09 T2
Row text on the raised row; chip text (stale since, Kill switch: engaged) | color.text.primary
  | color.surface.raised | text | E39-D01 s9.4; spec s4
Row secondary text; T2 reason sentence | color.text.secondary | color.surface.raised | text
  | E39-D01 s9.4; E09-D09 T2
Row caption; T2 lock glyph + label on the raised host | color.text.tertiary | color.surface.raised
  | text | E39-D01 s9.4; E09-D09 T2
Selected row text | color.text.primary | color.surface.selected | text | E39-D01 s9.4
Selected row secondary text -- adopted | color.text.secondary | color.surface.selected | text
  | E39-D01 s9.4 (6.24)
Selected row caption -- REJECTED (the E39-D01 s9.4 ban) | color.text.tertiary
  | color.surface.selected | rejected-text | E39-D01 s9.4: 3.98 dark
Table header text on the hover surface | color.text.primary | color.surface.hover | text | spec s4
Stale figure, dimmed (data-ink x 0.85, E11-D06 D13) | dim85:color.text.primary | color.surface.app
  | text | spec s4 stale; E11-D06 D13
Stale row secondary, dimmed | dim85:color.text.secondary | color.surface.raised | text
  | spec s4 stale; E11-D06 D13
Dialog title, restatement rows | color.text.primary | color.surface.overlay | text | spec s7
Dialog helper, consequence | color.text.secondary | color.surface.overlay | text | spec s7
Dialog captions: counter n / 280, as-of | color.text.tertiary | color.surface.overlay | text
  | spec s7
Banner title / body; critical banner lead (CMP-117, CMP-028 danger) | color.text.primary
  | color.status.danger.subtle | text | E40-D01 CR-23; spec s5
Banner facts row, caption (OD-12 bracket) | color.text.secondary | color.status.danger.subtle
  | text | E40-D01 CR-24; spec s5
Banner leading rule; FROZEN glyph fill on the banner | color.status.danger.strong
  | color.status.danger.subtle | non-text | E40-D01 CR-25; spec s5
Banner rule alternative -- REJECTED (danger.default); as the LOCK glyph's interior fill it is
  reinforcement inside the text.primary stroke (2.88 dark reported) | color.status.danger.default
  | color.status.danger.subtle | rejected-non-text | spec s11: fails dark
WARN twin title; stale callout text | color.text.primary | color.status.warning.subtle | text
  | spec s5, s4 stale
WARN twin secondary | color.text.secondary | color.status.warning.subtle | text | spec s5
WARN twin rule, diamond glyph fill; stale callout glyph | color.status.warning.strong
  | color.status.warning.subtle | non-text | E39-D03 s12 row 19; spec s5
WARN rule alternative -- REJECTED (warning.default) | color.status.warning.default
  | color.status.warning.subtle | rejected-non-text | spec s11: lands on the bar in light
Cleared / expired status banner text | color.text.primary | color.status.success.subtle | text
  | spec s5 cleared, expired
Cleared / expired banner glyph | color.status.success.strong | color.status.success.subtle
  | non-text | spec s5
RECONCILING callout text (CMP-028 info) | color.text.primary | color.status.info.subtle | text
  | spec s4 reconciling
RECONCILING callout glyph | color.status.info.strong | color.status.info.subtle | non-text
  | spec s4 reconciling
Meter near-cap fill on the raised row (number + WARN glyph carry it) | color.status.warning.default
  | color.surface.raised | decorative | E39-D03 s12 row 26; Q-D02-4
Meter near-cap fill on the sunken track (PROPOSED track) | color.status.warning.default
  | color.surface.sunken | decorative | spec s6; Q-D02-4
Meter breached fill on the raised row | color.status.danger.default | color.surface.raised
  | decorative | spec s6; Q-D02-4
Meter breached fill on the sunken track | color.status.danger.default | color.surface.sunken
  | decorative | spec s6; Q-D02-4
Q-D02-4 alternative: warning.strong fill on the raised row | color.status.warning.strong
  | color.surface.raised | decorative | Q-D02-4 alternative, measured
Q-D02-4 alternative: danger.strong fill on the raised row | color.status.danger.strong
  | color.surface.raised | decorative | Q-D02-4 alternative, measured
The 80 % tick on the track (state-carrying reading aid) | color.text.secondary
  | color.surface.sunken | non-text | spec s6; E39-D01 s9.4 (strokes in text tokens)
The 80 % tick alternative -- REJECTED (border.strong) | color.border.strong
  | color.surface.sunken | rejected-non-text | spec s11: fails
Meter track on the row (structure) | color.surface.sunken | color.surface.raised | decorative
  | spec s6
Meter track outline (structure) | color.border.strong | color.surface.raised | decorative
  | E39-D03 s12 row 41
Hatched unknown track strokes | color.text.tertiary | color.surface.sunken | non-text
  | spec s6 unknown; E25-D01 s9.5 pattern rule (C-row)
Over-cap overflow marker | color.status.danger.strong | color.surface.sunken | non-text | spec s6
Stale-since chip glyph (CMP-239 stale indicator) | color.data-confidence.stale.indicator
  | color.surface.raised | non-text | E42-D02 D4; spec s4 stale
LIVE badge border on the page | color.env.live | color.surface.app | non-text | 14 s0.5 item 1
DEMO badge border on the page | color.env.demo | color.surface.app | non-text | 14 s0.5 item 1
LIVE badge border on the raised row (CMP-075) | color.env.live | color.surface.raised | non-text
  | E39-D03 s12 row 29
DEMO badge border on the raised row (CMP-075) | color.env.demo | color.surface.raised | non-text
  | E39-D03 s12 row 30
LIVE / DEMO badge text (05 s5 item 3 stretch) | color.text.primary | color.surface.raised
  | hc-text | E39-D03 s12 row 31
LIVE as coloured text -- REJECTED | color.env.live | color.surface.app | rejected-hc-text
  | E39-D03 s12 row 32
Override Confirm label (CMP-001 danger) | color.text.on-action | color.status.danger.default
  | text | E39-D01 s9.4; E39-D03 s12 row 1
Primary button label (Release...) | color.text.on-action | color.action.primary.default | text
  | spec s4, s5
Danger button fill on the page (FREEZE... -- CMP-211 global; the override Confirm)
  | color.status.danger.default | color.surface.app | non-text | E39-D03 s12 row 20
Refused-field border on the dialog; the outline buttons' danger stroke (Freeze..., I've read
  this, Ask the owner for an override) on their overlay fill | color.status.danger.default
  | color.surface.overlay | non-text | E39-D03 s12 row 21
Focus ring on the page | color.focus.ring | color.surface.app | non-text | 05 s3.4 item 6
Focus ring on the raised row / banner host | color.focus.ring | color.surface.raised | non-text
  | 05 s3.4 item 6
Focus ring on the banner (danger.subtle) | color.focus.ring | color.status.danger.subtle
  | non-text | spec s5
Focus ring on the dialog | color.focus.ring | color.surface.overlay | non-text | spec s7
Focus ring against the danger fill inside the 2 px offset -- REJECTED | color.focus.ring
  | color.status.danger.default | rejected-non-text | E39-D03 s12 row 37: hence the offset
Hairline on the raised row (structure) | color.border.default | color.surface.raised
  | decorative | E39-D03 s12 row 40
Disabled text -- EXEMPT (page) | color.text.disabled | color.surface.app | exempt | WCAG 1.4.3
Disabled text -- EXEMPT (raised); never used by T2 | color.text.disabled | color.surface.raised
  | exempt | WCAG 1.4.3; E09-D09 T2
Disabled text -- EXEMPT (banner) | color.text.disabled | color.status.danger.subtle | exempt
  | WCAG 1.4.3
CR: light warning.default = palette.light.amber.300, on the raised row
  | CR:color.status.warning.default@light.amber.300 | color.surface.raised | non-text
  | Q-D02-4 DS request (E05-D02 lane)
CR: light warning.default = palette.amber.700, on the raised row
  | CR:color.status.warning.default@amber.700 | color.surface.raised | non-text
  | Q-D02-4 DS request (E05-D02 lane)
"""

# token | bound by
BINDINGS_TABLE = """
color.status.danger.subtle | CMP-117 LOCK / FROZEN surface, CMP-028 critical banner
color.status.danger.default | LOCK fill (table + banner glyph), FREEZE... / Confirm, refused field
color.status.danger.strong | banner rule, FROZEN glyph (E40 CR-25), over-cap marker, shield slash
color.status.warning.subtle | CMP-117 WARN twin, stale callout
color.status.warning.default | CMP-138 near-cap fill (reinforcement, Q-D02-4)
color.status.warning.strong | WARN rule and diamond glyph
color.status.success.subtle | cleared / expired status banner
color.status.success.strong | cleared / expired glyph
color.status.info.subtle | RECONCILING callout (CMP-028 info)
color.status.info.strong | RECONCILING callout glyph
color.env.demo | CMP-075 badge border
color.env.live | CMP-075 badge border
color.text.primary | every title, figure, state word; glyph strokes
color.text.secondary | KPI labels, DEMO group (Q-D02-2 rider), T2 reason, the 80 % tick
color.text.tertiary | as-of captions, T2 label, hatched unknown strokes
color.text.disabled | reported only; never on T2 (E09-D09)
color.text.on-action | danger / primary button labels
color.surface.app | SCR-071 page, shell
color.surface.raised | table rows, chips, banner host, T2 host
color.surface.overlay | the override dialog card
color.surface.canvas | the shell content area behind the dialog scrim
color.surface.hover | table header
color.surface.selected | the selected (drilled) row
color.surface.sunken | CMP-138 track (PROPOSED; color.track is MISSING)
color.border.subtle | row separators
color.border.default | hairlines
color.border.strong | track outline (decorative); the rejected tick alternative
color.focus.ring | the 2 px ring
color.action.primary.default | Release... (Freeze my account... and I've read this are outline)
color.action.selected | checked box / radio fill in the dialog
color.data-confidence.stale.indicator | the CMP-239 stale since chip glyph
space.2 | control row and table gaps
space.inset.xs | pill x inset
space.inset.sm | compact row inset
space.inset.md | comfortable row inset, banner inner inset
space.inset.lg | page padding
space.inset.xl | dialog outer inset
size.control.height | compact 24 px controls
size.control.comfortable | comfortable 32 px controls
size.target.min | 24 px floor
radius.control | buttons, fields
radius.card | banner, KPI tiles, callouts
radius.dialog | the override dialog card
radius.badge | CMP-075 badge
radius.pill | chips, the meter track
border.focus | ring width
opacity.scrim | the dialog scrim (black in every theme, E09-D08 D2)
opacity.disabled | never on a T2 label (reported)
opacity.muted | de-emphasised captions
elevation.dialog | the override dialog
elevation.scrim | the scrim layer
motion.duration.instant | state flips, the banner cut, the countdown tick
motion.duration.fast | the meter fill move (PROPOSED)
motion.duration.normal | the stale dim (E11-D06 D13), the SCR-006 chassis scrim
type.ui.caption | as-of, captions, footer
type.ui.body | banner body
type.ui.body-strong | banner title, state word
type.ui.label | KPI labels, option labels
type.ui.heading-sm | dialog title
type.ui.heading-md | the page h1
type.num.sm | table counts, chip figures
type.num.base | KPI figures, meter numeric text, countdown
type.num.md | the KPI equity figure
color.track | CMP-023 track (MISSING; color.surface.sunken PROPOSED)
color.text.warning | CMP-035 under-threshold text (MISSING; warning.strong on warning.subtle used)
color.callout.danger | CMP-028 (MISSING; danger.subtle + danger.strong used)
font.mono | CMP-035, CMP-116, CMP-049 (MISSING; type.num.* carries the mono family, E39-D03 G8)
color.surface.scrim | E09-D08 A-2 PROPOSED (MISSING here; cited, not re-proposed; E39-D03 G9)
color.action.danger | CMP-001 danger variant (MISSING; status.danger.default used; E39-D03 G14)
"""

# name | value | owner  (the Q-D02-4 DS change request; a value change, no new token name)
PROPOSED_TABLE = """
color.status.warning.default (light) | a light value >= 3:1 on color.surface.raised
  | E05-D02 lane (Q-D02-4; candidates measured as CR: rows)
"""

# group | comma-separated story names (one record per group; names only, E39-S04 implements)
STORIES_TABLE = """
CMP-117 | AccountScope, ManagerScope, GlobalScope, TimeBoxed, OpenEnded, OwnerOverrideAvailable,
  OverrideRequestable, OverrideRequested, Acknowledged, Cleared, ClearedWithAllowance, Expired,
  ExpiredInDay, Frozen, CapRefusal, Compact, Comfortable, ReducedMotion
CMP-138 | Ok, NearCap, Breached, Stale, Unknown, OverCapAfterTightening, AccountScope,
  PortfolioScope, Compact, Comfortable, ReducedMotion
SCR-071 | Normal, Warning, Locked, Frozen, Stale, Reconciling, Manager, Viewer, CriticalNativeStop
SCR-073 | ActiveDailyLoss, ConsecutiveLosses, MaxPositions, Manual, Acknowledged,
  OverrideRequested, Expired, FrozenByOwner, OwnerOverride, OverrideResult
"""
CMP117_VARIANTS = (
    "scope: account, manager, global | kind: locked, frozen | clock: time-boxed, open-ended"
    " | override: available, requestable, requested, acknowledged"
)
CMP117_STATES = "appearing, persistent, acknowledged, requested, cleared, expired, frozen"
CMP138_VARIANTS = "ok, near-cap, breached, unknown-stale, over-cap-after-tightening"
CMP138_STATES = "live, stale, unknown"
STATE_GLYPHS = "ok, WARN, LOCK, FROZEN, STALE, RECONCILING"
KPI_FIELDS = (
    "equity_usd, unrealised_pnl_usd, realised_pnl_today_usd, open_positions, gross_notional_usd"
)

# label | fg | bg | theme | expected  -- figures published elsewhere, re-derived here
EXPECTED_TABLE = """
E39-D01 s9.4 primary on app, dark | color.text.primary | color.surface.app | dark | 16.06
E39-D01 s9.4 secondary on app, dark | color.text.secondary | color.surface.app | dark | 9.85
E39-D01 s9.4 tertiary on app, dark | color.text.tertiary | color.surface.app | dark | 6.29
E39-D01 s9.4 primary on raised, dark | color.text.primary | color.surface.raised | dark | 14.35
E39-D01 s9.4 secondary on raised, dark | color.text.secondary | color.surface.raised | dark | 8.81
E39-D01 s9.4 tertiary on raised, dark | color.text.tertiary | color.surface.raised | dark | 5.62
E39-D01 s9.4 primary on selected, dark | color.text.primary | color.surface.selected | dark | 10.17
E39-D01 s9.4 secondary on selected, dark | color.text.secondary | color.surface.selected | dark
  | 6.24
E39-D01 s9.4 tertiary on selected, dark (the ban) | color.text.tertiary | color.surface.selected
  | dark | 3.98
E39-D01 s9.4 primary on app, hc | color.text.primary | color.surface.app | high-contrast | 18.18
E39-D01 s9.4 tertiary on selected, hc | color.text.tertiary | color.surface.selected
  | high-contrast | 7.94
E39-D01 s9.4 on-action on danger, dark | color.text.on-action | color.status.danger.default
  | dark | 5.05
E39-D01 s9.4 on-action on danger, hc | color.text.on-action | color.status.danger.default
  | high-contrast | 4.54
E39-D03 s12 row 19 warning.strong on warning.subtle, dark | color.status.warning.strong
  | color.status.warning.subtle | dark | 7.56
E39-D03 s12 row 19 warning.strong on warning.subtle, light | color.status.warning.strong
  | color.status.warning.subtle | light | 4.11
E39-D03 s12 row 26 meter fill on raised, dark | color.status.warning.default
  | color.surface.raised | dark | 7.98
E39-D03 s12 row 26 meter fill on raised, light (four decimals) | color.status.warning.default
  | color.surface.raised | light | 2.9992
E39-D03 s12 row 27 LIVE on app, dark | color.env.live | color.surface.app | dark | 4.94
E39-D03 s12 row 27 LIVE on app, light | color.env.live | color.surface.app | light | 5.20
E39-D03 s12 row 28 DEMO on app, dark | color.env.demo | color.surface.app | dark | 4.07
E39-D03 s12 row 28 DEMO on app, light | color.env.demo | color.surface.app | light | 4.76
E39-D03 s12 row 29 LIVE on raised, dark | color.env.live | color.surface.raised | dark | 4.42
E39-D03 s12 row 29 LIVE on raised, light | color.env.live | color.surface.raised | light | 4.51
E39-D03 s12 row 30 DEMO on raised, dark | color.env.demo | color.surface.raised | dark | 3.64
E39-D03 s12 row 30 DEMO on raised, light | color.env.demo | color.surface.raised | light | 4.13
E39-D03 s12 row 31 badge text on raised, light | color.text.primary | color.surface.raised
  | light | 15.62
E39-D03 s12 row 31 badge text on raised, hc | color.text.primary | color.surface.raised
  | high-contrast | 16.25
E40-D01 CR-23 dark | color.text.primary | color.status.danger.subtle | dark | 12.06
E40-D01 CR-23 light | color.text.primary | color.status.danger.subtle | light | 14.64
E40-D01 CR-23 hc | color.text.primary | color.status.danger.subtle | high-contrast | 13.66
E40-D01 CR-24 dark | color.text.secondary | color.status.danger.subtle | dark | 7.40
E40-D01 CR-24 light | color.text.secondary | color.status.danger.subtle | light | 8.42
E40-D01 CR-25 dark | color.status.danger.strong | color.status.danger.subtle | dark | 7.83
E40-D01 CR-25 light | color.status.danger.strong | color.status.danger.subtle | light | 3.85
E40-D01 CR-25 hc | color.status.danger.strong | color.status.danger.subtle | high-contrast | 7.83
"""

# key | value  -- the anatomy constants the boards quote (the computed counts are added in code)
CONSTANTS_TABLE = """
boards | 13
handoff_blocks | 2
handoff_lines | 13
tick_pct | 80
row_compact_px | 24
row_comfortable_px | 32
track_compact_px | 8
track_comfortable_px | 12
banner_min_px | 40
banner_rule_px | 4
dialog_width_px | 560
hit_target_px | 24
reason_drawn_min | 10
shared_meter_current | 212
shared_meter_cap | 250
shared_meter_pct | 85
warning_frame_pct | 95
lock_frame_pct | 105
over_cap_pct | 112
stale_age_s | 14
push_within_ms | 500
refresh_hz | 1
countdown_threshold_s_1 | 60
countdown_threshold_s_2 | 10
countdown_threshold_s_3 | 0
dim_pct | 85
risk_caps_grace_min | 5
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


def hex_of(name: str, tokens: Tokens, theme: str = "dark") -> str | None:
    """A token's hex in one theme; `dim85:` multiplies the data-ink by 0.85 (E11-D06 D13); a `CR:`
    candidate is measured on the primitive it would alias in that theme (never an invented hex)."""
    if name.startswith("dim85:"):
        base = hex_of(name[6:], tokens, theme)
        if base is None:
            return None
        r, g, b = (round(int(base[i : i + 2], 16) * DIM) for i in (1, 3, 5))
        return f"#{r:02X}{g:02X}{b:02X}"
    if name.startswith("CR:"):
        return hex_of(CR[name][theme], tokens, theme)
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
            a, b = hex_of(fg, themes[theme], theme), hex_of(bg, themes[theme], theme)
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
        if fg.startswith("CR:"):
            verdict = "CR: " + verdict + " (candidate; not a shipped token)"
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


def lockout_reasons() -> dict[str, object]:
    """The four reasons parsed from the `21` DDL CHECK and the `22` enum, cross-checked."""
    ddl = SCHEMA_DOC.read_text(encoding="utf-8")
    m = re.search(r"rl_reason\s+CHECK \(reason IN \(([^)]*)\)\)", ddl)
    from_ddl = tuple(re.findall(r"'([a-z_]+)'", m.group(1))) if m else ()
    api = API_DOC.read_text(encoding="utf-8")
    start = api.index("    RiskSummary:\n")
    block = api[start : api.index("\n    DetectorConfig:", start)]
    e = re.search(r"reason:\s*\{ type: string, enum: \[([^\]]*)\] \}", block)
    from_api = tuple(x.strip() for x in e.group(1).split(",")) if e else ()
    text_m = re.search(r"char_length\(release_reason\) <= (\d+)[\s\S]*?>= (\d+)\)", ddl)
    return {
        "from_ddl": from_ddl,
        "from_api": from_api,
        "agree": from_ddl == from_api and len(from_ddl) == 4,
        "release_reason_min": int(text_m.group(2)) if text_m else None,
        "release_reason_max": int(text_m.group(1)) if text_m else None,
    }


def risk_caps_bounds() -> list[dict[str, object]]:
    """`RiskCaps` integer bounds and the override `reason` bounds, parsed from `22`."""
    api = API_DOC.read_text(encoding="utf-8")
    start = api.index("    RiskCaps:\n")
    block = api[start : api.index("\n    ProfileSizingMode:", start)]
    out: list[dict[str, object]] = []
    pat = r"(\w+): \{ type: integer, minimum: (\d+), maximum: (\d+)(?:, default: (\d+))? \}"
    for name, low, high, default in re.findall(pat, block):
        row: dict[str, object] = {"field": name, "low": int(low), "high": int(high)}
        if default:
            row["default"] = int(default)
        out.append(row)
    ov = api.index("  /risk/lockouts/{accountId}/override:")
    r = re.search(r"reason: \{ type: string, minLength: (\d+), maxLength: (\d+) \}", api[ov:])
    if r:
        out.append({"field": "override.reason", "low": int(r.group(1)), "high": int(r.group(2))})
    return out


def fmt(ratio: float | None) -> str:
    """Two decimals; four when the two-decimal form would land exactly on a bar."""
    if ratio is None:
        return "n/a"
    if round(ratio, 2) in BARS and round(ratio, 2) != round(ratio, 4):
        return f"{ratio:.4f}"
    return f"{ratio:.2f}"


def counts(
    pairs: list[PairRow], tokens: list[TokenRow], exempt: set[str], caps: list[dict[str, object]]
) -> dict[str, int]:
    real = [p for p in pairs if not p["fg"].startswith("CR:")]
    gated = [p for p in real if p["role"] in GATED]
    distinct = {(p["fg"], p["bg"]) for p in gated}
    proposed = {(p["fg"], p["bg"]) for p in gated if not p["registered"]}
    bound = {t["token"] for t in tokens if t["status"] == "resolved"}
    n = dict(CONSTANTS)
    n["frames_scr071"], n["frames_scr073"] = len(STORIES["SCR-071"]), len(STORIES["SCR-073"])
    n["stories_cmp117"], n["stories_cmp138"] = len(STORIES["CMP-117"]), len(STORIES["CMP-138"])
    n["stories_total"], n["story_groups"] = sum(len(v) for v in STORIES.values()), len(STORIES)
    n["cmp117_states"], n["cmp138_states"] = len(words(CMP117_STATES)), len(words(CMP138_STATES))
    n["cmp138_variants"], n["state_glyphs"] = len(words(CMP138_VARIANTS)), len(words(STATE_GLYPHS))
    n["cmp117_variant_axes"] = len(CMP117_VARIANTS.split(" | "))
    n["kpi_fields"] = len(words(KPI_FIELDS))
    n["pairs_rows"], n["pairs_gated"], n["pairs_distinct"] = len(real), len(gated), len(distinct)
    n["pairs_registered"], n["pairs_proposed"] = len(distinct) - len(proposed), len(proposed)
    n["pairs_failing"] = sum(1 for p in gated if p["verdict"] != "PASS")
    n["pairs_decorative"] = sum(1 for p in real if p["role"] == "decorative")
    n["pairs_exempt"] = sum(1 for p in real if p["role"] == "exempt")
    n["pairs_rejected"] = sum(1 for p in real if p["role"].startswith("rejected"))
    n["pairs_cr"] = len(pairs) - len(real)
    n["tokens_bound"], n["tokens_proposed"] = len(bound), len(PROPOSED)
    n["tokens_missing"] = sum(1 for t in tokens if t["status"] == "MISSING")
    n["tokens_exempt"], n["themes"] = len(bound & exempt), len(THEME_ORDER)
    n["risk_caps_bounds"] = sum(1 for c in caps if c["field"] != "override.reason")
    return n


def reproduce(pairs: list[PairRow]) -> list[RepRow]:
    out: list[RepRow] = []
    for label, fg, bg, theme, want in EXPECTED:
        got = next((p["ratios"][theme] for p in pairs if p["fg"] == fg and p["bg"] == bg), None)
        nd = len(want.split(".")[1]) if "." in want else 0
        ok = got is not None and abs(round(got, nd) - float(want)) < 1e-9
        out.append({"label": label, "expected": float(want), "computed": got, "reproduced": ok})
    return out


def print_markdown(
    pairs: list[PairRow],
    tokens: list[TokenRow],
    nums: dict[str, int],
    caps: list[dict[str, object]],
    reasons: dict[str, object],
    rep: list[RepRow],
    exempt: set[str],
) -> None:
    print("# E39-D02 token audit (packages/ui/tokens; WCAG 2.x; unrounded compare)\n")
    print("## 1. Contrast matrix\n")
    print("| Element | fg | bg | role | bar | dark | light | hc | verdict | pairs.mjs | source |")
    print("| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |")
    for p in pairs:
        bar = "-" if p["bar"] is None else f"{p['bar']:g}:1"
        reg = "registered" if p["registered"] else ("PROPOSED" if p["role"] in GATED else "-")
        if p["fg"].startswith("CR:"):
            reg = "-"
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
    print("\n## 3. Lockout reasons (21 section 3.11 rl_reason vs 22 RiskSummary enum)\n")
    print(f"- from the DDL: {', '.join(cast(tuple[str, ...], reasons['from_ddl']))}")
    print(f"- from the API: {', '.join(cast(tuple[str, ...], reasons['from_api']))}")
    agree = "agree (4 reasons)" if reasons["agree"] else "DISAGREE"
    rr = f"{reasons['release_reason_min']}..{reasons['release_reason_max']}"
    print(f"- {agree}; `release_reason` {rr} characters (rl_text)")
    print("\n## 4. RiskCaps bounds and the override reason (parsed from 22)\n")
    for c in caps:
        default = f", default {c['default']}" if "default" in c else ""
        print(f"- `{c['field']}`: {c['low']} .. {c['high']}{default}")
    print("\n## 5. Figures re-derived\n")
    for row in rep:
        state = "reproduced" if row["reproduced"] else "DIFFERS"
        got = fmt(row["computed"])
        print(f"- {row['label']}: expected {row['expected']}, computed {got} -> {state}")
    print("\n## 6. Counts the boards quote\n")
    for key, number in nums.items():
        print(f"- {key}: {number}")
    print(
        "\nFinding (16 / E05 owner; E39-D03 s12 found it, cited not re-proposed): "
        "`color.status.danger.strong` aliases `palette.amber.400` (dark) and "
        "`palette.light.amber.300` (light): an amber in a danger ramp.\n"
        "CVD: no colour here carries meaning alone - glyph + word + number first (E39-D01 D8); the "
        "status fills are reinforcement, the DEMO / LIVE badge is text; the simulation "
        "(`cvd_sim.py`) runs on the exports after drawing."
    )


def main(argv: list[str]) -> int:
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")
    themes = {name: merged(files) for name, files in THEMES.items()}
    reg, exempt = registered_pairs(), exempt_tokens()
    pairs, tokens = measure(themes, reg), bindings(themes)
    caps, reasons = risk_caps_bounds(), lockout_reasons()
    nums, rep = counts(pairs, tokens, exempt, caps), reproduce(pairs)
    proposed = sorted(
        {
            (p["fg"], p["bg"])
            for p in pairs
            if p["role"] in GATED and not p["registered"] and not p["fg"].startswith("CR:")
        }
    )
    failing = [
        p
        for p in pairs
        if p["role"] in GATED and p["verdict"] != "PASS" and not p["fg"].startswith("CR:")
    ]
    if "--json" in argv:
        out: dict[str, object] = {"pairs": pairs, "tokens": tokens, "counts": nums, "caps": caps}
        out["lockout_reasons"], out["reproduced"] = reasons, rep
        out["proposed_pairs"] = [list(p) for p in proposed]
        out["exempt_tokens_bound"] = sorted({t["token"] for t in tokens} & exempt)
        out["stories"], out["state_glyphs"] = STORIES, words(STATE_GLYPHS)
        out["cmp117_variants"], out["cmp117_states"] = CMP117_VARIANTS, words(CMP117_STATES)
        out["cmp138_variants"], out["cmp138_states"] = words(CMP138_VARIANTS), words(CMP138_STATES)
        out["kpi_fields"] = words(KPI_FIELDS)
        print(json.dumps(out, indent=2, ensure_ascii=False))
        return 1 if failing else 0
    print_markdown(pairs, tokens, nums, caps, reasons, rep, exempt)
    print("\n## 7. Verdict\n")
    if failing:
        print("FAIL: " + "; ".join(f"{p['fg']} on {p['bg']} ({p['verdict']})" for p in failing))
        return 1
    g, th, miss = nums["pairs_gated"], nums["themes"], nums["tokens_missing"]
    deco, exe, rej = nums["pairs_decorative"], nums["pairs_exempt"], nums["pairs_rejected"]
    print(
        f"OK: {g} gated rows over {th} themes pass (unrounded compare); {miss} names MISSING "
        f"(expected); {deco} decorative, {exe} exempt and {rej} rejected rows reported; "
        f"PROPOSED pairs.mjs rows: {len(proposed)}; CR candidates: {nums['pairs_cr']}"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
