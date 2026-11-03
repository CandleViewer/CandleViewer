#!/usr/bin/env python3
"""E41-D03 (#1081) audit: the hi-fi spec of SCR-094 (the trade post-mortem), SCR-095 (the journal
analytics dashboard) and the CMP-167 / CMP-168 design-system entries.

Standalone and offline, shaped on the merged E38-D03 tool (`e38_d03_honesty_audit.py`): it imports
`packages/ui/tokens/tests/verify_tokens.py` (the token loader and resolver),
`docs/design/_tools/contrast_check.py` (`contrast_ratio`) and
`docs/research/_tools/cvd_simulate.py` (`simulate`, `delta_e76`, `contrast_ratio`; JND 5.0) from
the working tree and never re-implements them. It reads the spec and the pins file from the
working tree and every cited file AS TEXT with `git show` at the pinned base (`BASE`).
Default-deny: a gate that cannot read its input FAILs.

Gates (each FAIL led by its name):
  G-STATE     every frame the ticket's scope and states name has a §0 row, and each of the four
              acceptance criteria (AC-1 … AC-4) maps to frames that §0 lists.
  G-CHECKLIST every item of `14`'s SCR-094 and SCR-095 sign-off checklists at the base is a §8 row,
              verbatim, with a frame that §0 lists.
  G-TOKEN     every design token the spec names is in a merged set.
  G-CONTRAST  every §7.1 row is recomputed per theme and equals the spec to two decimals; a `text`
              row is at least 4.5:1 and a `ui` row at least 3:1 in every theme; the verdict matches.
  G-CVD       every §7.2 row's ΔE76 (normal and the three simulations) and its greyscale ratio
              equal the tool's to two decimals, and its JND column names the simulations under 5.0.
  G-SAMPLE    the low-sample caveat is attached to every headline number (§3.3, S95-03): the n line
              becomes the caveat, the value's `aria-describedby` points at it (§3.3 and CMP-168's
              A11y), and the page notice is a second carrier that never holds the per-number caveat;
              the small bucket is marked in text with no opacity (§3.5, S95-04); the scatter's
              outcome is carried by shape (filled circle, hollow square, hollow diamond).
  G-TABLE     each §3.4 chart has a CMP-049 table alternative and a §5 summary key, §3.4 names the
              "View as table" toggle, and the context pane's table state (S94-12) exists.
  G-CONTEXT   the context-not-recorded and pruned rows name what is missing (`context.missing`),
              the pruned row and §2.4 offer bar replay, and §2.4 / S94-02 rule out a spinner.
  G-T2        every state row whose Presentation is T2 names its rendering (2a, 2b or the sentence
              form), CMP-079 and the CMP-019 `lock`; every reason it quotes after an `rbac.*` or
              `notice.*` key is that key's text in E09-D09 at the base (unless marked PROPOSED), and a
              `{verb}` is the §3.2 verb of a permission code the row names; the Viewer and view-as
              rows (S94-09, S94-11) gate the journal writes and both replay actions; §1 item 4
              quotes G-T2.1b, G-T2.2, G-T2.3 and G-T2.6 verbatim from `DS`; §7.1 carries the
              tertiary label pair; AR-3 and AR-5 list CMP-079 and `lock`.
  G-COPY      every §5 row is verbatim (its string found on its cited line at the base, `{slots}`
              as wildcards) or PROPOSED with an owner.
  G-AROW      AR-1 … AR-12 (spec-local ids, never the memo's A-n, BQ-03) are present, and every Old
              text stands exactly once in its target at the base, on its cited line.
  G-MERGED    the unmerged E41-D02 appears only on a request row or a line saying so.
  G-CITE      every cite in range and on a non-blank line at its base, and equal to the pins.
  G-HYGIENE   no closing keyword, local path, URL or host, agent name, double-brace slot or deny
              word in the spec; no deny word in this tool's text or the pins.
  G-SCOPE     the diff touches only the spec, this tool and the pins file.
  G-ENV       paper trades are their own scope (`11`:4697): §3.2 never counts them in a LIVE or
              DEMO figure and gives them their own switch, states the ruled asymmetry with SCR-093
              (BQ-16) and never calls replay results paper; S95-16 draws the paper scope, and G-5
              names `is_paper`.
  G-AUTO      the joint BQ-15 / #1018 BQ-07 ruling: an auto tag is removable, the removal recorded,
              on SCR-094 only; §2.6 and C-9 say SCR-093 and SCR-096 show it with no remove control.
  G-OWNER     the BQ-24 ruling of #1018 as it reaches these screens: SCR-095's "Manage tags" names
              rename, merge and delete as owner-only (C-12.4) and is T2 for a Viewer (S95-17), and
              the Tag breakdown counts granted accounts only.
  G-GROUP     BQ-11 (C-2.12): §2.5 and S94-10 draw each ungranted leg with no account label, no
              figure and no link; with any leg out of scope the total is `group.total_partial`,
              over the granted legs and labelled partial, never the full group total; both totals
              are server-served and grant-scoped, and G-3 names the read; `group.out_of_scope`
              carries no slot.
  G-COHORT    BQ-07: §3.2's cohort set is E41-S03's (range, account, symbol, tag) and says that
              setup and side are not cohort filters.

Usage (from the repo root):
  python3 -I docs/design/_tools/e41_d03_hifi_audit.py --check
  python3 -I docs/design/_tools/e41_d03_hifi_audit.py --fill        (writes §7's figures)
  python3 -I docs/design/_tools/e41_d03_hifi_audit.py --self-test
  python3 -I docs/design/_tools/e41_d03_hifi_audit.py --repin-ruled (the pins' only writer)
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
SPEC_REL = "docs/design/E41/E41-D03.md"
TOOL_REL = "docs/design/_tools/e41_d03_hifi_audit.py"
PINS_REL = "docs/design/_tools/e41_d03_ruled_pins.txt"
OWN_PATHS = (SPEC_REL, TOOL_REL, PINS_REL)
BASE = "a7d659a5bee5d06a28950f324800f84dc3853e6f"  # origin/main when written; re-pinned by content
TOKENS = ROOT / "packages" / "ui" / "tokens"
CVD_PATH = ROOT / "docs" / "research" / "_tools" / "cvd_simulate.py"
CONTRAST_PATH = ROOT / "docs" / "design" / "_tools" / "contrast_check.py"
PATHS: dict[str, str] = {
    "04": "docs/plan/04-security-program.md",
    "05": "docs/plan/05-accessibility-standard.md",
    "11": "docs/plan/11-user-stories.md",
    "12": "docs/plan/12-sitemap.md",
    "14": "docs/plan/14-screens-catalogue.md",
    "15": "docs/plan/15-component-catalogue.md",
    "22": "docs/plan/22-api-openapi.yaml",
    "24": "docs/plan/24-internal-schemas.md",
    "D01": "docs/design/research/e41-journal-review.md",
    "E09D09": "docs/design/E09/E09-D09.md",
    "E10D03": "docs/design/E10/E10-D03.md",
    "E05D03": "docs/design/E05/E05-D03.md",
    "E47D04": "docs/design/E47/E47-D04.md",
    "DS": ".claude/rules/32-design-specs.md",
}
CITE = re.compile(r"`(\d\d|E09D09|E10D03|E05D03|E47D04|D01|DS)`:(\d+(?:–\d+)?(?:, :\d+(?:–\d+)?)*)")
TOKEN_NAME = re.compile(
    r"`((?:color|font|border|radius|type|space|size|motion|opacity)\.[a-z0-9.-]*[a-z0-9])`"
)
CLOSING = re.compile(r"\b(?:close[sd]?|fix(?:e[sd])?|resolve[sd]?)\s+#\d+", re.IGNORECASE)
LOCAL_PATH = re.compile("/" + "home/|/Users/|/" + "tmp/|[A-Za-z]:\\\\|\\bwt-" + "notes\\b")
AGENT_NAME = re.compile(r"\b[a-z]{2,4}-worker-\d\b")
URL_OR_HOST = re.compile(r"https?://|penpot\.[a-z]|team-id=|file-id=", re.IGNORECASE)
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
)  # each entry an explicit join, so this tool's own text carries none of the words
THEMES = ("dark", "light", "high-contrast")
FLOOR = {"text": 4.5, "ui": 3.0}
DEFICIENCIES = ("protanopia", "deuteranopia", "tritanopia")
REQUIRED_FRAMES = (
    "SCR-094/default",
    "SCR-094/loading",
    "SCR-094/bar-only",
    "SCR-094/context-not-recorded",
    "SCR-094/pruned",
    "SCR-094/error",
    "SCR-094/long-text",
    "SCR-094/keyboard-focus",
    "SCR-094/viewer-read-only",
    "SCR-094/group-out-of-scope",
    "SCR-094/context-table",
    "SCR-094/page-error",
    "SCR-094/not-found",
    "SCR-094/reconciling",
    "SCR-094/snapshot-failed",
    "SCR-095/default",
    "SCR-095/table-view",
    "SCR-095/insufficient-sample",
    "SCR-095/low-bucket",
    "SCR-095/empty",
    "SCR-095/no-match",
    "SCR-095/loading",
    "SCR-095/error",
    "SCR-095/demo-scope",
    "SCR-095/filters",
    "SCR-095/long-text",
    "SCR-095/keyboard-focus",
    "SCR-095/transfer-marked",
    "SCR-095/statistics-legend",
    "SCR-095/paper-scope",
    "CMP-167/default",
    "CMP-167/with-drawdown",
    "CMP-167/table-view-toggle",
    "CMP-168/default",
    "a11y/cvd-scatter-histogram",
)
ACS = ("AC-1", "AC-2", "AC-3", "AC-4")
CHECKLISTS = (("8.1", 2207), ("8.2", 2219))  # `14` lines of SCR-094's and SCR-095's checklists
FRAME = re.compile(r"`((?:SCR-\d{3}|CMP-\d{3}|[a-z0-9-]+)/[a-z0-9-]+)`")
UNMERGED = re.compile(r"E41-D02|#1018")
PAPER_ASYM = "SCR-095 hides paper by default behind this explicit second scope row"
AUTO_ONLY = "removable, with the removal recorded, on SCR-094 only"
AUTO_NONE = "no remove control"
OWNER_LINE = "its rename, merge and delete are owner-only (`rbac.owner_only`; C-12.4)"
TAG_SCOPE = "a tag's count covers trades on granted accounts only"
GROUP_LEG = "with no account label, no figure and no link"
GROUP_ROW = (
    "no label, figure or link; `group.total_partial` over the granted legs, labelled partial"
)
GROUP_PARTIAL = "with any leg out of scope it reads `group.total_partial`"
GROUP_SERVER = "**Both totals are served by the server**, grant-scoped"
COHORT_SET = (
    "range (CMP-047, UTC, default the last 30 days), account (granted accounts only), symbol and"
    " tag; the environment is the scope switch above, and setup and side are not cohort filters"
)
AROWS = tuple(f"AR-{i}" for i in range(1, 13))  # spec-local, never the memo's A-n (BQ-03)


@dataclass(frozen=True)
class Texts:
    spec: str
    pins: str
    tool: str
    changed: list[str] | None
    memo: dict[str, str | None]


def git(*args: str) -> str | None:
    try:
        r = subprocess.run(["git", "-C", str(ROOT), *args], capture_output=True, check=False)
    except OSError:
        return None
    return r.stdout.decode("utf-8", "surrogateescape") if r.returncode == 0 else None


def at(t: Texts, key: str) -> str:
    k = f"{BASE}:{PATHS[key]}"
    if k not in t.memo:
        t.memo[k] = git("show", k)
    text = t.memo[k]
    if text is None:
        raise SystemExit(f"{PATHS[key]} does not resolve at {BASE[:10]}; fetch first")
    return text


def _load(path: Path, name: str) -> ModuleType:
    spec = importlib.util.spec_from_file_location(name, path)
    if spec is None or spec.loader is None:
        raise SystemExit(f"cannot load {path}")
    m = importlib.util.module_from_spec(spec)
    sys.modules[name] = m
    spec.loader.exec_module(m)
    return m


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


def norm(s: str) -> str:
    return " ".join(s.split())


def cells(ln: str) -> list[str]:
    return [c.strip() for c in ln.strip().strip("|").split("|")]


def table_rows(text: str, lead: str) -> list[list[str]]:
    return [cells(ln) for ln in text.split("\n") if ln.startswith("| " + lead)]


def section(text: str, head: str) -> str:
    i = text.find("\n" + head)
    if i < 0:
        return ""
    level = len(head.split(" ")[0])
    m = re.compile(rf"\n#{{1,{level}}} ").search(text, i + 1)
    return text[i : m.start() if m else len(text)]


def row(t: Texts, lead: str) -> list[str]:
    rows = table_rows(t.spec, lead + " ")
    if len(rows) != 1:
        raise LookupError(f"the spec carries {len(rows)} `{lead}` rows, not 1")
    return rows[0]


# ---------------------------------------------------------------------------- tokens and figures

_THEMES: dict[str, dict[str, str]] = {}


def theme(name: str) -> dict[str, str]:
    """The colour tokens of one theme, resolved as E10-D03's tool does."""
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


