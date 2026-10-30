#!/usr/bin/env python3
"""E16-D06 audit: the accessibility review and engineering hand-off for the recorder design set.

Reads ``docs/design/E16/E16-D06.md`` and ``docs/design/E16/E16-D06-copy.json`` as text, re-derives
every ``<!-- audit:key=value -->`` marker, checks every ``KEY``:line cite by content at ``origin/main``
against the committed pins (``e16_d06_ruled_pins.txt``, written by ``--repin-ruled`` only), and gates
the review's tables (inventory, keyboard, focus, regions, script, budget, T2, verdicts, findings,
rows, the deck, the frozen set, the redlines, the state matrix, the icons, the ``14`` edit set and
the hygiene scan). Colour arithmetic is imported, never copied: ``contrast_check.contrast_ratio``,
``cvd_simulate.simulate`` / ``delta_e76`` and the E16-D05 audit's token resolver; the parents' pair
lists are the E16-D03 / D04 / D05 audits' ``PAIRS_TABLE`` plus E16-D02 §10.4's rows parsed at the base.

    --check         exit 1 on any FAIL
    --json          the numbers and findings as JSON
    --fill          rewrite every marker's number in the spec from the computed value
    --self-test     one mutation per gate; each must raise exactly its own FAIL
    --repin-ruled   rewrite the pins file from the spec's cites (the only pins writer)
"""

from __future__ import annotations

import argparse
import functools
import hashlib
import importlib.util
import json
import re
import subprocess
import sys
from collections.abc import Callable
from pathlib import Path
from types import ModuleType
from typing import Any, NamedTuple

ROOT = Path(__file__).resolve().parents[3]
TOOLS = ROOT / "docs" / "design" / "_tools"
SPEC = ROOT / "docs" / "design" / "E16" / "E16-D06.md"
DECK = ROOT / "docs" / "design" / "E16" / "E16-D06-copy.json"
PINS = TOOLS / "e16_d06_ruled_pins.txt"
HEAD = "origin/main"
IMG_DIR = "docs/design/E16/img"
RULING_ID = "6516426184"
RULED_STAMP = f"RULED (orchestrator, 2026-10-30, #374 ruling of record — {RULING_ID})"
TICKET = "#374"
POINTER_MARK = "**A11y review and hand-off (E16-D06):**"
POINTER_ANCHORS = {
    "SCR-047": "- **Hi-fi (E16-D05, #373):** [E16-D05.md](../design/E16/E16-D05.md) — the final",
    "SCR-140": "- **Design (E16-D02):**",
    "SCR-141": "- **Design (hi-fi):** [E16-D03.md]",
    "SCR-142": "- **Design (hi-fi):** [E16-D04.md]",
    "SCR-151": "- **Hi-fi (E16-D05, #373):** [E16-D05.md](../design/E16/E16-D05.md) (the recorder",
}
KEYS: dict[str, str] = {
    "02": "docs/plan/02-definition-of-ready-done.md",
    "04": "docs/plan/04-security-program.md",
    "05": "docs/plan/05-accessibility-standard.md",
    "14": "docs/plan/14-screens-catalogue.md",
    "15": "docs/plan/15-component-catalogue.md",
    "16": "docs/plan/16-design-system-brief.md",
    "22": "docs/plan/22-api-openapi.yaml",
    "23": "docs/plan/23-ws-protocol.md",
    "D01": "docs/design/research/e16-recorder-mental-model.md",
    "D02": "docs/design/E16/E16-D02.md",
    "D02H": "docs/design/E16/E16-D02-handoff.md",
    "D03": "docs/design/E16/E16-D03.md",
    "D04": "docs/design/E16/E16-D04.md",
    "D05": "docs/design/E16/E16-D05.md",
    "E09-D09": "docs/design/E09/E09-D09.md",
    "E42-D02": "docs/design/E42/E42-D02.md",
    "E11-D04": "docs/design/E11/E11-D04.md",
    "E12-D02": "docs/design/E12/E12-D02.md",
    "DS": ".claude/rules/32-design-specs.md",
    "README": "docs/design/README.md",
    "SEED": "services/api/candleviewer/auth/rbac_seed.json",
    "CAL": "docs/plan/backlog/_tools/calendar_cv.py",
    "ICONS": "packages/ui/src/icons/registry.ts",
    "E16": "docs/plan/backlog/E16.json",
}
PARENTS = ("D02", "D03", "D04", "D05")
UNTOUCHED = ("D02", "D03", "D04", "D05", "D02H", "15")
PUBLIC_KEYS = ("22", "04", "14", "05", "D02", "D03", "D04", "D05", "E09-D09", "SEED", "15", "23")
SURFACES = ("SCR-140", "SCR-141", "SCR-142", "SCR-047", "SCR-151", "CMP-177")
VERDICTS = (
    "reviewed",
    "cited",
    "cited · verdict given",
    "text-bound state (RULED `D02`:794)",
    "out of scope — ",
)
CLAUSE_VERDICT = re.compile(
    r"^(compliant(; extended)?|at risk( — interim path: .+)?|non-compliant|out of scope — .+|"
    r"not yet decidable — routed to E16-Q05 \(#482\))$"
)
# An F row's closing tag: the trailing parenthesis of its merged sentence, one level of nesting
# allowed — "(`05` §6.2; WCAG 4.1.3)", "(`T Tech`; `05`:206)", "(WCAG 2.4.3; R-1 (b))".
F_TAG = re.compile(r"\(([^()]*(?:\([^()]*\)[^()]*)*)\)\s*$")
TAG_CLAUSE = re.compile(r"`05` §(\d[\d.]*(?: (?:item|rule) \d+)?)")
TAG_WCAG = re.compile(r"WCAG (\d\.\d\.\d+)")
CLAUSE_LABEL = re.compile(r"^§(\d[\d.]*(?: (?:items?|rule) \d+(?:, \d+)*)?)")
CONSUMER = re.compile(r"E16-(?:S0\d|Q0\d|D07)")
POLITENESS = ("polite", "assertive", "none", "never", "— (G-")
FOCUS_RE = re.compile(
    r"^(?:\*\*PROPOSED \(F-\d\d\):\*\* )?(kept · |moves to · |returns to · |restored to · |n/a)"
)
CLASSES = ("T2", "validity", "busy", "status", "absence", "outcome", "T4", "n/a")
SEVERITIES = ("Blocking", "Major", "Minor", "Info")
OWNER_RE = re.compile(r"^E16-D0[2-5] · area/recorder-replay$")
TARGET_RE = re.compile(r"E16-(S0[1-5]|Q0[125]|D07) \(#\d+\)")
HOLD = "cannot enter Ready until fixed or an exception is recorded on #374"
BQ_IDS = tuple(f"BQ-{i:02d}" for i in range(1, 25))
KEY_VOCAB = re.compile(
    r"`(Tab|Shift\+Tab|Enter|Space|Esc|Home|End|PageUp|PageDown|Ctrl\+K|Ctrl\+\\|\?|Ctrl\+=|"
    r"[↑↓←→]|Shift\+[↑↓]|Space / Enter|Enter / Space|Tab / Shift\+Tab|Home / End|← →|↑ ↓|←/→|↑/↓)`"
)
KEY_LITERAL = re.compile(r"`([^`]+)`")
KEY_LIKE = re.compile(r"^(?:Ctrl|Alt|Shift|Meta)\+|^F\d{1,2}$")
CITE = re.compile(r"`([A-Za-z0-9\-]+)`:(\d+)(?:[–-]:?(\d+))?")
MARKER = re.compile(r"(\S+) <!-- audit:([a-z0-9\-_.]+)=([^ ]+) -->")
MARKER_BARE = re.compile(r"<!-- audit:([a-z0-9\-_.]+) -->")
QUOTED = re.compile(r'"([^"\n]{6,})"')
HOST = re.compile(r"\b[a-z0-9-]+\.(?:com|net|io|dev|org)\b", re.IGNORECASE)
URL = re.compile(r"https?://|\bwww\.", re.IGNORECASE)
UUID = re.compile(r"\b[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}\b")
LOCAL_PATH = re.compile(r"/(?:ho[m]e|Users)/[^/\s]+/")
ADVISORY_ID = re.compile(
    r"\b(?:GH[S]A-[0-9a-z]{4}-[0-9a-z]{4}-[0-9a-z]{4}|C[V]E-\d{4}-\d{4,})\b", re.IGNORECASE
)
# A loopback host or a host:port pair (the analogue of §20.3 row (ix)); never a bare `:\d+`,
# which every `` `22`:15418 `` cite would match.
LOOPBACK = re.compile(r"(?:\blocalhost|\b(?:\d{1,3}\.){3}\d{1,3}):\d{2,5}\b", re.IGNORECASE)
RECORD_WORDS = re.compile(
    r"\b(?:advis[o]r(?:y|ies)|vulnerab\w*|exploit\w*|threat.model|"
    r"security (?:record|finding|incident)|incident report)\b",
    re.IGNORECASE,
)
PERSON_WORDS = re.compile(r"\b(?:hpe|hcl)-wor[k]er(?:-\d)?\b|\bagent\b|\bworker\b", re.IGNORECASE)
PENDING_WALK = "pending — filled by the story-role dry run (BQ-16)"
SIMS = ("protanopia", "deuteranopia", "tritanopia")
BARS = {"text": 4.5, "non-text": 3.0, "hc-text": 7.0}
RULED_PIN_HEADER = (
    "# E16-D06 pins: KEY|line|words that stand on that line at origin/main (the tool's G10-CITE).\n"
    "# Written by `--repin-ruled` only; `--check` reads it (never hand-edit).\n"
)


def _load(path: Path, name: str) -> ModuleType:
    spec = importlib.util.spec_from_file_location(name, path)
    if spec is None or spec.loader is None:
        raise SystemExit(f"cannot load {path}")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


CONTRAST: Any = _load(TOOLS / "contrast_check.py", "contrast_check")
CVD: Any = _load(ROOT / "docs" / "research" / "_tools" / "cvd_simulate.py", "cvd_simulate")
D03T: Any = _load(TOOLS / "e16_d03_retention_audit.py", "e16_d03_retention_audit")
D04T: Any = _load(TOOLS / "e16_d04_storage_audit.py", "e16_d04_storage_audit")
D05T: Any = _load(TOOLS / "e16_d05_empty_states_audit.py", "e16_d05_empty_states_audit")


# ----------------------------------------------------------------------------- sources (cached once)


@functools.cache
def git_show(rev: str, rel: str) -> str:
    out = subprocess.run(
        ["git", "-C", str(ROOT), "show", f"{rev}:{rel}"], capture_output=True, check=False
    )
    return out.stdout.decode("utf-8") if out.returncode == 0 else ""


def git_diff_names(rel: str) -> str:
    out = subprocess.run(
        ["git", "-C", str(ROOT), "diff", "--unified=0", HEAD, "--", rel],
        capture_output=True,
        check=False,
    )
    return out.stdout.decode("utf-8")


