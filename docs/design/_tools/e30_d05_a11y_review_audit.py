"""E30-D05 (#918) audit: the accessibility review of the ticket, the confirmation and the defaults.

Stdlib only, offline (`python3 -I -B`). It reads the spec and the pins file from the working tree,
and every cited file AS TEXT at the pinned base with `git show`. It imports, never copies: E11-D07's
key-map engine (`nrm`, `expand_keys`, `load_keymap`, `shipped_bindings`, `load_reserved`,
`coactive`, `parse_05_hotkeys`), the E30-D04 audit's resolver and `col`, `ratio`, `over`, `grey`,
`VALIDITY`, `FLASH` and its `cvd` module (`docs/research/_tools/cvd_simulate.py`: `simulate`,
`delta_e76`, `srgb_to_xyz`, `xyz_to_lab`), and the E30-D02 / E30-D03 audits' `PAIRS`;
`contrast_check.py`'s `contrast_ratio()` is reached through E30-D04's `ratio`. Eleven gates, each
FAIL led by its code:

- [G1-INVENTORY] section 2 lists the seven surfaces and sixteen components as reviewed and
  CMP-104 / CMP-106 with the ruled out-of-scope words; section 0's board counts equal the merged
  E30 images at the base.
- [G2-KEYS] section 3: every KS step names a key and no pointer, every step has an escape, the
  three sequences are all there; section 4: every binding equals the shipped default, the
  `requires_arm` cell is yes / no, a destructive key has a modifier, submit and cancel-all are no
  single letter, no row says `requires_arm` yes while section 4 says none ships, the co-active
  collision and reserved-key sentence matches the engine, and `05`'s three drifted Trading rows
  still drift.
- [G3-R5] section 5: AR-01..AR-17, the R5 cell from the two words, no never-gated row names
  `arm.locked` / `arm.unknown`, every backticked route is a `22` operationId at the base, every
  arm-gated row names one, the FREEZE and view-as legs of AR-13 / AR-14 as ruled (A34: FREEZE and
  view-as leave both enabled, no `rbac.view_as` and no FREEZE reason anywhere on the AR-13 row),
  AR-04 names the arm lapsing mid-dialog (LR-07), AR-11's disarm never a dialog.
- [G4-T2] section 6: a class per row; no row greys "Flatten now" or "Set stop by hand" or shows
  the FREEZE close reason (A34); a T2 row's rendering (2a / 2b / sentence), its checks, no
  disabled token; a `rbac.*` reason is one sentence of at most 60 characters with no digit; every
  `key` "string" pair stands verbatim in a parent unless PROPOSED.
- [G5-LIVE] section 8: a politeness and a maximum rate on every row, assertive rows once per
  event, the A30 / A31 rows and C20 as ruled, the deck pairs verbatim.
- [G6-COLOUR] section 11's carriers and the measured CR rows; section 12's union line and CT rows;
  section 13's flash numbers, all recomputed.
- [G7-VERDICT] sections 7.1 and 14: a verdict from R-3's list; `at risk` names a Major F row or an
  interim path, `non-compliant` a Blocking one.
- [G8-FINDINGS] section 15: counts against the heading and the marker; severity, owner (a spec and
  an area, never an agent), target E30-D06 (#919), R5 and G-T2 cells (a row with neither filled
  fails); the hold sentence while a Blocking row stands; no dangling F id, nor an AR, LR, T2, CF,
  SD, CR, CT, G or Q id defined in no table; F-01 greys every write except the carve-out and quotes
  E09-D09 step 3a and says "never refused on the view-as leg" (R0315); AR-13, AR-14 and Feature 3
  say the view-as write is "audited as the viewer"; KS-X03 cites AR-11;
  section 19's row counts.
- [G9-RULED] every A30 to A34 stamp, at every site (STAMP_LINES, STAMP_LEADS), in the
  exact form with its own row and date, no stamp at an unchecked site, and the ruled words
  (RULING_PINS), and 7.2 (d)'s range held at 10–60 s with no extend; with `--source NAME=FILE` each pin also stands in that saved copy of the ruling.
- [G10-CITE] every `KEY`:line cite resolves at the base to a non-blank line; the pins file and the
  cited endpoints match both ways, each pin's words on its line; every cited file identical at the
  BQ list's base.
- [G11-HYGIENE] no word or substring on the lane's public-text list, host, uuid, local path, URL
  or closing keyword; no fixture account or decimal amount in a quoted example string (sections 3,
  5, 6, 8.1, 15 and 17).

`--json` prints the numbers and findings; `--check` exits 1 on any FAIL (0 FAIL, 0 WARN is the
bar); `--self-test` applies one mutation per gate (MUTATIONS) and the probes (PROBES) to an
in-memory copy and passes only when each adds exactly one new FAIL with its gate's code, a re-run
reproduces the base result and no file on disk changed. `--repin` rewrites the pins file from the
spec's cites (keeping every hand-written pin still cited).

Usage: python3 -I -B docs/design/_tools/e30_d05_a11y_review_audit.py [--check] [--json]
       [--self-test] [--repin] [--source R918=FILE] [--source LA=FILE] [--source LA33=FILE]
       [--source R0315=FILE]
"""

from __future__ import annotations

import argparse
import codecs
import hashlib
import importlib.util
import json
import re
import subprocess
import sys
from collections.abc import Callable
from pathlib import Path
from types import ModuleType
from typing import Any, NamedTuple

