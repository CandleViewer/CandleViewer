#!/usr/bin/env python3
"""E38-D04 (#1075) audit: the simulated labelling system and the fill-model disclosure block.

Standalone, offline, stdlib only; it runs no repo code and is run with `python3 -I`. It reads the
spec and the pins file from the working tree, and every cited file AS TEXT with `git show`: the
plan docs, E26-D02, E09-D09, the design-spec rules and the token JSON at the pinned base (`BASE`);
the E38-D01 memo at #5451's head (`MEMO_REF`) until it merges (R6).
Default-deny: a gate that cannot read its input FAILs.

Gates (each FAIL led by its name):
  G-CONTRAST  every CR anchor re-derived from `packages/ui/tokens` at the base (dark / light /
              high contrast; WCAG 2.x, 2 decimals); every gated pair at or above its bar; every
              contrast figure in the prose (§2.2, §5.2) carries its CR anchor, so no copy of a
              figure stands ungated.
  G-PLACE     §3 has a P row for every surface the ticket names, each with a heading carrier,
              a row carrier and an accessible name that says "simulated"; each row's screen id
              is the surface's own, and its `14` heading at the base names the surface.
  G-T2        §10.1 (BQ-13 RULED): the analytics view switch is a read, never T2, not even in a
              view-as session, and §6 says so; Export is T2 with `rbac.permission` and
              `journal:read`, names CMP-079, the `lock`'s "Not available", G-T2.2 and G-T2.3,
              and each `DS` quote marked verbatim stands in its cited `DS` lines at the base;
              A-1 lists CMP-079 and CMP-019 (G-T2.6).
  G-DISCLOSE  every `FillModelConfig` field §5's B rows name is a field of the class at `24`
              §12.1 at the base; the six rows the ticket asks for are present.
  G-WORDS     every N row's accessible name begins with "Simulated"; CA-5 and CA-6 stand verbatim
              on their memo lines; the badge's token cells never use `color.env.*` or
              `color.status.info.*`.
  G-AROW      every A-row's Old text or anchor stands exactly once in its target at the base;
              an "After" anchor names its line at the base, and that line starts with the quote.
  G-CITE      every cite in range and on a non-blank line at its ref, its content equal to the
              pins file's hash; the SHA anchors are the pinned refs.
  G-HYGIENE   no closing keyword, local path, URL or host, agent name, double-brace slot or
              public-text deny word in the spec, this tool or the pins file; no unknown anchor.
  G-SCOPE     the diff against `git merge-base HEAD origin/main` touches only the spec, this
              tool and the pins file.

Usage (from the repo root):
  python3 -I docs/design/_tools/e38_d04_hifi_audit.py --check       (exit 1 on any FAIL)
  python3 -I docs/design/_tools/e38_d04_hifi_audit.py --json
  python3 -I docs/design/_tools/e38_d04_hifi_audit.py --self-test
  python3 -I docs/design/_tools/e38_d04_hifi_audit.py --repin-ruled   (the pins file's only writer)
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
SPEC_REL = "docs/design/E38/E38-D04.md"
TOOL_REL = "docs/design/_tools/e38_d04_hifi_audit.py"
PINS_REL = "docs/design/_tools/e38_d04_ruled_pins.txt"
OWN_PATHS = (SPEC_REL, TOOL_REL, PINS_REL)
BASE = "c327ed438c01c5bab9247890dd00f5dce3717f97"  # origin/main when written
MEMO_REF = "4774b2f8cd7b67a1ee934fe88546568f7aa3e34c"  # #5451's head (E38-D01 memo)
TOKENS = "packages/ui/tokens"
PATHS: dict[str, str] = {
    "05": "docs/plan/05-accessibility-standard.md",
    "11": "docs/plan/11-user-stories.md",
    "14": "docs/plan/14-screens-catalogue.md",
    "15": "docs/plan/15-component-catalogue.md",
    "16": "docs/plan/16-design-system-brief.md",
    "21": "docs/plan/21-database-schema.md",
    "23": "docs/plan/23-ws-protocol.md",
    "24": "docs/plan/24-internal-schemas.md",
    "MEMO": "docs/design/research/E38-paper-parity.md",
    "E26D02": "docs/design/E26/E26-D02.md",
    "E09D09": "docs/design/E09/E09-D09.md",
    "DS": ".claude/rules/32-design-specs.md",
}
REF_OF = {"MEMO": MEMO_REF}
LAYERS = {
    "dark": ("primitives", "semantic-dark"),
    "light": ("primitives", "semantic-dark", "semantic-light"),
    "hc": ("primitives", "semantic-dark", "semantic-hc"),
}
# CR key -> (fg token, bg token, bar or None when reported, never gated)
PAIRS: dict[str, tuple[str, str, float | None]] = {
    "badge.word": ("color.text.primary", "color.neutral.subtle", 4.5),
    "badge.hair.canvas": ("color.border.strong", "color.surface.canvas", None),
    "badge.hair.raised": ("color.border.strong", "color.surface.raised", None),
    "block.label": ("color.text.secondary", "color.surface.raised", 4.5),
    "block.value": ("color.text.primary", "color.surface.raised", 4.5),
    "block.note": ("color.text.tertiary", "color.surface.raised", 4.5),
}
# the surfaces the ticket names (T Scope bullet 3), each a P row's first cell starts with it
SURFACES = (
    "orders blotter",
    "positions grid",
    "fills",
    "journal list",
    "journal trade detail",
    "analytics",
    "SCR-099",
)
# each surface's screen id and a word its `14` heading carries (G-PLACE)
SURFACE_HEADINGS = {
    "orders blotter": ("SCR-063", "orders"),
    "positions grid": ("SCR-063", "positions"),
    "fills": ("SCR-078", "fills"),
    "journal list": ("SCR-093", "journal"),
    "journal trade detail": ("SCR-094", "trade detail"),
    "analytics": ("SCR-095", "analytics"),
    "SCR-099": ("SCR-099", "replay"),
}
FIGURE = re.compile(r"\b\d{1,2}\.\d{2}\b(?!<!--=CR:)")
# the block's six rows (T AC 3 and Scope bullet 2), each a B row's label
BLOCK_ROWS = ("Fill model", "Queue position", "Latency", "Slippage", "Fees", "Funding")
FORBIDDEN_BADGE_TOKENS = ("color.env.", "color.status.info.")
DASH = "\u2013"  # the en dash of a cited range
KEYS = r"\d\d|MEMO|E26D02|E09D09|DS"
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
# assembled with an explicit +, so the formatter keeps the split and the tool never spells a word
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
    tool: str
    changed: list[str] | None
    memo: dict[str, str | None]


def git(*args: str) -> str | None:
    try:
        # git with fixed arguments and no shell; the only external program the audit runs
        r = subprocess.run(
            ["git", "-C", str(ROOT), *args],
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
        raise SystemExit(
            f"{PATHS[key]} does not resolve at {ref[:10]}; fetch #5451's head first"
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
    j = text.find("\n## ", i + 1)
    return text[i : j if j > 0 else len(text)]


# ---------------------------------------------------------------------------- contrast


def theme(t: Texts, th: str) -> dict[str, object]:
    out: dict[str, object] = {}
    for name in LAYERS[th]:
        raw = show(t, BASE, f"{TOKENS}/{name}.tokens.json")
        if raw is None:
            raise SystemExit(
                f"{TOKENS}/{name}.tokens.json does not resolve at the base"
            )
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


def ratio(a: str, b: str) -> float:
    x, y = sorted((lum(a), lum(b)), reverse=True)
    return (x + 0.05) / (y + 0.05)


def contrast(t: Texts) -> dict[str, float]:
    out: dict[str, float] = {}
    for th in LAYERS:
        m = theme(t, th)
        for key, (fg, bg, _) in PAIRS.items():
            f = str(resolve(m, m[fg])).upper()
            b = str(resolve(m, m[bg])).upper()
            out[f"CR:{key}.{th}"] = ratio(f, b)
    return out


def compute(t: Texts) -> dict[str, str]:
    v = {"SHA:BASE": BASE[:10], "SHA:MEMO": MEMO_REF[:10]}
    v.update({k: f"{x:.2f}" for k, x in contrast(t).items()})
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


def g_contrast(t: Texts, vals: dict[str, str]) -> list[str]:
    bad = anchor_problems(t, vals, "CR:")
    for i, ln in enumerate(t.spec.split("\n"), 1):
        for m in FIGURE.finditer(ln):
            bad.append(f"spec:{i}: the figure {m[0]} carries no CR anchor")
    for key, (_, _, bar) in PAIRS.items():
        for th in LAYERS:
            name = f"CR:{key}.{th}"
            if f"<!--={name}-->" not in t.spec:
                bad.append(f"the spec drops the {name} anchor")
            if bar is not None and float(vals[name]) < bar:
                bad.append(f"{name} measures {vals[name]}, under its {bar} bar")
    return bad


def heading_14(t: Texts, scr: str) -> str:
    for ln in at(t, "14").split("\n"):
        if ln.startswith(f"### {scr} "):
            return ln
    return ""


def g_place(t: Texts, vals: dict[str, str]) -> list[str]:
    ps = rows(section(t.spec, "## 3."), "P")
    bad = []
    for r in ps:
        if len(r) < 2:
            continue
        surface = next((s for s in SURFACES if r[1].startswith(s)), None)
        if surface is None:
            continue
        scr, word = SURFACE_HEADINGS[surface]
        ids = re.findall(r"SCR-\d{3}", r[1])
        if ids != [scr]:
            bad.append(f"{r[0]}: names {ids or 'no screen'}, the {surface} is {scr}")
        head = heading_14(t, scr)
        if word not in head.lower():
            bad.append(f"{r[0]}: `14`'s {scr} heading does not name the {surface}")
    for s in SURFACES:
        if not any(len(r) > 1 and r[1].startswith(s) for r in ps):
            bad.append(f"no P row for the surface {s!r}")
    for r in ps:
        if len(r) != 5:
            bad.append(f"{r[0]}: {len(r)} cells, not 5")
            continue
        if not r[2] or not r[3]:
            bad.append(f"{r[0]}: needs a heading carrier and a row carrier")
        if "imulated" not in r[4]:
            bad.append(f"{r[0]}: its accessible name does not say simulated")
    return bad


def config_fields(t: Texts) -> set[str]:
    text = at(t, "24")
    i = text.find("class FillModelConfig(BaseModel):")
    j = text.find("```", i)
    if i < 0 or j < 0:
        return set()
    return set(re.findall(r"^    ([a-z_]+):", text[i:j], re.MULTILINE))


def g_disclose(t: Texts, vals: dict[str, str]) -> list[str]:
    fields = config_fields(t)
    bs = rows(section(t.spec, "## 5."), "B")
    bad = [] if fields else ["`24` no longer carries class FillModelConfig at the base"]
    labels = [r[1] for r in bs if len(r) > 1]
    for want in BLOCK_ROWS:
        if want not in labels:
            bad.append(f"the block has no {want!r} row")
    for r in bs:
        if len(r) != 5:
            bad.append(f"{r[0]}: {len(r)} cells, not 5")
            continue
        for f in re.findall(r"`([a-z_]+)`", r[3]):
            if f not in fields:
                bad.append(f"{r[0]}: `{f}` is not a FillModelConfig field at the base")
    return bad


def g_words(t: Texts, vals: dict[str, str]) -> list[str]:
    bad = []
    for r in rows(section(t.spec, "## 9."), "N"):
        if len(r) < 3 or not r[2].strip('"').startswith("Simulated"):
            bad.append(f"{r[0]}: the accessible name does not begin with Simulated")
    memo = at(t, "MEMO").split("\n")
    for ca, line in re.findall(r"\*\*(CA-[56])\*\* \(`MEMO`:(\d+)\)", t.spec):
        quote = re.search(rf"\*\*{ca}\*\* \(`MEMO`:{line}\): \"(.+?)\"", t.spec)
        n = int(line)
        if not quote or not 0 < n <= len(memo) or quote[1] not in memo[n - 1]:
            bad.append(f"{ca} is not quoted verbatim from `MEMO`:{line}")
    tok = section(t.spec, "## 2.")
    for r in rows(tok, "T"):
        if any(x in " ".join(r) for x in FORBIDDEN_BADGE_TOKENS):
            bad.append(f"{r[0]}: the badge uses an environment or info token")
    return bad


def g_t2(t: Texts, vals: dict[str, str]) -> list[str]:
    ten = section(t.spec, "### 10.1")
    switch = next(
        (
            ln
            for ln in ten.split("\n")
            if ln.startswith("- **The analytics view switch**")
        ),
        "",
    )
    export = next((ln for ln in ten.split("\n") if ln.startswith("- **Export**")), "")
    bad = []
    if "never T2" not in switch or "view-as" not in switch or "T2 rendering" in switch:
        bad.append("§10.1: the view switch must read never T2, not even under view-as")
    if "The view switch is a read, never T2" not in section(t.spec, "## 6."):
        bad.append("§6 does not say the view switch is never T2")
    if "`rbac.permission`" not in export or "`journal:read`" not in export:
        bad.append("§10.1: Export must be T2 with `rbac.permission` and `journal:read`")
    for need in ("CMP-079", '"Not available"', "G-T2.2", "G-T2.3"):
        if need not in export:
            bad.append(f"§10.1: Export does not name {need} (G-T2.1d, G-T2.2, G-T2.3)")
    ds = at(t, "DS").split("\n")
    for m in re.finditer(VERBATIM, export):
        lo, hi = int(m[1]), int(m[2])
        cited = norm(" ".join(ds[lo - 1 : hi]).replace("**", ""))
        if norm(m[3]) not in cited:
            bad.append(f"§10.1: a quote marked verbatim is not in `DS`:{lo}\u2013{hi}")
    a1 = next((ln for ln in section(t.spec, "## 13.").split("\n") if "**A-1" in ln), "")
    for need in ("CMP-079", "CMP-019"):
        if need not in a1:
            bad.append(f"A-1 on CMP-099 does not list {need} (G-T2.6)")
    return bad


VERBATIM = re.compile(r"verbatim \(`DS`:(\d+)\u2013(\d+)\): (.+?)(?:\. | \(|\.$)")


def g_arow(t: Texts, vals: dict[str, str]) -> list[str]:
    bad = []
    for ln in section(t.spec, "## 13.").split("\n"):
        m = re.match(r"- \*\*(A-\d+) \u2192 `(\d\d)`", ln)
        if not m:
            continue
        aid, key = m[1], m[2]
        body = ln[m.end() :]
        anchors = re.findall(r'Old: "(.+?)"\. New:', body)
        after = re.findall(
            r'(?:[Aa]fter|[Bb]efore) "(.+?)" \(line `(\d\d)`:(\d+) at the base[^)]*\) add',
            body,
        )
        anchors += [a for a, _, _ in after]
        if re.search(r'(?:[Aa]fter|[Bb]efore) "', body) and not after:
            bad.append(f"{aid}: an After anchor with no line at the base")
        for a, k, n in after:
            ls = at(t, k).split("\n")
            if not (0 < int(n) <= len(ls) and ls[int(n) - 1].startswith(a)):
                bad.append(
                    f"{aid}: line `{k}`:{n} at the base does not start with {a[:40]!r}"
                )
        if not anchors:
            bad.append(f"{aid}: names neither an Old text nor an anchor")
        for a in anchors:
            n = at(t, key).count(a)
            if n != 1:
                bad.append(f"{aid}: {a[:40]!r} stands {n} times in `{key}`")
    return bad


def g_cite(t: Texts, vals: dict[str, str]) -> list[str]:
    hashes, bad = cite_hashes(t)
    pinned = parse_pins(t.pins)
    for label, h in hashes.items():
        if label not in pinned:
            bad.append(
                f"cite {label} is unpinned: verify it by content, then --repin-ruled"
            )
        elif pinned[label] != h:
            bad.append(f"cite {label}: the line at its ref is not the pinned content")
    return bad + anchor_problems(t, vals, "SHA:")


def g_hygiene(t: Texts, vals: dict[str, str]) -> list[str]:
    bad = []
    checks = (
        (CLOSING, "a closing keyword (PR 2 carries the closing line)"),
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
    "G-CONTRAST": g_contrast,
    "G-PLACE": g_place,
    "G-T2": g_t2,
    "G-DISCLOSE": g_disclose,
    "G-WORDS": g_words,
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
    pins = (
        (ROOT / PINS_REL).read_text(encoding="utf-8")
        if (ROOT / PINS_REL).exists()
        else ""
    )
    tool = (ROOT / TOOL_REL).read_text(encoding="utf-8")
    return Texts(spec, pins, tool, changed_paths(), {})


def sub(old: str, new: str) -> Callable[[Texts], Texts]:
    def f(t: Texts) -> Texts:
        if t.spec.count(old) != 1:
            raise SystemExit(
                f"self-test: the spec carries {old[:50]!r} {t.spec.count(old)} times"
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
        return replace(
            t,
            spec="\n".join(
                x for x in t.spec.split("\n") if not x.startswith(f"| {row} ")
            ),
        )

    return f


A1_T2 = ", wrapped by CMP-079 RbacGate and led by the CMP-019 `lock`"


def a1_without(name: str) -> Callable[[Texts], Texts]:
    """A-1 loses one of its two T2 components."""
    kept = {
        "CMP-079": ", led by the CMP-019 `lock`",
        "CMP-019": ", wrapped by CMP-079 RbacGate",
    }[name]
    return sub(A1_T2, kept)


MUTATIONS: tuple[tuple[str, str, Callable[[Texts], Texts]], ...] = (
    (
        "G-CONTRAST",
        "a contrast value typed by hand",
        lambda t: replace(
            t,
            spec=re.sub(
                r"[\d.]+(<!--=CR:badge\.word\.dark-->)",
                lambda m: "9.99" + m[1],
                t.spec,
                count=1,
            ),
        ),
    ),
    ("G-PLACE", "the fills row dropped", drop_row("P-3")),
    (
        "G-PLACE",
        "a row's name without simulated",
        set_cell("P-1", 4, '"Orders, 3 rows"'),
    ),
    (
        "G-PLACE",
        "the fills row pointed at SCR-079",
        set_cell("P-3", 1, "fills (SCR-079)"),
    ),
    (
        "G-T2",
        "the view switch made T2 under view-as",
        sub(
            "so it is never T2, not even in a view-as session",
            "so it is T2 rendering 2a in a view-as session",
        ),
    ),
    (
        "G-T2",
        "Export without its permission",
        sub(
            "A session without `journal:read` sees", "A session without the grant sees"
        ),
    ),
    (
        "G-CONTRAST",
        "a §5.2 prose figure typed by hand",
        sub("5.62<!--=CR:block.note.dark-->", "5.26<!--=CR:block.note.dark-->"),
    ),
    (
        "G-CONTRAST",
        "an unanchored copy of a figure in the prose",
        sub(
            "every gated pair is at or above 4.5.",
            "every gated pair is at or above 4.5; the word reads 12.22 on its fill.",
        ),
    ),
    (
        "G-AROW",
        "A-4's quote moved off its cited line",
        sub("[ ] per-fill", "[ ] positions,"),
    ),
    ("G-DISCLOSE", "the Funding row dropped", drop_row("B-6")),
    (
        "G-DISCLOSE",
        "a field name that is not in the class",
        set_cell("B-3", 3, "`latency_total_ms`"),
    ),
    (
        "G-WORDS",
        "a region name without Simulated",
        set_cell("N-2", 2, '"Results \u2014 Session 3"'),
    ),
    (
        "G-WORDS",
        "the badge on an environment token",
        set_cell("T-1", 2, "`color.env.demo`"),
    ),
    (
        "G-AROW",
        "A-1's Old text off by one character",
        sub('Old: "`formats: ("csv"|"pdf")[]`"', 'Old: "`formats: ("csv"|"pdf")[] `"'),
    ),
    (
        "G-CITE",
        "a `24` cite one line off its pinned content",
        sub("`24`:3999", "`24`:3998"),
    ),
    (
        "G-HYGIENE",
        "a closing keyword against #1075",
        sub("nothing here claims it.", "nothing here claims it. Closes #1075."),
    ),
    (
        "G-HYGIENE",
        "a deny word in the tool's own text",
        lambda t: replace(t, tool=t.tool + "\n# " + "fl" + "ood\n"),
    ),
    (
        "G-SCOPE",
        "a catalogue file in the diff",
        lambda t: replace(t, changed=[*OWN_PATHS, PATHS["15"]]),
    ),
    (
        "G-T2",
        "§10.1 without CMP-079",
        sub("CMP-079 RbacGate (`15`:890) wraps it; it", "It"),
    ),
    (
        "G-T2",
        "§10.1 without the lock's name",
        sub(', accessible name "Not available"', ""),
    ),
    (
        "G-T2",
        "§10.1 without G-T2.3",
        sub(
            " G-T2.3, verbatim (`DS`:47\u201348): `Enter`, `Space` or a bound hotkey on a T2"
            " control changes nothing and re-shows the reason inline with one polite"
            " announcement (board 02's G-T2.3 inset).",
            "",
        ),
    ),
    ("G-T2", "§10.1's G-T2.2 named G-T2", sub("G-T2.2, verbatim", "G-T2, verbatim")),
    (
        "G-T2",
        "a G-T2.3 quote off its DS text",
        sub("one polite announcement (", "an announcement ("),
    ),
    ("G-T2", "A-1 without CMP-079", a1_without("CMP-079")),
    ("G-T2", "A-1 without CMP-019", a1_without("CMP-019")),
)


def selftest() -> tuple[bool, list[str]]:
    base = replace(load(), changed=list(OWN_PATHS))
    before = base.spec
    found = audit(base)
    out = [f"self-test: baseline {len(found)} FAIL"] + [
        f"  baseline {g}: {m}" for g, m in found
    ]
    ok = not found
    for i, (gate, what, fn) in enumerate(MUTATIONS, 1):
        gates = sorted({g for g, _ in audit(fn(base))})
        good = gates == [gate]
        ok &= good
        out.append(
            f"{'ok  ' if good else 'FAIL'} M-{i} {gate}: {what} -> {', '.join(gates) or 'none'}"
        )
    missing = [g for g in GATES if g not in {m[0] for m in MUTATIONS}]
    ok &= not missing
    if missing:
        out.append(f"FAIL no mutation for {', '.join(missing)}")
    restored = load().spec == before
    ok &= restored
    out.append(
        f"self-test: {len(MUTATIONS)} mutations, text restored: {'yes' if restored else 'NO'}"
    )
    out.append(f"self-test: {'PASS' if ok else 'FAIL'}")
    return ok, out


def main(argv: list[str]) -> int:
    ap = argparse.ArgumentParser(description="E38-D04 hi-fi audit")
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
            "# E38-D04 cite pins: the cite, a hash of its cited line(s) at its ref."
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
                    "memo": MEMO_REF,
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
