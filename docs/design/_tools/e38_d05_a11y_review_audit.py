#!/usr/bin/env python3
"""E38-D05 (#1076) audit: the accessibility design review of the E38 surfaces.

Standalone, offline, stdlib only; run it with `python3 -I`. It reads the review and the
pins file from the working tree, and every cited file AS TEXT with `git show`: the plan
docs, E09-D09, E10-D04 and the design-spec rules at the pinned base (`BASE`), and the
three open parents at their pinned heads (`REF_OF`): E38-D02 at #5494's, E38-D03 at
#5493's and E38-D04 at #5490's, each "if it merges as is". For the colour figures it
imports `packages/ui/tokens/tests/verify_tokens.py` (the token loader and resolver),
`docs/design/_tools/contrast_check.py` (`contrast_ratio`) and
`docs/research/_tools/cvd_simulate.py` (`simulate`, `delta_e76`, `JND_FLOOR`) from the
working tree and never re-implements them. Default-deny: a gate that cannot read its
input FAILs.

Gates (each FAIL led by its name):
  G-FINDING   §9's F rows in order; each severity from R-1's set; each closing "fix:
              A-n" with §10 carrying A-n, "routed: ..." or "accepted: ..."; every
              Blocking and Major closes by an A-row (R-2); the heading's counts equal
              the rows; every F id the review names is a §9 row.
  G-NAMES     the six screen sections of §3 exist, each with its N rows in order, and
              every N row names its element with a non-empty accessible name (AC 1).
  G-PATH      §4's W rows are in order and cover the pill, the popover, the typed
              confirmation, the step-up and the completion; each has a focus target and
              a visible-focus note (AC 4).
  G-T2        every §5 row is T2 or V; a T2 reason is an E09-D09 §3.1 key's string at
              the base (its slot filled), another key's text on its cited line, or
              PROPOSED with its owner; a typed gate is V and carries no key.
  G-CONTRAST  every §6.1 row recomputed per theme (dark, light, high-contrast as
              verify_tokens merges them) equals the review to two decimals; `text` rows
              are at least 4.5:1 and `ui` rows at least 3:1 in every theme; the verdict
              matches.
  G-CVD       every §6.2 row's four ΔE76 figures and its JND column equal the tool's;
              DEMO vs LIVE stays above the JND in every simulation.
  G-AROW      every A-row's Old text or anchor stands exactly once in its parent at its
              ref.
  G-CITE      every cite in range and on a non-blank line at its ref, its content equal
              to the pins file's hash; the SHA anchors are the pinned refs.
  G-HYGIENE   no closing keyword, local path, URL or host, agent name, double-brace slot
              or public-text deny word in the review, this tool or the pins file; no
              unknown anchor.
  G-SCOPE     the diff against `git merge-base HEAD origin/main` touches only the
              review, this tool and the pins file.

Usage (from the repo root):
  python3 -I docs/design/_tools/e38_d05_a11y_review_audit.py --check
  python3 -I docs/design/_tools/e38_d05_a11y_review_audit.py --fill
  python3 -I docs/design/_tools/e38_d05_a11y_review_audit.py --self-test
  python3 -I docs/design/_tools/e38_d05_a11y_review_audit.py --repin-ruled
  (--check exits 1 on any FAIL; --fill writes §6's figures; --repin-ruled is
  the pins file's only writer)
"""

from __future__ import annotations

import argparse
import hashlib
import importlib.util
import re
import subprocess
import sys
from collections.abc import Callable
from dataclasses import dataclass, replace
from pathlib import Path
from types import ModuleType
from typing import Any

