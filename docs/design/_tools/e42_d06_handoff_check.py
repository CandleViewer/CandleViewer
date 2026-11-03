#!/usr/bin/env python3
"""E42-D06 (#961) check: the deck, link, hash, index, contrast and count gates of the hand-off pack.

Standalone, offline, stdlib only; it starts no process and runs under `python3 -I`. It reads the
working tree as text: the pack (`docs/design/E42/E42-D06.md`), its copy deck
(`docs/design/E42/E42-D06-copy.json`), the pattern sheet (`docs/design/E42/E42-patterns.md`), the
token JSON and every file the pack cites by key; the only repo code it runs is `contrast_ratio()`
of `docs/design/_tools/contrast_check.py`, loaded by path. The small check of hand-off-pack rule 2
(the orchestrator's ruling of record, #961 comment 6608091305): no ruled-pins file, no shared helper.

- **G-DECK**: every `entries` string (and each of its `variants`) stands verbatim on its source
  line; a `proposed` literal stands on its source line, or the entry has no line and says so; every
  key a side map names is an entry; every `inherited` cite resolves. At the full stage the pack
  names no key the deck lacks and binds no `retired` key to a §2 element.
- **G-LINK**: every Markdown link in the pack and the sheet resolves; every `` `NN` ``:line and
  KEY:line cite (ranges and `, :n` tails included) names a known file and a non-blank line in it.
- **G-HASH**: every `VALUE<!--=HASH:id-->` equals the first 12 hex digits of the sha256 of the
  block LIFTS names (its heading through the line before the next peer heading): the base-spec
  pins. A parent that changes moves its hash, so the pack is re-read, never quietly stale.
- **G-INDEX**: the review set: every in-set surface has its `14` pointer line and its §2 table,
  SCR-149 has neither (retired under D8); §3 holds P-1 … P-9; every §2 row has eight cells, a deck
  key (or `data:`) for its name and a CMP id `15` defines.
- **G-CONTRAST**: every §4.2 row is recomputed from the token JSON in dark, light and high
  contrast; its three ratios and its verdict match; §4.3's "Now (light)" equals its row's.
- **G-COUNT**: every `N<!--=COUNT:id-->` equals the count the check derives.

`--fill` rewrites the HASH values, the COUNT values and §4.2's ratio and verdict cells.
`--self-test` plants each mutation of MUTATIONS and passes only if each trips its own gate and no
other. STAGE is `deck` in slice 1 (the deck alone; the pack gates report SKIP) and `full` after.
Exit 0 when every gate passes, 1 otherwise.
"""

from __future__ import annotations

import argparse
import functools
import hashlib
import importlib.util
import json
import re
import sys
from collections.abc import Callable
from pathlib import Path
from typing import Any

STAGE = "deck"  # "deck" in slice 1; "full" once the pack lands
ROOT = Path(__file__).resolve().parents[3]
PACK_REL = "docs/design/E42/E42-D06.md"
DECK_REL = "docs/design/E42/E42-D06-copy.json"
SHEET_REL = "docs/design/E42/E42-patterns.md"
CAT_REL = "docs/plan/14-screens-catalogue.md"
TOKENS = "packages/ui/tokens/"

_D = "docs/design/"
KEYS: dict[str, str] = {
    **{f"D0{n}": f"{_D}E42/E42-D0{n}.md" for n in (2, 3, 4, 5)},
    **{f"D0{n}H": f"{_D}E42/E42-D0{n}-handoff.md" for n in (3, 4, 5)},
    "D09": f"{_D}E09/E09-D09.md",
    "E09-D12": f"{_D}E09/E09-D12.md",
    "E16-D06": f"{_D}E16/E16-D06.md",
    "R32": ".claude/rules/32-design-specs.md",
    "E42J": "docs/plan/backlog/E42.json",
    "README": f"{_D}README.md",
    "02": "docs/plan/02-definition-of-ready-done.md",
    "05": "docs/plan/05-accessibility-standard.md",
    "06": "docs/plan/06-performance-and-load-standard.md",
    "14": CAT_REL,
    "15": "docs/plan/15-component-catalogue.md",
    "16": "docs/plan/16-design-system-brief.md",
    "23": "docs/plan/23-ws-protocol.md",
}

