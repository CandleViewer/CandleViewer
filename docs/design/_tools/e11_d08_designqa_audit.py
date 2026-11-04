#!/usr/bin/env python3
"""E11-D08 design QA of the built chart-engine surfaces: the static half of the pass.

Reads every input at the base named in the spec (`<!-- audit:sha=... -->`) with `git show`, so a
later `main` never changes a number silently. It measures what can be measured from the code:

* TK-01 the shipped `color.chart.*` aliases resolved per theme against E11-D05 §4.1 / §4.1b;
* TK-02 every engine fg/bg pair (`ENGINE_SLOT_PAIRS`) on the shipped tokens, per theme;
* TK-03 hard-coded colours in the built chart surfaces; TK-04 every `var(--x)` names a token;
* DN the density records against E11-D02 §6; MO the momentum constants against E11-D06 D1-D4;
* CP built strings against the copy decks; SB the lock badge's tokens; EQ the view switch.

`--check` exits 1 on any FAIL: an audit marker whose value differs from the computed one, a
`KEY`:line cite whose words moved from its pin, a scrub hit in the spec. `--self-test` applies one
mutation per family and requires each to be caught. `--repin` rewrites the pins file.

Usage: python3 -I -B docs/design/_tools/e11_d08_designqa_audit.py [--check] [--json] [--self-test]
       [--repin]
"""

from __future__ import annotations

import argparse
import codecs
import hashlib
import json
import re
import shutil
import subprocess
import sys
from collections.abc import Callable, Mapping
from dataclasses import dataclass, field
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
GIT = shutil.which("git") or "git"
SPEC_REL = "docs/design/E11/E11-D08.md"
PINS_REL = "docs/design/_tools/e11_d08_ruled_pins.txt"
TOKENS = "packages/ui/tokens"
DESIGN_KEYS = {f"D0{n}": f"docs/design/E11/E11-D0{n}.md" for n in (2, 3, 4, 5, 6, 9)}
# The ruled precedent and the plan documents the ruling names (cited, not measured).
OWNER_KEYS = {
    "QA12": "docs/design/E12/E12-D13.md",
    "P02": "docs/plan/02-definition-of-ready-done.md",
    "P14": "docs/plan/14-screens-catalogue.md",
}
CODE_KEYS = {
    "DEN": "packages/chart-engine/src/theme/Density.ts",
    "SLOTS": "packages/chart-engine/src/theme/slots.ts",
    "MOM": "packages/chart-engine/src/interaction/momentum.ts",
    "MOT": "packages/chart-engine/src/host/motion.ts",
    "GES": "packages/chart-engine/src/interaction/gestures.ts",
    "CHART": "packages/chart-engine/src/api/chart.ts",
    "BADGE": "packages/chart-engine/src/host/scale-badge.ts",
    "PSM": "apps/web/src/features/chart-price-scale/PriceScaleMenu.tsx",
    "PSC": "apps/web/src/features/chart-price-scale/copy.ts",
    "CTP": "apps/web/src/chart/a11y/ChartTablePanel.tsx",
    "CTC": "apps/web/src/chart/a11y/chartTable.css",
    "TBC": "apps/web/src/chart/a11y/copy.ts",
    "CES": "apps/web/src/features/chart-errors/ChartErrorSurface.tsx",
    "CESC": "apps/web/src/features/chart-errors/copy.ts",
    "SEMD": f"{TOKENS}/semantic-dark.tokens.json",
}
KEYS = {**DESIGN_KEYS, **OWNER_KEYS, **CODE_KEYS}
# The built chart surfaces the token scans read (TK-03, TK-04).
BUILT = ("DEN", "SLOTS", "BADGE", "PSM", "PSC", "CTP", "CTC", "TBC", "CES", "CESC", "MOT")
# Copy files and the spec that owns their words (CP).
COPY_OWNERS = {"PSC": "D03", "CESC": "D04", "TBC": "D04", "BADGE": "D03", "MOT": "D06"}
THEMES = ("dark", "light", "high-contrast")
BARS = {"text": 4.5, "non-text": 3.0}
HC_TEXT_BAR = 7.0
CITE = re.compile(
    r"`(" + "|".join(sorted(KEYS, key=len, reverse=True)) + r")`:(\d+)(?:[\u2013-](\d+))?"
)
AUDIT = re.compile(r"<!-- audit:([\w.-]+)=([^>]*?) -->")
HEX_LITERAL = re.compile(r"#[0-9A-Fa-f]{3,8}\b|\brgba?\(|\bhsla?\(")
CSS_VAR = re.compile(r"var\(--([\w-]+)")
# The public-text scrub list, rot13 so this file does not itself carry the words.
BANNED_ROT13 = (
    "cer-nhgu yrnx rkcbfrq olcnff rkcybvg nggnpx benpyr erirny haobhaqrq sybbq fgnyy qbf "
    "nqivfbel tufn"
)
BANNED = re.compile(
    "|".join(
        r"\b" + re.escape(w) + r"\b" if len(w) <= 3 else re.escape(w)
        for w in codecs.decode(BANNED_ROT13, "rot13").split()
    ),
    re.IGNORECASE,
)
# E11-D09 row ids cited by the five checks (R §2, M §5, T §6, S §7), and their table rows.
D09_ID = re.compile(r"(?<![\w-])(R-\d{2}|T-\d{2}|S-\d{3}|M-\d{1,2})(?![\w-])")
D09_ROW = re.compile(r"^\| (R-\d{2}|T-\d{2}|S-\d{3}|\d{1,2}) +\|", re.MULTILINE)
SEVERITIES = ("Blocking", "Major", "Minor", "Info")
CLASSES = {
    "implementation defect": "defect",
    "specification gap": "gap",
    "accepted divergence": "accepted",
}
# The `14` sign-off checklists the ruling names (BQ-9): SCR-030, 031, 043 … 048.
CK_SCREENS = ("030", "031", "043", "044", "045", "046", "047", "048")
LOCAL_PATH = re.compile(r"/(?:home|mnt|tmp)/")
CLOSING = re.compile(r"\b(?:close[sd]?|fix(?:e[sd])?|resolve[sd]?) #\d+", re.IGNORECASE)

