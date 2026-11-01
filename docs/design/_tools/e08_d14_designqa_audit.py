"""E08-D14 (#277) audit: the design QA of the implemented E08 market-data surfaces.

Stdlib only, offline (`python3 -I -B`). It reads the spec, the pins file and the image folder from
the working tree, and every cited or lifted file AS TEXT at the merge-base with `origin/main`
(`git show`): E08-D13's state table and copy deck, the token JSON, the built source of SCR-102,
SCR-041 and SCR-152, the e2e a11y screen list and the VR baseline names. It runs no repo code and
drives no browser. Default-deny: a gate that cannot read its input FAILs.

Two modes, chosen by content, never by flag. PR-1 mode: the spec is absent at the merge-base; the
diff may touch only the own files (the spec, this tool, the pins file, the image folder). Post-merge
mode: the spec ships at the merge-base; every merged table row stands unchanged.

Gates (each FAIL led by its code):

- [G01-AUDIT] every `<!-- audit:key=value -->` marker is a known key and equals the recomputed value.
- [G02-CITE] every cited endpoint resolves at the base to a non-blank line, and its pin matches.
- [G03-PINS] the pins file and the spec's cited endpoints match both ways.
- [G04-COPY] the CP rows list every in-scope deck key the built strings do not hold, once each, and
  no key they hold; a CP finding is a DF row or "no divergence:" with a reason.
- [G05-TOKEN] the TK rows cite exactly the lines of the literal scan's hits; no reference is unresolved.
- [G06-CONTRAST] a CN pair under its bar in any theme names a DF row; a pair at the bar names none.
- [G07-STATES] the ST rows are E08-D13 section 5.4's SCR-102 and SCR-152 rows, once each, in order,
  each status from the ruled set; a "not built" status names a DF row; "reached" cites code or a suite.
- [G08-NI] the NI rows are the six unbuilt surfaces, each with its section 5.4 row count and an open
  owner issue.
- [G09-FINDINGS] every DF row has a class, severity and target from the ruled sets, an owner of the
  form `E08-Dnn · area/<slug>` (or `E17-D02 ·`), a cited sentence and, for Blocking and Major, a
  reason; a Blocking row is listed as an IS row.
- [G10-CLASS] every DF id named anywhere is a row of the register, and every row is named outside it.
- [G11-IDS] the ids of each table family are 1..n in order.
- [G12-HYGIENE] no local path, home directory, host name, agent or lane name, URL or closing keyword
  before an issue number in the own text files.
- [G13-SCOPE] the changed paths are the own files only.
- [G14-WALK] the owner checklist holds at most ten items.
- [G15-BQ] section R lists BQ-01..BQ-15 once each.
- [G16-IMG] every embedded image exists in the image folder and every image there is embedded.
- [G17-FREEZE] post-merge mode: every merged table row stands unchanged.
- [G18-ROUTE] every RT row targets an open owner of the ruled set; every DF target that is an issue
  is named by an RT row.

`--json` prints the numbers; `--check` exits 1 on any FAIL; `--self-test` applies one mutation per
gate to an in-memory copy and passes only when each adds FAILs of its gate's code and the base run is
clean; `--repin-ruled` rewrites the pins file from the spec's cites and is its only writer.

Usage: python3 -I -B docs/design/_tools/e08_d14_designqa_audit.py [--check] [--json] [--self-test]
       [--repin-ruled]
"""

from __future__ import annotations

import argparse
import dataclasses
import hashlib
import json
import re
import subprocess
import sys
from collections.abc import Callable
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[3]
SPEC_REL = "docs/design/E08/E08-D14.md"
TOOL_REL = "docs/design/_tools/e08_d14_designqa_audit.py"
PINS_REL = "docs/design/_tools/e08_d14_ruled_pins.txt"
IMG_DIR = "docs/design/E08/img/e08-d14"
OWN = {SPEC_REL, TOOL_REL, PINS_REL}
UPSTREAM = "origin/main"
DECK_REL = "docs/design/E08/E08-D13-copy.json"
DS_JSON_DIR = "packages/ui/tokens"
VR_DIR = "packages/ui/vr/baselines"

WEB = "apps/web/src/"
SRCH = WEB + "features/symbol-search/"
SHELL = WEB + "features/app-shell/"
UI = "packages/ui/src/components/"
KEYS: dict[str, str] = {
    "D05": "docs/design/E08/E08-D05.md",
    "D06": "docs/design/E08/E08-D06.md",
    "D08": "docs/design/E08/E08-D08.md",
    "D09": "docs/design/E08/E08-D09.md",
    "D11": "docs/design/E08/E08-D11.md",
    "D12": "docs/design/E08/E08-D12.md",
    "D13": "docs/design/E08/E08-D13.md",
    "E17D2": "docs/design/E17/E17-D02.md",
    "E09D11": "docs/design/E09/E09-D11.md",
    "SS": SRCH + "SymbolSearch.tsx",
    "QS": SRCH + "QuickSwitcher.tsx",
    "CPY": SRCH + "copy.ts",
    "SDECK": SRCH + "searchDeck.tsx",
    "SVIEW": SRCH + "searchView.ts",
    "SSESS": SRCH + "searchSession.ts",
    "LAYOUT": SHELL + "ShellLayout.tsx",
    "REGION": SHELL + "ConnectionRegion.tsx",
    "RSLOT": SHELL + "ConnectionRegionSlot.tsx",
    "RVIEW": WEB + "lib/ws/state/connectionRegion.ts",
    "CHIP": SHELL + "ConnectionStatus.tsx",
    "CSLOT": SHELL + "ConnectionStatusSlot.tsx",
    "SSI": UI + "SymbolSearchInput.tsx",
    "EMPTY": UI + "EmptyState.tsx",
    "DLGCSS": UI + "dialog.css",
    "POPCSS": UI + "popover.css",
    "WLCSS": UI + "watchlistrow.css",
    "FLCSS": UI + "fuzzylist.css",
    "SSCSS": UI + "symbolsearch.css",
    "A11YS": "apps/web/e2e/a11y/screens.ts",
    "SST": "apps/web/test/features/symbol-search/SymbolSearch.test.tsx",
    "QST": "apps/web/test/features/symbol-search/QuickSwitcher.test.tsx",
    "REGT": "apps/web/test/features/app-shell/connection-region.test.tsx",
}
CODE_KEYS = {
    k for k, v in KEYS.items() if v.startswith(("apps/", "packages/")) and "/test/" not in v
}
SUITE_KEYS = {"SST", "QST", "REGT"}

