#!/usr/bin/env python3
"""E36-D02 form-editor audit: measured matrix, token bindings, vocabulary counts, string gates.

Standalone, offline, stdlib only; it executes no repo code. It reads the token JSON, `pairs.mjs`,
`metrics.py`, `catalogue.py`, `ir/models.py`, the E36-D01 memo and `14` AS TEXT and prints, with a
source label on every row: (1) the WCAG 2.x ratio of every fg / bg pair SCR-081 and SCR-083 render
in dark / light / high-contrast (`themes.json` layering), against the role's bar, comparing the
UNROUNDED ratio as `tools/contrast/generate.mjs` does (a value that would round onto a bar prints
to four decimals); `rejected-*` and `decorative` rows are reported, never gated; (2) every token
the spec and the handoff bind, resolved or MISSING; (3) which pairs `pairs.mjs` registers (a text
scan of its `fg` / `bg` literals) and which are PROPOSED; (4) the vocabulary and IR counts the
boards quote; (5) the string gates — the #4118 string, the RULED lines, the two loosening sentences
#4137 supersedes (they must be absent), private paths; (6) the counts. Exit 1 on a gated FAIL or a
failed gate.

``--check SPEC`` runs the audit with SPEC as the spec under test and adds the section 0 gate:
"Boards as drawn", the page id, the ten drawn board ids with their export paths and PNG header
sizes, and the three not-drawn boards (03, 08, 11), each stated once; it prints ``N problem(s)``
and exits 1 on any. ``--self-test SPEC`` applies the gate's frame-level mutations to SPEC in
memory (the file is never written): each must raise exactly one new problem, and the clean spec
must pass before and after.

Usage: python3 -I docs/design/_tools/e36_d02_form_audit.py [--json] [--extra FILE ...]
       [--check SPEC] [--self-test SPEC]
"""

from __future__ import annotations

import json
import re
import struct
import sys
from pathlib import Path
from typing import TypedDict

