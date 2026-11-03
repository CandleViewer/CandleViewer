#!/usr/bin/env python3
"""E34-D03 (#997) audit: the hi-fi spec of the trade-group manager SCR-062 (open groups and their
legs) and the design-system and motion work SCR-061 and SCR-062 share.

Standalone and offline, shaped on the merged E38-D03 tool: it imports `verify_tokens`,
`contrast_check` (`contrast_ratio`) and `cvd_simulate` (`simulate`, `delta_e76`; JND 5.0) and never
re-implements them. It reads every cited file AS TEXT with `git show` at the pinned base (`BASE`);
the unmerged E34-D01 and E34-D02 are never read. Default-deny: a gate that cannot read its input FAILs.

Gates (each FAIL led by its name; spec §12):
  G-STATE     §0 frames for the Scope; AC-1 … AC-4 mapped to listed frames; insets are state rows.
  G-TOKEN     every token the spec names is in a merged set.
  G-CONTRAST  §8.1 recomputed per theme with `contrast_ratio`, at its floor, its verdict matching.
  G-CVD       §8.2 ΔE76 per simulation recomputed, its JND column matching.
  G-SAFETY    C-2.6: never omittable (§1); Protection from `native_sl_confirmed`; no state row, §5
              row or copy string offers a leg without its stop; Retry's preview line carries it;
              the closing copy keeps each stop; OQ-1 open with the whole-position copy.
  G-T2        T2 rows name a rendering and quote an E09-D09 key or registered state; §1 item 6
              names the `lock` and quotes G-T2.1b / 2 / 3 verbatim from `DS`; the label pair.
  G-MOTION    a reduced-motion twin per §6 row; terminal changes and the summary are cuts.
  G-COPY      every §7 row verbatim with a cite holding its fixed words, or PROPOSED with an owner.
  G-VOCAB     no retired word ("Flatten", "Cancel group", …) quoted in §3, §4 or §7 rows.
  G-RECOVERY  §3.5 RC-1 … RC-6 carry the one set of labels and confirms; the protective rows are
              never armed and available in every state; the tone is cited; state rows use them.
  G-PROTECT   no state row withholds Unwind, Retry unwind, Close group or Cancel working orders;
              the unknown, stop-pending, lockout, frozen, view-as and offline rows keep them.
  G-CMP258    §5.3 covers every leg state (words, built glyph, tokens) and the group states; every
              `icon/…` is built at the base; no status component is defined outside §5.
  G-COUNT     no client "N of M protected / accepted / unknown" count; G-12 records the gap.
  G-MERGED    E34-D01 (#936) and E34-D02 (#996) only on a request row, never by line.
  G-CITE      every cite in range, on a non-blank line at its base, and equal to the pins.
  G-HYGIENE   no closing keyword, local path, URL or host, agent name, double brace, tag-only line
              or deny word in the spec; no deny word or local path in the tool or the pins.
  G-SCOPE     the diff touches only the spec, this tool and the pins file.

Usage (from the repo root):
  python3 -I docs/design/_tools/e34_d03_manager_audit.py --check
  python3 -I docs/design/_tools/e34_d03_manager_audit.py --fill        (writes §8's figures)
  python3 -I docs/design/_tools/e34_d03_manager_audit.py --self-test
  python3 -I docs/design/_tools/e34_d03_manager_audit.py --repin-ruled (the pins' only writer)
"""

from __future__ import annotations

import argparse
import hashlib
import importlib.util
import re
import shutil
import subprocess
import sys
from collections.abc import Callable
from dataclasses import dataclass, replace
from pathlib import Path
from types import ModuleType
from typing import Any

