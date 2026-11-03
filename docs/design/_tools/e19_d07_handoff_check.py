#!/usr/bin/env python3
"""E19-D07 (#502) check: the link, words, hash, quote, raw-value and deck gates of the hand-off pack.

Standalone, offline, stdlib only; it runs under `python3 -I -B` and starts no process but `git
show`, which reads each source at its pin. The pack is `docs/design/E19/E19-D07.md`, its copy deck
`docs/design/E19/E19-D07-copy.json`. Hand-off-pack rule (2) of the ruling of record (#502 comment
6608092299): one small link-and-hash check with its test, no ruled-pins file, no shared helper.

- **G-LINK**: every Markdown link in the pack resolves; every `` `NN`:line `` or `KEY:line` cite
  (each `, :line` after it and each range end included) names a known source and a line that
  exists and is not blank at that source's pin.
- **G-WORDS**: each load-bearing line (WORDS) still holds its words at its pin and the pack cites it.
- **G-HASH**: each lifted block of §1.3 states the sha256 (whitespace-normalised, first 12 hex) of
  its line span at its pin, and its Lines cell names that span. `--fill` rewrites the values.
- **G-QUOTE**: each row of §6.1 (redlines) and §12 (budgets) quotes words that stand on its single
  Source line; a §6.1 row's numbers stand there too and its Bound cell names a token, a § or a cite.
- **G-RAW** (AC 2): no hex colour, `rgb(` / `hsl(` or `palette.` value in the pack or the deck, and
  no pixel value in the pack on a line without a token name, a pack row id, a § or a cite.
- **G-DECK** (AC 4): each deck entry's string is a whole cell of its source line at its pin; no
  entry is empty, lorem or a to-be-decided marker; each coverage id is an entry; the pack's
  `DECK holds N entries` equals the deck.

Slice 1a ships the deck and this check before the pack: with no pack on disk only the deck-side
gates run and the run says so; the pack-side gates run as soon as the pack lands (slice 1b).
`--self-test` applies each mutation in memory and requires exactly its own gate to fail.
Exit 0 when every gate passes, 1 otherwise; `--json` prints the findings.
"""

from __future__ import annotations

import argparse
import functools
import hashlib
import json
import re
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
PACK_REL = "docs/design/E19/E19-D07.md"
DECK_REL = "docs/design/E19/E19-D07-copy.json"
BASE = "b81479ab0"  # origin/main: every plan file and merged spec is read here
D03_HEAD = "35032f521"  # PR #5517 head (E19-D03, #438); re-pinned to main when it merges
D04_HEAD = "cbd0c7ba9"  # PR #5553 head (E19-D04, #439); re-pinned to main when it merges
D05_HEAD = "c726fa6b8"  # PR #5555 head (E19-D05, #500); re-pinned to main when it merges

_P = "docs/plan/"
_E = "docs/design/E19/E19-"
SOURCES: dict[str, tuple[str, str]] = {
    "02": (_P + "02-definition-of-ready-done.md", BASE),
    "05": (_P + "05-accessibility-standard.md", BASE),
    "06": (_P + "06-performance-and-load-standard.md", BASE),
    "11": (_P + "11-user-stories.md", BASE),
    "14": (_P + "14-screens-catalogue.md", BASE),
    "15": (_P + "15-component-catalogue.md", BASE),
    "16": (_P + "16-design-system-brief.md", BASE),
    "22": (_P + "22-api-openapi.yaml", BASE),
    "23": (_P + "23-ws-protocol.md", BASE),
    "24": (_P + "24-internal-schemas.md", BASE),
    "26": (_P + "26-chart-engine-design.md", BASE),
    "D02": (_E + "D02.md", BASE),
    "D03": (_E + "D03.md", D03_HEAD),
    "D03H": (_E + "D03-handoff.md", D03_HEAD),
    "C15": (_P + "15-component-catalogue.md", D03_HEAD),
    "D04": (_E + "D04.md", D04_HEAD),
    "D05": (_E + "D05.md", D05_HEAD),
    "E12P": ("docs/design/E12/E12-D12.md", BASE),
    "E47D06": ("docs/design/E47/E47-D06.md", BASE),
    "E47D09": ("docs/design/E47/E47-D09.md", BASE),
    "README": ("docs/design/README.md", BASE),
    "R32": (".claude/rules/32-design-specs.md", BASE),
    "E19J": (_P + "backlog/E19.json", BASE),
}
_NAMES = "|".join(sorted((k for k in SOURCES if not k.isdigit()), key=len, reverse=True))
CITE = re.compile(rf"(?:`(\d\d)`|\b({_NAMES}))((?::\d+(?:–\d+)?)(?:, :\d+(?:–\d+)?)*)")
SPAN = re.compile(r"(\d+)(?:–(\d+))?")
LINK = re.compile(r"\]\(([^)\s]+)\)")