ROOT = Path(__file__).resolve().parents[3]
SPEC_REL = "docs/design/E38/E38-D05.md"
TOOL_REL = "docs/design/_tools/e38_d05_a11y_review_audit.py"
PINS_REL = "docs/design/_tools/e38_d05_ruled_pins.txt"
OWN_PATHS = (SPEC_REL, TOOL_REL, PINS_REL)
BASE = "1c4f51bb5dbeb167627749a04d6ad426e26bf5e6"  # origin/main; re-pinned (BQ-04)
D02_REF = "17e0086b76bc048b47193a85c2650fd157adb6cd"  # #5494's head (E38-D02)
D03_REF = "133a45628ebca6b5955aa89d0208b92efb64d52a"  # #5493's head (E38-D03)
D04_REF = "2c47253340e130e6b88d25ed209fd1666e01418d"  # #5490's head (E38-D04)
TOKENS = ROOT / "packages" / "ui" / "tokens"
CVD_PATH = ROOT / "docs" / "research" / "_tools" / "cvd_simulate.py"
CONTRAST_PATH = ROOT / "docs" / "design" / "_tools" / "contrast_check.py"
PATHS: dict[str, str] = {
    "05": "docs/plan/05-accessibility-standard.md",
    "14": "docs/plan/14-screens-catalogue.md",
    "15": "docs/plan/15-component-catalogue.md",
    "D02": "docs/design/E38/E38-D02.md",
    "D03": "docs/design/E38/E38-D03.md",
    "D04": "docs/design/E38/E38-D04.md",
    "DS": ".claude/rules/32-design-specs.md",
    "E09D09": "docs/design/E09/E09-D09.md",
    "E10D04": "docs/design/E10/E10-D04.md",
}
REF_OF = {"D02": D02_REF, "D03": D03_REF, "D04": D04_REF}
# the A-row headers name their parents in these words
PARENT_WORDS = {"E38-D02": "D02", "E38-D03": "D03", "E38-D04": "D04"}
SEVERITIES = ("Blocking", "Major", "Minor", "Info")
# the six screens of the ticket's Scope, each a §3 subsection with its row prefix
SCREENS = (
    ("### 3.1 SCR-074", "N74"),
    ("### 3.2 SCR-075", "N75"),
    ("### 3.3 SCR-079", "N79"),
    ("### 3.4 SCR-099", "N99"),
    ("### 3.5 SCR-122", "N122"),
    ("### 3.6 SCR-137", "N137"),
)
# AC 4: the path from the badge to completion, each step named by a word in
# its Step cell
PATH_STEPS = ("pill", "popover", "typed", "step-up", "completion")
DASH = "–"  # the en dash of a cited range
KEYS = r"\d\d|D0[234]|DS|E09D09|E10D04"
CITE = re.compile(rf"`({KEYS})`:(\d+(?:{DASH}\d+)?(?:, :\d+(?:{DASH}\d+)?)*)")
ANCHOR = re.compile(r"`?([^\s<|(`]+)`?<!--=([A-Z]+:[A-Za-z0-9.]+)-->")
CLOSING = re.compile(
    r"\b(?:close[sd]?|fix(?:e[sd])?|resolve[sd]?)\s+#\d+", re.IGNORECASE
)
LOCAL_PATH = re.compile(
    "/" + "home/|/Users/|[A-Za-z]:\\\\|\\bwt-" + "notes\\b"
)  # assembled
AGENT_NAME = re.compile(r"\b[a-z]{2,4}-worker-\d\b")
URL_OR_HOST = re.compile(r"https?://|penpot\.[a-z]|team-id=|file-id=", re.IGNORECASE)
# assembled with an explicit +, so the formatter keeps the split and the tool
# never spells a word
DENY = (
    "le" + "ak",
    "expo" + "sed",
    "by" + "pass",
    "ex" + "ploit",
    "att" + "ack",
    "ora" + "cle",
    "rev" + "eal",
    "unbou" + "nded",
    "flo" + "od",
    "st" + "all",
    "d" + "os",
    "advi" + "sory",
    "gh" + "sa",
    "pre-" + "auth",
)
THEMES = ("dark", "light", "high-contrast")
FLOOR = {"text": 4.5, "ui": 3.0}
DEFICIENCIES = ("protanopia", "deuteranopia", "tritanopia")
# the CVD pair held above the JND in every simulation (BQ-11); the rest are reported
GATED_CVD = ("color.env.demo", "color.env.live")


@dataclass(frozen=True)
class Texts:
    spec: str
    pins: str
    tool: str
    changed: list[str] | None
    memo: dict[str, str | None]


def git(*args: str) -> str | None:
    try:
        # git with fixed arguments and no shell; the only external program it runs
        r = subprocess.run(
            ["git", "-C", str(ROOT), *args], capture_output=True, check=False
        )
    except OSError:
        return None
    return r.stdout.decode("utf-8", "surrogateescape") if r.returncode == 0 else None


