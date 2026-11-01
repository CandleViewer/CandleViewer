"""E12-D13 (#450) audit: the design QA of the built E12 bar modes, series and their states.

Stdlib only, offline (`python3 -I -B`). It reads the spec, the pins file and the captures from the
working tree, and every cited file AS TEXT at the merge-base with `origin/main` (`git show`). It runs
no repo code and drives no browser: the capture run is scratch and its observations are the spec's
rows. It imports, never copies: the E12-D06 tool's geometry functions (`body_px`, `wick_up_px`) and
`calendar_cv.sprint_range`. Default-deny: a gate that cannot read its input FAILs.

Two modes, chosen by content, never by branch name. PR-1 mode: the spec is absent at the merge-base;
the diff may touch only the three own files and the `E12-D13-*` captures. Post-merge mode: the spec
ships at the merge-base; every merged table row stands unchanged and only later rows may move.

Gates (each FAIL led by its code):

- [G01-FILLED] no `{{KIND:key}}` slot is left in the spec.
- [G02-AUDIT] every `<!-- audit:key=value -->` marker is a known key, equals the recomputed value
  and stands right after its visible value.
- [G03-CITE] every cited endpoint resolves at the base to a non-blank line, and its pin matches.
- [G04-PINS] the pins file and the spec's cited endpoints match both ways.
- [G05-STATUS] every row of a run family leads its status cell with a word of the ruled vocabulary;
  a `deferred-owned` or `not-comparable-yet` row names an owner story with its issue; an
  `owner-run` row names its OR leg.
- [G06-GEOM] the E12-D06 values this pass lifts agree with the formulas evaluated at the samples
  (D06's own body widths at the ladder samples equal `body_px`).
- [G07-COPY] every deck key a `pass` CP row names equals, part by part, a built string literal of
  the files the row cites; the ticket's superseded strings stand in no built source tree.
- [G08-REGISTER] every DF row has a class and a severity from the ruled sets, an owner of the form
  `E12-Dnn · area/<slug>` and a target story; no Blocking row stands without an IS row.
- [G09-IDS] the ids of each table family are unique and in order.
- [G10-HYGIENE] no lane-private word, URL, local path, uuid or closing keyword in the own files.
- [G11-RULED] section R lists BQ-01..BQ-25 once each with the ruling stamp; no BQ marker is left.
- [G12-SCOPE] the changed paths are the own files and the `E12-D13-*` captures only.
- [G13-FREEZE] post-merge mode: every merged table row stands unchanged.
- [G14-RERUN] every `deferred-owned`, `not-comparable-yet` and `out-of-scope` row is named by a row
  of the re-run table.
- [G15-CAPTURE] every CA row names an existing capture of the changed set, run kind `emulated`, a
  DPR of 1, 1.25 or 2; every `E12-D13-*` PNG is named by a CA row; each file is a PNG.
- [G16-EVENTS] the EV rows are E12-D12 §13's events in order; a name with a built call site is not
  `deferred-owned`, and a name with none is.
- [G17-SURFACES] the SU rows are the seven surfaces of `T Scope`, in order.
- [G18-TOKENS] each token TK-1 names ships in every theme and is bound by the card's source;
  `color.chart.background` ships in none (TK-3).

`--json` prints the numbers and findings; `--check` exits 1 on any FAIL; `--fill` writes the
computed values into the spec's slots and markers; `--self-test` applies one mutation per gate to an
in-memory copy and passes only when each adds FAILs of its gate's code and the base run is clean;
`--repin-ruled` rewrites the pins file from the spec's cites and is its only writer.

Usage: python3 -I -B docs/design/_tools/e12_d13_designqa_audit.py [--check] [--json] [--fill]
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
from decimal import ROUND_HALF_UP, Decimal
from pathlib import Path
from types import ModuleType

ROOT = Path(__file__).resolve().parents[3]
TOOLS = ROOT / "docs" / "design" / "_tools"
SPEC_REL = "docs/design/E12/E12-D13.md"
TOOL_REL = "docs/design/_tools/e12_d13_designqa_audit.py"
PINS_REL = "docs/design/_tools/e12_d13_ruled_pins.txt"
OWN = {SPEC_REL, TOOL_REL, PINS_REL}
IMG_DIR = "docs/design/E12/img"
IMG_PREFIX = f"{IMG_DIR}/E12-D13-"
UPSTREAM = "origin/main"
RULED_STAMP = "RULED (orchestrator, 2026-11-01, #450 ruling of record — 6552808644)"
D06_REL = "docs/design/E12/E12-D06.md"
D12_REL = "docs/design/E12/E12-D12.md"
DECK_REL = "docs/design/E12/E12-D12-copy.json"
CAL_REL = "docs/plan/backlog/_tools/calendar_cv.py"
D06_TOOL_REL = "docs/design/_tools/e12_d06_series_audit.py"
DS_SRC = "packages/ui/tokens"
BUILT_TREES = ("apps/web/src", "packages/ui/src", "packages/chart-engine/src")
EVENT_TREES = ("apps/web/src", "packages/ui/src")

CODE_KEYS = {
    "CHART": "apps/web/src/chart/Chart.tsx",
    "CESC": "apps/web/src/features/chart-errors/copy.ts",
    "CES": "apps/web/src/features/chart-errors/ChartErrorSurface.tsx",
    "QSW": "apps/web/src/features/symbol-search/QuickSwitcher.tsx",
    "SSC": "apps/web/src/features/symbol-search/copy.ts",
    "LAYERS": "packages/chart-engine/src/layers/index.ts",
    "MOUNT": "packages/chart-engine/src/host/mount.ts",
    "RESIZE": "packages/chart-engine/src/host/resize.ts",
    "PROTO": "packages/chart-engine/src/worker/protocol.ts",
    "README": "docs/design/README.md",
}
DESIGN_KEYS = {f"D{n:02d}": f"docs/design/E12/E12-D{n:02d}.md" for n in (*range(2, 10), 11, 12)}
KEY_RE = r"D0[2-9]|D1[12]|\d\d|E\d\d-D\d\d|" + "|".join(CODE_KEYS)
MD_CITE = re.compile(
    rf"`(?P<key>{KEY_RE})`:(?P<a>\d+)(?:[–-](?P<b>\d+))?(?P<more>(?:, :\d+(?:[–-]\d+)?)*)"
)
MORE = re.compile(r":(\d+)(?:[–-](\d+))?")
SLOT = re.compile(r"\{\{([A-Z]+):([\w.-]+)\}\}")
AUDIT = re.compile(r"<!-- audit:([\w.-]+)=([^>]*?) -->")
ANCHOR = re.compile(r"([\w.]+)<!--=([A-Z]+):([\w.-]+)-->")

STATUSES = (
    "compared",
    "compared-in-part",
    "pass",
    "fail",
    "deferred-owned",
    "owner-run",
    "not-comparable-yet",
    "known",
    "out-of-scope (unbuilt)",
)
RUN_FAMILIES = (
    "SU",
    "CM",
    "CA",
    "GE",
    "MX",
    "ST",
    "TK",
    "CP",
    "MO",
    "KR",
    "SR",
    "AX",
    "NN",
    "FB",
    "SC",
    "PF",
    "EV",
)
ID_FAMILIES = (*RUN_FAMILIES, "DF", "RT", "DR", "RR", "OR", "CO", "BQ")
STORY = re.compile(r"E\d\d-[A-Z]\d\d \(#\d+\)")
SEVERITIES = ("Blocking", "Major", "Minor", "Info")
CLASSES = ("implementation defect", "accepted divergence", "specification gap")
OWNER = re.compile(r"^`E\d\d-D\d\d · area/[a-z-]+`$")
SURFACES = ("SCR-030", "SCR-031", "SCR-041", "SCR-042", "SCR-045", "SCR-047", "SCR-048")
SUPERSEDED = ("Needs recorded ticks", "Values below one tick are not allowed.")
DPRS = ("1", "1.25", "2")
SAMPLE_KEYS = tuple(f"sample-{n}" for n in range(1, 6))
GE_SAMPLE = {"ge-01": "sample-1", "ge-02": "sample-2", "ge-03": "sample-3"}
STORY_COMPONENTS = {
    "cmp181": "CandleSeries",
    "cmp220": "IntervalPicker",
    "cmp222": "ChartTypeToggle",
    "cmp226": "BarCountdown",
    "cmp248": "HistoryMarker",
}
# rot13 keeps the private list out of plain text; underscores stand for spaces.
BANNED_ROT13 = (
    "yrnx rkcbfrq olcnff rkcybvg nggnpx benpyr erirny haobhaqrq sybbq fgnyy qbf nqivfbel tufn "
    "cer-nhgu ucr-jbexre znva-bepurfgengbe"
)
BANNED = [w.replace("_", " ") for w in codecs.decode(BANNED_ROT13, "rot13").split()]
BANNED_RE = re.compile(r"\b(?:" + "|".join(re.escape(w) for w in BANNED) + r")", re.IGNORECASE)
URL = re.compile(r"https?://|\bwww\.", re.IGNORECASE)
UUID = re.compile(r"\b[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}\b")
LOCAL_PATH = re.compile("|".join("/" + w + "/" for w in ("home", "mnt", "tmp")))
CLOSING = re.compile(r"\b(?:close[sd]?|fix(?:e[sd])?|resolve[sd]?) #\d+", re.IGNORECASE)
PNG_MAGIC = b"\x89PNG\r\n\x1a\n"


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
    if key in CODE_KEYS:
        return CODE_KEYS[key]
    if re.fullmatch(r"\d\d", key):
        return plan_path(key, rev)
    m = re.fullmatch(r"(E\d\d)-(D\d\d)", key)
    return f"docs/design/{m[1]}/{key}.md" if m else None


@functools.cache
def grep_base(rev: str, needle: str, trees: tuple[str, ...]) -> tuple[str, ...]:
    """The files under `trees` at `rev` whose text holds `needle` (fixed string)."""
    out = git("grep", "-l", "-F", "-e", needle, rev, "--", *trees)
    return tuple(sorted({ln.split(":", 1)[1] for ln in out.split() if ":" in ln}))


@functools.cache
def ls_base(rev: str, tree: str) -> tuple[str, ...]:
    return tuple(git("ls-tree", "-r", "--name-only", rev, tree).split())


def read(rel: str) -> str:
    p = ROOT / rel
    return p.read_text(encoding="utf-8") if p.exists() else ""


@functools.cache
def engine(name: str, rel: str) -> ModuleType:
    if str(TOOLS) not in sys.path:
        sys.path.insert(0, str(TOOLS))
    spec = importlib.util.spec_from_file_location(name, ROOT / rel)
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


def rows(text: str, family: str) -> list[list[str]]:
    pat = re.compile(rf"^\|\s*{re.escape(family)}-\d+\s*\|")
    return [cells(ln) for ln in text.split("\n") if pat.match(ln)]


def status_of(row: list[str]) -> str:
    m = re.match(r"^`([^`]+)`", row[-2]) if len(row) >= 2 else None
    return m[1] if m else ""


def norm(s: str) -> str:
    return re.sub(r"\s+", " ", s.replace("`", "").replace("*", "")).strip()


def line_hash(s: str) -> str:
    return hashlib.sha1(norm(s).encode("utf-8")).hexdigest()[:16]


def cite_spans(text: str) -> list[tuple[str, int, int]]:
    out: list[tuple[str, int, int]] = []
    for m in MD_CITE.finditer(text):
        key = m["key"]
        a = int(m["a"])
        out.append((key, a, int(m["b"]) if m["b"] else a))
        for mm in MORE.finditer(m["more"] or ""):
            x = int(mm[1])
            out.append((key, x, int(mm[2]) if mm[2] else x))
    return out


def endpoints(spec: str) -> set[tuple[str, int]]:
    out: set[tuple[str, int]] = set()
    for key, a, b in cite_spans(spec):
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


def expand_ids(cell: str) -> set[str]:
    """`GE-01..GE-03, GE-06` and `MX-08..MX-12` to the ids they name."""
    out: set[str] = set()
    for m in re.finditer(r"\b([A-Z]{2})-(\d+)(?:\.\.\1-(\d+))?", cell):
        fam, a = m[1], int(m[2])
        b = int(m[3]) if m[3] else a
        width = len(m[2])
        out |= {f"{fam}-{n:0{width}d}" for n in range(a, b + 1)}
    return out


def anchors(text: str) -> dict[str, str]:
    """`value<!--=KIND:key-->` anchors of a parent spec: `KIND:key` to its first value."""
    out: dict[str, str] = {}
    for m in ANCHOR.finditer(text):
        out.setdefault(f"{m[2]}:{m[3]}", m[1])
    return out


def literals(source: str) -> list[re.Pattern[str]]:
    """The string literals of a TS file as patterns: a template's `${…}` matches any text."""
    out: list[re.Pattern[str]] = []
    for m in re.finditer(r'"((?:[^"\\\n]|\\.)*)"|`([^`]*)`', source):
        raw = m[1] if m[1] is not None else m[2]
        parts = re.split(r"\$\{[^}]*\}", raw)
        out.append(re.compile(".+".join(re.escape(p) for p in parts) + r"\Z", re.DOTALL))
    return out


