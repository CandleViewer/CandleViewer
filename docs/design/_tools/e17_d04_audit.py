"""E17-D04 (#408) audit: the design QA and accessibility review of the shipped connection chrome.

Stdlib only, offline (`python3 -I -B`). It reads the record, the pins file and the image folder
from the working tree; every cited plan or design file AS TEXT at the merge-base with `origin/main`;
and every cited build file (the chip, its selector, its container, its announcer and their suites)
AS TEXT at #5420's pinned head (`PIN`), until that PR merges and `PIN` is re-pinned to its merge
commit. It runs no repo code and drives no browser. Default-deny: a gate that cannot read its input
FAILs.

Two modes, chosen by content, never by flag. PR mode: the record is absent at the merge-base; the
diff may touch only the own files (the record, this tool, the pins file, the image folder).
Post-merge mode: the record ships at the merge-base; every merged table row stands unchanged.

Gates (each FAIL led by its code):

- [G01-AUDIT] every `<!-- audit:key=value -->` marker is a known key and equals the recomputed
  value.
- [G02-CITE] every cited endpoint resolves to a non-blank line at its revision, and its pin
  matches.
- [G03-PINS] the pins file and the record's cited endpoints match both ways.
- [G04-COPY] the CP rows list every chip deck key (E08-D13's `e17d2.A.*`) the built chip strings do
  not hold, once each, and no key they hold; a CP finding is an F row or "no divergence:" a reason.
- [G05-CONTRAST] the CN rows are the computed pairs; a pair under its bar in any theme names an F
  row.
- [G06-WALK] the W rows are E17-D02 section 2 rows 5, 10-13 and 16, the DL rows the other eighteen,
  each row once; W statuses and DL deltas are from the ruled sets; a "not built" names its register
  row; every W or DL row a section 3 FS row names walks one of that FS row's matrix rows; no row
  anywhere reads "not reachable" (AC1).
- [G07-FINDINGS] every F row has a class, severity, priority, surface, criterion, owner, target and
  cited evidence from the ruled sets; the priority follows the severity; a Blocking row is an IS
  row.
- [G08-CLASS] every F id named anywhere is a register row, and every row is named outside it.
- [G09-IDS] the ids of each table family are 1..n in order.
- [G10-HYGIENE] no local path, URL, host, lane or agent name, closing keyword before an issue
  number, or "What this ... fixes" heading in the own text files or the images' PNG text chunks.
- [G11-SCOPE] the changed paths are the own files only.
- [G12-WALKTHROUGH] the owner checklist holds one to ten items.
- [G13-BQ] section R lists BQ-0..BQ-16 once each, each with a status from the ruled set, and names
  the comment that rules them.
- [G14-IMG] every embedded image is committed and every committed one embedded; ten at most.
- [G15-FREEZE] post-merge mode: every merged table row stands unchanged.
- [G16-ROUTE] every RT row targets an open owner of the ruled set; every F target that is an issue
  is named by an RT row.
- [G17-PIN] the pinned head is readable and named in the record; every build key reads at it.
- [G18-T2] every T2 row has a verdict from the ruled set, and the record states the gate's outcome.
- [G19-AROW] every A row amends an owner document of the ruled set, through an open owner, and cites
  an F row.

`--json` prints the numbers; `--check` exits 1 on any FAIL; `--self-test` applies at least one
mutation per gate (one per hygiene pattern) to an in-memory copy and passes only when each adds
FAILs of its gate's code and the base run is clean; `--repin-ruled` rewrites the pins file from the
record's cites and is its only writer.

Usage: python3 -I -B docs/design/_tools/e17_d04_audit.py [--check] [--json] [--self-test]
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
SPEC_REL = "docs/design/E17/E17-D04.md"
TOOL_REL = "docs/design/_tools/e17_d04_audit.py"
PINS_REL = "docs/design/_tools/e17_d04_ruled_pins.txt"
IMG_DIR = "docs/design/E17/img/e17-d04"
OWN = {SPEC_REL, TOOL_REL, PINS_REL}
UPSTREAM = "origin/main"
# #5420's head as the BQ list pins it; re-pinned to the merge commit once it lands (BQ-0).
PIN = "86f6a14c25e18e7b155d4de13062c70244b5ad5e"
DECK_REL = "docs/design/E08/E08-D13-copy.json"
DS_JSON_DIR = "packages/ui/tokens"
RULING_COMMENT = "6573202575"

WEB = "apps/web/src/"
SHELL = WEB + "features/app-shell/"
WS = WEB + "lib/ws/"
TEST = "apps/web/test/"
# Keys read at the merge-base (plan and design documents).
BASE_KEYS: dict[str, str] = {
    "D02": "docs/design/E17/E17-D02.md",
    "D02H": "docs/design/E17/E17-D02-handoff.md",
    "D14": "docs/design/E08/E08-D14.md",
    "E09D11": "docs/design/E09/E09-D11.md",
    "SDG": ".claude/rules/32-design-specs.md",
}
# Keys read at PIN (the build under review and its suites).
PIN_KEYS: dict[str, str] = {
    "CS": SHELL + "ConnectionStatus.tsx",
    "SLOT": SHELL + "ConnectionStatusSlot.tsx",
    "ANN": SHELL + "chipAnnouncer.ts",
    "SEL": WS + "state/chipState.ts",
    "RED": WS + "state/reducer.ts",
    "TYP": WS + "state/types.ts",
    "FC": WS + "worker/faultChannel.ts",
    "WSC": WS + "client/createWsClient.ts",
    "SELT": TEST + "lib/ws/chipState.test.ts",
    "FCT": TEST + "lib/ws/faultChannel.test.ts",
    "ANNT": TEST + "features/app-shell/connection-chip-announce.test.tsx",
    "ANNU": TEST + "features/app-shell/chipAnnouncer.test.ts",
    "CST": TEST + "features/app-shell/connection-status.test.tsx",
    "ISOT": TEST + "features/app-shell/status-bar-isolation.test.tsx",
    "E2E": "apps/web/e2e/shell/connection-chip.spec.ts",
    "TB": SHELL + "TopBar.tsx",
    "APP": SHELL + "AppShell.tsx",
    "MOT": SHELL + "motion.ts",
    "FR": "packages/ui/src/components/focusring.css",
}
# The chip's strings for the copy diff: the chip and the container that feeds it.
COPY_KEYS = ["CS", "SLOT"]
DECK_PREFIX = "e17d2.A."
THEMES = {
    "dark": ("primitives", "semantic-dark"),
    "light": ("primitives", "semantic-dark", "semantic-light"),
    "hc": ("primitives", "semantic-dark", "semantic-hc"),
}
# CN-n: the chip's fill / ink pairs (`CS`:35-42, the word always `color.text.primary`), bar.
CN_PAIRS: dict[str, tuple[str, str, str]] = {
    "cn1": ("color.text.primary", "color.surface.raised", "text"),
    "cn2": ("color.data-confidence.live.indicator", "color.surface.raised", "non-text"),
    "cn3": ("color.text.primary", "color.status.info.subtle", "text"),
    "cn4": ("color.status.info.default", "color.status.info.subtle", "non-text"),
    "cn5": ("color.data-confidence.stale.indicator", "color.surface.raised", "non-text"),
    "cn6": ("color.text.primary", "color.status.warning.subtle", "text"),
    "cn7": ("color.status.warning.strong", "color.status.warning.subtle", "non-text"),
    "cn8": ("color.text.primary", "color.status.danger.subtle", "text"),
    "cn9": ("color.status.danger.strong", "color.status.danger.subtle", "non-text"),
    "cn10": ("color.border.default", "color.surface.raised", "decorative"),
    # The CMP-039 ring sits 2 px outside the pill (`FR`:12-13), on the TopBar's raised surface.
    "cn11": ("color.focus.ring", "color.surface.raised", "non-text"),
    # The strong T2 fill against the T1 fill (both on the raised TopBar): it carries the tier.
    "cn12": ("color.status.warning.subtle", "color.surface.raised", "non-text"),
    # The Delayed fill: ◐ and the word carry Delayed, so the fill is decoration.
    "cn13": ("color.status.info.subtle", "color.surface.raised", "decorative"),
    # The T1 glyph ink against the T2 glyph ink (the same ⚠ both times).
    "cn14": ("color.data-confidence.stale.indicator", "color.status.warning.strong", "decorative"),
}
BARS = {"text": 4.5, "non-text": 3.0, "decorative": 0.0}
WALKED = (5, 10, 11, 12, 13, 16)
MATRIX_ROWS = 24
W_STATUS = {"pass", "pass with findings", "not built", "owner-run"}
DL_DELTA = re.compile(r"^(holds|changed by #5420|still `D14` DF-\d+)")
CLASSES = ("implementation defect", "accepted divergence", "specification gap")
SEVERITIES = {
    "Blocking": "priority/p0",
    "Major": "priority/p1",
    "Minor": "priority/p2",
    "Info": "—",
}
OPEN_OWNERS = {"#32", "#302", "#325", "#569", "#1028", "#5335"}
TARGETS_EXTRA = {"register"}
OWNER_DOCS = re.compile(r"^(`D02` §\d+[A-Z ]*(row \d+(–\d+)?)?|`14` SCR-\d+|`15` CMP-\d+)")
T2_VERDICTS = {"not a gated control", "not built", "other surface"}
T2_OUTCOME = "no in-scope T2 control"
BQ_IDS = list(range(17))
BQ_STATUS = re.compile(
    r"^(default built; ruling pending|built with the named deviations; ruling pending"
    r"|ruled as proposed|ruled: .+)$"
)
FAMILIES = (
    "BQ", "RN", "FS", "W", "DL", "CN", "CP", "CM", "IX", "AN", "MO", "AX", "T2", "SC", "F", "A",
    "DR", "RT", "IS", "OR",
)  # fmt: skip

KEY_RE = r"[A-Z][A-Z0-9]{1,7}|\d\d"
MD_CITE = re.compile(
    rf"`(?P<key>{KEY_RE})`:(?P<a>\d+)(?:[–-](?P<b>\d+))?(?P<more>(?:, :\d+(?:[–-]\d+)?)*)"
)
MORE = re.compile(r":(\d+)(?:[–-](\d+))?")
# An HTML comment can span lines: DOTALL.
MARK = re.compile(r"<!-- audit:(?P<k>[a-z0-9.\-]+)=(?P<v>.*?) -->", re.DOTALL)


# ------------------------------------------------------------------------------------ helpers


def run_git(*args: str) -> tuple[int, str]:
    r = subprocess.run(
        ["git", *args], cwd=ROOT, capture_output=True, text=True, encoding="utf-8", check=False
    )
    return r.returncode, r.stdout


def git(*args: str) -> str:
    rc, out = run_git(*args)
    return out if rc == 0 else ""


def merge_base() -> str:
    return git("merge-base", "HEAD", UPSTREAM).strip() or git("rev-parse", "HEAD").strip()


def show(rev: str, rel: str) -> str | None:
    rc, out = run_git("show", f"{rev}:{rel}")
    return out if rc == 0 else None


def plan_path(nn: str, rev: str) -> str | None:
    for name in git("ls-tree", "--name-only", rev, "docs/plan/").split():
        if name.startswith(f"docs/plan/{nn}-") and name.endswith(".md"):
            return name
    return None


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
    for m in re.finditer(rf"(?<![\w`]){fam}-(\d+)(?:\.\.{fam}-(\d+))?\b", text):
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


VALUE = r"(\d+(?:[.:,]\d+)*)"


def holds(text: str, lits: list[str]) -> bool:
    """A deck string is held when a built literal is it, with a fill for each of its numbers."""
    parts = re.split(VALUE, text)
    rx = re.compile(
        "".join(re.escape(p) if i % 2 == 0 else "\x01" for i, p in enumerate(parts)), re.DOTALL
    )
    return any(rx.fullmatch(lit.replace("\x00", "\x01")) for lit in lits)


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
    out: list[str] = []
    on = False
    level = 0
    for ln in text.split("\n"):
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
    pin: str
    pin_ok: bool
    changed: list[str]
    merged_spec: str | None
    sources: dict[str, str]
    deck: dict[str, Any]
    tokens: dict[str, dict[str, Any]]
    images: list[str]
    img_text: dict[str, str]

    def text_of(self, key: str) -> str | None:
        if key in PIN_KEYS:
            rev, rel = self.pin, PIN_KEYS[key]
        elif key in BASE_KEYS:
            rev, rel = self.base, BASE_KEYS[key]
        elif key.isdigit():
            found = plan_path(key, self.base)
            if found is None:
                return None
            rev, rel = self.base, found
        else:
            return None
        tag = f"{rev}:{rel}"
        if tag not in self.sources:
            self.sources[tag] = show(rev, rel) or ""
        return self.sources[tag] or None

    def line(self, key: str, n: int) -> str | None:
        text = self.text_of(key)
        if text is None:
            return None
        lines = text.split("\n")
        return lines[n - 1] if 0 < n <= len(lines) else None


def png_text(path: Path) -> str:
    """The keyword and text of a PNG's tEXt / iTXt chunks (zTXt is compressed and not read)."""
    b = path.read_bytes()
    out: list[str] = []
    i = 8
    while i + 8 <= len(b):
        n = int.from_bytes(b[i : i + 4], "big")
        kind = b[i + 4 : i + 8]
        if kind in (b"tEXt", b"iTXt"):
            out.append(b[i + 8 : i + 8 + n].replace(b"\x00", b" ").decode("latin-1"))
        i += 12 + n
    return "\n".join(out)