def show(t: Texts, rev: str, rel: str) -> str | None:
    key = f"{rev}:{rel}"
    if key not in t.memo:
        t.memo[key] = git("show", key)
    return t.memo[key]


def at(t: Texts, key: str) -> str:
    ref = REF_OF.get(key, BASE)
    text = show(t, ref, PATHS[key])
    if text is None:
        raise SystemExit(
            f"{PATHS[key]} does not resolve at {ref[:10]}; fetch the parents' heads"
        )
    return text


def norm(s: str) -> str:
    return " ".join(s.split())


def cells(line: str) -> list[str]:
    return [c.strip() for c in line.strip().strip("|").split("|")]


def rows(text: str, lead: str) -> list[list[str]]:
    return [cells(ln) for ln in text.split("\n") if re.match(rf"\| {lead}-\d+ ", ln)]


def section(text: str, head: str) -> str:
    i = text.find("\n" + head)
    if i < 0:
        return ""
    depth = head.split(" ")[0]
    j = text.find("\n" + depth + " ", i + 1)
    k = text.find("\n## ", i + 1) if depth != "##" else -1
    ends = [x for x in (j, k) if x > 0]
    return text[i : min(ends) if ends else len(text)]


# ---------------------------------------------------------------------------- colour


def _load(path: Path, name: str) -> ModuleType:
    spec = importlib.util.spec_from_file_location(name, path)
    if spec is None or spec.loader is None:
        raise SystemExit(f"cannot load {path}")
    mod = importlib.util.module_from_spec(spec)
    sys.modules[name] = mod
    spec.loader.exec_module(mod)
    return mod


_MODS: dict[str, ModuleType] = {}


def mod(name: str) -> ModuleType:
    if name not in _MODS:
        if name == "verify_tokens":
            sys.path.insert(0, str(TOKENS / "tests"))
            _MODS[name] = _load(TOKENS / "tests" / "verify_tokens.py", name)
        elif name == "contrast_check":
            _MODS[name] = _load(CONTRAST_PATH, name)
        else:
            _MODS[name] = _load(CVD_PATH, name)
    return _MODS[name]


_THEMES: dict[str, dict[str, str]] = {}


def theme(name: str) -> dict[str, str]:
    """The colour tokens of one theme, resolved as the merged E10-D03 tool does."""
    if name not in _THEMES:
        v = mod("verify_tokens")
        allt: dict[str, Any] = dict(v.load(v.PRIMITIVES))
        allt.update(v.merged_set(v.THEMES[name]))
        _THEMES[name] = {
            k: str(v.resolve(tok["$value"], allt)).upper()
            for k, tok in allt.items()
            if isinstance(tok, dict) and tok.get("$type") == "color"
        }
    return _THEMES[name]


def color(th: str, name: str) -> str:
    t = theme(th)
    if name not in t:
        raise LookupError(f"`{name}` does not resolve in {th}")
    return t[name][:7]


def hex_rgb(h: str) -> tuple[int, int, int]:
    h = h.lstrip("#")
    return int(h[0:2], 16), int(h[2:4], 16), int(h[4:6], 16)


def tok(cell: str) -> str:
    m = re.fullmatch(r"`([a-z0-9.-]+)`", cell)
    if not m:
        raise LookupError(f"{cell!r} is not one token")
    return m[1]


def contrast_values(row: list[str]) -> list[str]:
    cc = mod("contrast_check")
    fg, bg = tok(row[1]), tok(row[2])
    out = []
    for th in THEMES:
        ratio = float(cc.contrast_ratio(hex_rgb(color(th, fg)), hex_rgb(color(th, bg))))
        out.append(f"{ratio:.2f}")
    return out


def verdict(role: str, values: list[str]) -> str:
    floor = FLOOR.get(role)
    if floor is None:
        return "structure"
    return "pass" if min(map(float, values)) >= floor else "FAIL"


def cvd_values(row: list[str]) -> tuple[str, str]:
    cv = mod("cvd_simulate")
    th = {"hc": "high-contrast"}.get(row[3], row[3])
    ha, hb = color(th, tok(row[1])), color(th, tok(row[2]))
    ds = [float(cv.delta_e76(ha, hb))] + [
        float(cv.delta_e76(cv.simulate(ha, d), cv.simulate(hb, d)))
        for d in DEFICIENCIES
    ]
    jnd = float(cv.JND_FLOOR)
    under = [n for n, d in zip(("normal", *DEFICIENCIES), ds, strict=True) if d < jnd]
    return " / ".join(f"{d:.2f}" for d in ds), (", ".join(under) if under else "none")


