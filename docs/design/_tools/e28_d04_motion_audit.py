"""E28-D04 (#840) audit: the choreography table, the quotes, the still list, focus, cites, boards.

Stdlib only, offline (`python3 -I -B`). It reads the spec and the pins file from the working tree,
and every cited file and the token JSON AS TEXT at the pinned base with `git show`. Ten gates, each
FAIL led by its code, at most one G1 FAIL per table row:

- [G1-TABLE] section 2 holds M-1 to M-12 in order, every cell filled, no Carrier or reduce cell a
  dash; each row's Recipe is the proposed one (PROPOSED_RECIPE: its E05-D03 row ids and whether it
  is a cut), the ids exist in E05-D03 section 2 at the base; the preview rows are bare cuts; a cut's
  timing cell is the instant triple and its reduce cell "identical (a cut)"; a recipe's timing and
  reduce cells name its rows; every Status cell is "PROPOSED (BQ-nn)" with a BQ of section 1.
- [G2-TOKEN] every dotted name in backticks exists in the token JSON at the base; no easing and no
  duration other than `motion.duration.instant` is restated in the table (E05-D03 is the one
  definition); every Stagger cell is `motion.duration.instant` (nothing staggers).
- [G3-QUOTES] Q-1 to Q-7 of section 3 stand byte for byte in the ticket body, which is
  `E28.json`:444 at the base.
- [G4-STILL] NA-1 to NA-11 stand in order with their pinned sentences, and MS-1 with its own.
- [G5-FOCUS] section 5's FR-1 to FR-12 in order, each naming its M-rows; every M-row has a rule;
  each rule says "focus" and holds no aspiration wording (testable statements only).
- [G6-CITE] every `KEY`:line cite resolves to a declared key and a range in the file at the base;
  each word-pinned cite still carries its words; the pins file holds exactly the cited endpoints,
  each with the hash of its line at the base (`--repin-ruled` is its only writer).
- [G7-REQUEST] section 8 holds R1 to R7; R6 names E28-D03, #839, #5463 merged as 0af333fa0 and the
  boards PR #5482 PENDING at its head; E28-D03 is cited by the `D03` key only (never `E28-D03`:n),
  every block that names #5482 says PENDING, and no "if ... merges" pre-stage wording is left.
- [G8-HYGIENE] no local path, host, closing keyword or word on the lane's public-text list in the
  spec, the pins file or this tool; no own file name carries a reserved word.
- [G9-BOARDS] section 7: four dark boards, names and exports in the pattern, every one drawn;
  section 7.1 records each board's PNG (its file name, the IHDR size and the sha256 of the file in
  the working tree), and section 7.2 embeds each PNG once, in order, every embed pinned to one
  commit whose blob at that path has the same sha256.
- [G10-RULED] the BQ rulings (comment 6601762417): section 1 names the ruling and BQ-01 to BQ-14;
  section 3's MS-2 is the joint stale-preview sentence (JOINT) verbatim, the same in #840, #841 and
  #842; no `opacity.muted` anywhere; FR-5 and FR-12 cite E47-D04's removed-row move
  (`E47-D04`:285); section 6.1 holds A-1 to A-4, and each of A-1 to A-3 has its Old once on its
  target line at the base.

`--json` prints the numbers and findings; `--check` exits 1 on any FAIL (0 FAIL is the bar);
`--self-test` applies one mutation per gate (MUTATIONS) and the probes (PROBES) to an in-memory
copy and passes only when each adds exactly one new FAIL with its gate's code, a re-run on the
unmutated text reproduces the base result and no file on disk changed.

Usage: python3 -I -B docs/design/_tools/e28_d04_motion_audit.py
       [--check] [--json] [--self-test] [--repin-ruled]
"""

from __future__ import annotations

import argparse
import codecs
import hashlib
import json
import re
import subprocess
import sys
from collections.abc import Callable
from pathlib import Path
from typing import Any, NamedTuple