ROOT = Path(__file__).resolve().parents[3]
GIT = shutil.which("git") or "git"
SPEC_REL = "docs/design/E34/E34-D03.md"
TOOL_REL = "docs/design/_tools/e34_d03_manager_audit.py"
PINS_REL = "docs/design/_tools/e34_d03_ruled_pins.txt"
OWN_PATHS = (SPEC_REL, TOOL_REL, PINS_REL)
BASE = "d023df0f66409807f2594ccd5086cd6d5017b16a"  # origin/main when written; re-pinned by content
TOKENS = ROOT / "packages" / "ui" / "tokens"
CVD_PATH = ROOT / "docs" / "research" / "_tools" / "cvd_simulate.py"
CONTRAST_PATH = ROOT / "docs" / "design" / "_tools" / "contrast_check.py"
PATHS: dict[str, str] = {
    "05": "docs/plan/05-accessibility-standard.md", "11": "docs/plan/11-user-stories.md",
    "14": "docs/plan/14-screens-catalogue.md", "15": "docs/plan/15-component-catalogue.md",
    "16": "docs/plan/16-design-system-brief.md", "20": "docs/plan/20-architecture.md",
    "22": "docs/plan/22-api-openapi.yaml", "23": "docs/plan/23-ws-protocol.md",
    "24": "docs/plan/24-internal-schemas.md", "28": "docs/plan/28-statechart-catalogue.md",
    "ADR8": "docs/plan/27-adrs/ADR-0008-trade-group-fanout.md",
    "E09D09": "docs/design/E09/E09-D09.md", "E30D02": "docs/design/E30/E30-D02.md",
    "E30D04": "docs/design/E30/E30-D04.md", "E28D03": "docs/design/E28/E28-D03.md",
    "E39D03": "docs/design/E39/E39-D03.md", "DS": ".claude/rules/32-design-specs.md",
}  # fmt: skip
DASH = "\u2013"  # the en dash of a cite range in the spec
CITE = re.compile(r"`(\d\d|ADR8|E09D09|E30D0[24]|E28D03|E39D03|DS)`:(\d+(?:\u2013\d+)?(?:, :\d+(?:\u2013\d+)?)*)")  # fmt: skip
TOKEN_NAME = re.compile(r"`((?:color|font|border|radius|type|space|size|motion|opacity)\.[a-z0-9.-]*[a-z0-9])`")  # fmt: skip
CLOSING = re.compile(r"\b(?:close[sd]?|fix(?:e[sd])?|resolve[sd]?)\s+#\d+", re.IGNORECASE)
# assembled, so this tool's own text carries none of the paths
LOCAL_PATH = re.compile("/" + "home/|/" + "tmp/|/Us" + "ers/|[A-Za-z]:\\\\|\\bnotes" + "/|\\bwt-" + "notes\\b")  # fmt: skip
AGENT_NAME = re.compile(r"\b[a-z]{2,4}-worker-\d\b")
URL_OR_HOST = re.compile(r"https?://|penpot\.[a-z]|team-id=|file-id=", re.IGNORECASE)
# explicit joins, so this tool's own text carries none of the words
DENY = ("le" + "ak", "expo" + "sed", "by" + "pass", "ex" + "ploit", "att" + "ack", "ora" + "cle",
        "rev" + "eal", "unbou" + "nded", "flo" + "od", "st" + "all", "d" + "os", "advi" + "sory",
        "gh" + "sa", "pre-" + "auth")  # fmt: skip
