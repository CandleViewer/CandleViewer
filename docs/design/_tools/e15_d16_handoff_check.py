#!/usr/bin/env python3
"""E15-D16 (#370) check: the index, deck, link and hash gates of the E15 hand-off pack.

Standalone, offline, stdlib only; it executes no repo code, starts no process and runs under
`python3 -I`. It reads the working tree as text: the pack (`docs/design/specs/e15-handoff.md`),
its copy deck (`docs/design/E15/E15-D16-copy.json`), `18` §2.16 and every file the pack cites by
key. Option 2 of the orchestrator's ruling on the BQ list: four gates, no ruled-pins file.

- **G-LINK** (T test plan item 7): every Markdown link in the pack resolves to a file; every
  `` `KEY`:line `` cite (and each `:line` that follows it, ranges included) names a key the
  table below knows and a line that exists, and is not blank, in that file.
- **G-HASH** (lifted blocks): every `VALUE<!--=HASH:id-->` equals the first 12 hex digits of the
  sha256 of the block LIFTS names (its heading line through the line before the next heading of
  the same or a higher level). A parent that changes moves the hash, so the pack is re-issued
  under its late-change rule rather than quietly out of date. `--fill` rewrites the values.
- **G-INDEX** (AC 1; T test plan item 1): every US-LAY story of `18` §2.16 has rows in the pack's
  §2; together they name every screen and component `18` lists for the story, and the story's
  first row cites a spec section (a `§`).
- **G-DECK** (AC 4; T test plan item 4): every deck entry `ALIAS:line id` holds a string that
  stands verbatim and whole on that line of its source (a quoted string with both its quotes, so a
  fragment of a longer string fails; a bare string as a whole table cell); every concept group lists existing entries and is
  named in the pack; the pack's entry count equals the deck's.

`--check` exits 1 on any finding (without it the run only reports). `--self-test` applies one
mutation per gate to in-memory copies and passes only when each adds exactly one new finding of its
gate, a re-run reproduces the base result and no file on disk changed. `--json` prints the findings.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import sys
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[3]
PACK_REL = "docs/design/specs/e15-handoff.md"
DECK_REL = "docs/design/E15/E15-D16-copy.json"
PLAN18_REL = "docs/plan/18-traceability-matrix.md"

E15 = "docs/design/E15/E15-"
KEYS: dict[str, str] = {
    **{f"D{n:02d}": f"{E15}D{n:02d}.md" for n in range(2, 16)},
    **{
        f"D{n:02d}H": f"{E15}D{n:02d}-handoff.md"
        for n in (3, 4, 5, 6, 7, 10, 11, 12, 13)
    },
    "LF": "docs/design/specs/e15-layout-flows.md",
    "MG": "docs/design/specs/e15-multichart-grid.md",
    "RD": "docs/design/specs/e15-responsive-and-degraded.md",
    "DSC": "docs/design/specs/e15-design-system-contributions.md",
    "02": "docs/plan/02-definition-of-ready-done.md",
    "03": "docs/plan/03-testing-strategy.md",
    "05": "docs/plan/05-accessibility-standard.md",
    "11": "docs/plan/11-user-stories.md",
    "12": "docs/plan/12-sitemap.md",
    "14": "docs/plan/14-screens-catalogue.md",
    "15": "docs/plan/15-component-catalogue.md",
    "16": "docs/plan/16-design-system-brief.md",
    "18": PLAN18_REL,
    "RULE": ".claude/rules/32-design-specs.md",
    "FER": ".claude/rules/30-frontend-react.md",
    "README": "docs/design/README.md",
    "CON": "CONSTITUTION.md",
    "E15J": "docs/plan/backlog/E15.json",
    "CAL": "docs/plan/backlog/_tools/calendar_cv.py",
}

#: id -> (key, heading prefix): the blocks the pack lifts by hash.
LIFTS: dict[str, tuple[str, str]] = {
    "d15.s1_6": ("D15", "### 1.6 "),
    "d15.s3_1": ("D15", "### 3.1 "),
    "d15.s4": ("D15", "## 4. "),
    "d15.s5_2": ("D15", "### 5.2 "),
    "d15.s6_1": ("D15", "### 6.1 "),
    "d15.s7": ("D15", "## 7. "),
    "d15.s8_1": ("D15", "### 8.1 "),
    "d15.s8_2": ("D15", "### 8.2 "),
    "d15.s11": ("D15", "## 11. "),
    "d14.s2": ("D14", "## 2. "),
    "d14.s4": ("D14", "## 4. "),
    "d13h.k": ("D13H", "## Table K "),
    "d13h.n": ("D13H", "## Table N "),
    "d13h.s": ("D13H", "## Table S "),
}

CITE = re.compile(r"`([A-Z0-9]{2,6})`((?::\d+(?:–:?\d+)?)(?:, :\d+(?:–:?\d+)?)*)")
NUM = re.compile(r"\d+")
LINK = re.compile(r"\]\(([^)\s]+)\)")
HASH = re.compile(r"([0-9a-f]{12})<!--=HASH:([a-z0-9_.]+)-->")
COUNT = re.compile(r"(\d+)<!--=COUNT:deck\.entries-->")
STORY = re.compile(r"\*\*(US-LAY-00\d)\*\*")
IDS = re.compile(r"(?:SCR|CMP)-\d{3}")


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


def lift_hash(root: Path, lift_id: str) -> str:
    key, prefix = LIFTS[lift_id]
    text = "\n".join(block(read(KEYS[key], root), prefix))
    return hashlib.sha256(text.encode("utf-8")).hexdigest()[:12]


def gate_link(root: Path, pack: str) -> list[str]:
    bad: list[str] = []
    files: dict[str, list[str]] = {}
    for n, line in enumerate(pack.split("\n"), 1):
        for target in LINK.findall(line):
            if "://" in target or target.startswith("#"):
                continue
            path = (root / PACK_REL).parent / target.split("#", 1)[0]
            if not path.exists():
                bad.append(f"G-LINK pack:{n} link {target} does not resolve")
        for key, tail in CITE.findall(line):
            if key not in KEYS:
                bad.append(f"G-LINK pack:{n} unknown key `{key}`")
                continue
            lines = files.setdefault(key, read(KEYS[key], root))
            for num in NUM.findall(tail):
                if not 1 <= int(num) <= len(lines) or not lines[int(num) - 1].strip():
                    bad.append(
                        f"G-LINK pack:{n} `{key}`:{num} is blank or past the end of {KEYS[key]}"
                    )
    return bad


def gate_hash(root: Path, pack: str) -> list[str]:
    bad: list[str] = []
    seen = set()
    for value, lift_id in HASH.findall(pack):
        seen.add(lift_id)
        if lift_id not in LIFTS:
            bad.append(f"G-HASH unknown lift id {lift_id}")
        elif lift_hash(root, lift_id) != value:
            bad.append(
                f"G-HASH {lift_id}: the pack says {value}, the source is {lift_hash(root, lift_id)}"
            )
    bad += [
        f"G-HASH {lift_id} is never stated in the pack"
        for lift_id in sorted(set(LIFTS) - seen)
    ]
    return bad


def plan18_rows(root: Path) -> dict[str, set[str]]:
    rows: dict[str, set[str]] = {}
    for line in block(read(PLAN18_REL, root), "### 2.16 "):
        story = STORY.search(line)
        if story:
            rows[story.group(1)] = set(
                IDS.findall(line.split("|")[3] + line.split("|")[4])
            )
    return rows


def gate_index(root: Path, pack: str) -> list[str]:
    bad: list[str] = []
    lines = block(pack.split("\n"), "## 2. ")
    for story, wanted in sorted(plan18_rows(root).items()):
        rows = [line for line in lines if line.startswith(f"| {story} ")]
        if not rows:
            bad.append(f"G-INDEX {story} has no row in §2")
            continue
        if "§" not in rows[0]:
            bad.append(f"G-INDEX {story}: its first row cites no spec section")
        missing = wanted - set(IDS.findall(" ".join(rows)))
        if missing:
            bad.append(
                f"G-INDEX {story} omits {', '.join(sorted(missing))} (`18` §2.16)"
            )
    return bad


def verbatim(text: str, line: str) -> bool:
    """A quoted string must stand whole, quotes included; a bare one must be a whole table cell."""
    if len(text) >= 3 and text[0] == text[-1] == '"':
        return text in line
    return any(
        text in (cell.strip(), cell.strip().strip("`*")) for cell in line.split("|")
    )


def gate_deck(root: Path, pack: str, deck: dict[str, Any]) -> list[str]:
    bad: list[str] = []
    entries: dict[str, str] = deck["entries"]
    cache: dict[str, list[str]] = {}
    for key, text in entries.items():
        alias, rest = key.split(":", 1)
        num = int(rest.split(" ", 1)[0])
        if alias not in KEYS:
            bad.append(f"G-DECK {key}: unknown source key")
            continue
        lines = cache.setdefault(alias, read(KEYS[alias], root))
        if not (1 <= num <= len(lines)) or not verbatim(text, lines[num - 1]):
            bad.append(f"G-DECK {key}: the string is not verbatim on its source line")
    for group, members in deck["concepts"].items():
        bad += [f"G-DECK {group}: no entry {m}" for m in members if m not in entries]
        if group not in pack:
            bad.append(f"G-DECK {group} is not named in the pack")
    counts = COUNT.findall(pack)
    if not counts or any(int(c) != len(entries) for c in counts):
        bad.append(
            f"G-DECK the pack's entry count {counts} is not the deck's {len(entries)}"
        )
    return bad


def check(
    root: Path = ROOT, pack: str | None = None, deck: str | None = None
) -> list[str]:
    pack_text = (
        pack if pack is not None else (root / PACK_REL).read_text(encoding="utf-8")
    )
    deck_text = (
        deck if deck is not None else (root / DECK_REL).read_text(encoding="utf-8")
    )
    return [
        *gate_link(root, pack_text),
        *gate_hash(root, pack_text),
        *gate_index(root, pack_text),
        *gate_deck(root, pack_text, json.loads(deck_text)),
    ]


def fill(root: Path = ROOT) -> int:
    """Rewrite every HASH value and the deck count in the pack; return the number changed."""
    path = root / PACK_REL
    text = path.read_text(encoding="utf-8")
    total = len(json.loads((root / DECK_REL).read_text(encoding="utf-8"))["entries"])
    new = HASH.sub(
        lambda m: f"{lift_hash(root, m.group(2))}<!--=HASH:{m.group(2)}-->", text
    )
    new = COUNT.sub(f"{total}<!--=COUNT:deck.entries-->", new)
    changed = sum(
        a != b for a, b in zip(text.split("\n"), new.split("\n"), strict=True)
    )
    path.write_text(new, encoding="utf-8")
    return changed


def _mut_link(pack: str, deck: str) -> tuple[str, str]:
    return pack + "\n`D15`:999999\n", deck


def _mut_hash(pack: str, deck: str) -> tuple[str, str]:
    value, lift_id = HASH.findall(pack)[0]
    old = f"{value}<!--=HASH:{lift_id}-->"
    return pack.replace(old, f"000000000000<!--=HASH:{lift_id}-->", 1), deck


def _mut_index(pack: str, deck: str) -> tuple[str, str]:
    kept = [line for line in pack.split("\n") if not line.startswith("| US-LAY-008 ")]
    return "\n".join(kept), deck


def _mut_deck(pack: str, deck: str) -> tuple[str, str]:
    data = json.loads(deck)
    key = next(iter(data["entries"]))
    data["entries"][key] += " (mutated)"
    return pack, json.dumps(data)


MUTATIONS = (
    ("G-LINK", _mut_link),
    ("G-HASH", _mut_hash),
    ("G-INDEX", _mut_index),
    ("G-DECK", _mut_deck),
)


def self_test(root: Path = ROOT) -> list[str]:
    """One mutation per gate on in-memory copies; each must add exactly one finding of its gate."""
    paths = [root / PACK_REL, root / DECK_REL]
    before = [hashlib.sha256(p.read_bytes()).hexdigest() for p in paths]
    pack, deck = (p.read_text(encoding="utf-8") for p in paths)
    base = check(root, pack=pack, deck=deck)
    bad: list[str] = []
    for gate, mutate in MUTATIONS:
        m_pack, m_deck = mutate(pack, deck)
        if (m_pack, m_deck) == (pack, deck):
            bad.append(f"self-test {gate}: the mutation did not apply")
            continue
        new = [f for f in check(root, pack=m_pack, deck=m_deck) if f not in base]
        if len(new) != 1 or not new[0].startswith(f"{gate} "):
            bad.append(
                f"self-test {gate}: expected one new {gate} finding, got {new[:3]}"
            )
    if check(root, pack=pack, deck=deck) != base:
        bad.append("self-test: a re-run does not reproduce the base result")
    if [hashlib.sha256(p.read_bytes()).hexdigest() for p in paths] != before:
        bad.append("self-test: a file on disk changed")
    return bad


def main(argv: list[str]) -> int:
    ap = argparse.ArgumentParser(
        description="E15-D16 hand-off pack check (module docstring)"
    )
    ap.add_argument(
        "--fill", action="store_true", help="rewrite the HASH values and the count"
    )
    ap.add_argument("--json", action="store_true", help="print the findings as JSON")
    ap.add_argument("--check", action="store_true", help="exit 1 on any finding")
    ap.add_argument("--self-test", action="store_true", help="one mutation per gate")
    args = ap.parse_args(argv)
    if args.fill:
        print(f"filled: {fill()} line(s) changed")
    bad = check()
    st = self_test() if args.self_test else []
    if args.json:
        payload: dict[str, Any] = {"ok": not bad, "findings": bad}
        if args.self_test:
            payload["self_test"] = st
        print(json.dumps(payload, indent=2))
    else:
        for finding in bad + st:
            print(finding)
        print(
            f"e15_d16_handoff_check: {'PASS' if not bad else 'FAIL'} ({len(bad)} finding(s))"
        )
        if args.self_test:
            print(
                f"self-test: {'ok' if not st else 'FAILED'}: {len(MUTATIONS)} mutations, one per "
                "gate, each one new finding; a re-run reproduces; files on disk unchanged"
            )
    failed = (bool(bad) and args.check) or bool(st)
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
