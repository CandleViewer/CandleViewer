"""E14-D10 (#354) audit: the accessibility design review of the E14 drawing tools.

Stdlib only, offline (`python3 -I -B`). It reads the spec, the pins file and `14` from the working
tree, and every cited file AS TEXT at the merge-base with `origin/main` (`git show`). It imports,
never copies: the E14-D02 engine (`REG`, `registry_report`, `machine_report`, `lint_report`), the
E14-D08 union of the parents' pair lists (`Env`, `pairs_union`, `parent_pairs`, `resolve_any`), the
E12-D06 port of the CVD and Lab maths (`simulate`, `lab`, `delta_e76`), the E11-D07 key-map loader
(`load_keymap`) and `calendar_cv.sprint_range`. Default-deny: a gate that cannot read its input
FAILs.

Two modes, chosen by content, never by branch name. PR-1 mode: the spec is absent at the
merge-base; the diff may touch only the three own files and add the three `14` pointer lines.
Post-merge mode: the spec ships at the merge-base; every merged table row stands unchanged and
only later rows, the own files and the merged pointer lines may move.

Gates (each FAIL led by its code):

- [G01-FILLED] no `{{KIND:key}}` slot is left in the spec.
- [G02-AUDIT] every `<!-- audit:key=value -->` marker is a known key, equals the recomputed value
  and stands right after its visible value.
- [G03-CITE] every cited endpoint resolves at the base to a non-blank line, and its pin matches.
- [G04-PINS] the pins file and the spec's cited endpoints match both ways.
- [G05-VERBATIM] every plain quoted string in a Q07, VC or RG row stands on a line the row cites
  (±0), a `{...}` slot matching any text, a string under ten characters as a whole word; every
  Q07 expected cell holds a quoted string or begins "nothing is announced".
- [G06-SCRIPT] every Q07 row has a mechanism from the vocabulary, a rate from R-2's vocabulary,
  a source, and a host that is a live region of §5.1 for a live write, a region for focus speech
  and "no live write" for a `none` row; every VC host is a live region; RG-04 is E17-D02's pair.
- [G07-BUDGET] every BG row has a `max_rate` from R-2's vocabulary, an object and a source.
- [G08-FINDINGS] every F row has a severity from the scale, a reason, one owner token (spec and
  area, Info rows included), a target, `G-T2`, `Focus` and `Rate` from their sets and an
  `Assertion`; the hold sentence stands if and only if a Blocking row does.
- [G09-IDS] the ids of each table family are unique and in order.
- [G10-HYGIENE] no word from the private list, URL, local path, uuid, colour hex or closing
  keyword in the spec, the tool or the pins.
- [G11-SCOPE] no Q07 expected cell carries a role name, another user's handle, an opaque id or an
  account other than the fixture's active one.
- [G12-RULED] section R lists BQ-01..BQ-25 once each with the ruling stamp; every "RULED BQ-nn"
  stamp names a listed BQ.
- [G13-SCOPE] the changed paths are the own files and `14` only.
- [G14-POINTERS] `14` differs from the base by exactly the three pointer lines, each inside its
  entry.
- [G15-FREEZE] post-merge mode: every merged table row stands unchanged.
- [G16-CONTRAST] the union of the parents' gated pairs has no pair under its bar in any theme;
  §13.4 states the CVD method the imported port runs; no candle ink defeats both handle tones.
- [G17-BUDGET-SIM] the 60 s worst case keeps at most two writes in any second, drops only
  class-4 values and speaks every confirmation and the trailing flush.
- [G18-KEYMAP] a KB row's shipped ids exist in the key map; a key a row says is not in the key
  map is bound by no command of the Chart or Global context.
- [G19-WALK] the KW rows are D02's registry rows, one each, with its anchor count, its arming key
  and the place chain its anchor count gives in the machine.
- [G20-VOCAB] every sentence of every quoted VC string has at most ten words (class 1 aside).
- [G21-PARITY] every row of D07's action-parity table has a PA row, and no PA row reads "gap".
- [G22-WCAG] every WC row names an artefact, and the criteria the ticket names are all present.
- [G23-DRAG] every DR row has both alternatives, its images exist at the base, and a row drawn
  in text only names an F row that exists.
- [G24-T2] the T2 rule names CMP-079 RbacGate and CMP-026 with `cta` omitted; every T2 row names
  its §3.1 key (both legs and the §3.2 verb for a role leg), its component and a rendering,
  `Focus` and `Rate` from their sets.

`--json` prints the numbers and findings; `--check` exits 1 on any FAIL; `--fill` writes the
computed values into the spec's slots and markers; `--self-test` applies one mutation per gate to
an in-memory copy (the lens round's escaped mutations included) and passes only when each adds
FAILs of its gate's code and the base run is clean; `--repin-ruled` rewrites the pins file from the spec's cites and is its only writer.

Usage: python3 -I -B docs/design/_tools/e14_d10_a11y_review_audit.py [--check] [--json] [--fill]
       [--self-test] [--repin-ruled]
"""

from __future__ import annotations

import argparse
import codecs
import dataclasses
import datetime
import functools
import hashlib
import importlib.util
import itertools
import json
import re
import subprocess
import sys
from collections.abc import Callable
from pathlib import Path
from types import ModuleType
from typing import Any

ROOT = Path(__file__).resolve().parents[3]
TOOLS = ROOT / "docs" / "design" / "_tools"
SPEC_REL = "docs/design/E14/E14-D10.md"
TOOL_REL = "docs/design/_tools/e14_d10_a11y_review_audit.py"
PINS_REL = "docs/design/_tools/e14_d10_ruled_pins.txt"
P14_REL = "docs/plan/14-screens-catalogue.md"
OWN = {SPEC_REL, TOOL_REL, PINS_REL}
UPSTREAM = "origin/main"
BQ_BASE = "8addd87a734ea3ddc96f4ff0f7a79bcbf702d81d"  # where the BQ list read every cite
BQ_COUNT = 25
RULED_STAMP = "RULED (orchestrator, 2026-10-31, #354 ruling of record — 6546285999's answer)"
POINTER_MARK = "**A11y review (E14-D10):**"
POINTER_ENTRIES = ("SCR-036", "SCR-037", "SCR-045")
POINTER_HEAD = f"- {POINTER_MARK} [E14-D10.md](../design/E14/E14-D10.md) (E14-D10; "
IMG_DIR = "docs/design/E14/img"
KM_REL = "apps/web/src/keymap/keymap.json"
CAL_REL = "docs/plan/backlog/_tools/calendar_cv.py"
D07_REL = "docs/design/E14/E14-D07.md"
D08_REL = "docs/design/E14/E14-D08.md"
D09_REL = "docs/design/E14/E14-D09.md"

DESIGN_KEYS = {f"D0{n}": f"docs/design/E14/E14-D0{n}.md" for n in range(2, 10)}
KEY_RE = r"D0[2-9]|\d\d|E\d\d-D\d\d"
MD_CITE = re.compile(
    rf"`(?P<key>{KEY_RE})`:(?P<a>\d+)(?:[–-](?P<b>\d+))?(?P<more>(?:, :\d+(?:[–-]\d+)?)*)"
)
BARE_CITE = re.compile(
    rf"(?<![\w`:.-])(?P<key>{KEY_RE}):(?P<a>\d+)(?:[–-](?P<b>\d+))?(?P<more>(?:, :\d+(?:[–-]\d+)?)*)"
)
MORE = re.compile(r":(\d+)(?:[–-](\d+))?")
SLOT = re.compile(r"\{\{([A-Z]+):([\w.-]+)\}\}")
AUDIT = re.compile(r"<!-- audit:([\w.-]+)=([^>]*?) -->")
QUOTE = re.compile(r'"([^"]*)"')
ITALIC_QUOTE = re.compile(r'[*_]"[^"]*"[*_]')  # Prettier writes `_"…"_` outside code blocks
BRACE = re.compile(r"\{[^{}]*\}")

