#!/usr/bin/env python3
"""E41-D04 (#1082) audit: the journal accessibility review, motion spec and hand-off pack.

Standalone, offline, stdlib only; run it with `python3 -I`. It reads the pack, the copy deck and
the pins file from the working tree, and every cited file as text with `git show`: the plan docs,
E05-D03, E09-D09, E29-D04's hand-off, E42-D04, E47-D04, E41-D01's memo, the design-spec rules and
the keymap registry at the base (`BASE`); E41-D02 and E41-D03 at their heads (`D02_REF`,
`D03_REF`), each "if it merges as is", cited by section id only; #5567's memo at its merge
commit (`P01_REF`) for the request rows. It imports `verify_tokens`, `contrast_check` and
`cvd_simulate` from the working tree and never re-implements them. Default-deny: a gate that
cannot read its input FAILs.

`--stage` is required. The deck stage reads the copy deck and this tool and runs G-DECK,
G-HYGIENE and G-SCOPE; the full stage runs every gate, and a missing pack, hand-off or pins file
FAILs G-SCOPE. Statuses (shared with E37 and E38): `merged` (verbatim on a merged line at the
base, a `{slot}` matching any text), `RULED` (an unmerged parent's text its BQ ruling settled,
named in `ruling`), `PROPOSED` (owner approval pending); `frozen` names a head group.

Gates (each FAIL led by its name):
  G-DECK      the deck parses; the head pins the parents and lists the statuses and the frozen
              groups, each group's `ids` exactly its entries; ids unique, fields present;
              `merged` only on a merged line holding the text, `RULED` with a ruling, a parent
              string verbatim in its parent at its pin; no double or edge space; the five
              announcement classes present; no `_withheld` id but the Usage line (BQ-06); a
              string about accounts outside the grant is frozen in FZ-03 (`T` Security).
  G-COPY      every deck id the pack names is in the deck; §10.6's counts and FZ rows equal it.
  G-ANNOUNCE  AN-01 … AN-17 in order, each naming a deck id; the five classes spoken; nothing
              assertive.
  G-STATES    §10.5 lists exactly the state ids of D02's and D03's state tables at their pins.
  G-MAP       each of the ticket's seventeen components has an MP row named as its `15` heading.
  G-TOKEN     every token the pack names resolves; no raw colour value.
  G-CONTRAST  every P row recomputed per theme; `text` ≥ 4.5, `ui` ≥ 3; `rejected` under 4.5.
  G-ZOOM      every Z row's sizes and weight recomputed; the floor 4.5 at both sizes.
  G-CVD       every V row's ΔE76 figures and JND column recomputed.
  G-MOTION    every M row's Duration and Easing a motion token, "a cut" or a cited `linear`; a
              reduce cell (the end state, no motion) and a carrier; the ticket's four moments;
              the filter-change moment a cut.
  G-KEYS      the six ticket actions have K rows; no CM default is a key `05` §3.2 binds
              globally, §3.3 reserves, the registry lists as a browser or OS key, or a
              `defaultBinding` of the registry, all at the base.
  G-FINDING   F rows in order; the count anchors equal the rows; a Major closes by an A-row or
              is routed on a named gap; every A-row named exists; F-09 never below Major.
  G-AROW      A-1 … A-16 in order; a retired row quotes nothing; each Old or After text stands
              once in its target at its pin (a `14` or `11` one on its cited line); no A-row
              targets a `14` / `15` line a parent's A-row or AR-row owns.
  G-REQUEST   no line cite into D02 or D03; the SHA anchors are the pins; `P01` only on R rows;
              R-1 and R-2 qualify their parents "merges as is"; R-3 names #5567 merged.
  G-CITE      every cite in range, on a non-blank line, equal to the pins file.
  G-RULED     the 3 Nov rulings: RV-11 gates rename, merge and delete `rbac.owner_only`
              (BQ-06); A-1 retired and C-5 not routed (BQ-03); K96-04 moves focus by
              `E47D04`:285; §5.5 names `Alt+R`'s shadow (`05`:85, `14`:975; BQ-04).
  G-HANDOFF   one block per contract E41 changes (CMP-166 … CMP-169), headed by its `15` name,
              its lines `16` §11.4's in order; ticked with evidence, or `N/A` / `PENDING — why`.
  G-HYGIENE   no closing keyword, local path, URL, host, agent name, double-brace slot or deny
              word in the stage's files; no URL, host or key-like value in a deck field; no
              reserved word in an own file name.
  G-SCOPE     the stage's files are present, and the diff touches only this ticket's files.

Usage (from the repo root):
  python3 -I docs/design/_tools/e41_d04_handoff_audit.py --stage deck|full --check|--self-test
  python3 -I docs/design/_tools/e41_d04_handoff_audit.py --stage full --fill|--json|--repin-ruled
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
SPEC_REL = "docs/design/E41/E41-D04.md"
HAND_REL = "docs/design/E41/E41-D04-handoff.md"
DECK_REL = "docs/design/E41/E41-D04-copy-deck.jsonl"
TOOL_REL = "docs/design/_tools/e41_d04_handoff_audit.py"
PINS_REL = "docs/design/_tools/e41_d04_ruled_pins.txt"
OWN_PATHS = (SPEC_REL, HAND_REL, DECK_REL, TOOL_REL, PINS_REL)
DECK_PATHS = (DECK_REL, TOOL_REL)
DECK, FULL = "deck", "full"
BASE = "a7d659a5bee5d06a28950f324800f84dc3853e6f"  # origin/main
D02_REF = "c759ad15b6677fee769a78fbf88e90cd57b19069"  # E41-D02's pushed PR 1b head (#1018)
D03_REF = "94ce9438aa36f29998a834b016b8b94eeb1693ea"  # E41-D03's pushed PR 1b head (#1081)
P01_REF = "e2c6bfff7117c23ce0a1f753bd591c9d7f9857a3"  # #5567's merge commit (merged as is)
TOKENS = ROOT / "packages" / "ui" / "tokens"
CVD_PATH = ROOT / "docs" / "research" / "_tools" / "cvd_simulate.py"
CONTRAST_PATH = ROOT / "docs" / "design" / "_tools" / "contrast_check.py"
KEYMAP = "apps/web/src/keymap/keymap.json"
RESERVED_KEYS = "apps/web/src/keymap/reserved-keys.json"
PATHS: dict[str, str] = {
    "05": "docs/plan/05-accessibility-standard.md",
    "11": "docs/plan/11-user-stories.md",
    "14": "docs/plan/14-screens-catalogue.md",
    "15": "docs/plan/15-component-catalogue.md",
    "16": "docs/plan/16-design-system-brief.md",
    "D01": "docs/design/research/e41-journal-review.md",
    "E05D03": "docs/design/E05/E05-D03.md",
    "E09D09": "docs/design/E09/E09-D09.md",
    "E29D04H": "docs/design/E29/E29-D04-handoff.md",
    "E42D04": "docs/design/E42/E42-D04.md",
    "E47D04": "docs/design/E47/E47-D04.md",
    "DS": ".claude/rules/32-design-specs.md",
    "P01": "docs/design/research/e41-journal-review.md",
    "D02": "docs/design/E41/E41-D02.md",
    "D03": "docs/design/E41/E41-D03.md",
}
REF_OF = {"P01": P01_REF, "D02": D02_REF, "D03": D03_REF}
MERGED = ("05", "11", "14", "15", "16", "D01", "E05D03", "E09D09", "E29D04H", "E42D04", "E47D04")
STATUSES = ["merged", "RULED", "PROPOSED"]
CITE = re.compile(
    r"`(\d\d|D01|E05D03|E09D09|E29D04H|E42D04|E47D04|DS|P01|D02|D03)`:(\d+(?:–\d+)?(?:, :\d+(?:–\d+)?)*)"
)
DECK_ID = re.compile(r"`(journal\.[a-z0-9_.]*[a-z0-9_])`")
TOKEN_NAME = re.compile(
    r"`((?:color|font|border|radius|type|space|size|motion|opacity)\.[a-z0-9.-]*[a-z0-9])`"
)
RAW_COLOUR = re.compile(r"#(?:[0-9A-Fa-f]{6}|[0-9A-Fa-f]{3})(?![0-9A-Za-z])")
CLOSING = re.compile(r"\b(?:close[sd]?|fix(?:e[sd])?|resolve[sd]?)\s+#\d+", re.IGNORECASE)
LOCAL_PATH = re.compile(
    "/" + "home/|/Users/|/" + "tmp/|[A-Za-z]:\\\\|\\bwt-" + "notes\\b|\\bnotes/"
)  # assembled, so this line carries none of the paths
AGENT_NAME = re.compile(r"\b[a-z]{2,4}-worker-\d\b")
URL_OR_HOST = re.compile(r"https?://|penpot\.[a-z]|team-id=|file-id=", re.IGNORECASE)
HOSTNAME = re.compile(r"\b[a-z0-9-]+\.(?:com|net|org|io|dev|app)\b", re.IGNORECASE)
KEYLIKE = re.compile(r"\b[A-Za-z0-9+/_-]{24,}\b")
DENY = (
    "le" + "ak", "expo" + "sed", "by" + "pass", "ex" + "ploit", "att" + "ack", "ora" + "cle",
    "rev" + "eal", "unbou" + "nded", "flo" + "od", "st" + "all", "d" + "os", "advi" + "sory",
    "gh" + "sa", "pre-" + "auth",
)  # fmt: skip
RESERVED_NAME = ("k" + "ey", "t" + "oken")  # own file names never carry these
THEMES = ("dark", "light", "high-contrast")
FLOOR = {"text": 4.5, "ui": 3.0}
DEFICIENCIES = ("protanopia", "deuteranopia", "tritanopia")
SEVERITIES = ("Blocking", "Major", "Minor", "Info")
FROZEN_IDS = ["FZ-01", "FZ-02", "FZ-03", "FZ-04", "FZ-05"]
FIELDS = ("id", "screen", "kind", "text", "status", "source", "owner", "rbac")
REQUIRED_SPEECH = {
    "sort": "journal.an.sort",
    "selection": "journal.bulk.count",
    "filter": "journal.an.list_count",
    "low sample": "journal.caveat.sample",
    "no context": "journal.context.none",
}
TICKET_CMPS = (
    "CMP-166", "CMP-167", "CMP-168", "CMP-169", "CMP-049", "CMP-055", "CMP-047", "CMP-116",
    "CMP-099", "CMP-026", "CMP-036", "CMP-046", "CMP-058", "CMP-043", "CMP-044", "CMP-024",
    "CMP-021",
)  # fmt: skip
TICKET_MOMENTS = ("selection", "drawer", "filter change", "Recomputing")
TICKET_ACTIONS = ("list navigation", "open detail", "bulk select", "apply tag", "export",
                  "replay jump")  # fmt: skip
GLOBAL_CATEGORIES = ("Global / Navigation", "Accessibility")  # `05` §3.2's never-shadowed rows
MIN_SEVERITY = {"F-09": "Major"}  # `T` Security: the out-of-grant counts are never graded down
N_AROWS = 16
N_AN = 17
USAGE_LINE = "journal.tags.usage_withheld"  # BQ-06: the one count-free line left
HANDOFF_CMPS = ("CMP-166", "CMP-167", "CMP-168", "CMP-169")
OTHER_ACCOUNTS = re.compile(
    r"\b(?:other|another|all|every|any)\b[^.;—]*\baccounts?\b"
    r"|\baccounts?\b[^.;—]*\b(?:outside|beyond|elsewhere)\b"
    r"|\b(?:outside|beyond|not in) (?:your|the) (?:access|grant|scope)\b",
    re.IGNORECASE,
)
REDUCE_FORM = re.compile(r"identical|removed: .+|a cut\b.*")
MOTION_WORD = re.compile(
    r"\b(?:slides?|sliding|fades?|fading|moves?|moving|sweeps?|tweens?|animat\w*|grows?|"
    r"shrinks?|scales?|rotat\w*|spins?|bounces?|pulses?)\b|\d+\s*ms\b|`motion\.",
    re.IGNORECASE,
)


@dataclass(frozen=True)
class Texts:
    stage: str
    spec: str | None
    hand: str | None
    deck: str | None
    pins: str | None
    tool: str
    changed: list[str] | None
    memo: dict[str, str | None]


def git(*args: str) -> str | None:
    try:
        r = subprocess.run(["git", "-C", str(ROOT), *args], capture_output=True, check=False)
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
        raise LookupError(f"{PATHS[key]} does not resolve at {ref[:10]}; fetch first")
    return text


def need(text: str | None, what: str) -> str:
    if text is None:
        raise LookupError(f"the {what} is missing")
    return text


def _load(path: Path, name: str) -> ModuleType:
    spec = importlib.util.spec_from_file_location(name, path)
    if spec is None or spec.loader is None:
        raise SystemExit(f"cannot load {path}")
    m = importlib.util.module_from_spec(spec)
    sys.modules[name] = m
    spec.loader.exec_module(m)
    return m


_MODS: dict[str, ModuleType] = {}
_MOD_PATHS = {"verify_tokens": TOKENS / "tests" / "verify_tokens.py",
              "contrast_check": CONTRAST_PATH, "cvd_simulate": CVD_PATH}  # fmt: skip


def mod(name: str) -> ModuleType:
    if name not in _MODS:
        sys.path.insert(0, str(TOKENS / "tests"))  # verify_tokens imports its siblings
        _MODS[name] = _load(_MOD_PATHS[name], name)
    return _MODS[name]


def norm(s: str) -> str:
    return " ".join(s.split())


def cells(ln: str) -> list[str]:
    return [c.strip() for c in ln.strip().strip("|").split("|")]


def table_rows(text: str, lead: str) -> list[list[str]]:
    return [cells(ln) for ln in text.split("\n") if ln.startswith("| " + lead)]


def section(text: str, head: str) -> str:
    i = text.find("\n" + head)
    if i < 0:
        return ""
    depth = head.split(" ")[0]
    j = text.find("\n" + depth + " ", i + 1)
    return text[i : j if j > 0 else len(text)]


def deck_lines(t: Texts) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    raw = [ln for ln in need(t.deck, "copy deck").split("\n") if ln.strip()]
    if not raw:
        raise LookupError("the copy deck is empty")
    try:
        objs = [json.loads(ln) for ln in raw]
    except json.JSONDecodeError as e:
        raise LookupError(f"the copy deck does not parse: {e}") from e
    return objs[0], objs[1:]


def slot_rx(text: str) -> re.Pattern[str]:
    parts = re.split(r"\{[^{}]+\}", text)
    return re.compile(".+?".join(re.escape(p) for p in parts))


def g_deck(t: Texts) -> list[str]:
    bad: list[str] = []
    head, entries = deck_lines(t)
    if head.get("deck") != "E41-D04":
        bad.append("the head line does not name the deck E41-D04")
    if head.get("refs") != {"D02": D02_REF, "D03": D03_REF}:
        bad.append("the head's refs are not the parents' pins")
    if head.get("statuses") != STATUSES:
        bad.append(f"the head's statuses are not {STATUSES}")
    groups = head.get("frozen", [])
    if [g.get("id") for g in groups] != FROZEN_IDS:
        bad.append(f"the frozen groups are not {FROZEN_IDS}")
    ids = [str(e.get("id")) for e in entries]
    dup = sorted({i for i in ids if ids.count(i) > 1})
    if dup:
        bad.append(f"duplicate ids: {dup[:3]}")
    for g in groups:
        members = [e["id"] for e in entries if e.get("frozen") == g.get("id")]
        if not g.get("what") or g.get("ids") != members:
            bad.append(f"{g.get('id')}: its `ids` are not the entries that carry it")
    texts = {k: at(t, k) for k in ("D02", "D03")}
    for e in entries:
        eid = e.get("id", "?")
        missing = [f for f in FIELDS if not e.get(f)]
        if missing:
            bad.append(f"{eid}: missing {missing}")
            continue
        if not re.fullmatch(r"journal\.[a-z0-9_.]*[a-z0-9_]", eid):
            bad.append(f"{eid}: not a journal key")
        text, status, source = e["text"], e["status"], e["source"]
        if status not in STATUSES:
            bad.append(f"{eid}: status {status!r} is outside the vocabulary")
        if text != text.strip() or "  " in text:
            bad.append(f"{eid}: a double or edge space")
        if e.get("frozen") and e["frozen"] not in FROZEN_IDS:
            bad.append(f"{eid}: unknown frozen group {e['frozen']}")
        if e.get("announce") not in (None, "polite"):
            bad.append(f"{eid}: announce {e.get('announce')!r} (only polite here)")
        if OTHER_ACCOUNTS.search(text) and e.get("frozen") != "FZ-03":
            bad.append(f"{eid}: speaks of accounts outside the grant, not frozen FZ-03 (`T`)")
        m = re.fullmatch(r"`(\w+)`:(\d+)", source)
        if status == "merged":
            if not m or m[1] not in MERGED:
                bad.append(f"{eid}: merged without a merged source line")
                continue
            ls = at(t, m[1]).split("\n")
            n = int(m[2])
            if not 0 < n <= len(ls) or not slot_rx(text).search(ls[n - 1]):
                bad.append(f"{eid}: not on `{m[1]}`:{n} at the base")
        elif status == "RULED":
            if not e.get("ruling"):
                bad.append(f"{eid}: RULED with no ruling")
        else:
            if m and m[1] in MERGED:
                bad.append(f"{eid}: a merged source line but PROPOSED")
            pk = source.split(" ")[0]
            if pk in texts and text not in texts[pk]:
                bad.append(f"{eid}: not verbatim in {pk} at its pin")
    for what, sid in REQUIRED_SPEECH.items():
        if sid not in ids:
            bad.append(f"the {what} announcement ({sid}) is missing")
    twins = [i for i in ids if i.endswith("_withheld") and i != USAGE_LINE]
    if twins:
        bad.append(f"{twins[0]}: a count-free twin of an owner-only surface (BQ-06)")
    return bad


def deck_counts(t: Texts) -> dict[str, int]:
    _, entries = deck_lines(t)
    out = {"total": len(entries), "frozen": sum(1 for e in entries if e.get("frozen"))}
    for s in STATUSES:
        out[s] = sum(1 for e in entries if e.get("status") == s)
    return out


_THEMES: dict[str, dict[str, Any]] = {}


def theme_all(name: str) -> dict[str, Any]:
    if name not in _THEMES:
        v = mod("verify_tokens")
        allt: dict[str, Any] = dict(v.load(v.PRIMITIVES))
        allt.update(v.merged_set(v.THEMES[name]))
        _THEMES[name] = allt
    return _THEMES[name]


def color(th: str, name: str) -> str:
    v = mod("verify_tokens")
    allt = theme_all(th)
    tokn = allt.get(name)
    if not isinstance(tokn, dict) or tokn.get("$type") != "color":
        raise LookupError(f"`{name}` is not a colour in {th}")
    return str(v.resolve(tokn["$value"], allt)).upper()[:7]


def known_tokens() -> set[str]:
    names: set[str] = set()
    for th in THEMES:
        names |= set(theme_all(th))
    return names


def hex_rgb(h: str) -> tuple[int, int, int]:
    h = h.lstrip("#")
    return int(h[0:2], 16), int(h[2:4], 16), int(h[4:6], 16)


def tok(cell: str) -> str:
    m = re.fullmatch(r"`([a-z0-9.-]+)`", cell)
    if not m:
        raise LookupError(f"{cell!r} is not one token")
    return m[1]


def ratios(fg: str, bg: str) -> list[str]:
    cc = mod("contrast_check")
    return [
        f"{cc.contrast_ratio(hex_rgb(color(th, fg)), hex_rgb(color(th, bg))):.2f}" for th in THEMES
    ]


def verdict(role: str, values: list[str]) -> str:
    if role == "rejected":
        return "rejected"
    floor = FLOOR.get(role)
    if floor is None:
        return "structure"
    return "pass" if min(map(float, values)) >= floor else "FAIL"


def cvd_values(row_: list[str]) -> tuple[str, str]:
    cv = mod("cvd_simulate")
    th = {"hc": "high-contrast"}.get(row_[3], row_[3])
    ha, hb = color(th, tok(row_[1])), color(th, tok(row_[2]))
    ds = [cv.delta_e76(ha, hb)] + [
        cv.delta_e76(cv.simulate(ha, d), cv.simulate(hb, d)) for d in DEFICIENCIES
    ]
    under = [n for n, d in zip(("normal", *DEFICIENCIES), ds, strict=True) if d < cv.JND_FLOOR]
    return " / ".join(f"{d:.2f}" for d in ds), (", ".join(under) if under else "none")


def type_values(cell: str) -> list[str]:
    v = mod("verify_tokens")
    allt = theme_all("dark")
    name = tok(cell)
    tokn = allt.get(name)
    entry: dict[str, Any] = tokn if isinstance(tokn, dict) else {}
    val = entry.get("$value", None) or {}
    typographic = isinstance(val, dict)
    if not typographic:
        raise LookupError(f"`{name}` is not a typography token")
    px = float(str(v.resolve(val["fontSize"], allt)))
    weight = int(str(v.resolve(val["fontWeight"], allt)))
    return [f"{px:g}", f"{px * 2:g}", str(weight), "4.5"]


def cites(text: str) -> list[tuple[str, int, int]]:
    out = []
    for m in CITE.finditer(text):
        for part in m[2].split(", :"):
            a, _, b = part.partition("–")
            out.append((m[1], int(a), int(b or a)))
    return out


def cite_hashes(t: Texts) -> tuple[dict[str, str], list[str]]:
    hashes: dict[str, str] = {}
    bad: list[str] = []
    for key, a, b in cites(need(t.spec, "pack") + "\n" + (t.hand or "")):
        if key in ("D02", "D03"):
            continue  # G-REQUEST refuses these; nothing to pin
        label = f"{key}:{a}" if a == b else f"{key}:{a}–{b}"
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
        joined = norm(ls[a - 1]) + "\n" + norm(ls[b - 1])
        hashes[label] = hashlib.sha256(joined.encode()).hexdigest()[:12]
    return hashes, bad


def parse_pins(text: str) -> dict[str, str]:
    out = {}
    for ln in text.split("\n"):
        parts = ln.split("\t")
        if len(parts) == 2 and not ln.startswith("#"):
            out[parts[0]] = parts[1]
    return out


def g_copy(t: Texts) -> list[str]:
    spec = need(t.spec, "pack")
    head, entries = deck_lines(t)
    ids = {e.get("id") for e in entries}
    bad = [
        f"the pack names {i}, which the deck lacks"
        for i in sorted(set(DECK_ID.findall(spec + "\n" + (t.hand or ""))) - ids)
    ]
    for k, n in deck_counts(t).items():
        for got in re.findall(rf"(\d+)<!--=COPY:{k}-->", spec):
            if int(got) != n:
                bad.append(f"the COPY:{k} anchor reads {got}, the deck {n}")
    if not re.search(r"<!--=COPY:total-->", spec):
        bad.append("§10.6 carries no COPY:total anchor")
    fz = {r[0]: r[1] for r in table_rows(section(spec, "### 10.6"), "FZ-") if len(r) > 1}
    for g in head.get("frozen", []):
        if fz.get(g.get("id")) != g.get("what"):
            bad.append(f"§10.6's {g.get('id')} row is not the deck's `what`")
    return bad


def g_announce(t: Texts) -> list[str]:
    spec = need(t.spec, "pack")
    rows = table_rows(section(spec, "## 4."), "AN-")
    bad = []
    got = [r[0] for r in rows]
    if got != [f"AN-{i:02d}" for i in range(1, N_AN + 1)]:
        bad.append(f"the AN rows are {got[:3]}…, not AN-01 … AN-{N_AN}")
    spoken: set[str] = set()
    for r in rows:
        ids = DECK_ID.findall(r[2]) if len(r) > 2 else []
        if not ids:
            bad.append(f"{r[0]} names no deck id")
        spoken |= set(ids)
        if "assertive" in " ".join(r).lower():
            bad.append(f"{r[0]} is assertive")
    for what, sid in REQUIRED_SPEECH.items():
        if sid not in spoken:
            bad.append(f"no AN row speaks the {what} class ({sid})")
    return bad


def state_ids(text: str, prefixes: tuple[str, ...]) -> set[str]:
    return {
        m for m in re.findall(r"^\| (S9[3-6]-\d\d) \|", text, re.MULTILINE) if m[:3] in prefixes
    }


def g_states(t: Texts) -> list[str]:
    spec = need(t.spec, "pack")
    want = state_ids(at(t, "D02"), ("S93", "S96")) | state_ids(at(t, "D03"), ("S94", "S95"))
    rows = table_rows(section(spec, "### 10.5"), "S9")
    got = {r[0] for r in rows}
    bad = [f"{s} of the parents is not in §10.5" for s in sorted(want - got)]
    bad += [f"§10.5 lists {s}, which no parent has" for s in sorted(got - want)]
    for r in rows:
        if len(r) < 2 or r[1] != "SCR-0" + r[0][1:3]:
            bad.append(f"{r[0]}: screen {r[1] if len(r) > 1 else '?'}")
    if not want:
        bad.append("no state ids read from the parents")
    return bad


def g_map(t: Texts) -> list[str]:
    spec = need(t.spec, "pack")
    rows = table_rows(section(spec, "### 10.4"), "MP-")
    p15 = at(t, "15")
    bad = []
    for cmp_ in TICKET_CMPS:
        hit = [r for r in rows if r[1].startswith(cmp_ + " ")]
        if not hit:
            bad.append(f"{cmp_} has no MP row")
            continue
        name = hit[0][1]
        heads = [ln for ln in p15.split("\n") if ln.startswith(f"### {cmp_} ")]
        if not heads or not heads[0][4:].startswith(name):
            bad.append(f"{cmp_}: `15` has no heading starting {name!r}")
    return bad


def g_token(t: Texts) -> list[str]:
    spec = need(t.spec, "pack")
    known = known_tokens()
    bad = [f"`{n}` is not a token" for n in sorted(set(TOKEN_NAME.findall(spec)) - known)]
    bad += [f"pack:{i} carries a raw colour" for i, ln in enumerate(spec.split("\n"), 1)
            if RAW_COLOUR.search(ln)]  # fmt: skip
    return bad


def g_contrast(t: Texts) -> list[str]:
    bad = []
    rows = table_rows(need(t.spec, "pack"), "P-")
    if not rows:
        bad.append("no P rows")
    for r in rows:
        if len(r) != 8:
            bad.append(f"{r[0]}: {len(r)} cells")
            continue
        v = ratios(tok(r[1]), tok(r[2]))
        if r[4:7] != v:
            bad.append(f"{r[0]}: {r[4:7]} where the tool computes {v}")
        want = verdict(r[3], v)
        if r[7] != want:
            bad.append(f"{r[0]}: verdict {r[7]} where the tool reads {want}")
        if want == "FAIL":
            bad.append(f"{r[0]}: under its {r[3]} floor")
        if r[3] == "rejected" and min(map(float, v)) >= FLOOR["text"]:
            bad.append(f"{r[0]}: rejected yet ≥ 4.5 in every theme")
        if r[3] not in ("text", "ui", "rejected"):
            bad.append(f"{r[0]}: role {r[3]!r}")
    return bad


def g_zoom(t: Texts) -> list[str]:
    bad = []
    rows = table_rows(need(t.spec, "pack"), "Z-")
    if not rows:
        bad.append("no Z rows")
    for r in rows:
        if len(r) != 6:
            bad.append(f"{r[0]}: {len(r)} cells")
            continue
        v = type_values(r[1])
        if r[2:6] != v:
            bad.append(f"{r[0]}: {r[2:6]} where the tool computes {v}")
    return bad


def g_cvd(t: Texts) -> list[str]:
    bad = []
    rows = table_rows(need(t.spec, "pack"), "V-")
    if not rows:
        bad.append("no V rows")
    for r in rows:
        if len(r) != 6:
            bad.append(f"{r[0]}: {len(r)} cells")
            continue
        figs, under = cvd_values(r)
        if r[4] != figs or r[5] != under:
            bad.append(f"{r[0]}: {r[4]} / {r[5]} where the tool computes {figs} / {under}")
    return bad


MOTION_TOKEN = re.compile(r"`(motion\.[a-z.]+)`")


def g_motion(t: Texts) -> list[str]:
    spec = need(t.spec, "pack")
    rows = table_rows(section(spec, "### 7.2"), "M-")
    known = known_tokens()
    bad = []
    for r in rows:
        if len(r) != 8:
            bad.append(f"{r[0]}: {len(r)} cells")
            continue
        for col in (3, 4):
            names = MOTION_TOKEN.findall(r[col])
            for n in names:
                if n not in known:
                    bad.append(f"{r[0]}: `{n}` is not a motion token")
            cited_linear = "`linear`" in r[col] and re.search(r"`E05D03`:7[45]", r[7])
            if not names and r[col] != "a cut" and not cited_linear:
                bad.append(f"{r[0]}: {r[col]!r} is neither a token, a cut nor a cited `linear`")
            if names and "ms" in r[col]:
                bad.append(f"{r[0]}: a literal duration")
        if not r[5] or not r[6]:
            bad.append(f"{r[0]}: no reduce variant or carrier")
        elif r[5] == "identical" and r[3] != "a cut":
            bad.append(f"{r[0]}: identical under reduce, yet it moves")
        elif not REDUCE_FORM.fullmatch(r[5]) or MOTION_WORD.search(r[5]):
            bad.append(f"{r[0]}: the reduce cell {r[5]!r} is not an end state (MR-3)")
    for kw in TICKET_MOMENTS:
        hit = [r for r in rows if kw in r[1]]
        if not hit:
            bad.append(f"no moment for the ticket's {kw!r}")
    for r in rows:
        if "filter change" in r[1] and r[3] != "a cut":
            bad.append(f"{r[0]}: the filter-change moment is not a cut (the 800 ms budget)")
    return bad


def reserved_keys(t: Texts) -> set[str]:
    """`05` §3.2's global and accessibility keys, §3.3 rules 3 and 4, and the browser list."""
    p05 = at(t, "05")
    out: set[str] = set()
    cat = ""
    for r in table_rows(section(p05, "### 3.2"), ""):
        if len(r) > 2:
            cat = r[0].strip("*") or cat
            if cat in GLOBAL_CATEGORIES:
                out |= set(re.findall(r"`([^`]+)`", r[2]))
    for ln in section(p05, "### 3.3").split("\n"):
        if re.match(r"[34]\. \*\*", ln):
            out |= set(re.findall(r"`([^`]+)`", ln))
    raw = show(t, BASE, RESERVED_KEYS)
    if raw is None:
        raise LookupError(f"{RESERVED_KEYS} does not resolve at the base")
    out |= set(json.loads(raw))
    return out