ROOT = Path(__file__).resolve().parents[3]
TOOLS = ROOT / "docs" / "design" / "_tools"
SPEC = ROOT / "docs" / "design" / "E30" / "E30-D05.md"
PINS = TOOLS / "e30_d05_ruled_pins.txt"
BASE = "064aa16b9b"  # origin/main; every cite is read here
BQ_BASE = "2ac666b20b"  # where the BQ list (6513348656) read every cite
KEYS = {
    "05": "docs/plan/05-accessibility-standard.md",
    "14": "docs/plan/14-screens-catalogue.md",
    "15": "docs/plan/15-component-catalogue.md",
    "22": "docs/plan/22-api-openapi.yaml",
    "24": "docs/plan/24-internal-schemas.md",
    "DS": ".claude/rules/32-design-specs.md",
    "D02": "docs/design/E30/E30-D02.md",
    "D03": "docs/design/E30/E30-D03.md",
    "D04": "docs/design/E30/E30-D04.md",
    "E09-D09": "docs/design/E09/E09-D09.md",
    "E17-D01": "docs/design/E17/E17-D01.md",
    "E29-D05": "docs/design/E29/E29-D05.md",
    "E39-D03": "docs/design/E39/E39-D03.md",
    "KM": "apps/web/src/keymap/keymap.json",
    "CD": "packages/ui/src/components/ConfirmDialog.tsx",
    "PREF": "apps/web/src/features/a11y-preferences/model.ts",
    "CONST": "CONSTITUTION.md",
    "E30.json": "docs/plan/backlog/E30.json",
}
DECKS = ("D02", "D03", "D04", "E09-D09")  # a quoted `key` "string" stands verbatim in one of them
IMG_DIR = "docs/design/E30/img"
BOARDS = {"D02": 16, "D03": 14, "D04": 24}
SURFACES = ("SCR-060", "SCR-061", "SCR-076", "SCR-077", "SCR-113", "SCR-114", "SCR-158")
COMPONENTS = (  # D04's fifteen and CMP-044
    *(f"CMP-{n}" for n in (100, 101, 102, 103, 105, 107, 119, 121, 122, 130, 139, 158)),
    *(f"CMP-{n}" for n in (229, 231, 232)),
    "CMP-044",
)
OUT_OF_SCOPE = ("CMP-104", "CMP-106")
OUT_WORDS = "out of scope — no E30 spec draws them"
GATED, CARVE = "submit — arm-gated", "carve-out — never arm-gated"
R5_VOCAB = (GATED, CARVE, "n/a")
GT2_RE = re.compile(r"^(?:T2 · (?:2a|2b|sentence)\b.*|validity|busy|n/a)$")
AR_IDS = tuple(f"AR-{i:02d}" for i in range(1, 18))
ARM_REASONS = ("arm.locked", "arm.unknown")
T2_CHECKS = ("1a–d · 2 · 3 · 4 · 6", "1a–d · 2 · 3 · 4 · 5 · 6")
DISABLED_TOKENS = ("opacity.disabled", "color.text.disabled")
POLITENESS = ("polite", "assertive", "off", "never spoken", "none")
RATE_RE = re.compile(r"once|per |never|≤|marks?|on focus|debounced")
SEVERITIES = ("Blocking", "Major", "Minor", "Info")
VERDICT_RE = re.compile(
    r"^(?:compliant|at risk|non-compliant|out of scope — .+|not yet decidable — routed to E30-Q05)$"
)
OWNER_RE = re.compile(r"^E\d\d-D\d\d · area/[a-z-]+$")
AGENT_RE = re.compile(r"worker|agent|hpe-|session", re.IGNORECASE)
TARGET = "E30-D06 (#919)"
HOLD = "cannot be Done until fixed or an exception is recorded on #918"
STAMP = "RULED (orchestrator, 2026-10-30, #2701 ledger addendum A row {})"
WALK = "owner walkthrough: post-Done (#2701)"
R5_NAME = "R5 (arm carve-out, `DS`:74–78)"
FROZEN = "Frozen — the owner closes or releases"
VIEWER = "audited as the viewer"
LAPSE = "the arm lapsing mid-dialog included (LR-07)"
RANGE_WORDS = ("The user range stays 10–60 s", "no extend affordance is added")
# The ruled words, by ruling (R918 = #918 6513445642; LA = #2701 ledger addendum A, 6513450133;
# LA33 / LA34 = its rows A33 (6514063706) and A34 (6514157772); R0315 = the 03:15Z and 03:23Z
# rulings on the PR); each stands in the spec,
# and in the saved copy given with --source.
RULING_PINS: dict[str, tuple[str, ...]] = {
    "R918": (
        R5_NAME,
        HOLD,
        FROZEN,
        "Your trading defaults could not be loaded — the ticket uses your profile's values.",
        "Limit unavailable — checked by the server when you save",
        WALK,
        OUT_WORDS,
        "not yet decidable — routed to E30-Q05",
    ),
    "LA": (
        "Assertive, once, with its reason.",
        "The keymap is the truth; the `05` rows are corrected to it",
        "Superseded by the review's routing table",
    ),
    "LA33": (
        "2.2.1's essential exception",
        "stale-priced submit",
        "Confirmation timed out — nothing was sent",
        "re-opening the confirmation costs one press",
    ),
    "LA34": (
        "Corrected to the contract.",
        "stay enabled under FREEZE on every leg the carve-out binds",
        "is not a reason any carve-out control shows",
    ),
    "R0315": ("greys every write except the carve-out",),
}
STAMP_ROWS = ("A30", "A31", "A32", "A33", "A34")
STAMP_RE = re.compile(r"RULED \(orchestrator, (?!R918)[^)]*\)")
# Every stamp site: a table row or bullet by its opening words (each stamp on it is that row's),
# or the words that lead into the stamp where one line carries several.
STAMP_LINES = {
    "| AR-13 ": "A34",
    "| AR-14 ": "A34",
    "| C-i ": "A34",
    "| C-b ": "A31",
    "| C-c ": "A31",
    "| C-d ": "A30",
    "| C-f ": "A32",
    "| A-1 ": "A32",
    "| A-2 ": "A32",
    "| A-3 ": "A32",
    "| A-4 ": "A30",
    "| A-5 ": "A31",
    "| A-6 ": "A30",
    "| CF-06 ": "A33",
    "| F-06 ": "A33",
    "| Q-03 ": "A33",
    "| 2.2.1 Timing adjustable ": "A33",
    "- **(d) WCAG 2.2.1": "A33",
    "- **Over-announcing": "A31",
    "- **O-L.**": "A30",
}
STAMP_LEADS = {
    "O-L = **": "A30",
    "the throttle text of `T` = **": "A31",
    "the `05` hotkey rows = **": "A32",
    "against WCAG 2.2.1 = **": "A33",
    "A-1 to A-3, ": "A32",
    "is corrected to the contract = **": "A34",
}
F01_WORDS = (
    "greys every write except the carve-out",
    "(every write; the C-2.6 carve-out excepted)",
    "never refused on the view-as leg",
)
CARVE_CONTROLS = ('"Flatten now"', '"Set stop by hand"')
ENABLED = "FREEZE and view-as leave it enabled"
F01_NEVER = ("every other leg", "under every leg")
ID_KINDS = ("AR", "LR", "T2", "CF", "SD", "CR", "CT", "G", "Q")
CR_MEASURED = ("CR-01", "CR-02", "CR-03", "CR-04", "CR-05", "CR-06")
SIMS = ("protanopia", "deuteranopia", "tritanopia")
BARS = {"text": 4.5, "non-text": 3.0, "hc-text": 7.0}
BANNED_ROT13 = (
    "yrnx rkcbfrq olcnff rkcybvg nggnpx benpyr erirny haobhaqrq sybbq fgnyy nqivfbel TUFN cer-nhgu"
)
BANNED = codecs.decode(BANNED_ROT13, "rot13").split()
BANNED_WORD = re.compile(r"\b" + codecs.decode("qbf", "rot13") + r"\b", re.IGNORECASE)
HOST = re.compile(
    r"\b[a-z0-9-]+(?:\.[a-z0-9-]+)*\.(?:com|net|org|io|dev|app|cloud)\b", re.IGNORECASE
)
UUID = re.compile(
    r"\b[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}\b", re.IGNORECASE
)
FIXTURE = re.compile(r"\b(?:Main|Desk4|Core3|sub_00\d)\b|(?<![\w.-])\d[\d,]*\.\d")
QUOTED = re.compile(r'"([^"\n]*)"')
CITE = re.compile(r"`([A-Za-z0-9.\-]+)`:(\d+)(?:–(\d+))?")
PAIR = re.compile(r'`([a-z_][a-z0-9_.*]*)` "([^"]+)"')


def _load(name: str) -> ModuleType:
    spec = importlib.util.spec_from_file_location(name, TOOLS / f"{name}.py")
    if spec is None or spec.loader is None:
        raise SystemExit(f"cannot load {name}")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


E11: Any = _load("e11_d07_a11y_review_audit")
D02T: Any = _load("e30_d02_ticket_audit")
D03T: Any = _load("e30_d03_confirm_audit")
D04T: Any = _load("e30_d04_ds_motion_audit")


def git_show(rev: str, rel: str) -> str:
    out = subprocess.run(
        ["git", "-C", str(ROOT), "show", f"{rev}:{rel}"], capture_output=True, check=False
    )
    return out.stdout.decode("utf-8") if out.returncode == 0 else ""


def git_ls(rev: str, rel: str) -> list[str]:
    out = subprocess.run(
        ["git", "-C", str(ROOT), "ls-tree", "--name-only", rev, rel + "/"],
        capture_output=True,
        check=False,
    )
    return out.stdout.decode("utf-8").split() if out.returncode == 0 else []


class Ctx(NamedTuple):
    spec: str
    tool: str
    pins: str
    base: dict[str, str]
    bq_base: dict[str, str]
    sources: dict[str, str]
    images: tuple[str, ...]


class Result:
    def __init__(self) -> None:
        self.fails: list[str] = []
        self.warns: list[str] = []
        self.numbers: dict[str, object] = {}

    def fail(self, code: str, msg: str) -> None:
        self.fails.append(f"[{code}] {msg}")