# The literal scan: the built E08 surfaces (TS / TSX) and the E08 component CSS of packages/ui.
SCAN_TS = ["SS", "QS", "CPY", "SDECK", "SVIEW", "REGION", "RSLOT", "RVIEW", "CHIP", "CSLOT"]
SCAN_CSS = [
    UI + n
    for n in (
        "confidencedots.css",
        "freshness.css",
        "fuzzylist.css",
        "symbolpicker.css",
        "symbolsearch.css",
        "watchlistrow.css",
        "watchlisttabs.css",
        "emptystate.css",
    )
]
# Copy diff: the deck sections of each built surface and the files whose strings it renders.
COPY_SCOPE: dict[str, tuple[tuple[str, ...], list[str]]] = {
    "SCR-102/041": (
        ("d05.",),
        ["CPY", "SS", "QS", "SDECK", "SVIEW", "SSI", "EMPTY"],
    ),
    "SCR-152": (
        ("e17d2.A.", "e17d2.B.", "e17d2.E.", "e17d2.F.", "e17d2.G.", "e17d2.R."),
        ["REGION", "RSLOT", "RVIEW", "CHIP", "CSLOT"],
    ),
}
THEMES = {
    "dark": ("primitives", "semantic-dark"),
    "light": ("primitives", "semantic-dark", "semantic-light"),
    "hc": ("primitives", "semantic-dark", "semantic-hc"),
}
# CN-n: foreground, background, bar (text 4.5, non-text 3). A `@muted` foreground is the token at
# `opacity.muted` over the background (the F-01 fallback, `WLCSS`).
CN_PAIRS: dict[str, tuple[str, str, str]] = {
    "cn1": ("color.text.primary", "color.status.danger.subtle", "text"),
    "cn2": ("color.text.inverse", "color.status.danger.strong", "text"),
    "cn3": ("color.text.primary", "color.status.warning.subtle", "text"),
    "cn4": ("color.status.danger.strong", "color.status.danger.subtle", "text"),
    "cn5": ("color.status.warning.strong", "color.status.warning.subtle", "non-text"),
    "cn6": ("color.text.primary", "color.surface.raised", "text"),
    "cn7": ("color.status.info.default", "color.status.info.subtle", "non-text"),
    "cn8": ("color.text.secondary", "color.surface.overlay", "text"),
    "cn9": ("color.status.warning.strong", "color.surface.overlay", "non-text"),
    "cn10": ("color.text.primary@muted", "color.surface.sunken", "text"),
}
BARS = {"text": 4.5, "non-text": 3.0}
ST_SCREENS = ("SCR-102", "SCR-152")
NI_SCREENS = {
    "SCR-100": "#4702",
    "SCR-101": "#4702",
    "SCR-103": "#4704",
    "SCR-104": "#4705",
    "SCR-147": "#5207",
    "SCR-151": "#178",
}
ST_STATUS = {"reached", "reached in part", "not built", "other surface", "owner-run"}
CLASSES = ("implementation defect", "accepted divergence", "specification gap")
SEVERITIES = ("Blocking", "Major", "Minor", "Info")
OPEN_OWNERS = {
    "#282",
    "#304",
    "#408",
    "#451",
    "#566",
    "#1028",
    "#2701",
    "#4702",
    "#4704",
    "#4705",
    "#5111",
    "#5207",
    "#178",
}
TARGETS_EXTRA = {"register", "issue (listed)"}
BQ_COUNT = 15
FAMILIES = (
    "BQ", "RN", "FS", "ST", "NI", "TK", "CN", "CP", "CM", "IX", "AN", "MO", "AX", "T2", "SC",
    "DF", "DR", "RT", "IS", "OR",
)  # fmt: skip

KEY_RE = r"[A-Z][A-Z0-9]{1,7}|\d\d"
MD_CITE = re.compile(
    rf"`(?P<key>{KEY_RE})`:(?P<a>\d+)(?:[–-](?P<b>\d+))?(?P<more>(?:, :\d+(?:[–-]\d+)?)*)"
)
MORE = re.compile(r":(\d+)(?:[–-](\d+))?")
MARK = re.compile(r"<!-- audit:(?P<k>[a-z0-9.\-]+)=(?P<v>[^>]*?) -->")


# ------------------------------------------------------------------------------------ helpers


def git(*args: str) -> str:
    r = subprocess.run(["git", *args], cwd=ROOT, capture_output=True, text=True, check=False)
    return r.stdout if r.returncode == 0 else ""


def merge_base() -> str:
    return git("merge-base", "HEAD", UPSTREAM).strip() or git("rev-parse", "HEAD").strip()


def show(rev: str, rel: str) -> str | None:
    r = subprocess.run(
        ["git", "show", f"{rev}:{rel}"], cwd=ROOT, capture_output=True, text=True, check=False
    )
    return r.stdout if r.returncode == 0 else None


