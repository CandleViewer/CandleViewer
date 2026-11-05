#!/usr/bin/env python3
"""E18-D05 (#499) audit: the E18 footprint hand-off pack (SCR-030, SCR-032, SCR-056).

Offline and default-deny. The shared gates (git, cites, G-T2 vocabulary, closing keywords,
hygiene, public text, G-UNTOUCHED, the runner and the mutation harness) live in
`spec_audit_lib.py`, imported from `main` beside this file, never copied; this file keeps only
E18-D05's rows. It reads, AS TEXT at a pinned commit, E18-D02, E18-D04, E09-D09 and the E18
backlog at the base, and E18-D03 at PR #5881's head (cited "if it merges as is"); from the
working tree, the stage's files. It runs no repo code.

Stages, named by `--stage` (required; never guessed from the working tree). Slice 1a's `deck`
stage gates the copy deck and this tool alone; slice 1b's `full` stage, stacked on it, adds the
pack, the hand-off and the pins file and runs every gate below. It also reads, at the base, the
plan documents the pack cites, E25-D05's hand-off, the E06 report and ADR-0011; and D03's and
D04's hand-offs at their PR heads (#5881, #5908; "if it merges as is").

Gates (each FAIL led by its name):
  G-DECK       the header line first (pack, slice, base, the D03 head, the statuses, the
               `frozen` flag and the row and status counts, recomputed); then one JSON row per
               string with every field and none outside the closed set; a unique dotted id; a
               known screen, kind and status; an owner that is a ticket key (or `14`); a consumer
               that is an E18 story; `frozen` null for an E18-owned string, else its reason.
  G-SOURCE     each row's text stands on its cited line or wrapped line range (table pipes, box
               edges and runs of blanks folded) as a whole span, never a cut word; a `merged` row
               cites a merged file (D02, D04, D09); a D03 row (PR #5881, open) is PROPOSED; a
               `t2` row citing E09-D09 is its §3.1 template filled, so its §3.2 verb stands on
               the cited verb-table line as a whole span.
  G-WDECK      D03 §11's W-1 ... W-25, read at the pinned head, each have exactly one deck row
               carrying that `ref` with the same string, except a W row the ruling of record
               re-words (RULED_W: W-11 by BQ-7), whose row carries the ruled string and the
               status RULED (no other row does) while D03 still carries its own (a ruled
               override goes stale once D03 takes it); each
               verbatim W row's string stands on the D02 line D03 cites.
  G-LR         D04 §7.3's announced rows LR-2 ... LR-5 each have a deck row, and every LR row's
               text stands in that LR row's Text cell; every `announce` row, and no other, carries
               `live: polite`, the one polite `role="status"` region D04 §7.3 rules (never
               `assertive`), read in that section.
  G-T2         every `t2` row has a `key`: an E09-D09 §3.1 key whose template the text fills
               with a §3.2 verb (or a verb narrowed by a named authority; D02 A-29's "rebuild
               footprint cells" is none, by BQ-7), or `state`, PROPOSED
               and owned by E18-D05 or E17-D01; every reason is one sentence, at most 60
               characters, with no figure (G-T2.4).
  G-SUPERSEDED the ticket's two settled-away strings (`T` Scope, read in the E18 backlog) are no
               deck text, and the rows that replace them (D02 A-26: W-8, W-9 and the 150 %
               ratio message) are present.
  G-HYGIENE    no closing keyword, CR, trailing blank, invisible character, URL, local path,
               host, lane or persona name, HTML comment or placeholder word in the stage's
               texts (the deck and this tool; in `full` also the pack, hand-off and pins).
  G-SCOPE      the stage's files are present and the diff against `git merge-base HEAD
               origin/main` touches only them.
 The `full` stage adds:
  G-RULING     the BQ section is RULED: its heading names the ruling and the list, BQ-0 ... BQ-9
               carry the ruled verdicts, and each bullet's hash equals the pins file's row.
  G-MAP        §3 against `24` §4.7, `22`'s `getFootprint` and `23`'s `footprint` options: every
               field, parameter and option named exists; every §4.7 field is mapped or listed as
               not exposed; "applies as" is instant, re-snapshot or rebuild; a `ctl` key only
               where `23` makes it one; Rows re-snapshots; the ratio row carries the contract's
               1.5 to 20 (150 to 2000 %).
  G-SPIKE      §4.1 quotes E06's evidence rule as it stands; rows (a), (b) and (c) are PENDING and
               never met; (c) names ADR-0011; every §4.2 number has a provenance label and a G-row
               owned by E18-K01 #583.
  G-DECKPACK   §5.1's counts add up to the deck's rows and its PROPOSED count; every deck id the
               pack or the hand-off names is a deck row; §5.3's state keys are the deck's E18 ones.
  G-SIGNOFF    §9 has a row per item of `14`'s five checklists (SCR-045: E18's one) and no tick.
  G-HANDOFF    §G: a block only for CMP-197, CMP-046 and CMP-227, each with `16` §11.4's lines in
               order, `[x]` with evidence (never N/A) or `[ ]` with PENDING or N/A; every linked
               checklist cite is that component's block.
  G-AROW       each §C row's Old stands on its cited line; a pointer row sits after the last
               pointer line of its `14` entry.
  G-CITE       every cite of the pack and the hand-off resolves at its pin on a non-blank line,
               and each load-bearing cite still carries its words.
  G-T2STD      R-2 names every G-T2 marker (`.claude/rules/32-design-specs.md`).
  G-WALK       §13 has at most ten items, R1, R2 and R3 one each.

Usage (from the repo root):
  python3 -I docs/design/_tools/e18_d05_handoff_audit.py --stage deck --check
  python3 -I docs/design/_tools/e18_d05_handoff_audit.py --stage deck --self-test
  python3 -I docs/design/_tools/e18_d05_handoff_audit.py --stage full --check
  python3 -I docs/design/_tools/e18_d05_handoff_audit.py --stage full --self-test
  python3 -I docs/design/_tools/e18_d05_handoff_audit.py --stage full --repin-ruled
Every mode needs `--stage`. On slice 1b's branch only `--stage full` passes: the deck stage's
G-SCOPE admits slice 1a's files alone.
Exit 0 = no FAIL; 1 = at least one FAIL; 2 = a usage error.
"""

from __future__ import annotations

