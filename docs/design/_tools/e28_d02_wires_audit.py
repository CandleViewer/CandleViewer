#!/usr/bin/env python3
"""E28-D02 (#821) PR 1: the gate tool of the profile and trade-group wireframe spec.

Stdlib only, offline (`python3 -I -B`); it reads the spec (`docs/design/E28/E28-D02.md`), `14`,
`21`, `22`, `23`, `24`, ADR-0040, the audit registry and the RBAC matrix as text and runs no
repository code. Ruled by the orchestrator on 2026-10-29 (#821 comment 6502192723, BQ-21). The
gates, each FAIL led by its code:

- [BOARDS] at most 10 boards and at most 3 twins; names `E28-D02 / NN slug` with NN the row's
  number, exports `docs/design/E28/img/E28-D02-NN-slug.png`, every board PENDING.
- [SLUGS] no board name or slug holds a vault word (key / secret / token / crypt).
- [FRAMES] section 0 and section 7 agree in both directions: every register frame once, its
  status "board NN" (and on board NN) or "specified (drawn on request)"; every frame name in the
  spec is on the register; Shows and Covers are filled.
- [CATALOGUE] every T: and `14` state phrase of the six screens is quoted by a register row of
  its screen, each `14` phrase occurs in its entry, no row quotes a phrase of another screen, and
  the states handed to E34 are named in section 16.
- [SOURCES] each row names a `22` operation (or a `23` topic) or "not yet served: G-n", a `24`
  section 15.2 permission (or `self`) with a role, and an event a source names (or "no event").
- [SERVED] a row naming a route the RBAC matrix marks `not_mounted` carries the "not yet served"
  stamp, and every stamp names a gap id.
- [CHECKLIST] each of the 37 sign-off checklist items of the six `14` entries is quoted verbatim
  in section 12 with a disposition (a frame, E34-D02 / E34-D03, or N/A with a reason).
- [COPY] every validation rule the six entries name and every rule the frames reach has a
  section 10 string.
- [RULED] the strings the ruling fixes occur verbatim.
- [SAFETY] no control word beside a stop-loss line in a register Shows cell, a copy string or a
  mock line; the Safety frame shows CD-6; `native_stop_mandatory` is "not reachable from this UI".
- [SCAN] no UUID, credential-shaped run, key-id shape, address or 7+ digit number (only the
  cited comment ids), and account names only from the fixture set.
- [CITES] the pinned cites occur and hold at the base; every `14:n` / `22:n` cite is in range;
  every section 12 pin is its screen's sign-off checklist line; each of the six `14` entries
  carries exactly one E28-D02 pointer line. Line cites read `14` at the base: this PR's six
  pointer lines are dropped before a line is resolved.

`--json` prints the counts the PR body quotes; `--check` exits 1 on any FAIL; `--self-test`
applies one mutation per gate to an in-memory copy and passes only when each adds exactly one new
FAIL with its code, the base result is reproduced, and the files on disk are byte-identical.

Usage: python3 -I -B docs/design/_tools/e28_d02_wires_audit.py [--check] [--json] [--self-test]
"""

from __future__ import annotations

import hashlib
import json
import re
import sys
from collections.abc import Callable
from dataclasses import dataclass, field, replace
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
PLAN = ROOT / "docs" / "plan"
SPEC = ROOT / "docs" / "design" / "E28" / "E28-D02.md"
CAT14 = PLAN / "14-screens-catalogue.md"
DB21 = PLAN / "21-database-schema.md"
API22 = PLAN / "22-api-openapi.yaml"
WS23 = PLAN / "23-ws-protocol.md"
SCH24 = PLAN / "24-internal-schemas.md"
ADR40 = PLAN / "27-adrs" / "ADR-0040-per-trade-overrides-and-profile-propagation.md"
ACT = ROOT / "services" / "api" / "candleviewer" / "audit" / "actions.py"
MX = ROOT / "services" / "api" / "tests" / "contract" / "rbac" / "matrix.yaml"

GATES = (
    "BOARDS",
    "SLUGS",
    "FRAMES",
    "CATALOGUE",
    "SOURCES",
    "SERVED",
    "CHECKLIST",
    "COPY",
    "RULED",
    "SAFETY",
    "SCAN",
    "CITES",
)
MAX_BOARDS = 10
MAX_TWINS = 3
SPEC_ = "specified (drawn on request)"
NAME_DENY = re.compile(r"key|secret|token|crypt", re.IGNORECASE)
FRAME_RE = re.compile(r"`((?:SCR-(?:130|131|132|133|062|061)|CMP-087|Pattern) / [^`]+)`")
POINTER = re.compile(r"^- \*\*(Wireframes|UX research|Hi-fi|Motion|Design) \(")
OWN_POINTER = "- **Wireframes (E28-D02):** [E28-D02.md](../design/E28/E28-D02.md) "
SCREENS = ("SCR-130", "SCR-131", "SCR-132", "SCR-133", "SCR-062", "SCR-061")
GENERIC = ("loading", "empty", "populated", "validating", "error", "forbidden")
TOPICS = ("wallet", "trade_groups")
FIXTURE_ACCOUNTS = {"sub_001", "sub_002", "sub_003", "sub_004"}
# The comment ids the spec cites (#821's ruling and question list, #2701's ledgers and directive).
COMMENT_IDS = {"6502192723", "6502127235", "6493096777", "6502202762", "6490317249"}