#: id -> (key, heading prefix): the parent blocks the pack carries, pinned by hash.
LIFTS: dict[str, tuple[str, str]] = {
    "d03.s13": ("D03", "## 13. "),
    "d03.s14": ("D03", "## 14. "),
    "d04.s12": ("D04", "## 12. "),
    "d04.s13": ("D04", "## 13. "),
    "d04.s14": ("D04", "## 14. "),
    "d05.s8_2": ("D05", "### 8.2 "),
    "d05.s13": ("D05", "## 13. "),
    "d05.s14": ("D05", "## 14. "),
    "d05.s15": ("D05", "## 15. "),
    "e09d12.s5_6": ("E09-D12", "### 5.6 "),
    "14.scr149": ("14", "### SCR-149 "),
}

#: in-set catalogue entries: each carries one E42-D06 pointer line in `14` (SCR-149 is out).
IN_SET = tuple(
    f"SCR-{n:03d}"
    for n in (17, 62, 120, 121, 122, 123, 124, 135, 136, 143, 144, 145, 146, 148, 154, 155)
)
RETIRED_SCR = "SCR-149"
POINTER = "- **A11y review and hand-off (E42-D06):** [E42-D06.md](../design/E42/E42-D06.md)"
THEMES = {
    "dark": ("semantic-dark",),
    "light": ("semantic-dark", "semantic-light"),
    "high-contrast": ("semantic-dark", "semantic-hc"),
}
BARS = {"text": 4.5, "ui": 3.0}
OTHER = {
    "decorative": "info (not a carrier)",
    "rejected": "rejected (never rendered)",
    "retired": "retired (not built)",
}
SEVERITIES = ("Blocking", "Major", "Minor", "Info")

_TAIL = r"((?:\s?[–-]\s?:?\d+)?(?:,\s?:\d+(?:\s?[–-]\s?:?\d+)?)*)"
PLAN_CITE = re.compile(r"`(\d{2})`\s?:(\d+)" + _TAIL)
KEY_CITE = re.compile(r"(?<![\w-])(D0[2-5]H?|D09|E09-D12|E16-D06|R32|E42J|README)\s?:(\d+)" + _TAIL)
NUM = re.compile(r"\d+")
LINK = re.compile(r"\]\(([^)\s]+)\)")
HASH = re.compile(r"([0-9a-f]{12})<!--=HASH:([a-z0-9_.]+)-->", re.DOTALL)
COUNT = re.compile(r"(\d+)<!--=COUNT:([a-z0-9_.]+)-->", re.DOTALL)
SOURCE = re.compile(r"(D0[2-5]H?|\d{2})(?::(\d+))?|D06")
KEY_REF = re.compile(r"`([a-z][a-z0-9_]*\.[a-z0-9_.]+)`")
CMP = re.compile(r"CMP-\d{3}")
Texts = dict[str, str]


def read(rel: str, root: Path) -> list[str]:
    return (root / rel).read_text(encoding="utf-8").split("\n")


def block(lines: list[str], prefix: str) -> list[str]:
    """The heading that starts with `prefix` through the line before the next peer heading."""
    start = next(i for i, line in enumerate(lines) if line.startswith(prefix))
    level = len(prefix.split()[0])
    end = len(lines)
    for j in range(start + 1, len(lines)):
        head = lines[j].split(" ", 1)[0]
        if head and set(head) == {"#"} and len(head) <= level:
            end = j
            break
    return lines[start:end]


def section(text: str, prefix: str) -> str:
    return "\n".join(block(text.split("\n"), prefix))


def rows(text: str) -> list[list[str]]:
    """The body rows of every Markdown table in `text` (header and rule rows dropped)."""
    out: list[list[str]] = []
    lines = text.split("\n")
    for i, line in enumerate(lines):
        if not line.startswith("|") or set(line) <= set("|-: "):
            continue
        if i + 1 < len(lines) and set(lines[i + 1]) <= set("|-: ") and "-" in lines[i + 1]:
            continue
        out.append([c.strip() for c in line.strip().strip("|").split("|")])
    return out


def lift_hash(root: Path, lift_id: str, texts: Texts) -> str:
    key, prefix = LIFTS[lift_id]
    lines = texts["14"].split("\n") if key == "14" else read(KEYS[key], root)
    return hashlib.sha256("\n".join(block(lines, prefix)).encode("utf-8")).hexdigest()[:12]