@functools.cache
def source_lines(key: str) -> list[str]:
    """The cited file at origin/main, split; `14` without this PR's own pointer lines, so the
    line numbers hold before and after the merge."""
    text = git_show(HEAD, KEYS[key])
    lines = text.split("\n")
    if key == "14":
        lines = [ln for ln in lines if POINTER_MARK not in ln]
    return [""] + lines  # 1-based


@functools.cache
def source_norm(key: str) -> str:
    return norm(git_show(HEAD, KEYS[key]))


def norm(text: str) -> str:
    return re.sub(r"\s+", " ", text.replace("\\|", "|")).strip()


def source_has(key: str, needle: str) -> bool:
    return norm(needle) in source_norm(key)


class Ctx(NamedTuple):
    spec: str
    deck: str
    pins: str


def load_ctx() -> Ctx:
    return Ctx(
        SPEC.read_text(encoding="utf-8"),
        DECK.read_text(encoding="utf-8"),
        PINS.read_text(encoding="utf-8") if PINS.exists() else "",
    )


class Result:
    def __init__(self) -> None:
        self.fails: list[str] = []
        self.warns: list[str] = []
        self.numbers: dict[str, Any] = {}

    def fail(self, gate: str, msg: str) -> None:
        self.fails.append(f"[{gate}] {msg}")

    def warn(self, gate: str, msg: str) -> None:
        self.warns.append(f"[{gate}] {msg}")


# ----------------------------------------------------------------------------- markdown helpers


def section(text: str, head: str) -> str:
    """The block under the heading that starts with `head` (any level), to the next heading of the
    same or a higher level."""
    m = re.search(rf"^(#{{2,4}}) {re.escape(head)}", text, re.MULTILINE)
    if not m:
        return ""
    level = len(m.group(1))
    rest = text[m.end() :]
    nxt = re.search(rf"^#{{2,{level}}} ", rest, re.MULTILINE)
    return rest[: nxt.start()] if nxt else rest


def cells(line: str) -> list[str]:
    parts = re.split(r"(?<!\\)\|", line.strip())
    if parts and parts[0] == "":
        parts = parts[1:]
    if parts and parts[-1] == "":
        parts = parts[:-1]
    return [p.strip() for p in parts]


def rows(block: str) -> list[list[str]]:
    out: list[list[str]] = []
    in_fence = False
    for ln in block.split("\n"):
        if ln.startswith("```"):
            in_fence = not in_fence
            continue
        if in_fence or not ln.startswith("|"):
            continue
        cs = cells(ln)
        if not cs or all(re.fullmatch(r":?-{3,}:?", c) for c in cs):
            continue
        out.append(cs)
    return out[1:] if out else []  # drop the header row


def by_id(block: str, prefix: str) -> dict[str, list[str]]:
    return {r[0]: r for r in rows(block) if r and r[0].startswith(prefix)}


def strip_md(text: str) -> str:
    return re.sub(r"[*_`]", "", text)


def quoted_in(cell: str) -> list[str]:
    return [q for q in QUOTED.findall(cell) if "{" not in q]


def cites_in(text: str) -> list[tuple[str, int, int]]:
    out: list[tuple[str, int, int]] = []
    for key, a, b in CITE.findall(text):
        if key in KEYS:
            out.append((key, int(a), int(b) if b else int(a)))
    return out


# ----------------------------------------------------------------------------- parents' decks


def parent_deck_rows(key: str) -> list[tuple[str, str, str]]:
    """(deck key, string cell, cite) for every row of the parent's copy deck, parsed at origin/main."""
    text = git_show(HEAD, KEYS[key])
    out: list[tuple[str, str, str]] = []
    if key == "D02":
        blk = section(text, "8. Copy deck")
        if not blk.strip():
            return out
        first = text[: text.index(blk)].count("\n") + 1
        # join soft-wrapped bullets and paragraphs: a continuation line follows its opener
        units: list[tuple[int, str]] = []
        open_unit = False
        for i, ln in enumerate(blk.split("\n")):
            s = ln.strip()
            if not s or s.startswith("#"):
                open_unit = False
                continue
            if (
                open_unit
                and units
                and not s.startswith(("- ", "|"))
                and not units[-1][1].startswith("|")
            ):
                units[-1] = (units[-1][0], units[-1][1] + " " + s)
            else:
                units.append((first + i, s))
                open_unit = not s.startswith("|")
        n = 0
        for ln_no, s in units:
            if s.startswith("| `recorder."):
                cs = cells(s)
                out.append((cs[0].strip("`"), cs[1], f"`D02`:{ln_no}"))
            elif s.startswith("|"):
                cs = cells(s)
                if (
                    '"' in s
                    and len(cs) >= 3
                    and cs[0] not in ("Key", "Level / situation")
                    and "---" not in s
                ):
                    n += 1
                    out.append((f"d02.8.r{n:02d}", " · ".join(cs), f"`D02`:{ln_no}"))
            elif '"' in s:
                n += 1
                out.append(
                    (
                        f"d02.8.r{n:02d}",
                        s[2:].strip() if s.startswith("- ") else s,
                        f"`D02`:{ln_no}",
                    )
                )
        return out
    head = {"D03": "14. Copy deck", "D04": "14. Copy deck", "D05": "14. Copy deck"}[key]
    blk = section(text, head)
    offset = text[: text.index(blk)].count("\n") if blk else 0
    for i, ln in enumerate(blk.split("\n")):
        if ln.startswith("| `") and "---" not in ln:
            cs = cells(ln)
            if len(cs) >= 2:
                out.append((cs[0].strip("`"), cs[1], f"`{key}`:{offset + i}"))
    return out


# ----------------------------------------------------------------------------- colour (imported)


@functools.cache
def theme(name: str) -> dict[str, object]:
    return D05T.load_theme(name)


def hx(token: str, th: str) -> str | None:
    v = D05T.resolve(theme(th), token)
    return v if isinstance(v, str) and re.fullmatch(r"#[0-9A-Fa-f]{6}", v) else None


def rgb(h: str) -> tuple[int, int, int]:
    return (int(h[1:3], 16), int(h[3:5], 16), int(h[5:7], 16))


def ratio(a: str, b: str) -> float:
    return float(CONTRAST.contrast_ratio(rgb(a), rgb(b)))


def lstar(h: str) -> float:
    return float(CVD.xyz_to_lab(CVD.srgb_to_xyz(h))[0])


def grey(h: str) -> str:
    r, g, b = rgb(h)
    y = round(0.299 * r + 0.587 * g + 0.114 * b)
    return f"#{y:02x}{y:02x}{y:02x}"


def d02_pairs() -> list[tuple[str, str, str, bool]]:
    """E16-D02 §10.4's rows at origin/main: (fg, bg, role, gated)."""
    out: list[tuple[str, str, str, bool]] = []
    for r in rows(section(git_show(HEAD, KEYS["D02"]), "10.4 Computed contrast")):
        if len(r) < 7:
            continue
        need = r[6]
        fgs = re.findall(r"`([a-z][a-z0-9.\-{},]*)`", r[1])
        bgs = re.findall(r"`([a-z][a-z0-9.\-{},]*)`", r[2])
        role = "text" if need.startswith("4.5") else "non-text"
        for fg in expand(fgs):
            for bg in expand(bgs, prefix=r[2]):
                out.append((fg, bg, role, True))
    return out


def expand(names: list[str], prefix: str = "") -> list[str]:
    out: list[str] = []
    for n in names:
        m = re.match(r"(.+)\.\{(.+)\}(\..+)?$", n)
        if m:
            tail = m.group(3) or ""
            out += [f"{m.group(1)}.{p.strip()}{tail}" for p in m.group(2).split(",")]
        else:
            out.append(n)
    if prefix:
        base = out[0] if out else ""
        for alt in re.findall(r"/ `\.([a-z\-]+)`", prefix):
            if base:
                out.append(base.rsplit(".", 1)[0] + "." + alt)
    return out


def sibling_pairs(table: str) -> list[tuple[str, str, str, bool]]:
    out: list[tuple[str, str, str, bool]] = []
    for ln in table.strip().splitlines():
        parts = [p.strip() for p in ln.split("|")]
        if len(parts) < 4:
            continue
        role = parts[3]
        gated = role in ("text", "non-text")
        out.append((parts[1], parts[2], "text" if role.startswith("text") else "non-text", gated))
    return out


def union_pairs() -> list[tuple[str, str, str, bool]]:
    seen: set[tuple[str, str]] = set()
    out: list[tuple[str, str, str, bool]] = []
    for p in (
        d02_pairs()
        + sibling_pairs(D03T.PAIRS_TABLE)
        + sibling_pairs(D04T.PAIRS_TABLE)
        + sibling_pairs(D05T.PAIRS_TABLE)
    ):
        if (p[0], p[1]) in seen:
            continue
        seen.add((p[0], p[1]))
        out.append(p)
    return out


def union_line() -> tuple[str, dict[str, object]]:
    n = fail = skipped = 0
    under7: list[str] = []
    minima = {"text": 99.0, "non-text": 99.0, "hc-text": 99.0}
    for fg, bg, role, gated in union_pairs():
        cols = [(hx(fg, th), hx(bg, th), th) for th in D05T.THEMES]
        if any(c[0] is None or c[1] is None for c in cols):
            skipped += 1
            continue
        n += 1
        for f_hex, b_hex, th in cols:
            v = ratio(f_hex, b_hex)
            key = "hc-text" if (role == "text" and th == "high-contrast") else role
            if gated:
                minima[key] = min(minima[key], v)
                if v < BARS["text" if key == "hc-text" else key]:
                    fail += 1
                if key == "hc-text" and v < BARS["hc-text"]:
                    under7.append(f"`{fg}` on `{bg}` ({v:.2f})")
    line = (
        f"**Union:** {n} token pairs · gated FAIL {fail} at 4.5 / 3 · gated minima text {minima['text']:.2f}, "
        f"non-text {minima['non-text']:.2f}, hc-text {minima['hc-text']:.2f} · under the 7:1 AAA-leaning bar "
        f"in high contrast: {len(under7)} ({'; '.join(under7) or 'none'}), reported · "
        f"{skipped} pair reported, not gated (a non-token side) <!-- audit:contrast -->"
    )
    return line, {
        "union_pairs": n,
        "union_fail": fail,
        "union_under7": len(under7),
        "union_unresolved": skipped,
        "minima": {k: round(v, 2) for k, v in minima.items()},
    }


CR_TOKENS: dict[str, tuple[list[str], list[str]]] = {
    "CR-01": (
        ["color.status.success.strong", "color.status.warning.strong"],
        ["color.status.danger.default", "color.status.info.strong"],
    ),
    "CR-02": (
        ["color.action.primary.default"],
        ["color.status.warning.strong", "color.status.danger.default"],
    ),
    "CR-03": (["color.status.success.strong"], ["color.status.danger.strong"]),
    "CR-04": (["color.status.success.strong"], ["color.status.warning.strong"]),
    "CR-05": (["color.text.secondary"], ["color.surface.raised"]),
    "CR-06": (["color.text.tertiary"], ["color.surface.canvas"]),
    "CR-07": (["color.text.primary"], ["color.status.info.subtle"]),
    "CR-08": (["color.text.tertiary"], ["color.text.primary"]),
}