ROOT = Path(__file__).resolve().parents[3]
TOKENS = ROOT / "packages" / "ui" / "tokens"
RULES = ROOT / "services" / "api" / "candleviewer" / "rules"
SPEC = ROOT / "docs" / "design" / "E36" / "E36-D02.md"
HANDOFF = ROOT / "docs" / "design" / "E36" / "E36-D02-handoff.md"
MEMO = ROOT / "docs" / "design" / "research" / "e36-rules-in-words.md"
CAT14 = ROOT / "docs" / "plan" / "14-screens-catalogue.md"
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
BAR: dict[str, float | None] = {"text": 4.5, "non-text": 3.0, "hc-text": 7.0}
NEW_STRING = "Turns itself off after 5 errors in a row — you re-arm it."
OLD_STRING = "Pauses itself after 5 errors."
RULED = ("The stop only ever tightens.", "Rules never loosen a stop.")  # memo Q2; #4137
# #4137 (a rule action never loosens a stop, for any role) supersedes these two sentences: the gate
# fails if either appears. Split so this file never contains the literals it forbids.
SUPERSEDED = (
    r"This rule may wid[e]n the stop — owner-only, audited\.",
    r"Only the owner can loos[e]n a stop\.",
)
# Private paths and hosts that never belong in a public file: generic patterns only — no personal
# word and no hostname, whole or split (the opener's gate owns those); the path literal is split so
# this file never contains the string it forbids.
FORBIDDEN = (
    r"/ho[m]e/",
    r"penpot\.[a-z0-9-]+\.[a-z]+",
    r"team-i[d]=",
    r"file-i[d]=",
)
MULTI = re.MULTILINE
# Shipped ids the `14` SCR-081 list names; None = no shipped id (memo C2).
PLAN_TO_ID: dict[str, str | None] = {
    "unrealized_r_multiple": "unrealised_r_multiple",
    "unrealized_pnl_pct": "unrealised_pnl_pct",
    "realized_pnl_today": "realised_pnl_today",
    "time_in_trade": "time_in_trade_ms",
    "orderbook_imbalance": None,
}
# The twelve templates' metric ids (spec section 10; memo section 2 rows 3-14).
TEMPLATE_METRICS = (
    ("T1", "unrealised_r_multiple"),
    ("T2", "position_open"),
    ("T2", "atr"),
    ("T3", "position_side"),
    ("T3", "swing_low"),
    ("T4", "unrealised_r_multiple"),
    ("T5", "time_in_trade_ms"),
    ("T5", "unrealised_r_multiple"),
    ("T6", "spread_bps"),
    ("T7", "daily_loss_pct"),
    ("T8", "tape_speed_zscore"),
    ("T9", "distance_to_liquidity_cluster"),
    ("T9", "position_side"),
    ("T10", "funding_rate"),
    ("T11", "time_to_funding_ms"),
    ("T11", "position_open"),
    ("T12", "book_pressure"),
    ("T12", "liquidity_pulled"),
)
RECORDED_INPUTS = frozenset({"trades", "book", "liquidations"})
# element | fg | bg | role  -- every pair the two screens draw (spec section 15, rows in order).
# A line indented by two spaces continues the record above it (no physical line passes 100).
PAIRS_TABLE = """
header title, sentence, row values | color.text.primary | color.surface.canvas | text
row fragments, option descriptions | color.text.secondary | color.surface.canvas | text
Last saved caption; the any-of bracket ink (n5) | color.text.tertiary | color.surface.canvas | text
cards, action-bar labels, dialog text | color.text.primary | color.surface.raised | text
T2 reason sentence, card body | color.text.secondary | color.surface.raised | text
T2 kept label (E09-D09) | color.text.tertiary | color.surface.raised | text
indicator 1 word | color.text.primary | color.status.success.subtle | text
indicator 1 glyph | color.status.success.strong | color.status.success.subtle | non-text
indicator 2 word, read-only card, warning banner
  | color.text.primary | color.status.warning.subtle | text
read-only card kicker (m5 fix) | color.text.secondary | color.status.warning.subtle | text
indicator 2 glyph, banner glyph
  | color.status.warning.strong | color.status.warning.subtle | non-text
indicator 3 word, DCR-11 banner | color.text.primary | color.status.danger.subtle | text
indicator 3 glyph (dark danger.strong = palette.amber.400)
  | color.status.danger.strong | color.status.danger.subtle | non-text
the banner's second line | color.text.secondary | color.status.danger.subtle | text
indicator 4 word, Checking, the DRAFT pill | color.text.primary | color.surface.hover | text
since your last save; the ? glyph | color.text.secondary | color.surface.hover | text
the invalid row's 2 px outline | color.status.danger.default | color.surface.canvas | non-text
the invalid row's outline on a card | color.status.danger.default | color.surface.raised | non-text
the CMP-227 word, CMP-158's sentence | color.text.primary | color.status.info.subtle | text
the chip's glyph and outline | color.status.info.default | color.status.info.subtle | non-text
focus ring on rows | color.focus.ring | color.surface.canvas | non-text
focus ring on cards and the action bar | color.focus.ring | color.surface.raised | non-text
focus ring on the read-only card | color.focus.ring | color.status.warning.subtle | non-text
focus ring on indicator 3 | color.focus.ring | color.status.danger.subtle | non-text
focus ring on indicator 1 | color.focus.ring | color.status.success.subtle | non-text
focus ring on the chip | color.focus.ring | color.status.info.subtle | non-text
the selected / current row outline | color.border.selected | color.surface.canvas | non-text
Save draft, Create draft | color.text.on-action | color.action.primary.default | text
Arm against LIVE (the destructive class) | color.text.on-action | color.status.danger.default | text
the selected template card | color.text.primary | color.surface.selected | text
the amber chip outline on canvas | color.status.warning.default | color.surface.canvas | non-text
the sentence in high contrast (claimed) | color.text.primary | color.surface.canvas | hc-text
m5: never drawn (kickers on amber use text.secondary)
  | color.text.tertiary | color.status.warning.subtle | rejected-text
n5: not the bracket ink | color.border.strong | color.surface.canvas | rejected-non-text
E09-D09 T2 keeps text.tertiary for a disabled label
  | color.text.disabled | color.surface.raised | rejected-text
the card hairline | color.border.default | color.surface.raised | decorative
"""
# Every token the spec and the handoff bind (sections 2-15); the last seven are the `15`
# entries' names that do not exist (expected MISSING, spec section 15 request 1).
BINDINGS = (
    "color.surface.canvas",
    "color.surface.raised",
    "color.surface.hover",
    "color.surface.overlay",
    "color.surface.selected",
    "color.surface.sunken",
    "color.text.primary",
    "color.text.secondary",
    "color.text.tertiary",
    "color.text.on-action",
    "color.action.primary.default",
    "color.focus.ring",
    "color.status.success.subtle",
    "color.status.success.strong",
    "color.status.warning.subtle",
    "color.status.warning.strong",
    "color.status.warning.default",
    "color.status.danger.subtle",
    "color.status.danger.strong",
    "color.status.danger.default",
    "color.status.info.subtle",
    "color.status.info.default",
    "color.border.selected",
    "color.border.default",
    "color.buy.default",
    "color.sell.default",
    "elevation.chrome",
    "elevation.card",
    "elevation.popover",
    "elevation.dialog",
    "radius.control",
    "radius.card",
    "radius.badge",
    "type.ui.heading-md",
    "type.ui.heading-sm",
    "type.ui.body",
    "type.ui.caption",
    "type.num.sm",
    "font.family.mono",
    "font.family.ui",
    "size.control.height",
    "size.row.height",
    "size.target.min",
    "size.icon.sm",
    "space.inset.sm",
    "space.inset.md",
    "space.inset.lg",
    "space.stack.md",
    "space.field.gap",
    "space.button.paddingX",
    "space.panel.padding",
    "border.thick",
    "border.focus",
    "motion.duration.instant",
    "space.3",
    "space.4",
    "elevation.2",
    "elevation.4",
    "font.mono",
    "color.border.invalid",
    "space.rulegroup.indent",
    "color.status.warn",
    "color.status.danger",
    "color.status.info",
    "color.chip.estimated",
)
PRIMITIVE_ALIAS = {"elevation.2": "elevation.popover", "elevation.4": "elevation.dialog"}