THEMES = ("dark", "light", "high-contrast")
FLOOR = {"text": 4.5, "ui": 3.0}
DEFICIENCIES = ("protanopia", "deuteranopia", "tritanopia")
# the frames the ticket's Scope, its AC and the `14` checklist name; each needs a §0 row
_FRAMES = (
    "list", "group-expanded", "group-detail", "submitting", "partial-fill", "partial-failure",
    "unwinding", "unwind-incomplete", "checking-outcome", "rate-wait", "stop-pending", "leg-unknown",
    "divergent", "confirm-close-group", "confirm-close-half", "close-result-partial",
    "confirm-cancel-working", "confirm-unwind", "confirm-retry", "empty", "loading", "error",
    "viewer-read-only", "manager-scope", "lockout-frozen",
)  # fmt: skip
REQUIRED_FRAMES = tuple(f"SCR-062/{f}" for f in _FRAMES) + tuple(
    f"DS/{f}" for f in ("cmp-124-summary", "cmp-232-budget", "cmp-258-leg-status", "scope-confirm",
                        "motion-twins")
)  # fmt: skip
ACS = ("AC-1", "AC-2", "AC-3", "AC-4")
FRAME = re.compile(r"`((?:SCR-\d{3}|DS)/[a-z0-9-]+)`")
UNMERGED = re.compile(r"E34-D0[12]|#936|#996")
NO_STOP = re.compile(r"without (?:a |its |the )?stop|no stop\b|skip(?:ping)? the stop|remove the stop|turn(?:s|ing)? off the stop|stop is optional|optional stop|omit", re.IGNORECASE,)  # fmt: skip
RETIRED = re.compile(r"flatten|cancel group|rollback|retry failed", re.IGNORECASE)
QUOTE = re.compile(r'"([^"]{6,})"')
TAG_LINE = re.compile(r"^\s*</?[A-Za-z][\w-]*>\s*$")
ICON = re.compile(r"`icon/([a-z0-9-]+)`")
COUNT = re.compile(r"(?:\b\d+|\{\w+\}) of (?:\d+|\{\w+\})(?: legs?)? (?:protected|accepted|unknown)\b")  # fmt: skip
PROTECTIVE = "Unwind, Retry unwind, Close group and Cancel working orders stay enabled"
WITHHOLD = re.compile(r"(?:\bUnwind\b|Retry unwind|Close group|Cancel working orders)[^.;|]{0,40}?\b(?:gated|withheld|waits?|hidden|disabled|not offered|unavailable)\b|no (?:recovery|protective) action")  # fmt: skip
# the rows where a leg may be unprotected and something else might tempt a gate
THREATS = ("M62-09", "M62-11", "M62-18", "M62-25", "M62-27", "M62-30")
OWN_COMPONENT = re.compile(r"(?i)\b(?:new|own|second|another)\b[^|.;]{0,30}\b(?:status|state)\b[^|.;]{0,20}\b(?:component|cell|badge)\b|\bdefined here\b")  # fmt: skip
LEG_WORDS = ("queued", "sent", "accepted", "rejected", "cancelled", "checking outcome",
             "state unknown for", "waiting for rate budget", "unwinding", "flat",
             "closed: stop not confirmed", "divergent", "skipped", "protected", "stop pending")  # fmt: skip
# RC row: (trigger label, confirm label), the one recovery table of §3.5
RC = {
    "RC-1": ("Retry {account}", "Retry {account} of group {id}"),
    "RC-2": ("Unwind {n} accepted legs", "Unwind {n} accepted legs of group {id}"),
    "RC-3": ("Retry unwind ({n} leg not flat)", "Retry unwind on {legs} of group {id}"),
    "RC-4": ("Close group", "Close {legs} of group {id}"),
    "RC-5": ("Cancel working orders ({n} leg)", "Cancel working orders on {legs} of group {id}"),
    "RC-6": ("Leave as is ({n} open)", ""),
}
INSTANCES = (
    ("M62-06", (r"Retry sub_\d{3}\b", r"Unwind \d+ accepted legs", r"Leave as is \(\d+ open\)",
                r"Cancel working orders \(\d+ legs?\)")),
    ("M62-08", (r"Retry unwind \(\d+ legs? not flat\)",)),
    ("M62-17", (r"Unwind \d+ accepted legs of group tg_\d{4}",)),
    ("M62-29", (r"Retry sub_\d{3} of group tg_\d{4}",)),
)  # fmt: skip


@dataclass(frozen=True)
class Texts:
    spec: str
    pins: str
    tool: str
    changed: list[str] | None
    memo: dict[str, str | None]


def git(*args: str) -> str | None:
    try:
        # a fixed git argv, no shell and no outside input: the paths are this repo's own
        r = subprocess.run([GIT, "-C", str(ROOT), *args], capture_output=True, check=False)
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


def cells(line: str) -> list[str]:
    return [c.strip() for c in line.strip().strip("|").split("|")]


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


def state_rows(t: Texts) -> list[list[str]]:
    return table_rows(t.spec, "M62-")


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


def g_state(t: Texts) -> list[str]:
    bad = []
    zero = section(t.spec, "## 0.")
    frames = {r[1].strip("`") for r in table_rows(zero, "B") if len(r) > 1}
    for f in REQUIRED_FRAMES:
        if f not in frames:
            bad.append(f"no §0 frame row for `{f}`")
    acs = {r[0]: FRAME.findall(r[2]) for r in table_rows(zero, "AC-") if len(r) > 2}
    for ac in ACS:
        if not acs.get(ac):
            bad.append(f"{ac} maps to no frame in §0")
        for f in acs.get(ac, []):
            if f not in frames:
                bad.append(f"{ac} maps to `{f}`, which §0 does not list")
    ids = {r[0] for r in state_rows(t)}
    insets = re.search(r"\*\*Insets \(R4.*", zero)
    if not insets:
        bad.append("§0 names no insets paragraph (R4)")
    else:
        for i in re.findall(r"M62-\d\d", insets[0]):
            if i not in ids:
                bad.append(f"the inset {i} is no state row")
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