#: (source, line, words): the load-bearing lines; the pack must cite each one.
WORDS: tuple[tuple[str, int, str], ...] = (
    ("24", 974, 'kind: Literal["session"'),
    ("24", 987, "trade_count: int"),
    ("24", 1005, "naked_poc_ticks"),
    ("24", 1008, "complete: bool"),
    ("22", 4848, "/market/profile:"),
    ("22", 4891, "minimum: 50, maximum: 95"),
    ("22", 18744, "sources:"),
    ("22", 20577, "naked_poc:"),
    ("22", 20585, "ProfileResponse:"),
    ("23", 753, "`profile.{symbol}.{kind}`"),
    ("23", 1346, "drop `heatmap` and `profile` to 1 000 ms"),
    ("23", 3158, "### 14.6 `ProfileUpdate`"),
    ("14", 1025, "VA % between 1 and 100"),
    ("15", 1301, "client-side derived"),
    ("15", 2955, "`detector: DetectorId`"),
    ("16", 743, 'moved from "Backlog" to "Ready"'),
    ("16", 657, "### 11.5 Change control after sign-off"),
    ("02", 53, "Design has been Done for ≥2 sprints"),
    ("05", 190, "### 6.3 Layer 3"),
    ("06", 78, "Profile/CVD/indicator pane redraw | ≤2ms"),
    ("E47D09", 137, "| a time (anchor, profile range, scrubber) | one bar of the interval"),
    ("E47D06", 132, "designed here; D06-A9"),
    ("E19J", 522, "Sprint 11"),
    ("R32", 15, "G-T2 miss is a Major"),
    ("README", 44, "no exceptions"),
)

#: id -> (source, first line, last line): the blocks §1.3 lifts by hash.
LIFTS: dict[str, tuple[str, int, int]] = {
    "L-1": ("D03H", 10, 32),
    "L-2": ("D03H", 36, 60),
    "L-3": ("D03H", 64, 85),
    "L-4": ("D03H", 89, 131),
    "L-5": ("D05", 199, 210),
    "L-6": ("D05", 214, 244),
    "L-7": ("D05", 267, 284),
}
HEX = re.compile(r"#(?:[0-9a-fA-F]{8}|[0-9a-fA-F]{6}|[0-9a-fA-F]{3,4})\b")
RAW = re.compile(r"\b(?:rgba?|hsla?)\(|\bpalette\.", re.IGNORECASE)
PX = re.compile(r"\d\s?px\b")
BOUND = re.compile(r"`[a-z]+\.[a-z]|\b(?:RL|EL|TK|SD|BU|AS|IA)-\d\d\b|§\d")
JUNK = re.compile(r"\b(?:lorem|ipsum|TBD|TODO|XXX|FIXME)\b", re.IGNORECASE)
COUNT = re.compile(r"DECK holds \*\*(\d+)\*\* entries")
GATES = ("G-LINK", "G-WORDS", "G-HASH", "G-QUOTE", "G-RAW", "G-DECK")
PACK_GATES = ("G-LINK", "G-WORDS", "G-HASH", "G-QUOTE")  # need the pack on disk


@functools.cache
def source(key: str) -> tuple[str, ...]:
    path, pin = SOURCES[key]
    out = subprocess.run(
        ["git", "-C", str(ROOT), "show", f"{pin}:{path}"],
        capture_output=True,
        text=True,
        check=False,
    )
    return tuple(out.stdout.split("\n")) if out.returncode == 0 else ()


def line(key: str, n: int) -> str:
    lines = source(key)
    return lines[n - 1] if 1 <= n <= len(lines) else ""


def cells(row: str) -> list[str]:
    return [c.strip() for c in row.strip().strip("|").split("|")]


def section(pack: str, heading: str) -> list[str]:
    """The lines from the heading that starts with `heading` to the next peer or higher heading."""
    lines = pack.split("\n")
    start = next((i for i, x in enumerate(lines) if x.startswith(heading)), None)
    if start is None:
        return []
    level = len(heading.split(" ", 1)[0])
    for j in range(start + 1, len(lines)):
        mark = lines[j].split(" ", 1)[0]
        if mark and set(mark) == {"#"} and len(mark) <= level:
            return lines[start:j]
    return lines[start:]


def rows(pack: str, heading: str) -> list[list[str]]:
    return [cells(x) for x in section(pack, heading) if re.match(r"\| [A-Z]{1,2}-\d", x)]


