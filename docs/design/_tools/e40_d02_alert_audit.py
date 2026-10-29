#!/usr/bin/env python3
"""E40-D02 (#1013) PR-2: the gate tool of the alert surfaces' re-plan, hand-off pack and sounds.

Stdlib only, offline; it executes no application code. It reads the spec
(`docs/design/E40/E40-D02.md`), the hand-off pack (`docs/design/E40/E40-D02-handoff.md`), `14`,
D01's a11y contract (`docs/design/a11y/e40-alerts-a11y-review.md`), the template allow-list of
E40-T02 (`TEMPLATE_FIELDS` in `services/api/candleviewer/alerts/compiler.py`, parsed with `ast`,
never imported), the token JSON (resolved through `e40_d01_alert_contrast.py`'s loader and
`contrast_check.py`'s `contrast_ratio()`, both imported, never re-implemented) and the sound files
with `e40_d02_tones.py` (imported to regenerate the bytes in memory). Ruled by the orchestrator on
2026-10-29 (issuecomment-6486717743, BQ-1..BQ-9). The gates, each FAIL led by its code:

- [BOARDS] at most 10 boards and at most 3 light twins (a third); names `E40-D02 / NN slug`, the
  number equal to the board's, no `key` / `secret` / `token` / `crypt`; each board's frame in the
  frame index, whose status names that board.
- [FRAMES] the 39 frames of §12.1, each with a status ("board NN", or "specified (drawn on
  request)") and non-empty Shows and Covers cells; no board named by a frame that is not on it.
- [CHECKLIST] each of the 32 `14` sign-off checklist lines (SCR-090, SCR-091, SCR-092, SCR-014,
  SCR-015, SCR-115) quoted in §12.1's checklist map, with known frames and a tick that agrees
  with the boards ("drawn on board NN" only when board NN draws one of its frames).
- [MATRIX] the pack's C1: 12 states x 5 screens = 60 cells, each a frame present in C2 and a copy
  string this spec holds, or `N/A — reason`; equal to the data below (C1 is generated: `--write`);
  C3's frames present in C2.
- [INDEX] the pack's C2 equal to the frames and twins of §12.1 (board, size, status, walk order,
  Penpot board id): a board whose §12.1 status reads `board NN, drawn (rN): board id `<uuid>`
  (W x H)` is "drawn (rN)" in C2 with that id and size, any other board "board NN, PENDING".
- [COPY] every string of the pack's copy deck is held verbatim by the spec.
- [ALLOWLIST] §3.5's leaves and the pack's allow-list equal E40-T02's `TEMPLATE_FIELDS`; both keep
  the condition-metric clause and its "This condition" row (`_placeholder_ok`).
- [CONTRAST] §14.2's CP rows recomputed over the token JSON (dark, light, high contrast).
- [SOUNDS] the four WAVs and `manifest.json`: each at most 100 KB, at most 200 KB in all, the
  manifest's bytes and sha256 equal to the files, the files byte-equal to the generator's output.
- [CITES] every `D01:n` pin of the pack's a11y contract lands on its id's row in D01; every `14:n`
  pin of the checklist map lands on a sign-off checklist line.
- [PACK] the token map is one JSON block naming only existing tokens; the Deferred rows equal
  §17.3's DF-1..DF-19; "Open questions: none" is present.

`--json` is the only source of every number in the PR body. `--check` prints the gate summary
(0 FAIL and 0 WARN is the bar). `--self-test` (or `--selftest`) applies at least one mutation per
gate to an in-memory copy of the texts (or the sound bytes) and passes only when each adds exactly
one new FAIL carrying its gate code, the restored texts reproduce the base result, and the files
on disk are byte-identical afterwards. `--write` regenerates the pack's C1 and C2 blocks (between
their `<!-- c1:begin -->` / `<!-- c2:begin -->` markers). Exit 1 on any FAIL.

Usage: python3 -I -B docs/design/_tools/e40_d02_alert_audit.py [--check] [--json] [--self-test]
       [--write]
"""

from __future__ import annotations

import ast
import hashlib
import importlib.util
import json
import re
import sys
from collections.abc import Callable
from dataclasses import dataclass, field, replace
from pathlib import Path
from types import ModuleType

ROOT = Path(__file__).resolve().parents[3]
TOOLS = Path(__file__).resolve().parent
SPEC = ROOT / "docs/design/E40/E40-D02.md"
PACK = ROOT / "docs/design/E40/E40-D02-handoff.md"
CAT14 = ROOT / "docs/plan/14-screens-catalogue.md"
CAT15 = ROOT / "docs/plan/15-component-catalogue.md"
D01 = ROOT / "docs/design/a11y/e40-alerts-a11y-review.md"
COMPILER = ROOT / "services/api/candleviewer/alerts/compiler.py"
SOUNDS = ROOT / "docs/design/E40/sounds"
TOKENS = ROOT / "packages/ui/tokens"
THEMES = ("dark", "light", "high-contrast")
SPEC_ = "specified (drawn on request)"
NAME_DENY = re.compile(r"key|secret|token|crypt", re.IGNORECASE)
GATES = (
    "BOARDS",
    "FRAMES",
    "CHECKLIST",
    "MATRIX",
    "INDEX",
    "COPY",
    "ALLOWLIST",
    "CONTRAST",
    "SOUNDS",
    "CITES",
    "PACK",
)
SCREENS = ("SCR-090", "SCR-091", "SCR-092", "SCR-014", "SCR-115")
STATES = (
    "loading",
    "empty",
    "populated",
    "active",
    "triggered",
    "snoozed",
    "expired",
    "disabled",
    "delivery-failed",
    "vocabulary-unavailable",
    "permission-denied",
    "error",
)
CHECKLIST_SCREENS = ("SCR-090", "SCR-091", "SCR-092", "SCR-014", "SCR-015", "SCR-115")

