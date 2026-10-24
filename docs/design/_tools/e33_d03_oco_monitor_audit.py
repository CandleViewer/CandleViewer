#!/usr/bin/env python3
"""E33-D03 OCO builder and algo monitor audit (stdlib, offline; executes no repo code).

Reads the token JSON, `pairs.mjs`, the plan texts, the shipped B04 JSON, the E33-D01 memo and the
spec AS TEXT and prints: (1) the WCAG 2.x ratio of every fg / bg pair the two screens render in
dark / light / high-contrast (`themes.json` layering) and the validity composite; (2) every token
the spec binds, resolved or MISSING, and the glyph names no merged spec uses yet; (3) the pairs
`pairs.mjs` registers; (4) the contract facts the boards quote, parsed from text; (5) the copy
gates (memo strings byte-for-byte, retired words absent, T2 reasons within 60 characters, no
private path, every cited id and line still valid); (6) the counts the boards and the draft quote.
`--json` feeds the check-nums script; `--check` re-derives the spec's `audit:` markers.
Exit 1 on a gated FAIL or a failed gate.

Usage: python3 -I docs/design/_tools/e33_d03_oco_monitor_audit.py [--json] [--check] [--extra F]
"""

from __future__ import annotations

import json
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
TOKENS = ROOT / "packages" / "ui" / "tokens"
PLAN = ROOT / "docs" / "plan"
DESIGN = ROOT / "docs" / "design"
SPEC = DESIGN / "E33" / "E33-D03.md"
HANDOFF = DESIGN / "E33" / "E33-D03-handoff.md"
MEMO = DESIGN / "research" / "e33-emulated-algo-trust.md"
B04 = ROOT / "services/api/candleviewer/statechart/machines/B04.oco.machine.json"
PRIM, DARK, LIGHT, HC = (
    "primitives.tokens.json",
    "semantic-dark.tokens.json",
    "semantic-light.tokens.json",
    "semantic-hc.tokens.json",
)
THEMES = {"dark": (PRIM, DARK), "light": (PRIM, DARK, LIGHT), "high-contrast": (PRIM, DARK, HC)}
BAR: dict[str, float | None] = {"text": 4.5, "non-text": 3.0}
MULTI = re.MULTILINE
# Generic patterns only: no personal word, no hostname whole or split; the path literal is split.
FORBIDDEN = (
    r"/(?:ho[m]e|Users)/[^/\s]+/",
    r"penpot\.[a-z0-9-]+\.[a-z]{2,}",
    r"team-i[d]=",
    r"file-i[d]=",
)
# Words the memo retires from user-facing copy (SC-6, F6, F7, F11); checked on the copy deck only.
BANNED_COPY = (
    r"app-managed",
    r"client-side",
    r"client-of-exchange-side",
    r"Bybit has no",
    r"pauses? if the backend",
    r"algos pause if backend",
    r"\bfreeze\b",
    r"\(estimated\) tag",
)
CAVEAT_ENTRY = (
    "CandleViewer links these two orders, not Bybit: as one fills, it shrinks or cancels the "
    "other. It keeps working if you close this window. If CandleViewer's server is down or has "
    "lost Bybit when one fills, the other stays live and can fill too, so you could hold both. "
    "Your position keeps its stop-loss at Bybit."
)
CAVEAT_EXIT = (
    "CandleViewer links these two exits, not Bybit: as one fills, it shrinks or cancels the "
    "other. It keeps working if you close this window. If CandleViewer's server is down at that "
    "moment, the other exit stays at Bybit until it is back; it is reduce-only, so it cannot add "
    "to your position."
)
RESIDUAL_ENTRY = (
    "While CandleViewer could not manage OCO a_15, both entries filled: you hold 1.000 BTC, not "
    "0.500. CandleViewer sent a reduce-only order for the extra 0.500 BTC at 14:05:44 UTC — "
    "filled at 64,001.0."
)
RESIDUAL_EXIT = (
    "The take-profit of OCO a_16 filled at 14:03:10 UTC while CandleViewer could not manage it; "
    "the other exit was cancelled at 14:05:44, 2 min 34 s later."
)
BANNER_1 = "Can't reach CandleViewer's server, where your algos run."
BANNER_2 = "No new algo orders: CandleViewer's live link to Bybit is down."
STOP_LINE = (
    "Stop-losses at Bybit are held by Bybit and work whether or not CandleViewer is running."
)
TAG_NAME = "Emulated — run by CandleViewer, not Bybit"
# C-2.6 on an exit pair: the frame names the position's own stop; an OCO leg is never that stop.
EXTRA_EXIT = (
    "Your position's native stop stays at Bybit; this stop-market leg is an extra exit "
    "CandleViewer manages."
)
# C-2.6 on an entry pair: each leg's read-out names its own stop at Bybit (the derived fixture).
ENTRY_LEGS = (("Entry A", "stop_a"), ("Entry B", "stop_b"))
# The section 3 frames that show the entry legs, by name: each row carries both per-leg markers.
ENTRY_FRAMES = ("SCR-069/editing-entry-pair", "SCR-076/oco")
# A LIVE run, row or badge is an absence in R3: every LIVE env token in sections 2-10, in any case
# (`LIVE`, `live`, "a Live row", "a live run"), has a negation in its own clause. Plain-English
# "live" (a live link, live validation, aria-live) is not an env token.
ENV_NOUN = r"(?:rows?|runs?|badges?|accounts?|env(?:ironment)?s?|modes?|algos?|sessions?|starts?)"
LIVE_WORD = rf"\bLIVE\b|`live`|(?i:\blive\b(?= {ENV_NOUN}\b))"
NEGATION = r"\b(?:no|never|not|nor|absence|absent|without)\b"
CLAUSE_END = r"[.;|\n]"
HALT = "Halted by risk control"
MEMO_STRINGS = (
    CAVEAT_ENTRY,
    CAVEAT_EXIT,
    RESIDUAL_ENTRY,
    RESIDUAL_EXIT,
    BANNER_1,
    BANNER_2,
    STOP_LINE,
    TAG_NAME,
    HALT,
)
# element | fg | bg | role — every pair the two screens draw (spec section 14, rows in order).
PAIRS_TABLE = """
dialog and panel text, cell words | color.text.primary | color.surface.raised | text
labels, read-outs, T2 reasons on raised | color.text.secondary | color.surface.raised | text
T2 label and lock glyph | color.text.tertiary | color.surface.raised | text
cell text on the zebra row | color.text.primary | color.surface.canvas | text
secondary cells, captions | color.text.secondary | color.surface.canvas | text
tertiary captions on canvas | color.text.tertiary | color.surface.canvas | text
dialog body on the overlay | color.text.primary | color.surface.overlay | text
dialog labels and reasons on the overlay | color.text.secondary | color.surface.overlay | text
T2 menu item label on the overlay | color.text.tertiary | color.surface.overlay | text
Running word on the neutral chip | color.text.primary | color.surface.hover | text
cell text on the selected row | color.text.primary | color.surface.selected | text
DEMO badge word (AA bar) | color.text.primary | color.surface.raised | text
DEMO badge word (the 7:1 target) | color.text.primary | color.surface.raised | aaa-target
DEMO dot and border | color.env.demo | color.surface.raised | non-text
DEMO band rule | color.env.demo | color.surface.app | non-text
CMP-158 sentence, info banner word | color.text.primary | color.status.info.subtle | text
CMP-158 glyph | color.status.info.strong | color.status.info.subtle | non-text
Paused and Waiting words, the age warning | color.text.primary | color.status.warning.subtle | text
warning second line | color.text.secondary | color.status.warning.subtle | text
warning glyph | color.status.warning.strong | color.status.warning.subtle | non-text
Halted, Failed, refusal words | color.text.primary | color.status.danger.subtle | text
danger second line | color.text.secondary | color.status.danger.subtle | text
danger glyph | color.status.danger.strong | color.status.danger.subtle | non-text
validation boundary on the dialog | color.status.danger.default | color.surface.overlay | non-text
Completed word | color.text.primary | color.status.success.subtle | text
success glyph | color.status.success.strong | color.status.success.subtle | non-text
reconnect accent | color.data-confidence.reconnecting.indicator | color.surface.canvas | non-text
stale row (case 1) | color.data-confidence.stale.text | color.data-confidence.stale.surface | text
progress bar fill on its track | color.action.primary.default | color.surface.sunken | non-text
Place / Confirm label | color.text.on-action | color.action.primary.default | text
Cancel all confirm label | color.text.on-action | color.status.danger.default | text
focus ring on raised | color.focus.ring | color.surface.raised | non-text
focus ring on the overlay | color.focus.ring | color.surface.overlay | non-text
field well boundary | color.text.tertiary | color.surface.app | non-text
buy glyph on raised | color.buy.default | color.surface.raised | non-text
sell glyph on raised | color.sell.default | color.surface.raised | non-text
REJECTED accent on raised | color.data-confidence.reconnecting.indicator | color.surface.raised | rj
REJECTED T2 label in text.disabled | color.text.disabled | color.surface.raised | rejected-text
the card hairline | color.border.default | color.surface.raised | decorative
"""
BINDINGS = (
    "color.surface.app",
    "color.surface.canvas",
    "color.surface.raised",
    "color.surface.overlay",
    "color.surface.sunken",
    "color.surface.hover",
    "color.surface.selected",
    "color.border.default",
    "color.border.subtle",
    "color.text.primary",
    "color.text.secondary",
    "color.text.tertiary",
    "color.text.on-action",
    "color.status.info.subtle",
    "color.status.info.strong",
    "color.status.warning.subtle",
    "color.status.warning.strong",
    "color.status.danger.subtle",
    "color.status.danger.default",
    "color.status.danger.strong",
    "color.status.success.subtle",
    "color.status.success.strong",
    "color.action.primary.default",
    "color.action.selected",
    "color.focus.ring",
    "color.env.demo",
    "color.buy.default",
    "color.sell.default",
    "color.data-confidence.stale.text",
    "color.data-confidence.stale.surface",
    "color.data-confidence.reconnecting.indicator",
    "opacity.disabled",
    "radius.control",
    "radius.card",
    "radius.badge",
    "type.ui.caption",
    "type.ui.body",
    "type.ui.label",
    "type.num.base",
    "size.row.height",
    "size.control.height",
    "space.inset.sm",
    "color.track",
)
GLYPHS = ("lock", "alert-triangle", "refresh", "check", "x", "pause", "play")
GLYPH_PRECEDENTS = ("E29/E29-D02.md", "E29/E29-D03.md", "E36/E36-D04.md", "E17/E17-D02.md")
# doc | line at the base | text the line must hold; a `14` line may sit lower by the pointers. The
# `22` lines past :11489 are pinned to the `origin/main` the spec header names (six below the base).
CITED_TABLE = """
14 | 1577 | explicitly labelled "emulated — Bybit's API has no OCO"
14 | 1581 | `role="note"`
14 | 1582 | targeting <=300 ms from fill event
14 | 1584 | entry+bracket and standalone-OCO
14 | 1601 | **Data:** WS `orders`; `GET /api/v1/orders`
14 | 1602 | degraded (backend reconnecting
14 | 1604 | 'Cancel TWAP a_12 on BTCUSDT, Main'
14 | 1605 | Algo state arrives on `orders`, coalesced to 2 Hz
14 | 1608 | 'pause all' and 'cancel all'
22 | 281 | Read-only.
22 | 17938 | AlgoSpec:
22 | 18060 | CancelAllRequest:
22 | 18551 | SetKillSwitchRequest:
22 | 5871 | operationId: cancelAllOrders
23 | 824 | [`OrderUpdate`](#151-orderupdate)
23 | 898 | `algo:{algo_id}`
23 | 965 | `orders:read` on its account (E33-T02)
24 | 2714 | class AlgoSpec
24 | 2730 | class AlgoState
24 | 2773 | class OcoParams
24 | 2788 | Preferred alternative
24 | 4824 | `algo.started`
28 | 2986 | B4.2 States
28 | 3002 | B4.3 Events
28 | 4458 | B8.2 States
11 | 3434 | reconciliation runs at least every 30 s
20 | 912 | no WS or REST success this long = `down`
"""
# Table-row needles carry pipes, so they sit outside the pipe-split table (same cite rule).
CITED_ROWS: tuple[tuple[str, str, str], ...] = (
    ("28", "3382", "| `repricing` | _always_ | `two_consecutive_post_only_rejects` |"),
    ("28", "3384", "| `cooling_down` | `COOLDOWN_DUE` | — | `submitting_slice` |"),
)
POINTER = "E33-D03.md](../design/E33/E33-D03.md)"
DOC_NAMES = (
    "11-user-stories.md",
    "14-screens-catalogue.md",
    "15-component-catalogue.md",
    "20-architecture.md",
    "21-database-schema.md",
    "22-api-openapi.yaml",
    "23-ws-protocol.md",
    "24-internal-schemas.md",
    "28-statechart-catalogue.md",
)
DOCS = {n[:2]: PLAN / n for n in DOC_NAMES}
FIXTURE: dict[str, float] = json.loads(
    '{"entry": 64010.0, "stop": 63900.0, "target": 64230.0, "mark": 64012.0, "size": 0.25, '
    '"leg_qty": 0.5, "double": 1.0, "fill": 64001.0, "tick": 0.1, "entry_a": 64050.0, '
    '"entry_b": 63990.0, "exit_stop": 63950.0, "twap_total": 2.0, "twap_filled": 1.2, '
    '"twap_left": 0.8, "avg": 64004.0}'
)
# Derived, never typed: each entry leg's stop sits where E32-D02's stop sits under its entry; every
# tick distance is measured from the mark (the exit pair's stop leg is above the held stop).
_STOP_GAP = FIXTURE["entry"] - FIXTURE["stop"]
FIXTURE["stop_a"] = round(FIXTURE["entry_a"] - _STOP_GAP, 1)
FIXTURE["stop_b"] = round(FIXTURE["entry_b"] - _STOP_GAP, 1)
FIXTURE["ticks_up"] = round((FIXTURE["target"] - FIXTURE["mark"]) / FIXTURE["tick"])
FIXTURE["ticks_down"] = round((FIXTURE["mark"] - FIXTURE["exit_stop"]) / FIXTURE["tick"])
FIXTURE["ticks_entry_a"] = round((FIXTURE["entry_a"] - FIXTURE["mark"]) / FIXTURE["tick"])
FIXTURE["ticks_entry_b"] = round((FIXTURE["mark"] - FIXTURE["entry_b"]) / FIXTURE["tick"])
# The 40-run bulk fixture: the kinds, what Pause all skips per kind (every skip a section 1.3
# class), the cooling-down icebergs it defers (B5 defers USER_PAUSE; never skipped) and the per-item
# result; the paused, deferred and skipped counts are derived below, never typed.
BULK: dict[str, float] = json.loads(
    '{"twap": 12, "chase": 9, "iceberg": 14, "oco": 5, "orders": 31, "btc": 2.14, '
    '"cancelled": 38, "failed": 2, "twap_price_blocked": 3, "chase_parked": 2, '
    '"iceberg_cooling": 2, "finishing_twap": 0, "finishing_iceberg": 1}'
)
AT_BYBIT = json.loads(
    '{"twap": 0.07, "chase": 1.0, "iceberg": 0.25, "oco_entry": 1.0, "oco_exit": 0.5, "orders": 7}'
)
AGES = {"checked_s": 12, "warn_s": 60, "stale_s": 60, "example_stale_s": 75}
ROWS = {"compact_px": 24, "comfortable_px": 32, "core_px": 300, "density_rows": 100}
ROWS.update({"real_rows": 12, "virtualised": 88})
# section | pattern — the counted frame rows per spec section (start, end, regex).
COUNTS = (
    ("frames_069", 3, 4, r"^\| `SCR-069/"),
    ("frames_076", 3, 4, r"^\| `SCR-076/"),
    ("row_kinds", 6, 7, r"^\| `SCR-070/row-"),
    ("orphan_rows", 6, 7, r"^\| `SCR-070/orphan-"),
    ("panel_states", 7, 8, r"^\| `SCR-070/"),
    ("bulk_frames", 8, 9, r"^\| `SCR-070/"),
    ("density_frames", 9, 10, r"^\| `SCR-0(?:70|63)/"),
    ("boards", 0, 1, r"^\| \d\d +\| `"),
    ("light_twins", 0, 1, r"^\| \d\d +\| `[^`]+-light`"),
)
ROW_IDS = (("c_rows", "C"), ("cg_rows", "CG"), ("g_rows", "G"), ("a_rows", "A"), ("q_rows", "Q"))
REASON_RE = r"^\| `((?:rbac|algo|recon)\.[a-z_.]+|frozen|lockout)` +\| ([^|]+?) +\|"