def build_ctx() -> Ctx:
    base = merge_base()
    changed = sorted(
        {
            *git("diff", "--name-only", base).split(),
            *git("ls-files", "-o", "--exclude-standard").split(),
        }
    )
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
        pin=PIN,
        pin_ok=run_git("cat-file", "-e", f"{PIN}^{{commit}}")[0] == 0,
        changed=changed,
        merged_spec=show(base, SPEC_REL),
        sources={},
        deck=json.loads(show(base, DECK_REL) or "{}").get("strings", {}),
        tokens=tokens,
        images=sorted(p.name for p in img.glob("*.png")) if img.is_dir() else [],
        img_text={p.name: png_text(p) for p in img.glob("*.png")} if img.is_dir() else {},
    )


# ------------------------------------------------------------------------------------ compute


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
    return {
        f"{key}.{theme}": ratio(rgb(hex_of(ctx, theme, fg)), rgb(hex_of(ctx, theme, bg)))
        for key, (fg, bg, _bar) in CN_PAIRS.items()
        for theme in THEMES
    }


def deck_status(ctx: Ctx) -> dict[str, bool]:
    lits: list[str] = []
    for k in COPY_KEYS:
        lits += literals(ctx.text_of(k) or "")
    return {
        dk: holds(str(v.get("text", "")), lits)
        for dk, v in ctx.deck.items()
        if dk.startswith(DECK_PREFIX)
    }


