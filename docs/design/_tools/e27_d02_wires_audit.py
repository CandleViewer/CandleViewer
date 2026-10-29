"""E27-D02 wireframe audit: the inventory against `14`, the boards, the mapping, the scans.

Stdlib only, offline (`python3 -I -B`); it reads the spec, `14`, `22`, `23`, `24`, the audit
registry and the E27-D01 memo as text and runs no repository code. The lever-4 re-plan (#733,
BQ-1..BQ-14, ruled by the orchestrator on 2026-10-29) draws 39 of the 78 frames on ten boards and
keeps the other 39 "specified (drawn on request)". The gates, each FAIL led by its code:

- [INVENTORY] every state `14` names for the eight screens (CATALOGUE; each phrase must occur in
  the screen's entry and cover its "States" line) is quoted by a row of section 7, and no row
  quotes another phrase.
- [BOARDS] section 0 holds 1 to 10 boards and at most 3 twins (a third of the boards), each named
  `E27-D02 / NN slug` with its own number, no slug holding `key`, `secret`, `token` or `crypt`,
  exported by its slug, and PENDING until the boards PR.
- [MAP] every section 7 frame is on exactly one board or "on request", both ways: each board's
  frames in section 0 equal the rows whose Board cell names it, section 0's list of the frames
  specified (drawn on request) equals the "on request" rows, the five must-draw frames are on a
  board, every Covers cell is filled, the coverage sentence's counts are the computed ones, and no
  frame name in the spec is outside the inventory.
- [ANNOTATIONS] each row names a `22` operation or `23` topic, a `24` section 15.2 permission (or
  `self`) and an event a source names (or "no event").
- [SCAN] no 16+ hex or mixed 18+ alphanumeric run, key ids are `...` plus 4, IPv4 only from RFC
  5737, 7+ digit numbers only the catalogue's placeholder UIDs.
- [COPY] section 10's withdrawal refusal is CP-5's ruled text (#4936, BQ-9), byte for byte; the
  memo's CP-5 holds that text or, until #4936 merges, the text it replaces: that state is printed in
  `--check`'s summary line and in `--json` (not a WARN, since the spec is right either way), and the
  text PR rebases onto #4936's merge before READY, when this gate re-pins to the memo (BQ-9).
- [SUFFIX] every drawn title naming a LIVE account (a box title, a "Test", "Disable", "Revoke key",
  "Rotate the key of", "Actions for" or "Details for" title, a deleted-account notice) carries
  " · LIVE" (BQ-3).

`--json` prints the numbers, the FAILs and WARNs. `--check` prints the gate summary (0 FAIL and
0 WARN is the bar) and exits 1 on any FAIL. `--self-test` applies one mutation per gate to an
in-memory copy of the spec and passes only when each adds exactly one new FAIL carrying its gate
code, the restored text reproduces the base result byte for byte, and no file on disk changed.

Usage: python3 -I -B docs/design/_tools/e27_d02_wires_audit.py [--check] [--json] [--self-test]
"""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import sys
from collections.abc import Callable
from pathlib import Path
from typing import NamedTuple

ROOT = Path(__file__).resolve().parents[3]
SPEC = ROOT / "docs" / "design" / "E27" / "E27-D02.md"
PLAN = ROOT / "docs" / "plan"
REGISTRY = ROOT / "services" / "api" / "candleviewer" / "audit" / "actions.py"
MEMO = ROOT / "docs" / "design" / "research" / "e27-key-custody.md"

