#!/usr/bin/env python3
"""E36-D03 screens audit: SCR-080 / SCR-088 / SCR-089 measured matrix, token bindings, contract
and lifecycle counts, motion arithmetic and string gates, computed from text, never by running code.

Standalone, offline, stdlib only; it executes no repo code. It reads the token JSON files and
`themes.json` (the `verify_tokens.py` loader shape: dark = primitives + semantic-dark; light and
high-contrast layer their file over dark), `tools/contrast/pairs.mjs` and `encodings.json`, `14`,
`15`, `22`, `23`, `28`, `rules/manager.py`, `rules/validator.py`, `rules/ir/canonical.py`,
`api/rules_crud.py`, `api/rules.py`, `rules/vocabulary/catalogue.py`, the spec and the handoff as
text, and prints with a source label on every row:
(1) the WCAG 2.x ratio of every fg / bg pair the three screens render, dark / light /
high-contrast, compared UNROUNDED against the role's bar (text 4.5, non-text 3.0, hc-text 7.0 in
the high-contrast theme only; `tools/contrast/generate.mjs`: `ratio >= threshold`); a value within
0.01 of a bar prints to four decimals; `rejected-*` and `decorative` rows are reported, never gated;
(2) every token name the spec, the handoff and the thirteen edited `15` entries bind: resolved per
theme, PROPOSED (`space.rulegroup.indent`) or another entry's DS request (EXPECTED); an unlisted
MISSING name fails; (3) the `pairs.mjs` / `encodings.json` status of each pair; (4) the contract
and lifecycle counts the boards quote; (5) the motion arithmetic and flash audit (the shimmer's
relative-luminance delta against WCAG 2.3.1's 0.10); (6) the string gates; (7) every hit target's
height per density from `size.*` against `size.target.min`; (8) the counts (`--json`). Exit 1 on a
gated FAIL, a target under the minimum or a failed gate.

Usage: python3 -I docs/design/_tools/e36_d03_screens_audit.py [--json] [--extra <file> ...]
"""

from __future__ import annotations

import json
import re
import sys
from pathlib import Path
from typing import cast

