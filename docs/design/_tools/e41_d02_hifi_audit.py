#!/usr/bin/env python3
"""E41-D02 (#1018) audit: the hi-fi spec of the journal list (SCR-093) and the tag manager
(SCR-096).

Standalone and offline, shaped on the merged E10-D03 and E38-D03 tools: it imports
`packages/ui/tokens/tests/verify_tokens.py` (the token loader and resolver),
`docs/design/_tools/contrast_check.py` (`contrast_ratio`) and
`docs/research/_tools/cvd_simulate.py` (`simulate`, `delta_e76`; JND 5.0) from the working tree
and never re-implements them. It reads the spec and the pins file from the working tree and every
cited file AS TEXT with `git show` at the pinned base (`BASE`). The request-row keys (`P01`,
`S02`, `S09`) are read at #5567's merge commit (`REQ_REF`), else at `origin/main` by the same
path; the pins hash content, so the cites hold wherever they are read. Default-deny: a gate that cannot read its input FAILs.

Gates (each FAIL led by its name):
  G-STATE     every `14` checklist item for SCR-093 and SCR-096, read at the base, stands verbatim
              on a §0 CL row whose frames §0 lists; AC-2 … AC-4 map to listed frames; the required
              frames exist; every S93- / S96- state names a §0 frame or an inset that §0 names; each
              screen has a default, empty, loading, error, filtered, long-text and keyboard-focus
              state.
  G-TOKEN     every design token the spec names is in a merged set, and no raw colour value
              (a `#rgb` or `#rrggbb` literal) appears.
  G-CONTRAST  every §8.1 row recomputed per theme (dark, light, high-contrast) equals the spec to
              two decimals, meets its floor (`text` 4.5:1, `ui` 3:1) and its verdict matches.
  G-CVD       every §8.2 row's normal / protanopia / deuteranopia / tritanopia ΔE76 equals the
              spec, and its JND column names the simulations under 5.0.
  G-PICKER    AC-4: every §8.3 swatch row is recomputed — the label (`color.text.secondary` on
              the chip fill `color.neutral.subtle`) at least 4.5:1 and the swatch at least 3:1 in
              every theme — its word is in K-40 and names its token's role, never a hue (BQ-11:
              two status tokens resolve to one amber in dark), and §3.5's quoted label figures
              equal the tool's.
  G-ENV       AC-2: S93-02 renders separated, individually totalled groups with no combined total;
              §2.2 states it and keeps the group heading out of the virtualised body; any other
              mention of a combined total, a sum, a grand total, or a total across both or all
              environments is a negation.
  G-SERVER    AC-3: the merge confirm states the exact count (5,000 trades), its counts add up
              (gain + already-carrying = the source's count), the client sends one request, and
              S96-07 reads server-side, with progress, never a client-side loop.
  G-T2        every T- row and every state whose Presentation is T2 carries a quoted reason that
              is an E09-D09 key's text at the base (its `{slot}` filled) unless PROPOSED, and names
              its rendering (G-T2.1c); every "Your role can't {verb}." names a §3.2 verb of E09-D09
              at the base, bound to the T- row's gated permission; every T- row on a menu item is
              arrow-reachable; §1 item 4 names the CMP-019 `lock` and quotes G-T2.1b, G-T2.2,
              G-T2.3 and G-T2.5 verbatim from `DS` at the base; §8.1 carries the tertiary-on-raised label
              pair; both component lists name CMP-079 and the CMP-019 `lock` (G-T2.6); §1 item 5
              carries the C-2.6 carve-out.
  G-COPY      every §9.1 K-row is either PROPOSED with its owner, or sourced: each quoted string
              stands on its cited line at the base; every `(K-nn)` the spec names is a K-row.
  G-AROW      A-1 … A-15 are all present; every Old text stands exactly once in its cited plan
              file at the base, on its cited line; a new `12` M-row id is free in `12` at the
              base, or is the placeholder `M-0nn` with PR 2 named to fill it.
  G-REQUEST   R6: the #5567 keys (`P01`, `S02`, `S09`) are cited only on request rows, the spec
              pins #5567's merge commit, and no line outside a request row cites a section of the
              unmerged E41-D03 (#1081) (its rulings are cited by BQ id instead).
  G-CITE      every cite in range and on a non-blank line at its base, and equal to the pins.
  G-HYGIENE   no closing keyword, local path, URL or host, agent name, double-brace slot or deny
              word in the spec; no deny word in this tool's text or the pins.
  G-SCOPE     the diff touches only the spec, this tool and the pins file.
  G-OWNER     the BQ-24 ruling: tag rename, merge and delete are owner-only (C-12.4). §1 item 6
              rules it and records that `22` has no rename, merge or delete operation yet (G-3);
              §3.1 keeps the Manager's three IconButtons T2 and renders no Usage column for a
              Manager until G-11; T-07 is the drawn default, `rbac.owner_only` in rendering 2b, never conditional;
              S96-20 is its own frame with CMP-079, the CMP-019 `lock` and "Not available"; G-11
              names the gap; no line lets a Manager rename, merge or delete a tag.
  G-AUTO      the joint BQ-07 / #1081 BQ-15 ruling: an auto tag has no remove control on SCR-093
              or SCR-096. §2.1's Tags, §2.5's Remove tag, the row menu and §4.2 say so, and C-2
              names SCR-094 as the one removal path.

Usage (from the repo root):
  python3 -I docs/design/_tools/e41_d02_hifi_audit.py --check
  python3 -I docs/design/_tools/e41_d02_hifi_audit.py --fill        (writes §8's figures)
  python3 -I docs/design/_tools/e41_d02_hifi_audit.py --self-test
  python3 -I docs/design/_tools/e41_d02_hifi_audit.py --repin-ruled (the pins' only writer)
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
SPEC_REL = "docs/design/E41/E41-D02.md"
TOOL_REL = "docs/design/_tools/e41_d02_hifi_audit.py"
PINS_REL = "docs/design/_tools/e41_d02_ruled_pins.txt"
OWN_PATHS = (SPEC_REL, TOOL_REL, PINS_REL)
BASE = "a7d659a5bee5d06a28950f324800f84dc3853e6f"  # origin/main when written; re-pinned by content
REQ_REF = "e2c6bfff7117c23ce0a1f753bd591c9d7f9857a3"  # #5567's merge commit (merged as is)
TOKENS = ROOT / "packages" / "ui" / "tokens"
CVD_PATH = ROOT / "docs" / "research" / "_tools" / "cvd_simulate.py"
CONTRAST_PATH = ROOT / "docs" / "design" / "_tools" / "contrast_check.py"
SHEETS = "docs/design/_tools/sheets/e41-d01/"
PATHS: dict[str, str] = {
    "04": "docs/plan/04-security-program.md",
    "05": "docs/plan/05-accessibility-standard.md",
    "11": "docs/plan/11-user-stories.md",
    "12": "docs/plan/12-sitemap.md",
    "13": "docs/plan/13-user-flows.md",
    "14": "docs/plan/14-screens-catalogue.md",
    "15": "docs/plan/15-component-catalogue.md",
    "21": "docs/plan/21-database-schema.md",
    "22": "docs/plan/22-api-openapi.yaml",
    "E09D09": "docs/design/E09/E09-D09.md",
    "E42D02": "docs/design/E42/E42-D02.md",
    "E29D03": "docs/design/E29/E29-D03.md",
    "E05D03": "docs/design/E05/E05-D03.md",
    "E47D04": "docs/design/E47/E47-D04.md",
    "D01": "docs/design/research/e41-journal-review.md",
    "DS": ".claude/rules/32-design-specs.md",
    "P01": "docs/design/research/e41-journal-review.md",
    "S02": SHEETS + "02-scr093-default.md",
    "S09": SHEETS + "09-scr096-tag-manager.md",
}
REQUEST_KEYS = ("P01", "S02", "S09")
PLAN_FILES = ("12", "13", "14", "15")
CITE = re.compile(
    r"`(\d\d|E09D09|E42D02|E29D03|E05D03|E47D04|D01|DS|P01|S02|S09)`:(\d+(?:–\d+)?(?:, :\d+(?:–\d+)?)*)"
)
TOKEN_NAME = re.compile(
    r"`((?:color|font|border|radius|type|space|size|motion|opacity)\.[a-z0-9.-]*[a-z0-9])`"
)
RAW_COLOUR = re.compile(r"#(?:[0-9A-Fa-f]{6}|[0-9A-Fa-f]{3})(?![0-9A-Za-z])")
CLOSING = re.compile(r"\b(?:close[sd]?|fix(?:e[sd])?|resolve[sd]?)\s+#\d+", re.IGNORECASE)
LOCAL_PATH = re.compile(
    "/" + "home/|/Users/|/" + "tmp/|[A-Za-z]:\\\\|\\bwt-" + "notes\\b|\\bnotes/"
)  # assembled
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
    "SCR-093/default", "SCR-093/both-scopes", "SCR-093/filtered", "SCR-093/bulk-tag",
    "SCR-093/export-confirm", "SCR-093/focus", "SCR-093/long-text", "SCR-093/loading",
    "SCR-093/empty-first-run", "SCR-093/empty-range", "SCR-093/no-match", "SCR-093/error",
    "SCR-093/partial", "SCR-093/reconciling", "SCR-093/recomputing", "SCR-093/viewer-t2",
    "SCR-093/view-as", "SCR-096/default", "SCR-096/empty", "SCR-096/loading", "SCR-096/create",
    "SCR-096/rename", "SCR-096/merge-confirm", "SCR-096/merge-running", "SCR-096/delete-confirm",
    "SCR-096/error", "SCR-096/view-as", "SCR-096/long-text", "SCR-096/focus",
    "SCR-096/colour-picker", "SCR-096/colour-picker-light", "CMP-166/variants",
    "CMP-169/variants",
    "SCR-096/rename-running", "SCR-096/delete-running", "SCR-096/merge-background",
    "redlines/table-and-filterbar", "SCR-096/manager-t2", "SCR-093/divergent",
)  # fmt: skip
CHECKLISTS = ((2183, "CL-01", 6), (2230, "CL-07", 5))  # `14` line, first CL id, item count
ACS = ("AC-2", "AC-3", "AC-4")
ROLE_WORDS = {"neutral": "Neutral", "info": "Info", "success": "Success", "warning": "Warning",
              "danger": "Danger"}  # fmt: skip
OWNER_RULED = "Tag rename, merge and delete are owner-only (BQ-24, ruled; C-12.4)"
OWNER_GAP = "`22` has no rename, merge or delete operation on a tag today, only list and create"
OWNER_MANAGER = "for a Manager the three are T2 (T-07, S96-20) and Create tag stays enabled"
OWNER_USAGE = "for a Manager the Usage column is not rendered until G-11 serves a count in scope"
UNMERGED = re.compile(r"(?:E41-D03|#1081) §\d")
OWNER_REASON = '`rbac.owner_only` "Only the owner can change shared tags."'
MANAGER_CAN = re.compile(
    r"\b(?:a )?Manager (?:can|may) (?:[a-z, ]*? )?(?:rename|merge|delete)", re.IGNORECASE
)
AUTO_RULED = "the one removal path is SCR-094's (BQ-07, ruled jointly with #1081 BQ-15)"
AUTO_NONE = "no remove control"
REQUIRED_STATES = (
    "default", "empty", "loading", "error", "filtered", "long text", "keyboard focus",
)  # fmt: skip
FRAME = re.compile(r"`((?:SCR-\d{3}|CMP-\d{3}|[a-z-]+)/[a-z0-9-]+)`")
RENDERING = re.compile(r"rendering (2a|2b|the sentence form)")
LABEL_PAIR = ("color.text.secondary", "color.neutral.subtle")
ENV_SENTENCE = (
    "**two separated groups, one per environment, each individually totalled; no combined"
    " total is rendered across the two.**"
)
SUMMED = re.compile(
    r"\b(?:sum|sums|summed|summing|grand total|across both|across all environments"
    r"|all environments)\b"
)
NO_STICKY = "so it is never a sticky sub-header inside a virtualised body"
CARVE_OUT = (
    "Cancel, close, flatten and setting or tightening a stop live on the trading surfaces and"
    " are never gated by anything here."
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
        r = subprocess.run(["git", "-C", str(ROOT), *args], capture_output=True, check=False)
    except OSError:
        return None
    return r.stdout.decode("utf-8", "surrogateescape") if r.returncode == 0 else None


def show(t: Texts, rev: str, rel: str) -> str | None:
    key = f"{rev}:{rel}"
    if key not in t.memo:
        t.memo[key] = git("show", key)
    return t.memo[key]


def at(t: Texts, key: str) -> str:
    refs = (REQ_REF, "origin/main") if key in REQUEST_KEYS else (BASE,)
    for ref in refs:
        text = show(t, ref, PATHS[key])
        if text is not None:
            return text
    raise LookupError(f"{PATHS[key]} does not resolve at {refs[0][:10]}; fetch first")


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
    depth = head.split(" ")[0]
    j = text.find("\n" + depth + " ", i + 1)
    return text[i : j if j > 0 else len(text)]


def row(t: Texts, lead: str) -> list[str]:
    rows = table_rows(t.spec, lead + " ")
    if len(rows) != 1:
        raise LookupError(f"the spec carries {len(rows)} `{lead}` rows, not 1")
    return rows[0]


# ---------------------------------------------------------------------------- tokens


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


def ratios(fg: str, bg: str) -> list[str]:
    cc = mod("contrast_check")
    return [
        f"{cc.contrast_ratio(hex_rgb(color(th, fg)), hex_rgb(color(th, bg))):.2f}" for th in THEMES
    ]


def verdict(role: str, values: list[str]) -> str:
    floor = FLOOR.get(role)
    if floor is None:
        return "structure"
    return "pass" if min(map(float, values)) >= floor else "FAIL"


def cvd_values(row_: list[str]) -> tuple[str, str]:
    cv = mod("cvd_simulate")
    th = {"hc": "high-contrast"}.get(row_[3], row_[3])
    ha, hb = color(th, tok(row_[1])), color(th, tok(row_[2]))
    ds = [cv.delta_e76(ha, hb)] + [
        cv.delta_e76(cv.simulate(ha, d), cv.simulate(hb, d)) for d in DEFICIENCIES
    ]
    under = [n for n, d in zip(("normal", *DEFICIENCIES), ds, strict=True) if d < cv.JND_FLOOR]
    return " / ".join(f"{d:.2f}" for d in ds), (", ".join(under) if under else "none")


def picker_values(row_: list[str]) -> tuple[str, str, str]:
    label = ratios(*LABEL_PAIR)
    swatch = ratios(tok(row_[2]), LABEL_PAIR[1])
    ok = min(map(float, label)) >= FLOOR["text"] and min(map(float, swatch)) >= FLOOR["ui"]
    return " / ".join(label), " / ".join(swatch), "pass" if ok else "FAIL"


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


def frames_of(t: Texts) -> set[str]:
    zero = section(t.spec, "## 0.")
    return {r[1].strip("`") for r in table_rows(zero, "B") if len(r) > 1}


def g_state(t: Texts) -> list[str]:
    bad = []
    zero = section(t.spec, "## 0.")
    frames = frames_of(t)
    bad += [f"no §0 frame row for `{f}`" for f in REQUIRED_FRAMES if f not in frames]
    cl = {r[0]: r for r in table_rows(zero, "CL-") if len(r) > 2}
    lines14 = at(t, "14").split("\n")
    for line, first, count in CHECKLISTS:
        items = [norm(x) for x in lines14[line - 1].split("[ ]")[1:]]
        if len(items) != count:
            bad.append(f"`14`:{line} holds {len(items)} checklist items, not {count}")
        start = int(first[3:])
        for k, item in enumerate(items):
            cid = f"CL-{start + k:02d}"
            r = cl.get(cid)
            if r is None or norm(r[1]) != item:
                bad.append(f"{cid}: not `14`:{line}'s item {item[:40]!r} verbatim")
                continue
            fs = FRAME.findall(r[2])
            if not fs or any(f not in frames for f in fs):
                bad.append(f"{cid}: maps to no frame, or to one §0 does not list")
    acs = {r[0]: FRAME.findall(r[2]) for r in table_rows(zero, "AC-") if len(r) > 2}
    for ac in ACS:
        if not acs.get(ac) or any(f not in frames for f in acs[ac]):
            bad.append(f"{ac} maps to no frame, or to one §0 does not list")
    insets = section(t.spec, "## 0.")
    for lead, head in (("S93-", "### 2.7"), ("S96-", "### 3.6")):
        rows = table_rows(section(t.spec, head), lead)
        names = " | ".join(r[1] for r in rows if len(r) > 1)
        for need in REQUIRED_STATES:
            if need not in names:
                bad.append(f"{lead[:3]}: no {need!r} state in {head}")
        for r in rows:
            if len(r) < 5:
                bad.append(f"{r[0]}: {len(r)} cells, not 5")
                continue
            fs = FRAME.findall(r[4])
            if r[4] == "inset":
                if f"{r[0]} (" not in insets:
                    bad.append(f"{r[0]}: an inset §0 does not name")
            elif not fs or any(f not in frames for f in fs):
                bad.append(f"{r[0]}: its frame is not a §0 frame")
    return bad


def g_token(t: Texts) -> list[str]:
    known = known_tokens()
    bad = [
        f"`{n}` does not resolve in the token JSON at the base"
        for n in sorted(set(TOKEN_NAME.findall(t.spec)))
        if n not in known
    ]
    for i, ln in enumerate(t.spec.split("\n"), 1):
        if RAW_COLOUR.search(ln):
            bad.append(f"spec:{i} carries a raw colour value")
    return bad


def g_contrast(t: Texts) -> list[str]:
    bad = []
    rows = table_rows(section(t.spec, "### 8.1"), "P-")
    if not rows:
        return ["§8.1 has no contrast rows"]
    for r in rows:
        if len(r) != 8:
            bad.append(f"{r[0]}: {len(r)} cells, not 8")
            continue
        want = ratios(tok(r[1]), tok(r[2]))
        if r[4:7] != want:
            bad.append(f"{r[0]}: reads {r[4:7]}, the tokens give {want}")
        floor = FLOOR.get(r[3])
        if floor is not None and min(float(x) for x in want) < floor:
            bad.append(f"{r[0]}: below {floor}:1 for a `{r[3]}` pair")
        if r[7] != verdict(r[3], want):
            bad.append(f"{r[0]}: verdict reads {r[7]!r}, not {verdict(r[3], want)!r}")
    return bad


def g_cvd(t: Texts) -> list[str]:
    bad = []
    rows = table_rows(section(t.spec, "### 8.2"), "V-")
    if not rows:
        return ["§8.2 has no CVD rows"]
    for r in rows:
        if len(r) != 6:
            bad.append(f"{r[0]}: {len(r)} cells, not 6")
            continue
        ds, under = cvd_values(r)
        if r[4] != ds or r[5] != under:
            bad.append(f"{r[0]}: reads {r[4]} / {r[5]}, the tool gives {ds} / {under}")
    return bad


def g_picker(t: Texts) -> list[str]:
    bad = []
    rows = table_rows(section(t.spec, "### 8.3"), "W-")
    if len(rows) < 2:
        return ["§8.3 lists fewer than two picker swatches"]
    words = row(t, "K-40")[2]
    label = " / ".join(ratios(*LABEL_PAIR))
    for r in rows:
        if len(r) != 6:
            bad.append(f"{r[0]}: {len(r)} cells, not 6")
            continue
        want = picker_values(r)
        if (r[3], r[4], r[5]) != want:
            bad.append(f"{r[0]}: reads {r[3:6]}, the tokens give {list(want)}")
        if want[2] != "pass":
            bad.append(f"{r[0]}: the swatch or its label fails its floor (AC-4)")
        if f'"{r[1]}"' not in words:
            bad.append(f"{r[0]}: its word {r[1]!r} is not in K-40")
        parts = tok(r[2]).split(".")
        role = parts[2] if parts[1] == "status" else parts[1]
        if r[1] != ROLE_WORDS.get(role):
            bad.append(f"{r[0]}: the word {r[1]!r} does not name its token's role ({role}, BQ-11)")
    if f"(§8.3: {label})" not in section(t.spec, "### 3.5"):
        bad.append(f"§3.5 does not quote the label figures the tool gives ({label})")
    return bad


def g_env(t: Texts) -> list[str]:
    bad = []
    if "no combined total" not in row(t, "S93-02")[3]:
        bad.append("S93-02: the both-scopes frame does not rule out a combined total")
    if "individually totalled" not in row(t, "S93-02")[3]:
        bad.append("S93-02: the groups are not individually totalled")
    two = section(t.spec, "### 2.2")
    if ENV_SENTENCE not in two:
        bad.append("§2.2 does not state the separated, individually totalled groups")
    if NO_STICKY not in two:
        bad.append("§2.2 does not keep the group heading out of the virtualised body")
    for i, ln in enumerate(t.spec.split("\n"), 1):
        low = ln.lower()
        for m in re.finditer("combined total", low):
            lead = low[max(0, m.start() - 12) : m.start()]
            if "no " not in lead and "never a " not in lead:
                bad.append(f"spec:{i} renders a combined total (AC-2)")
        for m in SUMMED.finditer(low):
            lead = low[max(0, m.start() - 16) : m.start()]
            if not any(neg in lead for neg in ("no ", "never ", "not ")):
                bad.append(f"spec:{i} sums the groups: {m[0]!r} outside a negation (AC-2)")
    return bad


def num(s: str) -> int:
    return int(s.replace(",", ""))


def g_server(t: Texts) -> list[str]:
    bad = []
    three = section(t.spec, "### 3.3")
    m = re.search(
        r"\"([\d,]+) trades lose '[^']+'\. ([\d,]+) of them gain '[^']+'; ([\d,]+) already",
        three,
    )
    if not m:
        bad.append("§3.3: the merge counts line is missing")
    elif num(m[2]) + num(m[3]) != num(m[1]):
        bad.append("§3.3: the merge counts do not add up (gain + already carrying)")
    if "5,000 trades" not in row(t, "S96-06")[2] or not m or m[1] != "5,000":
        bad.append("S96-06: the confirm does not state the exact count, 5,000 trades (AC-3)")
    if "the client sends one request" not in three:
        bad.append("§3.3: the client does not send one request")
    pres = row(t, "S96-07")[3]
    if "server-side, with progress" not in pres or "never a client-side loop" not in pres:
        bad.append("S96-07: the merge is not server-side with progress, never a client loop")
    return bad


def e09_templates(t: Texts) -> list[re.Pattern[str]]:
    out = []
    for ln in at(t, "E09D09").split("\n"):
        if ln.startswith("| `"):
            for q in re.findall(r'"([^"]{8,})"', ln):
                parts = re.split(r"\{[^}]+\}", q)  # a slot may be a phrase
                if len("".join(parts).strip()) < 8:
                    continue  # a bare slot ("{account id}") is no key text
                out.append(re.compile(".+?".join(re.escape(x) for x in parts) + "$"))
    return out


# G-T2.1b, G-T2.2 and G-T2.3 as `DS` words them (its `**` emphasis dropped); §1 item 4 quotes each
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
        "G-T2.3",
        (
            "`Enter`, `Space` or a bound hotkey on a T2 control changes nothing and re-shows"
            " the reason inline with one polite announcement; arrow keys land on a disabled menu"
            " item without activating it"
        ),
    ),
    (
        "G-T2.5",
        (
            "a panel that is read-only for the session carries one panel-header notice; every"
            " gated control's `aria-describedby` points at that node"
        ),
    ),
)
ROLE_VERB = re.compile(r"[Yy]our role can't ([^.\"]+)\.")
PERM = re.compile(r"`([a-z_]+:[a-z_]+)`")


def e09_verbs(t: Texts) -> dict[str, str]:
    """E09-D09 §3.2's verb table at the base: each verb to the permission it names."""
    out: dict[str, str] = {}
    for ln in at(t, "E09D09").split("\n"):
        for perm, verb in re.findall(r'`([a-z_]+:[a-z_]+)` → "([^"]+)"', ln):
            out[verb] = perm
    return out