# ---------- the gates -------------------------------------------------------------------------
def gate_deck(root: Path, t: Texts) -> list[str]:
    deck: dict[str, Any] = json.loads(t["deck"])
    bad: list[str] = [] if deck.get("pack") == "E42-D06" else ["G-DECK the deck is not E42-D06's"]
    cache: dict[str, list[str]] = {}
    keys: dict[str, str] = {}
    proposed: dict[str, str] = deck["proposed"]
    for entry, text in deck["entries"].items():
        src, key = entry.split(" ", 1)
        if key in keys:
            bad.append(f"G-DECK {key} is keyed twice")
        keys[key] = src
        m = SOURCE.fullmatch(src)
        if not m:
            bad.append(f"G-DECK {key}: source {src} is not a cite")
            continue
        line = ""
        if m.group(2):  # an alias alone (`D03`, or `D06` for this pack) names no line
            lines = cache.setdefault(m.group(1), read(KEYS[m.group(1)], root))
            line = lines[int(m.group(2)) - 1] if int(m.group(2)) <= len(lines) else ""
        if key in proposed:
            note = proposed[key]
            if m.group(2) and note not in line:
                bad.append(f"G-DECK {key}: its literal is not on {src}")
            elif not m.group(2) and not note.startswith("no literal"):
                bad.append(f"G-DECK {key}: no source line and no 'no literal' note")
            continue
        for s in [text, *deck["variants"].get(key, [])]:
            if not line or s not in line:
                bad.append(f"G-DECK {key}: {s!r} is not verbatim on {src}")
    for side in ("proposed", "derived", "variants", "security", "conflict", "retired"):
        bad += [f"G-DECK {side} names no entry {k}" for k in deck[side] if k not in keys]
    bad += [f"G-DECK security {k} is empty" for k, v in deck["security"].items() if not v]
    for key, owner in deck["inherited"].items():
        if not cite_ok(root, owner, cache):
            bad.append(f"G-DECK inherited {key}: no resolvable cite in {owner!r}")
    if STAGE == "full":
        known = set(keys) | set(deck["inherited"])
        roots = {k.split(".")[0] for k in known}
        named = [section(t["pack"], h) for h in ("## 2. ", "## 3. ", "### 6.5 ", "### 7.1 ")]
        for k in sorted(set(KEY_REF.findall("\n".join([*named, t["sheet"]])))):
            if k.split(".")[0] in roots and k not in known:
                bad.append(f"G-DECK the pack names {k}, which the deck lacks")
        bound = "\n".join(r[3] for r in rows(section(t["pack"], "## 2. ")) if len(r) > 3)
        bad += [
            f"G-DECK retired {k} is bound to a §2 element"
            for k in sorted(deck["retired"])
            if f"`{k}`" in bound
        ]
    return bad


def cite_ok(root: Path, text: str, cache: dict[str, list[str]]) -> bool:
    found = KEY_CITE.findall(text)
    for key, first, tail in found:
        lines = cache.setdefault(key, read(KEYS[key], root))
        for num in [first, *NUM.findall(tail)]:
            if not 1 <= int(num) <= len(lines) or not lines[int(num) - 1].strip():
                return False
    return bool(found)


def gate_link(root: Path, t: Texts) -> list[str]:
    bad: list[str] = []
    cache: dict[str, list[str]] = {"14": t["14"].split("\n")}
    for name, rel in (("pack", PACK_REL), ("sheet", SHEET_REL)):
        for n, line in enumerate(t[name].split("\n"), 1):
            for target in LINK.findall(line):
                if "://" in target or target.startswith("#"):
                    continue
                if not ((root / rel).parent / target.split("#", 1)[0]).exists():
                    bad.append(f"G-LINK {name}:{n} link {target} does not resolve")
            for key, first, tail in PLAN_CITE.findall(line) + KEY_CITE.findall(line):
                if key not in KEYS:
                    bad.append(f"G-LINK {name}:{n} unknown key {key}")
                    continue
                lines = cache.setdefault(key, read(KEYS[key], root))
                for num in [first, *NUM.findall(tail)]:
                    if not 1 <= int(num) <= len(lines) or not lines[int(num) - 1].strip():
                        bad.append(f"G-LINK {name}:{n} {key}:{num} is blank or past the end")
    return bad