Reader = Callable[[str], str]


# ------------------------------------------------------------------------------- git and reads --
def git(*args: str) -> str:
    out = subprocess.run(
        [GIT, "-C", str(ROOT), *args],
        capture_output=True,
        text=True,
        check=True,
        timeout=60,
    )
    return out.stdout


def base_sha(spec: str) -> str:
    m = re.search(r"<!-- audit:sha=([0-9a-f]{10}) -->", spec)
    if m is None:
        raise SystemExit("the spec carries no audit:sha marker")
    return m.group(1)


def reader_at(rev: str) -> Reader:
    cache: dict[str, str] = {}

    def read(rel: str) -> str:
        if rel not in cache:
            cache[rel] = git("show", f"{rev}:{rel}")
        return cache[rel]

    return read


def patched(read: Reader, patches: Mapping[str, Callable[[str], str]]) -> Reader:
    return lambda rel: patches[rel](read(rel)) if rel in patches else read(rel)


def section(text: str, heading: str) -> str:
    """The lines of the section whose heading starts with `heading`, to the next of its level."""
    lines = text.splitlines()
    for i, line in enumerate(lines):
        if line.startswith(heading):
            level = len(line) - len(line.lstrip("#"))
            end = next(
                (
                    j
                    for j in range(i + 1, len(lines))
                    if lines[j].startswith("#")
                    and len(lines[j]) - len(lines[j].lstrip("#")) <= level
                ),
                len(lines),
            )
            return "\n".join(lines[i:end])
    raise SystemExit(f"section not found: {heading}")


def cells(line: str) -> list[str]:
    return [c.strip() for c in line.strip().strip("|").split("|")]


# -------------------------------------------------------------------------------------- tokens --
def theme_tokens(read: Reader) -> dict[str, dict[str, str]]:
    """Every token resolved per theme, layered as `themes.json` lists the sets."""
    spec = json.loads(read(f"{TOKENS}/themes.json"))
    out: dict[str, dict[str, str]] = {}
    for theme in spec["themes"]:
        raw: dict[str, object] = {}
        for name in theme["sets"]:
            raw.update(json.loads(read(f"{TOKENS}/{name}.tokens.json")))
        out[theme["name"]] = {k: str(resolve(k, raw)) for k in raw}
    return out