# C1, the state matrix (T: Part C; BQ-4): (screen, state) -> (frame id, copy) or (None, reason).
# Every copy string is quoted from the spec (the [MATRIX] gate checks it there).
C1: dict[tuple[str, str], tuple[str | None, str]] = {
    ("SCR-090", "loading"): ("A4", "Loading alerts…"),
    ("SCR-090", "empty"): ("A4", "No alerts yet"),
    ("SCR-090", "populated"): ("A1", "Showing 4 of 12 alerts"),
    ("SCR-090", "active"): ("A1", "Armed"),
    ("SCR-090", "triggered"): ("A2", "Fired at 14:02:11 UTC"),
    ("SCR-090", "snoozed"): ("A3", "Snoozed until 14:32 UTC (28 min)"),
    ("SCR-090", "expired"): ("A1", "Expired"),
    ("SCR-090", "disabled"): ("A1", "Disabled"),
    ("SCR-090", "delivery-failed"): (
        "A6",
        "The desktop app couldn't show the notification. The alert fired and is recorded here.",
    ),
    ("SCR-090", "vocabulary-unavailable"): (
        "A6",
        "Alert conditions can't be described right now: the rule engine isn't available. "
        "Your alerts are unchanged.",
    ),
    ("SCR-090", "permission-denied"): (
        "A6",
        "Desktop notification blocked by the OS — enable it in Settings",
    ),
    ("SCR-090", "error"): ("A4", "Alerts couldn't load."),
    ("SCR-091", "loading"): ("A10", "Saving…"),
    ("SCR-091", "empty"): ("A8", "New alert"),
    ("SCR-091", "populated"): (
        "A9",
        "Preview with current values; the alert uses the values when it fires.",
    ),
    ("SCR-091", "active"): ("A8", "Alert BTC above 65k created"),
    ("SCR-091", "triggered"): ("A12", "Test shown on this device"),
    ("SCR-091", "snoozed"): (
        None,
        "snoozing is done from SCR-090, the toast and SCR-014, never in the editor (D-5)",
    ),
    ("SCR-091", "expired"): ("A10", "Pick a time in the future."),
    ("SCR-091", "disabled"): ("A11", "Your role can't change alerts."),
    ("SCR-091", "delivery-failed"): ("A12", "Desktop didn't respond"),
    ("SCR-091", "vocabulary-unavailable"): (
        "A11",
        "The rule engine isn't available, so conditions can't be checked or changed right now. "
        "Your alerts keep running.",
    ),
    ("SCR-091", "permission-denied"): ("A12", "Blocked by the OS — fix in Notification settings"),
    ("SCR-091", "error"): (
        "A11",
        "The alerts service is unavailable. Your changes are kept — try again.",
    ),
    ("SCR-092", "loading"): (
        None,
        "the toast renders at once from the alerts item; the drawer's loading (B4) is CMP-015 "
        "rows with aria-busy and no string",
    ),
    ("SCR-092", "empty"): ("B4", "Values at fire time aren't available yet."),
    ("SCR-092", "populated"): ("B1", "Last price 65,012.5 crossed above 65,000"),
    ("SCR-092", "active"): ("B1", "Alert: {name}, {symbol}, {metric} {value}, {time}"),
    ("SCR-092", "triggered"): ("B2", "3 alerts fired for BTCUSDT"),
    ("SCR-092", "snoozed"): ("B1", "Snoozed until 14:32 UTC (28 min)"),
    ("SCR-092", "expired"): (
        None,
        "an expired alert never fires, so no toast or drawer exists for it (§2.3)",
    ),
    ("SCR-092", "disabled"): ("B1", "Alert disabled. It won't fire until you enable it."),
    ("SCR-092", "delivery-failed"): (
        "B3",
        "The desktop notification for this firing couldn't be shown.",
    ),
    ("SCR-092", "vocabulary-unavailable"): (
        "B1",
        "Alert disarmed: CVD divergence data source unavailable",
    ),
    ("SCR-092", "permission-denied"): (
        "B3",
        "Desktop notification blocked by the OS — enable it in Settings",
    ),
    ("SCR-092", "error"): ("B4", "The details of this firing couldn't load."),
    ("SCR-014", "loading"): (
        None,
        "five CMP-015 rows with aria-busy and no string (B7)",
    ),
    ("SCR-014", "empty"): ("B7", "Nothing yet today"),
    ("SCR-014", "populated"): ("B5", "Notifications, {N} unread"),
    ("SCR-014", "active"): ("B5", "3 new — Back to top"),
    ("SCR-014", "triggered"): ("B6", "12 similar alerts"),
    ("SCR-014", "snoozed"): (
        None,
        "snoozing is a row-menu action; the alert's snoozed state reads in SCR-090 (§5.6)",
    ),
    ("SCR-014", "expired"): (
        None,
        "the centre lists deliveries, never alert definitions; an expiry writes no row",
    ),
    ("SCR-014", "disabled"): ("B16", "Your role can't change alerts."),
    ("SCR-014", "delivery-failed"): ("B5", "Desktop notification not shown: {name}"),
    ("SCR-014", "vocabulary-unavailable"): (
        "B5",
        "Alert disarmed: {metric} data source unavailable",
    ),
    ("SCR-014", "permission-denied"): (
        None,
        "the centre needs no OS permission; a blocked desktop notification is its "
        "delivery-failed row",
    ),
    ("SCR-014", "error"): ("B7", "Notifications couldn't load."),
    ("SCR-115", "loading"): (
        None,
        "the sections as CMP-015 rows with aria-busy and no string; this device's values show "
        "at once (B17)",
    ),
    ("SCR-115", "empty"): (None, "the matrix always holds its six categories (§6.2)"),
    ("SCR-115", "populated"): (
        "B9",
        "Critical events ignore mutes and quiet hours: they always notify on every channel they "
        "use.",
    ),
    ("SCR-115", "active"): ("B10", "Critical events still notify during quiet hours."),
    ("SCR-115", "triggered"): ("B10", "Test notification shown"),
    ("SCR-115", "snoozed"): ("B17", "muted since 14:02 UTC"),
    ("SCR-115", "expired"): (None, "a notification setting never expires"),
    ("SCR-115", "disabled"): ("B17", "Your role can't change settings."),
    ("SCR-115", "delivery-failed"): (
        "B10",
        "The last sound couldn't play on this device (14:02 UTC). Alerts still show as toasts.",
    ),
    ("SCR-115", "vocabulary-unavailable"): (None, "SCR-115 reads no rule vocabulary"),
    ("SCR-115", "permission-denied"): (
        "B11",
        "This test can't show a desktop notification until the OS allows it.",
    ),
    ("SCR-115", "error"): ("B17", "Notification settings couldn't load."),
}