# The states `14` names per screen, verbatim (bold markers dropped), separated by "; "; an indented
# line continues the screen above. Each phrase must occur in the screen's own entry.
_CATALOGUE = """
SCR-016: loading; valid; invalid; Skip for now; A key with withdrawal permission is a hard block
SCR-019: pending; done; blocked with reason
SCR-079: healthy; key expiring soon; key invalid; IP-whitelist mismatch
  disabled/suspended account state
SCR-125: ok; key expiring (<14 d); key invalid; IP whitelist missing or mismatched
  withdrawal permission detected; within Bybit's 48 h new-key restriction; empty state
SCR-126: validating state; validation result panel; failure states for each check
  withdrawal permission present; duplicate UID; key/secret format; step-up gate before save
  edit mode where the secret field is empty and optional
SCR-127: step progress; rollback available until the old key is revoked; step-up gate
  rollback state if the new key fails validation
  the reminder to delete the old key at Bybit, with a confirmation checkbox
SCR-128: per-key age, permissions, allowlist and rotation-due state; overdue-rotation state
  'mark as compromised' emergency action
SCR-129: disable and delete are separate flows; open positions/orders/algos block deletion
  typed confirmation plus step-up; consequence summary is fetched before the dialog renders
"""
PLACEHOLDER_UIDS = {"1234567", "1234568", "1234569", "9000001"}  # `14` SCR-125's wireframe
DOC_NETS = ("192.0.2.", "198.51.100.", "203.0.113.")  # RFC 5737
TOPICS = ("wallet", "positions", "orders", "executions", "system")
FRAME_RE = re.compile(r"`((?:SCR-\d{3}|CMP-087|Pattern) / [^`]+)`")
OP_RE = re.compile(r"^(GET|POST|PUT|PATCH|DELETE) (/\S+)$")
POINTER = re.compile(r"^- \*\*(Wireframes|UX research|Hi-fi|Motion|Design) \(")  # not checklists
GATES = ("INVENTORY", "BOARDS", "MAP", "ANNOTATIONS", "SCAN", "COPY", "SUFFIX")
MAX_BOARDS, MAX_TWINS = 10, 3
NAME_DENY = re.compile(r"key|secret|token|crypt", re.IGNORECASE)
ON_REQUEST = "on request"
# The C-2.8 refusal and its onboarding form, the C-12.12 card, the revoke dialog, rung-3 rotation.
MUST_DRAW = (23, 34, 46, 50, 74)
KEYS = ("catalogue_states", "covered", "states_line_items", "frames")
CP5_OLD = (
    "Refused: this key can withdraw or transfer, and nothing was stored. It still works at Bybit: "
    "delete it in Bybit's dashboard, then create a key with only the trading rights CandleViewer "
    "allows."
)
CP5_RULED = (
    "Refused: this key has a right CandleViewer does not allow, such as withdraw or transfer, and "
    "nothing was stored. It still works at Bybit: delete it in Bybit's dashboard, then create a "
    "key with only the trading rights CandleViewer allows."
)
LIVE = r"(?:Main|sub_001|sub_002)"
TITLE_RE = re.compile(
    r'"((?:Test|Disable|Revoke key|Rotate the key of|Actions for|Details for) [^"]*)"'
)
NOTICE_RE = re.compile(rf'"({LIVE}(?: · LIVE)? deleted[^"]*)"')
BOX_TITLE_RE = re.compile(r"^\+-+ .*-\+$")
SPEC_LIST_RE = re.compile(
    r"\*\*Specified \(drawn on request\), (\d+) frames \(§7 #\):\*\* ([\d,\s]+?)\.\s*$",
    re.MULTILINE,
)
COVERAGE_RE = re.compile(
    r"(\d+) of the (\d+) frames are drawn and (\d+) specified \(drawn on request\); (\d+) of the"
    r" (\d+) `14` states are drawn and\s+(\d+) specified"
)


def catalogue() -> dict[str, tuple[str, ...]]:
    out: dict[str, list[str]] = {}
    key = ""
    for line in _CATALOGUE.strip().splitlines():
        text = line
        if line.startswith("SCR-"):
            key, text = line.split(": ", 1)
            out[key] = []
        out[key] += [p.strip() for p in text.split("; ") if p.strip()]
    return {k: tuple(v) for k, v in out.items()}


CATALOGUE = catalogue()


def norm(text: str) -> str:
    return " ".join(text.replace("**", "").split()).lower()


def read(path: Path) -> str:
    return path.read_text(encoding="utf-8")


def entry(cat: str, scr: str) -> str:
    """The screen's entry in `14`, without the design pointer lines (they quote states too)."""
    m = re.search(rf"^### {scr} — .*?(?=^### |^## |\Z)", cat, re.MULTILINE | re.DOTALL)
    if not m:
        raise SystemExit(f"{scr}: no entry in 14")
    return "\n".join(ln for ln in m.group(0).splitlines() if not POINTER.match(ln))


def states_items(sec: str) -> list[str]:
    m = re.search(r"\*\*States:\*\*\s*(.*?)(?:\s\*\*[A-Z][A-Za-z ]+:\*\*|\n|$)", sec)
    if not m:
        return []
    return [i.strip(" .") for i in re.split(r" · |; ", m.group(1)) if i.strip(" .")]