# Cite rule: the needle must occur exactly once in its file. Once, at the cited line (or the cited
# line plus the PR's pointer shift for `14`): OK. Once, elsewhere: WARN naming the current line
# (drift at any distance; re-pin at the next text touch). Not at all: FAIL "cited text gone".
# More than once: FAIL "cited text ambiguous" (lengthen the needle; do not re-pin).
CITE_WARN: list[str] = []


def rows(table: str) -> list[list[str]]:
    return [[c.strip() for c in ln.split("|")] for ln in table.strip().splitlines()]


def load_theme(name: str) -> dict[str, object]:
    merged: dict[str, object] = {}
    for f in THEMES[name]:
        data = json.loads((TOKENS / f).read_text(encoding="utf-8"))
        merged.update({k: v.get("$value") for k, v in data.items() if isinstance(v, dict)})
    return merged


def resolve(tokens: dict[str, object], name: str) -> str:
    if name not in tokens:
        return "MISSING"
    value, hops = tokens[name], 0
    while isinstance(value, str) and value.startswith("{") and value.endswith("}") and hops < 12:
        value, hops = tokens.get(value[1:-1], "MISSING"), hops + 1
    return str(value)


def rgb(hex6: str) -> list[int]:
    return [int(hex6.lstrip("#")[i : i + 2], 16) for i in (0, 2, 4)]


