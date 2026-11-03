#!/usr/bin/env python3
"""E26-D07 (#514) check: the deck gates of the replay hand-off pack (PR 1 of 2).

Standalone, offline, stdlib only; it executes no repo code, starts no process and runs under
`python3 -I`. It reads the working tree as text: the copy deck (`docs/design/E26/E26-D07-copy.json`)
and the parent lines it lifts. The shape is the hand-off-pack rule set of the orchestrator's ruling
on the BQ list (comment 6608093192, rule 2): one small index, the deck and this check with its
test; no ruled-pins file. The deck lands first (rule 1); PR 2 adds the pack and its gates here.

- **G-DECK**: every string stands verbatim on its source line, from a parent on `main` (E26-D02;
  E26-D03 and E26-D04 are PENDING, BQ-2); ids are unique; every slot example is in its string.
- **G-LEAK** (SR-097): no string or slot carries a path, a file name, a UUID, an identifier word
  or a slot that would echo the server's text.
- **G-PUBLIC**: no local path, host or worker name in the deck.
- **G-NOCLOSE**: no GitHub closing keyword followed by an issue number in the deck.

`--self-test` applies each mutation in memory and requires that it trips its own gate only.
Exit 0 when every gate passes, 1 otherwise. `--json` prints the findings as JSON.
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from collections.abc import Callable
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[3]
DECK_REL = "docs/design/E26/E26-D07-copy.json"
KEYS: dict[str, str] = {"D02": "docs/design/E26/E26-D02.md"}
DECK_SOURCES = {"D02"}

LEAK = (
    ("a path", re.compile(r"[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+|\\")),
    ("a file name", re.compile(r"\.(?:py|json|parquet|csv|sql|ya?ml|log)\b")),
    (
        "a UUID",
        re.compile(r"[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}", re.IGNORECASE),
    ),
    (
        "an identifier",
        re.compile(
            r"\b(?:dataset|registry|account_id|uid|exchange_uid|replay_?id|session_?id)\b",
            re.IGNORECASE,
        ),
    ),
    ("server text", re.compile(r"\{(?:error|message|reason|detail|path|id)\}")),
)
PUBLIC = re.compile(r"/(?:home|tmp|Users)/|\bscratch-[a-z]+|\b[a-z]+-worker-\d|localhost|\bwt/\d+")
CLOSING = re.compile(
    r"\b(?:close[sd]?|fix(?:e[sd])?|resolve[sd]?)\b:?\s+[\w./-]*#\d+", re.IGNORECASE
)
Texts = dict[str, str]
Mutation = Callable[[Texts], Texts]
GATES = ("G-DECK", "G-LEAK", "G-PUBLIC", "G-NOCLOSE")


def read(rel: str, root: Path) -> list[str]:
    return (root / rel).read_text(encoding="utf-8").split("\n")


def gate_deck(root: Path, t: Texts) -> list[str]:
    bad: list[str] = []
    seen: set[str] = set()
    cache: dict[str, list[str]] = {}
    for e in json.loads(t["deck"])["strings"]:
        key, text, source = str(e["id"]), str(e["string"]), str(e["source"])
        if key in seen:
            bad.append(f"G-DECK {key}: duplicate key")
        seen.add(key)
        alias, _, num = source.partition(":")
        if alias not in DECK_SOURCES or not num.isdigit():
            bad.append(f"G-DECK {key}: source {source} is not a parent on main")
            continue
        lines = cache.setdefault(alias, read(KEYS[alias], root))
        n = int(num)
        if len(text) < 3 or not 1 <= n <= len(lines) or text not in lines[n - 1]:
            bad.append(f"G-DECK {key}: the string is not verbatim on {source}")
        bad += [
            f"G-DECK {key}: slot {s!r} is not in the string" for s in e["slots"] if s not in text
        ]
    return bad


def gate_leak(t: Texts) -> list[str]:
    bad: list[str] = []
    for e in json.loads(t["deck"])["strings"]:
        texts = [str(e["string"]), *map(str, e["slots"].values())]
        bad += [
            f"G-LEAK {e['id']}: {what}" for what, rx in LEAK if any(rx.search(x) for x in texts)
        ]
    return bad


def gate_public(t: Texts) -> list[str]:
    return [f"G-PUBLIC deck: {m}" for m in PUBLIC.findall(t["deck"])]


def gate_noclose(t: Texts) -> list[str]:
    return [f"G-NOCLOSE deck: {m}" for m in CLOSING.findall(t["deck"])]


def texts(root: Path) -> Texts:
    return {"deck": (root / DECK_REL).read_text(encoding="utf-8")}


def check(root: Path = ROOT, t: Texts | None = None) -> list[str]:
    t = t if t is not None else texts(root)
    return [
        *gate_deck(root, t),
        *gate_leak(t),
        *gate_public(t),
        *gate_noclose(t),
    ]


def _deck_edit(t: Texts, edit: Callable[[dict[str, Any]], None]) -> Texts:
    deck = json.loads(t["deck"])
    edit(deck)
    return {**t, "deck": json.dumps(deck, ensure_ascii=False)}


def _first(deck: dict[str, Any], key: str = "") -> dict[str, Any]:
    entries: list[dict[str, Any]] = deck["strings"]
    return next(e for e in entries if not key or e["id"] == key)


KW = "Clo" + "ses"  # a closing keyword, split so this file never holds one
LOCAL = " see /" + "ho" + "me/x"  # a local path shape, split for the same reason
MUTATIONS: tuple[tuple[str, str, Mutation], ...] = (
    (
        "M-01",
        "G-DECK",
        lambda t: _deck_edit(t, lambda d: _first(d).update(string="Choose a window to play")),
    ),
    ("M-02", "G-DECK", lambda t: _deck_edit(t, lambda d: _first(d).update(source="D02:99999"))),
    ("M-03", "G-DECK", lambda t: _deck_edit(t, lambda d: d["strings"].append(dict(_first(d))))),
    (
        "M-04",
        "G-DECK",
        lambda t: _deck_edit(
            t, lambda d: _first(d, "replay.page.revived")["slots"].update({"14:00:00": "x"})
        ),
    ),
    ("M-05", "G-DECK", lambda t: _deck_edit(t, lambda d: _first(d).update(source="D03:343"))),
    (
        "M-06",
        "G-LEAK",
        lambda t: _deck_edit(
            t,
            lambda d: _first(d, "replay.page.revived")["slots"].update(
                {"13:38:04": "e.g. 0a1b2c3d-0a1b-0a1b-0a1b-0a1b2c3d4e5f"}
            ),
        ),
    ),
    (
        "M-07",
        "G-LEAK",
        lambda t: _deck_edit(
            t,
            lambda d: _first(d, "replay.page.revived")["slots"].update(
                {"13:38:04": "the {error} text"}
            ),
        ),
    ),
    ("M-08", "G-PUBLIC", lambda t: _deck_edit(t, lambda d: d.update(note=d["note"] + LOCAL))),
    (
        "M-09",
        "G-NOCLOSE",
        lambda t: _deck_edit(t, lambda d: d.update(note=d["note"] + f" {KW} #514.")),
    ),
)


def self_test(root: Path = ROOT) -> list[str]:
    base = texts(root)
    bad = [f"self-test: the tree fails: {f}" for f in check(root, base)]
    for mid, gate, mutate in MUTATIONS:
        try:
            found = check(root, mutate(base))
        except (ValueError, KeyError, IndexError) as exc:
            found = [f"error: {exc}"]
        if not found or any(not f.startswith(gate + " ") for f in found):
            bad.append(f"self-test {mid} ({gate}) gave {found[:3]}")
    return bad


def main(argv: list[str]) -> int:
    ap = argparse.ArgumentParser(description="E26-D07 hand-off pack check (module docstring)")
    ap.add_argument("--check", action="store_true", help="run the gates (the default)")
    ap.add_argument("--self-test", action="store_true", help="run the gates on each mutation")
    ap.add_argument("--json", action="store_true", help="print the findings as JSON")
    args = ap.parse_args(argv)
    bad = self_test() if args.self_test else check()
    if args.json:
        print(json.dumps({"ok": not bad, "findings": bad}, indent=2))
    else:
        print(
            "\n".join(
                bad + [f"e26_d07_handoff_check: {'PASS' if not bad else 'FAIL'} ({len(bad)})"]
            )
        )
    return 0 if not bad else 1


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