ROOT = Path(__file__).resolve().parents[3]
SPEC_REL = "docs/design/E28/E28-D04.md"
PINS_REL = "docs/design/_tools/e28_d04_ruled_pins.txt"
SPEC = ROOT / SPEC_REL
PINS = ROOT / PINS_REL
BASE = "a7d659a5be"  # main when the rulings were folded; every cite is read here
TICKET = "E28-D04"
KEYS = {
    "05": "docs/plan/05-accessibility-standard.md",
    "14": "docs/plan/14-screens-catalogue.md",
    "16": "docs/plan/16-design-system-brief.md",
    "23": "docs/plan/23-ws-protocol.md",
    "D02": "docs/design/E28/E28-D02.md",
    "E05-D03": "docs/design/E05/E05-D03.md",
    "E42-D04": "docs/design/E42/E42-D04.md",
    "E28.json": "docs/plan/backlog/E28.json",
    "15": "docs/plan/15-component-catalogue.md",
    "D03": "docs/design/E28/E28-D03.md",
    "E47-D04": "docs/design/E47/E47-D04.md",
    "E09-D06": "docs/design/E09/E09-D06.md",
    "E17-D01": "docs/design/E17/E17-D01.md",
    "DS": ".claude/rules/32-design-specs.md",
}
TOKEN_FILES = (
    "packages/ui/tokens/primitives.tokens.json",
    "packages/ui/tokens/semantic-dark.tokens.json",
)
# key|line|words that must stand on that line at the base (the load-bearing cites)
CITE_PINS = """\
05|100|Focus is never silently stolen;05|252|No content flashes more than 3 times per second
14|1507|preview ≤300 ms;14|1522|coalesced to 5 Hz;14|2782|Saving revalidates
14|2808|renders in <=600 ms;16|204|Per-property table, rules and override
16|213|never on a non-live value;16|218|Respects `prefers-reduced-motion`
16|250|a code dialog replacing a rung dialog;16|252|row expansion, disclosures
16|255|skeleton (CMP-015);16|256|busy (CMP-001 `loading`);23|862|`trade_groups`
D02|154|"Stale preview";D02|160|D18;D02|167|state unknown for {account}
D02|303|second-pass refusal;D02|306|412 version_conflict
D02|370|sub_002: version conflict, reload
D02|389|Expanding a row shows a nested members table;D02|432|focus moves to the summary
D02|438|Stale preview (D12);D02|558|Dialogs;D02|561|Live regions
E05-D03|67|Dialog open / close;E05-D03|74|Loading shimmer;E05-D03|75|Busy spinner
E05-D03|93|A mode flip mid-transition;E05-D03|118|MR-3
E42-D04|759|No cross-fade between allowed and denied
E28.json|444|E28's surfaces change under the user's hands
D03|89|No per-cell shadow, gradient or animation;D03|348|The same muting
E47-D04|285|else the grid's empty-state stop;E47-D04|302|the first credential field
E09-D06|67|focus starts on the **password** field;E17-D01|146|"Stale 7s"
05|141|colour is always a _reinforcing_ channel;05|159|body text and labels ≥4.5:1
DS|36|G-T2.1d;DS|59|G-T2.6;15|191|motion-reduce: no rotation
15|199|static (the two-tone fill"""
NA_TEXT = {
    "NA-1": "Preview numbers never tween.",
    "NA-2": "The worked example never tweens.",
    "NA-3": "Status text swaps without a transition.",
    "NA-4": "Virtualised rows do not animate on scroll.",
    "NA-5": "The readiness segments never move.",
    "NA-6": "No cross-fade between states.",
    "NA-7": "Heights and widths never animate.",
    "NA-8": "The meter never tweens.",
    "NA-9": "Safety and environment marks never animate.",
    "NA-10": "Focus never animates.",
    "NA-11": "A held grid never shows a skeleton.",
}
MS_TEXT = "**MS-1. Motion is never the sole carrier of a dangerous state.**"
QUOTE_IDS = tuple(f"Q-{i}" for i in range(1, 8))
ROWS = tuple(f"M-{i}" for i in range(1, 13))
PREVIEW_ROWS = ("M-4", "M-5")
FOCUS_RULES = 12
REQUESTS = tuple(f"R{i}" for i in range(1, 8))
R6_WORDS = ("E28-D03", "#839", "#5463", "0af333fa0", "#5482", "PENDING", "3b23ab11a")
RULING = "6601762417"
JOINT = (
    "**Stale preview (joint ruling: #840 BQ-04, #841 BQ-10, #842 BQ-15).** The stale table's text "
    'keeps `color.text.secondary` at full opacity, and the table carries the visible word "Stale" '
    "with the preview's age (`E17-D01`:146; dimming alone was misread, `E17-D01`:88); the muted "
    "treatment applies to decoration only, never to a word, number or glyph. No state rests on hue "
    "or opacity alone (`05`:141), every word keeps 4.5:1 (`05`:159), and focus moves only on a "
    "press (`05`:100). The a11y floor wins over the token choice; the A-row is #840's A-1 to "
    "E28-D03 §8, cross-referenced to #5550."
)
AROWS = ("A-1", "A-2", "A-3", "A-4")
FOCUS_OWNER = "`E47-D04`:285"
ORDER = "else the previous, else the"
ASPIRATION = (
    "should",
    "ideally",
    "where possible",
    "if possible",
    "as appropriate",
    "try to",
    "aim to",
    "sensible",
)
CUT_TIMING = "`motion.duration.instant` · `—`"
INSTANT = "`motion.duration.instant`"
BANNED_ROT13 = (
    "yrnx rkcbfrq olcnff rkcybvg nggnpx benpyr erirny haobhaqrq sybbq fgnyy QbF nqivfbel TUFN "
    "cer-nhgu"
)
BANNED = codecs.decode(BANNED_ROT13, "rot13").split()
RESERVED_IN_NAMES = codecs.decode("xrl xrlobneq xrlznc gbxra", "rot13").split()
BOARDS = 4
DASHES = {"—", "-", "–", "n/a", "N/A"}
# M-row -> (its E05-D03 section 2 row ids, whether it is a cut), as the BQ defaults propose
PROPOSED_RECIPE: dict[str, tuple[frozenset[str], bool]] = {
    "M-1": (frozenset({"7"}), True),
    "M-2": (frozenset({"2a"}), False),
    **{f"M-{i}": (frozenset(), True) for i in (3, 4, 5, 6, 7, 8, 9, 10, 12)},
    "M-11": (frozenset({"6"}), False),
}
# local roots, assembled so that this file itself names none of them
LOCAL_PATH = "|".join(
    re.escape(p) for p in ("/" + "home/", "/" + "tmp/", "/" + "mnt/", "no" + "tes/")
)
LOCAL_PATH += r"|[A-Z]:\\"
EMBED = re.compile(
    r"https://raw\.githubusercontent\.com/CandleViewer/CandleViewer/([0-9a-f]{40})/"
    r"(docs/design/E28/img/E28-D04-\d\d-[a-z0-9-]+\.png)"
)
HOST = re.compile(
    r"\b[a-z0-9-]+(?:\.[a-z0-9-]+)*\.(?:com|net|org|io|dev|app|cloud)\b", re.IGNORECASE
)