def deck_parts(text: str) -> list[str]:
    """A deck entry's parts: split on the deck's " · " joins, outer quotes stripped."""
    s = text.strip()
    if s.startswith('"') and s.endswith('"'):
        return [p.strip().strip('"') for p in re.split(r'"\s*·\s*"', s[1:-1])]
    return [p.strip() for p in s.split(" · ")]


def matches(part: str, pats: list[re.Pattern[str]]) -> bool:
    if any(p.match(part) for p in pats):
        return True
    # a line the build draws from two literals, title then body (the strip, `d08:W-20`)
    for i, a in enumerate(pats):
        for b in pats[i + 1 :]:
            src = a.pattern[:-2] + " " + b.pattern
            if re.match(src, part, re.DOTALL):
                return True
    return False


# ------------------------------------------------------------------------------------ context


@dataclasses.dataclass
class Ctx:
    spec: str
    pins: str
    tool: str
    changed: list[str]
    merged_spec: str | None
    base: str
    d06: str
    d12: str
    deck: dict[str, dict[str, str]]
    images: list[str]

    def base_line(self, key: str, n: int) -> str | None:
        rel = key_path(key, self.base)
        text = show(self.base, rel) if rel else None
        if text is None:
            return None
        lines = text.split("\n")
        return lines[n - 1] if 0 < n <= len(lines) else None