def load_ctx(sources: dict[str, str]) -> Ctx:
    return Ctx(
        spec=SPEC.read_text(encoding="utf-8"),
        tool=Path(__file__).read_text(encoding="utf-8"),
        pins=PINS.read_text(encoding="utf-8") if PINS.exists() else "",
        base={k: git_show(BASE, v) for k, v in KEYS.items()},
        bq_base={k: git_show(BQ_BASE, v) for k, v in KEYS.items()},
        sources=sources,
        images=tuple(Path(p).name for p in git_ls(BASE, IMG_DIR)),
    )


# --- markdown helpers ---------------------------------------------------------------------------
def section(text: str, head: str) -> str:
    """The body under `## {head}` (or `### {head}`) up to the next heading of that level or above."""
    m = re.search(rf"^(#{{2,3}}) {re.escape(head)}", text, re.MULTILINE)
    if not m:
        return ""
    level = len(m.group(1))
    rest = text[m.end() :]
    end = re.search(rf"^#{{2,{level}}} ", rest, re.MULTILINE)
    return rest[: end.start()] if end else rest


def cells(line: str) -> list[str]:
    body = line.strip()[1:-1]
    out, cur, code = [], "", False
    for ch in body:
        if ch == "`":
            code = not code
        if ch == "|" and not code:
            out.append(cur.strip())
            cur = ""
        else:
            cur += ch
    out.append(cur.strip())
    return out


def rows(block: str) -> list[list[str]]:
    """Every table body row in the block (header and rule lines dropped)."""
    lines = block.splitlines()
    out: list[list[str]] = []
    for i, ln in enumerate(lines):
        if not ln.startswith("|") or re.match(r"^\|\s*:?-", ln):
            continue
        if i + 1 < len(lines) and re.match(r"^\|\s*:?-", lines[i + 1]):
            continue  # a header
        out.append(cells(ln))
    return out


def by_id(block: str, prefix: str) -> dict[str, list[str]]:
    return {r[0]: r for r in rows(block) if re.fullmatch(prefix + r"-\w+", r[0])}


def norm(text: str) -> str:
    return re.sub(r"\s+", " ", text).strip()


def ticks(cell: str) -> list[str]:
    return re.findall(r"`([^`]+)`", cell)


# --- G1: inventory and boards -------------------------------------------------------------------
def gate_inventory(ctx: Ctx, r: Result) -> None:
    body = section(ctx.spec, "2. Inventory")
    seen: dict[str, str] = {}
    for row in rows(body):
        for item in re.findall(r"\b(?:SCR|CMP)-\d{3}\b", row[0]):
            seen.setdefault(item, row[2] if len(row) > 2 else "")
    for item in (*SURFACES, *COMPONENTS):
        if seen.get(item) != "reviewed":
            r.fail("G1-INVENTORY", f"{item} is not listed as reviewed")
    for item in OUT_OF_SCOPE:
        if seen.get(item) != OUT_WORDS:
            r.fail("G1-INVENTORY", f"{item} lacks the ruled words {OUT_WORDS!r}")
    counts = {k: sum(n.startswith(f"E30-{k}-") for n in ctx.images) for k in BOARDS}
    total = sum(counts.values())
    zero = section(ctx.spec, "0. Status")
    want = [f"the {total} merged E30 boards"] + [f"{k}'s {v} (" for k, v in counts.items()]
    for words in want:
        if words not in zero:
            r.fail("G1-INVENTORY", f"section 0 does not read {words!r} (the base has {counts})")
    if counts != BOARDS:
        r.fail("G1-INVENTORY", f"the merged boards at {BASE} are {counts}, ruled {BOARDS}")
    r.numbers["surfaces"] = sum(seen.get(s) == "reviewed" for s in SURFACES)
    r.numbers["components"] = sum(seen.get(c) == "reviewed" for c in COMPONENTS)
    r.numbers["boards"] = total


# --- G2: keyboard sequences and shortcuts -------------------------------------------------------
POINTER = re.compile(r"pointer|click|mouse|hover|drag", re.IGNORECASE)


def gate_keys(ctx: Ctx, r: Result) -> None:
    body = section(ctx.spec, "3. The keyboard-only sequences")
    steps = by_id(body, "KS")
    want = {"P": 10, "A": 4, "X": 3}
    for kind, least in want.items():
        n = sum(k.startswith(f"KS-{kind}") for k in steps)
        if n < least:
            r.fail("G2-KEYS", f"the KS-{kind} sequence has {n} steps (at least {least})")
    for sid, row in steps.items():
        key, focus, escape = row[1], row[2], row[4] if len(row) > 4 else ""
        arrival = key.startswith("none") and focus.startswith("unchanged")
        if not (ticks(key) or arrival):
            r.fail("G2-KEYS", f"{sid}: the step names no key")
        if POINTER.search(key):
            r.fail("G2-KEYS", f"{sid}: the key cell names a pointer action")
        if not escape:
            r.fail("G2-KEYS", f"{sid}: no escape")
    km = {c["id"]: c for c in E11.load_keymap()["commands"]}
    table = rows(section(ctx.spec, "4. The trading shortcuts"))
    bound: set[str] = set()
    ids: list[str] = []
    for row in table:
        cmd, binding, arm = ticks(row[1]), ticks(row[2]), row[3]
        if not cmd or cmd[0] not in km or not binding:
            r.fail("G2-KEYS", f"shortcut row {row[0]!r}: no shipped command or binding")
            continue
        c, keys = km[cmd[0]], [E11.nrm(k) for k in E11.expand_keys(binding[0])]
        ids.append(cmd[0])
        shipped = [E11.nrm(k) for k in E11.expand_keys(c["defaultBinding"])]
        if keys != shipped:
            r.fail("G2-KEYS", f"{cmd[0]}: the spec binds {keys}, the key map ships {shipped}")
        if arm not in ("yes", "no"):
            r.fail("G2-KEYS", f"{cmd[0]}: `requires_arm` is {arm!r}, not yes / no")
        single = [k for k in keys if "+" not in k and len(k) == 1]
        if c.get("destructive") and single:
            r.fail("G2-KEYS", f"{cmd[0]}: a destructive key without a modifier")
        if cmd[0] in ("ticket.submit", "dom.cancel_all") and single:
            r.fail("G2-KEYS", f"{cmd[0]}: a single unmodified key for submit or cancel")
        bound.update(keys)
    shipped_rows = [b for b in E11.shipped_bindings(E11.load_keymap()) if b["id"] in ids]
    allb = E11.shipped_bindings(E11.load_keymap())
    undeclared = 0
    for b in shipped_rows:
        for o in allb:
            same = o["key"] == b["key"] and o["id"] != b["id"]
            if same and E11.coactive(o["context"], b["context"]):
                undeclared += o["id"] not in b["shadows"] and b["id"] not in o["shadows"]
    reserved = E11.load_reserved()
    held = sorted({b["key"] for b in shipped_rows if b["key"] in reserved})
    naked = [b["id"] for b in shipped_rows if b["key"] in reserved and not b["reservedOverride"]]
    four = section(ctx.spec, "4. The trading shortcuts")
    sentence = f"the {len(table)} rows bind {len(bound)} keys after expansion; " + (
        "none collides with a co-active binding" if not undeclared else f"{undeclared} collide"
    )
    if norm(sentence) not in norm(four.replace("twelve", "12")):
        r.fail("G2-KEYS", f"section 4 does not read {sentence!r}")
    if (
        held != ["Ctrl+Shift+T"]
        or naked
        or "one key (`Ctrl+Shift+T`) is browser-reserved" not in four
    ):
        r.fail("G2-KEYS", f"reserved keys {held}, without an override {naked}")
    armed = [ticks(x[1])[0] for x in table if ticks(x[1]) and x[3] == "yes"]
    if armed or "No `requires_arm` binding of the ticket ships today" not in four:
        r.fail(
            "G2-KEYS", f"`requires_arm` rows {armed} against section 4's 'none ships' (`D02`:350)"
        )
    drift = drift_05()
    if drift != 3:
        r.fail("G2-KEYS", f"`05`'s Trading rows drift from the key map in {drift} places, not 3")
    r.numbers["steps"] = len(steps)
    r.numbers["shortcuts"] = len(table)
    r.numbers["keys"] = len(bound)
    r.numbers["collisions"] = undeclared
    r.numbers["drift_05"] = drift