def copy_rows(t: Texts) -> list[list[str]]:
    return [r for r in table_rows(section(t.spec, "## 7."), "`") if len(r) == 3]


def g_safety(t: Texts) -> list[str]:
    """C-2.6: the stop is a statement on every leg, never a choice."""
    bad = []
    one = norm(section(t.spec, "## 1."))
    if "never offers a way to omit, remove or turn off the stop" not in one:
        bad.append("§1 item 1 does not state that no surface offers to omit the stop")
    grid = section(t.spec, "### 2.1")
    prot = [r for r in table_rows(grid, "Protection") if len(r) > 2]
    if not prot or "native_sl_confirmed" not in " ".join(prot[0]):
        bad.append("§2.1 has no Protection column read from `native_sl_confirmed`")
    for r in state_rows(t):
        for c in r[2:]:
            if NO_STOP.search(c):
                bad.append(f"{r[0]}: offers or implies a leg without its stop")
    for r in copy_rows(t):
        if NO_STOP.search(r[1]):
            bad.append(f"copy {r[0]}: offers or implies a leg without its stop")
    for r in table_rows(section(t.spec, "## 5."), ""):
        if NO_STOP.search(" ".join(r)):
            bad.append(f"§5 row {r[0]}: offers or implies a leg without its stop")
    retry = [r for r in state_rows(t) if r[0] == "M62-29"]
    if not retry or not re.search(r"stop [\d,.]+ at the exchange", retry[0][2]):
        bad.append("M62-29: Retry's re-run preview line does not carry the leg's stop")
    keys = {r[0]: r[1] for r in copy_rows(t)}
    if "stop-loss stays" not in keys.get("`close.stop_line`", ""):
        bad.append("copy `close.stop_line` does not keep each stop until flat")
    if "stop-loss" not in keys.get("`cancel.effect`", ""):
        bad.append("copy `cancel.effect` does not say every stop-loss stays")
    if "whole" not in keys.get("`unwind.account`", ""):
        bad.append("copy `unwind.account` does not name the account's whole position (OQ-1)")
    oq1 = row(t, "OQ-1")
    if "open" not in oq1[2] or "whole" not in oq1[2]:
        bad.append("OQ-1 is not kept open with the whole-position copy")
    return bad


def templates(t: Texts, key: str) -> list[re.Pattern[str]]:
    out = []
    for ln in at(t, key).split("\n"):
        if ln.startswith("| `"):
            for q in re.findall(r'"([^"]{8,})"', ln):
                parts = re.split(r"\{[a-z_:]+\}", q)
                out.append(re.compile(".+?".join(re.escape(x) for x in parts) + "$"))
    return out


RENDERING = re.compile(r"rendering (2a|2b|the sentence form)")
# G-T2.1b, G-T2.2 and G-T2.3 as `DS` words them (its `**` emphasis dropped); §1 item 6 quotes each
T2_QUOTES = (
    ("G-T2.1b", '`aria-disabled="true"`, never the `disabled` attribute — it stays in the Tab order and a menu item stays arrow-reachable'),
    ("G-T2.2", "hi-fi label `color.text.tertiary`, reason `color.text.secondary`; for primary / buy / sell actions the fill becomes `color.surface.raised` with a `color.border.default` hairline; never `color.text.disabled`, never `opacity.disabled` on the label, glyph or reason"),
    ("G-T2.3", "`Enter`, `Space` or a bound hotkey on a T2 control changes nothing and re-shows the reason inline with one polite announcement"),
)  # fmt: skip