def carrier(a_tokens: list[str], b_tokens: list[str]) -> tuple[str, str]:
    dl = dee = 999.0
    for th in D05T.THEMES:
        for a in a_tokens:
            for b in b_tokens:
                ha, hb = hx(a, th), hx(b, th)
                if ha is None or hb is None or a == b:
                    continue
                dl = min(dl, abs(lstar(grey(ha)) - lstar(grey(hb))))
                for kind in SIMS:
                    dee = min(
                        dee, float(CVD.delta_e76(CVD.simulate(ha, kind), CVD.simulate(hb, kind)))
                    )
    return f"{dl:.1f}", f"{dee:.1f}"


# ----------------------------------------------------------------------------- numbers


def images() -> list[str]:
    out = subprocess.run(
        ["git", "-C", str(ROOT), "ls-tree", "--name-only", HEAD, IMG_DIR + "/"],
        capture_output=True,
        check=False,
    )
    return [p.rsplit("/", 1)[-1] for p in out.stdout.decode("utf-8").split()]


def parent_marker(key: str, name: str) -> int:
    m = re.search(rf"<!-- audit:{re.escape(name)}=(\d+) -->", git_show(HEAD, KEYS[key]))
    return int(m.group(1)) if m else 0


def compute(ctx: Ctx) -> dict[str, Any]:
    spec = ctx.spec
    n: dict[str, Any] = {}
    imgs = images()
    pngs = [p for p in imgs if p.endswith(".png")]
    cvd_imgs = [p for p in pngs if "-greyscale" in p or "-deuteranopia" in p or "-protanopia" in p]
    n["images"] = len(pngs)
    n["images-by-parent"] = "/".join(
        str(sum(1 for p in pngs if p.startswith(f"E16-{k}-"))) for k in PARENTS
    )
    n["cvd-images"] = len(cvd_imgs)
    n["frames"] = "/".join(str(parent_marker(k, "frames_total")) for k in ("D03", "D04", "D05"))
    n["bq"] = len(by_id(section(spec, "R. Rulings applied"), "BQ-"))
    n["inventory-rows"] = len(rows(section(spec, "2. Inventory")))
    n["kb"] = len(by_id(section(spec, "3. The consolidated keyboard model"), "KB-"))
    n["fm"] = len(by_id(section(spec, "4. The focus model"), "FM-"))
    n["rg"] = len(by_id(section(spec, "5. The region and landmark map"), "RG-"))
    n["sr"] = len(by_id(section(spec, "6.1 The script table"), "SR-"))
    n["bg"] = len(by_id(section(spec, "7. The announcement budget"), "BG-"))
    n["t2"] = len(by_id(section(spec, "8.1 The T2 table"), "T2-"))
    n["sd"] = len(by_id(section(spec, "8.2 The safety disclosures"), "SD-"))
    n["cr"] = len(by_id(section(spec, "10.4 Colour never the only signal"), "CR-"))
    fs = by_id(section(spec, "11. Findings"), "F-")
    sev = [r[1] for r in fs.values()]
    n["f"] = "/".join(str(x) for x in (len(fs), *[sev.count(s) for s in SEVERITIES]))
    n["f-blocking"] = sev.count("Blocking")
    n["c"] = len(by_id(section(spec, "12.1 Contradictions"), "C-"))
    n["g"] = len(by_id(section(spec, "12.2 Gaps"), "G-"))
    n["q"] = len(by_id(section(spec, "12.3 Open questions"), "Q-"))
    n["a"] = len(by_id(section(spec, "12.4 Copy-ready amendments"), "A-"))
    n["hr"] = len(
        re.findall(r"^- \*\*HR-\d+\*\*", section(spec, "12.5 Heuristic findings"), re.MULTILINE)
    )
    n["ks"] = len(by_id(section(spec, "14. The keyboard-only five-task walkthrough"), "KS-"))
    n["gherkin-features"] = len(
        re.findall(r"^Feature: ", section(spec, "13. The screen-reader script"), re.MULTILINE)
    )
    n["gherkin-scenarios"] = len(
        re.findall(r"^  Scenario: ", section(spec, "13. The screen-reader script"), re.MULTILINE)
    )
    n["data-rows"] = len(rows(section(spec, "16.2 Rendered fields")))
    n["g-carried"] = len(rows(section(spec, "16.3 Carried by id")))
    n["redline-rows"] = sum(len(rows(section(spec, f"17.{i} "))) for i in (1, 2, 3, 4))
    n["token-rows"] = len(rows(section(spec, "17.5 Token map")))
    n["state-families"] = len(rows(section(spec, "18. The state matrix")))
    n["components"] = len(rows(section(spec, "19. The component inventory")))
    n["frozen"] = len(rows(section(spec, "20.3 The frozen security-bearing set")))
    n["checklist-items"] = len(rows(section(spec, "20.2 The per-screen QA checklist")))
    n["icons"] = len(rows(section(spec, "21.1 Icons")))
    n["consumers"] = len(rows(section(spec, "24.1 Hand-offs")))
    n["walk"] = len(rows(section(spec, "22.2 The story-role dry run")))
    n["walk-qa"] = len(
        re.findall(r"^\d+\. ", section(spec, "22.3 The walkthrough protocol"), re.MULTILINE)
    )
    n["walk-pointers"] = len(rows(section(spec, "22.4 Where to find it")))
    n["codes-declared"] = len(set().union(*(declared_codes(op) for op in spec_ops(spec))))
    n["codes-routed"] = len(rows(section(spec, "16.4 Declared problem codes")))
    n["d-rows"] = len(
        re.findall(r"^- \*\*D-\d+\*\*", section(spec, "24.6 Deviations"), re.MULTILINE)
    )
    n["pointer-lines"] = 5
    n["recorder-key-chars"] = recorder_key_chars()
    deck = json.loads(ctx.deck) if ctx.deck else {}
    strings = deck.get("strings", {})
    n["deck"] = len(strings)
    n["deck-by-parent"] = "/".join(
        str(sum(1 for e in strings.values() if e.get("parent") == k)) for k in PARENTS
    )
    n["deck-proposed"] = sum(1 for e in strings.values() if e.get("status") == "PROPOSED")
    n["deck-frozen"] = sum(1 for e in strings.values() if e.get("frozen"))
    n["deck-script"] = len(deck.get("script", {}))
    n["parent-deck-rows"] = sum(len(parent_deck_rows(k)) for k in PARENTS)
    _line, cu = union_line()
    n["contrast"] = cu
    n["pins"] = sum(1 for ln in ctx.pins.splitlines() if ln and not ln.startswith("#"))
    n["gates"] = len(GATE_FNS)
    n["mutations"] = len(MUTATIONS)
    n["sprint"] = sprint_values()
    return n


def recorder_key_chars() -> str:
    lens = [
        len(s)
        for k, s, _ in parent_deck_rows("D02")
        if k.startswith("recorder.")
        for s in quoted_in(s) or [s]
    ]
    return f"{max(lens)}/{min(lens)}" if lens else "0/0"


def sprint_start(k: int) -> str | None:
    """Sprint k's first day from `CAL` at origin/main (SPRINT01_START + (k - 1) × SPRINT_DAYS)."""
    import datetime as dt

    text = git_show(HEAD, KEYS["CAL"])
    m = re.search(r"SPRINT01_START = datetime\.date\((\d+), (\d+), (\d+)\)", text)
    d = re.search(r"SPRINT_DAYS = (\d+)", text)
    if not m or not d:
        return None
    start = dt.date(int(m.group(1)), int(m.group(2)), int(m.group(3)))
    return (start + dt.timedelta(days=(k - 1) * int(d.group(1)))).isoformat()


def sprint_values() -> dict[str, str]:
    import datetime as dt

    out: dict[str, str] = {}
    days = re.search(r"SPRINT_DAYS = (\d+)", git_show(HEAD, KEYS["CAL"]))
    for k in (5, 6, 7, 8, 9):
        s, e = sprint_start(k), sprint_start(k + 1)
        if s is None or e is None or days is None:
            return {}
        out[f"s{k:02d}.start"] = s
        out[f"s{k:02d}.end"] = (dt.date.fromisoformat(e) - dt.timedelta(days=1)).isoformat()
    return out


@functools.cache
def consumer_sprints() -> dict[str, int]:
    """`E16.json` at origin/main: ticket key → sprint number (the consumers' due dates)."""
    out: dict[str, int] = {}
    try:
        data = json.loads(git_show(HEAD, KEYS["E16"]))
    except json.JSONDecodeError:
        return out
    for t in data if isinstance(data, list) else []:
        m = re.match(r"Sprint (\d+)", str(t.get("sprint", "")))
        if m and isinstance(t.get("key"), str):
            out[t["key"]] = int(m.group(1))
    return out


def due_of(owner_cell: str) -> str | None:
    """The first named consumer's sprint start, or None when the cell names no consumer."""
    sp = consumer_sprints()
    starts = [sprint_start(sp[c]) for c in CONSUMER.findall(owner_cell) if c in sp]
    dated = [s for s in starts if s]
    return min(dated) if dated else None


# ----------------------------------------------------------------------------- gates


def gate_markers(ctx: Ctx, r: Result, n: dict[str, Any]) -> None:
    seen: set[str] = set()
    for before, key, val in MARKER.findall(ctx.spec):
        if key.startswith("layout."):
            continue  # a parent's own marker, lifted inside a redlines cell
        seen.add(key)
        want = marker_value(n, key)
        if want is None:
            r.fail("G1-MARKER", f"audit:{key} has no computed value")
            continue
        if str(val) != want or before.strip("*") != want:
            r.fail("G1-MARKER", f"audit:{key} reads {before} / {val}, the tool computes {want}")
    for key in MARKER_BARE.findall(ctx.spec):
        if key == "contrast":
            line, _ = union_line()
            if line not in ctx.spec:
                r.fail("G1-MARKER", "the §10.3 union line differs from the tool's")
    if "contrast" not in MARKER_BARE.findall(ctx.spec):
        r.fail("G1-MARKER", "the §10.3 union line is missing")


def marker_value(n: dict[str, Any], key: str) -> str | None:
    if key in n and not isinstance(n[key], dict):
        return str(n[key])
    if key.startswith("sprint."):
        return n.get("sprint", {}).get(key[len("sprint.") :])
    if key.startswith("contrast."):
        cu = n.get("contrast", {})
        sub = key[len("contrast.") :]
        if sub in cu:
            return str(cu[sub])
        if sub.startswith("min-"):
            return f"{cu.get('minima', {}).get(sub[4:], 0):.2f}"
    return None