import functools
import json
import re
import sys
from collections.abc import Callable
from dataclasses import replace
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import spec_audit_lib as L  # the shared helper sits beside this file (main's blob 15793f79cf92)

ROOT = Path(__file__).resolve().parents[3]
BASE = "e7cc2dd2a1f8d70de462e0644a1e7e5aa02108a8"  # origin/main; D02, D04 and E09-D09 merged here
D03_HEAD = "67a2907b444265bc280b0ace9c86a2b12738e2ae"  # PR #5881 head (E18-D03 slice 1c), open
D04H_HEAD = "17e6d17d9750aed331577a5badb1d36b0732c618"  # PR #5908 head (E18-D04 slice 1b), open

DECK_REL = "docs/design/E18/E18-D05-copy-deck.jsonl"
TOOL_REL = "docs/design/_tools/e18_d05_handoff_audit.py"
PACK_REL = "docs/design/E18/E18-D05.md"
HANDOFF_REL = "docs/design/E18/E18-D05-handoff.md"
PINS_REL = "docs/design/_tools/e18_d05_ruled_pins.txt"
STAGES = {
    "deck": (DECK_REL, TOOL_REL),
    "full": (DECK_REL, TOOL_REL, PACK_REL, HANDOFF_REL, PINS_REL),
}

KEYED = {
    "D02": L.DocRef("docs/design/E18/E18-D02.md", BASE),
    "D03": L.DocRef("docs/design/E18/E18-D03.md", D03_HEAD),
    "D04": L.DocRef("docs/design/E18/E18-D04.md", BASE),
    "D09": L.DocRef("docs/design/E09/E09-D09.md", BASE),
    "E18J": L.DocRef("docs/plan/backlog/E18.json", BASE),
    "D03H": L.DocRef("docs/design/E18/E18-D03-handoff.md", D03_HEAD),
    "D04H": L.DocRef("docs/design/E18/E18-D04-handoff.md", D04H_HEAD),
    "E24": L.DocRef("docs/design/E24/E24-D05.md", BASE),
    "E25H": L.DocRef("docs/design/E25/E25-D05-handoff.md", BASE),
    "E06R": L.DocRef("docs/plan/spikes/E06-M0-report.md", BASE),
    "ADR11": L.DocRef("docs/plan/27-adrs/ADR-0011-electron-vs-tauri.md", BASE),
}
MERGED_KEYS = ("D02", "D04", "D09")

FIELDS: tuple[str, ...] = (
    "id",
    "text",
    "screen",
    "kind",
    "where",
    "status",
    "owner",
    "source",
    "ref",
)
FIELDS += ("consumer", "frozen")
OPTIONAL = ("key", "narrowed", "live")
HEADER = {
    "pack": "E18-D05",
    "slice": "1a",
    "base": BASE[:9],
    "d03_head": D03_HEAD[:9],
    "statuses": ["merged", "PROPOSED", "RULED"],
    "flags": ["frozen"],
}
SCREENS = ("SCR-030", "SCR-032", "SCR-042", "SCR-056", "CMP-228")
KINDS: tuple[str, ...] = (
    "announce",
    "badge",
    "button",
    "canvas",
    "caption",
    "cell",
    "chip",
    "dialog",
    "header",
)
KINDS += ("label", "legend", "menu", "message", "name", "notice", "strip", "t2", "title")
KINDS += ("tooltip",)
STATUSES = ("merged", "PROPOSED", "RULED")
ID_RE = re.compile(r"footprint(?:\.[a-z0-9_]+)+")
OWNER_RE = re.compile(r"E\d\d-[DSTKQX]\d\d|14")
CONSUMER_RE = re.compile(r"E18-S(?:0[1-9]|1[01])")
EN = "\u2013"  # the en dash of a line range
SOURCE_RE = re.compile(rf"(D0[234]|D09):(\d+)(?:{EN}(\d+))?")
REF_RE = re.compile(r"W-(?:[1-9]|1\d|2[0-5])|LR-(?:[1-9]|1[0-2])")
FOLD_EDGES = " |+│\t"

W_HEADING = "## 11. Copy deck"
W_ROW = re.compile(r"W-\d+")
D02_CITE = re.compile(rf"D02:(\d+)(?:{EN}(\d+))?")
LR_HEADING = "### 7.3 The announcement policy table"
LR_ANNOUNCED = ("LR-2", "LR-3", "LR-4", "LR-5")
LR_POLICY = ('role="status"', "never `assertive`")  # D04 §7.3's one polite region

T2_TEMPLATES = {
    "rbac.permission": "Your role can't {verb}.",
    "rbac.owner_only": "Only the owner can {verb}.",
}
NARROWINGS = {  # a verb narrower than E09-D09 §3.2's, and the authority that narrows it
    "E09-D09 §3.2": frozenset({"start recording"}),  # §3.2's recording row: a CTA may narrow it
}
RULED_W = {  # W rows the ruling of record (comment 6652596258) re-words, and the ruling
    "W-11": ("Only the owner can change recording.", "BQ-7"),
}
STATE_OWNERS = ("E18-D05", "E17-D01")  # D02:937 hands the footprint's state keys to E18-D05

SUPERSEDED = (  # `T` Scope's strings that D02 A-26 settles away (BQ-6 (a), (b))
    "Reduced detail: footprint text hidden below N px cells",
    "Enter a ratio between 100 and 2000 %.",
)
REPLACEMENTS = ("footprint.badge.zoom", "footprint.badge.load", "footprint.valid.ratio")
PLACEHOLDER = re.compile(r"\bTBD\b|\bTODO\b|\bFIXME\b|\?\?\?|\bXXX\b")


# ---------- sources -------------------------------------------------------------------------------
@functools.cache
def repo() -> L.Repo:
    return L.Repo(ROOT)


@functools.cache
def docs() -> L.Docs:
    return L.Docs(repo(), BASE, KEYED)


def doc_lines(key: str) -> tuple[str, ...]:
    got = docs().lines(key)
    if got is None:
        raise L.AuditError(f"{key} is not readable at its pin")
    return got


def fold(s: str) -> str:
    return re.sub(r"\s+", " ", s.strip(FOLD_EDGES)).strip()


def span(key: str, lo: int, hi: int) -> str:
    ls = doc_lines(key)
    if not 1 <= lo <= hi <= len(ls):
        raise L.AuditError(f"{key}:{lo}{EN}{hi} is outside {key}'s {len(ls)} lines")
    return " ".join(fold(x) for x in ls[lo - 1 : hi])


