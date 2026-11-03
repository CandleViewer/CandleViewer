#!/usr/bin/env python3
"""E43-D01 (#1138) audit: the hi-fi spec of the security centre (SCR-137), its live trading gate
(B17) and the gate's states on the two hosts (SCR-074's Live option, SCR-010's pill).

Standalone and offline, shaped on the merged E38-D03 tool (`e38_d03_honesty_audit.py`): it imports
`packages/ui/tokens/tests/verify_tokens.py` (the token loader and resolver),
`docs/design/_tools/contrast_check.py` (`contrast_ratio`) and
`docs/research/_tools/cvd_simulate.py` (`simulate`, `delta_e76`; JND 5.0) from the working tree
and never re-implements them. It reads the spec and the pins file from the working tree and every
cited file AS TEXT with `git show` at the pinned base (`BASE`). Default-deny: a gate that cannot
read its input FAILs.

Gates (each FAIL led by its name):
  G-STATE     every state the ticket's Scope names has a §0 frame row with a wireframe board
              (W1 … W3) and a hi-fi board (H1 … H3), and each acceptance criterion (AC-1 … AC-4)
              maps to frames that §0 lists.
  G-TOKEN     every design token the spec names is in a merged set.
  G-CONTRAST  every §10.1 row is recomputed per theme (dark, light, high-contrast as
              `verify_tokens` merges them) and equals the spec to two decimals; a `text` row is at
              least 4.5:1 and a `ui` row at least 3:1 in every theme; the verdict matches.
  G-CVD       every §10.2 row's normal / protanopia / deuteranopia / tritanopia ΔE76 equals the
              spec to two decimals, and its JND column names the simulations under 5.0.
  G-T2        every state row (SEC-, GATE-, SW-, SH-) whose Presentation is T2 names its rendering
              (2a, 2b or the sentence form) and quotes its reason right after "T2", and that reason
              is an E09-D09 key's text at the base unless the cell marks it PROPOSED. §1 names the
              CMP-019 `lock` and CMP-079, quotes G-T2.1b, G-T2.2 and G-T2.3 verbatim from `DS` at
              the base, and §10.1 carries the G-T2.2 label pair (tertiary on raised).
  G-GATE      the safety reading: the gate records and does not enforce (C-2.21); enabling LIVE
              switches no session (C-2.11); the enable is a typed `ENABLE LIVE` then a fresh
              `live_enablement` code; turning off needs no typed word and no code and is never T2
              or hidden; its consequence is `11`'s sentence verbatim; every confirm starts on
              Cancel; the C-2.6 carve-out is stated; the withdrawal finding is fix-only; the
              posture never renders a checkbox; a Manager's popover carries no admin link.
  G-SECRET    no secret material: key ids only as `...` plus four characters, no IPv4 literal,
              and "secret" only in §1's no-secret item.
  G-D8        D8 is read from the merged threat model (`TM`:749, :1045); E42-T06's ADR appears only
              on request rows and never with a number; no admin-operations doc is cited.
  G-CITE      every cite in range and on a non-blank line at its base, and equal to the pins.
  G-HYGIENE   no closing keyword, local path, URL or host, agent name, double-brace slot or
              deny word in the spec; no deny word in this tool's text or the pins.
  G-SCOPE     the diff touches only the spec, this tool and the pins file.

Usage (from the repo root):
  python3 -I docs/design/_tools/e43_d01_security_centre_audit.py --check
  python3 -I docs/design/_tools/e43_d01_security_centre_audit.py --fill        (writes §10's figures)
  python3 -I docs/design/_tools/e43_d01_security_centre_audit.py --self-test
  python3 -I docs/design/_tools/e43_d01_security_centre_audit.py --repin-ruled (the pins' only writer)
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
SPEC_REL = "docs/design/E43/E43-D01.md"
TOOL_REL = "docs/design/_tools/e43_d01_security_centre_audit.py"
PINS_REL = "docs/design/_tools/e43_d01_ruled_pins.txt"
OWN_PATHS = (SPEC_REL, TOOL_REL, PINS_REL)
BASE = "d023df0f66409807f2594ccd5086cd6d5017b16a"  # origin/main when written; re-pinned by content
TOKENS = ROOT / "packages" / "ui" / "tokens"
CVD_PATH = ROOT / "docs" / "research" / "_tools" / "cvd_simulate.py"
CONTRAST_PATH = ROOT / "docs" / "design" / "_tools" / "contrast_check.py"
PATHS: dict[str, str] = {
    "04": "docs/plan/04-security-program.md",
    "07": "docs/plan/07-release-and-prr.md",
    "11": "docs/plan/11-user-stories.md",
    "14": "docs/plan/14-screens-catalogue.md",
    "15": "docs/plan/15-component-catalogue.md",
    "22": "docs/plan/22-api-openapi.yaml",
    "28": "docs/plan/28-statechart-catalogue.md",
    "TM": "docs/security/threat-models/e42-admin.md",
    "E09D09": "docs/design/E09/E09-D09.md",
    "E42D02": "docs/design/E42/E42-D02.md",
    "E42D04": "docs/design/E42/E42-D04.md",
    "E38D02": "docs/design/E38/E38-D02.md",
    "DS": ".claude/rules/32-design-specs.md",
}
CITE = re.compile(
    r"`(\d\d|TM|E09D09|E42D0[24]|E38D02|DS)`:(\d+(?:–\d+)?(?:, :\d+(?:–\d+)?)*)"
)
TOKEN_NAME = re.compile(
    r"`((?:color|font|border|radius|type|space|size|motion|opacity|elevation)\.[a-z0-9.-]*[a-z0-9])`"
)
CLOSING = re.compile(
    r"\b(?:close[sd]?|fix(?:e[sd])?|resolve[sd]?)\s+#\d+", re.IGNORECASE
)
LOCAL_PATH = re.compile(
    "/" + "home/|/" + "tmp/|\\bno" + "tes/|/Users/|[A-Za-z]:\\\\|\\bwt-" + "notes\\b"
)  # assembled
AGENT_NAME = re.compile(r"\b[a-z]{2,9}-worker-\d\b")
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
    "advi" + "sor",
    "gh" + "sa",
    "pre-" + "auth",
)  # each entry an explicit join, so this tool's own text carries none of the words
THEMES = ("dark", "light", "high-contrast")
FLOOR = {"text": 4.5, "ui": 3.0}
DEFICIENCIES = ("protanopia", "deuteranopia", "tritanopia")
# the states the ticket's Scope names; each needs a §0 frame row with a wireframe and a hi-fi board
REQUIRED_FRAMES = (
    "SCR-137/loading",
    "SCR-137/compliant",
    "SCR-137/findings",
    "SCR-137/stale-check",
    "SCR-137/check-failed",
    "SCR-137/rescan-running",
    "SCR-137/unavailable",
    "SCR-137/dismiss-dialog",
    "SCR-137/dismiss-not-allowed",
    "SCR-137/gate-blocked",
    "SCR-137/gate-attest-dialog",
    "SCR-137/gate-eligible",
    "SCR-137/gate-enable-confirm",
    "SCR-137/gate-step-up",
    "SCR-137/gate-enabled",
    "SCR-137/gate-disable-confirm",
    "SCR-137/gate-turned-off",
    "SCR-137/gate-invalidated",
    "SCR-137/gate-unknown",
    "SCR-074/gate-locked-owner",
    "SCR-074/gate-locked-manager",
    "SCR-074/not-permitted",
    "SCR-010/gate-locked",
    "SCR-010/live-turned-off",
)
ACS = ("AC-1", "AC-2", "AC-3", "AC-4")
FRAME = re.compile(r"`((?:SCR-\d{3}|[a-z-]+)/[a-z0-9-]+)`")
ADR_NUMBER = re.compile(r"ADR-\d{4}")
OPS_DOC = re.compile(r"docs/ops")
T06_ADR = "E42-T06's ADR"
MASK = re.compile(r"[Kk]ey \.\.\.([A-Za-z0-9]*)")
IPV4 = re.compile(r"\b\d{1,3}\.\d{1,3}\.\d{1,3}\.\d{1,3}\b")


@dataclass(frozen=True)
class Texts:
    spec: str
    pins: str
    tool: str
    changed: list[str] | None
    memo: dict[str, str | None]


def git(*args: str) -> str | None:
    try:
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
    text = show(t, BASE, PATHS[key])
    if text is None:
        raise SystemExit(f"{PATHS[key]} does not resolve at {BASE[:10]}; fetch first")
    return text


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


def table_rows(text: str, lead: str) -> list[list[str]]:
    out = []
    for ln in text.split("\n"):
        if ln.startswith("| " + lead):
            out.append([c.strip() for c in ln.strip().strip("|").split("|")])
    return out


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


# ---------------------------------------------------------------------------- figures


def contrast_rows(t: Texts) -> list[list[str]]:
    return table_rows(section(t.spec, "### 10.1"), "P-")


def cvd_rows(t: Texts) -> list[list[str]]:
    return table_rows(section(t.spec, "### 10.2"), "V-")


def tok(cell: str) -> str:
    m = re.fullmatch(r"`([a-z0-9.-]+)`", cell)
    if not m:
        raise LookupError(f"{cell!r} is not one token")
    return m[1]


def contrast_values(row_: list[str]) -> list[str]:
    cc = mod("contrast_check")
    fg, bg = tok(row_[1]), tok(row_[2])
    return [
        f"{cc.contrast_ratio(hex_rgb(color(th, fg)), hex_rgb(color(th, bg))):.2f}"
        for th in THEMES
    ]


def cvd_values(row_: list[str]) -> tuple[str, str]:
    cv = mod("cvd_simulate")
    th = {"hc": "high-contrast"}.get(row_[3], row_[3])
    ha, hb = color(th, tok(row_[1])), color(th, tok(row_[2]))
    ds = [cv.delta_e76(ha, hb)] + [
        cv.delta_e76(cv.simulate(ha, d), cv.simulate(hb, d)) for d in DEFICIENCIES
    ]
    under = [
        n
        for n, d in zip(("normal", *DEFICIENCIES), ds, strict=True)
        if d < cv.JND_FLOOR
    ]
    return " / ".join(f"{d:.2f}" for d in ds), (", ".join(under) if under else "none")


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
    rows = {r[1].strip("`"): r for r in table_rows(zero, "B") if len(r) > 3}
    for f in REQUIRED_FRAMES:
        r = rows.get(f)
        if r is None:
            bad.append(f"no §0 frame row for `{f}`")
        elif not re.fullmatch(r"W[1-3]", r[2]) or not re.fullmatch(r"H[1-3]", r[3]):
            bad.append(f"`{f}`: the row names no wireframe and hi-fi board pair")
    acs = {r[0]: FRAME.findall(r[2]) for r in table_rows(zero, "AC-") if len(r) > 2}
    for ac in ACS:
        if not acs.get(ac):
            bad.append(f"{ac} maps to no frame in §0")
        for f in acs.get(ac, []):
            if f not in rows:
                bad.append(f"{ac} maps to `{f}`, which §0 does not list")
    return bad


def g_token(t: Texts) -> list[str]:
    known = known_tokens()
    names = sorted(set(TOKEN_NAME.findall(t.spec)))
    return [
        f"`{n}` does not resolve in the token JSON at the base"
        for n in names
        if n not in known
    ]


def verdict(role: str, values: list[str]) -> str:
    floor = FLOOR.get(role)
    if floor is None:
        return "structure"
    return "pass" if min(map(float, values)) >= floor else "FAIL"


def g_contrast(t: Texts) -> list[str]:
    bad = []
    rows = contrast_rows(t)
    if not rows:
        return ["§10.1 has no contrast rows"]
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
    return bad


def g_cvd(t: Texts) -> list[str]:
    bad = []
    rows = cvd_rows(t)
    if not rows:
        return ["§10.2 has no CVD rows"]
    for r in rows:
        if len(r) != 6:
            bad.append(f"{r[0]}: {len(r)} cells, not 6")
            continue
        ds, under = cvd_values(r)
        if r[4] != ds or r[5] != under:
            bad.append(f"{r[0]}: reads {r[4]} / {r[5]}, the tool gives {ds} / {under}")
    return bad


def e09_templates(t: Texts) -> list[re.Pattern[str]]:
    out = []
    for ln in at(t, "E09D09").split("\n"):
        if ln.startswith("| `"):
            for q in re.findall(r'"([^"]{8,})"', ln):
                parts = re.split(r"\{[a-z_]+\}", q)
                out.append(re.compile(".+?".join(re.escape(x) for x in parts) + "$"))
    return out


RENDERING = re.compile(r"rendering (2a|2b|the sentence form)")
T2_REASON = re.compile(r'T2(?: `[a-z_.]+`)? "([^"]{8,})"')
STATE_LEADS = ("SEC-", "GATE-", "SW-", "SH-")
# G-T2.1b, G-T2.2 and G-T2.3 as `DS` words them (its `**` emphasis dropped); §1 quotes each
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
            " the reason inline with one polite announcement"
        ),
    ),
)


def t2_quotes(t: Texts) -> list[str]:
    """G-T2.1b / 2 / 3: quoted from the owner, not paraphrased; the label pair measured."""
    bad = []
    owner = norm(at(t, "DS").replace("**", ""))
    one = norm(section(t.spec, "## 1."))
    for gid, q in T2_QUOTES:
        if norm(q) not in owner:
            bad.append(f"{gid}: the quote is no longer `DS`'s text at the base")
        elif f"{gid}, verbatim" not in one or norm(q) not in one:
            bad.append(f"§1 does not quote {gid} verbatim from `DS`")
    pairs = {(r[1], r[2], r[3]) for r in contrast_rows(t) if len(r) > 3}
    if ("`color.text.tertiary`", "`color.surface.raised`", "text") not in pairs:
        bad.append(
            "§10.1 has no `text` row for `color.text.tertiary` on `color.surface.raised` (G-T2.2)"
        )
    return bad


def g_t2(t: Texts) -> list[str]:
    bad = []
    rows = [r for lead in STATE_LEADS for r in table_rows(t.spec, lead)]
    if not rows:
        return ["the spec has no state rows"]
    keys = e09_templates(t)
    one = section(t.spec, "## 1.")
    if "CMP-019 `lock`" not in one or "CMP-079" not in one:
        bad.append("§1 does not name the CMP-019 `lock` glyph and CMP-079 for T2")
    bad += t2_quotes(t)
    for r in rows:
        if len(r) < 4 or "T2" not in r[3]:
            continue
        if not RENDERING.search(r[3]):
            bad.append(
                f"{r[0]}: a T2 control with no rendering (2a, 2b or the sentence form)"
            )
        quote = T2_REASON.search(r[3])
        if not quote:
            bad.append(f"{r[0]}: a T2 presentation with no quoted reason after T2")
        elif "PROPOSED" not in r[3] and not any(k.match(quote[1]) for k in keys):
            bad.append(
                f"{r[0]}: {quote[1]!r} is no E09-D09 key's text and is not PROPOSED"
            )
    return bad


def story_consequence(t: Texts) -> str:
    """US-ADMIN-012's re-disable sentence at the base, its Gherkin `Then ` dropped."""
    for ln in at(t, "11").split("\n"):
        s = ln.strip()
        if s.startswith("Then no new live orders are accepted"):
            return s.removeprefix("Then ")
    raise LookupError("`11` carries no re-disable sentence at the base")