def section(spec: str, num: int) -> str:
    m = re.search(rf"^## {num}\. .*?(?=^## |\Z)", spec, re.MULTILINE | re.DOTALL)
    if not m:
        raise SystemExit(f"spec: no section {num}")
    return m.group(0)


def rows(sec: str) -> list[list[str]]:
    out = []
    for line in sec.splitlines():
        if line.startswith("| ") and not line.startswith("| -"):
            cells = [c.strip() for c in line.strip().strip("|").split("|")]
            if re.fullmatch(r"\d+", cells[0]):
                out.append(cells)
    return out


def ticked(cell: str) -> list[str]:
    return re.findall(r"`([^`]+)`", cell)


def known_events(texts: list[str]) -> set[str]:
    """Every dotted name the sources use, `a.b|c` alternations expanded to `a.b` and `a.c`."""
    names: set[str] = set()
    for text in texts:
        for tok in re.findall(r"[a-z_]+\.[a-z_.]+(?:\|[a-z_]+)*", text):
            head, *alts = tok.split("|")
            names.add(head.rstrip("."))
            names.update(f"{head.rsplit('.', 1)[0]}.{alt}" for alt in alts)
    return names


class Ctx(NamedTuple):
    """The texts the gates read; the self-test swaps `spec` for a mutated copy."""

    spec: str
    texts: dict[str, str]


class Result:
    """FAILs and WARNs, each led by its gate code, and the numbers `--json` prints.

    A plain class, not a dataclass: E27-D03's audit loads this module without registering it in
    `sys.modules`, where a dataclass's annotation lookup would fail."""

    def __init__(self) -> None:
        self.fails: list[str] = []
        self.warns: list[str] = []
        self.numbers: dict[str, object] = {}

    def fail(self, code: str, msg: str) -> None:
        self.fails.append(f"[{code}] {msg}")


def load_ctx() -> Ctx:
    texts = {
        "14": read(PLAN / "14-screens-catalogue.md"),
        "22": read(PLAN / "22-api-openapi.yaml"),
        "23": read(PLAN / "23-ws-protocol.md"),
        "24": read(PLAN / "24-internal-schemas.md"),
        "registry": read(REGISTRY),
        "memo": read(MEMO),
    }
    return Ctx(spec=read(SPEC), texts=texts)


def inventory(spec: str, r: Result) -> list[list[str]]:
    inv = rows(section(spec, 7))
    for row in inv:
        if len(row) != 7:
            r.fail("INVENTORY", f"row {row[0]}: {len(row)} cells, 7 expected")
    return [row for row in inv if len(row) == 7]


def screen_of(row: list[str]) -> str:
    return (ticked(row[1]) or [""])[0].split(" / ")[0]


def quoted_states(row: list[str]) -> list[str]:
    return [] if row[2].startswith("—") else re.findall(r'"([^"]+)"', row[2])


def check_catalogue(cat: str, inv: list[list[str]], misses: list[str]) -> dict[str, dict[str, int]]:
    """A: the catalogue phrases, verified in `14`, against the inventory."""
    quoted: dict[str, set[str]] = {s: set() for s in CATALOGUE}
    for r in inv:
        if r[2].startswith("—"):
            continue
        scr = (ticked(r[1]) or [""])[0].split(" / ")[0]
        for p in re.findall(r'"([^"]+)"', r[2]):
            if p in CATALOGUE.get(scr, ()):
                quoted[scr].add(p)
            else:
                misses.append(f"row {r[0]}: {p!r} is not a 14 state of {scr}")
    per_screen: dict[str, dict[str, int]] = {}
    for scr, phrases in CATALOGUE.items():
        sec = entry(cat, scr)
        misses += [f"{scr}: {p!r} not in its 14 entry" for p in phrases if norm(p) not in norm(sec)]
        items = states_items(sec)
        for item in items:
            if not any(norm(p) in norm(item) for p in phrases):
                misses.append(f"{scr}: 14 States item {item!r} has no catalogue phrase")
        missing = [p for p in phrases if p not in quoted[scr]]
        misses += [f"{scr}: 14 state {p!r} has no frame" for p in missing]
        frames = [r for r in inv if (ticked(r[1]) or [""])[0].startswith(scr + " / ")]
        sizes = (len(phrases), len(phrases) - len(missing), len(items), len(frames))
        per_screen[scr] = dict(zip(KEYS, sizes, strict=True))
    return per_screen