def plan_path(nn: str, rev: str) -> str | None:
    for name in git("ls-tree", "--name-only", rev, "docs/plan/").split():
        if name.startswith(f"docs/plan/{nn}-") and name.endswith(".md"):
            return name
    return None


def key_path(key: str, rev: str) -> str | None:
    return plan_path(key, rev) if key.isdigit() else KEYS.get(key)


def read(rel: str) -> str:
    p = ROOT / rel
    return p.read_text(encoding="utf-8") if p.exists() else ""


def cells(line: str) -> list[str]:
    return [c.strip() for c in line.strip().strip("|").split("|")]


def rows(text: str, family: str) -> list[list[str]]:
    pat = re.compile(rf"^\|\s*{re.escape(family)}-\d+\s*\|")
    return [cells(ln) for ln in text.split("\n") if pat.match(ln)]


def norm(s: str) -> str:
    return re.sub(r"\s+", " ", s.replace("`", "").replace("*", "")).strip()


def line_hash(s: str) -> str:
    return hashlib.sha1(norm(s).encode("utf-8")).hexdigest()[:16]


def cite_spans(text: str) -> list[tuple[str, int, int]]:
    out: list[tuple[str, int, int]] = []
    for m in MD_CITE.finditer(text):
        a = int(m["a"])
        out.append((m["key"], a, int(m["b"]) if m["b"] else a))
        for mm in MORE.finditer(m["more"] or ""):
            x = int(mm[1])
            out.append((m["key"], x, int(mm[2]) if mm[2] else x))
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


def ids_in(text: str, fam: str) -> list[int]:
    out: list[int] = []
    for m in re.finditer(rf"\b{fam}-(\d+)(?:\.\.{fam}-(\d+))?\b", text):
        a = int(m[1])
        out.extend(range(a, int(m[2]) + 1) if m[2] else [a])
    return out


def strip_comments(text: str) -> str:
    text = re.sub(r"/\*.*?\*/", lambda m: "\n" * m[0].count("\n"), text, flags=re.DOTALL)
    return re.sub(r"(?m)(^|[^:\"'`])//.*$", r"\1", text)


def literals(text: str) -> list[str]:
    """Every string, template (`${…}` as a fill) and JSX text run, comments out."""
    t = strip_comments(text)
    out: list[str] = []
    for m in re.finditer(r'"((?:[^"\\\n]|\\.)*)"|\'((?:[^\'\\\n]|\\.)*)\'|`((?:[^`\\]|\\.)*)`', t):
        s = next(g for g in m.groups() if g is not None)
        out.append(re.sub(r"\$\{(?:[^{}]|\{[^{}]*\})*\}", "\x00", s))
    out.extend(s.strip() for s in re.findall(r">([^<>{}]+)<", t) if s.strip())
    return out


VALUE = r"(<[^>]*>|\{[^}]*\}|Chart \d+|[A-Z0-9]{2,}USDT|'[a-z]+'|\d+(?:[.:,]\d+)*)"


def deck_rx(text: str) -> re.Pattern[str]:
    parts = re.split(VALUE, text)
    rx = "".join(re.escape(p) if i % 2 == 0 else "(?:.+?)" for i, p in enumerate(parts))
    return re.compile(rx, re.DOTALL)


def holds(text: str, lits: list[str]) -> bool:
    """A deck string is held when a built literal is it, with fills for its values; a string of
    20 or more characters may also stand inside a longer literal."""
    rx = deck_rx(text)
    for lit in lits:
        cand = lit.replace("\x00", "\x01")
        if rx.fullmatch(cand) or (len(text) >= 20 and rx.search(cand)):
            return True
    return False


def flat_tokens(d: Any, path: tuple[str, ...] = ()) -> dict[str, Any]:
    out: dict[str, Any] = {}
    if isinstance(d, dict):
        if "$value" in d:
            out[".".join(path)] = d["$value"]
        else:
            for k, v in d.items():
                if not k.startswith("$"):
                    out.update(flat_tokens(v, (*path, k)))
    return out


def section(text: str, heading_prefix: str) -> str:
    lines = text.split("\n")
    out: list[str] = []
    on = False
    level = 0
    for ln in lines:
        m = re.match(r"^(#+) ", ln)
        if not on and m and ln[m.end() :].startswith(heading_prefix):
            on, level = True, len(m[1])
            continue
        if on and m and len(m[1]) <= level:
            break
        if on:
            out.append(ln)
    return "\n".join(out)


# ------------------------------------------------------------------------------------ context


@dataclasses.dataclass
class Ctx:
    spec: str
    pins: str
    tool: str
    base: str
    changed: list[str]
    merged_spec: str | None
    sources: dict[str, str]
    deck: dict[str, Any]
    tokens: dict[str, dict[str, Any]]
    css: dict[str, str]
    vr: list[str]
    images: list[str]

    def base_text(self, key: str) -> str | None:
        rel = key_path(key, self.base)
        if rel is None:
            return None
        if rel not in self.sources:
            self.sources[rel] = show(self.base, rel) or ""
        return self.sources[rel] or None

    def base_line(self, key: str, n: int) -> str | None:
        text = self.base_text(key)
        if text is None:
            return None
        lines = text.split("\n")
        return lines[n - 1] if 0 < n <= len(lines) else None