def build_ctx() -> Ctx:
    base = merge_base()
    if not base:
        raise RuntimeError("no merge-base with origin/main")
    changed = sorted(
        {
            *git("diff", "--name-only", base).split(),
            *git("ls-files", "-o", "--exclude-standard").split(),
        }
    )
    deck = json.loads(show(base, DECK_REL) or "{}").get("entries", {})
    images = sorted(
        f"{IMG_DIR}/{p.name}" for p in (ROOT / IMG_DIR).glob("E12-D13-*") if p.is_file()
    )
    return Ctx(
        spec=read(SPEC_REL),
        pins=read(PINS_REL),
        tool=read(TOOL_REL),
        changed=changed,
        merged_spec=show(base, SPEC_REL),
        base=base,
        d06=show(base, D06_REL) or "",
        d12=show(base, D12_REL) or "",
        deck=deck,
        images=images,
    )


# ------------------------------------------------------------------------------- the numbers


def rhu(x: Decimal) -> int:
    return int(x.to_integral_value(rounding=ROUND_HALF_UP))


def device_body(css: int, s: Decimal, dpr: Decimal, odd_from: int) -> int:
    """D06 §2: roundHalfUp(width x dpr) device px, re-forced odd where the CSS rule forces odd."""
    d = rhu(Decimal(css) * dpr)
    if css >= odd_from and d % 2 == 0:
        d = d + 1 if d + 1 <= s * dpr - 1 else d - 1
    return d