# The state phrases per screen: T: = #821 section Scope (generic and screen-specific states);
# 14 = the screen's catalogue entry, checked to occur there.
SPECIFIC: dict[str, tuple[tuple[str, str], ...]] = {
    "SCR-130": (
        ("unbound-account", "T"),
        ("allows-all-symbols", "T"),
        ("allows all symbols", "14"),
    ),
    "SCR-131": (("validation-blocked", "T"), ("step-up", "T")),
    "SCR-132": (("live-account acknowledgement", "T"),),
    "SCR-133": (("locked cell with an open position", "T"), ("unsaved-changes summary", "T")),
    "SCR-062": (("state unknown for sub_002", "14"), ("N-of-M readiness", "T")),
    "SCR-061": (
        ("previewing", "14"),
        ("ready", "14"),
        ("warn", "T"),
        ("excluded", "T"),
        ("blocked", "T"),
        ("stale-preview", "T"),
        ("blocked (group contains an account in lockout)", "14"),
    ),
}
# SCR-061 states that are E34-D02's (BQ-1): each must occur in its entry and in section 16.
HANDED_OFF = ("partial-send in progress", "partial failure", "rate-limit backoff")

# The rules section 10 must answer (AC3; BQ-19): the six entries' validation rules (as phrases)
# and every `22` rule, code and warning the frames reach.
RULE_KEYS = (
    "leverage ≤ the exchange maximum",
    "daily loss between −0.1 % and −50 %",
    "max position ≥ min lot",
    "sizing rule must produce ≥ min lot",
    "a group needs ≥1 account",
    "a group's accounts must share a symbol",
    "group names unique",
    "every row resolves a qty ≥ min lot",
    "excluded rows state the reason",
    "applying shows which accounts would breach exchange limits",
    "`required`",
    "`not_allowed`",
    "`range`",
    "`precision`",
    "`ladder_sum`",
    "`above_leverage_cap`",
    "`ap_trading_caps`",
    "`default_has_own_operation`",
    "`stop_defines_r`",
    "`native_stop_mandatory`",
    "`max_leverage`",
    "`min_order_qty`",
    "`qty_step`",
    "`min_notional`",
    "`symbol_not_listed`",
    "`instrument_cache_unavailable`",
    "`audit_unavailable`",
    "`version_conflict`",
    "`conflict` (a name)",
    "`conflict` (delete blocked)",
    "`step_up_required`",
    "`all_symbols`",
    "`no_symbols`",
    "`sizing_below_min_order`",
    "`stop_beyond_liquidation`",
    "`no_common_symbol`",
    "`environment_mismatch`",
    "`duplicate_account`",
    "`write_once`",
    "`account_scope_denied`",
    "`risk_limit_breached`",
    "`stop_fallback`",
    "`cap_breached`",
    "`symbol_not_allowed`",
    "`insufficient_margin`",
    "`rate_budget_exhausted`",
    "`account_locked`",
    "`key_invalid`",
    "`leverage_unavailable`",
    "`kill_switch_engaged`",
    "`profile_disabled`",
    "`symbol_denied`",
    "`below_min_notional`",
    "`skipped`",
    "`no_reference_price`",
    "`invalid_stop_distance`",
    "`figure_unknown`",
    "`account_disabled`",
    "`member_disabled`",
    "`account_unhealthy`",
    "`trading_disabled`",
    "`risk_state_unavailable`",
    "`intent_mismatch`",
    "`native_stop_required`",
    "`rate_limited`",
    "`not_found` (an override's profile)",
)

# The strings the ruling of record fixes (BQ-6, BQ-9, BQ-10, BQ-17, BQ-18, BQ-5), verbatim.
RULED_STRINGS = (
    (
        "BTCUSDT has an open position on sub_001 — new entries on it will be blocked; closing "
        "orders and stop changes stay allowed"
    ),
    "leverage {n}x · risk {p} % per trade · daily loss {d} %",
    (
        "values set at E28-S02's implementation (orchestrator ruling then), within these "
        "constraints: `aggressive` is demo-only and never applicable to a LIVE account; "
        "conservative ≤ standard ≤ aggressive in every cap; every template inside the profile "
        "schema's bounds and judged by the server like any save (F-12)"
    ),
    "not yet served (G-7: no template storage)",
    "Capped by profile: 5x",
    (
        "Daily loss cap: reaching it in realised loss locks the account until 00:00 UTC. New "
        "trades also count your open risk against it."
    ),
    "Every order carries a stop-loss at the exchange. This cannot be turned off.",
    "not reachable from this UI",
    'an unknown figure reads "unknown", never zero',
)
CD6 = RULED_STRINGS[6]
SAFETY_FRAME = "SCR-131 / Safety: the native stop-loss as a fixed statement"
STOP_RE = re.compile(r"stop-loss|native stop|native-stop|turned off|\bSL\b", re.IGNORECASE)
CONTROL_RE = re.compile(
    r"check ?box|toggle|switch|radio|opt[- ]out|\[x\]|\[ \]|\bturn (?:it )?off\b|\bdisable\b"
    r"|\[[^\]\n]*\bv\]|\(o\)|\( \)|\[on\b|\[off\b",
    re.IGNORECASE,
)