def luminance(hex6: str) -> float:
    lin = [
        (c / 12.92) if c <= 0.03928 else ((c + 0.055) / 1.055) ** 2.4
        for c in (v / 255 for v in rgb(hex6))
    ]
    return 0.2126 * lin[0] + 0.7152 * lin[1] + 0.0722 * lin[2]


def contrast(a: str, b: str) -> float:
    la, lb = luminance(a), luminance(b)
    return (max(la, lb) + 0.05) / (min(la, lb) + 0.05)


def blend(fg: str, bg: str, alpha: float) -> str:
    mixed = (round(a * alpha + b * (1 - alpha)) for a, b in zip(rgb(fg), rgb(bg), strict=True))
    return "#" + "".join(f"{v:02X}" for v in mixed)


def show(ratio: float) -> str:
    near = any(abs(ratio - bar) < 0.005 for bar in (3.0, 4.5, 7.0))
    return f"{ratio:.4f}" if near else f"{ratio:.2f}"


def section(spec: str, a: int, b: int) -> str:
    return spec[spec.index(f"\n## {a}.") : spec.index(f"\n## {b}.")]


def first(pattern: str, text: str, flags: int = 0) -> str:
    m = re.search(pattern, text, flags)
    return m.group(1) if m else "MISSING"


def count(pattern: str, text: str) -> int:
    return len(re.findall(pattern, text, MULTI))