def cites(text: str) -> list[tuple[str, int, int]]:
    out: list[tuple[str, int, int]] = []
    for plan, name, tail in CITE.findall(text):
        for lo, hi in SPAN.findall(tail):
            out.append((plan or name, int(lo), int(hi or lo)))
    return out


def lift_hash(lift: str) -> str:
    key, lo, hi = LIFTS[lift]
    flat = " ".join(" ".join(source(key)[lo - 1 : hi]).split())
    return hashlib.sha256(flat.encode("utf-8")).hexdigest()[:12]


def gate_link(pack: str) -> list[str]:
    bad = [f"{k} unreadable at its pin" for k in SOURCES if not source(k)]
    for n, text in enumerate(pack.split("\n"), 1):
        for target in LINK.findall(text):
            path = (ROOT / PACK_REL).parent / target.split("#", 1)[0]
            if "://" not in target and not target.startswith("#") and not path.exists():
                bad.append(f"pack:{n} link {target} does not resolve")
        for key, lo, hi in cites(text):
            if not (line(key, lo).strip() and line(key, hi).strip()) or hi < lo:
                bad.append(f"pack:{n} {key}:{lo}–{hi} is blank or past the end")
    return bad


def gate_words(pack: str) -> list[str]:
    cited = cites(pack)
    bad: list[str] = []
    for key, n, words in WORDS:
        if words not in " ".join(line(key, n).split()):
            bad.append(f"{key}:{n} no longer holds {words!r}")
        if not any(k == key and lo <= n <= hi for k, lo, hi in cited):
            bad.append(f"{key}:{n} ({words!r}) is not cited")
    return bad


def gate_hash(pack: str) -> list[str]:
    table = {r[0]: r for r in rows(pack, "### 1.3 ")}
    bad: list[str] = []
    for lift, (key, lo, hi) in LIFTS.items():
        row = " | ".join(table.get(lift, []))
        if f"`{lift_hash(lift)}`" not in row:
            bad.append(f"{lift} does not state {key} {lo}–{hi}'s hash {lift_hash(lift)}")
        if f"{key} {lo}–{hi}" not in row:
            bad.append(f"{lift} does not name its span {key} {lo}–{hi}")
    return bad


def gate_quote(pack: str) -> list[str]:
    bad: list[str] = []
    for heading, q, s, bound in (("### 6.1 ", 4, 5, 3), ("## 12. ", 2, 3, None)):
        table = rows(pack, heading)
        if not table:
            bad.append(f"no rows under {heading.strip()}")
        for r in table:
            src = cites(r[s]) if len(r) > s else []
            if len(src) != 1 or src[0][1] != src[0][2]:
                bad.append(f"{r[0]} has no single Source line")
                continue
            text = " ".join(line(src[0][0], src[0][1]).split())
            if r[q].strip('"') not in text:
                bad.append(f"{r[0]} quote is not on {src[0][0]}:{src[0][1]}")
            if bound is not None:
                if any(n not in text for n in re.findall(r"\d+(?:\.\d+)?", r[2])):
                    bad.append(f"{r[0]} value is not on {src[0][0]}:{src[0][1]}")
                if not (BOUND.search(r[bound]) or cites(r[bound]) or "D0" in r[bound]):
                    bad.append(f"{r[0]} is bound to nothing")
    return bad


def gate_raw(pack: str | None, deck: str) -> list[str]:
    bad: list[str] = []
    for label, text in (("pack", pack or ""), ("deck", deck)):
        for m in HEX.finditer(text):
            if re.search(r"[a-fA-F]", m.group(0)[1:]) or len(m.group(0)) in (7, 9):
                bad.append(f"{label}: hex {m.group(0)}")
        bad += [f"{label}: raw {m.group(0)}" for m in RAW.finditer(text)]
    for n, text in enumerate((pack or "").split("\n"), 1):
        if PX.search(text) and not (BOUND.search(text) or cites(text)):
            bad.append(f"pack:{n} an unbound pixel value")
    return bad


def gate_deck(pack: str | None, deck: str) -> list[str]:
    obj = json.loads(deck)
    entries: dict[str, dict[str, str]] = obj["entries"]
    bad: list[str] = []
    for wid, e in entries.items():
        src = cites(e.get("source", ""))
        if len(src) != 1 or e["text"] not in cells(line(src[0][0], src[0][1])):
            bad.append(f"{wid}: the string is not a whole cell of {e.get('source')}")
        if not e["text"].strip('" ') or JUNK.search(e["text"]):
            bad.append(f"{wid}: empty or placeholder text")
    for need, ids in obj["coverage"].items():
        bad += [f"coverage {need}: no entry {i}" for i in ids if i not in entries]
    if pack is not None:
        counts = COUNT.findall(pack)
        if counts != [str(len(entries))]:
            bad.append(f"the pack says {counts} entries, the deck holds {len(entries)}")
    return bad