MECHANISMS = {"name", "role", "desc", "polite", "alert", "text", "cell", "none"}
LIVE_MECHANISMS = {"polite", "alert"}
RATE_UNITS = (
    "episode|entry|change|press|action|key-down|key|release|focus entry|focus|open|arm|region"
)
RATE = re.compile(
    rf"^(?:never|on request|once per (?:{RATE_UNITS})\b"
    rf"|≤ \d+ per \d+ s (?:per (?:{RATE_UNITS})\b|across RG-\d\d(?: and RG-\d\d)*))"
)
G_T2 = re.compile(r"^(?:n/a|T2 · (?:2a|2b|sentence)|validity|availability)$")
T2_RENDER = re.compile(r"^T2 · (?:2a|2b|sentence)\b")
FOCUS = re.compile(r"^(?:n/a|(?:kept|moves to|restored to|returns to) · \S.*)$")
OWNER = re.compile(r"^`E\d\d-D\d\d · area/[a-z-]+`$")
RG_ID = re.compile(r"RG-\d\d")
NOTHING = "nothing is announced"
NO_LIVE = "no live write"
T2_KEYS = re.compile(r"`(rbac\.(?:view_as|permission|owner_only)|drawing\.locked|v\.risk\.cap)`")
HANDLE_INKS = ("color.candle.up", "color.candle.down", "color.candle.wick")
SEVERITIES = ("Blocking", "Major", "Minor", "Info")
# rot13 keeps the private list out of plain text; underscores stand for spaces.
BANNED_ROT13 = (
    "yrnx rkcbfrq olcnff rkcybvg nggnpx benpyr erirny haobhaqrq sybbq fgnyy qbf nqivfbel tufn "
    "cer-nhgu ucr-jbexre znva-bepurfgengbe"
)
BANNED = [w.replace("_", " ") for w in codecs.decode(BANNED_ROT13, "rot13").split()]
URL = re.compile(r"https?://|\bwww\.", re.IGNORECASE)
UUID = re.compile(r"\b[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}\b")
LOCAL_PATH = re.compile("|".join("/" + w + "/" for w in ("home", "mnt", "tmp")))
COLOUR_HEX = re.compile(r"#[0-9A-Fa-f]{6}\b")
CLOSING = re.compile(r"\b(?:close[sd]?|fix(?:e[sd])?|resolve[sd]?) #\d+", re.IGNORECASE)
ROLE_WORDS = re.compile(r"\b(?:Owner|Manager|Admin|owner|manager|admin|sub_user)\b")
OPAQUE_ID = re.compile(r"\bu_[A-Za-z0-9]{22}\b")
ACCOUNT_LINE = re.compile(r"(?:Sized for|·) ([A-Z][a-z]+) · (?:DEMO|LIVE)")
ACTIVE_ACCOUNT = "Main"

# the criteria `T Scope` bullet 6 names, plus the method's additions (§13.2)
CRITERIA = (
    *("1.3.1", "1.4.1", "1.4.3", "1.4.4", "1.4.10", "1.4.11", "1.4.13", "2.1.1", "2.1.2"),
    *("2.1.4", "2.2.2", "2.3.1", "2.4.3", "2.4.7", "2.4.11", "2.5.1", "2.5.7", "2.5.8"),
    *("3.3.1", "3.3.3", "4.1.2", "4.1.3"),
)
PARENT_TAGS = ("E14-D08", "D03", "D04", "D05", "D06", "D07")
BAR = {"TEXT": 4.5, "NON_TEXT": 3.0}
GREY_WEIGHTS = (0.299, 0.587, 0.114)  # Rec. 601 luma, as cvd_sim.py's to_greyscale
CARRIER_PAIRS: dict[str, tuple[str, str]] = {
    "selected": ("color.drawing.selected", "color.drawing.default"),
    "locked": ("color.drawing.locked", "color.drawing.default"),
    "side": ("color.buy.default", "color.sell.default"),
    "zones": ("color.position.loss.subtle", "color.position.reward.subtle"),
    "snap": ("color.drawing.snap", "color.surface.canvas"),
    "handle": ("color.drawing.handle", "color.drawing.handle.ring"),
    "focus": ("color.chart.focus.ring", "color.chart.pane.bg.default"),
    "t2": ("color.text.tertiary", "color.text.primary"),
}
CONSUMER_SPRINTS = {"s05": 5, "s06": 6, "s07": 7, "s08": 8, "s09": 9}
CHAINS = {
    "1": "T01 → T15 → T37 / T38",
    "2": "T01 → T16 → T26 → T37 / T38",
    "3": "T01 → T16 → T25 → T26 → T37 / T38",
    "2..100": "T01 → T16 → T25 … → T27 → T37 / T38",
}
DEFERRED_CHAIN = "deferred, no story"


# --------------------------------------------------------------------------------------- git


def git(*args: str) -> str:
    out = subprocess.run(
        ["git", *args],
        cwd=ROOT,
        capture_output=True,
        text=True,
        encoding="utf-8",
        check=False,
        timeout=60,
    )
    return out.stdout if out.returncode == 0 else ""


@functools.cache
def merge_base() -> str:
    return git("merge-base", "HEAD", UPSTREAM).strip()


@functools.cache
def show(rev: str, rel: str) -> str | None:
    out = subprocess.run(
        ["git", "show", f"{rev}:{rel}"],
        cwd=ROOT,
        capture_output=True,
        text=True,
        encoding="utf-8",
        check=False,
        timeout=60,
    )
    return out.stdout if out.returncode == 0 else None


@functools.cache
def plan_path(nn: str, rev: str) -> str | None:
    for name in git("ls-tree", "--name-only", rev, "docs/plan/").split():
        if Path(name).name.startswith(f"{nn}-") and name.endswith((".md", ".yaml")):
            return name
    return None


def key_path(key: str, rev: str) -> str | None:
    if key in DESIGN_KEYS:
        return DESIGN_KEYS[key]
    if re.fullmatch(r"\d\d", key):
        return plan_path(key, rev)
    m = re.fullmatch(r"(E\d\d)-(D\d\d)", key)
    return f"docs/design/{m[1]}/{key}.md" if m else None


def read(rel: str) -> str:
    p = ROOT / rel
    return p.read_text(encoding="utf-8") if p.exists() else ""


# ----------------------------------------------------------------------------------- imports


@functools.cache
def engine(name: str, rel: str = "") -> ModuleType:
    path = ROOT / (rel or f"docs/design/_tools/{name}.py")
    if str(TOOLS) not in sys.path:
        sys.path.insert(0, str(TOOLS))
    spec = importlib.util.spec_from_file_location(name, path)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"cannot import {name}")
    mod = importlib.util.module_from_spec(spec)
    sys.modules[name] = mod
    spec.loader.exec_module(mod)
    return mod


def d02() -> ModuleType:
    return engine("e14_d02_interaction_audit")


def d08() -> ModuleType:
    return engine("e14_d08_ds_audit")


# ----------------------------------------------------------------------------------- parsing


def heading_level(line: str) -> int:
    m = re.match(r"(#{1,6}) ", line)
    return len(m[1]) if m else 0


def section(text: str, prefix: str) -> str:
    lines = text.split("\n")
    for i, line in enumerate(lines):
        lvl = heading_level(line)
        if lvl and line[lvl + 1 :].startswith(prefix):
            out = []
            for nxt in lines[i + 1 :]:
                n = heading_level(nxt)
                if n and n <= lvl:
                    break
                out.append(nxt)
            return "\n".join(out)
    return ""


def cells(line: str) -> list[str]:
    return [c.strip() for c in line.strip().strip("|").split("|")]


def rows(block: str, family: str) -> list[list[str]]:
    pat = re.compile(rf"^\s*\|\s*{re.escape(family)}-[\w]+\s*\|")
    return [cells(ln) for ln in block.split("\n") if pat.match(ln)]


def q07_rows(spec: str) -> list[list[str]]:
    return [cells(ln) for ln in spec.split("\n") if re.match(r"^\s+\| Q07-\d+ ", ln)]


def norm(s: str) -> str:
    return re.sub(r"\s+", " ", s.replace("`", "").replace("*", "")).strip()


def line_hash(s: str) -> str:
    return hashlib.sha1(norm(s).encode("utf-8")).hexdigest()[:16]


def cite_spans(text: str, bare: bool = False) -> list[tuple[str, int, int]]:
    out: list[tuple[str, int, int]] = []
    for m in (BARE_CITE if bare else MD_CITE).finditer(text):
        key = m["key"]
        a = int(m["a"])
        out.append((key, a, int(m["b"]) if m["b"] else a))
        for mm in MORE.finditer(m["more"] or ""):
            x = int(mm[1])
            out.append((key, x, int(mm[2]) if mm[2] else x))
    return out


def all_cites(spec: str) -> list[tuple[str, int, int]]:
    spans = cite_spans(spec)
    for r in q07_rows(spec):
        spans += cite_spans(r[-1], bare=True)
    return spans


def endpoints(spec: str) -> set[tuple[str, int]]:
    out: set[tuple[str, int]] = set()
    for key, a, b in all_cites(spec):
        out.add((key, a))
        out.add((key, b))
    return out


def parse_pins(pins: str) -> dict[tuple[str, int], str]:
    out: dict[tuple[str, int], str] = {}
    for ln in pins.split("\n"):
        m = re.fullmatch(rf"({KEY_RE}):(\d+) ([0-9a-f]{{16}})", ln.strip())
        if m:
            out[(m[1], int(m[2]))] = m[3]
    return out


def plain_quotes(cell: str) -> list[str]:
    return QUOTE.findall(ITALIC_QUOTE.sub("", cell))


def quote_pattern(q: str) -> re.Pattern[str]:
    parts = BRACE.split(norm(q))
    return re.compile(".+?".join(re.escape(p) for p in parts))


def sentences(q: str) -> list[str]:
    return [s for s in re.split(r"(?<=[.?!])\s+", BRACE.sub("x", q).strip()) if s]


def word_count(sentence: str) -> int:
    return sum(1 for tok in sentence.split() if re.search(r"\w", tok))


# ------------------------------------------------------------------------------------ context

ContrastRow = tuple[str, str, str, str, dict[str, float]]  # tag, fg, bg, bar ("" = none), ratios