ROOT = Path(__file__).resolve().parents[3]
TOKENS, PLAN = ROOT / "packages" / "ui" / "tokens", ROOT / "docs" / "plan"
RULES = ROOT / "services" / "api" / "candleviewer" / "rules"
SPEC = ROOT / "docs" / "design" / "E36" / "E36-D03.md"
HANDOFF = ROOT / "docs" / "design" / "E36" / "E36-D03-handoff.md"
SETS = ("primitives", "semantic-dark", "semantic-light", "semantic-hc")
THEMES = {"dark": SETS[:2], "light": SETS[:3], "high-contrast": (*SETS[:2], SETS[3])}
ORDER = ("dark", "light", "high-contrast")
BAR = {"text": 4.5, "non-text": 3.0, "hc-text": 7.0, "rejected-text": 4.5, "rejected-non-text": 3.0}
GATED = ("text", "non-text", "hc-text")
HEX6 = re.compile(r"^#[0-9A-Fa-f]{6}$")
TOKEN_RE = re.compile(
    r"`((?:color|space|size|type|radius|elevation|border|font|motion)\.[a-z0-9.\-/]*)`"
)
ENTRIES = (
    "140",
    "141",
    "142",
    "143",
    "144",
    "145",
    "155",
    "157",
    "158",
    "159",
    "233",
    "234",
    "235",
)
#: The validator's issue codes the spec quotes, each counted once `validator.py` carries the
#: literal: eleven on main - PR 4246 (merged via 35efcf28) retired `permission_required` from the
#: validator as it added `stop_loosening`, so the count held while the set changed.
_CODES = (
    "unknown_metric schema_error operator_not_applicable type_mismatch missing_action_param "
    "unreachable_branch permission_required native_stop_violation feedback_loop "
    "guard_missing high_frequency stop_loosening"
)
CODES = _CODES.split()
COLUMNS = "name|scope|trigger summary|state|environment|last fired|author|version"
MENU = "Edit (form)|Edit (graph)|Duplicate|Run simulation…|Arm|Disarm|Export|Delete|Fire history"
# code | message (spec section 8): the import preview / results reasons, keyed by code + message
IMPORT_REASONS = (
    "forbidden | The bundle references an account you cannot access.",
    "unknown_metric | Metric '{m}' is not in the vocabulary.",
    "schema_error | Unknown action '{a}'.",
    "format_mismatch (PROPOSED) | This file is a `cv-rule-bundle/2` bundle; this version reads v1",
    "name_taken | A rule named '{name}' already exists.",
    "system_rule_reserved | The 'sys.' name prefix is reserved.",
    "forbidden | Only the Owner can raise a rule's action budget above the default.",
    (
        "rule_ir_invalid | the validator's issues, a field each (a loosening reads 'Not "
        "available'; stop_loosening for every role - PR 4246, merged via 35efcf28)"
    ),
    "payload_too_large (rule_body.py) | Request body or batch exceeds the operation's size ceiling",
    "not checked | Service unavailable - rule engine vocabulary unavailable (the call refused)",
)
TESTS = ("abuse/test_abuse_cases.py", "abuse/test_security_review_fixes.py", "test_rule_limits.py")
_OTHER = (
    "font.mono color.border.invalid color.status.warn color.status.danger color.status.info "
    "color.chip. color.action.on color.action.off color.action.on/off motion.toggle "
    "motion.slide color.surface.code color.border.dashed space.filterbar. space.emptystate. "
    "color.callout. color.action.ghost color.status."
)
OTHER = _OTHER.split()
EXPECTED = {n: "other owner's entry - DS request" for n in OTHER}
EXPECTED["space.rulegroup.indent"] = "PROPOSED token (spec section 9) - interim space.inset.lg"
ALIAS = {"elevation.3": "elevation.popover", "elevation.4": "elevation.dialog"}
# element | fg | bg | role | source  (spec section 12); a 2-space-indented line continues the record
PAIRS_TABLE = """
row name, column text on canvas | color.text.primary | color.surface.canvas | text | s2 s5
row name, high-contrast stretch | color.text.primary | color.surface.canvas | hc-text | s12
hover sentence, reason line | color.text.secondary | color.surface.canvas | text | s2 s3
"as of" caption (off-row) | color.text.tertiary | color.surface.canvas | text | s2 s3
row rule, tree connector (n5 ink) | color.text.tertiary | color.surface.canvas | non-text | s4 s5
pill words, card text on raised | color.text.primary | color.surface.raised | text | s3
T2 reason, reason line, stamps, v3 | color.text.secondary | color.surface.raised | text | s2 s3 s5
ARMED / Accept glyph | color.status.success.strong | color.surface.raised | non-text | s3 s8
SIMULATING glyph | color.status.info.strong | color.surface.raised | non-text | s3
PAUSED glyph | color.status.warning.strong | color.surface.raised | non-text | s3
OFF / ERROR / Skip glyph | color.status.danger.strong | color.surface.raised | non-text | s3 s8
DRAFT / DISARMED / DONE glyph | color.text.secondary | color.surface.raised | non-text | s3
env pill DEMO border (E11-D02 415) | color.env.demo | color.surface.raised | non-text | s2
env pill LIVE border | color.env.live | color.surface.raised | non-text | s2
LIVE band rule (chrome) | color.env.live | color.surface.app | non-text | 14 0.5
conflict banner text | color.text.primary | color.status.warning.subtle | text | s3
conflict banner 2nd line (m5 fix) | color.text.secondary | color.status.warning.subtle | text | s3
conflict banner glyph | color.status.warning.strong | color.status.warning.subtle | non-text | s3
rejected m5: tertiary on amber | color.text.tertiary | color.status.warning.subtle
  | rejected-text | s3
engine-down banner text | color.text.primary | color.status.danger.subtle | text | s3
engine-down banner 2nd line | color.text.secondary | color.status.danger.subtle | text | s3
engine-down banner glyph | color.status.danger.strong | color.status.danger.subtle | non-text | s3
estimated chip word (CMP-227) | color.text.primary | color.status.info.subtle | text | s3
estimated chip glyph, outline | color.status.info.default | color.status.info.subtle | non-text | s3
current row outline | color.border.selected | color.surface.canvas | non-text | s4
rejected n5: border.strong rule | color.border.strong | color.surface.canvas
  | rejected-non-text | s5
compiled IR text (pre) | color.text.primary | color.surface.sunken | text | s5
the pre's described-by note | color.text.secondary | color.surface.sunken | text | s5
row menu text (overlay) | color.text.primary | color.surface.overlay | text | s2
row menu T2 label (overlay) | color.text.tertiary | color.surface.overlay | text | s2 s12
row menu T2 reason (overlay) | color.text.secondary | color.surface.overlay | text | s2 s12
diagnostic pill word (hover) | color.text.primary | color.surface.hover | text | s5
focus ring on canvas | color.focus.ring | color.surface.canvas | non-text | s13
focus ring on raised | color.focus.ring | color.surface.raised | non-text | s13
focus ring on the pre | color.focus.ring | color.surface.sunken | non-text | s13
focus ring, conflict banner | color.focus.ring | color.status.warning.subtle | non-text | s13
focus ring, engine-down banner | color.focus.ring | color.status.danger.subtle | non-text | s13
focus ring, estimated chip | color.focus.ring | color.status.info.subtle | non-text | s13
primary button label | color.text.on-action | color.action.primary.default | text | s7
destructive confirm label | color.text.on-action | color.status.danger.default | text | s3
selected row text | color.text.primary | color.surface.selected | text | s4
selected row v3 cell, in-row caption | color.text.secondary | color.surface.selected | text | s2 s12
rejected: tertiary on a selected row | color.text.tertiary | color.surface.selected
  | rejected-text | s12
focus ring on a selected row | color.focus.ring | color.surface.selected | non-text | s13
current-row outline on selected | color.border.selected | color.surface.selected | non-text | s4
hovered row v3 cell, in-row caption | color.text.secondary | color.surface.hover | text | s2 s12
rejected: tertiary on a hovered row | color.text.tertiary | color.surface.hover
  | rejected-text | s12
focus ring on a hovered row | color.focus.ring | color.surface.hover | non-text | s13
current-row outline on hover | color.border.selected | color.surface.hover | non-text | s4
skeleton two-tone | color.surface.hover | color.surface.raised | decorative | s3
"""
# word | wire source or G-row  (spec section 3)
STATUS_TABLE = """
DRAFT | mode disabled with the shipped rules.disabled_reason null (not on the wire - D03-G7);
  interim heuristic: last_run_at null, which misreads an armed-then-disarmed rule that never ran
SIMULATING | mode simulate - wire
ARMED-DEMO | mode armed, environments without live (the detail, fetched for the visible rows;
  "ARMED" + "Loading..." until known, never DEMO by default; D03-G4) - wire + G-row
ARMED-LIVE | mode armed, environments with live (the detail; D03-G4) - wire + G-row
DISARMED | mode disabled with disabled_reason disarmed (not on the wire - D03-G7); interim
  heuristic: last_run_at set or the rules broadcast of rule.disarmed, which misreads an OFF rule
  as DISARMED; the quarantined reason via the view fields (D03-G14)
PAUSED | B9 paused_degraded - no wire field (D03-G7); until then the mode word, and the hover
  sentence says rules pause while their feed is degraded
OFF | B9 kill_switched = disabled_reason kill_switched (not on the wire - D03-G7); until then the
  mode word (the interim heuristic shows DISARMED)
DONE | B9 spent (once_satisfied); no wire field - D03-G7; until then the mode word
ERROR | last_run_status error while mode is armed or simulate - wire; latched until the next ok
  run plus 1 s
"""
# n | element | duration token | easing | reduce | carrier | rate note  (spec section 10)
MOTION_TABLE = """
1 | CMP-140 row add | fast | decelerate | instant | the new row's name, focus landing in it | -
2 | CMP-140 row remove | fast | accelerate | instant | the removal announcement, focus on the next
  row | -
3 | CMP-140 row reorder | fast | standard | instant | the move announcement, the renumbered names
  | -
4 | CMP-141 group expand / collapse | instant | none | n/a - the group does not collapse (E36-D02
  section 6) | the legend "any of" and the bracket carry the grouping | -
5 | CMP-234 error-count change | fast | standard | instant | the count text, the log announcement
  | debounce
6 | round-trip indicator transition | fast | standard | instant swap | word, glyph, one announcement
  | -
7 | CMP-046 drawer open / close | normal | decelerate / accelerate | instant | focus moves in, the
  heading | -
8 | SCR-080 row state flip | instant | none | same | the word + glyph; announced once, politely
  | coalesce
9 | SCR-080 bulk-bar appear | fast | decelerate | instant | the toolbar's "n selected" text | -
10 | CMP-044 / CMP-043 dialog open | normal | decelerate | instant | the focus trap, the dialog
  heading | -
11 | CMP-033 Copied label swap | fast | standard | instant | the polite announcement "Copied" | -
12 | SCR-089 import progress | instant | none | same | the "7 of 100 checked" text, 1 per 5 s at
  most | -
13 | SCR-080 loading skeleton | slow | standard | static two-tone | the "Loading..." text | shimmer
14 | value flash on the fires cell | instant | none | same | the number; a fire announced once | -
"""
EASINGS = ("standard", "decelerate", "accelerate", "none", "decelerate / accelerate")
COALESCE_MS, DEBOUNCE_MS, SHIMMER_MS, FLASH_BAR, LOOP_STOP_S = 250, 300, 1200, 3.0, 5
FLASH_LUM_BAR = 0.10  # WCAG 2.3.1: a flash is a relative-luminance change of 0.10 or more
# target | compact height source | comfortable height source  (spec section 13; 16 section 3);
# "pill20" = the 20 px pill plus its 2 px padded hit box on each side
TARGETS_TABLE = """
row selection checkbox (CMP-005) | size.control.compact | size.control.comfortable
row-menu button (CMP-002) | size.control.compact | size.control.comfortable
estimated chip (CMP-227) | pill20 | size.control.comfortable
sort header button | size.control.compact | size.control.comfortable
inspector segment (CMP-003) | size.control.compact | size.control.comfortable
Copy IR / Copy hash / Copy path / Export JSON | size.control.compact | size.control.comfortable
Set priority (CMP-159 action) | size.control.compact | size.control.comfortable
file input Choose files (CMP-067) | size.control.compact | size.control.comfortable
export radios (CMP-006) | size.control.compact | size.control.comfortable
tree item (CMP-240) | size.row.compact | size.row.comfortable
filter chip (CMP-055) | size.control.compact | size.control.comfortable
bulk-bar buttons (CMP-243) | size.control.compact | size.control.comfortable
"""
PILL_PX, PILL_PAD = 20, 2
Tokens = dict[str, dict[str, object]]