# CP rows of §14.2: id -> (foreground, background, bar, kind); `color.` is dropped in the spec.
CP: dict[str, tuple[str, str, float, str]] = {
    "CP-1": ("status.warning.strong", "surface.canvas", 3.0, "non-text"),
    "CP-2": ("status.danger.strong", "surface.canvas", 3.0, "non-text"),
    "CP-3": ("status.danger.default", "surface.canvas", 3.0, "non-text"),
    "CP-4": ("status.info.strong", "surface.canvas", 3.0, "non-text"),
    "CP-5": ("status.info.strong", "surface.raised", 3.0, "non-text"),
    "CP-6": ("status.info.strong", "surface.overlay", 3.0, "non-text"),
    "CP-7": ("status.info.default", "surface.raised", 3.0, "non-text"),
    "CP-8": ("text.secondary", "surface.selected", 4.5, "text"),
    "CP-9": ("text.secondary", "surface.hover", 4.5, "text"),
    "CP-10": ("focus.ring", "surface.hover", 3.0, "non-text"),
    "CP-11": ("action.primary.default", "surface.canvas", 3.0, "non-text"),
    "CP-12": ("action.primary.default", "surface.overlay", 3.0, "non-text"),
    "CP-13": ("border.selected", "surface.canvas", 3.0, "non-text"),
    "CP-14": ("text.inverse", "status.info.strong", 4.5, "text"),
    "CP-15": ("text.inverse", "status.info.default", 4.5, "text"),
    "CP-16": ("text.primary", "surface.sunken", 4.5, "text"),
    "CP-17": ("status.warning.strong", "status.warning.subtle", 3.0, "non-text"),
    "CP-18": ("text.secondary", "status.info.subtle", 4.5, "text"),
    "CP-19": ("status.info.strong", "status.info.subtle", 3.0, "non-text"),
    "CP-20": ("text.secondary", "neutral.subtle", 4.5, "text"),
    "CP-21": ("status.success.strong", "surface.canvas", 3.0, "non-text"),
    "CP-22": ("data-confidence.stale.text", "data-confidence.stale.surface", 4.5, "text"),
    "CP-23": ("data-confidence.disconnected.text", "data-confidence.stale.surface", 4.5, "text"),
    "CP-24": (
        "data-confidence.disconnected.indicator",
        "data-confidence.stale.surface",
        3.0,
        "non-text",
    ),
    "CP-25": (
        "data-confidence.resyncing.indicator",
        "data-confidence.stale.surface",
        3.0,
        "non-text",
    ),
}


@dataclass(frozen=True)
class Ctx:
    """Everything the gates read, so a mutation can replace one part in memory."""

    spec: str
    pack: str
    cat14: str
    d01: str
    allow: dict[str, frozenset[str]]
    sounds: dict[str, bytes]
    regenerated: dict[str, bytes]
    ratios: dict[str, tuple[float, float, float]]
    tokens: frozenset[str] = field(default_factory=frozenset)


def load_module(name: str, path: Path) -> ModuleType:
    spec = importlib.util.spec_from_file_location(name, path)
    if spec is None or spec.loader is None:
        raise SystemExit(f"{path.name} not found beside this tool")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def template_fields(source: str) -> dict[str, frozenset[str]]:
    """`TEMPLATE_FIELDS` of E40-T02's compiler, read from its syntax tree."""
    for node in ast.walk(ast.parse(source)):
        target = getattr(node, "target", None)
        if isinstance(node, ast.AnnAssign) and isinstance(target, ast.Name):
            if target.id == "TEMPLATE_FIELDS" and isinstance(node.value, ast.Dict):
                out: dict[str, frozenset[str]] = {}
                for k, v in zip(node.value.keys, node.value.values, strict=True):
                    leaves = v.args[0] if isinstance(v, ast.Call) and v.args else None
                    if not isinstance(k, ast.Constant) or not isinstance(leaves, ast.Set):
                        raise SystemExit("TEMPLATE_FIELDS is not a dict of frozenset({...})")
                    out[str(k.value)] = frozenset(
                        str(e.value) for e in leaves.elts if isinstance(e, ast.Constant)
                    )
                return out
    raise SystemExit("TEMPLATE_FIELDS not found in compiler.py")


def compute_ratios() -> tuple[dict[str, tuple[float, float, float]], frozenset[str]]:
    d01 = load_module("e40_d01_alert_contrast", TOOLS / "e40_d01_alert_contrast.py")
    tool = d01.load_contrast_module()
    themes = {t: d01.resolve_theme(t) for t in THEMES}
    out: dict[str, tuple[float, float, float]] = {}
    for cp, (fg, bg, _, _) in CP.items():
        vals = []
        for t in THEMES:
            f, b = themes[t].get("color." + fg), themes[t].get("color." + bg)
            if not f or not b:
                vals.append(-1.0)
                continue
            vals.append(round(tool.contrast_ratio(d01.hex_rgb(f), d01.hex_rgb(b)), 2))
        out[cp] = (vals[0], vals[1], vals[2])
    names: set[str] = set()
    for path in TOKENS.glob("*.tokens.json"):
        names |= set(json.loads(path.read_text(encoding="utf-8")))
    return out, frozenset(names)