def known_tokens() -> set[str]:
    v = mod("verify_tokens")
    names: set[str] = set(v.load(v.PRIMITIVES))
    for th in THEMES:
        names |= set(v.merged_set(v.THEMES[th]))
    return names


def hex_rgb(h: str) -> tuple[int, int, int]:
    h = h.lstrip("#")
    return int(h[0:2], 16), int(h[2:4], 16), int(h[4:6], 16)


def color(th: str, name: str) -> str:
    t = theme(th)
    if name not in t:
        raise LookupError(f"`{name}` does not resolve in {th}")
    return t[name][:7]


def tok(cell: str) -> str:
    m = re.fullmatch(r"`([a-z0-9.-]+)`", cell)
    if not m:
        raise LookupError(f"{cell!r} is not one token")
    return m[1]


def contrast_values(r: list[str]) -> list[str]:
    cc = mod("contrast_check")
    fg, bg = tok(r[1]), tok(r[2])
    return [
        f"{cc.contrast_ratio(hex_rgb(color(th, fg)), hex_rgb(color(th, bg))):.2f}" for th in THEMES
    ]


def cvd_values(r: list[str]) -> tuple[str, str, str]:
    cv = mod("cvd_simulate")
    th = {"hc": "high-contrast"}.get(r[3], r[3])
    ha, hb = color(th, tok(r[1])), color(th, tok(r[2]))
    ds = [cv.delta_e76(ha, hb)] + [
        cv.delta_e76(cv.simulate(ha, d), cv.simulate(hb, d)) for d in DEFICIENCIES
    ]
    under = [n for n, d in zip(("normal", *DEFICIENCIES), ds, strict=True) if d < cv.JND_FLOOR]
    grey = f"{cv.contrast_ratio(ha, hb):.2f}"
    return " / ".join(f"{d:.2f}" for d in ds), grey, (", ".join(under) if under else "none")


