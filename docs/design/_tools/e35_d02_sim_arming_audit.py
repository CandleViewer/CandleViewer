#!/usr/bin/env python3
"""E35-D02 simulation-panel and arming-dialog audit: matrix, bindings, shipped facts, copy gates.

Standalone, offline, stdlib only; it executes no repo code. It reads the token JSON, `pairs.mjs`,
`arming.py`, `rules_crud.py`, `b09_rule_instance.py`, `keymap.json`, `22`, `23`, `24`, the E35-D01
memo and the spec AS TEXT and prints, with a source label on every row: (1) the WCAG 2.x ratio of
every fg / bg pair SCR-084 and SCR-085 render in dark / light / high-contrast (`themes.json`
layering) against the role's bar — `rejected-*`, `decorative` and `composite` rows are reported,
never gated; (2) every token the spec and the handoff bind, resolved or MISSING; (3) which pairs
`pairs.mjs` registers (a text scan of its `fg` / `bg` literals) and which are PROPOSED; (4) the
shipped facts the boards quote, parsed from file text; (5) the copy gates — the memo's `unchanged`
and `binding-pending-owner` rows byte-for-byte, the two required sentences, the #4118 string, the
forbidden UI words, private paths, dangling `C-x.y` / `CMP-nnn` / `SCR-nnn` ids, and the standing
rule "no path arms LIVE without the `22` step-up" over the spec's section 4 classification table,
section 5 frame table and section 8 copy deck (`live_step_up`); (6) the counts. `--check` re-derives
every `<!-- audit:NAME=VALUE -->` marker in the spec. `--selftest` runs `live_step_up` on the spec
and on mutated copies of it held in memory (an armed frame moved ahead of the hand-off, SCR-006
dropped from the hand-off, the override drawn for DEMO only, a LIVE arm without the hand-off, the
LIVE override inset alone relabelled DEMO): the spec must pass and every mutation must fail. Exit 1 on a gated FAIL or a mutation that passes.

Usage: python3 -I docs/design/_tools/e35_d02_sim_arming_audit.py [--json] [--check] [--selftest]
       [--extra F ...]
"""

from __future__ import annotations