def g_keys(t: Texts) -> list[str]:
    spec = need(t.spec, "pack")
    rows = table_rows(section(spec, "## 5."), "K9")
    bad = []
    for a in TICKET_ACTIONS:
        if not any(a in r[1] for r in rows if len(r) > 1):
            bad.append(f"no K row for the ticket's {a!r}")
    km = show(t, BASE, KEYMAP)
    if km is None:
        raise LookupError(f"{KEYMAP} does not resolve at the base")
    bound = {c.get("defaultBinding") for c in json.loads(km).get("commands", [])}
    never = reserved_keys(t)
    if not {"Esc", "Ctrl+K"} <= never:
        bad.append("`05` §3.3 no longer reads `Esc` and `Ctrl+K` as reserved")
    for r in table_rows(section(spec, "### 5.5"), "CM-"):
        d = r[2].strip("`")
        if d == "unbound":
            continue
        if d in never:
            bad.append(f"{r[0]}: {d} is reserved (`05` §3.2, §3.3 or the registry's browser list)")
        if d in bound:
            bad.append(f"{r[0]}: {d} is already a defaultBinding in the registry")
    return bad


def g_finding(t: Texts) -> list[str]:
    spec = need(t.spec, "pack")
    rows = table_rows(section(spec, "## 8."), "F-")
    bad = []
    got = [r[0] for r in rows]
    if got != [f"F-{i:02d}" for i in range(1, len(rows) + 1)]:
        bad.append("the F rows are not F-01 … in order")
    count = {s.lower(): sum(1 for r in rows if r[1] == s) for s in SEVERITIES}
    count["total"] = len(rows)
    for k, n in count.items():
        for v in re.findall(rf"(\d+)<!--=F:{k}-->", spec):
            if int(v) != n:
                bad.append(f"the F:{k} anchor reads {v}, the rows {n}")
    arows = set(re.findall(r"^- \*\*(A-\d+) →", section(spec, "## 9."), re.MULTILINE))
    for fid, floor in MIN_SEVERITY.items():
        sev = [r[1] for r in rows if r[0] == fid]
        if (
            not sev
            or sev[0] not in SEVERITIES
            or SEVERITIES.index(sev[0]) > SEVERITIES.index(floor)
        ):
            bad.append(f"{fid} is graded {sev[0] if sev else 'nowhere'}, below {floor}")
    for r in rows:
        if r[1] not in SEVERITIES:
            bad.append(f"{r[0]}: severity {r[1]!r}")
        close = r[4]
        if r[1] in ("Blocking", "Major"):
            routed_ok = close.startswith("routed:") and re.search(r"\bG-\d+", close)
            if not close.startswith("fix: A-") and not routed_ok:
                bad.append(f"{r[0]}: a {r[1]} closes neither by an A-row nor routed on a gap")
        for a in re.findall(r"A-\d+", close):
            if a not in arows:
                bad.append(f"{r[0]}: closes by {a}, which §9 lacks")
    return bad