def hair(dpr: Decimal) -> int:
    return max(1, int(dpr))


def geom_values(ctx: Ctx) -> dict[str, str]:
    d06 = engine("e12_d06_series_audit", D06_TOOL_REL)
    a = anchors(ctx.d06)
    samples = [a[f"LADDER:{k}"] for k in SAMPLE_KEYS]
    odd_from = int(a["GEOM:body.odd-from"])
    dprs = [Decimal(x) for x in DPRS]
    out = {
        "samples": ", ".join(samples),
        "tier.l0": a["TIER:l0"],
        "tier.l1": a["TIER:l1"],
    }
    for key, sk in GE_SAMPLE.items():
        s = Decimal(a[f"LADDER:{sk}"])
        css = int(d06.body_px(s))
        dev = " / ".join(str(device_body(css, s, d, odd_from)) for d in dprs)
        out[key] = f"{css} · {dev}"
    up = int(d06.wick_up_px(int(d06.body_px(Decimal(samples[0])))))
    out["ge-06"] = f"{up} · " + " / ".join(str(up * hair(d)) for d in dprs)
    out["ge-07"] = f"{2 * up} · " + " / ".join(str(2 * up * hair(d)) for d in dprs)
    zero = int(a["GEOM:zero.h"])
    out["ge-08"] = f"{zero} · " + " / ".join(str(zero * hair(d)) for d in dprs)
    return out


def d12_story_counts(d12: str) -> dict[str, int]:
    a = anchors(d12)
    return {k: int(a[f"CITE:stories.{k}"]) for k in STORY_COMPONENTS}


def d12_events(d12: str) -> list[str]:
    sec = section(d12, "13. ")
    return [m[1] for m in re.finditer(r"^\| `(chart\.[\w.]+)`", sec, re.MULTILINE)]


@functools.cache
def layering(base: str) -> dict[str, tuple[str, ...]]:
    data = json.loads(show(base, f"{DS_SRC}/themes.json") or "{}")
    out: dict[str, tuple[str, ...]] = {}
    for th in data.get("themes", []) if isinstance(data, dict) else []:
        if isinstance(th, dict) and th.get("group") == "theme":
            out[str(th.get("name"))] = tuple(str(x) for x in th.get("sets", []))
    return out


@functools.cache
def theme_names(base: str, name: str) -> frozenset[str]:
    names: set[str] = set()
    for f in layering(base).get(name, ()):
        data = json.loads(show(base, f"{DS_SRC}/{f}.tokens.json") or "{}")
        if isinstance(data, dict):
            names |= {k for k, v in data.items() if isinstance(v, dict) and "$value" in v}
    return frozenset(names)


def shipped(base: str, token: str) -> bool:
    themes = layering(base)
    return bool(themes) and all(token in theme_names(base, t) for t in themes)


def manifest_rows(d12: str) -> list[tuple[str, str]]:
    """D12 §12's token rows: (token, the pack's mark `shipped` / `absent`)."""
    sec = section(d12, "12. ")
    pat = re.compile(r"^\| `([\w.-]+)`\s*\| (shipped|absent)<!--=TOKEN:", re.MULTILINE)
    return [(m[1], m[2]) for m in pat.finditer(sec)]


def cp_keys(row: list[str]) -> list[str]:
    return re.findall(r"\bd0[3-8]:[A-Z]+-\d+(?:#\d)?", row[1])