def git_show(rev: str, rel: str) -> str:
    out = subprocess.run(
        ["git", "-C", str(ROOT), "show", f"{rev}:{rel}"], capture_output=True, check=False
    )
    return out.stdout.decode("utf-8") if out.returncode == 0 else ""


def git_blob(rev: str, rel: str) -> bytes | None:
    out = subprocess.run(
        ["git", "-C", str(ROOT), "show", f"{rev}:{rel}"], capture_output=True, check=False
    )
    return out.stdout if out.returncode == 0 else None


def png_facts(data: bytes | None) -> tuple[str, str] | None:
    """(the IHDR size "W × H", the sha256) of a PNG, or None when it is not one."""
    if not data or data[:8] != b"\x89PNG\r\n\x1a\n" or data[12:16] != b"IHDR":
        return None
    w, h = int.from_bytes(data[16:20], "big"), int.from_bytes(data[20:24], "big")
    return f"{w} × {h}", hashlib.sha256(data).hexdigest()


def token_names(texts: list[str]) -> set[str]:
    names: set[str] = set()

    def walk(node: dict[str, Any], prefix: str) -> None:
        for k, v in node.items():
            if k.startswith("$") or not isinstance(v, dict):
                continue
            name = f"{prefix}.{k}" if prefix else k
            if "$value" in v:
                names.add(name)
            else:
                walk(v, name)

    for text in texts:
        if text:
            walk(json.loads(text), "")
    return names


class Ctx(NamedTuple):
    """The texts the gates read; the self-test swaps `spec` or `pins` for a mutated copy."""

    spec: str
    pins: str
    tool: str
    base: dict[str, str]
    tokens: frozenset[str]
    pngs: dict[str, bytes]
    blob: Callable[[str, str], bytes | None]


class Result:
    def __init__(self) -> None:
        self.fails: list[str] = []
        self.numbers: dict[str, object] = {}

    def fail(self, code: str, msg: str) -> None:
        self.fails.append(f"[{code}] {msg}")


def load_ctx() -> Ctx:
    base = {k: git_show(BASE, p) for k, p in KEYS.items()}
    tokens = frozenset(token_names([git_show(BASE, p) for p in TOKEN_FILES]))
    pins = PINS.read_text(encoding="utf-8") if PINS.exists() else ""
    tool = Path(__file__).read_text(encoding="utf-8")
    spec = SPEC.read_text(encoding="utf-8")
    pngs = {
        rel: (ROOT / rel).read_bytes()
        for rel in re.findall(r"`(docs/design/E28/img/E28-D04-[^`]+\.png)`", spec)
        if (ROOT / rel).exists()
    }
    return Ctx(spec, pins, tool, base, tokens, pngs, git_blob)


def subsection(spec: str, num: str) -> str:
    """Subsection `### num` of the spec, to the next heading."""
    m = re.search(
        rf"^### {re.escape(num)} [^\n]*\n(.*?)(?=^#{{2,3}} |\Z)", spec, re.MULTILINE | re.DOTALL
    )
    return m.group(1) if m else ""


def section(spec: str, num: int) -> str:
    """Section `num` of the spec: from its `## n.` heading to the next one outside a fence."""
    out: list[str] = []
    fenced = inside = False
    for line in spec.splitlines(keepends=True):
        if line.startswith("```"):
            fenced = not fenced
        if not fenced and re.match(r"## \d+\. ", line):
            inside = line.startswith(f"## {num}. ")
        if inside:
            out.append(line)
    return "".join(out)


def rows(sec: str) -> list[list[str]]:
    out = []
    for line in sec.splitlines():
        if line.startswith("|") and not re.match(r"^\|[\s:|-]+\|$", line):
            out.append([c.strip() for c in line.strip().strip("|").split("|")])
    return out[1:]  # drop the header


COLS = (
    "m",
    "transition",
    "surfaces",
    "trigger",
    "recipe",
    "timing",
    "stagger",
    "reduce",
    "carrier",
    "status",
    "source",
)


def table(spec: str) -> list[dict[str, str]]:
    return [dict(zip(COLS, r, strict=False)) for r in rows(section(spec, 2))]


def e05_rows(ctx: Ctx) -> set[str]:
    return {r[0] for r in rows(section(ctx.base["E05-D03"], 2)) if r}


def recipe_ids(cell: str) -> list[str]:
    ids: list[str] = []
    for m in re.finditer(r"\brows? (\w+(?: and \w+)*)", cell):
        ids += m.group(1).split(" and ")
    return ids


def bq_ids(spec: str) -> set[str]:
    return {r[0] for r in rows(section(spec, 1)) if r and re.fullmatch(r"BQ-\d\d", r[0])}


