#!/usr/bin/env python3
"""E17-D02 token audit: the connection-state chrome's contrast matrix, bindings and counts.

Standalone, offline, stdlib only. Reads `packages/ui/tokens/primitives.tokens.json` and the three
semantic files, resolves `{alias}` references per theme with the layering `themes.json` declares
(dark = primitives + semantic-dark; light and high-contrast layer their file over dark), the way
`packages/ui/tokens/tests/verify_tokens.py` does (same loader shape, same WCAG 2.x luminance;
nothing is imported from it), and prints, with a source label on every row:

1. the WCAG 2.x contrast ratio of every foreground / background pair the four components of
   `docs/design/E17/E17-D02.md` (CMP-076, CMP-077, CMP-078, CMP-092) and the three SCR-152
   variants render, in dark / light / high-contrast, against the role's bar (text 4.5:1,
   non-text 3:1, hc-text 7:1 in the high-contrast theme only; `05-accessibility-standard.md`
   section 5) with PASS or FAIL. The UNROUNDED ratio is compared, as the CI gate does
   (`tools/contrast/generate.mjs`: `ratio >= threshold`); the display rounds to the hundredth
   and a value that would round onto a bar is printed to four decimals (the #4056 2.9992 lesson).
   `rejected-*` rows are pairs the spec considered and designed around (among them the
   `color.text.disabled` label E09-D09 T2 forbids on a disabled-with-reason control; the label
   binds `color.text.tertiary` with the lock glyph, the reason `color.text.secondary`);
   `decorative` rows carry no meaning: reported, never gated. A `mix(a,b,p)`
   background is the composite the spec draws (p of b over a: the 15 % stale dim, the 0.6 scrim);
   a composite cannot be a `pairs.mjs` row and is counted apart. The six E08-D03 section 6 pairs
   are reproduced from the token JSON (that tool held Penpot-read RGB values).
2. every token name the four `15-component-catalogue.md` entries, the ticket and the spec bind,
   resolved in all three themes or MISSING (`color.overlay.stale`, `color.surface.scrim`,
   `color.status.warning`, `color.callout.*`, `color.text.warning`, `font.mono` and the A7
   `color.data-confidence.delayed.*` group are expected MISSING: catalogue drift or an open
   change request); `elevation.5` is reported as a primitive with its semantic alias.
3. which pairs are present in `tools/contrast/pairs.mjs` (a text scan of its `fg` / `bg`
   literals) and which are PROPOSED additions for E17-T04, plus which of this spec's surfaces
   the existing `tools/contrast/encodings.json` `connection-health` row already lists and which
   it lacks (the spec extends that row, CR-7; it never asks for a parallel `connection` key).
4. the counts the Penpot boards quote (components, matrix rows and no-treatment cells, chip
   values, stories, pairs, close codes, bye reasons, announcement and motion rows, the anatomy px).

Usage: python3 -I docs/design/_tools/e17_d02_token_audit.py         (Markdown; exit 1 on a FAIL)
       python3 -I docs/design/_tools/e17_d02_token_audit.py --json  (the boards' numbers)
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
ENCODINGS = ROOT / "tools" / "contrast" / "encodings.json"
PRIM, DARK, LIGHT, HC = (
    "primitives.tokens.json",
    "semantic-dark.tokens.json",
    "semantic-light.tokens.json",
    "semantic-hc.tokens.json",
)
THEMES: dict[str, tuple[str, ...]] = {
    "dark": (PRIM, DARK),
    "light": (PRIM, DARK, LIGHT),
    "high-contrast": (PRIM, DARK, HC),
}
THEME_ORDER = ("dark", "light", "high-contrast")
NON_TEXT_BAR = 3.0
BAR: dict[str, float | None] = {
    "text": 4.5,
    "non-text": NON_TEXT_BAR,
    "hc-text": 7.0,
    "decorative": None,
    "rejected-text": 4.5,
    "rejected-non-text": NON_TEXT_BAR,
}
BARS = (NON_TEXT_BAR, 4.5, 7.0)
GATED = ("text", "non-text", "hc-text")
HEX6 = re.compile(r"^#[0-9A-Fa-f]{6}$")
MIX = re.compile(r"^mix\(([^,()]+),([^,()]+),(0?\.\d+|1|0)\)$")
DIM = "mix(color.surface.canvas,color.data-confidence.stale.surface,0.15)"
DIM_RAISED = "mix(color.surface.raised,color.data-confidence.stale.surface,0.15)"
SCRIM = "mix(color.surface.canvas,color.surface.overlay,0.6)"

# element | fg | bg | role | source  -- every pair the four components and the three variants draw.
PAIRS_TABLE = """
banner title (danger); CMP-092 blocking message; SCR-001 alert sentence | color.text.primary |
  color.status.danger.subtle | text | E08-D03 s2 title; spec s6, s8, s4