def gate_inventory(ctx: Ctx, r: Result, n: dict[str, Any]) -> None:
    blk = section(ctx.spec, "2. Inventory")
    found = set()
    for row in rows(blk):
        if len(row) < 4:
            r.fail("G2-INVENTORY", f"row {row[:1]} has fewer than four cells")
            continue
        item, verdict, evidence = row[0], row[2], row[3]
        for s in SURFACES:
            if item.startswith(s):
                found.add(s)
        if not any(verdict.startswith(v) for v in VERDICTS):
            r.fail("G2-INVENTORY", f"{item[:40]}: verdict {verdict!r} is not in the vocabulary")
        if not cites_in(evidence) and "not yet built" not in evidence:
            r.fail("G2-INVENTORY", f"{item[:40]}: the evidence cell carries no cite")
    for s in SURFACES:
        if s not in found:
            r.fail("G2-INVENTORY", f"{s} is not in the inventory")


def gate_keys(ctx: Ctx, r: Result, n: dict[str, Any]) -> None:
    blk = section(ctx.spec, "3. The consolidated keyboard model")
    for kid, row in by_id(blk, "KB-").items():
        if len(row) < 10:
            r.fail("G3-KEYS", f"{kid}: fewer than ten cells")
            continue
        if not cites_in(row[9]):
            r.fail("G3-KEYS", f"{kid}: no source cite")
        for lit in KEY_LITERAL.findall(row[5]):
            if KEY_LIKE.match(lit) and not KEY_VOCAB.match(f"`{lit}`"):
                r.fail("G3-KEYS", f"{kid}: binds a key outside the merged vocabulary: {lit}")
    if "no key bound anywhere" not in blk:
        r.fail("G3-KEYS", "the consolidation sentence (no key bound anywhere) is missing")


def gate_focus(ctx: Ctx, r: Result, n: dict[str, Any]) -> None:
    blk = section(ctx.spec, "4. The focus model")
    for fid, row in by_id(blk, "FM-").items():
        if len(row) < 7:
            r.fail("G4-FOCUS", f"{fid}: fewer than seven cells")
            continue
        dest = row[3]
        if not dest or re.search(r"\bbody\b", dest) or not FOCUS_RE.match(dest):
            r.fail(
                "G4-FOCUS",
                f"{fid}: destination {dest[:40]!r} is empty, body or outside the vocabulary",
            )
        if not cites_in(row[5]) and "PROPOSED" not in dest:
            r.fail("G4-FOCUS", f"{fid}: no source cite")
    for pro in re.findall(r"PROPOSED \((F-\d\d)\)", blk):
        if pro not in by_id(section(ctx.spec, "11. Findings"), "F-"):
            r.fail("G4-FOCUS", f"a PROPOSED destination names {pro}, which is not an F row")


def gate_regions(ctx: Ctx, r: Result, n: dict[str, Any]) -> None:
    blk = section(ctx.spec, "5. The region and landmark map")
    for rid, row in by_id(blk, "RG-").items():
        if len(row) < 6 or not row[2] or not cites_in(row[5]):
            r.fail("G5-REGIONS", f"{rid}: a role or a source cite is missing")


def gate_script(ctx: Ctx, r: Result, n: dict[str, Any]) -> None:
    blk = section(ctx.spec, "6.1 The script table")
    deck = json.loads(ctx.deck) if ctx.deck else {}
    script = deck.get("script", {})
    for sid, row in by_id(blk, "SR-").items():
        if len(row) < 8:
            r.fail("G6-SCRIPT", f"{sid}: fewer than eight cells")
            continue
        string, pol, src = row[2], row[3], row[6]
        if not any(pol.startswith(p) for p in POLITENESS):
            r.fail("G6-SCRIPT", f"{sid}: politeness {pol!r} outside the vocabulary")
        if "PROPOSED" in string or "G-" in string or "no merged string" in string:
            continue
        keys = {c[0] for c in cites_in(src)} or {c[0] for c in cites_in(string)}
        for q in quoted_in(string):
            if not any(source_has(k, q) for k in keys):
                r.fail("G6-SCRIPT", f"{sid}: {q[:50]!r} is not verbatim in {sorted(keys)}")
        ent = script.get(sid)
        if not ent or norm(ent.get("string", "")) != norm(strip_md(string)):
            r.fail("G6-SCRIPT", f"{sid}: the deck's script entry is missing or differs")
    for sid in script:
        if sid not in by_id(blk, "SR-"):
            r.fail("G6-SCRIPT", f"the deck's script entry {sid} has no SR row")


def gate_budget(ctx: Ctx, r: Result, n: dict[str, Any]) -> None:
    blk = section(ctx.spec, "7. The announcement budget")
    bg = by_id(blk, "BG-")
    if not any("at most once every 10 s" in row[1] for row in bg.values()):
        r.fail("G7-BUDGET", "no BG row carries the 10 s rule (T AC2)")
    if not any("never swallows an assertive row" in row[1] for row in bg.values()):
        r.fail("G7-BUDGET", "no BG row carries the coalescing precision (R369 BQ-13)")
    if not any(
        "one announcement at a job's start and one per terminal state" in row[1]
        for row in bg.values()
    ):
        r.fail("G7-BUDGET", "no BG row carries D04 :357's job rule")
    for bid, row in bg.items():
        if len(row) < 3 or not cites_in(row[2]):
            r.fail("G7-BUDGET", f"{bid}: no source cite")


def gate_t2(ctx: Ctx, r: Result, n: dict[str, Any]) -> None:
    blk = section(ctx.spec, "8.1 The T2 table")
    for tid, row in by_id(blk, "T2-").items():
        if len(row) < 9:
            r.fail("G8-T2", f"{tid}: fewer than nine cells")
            continue
        if row[4] not in CLASSES:
            r.fail("G8-T2", f"{tid}: class {row[4]!r} outside the parents' class words")
        if not FOCUS_RE.match(row[6]):
            r.fail("G8-T2", f"{tid}: Focus {row[6][:30]!r} outside the vocabulary")
        if row[4] == "T2" and "1a–d" not in row[7]:
            r.fail("G8-T2", f"{tid}: a T2 row without the G-T2.1a–d check")
        if not cites_in(row[8]):
            r.fail("G8-T2", f"{tid}: no source cite")
    for key, s, _ in parent_deck_rows("D02"):
        if key.startswith("recorder."):
            for q in quoted_in(s):
                if len(q) > 60 or not q.endswith("."):
                    r.fail("G8-T2", f"{key}: {q!r} breaks the 60-character / full-stop bar")


def f_citations(fs: dict[str, list[str]]) -> dict[str, tuple[set[str], set[int], set[str]]]:
    """Per Minor-or-above F row: the `05` clause labels, the `05` lines and the WCAG numbers its
    closing tag names (an Info row never re-verdicts a clause)."""
    out: dict[str, tuple[set[str], set[int], set[str]]] = {}
    for fid, row in fs.items():
        if len(row) < 3 or row[1] == "Info":
            continue
        m = F_TAG.search(row[2])
        tag = m.group(1) if m else ""
        lines = {ln for k, a, b in cites_in(tag) if k == "05" for ln in range(a, b + 1)}
        out[fid] = (set(TAG_CLAUSE.findall(tag)), lines, set(TAG_WCAG.findall(tag)))
    return out


def gate_verdicts(ctx: Ctx, r: Result, n: dict[str, Any]) -> None:
    """G9: R-3's vocabulary; `non-compliant` needs a Blocking row, `at risk` a Major row or an
    interim path; a clause or criterion any Minor-or-above F row cites (by `05` label, `05` line
    or WCAG number in the F row's closing tag) is never `compliant`, and its Row cell names them."""
    fs = by_id(section(ctx.spec, "11. Findings"), "F-")
    cites = f_citations(fs)
    for head in ("10.1 `05` clauses", "10.2 WCAG 2.2 cross-walk"):
        for row in rows(section(ctx.spec, head)):
            if len(row) < 4:
                r.fail("G9-VERDICT", f"{head}: {row[:1]} has fewer than four cells")
                continue
            verdict, evidence, ref = row[1], row[2], row[3]
            if not CLAUSE_VERDICT.match(verdict):
                r.fail("G9-VERDICT", f"{row[0][:30]}: verdict {verdict!r} outside R-3")
            named = re.findall(r"F-\d\d", ref)
            if verdict == "non-compliant" and not any(
                fs.get(f, ["", ""])[1] == "Blocking" for f in named
            ):
                r.fail("G9-VERDICT", f"{row[0][:30]}: non-compliant without a Blocking F row")
            if verdict.startswith("at risk") and not (
                any(fs.get(f, ["", ""])[1] == "Major" for f in named)
                or "interim path" in verdict
                or "interim" in evidence
            ):
                r.fail(
                    "G9-VERDICT", f"{row[0][:30]}: at risk without a Major F row or an interim path"
                )
            for f in named:
                if f not in fs:
                    r.fail("G9-VERDICT", f"{row[0][:30]} names {f}, which is not an F row")
            if head.startswith("10.1"):
                m = CLAUSE_LABEL.match(row[0])
                label = m.group(1) if m else ""
                lines = {
                    ln for k, a, b in cites_in(evidence) if k == "05" for ln in range(a, b + 1)
                }
                citing = sorted(
                    f
                    for f, (labels, flines, _) in cites.items()
                    if label in labels or flines & lines
                )
            else:
                crit = row[0].split()[0]
                citing = sorted(f for f, (_, _, wcag) in cites.items() if crit in wcag)
            if not citing:
                continue
            if verdict.startswith("compliant"):
                r.fail(
                    "G9-VERDICT",
                    f"{row[0][:30]}: reads compliant while {', '.join(citing)} cite it (Minor or above)",
                )
            if ref.strip() == "none":
                r.fail(
                    "G9-VERDICT", f"{row[0][:30]}: Row reads none while {', '.join(citing)} cite it"
                )
            missing = [f for f in citing if f not in named]
            if missing:
                r.fail("G9-VERDICT", f"{row[0][:30]}: Row does not name {', '.join(missing)}")


def gate_findings(ctx: Ctx, r: Result, n: dict[str, Any]) -> None:
    blk = section(ctx.spec, "11. Findings")
    fs = by_id(blk, "F-")
    for fid, row in fs.items():
        if len(row) < 8:
            r.fail("G10-FINDINGS", f"{fid}: fewer than eight cells")
            continue
        sev, sentence, owner, target, gt2, focus = row[1], row[2], row[4], row[5], row[6], row[7]
        if sev not in SEVERITIES:
            r.fail("G10-FINDINGS", f"{fid}: severity {sev!r}")
        if not OWNER_RE.match(owner) or PERSON_WORDS.search(owner):
            r.fail("G10-FINDINGS", f"{fid}: owner {owner!r} is not a spec and its area")
        if not TARGET_RE.search(target) and "DS owner" not in target and "E16-D07" not in target:
            r.fail("G10-FINDINGS", f"{fid}: target names no consuming story")
        if sev != "Info" and "next text touch" not in target:
            r.fail("G10-FINDINGS", f"{fid}: target lacks the parent's next text touch")
        if not gt2 or not focus:
            r.fail("G10-FINDINGS", f"{fid}: G-T2 or Focus cell empty")
        if gt2 not in CLASSES and not gt2.startswith("T2 ·"):
            r.fail("G10-FINDINGS", f"{fid}: G-T2 {gt2!r} outside the class words")
        if not FOCUS_RE.match(focus):
            r.fail("G10-FINDINGS", f"{fid}: Focus {focus[:30]!r} outside the vocabulary")
        if not cites_in(sentence):
            r.fail("G10-FINDINGS", f"{fid}: the merged sentence carries no cite")
    blocking = [f for f, row in fs.items() if len(row) > 1 and row[1] == "Blocking"]
    if blocking and HOLD not in blk:
        r.fail("G10-FINDINGS", "a Blocking row without the Ready hold on E16-S01 / S03 / S04")
    if not blocking and "no f row is blocking" not in strip_md(blk).lower():
        r.fail(
            "G10-FINDINGS",
            "the register must say that no F row is Blocking (the hold is not armed)",
        )