# --- G1, G2: the table ------------------------------------------------------------------------
def row_problem(row: dict[str, str], known: set[str], bqs: set[str]) -> str:
    if len(row) != len(COLS) or not all(row.get(c) for c in COLS):
        return "a cell is missing or empty"
    if row["carrier"] in DASHES or row["reduce"] in DASHES:
        return "the Carrier or the motion-reduce cell is a dash"
    ids, cut = recipe_ids(row["recipe"]), "a cut" in row["recipe"]
    if row["m"] in PROPOSED_RECIPE and PROPOSED_RECIPE[row["m"]] != (frozenset(ids), cut):
        return f"Recipe {row['recipe']!r} is not the proposed one {PROPOSED_RECIPE[row['m']]}"
    if row["m"] in PREVIEW_ROWS and row["recipe"] != "a cut":
        return "a preview row is not a bare cut (T caps preview motion at the shortest token)"
    if unknown := [i for i in ids if i not in known]:
        return f"E05-D03 has no section 2 row {unknown}"
    if cut and not (
        row["timing"].startswith(CUT_TIMING) and row["reduce"].startswith("identical (a cut)")
    ):
        return "a cut's timing is not the instant triple or its reduce is not 'identical (a cut)'"
    for col in ("timing", "reduce"):
        if sorted(recipe_ids(row[col])) != sorted(ids):
            return f"the {col} cell names rows {recipe_ids(row[col])}, the Recipe {ids}"
    if ids and not re.search(r"'s reduce cells?$", row["reduce"]):
        return "a recipe row's reduce cell does not name that row's reduce cell"
    status = re.fullmatch(r"PROPOSED \((BQ-\d\d)\)", row["status"])
    if not status or status.group(1) not in bqs:
        return f"Status {row['status']!r} is not PROPOSED with a BQ of section 1"
    if not CITE.search(row["source"]):
        return "the Source cell holds no cite"
    return ""


def gate_table(ctx: Ctx, r: Result) -> None:
    rs, known, bqs = table(ctx.spec), e05_rows(ctx), bq_ids(ctx.spec)
    if tuple(x.get("m") for x in rs) != ROWS:
        r.fail("G1-TABLE", f"rows {[x.get('m') for x in rs]}, expected M-1 to M-12 in order")
    for row in rs:
        if problem := row_problem(row, known, bqs):
            r.fail("G1-TABLE", f"{row.get('m')}: {problem}")
    r.numbers["rows"] = len(rs)
    r.numbers["cut_rows"] = sum("a cut" in x.get("recipe", "") for x in rs)
    r.numbers["recipe_rows"] = sorted({i for x in rs for i in recipe_ids(x.get("recipe", ""))})
    r.numbers["bqs"] = len(bqs)


TOKEN = re.compile(r"`([a-z]+(?:\.[a-z0-9_]+)+)`")


def gate_token(ctx: Ctx, r: Result) -> None:
    named = set(TOKEN.findall(ctx.spec))
    if missing := sorted(named - ctx.tokens):
        r.fail("G2-TOKEN", f"token names not in the token JSON at the base: {missing}")
    for row in table(ctx.spec):
        cells = " ".join(v for k, v in row.items() if k not in ("transition", "surfaces"))
        restated = [t for t in TOKEN.findall(cells) if t.startswith("motion.")]
        if row.get("stagger") != INSTANT or set(restated) - {"motion.duration.instant"}:
            r.fail("G2-TOKEN", f"{row.get('m')}: a stagger or a restated recipe token")
    r.numbers["tokens_named"] = sorted(named)


# --- G3: the quotes ---------------------------------------------------------------------------
QUOTE = re.compile(r'^- (Q-\d) \([^)]*\): "(.+)"$', re.MULTILINE)


def ticket_body(ctx: Ctx) -> str:
    """The ticket's body, and only when line 444 of E28.json at the base is that body's line."""
    text = ctx.base["E28.json"]
    try:
        body = next(t["body"] for t in json.loads(text) if t.get("key") == TICKET)
    except (ValueError, StopIteration, TypeError, KeyError):
        return ""
    lines = text.splitlines()
    on_line = len(lines) >= 444 and json.dumps(body, ensure_ascii=False) in lines[443]
    return str(body) if on_line else ""


def gate_quotes(ctx: Ctx, r: Result) -> None:
    body = ticket_body(ctx)
    if not body:
        r.fail("G3-QUOTES", f"`E28.json`:444 at {BASE} is not the {TICKET} body")
    found = QUOTE.findall(section(ctx.spec, 3))
    if tuple(q for q, _ in found) != QUOTE_IDS:
        r.fail("G3-QUOTES", f"quotes {[q for q, _ in found]}, expected {list(QUOTE_IDS)}")
    for qid, text in found:
        if body and text not in body:
            r.fail("G3-QUOTES", f"{qid} is not byte for byte in `E28.json`:444 at {BASE}")
    r.numbers["quotes"] = len(found)


# --- G4: the still list -----------------------------------------------------------------------
def gate_still(ctx: Ctx, r: Result) -> None:
    sec3 = section(ctx.spec, 3)
    order = re.findall(r"^- \*\*(NA-\d+)\. ", sec3, re.MULTILINE)
    if order != list(NA_TEXT):
        r.fail("G4-STILL", f"the list holds {order}, expected NA-1 to NA-11 in order")
    for na, text in NA_TEXT.items():
        if f"**{na}. {text}**" not in sec3:
            r.fail("G4-STILL", f"{na}'s pinned sentence is not in section 3")
    if MS_TEXT not in sec3:
        r.fail("G4-STILL", "MS-1's pinned sentence is not in section 3")
    r.numbers["still"] = len(order)


# --- G5: focus --------------------------------------------------------------------------------
FR = re.compile(r"^- \*\*FR-(\d+) \(([^)]*)\)\.\*\* (.+?)(?=^- |\n\n|\Z)", re.MULTILINE | re.DOTALL)