def gate_inventory(ctx: Ctx, r: Result) -> None:
    misses: list[str] = []
    inv = inventory(ctx.spec, r)
    r.numbers.update(screens=check_catalogue(ctx.texts["14"], inv, misses), inventory_rows=len(inv))
    r.fails += [f"[INVENTORY] {m}" for m in misses]


def boards(spec: str) -> list[list[str]]:
    return rows(section(spec, 0))


def gate_boards(ctx: Ctx, r: Result) -> None:
    """Section 0: the cap, the twins, the names, the exports and the state."""
    bs = boards(ctx.spec)
    nums = [b[0] for b in bs]
    twins = [b for b in bs if len(b) == 7 and b[4] != "—"]
    r.numbers.update(boards=len(bs), twins=len(twins))
    if not bs or len(bs) > MAX_BOARDS:
        r.fail("BOARDS", f"{len(bs)} boards; the set holds 1 to {MAX_BOARDS}")
    if len(twins) > MAX_TWINS or 3 * len(twins) > len(bs):
        r.fail("BOARDS", f"{len(twins)} twins in {len(bs)} boards; at most {MAX_TWINS}, a third")
    if nums != [f"{i:02d}" for i in range(1, len(bs) + 1)]:
        r.fail("BOARDS", f"board numbers {nums} are not 01 to {len(bs):02d} in order")
    for b in bs:
        num = b[0]
        if len(b) != 7:
            r.fail("BOARDS", f"board {num}: {len(b)} cells, 7 expected")
            continue
        name = re.fullmatch(r"`E27-D02 / (\d+) ([a-z0-9-]+)`", b[1])
        if not name or name.group(1) != num:
            r.fail("BOARDS", f"board {num}: name {b[1]!r}")
        elif NAME_DENY.search(name.group(2)):
            r.fail("BOARDS", f"board {num}'s slug holds a denied word: {name.group(2)}")
        elif b[5] != f"`docs/design/E27/img/E27-D02-{num}-{name.group(2)}.png`":
            r.fail("BOARDS", f"board {num}: export {b[5]!r} is not named by the board's slug")
        if b[4] != "—" and b[4] not in nums:
            r.fail("BOARDS", f"board {num}: twin of {b[4]!r}, no such board")
        if b[6] != "PENDING":
            r.fail("BOARDS", f"board {num}: state {b[6]!r}; PENDING until the boards PR")


def gate_map(ctx: Ctx, r: Result) -> None:
    """Section 0 against section 7, both ways; the coverage counts; stray frame names."""
    spec, inv = ctx.spec, inventory(ctx.spec, Result())
    bs = [b for b in boards(spec) if len(b) == 7]
    nums = {b[0] for b in bs}
    name_of: dict[str, str] = {}
    num_of: dict[str, int] = {}
    board_of: dict[int, str] = {}
    for row in inv:
        names = ticked(row[1])
        if len(names) != 1 or not FRAME_RE.fullmatch(f"`{names[0]}`"):
            r.fail("MAP", f"row {row[0]}: the frame cell must hold one frame name")
            continue
        if names[0] in num_of:
            r.fail("MAP", f"row {row[0]}: {names[0]!r} listed twice")
        n = int(row[0])
        name_of[row[0]], num_of[names[0]], board_of[n] = names[0], n, row[6]
        if row[6] != ON_REQUEST and row[6] not in nums:
            r.fail("MAP", f"row {row[0]}: Board {row[6]!r} is neither a board nor {ON_REQUEST!r}")
        if not row[2].strip():
            r.fail("MAP", f"row {row[0]}: an empty Covers cell")
    for b in bs:
        listed = re.findall(r"(\d+) `((?:SCR-\d{3}|CMP-087|Pattern) / [^`]+)`", b[2])
        for n_text, name in listed:
            if num_of.get(name) != int(n_text):
                r.fail("MAP", f"board {b[0]}: {n_text} {name!r} is not section 7's row {n_text}")
        on_board = {int(n) for n, _ in listed}
        in_rows = {n for n, bd in board_of.items() if bd == b[0]}
        if on_board != in_rows:
            gone, extra = sorted(in_rows - on_board), sorted(on_board - in_rows)
            r.fail("MAP", f"board {b[0]}: section 7 adds {gone}, section 0 adds {extra}")
    asked = {n for n, bd in board_of.items() if bd == ON_REQUEST}
    m = SPEC_LIST_RE.search(section(spec, 0))
    listed_asked = {int(x) for x in re.findall(r"\d+", m.group(2))} if m else set()
    if not m or int(m.group(1)) != len(listed_asked) or listed_asked != asked:
        lacks, adds = sorted(asked - listed_asked), sorted(listed_asked - asked)
        r.fail("MAP", f"section 0's specified (drawn on request) list lacks {lacks}, adds {adds}")
    for n in MUST_DRAW:
        if board_of.get(n, ON_REQUEST) == ON_REQUEST:
            r.fail("MAP", f"must-draw frame {n} is on no board")
    drawn_states = total_states = 0
    for scr, phrases in CATALOGUE.items():
        for p in phrases:
            frames = [row for row in inv if screen_of(row) == scr and p in quoted_states(row)]
            total_states += 1
            drawn_states += any(row[6] != ON_REQUEST for row in frames)
    drawn = len(board_of) - len(asked)
    specified_states = total_states - drawn_states
    got = (drawn, len(board_of), len(asked), drawn_states, total_states, specified_states)
    c = COVERAGE_RE.search(section(spec, 0))
    if not c or tuple(int(x) for x in c.groups()) != got:
        r.fail("MAP", f"section 0's coverage sentence is not the computed {got}")
    # A code span may wrap across lines (CommonMark reads the line ending as a space).
    stray = {" ".join(f.split()) for f in FRAME_RE.findall(spec)} - set(num_of)
    for f in sorted(stray):
        r.fail("MAP", f"frame name outside the inventory: {f!r}")
    r.numbers.update(frames=len(board_of), frames_drawn=drawn, frames_specified=len(asked))
    r.numbers.update(states=total_states, states_drawn=drawn_states)