GATE_TEXTS = (
    ("§1 item 2", "records and orchestrates; it does not enforce"),
    (
        "§1 item 2",
        "No copy on these surfaces says the screen enforces anything",
    ),
    ("§1 item 3", "Enabling live makes LIVE **selectable**; it switches no session."),
    ("§6.3", "class `live_enablement`"),
    ("§6.4", "It is **never T2 and never hidden** while live may be on"),
    ("§6.4", "**no typed word and no code**"),
    ("§7.2", "**Protective writes are never gated.**"),
    (
        "§7.2",
        "cancel, close, flatten, reduce-only orders and setting or tightening a stop stay enabled",
    ),
)


def g_gate(t: Texts) -> list[str]:
    """The safety reading the brief and the owners fix; each a sentence the lens can cite."""
    bad = []
    for where, s in GATE_TEXTS:
        if s not in t.spec:
            bad.append(f"{where}: missing {s[:60]!r}")
    if f'"{story_consequence(t)}" (`11`:5013)' not in t.spec:
        bad.append("§6.4: the consequence is not `11`:5013's sentence verbatim")
    if '"Type ENABLE LIVE to confirm"' not in section(t.spec, "### 6.3"):
        bad.append("§6.3: the enable confirm types no ENABLE LIVE token")
    off = row(t, "GATE-08")[3]
    if "no typed word, no code" not in off:
        bad.append("GATE-08: turning off must ask no typed word and no code")
    for lead in ("SEC-10", "GATE-05", "GATE-08"):
        if "focus on Cancel" not in row(t, lead)[3]:
            bad.append(f"{lead}: the confirm does not start with focus on Cancel")
    if "T2" in row(t, "GATE-07")[3]:
        bad.append("GATE-07: the off control is drawn gated")
    wd = row(t, "Withdrawal permission detected")
    if not wd[4].startswith("no (C-2.8"):
        bad.append("§5.1: the withdrawal finding is drawn dismissible")
    if "T2" not in row(t, "SEC-12")[3]:
        bad.append("SEC-12: the fix-only finding's Dismiss… is not T2")
    if "**no link**" not in row(t, "SW-02")[3]:
        bad.append("SW-02: a Manager's popover carries an admin link")
    for i, ln in enumerate(t.spec.split("\n"), 1):
        low = ln.lower()
        if "checkbox" in low and not (
            "no check renders as a checkbox" in low or "never a checkbox" in low
        ):
            bad.append(f"spec:{i} draws a checkbox (`11`:4976: never a checklist)")
    return bad