import json
import re
import sys
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[3]
TOKENS = ROOT / "packages" / "ui" / "tokens"
API = ROOT / "services" / "api" / "candleviewer"
PLAN = ROOT / "docs" / "plan"
SPEC = ROOT / "docs" / "design" / "E35" / "E35-D02.md"
HANDOFF = ROOT / "docs" / "design" / "E35" / "E35-D02-handoff.md"
MEMO = ROOT / "docs" / "design" / "research" / "e35-rule-arming-trust.md"
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
MULTI = re.MULTILINE
REQUIRED = (
    (
        "Simulation replays recorded market data. Fills are modelled, not real; results are not a "
        "guarantee."
    ),
    "If the backend stops, this rule stops. Native stops stay.",
)
NEW_STRING = "Turns itself off after 5 errors in a row — you re-arm it."
OLD_STRING = "Pauses itself after 5 errors."
OWNER_ONLY = "Only the owner can arm rules against live."
# Words the UI copy (spec section 8) never carries (memo SC-1, SC-12, SC-15, section 7).
BANNED_UI = ("backtest", "Type ARM", "emulated stop", "Panic", "triggered")
# Private paths and hosts never belong in a public file: generic patterns only — no personal word
# and no hostname; the path literal is split so this file never contains the string it forbids.
FORBIDDEN = (
    r"/(?:ho" + r"me|Users)/[^/\s]+/",
    r"penpot\.[a-z0-9-]+\.[a-z]{2,}",
    r"team-i" + r"d=",
    r"file-i" + r"d=",
)
# element | fg | bg | role — every pair the two screens draw (spec section 10, rows in order).
PAIRS_TABLE = """
dialog title, restatement, option words | color.text.primary | color.surface.overlay | text
dialog second lines, the validity reason | color.text.secondary | color.surface.overlay | text
drawer title, summary values, table text | color.text.primary | color.surface.raised | text
drawer captions, T2 reason sentence | color.text.secondary | color.surface.raised | text
T2 label + lock (LIVE option, Run, Arm) | color.text.tertiary | color.surface.raised | text
timeline rows on the canvas | color.text.primary | color.surface.canvas | text
timeline captions on the canvas | color.text.secondary | color.surface.canvas | text
the band's DEMO / LIVE word | color.text.primary | color.surface.app | text
DEMO / LIVE option word (7:1, memo 9d A7) | color.text.primary | color.surface.raised | hc-text
DEMO glyph and 2 px pill border | color.env.demo | color.surface.raised | non-text
LIVE glyph and 2 px pill border | color.env.live | color.surface.raised | non-text
DEMO pill border on the dialog | color.env.demo | color.surface.overlay | non-text
LIVE pill border on the dialog | color.env.live | color.surface.overlay | non-text
selected radio ring | color.action.primary.default | color.surface.overlay | non-text
Arm on DEMO, Run simulation (primary) | color.text.on-action | color.action.primary.default | text
Arm on LIVE… (the destructive class) | color.text.on-action | color.status.danger.default | text
coverage line, gate strip (amber) | color.text.primary | color.status.warning.subtle | text
coverage second line | color.text.secondary | color.status.warning.subtle | text
coverage glyph | color.status.warning.strong | color.status.warning.subtle | non-text
refusal line (T4), failed state | color.text.primary | color.status.danger.subtle | text
refusal glyph | color.status.danger.strong | color.status.danger.subtle | non-text
CMP-158 sentence, estimated chip word | color.text.primary | color.status.info.subtle | text
CMP-158 glyph | color.status.info.strong | color.status.info.subtle | non-text
estimated chip outline | color.status.info.default | color.status.info.subtle | non-text
Armed glyph on the dialog | color.status.success.strong | color.surface.overlay | non-text
Not armed glyph on the dialog | color.status.danger.strong | color.surface.overlay | non-text
partial glyph on the drawer | color.status.warning.strong | color.surface.raised | non-text
gate-strip done glyph | color.status.success.strong | color.surface.raised | non-text
the Open the simulation link | color.text.link | color.surface.overlay | text
progress fill on the drawer | color.action.primary.default | color.surface.raised | non-text
focus ring on the dialog | color.focus.ring | color.surface.overlay | non-text
focus ring on the drawer | color.focus.ring | color.surface.raised | non-text
focus ring halo (E30-D02 D3 double ring) | color.focus.ring | color.surface.canvas | non-text
the dialog in high contrast (claimed) | color.text.primary | color.surface.overlay | hc-text
ring on the primary fill | color.focus.ring | color.action.primary.default | rejected-non-text
ring on the danger fill (never) | color.focus.ring | color.status.danger.default | rejected-non-text
E09-D09 T2 keeps text.tertiary (never) | color.text.disabled | color.surface.raised | rejected-text
the card hairline | color.border.default | color.surface.raised | decorative
the dialog hairline | color.border.default | color.surface.overlay | decorative
"""
# Every token the spec and the handoff bind (sections 2 to 10); the last three are the `15`
# entries' names that do not exist (expected MISSING, spec section 10 request 1).
BINDINGS = (
    "color.surface.app", "color.surface.canvas", "color.surface.raised", "color.surface.overlay",
    "color.surface.hover", "color.surface.selected", "color.surface.sunken",
    "color.text.primary", "color.text.secondary", "color.text.tertiary", "color.text.on-action",
    "color.text.link", "color.action.primary.default", "color.focus.ring", "color.border.default",
    "color.border.selected", "color.status.success.subtle", "color.status.success.strong",
    "color.status.warning.subtle", "color.status.warning.strong", "color.status.danger.subtle",
    "color.status.danger.strong", "color.status.danger.default", "color.status.info.subtle",
    "color.status.info.strong", "color.status.info.default", "color.env.demo", "color.env.live",
    "opacity.disabled", "elevation.chrome", "elevation.dialog", "radius.control", "radius.card",
    "radius.badge", "radius.pill", "type.ui.heading-md", "type.ui.heading-sm", "type.ui.body",
    "type.ui.caption", "type.ui.label", "type.num.sm", "font.family.mono", "size.control.height",
    "size.row.height", "size.target.min", "size.icon.sm", "space.inset.sm", "space.inset.md",
    "space.inset.lg", "space.stack.md", "space.field.gap", "space.button.paddingX",
    "motion.duration.instant", "motion.duration.normal", "motion.duration.fast",
    "elevation.4", "color.track", "color.action.primary",
)  # fmt: skip
PRIMITIVE_ALIAS = {"elevation.4": "elevation.dialog"}
# the specimen tokens whose Rec. 601 luma the greyscale strip (board 09) prints
LUMA_TOKENS = (
    "color.surface.raised", "color.surface.overlay", "color.text.primary", "color.text.secondary",
    "color.text.tertiary", "color.env.demo", "color.env.live", "color.status.success.strong",
    "color.status.danger.strong", "color.status.warning.strong", "color.status.danger.default",
    "color.action.primary.default",
)  # fmt: skip