def check_annotations(inv: list[list[str]], texts: dict[str, str], misses: list[str]) -> None:
    """C: data, RBAC and event per row."""
    paths = set(re.findall(r"^  (/\S+):\s*$", texts["22"], re.MULTILINE))
    block = re.search(r"class Permission\(StrEnum\):(.*?)\n\n", texts["24"], re.DOTALL)
    perms = set(re.findall(r'= "([a-z_]+:[a-z_]+)"', block.group(1))) if block else set()
    events = known_events([texts["14"], texts["registry"], texts["24"], texts["memo"]])
    for r in inv:
        sources = 0
        for tok in ticked(r[3]):
            m = OP_RE.match(tok)
            if m:
                sources += 1
                if m.group(2) not in paths:
                    misses.append(f"row {r[0]}: {tok!r} is not a 22 path")
            elif tok in TOPICS and f"| `{tok}`" in texts["23"]:
                sources += 1
        if not sources:
            misses.append(f"row {r[0]}: no data source")
        rb = ticked(r[4])
        for t in rb:
            if re.fullmatch(r"[a-z_]+:[a-z_]+", t) and t not in perms:
                misses.append(f"row {r[0]}: {t!r} is not a 24 permission")
        if not any(t in perms or t == "self" for t in rb):
            misses.append(f"row {r[0]}: no RBAC requirement")
        evs = [t for t in ticked(r[5]) if re.fullmatch(r"[a-z_]+\.[a-z_.]+", t)]
        misses += [f"row {r[0]}: event {t!r} is named by no source" for t in evs if t not in events]
        if not evs and "no event" not in r[5]:
            misses.append(f"row {r[0]}: no event")


def gate_annotations(ctx: Ctx, r: Result) -> None:
    misses: list[str] = []
    check_annotations(inventory(ctx.spec, Result()), ctx.texts, misses)
    r.fails += [f"[ANNOTATIONS] {m}" for m in misses]


