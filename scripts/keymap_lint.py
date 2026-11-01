#!/usr/bin/env python3
"""E49-T04: prove the default keymap is conflict-free in every context.

Reads apps/web/src/keymap/keymap.json (single source of truth) and
docs/plan/14-screens-catalogue.md. Checks: same-context collisions, undeclared
cross-context shadows, reserved OS/browser/Electron keys, the destructive-command
safety default, hotkey-only (no visible control) commands, keymap<->catalogue drift
and cheatsheet / SCR-113 coverage. Also emits the default-keymap markdown table.

Exit codes: 0 clean, 1 violations, 2 internal error. Stdlib only.
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parent.parent
KEYMAP = ROOT / "apps/web/src/keymap/keymap.json"
CATALOGUE = ROOT / "docs/plan/14-screens-catalogue.md"
RESERVED_FILE = ROOT / "apps/web/src/keymap/reserved-keys.json"  # shared with the TS validator
DOCS_OUT = ROOT / "docs/generated/default-keymap.md"

CONTEXTS = (
    "Global",
    "Workspace",
    "Chart",
    "DOM",
    "Ticket",
    "Positions",
    "Replay",
    "Rules",
    "Admin",
    "Settings",
    "Auth",
    "Tape",
)
MOD_ORDER = ("Ctrl", "Alt", "Shift")
MOD_ALIASES = {
    "ctrl": "Ctrl",
    "control": "Ctrl",
    "cmd": "Ctrl",
    "meta": "Ctrl",
    "mod": "Ctrl",
    "command": "Ctrl",
    "alt": "Alt",
    "option": "Alt",
    "shift": "Shift",
}
KEY_ALIASES = {
    "esc": "Esc",
    "escape": "Esc",
    "del": "Del",
    "delete": "Del",
    "space": "Space",
    "spacebar": "Space",
    "enter": "Enter",
    "return": "Enter",
    "tab": "Tab",
    "arrowleft": "←",
    "arrowright": "→",
    "arrowup": "↑",
    "arrowdown": "↓",
    "left": "←",
    "right": "→",
    "up": "↑",
    "down": "↓",
    "home": "Home",
    "end": "End",
}
NAMED_KEYS = {"Esc", "Del", "Space", "Enter", "Tab", "←", "→", "↑", "↓", "Home", "End"}
POINTER_WORDS = {"click", "drag", "wheel"}
SCREEN_CONTEXT = {
    "SCR-001": "Auth",
    "SCR-010": "Global",
    "SCR-020": "Workspace",
    "SCR-030": "Chart",
    "SCR-050": "DOM",
    "SCR-060": "Ticket",
    "SCR-063": "Positions",
    "SCR-081": "Rules",
    "SCR-082": "Rules",
    "SCR-097": "Replay",
}
RANGE_RE = re.compile(r"^(\d)\.\.(\d)$")
FKEY_RE = re.compile(r"^F([1-9]|1\d|2[0-4])$")


class KeymapError(ValueError):
    """A binding string that cannot be normalised."""


def _split_binding(raw: str) -> list[str]:
    s = raw.strip()
    if not s:
        raise KeymapError("empty binding")
    if s.endswith("++"):  # e.g. Ctrl++
        return [p for p in s[:-2].split("+") if p] + ["+"]
    if s == "+":
        return ["+"]
    parts = s.split("+")
    if parts[-1] == "" and len(parts) > 1:  # trailing '+' key
        return parts[:-2] + ["+"] if parts[-2] == "" else parts[:-1] + ["+"]
    return parts


def _norm_key(key: str) -> str:
    low = key.lower()
    if low in KEY_ALIASES:
        return KEY_ALIASES[low]
    if FKEY_RE.match(key.upper()):
        return key.upper()
    if RANGE_RE.match(key):
        return key
    if len(key) == 1:
        return key.upper()
    raise KeymapError(f"unrecognised key {key!r}")


def normalise(raw: str) -> str:
    """Canonical form: modifiers ordered Ctrl, Alt, Shift; Cmd/Meta/Mod fold to Ctrl."""
    parts = _split_binding(raw)
    if len(parts) == 1 and parts[0].lower() in MOD_ALIASES:  # modifier-only (multi-select)
        return MOD_ALIASES[parts[0].lower()]
    pointer = parts[-1].lower() in POINTER_WORDS
    mods: set[str] = set()
    for p in parts[:-1]:
        m = MOD_ALIASES.get(p.lower())
        if m is None and pointer and p.lower() == "space":
            m = "Space"
        if m is None:
            raise KeymapError(f"unknown modifier {p!r} in {raw!r}")
        mods.add(m)
    key = parts[-1].lower() if pointer else _norm_key(parts[-1])
    return "+".join([m for m in (*MOD_ORDER, "Space") if m in mods] + [key])


def expand(raw: str) -> list[str]:
    """Normalise and expand digit ranges (``1..9``) into atomic bindings."""
    norm = normalise(raw)
    head, _, last = norm.rpartition("+") if not norm.endswith("++") else (norm[:-2], "+", "+")
    mt = RANGE_RE.match(last)
    if not mt:
        return [norm]
    prefix = head + "+" if head else ""
    return [f"{prefix}{d}" for d in range(int(mt.group(1)), int(mt.group(2)) + 1)]


# --------------------------------------------------------------------------- catalogue parsing
HOTKEY_MARK = "**Interactions/hotkeys:**"
SPAN_RE = re.compile(r"`([^`]+)`")
SCR_HEAD_RE = re.compile(r"^### (SCR-\d+)\b")
ARROWS = set("←→↑↓")


def _span_bindings(span: str) -> list[str]:
    """Expand one backtick span (``Ctrl+Z/Ctrl+Y``, ``Alt+↑/↓``, ``Ctrl+/``) to bindings."""
    if span == "/" or span.endswith("+/"):
        return expand(span)
    segs = span.split("/")
    first_parts = _split_binding(segs[0])
    inherited = first_parts[:-1]
    out: list[str] = []
    for i, seg in enumerate(segs):
        if i > 0 and "+" not in seg and inherited and (seg in ARROWS or len(seg) == 1):
            seg = "+".join([*inherited, seg])
        out.extend(expand(seg))
    return out


def parse_catalogue(text: str) -> tuple[dict[str, set[str]], list[str], list[str]]:
    """Return ({screen: bindings}, cheatsheet context groups, errors). Strict: unparseable = error."""
    screens: dict[str, set[str]] = {}
    errors: list[str] = []
    groups: list[str] = []
    current = ""
    for n, line in enumerate(text.splitlines(), 1):
        m = SCR_HEAD_RE.match(line)
        if m:
            current = m.group(1)
        if current == "SCR-013":
            g = re.search(r"grouped by context \(([^)]*)\)", line)
            if g:
                groups = [x.strip() for x in g.group(1).split(",") if x.strip()]
        if HOTKEY_MARK not in line:
            continue
        if not current:
            errors.append(f"catalogue line {n}: hotkeys line outside any SCR section")
            continue
        found: set[str] = set()
        for span in SPAN_RE.findall(line.split(HOTKEY_MARK, 1)[1]):
            try:
                found.update(_span_bindings(span))
            except KeymapError as exc:
                errors.append(f"{current} (catalogue line {n}): unparseable hotkey `{span}`: {exc}")
        screens.setdefault(current, set()).update(found)
    return screens, groups, errors


# --------------------------------------------------------------------------- reserved keys
# binding -> reserving platform(s). Digit ranges are expanded.
_RESERVED_RAW: dict[str, str] = json.loads(RESERVED_FILE.read_text(encoding="utf-8"))
RESERVED: dict[str, str] = {b: why for raw, why in _RESERVED_RAW.items() for b in expand(raw)}


# --------------------------------------------------------------------------- lint core
def _is_single_letter(binding: str) -> bool:
    return len(binding) == 1 and binding.isalpha()


def _declares(a: dict[str, Any], b: dict[str, Any]) -> bool:
    return any(
        s.get("command") == b["id"] and str(s.get("rationale", "")).strip()
        for s in a.get("shadows", []) or []
    )


def _check_command(c: dict[str, Any], safety: bool, errs: list[str]) -> list[str]:
    """Per-command checks; returns the expanded atomic bindings."""
    cid = c.get("id", "<missing id>")
    for field in ("id", "label", "context", "defaultBinding", "destructive", "validWhen"):
        if field not in c:
            errs.append(f"{cid}: missing field {field}")
    if c.get("context") not in CONTEXTS:
        errs.append(f"{cid}: unknown context {c.get('context')!r}")
        return []
    try:
        binds = expand(c["defaultBinding"])
    except (KeymapError, KeyError) as exc:
        errs.append(f"{cid}: invalid binding {c.get('defaultBinding')!r}: {exc}")
        return []
    rationale = str((c.get("reservedOverride") or {}).get("rationale", "")).strip()
    for b in binds:
        why = RESERVED.get(b)
        if why and not rationale:
            errs.append(
                f"{cid}: binding {b} is reserved by {why}; add reservedOverride.rationale "
                "to override deliberately"
            )
        if c.get("destructive") and safety and _is_single_letter(b):
            errs.append(
                f"{cid}: destructive command has bare single-letter binding {b} while "
                "the modifier safety default is on"
            )
    vc = c.get("visibleControl")
    if not (vc is True or (isinstance(vc, str) and vc.strip())):
        errs.append(f"{cid}: hotkey-only command; set visibleControl=true or a rationale string")
    return binds


def lint_keymap(km: dict[str, Any]) -> list[str]:
    errs: list[str] = []
    cmds: list[dict[str, Any]] = km.get("commands", [])
    safety = bool(km.get("safetyModifierDefault", True))
    if not safety:
        errs.append("safetyModifierDefault must stay true (destructive-command safety default)")
    ids: dict[str, dict[str, Any]] = {}
    by_ctx: dict[tuple[str, str], dict[str, dict[str, Any]]] = {}
    by_binding: dict[str, list[dict[str, Any]]] = {}
    for c in cmds:
        cid = c.get("id", "<missing id>")
        if cid in ids:
            errs.append(f"duplicate command id {cid}")
        ids[cid] = c
        for b in _check_command(c, safety, errs):
            by_ctx.setdefault((c["context"], b), {})[cid] = c
            by_binding.setdefault(b, []).append(c)
    for (ctx, b), group in sorted(by_ctx.items()):
        if len(group) > 1:
            errs.append(
                f"conflict in context {ctx}: binding {b} shared by " + " and ".join(sorted(group))
            )
    for b, group in sorted(by_binding.items()):
        outers = [c for c in group if c["context"] == "Global"]
        inner = [c for c in group if c["context"] != "Global"]
        for c in inner:
            for o in outers:
                if not (_declares(c, o) or _declares(o, c)):
                    errs.append(
                        f"undeclared shadow: {c['id']} ({c['context']}) shadows Global "
                        f"{o['id']} on {b}; declare shadows with rationale"
                    )
        for i, a in enumerate(inner):
            for o in inner[i + 1 :]:
                if a["context"] != o["context"] and not (_declares(a, o) and _declares(o, a)):
                    errs.append(
                        f"undeclared reuse of {b}: {a['id']} ({a['context']}) and {o['id']} "
                        f"({o['context']}) must each list the other in shadows with rationale"
                    )
    for c in cmds:
        for s in c.get("shadows", []) or []:
            if s.get("command") not in ids:
                errs.append(f"{c.get('id')}: shadows unknown command {s.get('command')!r}")
            if not str(s.get("rationale", "")).strip():
                errs.append(f"{c.get('id')}: shadows {s.get('command')} without rationale")
    return errs


# --------------------------------------------------------------------------- coverage
def _bindings_of(c: dict[str, Any]) -> set[str]:
    try:
        return set(expand(c["defaultBinding"]))
    except (KeymapError, KeyError):
        return set()


def check_coverage(km: dict[str, Any], catalogue_text: str) -> list[str]:
    screens, _groups, errs = parse_catalogue(catalogue_text)
    cmds = km.get("commands", [])
    cheat = set(km.get("cheatsheetContexts", []))
    for c in cmds:
        if c.get("context") not in cheat:
            errs.append(
                f"{c['id']}: context {c.get('context')} missing from cheatsheet (SCR-013) data"
            )
        if c.get("editable") is False and not str(c.get("editableException", "")).strip():
            errs.append(f"{c['id']}: not editable in SCR-113 and no editableException rationale")
    for scr, bindings in sorted(screens.items()):
        ctx = SCREEN_CONTEXT.get(scr)
        if ctx is None:
            errs.append(
                f"{scr}: hotkeys line present but screen has no context mapping in keymap_lint"
            )
            continue
        have: set[str] = set()
        for c in cmds:
            if c.get("context") == ctx or scr in c.get("screens", []):
                have |= _bindings_of(c)
        for b in sorted(bindings - have):
            errs.append(
                f"{scr}: catalogue documents hotkey {b} but no keymap entry defines it in context {ctx}"
            )
    for c in cmds:
        for scr in c.get("screens", []):
            if scr in screens and not (_bindings_of(c) & screens[scr]):
                errs.append(f"{c['id']}: binding {c['defaultBinding']} not documented on {scr}")
    return errs


# --------------------------------------------------------------------------- docs generator
def _cell(text: str) -> str:
    return text.replace("|", "\\|")


def render_docs(km: dict[str, Any]) -> str:
    lines = [
        "<!-- GENERATED by scripts/keymap_lint.py --docs; do not edit by hand. -->",
        "# Default keymap",
        "",
        "| Context | Command | Default binding | Destructive | Notes |",
        "|---|---|---|---|---|",
    ]
    order = {c: i for i, c in enumerate(CONTEXTS)}
    for c in sorted(km["commands"], key=lambda x: (order.get(x["context"], 99), x["id"])):
        notes = []
        if c.get("reservedOverride"):
            notes.append("overrides reserved key: " + c["reservedOverride"]["rationale"])
        if c.get("validWhen"):
            notes.append("valid when: " + c["validWhen"])
        lines.append(
            f"| {c['context']} | {_cell(c['label'])} | `{_cell(c['defaultBinding'])}` | "
            f"{'yes' if c['destructive'] else 'no'} | {_cell('; '.join(notes))} |"
        )
    return "\n".join(lines) + "\n"


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--keymap", type=Path, default=KEYMAP)
    ap.add_argument("--catalogue", type=Path, default=CATALOGUE)
    ap.add_argument("--docs", action="store_true", help="write the default-keymap markdown table")
    ap.add_argument(
        "--check-docs", action="store_true", help="fail if the committed table is stale"
    )
    ap.add_argument("--docs-out", type=Path, default=DOCS_OUT)
    a = ap.parse_args(argv)
    try:
        km = json.loads(a.keymap.read_text(encoding="utf-8"))
        cat = a.catalogue.read_text(encoding="utf-8")
    except (OSError, json.JSONDecodeError) as exc:
        print(f"keymap-lint: internal error: {exc}", file=sys.stderr)
        return 2
    errs = lint_keymap(km) + check_coverage(km, cat)
    if a.docs:
        a.docs_out.parent.mkdir(parents=True, exist_ok=True)
        a.docs_out.write_text(render_docs(km), encoding="utf-8", newline="\n")
    if a.check_docs:
        cur = a.docs_out.read_text(encoding="utf-8") if a.docs_out.exists() else ""
        if cur != render_docs(km):
            errs.append(f"{a.docs_out.name} is stale; run python scripts/keymap_lint.py --docs")
    for e in errs:
        print(f"keymap-lint: {e}")
    if errs:
        print(f"keymap-lint: {len(errs)} violation(s)")
        return 1
    print(f"keymap-lint: OK ({len(km['commands'])} commands)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
