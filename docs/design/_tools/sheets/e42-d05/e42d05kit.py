"""e42d05kit: the sheet kit for the E42-D05 (#960) Penpot boards. Python 3.12+, standard library only, built on
E42-D03's e42kit (imported from its folder, never edited) for the CMP-087 admin shell and the primitives.

Every builder returns cvsheet node dicts (schema: ../lib/cvsheet-v4.3.js header; the v1 node schema, unchanged in v4.x),
so each board generator draws its frames 1:1 at 1280 x 800 and 2560 x 1440, composes them in the confirmed plan's rows
with 80 px gutters, adds the 400 px annotation column outside the frames and writes, validates and packs the sheet.

Sources: SPEC (the merged docs/design/E42/E42-D05.md, a byte copy checked by SPEC_MD5; every L-number below and every
line the kit records is read there): §0 boards and names, §1 the worked example, §4.1 T2, §4.2 200 %, §4.3 forced
colours, §5-§11 the screens and their state tables (HL-, IL-, BK-, RW-, WZ-, IW-, GV-, SI- ids, parsed: STATES),
§8.2 the restore impact copy, §12 rungs, §13 keys, §15 the copy deck (parsed: COPY), §16 tokens; PLAN, the confirmed
ten-board plan (orchestrator 18:44Z, #960 comment 6477583631: BOARDS). build-notes.md beside this file is binding.

Use from a generator (python3 -I keeps the generator's folder off sys.path):
    import sys; sys.dont_write_bytecode = True
    sys.path.insert(0, "<this folder>")
    import e42d05kit as d
    fr = [d.at(d.scr143(px, "HL-2"), "HL-2", px, 6) for px in (1280, 2560)]   # one frame per size, named
    ann = d.ann_column(3, [d.ann_group("HL-2", fr, {...})])                     # build it after the frames
    d.write_board(3, [[fr[0], fr[1], ...], [...]], ann)                         # json + md, validate, pack
Copy: copy(key, **fills) returns a §15 / §8.2 string verbatim (or an inherited D03 / D04 / D09 / E17 one) and records
its key; rich(key, **fills) draws it with unknown fills as neutral bars and its [Actions] as controls; label(key)
returns an anatomy string the screen sections give outside §15 and records it as a copy gap with its line; bar(field)
draws a value no source gives. Notes go to e42kit.LOG (shared), merged into the sheet by write_board().
CLI: python3 -I e42d05kit.py selftest   (writes 00-selftest.json, validated)
"""

from __future__ import annotations

import copy as _copy
import hashlib
import json
import math
import re
import subprocess
import sys
from collections.abc import Iterable
from pathlib import Path
from typing import Any, NamedTuple

sys.dont_write_bytecode = (
    True  # importing e42kit must never refresh E42-D03's __pycache__ (read-only for this kit)
)
D03_DIR = (
    Path(__file__).resolve().parent.parent / "e42-d03"
)  # E42-D03's kit (e42kit.py; its boards PR)
if str(D03_DIR) not in sys.path:
    sys.path.insert(0, str(D03_DIR))
import e42kit as k

Node = dict[str, Any]
KIT_DIR = Path(__file__).resolve().parent
SHEETS_DIR = KIT_DIR.parent  # docs/design/_tools/sheets
TOOLS_DIR = SHEETS_DIR / "tools"
VALIDATOR = TOOLS_DIR / "validate_sheet.py"
COMPONENTS_FILE = TOOLS_DIR / "components.offline.json"
PACKER = TOOLS_DIR / "compact.py"  # the packer E42-D04 used for its v4 sheets (gen10/BUILD.md)
PACKED_DIR = KIT_DIR / "v4"  # the packed sheets the boards were rendered from
SPEC = (
    KIT_DIR / "spec/E42-D05@72ee4fb32.md"
)  # frozen: `git show 72ee4fb32:docs/design/E42/E42-D05.md`
SPEC_MD5 = "caa2ca66de34951efc989eac875def0a"  # 931 lines; origin/main 2026-10-28 (5e570c740)
PLAN = (
    KIT_DIR / "spec/e42d05-plan.md"
)  # posted as #960 comment 6477436230; confirmed 18:44Z (#960 comment 6477583631)


def _rel(p: Path) -> str:
    """A path as the sheets record it: relative to the kit folder, never absolute."""
    return p.relative_to(KIT_DIR).as_posix()


PIN = "d2e074f3330e7265d1908c29f99a772ff8ed6ab4"  # the spec's key: every `path:line` at this main (L17-18)
PAGE, REV = "E42-D05", "r1"
FILE_NAME = "E42-D05 boards"  # the per-set Penpot file (plan)
SECTION_BUDGET = (
    14000  # bytes per section (E42-D04 build notes); write_board() refuses more than SECTION_HARD
)
SECTION_HARD = 20000
GUTTER = 80  # margin and gutter between frames, rows and the annotation column (brief; no 80 px space token)
GRID_X, GRID_Y = (
    6000,
    9500,
)  # board NN at x = ((NN-1) mod 5) * 6000, y = floor((NN-1)/5) * 9500 (brief)
ANN_W, ANN_TEXT_W = k.ANN_W, k.ANN_TEXT_W  # 400 / 368
SIZES = (
    k.SIZES
)  # 1280: NavRail 64, main 976 (944 inside); 2560: NavRail 240, main 2080 (2048 inside); RightRail 240
SIZE_NAME = {1280: "1280×800", 2560: "2560×1440"}

# --- Tokens: exact Penpot names (d02/token-sync.json); colour and typography from the semantic sets only (§16).
APP, RAISED, OVERLAY, SUNKEN, HOVER, SELECTED = (
    k.APP,
    k.RAISED,
    k.OVERLAY,
    k.SUNKEN,
    k.HOVER,
    k.SELECTED,
)
BORDER_SUBTLE, BORDER_DEFAULT = k.BORDER_SUBTLE, k.BORDER_DEFAULT
BORDER_SELECTED = "color.border.selected"  # current step and the diagram's current state (§16 L734)
TEXT_1, TEXT_2, TEXT_3, TEXT_LINK, TEXT_ON = (
    k.TEXT_1,
    k.TEXT_2,
    k.TEXT_3,
    k.TEXT_LINK,
    k.TEXT_ON_ACTION,
)
ACTION_PRIMARY, FOCUS_RING = k.ACTION_PRIMARY, k.FOCUS_RING
OK_SUBTLE, OK_STRONG, WARN_SUBTLE, WARN_STRONG = (
    k.OK_SUBTLE,
    k.OK_STRONG,
    k.WARN_SUBTLE,
    k.WARN_STRONG,
)
DANGER_SUBTLE, DANGER_STRONG, INFO_SUBTLE, INFO_STRONG = (
    k.DANGER_SUBTLE,
    k.DANGER_STRONG,
    k.INFO_SUBTLE,
    k.INFO_STRONG,
)
NEUTRAL_DEFAULT, NEUTRAL_SUBTLE = (
    "color.neutral.default",
    k.NEUTRAL_SUBTLE,
)  # the "neutral" tone (§16 L724, CG-30)
STALE_IND = "color.data-confidence.stale.indicator"  # clock glyph (§16 L732)
STALE_TEXT, STALE_SURFACE = (
    "color.data-confidence.stale.text",
    "color.data-confidence.stale.surface",
)  # L736
TRACK = HOVER  # CMP-023's color.track -> color.surface.hover (§16 L723, D04 §15)
CAPTION, BODY, BODY_STRONG, LABEL = k.CAPTION, k.BODY, k.BODY_STRONG, k.LABEL
HEADING_SM, HEADING_MD, NUM_SM, NUM_BASE = k.HEADING_SM, k.HEADING_MD, k.NUM_SM, k.NUM_BASE
INSET_XS, INSET_SM, INSET_MD, INSET_LG, INSET_XL = (
    k.INSET_XS,
    k.INSET_SM,
    k.INSET_MD,
    k.INSET_LG,
    k.INSET_XL,
)
STACK_XS, STACK_SM, STACK_MD, STACK_LG = k.STACK_XS, k.STACK_SM, k.STACK_MD, k.STACK_LG
STEP = k.STEP  # space.3 gaps (D1) bound as space.stack.md (12 px), e42kit's binding
DIALOG_PAD, FIELD_GAP = k.DIALOG_PAD, k.FIELD_GAP
R_CONTROL, R_CARD, R_BADGE, R_DIALOG = k.R_CONTROL, k.R_CARD, k.R_BADGE, k.R_DIALOG
HAIRLINE, THICK, FOCUS_W = k.HAIRLINE, k.THICK, k.FOCUS_W
OPACITY_SCRIM, E_DIALOG = k.OPACITY_SCRIM, k.E_DIALOG
PX = dict(k.PX)
BAR_FILL, BAR_H = SELECTED, 10  # neutral value bars (E42-D03/D04 boards' look; never a value)
CONTROL_H, ROW_H = k.CONTROL_H, k.ROW_H
STEPPER_W = 240  # D1 / D27: steppers a 240 px column left of the step body
TILE_W = {
    1280: (307, 306, 307),
    2560: (400, 400, 400, 400, 400),
}  # D1: three columns at 1280, five at 2560
for _px, _ws in TILE_W.items():
    assert sum(_ws) + (len(_ws) - 1) * PX[STEP] == SIZES[_px].inner

# --- Notes (shared with e42kit: its LOG collects every token, fallback, live check, source and deviation).
LOG = k.LOG
NOTE_KINDS = (
    "sources",
    "copy_keys",
    "copy_gaps",
    "spec_gaps",
    "live_checks",
    "deviations",
    "fallbacks",
    "tokens",
)
for _kind in NOTE_KINDS:
    LOG.notes.setdefault(_kind, [])


def note(kind: str, line: str) -> str:
    """Record one note line (deduplicated) under kind."""
    LOG.notes.setdefault(kind, [])
    return LOG.add(kind, line)


def reset_notes() -> None:
    """Clear the shared collector (write_board() does this after writing)."""
    LOG.reset()
    for kind in NOTE_KINDS:
        LOG.notes.setdefault(kind, [])


FALLBACKS = {
    "TRACK": "fallback: color.track does not exist: CMP-023's track binds color.surface.hover (§16 L723, D04 §15)",
    "NEUTRAL": "fallback: no color.status.neutral.* exists (CG-30): the neutral tone binds color.neutral.default "
    "(glyph) on color.neutral.subtle (§16 L724)",
    "SCRIM": "fallback: the scrim is black at opacity.scrim in every theme; cvsheet binds tokens only, so it binds "
    "color.surface.sunken (= palette.black in dark); no light board holds a dialog (plan board 10)",
    "DOT": "fallback: the stepper's 'Current' dot has no registry glyph: drawn as an 8 px ellipse in "
    "color.border.selected (§9.1 L527)",
    "FC": "fallback: CSS system colours have no Penpot token: the forced-colours column binds Canvas -> "
    "color.surface.app, CanvasText -> color.text.primary, LinkText -> color.text.link, Highlight -> "
    "color.action.primary.default, HighlightText -> color.text.on-action (a construction, §4.3 L224-230)",
}
DEVIATIONS = {
    "compose": "compositions: library sets are instanced only where components.offline.json lists them (CMP-015 "
    "Skeleton); everything else is drawn locally and named '<CMP id> <Name> (composition)'",
    "bars": "values the worked example (§1 L83-95) does not give are drawn as neutral bars named by their field, "
    "never invented numbers or words",
    "names": "board name 'E42-D05 / NN <slug> · <sizes> · <theme>' per the confirmed plan (its new board numbers "
    "01-10); frames are named '<state id> · <size> [<old §0 board>]' so §0, the state rows, §18 and §22 "
    "reconcile mechanically",
    "root": "root is not a flex board: the plan's 80 px gutters have no spacing token (space.* has 64 and 96), so "
    "frames and the annotation column are placed by x/y with an 80 px margin",
    "insets": "insets are drawn inside the frame §0 names them on, as an absolute card at the frame's lower right "
    "titled 'Inset · <state id>' (they are not frames)",
    "modal-env": "dialogs: the TopBar's and the StatusBar's ENV badges are drawn again above the scrim at their "
    "chrome places (E42-D04 G-31; C-2.11); a live check aligns them after relayout",
    "light": "light boards are the same construction as their dark state, named '· light'; the theme switch "
    "happens at export (Penpot's token theme is file-wide)",
    "status-cols": "board 02's dark, light and hc columns are the same construction, one 1280 × 800 frame each, "
    "exported with its theme (deviation (4): proofs at 1280 only); the forced-colours column is a "
    "construction (FALLBACKS['FC'])",
    "shell": "the CMP-087 shell (TopBar, NavRail, band, rule, strip, footer marker, RightRail, StatusBar) is "
    "E42-D03's e42kit, reused as built (its own E42-D03 line references stay in its notes)",
}


def fallback(key: str) -> None:
    """Record FALLBACKS[key]."""
    note("fallbacks", FALLBACKS[key])


def deviate(key: str, line: str | None = None) -> None:
    """Record DEVIATIONS[key] (or a one-off line)."""
    note("deviations", line or DEVIATIONS[key])


# --- The spec: read once, md5-checked; L(n) is line n (1-based).
def _spec_lines() -> list[str]:
    raw = SPEC.read_bytes()
    got = hashlib.md5(raw).hexdigest()
    if got != SPEC_MD5:
        raise RuntimeError(
            f"{SPEC}: md5 {got}, the kit reads {SPEC_MD5}: re-pin the kit (L-numbers) first"
        )
    return raw.decode("utf-8").splitlines()


SPEC_LINES = _spec_lines()


def L(n: int) -> str:
    """Spec line n (1-based)."""
    return SPEC_LINES[n - 1]


def _ws(s: str) -> str:
    return re.sub(r"\s+", " ", s).strip()


def src(line: str) -> None:
    """Record a source line ("E42-D05 §x Lnnn …")."""
    note("sources", line)


def find_line(needle: str, lo: int = 1, hi: int | None = None) -> int:
    """The first spec line in [lo, hi] containing needle (whitespace-normalised); raises when absent."""
    nd = _ws(needle)
    for i in range(lo, (hi or len(SPEC_LINES)) + 1):
        if nd in _ws(L(i)):
            return i
    raise KeyError(f"spec: {needle!r} not found in L{lo}-{hi or len(SPEC_LINES)}")


# --- §15 copy deck (L705-715) and §8.2's impact lines (L471-485), parsed into COPY {key: (string, line)}.
FAMILIES = (
    "health",
    "stops",
    "hint",
    "incident",
    "backup",
    "restore",
    "onboard",
    "invitee",
    "group",
    "machine",
    "admin",
)
DECK_LO, DECK_HI = find_line("## 15. Copy deck"), find_line("## 16. Tokens")
IMPACT_LO, IMPACT_HI = find_line("### 8.2 What a restore does"), find_line("### 8.3 States")
COPY: dict[str, tuple[str, int]] = {}
COPY_KIT_NAMED: set[str] = (
    set()
)  # keys the kit names for a §15 "*" list the deck gives without sub-keys
_TOKEN = re.compile(r"`([^`]+)`|\"([^\"]*)\"")
STAR_NAMES = {  # §15's unnamed lists: the deck's strings in order -> the kit's sub-key names (recorded as such)
    "incident.detail": ("occurrences", "first_seen", "last_seen", "runbook", "signature"),
    "backup.status": (
        "verified",
        "ok",
        "failed",
        "running",
        "restored",
        "deleted",
        "not_encrypted",
    ),
    "backup.verify_refused": ("verify_running", "restore_running", "not_usable", "rate", "store"),
    "backup.del.refused": ("deleted", "in_use", "last_usable"),
    "machine.timeline": ("ahead", "commit", "fault", "faulted"),
}


def _put(key: str, s: str, line: int) -> None:
    key = key.strip()
    if key in COPY and COPY[key][0] != s:
        n = 2
        while f"{key}#{n}" in COPY:
            n += 1
        key = f"{key}#{n}"
        if key in ALIASES:
            key = ALIASES[key]
            COPY_KIT_NAMED.add(key)
    COPY.setdefault(key, (s, line))


def _segments(cell: str) -> list[str]:
    """cell split at ' · ' outside quotes and backticks."""
    out, cur, q, b = [], [], False, False
    i = 0
    while i < len(cell):
        c = cell[i]
        if c == '"' and not b:
            q = not q
        elif c == "`" and not q:
            b = not b
        if not q and not b and cell.startswith(" · ", i):
            out.append("".join(cur))
            cur = []
            i += 3
            continue
        cur.append(c)
        i += 1
    out.append("".join(cur))
    return out


def _full(tok: str, prefix: str, last: str | None) -> str:
    """A §15 key token as a full key: 'health.x' kept, '.y' relative to the last key's parent, 'z' under prefix."""
    tok = tok.strip()
    if tok.startswith("."):
        if not last:
            raise ValueError(f"relative key {tok!r} with no key before it")
        return last.rsplit(".", 1)[0] + tok
    if tok.split(".")[0] in FAMILIES:
        return tok
    return prefix + tok


ALIASES = {  # a key's second string in the deck, named by the kit (recorded as kit-named)
    "health.incidents#2": "health.incidents.more",
    "health.announce#2": "health.announce.recovered",
    "health.export.ready#2": "health.export.truncated",
    "incident.acked#2": "incident.acked.unnamed",
    "incident.duration#2": "incident.duration.open",
    "onboard.key_revisit#2": "onboard.key_revisit.secret",
    "invitee.accept#2": "invitee.accept.body",
}
PARSE_SKIP = {"Acknowledge a latch"}
NOT_COPY = {  # quoted strings in the keyed rows that are not copy: (why)
    "Exchange-side stop-losses stay active.": "the D02:715 tail ruling Q11 removes (§15 L708)",
    "if D7 decides as proposed": "RW-5's target label (§8.2 L481), drawn by restore_step2(part='security')",
}  # quoted source titles inside a row (E42J:907's AC name), not copy
_CITE = re.compile(r"^\d+:\d|:|^[A-Z]")  # `14:2698`, `20:1560` … (citations), never keys


def _groups(seg: str) -> list[tuple[list[str], list[str]]]:
    """A segment's tokens as alternating (keys, strings) groups, citations dropped."""
    out: list[tuple[list[str], list[str]]] = []
    for m in _TOKEN.finditer(seg):
        kk, ss = m.group(1), m.group(2)
        if kk is not None:
            if _CITE.search(kk) and not kk.startswith("."):
                continue
            if not out or out[-1][1]:
                out.append(([], []))
            out[-1][0].append(kk)
        elif ss not in PARSE_SKIP:
            if not out:
                out.append(([], []))
            out[-1][1].append(ss)
    return out


def _parse_deck() -> None:
    for ln in range(DECK_LO, DECK_HI):
        row = L(ln)
        if not row.startswith("| `") or row.startswith("| `Keys"):
            continue
        cells = [c.strip() for c in row.strip().strip("|").split(" | ")]
        keys_cell, strings = cells[0], cells[1]
        fams = re.findall(r"`([a-z_]+)\.\*`", keys_cell)
        prefix = (fams[0] + ".") if fams else "admin."
        if fams[:1] == ["stops"]:
            _parse_stops(strings, ln)
            continue
        last: str | None = None
        star: list[Any] | None = (
            None  # [base, names, i] while a "*" list takes the strings that follow
        )
        for seg in _segments(strings.replace(". **Proposed", ". · **Proposed")):
            if "by reference" in seg:
                continue
            for gi, (keys, strs) in enumerate(_groups(seg)):
                fulls = [_full(t, prefix, last) for t in keys]
                stars = [f for f in fulls if f.endswith((".*", "_*"))]
                plain = [f for f in fulls if not f.endswith((".*", "_*"))]
                if stars:
                    base = stars[0][:-2].rstrip("._")
                    if plain and all("." not in t for t in keys[1:]) and len(plain) == len(strs):
                        for kk, s_ in zip(plain, strs):  # `label.*` for `a`, `b` …: "A", "B" …
                            _put(f"{base}.{kk.rsplit('.', 1)[-1]}", s_, ln)
                        star = None
                        continue
                    star = [base, STAR_NAMES.get(base, ()), 0] if not plain else None
                    fulls = plain
                if not fulls:
                    if star is not None:
                        for s_ in strs:
                            names, i = star[1], star[2]
                            nm = (
                                f"{star[0]}.{names[i]}" if i < len(names) else f"{star[0]}.#{i + 1}"
                            )
                            _put(nm, s_, ln)
                            COPY_KIT_NAMED.add(nm)
                            star[2] += 1
                    elif gi > 0 and last:
                        for s_ in strs:
                            _put(last, s_, ln)
                    continue
                star = None
                if not strs:
                    continue
                if len(fulls) == len(strs):
                    for kk, s_ in zip(fulls, strs):
                        _put(kk, s_, ln)
                elif len(fulls) == 1:
                    for s_ in strs:
                        _put(fulls[0], s_, ln)
                else:
                    for kk in fulls:
                        _put(kk, strs[0], ln)
                last = fulls[-1]


STAR_STATE: dict[str, tuple[str, int]] = {}
_STOP = re.compile(r"(\w+) (down|degraded|warning) \"([^\"]+)\"")


def _parse_stops(strings: str, ln: int) -> None:
    """§15 L708: stops.<component>.<state> (D02:715 cited; proposed for E42-D06), stops.clock.*, hint.<component>."""
    head, _sep, hints = strings.partition("`hint.<component>`")
    for comp, st, s in _STOP.findall(head):
        _put(f"stops.{comp}.{st}", s, ln)
    m = re.search(r'clock "([^"]+)" / "([^"]+)" / "([^"]+)"', head)
    if m:
        for nm, s in zip(("ok", "drift", "not_measured"), m.groups()):
            _put(f"stops.clock.{nm}", s, ln)
    for seg in _segments(hints):
        keys = re.findall(r"`(\w+)`", seg)
        strs = re.findall(r'"([^"]+)"', seg)
        for kk in keys:
            if strs:
                _put(f"hint.{kk}", strs[0], ln)


def _parse_impact() -> None:
    """§8.2 L471-485: restore.impact.* and restore.positions.* (+ their ticks), first column of each row."""
    for ln in range(IMPACT_LO, IMPACT_HI):
        row = L(ln)
        if not row.startswith("| `restore."):
            continue
        cell = row.strip().strip("|").split(" | ")[0]
        for kk, s in re.findall(r"`(restore\.[a-z_.]+)` \"([^\"]+)\"", cell):
            _put(kk, s, ln)


_parse_deck()
_parse_impact()

# The strings this kit inherits (§15 L715 "inherited", by reference): (string, source).
INHERITED: dict[str, tuple[str, str]] = {
    "banner.maintenance_fail_closed": (
        (
            "Order entry is blocked: maintenance mode's stored value can't be read, so it "
            "counts as on. Native stops on the exchange are unaffected."
        ),
        "D04 §14 (e42d04kit.py COPY, L718-719)",
    ),
    "banner.maintenance_unverified": (
        (
            "Maintenance mode is on — new orders are refused. Native stops on the exchange "
            "are unaffected."
        ),
        "D04 §14 (e42d04kit.py COPY, L720-721)",
    ),
    "admin.rate_limited": ("Paused by a rate limit.", "D04 §14, cited in §15 L714"),
    "fresh_code": (
        "This always needs a fresh code.",
        "D04 §11 L553 (dlg step-up line); §7 BK-12/BK-14, §11 SI-6",
    ),
    "spent_code": (
        "Your code was spent on this attempt — you'll confirm with a fresh code",
        "D02:708, cited §15 L710",
    ),
    "e17.banner.title": ("Disconnected — reconnecting (3)", "E17-D01:154 (SCR-152 banner title)"),
    "e17.banner.body": (
        (
            "Last data 00:12 ago. New orders off; cancel and close remain available, confirmed over the "
            "server. Exchange-side stops still protect open positions; app-managed rules are paused."
        ),
        "E17-D01:154 (SCR-152 banner body)",
    ),
    "e17.chip.reconnecting": ("Reconnecting (3)", "E17-D01:102 (CMP-076 chip)"),
    "e17.unreachable": ("Cannot reach server", "E17-D01:197 (Disconnected, REST unreachable)"),
    "scr017.cannot.manager": (
        "Not included in your role: manage users · change account settings · manage API keys.",
        "D09:281 (E09-D09 `scr017.cannot`, a Manager)",
    ),
    "scr017.cannot.viewer": (
        "Not included in your role: place orders · change rules · manage users.",
        "D09:281 (E09-D09 `scr017.cannot`, a Viewer)",
    ),
    "scr017.ask": ("Ask the owner if you need it.", "D09:85, cited §9.3 IW-4"),
    "withdraw_refused": (
        "This key has withdrawal permission. Create a key with withdrawal disabled.",
        "`14:425`, cited §9.2 WZ-13",
    ),
}
D03_INHERITED = (
    "tile.",
    "banner.maintenance",
    "meta.asof",
    "footer.area_entered",
    "strip.",
    "save.",
    "inv.",
    "ud.live_48h",
    "ud.cap_max",
    "cap.at_capacity",
    "dlg.",
    "admin.locked",
    "admin.ack_first",
    "rbac.view_as",
    "inflight.",
)
# §15 L714 proposes `admin.invite_pending` "The invite hasn't been accepted yet." while D03 §14 already has
# `admin.invite_pending` "Available once the invite is accepted." (e42kit COPY): D05's own string wins on its boards.
SPEC_GAPS = [
    (
        '§15 L714 proposes `admin.invite_pending` "The invite hasn\'t been accepted yet.", a key E42-D03 §14 already '
        'holds with another string ("Available once the invite is accepted."): the kit draws D05\'s (WZ-14 is not drawn)'
    ),
]