def compute(ctx: Ctx) -> dict[str, str]:
    spec = ctx.spec
    v: dict[str, str] = {"sha": ctx.base[:10]}
    su = [status_of(r) for r in rows(spec, "SU")]
    v["su.compared"] = str(su.count("compared"))
    v["su.part"] = str(su.count("compared-in-part"))
    v["su.deferred"] = str(su.count("deferred-owned"))
    ge = [status_of(r) for r in rows(spec, "GE")]
    v["ge"] = str(len(ge))
    v["ge.pass"] = str(ge.count("pass"))
    v["ge.deferred"] = str(ge.count("deferred-owned"))
    v["ge.owner"] = str(ge.count("owner-run"))
    v["mx"] = str(len(rows(spec, "MX")))
    st = [status_of(r) for r in rows(spec, "ST")]
    v["st"] = str(len(st))
    v["st.reached"] = str(sum(s in ("compared", "compared-in-part", "pass") for s in st))
    v["mo"] = str(len(rows(spec, "MO")))
    v["ax.run"] = str(sum(status_of(r) == "pass" for r in rows(spec, "AX")))
    v["sr.tree"] = str(sum(status_of(r) != "deferred-owned" for r in rows(spec, "SR")))
    v["ca"] = str(len(rows(spec, "CA")))
    compared = [k for r in rows(spec, "CP") if status_of(r) == "pass" for k in cp_keys(r)]
    v["deck.compared"] = str(len(compared))
    v["deck.differs"] = str(len(copy_differences(ctx)))
    v["deck.rest"] = str(len(ctx.deck) - len(set(compared)))
    agree = [shipped(ctx.base, t) == (mark == "shipped") for t, mark in manifest_rows(ctx.d12)]
    v["tk.rows"] = str(len(agree))
    v["tk.agree"] = str(sum(agree))
    v["ev.manifest"] = str(len(d12_events(ctx.d12)))
    counts = d12_story_counts(ctx.d12)
    for k, n in counts.items():
        v[f"stories.{k}"] = str(n)
    v["stories.required"] = str(sum(counts.values()))
    v["stories.built"] = str(len(built_stories(ctx.base)))
    df = rows(spec, "DF")
    v["df"] = str(len(df))
    for sev in SEVERITIES:
        v[f"df.{sev.lower()}"] = str(sum(r[2] == sev for r in df if len(r) > 2))
    for key, cls in zip(("df.defect", "df.accepted", "df.gap"), CLASSES, strict=True):
        v[key] = str(sum(r[1].startswith(cls) for r in df if len(r) > 1))
    v.update(geom_values(ctx))
    cal = engine("calendar_cv", CAL_REL)
    for n in (8, 9):
        s, e = cal.sprint_range(n)
        v[f"s0{n}.start"], v[f"s0{n}.end"] = s.isoformat(), e.isoformat()
    s9, _ = cal.sprint_range(9)
    v["ahead.s09"] = (s9 - datetime.timedelta(days=14)).isoformat()
    return v


def built_stories(base: str) -> list[str]:
    return [
        p
        for p in ls_base(base, "packages/ui/src") + ls_base(base, "apps/web/src")
        if p.endswith((".stories.tsx", ".stories.ts"))
        and any(name in Path(p).name for name in STORY_COMPONENTS.values())
    ]


def copy_differences(ctx: Ctx) -> list[str]:
    """Each deck key of a `pass` CP row whose parts do not all equal a built literal."""
    out: list[str] = []
    for r in rows(ctx.spec, "CP"):
        if status_of(r) != "pass" or len(r) < 3:
            continue
        pats: list[re.Pattern[str]] = []
        for key, _, _ in cite_spans(r[2]):
            rel = key_path(key, ctx.base)
            pats += literals((show(ctx.base, rel) if rel else None) or "")
        for k in cp_keys(r):
            entry = ctx.deck.get(k)
            if entry is None or not pats:
                out.append(f"{r[0]}: {k} has no deck entry or no built source")
                continue
            for part in deck_parts(str(entry.get("text", ""))):
                if not matches(part, pats):
                    out.append(f"{r[0]}: {k} part {part[:40]!r} equals no built literal")
    return out


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


def g_status(ctx: Ctx, vals: dict[str, str], f: Findings) -> None:
    seen = 0
    for fam in RUN_FAMILIES:
        for r in rows(ctx.spec, fam):
            seen += 1
            st = status_of(r)
            if st not in STATUSES:
                f.append(("G05-STATUS", f"{r[0]}: status {r[-2][:30]!r} is not a ruled word"))
                continue
            if st in ("deferred-owned", "not-comparable-yet") and not STORY.search(r[-1]):
                f.append(("G05-STATUS", f"{r[0]}: {st} names no owner story with its issue"))
            if st == "owner-run" and not re.search(r"\bOR-\d\b", r[-1]):
                f.append(("G05-STATUS", f"{r[0]}: owner-run names no OR leg"))
    if not seen:
        f.append(("G05-STATUS", "no run row found"))