# Load-bearing cites: each must occur in the spec and its lines must hold the text at the base.
PINS: dict[str, str] = {
    "`22:3499-3501`": "a position sized",
    "`22:3502-3504`": "native_stop_mandatory",
    "`22:3616-3618`": "Every account has one from",
    "`22:6645`": "listed only when every member",
    "`22:6693`": "These accounts have no symbol in common",
    "`22:16516`": "The default binding has its own operation.",
    "`22:16557`": "SOLUSDT allows at most 20x",
    "`22:16570`": "cannot be turned off",
    "`22:19899`": "Never null",
    "`22:23140`": "stop_fallback",
    "`21:1478`": "require_native_sl",
    "`24:3616`": "daily_loss_lockout",
    "`14:1433`": "excluded: symbol not allowed by profile",
    "`14:1444`": "below the 0.001 minimum",
    "`14:2637`": "allows all symbols - consider restricting",
    "`14:2699`": "single server call",
    "`14:2700`": "denying a symbol with an open position is refused",
    "`ADR40:441-445`": "capped by profile: 5x",
    "`MX:1500-1513`": "not_mounted",
    "`MX:1528-1533`": "not_mounted",
}


@dataclass(frozen=True)
class Ctx:
    spec: str
    cat14: str
    db21: str
    api22: str
    ws23: str
    sch24: str
    adr40: str
    act: str
    mx: str


@dataclass
class Result:
    fails: list[str] = field(default_factory=list)
    warns: list[str] = field(default_factory=list)
    numbers: dict[str, int] = field(default_factory=dict)

    def fail(self, gate: str, msg: str) -> None:
        self.fails.append(f"[{gate}] {msg}")


def read(path: Path) -> str:
    return path.read_text(encoding="utf-8")


def load_ctx() -> Ctx:
    return Ctx(
        spec=read(SPEC),
        cat14=read(CAT14),
        db21=read(DB21),
        api22=read(API22),
        ws23=read(WS23),
        sch24=read(SCH24),
        adr40=read(ADR40),
        act=read(ACT),
        mx=read(MX),
    )


# --- parsing helpers -----------------------------------------------------------------------------


def flat(text: str) -> str:
    return " ".join(text.split())


def norm(text: str) -> str:
    return flat(text.replace("**", "")).lower()


def section(spec: str, num: int) -> str:
    m = re.search(rf"^## {num}\. .*?(?=^## |\Z)", spec, re.MULTILINE | re.DOTALL)
    return m.group(0) if m else ""


def rows(block: str, width: int) -> list[list[str]]:
    """The numbered rows of every table in `block` with exactly `width` cells."""
    out: list[list[str]] = []
    for line in block.splitlines():
        if line.startswith("| ") and not line.startswith("| -"):
            cells = [c.strip() for c in line.strip().strip("|").split("|")]
            if len(cells) == width and re.fullmatch(r"\d+", cells[0]):
                out.append(cells)
    return out


def ticked(cell: str) -> list[str]:
    return re.findall(r"`([^`]+)`", cell)


def entry(cat14: str, scr: str) -> str:
    """The screen's `14` entry without its design pointer lines (they quote states too)."""
    m = re.search(rf"^### {scr} — .*?(?=^### |^## |\Z)", cat14, re.MULTILINE | re.DOTALL)
    if not m:
        return ""
    return "\n".join(ln for ln in m.group(0).splitlines() if not POINTER.match(ln))


def base14(cat14: str) -> str:
    """`14` as the spec's line cites read it: at the base, before this PR's six pointer lines."""
    return "\n".join(ln for ln in cat14.split("\n") if not ln.startswith(OWN_POINTER))


def entry_raw(cat14: str, scr: str) -> list[str]:
    m = re.search(rf"^### {scr} — .*?(?=^### |^## |\Z)", cat14, re.MULTILINE | re.DOTALL)
    return m.group(0).splitlines() if m else []


def checklist(cat14: str, scr: str) -> tuple[int, list[str]]:
    """The line number and the items of the screen's sign-off checklist."""
    m = re.search(rf"^### {scr} — ", cat14, re.MULTILINE)
    if not m:
        return 0, []
    start = cat14.count("\n", 0, m.start())
    lines = cat14.split("\n")
    for i in range(start + 1, len(lines)):
        if lines[i].startswith("### "):
            break
        if "Design sign-off acceptance checklist:**" in lines[i]:
            body = lines[i].split("checklist:**", 1)[1]
            return i + 1, [x.strip() for x in body.split("[ ]") if x.strip()]
    return 0, []