def rows(table: str) -> list[list[str]]:
    recs: list[str] = []
    for ln in table.strip("\n").splitlines():
        if ln.startswith("  ") and recs:
            recs[-1] += " " + ln.strip()
        elif ln:
            recs.append(ln)
    return [[c.strip() for c in r.split(" | ")] for r in recs]


def read(path: Path) -> str:
    return path.read_text(encoding="utf-8") if path.exists() else ""


def merged(files: tuple[str, ...]) -> Tokens:
    out: Tokens = {}
    for f in files:
        out.update(cast(Tokens, json.loads(read(TOKENS / f"{f}.tokens.json"))))
    return out


def resolve(value: object, tokens: Tokens, seen: frozenset[str] = frozenset()) -> object:
    if isinstance(value, str) and value.startswith("{") and value.endswith("}"):
        ref = value[1:-1]
        if ref in seen or ref not in tokens:
            raise KeyError(ref)
        return resolve(tokens[ref]["$value"], tokens, seen | {ref})
    return value


def hex_of(name: str, tokens: Tokens) -> str | None:
    v = resolve(tokens[name]["$value"], tokens) if name in tokens else None
    return v if isinstance(v, str) and HEX6.match(v) else None


def lum(h: str) -> float:
    c = [int(h[i : i + 2], 16) / 255.0 for i in (1, 3, 5)]
    r, g, b = (x / 12.92 if x <= 0.04045 else ((x + 0.055) / 1.055) ** 2.4 for x in c)
    return 0.2126 * r + 0.7152 * g + 0.0722 * b