def g_geom(ctx: Ctx, vals: dict[str, str], f: Findings) -> None:
    d06 = engine("e12_d06_series_audit", D06_TOOL_REL)
    a = anchors(ctx.d06)
    for n, sk in enumerate(SAMPLE_KEYS[:3], start=1):
        s = Decimal(a[f"LADDER:{sk}"])
        said = a.get(f"LADDER:body.at-sample-{n}")
        got = str(d06.body_px(s))
        if said != got:
            f.append(("G06-GEOM", f"D06's body at {sk} reads {said}, the formula gives {got}"))
    for r in rows(ctx.spec, "GE"):
        key = r[0].lower()
        if key in vals and vals[key] not in r[4]:
            f.append(("G06-GEOM", f"{r[0]}: the expected cell is not the evaluated value"))


def g_copy(ctx: Ctx, vals: dict[str, str], f: Findings) -> None:
    if not any(status_of(r) == "pass" and cp_keys(r) for r in rows(ctx.spec, "CP")):
        f.append(("G07-COPY", "no CP row compares a deck key"))
    for msg in copy_differences(ctx):
        f.append(("G07-COPY", msg))
    for old in SUPERSEDED:
        hits = grep_base(ctx.base, old, BUILT_TREES)
        if hits:
            f.append(("G07-COPY", f"the superseded string {old[:24]!r} stands in {hits[0]}"))


def g_register(ctx: Ctx, vals: dict[str, str], f: Findings) -> None:
    df = rows(ctx.spec, "DF")
    if not df:
        f.append(("G08-REGISTER", "no DF row found"))
    for r in df:
        if len(r) != 8:
            f.append(("G08-REGISTER", f"{r[0]}: {len(r)} cells, not 8"))
            continue
        if not any(r[1].startswith(c) for c in CLASSES):
            f.append(("G08-REGISTER", f"{r[0]}: class {r[1][:30]!r} is not a ruled class"))
        if r[2] not in SEVERITIES:
            f.append(("G08-REGISTER", f"{r[0]}: severity {r[2]!r} is not on the scale"))
        if not OWNER.match(r[4]):
            f.append(("G08-REGISTER", f"{r[0]}: owner {r[4]!r} is not a spec and its area"))
        if not STORY.fullmatch(r[5]):
            f.append(("G08-REGISTER", f"{r[0]}: target {r[5]!r} is not a story with its issue"))
        if r[2] == "Blocking" and r[0] not in section(ctx.spec, "13.2 "):
            f.append(("G08-REGISTER", f"{r[0]}: a Blocking row with no IS row"))


def g_ids(ctx: Ctx, vals: dict[str, str], f: Findings) -> None:
    for fam in ID_FAMILIES:
        ids = [r[0] for r in rows(ctx.spec, fam)]
        nums = [int(i.split("-")[1]) for i in ids]
        if len(set(ids)) != len(ids):
            f.append(("G09-IDS", f"{fam}: a repeated id"))
        if nums != list(range(1, len(nums) + 1)):
            f.append(("G09-IDS", f"{fam}: ids are not 1..{len(nums)} in order"))


def g_hygiene(ctx: Ctx, vals: dict[str, str], f: Findings) -> None:
    for name, text in (("the spec", ctx.spec), ("the tool", ctx.tool), ("the pins", ctx.pins)):
        m = BANNED_RE.search(text)
        if m:
            f.append(("G10-HYGIENE", f"{name}: a word from the private list"))
        for pat, what in ((URL, "a URL"), (UUID, "a uuid"), (LOCAL_PATH, "a local path")):
            hit = pat.search(text)
            if hit:
                f.append(("G10-HYGIENE", f"{name}: {what} {hit[0][:24]!r}"))
    if CLOSING.search(ctx.spec):
        f.append(("G10-HYGIENE", "the spec carries a closing keyword before an issue number"))


def g_ruled(ctx: Ctx, vals: dict[str, str], f: Findings) -> None:
    sec = section(ctx.spec, "R. ")
    listed = [r[0] for r in rows(sec, "BQ")]
    if listed != [f"BQ-{n:02d}" for n in range(1, 26)]:
        f.append(("G11-RULED", f"section R lists {len(listed)} BQ rows, not BQ-01..BQ-25"))
    for r in rows(sec, "BQ"):
        if r[-1] != RULED_STAMP:
            f.append(("G11-RULED", f"{r[0]}: the status is not the ruling stamp"))
    if "<!-- BQ-" in ctx.spec:
        f.append(("G11-RULED", "a BQ marker is left in the spec"))


def g_scope(ctx: Ctx, vals: dict[str, str], f: Findings) -> None:
    for p in ctx.changed:
        if p not in OWN and not (p.startswith(IMG_PREFIX) and p.endswith(".png")):
            f.append(("G12-SCOPE", f"{p} is outside the edit set"))


