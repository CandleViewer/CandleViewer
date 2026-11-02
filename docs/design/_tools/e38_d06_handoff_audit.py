#!/usr/bin/env python3
"""E38-D06 (#1077) audit: the engineering hand-off pack for the E38 surfaces.

Standalone, offline, stdlib only; run it with `python3 -I`. It reads the pack, the copy
deck and the pins file from the working tree, and every cited file AS TEXT with
`git show`: the plan docs, E09-D09, E10-D03, E10-D04, the design-spec rules and the
sprint calendar at the pinned base (`BASE`), and the five unmerged parents at their
pinned heads (`REF_OF`): the E38-D01 memo at #5451's, E38-D02 at #5494's, E38-D03 at
#5493's, E38-D04 at #5490's and E38-D05 at its head (#1076), each "if it merges as is".
For the token names it imports `packages/ui/tokens/tests/verify_tokens.py` (the token
loader) from the working tree and never re-implements it. Default-deny: a gate that
cannot read its input FAILs.

Two modes, chosen by the working tree. Full mode (the pack and the pins file both
present) runs every gate. Deck-only mode (neither present: the deck lands first, in
its own PR) runs G-COPY on the deck alone (ids, statuses, owners, sources, the
verbatim match, the two required notices), G-HYGIENE on the deck and this tool, and
G-SCOPE against the deck and this tool only. With one of the two files present the
mode is full, so the missing one FAILs its gates (default-deny).

Gates (each FAIL led by its name):
  G-STATES     every state id of D02's and D03's state tables, every frame name of
               their §0 tables and every D04 badge and block state stands in the pack's
               §3 or §2; the pack's diagram equals D02 §5's, line for line.
  G-COPY       the copy deck parses with unique ids; each string stands verbatim on its
               cited source line at its ref; `final` only from a merged source; every
               PROPOSED string names an owner; the two required notices are present
               with their texts and sources and quoted in the pack; §8's tables equal
               the deck; the COPY anchors equal the deck's counts.
  G-COMPONENT  the eleven catalogue components of the ticket each have a §9 row naming
               a screen, and their `15` heading at the base starts with the row's name.
  G-TOKEN      every token the pack names resolves in the merged token sets of every
               theme (dark, light, high-contrast as verify_tokens merges them).
  G-EVENT      every backticked event of §12 stands on one of its row's cited lines.
  G-QUESTION   every §13 row has an owner and a "resolution:" or "follow-up:" with text.
  G-AROW       every §17.1 A-row's Old text or anchor stands exactly once in its target
               at the base, on the line its header cites.
  G-CITE       every cite in range and on a non-blank line at its ref, its content equal
               to the pins file's hash; the SHA anchors are the pinned refs.
  G-HYGIENE    no closing keyword, local path, URL or host, agent name, double-brace
               slot or public-text deny word in the pack, the deck, this tool or the
               pins file; no unknown anchor.
  G-SCOPE      the diff against `git merge-base HEAD origin/main` touches only the pack,
               the deck, this tool and the pins file.

Usage (from the repo root):
  python3 -I docs/design/_tools/e38_d06_handoff_audit.py --check
  python3 -I docs/design/_tools/e38_d06_handoff_audit.py --json
  python3 -I docs/design/_tools/e38_d06_handoff_audit.py --self-test
  python3 -I docs/design/_tools/e38_d06_handoff_audit.py --repin-ruled
  (--check exits 1 on any FAIL; --repin-ruled is the pins file's only writer)
"""

from __future__ import annotations

import argparse
import hashlib
import importlib.util
import json
import re
import subprocess
import sys
from collections.abc import Callable
from dataclasses import dataclass, replace
from pathlib import Path
from types import ModuleType
from typing import Any