banner body lines; the countdown; SCR-001 retry sentence | color.text.secondary |
  color.status.danger.subtle | text | E08-D03 s2 body; spec s6
banner glyph and 4 px left border (danger); Offline chip glyph | color.status.danger.strong |
  color.status.danger.subtle | non-text | E08-D03 s2 icon-alert; spec s5
Retry now pill fill on the danger fill | color.action.primary.default | color.status.danger.subtle
  | non-text | E08-D03 s6 (filled pill, 3:1)
Retry now label on the pill | color.text.on-action | color.action.primary.default | text | E08-D03
  s6
Details link (danger) | color.text.link | color.status.danger.subtle | text | E08-D03 s2 btn-details
focus ring on the danger fill (Retry now, Details) | color.focus.ring | color.status.danger.subtle
  | non-text | 05 s3.4 item 6; spec s13
Read-only banner title; CMP-092 warning message; T2 strong chip word; CMP-078 strip |
  color.text.primary | color.status.warning.subtle | text | E17-D01 s5 Read-only, T2; spec s7
Read-only body; CMP-092 stillWorks line; dismiss control | color.text.secondary |
  color.status.warning.subtle | text | spec s6, s8
warning glyph and left border; T2 chip glyph; strip glyph | color.status.warning.strong |
  color.status.warning.subtle | non-text | spec s5, s7, s8
Details link (warning) | color.text.link | color.status.warning.subtle | text | spec s6
focus ring on the warning fill | color.focus.ring | color.status.warning.subtle | non-text | spec
  s13
rejected: the .default glyph on the warning fill | color.status.warning.default |
  color.status.warning.subtle | rejected-non-text | spec s14 (why the glyph is .strong)
recovered title; Book rebuilt tag word | color.text.primary | color.status.success.subtle | text |
  E08-D03 s3 recovered; E17-D01 D15
recovered body (while you were offline) | color.text.secondary | color.status.success.subtle |
  text | E08-D03 s3
recovered glyph and border; Book rebuilt glyph | color.status.success.strong |
  color.status.success.subtle | non-text | E08-D03 s3
Delayed chip word; 1 s refresh tag; CMP-092 info message | color.text.primary |
  color.status.info.subtle | text | E17-D01 s5 Delayed (pending A7)
CMP-092 info stillWorks line | color.text.secondary | color.status.info.subtle | text | spec s8
Delayed chip glyph; 1 s refresh tag glyph; CMP-092 info glyph | color.status.info.default |
  color.status.info.subtle | non-text | E25-D05 s12.1 (identical pair)
long-outage title, body, outlined Retry now, underlined Details | color.text.inverse |
  color.status.danger.strong | text | E08-D03 s3 long-outage; spec s6
rejected: the filled Retry pill on the strong fill | color.action.primary.default |
  color.status.danger.strong | rejected-non-text | spec s6 (long-outage design-around)
rejected: the Details link on the strong fill | color.text.link | color.status.danger.strong |
  rejected-text | spec s6 (long-outage design-around)
chip word, age and latency (every state); popover title | color.text.primary |
  color.surface.raised | text | CMP-072 TopBar surface; spec s5
chip Stale glyph on the bar | color.data-confidence.stale.indicator | color.surface.raised |
  non-text | E08-D04 tokens; spec s5
rejected: the connection-reconnecting indicator as the chip glyph |
  color.data-confidence.reconnecting.indicator | color.surface.raised | rejected-non-text | spec
  s5 (chip uses danger.strong on danger.subtle)
StatusBar ws dot (CMP-208) disconnected | color.data-confidence.disconnected.indicator |
  color.surface.sunken | non-text | spec s5 (StatusBar duplicate, Q3; 15 CMP-208 binds
  surface.sunken)
chip hover and tooltip-open fill | color.text.primary | color.surface.hover | text | spec s5
focus ring on the bar (chip) | color.focus.ring | color.surface.raised | non-text | 05 s3.4 item 6
popover body (connection quality numbers) | color.text.secondary | color.surface.overlay | text |
  E17-D01 s4 lagging tooltip
rejected: the connection-disconnected accent on the banner fill (CMP-028 token line) |
  color.data-confidence.disconnected.indicator | color.status.danger.subtle | rejected-non-text |
  15 CMP-028 tokens vs E08-D03 s2