def g_t2(t: Texts) -> list[str]:
    bad = []
    keys = e09_templates(t)
    gated = [(r[0], r[3]) for lead in ("S93-", "S96-") for r in table_rows(t.spec, lead)
             if len(r) > 3 and "T2" in r[3]]  # fmt: skip
    trows = [r for r in table_rows(t.spec, "T-") if len(r) > 4]
    gated += [(r[0], r[4]) for r in trows]
    if not gated:
        return ["the spec has no T2 control"]
    verbs = e09_verbs(t)
    gate_perm = {r[0]: PERM.findall(r[3]) for r in trows}
    for rid, pres in gated:
        for verb in ROLE_VERB.findall(pres):
            perm = verbs.get(verb)
            if perm is None:
                bad.append(f"{rid}: {verb!r} is not a §3.2 verb of E09-D09 at the base")
            elif gate_perm.get(rid) and perm not in gate_perm[rid]:
                bad.append(f"{rid}: {verb!r} is §3.2's verb for `{perm}`, not the row's gate")
        if not RENDERING.search(pres):
            bad.append(f"{rid}: a T2 control with no rendering (2a, 2b or the sentence form)")
        quote = re.search(r'"([^"]{8,})"', pres)
        if not quote:
            bad.append(f"{rid}: a T2 presentation with no quoted reason")
        elif "PROPOSED" not in pres and not any(k.match(quote[1]) for k in keys):
            bad.append(f"{rid}: {quote[1]!r} is no E09-D09 key's text and is not PROPOSED")
    for r in trows:
        if "menu" in r[1] and ("arrow-reachable" not in r[4] or "skipped" in r[4]):
            bad.append(f"{r[0]}: a T2 menu item that is not arrow-reachable (G-T2.1b, G-T2.3)")
    one = section(t.spec, "## 1.")
    if "CMP-019 `lock`" not in one:
        bad.append("§1 item 4 does not state the CMP-019 `lock` glyph that leads a T2 label")
    owner = norm(at(t, "DS").replace("**", ""))
    item4 = norm(one)
    for gid, q in T2_QUOTES:
        if norm(q) not in owner:
            bad.append(f"{gid}: the quote is no longer `DS`'s text at the base")
        elif f"{gid}, verbatim" not in item4 or norm(q) not in item4:
            bad.append(f"§1 item 4 does not quote {gid} verbatim from `DS`")
    pairs = {(r[1], r[2]) for r in table_rows(section(t.spec, "### 8.1"), "P-") if len(r) > 2}
    if ("`color.text.tertiary`", "`color.surface.raised`") not in pairs:
        bad.append("§8.1 has no `color.text.tertiary` on `color.surface.raised` pair (G-T2.2)")
    for head in ("## 2.", "## 3."):
        comp = re.search(r"\*\*Components:\*\*([^\n]+)", section(t.spec, head))
        if not comp or "CMP-079" not in comp[1] or "CMP-019 `lock`" not in comp[1]:
            bad.append(f"{head} the component list lacks CMP-079 or the CMP-019 `lock` (G-T2.6)")
    if CARVE_OUT not in one:
        bad.append("§1 item 5 does not carry the C-2.6 carve-out")
    return bad