def verdict(role: str, values: list[str]) -> str:
    floor = FLOOR.get(role)
    if floor is None:
        return "reported"  # structure: reported, never gated
    return "pass" if min(map(float, values)) >= floor else "FAIL"


# ---------------------------------------------------------------------------- cites


def cites(text: str) -> list[tuple[str, int, int]]:
    out = []
    for m in CITE.finditer(text):
        for part in m[2].split(", :"):
            a, _, b = part.partition("–")
            out.append((m[1], int(a), int(b or a)))
    return out


def cite_hashes(t: Texts) -> tuple[dict[str, str], list[str]]:
    hashes: dict[str, str] = {}
    bad: list[str] = []
    for key, a, b in cites(t.spec):
        label = f"{key}:{a}" if a == b else f"{key}:{a}–{b}"
        if label in hashes:
            continue
        ls = at(t, key).split("\n")
        if not 0 < a <= b <= len(ls):
            bad.append(f"{label} is past the end of {PATHS[key]} ({len(ls)} lines)")
            continue
        blank = [n for n in (a, b) if not ls[n - 1].strip()]
        if blank:
            bad.append(f"{label}: line {blank[0]} is blank at its base")
            continue
        joined = norm(ls[a - 1]) + "\n" + norm(ls[b - 1])
        hashes[label] = hashlib.sha256(joined.encode()).hexdigest()[:12]
    return hashes, bad


def parse_pins(text: str) -> dict[str, str]:
    out = {}
    for ln in text.split("\n"):
        parts = ln.split("\t")
        if len(parts) == 2 and not ln.startswith("#"):
            out[parts[0]] = parts[1]
    return out


# ---------------------------------------------------------------------------- gates


def frames(t: Texts) -> set[str]:
    zero = section(t.spec, "## 0.")
    return {r[1].strip("`") for r in table_rows(zero, "B") if len(r) > 1}


def g_state(t: Texts) -> list[str]:
    have = frames(t)
    bad = [f"no §0 frame row for `{f}`" for f in REQUIRED_FRAMES if f not in have]
    acs = {r[0]: FRAME.findall(r[2]) for r in table_rows(section(t.spec, "## 0."), "AC-")}
    for ac in ACS:
        if not acs.get(ac):
            bad.append(f"{ac} maps to no frame in §0")
        bad += [
            f"{ac} maps to `{f}`, which §0 does not list" for f in acs.get(ac, []) if f not in have
        ]
    return bad


def g_checklist(t: Texts) -> list[str]:
    bad = []
    ls = at(t, "14").split("\n")
    have = frames(t)
    for head, n in CHECKLISTS:
        line = ls[n - 1]
        if "Design sign-off acceptance checklist" not in line:
            raise LookupError(f"`14`:{n} is no longer a sign-off checklist")
        items = [norm(x) for x in line.split("[ ]")[1:]]
        rows = {norm(r[0]): r for r in table_rows(section(t.spec, "### " + head), "")[2:]}
        for it in items:
            r = rows.get(it)
            if r is None:
                bad.append(f"§{head}: `14`:{n}'s item {it[:50]!r} has no verbatim row")
            elif not FRAME.findall(r[-1]) or FRAME.findall(r[-1])[0] not in have:
                bad.append(f"§{head}: {it[:40]!r} maps to no §0 frame")
        if len(rows) != len(items):
            bad.append(f"§{head}: {len(rows)} rows for {len(items)} checklist items")
    return bad