def rows(table: str) -> list[list[str]]:
    return [[c.strip() for c in ln.split(" | ")] for ln in table.strip("\n").splitlines() if ln]


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


def rgb(hex6: str) -> tuple[float, float, float]:
    r, g, b = (int(hex6.lstrip("#")[i : i + 2], 16) for i in (0, 2, 4))
    return r, g, b


def luminance(hex6: str) -> float:
    lin = [
        c / 12.92 if c <= 0.03928 else ((c + 0.055) / 1.055) ** 2.4
        for c in (v / 255 for v in rgb(hex6))
    ]
    return 0.2126 * lin[0] + 0.7152 * lin[1] + 0.0722 * lin[2]


def contrast(a: str, b: str) -> float:
    la, lb = luminance(a), luminance(b)
    return (max(la, lb) + 0.05) / (min(la, lb) + 0.05)


def composite(top: str, under: str, alpha: float) -> str:
    """`top` at `alpha` over `under`, as the validity look dims a control (E30-D02 D3)."""
    t, u = rgb(top), rgb(under)
    return "#" + "".join(
        f"{round(a * alpha + b * (1 - alpha)):02X}" for a, b in zip(t, u, strict=True)
    )


def luma601(hex6: str) -> int:
    r, g, b = rgb(hex6)
    return int(0.299 * r + 0.587 * g + 0.114 * b)


def show(ratio: float) -> str:
    near = any(abs(ratio - bar) < 0.005 for bar in (3.0, 4.5, 7.0))
    return f"{ratio:.4f}" if near else f"{ratio:.2f}"


def arming_messages() -> list[tuple[str, int, str]]:
    """Every `Refusal(code, status, message)` in `arming.py`, its f-string fills as the defaults."""
    text = (API / "rules" / "arming.py").read_text(encoding="utf-8")
    fires = re.search(r"DEFAULT_MIN_SIMULATION_FIRES = (\d+)", B09.read_text(encoding="utf-8"))
    hours = re.search(r"DEFAULT_MIN_SIMULATION_HOURS = ([\d.]+)", B09.read_text(encoding="utf-8"))
    out: list[tuple[str, int, str]] = []
    for m in re.finditer(r'Refusal\(\s*"([a-z_]+)",\s*(\d+),\s*((?:f?"[^"]*"\s*\+?\s*)+)', text):
        msg = "".join(re.findall(r'"([^"]*)"', m[3]))
        msg = msg.replace("{f.min_fires}", fires[1] if fires else "?")
        msg = msg.replace("{f.min_hours:g}", f"{float(hours[1]):g}" if hours else "?")
        msg = msg.strip()
        out.append(
            (m[1], int(m[2]), msg[:-1].rstrip() + " {accounts}." if msg.endswith(",") else msg)
        )
    return out


B09 = API / "statechart" / "bindings" / "b09_rule_instance.py"


def grab(pattern: str, text: str) -> str:
    m = re.search(pattern, text)
    if m is None:
        raise SystemExit(f"pattern not found: {pattern}")
    return m[1]