def load_ctx() -> Ctx:
    tones = load_module("e40_d02_tones", TOOLS / "e40_d02_tones.py")
    ratios, names = compute_ratios()
    sounds = {p.name: p.read_bytes() for p in sorted(SOUNDS.glob("*")) if p.is_file()}
    return Ctx(
        spec=SPEC.read_text(encoding="utf-8"),
        pack=PACK.read_text(encoding="utf-8"),
        cat14=CAT14.read_text(encoding="utf-8"),
        d01=D01.read_text(encoding="utf-8"),
        allow=template_fields(COMPILER.read_text(encoding="utf-8")),
        sounds=sounds,
        regenerated=tones.build(),
        ratios=ratios,
        tokens=names,
    )


# --- parsing helpers -----------------------------------------------------------------------------


def section(text: str, head: str, stop: str = r"\n#{2,3} ") -> str:
    i = text.find(head)
    if i < 0:
        return ""
    m = re.search(stop, text[i + len(head) :])
    return text[i : i + len(head) + m.start()] if m else text[i:]


def table(block: str) -> list[list[str]]:
    rows = []
    for line in block.split("\n"):
        if line.startswith("|") and not re.match(r"^\|\s*-{3}", line):
            rows.append([c.strip() for c in line.strip().strip("|").split("|")])
    return rows[1:]  # drop the header row


def flat(text: str) -> str:
    return re.sub(r"\s+", " ", text)


def unquote(cell: str) -> str:
    cell = cell.strip()
    return cell[1:-1] if len(cell) >= 2 and cell[0] == cell[-1] == '"' else cell


def strip_ticks(cell: str) -> str:
    return cell.replace("`", "").strip()


@dataclass(frozen=True)
class Frame:
    fid: str
    name: str
    size: str
    twin: bool
    status: str
    shows: str
    covers: str


def frames(spec: str) -> list[Frame]:
    block = section(spec, "### 12.1 Board index", r"\n### 12\.2 ")
    out = []
    for r in table(block):
        if len(r) == 7 and re.fullmatch(r"[AB]\d+", r[0]):
            out.append(Frame(r[0], strip_ticks(r[1]), r[2], r[3] == "Y", r[4], r[5], r[6]))
    return out


def boards(spec: str) -> list[tuple[str, str, str, str, str]]:
    """(number, name number, slug, frame cell, theme) per row of §12.1's board table."""
    block = section(spec, "### 12.1 Board index", r"\n### 12\.2 ")
    out = []
    for r in table(block):
        m = re.fullmatch(r"`E40-D02 / (\d\d) ([a-z0-9-]+)`", r[1]) if len(r) == 6 else None
        if m and re.fullmatch(r"\d\d", r[0]):
            out.append((r[0], m.group(1), m.group(2), r[2], r[3]))
    return out


DRAWN = re.compile(
    r"board (\d\d), drawn \((r\d+[a-z]?)\): board id `([0-9a-f-]{36})` \((\d+ \u00d7 \d+)\)"
)


def drawn_of(status: str) -> dict[str, tuple[str, str, str]]:
    """{board: (run, Penpot board id, board size)} for each board a status cell records as drawn."""
    return {m.group(1): (m.group(2), m.group(3), m.group(4)) for m in DRAWN.finditer(status)}


def c2_status(board: str, drawn: dict[str, tuple[str, str, str]]) -> tuple[str, str]:
    """(C2 status, C2 Penpot board-id cell) of a board."""
    if board not in drawn:
        return f"board {board}, PENDING", "—"
    run, bid, size = drawn[board]
    return f"drawn ({run})", f"`{bid}` ({size})"


def board_of(status: str) -> tuple[str | None, str | None]:
    """(the frame's own board, its light twin's board) named by a status cell."""
    own = re.match(r"board (\d\d)", status)
    twin = re.search(r"light twin board (\d\d)", status)
    return (own.group(1) if own else None, twin.group(1) if twin else None)


def checklist_items(cat14: str) -> list[tuple[str, int, str]]:
    lines = cat14.split("\n")
    out: list[tuple[str, int, str]] = []
    for scr in CHECKLIST_SCREENS:
        head = next(i for i, ln in enumerate(lines) if ln.startswith(f"### {scr} "))
        idx = next(
            i
            for i in range(head, len(lines))
            if lines[i].startswith("- **Design sign-off acceptance checklist:**")
        )
        body = lines[idx].split("**Design sign-off acceptance checklist:**", 1)[1]
        out += [(scr, idx + 1, x.strip()) for x in body.split("[ ]") if x.strip()]
    return out


def checklist_map(spec: str) -> list[list[str]]:
    block = section(spec, "**The checklist map", r"\n### ")
    return [r for r in table(block) if len(r) == 6 and r[0].isdigit()]


def pack_block(pack: str, name: str) -> str:
    m = re.search(rf"<!-- {name}:begin -->(.*?)<!-- {name}:end -->", pack, re.DOTALL)
    return m.group(1) if m else ""


def c1_rows(pack: str) -> list[list[str]]:
    return [r for r in table(pack_block(pack, "c1")) if len(r) == 5]


def c2_rows(pack: str) -> list[list[str]]:
    return [r for r in table(pack_block(pack, "c2")) if len(r) == 7]


# --- generation ----------------------------------------------------------------------------------


def c2_expected(spec: str) -> list[tuple[str, str, str, str, str, str, str]]:
    """(walk, frame, theme, board, size, status, board id) per frame and twin, in §12.1's order."""
    out = []
    for f in frames(spec):
        own, twin = board_of(f.status)
        drawn = drawn_of(f.status)
        label = f"{f.fid} {f.name}"
        status, bid = c2_status(own, drawn) if own else (SPEC_, "—")
        out.append(
            (str(int(own)) if own else "on request", label, "dark", own or "—", f.size, status, bid)
        )
        if f.twin:
            status, bid = c2_status(twin, drawn) if twin else (SPEC_, "—")
            out.append(
                (
                    str(int(twin)) if twin else "on request",
                    label + " (light twin)",
                    "light",
                    twin or "—",
                    f.size,
                    status,
                    bid,
                )
            )
    return out