def g_freeze(ctx: Ctx, vals: dict[str, str], f: Findings) -> None:
    if ctx.merged_spec is None:
        return
    now = set(ctx.spec.split("\n"))
    for ln in ctx.merged_spec.split("\n"):
        if ln.startswith("|") and not ln.startswith("| ---") and ln not in now:
            f.append(("G13-FREEZE", f"a merged row changed: {ln[:48]!r}"))


def g_rerun(ctx: Ctx, vals: dict[str, str], f: Findings) -> None:
    named: set[str] = set()
    for r in rows(ctx.spec, "RR"):
        named |= expand_ids(r[1])
    if not named:
        f.append(("G14-RERUN", "no re-run row found"))
    for fam in RUN_FAMILIES:
        for r in rows(ctx.spec, fam):
            st = status_of(r)
            open_row = st in ("deferred-owned", "not-comparable-yet", "out-of-scope (unbuilt)")
            if open_row and r[0] not in named:
                f.append(("G14-RERUN", f"{r[0]} is {st} and no re-run row names it"))


def g_capture(ctx: Ctx, vals: dict[str, str], f: Findings) -> None:
    named: set[str] = set()
    for r in rows(ctx.spec, "CA"):
        if len(r) != 9:
            f.append(("G15-CAPTURE", f"{r[0]}: {len(r)} cells, not 9"))
            continue
        rel = f"{IMG_DIR}/{r[1].strip('`')}"
        named.add(rel)
        if rel not in ctx.images:
            f.append(("G15-CAPTURE", f"{r[0]}: {rel} does not exist"))
        elif ctx.merged_spec is None and rel not in ctx.changed:
            f.append(("G15-CAPTURE", f"{r[0]}: {rel} is not in the change set"))
        elif (ROOT / rel).read_bytes()[:8] != PNG_MAGIC:
            f.append(("G15-CAPTURE", f"{r[0]}: {rel} is not a PNG"))
        if r[4] not in DPRS or r[5] != "emulated":
            f.append(("G15-CAPTURE", f"{r[0]}: DPR {r[4]!r} or run {r[5]!r} is not ruled"))
    for img in ctx.images:
        if img not in named:
            f.append(("G15-CAPTURE", f"{img} is named by no CA row"))


def g_events(ctx: Ctx, vals: dict[str, str], f: Findings) -> None:
    manifest = d12_events(ctx.d12)
    ev = rows(ctx.spec, "EV")
    names = [r[1].strip("`") for r in ev]
    if not manifest or names != manifest:
        f.append(("G16-EVENTS", "the EV rows are not E12-D12 §13's events in order"))
    for r, name in zip(ev, names, strict=False):
        built = bool(grep_base(ctx.base, f'"{name}"', EVENT_TREES))
        if built == (status_of(r) == "deferred-owned"):
            f.append(("G16-EVENTS", f"{r[0]}: built call site {built}, status {status_of(r)}"))


def g_surfaces(ctx: Ctx, vals: dict[str, str], f: Findings) -> None:
    got = tuple(r[1].split()[0] if len(r) > 1 and r[1] else "" for r in rows(ctx.spec, "SU"))
    if got != SURFACES:
        f.append(("G17-SURFACES", f"the SU rows name {got}, not the seven of T Scope"))


def g_tokens(ctx: Ctx, vals: dict[str, str], f: Findings) -> None:
    tk = {r[0]: r for r in rows(ctx.spec, "TK")}
    ces = show(ctx.base, CODE_KEYS["CES"]) or ""
    named = re.findall(r"`(color\.[\w.]+)`", tk.get("TK-1", ["", ""])[1])
    if not named:
        f.append(("G18-TOKENS", "TK-1 names no token"))
    for tok in named:
        if not shipped(ctx.base, tok):
            f.append(("G18-TOKENS", f"TK-1: {tok} is not shipped in every theme"))
        if f"var(--{tok.replace('.', '-')})" not in ces:
            f.append(("G18-TOKENS", f"TK-1: {tok} is not bound by the card's source"))
    if shipped(ctx.base, "color.chart.background"):
        f.append(("G18-TOKENS", "TK-3: color.chart.background ships; the row is stale"))
    if vals.get("tk.agree") != vals.get("tk.rows"):
        f.append(("G18-TOKENS", "TK-2: a manifest row disagrees with the base"))


GATES: list[tuple[str, Callable[[Ctx, dict[str, str], Findings], None]]] = [
    ("G01-FILLED", g_filled),
    ("G02-AUDIT", g_audit),
    ("G03-CITE", g_cite),
    ("G04-PINS", g_pins),
    ("G05-STATUS", g_status),
    ("G06-GEOM", g_geom),
    ("G07-COPY", g_copy),
    ("G08-REGISTER", g_register),
    ("G09-IDS", g_ids),
    ("G10-HYGIENE", g_hygiene),
    ("G11-RULED", g_ruled),
    ("G12-SCOPE", g_scope),
    ("G13-FREEZE", g_freeze),
    ("G14-RERUN", g_rerun),
    ("G15-CAPTURE", g_capture),
    ("G16-EVENTS", g_events),
    ("G17-SURFACES", g_surfaces),
    ("G18-TOKENS", g_tokens),
]