def whole_span(hay: str, text: str) -> bool:
    """`text` stands in `hay` with no letter or digit glued to either end."""
    i = hay.find(text)
    while text and i >= 0:
        a = hay[i - 1] if i > 0 else " "
        j = i + len(text)
        b = hay[j] if j < len(hay) else " "
        if not (a.isalnum() and text[0].isalnum()) and not (b.isalnum() and text[-1].isalnum()):
            return True
        i = hay.find(text, i + 1)
    return False


# ---------- the deck ------------------------------------------------------------------------------
Row = dict[str, object]


def parse_deck(text: str) -> tuple[Row, list[Row]]:
    lines = [ln for ln in text.split("\n") if ln.strip()]
    if not lines:
        raise ValueError("the deck is empty")
    head = json.loads(lines[0])
    rows = [json.loads(ln) for ln in lines[1:]]
    if not isinstance(head, dict) or not all(isinstance(r, dict) for r in rows):
        raise ValueError("a deck line is not a JSON object")
    return head, rows


def deck(t: L.Tree) -> tuple[Row, list[Row]]:
    return parse_deck(t.text("deck"))


def s(r: Row, f: str) -> str:
    v = r.get(f)
    return v if isinstance(v, str) else ""


def counts(rows: list[Row]) -> dict[str, int]:
    out = {"rows": len(rows)}
    out.update({st: sum(r.get("status") == st for r in rows) for st in STATUSES})
    return out


# ---------- gates ---------------------------------------------------------------------------------
def g_deck(t: L.Tree) -> list[str]:
    head, rows = deck(t)
    bad = [
        f"header {k} is {head.get(k)!r}, not {v!r}" for k, v in HEADER.items() if head.get(k) != v
    ]
    if head.get("counts") != counts(rows):
        bad.append(f"header counts {head.get('counts')} are not the rows' {counts(rows)}")
    seen: set[str] = set()
    for r in rows:
        rid = s(r, "id")
        missing = [f for f in FIELDS if f not in r]
        extra = [f for f in r if f not in FIELDS + OPTIONAL]
        if missing or extra:
            bad.append(f"{rid or r}: missing {missing}, unknown {extra}")
        if not ID_RE.fullmatch(rid) or rid in seen:
            bad.append(f"{rid!r}: not a dotted footprint id, or a duplicate")
        seen.add(rid)
        for f, ok in (
            ("screen", s(r, "screen") in SCREENS),
            ("kind", s(r, "kind") in KINDS),
            ("status", s(r, "status") in STATUSES),
            ("owner", bool(OWNER_RE.fullmatch(s(r, "owner")))),
            ("consumer", bool(CONSUMER_RE.fullmatch(s(r, "consumer")))),
            ("text", bool(s(r, "text").strip()) and s(r, "where") != ""),
            ("ref", r.get("ref") is None or bool(REF_RE.fullmatch(s(r, "ref")))),
        ):
            if not ok:
                bad.append(f"{rid}: bad {f}")
        e18 = s(r, "owner").startswith("E18-")
        if e18 != (r.get("frozen") is None) or not (e18 or s(r, "frozen")):
            bad.append(f"{rid}: `frozen` must be null for an E18 string, else its reason")
    return bad


def t2_verb(r: Row) -> str:
    """The verb a `t2` row fills its §3.1 template with ("" if the text does not fill it)."""
    tpl = T2_TEMPLATES.get(s(r, "key"), "")
    if "{verb}" not in tpl:
        return ""
    lead, tail = tpl.split("{verb}")
    text = s(r, "text")
    ok = text.startswith(lead) and text.endswith(tail) and len(text) > len(lead + tail)
    return text[len(lead) : -len(tail)] if ok else ""


def g_source(t: L.Tree) -> list[str]:
    _, rows = deck(t)
    bad: list[str] = []
    for r in rows:
        rid, src = s(r, "id"), s(r, "source")
        m = SOURCE_RE.fullmatch(src)
        if m is None:
            bad.append(f"{rid}: source {src!r} is not KEY:line or KEY:a{EN}b")
            continue
        key, lo = m.group(1), int(m.group(2))
        hi = int(m.group(3) or lo)
        if key != "D09" and not whole_span(span(key, lo, hi), s(r, "text")):
            bad.append(f"{rid}: its text is not a whole span on {src}")
        if r.get("status") == "merged" and key not in MERGED_KEYS:
            bad.append(f"{rid}: `merged` but cites {key}, which is not merged")
        verb = t2_verb(r) if key == "D09" and r.get("kind") == "t2" else None
        if key == "D09" and r.get("kind") == "t2":
            if not verb or not whole_span(span(key, lo, hi), verb):
                bad.append(f"{rid}: its §3.2 verb {verb!r} is not a whole span on {src}")
            continue
    return bad


def w_rows() -> dict[str, tuple[str, str, str]]:
    """D03 §11 at the pinned head: W-n -> (string, source cell, status cell)."""
    block = L.section("\n".join(doc_lines("D03")), W_HEADING)
    out = {
        r[0]: (L.unquote(r[2]), r[3], r[4]) for r in L.table_rows(block) if W_ROW.fullmatch(r[0])
    }
    if len(out) != 25:
        raise L.AuditError(f"D03 §11 parses {len(out)} W rows, not 25")
    return out


def g_wdeck(t: L.Tree) -> list[str]:
    _, rows = deck(t)
    bad = [
        f"{s(r, 'id')}: RULED, but no ruling re-words its W row"
        for r in rows
        if r.get("status") == "RULED" and s(r, "ref") not in RULED_W
    ]
    for w, (text, src, status) in w_rows().items():
        mine = [r for r in rows if r.get("ref") == w]
        want, why = RULED_W.get(w, (text, ""))
        if why and want == text:
            bad.append(f"{w}: D03 now carries the {why} string; drop the ruled override")
        if len(mine) != 1:
            bad.append(f"{w}: {len(mine)} deck rows, want 1")
        elif s(mine[0], "text") != want:
            bad.append(f"{w}: the deck's string differs from {why or 'D03'}'s")
        elif (mine[0].get("status") == "RULED") != bool(why):
            bad.append(f"{w}: a ruled override, and only one, has the status RULED")
        m = D02_CITE.search(src)
        if status == "verbatim" and m is not None:
            lo = int(m.group(1))
            if not whole_span(span("D02", lo, int(m.group(2) or lo)), text):
                bad.append(f"{w}: D03 cites {m.group(0)}, which does not carry its string")
    return bad


