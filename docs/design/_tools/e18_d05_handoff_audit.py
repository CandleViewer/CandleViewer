#!/usr/bin/env python3
"""E18-D05 (#499) audit: the E18 footprint hand-off pack (SCR-030, SCR-032, SCR-056).

Offline and default-deny. The shared gates (git, cites, G-T2 vocabulary, closing keywords,
hygiene, public text, G-UNTOUCHED, the runner and the mutation harness) live in
`spec_audit_lib.py`, imported from `main` beside this file, never copied; this file keeps only
E18-D05's rows. It reads, AS TEXT at a pinned commit, E18-D02, E18-D04, E09-D09 and the E18
backlog at the base, and E18-D03 at PR #5881's head (cited "if it merges as is"); from the
working tree, the copy deck and itself. It runs no repo code.

Stages, named by `--stage` (required; never guessed from the working tree). This is slice 1a's
tool: the `deck` stage gates the copy deck and this tool alone. Slice 1b, stacked on it, adds the
pack, the hand-off and the pins file, and with them the `full` stage and its gates (the mapping
table against `24` §4.7, the spike rows' PENDING state, the §G line rule, the cite pins, deck to
pack strings); until then `--stage full` is refused.

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
               re-words (RULED_W: W-11 by BQ-7), whose row carries the ruled string while D03
               still carries its own (a ruled override goes stale once D03 takes it); each
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
               host, lane or persona name, HTML comment or placeholder word in the deck or this
               tool's text.
  G-SCOPE      the diff against `git merge-base HEAD origin/main` touches only the stage's
               files.

Usage (from the repo root):
  python3 -I docs/design/_tools/e18_d05_handoff_audit.py --stage deck --check
  python3 -I docs/design/_tools/e18_d05_handoff_audit.py --stage deck --self-test
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

DECK_REL = "docs/design/E18/E18-D05-copy-deck.jsonl"
TOOL_REL = "docs/design/_tools/e18_d05_handoff_audit.py"
STAGES = {"deck": (DECK_REL, TOOL_REL)}  # slice 1b adds "full" with the pack, hand-off and pins

KEYED = {
    "D02": L.DocRef("docs/design/E18/E18-D02.md", BASE),
    "D03": L.DocRef("docs/design/E18/E18-D03.md", D03_HEAD),
    "D04": L.DocRef("docs/design/E18/E18-D04.md", BASE),
    "D09": L.DocRef("docs/design/E09/E09-D09.md", BASE),
    "E18J": L.DocRef("docs/plan/backlog/E18.json", BASE),
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
    "statuses": ["merged", "PROPOSED"],
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
STATUSES = ("merged", "PROPOSED")
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
    bad: list[str] = []
    for w, (text, src, status) in w_rows().items():
        mine = [r for r in rows if r.get("ref") == w]
        want, why = RULED_W.get(w, (text, ""))
        if why and want == text:
            bad.append(f"{w}: D03 now carries the {why} string; drop the ruled override")
        if len(mine) != 1:
            bad.append(f"{w}: {len(mine)} deck rows, want 1")
        elif s(mine[0], "text") != want:
            bad.append(f"{w}: the deck's string differs from {why or 'D03'}'s")
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


def g_hygiene(t: L.Tree) -> list[str]:
    named = t.named("deck", "tool")
    bad = L.closing_keywords(named) + L.whitespace_hygiene(named) + L.scan_public(named)
    bad += L.comment_findings(named)
    return bad + [f"deck: {m.group(0)}" for m in PLACEHOLDER.finditer(t.text("deck"))]


def g_scope(t: L.Tree) -> list[str]:
    own = STAGES[t.text("stage")]
    absent = [rel for rel in own if rel not in t.files.get("present", "").split("\n")]
    return [f"{rel} is missing" for rel in absent] + L.untouched(t.changed, own)


# fmt: off
GATES = tuple(L.Gate("G-" + f.__name__[2:].upper().replace("_", "-"), f) for f in (
    g_deck, g_source, g_wdeck, g_lr, g_t2, g_superseded, g_hygiene, g_scope,
))
# fmt: on


# ---------- mutations -----------------------------------------------------------------------------
def deck_edit(rid: str, **fields: object) -> Callable[[L.Tree], L.Tree]:
    """A mutation fn: set fields of one deck row (`_DROP` removes the field)."""

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
                return replace(t, files={**t.files, "deck": "\n".join(lines)})
        raise L.AuditError(f"no deck row {rid}")

    return fn


_DROP = object()
_M = L.Mutation
_U = "http" + "s://example.org"
_KW = "Clo" + "ses #" + "499"
# fmt: off
MUTATIONS: tuple[L.Mutation, ...] = (
    _M("M-1", "G-DECK", "blank a row's owner", fn=deck_edit("footprint.legend.row", owner="")),
    _M("M-2", "G-DECK", "the header miscounts the rows", "deck", '"rows": 143', '"rows": 142'),
    _M("M-3", "G-DECK", "a field outside the closed set",
       fn=deck_edit("footprint.settings.poc", note="x")),
    _M("M-4", "G-DECK", "a status outside the header's",
       fn=deck_edit("footprint.valid.window", status="RULED")),
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
)
# fmt: on


# ---------- modes ---------------------------------------------------------------------------------
def read_tree(stage: str) -> L.Tree:
    files = {"stage": stage}
    present = [rel for rel in STAGES[stage] if (ROOT / rel).exists()]
    files["present"] = "\n".join(present)
    for label, rel in (("deck", DECK_REL), ("tool", TOOL_REL)):
        path = ROOT / rel
        files[label] = path.read_text(encoding="utf-8") if path.exists() else ""
    base = repo().diff_base(BASE)
    return L.Tree(files=files, changed=repo().changed_paths(base))


def main(argv: list[str]) -> int:
    args = list(argv)
    if "--stage" not in args or args.index("--stage") + 1 >= len(args):
        print("--stage deck is required (slice 1b adds full)", file=sys.stderr)
        return 2
    i = args.index("--stage")
    stage = args.pop(i + 1)
    args.pop(i)
    if stage not in STAGES:
        print(f"--stage {stage} is refused: this slice has only {sorted(STAGES)}", file=sys.stderr)
        return 2
    disk = [ROOT / rel for rel in STAGES[stage]]
    modes = {
        "check": lambda: L.report(L.run_gates(GATES, read_tree(stage))),
        "self-test": lambda: L.self_test(
            read_tree(stage), GATES, MUTATIONS, disk, namespace=globals()
        ),
    }
    return L.cli(args, modes, __doc__)


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