def g_token(t: Texts) -> list[str]:
    known = known_tokens()
    return [
        f"`{n}` does not resolve in the token JSON at the base"
        for n in sorted(set(TOKEN_NAME.findall(re.sub(r'Old: ".+?"\. New:', "", t.spec))))
        if n not in known
    ]


def g_contrast(t: Texts) -> list[str]:
    bad = []
    rows = table_rows(section(t.spec, "### 7.1"), "P-")
    if not rows:
        return ["§7.1 has no contrast rows"]
    for r in rows:
        if len(r) != 8:
            bad.append(f"{r[0]}: {len(r)} cells, not 8")
            continue
        want = contrast_values(r)
        if r[4:7] != want:
            bad.append(f"{r[0]}: reads {r[4:7]}, the tokens give {want}")
        floor = FLOOR.get(r[3])
        if r[3] not in ("text", "ui", "structure"):
            bad.append(f"{r[0]}: role {r[3]!r} is not text, ui or structure")
        elif floor is not None and min(float(x) for x in want) < floor:
            bad.append(f"{r[0]}: below {floor}:1 for a `{r[3]}` pair")
        if r[7] != verdict(r[3], want):
            bad.append(f"{r[0]}: verdict reads {r[7]!r}, not {verdict(r[3], want)!r}")
    return bad


def g_cvd(t: Texts) -> list[str]:
    bad = []
    rows = table_rows(section(t.spec, "### 7.2"), "V-")
    if not rows:
        return ["§7.2 has no CVD rows"]
    for r in rows:
        if len(r) != 7:
            bad.append(f"{r[0]}: {len(r)} cells, not 7")
            continue
        want = cvd_values(r)
        if (r[4], r[5], r[6]) != want:
            bad.append(f"{r[0]}: reads {r[4:7]}, the tool gives {list(want)}")
    return bad


def g_sample(t: Texts) -> list[str]:
    bad = []
    s33, s35 = section(t.spec, "### 3.3"), section(t.spec, "### 3.5")
    para = next((p for p in s33.split("\n\n") if p.strip().startswith("**Under 20 trades")), "")
    head, _, notice = para.partition("The page also carries")
    if any(w not in head for w in SAMPLE_HEAD):
        bad.append("§3.3: the caveat is not attached to every headline number (AC-1)")
    if SAMPLE_BINDING not in head:
        bad.append("§3.3: the value's `aria-describedby` does not point at the caveat (AC-1)")
    if "the notice is never the only carrier" not in notice or "not statistically" in notice:
        bad.append("§3.3: the page notice is not a second carrier only (it holds the caveat)")
    if CMP168_BINDING not in section(t.spec, "## 4."):
        bad.append("§4: CMP-168's value is not described by its n line or caveat")
    if "caveat attached to each number" not in row(t, "S95-03")[3]:
        bad.append("S95-03: the insufficient-sample state does not attach the caveat per number")
    if '"Low sample (n = 3)"' not in s35 or "no opacity is used" not in s35:
        bad.append("§3.5: the small bucket is not marked in text without opacity (AC-2)")
    if "Low sample (n = 3)" not in row(t, "S95-04")[3]:
        bad.append("S95-04: the low-bucket state carries no text marker")
    scatter = section(t.spec, "### 3.4")
    for shape in ("filled circle", "hollow square", "hollow diamond"):
        if shape not in scatter:
            bad.append(f"§3.4: the scatter's outcome shape {shape!r} is missing")
    return bad


SAMPLE_HEAD = (
    "every tile's n line becomes the caveat",
    "attached to the number",
    "12 trades — not statistically meaningful",
)
SAMPLE_BINDING = (
    "the value's `aria-describedby` points at it, so the caveat is read with the number"
)
CMP168_BINDING = "the value's `aria-describedby` points at the n line or the caveat"


def g_table(t: Texts) -> list[str]:
    bad = []
    s34 = section(t.spec, "### 3.4")
    keys = {r[0].strip("`") for r in table_rows(section(t.spec, "## 5."), "`")}
    rows = [r for r in table_rows(s34, "") if len(r) == 4 and r[0] not in ("Chart", "")]
    rows = [r for r in rows if not set(r[0]) <= set("-")]
    if len(rows) != 3:
        bad.append(f"§3.4 lists {len(rows)} charts, not 3")
    for r in rows:
        if "·" not in r[2]:
            bad.append(f"§3.4 {r[0][:30]!r}: no table-alternative columns")
        if r[3].strip("`") not in keys:
            bad.append(f"§3.4 {r[0][:30]!r}: summary {r[3]!r} is not a §5 key")
    if 'a toggle button "View as table"' not in s34 or "CMP-049" not in s34:
        bad.append('§3.4 does not name the "View as table" toggle and CMP-049 (AC-4)')
    if "View as table" not in row(t, "S94-12")[2]:
        bad.append("S94-12: the context pane has no table state")
    return bad


def g_context(t: Texts) -> list[str]:
    bad = []
    for sid, word in (("S94-04", "context.none"), ("S94-05", "context.pruned")):
        pres = row(t, sid)[3]
        if word not in pres or "context.missing" not in pres:
            bad.append(f"{sid}: does not name what is missing ({word} + context.missing)")
    if "Open bar replay" not in row(t, "S94-05")[2] or "Open bar replay" not in section(
        t.spec, "### 2.4"
    ):
        bad.append("the pruned state does not offer bar-level replay (AC-3)")
    if "never shows an indefinite spinner" not in section(t.spec, "### 2.4"):
        bad.append("§2.4 does not rule out an indefinite spinner")
    if "never a spinner" not in row(t, "S94-02")[3]:
        bad.append("S94-02: the loading state does not end at the 1.5 s budget")
    return bad


def template_rx(q: str) -> re.Pattern[str]:
    """A key's string as a pattern: `{verb}` a named group, any other `{slot}` a wildcard."""
    out = ""
    for part in re.split(r"(\{[a-z_]+\})", q):
        out += (
            "(?P<verb>.+?)" if part == "{verb}" else ".+?" if part[:1] == "{" else re.escape(part)
        )
    return re.compile(out + "$")