def build_ctx() -> Ctx:
    base = merge_base()
    changed = sorted(
        {
            *git("diff", "--name-only", base).split(),
            *git("ls-files", "-o", "--exclude-standard").split(),
        }
    )
    sources = {rel: show(base, rel) or "" for rel in KEYS.values()}
    tokens: dict[str, dict[str, Any]] = {}
    for theme, sets in THEMES.items():
        flat: dict[str, Any] = {}
        for s in sets:
            flat.update(
                flat_tokens(json.loads(show(base, f"{DS_JSON_DIR}/{s}.tokens.json") or "{}"))
            )
        tokens[theme] = flat
    img = ROOT / IMG_DIR
    return Ctx(
        spec=read(SPEC_REL),
        pins=read(PINS_REL),
        tool=read(TOOL_REL),
        base=base,
        changed=changed,
        merged_spec=show(base, SPEC_REL),
        sources=sources,
        deck=json.loads(show(base, DECK_REL) or "{}").get("strings", {}),
        tokens=tokens,
        css={rel: show(base, rel) or "" for rel in SCAN_CSS},
        vr=git("ls-tree", "--name-only", base, VR_DIR + "/").split(),
        images=sorted(p.name for p in img.glob("*.png")) if img.is_dir() else [],
    )


# ------------------------------------------------------------------------------------ compute


# A `* 1px` is the unit a unitless border token is multiplied by, not a value of its own.
LITERAL = re.compile(
    r"(?<![\w-])(?<!\* )(\d+(?:\.\d+)?px|#[0-9a-fA-F]{3,8}\b|rgba?\(|hsla?\(|transparent\b)"
    r"|fontWeight:\s*\d+|font-weight:\s*\d+"
)


def literal_hits(ctx: Ctx) -> list[tuple[str, int, str]]:
    """(key or css path, line, value) per style literal outside comments and forced-colors blocks."""
    out: list[tuple[str, int, str]] = []
    for key in SCAN_TS:
        text = strip_comments(ctx.sources[KEYS[key]])
        for n, ln in enumerate(text.split("\n"), 1):
            for m in LITERAL.finditer(ln):
                out.append((key, n, m[0]))
    for rel, text in ctx.css.items():
        t = strip_comments(text)
        depth = 0
        forced = False
        for n, ln in enumerate(t.split("\n"), 1):
            if "@media (forced-colors" in ln:
                forced, depth = True, 0
            if forced:
                depth += ln.count("{") - ln.count("}")
                if depth <= 0 and "}" in ln:
                    forced = False
                continue
            for m in LITERAL.finditer(ln):
                out.append((rel.rsplit("/", 1)[1], n, m[0]))
    return out


def var_refs(ctx: Ctx) -> tuple[int, list[str]]:
    names = {k.replace(".", "-") for k in ctx.tokens["dark"]}
    seen: list[str] = []
    for key in SCAN_TS:
        seen += re.findall(r"var\(--([a-z0-9-]+)\)", strip_comments(ctx.sources[KEYS[key]]))
    composite = re.compile(r"-(font-family|font-size|font-weight|line-height|letter-spacing)$")
    unresolved = sorted(
        {
            n
            for n in seen
            if n not in names
            and composite.sub("", n) not in names
            and not n.startswith(("cv-", "border-ink"))
        }
    )
    return len(seen), unresolved


def hex_of(ctx: Ctx, theme: str, token: str) -> str:
    flat = ctx.tokens[theme]
    v: Any = flat[token]
    for _ in range(12):
        if isinstance(v, str) and v.startswith("{") and v.endswith("}"):
            v = flat[v[1:-1]]
        else:
            break
    return str(v)


def rgb(h: str) -> tuple[float, float, float]:
    h = h.lstrip("#")[:6]
    return (int(h[0:2], 16), int(h[2:4], 16), int(h[4:6], 16))


def luminance(c: tuple[float, float, float]) -> float:
    lin = [
        (x / 255) / 12.92 if x / 255 <= 0.03928 else ((x / 255 + 0.055) / 1.055) ** 2.4 for x in c
    ]
    return 0.2126 * lin[0] + 0.7152 * lin[1] + 0.0722 * lin[2]


def ratio(a: tuple[float, float, float], b: tuple[float, float, float]) -> float:
    la, lb = sorted((luminance(a), luminance(b)), reverse=True)
    return (la + 0.05) / (lb + 0.05)


def contrast(ctx: Ctx) -> dict[str, float]:
    out: dict[str, float] = {}
    for key, (fg, bg, _bar) in CN_PAIRS.items():
        for theme in THEMES:
            back = rgb(hex_of(ctx, theme, bg))
            if fg.endswith("@muted"):
                a = float(hex_of(ctx, theme, "opacity.muted"))
                front = rgb(hex_of(ctx, theme, fg[: -len("@muted")]))
                fore = (
                    a * front[0] + (1 - a) * back[0],
                    a * front[1] + (1 - a) * back[1],
                    a * front[2] + (1 - a) * back[2],
                )
            else:
                fore = rgb(hex_of(ctx, theme, fg))
            out[f"{key}.{theme}"] = ratio(fore, back)
    return out


def d13_rows(ctx: Ctx, screen: str) -> list[list[str]]:
    text = ctx.base_text("D13") or ""
    return [cells(ln) for ln in text.split("\n") if ln.startswith(f"| `{screen}/")]


def deck_status(ctx: Ctx) -> dict[str, bool]:
    out: dict[str, bool] = {}
    for prefixes, keys in COPY_SCOPE.values():
        lits: list[str] = []
        for k in keys:
            lits += literals(ctx.sources[KEYS[k]])
        for dk, v in ctx.deck.items():
            if dk.startswith(prefixes):
                out[dk] = holds(v["text"], lits)
    return out


def axe_ids(ctx: Ctx) -> list[str]:
    m = re.search(r"PR_IDS[^=]*=\s*new Set\(\[([^\]]*)\]", ctx.sources[KEYS["A11YS"]])
    return re.findall(r'"([^"]+)"', m[1]) if m else []