class Action(TypedDict):
    id: str
    title: str
    places_orders: bool
    loosens_risk: bool


class Vocab(TypedDict):
    descriptor_rows: int
    kernel_bound: int
    golden: int
    ids_match_golden: bool
    estimated: list[str]
    categories: dict[str, int]
    estimated_by_category: dict[str, int]
    longest_title: str
    longest_bound_title: str
    templates: list[str]
    plan_names: dict[str, str | None]
    actions: list[Action]
    destructive: list[str]
    triggers: list[str]
    operators: list[str]
    arity3: list[str]
    limits: list[tuple[str, str]]


def rows(table: str) -> list[list[str]]:
    """One record per line; a line indented by two spaces continues the record above it."""
    records: list[str] = []
    for ln in table.strip("\n").splitlines():
        if ln.startswith("  ") and records:
            records[-1] += " " + ln.strip()
        elif ln:
            records.append(ln.strip())
    return [[c.strip() for c in rec.split(" | ")] for rec in records]


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


def luminance(hex6: str) -> float:
    r, g, b = (int(hex6.lstrip("#")[i : i + 2], 16) / 255 for i in (0, 2, 4))
    lin = [c / 12.92 if c <= 0.03928 else ((c + 0.055) / 1.055) ** 2.4 for c in (r, g, b)]
    return 0.2126 * lin[0] + 0.7152 * lin[1] + 0.0722 * lin[2]