def e09_keys(t: Texts) -> dict[str, list[re.Pattern[str]]]:
    """E09-D09's `rbac.*` and `notice.*` keys at the base, each to its string's pattern(s)."""
    keys: dict[str, list[re.Pattern[str]]] = {}
    for ln in at(t, "E09D09").split("\n"):
        m = re.match(r'\| `((?:rbac|notice)\.[a-z_]+)` +\| "([^"]+)"', ln)
        if m:
            keys.setdefault(m[1], []).append(template_rx(m[2]))
    rbac = [r.pattern for k, v in keys.items() if k.startswith("rbac.") for r in v]
    if "notice.panel_read_only" in keys:  # "Read-only — {rbac sentence, first letter lower-cased}"
        keys["notice.panel_read_only"] = [
            re.compile(re.escape("Read-only — ") + p[:1].lower() + p[1:]) for p in rbac
        ]
    return keys


def e09_verbs(t: Texts) -> dict[str, str]:
    """E09-D09 §3.2: each permission code to its `{verb}`."""
    out: dict[str, str] = {}
    for ln in at(t, "E09D09").split("\n"):
        if ln.startswith("| ") and "→" in ln:
            out.update(re.findall(r'`([a-z]+:[a-z_]+)` → "([^"]+)"', ln))
    return out


RENDERING = re.compile(r"rendering (2a|2b|the sentence form)")
KEYED = re.compile(r'`((?:rbac|notice)\.[a-z_]+)` "([^"]+)"')
T2_CONTROLS = ("Add note", "Add tag", "Open in replay", "Open bar replay")
T2_QUOTES = (
    (
        "G-T2.1b",
        (
            '`aria-disabled="true"`, never the `disabled` attribute — it stays in the Tab'
            " order and a menu item stays arrow-reachable"
        ),
    ),
    (
        "G-T2.2",
        (
            "hi-fi label `color.text.tertiary`, reason `color.text.secondary`; for primary /"
            " buy / sell actions the fill becomes `color.surface.raised` with a"
            " `color.border.default` hairline; never `color.text.disabled`, never"
            " `opacity.disabled` on the label, glyph or reason"
        ),
    ),
    (
        "G-T2.6",
        (
            "T2 is named in every state row and frame that shows a gated control; CMP-079 and"
            " CMP-019 `lock` appear in every component list and component amendment that covers"
            " those surfaces"
        ),
    ),
    (
        "G-T2.3",
        (
            "`Enter`, `Space` or a bound hotkey on a T2 control changes nothing and re-shows"
            " the reason inline with one polite announcement"
        ),
    ),
)


def g_t2(t: Texts) -> list[str]:
    bad = []
    rows = [r for r in table_rows(t.spec, "S94-") + table_rows(t.spec, "S95-") if len(r) >= 4]
    keys, verbs = e09_keys(t), e09_verbs(t)
    t2 = [r for r in rows if "T2" in r[3]]
    if not t2:
        return ["no state row carries T2 (the Viewer and view-as states)"]
    for rid in ("S94-09", "S94-11"):
        miss = [c for c in T2_CONTROLS if c not in row(t, rid)[3]]
        if miss:
            bad.append(f"{rid}: {', '.join(miss)} not gated (the journal and replay writes, G-T2)")
    for r in t2:
        if not RENDERING.search(r[3]):
            bad.append(f"{r[0]}: a T2 control with no rendering (2a, 2b or the sentence form)")
        if "CMP-079" not in r[3] or "CMP-019 `lock`" not in r[3]:
            bad.append(f"{r[0]}: the T2 row does not name CMP-079 and the CMP-019 `lock` (G-T2.6)")
        quoted = KEYED.findall(r[3])
        if not quoted:
            bad.append(f"{r[0]}: a T2 presentation with no keyed reason")
        named = {verbs[c] for c in re.findall(r"`([a-z]+:[a-z_]+)`", r[3]) if c in verbs}
        for key, q in quoted if "PROPOSED" not in r[3] else []:
            hits = [m for m in (rx.match(q) for rx in keys.get(key, [])) if m]
            if not hits:
                bad.append(f"{r[0]}: {q!r} is not E09-D09's text for `{key}`")
            elif "verb" in hits[0].groupdict() and hits[0]["verb"] not in named:
                bad.append(
                    f"{r[0]}: the verb {hits[0]['verb']!r} is no §3.2 verb of a code it names"
                )
    owner = norm(at(t, "DS").replace("**", ""))
    item4 = norm(section(t.spec, "## 1."))
    for gid, q in T2_QUOTES:
        if norm(q) not in owner:
            bad.append(f"{gid}: the quote is no longer `DS`'s text at the base")
        elif f"{gid}, verbatim" not in item4 or norm(q) not in item4:
            bad.append(f"§1 item 4 does not quote {gid} verbatim from `DS`")
    if "CMP-019 `lock`" not in item4:
        bad.append("§1 item 4 does not state the CMP-019 `lock` that leads a T2 label")
    pairs = {(r[1], r[2]) for r in table_rows(section(t.spec, "### 7.1"), "P-") if len(r) > 2}
    if ("`color.text.tertiary`", "`color.surface.raised`") not in pairs:
        bad.append("§7.1 has no `color.text.tertiary` on `color.surface.raised` pair (G-T2.2)")
    for aid, scr in (("AR-3", "SCR-094"), ("AR-5", "SCR-095")):
        ar = next((ln for ln in t.spec.split("\n") if ln.startswith(f"- **{aid},")), "")
        if "CMP-079" not in ar or "`lock`" not in ar:
            bad.append(f"{aid}: {scr}'s component list gains no CMP-079 and `lock` (G-T2.6)")
    return bad


def slot_rx(s: str) -> re.Pattern[str]:
    return re.compile(".+?".join(re.escape(x) for x in re.split(r"\{[a-z]+\}", s)))