def gate_hash(root: Path, t: Texts) -> list[str]:
    bad: list[str] = []
    seen = set()
    for value, lift_id in HASH.findall(t["pack"]):
        seen.add(lift_id)
        if lift_id not in LIFTS:
            bad.append(f"G-HASH unknown lift id {lift_id}")
        elif (now := lift_hash(root, lift_id, t)) != value:
            bad.append(f"G-HASH {lift_id}: the pack says {value}, the source is {now}")
    bad += [f"G-HASH {i} is never stated in the pack" for i in sorted(set(LIFTS) - seen)]
    return bad


def pointer_entries(cat: str) -> set[str]:
    """The SCR ids whose catalogue entry (### heading to the next) holds the E42-D06 pointer."""
    out: set[str] = set()
    current = ""
    for line in cat.split("\n"):
        if line.startswith("### SCR-"):
            current = line.split(" ", 2)[1]
        elif line.startswith("## "):
            current = ""
        elif line.startswith(POINTER) and current:
            out.add(current)
    return out


def gate_index(root: Path, t: Texts) -> list[str]:
    pack = t["pack"]
    have = pointer_entries(t["14"])
    bad = [f"G-INDEX {s} has no E42-D06 pointer line in `14`" for s in IN_SET if s not in have]
    bad += [f"G-INDEX {s} carries a pointer line but is not in the set" for s in have - set(IN_SET)]
    heads = [ln for ln in section(pack, "## 2. ").split("\n") if ln.startswith("### 2.")]
    bad += [f"G-INDEX {s} has no §2 table" for s in IN_SET if not any(s in h for h in heads)]
    retired_rows = [r for r in rows(section(pack, "### 1.3 ")) if RETIRED_SCR in r[0]]
    if not retired_rows or retired_rows[0][2] != "out":
        bad.append(f"G-INDEX {RETIRED_SCR} is not out of the review set in §1.3")
    paths = {ln[4:7] for ln in pack.split("\n") if ln.startswith("### P-")}
    bad += [f"G-INDEX P-{i} is missing from §3" for i in range(1, 10) if f"P-{i}" not in paths]
    deck: dict[str, Any] = json.loads(t["deck"])
    keys = {e.split(" ", 1)[1] for e in deck["entries"]} | set(deck["inherited"])
    cmps = set(re.findall(r"^### (CMP-\d{3}) ", "\n".join(read(KEYS["15"], root)), re.MULTILINE))
    for r in rows(section(pack, "## 2. ")):
        if len(r) != 8:
            bad.append(f"G-INDEX §2 row {r[0]} has {len(r)} cells, not 8")
            continue
        if not r[3].startswith("data:") and not set(KEY_REF.findall(r[3])) & keys:
            bad.append(f"G-INDEX §2 row {r[0]} names no deck key")
        if not CMP.findall(r[1]) or set(CMP.findall(r[1])) - cmps:
            bad.append(f"G-INDEX §2 row {r[0]}: {r[1]} is not a `15` CMP id")
    return bad


def resolve(tokens: dict[str, Any], value: object, seen: frozenset[str]) -> str:
    """A token's `$value` with every `{ref}` followed; "" for a cycle or a missing ref."""
    if isinstance(value, str) and value.startswith("{") and value.endswith("}"):
        ref = value[1:-1]
        if ref in seen or ref not in tokens:
            return ""
        return resolve(tokens, tokens[ref].get("$value"), seen | {ref})
    return value if isinstance(value, str) else ""


@functools.cache
def themes(root: Path) -> dict[str, dict[str, str]]:
    def load(part: str) -> dict[str, Any]:
        raw = json.loads((root / f"{TOKENS}{part}.tokens.json").read_text(encoding="utf-8"))
        return {k: v for k, v in raw.items() if not k.startswith("$") and isinstance(v, dict)}

    out: dict[str, dict[str, str]] = {}
    for name, parts in THEMES.items():
        tokens = load("primitives")
        for part in parts:
            tokens.update(load(part))
        out[name] = {k: resolve(tokens, v.get("$value"), frozenset({k})) for k, v in tokens.items()}
    return out


def rgb(hexv: str) -> tuple[int, int, int]:
    return int(hexv[1:3], 16), int(hexv[3:5], 16), int(hexv[5:7], 16)


@functools.cache
def ratio_fn(root: Path) -> Callable[[tuple[int, int, int], tuple[int, int, int]], float]:
    spec = importlib.util.spec_from_file_location(
        "contrast_check", root / "docs/design/_tools/contrast_check.py"
    )
    if spec is None or spec.loader is None:
        raise RuntimeError("contrast_check.py is not loadable")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    fn: Callable[[tuple[int, int, int], tuple[int, int, int]], float] = module.contrast_ratio
    return fn