def scan(spec: str, misses: list[str]) -> dict[str, int]:
    """Secret shapes, key ids, addresses and UIDs anywhere in the spec (E27-D03 imports it)."""
    n = {"hex": 0, "mixed": 0, "key_ids": 0, "ips": 0, "uids": 0}
    for m in re.finditer(r"(?<![0-9A-Za-z])[0-9a-fA-F]{16,}(?![0-9A-Za-z])", spec):
        n["hex"] += 1
        misses.append(f"secret-shaped hex run {m.group(0)[:6]}…")
    for m in re.finditer(r"[A-Za-z0-9]{18,}", spec):
        t = m.group(0)
        if all(re.search(c, t) for c in (r"\d", "[a-z]", "[A-Z]")):
            n["mixed"] += 1
            misses.append(f"secret-shaped run {t[:6]}…")
    for m in re.finditer(r"([A-Za-z0-9]?)\.\.\.([A-Za-z0-9]*)", spec):
        if m.group(2):
            n["key_ids"] += 1
            if m.group(1) or len(m.group(2)) != 4:
                misses.append(f"key id not truncated to ... plus 4: {m.group(0)!r}")
    for m in re.finditer(r"(?<![\d.])(\d{1,3}(?:\.\d{1,3}){3})(?!\.?\d)", spec):
        n["ips"] += 1
        if not m.group(1).startswith(DOC_NETS):
            misses.append(f"IPv4 outside the documentation ranges: {m.group(1)}")
    for m in re.finditer(r"(?<![\d.,])\d{7,}(?!\d)", spec):
        n["uids"] += 1
        if m.group(0) not in PLACEHOLDER_UIDS:
            misses.append(f"7+ digit number that is no placeholder UID: {m.group(0)}")
    return n


def gate_scan(ctx: Ctx, r: Result) -> None:
    misses: list[str] = []
    r.numbers["scans"] = scan(ctx.spec, misses)
    for msg in misses:
        r.fail("SCAN", msg)


def gate_copy(ctx: Ctx, r: Result) -> None:
    """CP-5's ruled text in section 10; the memo's CP-5 either text (re-pinned at #4936's merge)."""
    row = [x for x in rows_any(section(ctx.spec, 10)) if x[0] == "withdrawal refusal"]
    if len(row) != 1 or row[0][1] != f'"{CP5_RULED}"':
        r.fail("COPY", "section 10's withdrawal refusal is not CP-5's ruled text (BQ-9)")
    memo = [ln for ln in ctx.texts["memo"].splitlines() if ln.startswith("| CP-5 ")]
    state = "ruled" if memo and CP5_RULED in memo[0] else "the old text until #4936 merges"
    if not memo or (CP5_RULED not in memo[0] and CP5_OLD not in memo[0]):
        r.fail("COPY", "the memo's CP-5 holds neither the ruled text nor the text it replaces")
    r.numbers["memo_cp5"] = state


def rows_any(sec: str) -> list[list[str]]:
    """Every body row of the section's tables, the separator and header rows dropped."""
    out, last = [], ""
    for line in sec.splitlines():
        if line.startswith("| ") and not line.startswith("| -"):
            if not last.startswith("|"):
                last = line
                continue  # the header row
            out.append([c.strip() for c in line.strip().strip("|").split("|")])
        last = line
    return out


def gate_suffix(ctx: Ctx, r: Result) -> None:
    """BQ-3: a LIVE account named apart from its group carries " · LIVE"."""
    flat = " ".join(ctx.spec.split())
    seen = 0
    for m in TITLE_RE.finditer(flat):
        title = m.group(1)
        if re.search(rf"\b{LIVE}\b", title):
            seen += 1
            if " · LIVE" not in title:
                r.fail("SUFFIX", f"title without ' · LIVE': {title!r}")
    for m in NOTICE_RE.finditer(flat):
        seen += 1
        if " · LIVE" not in m.group(1):
            r.fail("SUFFIX", f"notice without ' · LIVE': {m.group(1)[:40]!r}")
    for line in ctx.spec.splitlines():
        if BOX_TITLE_RE.match(line) and re.search(rf"\b{LIVE}\b", line):
            seen += 1
            if "· LIVE" not in line:
                r.fail("SUFFIX", f"box title without '· LIVE': {line.strip('+- ')!r}")
    r.numbers["suffix_titles"] = seen


GATE_FNS: tuple[Callable[[Ctx, Result], None], ...] = (
    gate_inventory,
    gate_boards,
    gate_map,
    gate_annotations,
    gate_scan,
    gate_copy,
    gate_suffix,
)


def run(ctx: Ctx) -> Result:
    r = Result()
    for fn in GATE_FNS:
        fn(ctx, r)
    return r


# --- self-test -----------------------------------------------------------------------------------


def regex(pattern: str, repl: str) -> Callable[[Ctx], Ctx]:
    def apply(ctx: Ctx) -> Ctx:
        return ctx._replace(spec=re.sub(pattern, repl, ctx.spec, count=1, flags=re.MULTILINE))

    return apply


def sub(old: str, new: str) -> Callable[[Ctx], Ctx]:
    def apply(ctx: Ctx) -> Ctx:
        return ctx._replace(spec=ctx.spec.replace(old, new, 1))

    return apply