@dataclasses.dataclass
class Ctx:
    spec: str
    pins: str
    tool: str
    p14: str
    p14_base: str
    changed: list[str]
    merged_spec: str | None
    base: str
    base_date: datetime.date
    images: list[str]
    contrast: list[ContrastRow]  # every parent row, ratios from the union
    union: list[ContrastRow]  # one row per {fg, bg}, the stricter bar
    combined_rule: bool = True

    def base_line(self, key: str, n: int) -> str | None:
        rel = key_path(key, self.base)
        text = show(self.base, rel) if rel else None
        if text is None:
            return None
        lines = text.split("\n")
        return lines[n - 1] if 0 < n <= len(lines) else None


def load_contrast(base: str) -> tuple[list[ContrastRow], list[ContrastRow]]:
    mod = d08()
    env = mod.Env(base, {})
    spec = env.at_base(D08_REL)
    union: list[ContrastRow] = []
    by_pair: dict[tuple[str, str], dict[str, float]] = {}
    for r in mod.pairs_union(env, spec):
        ratios = {str(t): float(v) for t, v in r.ratios.items()}
        by_pair[(r.fg, r.bg)] = ratios
        union.append(("union", str(r.fg), str(r.bg), str(r.bar or ""), ratios))
    raw: list[ContrastRow] = []
    for fg, bg, bar, src in mod.parent_pairs(env, spec):
        tag = str(src).split(" ")[0].split(":")[0]
        raw.append((tag, str(fg), str(bg), str(bar or ""), by_pair.get((fg, bg), {})))
    return raw, union


def build_ctx(with_contrast: bool = True) -> Ctx:
    base = merge_base()
    changed = sorted(
        {
            *git("diff", "--name-only", base).split(),
            *git("ls-files", "-o", "--exclude-standard").split(),
        }
    )
    date_s = git("show", "-s", "--format=%cs", base).strip() or "1970-01-01"
    raw, union = load_contrast(base) if with_contrast else ([], [])
    return Ctx(
        spec=read(SPEC_REL),
        pins=read(PINS_REL),
        tool=read(TOOL_REL),
        p14=read(P14_REL),
        p14_base=show(base, P14_REL) or "",
        changed=changed,
        merged_spec=show(base, SPEC_REL),
        base=base,
        base_date=datetime.date.fromisoformat(date_s),
        images=[Path(p).name for p in git("ls-tree", "--name-only", base, f"{IMG_DIR}/").split()],
        contrast=raw,
        union=union,
    )


# ------------------------------------------------------------------------------- the numbers


def simulate(combined: bool) -> dict[str, int]:
    """§8.4: 60 s of a held nudge key, a snap press, commits, a delete, an undo and an episode."""
    cand: dict[int, list[tuple[int, str]]] = {}
    for t in range(0, 60_000, 500):  # the repeat window carries the latest value
        cand.setdefault(t, []).append((4, "value"))
    cand.setdefault(40_200, []).append((4, "snap"))
    cand.setdefault(60_100, []).append((4, "flush"))  # trailingFlush ≤ 250 ms after release
    confirmations = [(t, "commit") for t in range(2_500, 60_000, 5_000)]
    confirmations += [(21_000, "delete"), (23_000, "undo")]
    for t, what in confirmations:
        cand.setdefault(t, []).append((2, what))
    cand.setdefault(30_500, []).append((3, "unsaved"))
    spoken: list[tuple[int, int, str]] = []
    pending: list[tuple[int, str]] = []
    dropped: list[tuple[int, str]] = []
    last2 = -10_000
    for t in range(62_000):
        for item in cand.get(t, []):
            if item[0] == 4:
                for old in [p for p in pending if p[0] == 4]:
                    pending.remove(old)
                    dropped.append(old)
            pending.append(item)
        if not pending:
            continue
        if not combined:
            for p in pending:
                spoken.append((t, p[0], p[1]))
            pending.clear()
            continue
        window = sum(1 for s in spoken if t - 1000 < s[0] <= t)
        pending.sort()
        head = pending[0]
        if window >= 2:
            continue
        if head[0] == 2 and t - last2 < 500:
            continue
        spoken.append((t, head[0], head[1]))
        pending.remove(head)
        if head[0] == 2:
            last2 = t
    peak = max(sum(1 for s in spoken if t - 1000 < s[0] <= t) for t in range(0, 62_000, 50))
    return {
        "max": peak,
        "dropped_non4": sum(1 for d in dropped if d[0] != 4) + sum(1 for p in pending if p[0] != 4),
        "class2_spoken": sum(1 for s in spoken if s[1] == 2),
        "class2_total": len(confirmations),
        "flush_kept": int(any(s[2] == "flush" for s in spoken)),
    }


def colour(base: str, token: str) -> str:
    mod = d08()
    env = mod.Env(base, {})
    hexv = mod.resolve_any(env, env.at_base(D08_REL), "dark", token)
    if not hexv:
        raise ValueError(f"{token} does not resolve in the dark theme")
    return str(hexv)


def grey_l(hex6: str) -> float:
    h = hex6.lstrip("#")
    r, g, b = (int(h[i : i + 2], 16) for i in (0, 2, 4))
    y = round(GREY_WEIGHTS[0] * r + GREY_WEIGHTS[1] * g + GREY_WEIGHTS[2] * b)
    lab = engine("e12_d06_series_audit").lab(f"#{y:02X}{y:02X}{y:02X}")
    return float(lab[0])


def carrier_values(ctx: Ctx) -> dict[str, str]:
    port = engine("e12_d06_series_audit")
    out: dict[str, str] = {}
    for key, (a, b) in CARRIER_PAIRS.items():
        ha, hb = colour(ctx.base, a), colour(ctx.base, b)
        out[f"grey.{key}"] = f"{abs(grey_l(ha) - grey_l(hb)):.1f}"
        des = [
            float(port.delta_e76(port.simulate(ha, d), port.simulate(hb, d)))
            for d in ("protanopia", "deuteranopia", "tritanopia")
        ]
        out[f"cvd.{key}"] = " / ".join(f"{x:.1f}" for x in des)
    return out


def contrast_values(ctx: Ctx) -> dict[str, str]:
    out: dict[str, str] = {}
    groups: dict[str, list[ContrastRow]] = {t.lower(): [] for t in PARENT_TAGS}
    for row in ctx.contrast:
        groups.setdefault(row[0].lower(), []).append(row)
    groups["union"] = ctx.union
    for k, rows_ in groups.items():
        gated = [r for r in rows_ if r[3] in BAR]
        fails = [(r, t) for r in gated for t, v in r[4].items() if v < BAR[r[3]]]
        lows = [(v, t, r) for r in gated for t, v in r[4].items()]
        out[f"pairs.{k}"] = str(len(rows_))
        out[f"gated.{k}"] = str(len(gated))
        out[f"fail.{k}"] = str(len(fails))
        if lows:
            v, t, r = min(lows, key=lambda x: x[0])
            name = f"{r[1]} on {r[2]}".replace("color.", "")
            out[f"low.{k}"] = f"{v:.2f}:1 ({t}, {name})"
        else:
            out[f"low.{k}"] = "—"
    return out


def sprint_values(ctx: Ctx) -> dict[str, str]:
    cal = engine("calendar_cv", CAL_REL)
    out: dict[str, str] = {}
    for n in (5, 6):
        s, e = cal.sprint_range(n)
        out[f"s0{n}.start"], out[f"s0{n}.end"] = s.isoformat(), e.isoformat()
    for key, n in CONSUMER_SPRINTS.items():
        start, _ = cal.sprint_range(n)
        ahead = start - datetime.timedelta(days=14)
        out[f"ahead.{key}"] = ahead.isoformat()
        if key == "s09":
            out["ahead.s09.status"] = "open" if ahead >= ctx.base_date else "missed"
    return out


def registry_values() -> dict[str, str]:
    mod = d02()
    sink: list[str] = []
    reg = mod.registry_report(sink)
    mach = mod.machine_report(sink)
    lint = mod.lint_report(sink)
    rail = [r for r in mod.REG if r[2] != "-" and str(r[7]).startswith("R1")]
    cls = reg["anchor_classes"]
    return {
        "reg-rows": str(reg["reg_rows"]),
        "rail-api": str(reg["rail_api"]),
        "class1": str(cls["1"]),
        "class2": str(cls["2"]),
        "class2-rail": str(sum(1 for r in rail if r[3] == "2")),
        "class3": str(cls["3"]),
        "class3-rail": str(sum(1 for r in rail if r[3] == "3")),
        "classn": str(cls["n"]),
        "deferred": str(reg["deferred"]),
        "machine-pairs": str(mach["pairs"]),
        "machine-missing": str(mach["missing"]),
        "lint-scr037": str(len(lint["scr037"])),
        "lint-scr037-table": str(len(lint["scr037_table"])),
        "lint-a": str(len(lint["a"])),
        "lint-b": str(len(lint["b"])),
    }


def table_count(block: str) -> int:
    return max(0, sum(1 for ln in block.split("\n") if ln.startswith("| ")) - 1)