def g_secret(t: Texts) -> list[str]:
    bad = []
    one = section(t.spec, "## 1.")
    if "Every field drawn exists in `SecuritySummary`" not in one:
        bad.append("§1 does not hold every field to `SecuritySummary` or a G-row")
    for i, ln in enumerate(t.spec.split("\n"), 1):
        for m in MASK.finditer(ln):
            if not re.fullmatch(r"[A-Za-z0-9]{4}", m[1]):
                bad.append(
                    f"spec:{i} shows a key id that is not `...` plus four characters"
                )
        if IPV4.search(ln):
            bad.append(f"spec:{i} shows an address literal")
        if "secret" in ln.lower().replace("g-secret", "") and not ln.startswith(
            "4. **No secret material.**"
        ):
            bad.append(f"spec:{i} names secret material outside §1 item 4")
    return bad


def g_d8(t: Texts) -> list[str]:
    bad = []
    one = section(t.spec, "## 1.")
    for need in ("`TM`:749", "`TM`:1045", "D8-invariant"):
        if need not in one:
            bad.append(f"§1 item 6 lacks {need}")
    for i, ln in enumerate(t.spec.split("\n"), 1):
        if ADR_NUMBER.search(ln):
            bad.append(
                f"spec:{i} names an ADR number (E42-T06's ADR is unnumbered here)"
            )
        if OPS_DOC.search(ln):
            bad.append(f"spec:{i} cites an admin-operations doc")
        if T06_ADR in ln and not (
            ln.startswith(("| R-", "**Pre-stage.**")) or "request row" in ln
        ):
            bad.append(f"spec:{i} leans on E42-T06's ADR outside a request row")
    row(t, "C-2")  # the D8 conflict row must exist (LookupError otherwise)
    return bad