_FILL = re.compile(r"\{([^{}]+)\}")


def norm_fill(name: str) -> str:
    """A fill name as a keyword: '{yyyy-mm-dd hh:mm}' -> yyyy_mm_dd_hh_mm, '{first seen}' -> first_seen."""
    return re.sub(r"[^0-9A-Za-z]+", "_", name).strip("_").lower()


def raw(key: str) -> tuple[str, str]:
    """(template, source) of a key: §15 / §8.2 (parsed), INHERITED, or E42-D03's e42kit COPY (D03_INHERITED)."""
    if key in COPY:
        s, ln = COPY[key]
        return s, f"E42-D05 L{ln}"
    if key in INHERITED:
        return INHERITED[key]
    if key.startswith(D03_INHERITED) and key in k.COPY:
        v = k.COPY[key]
        return (" ".join(v) if isinstance(v, tuple) else v), "E42-D03 §14 (inherited, §15 L715)"
    raise KeyError(f"copy key {key!r}: not in §15 / §8.2, INHERITED or E42-D03's inherited keys")


def fills_of(key: str) -> list[str]:
    """The normalised fill names a key's template takes, in order."""
    return [norm_fill(f) for f in _FILL.findall(raw(key)[0])]


def copy(key: str, **fills: Any) -> str:
    """The key's string verbatim with every {fill} filled (keyword = norm_fill(name)); records the key. A missing or
    None fill raises: use rich() to draw an unknown fill as a bar."""
    tmpl, source = raw(key)
    note("copy_keys", key)
    src(f"copy {key}: {source}")
    if key in COPY_KIT_NAMED:
        note("copy_gaps", f"{key}: §15 lists the string without a sub-key; the kit names it")

    def sub(m: re.Match[str]) -> str:
        nm = norm_fill(m.group(1))
        if fills.get(nm) is None:
            raise KeyError(
                f"copy({key!r}): fill {{{m.group(1)}}} ({nm}=) not given; use rich() for a bar"
            )
        return str(fills[nm])

    return _FILL.sub(sub, tmpl)


def label(chars: str, line: int, why: str = "anatomy") -> str:
    """An anatomy string the screen sections give outside §15 (h1, column header, button label…), verbatim from
    spec line `line` (checked), recorded as a copy gap with its line."""
    rng = range(max(1, line - 2), min(line + 7, len(SPEC_LINES)))
    for span in (1, 2):  # a single line first, then a string wrapped across two lines
        for start in rng:
            if _ws(chars) in _ws(" ".join(SPEC_LINES[start - 1 : start - 1 + span])):
                where = f"L{start}" if span == 1 else f"L{start}-{start + 1}"
                note("copy_gaps", f"'{chars}': {why}, spec {where} (no §15 key)")
                return chars
    raise KeyError(f"label {chars!r} is not on spec L{line}-{line + 6}")


# --- §5.3-§11 state tables, parsed: STATES[id] = State(...).
class State(NamedTuple):
    sid: str
    name: str
    board: str  # "06 `scr143-healthy` ★" as §0's column gives it
    when: str
    renders: str
    copy_keys: str
    announce: str
    line: int


def _parse_states() -> dict[str, State]:
    out: dict[str, State] = {}
    for i, row in enumerate(SPEC_LINES, 1):
        m = re.match(r"\| ((?:HL|IL|BK|RW|WZ|IW|GV|SI)-\d+) +\|", row)
        if not m:
            continue
        cells = [c.strip() for c in row.strip().strip("|").split(" | ")]
        if len(cells) != 7:
            raise ValueError(f"spec L{i}: state row with {len(cells)} cells")
        out[cells[0]] = State(
            cells[0], cells[1], cells[2], cells[3], cells[4], cells[5], cells[6], i
        )
    return out


STATES = _parse_states()


def state(sid: str) -> State:
    """A state row (§5.3, §6, §7, §8.3, §9.2, §9.3, §10, §11) by id; records its line as a source."""
    st = STATES[sid]
    src(f"{sid} {st.name}: E42-D05 L{st.line}")
    return st


SCREEN_HEAD = {
    "SCR-143": "### 5.3 States",
    "SCR-144": "## 6. SCR-144",
    "SCR-146": "## 7. SCR-146",
    "restore": "### 8.3 States",
    "wizard": "### 9.3 SCR-017",
    "SCR-062": "## 10. SCR-062",
    "inspector": "## 11. The E42-S08",
}


def bullet(screen: str, lead: str) -> tuple[str, int]:
    """A '- **<lead>…**' paragraph of a screen section (whitespace-normalised) and its first line."""
    lo = find_line(SCREEN_HEAD[screen])
    start = find_line(f"- **{lead}", lo)
    out = [L(start)]
    j = start + 1
    while j <= len(SPEC_LINES) and L(j).startswith("  "):
        out.append(L(j))
        j += 1
    return _ws(" ".join(out))[2:], start


def keys_text(screen: str) -> tuple[str, int]:
    """The screen's keyboard paragraph (focus order; the plan's keyboard rider)."""
    return bullet(screen, "Keys")


def events_text(screen: str) -> tuple[str, int]:
    """The screen's events paragraph (audit, analytics, metrics)."""
    lead = {
        "SCR-143": "RBAC and events",
        "SCR-144": "RBAC and events",
        "SCR-146": "Events",
        "restore": "Events",
        "wizard": "Events",
        "SCR-062": "Keys and events",
        "inspector": "Keys and events",
    }[screen]
    if screen == "restore":
        screen = "SCR-146"  # the restore's events are SCR-146's (§7 Events: backup.restore)
    return bullet(screen, lead)


SHARED_KEYS_LINE = find_line("Orders per surface are in §5–§11.")


def shared_keys() -> str:
    """§13's shared keyboard paragraph (dialogs focus Cancel, Esc cancels, focus returns; steppers the heading)."""
    out = []
    j = SHARED_KEYS_LINE
    while L(j).strip():
        out.append(L(j))
        j += 1
    return _ws(" ".join(out))


# --- §0 / the confirmed plan: ten boards, their rows of frames (state id, size, old §0 board, insets).
class F(NamedTuple):
    """One planned frame: state id (or a sheet column's id), px, the old §0 board, a variant tag, its insets."""

    sid: str
    px: int
    old: str
    tag: str = ""
    insets: tuple[str, ...] = ()


class Bd(NamedTuple):
    nn: int
    slug: str
    theme: str
    rows: tuple[tuple[F, ...], ...]
    star: bool
    keys: tuple[
        str, ...
    ]  # screens whose focus order the annotation column overlays (keyboard rider)


def _f(spec: str) -> tuple[F, ...]:
    """'HL-2@1280+2560[06]{client}' -> F frames (insets after '{', ';'-separated)."""
    m = re.fullmatch(r"([A-Za-z0-9-]+)@([0-9+]+)\[(\d{2,3})\](?:<([^>]*)>)?(?:\{([^}]*)\})?", spec)
    if not m:
        raise ValueError(spec)
    sid, sizes, old, tag, ins = m.groups()
    out = []
    for i, s in enumerate(sizes.split("+")):
        out.append(
            F(sid, int(s), old, tag or "", tuple((ins or "").split(";")) if ins and i == 0 else ())
        )
    return tuple(out)


def _row(*specs: str) -> tuple[F, ...]:
    return tuple(f for s in specs for f in _f(s))


BOARDS: dict[int, Bd] = {
    b.nn: b
    for b in (
        Bd(
            1,
            "e04-continuity",
            "dark",
            (
                _row(
                    "HL-2@1280[01]<E04 scr-143-all-green>",
                    "HL-5@1280[01]<E04 scr-143-degraded-outage>",
                    "HL-14@1280[01]<E04 scr-143-unreachable-backend>",
                    "IL-2@1280[01]<E04 scr-144-incident-log>",
                ),
            ),
            False,
            (),
        ),
        Bd(
            2,
            "status-sheet",
            "dark",
            (
                _row(
                    "sheet-dark@1280[02]<dark>",
                    "sheet-light@1280[02]<light>",
                    "sheet-hc@1280[02]<hc>",
                    "sheet-fc@1280[04]<forced colours>",
                ),
            ),
            True,
            (),
        ),
        Bd(
            3,
            "scr143-144-populated",
            "dark",
            (
                _row("HL-2@1280+2560[06]{client-tile}", "HL-5@1280[09]{HL-5-gate}"),
                _row("HL-6@1280[10]{HL-7}", "IL-2@1280+2560[24]"),
            ),
            True,
            ("SCR-143", "SCR-144"),
        ),
        Bd(
            4,
            "scr143-outage",
            "dark",
            (
                _row("HL-11@1280+2560[14]", "HL-12@1280[15]{HL-15}"),
                _row("HL-14@1280+2560[17]", "HL-18@1280[20]"),
            ),
            True,
            (),
        ),
        Bd(
            5,
            "scr146-list-download",
            "dark",
            (
                _row("BK-4@1280+2560[38]", "BK-2@1280[36]"),
                _row("BK-12@1280+2560[46]", "BK-9@1280[43]"),
                _row("BK-13@1280[47]{link-expired;404}", "BK-14@1280[48]"),
            ),
            False,
            ("SCR-146",),
        ),
        Bd(
            6,
            "restore-gate-impact",
            "dark",
            (
                _row("RW-1@1280+2560[52]{RW-16}", "RW-3@1280[54]"),
                _row("RW-3@2560[54]", "RW-4@1280[55]{loading}", "RW-5@1280[56]{today}"),
                _row("RW-6@1280+2560[57]{config-only}"),
            ),
            True,
            ("restore",),
        ),
        Bd(
            7,
            "restore-outcomes",
            "dark",
            (
                _row("RW-8@1280+2560[59]{outcome-unknown}", "RW-10@1280[61]"),
                _row("RW-12@1280[63]", "RW-14@1280[65]<200 % zoom>", "RW-14@1280[65]<200 % text>"),
            ),
            False,
            (),
        ),
        Bd(
            8,
            "onboard-key",
            "dark",
            (
                _row("WZ-4@1280+2560[70]", "WZ-5@1280[71]"),
                _row("WZ-1@1280[67]{WZ-15}", "WZ-6@1280[72]", "WZ-11@1280[77]", "WZ-12@1280[78]"),
            ),
            False,
            ("wizard",),
        ),
        Bd(
            9,
            "scr017-scr062-inspector",
            "dark",
            (
                _row("IW-3@1280[84]{IW-9}", "IW-4@1280[85]", "GV-1@1280[90]"),
                _row("SI-1@1280[98]{rowless}", "SI-6@1280[103]"),
            ),
            False,
            ("wizard", "SCR-062", "inspector"),
        ),
        Bd(
            10,
            "light-representatives",
            "light",
            (_row("HL-20@1280[22]", "RW-15@1280[66]", "WZ-16@1280[81]"),),
            False,
            (),
        ),
    )
}
STAR_BOARDS = tuple(nn for nn, b in BOARDS.items() if b.star)  # (2, 3, 4, 6): 8 PNGs (plan)


def plan_frames(nn: int) -> list[F]:
    return [f for row in BOARDS[nn].rows for f in row]


def frame_name(f: F) -> str:
    """'<state id>[ · <tag>] · <size> [<old>]' (sibling names on a board stay unique)."""
    tag = f" · {f.tag}" if f.tag and not f.sid.startswith("sheet-") else ""
    sid = f.sid if not f.sid.startswith("sheet-") else f"status sheet · {f.tag}"
    return f"{sid}{tag} · {SIZE_NAME[f.px]} [{f.old}]"


def board_sizes(nn: int) -> str:
    pxs = sorted({f.px for f in plan_frames(nn)})
    return "+".join(SIZE_NAME[p] for p in pxs)


def board_name(nn: int) -> str:
    """'E42-D05 / NN <slug> · <sizes> · <theme>' (brief; Penpot's ' / ' form)."""
    b = BOARDS[nn]
    return f"{PAGE} / {nn:02d} {b.slug} · {board_sizes(nn)} · {b.theme}"


