#!/usr/bin/env python3
"""E25-D06 (#671) audit: the accessibility design review of SCR-055 ... SCR-059.

Standalone, offline, stdlib only; it runs no repo code and is run with `python3 -I`. It reads the
review and the pins file from the working tree, and every cited file AS TEXT with `git show`: the
plan docs, E25-D02, E25-D05, E05-D03, the design-spec rules and the token JSON at the pinned base
(`BASE`); E25-D03 and E25-D04 at their PR heads (`REF_OF`) until #5404 and #5415 merge (R6).
Default-deny: a gate that cannot read its input FAILs.

Gates (each FAIL led by its name):
  G-FINDING   §11's F rows in order; each severity from R-1's set; each closing "fix: A-n" with
              §12 carrying A-n, each target E25-D07, "accepted: ..." or "accepted exception:
              ..." with a rationale, or
              "routed: ..." with an owner; no Blocking or Major without a fix; the counts in §11's
              heading equal the rows.
  G-CONTRAST  every CR anchor re-derived from `packages/ui/tokens` at the base (dark / light /
              high contrast; a blend at alpha a is fg*a + bg*(1 - a) per channel; WCAG 2.x, 4
              decimals).
  G-NARRATIVE every N row's quoted sentence stands verbatim on its cited line at its ref.
  G-T2        every T row's rendering and reason key come from the allowed sets.
  G-CITE      every cite in range and on a non-blank line at its ref, its content equal to the
              pins file's hash; the SHA anchors are the pinned refs.
  G-HYGIENE   no closing keyword, local path, URL or host, agent name, double-brace slot or
              public-text deny word in the review; no unknown anchor key.
  G-SCOPE     the diff against `git merge-base HEAD origin/main` touches only the review, this
              tool and the pins file.

Usage (from the repo root):
  python3 -I docs/design/_tools/e25_d06_a11y_review_audit.py --check       (exit 1 on any FAIL)
  python3 -I docs/design/_tools/e25_d06_a11y_review_audit.py --json
  python3 -I docs/design/_tools/e25_d06_a11y_review_audit.py --self-test
  python3 -I docs/design/_tools/e25_d06_a11y_review_audit.py --repin-ruled
      (the pins file's only writer)
"""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import subprocess
import sys
from collections.abc import Callable
from dataclasses import dataclass, replace
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
SPEC_REL = "docs/design/E25/E25-D06.md"
TOOL_REL = "docs/design/_tools/e25_d06_a11y_review_audit.py"
PINS_REL = "docs/design/_tools/e25_d06_ruled_pins.txt"
OWN_PATHS = (SPEC_REL, TOOL_REL, PINS_REL)
BASE = "e5b286ed50d3a320d80b24df5030fb09dd405a4a"  # origin/main when written
D03_REF = "5a73e7b9dd24f855b0d02926a85b16a8ccfbd0f4"  # #5404's head (E25-D03 PR 2)
D04_REF = "f61afd6afbcc0e4f9c2a1a7d0615f1693580c8f8"  # #5415's head (E25-D04 PR 2)
TOKENS = "packages/ui/tokens"
PATHS: dict[str, str] = {
    "05": "docs/plan/05-accessibility-standard.md",
    "14": "docs/plan/14-screens-catalogue.md",
    "15": "docs/plan/15-component-catalogue.md",
    "16": "docs/plan/16-design-system-brief.md",
    "24": "docs/plan/24-internal-schemas.md",
    "D02": "docs/design/E25/E25-D02.md",
    "D03": "docs/design/E25/E25-D03.md",
    "D04": "docs/design/E25/E25-D04.md",
    "D05": "docs/design/E25/E25-D05.md",
    "E05D03": "docs/design/E05/E05-D03.md",
    "DS": ".claude/rules/32-design-specs.md",
    "E09D09": "docs/design/E09/E09-D09.md",
    "E30D05": "docs/design/E30/E30-D05.md",
}
REF_OF = {"D03": D03_REF, "D04": D04_REF}
LAYERS = {
    "dark": ("primitives", "semantic-dark"),
    "light": ("primitives", "semantic-dark", "semantic-light"),
    "hc": ("primitives", "semantic-dark", "semantic-hc"),
}
THEME_OF = {"dark": "dark", "light": "light", "hc": "hc"}
# CR key -> (fg token, bg token, alpha token or a number, or None)
PAIRS: dict[str, tuple[str, str, str | float | None]] = {
    "stale.ter": ("color.text.tertiary", "color.surface.raised", 0.85),
    "stale.sec": ("color.text.secondary", "color.surface.raised", 0.85),
    "validity": ("color.text.primary", "color.surface.overlay", "opacity.disabled"),
    "t2.label": ("color.text.tertiary", "color.surface.raised", None),
    "t2.reason": ("color.text.secondary", "color.surface.raised", None),
    "warn": ("color.status.warning.default", "color.surface.raised", None),
    "focus.raised": ("color.focus.ring", "color.surface.raised", None),
    "focus.overlay": ("color.focus.ring", "color.surface.overlay", None),
    "side": ("color.buy.default", "color.sell.default", None),
}
SEVERITIES = ("Blocking", "Major", "Minor", "Info")
# BQ-04 RULED (6573604055): the P42 stale-tertiary 1.4.3 miss is Blocking, never lowered
RULED_SEVERITY = {"F-02": "Blocking"}
# every gated control BQ-14's rider puts in scope: (screen, words of the control, reason key)
REQUIRED_T2 = (
    ("SCR-055", "alert affordance", "rbac.permission"),  # D03 S55-13
    ("SCR-056", "settings pills", "notice.panel_read_only"),  # D03 S56-12
    ("SCR-056", "Sync footprint", "notice.panel_read_only"),  # D03 S56-12
    ("SCR-056", "Recompute history", "rbac.owner_only"),  # D03 S56-3
    ("SCR-056", "empty state", "notice.panel_read_only"),  # D03 S56-2, the sentence form
    ("SCR-056", "Create alert at this level", "rbac.permission"),  # D03 S56-12
)
D04_T2_LINES = frozenset(range(280, 294)) - {285}  # D04 §4.10's rows T2-1 ... T2-14; T2-6 is inert
RENDERINGS = (
    "2a",
    "2a; 2b at the 208 px cell",
    "2b",
    "sentence form",
    "unreachable",
    "T1",
    "T1, never locked",
    "omitted",
)
# E09-D09 §3.1's seven, notice.panel_read_only (§10) and an em dash for an ungated row (BQ-14 rider)
REASON_KEYS = (
    "rbac.permission",
    "rbac.owner_only",
    "rbac.view_as",
    "rbac.env",
    "rbac.account",
    "rbac.account_read_only",
    "rbac.read_only",
    "notice.panel_read_only",
    "\u2014",
)
DASH = "\u2013"  # the en dash of a cited range
CITE = re.compile(
    r"`(\d\d|D0[2-5]|E05D03|E09D09|E30D05|DS)`:(\d+(?:\u2013\d+)?(?:, :\d+(?:\u2013\d+)?)*)"
)
ANCHOR = re.compile(r"`?([^\s<|(`]+)`?<!--=([A-Z]+:[A-Za-z0-9.]+)-->")
CLOSING = re.compile(r"\b(?:close[sd]?|fix(?:e[sd])?|resolve[sd]?)\s+#\d+", re.IGNORECASE)
LOCAL_PATH = re.compile("/" + "home/|/Users/|[A-Za-z]:\\\\|\\bwt-" + "notes\\b")  # assembled
AGENT_NAME = re.compile(r"\b[a-z]{2,4}-worker-\d\b")
URL_OR_HOST = re.compile(r"https?://|penpot\.[a-z]|team-id=|file-id=", re.IGNORECASE)
# assembled, so the list never spells the words it refuses
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