def contrast(a: str, b: str) -> float:
    la, lb = lum(a), lum(b)
    return (max(la, lb) + 0.05) / (min(la, lb) + 0.05)


def fmt(r: float | None) -> str:
    if r is None:
        return "n/a"
    return (
        f"{r:.4f}" if round(r, 2) in (3.0, 4.5, 7.0) and round(r, 4) != round(r, 2) else f"{r:.2f}"
    )


def ms_of(token: str, prim: Tokens) -> int:
    return int(str(resolve(prim[f"motion.duration.{token}"]["$value"], prim)).rstrip("ms"))


def measure(themes: dict[str, Tokens], reg: set[tuple[str, str]]) -> list[dict[str, object]]:
    out: list[dict[str, object]] = []
    for element, fg, bg, role, source in rows(PAIRS_TABLE):
        ratios: dict[str, float | None] = {}
        for th in ORDER:
            a, b = hex_of(fg, themes[th]), hex_of(bg, themes[th])
            ratios[th] = contrast(a, b) if a and b else None
        bar = BAR.get(role)
        low = [t for t in ORDER if bar and (ratios[t] or 0) < bar]
        if role == "hc-text":
            low = [t for t in low if t == "high-contrast"]
        if role == "decorative":
            verdict = "decorative (reported)"
        elif role.startswith("rejected"):
            verdict = (
                "rejected: fails " + ", ".join(low) if low else "rejected: passes"
            ) + ", never used"
        else:
            verdict = "PASS" if not low else "FAIL " + ", ".join(low)
        reg_s = "registered" if (fg, bg) in reg else "PROPOSED" if role in GATED else "-"
        cells = [element, f"`{fg}`", f"`{bg}`", role] + [fmt(ratios[t]) for t in ORDER]
        row = {"fg": fg, "bg": bg, "role": role, "verdict": verdict, "registered": (fg, bg) in reg}
        out.append(row | {"cells": [*cells, verdict, reg_s, source]})
    return out