def gate_focus(ctx: Ctx, r: Result) -> None:
    found = FR.findall(section(ctx.spec, 5))
    if [int(n) for n, _, _ in found] != list(range(1, FOCUS_RULES + 1)):
        r.fail("G5-FOCUS", f"rules FR-{[n for n, _, _ in found]}, expected FR-1 to FR-12")
    covered: set[str] = set()
    for n, tags, text in found:
        ms = re.findall(r"M-\d+", tags)
        covered |= set(ms)
        words = " ".join(text.split()).lower()
        if not ms or set(ms) - set(ROWS):
            r.fail("G5-FOCUS", f"FR-{n} names {tags!r}, not M-rows of section 2")
        elif "focus" not in words:
            r.fail("G5-FOCUS", f"FR-{n} does not say what focus does")
        elif hit := [w for w in ASPIRATION if re.search(rf"\b{w}\b", words)]:
            r.fail("G5-FOCUS", f"FR-{n} is an aspiration, not a testable statement: {hit}")
    if missing := [m for m in ROWS if m not in covered]:
        r.fail("G5-FOCUS", f"no focus rule for {missing}")
    r.numbers["focus_rules"] = len(found)


# --- G6: cites and the pins file --------------------------------------------------------------
CITE = re.compile(r"`([A-Za-z0-9.-]+)`((?::\d+(?:-\d+)?)(?:, :\d+(?:-\d+)?)*)")


def norm(s: str) -> str:
    return re.sub(r"\s+", " ", s.replace("`", "").replace("*", "")).strip()


def line_hash(s: str) -> str:
    return hashlib.sha1(norm(s).encode("utf-8")).hexdigest()[:16]


def cites(spec: str) -> list[tuple[str, int, int]]:
    out: list[tuple[str, int, int]] = []
    body = re.sub(r"```.*?```", "", spec, flags=re.DOTALL)
    for key, spans in CITE.findall(body):
        for a, b in re.findall(r":(\d+)(?:-(\d+))?", spans):
            out.append((key, int(a), int(b or a)))
    return out


def endpoints(spec: str) -> set[tuple[str, int]]:
    return {(k, n) for k, a, b in cites(spec) if k in KEYS for n in (a, b)}


def parse_pins(text: str) -> dict[tuple[str, int], str]:
    out: dict[tuple[str, int], str] = {}
    for ln in text.splitlines():
        if m := re.fullmatch(r"([A-Za-z0-9.-]+):(\d+) ([0-9a-f]{16})", ln.strip()):
            out[(m.group(1), int(m.group(2)))] = m.group(3)
    return out


def base_line(ctx: Ctx, key: str, n: int) -> str | None:
    lines = ctx.base.get(key, "").splitlines()
    return lines[n - 1] if 0 < n <= len(lines) else None


def gate_cite(ctx: Ctx, r: Result) -> None:
    cited = cites(ctx.spec)
    for key, a, b in cited:
        if key not in KEYS:
            r.fail("G6-CITE", f"`{key}`:{a}: an undeclared key")
        elif not 0 < a <= b <= len(ctx.base[key].splitlines()):
            r.fail("G6-CITE", f"`{key}`:{a}-{b} is outside the file at {BASE}")
    for pin in CITE_PINS.replace("\n", ";").split(";"):
        key, line, words = pin.split("|", 2)
        text = base_line(ctx, key, int(line))
        if text is None or words not in text:
            r.fail("G6-CITE", f"`{key}`:{line} no longer carries {words!r}")
        if not any(k == key and a <= int(line) <= b for k, a, b in cited):
            r.fail("G6-CITE", f"the pinned cite `{key}`:{line} is not in the spec")
    pins, want = parse_pins(ctx.pins), endpoints(ctx.spec)
    missing = sorted(want - set(pins))
    extra = sorted(set(pins) - want)
    moved = sorted(
        k for k, h in pins.items() if k in want and line_hash(base_line(ctx, *k) or "") != h
    )
    if missing or extra or moved:
        r.fail("G6-CITE", f"the pins file: unpinned {missing}, uncited {extra}, changed {moved}")
    r.numbers["cites"] = len(cited)
    r.numbers["pins"] = len(pins)


def repin(ctx: Ctx) -> str:
    out = [
        "# E28-D04 pins: one cited endpoint per line, `KEY:line sha1-16` of its words at the base.",
        "# Written only by `e28_d04_motion_audit.py --repin-ruled`; `--check` reads it.",
    ]
    for key, n in sorted(endpoints(ctx.spec), key=lambda x: (x[0], x[1])):
        line = base_line(ctx, key, n)
        if line is not None:
            out.append(f"{key}:{n} {line_hash(line)}")
    return "\n".join(out) + "\n"


# --- G7: the request rows ---------------------------------------------------------------------
def gate_request(ctx: Ctx, r: Result) -> None:
    rs = {x[0]: " ".join(x) for x in rows(section(ctx.spec, 8)) if x}
    if tuple(rs) != REQUESTS:
        r.fail("G7-REQUEST", f"request rows {list(rs)}, expected R1 to R7")
    if missing := [w for w in R6_WORDS if w not in rs.get("R6", "")]:
        r.fail("G7-REQUEST", f"R6 does not name {missing}")
    if re.search(r"`E28-D03`:\d|merges? as is|once #5463 merges|unmerged", ctx.spec):
        r.fail("G7-REQUEST", "E28-D03 is cited off its `D03` key, or pre-stage wording is left")
    for block in re.split(r"\n\s*\n|\n(?=\|)", ctx.spec):
        if "#5482" in block and "PENDING" not in block:
            r.fail("G7-REQUEST", f"a block names #5482 without PENDING: {block.strip()[:60]!r}")
    r.numbers["requests"] = len(rs)


