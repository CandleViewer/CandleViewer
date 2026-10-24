#!/usr/bin/env python3
"""E35-D03 diagnostics audit: SCR-086 / 087 / 088 / 089 matrix, bindings, shipped facts, copy gates.

Standalone, offline, stdlib only; it executes no repo code. It reads the token JSON, `pairs.mjs`,
the rules module (`evaluator/engine.py`, `runner.py`, `manager.py`, `validator.py`, `canonical.py`,
`api/rules_crud.py`, `api/rules.py`), `keymap.json`, `21`, `22`, `24`, the E35-D01 memo, the merged
E35-D02 / E36-D03 specs and this ticket's spec AS TEXT and prints, with a source label on every row:
(1) the WCAG 2.x ratio of every fg / bg pair the four screens render in dark / light / high-contrast
(`themes.json` layering) against the role's bar — `rejected-*`, `decorative` and `composite` rows
are reported, never gated; (2) every token the spec and the handoff bind, resolved or MISSING; (3)
which pairs `pairs.mjs` registers and which are PROPOSED; (4) the shipped facts the boards and the
section 6 mapping quote, parsed from file text — every shipped `skipped_reason` literal must have a
section 6 row; (5) the copy gates — the memo's CA rows byte-for-byte by status, CA-27 and CA-29
verbatim, the #4118 string, no banned UI word, no private path or host (generic patterns), dangling
`C-x.y` / `CMP-nnn` / `SCR-nnn` ids, every section 6 sentence at most 80 characters and free of
exception text, the stop pair tighten-only, the resolver never arming, and the cite check — a cited
`file:line` whose quoted fragment moved WARNs with the current line and FAILs only when the
fragment is gone; (6) the counts. `--check` re-derives every `<!-- audit:NAME=VALUE -->` marker in
the spec. `--selftest` holds mutated copies of the spec in memory (a section 6 row dropped, a CA
quote altered, a cite's line number moved, a cite's fragment removed): the spec must pass, the first
two must FAIL, the moved cite must WARN and the gone cite must FAIL.

Usage: python3 -I docs/design/_tools/e35_d03_diagnostics_audit.py [--json] [--check] [--selftest]
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
DESIGN = ROOT / "docs" / "design"
SPEC = DESIGN / "E35" / "E35-D03.md"
HANDOFF = DESIGN / "E35" / "E35-D03-handoff.md"
MEMO = DESIGN / "research" / "e35-rule-arming-trust.md"
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
CA_VERBATIM = ("CA-27", "CA-29")  # the sentences the spec quotes byte-for-byte (BQ-7, BQ-17)
NEW_STRING = "Turns itself off after 5 errors in a row — you re-arm it."
OLD_STRING = "Pauses itself after 5 errors."
GENERIC_ERROR = "Evaluation failed — see the audit record."  # BQ-11: one sentence for every error
ERROR_CODES = ("evaluation_timeout", "{ExceptionName}", "auto_disabled:{error}")
ERROR_PROBES = ('"evaluation_timeout"', "type(exc).__name__", 'f"auto_disabled:{error}"')
TIGHTEN = "Later checks can still tighten the stop."
# Words the UI copy (sections 6 and 11) never carries (memo SC-1, SC-15, section 7; #4137).
BANNED_UI = ("backtest", "emulated stop", "Panic", "triggered", "widen")
# Private paths and hosts never belong in a public file: generic patterns only — no personal word
# and no hostname; the path literal is split so this file never contains the string it forbids.
FORBIDDEN = (
    r"/(?:ho" + r"me|Users)/[^/\s]+/",
    r"penpot\.[a-z0-9-]+\.[a-z]{2,}",
    r"team-i" + r"d=",
    r"file-i" + r"d=",
)
NOT_IN_15 = {"CMP-240"}  # E13-D02 G-1's proposed TreeView (E36-D03 BQ-D03-2): no `15` heading yet
# a cite-checked line: `E36-D03.md:118` "the fragment the line must still contain"
CITE = re.compile(r"`([A-Z]\d{2}-D\d{2})\.md:(\d+)` \"([^\"]+)\"")
CA_ROW = re.compile(r'^\| (CA-\d+b?)(?: \([^)]*\))? +\| [^|]+\| "(.*?)" +\| ([a-z-]+)', MULTI)
MAP_ROW = re.compile(r'^\| `([^`]+)` +\| ([a-z_-]+) +\| [^|]+\| "([^"]*)"', MULTI)
MARKER = re.compile(r"<!-- audit:([A-Za-z0-9_.\-]+)=([^ >]+) -->")
# element | fg | bg | role — every pair the four screens draw (spec section 13, rows in order).
PAIRS_TABLE = """
SCR-086 title, table text, option labels | color.text.primary | color.surface.overlay | text
consequence sentences, the validity reason | color.text.secondary | color.surface.overlay | text
T2 label + lock (Set priority, Disarm one) | color.text.tertiary | color.surface.raised | text
T2 reason sentence | color.text.secondary | color.surface.raised | text
the conflict row (amber) | color.text.primary | color.status.warning.subtle | text
the conflict row glyph | color.status.warning.strong | color.status.warning.subtle | non-text
the risk band text | color.text.primary | color.surface.sunken | text
the risk band glyph | color.status.info.strong | color.surface.sunken | non-text
selected radio ring, checked box | color.action.primary.default | color.surface.overlay | non-text
Apply, Import (primary) | color.text.on-action | color.action.primary.default | text
the refusal line (T4), the failed check | color.text.primary | color.status.danger.subtle | text
the refusal glyph | color.status.danger.strong | color.status.danger.subtle | non-text
focus ring on the dialog | color.focus.ring | color.surface.overlay | non-text
SCR-087 odd rows on the canvas | color.text.primary | color.surface.canvas | text
SCR-087 captions, the meta line | color.text.secondary | color.surface.canvas | text
even rows, the expanded row, the nested table | color.text.primary | color.surface.raised | text
second lines on raised, the snapshot note | color.text.secondary | color.surface.raised | text
a hovered row | color.text.primary | color.surface.hover | text
a selected row | color.text.primary | color.surface.selected | text
a selected row's second line | color.text.secondary | color.surface.selected | text
the failed row, the CMP-234 entries | color.text.primary | color.status.danger.subtle | text
the Done glyph on raised | color.status.success.strong | color.surface.raised | non-text
the Done glyph on the canvas | color.status.success.strong | color.surface.canvas | non-text
the Failed glyph on raised | color.status.danger.strong | color.surface.raised | non-text
the Failed glyph on the canvas | color.status.danger.strong | color.surface.canvas | non-text
the Skipped dash, the checkbox border | color.text.tertiary | color.surface.raised | non-text
DEMO glyph | color.env.demo | color.surface.raised | non-text
LIVE glyph | color.env.live | color.surface.raised | non-text
the environment word (7:1, memo 9d A7) | color.text.primary | color.surface.raised | hc-text
the engine-restart marker | color.text.secondary | color.surface.sunken | text
the new-firings pill, the verification strip | color.text.primary | color.status.info.subtle | text
the pill glyph | color.status.info.strong | color.status.info.subtle | non-text
the strip's check glyph | color.status.success.strong | color.status.info.subtle | non-text
the pre text (SCR-088) | color.text.primary | color.surface.sunken | text
the masked account token | color.text.secondary | color.surface.sunken | text
the Order / Audit / Replay links | color.text.link | color.surface.canvas | text
focus ring on the canvas | color.focus.ring | color.surface.canvas | non-text
focus ring on raised | color.focus.ring | color.surface.raised | non-text
tertiary on a selected row (never) | color.text.tertiary | color.surface.selected | rejected-text
E09-D09 T2 keeps text.tertiary (never) | color.text.disabled | color.surface.raised | rejected-text
the row hairline | color.border.default | color.surface.raised | decorative
"""
BINDINGS = (
    "color.surface.app", "color.surface.canvas", "color.surface.raised", "color.surface.overlay",
    "color.surface.hover", "color.surface.selected", "color.surface.sunken", "color.text.primary",
    "color.text.secondary", "color.text.tertiary", "color.text.on-action", "color.text.link",
    "color.action.primary.default", "color.focus.ring", "color.border.default",
    "color.border.subtle", "color.status.success.strong", "color.status.warning.subtle",
    "color.status.warning.strong", "color.status.danger.subtle", "color.status.danger.strong",
    "color.status.danger.default", "color.status.info.subtle", "color.status.info.strong",
    "color.status.info.default", "color.env.demo", "color.env.live", "opacity.disabled",
    "elevation.chrome", "elevation.dialog", "radius.control", "radius.pill", "type.ui.heading-md",
    "type.ui.heading-sm", "type.ui.body", "type.ui.caption", "type.ui.label", "type.num.sm",
    "font.family.mono", "size.control.height", "size.row.height", "size.row.compact",
    "size.row.comfortable", "size.target.min", "space.inset.sm", "space.inset.md",
    "space.stack.md", "motion.duration.instant", "motion.duration.normal",
    "motion.duration.fast", "elevation.4", "font.mono",
)  # fmt: skip
PRIMITIVE_ALIAS = {"elevation.4": "elevation.dialog"}
LUMA_TOKENS = (
    "color.surface.raised", "color.surface.canvas", "color.surface.sunken", "color.text.primary",
    "color.text.secondary", "color.text.tertiary", "color.env.demo", "color.env.live",
    "color.status.success.strong", "color.status.danger.strong", "color.status.warning.strong",
    "color.status.info.strong",
)  # fmt: skip
F18 = re.compile(
    r"from ([\d,.]+), stop ([\d,.]+) \(1R = (\d+)\), price ([\d,.]+);.*?wants ([\d,.]+),"
    r".*?ATR (\d+)\) wants ([\d,.]+)",
    re.DOTALL,
)
F18_KEYS = ("entry", "stop", "one_r", "price", "be_wants", "atr", "atr_wants")
FRAME_SECTIONS = (
    ("scr086_frames", "SCR-086", "3"),
    ("scr087_frames", "SCR-087", "5"),
    ("scr088_deltas", "SCR-088", "7"),
    ("scr089_deltas", "SCR-089", "8"),
)
# name -> (old, new, the expected outcome); CITE-LINE / CITE-FRAG edit the first cite in the spec
MUTATIONS: dict[str, tuple[str, str, str]] = {
    "a section 6 row dropped": ("| `stale_data`", "| `stale_datum`", "FAIL"),
    "a CA quote altered": ("controls always go first.", "controls usually go first.", "FAIL"),
    "a cite's line moved": ("CITE-LINE", "", "WARN"),
    "a cite's fragment gone": ("CITE-FRAG", "", "FAIL"),
}


def rows(table: str) -> list[list[str]]:
    return [[c.strip() for c in ln.split(" | ")] for ln in table.strip("\n").splitlines() if ln]


def read(p: Path) -> str:
    return p.read_text(encoding="utf-8")


def grab(pattern: str, text: str, default: str = "", flags: int = 0) -> str:
    m = re.search(pattern, text, flags)
    return m[1] if m else default


def count(pattern: str, text: str) -> int:
    return len(re.findall(pattern, text, MULTI))


def load_theme(name: str) -> dict[str, object]:
    merged: dict[str, object] = {}
    for f in THEMES[name]:
        data = json.loads(read(TOKENS / f))
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


def routes() -> list[tuple[str, str]]:
    out: list[tuple[str, str]] = []
    for name in ("rules_crud.py", "rules.py"):
        text = read(API / "api" / name)
        out += re.findall(r'@router\.(get|post|put|delete)\("([^"]+)"\)', text)
    return out


def schema_props(api22: str, schema: str) -> list[str]:
    """The property names of one `22` component schema (the block up to the next schema)."""
    block = api22[api22.index(f"    {schema}:\n") + 1 :]
    nxt = re.search(r"\n    [A-Z]", block)
    return re.findall(r"^\s{8}([a-z_]+):", block[: nxt.start()] if nxt else block, MULTI)


def shipped() -> dict[str, Any]:
    """The facts the boards and section 6 quote, parsed from file text (never executed)."""
    engine = read(API / "rules" / "evaluator" / "engine.py")
    runner = read(API / "rules" / "runner.py")
    literals = set(re.findall(r'_skip\([^)\n]*"([a-z_]+)"\)', engine))
    literals |= set(re.findall(r'^\s+return "([a-z_]+)"$', engine, MULTI))
    skipped = sorted(literals)
    if re.search(r'MetricValue\(None, 0, 0, "warmup"\)', runner):
        skipped.append("warmup")
    errors = [c for c, p in zip(ERROR_CODES, ERROR_PROBES, strict=True) if p in engine]
    manager = read(API / "rules" / "manager.py")
    api22 = read(PLAN / "22-api-openapi.yaml")
    ev_block = api22[api22.index("    RuleEvent:\n") :][:600]
    kind22 = grab(r"enum: \[([a-z_, ]+)\],\s*\}\s*payload", ev_block)
    db21 = read(PLAN / "21-database-schema.md")
    kind21 = grab(r"CONSTRAINT re_kind CHECK \(kind IN \(([^)]+)\)\)", db21)
    schemas = read(PLAN / "24-internal-schemas.md")
    audit24 = grab(r"### 15.5 Audited action vocabulary.*?\n\n(.*?)\n\n", schemas, "", re.DOTALL)
    retcodes = schemas[schemas.index("### 8.6 Error mapping") : schemas.index("### 8.7 Rate")]
    retrows = [ln for ln in retcodes.splitlines() if re.match(r"\| (?:`\d|any other)", ln)]
    events = api22[api22.index("operationId: listRuleRunEvents") :][:4000]
    f18 = F18.search(read(MEMO))
    keymap = read(ROOT / "apps" / "web" / "src" / "keymap" / "keymap.json")
    all_routes = routes()
    privacy = r'\*\*"(This file holds the rule\'s logic only[^"]+)"\*\*'
    return {
        "skipped_reasons": skipped,
        "error_codes": errors,
        "compiler_version": grab(r'COMPILER_VERSION = "([^"]+)"', manager),
        "ir_hash_version": int(
            grab(r"IR_HASH_VERSION = (\d+)", read(API / "rules" / "ir" / "canonical.py"), "0")
        ),
        "routes": sorted({f"{m.upper()} {p}" for m, p in all_routes}),
        "runs_route": any("/runs" in p for _m, p in all_routes),
        "export": {
            "format": grab(r'"format": "([^"]+)"', manager),
            "environments_forced": 'scope["environments"] = ["demo"]' in manager,
            "disabled_forced": 'mode="disabled", enabled=False' in manager,
            "import_refused": '"rule.import_refused"' in manager,
        },
        "validator_defers_conflicts": (
            "conflicts between rules are E35-S07" in read(API / "rules" / "validator.py")
        ),
        "rule_run_props": schema_props(api22, "RuleRun"),
        "rule_event_kinds_22": [k.strip() for k in kind22.split(",")] if kind22 else [],
        "rule_event_kinds_21": re.findall(r"'([a-z_]+)'", kind21),
        "priority_lower_first": bool(
            re.search(r"priority\s+smallint NOT NULL DEFAULT 100,\s*-- lower runs first", db21)
        ),
        "skipped_comment_24": grab(r"skipped_reason: str \| None\s*# ([a-z_|.]+)", schemas),
        "audited_rule_keys": re.findall(r"`(rule\.[a-z_]+)`", audit24),
        "oms_codes": sorted(set(re.findall(r"`([A-Z][A-Z_]+)`", "\n".join(retrows))) - {"OK"}),
        "rules_commands": sorted(set(re.findall(r'"(rules\.[a-z_]+)"', keymap))),
        "privacy_note": grab(privacy, read(DESIGN / "E36" / "E36-D03.md")),
        "ca21_d02": grab(r'\| CA-21 +\| [^|]+\| "([^"]+)"', read(DESIGN / "E35" / "E35-D02.md")),
        "f18": dict(zip(F18_KEYS, f18.groups(), strict=True)) if f18 else {},
        "trace": {
            "left": grab(r'left: "([\d.]+)", right: "\d+"', events),
            "right": grab(r'left: "[\d.]+", right: "(\d+)"', events),
            "latency_ms": int(grab(r"latency_ms: (\d+)", events, "0")),
        },
    }


def memo_copy() -> dict[str, tuple[str, list[str]]]:
    """CA id -> (status, the quoted strings of its Proposed column — Plan when unchanged)."""
    out: dict[str, tuple[str, list[str]]] = {}
    for m in re.finditer(
        r"^\| (CA-\d+b?) +\| [^|]+\| (.*?) +\| (.*?) +\| ([a-z-]+(?: \(E3[67][^)]*\))?) +\| ",
        read(MEMO),
        MULTI,
    ):
        status = m[4].split(" ")[0]
        out[m[1]] = (status, re.findall(r'"([^"]+)"', m[2] if status == "unchanged" else m[3]))
    return out


def spec_sections(spec: str) -> dict[str, str]:
    heads = [(m.start(), m[1]) for m in re.finditer(r"^## (\d+)\.", spec, MULTI)]
    return {
        n: spec[pos : heads[i + 1][0] if i + 1 < len(heads) else len(spec)]
        for i, (pos, n) in enumerate(heads)
    }


def cite_check(spec: str) -> tuple[list[str], list[str]]:
    """WARN when a cited line moved (the fragment found elsewhere); FAIL when it is gone."""
    warns, fails = [], []
    for m in CITE.finditer(spec):
        path = DESIGN / m[1].split("-")[0] / f"{m[1]}.md"
        if not path.exists():
            fails.append(f"cite {m[1]}.md:{m[2]}: no such file")
            continue
        lines, n, frag = read(path).splitlines(), int(m[2]), m[3]
        if 0 < n <= len(lines) and frag in lines[n - 1]:
            continue
        found = [i + 1 for i, ln in enumerate(lines) if frag in ln]
        if found:
            warns.append(f'cite {m[1]}.md:{n} "{frag}" drifted — now at line {found[0]}')
        else:
            fails.append(f'cite {m[1]}.md:{n} "{frag}" is gone from the file')
    return warns, fails


def ids_resolve(name: str, t: str) -> list[str]:
    cat14, cat15 = read(PLAN / "14-screens-catalogue.md"), read(PLAN / "15-component-catalogue.md")
    constitution = read(ROOT / "CONSTITUTION.md")
    bad = [f"{name}: the old kill-switch string is present"] if OLD_STRING in t else []
    bad += [f"{name}: forbidden text {p}" for p in FORBIDDEN if re.search(p, t)]
    rules = sorted(set(re.findall(r"\bC-\d+\.\d+\b", t)))
    bad += [f"{name}: dangling rule id {r}" for r in rules if r not in constitution]
    cmps = sorted(set(re.findall(r"\bCMP-\d{3}\b", t)) - NOT_IN_15)
    bad += [f"{name}: no such component {c}" for c in cmps if f"### {c} " not in cat15]
    scrs = sorted(set(re.findall(r"\bSCR-\d{3}\b", t)))
    bad += [f"{name}: no such screen {s}" for s in scrs if f"### {s} " not in cat14]
    return bad


def gates(
    spec: str, hand: str, memo: dict[str, tuple[str, list[str]]], facts: dict[str, Any]
) -> tuple[list[str], list[str]]:
    """The copy gates over the spec and the handoff; returns (failures, cite warnings)."""
    bad: list[str] = []
    sec = spec_sections(spec)
    deck, s6 = sec.get("11", ""), sec.get("6", "")
    if NEW_STRING not in deck:
        bad.append("the #4118 string is missing from section 11")
    for cid in CA_VERBATIM:
        if cid not in memo or not any(s in spec for s in memo[cid][1]):
            bad.append(f"{cid} is not quoted verbatim in the spec")
    for w in BANNED_UI:
        for name, text in (("6", s6), ("11", deck)):
            if re.search(rf"\b{re.escape(w)}", re.sub(r"`[^`]*`", "", text), re.IGNORECASE):
                bad.append(f"banned UI word in section {name}: {w}")
    for row in CA_ROW.finditer(deck):
        cid, text, status = row[1], row[2], row[3]
        if cid not in memo:
            bad.append(f"{cid}: not in the memo")
        elif text not in memo[cid][1]:
            bad.append(f"{cid}: differs from the memo ({status})")
        elif status != memo[cid][0]:
            bad.append(f"{cid}: status {status} vs the memo's {memo[cid][0]}")
    maps = [(m[1], m[2], m[3]) for m in MAP_ROW.finditer(s6)]
    codes = {c for c, _k, _s in maps}
    for code in facts["skipped_reasons"] + facts["error_codes"]:
        if code not in codes:
            bad.append(f"section 6 has no row for the shipped code {code}")
    for code, kind, sentence in maps:
        if len(sentence) > 80:
            bad.append(f"section 6 sentence over 80 characters: {code}")
        if re.search(r"Error\b|Exception|Traceback|timeout_ms|\{error\}", sentence):
            bad.append(f"section 6 sentence carries exception text: {code}")
        if kind == "exchange" and code not in facts["oms_codes"]:
            bad.append(f"section 6 exchange code not in 24 §8.6: {code}")
    for code in ERROR_CODES:
        if not any(c == code and s == GENERIC_ERROR for c, _k, s in maps):
            bad.append(f"section 6: {code} must map to the one generic sentence (BQ-11)")
    for s in (facts["privacy_note"], facts["ca21_d02"]):
        if s and s not in spec:
            bad.append(f"not quoted byte-for-byte: {s[:40]}…")
    bad += ids_resolve(SPEC.name, spec) + ids_resolve(HANDOFF.name, hand)
    rows3 = sec.get("3", "").splitlines()
    pair = next((ln for ln in rows3 if ln.startswith("| `SCR-086/conflicts-stop-pair`")), "")
    if "tighten" not in pair or TIGHTEN not in pair:
        bad.append("the stop-pair frame does not state the tighten-only rule (BQ-8, C-2.6)")
    if re.search(r"Apply (?:arms|also arms)", spec):
        bad.append("the resolver must never arm (BQ-17)")
    warns, fails = cite_check(spec)
    return bad + fails, warns


def mutate(spec: str, old: str, new: str) -> str:
    """A copy of the spec with one edit; the file on disk is never touched."""
    m = CITE.search(spec)
    if old == "CITE-LINE" and m:
        return spec.replace(m[0], m[0].replace(f":{m[2]}`", f":{int(m[2]) + 1}`"), 1)
    if old == "CITE-FRAG" and m:
        return spec.replace(m[0], m[0].replace(m[3], "zzqx not in any file"), 1)
    return spec.replace(old, new)


def selftest(
    spec: str, hand: str, memo: dict[str, tuple[str, list[str]]], facts: dict[str, Any]
) -> tuple[bool, list[str]]:
    bad, warns = gates(spec, hand, memo, facts)
    out, ok = [f"spec: {'pass' if not bad else 'FAIL ' + str(bad)}"], not bad
    for name, (old, new, want) in MUTATIONS.items():
        mutated = mutate(spec, old, new)
        b2, w2 = gates(mutated, hand, memo, facts) if mutated != spec else (bad, warns)
        got = "FAIL" if len(b2) > len(bad) else "WARN" if len(w2) > len(warns) else "pass"
        ok = ok and got == want
        out.append(f"mutation {name}: {got} (expected {want})")
    return ok, out


def matrix_rows(
    themes: dict[str, dict[str, object]], registered: set[tuple[str, str]]
) -> tuple[list[dict[str, object]], list[str], dict[str, int]]:
    matrix: list[dict[str, object]] = []
    out: list[str] = []
    n = {"gated": 0, "proposed": 0, "fails": 0}
    for element, fg, bg, role in rows(PAIRS_TABLE):
        ratios = {th: contrast(resolve(t, fg), resolve(t, bg)) for th, t in themes.items()}
        bar = BAR.get(role)
        if bar is None:
            verdict = "reported, not gated" if role == "decorative" else "rejected, never drawn"
        else:
            n["gated"] += 1
            verdict = "PASS" if all(r >= bar for r in ratios.values()) else "FAIL"
            n["fails"] += verdict == "FAIL"
            n["proposed"] += (fg, bg) not in registered
        reg = "registered" if (fg, bg) in registered else "PROPOSED"
        row: dict[str, object] = {"fg": fg, "bg": bg, "role": role, "verdict": verdict}
        row.update({"pairs": reg, "where": element})
        row.update({k: round(v, 2) for k, v in ratios.items()})
        matrix.append(row)
        shown = " / ".join(show(r) for r in ratios.values())
        out.append(f"{fg} on {bg} | {role} | {shown} | {verdict} | {reg} | {element}")
    return matrix, out, n


def bindings(
    themes: dict[str, dict[str, object]],
) -> tuple[list[str], list[str], dict[str, dict[str, str]]]:
    out: list[str] = []
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
    return out, missing, palette


def facts_lines(f: dict[str, Any]) -> list[str]:
    return [
        f"skipped_reason literals {f['skipped_reasons']} | error codes {f['error_codes']} | "
        f"24 §11.9 comment {f['skipped_comment_24']}",
        f"routes {f['routes']} | a /runs route: {f['runs_route']} (D03-G3) | "
        f"validator defers conflicts: {f['validator_defers_conflicts']} (D03-G2)",
        f"export {f['export']} | COMPILER_VERSION {f['compiler_version']} | "
        f"IR_HASH_VERSION {f['ir_hash_version']}",
        f"22 RuleRun props {f['rule_run_props']} | RuleEvent.kind 22 {f['rule_event_kinds_22']} "
        f"vs 21 {f['rule_event_kinds_21']} (D03-C5) | 21 priority lower-first: "
        f"{f['priority_lower_first']}",
        f"24 audited rule.* {f['audited_rule_keys']} | 24 §8.6 codes {f['oms_codes']} | "
        f"keymap Rules {f['rules_commands']}",
        f"memo F18 {f['f18']} | 22 trace {f['trace']} | E36-D03 privacy note / D02 CA-21 parsed: "
        f"{bool(f['privacy_note'])} / {bool(f['ca21_d02'])}",
    ]


def spec_numbers(spec: str, hand: str, warns: list[str]) -> dict[str, object]:
    sec = spec_sections(spec)
    deck, s14, s0 = sec.get("11", ""), sec.get("14", ""), sec.get("0", "")
    head = spec[: spec.find("## 0.")]
    ca_status: dict[str, int] = {}
    for m in CA_ROW.finditer(deck):
        ca_status[m[3]] = ca_status.get(m[3], 0) + 1
    by_class: dict[str, int] = {}
    for m in MAP_ROW.finditer(sec.get("6", "")):
        by_class[m[2]] = by_class.get(m[2], 0) + 1
    numbers: dict[str, object] = {
        n: count(rf"^\| `{s}/[a-z0-9-]+` +\|", sec.get(k, "")) for n, s, k in FRAME_SECTIONS
    }
    numbers.update(
        {
            "boards": count(r"^\| 0\d +\| `", s0),
            "light_twins": count(r"^\| 0\d +\| `[a-z0-9-]+-light` ", s0),
            "mapping_rows": sum(by_class.values()),
            "mapping_by_class": by_class,
            "ca_rows": sum(ca_status.values()),
            "ca_by_status": ca_status,
            "new_strings": count(r"^\| new-\d+ +\|", deck),
            "reason_keys": count(r"^\| `(?:rbac|rule)\.[a-z_.]+` +\|", deck),
            "g_rows": count(r"^\| D03-G\d+ +\|", s14),
            "c_rows": count(r"^\| D03-C\d+ +\|", s14),
            "a_rows": count(r"^\| D03-A\d+ +\|", s14),
            "d03_q_rows": count(r"^\| D03-Q\d+ +\|", s14),
            "q_rows": count(r"^\| BQ-\d+ +\|", head),
            "q_ruled": count(r"^\| BQ-\d+ +\|.*\| RULED 6381678125(?: \(amended\))? +\|$", head),
            "handoff_blocks": count(r"^## Handoff checklist — ", hand),
            "checklist_ticked": count(r"^\| \[x\] ", head),
            "producibility_rows": count(r"^\| `SCR-08[6-9]/[a-z0-9-]+` +\|", sec.get("9", "")),
            "cites": len(CITE.findall(spec)),
            "cite_warnings": len(warns),
            "blank_checklist_lines": count(r"^- \[[ x~]\] \*\*[^*]+\*\*\s*$", hand),
        }
    )
    return numbers


def main(argv: list[str]) -> int:
    themes = {k: load_theme(k) for k in THEMES}
    facts, memo = shipped(), memo_copy()
    spec = read(SPEC) if SPEC.exists() else ""
    hand = read(HANDOFF) if HANDOFF.exists() else ""
    if "--selftest" in argv:
        passed, lines = selftest(spec, hand, memo, facts)
        print("\n".join(lines))
        print(f"--selftest: {'ok' if passed else 'FAIL'} — {len(MUTATIONS)} mutations in memory")
        return 0 if passed else 1
    pairs_src = read(ROOT / "tools" / "contrast" / "pairs.mjs")
    registered = set(re.findall(r'fg:\s*"([^"]+)",\s*bg:\s*"([^"]+)"', pairs_src))
    matrix, out, n = matrix_rows(themes, registered)
    out.insert(0, "## 1. Measured matrix (fg on bg | role | dark / light / hc | verdict | pairs)")
    alpha = float(resolve(themes["dark"], "opacity.disabled"))
    comp: dict[str, float] = {}
    for th, t in themes.items():
        primary, overlay = resolve(t, "color.action.primary.default"), resolve(
            t, "color.surface.overlay"
        )
        fill = composite(primary, overlay, alpha)
        comp[th] = round(
            contrast(composite(resolve(t, "color.text.on-action"), fill, alpha), fill), 2
        )
    out.append(f"validity composite (label at {alpha} over the dimmed primary fill) | {comp}")
    out.append("\n## 2. Token bindings (token | dark / light / hc)")
    lines, missing, palette = bindings(themes)
    out += lines
    files = {
        f: sum("$value" in v for v in json.loads(read(TOKENS / f)).values())
        for f in THEMES["light"] + (HC,)
    }
    row_h = {k: int(resolve(themes["dark"], f"size.row.{k}")) for k in ("compact", "comfortable")}
    out.append(
        f"token files: {files} | MISSING: {missing} | opacity.disabled = {alpha} | rows {row_h}"
    )
    greyscale = {
        tok: {th: luma601(resolve(t, tok)) for th, t in themes.items()} for tok in LUMA_TOKENS
    }
    out.append(
        f"\n## 3. pairs.mjs: {len(registered)} registered; {n['gated']} gated rows, "
        f"{n['proposed']} PROPOSED"
    )
    out.append("\n## 4. Shipped facts (parsed from text)")
    out += facts_lines(facts)
    out.append("\n## 5. Copy gates")
    bad, warns = gates(spec, hand, memo, facts) if spec else (["spec missing"], [])
    out += [f"WARN {w}" for w in warns]
    out.append(
        "OK — CA-27 / CA-29 verbatim, memo rows byte-equal by status, the #4118 string, every "
        "shipped code mapped, no sentence over 80 or with exception text, no banned UI word, no "
        "private path, ids resolve, cites found, the stop pair tighten-only, no arm here"
        if not bad
        else "\n".join("FAIL " + b for b in bad)
    )
    numbers = spec_numbers(spec, hand, warns)
    numbers.update(
        {
            "pairs_rows": n["gated"],
            "pairs_registered": n["gated"] - n["proposed"],
            "pairs_proposed": n["proposed"],
            "pairs_fail": n["fails"],
            "missing_tokens": len(missing),
            "opacity_disabled": alpha,
            "row_compact": row_h["compact"],
            "row_comfortable": row_h["comfortable"],
            "skipped_codes": len(facts["skipped_reasons"]),
            "error_codes": len(facts["error_codes"]),
            "oms_codes": len(facts["oms_codes"]),
            "routes": len(facts["routes"]),
            "composite": comp,
            "f18": facts["f18"],
            "trace": facts["trace"],
            "compiler_version": facts["compiler_version"],
            "ir_hash_version": facts["ir_hash_version"],
            "token_files": {
                "primitives": files[PRIM],
                "dark": files[DARK],
                "light": files[LIGHT],
                "hc": files[HC],
            },
            "pairs_registry": len(registered),
        }
    )
    if numbers["q_ruled"] != numbers["q_rows"]:
        bad.append(f"BQ rows RULED {numbers['q_ruled']} of {numbers['q_rows']}")
    out.append("\n## 6. Counts: " + json.dumps(numbers, ensure_ascii=False))
    pairs = {str(i): m for i, m in enumerate(matrix)}
    flat = flatten({"numbers": numbers, "pairs": pairs, "greyscale": greyscale})
    if "--check" in argv:
        for m in MARKER.finditer(spec):
            have = flat.get(m[1])
            if have is None:
                bad.append(f"marker {m[1]}: no such key")
            elif str(have) != m[2] and not (
                isinstance(have, int | float) and abs(float(have) - float(m[2])) < 0.006
            ):
                bad.append(f"marker {m[1]}={m[2]} vs {have}")
        marker_bad = [b for b in bad if b.startswith("marker")]
        out.append("\n## 7. --check: " + ("every marker re-derived" if not marker_bad else "FAIL"))
    if "--json" in argv:
        doc: dict[str, object] = {"numbers": numbers, "matrix": matrix, "palette": palette}
        doc.update({"greyscale": greyscale, "missing": missing, "shipped": facts})
        doc.update({"memo_ca": {k: v[0] for k, v in memo.items()}, "warnings": warns})
        doc.update({"problems": bad})
        print(json.dumps(doc, ensure_ascii=False, indent=1))
    else:
        print("\n".join(out))
    return 1 if n["fails"] or bad or numbers["blank_checklist_lines"] else 0


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