def operations(api22: str) -> dict[str, tuple[str, str]]:
    """operationId -> (METHOD, path) from `22`."""
    ops: dict[str, tuple[str, str]] = {}
    path = method = ""
    for line in api22.splitlines():
        pm = re.match(r"^  (/\S*):\s*$", line)
        if pm:
            path = pm.group(1)
            continue
        mm = re.match(r"^    (get|put|post|delete|patch):\s*$", line)
        if mm:
            method = mm.group(1).upper()
            continue
        om = re.match(r"^\s+operationId:\s*(\w+)\s*$", line)
        if om and path:
            ops[om.group(1)] = (method, path)
    return ops


def mx_states(mx: str) -> dict[str, str]:
    """'METHOD /path' -> state, from the matrix's first (full) block of each route."""
    states: dict[str, str] = {}
    current = ""
    for line in mx.splitlines():
        rm = re.match(r"^  ((?:GET|PUT|POST|DELETE|PATCH) /\S*):\s*$", line)
        if rm:
            current = rm.group(1)
            continue
        if re.match(r"^  \S", line):
            current = ""
            continue
        sm = re.match(r"^    state:\s*(\w+)", line)
        if sm and current and current not in states:
            states[current] = sm.group(1)
    return states


def permissions(sch24: str) -> set[str]:
    m = re.search(r"class Permission\(StrEnum\):(.*?)\n\n", sch24, re.DOTALL)
    return set(re.findall(r'= "([a-z_]+:[a-z_]+)"', m.group(1))) if m else set()


def registered(act: str) -> set[str]:
    """The audit codes `ACT` registers (every quoted dotted name in it)."""
    return set(re.findall(r'"([a-z_]+\.[a-z_.]+)"', act))


def mx_permissions(mx: str) -> dict[str, set[str]]:
    """'METHOD /path' -> the permissions the matrix's first block of each route requires."""
    perms: dict[str, set[str]] = {}
    current = ""
    for line in mx.splitlines():
        rm = re.match(r"^  ((?:GET|PUT|POST|DELETE|PATCH) /\S*):\s*$", line)
        if rm:
            current = rm.group(1)
            continue
        if re.match(r"^  \S", line):
            current = ""
            continue
        pm = re.match(r"^    permissions:\s*\[(.*)\]", line)
        if pm and current and current not in perms:
            perms[current] = set(re.findall(r"'([a-z_]+:[a-z_]+)'", pm.group(1)))
    return perms


def enum_values(api22: str, schema: str, member: str) -> list[str]:
    """The enum of `member` inside the `22` component `schema` (the first one after it)."""
    m = re.search(rf"^    {schema}:\n", api22, re.MULTILINE)
    if not m:
        return []
    rest = api22[m.end() :]
    stop = re.search(r"^    \S", rest, re.MULTILINE)
    body = rest[: stop.start()] if stop else rest
    mm = re.search(rf"\b{member}:.*?enum:\s*\[(.*?)\]", body, re.DOTALL)
    return [v for v in re.findall(r"[a-z_]+", mm.group(1)) if v != "null"] if mm else []


def known_events(texts: list[str]) -> set[str]:
    """Every dotted name the sources use, `a.b|c` alternations expanded to `a.b` and `a.c`."""
    names: set[str] = set()
    for text in texts:
        for tok in re.findall(r"[a-z_]+\.[a-z_.]+(?:\|[a-z_]+)*", text):
            head, *alts = tok.split("|")
            names.add(head.rstrip("."))
            names.update(f"{head.rsplit('.', 1)[0]}.{alt}" for alt in alts)
    return names


def register(spec: str) -> list[list[str]]:
    return rows(section(spec, 7), 8)


def frame_of(row: list[str]) -> str:
    names = ticked(row[1])
    return names[0] if len(names) == 1 else ""


def screen_of(frame: str) -> str:
    return frame.split(" / ", 1)[0]


# --- gates ---------------------------------------------------------------------------------------


def board_rows(spec: str) -> list[list[str]]:
    return rows(section(spec, 0), 6)


def gate_boards(ctx: Ctx, r: Result) -> None:
    boards = board_rows(ctx.spec)
    twins = 0
    for b in boards:
        num = b[0]
        issues = []
        m = re.fullmatch(rf"`E28-D02 / {num} ([a-z0-9-]+)`", b[1])
        if not m:
            issues.append(f"name {b[1]!r}")
        elif b[3] != f"`docs/design/E28/img/E28-D02-{num}-{m.group(1)}.png`":
            issues.append(f"export {b[3]!r} is not named by the board's slug")
        if not re.fullmatch(r"\d+", b[4]):
            issues.append(f"twins {b[4]!r} is not a count")
        else:
            twins += int(b[4])
        if b[5] != "PENDING":
            issues.append(f"state {b[5]!r}, PENDING expected")
        if issues:
            r.fail("BOARDS", f"board {num}: " + "; ".join(issues))
    if len(boards) > MAX_BOARDS:
        r.fail("BOARDS", f"{len(boards)} boards, at most {MAX_BOARDS}")
    if twins > MAX_TWINS:
        r.fail("BOARDS", f"{twins} twins, at most {MAX_TWINS}")
    r.numbers["boards"] = len(boards)
    r.numbers["twins"] = twins