def motion_hits(ctx: Ctx) -> int:
    n = 0
    for key in SCAN_TS:
        n += len(
            re.findall(
                r"\btransition\s*:|\banimation\s*:|@keyframes",
                strip_comments(ctx.sources[KEYS[key]]),
            )
        )
    return n


def df_rows(spec: str) -> list[list[str]]:
    return rows(section(spec, "12."), "DF")


def compute(ctx: Ctx) -> dict[str, str]:
    v: dict[str, str] = {}
    hits = literal_hits(ctx)
    refs, unresolved = var_refs(ctx)
    v["tk.files"] = str(len(SCAN_TS) + len(SCAN_CSS))
    v["tk.refs"] = str(refs)
    v["tk.unresolved"] = str(len(unresolved))
    v["tk.literals"] = str(len(hits))
    for key, r in contrast(ctx).items():
        v[key] = f"{r:.2f}:1"
    below = []
    for key, (_fg, _bg, bar) in CN_PAIRS.items():
        th = [t for t in THEMES if contrast(ctx)[f"{key}.{t}"] < BARS[bar]]
        if th:
            below.append(f"CN-{key[2:]} ({', '.join(th)})")
    v["cn.below"] = "; ".join(below) or "none"
    for scr in ST_SCREENS:
        v[f"st.{scr.lower()}"] = str(len(d13_rows(ctx, scr)))
    for scr in NI_SCREENS:
        v[f"ni.{scr.lower()}"] = str(len(d13_rows(ctx, scr)))
    st = rows(section(ctx.spec, "4."), "ST")
    v["st"] = str(len(st))
    for s in ("reached", "reached in part", "not built", "other surface", "owner-run"):
        v[f"st.{s.replace(' ', '-')}"] = str(sum(1 for r in st if r[6] == s))
    status = deck_status(ctx)
    for scope, (prefixes, _k) in COPY_SCOPE.items():
        tag = "d05" if scope.startswith("SCR-102") else "e17d2"
        keys = [k for k in status if k.startswith(prefixes)]
        v[f"deck.{tag}"] = str(len(keys))
        v[f"deck.{tag}.held"] = str(sum(1 for k in keys if status[k]))
        v[f"deck.{tag}.missed"] = str(sum(1 for k in keys if not status[k]))
    stems = [
        "confidencedots",
        "emptystate",
        "freshnessmarker",
        "fuzzylist",
        "symbolpicker",
        "symbolsearchinput",
        "watchlistgrouptabs",
        "watchlistrow",
    ]
    vr = [n for n in ctx.vr if any(f"-{s}--" in n for s in stems)]
    v["vr.e08"] = str(len(vr))
    v["ax.ids"] = ", ".join(axe_ids(ctx))
    v["mo.hits"] = str(motion_hits(ctx))
    dfs = df_rows(ctx.spec)
    v["df"] = str(len(dfs))
    for sev in SEVERITIES:
        v[f"df.{sev.lower()}"] = str(sum(1 for r in dfs if len(r) > 2 and r[2] == sev))
    for cls, tag in zip(CLASSES, ("defect", "accepted", "gap"), strict=True):
        v[f"df.{tag}"] = str(sum(1 for r in dfs if len(r) > 1 and r[1] == cls))
    v["img"] = str(len(ctx.images))
    return v


# ------------------------------------------------------------------------------------ gates

Findings = list[str]


def g_audit(ctx: Ctx, vals: dict[str, str], f: Findings) -> None:
    for m in MARK.finditer(ctx.spec):
        k, got = m["k"], m["v"]
        if k not in vals:
            f.append(f"[G01-AUDIT] unknown marker key {k}")
        elif vals[k] != got:
            f.append(f"[G01-AUDIT] {k}: marker {got!r} != computed {vals[k]!r}")


def g_cite(ctx: Ctx, vals: dict[str, str], f: Findings) -> None:
    pins = parse_pins(ctx.pins)
    for key, n in sorted(endpoints(ctx.spec)):
        line = ctx.base_line(key, n)
        if line is None or not line.strip():
            f.append(f"[G02-CITE] `{key}`:{n} does not resolve to a non-blank line at the base")
        elif (key, n) in pins and pins[(key, n)] != line_hash(line):
            f.append(f"[G02-CITE] `{key}`:{n} moved: its pin no longer matches")


def g_pins(ctx: Ctx, vals: dict[str, str], f: Findings) -> None:
    pins = set(parse_pins(ctx.pins))
    cited = endpoints(ctx.spec)
    for k, n in sorted(cited - pins):
        f.append(f"[G03-PINS] `{k}`:{n} is cited but not pinned")
    for k, n in sorted(pins - cited):
        f.append(f"[G03-PINS] `{k}`:{n} is pinned but not cited")


def g_copy(ctx: Ctx, vals: dict[str, str], f: Findings) -> None:
    status = deck_status(ctx)
    listed: dict[str, int] = {}
    for r in rows(section(ctx.spec, "6."), "CP"):
        for k in re.findall(r"`((?:d05|e17d2)\.[A-Za-z0-9.\-]+)`", r[1]):
            listed[k] = listed.get(k, 0) + 1
        fin = r[-1]
        if not (re.search(r"\bDF-\d+", fin) or fin.startswith("no divergence:")):
            f.append(f"[G04-COPY] {r[0]}: its finding is neither a DF row nor 'no divergence:'")
    for k, held in status.items():
        n = listed.get(k, 0)
        if not held and n != 1:
            f.append(f"[G04-COPY] deck key {k} is not held by the build and is listed {n} times")
        if held and n:
            f.append(f"[G04-COPY] deck key {k} is held by the build but listed as a difference")
    for k in listed:
        if k not in status:
            f.append(f"[G04-COPY] {k} is not an in-scope deck key")