ROOT = Path(__file__).resolve().parents[3]
SPEC_REL = "docs/design/E38/E38-D06.md"
DECK_REL = "docs/design/E38/E38-D06-copy.json"
TOOL_REL = "docs/design/_tools/e38_d06_handoff_audit.py"
PINS_REL = "docs/design/_tools/e38_d06_ruled_pins.txt"
OWN_PATHS = (SPEC_REL, DECK_REL, TOOL_REL, PINS_REL)
DECK_PATHS = (DECK_REL, TOOL_REL)
FULL, DECK_ONLY = "full", "deck-only"
BASE = "b005ce6105c2675c90aed6550d6220def0d9f227"  # origin/main
D01_REF = "4774b2f8cd7b67a1ee934fe88546568f7aa3e34c"  # #5451's head (the memo)
D02_REF = "17e0086b76bc048b47193a85c2650fd157adb6cd"  # #5494's head (E38-D02)
D03_REF = "133a45628ebca6b5955aa89d0208b92efb64d52a"  # #5493's head (E38-D03)
D04_REF = "2c47253340e130e6b88d25ed209fd1666e01418d"  # #5490's head (E38-D04)
D05_REF = "89d2d790ea73dcc87dc216c5d344d2b9296ffc68"  # E38-D05's head (#1076)
TOKENS = ROOT / "packages" / "ui" / "tokens"
PATHS: dict[str, str] = {
    "00": "docs/plan/00-planning-brief.md",
    "02": "docs/plan/02-definition-of-ready-done.md",
    "14": "docs/plan/14-screens-catalogue.md",
    "15": "docs/plan/15-component-catalogue.md",
    "16": "docs/plan/16-design-system-brief.md",
    "22": "docs/plan/22-api-openapi.yaml",
    "24": "docs/plan/24-internal-schemas.md",
    "CAL": "docs/plan/backlog/_tools/calendar_cv.py",
    "D01": "docs/design/research/E38-paper-parity.md",
    "D02": "docs/design/E38/E38-D02.md",
    "D03": "docs/design/E38/E38-D03.md",
    "D04": "docs/design/E38/E38-D04.md",
    "D05": "docs/design/E38/E38-D05.md",
    "DS": ".claude/rules/32-design-specs.md",
    "E09D09": "docs/design/E09/E09-D09.md",
    "E10D03": "docs/design/E10/E10-D03.md",
    "E10D04": "docs/design/E10/E10-D04.md",
}
REF_OF = {
    "D01": D01_REF,
    "D02": D02_REF,
    "D03": D03_REF,
    "D04": D04_REF,
    "D05": D05_REF,
}
# a string is `final` only when its source is merged at the base
MERGED = ("14", "15", "E09D09", "E10D03")
STATUSES = ("final", "PROPOSED")
# the two notices the ticket names, verbatim, with their sources
REQUIRED = {
    "env.popover.demo_statement": (
        (
            "Demo uses Bybit's demo matching engine — REST order entry only, no"
            " private WS order entry."
        ),
        "14:1788",
    ),
    "sim.caveat": ("these results are not a backtest guarantee", "14:2277"),
}
# the ticket's component mapping
CMPS = ("074", "075", "139", "044", "049", "099", "116", "167", "168", "175", "178")
THEMES = ("dark", "light", "high-contrast")
TOKEN = re.compile(
    r"`((?:color|type|font|radius|space|size|border|motion|opacity|elevation)"
    r"\.[a-z0-9.-]+)`"
)
DASH = "–"  # the en dash of a cited range
KEYS = r"\d\d|D0[1-5]|DS|CAL|E09D09|E10D0[34]"
CITE = re.compile(rf"`({KEYS})`:(\d+(?:{DASH}\d+)?(?:, :\d+(?:{DASH}\d+)?)*)")
SOURCE = re.compile(rf"({KEYS}):(\d+)(?:{DASH}(\d+))?")
ANCHOR = re.compile(r"`?([^\s<|(`]+)`?<!--=([A-Z]+:[A-Za-z0-9.]+)-->")
CLOSING = re.compile(
    r"\b(?:close[sd]?|fix(?:e[sd])?|resolve[sd]?)\s+#\d+", re.IGNORECASE
)
LOCAL_PATH = re.compile(
    "/" + "home/|/Users/|[A-Za-z]:\\\\|\\bwt-" + "notes\\b"
)  # assembled
AGENT_NAME = re.compile(r"\b[a-z]{2,4}-worker-\d\b")
URL_OR_HOST = re.compile(r"https?://|penpot\.[a-z]|team-id=|file-id=", re.IGNORECASE)
# assembled with an explicit +, so the formatter keeps the split and the tool
# never spells a word
DENY = (
    "le" + "ak",
    "expo" + "sed",
    "by" + "pass",
    "ex" + "ploit",
    "att" + "ack",
    "ora" + "cle",
    "rev" + "eal",
    "unbou" + "nded",
    "flo" + "od",
    "st" + "all",
    "d" + "os",
    "advi" + "sory",
    "gh" + "sa",
    "pre-" + "auth",
)


@dataclass(frozen=True)
class Texts:
    spec: str
    deck: str
    pins: str
    tool: str
    changed: list[str] | None
    memo: dict[str, str | None]
    mode: str = FULL