AROW = re.compile(r"^- \*\*(A-\d+) → (E41-D02|E41-D03|`14`|`11`)[^*]*\*\*(.*)$", re.MULTILINE)


def owned_lines(t: Texts) -> set[str]:
    out: set[str] = set()
    for key in ("D02", "D03"):
        for ln in at(t, key).split("\n"):
            if ln.startswith(("- **A-", "- **AR-")):
                head = ln.split(")", 1)[0]
                for k, a, _ in cites(head):
                    if k in ("14", "15"):
                        out.add(f"{k}:{a}")
    return out


def g_arow(t: Texts) -> list[str]:
    spec = need(t.spec, "pack")
    rows = AROW.findall(section(spec, "## 9."))
    bad = []
    if [r[0] for r in rows] != [f"A-{i}" for i in range(1, N_AROWS + 1)]:
        bad.append(f"the A-rows are {[r[0] for r in rows]}, not A-1 … A-{N_AROWS}")
    owned = owned_lines(t)
    for aid, target, body in rows:
        quotes = re.findall(r'(?:Old|After) "(.+?)"(?=\. New:| add)', body.replace("Old: ", "Old "))
        if "retired" in body.split(".")[0]:
            if quotes:
                bad.append(f"{aid}: a retired row quotes a text to apply")
            continue
        if not quotes:
            bad.append(f"{aid}: no Old or After text")
            continue
        key = {"E41-D02": "D02", "E41-D03": "D03", "`14`": "14", "`11`": "11"}[target]
        text = at(t, key)
        for q in quotes:
            if text.count(q) != 1:
                bad.append(f"{aid}: {q[:40]!r} stands {text.count(q)} times in {key}")
        if key in ("11", "14"):
            lines = [a for k, a, _ in cites(body) if k == key]
            ls = text.split("\n")
            if not lines or not all(q in ls[lines[0] - 1] for q in quotes):
                bad.append(f"{aid}: its text is not on its cited `{key}` line")
            for q in quotes:
                where = [i for i, ln in enumerate(ls, 1) if q in ln]
                if where and f"14:{where[0]}" in owned:
                    bad.append(f"{aid}: `14`:{where[0]} is a parent's A-row line")
    return bad