@dataclass(frozen=True)
class Texts:
    spec: str
    pins: str
    changed: list[str] | None
    memo: dict[str, str | None]


def git(*args: str) -> str | None:
    try:
        # git with fixed arguments and no shell; the only external program the audit runs
        r = subprocess.run(  # noqa: S603
            ["git", "-C", str(ROOT), *args],  # noqa: S607
            capture_output=True,
            check=False,
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
        raise SystemExit(f"{PATHS[key]} does not resolve at {ref[:10]}; fetch the PR heads first")
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
    j = text.find("\n## ", i + 1)
    return text[i : j if j > 0 else len(text)]


# ---------------------------------------------------------------------------- contrast


def theme(t: Texts, th: str) -> dict[str, object]:
    out: dict[str, object] = {}
    for name in LAYERS[th]:
        raw = show(t, BASE, f"{TOKENS}/{name}.tokens.json")
        if raw is None:
            raise SystemExit(f"{TOKENS}/{name}.tokens.json does not resolve at the base")
        out.update(
            {
                k: v["$value"]
                for k, v in json.loads(raw).items()
                if isinstance(v, dict) and "$value" in v
            }
        )
    return out


def resolve(m: dict[str, object], v: object, depth: int = 0) -> object:
    hit = re.fullmatch(r"\{([^}]+)\}", str(v))
    if hit and depth < 16:
        return resolve(m, m[hit[1]], depth + 1)
    return v


def lum(hex6: str) -> float:
    c = [int(hex6[i : i + 2], 16) / 255 for i in (1, 3, 5)]
    c = [x / 12.92 if x <= 0.04045 else ((x + 0.055) / 1.055) ** 2.4 for x in c]
    return 0.2126 * c[0] + 0.7152 * c[1] + 0.0722 * c[2]


def blend(fg: str, bg: str, a: float) -> str:
    return "#" + "".join(
        f"{round(int(fg[i : i + 2], 16) * a + int(bg[i : i + 2], 16) * (1 - a)):02X}"
        for i in (1, 3, 5)
    )


def ratio(a: str, b: str) -> float:
    x, y = sorted((lum(a), lum(b)), reverse=True)
    return (x + 0.05) / (y + 0.05)


def hexof(m: dict[str, object], key: str) -> str:
    return str(resolve(m, m[key])).upper()


def contrast_values(t: Texts) -> dict[str, str]:
    out: dict[str, str] = {}
    for th in LAYERS:
        m = theme(t, th)
        for key, (fg, bg, alpha) in PAIRS.items():
            f, b = hexof(m, fg), hexof(m, bg)
            if alpha is not None:
                a = float(alpha) if isinstance(alpha, float) else float(str(resolve(m, m[alpha])))
                f = blend(f, b, a)
            out[f"CR:{key}.{THEME_OF[th]}"] = f"{ratio(f, b):.4f}"
    return out


def compute(t: Texts) -> dict[str, str]:
    v = {"SHA:BASE": BASE[:10], "SHA:D03": D03_REF[:10], "SHA:D04": D04_REF[:10]}
    v.update(contrast_values(t))
    fs = rows(section(t.spec, "## 11."), "F")
    v["F:total"] = str(len(fs))
    for s in SEVERITIES:
        v[f"F:{s.lower()}"] = str(sum(r[1] == s for r in fs if len(r) > 1))
    return v


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


def anchor_problems(t: Texts, vals: dict[str, str], prefix: str) -> list[str]:
    return [
        f"`{key}` reads {value}; the tool derives {vals[key]}"
        for value, key in ANCHOR.findall(t.spec)
        if key.startswith(prefix) and key in vals and vals[key] != value
    ]


def g_finding(t: Texts, vals: dict[str, str]) -> list[str]:
    fs = rows(section(t.spec, "## 11."), "F")
    arows = set(re.findall(r"\*\*(A-\d+) →", section(t.spec, "## 12.")))
    bad = []
    if [r[0] for r in fs] != [f"F-{i:02d}" for i in range(1, len(fs) + 1)]:
        bad.append("§11's F rows are not F-01 ... F-n in order")
    for r in fs:
        if len(r) != 7:
            bad.append(f"{r[0]}: {len(r)} cells, not 7")
            continue
        fid, sev, _, _, closing, owner, target = r
        if not target.startswith("E25-D07"):
            bad.append(
                f"{fid}: the target is {target!r}, not E25-D07, which lifts each version"
                " into the pack (R-2)"
            )
        if sev not in SEVERITIES:
            bad.append(f"{fid}: severity {sev!r} is not one of {', '.join(SEVERITIES)}")
        fix = re.fullmatch(r"fix: (A-\d+)", closing)
        if fix and fix[1] not in arows:
            bad.append(f"{fid}: closes by {fix[1]}, which §12 does not carry")
        if not fix and not re.match(r"(accepted(?: exception)?|routed): \S", closing):
            bad.append(
                f"{fid}: the closing {closing!r} is neither a fix, an acceptance with its"
                " rationale nor a route"
            )
        if sev in ("Blocking", "Major") and not fix:
            bad.append(f"{fid}: a {sev} finding without a fix (R-2: no high finding stays open)")
        if not owner:
            bad.append(f"{fid}: no owner")
        if fid in RULED_SEVERITY and sev != RULED_SEVERITY[fid]:
            bad.append(f"{fid}: severity {sev}, ruled {RULED_SEVERITY[fid]} (BQ-04)")
    return bad + anchor_problems(t, vals, "F:")


def g_contrast(t: Texts, vals: dict[str, str]) -> list[str]:
    return anchor_problems(t, vals, "CR:")


def g_narrative(t: Texts, vals: dict[str, str]) -> list[str]:
    bad = []
    for r in rows(section(t.spec, "## 5."), "N"):
        if len(r) != 6:
            bad.append(f"{r[0]}: {len(r)} cells, not 6")
            continue
        quote = re.fullmatch(r'"(.+)"', r[3])
        src = CITE.fullmatch(r[5])
        if not quote:
            continue  # a described row (the T2 reason) quotes nothing
        if not src:
            bad.append(f"{r[0]}: the source {r[5]!r} is not one cite")
            continue
        ls = at(t, src[1]).split("\n")
        n = int(src[2].split(DASH)[0])
        if not 0 < n <= len(ls) or quote[1] not in ls[n - 1]:
            bad.append(f"{r[0]}: {quote[1][:40]!r} is not verbatim on {src[1]}:{n}")
    return bad


def g_t2(t: Texts, vals: dict[str, str]) -> list[str]:
    bad = []
    for r in rows(section(t.spec, "## 8."), "T"):
        if len(r) != 7:
            bad.append(f"{r[0]}: {len(r)} cells, not 7")
            continue
        if r[3] not in RENDERINGS:
            bad.append(f"{r[0]}: rendering {r[3]!r} is not one of the allowed set")
        if r[4] not in REASON_KEYS:
            bad.append(f"{r[0]}: reason key {r[4]!r} is not a registered key")
        if r[3].startswith(("2a", "2b", "sentence")) and r[4] == "\u2014":
            bad.append(f"{r[0]}: a T2 rendering without a reason key")
    table = [r for r in rows(section(t.spec, "## 8."), "T") if len(r) == 7]
    for screen, words, key in REQUIRED_T2:
        if not any(r[1] == screen and words in r[2] and r[4] == key for r in table):
            bad.append(f"no T row for {screen}'s {words!r} with {key} (BQ-14: every gated control)")
    cited: set[int] = set()
    for r in table:
        for key, a, b in cites(r[5]):
            if key == "D04":
                cited |= set(range(a, b + 1))
    for n in sorted(D04_T2_LINES - cited):
        bad.append(f"D04 §4.10's row at `D04`:{n} has no T row")
    return bad


def g_arow(t: Texts, vals: dict[str, str]) -> list[str]:
    """Each A-row is copy-ready at its parent's pinned head: its Old text (or its anchor) stands
    there exactly once, and A-1's target cell exists."""
    bad = []
    for ln in section(t.spec, "## 12.").split("\n"):
        m = re.match(r"- \*\*(A-\d+) \u2192 (E25-D0[34])", ln)
        if not m:
            continue
        aid, parent = m[1], {"E25-D03": "D03", "E25-D04": "D04"}[m[2]]
        text = at(t, parent)
        anchors = re.findall(r'Old: "(.+?)"\. New:', ln) + re.findall(r'after "(.+?)"\*\* \(F-', ln)
        for a in anchors:
            if text.count(a) != 1:
                bad.append(
                    f"{aid}: {a[:40]!r} stands {text.count(a)} times in {parent} at its head"
                )
        cell = re.search(r"Append to the row's (.+?) cell", ln)
        if cell:
            row = re.search(r"the (\w[\w ]*? row)\*\*", ln)
            ls = text.split("\n")
            at_row = next(
                (k for k, x in enumerate(ls) if row and x.startswith(f"| {row[1]} (")), None
            )
            head = ""
            if at_row is not None:
                head = next(
                    (ls[k] for k in range(at_row, -1, -1) if ls[k].startswith("| Element")), ""
                )
            if cell[1] not in head:
                bad.append(
                    f"{aid}: its target cell ({cell[1]!r}) is not a column of {parent}'s table"
                )
        if not anchors and not cell:
            bad.append(f"{aid}: names neither an Old text, an anchor nor a target cell")
    return bad


def g_cite(t: Texts, vals: dict[str, str]) -> list[str]:
    hashes, bad = cite_hashes(t)
    pinned = parse_pins(t.pins)
    for label, h in hashes.items():
        if label not in pinned:
            bad.append(f"cite {label} is unpinned: verify it by content, then --repin-ruled")
        elif pinned[label] != h:
            bad.append(
                f"cite {label}: the line at its ref is not the pinned content (moved or edited)"
            )
    return bad + anchor_problems(t, vals, "SHA:")


def g_hygiene(t: Texts, vals: dict[str, str]) -> list[str]:
    bad = []
    for i, ln in enumerate(t.spec.split("\n"), 1):
        checks = (
            (CLOSING, "a closing keyword (the closing line waits for the parents)"),
            (LOCAL_PATH, "a local path"),
            (AGENT_NAME, "an agent name"),
            (URL_OR_HOST, "a URL or a host"),
        )
        for rx, what in checks:
            if rx.search(ln):
                bad.append(f"spec:{i} carries {what}")
        if "{{" in ln:
            bad.append(f"spec:{i} carries a double-brace slot")
        if any(d in ln.lower() for d in DENY):
            bad.append(f"spec:{i} carries a public-text deny word")
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
    "G-CONTRAST": g_contrast,
    "G-NARRATIVE": g_narrative,
    "G-T2": g_t2,
    "G-AROW": g_arow,
    "G-CITE": g_cite,
    "G-HYGIENE": g_hygiene,
    "G-SCOPE": g_scope,
}