rejected: the connection-reconnecting accent on the banner fill (CMP-028 token line) |
  color.data-confidence.reconnecting.indicator | color.status.danger.subtle | rejected-non-text |
  15 CMP-028 tokens vs E08-D03 s2
Last update 7 s ago / Stale 7s word over the 15 % dim | color.text.primary | {DIM} | text |
  E08-D11 D11 / D17 recipe (composite)
stale chip indicator over the dim | color.data-confidence.stale.indicator | {DIM} | non-text |
  E08-D11 D13 (composite)
Mark 8s old on the dimmed grid | color.text.secondary | {DIM_RAISED} | text | E17-D01 s5 (composite)
Disconnected / Resyncing scrim label | color.text.primary | {SCRIM} | text | E08-D03 s5; E08-D11
  M8, M11 (composite)
resyncing indicator on the scrim | color.data-confidence.resyncing.indicator | {SCRIM} | non-text
  | E08-D04 tokens (composite)
revoked placeholder No longer shown | color.text.secondary | color.surface.canvas | text | E17-D01
  s5 revoked
Not connected - order not sent (inline refusal) | color.text.primary | color.surface.canvas | text
  | SCR-050 Validation; E17-D01 D13
refusal glyph on the ladder | color.status.danger.strong | color.surface.canvas | non-text | spec
  s4 in-panel
Positions as of 00:12 ago note on the grid; the CMP-079 reason sentence (E09-D09 T2) |
  color.text.secondary | color.surface.raised | text | E17-D01 s5 Disconnected; E09-D09 T2
CMP-210 chip glyph beside an issue (warn) | color.status.warning.strong | color.surface.raised |
  non-text | spec s8
CMP-210 chip glyph beside an issue (error) | color.status.danger.strong | color.surface.raised |
  non-text | spec s8
disabled-with-reason control label with the lock glyph (CMP-079; E09-D09 T2) | color.text.tertiary
  | color.surface.raised | text | E09-D09 T2, s2.4 (the submit while Disconnected); 14 s0.5.5
rejected: color.text.disabled on the disabled label (E09-D09 T2, DS-1) | color.text.disabled |
  color.surface.raised | rejected-text | E09-D09 s11 (rejected by design; never bound here)
E08-D03 s6 pair 6: workspace note (annotation only) | color.text.tertiary | color.surface.app |
  text | E08-D03 s6