def measure(root: Path, row: list[str]) -> list[str]:
    """The three ratio cells and the verdict a §4.2 row must carry."""
    th, fn = themes(root), ratio_fn(root)
    fg, bg, kind = row[2].strip("`"), row[3].strip("`"), row[4]
    vals = []
    for name in THEMES:
        a, b = th[name].get(fg, ""), th[name].get(bg, "")
        if len(a) != 7 or len(b) != 7:
            return ["?", "?", "?", f"{fg} or {bg} resolves to no colour in {name}"]
        vals.append(float(fn(rgb(a), rgb(b))))
    if kind in BARS:
        verdict = "pass" if all(v >= BARS[kind] for v in vals) else "FAIL"
    else:
        verdict = OTHER.get(kind, f"unknown kind {kind}")
    return [*(f"{v:.2f}" for v in vals), verdict]


def matrix(t: Texts) -> list[list[str]]:
    return [r for r in rows(section(t["pack"], "### 4.2 ")) if r[0].startswith("CP-")]


def gate_contrast(root: Path, t: Texts) -> list[str]:
    bad: list[str] = []
    light: dict[str, str] = {}
    for r in matrix(t):
        want = measure(root, r)
        light[r[0]] = want[1]
        if r[5:9] != want:
            bad.append(f"G-CONTRAST {r[0]} says {r[5:9]}, the tokens give {want}")
    for r in rows(section(t["pack"], "### 4.3 ")):
        if light.get(r[0]) != r[3]:
            bad.append(f"G-CONTRAST §4.3 {r[0]} now (light) {r[3]} is not §4.2's")
    return bad


def counts(t: Texts) -> dict[str, int]:
    pack = t["pack"]
    deck: dict[str, Any] = json.loads(t["deck"])
    els = section(pack, "## 2. ")
    tables = [c for c in els.split("\n### ")[1:] if rows(c)]
    steps = rows(section(pack, "## 3. "))
    cps = matrix(t)
    sev = [r[1] for r in rows(section(pack, "## 8. "))]
    out = {
        "el.rows": len(rows(els)),
        "el.surfaces": len(tables),
        "paths": sum(1 for ln in pack.split("\n") if ln.startswith("### P-")),
        "steps": sum(1 for r in steps if r[0].startswith("P-")),
        "cp.pairs": len(cps),
        "cp.gated": sum(1 for r in cps if r[4] in BARS),
        "cp.passing": sum(1 for r in cps if r[8] == "pass"),
        "mr.rows": len(rows(section(pack, "## 5. "))),
        "cmp.rows": len(rows(section(pack, "## 11. "))),
        "deck.entries": len(deck["entries"]),
        "deck.parent": len(deck["entries"]) - len(deck["proposed"]),
        "deck.proposed": len(deck["proposed"]),
        "deck.inherited": len(deck["inherited"]),
        "deck.retired": len(deck["retired"]),
        "deck.frozen": len(deck["security"]),
        "f.total": len(sev),
    }
    out.update({f"cp.{k}": sum(1 for r in cps if r[4] == k) for k in OTHER})
    out.update({f"f.{s.lower()}": sev.count(s) for s in SEVERITIES})
    return out


def gate_count(root: Path, t: Texts) -> list[str]:
    want = counts(t)
    bad = [
        f"G-COUNT {cid}: the pack says {value}, the check derives {want.get(cid)}"
        for value, cid in COUNT.findall(t["pack"])
        if want.get(cid) != int(value)
    ]
    stated = {cid for _, cid in COUNT.findall(t["pack"])}
    return bad + [f"G-COUNT {cid} is never stated" for cid in sorted(set(want) - stated)]


GATES: dict[str, Callable[[Path, Texts], list[str]]] = {
    "G-DECK": gate_deck,
    "G-LINK": gate_link,
    "G-HASH": gate_hash,
    "G-INDEX": gate_index,
    "G-CONTRAST": gate_contrast,
    "G-COUNT": gate_count,
}
DECK_STAGE = ("G-DECK",)


def texts(root: Path) -> Texts:
    t = {"deck": (root / DECK_REL).read_text(encoding="utf-8")}
    if STAGE == "full":
        t["pack"] = (root / PACK_REL).read_text(encoding="utf-8")
        t["sheet"] = (root / SHEET_REL).read_text(encoding="utf-8")
        t["14"] = (root / CAT_REL).read_text(encoding="utf-8")
    return t