# ---------------------------------------------------------------------------- values


def compute(t: Texts) -> dict[str, str]:
    v = {
        "SHA:BASE": BASE[:10],
        "SHA:D02": D02_REF[:10],
        "SHA:D03": D03_REF[:10],
        "SHA:D04": D04_REF[:10],
    }
    fs = rows(section(t.spec, "## 9."), "F")
    v["F:total"] = str(len(fs))
    for s in SEVERITIES:
        v[f"F:{s.lower()}"] = str(sum(r[1] == s for r in fs if len(r) > 1))
    return v


def anchor_problems(t: Texts, vals: dict[str, str], prefix: str) -> list[str]:
    return [
        f"`{key}` reads {value}; the tool derives {vals[key]}"
        for value, key in ANCHOR.findall(t.spec)
        if key.startswith(prefix) and key in vals and vals[key] != value
    ]


# ---------------------------------------------------------------------------- cites


def cites(text: str) -> list[tuple[str, int, int]]:
    out = []
    for m in CITE.finditer(text):
        for part in m[2].split(", :"):
            a, _, b = part.partition(DASH)
            out.append((m[1], int(a), int(b or a)))
    return out


def cite_hashes(t: Texts) -> tuple[dict[str, str], list[str]]:
    hashes: dict[str, str] = {}
    bad: list[str] = []
    for key, a, b in cites(t.spec):
        label = f"{key}:{a}" if a == b else f"{key}:{a}{DASH}{b}"
        if label in hashes:
            continue
        ls = at(t, key).split("\n")
        if not 0 < a <= b <= len(ls):
            bad.append(f"{label} is past the end of {PATHS[key]} ({len(ls)} lines)")
            continue
        blank = [n for n in (a, b) if not ls[n - 1].strip()]
        if blank:
            bad.append(f"{label}: line {blank[0]} is blank at its ref")
            continue
        hashes[label] = hashlib.sha256(
            (norm(ls[a - 1]) + "\n" + norm(ls[b - 1])).encode()
        ).hexdigest()[:12]
    return hashes, bad


def parse_pins(text: str) -> dict[str, str]:
    out = {}
    for ln in text.split("\n"):
        parts = ln.split("\t")
        if len(parts) == 2 and not ln.startswith("#"):
            out[parts[0]] = parts[1]
    return out


# ---------------------------------------------------------------------------- gates


def g_finding(t: Texts, vals: dict[str, str]) -> list[str]:
    fs = rows(section(t.spec, "## 9."), "F")
    arows = set(re.findall(r"\*\*(A-\d+) →", section(t.spec, "## 10.")))
    bad = []
    if [r[0] for r in fs] != [f"F-{i:02d}" for i in range(1, len(fs) + 1)]:
        bad.append("§9's F rows are not F-01 ... F-n in order")
    for r in fs:
        if len(r) != 6:
            bad.append(f"{r[0]}: {len(r)} cells, not 6")
            continue
        fid, sev, _, text, closing, owner = r
        if sev not in SEVERITIES:
            bad.append(f"{fid}: severity {sev!r} is not one of {', '.join(SEVERITIES)}")
        fix = re.fullmatch(r"fix: (A-\d+)", closing)
        if fix and fix[1] not in arows:
            bad.append(f"{fid}: closes by {fix[1]}, which §10 does not carry")
        if not fix and not re.match(r"(accepted|routed): \S", closing):
            bad.append(f"{fid}: the closing {closing!r} is no fix, route or acceptance")
        if sev in ("Blocking", "Major") and not fix:
            bad.append(f"{fid}: a {sev} finding that no A-row closes (R-2)")
        if not owner or not text:
            bad.append(f"{fid}: no finding text or no owner")
    known = {r[0] for r in fs}
    bad += [
        f"{fid} is named but §9 has no such row"
        for fid in sorted(set(re.findall(r"\bF-\d\d\b", t.spec)))
        if fid not in known
    ]
    return bad + anchor_problems(t, vals, "F:")