def drift_05() -> int:
    """`05`'s Trading rows against the key map: B / S as market, presets to 5, Ctrl+Shift+1."""
    km = E11.load_keymap()["commands"]
    keys = {E11.nrm(k) for c in km for k in E11.expand_keys(c["defaultBinding"])}
    rows05 = [x for x in E11.parse_05_hotkeys() if x["category"] == "Trading"]
    n = 0
    for x in rows05:
        ks = E11.hotkey_05_keys(x)
        if "market" in x["action"] and ks == ["B", "S"]:
            labels = {c["label"] for c in km if c["defaultBinding"] in ("B", "S")}
            n += not any("market" in lab.lower() for lab in labels)
        elif "preset" in x["action"].lower():
            n += "5" in ks and not any(
                c["id"] == "ticket.qty_preset" and "5" in E11.expand_keys(c["defaultBinding"])
                for c in km
            )
        elif "1-click" in x["action"]:
            n += any(k not in keys for k in ks)
    return n


# --- G3: the arm table --------------------------------------------------------------------------
def operation_ids(api: str) -> set[str]:
    return set(re.findall(r"^\s+operationId: (\w+)\s*$", api, re.MULTILINE))


def gate_r5(ctx: Ctx, r: Result) -> None:
    table = by_id(section(ctx.spec, "5. The arm table"), "AR")
    ops = operation_ids(ctx.base["22"])
    if tuple(table) != AR_IDS:
        r.fail("G3-R5", f"the arm table holds {list(table)}, ruled {list(AR_IDS)}")
    for aid, row in table.items():
        text, route, r5 = " | ".join(row), row[2], row[3]
        if r5 not in (GATED, CARVE):
            r.fail("G3-R5", f"{aid}: R5 cell {r5!r}")
        if r5 == CARVE and any(a in text for a in ARM_REASONS):
            r.fail("G3-R5", f"{aid}: a never-gated row names an arm reason")
        names = ticks(route)
        if r5 == GATED and not names:
            r.fail("G3-R5", f"{aid}: an arm-gated row names no `22` route")
        for op in names:
            if op not in ops:
                r.fail("G3-R5", f"{aid}: `{op}` is no operationId in `22` at {BASE}")
    wrong = [k for k, v in table.items() if v[3] != (GATED if k <= "AR-08" else CARVE)]
    if wrong:
        r.fail("G3-R5", f"rows whose R5 cell is not as ruled (AR-01..08 gated): {wrong}")
    legs = {k: v[4] if len(v) > 4 else "" for k, v in table.items()}
    if "none on any leg" not in legs.get("AR-14", "") or ENABLED not in legs.get("AR-14", ""):
        r.fail("G3-R5", "AR-14's carve-out is not as ruled (L1 row 82, A34)")
    ar13 = " | ".join(table.get("AR-13", []))
    if ENABLED not in ar13 or FROZEN in ar13 or "rbac.view_as" in ar13:
        r.fail(
            "G3-R5", "AR-13's close is T2 under FREEZE or view-as (A34, R0315: it stays enabled)"
        )
    if LAPSE not in legs.get("AR-04", ""):
        r.fail("G3-R5", "AR-04 does not name the arm lapsing mid-dialog (LR-07, m-3)")
    if "never a dialog" not in legs.get("AR-11", ""):
        r.fail("G3-R5", "AR-11's disarm is not one press, never a dialog")
    r.numbers["arm_rows"] = len(table)
    r.numbers["arm_gated"] = sum(v[3] == GATED for v in table.values())


# --- G4, G5: the T2 table and the routing table -------------------------------------------------
def deck_pairs(row_text: str, ctx: Ctx) -> list[str]:
    """Every `key` "string" pair that stands in no parent deck (PROPOSED rows are exempt)."""
    if "PROPOSED" in row_text:
        return []
    decks = "\n".join(ctx.base[k].replace('\\"', '"') for k in DECKS)
    return [f"{k} {s!r}" for k, s in PAIR.findall(row_text) if s not in decks]


def gate_t2(ctx: Ctx, r: Result) -> None:
    table = by_id(section(ctx.spec, "6. Gated controls"), "T2")
    classes = {"T2": 0, "validity": 0, "busy": 0}
    for tid, row in table.items():
        text = " | ".join(row)
        reason, klass, rendering, r5, checks = row[2], row[3], row[4], row[5], row[6]
        if klass not in classes:
            r.fail("G4-T2", f"{tid}: class {klass!r}")
            continue
        classes[klass] += 1
        if r5 not in R5_VOCAB:
            r.fail("G4-T2", f"{tid}: R5 cell {r5!r}")
        if klass == "T2":
            if not re.match(r"(?:2a|2b|sentence)\b", rendering):
                r.fail("G4-T2", f"{tid}: rendering {rendering!r}")
            want = T2_CHECKS[1] if "notice" in rendering else T2_CHECKS[0]
            if checks.split(";")[0] != want:
                r.fail("G4-T2", f"{tid}: checks {checks!r}, want {want!r}")
            if any(t in text for t in DISABLED_TOKENS):
                r.fail("G4-T2", f"{tid}: a T2 row names a disabled token")
        elif not checks.startswith("outside the grammar"):
            r.fail("G4-T2", f"{tid}: a {klass} row is not marked outside the grammar")
        for key, s in PAIR.findall(reason):
            bad = len(s) > 60 or not s.endswith(".") or re.search(r"\d", s)
            if key.startswith("rbac.") and bad:
                r.fail("G4-T2", f"{tid}: `{key}` {s!r} is not a data-free sentence of <= 60")
        r.fails.extend(f"[G4-T2] {tid}: not in a parent deck: {p}" for p in deck_pairs(text, ctx))
    for tid, row in table.items():
        if any(w in row[1] for w in CARVE_CONTROLS) or FROZEN in row[2]:
            r.fail("G4-T2", f"{tid}: a carve-out control greyed, or the FREEZE close reason (A34)")
    r.numbers["t2_rows"] = len(table)
    r.numbers["t2_classes"] = classes


def gate_live(ctx: Ctx, r: Result) -> None:
    table = by_id(section(ctx.spec, "8.1 The routing table"), "LR")
    tally = dict.fromkeys(POLITENESS, 0)
    for lid, row in table.items():
        text, pol, rate = " | ".join(row), row[3], row[4]
        head = next((p for p in POLITENESS if pol.startswith(p)), "")
        if not head:
            r.fail("G5-LIVE", f"{lid}: politeness {pol!r}")
        else:
            tally[head] += 1
        if not RATE_RE.search(rate):
            r.fail("G5-LIVE", f"{lid}: no maximum rate")
        if head == "assertive" and "once" not in rate:
            r.fail("G5-LIVE", f"{lid}: an assertive row that is not once per event")
        r.fails.extend(f"[G5-LIVE] {lid}: not in a parent deck: {p}" for p in deck_pairs(text, ctx))

    def find(words: str) -> list[str]:
        return next((v for v in table.values() if words in v[1]), ["", "", "", "", "", "", ""])

    ruled = (
        ("hold-to-confirm progress", "never spoken", "never", "A31"),
        ("auto-disarm", "assertive", "once", "A30"),
        ("a `requires_arm` binding", "polite", "once", "C-e"),
        ("read-out line after a user input", "polite", "≤ 1 per 500 ms", "A31"),
        ("WS push alone", "never spoken", "never", "A31"),
        ("an ambient value", "polite", "1 per 2 s", "A31"),
    )
    for event, pol, rate, src in ruled:
        row = find(event)
        if row[3] != pol or rate not in row[4] or src not in row[6]:
            r.fail("G5-LIVE", f"the {event!r} row is not {pol} / {rate} / {src} as ruled")
    lr12 = " | ".join(table.get("LR-12", []))
    if "confirm.timeout.announce" in lr12 or "confirm.countdown.announce10" not in lr12:
        r.fail("G5-LIVE", "LR-12 must name `confirm.countdown.announce10` only (0:00 is silent)")
    r.numbers["live_rows"] = len(table)
    r.numbers["politeness"] = tally