def g_copy(t: Texts) -> list[str]:
    bad = []
    rows = [r for r in table_rows(section(t.spec, "## 5."), "`") if len(r) == 3]
    if not rows:
        return ["§5 has no copy rows"]
    for key, string, source in rows:
        if source.startswith("PROPOSED"):
            if "owner" not in source:
                bad.append(f"{key}: PROPOSED with no owner")
            continue
        m = CITE.search(source)
        if not source.startswith("verbatim") or m is None:
            bad.append(f"{key}: neither verbatim with a cite nor PROPOSED with an owner")
            continue
        q = re.search(r'"(.+?)"$', string) or re.search(r'"(.+?)"', string)
        n = int(m[2].split("–")[0])
        line = at(t, m[1]).split("\n")[n - 1]
        if q is None or not slot_rx(q[1]).search(line):
            bad.append(f"{key}: the string is not on `{m[1]}`:{n} at the base")
    return bad


def g_arow(t: Texts) -> list[str]:
    bad = []
    lines = [ln for ln in section(t.spec, "## 9.").split("\n") if ln.startswith("- **AR-")]
    got = [m[1] for m in (re.match(r"- \*\*(AR-\d+),", ln) for ln in lines) if m]
    if tuple(got) != AROWS:
        bad.append(f"the amendment rows are {got}, not AR-1 … AR-12")
    for ln in lines:
        aid = ln[4 : ln.index(",")]
        cite = CITE.search(ln)
        olds = re.findall(r'Old: "(.+?)"\. New:', ln)
        if cite is None or not olds:
            bad.append(f"{aid}: no cited line or no Old text")
            continue
        text = at(t, cite[1])
        n = int(cite[2].split("–")[0])
        for o in olds:
            if text.count(o) != 1:
                bad.append(f"{aid}: {o[:40]!r} stands {text.count(o)} times in `{cite[1]}`")
            elif o not in text.split("\n")[n - 1]:
                bad.append(f"{aid}: {o[:40]!r} is not on `{cite[1]}`:{n}")
    return bad


def g_merged(t: Texts) -> list[str]:
    return [
        f"spec:{i} leans on the unmerged E41-D02 outside a request row"
        for i, ln in enumerate(t.spec.split("\n"), 1)
        if UNMERGED.search(ln) and not (ln.startswith("| R-") or "request row" in ln)
    ]


def g_cite(t: Texts) -> list[str]:
    hashes, bad = cite_hashes(t)
    pinned = parse_pins(t.pins)
    for label, h in hashes.items():
        if label not in pinned:
            bad.append(f"cite {label} is unpinned: verify it by content, then --repin-ruled")
        elif pinned[label] != h:
            bad.append(f"cite {label}: the line at its base is not the pinned content")
    return bad


def g_hygiene(t: Texts) -> list[str]:
    bad = []
    checks = ((CLOSING, "a closing keyword (PR 2 alone closes #1081)"), (LOCAL_PATH, "a local path"),
              (AGENT_NAME, "an agent name"), (URL_OR_HOST, "a URL or a host"))  # fmt: skip
    for i, ln in enumerate(t.spec.split("\n"), 1):
        bad += [f"spec:{i} carries {what}" for rx, what in checks if rx.search(ln)]
        if "{{" in ln:
            bad.append(f"spec:{i} carries a double-brace slot")
        if any(d in ln.lower() for d in DENY):
            bad.append(f"spec:{i} carries a public-text deny word")
    for label, text in (("tool", t.tool), ("pins", t.pins)):
        for i, ln in enumerate(text.split("\n"), 1):
            if any(d in ln.lower() for d in DENY):
                bad.append(f"{label}:{i} carries a public-text deny word")
    return bad


def g_scope(t: Texts) -> list[str]:
    if t.changed is None:
        return ["cannot list the changed paths (git failed)"]
    own = ", ".join(OWN_PATHS)
    return [f"{p} is touched; this ticket owns {own}" for p in t.changed if p not in OWN_PATHS]


def g_env(t: Texts) -> list[str]:
    bad = []
    s32 = section(t.spec, "### 3.2")
    for words, what in (
        ("never counted in a LIVE or DEMO figure", "keeps paper out of LIVE and DEMO figures"),
        ("Show paper trades instead", "gives paper its own switch"),
        ("`11`:4697", "cites the never-mixed story"),
    ):
        if words not in s32:
            bad.append(f"§3.2 no longer {what} (`11`:4697)")
    paper = [r for r in table_rows(t.spec, "S95-") if r[-1] == "`SCR-095/paper-scope`"]
    if not paper:
        bad.append("no S95 row draws the paper scope (`SCR-095/paper-scope`)")
    if "`is_paper`" not in row(t, "G-5")[1]:
        bad.append("G-5 does not name `is_paper` for the journal reads")
    if PAPER_ASYM not in s32:
        bad.append("§3.2 does not state the paper asymmetry with SCR-093 (BQ-16)")
    if re.search(r"[Rr]eplay results are paper", t.spec):
        bad.append("the spec calls replay results paper (BQ-16: replay is a third class)")
    return bad


def g_auto(t: Texts) -> list[str]:
    bad = []
    s26 = section(t.spec, "### 2.6")
    tags = next((ln for ln in s26.split("\n") if ln.startswith("- **Tags:**")), "")
    if AUTO_ONLY not in tags:
        bad.append("§2.6: the auto tag is not removable on SCR-094 only, recorded (BQ-15)")
    if AUTO_NONE not in tags:
        bad.append("§2.6: SCR-093 and SCR-096 are not said to show no remove control (BQ-15)")
    c9 = row(t, "C-9")[2]
    if "SCR-094 only" not in c9 or AUTO_NONE not in c9:
        bad.append("C-9 does not carry the joint ruling (SCR-094 only; none elsewhere)")
    return bad


def g_group(t: Texts) -> list[str]:
    bad = []
    s25 = section(t.spec, "### 2.5")
    if GROUP_LEG not in s25:
        bad.append("§2.5: an ungranted leg is drawn with its account label, a figure or a link")
    if GROUP_PARTIAL not in s25:
        bad.append("§2.5: with a leg out of scope the total is not `group.total_partial`")
    if GROUP_SERVER not in s25:
        bad.append("§2.5: the group and partial totals are not server-served and grant-scoped")
    if GROUP_ROW not in row(t, "S94-10")[3]:
        bad.append("S94-10: not one bare row per ungranted leg with a partial total (BQ-11)")
    if "total" not in row(t, "G-3")[1]:
        bad.append("G-3 does not name the grant-scoped group and partial totals")
    if "{" in row(t, "`group.out_of_scope`")[1]:
        bad.append("`group.out_of_scope` carries a slot: an ungranted leg shows nothing of its own")
    return bad