def g_request(t: Texts) -> list[str]:
    spec = need(t.spec, "pack")
    bad = []
    for label, text in (("pack", spec), ("hand-off", t.hand or "")):
        for i, ln in enumerate(text.split("\n"), 1):
            keys = {k for k, _, _ in cites(ln)}
            if keys & {"D02", "D03"}:
                bad.append(f"{label}:{i} cites a parent by line; cite its section")
            if "P01" in keys and not (label == "pack" and ln.startswith("| R-")):
                bad.append(f"{label}:{i} cites #5567 outside a request row")
    for name, ref in (("BASE", BASE), ("D02", D02_REF), ("D03", D03_REF), ("P01", P01_REF)):
        m = re.search(rf"`([0-9a-f]+)`<!--=SHA:{name}-->", spec)
        if not m or not ref.startswith(m[1]):
            bad.append(f"the SHA:{name} anchor is not the pinned ref")
    rr = {r[0]: r for r in table_rows(section(spec, "## 12."), "R-")}
    for rid, num, word in (("R-1", "#1018", "merges as is"), ("R-2", "#1081", "merges as is"),
                           ("R-3", "#5567", "merged")):  # fmt: skip
        if rid not in rr or num not in rr[rid][1] or word not in rr[rid][1]:
            bad.append(f"{rid} does not qualify {num} {word!r}")
    return bad