def contrast(a: str, b: str) -> float:
    la, lb = luminance(a), luminance(b)
    return (max(la, lb) + 0.05) / (min(la, lb) + 0.05)


def show(ratio: float) -> str:
    near = any(abs(ratio - bar) < 0.005 for bar in (3.0, 4.5, 7.0))
    return f"{ratio:.4f}" if near else f"{ratio:.2f}"


def split_args(s: str) -> list[str]:
    """Split a Python call's argument text at depth-0 commas (quotes and brackets respected)."""
    out: list[str] = []
    depth, quote, cur = 0, "", ""
    for ch in s:
        if quote:
            quote = "" if ch == quote else quote
        elif ch in "\"'":
            quote = ch
        elif ch in "([{":
            depth += 1
        elif ch in ")]}":
            depth -= 1
        elif ch == "," and depth == 0:
            out.append(cur.strip())
            cur = ""
            continue
        cur += ch
    return [*out, cur.strip()] if cur.strip() else out


def vocabulary() -> Vocab:
    text = (RULES / "vocabulary" / "metrics.py").read_text(encoding="utf-8")
    inputs = {"_T": "trades", "_B": "book", "_R": "bars"}
    row_re = re.compile(
        r'^\s*\("([a-z0-9_]+)", "([^"]+)", "[^"]+", (_T|_B|_R|"[a-z]+"), "[^"]*", \d+, '
        r'(_E|_S), "([a-z]+)",',
        MULTI,
    )
    descr = [
        (m[1], m[2], inputs.get(m[3], m[3].strip('"')), m[4] == "_S", m[5])
        for m in row_re.finditer(text)
    ]
    bound_re = re.compile(
        r'^\s*\("([a-z0-9_]+)", "[a-z_]+", "[a-z_]+", "([^"]+)", (_TAPE|_NO_TAPE),', MULTI
    )
    bound = [(m[1], m[2], m[3] == "_TAPE") for m in bound_re.finditer(text)]
    golden = (RULES / "vocabulary" / "metric_names.golden.txt").read_text(encoding="utf-8").split()
    names = ("price", "orderflow", "book", "derivatives", "position", "account", "replay")
    cats: dict[str, list[str]] = {k: [] for k in names}
    est: dict[str, list[str]] = {k: [] for k in names}
    by_scope = {"global": "replay", "account": "account", "position": "position"}
    by_input = {"bars": "price", "trades": "orderflow", "book": "book"}
    for name, _title, inp, is_est, scope in descr:
        cat = by_scope.get(scope) or by_input.get(inp, "derivatives")
        cats[cat].append(name)
        if is_est:
            est[cat].append(name)
    for name, _title, tape in bound:
        cats["orderflow" if tape else "price"].append(name)
    cat_text = (RULES / "vocabulary" / "catalogue.py").read_text(encoding="utf-8")
    actions: list[Action] = []
    for m in re.finditer(r"ActionSpec\((.*)\),\s*$", cat_text, MULTI):
        a = [*split_args(m[1]), *[""] * 9]
        actions.append(
            Action(
                id=a[0].strip('"'),
                title=a[1].strip('"'),
                places_orders=a[4] == "True",
                loosens_risk=a[8] == "True",
            )
        )
    triggers = re.findall(r'^\s*"(on_[a-z_]+|pre_trade_check)": \("', cat_text, MULTI)
    ops = re.findall(r"for op in \(([^)]*)\)", cat_text)[0].replace('"', "").split(", ")
    ops += re.findall(r'^\s*"([a-z_]+)": \(\d, ', cat_text, MULTI)
    models = (RULES / "ir" / "models.py").read_text(encoding="utf-8")
    block = models[models.index("class RuleLimits") : models.index("class Rule(")]
    titles = {n: t for n, t, *_ in descr} | {n: t for n, t, _ in bound}
    conf = {n: "estimated" if e else "exact" for n, _t, _i, e, _s in descr}
    inputs_of = {n: {i} for n, _t, i, _e, _s in descr}
    inputs_of |= {n: ({"bars", "trades"} if tp else {"bars"}) for n, _t, tp in bound}
    templates = [
        f"{t} {m} ({titles.get(m, '?')}) {conf.get(m, 'exact')} "
        f"{sorted(inputs_of.get(m, set()) & RECORDED_INPUTS) or 'none'}"
        for t, m in TEMPLATE_METRICS
    ]
    destructive = {a["id"] for a in actions if a["places_orders"] or a["id"].startswith("flatten_")}
    return Vocab(
        descriptor_rows=len(descr),
        kernel_bound=len(bound),
        golden=len(golden),
        ids_match_golden=sorted(n for v in cats.values() for n in v) == sorted(golden),
        estimated=sorted(n for v in est.values() for n in v),
        categories={k: len(v) for k, v in cats.items()},
        estimated_by_category={k: len(v) for k, v in est.items()},
        longest_title=max((t for _n, t, *_ in descr), key=len),
        longest_bound_title=max((t for _n, t, _tp in bound), key=len),
        templates=templates,
        plan_names={k: (None if v is None else titles.get(v, "?")) for k, v in PLAN_TO_ID.items()},
        actions=actions,
        destructive=sorted(destructive),
        triggers=triggers,
        operators=sorted(set(ops)),
        arity3=re.findall(r'^\s*"([a-z_]+)": \(3, ', cat_text, MULTI),
        limits=re.findall(r"^\s{4}([a-z_]+):.*?= (\S+)$", block, MULTI),
    )