def lr_cells() -> dict[str, str]:
    block = L.section("\n".join(doc_lines("D04")), LR_HEADING)
    out = {r[0]: r[4] for r in L.table_rows(block) if r and r[0].startswith("LR-")}
    if len(out) < 9:
        raise L.AuditError(f"D04 §7.3 parses {len(out)} LR rows")
    return out


def g_lr(t: L.Tree) -> list[str]:
    _, rows = deck(t)
    cells = lr_cells()
    bad = [f"{lr}: no deck row" for lr in LR_ANNOUNCED if not any(r.get("ref") == lr for r in rows)]
    for r in rows:
        ref = s(r, "ref")
        if ref.startswith("LR-") and s(r, "text") not in cells.get(ref, ""):
            bad.append(f"{s(r, 'id')}: not in D04 {ref}'s Text cell")
    block = L.section("\n".join(doc_lines("D04")), LR_HEADING)
    if not all(p in block for p in LR_POLICY):
        raise L.AuditError("D04 §7.3 no longer rules one polite status region")
    for r in rows:
        want = "polite" if r.get("kind") == "announce" else None
        if r.get("live") != want:
            bad.append(f"{s(r, 'id')}: `live` is {r.get('live')!r}, D04 §7.3 rules {want!r}")
    return bad


def g_t2(t: L.Tree) -> list[str]:
    _, rows = deck(t)
    d09 = "\n".join(doc_lines("D09"))
    keys, verbs = L.d09_keys(d09), set(L.d09_verbs(d09).values())
    if not keys or not verbs:
        raise L.AuditError("E09-D09 §3.1 or §3.2 parses empty")
    bad: list[str] = []
    for r in rows:
        rid, key, text = s(r, "id"), s(r, "key"), s(r, "text")
        if r.get("kind") != "t2":
            if "key" in r or "narrowed" in r:
                bad.append(f"{rid}: a key or a narrowing on a non-T2 row")
            continue
        why = L.t2_reason_string(text)
        if why:
            bad.append(f"{rid}: {why}")
        if key == "state":
            if r.get("status") != "PROPOSED" or s(r, "owner") not in STATE_OWNERS:
                bad.append(f"{rid}: a state reason is PROPOSED and owned by {STATE_OWNERS}")
            continue
        tpl = T2_TEMPLATES.get(key)
        if tpl is None or keys.get(key) != tpl:
            bad.append(f"{rid}: {key!r} is not an E09-D09 §3.1 key this deck fills")
            continue
        verb = t2_verb(r)
        narrowed = NARROWINGS.get(s(r, "narrowed"), frozenset())
        if not verb or (verb not in verbs and verb not in narrowed):
            bad.append(f"{rid}: {verb!r} is not a §3.2 verb nor narrowed by its authority")
        elif verb in verbs and "narrowed" in r:
            bad.append(f"{rid}: a §3.2 verb carries a narrowing")
    return bad


def g_superseded(t: L.Tree) -> list[str]:
    _, rows = deck(t)
    backlog = "\n".join(doc_lines("E18J"))
    bad = [f"the E18 backlog no longer carries {x!r}" for x in SUPERSEDED if x not in backlog]
    texts = {s(r, "text") for r in rows}
    bad += [f"the deck carries the settled-away {x!r}" for x in SUPERSEDED if x in texts]
    ids = {s(r, "id") for r in rows}
    return bad + [f"{x}: the replacing row is missing" for x in REPLACEMENTS if x not in ids]


TEXTS = {"deck": ("deck", "tool"), "full": ("deck", "tool", "pack", "handoff", "pins")}


def g_hygiene(t: L.Tree) -> list[str]:
    named = t.named(*TEXTS[t.text("stage")])
    bad = L.closing_keywords(named) + L.whitespace_hygiene(named) + L.scan_public(named)
    bad += L.comment_findings(named)
    texts = [(lb, x) for lb, x in named if lb != "tool"]
    return bad + [f"{lb}: {m.group(0)}" for lb, x in texts for m in PLACEHOLDER.finditer(x)]


def g_scope(t: L.Tree) -> list[str]:
    own = STAGES[t.text("stage")]
    absent = [rel for rel in own if rel not in t.files.get("present", "").split("\n")]
    return [f"{rel} is missing" for rel in absent] + L.untouched(t.changed, own)