def g_copy(t: Texts) -> list[str]:
    bad = []
    deck = table_rows(section(t.spec, "### 9.1"), "K-")
    ids = {r[0] for r in deck}
    for r in deck:
        if len(r) != 4:
            bad.append(f"{r[0]}: {len(r)} cells, not 4")
            continue
        strings = re.findall(r'"([^"]+)"', r[2])
        if not strings:
            bad.append(f"{r[0]}: no quoted string")
        if r[3].startswith("PROPOSED"):
            if not re.match(r"PROPOSED \(E\d\d-[A-Z]\d\d", r[3]):
                bad.append(f"{r[0]}: PROPOSED names no owner")
            continue
        found = cites(r[3])
        if not found:
            bad.append(f"{r[0]}: neither sourced by a cite nor PROPOSED with an owner")
            continue
        key, a, _ = found[0]
        line = norm(at(t, key).split("\n")[a - 1]) if a else ""
        for s in strings:
            if norm(s) not in line:
                bad.append(f"{r[0]}: {s[:40]!r} is not on {key}:{a} at its base")
    for k in sorted(set(re.findall(r"\b(K-\d\d)\b", t.spec)) - ids):
        bad.append(f"the spec names {k}, which §9.1 lacks")
    return bad


def g_arow(t: Texts) -> list[str]:
    bad = []
    lines = [ln for ln in section(t.spec, "### 9.4").split("\n") if ln.startswith("- **A-")]
    got = [m[1] for ln in lines if (m := re.match(r"- \*\*(A-\d+),", ln))]
    if got != [f"A-{i}" for i in range(1, 16)]:
        bad.append(f"the A-rows are {got}, not A-1 … A-15")
    for ln in lines:
        aid = ln.split(",")[0][4:]
        olds = re.findall(r'Old: "(.+?)"\. New:', ln)
        if not olds:
            bad.append(f"{aid}: no Old text")
            continue
        plan = [(k, a) for k, a, _ in cites(ln) if k in PLAN_FILES]
        if not plan:
            bad.append(f"{aid}: names no plan-file line at the base")
            continue
        key, a = plan[0]
        for mid in re.findall(r"\| M-(\w+) \|", ln.split("New:", 1)[-1]):
            if mid == "0nn":
                if "PR 2 fills the id from `12`'s next free M-row" not in ln:
                    bad.append(f"{aid}: the placeholder M-0nn names no filler")
            elif f"| M-{mid} |" in at(t, "12"):
                bad.append(f"{aid}: M-{mid} is already a row of `12` at the base")
        text = at(t, key)
        ls = text.split("\n")
        for o in olds:
            if text.count(o) != 1:
                bad.append(f"{aid}: {o[:40]!r} stands {text.count(o)} times in `{key}`")
            elif not 0 < a <= len(ls) or o not in ls[a - 1]:
                bad.append(f"{aid}: {o[:40]!r} is not on `{key}`:{a}")
    return bad