def bindings(themes: dict[str, Tokens], scanned: str) -> list[tuple[str, str, str]]:
    out = []
    for name in sorted(set(TOKEN_RE.findall(scanned))):
        values = {
            t: resolve(themes[t][name]["$value"], themes[t]) for t in ORDER if name in themes[t]
        }
        if values:
            status = f"primitive (alias {ALIAS[name]})" if name in ALIAS else "resolved"
        else:
            status = (
                EXPECTED.get(name) or EXPECTED.get(name.rstrip("./") + ".") or "MISSING (unlisted)"
            )
        out.append((name, status, json.dumps(values)))
    return out


def enum_of(text: str, name: str) -> list[str]:
    m = re.search(rf"^    {name}:.*?enum:\s*\[([^\]]*)\]", text, re.MULTILINE | re.DOTALL)
    return [x.strip() for x in m.group(1).split(",")] if m else []


def contract() -> dict[str, object]:
    t22, t23 = read(PLAN / "22-api-openapi.yaml"), read(PLAN / "23-ws-protocol.md")
    t28, manager = read(PLAN / "28-statechart-catalogue.md"), read(RULES / "manager.py")
    paths = re.findall(r"^  (/rules[^:]*):", t22, re.MULTILINE)
    rule_block = t22[t22.index("\n    Rule:\n") : t22.index("\n    RuleDetail:")]
    ws = t23[t23.index("### 15.6") : t23.index("### 15.7")]
    kinds = re.search(r'"kind":\s*\{\s*"enum":\s*\[([^\]]*)\]', ws, re.DOTALL)
    b9 = t28[t28.index("### B9.2") : t28.index("### B9.3")]
    validator, canonical = read(RULES / "validator.py"), read(RULES / "ir" / "canonical.py")
    hv = re.search(r"^IR_HASH_VERSION = (\d+)", canonical, re.MULTILINE)
    api = ROOT / "services" / "api" / "candleviewer" / "api"
    crud, api_rules = read(api / "rules_crud.py"), read(api / "rules.py")
    catalogue = read(RULES / "vocabulary" / "catalogue.py")
    t15 = read(PLAN / "15-component-catalogue.md")
    con: dict[str, object] = {"rule_paths": paths}
    con["no_export_import_path"] = not any("port" in p for p in paths)
    con["rule_mode"], con["rule_run_status"] = enum_of(t22, "RuleMode"), enum_of(
        t22, "RuleRunStatus"
    )
    con["rule_props"] = re.findall(r"^        ([a-z_0-9]+):", rule_block, re.MULTILINE)
    con["ws_item_props"] = re.findall(
        r'^          "([a-z_0-9]+)":', ws.split('"events"')[0], re.MULTILINE
    )
    con["ws_event_kinds"] = re.findall(r'"([a-z_]+)"', kinds.group(1)) if kinds else []
    con["b9_states"] = re.findall(r"^\| `([a-z_]+)` \|", b9, re.MULTILINE)
    con["b9_tags_present"] = "needs_human_rearm" in b9 and "once_satisfied" in b9
    con["audit_keys"] = sorted(set(re.findall(r'"(rule\.[a-z_]+)"', manager)))
    con["validator_codes"] = [c for c in CODES if f'"{c}"' in validator]
    # PR 4246 (stop_loosening, merged via 35efcf28) probes, read from text: the code in the
    # validator, widen_stop retired from the catalogue, and the validate / compile routes no
    # longer reading a loosen-stop permission (D03-G18 closed). main() gates all three.
    con["stop_loosening_shipped"] = '"stop_loosening"' in validator
    con["widen_stop_retired"] = "RETIRED_ACTIONS" in catalogue
    con["validate_reads_loosen_permission"] = "LOOSEN_STOP_PERMISSION" in api_rules
    msgs = ("is not in the vocabulary.", "Unknown action '")
    con["import_messages_present"] = all(m in validator for m in msgs) and (
        "The bundle references an account you cannot access." in manager
    )
    con["ir_hash_version"] = int(hv.group(1)) if hv else None
    con["bundle_format"] = '"cv-rule-bundle/1"' in manager
    con["crud_routes"] = len(re.findall(r"@router\.(?:get|post|put|delete)\(", crud))
    con["entries_present"] = [
        f"CMP-{i}" for i in ENTRIES if re.search(rf"^### CMP-{i} ", t15, re.MULTILINE)
    ]
    return con