# --- G8, G9: hygiene and boards ---------------------------------------------------------------
def gate_hygiene(ctx: Ctx, r: Result) -> None:
    for name, text in (("the spec", ctx.spec), ("the pins", ctx.pins), ("the tool", ctx.tool)):
        text = EMBED.sub("", text)  # the board embeds (section 7.2) are G9's
        for word in BANNED:
            mixed = word[:1].isupper() and not word.isupper()  # a mixed-case word matches its case
            hay, needle = (text, word) if mixed else (text.lower(), word.lower())
            if needle in hay:
                r.fail("G8-HYGIENE", f"{name}: a word from the public-text list: {word!r}")
        if host := HOST.search(text):
            r.fail("G8-HYGIENE", f"{name}: a host name {host.group(0)!r}")
    for pat, what in (
        (LOCAL_PATH, "a local path"),
        (r"https?://", "a host"),
        (r"\b(?:close[sd]?|fix(?:e[sd])?|resolve[sd]?) #\d", "a closing keyword"),
    ):
        if re.search(pat, EMBED.sub("", ctx.spec), re.IGNORECASE):
            r.fail("G8-HYGIENE", f"the spec: {what}")
    for rel in (SPEC_REL, PINS_REL, Path(__file__).name):
        if hit := [w for w in RESERVED_IN_NAMES if w in Path(rel).name.lower()]:
            r.fail("G8-HYGIENE", f"the file name {Path(rel).name!r} carries {hit}")


def gate_boards(ctx: Ctx, r: Result) -> None:
    bs = rows(section(ctx.spec, 7).split("\n### 7.1 ")[0])
    for i, b in enumerate(bs, 1):
        m = re.fullmatch(r"`E28-D04 / (\d\d) ([a-z0-9-]+)`", b[1] if len(b) > 1 else "")
        exp = f"`docs/design/E28/img/E28-D04-{m.group(1)}-{m.group(2)}.png`" if m else ""
        ok = m and len(b) == 6 and b[0] == m.group(1) == f"{i:02d}" and b[2] == exp
        if not ok or b[3] != "dark" or b[5] != "drawn":
            r.fail("G9-BOARDS", f"board row {b[:2]}: name, export, theme or status off the pattern")
    if len(bs) != BOARDS:
        r.fail("G9-BOARDS", f"{len(bs)} boards (proposed {BOARDS} dark, no twins)")
    r.numbers["boards"] = len(bs)
    exports = [b[2].strip("`") if len(b) > 2 else "" for b in bs]
    built = {x[0]: x for x in rows(subsection(ctx.spec, "7.1")) if x}
    sums: dict[str, str] = {}
    for no, rel in zip([b[0] for b in bs], exports, strict=False):
        x, facts = built.get(no), png_facts(ctx.pngs.get(rel))
        if facts:
            sums[rel] = facts[1]
        if not x or len(x) != 4 or x[1] != f"`{Path(rel).name}`" or not facts:
            r.fail(
                "G9-BOARDS", f"board {no}: no section 7.1 row naming {Path(rel).name}, or no PNG"
            )
        elif (x[2], x[3]) != (facts[0], f"`{facts[1]}`"):
            r.fail(
                "G9-BOARDS", f"board {no}: section 7.1 records {x[2]} {x[3][:12]}, the PNG differs"
            )
    embeds = EMBED.findall(subsection(ctx.spec, "7.2"))
    pins = [sha for sha, _ in embeds]
    ref = max(set(pins), key=pins.count) if pins else ""
    if [rel for _, rel in embeds] != exports:
        r.fail("G9-BOARDS", "section 7.2 does not embed each board's export once, in order")
    for sha, rel in embeds:
        if rel not in sums:
            continue  # no PNG: the section 7.1 FAIL above names it
        blob = ctx.blob(sha, rel)
        if sha != ref or blob is None or hashlib.sha256(blob).hexdigest() != sums.get(rel):
            r.fail("G9-BOARDS", f"{Path(rel).name}: the embed's commit {sha[:10]} is not the PNG")
    r.numbers["embeds"] = len(embeds)


# --- G10: the rulings ------------------------------------------------------------------------
def gate_ruled(ctx: Ctx, r: Result) -> None:
    sec1, sec3, sec5 = section(ctx.spec, 1), section(ctx.spec, 3), section(ctx.spec, 5)
    if RULING not in sec1 or len(bq_ids(ctx.spec)) != 14:
        r.fail("G10-RULED", f"section 1 does not name ruling {RULING} over BQ-01 to BQ-14")
    if f"**MS-2.** {JOINT}" not in " ".join(sec3.split()):
        r.fail("G10-RULED", "MS-2 is not the joint stale-preview sentence verbatim")
    if "opacity.muted" in ctx.spec:
        r.fail("G10-RULED", "`opacity.muted` is named; the stale rule cites E28-D03 section 8")
    for n, _, text in FR.findall(sec5):
        if n in ("5", "12") and FOCUS_OWNER not in text:
            r.fail("G10-RULED", f"FR-{n} does not cite E47-D04's removed-row move {FOCUS_OWNER}")
    for n, _, text in FR.findall(sec5):
        flat = " ".join(text.split())
        if n in ("5", "12") and ORDER not in flat:
            r.fail("G10-RULED", f"FR-{n} does not pin the removed-row order {ORDER!r}")
        if n == "2" and "first credential field" not in flat:
            r.fail("G10-RULED", "FR-2 does not name the first credential field")
        if n == "8" and "LR-09" not in flat:
            r.fail("G10-RULED", "FR-8 does not hand the save report's politeness to E28-D05 LR-09")
    sec6 = section(ctx.spec, 6)
    found = [x for x in rows(sec6) if x and re.fullmatch(r"A-\d+", x[0])]
    if tuple(x[0] for x in found) != AROWS:
        r.fail("G10-RULED", f"A-rows {[x[0] for x in found]}, expected {list(AROWS)}")
    for row in found[:3]:
        m = re.fullmatch(r"`([A-Za-z0-9.-]+)`:(\d+)", row[1]) if len(row) > 4 else None
        old = row[3][1:-1] if len(row) > 4 else ""
        line = base_line(ctx, m.group(1), int(m.group(2))) if m else None
        if line is None or line.count(old) != 1:
            r.fail("G10-RULED", f"{row[0]}: its Old does not stand once on its target line")
    r.numbers["arows"] = len(found)