def gate_rows(ctx: Ctx, r: Result, n: dict[str, Any]) -> None:
    """G11: every C / G / Q / A row filled; every G and Q row carries an Owner and a Due cell, the
    due date = the first named consumer's sprint start (`E16.json` × `CAL`), else a sprint start."""
    all_starts = set(n.get("sprint", {}).values())
    for head, prefix, width, owner_col, due_col in (
        ("12.1 Contradictions", "C-", 3, None, None),
        ("12.2 Gaps", "G-", 4, 2, 3),
        ("12.3 Open questions", "Q-", 5, 3, 4),
        ("12.4 Copy-ready amendments", "A-", 5, None, None),
    ):
        ids = by_id(section(ctx.spec, head), prefix)
        if not ids:
            r.fail("G11-ROWS", f"{head}: no {prefix} rows")
        for rid, row in ids.items():
            if len(row) < width or any(not c for c in row[:width]):
                r.fail("G11-ROWS", f"{rid}: an empty cell")
                continue
            if prefix == "G-" and not re.search(r"E16-|owner|E05-T06|#2701", row[2]):
                r.fail("G11-ROWS", f"{rid}: no owner lane")
            if owner_col is None or due_col is None:
                continue
            owner, due = row[owner_col], row[due_col]
            if not owner.strip() or PERSON_WORDS.search(owner):
                r.fail("G11-ROWS", f"{rid}: the Owner cell is empty or names a person")
            m = re.search(r"\d{4}-\d{2}-\d{2}", due)
            want = due_of(owner)
            if not m:
                r.fail("G11-ROWS", f"{rid}: the Due cell carries no date")
            elif want is not None and m.group(0) != want:
                r.fail("G11-ROWS", f"{rid}: due {m.group(0)}, the consumer's sprint starts {want}")
            elif want is None and m.group(0) not in all_starts:
                r.fail("G11-ROWS", f"{rid}: due {m.group(0)} is no sprint start")
    gaps = by_id(section(ctx.spec, "12.2 Gaps"), "G-")
    for row in rows(section(ctx.spec, "16.3 Carried by id")):
        if len(row) < 5 or not re.search(r"\d{4}-\d{2}-\d{2}", row[-1]):
            r.fail("G11-ROWS", f"carried gap {row[:1]}: no due date")
    if not gaps:
        return
    for sid in ("E16-S01", "E16-S03", "E16-S04", "E16-S05"):
        if sid not in section(ctx.spec, "24.1 Hand-offs"):
            r.fail("G11-ROWS", f"the hand-off table names no {sid} row")


def gate_ruled(ctx: Ctx, r: Result, n: dict[str, Any]) -> None:
    blk = section(ctx.spec, "R. Rulings applied")
    got = by_id(blk, "BQ-")
    for bq in BQ_IDS:
        row = got.get(bq)
        if not row:
            r.fail("G12-RULED", f"{bq} has no row in §R")
        elif RULED_STAMP not in row[-1]:
            r.fail("G12-RULED", f"{bq}: the status cell lacks the ruling stamp")
    for stamp in set(re.findall(r"RULED BQ-(\d\d)", ctx.spec)):
        if f"BQ-{stamp}" not in got:
            r.fail("G12-RULED", f"a stamp points at BQ-{stamp}, which has no §R row")
    if RULING_ID not in ctx.spec.split("\n## R.")[0]:
        r.fail("G12-RULED", "the header does not name the ruling of record")


def parse_pins(text: str) -> dict[tuple[str, int], str]:
    out: dict[tuple[str, int], str] = {}
    for ln in text.splitlines():
        if not ln or ln.startswith("#"):
            continue
        key, line, words = ln.split("|", 2)
        out[(key, int(line))] = words
    return out


def endpoints(spec: str) -> set[tuple[str, int]]:
    out: set[tuple[str, int]] = set()
    for key, a, b in cites_in(spec):
        out.add((key, a))
        out.add((key, b))
    return out


def gate_cite(ctx: Ctx, r: Result, n: dict[str, Any]) -> None:
    pins = parse_pins(ctx.pins)
    for key, a, b in CITE.findall(ctx.spec):
        if key not in KEYS:
            r.fail("G13-CITE", f"unknown cite key `{key}`")
    for key, line in sorted(endpoints(ctx.spec)):
        src = source_lines(key)
        if line >= len(src) or not src[line].strip():
            r.fail("G13-CITE", f"`{key}`:{line} is past the end or blank at {HEAD}")
            continue
        pin = pins.get((key, line))
        if pin is None:
            r.fail("G13-CITE", f"`{key}`:{line} has no pin (run --repin-ruled)")
        elif not norm(src[line]).startswith(norm(pin)):
            r.fail(
                "G13-CITE", f"`{key}`:{line} moved: the pinned words no longer stand on that line"
            )
    for key, line in pins:
        if (key, line) not in endpoints(ctx.spec):
            r.warn("G13-CITE", f"stale pin `{key}`:{line} (run --repin-ruled)")


def repin(ctx: Ctx) -> int:
    lines = [RULED_PIN_HEADER.rstrip("\n")]
    count = 0
    for key, line in sorted(endpoints(ctx.spec)):
        src = source_lines(key)
        if line < len(src) and src[line].strip():
            lines.append(f"{key}|{line}|{norm(src[line])[:70]}")
            count += 1
    PINS.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return count


def gate_colour(ctx: Ctx, r: Result, n: dict[str, Any]) -> None:
    _line, cu = union_line()
    if cu["union_fail"]:
        r.fail("G14-COLOUR", f"the contrast union has {cu['union_fail']} gated FAIL")
    blk = section(ctx.spec, "10.4 Colour never the only signal")
    for cid, row in by_id(blk, "CR-").items():
        if len(row) < 7:
            r.fail("G14-COLOUR", f"{cid}: fewer than seven cells")
            continue
        if cid in CR_TOKENS:
            dl, dee = carrier(*CR_TOKENS[cid])
            if row[4] != dl or row[5] != dee:
                r.fail(
                    "G14-COLOUR",
                    f"{cid}: reads {row[4]} / {row[5]}, the tool computes {dl} / {dee}",
                )
        elif row[4] != "not measured":
            r.fail("G14-COLOUR", f"{cid}: not a measured family but carries a number")
        if "distinguishable by carrier" not in row[6]:
            r.fail("G14-COLOUR", f"{cid}: verdict is not 'distinguishable by carrier'")
    tokens = set(
        re.findall(
            r"`((?:color|size|space|type|radius|elevation|motion|font|opacity)\.[a-z0-9.\-]+)`",
            section(ctx.spec, "17.5 Token map"),
        )
    )
    for tok in sorted(tokens):
        unresolved = tok.startswith("color.") and all(hx(tok, th) is None for th in D05T.THEMES)
        if unresolved and "MISSING" not in rows_of_token(ctx.spec, tok):
            r.fail(
                "G14-COLOUR",
                f"{tok} does not resolve in any theme and its row does not say MISSING",
            )


def rows_of_token(spec: str, tok: str) -> str:
    for row in rows(section(spec, "17.5 Token map")):
        if row and f"`{tok}`" in row[0]:
            return " ".join(row)
    return ""


def gate_hygiene(ctx: Ctx, r: Result, n: dict[str, Any]) -> None:
    for name, text in (
        ("spec", ctx.spec),
        ("deck", ctx.deck),
        ("pins", ctx.pins),
        ("tool", Path(__file__).read_text(encoding="utf-8")),
    ):
        for pat, what in (
            (URL, "a URL"),
            (UUID, "a UUID / page or file id"),
            (LOCAL_PATH, "a local path"),
            (ADVISORY_ID, "an advisory-style identifier"),
        ):
            m = pat.search(text)
            if m and name != "tool":
                r.fail("G15-HYGIENE", f"{name} carries {what}: {m.group(0)[:30]}")
        if name in ("spec", "deck"):
            m = HOST.search(text)
            if m and not m.group(0).lower().startswith(("e16-", "d0")):
                r.fail("G15-HYGIENE", f"{name} carries a host-like token: {m.group(0)}")
            m = LOOPBACK.search(text)
            if m:
                r.fail("G15-HYGIENE", f"{name} carries a loopback host or a port: {m.group(0)}")
            m = RECORD_WORDS.search(text)
            if m:
                r.fail(
                    "G15-HYGIENE",
                    f"{name} carries a word that would name a private record: {m.group(0)}",
                )
            m = PERSON_WORDS.search(text)
            if m:
                r.fail("G15-HYGIENE", f"{name} names a person, a lane or a role: {m.group(0)}")
    if re.search(r"\b(?:Closes|Fixes|Resolves)\s+#\d+", ctx.spec, re.IGNORECASE):
        r.fail("G15-HYGIENE", "the spec carries a closing keyword before an issue number")


def gate_deck(ctx: Ctx, r: Result, n: dict[str, Any]) -> None:
    try:
        deck = json.loads(ctx.deck)
    except json.JSONDecodeError as exc:
        r.fail("G16-DECK", f"the deck is not valid JSON: {exc}")
        return
    strings = deck.get("strings", {})
    missing = 0
    for key in PARENTS:
        for dk, s, cite in parent_deck_rows(key):
            ent = strings.get(dk)
            if ent is None:
                missing += 1
                r.fail("G16-DECK", f"{key} row {dk} ({cite}) is missing from the deck")
                continue
            src = ent.get("sources", {}).get(key)
            if src is None or norm(src) != norm(s):
                r.fail(
                    "G16-DECK", f"{dk}: the deck's {key} string is not the parent's cell verbatim"
                )
    for dk, ent in strings.items():
        for k in ("parent", "surface", "string", "provenance", "status"):
            if k not in ent:
                r.fail("G16-DECK", f"{dk}: field {k} missing")
        if (
            ent.get("status") == "PROPOSED"
            and "PROPOSED" not in ent.get("provenance", "")
            and "new" not in ent.get("provenance", "")
        ):
            r.fail("G16-DECK", f"{dk}: PROPOSED without a provenance saying so")
    if deck.get("pack") != "E16-D06":
        r.fail("G16-DECK", "the deck's pack field is not E16-D06")
    n["deck-missing"] = missing