def g_cite(t: Texts) -> list[str]:
    hashes, bad = cite_hashes(t)
    pinned = parse_pins(t.pins)
    for label, h in hashes.items():
        if label not in pinned:
            bad.append(
                f"cite {label} is unpinned: verify it by content, then --repin-ruled"
            )
        elif pinned[label] != h:
            bad.append(f"cite {label}: the line at its base is not the pinned content")
    return bad


def g_hygiene(t: Texts) -> list[str]:
    bad = []
    checks = ((CLOSING, "a closing keyword (PR 2 alone closes #1138)"), (LOCAL_PATH, "a local path"),
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
    return [
        f"{p} is touched; this ticket owns {own}"
        for p in t.changed
        if p not in OWN_PATHS
    ]


GATES: dict[str, Callable[[Texts], list[str]]] = {
    "G-STATE": g_state, "G-TOKEN": g_token, "G-CONTRAST": g_contrast, "G-CVD": g_cvd,
    "G-T2": g_t2, "G-GATE": g_gate, "G-SECRET": g_secret, "G-D8": g_d8, "G-CITE": g_cite,
    "G-HYGIENE": g_hygiene, "G-SCOPE": g_scope,
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
    pins = (
        (ROOT / PINS_REL).read_text(encoding="utf-8")
        if (ROOT / PINS_REL).exists()
        else ""
    )
    tool = (ROOT / TOOL_REL).read_text(encoding="utf-8")
    return Texts(spec, pins, tool, changed_paths(), {})


def fill(t: Texts) -> str:
    out = []
    for ln in t.spec.split("\n"):
        cells = [c.strip() for c in ln.strip().strip("|").split("|")]
        if ln.startswith("| P-") and len(cells) == 8:
            v = contrast_values(cells)
            cells[4:8] = [*v, verdict(cells[3], v)]
            ln = "| " + " | ".join(cells) + " |"
        elif ln.startswith("| V-") and len(cells) == 6:
            cells[4], cells[5] = cvd_values(cells)
            ln = "| " + " | ".join(cells) + " |"
        out.append(ln)
    return "\n".join(out)


def sub(old: str, new: str) -> Callable[[Texts], Texts]:
    def f(t: Texts) -> Texts:
        if t.spec.count(old) != 1:
            raise SystemExit(
                f"self-test: the spec carries {old[:50]!r} {t.spec.count(old)} times"
            )
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
    def f(t: Texts) -> Texts:
        return replace(
            t,
            spec="\n".join(ln for ln in t.spec.split("\n") if not ln.startswith(lead)),
        )

    return f


def add_line(text: str) -> Callable[[Texts], Texts]:
    def f(t: Texts) -> Texts:
        return replace(t, spec=t.spec + "\n" + text + "\n")

    return f


MUTATIONS: tuple[tuple[str, str, Callable[[Texts], Texts]], ...] = (
    ("G-STATE", "drop the gate-blocked frame row", drop_row("| B10 ")),
    ("G-STATE", "drop the AC-4 mapping", drop_row("| AC-4 ")),
    ("G-STATE", "draw a frame with no wireframe", set_cell("B03", 2, "—")),
    ("G-TOKEN", "misspell a token", sub("labels and sources `type.ui.label`", "labels and sources `type.ui.lable`")),
    ("G-CONTRAST", "type a contrast figure off", set_cell("P-01", 4, "1.00")),
    ("G-CONTRAST", "report a ui pair as structure", set_cell("P-05", 3, "structure")),
    ("G-CVD", "type a ΔE figure off", set_cell("V-01", 4, "1.00 / 1.00 / 1.00 / 1.00")),
    ("G-T2", "drop the gate's reason", set_cell("GATE-02", 3, "Enable T2; rendering 2a")),
    ("G-T2", "retype a key's text", set_cell("SW-03", 3, 'T2 `rbac.env` "Live isn\'t on for you."; rendering 2a')),
    ("G-T2", "drop a control's rendering", set_cell("SEC-12", 3, 'T2 "This finding clears only when it is fixed." (a PROPOSED key)')),
    ("G-T2", "drop the lock from §1", sub("led by the CMP-019 `lock` glyph", "led by its glyph")),
    ("G-T2", "let a T2 control leave the Tab order (G-T2.1b)", sub("never the `disabled` attribute — it stays in the Tab order", "or the `disabled` attribute")),
    ("G-T2", "dim a T2 label (G-T2.2)", sub("never `color.text.disabled`, never `opacity.disabled` on", "dimmed with `opacity.disabled` on")),
    ("G-T2", "make a T2 press act (G-T2.3)", sub("changes nothing and re-shows the reason inline with one polite announcement", "acts")),
    ("G-T2", "drop the tertiary label pair (G-T2.2)", drop_row("| P-03 ")),
    ("G-GATE", "let the screen claim enforcement", sub("records and orchestrates; it does not enforce", "records and enforces")),
    ("G-GATE", "let enabling switch sessions (C-2.11)", sub("it switches no session.", "every session follows.")),
    ("G-GATE", "ask a code to turn live off", set_cell("GATE-08", 3, "standard confirm and a fresh code; focus on Cancel")),
    ("G-GATE", "paraphrase the reduce-only consequence", sub("remain manageable in reduce-only mode\" (`11`:5013)", "stay manageable\" (`11`:5013)")),
    ("G-GATE", "drop the typed token", sub('"Type ENABLE LIVE to confirm"', '"Type LIVE to confirm"')),
    ("G-GATE", "start a confirm on its Confirm", set_cell("SEC-10", 3, "Confirm natively disabled until the reason holds text; focus on Confirm")),
    ("G-GATE", "make the withdrawal finding dismissible", set_cell("Withdrawal permission detected", 4, "yes, with a reason")),
    ("G-GATE", "gate the protective writes", sub("**Protective writes are never gated.**", "**Protective writes follow the band.**")),
    ("G-GATE", "give a Manager the admin link", set_cell("SW-02", 3, 'T2 "Live trading is off until the live gate opens." (PROPOSED); rendering 2a, with a "Security centre" link')),
    ("G-GATE", "draw a posture checkbox", add_line("Each check carries a checkbox the Owner can set.")),
    ("G-SECRET", "show a full key id", add_line("The row names key ...a1B2c3D4e5 in full.")),
    ("G-SECRET", "show an allowlisted address", add_line("The allowlist expects 100.64.0.7.")),
    ("G-SECRET", "name secret material in a row", add_line("The dialog shows the API secret once.")),
    ("G-D8", "number E42-T06's ADR", add_line("The admin window is ADR-0022's.")),
    ("G-D8", "cite E42-T06's ADR as an owner", add_line("Per E42-T06's ADR, the window covers the enable.")),
    ("G-D8", "cite an admin-operations doc", add_line("See the runbook in docs/ops for the off-switch.")),
    ("G-CITE", "re-point a `14` cite to an unpinned line", sub("(`14`:2876)", "(`14`:2879)")),
    ("G-HYGIENE", "write a closing keyword against #1138", sub("carries the closing line.", "carries the closing line. Closes #1138.")),
    ("G-HYGIENE", "put a deny word into the tool's own text", lambda t: replace(t, tool=t.tool + "\n# " + DENY[9] + "\n")),
    ("G-SCOPE", "touch `14` in the diff", lambda t: replace(t, changed=[*OWN_PATHS, PATHS["14"]])),
)  # fmt: skip


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
    restored = load().spec == before
    ok &= restored
    out.append(
        f"self-test: {len(MUTATIONS)} mutations, text restored: {'yes' if restored else 'NO'}"
    )
    out.append(f"self-test: {'PASS' if ok else 'FAIL'}")
    return ok, out


def main(argv: list[str]) -> int:
    ap = argparse.ArgumentParser(description="E43-D01 security centre audit")
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
        print(f"filled §10 in {SPEC_REL}")
        return 0
    if a.repin_ruled:
        hashes, bad = cite_hashes(t)
        if bad:
            print(f"refused: {bad[0]}")
            return 1
        head = "# E43-D01 cite pins: the cite, a hash of its cited line(s) at its base. Written by --repin-ruled only.\n"
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
