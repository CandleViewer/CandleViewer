#!/usr/bin/env python3
"""E21-D07 (#576) check: the index, deck, link, hash and open-items gates of the E21 hand-off pack.

R370 BQ-02b's form, which the ruling of record on #576 (comment 6608090271) makes the hand-off-pack
rule: one small check with its test, no ruled-pins file and no helper copy. Offline, stdlib only;
it executes no repo code. It reads the pack (`docs/design/E21/E21-D07.md`) and its copy deck
(`docs/design/E21/E21-D07-copy.json`) from the working tree, and every document they cite AS TEXT
at its pin with `git show` (E21-D05 and E21-D06 are read at their PR heads, so a working-tree read
cannot stand in for them). Three gates carry the ticket's Gherkin scenario names.

- **G-DECK** ("Copy is frozen"): every deck entry's text stands verbatim on its source line at the
  source's pin (whole: no letter or digit runs on at either end); each
  entry has a unique id that starts with its source, a state frame, an accessible-name or
  announcement variant, a known status (or "superseded by" an entry) and an owner issue; the deck's
  pins are this file's; the pack's entry count and per-source counts are the deck's.
- **G-LINK**: every Markdown link in the pack resolves; every `KEY:line` and `` `NN`:line `` cite in
  the pack and in the deck's variants and notes (ranges and `, :n` tails included) names a line
  that exists, and is not blank, in that document at its pin.
- **G-HASH**: every `VALUE<!--=HASH:id-->` equals the first 12 hex digits of the sha256 of the
  block LIFTS names, at the pin; a parent that changes moves the hash, so the lift is re-issued.
- **G-INDEX** ("Self-sufficient handoff"): every element of the build index has its ten facets,
  each with a resolving cite or a section reference; the five elements the ticket names are there;
  the index links `16` section 12 and `05` section 10.
- **G-OPEN** ("Open items are bounded"): every open-items row names an issue (or the owner's) and
  no agent, and a close-by date before Sprint 11 starts (read from CAL at its pin); ids unique;
  the pack's row count is the register's.

`--self-test` applies each mutation of MUTATIONS in memory and requires findings from its gate
only. `--fill` rewrites the HASH and COUNT values. Exit 0 when every gate passes, 1 otherwise.
"""

from __future__ import annotations

import argparse
import datetime
import hashlib
import json
import re
import subprocess
import sys
from collections.abc import Callable
from functools import cache
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[3]
PACK_REL = "docs/design/E21/E21-D07.md"
DECK_REL = "docs/design/E21/E21-D07-copy.json"
#: The deck-first split (the ruling's rule 1) lands the deck and this check before the pack; the
#: pack's gates run only when this is True, which the pack's own slice sets.
PACK_IN_TREE = False

BASE = "b81479ab0"  # origin/main after #5518 merged; every plan and merged-parent cite is read here
PINS: dict[str, tuple[str, str]] = {
    "D02": ("docs/design/E21/E21-D02.md", BASE),  # merged, #5488
    "D03": ("docs/design/E21/E21-D03.md", BASE),  # merged, #5518 (head c7b0d2087, text identical)
    "D04": ("docs/design/E21/E21-D04.md", BASE),  # merged, #5519
    "D04H": ("docs/design/E21/E21-D04-handoff.md", BASE),
    "D05": ("docs/design/E21/E21-D05.md", "e19e7c2a3"),  # #5554 head, if it merges as is
    "D06": ("docs/design/E21/E21-D06.md", "e3fd2b47e"),  # #5601 head, if it merges as is
    "E25D05": ("docs/design/E25/E25-D05.md", BASE),
    "E47D04": ("docs/design/E47/E47-D04.md", BASE),
    "E47D06": ("docs/design/E47/E47-D06.md", BASE),
    "E47D09": ("docs/design/E47/E47-D09.md", BASE),
    "E15H": ("docs/design/specs/e15-handoff.md", BASE),
    "README": ("docs/design/README.md", BASE),
    "CAL": ("docs/plan/backlog/_tools/calendar_cv.py", BASE),
    "DS": (".claude/rules/32-design-specs.md", BASE),
}
PLAN = {
    "02": "docs/plan/02-definition-of-ready-done.md",
    "05": "docs/plan/05-accessibility-standard.md",
    "11": "docs/plan/11-user-stories.md",
    "14": "docs/plan/14-screens-catalogue.md",
    "15": "docs/plan/15-component-catalogue.md",
    "16": "docs/plan/16-design-system-brief.md",
    "23": "docs/plan/23-ws-protocol.md",
    "24": "docs/plan/24-internal-schemas.md",
}
#: id -> (key, heading prefix): the parents' blocks the pack lifts, hashed at their pins.
LIFTS: dict[str, tuple[str, str]] = {
    "d03.s13_1": ("D03", "### 13.1 "),
    "d06.s4": ("D06", "## 4. "),
    "d06.s5_1": ("D06", "### 5.1 "),
    "d06.s7": ("D06", "## 7. "),
    "d06.s9": ("D06", "## 9. "),
    "d06.s13_5": ("D06", "### 13.5 "),
}