def gate_frozen(ctx: Ctx, r: Result, n: dict[str, Any]) -> None:
    blk = section(ctx.spec, "20.3 The frozen security-bearing set")
    deck = json.loads(ctx.deck) if ctx.deck else {}
    strings = deck.get("strings", {})
    ids = [row[0] for row in rows(blk)]
    want = ["(i)", "(ii)", "(iii)", "(iv)", "(v)", "(vi)", "(vii)", "(viii)", "(ix)"]
    if ids != want:
        r.fail("G17-FROZEN", f"the frozen set is {ids}, not rows (i)–(ix)")
    for row in rows(blk):
        if len(row) < 5:
            r.fail("G17-FROZEN", f"{row[0]}: fewer than five cells")
            continue
        text, hook = row[1], row[4]
        keys = {c[0] for c in cites_in(text)}
        if not keys or not keys <= set(PUBLIC_KEYS):
            r.fail(
                "G17-FROZEN",
                f"{row[0]}: cites outside the merged public set: {sorted(keys - set(PUBLIC_KEYS))}",
            )
        for q in quoted_in(text):
            if not any(source_has(k, q) for k in keys):
                r.fail("G17-FROZEN", f"{row[0]}: {q[:50]!r} is not verbatim in {sorted(keys)}")
        hooks = re.findall(r"`([a-z][a-z0-9_.]+)`", hook)
        if not hooks and "test:" not in hook:
            r.fail("G17-FROZEN", f"{row[0]}: the hook names no deck key and no test")
        for h in hooks:
            if (
                h.startswith(
                    ("recorder.", "storage.", "retention.", "empty.", "rbac.", "notice.", "d02.")
                )
                and h not in strings
            ):
                r.fail("G17-FROZEN", f"{row[0]}: hook {h} is not a deck key")
    if "names no review record" not in blk and "quoted from merged public text" not in blk:
        r.fail("G17-FROZEN", "the frozen set lacks its public-text sentence")


def gate_redlines(ctx: Ctx, r: Result, n: dict[str, Any]) -> None:
    heads = {
        "17.1 ": ("D02", "11.1 Token map"),
        "17.2 ": ("D03", "11. Tokens and redlines"),
        "17.3 ": ("D04", "11. Tokens and redlines"),
        "17.4 ": ("D05", "11. Tokens and redlines"),
    }
    for head, (key, phead) in heads.items():
        want_cells = 3 if key == "D05" else 2
        parent = {
            norm(row[0]): norm(row[1])
            for row in rows(section(git_show(HEAD, KEYS[key]), phead))
            if len(row) == want_cells and row[0] not in ("Element", "Frame")
        }
        mine = rows(section(ctx.spec, head))
        if not mine:
            r.fail("G18-REDLINES", f"{head}: no rows")
        for row in mine:
            if len(row) < 3:
                r.fail("G18-REDLINES", f"{head} {row[:1]}: fewer than three cells")
                continue
            el, toks, src = norm(row[0]), norm(row[1]), row[2]
            if el not in parent:
                r.fail("G18-REDLINES", f"{head} {el[:30]!r}: no such Element in {key}")
            elif parent[el] != toks:
                r.fail("G18-REDLINES", f"{head} {el[:30]!r}: the Tokens cell differs from {key}'s")
            if not cites_in(src):
                r.fail("G18-REDLINES", f"{head} {el[:30]!r}: no source cite")
        if len(mine) != len(parent):
            r.fail("G18-REDLINES", f"{head}: {len(mine)} rows lifted, {key} has {len(parent)}")
    if "never measured" not in section(ctx.spec, "17. Redlines"):
        r.fail("G18-REDLINES", "the redlines section lacks 'tool-lifted, never measured'")


def gate_states(ctx: Ctx, r: Result, n: dict[str, Any]) -> None:
    imgs = set(images())
    blk = section(ctx.spec, "18. The state matrix")
    text_bound = 0
    for row in rows(blk):
        if len(row) < 4:
            r.fail("G19-STATES", f"{row[:1]}: fewer than four cells")
            continue
        for png in re.findall(r"`(E16-D0[2-5]-[0-9a-z\-]+\.png)`", row[2]):
            if png not in imgs:
                r.fail("G19-STATES", f"{row[0][:30]}: {png} is not committed")
        if "text-bound" in row[3]:
            text_bound += (
                int(re.search(r"(\d+) text-bound", row[3]).group(1))
                if re.search(r"(\d+) text-bound", row[3])
                else 1
            )
        if not cites_in(row[1]) and not cites_in(row[2]):
            r.fail("G19-STATES", f"{row[0][:30]}: no cite")
    if text_bound != 13:
        r.fail("G19-STATES", f"{text_bound} text-bound D02 states flagged, the ruling names 13")


def gate_components(ctx: Ctx, r: Result, n: dict[str, Any]) -> None:
    cat = git_show(HEAD, KEYS["15"])
    for row in rows(section(ctx.spec, "19. The component inventory")):
        if len(row) < 5:
            r.fail("G20-COMPONENTS", f"{row[:1]}: fewer than five cells")
            continue
        for cid in re.findall(r"CMP-\d{3}", row[0]):
            if f"### {cid} " not in cat:
                r.fail("G20-COMPONENTS", f"{cid} has no `15` heading")
        if re.search(r"\bbuilt\b", row[3]) and "never" not in row[3]:
            r.fail("G20-COMPONENTS", f"{row[0][:30]}: the Storybook column claims 'built'")
    blk = section(ctx.spec, "19. The component inventory")
    if "CMP-177" not in blk or "nineteen" not in blk and "19 stories" not in blk:
        r.fail("G20-COMPONENTS", "CMP-177's nineteen required stories are not named")


def gate_icons(ctx: Ctx, r: Result, n: dict[str, Any]) -> None:
    reg = set(re.findall(r"^  ([a-z][a-zA-Z\-]*): \{", git_show(HEAD, KEYS["ICONS"]), re.MULTILINE))
    for row in rows(section(ctx.spec, "21.1 Icons")):
        if len(row) < 5:
            r.fail("G21-ICONS", f"{row[:1]}: fewer than five cells")
            continue
        key, status = row[1].strip("`"), row[2]
        if status.startswith("present"):
            if key not in reg:
                r.fail("G21-ICONS", f"{row[0]}: {key!r} is not in the registry")
        elif status.startswith("absent"):
            if key not in ("—", "") and key in reg:
                r.fail("G21-ICONS", f"{row[0]}: claimed absent but {key!r} is registered")
            if "E05-T06" not in status and "rendered" not in status and "shell" not in status:
                r.fail("G21-ICONS", f"{row[0]}: an absent glyph not routed")
        else:
            r.fail("G21-ICONS", f"{row[0]}: status {status[:20]!r}")
    if "No SVG" not in section(ctx.spec, "21. Assets") and "no SVG" not in section(
        ctx.spec, "21. Assets"
    ):
        r.fail("G21-ICONS", "the assets section does not say no SVG is copied")


def gate_edit_set(ctx: Ctx, r: Result, n: dict[str, Any]) -> None:
    for key in UNTOUCHED:
        if git_diff_names(KEYS[key]).strip():
            r.fail(
                "G22-EDIT-SET", f"{key} differs from {HEAD}: the parents and `15` are never edited"
            )
    diff = git_diff_names(KEYS["14"])
    added = [ln[1:] for ln in diff.splitlines() if ln.startswith("+") and not ln.startswith("+++")]
    removed = [ln for ln in diff.splitlines() if ln.startswith("-") and not ln.startswith("---")]
    if removed:
        r.fail(
            "G22-EDIT-SET",
            f"`14` has {len(removed)} removed or changed lines; only pointer lines may be added",
        )
    if added and len(added) != 5:
        r.fail("G22-EDIT-SET", f"`14` has {len(added)} added lines, not five pointer lines")
    for ln in added:
        if (
            POINTER_MARK not in ln
            or "[E16-D06.md](../design/E16/E16-D06.md)" not in ln
            or "owner approval pending" not in ln
        ):
            r.fail("G22-EDIT-SET", f"`14` added line is not a pointer line: {ln[:60]}")
        if "[x]" in ln or "[ ]" in ln:
            r.fail("G22-EDIT-SET", "a `14` pointer line carries a checklist tick")
    head14 = git_show(HEAD, KEYS["14"]).split("\n")
    work14 = (ROOT / KEYS["14"]).read_text(encoding="utf-8").split("\n")
    if added:
        for scr, anchor in POINTER_ANCHORS.items():
            idx = next((i for i, ln in enumerate(work14) if ln.startswith(anchor)), None)
            if idx is None or idx + 1 >= len(work14) or POINTER_MARK not in work14[idx + 1]:
                r.fail("G22-EDIT-SET", f"{scr}: the pointer line does not follow its anchor line")
    n["14-added"] = len(added)
    del head14


WALK_SELF = "self-counted by an independent fresh-context reader"
WALK_DISPOSITION = re.compile(r"pointer (\d+) · C (\d+) · G (\d+) · Q (\d+)")
WALK_ROLES = (
    "story: E16-S01 (#484)",
    "story: E16-S03 (#485)",
    "story: E16-S04 (#486)",
    "story: E16-S05 (#487)",
    "story: E16-S02 (#566)",
    "QA: E16-Q01 (#404)",
    "QA: E16-Q05 (#482)",
    "frontend: the FE-lead read",
)
ROW_REF = re.compile(r"\b(?:C-[a-z]|[GQF]-\d\d|§22\.4|§16\.4)\b")


def gate_walk(ctx: Ctx, r: Result, n: dict[str, Any]) -> None:
    """G23: the dry run is filled (BQ-16) — one self-counted row per reader whose dispositions
    add up to its not-found count, a Q&A whose every item names a row, and the pointer table."""
    walk = section(ctx.spec, "22.2 The story-role dry run")
    qa = section(ctx.spec, "22.3 The walkthrough protocol")
    where = section(ctx.spec, "22.4 Where to find it")
    for name, blk in (("G-WALK", walk), ("the Q&A", qa)):
        if PENDING_WALK in blk or not blk.strip():
            r.fail("G23-WALK", f"{name} is still the pending placeholder")
    if WALK_SELF not in walk:
        r.fail("G23-WALK", "G-WALK does not say the counts are the readers' own")
    pointer_rows: dict[str, int] = {}
    for row in rows(where):
        if row:
            pointer_rows[row[0]] = pointer_rows.get(row[0], 0) + 1
    seen: list[str] = []
    for row in rows(walk):
        if len(row) < 6:
            r.fail("G23-WALK", f"walk row {row[:1]}: fewer than six cells")
            continue
        date, role, needs, found, notfound, disp = row[:6]
        seen.append(role)
        ints = [
            int(m0.group(0)) if (m0 := re.match(r"\d+", c)) else -1
            for c in (needs, found, notfound)
        ]
        if not re.fullmatch(r"\d{4}-\d{2}-\d{2}", date) or min(ints) < 0:
            r.fail("G23-WALK", f"{role}: the date or a count is not filled")
            continue
        m = WALK_DISPOSITION.search(disp)
        if not m:
            r.fail("G23-WALK", f"{role}: the disposition names no pointer · C · G · Q counts")
        elif sum(int(g) for g in m.groups()) != ints[2]:
            r.fail("G23-WALK", f"{role}: the dispositions do not add up to its not-found count")
        tag = re.search(r"§22\.4 \((\w+)\)", disp)
        if m and not tag:
            r.fail("G23-WALK", f"{role}: the disposition names no §22.4 consumer tag")
        elif m and tag and pointer_rows.get(tag.group(1), 0) != int(m.group(1)):
            r.fail(
                "G23-WALK",
                f"{role}: pointer {m.group(1)}, §22.4 has {pointer_rows.get(tag.group(1), 0)} "
                f"{tag.group(1)} rows",
            )
    for role in WALK_ROLES:
        if not any(s.startswith(role) for s in seen):
            r.fail("G23-WALK", f"G-WALK has no row for {role}")
    items = re.findall(r"^\d+\. (.+)$", qa, re.MULTILINE)
    if not items:
        r.fail("G23-WALK", "the Q&A has no numbered items")
    for it in items:
        if not ROW_REF.search(it):
            r.fail("G23-WALK", f"a Q&A item names no row: {strip_md(it)[:50]!r}")
    if len(rows(where)) < len(WALK_ROLES):
        r.fail("G23-WALK", "the where-to-find-it table is missing or too short")
    for row in rows(where):
        if len(row) < 3 or not CITE.search(row[2]):
            r.fail("G23-WALK", f"pointer row {row[:1]}: no cite by content")
    if "No session" not in section(ctx.spec, "22. ") and "no session" not in section(
        ctx.spec, "22. "
    ):
        r.fail("G23-WALK", "the walkthrough section does not say no session was held")