def g_t2(t: Texts) -> list[str]:
    bad = []
    rows = [r for r in state_rows(t) if len(r) >= 4 and "T2" in r[3]]
    if not rows:
        return ["the spec has no T2 state rows"]
    keys = templates(t, "E09D09") + templates(t, "E30D02")
    for r in rows:
        if not RENDERING.search(r[3]):
            bad.append(f"{r[0]}: a T2 control with no rendering (2a, 2b or the sentence form)")
        quotes = QUOTE.findall(r[3])
        if not quotes:
            bad.append(f"{r[0]}: a T2 presentation with no quoted reason")
        for q in quotes:
            if "PROPOSED" not in r[3] and not any(k.match(q) for k in keys):
                bad.append(f"{r[0]}: {q!r} is no E09-D09 key's or registered state's text")
    one = section(t.spec, "## 1.")
    if "CMP-019 `lock`" not in one:
        bad.append("§1 item 6 does not state the CMP-019 `lock` glyph that leads a T2 label")
    owner = norm(at(t, "DS").replace("**", ""))
    item = norm(one)
    for gid, q in T2_QUOTES:
        if norm(q) not in owner:
            bad.append(f"{gid}: the quote is no longer `DS`'s text at the base")
        elif f"{gid}, verbatim" not in item or norm(q) not in item:
            bad.append(f"§1 item 6 does not quote {gid} verbatim from `DS`")
    pairs = {(r[1], r[2]) for r in contrast_rows(t) if len(r) > 2}
    if ("`color.text.tertiary`", "`color.surface.raised`") not in pairs:
        bad.append("§8.1 has no `color.text.tertiary` on `color.surface.raised` pair (G-T2.2)")
    return bad


def g_motion(t: Texts) -> list[str]:
    bad = []
    six = section(t.spec, "## 6.")
    rows = table_rows(six, "MO-")
    if not rows:
        return ["§6 has no motion rows"]
    for r in rows:
        if len(r) != 4 or not r[3] or r[3] in ("—", "-", "none"):
            bad.append(f"{r[0]}: no reduced-motion equivalent")
    by = {r[0]: r for r in rows}
    for lead, what in (("MO-2", "the terminal leg change"), ("MO-3", "the summary's entrance")):
        cut = by.get(lead)
        if not cut or not cut[2].startswith("a cut"):
            bad.append(f"{lead}: {what} is not a cut")
    if "summary" not in " ".join(by.get("MO-2", [])):
        bad.append("MO-2: the row does not say the summary keeps the eye")
    r5 = by.get("MO-5")
    if not r5 or "text swap" not in r5[2]:
        bad.append("MO-5: the countdown is not a text swap")
    if "**Never animates:**" not in six:
        bad.append("§6 has no Never animates list")
    return bad


def g_copy(t: Texts) -> list[str]:
    bad = []
    rows = copy_rows(t)
    if not rows:
        return ["§7 has no copy rows"]
    for r in rows:
        status = r[2]
        if "PROPOSED" in status:
            if "owner" not in status:
                bad.append(f"copy {r[0]}: PROPOSED with no owner")
            continue
        if "verbatim" not in status:
            bad.append(f"copy {r[0]}: neither verbatim with a cite nor PROPOSED with an owner")
            continue
        cs = cites(status)
        if not cs:
            bad.append(f"copy {r[0]}: verbatim with no cite")
            continue
        key, a, b = cs[0]
        text = norm(" ".join(at(t, key).split("\n")[a - 1 : b])).lower()
        words = [w for w in re.split(r"\{[a-z_:]+\}", r[1].strip('"')) if w.strip(" .:")]
        for w in words:
            if norm(w).lower().strip() not in text:
                bad.append(f"copy {r[0]}: {w.strip()!r} is not in {key}:{a}")
    return bad


def g_vocab(t: Texts) -> list[str]:
    bad = []
    for head in ("## 3.", "## 4.", "## 7."):
        for ln in section(t.spec, head).split("\n"):
            if not ln.startswith("| "):
                continue
            for q in QUOTE.findall(ln):
                if RETIRED.search(q):
                    bad.append(f"{head} row {cells(ln)[0]}: quotes the retired word in {q!r}")
    return bad