""".replace("{DIM_RAISED}", DIM_RAISED).replace("{DIM}", DIM).replace("{SCRIM}", SCRIM)

# token | bound by  -- every name the four 15 entries, the ticket and the spec bind.
BINDINGS_TABLE = """
color.status.danger.subtle | CMP-077, CMP-076 offline, CMP-092 blocking
color.status.danger.strong | CMP-077 glyph/border, long-outage fill, CMP-210 error
color.status.warning.subtle | CMP-077 read-only, CMP-076 T2, CMP-078 strip, CMP-092 warning
color.status.warning.strong | CMP-077, CMP-076 T2, CMP-078, CMP-092, CMP-210 warn
color.status.warning.default | 15 CMP-092 (bare color.status.warning resolves to the triad)
color.status.success.subtle | CMP-077 recovered, Book rebuilt tag
color.status.success.strong | CMP-077 recovered glyph
color.status.info.subtle | CMP-076 delayed (pending A7), 1 s refresh tag, CMP-092 info
color.status.info.default | CMP-076 delayed glyph (pending A7), CMP-092 info glyph
color.status.info.strong | CMP-092 info (reported only)
color.text.primary | words on every surface (the cross-spec agreement)
color.text.secondary | body lines, ages, stillWorks
color.text.tertiary | CMP-079 disabled label + lock glyph (E09-D09 T2); E08-D03 s6 annotation
color.text.inverse | long-outage step
color.text.link | Details
color.text.on-action | Retry now label
color.text.disabled | rejected on the CMP-079 label by E09-D09 T2 (reported, never bound)
color.action.primary.default | Retry now pill
color.surface.raised | TopBar (CMP-072), the chip's bar, SCR-001 card
color.surface.sunken | CMP-208 StatusBar (the ws dot's surface)
color.surface.hover | chip hover / tooltip-open
color.surface.overlay | popover; the scrim colour (at opacity.scrim)
color.surface.canvas | panels under the dim and the scrim
color.surface.app | E08-D03 s6 pair 6
color.focus.ring | every interactive element
color.data-confidence.live.text | CMP-239 format (reported; the chip word stays text.primary)
color.data-confidence.live.indicator | CMP-076 live glyph (quiet)
color.data-confidence.stale.text | CMP-078 (CMP-239 format)
color.data-confidence.stale.indicator | CMP-076 stale glyph, CMP-078 chip
color.data-confidence.stale.surface | CMP-078 dim (15 % composite); the color.overlay.stale alias
  target
color.data-confidence.reconnecting.indicator | CMP-028 connection-reconnecting accent (not the chip)
color.data-confidence.disconnected.indicator | CMP-208 ws dot; CMP-028 accent (rejected on the fill)
color.data-confidence.resyncing.indicator | resync scrim indicator
color.data-confidence.delayed.text | E17-D01 A7 (requested, not re-requested)
color.data-confidence.delayed.indicator | E17-D01 A7
color.data-confidence.delayed.surface | E17-D01 A7
color.overlay.stale | 15 CMP-078 (alias request CR-1)
color.surface.scrim | 15 CMP-077 (alias request CR-2)
color.status.warning | 15 CMP-092 (bare name)
color.callout.* | 15 CMP-028 (drift)
color.text.warning | 15 CMP-035 (drift)
font.mono | 15 CMP-035 (drift; font.family.mono exists)
font.family.ui | chip, banner text
font.family.mono | absolute UTC time (tabular)
elevation.5 | 15 CMP-077 (primitive; bind elevation.scrim)
elevation.scrim | per-panel scrims
elevation.chrome | the connection region in the banner slot
elevation.popover | the chip popover
opacity.scrim | the scrims (0.6)
opacity.disabled | rejected on the CMP-079 label, glyph and reason by E09-D09 T2 (reported)
radius.badge | chips and tags
radius.control | Retry now pill
type.ui.caption | compact chip, tags
type.ui.label | comfortable chip
type.ui.body | banner body
type.ui.body-strong | banner title
size.control.compact | compact row 24
size.control.comfortable | comfortable row 32
size.target.min | 24 px targets
size.icon.sm | chip glyph 12
size.icon.md | banner glyph 16
border.hairline | chip outline
border.thick | strip left border, outlined pill
border.focus | focus ring width
space.inset.xs | chip padding x
space.inset.sm | banner inset
space.stack.sm | CMP-092 issue rows
motion.duration.instant | every flip
motion.duration.fast | dismissal, scrim lift
motion.duration.normal | stale settle (E08-D11 D11)
motion.easing.standard | stale settle
motion.easing.accelerate | dismissal, scrim lift
"""
PRIMITIVE_ONLY = ("elevation.5",)

# matrix row | producing frame or field | columns with "no treatment" (comma list, or -)
STATES_TABLE = """
connecting before the session's first auth_ok | TransportState connecting (a reconnect attempt's
  socket emits it too, connection.ts open(): row 3's in-flight phase) | panel chrome
connected (Live) | TransportState connected; every topic live | panel chrome, announcement, motion
reconnecting (Disconnected): a retry scheduled or in flight | TransportState reconnecting
  (Link.reconnecting.attempt / nextAttemptAtMs); offline with a shell cause (offline /
  tailnet_unreachable / backend_unreachable: the retry timer runs); connecting after the first
  auth_ok | -
degraded:lagging | connection_quality.class lagging | global chrome, panel chrome, copy,
  announcement, motion
degraded:saturated (Delayed) | connection_quality.class saturated or overflowing; applied | -
offline (retry stopped) in a mounted workspace | TransportState offline; Link.offline.cause fatal
  (1002, 1009, 4400; a 4403 close code is the session-ended row; bye.reconnect false is folded
  into fatal by closePolicy) - never a shell cause | -
offline: shell cause on the login screen (SCR-001 inline, SCR-159) | the shell's ConnectionState
  offline, tailnet_unreachable, backend_unreachable (the folded fatal, C27) with no workspace
  mounted | panel chrome
shutdown_pending (Read-only, countdown) | system shutdown_notice: closing_in_ms,
  expected_downtime_ms, message | panel chrome
topic_resyncing (Resyncing) | TopicStatus resyncing; exchange_state.public_ws resyncing +
  affected_symbols | global chrome
topic_stale, T1 <= age < T2 | TopicStatus stale (age per topic, T1 table) | -
topic_stale >= T2 (escalated) | age >= 3 x T1; meta.stale on ticker or book counts as T2 | -
stale (server) | snap meta.stale true, held until the next snap | global chrome (unless ticker or
  book)
stale: upstream feed down | system exchange_state.public_ws connecting or disconnected; err
  exchange_unavailable | motion
book rebuilt | incident snap (upstream_desync, backpressure, upstream_reconnect) on a consumable
  book | global chrome, announcement
topic_revoked / permission change | revoked (reason, resubscribe_allowed, removed_accounts);
  permission_change | global chrome, motion
recovered / reconciling | auth_ok + public snapshots; then private snapshots + system or
  auth_ok.kill_switch | -
read-only reason (the region's slot) | system kill_switch, clock_drift; auth_ok.kill_switch;
  B20 lockout; exchange.private_ws down > 10 s; view-as (23 s9.6) | panel chrome
system unknown (D11) | WsState.systemStream not live; KillSwitchView unknown | panel chrome, motion
flapping (T5) | >= 3 transport changes in 5 s (transitionSeq) | panel chrome
long-outage / T4 steps (10 s, 30 s, 5 min) | continuous Disconnected (client clock) | panel chrome
session ended (no retry) | bye.reconnect false: session_revoked (4401), user_disabled (4403),
  mfa_enrollment_required (4403); a bare 4403 (Link.offline.closeCode) lands here today; told
  apart from a 4401 fatal close only with G12 | -
backend-health conditions (CMP-092): blocking only for the causes the order path refuses on
  (24 s8.10), info / warning for the rest | system health components[] (postgres -> blocking: the
  gate reads its flags from the Postgres store and MaintenanceGate fails closed; the overall
  health word routes nothing by itself; ingestion, recorder, rule engine, GPU fallback, cold tier
  -> info / warning), notice read-only codes, account_notice, maintenance.enabled; wallet
  health[] per account (23 s15.4) | panel chrome
err by errorMapping class (23 s10.3) | err protocol_violation / frame_malformed / invalid_options
  (client bug); subscription_limit / client_rate_limited (capacity); resync_rate_limited (rebuild
  budget, 23 s7.5) | global chrome
upstream private reconnect (E17-D01 s5; CMP-092 warning, then R5 at 10 s) | system
  exchange_state.private_ws connecting / resyncing (health.exchange.private_ws), until the private
  snap with reason upstream_reconnect | -
"""

# group | stories  -- the Storybook list (spec section 15; PROPOSED).
STORIES_TABLE = """
Organisms/ConnectionStatus | Live, Delayed, Stale, StaleEscalated, StaleServer, UpstreamDown,
  Reconnecting, Offline, Compact, Comfortable, TooltipOpen, HighContrast, Greyscale
Organisms/ReconnectOverlay | Reconnecting, OfflineFatal, ReconnectingUnreachable, SessionEnded,
  Recovered, LongOutage, ReadOnlyShutdown, ReadOnlyKillSwitch, DetailsOwner, DetailsViewer,
  Keyboard, ReducedMotion
Molecules/StaleDataShade | Fresh, Stale, Escalated, StaleServer, Disconnected, ReducedMotion
Molecules/DegradedModeBanner | SingleIssue, MultipleIssues, Blocking, DismissedReappears,
  HighContrast
"""
COMPONENTS = ("CMP-076", "CMP-077", "CMP-078", "CMP-092")
CHIP_VALUES = ("live", "delayed", "stale", "reconnecting", "offline")
CLOSE_CODES = (1000, 1001, 1002, 1009, 1011, 1012, 1013, 4401, 4403, 4429, 4400)
BYE_REASONS = (
    "server_shedding_load",
    "slow_consumer",
    "shutdown",
    "heartbeat_timeout",
    "internal_error",
    "frame_too_big",
    "session_revoked",
    "user_disabled",
    "auth_failed",
    "auth_timeout",
    "not_authenticated",
    "token_expired",
    "client_rate_limited",
    "too_many_connections",
    "view_as_changed",
    "view_as_expired",
    "mfa_enrollment_required",
    "origin_forbidden",
    "unsupported_protocol",
)
E08_D03_PAIRS = (
    ("color.text.primary", "color.status.danger.subtle"),
    ("color.text.secondary", "color.status.danger.subtle"),
    ("color.status.danger.strong", "color.status.danger.subtle"),
    ("color.action.primary.default", "color.status.danger.subtle"),
    ("color.text.link", "color.status.danger.subtle"),
    ("color.text.tertiary", "color.surface.app"),
)
DIMENSIONS = (
    "size.control.compact",
    "size.control.comfortable",
    "size.target.min",
    "size.icon.sm",
    "size.icon.md",
    "radius.badge",
    "radius.control",
    "border.hairline",
    "border.thick",
    "border.focus",
    "space.inset.xs",
    "space.inset.sm",
    "space.stack.sm",
    "opacity.scrim",
    "opacity.disabled",
    "motion.duration.instant",
    "motion.duration.fast",
    "motion.duration.normal",
)
PX_TYPES = ("sizing", "spacing", "borderRadius", "borderWidth", "fontSizes")
FIXED: dict[str, int | float] = {
    "boards": 12,
    "announcement_rows": 16,
    "motion_rows": 17,
    "hit_target_px": 24,
    "banner_slot_px": 96,
    "border_px": 4,
    "glyph_x": 24,
    "glyph_y": 16,
    "title_y": 14,
    "dim_pct": 15,
    "scrim_opacity": 0.6,
    "t1_book_s": 2,
    "t1_ticker_s": 5,
    "t1_trades_s": 10,
    "t2_book_s": 6,
    "t2_ticker_s": 15,
    "t2_trades_s": 30,
    "t3_min_s": 5,
    "t4_notify_s": 10,
    "t4_warn_s": 30,
    "t4_long_s": 300,
    "t5_changes": 3,
    "t5_window_s": 5,
    "t6_ping_s": 10,
    "recovered_hold_s": 10,
    "fill_step_s": 5,
    "rebuilt_s": 3,
    "budget_s": 5,
    "speak_s": 3,
}


class PairRow(TypedDict):
    element: str
    fg: str
    bg: str
    role: str
    bar: float | None
    ratios: dict[str, float | None]
    verdict: str
    registered: bool
    composite: bool
    source: str


class TokenRow(TypedDict):
    token: str
    bound_by: str
    status: str
    values: dict[str, str]


Tokens = dict[str, dict[str, object]]


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


def listed(table: str) -> dict[str, tuple[str, ...]]:
    return {k: tuple(x.strip() for x in v.split(",")) for k, v in rows(table)}


PAIRS = rows(PAIRS_TABLE)
BINDINGS = rows(BINDINGS_TABLE)
STATES = rows(STATES_TABLE)
STORIES = listed(STORIES_TABLE)


def load(name: str) -> Tokens:
    return cast(Tokens, json.loads((TOKENS / name).read_text(encoding="utf-8")))


def merged(files: tuple[str, ...]) -> Tokens:
    out: Tokens = {}
    for f in files:
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


def mix(a: str, b: str, p: float) -> str:
    ca = [int(a[i : i + 2], 16) for i in (1, 3, 5)]
    cb = [int(b[i : i + 2], 16) for i in (1, 3, 5)]
    return "#" + "".join(f"{round(x * (1 - p) + y * p):02X}" for x, y in zip(ca, cb, strict=True))


def hex_of(name: str, tokens: Tokens) -> str | None:
    m = MIX.match(name)
    if m:
        a, b = hex_of(m.group(1), tokens), hex_of(m.group(2), tokens)
        return mix(a, b, float(m.group(3))) if a and b else None
    if name not in tokens:
        return None
    value = resolve(tokens[name]["$value"], tokens)
    return value if isinstance(value, str) and HEX6.match(value) else None


def luminance(hex6: str) -> float:
    def chan(c: int) -> float:
        x = c / 255.0
        return x / 12.92 if x <= 0.04045 else ((x + 0.055) / 1.055) ** 2.4

    r, g, b = (int(hex6[i : i + 2], 16) for i in (1, 3, 5))
    return 0.2126 * chan(r) + 0.7152 * chan(g) + 0.0722 * chan(b)


def contrast(a: str, b: str) -> float:
    la, lb = luminance(a), luminance(b)
    return (max(la, lb) + 0.05) / (min(la, lb) + 0.05)


def registered_pairs() -> set[tuple[str, str]]:
    text = PAIRS_MJS.read_text(encoding="utf-8")
    return set(re.findall(r'fg:\s*"([^"]+)",\s*bg:\s*"([^"]+)"', text))


ENCODING_ROW = "connection-health"
#: The surfaces this spec draws the connection state on (CR-7 extends the existing row with them).
ENCODING_SURFACES = (
    "status bar",
    "chart overlay",
    "TopBar chip (CMP-076)",
    "SCR-152 region (CMP-077)",
    "panel shade (CMP-078)",
    "issue rows (CMP-092)",
)


def encodings_connection_health() -> dict[str, list[str]]:
    """The `connection-health` row: the surfaces it lists, and this spec's surfaces it lacks."""
    data = cast(dict[str, object], json.loads(ENCODINGS.read_text(encoding="utf-8")))
    encodings = cast(dict[str, object], data.get("encodings", {}))
    row = cast(dict[str, object], encodings.get(ENCODING_ROW, {}))
    present = sorted(cast(dict[str, object], row.get("surfaces", {})))
    missing = [surface for surface in ENCODING_SURFACES if surface not in present]
    return {"present": present, "missing": missing}


def measure(themes: dict[str, Tokens], reg: set[tuple[str, str]]) -> list[PairRow]:
    out: list[PairRow] = []
    for element, fg, bg, role, source in PAIRS:
        bar = BAR[role]
        ratios: dict[str, float | None] = {}
        fails: list[str] = []
        for theme in THEME_ORDER:
            a, b = hex_of(fg, themes[theme]), hex_of(bg, themes[theme])
            exact = contrast(a, b) if a and b else None  # compared unrounded, as generate.mjs
            ratios[theme] = None if exact is None else round(exact, 4)
            gated_here = role in GATED and (role != "hc-text" or theme == "high-contrast")
            if gated_here and bar is not None and (exact is None or exact < bar):
                fails.append(theme)
        if role == "decorative":
            low = [t for t in THEME_ORDER if (ratios[t] or 0) < NON_TEXT_BAR]
            below = "; below 3:1 in " + ", ".join(low) if low else ""
            verdict = f"decorative (reported{below})"
        elif role.startswith("rejected"):
            low = [t for t in THEME_ORDER if bar is not None and (ratios[t] or 0) < bar]
            verdict = "rejected: fails " + ", ".join(low) if low else "rejected: passes, not used"
        else:
            verdict = "PASS" if not fails else "FAIL " + ", ".join(fails)
        out.append(
            {
                "element": element,
                "fg": fg,
                "bg": bg,
                "role": role,
                "bar": bar,
                "ratios": ratios,
                "verdict": verdict,
                "registered": (fg, bg) in reg,
                "composite": bool(MIX.match(bg)),
                "source": source,
            }
        )
    return out


def bindings(themes: dict[str, Tokens]) -> list[TokenRow]:
    out: list[TokenRow] = []
    for name, bound_by in BINDINGS:
        values: dict[str, str] = {}
        for theme in THEME_ORDER:
            tokens = themes[theme]
            if name in tokens:
                resolved = resolve(tokens[name]["$value"], tokens)
                values[theme] = json.dumps(resolved, separators=(",", ":"))
        if not values:
            status = "MISSING"
        elif name in PRIMITIVE_ONLY:
            status = "primitive (alias elevation.scrim)"
        else:
            status = "resolved"
        out.append({"token": name, "bound_by": bound_by, "status": status, "values": values})
    return out


def dimension(name: str, tokens: Tokens) -> str:
    if name not in tokens:
        return "MISSING"
    value = resolve(tokens[name]["$value"], tokens)
    unit = " px" if str(tokens[name].get("$type")) in PX_TYPES else ""
    return f"{value}{unit}" if isinstance(value, str) else json.dumps(value)


def fmt(ratio: float | None) -> str:
    """Two decimals; four when the two-decimal form would land exactly on a bar."""
    if ratio is None:
        return "n/a"
    if round(ratio, 2) in BARS and round(ratio, 2) != round(ratio, 4):
        return f"{ratio:.4f}"
    return f"{ratio:.2f}"


def counts(pairs: list[PairRow], tokens: list[TokenRow]) -> dict[str, int | float]:
    gated = [p for p in pairs if p["role"] in GATED]
    plain = [p for p in gated if not p["composite"]]
    distinct = {(p["fg"], p["bg"]) for p in plain}
    proposed = {(p["fg"], p["bg"]) for p in plain if not p["registered"]}
    no_treatment = sum(0 if r[2] == "-" else len(r[2].split(",")) for r in STATES)
    out: dict[str, int | float] = {
        "components": len(COMPONENTS),
        "chip_values": len(CHIP_VALUES),
        "states_rows": len(STATES),
        "no_treatment_cells": no_treatment,
        "stories_total": sum(len(v) for v in STORIES.values()),
        "story_groups": len(STORIES),
        "close_codes": len(CLOSE_CODES),
        "bye_reasons": len(BYE_REASONS),
        "pairs_rows": len(pairs),
        "pairs_gated": len(gated),
        "pairs_composite": sum(1 for p in gated if p["composite"]),
        "pairs_distinct": len(distinct),
        "pairs_registered": len(distinct) - len(proposed),
        "pairs_proposed": len(proposed),
        "pairs_failing": sum(1 for p in gated if p["verdict"] != "PASS"),
        "pairs_rejected": sum(1 for p in pairs if p["role"].startswith("rejected")),
        "pairs_decorative": sum(1 for p in pairs if p["role"] == "decorative"),
        "e08_d03_pairs": len(E08_D03_PAIRS),
        "tokens_bound": sum(1 for t in tokens if t["status"] == "resolved"),
        "tokens_missing": sum(1 for t in tokens if t["status"] == "MISSING"),
        "themes": len(THEME_ORDER),
    }
    out.update(FIXED)
    return out


def print_markdown(
    pairs: list[PairRow],
    tokens: list[TokenRow],
    dims: dict[str, str],
    nums: dict[str, int | float],
    proposed: list[tuple[str, str]],
    reg_count: int,
) -> None:
    print("# E17-D02 token audit (packages/ui/tokens; WCAG 2.x; ratios to the hundredth)\n")
    print("## 1. Contrast matrix\n")
    print("| Element | fg | bg | role | bar | dark | light | hc | verdict | pairs.mjs | source |")
    print("| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |")
    for p in pairs:
        bar = "-" if p["bar"] is None else f"{p['bar']:g}:1"
        if p["composite"]:
            reg = "composite"
        else:
            reg = "registered" if p["registered"] else ("PROPOSED" if p["role"] in GATED else "-")
        r = p["ratios"]
        cells = [p["element"], f"`{p['fg']}`", f"`{p['bg']}`", p["role"], bar, fmt(r["dark"])]
        cells += [fmt(r["light"]), fmt(r["high-contrast"]), p["verdict"], reg, p["source"]]
        print("| " + " | ".join(cells) + " |")
    print("\n## 2. Token bindings\n")
    print("| Token | Bound by | Status | dark | light | hc |")
    print("| --- | --- | --- | --- | --- | --- |")
    for t in tokens:
        v = t["values"]
        cells = [f"`{t['token']}`", t["bound_by"], t["status"]]
        cells += [v.get(theme, "-") for theme in THEME_ORDER]
        print("| " + " | ".join(cells) + " |")
    print("\n## 3. Dimensions bound by the anatomy (identical in every theme)\n")
    print("| Token | Value |")
    print("| --- | --- |")
    for name, value in dims.items():
        print(f"| `{name}` | {value} |")
    print("\n## 4. pairs.mjs and encodings.json\n")
    listing = ", ".join(f"`{a}` on `{b}`" for a, b in proposed)
    print(f"- registered pairs scanned: {reg_count}; PROPOSED additions ({len(proposed)}):")
    print(f"  {listing}")
    enc = encodings_connection_health()
    print(f"- `encodings.json` `{ENCODING_ROW}` row: surfaces {enc['present']};")
    print(f"  this spec's surfaces it lacks ({len(enc['missing'])}; CR-7 extends it):")
    print(f"  {enc['missing']}")
    e08 = [p for p in pairs if (p["fg"], p["bg"]) in E08_D03_PAIRS]
    print(f"- E08-D03 section 6 pairs reproduced from the tokens: {len(e08)} of 6")
    print("\n## 5. Counts the boards quote\n")
    for key, number in nums.items():
        print(f"- {key}: {number}")


def main(argv: list[str]) -> int:
    themes = {name: merged(files) for name, files in THEMES.items()}
    reg = registered_pairs()
    pairs = measure(themes, reg)
    tokens = bindings(themes)
    dims = {d: dimension(d, themes["dark"]) for d in DIMENSIONS}
    nums = counts(pairs, tokens)
    proposed = sorted(
        {
            (p["fg"], p["bg"])
            for p in pairs
            if p["role"] in GATED and not p["registered"] and not p["composite"]
        }
    )
    failing = [p for p in pairs if p["role"] in GATED and p["verdict"] != "PASS"]
    if "--json" in argv:
        out = {
            "pairs": pairs,
            "tokens": tokens,
            "dimensions": dims,
            "counts": nums,
            "proposed_pairs": [list(p) for p in proposed],
            "encodings_connection_health": encodings_connection_health(),
            "states": STATES,
            "stories": STORIES,
            "chip_values": list(CHIP_VALUES),
            "close_codes": list(CLOSE_CODES),
            "bye_reasons": list(BYE_REASONS),
        }
        print(json.dumps(out, indent=2, ensure_ascii=False))
        return 1 if failing else 0
    print_markdown(pairs, tokens, dims, nums, proposed, len(reg))
    print("\n## 6. Verdict\n")
    if failing:
        print("FAIL: " + "; ".join(f"{p['fg']} on {p['bg']} ({p['verdict']})" for p in failing))
        return 1
    gated, themes_n, missing = nums["pairs_gated"], nums["themes"], nums["tokens_missing"]
    rej, deco = nums["pairs_rejected"], nums["pairs_decorative"]
    print(
        f"OK: {gated} gated rows over {themes_n} themes pass (unrounded compare); "
        f"{missing} names MISSING (expected); {rej} rejected and {deco} decorative rows reported"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