def check(pack: str | None, deck: str) -> dict[str, list[str]]:
    out = {"G-RAW": gate_raw(pack, deck), "G-DECK": gate_deck(pack, deck)}
    if pack is not None:
        out.update(
            {
                "G-LINK": gate_link(pack),
                "G-WORDS": gate_words(pack),
                "G-HASH": gate_hash(pack),
                "G-QUOTE": gate_quote(pack),
            }
        )
    return {g: out[g] for g in GATES if g in out}


def read() -> tuple[str | None, str]:
    pack = ROOT / PACK_REL
    text = pack.read_text(encoding="utf-8") if pack.exists() else None
    return text, (ROOT / DECK_REL).read_text(encoding="utf-8")


#: (gate, target, find, replace): each must make exactly its own gate fail; at least one per
#: gate, and G-RAW and G-DECK each have a deck-side one that runs before the pack lands.
MUTATIONS: tuple[tuple[str, str, str, str], ...] = (
    ("G-LINK", "pack", "(`16`:344)", "(`16`:99999)"),
    ("G-WORDS", "pack", "`23`:3158)", "`23`:3160)"),
    ("G-HASH", "pack", "| L-2 ", "| L-9 "),
    ("G-QUOTE", "pack", '"price gutter 56 px"', '"price gutter 58 px"'),
    ("G-RAW", "pack", "Radius: the canvas draws", "Radius: the canvas #1a2b3c draws"),
    ("G-RAW", "deck", '"pack": "E19-D07"', '"pack": "#a1b2c3"'),
    ("G-DECK", "deck", '"d02:W-23", "d04:W-41"', '"d02:W-99", "d04:W-41"'),
)


def self_test() -> list[str]:
    pack, deck = read()
    bad: list[str] = []
    for gate, target, find, repl in MUTATIONS:
        if target == "pack" and pack is None:
            print(f"self-test {gate}: n/a until the pack lands (slice 1b)")
            continue
        text = pack if target == "pack" else deck
        if text is None or text.count(find) != 1:
            bad.append(f"self-test {gate}: the find text is not unique")
            continue
        mutated = text.replace(find, repl)
        got = check(mutated, deck) if target == "pack" else check(pack, mutated)
        failing = [g for g, f in got.items() if f]
        print(f"self-test {gate}: {'ok' if failing == [gate] else 'BROKEN'} ({failing})")
        if failing != [gate]:
            bad.append(f"self-test {gate}: failing gates {failing}")
    return bad


def fill() -> int:
    """Rewrite the §1.3 hash values; return the number of lines changed."""
    path = ROOT / PACK_REL
    lines = path.read_text(encoding="utf-8").split("\n")
    changed = 0
    for i, text in enumerate(lines):
        m = re.match(r"\| (L-\d) ", text)
        if m and m.group(1) in LIFTS:
            new = re.sub(r"hash `[0-9a-f]{12}`", f"hash `{lift_hash(m.group(1))}`", text)
            changed += new != text
            lines[i] = new
    path.write_text("\n".join(lines), encoding="utf-8")
    return changed


def main(argv: list[str]) -> int:
    ap = argparse.ArgumentParser(description="E19-D07 hand-off pack check (module docstring)")
    ap.add_argument("--check", action="store_true", help="run the gates (the default)")
    ap.add_argument("--json", action="store_true", help="print the findings as JSON")
    ap.add_argument("--self-test", action="store_true", help="one mutation per gate")
    ap.add_argument("--fill", action="store_true", help="rewrite the §1.3 hash values")
    args = ap.parse_args(argv)
    if args.fill:
        print(f"filled: {fill()} line(s) changed")
    if args.self_test:
        bad = self_test()
        print(f"e19_d07_handoff_check self-test: {'ok' if not bad else 'FAIL'}")
        return 0 if not bad else 1
    pack, deck = read()
    result = check(pack, deck)
    findings = [f"{g} {f}" for g, fs in result.items() for f in fs]
    if args.json:
        print(json.dumps({"ok": not findings, "gates": result}, indent=2, ensure_ascii=False))
    else:
        print("\n".join(findings + [f"{g}: {'FAIL' if f else 'PASS'}" for g, f in result.items()]))
        if pack is None:
            print("the pack is not on disk: deck-side gates only (slice 1a)")
        print(f"e19_d07_handoff_check: FAIL {len(findings)}")
    return 0 if not findings else 1


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