CODE_TOKEN = re.compile(r"\b(?:400|403|404|409|422|503)\s+([a-z]+_[a-z_]+|conflict)\b")
CODE_RULE = re.compile(r"\brule:?\s+([a-z]+_[a-z_]+)\b")
CODE_PAREN = re.compile(r"\(([a-z]+_[a-z_]+)\)")


def spec_ops(spec: str) -> set[str]:
    return set(re.findall(r"`([a-z][A-Za-z]+)`", section(spec, "16.1 The operation set")))


def declared_codes(op: str) -> set[str]:
    """Every problem code `22` declares in an operation's block at origin/main (the description
    and its responses), read from the text: `NNN code`, `rule code` and a bare `(code)`."""
    src = source_lines("22")
    start = next((i for i, ln in enumerate(src) if ln.strip() == f"operationId: {op}"), None)
    if start is None:
        return set()
    end = start + 1
    while end < len(src) and not re.match(r"^\s{2,6}(?:operationId:|/[a-z])", src[end]):
        end += 1
    text = " ".join(ln.strip() for ln in src[start:end]).replace("`", "")
    found = set(CODE_TOKEN.findall(text)) | set(CODE_RULE.findall(text))
    found |= set(CODE_PAREN.findall(text))
    return {c for c in found if c not in ("x_rbac", "x_idempotency")}


def gate_codes(ctx: Ctx, r: Result, n: dict[str, Any]) -> None:
    """G26: every code a §16.1 operation declares in `22` has a row in §16.4 that routes it to a
    deck key, the step-up flow or the generic T4 sentence; nothing routes to the body's text."""
    ops = spec_ops(ctx.spec)
    blk = section(ctx.spec, "16.4 Declared problem codes")
    deck = json.loads(ctx.deck) if ctx.deck else {}
    strings = deck.get("strings", {})
    table = rows(blk)
    if not table:
        r.fail("G26-CODES", "§16.4 has no code table")
        return
    routed = {re.sub(r"[`*]", "", row[1]).strip() for row in table if len(row) >= 4}
    declared: set[str] = set()
    for op in sorted(ops):
        codes = declared_codes(op)
        declared |= codes
        for code in sorted(codes - routed):
            r.fail("G26-CODES", f"`22` declares {code} on {op}; §16.4 routes it nowhere")
    for row in table:
        if len(row) < 4:
            r.fail("G26-CODES", f"code row {row[:1]}: fewer than four cells")
            continue
        code, route = re.sub(r"[`*]", "", row[1]).strip(), row[3]
        keys = re.findall(r"`([a-z][a-z0-9_.]+)`", route)
        deck_keys = [k for k in keys if k in strings]
        if not deck_keys and "step-up" not in route and "T4" not in route:
            r.fail("G26-CODES", f"{code}: routed to no deck key, step-up flow or T4 sentence")
        if re.search(r"\bmessage\b|\bdetail\b", route) and "never" not in route:
            r.fail("G26-CODES", f"{code}: routes to the problem body's text")
    if "never rendered" not in blk and "never rendered" not in section(
        ctx.spec, "20.3 The frozen security-bearing set"
    ):
        r.fail("G26-CODES", "neither §16.4 nor §20.3 says the body's text is never rendered")


RBAC_BLOCK = re.compile(r"x-rbac: \{ permissions: \[([^\]]*)\], scope: ([a-z_]+) \}")


def rbac_of(op: str) -> tuple[list[str], str] | None:
    """`22`'s x-rbac block for an operation at origin/main: (permissions, scope); None when `22`
    declares no such operationId (the WS topic row)."""
    src = source_lines("22")
    start = next((i for i, ln in enumerate(src) if ln.strip() == f"operationId: {op}"), None)
    if start is None:
        return None
    end = start + 1
    while end < len(src) and not re.match(r"^\s{2,6}(?:operationId:|/[a-z])", src[end]):
        end += 1
    m = RBAC_BLOCK.search(" ".join(ln.strip() for ln in src[start:end]))
    if not m:
        return None
    return [p.strip() for p in m.group(1).split(",") if p.strip()], m.group(2)


def gate_rbac(ctx: Ctx, r: Result, n: dict[str, Any]) -> None:
    """G27: every §16.1 `x-rbac` cell equals `22`'s x-rbac block for each operation on the row —
    each permission as `` `code` · scope `` — and names no permission `22` does not declare there.
    """
    checked = 0
    for row in rows(section(ctx.spec, "16.1 The operation set")):
        if len(row) < 4:
            r.fail("G27-RBAC", f"{row[:1]}: fewer than four cells")
            continue
        ops = re.findall(r"`([a-z][A-Za-z]+)`", row[0])
        cell = row[3]
        declared: set[str] = set()
        for op in ops:
            got = rbac_of(op)
            if got is None:
                continue
            perms, scope = got
            checked += 1
            declared |= set(perms)
            for perm in perms:
                if f"`{perm}` · {scope}" not in cell:
                    r.fail(
                        "G27-RBAC",
                        f"{op}: `22` declares `{perm}` · {scope}; the §16.1 cell reads {cell[:60]!r}",
                    )
        for perm in re.findall(r"`([a-z]+:[a-z]+)`", cell):
            if declared and perm not in declared:
                r.fail(
                    "G27-RBAC",
                    f"{row[0][:40]}: names `{perm}`, which no operation on the row declares",
                )
    if not checked:
        r.fail("G27-RBAC", "no §16.1 operation could be read against `22`")
    n["rbac-ops"] = checked


def gate_calendar(ctx: Ctx, r: Result, n: dict[str, Any]) -> None:
    blk = section(ctx.spec, "23. The design-ahead record")
    sp = n.get("sprint", {})
    for k in ("s06.start", "s06.end", "s08.start"):
        if sp.get(k) and sp[k] not in blk:
            r.fail("G24-CALENDAR", f"the design-ahead record lacks {k} = {sp[k]}")
    if "promises nothing" not in blk and "nothing is promised" not in blk:
        r.fail("G24-CALENDAR", "the design-ahead record must report, not promise")
    if "waived" not in blk:
        r.fail("G24-CALENDAR", "the waiver line is missing")


def gate_xref(ctx: Ctx, r: Result, n: dict[str, Any]) -> None:
    spec = ctx.spec
    defined: set[str] = set()
    for head, prefix in (
        ("3. The consolidated keyboard model", "KB-"),
        ("4. The focus model", "FM-"),
        ("5. The region and landmark map", "RG-"),
        ("6.1 The script table", "SR-"),
        ("7. The announcement budget", "BG-"),
        ("8.1 The T2 table", "T2-"),
        ("8.2 The safety disclosures", "SD-"),
        ("10.4 Colour never the only signal", "CR-"),
        ("11. Findings", "F-"),
        ("12.1 Contradictions", "C-"),
        ("12.2 Gaps", "G-"),
        ("12.3 Open questions", "Q-"),
        ("12.4 Copy-ready amendments", "A-"),
        ("14. The keyboard-only five-task walkthrough", "KS-"),
    ):
        defined |= set(by_id(section(spec, head), prefix))
    used = set(re.findall(r"\b((?:KB|FM|RG|SR|BG|T2|SD|CR|KS|F|G|Q)-\d\d)\b", spec))
    for ref in sorted(used - defined):
        if (
            ref.startswith("G-")
            and re.match(r"G-\d\d$", ref)
            and ref not in defined
            or not ref.startswith("G-")
        ):
            r.fail("G25-XREF", f"{ref} is referenced but not defined")
    for c in set(re.findall(r"\bC-([a-z])\b", spec)):
        if f"C-{c}" not in defined:
            r.fail("G25-XREF", f"C-{c} is referenced but not defined")


GATE_FNS: tuple[tuple[str, Callable[[Ctx, Result, dict[str, Any]], None]], ...] = (
    ("G1-MARKER", gate_markers),
    ("G2-INVENTORY", gate_inventory),
    ("G3-KEYS", gate_keys),
    ("G4-FOCUS", gate_focus),
    ("G5-REGIONS", gate_regions),
    ("G6-SCRIPT", gate_script),
    ("G7-BUDGET", gate_budget),
    ("G8-T2", gate_t2),
    ("G9-VERDICT", gate_verdicts),
    ("G10-FINDINGS", gate_findings),
    ("G11-ROWS", gate_rows),
    ("G12-RULED", gate_ruled),
    ("G13-CITE", gate_cite),
    ("G14-COLOUR", gate_colour),
    ("G15-HYGIENE", gate_hygiene),
    ("G16-DECK", gate_deck),
    ("G17-FROZEN", gate_frozen),
    ("G18-REDLINES", gate_redlines),
    ("G19-STATES", gate_states),
    ("G20-COMPONENTS", gate_components),
    ("G21-ICONS", gate_icons),
    ("G22-EDIT-SET", gate_edit_set),
    ("G23-WALK", gate_walk),
    ("G24-CALENDAR", gate_calendar),
    ("G25-XREF", gate_xref),
    ("G26-CODES", gate_codes),
    ("G27-RBAC", gate_rbac),
)


def run(ctx: Ctx) -> Result:
    r = Result()
    n = compute(ctx)
    for _, fn in GATE_FNS:
        fn(ctx, r, n)
    r.numbers = n
    return r


# ----------------------------------------------------------------------------- fill