# Section 0 gate: the ten boards of the cap of ten, their ids, and the three not drawn.
PAGE_ID = "a3e246e9-1c1d-806b-8008-da9df49a8b99"
DRAWN = {
    "01": "a3e246e9-1c1d-806b-8008-da9e3717228c",
    "02": "8bea9290-daa1-806c-8008-da9ecf9475d9",
    "04": "2816592d-1b32-804f-8008-da9fa1ac9250",
    "05": "761d762c-1e4d-80a6-8008-daa049a2dea5",
    "06": "662e5072-b589-8072-8008-daa0e25ce682",
    "07": "8aa80863-d01a-80b6-8008-daa178a95404",
    "09": "44b0d201-b3b5-806e-8008-daa2137aa57a",
    "10": "e5e21895-0fbc-80a7-8008-daa2afe14f41",
    "12": "cc9877da-ad62-8019-8008-daa447ebc82d",
    "13": "78465431-b6e8-80c7-8008-daa34500470f",
}
NOT_DRAWN = ("03", "08", "11")
BOARD_LINE = re.compile(
    r"^- `E36-D02-(\d\d)-([a-z0-9-]+)` — board id `([0-9a-f-]{36})` — `([^`]+)` \((\d+) × (\d+)\)$",
    MULTI,
)


def png_size(path: Path) -> tuple[int, int] | None:
    try:
        head = path.read_bytes()[:24]
    except OSError:
        return None
    if head[:8] != b"\x89PNG\r\n\x1a\n":
        return None
    w, h = struct.unpack(">II", head[16:24])
    return w, h


def boards_problems(spec: str, root: Path = ROOT) -> list[str]:
    """Section 0 gate on the spec text; the PNG header sizes are read from disk."""
    bad: list[str] = []
    if "## 0." not in spec or "## 1." not in spec:
        return ["FAIL section 0 not found"]
    sec = spec[spec.index("## 0.") : spec.index("## 1.")]
    if "Boards as drawn (exported" not in sec:
        bad.append("FAIL section 0 does not list the boards as drawn")
    if sec.count(PAGE_ID) != 1:
        bad.append("FAIL section 0 does not name the page id exactly once")
    found = {m[1]: m for m in BOARD_LINE.finditer(sec)}
    for n, bid in DRAWN.items():
        m = found.get(n)
        if m is None:
            bad.append(f"FAIL board {n} is not listed as drawn")
            continue
        if m[3] != bid:
            bad.append(f"FAIL board {n} id differs from the drawn id")
        size = png_size(root / m[4])
        if size is None:
            bad.append(f"FAIL board {n} export {m[4]} is missing or not a PNG")
        elif size != (int(m[5]), int(m[6])):
            bad.append(f"FAIL board {n} size {m[5]} x {m[6]} differs from the PNG header {size}")
    for n in NOT_DRAWN:
        if n in found:
            bad.append(f"FAIL board {n} is listed as drawn")
    if "not drawn (capped)" not in sec.lower() or "boards 03" not in sec:
        bad.append("FAIL section 0 does not mark boards 03, 08 and 11 not drawn (capped)")
    return bad