# --- G6: carriers, contrast and flashes ---------------------------------------------------------
def lstar(hex6: str) -> float:
    return float(D04T.cvd.xyz_to_lab(D04T.cvd.srgb_to_xyz(D04T.grey(hex6)))[0])


def carrier_numbers(a: str, b: str) -> tuple[str, str]:
    dl, de = [], []
    for t in D04T.THEMES:
        ha, hb = D04T.col(t, a), D04T.col(t, b)
        dl.append(abs(lstar(ha) - lstar(hb)))
        de += [
            float(D04T.cvd.delta_e76(D04T.cvd.simulate(ha, k), D04T.cvd.simulate(hb, k)))
            for k in SIMS
        ]
    return f"{min(dl):.1f}", f"{min(de):.1f}"


def union() -> dict[tuple[str, str, str], list[str]]:
    """D02 section 15.1, D03 section 13 and D04 section 23.1, by (fg, bg, role); CR rows left out."""
    out: dict[tuple[str, str, str], list[str]] = {}
    for _, fg, bg, role in D02T.PAIRS:
        if not (fg.startswith("CR:") or bg.startswith("CR:")):
            out.setdefault((fg.removeprefix("color."), bg.removeprefix("color."), role), []).append(
                "D02"
            )
    for src, pairs in (("D03", D03T.PAIRS), ("D04", D04T.PAIRS)):
        for line in pairs:
            _, fg, bg, role = line.split("|")
            out.setdefault((fg, bg, role), []).append(src)
    return out


def ratios(fg: str, bg: str) -> list[float]:
    return [float(D04T.ratio(D04T.col(t, fg), D04T.col(t, bg))) for t in D04T.THEMES]


def passes(role: str, v: list[float]) -> bool:
    bar = BARS.get(role)
    return bar is None or (v[2] >= bar if role == "hc-text" else min(v) >= bar)


def union_line() -> str:
    u = union()
    fails, mins = 0, dict[str, float]()
    for fg, bg, role in u:
        v = ratios(fg, bg)
        fails += not passes(role, v)
        if role in BARS:
            m = v[2] if role == "hc-text" else min(v)
            mins[role] = min(mins.get(role, m), m)
    return (
        f"**Union:** {len(u)} (fg, bg, role) rows · gated FAIL {fails} · minima text "
        f"{mins['text']:.2f}, non-text {mins['non-text']:.2f}, hc-text {mins['hc-text']:.2f}"
    )


def validity_range() -> str:
    vals: list[float] = []
    for line in D04T.VALIDITY:
        _, lab, fill, surf = line.split("|")
        for t in D04T.THEMES:
            under = D04T.col(t, surf)
            fg, bg = (D04T.over(D04T.col(t, x), under, 0.45) for x in (lab, fill))
            vals.append(float(D04T.ratio(fg, bg)))
    return f"{min(vals):.2f}–{max(vals):.2f}"


def gate_colour(ctx: Ctx, r: Result) -> None:
    table = by_id(section(ctx.spec, "11. Colour never"), "CR")
    for cid, row in table.items():
        carrier, toks, verdict = row[2], ticks(row[3]), row[6]
        if not carrier or verdict != "distinguishable by carrier":
            r.fail("G6-COLOUR", f"{cid}: carrier or verdict off the rule")
        if cid in CR_MEASURED:
            want = carrier_numbers(*(t.removeprefix("color.") for t in toks[:2]))
            if len(toks) != 2 or (row[4], row[5]) != want:
                r.fail("G6-COLOUR", f"{cid}: ΔL* / ΔE {row[4]} / {row[5]}, computed {want}")
    twelve = section(ctx.spec, "12. Contrast")
    line = union_line()
    if line not in twelve:
        r.fail("G6-COLOUR", f"section 12 does not read {line!r}")
    for tid, row in by_id(twelve, "CT").items():
        toks = [t.removeprefix("color.") for t in ticks(row[2])]
        v = ratios(*toks[:2])
        got = [f"{x:.2f}" for x in v] + ["PASS" if passes(row[3], v) else "FAIL"]
        if row[4:8] != got:
            r.fail("G6-COLOUR", f"{tid}: {row[4:8]}, computed {got}")
    rng = validity_range()
    if f"measures {rng} across" not in twelve:
        r.fail("G6-COLOUR", f"the validity composite range is {rng}")
    flash = [x.split("|") for x in D04T.FLASH]
    moving = [f for f in flash if f[0].startswith("M")]
    worst = max(moving, key=lambda f: int(f[1]))
    loops = [f[0] for f in flash if f[2] == "yes"]
    words = f"{len(moving)} rows and the hatch, the worst {worst[1]} per second ({worst[0]}), " + (
        "none looping" if not loops else f"looping {loops}"
    )
    if words not in section(ctx.spec, "13. Motion") or int(worst[1]) > 3:
        r.fail("G6-COLOUR", f"section 13 does not read {words!r} or a row passes 3 a second")
    r.numbers["carriers"] = len(table)
    r.numbers["union"] = line.removeprefix("**Union:** ")
    r.numbers["validity"] = rng
    r.numbers["flash"] = words


# --- G7: verdicts -------------------------------------------------------------------------------
def severities(spec: str) -> dict[str, str]:
    return {k: v[1] for k, v in by_id(section(spec, "15. Findings"), "F").items()}


def gate_verdict(ctx: Ctx, r: Result) -> None:
    sev = severities(ctx.spec)
    blocks = (
        ("7.1", rows(section(ctx.spec, "7.1 The gates")), 3, 4),
        ("14.1", rows(section(ctx.spec, "14.1 `05` clauses")), 1, 3),
        ("14.2", rows(section(ctx.spec, "14.2 WCAG 2.2 cross-walk")), 1, 3),
    )
    n = 0
    for name, table, vi, ri in blocks:
        for row in table:
            n += 1
            verdict, ref, text = row[vi], row[ri], " ".join(row)
            if not VERDICT_RE.match(verdict):
                r.fail("G7-VERDICT", f"{name} {row[0]!r}: verdict {verdict!r}")
            fids = re.findall(r"\bF-\d\d\b", ref)
            if verdict == "at risk" and not (
                "interim path" in text or any(sev.get(f) in ("Major", "Blocking") for f in fids)
            ):
                r.fail("G7-VERDICT", f"{name} {row[0]!r}: at risk without a Major row or path")
            if verdict == "non-compliant" and not any(sev.get(f) == "Blocking" for f in fids):
                r.fail("G7-VERDICT", f"{name} {row[0]!r}: non-compliant without a Blocking row")
    r.numbers["verdicts"] = n


