"""E12-D11 (#312) audit: the accessibility design review of the E12 bar and series band.

Stdlib only, offline (`python3 -I -B`). It reads the spec, the pins file and `14` from the working
tree, and every cited file AS TEXT at the merge-base with `origin/main` (`git show`). It imports,
never copies: the E11-D07 key-map engine (`load_keymap`, `shipped_bindings`), the six E12 parent
audits' pair lists and ratio functions (E12-D03 `PAIRS` / `ratio` / `col`; E12-D04 and E12-D05
`PAIRS` / `contrast_grid`; E12-D06 `contrast_grid`, `inks`, `simulate`, `lab`, `delta_e76`;
E12-D07 `CONTRAST_PAIRS` / `contrast_values` / `hex_of`; E12-D08 `contrast_rows` / `compute`),
and `calendar_cv.sprint_range`. Default-deny: a gate that cannot read its input FAILs.

Two modes, chosen by content, never by branch name. PR-1 mode: the spec is absent at the
merge-base; the diff may touch only the three own files and add the six `14` pointer lines.
Post-merge mode: the spec ships at the merge-base; every merged table row stands unchanged and
only later rows, the own files and the merged pointer lines may move; every cite is read at the
base the merged spec recorded (`audit:sha`), not at the merge-base with the moving main.

Gates (each FAIL led by its code):

- [G01-FILLED] no `{{KIND:key}}` slot is left in the spec.
- [G02-AUDIT] every `<!-- audit:key=value -->` marker is a known key, equals the recomputed value
  and stands right after its visible value.
- [G03-CITE] every cited endpoint resolves at the base to a non-blank line, and its pin matches.
- [G04-PINS] the pins file and the spec's cited endpoints match both ways.
- [G05-VERBATIM] every quoted string of ten characters or more in a Q07 row stands, slots aside,
  on or beside a line the row cites.
- [G06-SCRIPT] every Q07 row has a mechanism from the vocabulary, a host, a rate and a source.
- [G07-BUDGET] every BG row has a `max_rate` (never `n/a`), an object and a source.
- [G08-FINDINGS] every F row has a severity from the scale, an owner, a target and the `G-T2`,
  `Focus` and `Rate` cells; no Blocking row stands while the hold sentence says "not armed".
- [G09-IDS] the ids of each table family are unique and in order.
- [G10-HYGIENE] no lane-private word, URL, local path, uuid or closing keyword in the spec, the
  tool or the pins.
- [G11-ACCOUNT] no Q07 row carries position, order-book, balance or account words.
- [G12-RULED] section R lists BQ-01..BQ-22 once each with the ruling stamp; no BQ marker is left;
  every "RULED BQ-nn" stamp names a listed BQ.
- [G13-SCOPE] the changed paths are the own files and `14` only.
- [G14-POINTERS] `14` differs from the base by exactly the six pointer lines, each inside its entry.
- [G15-FREEZE] post-merge mode: every merged table row stands unchanged.
- [G16-CONTRAST] the union of the parents' gated pairs has no pair under its floor.
- [G17-BUDGET-SIM] the 60 s worst case keeps at most two writes in any second and drops only
  class-4 text.
- [G18-KEYMAP] a KB row's shipped ids exist in the key map; a key a row says is not in the key map
  is bound by no command of the Chart or Global context.
- [G19-T2] section 9.1 states CMP-079's wrap and the CMP-026 sentence form; every T2 row
  names its section 3.1 key, a section 3.2 verb where the key takes one, and its component.

`--json` prints the numbers and findings; `--check` exits 1 on any FAIL; `--fill` writes the
computed values into the spec's slots and markers; `--self-test` applies one mutation per gate to
an in-memory copy and passes only when each adds FAILs of its gate's code and the base run is
clean; `--repin-ruled` rewrites the pins file from the spec's cites and is its only writer.

Usage: python3 -I -B docs/design/_tools/e12_d11_a11y_review_audit.py [--check] [--json] [--fill]
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
SPEC_REL = "docs/design/E12/E12-D11.md"
TOOL_REL = "docs/design/_tools/e12_d11_a11y_review_audit.py"
PINS_REL = "docs/design/_tools/e12_d11_ruled_pins.txt"
P14_REL = "docs/plan/14-screens-catalogue.md"
OWN = {SPEC_REL, TOOL_REL, PINS_REL}
UPSTREAM = "origin/main"
BQ_BASE = "f573fcee2f40d384a0b725187c2984b0af9a0a0d"  # where the BQ list read every cite
RULED_STAMP = "RULED (orchestrator, 2026-10-31, #312 ruling of record — 6545803468's answer)"
POINTER_MARK = "**A11y review (E12-D11):**"
POINTER_ENTRIES = ("SCR-030", "SCR-031", "SCR-042", "SCR-045", "SCR-047", "SCR-048")
IMG_DIR = "docs/design/E12/img"
KM_REL = "apps/web/src/keymap/keymap.json"
SRK_REL = "docs/design/_tools/e11_d07_sr_reserved_keys.json"
CAL_REL = "docs/plan/backlog/_tools/calendar_cv.py"
D07_REL = "docs/design/E12/E12-D07.md"
D08_REL = "docs/design/E12/E12-D08.md"

DESIGN_KEYS = {f"D0{n}": f"docs/design/E12/E12-D0{n}.md" for n in range(2, 10)}
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
ITALIC_QUOTE = re.compile(r'\*"[^"]*"\*')

MECHANISMS = {"name", "role", "desc", "polite", "cell", "none", "text"}
RATE_UNITS = (
    "episode|entry|exit|change|press|action|key-down|release|focus entry|focus|group entry|open"
    "|menu open|commit|switch|build|rebuild|return|arrival|amended bar|bar|Enter|key"
)
RATE = re.compile(
    rf"^(?:never|on demand|once per (?:{RATE_UNITS})\b"
    rf"|≤ \d+ per \d+ s (?:per (?:{RATE_UNITS}|region)\b|across RG-\d\d))"
)
G_T2 = re.compile(r"^(?:n/a|T2 · (?:2a|2b|sentence)|validity|availability)$")
FOCUS = re.compile(r"^(?:n/a|(?:kept|moves to|restored to|returns to) · \S.*)$")
OWNER = re.compile(r"^`E\d\d-D\d\d · area/[a-z-]+`$")
HOST = re.compile(r"^(RG-\d\d)\b")
NOTHING = "nothing is announced"
CLOSE_MS = 1000  # §7.4: a bar close every second
CLASS2 = ((10_000, "start"), (30_000, "overrun"), (45_000, "cancel"))
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
CLOSING = re.compile(r"\b(?:close[sd]?|fix(?:e[sd])?|resolve[sd]?) #\d+", re.IGNORECASE)
ACCOUNT_WORDS = re.compile(r"\b(?:position|positions|balance|balances|account|accounts|PnL|P&L)\b")

THRESHOLD = {"text": 4.5, "mark": 3.0}
GREY_WEIGHTS = (0.299, 0.587, 0.114)  # Rec. 601 luma, kept here as E08-D12 keeps it
CARRIER_PAIRS: dict[str, tuple[str, str]] = {
    "direction": ("ink:candle.up", "ink:candle.down"),
    "forming": ("ink:candle.wick", "ink:surface.canvas"),
    "corrected": ("ink:candle.wick", "ink:surface.canvas"),
    "boundary": ("color.text.tertiary", "color.surface.canvas"),
    "gap": ("color.text.secondary", "color.surface.canvas"),
    "strip": ("color.text.primary", "color.surface.raised"),
    "t2": ("color.text.tertiary", "color.text.primary"),
    "warn": ("color.status.warning.strong", "color.text.secondary"),
}
CONSUMER_SPRINTS = {"s06": 6, "s07": 7, "s08": 8, "s09": 9}


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


def table_body(block: str) -> list[str]:
    """The body rows of the first table in a block: every row after its separator line."""
    lines = [ln for ln in block.split("\n") if ln.startswith("|")]
    for i, ln in enumerate(lines):
        if re.match(r"^\|\s*:?-{3,}", ln):
            return lines[i + 1 :]
    return []


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


# ------------------------------------------------------------------------------------ context


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
    contrast: list[tuple[str, str, str, float, str]]  # parent, pair, theme, ratio, role
    combined_rule: bool = True

    def base_line(self, key: str, n: int) -> str | None:
        rel = key_path(key, self.base)
        text = show(self.base, rel) if rel else None
        if text is None:
            return None
        lines = text.split("\n")
        return lines[n - 1] if 0 < n <= len(lines) else None


def load_contrast(base: str) -> list[tuple[str, str, str, float, str]]:
    out: list[tuple[str, str, str, float, str]] = []
    d03 = engine("e12_d03_menu_audit")
    for _el, fg, bgs, role in d03.PAIRS:
        for bg in bgs:
            for th in d03.T:
                kind = {"text": "text", "non-text": "mark"}.get(role)
                if role == "hc-text" and th == "high-contrast":
                    kind = "text"
                if role == "light-text" and th == "light":
                    kind = "text"
                if kind is None:
                    continue
                r = float(d03.ratio(d03.col(th, fg), d03.col(th, bg)))
                out.append(("D03", f"{fg.removeprefix('CR:')} on {bg}", th, r, kind))
    for tag, name in (("D04", "e12_d04_switcher_audit"), ("D05", "e12_d05_settings_audit")):
        mod = engine(name)
        grid = mod.contrast_grid()
        for th, row in grid.items():
            for key, r in row.items():
                fg, bg, kind = mod.PAIRS[key]
                k = "text" if kind == "text" else "mark" if kind in ("mark", "non-text") else ""
                if k:
                    out.append((tag, f"{fg} on {bg}", str(th), float(r), k))
    d06 = engine("e12_d06_series_audit")
    d06_kind = {"axis-text": "text", "outline-on-tint": ""}
    for th, row in d06.contrast_grid().items():
        for key, r in row.items():
            k = d06_kind.get(key, "mark")
            if k:
                out.append(("D06", f"{key} on canvas", str(th), float(r), k))
    d07 = engine("e12_d07_datatable_audit")
    vals = d07.contrast_values()
    for key, (fg, bg, role) in d07.CONTRAST_PAIRS.items():
        for th in d07.THEMES:
            r = float(vals[f"CONTRAST:{key}.{th}"])
            out.append(("D07", f"{fg} on {bg}", str(th), r, "text" if role == "text" else "mark"))
    d08 = engine("e12_d08_audit")
    d08_spec = show(base, D08_REL) or ""
    dvals = d08.compute(d08_spec, d08.Env(handoff=None))
    for r8 in d08.contrast_rows(d08_spec):
        if len(r8) < 4:
            continue
        for th in d08.THEMES:
            v = dvals.get(f"CONTRAST:{r8[0]}.{th}")
            if v is None:
                continue
            k = "text" if r8[3] == "text" else "mark"
            out.append(("D08", f"{r8[1]} on {r8[2]}".replace("`", ""), str(th), float(v), k))
    return out


def frozen_base(merged_spec: str | None, mb: str) -> str:
    """PR-1: the merge-base. Post-merge: the base the merged spec recorded in its own
    `audit:sha` marker (the base its pins were read at), never the merge commit or moving main.
    Falls back to the merge-base when the marker is missing or does not resolve (G02 then FAILs).
    """
    if merged_spec is None:
        return mb
    for m in AUDIT.finditer(merged_spec):
        if m[1] == "sha" and re.fullmatch(r"[0-9a-f]{40}", m[2]):
            probe = subprocess.run(
                ["git", "cat-file", "-e", m[2] + "^{commit}"],
                cwd=ROOT,
                check=False,
                stderr=subprocess.DEVNULL,
                timeout=60,
            )
            if probe.returncode == 0:
                return m[2]
    return mb


def build_ctx(with_contrast: bool = True) -> Ctx:
    mb = merge_base()
    merged_spec = show(mb, SPEC_REL)
    base = frozen_base(merged_spec, mb)
    changed = sorted(
        {
            *git("diff", "--name-only", mb).split(),
            *git("ls-files", "-o", "--exclude-standard").split(),
        }
    )
    date_s = git("show", "-s", "--format=%cs", base).strip() or "1970-01-01"
    return Ctx(
        spec=read(SPEC_REL),
        pins=read(PINS_REL),
        tool=read(TOOL_REL),
        p14=read(P14_REL),
        p14_base=show(mb, P14_REL) or "",  # this branch's own `14` edits, in both modes
        changed=changed,
        merged_spec=merged_spec,
        base=base,
        base_date=datetime.date.fromisoformat(date_s),
        contrast=load_contrast(base) if with_contrast else [],
    )


# ------------------------------------------------------------------------------- the numbers


def simulate(combined: bool) -> dict[str, int]:
    """§7.4: 60 s, a held cursor key, a 1 s close (silent), a build and an LOD episode."""
    cand: dict[int, list[tuple[int, str]]] = {}
    for t in range(0, 60_000, 500):  # the repeat window carries the latest state
        cand.setdefault(t, []).append((4, "cursor"))
    cand.setdefault(60_100, []).append((4, "flush"))  # trailingFlush ≤ 250 ms after release
    for t, what in CLASS2:
        cand.setdefault(t, []).append((2, what))
    for t, what in ((20_000, "lod-in"), (40_000, "lod-out")):
        cand.setdefault(t, []).append((3, what))
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
        window = sum(1 for s in spoken if t - 1000 < s[0] <= t)
        pending.sort()
        head = pending[0]
        if combined and window >= 2:
            continue
        if combined and head[0] == 2 and t - last2 < 500:
            continue
        if not combined:
            for p in pending:
                spoken.append((t, p[0], p[1]))
            pending.clear()
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
        "class2_total": len(CLASS2),
        "flush_kept": int(any(s[2] == "flush" for s in spoken)),
    }


def hexes(token: str, theme: str = "dark") -> str:
    if token.startswith("ink:"):
        return str(engine("e12_d06_series_audit").inks(theme)[token[4:]])
    return str(engine("e12_d07_datatable_audit").hex_of(theme, token))


def grey_l(hex6: str) -> float:
    h = hex6.lstrip("#")
    r, g, b = (int(h[i : i + 2], 16) for i in (0, 2, 4))
    y = round(GREY_WEIGHTS[0] * r + GREY_WEIGHTS[1] * g + GREY_WEIGHTS[2] * b)
    lab = engine("e12_d06_series_audit").lab(f"#{y:02X}{y:02X}{y:02X}")
    return float(lab[0])


def carrier_values() -> dict[str, str]:
    d06 = engine("e12_d06_series_audit")
    out: dict[str, str] = {}
    for key, (a, b) in CARRIER_PAIRS.items():
        ha, hb = hexes(a), hexes(b)
        out[f"grey.{key}"] = f"{abs(grey_l(ha) - grey_l(hb)):.1f}"
        des = [
            float(d06.delta_e76(d06.simulate(ha, d), d06.simulate(hb, d)))
            for d in ("protanopia", "deuteranopia", "tritanopia")
        ]
        out[f"cvd.{key}"] = " / ".join(f"{x:.1f}" for x in des)
    return out


def contrast_values(ctx: Ctx) -> dict[str, str]:
    out: dict[str, str] = {}
    groups: dict[str, list[tuple[str, str, str, float, str]]] = {}
    for row in ctx.contrast:
        groups.setdefault(row[0], []).append(row)
    groups["union"] = ctx.contrast
    for tag, rows_ in groups.items():
        k = tag.lower()
        pairs = {(r[1].replace("color.", "")) for r in rows_}
        fails = [r for r in rows_ if r[3] < THRESHOLD[r[4]]]
        texts = [r for r in rows_ if r[4] == "text"] or rows_
        low = min(texts, key=lambda r: r[3]) if texts else None
        out[f"pairs.{k}"] = str(len(pairs))
        out[f"fail.{k}"] = str(len(fails))
        out[f"low.{k}"] = (
            f"{low[3]:.2f}:1 ({low[2]}, {low[1].replace('color.', '')})" if low else "—"
        )
    return out


def sprint_values(ctx: Ctx) -> dict[str, str]:
    cal = engine("calendar_cv", CAL_REL)
    out: dict[str, str] = {}
    for n in (4, 6):
        s, e = cal.sprint_range(n)
        out[f"s0{n}.start"], out[f"s0{n}.end"] = s.isoformat(), e.isoformat()
    for key, n in CONSUMER_SPRINTS.items():
        start, _ = cal.sprint_range(n)
        ahead = start - datetime.timedelta(days=14)
        out[f"ahead.{key}"] = ahead.isoformat()
        if key == "s09":
            out["ahead.s09.status"] = "open" if ahead >= ctx.base_date else "missed"
    return out


def compute(ctx: Ctx) -> dict[str, str]:
    spec = ctx.spec
    v: dict[str, str] = {"sha": ctx.base}
    fam = {
        "kb": ("3.1 ", "KB"),
        "pp": ("3.2 ", "PP"),
        "fm": ("4. ", "FM"),
        "rg": ("5.1 ", "RG"),
        "bg": ("7.1 ", "BG"),
        "ow": ("8. ", "OW"),
        "c": ("12.1 ", "C"),
        "g": ("12.2 ", "G"),
        "ks": ("13.1 ", "KS"),
    }
    for key, (sec, f) in fam.items():
        v[key] = str(len(rows(section(spec, sec), f)))
    v["kb-summary"] = v["kb"]
    q = q07_rows(spec)
    v["q07"] = str(len(q))
    v["q07-summary"] = v["q07"]
    v["q07-proposed"] = str(sum(1 for r in q if "none merged — PROPOSED" in r[3]))
    clauses = section(spec, "10.1 ")
    v["clauses"] = str(sum(1 for ln in clauses.split("\n") if ln.startswith("| §")))
    car = section(spec, "10.4 ")
    v["carriers"] = str(len(table_body(car)))
    fr = rows(section(spec, "11. "), "F")
    v["f"] = v["f-summary"] = str(len(fr))
    for sev in SEVERITIES:
        v[f"f.{sev.lower()}"] = str(sum(1 for r in fr if len(r) > 1 and r[1] == sev))
    v["hr"] = str(len(re.findall(r"^- \*\*HR-\d+\*\*", section(spec, "12.5 "), re.MULTILINE)))
    v["pointer-lines"] = str(sum(1 for ln in ctx.p14.split("\n") if POINTER_MARK in ln))
    imgs = git("ls-tree", "--name-only", ctx.base, f"{IMG_DIR}/").split()
    v["images"] = v["inventory-images"] = str(len(imgs))
    for n in range(2, 9):
        v[f"images.d0{n}"] = str(sum(1 for p in imgs if Path(p).name.startswith(f"E12-D0{n}-")))
    km = engine("e11_d07_a11y_review_audit").load_keymap()
    v["km-commands"] = str(len(km["commands"]))
    v["km-version"] = str(km.get("version", "?"))
    srk = json.loads(show(ctx.base, SRK_REL) or "{}")
    v["srk-entries"] = str(len(srk.get("keys", [])))
    v["kb-undeclared"] = str(keymap_collisions(ctx, km))
    changed = set(git("diff", "--name-only", BQ_BASE, ctx.base).split())
    cited = {key_path(k, ctx.base) for k, _, _ in all_cites(spec)}
    v["bq-moved"] = str(len({p for p in cited if p} & changed))
    d07 = show(ctx.base, D07_REL) or ""
    v["parity-facts"] = str(
        max(0, len([ln for ln in section(d07, "9.2 ").split("\n") if ln.startswith("| ")]) - 2)
    )
    sim = simulate(ctx.combined_rule)
    v["sim.max-per-1s"] = str(sim["max"])
    v["sim.dropped-non-class4"] = str(sim["dropped_non4"])
    v["sim.class2-spoken"] = str(sim["class2_spoken"])
    v["sim.class2-total"] = str(sim["class2_total"])
    v["sim.flush-kept"] = "kept" if sim["flush_kept"] else "lost"
    v["flash.close-1s"] = str(round(1000 / CLOSE_MS))  # the ring moves once per close
    v["sd.account-word-hits"] = str(sum(len(ACCOUNT_WORDS.findall(r[3])) for r in q))
    v.update(contrast_values(ctx))
    ok = v["fail.union"] == "0"
    v["clause.contrast"] = "compliant" if ok else "at risk"
    v["wcag.143"] = v["wcag.1411"] = "compliant" if ok else "at risk"
    v.update(carrier_values())
    v.update(sprint_values(ctx))
    return v


def keymap_collisions(ctx: Ctx, km: dict[str, Any]) -> int:
    named = set(re.findall(r"shipped \(`([\w.]+)`", section(ctx.spec, "3.1 ")))
    seen: dict[tuple[str, str], int] = {}
    for c in km["commands"]:
        if c["id"] in named:
            k = (str(c["context"]), str(c["defaultBinding"]))
            seen[k] = seen.get(k, 0) + 1
    return sum(n - 1 for n in seen.values() if n > 1)


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
    states = [
        cells(ln)[0]
        for ln in section(ctx.spec, "10.4 ").split("\n")
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


def g_verbatim(ctx: Ctx, vals: dict[str, str], f: Findings) -> None:
    for r in q07_rows(ctx.spec):
        if len(r) < 8:
            f.append(("G05-VERBATIM", f"{r[0]}: the row has {len(r)} cells, not 8"))
            continue
        hay: list[str] = []
        for key, a, b in cite_spans(r[-1], bare=True):
            span = [ctx.base_line(key, n) or "" for n in range(a, b + 1)]
            hay.append(norm(" ".join(span)).replace("{", "").replace("}", ""))
        plain = ITALIC_QUOTE.sub("", r[3])
        quotes = QUOTE.findall(plain)
        if not quotes and not r[3].startswith(NOTHING) and "none merged — PROPOSED" not in r[3]:
            f.append(("G05-VERBATIM", f"{r[0]}: no quoted string and no {NOTHING!r}"))
        for q in quotes:
            nq = norm(q)
            if len(nq) >= 10:
                ok = any(nq in h for h in hay)
            else:
                ok = any(re.search(rf"(?<!\w){re.escape(nq)}(?!\w)", h) for h in hay)
            if not ok:
                f.append(("G05-VERBATIM", f"{r[0]}: {q[:48]!r} stands on no line the row cites"))


def g_script(ctx: Ctx, vals: dict[str, str], f: Findings) -> None:
    q = q07_rows(ctx.spec)
    regions = {x[0] for x in rows(section(ctx.spec, "5.1 "), "RG")}
    if not q:
        f.append(("G06-SCRIPT", "no Q07 row found"))
    for r in q:
        if len(r) < 8:
            f.append(("G06-SCRIPT", f"{r[0]}: {len(r)} cells"))
            continue
        mech = {m.strip() for m in re.split(r"[·;/]", r[4]) if m.strip()}
        if not mech or not mech <= MECHANISMS:
            f.append(("G06-SCRIPT", f"{r[0]}: mechanism {r[4]!r} is not from the vocabulary"))
        for i, what in ((5, "host"), (6, "rate"), (7, "source")):
            if not r[i]:
                f.append(("G06-SCRIPT", f"{r[0]}: no {what}"))
        if r[6] and not RATE.match(r[6]):
            f.append(("G06-SCRIPT", f"{r[0]}: rate {r[6]!r} is not from the vocabulary"))
        host = HOST.match(r[5])
        if host and host[1] not in regions:
            f.append(("G06-SCRIPT", f"{r[0]}: host {host[1]} is not a region of section 5.1"))
        if not host and not (r[5] == "no live write" and mech == {"none"}):
            f.append(("G06-SCRIPT", f"{r[0]}: host {r[5]!r} names no region"))
    shell = rows(section(ctx.spec, "5.1 "), "RG")
    pair = [x for x in shell if x[0] == "RG-06"]
    line = ctx.base_line("E17-D02", 249) or ""
    if not pair or "`E17-D02`:249" not in pair[0][-1] or "live-region pair" not in line:
        f.append(("G06-SCRIPT", "RG-06 is not E17-D02's shell announcer pair"))


def g_budget(ctx: Ctx, vals: dict[str, str], f: Findings) -> None:
    for r in rows(section(ctx.spec, "7.1 "), "BG"):
        if len(r) < 7:
            f.append(("G07-BUDGET", f"{r[0]}: {len(r)} cells"))
            continue
        if not RATE.match(r[3]) or r[3].startswith("n/a"):
            f.append(("G07-BUDGET", f"{r[0]}: max_rate {r[3]!r} is not an enforceable rate"))
        if not r[4] or not r[6]:
            f.append(("G07-BUDGET", f"{r[0]}: no object or no source"))


def g_findings(ctx: Ctx, vals: dict[str, str], f: Findings) -> None:
    sec = section(ctx.spec, "11. ")
    fr = rows(sec, "F")
    for r in fr:
        if len(r) < 9:
            f.append(("G08-FINDINGS", f"{r[0]}: {len(r)} cells"))
            continue
        if r[1] not in SEVERITIES:
            f.append(("G08-FINDINGS", f"{r[0]}: severity {r[1]!r}"))
        if not OWNER.match(r[4]):
            f.append(("G08-FINDINGS", f"{r[0]}: the owner is not one spec and its area"))
        if not r[5]:
            f.append(("G08-FINDINGS", f"{r[0]}: the target cell is empty"))
        if r[1] in ("Blocking", "Major") and (len(r) < 10 or r[9] in ("", "—")):
            f.append(("G08-FINDINGS", f"{r[0]}: a {r[1]} row has no reason cell"))
        if not G_T2.match(r[6]):
            f.append(("G08-FINDINGS", f"{r[0]}: G-T2 {r[6]!r} is not from the set"))
        if not FOCUS.match(r[7]):
            f.append(("G08-FINDINGS", f"{r[0]}: Focus {r[7]!r} is not from the set"))
        if r[8] != "n/a" and not RATE.match(r[8]):
            f.append(("G08-FINDINGS", f"{r[0]}: Rate {r[8]!r} is not from the set"))
    blocking = any(len(r) > 1 and r[1] == "Blocking" for r in fr)
    armed = "cannot be Done until fixed" in sec and "**not armed**" not in sec
    if blocking != armed:
        f.append(("G08-FINDINGS", "the hold sentence does not match the Blocking rows"))


def g_ids(ctx: Ctx, vals: dict[str, str], f: Findings) -> None:
    fams = {
        "KB": "3.1 ",
        "PP": "3.2 ",
        "FM": "4. ",
        "RG": "5.1 ",
        "BG": "7.1 ",
        "OW": "8. ",
        "T2": "9.1 ",
        "SD": "9.2 ",
        "F": "11. ",
        "G": "12.2 ",
        "A": "12.4 ",
        "KS": "13.1 ",
    }
    for fam, sec in fams.items():
        ids = [r[0] for r in rows(section(ctx.spec, sec), fam)]
        nums = [int(i.rsplit("-", 1)[1]) for i in ids]
        if not ids or nums != list(range(1, len(ids) + 1)):
            f.append(("G09-IDS", f"{fam}: the ids are not 1..n in order ({ids[:4]}…)"))
    q = [r[0] for r in q07_rows(ctx.spec)]
    if len(q) != len(set(q)):
        f.append(("G09-IDS", "a Q07 id repeats"))


T2_KEY = re.compile(r"^`(?:rbac\.(?:view_as|permission|owner_only)|barmode\.[a-z_]+)`")
T2_VERB = re.compile(r'(?:→ |· )"[a-z][^"]*"')


def g_t2(ctx: Ctx, vals: dict[str, str], f: Findings) -> None:
    sec = section(ctx.spec, "9.1 ")
    if "CMP-079 RbacGate wraps every gated control" not in sec or "`cta` omitted" not in sec:
        f.append(
            ("G19-T2", "section 9.1 does not state CMP-079's wrap and CMP-026's sentence form")
        )
    t2 = rows(sec, "T2")
    if not t2:
        f.append(("G19-T2", "no T2 row found"))
    for r in t2:
        cell = r[4] if len(r) > 4 else ""
        if not T2_KEY.match(cell):
            f.append(("G19-T2", f"{r[0]}: no E09-D09 section 3.1 key"))
        if re.match(r"^`rbac\.(?:permission|owner_only)`", cell) and not T2_VERB.search(cell):
            f.append(("G19-T2", f"{r[0]}: no section 3.2 verb"))
        sentence = len(r) > 5 and r[5] == "sentence"
        if sentence and "CMP-026" not in cell:
            f.append(("G19-T2", f"{r[0]}: the sentence form is not CMP-026"))
        if not sentence and "CMP-079" not in cell:
            f.append(("G19-T2", f"{r[0]}: the control is not wrapped by CMP-079"))


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
    if CLOSING.search(ctx.spec):
        f.append(("G10-HYGIENE", "the spec carries a closing keyword before an issue number"))


def g_account(ctx: Ctx, vals: dict[str, str], f: Findings) -> None:
    for r in q07_rows(ctx.spec):
        m = ACCOUNT_WORDS.search(r[3]) if len(r) > 3 else None
        if m:
            f.append(("G11-ACCOUNT", f"{r[0]}: an account-scoped word {m[0]!r}"))


def g_ruled(ctx: Ctx, vals: dict[str, str], f: Findings) -> None:
    sec = section(ctx.spec, "R. ")
    listed = [r[0] for r in rows(sec, "BQ")]
    if listed != [f"BQ-{n:02d}" for n in range(1, 23)]:
        f.append(("G12-RULED", f"section R lists {len(listed)} BQ rows, not BQ-01..BQ-22"))
    for r in rows(sec, "BQ"):
        if r[-1] != RULED_STAMP:
            f.append(("G12-RULED", f"{r[0]}: the status is not the ruling stamp"))
    if "<!-- BQ-" in ctx.spec:
        f.append(("G12-RULED", "a BQ marker is left in the spec"))
    for m in re.finditer(r"RULED (BQ-\d\d)((?:, BQ-\d\d)*)", ctx.spec):
        for bq in [m[1], *re.findall(r"BQ-\d\d", m[2])]:
            if bq not in listed:
                f.append(("G12-RULED", f"a stamp names {bq}, which section R does not list"))


def g_scope(ctx: Ctx, vals: dict[str, str], f: Findings) -> None:
    for p in ctx.changed:
        # post-merge, a fix to this tool may ship in one bundle with its sibling design tools
        sibling = ctx.merged_spec is not None and p.startswith("docs/design/_tools/")
        if p not in OWN and p != P14_REL and not sibling:
            f.append(("G13-SCOPE", f"{p} is outside the edit set"))


def g_pointers(ctx: Ctx, vals: dict[str, str], f: Findings) -> None:
    base = ctx.p14_base.split("\n")
    wt = ctx.p14.split("\n")
    added = [ln for ln in wt if ln not in set(base)]
    removed = [ln for ln in base if ln not in set(wt)]
    if removed:
        f.append(("G14-POINTERS", f"{len(removed)} line(s) of `14` removed or changed"))
    if ctx.merged_spec is None and len(added) != len(POINTER_ENTRIES):
        f.append(("G14-POINTERS", f"{len(added)} line(s) added to `14`, not six"))
    for ln in added:
        if not ln.startswith(f"- {POINTER_MARK} [E12-D11.md](../design/E12/E12-D11.md) (E12-D11; "):
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


def g_freeze(ctx: Ctx, vals: dict[str, str], f: Findings) -> None:
    if ctx.merged_spec is None:
        return
    now = set(ctx.spec.split("\n"))
    for ln in ctx.merged_spec.split("\n"):
        if ln.startswith("|") and not ln.startswith("| ---") and ln not in now:
            f.append(("G15-FREEZE", f"a merged row changed: {ln[:48]!r}"))


def g_contrast(ctx: Ctx, vals: dict[str, str], f: Findings) -> None:
    if not ctx.contrast:
        f.append(("G16-CONTRAST", "no pair could be measured"))
    for parent, pair, theme, r, kind in ctx.contrast:
        if r < THRESHOLD[kind]:
            f.append(
                ("G16-CONTRAST", f"{parent} {pair} ({theme}): {r:.2f}:1 under {THRESHOLD[kind]}")
            )


def g_sim(ctx: Ctx, vals: dict[str, str], f: Findings) -> None:
    sim = simulate(ctx.combined_rule)
    if sim["max"] > 2:
        f.append(("G17-BUDGET-SIM", f"{sim['max']} writes in one second"))
    if sim["dropped_non4"]:
        f.append(("G17-BUDGET-SIM", f"{sim['dropped_non4']} non-cursor write(s) dropped"))
    if not sim["flush_kept"] or sim["class2_spoken"] != sim["class2_total"]:
        f.append(("G17-BUDGET-SIM", "the trailing flush or a confirmation was lost"))


def g_keymap(ctx: Ctx, vals: dict[str, str], f: Findings) -> None:
    km = engine("e11_d07_a11y_review_audit").load_keymap()
    ids = {c["id"] for c in km["commands"]}
    bound = {
        str(c["defaultBinding"]).replace(" ", "")
        for c in km["commands"]
        if c["context"] in ("Chart", "Global")
    }
    for r in rows(section(ctx.spec, "3.1 "), "KB"):
        for cid in re.findall(r"`((?:chart|global)\.[\w.]+)`", r[4] if len(r) > 4 else ""):
            if cid not in ids:
                f.append(("G18-KEYMAP", f"{r[0]}: {cid} is not a command of the key map"))
        if len(r) > 4 and re.match(r"^(?:`05 row`|PROPOSED[^;]*); not in `KM`", r[4]):
            for key in re.findall(r"`([^`]+)`", r[2]):
                if key.replace(" ", "") in bound:
                    f.append(("G18-KEYMAP", f"{r[0]}: {key} is bound in the key map"))


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
    ("G11-ACCOUNT", g_account),
    ("G12-RULED", g_ruled),
    ("G13-SCOPE", g_scope),
    ("G14-POINTERS", g_pointers),
    ("G15-FREEZE", g_freeze),
    ("G16-CONTRAST", g_contrast),
    ("G17-BUDGET-SIM", g_sim),
    ("G18-KEYMAP", g_keymap),
    ("G19-T2", g_t2),
]


def run(ctx: Ctx) -> tuple[dict[str, str], Findings]:
    vals = compute(ctx)
    f: Findings = []
    for code, gate in GATES:
        try:
            gate(ctx, vals, f)
        except RUN_ERRORS as e:  # default-deny: an unreadable input is a FAIL
            f.append((code, f"the gate could not run: {type(e).__name__}: {e}"))
    return vals, f


# ---------------------------------------------------------------------------------- writers


def fill(ctx: Ctx) -> str:
    vals = compute(ctx)
    spec = ctx.spec

    def slot(m: re.Match[str]) -> str:
        kind, key = m[1], m[2]
        k = "sha" if kind == "SHA" else key
        k = "ahead.s09.status" if (kind, key) == ("STATUS", "ahead.s09") else k
        if k not in vals:
            return m[0]
        return f"{vals[k]} <!-- audit:{k}={vals[k]} -->"

    spec = SLOT.sub(slot, spec)

    def marker(m: re.Match[str]) -> str:
        key = m[1]
        return f"<!-- audit:{key}={vals[key]} -->" if key in vals else m[0]

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

        ln = AUDIT.sub(marker, ln)
        for m in list(AUDIT.finditer(ln)):  # a single-token visible value left stale: rewrite it
            key, val = m[1], m[2]
            if " " not in val:
                tail = f" <!-- audit:{key}={val} -->"
                pat = re.compile(rf"(`?)(?<![>\w.:+-])[\w.:+-]+(`?){re.escape(tail)}")
                hit = pat.search(ln)
                if hit:
                    fixed = f"{hit[1]}{val}{hit[2]}{tail}"
                    ln = ln[: hit.start()] + fixed + ln[hit.end() :]
        out.append(ln)
    return "\n".join(out)


def repin(ctx: Ctx) -> str:
    lines = [
        "# E12-D11 pins: one cited endpoint per line, `KEY:line sha1-16` of its words at the base.",
        "# Written only by `e12_d11_a11y_review_audit.py --repin-ruled`.",
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


def set_cell(text: str, row_id: str, index: int, value: str, indent: int = 0) -> str:
    out = []
    done = False
    for ln in text.split("\n"):
        if not done and re.match(rf"^ {{{indent}}}\|\s*{re.escape(row_id)}\s*\|", ln):
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


MUTATIONS: list[tuple[str, Callable[[Ctx], Ctx]]] = [
    ("G01-FILLED", lambda c: dataclasses.replace(c, spec=c.spec + "\n{{COUNT:kb}}\n")),
    (
        "G02-AUDIT",
        lambda c: dataclasses.replace(
            c, spec=_swap(c.spec, first(r"<!-- audit:kb=\d+ -->", c.spec), "<!-- audit:kb=999 -->")
        ),
    ),
    (
        "G03-CITE",
        lambda c: dataclasses.replace(
            c,
            pins=re.sub(
                r"^(D03:\d+) [0-9a-f]{16}$",
                r"\1 0000000000000000",
                c.pins,
                count=1,
                flags=re.MULTILINE,
            ),
        ),
    ),
    ("G04-PINS", lambda c: dataclasses.replace(c, spec=c.spec + "\nSee `D03`:5.\n")),
    (
        "G05-VERBATIM",
        lambda c: dataclasses.replace(
            c, spec=_swap(c.spec, '"Lot size not known yet"', '"Lot size not quite known"')
        ),
    ),
    (
        "G06-SCRIPT",
        lambda c: dataclasses.replace(
            c, spec=_swap(c.spec, first(r"\| name · role · desc \|", c.spec), "| shouted |")
        ),
    ),
    ("G07-BUDGET", lambda c: dataclasses.replace(c, spec=set_cell(c.spec, "BG-01", 3, "n/a"))),
    ("G08-FINDINGS", lambda c: dataclasses.replace(c, spec=set_cell(c.spec, "F-02", 1, "Severe"))),
    (
        "G02-AUDIT",
        lambda c: dataclasses.replace(
            c,
            spec=c.spec.replace(
                f"{len(table_body(section(c.spec, '10.4 ')))} <!-- audit:carriers=",
                f"{len(table_body(section(c.spec, '10.4 '))) + 1} <!-- audit:carriers=",
            ),
            combined_rule=c.combined_rule,
        ),
    ),
    (
        "G06-SCRIPT",
        lambda c: dataclasses.replace(c, spec=set_cell(c.spec, "Q07-49", 6, "whenever", 4)),
    ),
    (
        "G06-SCRIPT",
        lambda c: dataclasses.replace(c, spec=set_cell(c.spec, "Q07-48", 5, "RG-99", 4)),
    ),
    (
        "G08-FINDINGS",
        lambda c: dataclasses.replace(
            c,
            spec=set_cell(
                set_cell(set_cell(c.spec, "F-02", 6, "bogus"), "F-02", 7, "whatever"),
                "F-02",
                8,
                "sometimes",
            ),
        ),
    ),
    (
        "G05-VERBATIM",
        lambda c: dataclasses.replace(
            c, spec=set_cell(c.spec, "Q07-48", 3, "the chip text, in words of its own", 4)
        ),
    ),
    (
        "G05-VERBATIM",
        lambda c: dataclasses.replace(c, spec=set_cell(c.spec, "Q07-65", 3, '"Back"', 4)),
    ),
    (
        "G19-T2",
        lambda c: dataclasses.replace(c, spec=set_cell(c.spec, "T2-05", 4, "CMP-079 RbacGate")),
    ),
    (
        "G19-T2",
        lambda c: dataclasses.replace(
            c, spec=set_cell(c.spec, "T2-06", 4, "`rbac.owner_only` · CMP-079")
        ),
    ),
    ("G09-IDS", lambda c: dataclasses.replace(c, spec=_swap(c.spec, "| KB-03 |", "| KB-02 |"))),
    (
        "G10-HYGIENE",
        lambda c: dataclasses.replace(c, spec=c.spec + "\n" + BANNED[8].upper() + "\n"),
    ),
    (
        "G11-ACCOUNT",
        lambda c: dataclasses.replace(
            c, spec=_swap(c.spec, '"Lot size not known yet"', '"Lot size not known yet" position')
        ),
    ),
    (
        "G12-RULED",
        lambda c: dataclasses.replace(c, spec=_swap(c.spec, f"| {RULED_STAMP} |", "| pending |")),
    ),
    ("G13-SCOPE", lambda c: dataclasses.replace(c, changed=[*c.changed, "docs/plan/15-x.md"])),
    (
        "G14-POINTERS",
        lambda c: dataclasses.replace(
            c, p14="\n".join(ln for ln in c.p14.split("\n") if "E12-D11; the polite card" not in ln)
        ),
    ),
    (
        "G15-FREEZE",
        lambda c: dataclasses.replace(c, merged_spec="| KB-99 | a merged row since changed |\n"),
    ),
    (
        "G16-CONTRAST",
        lambda c: dataclasses.replace(
            c, contrast=[*c.contrast, ("D99", "x on y", "dark", 2.1, "text")]
        ),
    ),
    ("G17-BUDGET-SIM", lambda c: dataclasses.replace(c, combined_rule=False)),
    (
        "G18-KEYMAP",
        lambda c: dataclasses.replace(
            c,
            spec=_swap(c.spec, "shipped (`chart.interval_preset`)", "shipped (`chart.no_such_id`)"),
        ),
    ),
]


def frozen_base_problems(ctx: Ctx) -> list[str]:
    """Post-merge cites freeze at the recorded base: a moved merge-base must not move them."""
    out: list[str] = []
    moved = "f" * 40  # stands for a main that has moved on since the pack merged
    if frozen_base(None, moved) != moved:
        out.append("PR-1 mode must read at the merge-base")
    if ctx.merged_spec is not None:
        if frozen_base(ctx.merged_spec, moved) != ctx.base:
            out.append("post-merge mode follows the merge-base, not the recorded base")
        no_marker = ctx.merged_spec.replace("audit:sha=", "audit:unused=")
        if frozen_base(no_marker, moved) != moved:
            out.append("post-merge mode with no recorded base must fall back, which G02 then fails")
        stale = re.sub(r"(audit:sha=)[0-9a-f]{40}", r"\g<1>" + "0" * 40, ctx.merged_spec)
        if frozen_base(stale, moved) != moved:
            out.append("an unresolvable recorded base was accepted")
    return out


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
    problems += frozen_base_problems(ctx)
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