# name -> (old, new): each must raise exactly one new problem.
MUTATIONS: tuple[tuple[str, str, str], ...] = (
    (
        "section 0 no longer records the boards as drawn",
        "Boards as drawn (exported",
        "Boards as planned (exported",
    ),
    ("board 12 dropped from the drawn list", "- `E36-D02-12-themes", "- `E36-D02-XX-themes"),
    (
        "board 07 id altered",
        "board id `8aa80863-d01a-80b6-8008-daa178a95404`",
        "board id `8aa80863-d01a-80b6-8008-daa178a95405`",
    ),
    ("board 01 size altered", "(1984 × 1930)", "(1984 × 1931)"),
    ("the page id removed", f"page id `{PAGE_ID}`; boards 01", "boards 01"),
    ("not-drawn (capped) mark removed", "**Not drawn (capped):**", "**Not drawn:**"),
)


def self_test(spec_path: Path) -> int:
    spec = spec_path.read_text(encoding="utf-8")
    before = len(boards_problems(spec))
    ok = before == 0
    print(f"clean spec before: {before} problem(s)")
    for name, old, new in MUTATIONS:
        if spec.count(old) != 1:
            print(f"FAIL mutation `{name}`: the needle occurs {spec.count(old)} times")
            ok = False
            continue
        n = len(boards_problems(spec.replace(old, new)))
        print(f"{'ok' if n == 1 else 'FAIL'} mutation `{name}`: {n} new problem(s)")
        ok = ok and n == 1
    after = len(boards_problems(spec_path.read_text(encoding="utf-8")))
    print(f"clean spec after: {after} problem(s)")
    print(f"--self-test: {'ok' if ok and after == 0 else 'FAILED'} - {len(MUTATIONS)} mutations")
    return 0 if ok and after == 0 else 1


def gates(files: list[Path]) -> list[str]:
    bad: list[str] = []
    constitution = (ROOT / "CONSTITUTION.md").read_text(encoding="utf-8")
    for f in files:
        t = f.read_text(encoding="utf-8")
        if NEW_STRING not in t:
            bad.append(f"{f.name}: the #4118 string is missing")
        if OLD_STRING in t:
            bad.append(f"{f.name}: the old kill-switch string is present")
        bad += [f"{f.name}: RULED string missing: {s}" for s in RULED if s not in t]
        bad += [
            f"{f.name}: superseded loosening sentence (#4137) {p}"
            for p in SUPERSEDED
            if re.search(p, t)
        ]
        bad += [f"{f.name}: forbidden text {p}" for p in FORBIDDEN if re.search(p, t)]
        cited = sorted(set(re.findall(r"\bC-\d+\.\d+\b", t)))
        bad += [f"{f.name}: dangling rule id {r}" for r in cited if r not in constitution]
    return bad