def contract_facts(t: dict[str, str]) -> dict[str, object]:
    """Every fact a board quotes, parsed from the plan text; nothing is executed."""
    memo = " ".join(MEMO.read_text(encoding="utf-8").split())
    d24, api = t["24"], t["22"]
    spec_cls = d24[d24.index("class AlgoSpec") : d24.index("class AlgoState")]
    state = d24[d24.index("class AlgoState") :]
    oco = d24[d24.index("class OcoParams") :]
    oco = oco[: oco.index("```")]
    oco22 = api[api.index("    AlgoSpec:") :]
    oco22 = oco22[oco22.index("        oco:") : oco22.index("        iceberg:")]
    kill = api[api.index("    SetKillSwitchRequest:") :]
    b4 = t["28"][t["28"].index("### B4.2") : t["28"].index("### B4.4")]
    b4_states = re.findall(r"^\| `([a-z_]+)` \| (?:atomic|final)", b4, MULTI)
    b8 = t["28"][t["28"].index("### B8.2") : t["28"].index("### B8.3")]
    b04 = list(json.loads(B04.read_text(encoding="utf-8"))["states"].keys())
    scr070 = t["14"][t["14"].index("### SCR-070") : t["14"].index("### SCR-071")]
    m1 = memo[memo.index("| M1 ") : memo.index("| M2 ")]
    spec_default = (
        r"^\s+(max_children|on_disconnect|cancel_on_position_flat): [^=]+= ([^#\n]+?)\s*(?:#.*)?$"
    )
    ks_default = (
        r"^\s+(cancel_open_orders|flatten_positions|disarm_rules): \{ type: boolean, default: (\w+)"
    )
    zero_words = ("/algos", "last_reconciled", "chart_state", "paused_by", "halt_reason")
    return {
        "algo_state_status": re.findall(
            r'"(\w+)"', first(r"status: Literal\[(.*?)\]", state, re.DOTALL)
        ),
        "algo_spec_defaults": dict(re.findall(spec_default, spec_cls, MULTI)),
        "oco_params_24": re.findall(r"^\s+(leg_a|leg_b|mode|reduce_only):", oco, MULTI),
        "oco_mode_default_24": first(r'mode: Literal\[.*?\] = "(\w+)"', oco),
        "oco_22_properties": re.findall(r"^\s{12}(\w+):", oco22, MULTI),
        "cancel_timeout_ms_default_22": int(first(r"maximum: 60000,\s*default: (\d+)", oco22)),
        "exclude_reduce_only_default": first(
            r"exclude_reduce_only:\s*\{\s*type: boolean,\s*default: (\w+)", api
        ),
        "kill_switch_defaults": dict(re.findall(ks_default, kill, MULTI)),
        "orders_topic_throttle": first(
            r"^\| `orders` +\|[^|]*\|[^|]*\| ([^|]+?) +\|", t["23"], MULTI
        ),
        "machines_algo_row": "`algo:{algo_id}`" in t["23"]
        and "`oco`, `iceberg`, `twap`, `chase`" in t["23"],
        "zero_counts": {f"{k}:{w}": t[k].count(w) for k in ("22", "23") for w in zero_words},
        "b4_states": b4_states,
        "b4_racing_events": sorted(set(re.findall(r"^\| `racing` \| `([A-Z_*]+)`", b4, MULTI))),
        "b4_has_user_pause": "USER_PAUSE" in b4,
        "b4_has_ws_disconnect": "WS_DISCONNECT" in b4,
        "b8_tags": sorted(set(re.findall(r"`(protected|naked)`", b8))),
        "b8_states": re.findall(r"^\| `sl\.([a-z_]+)` \| atomic", b8, MULTI),
        "b8_public_id": "B8 `position_protection`" in t["23"]
        and "have no public id yet" in t["23"],
        "b04_shipped_states": b04,
        "b04_equals_b4": b04 == b4_states,
        "scr070_3ms": "3 ms" in scr070,
        "scr070_2hz": "2 Hz" in scr070,
        "us_algo_010_30s": "reconciliation runs at least every 30 s" in t["11"],
        "cv_account_down_s": int(first(r"`CV_ACCOUNT_DOWN_S` +\| float +\| `(\d+)`", t["20"])),
        "memo_m1_ages": [
            int(x)
            for g in re.findall(r"Bybit (\d+) s ago|older than (\d+) s|for (\d+) s", m1)
            for x in g
            if x
        ],
        "reconcile_interval_in_24": "reconcile_interval" in d24,
        "memo_strings_present": [s in memo for s in MEMO_STRINGS],
        "flags_24": "`trading.algos.oco`" in d24,
        "flags_21_algo": "`algo.oco`" in t["21"],
    }