GATE_FNS: tuple[tuple[str, Callable[[Ctx, Result], None]], ...] = (
    ("G1-TABLE", gate_table),
    ("G2-TOKEN", gate_token),
    ("G3-QUOTES", gate_quotes),
    ("G4-STILL", gate_still),
    ("G5-FOCUS", gate_focus),
    ("G6-CITE", gate_cite),
    ("G7-REQUEST", gate_request),
    ("G8-HYGIENE", gate_hygiene),
    ("G9-BOARDS", gate_boards),
    ("G10-RULED", gate_ruled),
)


def run(ctx: Ctx) -> Result:
    r = Result()
    for _, fn in GATE_FNS:
        fn(ctx, r)
    return r


# --- self-test --------------------------------------------------------------------------------
def sub(old: str, new: str) -> Callable[[Ctx], Ctx]:
    return lambda ctx: ctx._replace(spec=ctx.spec.replace(old, new, 1))


def regex(pattern: str, repl: str) -> Callable[[Ctx], Ctx]:
    return lambda ctx: ctx._replace(
        spec=re.sub(pattern, repl, ctx.spec, count=1, flags=re.MULTILINE)
    )


def pin_sub(pattern: str, repl: str) -> Callable[[Ctx], Ctx]:
    return lambda ctx: ctx._replace(
        pins=re.sub(pattern, repl, ctx.pins, count=1, flags=re.MULTILINE)
    )


def retarget(m: str, row_id: str) -> Callable[[Ctx], Ctx]:
    """Move row `m` onto E05-D03 row `row_id` consistently in its Recipe, timing and reduce cells."""

    def fn(ctx: Ctx) -> Ctx:
        out = []
        for line in ctx.spec.splitlines(keepends=True):
            cells = line.split("|")
            if len(cells) > 10 and cells[1].strip() == m:
                cells[5], cells[6] = f" row {row_id} ", f" per row {row_id} "
                cells[8] = f" row {row_id}'s reduce cell "
                line = "|".join(cells)
            out.append(line)
        return ctx._replace(spec="".join(out))

    return fn


MUTATIONS: tuple[tuple[str, Callable[[Ctx], Ctx]], ...] = (
    ("G1-TABLE", retarget("M-11", "2c")),
    (
        "G2-TOKEN",
        regex(
            r"^(\| M-3 +(?:\|[^|]+){5}\| )`motion\.duration\.instant`", r"\1`motion.duration.fast`"
        ),
    ),
    ("G3-QUOTES", sub("the sole indicator of a dangerous", "the only indicator of a dangerous")),
    ("G4-STILL", sub("The worked example never tweens.**", "The worked example rarely tweens.**")),
    ("G5-FOCUS", sub("The stale cut never moves focus.", "The stale cut should not move focus.")),
    ("G6-CITE", pin_sub(r"^(D02:154 )[0-9a-f]{16}$", r"\g<1>0000000000000000")),
    ("G7-REQUEST", regex(r"^(\| R6 .*?) at `3b23ab11a`", r"\1 at its head")),
    ("G8-HYGIENE", sub("one hash per cited line.", "one hash per cited line (" + "/" + "tmp/x).")),
    ("G9-BOARDS", sub("`E28-D04 / 03 readiness-bulk`", "`E28-D04 / 03 Readiness-bulk`")),
    ("G10-RULED", sub("full opacity, and the table carries", "full opacity, and the table shows")),
)

# Probes: edits a weaker gate would let through; each must add one FAIL.
PROBES: tuple[tuple[str, Callable[[Ctx], Ctx]], ...] = (
    ("G1-TABLE", retarget("M-4", "2a")),
    ("G1-TABLE", regex(r"^(\| M-6 .*\| )PROPOSED \(BQ-06\)", r"\1RULED (BQ-06)")),
    ("G2-TOKEN", sub("`color.text.secondary`", "`color.text.second`")),
    ("G3-QUOTES", sub("does not flash a skeleton", "does not show a skeleton")),
    ("G4-STILL", sub(MS_TEXT, "MS-1. Motion is never the sole carrier of a dangerous state.")),
    ("G5-FOCUS", sub("- **FR-9 (M-9).**", "- **FR-9 (M-8).**")),
    ("G6-CITE", sub("`D02`:389, :556;", "`D02`:389, :557;")),
    ("G7-REQUEST", sub("the one open input (R6, PENDING)", "the one open input (R6)")),
    ("G8-HYGIENE", sub("Ten gates:", "Ten gates (see relay" + ".example" + ".com):")),
    (
        "G7-REQUEST",
        sub("re-pinned to `main` and cited by", "re-pinned once #5463 merges, cited by"),
    ),
    ("G10-RULED", sub('"- **Stale.** The same muting,', '"- **Stale.** The same muted,')),
    ("G9-BOARDS", regex(r"^(\| 02 .*\| )drawn( +\|)$", r"\1PENDING (boards)\2")),
    ("G9-BOARDS", regex(r"^(\| 03 +\| `[^`]+` +\| \d+ × )(\d+)", r"\g<1>1\2")),
    ("G9-BOARDS", regex(r"^(\| 04 +\| `[^`]+` +\| \d[^|]+\| `)[0-9a-f]", r"\g<1>z")),
    (
        "G9-BOARDS",
        regex(
            r"(CandleViewer/CandleViewer/)[0-9a-f]{40}(/docs/design/E28/img/E28-D04-02)",
            "\\g<1>" + "0" * 40 + "\\2",
        ),
    ),
    ("G9-BOARDS", lambda ctx: ctx._replace(pngs={**ctx.pngs, next(iter(ctx.pngs), ""): b"x"})),
    (
        "G10-RULED",
        sub(
            "empty-state stop,\n  announced once (`E47-D04`:285;",
            "empty-state stop,\n  announced once (",
        ),
    ),
    ("G10-RULED", sub("(`E47-D04`:285). A refused-whole", "(E47-D04). A refused-whole")),
    (
        "G10-RULED",
        sub(
            "next row in the current sort, else the previous",
            "next row in the current sort, else the first row",
        ),
    ),
    (
        "G10-RULED",
        sub("the first\n  credential field in the step-up", "the first\n  button in the step-up"),
    ),
    (
        "G10-RULED",
        sub(
            "E28-D05 §4.4 puts focus on the report and LR-09",
            "E28-D05 §4.4 puts focus on the report",
        ),
    ),
)