ALTS = "|".join(sorted(PINS, key=len, reverse=True))
CITE = re.compile(
    rf"(?:`(?P<nn>\d\d)`|(?<![A-Za-z0-9-])(?P<key>{ALTS})):(?P<a>\d+)(?:–(?P<b>\d+))?"
    r"(?P<more>(?:, :\d+(?:–\d+)?)*)"
)
MORE = re.compile(r":(\d+)(?:–(\d+))?")
LINK = re.compile(r"\]\(([^)\s]+)\)")
HASH = re.compile(r"([0-9a-f]{12})<!--=HASH:([a-z0-9_.]+)-->", re.DOTALL)
COUNT = re.compile(r"(\d+)<!--=COUNT:([a-z.]+)-->", re.DOTALL)
STATE = re.compile(r"^SCR-(?:050|051|153)/[a-z0-9-]+$")
STATUS = ("frozen", "frozen, PROPOSED", "not rendered in E21; E31's")
ELEMENTS = ("Header", "Ladder", "Heatmap frame", "Legend", "Footer")
FACETS = (
    "spec section",
    "components",
    "tokens",
    "redlines",
    "states",
    "keys and focus",
    "live regions",
    "copy ids",
    "motion",
    "a11y requirement",
)
RIDER_LINKS = ("`16`:679", "`05`:308")
REG_ROW = re.compile(r"^\| ((?:D0\d|E\d\dD\d\d) [A-Z]+-\d+) +\|", re.MULTILINE)
AGENT = re.compile(r"\b(?:orchestrator|agent|lane|session|persona|worker)\b", re.IGNORECASE)
DATE = re.compile(r"^\d{4}-\d\d-\d\d$")
SPRINT01 = re.compile(r"SPRINT01_START = datetime\.date\((\d+), (\d+), (\d+)\)")
Edit = Callable[[str, str], tuple[str, str]]  # (pack, deck) -> (pack, deck)


@cache
def show(rel: str, rev: str) -> tuple[str, ...]:
    out = subprocess.run(
        ["git", "show", f"{rev}:{rel}"], cwd=ROOT, capture_output=True, text=True, check=True
    )
    return tuple(out.stdout.split("\n"))


def doc(name: str) -> tuple[str, ...]:
    """A key's or a plan document's lines at its pin."""
    if name in PINS:
        return show(*PINS[name])
    return show(PLAN[name], BASE)


def block(lines: tuple[str, ...] | list[str], prefix: str) -> list[str]:
    """The heading that starts with `prefix` through the line before the next peer heading."""
    start = next(i for i, line in enumerate(lines) if line.startswith(prefix))
    level = len(prefix.split()[0])
    for j in range(start + 1, len(lines)):
        head = lines[j].split(" ", 1)[0]
        if head and set(head) == {"#"} and len(head) <= level:
            return list(lines[start:j])
    return list(lines[start:])


def lift_hash(lift_id: str) -> str:
    key, prefix = LIFTS[lift_id]
    text = "\n".join(block(doc(key), prefix))
    return hashlib.sha256(text.encode("utf-8")).hexdigest()[:12]


def cites(text: str) -> list[tuple[str, int, str]]:
    out: list[tuple[str, int, str]] = []
    for m in CITE.finditer(text):
        name = m.group("nn") or m.group("key")
        if m.group("nn") and name not in PLAN:
            out.append((name, 0, m.group(0)))
            continue
        nums = [m.group("a"), m.group("b")] + [n for p in MORE.findall(m.group("more")) for n in p]
        out += [(name, int(n), m.group(0)) for n in nums if n]
    return out