def table_body(block: str) -> list[str]:
    """The body rows of the first table in a block: every row after its separator line."""
    lines = block.split("\n")
    for i, ln in enumerate(lines):
        if re.match(r"^\|\s*:?-{3,}", ln):
            out = []
            for nxt in lines[i + 1 :]:
                if not nxt.startswith("|"):
                    break
                out.append(nxt)
            return out
    return []


def handle_values(ctx: Ctx) -> dict[str, str]:
    """§13.4.1: the handle's dot and ring against each candle ink, in the three themes."""
    mod = d08()
    env = mod.Env(ctx.base, {})
    spec = env.at_base(D08_REL)
    out: dict[str, str] = {}
    both_low = 0
    for ink in HANDLE_INKS:
        low: dict[str, list[bool]] = {"dot": [], "ring": []}
        for tone, tok in (("dot", "color.drawing.handle"), ("ring", "color.drawing.handle.ring")):
            vals = []
            for th in mod.THEMES:
                a, b = mod.resolve_any(env, spec, th, tok), mod.resolve_any(env, spec, th, ink)
                if not a or not b:
                    raise ValueError(f"{tok} or {ink} does not resolve in {th}")
                r = float(mod.contrast(a, b))
                low[tone].append(r < 3.0)
                vals.append(str(mod.show_ratio(r)))
            out[f"hink.{tone}.{ink.removeprefix('color.')}"] = " / ".join(vals)
        both_low += sum(1 for d, r in zip(low["dot"], low["ring"], strict=True) if d and r)
    out["hink"] = str(len(HANDLE_INKS))
    out["hink-both-low"] = str(both_low)
    return out


FAMILIES: dict[str, tuple[str, str]] = {
    "kw": ("3.1 ", "KW"),
    "kb": ("3.2 ", "KB"),
    "dr": ("3.3 ", "DR"),
    "fm": ("4. ", "FM"),
    "rg": ("5.1 ", "RG"),
    "vc": ("7.1 ", "VC"),
    "bg": ("8.1 ", "BG"),
    "ow": ("9. ", "OW"),
    "pa": ("10.1 ", "PA"),
    "po": ("10.2 ", "PO"),
    "ts": ("11. ", "TS"),
    "t2": ("12.1 ", "T2"),
    "sd": ("12.2 ", "SD"),
    "wc": ("13.2 ", "WC"),
    "f": ("14. ", "F"),
    "c": ("15.1 ", "C"),
    "g": ("15.2 ", "G"),
    "a": ("15.4 ", "A"),
    "ks": ("16.1 ", "KS"),
}


def fam(spec: str, key: str) -> list[list[str]]:
    sec, family = FAMILIES[key]
    return rows(section(spec, sec), family)


def d07_parity(base: str) -> list[list[str]]:
    text = show(base, D07_REL) or ""
    block = section(text, "9.2 ")
    return [cells(ln) for ln in block.split("\n") if ln.startswith("| ")][2:]


def scope_hits(cell: str) -> list[str]:
    hits = [m[0] for m in ROLE_WORDS.finditer(cell)]
    hits += [m[0] for m in OPAQUE_ID.finditer(cell)] + [m[0] for m in UUID.finditer(cell)]
    hits += [m[1] for m in ACCOUNT_LINE.finditer(cell) if m[1] != ACTIVE_ACCOUNT]
    return hits


def vc_words(spec: str) -> list[tuple[str, str, int]]:
    out: list[tuple[str, str, int]] = []
    for r in fam(spec, "vc"):
        if len(r) < 8 or r[5].startswith("1"):
            continue
        for q in QUOTE.findall(r[2]):
            for s in sentences(q):
                out.append((r[0], s, word_count(s)))
    return out


def keymap_collisions(ctx: Ctx, km: dict[str, Any]) -> int:
    named = set(re.findall(r"`((?:chart|global)\.[\w.]+)`", section(ctx.spec, "3.2 ")))
    seen: dict[tuple[str, str], int] = {}
    for c in km["commands"]:
        if c["id"] in named:
            k = (str(c["context"]), str(c["defaultBinding"]))
            seen[k] = seen.get(k, 0) + 1
    return sum(n - 1 for n in seen.values() if n > 1)


def compute(ctx: Ctx) -> dict[str, str]:
    spec = ctx.spec
    v: dict[str, str] = {"sha": ctx.base}
    for key in FAMILIES:
        v[key] = str(len(fam(spec, key)))
    for key in ("kw", "dr", "fm", "f"):
        v[f"{key}-summary"] = v[key]
    q = q07_rows(spec)
    v["q07"] = v["q07-summary"] = str(len(q))
    v["q07-readings"] = str(sum(1 for r in q if len(r) > 3 and "PROPOSED reading" in r[3]))
    v["q07-proposed"] = str(sum(1 for r in q if len(r) > 3 and "none merged — PROPOSED" in r[3]))
    vc = fam(spec, "vc")
    v["vc-readings"] = str(sum(1 for r in vc if "reading C-" in " ".join(r[1:3])))
    words = vc_words(spec)
    v["vc-max-words"] = str(max((w for _, _, w in words), default=0))
    fm = fam(spec, "fm")
    v["fm-derived"] = str(sum(1 for r in fm if len(r) > 6 and r[6].startswith("derived")))
    v["fm-unstated"] = str(sum(1 for r in fm if len(r) > 6 and r[6].startswith("unstated")))
    pa = fam(spec, "pa")
    v["pa-d07"] = str(len(d07_parity(ctx.base)))
    v["pa-gap"] = str(sum(1 for r in pa if "gap" in r[-1]))
    ts = fam(spec, "ts")
    v["ts-fail"] = str(sum(1 for r in ts if len(r) > 4 and "fail" in (r[3] + r[4]).lower()))
    wc = fam(spec, "wc")
    v["wc-none"] = str(sum(1 for r in wc if len(r) < 4 or r[3].strip() in ("", "none", "—")))
    v["clauses"] = str(sum(1 for ln in section(spec, "13.1 ").split("\n") if ln.startswith("| §")))
    v["carriers"] = str(len(table_body(section(spec, "13.4 "))))
    fr = fam(spec, "f")
    for sev in SEVERITIES:
        v[f"f.{sev.lower()}"] = str(sum(1 for r in fr if len(r) > 1 and r[1] == sev))
    v["hr"] = str(len(re.findall(r"^- \*\*HR-\d+\*\*", section(spec, "15.5 "), re.MULTILINE)))
    v["pointer-lines"] = str(sum(1 for ln in ctx.p14.split("\n") if POINTER_MARK in ln))
    v["images"] = v["inventory-images"] = str(len(ctx.images))
    for n in range(2, 10):
        v[f"images.d0{n}"] = str(sum(1 for p in ctx.images if p.startswith(f"E14-D0{n}-")))
    km = json.loads(show(ctx.base, KM_REL) or "{}")
    v["km-commands"] = str(len(km.get("commands", [])))
    v["km-version"] = str(km.get("version", "?"))
    v["kb-undeclared"] = str(keymap_collisions(ctx, km))
    changed = set(git("diff", "--name-only", BQ_BASE, ctx.base).split())
    cited = {key_path(k, ctx.base) for k, _, _ in all_cites(spec)}
    v["bq-moved"] = str(len({p for p in cited if p} & changed))
    d09 = show(ctx.base, D09_REL) or ""
    v["d09-rows"] = str(len(rows(section(d09, "2. "), "D9")))
    sim = simulate(ctx.combined_rule)
    v["sim.max-per-1s"] = str(sim["max"])
    v["sim.dropped-non-class4"] = str(sim["dropped_non4"])
    v["sim.class2-spoken"] = str(sim["class2_spoken"])
    v["sim.class2-total"] = str(sim["class2_total"])
    v["sim.flush-kept"] = "kept" if sim["flush_kept"] else "lost"
    v["sd.scope-hits"] = str(sum(len(scope_hits(r[3])) for r in q if len(r) > 3))
    v.update(registry_values())
    v.update(contrast_values(ctx))
    ok = v.get("fail.union") == "0"
    v["clause.contrast"] = "compliant" if ok else "at risk"
    v["wcag.143"] = v["wcag.1411"] = "compliant" if ok else "at risk"
    v.update(carrier_values(ctx))
    v.update(handle_values(ctx))
    v.update(sprint_values(ctx))
    return v


# ------------------------------------------------------------------------------------- gates


Findings = list[tuple[str, str]]
RUN_ERRORS = (
    OSError,
    ValueError,
    KeyError,
    IndexError,
    TypeError,
    AttributeError,
    RuntimeError,
    SystemExit,
    subprocess.SubprocessError,
)


def g_filled(ctx: Ctx, vals: dict[str, str], f: Findings) -> None:
    for m in SLOT.finditer(ctx.spec):
        f.append(("G01-FILLED", f"slot {m[0]} is not filled"))