def g_token(ctx: Ctx, vals: dict[str, str], f: Findings) -> None:
    hits = {(k, n) for k, n, _v in literal_hits(ctx)}
    cited: set[tuple[str, int]] = set()
    for r in rows(section(ctx.spec, "5."), "TK"):
        where = r[2]
        for key, a, b in cite_spans(where):
            cited.update((key, x) for x in range(a, b + 1))
        for name, ln in re.findall(r"`([a-z]+\.css)`:(\d+)", where):
            cited.add((name, int(ln)))
    css_hits = {h for h in hits}
    for h in sorted(css_hits - cited):
        f.append(f"[G05-TOKEN] literal hit {h[0]}:{h[1]} is not cited by a TK row")
    for c in sorted(cited - css_hits):
        f.append(f"[G05-TOKEN] TK cites {c[0]}:{c[1]}, which is no literal hit")
    if vals["tk.unresolved"] != "0":
        f.append(f"[G05-TOKEN] {vals['tk.unresolved']} unresolved token references")


def g_contrast(ctx: Ctx, vals: dict[str, str], f: Findings) -> None:
    cn = contrast(ctx)
    for r in rows(section(ctx.spec, "5."), "CN"):
        key = "cn" + r[0].split("-")[1]
        if key not in CN_PAIRS:
            f.append(f"[G06-CONTRAST] {r[0]} is no computed pair")
            continue
        bar = BARS[CN_PAIRS[key][2]]
        under = any(cn[f"{key}.{t}"] < bar for t in THEMES)
        names = bool(re.search(r"\bDF-\d+", r[-1]))
        if under and not names:
            f.append(f"[G06-CONTRAST] {r[0]} is under its bar and names no DF row")
        if not under and names:
            f.append(f"[G06-CONTRAST] {r[0]} meets its bar but names a DF row")


def g_states(ctx: Ctx, vals: dict[str, str], f: Findings) -> None:
    want = [r[0].strip("`") for s in ST_SCREENS for r in d13_rows(ctx, s)]
    st = rows(section(ctx.spec, "4."), "ST")
    got = [r[2].strip("`") for r in st]
    if got != want:
        f.append(
            f"[G07-STATES] the ST rows' test ids differ from D13 section 5.4 ({len(got)} vs {len(want)})"
        )
    for r in st:
        if r[6] not in ST_STATUS:
            f.append(f"[G07-STATES] {r[0]}: status {r[6]!r} is not ruled")
        if r[6] == "not built" and not re.search(r"\bDF-\d+", r[-1]):
            f.append(f"[G07-STATES] {r[0]} is not built and names no DF row")
        if r[6].startswith("reached"):
            keys = {k for k, _a, _b in cite_spans(r[7])}
            if not keys & (CODE_KEYS | SUITE_KEYS) and "RN-" not in r[7]:
                f.append(f"[G07-STATES] {r[0]} is reached with no code, suite or run cite")


def g_ni(ctx: Ctx, vals: dict[str, str], f: Findings) -> None:
    ni = rows(section(ctx.spec, "3."), "NI")
    got = {r[1]: r for r in ni}
    if sorted(got) != sorted(NI_SCREENS):
        f.append(f"[G08-NI] the NI rows are {sorted(got)}, not the six unbuilt surfaces")
    for scr, owner in NI_SCREENS.items():
        r = got.get(scr)
        if r is None:
            continue
        if owner not in r[-1]:
            f.append(f"[G08-NI] {r[0]} ({scr}) does not name its owner {owner}")
        if f"<!-- audit:ni.{scr.lower()}=" not in "|".join(r):
            f.append(f"[G08-NI] {r[0]} ({scr}) carries no computed state count")


def g_findings(ctx: Ctx, vals: dict[str, str], f: Findings) -> None:
    is_rows = {r[1] for r in rows(section(ctx.spec, "14."), "IS")}
    for r in df_rows(ctx.spec):
        if len(r) < 9:
            f.append(f"[G09-FINDINGS] {r[0]} has {len(r)} cells, not 9")
            continue
        _id, cls, sev, _clause, owner, target, _prio, sentence, reason = r[:9]
        if cls not in CLASSES:
            f.append(f"[G09-FINDINGS] {r[0]}: class {cls!r}")
        if sev not in SEVERITIES:
            f.append(f"[G09-FINDINGS] {r[0]}: severity {sev!r}")
        if not re.fullmatch(r"`E(08-D\d\d|17-D02) · area/[a-z-]+`", owner):
            f.append(f"[G09-FINDINGS] {r[0]}: owner {owner!r}")
        tgt = [t.strip() for t in target.split(";")]
        for t in tgt:
            if t not in OPEN_OWNERS and t not in TARGETS_EXTRA:
                f.append(f"[G09-FINDINGS] {r[0]}: target {t!r} is not an open owner")
        if not cite_spans(sentence) and not re.search(
            r"\b(RN|FS|ST|TK|CN|CP|IX|AN|MO|AX)-\d+", sentence
        ):
            f.append(f"[G09-FINDINGS] {r[0]}: the sentence carries no cite")
        if sev in ("Blocking", "Major") and reason in ("", "—"):
            f.append(f"[G09-FINDINGS] {r[0]}: a {sev} row needs a reason")
        if sev == "Blocking" and r[0] not in is_rows:
            f.append(f"[G09-FINDINGS] {r[0]} is Blocking but not listed as an IS row")