def gate_slugs(ctx: Ctx, r: Result) -> None:
    for b in board_rows(ctx.spec):
        if NAME_DENY.search(b[1]) or NAME_DENY.search(b[3]):
            r.fail("SLUGS", f"board {b[0]}: {b[1]!r} holds a vault word")


def gate_frames(ctx: Ctx, r: Result) -> None:
    on_board: dict[str, str] = {}
    for b in board_rows(ctx.spec):
        for f in FRAME_RE.findall(b[2]):
            if f in on_board:
                r.fail("FRAMES", f"{f!r} on boards {on_board[f]} and {b[0]}")
            on_board[f] = b[0]
    inv: dict[str, str] = {}
    for row in register(ctx.spec):
        f = frame_of(row)
        if not f or not FRAME_RE.fullmatch(f"`{f}`"):
            r.fail("FRAMES", f"row {row[0]}: the frame cell must hold one frame name")
            continue
        issues = []
        if f in inv:
            issues.append("listed twice")
        status = row[7]
        bm = re.fullmatch(r"board (\d\d)", status)
        if bm:
            if on_board.get(f) != bm.group(1):
                issues.append(
                    f"{status} in section 7, board {on_board.get(f, 'none')} in section 0"
                )
        elif status != SPEC_:
            issues.append(f"status {status!r}")
        elif f in on_board:
            issues.append(f"on board {on_board[f]} but {SPEC_!r}")
        if not row[2] or not row[3]:
            issues.append("empty Shows or Covers")
        if issues:
            r.fail("FRAMES", f"row {row[0]} {f!r}: " + "; ".join(issues))
        inv[f] = status
    for f, num in on_board.items():
        if f not in inv:
            r.fail("FRAMES", f"board {num}: {f!r} is not on the register")
    stray = {flat(f) for f in FRAME_RE.findall(ctx.spec)} - set(inv)
    for f in sorted(stray):
        r.fail("FRAMES", f"frame name outside the register: {f!r}")
    r.numbers["frames"] = len(inv)
    r.numbers["frames_on_boards"] = sum(1 for s in inv.values() if s.startswith("board"))
    r.numbers["frames_on_request"] = sum(1 for s in inv.values() if s == SPEC_)


def gate_catalogue(ctx: Ctx, r: Result) -> None:
    phrases = {s: [*((g, "T") for g in GENERIC), *SPECIFIC[s]] for s in SCREENS}
    quoted: dict[str, set[str]] = {s: set() for s in SCREENS}
    for row in register(ctx.spec):
        scr = screen_of(frame_of(row))
        if scr not in quoted:
            continue
        wanted = {p for p, _ in phrases[scr]}
        bad = [p for p in re.findall(r'"([^"]+)"', row[3]) if p not in wanted]
        quoted[scr].update(p for p in re.findall(r'"([^"]+)"', row[3]) if p in wanted)
        if bad:
            r.fail("CATALOGUE", f"row {row[0]}: {bad} are not states of {scr}")
    total = covered = 0
    for scr in SCREENS:
        text = norm(entry(ctx.cat14, scr))
        for p, src in phrases[scr]:
            total += 1
            if src == "14" and norm(p) not in text:
                r.fail("CATALOGUE", f"{scr}: {p!r} is not in its 14 entry")
            if p in quoted[scr]:
                covered += 1
            else:
                r.fail("CATALOGUE", f"{scr}: state {p!r} has no frame")
    hand = norm(section(ctx.spec, 16))
    text61 = norm(entry(ctx.cat14, "SCR-061"))
    for p in HANDED_OFF:
        if norm(p) not in text61 or norm(p) not in hand:
            r.fail("CATALOGUE", f"SCR-061: {p!r} is not handed off in section 16")
    r.numbers["catalogue_states"] = total
    r.numbers["catalogue_covered"] = covered