def var_refs(ctx: Ctx) -> tuple[int, list[str]]:
    """The chip's `var(--…)` references and its LOOK fill / ink names, against the dark set."""
    names = {k.replace(".", "-") for k in ctx.tokens["dark"]}
    src = strip_comments(ctx.text_of("CS") or "")
    seen = re.findall(r"var\(--([a-z0-9-]+)\)", src)
    look = re.search(r"const LOOK[^=]*=\s*\{(.*?)\n\};", src, re.DOTALL)
    if look:
        seen += [
            "color-" + n
            for n in re.findall(r'"((?:surface|status|data-confidence)[a-z-]*)"', look[1])
        ]
    return len(seen), sorted({n for n in seen if n not in names})


def handoff_stories(ctx: Ctx, key: str, n: int) -> int:
    line = ctx.line(key, n) or ""
    tail = line.split("|")[2] if key == "D02" and line.count("|") >= 3 else line.split(":", 1)[-1]
    return len([s for s in re.split(r",\s*", tail.strip(" .|*")) if s.strip()])


def f_rows(spec: str) -> list[list[str]]:
    return rows(section(spec, "12."), "F")


def compute(ctx: Ctx) -> dict[str, str]:
    v: dict[str, str] = {}
    status = deck_status(ctx)
    v["deck.a"] = str(len(status))
    v["deck.a.held"] = str(sum(status.values()))
    v["deck.a.missed"] = str(len(status) - sum(status.values()))
    refs, unresolved = var_refs(ctx)
    v["tk.refs"] = str(refs)
    v["tk.unresolved"] = str(len(unresolved))
    cn = contrast(ctx)
    for key, r in cn.items():
        v[key] = f"{r:.2f}:1"
    v["story.d02"] = str(handoff_stories(ctx, "D02", 396))
    v["story.15"] = str(handoff_stories(ctx, "15", 861))
    v["w"] = str(len(rows(section(ctx.spec, "4."), "W")))
    v["dl"] = str(len(rows(section(ctx.spec, "4."), "DL")))
    fs = f_rows(ctx.spec)
    v["f"] = str(len(fs))
    for sev in SEVERITIES:
        v[f"f.{sev.lower()}"] = str(sum(1 for r in fs if len(r) > 2 and r[2] == sev))
    for cls, tag in zip(CLASSES, ("defect", "accepted", "gap"), strict=True):
        v[f"f.{tag}"] = str(sum(1 for r in fs if len(r) > 1 and r[1] == cls))
    v["a"] = str(len(rows(section(ctx.spec, "13."), "A")))
    v["img"] = str(len(ctx.images))
    v["ring.width"] = hex_of(ctx, "dark", "border.focus")
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
        line = ctx.line(key, n)
        if line is None or not line.strip():
            f.append(f"[G02-CITE] `{key}`:{n} does not resolve to a non-blank line")
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
    if not status:
        f.append("[G04-COPY] the chip deck cannot be read")
        return
    listed: dict[str, int] = {}
    for r in rows(section(ctx.spec, "6."), "CP"):
        for k in re.findall(r"`(e17d2\.A\.\d+)`", r[1]):
            listed[k] = listed.get(k, 0) + 1
        fin = r[-1]
        if not (re.search(r"(?<![\w`])F-\d+", fin) or fin.startswith("no divergence:")):
            f.append(f"[G04-COPY] {r[0]}: its finding is neither an F row nor 'no divergence:'")
    for k, held in status.items():
        n = listed.get(k, 0)
        if not held and n != 1:
            f.append(f"[G04-COPY] deck key {k} is not held by the build and is listed {n} times")
        if held and n:
            f.append(f"[G04-COPY] deck key {k} is held by the build but listed as a difference")
    for k in listed:
        if k not in status:
            f.append(f"[G04-COPY] {k} is not a chip deck key")