def rows(text: str, prefix: str) -> list[list[str]]:
    lines = block(text.split("\n"), prefix)
    return [
        [c.strip() for c in line.strip().strip("|").split("|")]
        for line in lines
        if line.startswith("| ") and not set(line) <= set("|-: ")
    ]


def verbatim(text: str, line: str) -> bool:
    """The string stands on the line whole: no letter or digit runs on at either end of it."""
    at = line.find(text)
    while text.strip() and at >= 0:
        before, after = line[at - 1 : at] if at else "", line[at + len(text) : at + len(text) + 1]
        if not (before.isalnum() or after.isalnum()):
            return True
        at = line.find(text, at + 1)
    return False


def gate_deck(pack: str | None, deck: dict[str, Any]) -> list[str]:
    bad: list[str] = []
    for key, src in deck["sources"].items():
        if key not in PINS and key not in PLAN:
            bad.append(f"G-DECK source {key} is not a known key")
        elif key in PINS and [src["path"], src["rev"]] != list(PINS[key]):
            bad.append(f"G-DECK source {key} is not pinned where the check reads it")
    ids = [e["id"] for e in deck["entries"]]
    bad += [f"G-DECK {i} is not unique" for i in sorted({i for i in ids if ids.count(i) > 1})]
    for e in deck["entries"]:
        eid, src = e["id"], e["source"]
        found = cites(src)
        if (
            len(found) != 1
            or eid.split()[0] != found[0][0]
            or eid.split()[0] not in deck["sources"]
        ):
            bad.append(f"G-DECK {eid}: its source {src} is not one line of its own document")
            continue
        lines = doc(found[0][0])
        num = found[0][1]
        if not 1 <= num <= len(lines) or not verbatim(e["text"], lines[num - 1]):
            bad.append(f"G-DECK {eid}: the string is not verbatim on {src}")
        if not STATE.match(e.get("state", "")) or not e.get("a11y", "").strip():
            bad.append(f"G-DECK {eid}: no state frame or no accessible-name variant")
        sup = e["status"].removeprefix("superseded by ")
        if e["status"] not in STATUS and (sup == e["status"] or sup not in ids):
            bad.append(f"G-DECK {eid}: status {e['status']!r}")
        if not re.search(r"#\d+", e.get("owner", "")):
            bad.append(f"G-DECK {eid}: no owner issue")
    if pack is None:
        return bad
    counts = {k: 0 for k in deck["sources"]}
    for i in ids:
        counts[i.split()[0]] = counts.get(i.split()[0], 0) + 1
    table = {r[0]: r[1] for r in rows(pack, "### 8.3 ") if len(r) > 1 and r[0] != "Source"}
    if table != {k: str(v) for k, v in counts.items()} | {"total": str(len(ids))}:
        bad.append(f"G-DECK §8.3's counts {table} are not the deck's")
    stated = [int(n) for n, what in COUNT.findall(pack) if what == "deck.entries"]
    if not stated or any(n != len(ids) for n in stated):
        bad.append(f"G-DECK the pack's entry count {stated} is not the deck's {len(ids)}")
    return bad


def gate_link(pack: str, deck: dict[str, Any]) -> list[str]:
    bad: list[str] = []
    texts = [("pack", n, line) for n, line in enumerate(pack.split("\n"), 1)]
    texts += [(e["id"], 0, e.get("a11y", "") + " " + e.get("note", "")) for e in deck["entries"]]
    for where, n, line in texts:
        for target in LINK.findall(line):
            local = "://" not in target and not target.startswith("#")
            if local and not ((ROOT / PACK_REL).parent / target.split("#", 1)[0]).exists():
                bad.append(f"G-LINK {where}:{n} link {target} does not resolve")
        for name, num, raw in cites(line):
            lines = doc(name) if num else ()
            if not 1 <= num <= len(lines) or not lines[num - 1].strip():
                bad.append(f"G-LINK {where}:{n} {raw}: line {num} is blank or not in {name}")
    return bad


def gate_hash(pack: str) -> list[str]:
    bad: list[str] = []
    seen = set()
    for value, lift_id in HASH.findall(pack):
        seen.add(lift_id)
        if lift_id not in LIFTS:
            bad.append(f"G-HASH unknown lift id {lift_id}")
        elif lift_hash(lift_id) != value:
            bad.append(
                f"G-HASH {lift_id}: the pack says {value}, the source is {lift_hash(lift_id)}"
            )
    return bad + [f"G-HASH {i} is never stated in the pack" for i in sorted(set(LIFTS) - seen)]