def px_of(name: str, prim: Tokens) -> int:
    if name == "pill20":
        return PILL_PX + 2 * PILL_PAD
    return int(str(resolve(prim[name]["$value"], prim)))


def targets(prim: Tokens) -> tuple[list[list[str]], list[str]]:
    """Every hit target's height per density against `size.target.min` (spec section 13)."""
    minimum, table, problems = px_of("size.target.min", prim), [], []
    for target, compact, comfortable in rows(TARGETS_TABLE):
        c, k = px_of(compact, prim), px_of(comfortable, prim)
        verdict = "PASS" if c >= minimum and k >= minimum else "FAIL"
        if verdict != "PASS":
            problems.append(f"target under {minimum} px: {target}")
        table.append([target, f"{c} px ({compact})", f"{k} px ({comfortable})", verdict])
    return table, problems


def motion(prim: Tokens) -> tuple[list[list[str]], list[str], dict[str, float]]:
    slow, table, problems = ms_of("slow", prim), [], []
    for n, element, dur, easing, reduce, carrier, note in rows(MOTION_TABLE):
        ms = ms_of(dur, prim)
        if ms > slow or easing not in EASINGS or not reduce or not carrier:
            problems.append(f"motion row {n}")
        table.append([n, element, f"{dur} ({ms} ms)", easing, reduce, carrier, note])
    rates = {
        "coalesce_per_s": round(1000 / COALESCE_MS, 2),
        "debounce_per_s": round(1000 / DEBOUNCE_MS, 2),
    }
    rates |= {
        "shimmer_per_s": round(1000 / SHIMMER_MS, 2),
        "shimmer_slow_bound_per_s": round(1000 / slow, 2),
    }
    rates |= {"flash_bar_per_s": FLASH_BAR, "loop_stop_s": LOOP_STOP_S}
    hover, raised = hex_of("color.surface.hover", prim), hex_of("color.surface.raised", prim)
    delta = round(abs(lum(hover) - lum(raised)), 3) if hover and raised else 1.0
    rates |= {"skeleton_lum_delta": delta, "flash_lum_bar": FLASH_LUM_BAR}
    if rates["debounce_per_s"] <= FLASH_BAR:
        problems.append("debounce arithmetic: row 5 must be flash-free by construction")
    if delta >= FLASH_LUM_BAR:
        problems.append("skeleton shimmer: the two tones differ by a flash-level luminance step")
    return table, problems, rates


def gates(files: list[Path]) -> list[str]:
    old = ("Pauses itself " + "after 5 errors.", "Only the owner can " + "loosen a stop.")
    private = (
        "/" + "home/",
        "page" + "Link",
    )
    need = ("5 errors in a row", "re-arm", "The stop only ever tightens.",
            "Not available — rules never loosen a stop.", "Native stops are unaffected.",
            "no screen of this ticket offers a loosening or stop-clearing control",
            "no account ids, no keys, no armed state",
            "System rules cannot be changed.", "from the IR itself",
            "stop_loosening", "35efcf28",
            "could loosen a stop. Not available — rules never loosen a stop.")  # fmt: skip
    cons, bad = read(ROOT / "CONSTITUTION.md"), []
    for f in files:
        t = read(f)
        if not t:
            bad.append(f"{f.name}: missing")
            continue
        bad += [f"{f.name}: lacks {s!r}" for s in need if s not in t]
        forbidden = (
            *old,
            "This rule may " + "widen the stop",
            "if #4246 " + "merges as is",  # a merge qualifier that outlived the merge
            *private,
        )
        bad += [f"{f.name}: forbidden {s!r}" for s in forbidden if s in t]
        cids = sorted(set(re.findall(r"\bC-\d+\.\d+\b", t)))
        bad += [f"{f.name}: dangling {c}" for c in cids if f"**{c}" not in cons]
    bad += [
        f"test path missing: {p}"
        for p in TESTS
        if not (ROOT / "services/api/tests/rules" / p).exists()
    ]
    return bad