def audit(t: Texts) -> list[tuple[str, str]]:
    vals = compute(t)
    return [(g, msg) for g, fn in GATES.items() for msg in fn(t, vals)]


# ---------------------------------------------------------------------------- load, self-test


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
    pins = (ROOT / PINS_REL).read_text(encoding="utf-8") if (ROOT / PINS_REL).exists() else ""
    return Texts(spec, pins, changed_paths(), {})


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


MUTATIONS: tuple[tuple[str, str, Callable[[Texts], Texts]], ...] = (
    (
        "G-FINDING",
        "a Blocking finding marked accepted with no fix",
        set_cell("F-02", 4, "accepted: the chip carries the state"),
    ),
    (
        "G-FINDING",
        "a count typed by hand in §11's heading",
        sub("Blocking 1<!--=F:blocking-->", "Blocking 0<!--=F:blocking-->"),
    ),
    (
        "G-CONTRAST",
        "a contrast value typed by hand",
        sub("4.4307<!--=CR:stale.ter.dark-->", "4.5100<!--=CR:stale.ter.dark-->"),
    ),
    (
        "G-NARRATIVE",
        "one word changed in N-1's sentence",
        sub('"Tape elevated — 42 trades a second', '"Tape raised — 42 trades a second'),
    ),
    ("G-T2", "a T row's rendering 'hidden'", set_cell("T-9", 3, "hidden")),
    (
        "G-CITE",
        "a `D04` cite re-pointed one line off its pinned content",
        sub("`D04`:474", "`D04`:475"),
    ),
    (
        "G-HYGIENE",
        "a closing keyword against #671",
        sub("nothing here claims it.", "nothing here claims it. Closes #671."),
    ),
    (
        "G-T2",
        "the Viewer's 'Create alert at this level' row dropped",
        lambda t: replace(
            t, spec="\n".join(x for x in t.spec.split("\n") if not x.startswith("| T-18 "))
        ),
    ),
    (
        "G-FINDING",
        "F-02 lowered to Major, the counts kept consistent",
        lambda t: set_cell("F-02", 1, "Major")(
            sub("Blocking 1<!--=F:blocking--> · Major 1", "Blocking 0<!--=F:blocking--> · Major 2")(
                t
            )
        ),
    ),
    (
        "G-AROW",
        "A-3's Old text off by one character",
        sub(
            'Old: "instant; the spinner\'s opacity pulse"',
            'Old: "instant; the spinners opacity pulse"',
        ),
    ),
    (
        "G-AROW",
        "A-1's target cell renamed",
        sub("Append to the row's Text / glyph cell", "Append to the row's Glyph text cell"),
    ),
    (
        "G-SCOPE",
        "a parent file in the diff",
        lambda t: replace(t, changed=[*OWN_PATHS, PATHS["D03"]]),
    ),
)