def g_contrast(ctx: Ctx, vals: dict[str, str], f: Findings) -> None:
    cn = contrast(ctx)
    got = [r[0] for r in rows(section(ctx.spec, "5."), "CN")]
    want = [f"CN-{k[2:]}" for k in CN_PAIRS]
    if got != want:
        f.append(f"[G05-CONTRAST] the CN rows are {got}, not {want}")
    for r in rows(section(ctx.spec, "5."), "CN"):
        key = "cn" + r[0].split("-")[1]
        if key not in CN_PAIRS:
            continue
        bar = BARS[CN_PAIRS[key][2]]
        under = any(cn[f"{key}.{t}"] < bar for t in THEMES)
        if under and not re.search(r"(?<![\w`])F-\d+", r[-1]):
            f.append(f"[G05-CONTRAST] {r[0]} is under its bar and names no F row")


def g_walk(ctx: Ctx, vals: dict[str, str], f: Findings) -> None:
    sec = section(ctx.spec, "4.")
    seen: list[int] = []
    for r in rows(sec, "W"):
        m = re.fullmatch(r"row (\d+)", r[1])
        n = int(m[1]) if m else -1
        seen.append(n)
        if n not in WALKED:
            f.append(f"[G06-WALK] {r[0]} walks {r[1]!r}, not one of rows {WALKED}")
        if r[6] not in W_STATUS:
            f.append(f"[G06-WALK] {r[0]}: status {r[6]!r}")
        if r[6] == "not built" and not re.search(r"DF-\d+|(?<![\w`])F-\d+", r[-1]):
            f.append(f"[G06-WALK] {r[0]} is not built and names no register row")
    for r in rows(sec, "DL"):
        m = re.fullmatch(r"row (\d+)", r[1])
        n = int(m[1]) if m else -1
        seen.append(n)
        if n in WALKED:
            f.append(f"[G06-WALK] {r[0]}: row {n} is walked in full, not a delta line")
        if not DL_DELTA.match(r[4]):
            f.append(f"[G06-WALK] {r[0]}: delta {r[4][:30]!r} is not holds / changed / still")
    d02_row = {r[0]: r[1] for fam in ("W", "DL") for r in rows(sec, fam)}
    for r in rows(section(ctx.spec, "3."), "FS"):
        named = re.findall(r"(?<![\w`])((?:W|DL)-\d+)\b", r[-1])
        mine = {f"row {n}" for n in re.findall(r"\d+", r[3])}
        for x in named:
            if d02_row.get(x) not in mine:
                f.append(f"[G06-WALK] {r[0]} names {x}, which walks {d02_row.get(x)}, not {r[3]}")
    if sorted(seen) != list(range(1, MATRIX_ROWS + 1)):
        f.append(f"[G06-WALK] the W and DL rows cover {sorted(seen)}, not rows 1..{MATRIX_ROWS}")
    m = re.search(r"\bnot[ -]reachable\b", ctx.spec.replace('"not reachable"', ""))
    if m:
        f.append("[G06-WALK] a row reads 'not reachable' (AC1 forbids it)")