# ---------- the full stage: the pack and the hand-off ---------------------------------------------
RULING_LINE = "## The questions BQ-0 … BQ-9 — RULED (comment 6652596258, on the BQ list 6649830901)"
LIST_ID = "6649830901"
_RIDER = "AGREE +rider"
VERDICTS = (_RIDER, _RIDER, "AGREE", _RIDER, "AGREE", _RIDER, _RIDER, "AMEND", _RIDER, _RIDER)
PINS_HEADER = "# E18-D05 ruled pins: a hash per BQ bullet. Written by --repin-ruled only."
APPLIES = ("instant", "re-snapshot", "rebuild", "—")
RATIO_RANGE = (f"1.5{EN}20", f"150{EN}2000 %")  # `22`:4889's minimum and maximum, and as percent
TICK = re.compile(r"`([a-z][\w:]*)`")  # a field, parameter or option name
EVIDENCE = (19, 20)  # E06R: the evidence rule the pack quotes
PROVENANCE = ("E06-frozen", "planning", "SYNTHETIC")
K01 = "E18-K01 #583"
CHECKLISTS = {  # `14` line -> (the label the line starts with, map rows, the map's label)
    747: ("- **Sign-off:**", None, "SCR-030 Sign-off"),
    751: ("- **Design sign-off acceptance checklist:**", None, "SCR-030 checklist"),
    853: ("- **Design sign-off acceptance checklist:**", None, "SCR-032 checklist"),
    1116: ("- **Design sign-off acceptance checklist:**", 1, "SCR-045 checklist"),
    1387: ("- **Design sign-off acceptance checklist:**", None, "SCR-056 checklist"),
}
BLOCKS = ("CMP-197", "CMP-046", "CMP-227")  # the contracts no parent checklists (BQ-8)
LINKED = {  # a §G link -> the component whose block heads that line
    ("D03H", 55): "CMP-109",
    ("D03H", 117): "CMP-132",
    ("D03H", 146): "CMP-182",
    ("D03H", 174): "CMP-228",
    ("E25H", 5): "CMP-227",
    ("E25H", 62): "CMP-132",
}
BLOCK_HEAD = re.compile(r"^## Handoff checklist — (CMP-\d{3})", re.MULTILINE)
TEMPLATE_LINE = re.compile(r"^- \[ \] \*\*(.+?)\*\*", re.MULTILINE)
CITE_KEYS = ("D02", "D03", "D04", "D09", "D03H", "D04H", "E24", "E25H", "E06R", "ADR11", "E18J")
_ALTS = "|".join(sorted(CITE_KEYS, key=len, reverse=True))
CITE_RX = re.compile(  # the helper's grammar, a named key optionally backticked as `NN` is
    rf"(?:`(?P<nn>\d\d)`|`?(?<![A-Za-z0-9-])(?P<named>{_ALTS})`?):(?P<first>\d+)"
    rf"(?:{EN}(?P<firstend>\d+))?(?P<more>(?:, :\d+(?:{EN}\d+)?)*)"
)
PINNED_WORDS = (  # load-bearing cites: the words each line must still carry
    L.KeyCite("14", 844, "Enter a ratio between 100 and 2000 %."),
    L.KeyCite("14", 745, "Tauri/WebView2"),
    L.KeyCite("14", 848, "Tauri/WebView2"),
    L.KeyCite("22", 4889, "minimum: 1.5, maximum: 20"),
    L.KeyCite("22", 15641, "recomputeFootprint"),
    L.KeyCite("22", 15644, "price-grouping or imbalance-parameter change"),
    L.KeyCite("22", 15647, "recording:write"),
    L.KeyCite("23", 719, "`price_grouping`"),
    L.KeyCite("23", 721, "`price_grouping` on `footprint`"),
    L.KeyCite("24", 941, "**display-time**"),
    L.KeyCite("26", 286, "194 glyphs"),
    L.KeyCite("ADR11", 3, "Electron"),
    L.KeyCite("E06R", 22, "dropped the Tauri / WebView2 arm"),
    L.KeyCite("E06R", 282, "73 glyphs"),
    L.KeyCite("D02", 621, "rebuild footprint cells"),
    L.KeyCite("D02", 908, "market.footprint_recompute_requested"),
    L.KeyCite("D02", 909, "2,500"),
    L.KeyCite("D03", 380, "W-11"),
    L.KeyCite("D09", 85, "E17-D01 §7"),
    L.KeyCite("D09", 108, '"change recording"'),
    L.KeyCite("16", 577, "### 11.4"),
    L.KeyCite("16", 664, "### 11.5"),
    L.KeyCite("02", 53, "design-ahead"),
)


def text_of(key: str) -> str:
    return "\n".join(doc_lines(key))


def pack_section(t: L.Tree, prefix: str, label: str = "pack") -> str:
    block = L.section(t.text(label), prefix)
    if not block.strip():
        raise L.AuditError(f"{label}: no section {prefix!r}")
    return block


def ticks(cell: str) -> list[str]:
    return TICK.findall(cell)


def config_fields() -> list[str]:
    block = L.section(text_of("24"), "### 4.7 Footprint configuration")
    out = re.findall(r"^    (\w+): ", block, re.MULTILINE)
    if len(out) < 10:
        raise L.AuditError("`24` §4.7 parses too few fields")
    return out


def rest_params() -> set[str]:
    yaml = text_of("22")
    i = yaml.index("\n  /market/footprint:\n")
    j = yaml.index("\n  /", i + 1)
    return set(re.findall(r"- name: (\w+)", yaml[i:j]))


def ws_options() -> tuple[set[str], set[str]]:
    lines = doc_lines("23")
    row = next(ln for ln in lines if ln.startswith("| `footprint.{symbol}"))
    ctl = re.search(r"`(\w+)` on `footprint`", "\n".join(lines))
    return set(ticks(L.cells(row)[1])), {ctl.group(1)} if ctl else set()


def g_ruling(t: L.Tree) -> list[str]:
    pack = t.text("pack")
    bad = L.check_ruling(
        pack,
        heading_line=RULING_LINE,
        list_ref=LIST_ID,
        count=10,
        verdict=lambda n: f"**RULED: {VERDICTS[n]}.**",
    )
    return bad + L.check_hash_pins(pack, t.text("pins"))


def g_map(t: L.Tree) -> list[str]:
    block = pack_section(t, "## 3. ")
    rows = L.table_rows(block)
    fields, params = config_fields(), rest_params()
    opts, ctl = ws_options()
    yaml = text_of("22")
    bad: list[str] = []
    seen: list[str] = []
    for r in rows:
        ctrl, cfg, rest, ws, applies = r[0], r[1], r[2], r[3], r[4]
        seen += [f for f in ticks(cfg) if f in fields]
        bad += [f"{ctrl}: `{f}` is no `24` §4.7 field" for f in ticks(cfg) if f not in fields]
        for p_ in ticks(rest):
            if p_ not in params and not (
                p_ in ("recomputeFootprint", "recording:write") and p_ in yaml
            ):
                bad.append(f"{ctrl}: `{p_}` is no `getFootprint` parameter")
        bad += [
            f"{ctrl}: `{o}` is no `footprint` option"
            for o in ticks(ws)
            if o not in opts | {"ctl", "sub"}
        ]
        if ("a `ctl` key" in ws) != any(o in ctl for o in ticks(ws)):
            bad.append(f"{ctrl}: the `ctl` reading differs from `23`")
        if applies not in APPLIES:
            bad.append(f"{ctrl}: applies as {applies!r}")
        if "price_grouping" in ticks(ws) and applies != "re-snapshot":
            bad.append(f"{ctrl}: a `ctl` key change re-snapshots (`23`:719)")
        if "imbalance_ratio" in ticks(rest) and not all(x in rest for x in RATIO_RANGE):
            bad.append(f"{ctrl}: the ratio row lacks the contract's {RATIO_RANGE}")
    tail = block.split("**Not exposed**", 1)[-1].split("\n\n", 1)[0]
    seen += [f for f in ticks(tail) if f in fields]
    gone = [f for f in fields if seen.count(f) != 1]
    return bad + ([f"§4.7 fields mapped other than once: {gone}"] if gone else [])