def shipped() -> dict[str, Any]:
    crud = (API / "api" / "rules_crud.py").read_text(encoding="utf-8")
    keys_m = re.search(r"set\(body\)\s*-\s*\{([^}]*)\}", crud)
    accepted = re.findall(r'"([a-z_]+)"', keys_m[1]) if keys_m else []
    api22 = (PLAN / "22-api-openapi.yaml").read_text(encoding="utf-8")
    mode = api22[api22.index("operationId: setRuleMode") :]
    body = mode[mode.index("requestBody:") : mode.index("responses:")]
    props = re.findall(r"^\s{16}([a-z_]+):", body, MULTI)
    sim = api22[api22.index("operationId: simulateRule") : api22.index("operationId: setRuleMode")]
    ex = {
        k: int(v)
        for k, v in re.findall(r"(evaluations|fires|suppressed_by_guard|duration_ms): (\d+)", sim)
    }
    run_status = re.search(r"RuleRunStatus:\s*\{ type: string, enum: \[([^\]]+)\]", api22)
    result = api22[api22.index("    RuleSimulationResult:") : api22.index("    RuleRun:")]
    ws = (PLAN / "23-ws-protocol.md").read_text(encoding="utf-8")
    upd = ws[ws.index("### 15.6 `RuleUpdate`") : ws.index("### 15.7")]
    upd = upd[: upd.index('"events"')]
    update_props = re.findall(r'^\s{10}"([a-z_0-9]+)": \{', upd, MULTI)
    schemas = (PLAN / "24-internal-schemas.md").read_text(encoding="utf-8")
    cfg = schemas[schemas.index("class RuleEngineConfig") :][:600]
    keymap = (ROOT / "apps" / "web" / "src" / "keymap" / "keymap.json").read_text(encoding="utf-8")
    b09 = B09.read_text(encoding="utf-8")
    fires = re.search(r"DEFAULT_MIN_SIMULATION_FIRES = (\d+)", b09)
    hours = re.search(r"DEFAULT_MIN_SIMULATION_HOURS = ([\d.]+)", b09)
    audit24 = re.search(r"### 15.5 Audited action vocabulary.*?\n\n(.*?)\n\n", schemas, re.DOTALL)
    audited = re.findall(r"`(rule\.[a-z_]+)`", audit24[1]) if audit24 else []
    return {
        "arming": [{"code": c, "status": s, "message": m} for c, s, m in arming_messages()],
        "crud_accepted": accepted,
        "setRuleMode_body": props,
        "simulate_example": ex,
        "run_status": [s.strip() for s in run_status[1].split(",")] if run_status else [],
        "simulation_result_props": re.findall(r"^\s{8}([a-z_]+):", result, MULTI),
        "rule_update_props": update_props,
        "b09_defaults": {
            "fires": int(fires[1]) if fires else None,
            "hours": float(hours[1]) if hours else None,
        },
        "config_defaults": {
            "fires": int(grab(r"min_simulation_fires: int = (\d+)", cfg)),
            "hours": int(grab(r"min_simulation_hours: int = (\d+)", cfg)),
        },
        "rules_commands": sorted(set(re.findall(r'"(rules\.[a-z_]+)"', keymap))),
        "audited_rule_keys": audited,
    }


def memo_copy() -> dict[str, tuple[str, list[str]]]:
    """CA id -> (status, the quoted strings of its Proposed column — Plan when unchanged)."""
    out: dict[str, tuple[str, list[str]]] = {}
    for m in re.finditer(
        r"^\| (CA-\d+b?) +\| [^|]+\| (.*?) +\| (.*?) +\| ([a-z-]+(?: \(E3[67][^)]*\))?) +\| ",
        MEMO.read_text(encoding="utf-8"),
        MULTI,
    ):
        status = m[4].split(" ")[0]
        col = m[2] if status == "unchanged" else m[3]
        out[m[1]] = (status, re.findall(r'"([^"]+)"', col))
    return out


def spec_sections(spec: str) -> dict[str, str]:
    heads = [(m.start(), m[1]) for m in re.finditer(r"^## (\d+)\.", spec, MULTI)]
    out: dict[str, str] = {}
    for i, (pos, n) in enumerate(heads):
        out[n] = spec[pos : heads[i + 1][0] if i + 1 < len(heads) else len(spec)]
    return out


HAND_OFF = "SCR-006 / no-grace-live-enable"
LIVE_ARM = re.compile(r"Arm (?:again )?on LIVE…")
DEMO_ARM = re.compile(r'"(Arm (?:again )?on DEMO[^"]*)"')
DEMO_LABEL = re.compile(r"Arm (?:again )?on DEMO")
LIVE_IR = re.compile(r"IR lists live")
# the blocked row's live clause: the override label nearest before "when it lists live"
LIVE_CLAUSE = re.compile(r'"(Arm [^"]*— override)"[^"]*?when it lists live')
LIVE_OVERRIDE = "Arm on LIVE… — override"
# classes whose rows cannot arm: a gate, an absence, a status, a refusal or an outcome
NO_PRESS = ("T2", "**T2", "absence", "**absence", "status", "**status", "T4", "**T4", "outcome")


def cells(line: str) -> list[str]:
    return [c.strip() for c in re.split(r"(?<!\\)\|", line)[1:-1]]


def frame_rows(spec: str) -> list[list[str]]:
    """Section 5's frame and treatment rows, in order."""
    sec = spec_sections(spec).get("5", "")
    return [
        cells(ln) for ln in sec.splitlines() if re.match(r"\| (?:`SCR-085/[a-z-]+`|treatment )", ln)
    ]