def gate_sources(ctx: Ctx, r: Result) -> None:
    ops = operations(ctx.api22)
    perms = permissions(ctx.sch24)
    events = known_events([ctx.cat14, ctx.act, ctx.api22, ctx.sch24])
    codes = registered(ctx.act)
    needs = mx_permissions(ctx.mx)
    for row in register(ctx.spec):
        issues = []
        sources = 0
        rb = ticked(row[5])
        for tok in ticked(row[4]):
            if tok in ops or (tok in TOPICS and f"| `{tok}`" in ctx.ws23):
                sources += 1
                missing = needs.get(" ".join(ops[tok]), set()) - set(rb) if tok in ops else set()
                if missing:
                    issues.append(f"{tok} needs {sorted(missing)} in RBAC")
            elif re.fullmatch(r"[a-z]+[A-Z]\w*", tok):
                issues.append(f"{tok!r} is not a 22 operation")
        if re.search(r"not yet served: G-\d", row[4]):
            sources += 1
        if not sources:
            issues.append("no data source")
        issues += [f"{t!r} is not a 24 permission" for t in rb if ":" in t and t not in perms]
        if not any(t in perms or t == "self" for t in rb):
            issues.append("no RBAC permission")
        if not re.search(r"\b(Owner|Manager)\b", row[5]):
            issues.append("no role")
        evs = [t for t in ticked(row[6]) if re.fullmatch(r"[a-z_]+\.[a-z_.]+", t)]
        issues += [f"event {t!r} is named by no source" for t in evs if t not in events]
        routed = "analytics" in row[6] or re.search(r"\bC-\d", row[6])
        issues += [f"event {t!r} is not registered" for t in evs if t not in codes and not routed]
        if not evs and "no event" not in row[6]:
            issues.append("no event")
        if issues:
            r.fail("SOURCES", f"row {row[0]}: " + "; ".join(issues))
    r.numbers["operations_named"] = len(
        {t for row in register(ctx.spec) for t in ticked(row[4]) if t in ops}
    )


def gate_served(ctx: Ctx, r: Result) -> None:
    ops = operations(ctx.api22)
    states = mx_states(ctx.mx)
    stamped = 0
    for row in register(ctx.spec):
        issues = []
        stamp = "not yet served" in row[4]
        for tok in ticked(row[4]):
            if tok not in ops:
                continue
            route = " ".join(ops[tok])
            state = states.get(route)
            if state is None:
                issues.append(f"{route} is not in the RBAC matrix")
            elif state == "not_mounted" and not stamp:
                issues.append(f"{route} is not mounted and the row has no stamp")
        if stamp:
            stamped += 1
            if not re.search(r"not yet served: G-\d", row[4]):
                issues.append("the stamp names no gap id")
        if issues:
            r.fail("SERVED", f"row {row[0]}: " + "; ".join(issues))
    r.numbers["frames_not_yet_served"] = stamped


def refs(cell: str) -> list[int]:
    """The register rows a disposition names after "frame: row(s)"."""
    m = re.match(r"frame: rows? ([\d, ]+)", cell)
    return [int(n) for n in re.findall(r"\d+", m.group(1))] if m else []


def gate_checklist(ctx: Ctx, r: Result) -> None:
    table = rows(section(ctx.spec, 12), 5)
    have = {(x[1], x[3]): x for x in table}
    frames = {int(x[0]): frame_of(x) for x in register(ctx.spec)}
    expected: set[tuple[str, str]] = set()
    for scr in SCREENS:
        _, items = checklist(ctx.cat14, scr)
        for item in items:
            expected.add((scr, item))
            x = have.get((scr, item))
            if x is None:
                r.fail("CHECKLIST", f"{scr}: {item[:60]!r} is not quoted in section 12")
            elif not re.match(r"(frame: rows? \d|E34-D0[23]\b|N/A — )", x[4]):
                r.fail("CHECKLIST", f"row {x[0]}: disposition {x[4][:40]!r}")
            else:
                bad = [n for n in refs(x[4]) if screen_of(frames.get(n, "")) != scr]
                if bad:
                    r.fail("CHECKLIST", f"row {x[0]}: register rows {bad} are not {scr} frames")
    for key, x in have.items():
        if key not in expected:
            r.fail("CHECKLIST", f"row {x[0]}: {key[1][:60]!r} is not a {key[0]} checklist item")
    r.numbers["checklist_items"] = len(expected)


def gate_copy(ctx: Ctx, r: Result) -> None:
    deck = rows(section(ctx.spec, 10), 5)
    rules = " ".join(x[1] for x in deck)
    served = [
        *enum_values(ctx.api22, "TradeGroupPreview", "code"),
        *enum_values(ctx.api22, "TradeGroupPreview", "warnings"),
        *enum_values(ctx.api22, "TradeGroupReadiness", "reason"),
        *enum_values(ctx.api22, "ProfileWarning", "code"),
    ]
    keys = list(dict.fromkeys([*RULE_KEYS, *(f"`{v}`" for v in served)]))
    for key in keys:
        if key not in rules:
            r.fail("COPY", f"rule {key} has no section 10 string")
    for x in deck:
        if not x[2]:
            r.fail("COPY", f"row {x[0]}: empty string")
    r.numbers["copy_rows"] = len(deck)
    r.numbers["copy_rules"] = len(keys)
    r.numbers["copy_rules_from_22"] = len(set(served))


def gate_ruled(ctx: Ctx, r: Result) -> None:
    text = flat(ctx.spec)
    for s in RULED_STRINGS:
        if s not in text:
            r.fail("RULED", f"ruled string missing: {s[:50]!r}")
    r.numbers["ruled_strings"] = len(RULED_STRINGS)


def mock_lines(spec: str) -> list[str]:
    return [
        ln for block in re.findall(r"```\n(.*?)```", spec, re.DOTALL) for ln in block.split("\n")
    ]


