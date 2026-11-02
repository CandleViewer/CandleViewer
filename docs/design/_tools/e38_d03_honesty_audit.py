#!/usr/bin/env python3
"""E38-D03 (#1074) audit: the hi-fi spec of the paper reset (SCR-079), live eligibility
(SCR-122), the environment parity report and the paper fidelity panel (SCR-137 fragments).

Standalone and offline, shaped on the merged E10-D03 tool (`e10_d03_shell_audit.py`): it imports
`packages/ui/tokens/tests/verify_tokens.py` (the token loader and resolver),
`docs/design/_tools/contrast_check.py` (`contrast_ratio`) and
`docs/research/_tools/cvd_simulate.py` (`simulate`, `delta_e76`; JND 5.0) from the working tree
and never re-implements them. It reads the spec and the pins file from the working tree and every
cited file AS TEXT with `git show` at the pinned base (`BASE`), except E38-D01, which is read at
#5451's approved head (`D01_REF`) until it merges. Default-deny: a gate that cannot read its
input FAILs.

Gates (each FAIL led by its name):
  G-STATE     every state the ticket's Scope and the rulings name has a §0 frame row, and each
              of the five acceptance criteria (AC-1 … AC-5) maps to frames that §0 lists.
  G-TOKEN     every design token the spec names (`color.*`, `font.*`, `border.*`, `radius.*`,
              `type.*`, `space.*`, `size.*`, `motion.*`, `opacity.*`) is in a merged set.
  G-CONTRAST  every §8.1 row is recomputed per theme (dark, light, high-contrast as
              `verify_tokens` merges them) with `contrast_check.contrast_ratio` and equals the
              spec to two decimals; a `text` row is at least 4.5:1 and a `ui` row at least 3:1
              in every theme; the verdict cell matches its role and figures.
  G-CVD       every §8.2 row's normal / protanopia / deuteranopia / tritanopia ΔE76 equals the
              spec to two decimals, and its JND column names the simulations under 5.0.
  G-HIDDEN    the reset in a LIVE session is absent, never disabled (US-PAPER-006; the AC):
              S79-07 reads absent with the "not even disabled" note and no T2, and the T2
              alternative (S79-09, B07) is marked "not adopted".
  G-T2        every state row (S77-, S79-, S122-, S137-) whose Presentation is T2 carries its
              reason as a quoted sentence, and that sentence is an E09-D09 key's text at the
              base (its `{slot}` filled) unless the cell marks it PROPOSED. Every gated control
              names its rendering (2a, 2b or the sentence form; G-T2.1c), §1 item 4 names the
              CMP-019 `lock` (G-T2.1d), and the acknowledgement wait names its rendering.
              §1 item 4 quotes G-T2.1b, G-T2.2 and G-T2.3 verbatim from `DS` at the base
              (`T2_QUOTES`), and §8.1 carries the G-T2.2 label pair (tertiary on raised).
  G-RULED     the account's own name is the typed token (never a fixed word; BQ-07), the
              protective writes stay enabled (BQ-13, C-2.6), and the S77-01 and OQ-2 rows exist.
  G-MERGED    only merged owners are cited: E38-D02 or #1003 appears only on a request row or
              the sentence saying so, and the unmerged #1075 is never named.
  G-CITE      every cite in range and on a non-blank line at its base, and equal to the pins.
  G-HYGIENE   no closing keyword, local path, URL or host, agent name, double-brace slot or
              deny word in the spec; no deny word in this tool's text or the pins.
  G-DRAWN     §0 is pending ("to draw (PR 2)" with no board table, PR 1) or drawn (PR 2).
              Drawn: §0 names the page id; every frame row's Status reads "drawn, board NN" (or
              "boards NN and MM") with each NN a row of the board table and the first NN its
              Board cell's number; each board row's Status is `drawn (r<n>)` with its board id
              and export, the export's number and slug agree with the row's board name, and on
              disk the PNG's IHDR width × height and sha256 equal the record; and no other
              E38-D03-*.png sits in `docs/design/E38/img/`.
  G-SCOPE     the diff touches only the spec, this tool, the pins file and the E38-D03 exports in
              `docs/design/E38/img/`.

Usage (from the repo root):
  python3 -I docs/design/_tools/e38_d03_honesty_audit.py --check
  python3 -I docs/design/_tools/e38_d03_honesty_audit.py --fill        (writes §8's figures)
  python3 -I docs/design/_tools/e38_d03_honesty_audit.py --self-test
  python3 -I docs/design/_tools/e38_d03_honesty_audit.py --repin-ruled (the pins' only writer)
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
SPEC_REL = "docs/design/E38/E38-D03.md"
TOOL_REL = "docs/design/_tools/e38_d03_honesty_audit.py"
PINS_REL = "docs/design/_tools/e38_d03_ruled_pins.txt"
OWN_PATHS = (SPEC_REL, TOOL_REL, PINS_REL)
BASE = "c327ed438c01c5bab9247890dd00f5dce3717f97"  # origin/main when written; re-pinned by content
D01_REF = "4774b2f8cd7b67a1ee934fe88546568f7aa3e34c"  # #5451's approved head; re-pinned at merge
TOKENS = ROOT / "packages" / "ui" / "tokens"
CVD_PATH = ROOT / "docs" / "research" / "_tools" / "cvd_simulate.py"
CONTRAST_PATH = ROOT / "docs" / "design" / "_tools" / "contrast_check.py"
PATHS: dict[str, str] = {
    "04": "docs/plan/04-security-program.md",
    "11": "docs/plan/11-user-stories.md",
    "14": "docs/plan/14-screens-catalogue.md",
    "15": "docs/plan/15-component-catalogue.md",
    "22": "docs/plan/22-api-openapi.yaml",
    "24": "docs/plan/24-internal-schemas.md",
    "E42D02": "docs/design/E42/E42-D02.md",
    "E42D03": "docs/design/E42/E42-D03.md",
    "E30D04": "docs/design/E30/E30-D04.md",
    "E27D02": "docs/design/E27/E27-D02.md",
    "E27D03": "docs/design/E27/E27-D03.md",
    "E10D03": "docs/design/E10/E10-D03.md",
    "E05D03": "docs/design/E05/E05-D03.md",
    "E09D09": "docs/design/E09/E09-D09.md",
    "D01": "docs/design/research/E38-paper-parity.md",
    "DS": ".claude/rules/32-design-specs.md",
}
REF_OF = {"D01": D01_REF}
CITE = re.compile(
    r"`(\d\d|E42D0[23]|E09D09|E30D04|E27D0[23]|E10D03|E05D03|D01|DS)`:(\d+(?:–\d+)?(?:, :\d+(?:–\d+)?)*)"
)
TOKEN_NAME = re.compile(
    r"`((?:color|font|border|radius|type|space|size|motion|opacity)\.[a-z0-9.-]*[a-z0-9])`"
)
CLOSING = re.compile(r"\b(?:close[sd]?|fix(?:e[sd])?|resolve[sd]?)\s+#\d+", re.IGNORECASE)
LOCAL_PATH = re.compile("/" + "home/|/Users/|[A-Za-z]:\\\\|\\bwt-" + "notes\\b")  # assembled
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
# the states the ticket's Scope and the rulings name; each needs a §0 frame row
REQUIRED_FRAMES = (
    "SCR-079/reset-demo",
    "SCR-079/reset-confirm-plain",
    "SCR-079/reset-confirm-typed",
    "SCR-079/reset-done",
    "SCR-079/reset-error",
    "SCR-079/reset-live-absent",
    "SCR-079/reset-alt-t2",
    "SCR-122/eligibility-default",
    "SCR-122/eligibility-grant",
    "SCR-122/eligibility-revoke",
    "sign-in/acknowledge-live",
    "workspace/reduce-only",
    "SCR-077/parity-link",
    "SCR-137/parity",
    "SCR-137/parity-stale",
    "SCR-137/parity-candidates",
    "SCR-137/parity-empty-error",
    "SCR-137/fidelity",
    "SCR-137/fidelity-breach",
    "SCR-137/fidelity-fill-rate",
    "SCR-137/fidelity-unavailable",
)
ACS = ("AC-1", "AC-2", "AC-3", "AC-4", "AC-5")
FRAME = re.compile(r"`((?:SCR-\d{3}|[a-z-]+)/[a-z0-9-]+)`")
UNMERGED = re.compile(r"E38-D02|#1003")
NEVER = re.compile(r"#1075|FillModelDisclosure")
IMG_REL = "docs/design/E38/img"
IMG = re.compile(r"docs/design/E38/img/E38-D03-\d\d-[a-z0-9-]+\.png")
PENDING = "to draw (PR 2)"
UUID = r"[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}"
DRAWN = re.compile(
    rf"drawn \(r\d+\): board id `{UUID}`, "
    r"`docs/design/E38/img/(E38-D03-(\d\d)-([a-z0-9-]+)\.png)` "
    r"\((\d+) × (\d+), sha256 `([0-9a-f]{64})`\)"
)
FRAME_DRAWN = re.compile(r"drawn, boards? (\d\d)(?: and (\d\d))?")


@dataclass(frozen=True)
class Texts:
    spec: str
    pins: str
    tool: str
    changed: list[str] | None
    memo: dict[str, str | None]
    files: dict[str, bytes]


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
    ref = REF_OF.get(key, BASE)
    text = show(t, ref, PATHS[key])
    if text is None:
        raise SystemExit(f"{PATHS[key]} does not resolve at {ref[:10]}; fetch first")
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


def cvd() -> ModuleType:
    return mod("cvd_simulate")


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


def contrast_values(t: Texts, row: list[str]) -> list[str]:
    cc = mod("contrast_check")
    fg, bg = tok(row[1]), tok(row[2])
    return [
        f"{cc.contrast_ratio(hex_rgb(color(th, fg)), hex_rgb(color(th, bg))):.2f}" for th in THEMES
    ]


def cvd_values(t: Texts, row: list[str]) -> tuple[str, str]:
    cv = cvd()
    th = {"hc": "high-contrast"}.get(row[3], row[3])
    a, b = tok(row[1]), tok(row[2])
    ha, hb = color(th, a), color(th, b)
    ds = [cv.delta_e76(ha, hb)] + [
        cv.delta_e76(cv.simulate(ha, d), cv.simulate(hb, d)) for d in DEFICIENCIES
    ]
    under = [n for n, d in zip(("normal", *DEFICIENCIES), ds, strict=True) if d < cv.JND_FLOOR]
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
    return bad


def g_token(t: Texts) -> list[str]:
    known = known_tokens()
    names = sorted(set(TOKEN_NAME.findall(t.spec)))
    return [
        f"`{n}` does not resolve in the token JSON at the base" for n in names if n not in known
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
        return ["§8.1 has no contrast rows"]
    for r in rows:
        if len(r) != 8:
            bad.append(f"{r[0]}: {len(r)} cells, not 8")
            continue
        want = contrast_values(t, r)
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
        ds, under = cvd_values(t, r)
        if r[4] != ds or r[5] != under:
            bad.append(f"{r[0]}: reads {r[4]} / {r[5]}, the tool gives {ds} / {under}")
    return bad


def row(t: Texts, lead: str) -> list[str]:
    rows = table_rows(t.spec, lead + " ")
    if len(rows) != 1:
        raise LookupError(f"the spec carries {len(rows)} `{lead}` rows, not 1")
    return rows[0]


def g_hidden(t: Texts) -> list[str]:
    bad = []
    live, alt, b07 = row(t, "S79-07"), row(t, "S79-09"), row(t, "B07")
    if "absent" not in live[3] or "T2" in live[3] or "disabled" in live[3]:
        bad.append("S79-07: the LIVE reset must read absent, with no T2 or disabled leg")
    if "not even disabled" not in live[2]:
        bad.append("S79-07: the note that it never renders disabled is missing")
    for r in (alt, b07):
        if "not adopted" not in " ".join(r):
            bad.append(f'{r[0]}: the T2 alternative is not marked "not adopted"')
    if "the control is absent" not in section(t.spec, "### 2.1"):
        bad.append("§2.1 does not state that the control is absent in a LIVE session")
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
            " the reason inline with one polite announcement"
        ),
    ),
)


def t2_quotes(t: Texts) -> list[str]:
    """G-T2.1b / 2 / 3: quoted from the owner, not paraphrased; the label pair measured."""
    bad = []
    owner = norm(at(t, "DS").replace("**", ""))
    item4 = norm(section(t.spec, "## 1."))
    for gid, q in T2_QUOTES:
        if norm(q) not in owner:
            bad.append(f"{gid}: the quote is no longer `DS`'s text at the base")
        elif f"{gid}, verbatim" not in item4 or norm(q) not in item4:
            bad.append(f"§1 item 4 does not quote {gid} verbatim from `DS`")
    pairs = {(r[1], r[2]) for r in contrast_rows(t) if len(r) > 2}
    if ("`color.text.tertiary`", "`color.surface.raised`") not in pairs:
        bad.append("§8.1 has no `color.text.tertiary` on `color.surface.raised` pair (G-T2.2)")
    return bad


def g_t2(t: Texts) -> list[str]:
    bad = []
    leads = ("S77-", "S79-", "S122-", "S137-")
    rows = [r for lead in leads for r in table_rows(t.spec, lead)]
    if not rows:
        return ["the spec has no state rows"]
    keys = e09_templates(t)
    for r in rows:  # G-T2.1c: every gated control names its rendering
        if len(r) >= 4 and ("T2" in r[2] or "T2" in r[3]) and not RENDERING.search(r[3]):
            bad.append(f"{r[0]}: a T2 control with no rendering (2a, 2b or the sentence form)")
    if "CMP-019 `lock`" not in section(t.spec, "## 1."):
        bad.append("§1 item 4 does not state the CMP-019 `lock` glyph that leads a T2 label")
    if not re.search(
        r"Until it is acknowledged, live order entry stays T2 `rbac.env` \(G-3\), rendering",
        t.spec,
    ):
        bad.append("§4.2: the acknowledgement wait's T2 names no rendering")
    bad += t2_quotes(t)
    for r in rows:
        if len(r) < 4 or "T2" not in r[3]:
            continue
        quote = re.search(r'"([^"]{8,})"', r[3])
        if not quote:
            bad.append(f"{r[0]}: a T2 presentation with no quoted reason")
        elif "PROPOSED" not in r[3] and not any(k.match(quote[1]) for k in keys):
            bad.append(f"{r[0]}: {quote[1]!r} is no E09-D09 key's text and is not PROPOSED")
    return bad


def g_ruled(t: Texts) -> list[str]:
    """The overrides the lens found ungated: BQ-07's token, BQ-13's protective writes, BQ-18's entry, BQ-05's ids."""
    bad = []
    typed = re.search(r'"Type ([^"]+) to confirm"', row(t, "S79-03")[2])
    if not typed or typed[1] != "Paper 1":
        bad.append(
            "S79-03: the typed token is not the account's own name (BQ-07; never a fixed word)"
        )
    if (
        "**Close, cancel, reduce-only and stops stay enabled** (C-2.6): a protective write is never gated."
        not in t.spec
    ):
        bad.append("§4.2: the protective writes are not stated as enabled (BQ-13, C-2.6)")
    if "close, cancel, reduce-only and stops enabled" not in row(t, "S122-06")[2]:
        bad.append("S122-06: the reduce-only frame does not keep the protective writes enabled")
    row(t, "S77-01")  # BQ-18's primary entry: the row must exist (LookupError otherwise)
    row(t, "OQ-2")  # BQ-05: the section ids asked of the `14` owner
    return bad


def g_merged(t: Texts) -> list[str]:
    bad = []
    for i, ln in enumerate(t.spec.split("\n"), 1):
        if UNMERGED.search(ln) and not (ln.startswith("| R-") or "request row" in ln):
            bad.append(f"spec:{i} leans on the unmerged E38-D02 outside a request row")
        if NEVER.search(ln):
            bad.append(f"spec:{i} names the unmerged #1075")
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
    checks = ((CLOSING, "a closing keyword (PR 2 alone closes #1074)"), (LOCAL_PATH, "a local path"),
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
        f"{p} is touched; this ticket owns {own} and the E38-D03 exports"
        for p in t.changed
        if p not in OWN_PATHS and not IMG.fullmatch(p)
    ]


def png_size(data: bytes) -> tuple[int, int] | None:
    if len(data) < 24 or data[:8] != b"\x89PNG\r\n\x1a\n" or data[12:16] != b"IHDR":
        return None
    return int.from_bytes(data[16:20], "big"), int.from_bytes(data[20:24], "big")


def board_problems(t: Texts, boards: list[list[str]]) -> list[str]:
    bad = []
    listed: set[str] = set()
    for r in boards:
        m = DRAWN.fullmatch(r[5]) if len(r) == 6 else None
        if m is None:
            bad.append(f"board {r[0]}: Status is not the drawn form")
            continue
        name, no, slug, sha = m[1], m[2], m[3], m[6]
        listed.add(name)
        if no != r[0] or r[1] != f"`E38-D03 / {no} {slug}`":
            bad.append(f"board {r[0]}: the export names another board or slug")
        data = t.files.get(name)
        size = (int(m[4]), int(m[5]))
        if data is None or hashlib.sha256(data).hexdigest() != sha or png_size(data) != size:
            bad.append(f"board {r[0]}: {name} is missing or not its W × H and sha256")
    stray = sorted(set(t.files) - listed)
    if stray:
        bad.append(f"E38-D03 PNGs on disk that §0 does not list: {stray}")
    return bad


def g_drawn(t: Texts) -> list[str]:
    zero = section(t.spec, "## 0.")
    head = zero.strip().split("\n", 1)[0]
    frames = [r for r in table_rows(zero, "B") if re.fullmatch(r"B\d\d", r[0])]
    boards = table_rows(zero, "0")
    if not frames:
        return ["§0 lists no frames"]
    if PENDING in head and not boards:
        return []  # PR 1: nothing drawn yet
    bad = []
    if PENDING in head:
        bad.append(f"a mix: §0's heading still reads {PENDING!r}")
    if not re.search(rf"page id `{UUID}`", zero):
        bad.append("drawn, but §0 names no page id")
    nos = {r[0] for r in boards}
    for r in frames:
        m = FRAME_DRAWN.fullmatch(r[3]) if len(r) == 4 else None
        drawn = [n for n in (m.groups() if m else ()) if n]
        if not drawn or any(n not in nos for n in drawn) or int(drawn[0]) != int(r[2][:1] or 0):
            bad.append(f"{r[0]}: names no drawn board of the board table")
    return bad + board_problems(t, boards)


GATES: dict[str, Callable[[Texts], list[str]]] = {
    "G-STATE": g_state, "G-TOKEN": g_token, "G-CONTRAST": g_contrast, "G-CVD": g_cvd,
    "G-HIDDEN": g_hidden, "G-T2": g_t2, "G-RULED": g_ruled, "G-MERGED": g_merged, "G-CITE": g_cite, "G-HYGIENE": g_hygiene,
    "G-DRAWN": g_drawn, "G-SCOPE": g_scope,
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
    img = ROOT / IMG_REL
    files = (
        {f.name: f.read_bytes() for f in sorted(img.glob("E38-D03-*.png"))} if img.is_dir() else {}
    )
    return Texts(spec, pins, tool, changed_paths(), {}, files)


def fill(t: Texts) -> str:
    out = []
    for ln in t.spec.split("\n"):
        cells = [c.strip() for c in ln.strip().strip("|").split("|")]
        if ln.startswith("| P-") and len(cells) == 8:
            v = contrast_values(t, cells)
            cells[4:8] = [*v, verdict(cells[3], v)]
            ln = "| " + " | ".join(cells) + " |"
        elif ln.startswith("| V-") and len(cells) == 6:
            cells[4], cells[5] = cvd_values(t, cells)
            ln = "| " + " | ".join(cells) + " |"
        out.append(ln)
    return "\n".join(out)


def sub(old: str, new: str) -> Callable[[Texts], Texts]:
    def f(t: Texts) -> Texts:
        if t.spec.count(old) != 1:
            raise SystemExit(f"self-test: the spec carries {old[:50]!r} {t.spec.count(old)} times")
        return replace(t, spec=t.spec.replace(old, new))

    return f


def set_cell(row: str, col: int, value: str) -> Callable[[Texts], Texts]:
    def f(t: Texts) -> Texts:
        ls = t.spec.split("\n")
        i = next(k for k, ln in enumerate(ls) if ln.startswith(f"| {row} "))
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


def with_file(name: str, data: bytes | None) -> Callable[[Texts], Texts]:
    def f(t: Texts) -> Texts:
        files = {k: v for k, v in t.files.items() if k != name}
        if data is not None:
            files[name] = data
        return replace(t, files=files)

    return f


B04_PNG = "E38-D03-04-scr-137-paper-fidelity.png"
B02_PNG = "E38-D03-02-scr-122-live-eligibility.png"


def one_pixel_wider(t: Texts) -> Texts:
    """Board 04's IHDR width plus one; the record's sha256 moves to match, so only the size is off."""
    data = bytearray(t.files[B04_PNG])
    data[16:20] = (int.from_bytes(data[16:20], "big") + 1).to_bytes(4, "big")
    old = hashlib.sha256(t.files[B04_PNG]).hexdigest()
    new = hashlib.sha256(bytes(data)).hexdigest()
    return replace(t, spec=t.spec.replace(old, new, 1), files={**t.files, B04_PNG: bytes(data)})


def one_byte_off(t: Texts) -> Texts:
    """Board 02's last byte changed: its size stands, its sha256 does not."""
    data = bytearray(t.files[B02_PNG])
    data[-1] ^= 0x01
    return replace(t, files={**t.files, B02_PNG: bytes(data)})