def g_spike(t: L.Tree) -> list[str]:
    ev = pack_section(t, "### 4.1")
    m = re.search(r'The evidence rule, quoted: "(.+?)"', ev)
    rule = span("E06R", *EVIDENCE)
    bad = [] if m and whole_span(rule, fold(m.group(1))) else ["§4.1 does not quote E06's rule"]
    rows = L.table_rows(ev)
    if [r[0][:3] for r in rows] != ["(a)", "(b)", "(c)"]:
        bad.append("§4.1 rows are not (a), (b), (c)")
    for r in rows:
        if not r[-1].startswith("PENDING") or "met" in r[-1].split() or "[x]" in r[-1]:
            bad.append(f"{r[0][:3]}: status {r[-1]!r} is not PENDING")
    if rows and not ("ADR-0011" in rows[-1][2] and "C-3" in rows[-1][2]):
        bad.append("(c) does not name ADR-0011 and C-3")
    nums = pack_section(t, "### 4.2")
    if "no figure here is a measurement" not in t.text("pack").split("### 4.2", 1)[-1][:120]:
        bad.append("§4.2's heading lacks the no-measurement sentence")
    tables = L.all_tables(pack_section(t, "## 10. "))
    g_table = next((tb for tb in tables if tb and tb[0][0].startswith("G-")), [])
    g_rows = {r[0]: r[2] for r in g_table}
    for r in L.table_rows(nums):
        if not r[2].startswith(PROVENANCE):
            bad.append(f"{r[0]}: provenance {r[2]!r}")
        if K01 not in g_rows.get(r[3], ""):
            bad.append(f"{r[0]}: {r[3]} is not a G-row owned by {K01}")
    return bad


def g_deckpack(t: L.Tree) -> list[str]:
    _, rows = deck(t)
    m = re.search(
        r"The deck has (\d+) rows: (\d+) merged, (\d+) PROPOSED and (\d+) RULED", t.text("pack")
    )
    bad: list[str] = []
    if m is None:
        return ["§5.1 states no counts"]
    n, mg, pr, ru = (int(x) for x in m.groups())
    if (
        n != len(rows)
        or mg + pr + ru != n
        or pr != sum(r.get("status") == "PROPOSED" for r in rows)
    ):
        bad.append(f"§5.1's counts {m.group(0)!r} are not the deck's")
    ids = {s(r, "id") for r in rows}
    named = set(re.findall(r"`(footprint(?:\.[a-z0-9_]+)+)`", t.text("pack") + t.text("handoff")))
    bad += [f"{x} is named but is no deck row" for x in sorted(named - ids)]
    state = {s(r, "id") for r in rows if r.get("key") == "state" and r.get("frozen") is None}
    listed = set(re.findall(r"`(footprint\.t2\.\w+)`", pack_section(t, "### 5.3")))
    return bad + ([f"§5.3 lists {sorted(listed)}, not {sorted(state)}"] if listed != state else [])


def g_signoff(t: L.Tree) -> list[str]:
    block = pack_section(t, "## 9. ")
    rows = L.table_rows(block)
    bad = ["§9 ticks a box"] if "[x]" in block else []
    for n, (lead, want, label) in CHECKLISTS.items():
        line = docs().line("14", n) or ""
        if not line.startswith(lead):
            bad.append(f"`14`:{n} is no longer {label}'s checklist")
        items = len(re.findall(r"\[[ x]\]", line)) if want is None else want
        got = [r for r in rows if r[0].split(" (")[0] == label]
        if not got or len(got) != items or f"({n})" not in got[0][0]:
            bad.append(f"{label}: {len(got)} map rows, `14`:{n} has {items} items")
        for r in got:
            if not ("PENDING —" in r[2] or r[2].startswith("not E18's") or "not E18's" in r[2]):
                bad.append(f"{label} {r[1]!r}: no closer")
    return bad


def g_handoff(t: L.Tree) -> list[str]:
    ho = t.text("handoff")
    brief = text_of("16")
    names = TEMPLATE_LINE.findall(brief.split("### 11.4", 1)[-1].split("### 11.5", 1)[0])
    if len(names) != 13:
        raise L.AuditError(f"`16` §11.4 parses {len(names)} checklist lines")
    heads = BLOCK_HEAD.findall(ho)
    bad = [] if tuple(heads) == BLOCKS else [f"§G blocks {heads}, not {list(BLOCKS)}"]
    for part in ho.split("\n## Handoff checklist — ")[1:]:
        lines = [ln for ln in part.split("\n") if ln.startswith("- [")]
        got = [re.match(r"- \[[ x]\] \*\*(.+?)\*\*", ln) for ln in lines]
        if [g.group(1) if g else "" for g in got] != names:
            bad.append(f"{part[:7]}: the lines are not `16` §11.4's, in order")
        for ln in lines:
            ok = re.match(r"- \[x\] \*\*.+?\*\* — (?!PENDING|N/A)\S", ln) or re.match(
                r"- \[ \] \*\*.+?\*\* — (PENDING|N/A) — \S", ln
            )
            if not ok:
                bad.append(f"{part[:7]}: {ln[:40]!r} breaks the line rule")
    for (key, n), cmp_ in LINKED.items():
        if f"`{key}`:{n}" not in L.section(ho, "## §G"):
            bad.append(f"§G does not link {key}:{n}")
        if not (docs().line(key, n) or "").startswith(f"## Handoff checklist — {cmp_}"):
            bad.append(f"{key}:{n} is not {cmp_}'s checklist")
    return bad


def g_arow(t: L.Tree) -> list[str]:
    rows = L.table_rows(L.section(t.text("handoff"), "## §C"))
    rx = CITE_RX
    bad: list[str] = []
    for r in rows:
        cites = L.extract_cites(r[1], rx)
        if not cites:
            bad.append(f"{r[0]}: no cite")
            continue
        c = cites[0]
        line = docs().line(c.doc, c.lo) or ""
        if r[2] != "—" and L.unquote(r[2]) not in line:
            bad.append(f"{r[0]}: Old is not on {c.raw}")
        if "a line after" in r[1]:
            nxt = docs().line(c.doc, c.lo + 1) or ""
            pointer = "](../design/"
            if not (line.startswith("- **") and pointer in line) or (
                nxt.startswith("- **") and pointer in nxt
            ):
                bad.append(f"{r[0]}: {c.raw} is not its entry's last pointer line")
    return bad