def g_names(t: Texts, vals: dict[str, str]) -> list[str]:
    bad = []
    three = section(t.spec, "## 3.")
    for head, lead in SCREENS:
        block = section(three, head)
        if not block:
            bad.append(f"§3 has no section {head[4:]!r}")
            continue
        ns = rows(block, lead)
        if not ns:
            bad.append(f"{head[4:]} has no {lead} rows")
        if [r[0] for r in ns] != [f"{lead}-{i:02d}" for i in range(1, len(ns) + 1)]:
            bad.append(f"{head[4:]}: the {lead} rows are not in order from 01")
        for r in ns:
            if len(r) != 7:
                bad.append(f"{r[0]}: {len(r)} cells, not 7")
                continue
            if not r[1] or r[3] in ("", "—"):
                bad.append(f"{r[0]}: no element or no accessible name (AC 1)")
    return bad


def g_path(t: Texts, vals: dict[str, str]) -> list[str]:
    ws = rows(section(t.spec, "## 4."), "W")
    bad = []
    if [r[0] for r in ws] != [f"W-{i:02d}" for i in range(1, len(ws) + 1)]:
        bad.append("§4's W rows are not W-01 ... W-n in order")
    for step in PATH_STEPS:
        if not any(step in r[1] for r in ws if len(r) > 1):
            bad.append(f"§4 has no step for the {step} (AC 4)")
    for r in ws:
        if len(r) != 6:
            bad.append(f"{r[0]}: {len(r)} cells, not 6")
            continue
        for col, what in ((3, "focus target"), (4, "visible-focus note")):
            if r[col] in ("", "—"):
                bad.append(f"{r[0]}: no {what}")
    return bad


def e09_keys(t: Texts) -> dict[str, str]:
    out = {}
    for ln in at(t, "E09D09").split("\n"):
        m = re.match(r'\| `(rbac\.[a-z_]+)`\s*\| "([^"]+)"', ln)
        if m:
            out[m[1]] = m[2]
    return out


def g_t2(t: Texts, vals: dict[str, str]) -> list[str]:
    keys = e09_keys(t)
    bad = []
    ts = rows(section(t.spec, "## 5."), "T")
    if not ts:
        return ["§5 has no T rows"]
    for r in ts:
        if len(r) != 7:
            bad.append(f"{r[0]}: {len(r)} cells, not 7")
            continue
        tid, _, control, cls, key, text, source = r
        typed = "typed" in control
        if cls not in ("T2", "V"):
            bad.append(f"{tid}: class {cls!r} is neither T2 nor V")
        if typed and cls != "V":
            bad.append(f"{tid}: a typed gate is form validity (V), not {cls}")
        if cls == "V":
            if key != "—":
                bad.append(f"{tid}: a V row carries a reason key")
            continue
        quote = re.fullmatch(r'"(.+)"', text)
        if not quote:
            bad.append(f"{tid}: the reason is not one quoted sentence")
            continue
        km = re.fullmatch(r"`([a-z_.]+)`(?: .*)?", key)
        if key.startswith("PROPOSED (") and key.endswith(")"):
            continue
        if not km:
            bad.append(f"{tid}: the key {key!r} is neither a key nor PROPOSED (owner)")
        elif km[1] in keys:
            pat = re.sub(r"\\\{\w+\\\}", ".+", re.escape(keys[km[1]]))
            if not re.fullmatch(pat, quote[1]):
                bad.append(f"{tid}: {quote[1]!r} is not {km[1]}'s {keys[km[1]]!r}")
        elif km[1].startswith("rbac."):
            bad.append(f"{tid}: {km[1]} is not an E09-D09 §3.1 key at the base")
        else:
            src = CITE.search(source)
            ls = at(t, src[1]).split("\n") if src else []
            n = int(src[2].split(DASH)[0].split(",")[0]) if src else 0
            if not (0 < n <= len(ls) and quote[1] in ls[n - 1]):
                bad.append(f"{tid}: {quote[1][:40]!r} is not on its cited line")
    return bad