def g_audit(ctx: Ctx, vals: dict[str, str], f: Findings) -> None:
    for m in AUDIT.finditer(ctx.spec):
        key, val = m[1], m[2]
        if key not in vals:
            f.append(("G02-AUDIT", f"marker {key!r} is not a key the tool computes"))
            continue
        if vals[key] != val:
            f.append(("G02-AUDIT", f"{key}: the marker says {val!r}, the tool {vals[key]!r}"))
        if not ctx.spec[: m.start()].rstrip().rstrip("`").endswith(val):
            f.append(("G02-AUDIT", f"{key}: the visible value before the marker is not {val!r}"))
    # an independent count, not the helper `compute` uses: one state per row, header excluded
    head = section(ctx.spec, "13.4 ").split("#### ")[0]
    states = [
        cells(ln)[0]
        for ln in head.split("\n")
        if ln.startswith("| ") and not set(cells(ln)[0]) <= set("-: ")
    ][1:]
    shown = re.search(r"(\d+) <!-- audit:carriers=", ctx.spec)
    if not shown or int(shown[1]) != len(states):
        f.append(("G02-AUDIT", f"carriers: the table holds {len(states)} states, not the marker's"))


def g_cite(ctx: Ctx, vals: dict[str, str], f: Findings) -> None:
    pins = parse_pins(ctx.pins)
    for key, n in sorted(endpoints(ctx.spec)):
        line = ctx.base_line(key, n)
        if line is None or not line.strip():
            f.append(("G03-CITE", f"{key}:{n} does not resolve to a non-blank line at the base"))
            continue
        if (key, n) in pins and pins[(key, n)] != line_hash(line):
            f.append(("G03-CITE", f"{key}:{n} moved: its pin no longer matches the base line"))


def g_pins(ctx: Ctx, vals: dict[str, str], f: Findings) -> None:
    pins = set(parse_pins(ctx.pins))
    ends = endpoints(ctx.spec)
    for k, n in sorted(ends - pins):
        f.append(("G04-PINS", f"{k}:{n} is cited but not pinned"))
    for k, n in sorted(pins - ends):
        f.append(("G04-PINS", f"{k}:{n} is pinned but no longer cited"))


def hay_for(ctx: Ctx, spans: list[tuple[str, int, int]]) -> list[str]:
    """The cited lines exactly (±0): one entry per cited span."""
    hay: list[str] = []
    for key, a, b in spans:
        span = [ctx.base_line(key, n) or "" for n in range(a, b + 1)]
        hay.append(norm(" ".join(span)))
    return hay


def quote_found(q: str, hay: list[str]) -> bool:
    """A string of ten characters or more as a substring; a shorter one as a whole word."""
    pat = quote_pattern(q)
    if len(norm(q)) >= 10:
        return any(pat.search(h) for h in hay)
    word = re.compile(rf"(?<!\w){pat.pattern}(?!\w)")
    return any(word.search(h) for h in hay)


def g_verbatim(ctx: Ctx, vals: dict[str, str], f: Findings) -> None:
    checks: list[tuple[str, str, list[str]]] = []
    for r in q07_rows(ctx.spec):
        if len(r) < 8:
            f.append(("G05-VERBATIM", f"{r[0]}: the row has {len(r)} cells, not 8"))
            continue
        if (
            not plain_quotes(r[3])
            and not ITALIC_QUOTE.search(r[3])
            and not r[3].startswith(NOTHING)
        ):
            f.append(("G05-VERBATIM", f"{r[0]}: no quoted string and no {NOTHING!r}"))
        checks.append((r[0], r[3], hay_for(ctx, cite_spans(r[-1], bare=True))))
    for r in fam(ctx.spec, "vc"):
        if len(r) < 8:
            f.append(("G05-VERBATIM", f"{r[0]}: the row has {len(r)} cells, not 8"))
            continue
        checks.append((r[0], r[2], hay_for(ctx, cite_spans(r[-1]))))
    for r in fam(ctx.spec, "rg"):
        if len(r) >= 6:
            checks.append((r[0], f"{r[2]} {r[3]}", hay_for(ctx, cite_spans(r[-1]))))
    for rid, cell, hay in checks:
        for q in plain_quotes(cell):
            if q and not quote_found(q, hay):
                f.append(("G05-VERBATIM", f"{rid}: {q[:48]!r} stands on no line the row cites"))


def live_regions(spec: str) -> tuple[set[str], set[str]]:
    regions = fam(spec, "rg")
    every = {r[0] for r in regions}
    live = {r[0] for r in regions if len(r) > 4 and r[4] and not r[4].startswith("none")}
    return every, live


def g_script(ctx: Ctx, vals: dict[str, str], f: Findings) -> None:
    q = q07_rows(ctx.spec)
    every, live = live_regions(ctx.spec)
    if not q:
        f.append(("G06-SCRIPT", "no Q07 row found"))
    for r in q:
        if len(r) < 8:
            f.append(("G06-SCRIPT", f"{r[0]}: {len(r)} cells"))
            continue
        mech = {m.strip() for m in re.split(r"[·;/]", r[4]) if m.strip()}
        if not mech or not mech <= MECHANISMS:
            f.append(("G06-SCRIPT", f"{r[0]}: mechanism {r[4]!r} is not from the vocabulary"))
        hosts = set(RG_ID.findall(r[5]))
        if mech == {"none"}:
            if r[5] != NO_LIVE:
                f.append(("G06-SCRIPT", f"{r[0]}: a `none` row's host must read {NO_LIVE!r}"))
        elif not hosts or not hosts <= every:
            f.append(("G06-SCRIPT", f"{r[0]}: host {r[5]!r} is not a region of §5.1"))
        elif mech & LIVE_MECHANISMS and not hosts & live:
            f.append(("G06-SCRIPT", f"{r[0]}: a live write to {r[5]!r}, which has no live region"))
        if not RATE.match(r[6]):
            f.append(("G06-SCRIPT", f"{r[0]}: rate {r[6]!r} is not from R-2's vocabulary"))
        if not cite_spans(r[7], bare=True):
            f.append(("G06-SCRIPT", f"{r[0]}: no source cite"))
    for r in fam(ctx.spec, "vc"):
        hosts = set(RG_ID.findall(r[4])) if len(r) > 4 else set()
        if not hosts or not hosts <= live:
            f.append(("G06-SCRIPT", f"{r[0]}: host {r[4] if len(r) > 4 else ''!r} is not live"))
    pair = [x for x in fam(ctx.spec, "rg") if x[0] == "RG-04"]
    line = ctx.base_line("E17-D02", 249) or ""
    if not pair or "`E17-D02`:249" not in pair[0][-1] or "live-region pair" not in line:
        f.append(("G06-SCRIPT", "RG-04 is not E17-D02's shell live-region pair"))


def g_budget(ctx: Ctx, vals: dict[str, str], f: Findings) -> None:
    for r in fam(ctx.spec, "bg"):
        if len(r) < 7:
            f.append(("G07-BUDGET", f"{r[0]}: {len(r)} cells"))
            continue
        if not RATE.match(r[3]):
            f.append(("G07-BUDGET", f"{r[0]}: max_rate {r[3]!r} is not an enforceable rate"))
        if not r[4] or not r[6]:
            f.append(("G07-BUDGET", f"{r[0]}: no object or no source"))


def g_findings(ctx: Ctx, vals: dict[str, str], f: Findings) -> None:
    sec = section(ctx.spec, "14. ")
    fr = rows(sec, "F")
    for r in fr:
        if len(r) < 11:
            f.append(("G08-FINDINGS", f"{r[0]}: {len(r)} cells"))
            continue
        if r[1] not in SEVERITIES:
            f.append(("G08-FINDINGS", f"{r[0]}: severity {r[1]!r}"))
        for i, what in ((2, "merged sentence"), (3, "replacement"), (4, "reason"), (6, "target")):
            if not r[i]:
                f.append(("G08-FINDINGS", f"{r[0]}: the {what} cell is empty"))
        if not OWNER.match(r[5]):
            f.append(("G08-FINDINGS", f"{r[0]}: the owner is not one spec and its area"))
        if not G_T2.match(r[7]):
            f.append(("G08-FINDINGS", f"{r[0]}: G-T2 {r[7]!r} is not from the set"))
        if not FOCUS.match(r[8]):
            f.append(("G08-FINDINGS", f"{r[0]}: Focus {r[8]!r} is not from the set"))
        if r[9] != "n/a" and not RATE.match(r[9]):
            f.append(("G08-FINDINGS", f"{r[0]}: Rate {r[9]!r} is not from the set"))
        if not r[10]:
            f.append(("G08-FINDINGS", f"{r[0]}: the Assertion cell is empty"))
    blocking = any(len(r) > 1 and r[1] == "Blocking" for r in fr)
    armed = "cannot be Done until fixed" in sec and "**not armed**" not in sec
    if blocking != armed:
        f.append(("G08-FINDINGS", "the hold sentence does not match the Blocking rows"))