def git(*args: str) -> str | None:
    try:
        # git with fixed arguments and no shell; the only external program it runs
        r = subprocess.run(
            ["git", "-C", str(ROOT), *args], capture_output=True, check=False
        )
    except OSError:
        return None
    return r.stdout.decode("utf-8", "surrogateescape") if r.returncode == 0 else None


def show(t: Texts, rev: str, rel: str) -> str | None:
    key = f"{rev}:{rel}"
    if key not in t.memo:
        t.memo[key] = git("show", key)
    return t.memo[key]


def at(t: Texts, key: str) -> str:
    ref = REF_OF.get(key, BASE)
    text = show(t, ref, PATHS[key])
    if text is None:
        raise LookupError(f"{PATHS[key]} does not resolve at {ref[:10]}")
    return text


def norm(s: str) -> str:
    return " ".join(s.split())


def lines_at(t: Texts, key: str, a: int, b: int) -> str:
    """The cited lines, joined, with a wireframe's box borders dropped."""
    ls = at(t, key).split("\n")
    if not 0 < a <= b <= len(ls):
        raise LookupError(f"{key}:{a} is past the end of {PATHS[key]}")
    return norm(" ".join(ls[a - 1 : b]).replace("|", " "))


def cells(line: str) -> list[str]:
    return [c.strip() for c in re.split(r"(?<!\\)\|", line.strip().strip("|"))]


def rows(text: str, lead: str) -> list[list[str]]:
    return [cells(ln) for ln in text.split("\n") if re.match(rf"\| {lead} ", ln)]


def section(text: str, head: str) -> str:
    i = text.find("\n" + head)
    if i < 0:
        return ""
    depth = head.split(" ")[0]
    j = text.find("\n" + depth + " ", i + 1)
    k = text.find("\n## ", i + 1) if depth != "##" else -1
    ends = [x for x in (j, k) if x > 0]
    return text[i : min(ends) if ends else len(text)]


def mermaid(text: str) -> list[str]:
    m = re.search(r"```mermaid\n(.*?)```", text, re.DOTALL)
    return [ln.strip() for ln in m[1].split("\n") if ln.strip()] if m else []


# ---------------------------------------------------------------------------- tokens


_MODS: dict[str, ModuleType] = {}


def verify_tokens() -> ModuleType:
    if "v" not in _MODS:
        path = TOKENS / "tests" / "verify_tokens.py"
        spec = importlib.util.spec_from_file_location("verify_tokens", path)
        if spec is None or spec.loader is None:
            raise LookupError(f"cannot load {path}")
        mod = importlib.util.module_from_spec(spec)
        sys.modules["verify_tokens"] = mod
        spec.loader.exec_module(mod)
        _MODS["v"] = mod
    return _MODS["v"]


_SETS: dict[str, set[str]] = {}


def token_names(theme: str) -> set[str]:
    if theme not in _SETS:
        v = verify_tokens()
        allt: dict[str, Any] = dict(v.load(v.PRIMITIVES))
        allt.update(v.merged_set(v.THEMES[theme]))
        _SETS[theme] = {k for k, tok in allt.items() if isinstance(tok, dict)}
    return _SETS[theme]


# ---------------------------------------------------------------------------- deck