def gate_index(pack: str) -> list[str]:
    bad: list[str] = []
    index = "\n".join(block(pack.split("\n"), "## 2. "))
    titles = re.findall(r"^### 2\.\d+ (.+)$", index, re.MULTILINE)
    bad += [f"G-INDEX the element {e} has no table" for e in ELEMENTS if e not in titles]
    for title in titles:
        got = {r[0]: r[1] for r in rows(index, f"### 2.{titles.index(title) + 1} ") if len(r) > 1}
        for facet in FACETS:
            cell = got.get(facet, "")
            if not cites(cell) and "§" not in cell:
                bad.append(f"G-INDEX {title}: the facet {facet} has no cite")
    intro = index.split("### 2.1 ", 1)[0]
    bad += [f"G-INDEX §2 does not link {r}" for r in RIDER_LINKS if r not in intro]
    return bad


def gate_open(pack: str) -> list[str]:
    bad: list[str] = []
    match = SPRINT01.search("\n".join(doc("CAL")))
    if match is None:
        return ["G-OPEN CAL names no Sprint 01 start"]
    sprint11 = datetime.date(*map(int, match.groups())) + datetime.timedelta(days=70)
    register = [r for r in rows(pack, "## 9. ") if REG_ROW.match(f"| {r[0]} |")]
    ids = [r[0] for r in register]
    bad += [f"G-OPEN {i} is not unique" for i in sorted({i for i in ids if ids.count(i) > 1})]
    for r in register:
        if len(r) < 7:
            bad.append(f"G-OPEN {r[0]}: cells missing")
            continue
        if not re.search(r"#\d+", r[3]) or AGENT.search(r[3]):
            bad.append(f"G-OPEN {r[0]}: owner {r[3]!r} is not an issue or the owner")
        if not DATE.match(r[4]) or datetime.date.fromisoformat(r[4]) >= sprint11:
            bad.append(f"G-OPEN {r[0]}: close-by {r[4]!r} is not before {sprint11}")
    stated = [int(n) for n, what in COUNT.findall(pack) if what == "register.rows"]
    if not stated or any(n != len(ids) for n in stated):
        bad.append(f"G-OPEN the pack's row count {stated} is not the register's {len(ids)}")
    return bad


def check(pack: str | None = None, deck: str | None = None) -> list[str]:
    deck_obj = json.loads(deck if deck is not None else (ROOT / DECK_REL).read_text("utf-8"))
    if not PACK_IN_TREE:
        return gate_deck(None, deck_obj)
    text = pack if pack is not None else (ROOT / PACK_REL).read_text("utf-8")
    return [
        *gate_deck(text, deck_obj),
        *gate_link(text, deck_obj),
        *gate_hash(text),
        *gate_index(text),
        *gate_open(text),
    ]


def _deck_edit(fn: Callable[[dict[str, Any]], None]) -> Edit:
    def run(pack: str, deck: str) -> tuple[str, str]:
        obj = json.loads(deck)
        fn(obj)
        return pack, json.dumps(obj)

    return run


def _pack_edit(old: str, new: str) -> Edit:
    def run(pack: str, deck: str) -> tuple[str, str]:
        if old not in pack:
            raise LookupError(f"mutation anchor {old!r} is not in the pack")
        return pack.replace(old, new, 1), deck

    return run


def _set(field: str, value: str) -> Callable[[dict[str, Any]], None]:
    def run(obj: dict[str, Any]) -> None:
        obj["entries"][0][field] = value

    return run