# --- G8: findings -------------------------------------------------------------------------------
def gate_findings(ctx: Ctx, r: Result) -> None:
    body = section(ctx.spec, "15. Findings")
    table = by_id(body, "F")
    counts = {s: sum(v[1] == s for v in table.values()) for s in SEVERITIES}
    head = re.search(
        r"^## 15\. Findings — F (\d+) \((.*?)\)(?: <!-- audit:f=([\d/]+) -->)?$",
        ctx.spec,
        re.MULTILINE,
    )
    want = f"{len(table)} (" + " · ".join(f"{s} {counts[s]}" for s in SEVERITIES) + ")"
    marker = "/".join(str(x) for x in (len(table), *counts.values()))
    if not head or f"{head.group(1)} ({head.group(2)})" != want or head.group(3) != marker:
        r.fail("G8-FINDINGS", f"the heading or its marker does not read F {want} ({marker})")
    for fid, row in table.items():
        sev, owner, target, r5, gt2 = row[1], row[4], row[5], row[6], row[7]
        if sev not in SEVERITIES:
            r.fail("G8-FINDINGS", f"{fid}: severity {sev!r}")
        if not OWNER_RE.match(owner) or AGENT_RE.search(owner):
            r.fail("G8-FINDINGS", f"{fid}: owner {owner!r} is not a spec and an area")
        if TARGET not in target:
            r.fail("G8-FINDINGS", f"{fid}: the target does not name {TARGET}")
        filled = [c for c in (r5, gt2) if c not in ("", "—", "-")]
        if not filled:
            r.fail("G8-FINDINGS", f"{fid}: neither R5 nor G-T2 is filled")
        if r5 and r5 not in R5_VOCAB:
            r.fail("G8-FINDINGS", f"{fid}: R5 cell {r5!r}")
        if gt2 and not GT2_RE.match(gt2):
            r.fail("G8-FINDINGS", f"{fid}: G-T2 cell {gt2!r}")
    if counts["Blocking"] and (HOLD not in body or HOLD not in section(ctx.spec, "18. Hand-offs")):
        r.fail("G8-FINDINGS", "a Blocking row stands without the hold sentence in 15 and 18")
    dangling = sorted(set(re.findall(r"\bF-\d\d\b", ctx.spec)) - set(table))
    if dangling:
        r.fail("G8-FINDINGS", f"F ids cited but not in section 15: {dangling}")
    defined = {
        k
        for r_ in rows(ctx.spec)
        if (k := r_[0]) and re.fullmatch(r"(?:" + "|".join(ID_KINDS) + r")-\d\d", k)
    }
    cited = set(re.findall(r"\b(?:" + "|".join(ID_KINDS) + r")-\d\d\b", ctx.spec))
    if loose := sorted(cited - defined):
        r.fail("G8-FINDINGS", f"row ids cited but defined in no table: {loose}")
    f01 = " ".join(table.get("F-01", []))
    arm = by_id(section(ctx.spec, "5. The arm table"), "AR")
    legs13, legs14 = (" ".join(arm.get(k, [])) for k in ("AR-13", "AR-14"))
    if not all(w in f01 for w in F01_WORDS) or any(w in f01 for w in F01_NEVER):
        r.fail("G8-FINDINGS", "F-01 does not grey every write except the carve-out (R0315)")
    scenario = ctx.spec.partition("Scenario: The carve-out is never refused")[2].partition("\n\n")[
        0
    ]
    sites = {
        "AR-13": legs13,
        "AR-14": legs14,
        "the carve-out scenario": scenario,
    }
    if gone := [k for k, v in sites.items() if VIEWER not in v]:
        r.fail("G8-FINDINGS", f"the view-as write is not 'audited as the viewer' at {gone}")
    x03 = by_id(section(ctx.spec, "3. The keyboard-only sequences"), "KS").get("KS-X03", [])
    if "AR-11" not in " ".join(x03):
        r.fail("G8-FINDINGS", "KS-X03's disarm does not cite the disarm row AR-11")
    rowcount = {
        "C": len(by_id(section(ctx.spec, "16.1 Contradictions"), "C")),
        "G": len(by_id(section(ctx.spec, "16.2 Gaps"), "G")),
        "Q": len(by_id(section(ctx.spec, "16.3 Open questions"), "Q")),
        "A": len(by_id(section(ctx.spec, "16.4 Copy-ready amendments"), "A")),
        "H": len(
            re.findall(r"^- \*\*H-\d+\*\*", section(ctx.spec, "16.5 Heuristic"), re.MULTILINE)
        ),
    }
    line = "; " + " · ".join(f"{k} {v}" for k, v in rowcount.items()) + "."
    if line not in section(ctx.spec, "19. Summary"):
        r.fail("G8-FINDINGS", f"section 19 does not end its counts with {line!r}")
    r.numbers["findings"] = counts
    r.numbers["rows"] = rowcount


# --- G9: ruled words and stamps -----------------------------------------------------------------
def stamp_sites(spec: str) -> tuple[dict[str, int], list[str]]:
    """Each stamp checked against the row its site names; the sites seen, and the misses."""
    seen: dict[str, int] = {}
    bad: list[str] = []
    for ln in spec.splitlines():
        hits = list(STAMP_RE.finditer(ln))
        if not hits:
            continue
        site = next((k for k in STAMP_LINES if ln.startswith(k)), "")
        for m in hits:
            lead = site or next((k for k in STAMP_LEADS if ln[: m.start()].endswith(k)), "")
            want = STAMP_LINES.get(lead) or STAMP_LEADS.get(lead)
            if not want:
                bad.append(f"a stamp at an unchecked site: {ln[:40]!r}")
            elif m.group(0) != STAMP.format(want):
                bad.append(f"{lead.strip()!r} carries {m.group(0)!r}, not row {want}'s stamp")
            seen[lead] = seen.get(lead, 0) + 1
    missing = sorted(k.strip() for k in (*STAMP_LINES, *STAMP_LEADS) if k not in seen)
    bad += [f"no stamp at {k!r}" for k in missing]
    return seen, bad


def gate_ruled(ctx: Ctx, r: Result) -> None:
    for row in STAMP_ROWS:
        if STAMP.format(row) not in ctx.spec:
            r.fail("G9-RULED", f"the stamp for {row} is missing")
    seen, bad = stamp_sites(ctx.spec)
    for msg in bad:
        r.fail("G9-RULED", msg)
    r.numbers["stamps"] = sum(seen.values())
    checked = 0
    for name, pins in RULING_PINS.items():
        for pin in pins:
            if pin not in ctx.spec:
                r.fail("G9-RULED", f"{name}: the ruled words {pin!r} are not in the spec")
            if name in ctx.sources:
                checked += 1
                if norm(pin.replace("`", "")) not in norm(
                    ctx.sources[name].replace("`", "").replace("**", "")
                ):
                    r.fail("G9-RULED", f"{name}: {pin!r} is not in the saved copy")
    (bullet,) = [ln for ln in ctx.spec.splitlines() if ln.startswith("- **(d) WCAG 2.2.1")] or [""]
    ranges = set(re.findall(r"\d+–\d+ s", bullet))
    if not all(w in bullet for w in RANGE_WORDS) or ranges != {"10–60 s"}:
        r.fail("G9-RULED", "7.2 (d) does not hold the range at 10–60 s with no extend (A33)")
    r.numbers["ruling_pins"] = sum(len(p) for p in RULING_PINS.values())
    r.numbers["sources_checked"] = checked


# --- G10: cites and pins ------------------------------------------------------------------------
def cites(spec: str) -> list[tuple[str, int, int]]:
    return [(k, int(a), int(b or a)) for k, a, b in CITE.findall(spec)]


def parse_pins(text: str) -> dict[tuple[str, int], str]:
    out: dict[tuple[str, int], str] = {}
    for ln in text.splitlines():
        if ln.strip() and not ln.startswith("#"):
            key, line, words = ln.split("|", 2)
            out[(key, int(line))] = words
    return out


def endpoints(spec: str) -> set[tuple[str, int]]:
    return {e for k, a, b in cites(spec) for e in ((k, a), (k, b))}