def live_step_up(spec: str) -> list[str]:
    """The standing rule: no path arms LIVE without the `22` step-up (`setRuleMode`, `authStepUp`).

    (1) the hand-off frame names SCR-006's no-grace frame and `step_up_required` and comes before
    `pending` and `armed`; (2) every section 4 classification row and section 5 row that names a
    LIVE arm control and can be pressed routes through `step-up-hand-off` or SCR-006; (3) every
    DEMO arm label in the copy deck has its LIVE twin there, named by a pressable section 5 row that
    routes through the hand-off — so no override or re-arm is drawn for DEMO only; (4) the board
    script's rule 5 (record 6379900801): no section 5 row whose "Who sees it" names a live IR
    carries an `Arm (again )?on DEMO` label, and the `blocked` row's live clause ("when it lists
    live") names the override "Arm on LIVE… — override", never a DEMO label.
    """
    bad: list[str] = []
    rows = frame_rows(spec)
    names = [r[0] for r in rows]
    order = {
        n: names.index(f"`SCR-085/{n}`")
        for n in ("step-up-hand-off", "pending", "armed")
        if f"`SCR-085/{n}`" in names
    }
    if len(order) < 3:
        bad.append("step-up rule: section 5 lacks step-up-hand-off, pending or armed")
    elif not order["step-up-hand-off"] < order["pending"] < order["armed"]:
        bad.append("step-up rule: an armed or pending frame comes before step-up-hand-off")
    hand = next((r for r in rows if r[0] == "`SCR-085/step-up-hand-off`"), [])
    if HAND_OFF not in " ".join(hand) or "step_up_required" not in " ".join(hand):
        bad.append(f"step-up rule: step-up-hand-off does not name {HAND_OFF} and step_up_required")
    sec4 = spec_sections(spec).get("4", "")
    table4 = sec4[sec4.find("**The classification table") :]
    rows4 = [cells(ln) for ln in table4.splitlines() if ln.startswith("| ") and "---" not in ln]
    routes = ("`step-up-hand-off`", "SCR-006")

    def pressable(row: list[str], cls: int) -> bool:
        return len(row) > cls and not row[cls].startswith(NO_PRESS)

    for row, cls in [(r, 1) for r in rows4[1:]] + [(r, 5) for r in rows]:
        text = " ".join(row)
        if LIVE_ARM.search(text) and pressable(row, cls) and not any(k in text for k in routes):
            bad.append(f"step-up rule: {row[0][:48]} arms LIVE without the hand-off")
    deck = spec_sections(spec).get("8", "")
    strings = set(re.findall(r'^\| [^|]+\|[^|]+\| "([^"]+)"', deck, MULTI))
    for demo in sorted({m for s in strings for m in DEMO_ARM.findall(f'"{s}"')}):
        twin = (
            demo.replace("on DEMO…", "on LIVE…")
            if "on DEMO…" in demo
            else demo.replace("on DEMO", "on LIVE…")
        )
        named = [
            r
            for r in rows
            if twin in " ".join(r) and pressable(r, 5) and any(k in " ".join(r) for k in routes)
        ]
        if twin not in strings or not named:
            bad.append(f"step-up rule: {demo!r} has no LIVE twin {twin!r} routed to the hand-off")
    for row in rows:
        if len(row) > 2 and LIVE_IR.search(row[2]) and DEMO_LABEL.search(" ".join(row)):
            bad.append(f"step-up rule: {row[0][:48]} names a live IR but carries a DEMO arm label")
    blocked = next((r for r in rows if r[0] == "`SCR-085/blocked`"), [])
    clause = LIVE_CLAUSE.search(" ".join(blocked))
    if not clause or clause.group(1) != LIVE_OVERRIDE:
        bad.append(f"step-up rule: the blocked row's live clause does not name {LIVE_OVERRIDE!r}")
    return bad


# name -> (the section 5 row it edits, or "" for the whole spec; old text or "move"; new text)
MUTATIONS: dict[str, tuple[str, str, str]] = {
    "an armed frame ahead of the hand-off": ("`SCR-085/armed`", "move", ""),
    "SCR-006 dropped from the hand-off": ("`SCR-085/step-up-hand-off`", HAND_OFF, "the dialog"),
    "the override drawn for DEMO only": ("", "Arm on LIVE… — override", "Arm on DEMO — override"),
    "a LIVE arm without the hand-off": ("`SCR-085/review-live`", "`step-up-hand-off`", "`armed`"),
    "the LIVE override inset relabelled DEMO alone": (
        "treatment blocked-override-live",
        "Arm on LIVE… — override",
        "Arm on DEMO — override",
    ),
}