def main(argv: list[str]) -> int:
    global SPEC
    if "--self-test" in argv:
        return self_test(Path(argv[argv.index("--self-test") + 1]))
    checking = "--check" in argv
    if checking:
        SPEC = Path(argv[argv.index("--check") + 1])
    extra = [Path(a) for a in argv[argv.index("--extra") + 1 :]] if "--extra" in argv else []
    themes = {k: load_theme(k) for k in THEMES}
    pairs_text = (ROOT / "tools" / "contrast" / "pairs.mjs").read_text(encoding="utf-8")
    registered = set(re.findall(r'fg:\s*"([^"]+)",\s*bg:\s*"([^"]+)"', pairs_text))
    out = ["## 1. Measured matrix (fg on bg | role | dark / light / hc | verdict | pairs | where)"]
    matrix: list[dict[str, object]] = []
    fails = proposed = gated = 0
    for element, fg, bg, role in rows(PAIRS_TABLE):
        ratios = {th: contrast(resolve(t, fg), resolve(t, bg)) for th, t in themes.items()}
        bar = BAR.get(role)
        if bar is None:
            verdict = "reported, not gated" if role == "decorative" else "rejected, never drawn"
        else:
            gated += 1
            verdict = "PASS" if all(r >= bar for r in ratios.values()) else "FAIL"
            fails += verdict == "FAIL"
            proposed += (fg, bg) not in registered
        reg = "registered" if (fg, bg) in registered else "PROPOSED"
        matrix.append({"fg": fg, "bg": bg, "role": role, "verdict": verdict, "pairs": reg})
        matrix[-1].update({k: round(v, 4) for k, v in ratios.items()})
        shown = " / ".join(show(r) for r in ratios.values())
        out.append(f"{fg} on {bg} | {role} | {shown} | {verdict} | {reg} | {element} (spec 15)")
    out.append("\n## 2. Token bindings (token | dark / light / hc)")
    missing: list[str] = []
    for token in BINDINGS:
        vals = [resolve(t, token)[:40] for t in themes.values()]
        if token in PRIMITIVE_ALIAS:
            vals = [f"primitive; alias {PRIMITIVE_ALIAS[token]}"]
        if vals[0] == "MISSING":
            missing.append(token)
        out.append(f"{token} | {' / '.join(vals)}")
    counts = {
        f: sum("$value" in v for v in json.loads((TOKENS / f).read_text(encoding="utf-8")).values())
        for f in (PRIM, DARK, LIGHT, HC)
    }
    out.append(f"token files: {counts} | MISSING: {missing}")
    voc = vocabulary()
    memo = MEMO.read_text(encoding="utf-8")
    summaries = re.findall(r"^\| (S[123]) +\| (.+?) +\| [^|]+\| +(\d+) +\|$", memo, MULTI)
    words = [(s, len(txt.split()), int(n)) for s, txt, n in summaries]
    cat14 = CAT14.read_text(encoding="utf-8")
    sp = re.search(r"Starting points: (.+?)\.\n", cat14[cat14.index("### SCR-083") :])
    templates_14 = [n.strip() for n in sp[1].split(";")] if sp else []
    out.append(
        f"\n## 3. pairs.mjs: {len(registered)} registered; {gated} gated rows, {proposed} PROPOSED"
    )
    out.append("\n## 4. Vocabulary and IR counts (parsed from the shipped text)")
    out.append(
        f"descriptor rows {voc['descriptor_rows']} + kernel-bound {voc['kernel_bound']} (inputs "
        f"from the tape flag, not the indicator catalogue) = golden {voc['golden']}: "
        + ("reconciled" if voc["ids_match_golden"] else "MISMATCH")
    )
    out.append(f"estimated ids ({len(voc['estimated'])}): {', '.join(voc['estimated'])}")
    out.append(
        f"categories derived (scope + input): {voc['categories']} | memo section 5.2: "
        f"13 / 41 / 16 / 11 / 13 / 8 / 3 | estimated by category: {voc['estimated_by_category']}"
    )
    out.append(
        f"longest title: '{voc['longest_title']}' ({len(voc['longest_title'])} characters); "
        f"longest kernel-bound title: '{voc['longest_bound_title']}'"
    )
    out.append("templates -> confidence / recorded inputs: " + "; ".join(voc["templates"]))
    out.append(f"14 plan names -> shipped display_name: {voc['plan_names']}")
    flags = {True: " places_orders", False: ""}
    out.append(
        f"actions {len(voc['actions'])}: "
        + ", ".join(f"{a['id']} '{a['title']}'{flags[a['places_orders']]}" for a in voc["actions"])
    )
    out.append(
        f"destructive class (PROPOSED rule: places_orders | flatten_*; widen_stop left it, #4137) "
        f"{len(voc['destructive'])}: {', '.join(voc['destructive'])}"
    )
    out.append(
        f"triggers {len(voc['triggers'])}: {', '.join(voc['triggers'])} | operators "
        f"{len(voc['operators'])} (arity 3: {', '.join(voc['arity3'])})"
    )
    limits = ", ".join(f"{n}={d}" for n, d in voc["limits"])
    out.append(f"RuleLimits {len(voc['limits'])}: {limits}")
    out.append(f"memo S1-S3 (id, counted, stated): {words} | 14 templates: {len(templates_14)}")
    out.append("\n## 5. String gates")
    bad = gates([SPEC, HANDOFF, *extra])
    if memo.count(NEW_STRING) != 3 or OLD_STRING in memo:
        bad.append(f"memo strings: {memo.count(NEW_STRING)} new / {memo.count(OLD_STRING)} old")
    ok = (
        "OK — #4118 string present, old string absent, RULED strings present, "
        "no superseded loosening sentence, no private path"
    )
    out.append(ok if not bad else "\n".join("FAIL " + b for b in bad))
    spec, hand = SPEC.read_text(encoding="utf-8"), HANDOFF.read_text(encoding="utf-8")
    sec0 = spec[spec.index("## 0.") : spec.index("## 1.")]
    sec16 = spec[spec.index("## 16.") : spec.index("## 17.")]
    sec20 = spec[spec.index("## 20.") :]
    blank = re.findall(r"^- \[[ x~]\] \*\*[^*]+\*\*\s*$", hand, MULTI)
    numbers: dict[str, object] = {
        "states": 6,
        "indicator_states": 4,
        "boards": len(re.findall(r"^\| \d\d +\| `", sec0, MULTI)),
        "templates": len(templates_14),
        "categories": len(voc["categories"]),
        "operators": len(voc["operators"]),
        "actions": len(voc["actions"]),
        "triggers": len(voc["triggers"]),
        "limits": len(voc["limits"]),
        "estimated": len(voc["estimated"]),
        "pairs_rows": gated,
        "pairs_registered": gated - proposed,
        "pairs_proposed": proposed,
        "pairs_fail": fails,
        "c_rows": len(re.findall(r"^\| D02-C\d+ +\|", sec20, MULTI)),
        "g_rows": len(re.findall(r"^\| D02-G\d+ +\|", sec20, MULTI)),
        "q_rows": len(re.findall(r"^\| (?:BQ-\d+|D02-Q\d+) +\|", sec20, MULTI)),
        "handoff_blocks": len(re.findall(r"^## Handoff checklist — ", hand, MULTI)),
        "amendment_rows": len(re.findall(r"^\| CMP-\d+ +\|", sec16, MULTI)),
        "destructive": len(voc["destructive"]),
        "longest_title_len": len(voc["longest_title"]),
        "missing_tokens": len(missing),
        "blank_checklist_lines": len(blank),
        "summary_words": [w for _s, w, _n in words],
    }
    out.append("\n## 6. Counts: " + json.dumps(numbers))
    board_bad = boards_problems(spec) if checking else []
    if checking:
        out.extend(board_bad)
        out.append(f"\n--check: {len(bad) + len(board_bad)} problem(s)")
    if "--json" in argv:
        voc_json = {k: v for k, v in voc.items() if k != "actions"}
        payload = {"numbers": numbers, "matrix": matrix, "missing": missing, "vocabulary": voc_json}
        print(json.dumps(payload, ensure_ascii=False, indent=1))
    else:
        print("\n".join(out))
    return 1 if fails or bad or blank or board_bad else 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