def g_contrast(t: Texts, vals: dict[str, str]) -> list[str]:
    bad = []
    ps = rows(section(t.spec, "### 6.1"), "P")
    if not ps:
        return ["§6.1 has no contrast rows"]
    for r in ps:
        if len(r) != 8:
            bad.append(f"{r[0]}: {len(r)} cells, not 8")
            continue
        want = contrast_values(r)
        if r[4:7] != want:
            bad.append(f"{r[0]}: reads {r[4:7]}, the tokens give {want}")
        floor = FLOOR.get(r[3])
        if floor is not None and min(float(x) for x in want) < floor:
            bad.append(f"{r[0]}: below {floor}:1 for a `{r[3]}` pair")
        if r[7] != verdict(r[3], want):
            bad.append(f"{r[0]}: verdict reads {r[7]!r}, not {verdict(r[3], want)!r}")
    return bad


def g_cvd(t: Texts, vals: dict[str, str]) -> list[str]:
    bad = []
    vs = rows(section(t.spec, "### 6.2"), "V")
    if not vs:
        return ["§6.2 has no CVD rows"]
    for r in vs:
        if len(r) != 6:
            bad.append(f"{r[0]}: {len(r)} cells, not 6")
            continue
        ds, under = cvd_values(r)
        if r[4] != ds or r[5] != under:
            bad.append(f"{r[0]}: reads {r[4]} / {r[5]}, the tool gives {ds} / {under}")
        if (tok(r[1]), tok(r[2])) == GATED_CVD and under != "none":
            bad.append(f"{r[0]}: DEMO vs LIVE falls under the JND ({under})")
    return bad


def g_arow(t: Texts, vals: dict[str, str]) -> list[str]:
    """Each A-row is copy-ready: its Old text or its anchor stands exactly once in the
    parents its header names, at their refs."""
    bad = []
    for ln in section(t.spec, "## 10.").split("\n"):
        m = re.match(r"- \*\*(A-\d+) → ([^*]+)\*\*", ln)
        if not m:
            continue
        aid = m[1]
        parents = [key for word, key in PARENT_WORDS.items() if word in m[2]]
        if not parents:
            bad.append(f"{aid}: names no parent")
            continue
        body = ln[m.end() :]
        anchors = re.findall(r'Old: "(.+?)"\. New:', body)
        anchors += re.findall(r'(?:[Aa]fter|[Bb]efore) "(.+?)" add', body)
        if not anchors:
            bad.append(f"{aid}: names neither an Old text nor an anchor")
        for a in anchors:
            n = sum(at(t, p).count(a) for p in parents)
            if n != 1:
                bad.append(
                    f"{aid}: {a[:40]!r} stands {n} times in {', '.join(parents)}"
                )
    return bad


def g_cite(t: Texts, vals: dict[str, str]) -> list[str]:
    hashes, bad = cite_hashes(t)
    pinned = parse_pins(t.pins)
    for label, h in hashes.items():
        if label not in pinned:
            bad.append(f"cite {label} is unpinned: verify it by content, then repin")
        elif pinned[label] != h:
            bad.append(f"cite {label}: the line at its ref is not the pinned content")
    return bad + anchor_problems(t, vals, "SHA:")


def g_hygiene(t: Texts, vals: dict[str, str]) -> list[str]:
    bad = []
    checks = (
        (CLOSING, "a closing keyword (the closing line waits for the A-row PR)"),
        (LOCAL_PATH, "a local path"),
        (AGENT_NAME, "an agent name"),
        (URL_OR_HOST, "a URL or a host"),
    )
    for i, ln in enumerate(t.spec.split("\n"), 1):
        for rx, what in checks:
            if rx.search(ln):
                bad.append(f"spec:{i} carries {what}")
        if "{{" in ln:
            bad.append(f"spec:{i} carries a double-brace slot")
    for name, text in (("spec", t.spec), ("tool", t.tool), ("pins", t.pins)):
        for i, ln in enumerate(text.split("\n"), 1):
            if any(d in ln.lower() for d in DENY):
                bad.append(f"{name}:{i} carries a public-text deny word")
    for _, key in ANCHOR.findall(t.spec):
        if key not in vals:
            bad.append(f"an anchor `{key}` the tool does not compute")
    return bad


def g_scope(t: Texts, vals: dict[str, str]) -> list[str]:
    if t.changed is None:
        return ["cannot list the changed paths (git failed)"]
    return [
        f"{p} is touched; this ticket owns {', '.join(OWN_PATHS)}"
        for p in t.changed
        if p not in OWN_PATHS
    ]