def g_cite(t: Texts) -> list[str]:
    hashes, bad = cite_hashes(t)
    pinned = parse_pins(need(t.pins, "pins file"))
    for label, h in hashes.items():
        if label not in pinned:
            bad.append(f"cite {label} is unpinned: verify it by content, then --repin-ruled")
        elif pinned[label] != h:
            bad.append(f"cite {label}: the line at its ref is not the pinned content")
    return bad


def g_ruled(t: Texts) -> list[str]:
    """The 3 Nov BQ rulings (#1082), checked where they land in the pack."""
    spec = need(t.spec, "pack")
    bad = []
    rv11 = " ".join(next((r for r in table_rows(spec, "RV-11") if r), []))
    if "`journal.tags.owner_only`" not in rv11 or "`rbac.owner_only`" not in rv11:
        bad.append("RV-11 does not gate a Manager's rename, merge and delete owner-only (BQ-06)")
    a1 = re.search(r"^- \*\*A-1 → [^\n]*", section(spec, "## 9."), re.MULTILINE)
    if not a1 or "retired" not in a1[0]:
        bad.append("A-1 is not retired (BQ-03)")
    c5 = " ".join(next((r for r in table_rows(spec, "C-5") if r), []))
    if "routed" in c5 or "SCR-094" not in c5:
        bad.append("C-5 is routed again, or no longer names SCR-094 as the one removal (BQ-03)")
    k96 = " ".join(next((r for r in table_rows(spec, "K96-04") if r), []))
    if "`E47D04`:285" not in k96:
        bad.append("K96-04 does not move focus as E47-D04 rules (`E47D04`:285)")
    cm = section(spec, "### 5.5")
    if "`05`:85" not in cm or "`14`:975" not in cm:
        bad.append("§5.5 does not name `Alt+R` as shadowing the Chart's chord (BQ-04)")
    return bad