def g_class(ctx: Ctx, vals: dict[str, str], f: Findings) -> None:
    reg = section(ctx.spec, "12.")
    ids = {int(r[0].split("-")[1]) for r in df_rows(ctx.spec)}
    outside = ctx.spec.replace(reg, "")
    for n in sorted(set(ids_in(ctx.spec, "DF")) - ids):
        f.append(f"[G10-CLASS] DF-{n} is named but is no register row")
    for n in sorted(ids - set(ids_in(outside, "DF"))):
        f.append(f"[G10-CLASS] DF-{n} is named nowhere outside the register")


def g_ids(ctx: Ctx, vals: dict[str, str], f: Findings) -> None:
    for fam in FAMILIES:
        got = [int(r[0].split("-")[1]) for r in rows(ctx.spec, fam)]
        if got and got != list(range(1, len(got) + 1)):
            f.append(f"[G11-IDS] the {fam} rows are not 1..{len(got)} in order")


HYGIENE = [
    (re.compile(r"/home/|~/|\bwt/i\d+|scratch-"), "a local path"),
    (re.compile(r"https?://"), "a URL"),
    (
        re.compile(r"\b(hcl|hpe|vps)-?worker|\bworker-\d|\bRelayRoom\b", re.IGNORECASE),
        "a lane or agent name",
    ),
    (
        re.compile(r"\b(close[sd]?|fix(e[sd])?|resolve[sd]?)\s+#\d+", re.IGNORECASE),
        "a closing keyword before an issue number",
    ),
    (re.compile(r"\b[a-z0-9-]+\.(local|lan|internal)\b"), "a host name"),
]


def g_hygiene(ctx: Ctx, vals: dict[str, str], f: Findings) -> None:
    for rel, text in ((SPEC_REL, ctx.spec), (PINS_REL, ctx.pins)):
        for rx, what in HYGIENE:
            m = rx.search(text)
            if m:
                f.append(f"[G12-HYGIENE] {rel}: {what} ({m[0]!r})")
    body = ctx.tool.split("HYGIENE = [", 1)[0] + ctx.tool.split("def g_hygiene", 1)[-1]
    for rx, what in HYGIENE[:3]:
        m = rx.search(body)
        if m:
            f.append(f"[G12-HYGIENE] {TOOL_REL}: {what} ({m[0]!r})")


def g_scope(ctx: Ctx, vals: dict[str, str], f: Findings) -> None:
    for rel in ctx.changed:
        if rel not in OWN and not (rel.startswith(IMG_DIR + "/") and rel.endswith(".png")):
            f.append(f"[G13-SCOPE] {rel} is outside this ticket's own files")


def g_walk(ctx: Ctx, vals: dict[str, str], f: Findings) -> None:
    block = ctx.spec.split("**The owner checklist**", 1)
    items = re.findall(r"(?m)^\d+\. ", block[1].split("\n## ", 1)[0]) if len(block) == 2 else []
    if not items or len(items) > 10:
        f.append(f"[G14-WALK] the owner checklist holds {len(items)} items (1..10)")


def g_bq(ctx: Ctx, vals: dict[str, str], f: Findings) -> None:
    got = [int(r[0].split("-")[1]) for r in rows(section(ctx.spec, "R."), "BQ")]
    if got != list(range(1, BQ_COUNT + 1)):
        f.append(f"[G15-BQ] section R lists {got}, not BQ-01..BQ-{BQ_COUNT:02d}")


def g_img(ctx: Ctx, vals: dict[str, str], f: Findings) -> None:
    embedded = set(re.findall(r"img/e08-d14/([a-z0-9.\-]+\.png)", ctx.spec))
    for n in sorted(embedded - set(ctx.images)):
        f.append(f"[G16-IMG] {n} is embedded but not committed")
    for n in sorted(set(ctx.images) - embedded):
        f.append(f"[G16-IMG] {n} is committed but not embedded")


def g_freeze(ctx: Ctx, vals: dict[str, str], f: Findings) -> None:
    if ctx.merged_spec is None:
        return
    now = set(ctx.spec.split("\n"))
    for ln in ctx.merged_spec.split("\n"):
        if re.match(r"^\| [A-Z]{2,3}-\d+ ", ln) and ln not in now:
            f.append(f"[G17-FREEZE] a merged row changed: {ln[:60]!r}")


def g_route(ctx: Ctx, vals: dict[str, str], f: Findings) -> None:
    rt = rows(section(ctx.spec, "14."), "RT")
    on = {r[1] for r in rt}
    for r in rt:
        if r[1] not in OPEN_OWNERS:
            f.append(f"[G18-ROUTE] {r[0]} targets {r[1]}, no open owner of the ruled set")
    for r in df_rows(ctx.spec):
        for t in (t.strip() for t in r[5].split(";")):
            if t.startswith("#") and t not in on:
                f.append(f"[G18-ROUTE] {r[0]} targets {t}, which no RT row names")


GATES: list[Callable[[Ctx, dict[str, str], Findings], None]] = [
    g_audit, g_cite, g_pins, g_copy, g_token, g_contrast, g_states, g_ni, g_findings, g_class,
    g_ids, g_hygiene, g_scope, g_walk, g_bq, g_img, g_freeze, g_route,
]  # fmt: skip


def run(ctx: Ctx) -> tuple[dict[str, str], Findings]:
    f: Findings = []
    if not ctx.spec:
        return {}, ["[G01-AUDIT] the spec cannot be read"]
    vals = compute(ctx)
    for g in GATES:
        try:
            g(ctx, vals, f)
        except (
            IndexError,
            KeyError,
            ValueError,
        ) as e:  # default-deny: a gate that cannot read FAILs
            f.append(f"[{g.__name__}] could not run: {e!r}")
    return vals, f