def gate_safety(ctx: Ctx, r: Result) -> None:
    cells: list[tuple[str, str]] = [(f"row {x[0]} Shows", x[2]) for x in register(ctx.spec)]
    cells += [(f"copy {x[0]}", x[2]) for x in rows(section(ctx.spec, 10), 5)]
    lines = mock_lines(ctx.spec)
    for i, ln in enumerate(lines):
        if STOP_RE.search(ln):
            cells.append(
                (
                    f"mock line {ln.strip()[:30]!r}",
                    ln + " " + (lines[i + 1] if i + 1 < len(lines) else ""),
                )
            )
    checked = 0
    for where, text in cells:
        if STOP_RE.search(text):
            checked += 1
            m = CONTROL_RE.search(text)
            if m:
                r.fail("SAFETY", f"{where}: control word {m.group(0)!r} beside a stop-loss line")
    safety = [x for x in register(ctx.spec) if frame_of(x) == SAFETY_FRAME]
    if not safety or "CD-6" not in safety[0][2] or CD6 not in flat(section(ctx.spec, 5)):
        r.fail("SAFETY", "the Safety frame does not show CD-6 as the section's statement")
    deck = [x for x in rows(section(ctx.spec, 10), 5) if "`native_stop_mandatory`" in x[1]]
    if not deck or "not reachable from this UI" not in deck[0][2]:
        r.fail("SAFETY", '`native_stop_mandatory` is not listed as "not reachable from this UI"')
    r.numbers["safety_checked"] = checked


def gate_scan(ctx: Ctx, r: Result) -> None:
    s = ctx.spec
    n = {"uuid": 0, "hex": 0, "mixed": 0, "key_ids": 0, "ips": 0, "long_numbers": 0}
    for m in re.finditer(
        r"\b[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12}\b", s
    ):
        n["uuid"] += 1
        r.fail("SCAN", f"UUID-shaped id {m.group(0)[:8]}…")
    for m in re.finditer(r"(?<![0-9A-Za-z])[0-9a-fA-F]{16,}(?![0-9A-Za-z])", s):
        n["hex"] += 1
        r.fail("SCAN", f"credential-shaped hex run {m.group(0)[:6]}…")
    for m in re.finditer(r"[A-Za-z0-9]{18,}", s):
        if all(re.search(c, m.group(0)) for c in (r"\d", "[a-z]", "[A-Z]")):
            n["mixed"] += 1
            r.fail("SCAN", f"credential-shaped run {m.group(0)[:6]}…")
    for m in re.finditer(r"\.\.\.[A-Za-z0-9]{2,}", s):
        n["key_ids"] += 1
        r.fail("SCAN", f"key-id shape {m.group(0)!r}")
    for m in re.finditer(r"(?<![\d.])\d{1,3}(?:\.\d{1,3}){3}(?![\d.])", s):
        n["ips"] += 1
        r.fail("SCAN", f"IPv4 address {m.group(0)}")
    for m in re.finditer(r"(?<![\d.,])\d{7,}(?!\d)", s):
        if m.group(0) not in COMMENT_IDS:
            n["long_numbers"] += 1
            r.fail("SCAN", f"7+ digit number that is no cited comment id: {m.group(0)}")
    for m in re.finditer(r"[\w.+-]+@[\w-]+\.[\w.]+", s):
        r.fail("SCAN", f"address-shaped string {m.group(0)[:8]}…")
    for acct in sorted(set(re.findall(r"\bsub_\d+\b", s)) - FIXTURE_ACCOUNTS):
        r.fail("SCAN", f"account {acct} is not a fixture name")
    r.numbers |= {f"scan_{k}": v for k, v in n.items()}


def gate_cites(ctx: Ctx, r: Result) -> None:
    files = {
        "14": base14(ctx.cat14),
        "21": ctx.db21,
        "22": ctx.api22,
        "24": ctx.sch24,
        "ADR40": ctx.adr40,
        "MX": ctx.mx,
    }
    lines = {k: v.split("\n") for k, v in files.items()}
    for cite, text in PINS.items():
        m = re.fullmatch(r"`(\w+):(\d+)(?:-(\d+))?`", cite)
        if not m:
            continue
        a = int(m.group(2))
        b = int(m.group(3) or a)
        held = text in " ".join(lines[m.group(1)][a - 1 : b])
        if cite not in ctx.spec or not held:
            r.fail("CITES", f"pinned cite {cite} is missing from the spec or no longer holds")
    cites = 0
    for m in re.finditer(r"`(14|22):(\d+)(?:-(\d+))?`", ctx.spec):
        cites += 1
        if int(m.group(3) or m.group(2)) > len(lines[m.group(1)]):
            r.fail("CITES", f"{m.group(0)} is past the end of {m.group(1)}")
    pins = {scr: checklist(base14(ctx.cat14), scr)[0] for scr in SCREENS}
    for scr in SCREENS:
        own = [ln for ln in entry_raw(ctx.cat14, scr) if ln.startswith(OWN_POINTER)]
        if len(own) != 1:
            r.fail("CITES", f"{scr}: {len(own)} E28-D02 pointer lines in its 14 entry, 1 expected")
    for x in rows(section(ctx.spec, 12), 5):
        if x[2] != f"`14:{pins.get(x[1], 0)}`":
            r.fail("CITES", f"checklist row {x[0]}: {x[2]} is not {x[1]}'s sign-off line")
    r.numbers["pinned_cites"] = len(PINS)
    r.numbers["line_cites"] = cites