def gate_cite(ctx: Ctx, r: Result) -> None:
    found = cites(ctx.spec)
    for key, a, b in found:
        lines = ctx.base.get(key, "").splitlines()
        if key not in KEYS:
            r.fail("G10-CITE", f"`{key}`:{a}: an undeclared key")
        elif not (0 < a <= b <= len(lines)) or not lines[a - 1].strip() or not lines[b - 1].strip():
            r.fail("G10-CITE", f"`{key}`:{a}-{b}: out of range or blank at {BASE}")
    pins = parse_pins(ctx.pins)
    for (key, n), words in pins.items():
        lines = ctx.base.get(key, "").splitlines()
        line = lines[n - 1] if 0 < n <= len(lines) else ""
        if not words.strip() or norm(words) not in norm(line):
            r.fail("G10-CITE", f"pin {key}:{n}: {words[:40]!r} is not on that line at {BASE}")
    ends = endpoints(ctx.spec)
    uncited, unpinned = sorted(set(pins) - ends), sorted(ends - set(pins))
    if uncited or unpinned:
        r.fail("G10-CITE", f"pins and cites disagree: uncited {uncited}; unpinned {unpinned}")
    used = {k for k, _, _ in found}
    moved = sorted(k for k in used if ctx.bq_base.get(k) and ctx.bq_base[k] != ctx.base.get(k))
    if moved:
        r.fail("G10-CITE", f"cited files changed between {BQ_BASE} and {BASE}: {moved}")
    r.numbers["cites"] = len(found)
    r.numbers["endpoints"] = len(ends)
    r.numbers["pins"] = len(pins)
    readable = all(ctx.bq_base.get(k) for k in used)
    r.numbers["bq_base"] = f"{BQ_BASE} -> {BASE}: " + ("identical" if readable else "not readable")


def repin(ctx: Ctx) -> int:
    old = parse_pins(ctx.pins)
    lines = []
    for key, n in sorted(endpoints(ctx.spec), key=lambda e: (e[0], e[1])):
        text = norm(ctx.base[key].splitlines()[n - 1])
        lines.append(f"{key}|{n}|{old.get((key, n)) or text[:72].rstrip()}")
    head = (
        "# E30-D05 pins: KEY|line|words that stand on that line at the base (the tool's G10).\n"
        "# `--repin` keeps every hand-written pin still cited and adds the line's opening words.\n"
    )
    PINS.write_text(head + "\n".join(lines) + "\n", encoding="utf-8")
    return len(lines)


# --- G11: hygiene -------------------------------------------------------------------------------
def gate_hygiene(ctx: Ctx, r: Result) -> None:
    for name, text in (("the spec", ctx.spec), ("the tool", ctx.tool), ("the pins", ctx.pins)):
        low = text.lower()
        for word in BANNED:
            if word.lower() in low:
                r.fail("G11-HYGIENE", f"{name}: a word from the public-text list: {word!r}")
        if BANNED_WORD.search(text):
            r.fail("G11-HYGIENE", f"{name}: a word from the public-text list")
        if host := HOST.search(text):
            r.fail("G11-HYGIENE", f"{name}: a host name {host.group(0)!r}")
        if UUID.search(text):
            r.fail("G11-HYGIENE", f"{name}: an id in the uuid form")
    local = "/" + "home/|/tmp/|/mnt/|[A-Z]:\\\\"
    for pat, what in (
        (local, "a local path"),
        (r"https?://", "a host"),
        (r"\b(?:close[sd]?|fix(?:e[sd])?|resolve[sd]?) #\d", "a closing keyword"),
    ):
        if re.search(pat, ctx.spec, re.IGNORECASE):
            r.fail("G11-HYGIENE", f"the spec: {what}")
    examples = "".join(
        section(ctx.spec, h)
        for h in (
            "3. The keyboard",
            "5. The arm table",
            "6. Gated controls",
            "8.1 The routing",
            "15. Findings",
            "17. The screen",
        )
    )
    bad = [q for q in QUOTED.findall(examples) if FIXTURE.search(q)]
    if bad:
        r.fail("G11-HYGIENE", f"an example string with a fixture account or amount: {bad[:2]}")


GATE_FNS: tuple[tuple[str, Callable[[Ctx, Result], None]], ...] = (
    ("G1-INVENTORY", gate_inventory),
    ("G2-KEYS", gate_keys),
    ("G3-R5", gate_r5),
    ("G4-T2", gate_t2),
    ("G5-LIVE", gate_live),
    ("G6-COLOUR", gate_colour),
    ("G7-VERDICT", gate_verdict),
    ("G8-FINDINGS", gate_findings),
    ("G9-RULED", gate_ruled),
    ("G10-CITE", gate_cite),
    ("G11-HYGIENE", gate_hygiene),
)


def run(ctx: Ctx) -> Result:
    r = Result()
    for _, fn in GATE_FNS:
        fn(ctx, r)
    return r


# --- self-test ----------------------------------------------------------------------------------
Mut = Callable[[Ctx], Ctx]


def sub(old: str, new: str) -> Mut:
    return lambda ctx: ctx._replace(spec=ctx.spec.replace(old, new, 1))


def regex(pattern: str, repl: str) -> Mut:
    return lambda ctx: ctx._replace(
        spec=re.sub(pattern, repl, ctx.spec, count=1, flags=re.MULTILINE)
    )


def pin_sub(old: str, new: str) -> Mut:
    return lambda ctx: ctx._replace(pins=ctx.pins.replace(old, new, 1))


MUTATIONS: tuple[tuple[str, Mut], ...] = (
    (
        "G1-INVENTORY",
        regex(r"^(\| CMP-232 LimitsChip .*?\| component \| )reviewed ", r"\1skipped  "),
    ),
    ("G2-KEYS", regex(r"^(\| Submit .*?\| )`Ctrl\+Enter`", r"\1`Ctrl+Shift+Enter`")),
    (
        "G3-R5",
        sub("valid when working orders exist; no arm condition", "refused with `arm.locked`"),
    ),
    ("G4-T2", regex(r"^(\| T2-05 .*?\| T2 +\| )2a ", r"\1tip")),
    ("G5-LIVE", regex(r"^(\| LR-15 .*?\| )never spoken ", r"\1polite       ")),
    ("G6-COLOUR", regex(r"^(\| CR-01 .*?\| )1\.5 ", r"\g<1>2.5 ")),
    ("G7-VERDICT", regex(r"^(\| 1\.4\.1 Use of colour +\| )compliant", r"\1compliance")),
    ("G8-FINDINGS", regex(r"^(\| F-19 .*?\| )E30-D04 · area/oms-execution", r"\1a worker")),
    ("G9-RULED", regex(r"^(\| A-5 .*)A31\)", r"\1A30)")),
    ("G10-CITE", sub("(`D04`:1047)", "(`D04`:1046)")),
    ("G11-HYGIENE", sub("## 19. Summary", "## 19. Summary " + codecs.decode("Nggnpx", "rot13"))),
)