def deck_of(t: Texts) -> dict[str, Any]:
    def no_dups(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
        seen: dict[str, Any] = {}
        for k, v in pairs:
            if k in seen:
                raise LookupError(f"the deck repeats the id {k!r}")
            seen[k] = v
        return seen

    try:
        doc = json.loads(t.deck, object_pairs_hook=no_dups)
    except json.JSONDecodeError as e:
        raise LookupError(f"the deck does not parse: {e}") from e
    strings = doc.get("strings") if isinstance(doc, dict) else None
    if not isinstance(strings, dict):
        raise TypeError("the deck has no `strings` object")
    return dict(doc)


def counts(t: Texts) -> dict[str, str]:
    strings = deck_of(t)["strings"]
    statuses = [s.get("status") for s in strings.values() if isinstance(s, dict)]
    return {
        "COPY:total": str(len(strings)),
        "COPY:final": str(statuses.count("final")),
        "COPY:proposed": str(statuses.count("PROPOSED")),
    }


# ---------------------------------------------------------------------------- values


def compute(t: Texts) -> dict[str, str]:
    v = {
        "SHA:BASE": BASE[:10],
        "SHA:D01": D01_REF[:10],
        "SHA:D02": D02_REF[:10],
        "SHA:D03": D03_REF[:10],
        "SHA:D04": D04_REF[:10],
        "SHA:D05": D05_REF[:10],
    }
    try:
        v.update(counts(t))
    except (LookupError, TypeError):
        pass  # G-COPY reports it
    return v


def anchor_problems(t: Texts, vals: dict[str, str], prefix: str) -> list[str]:
    return [
        f"`{key}` reads {value}; the tool derives {vals.get(key, '?')}"
        for value, key in ANCHOR.findall(t.spec)
        if key.startswith(prefix) and vals.get(key) != value
    ]


# ---------------------------------------------------------------------------- cites


def cites(text: str) -> list[tuple[str, int, int]]:
    out = []
    for m in CITE.finditer(text):
        for part in m[2].split(", :"):
            a, _, b = part.partition(DASH)
            out.append((m[1], int(a), int(b or a)))
    return out


def cite_hashes(t: Texts) -> tuple[dict[str, str], list[str]]:
    hashes: dict[str, str] = {}
    bad: list[str] = []
    for key, a, b in cites(t.spec):
        label = f"{key}:{a}" if a == b else f"{key}:{a}{DASH}{b}"
        if label in hashes:
            continue
        ls = at(t, key).split("\n")
        if not 0 < a <= b <= len(ls):
            bad.append(f"{label} is past the end of {PATHS[key]} ({len(ls)} lines)")
            continue
        blank = [n for n in (a, b) if not ls[n - 1].strip()]
        if blank:
            bad.append(f"{label}: line {blank[0]} is blank at its ref")
            continue
        hashes[label] = hashlib.sha256(
            (norm(ls[a - 1]) + "\n" + norm(ls[b - 1])).encode()
        ).hexdigest()[:12]
    return hashes, bad


def parse_pins(text: str) -> dict[str, str]:
    out = {}
    for ln in text.split("\n"):
        parts = ln.split("\t")
        if len(parts) == 2 and not ln.startswith("#"):
            out[parts[0]] = parts[1]
    return out


# ---------------------------------------------------------------------------- gates


def g_states(t: Texts, vals: dict[str, str]) -> list[str]:
    bad = []
    d02, d03, d04 = at(t, "D02"), at(t, "D03"), at(t, "D04")
    s3, s2 = section(t.spec, "## 3."), section(t.spec, "## 2.")
    ids = [r[0] for r in rows(section(d02, "### 4.3"), r"S74-\d+")]
    ids += [r[0] for r in rows(d03, r"S(?:79|122|137|77)-\d+")]
    if len(ids) < 30:
        bad.append(f"only {len(ids)} parent state ids read: the parents moved")
    have = {r[0] for r in rows(s3, r"S\d+-\d+")}
    bad += [f"state {i} has no §3 row" for i in ids if i not in have]
    frames = []
    for parent in (d02, d03):
        for r in rows(section(parent, "## 0."), r"B\d\d"):
            frames += re.findall(r"`((?:SCR-\d+|sign-in|workspace)/[a-z0-9-]+)`", r[1])
    if len(frames) < 30:
        bad.append(f"only {len(frames)} parent frames read: the parents moved")
    bad += [f"frame `{f}` is not in §2" for f in frames if f"`{f}`" not in s2]
    s34 = section(t.spec, "### 3.4")
    named = re.findall(r"^- ([a-z][^(;.]*)", section(d04, "### 2.3"), re.MULTILINE)
    block = section(d04, "### 5.2").split("**Tokens:**")[0]
    named += re.findall(r"^\s+- ([a-z][^(;.]*)", block, re.MULTILINE)
    if len(named) < 10:
        bad.append(f"only {len(named)} D04 states read: D04 moved")
    bad += [f"D04 state {n.strip()!r} is not in §3.4" for n in named if n not in s34]
    want = mermaid(section(d02, "## 5."))
    if not want or mermaid(section(t.spec, "## 4.")) != want:
        bad.append("§4's diagram is not D02 §5's, line for line")
    return bad


def g_copy(t: Texts, vals: dict[str, str]) -> list[str]:
    bad = []
    doc = deck_of(t)
    strings: dict[str, Any] = doc["strings"]
    for sid, s in strings.items():
        if not isinstance(s, dict):
            bad.append(f"{sid}: not an object")
            continue
        text, owner, status = s.get("string"), s.get("owner"), s.get("status")
        m = SOURCE.fullmatch(str(s.get("source", "")))
        if not isinstance(text, str) or not text:
            bad.append(f"{sid}: no string")
            continue
        if status not in STATUSES:
            bad.append(f"{sid}: status {status!r} is not one of {STATUSES}")
        if not isinstance(owner, str) or not owner.strip():
            bad.append(f"{sid}: no owner")
        if not m:
            bad.append(f"{sid}: source {s.get('source')!r} is not KEY:line")
            continue
        a = int(m[2])
        if norm(text) not in lines_at(t, m[1], a, int(m[3] or a)):
            bad.append(f"{sid}: not verbatim at {m[0]}")
        if status == "final" and m[1] not in MERGED:
            bad.append(f"{sid}: final from {m[1]}, which is not merged")
    for sid, (text, src) in REQUIRED.items():
        s = strings.get(sid)
        if not isinstance(s, dict) or s.get("string") != text or s.get("source") != src:
            bad.append(f"the required notice {sid} is missing or changed")
        if t.mode == FULL and f'"{text}"' not in t.spec:
            bad.append(f"the pack does not quote the required notice {sid}")
    if t.mode == DECK_ONLY:
        return bad  # the pack, its §8 and its anchors land with the pack
    table = {}
    for ln in section(t.spec, "## 8.").split("\n"):
        if re.match(r"\| `[a-z0-9_.]+` ", ln):
            c = cells(ln)
            table[c[0].strip("`")] = c
    for sid in sorted(set(strings) ^ set(table)):
        bad.append(f"{sid} is in {'the deck' if sid in strings else '§8'} only")
    for sid, c in table.items():
        s = strings.get(sid)
        if not isinstance(s, dict) or len(c) != 5:
            continue
        got = c[1][1:-1].replace("\\|", "|") if c[1].startswith('"') else c[1]
        src = str(s.get("source", "")).replace(":", "`:", 1)
        if (
            got != s.get("string")
            or not c[2].startswith(str(s.get("status")))
            or c[3] != s.get("owner")
            or c[4] != f"`{src}"
        ):
            bad.append(f"{sid}: §8's row differs from the deck")
    return bad + anchor_problems(t, vals, "COPY:")


def g_component(t: Texts, vals: dict[str, str]) -> list[str]:
    bad = []
    table = {r[0]: r for r in rows(section(t.spec, "## 9."), r"CMP-\d+")}
    heads = re.findall(r"^### (CMP-\d+) (.*)$", at(t, "15"), re.MULTILINE)
    head = dict(heads)
    for n in CMPS:
        cid = f"CMP-{n}"
        r = table.get(cid)
        if r is None or len(r) < 4:
            bad.append(f"{cid} has no §9 row")
            continue
        if "SCR-" not in r[2]:
            bad.append(f"{cid}: its row names no screen")
        if cid not in head or not head[cid].startswith(r[1]):
            bad.append(f"{cid}: `15` has no heading {cid} {r[1]} at the base")
    return bad


def g_token(t: Texts, vals: dict[str, str]) -> list[str]:
    names = sorted(set(TOKEN.findall(t.spec)))
    if not names:
        return ["the pack names no token"]
    return [
        f"`{n}` does not resolve in {th}"
        for n in names
        for th in THEMES
        if n not in token_names(th)
    ]


def g_event(t: Texts, vals: dict[str, str]) -> list[str]:
    bad = []
    es = rows(section(t.spec, "## 12."), r"E-\d+")
    if len(es) < 10:
        bad.append(f"§12 has {len(es)} event rows")
    for r in es:
        if len(r) < 6:
            bad.append(f"{r[0]}: short row")
            continue
        names = re.findall(r"`([a-z_]+\.[a-z_]+)`", r[2])
        hay = " ".join(lines_at(t, k, a, b) for k, a, b in cites(r[5]))
        if names and not hay:
            bad.append(f"{r[0]}: an event with no cited source")
        bad += [
            f"{r[0]}: `{n}` is not on its cited line" for n in names if n not in hay
        ]
    return bad


def g_question(t: Texts, vals: dict[str, str]) -> list[str]:
    bad = []
    qs = rows(section(t.spec, "## 13."), r"Q-\d+")
    if len(qs) < 10:
        bad.append(f"§13 has {len(qs)} rows")
    for i, r in enumerate(qs, 1):
        if r[0] != f"Q-{i:02d}":
            bad.append(f"{r[0]} is out of order (expected Q-{i:02d})")
        if len(r) < 4 or r[2].strip() in ("", "—", "-", "TBD"):
            bad.append(f"{r[0]}: no owner")
            continue
        m = re.match(r"(resolution|follow-up): (\S.*)", r[3])
        if not m:
            bad.append(f"{r[0]}: neither a resolution nor a follow-up")
    return bad


def g_arow(t: Texts, vals: dict[str, str]) -> list[str]:
    bad = []
    seen = 0
    for ln in section(t.spec, "### 17.1").split("\n"):
        m = re.match(r"- \*\*(A-\d+) → `(\d\d)` [^*]+\*\* \(`(\d\d)`:(\d+)\)\.", ln)
        if not ln.startswith("- **A-"):
            continue
        seen += 1
        if not m or m[2] != m[3]:
            bad.append(f"{ln[:20]}: no target with its line cite")
            continue
        body = ln[m.end() :]
        anchors = re.findall(r'Old: "(.+?)"\. New:', body)
        anchors += re.findall(r'[Aa]fter "(.+?)" add', body)
        if not anchors:
            bad.append(f"{m[1]}: names neither an Old text nor an anchor")
        text = at(t, m[2])
        line = text.split("\n")[int(m[4]) - 1] if int(m[4]) else ""
        for a in anchors:
            n = text.count(a)
            if n != 1:
                bad.append(f"{m[1]}: {a[:40]!r} stands {n} times in `{m[2]}`")
            elif a not in line:
                bad.append(f"{m[1]}: {a[:40]!r} is not on `{m[2]}`:{m[4]}")
    if seen < 1:
        bad.append("§17.1 carries no A-row")
    return bad


def g_cite(t: Texts, vals: dict[str, str]) -> list[str]:
    hashes, bad = cite_hashes(t)
    pinned = parse_pins(t.pins)
    for label, h in hashes.items():
        if label not in pinned:
            bad.append(f"cite {label} is unpinned: verify it by content, then repin")
        elif pinned[label] != h:
            bad.append(f"cite {label}: the line at its ref is not the pinned content")
    return bad + anchor_problems(t, vals, "SHA:")


def g_hygiene(t: Texts, vals: dict[str, str]) -> list[str]:
    bad = []
    checks = (
        (CLOSING, "a closing keyword (the closing line waits for the parents)"),
        (LOCAL_PATH, "a local path"),
        (AGENT_NAME, "an agent name"),
        (URL_OR_HOST, "a URL or a host"),
    )
    for name, text in (("spec", t.spec), ("deck", t.deck)):
        for i, ln in enumerate(text.split("\n"), 1):
            for rx, what in checks:
                if rx.search(ln):
                    bad.append(f"{name}:{i} carries {what}")
            if "{{" in ln:
                bad.append(f"{name}:{i} carries a double-brace slot")
    texts = (("spec", t.spec), ("deck", t.deck), ("tool", t.tool), ("pins", t.pins))
    for name, text in texts:
        for i, ln in enumerate(text.split("\n"), 1):
            if any(d in ln.lower() for d in DENY):
                bad.append(f"{name}:{i} carries a public-text deny word")
    for _, key in ANCHOR.findall(t.spec):
        if key not in vals:
            bad.append(f"an anchor `{key}` the tool does not compute")
    return bad


def owned(mode: str) -> tuple[str, ...]:
    return DECK_PATHS if mode == DECK_ONLY else OWN_PATHS


def g_scope(t: Texts, vals: dict[str, str]) -> list[str]:
    if t.changed is None:
        return ["cannot list the changed paths (git failed)"]
    own = owned(t.mode)
    return [
        f"{p} is touched; this {t.mode} change owns {', '.join(own)}"
        for p in t.changed
        if p not in own
    ]


GATES: dict[str, Callable[[Texts, dict[str, str]], list[str]]] = {
    "G-STATES": g_states,
    "G-COPY": g_copy,
    "G-COMPONENT": g_component,
    "G-TOKEN": g_token,
    "G-EVENT": g_event,
    "G-QUESTION": g_question,
    "G-AROW": g_arow,
    "G-CITE": g_cite,
    "G-HYGIENE": g_hygiene,
    "G-SCOPE": g_scope,
}
DECK_GATES = ("G-COPY", "G-HYGIENE", "G-SCOPE")


def gates_of(mode: str) -> list[str]:
    return [g for g in GATES if mode == FULL or g in DECK_GATES]


def audit(t: Texts) -> list[tuple[str, str]]:
    vals = compute(t)
    out = []
    for g in gates_of(t.mode):
        fn = GATES[g]
        try:
            out += [(g, msg) for msg in fn(t, vals)]
        except (LookupError, TypeError, ValueError, IndexError) as e:
            # default-deny: an unreadable input fails its gate
            out.append((g, f"cannot evaluate: {e}"))
    return out


# ---------------------------------------------------------------------------- load


def changed_paths() -> list[str] | None:
    mb = git("merge-base", "HEAD", "origin/main")
    if not mb:
        return None
    a = git("diff", "--name-only", mb.strip())
    b = git("status", "--porcelain", "--untracked-files=all")
    if a is None or b is None:
        return None
    out = {p for p in a.split("\n") if p}
    out |= {ln[3:].split(" -> ")[-1].strip('"') for ln in b.split("\n") if len(ln) > 3}
    return sorted(out)


def read(rel: str) -> str:
    path = ROOT / rel
    return path.read_text(encoding="utf-8") if path.exists() else ""


def mode_now() -> str:
    """Deck-only when neither the pack nor the pins file is in the working tree."""
    present = [(ROOT / rel).exists() for rel in (SPEC_REL, PINS_REL)]
    return FULL if any(present) else DECK_ONLY


def load() -> Texts:
    return Texts(
        read(SPEC_REL),
        read(DECK_REL),
        read(PINS_REL),
        read(TOOL_REL),
        changed_paths(),
        {},
        mode_now(),
    )


# ---------------------------------------------------------------------------- self-test


def sub(old: str, new: str) -> Callable[[Texts], Texts]:
    def f(t: Texts) -> Texts:
        if t.spec.count(old) != 1:
            raise SystemExit(
                f"self-test: the pack carries {old[:50]!r} {t.spec.count(old)} times"
            )
        return replace(t, spec=t.spec.replace(old, new))

    return f


def set_cell(row: str, col: int, value: str) -> Callable[[Texts], Texts]:
    def f(t: Texts) -> Texts:
        ls = t.spec.split("\n")
        i = next(k for k, ln in enumerate(ls) if ln.startswith(f"| {row} "))
        c = cells(ls[i])
        c[col] = value
        ls[i] = "| " + " | ".join(c) + " |"
        return replace(t, spec="\n".join(ls))

    return f


def drop_row(row: str) -> Callable[[Texts], Texts]:
    def f(t: Texts) -> Texts:
        kept = [x for x in t.spec.split("\n") if not x.startswith(f"| {row} ")]
        return replace(t, spec="\n".join(kept))

    return f


def deck_edit(fn: Callable[[dict[str, Any]], None]) -> Callable[[Texts], Texts]:
    def f(t: Texts) -> Texts:
        doc = json.loads(t.deck)
        fn(doc)
        return replace(t, deck=json.dumps(doc, ensure_ascii=False, indent=2))

    return f


def _set(sid: str, field: str, value: str) -> Callable[[dict[str, Any]], None]:
    def f(doc: dict[str, Any]) -> None:
        doc["strings"][sid][field] = value

    return f


def _rename(old: str, new: str) -> Callable[[dict[str, Any]], None]:
    def f(doc: dict[str, Any]) -> None:
        doc["strings"] = {
            (new if k == old else k): v for k, v in doc["strings"].items()
        }

    return f


def _note(doc: dict[str, Any]) -> None:
    doc["note"] = "fl" + "ood"


MUTATIONS: tuple[tuple[str, str, Callable[[Texts], Texts]], ...] = (
    ("G-STATES", "a state row dropped", drop_row("S79-04")),
    (
        "G-STATES",
        "a frame renamed in §2",
        sub(
            "`SCR-137/fidelity-unavailable` (`D03`:60–63)",
            "`SCR-137/fidelity-missing` (`D03`:60–63)",
        ),
    ),
    (
        "G-COPY",
        "a deck string reworded",
        deck_edit(_set("rbac.env", "string", "Live trading is not enabled for you.")),
    ),
    (
        "G-COPY",
        "a PROPOSED string's owner emptied",
        deck_edit(_set("env.switched.banner_live", "owner", "")),
    ),
    (
        "G-COPY",
        "a PROPOSED string marked final",
        deck_edit(_set("env.confirm_live.mismatch", "status", "final")),
    ),
    (
        "G-COPY",
        "the demo notice's id renamed",
        deck_edit(_rename("env.popover.demo_statement", "env.popover.demo")),
    ),
    ("G-COMPONENT", "a component row dropped", drop_row("CMP-168")),
    (
        "G-TOKEN",
        "a token misspelled",
        sub(
            "`font.weight.semibold`, `size.icon.sm`",
            "`font.weight.semi`, `size.icon.sm`",
        ),
    ),
    ("G-EVENT", "an event renamed", set_cell("E-10", 2, "`users.access_changed`")),
    ("G-QUESTION", "a question's owner emptied", set_cell("Q-05", 2, "")),
    (
        "G-AROW",
        "A-01's Old text off by one character",
        sub(
            'Old: "not permitted ("The owner hasn\'t enabled Live for your account.")"',
            'Old: "not permitted ("The owner hasn\'t enabled Live for your account!")"',
        ),
    ),
    ("G-CITE", "a `D03` cite one line off", sub("`D03`:118", "`D03`:119")),
    (
        "G-HYGIENE",
        "a closing keyword against #1077",
        sub("nothing here claims it.", "nothing here claims it. Closes #1077."),
    ),
    ("G-HYGIENE", "a deny word in the deck", deck_edit(_note)),
    (
        "G-SCOPE",
        "a parent file in the diff",
        lambda t: replace(t, changed=[*(t.changed or []), PATHS["D02"]]),
    ),
    (
        "G-STATES",
        "a diagram line changed",
        sub("failed --> idle: Close", "failed --> idle: Retry"),
    ),
    (
        "G-COPY",
        "a count typed by hand",
        sub("Of 147<!--=COPY:total-->", "Of 148<!--=COPY:total-->"),
    ),
)
# the mutations that touch only the deck or the diff: deck-only mode runs these
DECK_MUTATIONS = (3, 4, 5, 6, 14, 15)


def selftest() -> tuple[bool, list[str]]:
    loaded = load()
    base = replace(loaded, changed=list(owned(loaded.mode)))
    before = (base.spec, base.deck)
    found = audit(base)
    out = [f"self-test: mode {base.mode}, baseline {len(found)} FAIL"]
    out += [f"  baseline {g}: {m}" for g, m in found]
    ok = not found
    run = 0
    for i, (gate, what, fn) in enumerate(MUTATIONS, 1):
        if base.mode == DECK_ONLY and i not in DECK_MUTATIONS:
            continue
        run += 1
        gates = sorted({g for g, _ in audit(fn(base))})
        good = gates == [gate]
        ok &= good
        shown = ", ".join(gates) or "none"
        out.append(f"{'ok  ' if good else 'FAIL'} M-{i} {gate}: {what} -> {shown}")
    hit = {m[0] for i, m in enumerate(MUTATIONS, 1) if i in DECK_MUTATIONS}
    if base.mode == FULL:
        hit = {m[0] for m in MUTATIONS}
    missing = [g for g in gates_of(base.mode) if g not in hit]
    ok &= not missing
    if missing:
        out.append(f"FAIL no mutation for {', '.join(missing)}")
    now = load()
    restored = (now.spec, now.deck) == before
    ok &= restored
    out.append(
        f"self-test: {run} mutations, text restored: " + ("yes" if restored else "NO")
    )
    out.append(f"self-test: {'PASS' if ok else 'FAIL'}")
    return ok, out


def main(argv: list[str]) -> int:
    ap = argparse.ArgumentParser(description="E38-D06 hand-off pack audit")
    g = ap.add_mutually_exclusive_group()
    g.add_argument("--check", action="store_true")
    g.add_argument("--json", action="store_true")
    g.add_argument("--self-test", action="store_true")
    g.add_argument("--repin-ruled", action="store_true")
    a = ap.parse_args(argv)
    if a.self_test:
        ok, lines = selftest()
        print("\n".join(lines))
        return 0 if ok else 1
    t = load()
    if a.repin_ruled and t.mode == DECK_ONLY:
        print("refused: deck-only mode has no pack to pin")
        return 1
    if a.repin_ruled:
        hashes, bad = cite_hashes(t)
        if bad:
            print(f"refused: {bad[0]}")
            return 1
        head = (
            "# E38-D06 cite pins: the cite, a hash of its cited line(s) at its ref."
            " Written by --repin-ruled only.\n"
        )
        (ROOT / PINS_REL).write_text(
            head + "".join(f"{k}\t{h}\n" for k, h in hashes.items()), encoding="utf-8"
        )
        print(f"wrote {PINS_REL} ({len(hashes)} cites)")
        return 0
    found = audit(t)
    if a.json:
        print(json.dumps([{"gate": g_, "fail": m} for g_, m in found], indent=2))
        return 1 if found else 0
    for gate, msg in found:
        print(f"FAIL {gate}: {msg}")
    print(f"{len(found)} FAIL ({len(gates_of(t.mode))} gates, {t.mode} mode)")
    return 1 if found else 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