def repin(ctx: Ctx) -> str:
    out = [
        "# E08-D14 pins: one cited endpoint per line, `KEY:line sha1-16` of its words at the base.",
        "# Written only by `e08_d14_designqa_audit.py --repin-ruled`.",
    ]
    for key, n in sorted(endpoints(ctx.spec), key=lambda x: (x[0], x[1])):
        line = ctx.base_line(key, n)
        if line is not None:
            out.append(f"{key}:{n} {line_hash(line)}")
    return "\n".join(out) + "\n"


# ------------------------------------------------------------------------------------ self-test


def _mut(text: str, old: str, new: str) -> str:
    return text.replace(old, new, 1) if old in text else text + "\n" + new


def mutations(ctx: Ctx) -> list[tuple[str, Callable[[Ctx], Ctx]]]:
    def spec(fn: Callable[[str], str]) -> Callable[[Ctx], Ctx]:
        return lambda c: dataclasses.replace(c, spec=fn(c.spec))

    first_df = df_rows(ctx.spec)[0][0] if df_rows(ctx.spec) else "DF-1"
    return [
        ("G01-AUDIT", spec(lambda s: re.sub(r"audit:tk\.literals=\d+", "audit:tk.literals=999", s, count=1))),
        ("G02-CITE", lambda c: dataclasses.replace(c, pins=re.sub(r"[0-9a-f]{16}", "0" * 16, c.pins, count=1))),
        ("G03-PINS", lambda c: dataclasses.replace(c, pins=c.pins + "D05:9999 " + "a" * 16 + "\n")),
        ("G04-COPY", spec(lambda s: re.sub(r"(?m)^(\| CP-1\s+\| )", r"\1`d05.idle.3`, ", s, count=1))),
        ("G05-TOKEN", spec(lambda s: re.sub(r"(?m)^(\| TK-1\s+\|[^|]*\| )", r"\1`SS`:1; ", s, count=1))),
        ("G06-CONTRAST", spec(lambda s: re.sub(r"(?m)^(\| CN-1\s+\|.*)\| —(\s*)\|$", r"\1| DF-1\2|", s, count=1))),
        ("G07-STATES", spec(lambda s: re.sub(r"(?m)^\| ST-1\s+\|.*\n", "", s, count=1))),
        ("G08-NI", spec(lambda s: re.sub(r"(?m)^\| NI-1\s+\|.*\n", "", s, count=1))),
        ("G09-FINDINGS", spec(lambda s: re.sub(rf"(?m)^(\| {first_df}\s+\| )implementation defect", r"\1a hunch", s, count=1))),
        ("G10-CLASS", spec(lambda s: s + "\nSee DF-999.\n")),
        ("G11-IDS", spec(lambda s: re.sub(r"(?m)^\| RN-2(\s+)\|", r"| RN-9\1|", s, count=1))),
        ("G12-HYGIENE", spec(lambda s: s + "\nfixes #277\n")),
        ("G13-SCOPE", lambda c: dataclasses.replace(c, changed=[*c.changed, "docs/plan/14-screens-catalogue.md"])),
        ("G14-WALK", spec(lambda s: s.replace("**The owner checklist**", "**The owner checklist**\n" + "".join(f"\n{i}. x" for i in range(1, 12)), 1))),
        ("G15-BQ", spec(lambda s: re.sub(r"(?m)^\| BQ-15\s+\|.*\n", "", s, count=1))),
        ("G16-IMG", lambda c: dataclasses.replace(c, images=[*c.images, "e08-d14-extra.png"])),
        ("G17-FREEZE", lambda c: dataclasses.replace(c, merged_spec="| DF-1 | a row that changed |\n")),
        ("G18-ROUTE", spec(lambda s: re.sub(r"(?m)^\| RT-1\s+\|.*\n", "", s, count=1))),
    ]  # fmt: skip


def self_test(ctx: Ctx) -> tuple[int, int, list[str]]:
    _v, base = run(ctx)
    notes: list[str] = []
    if base:
        notes.append(f"base run is not clean: {len(base)} FAILs")
    ok = 0
    muts = mutations(ctx)
    for code, mut in muts:
        _v2, got = run(mut(ctx))
        new = [x for x in got if x not in base and x.startswith(f"[{code}]")]
        if new:
            ok += 1
        else:
            notes.append(f"mutation for {code} added no {code} FAIL")
    return ok, len(muts), notes


# ------------------------------------------------------------------------------------ main


def main(argv: list[str]) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n", 1)[0])
    ap.add_argument("--check", action="store_true")
    ap.add_argument("--json", action="store_true")
    ap.add_argument("--self-test", action="store_true")
    ap.add_argument("--repin-ruled", action="store_true")
    a = ap.parse_args(argv)
    ctx = build_ctx()
    if a.repin_ruled:
        (ROOT / PINS_REL).write_text(repin(ctx), encoding="utf-8")
        print(f"wrote {PINS_REL}")
        return 0
    if a.self_test:
        ok, n, notes = self_test(ctx)
        for x in notes:
            print(x)
        print(f"self-test: {ok}/{n} mutations caught")
        return 0 if ok == n and not notes else 1
    vals, f = run(ctx)
    if a.json:
        print(
            json.dumps({"base": ctx.base, "values": vals, "fails": f}, indent=2, ensure_ascii=False)
        )
    else:
        for x in f:
            print(f"FAIL {x}")
        print(f"{'FAIL' if f else 'PASS'}: {len(f)} findings at base {ctx.base[:10]}")
    return 1 if (a.check and f) else 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