def g_cite(t: L.Tree) -> list[str]:
    cites = L.extract_cites(t.text("pack") + "\n" + t.text("handoff"), CITE_RX)
    bad = L.check_cites(cites, docs(), nonblank=False, min_count=150)
    ends = [
        c for c in cites if not all((docs().line(c.doc, n) or "").strip() for n in (c.lo, c.hi))
    ]
    bad += [f"{c.raw} (a blank end line)" for c in ends]
    return bad + L.check_key_cites(PINNED_WORDS, docs())


def g_t2std(t: L.Tree) -> list[str]:
    rule = next((ln for ln in t.text("pack").split("\n") if ln.startswith("- **R-2 ")), "")
    return [f"R-2 lacks {m!r}" for m in L.t2_markers(rule)]


def g_walk(t: L.Tree) -> list[str]:
    items = re.findall(r"^\d+\. (.*)$", pack_section(t, "## 13. "), re.MULTILINE)
    bad = [] if 0 < len(items) <= 10 else [f"§13 has {len(items)} items"]
    for r in ("R1 ", "R2 ", "R3 "):
        if sum(i.startswith(r) for i in items) != 1:
            bad.append(f"§13 has not exactly one {r.strip()} item")
    return bad


# fmt: off
DECK_GATES = tuple(L.Gate("G-" + f.__name__[2:].upper().replace("_", "-"), f) for f in (
    g_deck, g_source, g_wdeck, g_lr, g_t2, g_superseded, g_hygiene, g_scope,
))
FULL_GATES = DECK_GATES + tuple(L.Gate("G-" + f.__name__[2:].upper(), f) for f in (
    g_ruling, g_map, g_spike, g_deckpack, g_signoff, g_handoff, g_arow, g_cite, g_t2std, g_walk,
))
GATES = {"deck": DECK_GATES, "full": FULL_GATES}
# fmt: on


# ---------- mutations -----------------------------------------------------------------------------
def deck_edit(rid: str, recount: bool = False, **fields: object) -> Callable[[L.Tree], L.Tree]:
    """A mutation fn: set fields of one deck row (`_DROP` removes the field); `recount` keeps
    the header's counts true, so only the row's own gate sees the change."""

    def fn(t: L.Tree) -> L.Tree:
        lines = t.text("deck").split("\n")
        for i, ln in enumerate(lines[1:], 1):
            if ln.strip() and json.loads(ln).get("id") == rid:
                row = json.loads(ln)
                for k, v in fields.items():
                    if v is _DROP:
                        row.pop(k, None)
                    else:
                        row[k] = v
                lines[i] = json.dumps(row, ensure_ascii=False)
                if recount:
                    head, rows = parse_deck("\n".join(lines))
                    head["counts"] = counts(rows)
                    lines[0] = json.dumps(head, ensure_ascii=False)
                return replace(t, files={**t.files, "deck": "\n".join(lines)})
        raise L.AuditError(f"no deck row {rid}")

    return fn


_DROP = object()
_M = L.Mutation
_U = "http" + "s://example.org"
_KW = "Clo" + "ses #" + "499"
# fmt: off
DECK_MUTATIONS: tuple[L.Mutation, ...] = (
    _M("M-1", "G-DECK", "blank a row's owner", fn=deck_edit("footprint.legend.row", owner="")),
    _M("M-2", "G-DECK", "the header miscounts the rows", "deck", '"rows": 143', '"rows": 142'),
    _M("M-3", "G-DECK", "a field outside the closed set",
       fn=deck_edit("footprint.settings.poc", note="x")),
    _M("M-4", "G-DECK", "a status outside the header's",
       fn=deck_edit("footprint.settings.poc", status="DRAFT")),
    _M("M-5", "G-SOURCE", "a merged string reworded off its line",
       fn=deck_edit("footprint.legend.bands", text="strong ≥ 60 · medium ≥ 20 · weak ≥ 5 BTC")),
    _M("M-6", "G-SOURCE", "a row re-pointed at the next line",
       fn=deck_edit("footprint.settings.stack", source="D02:517")),
    _M("M-7", "G-SOURCE", "a cut word passes as the string",
       fn=deck_edit("footprint.mode.bid_ask", text="Bid \u00d7 As")),
    _M("M-8", "G-WDECK", "W-5 loses its deck row",
       fn=deck_edit("footprint.canvas.stack_short.tested", ref=None)),
    _M("M-9", "G-LR", "LR-4 loses its deck row",
       fn=deck_edit("footprint.live.new_stack", ref=None)),
    _M("M-18", "G-LR", "an announcement turned assertive",
       fn=deck_edit("footprint.scr056.located", live="assertive")),
    _M("M-19", "G-LR", "a caption given a live politeness",
       fn=deck_edit("footprint.board.synthetic", live="polite")),
    _M("M-10", "G-T2", "a permission reason under the account key",
       fn=deck_edit("footprint.t2.save", key="rbac.account")),
    _M("M-11", "G-T2", "a narrowed verb without its authority",
       fn=deck_edit("footprint.t2.start_recording", narrowed=_DROP)),
    _M("M-20", "G-T2", "the A-29 verb restored (BQ-7)",
       fn=deck_edit("footprint.t2.rebuild_permission", source="D02:621", narrowed="A-29",
                    text="Your role can't rebuild footprint cells.")),
    _M("M-21", "G-WDECK", "the ruled W-11 row detached from W-11",
       fn=deck_edit("footprint.t2.rebuild_owner_only", ref=None)),
    _M("M-22", "G-SOURCE", "a composed reason off its verb-table line",
       fn=deck_edit("footprint.t2.rebuild_permission", source="D09:107")),
    _M("M-12", "G-T2", "a state reason owned outside its vocabulary",
       fn=deck_edit("footprint.t2.no_imbalance", owner="E18-D02")),
    _M("M-13", "G-SUPERSEDED", "the 150 % ratio row renamed away",
       fn=deck_edit("footprint.valid.ratio", id="footprint.valid.ratio_pct")),
    _M("M-14", "G-HYGIENE", "a closing keyword in a row",
       fn=deck_edit("footprint.settings.cell_type", where=_KW)),
    _M("M-15", "G-HYGIENE", "a URL in a row", fn=deck_edit("footprint.settings.display", where=_U)),
    _M("M-16", "G-HYGIENE", "a placeholder in a row",
       fn=deck_edit("footprint.settings.rows", where="T" + "BD")),
    _M("M-17", "G-SCOPE", "an owner document edited", "@changed", "",
       "docs/plan/14-screens-catalogue.md"),
    _M("M-23", "G-WDECK", "the W-11 override marked merged",
       fn=deck_edit("footprint.t2.rebuild_owner_only", recount=True, status="merged")),
)