def g_recovery(t: Texts) -> list[str]:
    """One recovery table (§3.5), its labels used as they stand."""
    bad = []
    five = section(t.spec, "### 3.5")
    rows = {r[0]: r for r in table_rows(five, "RC-") if len(r) == 6}
    for rc, (trigger, confirm) in RC.items():
        r = rows.get(rc)
        if r is None:
            bad.append(f"§3.5 has no {rc} row")
            continue
        if r[2] != f'"{trigger}"':
            bad.append(f"{rc}: the trigger label is not {trigger!r}")
        if confirm and f'"{confirm}"' not in r[3]:
            bad.append(f"{rc}: the confirm label is not {confirm!r}")
        if rc in ("RC-2", "RC-3", "RC-4", "RC-5") and (
            r[4] != "never" or "in every state" not in r[5]
        ):
            bad.append(f"{rc}: a protective action is armed or not available in every state")
    if "CMP-001 `danger`" not in five or "`15`:522" not in five:
        bad.append("§3.5 does not state the one Confirm tone with its owner's cite")
    for lead, rxs in INSTANCES:
        text = " ".join(" ".join(r) for r in state_rows(t) if r[0] == lead)
        for rx in rxs:
            if not re.search(rx, text):
                bad.append(f"{lead}: no label in §3.5's scoped form /{rx}/")
    return bad


def g_protect(t: Texts) -> list[str]:
    """C-2.6 / C-2.21: the protective actions are never hidden or blocked."""
    bad = []
    for r in state_rows(t):
        if any(WITHHOLD.search(c) for c in r[1:]):
            bad.append(f"{r[0]}: withholds or gates a protective action")
    for lead in THREATS:
        if not any(PROTECTIVE in " ".join(r) for r in state_rows(t) if r[0] == lead):
            bad.append(f"{lead}: does not keep the protective actions enabled")
    if "the kill switch, `lockout`, `frozen` and view-as never do" not in norm(
        section(t.spec, "### 3.4")
    ):
        bad.append("§3.4 does not say the kill switch, lockout, frozen and view-as never gate them")
    return bad


def built_glyphs() -> set[str] | None:
    out = git("ls-tree", "-r", "--name-only", BASE, "packages/ui/src/icons/source")
    if out is None:
        return None
    return {Path(p).name.split(".")[0] for p in out.split("\n") if p.endswith(".svg")}


def g_cmp258(t: Texts) -> list[str]:
    """CMP-258 defined once and completely, with built glyphs only."""
    bad = []
    five3 = section(t.spec, "### 5.3")
    legs = [r for r in table_rows(five3, "LS-") if len(r) == 6]
    groups = [r for r in table_rows(five3, "GS-") if len(r) == 6]
    words = " ".join(r[3] for r in legs)
    bad += [f"§5.3 has no leg state {w!r}" for w in LEG_WORDS if f'"{w}' not in words]
    if not groups:
        bad.append("§5.3 has no group states")
    for r in legs + groups:
        if '"' not in r[3] or "`color." not in r[5] or not (r[4] == "none" or ICON.search(r[4])):
            bad.append(f"{r[0]}: a state without its words, glyph and tokens")
    built = built_glyphs()
    if built is None:
        return [*bad, "cannot list the built icon set at the base"]
    for name in sorted(set(ICON.findall(t.spec)) - built):
        bad.append(f"`icon/{name}` is not in the built icon set at the base")
    rest = t.spec.replace(section(t.spec, "## 5."), "")
    for ln in rest.split("\n"):
        if OWN_COMPONENT.search(ln) and not ln.startswith("| RQ-"):
            bad.append(f"a status component outside §5: {ln[:60]!r}")
    return bad


def g_count(t: Texts) -> list[str]:
    """Every safety count is served; none is today (G-12)."""
    bad = [f"spec:{i} counts legs in the client" for i, ln in enumerate(t.spec.split("\n"), 1)
           if COUNT.search(ln)]  # fmt: skip
    gap = [r for r in table_rows(t.spec, "G-12 ") if len(r) > 1]
    if not gap or not all(w in gap[0][1] for w in ("accepted", "protected", "unknown")):
        bad.append("§11.1 has no G-12 row for served accepted, protected and unknown counts")
    prot = [r for r in table_rows(section(t.spec, "### 2.1"), "Protection") if len(r) > 2]
    if not prot or "not served yet" not in prot[0][1]:
        bad.append('§2.1: the group row\'s Protection is not "not served yet"')
    return bad