def mutate(spec: str, row: str, old: str, new: str) -> str:
    """A copy of the spec with one edit; the file on disk is never touched."""
    if not row:
        return spec.replace(old, new)
    lines = spec.splitlines(keepends=True)
    i = next(k for k, ln in enumerate(lines) if ln.startswith(f"| {row} "))
    if old == "move":  # move that section 5 row above the step-up-hand-off row
        moved = lines.pop(i)
        dst = next(k for k, ln in enumerate(lines) if ln.startswith("| `SCR-085/step-up-hand-off`"))
        lines.insert(dst, moved)
    else:
        lines[i] = lines[i].replace(old, new)
    return "".join(lines)


def selftest(spec: str) -> tuple[bool, list[str]]:
    out = [f"spec: {'pass' if not live_step_up(spec) else 'FAIL ' + str(live_step_up(spec))}"]
    ok = not live_step_up(spec)
    for name, (row, old, new) in MUTATIONS.items():
        mutated = mutate(spec, row, old, new)
        found = live_step_up(mutated) if mutated != spec else []
        ok = ok and bool(found)
        out.append(f"mutation {name}: {'refused' if found else 'PASSED (the check is blind)'}")
    return ok, out


def gates(
    spec: str, hand: str, extra: list[Path], memo: dict[str, tuple[str, list[str]]]
) -> list[str]:
    bad: list[str] = []
    sec = spec_sections(spec)
    deck = sec.get("8", "")
    for s in REQUIRED:
        if s not in deck:
            bad.append(f"required sentence missing from section 8: {s[:40]}…")
    if NEW_STRING not in deck:
        bad.append("the #4118 string is missing from section 8")
    if OWNER_ONLY not in deck:
        bad.append("the rbac.owner_only live sentence is missing from section 8")
    bad += [f"banned UI word in section 8: {w}" for w in BANNED_UI if w.lower() in deck.lower()]
    for row in re.finditer(
        r"^\| (CA-\d+b?)(?: \([^)]*\))? +\| [^|]+\| \"(.*?)\" +\| ([a-z-]+)", deck, MULTI
    ):
        cid, text, status = row[1], row[2], row[3]
        if cid not in memo:
            bad.append(f"{cid}: not in the memo")
        elif status in ("unchanged", "binding-pending-owner") and text not in memo[cid][1]:
            bad.append(f"{cid}: differs from the memo ({status})")
        elif status != memo[cid][0]:
            bad.append(f"{cid}: status {status} vs the memo's {memo[cid][0]}")
    cat14 = (PLAN / "14-screens-catalogue.md").read_text(encoding="utf-8")
    cat15 = (PLAN / "15-component-catalogue.md").read_text(encoding="utf-8")
    constitution = (ROOT / "CONSTITUTION.md").read_text(encoding="utf-8")
    for f, t in [(SPEC, spec), (HANDOFF, hand)] + [
        (p, p.read_text(encoding="utf-8")) for p in extra
    ]:
        if OLD_STRING in t:
            bad.append(f"{f.name}: the old kill-switch string is present")
        bad += [f"{f.name}: forbidden text {p}" for p in FORBIDDEN if re.search(p, t)]
        bad += [
            f"{f.name}: dangling rule id {r}"
            for r in sorted(set(re.findall(r"\bC-\d+\.\d+\b", t)))
            if r not in constitution
        ]
        bad += [
            f"{f.name}: no such component {c}"
            for c in sorted(set(re.findall(r"\bCMP-\d{3}\b", t)))
            if f"### {c} " not in cat15
        ]
        bad += [
            f"{f.name}: no such screen {s}"
            for s in sorted(set(re.findall(r"\bSCR-\d{3}\b", t)))
            if f"### {s} " not in cat14
        ]
    return bad + live_step_up(spec)