def g_findings(ctx: Ctx, vals: dict[str, str], f: Findings) -> None:
    is_rows = {r[1] for r in rows(section(ctx.spec, "15."), "IS")}
    for r in f_rows(ctx.spec):
        if len(r) < 10:
            f.append(f"[G07-FINDINGS] {r[0]} has {len(r)} cells, not 10")
            continue
        _id, cls, sev, prio, surface, crit, owner, target, evidence, _reason = r[:10]
        if cls not in CLASSES:
            f.append(f"[G07-FINDINGS] {r[0]}: class {cls!r}")
        if sev not in SEVERITIES:
            f.append(f"[G07-FINDINGS] {r[0]}: severity {sev!r}")
        elif prio != SEVERITIES[sev]:
            f.append(f"[G07-FINDINGS] {r[0]}: priority {prio!r} for a {sev} row")
        if not surface or surface == "—":
            f.append(f"[G07-FINDINGS] {r[0]}: no surface")
        if not crit or crit == "—":
            f.append(f"[G07-FINDINGS] {r[0]}: no criterion")
        if not re.fullmatch(r"`E\d\d-[DTSQ]\d\d · area/[a-z-]+`", owner):
            f.append(f"[G07-FINDINGS] {r[0]}: owner {owner!r}")
        for t in (t.strip() for t in target.split(";")):
            if t not in OPEN_OWNERS and t not in TARGETS_EXTRA:
                f.append(f"[G07-FINDINGS] {r[0]}: target {t!r} is not an open owner")
        if not cite_spans(evidence):
            f.append(f"[G07-FINDINGS] {r[0]}: the evidence carries no file:line cite")
        if sev == "Blocking" and r[0] not in is_rows:
            f.append(f"[G07-FINDINGS] {r[0]} is Blocking but not listed as an IS row")