def g_merged(t: Texts) -> list[str]:
    bad = []
    for i, ln in enumerate(t.spec.split("\n"), 1):
        if UNMERGED.search(ln) and not (ln.startswith("| RQ-") or "request row" in ln):
            bad.append(f"spec:{i} names an unmerged input outside a request row")
        if UNMERGED.search(ln) and re.search(r"(E34-D0[12]|#936|#996)[^|]*`:\d", ln):
            bad.append(f"spec:{i} cites an unmerged input by line")
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
    checks = ((CLOSING, "a closing keyword (PR 2 alone closes #997)"), (LOCAL_PATH, "a local path"),
              (AGENT_NAME, "an agent name"), (URL_OR_HOST, "a URL or a host"))  # fmt: skip
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
            if LOCAL_PATH.search(ln):
                bad.append(f"{label}:{i} carries a local path")
    return bad


def g_scope(t: Texts) -> list[str]:
    if t.changed is None:
        return ["cannot list the changed paths (git failed)"]
    own = ", ".join(OWN_PATHS)
    return [f"{p} is touched; this ticket owns {own}" for p in t.changed if p not in OWN_PATHS]


GATES: dict[str, Callable[[Texts], list[str]]] = {
    "G-STATE": g_state, "G-TOKEN": g_token, "G-CONTRAST": g_contrast, "G-CVD": g_cvd,
    "G-SAFETY": g_safety, "G-T2": g_t2, "G-MOTION": g_motion, "G-COPY": g_copy,
    "G-VOCAB": g_vocab, "G-RECOVERY": g_recovery, "G-PROTECT": g_protect, "G-CMP258": g_cmp258,
    "G-COUNT": g_count, "G-MERGED": g_merged, "G-CITE": g_cite, "G-HYGIENE": g_hygiene,
    "G-SCOPE": g_scope,
}  # fmt: skip


def audit(t: Texts) -> list[tuple[str, str]]:
    out = []
    for g, fn in GATES.items():
        try:
            out += [(g, m) for m in fn(t)]
        except LookupError as e:
            out.append((g, str(e)))
    return out


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
        cs = cells(ln)
        if ln.startswith("| P-") and len(cs) == 8:
            v = contrast_values(cs)
            cs[4:8] = [*v, verdict(cs[3], v)]
            ln = "| " + " | ".join(cs) + " |"
        elif ln.startswith("| V-") and len(cs) == 6:
            cs[4], cs[5] = cvd_values(cs)
            ln = "| " + " | ".join(cs) + " |"
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
        cs = cells(ls[i])
        cs[col] = value
        ls[i] = "| " + " | ".join(cs) + " |"
        return replace(t, spec="\n".join(ls))

    return f


def drop_row(lead: str) -> Callable[[Texts], Texts]:
    def f(t: Texts) -> Texts:
        return replace(
            t, spec="\n".join(ln for ln in t.spec.split("\n") if not ln.startswith(lead))
        )

    return f