def resolve(name: str, raw: Mapping[str, object], depth: int = 0) -> object:
    entry = raw[name]
    value = entry["$value"] if isinstance(entry, dict) else entry
    if isinstance(value, str) and value.startswith("{") and value.endswith("}") and depth < 20:
        return resolve(value[1:-1], raw, depth + 1)
    return value


def luminance(hex6: str) -> float:
    def lin(c: int) -> float:
        s = c / 255
        return s / 12.92 if s <= 0.04045 else ((s + 0.055) / 1.055) ** 2.4

    r, g, b = (int(hex6[i : i + 2], 16) for i in (1, 3, 5))
    return 0.2126 * lin(r) + 0.7152 * lin(g) + 0.0722 * lin(b)


def ratio(a: str, b: str) -> float:
    la, lb = sorted((luminance(a), luminance(b)), reverse=True)
    return (la + 0.05) / (lb + 0.05)


# ----------------------------------------------------------------------------------- measures --
@dataclass
class Result:
    values: dict[str, str] = field(default_factory=dict)
    lists: dict[str, list[str]] = field(default_factory=dict)


def tk01_slot_bindings(read: Reader, tok: Mapping[str, Mapping[str, str]], res: Result) -> None:
    """D05 §4.1 / §4.1b 'Resolved' column against the shipped alias resolved per theme."""
    d05 = read(DESIGN_KEYS["D05"])
    rows = [
        cells(line)
        for part in ("### 4.1 Chart chrome slots", "### 4.1b Engine-chrome aliases")
        for line in section(d05, part).splitlines()
        if line.startswith("| `color.chart.")
    ]
    expected: dict[str, list[str]] = {}
    previous: list[str] = []
    for row in rows:
        slot, text = row[0].strip("`"), row[2]
        hexes = re.findall(r"#[0-9A-Fa-f]{6}", text)
        if text.startswith("as "):
            hexes = list(expected[f"color.chart.{text[3:].strip()}"])
        elif text == "identical":
            hexes = list(previous)
        elif "(off)" in text:
            hexes = [*hexes, ""]  # high-contrast filled below
        expected[slot] = hexes
        previous = hexes
    # "(off)" in high-contrast is the pane fill: the minor line drawn in the canvas colour.
    canvas = expected["color.chart.pane.bg.default"]
    expected["color.chart.grid.minor"][2] = canvas[2]
    mismatched = [
        f"{slot}@{theme}: shipped {tok[theme][slot]} spec {want[i]}"
        for slot, want in expected.items()
        for i, theme in enumerate(THEMES)
        if tok[theme].get(slot, "?").upper() != want[i].upper()
    ]
    res.values["tk01.slots"] = str(len(expected))
    res.values["tk01.cells"] = str(len(expected) * len(THEMES))
    res.values["tk01.mismatch"] = str(len(mismatched))
    res.lists["tk01.mismatch"] = mismatched


def tk02_pairs(read: Reader, tok: Mapping[str, Mapping[str, str]], res: Result) -> None:
    pairs = re.findall(
        r'pair\("([\w.-]+)", "([\w-]+)"(?:, "([\w.-]+)")?\)', read(CODE_KEYS["SLOTS"])
    )
    fails: list[str] = []
    hc_short: list[str] = []
    gated = 0
    lows: dict[str, float] = {}
    for fg, cls, bg in pairs:
        bg = bg or "color.chart.pane.bg.default"
        for theme in THEMES:
            r = ratio(tok[theme][fg], tok[theme][bg])
            if cls in BARS:
                gated += 1
                lows[cls] = min(lows.get(cls, 99.0), r)
                if r < BARS[cls]:
                    fails.append(f"{fg} on {bg} @{theme}: {r:.2f} < {BARS[cls]}")
                if cls == "text" and theme == "high-contrast" and r < HC_TEXT_BAR:
                    hc_short.append(f"{fg} on {bg}: {r:.2f}")
    res.values["tk02.pairs"] = str(len(pairs))
    res.values["tk02.gated"] = str(gated)
    res.values["tk02.fail"] = str(len(fails))
    res.values["tk02.min.text"] = f"{lows['text']:.2f}"
    res.values["tk02.min.nontext"] = f"{lows['non-text']:.2f}"
    res.values["tk02.hc7.short"] = str(len(hc_short))
    res.lists["tk02.fail"] = fails
    res.lists["tk02.hc7.short"] = hc_short