def fill(ctx: Ctx) -> int:
    n = compute(ctx)
    changed = 0

    def repl(m: re.Match[str]) -> str:
        nonlocal changed
        want = marker_value(n, m.group(2))
        if want is None or m.group(2).startswith("layout."):
            return m.group(0)
        before = m.group(1)
        bold = before.startswith("**") and before.endswith("**")
        new_before = f"**{want}**" if bold else want
        if new_before != before or m.group(3) != want:
            changed += 1
        return f"{new_before} <!-- audit:{m.group(2)}={want} -->"

    spec = MARKER.sub(repl, ctx.spec)
    line, _ = union_line()
    spec2 = re.sub(r"^\*\*Union:\*\* .*<!-- audit:contrast -->$", line, spec, flags=re.MULTILINE)
    if spec2 != spec:
        changed += 1
    SPEC.write_text(spec2, encoding="utf-8")
    return changed


# ----------------------------------------------------------------------------- self-test

Mut = Callable[[Ctx], Ctx]


def sub(old: str, new: str) -> Mut:
    return lambda c: c._replace(spec=c.spec.replace(old, new, 1))


def regex(pattern: str, repl: str) -> Mut:
    return lambda c: c._replace(spec=re.sub(pattern, repl, c.spec, count=1, flags=re.MULTILINE))


def deck_sub(old: str, new: str) -> Mut:
    return lambda c: c._replace(deck=c.deck.replace(old, new, 1))


def pin_sub(pattern: str, repl: str) -> Mut:
    return lambda c: c._replace(pins=re.sub(pattern, repl, c.pins, count=1, flags=re.MULTILINE))


MUTATIONS: tuple[tuple[str, Mut], ...] = (
    ("G1-MARKER", regex(r"<!-- audit:kb=(\d+) -->", r"<!-- audit:kb=999 -->")),
    ("G2-INVENTORY", regex(r"(\| SCR-141 [^|]*\| surface\s+\| )reviewed", r"\1pending ")),
    (
        "G3-KEYS",
        sub("`↑ ↓` rows (the header row first)", "`Ctrl+Alt+R` `↑ ↓` rows (the header row first)"),
    ),
    ("G4-FOCUS", regex(r"(\| FM-01 [^\n]*?\| )(kept · [^|]*)\|", r"\1moves to · body |")),
    ("G5-REGIONS", sub("`region` landmark (CMP-087)", "")),
    (
        "G6-SCRIPT",
        sub(
            '"SOLUSDT stopped recording" (the batch\'s grammar)',
            '"SOLUSDT has stopped recording" (the batch\'s grammar)',
        ),
    ),
    ("G7-BUDGET", sub("**at most once every 10 s**", "**at most once every 5 s**")),
    ("G8-T2", regex(r"(\| T2-01 [^\n]*?\| )T2(\s+\|)", r"\1T9\2")),
    (
        "G9-VERDICT",
        regex(
            r"(\| 2\.4\.3 Focus order\s+\| )at risk — interim path: [^|]*\|", r"\1non-compliant |"
        ),
    ),
    (
        "G9-VERDICT",  # a cited criterion whose Row cell reads none
        regex(r"^(\| 4\.1\.3 Status messages .*\| )F-07, F-08, F-10( *\|)$", r"\1none\2"),
    ),
    (
        "G9-VERDICT",  # a cited clause re-verdicted compliant
        regex(r"(\| §7 — reduced motion\s+\| )at risk — interim path: [^|]*\|", r"\1compliant |"),
    ),
    (
        "G10-FINDINGS",
        regex(
            r"(\| F-01 [^\n]*?\| )E16-D03 · area/recorder-replay", r"\1E16-D03 · area/charting-ui"
        ),
    ),
    ("G11-ROWS", regex(r"(\| G-01 [^\n]*?\| )([^|]+)\|\s*$", r"\1 |")),
    (
        "G11-ROWS",  # a Q row due on a date that is not its consumer's sprint start
        regex(r"^(\| Q-08 .*\| )2026-11-13( *\|)$", r"\g<1>2026-11-14\2"),
    ),
    (
        "G12-RULED",
        regex(
            r"(\| BQ-04 [^\n]*?)RULED \(orchestrator, 2026-10-30, #374 ruling of record — 6516426184\)",
            r"\1pending",
        ),
    ),
    ("G13-CITE", pin_sub(r"^(05\|96\|)(.*)$", r"\1NOT THE WORDS \2")),
    (
        "G14-COLOUR",
        regex(r"(\| CR-01 [^\n]*?\| )(\d+\.\d)(\s+\| )(\d+\.\d)", r"\g<1>0.0\g<3>\g<4>"),
    ),
    (
        "G15-HYGIENE",
        sub(
            "## 25. Summary for #374 (≤ 10 lines)",
            "## 25. Summary for #374 (≤ 10 lines; see https://example.invalid)",
        ),
    ),
    (
        "G15-HYGIENE",  # the case variant of an advisory-style identifier
        sub(
            "## 25. Summary for #374 (≤ 10 lines)",
            "## 25. Summary for #374 (" + "GH" + "SA-ABCD-EF12-3456)",
        ),
    ),
    (
        "G15-HYGIENE",  # a loopback host and port (the analogue of §20.3 row (ix))
        sub(
            "## 25. Summary for #374 (≤ 10 lines)",
            "## 25. Summary for #374 (" + "local" + "host:9000)",
        ),
    ),
    ("G16-DECK", deck_sub('"rbac.view_as": {', '"rbac.view_as_x": {')),
    ("G17-FROZEN", regex(r"^\| \(ix\)\s+\|", "| (ix-b) |")),
    (
        "G18-REDLINES",
        regex(r"(\| Page, cards\s+\| page `color\.surface\.canvas`)", r"\1 `color.surface.app`"),
    ),
    ("G19-STATES", sub("13 text-bound states (RULED", "12 text-bound states (RULED")),
    ("G20-COMPONENTS", regex(r"(\| CMP-177 [^\n]*?\| )the nineteen", r"\1built: the nineteen")),
    ("G21-ICONS", regex(r"(\| `lock` \(the T2 glyph\)\s+\| )`lock`", r"\1`padlock`")),
    (
        "G22-EDIT-SET",
        lambda c: c,
    ),  # replaced at run time: the working tree is probed, see self_test
    ("G23-WALK", regex(r"(\| story: E16-S01 \(#484\)[^\n]*?\| )pointer \d+", r"\1pointer 0")),
    (
        "G23-WALK",  # the sum still holds, the §22.4 row count does not
        sub(
            "pointer 17 · C 6 · G 1 · Q 1 — §22.4 (S01)",
            "pointer 18 · C 5 · G 1 · Q 1 — §22.4 (S01)",
        ),
    ),
    ("G24-CALENDAR", sub("**reports and promises nothing**", "**reports and promises Done**")),
    ("G25-XREF", sub("routed (G-01, G-02; F-07, F-08)", "routed (G-01, G-02; F-07, F-99)")),
    ("G26-CODES", regex(r"^(\| [^|]*\| )`invalid_cursor`( +\|)", r"\1`invalid_cursor_x`\2")),
    ("G27-RBAC", sub("PUT `admin:write` · none", "PUT `recording:write` · none")),
)


def digests() -> dict[str, str]:
    paths = (SPEC, DECK, PINS, Path(__file__))
    return {str(p): hashlib.sha256(p.read_bytes()).hexdigest() for p in paths if p.exists()}


def self_test(ctx: Ctx, base: Result) -> list[str]:
    bad: list[str] = []
    before = digests()
    covered = {code for code, _ in MUTATIONS}
    bad += [f"self-test: gate {g} has no mutation" for g, _ in GATE_FNS if g not in covered]
    for code, fn in MUTATIONS:
        if code == "G22-EDIT-SET":
            new = edit_set_probe(ctx, base)
        else:
            mutated = fn(ctx)
            if mutated == ctx:
                bad.append(f"self-test {code}: the mutation did not apply")
                continue
            new = sorted(set(run(mutated).fails) - set(base.fails))
        if not new or not all(x.startswith(f"[{code}]") for x in new):
            bad.append(f"self-test {code}: expected new [{code}] FAILs only, got {new[:3]}")
    again = run(ctx)
    if again.fails != base.fails:
        bad.append("self-test: a re-run does not reproduce the base result")
    if digests() != before:
        bad.append("self-test: a file on disk changed")
    return bad


def edit_set_probe(ctx: Ctx, base: Result) -> list[str]:
    """G22 reads the working tree: probe it by appending a tick to one pointer line on disk, then
    restore the file byte for byte."""
    path = ROOT / KEYS["14"]
    original = path.read_bytes()
    text = original.decode("utf-8")
    probe = text.replace(POINTER_MARK, POINTER_MARK + " [x]", 1)
    if probe == text:
        return ["[G22-EDIT-SET] no pointer line to probe (the `14` edit set is not in the tree)"]
    try:
        path.write_bytes(probe.encode("utf-8"))
        return sorted(set(run(ctx).fails) - set(base.fails))
    finally:
        path.write_bytes(original)


# ----------------------------------------------------------------------------- main


def main(argv: list[str]) -> int:
    ap = argparse.ArgumentParser(description=(__doc__ or "").splitlines()[0])
    ap.add_argument("--check", action="store_true", help="exit 1 on any FAIL")
    ap.add_argument("--json", action="store_true", help="print the numbers and findings as JSON")
    ap.add_argument("--fill", action="store_true", help="rewrite the spec's markers from the tool")
    ap.add_argument("--self-test", "--selftest", action="store_true", help="the mutation self-test")
    ap.add_argument(
        "--repin-ruled", action="store_true", help="rewrite the pins file (the only writer)"
    )
    args = ap.parse_args(argv)
    missing = [k for k, rel in KEYS.items() if not git_show(HEAD, rel)]
    if missing:
        print(f"FAIL [G13-CITE] cannot read {missing} at {HEAD} (fetch first)")
        return 1
    ctx = load_ctx()
    if args.fill:
        print(f"markers filled: {fill(ctx)}")
        ctx = load_ctx()
    if args.repin_ruled:
        print(f"pins written: {repin(ctx)}")
        ctx = load_ctx()
    res = run(ctx)
    st = self_test(ctx, res) if args.self_test else []
    if args.json:
        payload: dict[str, object] = {
            "numbers": res.numbers,
            "fails": res.fails,
            "warns": res.warns,
        }
        if args.self_test:
            payload["self_test"] = st
        print(json.dumps(payload, ensure_ascii=False, indent=1, sort_keys=True, default=str))
    else:
        out = [f"FAIL {line}" for line in res.fails] + [f"WARN {line}" for line in res.warns]
        out += [f"{k}: {v}" for k, v in res.numbers.items()]
        out.append(f"gates: {len(GATE_FNS)}; FAIL {len(res.fails)}, WARN {len(res.warns)}")
        if args.self_test:
            out += [f"FAIL {line}" for line in st]
            out.append(
                f"self-test: {'ok' if not st else 'FAILED'}: {len(MUTATIONS)} mutations (one per gate), "
                "each its own FAIL; a re-run reproduces the base result; files on disk unchanged"
            )
        print("\n".join(out))
    failed = bool(res.fails or st)
    return 1 if (failed and (args.check or args.self_test)) else 0


if __name__ == "__main__":
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")
    raise SystemExit(main(sys.argv[1:]))