def g_cohort(t: Texts) -> list[str]:
    s32 = section(t.spec, "### 3.2")
    cohort = next((ln for ln in s32.split("\n") if ln.startswith("- **Cohort bar**")), "")
    if COHORT_SET not in cohort:
        return ["§3.2: the cohort set is not E41-S03's (range, account, symbol, tag; BQ-07)"]
    return []


def g_owner(t: Texts) -> list[str]:
    bad = []
    if OWNER_LINE not in section(t.spec, "### 3.1"):
        bad.append("§3.1: Manage tags does not name the tag manager's owner-only writes (BQ-24)")
    s17 = row(t, "S95-17")
    if "T2" not in s17[3] or "Manage tags" not in s17[2]:
        bad.append("S95-17: Manage tags is not T2 for a Viewer and under view-as")
    if TAG_SCOPE not in section(t.spec, "### 3.5"):
        bad.append("§3.5: the Tag breakdown's counts are not grant-scoped")
    return bad


GATES: dict[str, Callable[[Texts], list[str]]] = {
    "G-STATE": g_state, "G-CHECKLIST": g_checklist, "G-TOKEN": g_token, "G-CONTRAST": g_contrast,
    "G-CVD": g_cvd, "G-SAMPLE": g_sample, "G-TABLE": g_table, "G-CONTEXT": g_context,
    "G-T2": g_t2, "G-COPY": g_copy, "G-AROW": g_arow, "G-MERGED": g_merged, "G-CITE": g_cite,
    "G-HYGIENE": g_hygiene, "G-SCOPE": g_scope, "G-ENV": g_env, "G-AUTO": g_auto,
    "G-OWNER": g_owner, "G-GROUP": g_group, "G-COHORT": g_cohort,
}  # fmt: skip


def audit(t: Texts) -> list[tuple[str, str]]:
    out = []
    for g, fn in GATES.items():
        try:
            out += [(g, m) for m in fn(t)]
        except LookupError as e:
            out.append((g, str(e)))
    return out


# ---------------------------------------------------------------------------- load, fill, self-test


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
    tool = (ROOT / TOOL_REL).read_text(encoding="utf-8")
    return Texts(spec, pins, tool, changed_paths(), {})


def fill(t: Texts) -> str:
    out = []
    for ln in t.spec.split("\n"):
        c = cells(ln)
        if ln.startswith("| P-") and len(c) == 8:
            v = contrast_values(c)
            c[4:8] = [*v, verdict(c[3], v)]
            ln = "| " + " | ".join(c) + " |"
        elif ln.startswith("| V-") and len(c) == 7:
            c[4], c[5], c[6] = cvd_values(c)
            ln = "| " + " | ".join(c) + " |"
        out.append(ln)
    return "\n".join(out)


def sub(old: str, new: str) -> Callable[[Texts], Texts]:
    def f(t: Texts) -> Texts:
        if t.spec.count(old) != 1:
            raise SystemExit(f"self-test: the spec carries {old[:50]!r} {t.spec.count(old)} times")
        return replace(t, spec=t.spec.replace(old, new))

    return f


def set_cell(lead: str, col: int, value: str) -> Callable[[Texts], Texts]:
    def f(t: Texts) -> Texts:
        ls = t.spec.split("\n")
        i = next(k for k, ln in enumerate(ls) if ln.startswith(f"| {lead} "))
        c = cells(ls[i])
        c[col] = value
        ls[i] = "| " + " | ".join(c) + " |"
        return replace(t, spec="\n".join(ls))

    return f


def drop_row(lead: str) -> Callable[[Texts], Texts]:
    def f(t: Texts) -> Texts:
        return replace(
            t, spec="\n".join(ln for ln in t.spec.split("\n") if not ln.startswith(lead))
        )

    return f


def chain(*fns: Callable[[Texts], Texts]) -> Callable[[Texts], Texts]:
    def f(t: Texts) -> Texts:
        for fn in fns:
            t = fn(t)
        return t

    return f