def code_lines(text: str) -> list[tuple[int, str]]:
    """(line, text) for lines that are not comments."""
    out: list[tuple[int, str]] = []
    in_block = False
    for n, line in enumerate(text.splitlines(), 1):
        s = line.strip()
        if in_block:
            in_block = "*/" not in s
            continue
        if s.startswith("/*"):
            in_block = "*/" not in s
            continue
        if s.startswith(("//", "*", "{/*")):
            continue
        out.append((n, line))
    return out


def tk03_tk04_scans(read: Reader, tok: Mapping[str, Mapping[str, str]], res: Result) -> None:
    names = set(tok["dark"])
    composite_fields = ("font-family", "font-size", "font-weight", "line-height")
    known = {n.replace(".", "-") for n in names}
    known |= {
        f"{n.replace('.', '-')}-{f}"
        for n in names
        if n.startswith("type.")
        for f in composite_fields
    }
    hits: list[str] = []
    unknown: list[str] = []
    used: set[str] = set()
    for key in BUILT:
        for n, line in code_lines(read(CODE_KEYS[key])):
            if HEX_LITERAL.search(line):
                hits.append(f"{key}:{n}")
            for var in CSS_VAR.findall(line):
                used.add(var)
                if var not in known:
                    unknown.append(f"{key}:{n} --{var}")
    res.values["tk03.files"] = str(len(BUILT))
    res.values["tk03.hits"] = str(len(hits))
    res.values["tk04.vars"] = str(len(used))
    res.values["tk04.unknown"] = str(len(unknown))
    res.lists["tk03.hits"] = hits
    res.lists["tk04.unknown"] = unknown


def dn_density(read: Reader, res: Result) -> None:
    d02 = section(read(DESIGN_KEYS["D02"]), "## 6. Density triples")
    axis = re.search(r"`axisFontSizeClass` \((\d) / (\d) / (\d)", d02)
    if axis is None:
        raise SystemExit("D02 §6: axisFontSizeClass triple not found")
    spec: dict[str, tuple[int, ...]] = {}
    for i, mode in enumerate(("comfortable", "compact", "dense")):
        row = next(cells(x) for x in d02.splitlines() if x.startswith(f"| **{mode}**"))
        lod = re.search(r"[+]?(\d+)", row[3].replace("*", ""))
        gaps = re.findall(r"\d+", row[5])
        if lod is None or len(gaps) != 2:
            raise SystemExit(f"D02 §6: row {mode} unreadable")
        spec[mode] = (
            int(row[1]),
            int(row[2][0]),
            int(axis.group(i + 1)),
            int(lod.group(1)),
            int(gaps[0]),
            int(gaps[1]),
        )
    built = {
        m: tuple(int(v) for v in vals)
        for m, *vals in re.findall(
            r'rec\("(\w+)", (\d+), (\d), (\d), (\d+), (\d+), (\d+)\)', read(CODE_KEYS["DEN"])
        )
    }
    diff = [f"{m}: built {built.get(m)} spec {v}" for m, v in spec.items() if built.get(m) != v]
    res.values["dn.values"] = str(sum(len(v) for v in spec.values()))
    res.values["dn.mismatch"] = str(len(diff))
    res.lists["dn.mismatch"] = diff


MO_SPEC = {
    "tauMs": r"τ = (\d+) ms",
    "stopPxPerMs": r"when `\\\|v\\\| < ([\d.]+) px/ms`",
    "ewmaMs": r"in the last (\d+) ms before pointer-up",
    "stillMs": r"still for > (\d+) ms",
    "minPxPerMs": r"`\\\|v₀\\\| < ([\d.]+) px/ms`",
    "capWidths": r"Maximum fling distance ([\d.]+) viewport widths",
}