MUTATIONS: tuple[tuple[str, Callable[[Ctx], Ctx]], ...] = (
    ("INVENTORY", regex(r'^(\| 26 +\|[^|]+\| )"failure states', r'\1"failure state')),
    ("BOARDS", sub("`E27-D02 / 07 revoke-dialog`", "`E27-D02 / 07 revoke-key`")),
    ("MAP", regex(r"^(\*\*Specified \(drawn on request\)[\s\S]*?)\b75, ", r"\1")),
    ("ANNOTATIONS", regex(r"^(\| 19 +\|.*`admin\.key_form_)opened`", r"\1open`")),
    ("SCAN", sub("198.51.100.7", "198.18.100.7")),
    ("COPY", sub("such as withdraw or transfer, and nothing", "such as withdraw, and nothing")),
    ("SUFFIX", sub("...c3d4 · LIVE\": CP-6's", "...c3d4\": CP-6's")),
)


def digests() -> dict[str, str]:
    paths = [SPEC, MEMO, REGISTRY, *(PLAN / f for f in ("14-screens-catalogue.md",))]
    return {str(p): hashlib.sha256(p.read_bytes()).hexdigest() for p in paths}


def self_test(ctx: Ctx, base: Result) -> list[str]:
    bad: list[str] = []
    before, spec_sha = digests(), hashlib.sha256(ctx.spec.encode()).hexdigest()
    covered = {code for code, _ in MUTATIONS}
    bad += [f"self-test: gate {g} has no mutation" for g in GATES if g not in covered]
    for code, fn in MUTATIONS:
        mutated = fn(ctx)
        if mutated.spec == ctx.spec:
            bad.append(f"self-test {code}: the mutation did not apply")
            continue
        new = sorted(set(run(mutated).fails) - set(base.fails))
        if len(new) != 1 or not new[0].startswith(f"[{code}]"):
            bad.append(f"self-test {code}: expected one new [{code}] FAIL, got {new[:3]}")
    again = run(ctx)
    if hashlib.sha256(ctx.spec.encode()).hexdigest() != spec_sha:
        bad.append("self-test: the restored text is not byte-identical")
    if again.fails != base.fails or again.numbers != base.numbers:
        bad.append("self-test: the restored text does not reproduce the base result")
    if digests() != before:
        bad.append("self-test: a file on disk changed")
    return bad


def main(argv: list[str]) -> int:
    ap = argparse.ArgumentParser(description=(__doc__ or "").splitlines()[0])
    ap.add_argument("--check", action="store_true", help="exit 1 on any FAIL")
    ap.add_argument("--json", action="store_true", help="print the numbers and findings as JSON")
    ap.add_argument("--self-test", "--selftest", action="store_true", help="the mutation self-test")
    args = ap.parse_args(argv)
    ctx = load_ctx()
    res = run(ctx)
    st = self_test(ctx, res) if args.self_test else []
    if args.self_test:
        res.numbers["mutations"] = len(MUTATIONS)
    if args.json:
        payload: dict[str, object] = {"numbers": res.numbers, "fails": res.fails}
        payload["warns"] = res.warns
        if args.self_test:
            payload["self_test"] = st
        print(json.dumps(payload, ensure_ascii=False, indent=1, sort_keys=True))
    else:
        out = [f"FAIL {line}" for line in res.fails] + [f"WARN {line}" for line in res.warns]
        n = res.numbers
        out.append(
            f"boards {n['boards']} (twins {n['twins']}); frames {n['frames']}: drawn "
            f"{n['frames_drawn']}, specified (drawn on request) {n['frames_specified']}; 14 states "
            f"{n['states']}, drawn {n['states_drawn']}; memo CP-5: {n['memo_cp5']}"
        )
        out.append(f"gates: {len(GATES)} ({', '.join(GATES)}); FAIL {len(res.fails)}, ")
        out[-1] += f"WARN {len(res.warns)}"
        if args.self_test:
            out += [f"FAIL {line}" for line in st]
            out.append(
                f"self-test: {'ok' if not st else 'FAILED'} — {len(MUTATIONS)} mutations, one "
                "per gate, each one new FAIL; restored text byte-identical; files on disk unchanged"
            )
        print("\n".join(out))
    failed = bool(res.fails or st)
    return 1 if (failed and (args.check or args.self_test)) else 0


if __name__ == "__main__":
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")
    raise SystemExit(main(sys.argv[1:]))