# Probes: edits a weaker gate would let through; each must add one FAIL.
PROBES: tuple[tuple[str, Mut], ...] = (
    ("G2-KEYS", regex(r"^(\| KS-P03 \| )`Tab`", r"\1click, then `Tab`")),
    ("G3-R5", regex(r"^(\| AR-14 .*?\| )carve-out — never arm-gated", r"\1" + GATED)),
    ("G4-T2", regex(r"^(\| T2-03 .*?)`rbac\.account` ", r"\1`opacity.disabled` `rbac.account` ")),
    (
        "G4-T2",
        sub(
            '`rbac.account` "This account isn\'t assigned to you."',
            '`rbac.account` "This account isn\'t assigned to you, nor its 2 positions." (PROPOSED)',
        ),
    ),
    ("G5-LIVE", regex(r"^(\| LR-17 .*?\| )once per event", r"\1≤ 1 per 2 s")),
    ("G6-COLOUR", sub("gated FAIL 0 · minima", "gated FAIL 1 · minima")),
    ("G7-VERDICT", regex(r"^(\| 1\.4\.4 Resize text .*\| )F-02( +\|)$", r"\1none\2")),
    (
        "G8-FINDINGS",
        regex(r"^(\| F-16 .*\| )carve-out — never arm-gated \| n/a( +\|)$", r"\1 | \2"),
    ),
    (
        "G8-FINDINGS",
        sub(
            "(Blocking 1 · Major 4 · Minor 9 · Info 5) <!--",
            "(Blocking 1 · Major 5 · Minor 8 · Info 5) <!--",
        ),
    ),
    ("G9-RULED", regex(r"^(\| A-1 .*)2026-10-30", r"\g<1>2026-10-29")),
    ("G9-RULED", regex(r"^(\| C-b .*)row A31\)", r"\1row A32)")),
    ("G9-RULED", regex(r"^(\| F-06 .*?)2026-10-30", r"\g<1>2026-10-31")),
    ("G9-RULED", regex(r"^(\| Q-03 .*?)row A33\)", r"\1row A32)")),
    ("G9-RULED", regex(r"^(- \*\*O-L\.\*\*.*?)2026-10-30", r"\g<1>2026-10-29")),
    ("G9-RULED", sub("WCAG 2.2.1 = **RULED (orchestrator, 2026-10-30", "WCAG 2.2.1 = **RULED (x")),
    ("G9-RULED", regex(r"^(\| 2\.2\.1 Timing adjustable .*?), RULED \([^)]*\)", r"\1")),
    ("G3-R5", sub("one press, never a dialog (`D02`:66; F-11)", "opens a dialog (`D02`:66; F-11)")),
    (
        "G3-R5",
        sub("never refused on the view-as leg, where", "T2 `rbac.view_as`, where"),
    ),
    (
        "G3-R5",
        sub(
            "none on a carve-out leg: FREEZE and view-as leave it enabled",
            "FREEZE: a Manager's press is T2 \"" + FROZEN + '"',
        ),
    ),
    ("G4-T2", regex(r"^(\| T2-29 \| )SCR-158's submit and Replay", r'\1"Flatten now" and Replay')),
    ("G9-RULED", regex(r"^(\| AR-13 .*?)2026-10-30", r"\g<1>2026-10-31")),
    ("G9-RULED", regex(r"^(\| C-i .*?)row A34\)", r"\1row A33)")),
    ("G2-KEYS", regex(r"^(\| Arm / disarm \(ticket\) .*?\| )no ", r"\1yes")),
    (
        "G8-FINDINGS",
        regex(r"^(\| F-01 .*?)\(every write; the C-2\.6 carve-out excepted\)", r"\1(every write)"),
    ),
    ("G8-FINDINGS", sub('never refused on the view-as leg";', 'stay enabled under every leg";')),
    ("G8-FINDINGS", sub("no dialog (AR-11, F-11)", "no dialog (AR-12, F-11)")),
    ("G8-FINDINGS", sub("before it is pressed (AR-04)", "before it is pressed (AR-40)")),
    (
        "G8-FINDINGS",
        sub(
            "never refused; the write runs and is audited as the viewer",
            "never refused; the write runs",
        ),
    ),
    ("G9-RULED", regex(r"^(\| AR-14 .*?)2026-10-30", r"\g<1>2026-10-31")),
    ("G3-R5", sub("the arm lapsing mid-dialog included (LR-07)", "a leg removed")),
    ("G9-RULED", sub("The user range stays 10–60 s", "The user range widens to 10–200 s")),
    (
        "G3-R5",
        regex(r"^(\| AR-13 .*?)never refused for want of the arm", r"\1" + FROZEN),
    ),
    (
        "G5-LIVE",
        sub(
            "| `confirm.countdown.announce10` only ",
            "| `confirm.countdown.announce10` and `confirm.timeout.announce` ",
        ),
    ),
    ("G10-CITE", pin_sub("|The C-2.6 carve-out binds this", "|The C-2.6 carve-out binds no")),
    ("G11-HYGIENE", sub('"Preset {n}, {qty} {coin}, active"', '"Preset 3, 0.250 BTC, active"')),
)


def digests() -> dict[str, str]:
    paths = (SPEC, PINS, Path(__file__))
    return {str(p): hashlib.sha256(p.read_bytes()).hexdigest() for p in paths if p.exists()}


def self_test(ctx: Ctx, base: Result) -> list[str]:
    bad: list[str] = []
    before = digests()
    covered = {code for code, _ in MUTATIONS}
    bad += [f"self-test: gate {g} has no mutation" for g, _ in GATE_FNS if g not in covered]
    for code, fn in (*MUTATIONS, *PROBES):
        mutated = fn(ctx)
        if mutated == ctx:
            bad.append(f"self-test {code}: the mutation did not apply")
            continue
        new = sorted(set(run(mutated).fails) - set(base.fails))
        if len(new) != 1 or not new[0].startswith(f"[{code}]"):
            bad.append(f"self-test {code}: expected one new [{code}] FAIL, got {new[:3]}")
    again = run(ctx)
    if again.fails != base.fails or again.numbers != base.numbers:
        bad.append("self-test: a re-run does not reproduce the base result")
    if digests() != before:
        bad.append("self-test: a file on disk changed")
    return bad


def parse_sources(items: list[str]) -> dict[str, str]:
    out: dict[str, str] = {}
    for item in items:
        name, _, path = item.partition("=")
        if name not in RULING_PINS or not path:
            raise SystemExit(f"--source takes NAME=FILE with NAME one of {sorted(RULING_PINS)}")
        out[name] = Path(path).read_text(encoding="utf-8")
    return out


def main(argv: list[str]) -> int:
    ap = argparse.ArgumentParser(description=(__doc__ or "").splitlines()[0])
    ap.add_argument("--check", action="store_true", help="exit 1 on any FAIL")
    ap.add_argument("--json", action="store_true", help="print the numbers and findings as JSON")
    ap.add_argument("--self-test", "--selftest", action="store_true", help="the mutation self-test")
    ap.add_argument("--repin", action="store_true", help="rewrite the pins file from the cites")
    ap.add_argument("--source", action="append", default=[], help="NAME=FILE, a saved ruling")
    args = ap.parse_args(argv)
    ctx = load_ctx(parse_sources(args.source))
    if not all(ctx.base.values()):
        missing = [k for k, v in ctx.base.items() if not v]
        print(f"FAIL [G10-CITE] cannot read {missing} at {BASE} (fetch first)")
        return 1
    if args.repin:
        print(f"pins written: {repin(ctx)}")
        ctx = load_ctx(ctx.sources)
    res = run(ctx)
    st = self_test(ctx, res) if args.self_test else []
    if args.json:
        payload: dict[str, object] = {"numbers": res.numbers, "fails": res.fails}
        payload["warns"] = res.warns
        if args.self_test:
            payload["self_test"] = st
        print(json.dumps(payload, ensure_ascii=False, indent=1, sort_keys=True))
    else:
        out = [f"FAIL {line}" for line in res.fails] + [f"WARN {line}" for line in res.warns]
        out += [f"{k}: {v}" for k, v in res.numbers.items()]
        out.append(f"gates: {len(GATE_FNS)}; FAIL {len(res.fails)}, WARN {len(res.warns)}")
        if args.self_test:
            out += [f"FAIL {line}" for line in st]
            out.append(
                f"self-test: {'ok' if not st else 'FAILED'}: {len(MUTATIONS)} mutations (one per "
                f"gate) and {len(PROBES)} probes, each one new FAIL; a re-run reproduces the base "
                "result; files on disk unchanged"
            )
        print("\n".join(out))
    failed = bool(res.fails or st)
    return 1 if (failed and (args.check or args.self_test)) else 0


if __name__ == "__main__":
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")
    raise SystemExit(main(sys.argv[1:]))
