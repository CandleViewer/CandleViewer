#!/usr/bin/env python3
"""E34-D02 (#996) audit: the hi-fi spec of the trade-group ticket SCR-061, every state, with the
partial failure as its primary case.

Standalone and offline, shaped on the merged E38-D03 tool (`e38_d03_honesty_audit.py`): it imports
`packages/ui/tokens/tests/verify_tokens.py` (the token loader and resolver),
`docs/design/_tools/contrast_check.py` (`contrast_ratio`) and
`docs/research/_tools/cvd_simulate.py` (`simulate`, `delta_e76`; JND 5.0) from the working tree
and never re-implements them. It reads the spec and the pins file from the working tree and every
cited file AS TEXT with `git show` at the pinned base (`BASE`). Default-deny: a gate that cannot
read its input FAILs.

Gates (each FAIL led by its name):
  G-STATE     every state the catalogue, the ticket's Scope and the assignment name has a §0 frame
              row; each of the three acceptance criteria (AC-1 … AC-3) maps to frames §0 lists;
              the cover board opens on `SCR-061/partial-failure` (AC-2).
  G-TOKEN     every design token the spec names (`color.*`, `font.*`, `border.*`, `radius.*`,
              `type.*`, `space.*`, `size.*`, `motion.*`, `opacity.*`) is in a merged set.
  G-CONTRAST  every §8.1 row is recomputed per theme (dark, light, high-contrast as
              `verify_tokens` merges them) with `contrast_check.contrast_ratio` and equals the
              spec to two decimals; a `text` row is at least 4.5:1 and a `ui` row at least 3:1
              in every theme; the verdict cell matches its role and figures.
  G-CVD       every §8.2 row's normal / protanopia / deuteranopia / tritanopia ΔE76 equals the
              spec to two decimals, and its JND column names the simulations under 5.0.
  G-T2        every S061 state row whose Presentation quotes a T2 reason names its rendering
              (2a, 2b or the sentence form; G-T2.1c), and the reason is an E09-D09 key's text or
              a registered state string of E30-D02 at the base (its `{slot}` filled) unless the
              cell marks it PROPOSED. §1 item 7 names CMP-079 and the CMP-019 `lock`, and quotes
              G-T2.1b, G-T2.2 and G-T2.3 verbatim from `DS` at the base (`T2_QUOTES`); §8.1
              carries the G-T2.2 label pair (tertiary on raised).
  G-SAFETY    C-2.6: §1 states that no control turns the native stop off; no state row offers
              a stop as an option or leaves the SL cell empty or blank; the CMP-158 sentence and
              the never-empty SL cell are stated; every leg row of the B01 sketch carries its SL,
              and every accepted one its protection word.
  G-RECOVERY  §4.2 is the shared recovery table (RC-1 … RC-6: labels, confirms, never armed,
              available in every state, the cited tone); the B01 sketch and the rows use the
              labels in their scoped form; the retired words appear only on A- and C-rows; no
              row withholds a protective action, and the stop-pending, unknown, offline,
              lockout, frozen and view-as rows keep Unwind, Retry unwind and Cancel working
              orders enabled.
  G-RULED     OQ-1 is carried, not decided (the confirm names the whole position and what the
              group added); the Manager scope is stated (C-12.4); the Viewer's frame has no Send;
              §3.1 consumes E34-D03's CMP-258 and no status component is defined here; no
              client "N of M accepted / protected / unknown" count.
  G-COPY      every §11 row is verbatim with a cite whose line holds its fixed words, PROPOSED
              with an owner, or a request row to E34-D03's keys.
  G-D01       the unmerged E34-D01 (#936) and E34-D03 (#997), and any CMP id `15` lacks at the
              base, appear only on request rows or in a sentence naming a request row, never as a
              cite or by path.
  G-CITE      every cite in range and on a non-blank line at its base, and equal to the pins.
  G-HYGIENE   no closing keyword, local path, URL or host, agent name, double-brace slot or
              deny word in the spec; no deny word in this tool's text or the pins.
  G-SCOPE     the diff touches only the spec, this tool and the pins file.

Usage (from the repo root):
  python3 -I docs/design/_tools/e34_d02_hifi_audit.py --check
  python3 -I docs/design/_tools/e34_d02_hifi_audit.py --fill        (writes §8's figures)
  python3 -I docs/design/_tools/e34_d02_hifi_audit.py --self-test
  python3 -I docs/design/_tools/e34_d02_hifi_audit.py --repin-ruled (the pins' only writer)
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
SPEC_REL = "docs/design/E34/E34-D02.md"
TOOL_REL = "docs/design/_tools/e34_d02_hifi_audit.py"
PINS_REL = "docs/design/_tools/e34_d02_ruled_pins.txt"
OWN_PATHS = (SPEC_REL, TOOL_REL, PINS_REL)
BASE = "d023df0f66409807f2594ccd5086cd6d5017b16a"  # origin/main when written; re-pinned by content
TOKENS = ROOT / "packages" / "ui" / "tokens"
CVD_PATH = ROOT / "docs" / "research" / "_tools" / "cvd_simulate.py"
CONTRAST_PATH = ROOT / "docs" / "design" / "_tools" / "contrast_check.py"
PATHS: dict[str, str] = {
    "05": "docs/plan/05-accessibility-standard.md", "11": "docs/plan/11-user-stories.md",
    "14": "docs/plan/14-screens-catalogue.md", "15": "docs/plan/15-component-catalogue.md",
    "20": "docs/plan/20-architecture.md", "22": "docs/plan/22-api-openapi.yaml",
    "23": "docs/plan/23-ws-protocol.md", "24": "docs/plan/24-internal-schemas.md",
    "28": "docs/plan/28-statechart-catalogue.md",
    "ADR8": "docs/plan/27-adrs/ADR-0008-trade-group-fanout.md", "CON": "CONSTITUTION.md",
    "E09D09": "docs/design/E09/E09-D09.md", "E30D02": "docs/design/E30/E30-D02.md",
    "E30D03": "docs/design/E30/E30-D03.md", "E28D02": "docs/design/E28/E28-D02.md",
    "E28D03": "docs/design/E28/E28-D03.md", "DS": ".claude/rules/32-design-specs.md",
}  # fmt: skip
DASH = "–"  # the en dash of a line range, `14`:1504–1505
CITE = re.compile(
    r"`(\d\d|ADR8|CON|E09D09|E30D0[23]|E28D0[23]|DS)`:"
    rf"(\d+(?:{DASH}\d+)?(?:, :\d+(?:{DASH}\d+)?)*)"
)
TOKEN_NAME = re.compile(
    r"`((?:color|font|border|radius|type|space|size|motion|opacity)\.[a-z0-9.-]*[a-z0-9])`"
)
CLOSING = re.compile(r"\b(?:close[sd]?|fix(?:e[sd])?|resolve[sd]?)\s+#\d+", re.IGNORECASE)
# assembled, so this tool's own text carries none of the paths
LOCAL_PATH = re.compile("/" + "home/|/Us" + "ers/|/" + "tmp/|[A-Za-z]:\\\\|\\bnotes" + "/")
AGENT_NAME = re.compile(r"\b[a-z]{2,4}-worker-\d\b")
URL_OR_HOST = re.compile(r"https?://|penpot\.[a-z]|team-id=|file-id=", re.IGNORECASE)
# explicit joins, so this tool's own text carries none of the words
DENY = ("le" + "ak", "expo" + "sed", "by" + "pass", "ex" + "ploit", "att" + "ack", "ora" + "cle",
        "rev" + "eal", "unbou" + "nded", "flo" + "od", "st" + "all", "d" + "os", "advi" + "sory",
        "gh" + "sa", "pre-" + "auth")  # fmt: skip
THEMES = ("dark", "light", "high-contrast")
FLOOR = {"text": 4.5, "ui": 3.0}
DEFICIENCIES = ("protanopia", "deuteranopia", "tritanopia")
COVER = "SCR-061/partial-failure"
# the states the catalogue (`14` SCR-061), the ticket's Scope and the assignment name
REQUIRED_FRAMES = (COVER,) + tuple(f"SCR-061/{f}" for f in (
    "unwind-confirm", "partial-failure-demo", "unwinding", "unwind-incomplete", "sending",
    "rate-limit-backoff", "checking-outcome", "partial-fill", "done", "all-failed",
    "all-or-none-unwound", "stop-not-confirmed", "loading", "previewing", "ready", "sub-minimum",
    "override", "preview-failed", "empty", "blocked-lockout", "blocked-kill-switch", "viewer",
    "view-as", "live-not-enabled", "read-only-member",
))  # fmt: skip
ACS = ("AC-1", "AC-2", "AC-3")
FRAME = re.compile(r"`(SCR-\d{3}/[a-z0-9-]+)`")
UNMERGED = re.compile(r"E34-D01|#936|E34-D03|#997")
MEMO_PATH = re.compile(r"research/e34|fanout-partial-failure|`D01`:")
# a stop offered as an option, or the SCR-060 checkbox that implies one
STOP_OPTION = re.compile(
    r"without (?:a|its) stop|no stop\b|remove (?:the |its )?stop|stop off\b|opt[- ]out|"
    r"Attach SL|skip the stop",
    re.IGNORECASE,
)
RETIRED = re.compile(r"Flatten accepted|Retry failed|rollback|Flatten group|cancel-remaining")
# the one recovery table, E34-D03 §3.5 as it stands: RC row -> (trigger label, confirm label)
RC = {
    "RC-1": ("Retry {account}", "Retry {account} of group {id}"),
    "RC-2": ("Unwind {n} accepted legs", "Unwind {n} accepted legs of group {id}"),
    "RC-3": ("Retry unwind ({n} leg not flat)", "Retry unwind on {legs} of group {id}"),
    "RC-4": ("Close group", "Close {legs} of group {id}"),
    "RC-5": ("Cancel working orders ({n} leg)", "Cancel working orders on {legs} of group {id}"),
    "RC-6": ("Leave as is ({n} open)", ""),
}
SKETCH_LABELS = (r"\[ Retry sub_\d{3} \]", r"\[ Unwind \d+ accepted legs \]",
                 r"\[ Cancel working orders \(\d+ legs?\) \]", r"\[ Leave as is \(\d+ open\) \]")  # fmt: skip
PROTECTIVE = "Unwind, Retry unwind and Cancel working orders stay enabled"
THREATS = ("S061-14", "S061-15", "S061-37", "S061-32", "S061-34", "S061-38")
WITHHOLD = re.compile(
    r"(?:\bUnwind\b|Retry unwind|Cancel working orders)[^.;|]{0,40}?"
    r"\b(?:gated|withheld|waits?|hidden|disabled|not offered|unavailable)\b"
    r"|no (?:recovery|protective) action|\bactions wait\b"
)
SL_BLANK = re.compile(r"\bSL\b(?:(?!never)[^.;|]){0,20}\b(?:empty|blank)\b", re.IGNORECASE)
OWN_COMPONENT = re.compile(
    r"(?i)\b(?:new|own|second|another)\b[^|.;]{0,30}\b(?:status|state)\b[^|.;]{0,20}"
    r"\b(?:component|cell|badge)\b|\bdefined here\b"
)
COUNT = re.compile(
    r"(?:\b\d+|\{\w+\}) of (?:\d+|\{\w+\})(?: legs?)? (?:protected|accepted|unknown)\b"
)
TAG_LINE = re.compile(r"^\s*</?[A-Za-z][\w-]*>\s*$")
SAFETY_LINE = (
    "No control on SCR-061 turns the native stop off, and no frame shows a way to omit it."
)
OWN_CELL = "SCR-061 defines no status component of its own."
NOTICE = "Every order carries a stop-loss at the exchange. This cannot be turned off."


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


# ---------------------------------------------------------------------------- figures


def contrast_rows(t: Texts) -> list[list[str]]:
    return table_rows(section(t.spec, "### 8.1"), "P-")


def cvd_rows(t: Texts) -> list[list[str]]:
    return table_rows(section(t.spec, "### 8.2"), "V-")


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


def cvd_values(r: list[str]) -> tuple[str, str]:
    cv = mod("cvd_simulate")
    th = {"hc": "high-contrast"}.get(r[3], r[3])
    ha, hb = color(th, tok(r[1])), color(th, tok(r[2]))
    ds = [cv.delta_e76(ha, hb)] + [
        cv.delta_e76(cv.simulate(ha, d), cv.simulate(hb, d)) for d in DEFICIENCIES
    ]
    names = ("normal", *DEFICIENCIES)
    under = [n for n, d in zip(names, ds, strict=True) if d < cv.JND_FLOOR]
    return " / ".join(f"{d:.2f}" for d in ds), (", ".join(under) if under else "none")


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
    rows = [r for r in table_rows(zero, "B") if len(r) > 2 and re.fullmatch(r"B\d\d", r[0])]
    frames = {r[1].strip("`") for r in rows}
    for f in REQUIRED_FRAMES:
        if f not in frames:
            bad.append(f"no §0 frame row for `{f}`")
    if not rows or rows[0][1].strip("`") != COVER or "(cover)" not in rows[0][2]:
        bad.append(f"§0's first frame is not the cover `{COVER}` (AC-2)")
    acs = {r[0]: FRAME.findall(r[2]) for r in table_rows(zero, "AC-") if len(r) > 2}
    for ac in ACS:
        if not acs.get(ac):
            bad.append(f"{ac} maps to no frame in §0")
        for f in acs.get(ac, []):
            if f not in frames:
                bad.append(f"{ac} maps to `{f}`, which §0 does not list")
    for r in table_rows(t.spec, "S061-"):
        for f in FRAME.findall(" ".join(r)):
            if f not in frames:
                bad.append(f"{r[0]} names `{f}`, which §0 does not list")
    return bad


def g_token(t: Texts) -> list[str]:
    known = known_tokens()
    names = sorted(set(TOKEN_NAME.findall(t.spec)))
    return [
        f"`{n}` does not resolve in the token JSON at the base" for n in names if n not in known
    ]


def g_contrast(t: Texts) -> list[str]:
    bad = []
    rows = contrast_rows(t)
    if not rows:
        return ["§8.1 has no contrast rows"]
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
        return ["§8.2 has no CVD rows"]
    for r in rows:
        if len(r) != 6:
            bad.append(f"{r[0]}: {len(r)} cells, not 6")
            continue
        ds, under = cvd_values(r)
        if r[4] != ds or r[5] != under:
            bad.append(f"{r[0]}: reads {r[4]} / {r[5]}, the tool gives {ds} / {under}")
    return bad


def reason_templates(t: Texts) -> list[re.Pattern[str]]:
    """E09-D09 §3.1's key strings and E30-D02 §14's registered `lockout` / `frozen` strings."""
    lines = [ln for ln in at(t, "E09D09").split("\n") if ln.startswith("| `rbac.")]
    lines += [
        ln for ln in at(t, "E30D02").split("\n") if ln.startswith(("| `lockout`", "| `frozen`"))
    ]
    out = []
    for ln in lines:
        for q in re.findall(r'"([^"]{8,})"', ln):
            parts = re.split(r"\{[a-z_:]+\}", q)
            out.append(re.compile(".+?".join(re.escape(x) for x in parts) + "$"))
    return out


RENDERING = re.compile(r"rendering (2a|2b|the sentence form)")
T2_REASON = re.compile(r'T2 "([^"]{8,})"')
# G-T2.1b, G-T2.2 and G-T2.3 as `DS` words them (its `**` emphasis dropped); §1 item 7 quotes each
T2_QUOTES = (
    ("G-T2.1b", '`aria-disabled="true"`, never the `disabled` attribute — it stays in the Tab order and a menu item stays arrow-reachable'),
    ("G-T2.2", "hi-fi label `color.text.tertiary`, reason `color.text.secondary`; for primary / buy / sell actions the fill becomes `color.surface.raised` with a `color.border.default` hairline; never `color.text.disabled`, never `opacity.disabled` on the label, glyph or reason"),
    ("G-T2.3", "`Enter`, `Space` or a bound hotkey on a T2 control changes nothing and re-shows the reason inline with one polite announcement"),
)  # fmt: skip


def t2_quotes(t: Texts) -> list[str]:
    """G-T2.1b / 2 / 3: quoted from the owner, not paraphrased; the label pair measured."""
    bad = []
    owner = norm(at(t, "DS").replace("**", ""))
    one = norm(section(t.spec, "## 1."))
    for gid, q in T2_QUOTES:
        if norm(q) not in owner:
            bad.append(f"{gid}: the quote is no longer `DS`'s text at the base")
        elif f"{gid}, verbatim" not in one or norm(q) not in one:
            bad.append(f"§1 item 7 does not quote {gid} verbatim from `DS`")
    pairs = {(r[1], r[2]) for r in contrast_rows(t) if len(r) > 2}
    if ("`color.text.tertiary`", "`color.surface.raised`") not in pairs:
        bad.append("§8.1 has no `color.text.tertiary` on `color.surface.raised` pair (G-T2.2)")
    return bad


def g_t2(t: Texts) -> list[str]:
    bad = []
    rows = table_rows(t.spec, "S061-")
    if not rows:
        return ["the spec has no S061 state rows"]
    keys = reason_templates(t)
    gated = [r for r in rows if len(r) >= 5 and T2_REASON.search(r[4])]
    if not gated:
        bad.append("no S061 row carries a T2 reason")
    for r in gated:
        if not RENDERING.search(r[4]):
            bad.append(f"{r[0]}: a T2 control with no rendering (2a, 2b or the sentence form)")
        quote = T2_REASON.search(r[4])
        if quote and "PROPOSED" not in r[4] and not any(k.match(quote[1]) for k in keys):
            bad.append(f"{r[0]}: {quote[1]!r} is no E09-D09 key or registered state string")
    one = section(t.spec, "## 1.")
    if "CMP-019 `lock`" not in one or "CMP-079" not in one:
        bad.append("§1 item 7 does not name CMP-079 and the CMP-019 `lock` (G-T2.1d)")
    return bad + t2_quotes(t)


def g_safety(t: Texts) -> list[str]:
    bad = []
    if SAFETY_LINE not in section(t.spec, "## 1."):
        bad.append("§1 item 1 does not state that no control turns the native stop off")
    for r in table_rows(t.spec, "S061-"):
        if STOP_OPTION.search(" ".join(r)) or SL_BLANK.search(" ".join(r)):
            bad.append(f"{r[0]}: a state row offers the stop as an option or leaves it out")
    two = section(t.spec, "### 2.1")
    if f'"{NOTICE}"' not in two:
        bad.append("§2.1 does not carry the CMP-158 sentence verbatim")
    if "The SL cell is **never empty**" not in two:
        bad.append("§2.1 does not state the SL cell is never empty")
    legs = [ln for ln in sketch(t).split("\n") if re.match(r"\| (?:Main|sub_\d{3}) ", ln)]
    if len(legs) != 5:
        bad.append(f"§4.1: the B01 sketch draws {len(legs)} leg rows, not 5")
    for ln in legs:
        if not re.search(r"\(s\) [\d,.]+", ln):
            bad.append(f"B01 sketch: {ln[2:9].strip()} draws no SL")
        if "accepted" in ln and not re.search(r"protected|stop pending", ln):
            bad.append(f"B01 sketch: accepted {ln[2:9].strip()} has no protection word")
    return bad


def sketch(t: Texts) -> str:
    four1 = section(t.spec, "### 4.1")
    i = four1.find("```\n")
    return four1[i : four1.find("```", i + 4)] if i >= 0 else ""


def g_recovery(t: Texts) -> list[str]:
    bad = []
    four2 = section(t.spec, "### 4.2")
    rows = {r[0]: r for r in table_rows(four2, "RC-") if len(r) == 6}
    for rc, (trigger, confirm) in RC.items():
        r = rows.get(rc)
        if r is None or r[2] != f'"{trigger}"' or (confirm and f'"{confirm}"' not in r[3]):
            bad.append(f"{rc}: not the shared label {trigger!r} and its confirm")
        elif rc in ("RC-2", "RC-3", "RC-4", "RC-5") and (
            r[4] != "never" or "in every state" not in r[5]
        ):
            bad.append(f"{rc}: a protective action is armed or not available in every state")
    if "CMP-001 `danger`" not in four2 or "`15`:522" not in four2:
        bad.append("§4.2 does not state the one Confirm tone with its owner's cite")
    for rx in SKETCH_LABELS:
        if not re.search(rx, sketch(t)):
            bad.append(f"B01 sketch: no label in its scoped form /{rx}/")
    if not re.search(r"\*\*Retry unwind \(\d+ legs? not flat\)\*\*", " ".join(row(t, "S061-27"))):
        bad.append("S061-27: Retry unwind does not name its scope")
    for r in table_rows(t.spec, "S061-"):
        if any(WITHHOLD.search(c) for c in r[1:]):
            bad.append(f"{r[0]}: withholds or gates a protective action")
    if WITHHOLD.search(section(t.spec, "### 4.1")):
        bad.append("§4.1 withholds a protective action")
    for lead in THREATS:
        if PROTECTIVE not in " ".join(row(t, lead)):
            bad.append(f"{lead}: does not keep the protective actions enabled")
    checklist = set(section(t.spec, "### 10.1").split("\n"))  # `14`'s own item words, quoted
    for i, ln in enumerate(t.spec.split("\n"), 1):
        if ln in checklist and ln.startswith("| "):
            continue
        if RETIRED.search(ln) and not ln.startswith(("| C-", "- **A-")):
            bad.append(f"spec:{i} uses a retired recovery word outside an A- or C-row")
    return bad


def g_ruled(t: Texts) -> list[str]:
    """OQ-1 carried, never decided; the Manager scope; no Send for a Viewer."""
    bad = []
    four3 = section(t.spec, "### 4.3")
    if "This spec decides nothing about OQ-1" not in four3:
        bad.append("§4.3: OQ-1 is not carried as undecided")
    if "this group added" not in four3:
        bad.append("§4.3: the confirm does not name what the group added beside the position")
    oq1 = row(t, "OQ-1")
    if "until ruled" not in oq1[2]:
        bad.append("OQ-1: the row decides the question instead of carrying it")
    manager = "**Manager scope (C-12.4).**"
    if manager not in t.spec or "assigned accounts" not in t.spec.split(manager, 1)[-1][:200]:
        bad.append("§5: the Manager scope to assigned accounts is not stated (C-12.4)")
    if "no Send" not in row(t, "S061-33")[4]:
        bad.append("S061-33: the Viewer's frame offers a Send")
    three1 = section(t.spec, "### 3.1")
    if "CMP-258" not in three1 or OWN_CELL not in three1:
        bad.append("§3.1: the status cell is not E34-D03's shared CMP-258 (coordination ruling)")
    for i, ln in enumerate(t.spec.split("\n"), 1):
        if OWN_COMPONENT.search(ln) and not ln.startswith("| R-"):
            bad.append(f"spec:{i} defines a status component of SCR-061's own")
        if COUNT.search(ln):
            bad.append(f"spec:{i} counts legs in the client (G-7)")
    return bad


def g_copy(t: Texts) -> list[str]:
    bad = []
    rows = [r for r in table_rows(section(t.spec, "## 11."), "`") if len(r) == 3]
    if not rows:
        return ["§11 has no copy deck"]
    for r in rows:
        status = r[2]
        if "request row" in status or ("PROPOSED" in status and "owner" in status):
            continue
        cs = cites(status)
        if "verbatim" not in status or not cs:
            bad.append(f"copy {r[0]}: neither verbatim with a cite nor PROPOSED with an owner")
            continue
        key, a, b = cs[0]
        text = norm(" ".join(at(t, key).split("\n")[a - 1 : b])).lower()
        for w in re.split(r"\{[a-z_:]+\}", r[1].strip('"')):
            if w.strip(" .:,") and norm(w).lower().strip(" ,") not in text:
                bad.append(f"copy {r[0]}: {w.strip()!r} is not in {key}:{a}")
    return bad


def g_d01(t: Texts) -> list[str]:
    bad = []
    merged = set(re.findall(r"^### (CMP-\d{3})\b", at(t, "15"), re.MULTILINE))
    for i, ln in enumerate(t.spec.split("\n"), 1):
        on_request = ln.startswith("| R-") or "request row" in ln
        if UNMERGED.search(ln) and not on_request:
            bad.append(f"spec:{i} leans on unmerged research or design outside a request row")
        for cmp_id in sorted(set(re.findall(r"CMP-\d{3}", ln)) - merged):
            if not on_request:
                bad.append(f"spec:{i} names {cmp_id}, not in `15` at the base, off a request row")
        if MEMO_PATH.search(ln):
            bad.append(f"spec:{i} cites the unmerged E34-D01 memo by path or line")
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
        (CLOSING, "a closing keyword (PR 2 alone closes #996)"),
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
        if TAG_LINE.match(ln):
            bad.append(f"spec:{i} is a markup tag line")
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


GATES: dict[str, Callable[[Texts], list[str]]] = {
    "G-STATE": g_state,
    "G-TOKEN": g_token,
    "G-CONTRAST": g_contrast,
    "G-CVD": g_cvd,
    "G-T2": g_t2,
    "G-SAFETY": g_safety,
    "G-RECOVERY": g_recovery,
    "G-RULED": g_ruled,
    "G-COPY": g_copy,
    "G-D01": g_d01,
    "G-CITE": g_cite,
    "G-HYGIENE": g_hygiene,
    "G-SCOPE": g_scope,
}


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
        elif ln.startswith("| V-") and len(c) == 6:
            c[4], c[5] = cvd_values(c)
            ln = "| " + " | ".join(c) + " |"
        out.append(ln)
    return "\n".join(out)


Mutation = Callable[[Texts], Texts]


def sub(old: str, new: str) -> Mutation:
    def f(t: Texts) -> Texts:
        if t.spec.count(old) != 1:
            raise SystemExit(f"self-test: the spec carries {old[:50]!r} {t.spec.count(old)} times")
        return replace(t, spec=t.spec.replace(old, new))

    return f


def set_cell(lead: str, col: int, value: str) -> Mutation:
    def f(t: Texts) -> Texts:
        ls = t.spec.split("\n")
        i = next(k for k, ln in enumerate(ls) if ln.startswith(f"| {lead} "))
        c = cells(ls[i])
        c[col] = value
        ls[i] = "| " + " | ".join(c) + " |"
        return replace(t, spec="\n".join(ls))

    return f


def drop_row(lead: str) -> Mutation:
    def f(t: Texts) -> Texts:
        kept = (ln for ln in t.spec.split("\n") if not ln.startswith(lead))
        return replace(t, spec="\n".join(kept))

    return f


def swap_rows(a: str, b: str) -> Mutation:
    def f(t: Texts) -> Texts:
        ls = t.spec.split("\n")
        i = next(k for k, ln in enumerate(ls) if ln.startswith(a))
        j = next(k for k, ln in enumerate(ls) if ln.startswith(b))
        ls[i], ls[j] = ls[j], ls[i]
        return replace(t, spec="\n".join(ls))

    return f


MUTATIONS: tuple[tuple[str, str, Mutation], ...] = (
    ("G-STATE", "drop the backoff frame row", drop_row("| B07 ")),
    ("G-STATE", "drop the AC-3 mapping", drop_row("| AC-3 ")),
    ("G-STATE", "move the cover off the partial failure", swap_rows("| B01 ", "| B02 ")),
    ("G-TOKEN", "misspell a status token", sub("skipped word `color.text.secondary`", "skipped word `color.text.secundary`")),
    ("G-CONTRAST", "type a contrast figure off", set_cell("P-01", 4, "1.00")),
    ("G-CONTRAST", "report a ui pair as structure", set_cell("P-05", 3, "structure")),
    ("G-CVD", "type a ΔE figure off", set_cell("V-01", 4, "1.00 / 1.00 / 1.00 / 1.00")),
    ("G-T2", "drop the view-as rendering", set_cell("S061-34", 4, f'T2 "Read-only while viewing as alex." (`rbac.view_as`); {PROTECTIVE} (the C-2.6 carve-out)')),
    ("G-T2", "retype a key's text", sub("T2 \"Live trading isn't enabled for you.\"", 'T2 "Live trading is off for you."')),
    ("G-T2", "drop the lock from §1 item 7", sub("led by the CMP-019 `lock` glyph", "led by its glyph")),
    ("G-T2", "let a T2 control leave the Tab order (G-T2.1b)", sub("never the `disabled` attribute — it stays in the Tab order", "or the `disabled` attribute")),
    ("G-T2", "dim a T2 label with the disabled tokens (G-T2.2)", sub("never `color.text.disabled`, never `opacity.disabled` on", "dimmed with `opacity.disabled` on")),
    ("G-T2", "make a T2 press act (G-T2.3)", sub("changes nothing and re-shows the reason inline with one polite announcement", "acts")),
    ("G-T2", "drop the tertiary label pair from §8.1 (G-T2.2)", drop_row("| P-08 ")),
    ("G-SAFETY", "drop the no-control statement", sub(SAFETY_LINE, "The stop is attached.")),
    ("G-SAFETY", "offer the stop as an option on a row", set_cell("S061-05", 4, "E28-D03 S61-2; the totals line; Send enabled; an Attach SL checkbox per row")),
    ("G-SAFETY", "paraphrase the CMP-158 sentence", sub(f'"{NOTICE}" (`E28D02`:587). `role', '"Orders carry stops." (`E28D02`:587). `role')),
    ("G-SAFETY", "drop sub_001's protection word in the sketch", sub("filled 0.100 of 0.100  | protected", "filled 0.100 of 0.100  | —")),
    ("G-SAFETY", "blank sub_001's SL cell in the sketch", sub("| sub_001  [LIVE]  | 0.100 | (s) 63,900.0 |", "| sub_001  [LIVE]  | 0.100 |              |")),
    ("G-SAFETY", "leave the partial-fill row's SL cell empty", set_cell("S061-16", 3, 'an accepted row "accepted — filled 0.040 of 0.080", protected, its SL cell empty')),
    ("G-SAFETY", "blank the ready row's SL", set_cell("S061-05", 4, "E28-D03 S61-2; the totals line; Send enabled; the SL blank where the profile sets none")),
    ("G-RECOVERY", "label Unwind without its scope", set_cell("RC-2", 2, '"Unwind"')),
    ("G-RECOVERY", "label Leave as is without its count", sub("[ Leave as is (3 open) ]", "[ Leave as is ]")),
    ("G-RECOVERY", "write Cancel remaining in the sketch", sub("[ Cancel working orders (1 leg) ]", "[ Cancel remaining (1 leg) ]")),
    ("G-RECOVERY", "rename Cancel working orders in the table", set_cell("RC-5", 2, '"Cancel open orders ({n} leg)"')),
    ("G-RECOVERY", "make the actions wait on a pending stop", sub("Leave as is waits, and " + PROTECTIVE, "the actions wait")),
    ("G-RECOVERY", "ask Unwind for the arm", set_cell("RC-2", 4, "on LIVE (a submit)")),
    ("G-RECOVERY", "gate Unwind under the kill switch", set_cell("S061-32", 4, 'T2 "Trading frozen by the owner at 14:02 UTC — new orders off. Cancel and close still work." (`frozen`, `E30D02`:422); rendering 2a; Unwind gated too')),
    ("G-RECOVERY", "bring back a retired word", sub("**Never offered:** a control", "**Never offered:** Flatten accepted, a control")),
    ("G-RULED", "decide OQ-1 in §4.3", sub("**This spec decides nothing about OQ-1**", "**This spec closes only what the leg added**")),
    ("G-RULED", "drop the Manager scope", sub("**Manager scope (C-12.4).**", "**Scope.**")),
    ("G-RULED", "give the Viewer a Send", sub("rendering the sentence form, CMP-026 with `cta` omitted; no Send", "rendering the sentence form, CMP-026 with `cta` omitted; Send shown")),
    ("G-D01", "lean on E34-D01 outside a request row", sub("**Rows:** `size.row.compact`", "**Rows (E34-D01 P-1):** `size.row.compact`")),
    ("G-D01", "name the unmerged CMP-258 off a request row", sub(" in E34-D03 §5.3 (a request row, R-7), drawn", ", drawn")),
    ("G-RULED", "define a row-status cell of SCR-061's own", sub(OWN_CELL, "SCR-061 defines its own status cell.")),
    ("G-RULED", "define a second status component, no CMP id", sub("No summary counts legs in the client (§1 item 10).", "SendRowStatus, a status component, is defined here.")),
    ("G-RULED", "count protection in the client", set_cell("S061-17", 3, '"5 of 5 accepted. All 5 are protected by a native stop."')),
    ("G-COPY", "drop a PROPOSED string's owner", set_cell("`preview.failed`", 2, "PROPOSED")),
    ("G-COPY", "claim a string verbatim that the line lacks", set_cell("`refusal.frozen`", 1, '"Trading paused by the owner"')),
    ("G-D01", "cite the memo by path", sub("Only these words appear on SCR-061,", "Only these words appear on SCR-061 (research/e34 memo),")),
    ("G-CITE", "re-point a `14` cite to an unpinned line", sub("(`14`:1503) and, in a dialog", "(`14`:1502) and, in a dialog")),
    ("G-HYGIENE", "write a closing keyword against #996", sub("carries the closing line.", "carries the closing line. Closes #996.")),
    ("G-HYGIENE", "close the file with a tag line", lambda t: replace(t, spec=t.spec + "</content>\n")),
    ("G-HYGIENE", "put a deny word into the tool's own text", lambda t: replace(t, tool=t.tool + "\n# " + DENY[6] + "\n")),
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
        mark = "ok  " if good else "FAIL"
        out.append(f"{mark} M-{i} {gate}: {what} -> {', '.join(gates) or 'none'}")
    restored = load().spec == before
    ok &= restored
    out.append(
        f"self-test: {len(MUTATIONS)} mutations, text restored: {'yes' if restored else 'NO'}"
    )
    out.append(f"self-test: {'PASS' if ok else 'FAIL'}")
    return ok, out


def main(argv: list[str]) -> int:
    ap = argparse.ArgumentParser(description="E34-D02 trade-group ticket hi-fi audit")
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
        head = "# E34-D02 cite pins: the cite, a hash of its cited line(s) at its base.\n"
        head += "# Written by --repin-ruled only.\n"
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