def active() -> list[str]:
    return list(GATES) if STAGE == "full" else list(DECK_STAGE)


def check(root: Path = ROOT, override: Texts | None = None) -> list[str]:
    t = {**texts(root), **(override or {})}
    return [f for gate in active() for f in GATES[gate](root, t)]


# ---------- self-test ---------------------------------------------------------------------------
#: (id, gate, target, find, replace): each must trip its own gate and no other.
MUTATIONS: tuple[tuple[str, str, str, str, str], ...] = (
    ("M-1", "G-DECK", "deck", "Acknowledging isn't built yet.", "Acknowledging is not built."),
    ("M-2", "G-DECK", "deck", '\\"Acknowledge: {title}\\"', '\\"Acknowledge {title}\\"'),
    ("M-3", "G-DECK", "deck", '"gate.wrong": "SCR-149', '"gate.wrongly": "SCR-149'),
    ("M-4", "G-DECK", "deck", "E09-D09 (D09:95)", "E09-D09 (D09:99999)"),
)
FULL_MUTATIONS: tuple[tuple[str, str, str, str, str], ...] = ()


def mutations() -> tuple[tuple[str, str, str, str, str], ...]:
    return MUTATIONS + (FULL_MUTATIONS if STAGE == "full" else ())


def self_test(root: Path = ROOT) -> list[str]:
    base = texts(root)
    bad = [f"the tree itself fails: {f}" for f in check(root, base)]
    for mid, gate, target, find, repl in mutations():
        if base[target].count(find) < 1:
            bad.append(f"{mid}: {find!r} is not in {target}")
            continue
        got = check(root, {target: base[target].replace(find, repl, 1)})
        tripped = {f.split(" ", 1)[0] for f in got}
        if tripped != {gate}:
            bad.append(f"{mid}: expected only {gate}, got {sorted(tripped) or 'nothing'}")
    return bad


# ---------- fill --------------------------------------------------------------------------------
def fill(root: Path = ROOT) -> int:
    """Rewrite the HASH and COUNT values and §4.2's measured cells; return the lines changed."""
    path = root / PACK_REL
    t = texts(root)
    text = t["pack"]
    new = HASH.sub(lambda m: f"{lift_hash(root, m.group(2), t)}<!--=HASH:{m.group(2)}-->", text)
    lines = new.split("\n")
    for i, line in enumerate(lines):
        if line.startswith("| CP-"):
            cells = [c.strip() for c in line.strip().strip("|").split("|")]
            if len(cells) == 9 and cells[5:9] != (measured := measure(root, cells)):
                cells[5:9] = measured  # unaligned; Prettier re-aligns the table
                lines[i] = "| " + " | ".join(cells) + " |"
    new = "\n".join(lines)
    want = counts({**t, "pack": new})
    new = COUNT.sub(lambda m: f"{want.get(m.group(2), 0)}<!--=COUNT:{m.group(2)}-->", new)
    changed = sum(a != b for a, b in zip(text.split("\n"), new.split("\n"), strict=True))
    path.write_text(new, encoding="utf-8")
    return changed


def main(argv: list[str]) -> int:
    ap = argparse.ArgumentParser(description="E42-D06 hand-off pack check (module docstring)")
    mode = ap.add_mutually_exclusive_group(required=True)
    mode.add_argument("--check", action="store_true", help="run every gate of the stage")
    mode.add_argument("--self-test", action="store_true", help="plant each mutation")
    mode.add_argument("--fill", action="store_true", help="rewrite HASH, COUNT and §4.2 cells")
    args = ap.parse_args(argv)
    if args.fill:
        if STAGE != "full":
            print("--fill needs the full stage")
            return 1
        print(f"filled: {fill()} line(s) changed")
        return 0
    if args.self_test:
        bad = self_test()
        for finding in bad:
            print(finding)
        print(f"self-test: {'ok' if not bad else 'FAIL'} ({len(mutations())} mutation(s))")
        return 0 if not bad else 1
    bad = check()
    for finding in bad:
        print(finding)
    skipped = [g for g in GATES if g not in active()]
    for gate in skipped:
        print(f"SKIP {gate} (stage {STAGE})")
    print(f"e42_d06_handoff_check: {'PASS' if not bad else 'FAIL'} ({len(bad)} finding(s))")
    return 0 if not bad else 1


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
