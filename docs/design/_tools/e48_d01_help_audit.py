#!/usr/bin/env python3
"""E48-D01 (#1327) audit: the hi-fi spec of SCR-119 Help & about and the user-guide IA.

Standalone and offline, shaped on the E43-D01 and E41-D02 tools: it imports
`packages/ui/tokens/tests/verify_tokens.py` (the token loader and resolver) and
`docs/design/_tools/contrast_check.py` (`contrast_ratio`) from the working tree and never
re-implements them. It reads the spec and the pins file from the working tree, and every cited
file AS TEXT with `git show` at the pinned base (`BASE`); the pins hash content. Default-deny: a
gate that cannot read its input FAILs.

Gates (each FAIL led by its name):
  G-STATE     §0 lists every frame once; every state row (UC-, DG-, GL-) names a §0 frame; AC-1 …
              AC-5 map to §0 frames; the ticket's states exist (five update results, the browser
              build, offline, and the bundle's generating, generated, secret-detected and
              truncated); every frame is named by a state, an AC, a CL row or an inset.
  G-CHECKLIST every item of SCR-119's `14` checklist, read at the base, stands verbatim on a CL row.
  G-SECURITY  C-2.7 / C-12.6: §1 item 3 states the baseline (no secret on screen, in copied text or
              in a bundle; redaction always on and never a user option; local only); §5 and §7
              cite it; the secret-detected copy names no pattern; the local path is not rendered;
              no line offers to turn redaction off; no credential-shaped value anywhere.
  G-BUILD     every V-row's source is `BuildInfo`, the client bundle or a build constant; every
              `BuildInfo` field named is in the schema at the base; no host or path row.
  G-RBAC      BQ-03 (AMEND): the bundle control is T2 (never absent) for a Manager or Viewer,
              `rbac.owner_only` with rendering 2a, citing E09-D09's never-hide rule; a view-as
              session gets T2 `rbac.view_as`; no step-up is asked on SCR-119.
  G-BROWSER   AC-2: shell-only items are absent with K-09, never drawn disabled.
  G-SHORTCUT  AC-3: the command and context counts §8 states equal `keymap.json` at the base, and
              §8 draws no second cheatsheet (it links SCR-013).
  G-TOKEN     every design token the spec names resolves; no raw colour literal.
  G-CONTRAST  every §12 row recomputed per theme equals the spec, meets its floor, and its
              verdict matches.
  G-T2        §1 item 6 quotes G-T2.1b, G-T2.2 and G-T2.3 verbatim from `DS` at the base; every
              T2 row names its rendering; §14 lists CMP-079 and the CMP-019 `lock`.
  G-RULED     the BQ ruling of 2026-11-04: the tour opens SCR-018, never SCR-016 / SCR-017
              (BQ-10); every IA-01 … IA-09 row stands (BQ-10); DG-09 … DG-11 reuse E42-D05's
              refusals (BQ-05); the saved line names no file and no Show in folder (BQ-05).
  G-REQUEST   R6: #1220 appears only on an R-row, the pre-stage paragraph or a line naming R-1.
  G-CITE      every cite in range, on a non-blank line at its base, and equal to the pins.
  G-HYGIENE   no closing keyword, local path, URL or host, agent name, double-brace slot or
              deny word in the spec; no deny word in this tool's text or the pins.
  G-SCOPE     the diff touches only the spec, this tool and the pins file.

Usage (from the repo root):
  python3 -I docs/design/_tools/e48_d01_help_audit.py --check
  python3 -I docs/design/_tools/e48_d01_help_audit.py --fill        (writes §12's figures)
  python3 -I docs/design/_tools/e48_d01_help_audit.py --self-test
  python3 -I docs/design/_tools/e48_d01_help_audit.py --repin-ruled (the pins' only writer)
"""

from __future__ import annotations

import argparse
import hashlib
import importlib.util
import json
import re
import subprocess
import sys
from collections.abc import Callable
from dataclasses import dataclass, replace
from pathlib import Path
from types import ModuleType
from typing import Any