def swap_boards(t: Texts) -> Texts:
    """Boards 01 and 03 swap bytes: both sizes and sha256 then disagree with the record."""
    a = "E38-D03-01-scr-079-paper-reset.png"
    b = "E38-D03-03-scr-137-parity-report.png"
    return replace(t, files={**t.files, a: t.files[b], b: t.files[a]})


MUTATIONS: tuple[tuple[str, str, Callable[[Texts], Texts]], ...] = (
    ("G-STATE", "drop the fidelity-breach frame row", drop_row("| B19 ")),
    ("G-STATE", "drop the AC-4 mapping", drop_row("| AC-4 ")),
    ("G-TOKEN", "misspell a status token", sub("text, `color.text.secondary`", "text, `color.text.secondry`")),
    ("G-CONTRAST", "type a contrast figure off", set_cell("P-01", 4, "1.00")),
    ("G-CONTRAST", "report a ui pair as structure", set_cell("P-08", 3, "structure")),
    ("G-CVD", "type a ΔE figure off", set_cell("V-01", 4, "1.00 / 1.00 / 1.00 / 1.00")),
    ("G-HIDDEN", "draw the LIVE reset disabled", set_cell("S79-07", 3, "T2 \"Paper reset isn't available in a LIVE session.\" (PROPOSED); rendering 2a")),
    ("G-HIDDEN", "adopt the T2 alternative silently", sub("**not adopted**", "**the default**")),
    ("G-T2", "drop the reduce-only reason", set_cell("S122-06", 3, "T2")),
    ("G-T2", "retype a key's text", set_cell("S137-09", 3, 'T2 "Read only while viewing someone."')),
    ("G-T2", "drop a control's rendering", set_cell("S122-02", 3, 'T2 "This is a demo account." (a PROPOSED key, E42-D03\'s)')),
    ("G-T2", "drop the lock from §1 item 4", sub("led by the CMP-019 `lock` glyph", "led by its glyph")),
    ("G-T2", "let a T2 control leave the Tab order (G-T2.1b)", sub("never the `disabled` attribute — it stays in the Tab order", "or the `disabled` attribute")),
    ("G-T2", "dim a T2 label with the disabled tokens (G-T2.2)", sub("never `color.text.disabled`, never `opacity.disabled` on", "dimmed with `opacity.disabled` on")),
    ("G-T2", "make a T2 press act (G-T2.3)", sub("changes nothing and re-shows the reason inline with one polite announcement", "acts")),
    ("G-T2", "drop the tertiary label pair from §8.1 (G-T2.2)", drop_row("| P-09 ")),
    ("G-RULED", "type a fixed word as the token", set_cell("S79-03", 2, 'CMP-044 typed (rung 3): the counts line, the history line, "Type RESET to confirm"')),
    ("G-RULED", "gate the protective writes", sub("**Close, cancel, reduce-only and stops stay enabled** (C-2.6): a protective write is never gated.", "**Close, cancel, reduce-only and stops are T2** (C-2.6).")),
    ("G-RULED", "drop the S77-01 row", drop_row("| S77-01 ")),
    ("G-RULED", "drop the OQ-2 row", drop_row("| OQ-2 ")),
    ("G-MERGED", "cite the unmerged E38-D02", sub("It is a request row to E38-D02 (R-1), not drawn here.", "It is drawn by E38-D02 §3.4.")),
    ("G-MERGED", "name #1075's offer", sub("The values are illustrative, and the defect ids are fixtures.", "The values are illustrative (#1075).")),
    ("G-CITE", "re-point a `14` cite to an unpinned line", sub("(`14`:43)", "(`14`:44)")),
    ("G-HYGIENE", "write a closing keyword against #1074", sub("carries the closing line.", "carries the closing line. Closes #1074.")),
    ("G-HYGIENE", "put a deny word into the tool's own text", lambda t: replace(t, tool=t.tool + "\n# " + DENY[6] + "\n")),
    ("G-DRAWN", "board 04's PNG one pixel wider than its record", one_pixel_wider),
    ("G-DRAWN", "board 02's PNG one byte off its sha256", one_byte_off),
    ("G-DRAWN", "boards 01 and 03 swap bytes", swap_boards),
    ("G-DRAWN", "a board's PNG missing on disk", with_file("E38-D03-05-scr-079-paper-reset-light.png", None)),
    ("G-DRAWN", "an extra E38-D03 PNG on disk", with_file("E38-D03-06-extra.png", b"\x89PNG\r\n\x1a\n")),
    ("G-DRAWN", "§0's heading back to pending (a mix)", sub("## 0. The frames (Penpot) — drawn", "## 0. The frames (Penpot) — to draw (PR 2)")),
    ("G-DRAWN", "a frame row names a board not drawn", set_cell("B19", 3, "drawn, board 06")),
    ("G-DRAWN", "a frame row on another board than its Board cell", set_cell("B13", 3, "drawn, board 02")),
    ("G-DRAWN", "a frame row back to pending", set_cell("B08", 3, PENDING)),
    ("G-DRAWN", "a board row's name off its export's slug", sub("`E38-D03 / 02 scr-122-live-eligibility`", "`E38-D03 / 02 scr-122-live-access`")),
    ("G-DRAWN", "the page id dropped", lambda t: replace(t, spec=re.sub(rf"page id `{UUID}`", "page id pending", t.spec))),
    ("G-DRAWN", "board 05's row dropped (its PNG then unlisted)", drop_row("| 05 ")),
    ("G-SCOPE", "touch `14` in the diff", lambda t: replace(t, changed=[*OWN_PATHS, PATHS["14"]])),
    ("G-SCOPE", "another ticket's export in the diff", lambda t: replace(t, changed=[*OWN_PATHS, "docs/design/E38/img/E38-D04-01-x.png"])),
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
    ap = argparse.ArgumentParser(description="E38-D03 honesty surfaces audit")
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
        head = "# E38-D03 cite pins: the cite, a hash of its cited line(s) at its base. Written by --repin-ruled only.\n"
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