def g_request(t: Texts) -> list[str]:
    bad = []
    for i, ln in enumerate(t.spec.split("\n"), 1):
        keys = {k for k, _, _ in cites(ln)}
        if keys & set(REQUEST_KEYS) and not ln.startswith("| R-"):
            bad.append(f"spec:{i} cites a #5567 key outside a request row")
        if UNMERGED.search(ln) and not ln.startswith("| R-"):
            bad.append(f"spec:{i} cites a section of the unmerged E41-D03 outside a request row")
    if f"`{REQ_REF[:9]}`" not in t.spec:
        bad.append("the spec does not pin #5567's merge commit")
    return bad


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
    checks = ((CLOSING, "a closing keyword (PR 2 alone closes #1018)"), (LOCAL_PATH, "a local path"),
              (AGENT_NAME, "an agent name"), (URL_OR_HOST, "a URL or a host"))  # fmt: skip
    for i, ln in enumerate(t.spec.split("\n"), 1):
        for rx, what in checks:
            if rx.search(ln):
                bad.append(f"spec:{i} carries {what}")
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


def g_owner(t: Texts) -> list[str]:
    bad = []
    one = section(t.spec, "## 1.")
    if OWNER_RULED not in one:
        bad.append("§1 item 6 does not rule tag rename, merge and delete owner-only (BQ-24)")
    if OWNER_GAP not in one:
        bad.append("§1 item 6 does not record that `22` has no rename, merge or delete (G-3)")
    s31 = section(t.spec, "### 3.1")
    if OWNER_MANAGER not in s31:
        bad.append("§3.1: a Manager's Rename, Merge into… and Delete are not T2 (T-07, S96-20)")
    if OWNER_USAGE not in s31:
        bad.append("§3.1: a Manager's Usage column is rendered before G-11 serves a scoped count")
    r = row(t, "T-07")
    if "owner-only" not in r[3] or "conditional" in r[3] + r[4]:
        bad.append("T-07: the owner-only tag gate is not the drawn default")
    if OWNER_REASON not in r[4] or "rendering 2b" not in r[4]:
        bad.append("T-07: not `rbac.owner_only` in rendering 2b on the IconButtons")
    s96 = row(t, "S96-20")
    if s96[4] != "`SCR-096/manager-t2`":
        bad.append("S96-20: the Manager's gate is not its own frame, `SCR-096/manager-t2`")
    for need in ("T2 `rbac.owner_only`", "CMP-079", "CMP-019 `lock`", '"Not available"'):
        if need not in s96[3]:
            bad.append(f"S96-20: the Manager's gate does not name {need}")
    g11 = row(t, "G-11")[1]
    if "owner-only" not in g11 or "`journal:write`" not in g11:
        bad.append("G-11 does not name the owner-only gap over `journal:write`")
    for i, ln in enumerate(t.spec.split("\n"), 1):
        m = MANAGER_CAN.search(ln)
        lead = ln[max(0, m.start() - 24) : m.start()] if m else ""
        if m and not re.search(r"\b(?:no|not|never|cannot)\b", lead):
            bad.append(f"spec:{i} lets a Manager rename, merge or delete a tag (BQ-24)")
    return bad