def drop_present(rel: str) -> Callable[[L.Tree], L.Tree]:
    def fn(t: L.Tree) -> L.Tree:
        kept = [x for x in t.text("present").split("\n") if x != rel]
        return replace(t, files={**t.files, "present": "\n".join(kept)})

    return fn


MUTATIONS: tuple[L.Mutation, ...] = (
    *DECK_MUTATIONS,
    _M("M-24", "G-RULING", "BQ-7's AMEND read as AGREE", "pack",
       "**RULED: AMEND.**", "**RULED: AGREE.**"),
    _M("M-25", "G-RULING", "a pin row altered", "pins", r"(?m)^BQ-3 [0-9a-f]+",
       "BQ-3 " + "0" * 16, regex=True),
    _M("M-26", "G-MAP", "Rows read as instant", "pack",
       r"(a `ctl` key \(`23`:721\)\s*\|\s*)re-snapshot", r"\1instant", regex=True),
    _M("M-27", "G-MAP", "the ratio row loses the contract's range", "pack",
       f"`imbalance_ratio` 1.5{EN}20, so", f"`imbalance_ratio` 1{EN}20, so"),
    _M("M-28", "G-MAP", "a field name invented", "pack",
       "`noise_filter_volume` (`24`:962)", "`noise_filter` (`24`:962)"),
    _M("M-29", "G-SPIKE", "criterion (a) claimed met", "pack",
       r"\| PENDING — owner or K01 +\|", "| met |", regex=True),
    _M("M-30", "G-SPIKE", "a planning number labelled measured", "pack",
       "| planning (GAP-14)", "| measured (GAP-14)"),
    _M("M-31", "G-DECKPACK", "the pack miscounts the deck", "pack",
       "The deck has 143 rows", "The deck has 142 rows"),
    _M("M-32", "G-DECKPACK", "a deck id the deck lacks", "pack",
       "`footprint.strip.first_recorded`", "`footprint.strip.first_record`"),
    _M("M-33", "G-SIGNOFF", "a sign-off box ticked by the pack", "pack",
       "| PENDING — D03 PR 2; legibility measured by K01", "| [x] D03 PR 2; legibility"),
    _M("M-34", "G-HANDOFF", "a PENDING line without its marker", "handoff",
       "- [ ] **Tokens used** — PENDING — D03", "- [ ] **Tokens used** — D03"),
    _M("M-35", "G-HANDOFF", "a second CMP-132 checklist", "handoff",
       "## Handoff checklist — CMP-197 ChartTooltip", "## Handoff checklist — CMP-132 Imbalance"),
    _M("M-36", "G-AROW", "an Old text off its line", "handoff",
       '"Enter a ratio between 100 and 2000 %."', '"Enter a ratio between 120 and 2000 %."'),
    _M("M-37", "G-AROW", "a pointer row on a middle pointer line", "handoff",
       "`14`:790, a line after", "`14`:789, a line after"),
    _M("M-38", "G-CITE", "a cite out of range", "pack",
       "(`26`:286), the set of record", "(`26`:9286), the set of record"),
    _M("M-39", "G-T2STD", "R-2 loses aria-disabled", "pack",
       'G-T2.1b `aria-disabled="true"`, never', "G-T2.1b never"),
    _M("M-40", "G-WALK", "an eleventh walkthrough item", "pack",
       "10. The three", "10. One more.\n11. The three"),
    _M("M-41", "G-HYGIENE", "a placeholder in the pack", "pack",
       "**Status:** Draft v0.1.", "**Status:** Draft v0.1, T" + "BD."),
    _M("M-42", "G-SCOPE", "the pins file missing", fn=drop_present(PINS_REL)),
    _M("M-43", "G-HANDOFF", "an N/A line ticked", "handoff",
       "- [ ] **Motion pair** — N/A — none", "- [x] **Motion pair** — N/A — none"),
)
# fmt: on


# ---------- modes ---------------------------------------------------------------------------------
LABELS = {"deck": DECK_REL, "tool": TOOL_REL, "pack": PACK_REL, "handoff": HANDOFF_REL}
LABELS["pins"] = PINS_REL


def read_tree(stage: str) -> L.Tree:
    files = {"stage": stage}
    present = [rel for rel in STAGES[stage] if (ROOT / rel).exists()]
    files["present"] = "\n".join(present)
    for label, rel in LABELS.items():
        path = ROOT / rel
        files[label] = path.read_text(encoding="utf-8") if path.exists() else ""
    base = repo().diff_base(BASE)
    return L.Tree(files=files, changed=repo().changed_paths(base))


def repin_ruled(stage: str) -> int:
    """The only pin writer: one hashed row per ruled BQ bullet of the pack."""
    pack = ROOT / PACK_REL
    if stage != "full" or not pack.exists():
        print("--repin-ruled needs --stage full and the pack", file=sys.stderr)
        return 2
    rows = L.bq_hash_pins(pack.read_text(encoding="utf-8"))
    L.write_pins(ROOT / PINS_REL, "\n".join([PINS_HEADER, *rows]))
    print(f"wrote {len(rows)} pins")
    return 0


def main(argv: list[str]) -> int:
    args = list(argv)
    if "--stage" not in args or args.index("--stage") + 1 >= len(args):
        print("--stage deck or --stage full is required, with every mode", file=sys.stderr)
        return 2
    i = args.index("--stage")
    stage = args.pop(i + 1)
    args.pop(i)
    if stage not in STAGES:
        print(f"--stage {stage} is refused: the stages are {sorted(STAGES)}", file=sys.stderr)
        return 2
    disk = [ROOT / rel for rel in STAGES[stage]]
    muts = MUTATIONS if stage == "full" else DECK_MUTATIONS
    modes = {
        "check": lambda: L.report(L.run_gates(GATES[stage], read_tree(stage))),
        "self-test": lambda: L.self_test(
            read_tree(stage), GATES[stage], muts, disk, namespace=globals()
        ),
        "repin-ruled": lambda: repin_ruled(stage),
    }
    return L.cli(args, modes, __doc__)


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