def dark_ratio(dark: Tokens, a: str, b: str) -> float:
    return round(
        contrast(hex_of(f"color.{a}", dark) or "#000", hex_of(f"color.{b}", dark) or "#000"), 2
    )


def count_rows(spec: str, prefix: str) -> int:
    return len(set(re.findall(rf"^\| {prefix}(\d+) ", spec, re.MULTILINE)))


def counts(
    spec: str,
    handoff: str,
    pairs: list[dict[str, object]],
    bound: list[tuple[str, str, str]],
    con: dict[str, object],
    proposed: list[tuple[str, str]],
) -> dict[str, int]:
    gated = [p for p in pairs if p["role"] in GATED]
    distinct = {(str(p["fg"]), str(p["bg"])) for p in gated}
    t4 = handoff.split("### Table 4")[-1].split("### Table 5")[0].splitlines()
    n = {"status_words": len(rows(STATUS_TABLE)), "boards": 12, "entries_15": len(ENTRIES)}
    n |= {"import_reasons": len(IMPORT_REASONS), "motion_rows": len(rows(MOTION_TABLE))}
    n |= {"targets": len(rows(TARGETS_TABLE))}
    n |= {"columns": len(COLUMNS.split("|")), "menu_items": len(MENU.split("|"))}
    n |= {"pairs_rows": len(pairs), "pairs_gated": len(gated)}
    for k in ("b9_states", "rule_paths", "audit_keys", "validator_codes"):
        n[k] = len(cast(list[str], con[k]))
    n["ws_modes"] = len(cast(list[str], con["rule_mode"]))
    n["ws_run_statuses"] = len(cast(list[str], con["rule_run_status"]))
    n["ws_event_kinds"] = len(cast(list[str], con["ws_event_kinds"]))
    n |= {"pairs_distinct": len(distinct), "pairs_proposed": len(proposed)}
    n["pairs_registered"] = len(distinct) - len(proposed)
    n["pairs_failing"] = sum(p["verdict"] != "PASS" for p in gated)
    n["pairs_decorative"] = sum(p["role"] == "decorative" for p in pairs)
    n["pairs_rejected"] = sum(str(p["role"]).startswith("rejected") for p in pairs)
    n["tokens_bound"] = sum(s == "resolved" or s.startswith("primitive") for _, s, _ in bound)
    n["tokens_proposed"] = sum(s.startswith("PROPOSED") for _, s, _ in bound)
    n["tokens_other_owner"] = sum(s.startswith("other") for _, s, _ in bound)
    n |= {"c_rows": count_rows(spec, "D03-C"), "g_rows": count_rows(spec, "D03-G")}
    n["q_rows"] = count_rows(spec, "(?:BQ-D03-|D03-Q)")
    n["handoff_blocks"] = handoff.count("## Handoff checklist —")
    n["table4_rows"] = sum(
        ln.startswith("| ") and not ln.startswith(("| Comp", "| ---")) for ln in t4
    )
    return n