def main(argv: list[str]) -> int:
    extra = [Path(a) for a in argv[argv.index("--extra") + 1 :]] if "--extra" in argv else []
    if "--selftest" in argv:
        passed, lines = selftest(SPEC.read_text(encoding="utf-8"))
        refused = sum(ln.endswith("refused") for ln in lines)
        print("\n".join(lines))
        print(f"--selftest: {'ok' if passed else 'FAIL'} — {refused} of {len(MUTATIONS)} refused")
        return 0 if passed else 1
    themes = {k: load_theme(k) for k in THEMES}
    registered = set(
        re.findall(
            r'fg:\s*"([^"]+)",\s*bg:\s*"([^"]+)"',
            (ROOT / "tools" / "contrast" / "pairs.mjs").read_text(encoding="utf-8"),
        )
    )
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
        matrix.append(
            {"fg": fg, "bg": bg, "role": role, "verdict": verdict, "pairs": reg, "where": element}
        )
        matrix[-1].update({k: round(v, 2) for k, v in ratios.items()})
        out.append(
            f"{fg} on {bg} | {role} | {' / '.join(show(r) for r in ratios.values())} | "
            f"{verdict} | {reg} | {element}"
        )
    alpha = float(resolve(themes["dark"], "opacity.disabled"))
    comp: dict[str, float] = {}
    for th, t in themes.items():
        fill = composite(
            resolve(t, "color.action.primary.default"), resolve(t, "color.surface.overlay"), alpha
        )
        comp[th] = round(
            contrast(composite(resolve(t, "color.text.on-action"), fill, alpha), fill), 2
        )
    out.append(
        f"validity composite (label at {alpha} over the dimmed primary fill) | reported | {comp}"
    )
    out.append("\n## 2. Token bindings (token | dark / light / hc)")
    missing: list[str] = []
    palette: dict[str, dict[str, str]] = {th: {} for th in themes}
    for token in BINDINGS:
        vals = [resolve(t, token)[:40] for t in themes.values()]
        if token in PRIMITIVE_ALIAS:
            vals = [f"primitive; alias {PRIMITIVE_ALIAS[token]}"]
        if vals[0] == "MISSING":
            missing.append(token)
        for th, t in themes.items():
            if token.startswith("color."):
                palette[th][token] = resolve(t, token)
        out.append(f"{token} | {' / '.join(vals)}")
    counts = {
        f: sum("$value" in v for v in json.loads((TOKENS / f).read_text(encoding="utf-8")).values())
        for f in (PRIM, DARK, LIGHT, HC)
    }
    out.append(f"token files: {counts} | MISSING: {missing} | opacity.disabled = {alpha}")
    greyscale = {
        tok: {th: luma601(resolve(t, tok)) for th, t in themes.items()} for tok in LUMA_TOKENS
    }
    out.append(
        f"\n## 3. pairs.mjs: {len(registered)} registered; {gated} gated rows, {proposed} PROPOSED"
    )
    facts = shipped()
    out.append("\n## 4. Shipped facts (parsed from text)")
    for a in facts["arming"]:
        out.append(f"arming.py {a['code']} {a['status']} | {a['message']}")
    out.append(
        f"rules_crud.py accepts {facts['crud_accepted']} | 22 setRuleMode body "
        f"{facts['setRuleMode_body']} (D02-CG1, a contract-gap row)"
    )
    out.append(
        f"simulate example {facts['simulate_example']} | RuleRunStatus {facts['run_status']}"
    )
    out.append(
        f"RuleSimulationResult props {facts['simulation_result_props']} | RuleUpdate props "
        f"{facts['rule_update_props']}"
    )
    out.append(
        f"gate defaults b09 {facts['b09_defaults']} = config {facts['config_defaults']} | "
        f"keymap Rules {facts['rules_commands']} | 24 audited {facts['audited_rule_keys']}"
    )
    cfg, b09 = facts["config_defaults"], facts["b09_defaults"]
    bad: list[str] = []
    if (cfg["fires"], float(cfg["hours"])) != (b09["fires"], b09["hours"]):
        bad.append("gate defaults: b09 and RuleEngineConfig disagree")
    spec = SPEC.read_text(encoding="utf-8") if SPEC.exists() else ""
    hand = HANDOFF.read_text(encoding="utf-8") if HANDOFF.exists() else ""
    memo = memo_copy()
    out.append("\n## 5. Copy gates")
    bad += gates(spec, hand, extra, memo) if spec else ["spec missing"]
    out.append(
        "OK — required sentences, the #4118 string, the live sentence, no banned UI word, "
        "memo rows byte-equal, no private path, ids resolve, no LIVE arm without the step-up"
        if not bad
        else "\n".join("FAIL " + b for b in bad)
    )
    sec = spec_sections(spec)
    deck, s11, s0, s1 = (
        sec.get("8", ""),
        sec.get("11", ""),
        sec.get("0", ""),
        spec[: spec.find("## 0.")],
    )
    ca_status: dict[str, int] = {}
    for m in re.finditer(
        r"^\| (CA-\d+b?)(?: \([^)]*\))? +\| [^|]+\| \"(.*?)\" +\| ([a-z-]+)", deck, MULTI
    ):
        ca_status[m[3]] = ca_status.get(m[3], 0) + 1
    numbers: dict[str, object] = {
        "scr084_states": len(re.findall(r"^\| `SCR-084/[a-z-]+` +\|", sec.get("3", ""), MULTI)),
        "scr084_treatments": len(re.findall(r"^\| treatment ", sec.get("3", ""), MULTI)),
        "scr085_frames": len(re.findall(r"^\| `SCR-085/[a-z-]+` +\|", sec.get("5", ""), MULTI)),
        "boards": len(re.findall(r"^\| 0\d +\| `", s0, MULTI)),
        "light_twins": len(re.findall(r"^\| 0\d +\| `[a-z0-9-]+-light` ", s0, MULTI)),
        "ca_rows": sum(ca_status.values()), "ca_by_status": ca_status,
        "new_strings": len(re.findall(r"^\| new-\d+ +\|", deck, MULTI)),
        "reason_keys": len(re.findall(r"^\| `(?:rbac|rule)\.[a-z_.]+` +\|", deck, MULTI)),
        "g_rows": len(re.findall(r"^\| D02-G\d+ +\|", s11, MULTI)),
        "c_rows": len(re.findall(r"^\| D02-C\d+ +\|", s11, MULTI)),
        "cg_rows": len(re.findall(r"^\| D02-CG\d+ +\|", s11, MULTI)),
        "a_rows": len(re.findall(r"^\| D02-A\d+ +\|", s11, MULTI)),
        "q_rows": len(re.findall(r"^\| BQ-\d+ +\|", s1, MULTI)),
        "q_ruled": len(re.findall(r"^\| BQ-\d+ +\|.*\| RULED 6377845082 +\|$", s1, MULTI)),
        "handoff_blocks": len(re.findall(r"^## Handoff checklist — ", hand, MULTI)),
        "checklist_ticked": len(re.findall(r"^\| \[x\] ", s1, MULTI)),
        "producibility_rows": len(re.findall(r"^\| `SCR-08[45]/[a-z-]+` +\|", sec["6"], MULTI)),
        "pairs_rows": gated, "pairs_registered": gated - proposed, "pairs_proposed": proposed,
        "pairs_fail": fails,
        "missing_tokens": len(missing), "arming_codes": len({a["code"] for a in facts["arming"]}),
        "arming_refusals": len(facts["arming"]),
        "opacity_disabled": alpha, "gate_fires": cfg["fires"], "gate_hours": cfg["hours"],
        "example": facts["simulate_example"], "composite": comp,
        "blank_checklist_lines": len(re.findall(r"^- \[[ x~]\] \*\*[^*]+\*\*\s*$", hand, MULTI)),
        "token_files": {
            "primitives": counts[PRIM], "dark": counts[DARK],
            "light": counts[LIGHT], "hc": counts[HC],
        },
        "pairs_registry": len(registered),
    }  # fmt: skip
    if numbers["q_ruled"] != numbers["q_rows"]:
        bad.append(f"BQ rows RULED {numbers['q_ruled']} of {numbers['q_rows']}")
    out.append("\n## 6. Counts: " + json.dumps(numbers, ensure_ascii=False))
    flat = flatten(
        {
            "numbers": numbers,
            "pairs": {str(i): m for i, m in enumerate(matrix)},
            "greyscale": greyscale,
        }
    )
    if "--check" in argv:
        for m in re.finditer(r"<!-- audit:([A-Za-z0-9_.\-]+)=([^ >]+) -->", spec):
            have = flat.get(m[1])
            if have is None:
                bad.append(f"marker {m[1]}: no such key")
            elif str(have) != m[2] and not (
                isinstance(have, (int, float)) and abs(float(have) - float(m[2])) < 0.006
            ):
                bad.append(f"marker {m[1]}={m[2]} vs {have}")
        out.append(
            "\n## 7. --check: "
            + (
                "every marker re-derived"
                if not [b for b in bad if b.startswith("marker")]
                else "FAIL"
            )
        )
    if "--json" in argv:
        print(
            json.dumps(
                {
                    "numbers": numbers,
                    "matrix": matrix,
                    "palette": palette,
                    "greyscale": greyscale,
                    "missing": missing,
                    "shipped": facts,
                    "memo_ca": {k: v[0] for k, v in memo.items()},
                    "problems": bad,
                },
                ensure_ascii=False,
                indent=1,
            )
        )
    else:
        print("\n".join(out))
    return 1 if fails or bad or numbers["blank_checklist_lines"] else 0


def flatten(d: object, prefix: str = "") -> dict[str, object]:
    out: dict[str, object] = {}
    if isinstance(d, dict):
        for k, v in d.items():
            out.update(flatten(v, f"{prefix}{k}."))
    else:
        out[prefix[:-1]] = d
    return out


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