def selftest() -> tuple[bool, list[str]]:
    base = replace(load(), changed=list(OWN_PATHS))
    before = base.spec
    found = audit(base)
    out = [f"self-test: baseline {len(found)} FAIL"] + [f"  baseline {g}: {m}" for g, m in found]
    ok = not found
    for i, (gate, what, fn) in enumerate(MUTATIONS, 1):
        gates = sorted({g for g, _ in audit(fn(base))})
        good = gates == [gate]
        ok &= good
        out.append(
            f"{'ok  ' if good else 'FAIL'} M-{i} {gate}: {what} -> {', '.join(gates) or 'none'}"
        )
    restored = load().spec == before
    ok &= restored
    out.append(
        f"self-test: {len(MUTATIONS)} mutations, text restored: {'yes' if restored else 'NO'}"
    )
    out.append(f"self-test: {'PASS' if ok else 'FAIL'}")
    return ok, out


def main(argv: list[str]) -> int:
    ap = argparse.ArgumentParser(description="E25-D06 a11y review audit")
    g = ap.add_mutually_exclusive_group()
    g.add_argument("--check", action="store_true")
    g.add_argument("--self-test", action="store_true")
    g.add_argument("--repin-ruled", action="store_true")
    ap.add_argument("--json", action="store_true")
    a = ap.parse_args(argv)
    if a.self_test:
        ok, lines = selftest()
        print("\n".join(lines))
        return 0 if ok else 1
    t = load()
    if a.repin_ruled:
        hashes, bad = cite_hashes(t)
        if bad:
            print(f"refused: {bad[0]}")
            return 1
        head = (
            "# E25-D06 cite pins: the cite, a hash of its cited line(s) at its ref."
            " Written by --repin-ruled only.\n"
        )
        (ROOT / PINS_REL).write_text(
            head + "".join(f"{k}\t{h}\n" for k, h in hashes.items()), encoding="utf-8"
        )
        print(f"wrote {PINS_REL} ({len(hashes)} cites)")
        return 0
    found = audit(t)
    if a.json:
        print(
            json.dumps(
                {
                    "base": BASE,
                    "d03": D03_REF,
                    "d04": D04_REF,
                    "values": compute(t),
                    "findings": [{"gate": g, "msg": m} for g, m in found],
                },
                ensure_ascii=False,
                indent=2,
            )
        )
    else:
        for gate, msg in found:
            print(f"FAIL {gate}: {msg}")
        print(f"{len(found)} FAIL ({len(GATES)} gates)")
    return 1 if found else 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