def render_c1(spec: str) -> str:
    names = {f.fid: f.name for f in frames(spec)}
    lines = ["| Screen | State | Frame | Copy string, or N/A — reason | Ref |", "| --- " * 5 + "|"]
    for scr in SCREENS:
        for st in STATES:
            fid, copy = C1[(scr, st)]
            if fid is None:
                lines.append(f"| {scr} | {st} | — | N/A — {copy} | — |")
            else:
                lines.append(f'| {scr} | {st} | `{fid} {names.get(fid, "?")}` | "{copy}" | {fid} |')
    return "\n" + "\n".join(lines) + "\n"


def render_c2(spec: str) -> str:
    lines = [
        "| Walk | Frame | Theme | Board | Size | Status | Penpot board id |",
        "| --- " * 7 + "|",
    ]
    for walk, label, theme, board, size, status, bid in c2_expected(spec):
        lines.append(f"| {walk} | `{label}` | {theme} | {board} | {size} | {status} | {bid} |")
    return "\n" + "\n".join(lines) + "\n"


def write_blocks(pack: str, spec: str) -> str:
    for name, body in (("c1", render_c1(spec)), ("c2", render_c2(spec))):
        block = f"<!-- {name}:begin -->\n{body}\n<!-- {name}:end -->"

        def keep(_m: re.Match[str], text: str = block) -> str:
            return text

        pack = re.sub(rf"<!-- {name}:begin -->.*?<!-- {name}:end -->", keep, pack, flags=re.DOTALL)
    return pack


# --- gates ---------------------------------------------------------------------------------------


@dataclass
class Result:
    fails: list[str] = field(default_factory=list)
    warns: list[str] = field(default_factory=list)
    numbers: dict[str, object] = field(default_factory=dict)

    def fail(self, code: str, msg: str) -> None:
        self.fails.append(f"[{code}] {msg}")


def gate_boards(ctx: Ctx, r: Result) -> None:
    bs = boards(ctx.spec)
    fr = {f.fid: f for f in frames(ctx.spec)}
    light = [b for b in bs if b[4] == "light"]
    r.numbers.update(boards=len(bs), boards_dark=len(bs) - len(light), boards_light=len(light))
    if not bs or len(bs) > 10:
        r.fail("BOARDS", f"{len(bs)} boards; the set holds 1 to 10")
    if len(light) > 3 or 3 * len(light) > len(bs):
        r.fail("BOARDS", f"{len(light)} light twins in {len(bs)} boards; at most 3, a third")
    for num, name_num, slug, frame_cell, theme in bs:
        if num != name_num:
            r.fail("BOARDS", f"board {num} is named {name_num}")
        elif NAME_DENY.search(slug):
            r.fail("BOARDS", f"board {num}'s name holds a denied word: {slug}")
        else:
            fid = frame_cell.split(",")[0].strip()
            own, twin = board_of(fr[fid].status) if fid in fr else (None, None)
            want = twin if theme == "light" else own
            if fid not in fr or want != num:
                r.fail("BOARDS", f"board {num} ({fid}) is not named by its frame's status")


def gate_frames(ctx: Ctx, r: Result) -> None:
    fs = frames(ctx.spec)
    nums = {b[0] for b in boards(ctx.spec)}
    drawn = [f for f in fs if board_of(f.status)[0]]
    twins = [f for f in fs if f.twin]
    twins_drawn = [f for f in twins if board_of(f.status)[1]]
    r.numbers.update(
        frames=len(fs),
        frames_drawn=len(drawn),
        frames_specified=len(fs) - len(drawn),
        twins=len(twins),
        twins_drawn=len(twins_drawn),
        twins_specified=len(twins) - len(twins_drawn),
    )
    if len(fs) != 39:
        r.fail("FRAMES", f"{len(fs)} frames in §12.1; PR-1 named 39")
    for f in fs:
        own, twin = board_of(f.status)
        if not f.shows or not f.covers:
            r.fail("FRAMES", f"{f.fid}: an empty Shows or Covers cell")
        elif not own and not f.status.startswith(SPEC_):
            r.fail("FRAMES", f"{f.fid}: status {f.status!r} is neither a board nor {SPEC_!r}")
        elif (own and own not in nums) or (twin and twin not in nums):
            r.fail("FRAMES", f"{f.fid}: names a board that does not exist")
        elif f.twin and not twin and "light twin" not in f.status:
            r.fail("FRAMES", f"{f.fid}: a twinned frame whose status says nothing of its twin")


def gate_checklist(ctx: Ctx, r: Result) -> None:
    items = checklist_items(ctx.cat14)
    rows = checklist_map(ctx.spec)
    fr = {f.fid: f for f in frames(ctx.spec)}
    on_board = {b[0]: b[3].split(",")[0].strip() for b in boards(ctx.spec) if b[4] == "dark"}
    r.numbers.update(
        checklist_lines=len(items),
        checklist_drawn=sum(1 for x in rows if x[5].startswith("drawn on board")),
        checklist_specified=sum(1 for x in rows if x[5].startswith(SPEC_)),
    )
    if len(items) != 32:
        r.fail("CHECKLIST", f"{len(items)} checklist lines in `14`; the ticket's six hold 32")
    for scr, line, text in items:
        hit = [x for x in rows if x[1] == scr and x[3] == text]
        if len(hit) != 1:
            r.fail("CHECKLIST", f"{scr} line not mapped once: {text!r}")
            continue
        row = hit[0]
        fids = [x.strip() for x in row[4].split(",")]
        m = re.match(r"drawn on board (\d\d)", row[5])
        if row[2] != f"`14:{line}`":
            r.fail("CHECKLIST", f"{scr} {text!r}: cites {row[2]}, the line is `14:{line}`")
        elif not fids or any(fid not in fr for fid in fids):
            r.fail("CHECKLIST", f"{scr} {text!r}: an unknown frame in {row[4]!r}")
        elif m and on_board.get(m.group(1)) not in fids:
            r.fail("CHECKLIST", f"{scr} {text!r}: board {m.group(1)} draws none of {row[4]}")
        elif not m and not row[5].startswith(SPEC_):
            r.fail("CHECKLIST", f"{scr} {text!r}: the tick {row[5]!r} is neither form")