def g_ids(ctx: Ctx, vals: dict[str, str], f: Findings) -> None:
    for key, (_, family) in FAMILIES.items():
        ids = [r[0] for r in fam(ctx.spec, key)]
        if family == "C":
            if not ids or len(ids) != len(set(ids)):
                f.append(("G09-IDS", "C: the ids repeat or are missing"))
            continue
        nums = [int(i.rsplit("-", 1)[1]) for i in ids]
        if not ids or nums != list(range(1, len(ids) + 1)):
            f.append(("G09-IDS", f"{family}: the ids are not 1..n in order ({ids[:4]}…)"))
    q = [int(r[0][4:]) for r in q07_rows(ctx.spec)]
    if any(b <= a for a, b in itertools.pairwise(q)):
        f.append(("G09-IDS", "a Q07 id repeats or is out of order"))


def g_hygiene(ctx: Ctx, vals: dict[str, str], f: Findings) -> None:
    for name, text in (("the spec", ctx.spec), ("the tool", ctx.tool), ("the pins", ctx.pins)):
        low = text.lower()
        for word in BANNED:
            if word in low:
                f.append(("G10-HYGIENE", f"{name}: a word from the private list"))
        for pat, what in ((URL, "a URL"), (UUID, "a uuid"), (LOCAL_PATH, "a local path")):
            m = pat.search(text)
            if m:
                f.append(("G10-HYGIENE", f"{name}: {what} {m[0][:24]!r}"))
    m = COLOUR_HEX.search(ctx.spec)
    if m:
        f.append(("G10-HYGIENE", f"the spec: a colour hex {m[0]!r}"))
    if CLOSING.search(ctx.spec):
        f.append(("G10-HYGIENE", "the spec carries a closing keyword before an issue number"))


def g_scope_words(ctx: Ctx, vals: dict[str, str], f: Findings) -> None:
    for r in q07_rows(ctx.spec):
        for hit in scope_hits(r[3]) if len(r) > 3 else []:
            f.append(("G11-SCOPE", f"{r[0]}: {hit!r} is outside the active context"))


def g_ruled(ctx: Ctx, vals: dict[str, str], f: Findings) -> None:
    sec = section(ctx.spec, "R. ")
    listed = [r[0] for r in rows(sec, "BQ")]
    if listed != [f"BQ-{n:02d}" for n in range(1, BQ_COUNT + 1)]:
        f.append(("G12-RULED", f"section R lists {len(listed)} BQ rows, not BQ-01..BQ-{BQ_COUNT}"))
    for r in rows(sec, "BQ"):
        if r[-1] != RULED_STAMP:
            f.append(("G12-RULED", f"{r[0]}: the status is not the ruling stamp"))
    for m in re.finditer(r"RULED (BQ-\d\d)((?:, BQ-\d\d)*)", ctx.spec):
        for bq in [m[1], *re.findall(r"BQ-\d\d", m[2])]:
            if bq not in listed:
                f.append(("G12-RULED", f"a stamp names {bq}, which section R does not list"))


def g_scope(ctx: Ctx, vals: dict[str, str], f: Findings) -> None:
    for p in ctx.changed:
        if p not in OWN and p != P14_REL:
            f.append(("G13-SCOPE", f"{p} is outside the edit set"))


def g_pointers(ctx: Ctx, vals: dict[str, str], f: Findings) -> None:
    base = ctx.p14_base.split("\n")
    wt = ctx.p14.split("\n")
    added = [ln for ln in wt if ln not in set(base)]
    removed = [ln for ln in base if ln not in set(wt)]
    if removed:
        f.append(("G14-POINTERS", f"{len(removed)} line(s) of `14` removed or changed"))
    if ctx.merged_spec is None and len(added) != len(POINTER_ENTRIES):
        f.append(("G14-POINTERS", f"{len(added)} line(s) added to `14`, not three"))
    for ln in added:
        if not ln.startswith(POINTER_HEAD):
            f.append(("G14-POINTERS", f"an added `14` line is not a pointer line: {ln[:40]!r}"))
    entry = ""
    found: set[str] = set()
    for ln in wt:
        m = re.match(r"### (SCR-\d+) ", ln)
        if m:
            entry = m[1]
        elif ln.startswith("## "):
            entry = ""
        if POINTER_MARK in ln:
            if entry not in POINTER_ENTRIES:
                f.append(("G14-POINTERS", f"a pointer line sits in {entry or 'no entry'}"))
            found.add(entry)
    for e in POINTER_ENTRIES:
        if e not in found:
            f.append(("G14-POINTERS", f"{e} has no pointer line"))


# v1.1 (#5245): the rows the orchestrator's approval of record 6549312022 carried as Minors.
V11_ROWS = frozenset({"T2-02", "T2-03", "T2-04", "T2-05", "T2-07", "C-p"})


def _row_id(ln: str) -> str:
    return ln.split("|")[1].strip() if ln.count("|") > 2 else ""


def _cells(ln: str) -> str:
    return re.sub(r" +", " ", ln.strip())


def g_freeze(ctx: Ctx, vals: dict[str, str], f: Findings) -> None:
    if ctx.merged_spec is None:
        return
    lines = ctx.spec.split("\n")
    now = {_cells(ln) for ln in lines}
    ids = {_row_id(ln) for ln in lines}
    for ln in ctx.merged_spec.split("\n"):
        if not ln.startswith("|") or ln.startswith("| ---") or _cells(ln) in now:
            continue
        if _row_id(ln) in V11_ROWS and _row_id(ln) in ids:
            continue
        f.append(("G15-FREEZE", f"a merged row changed: {ln[:48]!r}"))


def g_contrast(ctx: Ctx, vals: dict[str, str], f: Findings) -> None:
    if not ctx.union:
        f.append(("G16-CONTRAST", "no pair could be measured"))
    for _tag, fg, bg, bar, ratios in ctx.union:
        if bar not in BAR:
            continue
        if not ratios:
            f.append(("G16-CONTRAST", f"{fg} on {bg}: no ratio in any theme"))
        for theme, r in ratios.items():
            if r < BAR[bar]:
                f.append(("G16-CONTRAST", f"{fg} on {bg} ({theme}): {r:.2f}:1 under {BAR[bar]}"))
    # the method sentence states what ran: the port's tritan is the Machado matrix
    port = engine("e12_d06_series_audit")
    method = section(ctx.spec, "13.4 ")
    ran = port.LINEAR_RGB_SIMS.get("tritanopia") is port.TRITAN_MACHADO
    for need in ("Brettel (1997) / Viénot", "Machado, Oliveira and Fernandes 2009", "is not used"):
        if not ran or need not in method:
            f.append(("G16-CONTRAST", f"§13.4 does not state what ran ({need!r})"))
    if vals.get("hink-both-low", "0") != "0":
        f.append(("G16-CONTRAST", "a candle ink defeats both tones of the handle"))


def g_sim(ctx: Ctx, vals: dict[str, str], f: Findings) -> None:
    sim = simulate(ctx.combined_rule)
    if sim["max"] > 2:
        f.append(("G17-BUDGET-SIM", f"{sim['max']} writes in one second"))
    if sim["dropped_non4"]:
        f.append(("G17-BUDGET-SIM", f"{sim['dropped_non4']} non-value write(s) dropped"))
    if not sim["flush_kept"] or sim["class2_spoken"] != sim["class2_total"]:
        f.append(("G17-BUDGET-SIM", "the trailing flush or a confirmation was lost"))


def g_keymap(ctx: Ctx, vals: dict[str, str], f: Findings) -> None:
    km = json.loads(show(ctx.base, KM_REL) or "{}")
    if not km.get("commands"):
        f.append(("G18-KEYMAP", "the key map could not be read at the base"))
        return
    ids = {c["id"] for c in km["commands"]}
    bound = {
        str(c["defaultBinding"]).replace(" ", "")
        for c in km["commands"]
        if c["context"] in ("Chart", "Global")
    }
    for r in fam(ctx.spec, "kb"):
        status = r[4] if len(r) > 4 else ""
        for cid in re.findall(r"`((?:chart|global)\.[\w.]+)`", status):
            if cid not in ids:
                f.append(("G18-KEYMAP", f"{r[0]}: {cid} is not a command of the key map"))
        if "not in `KM`" in status:
            for key in re.findall(r"`([^`]+)`", r[2]):
                if key.replace(" ", "") in bound:
                    f.append(("G18-KEYMAP", f"{r[0]}: {key} is bound in the key map"))


def g_walk(ctx: Ctx, vals: dict[str, str], f: Findings) -> None:
    kw = {r[1].strip("`"): r for r in fam(ctx.spec, "kw") if len(r) >= 9}
    expected: dict[str, tuple[str, str, str]] = {}
    for r in d02().REG:
        tool = str(r[2]) if r[2] != "-" else str(r[0])
        if r[2] == "-" and r[0] != "emoji_marker":
            continue
        deferred = str(r[7]).startswith("deferred")
        anchors = str(r[3]) if r[3] != "-" else "—"
        key = str(r[5])
        arming = "—" if deferred else (f"`{key}`" if key.startswith(("Alt+", "Ctrl+")) else "")
        arming = arming or "rail / palette"
        chain = DEFERRED_CHAIN if deferred else CHAINS.get(anchors, "?")
        expected[tool] = (anchors, arming, chain)
    for tool, (anchors, arming, chain) in expected.items():
        row = kw.get(tool)
        if row is None:
            f.append(("G19-WALK", f"the registry's {tool} has no KW row"))
            continue
        if row[2] != anchors:
            f.append(("G19-WALK", f"{row[0]}: anchors {row[2]!r}, the registry says {anchors!r}"))
        if row[3] != arming:
            f.append(("G19-WALK", f"{row[0]}: arming {row[3]!r}, the registry says {arming!r}"))
        if row[4] != chain:
            f.append(("G19-WALK", f"{row[0]}: chain {row[4]!r}, the machine gives {chain!r}"))
    for tool in kw:
        if tool not in expected:
            f.append(("G19-WALK", f"the KW row for {tool} has no registry row"))