def gates(files: list[Path], spec: str, facts: dict[str, object], t: dict[str, str]) -> list[str]:
    bad: list[str] = []
    constitution = (ROOT / "CONSTITUTION.md").read_text(encoding="utf-8")
    deck = section(spec, 13, 14)
    bad += [f"spec: memo string missing: {s[:50]}" for s in MEMO_STRINGS if s not in spec]
    present = list(facts["memo_strings_present"])  # type: ignore[call-overload]
    bad += [
        f"memo: string not in the memo: {s[:50]}"
        for s, ok in zip(MEMO_STRINGS, present, strict=True)
        if not ok
    ]
    bad += [
        f"spec section 13: retired word in UI copy: {m.group(0)!r}"
        for p in BANNED_COPY
        for m in re.finditer(p, deck)
    ]
    for key, cell in re.findall(REASON_RE, deck, MULTI):
        if key in ("frozen", "lockout"):
            continue  # E30-D02 §14 registered strings, cited verbatim; not this spec's to shorten
        for s in re.findall(r'"([^"]+)"', cell):  # every string a key row carries, not the first
            if len(s) > 60 or not s.endswith(".") or re.search(r"\d", s):
                digit = bool(re.search(r"\d", s))
                stop = s.endswith(".")
                bad.append(f"T2 reason {key}: {len(s)} chars; stop {stop}; digit {digit}")
    s3 = section(spec, 3, 4)
    if re.search(r"^\| `SCR-069/[a-z0-9-]+` +\|(?![^\n]*CMP-158)", s3, MULTI):
        bad.append("spec section 3: a SCR-069 frame lacks the CMP-158 line")
    flat_uncond = (
        r"^\| `SCR-0(?:69|76)/[a-z0-9-]+` +\|"
        r"(?=[^\n]*`caveat\.oco_entry`)(?![^\n]*`stop\.interim`)"
    )
    if re.search(flat_uncond, s3, MULTI):
        bad.append("spec section 3: an entry-pair frame binds the unconditional stop sentence")
    bad += stop_gates(spec)
    body = section(spec, 2, 11)
    for m in re.finditer(LIVE_WORD, body):
        starts = [e.end() for e in re.finditer(CLAUSE_END, body[: m.start()])]
        end = re.search(CLAUSE_END, body[m.end() :])
        clause = body[starts[-1] if starts else 0 : m.end() + (end.start() if end else 0)]
        if not re.search(NEGATION, clause, re.IGNORECASE):
            bad.append(f"spec sections 2-10: {m.group(0)} without a negation (LIVE is an absence)")
    lines = {k: v.split("\n") for k, v in t.items()}
    CITE_WARN.clear()
    for doc, line_s, want in [*rows(CITED_TABLE), *CITED_ROWS]:
        line = int(line_s)
        shift = sum(POINTER in ln for ln in lines[doc][: line - 1]) if doc == "14" else 0
        found = [i + 1 for i, ln in enumerate(lines[doc]) if want in ln]
        total = sum(ln.count(want) for ln in lines[doc])
        if total == 0:
            bad.append(f"cited text gone: `{doc}` :{line} {want[:40]!r} (nowhere in the file)")
        elif total > 1:
            bad.append(
                f"cited text ambiguous: `{doc}` :{line} {want[:40]!r} "
                f"({total} matches: use a longer needle)"
            )
        elif found[0] not in (line, line + shift):
            CITE_WARN.append(f"`{doc}` :{line} now at :{found[0]} ({want[:40]!r})")
    for f in files:
        txt = f.read_text(encoding="utf-8")
        bad += [f"{f.name}: forbidden text {p}" for p in FORBIDDEN if re.search(p, txt)]
        for r in sorted(set(re.findall(r"\bC-\d+\.\d+\b", txt))):
            if f"**{r}" not in constitution:
                bad.append(f"{f.name}: dangling rule id {r}")
        for c in sorted(set(re.findall(r"\b(?:CMP|SCR)-\d{3}\b", txt))):
            if f"### {c} " not in t["15" if c.startswith("CMP") else "14"]:
                bad.append(f"{f.name}: no catalogue heading for {c}")
    return bad