def mo_momentum(read: Reader, res: Result) -> None:
    d06 = section(read(DESIGN_KEYS["D06"]), "## 2. Decisions at a glance")
    built = dict(re.findall(r"^\s+(\w+): ([\d.]+),$", read(CODE_KEYS["MOM"]), re.MULTILINE))
    diff: list[str] = []
    for name, pattern in MO_SPEC.items():
        m = re.search(pattern, d06)
        if m is None:
            diff.append(f"{name}: not found in D06 §2")
        elif float(built.get(name, "nan")) != float(m.group(1)):
            diff.append(f"{name}: built {built.get(name)} spec {m.group(1)}")
    reduce_src = read(CODE_KEYS["MOT"])
    anim = [
        f"{key}:{n}"
        for key in BUILT
        for n, line in code_lines(read(CODE_KEYS[key]))
        if re.search(r"\b(?:transition|animation)(?:-[a-z]+)?\s*[:=]|@keyframes", line)
    ]
    res.values["mo.anim"] = str(len(anim))
    res.lists["mo.anim"] = anim
    res.values["mo.values"] = str(len(MO_SPEC))
    res.values["mo.mismatch"] = str(len(diff))
    res.values["mo.mediaquery"] = str(reduce_src.count("matchMedia"))
    res.lists["mo.mismatch"] = diff


def literals(text: str) -> list[str]:
    """User-facing string literals: `key: "…"`, `= "…"` and template fragments; imports skipped."""
    out: list[str] = []
    for _, line in code_lines(text):
        if line.lstrip().startswith(("import", "export type", "type ")):
            continue
        for m in re.finditer(r'(?::|=|\?\?|\()\s*"((?:[^"\\]|\\.)*)"', line):
            out.append(m.group(1))
        for m in re.finditer(r"`([^`]*)`", line):
            out.extend(p for p in re.split(r"\$\{[^}]*\}", m.group(1)))
    return [s.strip(" .;:}") for s in out if re.search(r"[A-Z][a-z]+ [a-z]", s)]


def cp_copy(read: Reader, res: Result) -> None:
    missing: list[str] = []
    total = 0
    for key, owner in COPY_OWNERS.items():
        spec = read(DESIGN_KEYS[owner])
        for s in literals(read(CODE_KEYS[key])):
            total += 1
            if s not in spec:
                missing.append(f"{key} → {owner}: {s}")
    res.values["cp.strings"] = str(total)
    res.values["cp.missing"] = str(len(missing))
    res.lists["cp.missing"] = missing


def sb_badge(read: Reader, res: Result) -> None:
    src = read(CODE_KEYS["BADGE"])
    d03 = section(read(DESIGN_KEYS["D03"]), "## 5. The scale-lock badge")
    rest = next(cells(x) for x in d03.splitlines() if x.startswith("| **resting**"))
    want = set(re.findall(r"`(color\.[\w.-]+)`", rest[1]))
    have = set(re.findall(r'theme\["(color\.[\w.-]+)"\]', src))
    states = {"hover": "color.surface.hover", "active": "color.surface.selected"}
    absent = [s for s, t in states.items() if t not in src]
    if not re.search(r"outline|focus", src.split("const make", 1)[1].split("return el", 1)[0]):
        absent.append("focus")
    res.values["sb.resting"] = "match" if want == have else f"diff {sorted(want ^ have)}"
    res.values["sb.absent"] = ", ".join(absent) or "none"


def eq_view_switch(read: Reader, res: Result) -> None:
    src = read(CODE_KEYS["CTP"])
    importers = [
        p
        for p in git("ls-tree", "-r", "--name-only", res.values["sha"], "apps/web/src").split()
        if p.endswith((".ts", ".tsx"))
        and ".test." not in p
        and p != CODE_KEYS["CTP"]
        and "ChartTablePanel" in read(p)
    ]
    res.values["eq.mounts"] = str(len(importers))
    res.values["eq.role"] = "radiogroup" if 'role="radiogroup"' in src else "group + aria-pressed"
    res.values["eq.glyph"] = "present" if "icon" in src.lower() else "absent"


def table_rows(spec: str, prefix: str) -> list[list[str]]:
    return [cells(x) for x in spec.splitlines() if x.startswith(f"| {prefix}")]