GATE_FNS: tuple[Callable[[Ctx, Result], None], ...] = (
    gate_boards,
    gate_slugs,
    gate_frames,
    gate_catalogue,
    gate_sources,
    gate_served,
    gate_checklist,
    gate_copy,
    gate_ruled,
    gate_safety,
    gate_scan,
    gate_cites,
)


def run(ctx: Ctx) -> Result:
    r = Result()
    for fn in GATE_FNS:
        fn(ctx, r)
    return r


# --- self-test -----------------------------------------------------------------------------------


def sub(old: str, new: str, count: int = 1) -> Callable[[Ctx], Ctx]:
    def apply(ctx: Ctx) -> Ctx:
        if old not in ctx.spec:
            return ctx
        return replace(ctx, spec=ctx.spec.replace(old, new, count if count > 0 else -1))

    return apply


def regex(pattern: str, repl: str) -> Callable[[Ctx], Ctx]:
    def apply(ctx: Ctx) -> Ctx:
        return replace(ctx, spec=re.sub(pattern, repl, ctx.spec, count=1, flags=re.MULTILINE))

    return apply


MUTATIONS: tuple[tuple[str, Callable[[Ctx], Ctx]], ...] = (
    ("BOARDS", regex(r"^(\| 02 .*?`docs/design/E28/img/E28-D02-02-)profile-editor", r"\1editor")),
    (
        "SLUGS",
        regex(
            r"^(\| 05 +\| `E28-D02 / 05 )symbol-matrix(`.*?E28-D02-05-)symbol-matrix",
            r"\1symbol-tokens\2symbol-tokens",
        ),
    ),
    ("FRAMES", regex(r"^(\| 4 +\| `SCR-130 / delete.*\| )board 01( +\|)$", r"\1board 02\2")),
    ("CATALOGUE", regex(r'^(\| 56 +\|.*\| )"stale-preview"', r"\1stale preview")),
    ("SOURCES", sub("`getAccountDefaultProfile`", "`getAccountDefaultProfiles`")),
    ("SERVED", regex(r"^(\| 47 +\|.*\| )not yet served: G-9; ", r"\1")),
    ("CHECKLIST", regex(r"^(\| 36 +\| SCR-133 .*\| )frame: row 34", r"\1drawn later")),
    ("COPY", regex(r"^(\| 33 +\| )`ladder_sum`", r"\1`ladder`")),
    ("RULED", sub("Capped by profile: 5x", "Capped by profile 5x", 0)),
    (
        "SAFETY",
        sub(
            "the native stop-loss statement (CD-6) as plain text",
            "the native stop-loss statement (CD-6) beside a checkbox",
        ),
    ),
    (
        "SCAN",
        sub(
            "## 1. Purpose",
            "-".join(["b1e2c3d4", "aaaa", "4bbb", "8ccc", "d" * 12]) + "\n\n## 1. Purpose",
        ),
    ),
    ("CITES", sub("`22:3499-3501`", "`22:3399-3401`", 0)),
)


def digests() -> dict[str, str]:
    paths = [SPEC, CAT14, DB21, API22, WS23, SCH24, ADR40, ACT, MX]
    return {str(p): hashlib.sha256(p.read_bytes()).hexdigest() for p in paths}


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
    ctx = load_ctx()
    res = run(ctx)
    st: list[str] = []
    testing = "--self-test" in argv
    if testing:
        st = self_test(ctx, res)
        res.numbers["mutations"] = len(MUTATIONS)
    if "--json" in argv:
        payload = {"numbers": res.numbers, "fails": res.fails, "warns": res.warns, "self_test": st}
        print(json.dumps(payload, ensure_ascii=False, indent=1, sort_keys=True))
    else:
        for line in res.fails:
            print(f"FAIL {line}")
        for line in res.warns:
            print(f"WARN {line}")
        print(
            f"gates: {len(GATES)} ({', '.join(GATES)}); "
            f"FAIL {len(res.fails)}, WARN {len(res.warns)}"
        )
        if testing:
            for line in st:
                print(f"FAIL {line}")
            verdict = "ok" if not st else "FAILED"
            print(
                f"self-test: {verdict} — {len(MUTATIONS)} mutations, one per gate, each one new "
                "FAIL; restored result identical; files on disk unchanged"
            )
    failed = bool(res.fails or st)
    return 1 if failed and ("--check" in argv or testing) else 0


if __name__ == "__main__":
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")
    sys.exit(main(sys.argv[1:]))