def stop_gates(spec: str) -> list[str]:
    """C-2.6 per leg: every entry leg names its own stop, every exit pair names the position's."""
    bad: list[str] = []
    s2, s3 = section(spec, 2, 3), section(spec, 3, 4)
    for leg, key in ENTRY_LEGS:
        want = f"stop {FIXTURE[key]:,.1f} at Bybit"
        readouts = re.findall(rf'"{leg} ·[^"]*"', s2)
        if not readouts or any(want not in r for r in readouts):
            bad.append(f"spec section 2: the {leg} read-out lacks its own stop ({want})")
    frames = re.findall(r"^\| `SCR-0(?:69|76)/[a-z0-9-]+` +\|[^\n]*", s3, MULTI)
    by_name = {row.split("`")[1]: row for row in frames}
    for name in ENTRY_FRAMES:
        row = by_name.get(name, "")
        for leg, key in ENTRY_LEGS:
            want = f"stop {FIXTURE[key]:,.1f} at Bybit"
            if want not in row:
                bad.append(f"spec section 3: {name} lacks {leg}'s stop marker ({want})")
    for row in frames:
        name = row.split("`")[1]
        if re.search(r"Entry [AB]|both legs with", row) and not re.search(
            r"(?:its|their) (?:own )?stops?\b|stop [\d,]+\.\d at Bybit", row
        ):
            bad.append(f"spec section 3: {name} shows the entry legs without their stops")
        if "`caveat.oco_exit`" in row and not re.search(r"`oco\.extra_exit`|`sl\.label`", row):
            bad.append(f"spec section 3: {name} is an exit pair that names no position stop")
        if "`oco.extra_exit`" in row and EXTRA_EXIT not in row:
            bad.append(f"spec section 3: {name} binds oco.extra_exit without its sentence")
    if EXTRA_EXIT not in section(spec, 13, 14):
        bad.append("spec section 13: the oco.extra_exit sentence is missing")
    return bad