ROOT = Path(__file__).resolve().parents[3]
SPEC_REL = "docs/design/E48/E48-D01.md"
TOOL_REL = "docs/design/_tools/e48_d01_help_audit.py"
PINS_REL = "docs/design/_tools/e48_d01_ruled_pins.txt"
OWN_PATHS = (SPEC_REL, TOOL_REL, PINS_REL)
BASE = "df125c269be0b014e9e0655b571468e1fb641d6c"  # origin/main at the fold; by content
TOKENS = ROOT / "packages" / "ui" / "tokens"
CONTRAST_PATH = ROOT / "docs" / "design" / "_tools" / "contrast_check.py"
KEYMAP = "apps/web/src/keymap/keymap.json"
PATHS: dict[str, str] = {
    "05": "docs/plan/05-accessibility-standard.md",
    "11": "docs/plan/11-user-stories.md",
    "14": "docs/plan/14-screens-catalogue.md",
    "15": "docs/plan/15-component-catalogue.md",
    "22": "docs/plan/22-api-openapi.yaml",
    "TM48": "docs/plan/security/threat-models/e48-docs-ga.md",
    "E09D09": "docs/design/E09/E09-D09.md",
    "E42D05": "docs/design/E42/E42-D05.md",
    "E25D04": "docs/design/E25/E25-D04.md",
    "DS": ".claude/rules/32-design-specs.md",
}
CITE = re.compile(r"`(\d\d|TM48|E09D09|E42D05|E25D04|DS)`:(\d+(?:–\d+)?(?:, :\d+(?:–\d+)?)*)")
FRAME_ID = re.compile(r"\bB\d\d\b")
STATE_LEADS = ("UC-", "DG-", "GL-")
ACS = ("AC-1", "AC-2", "AC-3", "AC-4", "AC-5")
REQUIRED_STATES = {
    "UC-01": "idle", "UC-02": "checking", "UC-03": "up to date", "UC-04": "update ready",
    "UC-05": "check failed", "UC-07": "browser build", "UC-08": "offline",
    "DG-03": "generating", "DG-04": "generated", "DG-05": "secret detected",
    "DG-06": "truncated", "DG-08": "not the owner", "DG-12": "viewing as",
}  # fmt: skip
BUILDINFO_SOURCES = ("`BuildInfo`", "the client bundle", "a build constant")
RENDERING = re.compile(r"rendering (2a|2b|the sentence form)")
TOKEN_NAME = re.compile(
    r"`((?:color|font|border|radius|type|space|size|motion|opacity)\.[a-z0-9.-]*[a-z0-9])`"
)
RAW_COLOUR = re.compile(r"#(?:[0-9A-Fa-f]{6}|[0-9A-Fa-f]{3})(?![0-9A-Za-z])")
THEMES = ("dark", "light", "high-contrast")
FLOOR = {"text": 4.5, "ui": 3.0}
CLOSING = re.compile(r"\b(?:close[sd]?|fix(?:e[sd])?|resolve[sd]?)\s+#\d+", re.IGNORECASE)
LOCAL_PATH = re.compile("/" + "home/|/Users/|/" + "tmp/|[A-Za-z]:\\\\|\\bnotes/")  # assembled
AGENT_NAME = re.compile(r"\b[a-z]{2,9}-worker-\d\b")
URL_OR_HOST = re.compile(r"https?://|penpot\.[a-z]|team-id=|file-id=", re.IGNORECASE)
DENY = (
    "le" + "ak", "expo" + "sed", "by" + "pass", "ex" + "ploit", "att" + "ack", "ora" + "cle",
    "rev" + "eal", "unbou" + "nded", "flo" + "od", "st" + "all", "advi" + "sory", "gh" + "sa",
    "pre-" + "auth",
)  # fmt: skip
DENY_WORD = re.compile(r"\bd" + r"os\b", re.IGNORECASE)
CRED_RUN = re.compile(r"(?<![A-Za-z0-9])(?=[A-Za-z0-9]*\d)(?=[A-Za-z0-9]*[A-Za-z])[A-Za-z0-9]{20,}")
CRED_NAMED = re.compile(
    r"x-bapi-|api_key\s*[:=]|\bsign=|\bbearer\s+[A-Za-z0-9._~+/-]{8,}", re.IGNORECASE
)
REDACTION_OFF = re.compile(
    r"(turn|switch)(s|ing)? (off|of) (the )?redaction|redaction (toggle|option|off)|"
    r"include (raw|unredacted)",
    re.IGNORECASE,
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


def show(t: Texts, rel: str) -> str:
    key = f"{BASE}:{rel}"
    if key not in t.memo:
        t.memo[key] = git("show", key)
    text = t.memo[key]
    if text is None:
        raise LookupError(f"{rel} does not resolve at {BASE[:10]}; fetch first")
    return text


def at(t: Texts, key: str) -> str:
    return show(t, PATHS[key])


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
        else:
            _MODS[name] = _load(CONTRAST_PATH, name)
    return _MODS[name]


def norm(s: str) -> str:
    return " ".join(s.split())


def table_rows(text: str, lead: str) -> list[list[str]]:
    return [
        [c.strip() for c in ln.strip().strip("|").split("|")]
        for ln in text.split("\n")
        if ln.startswith("| " + lead)
    ]


def section(text: str, head: str) -> str:
    i = text.find("\n" + head)
    if i < 0:
        raise LookupError(f"the spec has no `{head}` section")
    depth = head.split(" ")[0]
    j = text.find("\n" + depth + " ", i + 1)
    return text[i : j if j > 0 else len(text)]


def one_row(text: str, lead: str) -> list[str]:
    rows = table_rows(text, lead + " ")
    if len(rows) != 1:
        raise LookupError(f"the spec carries {len(rows)} `{lead}` rows, not 1")
    return rows[0]


def state_rows(t: Texts) -> list[list[str]]:
    return [r for lead in STATE_LEADS for r in table_rows(t.spec, lead) if r[0][3:].isdigit()]


# ---------------------------------------------------------------------------- tokens


_THEMES: dict[str, dict[str, str]] = {}


def theme(name: str) -> dict[str, str]:
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


def contrast_rows(t: Texts) -> list[list[str]]:
    return table_rows(section(t.spec, "## 12."), "P-")


def contrast_values(r: list[str]) -> list[str]:
    cc = mod("contrast_check")
    fg, bg = tok(r[1]), tok(r[2])
    return [
        f"{cc.contrast_ratio(hex_rgb(color(th, fg)), hex_rgb(color(th, bg))):.2f}" for th in THEMES
    ]


def verdict(role: str, values: list[str]) -> str:
    floor = FLOOR.get(role)
    if floor is None:
        return "structure"
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


def g_state(t: Texts) -> list[str]:
    bad = []
    zero = section(t.spec, "## 0.")
    frames = [r[0] for r in table_rows(zero, "B") if FRAME_ID.fullmatch(r[0])]
    if len(frames) != len(set(frames)):
        bad.append("§0 lists a frame twice")
    listed = set(frames)
    named: set[str] = set()
    for r in state_rows(t) + table_rows(t.spec, "CL-"):
        ws = set(FRAME_ID.findall(r[-1]))
        if not ws:
            bad.append(f"{r[0]} names no frame")
        for w in ws - listed:
            bad.append(f"{r[0]} names {w}, which §0 does not list")
        named |= ws
    for ac in ACS:
        rows = table_rows(zero, ac + " ")
        if len(rows) != 1:
            bad.append(f"{ac} is not mapped once in §0")
            continue
        ws = set(FRAME_ID.findall(rows[0][-1]))
        if not ws or ws - listed:
            bad.append(f"{ac} maps to no frame §0 lists")
        named |= ws
    inset = re.search(r"\*\*Insets.*", zero)
    if inset:
        named |= set(FRAME_ID.findall(inset[0]))
    for frame_ref in re.findall(r"\(B(\d\d)\)", t.spec):
        named.add("B" + frame_ref)
    have = {r[0]: r for r in state_rows(t)}
    for sid, word in REQUIRED_STATES.items():
        if sid not in have or word not in have[sid][1].lower():
            bad.append(f"{sid} ({word}) is not a state row")
    bad += [f"§0's {w} is named by no state, AC, CL row or inset" for w in sorted(listed - named)]
    return bad


def g_checklist(t: Texts) -> list[str]:
    src = norm(at(t, "14").split("\n")[2524])
    if "Design sign-off acceptance checklist" not in src:
        raise LookupError("`14`:2525 is not SCR-119's checklist at the base")
    items = [norm(x) for x in src.split("[ ]")[1:]]
    cl = [norm(r[1]) for r in table_rows(t.spec, "CL-")]
    return [f"`14` item {x!r} stands on no CL row" for x in items if x not in cl]


def g_security(t: Texts) -> list[str]:
    bad = []
    one = section(t.spec, "## 1.")
    for need in (
        "3. **Security baseline (C-2.7, C-12.6).**",
        "in copied text or in a diagnostics bundle",
        "Redaction is always on and is never a user option",
        "never uploaded automatically",
    ):
        if need not in one:
            bad.append(f"§1 item 3 lacks {need!r}")
    for head in ("## 5.", "## 7."):
        if "§1 item 3" not in section(t.spec, head):
            bad.append(f"{head} does not cite §1 item 3")
    k06 = one_row(t.spec, "K-06")[1]
    if re.search(r"\{|pattern '|matched|line \d", k06):
        bad.append("K-06 names what was matched")
    if "names no pattern" not in " ".join(one_row(t.spec, "DG-05")):
        bad.append("DG-05 does not withhold the pattern")
    if "the full local path is not rendered" not in " ".join(one_row(t.spec, "DG-04")):
        bad.append("DG-04 renders the local path")
    if "Stored on this computer only. Never uploaded." not in section(t.spec, "### 7.2"):
        bad.append("§7.2 does not say the bundle stays local")
    for i, ln in enumerate(t.spec.split("\n"), 1):
        if REDACTION_OFF.search(ln) and "never" not in ln and "no control" not in ln:
            bad.append(f"spec:{i} offers to turn redaction off")
        if CRED_RUN.search(ln) or CRED_NAMED.search(ln):
            bad.append(f"spec:{i} carries a credential-shaped value")
    return bad


def g_build(t: Texts) -> list[str]:
    bad = []
    y = at(t, "22").split("\n")
    i = next((k for k, ln in enumerate(y) if ln.strip() == "BuildInfo:"), None)
    if i is None:
        raise LookupError("`BuildInfo` is not in `22` at the base")
    j = next(k for k in range(i + 1, len(y)) if y[k].startswith("    ") and y[k][4] != " ")
    fields = set(re.findall(r"^\s{8}([a-z_]+):", "\n".join(y[i:j]), re.MULTILINE))
    for r in table_rows(section(t.spec, "## 5."), "V-"):
        if not any(s in r[3] for s in BUILDINFO_SOURCES):
            bad.append(f"{r[0]} reads from {r[3]!r}")
        for f in re.findall(r"`([a-z_]+)`", r[2]):
            if "`BuildInfo`" in r[3] and f not in fields:
                bad.append(f"{r[0]} names `{f}`, which `BuildInfo` does not serve")
        if re.search(r"\b(host|path|node|hostname)\b", r[1].lower()):
            bad.append(f"{r[0]} shows infrastructure detail")
    return bad


def g_rbac(t: Texts) -> list[str]:
    bad = []
    one = section(t.spec, "## 1.")
    for need in ("is **T2**", "`E09D09`:38, :44", "`rbac.owner_only`", "rendering 2a"):
        if need not in one:
            bad.append(f"§1 item 4 lacks {need!r} (BQ-03: T2, never hidden)")
    dg08 = " ".join(one_row(t.spec, "DG-08"))
    if not re.search(r"\bT2\b", dg08) or "`rbac.owner_only`" not in dg08 or "absent" in dg08:
        bad.append("DG-08 does not draw the bundle T2 with `rbac.owner_only`")
    if "`rbac.view_as`" not in " ".join(one_row(t.spec, "DG-12")):
        bad.append("DG-12 does not draw the view-as T2")
    if "5. **No step-up on SCR-119.**" not in one:
        bad.append("§1 item 5 (no step-up) is missing")
    return bad


def g_browser(t: Texts) -> list[str]:
    bad = []
    uc7 = " ".join(one_row(t.spec, "UC-07"))
    if "absent" not in uc7 or "K-09" not in uc7:
        bad.append("UC-07 does not draw shell-only items absent with K-09")
    if "never drawn disabled" not in section(t.spec, "## 1."):
        bad.append("§1 item 7 does not forbid drawing shell-only items disabled")
    return bad


def g_shortcut(t: Texts) -> list[str]:
    bad = []
    km = json.loads(show(t, KEYMAP))
    n, c = len(km["commands"]), len(km["cheatsheetContexts"])
    eight = section(t.spec, "## 8.")
    if f"**{n} commands in {c} contexts**" not in eight:
        bad.append(f"§8 does not state the base's {n} commands in {c} contexts")
    if "draws no second cheatsheet" not in eight or "SCR-013" not in eight:
        bad.append("§8 does not reuse SCR-013")
    return bad


def g_token(t: Texts) -> list[str]:
    known = known_tokens()
    bad = [
        f"`{n}` does not resolve" for n in sorted(set(TOKEN_NAME.findall(t.spec))) if n not in known
    ]
    for i, ln in enumerate(t.spec.split("\n"), 1):
        if RAW_COLOUR.search(ln):
            bad.append(f"spec:{i} carries a raw colour value")
    return bad


def g_contrast(t: Texts) -> list[str]:
    bad = []
    rows = contrast_rows(t)
    if not rows:
        return ["§12 has no contrast rows"]
    for r in rows:
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
    if not any(r[1:3] == ["`color.text.tertiary`", "`color.surface.raised`"] for r in rows):
        bad.append("§12 lacks G-T2.2's tertiary-on-raised label pair")
    return bad


def g_t2(t: Texts) -> list[str]:
    bad = []
    ds = at(t, "DS").split("\n")
    one = norm(section(t.spec, "## 1."))
    for a, b, lead in ((28, 29, "`aria-disabled"), (40, 42, "hi-fi label"), (47, 48, "`Enter`")):
        src = norm(" ".join(ds[a - 1 : b]))
        quote = src[src.find(lead) :][:70]
        if quote not in one:
            bad.append(f"§1 item 6 does not quote `DS`:{a}–{b} verbatim")
    if "CMP-019 `lock`" not in one:
        bad.append("§1 item 6 does not name the CMP-019 `lock`")
    for r in state_rows(t):
        cells = " ".join(r)
        if re.search(r"\bT2\b", cells) and not RENDERING.search(cells):
            bad.append(f"{r[0]} shows a T2 control and names no rendering")
    fourteen = section(t.spec, "## 14.")
    if "CMP-079" not in fourteen or "CMP-019 `lock`" not in fourteen:
        bad.append("§14 does not list CMP-079 and the CMP-019 `lock` (G-T2.6)")
    return bad


def g_ruled(t: Texts) -> list[str]:
    bad = []
    k08 = one_row(t.spec, "K-08")[1]
    if "SCR-018" not in k08 or re.search(r"SCR-01[67]", k08):
        bad.append("K-08 does not open SCR-018 (BQ-10)")
    ia = {r[0] for r in table_rows(t.spec, "IA-")}
    bad += [f"IA-0{n} is missing (BQ-10)" for n in range(1, 10) if f"IA-0{n}" not in ia]
    for lead in ("DG-09", "DG-10", "DG-11"):
        if "E42-D05's" not in one_row(t.spec, lead)[2]:
            bad.append(f"{lead} does not reuse E42-D05's refusal (BQ-05)")
    saved = " ".join(one_row(t.spec, "DG-04")) + one_row(t.spec, "K-05")[1]
    if "{file}" in saved or "no Show in folder" not in saved:
        bad.append("the saved line draws a file name or Show in folder as served (BQ-05)")
    return bad


def g_request(t: Texts) -> list[str]:
    bad = []
    for i, ln in enumerate(t.spec.split("\n"), 1):
        if "#1220" not in ln:
            continue
        if ln.startswith(("| R-", "**Pre-stage.**")) or "R-1" in ln:
            continue
        bad.append(f"spec:{i} cites unmerged work outside a request row")
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
    checks = (
        (CLOSING, "a closing keyword (PR 2 alone closes #1327)"),
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
    for label, text in (("spec", t.spec), ("tool", t.tool), ("pins", t.pins)):
        for i, ln in enumerate(text.split("\n"), 1):
            if any(d in ln.lower() for d in DENY) or DENY_WORD.search(ln):
                bad.append(f"{label}:{i} carries a public-text deny word")
    return bad


def g_scope(t: Texts) -> list[str]:
    if t.changed is None:
        return ["cannot list the changed paths (git failed)"]
    own = ", ".join(OWN_PATHS)
    return [f"{p} is touched; this PR owns {own}" for p in t.changed if p not in OWN_PATHS]


GATES: dict[str, Callable[[Texts], list[str]]] = {
    "G-STATE": g_state, "G-CHECKLIST": g_checklist, "G-SECURITY": g_security,
    "G-BUILD": g_build, "G-RBAC": g_rbac, "G-BROWSER": g_browser, "G-SHORTCUT": g_shortcut,
    "G-TOKEN": g_token, "G-CONTRAST": g_contrast, "G-T2": g_t2, "G-RULED": g_ruled,
    "G-REQUEST": g_request,
    "G-CITE": g_cite, "G-HYGIENE": g_hygiene, "G-SCOPE": g_scope,
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
        cells = [c.strip() for c in ln.strip().strip("|").split("|")]
        if ln.startswith("| P-") and len(cells) == 8 and cells[0][2:].isdigit():
            v = contrast_values(cells)
            cells[4:8] = [*v, verdict(cells[3], v)]
            ln = "| " + " | ".join(cells) + " |"
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
        cells = [c.strip() for c in ls[i].strip().strip("|").split("|")]
        cells[col] = value
        ls[i] = "| " + " | ".join(cells) + " |"
        return replace(t, spec="\n".join(ls))

    return f


def drop_row(lead: str) -> Callable[[Texts], Texts]:
    return lambda t: replace(
        t, spec="\n".join(x for x in t.spec.split("\n") if not x.startswith(lead))
    )


def add_line(text: str) -> Callable[[Texts], Texts]:
    return lambda t: replace(t, spec=t.spec + "\n" + text + "\n")


MUTATIONS: tuple[tuple[str, str, Callable[[Texts], Texts]], ...] = (
    ("G-STATE", "drop the secret-detected frame", drop_row("| B10 ")),
    ("G-STATE", "drop the AC-2 mapping", drop_row("| AC-2 ")),
    ("G-STATE", "drop the check-failed state", drop_row("| UC-05 ")),
    ("G-STATE", "point a state at an unlisted frame", set_cell("DG-06", 3, "B99")),
    ("G-STATE", "leave a frame unnamed", sub("| B21 | `SCR-119/copied`", "| B22 | `SCR-119/extra` | W1 | to draw (PR 2) |\n| B21 | `SCR-119/copied`")),
    ("G-CHECKLIST", "paraphrase a `14` item", set_cell("CL-05", 1, "the licence list")),
    ("G-CHECKLIST", "drop a `14` item", drop_row("| CL-02 ")),
    ("G-SECURITY", "drop the copied-text clause", sub("in copied text or in a diagnostics bundle", "or in a bundle")),
    ("G-SECURITY", "make redaction optional", sub("Redaction is always on and is never a user option", "Redaction is on by default")),
    ("G-SECURITY", "offer to turn redaction off", add_line("An advanced switch lets the Owner turn off redaction for one bundle.")),
    ("G-SECURITY", "name the matched pattern", set_cell("K-06", 1, '"No bundle was created. The pattern {pattern} matched."')),
    ("G-SECURITY", "render the local path", set_cell("DG-04", 2, "K-05 with the full local path and Copy; no Show in folder")),
    ("G-SECURITY", "drop the local-only line", sub('"Stored on this computer only. Never uploaded."', '"Saved."')),
    ("G-SECURITY", "draw a token-shaped value", add_line("| X-1 | the log line reads bearer " + "abcDEFghiJKLmno |")),
    ("G-BUILD", "show a host row", sub("| V-07 |", "| V-08 | Host name | the server's host | `BuildInfo` |\n| V-07 |")),
    ("G-BUILD", "name a field BuildInfo lacks", set_cell("V-05", 2, "`ws_version`")),
    ("G-BUILD", "read a version from elsewhere", set_cell("V-02", 3, "the docs site")),
    ("G-RBAC", "hide the bundle from a Manager", set_cell("DG-08", 2, "the control and its section absent; no reason line")),
    ("G-RBAC", "drop the view-as T2", set_cell("DG-12", 2, "the control as for the Owner")),
    ("G-RBAC", "hide it in §1 item 4", sub("is **T2**: `aria-disabled`", "is **absent**: `aria-disabled`")),
    ("G-RBAC", "ask a step-up on SCR-119", sub("5. **No step-up on SCR-119.**", "5. **A step-up on the bundle.**")),
    ("G-BROWSER", "draw shell-only items disabled", set_cell("UC-07", 2, "the control and V-06 disabled with K-09")),
    ("G-BROWSER", "allow disabled shell items", sub("never drawn disabled, always", "drawn disabled, always")),
    ("G-SHORTCUT", "state a stale binding count", sub("**85 commands in 9 contexts**", "**60 commands in 6 contexts**")),
    ("G-SHORTCUT", "draw a second cheatsheet", sub("SCR-119 draws no second cheatsheet.", "SCR-119 draws its own cheatsheet.")),
    ("G-TOKEN", "misspell a token", sub("with `font.lineheight.relaxed`, about", "with `font.lineheight.relax`, about")),
    ("G-TOKEN", "use a raw colour", add_line("The callout border is #FF0000.")),
    ("G-CONTRAST", "type a contrast figure off", set_cell("P-01", 4, "1.00")),
    ("G-CONTRAST", "drop the T2 label pair", drop_row("| P-03 ")),
    ("G-T2", "let a T2 control leave the Tab order (G-T2.1b)", sub("never the `disabled` attribute — it stays in the Tab order", "or the `disabled` attribute")),
    ("G-T2", "dim the T2 label (G-T2.2)", sub("hi-fi label `color.text.tertiary`, reason", "hi-fi label dimmed, reason")),
    ("G-T2", "make a T2 press act (G-T2.3)", sub("changes nothing and re-shows the reason inline with one polite announcement", "acts")),
    ("G-T2", "drop the offline rendering", set_cell("UC-08", 2, 'Check for updates T2 `help.offline` "Needs a connection to the server." (PROPOSED)')),
    ("G-RULED", "restart the SCR-016 wizard", set_cell("K-08", 1, '"Restart the guided tour" (opens SCR-016 at step 1)')),
    ("G-RULED", "drop the changelog row", drop_row("| IA-02 ")),
    ("G-RULED", "write new copy for a refusal", set_cell("DG-10", 2, '"There is not enough disk space."')),
    ("G-RULED", "draw the file name as served", set_cell("K-05", 1, '"Bundle created: {file} ({size})."')),
    ("G-REQUEST", "lean on #1220 outside a request row", add_line("Per #1220, the bundle needs no code.")),
    ("G-CITE", "re-point a cite to an unpinned line", sub("(`22`:12464)", "(`22`:12465)")),
    ("G-HYGIENE", "write a closing keyword against #1327", add_line("This PR closes #1327.")),
    ("G-HYGIENE", "put a deny word into the tool's own text", lambda t: replace(t, tool=t.tool + "\n# " + DENY[9] + "\n")),
    ("G-SCOPE", "touch `14` in the diff", lambda t: replace(t, changed=[*OWN_PATHS, PATHS["14"]])),
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
    restored = load().spec == before
    ok &= restored
    out.append(
        f"self-test: {len(MUTATIONS)} mutations, text restored: {'yes' if restored else 'NO'}"
    )
    out.append(f"self-test: {'PASS' if ok else 'FAIL'}")
    return ok, out


def main(argv: list[str]) -> int:
    ap = argparse.ArgumentParser(description="E48-D01 help and about audit")
    g = ap.add_mutually_exclusive_group()
    for flag in ("--check", "--fill", "--self-test", "--repin-ruled"):
        g.add_argument(flag, action="store_true")
    a = ap.parse_args(argv)
    if a.self_test:
        ok, lines = selftest()
        print("\n".join(lines))
        return 0 if ok else 1
    t = load()
    if a.fill:
        (ROOT / SPEC_REL).write_text(fill(t), encoding="utf-8")
        print(f"filled §12 in {SPEC_REL}")
        return 0
    if a.repin_ruled:
        hashes, bad = cite_hashes(t)
        if bad:
            print(f"refused: {bad[0]}")
            return 1
        head = (
            "# E48-D01 cite pins: the cite, a hash of its cited line(s) at its base."
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