def g_vocab(ctx: Ctx, vals: dict[str, str], f: Findings) -> None:
    if not fam(ctx.spec, "vc"):
        f.append(("G20-VOCAB", "no VC row found"))
    for rid, s, n in vc_words(ctx.spec):
        if n > 10:
            f.append(("G20-VOCAB", f"{rid}: {n} words in {s[:40]!r}"))


def g_parity(ctx: Ctx, vals: dict[str, str], f: Findings) -> None:
    d07 = d07_parity(ctx.base)
    pa = fam(ctx.spec, "pa")
    if not d07:
        f.append(("G21-PARITY", "D07's parity table could not be read at the base"))
    if len(pa) < len(d07):
        f.append(("G21-PARITY", f"{len(pa)} PA rows for D07's {len(d07)} actions"))
    for r in d07:
        if "gap" in r[-1]:
            f.append(("G21-PARITY", f"D07's {r[0]!r} reads gap"))
    for r in pa:
        if len(r) < 5 or not r[3] or "gap" in r[4]:
            f.append(("G21-PARITY", f"{r[0]}: no tree twin or a gap"))


def g_wcag(ctx: Ctx, vals: dict[str, str], f: Findings) -> None:
    wc = fam(ctx.spec, "wc")
    have = {r[1].split()[0] for r in wc if len(r) > 1 and r[1]}
    for c in CRITERIA:
        if c not in have:
            f.append(("G22-WCAG", f"criterion {c} has no WC row"))
    blocking = any(r[1] == "Blocking" for r in fam(ctx.spec, "f") if len(r) > 1)
    for r in wc:
        if (len(r) < 5 or r[3].strip() in ("", "none", "—")) and not blocking:
            f.append(("G22-WCAG", f"{r[0]}: no proving artefact and no Blocking F row"))


def g_drag(ctx: Ctx, vals: dict[str, str], f: Findings) -> None:
    f_ids = {r[0] for r in fam(ctx.spec, "f")}
    for r in fam(ctx.spec, "dr"):
        if len(r) < 7 or not all(r[1:7]):
            f.append(("G23-DRAG", f"{r[0]}: a cell is empty"))
            continue
        for img in re.findall(r"`([\w.-]+\.png)`", r[5]):
            if img not in ctx.images:
                f.append(("G23-DRAG", f"{r[0]}: {img} does not exist at the base"))
        if "text only" in r[5] and not (set(re.findall(r"F-\d\d", r[6])) & f_ids):
            f.append(("G23-DRAG", f"{r[0]}: drawn in text only and no F row named"))


def g_t2(ctx: Ctx, vals: dict[str, str], f: Findings) -> None:
    sec = section(ctx.spec, "12.1 ")
    for need in ("CMP-079 RbacGate", "CMP-026 with `cta` omitted"):
        if need not in sec:
            f.append(("G24-T2", f"the T2 rule does not say {need!r}"))
    t2 = fam(ctx.spec, "t2")
    if not t2:
        f.append(("G24-T2", "no T2 row found"))
    for r in t2:
        if len(r) < 10:
            f.append(("G24-T2", f"{r[0]}: {len(r)} cells"))
            continue
        keys = set(T2_KEYS.findall(r[3]))
        if not keys:
            f.append(("G24-T2", f"{r[0]}: no §3.1 key or state key"))
        role_leg = "view-as" in r[2] or "permission" in r[2] or r[2].startswith("as T2-")
        if role_leg and not ({"rbac.view_as", "rbac.permission"} <= keys and QUOTE.search(r[3])):
            f.append(("G24-T2", f"{r[0]}: a role leg names both keys and the §3.2 verb"))
        sentence = r[6].startswith("T2 · sentence")
        if sentence and "CMP-026 with `cta` omitted" not in r[4]:
            f.append(("G24-T2", f"{r[0]}: a sentence form names CMP-026 with `cta` omitted"))
        if role_leg and not sentence and "CMP-079" not in r[4]:
            f.append(("G24-T2", f"{r[0]}: a role-gated control names CMP-079 RbacGate"))
        if not T2_RENDER.match(r[6]):
            f.append(("G24-T2", f"{r[0]}: rendering {r[6]!r} is not from the set"))
        if not FOCUS.match(r[7]) or not RATE.match(r[8]):
            f.append(("G24-T2", f"{r[0]}: Focus or Rate is not from its set"))


GATES: list[tuple[str, Callable[[Ctx, dict[str, str], Findings], None]]] = [
    ("G01-FILLED", g_filled),
    ("G02-AUDIT", g_audit),
    ("G03-CITE", g_cite),
    ("G04-PINS", g_pins),
    ("G05-VERBATIM", g_verbatim),
    ("G06-SCRIPT", g_script),
    ("G07-BUDGET", g_budget),
    ("G08-FINDINGS", g_findings),
    ("G09-IDS", g_ids),
    ("G10-HYGIENE", g_hygiene),
    ("G11-SCOPE", g_scope_words),
    ("G12-RULED", g_ruled),
    ("G13-SCOPE", g_scope),
    ("G14-POINTERS", g_pointers),
    ("G15-FREEZE", g_freeze),
    ("G16-CONTRAST", g_contrast),
    ("G17-BUDGET-SIM", g_sim),
    ("G18-KEYMAP", g_keymap),
    ("G19-WALK", g_walk),
    ("G20-VOCAB", g_vocab),
    ("G21-PARITY", g_parity),
    ("G22-WCAG", g_wcag),
    ("G23-DRAG", g_drag),
    ("G24-T2", g_t2),
]


def run(ctx: Ctx) -> tuple[dict[str, str], Findings]:
    f: Findings = []
    try:
        vals = compute(ctx)
    except RUN_ERRORS as e:  # default-deny: an unreadable input is a FAIL
        return {}, [("G02-AUDIT", f"the numbers could not be computed: {type(e).__name__}: {e}")]
    for code, gate in GATES:
        try:
            gate(ctx, vals, f)
        except RUN_ERRORS as e:
            f.append((code, f"the gate could not run: {type(e).__name__}: {e}"))
    return vals, f


# ---------------------------------------------------------------------------------- writers


def fill(ctx: Ctx) -> str:
    vals = compute(ctx)

    def slot(m: re.Match[str]) -> str:
        key = m[2]
        if key not in vals:
            return m[0]
        value = f"`{vals[key]}`" if m[1] == "SHA" else vals[key]
        return f"{value} <!-- audit:{key}={vals[key]} -->"

    spec = SLOT.sub(slot, ctx.spec)
    out = []
    for ln in spec.split("\n"):
        for m in list(AUDIT.finditer(ln)):
            key, old = m[1], m[2]
            if key in vals and old != vals[key]:
                new = vals[key]
                for tick in ("", "`"):
                    ln = ln.replace(
                        f"{old}{tick} <!-- audit:{key}={old} -->",
                        f"{new}{tick} <!-- audit:{key}={new} -->",
                    )
        out.append(ln)
    return "\n".join(out)


def repin(ctx: Ctx) -> str:
    lines = [
        "# E14-D10 pins: one cited endpoint per line, `KEY:line sha1-16` of its words at the base.",
        "# Written only by `e14_d10_a11y_review_audit.py --repin-ruled`.",
    ]
    for key, n in sorted(endpoints(ctx.spec), key=lambda x: (x[0], x[1])):
        line = ctx.base_line(key, n) or ""
        lines.append(f"{key}:{n} {line_hash(line)}")
    return "\n".join(lines) + "\n"


# -------------------------------------------------------------------------------- self-test


def _swap(text: str, old: str, new: str) -> str:
    if old not in text:
        raise ValueError(f"mutation anchor missing: {old[:40]!r}")
    return text.replace(old, new, 1)


def set_cell(text: str, row_id: str, index: int, value: str) -> str:
    out = []
    done = False
    for ln in text.split("\n"):
        if not done and re.match(rf"^\s*\|\s*{re.escape(row_id)}\s*\|", ln):
            parts = ln.split("|")
            parts[index + 1] = f" {value} "
            ln = "|".join(parts)
            done = True
        out.append(ln)
    if not done:
        raise ValueError(f"mutation anchor missing: row {row_id}")
    return "\n".join(out)


def first(pattern: str, text: str) -> str:
    m = re.search(pattern, text, re.MULTILINE)
    if not m:
        raise ValueError(f"mutation anchor missing: {pattern}")
    return m[0]