def g_class(ctx: Ctx, vals: dict[str, str], f: Findings) -> None:
    reg = section(ctx.spec, "12.")
    ids = {int(r[0].split("-")[1]) for r in f_rows(ctx.spec)}
    outside = ctx.spec.replace(reg, "")
    for n in sorted(set(ids_in(ctx.spec, "F")) - ids):
        f.append(f"[G08-CLASS] F-{n} is named but is no register row")
    for n in sorted(ids - set(ids_in(outside, "F"))):
        f.append(f"[G08-CLASS] F-{n} is named nowhere outside the register")


def g_ids(ctx: Ctx, vals: dict[str, str], f: Findings) -> None:
    for fam in FAMILIES:
        got = [int(r[0].split("-")[1]) for r in rows(ctx.spec, fam)]
        start = 0 if fam == "BQ" else 1
        if got and got != list(range(start, start + len(got))):
            f.append(f"[G09-IDS] the {fam} rows are not {start}..{start + len(got) - 1} in order")


def _alt(*parts: str) -> str:
    return "|".join(parts)


# Built from fragments so that this file names no path, lane or agent it forbids.
HYGIENE = [
    (re.compile(_alt("/" + "home/", "~" + "/", r"\bw" + r"t/\d", "scr" + "atch-")), "a local path"),
    (re.compile("ht" + r"tps?://"), "a URL"),
    (
        re.compile(
            _alt(
                r"\b(h" + "cl|h" + "pe|v" + r"ps)-?w" + "orker",
                r"\bw" + r"orker-\d",
                r"\bRel" + r"ay" + r"Room\b",
                r"\bAn" + r"vil\b",
                r"\bsc" + r"out\b",
            ),
            re.IGNORECASE,
        ),
        "a lane or agent name",
    ),
    (
        re.compile(r"\b(close[sd]?|fix(e[sd])?|resolve[sd]?)\s+#\d+", re.IGNORECASE),
        "a closing keyword before an issue number",
    ),
    (re.compile(r"\b[a-z0-9-]+\.(local|lan|internal)\b"), "a host name"),
    (re.compile(r"(?m)^#+ What this\b.*\bfixes\b", re.IGNORECASE), "a 'What this … fixes' heading"),
]


def g_hygiene(ctx: Ctx, vals: dict[str, str], f: Findings) -> None:
    texts = [(SPEC_REL, ctx.spec), (PINS_REL, ctx.pins), (TOOL_REL, ctx.tool)]
    texts += [(f"{IMG_DIR}/{n} text chunks", t) for n, t in sorted(ctx.img_text.items())]
    for rel, text in texts:
        for rx, what in HYGIENE:
            m = rx.search(text)
            if m:
                f.append(f"[G10-HYGIENE] {rel}: {what} ({m[0]!r})")


def g_scope(ctx: Ctx, vals: dict[str, str], f: Findings) -> None:
    for rel in ctx.changed:
        if rel not in OWN and not (rel.startswith(IMG_DIR + "/") and rel.endswith(".png")):
            f.append(f"[G11-SCOPE] {rel} is outside this ticket's own files")


def g_walkthrough(ctx: Ctx, vals: dict[str, str], f: Findings) -> None:
    block = ctx.spec.split("**The owner checklist**", 1)
    items = re.findall(r"(?m)^\d+\. ", block[1].split("\n## ", 1)[0]) if len(block) == 2 else []
    if not items or len(items) > 10:
        f.append(f"[G12-WALKTHROUGH] the owner checklist holds {len(items)} items (1..10)")


def g_bq(ctx: Ctx, vals: dict[str, str], f: Findings) -> None:
    sec = section(ctx.spec, "R.")
    got = [int(r[0].split("-")[1]) for r in rows(sec, "BQ")]
    if got != BQ_IDS:
        f.append(f"[G13-BQ] section R lists {got}, not BQ-0..BQ-{BQ_IDS[-1]}")
    for r in rows(sec, "BQ"):
        if not BQ_STATUS.match(r[-1]):
            f.append(f"[G13-BQ] {r[0]}: status {r[-1]!r}")
    head = re.search(r"(?m)^## R\. .*$", ctx.spec)
    if not head or RULING_COMMENT not in head[0]:
        f.append(f"[G13-BQ] section R's heading does not name comment {RULING_COMMENT}")


def g_img(ctx: Ctx, vals: dict[str, str], f: Findings) -> None:
    embedded = set(re.findall(r"img/e17-d04/([a-z0-9.\-]+\.png)", ctx.spec))
    for n in sorted(embedded - set(ctx.images)):
        f.append(f"[G14-IMG] {n} is embedded but not committed")
    for n in sorted(set(ctx.images) - embedded):
        f.append(f"[G14-IMG] {n} is committed but not embedded")
    if len(ctx.images) > 10:
        f.append(f"[G14-IMG] {len(ctx.images)} images, more than ten")