def rg_register(spec: str, read: Reader, res: Result) -> None:
    """The record's own tables: surfaces, findings, G-rows, D09 ids, the `14` checklists."""
    su = [r[3].strip("`") for r in table_rows(spec, "SU-") if len(r) == 5]
    res.values["su"] = str(len(su))
    for key, word in (("part", "compared-in-part"), ("deferred", "deferred-owned")):
        res.values[f"su.{key}"] = str(su.count(word))
    res.values["su.unowned"] = str(su.count("deferred-unowned"))
    df = [r for r in table_rows(spec, "DF-") if len(r) == 6]
    res.values["df"] = str(len(df))
    for sev in SEVERITIES:
        res.values[f"df.{sev.lower()}"] = str(sum(r[2] == sev for r in df))
    for word, key in CLASSES.items():
        res.values[f"df.{key}"] = str(sum(r[1] == word for r in df))
    res.lists["df.unknown"] = [r[0] for r in df if r[2] not in SEVERITIES or r[1] not in CLASSES]
    res.values["g"] = str(len(table_rows(spec, "G-")))
    d09 = read(DESIGN_KEYS["D09"])
    have = {m if not m.isdigit() else f"M-{m}" for m in D09_ROW.findall(d09)}
    cited = set(D09_ID.findall(spec))
    res.lists["d09.unknown"] = sorted(cited - have)
    p14 = read(OWNER_KEYS["P14"])
    items = 0
    for scr in CK_SCREENS:
        part = section(p14, f"### SCR-{scr} ")
        line = next(x for x in part.splitlines() if "sign-off acceptance checklist" in x)
        items += len(re.findall(r"\[[ x]\]", line))
    ck = table_rows(spec, "CK-")
    res.values["ck"] = str(items)
    res.values["ck.rows"] = str(len(ck))
    res.values["ck.ticked"] = str(sum(r[-1].startswith("[x]") for r in ck))


def measure(read: Reader, sha: str, spec: str) -> Result:
    res = Result(values={"sha": sha})
    rg_register(spec, read, res)
    tok = theme_tokens(read)
    tk01_slot_bindings(read, tok, res)
    tk02_pairs(read, tok, res)
    tk03_tk04_scans(read, tok, res)
    dn_density(read, res)
    mo_momentum(read, res)
    cp_copy(read, res)
    sb_badge(read, res)
    eq_view_switch(read, res)
    return res


# ------------------------------------------------------------------------------- spec gates --
def line_hash(s: str) -> str:
    return hashlib.sha1(" ".join(s.split()).encode(), usedforsecurity=False).hexdigest()[:16]


def cited(spec: str) -> list[tuple[str, int]]:
    out: set[tuple[str, int]] = set()
    for m in CITE.finditer(spec):
        out.add((m.group(1), int(m.group(2))))
        if m.group(3):
            out.add((m.group(1), int(m.group(3))))
    return sorted(out)


def pin_lines(spec: str, read: Reader) -> list[str]:
    out = []
    for key, n in cited(spec):
        lines = read(KEYS[key]).splitlines()
        words = lines[n - 1] if 0 < n <= len(lines) else ""
        out.append(f"{key}:{n} {line_hash(words)}")
    return out


def gate(spec: str, pins: str, read: Reader, res: Result) -> list[str]:
    fails: list[str] = []
    markers = AUDIT.findall(spec)
    for name, value in markers:
        if name not in res.values:
            fails.append(f"audit marker with no computed value: {name}")
        elif res.values[name] != value.strip():
            fails.append(f"audit {name}: spec {value.strip()!r} computed {res.values[name]!r}")
    unmarked = set(res.values) - {n for n, _ in markers}
    fails += [f"computed value not recorded in the spec: {n}" for n in sorted(unmarked)]
    fails += [f"D09 row id not in E11-D09: {x}" for x in res.lists.get("d09.unknown", [])]
    fails += [f"DF row off the ruled scale: {x}" for x in res.lists.get("df.unknown", [])]
    if res.values.get("ck") != res.values.get("ck.rows"):
        fails.append("the CK table does not list every `14` checklist item")
    have = {x for x in pins.splitlines() if x and not x.startswith("#")}
    want = set(pin_lines(spec, read))
    fails += [f"cite not pinned or its words moved: {x}" for x in sorted(want - have)]
    fails += [f"stale pin: {x}" for x in sorted(have - want)]
    for n, line in enumerate(spec.splitlines(), 1):
        for pat, what in ((BANNED, "scrub word"), (LOCAL_PATH, "local path"), (CLOSING, "closer")):
            if pat.search(line):
                fails.append(f"spec:{n}: {what}")
    return fails