def template_labels(t: Texts) -> list[str]:
    """The line labels of `16` §11.4's template block at the base, in order."""
    block = section(at(t, "16"), "### 11.4")
    return re.findall(r"^- \[ \] \*\*([^*]+)\*\*", block, re.MULTILINE)


def g_handoff(t: Texts) -> list[str]:
    hand = need(t.hand, "hand-off")
    labels = template_labels(t)
    bad = [] if len(labels) == 13 else [f"`16` §11.4 reads {len(labels)} template lines, not 13"]
    p15 = at(t, "15").split("\n")
    for c in HANDOFF_CMPS:
        heads = [ln for ln in p15 if ln.startswith(f"### {c} ")]
        name = re.sub(r" \(.*\)$", "", heads[0][4:]) if heads else c
        block = section(hand, f"## Handoff checklist — {name} (E41-D04, #1082)")
        items = [ln for ln in block.split("\n") if ln.startswith("- [")]
        got = [re.sub(r"^- \[[x ]\] \*\*([^*]+)\*\*.*", r"\1", ln) for ln in items]
        if not block:
            bad.append(f"{c}: no `16` §11.4 block headed {name!r}")
        elif got != labels:
            bad.append(f"{c}: the block's lines are not `16` §11.4's ({len(got)} of {len(labels)})")
        for ln in items:
            if ln.startswith("- [x] ") and not re.search(r"\*\* [^—]*— \S.{2,}", ln):
                bad.append(f"{c}: a ticked line with no evidence: {ln[:50]!r}")
            elif ln.startswith("- [ ] ") and not re.search(r"(?:N/A|PENDING) — \S.{2,}", ln):
                bad.append(f"{c}: an open line with no N/A or PENDING reason: {ln[:50]!r}")
            elif not ln.startswith(("- [x] ", "- [ ] ")):
                bad.append(f"{c}: a line neither ticked nor open: {ln[:50]!r}")
    return bad


def g_hygiene(t: Texts) -> list[str]:
    bad = []
    checks = ((CLOSING, "a closing keyword (PR 2 closes #1082)"), (LOCAL_PATH, "a local path"),
              (AGENT_NAME, "an agent name"), (URL_OR_HOST, "a URL or a host"))  # fmt: skip
    files = [("deck", t.deck), ("tool", t.tool)]
    if t.stage == FULL:
        files += [("pack", t.spec), ("hand-off", t.hand), ("pins", t.pins)]
    for label, text in files:
        for i, ln in enumerate((text or "").split("\n"), 1):
            if label != "tool":
                for rx, what in checks:
                    if rx.search(ln):
                        bad.append(f"{label}:{i} carries {what}")
                if "{{" in ln:
                    bad.append(f"{label}:{i} carries a double-brace slot")
            if any(d in ln.lower() for d in DENY):
                bad.append(f"{label}:{i} carries a public-text deny word")
    if t.deck:
        _, entries = deck_lines(t)
        for e in entries:
            for k, v in e.items():
                odd = isinstance(v, str) and ("://" in v or HOSTNAME.search(v) or KEYLIKE.search(v))
                if odd and k != "id":
                    bad.append(f"{e.get('id')}: `{k}` carries a URL, host or key-like value")
    for p in OWN_PATHS:
        if any(w in Path(p).name.lower() for w in RESERVED_NAME):
            bad.append(f"{p}: a reserved word in an own file name")
    return bad


def g_scope(t: Texts) -> list[str]:
    paths = DECK_PATHS if t.stage == DECK else OWN_PATHS
    bad = []
    present = {SPEC_REL: t.spec, HAND_REL: t.hand, DECK_REL: t.deck, TOOL_REL: t.tool,
               PINS_REL: t.pins}  # fmt: skip
    for p in paths:
        if present[p] is None:
            bad.append(f"{p} is missing in the {t.stage} stage")
    if t.changed is None:
        return bad + ["cannot list the changed paths (git failed)"]
    own = ", ".join(OWN_PATHS)  # a combined PR may carry the pack beside the deck
    return bad + [f"{p} is touched; this ticket owns {own}" for p in t.changed
                  if p not in OWN_PATHS]  # fmt: skip


DECK_GATES: dict[str, Callable[[Texts], list[str]]] = {
    "G-DECK": g_deck, "G-HYGIENE": g_hygiene, "G-SCOPE": g_scope,
}  # fmt: skip
GATES: dict[str, Callable[[Texts], list[str]]] = {
    "G-DECK": g_deck, "G-COPY": g_copy, "G-ANNOUNCE": g_announce, "G-STATES": g_states,
    "G-MAP": g_map, "G-TOKEN": g_token, "G-CONTRAST": g_contrast, "G-ZOOM": g_zoom,
    "G-CVD": g_cvd, "G-MOTION": g_motion, "G-KEYS": g_keys, "G-FINDING": g_finding,
    "G-AROW": g_arow, "G-REQUEST": g_request, "G-CITE": g_cite, "G-RULED": g_ruled,
    "G-HANDOFF": g_handoff,
    "G-HYGIENE": g_hygiene, "G-SCOPE": g_scope,
}  # fmt: skip


def gates_for(stage: str) -> dict[str, Callable[[Texts], list[str]]]:
    return DECK_GATES if stage == DECK else GATES


def audit(t: Texts) -> list[tuple[str, str]]:
    out = []
    for g, fn in gates_for(t.stage).items():
        try:
            out += [(g, m) for m in fn(t)]
        except LookupError as e:
            out.append((g, str(e)))
    return out


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


def read(rel: str) -> str | None:
    p = ROOT / rel
    return p.read_text(encoding="utf-8") if p.exists() else None


def load(stage: str) -> Texts:
    tool = need(read(TOOL_REL), "tool")
    spec = read(SPEC_REL) if stage == FULL else None
    hand = read(HAND_REL) if stage == FULL else None
    pins = read(PINS_REL) if stage == FULL else None
    return Texts(stage, spec, hand, read(DECK_REL), pins, tool, changed_paths(), {})