GATES: dict[str, Callable[[Texts, dict[str, str]], list[str]]] = {
    "G-FINDING": g_finding,
    "G-NAMES": g_names,
    "G-PATH": g_path,
    "G-T2": g_t2,
    "G-CONTRAST": g_contrast,
    "G-CVD": g_cvd,
    "G-AROW": g_arow,
    "G-CITE": g_cite,
    "G-HYGIENE": g_hygiene,
    "G-SCOPE": g_scope,
}


def audit(t: Texts) -> list[tuple[str, str]]:
    vals = compute(t)
    out = []
    for g, fn in GATES.items():
        try:
            out += [(g, msg) for msg in fn(t, vals)]
        except LookupError as e:  # default-deny: an unreadable input fails its gate
            out.append((g, f"cannot evaluate: {e}"))
    return out


# ------------------------------------------------------------------------ load, fill


def changed_paths() -> list[str] | None:
    mb = git("merge-base", "HEAD", "origin/main")
    if not mb:
        return None
    a = git("diff", "--name-only", mb.strip())
    b = git("status", "--porcelain", "--untracked-files=all")
    if a is None or b is None:
        return None
    out = {p for p in a.split("\n") if p}
    out |= {ln[3:].split(" -> ")[-1].strip('"') for ln in b.split("\n") if len(ln) > 3}
    return sorted(out)


def load() -> Texts:
    spec = (ROOT / SPEC_REL).read_text(encoding="utf-8")
    pins_path = ROOT / PINS_REL
    pins = pins_path.read_text(encoding="utf-8") if pins_path.exists() else ""
    tool = (ROOT / TOOL_REL).read_text(encoding="utf-8")
    return Texts(spec, pins, tool, changed_paths(), {})


def fill(t: Texts) -> str:
    out = []
    for ln in t.spec.split("\n"):
        c = cells(ln)
        if re.match(r"\| P-\d+ ", ln) and len(c) == 8:
            v = contrast_values(c)
            c[4:8] = [*v, verdict(c[3], v)]
            ln = "| " + " | ".join(c) + " |"
        elif re.match(r"\| V-\d+ ", ln) and len(c) == 6:
            c[4], c[5] = cvd_values(c)
            ln = "| " + " | ".join(c) + " |"
        out.append(ln)
    return "\n".join(out)


# ---------------------------------------------------------------------------- self-test


def sub(old: str, new: str) -> Callable[[Texts], Texts]:
    def f(t: Texts) -> Texts:
        if t.spec.count(old) != 1:
            raise SystemExit(
                f"self-test: the review carries {old[:50]!r} {t.spec.count(old)} times"
            )
        return replace(t, spec=t.spec.replace(old, new))

    return f


def set_cell(row: str, col: int, value: str) -> Callable[[Texts], Texts]:
    def f(t: Texts) -> Texts:
        ls = t.spec.split("\n")
        i = next(k for k, ln in enumerate(ls) if ln.startswith(f"| {row} "))
        c = cells(ls[i])
        c[col] = value
        ls[i] = "| " + " | ".join(c) + " |"
        return replace(t, spec="\n".join(ls))

    return f


def drop_row(row: str) -> Callable[[Texts], Texts]:
    def f(t: Texts) -> Texts:
        kept = [x for x in t.spec.split("\n") if not x.startswith(f"| {row} ")]
        return replace(t, spec="\n".join(kept))

    return f