# ---------------------------------------------------------------------------------- self-test --
def self_test(spec: str, pins: str, read: Reader, sha: str) -> list[str]:
    def sub(old: str, new: str) -> Callable[[str], str]:
        def f(text: str) -> str:
            if old not in text:
                raise SystemExit(f"self-test: anchor not found: {old!r}")
            return text.replace(old, new, 1)

        return f

    mutations: dict[str, tuple[dict[str, Callable[[str], str]], str, str]] = {
        "DN": ({CODE_KEYS["DEN"]: sub('"dense", 1, 0', '"dense", 2, 0')}, spec, pins),
        "MO": ({CODE_KEYS["MOM"]: sub("tauMs: 120", "tauMs: 140")}, spec, pins),
        "TK-03": ({CODE_KEYS["CTC"]: sub("display: flex;", "color: #ff0000;")}, spec, pins),
        "TK-04": (
            {CODE_KEYS["CTC"]: sub("--color-text-primary", "--color-text-primry")},
            spec,
            pins,
        ),
        "TK-01": (
            {
                f"{TOKENS}/semantic-dark.tokens.json": sub(
                    "{color.text.inverse}", "{color.text.primary}"
                )
            },
            spec,
            pins,
        ),
        "CP": ({CODE_KEYS["PSC"]: sub('"Lock scale"', '"Lock the scale"')}, spec, pins),
        "EQ": ({CODE_KEYS["CTP"]: sub('role="group"', 'role="radiogroup"')}, spec, pins),
        "pin": ({}, spec, pins.replace(pins.splitlines()[-1], pins.splitlines()[-1][:-1] + "0", 1)),
        "D09": ({}, spec.replace("R-26: 24 px", "R-99: 24 px", 1), pins),
        "DF": ({}, spec.replace("| Blocking |", "| High |", 1), pins),
        "CK": (
            {OWNER_KEYS["P14"]: sub("[ ] 'reset scale' item", "[ ] 'reset scale' item [ ] extra")},
            spec,
            pins,
        ),
        "scrub": ({}, spec + "\n" + codecs.decode("na haobhaqrq dhrhr", "rot13") + "\n", pins),
    }
    caught: list[str] = []
    for name, (patches, s, p) in mutations.items():
        r = patched(read, patches)
        if gate(s, p, r, measure(r, sha, s)):
            caught.append(name)
    return [n for n in mutations if n not in caught]


# --------------------------------------------------------------------------------------- main --
def main(argv: list[str]) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0] if __doc__ else None)
    ap.add_argument("--check", action="store_true")
    ap.add_argument("--json", action="store_true")
    ap.add_argument("--self-test", action="store_true")
    ap.add_argument("--repin", action="store_true")
    args = ap.parse_args(argv)
    spec = (ROOT / SPEC_REL).read_text(encoding="utf-8")
    sha = base_sha(spec)
    read = reader_at(sha)
    if args.repin:
        head = (
            "# E11-D08 pins: one cited line per row, `KEY:line sha1-16` of its words at the base.\n"
        )
        body = "\n".join(pin_lines(spec, read))
        (ROOT / PINS_REL).write_text(head + body + "\n", encoding="utf-8")
        print(f"repinned {len(body.splitlines())} cites")
        return 0
    pins = (ROOT / PINS_REL).read_text(encoding="utf-8")
    res = measure(read, sha, spec)
    if args.self_test:
        missed = self_test(spec, pins, read, sha)
        print("self-test:", "PASS" if not missed else f"FAIL (not caught: {', '.join(missed)})")
        return 1 if missed else 0
    fails = gate(spec, pins, read, res)
    if args.json:
        print(json.dumps({"values": res.values, "lists": res.lists, "fail": fails}, indent=2))
    else:
        for k, v in sorted(res.values.items()):
            print(f"{k} = {v}")
        for k, items in sorted(res.lists.items()):
            for item in items:
                print(f"  {k}: {item}")
        print(f"FAIL {len(fails)}")
        for f in fails:
            print(f"  FAIL {f}")
    return 1 if (args.check and fails) else 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