MUTATIONS: tuple[tuple[str, str, Callable[[Texts], Texts]], ...] = (
    ("G-STATE", "drop the leg-unknown frame row", drop_row("| B12 ")),
    ("G-STATE", "drop the AC-2 mapping", drop_row("| AC-2 ")),
    ("G-STATE", "name an inset that is no state row", sub("M62-20 (filtered empty) on", "M62-99 (filtered empty) on")),
    ("G-TOKEN", "misspell a status token", sub("in `color.status.info.strong` beside the word", "in `color.status.unknwon.strong` beside the word")),
    ("G-CONTRAST", "type a contrast figure off", set_cell("P-01", 4, "1.00")),
    ("G-CONTRAST", "report a ui pair as structure", set_cell("P-05", 3, "structure")),
    ("G-CVD", "type a ΔE figure off", set_cell("V-01", 4, "1.00 / 1.00 / 1.00 / 1.00")),
    ("G-SAFETY", "offer a leg without its stop", set_cell("M62-29", 3, "an order confirm with a box to send it without a stop; G-1")),
    ("G-SAFETY", "let the cancel copy drop the stops", set_cell("`cancel.effect`", 1, '"Cancels the unfilled orders of {n} legs."')),
    ("G-SAFETY", "close OQ-1 silently", set_cell("OQ-1", 2, "the leg only")),
    ("G-SAFETY", "drop the never-omit statement", sub("never offers a way to omit, remove or turn off the stop", "shows the stop")),
    ("G-SAFETY", "drop the stop from Retry's preview line", sub('"sub_004: buy 0.060 BTCUSDT, stop 63,900.0 at the exchange"', '"sub_004: buy 0.060 BTCUSDT"')),
    ("G-SAFETY", "a CMP-258 protection value without a stop", sub('protection "—"', 'protection "off (the leg sent without a stop)"')),
    ("G-T2", "drop the Viewer's rendering", set_cell("M62-23", 3, 'T2 `rbac.permission` "Your role can\'t place orders."')),
    ("G-T2", "retype a key's text", set_cell("M62-24", 3, 'T2 "You may only look at this account."; rendering 2a')),
    ("G-T2", "retype a registered state", set_cell("M62-25", 3, 'T2 "Trading is paused right now, try later." (registered states); rendering 2a')),
    ("G-T2", "drop the lock from §1 item 6", sub("the label led by the CMP-019 `lock` glyph", "the label led by its glyph")),
    ("G-T2", "let a T2 control leave the Tab order (G-T2.1b)", sub("never the `disabled` attribute — it stays in the Tab order", "or the `disabled` attribute")),
    ("G-T2", "drop the tertiary label pair (G-T2.2)", drop_row("| P-04 ")),
    ("G-MOTION", "drop a reduced-motion twin", set_cell("MO-1", 3, "—")),
    ("G-MOTION", "animate the summary's entrance", set_cell("MO-3", 2, "a slide down over `motion.duration.normal`")),
    ("G-MOTION", "pulse the countdown", set_cell("MO-5", 2, "a pulse each second")),
    ("G-COPY", "drop a PROPOSED string's owner", set_cell("`list.empty`", 2, "PROPOSED")),
    ("G-COPY", "claim a string verbatim that the line lacks", set_cell("`leg.unknown`", 1, '"status unknown for {account}"')),
    ("G-VOCAB", "flatten a group in the copy", set_cell("`close.title`", 1, '"Flatten group {id}?"')),
    ("G-RECOVERY", "rename Retry unwind on the banner", sub('with RC-3 "Retry unwind (1 leg not flat)"', 'with RC-3 "Try again"')),
    ("G-RECOVERY", "rename the Unwind label", set_cell("RC-2", 2, '"Roll back {n} accepted legs"')),
    ("G-RECOVERY", "arm Cancel working orders", set_cell("RC-5", 4, "on LIVE")),
    ("G-PROTECT", "gate the protective actions under a lockout", set_cell("M62-25", 2, "Retry on a leg of a locked or frozen account; Close group, Cancel working orders and Unwind gated as well")),
    ("G-PROTECT", "gate every action under view-as", set_cell("M62-27", 2, "under view-as, every action")),
    ("G-CMP258", "define a second status component in §3", sub("Group words and leg words are CMP-258's (§5.3).", "Group words and leg words are CMP-258's (§5.3); a second status component, LegBadge, is defined here.")),
    ("G-CMP258", "draw stop pending with an unbuilt glyph", set_cell("LS-15", 4, "`icon/shield-off`")),
    ("G-CMP258", "drop the unwinding leg state", drop_row("| LS-09 ")),
    ("G-COUNT", "count protection in the client", sub('Protection "not served yet" (G-12)', '"5 of 5 protected"')),
    ("G-COUNT", "count accepted legs in the summary copy", set_cell("`group.partial`", 1, '"{k} of {n} accepted. {account} rejected: {reason}."')),
    ("G-MERGED", "name E34-D02 outside a request row", sub("**the one definition**: SCR-061 consumes it", "**the one definition**: E34-D02 consumes it")),
    ("G-CITE", "re-point a `14` cite to an unpinned line", sub("(`14`:1526, LS-07)", "(`14`:1527, LS-07)")),
    ("G-HYGIENE", "write a closing keyword against #997", sub("carries the closing line.", "carries the closing line. Closes #997.")),
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
    ap = argparse.ArgumentParser(description="E34-D03 trade-group manager audit")
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
            "# E34-D03 cite pins: the cite, a hash of its cited line(s) at its base."
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