def run(ctx: Ctx) -> tuple[dict[str, str], Findings]:
    f: Findings = []
    try:
        vals = compute(ctx)
    except RUN_ERRORS as e:  # default-deny: no numbers, every gate that needs them FAILs
        vals = {}
        f.append(("G02-AUDIT", f"the numbers could not be computed: {type(e).__name__}: {e}"))
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
        key = "sha" if m[1] == "SHA" else m[2]
        if key not in vals:
            return m[0]
        return f"{vals[key]} <!-- audit:{key}={vals[key]} -->"

    spec = SLOT.sub(slot, ctx.spec)
    out = []
    for ln in spec.split("\n"):
        for m in list(AUDIT.finditer(ln)):
            key, old = m[1], m[2]
            if key in vals and old != vals[key]:
                ln = ln.replace(
                    f"{old} <!-- audit:{key}={old} -->",
                    f"{vals[key]} <!-- audit:{key}={vals[key]} -->",
                )
        out.append(ln)
    return "\n".join(out)


def repin(ctx: Ctx) -> str:
    lines = [
        "# E12-D13 pins: one cited endpoint per line, `KEY:line sha1-16` of its words at the base.",
        "# Written only by `e12_d13_designqa_audit.py --repin-ruled`.",
    ]
    for key, n in sorted(endpoints(ctx.spec)):
        lines.append(f"{key}:{n} {line_hash(ctx.base_line(key, n) or '')}")
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
        if not done and re.match(rf"^\|\s*{re.escape(row_id)}\s*\|", ln):
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
    ("G01-FILLED", lambda c: _spec(c, c.spec + "\n{{COUNT:mx}}\n")),
    (
        "G02-AUDIT",
        lambda c: _spec(
            c, _swap(c.spec, first(r"<!-- audit:mx=\d+ -->", c.spec), "<!-- audit:mx=999 -->")
        ),
    ),
    (
        "G03-CITE",
        lambda c: dataclasses.replace(
            c,
            pins=re.sub(
                r"^(D08:\d+) [0-9a-f]{16}$",
                r"\1 0000000000000000",
                c.pins,
                count=1,
                flags=re.MULTILINE,
            ),
        ),
    ),
    ("G04-PINS", lambda c: _spec(c, c.spec + "\nSee `D03`:5.\n")),
    ("G05-STATUS", lambda c: _spec(c, set_cell(c.spec, "MX-05", 5, "`postponed`"))),
    (
        "G06-GEOM",
        lambda c: dataclasses.replace(
            c,
            d06=_swap(
                c.d06, "9<!--=LADDER:body.at-sample-1-->", "8<!--=LADDER:body.at-sample-1-->"
            ),
        ),
    ),
    ("G07-COPY", lambda c: _spec(c, _swap(c.spec, "d08:W-21, d08:W-22", "d08:W-13, d08:W-22"))),
    ("G08-REGISTER", lambda c: _spec(c, set_cell(c.spec, "DF-2", 2, "Severe"))),
    ("G09-IDS", lambda c: _spec(c, _swap(c.spec, "| MX-03 |", "| MX-02 |"))),
    ("G10-HYGIENE", lambda c: _spec(c, c.spec + "\n" + BANNED[9].upper() + "\n")),
    ("G11-RULED", lambda c: _spec(c, _swap(c.spec, f"| {RULED_STAMP} |", "| pending |"))),
    ("G12-SCOPE", lambda c: dataclasses.replace(c, changed=[*c.changed, "docs/plan/14-x.md"])),
    (
        "G13-FREEZE",
        lambda c: dataclasses.replace(c, merged_spec="| MX-99 | a merged row since changed |\n"),
    ),
    ("G14-RERUN", lambda c: _spec(c, _swap(c.spec, "| RR-11 | MX-17 ", "| RR-11 | MX-99 "))),
    (
        "G15-CAPTURE",
        lambda c: _spec(
            c, _swap(c.spec, "E12-D13-07-scr041-host-light.png`", "E12-D13-07-missing.png`")
        ),
    ),
    ("G16-EVENTS", lambda c: _spec(c, set_cell(c.spec, "EV-06", 3, "`deferred-owned`"))),
    ("G17-SURFACES", lambda c: _spec(c, _swap(c.spec, "| SU-5 | SCR-045", "| SU-5 | SCR-046"))),
    (
        "G18-TOKENS",
        lambda c: _spec(
            c,
            _swap(c.spec, "binds `color.status.danger.strong`", "binds `color.status.danger.loud`"),
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
    if {code for code, _ in GATES} - {code for code, _ in MUTATIONS}:
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