def g_freeze(ctx: Ctx, vals: dict[str, str], f: Findings) -> None:
    if ctx.merged_spec is None:
        return
    now = set(ctx.spec.split("\n"))
    for ln in ctx.merged_spec.split("\n"):
        if re.match(r"^\| [A-Z][A-Z0-9]{0,2}-\d+ ", ln) and ln not in now:
            f.append(f"[G15-FREEZE] a merged row changed: {ln[:60]!r}")


def g_route(ctx: Ctx, vals: dict[str, str], f: Findings) -> None:
    rt = rows(section(ctx.spec, "15."), "RT")
    on = {r[1] for r in rt}
    for r in rt:
        if r[1] not in OPEN_OWNERS:
            f.append(f"[G16-ROUTE] {r[0]} targets {r[1]}, no open owner of the ruled set")
    for r in f_rows(ctx.spec):
        for t in (t.strip() for t in r[7].split(";")):
            if t.startswith("#") and t not in on:
                f.append(f"[G16-ROUTE] {r[0]} targets {t}, which no RT row names")


def g_pin(ctx: Ctx, vals: dict[str, str], f: Findings) -> None:
    if not ctx.pin_ok:
        f.append(f"[G17-PIN] the pinned head {ctx.pin[:10]} cannot be read (fetch #5420's head)")
        return
    if ctx.pin[:9] not in ctx.spec:
        f.append(f"[G17-PIN] the record does not name the pinned head {ctx.pin[:9]}")
    for key in PIN_KEYS:
        if ctx.text_of(key) is None:
            f.append(f"[G17-PIN] `{key}` does not read at the pinned head")


def g_t2(ctx: Ctx, vals: dict[str, str], f: Findings) -> None:
    sec = section(ctx.spec, "10.")
    t2 = rows(sec, "T2")
    if not t2:
        f.append("[G18-T2] no T2 row")
    for r in t2:
        if not any(r[3].startswith(v) for v in T2_VERDICTS):
            f.append(f"[G18-T2] {r[0]}: verdict {r[3][:30]!r}")
    if T2_OUTCOME not in sec:
        f.append(f"[G18-T2] the T2 section does not state {T2_OUTCOME!r}")


def g_arow(ctx: Ctx, vals: dict[str, str], f: Findings) -> None:
    fs = {r[0] for r in f_rows(ctx.spec)}
    for r in rows(section(ctx.spec, "13."), "A"):
        if not OWNER_DOCS.match(r[1]):
            f.append(f"[G19-AROW] {r[0]}: {r[1][:30]!r} is no owner document of the ruled set")
        if r[2] not in OPEN_OWNERS:
            f.append(f"[G19-AROW] {r[0]}: owner {r[2]!r} is not open")
        named = {f"F-{n}" for n in ids_in(r[-1], "F")}
        if not named or not named <= fs:
            f.append(f"[G19-AROW] {r[0]} cites no register row")


GATES: list[Callable[[Ctx, dict[str, str], Findings], None]] = [
    g_audit, g_cite, g_pins, g_copy, g_contrast, g_walk, g_findings, g_class, g_ids, g_hygiene,
    g_scope, g_walkthrough, g_bq, g_img, g_freeze, g_route, g_pin, g_t2, g_arow,
]  # fmt: skip


def run(ctx: Ctx) -> tuple[dict[str, str], Findings]:
    f: Findings = []
    if not ctx.spec:
        return {}, ["[G01-AUDIT] the record cannot be read"]
    try:
        vals = compute(ctx)
    except (IndexError, KeyError, ValueError) as e:
        return {}, [f"[G01-AUDIT] the numbers cannot be computed: {e!r}"]
    for g in GATES:
        try:
            g(ctx, vals, f)
        except (IndexError, KeyError, ValueError) as e:  # default-deny: a gate that cannot read
            f.append(f"[{g.__name__}] could not run: {e!r}")
    return vals, f


def repin(ctx: Ctx) -> str:
    out = [
        "# E17-D04 pins: one cited endpoint per line, `KEY:line sha1-16` of its words.",
        "# Plan and design keys at the merge-base; build keys at the tool's PIN (#5420's head).",
        "# Written only by `e17_d04_audit.py --repin-ruled`.",
    ]
    for key, n in sorted(endpoints(ctx.spec), key=lambda x: (x[0], x[1])):
        line = ctx.line(key, n)
        if line is not None:
            out.append(f"{key}:{n} {line_hash(line)}")
    return "\n".join(out) + "\n"


# ------------------------------------------------------------------------------------ self-test