def _spec(c: Ctx, text: str) -> Ctx:
    return dataclasses.replace(c, spec=text)


MUTATIONS: list[tuple[str, Callable[[Ctx], Ctx]]] = [
    ("G01-FILLED", lambda c: _spec(c, c.spec + "\n{{COUNT:kb}}\n")),
    (
        "G02-AUDIT",
        lambda c: _spec(
            c, _swap(c.spec, first(r"<!-- audit:kb=\d+ -->", c.spec), "<!-- audit:kb=999 -->")
        ),
    ),
    (
        "G03-CITE",
        lambda c: dataclasses.replace(
            c,
            pins=re.sub(
                r"^(D02:\d+) [0-9a-f]{16}$",
                r"\1 0000000000000000",
                c.pins,
                count=1,
                flags=re.MULTILINE,
            ),
        ),
    ),
    ("G04-PINS", lambda c: _spec(c, c.spec + "\nSee `D03`:5.\n")),
    (
        "G05-VERBATIM",
        lambda c: _spec(c, _swap(c.spec, '"Anchor 1 removed."', '"Anchor one removed."')),
    ),
    ("G06-SCRIPT", lambda c: _spec(c, set_cell(c.spec, "Q07-01", 4, "shouted"))),
    ("G07-BUDGET", lambda c: _spec(c, set_cell(c.spec, "BG-01", 3, "n/a"))),
    ("G08-FINDINGS", lambda c: _spec(c, set_cell(c.spec, "F-05", 1, "Severe"))),
    ("G09-IDS", lambda c: _spec(c, _swap(c.spec, "| KB-03 |", "| KB-02 |"))),
    ("G10-HYGIENE", lambda c: _spec(c, c.spec + "\n" + BANNED[6].upper() + "\n")),
    (
        "G11-SCOPE",
        lambda c: _spec(
            c, set_cell(c.spec, "Q07-98", 3, '"Send to ticket — Sized for Alex · LIVE"')
        ),
    ),
    ("G12-RULED", lambda c: _spec(c, _swap(c.spec, f"| {RULED_STAMP} |", "| pending |"))),
    ("G13-SCOPE", lambda c: dataclasses.replace(c, changed=[*c.changed, "docs/plan/15-x.md"])),
    (
        "G14-POINTERS",
        lambda c: dataclasses.replace(
            c, p14="\n".join(ln for ln in c.p14.split("\n") if "the drawing entry only" not in ln)
        ),
    ),
    (
        "G15-FREEZE",
        lambda c: dataclasses.replace(c, merged_spec="| KB-99 | a merged row since changed |\n"),
    ),
    (
        "G16-CONTRAST",
        lambda c: dataclasses.replace(
            c, union=[*c.union, ("union", "x", "y", "TEXT", {"dark": 2.1})]
        ),
    ),
    ("G17-BUDGET-SIM", lambda c: dataclasses.replace(c, combined_rule=False)),
    (
        "G18-KEYMAP",
        lambda c: _spec(
            c, _swap(c.spec, "shipped (`global.region_cycle`)", "shipped (`global.no_such_id`)")
        ),
    ),
    ("G19-WALK", lambda c: _spec(c, set_cell(c.spec, "KW-08", 2, "2"))),
    (
        "G20-VOCAB",
        lambda c: _spec(
            c,
            set_cell(
                c.spec,
                "VC-33",
                2,
                '"Cloned and selected, one two three four five six seven eight."',
            ),
        ),
    ),
    ("G21-PARITY", lambda c: _spec(c, set_cell(c.spec, "PA-05", 4, "gap"))),
    ("G22-WCAG", lambda c: _spec(c, set_cell(c.spec, "WC-08", 3, "none"))),
    ("G23-DRAG", lambda c: _spec(c, set_cell(c.spec, "DR-05", 6, "at risk"))),
    ("G24-T2", lambda c: _spec(c, set_cell(c.spec, "T2-03", 3, "the one notice"))),
    # the lens round's escaped mutations, each caught by a content gate
    ("G06-SCRIPT", lambda c: _spec(c, set_cell(c.spec, "Q07-05", 6, "whenever"))),
    (
        "G05-VERBATIM",
        lambda c: _spec(
            c, set_cell(c.spec, "Q07-05", 3, "the anchor's place, in words of its own")
        ),
    ),
    (
        "G05-VERBATIM",
        lambda c: _spec(
            c, set_cell(c.spec, "Q07-01", 3, '"Pencil" · "toggle button, not pressed"')
        ),
    ),
    ("G06-SCRIPT", lambda c: _spec(c, set_cell(c.spec, "Q07-05", 5, "RG-05"))),
    ("G06-SCRIPT", lambda c: _spec(c, set_cell(c.spec, "Q07-33", 5, "RG-09"))),
    ("G06-SCRIPT", lambda c: _spec(c, set_cell(c.spec, "VC-01", 4, "RG-05"))),
    ("G08-FINDINGS", lambda c: _spec(c, set_cell(c.spec, "F-03", 9, "sometimes"))),
    ("G08-FINDINGS", lambda c: _spec(c, set_cell(c.spec, "F-03", 5, "the lane · area/zzz"))),
    (
        "G08-FINDINGS",
        lambda c: _spec(
            c,
            set_cell(
                set_cell(
                    set_cell(set_cell(c.spec, "F-13", 5, "whoever"), "F-13", 7, "bogus"),
                    "F-13",
                    8,
                    "bogus",
                ),
                "F-13",
                9,
                "bogus",
            ),
        ),
    ),
    ("G08-FINDINGS", lambda c: _spec(c, set_cell(c.spec, "F-03", 1, "Blocking"))),
    ("G08-FINDINGS", lambda c: _spec(c, set_cell(c.spec, "F-04", 4, ""))),
    (
        "G05-VERBATIM",
        lambda c: _spec(
            c, set_cell(c.spec, "RG-07", 3, 'the description "Page keys move items. Arrows nudge."')
        ),
    ),
    (
        "G16-CONTRAST",
        lambda c: _spec(c, _swap(c.spec, "Machado, Oliveira and Fernandes 2009", "the research")),
    ),
    (
        "G02-AUDIT",
        lambda c: _spec(
            c,
            re.sub(
                r"(\d+) <!-- audit:carriers=(\d+) -->",
                lambda m: f"{int(m[1]) + 1} <!-- audit:carriers={int(m[2]) + 1} -->",
                c.spec,
                count=1,
            ),
        ),
    ),
]


def self_test(ctx: Ctx) -> tuple[int, int, list[str]]:
    _, base = run(ctx)
    problems: list[str] = []
    if base:
        problems.append(f"the base run is not clean: {len(base)} FAIL(s)")
    before = {code for code, _ in base}
    passed = 0
    for code, mutate in MUTATIONS:
        try:
            _, got = run(mutate(ctx))
        except RUN_ERRORS as e:
            problems.append(f"{code}: the mutation could not apply: {e}")
            continue
        if any(c == code for c, _ in got) and code not in before:
            passed += 1
        else:
            problems.append(f"{code}: the mutation added no FAIL of its gate")
    gates = {code for code, _ in GATES}
    if gates - {code for code, _ in MUTATIONS}:
        problems.append("a gate has no mutation")
    return passed, len(MUTATIONS), problems


# ------------------------------------------------------------------------------------- main


def main(argv: list[str]) -> int:
    ap = argparse.ArgumentParser(description=(__doc__ or "").splitlines()[0])
    ap.add_argument("--check", action="store_true", help="exit 1 on any FAIL (a bare run does too)")
    ap.add_argument("--json", action="store_true", help="print the numbers and findings as JSON")
    ap.add_argument("--fill", action="store_true", help="write the computed values into the spec")
    ap.add_argument("--self-test", action="store_true", help="the mutation self-test")
    ap.add_argument("--repin-ruled", action="store_true", help="rewrite the pins file")
    args = ap.parse_args(argv)
    ctx = build_ctx()
    mode = "post-merge" if ctx.merged_spec is not None else "PR-1"
    if args.repin_ruled:
        (ROOT / PINS_REL).write_text(repin(ctx), encoding="utf-8")
        print(f"pins rewritten: {len(endpoints(ctx.spec))} cited endpoints")
        return 0
    if args.fill:
        (ROOT / SPEC_REL).write_text(fill(ctx), encoding="utf-8")
        print("spec filled")
        return 0
    if args.self_test:
        passed, total, problems = self_test(ctx)
        for p in problems:
            print(f"SELF-TEST FAIL {p}")
        print(f"self-test: {passed}/{total} mutations caught; {len(GATES)} gates; mode {mode}")
        return 0 if passed == total and not problems else 1
    vals, f = run(ctx)
    if args.json:
        print(
            json.dumps({"mode": mode, "base": ctx.base, "numbers": vals, "findings": f}, indent=2)
        )
    else:
        for code, msg in f:
            print(f"FAIL [{code}] {msg}")
        print(f"mode {mode}; base {ctx.base[:12]}; {len(GATES)} gates; FAIL {len(f)} / WARN 0")
    return 1 if f else 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