def flatten(d: object, prefix: str = "") -> dict[str, object]:
    out: dict[str, object] = {}
    if isinstance(d, dict):
        for k, v in d.items():
            out.update(flatten(v, f"{prefix}{k}."))
    else:
        out[prefix[:-1]] = d
    return out


def main(argv: list[str]) -> int:
    extra = [Path(a) for a in argv[argv.index("--extra") + 1 :]] if "--extra" in argv else []
    themes = {k: load_theme(k) for k in THEMES}
    t = {k: p.read_text(encoding="utf-8") for k, p in DOCS.items()}
    pairs_text = (ROOT / "tools" / "contrast" / "pairs.mjs").read_text(encoding="utf-8")
    registered = set(re.findall(r'fg:\s*"([^"]+)",\s*bg:\s*"([^"]+)"', pairs_text))
    out = ["## 1. Measured matrix (fg on bg | role | dark / light / hc | verdict | pairs | where)"]
    matrix: list[dict[str, object]] = []
    fails = proposed = gated = 0
    demo_7 = True
    for element, fg, bg, role in rows(PAIRS_TABLE):
        ratios = {th: contrast(resolve(tk, fg), resolve(tk, bg)) for th, tk in themes.items()}
        bar = BAR.get(role)
        if role == "aaa-target":
            demo_7 = all(r >= 7.0 for r in ratios.values())
            verdict = "7:1 met" if demo_7 else "7:1 not met — shortfall stated (spec 14)"
        elif bar is None:
            verdict = "reported, not gated" if role == "decorative" else "rejected, never drawn"
        else:
            gated += 1
            verdict = "PASS" if all(r >= bar for r in ratios.values()) else "FAIL"
            fails += verdict == "FAIL"
            proposed += (fg, bg) not in registered
        reg = "registered" if (fg, bg) in registered else "PROPOSED"
        row: dict[str, object] = {"element": element, "fg": fg, "bg": bg, "role": role}
        row.update(
            {"verdict": verdict, "pairs": reg, **{k: round(v, 4) for k, v in ratios.items()}}
        )
        matrix.append(row)
        shown = " / ".join(show(r) for r in ratios.values())
        out.append(f"{fg} on {bg} | {role} | {shown} | {verdict} | {reg} | {element}")
    composite: dict[str, float] = {}
    for th, tk in themes.items():
        over = resolve(tk, "color.surface.overlay")
        label = blend(resolve(tk, "color.text.on-action"), over, 0.45)
        fill = blend(resolve(tk, "color.action.primary.default"), over, 0.45)
        composite[th] = round(contrast(label, fill), 2)
    out.append(
        f"validity composite (Place at opacity.disabled over the overlay; not gated): {composite}"
    )
    out.append("\n## 2. Token bindings (token | dark / light / hc)")
    missing = [tok for tok in BINDINGS if resolve(themes["dark"], tok) == "MISSING"]
    out += [
        f"{tok} | {' / '.join(resolve(tk, tok)[:40] for tk in themes.values())}" for tok in BINDINGS
    ]
    precedents = (
        "".join((DESIGN / p).read_text(encoding="utf-8") for p in GLYPH_PRECEDENTS) + t["15"]
    )
    glyphs_new = [g for g in GLYPHS if f"`{g}`" not in precedents]
    out.append(f"MISSING tokens: {missing} | glyph names no merged spec names yet: {glyphs_new}")
    facts = contract_facts(t)
    out.append("\n## 3-4. pairs.mjs status is per row above; contract facts parsed from text:")
    out.append(json.dumps(facts, ensure_ascii=False))
    spec = SPEC.read_text(encoding="utf-8")
    bad = gates([SPEC, HANDOFF, *extra], spec, facts, t)
    ok = (
        "OK — both OCO caveats, the outage notes, the banner leads and the halt words present "
        "verbatim; no retired word in the copy deck; every T2 reason within 60 characters; no "
        "private path; every C / CMP / SCR id exists; every cited text exists"
    )
    out.append("\n## 5. String gates: " + (ok if not bad else "\n".join("FAIL " + b for b in bad)))
    out += [f"WARN cited line drifted: {w}" for w in CITE_WARN]
    deck = section(spec, 13, 14)
    deck_rows = re.findall(r"^\| `[^`]+` +\| [^|]*\| ([^|]+?) +\|", deck, MULTI)
    by_source: dict[str, int] = {}
    for src in deck_rows:
        key = src.split(" ")[0].strip("`*")
        by_source[key] = by_source.get(key, 0) + 1
    reasons = [k for k, _ in re.findall(REASON_RE, deck, MULTI)]
    pausable = {
        "pausable_twap": BULK["twap"] - BULK["twap_price_blocked"] - BULK["finishing_twap"],
        "pausable_chase": BULK["chase"] - BULK["chase_parked"],
        "pausable_iceberg": BULK["iceberg"] - BULK["iceberg_cooling"] - BULK["finishing_iceberg"],
        "finishing": BULK["finishing_twap"] + BULK["finishing_iceberg"],
    }
    skipped = ("oco", "twap_price_blocked", "chase_parked")
    pausable["skipped"] = sum(BULK[k] for k in skipped) + pausable["finishing"]
    pausable["deferred"] = BULK["iceberg_cooling"]
    total = BULK["twap"] + BULK["chase"] + BULK["iceberg"] + BULK["oco"]
    pausable["pausable"] = sum(pausable[f"pausable_{k}"] for k in ("twap", "chase", "iceberg"))
    if pausable["pausable"] + pausable["deferred"] + pausable["skipped"] != total:
        bad.append("bulk fixture: paused + deferred + skipped does not reconcile to the total")
    if BULK["cancelled"] + BULK["failed"] != total or pausable["finishing"] + 1 != BULK["failed"]:
        bad.append("bulk fixture: the per-item result does not add up (finishing + 1 unanswered)")
    at_bybit = dict(AT_BYBIT)
    at_bybit["btc"] = round(sum(v for k, v in AT_BYBIT.items() if k != "orders"), 2)
    handoff = HANDOFF.read_text(encoding="utf-8") if HANDOFF.exists() else ""
    b4_states, statuses = list(facts["b4_states"]), list(facts["algo_state_status"])  # type: ignore[call-overload]
    numbers: dict[str, object] = {k: count(p, section(spec, a, b)) for k, a, b, p in COUNTS}
    numbers.update({k: count(rf"^\| D03-{p}\d+ ", spec) for k, p in ROW_IDS})
    numbers["frames_total"] = int(str(numbers["frames_069"])) + int(str(numbers["frames_076"]))
    numbers["bq_rows"] = count(r"^\| BQ-\d+ ", spec)
    numbers.update({"pairs_rows": gated, "pairs_registered": gated - proposed})
    numbers.update({"pairs_proposed": proposed, "pairs_fail": fails, "demo_badge_7_1": demo_7})
    numbers.update(
        {"composite": composite, "deck_rows": len(deck_rows), "deck_by_source": by_source}
    )
    numbers["opacity_disabled"] = float(resolve(themes["dark"], "opacity.disabled"))
    numbers.update({"deck_new": by_source.get("new", 0), "reason_keys": len(reasons)})
    numbers["reason_keys_proposed"] = sum(r.startswith("algo.") for r in reasons)
    numbers["checklist_items"] = count(r"^\| 14:(?:1584|1608|1475) ", spec)
    numbers["handoff_blocks"] = count(r"^## Handoff checklist", handoff)
    numbers.update({"missing_tokens": len(missing), "glyphs_new": len(glyphs_new)})
    numbers["banned_copy_words"] = len(BANNED_COPY)
    numbers["ages"] = {
        **AGES,
        "reconcile_interval_s": 30,
        "account_down_s": facts["cv_account_down_s"],
    }
    ms = {"cancel_timeout": facts["cancel_timeout_ms_default_22"], "confirm_gate": 400}
    numbers["ms"] = {**ms, "flash_max": 200, "sl_deadline_s": 2, "budget_scripting": 3}
    numbers["bulk"] = {**BULK, "total": total, **pausable}
    numbers.update({"rows": ROWS, "at_bybit": at_bybit, "fixture": FIXTURE})
    numbers.update({"b4_states": len(b4_states), "algo_state_status": len(statuses)})
    numbers["b8_states"] = len(list(facts["b8_states"]))  # type: ignore[call-overload]
    flat = flatten(numbers)
    if "--check" in argv:
        for key, val in re.findall(r"<!-- audit:([a-z0-9_.-]+)=([^ ]+) -->", spec):
            have = flat.get(key)
            same = str(have).lower() == val.lower()
            try:
                same = same or float(str(have)) == float(val)
            except ValueError:
                pass
            if have is None or not same:
                bad.append(f"marker audit:{key}={val} vs tool {have}")
        clean = not any(b.startswith("marker") for b in bad)
        out.append("markers: " + ("clean" if clean else "MISMATCH"))
    out.append("\n## 6. Counts: " + json.dumps(numbers, ensure_ascii=False))
    if "--json" in argv:
        palette = {th: {n: resolve(tk, n) for n in BINDINGS} for th, tk in themes.items()}
        payload = {"numbers": numbers, "matrix": matrix, "missing": missing, "facts": facts}
        payload.update({"problems": bad, "cite_warnings": CITE_WARN, "palette": palette})
        print(json.dumps(payload, ensure_ascii=False, indent=1))
    else:
        print("\n".join(out))
    return 1 if fails or bad else 0


if __name__ == "__main__":
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")
    sys.exit(main(sys.argv[1:]))