#: (gate, what the mutation does, the edit); each must draw findings from its own gate only.
MUTATIONS: list[tuple[str, str, Edit]] = [
    ("G-DECK", "a deck string reworded", _deck_edit(_set("text", '"DOM ladder, edited"'))),
    ("G-DECK", "an entry loses its accessible-name variant", _deck_edit(_set("a11y", " "))),
    ("G-DECK", "an entry's state is no frame", _deck_edit(_set("state", "somewhere"))),
    (
        "G-DECK",
        "a superseded entry points at nothing",
        _deck_edit(_set("status", "superseded by x")),
    ),
    (
        "G-DECK",
        "a source pinned elsewhere",
        _deck_edit(lambda o: o["sources"]["D02"].update(rev="HEAD")),
    ),
]
PACK_MUTATIONS: list[tuple[str, str, Edit]] = [
    (
        "G-DECK",
        "§8.3 miscounts a source",
        _pack_edit("| D02    | 53      |", "| D02    | 52      |"),
    ),
    ("G-LINK", "a cite past the end of D02", _pack_edit("D02:140 (§2.1", "D02:99999 (§2.1")),
    ("G-LINK", "a link to a missing file", _pack_edit("](E21-D07-copy.json)", "](E21-D07-x.json)")),
    (
        "G-HASH",
        "a lift hash changed",
        lambda p, d: (HASH.sub(r"000000000000<!--=HASH:\2-->", p, 1), d),
    ),
    (
        "G-INDEX",
        "a footer facet dropped",
        _pack_edit("| motion           | none: the sighted", "| moved | none: the sighted"),
    ),
    (
        "G-INDEX",
        "the `16` section 12 link dropped",
        _pack_edit("checklist (`16`:679)", "checklist (`16` §12)"),
    ),
    (
        "G-OPEN",
        "an open item owned by an agent",
        _pack_edit("| E21-D06 #506 (order-flow); arbiters", "| the orchestrator; arbiters"),
    ),
    (
        "G-OPEN",
        "an open item dated after the cut",
        _pack_edit("| 2026-12-03 | E21-S04 Sprint 12", "| 2026-12-10 | E21-S04 Sprint 12"),
    ),
    (
        "G-OPEN",
        "the register's count is off",
        lambda p, d: (
            COUNT.sub(
                lambda m: (
                    "1<!--=COUNT:register.rows-->" if m.group(2) == "register.rows" else m.group(0)
                ),
                p,
            ),
            d,
        ),
    ),
]


def self_test() -> list[str]:
    pack = (ROOT / PACK_REL).read_text("utf-8") if PACK_IN_TREE else ""
    deck = (ROOT / DECK_REL).read_text("utf-8")
    bad: list[str] = []
    for gate, what, edit in MUTATIONS + (PACK_MUTATIONS if PACK_IN_TREE else []):
        new_pack, new_deck = edit(pack, deck)
        got = check(new_pack if PACK_IN_TREE else None, new_deck)
        if not got or any(not f.startswith(gate + " ") for f in got):
            bad.append(f"{gate} '{what}': {got[:3] or 'no finding'}")
    return bad


def fill() -> int:
    """Rewrite every HASH and COUNT value in the pack; return the number of lines changed."""
    path = ROOT / PACK_REL
    text = path.read_text("utf-8")
    deck = json.loads((ROOT / DECK_REL).read_text("utf-8"))
    regs = len([r for r in rows(text, "## 9. ") if REG_ROW.match(f"| {r[0]} |")])
    totals = {"deck.entries": len(deck["entries"]), "register.rows": regs}
    new = HASH.sub(lambda m: f"{lift_hash(m.group(2))}<!--=HASH:{m.group(2)}-->", text)
    new = COUNT.sub(lambda m: f"{totals[m.group(2)]}<!--=COUNT:{m.group(2)}-->", new)
    path.write_text(new, "utf-8")
    return sum(a != b for a, b in zip(text.split("\n"), new.split("\n"), strict=True))


def main(argv: list[str]) -> int:
    ap = argparse.ArgumentParser(description="E21-D07 hand-off pack check (module docstring)")
    ap.add_argument("--check", action="store_true", help="run the gates (the default)")
    ap.add_argument("--self-test", action="store_true", help="run every mutation")
    ap.add_argument("--fill", action="store_true", help="rewrite the HASH and COUNT values")
    ap.add_argument("--json", action="store_true", help="print the findings as JSON")
    args = ap.parse_args(argv)
    if args.fill:
        print(f"filled: {fill()} line(s) changed")
    if args.self_test:
        bad = self_test()
        total = len(MUTATIONS) + (len(PACK_MUTATIONS) if PACK_IN_TREE else 0)
        for finding in bad:
            print(finding)
        print(f"e21_d07_handoff_check --self-test: {total - len(bad)}/{total} caught by their gate")
        return 0 if not bad else 1
    bad = check()
    if args.json:
        print(json.dumps({"ok": not bad, "findings": bad}, indent=2))
    else:
        for finding in bad:
            print(finding)
        print(f"e21_d07_handoff_check: {'PASS' if not bad else 'FAIL'} ({len(bad)} finding(s))")
    return 0 if not bad else 1


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