MUTATIONS: tuple[tuple[str, str, Callable[[Texts], Texts]], ...] = (
    ("G-FINDING", "a Major accepted", set_cell("F-02", 4, "accepted: later")),
    (
        "G-FINDING",
        "a count typed by hand in §9's heading",
        sub("Major 11<!--=F:major-->", "Major 10<!--=F:major-->"),
    ),
    ("G-FINDING", "the Blocking routed", set_cell("F-01", 4, "routed: E38-S0x")),
    ("G-NAMES", "the reset Confirm's name emptied", set_cell("N79-07", 3, "")),
    ("G-NAMES", "the SCR-099 section renamed", sub("### 3.4 SCR-099", "### 3.4 SCR")),
    ("G-NAMES", "an SCR-122 row dropped", drop_row("N122-04")),
    ("G-PATH", "W-04's focus target emptied", set_cell("W-04", 3, "—")),
    ("G-PATH", "the completion step renamed", set_cell("W-08", 1, "the end")),
    (
        "G-T2",
        "T-01's reason reworded",
        set_cell("T-01", 5, '"Live trading is not enabled for you."'),
    ),
    ("G-T2", "the typed LIVE gate classed T2", set_cell("T-04", 3, "T2")),
    ("G-T2", "an unknown rbac key", set_cell("T-06", 4, "`rbac.read_write`")),
    ("G-CONTRAST", "P-03's dark figure typed by hand", set_cell("P-03", 4, "3.65")),
    ("G-CONTRAST", "P-14's verdict changed", set_cell("P-14", 7, "structure")),
    ("G-CVD", "V-02's JND column typed by hand", set_cell("V-02", 5, "protanopia")),
    (
        "G-AROW",
        "A-16's Old text off by one character",
        sub(
            'Old: "CMP-027 inline error in the dialog with Retry; nothing changed"',
            'Old: "CMP-027 inline error in the dialog with Retry: nothing changed"',
        ),
    ),
    ("G-CITE", "a `D03` cite one line off", sub("`D03`:250", "`D03`:251")),
    (
        "G-HYGIENE",
        "a closing keyword against #1076",
        sub("nothing here claims it.", "nothing here claims it. Closes #1076."),
    ),
    (
        "G-HYGIENE",
        "a deny word in the tool's own text",
        lambda t: replace(t, tool=t.tool + "\n# " + "fl" + "ood\n"),
    ),
    (
        "G-SCOPE",
        "a parent file in the diff",
        lambda t: replace(t, changed=[*OWN_PATHS, PATHS["D02"]]),
    ),
)


def selftest() -> tuple[bool, list[str]]:
    base = replace(load(), changed=list(OWN_PATHS))
    before = base.spec
    found = audit(base)
    out = [f"self-test: baseline {len(found)} FAIL"]
    out += [f"  baseline {g}: {m}" for g, m in found]
    ok = not found
    for i, (gate, what, fn) in enumerate(MUTATIONS, 1):
        gates = sorted({g for g, _ in audit(fn(base))})
        good = gates == [gate]
        ok &= good
        shown = ", ".join(gates) or "none"
        out.append(f"{'ok  ' if good else 'FAIL'} M-{i} {gate}: {what} -> {shown}")
    missing = [g for g in GATES if g not in {m[0] for m in MUTATIONS}]
    ok &= not missing
    if missing:
        out.append(f"FAIL no mutation for {', '.join(missing)}")
    restored = load().spec == before
    ok &= restored
    out.append(
        f"self-test: {len(MUTATIONS)} mutations, text restored: "
        + ("yes" if restored else "NO")
    )
    out.append(f"self-test: {'PASS' if ok else 'FAIL'}")
    return ok, out


def main(argv: list[str]) -> int:
    ap = argparse.ArgumentParser(description="E38-D05 a11y review audit")
    g = ap.add_mutually_exclusive_group()
    g.add_argument("--check", action="store_true")
    g.add_argument("--fill", action="store_true")
    g.add_argument("--self-test", action="store_true")
    g.add_argument("--repin-ruled", action="store_true")
    a = ap.parse_args(argv)
    if a.self_test:
        ok, lines = selftest()
        print("\n".join(lines))
        return 0 if ok else 1
    t = load()
    if a.fill:
        (ROOT / SPEC_REL).write_text(fill(t), encoding="utf-8")
        print(f"wrote §6's figures into {SPEC_REL}")
        return 0
    if a.repin_ruled:
        hashes, bad = cite_hashes(t)
        if bad:
            print(f"refused: {bad[0]}")
            return 1
        head = (
            "# E38-D05 cite pins: the cite, a hash of its cited line(s) at its ref."
            " Written by --repin-ruled only.\n"
        )
        (ROOT / PINS_REL).write_text(
            head + "".join(f"{k}\t{h}\n" for k, h in hashes.items()), encoding="utf-8"
        )
        print(f"wrote {PINS_REL} ({len(hashes)} cites)")
        return 0
    found = audit(t)
    for gate, msg in found:
        print(f"FAIL {gate}: {msg}")
    print(f"{len(found)} FAIL ({len(GATES)} gates)")
    return 1 if found else 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