def digests() -> dict[str, str]:
    files = (SPEC, PINS, Path(__file__))
    return {str(p): hashlib.sha256(p.read_bytes()).hexdigest() for p in files if p.exists()}


def self_test(ctx: Ctx, base: Result) -> list[str]:
    bad: list[str] = []
    before = digests()
    snap = hashlib.sha256((ctx.spec + ctx.pins).encode()).hexdigest()
    covered = {code for code, _ in MUTATIONS}
    bad += [f"self-test: gate {g} has no mutation" for g, _ in GATE_FNS if g not in covered]
    for code, fn in (*MUTATIONS, *PROBES):
        mutated = fn(ctx)
        if (mutated.spec, mutated.pins, mutated.pngs) == (ctx.spec, ctx.pins, ctx.pngs):
            bad.append(f"self-test {code}: the mutation did not apply")
            continue
        new = sorted(set(run(mutated).fails) - set(base.fails))
        if len(new) != 1 or not new[0].startswith(f"[{code}]"):
            bad.append(f"self-test {code}: expected one new [{code}] FAIL, got {new[:3]}")
    again = run(ctx)
    if hashlib.sha256((ctx.spec + ctx.pins).encode()).hexdigest() != snap:
        bad.append("self-test: the texts in memory changed")
    if again.fails != base.fails or again.numbers != base.numbers:
        bad.append("self-test: a re-run does not reproduce the base result")
    if digests() != before:
        bad.append("self-test: a file on disk changed")
    return bad


def main(argv: list[str]) -> int:
    ap = argparse.ArgumentParser(description=(__doc__ or "").splitlines()[0])
    ap.add_argument("--check", action="store_true", help="exit 1 on any FAIL")
    ap.add_argument("--json", action="store_true", help="print the numbers and findings as JSON")
    ap.add_argument("--self-test", "--selftest", action="store_true", help="the mutation self-test")
    ap.add_argument("--repin-ruled", action="store_true", help=f"rewrite {PINS_REL} deliberately")
    args = ap.parse_args(argv)
    ctx = load_ctx()
    if not all(ctx.base.values()) or not ctx.tokens:
        missing = [k for k, v in ctx.base.items() if not v]
        print(
            f"FAIL [G6-CITE] cannot read {missing or 'the tokens'} at {BASE} (fetch origin first)"
        )
        return 1
    if args.repin_ruled:
        PINS.write_text(repin(ctx), encoding="utf-8")
        print(f"--repin-ruled: {len(endpoints(ctx.spec))} endpoints pinned in {PINS_REL}")
        return 0
    res = run(ctx)
    st = self_test(ctx, res) if args.self_test else []
    if args.json:
        payload: dict[str, object] = {"numbers": res.numbers, "fails": res.fails}
        if args.self_test:
            payload["self_test"] = st
        print(json.dumps(payload, ensure_ascii=False, indent=1, sort_keys=True))
    else:
        n = res.numbers
        out = [f"FAIL {line}" for line in res.fails]
        out.append(
            f"rows {n.get('rows')} (cuts {n.get('cut_rows')}, E05-D03 rows "
            f"{n.get('recipe_rows')}); BQs {n.get('bqs')}; quotes {n.get('quotes')}; still "
            f"{n.get('still')}; focus rules {n.get('focus_rules')}; cites {n.get('cites')}; "
            f"pins {n.get('pins')}; requests {n.get('requests')}; boards {n.get('boards')}; "
            f"A-rows {n.get('arows')}"
        )
        out.append(f"gates: {len(GATE_FNS)}; FAIL {len(res.fails)}")
        if args.self_test:
            out += [f"FAIL {line}" for line in st]
            out.append(
                f"self-test: {'PASS' if not st else 'FAILED'}: {len(MUTATIONS)} mutations (one "
                f"per gate) and {len(PROBES)} probes, each one new FAIL; a re-run reproduces the "
                "base result; files on disk unchanged"
            )
        print("\n".join(out))
    failed = bool(res.fails or st)
    return 1 if (failed and (args.check or args.self_test)) else 0


if __name__ == "__main__":
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")
    raise SystemExit(main(sys.argv[1:]))