def gate_matrix(ctx: Ctx, r: Result) -> None:
    rows = c1_rows(ctx.pack)
    c2_frames = {strip_ticks(x[1]).removesuffix(" (light twin)") for x in c2_rows(ctx.pack)}
    spec = flat(ctx.spec)
    seen: dict[tuple[str, str], list[str]] = {}
    for row in rows:
        seen.setdefault((row[0], row[1]), row)
    na = sum(1 for v in C1.values() if v[0] is None)
    r.numbers.update(c1_cells=len(rows), c1_na=na, c1_framed=len(C1) - na)
    if len(rows) != 60 or len(seen) != 60:
        r.fail("MATRIX", f"C1 holds {len(rows)} rows, {len(seen)} distinct; 12 x 5 = 60")
    for scr in SCREENS:
        for st in STATES:
            got = seen.get((scr, st))
            fid, copy = C1[(scr, st)]
            if got is None:
                r.fail("MATRIX", f"C1 {scr} · {st}: no row")
            elif not got[3] or got[3] in ('""', "N/A —", "N/A"):
                r.fail("MATRIX", f"C1 {scr} · {st}: an empty cell")
            elif fid is None and got[3] != f"N/A — {copy}":
                r.fail("MATRIX", f"C1 {scr} · {st}: differs from the generated N/A reason")
            elif fid is not None and strip_ticks(got[2]) not in c2_frames:
                r.fail("MATRIX", f"C1 {scr} · {st}: frame {got[2]} is not in C2")
            elif fid is not None and (unquote(got[3]) != copy or not got[2].startswith(f"`{fid} ")):
                r.fail("MATRIX", f"C1 {scr} · {st}: differs from the generated cell")
            elif fid is not None and copy not in spec:
                r.fail("MATRIX", f"C1 {scr} · {st}: the spec does not hold {copy!r}")
    c3 = [x for x in table(section(ctx.pack, "## C3")) if len(x) == 6]
    r.numbers["c3_rows"] = len(c3)
    for x in c3:
        for fid in re.findall(r"\b([AB]\d{1,2})\b", x[4]):
            if fid not in {f.fid for f in frames(ctx.spec)}:
                r.fail("MATRIX", f"C3 row {x[0]}: frame {fid} is not in C2")


def gate_index(ctx: Ctx, r: Result) -> None:
    want = c2_expected(ctx.spec)
    got = [(x[0], strip_ticks(x[1]), x[2], x[3], x[4], x[5], x[6]) for x in c2_rows(ctx.pack)]
    r.numbers.update(c2_rows=len(got))
    if len(got) != len(want):
        r.fail("INDEX", f"C2 holds {len(got)} rows; §12.1 gives {len(want)}")
        return
    for g, w in zip(got, want, strict=True):
        if g != w:
            r.fail("INDEX", f"C2 row {w[1]!r} differs: {g} != {w}")


def gate_copy(ctx: Ctx, r: Result) -> None:
    block = section(ctx.pack, "## Copy deck", r"\n## ")
    rows = [x for x in table(block) if len(x) == 3]
    spec = flat(ctx.spec)
    r.numbers["copy_deck_strings"] = len(rows)
    if not rows:
        r.fail("COPY", "the pack has no copy deck rows")
    for x in rows:
        s = unquote(x[1])
        if not s or s not in spec:
            r.fail("COPY", f"copy deck {x[0]!r}: the spec does not hold {s!r}")


def leaves_in(block: str) -> dict[str, frozenset[str]]:
    out: dict[str, frozenset[str]] = {}
    keys = {"Market": "market", "Footprint": "footprint", "Position": "position", "Alert": "alert"}
    for x in table(block):
        name = x[0].split(" (")[0].strip("`")
        if name in keys and len(x) >= 2:
            cell = re.sub(r"\(\d+\)\s*$", "", x[1].replace("`", "")).strip()
            out[keys[name]] = frozenset(s.strip() for s in cell.split(",") if s.strip())
    return out


# _placeholder_ok also admits the condition's own metrics under market / footprint (§3.5).
METRIC_CLAUSE = (
    "plus the metrics the condition references, inserted as "
    "`market.<metric>` or `footprint.<metric>`",
    "| This condition | each metric the condition uses, under its namespace |",
)


def gate_allowlist(ctx: Ctx, r: Result) -> None:
    r.numbers["allow_list_leaves"] = sum(len(v) for v in ctx.allow.values())
    for where, text in (("spec §3.5", ctx.spec), ("pack", ctx.pack)):
        head = "### 3.5 Message template" if where == "spec §3.5" else "## Template allow-list"
        got = leaves_in(section(text, head, r"\n#{2,3} "))
        if got != ctx.allow:
            diff = {
                k: sorted(ctx.allow.get(k, frozenset()) ^ got.get(k, frozenset()))
                for k in set(ctx.allow) | set(got)
            }
            r.fail("ALLOWLIST", f"{where} differs from E40-T02's TEMPLATE_FIELDS: {diff}")
        block = flat(section(text, head, r"\n#{2,3} "))
        for pin in METRIC_CLAUSE:
            if pin not in block:
                r.fail("ALLOWLIST", f"{where} drops the condition-metric clause {pin!r}")