def main(argv: list[str]) -> int:
    themes = {k: merged(v) for k, v in THEMES.items()}
    pairs_src = read(ROOT / "tools" / "contrast" / "pairs.mjs")
    reg = set(re.findall(r'fg:\s*"([^"]+)",\s*bg:\s*"([^"]+)"', pairs_src))
    enc_doc = cast(
        dict[str, object], json.loads(read(ROOT / "tools" / "contrast" / "encodings.json"))
    )
    enc = sorted(cast(dict[str, object], enc_doc["encodings"]))
    extra = [Path(a) for a in argv[argv.index("--extra") + 1 :]] if "--extra" in argv else []
    pairs, con = measure(themes, reg), contract()
    spec, handoff = read(SPEC), read(HANDOFF)
    t15 = read(PLAN / "15-component-catalogue.md")
    ent = [
        re.search(rf"^### CMP-{i} .*?(?=^### |^## )", t15, re.MULTILINE | re.DOTALL)
        for i in ENTRIES
    ]
    bound = bindings(themes, spec + handoff + "".join(m.group(0) for m in ent if m))
    mtable, bad, rates = motion(themes["dark"])
    ttable, tbad = targets(themes["dark"])
    bad += tbad
    memo = {"text.primary/surface.canvas": 15.20, "text.primary/status.warning.subtle": 9.86}
    memo |= {"text.secondary/surface.canvas": 9.33, "text.tertiary/surface.raised": 5.62}
    memo |= {"text.tertiary/status.warning.subtle": 3.86}
    got = {k: dark_ratio(themes["dark"], *k.split("/")) for k in memo}
    gated = [p for p in pairs if p["role"] in GATED]
    proposed = sorted({(str(p["fg"]), str(p["bg"])) for p in gated if not p["registered"]})
    bad += gates([SPEC, HANDOFF, *extra])
    # PR 4246 is merged and cited plainly, so its three probes must read true / true / false
    bad += [] if con["stop_loosening_shipped"] else ["validator.py lacks stop_loosening (PR 4246)"]
    bad += [] if con["widen_stop_retired"] else ["catalogue.py lacks RETIRED_ACTIONS (PR 4246)"]
    if con["validate_reads_loosen_permission"]:
        bad.append("api/rules.py reads a loosen-stop permission, but D03-G18 is cited as closed")
    bad += [f"invented token {n}" for n, s, _ in bound if s.startswith("MISSING")]
    bad += [f"memo pair {k}: {got[k]} != {v}" for k, v in memo.items() if got[k] != v]
    bad += [f"{p['fg']} on {p['bg']}: {p['verdict']}" for p in gated if p["verdict"] != "PASS"]
    bad += ["22 has an export / import path"] if not con["no_export_import_path"] else []
    words = COLUMNS.split("|") + MENU.split("|")
    bad += [f"spec lacks {w!r}" for w in words if w.lower() not in spec.lower()]
    n = counts(spec, handoff, pairs, bound, con, proposed)
    if "--json" in argv:
        out = {"counts": n, "rates": rates, "contract": con, "memo_pairs": got}
        print(
            json.dumps(
                out | {"proposed_pairs": proposed, "encodings": enc, "problems": bad}, indent=2
            )
        )
        return 1 if bad else 0
    print("# E36-D03 screens audit (packages/ui/tokens; WCAG 2.x; unrounded compare)\n")
    print("## 1. Matrix\n")
    print(
        "| element | fg | bg | role | dark | light | hc | verdict | pairs.mjs | source |\n|"
        + " --- |" * 10
    )
    print("\n".join("| " + " | ".join(cast(list[str], p["cells"])) + " |" for p in pairs))
    print(f"\nmemo section 0 pairs reproduced: {got}\n\n## 2. Token bindings\n")
    print("\n".join(f"- `{name}`: {status} {values}" for name, status, values in bound))
    print(f"\n## 3. pairs.mjs ({len(reg)} registered) and encodings.json\n")
    print(f"- PROPOSED ({len(proposed)}):")
    print("  " + "; ".join(f"`{a}` on `{b}`" for a, b in proposed))
    print(f"- encodings present: {enc}; PROPOSED: rule-state, round-trip\n")
    print("## 4. Contract and lifecycle\n")
    print(
        "\n".join(f"- {k}: {v}" for k, v in con.items())
        + "\n\n## 5. Motion arithmetic, status words\n"
    )
    print("\n".join("| " + " | ".join(r) + " |" for r in mtable))
    print(f"- rates: {rates} (coalescing is data, 0 flashes; the debounce rate is above")
    print(f"  {FLASH_BAR}/s, so row 5 has no flash by design; the shimmer stops on data or at 5 s;")
    print(f"  its two tones differ by a relative luminance of {rates['skeleton_lum_delta']}, under")
    print(f"  the {FLASH_LUM_BAR} flash bar)")
    print("\n".join(f"- status {w}: {src}" for w, src in rows(STATUS_TABLE)))
    print("\n## 6. Import reasons (code | message)\n")
    print("\n".join(f"- {r}" for r in IMPORT_REASONS))
    print("\n## 7. Hit targets per density (against size.target.min)\n")
    print("| target | compact | comfortable | verdict |\n|" + " --- |" * 4)
    print("\n".join("| " + " | ".join(r) + " |" for r in ttable))
    print("\n## 8. String gates and counts\n\n" + ("\n".join(bad) if bad else "gates: all pass"))
    print(json.dumps(n))
    return 1 if bad else 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