def g_auto(t: Texts) -> list[str]:
    bad = []
    if AUTO_RULED not in row(t, "C-2")[2]:
        bad.append("C-2 does not name SCR-094 as the one removal path (BQ-07)")
    s21 = section(t.spec, "### 2.1")
    tags = next((ln for ln in s21.split("\n") if ln.startswith("- **Tags**")), "")
    menu = next((ln for ln in s21.split("\n") if ln.startswith("- **Row menu**")), "")
    if AUTO_NONE not in tags:
        bad.append("§2.1: an auto chip on SCR-093 is not drawn with no remove control")
    if "manual tags only" not in menu:
        bad.append("§2.1: the row menu's Remove tag… offers auto tags")
    if "manual tags only" not in section(t.spec, "### 2.5"):
        bad.append("§2.5: the bulk Remove tag offers auto tags")
    if AUTO_NONE not in section(t.spec, "### 4.2"):
        bad.append("§4.2: CMP-169's auto chip carries a remove control on SCR-093 or SCR-096")
    return bad


GATES: dict[str, Callable[[Texts], list[str]]] = {
    "G-STATE": g_state, "G-TOKEN": g_token, "G-CONTRAST": g_contrast, "G-CVD": g_cvd,
    "G-PICKER": g_picker, "G-ENV": g_env, "G-SERVER": g_server, "G-T2": g_t2, "G-COPY": g_copy,
    "G-AROW": g_arow, "G-REQUEST": g_request, "G-CITE": g_cite, "G-HYGIENE": g_hygiene,
    "G-SCOPE": g_scope, "G-OWNER": g_owner, "G-AUTO": g_auto,
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
    pins_path = ROOT / PINS_REL
    pins = pins_path.read_text(encoding="utf-8") if pins_path.exists() else ""
    tool = (ROOT / TOOL_REL).read_text(encoding="utf-8")
    return Texts(spec, pins, tool, changed_paths(), {})


def fill(t: Texts) -> str:
    out = []
    for ln in t.spec.split("\n"):
        c = cells(ln)
        if ln.startswith("| P-") and len(c) == 8:
            v = ratios(tok(c[1]), tok(c[2]))
            c[4:8] = [*v, verdict(c[3], v)]
            ln = "| " + " | ".join(c) + " |"
        elif ln.startswith("| V-") and len(c) == 6:
            c[4], c[5] = cvd_values(c)
            ln = "| " + " | ".join(c) + " |"
        elif ln.startswith("| W-") and len(c) == 6:
            c[3], c[4], c[5] = picker_values(c)
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


def chain(*fns: Callable[[Texts], Texts]) -> Callable[[Texts], Texts]:
    def f(t: Texts) -> Texts:
        for fn in fns:
            t = fn(t)
        return t

    return f


def drop_row(lead: str) -> Callable[[Texts], Texts]:
    def f(t: Texts) -> Texts:
        return replace(
            t, spec="\n".join(ln for ln in t.spec.split("\n") if not ln.startswith(lead))
        )

    return f


MUTATIONS: tuple[tuple[str, str, Callable[[Texts], Texts]], ...] = (
    ("G-STATE", "drop the merge-confirm frame row", drop_row("| B23 ")),
    ("G-STATE", "retype a `14` checklist item", set_cell("CL-09", 1, "delete confirmation names the tag")),
    ("G-STATE", "drop SCR-096's keyboard-focus state", set_cell("S96-17", 1, "focus ring")),
    ("G-STATE", "point a state at an unlisted frame", set_cell("S93-14", 4, "`SCR-093/fills-arriving`")),
    ("G-TOKEN", "misspell a token", sub("`color.surface.canvas` / `color.surface.raised`", "`color.surface.canvass` / `color.surface.raised`")),
    ("G-TOKEN", "write a raw colour value", sub("an 8 px square (`radius.xs`)", "an 8 px square (`radius.xs`, #5B8DEF)")),
    ("G-CONTRAST", "type a contrast figure off", set_cell("P-01", 4, "1.00")),
    ("G-CONTRAST", "report a ui pair as structure", set_cell("P-08", 3, "structure")),
    ("G-CVD", "type a ΔE figure off", set_cell("V-01", 4, "1.00 / 1.00 / 1.00 / 1.00")),
    ("G-PICKER", "type a label figure off", set_cell("W-02", 3, "1.00 / 1.00 / 1.00")),
    ("G-PICKER", "offer a swatch that fails 3:1", set_cell("W-03", 2, "`color.border.strong`")),
    ("G-PICKER", "misquote the label figures in §3.5", sub("(§8.3: ", "(§8.3: 9.99 / ")),
    ("G-ENV", "render a combined total", sub("no combined total anywhere", "a combined total under both groups")),
    ("G-ENV", "let the group heading sit in the virtualised body", sub(NO_STICKY, "inside the body")),
    ("G-ENV", "add a grand total summing both groups", sub("no combined total anywhere", "no combined total anywhere; then a grand total row summing both groups")),
    ("G-SERVER", "make the merge counts not add up", sub("3,760 of them gain", "3,700 of them gain")),
    ("G-SERVER", "run the merge as a client loop", set_cell("S96-07", 3, "the client tags each trade in turn")),
    ("G-T2", "drop a reason", set_cell("T-02", 4, "T2; rendering 2a")),
    ("G-T2", "retype a key's text", set_cell("T-04", 4, 'T2 "Read only while viewing someone."; rendering 2a')),
    ("G-T2", "drop a control's rendering", set_cell("T-06", 4, 'T2 `rbac.view_as` "Read-only while viewing as alex."')),
    ("G-T2", "drop the lock from §1 item 4", sub("led by the CMP-019 `lock` glyph", "led by its glyph")),
    ("G-T2", "let a T2 control leave the Tab order (G-T2.1b)", sub("never the `disabled` attribute — it stays in the Tab order", "or the `disabled` attribute")),
    ("G-T2", "dim a T2 label (G-T2.2)", sub("never `color.text.disabled`, never `opacity.disabled` on", "dimmed with `opacity.disabled` on")),
    ("G-T2", "make a T2 press act (G-T2.3)", sub("changes nothing and re-shows the reason inline with one polite announcement", "acts")),
    ("G-T2", "drop the tertiary label pair", drop_row("| P-04 ")),
    ("G-T2", "give a gate the wrong §3.2 verb", set_cell("T-01", 4, 'T2 `rbac.permission` "Your role can\'t change settings." (K-11); rendering 2a through the notice')),
    ("G-T2", "skip T2 menu items with the arrow keys", sub("each item points at the one header notice, arrow-reachable", "each item points at the one header notice, skipped by the arrow keys")),
    ("G-T2", "drop the one-notice rule (G-T2.5)", sub("carries one panel-header notice", "carries a notice per control")),
    ("G-T2", "drop CMP-079 from SCR-096's components", sub("CMP-169 TagEditor, CMP-016 Tooltip, CMP-079 RbacGate", "CMP-169 TagEditor, CMP-016 Tooltip, RbacGate")),
    ("G-T2", "drop the C-2.6 carve-out", sub(CARVE_OUT, "Order controls are elsewhere.")),
    ("G-COPY", "retype a sourced string", set_cell("K-04", 2, '"No trades match the filters"')),
    ("G-COPY", "drop a PROPOSED string's owner", set_cell("K-20", 3, "PROPOSED")),
    ("G-COPY", "name a K-row the deck lacks", sub(", K-41; ≤ 24", ", K-99; ≤ 24")),
    ("G-AROW", "an Old text off by one character", sub('Old: "merging warns how many trades are affected."', 'Old: "merging warns how many trade are affected."')),
    ("G-AROW", "give the new M-row a taken id", sub("| M-0nn | Modal", "| M-025 | Modal")),
    ("G-AROW", "drop A-12", lambda t: replace(t, spec="\n".join(ln for ln in t.spec.split("\n") if not ln.startswith("- **A-12,")))),
    ("G-REQUEST", "cite #5567 outside a request row", sub("visible as T2 (`D01`:142).", "visible as T2 (`D01`:142, `P01`:79).")),
    ("G-CITE", "re-point a cite to an unpinned line", sub("(`E05D03`:67)", "(`E05D03`:68)")),
    ("G-HYGIENE", "write a closing keyword against #1018", sub("carries the closing line.", "carries the closing line. Closes #1018.")),
    ("G-HYGIENE", "put a deny word into the tool's text", lambda t: replace(t, tool=t.tool + "\n# " + DENY[6] + "\n")),
    ("G-SCOPE", "touch `14` in the diff", lambda t: replace(t, changed=[*OWN_PATHS, PATHS["14"]])),
    ("G-PICKER", "name a swatch by a hue (BQ-11)", chain(set_cell("W-05", 1, "Red"), sub('"Danger"', '"Red"'))),
    ("G-OWNER", "make the owner-only gate conditional again", set_cell("T-07", 3, "none today; conditional on G-11")),
    ("G-OWNER", "fold the Manager's gate into an inset", set_cell("S96-20", 4, "`SCR-096/default`")),
    ("G-OWNER", "drop the server-gap sentence", sub(OWNER_GAP, "the server agrees")),
    ("G-OWNER", "enable a Manager's three IconButtons in §3.1", sub("for a Manager the three are T2 (T-07, S96-20)", "for a Manager the three are enabled, as `22` allows (T-07, S96-20)")),
    ("G-OWNER", "render the Manager's Usage column as served", sub(OWNER_USAGE, "for a Manager the Usage column shows `usage_count` as served")),
    ("G-REQUEST", "cite an unmerged E41-D03 section in an A-row", sub("recorded; E41-D02 §4.2, #1081 BQ-15", "recorded; E41-D02 §4.2, E41-D03 §2.6")),
    ("G-OWNER", "let a Manager rename a tag", sub("Create stays open to a Manager", "A Manager can rename a tag; Create stays open to a Manager")),
    ("G-AUTO", "give SCR-093's auto chip a remove control", sub("the word \"auto\" and no remove control (BQ-07)", "the word \"auto\" and a remove control (BQ-07)")),
    ("G-AUTO", "drop SCR-094 as the one removal path", sub(AUTO_RULED, "auto tags are read-only")),
    ("G-AUTO", "let the bulk Remove tag offer auto tags", sub("**Remove tag** lists manual tags only", "**Remove tag** lists every tag")),
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
    out.append(f"self-test: gates with no mutation: {', '.join(missing) or 'none'}")
    out.append(
        f"self-test: {len(MUTATIONS)} mutations, text restored: {'yes' if restored else 'NO'}"
    )
    out.append(f"self-test: {'PASS' if ok else 'FAIL'}")
    return ok, out


def main(argv: list[str]) -> int:
    ap = argparse.ArgumentParser(description="E41-D02 journal list and tag manager audit")
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
        print(f"filled §8 in {SPEC_REL}")
        return 0
    if a.repin_ruled:
        hashes, bad = cite_hashes(t)
        if bad:
            print(f"refused: {bad[0]}")
            return 1
        head = (
            "# E41-D02 cite pins: the cite, a hash of its cited line(s) at its base."
            " Written by --repin-ruled only.\n"
        )
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