def fill(t: Texts) -> str:
    counts = {s.lower(): 0 for s in SEVERITIES}
    out = []
    for ln in need(t.spec, "pack").split("\n"):
        c = cells(ln)
        if ln.startswith("| P-") and len(c) == 8:
            v = ratios(tok(c[1]), tok(c[2]))
            c[4:8] = [*v, verdict(c[3], v)]
            ln = "| " + " | ".join(c) + " |"
        elif ln.startswith("| Z-") and len(c) == 6:
            c[2:6] = type_values(c[1])
            ln = "| " + " | ".join(c) + " |"
        elif ln.startswith("| V-") and len(c) == 6:
            c[4], c[5] = cvd_values(c)
            ln = "| " + " | ".join(c) + " |"
        elif ln.startswith("| F-") and len(c) > 1 and c[1] in SEVERITIES:
            counts[c[1].lower()] += 1
        out.append(ln)
    text = "\n".join(out)
    counts["total"] = sum(counts.values())
    for k, n in counts.items():
        text = re.sub(rf"\d+<!--=F:{k}-->", f"{n}<!--=F:{k}-->", text)
    for k, n in deck_counts(t).items():
        text = re.sub(rf"\d+<!--=COPY:{k}-->", f"{n}<!--=COPY:{k}-->", text)
    return text


def measurements(t: Texts) -> dict[str, Any]:
    spec = need(t.spec, "pack")
    out: dict[str, Any] = {"base": BASE, "themes": list(THEMES), "contrast": [], "zoom": [],
                           "cvd": []}  # fmt: skip
    for r in table_rows(spec, "P-"):
        v = ratios(tok(r[1]), tok(r[2]))
        out["contrast"].append({"id": r[0], "fg": tok(r[1]), "bg": tok(r[2]), "role": r[3],
                                "ratios": dict(zip(THEMES, v, strict=True)),
                                "verdict": verdict(r[3], v)})  # fmt: skip
    for r in table_rows(spec, "Z-"):
        out["zoom"].append({"id": r[0], "token": tok(r[1]), "values": type_values(r[1])})
    for r in table_rows(spec, "V-"):
        figs, under = cvd_values(r)
        out["cvd"].append({"id": r[0], "a": tok(r[1]), "b": tok(r[2]), "theme": r[3],
                           "delta_e76": figs, "under_jnd": under})  # fmt: skip
    return out


def sub(old: str, new: str, field: str = "spec") -> Callable[[Texts], Texts]:
    def f(t: Texts) -> Texts:
        text = str(getattr(t, field) or "")
        if text.count(old) != 1:
            raise SystemExit(f"self-test: the {field} carries {old[:50]!r} {text.count(old)} times")
        changes: dict[str, Any] = {field: text.replace(old, new)}
        return replace(t, **changes)

    return f


def set_cell(lead: str, col: int, value: str) -> Callable[[Texts], Texts]:
    def f(t: Texts) -> Texts:
        ls = (t.spec or "").split("\n")
        i = next(k for k, ln in enumerate(ls) if ln.startswith(f"| {lead} "))
        c = cells(ls[i])
        c[col] = value
        ls[i] = "| " + " | ".join(c) + " |"
        return replace(t, spec="\n".join(ls))

    return f


def drop_row(lead: str) -> Callable[[Texts], Texts]:
    return lambda t: replace(t, spec="\n".join(ln for ln in (t.spec or "").split("\n")
                                               if not ln.startswith(lead)))  # fmt: skip


def deck_edit(eid: str, key: str, value: Any) -> Callable[[Texts], Texts]:
    def f(t: Texts) -> Texts:
        out = []
        for ln in (t.deck or "").split("\n"):
            if ln.strip() and json.loads(ln).get("id") == eid:
                o = json.loads(ln)
                o[key] = value
                ln = json.dumps(o, ensure_ascii=False)
            out.append(ln)
        return replace(t, deck="\n".join(out))

    return f


def deck_add(obj: dict[str, Any]) -> Callable[[Texts], Texts]:
    """Append a deck entry and, in the full stage, bump the pack's count anchors to match."""

    def f(t: Texts) -> Texts:
        deck = (t.deck or "").rstrip("\n") + "\n" + json.dumps(obj, ensure_ascii=False) + "\n"
        spec = t.spec
        if spec is not None:
            for k in ("total", obj["status"]):
                n = deck_counts(t)[k] + 1
                spec = re.sub(rf"\d+<!--=COPY:{k}-->", f"{n}<!--=COPY:{k}-->", spec)
        return replace(t, deck=deck, spec=spec)

    return f


def recount(fn: Callable[[Texts], Texts]) -> Callable[[Texts], Texts]:
    """Apply `fn`, then set the count anchors to the rows, as --fill does."""

    def f(t: Texts) -> Texts:
        t2 = fn(t)
        return replace(t2, spec=fill(t2))

    return f


OUT_OF_GRANT = {"id": "journal.tags.usage_elsewhere", "screen": "SCR-096", "kind": "string",
                "text": "Also used on {n} trades in accounts outside your access",
                "status": "PROPOSED", "source": "E41-D04 §10.7", "owner": "E41-D04",
                "rbac": "manager"}  # fmt: skip

WITHHELD_TWIN = {"id": "journal.merge.confirm_withheld", "screen": "SCR-096", "kind": "string",
                 "text": "Merge tags", "status": "PROPOSED", "source": "E41-D04 §10.7 RV-11",
                 "owner": "E41-D04", "rbac": "manager"}  # fmt: skip