def gate_contrast(ctx: Ctx, r: Result) -> None:
    block = section(ctx.spec, "### 14.2 Contrast", r"\n### ")
    rows = {x[0]: x for x in table(block) if x and x[0] in CP}
    r.numbers["cp_rows"] = len(rows)
    if len(rows) != len(CP):
        r.fail("CONTRAST", f"§14.2 holds {len(rows)} CP rows; the tool knows {len(CP)}")
    for cp, x in rows.items():
        fg, bg, bar, kind = CP[cp]
        if x[2] != f"`{fg}` on `{bg}`":
            r.fail("CONTRAST", f"{cp}: the pair reads {x[2]!r}, not `{fg}` on `{bg}`")
            continue
        for i, theme in enumerate(THEMES):
            cell = x[3 + i].replace("*", "")
            num = cell.split()[0] if cell else ""
            val = ctx.ratios[cp][i]
            need = 7.0 if theme == "high-contrast" and kind == "text" else bar
            if num != f"{val:.2f}" or (("FAIL" in cell) != (val < need)):
                r.fail("CONTRAST", f"{cp} {theme}: the spec reads {cell!r}, computed {val:.2f}")
                break


def gate_sounds(ctx: Ctx, r: Result) -> None:
    wavs = {n: b for n, b in ctx.sounds.items() if n.endswith(".wav")}
    total = sum(len(b) for b in wavs.values())
    r.numbers.update(sound_files=len(wavs), sound_bytes=total)
    try:
        manifest = json.loads(ctx.sounds.get("manifest.json", b"{}"))
    except ValueError:
        manifest = {}
    files = manifest.get("files", {}) if isinstance(manifest, dict) else {}
    if len(wavs) != 4 or total > 200 * 1024:
        r.fail("SOUNDS", f"{len(wavs)} tones, {total} bytes; four, at most 204,800 bytes")
    made = sum(len(b) for n, b in ctx.regenerated.items() if n.endswith(".wav"))
    if f"{made:,} bytes in all" not in ctx.spec:
        r.fail("SOUNDS", f"§9.1 does not state the {made:,} bytes the generator writes")
    for name, data in sorted(wavs.items()):
        entry = files.get(name, {})
        if len(data) > 100 * 1024:
            r.fail("SOUNDS", f"{name}: {len(data)} bytes, over 102,400")
        elif (
            entry.get("bytes") != len(data)
            or entry.get("sha256") != hashlib.sha256(data).hexdigest()
        ):
            r.fail("SOUNDS", f"{name}: the manifest's bytes or sha256 differ from the file")
        elif ctx.regenerated.get(name) != data:
            r.fail("SOUNDS", f"{name}: differs from e40_d02_tones.py's output")
    if ctx.regenerated.get("manifest.json") != ctx.sounds.get("manifest.json"):
        r.fail("SOUNDS", "manifest.json differs from e40_d02_tones.py's output")


def gate_cites(ctx: Ctx, r: Result) -> None:
    d01 = ctx.d01.split("\n")
    block = section(ctx.pack, "## A11y contract", r"\n## ")
    rows = [x for x in table(block) if len(x) == 4]
    r.numbers["a11y_ids"] = len(rows)
    for x in rows:
        m = re.fullmatch(r"`D01:(\d+)`", x[2])
        n = int(m.group(1)) if m else 0
        line = d01[n - 1] if 0 < n <= len(d01) else ""
        ok = line.startswith(f"| {x[0]} ") or (x[0] == "LR-0" and "(LR-0)" in line)
        if not ok:
            r.fail("CITES", f"{x[0]}: `D01:{n}` does not hold its row")
    lines14 = ctx.cat14.split("\n")
    pins = {x[2] for x in checklist_map(ctx.spec)}
    r.numbers["cite_pins"] = len(rows) + len(pins)
    for pin in sorted(pins):
        m = re.fullmatch(r"`14:(\d+)`", pin)
        n = int(m.group(1)) if m else 0
        if not (0 < n <= len(lines14)) or "sign-off acceptance checklist" not in lines14[n - 1]:
            r.fail("CITES", f"{pin} is not a sign-off checklist line")


def gate_pack(ctx: Ctx, r: Result) -> None:
    blocks = re.findall(r"```json\n(.*?)```", ctx.pack, re.DOTALL)
    names: list[str] = []
    if len(blocks) != 1:
        r.fail("PACK", f"{len(blocks)} JSON blocks; the token map is one")
    else:
        try:
            data = json.loads(blocks[0])
            for group in data["surfaces"].values():
                names += list(group)
        except (ValueError, KeyError, AttributeError):
            r.fail("PACK", "the token map's JSON does not parse as {surfaces: {..: [..]}}")
    unknown = sorted({n for n in names if n not in ctx.tokens})
    r.numbers["token_map_names"] = len(set(names))
    if unknown:
        r.fail("PACK", f"the token map names {len(unknown)} non-tokens: {unknown[:4]}")
    spec_df = {x[0]: x[1] for x in table(section(ctx.spec, "### 17.3 Deferred")) if x}
    pack_df = {x[0]: x[1] for x in table(section(ctx.pack, "## Deferred", r"\n## ")) if x}
    r.numbers["deferred_rows"] = len(pack_df)
    if spec_df != pack_df or len(pack_df) != 19:
        r.fail("PACK", "the Deferred rows differ from §17.3's DF-1..DF-19")
    for cmp in ("CMP-163", "CMP-164", "CMP-165"):
        entry = section(CAT15.read_text(encoding="utf-8"), f"### {cmp} ", r"\n### ")
        m = re.search(r"^- \*\*Storybook\*\*: (.*)$", entry, re.M)
        r.numbers[f"stories_{cmp}"] = len(m.group(1).split(", ")) if m else 0
    if "Open questions: none" not in ctx.pack:
        r.fail("PACK", 'the pack does not say "Open questions: none"')


GATE_FNS: tuple[Callable[[Ctx, Result], None], ...] = (
    gate_boards,
    gate_frames,
    gate_checklist,
    gate_matrix,
    gate_index,
    gate_copy,
    gate_allowlist,
    gate_contrast,
    gate_sounds,
    gate_cites,
    gate_pack,
)


def run(ctx: Ctx) -> Result:
    r = Result()
    for fn in GATE_FNS:
        fn(ctx, r)
    return r