MUTATIONS: tuple[tuple[str, str, Callable[[Texts], Texts]], ...] = (
    ("G-STATE", "drop the SCR-095 long-text frame row", drop_row("| B22 ")),
    ("G-STATE", "drop the AC-3 mapping", drop_row("| AC-3 ")),
    ("G-STATE", "drop the not-found frame row", drop_row("| B34 ")),
    ("G-CHECKLIST", "drop the replay-link checklist row", drop_row("| link into replay at the trade's timestamp ")),
    ("G-CHECKLIST", "paraphrase the small-sample item", sub("small-sample warning ('12 trades - not statistically meaningful')", "small-sample warning")),
    ("G-TOKEN", "misspell a token", sub("an outline in `color.text.secondary`", "an outline in `color.text.secondry`")),
    ("G-CONTRAST", "type a contrast figure off", set_cell("P-01", 4, "1.00")),
    ("G-CONTRAST", "report a ui pair as structure", set_cell("P-10", 3, "structure")),
    ("G-CVD", "type a ΔE figure off", set_cell("V-01", 4, "1.00 / 1.00 / 1.00 / 1.00")),
    ("G-CVD", "type a greyscale ratio off", set_cell("V-02", 5, "9.99")),
    ("G-SAMPLE", "move the caveat to a banner only", sub("becomes the caveat **attached to the number**", "becomes a page banner")),
    ("G-SAMPLE", "drop the caveat's aria-describedby binding", sub(", and the value's `aria-describedby` points at it, so the caveat is read with the number.", ".")),
    ("G-SAMPLE", "move the per-number caveat into the page notice", chain(sub('and "12 trades — not statistically meaningful", and', "and the n line, and"), sub("statistics are noisy\" (`14`:2213)", "statistics are noisy\" and \"12 trades — not statistically meaningful\" (`14`:2213)"))),
    ("G-SAMPLE", "mark small buckets by opacity", sub("no opacity is used", "the bar is dimmed")),
    ("G-SAMPLE", "encode the outcome by colour alone", sub("a hollow square (2 px)", "a filled dot (2 px)")),
    ("G-TABLE", "drop the toggle's name", sub('a toggle button "View as table" (`aria-pressed`', "a toggle button (`aria-pressed`")),
    ("G-TABLE", "give a chart an unknown summary key", set_cell("MAE and MFE", 3, "`summary.points`")),
    ("G-CONTEXT", "drop what is missing from the not-recorded row", set_cell("S94-04", 3, "`context.none` only")),
    ("G-CONTEXT", "let the loading state spin", set_cell("S94-02", 3, "a spinner until the data arrives")),
    ("G-T2", "drop the Viewer's rendering", set_cell("S94-09", 3, 'T2 `rbac.permission` "Your role can\'t write in the journal."; CMP-079 and the CMP-019 `lock`')),
    ("G-T2", "give S94-09's replay reason a wrong verb", sub('"Your role can\'t control replay." (`replay:write`)', '"Your role can\'t change settings." (`replay:write`)')),
    ("G-T2", "leave Open bar replay ungated under view-as", sub("rendering 2a inline on Open in replay and Open bar replay;", "rendering 2a inline on Open in replay;")),
    ("G-T2", "retype a key's text", sub('T2 `rbac.view_as` "Read-only while viewing as alex."', 'T2 `rbac.view_as` "Read only while someone views."')),
    ("G-T2", "let a T2 control leave the Tab order (G-T2.1b)", sub("never the `disabled` attribute — it stays in the Tab order", "or the `disabled` attribute")),
    ("G-T2", "dim a T2 label with the disabled tokens (G-T2.2)", sub("never `color.text.disabled`, never `opacity.disabled` on", "dimmed with `opacity.disabled` on")),
    ("G-T2", "drop the tertiary label pair (G-T2.2)", drop_row("| P-03 ")),
    ("G-COPY", "retype a verbatim string", set_cell("`caveat.sample`", 1, '"Fewer than 20 trades — statistics may be noisy"')),
    ("G-COPY", "drop a PROPOSED row's owner", sub("| PROPOSED — owner E41-D03 (D01's kit label)", "| PROPOSED (D01's kit label)")),
    ("G-AROW", "an Old text off by one character", sub('Old: "`stats: JournalStats`.". New:', 'Old: "`stats: JournalStat`.". New:')),
    ("G-MERGED", "cite the unmerged E41-D02", sub("the cohort bar (range, then each filter", "the cohort bar as E41-D02 draws it (range, then each filter")),
    ("G-CITE", "re-point a cite to an unpinned line", sub("(`D01`:170)", "(`D01`:172)")),
    ("G-HYGIENE", "write a closing keyword against #1081", sub("carries the closing line (BQ-01).", "carries the closing line (BQ-01). Closes #1081.")),
    ("G-HYGIENE", "put a deny word into the tool's own text", lambda t: replace(t, tool=t.tool + "\n# " + DENY[6] + "\n")),
    ("G-SCOPE", "touch `14` in the diff", lambda t: replace(t, changed=[*OWN_PATHS, PATHS["14"]])),
    ("G-ENV", "count paper trades in the LIVE figures", sub("never counted in a LIVE or DEMO figure", "counted in the LIVE or DEMO figures")),
    ("G-ENV", "drop the paper-scope state row", drop_row("| S95-16 ")),
    ("G-ENV", "drop the paper asymmetry", sub(PAPER_ASYM, "SCR-095 shows paper")),
    ("G-ENV", "call replay results paper again", sub("Replay results are a third class", "Replay results are paper, a third class")),
    ("G-AUTO", "make the auto tag removable everywhere", sub(AUTO_ONLY, "removable on every screen")),
    ("G-AUTO", "drop the joint ruling from C-9", set_cell("C-9", 2, "WD-8 holds")),
    ("G-OWNER", "let Manage tags hide the owner-only writes", sub(OWNER_LINE, "it edits tags")),
    ("G-OWNER", "drop the Viewer's gate on Manage tags", set_cell("S95-17", 3, "enabled")),
    ("G-GROUP", "show an ungranted leg's account label and net P&L", set_cell("S94-10", 3, "`group.out_of_scope` on each ungranted leg, with its account label and net P&L; `group.total_partial` over the granted legs, labelled partial (BQ-11)")),
    ("G-GROUP", "read the full group total in the partial case", sub(GROUP_PARTIAL, "with any leg out of scope it reads `group.total`")),
    ("G-GROUP", "let the client sum the legs", sub(GROUP_SERVER, "**The client sums the legs**")),
    ("G-COHORT", "add setup and side back to the cohort set", sub("symbol and tag; the environment", "symbol, tag, setup and side; the environment")),
    ("G-OWNER", "count every trade in the Tag breakdown", sub(TAG_SCOPE, "a tag's count covers every trade")),
)  # fmt: skip


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
    covered = {g for g, _, _ in MUTATIONS}
    missing = [g for g in GATES if g not in covered]
    ok &= not missing
    restored = load().spec == before
    ok &= restored
    out.append(f"self-test: {len(MUTATIONS)} mutations over {len(covered)} of {len(GATES)} gates")
    out.append(f"self-test: text restored: {'yes' if restored else 'NO'}")
    out.append(f"self-test: {'PASS' if ok else 'FAIL'}")
    return ok, out


def main(argv: list[str]) -> int:
    ap = argparse.ArgumentParser(description="E41-D03 journal post-mortem and analytics audit")
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
        print(f"filled §7 in {SPEC_REL}")
        return 0
    if a.repin_ruled:
        hashes, bad = cite_hashes(t)
        if bad:
            print(f"refused: {bad[0]}")
            return 1
        head = "# E41-D03 cite pins: the cite, a hash of its cited line(s) at its base. Written by --repin-ruled only.\n"
        body = "".join(f"{k}\t{h}\n" for k, h in hashes.items())
        (ROOT / PINS_REL).write_text(head + body, encoding="utf-8")
        print(f"wrote {PINS_REL} ({len(hashes)} cites)")
        return 0
    found = audit(t)
    for gate, msg in found:
        print(f"FAIL {gate}: {msg}")
    print(f"{len(found)} FAIL ({len(GATES)} gates)")
    return 1 if found else 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