MUTATIONS: tuple[tuple[str, str, str, Callable[[Texts], Texts]], ...] = (
    ("both", "G-DECK", "retype a merged string", deck_edit("journal.caveat.sample", "text", "Fewer than 20 trades — statistics are weak")),
    (DECK, "G-DECK", "mark a parent string merged", deck_edit("journal.bulk.count", "status", "merged")),
    (DECK, "G-DECK", "use a status outside the vocabulary", deck_edit("journal.an.updating", "status", "final")),
    ("both", "G-DECK", "retype a parent string", deck_edit("journal.merge.confirm", "text", "Merge all {n} trades")),
    (DECK, "G-DECK", "drop a frozen flag", deck_edit("journal.typed", "frozen", None)),
    ("both", "G-DECK", "make a string assertive", deck_edit("journal.an.sort", "announce", "assertive")),
    ("both", "G-DECK", "add an unfrozen out-of-grant count", deck_add(OUT_OF_GRANT)),
    ("both", "G-DECK", "add a count-free twin of an owner-only confirm", deck_add(WITHHELD_TWIN)),
    ("both", "G-HYGIENE", "put a host into a deck string", deck_edit("journal.an.updating", "source", "E41-D04 §4, see example.com")),
    ("both", "G-HYGIENE", "put a deny word into the tool", lambda t: replace(t, tool=t.tool + "\n# " + DENY[6] + "\n")),
    (DECK, "G-SCOPE", "touch `14` in the deck stage", lambda t: replace(t, changed=[*DECK_PATHS, PATHS["14"]])),
    (FULL, "G-COPY", "name an id the deck lacks", sub("`journal.an.selection_cleared`", "`journal.an.selection_gone`")),
    (FULL, "G-COPY", "misstate the deck's count", sub("**261<!--=COPY:total--> strings:", "**260<!--=COPY:total--> strings:")),
    (FULL, "G-ANNOUNCE", "make a row assertive", set_cell("AN-14", 3, "assertive, once")),
    (FULL, "G-ANNOUNCE", "drop the sort announcement", drop_row("| AN-01 ")),
    (FULL, "G-STATES", "drop a parent state", drop_row("| S95-14 ")),
    (FULL, "G-MAP", "drop a ticket component", drop_row("| MP-10 ")),
    (FULL, "G-MAP", "misname a component", set_cell("MP-11", 1, "CMP-046 SidePanel")),
    (FULL, "G-TOKEN", "misspell a token", sub("`space.panel.padding`; cards", "`space.panel.pading`; cards")),
    (FULL, "G-TOKEN", "write a raw colour", sub("swatch `radius.xs`", "swatch `radius.xs` #5B8DEF")),
    (FULL, "G-CONTRAST", "type a figure off", set_cell("P-01", 4, "1.00")),
    (FULL, "G-CONTRAST", "pass the rejected pair", set_cell("P-21", 3, "text")),
    (FULL, "G-ZOOM", "type a size off", set_cell("Z-02", 3, "20")),
    (FULL, "G-CVD", "type a ΔE off", set_cell("V-01", 4, "1.00 / 1.00 / 1.00 / 1.00")),
    (FULL, "G-MOTION", "write a literal duration", set_cell("M-04", 3, "240 ms")),
    (FULL, "G-MOTION", "animate the filter change", set_cell("M-06", 3, "`motion.duration.normal`")),
    (FULL, "G-MOTION", "drop a reduce variant", set_cell("M-11", 5, "")),
    (FULL, "G-MOTION", "a reduce variant that still slides", set_cell("M-04", 5, "a shorter 100 ms slide")),
    (FULL, "G-KEYS", "bind a taken key", set_cell("CM-01", 2, "`F`")),
    (FULL, "G-KEYS", "bind the browser's reload", set_cell("CM-02", 2, "`Ctrl+R`")),
    (FULL, "G-KEYS", "drop the replay jump", lambda t: drop_row("| K94-03 ")(drop_row("| K93-07 ")(t))),
    (FULL, "G-FINDING", "let a Major close by acceptance", set_cell("F-05", 4, "accepted: minor")),
    (FULL, "G-FINDING", "misstate a count", sub("Major 9<!--=F:major-->", "Major 8<!--=F:major-->")),
    (FULL, "G-FINDING", "demote F-09 to Info, counts adjusted", recount(set_cell("F-09", 1, "Info"))),
    (FULL, "G-AROW", "an Old text off by one character", sub('Old: "Win rate 43 %"', 'Old: "Win rate 43  %"')),
    (FULL, "G-AROW", "anchor on a parent's `14` line", sub('After "- **Stories:** US-JRN-001, US-JRN-002, US-JRN-003, US-JRN-008."', 'After "- **Components:** CMP-026 EmptyState, CMP-047 DatePicker / DateRangePicker, CMP-049 Table, CMP-055 FilterBar, CMP-116 PnLBadge, CMP-166 JournalEntryRow, CMP-169 TagEditor."')),
    (FULL, "G-REQUEST", "cite a parent by line", set_cell("F-10", 2, "`D02`:157")),
    (FULL, "G-REQUEST", "drop R-1's qualifier", sub("(#5717, PR 1b's head), if #1018's PR merges as is", "(#5717, PR 1b's head), if #1018's PR merges")),
    (FULL, "G-CITE", "re-point a cite to an unpinned line", sub("(`E29D04H`:115)", "(`E29D04H`:114)")),
    (FULL, "G-AROW", "un-retire A-1 with a text to apply", sub("(F-01) — retired (BQ-03, ruled jointly):", "(F-01) — retired (BQ-03, ruled jointly). Old: \"and has a remove button\". New: \"x\"; then:")),
    (FULL, "G-RULED", "let a Manager rename, merge and delete again", set_cell("RV-11", 3, "every write as for the owner")),
    (FULL, "G-RULED", "route C-5 to E41-D02's owner again", set_cell("C-5", 2, "routed to the D02 owner (BQ-03)")),
    (FULL, "G-RULED", "send focus back to the gone row", set_cell("K96-04", 3, "focus returns to the row's IconButton, else the grid")),
    (FULL, "G-RULED", "drop the `Alt+R` shadow note", sub("which `05` allows only across mutually exclusive focus contexts (`05`:85)", "which `05` allows only across mutually exclusive focus contexts")),
    (FULL, "G-HANDOFF", "drop CMP-168's keyboard line", sub("- [x] **Keyboard table** — §5.3 K95-04: one stop per tile", "§5.3 K95-04: one stop per tile", "hand")),
    (FULL, "G-HANDOFF", "leave an N/A without a reason", sub("N/A — static chips; an add or a removal speaks once (AN-04, AN-12)", "N/A —", "hand")),
    (FULL, "G-HYGIENE", "write a closing keyword", sub("Owner approval is pending.\n", "Owner approval is pending. Closes #1082.\n")),
    (FULL, "G-SCOPE", "touch `15` in the diff", lambda t: replace(t, changed=[*OWN_PATHS, PATHS["15"]])),
)  # fmt: skip


def selftest(stage: str) -> tuple[bool, list[str]]:
    base = load(stage)
    base = replace(base, changed=list(DECK_PATHS if stage == DECK else OWN_PATHS))
    before = (base.spec, base.hand, base.deck)
    found = audit(base)
    out = [f"self-test ({stage}): baseline {len(found)} FAIL"]
    out += [f"  baseline {g}: {m}" for g, m in found]
    ok = not found
    muts = [m for m in MUTATIONS if m[0] in (stage, "both")]
    for i, (_, gate, what, fn) in enumerate(muts, 1):
        gates = sorted({g for g, _ in audit(fn(base))})
        good = gates == [gate]
        ok &= good
        out.append(
            f"{'ok  ' if good else 'FAIL'} M-{i} {gate}: {what} -> {', '.join(gates) or 'none'}"
        )
    covered = {g for _, g, _, _ in muts}
    missing = [g for g in gates_for(stage) if g not in covered]
    ok &= not missing
    again = load(stage)
    restored = (again.spec, again.hand, again.deck) == before
    ok &= restored
    out.append(f"self-test: gates with no mutation: {', '.join(missing) or 'none'}")
    out.append(f"self-test: {len(muts)} mutations, text restored: {'yes' if restored else 'NO'}")
    out.append(f"self-test: {'PASS' if ok else 'FAIL'}")
    return ok, out


def main(argv: list[str]) -> int:
    ap = argparse.ArgumentParser(description="E41-D04 journal review, motion and hand-off audit")
    ap.add_argument("--stage", choices=(DECK, FULL), required=True)
    g = ap.add_mutually_exclusive_group()
    g.add_argument("--check", action="store_true")
    g.add_argument("--fill", action="store_true")
    g.add_argument("--json", action="store_true")
    g.add_argument("--self-test", action="store_true")
    g.add_argument("--repin-ruled", action="store_true")
    a = ap.parse_args(argv)
    if a.self_test:
        ok, lines = selftest(a.stage)
        print("\n".join(lines))
        return 0 if ok else 1
    t = load(a.stage)
    if (a.fill or a.json or a.repin_ruled) and a.stage != FULL:
        print("refused: --fill, --json and --repin-ruled run in the full stage only")
        return 1
    if a.fill:
        (ROOT / SPEC_REL).write_text(fill(t), encoding="utf-8")
        print(f"filled §6, §8 and §10.6's anchors in {SPEC_REL}")
        return 0
    if a.json:
        print(json.dumps(measurements(t), ensure_ascii=False, indent=2))
        return 0
    if a.repin_ruled:
        hashes, bad = cite_hashes(t)
        if bad:
            print(f"refused: {bad[0]}")
            return 1
        head = (
            "# E41-D04 cite pins: the cite, a hash of its cited line(s) at its ref."
            " Written by --repin-ruled only.\n"
        )
        body = "".join(f"{k}\t{h}\n" for k, h in hashes.items())
        (ROOT / PINS_REL).write_text(head + body, encoding="utf-8")
        print(f"wrote {PINS_REL} ({len(hashes)} cites)")
        return 0
    found = audit(t)
    for gate, msg in found:
        print(f"FAIL {gate}: {msg}")
    print(f"{len(found)} FAIL ({len(gates_for(a.stage))} gates, {a.stage} stage)")
    return 1 if found else 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