def mutations(ctx: Ctx) -> list[tuple[str, Callable[[Ctx], Ctx]]]:
    def spec(fn: Callable[[str], str]) -> Callable[[Ctx], Ctx]:
        return lambda c: dataclasses.replace(c, spec=fn(c.spec))

    def sub(pat: str, rep: str) -> Callable[[Ctx], Ctx]:
        return spec(lambda s: re.sub(pat, rep, s, count=1))

    def with_(**kw: Any) -> Callable[[Ctx], Ctx]:
        return lambda c: dataclasses.replace(c, **kw)

    def info_eq_subtle(c: Ctx) -> Ctx:
        key = "color.status.info.default"
        tokens = {t: {**v, key: v["color.status.info.subtle"]} for t, v in c.tokens.items()}
        return dataclasses.replace(c, tokens=tokens)

    # One G10 mutation per HYGIENE pattern, each built from fragments, plus a PNG text chunk.
    dirty = [
        "/" + "home/x",
        "ht" + "tps://x",
        "h" + "cl-w" + "orker",
        "fix" + "es #" + "408",
        "box.lo" + "cal",
        "\n## What this " + "change fixes\n",
    ]

    def append(d: str) -> Callable[[Ctx], Ctx]:
        return spec(lambda s: s + "\n" + d + "\n")

    hygiene: list[tuple[str, Callable[[Ctx], Ctx]]] = [("G10-HYGIENE", append(d)) for d in dirty]
    hygiene.append(
        (
            "G10-HYGIENE",
            lambda c: dataclasses.replace(c, img_text={**c.img_text, "x.png": dirty[0]}),
        )
    )
    checklist = "**The owner checklist**\n" + "".join(f"\n{i}. x" for i in range(1, 12))
    return [
        ("G01-AUDIT", sub(r"audit:f\.minor=\d+", "audit:f.minor=999")),
        ("G02-CITE", lambda c: with_(pins=re.sub(r"[0-9a-f]{16}", "0" * 16, c.pins, count=1))(c)),
        ("G03-PINS", lambda c: with_(pins=c.pins + "D02:9999 " + "a" * 16 + "\n")(c)),
        ("G04-COPY", sub(r"(?m)^(\| CP-1\s+\| )", r"\1`e17d2.A.1`, ")),
        ("G05-CONTRAST", info_eq_subtle),
        ("G06-WALK", sub(r"(?m)^\| W-1\s+\|.*\n", "")),
        ("G06-WALK", sub(r"(?m)^(\| FS-7 .*)\(DL-7\)", r"\1(DL-8)")),
        ("G07-FINDINGS", sub(r"(?m)^(\| F-1\s+\|[^|]*\|[^|]*\| )priority/p2", r"\1priority/p0")),
        ("G08-CLASS", spec(lambda s: s + "\nSee F-999.\n")),
        ("G09-IDS", sub(r"(?m)^\| RN-2(\s+)\|", r"| RN-9\1|")),
        *hygiene,
        (
            "G11-SCOPE",
            lambda c: with_(changed=[*c.changed, "docs/plan/14-screens-catalogue.md"])(c),
        ),
        ("G12-WALKTHROUGH", spec(lambda s: s.replace("**The owner checklist**", checklist, 1))),
        ("G13-BQ", sub(r"(?m)^\| BQ-16\s+\|.*\n", "")),
        ("G14-IMG", lambda c: with_(images=[*c.images, "e17-d04-extra.png"])(c)),
        ("G15-FREEZE", with_(merged_spec="| F-1 | a row that changed |\n")),
        ("G16-ROUTE", sub(r"(?m)^\| RT-1\s+\|.*\n", "")),
        ("G17-PIN", with_(pin="0" * 40, pin_ok=False)),
        ("G18-T2", spec(lambda s: s.replace(T2_OUTCOME, "no T2 outcome"))),
        ("G19-AROW", sub(r"(?m)^(\| A-1\s+\| )", r"\1`22` ")),
    ]


def self_test(ctx: Ctx) -> tuple[int, int, list[str]]:
    _v, base = run(ctx)
    notes: list[str] = []
    if base:
        notes.append(f"base run is not clean: {len(base)} FAILs")
    ok = 0
    muts = mutations(ctx)
    for code, mut in muts:
        _v2, got = run(mut(dataclasses.replace(ctx, sources=dict(ctx.sources))))
        if any(x not in base and x.startswith(f"[{code}]") for x in got):
            ok += 1
        else:
            notes.append(f"mutation for {code} added no {code} FAIL")
    return ok, len(muts), notes


# ------------------------------------------------------------------------------------ main


def main(argv: list[str]) -> int:
    ap = argparse.ArgumentParser(description=(__doc__ or "").split("\n", 1)[0])
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
            json.dumps(
                {"base": ctx.base, "pin": ctx.pin, "values": vals, "fails": f},
                indent=2,
                ensure_ascii=False,
            )
        )
    else:
        for x in f:
            print(f"FAIL {x}")
        print(f"{'FAIL' if f else 'PASS'}: {len(f)} findings at base {ctx.base[:10]}")
    return 1 if (a.check and f) else 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