def grid_xy(nn: int) -> tuple[int, int]:
    """x = ((NN-1) mod 5) × 6000, y = floor((NN-1)/5) × 9500 (brief)."""
    return ((nn - 1) % 5) * GRID_X, ((nn - 1) // 5) * GRID_Y


def export_path(nn: int) -> str:
    return f"docs/design/E42/img/E42-D05-{nn:02d}-{BOARDS[nn].slug}.png"


def footer_text(nn: int) -> str:
    return f"page {PAGE} · board {nn:02d} · {REV}"


# --- Primitives (e42kit's node, text, glyph, boxes; D05's T2, bars, rich copy, the modal with the ENV badges).
node, text, icon, rect, ellipse = k.node, k.text, k.icon, k.rect, k.ellipse
box, hbox, vbox, inst = k.box, k.hbox, k.vbox, k.inst
est_width, est_height, text_w, text_lines = k.est_width, k.est_height, k.text_w, k.text_lines
link, button, busy_button, ring, skeleton, env_badge = (
    k.link,
    k.button,
    k.busy_button,
    k.ring,
    k.skeleton,
    k.env_badge,
)
glyph, tick, field, dialog, divider_rect = k.glyph, k.tick, k.field, k.dialog, k._divider


def _safe(s: str) -> str:
    return s.replace("/", "∕")


def bar(fld: str, w: int = 56, h: int = BAR_H, note_: str | None = None) -> Node:
    """A value no source gives (§1 L83-95, the state rows): a neutral bar named by its field, never a value."""
    deviate("bars")
    return rect(
        f"bar · {_safe(fld)}",
        w,
        h,
        BAR_FILL,
        {"radius": R_CONTROL},
        note=note_ or f"{fld}: no worked-example value (§1): a bar, never a value",
    )


_ACTION = re.compile(r"\[([^\]]+)\]")
BUTTON_ACTIONS = (
    "Retry",
    "Reload",
    "Check again",
    "Try again",
    "Start again",
    "Send again…",
    "Download",
    "Copy path",
    "Show all",
)


def action(chars: str, focused: bool = False) -> Node:
    """A control named inside a keyed string ("[Retry]"): a secondary CMP-001 for BUTTON_ACTIONS, else a CMP-021 link
    (E42-D03's rule)."""
    if chars in BUTTON_ACTIONS:
        return button(chars, "secondary", focused=focused)
    return link(chars)


def rich(
    key: str,
    *,
    w: int | None = None,
    typo: str = BODY,
    color: str = TEXT_1,
    name: str | None = None,
    focus: str | None = None,
    fill_map: dict[str, Any] | None = None,
    **fills: Any,
) -> Node:
    """A keyed string drawn as a wrapping row: its words (typo, color), every fill passed as None a bar named by the
    fill, every [Action] a control (focus= its label gets the ring). Records the key."""
    tmpl, source = raw(key)
    note("copy_keys", key)
    src(f"copy {key}: {source}")
    fills = {
        **fills,
        **(fill_map or {}),
    }  # fill_map: fills whose names clash with the keywords (e.g. {name})
    parts: list[Node] = []
    pos = 0
    pat = re.compile(r"\{([^{}]+)\}|\[([^\]]+)\]")
    i = 0
    for m in pat.finditer(tmpl):
        if m.start() > pos and tmpl[pos : m.start()].strip():
            i += 1
            parts.append(text(f"words-{i}", tmpl[pos : m.start()].strip(), typo, color))
        if m.group(1) is not None:
            nm = norm_fill(m.group(1))
            if nm not in fills:
                raise KeyError(
                    f"rich({key!r}): fill {{{m.group(1)}}} ({nm}=) not given (None draws a bar)"
                )
            v = fills[nm]
            i += 1
            if v is None:
                parts.append(bar(m.group(1)))
            elif isinstance(v, dict):
                parts.append(v)
            else:
                parts.append(
                    text(
                        f"fill-{i}",
                        str(v),
                        NUM_BASE if re.fullmatch(r"[\d:., %+-]+", str(v)) else typo,
                        color,
                    )
                )
        else:
            parts.append(action(m.group(2), focused=(focus == m.group(2))))
        pos = m.end()
    if tmpl[pos:].strip():
        i += 1
        parts.append(text(f"words-{i}", tmpl[pos:].strip(), typo, color))
    if len(parts) == 1 and parts[0]["t"] == "text" and w:
        return dict(parts[0], name=name or key, w=w)
    o: dict[str, Any] = {"gap": INSET_XS, "wrap": "wrap", "align": "center"}
    return hbox(
        name or key,
        parts,
        o,
        w=w,
        note=f"copy {key}: one string; fills as bars where no value is given",
    )


def words(
    key: str,
    typo: str = BODY,
    color: str = TEXT_1,
    w: int | None = None,
    name: str | None = None,
    **fills: Any,
) -> Node:
    """copy(key) as one text node (every fill given)."""
    return text(name or key, copy(key, **fills), typo, color, w=w)


# T2 (§4.1 L182-212): the look and the keys; never color.text.disabled or opacity.disabled.
T2_LABEL, T2_REASON, T2_FILL, T2_EDGE = TEXT_3, TEXT_2, RAISED, BORDER_DEFAULT
NEVER_TOKENS = ("color.text.disabled", "opacity.disabled")
T2_LINE = find_line("### 4.1 T2")


def lock_glyph(name: str = "lock") -> Node:
    """CMP-019 `lock` (decorative=false, name "Not available") in color.text.tertiary, leading the label (§4.1)."""
    return dict(
        glyph("lock", T2_LABEL, name),
        note='CMP-019 lock: decorative=false, accessible name "Not available"; '
        f"leads the full label (§4.1 L{T2_LINE + 2}-{T2_LINE + 4})",
    )


def t2_reason(reason: str, w: int | None = None, name: str = "reason", **fills: Any) -> Node:
    """The 2a reason: an admin.* key (≤ 60 characters, a full stop, no data), color.text.secondary caption, in the DOM
    at mount, the control's only aria-describedby (§4.1)."""
    s = copy(reason, **fills)
    if reason.startswith("admin.") and (len(s) > 60 or not s.endswith(".")):
        raise ValueError(
            f"{reason}: a T2 reason is ≤ 60 characters and ends with a full stop (§4.1)"
        )
    return text(
        name,
        s,
        CAPTION,
        T2_REASON,
        w=w,
        note="T2 reason: in the DOM at mount, the control's only aria-describedby; a T2 keystroke re-shows it "
        "with one polite announcement (§4.1)",
    )


def t2(
    chars: str,
    reason: str | None,
    variant: str = "secondary",
    *,
    shared: bool = False,
    focused: bool = False,
    beside: Node | None = None,
    w: int | None = None,
    name: str | None = None,
) -> Node:
    """A T2 CMP-001 control (§4.1 L184-212): native role and full label kept, aria-disabled (never disabled, in the
    Tab order), the lock leading the label, both color.text.tertiary; a filled variant drops to color.surface.raised
    with a color.border.default hairline; the reason inline under it (2a) unless shared=True (one notice, many
    pointers: the control's aria-describedby is the notice); beside= a node beside the reason (an exact time or a
    '→ Maintenance' link sits beside the reason, never in it). Emits nothing."""
    src(f"T2: E42-D05 §4.1 L{T2_LINE}-{T2_LINE + 30}")
    deviate("compose")
    kids = [lock_glyph(), text("label", chars, BODY_STRONG, T2_LABEL)]
    bw = round(est_width(hbox("m", kids, {"gap": INSET_XS})) + 2 * PX[k.BUTTON_PADX] + 2)
    o: dict[str, Any] = {
        "gap": INSET_XS,
        "padX": k.BUTTON_PADX,
        "radius": R_CONTROL,
        "height": k.CONTROL_COMF,
        "justify": "center",
    }
    if variant != "ghost":
        o.update(fill=T2_FILL, stroke=T2_EDGE, strokeWidth=HAIRLINE, strokeAlign="inner")
    ctl = hbox(
        f"CMP-001 Button (composition) · {chars} (T2)",
        kids,
        o,
        w=bw,
        h=CONTROL_H,
        note=f"T2 (§4.1): aria-disabled, focusable, no hover, variant {variant} when enabled; Enter or Space "
        "changes and sends nothing and re-shows the reason (polite once); no audit, no analytics",
    )
    if focused:
        ctl = ring(ctl)
    if shared or reason is None:
        return dict(ctl, name=name) if name else ctl
    rs = t2_reason(reason, w=w)
    under = hbox("reason row", [rs, beside], {"gap": INSET_SM, "wrap": "wrap"}) if beside else rs
    return vbox(
        name or f"T2 · {chars}",
        [ctl, under],
        {"gap": INSET_XS},
        note="T2 2a: the reason under the control is its aria-describedby (§4.1)",
    )


def t2_notice(reason: str, w: int | None = None, name: str | None = None) -> Node:
    """One shared T2 notice under the header ("one notice, many pointers", §4.1): a CMP-028 info notice holding the
    reason; every control under it points aria-describedby at it."""
    n = k.notice(copy(reason), "info", w=w, name=name or "CMP-028 notice (composition) · T2")
    return dict(
        n,
        note="the shared T2 reason node (§4.1 'one notice, many pointers'), in the DOM at mount, no live role",
    )


def t2_radio(
    label_: str, body: str | None, reason: str, *, w: int = 560, focused: bool = False
) -> Node:
    """A T2 radio (§4.1: arrows focus it and never check it): the lock leading the full label in tertiary, its reason
    the second line."""
    kids = [
        ellipse("ring", 16, 16, {"stroke": T2_LABEL, "strokeWidth": HAIRLINE}),
        lock_glyph(),
        text("label", label_, BODY_STRONG, T2_LABEL),
    ]
    col = [hbox("radio", kids, {"gap": INSET_XS})] + (
        [text("body", body, BODY, TEXT_2, w=w - 24)] if body else []
    )
    col.append(t2_reason(reason))
    n = vbox(
        f"CMP-006 Radio (composition) · {label_} (T2)",
        col,
        {"gap": INSET_XS, "pad": INSET_XS},
        w=w,
        note="T2 radio: role=radio kept, aria-disabled; arrows focus it and never check it (§4.1, §8.1)",
    )
    return ring(n) if focused else n


def busy(chars: str, variant: str = "secondary", focused: bool = False) -> Node:
    """CMP-001 loading (never T2, §4.1): a control whose own job runs, or that waits on a read in flight."""
    return dict(
        busy_button(chars, variant, focused=focused),
        note="CMP-001 loading: aria-busy=true, focusable, no lock (§4.1 'Not T2, said so')",
    )


def validity(chars: str, hint: str | None = None, variant: str = "destructive") -> Node:
    """A confirm waiting on its own inputs (form validity, native `disabled` allowed, §4.1, §12): no lock, no reason;
    the fill dropped to raised with the hairline, the label tertiary, its hint under it when given.
    """
    kids = [text("label", chars, BODY_STRONG, TEXT_3)]
    o: dict[str, Any] = {
        "padX": k.BUTTON_PADX,
        "radius": R_CONTROL,
        "height": k.CONTROL_COMF,
        "justify": "center",
        "fill": RAISED,
        "stroke": BORDER_DEFAULT,
        "strokeWidth": HAIRLINE,
        "strokeAlign": "inner",
    }
    bw = round(est_width(hbox("m", kids)) + 2 * PX[k.BUTTON_PADX] + 2)
    ctl = hbox(
        f"CMP-001 Button (composition) · {chars} (form validity)",
        kids,
        o,
        w=bw,
        h=CONTROL_H,
        note="form validity: native disabled allowed, not T2 (§4.1; §12): enabled once its inputs are valid",
    )
    if not hint:
        return ctl
    return vbox(
        f"{chars} (form validity)", [ctl, text("hint", hint, CAPTION, TEXT_3)], {"gap": INSET_XS}
    )


def marker(label_: str, code: str | None = None) -> Node:
    """CMP-093 "Recorded in the audit log · <label> (<code>)"; code=None: a marker without a code (D37)."""
    return k.marker(label_, code)


def status_word(
    word: str,
    kind: str,
    color: str,
    *,
    typo: str = BODY_STRONG,
    name: str | None = None,
    w: int | None = None,
) -> Node:
    """A word and its glyph (never colour alone, §16 L750-751): the glyph in its strong colour, the word primary."""
    if kind == "ring":
        fallback("NEUTRAL")
    g = step_glyph(kind, color) if kind == "dot" else glyph(kind, color)
    return hbox(
        name or f"status · {word}", [g, text("word", word, typo, TEXT_1, w=w)], {"gap": INSET_XS}
    )


# Health words and glyphs (D2 L117; §16 L732): state -> (glyph, colour).
HEALTH_LOOK = {
    "healthy": ("check", OK_STRONG),
    "degraded": ("triangle", WARN_STRONG),
    "warning": ("triangle", WARN_STRONG),
    "down": ("octagon", DANGER_STRONG),
    "not_deployed": ("ring", NEUTRAL_DEFAULT),
    "stale": ("clock", STALE_IND),
    "not_reported": ("ring", NEUTRAL_DEFAULT),
}
D2_LINE = find_line("| D2  | **Health words are the contract's**")
HEALTH_ORDER = ("healthy", "degraded", "warning", "down", "not_deployed")  # Y:15845-15848 (§1 L99)


def health_word(st: str, **fills: Any) -> str:
    """The word D2 draws for a state: the contract's verbatim, `not_deployed` "Not built yet", "stale since …"."""
    if st == "not_deployed":
        return copy("health.not_deployed")
    if st == "not_reported":
        return copy("health.not_reported")
    if st == "stale":
        return copy("tile.stale", **fills)
    return label(st, D2_LINE, "D2's contract word")


def health_status(st: str, *, name: str | None = None, **fills: Any) -> Node:
    """A health state word with its glyph (D2): check healthy, triangle degraded / warning, octagon down, ring not
    built yet (neutral), clock stale."""
    g, c = HEALTH_LOOK[st]
    return status_word(health_word(st, **fills), g, c, name=name or f"status · {st}")


def stale_chip(since: str | None) -> Node:
    """CMP-239 "stale since {time}" (D6): the clock glyph, stale.text on stale.surface, a 1 px border (§4.3)."""
    kids: list[Node] = [glyph("clock", STALE_IND)]
    kids.append(
        text("words", copy("tile.stale", hh_mm_ss=since), CAPTION, STALE_TEXT)
        if since
        else rich("tile.stale", typo=CAPTION, color=STALE_TEXT, hh_mm_ss=None)
    )
    return hbox(
        "CMP-239 StaleChip (composition)",
        kids,
        {
            "gap": INSET_XS,
            "padX": INSET_SM,
            "radius": R_BADGE,
            "fill": STALE_SURFACE,
            "stroke": STALE_IND,
            "strokeWidth": HAIRLINE,
        },
        h=24,
        note="CMP-239: stale.text on stale.surface (10.69); keeps a 1 px border under forced colours (§4.3)",
    )


def progress(
    pct: int | None, w: int = 160, name: str = "CMP-023 Progress Bar (composition)"
) -> Node:
    """CMP-023 (8 px): the color.surface.hover track (color.track's stand-in) and the action.primary fill; pct=None
    draws the track alone; aria-live off, the '{n} %' text carries it (§13)."""
    fallback("TRACK")
    kids = [rect("track", w, 8, TRACK, {"radius": R_BADGE}, x=0, y=0)]
    if pct is not None:
        kids.append(
            rect(
                "fill",
                max(round(w * pct / 100), 1),
                8,
                ACTION_PRIMARY,
                {"radius": R_BADGE},
                x=0,
                y=0,
            )
        )
    return box(
        name,
        kids,
        None,
        w=w,
        h=8,
        note="role=progressbar; aria-live off; '{n} %' polite at 25 % steps (§13)",
    )


def notice(chars: str, tone: str = "info", w: int | None = None, name: str | None = None) -> Node:
    return k.notice(chars, tone, w=w, name=name)


def banner(
    tone: str,
    node_or_chars: str | Node,
    *,
    title: str | None = None,
    shell: bool = False,
    w: int | None = None,
    name: str | None = None,
) -> Node:
    """A CMP-028 / CMP-092 callout: the tone's subtle fill, its strong glyph, the text primary; node_or_chars may be a
    rich() node (fills as bars, actions as controls)."""
    if isinstance(node_or_chars, str):
        return k.banner(tone, node_or_chars, title=title, shell=shell, w=w, name=name)
    fill_, kind, gcol = k.TONES[tone]
    kids = [
        glyph(kind, gcol),
        vbox(
            "words",
            ([text("title", title, BODY_STRONG, TEXT_1)] if title else []) + [node_or_chars],
            {"gap": STACK_XS},
        ),
    ]
    o = {"gap": INSET_SM, "padX": INSET_LG, "padY": INSET_SM, "fill": fill_, "align": "start"}
    if not shell:
        o["radius"] = R_CARD
    return hbox(
        name or f"CMP-028 Callout (composition) · {tone}",
        kids,
        o,
        w=w,
        hs="fill" if shell else None,
    )


def disclosure(chars: str, open_: bool = False) -> Node:
    """A disclosure button (chevron + label, a CMP-021 link look)."""
    return hbox(
        f"disclosure · {chars}",
        [
            icon("chevron", "chevron-down" if open_ else "chevron-right", TEXT_2),
            text("label", chars, BODY, TEXT_LINK),
        ],
        {"gap": INSET_XS},
        note=f"aria-expanded={'true' if open_ else 'false'}",
    )


# --- Frames, the admin shell with D05's header, the modal, insets.
SCRIM = SUNKEN


def env_badges_above(px: int, env: str = "LIVE") -> list[Node]:
    """The TopBar's and the StatusBar's ENV badges drawn again above a scrim at their chrome places (E42-D04 G-31;
    C-2.11): no scrim or card covers them."""
    g = SIZES[px]
    deviate("modal-env")
    bw = round(est_width(env_badge(env)))
    note(
        "live_checks",
        f"ENV badges above the scrim (frame-{px}): align each over its chrome badge after relayout",
    )
    return [
        dict(
            env_badge(env, name=f"CMP-074 EnvBanner (composition) · {env} · above the scrim"),
            x=PX[INSET_LG] + 88 + PX[INSET_MD],
            y=round((g.top - k.ENV_H) / 2),
            abs=True,
        ),
        dict(
            env_badge(env, name=f"CMP-075 EnvBadgeLocal (composition) · {env} · above the scrim"),
            x=g.w - PX[INSET_LG] - bw,
            y=g.h - g.status + round((g.status - k.ENV_H) / 2),
            abs=True,
        ),
    ]


def modal(px: int, dialog_node: Node, *, env: str = "LIVE", fill: bool = False) -> list[Node]:
    """The modal layer for shell(overlays=…): the scrim (black at opacity.scrim; bound color.surface.sunken, dark
    only), the dialog centred (fill=True: §4.2's 200 % rule, the area between the bars), then the ENV badges above.
    """
    g = SIZES[px]
    fallback("SCRIM")
    sc = rect(
        "scrim",
        g.w,
        g.h,
        SCRIM,
        {"opacity": OPACITY_SCRIM},
        x=0,
        y=0,
        abs=True,
        note="black at opacity.scrim, no blur (E09-D08 D2)",
    )
    dw, dh = est_width(dialog_node), est_height(dialog_node)
    if fill:
        dlg = dict(dialog_node, x=0, y=g.top, w=g.w, h=g.h - g.top - g.status, abs=True)
    else:
        dlg = dict(
            dialog_node, x=round((g.w - dw) / 2), y=round(max((g.h - dh) / 2, g.top)), abs=True
        )
        note(
            "live_checks",
            f"modal: centre '{dialog_node['name']}' in frame-{px} after relayout (estimated "
            f"{dw:.0f} x {dh:.0f} px)",
        )
    return [
        box(
            "overlay",
            [sc, dlg, *env_badges_above(px, env)],
            None,
            w=g.w,
            h=g.h,
            x=0,
            y=0,
            abs=True,
            note="the modal layer: scrim, dialog, then the ENV badges above both",
        )
    ]


def page_head(
    px: int,
    h1: str,
    *,
    meta: Node | str | None = None,
    primary: Iterable[Node] = (),
    extra: Iterable[Node] = (),
) -> Node:
    """CMP-088 PageHeader (D05's form): the h1, the meta line (default meta.asof 14:02:11) which may carry a control
    ([Re-read], ruling Q10), the primary actions at the end, and lines under it (extra: the overall line…).
    """
    if meta is None:
        meta = k.copy("meta.asof", hhmmss="14:02:11")
        note("copy_keys", "meta.asof")
    mnode = (
        text("meta", meta, CAPTION, TEXT_3) if isinstance(meta, str) else dict(meta, name="meta")
    )
    titles = vbox(
        "titles", [text("h1", h1, HEADING_MD, TEXT_1, note="the h1"), mnode], {"gap": STACK_SM}
    )
    prim = list(primary)
    top = hbox(
        "top",
        [titles] + ([hbox("primary actions", prim, {"gap": INSET_SM})] if prim else []),
        {"justify": "space-between", "align": "end"},
        w=SIZES[px].inner,
    )
    return vbox(
        "CMP-088 PageHeader (composition)",
        [top, *extra],
        {"padY": INSET_LG, "gap": STACK_SM},
        w=SIZES[px].inner,
    )


def _find(n: Node, name: str) -> tuple[Node, int] | None:
    for i, kid in enumerate(n.get("kids") or []):
        if kid["name"] == name:
            return n, i
        hit = _find(kid, name)
        if hit:
            return hit
    return None


def admin_frame(
    px: int,
    *,
    route: str,
    h1: str,
    head: Node | None = None,
    content: Iterable[Node] = (),
    banners: Iterable[Node] = (),
    overlays: Iterable[Node] = (),
    items: Iterable[Node] = (),
    insets: Iterable[Node] = (),
    name: str | None = None,
    env: str = "LIVE",
) -> Node:
    """A CMP-087 admin frame (E42-D03's shell, reused) at px: band "◆ Admin area · <route>", the strip (items), the
    PageHeader (head= replaces e42kit's with page_head()'s), the content, the footer marker, banners in the shell slot,
    overlays (modal()) and insets on top."""
    deviate("shell")
    fr = k.shell(
        px,
        route=route,
        h1=h1,
        content=content,
        banners=banners,
        overlays=overlays,
        items=items,
        name=name,
        env=env,
    )
    if head is not None:
        hit = _find(fr, "CMP-088 PageHeader (composition)")
        assert hit, "e42kit shell without a PageHeader"
        parent, i = hit
        parent["kids"][i] = head
    for ins in insets:
        fr["kids"].append(ins)
    return fr


def plain_frame(
    px: int, kids: Iterable[Node], *, name: str | None = None, center: bool = True
) -> Node:
    """A frame outside the admin shell (SCR-017, the invitee's pages before any session): app surface, content
    centred, no chrome."""
    g = SIZES[px]
    o: dict[str, Any] = {"fill": APP, "clip": True, "pad": INSET_XL, "gap": STACK_LG}
    if center:
        o.update(align="center", justify="center")
    return vbox(name or f"frame-{px}", kids, o, w=g.w, h=g.h)


def inset(
    px: int, sid: str, what: str, kids: Iterable[Node], *, w: int = 480, corner: str = "br"
) -> Node:
    """An inset inside its frame (§0: 'insets sit inside the frame §0 names them on'): an absolute card at a corner,
    titled 'Inset · <sid> — <what>', raised with a color.border.default hairline and elevation.popover.
    """
    deviate("insets")
    g = SIZES[px]
    ks = [text("title", f"Inset · {sid} — {what}", LABEL, TEXT_2, w=w - 2 * PX[INSET_LG]), *kids]
    card = vbox(
        f"inset · {sid} · {_safe(what)}",
        ks,
        {
            "fill": RAISED,
            "radius": R_CARD,
            "pad": INSET_LG,
            "gap": STACK_SM,
            "stroke": BORDER_DEFAULT,
            "strokeWidth": HAIRLINE,
            "shadow": k.E_POPOVER,
        },
        w=w,
        note=f"inset {sid}: not a frame (§0); placed over the frame's content",
    )
    h = est_height(card)
    x = g.w - w - PX[INSET_LG] - g.right if corner in ("br", "tr") else g.nav + PX[INSET_LG]
    y = g.h - g.status - h - PX[INSET_LG] if corner in ("br", "bl") else g.top + 160
    note(
        "live_checks",
        f"inset '{card['name']}' (frame-{px}): estimated {w} x {h:.0f} px at ({x}, {y:.0f}); after "
        "relayout keep it inside the frame above the StatusBar",
    )
    return dict(card, x=x, y=max(round(y), g.top), abs=True)


def at(fr: Node, f: F) -> Node:
    """A built frame renamed for its board: '<state id>[ · tag] · <size> [<old>]' (frame_name)."""
    return dict(fr, name=frame_name(f))


def marker_line(label_: str | None, code: str | None) -> Node:
    """A CMP-093 marker; label_=None draws the label as a bar (no source names it), code=None a marker without a code
    (D37)."""
    if label_ is not None:
        return marker(label_, code)
    kids: list[Node] = [
        text("lead", "Recorded in the audit log ·", CAPTION, TEXT_3),
        bar("marker label", 96),
    ]
    if code:
        kids.append(text("code", f"({code})", CAPTION, TEXT_3))
    return hbox("CMP-093 AuditActionTrigger marker (composition)", kids, {"gap": INSET_XS})


# --- §1 worked example (L83-95): the clocks, the cast and the data every frame uses.
AS_OF, AS_OF_144 = "14:02:11", "14:06:02"  # SCR-144's boards read 14:06:02 (§1 L87-88)
DATE = "2026-10-22"
L_EXAMPLE = find_line("**Worked example (every frame).**")


class Comp(NamedTuple):
    name: str
    state: str = "healthy"
    probe: int | None = None  # ms; None = not given (a bar), the report carries it
    detail: str | None = None
    last_good: str | None = None


COMPONENTS = tuple(
    kk.split(".", 2)[2] for kk in COPY if kk.startswith("health.label.")
)  # §15 L707's order (DJ:
# the server order is not given; this is the deck's order)
NO_PROBE = ("disk", "secrets")  # §5 L254-255: no probe line for disk and secrets (DJ)
EXAMPLE_HEALTH = {  # §1 L84-86 (Y:10069-10136): the two non-healthy components and their words
    "bybit_private_ws": Comp(
        "bybit_private_ws",
        "degraded",
        210,
        "account a1000000… reconnected 3× in the last hour",
        "14:01:40",
    ),
    "disk": Comp("disk", "warning", None, "30% free; projected full 2027-02-11"),
}


def health_set(
    overrides: dict[str, Comp | str] | None = None, *, example: bool = False
) -> list[Comp]:
    """Every component (COMPONENTS order) healthy, plus §1's two (example=True) and the overrides (a Comp or a state
    word)."""
    out = []
    for nm in COMPONENTS:
        c = EXAMPLE_HEALTH.get(nm, Comp(nm)) if example else Comp(nm)
        o = (overrides or {}).get(nm)
        if isinstance(o, str):
            c = c._replace(state=o)
        elif isinstance(o, Comp):
            c = o
        out.append(c)
    return out


def overall_state(comps: Iterable[Comp]) -> str:
    """The worst state (Y:10061): down > degraded / warning > healthy; not_deployed ranks healthy."""
    rank = {"down": 3, "degraded": 2, "warning": 2, "healthy": 0, "not_deployed": 0}
    return max(comps, key=lambda c: rank.get(c.state, 0)).state if comps else "healthy"


def comp_label(nm: str) -> str:
    """'{plain label} ({name})' (D4)."""
    return f"{copy(f'health.label.{nm}')} ({nm})"


def health_tile(
    px: int,
    c: Comp,
    *,
    col: int = 0,
    numbers: str = "live",
    asof: str = AS_OF,
    stale_since: str | None = "bar",
    safe: bool = True,
    retry: bool = False,
    history: bool = False,
    w: int | None = None,
) -> Node:
    """A CMP-178 tile (D3, D4, D9; §5 L252-256): role=region labelled by its heading link "{plain label} ({name})";
    the state word and glyph; "probe {n} ms" (none for disk and secrets); the server's detail; "as of" / "last good";
    for a degraded, warning or down state what stops (stops.<name>.<state>), health.safe (safe=False: withheld, D9),
    the hint and "Runbook →"; the history disclosure. numbers: "live" (the report's), "stale" (kept with CMP-239
    'stale since', HL-11 / HL-14), "none" ("— not received", HL-12)."""
    tw = w or TILE_W[px][col % len(TILE_W[px])]
    inner = tw - 2 * PX[INSET_LG]
    kids: list[Node] = [link(comp_label(c.name), HEADING_SM, name="heading")]
    if c.state == "degraded" and c.detail:
        st = hbox(
            "status",
            [
                glyph("triangle", WARN_STRONG),
                text(
                    "word",
                    copy("tile.degraded", detail=c.detail),
                    BODY_STRONG,
                    TEXT_1,
                    w=inner - 24,
                ),
            ],
            {"gap": INSET_XS, "align": "start"},
        )
    else:
        st = health_status(c.state)
    kids.append(st)
    if c.state not in ("not_deployed", "down") and c.name not in NO_PROBE:
        if numbers == "none":
            kids.append(words("health.not_received", BODY, TEXT_2, name="probe"))
        else:
            kids.append(rich("health.probe", typo=BODY, color=TEXT_2, name="probe", n=c.probe))
    if c.detail and c.state != "degraded":
        kids.append(text("detail", c.detail, BODY, TEXT_1, w=inner))
    stamps: list[Node] = []
    if c.state in ("down", "degraded") and c.last_good:
        stamps.append(
            text("last good", copy("tile.last_good", hh_mm_ss=c.last_good), CAPTION, TEXT_3)
        )
    elif c.state == "down":
        stamps.append(
            rich("tile.last_good", typo=CAPTION, color=TEXT_3, name="last good", hh_mm_ss=None)
        )
    else:
        stamps.append(text("as of", copy("tile.asof", hh_mm_ss=asof), CAPTION, TEXT_3))
    if numbers == "stale":
        stamps.append(stale_chip(None if stale_since == "bar" else stale_since))
    kids.append(hbox("stamps", stamps, {"gap": INSET_SM, "wrap": "wrap"}))
    if c.state in ("degraded", "warning", "down"):
        sk = f"stops.{c.name}.{c.state}"
        if sk in COPY:
            kids.append(words(sk, BODY, TEXT_1, w=inner, name="what stops"))
        else:
            note(
                "spec_gaps",
                f"{sk}: §15 L708 gives no sentence for {c.name} {c.state}: the tile draws none",
            )
        if safe:
            kids.append(words("health.safe", BODY, TEXT_1, w=inner, name="still safe"))
        else:
            note(
                "deviations",
                "health.safe withheld (D9): never reworded, the tile simply has no 'still safe' line",
            )
        hk = f"hint.{c.name}" if f"hint.{c.name}" in COPY else "hint.default"
        kids.append(words(hk, BODY, TEXT_2, w=inner, name="what to do"))
        kids.append(link(copy("health.runbook"), name="runbook"))
    if retry:
        kids.append(button("Retry", "secondary"))
    kids.append(_history_disclosure(history))
    return vbox(
        f"CMP-178 SystemHealthTile (composition) · {c.name}",
        kids,
        {"fill": RAISED, "radius": R_CARD, "pad": INSET_LG, "gap": STACK_SM},
        w=tw,
        note='role="region" aria-labelledby its heading link (D3, D4); words from frames, numbers from the '
        "report only (D5); no number for a field not received (D02 D4)",
    )


L_HISTORY = find_line("the history disclosure (D13)")


def _history_disclosure(open_: bool) -> Node:
    """The tile's history disclosure (D13): a chevron and the label; the label has no §15 key (a bar)."""
    note(
        "copy_gaps",
        f"the tile's history disclosure (§5 L{L_HISTORY}, D13) has no label in §15: drawn as a bar",
    )
    return hbox(
        "history disclosure",
        [
            icon("chevron", "chevron-down" if open_ else "chevron-right", TEXT_2),
            bar("history disclosure label", 64),
        ],
        {"gap": INSET_XS},
        note=f"aria-expanded={'true' if open_ else 'false'}; opens the sparkline and its table (D13)",
    )


L_CLIENT = find_line('tile "Chart engine (this session)"')


def client_tile(px: int, engine: bool = True, *, col: int = 0, w: int | None = None) -> Node:
    """The client tile "Chart engine (this session)" (D4): "60 fps · frame p95 12 ms" (HL-2) measured in this window,
    or "No chart open in this window" (neutral, no number)."""
    tw = w or TILE_W[px][col % len(TILE_W[px])]
    head = label("Chart engine (this session)", L_CLIENT)
    kids: list[Node] = [text("heading", head, HEADING_SM, TEXT_1)]
    if engine:
        kids.append(
            text(
                "value",
                label("60 fps · frame p95 12 ms", STATES["HL-2"].line, "HL-2's measured value"),
                NUM_BASE,
                TEXT_1,
                note='accessible name "60 frames per second, 95th-percentile frame time 12 milliseconds" '
                "(§13)",
            )
        )
    else:
        kids.append(
            status_word(copy("health.client_none"), "ring", NEUTRAL_DEFAULT, name="no engine")
        )
    return vbox(
        "CMP-178 SystemHealthTile (composition) · client",
        kids,
        {"fill": RAISED, "radius": R_CARD, "pad": INSET_LG, "gap": STACK_SM},
        w=tw,
        note="measured in the browser only while a chart engine runs in this window, per window, never "
        "aggregated (D4)",
    )


def tile_grid(px: int, tiles: list[Node]) -> Node:
    """The D1 grid: three columns at 1280 (≈307 px), five at 2560 (400 px), space.3 gaps; rows top-aligned."""
    n = len(TILE_W[px])
    rows = []
    for r in range(0, len(tiles), n):
        chunk = [dict(t, w=TILE_W[px][i]) for i, t in enumerate(tiles[r : r + n])]
        rows.append(hbox(f"row-{r // n + 1}", chunk, {"gap": STEP, "align": "start"}))
    return vbox(
        "tile grid",
        rows,
        {"gap": STEP},
        w=SIZES[px].inner,
        note="D1: tiles in server order; each tile resolves alone (D5); no page spinner",
    )


L_BUILD = find_line("CMP-207 build line")


def build_line() -> Node:
    """CMP-207 "{version} · {git_sha} · {environment} · up {uptime}" (E04:233): every value a bar (none is given)."""
    label(
        "{version} · {git_sha} · {environment} · up {uptime}", L_BUILD + 1, "the CMP-207 build line"
    )
    kids = [
        bar("version", 48),
        text("s1", "·", CAPTION, TEXT_3),
        bar("git_sha", 56),
        text("s2", "·", CAPTION, TEXT_3),
        bar("environment", 40),
        text("s3", "· up", CAPTION, TEXT_3),
        bar("uptime", 48),
    ]
    return hbox("CMP-207 BuildInfo (composition)", kids, {"gap": INSET_XS})


L_ANATOMY_143 = find_line("**Anatomy, top to bottom (both sizes).**")


def overall_line(
    px: int,
    word_state: str | None,
    *,
    asof: str = AS_OF,
    open_n: int | None = None,
    unavailable: str | None = None,
    failed: bool = False,
    retry_focus: bool = False,
) -> Node:
    """The overall line and the incidents link (D10): "Overall: {word} · as of {hh:mm:ss} (last health frame)" and
    "Incidents ({n} open) →"; unavailable= HL-15's "Unavailable — {detail}" in its place; failed=True adds
    health.report_failed + [Retry] under it (HL-11, HL-12, HL-14)."""
    if unavailable is not None:
        first: Node = rich(
            "tile.unavailable", name="overall", detail=None if unavailable == "bar" else unavailable
        )
    else:
        assert word_state
        first = words(
            "health.overall",
            BODY_STRONG,
            TEXT_1,
            name="overall",
            word=health_word(word_state),
            hh_mm_ss=asof,
        )
    inc = rich("health.incidents", typo=BODY, color=TEXT_LINK, name="incidents link", n=open_n)
    kids = [hbox("overall row", [first, inc], {"gap": INSET_LG, "wrap": "wrap"})]
    if failed:
        kids.append(
            rich(
                "health.report_failed",
                w=SIZES[px].inner,
                detail=None,
                focus="Retry" if retry_focus else None,
            )
        )
    return vbox(
        "overall line",
        kids,
        {"gap": STACK_SM},
        note="overall = the worst state (Y:10061); the incidents count from status=open (D10)",
    )


def reread_meta(asof: str = AS_OF) -> Node:
    """The meta line "All times UTC · as of {hh:mm:ss}" with [Re-read] (ruling Q10)."""
    note("copy_keys", "meta.asof")
    return hbox(
        "meta",
        [
            text("words", k.copy("meta.asof", hhmmss=asof), CAPTION, TEXT_3),
            link(copy("health.reread"), CAPTION, name="Re-read"),
        ],
        {"gap": INSET_SM},
        note="[Re-read]: one re-read of D5's reads, never a timer (D6)",
    )


def scr143(
    px: int,
    sid: str,
    *,
    comps: list[Comp] | None = None,
    numbers: str = "live",
    safe: bool = True,
    banner_down: bool = False,
    e17: bool = False,
    export_t2: bool = False,
    failed: bool = False,
    unavailable: str | None = None,
    engine: bool = True,
    overlays: Iterable[Node] = (),
    insets: Iterable[Node] = (),
    open_n: int | None = None,
) -> Node:
    """An SCR-143 frame (§5): the shell "◆ Admin area · System health", the h1, meta with [Re-read], [Export
    diagnostics…] (T2 admin.server_unreachable when export_t2), the overall line and the incidents link, the CMP-092
    outage banner (banner_down), the tile grid, the client tile, the build line, the footer marker. Presets by state
    id: see SCR143_PRESETS (HL-2, HL-5, HL-6, HL-11, HL-12, HL-14, HL-18, HL-20)."""
    state(sid)
    src(f"SCR-143 anatomy: E42-D05 §5 L{L_ANATOMY_143}-{L_ANATOMY_143 + 12}")
    comps = comps or health_set()
    exp_label = label("Export diagnostics…", L_ANATOMY_143 + 2, "the primary action")
    prim = (
        t2(exp_label, "admin.server_unreachable") if export_t2 else button(exp_label, "secondary")
    )
    head = page_head(
        px,
        label("System health", L_ANATOMY_143 + 1, "the h1"),
        meta=reread_meta(),
        primary=[prim],
        extra=[
            overall_line(
                px, overall_state(comps), open_n=open_n, unavailable=unavailable, failed=failed
            )
        ],
    )
    content: list[Node] = []
    if banner_down:
        down = [copy(f"health.label.{c.name}") for c in comps if c.state == "down"]
        bkids = [
            words(
                "health.banner_down", BODY, TEXT_1, labels=", ".join(down), w=SIZES[px].inner - 64
            )
        ]
        if safe:
            bkids.append(words("health.safe", BODY, TEXT_1, name="still safe"))
        bkids.append(rich("health.incidents", color=TEXT_LINK, name="incidents link", n=open_n))
        content.append(
            hbox(
                "CMP-092 OutageBanner (composition)",
                [glyph("octagon", DANGER_STRONG), vbox("words", bkids, {"gap": STACK_XS})],
                {
                    "gap": INSET_SM,
                    "padX": INSET_LG,
                    "padY": INSET_SM,
                    "fill": DANGER_SUBTLE,
                    "radius": R_CARD,
                    "align": "start",
                },
                w=SIZES[px].inner,
                note='CMP-092 static role="status": what is down and what still works (D11)',
            )
        )
    tiles = [health_tile(px, c, col=i, numbers=numbers, safe=safe) for i, c in enumerate(comps)]
    tiles.append(client_tile(px, engine))
    content += [tile_grid(px, tiles), build_line()]
    banners = [e17_banner(px)] if e17 else []
    return admin_frame(
        px,
        route=label("System health", L_ANATOMY_143 + 1),
        h1="System health",
        head=head,
        content=content,
        banners=banners,
        overlays=overlays,
        insets=insets,
        name=f"frame-{px}",
    )


def e17_banner(px: int) -> Node:
    """E17's transport banner (SCR-152; HL-13, HL-14), its title, body and actions as E17-D01:154 gives them."""
    note("copy_keys", "e17.banner.title")
    note("copy_keys", "e17.banner.body")
    src("E17-D01:154 (SCR-152 Disconnected banner), :102 (CMP-076 chip)")
    return k.banner(
        "danger",
        INHERITED["e17.banner.body"][0],
        title=INHERITED["e17.banner.title"][0],
        actions=[button("Retry now", "secondary"), link("Details")],
        shell=True,
        name="SCR-152 Disconnected banner (E17, composition)",
        note="E17's banner, not D05's: [Retry now] [Details] are E17-D01:154's",
    )


def export_dialog(px: int) -> list[Node]:
    """HL-18 (§12: rung 1, no step-up): health.export.title, From / To in UTC (default the last 24 h), the body, the
    marker health.diagnostics_exported, [Cancel] (focused) [Export diagnostics]. Returns modal() overlays.
    """
    state("HL-18")
    frm = field("From (UTC)", "2026-10-21 14:02", w=200, mono=True)
    to = field("To (UTC)", "2026-10-22 14:02", w=200, mono=True)
    note(
        "deviations",
        "HL-18: From / To show the default last 24 h derived from §1's 14:02:11 (D14); the field "
        "labels 'From (UTC)' / 'To (UTC)' and the confirm label are the kit's (no §15 key)",
    )
    dlg = dialog(
        copy("health.export.title"),
        [
            hbox("window", [frm, to], {"gap": INSET_LG}),
            words("health.export.body", BODY, TEXT_1, w=592),
            marker_line(None, "health.diagnostics_exported"),
        ],
        [ring(button("Cancel", "secondary")), button(copy("health.export.title"), "primary")],
        size="large",
        role="dialog",
    )
    return modal(px, dlg)


# --- SCR-144 (§6): incidents.
class Incident(NamedTuple):
    component: str
    title: str | None  # None: not given (a bar)
    severity: str  # "error" | "critical" | "" (not given)
    status: str  # open | acknowledged | resolved
    occurrences: int | None = None
    safety: str = ""  # "chain" (D04's audit_chain_break) | "break_glass" (D03 OV-10)


INCIDENTS = (  # §1 L86-88: the open private-WS storm, a resolved recorder gap, D04's chain break, D03's break-glass row
    Incident("bybit_private_ws", "reconnect storm", "error", "open", 3),
    Incident("audit_chain_break", None, "critical", "open", None, "chain"),
    Incident("break_glass", None, "", "acknowledged", None, "break_glass"),
    Incident("recorder", None, "", "resolved"),
)
SEVERITY_LOOK = {"error": ("octagon", DANGER_STRONG), "critical": ("octagon", DANGER_STRONG)}
L_ANATOMY_144 = find_line('- **Anatomy.** The shell "◆ Admin area · Incidents"')


def incident_cols(px: int) -> list[tuple[str, str, int]]:
    """(id, header, width) for §6's columns at px (Time · Subsystem · Severity · Message · Duration · Resolution ·
    the Acknowledge cell; a disclosure first); widths are the kit's."""
    w = SIZES[px].inner
    base = [
        ("disclosure", "", 32),
        ("time", "Time", 168),
        ("subsystem", "Subsystem", 136),
        ("severity", "Severity", 104),
        ("message", "Message", 0),
        ("duration", "Duration", 128),
        ("resolution", "Resolution", 152),
        ("ack", "", 168),
    ]
    fixed = sum(c[2] for c in base)
    return [(i, h, (w - fixed) if i == "message" else cw) for i, h, cw in base]


def grid_table(
    cols: list[tuple[str, str, int]],
    rows: list[dict[str, Any]],
    *,
    name: str = "CMP-049 Table",
    caption: str | None = None,
    selected: int | None = None,
) -> Node:
    """A CMP-049 table composition: optional caption, the header row on color.surface.hover (type.ui.label,
    secondary), rows on raised with a color.border.subtle hairline, cells growing with their content (no fixed row
    height, so wrapped messages and 2a reasons fit)."""
    kids: list[Node] = []
    if caption:
        kids.append(text("caption", caption, CAPTION, TEXT_2))
    hdr = [
        hbox(i, [text("label", h, LABEL, TEXT_2)] if h else [], {"padX": INSET_SM}, w=cw, h=ROW_H)
        for i, h, cw in cols
    ]
    kids.append(hbox("header", hdr, {"fill": HOVER}, h=ROW_H))
    for r, cells in enumerate(rows, 1):
        ck = []
        for i, _h, cw in cols:
            v = cells.get(i)
            inner = (
                []
                if v is None
                else (
                    [text("value", v, BODY, TEXT_1, w=cw - 16)]
                    if isinstance(v, str)
                    else ([dict(n) for n in v] if isinstance(v, list) else [dict(v)])
                )
            )
            ck.append(vbox(i, inner, {"padX": INSET_SM, "padY": INSET_SM, "gap": INSET_XS}, w=cw))
        fill_ = SELECTED if selected == r else RAISED
        kids.append(
            hbox(
                cells.get("_name", f"row-{r:02d}"),
                ck,
                {
                    "fill": fill_,
                    "align": "start",
                    "stroke": BORDER_SUBTLE,
                    "strokeWidth": HAIRLINE,
                    "strokeAlign": "inner",
                },
                w=sum(c[2] for c in cols),
            )
        )
    return vbox(f"{name} (composition)", kids, None, w=sum(c[2] for c in cols))


def severity_cell(sev: str) -> Node:
    """Severity as word + glyph (§6); a severity §1 does not give is a bar."""
    if not sev:
        return bar("severity", 48)
    g, c = SEVERITY_LOOK[sev]
    return status_word(
        sev, g, c, typo=BODY_STRONG if sev == "critical" else BODY, name=f"severity · {sev}"
    )


def incident_row(
    px: int,
    inc: Incident,
    cols: list[tuple[str, str, int]],
    *,
    ack_state: str = "button",
    expanded: bool = False,
) -> dict[str, Any]:
    """One SCR-144 row's cells: Time "{first seen} · last {hh:mm}" (bars), Subsystem, Severity (word + glyph),
    Message (title, wrapping; a bar where §1 gives none), Duration ("… so far" while open or acknowledged), Resolution
    (octagon "Open", clock "Acknowledged {time}", check "Resolved {time}"), and [Acknowledge] on open rows, else its
    outcome line (D18). ack_state: "button" | "acking"."""
    cw = {i: w for i, _h, w in cols}
    open_like = inc.status in ("open", "acknowledged")
    res = {
        "open": status_word("Open", "octagon", DANGER_STRONG, name="resolution · open"),
        "acknowledged": hbox(
            "resolution · acknowledged",
            [
                glyph("clock", STALE_IND),
                text("w", "Acknowledged", BODY, TEXT_1),
                bar("acknowledged time", 40),
            ],
            {"gap": INSET_XS},
        ),
        "resolved": hbox(
            "resolution · resolved",
            [
                glyph("check", OK_STRONG),
                text("w", "Resolved", BODY, TEXT_1),
                bar("resolved time", 40),
            ],
            {"gap": INSET_XS},
        ),
    }[inc.status]
    if inc.status == "open":
        if ack_state == "acking":
            ack: Node = words("incident.acking", BODY, TEXT_2, name="acking")
        else:
            ack = button("Acknowledge", "secondary")
            ack = dict(
                ack, note=f'accessible name "Acknowledge: {inc.title or "{title}"}" (D02:516)'
            )
            if inc.safety == "chain":
                ack = vbox(
                    "acknowledge + chain note",
                    [ack, words("incident.ack_chain_break", CAPTION, TEXT_2, w=cw["ack"] - 16)],
                    {"gap": INSET_XS},
                )
    elif inc.status == "acknowledged":
        ack = rich(
            "incident.acked.unnamed",
            typo=CAPTION,
            color=TEXT_2,
            w=cw["ack"] - 16,
            name="outcome line",
            yyyy_mm_dd_hh_mm=None,
        )
    else:
        ack = rich(
            "incident.resolved",
            typo=CAPTION,
            color=TEXT_2,
            w=cw["ack"] - 16,
            name="outcome line",
            yyyy_mm_dd_hh_mm=None,
        )
    dur = rich(
        "incident.duration.open" if open_like else "incident.duration",
        typo=NUM_BASE,
        name="duration",
        h=None,
        m=None,
    )
    msg: Node = (
        text("value", inc.title, BODY, TEXT_1, w=cw["message"] - 16)
        if inc.title
        else bar("title", 120)
    )
    sub = (
        text("value", inc.component, NUM_SM, TEXT_1)
        if inc.component not in ("break_glass",)
        else bar("component", 72)
    )
    return {
        "_name": f"row · {inc.component}",
        "disclosure": icon("chevron", "chevron-down" if expanded else "chevron-right", TEXT_2),
        "time": rich("incident.time", typo=NUM_BASE, name="time", first_seen=None, hh_mm=None),
        "subsystem": sub,
        "severity": severity_cell(inc.severity),
        "message": msg,
        "duration": dur,
        "resolution": res,
        "ack": ack,
    }


L_SEGMENTED = L_ANATOMY_144 + 1


def segmented(selected: str = "Open") -> Node:
    """The status filter: a CMP-003 segmented control Open · Acknowledged · Resolved · All (a radio group)."""
    opts = ["Open", "Acknowledged", "Resolved", "All"]
    label("Open · Acknowledged · Resolved · All", L_SEGMENTED, "the segmented control")
    kids = []
    for o in opts:
        sel = o == selected
        kids.append(
            hbox(
                o,
                [text("label", o, BODY_STRONG if sel else BODY, TEXT_1)],
                {"padX": INSET_MD, "radius": R_CONTROL, **({"fill": SELECTED} if sel else {})},
                h=CONTROL_H - 4,
                note="aria-checked=true" if sel else None,
            )
        )
    return hbox(
        "CMP-003 SegmentedControl (composition) · status",
        kids,
        {"gap": INSET_XS, "pad": INSET_XS, "fill": HOVER, "radius": R_CONTROL},
        note="a radio group: arrows move and select (§6 Keys)",
    )


def incident_filters(px: int) -> Node:
    """The filter row (Subsystem, Severity, From–To) and [Export], T2 under one notice (D16, IL-9)."""
    kids = [
        t2("Subsystem", None, shared=True),
        t2("Severity", None, shared=True),
        t2("From–To", None, shared=True),
        t2("Export", None, shared=True),
    ]
    return vbox(
        "filters",
        [
            t2_notice("admin.filters_export_not_built", w=SIZES[px].inner),
            hbox("filter row", kids, {"gap": INSET_SM}),
        ],
        {"gap": STACK_SM},
    )


def scr144(
    px: int,
    sid: str = "IL-2",
    *,
    incidents: Iterable[Incident] = INCIDENTS,
    filter_: str = "All",
    expanded: str | None = None,
) -> Node:
    """An SCR-144 frame (§6): the shell "◆ Admin area · Incidents", h1 "Incidents", meta "as of 14:06:02", the
    segmented control, the filter row and Export T2 under one notice (D16), the CMP-049 table captioned
    incident.caption with the scope line, [Load more], the footer marker."""
    state(sid)
    src(f"SCR-144 anatomy: E42-D05 §6 L{L_ANATOMY_144}-{L_ANATOMY_144 + 10}")
    cols = incident_cols(px)
    rows = [incident_row(px, i, cols, expanded=(i.component == expanded)) for i in incidents]
    tbl = grid_table(cols, rows, name="CMP-049 Table · incidents", caption=copy("incident.caption"))
    note(
        "live_checks",
        "SCR-144 table: virtualised CMP-049 keeps aria-rowindex (§6 L337-338); an APG grid (one tab "
        "stop)",
    )
    content = [
        hbox("status and filters", [segmented(filter_)], {"gap": INSET_LG}),
        incident_filters(px),
        words("incident.scope", CAPTION, TEXT_2, name="scope"),
        tbl,
        button(label("Load more", L_ANATOMY_144 + 8, "the pager"), "secondary"),
    ]
    head = page_head(
        px,
        label("Incidents", L_ANATOMY_144 + 1, "the h1"),
        meta=k.copy("meta.asof", hhmmss=AS_OF_144),
    )
    note("copy_keys", "meta.asof")
    return admin_frame(
        px, route="Incidents", h1="Incidents", head=head, content=content, name=f"frame-{px}"
    )


# --- The annotation column (outside the frames): per state a group, the focus overlay, the board block, the footer.
_MARK: dict[str, int] = {}


def mark() -> None:
    """Start a state group: annotation defaults (copy keys, tokens) count what is recorded after this call."""
    _MARK.update({kd: len(LOG.notes.get(kd, [])) for kd in ("copy_keys", "tokens", "fallbacks")})


def _since(kind: str) -> list[str]:
    return LOG.notes.get(kind, [])[_MARK.get(kind, 0) :]


def ann_text(name: str, chars: str, typo: str = BODY, color: str = TEXT_1) -> Node:
    return text(name, chars, typo, color, w=ANN_TEXT_W)


def ann_block(lab: str, values: Iterable[str], name: str | None = None) -> Node:
    vals = [v for v in values if v]
    return vbox(
        name or f"block · {_safe(lab)[:40]}",
        [ann_text("label", lab, LABEL, TEXT_2)]
        + [ann_text(f"value-{i}", v) for i, v in enumerate(vals, 1)],
        {"gap": STACK_XS},
        w=ANN_TEXT_W,
    )


ANN_ORDER = (
    ("source", "Source (operation, mount state, budget)"),
    ("state", "State id and trigger"),
    ("decisions", "Decision ids"),
    ("roles", "Roles"),
    ("keyboard", "Keyboard path and focus"),
    ("announcement", "Announcement"),
    ("copy", "Copy keys"),
    ("tokens", "Tokens"),
    ("events", "Analytics and audit events"),
)
SCREEN_OF = {
    "HL": "SCR-143",
    "IL": "SCR-144",
    "BK": "SCR-146",
    "RW": "restore",
    "WZ": "wizard",
    "IW": "wizard",
    "GV": "SCR-062",
    "SI": "inspector",
}
ROLES = {
    "SCR-143": "Owner only; a typed URL for anyone else is SCR-155 (D02 D6)",
    "SCR-144": "Owner only (M:135-146)",
    "SCR-146": "Owner only (backups:read / backups:write)",
    "restore": "Owner only (backups:write, rung 4)",
    "wizard": "Owner (the owner's wizard); the invitee on SCR-017 (no session until done)",
    "SCR-062": "Owner (accounts:write + risk_caps step-up); managers see the picker only (GV-7)",
    "inspector": "Owner (admin:read; the acknowledge rung 4)",
}


def ann_group(
    sid: str,
    frames: Iterable[Node | str],
    blocks: dict[str, Any] | None = None,
    *,
    heading: str | None = None,
    insets: Iterable[str] = (),
) -> Node:
    """One state's annotation group: heading (id, name, old board), its frames, then the blocks in ANN_ORDER. Defaults
    from the parsed state row: state and trigger (When), announcement, copy keys (the row's plus every key recorded
    since mark()), tokens (recorded since mark()), source (the row's line), roles (ROLES) and events (the screen's
    events paragraph); pass decisions= and keyboard= (or override any)."""
    st = STATES.get(sid)
    b = dict(blocks or {})
    if st:
        scr = SCREEN_OF[sid.split("-")[0]]
        b.setdefault("source", f"E42-D05 L{st.line} ({sid}); {st.board}")
        b.setdefault("state", f"{sid} {st.name} — when: {st.when}")
        b.setdefault("announcement", st.announce)
        b.setdefault("roles", ROLES[scr])
        ev, ln = events_text(scr)
        b.setdefault("events", f"{ev} (L{ln})")
    if "copy" not in b:
        b["copy"] = ", ".join(
            dict.fromkeys(
                ([st.copy_keys] if st and st.copy_keys != "—" else []) + _since("copy_keys")
            )
        )
    if "tokens" not in b:
        b["tokens"] = k.tokens_line(_since("tokens"))
    kids = [
        ann_text("heading", heading or (f"{sid} · {st.name}" if st else sid), HEADING_SM),
        ann_text(
            "frames",
            "Frames: " + " · ".join(f if isinstance(f, str) else f["name"] for f in frames),
            CAPTION,
            TEXT_2,
        ),
    ]
    ins = list(insets)
    if ins:
        kids.append(
            ann_text(
                "insets",
                "Insets (inside the frame, not frames): " + " · ".join(ins),
                CAPTION,
                TEXT_2,
            )
        )
    labels = dict(ANN_ORDER)
    for key_, lab in ANN_ORDER:
        if b.get(key_):
            v = b[key_]
            kids.append(
                ann_block(lab, [v] if isinstance(v, str) else list(v), name=f"block · {key_}")
            )
    for key_, v in b.items():
        if key_ not in labels and v:
            kids.append(
                ann_block(
                    key_, [v] if isinstance(v, str) else list(v), name=f"block · {_safe(key_)[:40]}"
                )
            )
    return vbox(f"group · {sid}", kids, {"gap": STACK_SM}, w=ANN_TEXT_W)


def focus_overlay(screen: str, *, dialogs: bool = False, stepper: bool = False) -> Node:
    """The keyboard rider's overlay: the screen's focus order quoted from its Keys paragraph, plus §13's shared rules
    for dialogs and steppers."""
    t, ln = keys_text(screen)
    vals = [f"{t} (E42-D05 L{ln})"]
    if dialogs or stepper:
        vals.append(f"{shared_keys()} (E42-D05 §13 L{SHARED_KEYS_LINE})")
    return ann_block(
        f"Focus order · {screen} (keyboard rider)", vals, name=f"focus order · {screen}"
    )


def board_block(nn: int, n_frames: int) -> Node:
    b = BOARDS[nn]
    vals = [
        f"{board_name(nn)} → {export_path(nn)}",
        (
            f"{n_frames} frames in {len(b.rows)} row(s); page {PAGE}; file "
            f"'{FILE_NAME}'; grid {grid_xy(nn)}"
        ),
    ]
    if b.star:
        stem = Path(export_path(nn)).stem
        vals.append(
            f"★ greyscale and deuteranopia renders: {stem}-greyscale.png, {stem}-deuteranopia.png"
        )
    return ann_block("Board", vals, name="board")


def ann_column(
    nn: int, groups: Iterable[Node], extra: Iterable[Node] = (), *, subtitle: str | None = None
) -> Node:
    """The 400 px annotation column: title, subtitle, the state groups, extra blocks (focus overlays…), the board
    block and the footer "page E42-D05 · board NN · r1"."""
    b = BOARDS[nn]
    sub = subtitle or (
        "E42-D05 confirmed ten-board plan (18:44Z, #960 comment 6477583631): the frames 1:1 in the "
        "plan's rows with 80 px gutters; insets sit inside their frame; annotations outside."
    )
    nfr = len(plan_frames(nn))
    kids = [
        ann_text("title", f"{nn:02d} {b.slug} · {board_sizes(nn)} · {b.theme}", HEADING_SM),
        ann_text("subtitle", sub, CAPTION, TEXT_3),
        *groups,
        *extra,
        board_block(nn, nfr),
        ann_text("footer", footer_text(nn), CAPTION, TEXT_3),
    ]
    return vbox("annotations", kids, {"gap": STACK_MD, "pad": INSET_LG}, w=ANN_W)


# --- Board composition, writing, validation, packing.
def compose(nn: int, rows: Iterable[Iterable[Node]], ann: Node) -> dict[str, Any]:
    """Place the frames 1:1 in rows (80 px margin and gutters), the annotation column right of the widest row; return
    {"board", "frames", "ann"} with x/y set. Raises when the board would cross its 6000 × 9500 grid cell.
    """
    deviate("root")
    y, right, placed = GUTTER, 0, []
    meta = []
    for r, row in enumerate(rows, 1):
        x, h_row = GUTTER, 0
        for fr in row:
            w, h = int(fr["w"]), int(fr["h"])
            placed.append(dict(fr, x=x, y=y))
            meta.append({"name": fr["name"], "x": x, "y": y, "w": w, "h": h, "row": r})
            x += w + GUTTER
            h_row = max(h_row, h)
        right = max(right, x - GUTTER)
        y += h_row + GUTTER
    ax = right + GUTTER
    a = dict(ann, x=ax, y=GUTTER)
    ann_h = math.ceil(est_height(ann))
    w = ax + ANN_W + GUTTER
    h = max(y, GUTTER + ann_h + GUTTER)
    h = int(math.ceil(h / 8) * 8)
    if w > GRID_X or h > GRID_Y:
        raise ValueError(f"board {nn:02d}: {w} x {h} px crosses its {GRID_X} x {GRID_Y} grid cell")
    if w > GRID_X - GUTTER:
        note(
            "live_checks",
            f"board {nn:02d} is {w} px wide: it abuts its right neighbour's cell; the neighbour's "
            "80 px margin keeps the content apart",
        )
    gx, gy = grid_xy(nn)
    names = [m["name"] for m in meta]
    if len(set(names)) != len(names):
        raise ValueError(f"board {nn:02d}: duplicate frame names {names}")
    note(
        "live_checks",
        f"root '{board_name(nn)}' at ({gx}, {gy}): {w} x {h} px; after relayout the annotation column "
        f"(estimated {ann_h} px) must end inside the root: raise h if not",
    )
    board_ = {
        "name": board_name(nn),
        "w": w,
        "h": h,
        "x": gx,
        "y": gy,
        "o": {"fill": APP, "clip": True},
    }
    return {"board": board_, "frames": placed, "ann": a, "meta": meta, "ann_h": ann_h}


def walk(n: Node) -> Iterable[Node]:
    yield n
    for kid in n.get("kids") or []:
        yield from walk(kid)


def _validate(path: Path) -> tuple[int, str]:
    res = subprocess.run(
        [sys.executable, "-I", str(VALIDATOR), str(path), "--components", str(COMPONENTS_FILE)],
        capture_output=True,
        text=True,
        timeout=180,
        check=False,
    )
    lines = (res.stdout + res.stderr).strip().splitlines()
    return res.returncode, (lines[-1] if lines else "")


def pack(path: Path) -> tuple[int, str]:
    """compact.py (v4.1 clones + styles) into v4/ (the packed copy validates like the source)."""
    PACKED_DIR.mkdir(exist_ok=True)
    res = subprocess.run(
        [sys.executable, "-I", str(PACKER), str(path), str(PACKED_DIR / path.name)],
        capture_output=True,
        text=True,
        timeout=300,
        check=False,
    )
    out = (res.stdout + res.stderr).strip().splitlines()
    return res.returncode, (out[-1] if out else "")


def write_board(
    nn: int,
    rows: Iterable[Iterable[Node]],
    ann: Node,
    *,
    stem: str | None = None,
    notes: dict[str, Iterable[str]] | None = None,
    packed: bool = True,
    md_extra: Iterable[str] = (),
) -> dict[str, Any]:
    """Compose, split into sections (≤ SECTION_BUDGET bytes each), write NN-<slug>.json and .md into KIT_DIR, validate
    (exit 0 required) and pack into v4/. Merges e42kit.LOG (then clears it), SPEC_GAPS and a live check per
    inst node into the sheet's notes. Returns a summary dict."""
    c = compose(nn, rows, ann)
    secs = k.sections_for_board(c["frames"], c["ann"], budget=SECTION_BUDGET)
    big = [
        (s_["node"]["name"], len(json.dumps(s_)))
        for s_ in secs
        if len(json.dumps(s_)) > SECTION_HARD
    ]
    if big:
        raise RuntimeError(f"sections over {SECTION_HARD} bytes: {big}")
    merged: dict[str, list[str]] = {kd: [] for kd in NOTE_KINDS}
    for srcn in (notes or {}, LOG.notes):
        for kd, lines in srcn.items():
            merged.setdefault(kd, [])
            for ln in ([lines] if isinstance(lines, str) else lines):
                if ln not in merged[kd]:
                    merged[kd].append(ln)
    for g in SPEC_GAPS:
        if g not in merged["spec_gaps"]:
            merged["spec_gaps"].append(g)
    merged["sources"].insert(
        0,
        f"E42-D05 kit e42d05kit.py; spec {_rel(SPEC)} md5 {SPEC_MD5[:8]} (origin/main); plan {_rel(PLAN)}",
    )
    insts = 0
    for s_ in secs:
        for n in walk(s_["node"]):
            if n["t"] == "inst":
                insts += 1
                chk = k._inst_check(n)
                if chk not in merged["live_checks"]:
                    merged["live_checks"].append(chk)
    for sec in secs:
        for n in walk(sec["node"]):
            for kk_ in ("color", "typo"):
                if n.get(kk_) in NEVER_TOKENS:
                    raise ValueError(f"{n['name']}: {n[kk_]} is never used (§4.1)")
            if any(v in NEVER_TOKENS for v in (n.get("o") or {}).values()):
                raise ValueError(f"{n['name']}: a NEVER token (§4.1)")
    st = stem or f"{nn:02d}-{BOARDS[nn].slug}"
    path = KIT_DIR / f"{st}.json"
    sheet = {
        "board": c["board"],
        "sections": secs,
        "export": export_path(nn),
        "notes": {kd: v for kd, v in merged.items() if v},
    }
    path.write_text(json.dumps(sheet, ensure_ascii=False, indent=1) + "\n", encoding="utf-8")
    reset_notes()
    code, vline = _validate(path)
    nodes = sum(1 for s_ in secs for _n in walk(s_["node"]))
    summ = {
        "json": str(path),
        "valid": (code, vline),
        "sections": len(secs),
        "nodes": nodes,
        "insts": insts,
        "board": c["board"],
        "meta": c["meta"],
        "ann_h": c["ann_h"],
        "largest": max(len(json.dumps(s_)) for s_ in secs),
    }
    md = [
        f"# {c['board']['name']}",
        "",
        (
            f"File `{FILE_NAME}`, page `{PAGE}`; export `{export_path(nn)}`; sheet `{path.name}` (validated); theme "
            f"{BOARDS[nn].theme}."
        ),
        "",
        (
            f"Board {nn:02d} of the confirmed ten (plan {PLAN.name}, main-orchestrator 18:44Z, #960 comment "
            f"6477583631). Grid ({c['board']['x']}, {c['board']['y']}); {c['board']['w']} x {c['board']['h']} px; "
            f"{len(c['meta'])} frames; footer \"{footer_text(nn)}\"."
        ),
        "",
        "## Frames",
        "",
    ]
    md += [
        f"- `{m['name']}` — {m['w']} x {m['h']} at ({m['x']}, {m['y']}), row {m['row']}"
        for m in c["meta"]
    ]
    md += [
        "",
        "## Sources",
        "",
        f"- spec `{_rel(SPEC)}` (md5 {SPEC_MD5}), kit `e42d05kit.py`, plan `{_rel(PLAN)}`",
    ]
    md += [f"- {x}" for x in merged["sources"][1:25]]
    md += [
        "",
        "## Renders",
        "",
        (
            f"- ★ `{Path(export_path(nn)).stem}-greyscale.png` and "
            f"`{Path(export_path(nn)).stem}-deuteranopia.png`"
            if BOARDS[nn].star
            else "- none (the plan renders boards 02, 03, 04 and 06)"
        ),
    ]
    md += [
        "",
        "## Validator and size",
        "",
        f"- `{vline}` (exit {code})",
        f"- {len(secs)} sections, {nodes} nodes ({insts} instances), largest section {summ['largest']} bytes",
    ]
    md += list(md_extra)
    (KIT_DIR / f"{st}.md").write_text("\n".join(md) + "\n", encoding="utf-8")
    if code != 0:
        raise RuntimeError(f"{path.name}: validator exit {code}: {vline}")
    if packed:
        summ["pack"] = pack(path)
    return summ


def ext_label(chars: str, source: str) -> str:
    """An anatomy string another document gives (`14`, E09-D09 …), recorded as a copy gap with its source."""
    note("copy_gaps", f"'{chars}': from {source} (no E42-D05 §15 key)")
    return chars


def confirm_bar(variant: str = "destructive", state: str = "validity") -> Node:
    """A dialog confirm whose label no source gives: the label a bar (recorded as a copy gap); state "validity"
    (waiting on the token: form validity, §4.1) or "enabled"."""
    note(
        "copy_gaps", "a dialog confirm label: no §15 key or anatomy string names it; drawn as a bar"
    )
    look = {"validity": (RAISED, BORDER_DEFAULT), "enabled": (DANGER_SUBTLE, DANGER_STRONG)}[state]
    return hbox(
        f"CMP-001 Button (composition) · confirm ({state})",
        [bar("confirm label", 72)],
        {
            "padX": k.BUTTON_PADX,
            "radius": R_CONTROL,
            "height": k.CONTROL_COMF,
            "justify": "center",
            "fill": look[0],
            "stroke": look[1],
            "strokeWidth": HAIRLINE,
            "strokeAlign": "inner",
        },
        h=CONTROL_H,
        note="the confirm: enabled once the token matches (form validity, native disabled, §4.1, §12)",
    )


def fresh_code_line() -> Node:
    """ "This always needs a fresh code." (no grace; §12: download, delete, restore, the latch)."""
    note("copy_keys", "fresh_code")
    return text("step-up", INHERITED["fresh_code"][0], BODY, TEXT_2)


def token_field(
    key: str, note_key: str | None, *, value: str | None = None, w: int = 592, **fills: Any
) -> Node:
    """A typed-token field (D21, D23): its label the keyed sentence, the well empty or typed, the note under it."""
    kids = [
        field(
            copy(key, **fills),
            value,
            w=w,
            mono=True,
            name="CMP-040 FormField (composition) · token",
        )
    ]
    if note_key:
        kids.append(words(note_key, CAPTION, TEXT_2, w=w))
    return vbox(
        "token",
        kids,
        {"gap": INSET_XS},
        note="Enter in the token field never confirms (§7 Keys, §8.3 Keys)",
    )


# --- SCR-146 (§7): backups.
class Backup(NamedTuple):
    when: str | None  # started_at "yyyy-mm-dd hh:mm" (UTC); a date alone keeps its time as a bar
    kind: str | None
    status: (
        str | None
    )  # verified | ok | failed | running | restored | deleted | None (not given: a bar)
    size: str | None = None
    error: str | None = None  # Backup.error code (failed)
    last_verified: bool = (
        False  # the last verified backup of its kind (Delete T2 admin.last_backup)
    )
    pct: int | None = None  # running


BACKUPS = (  # §1 L88-91 (on `21`'s schedule, DJ), newest first; the 2026-10-21 01:00 restore point (RW-6: 820 MB)
    Backup("2026-10-22 02:00", "questdb_snapshot", "ok"),
    Backup("2026-10-22 01:30", "pg_dump", "ok"),
    Backup("2026-10-22 01:00", "pg_basebackup", "verified", last_verified=True),
    Backup("2026-10-21 03:30", "parquet_sync", "failed", error="checksum_mismatch"),
    Backup("2026-10-21 01:00", "pg_basebackup", None, "820 MB"),
    Backup("2026-10-19", "config_bundle", "verified", last_verified=True),
    Backup("2026-09-13 01:00", None, "deleted"),
)
RESTORE_POINT = BACKUPS[4]
SINGLE_FILE = (
    "pg_dump",
    "config_bundle",
)  # D21 / CG-13: Download only on single-file kinds (an inference from
# the kind; the kit's reading: pg_basebackup, questdb_snapshot and parquet_sync are directories or repositories)
L_ANATOMY_146 = find_line('- **Anatomy.** The shell · `h1` "Backups"')
STATUS_LOOK = {
    "verified": ("check", OK_STRONG),
    "ok": ("check", OK_STRONG),
    "failed": ("octagon", DANGER_STRONG),
    "running": ("ring", NEUTRAL_DEFAULT),
    "restored": ("ring", NEUTRAL_DEFAULT),
    "deleted": ("slashed-circle", TEXT_2),
    "not_encrypted": ("octagon", DANGER_STRONG),
}


def kind_label(kind: str | None) -> Node:
    """A kind: "a label with the enum in brackets" (§7 L392): "Postgres full (pg_basebackup)"; the plain label of
    every other kind is not given (a bar before the enum)."""
    if kind is None:
        return bar("kind", 120)
    if kind == "pg_basebackup":
        return text(
            "kind",
            label("Postgres full (pg_basebackup)", L_ANATOMY_146 + 3, "the kind label"),
            BODY,
            TEXT_1,
        )
    note(
        "copy_gaps",
        f"kind {kind}: §7 gives only pg_basebackup's plain label; the label is a bar, the enum drawn",
    )
    return hbox(
        "kind",
        [bar(f"{kind} label", 64), text("enum", f"({kind})", NUM_SM, TEXT_1)],
        {"gap": INSET_XS},
    )


def when_cell(when: str | None) -> Node:
    if when is None:
        return bar("started_at", 96)
    if len(when) == 10:
        return hbox(
            "when", [text("date", when, NUM_BASE, TEXT_1), bar("time", 32)], {"gap": INSET_XS}
        )
    return text("when", when, NUM_BASE, TEXT_1)


def backup_status(
    b: Backup, *, pct: int | None = None, expanded: bool = False, w: int = 200
) -> Node:
    """Status as word + glyph (§7, BK-4): Verified, "OK — not verified", Failed + the code in words (the code in a
    disclosure, `11:46`), Running with CMP-023 "{n} %", Restored (ring), Deleted {date}; a status §1 does not give is
    a bar."""
    if b.status is None:
        return bar("status", 72)
    g, c = STATUS_LOOK[b.status]
    if b.status == "deleted":
        return status_word(
            copy("backup.status.deleted", yyyy_mm_dd_hh_mm=b.when) if b.when else "Deleted",
            g,
            c,
            typo=BODY,
            name="status · deleted",
        )
    word = copy(f"backup.status.{b.status}")
    kids: list[Node] = [status_word(word, g, c, typo=BODY, name=f"status · {b.status}")]
    if b.status == "running":
        kids.append(
            hbox(
                "progress",
                [
                    progress(pct if pct is not None else b.pct, 96),
                    rich(
                        "backup.running",
                        typo=CAPTION,
                        color=TEXT_2,
                        n=pct if pct is not None else b.pct,
                    ),
                ],
                {"gap": INSET_XS},
            )
        )
    if b.status == "failed" and b.error:
        kids.append(words(f"backup.error.{b.error}", CAPTION, TEXT_1, w=w))
        kids.append(disclosure("Code", expanded))
        note(
            "copy_gaps",
            "the failed row's code disclosure label 'Code' is the kit's (`11:46`: the code in a "
            "disclosure)",
        )
        if expanded:
            kids.append(text("code", b.error, NUM_SM, TEXT_2))
    return vbox("status", kids, {"gap": INSET_XS})


def backup_actions(
    b: Backup,
    *,
    gate: str | None = None,
    rate_dl: bool = False,
    own_verify: bool = False,
    shared: bool = False,
    focus: str | None = None,
) -> Node:
    """[Verify] [Download…] [Delete…], always present, T2 (§4.1) where blocked (BK-4): Verify and Download on a row
    not usable admin.backup_not_usable; Download on a non-single-file kind admin.download_kind (CG-13); Delete on a
    kind's last verified backup admin.last_backup; gate= a page-wide reason for every action (admin.backup_running on
    the other rows' Verify; shared=True points them at the page notice); rate_dl: Download T2 admin.rate_limited with
    "until {hh:mm} UTC" beside it (BK-13); a deleted row gives way to its outcome line (BK-15)."""
    if b.status == "deleted":
        return rich(
            "backup.del.outcome",
            typo=CAPTION,
            color=TEXT_2,
            w=220,
            name="outcome line",
            yyyy_mm_dd_hh_mm=b.when,
        )
    usable = b.status in ("verified", "ok", None) and b.status != "running"
    acts: list[Node] = []
    v_reason = gate or (None if usable else "admin.backup_not_usable")
    acts.append(
        busy("Verify")
        if own_verify
        else (
            t2("Verify", v_reason, shared=shared)
            if v_reason
            else button("Verify", "secondary", focused=focus == "Verify")
        )
    )
    if rate_dl:
        until = hbox(
            "until",
            [
                text("w", "until", CAPTION, TEXT_2),
                bar("hh:mm", 32),
                text("u", "UTC", CAPTION, TEXT_2),
            ],
            {"gap": INSET_XS},
        )
        acts.append(t2("Download…", "admin.rate_limited", beside=until))
    else:
        d_reason = gate or (
            "admin.backup_not_usable"
            if not usable
            else None if (b.kind in SINGLE_FILE) else "admin.download_kind"
        )
        acts.append(
            t2("Download…", d_reason, shared=shared)
            if d_reason
            else button("Download…", "secondary", focused=focus == "Download…")
        )
    del_reason = gate or ("admin.last_backup" if b.last_verified else None)
    acts.append(
        t2("Delete…", del_reason, shared=shared)
        if del_reason
        else button("Delete…", "secondary", focused=focus == "Delete…")
    )
    return hbox("actions", acts, {"gap": INSET_SM, "align": "start", "wrap": "wrap"})


def backup_cols(px: int) -> list[tuple[str, str, int]]:
    w = SIZES[px].inner
    base = [
        ("when", "When", 136),
        ("kind", "Kind", 0),
        ("size", "Size", 80),
        ("status", "Status", 200),
        ("verified", "Verified", 112),
        ("keep", "Keep until", 104),
        ("actions", "", 300 if px == 1280 else 520),
    ]
    fixed = sum(c[2] for c in base)
    label("When", L_ANATOMY_146 + 2, "a column header")
    return [(i, h, (w - fixed) if i == "kind" else cw) for i, h, cw in base]


def backup_rows(
    px: int,
    backups: Iterable[Backup] = BACKUPS,
    *,
    actions: dict[int, dict[str, Any]] | None = None,
    expanded: int | None = None,
) -> list[dict[str, Any]]:
    """The table's cells per row (actions= per-row keyword overrides for backup_actions, by 0-based index)."""
    out = []
    for i, b in enumerate(backups):
        out.append(
            {
                "_name": f"row · {b.when or 'bar'} · {b.kind or 'bar'}",
                "when": when_cell(b.when),
                "kind": kind_label(b.kind),
                "size": text("size", b.size, NUM_BASE, TEXT_1) if b.size else bar("size_bytes", 48),
                "status": backup_status(b, expanded=(expanded == i)),
                "verified": (
                    bar("verified_at", 72)
                    if b.status == "verified"
                    else text("v", "—", BODY, TEXT_2)
                ),
                "keep": bar("retention_until", 64),
                "actions": backup_actions(b, **((actions or {}).get(i, {}))),
            }
        )
    return out


def backup_summary(px: int, *, warn: bool = False) -> Node:
    """The summary lines (D19, D20): last successful, last verified, the restore drill (a target, CG-12); warn=True
    prefixes the line past D20's threshold with "Attention:" and the triangle (BK-11)."""
    ok = rich(
        "backup.summary.last_ok",
        name="last successful",
        age=None,
        yyyy_mm_dd_hh_mm="2026-10-22 02:00",
    )
    ver = rich(
        "backup.summary.last_verified",
        name="last verified",
        age=None,
        yyyy_mm_dd_hh_mm="2026-10-22 01:00",
    )
    if warn:
        ver = hbox(
            "attention",
            [glyph("triangle", WARN_STRONG), text("lead", "Attention:", BODY_STRONG, TEXT_1), ver],
            {"gap": INSET_XS},
        )
    drill = hbox(
        "drill",
        [
            words("backup.summary.drill", BODY, TEXT_2),
            text("target", "(target, CG-12)", CAPTION, TEXT_3),
        ],
        {"gap": INSET_XS},
    )
    return vbox("summary", [ok, ver, drill], {"gap": STACK_XS}, w=SIZES[px].inner)


def scr146(
    px: int,
    sid: str = "BK-4",
    *,
    backups: Iterable[Backup] = BACKUPS,
    notice_key: str | None = None,
    header: str = "enabled",
    rows: bool = True,
    actions: dict[int, dict[str, Any]] | None = None,
    expanded: int | None = None,
    overlays: Iterable[Node] = (),
    insets: Iterable[Node] = (),
    extra_top: Iterable[Node] = (),
    warn: bool = False,
) -> Node:
    """An SCR-146 frame (§7): the shell "◆ Admin area · Backups", h1 "Backups", meta "as of", [Back up now…]
    [Restore…], the summary lines, the CMP-049 table (When · Kind · Size · Status · Verified · Keep until · actions),
    [Load more], the footer marker. header: "enabled" | "t2-shared" (BK-2, the notice_key notice) | "running"
    (Back up now… and Restore… T2 admin.backup_running) | "restore-not-built" (RW-16)."""
    state(sid)
    src(f"SCR-146 anatomy: E42-D05 §7 L{L_ANATOMY_146}-{L_ANATOMY_146 + 8}")
    bun = label("Back up now…", L_ANATOMY_146, "a header action")
    rst = label("Restore…", L_ANATOMY_146, "a header action")
    if header == "t2-shared":
        prim = [t2(bun, None, shared=True), t2(rst, None, shared=True)]
    elif header == "running":
        prim = [t2(bun, "admin.backup_running"), t2(rst, "admin.backup_running")]
    elif header == "restore-not-built":
        prim = [button(bun, "secondary"), t2(rst, "admin.restore_not_built")]
    else:
        prim = [button(bun, "secondary"), button(rst, "secondary")]
    extra = [t2_notice(notice_key, w=SIZES[px].inner)] if notice_key else []
    head = page_head(px, label("Backups", L_ANATOMY_146, "the h1"), primary=prim, extra=extra)
    content: list[Node] = list(extra_top)
    if rows:
        content.append(backup_summary(px, warn=warn))
        content.append(
            grid_table(
                backup_cols(px),
                backup_rows(px, backups, actions=actions, expanded=expanded),
                name="CMP-049 Table · backups",
            )
        )
        content.append(button(label("Load more", L_ANATOMY_146 + 4, "the pager"), "secondary"))
        note("live_checks", "SCR-146 table: an APG grid; row actions reached by ← → (§7 Keys)")
    return admin_frame(
        px,
        route="Backups",
        h1="Backups",
        head=head,
        content=content,
        overlays=overlays,
        insets=insets,
        name=f"frame-{px}",
    )


def download_dialog(
    px: int, b: Backup = BACKUPS[1], *, state_: str = "ask", typed: str | None = None
) -> list[Node]:
    """BK-12 (rung 4, ruling Q9, D21): backup.dl.title, the warning, who can fetch it, the token backup.dl.token with
    backup.dl.token_note under it, "This always needs a fresh code.", the marker backup.downloaded; [Cancel] (focused)
    and the confirm (form validity until the token matches). state_="ready" is BK-13: backup.dl.ready with [Download]
    and its expiry, never [Copy link], backup.dl.close_warning, [Close]."""
    title = copy("backup.dl.title", yyyy_mm_dd_hh_mm=b.when, kind=b.kind)
    if state_ == "ask":
        kids = [
            banner("warning", copy("backup.dl.warning"), w=592),
            words("backup.dl.who", BODY, TEXT_1, w=592),
            token_field(
                "backup.dl.token", "backup.dl.token_note", value=typed, yyyy_mm_dd_hh_mm=b.when
            ),
            fresh_code_line(),
            marker_line(None, "backup.downloaded"),
        ]
        acts = [
            ring(button("Cancel", "secondary")),
            confirm_bar("enabled" if typed == b.when else "validity"),
        ]
    else:
        kids = [
            hbox(
                "ready",
                [
                    glyph("check", OK_STRONG),
                    rich("backup.dl.ready", hh_mm_ss=None, focus="Download"),
                ],
                {"gap": INSET_XS},
            ),
            rich("backup.dl.close_warning", w=592, hh_mm_ss=None),
            marker_line(None, "backup.downloaded"),
        ]
        acts = [button("Close", "secondary")]
        note(
            "deviations",
            "BK-13: the link is shown once with [Download] and its expiry, never [Copy link] (D21); the "
            "dialog's [Close] label is the kit's",
        )
    dlg = dialog(title, kids, acts, size="large", role="alertdialog")
    return modal(px, dlg)


def delete_dialog(px: int, b: Backup = BACKUPS[1]) -> list[Node]:
    """BK-14 (rung 4 + token): backup.del.title, backup.del.list (the row stays; {n} usable backups left: a bar),
    the token, "This always needs a fresh code.", the marker backup.deleted; [Cancel] (focused), the confirm.
    """
    title = copy("backup.del.title", yyyy_mm_dd_hh_mm=b.when, kind=b.kind)
    kids = [
        rich("backup.del.list", w=592, n=None),
        token_field("backup.dl.token", None, yyyy_mm_dd_hh_mm=b.when),
        fresh_code_line(),
        marker_line(None, "backup.deleted"),
    ]
    note(
        "deviations",
        "BK-14: the token's label is backup.dl.token (§15 gives one 'Type the backup time to confirm' "
        "sentence for the download; the delete's own token key is not listed)",
    )
    return modal(
        px,
        dialog(
            title,
            kids,
            [ring(button("Cancel", "secondary")), confirm_bar("validity")],
            size="large",
        ),
    )


# --- The steppers (CMP-066; D27): restore (six steps) and onboarding (eight).
RESTORE_STEPS = (
    "Choose a backup",
    "What a restore does",
    "Confirm",
    "Restoring",
    "Checking the result",
    "Summary",
)
L_STEPS = find_line("- **Steps** (`14:2758`): 1 Choose a backup")
ONBOARD_STEPS = (
    "Sub-account",
    "The 48-hour wait",
    "API key",
    "Access",
    "IP allowlist",
    "Profile",
    "Limits",
    "Invite",
)
L_WZ_ANATOMY = find_line(
    "the CMP-066 stepper (240 px, D27), each step a link with its status word and glyph"
)
STEP_LOOK = {
    "done": ("check", OK_STRONG),
    "current": ("dot", BORDER_SELECTED),
    "blocked": ("clock", STALE_IND),
    "not_started": ("ring", NEUTRAL_DEFAULT),
    "attention": ("octagon", DANGER_STRONG),
}


def step_word(status: str, **fills: Any) -> str:
    """The onboarding stepper's status words (§9.1 L527-528): "Done {yyyy-mm-dd}", "Current", "Blocked until
    {yyyy-mm-dd hh:mm} UTC", "Not started", "Needs attention"."""
    ln = L_WZ_ANATOMY
    if status == "done":
        d_ = fills.get("date")
        label("Done {yyyy-mm-dd}", ln, "a stepper status")
        return f"Done {d_}" if d_ else "Done"
    if status == "blocked":
        label("Blocked until {yyyy-mm-dd hh:mm} UTC", ln, "a stepper status")
        return f"Blocked until {fills['until']} UTC"
    return label(
        {"current": "Current", "not_started": "Not started", "attention": "Needs attention"}[
            status
        ],
        ln,
        "a stepper status",
    )


def step_glyph(kind: str, color: str) -> Node:
    """A stepper glyph: the registry stand-in, or the 'Current' dot (an 8 px ellipse, FALLBACKS['DOT'])."""
    if kind == "dot":
        fallback("DOT")
        return hbox(
            "dot", [ellipse("dot", 8, 8, {"fill": color})], {"justify": "center"}, w=16, h=16
        )
    if kind == "ring":
        fallback("NEUTRAL")
    return glyph(kind, color)


def stepper(
    steps: Iterable[str],
    statuses: list[tuple[str, dict[str, Any]]],
    current: int,
    *,
    name: str = "CMP-066 Stepper (composition)",
) -> Node:
    """CMP-066 (D27): a <nav> with an ordered list, 240 px; each step a link "n Name" with its status word and one
    glyph (never colour alone); the current step aria-current="step" with a 3 px color.border.selected left edge
    (§16 L734)."""
    items: list[Node] = []
    for i, (nm, (stt, fl)) in enumerate(zip(steps, statuses), 1):
        g, c = STEP_LOOK[stt]
        word = step_word(stt, **fl) if stt in STEP_LOOK else stt
        if stt == "done" and not fl.get("date") and fl.get("bar_date"):
            wn: Node = hbox(
                "status",
                [step_glyph(g, c), text("word", "Done", CAPTION, TEXT_2), bar("date", 56)],
                {"gap": INSET_XS},
            )
        else:
            wn = hbox(
                "status",
                [step_glyph(g, c), text("word", word, CAPTION, TEXT_2, w=STEPPER_W - 56)],
                {"gap": INSET_XS},
            )
        kids = [
            text(
                "name",
                f"{i} {nm}",
                BODY_STRONG if i == current else BODY,
                TEXT_LINK if i != current else TEXT_1,
            ),
            wn,
        ]
        o: dict[str, Any] = {"gap": STACK_XS, "padX": INSET_MD, "padY": INSET_SM}
        if i == current:
            o.update(fill=SELECTED)
            kids.insert(0, rect("current edge", 3, 40, BORDER_SELECTED, x=0, y=0, abs=True))
        items.append(
            vbox(
                f"step {i}",
                kids,
                o,
                w=STEPPER_W,
                note='aria-current="step"' if i == current else "a link (navigable)",
            )
        )
    return vbox(
        name,
        items,
        {"gap": STACK_XS},
        w=STEPPER_W,
        note="<nav aria-label> with an ordered list (D27)",
    )


def restore_statuses(
    current: int, done_upto: int | None = None
) -> list[tuple[str, dict[str, Any]]]:
    """Restore steps: done before current, current, not started after (the words are §9.1's; the restore names no
    others: DJ)."""
    note(
        "deviations",
        "restore stepper: §8 names no status words; the kit uses §9.1's Done / Current / Not started "
        "(D27: each status a word with one glyph)",
    )
    d_ = current - 1 if done_upto is None else done_upto
    return [
        ("done", {}) if i <= d_ else ("current", {}) if i == current else ("not_started", {})
        for i in range(1, 7)
    ]


def step_body(
    px: int, h2: str, kids: Iterable[Node], actions: Iterable[Node], *, w: int | None = None
) -> Node:
    """A step region: its h2 (the focus target on a step change, tabindex=-1, D27), the content, one actions row."""
    bw = w or (SIZES[px].inner - STEPPER_W - PX[INSET_XL])
    return vbox(
        "step body",
        [
            text(
                "h2",
                h2,
                HEADING_MD,
                TEXT_1,
                w=bw,
                note="h2 tabindex=-1: focus lands here on a " "step change (D27)",
            ),
            *kids,
            hbox("actions", list(actions), {"gap": INSET_SM, "align": "start"}),
        ],
        {"gap": STACK_MD},
        w=bw,
    )


def wizard_layout(px: int, step_nav: Node, body: Node) -> Node:
    return hbox("wizard", [step_nav, body], {"gap": INSET_XL, "align": "start"}, w=SIZES[px].inner)


def restore_frame(
    px: int,
    sid: str,
    step: int,
    body_kids: Iterable[Node],
    actions: Iterable[Node],
    *,
    statuses: list[tuple[str, dict[str, Any]]] | None = None,
    overlays: Iterable[Node] = (),
    insets: Iterable[Node] = (),
) -> Node:
    """The restore wizard, a view of SCR-146 (§8.1; no route of its own): the stepper column and the step body."""
    state(sid)
    src(f"restore anatomy: E42-D05 §8.1 L{L_STEPS}-{L_STEPS + 15}")
    h2 = label(RESTORE_STEPS[step - 1], L_STEPS, "a step name")
    body = step_body(px, h2, body_kids, actions)
    content = [
        wizard_layout(px, stepper(RESTORE_STEPS, statuses or restore_statuses(step), step), body)
    ]
    head = page_head(px, "Backups")
    return admin_frame(
        px,
        route="Backups",
        h1="Backups",
        head=head,
        content=content,
        overlays=overlays,
        insets=insets,
        name=f"frame-{px}",
    )


def cancel_restore() -> Node:
    return button(label("Cancel restore", L_STEPS + 2, "steps 1-3's way out"), "ghost")


def backup_radio(b: Backup, *, w: int, checked: bool = False, focused: bool = False) -> Node:
    """A step-1 radio (none pre-selected): time, kind, size, status, verified; a row that cannot be restored is a T2
    radio admin.backup_not_usable (arrows focus it, never check it)."""
    if b.status in ("failed", "deleted", "running"):
        return t2_radio(
            b.when or "—",
            f"{b.kind or ''} · {b.status}",
            "admin.backup_not_usable",
            w=w,
            focused=focused,
        )
    dot = ellipse(
        "ring", 16, 16, {"stroke": TEXT_3 if not checked else ACTION_PRIMARY, "strokeWidth": THICK}
    )
    row = hbox(
        "facts",
        [
            dot,
            when_cell(b.when),
            kind_label(b.kind),
            text("size", b.size, NUM_BASE, TEXT_1) if b.size else bar("size", 48),
            backup_status(b),
            bar("verified_at", 56) if b.status == "verified" else text("v", "—", BODY, TEXT_2),
        ],
        {"gap": INSET_MD},
    )
    n = hbox(
        f"CMP-006 Radio (composition) · {b.when}",
        [row],
        {"pad": INSET_XS},
        w=w,
        note="role=radio; none pre-selected (§8.1)",
    )
    return ring(n) if focused else n


def restore_step1(
    px: int, maint: str = "off", *, chosen: Backup | None = None
) -> tuple[list[Node], list[Node]]:
    """Step 1 (RW-1, RW-2): first the maintenance line (off: restore.step1.needs_maint with "Turn on maintenance mode
    → Maintenance" beside it; on: maint_on; unknown: maint_unknown), the usable backups as radios, [Back up now
    first…]; Next T2 admin.maintenance_first / admin.maintenance_unknown, or enabled once a backup is chosen.
    """
    bw = SIZES[px].inner - STEPPER_W - PX[INSET_XL]
    key = {
        "off": "restore.step1.needs_maint",
        "on": "restore.step1.maint_on",
        "unknown": "restore.step1.maint_unknown",
    }[maint]
    first: list[Node] = [words(key, BODY_STRONG, TEXT_1)]
    if maint == "off":
        first.append(
            link(
                label("Turn on maintenance mode → Maintenance", STATES["RW-1"].line, "RW-1's link")
            )
        )
    kids = [hbox("maintenance", first, {"gap": INSET_SM, "wrap": "wrap"}, w=bw)]
    kids += [backup_radio(b, w=bw, checked=(chosen is b)) for b in BACKUPS if b.status != "deleted"]
    kids.append(button(copy("restore.step1.backup_first"), "secondary"))
    nxt = (
        t2("Next", "admin.maintenance_first")
        if maint == "off"
        else (
            t2("Next", "admin.maintenance_unknown")
            if maint == "unknown"
            else (button("Next", "primary") if chosen else validity("Next", None, "primary"))
        )
    )
    return kids, [cancel_restore(), nxt]


SCOPE = (
    ("postgres", True, False),
    ("config", True, False),
    ("questdb", False, True),
    ("parquet", False, True),
)
L_D22 = find_line("| D22 | **Restore scope**")


def scope_picker(w: int, ticked: tuple[str, ...] = ("postgres", "config")) -> Node:
    """D22: the wizard always sends components; postgres + config ticked by default; questdb and parquet drawn as
    labelled targets ("target — the contract does not define per-store restore semantics yet", CG-9).
    """
    tgt = label(
        "target — the contract does not define per-store restore semantics yet",
        L_D22,
        "D22's target label",
    )
    rows = []
    for nm, _dflt, target in SCOPE:
        rows.append(
            hbox(
                f"store · {nm}",
                [tick(nm, checked=nm in ticked, w=160)]
                + ([text("target", tgt, CAPTION, TEXT_3)] if target else []),
                {"gap": INSET_SM},
            )
        )
    return vbox(
        "scope picker (CMP-005 group)",
        rows,
        {"gap": STACK_XS},
        w=w,
        note="the last ticked store can't be unticked (form validity, restore.scope_one)",
    )


IMPACT_ORDER = (
    "bybit",
    "rewind",
    "config",
    "trading",
    "reconcile",
    "market",
    "secrets",
    "signin",
    "security_today",
)


def impact_lines(
    w: int, scope: tuple[str, ...] = ("postgres", "config"), *, audit: bool = True
) -> Node:
    """§8.2's lines in order for a scope (the security reviewer's table, L471-485): bybit first, always; rewind,
    secrets, signin, security_today with postgres; config with config; trading and reconcile always; market (both
    market stores off); audit as the labelled target (per D7)."""
    out: list[Node] = []
    for kk in IMPACT_ORDER:
        if kk in ("rewind", "secrets", "signin", "security_today") and "postgres" not in scope:
            continue
        if kk == "config" and "config" not in scope:
            continue
        if kk == "market" and ({"questdb", "parquet"} & set(scope)):
            kk = "market_on"
        fills = (
            {"yyyy_mm_dd_hh_mm": RESTORE_POINT.when}
            if kk == "rewind"
            else ({"yyyy_mm_dd": RESTORE_POINT.when[:10]} if kk == "signin" else {})
        )
        out.append(words(f"restore.impact.{kk}", BODY, TEXT_1, w=w, name=f"impact · {kk}", **fills))
    if audit and "postgres" in scope:
        out.append(
            hbox(
                "impact · audit (target)",
                [
                    words("restore.impact.audit", BODY, TEXT_1, w=w - 72),
                    text("target", "(target, D7)", CAPTION, TEXT_3),
                ],
                {"gap": INSET_XS, "align": "start"},
            )
        )
    return vbox(
        "impact (§8.2)",
        out,
        {"gap": STACK_SM},
        w=w,
        note="§8.2's copy only; nothing says 'safe', 'undo' or 'recover your trades' (RES:780-784)",
    )


def fold(what: str, w: int) -> Node:
    """An elided part of a long step ('↑ … elided'), so a frame shows the part its state is about."""
    return text("elided", f"↑ {what} — elided", CAPTION, TEXT_3, w=w)


def restore_step2(
    px: int,
    part: str = "impact",
    *,
    branch: str = "open",
    ticked: bool = False,
    security: str = "target",
) -> tuple[list[Node], list[Node]]:
    """Step 2 (§8.2 in order: impact lines + scope picker, the positions block with its tick, the security block).
    part: "impact" (RW-3), "positions" (RW-4: branch "open" 2 positions / "unknown"), "security" (RW-5: "target" the
    list + tick + sign-out, labelled "if D7 decides as proposed", or "today"). Next T2 admin.ack_first until every
    shown tick is ticked."""
    bw = SIZES[px].inner - STEPPER_W - PX[INSET_XL]
    kids: list[Node] = []
    nxt: Node = button("Next", "primary")
    if part == "impact":
        kids += [impact_lines(bw), scope_picker(bw)]
    elif part == "positions":
        kids.append(fold("§8.2's impact lines and the scope picker (RW-3)", bw))
        if branch == "open":
            kids += [
                words("restore.positions.open", BODY, TEXT_1, w=bw, n=2),
                tick(copy("restore.positions.open_ack"), checked=ticked, w=bw),
            ]
        else:
            kids += [
                words("restore.positions.unknown", BODY, TEXT_1, w=bw),
                tick(copy("restore.positions.unknown_ack"), checked=ticked, w=bw),
            ]
        nxt = button("Next", "primary") if ticked else t2("Next", "admin.ack_first")
    else:
        kids.append(
            fold("§8.2's impact lines, the scope picker and the positions block (RW-3, RW-4)", bw)
        )
        if security == "target":
            kids += [
                text(
                    "target",
                    label("if D7 decides as proposed", STATES["RW-5"].line, "RW-5's target label"),
                    CAPTION,
                    TEXT_3,
                ),
                rich("restore.impact.security_list", w=bw, list=None),
                tick(copy("restore.impact.security_ack"), checked=ticked, w=bw),
                words("restore.impact.signout", BODY, TEXT_1, w=bw),
            ]
            nxt = button("Next", "primary") if ticked else t2("Next", "admin.ack_first")
        else:
            kids.append(words("restore.impact.security_today", BODY, TEXT_1, w=bw))
    return kids, [cancel_restore(), button("Back", "secondary"), nxt]


def restore_step3(
    px: int, *, replaced: bool = True, refused: str | None = None, typed: bool = False
) -> tuple[list[Node], list[Node]]:
    """Step 3 (RW-6; rung 4 inside the step, D24): restore.confirm.title, "Postgres full (pg_basebackup) · 820 MB",
    the token with its note (D23), Why? (restore.confirm.reason_replaced while postgres is in scope and CG-7 is open,
    else restore.confirm.reason), restore.confirm.stepup, the marker (restore.confirm.marker_replaced, or "Recorded in
    the audit log · Backup restored (backup.restore)"), [Cancel restore] [Back] [Restore from
    {time}] (form validity). refused= a
    restore.refused.* key (RW-8): the rule in words + D02:708's spent-code sentence, inputs kept, [Try again].
    """
    bw = SIZES[px].inner - STEPPER_W - PX[INSET_XL]
    b = RESTORE_POINT
    kids: list[Node] = []
    if refused:
        kids.append(
            banner(
                "danger",
                vbox(
                    "words",
                    [
                        words(refused, BODY, TEXT_1, w=bw - 64),
                        text("spent", INHERITED["spent_code"][0], BODY, TEXT_1, w=bw - 64),
                        button("Try again", "secondary"),
                    ],
                    {"gap": STACK_XS},
                ),
                w=bw,
                name="refusal (assertive once)",
            )
        )
        note("copy_keys", "spent_code")
    kids += [
        words("restore.confirm.title", HEADING_SM, TEXT_1, w=bw, yyyy_mm_dd_hh_mm=b.when),
        hbox(
            "what",
            [
                kind_label(b.kind),
                text(
                    "size",
                    f"· {b.size}",
                    NUM_BASE,
                    TEXT_1,
                    note='accessible name "820 megabytes" (§13)',
                ),
            ],
            {"gap": INSET_XS},
        ),
        token_field(
            "restore.confirm.token",
            "restore.confirm.token_note",
            value=b.when if typed or refused else None,
            w=bw,
            yyyy_mm_dd_hh_mm=b.when,
        ),
        field(
            copy("restore.confirm.reason_replaced" if replaced else "restore.confirm.reason"),
            None,
            w=bw,
            name="CMP-040 FormField (composition) · Why?",
        ),
        words("restore.confirm.stepup", BODY, TEXT_2, w=bw),
        (
            text("marker", copy("restore.confirm.marker_replaced"), CAPTION, TEXT_3)
            if replaced
            else marker("Backup restored", "backup.restore")
        ),
    ]
    if refused or typed:
        note(
            "deviations",
            "the Why? value typed in this frame is not given by §1: the field is drawn empty",
        )
    conf = label("Restore from {time}", L_STEPS + 7, "the confirm")
    conf_txt = conf.replace("{time}", b.when)
    return kids, [
        cancel_restore(),  # D24, §8.1, §8.3: "Cancel restore" on steps 1-3 (boards review round 1, M-1)
        button("Back", "secondary"),
        validity(conf_txt, None) if not refused else button(conf_txt, "destructive"),
    ]


def restore_outcome(px: int, which: str) -> tuple[list[Node], list[Node]]:
    """Steps 4-6 bodies: "progress" (RW-9, CMP-023 restore.progress), "lost" (RW-10, restore.lost), "summary" (RW-12:
    "Restored to the backup of {yyyy-mm-dd hh:mm}", restore.summary.review, restore.summary.trading), "failed",
    "cancelled" (RW-13). No Cancel on 4-6; "Close" leaves the job running (§8.1)."""
    bw = SIZES[px].inner - STEPPER_W - PX[INSET_XL]
    if which == "progress":
        kids = [progress(None, bw), rich("restore.progress", n=None)]
    elif which == "lost":
        kids = [words("restore.lost", BODY, TEXT_1, w=bw)]
    elif which == "summary":
        head = label(
            "Restored to the backup of {yyyy-mm-dd hh:mm}",
            STATES["RW-12"].line,
            "RW-12's summary line",
        )
        kids = [
            text(
                "restored",
                head.replace("{yyyy-mm-dd hh:mm}", RESTORE_POINT.when),
                BODY_STRONG,
                TEXT_1,
            ),
            rich("restore.summary.review", w=bw, n=None),
            hbox(
                "trading",
                [
                    words("restore.summary.trading", BODY, TEXT_1),
                    text("target", "(where to turn trading on: a target, CG-11)", CAPTION, TEXT_3),
                ],
                {"gap": INSET_XS, "wrap": "wrap"},
                w=bw,
            ),
        ]
    elif which == "failed":
        kids = [rich("restore.failed", w=bw, reason=None)]
    else:
        kids = [words("restore.cancelled", BODY, TEXT_1, w=bw)]
    return kids, [
        button(ext_label("Close", "§8.1 L451 ('\"Close\" leaves the job running')"), "secondary")
    ]


def wide_200(px: int, kind: str = "zoom") -> Node:
    """RW-14 (§4.2, at 1280 × 800): the step reflowed for 200 % zoom (kind "zoom") or the 200 % in-app text scale
    ("text"): the stepper collapsed to "Step 2 of 6: What a restore does" with a disclosure, the body scrolling, Back
    and Next one sticky row. cvsheet has no 2× type tokens: the frame draws the reflow with the largest semantic type
    (type.ui.heading-lg / display) and a 640 px column (zoom) or the full width (text)."""
    state("RW-14")
    note(
        "deviations",
        f"RW-14 ({kind}): no 2× typography tokens exist; the reflow is drawn with type.ui.heading-lg "
        "and type.ui.display, a single column, the collapsed stepper and a sticky footer row",
    )
    g = SIZES[px]
    col_w = 640 if kind == "zoom" else g.w - 2 * PX[INSET_XL]
    big, huge = "type.ui.heading-lg", "type.ui.display"
    head = label(
        "Step {n} of {m}: {name}",
        find_line('collapses to "Step {n} of {m}: {name}"'),
        "§4.2's collapsed " "stepper",
    )
    del head
    lines = [
        hbox(
            "collapsed stepper",
            [
                icon("chevron", "chevron-right", TEXT_2),
                text("step", "Step 2 of 6: What a restore does", huge, TEXT_1, w=col_w - 32),
            ],
            {"gap": INSET_XS},
            note="a disclosure listing every step and its status word (§4.2)",
        ),
        text("h2", "What a restore does", huge, TEXT_1, w=col_w),
    ]
    for kk in IMPACT_ORDER[:4]:
        fills = {"yyyy_mm_dd_hh_mm": RESTORE_POINT.when} if kk == "rewind" else {}
        lines.append(
            text(f"impact · {kk}", copy(f"restore.impact.{kk}", **fills), big, TEXT_1, w=col_w)
        )
    body = vbox(
        "step body (scrolls)", lines, {"gap": STACK_LG, "clip": True}, w=col_w, h=g.h - 2 * 48 - 140
    )
    foot = hbox(
        "sticky footer row",
        [button("Back", "secondary"), button("Next", "primary")],
        {"gap": INSET_SM, "fill": RAISED, "padX": INSET_LG, "padY": INSET_SM},
        w=col_w,
        note="Back and Next stay one sticky row (§4.2)",
    )
    page = vbox("viewport", [body, foot], {"fill": APP}, w=col_w)
    return vbox(
        f"frame-{px}",
        [
            k.topbar(px),
            hbox("content", [page], {"justify": "center", "padY": INSET_LG}, w=g.w, h=g.h - 96),
            k.statusbar(px),
        ],
        {"fill": APP, "clip": True},
        w=g.w,
        h=g.h,
    )


# --- The owner's onboarding wizard (§9.1-§9.2) at R-303 /admin/users/new.
L_WZ_HEAD = find_line('- **Anatomy.** The shell "◆ Admin area · Onboard a manager"')
ONBOARD_EXAMPLE = (
    {  # §1 L91-92: sub_004 created 2026-10-22 09:15 UTC, key creation opens 2026-10-24 09:15 UTC
        "created": "2026-10-22 09:15",
        "opens": "2026-10-24 09:15",
        "opens_in": ("1", "23"),
        "invitee": "gina",
        "sub": "sub_004",
    }
)


def onboard_statuses(kind: str = "key") -> list[tuple[str, dict[str, Any]]]:
    """Step statuses for the worked example: "start" (WZ-1: none done), "key" (WZ-4: 1-2 done 2026-10-22, 3 current),
    "blocked" (WZ-5: 3 blocked until 2026-10-24 09:15, 4 current), "invite" (WZ-11: 8 current, 3 blocked, the rest
    done with their dates as bars), "resume" (WZ-12: as invite, the current step the first incomplete).
    """
    d_ = {"date": DATE}
    if kind == "start":
        return [("current", {})] + [("not_started", {})] * 7
    if kind == "key":
        return [("done", d_), ("done", d_), ("current", {})] + [("not_started", {})] * 5
    if kind == "blocked":
        return [
            ("done", d_),
            ("done", d_),
            ("blocked", {"until": ONBOARD_EXAMPLE["opens"]}),
            ("current", {}),
        ] + [("not_started", {})] * 4
    if kind == "revisit":
        return [("done", d_), ("done", d_), ("current", {})] + [("not_started", {})] * 5
    if kind == "invite":
        return (
            [("done", d_), ("done", d_), ("blocked", {"until": ONBOARD_EXAMPLE["opens"]})]
            + [("done", {"bar_date": True})] * 4
            + [("current", {})]
        )
    if kind == "resume":
        return [
            ("done", d_),
            ("done", d_),
            ("blocked", {"until": ONBOARD_EXAMPLE["opens"]}),
            ("current", {}),
        ] + [("not_started", {})] * 4
    raise ValueError(kind)


def onboard_frame(
    px: int,
    sid: str,
    step: int,
    body_kids: Iterable[Node],
    actions: Iterable[Node],
    *,
    statuses: list[tuple[str, dict[str, Any]]] | None = None,
    h2: str | None = None,
    top: Iterable[Node] = (),
    insets: Iterable[Node] = (),
    overlays: Iterable[Node] = (),
) -> Node:
    """The owner's wizard (§9.1): the shell "◆ Admin area · Onboard a manager", h1 "Onboard a manager", meta
    onboard.saved_server, the CMP-066 stepper (240 px), the step body (h2, one CMP-065 section, its own Save,
    [Back] [Continue to step {n}], the step's marker)."""
    state(sid)
    src(f"onboarding anatomy: E42-D05 §9.1 L{L_WZ_HEAD}-{L_WZ_HEAD + 8}")
    h1 = label("Onboard a manager", L_WZ_HEAD, "the h1")
    head = page_head(px, h1, meta=copy("onboard.saved_server"))
    name = h2 or f"{step} {ONBOARD_STEPS[step - 1]}"
    body = step_body(px, name, body_kids, actions)
    content = [
        *top,
        wizard_layout(px, stepper(ONBOARD_STEPS, statuses or onboard_statuses("key"), step), body),
    ]
    return admin_frame(
        px,
        route=h1,
        h1=h1,
        head=head,
        content=content,
        insets=insets,
        overlays=overlays,
        name=f"frame-{px}",
    )


def continue_to(n: int, enabled: bool = True) -> Node:
    lab = label("Continue to step {n}", L_WZ_HEAD + 5, "the step's next action").replace(
        "{n}", str(n)
    )
    return button(lab, "primary") if enabled else validity(lab, None, "primary")


def onboard_step3(px: int, kind: str = "key") -> tuple[list[Node], list[Node]]:
    """Step 3 bodies. "key" (WZ-4): API key, then API secret (write-only, no reveal, the format hint
    onboard.s3.secret_hint), onboard.secret_once on warning.subtle in text.primary (D30), the IP precondition line,
    "You'll confirm with your password and a code." (`keys`), the marker api_key.import, Save. "blocked" (WZ-5): Add
    key T2 admin.key_cooldown with onboard.opens beside it; [Continue to step 4] enabled (AC-4). "revisit" (WZ-6):
    onboard.key_revisit + "Secret — not shown again", no field, no value, no hash (a target, M:577-581).
    """
    bw = SIZES[px].inner - STEPPER_W - PX[INSET_XL]
    if kind == "key":
        kids = [
            field(
                ext_label("API key", "§9.2 WZ-4 L552 ('API key, then API secret')"),
                None,
                w=min(bw, 480),
            ),
            vbox(
                "secret",
                [
                    field(
                        ext_label("API secret", "§9.2 WZ-4 L552"),
                        None,
                        w=min(bw, 480),
                        name="CMP-201 PasswordField (composition) · API secret",
                    ),
                    words("onboard.s3.secret_hint", CAPTION, TEXT_2),
                ],
                {"gap": INSET_XS},
                note='type="password", autocomplete="off", no reveal control (D30); the secret in no event, log, '
                "analytics or error payload (E42J:246)",
            ),
            banner(
                "warning", copy("onboard.secret_once"), w=bw, name="secret once (warning.subtle)"
            ),
            words("onboard.ip_unknown", BODY, TEXT_2, w=bw, name="IP precondition"),
            text("step-up", k.copy("dlg.step_up.code"), BODY, TEXT_2),
            marker_line(None, "api_key.import"),
        ]
        note("copy_keys", "dlg.step_up.code")
        return kids, [button("Save", "primary"), button("Back", "secondary"), continue_to(4)]
    if kind == "blocked":
        y, m = ONBOARD_EXAMPLE["opens"], ONBOARD_EXAMPLE["opens_in"]
        opens = words("onboard.opens", BODY, TEXT_2, yyyy_mm_dd_hh_mm=y, d=m[0], h=m[1])
        add = t2(
            label("Add key", STATES["WZ-5"].line, "WZ-5's control"),
            "admin.key_cooldown",
            variant="primary",
            beside=opens,
        )
        kids = [words("onboard.key_wait", BODY, TEXT_1, w=bw), add]
        return kids, [button("Back", "secondary"), continue_to(4)]
    if kind == "revisit":
        kids = [
            rich("onboard.key_revisit", w=bw, last4=None, status=None, hh_mm=None),
            words("onboard.key_revisit.secret", BODY, TEXT_2),
        ]
        note(
            "deviations",
            "WZ-6: no field, no value, no hash; '…{last4}', status and the check time are bars (a "
            "target: the key list is not mounted, M:577-581)",
        )
        return kids, [button("Back", "secondary"), continue_to(4)]
    raise ValueError(kind)


def onboard_start(px: int) -> tuple[list[Node], list[Node]]:
    """WZ-1: the eight steps with their status words (the stepper), onboard.saved_server (meta), [Start with step 1]."""
    return (
        [words("onboard.saved_server", BODY, TEXT_2)],
        [button(label("Start with step 1", STATES["WZ-1"].line, "WZ-1's action"), "primary")],
    )


def wz15_inset(px: int) -> Node:
    """WZ-15 (inset on WZ-1): [Start] T2 admin.wizard_not_built; links to Sub-accounts (SCR-125) and Invite
    (SCR-123)."""
    ln = STATES["WZ-15"].line
    return inset(
        px,
        "WZ-15",
        "today: no wizard record or route (CG-3)",
        [
            t2(label("Start", ln), "admin.wizard_not_built", variant="primary"),
            hbox(
                "links",
                [
                    link(label("Sub-accounts", ln, "WZ-15's link") + " (SCR-125)"),
                    link(label("Invite", ln, "WZ-15's link") + " (SCR-123)"),
                ],
                {"gap": INSET_LG},
            ),
        ],
    )


def onboard_invite(px: int) -> tuple[list[Node], list[Node]]:
    """WZ-11 (D32): D03's SCR-123 embedded, never a fork: inv.role, inv.tailscale, then the link once with Copy,
    inv.once, inv.close_warning (D03's copy)."""
    bw = SIZES[px].inner - STEPPER_W - PX[INSET_XL]
    for kk in ("inv.role", "inv.tailscale", "inv.once", "inv.close_warning"):
        note("copy_keys", kk)
    once = raw("inv.once")[0]
    linkrow = hbox(
        "the link once",
        [
            field(ext_label("Invite link", "D03 SCR-123 (embedded)"), None, w=bw - 120, mono=True),
            button("Copy", "secondary"),
        ],
        {"gap": INSET_SM, "align": "end"},
        note="the invite_url shown once (Y:16152); never logged or announced",
    )
    kids = [
        text("role", k.copy("inv.role"), BODY, TEXT_1, w=bw),
        text("tailscale", k.copy("inv.tailscale"), BODY, TEXT_2, w=bw),
        linkrow,
        hbox(
            "once",
            [
                text("w", once.split("{")[0].strip(), BODY_STRONG, TEXT_1),
                bar("expires", 120),
                text("u", "UTC.", BODY_STRONG, TEXT_1),
            ],
            {"gap": INSET_XS},
        ),
        text("close warning", k.copy("inv.close_warning"), BODY, TEXT_1, w=bw),
        marker_line(None, "users.invited"),
    ]
    note(
        "deviations",
        "WZ-11 embeds D03's SCR-123 by its copy (inv.*); the link field's label is the kit's",
    )
    return kids, [button("Back", "secondary")]


def onboard_resume_top() -> Node:
    """WZ-12: onboard.resume (n, k and the step name are bars: §1 gives no resumed count)."""
    return rich("onboard.resume", n=None, k=None, fill_map={"name": None})


# --- SCR-017, the invitee's wizard (§9.3; D33): no session, no admin shell.
INVITEE_STEPS = ("Accept the invite", "Set a password", "Two-factor", "Orientation")
L_IW = find_line("### 9.3 SCR-017, the invitee's wizard")


def invitee_frame(
    px: int, sid: str, step: int, kids: Iterable[Node], *, insets: Iterable[Node] = ()
) -> Node:
    """SCR-017 (§9.3, `14:433-455`): four steps, a <form> each with an aria-current="step" progress list and an h1;
    a centred card on the app surface (no admin shell: no session until done)."""
    state(sid)
    src(f"SCR-017: E42-D05 §9.3 L{L_IW}-{L_IW + 5}; `14:433-455` at {PIN[:9]}")
    note(
        "copy_gaps",
        "SCR-017's step names in the progress list are the kit's ('Accept the invite', 'Set a password', "
        "'Two-factor', 'Orientation'; `14:435`'s 'accept invite → set password → enrol TOTP → "
        "orientation card')",
    )
    prog = hbox(
        "progress list",
        [
            text(
                f"step {i}",
                f"{i} {nm}",
                BODY_STRONG if i == step else BODY,
                TEXT_1 if i == step else TEXT_2,
                note='aria-current="step"' if i == step else None,
            )
            for i, nm in enumerate(INVITEE_STEPS, 1)
        ],
        {"gap": INSET_LG},
        note="an aria-current progress list (`14:452`)",
    )
    card = vbox(
        "form card",
        [prog, *kids],
        {"fill": RAISED, "radius": R_CARD, "pad": INSET_XL, "gap": STACK_MD},
        w=640,
        note="a <form> per step with an h1 (`14:452`)",
    )
    fr = plain_frame(px, [card], name=f"frame-{px}")
    fr["kids"] += list(insets)
    return fr


def invitee_totp(px: int) -> list[Node]:
    """IW-3: SCR-003 embedded (E09-D04's frames): drawn as a named region, not redrawn; the recovery codes shown once
    (CMP-206)."""
    note(
        "deviations",
        "IW-3: SCR-003 is E09-D04's; the frame holds a named region for its embed (not redrawn here)",
    )
    return [
        text("h1", INVITEE_STEPS[2], HEADING_MD, TEXT_1),
        box(
            "SCR-003 TwoFactorEnrol (E09-D04, embedded)",
            [
                text(
                    "w",
                    "SCR-003 (E09-D04's frames, embedded): "
                    "CMP-205 QrCode, the code field, CMP-206 "
                    "RecoveryCodeList shown once",
                    CAPTION,
                    TEXT_3,
                    w=560,
                )
            ],
            {"fill": SUNKEN, "radius": R_CARD, "pad": INSET_LG, "dir": "column"},
            w=592,
            h=280,
        ),
    ]


def iw9_inset(px: int, op: str = "confirmInvite") -> Node:
    """IW-9 (inset on IW-3): the step stays, inputs kept, invitee.too_many or invitee.unavailable under its form."""
    return inset(
        px,
        "IW-9",
        f"too many attempts; unavailable ({op})",
        [
            banner("warning", copy("invitee.too_many"), w=440),
            banner("warning", copy("invitee.unavailable"), w=440),
        ],
        corner="br",
    )


def orientation_card(px: int, role: str = "manager") -> list[Node]:
    """IW-4 / IW-5: `14:439-444`'s card verbatim, filled from Me.accounts (bars: §1 gives gina no account), the
    48-hour line from her checklist, her limits; D09's scr017.cannot and "Ask the owner if you need it." (D09:85);
    [Open the terminal]."""
    src(f"`14:439-444` at {PIN[:9]} (SCR-017's card)")
    if role == "manager":
        lines = [
            text(
                "set up",
                ext_label("You're set up as: Account Manager", "`14:439`"),
                HEADING_SM,
                TEXT_1,
            ),
            hbox(
                "accounts",
                [
                    text("w", ext_label("Accounts:", "`14:440`"), BODY, TEXT_1),
                    bar("accounts", 120),
                    text("e", ext_label("Environment:", "`14:440`"), BODY, TEXT_1),
                    bar("environment", 48),
                ],
                {"gap": INSET_SM},
            ),
            hbox(
                "limits",
                [text("w", ext_label("Limits:", "`14:441`"), BODY, TEXT_1), bar("risk_caps", 220)],
                {"gap": INSET_SM},
            ),
            hbox(
                "48 h",
                [
                    text(
                        "w",
                        ext_label(
                            "API key pending Bybit's 48 h restriction - live from", "`14:442`"
                        ),
                        BODY,
                        TEXT_1,
                    ),
                    bar("unblock_at", 120),
                    text(
                        "e",
                        ext_label("UTC. You can trade Demo meanwhile.", "`14:443`"),
                        BODY,
                        TEXT_1,
                    ),
                ],
                {"gap": INSET_XS, "wrap": "wrap"},
                w=592,
            ),
            text("cannot", INHERITED["scr017.cannot.manager"][0], BODY, TEXT_1, w=592),
        ]
        note("copy_keys", "scr017.cannot.manager")
    else:
        lines = [
            text("set up", "You're set up as: Viewer", HEADING_SM, TEXT_1),
            text("cannot", INHERITED["scr017.cannot.viewer"][0], BODY, TEXT_1, w=592),
        ]
        note("copy_keys", "scr017.cannot.viewer")
    lines.append(text("ask", INHERITED["scr017.ask"][0], BODY, TEXT_2))
    note("copy_keys", "scr017.ask")
    lines.append(
        hbox(
            "actions",
            [button(ext_label("Open the terminal", "`14:444`"), "primary")],
            {"justify": "end"},
            w=592,
        )
    )
    return [text("h1", INVITEE_STEPS[3], HEADING_MD, TEXT_1)] + lines


# --- SCR-062 governance layer (§10; D34): the layer only, as targets (CG-25).
class Group(NamedTuple):
    name: str
    members: str | None  # None: not given (a bar)
    version: int | None
    enabled: bool = True


GROUPS = (Group("Scalp desk", "sub_001, sub_002", 3), Group("Swing", None, None))  # §1 L92-93
L_GV = find_line("**Anatomy (the layer only, D34).**")


def group_row(g: Group, i: int, n: int, *, focus: str | None = None) -> list[Node]:
    """One group's layer (§10): name and members (E28's base, as given), status word "Enabled"/"Disabled", "Who may
    use: {users}", "Version {n}", [Disable…]/[Enable…], [Rename], [Move up] [Move down] (the ends T2
    admin.order_edge), [Who may use…]; buttons named with their scope."""
    tgt = text("target", "target (CG-25)", CAPTION, TEXT_3)
    st = status_word(
        label("Enabled" if g.enabled else "Disabled", L_GV, "the status word"),
        "check" if g.enabled else "slashed-circle",
        OK_STRONG if g.enabled else TEXT_2,
        typo=BODY,
    )
    who = hbox(
        "who",
        [
            text(
                "w", label("Who may use:", L_GV, "the layer column").rstrip(":") + ":", BODY, TEXT_1
            ),
            bar("users", 80),
        ],
        {"gap": INSET_XS},
    )
    ver = (
        text("version", copy("group.version", n=g.version), NUM_BASE, TEXT_1)
        if g.version is not None
        else rich("group.version", typo=NUM_BASE, n=None)
    )
    dis = button(
        label("Disable…" if g.enabled else "Enable…", L_GV, "the layer's action"), "secondary"
    )
    dis = dict(
        dis,
        note=f'accessible name "Disable trade group {g.name} — removes it from ticket targets" (E42J:246)',
    )
    up = (
        t2(label("Move up", L_GV), "admin.order_edge") if i == 0 else button("Move up", "secondary")
    )
    down = (
        t2(label("Move down", L_GV), "admin.order_edge")
        if i == n - 1
        else button("Move down", "secondary")
    )
    return [
        text("name", g.name, BODY_STRONG, TEXT_1),
        text("members", g.members, NUM_SM, TEXT_1) if g.members else bar("members", 96),
        vbox("status", [st, tgt], {"gap": INSET_XS}),
        vbox("who", [who, tgt], {"gap": INSET_XS}),
        vbox("version", [ver, tgt], {"gap": INSET_XS}),
        hbox(
            "actions",
            [
                dis,
                button(copy("group.rename"), "secondary"),
                up,
                down,
                button(label("Who may use…", L_GV, "the layer's action"), "secondary"),
            ],
            {"gap": INSET_SM, "wrap": "wrap", "align": "start"},
        ),
    ]


def scr062(
    px: int, sid: str = "GV-1", *, groups: Iterable[Group] = GROUPS, overlays: Iterable[Node] = ()
) -> Node:
    """An SCR-062 admin frame (§10): E28's base columns as given (name, members) plus the governance layer, each
    layer column labelled "target" until CG-25 lands; no grid (a few rows: Tab walks the buttons).
    """
    state(sid)
    src(f"SCR-062 layer: E42-D05 §10 L{L_GV}-{L_GV + 8}; `14:1380` at {PIN[:9]} (the title)")
    gs = list(groups)
    w = SIZES[px].inner
    cols = [
        ("name", "Group", 128),
        ("members", "Members", 136),
        ("status", "Status", 112),
        ("who", "Who may use", 136),
        ("version", "Version", 96),
        ("actions", "", 0),
    ]
    cols = [(i, h, (w - sum(c[2] for c in cols)) if i == "actions" else cw) for i, h, cw in cols]
    note(
        "copy_gaps",
        "SCR-062's column headers (Group, Members, Status, Who may use, Version) are the kit's: E28's "
        "base design does not exist (deviation (9))",
    )
    rows = []
    for i, g in enumerate(gs):
        cells = dict(zip([c[0] for c in cols], group_row(g, i, len(gs))))
        cells["_name"] = f"row · {g.name}"
        rows.append(cells)
    tbl = grid_table(cols, rows, name="CMP-049 Table · trade groups")
    h1 = ext_label("Trade-group manager", "`14:1380` (SCR-062)")
    return admin_frame(
        px,
        route=h1,
        h1=h1,
        head=page_head(px, h1),
        content=[tbl],
        overlays=overlays,
        name=f"frame-{px}",
    )


# --- The E42-S08 statechart inspector (§11; D35).
L_SI = find_line('**Anatomy.** The shell "◆ Admin area · Statechart inspector"')


def kind_counters(px: int, *, rowless: bool = True) -> Node:
    """The kind counters (CMP-049: kind · environment · machines · by state · chain trips · latched · dropped
    receipts): B1 order with one latched machine and 2 chain trips; B8 position_protection with one latched machine
    and no row (machine.rowless). Counts §1 does not give are bars."""
    w = SIZES[px].inner
    cols = [
        ("kind", "Kind", 0),
        ("env", "Environment", 112),
        ("machines", "Machines", 96),
        ("by", "By state", 160),
        ("trips", "Chain trips", 104),
        ("latched", "Latched", 88),
        ("dropped", "Dropped receipts", 136),
    ]
    cols = [(i, h, (w - sum(c[2] for c in cols)) if i == "kind" else cw) for i, h, cw in cols]
    label(
        "kind · environment · machines · by state · chain trips · latched · dropped receipts",
        L_SI + 1,
        "the counters' columns",
    )
    rows = [
        {
            "_name": "kind · order",
            "kind": text("k", "order (B1)", NUM_SM, TEXT_1),
            "env": text("e", "LIVE", BODY, TEXT_1),
            "machines": bar("machines", 32),
            "by": bar("by state", 96),
            "trips": text("t", "2", NUM_BASE, TEXT_1),
            "latched": text("l", "1", NUM_BASE, TEXT_1),
            "dropped": bar("dropped_receipts", 32),
        },
        {
            "_name": "kind · position_protection",
            "kind": text("k", "position_protection (B8)", NUM_SM, TEXT_1),
            "env": text("e", "LIVE", BODY, TEXT_1),
            "machines": bar("machines", 32),
            "by": bar("by state", 96),
            "trips": bar("chain trips", 32),
            "latched": text("l", "1", NUM_BASE, TEXT_1),
            "dropped": bar("dropped_receipts", 32),
        },
    ]
    tbl = grid_table(cols, rows, name="CMP-049 Table · kinds")
    kids = [tbl]
    if rowless:
        kids.append(
            hbox(
                "rowless",
                [
                    glyph("octagon", DANGER_STRONG),
                    words(
                        "machine.rowless", BODY, TEXT_1, w=w - 32, kind="position_protection", n=1
                    ),
                ],
                {"gap": INSET_XS, "align": "start"},
            )
        )
    note(
        "deviations",
        "inspector: the environment LIVE is §1's; machine counts, by-state and dropped receipts are bars",
    )
    return vbox("kind counters", kids, {"gap": STACK_SM}, w=w)


def machine_table(px: int) -> Node:
    """The machine table (machine · kind · environment · state · hash (8 hex, "matches the lock" or "differs") · chain
    trips · latched · deferred · updated) with "Latched only" (aria-pressed); the latched B1 row "Latched — chain
    trips: 2" (octagon)."""
    w = SIZES[px].inner
    cols = [
        ("machine", "Machine", 0),
        ("kind", "Kind", 96),
        ("env", "Environment", 104),
        ("state", "State", 104),
        ("hash", "Hash", 168),
        ("trips", "Chain trips", 96),
        ("latched", "Latched", 200),
        ("deferred", "Deferred", 80),
        ("updated", "Updated", 88),
    ]
    cols = [(i, h, (w - sum(c[2] for c in cols)) if i == "machine" else cw) for i, h, cw in cols]
    latched = status_word(copy("machine.latched", n=2), "octagon", DANGER_STRONG, typo=BODY_STRONG)
    rows = [
        {
            "_name": "machine · B1 latched",
            "machine": bar("machine id", 96),
            "kind": text("k", "order", NUM_SM, TEXT_1),
            "env": text("e", "LIVE", BODY, TEXT_1),
            "state": bar("state", 64),
            "hash": hbox(
                "hash",
                [bar("8 hex", 48), text("m", label("matches the lock", L_SI + 3), CAPTION, TEXT_2)],
                {"gap": INSET_XS},
            ),
            "trips": text("t", "2", NUM_BASE, TEXT_1, note='accessible name "2 chain trips" (§13)'),
            "latched": latched,
            "deferred": bar("deferred", 24),
            "updated": bar("updated", 48),
        }
    ]
    toggle = hbox(
        "CMP-004 Toggle (composition) · Latched only",
        [
            rect("track", 28, 16, HOVER, {"radius": R_BADGE}),
            text("label", label("Latched only", L_SI + 4, "the toggle"), BODY, TEXT_1),
        ],
        {"gap": INSET_XS},
        note="aria-pressed",
    )
    return vbox(
        "machines",
        [toggle, grid_table(cols, rows, name="CMP-049 Table · machines")],
        {"gap": STACK_SM},
        w=w,
    )


def inspector(
    px: int,
    sid: str = "SI-1",
    *,
    overlays: Iterable[Node] = (),
    insets: Iterable[Node] = (),
    rowless: bool = False,
) -> Node:
    """An inspector frame (§11): the shell "◆ Admin area · Statechart inspector", the h1 ("E42-S08 inspector", D35),
    the kind counters, machine.latched_effect above the table while a machine is latched, the machine table.
    """
    state(sid)
    src(f"inspector anatomy: E42-D05 §11 L{L_SI}-{L_SI + 6}")
    h1 = label("E42-S08 inspector", find_line('labelled "E42-S08 inspector"'), "the h1 (D35, D45)")
    content = [
        kind_counters(px, rowless=rowless),
        banner("danger", copy("machine.latched_effect"), w=SIZES[px].inner, name="latched effect"),
        machine_table(px),
    ]
    return admin_frame(
        px,
        route=label("Statechart inspector", L_SI, "the band route"),
        h1=h1,
        head=page_head(px, h1),
        content=content,
        overlays=overlays,
        insets=insets,
        name=f"frame-{px}",
    )


def latch_dialog(px: int) -> list[Node]:
    """SI-6 (rung 4, ruling Q12): machine.ack.title ({machine_key} a bar), machine.ack.effect, machine.ack.trips (2),
    "This always needs a fresh code.", a marker without a code (CG-26); [Cancel] (focused), [Acknowledge latch].
    """
    kids = [
        words("machine.ack.effect", BODY, TEXT_1, w=592),
        words("machine.ack.trips", BODY, TEXT_1, n=2),
        fresh_code_line(),
        marker_line(None, None),
    ]
    title = rich("machine.ack.title", typo=HEADING_MD, machine_key=None)
    dlg = dialog(
        copy("machine.ack.title", machine_key="{machine_key}"),
        kids,
        [
            ring(button("Cancel", "secondary")),
            button(label("Acknowledge latch…", L_SI + 4).rstrip("…"), "destructive"),
        ],
        size="large",
    )
    dlg["kids"][0] = dict(title, name="title")
    note(
        "deviations",
        "SI-6: the confirm reads 'Acknowledge latch' (the page control's words without the ellipsis)",
    )
    return modal(px, dlg)


# --- Board 02: the status sheet (dark, light, hc columns; the forced-colours column) — §16, §4.3.
L_FORCED = find_line("### 4.3 Forced colours")
L_GREY = find_line("| Greyscale and colour-vision pair")


def _sheet_section(title: str, rows: Iterable[Node], w: int = 400) -> Node:
    note("copy_gaps", f"status sheet section heading '{title}' is the kit's")
    return vbox(
        f"section · {title}",
        [text("heading", title, HEADING_SM, TEXT_1), *rows],
        {"gap": STACK_SM},
        w=w,
    )


def status_sheet_column(theme: str, px: int = 1280) -> Node:
    """One status-sheet column (board 02; deviation (4): 1280 × 800): every status family as words and glyphs — health
    (D2) and stale (CMP-239), incident resolution and severity, backup statuses, stepper statuses, machine statuses
    (latched, the current state's 3 px border and "current", the hash match), T2 (§4.1) and CMP-023 — so the greyscale
    and deuteranopia renders prove that no state is colour alone (§16 L750-751). The theme switches at export.
    """
    deviate("status-cols")
    src(f"status sheet: E42-D05 §16 L{L_GREY - 22}-{L_GREY + 9}; D2 L{D2_LINE}")
    health = [health_status(s) for s in HEALTH_ORDER] + [stale_chip(AS_OF)]
    inc = [
        status_word("Open", "octagon", DANGER_STRONG, typo=BODY),
        hbox(
            "acknowledged",
            [glyph("clock", STALE_IND), text("w", "Acknowledged", BODY, TEXT_1)],
            {"gap": INSET_XS},
        ),
        status_word("Resolved", "check", OK_STRONG, typo=BODY),
        severity_cell("error"),
        severity_cell("critical"),
    ]
    label("Open", L_ANATOMY_144 + 6, "a resolution word")
    bk = [
        backup_status(b)
        for b in (
            Backup(None, None, "verified"),
            Backup(None, None, "ok"),
            Backup(None, None, "failed", error="checksum_mismatch"),
            Backup(None, None, "running", pct=48),
            Backup(None, None, "restored"),
            Backup("2026-09-13 01:00", None, "deleted"),
            Backup(None, None, "not_encrypted"),
        )
    ]
    steps = [
        hbox(
            f"step · {st}",
            [
                step_glyph(*STEP_LOOK[st]),
                text(
                    "w", step_word(st, date=DATE, until=ONBOARD_EXAMPLE["opens"]), CAPTION, TEXT_2
                ),
            ],
            {"gap": INSET_XS},
        )
        for st in ("done", "current", "blocked", "not_started", "attention")
    ]
    inner = hbox(
        "state",
        [
            text("state", "position_open", BODY_STRONG, TEXT_1),
            text("w", copy("machine.current"), CAPTION, TEXT_2),
        ],
        {
            "gap": INSET_XS,
            "padX": INSET_SM,
            "padY": INSET_XS,
            "stroke": BORDER_SELECTED,
            "strokeWidth": HAIRLINE,
            "strokeAlign": "inner",
            "radius": R_CONTROL,
        },
    )
    cur = hbox(
        "diagram · current",
        [inner],
        {
            "stroke": BORDER_SELECTED,
            "strokeWidth": THICK,
            "strokeAlign": "inner",
            "radius": R_CONTROL,
        },
        note="the diagram's current state: a 3 px color.border.selected border (border.thick + border.hairline "
        "nested: no 3 px token), the word 'current' and a bold label (SI-4)",
    )
    note(
        "deviations",
        "status sheet: the diagram's 3 px border is border.thick (2 px) on a wrapper plus "
        "border.hairline (1 px) on the state (no 3 px border token); 'position_open' is a sample label",
    )
    mach = [
        status_word(copy("machine.latched", n=2), "octagon", DANGER_STRONG, typo=BODY),
        cur,
        text("match", label("matches the lock", L_SI + 3), CAPTION, TEXT_2),
        text("differs", label("differs", L_SI + 3), CAPTION, TEXT_2),
    ]
    t2s = [
        t2(copy("backup.run.title") + "…", "admin.backup_running"),
        t2_radio("2026-10-21 03:30", "parquet_sync · failed", "admin.backup_not_usable", w=380),
        hbox(
            "progress",
            [progress(48, 160), text("pct", "48 %", NUM_BASE, TEXT_2)],
            {"gap": INSET_SM},
        ),
    ]
    note(
        "deviations",
        "status sheet: CMP-023's 48 % is a sample value (no running backup's % is given)",
    )
    cols = [
        vbox(
            "col-1",
            [_sheet_section("Health", health), _sheet_section("Incidents", inc)],
            {"gap": STACK_LG},
            w=400,
        ),
        vbox(
            "col-2",
            [_sheet_section("Backups", bk), _sheet_section("Steppers", steps)],
            {"gap": STACK_LG},
            w=400,
        ),
        vbox(
            "col-3",
            [_sheet_section("Machines", mach), _sheet_section("T2 and progress", t2s)],
            {"gap": STACK_LG},
            w=400,
        ),
    ]
    head = text("theme", f"Theme column: {theme} (the theme is applied at export)", LABEL, TEXT_2)
    g = SIZES[px]
    return vbox(
        f"frame-{px}",
        [head, hbox("columns", cols, {"gap": INSET_XL, "align": "start"})],
        {"fill": APP, "clip": True, "pad": INSET_LG, "gap": STACK_MD},
        w=g.w,
        h=g.h,
    )


FC = {
    "Canvas": APP,
    "CanvasText": TEXT_1,
    "LinkText": TEXT_LINK,
    "Highlight": ACTION_PRIMARY,
    "HighlightText": TEXT_ON,
}


def forced(n: Node, *, root: bool = True) -> Node:
    """The forced-colours construction (§4.3), on a copy: fills drop (the frame's Canvas, a selected row's or the
    current step's Highlight and CMP-023's bar kept); words CanvasText (links LinkText, HighlightText on Highlight);
    glyphs currentColor; every border CanvasText; banners, the stale chip and T2 controls keep (or gain) a 1 px
    border; value bars kept (placeholders)."""
    fallback("FC")
    out = _copy.deepcopy(n)

    def visit(m: Node, hl: bool, lnk: bool) -> None:
        nm = m["name"]
        if nm.startswith("bar · "):
            return
        o = m.get("o")
        lnk = lnk or nm.startswith(("CMP-021", "incidents link", "Re-read", "heading", "runbook"))
        if m["t"] == "board" and o is not None and m is not out:
            if o.get("fill") == SELECTED:
                o["fill"] = FC["Highlight"]
                hl = True
            elif "fill" in o:
                del o["fill"]
            if "stroke" in o:
                o["stroke"] = FC["HighlightText"] if hl else FC["CanvasText"]
            if nm.startswith(("CMP-028", "CMP-092", "CMP-239", "SCR-152")) or nm.endswith("(T2)"):
                o.update(stroke=FC["CanvasText"], strokeWidth=HAIRLINE, strokeAlign="inner")
        if m["t"] == "text":
            m["color"] = (
                FC["HighlightText"]
                if hl
                else (FC["LinkText"] if lnk or m.get("color") == TEXT_LINK else FC["CanvasText"])
            )
        if m["t"] == "icon":
            m["color"] = FC["HighlightText"] if hl else FC["CanvasText"]
        if m["t"] in ("rect", "ellipse") and o is not None:
            if nm == "fill" or nm == "current edge":
                o["fill"] = FC["Highlight"]
            elif "fill" in o and nm != "scrim":
                o["fill"] = FC["CanvasText"] if nm in ("dot", "divider") else o["fill"]
                if nm == "track":
                    del o["fill"]
                    o.update(stroke=FC["CanvasText"], strokeWidth=HAIRLINE)
            if "stroke" in o:
                o["stroke"] = FC["CanvasText"]
        for kid in m.get("kids") or []:
            visit(kid, hl, lnk)

    visit(out, False, False)
    if root and out.get("o") is not None:
        out["o"]["fill"] = FC["Canvas"]
    return out


def fc_column(px: int = 1280) -> Node:
    """Board 02's fourth column: old board 04's forced-colours inset of HL-6, RW-3 and WZ-5 (§4.3 L230), three 1:1
    crops of those frames' key parts (tiles; stepper and impact; stepper and the blocked step) under forced().
    """
    deviate("status-cols")
    src(f"forced colours: E42-D05 §4.3 L{L_FORCED}-{L_FORCED + 7}")
    g = SIZES[px]
    cw = g.w - 2 * PX[INSET_LG]
    comps = hl6_comps()
    tiles = hbox(
        "HL-6 tiles",
        [dict(health_tile(px, c, col=i), w=TILE_W[px][i]) for i, c in enumerate(comps[:3])],
        {"gap": STEP, "align": "start"},
    )
    rw_body, _a = restore_step2(px, "impact")
    rw = wizard_layout(
        px,
        stepper(RESTORE_STEPS, restore_statuses(2), 2),
        step_body(px, RESTORE_STEPS[1], rw_body[:1], []),
    )
    wz_body, wz_act = onboard_step3(px, "blocked")
    wz = wizard_layout(
        px,
        stepper(ONBOARD_STEPS, onboard_statuses("blocked"), 3),
        step_body(px, "3 API key", wz_body, wz_act),
    )
    crops = []
    for sid, part, h in (("HL-6", tiles, 236), ("RW-3", rw, 236), ("WZ-5", wz, 236)):
        crops.append(
            vbox(
                f"crop · {sid}",
                [
                    text("label", f"{sid} · forced-colors: active", LABEL, TEXT_2),
                    box("crop", [dict(part, x=0, y=0)], {"clip": True}, w=cw, h=h - 24),
                ],
                {"gap": STACK_XS},
                w=cw,
            )
        )
    fr = vbox(
        f"frame-{px}",
        crops,
        {"fill": APP, "clip": True, "pad": INSET_LG, "gap": STACK_SM},
        w=g.w,
        h=g.h,
    )
    return forced(fr)


# --- Every planned frame, built by state id (the presets the board generators use).
def hl6_comps() -> list[Comp]:
    """HL-6: degraded, down, warning and not built at once (§1's private WS and disk, bybit_rest down, and
    bars_writer not built: DJ, the row names no component)."""
    note(
        "deviations",
        "HL-6 / HL-7: the not-built component is bars_writer (DJ: the state row names none)",
    )
    return health_set(
        {"bybit_rest": Comp("bybit_rest", "down"), "bars_writer": "not_deployed"}, example=True
    )


def _scr143_preset(px: int, sid: str, insets: tuple[str, ...]) -> Node:
    ins: list[Node] = []
    if sid == "HL-2":
        if "client-tile" in insets:
            ins.append(
                inset(
                    px,
                    "HL-2",
                    "no engine in this window (D4)",
                    [client_tile(px, engine=False, w=300)],
                    w=340,
                )
            )
        return scr143(px, sid, insets=ins)
    if sid == "HL-5":
        comps = health_set({"bybit_rest": Comp("bybit_rest", "down")})
        if "HL-5-gate" in insets:
            ins.append(
                inset(
                    px,
                    "HL-5",
                    "an oms fault or a gate read missing: health.safe withheld (D9; today's)",
                    [health_tile(px, comps[2], safe=False, w=420)],
                    w=460,
                )
            )
        return scr143(px, sid, comps=comps, banner_down=True, insets=ins)
    if sid in ("HL-6", "HL-20"):
        comps = hl6_comps()
        if "HL-7" in insets:
            state("HL-7")
            ins.append(
                inset(
                    px,
                    "HL-7",
                    "not built yet (neutral, ranks healthy)",
                    [health_tile(px, Comp("bars_writer", "not_deployed"), w=300)],
                    w=340,
                )
            )
        return scr143(px, sid, comps=comps, banner_down=True, insets=ins)
    if sid == "HL-11":
        return scr143(px, sid, comps=health_set(example=True), numbers="stale", failed=True)
    if sid == "HL-12":
        if "HL-15" in insets:
            state("HL-15")
            ins.append(
                inset(
                    px,
                    "HL-15",
                    "503 audit_unavailable: the guard refuses admin reads",
                    [overall_line(px, None, unavailable="bar")],
                    w=520,
                )
            )
        return scr143(
            px, sid, comps=health_set(example=True), numbers="none", failed=True, insets=ins
        )
    if sid == "HL-14":
        return scr143(
            px,
            sid,
            comps=health_set(example=True),
            numbers="stale",
            e17=True,
            export_t2=True,
            failed=True,
        )
    if sid == "HL-18":
        return scr143(px, sid, comps=health_set(example=True), overlays=export_dialog(px))
    raise KeyError(sid)


def _scr146_preset(px: int, sid: str, insets: tuple[str, ...]) -> Node:
    if sid == "BK-4":
        bks = list(BACKUPS) + [
            Backup(None, None, "running", pct=None),
            Backup(None, None, "restored"),
        ]
        return scr146(px, sid, backups=bks, header="running")
    if sid == "BK-2":
        return scr146(px, sid, notice_key="admin.backups_not_built", header="t2-shared", rows=False)
    if sid == "BK-12":
        return scr146(px, sid, overlays=download_dialog(px))
    if sid == "BK-9":
        return scr146(
            px,
            sid,
            expanded=3,
            extra_top=[
                banner(
                    "danger",
                    copy("backup.error.checksum_mismatch"),
                    w=SIZES[px].inner,
                    name="verification failed",
                )
            ],
        )
    if sid == "BK-13":
        ins = []
        if "link-expired" in insets:
            ins.append(
                inset(
                    px,
                    "BK-13",
                    "link expired (outcome line in [Download]'s place)",
                    [rich("backup.dl.expired", w=420, hh_mm_ss=None)],
                    w=460,
                    corner="tl",
                )
            )
        if "404" in insets:
            ins.append(
                inset(
                    px,
                    "BK-13",
                    "404 before the challenge: no code spent",
                    [rich("backup.dl.refused_gone", w=420)],
                    w=460,
                    corner="bl",
                )
            )
        return scr146(px, sid, overlays=download_dialog(px, state_="ready"), insets=ins)
    if sid == "BK-14":
        return scr146(px, sid, overlays=delete_dialog(px))
    raise KeyError(sid)


def _restore_preset(px: int, sid: str, insets: tuple[str, ...], tag: str = "") -> Node:
    ins: list[Node] = []
    if sid == "RW-1":
        b, a = restore_step1(px, "off")
        if "RW-16" in insets:
            state("RW-16")
            ins.append(
                inset(
                    px,
                    "RW-16",
                    "today: not mounted — Restore… on the list",
                    [t2(label("Restore…", L_ANATOMY_146), "admin.restore_not_built")],
                    w=380,
                )
            )
        return restore_frame(px, sid, 1, b, a, insets=ins)
    if sid in ("RW-3", "RW-15"):
        b, a = restore_step2(px, "impact")
        return restore_frame(px, sid, 2, b, a)
    if sid == "RW-4":
        b, a = restore_step2(px, "positions", branch="open")
        if "loading" in insets:
            ins.append(
                inset(
                    px,
                    "RW-4",
                    "the overview read in flight: Next busy (not T2)",
                    [busy("Next", "primary")],
                    w=380,
                )
            )
        return restore_frame(px, sid, 2, b, a, insets=ins)
    if sid == "RW-5":
        b, a = restore_step2(px, "security", security="target")
        if "today" in insets:
            ins.append(
                inset(
                    px,
                    "RW-5",
                    "today: no list, no tick",
                    [words("restore.impact.security_today", BODY, TEXT_1, w=420)],
                    w=460,
                )
            )
        return restore_frame(px, sid, 2, b, a, insets=ins)
    if sid == "RW-6":
        b, a = restore_step3(px, replaced=True)
        if "config-only" in insets:
            ins.append(
                inset(
                    px,
                    "RW-6",
                    "config only: the record is kept",
                    [
                        words("restore.confirm.reason", BODY, TEXT_1, w=440),
                        marker("Backup restored", "backup.restore"),
                    ],
                    w=480,
                )
            )
        return restore_frame(px, sid, 3, b, a, insets=ins)
    if sid == "RW-8":
        b, a = restore_step3(px, refused="restore.refused.running")
        if "outcome-unknown" in insets:
            ins.append(
                inset(
                    px,
                    "RW-8",
                    "no answer: never re-sent alone",
                    [rich("restore.unknown", w=520)],
                    w=560,
                )
            )
        return restore_frame(px, sid, 3, b, a, insets=ins)
    if sid == "RW-10":
        bks = [b._replace(status="restored") if b is RESTORE_POINT else b for b in BACKUPS]
        return scr146(
            px,
            sid,
            backups=bks,
            extra_top=[
                notice(
                    copy("restore.after_signin", yyyy_mm_dd=RESTORE_POINT.when[:10]),
                    "info",
                    w=SIZES[px].inner,
                    name="after sign-in",
                )
            ],
        )
    if sid == "RW-12":
        b, a = restore_outcome(px, "summary")
        return restore_frame(px, sid, 6, b, a, statuses=restore_statuses(6, 5))
    if sid == "RW-14":
        return wide_200(px, "zoom" if "zoom" in tag else "text")
    raise KeyError(sid)


def _wizard_preset(px: int, sid: str, insets: tuple[str, ...]) -> Node:
    if sid == "WZ-4":
        b, a = onboard_step3(px, "key")
        return onboard_frame(px, sid, 3, b, a, statuses=onboard_statuses("key"))
    if sid in ("WZ-5", "WZ-16"):
        b, a = onboard_step3(px, "blocked")
        return onboard_frame(px, sid, 3, b, a, statuses=onboard_statuses("blocked"))
    if sid == "WZ-1":
        b, a = onboard_start(px)
        ins = [wz15_inset(px)] if "WZ-15" in insets else []
        if ins:
            state("WZ-15")
        return onboard_frame(
            px, sid, 1, b, a, statuses=onboard_statuses("start"), insets=ins, h2="Onboard a manager"
        )
    if sid == "WZ-6":
        b, a = onboard_step3(px, "revisit")
        return onboard_frame(px, sid, 3, b, a, statuses=onboard_statuses("revisit"))
    if sid == "WZ-11":
        b, a = onboard_invite(px)
        return onboard_frame(px, sid, 8, b, a, statuses=onboard_statuses("invite"))
    if sid == "WZ-12":
        return onboard_frame(
            px,
            sid,
            4,
            [onboard_resume_top()],
            [button("Back", "secondary"), continue_to(5)],
            statuses=onboard_statuses("resume"),
        )
    if sid == "IW-3":
        ins = [iw9_inset(px)] if "IW-9" in insets else []
        if ins:
            state("IW-9")
        return invitee_frame(px, sid, 3, invitee_totp(px), insets=ins)
    if sid == "IW-4":
        return invitee_frame(px, sid, 4, orientation_card(px, "manager"))
    raise KeyError(sid)


def build_frame(f: F) -> Node:
    """The planned frame f, built from its state id with the kit's presets (the worked example, §0's insets) and named
    for its board (at()). Generators may build their own instead; every builder above is public."""
    sid, px = f.sid, f.px
    if sid.startswith("sheet-"):
        fr = fc_column(px) if sid == "sheet-fc" else status_sheet_column(f.tag, px)
    elif sid.startswith("HL-"):
        fr = _scr143_preset(px, sid, f.insets)
    elif sid.startswith("IL-"):
        fr = scr144(px, sid)
    elif sid.startswith("BK-"):
        fr = _scr146_preset(px, sid, f.insets)
    elif sid.startswith("RW-"):
        fr = _restore_preset(px, sid, f.insets, f.tag)
    elif sid.startswith(("WZ-", "IW-")):
        fr = _wizard_preset(px, sid, f.insets)
    elif sid.startswith("GV-"):
        fr = scr062(px, sid)
    elif sid == "SI-1":
        fr = inspector(
            px,
            sid,
            rowless="rowless" in f.insets,
            insets=(
                [
                    inset(
                        px,
                        "SI-1",
                        "a latched kind with no rows (B8)",
                        [
                            words(
                                "machine.rowless",
                                BODY,
                                TEXT_1,
                                w=420,
                                kind="position_protection",
                                n=1,
                            )
                        ],
                        w=460,
                    )
                ]
                if "rowless" in f.insets
                else []
            ),
        )
    elif sid == "SI-6":
        fr = inspector(px, sid, overlays=latch_dialog(px))
    else:
        raise KeyError(f"no preset for {sid}")
    return at(fr, f)


L_ANCHORS = find_line("### 5.2 Continuity with E04-D01")


def anchors() -> list[str]:
    """§5.2's continuity anchors, one line each: 'anchor: E04 → D05 — kept or superseded (why)'."""
    out = []
    for i in range(L_ANCHORS, L_ANCHORS + 20):
        row = L(i)
        if not row.startswith("| ") or row.startswith(("| Anchor", "| ---")):
            continue
        c = [x.strip() for x in row.strip().strip("|").split(" | ")]
        out.append(f"{c[0]}: E04 {c[1]} → D05 {c[2]} — {c[3]} (L{i})")
    return out


def board_parts(
    nn: int, blocks: dict[str, dict[str, Any]] | None = None
) -> tuple[list[list[Node]], list[Node]]:
    """Every planned frame of board nn built (build_frame) in the plan's rows, and one annotation group per state
    (ann_group, its copy keys and tokens counted per state), blocks= per-state overrides (decisions=, keyboard=, …).
    """
    order: list[tuple[str, str]] = []
    by_state: dict[tuple[str, str], list[F]] = {}
    for f in plan_frames(nn):
        key_ = (f.sid, f.tag if f.sid in ("RW-14",) or f.sid.startswith("sheet-") else "")
        if key_ not in by_state:
            order.append(key_)
        by_state.setdefault(key_, []).append(f)
    built: dict[F, Node] = {}
    groups: list[Node] = []
    for key_ in order:
        mark()
        fs = by_state[key_]
        for f in fs:
            built[f] = build_frame(f)
        sid = key_[0]
        ins = [f"{sid} · {x}" for f in fs for x in f.insets]
        bl = dict((blocks or {}).get(sid if not key_[1] else f"{sid} · {key_[1]}", {}))
        if nn == 1:
            bl.setdefault(
                "E04 counterpart (§5.2)", f"{fs[0].tag} (E04-D01's frame, placed beside this one)"
            )
        groups.append(
            ann_group(
                sid if sid in STATES else f"status sheet · {key_[1]}",
                [built[f] for f in fs],
                bl,
                insets=ins,
            )
        )
    rows = [[built[f] for f in row] for row in BOARDS[nn].rows]
    return rows, groups


# --- Self-test: python3 -I e42d05kit.py selftest  (checks + 00-selftest.json, validated).
def _deck_strings() -> list[tuple[int, str]]:
    """Every quoted string in §15's keyed rows and §8.2's first column (for the coverage check)."""
    out = []
    for ln in list(range(DECK_LO, DECK_HI)) + list(range(IMPACT_LO, IMPACT_HI)):
        row = L(ln)
        if not row.startswith("| `") or row.startswith("| `Keys"):
            continue
        cells = row.strip().strip("|").split(" | ")
        cell = cells[0] if ln < DECK_LO else cells[1]
        out += [(ln, s_) for s_ in re.findall(r'"([^"]+)"', cell)]
    return out


def _checks() -> list[tuple[str, bool, str]]:
    res: list[tuple[str, bool, str]] = []

    def check(name: str, ok: bool, detail: str = "") -> None:
        res.append((name, bool(ok), detail))

    check("spec md5", hashlib.md5(SPEC.read_bytes()).hexdigest() == SPEC_MD5, SPEC_MD5)
    vals = {v for v, _ln in COPY.values()} | {v for v, _s in INHERITED.values()}
    unc = [(ln, s_) for ln, s_ in _deck_strings() if s_ not in vals and s_ not in PARSE_SKIP]
    check(
        "copy deck coverage",
        all(s_ in NOT_COPY for _ln, s_ in unc),
        f"{len(COPY)} keys; strings not keyed: {[(ln, s_[:40]) for ln, s_ in unc]}",
    )
    check(
        "states parsed",
        len(STATES) == 107 and all(f"{p}-1" in STATES for p in SCREEN_OF),
        f"{len(STATES)} ids",
    )
    plan = PLAN.read_text(encoding="utf-8")
    missing = []
    for nn, b in BOARDS.items():
        row = next((ln for ln in plan.splitlines() if ln.startswith(f"| {nn:02d} ")), "")
        if f"`{b.slug}`" not in row:
            missing.append(f"{nn}: slug")
        for f in plan_frames(nn):
            if not f.sid.startswith("sheet-") and f.sid not in row:
                missing.append(f"{nn}: {f.sid}")
            if f"[{f.old}]" not in row and not f.sid.startswith("sheet-") and nn != 1:
                missing.append(f"{nn}: [{f.old}]")
        if (b.theme == "light") != (
            "| light |" in row.replace("  ", " ").replace(" light ", " light ")
        ):
            pass
    check("plan rows", not missing, "; ".join(missing))
    check("57 frames", sum(len(plan_frames(n)) for n in BOARDS) == 57)
    check(
        "renders on boards 02, 03, 04, 06",
        STAR_BOARDS == (2, 3, 4, 6) and "renders on **4 boards**" in plan,
    )
    bad = [
        kk
        for kk, (v, _ln) in COPY.items()
        if kk.startswith("admin.") and (len(v) > 60 or not v.endswith("."))
    ]
    check("admin.* reasons ≤ 60, a full stop", not bad, str(bad))
    cases = re.findall(r"`(admin\.[a-z_]+)`", " ".join(SPEC_LINES[T2_LINE - 1 : T2_LINE + 30]))
    nokey = [c_ for c_ in set(cases) if c_ not in COPY and c_ not in INHERITED and c_ not in k.COPY]
    check("§4.1 T2 cases have strings", not nokey, str(sorted(nokey)))
    for nn, bd_ in BOARDS.items():
        try:
            rows, groups = board_parts(nn)
            sizes_ok = all(
                (fr["w"], fr["h"]) == (SIZES[px].w, SIZES[px].h)
                for row, fs in zip(rows, bd_.rows)
                for fr, px in zip(row, [f.px for f in fs])
            )
            c = compose(nn, rows, ann_column(nn, groups))
            never = [
                n["name"]
                for fr in c["frames"]
                for n in walk(fr)
                if n.get("color") in NEVER_TOKENS
                or any(v in NEVER_TOKENS for v in (n.get("o") or {}).values())
            ]
            check(
                f"board {nn:02d} builds and fits its cell",
                sizes_ok and not never,
                f"{c['board']['w']} x {c['board']['h']}; frames 1:1 {sizes_ok}; never-tokens {never}",
            )
        except Exception as e:  # noqa: BLE001 (reported, not swallowed)
            check(f"board {nn:02d} builds and fits its cell", False, f"{type(e).__name__}: {e}")
        reset_notes()
    check("grid", grid_xy(1) == (0, 0) and grid_xy(6) == (0, 9500) and grid_xy(10) == (24000, 9500))
    check(
        "names",
        board_name(3) == "E42-D05 / 03 scr143-144-populated · 1280×800+2560×1440 · dark"
        and footer_text(7) == "page E42-D05 · board 07 · r1"
        and export_path(5) == "docs/design/E42/img/E42-D05-05-scr146-list-download.png",
    )
    imp = [kk.split(".")[-1] for kk in COPY if kk.startswith("restore.impact.")]
    check(
        "§8.2 impact keys",
        set(IMPACT_ORDER) <= set(imp)
        and {"market_on", "security_list", "security_ack", "signout", "audit"} <= set(imp),
        str(imp),
    )
    return res


def selftest() -> int:
    res = _checks()
    reset_notes()
    fs = [
        F("HL-2", 1280, "06", "", ("client-tile",)),
        F("BK-12", 1280, "46"),
        F("RW-3", 1280, "54"),
        F("WZ-5", 1280, "71"),
        F("sheet-dark", 1280, "02", "dark"),
    ]
    BOARDS[0] = Bd(0, "selftest", "dark", (tuple(fs[:3]), tuple(fs[3:])), False, ("restore",))
    try:
        rows, groups = board_parts(0, {"HL-2": {"decisions": "D1-D5, D9, D10 (§2)"}})
        ann = ann_column(
            0,
            groups,
            [
                focus_overlay("SCR-143"),
                focus_overlay("restore", stepper=True),
                ann_block("Continuity anchors (§5.2)", anchors()[:3]),
            ],
            subtitle="Kit self-test (not a planned board): one frame per family.",
        )
        summ = write_board(0, rows, ann, packed=False)
        res.append(
            (
                "00-selftest.json validates",
                summ["valid"][0] == 0,
                (
                    f"{summ['valid'][1]}; {summ['sections']} sections, {summ['nodes']} nodes, largest "
                    f"{summ['largest']} B"
                ),
            )
        )
    finally:
        BOARDS.pop(0, None)
    fails = 0
    for nm, ok, det in res:
        print(f"{'PASS' if ok else 'FAIL'} {nm}{': ' + det if det else ''}")
        fails += not ok
    print(f"{len(res) - fails} PASS, {fails} FAIL")
    return 1 if fails else 0


if __name__ == "__main__":
    if sys.argv[1:] == ["selftest"]:
        sys.exit(selftest())
    print(__doc__)