# --- self-test -----------------------------------------------------------------------------------


def with_text(ctx: Ctx, field_name: str, text: str) -> Ctx:
    return replace(ctx, spec=text) if field_name == "spec" else replace(ctx, pack=text)


def sub(field_name: str, old: str, new: str) -> Callable[[Ctx], Ctx]:
    def apply(ctx: Ctx) -> Ctx:
        text: str = getattr(ctx, field_name)
        return with_text(ctx, field_name, text.replace(old, new, 1)) if old in text else ctx

    return apply


def regex(field_name: str, pattern: str, repl: str) -> Callable[[Ctx], Ctx]:
    def apply(ctx: Ctx) -> Ctx:
        text: str = getattr(ctx, field_name)
        return with_text(ctx, field_name, re.sub(pattern, repl, text, count=1, flags=re.M))

    return apply


def grow_tone(ctx: Ctx) -> Ctx:
    sounds = dict(ctx.sounds)
    sounds["critical-tone.wav"] = sounds.get("critical-tone.wav", b"") + bytes(120 * 1024)
    return replace(ctx, sounds=sounds)


MUTATIONS: tuple[tuple[str, Callable[[Ctx], Ctx]], ...] = (
    ("BOARDS", sub("spec", "`E40-D02 / 05 centre-populated`", "`E40-D02 / 05 centre-token`")),
    ("FRAMES", regex("spec", r"^(\| B22 +\|.*\|)\s*DoD-B1\s*\|$", r"\1  |")),
    ("CHECKLIST", regex("spec", r"^(\| 30 +\| SCR-115 \| `14:2375` \| )per-sound", r"\1per sound")),
    ("MATRIX", regex("pack", r'^(\| SCR-014 +\| empty +\| [^|]+\| )"Nothing yet today"', r"\1")),
    (
        "INDEX",
        regex(
            "pack",
            r"^(\| 4 +\| `B15 [^|]+\| dark +\| 04 +\| )1600 \u00d7 1000",
            "\\g<1>1600 \u00d7 900",
        ),
    ),
    (
        "INDEX",
        regex(
            "pack",
            r"^(\| \d+ +\|[^|]+\|[^|]+\|[^|]+\|[^|]+\| drawn \()r\d+[a-z]?\)",
            r"\g<1>r0)",
        ),
    ),
    (
        "COPY",
        sub("pack", '"Sound requires the desktop shell."', '"Sound needs the desktop shell."'),
    ),
    ("ALLOWLIST", sub("spec", "index, index_price, funding_rate", "index, funding_rate")),
    ("ALLOWLIST", sub("pack", "or `footprint.<metric>`", "or `footprint.metric`")),
    ("CONTRAST", regex("spec", r"^(\| CP-7 +\|[^|]+\|[^|]+\| )6\.20", r"\g<1>6.21")),
    ("SOUNDS", grow_tone),
    ("CITES", sub("pack", "| LR-1 ", "| LR-2 ")),
    ("PACK", sub("pack", "Open questions: none", "Open questions: one")),
)


def digests() -> dict[str, str]:
    paths = [SPEC, PACK, CAT14, CAT15, D01, COMPILER, *sorted(SOUNDS.glob("*"))]
    return {str(p): hashlib.sha256(p.read_bytes()).hexdigest() for p in paths if p.is_file()}


def self_test(ctx: Ctx, base: Result) -> list[str]:
    bad: list[str] = []
    before = digests()
    covered = {code for code, _ in MUTATIONS}
    bad += [f"self-test: gate {g} has no mutation" for g in GATES if g not in covered]
    for code, fn in MUTATIONS:
        mutated = fn(ctx)
        if mutated == ctx:
            bad.append(f"self-test {code}: the mutation did not apply")
            continue
        new = sorted(set(run(mutated).fails) - set(base.fails))
        if len(new) != 1 or not new[0].startswith(f"[{code}]"):
            bad.append(f"self-test {code}: expected one new [{code}] FAIL, got {new[:3]}")
    again = run(ctx)
    if sorted(again.fails) != sorted(base.fails) or again.numbers != base.numbers:
        bad.append("self-test: the restored texts do not reproduce the base result")
    if digests() != before:
        bad.append("self-test: a file on disk changed")
    return bad


def main(argv: list[str]) -> int:
    if "--write" in argv:
        spec = SPEC.read_text(encoding="utf-8")
        PACK.write_text(write_blocks(PACK.read_text(encoding="utf-8"), spec), encoding="utf-8")
        print(f"wrote C1 and C2 into {PACK.relative_to(ROOT)}")
    ctx = load_ctx()
    res = run(ctx)
    st: list[str] = []
    if "--self-test" in argv or "--selftest" in argv:
        st = self_test(ctx, res)
        res.numbers["mutations"] = len(MUTATIONS)
    if "--json" in argv:
        payload = {
            "numbers": res.numbers,
            "contrast": {cp: dict(zip(THEMES, v, strict=True)) for cp, v in ctx.ratios.items()},
            "fails": res.fails,
            "warns": res.warns,
            "self_test": st,
        }
        print(json.dumps(payload, ensure_ascii=False, indent=1))
    else:
        for line in res.fails:
            print(f"FAIL {line}")
        for line in res.warns:
            print(f"WARN {line}")
        tally = f"FAIL {len(res.fails)}, WARN {len(res.warns)}"
        print(f"gates: {len(GATES)} ({', '.join(GATES)}); {tally}")
        if "--self-test" in argv or "--selftest" in argv:
            for line in st:
                print(f"FAIL {line}")
            print(
                f"self-test: {'ok' if not st else 'FAILED'} — {len(MUTATIONS)} mutations, at "
                "least one per gate, each one new FAIL; restored result identical; files on disk "
                "unchanged"
            )
    return 1 if res.fails or st else 0


if __name__ == "__main__":
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")
    sys.exit(main(sys.argv[1:]))
