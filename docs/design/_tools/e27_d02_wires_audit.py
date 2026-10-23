"""E27-D02 wireframe audit: the inventory against `14`, the frames, the annotations, the scans.

Stdlib only, offline (`python3 -I -B`); it reads the spec, `14`, `22`, `23`, `24`, the audit
registry and the E27-D01 memo as text and runs no repository code. A: every state `14` names for
the eight screens (CATALOGUE; each phrase must occur in the screen's entry and cover its "States"
line) is quoted by a row of the spec's section 7 inventory, and no row quotes another phrase.
B: section 0's boards list exactly section 7's frames, each once, on the same board; every frame
name in the spec is an inventory frame; at most 16 boards, each PENDING, exported by its slug.
C: each row names a `22` operation or `23` topic, a `24` section 15.2 permission (or `self`) and
an event a source names (or "no event"). D: no 16+ hex or mixed 18+ alphanumeric run, key ids are
`...` plus 4, IPv4 only from RFC 5737, 7+ digit numbers only the catalogue's placeholder UIDs.

Usage: python3 -I -B docs/design/_tools/e27_d02_wires_audit.py [--check] [--json]
`--json` prints the counts instead of the report; `--check` exits 1 on any miss.
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path

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
MAX_BOARDS = 16
KEYS = ("catalogue_states", "covered", "states_line_items", "frames")


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


def check_catalogue(cat: str, inv: list[list[str]], misses: list[str]) -> dict[str, dict]:
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
    per_screen = {}
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


def check_frames(spec: str, inv: list[list[str]], misses: list[str]) -> tuple[int, int, int]:
    """B: section 0 against section 7, and every frame name in the spec."""
    inv_frames: dict[str, str] = {}
    for r in inv:
        names = ticked(r[1])
        if len(names) != 1 or not FRAME_RE.fullmatch(f"`{names[0]}`"):
            misses.append(f"row {r[0]}: the frame cell must hold one frame name")
            continue
        if names[0] in inv_frames:
            misses.append(f"row {r[0]}: {names[0]!r} listed twice")
        inv_frames[names[0]] = r[6]
    boards = rows(section(spec, 0))
    on_board: dict[str, str] = {}
    for b in boards:
        num = b[0]
        name = re.fullmatch(rf"`E27-D02 / {num} ([a-z0-9-]+)`", b[1])
        if not name:
            misses.append(f"board {num}: name {b[1]!r}")
        elif b[3] != f"`docs/design/E27/img/E27-D02-{num}-{name.group(1)}.png`":
            misses.append(f"board {num}: export {b[3]!r} is not named by the board's slug")
        if b[4] != "PENDING":
            misses.append(f"board {num}: state {b[4]!r}, PENDING expected")
        for f in FRAME_RE.findall(b[2]):
            if f in on_board:
                misses.append(f"board {num}: {f!r} also on board {on_board[f]}")
            on_board[f] = num
    if len(boards) > MAX_BOARDS:
        misses.append(f"{len(boards)} boards, at most {MAX_BOARDS}")
    for f, num in on_board.items():
        if f not in inv_frames:
            misses.append(f"board {num}: {f!r} is not in the inventory")
        elif inv_frames[f] != num:
            misses.append(f"{f!r}: board {num} in section 0, {inv_frames[f]} in section 7")
    misses += [f"{f!r}: on no board" for f in inv_frames if f not in on_board]
    # A code span may wrap across lines (CommonMark reads the line ending as a space).
    stray = {" ".join(f.split()) for f in FRAME_RE.findall(spec)} - set(inv_frames)
    misses += [f"frame name outside the inventory: {f!r}" for f in sorted(stray)]
    return len(inv_frames), len(boards), len(on_board)


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


def scan(spec: str, misses: list[str]) -> dict[str, int]:
    """D: secret shapes, key ids, addresses and UIDs anywhere in the spec."""
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
    for m in re.finditer(r"(?<![\d.])(\d{1,3}(?:\.\d{1,3}){3})(?![\d.])", spec):
        n["ips"] += 1
        if not m.group(1).startswith(DOC_NETS):
            misses.append(f"IPv4 outside the documentation ranges: {m.group(1)}")
    for m in re.finditer(r"(?<![\d.,])\d{7,}(?!\d)", spec):
        n["uids"] += 1
        if m.group(0) not in PLACEHOLDER_UIDS:
            misses.append(f"7+ digit number that is no placeholder UID: {m.group(0)}")
    return n


def main() -> int:
    ap = argparse.ArgumentParser(description=(__doc__ or "").splitlines()[0])
    ap.add_argument("--check", action="store_true", help="exit 1 on any miss")
    ap.add_argument("--json", action="store_true", help="print the counts as JSON")
    args = ap.parse_args()
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")
    spec = read(SPEC)
    texts = {
        "14": read(PLAN / "14-screens-catalogue.md"),
        "22": read(PLAN / "22-api-openapi.yaml"),
        "23": read(PLAN / "23-ws-protocol.md"),
        "24": read(PLAN / "24-internal-schemas.md"),
        "registry": read(REGISTRY),
        "memo": read(MEMO),
    }
    misses: list[str] = []
    inv = rows(section(spec, 7))
    misses += [f"inventory row {r[0]}: {len(r)} cells, 7 expected" for r in inv if len(r) != 7]
    inv = [r for r in inv if len(r) == 7]
    per_screen = check_catalogue(texts["14"], inv, misses)
    frames, boards, on_boards = check_frames(spec, inv, misses)
    check_annotations(inv, texts, misses)
    scans = scan(spec, misses)
    counts = {"screens": per_screen, "scans": scans, "misses": len(misses), "boards": boards}
    counts |= {"inventory_rows": len(inv), "frames": frames, "frames_on_boards": on_boards}
    if args.json:
        print(json.dumps(counts, indent=2, sort_keys=True))
    else:
        out = ["# E27-D02 wireframe audit", ""]
        for scr, c in per_screen.items():
            out.append(f"- {scr}: {c['catalogue_states']} 14 states, {c['covered']} with a frame; ")
            out[-1] += f"States line items {c['states_line_items'] or 'none'}; {c['frames']} frames"
        out += ["", f"- rows {len(inv)}, frames {frames}, boards {boards}, on boards {on_boards}"]
        out.append(f"- scans: {scans['key_ids']} key ids, {scans['ips']} IPv4, {scans['uids']} ")
        out[-1] += f"7+ digit numbers; {scans['hex']} hex and {scans['mixed']} mixed runs found"
        out += ["", f"MISSES: {len(misses)}", *(f"- {m}" for m in misses)]
        print("\n".join(out))
    return 1 if (args.check and misses) else 0


if __name__ == "__main__":
    raise SystemExit(main())
