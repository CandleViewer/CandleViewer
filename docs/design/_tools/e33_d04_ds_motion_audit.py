#!/usr/bin/env python3
"""E33-D04 (#988) audit: the emulated-algo design-system contributions and the motion spec.

Standalone, offline, stdlib only; it executes no repo code. It reads, AS TEXT at the pinned
base `965cf14090` (`git show`): the token JSON (`themes.json` layering: dark = primitives +
semantic-dark, light = + semantic-light, hc = + semantic-hc), `theme.css`,
`tools/contrast/pairs.mjs` and `encodings.json`, the plan texts `05`, `14`, `15`, `16`, `23`, `24`,
`28`, the ticket JSON, the merged E33-D02 / E33-D03 / H03 / E05-D02 slice 4 / E09-D08 / E30-D04 /
E32-D02 texts, the CVD port's source `docs/research/_tools/cvd_simulate.py` and the E11-D05 tool's
JND floor; then this ticket's spec and hand-off from the working tree, and the working-tree `15`
and `16` (which must equal the base).

1. **Values.** Every `{{KIND:key}}` outside a code span is COMPUTED (MOTION, BUDGET, CONTRAST,
   DIST, COUNT): durations and easings from the primitives, the cadence, flash, loop and skeleton
   constants parsed from the cited texts, contrast by the WCAG 2.x formula per theme, CVD as CIE76
   ΔE after the Brettel / Viénot projection of `cvd_simulate.py` (ported verbatim; G-CVD-PORT
   re-reads its constants) for every two state fills and every two glyph colours per simulation
   and theme (`--json` `cvd`), greyscale as the CIELAB L* gap, and the counts from the spec's own
   tables. `--fill` writes `VALUE<!--=KIND:key-->`; `--check` re-derives every anchored value and
   FAILs on a difference, a missing anchor, a `{{` left outside a code span, or a hand-typed
   figure with a unit.
2. **Cites.** Every `NN`:line, `D02`/`D03`/`H03`/`FO`/`PRIM`/`SL`/`SD`:line, `Exx-Dyy`:line and
   `path`:line cite is read at the base (FAIL when the line is gone or blank; WARN when it
   drifted at `origin/main`), and a table of load-bearing fragments must sit on the cited line
   exactly. The merged-sha pins are ancestors of the base, carry their PR numbers and touch the
   cited files.
3. **Gates (RULED comment 6397030902).** Every table row AND the prose, bullets and headings are
   read after normalising (HTML comments, soft hyphens and zero-width characters dropped, NFKC,
   `*`, backticks and `_emphasis_` stripped, whitespace collapsed, dashes to spaces, lower case;
   quoted copy removed where a gate reads claims, except the gates where quoted copy is itself a
   claim: G-AFFORD, G-INSTANT, G-NOFADE, G-TAGNAME). A claim is read per sentence (split at "; ",
   " — " and a sentence end, never at a comma); a table row is read cell by cell with its lead
   cell as the subject; where a gate carries the subject (the #4507 design), the subject is read
   in the clause's whole sentence, across "; ", parentheses and quotes; a clause opening on a
   pronoun ("; it eases") takes the previous clause's subject, and "<noun phrase> — <clause>"
   reads as "<noun phrase> is <clause>". Terms match their inflections and synonyms (one motion
   vocabulary: ease, interpolate, tween, cross-fade, glide, animate, transition, morph, smooth,
   slide, fade, settle, fill continuously, tick up, pulse, bounce, dissolve, blend, zoom, grow;
   the sample nouns sample, reading, tick, update, value; a rate in words, fps, hertz or "/s"),
   a negation covers its own term (within three words) and a list coordinated after it, and a
   double negation or a negation chain ("never without", "never fails to", "never stops", "never
   un-gated", "no other … than") counts as a claim. A cite exempts only what it cites: T Scope
   exempts a quote the ticket itself holds, never a paraphrase and never the rest of the clause;
   "per CMP-043 as ruled" exempts its own sub-clause, never a later "…, and also fade". A null cell
   ("none", "n/a", "-", "(none)") is no value; a row id in markup (`**Mo-11**`, `DR 16`) is read and
   reported. The sweeps skip §9.3, whose rows describe the violations they plant. Each gate reports
   at most one FAIL line.
4. **--selftest** applies every §9.3 mutation M-n in memory to the filled texts, with the values
   frozen at the baseline (so only the semantic gate can trip); each must add exactly one FAIL,
   from the gate it names, and every text is restored byte-identically (sha256 of the in-memory
   baseline and of the spec, hand-off, `15` and `16` re-read from disk); a mutation of the tool's
   own state (the CVD port, M-62) is undone and re-checked. G-Q3, G-C15 and G-DR14 gate the
   orchestrator's 14:42Z decisions through M-99, M-100 and M-101 (each marked "RULED
   (6401561066)"; "RULED" cites comment 6397030902 or 6401561066, never a lane thread); M-102 to M-117 are the round-1 record's forms,
   M-118 to M-124 the round-2 classes (motion vocabulary, sample nouns, the carried subject, a
   negation chain, a rate in words or fps, a cite's own sub-clause, the tag suppressed).

Usage (from the repo root):
  uv run --no-project python docs/design/_tools/e33_d04_ds_motion_audit.py --check [--fill] [--json]
  uv run --no-project python docs/design/_tools/e33_d04_ds_motion_audit.py --selftest
Exit 0 = no FAIL; 1 = at least one FAIL.
"""

from __future__ import annotations

import argparse
import functools
import hashlib
import json
import math
import re
import subprocess
import sys
import unicodedata
from collections.abc import Callable
from dataclasses import dataclass
from itertools import combinations
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
BASE = "965cf14090"  # every cite was read here (the spec's Inputs line)
HEAD = "origin/main"  # drift is reported against this ref (WARN, never FAIL)
MULTI = re.MULTILINE

SPEC_REL = "docs/design/E33/E33-D04.md"
HAND_REL = "docs/design/E33/E33-D04-handoff.md"
P15_REL = "docs/plan/15-component-catalogue.md"
P16_REL = "docs/plan/16-design-system-brief.md"
TICKETS_REL = "docs/plan/backlog/E33.json"
DS_SRC_REL = "packages/ui/tokens"
CSS_REL = "packages/ui/src/theme/theme.css"
PAIRS_REL = "tools/contrast/pairs.mjs"
ENCODINGS_REL = "tools/contrast/encodings.json"
CVD_REL = "docs/research/_tools/cvd_simulate.py"
JND_REL = "docs/design/_tools/e11_d05_ds_audit.py"
CITE_FILES: dict[str, str] = {
    "D02": "docs/design/E33/E33-D02.md",
    "D03": "docs/design/E33/E33-D03.md",
    "H03": "docs/design/E33/E33-D03-handoff.md",
    "FO": "docs/design/E05/E05-D02-feedback-overlays.md",
    "PRIM": f"{DS_SRC_REL}/primitives.tokens.json",
    "SL": f"{DS_SRC_REL}/semantic-light.tokens.json",
    "SD": f"{DS_SRC_REL}/semantic-dark.tokens.json",
    "semantic-light": f"{DS_SRC_REL}/semantic-light.tokens.json",
    "theme.css": CSS_REL,
}
THEMES: dict[str, tuple[str, ...]] = {
    "dark": ("primitives", "semantic-dark"),
    "light": ("primitives", "semantic-dark", "semantic-light"),
    "hc": ("primitives", "semantic-dark", "semantic-hc"),
}
SEMANTIC = ("semantic-dark", "semantic-light", "semantic-hc")

# ---- the ruling and the fixed facts
RULING_ID = "6397030902"
BQ_LIST_ID = "6396755099"
RULING_1442_ID = "6401561066"  # the 14:42Z decisions: D04-Q3, D04-C15 / CR-T1, DR-14
RULED_1442 = f"RULED ({RULING_1442_ID})"
OWNER_MARK = "owner approval pending (#2701)"
OWNER_BQS = ("BQ-2", "BQ-11", "BQ-17")
# sha → (PR, a path the merge touched): the merged inputs the spec cites (its Start / Inputs lines)
PINS: dict[str, tuple[str, str]] = {
    "4f9d15b6": ("#4368", "docs/design/E33/E33-D02.md"),
    "6a8fc962": ("#4425", "docs/design/E33/img/"),
    "88839ea3": ("#4375", "docs/design/E33/E33-D03.md"),
    "05aa6fba": ("#4402", "docs/design/E33/img/"),
    "04a8caa9": ("#4414", "docs/design/E05/E05-D02-feedback-overlays.md"),
}
MAX_BOARDS = 10  # RULED BQ-18 (lever 4): at most ten boards, light twins at most a third
SPEC_LINE_BUDGET = 600  # RULED BQ-1: the spec's line budget (the tool prints it; M-25)
THEME_DENSITY_RUNS = 4  # every story in dark / light × compact / comfortable (`15`:41)
SIMS = ("protanopia", "deuteranopia", "tritanopia")
SIM_KEY = {"protanopia": "protan", "deuteranopia": "deutan", "tritanopia": "tritan"}
# §10's pairs: key → (fg, bg, role); the tool measures these, the spec's rows must match them
PAIRS: dict[str, tuple[str, str, str]] = {
    "word-neutral": ("color.text.primary", "color.surface.hover", "text"),
    "word-warning": ("color.text.primary", "color.status.warning.subtle", "text"),
    "cause-warning": ("color.text.secondary", "color.status.warning.subtle", "text"),
    "glyph-warning": ("color.status.warning.strong", "color.status.warning.subtle", "non-text"),
    "word-danger": ("color.text.primary", "color.status.danger.subtle", "text"),
    "cause-danger": ("color.text.secondary", "color.status.danger.subtle", "text"),
    "glyph-danger": ("color.status.danger.strong", "color.status.danger.subtle", "non-text"),
    "word-success": ("color.text.primary", "color.status.success.subtle", "text"),
    "glyph-success": ("color.status.success.strong", "color.status.success.subtle", "non-text"),
    "word-stale": (
        "color.data-confidence.stale.text",
        "color.data-confidence.stale.surface",
        "text",
    ),
    "tag-emulated": ("color.text.secondary", "color.surface.raised", "text"),
    "bar-track": ("color.action.primary.default", "color.surface.hover", "non-text"),
    "cause-neutral": ("color.text.secondary", "color.surface.hover", "text"),
    "cause-success": ("color.text.secondary", "color.status.success.subtle", "text"),
    "bar-success": ("color.status.success.default", "color.surface.hover", "non-text"),
    "bar-warning": ("color.status.warning.strong", "color.surface.hover", "non-text"),
    "bar-danger": ("color.status.danger.strong", "color.surface.hover", "non-text"),
}
# measured but not gated: the value a C-row records (D04-C15), never a §10 row
MEASURED_ONLY: dict[str, tuple[str, str, str]] = {
    "bar-danger-default": ("color.status.danger.default", "color.surface.hover", "non-text"),
}
LABEL_PAIR = re.compile(r"(?:word|cause|glyph)-")  # the CMP-246 label's own pairs
# sha → the document it pins (the Start line): a cite next to it must be that document's
PIN_DOC = {
    "4f9d15b6": "D02",
    "6a8fc962": "D02",
    "88839ea3": "D03",
    "05aa6fba": "D03",
    "04a8caa9": "FO",
}
PIN_DOCS_OK: dict[str, set[str]] = {
    "D02": {"d02", "e33 d02"},
    "D03": {"d03", "h03", "e33 d03"},
    "FO": {"fo", "e05 d02"},
}
# the load-bearing fragments: (cite id, line at the base, text the line must hold)
CITED: tuple[tuple[str, int, str], ...] = (
    ("D02", 464, "Organism (trading, safety-critical)"),
    ("D02", 415, "state swaps are instant"),
    ("D02", 468, "`Esc` closes and never cancels a run"),
    ("D02", 472, "- **Storybook**: Twap"),
    ("D02", 336, "≤ once per 5 s"),
    ("D02", 368, '"6 of 10 slices · 60 %"'),
    ("D03", 192, "shared 1 s ticker"),
    ("D03", 206, "Progress text per kind (M4)"),
    ("D03", 221, "Halted by risk control"),
    ("D03", 363, "`tag.emulated`"),
    ("H03", 90, "Algos — Emulated — run by CandleViewer"),
    ("H03", 110, "determinate width change"),
    ("H03", 112, "`motion.shimmer`"),
    ("15", 268, "track `color.surface.hover`"),
    ("15", 316, "content at 0 ms"),
    ("15", 1344, "local state machine"),
    ("15", 1408, "`color.status.danger`."),
    ("15", 2656, "`detector: DetectorId`"),
    ("16", 175, "No flashing content exceeding 3 times per second"),
    ("16", 178, "`normal` scale+fade"),
    ("16", 182, "`slow` looping shimmer"),
    ("16", 199, "value-change emphasis"),
    ("16", 183, "in-app override"),
    ("16", 195, "a stale cell never animates"),
    ("23", 824, "never throttled"),
    ("14", 1613, "coalesced to 2 Hz"),
    ("05", 113, "clock/check/x/slash"),
    ("05", 206, "single low-amplitude cross-fade"),
    ("05", 208, "No content flashes more than 3 times per second"),
    ("24", 2780, "class AlgoState"),
    ("SL", 41, '"color.status.warning.strong"'),
    ("SL", 44, '"color.status.danger.strong"'),
    ("SD", 410, '"radius.dialog"'),
    ("SD", 414, '"radius.badge"'),
    ("SD", 560, '"elevation.dialog"'),
    ("PRIM", 450, '"motion.duration.instant"'),
    ("E09-D08", 220, "reads as neither state"),
    ("E09-D08", 221, "A countdown animated smoothly"),
    ("E30-D04", 553, "**Never animates**"),
    ("E30-D04", 561, "`data-motion = safe | reduce`"),
    ("E32-D02", 762, "`AlgoBuilderDialog`"),
    ("FO", 3, "awaiting owner approval"),
    ("FO", 398, "sampled at most once"),
    ("theme.css", 51, ':root[data-motion="reduce"]'),
)

PLACEHOLDER = re.compile(r"\{\{([A-Z]+:[^{}]+)\}\}")
ANCHOR = re.compile(r"<!--=([A-Z]+:[^>]+?)-->")
CODE = re.compile(r"`[^`\n]*`")
QUOTED = re.compile(r'"[^"\n]*"|“[^”\n]*”')
TOKEN_NAME = re.compile(
    r"`((?:color|space|size|type|radius|elevation|opacity|motion|border)\.[a-z0-9.{},*-]+)`"
)
TOKEN_FAMILIES = (
    "color", "space", "size", "type", "radius", "elevation", "opacity", "motion", "border",
    "shadow", "z", "zindex", "font",
)  # fmt: skip
# a token-shaped name anywhere (backticked or bare, any case): a family, then dotted segments
TOKENISH = re.compile(
    rf"(?<![\w./@#-])((?:{'|'.join(TOKEN_FAMILIES)})\.[a-z0-9-]+(?:\.[a-z0-9{{}},*-]+)*)(?![\w(])",
    re.IGNORECASE,
)
UNRESOLVED = (
    r"\bunresolved\b|\bstill open\b|\bnot (?:yet )?(?:resolved|answered|corrected)\b|\btb[dc]\b"
    r"|\bno owner\b|\bno replacement\b"
)
BOUND_NAME = re.compile(
    r"`((?:color|space|size|type|radius|elevation|opacity|motion)\.[a-z0-9.-]+)`"
)
FIGURE = re.compile(
    r"(?<![\w.,:#/>{-])(\d+(?:[.,]\d+)*)\s?(ms|s|hz|px|%|:1)(?![\w])", re.IGNORECASE
)
CITE_GROUP = re.compile(
    r"(?:`(?P<a>[A-Za-z0-9._/-]+)`|(?P<b>\b(?:D02|D03|H03|FO|PRIM|SL|SD|E\d\d-D\d\d)\b)) ?"
    r":(?P<first>\d+(?:[–-]\d+)?)(?P<more>(?:, :\d+(?:[–-]\d+)?)*)"
)

Values = dict[str, str]
Fetch = Callable[[str, str], str | None]

# ---------------------------------------------------------------------------- reading


@functools.lru_cache(maxsize=256)
def git_show(rev: str, rel: str) -> str | None:
    """The file at `rev`, or None when it does not exist there (never raises)."""
    try:
        out = subprocess.run(
            ["git", "-C", str(ROOT), "show", f"{rev}:{rel}"],
            capture_output=True,
            check=False,
            timeout=30,
        )
    except (OSError, subprocess.SubprocessError):
        return None
    return out.stdout.decode("utf-8") if out.returncode == 0 else None


def git_out(*args: str) -> str:
    try:
        out = subprocess.run(
            ["git", "-C", str(ROOT), *args], capture_output=True, check=False, timeout=60
        )
    except (OSError, subprocess.SubprocessError):
        return ""
    return out.stdout.decode("utf-8") if out.returncode == 0 else ""


def git_ok(*args: str) -> bool:
    try:
        out = subprocess.run(
            ["git", "-C", str(ROOT), *args], capture_output=True, check=False, timeout=60
        )
    except (OSError, subprocess.SubprocessError):
        return False
    return out.returncode == 0


def git_fetch(rev: str, rel: str) -> str | None:
    return git_show(rev, rel)


def at_base(rel: str) -> str:
    text = git_show(BASE, rel)
    if text is None:
        raise SystemExit(f"FAIL parse: {rel} is not readable at {BASE}")
    return text


def plan_rel(nn: str) -> str | None:
    listing = git_out("ls-tree", "--name-only", BASE, "docs/plan/")
    names = [n for n in listing.split("\n") if n.startswith(f"docs/plan/{nn}-")]
    return min(names) if names else None


def plan(nn: str) -> str:
    rel = plan_rel(nn)
    if rel is None:
        raise SystemExit(f"FAIL parse: docs/plan/{nn}-* missing at {BASE}")
    return at_base(rel)


def grab(pattern: str, text: str, what: str, flags: int = MULTI) -> str:
    m = re.search(pattern, text, flags)
    if not m:
        raise SystemExit(f"FAIL parse: {what} not found ({pattern})")
    return m[1]


# ---------------------------------------------------------------------------- markdown


def fenced(lines: list[str]) -> list[bool]:
    """For each line, whether it sits inside (or is) a ``` fence."""
    out: list[bool] = []
    inside = False
    for ln in lines:
        if ln.lstrip().startswith("```"):
            out.append(True)
            inside = not inside
            continue
        out.append(inside)
    return out


def section(text: str, head: str) -> str:
    """From the heading starting with `head` (outside fences) to the next heading of the same or a
    higher level outside a fence."""
    lines = text.split("\n")
    fence = fenced(lines)
    start, level = -1, 0
    for i, ln in enumerate(lines):
        m = re.match(r"^(#+) (.*)$", ln)
        if m and not fence[i] and m[2].startswith(head):
            start, level = i, len(m[1])
            break
    if start < 0:
        return ""
    end = len(lines)
    for j in range(start + 1, len(lines)):
        m = re.match(r"^(#+) ", lines[j])
        if m and not fence[j] and len(m[1]) <= level:
            end = j
            break
    return "\n".join(lines[start:end])


def split_row(line: str) -> list[str]:
    body = line.strip()
    body = body.removeprefix("|")
    body = body.removesuffix("|")
    return [c.strip() for c in re.split(r"(?<!\\)\|", body)]


def is_rule(line: str) -> bool:
    return re.match(r"^\s*\|\s*:?-{1,}", line) is not None and set(line.strip()) <= set("|-: ")


def table_rows(block: str) -> list[list[str]]:
    """Every table row of `block` but each table's header and rule rows."""
    out: list[list[str]] = []
    lines = block.split("\n")
    for i, ln in enumerate(lines):
        if not re.match(r"^ {0,3}\|", ln) or is_rule(ln):
            continue
        nxt = lines[i + 1] if i + 1 < len(lines) else ""
        if is_rule(nxt):
            continue  # a header row
        out.append(split_row(ln))
    return out


def row_key(cell: str) -> str:
    """A row id with markup dropped and its separator normalised (`**Mo-11**`, `DR 16` → the id)."""
    k = re.sub(r"[*_`]", "", cell).strip()
    return re.sub(r"^([A-Za-z]+)\s+(\d+)$", r"\1-\2", k)


def rows_by(block: str, pattern: str) -> dict[str, list[str]]:
    """The table rows whose id (markup dropped, separator normalised) is of the form `pattern`."""
    return {row_key(r[0]): r for r in table_rows(block) if re.fullmatch(pattern, row_key(r[0]))}


def bullet(block: str, label: str) -> str:
    """The `- **Label**...` line of a copy-ready entry (fenced lines included)."""
    for ln in block.split("\n"):
        if ln.startswith(f"- **{label}"):
            return ln
    return ""


_DASHES = re.compile(r"[‐-―−-]")
_MARKUP = re.compile(r"[*`]")
_LINK = re.compile(r"\[([^\]]*)\]\([^)]*\)")
# hidden in rendered markdown: HTML comments (anchors included), soft hyphens, zero-width characters
_HIDDEN = re.compile(r"<!--.*?-->|[\u00ad\u200b-\u200d\u2060\ufeff]", re.DOTALL)
_EMPH = re.compile(r"(?<!\w)_+|_+(?!\w)")  # `_emphasis_` (an underscore inside a word stays)


def norm_text(text: str) -> str:
    """Rendered words only: comments, soft hyphens and markup dropped, NFKC, dashes to spaces,
    whitespace collapsed, lower case."""
    t = unicodedata.normalize("NFKC", _HIDDEN.sub("", text))
    t = _EMPH.sub(" ", _MARKUP.sub("", _LINK.sub(r"\1", t)))
    return " ".join(_DASHES.sub(" ", t).split()).lower()


def unquote(text: str) -> str:
    return QUOTED.sub(" ", text)


SENTENCE = re.compile(r";\s|(?<=[.!?])\s+|\s—\s")
NEG_WORD = r"(?:no|never|not|nor|without|nothing|none|cannot)"
DOUBLE_NEG = re.compile(
    r"\b(?:never|not|no)\s+(?:\S+\s+){0,2}?without\b|\bnever not\b|\bnot never\b"
    r"|\bnot (?:only|just)\b"
    # a negation chain asserts its term: "never fails to", "never un-gated", "no other … than",
    # "never stops", "does not stop" (record r2)
    r"|\b(?:never|not|no|cannot|nothing)\s+(?:\S+\s+){0,2}?"
    r"(?:fail(?:s|ed|ing)?|lack(?:s|ed|ing)?|omit\w*|un|other|ceas\w*|stop(?:s|ped|ping)?)\b"
)


# a flip negates everything after it: "it is not true that the bar never eases" asserts the easing
# and "it is false that the bar eases" denies it (record r3)
FLIP = re.compile(
    r"\b(?:it|this)(?:(?: is| was|['’]s) (?:not (?:true|the case)|false|untrue|wrong)"
    r"| (?:isn['’]t|wasn['’]t) (?:true|the case)) (?:that|to say that)\b"
)


def live(clause: str, term: str, keep_quotes: bool = False) -> bool:
    """`term` asserted in `clause` once every negated mention is removed. A negation covers only
    its own term (at most three words before it) and a list of its terms coordinated after it; a
    double negation or a negation chain asserts its term; a flip ("it is not true that …", "it is
    false that …") inverts what follows it."""
    t = norm_text(clause) if keep_quotes else norm_text(unquote(clause))
    f = FLIP.search(t)
    if f:
        rest = t[f.end() :]
        return _live(t[: f.start()], term) or (
            re.search(term, rest) is not None and not live(rest, term, True)
        )
    return _live(t, term)


def _live(t: str, term: str) -> bool:
    t = DOUBLE_NEG.sub(" ", t)
    # a negation covers a coordinated list of its terms too ("nothing loops, pulses or drifts")
    listed = rf"(?:(?:,\s*(?:or\s+|nor\s+|and\s+)?|\s+(?:or|nor|and)\s+)(?:{term})\w*)*"
    t = re.sub(rf"\b{NEG_WORD}\b(?:\s+\S+){{0,3}}?\s+\W?(?:[\w-]+\.)*(?:{term}){listed}", " ", t)
    return re.search(term, t) is not None


_SEP = re.compile(r"(;\s|(?<=[.!?])\s+|\s—\s)")
# a clause that opens on a pronoun ("; it eases", "; no, it is drawn as shipped") reads with the
# previous clause's subject in its place (record r2: the subject carried across "; " and " — ")
PRONOUN = re.compile(
    r"^\W*(?:(?:no|yes|and|but|so|then|instead|rather),?\s+)?(?:it|they|this|these|those)\b"
    r"(?!\s+(?:is|was)\s+(?:not\s+)?(?:true|false|untrue|wrong|the case)\b)",  # a flip (r3)
    re.IGNORECASE,
)
SUBJECT_END = re.compile(
    r"\s(?:is|are|was|were|be|does|do|did|has|have|had|can|cannot|may|might|must|will|would"
    r"|shall|should|never|not|no|always|only|sits?|stays?|keeps?|carries|carry|reads?|becomes?"
    r"|gets?|takes?|shows?|uses?|reuses?|serves?|wears?)\b",
    re.IGNORECASE,
)

APPOSED = re.compile(r"^\W*(?:the|a|an|its|each|every)\s+(?:\S+\s+){0,3}?\S+\W*$", re.IGNORECASE)


SUBCLAUSE = re.compile(
    r",\s+(?=(?:and|but|plus|then|while|yet|also)\b)|\s+(?=(?:and also|and then|but also|plus)\b)"
)


PAREN = re.compile(r"\([^()]*\)")


def cited_rest(clause: str, term: str, near: str, unless: str, keep_quotes: bool) -> bool:
    """A sub-clause the cite (`unless`) does not cover asserts `term`, its subject (`near`) named
    in it or in a sub-clause before it. A cite in parentheses covers only its parenthesis: the
    words around it are read without it (record r3)."""
    seen = False
    for x in SUBCLAUSE.split(clause):
        y = PAREN.sub(lambda m: " " if re.search(unless, norm_text(m[0])) else m[0], x)
        n = norm_text(y if keep_quotes else unquote(y))
        seen = seen or not near or re.search(near, n) is not None
        if seen and not re.search(unless, norm_text(y)) and live(y, term, keep_quotes):
            return True
    return False


def negated_after(clause: str, term: str) -> bool:
    """`clause` negates its predicate on `term`: a negation follows the term's first mention."""
    t = DOUBLE_NEG.sub(" ", norm_text(unquote(clause)))
    m = re.search(term, t)
    return m is not None and re.search(rf"\b{NEG_WORD}\b", t[m.end() :]) is not None


def sentences(text: str) -> list[str]:
    """The clauses of `text` (split at "; ", " — " and a sentence end). A clause that opens on a
    pronoun takes the previous clause's subject (its words before the first verb), and a clause
    after " — " whose previous clause is a bare noun phrase (an article and at most four words, no
    verb) reads as "<previous> is <clause>" (an
    apposition: "The status label — T2 …"). A sentence end resets the subject."""
    parts = _SEP.split(text)
    out: list[str] = []
    prev, subj = "", ""
    for i in range(0, len(parts), 2):
        c, sep = parts[i], parts[i - 1] if i else ""
        if not c.strip():
            continue
        if sep and sep.strip() not in (";", "—"):
            prev, subj = "", ""
        m = PRONOUN.match(c)
        if m and subj:
            c = subj + c[m.end() :]
        elif sep.strip() == "—" and APPOSED.match(prev) and not SUBJECT_END.search(prev):
            c = f"{prev.strip()} is {c}"
        v = SUBJECT_END.search(c)
        prev, subj = c, (c[: v.start()] if v else "")
        out.append(c)
    return out


def clauses(text: str) -> list[str]:
    """The sentences of a unit (split at "; ", " — " and a sentence end, never at a comma, so a
    subject and its verb stay together). A table row is read cell by cell, each cell's sentences
    prefixed with the row's lead (its first cell, and the second when the first is an id), so a
    subject in one cell and a verb in another are read together."""
    if " | " not in text:
        return sentences(text)
    cells = text.split(" | ")
    idish = re.match(r"^[`*_]*[A-Za-z]+[- ]?\d", cells[0]) is not None
    head = cells[:2] if idish and len(cells) > 1 else cells[:1]
    out = [x for c in head for x in sentences(c)]
    lead = " | ".join([*head[:-1], (sentences(head[-1]) or [""])[-1]])
    for c in cells[len(head) :]:
        out += [f"{lead} | {x}" for x in sentences(c)]
    return out


FULL_STOP = re.compile(r"(?<=[.!?])\s+")


def scoped_clauses(text: str) -> list[tuple[str, str]]:
    """(clause, scope) for every clause of `clauses`: the scope is the whole sentence the clause
    sits in (split at a sentence end only), so a subject named before a "; ", a " — ", an opening
    parenthesis or a quote carries into the clauses after it (the #4507 whole-unit reading); in a
    table row the scope is the row's lead plus the whole cell."""
    if " | " not in text:
        return [(c, s) for s in FULL_STOP.split(text) if s.strip() for c in sentences(s)]
    cells = text.split(" | ")
    idish = re.match(r"^[`*_]*[A-Za-z]+[- ]?\d", cells[0]) is not None
    head = cells[:2] if idish and len(cells) > 1 else cells[:1]
    out = [(x, c) for c in head for x in sentences(c)]
    lead = " | ".join([*head[:-1], (sentences(head[-1]) or [""])[-1]])
    for c in cells[len(head) :]:
        out += [(f"{lead} | {x}", f"{lead} | {c}") for x in sentences(c)]
    return out


def units(text: str) -> list[str]:
    """Every unit a gate reads: each table row (its cells joined by " | "), each bullet, each
    prose paragraph and each heading; fenced copy-ready lines are read like the rest."""
    out: list[str] = []
    para: list[str] = []

    def flush() -> None:
        if para:
            out.append(" ".join(para))
            para.clear()

    for ln in text.split("\n"):
        s = ln.strip()
        if s.startswith("```"):
            flush()
        elif re.match(r"^\s*\|", ln):
            flush()
            if not is_rule(ln):
                out.append(" | ".join(split_row(s)))
        elif re.match(r"^\s*(?:[-*+]|\d+\.) ", ln) or s.startswith("#"):
            flush()
            out.append(s)
        elif s:
            para.append(s)
        else:
            flush()
    flush()
    return out


def claims(
    texts: list[str],
    term: str,
    near: str = "",
    keep_quotes: bool = False,
    unless: str = "",
    near_live: bool = False,
    carry: bool = False,
    affirmed: bool = False,
) -> list[str]:
    """Every sentence of every unit asserting `term` (and naming `near`, when given — asserting
    it too when `near_live`; never one naming `unless`, the cited or recorded forms a gate
    allows). With `carry` (the #4507 design) the subject `near` is read in the clause's whole
    sentence (`scoped_clauses`), so a subject named before a "; ", a parenthesis or a quote still
    binds the clause after it; the `unless` exemption stays scoped to the one clause that cites
    it. With `affirmed`, a clause that negates what follows `term` ("CMP-227 never the badge") is
    no claim; a double negation there ("never not") still is."""
    hits: list[str] = []
    for text in texts:
        for u in units(text):
            for c, whole in scoped_clauses(u):
                raw = whole if carry else c
                scope = norm_text(raw if keep_quotes else unquote(raw))
                if near and not re.search(near, scope):
                    continue
                if near and near_live and not live(raw, near, keep_quotes):
                    continue
                if unless and re.search(unless, norm_text(c)):
                    # the cite exempts its own sub-clause only ("…, and also fade"; record r2); the
                    # subject carries forward into a later sub-clause, never back
                    if cited_rest(c, term, near, unless, keep_quotes):
                        hits.append(norm_text(c)[:70])
                    continue
                if affirmed and negated_after(c, term):
                    continue
                if live(c, term, keep_quotes):
                    hits.append(norm_text(c)[:70])
    return hits


def one(tag: str, problems: list[str]) -> list[str]:
    """At most one FAIL line per gate."""
    if not problems:
        return []
    more = f" (+{len(problems) - 4} more)" if len(problems) > 4 else ""
    return [f"[{tag}] " + "; ".join(problems[:4]) + more]


def plain(text: str, values: Values) -> str:
    """The text with every anchor dropped and every placeholder replaced by its value."""
    return PLACEHOLDER.sub(lambda m: values.get(m[1], m[0]), ANCHOR.sub("", text))


# ---------------------------------------------------------------------------- tokens


@functools.lru_cache(maxsize=8)
def token_file(name: str) -> dict[str, object]:
    data = json.loads(at_base(f"{DS_SRC_REL}/{name}.tokens.json"))
    return {k: v.get("$value") for k, v in data.items() if isinstance(v, dict)}


def load_theme(name: str) -> dict[str, object]:
    merged: dict[str, object] = {}
    for f in THEMES[name]:
        merged.update(token_file(f))
    return merged


def resolve(tokens: dict[str, object], name: str) -> str:
    if name not in tokens:
        return "MISSING"
    value, hops = tokens[name], 0
    while isinstance(value, str) and value.startswith("{") and value.endswith("}") and hops < 12:
        value, hops = tokens.get(value[1:-1], "MISSING"), hops + 1
    return value if isinstance(value, str) else json.dumps(value)


def all_token_names() -> set[str]:
    names: set[str] = set()
    for f in ("primitives", *SEMANTIC):
        names |= set(token_file(f))
    return names


def aliased_primitives() -> set[str]:
    """Primitives some semantic token references: class (d) when bound directly."""
    refs: set[str] = set()
    for f in SEMANTIC:
        for v in token_file(f).values():
            refs |= set(re.findall(r"\{([^}]+)\}", json.dumps(v)))
    sem = set().union(*(set(token_file(f)) for f in SEMANTIC))
    return {r for r in refs if r in token_file("primitives") and r not in sem}


def expand(name: str, known: set[str]) -> list[str]:
    """`a.{b,c}` → [a.b, a.c]; `a.*` → every known name under `a.`."""
    m = re.search(r"\{([^}]+)\}", name)
    if m:
        return [x for part in m[1].split(",") for x in expand(name.replace(m[0], part), known)]
    if name.endswith(".*"):
        return sorted(n for n in known if n.startswith(name[:-1])) or [name]
    return [name]


# ---------------------------------------------------------------------------- colour


def hex_of(tokens: dict[str, object], name: str) -> str:
    v = resolve(tokens, name)
    if not re.fullmatch(r"#[0-9A-Fa-f]{6}(?:[0-9A-Fa-f]{2})?", v):
        raise SystemExit(f"FAIL token {name} does not resolve to a colour ({v})")
    if len(v) == 9:  # an alpha colour: composited over the raised surface of the same theme
        under = hex_of(tokens, "color.surface.raised")
        a = int(v[7:9], 16) / 255
        mix = (
            round(int(v[i : i + 2], 16) * a + int(under[i : i + 2], 16) * (1 - a))
            for i in (1, 3, 5)
        )
        return "#" + "".join(f"{c:02X}" for c in mix)
    return v.upper()


def rgb(hex6: str) -> tuple[int, int, int]:
    h = hex6.lstrip("#")
    return int(h[0:2], 16), int(h[2:4], 16), int(h[4:6], 16)


def srgb_to_linear(c: float) -> float:
    c = c / 255.0
    return c / 12.92 if c <= 0.04045 else ((c + 0.055) / 1.055) ** 2.4


def luminance(hex6: str) -> float:
    r, g, b = (srgb_to_linear(v) for v in rgb(hex6))
    return 0.2126 * r + 0.7152 * g + 0.0722 * b


def contrast(a: str, b: str) -> float:
    la, lb = luminance(a), luminance(b)
    return (max(la, lb) + 0.05) / (min(la, lb) + 0.05)


def show_ratio(r: float) -> str:
    near = any(abs(r - bar) < 0.005 for bar in (3.0, 4.5, 7.0))
    return f"{r:.4f}:1" if near else f"{r:.2f}:1"


# The Brettel (1997) / Viénot projection of `docs/research/_tools/cvd_simulate.py`, ported verbatim
# (G-CVD-PORT re-reads these constants from that file at the base).
RGB_TO_LMS = (
    (17.8824, 43.5161, 4.11935),
    (3.45565, 27.1554, 3.86714),
    (0.0299566, 0.184309, 1.46709),
)
LMS_TO_RGB = (
    (0.0809444479, -0.130504409, 0.116721066),
    (-0.0102485335, 0.0540193266, -0.113614708),
    (-0.000365296938, -0.00412161469, 0.693511405),
)
PROJECTIONS: dict[str, tuple[float, ...]] = {
    "protanopia": (0.0, 2.02344, -2.52581, 0.0, 1.0, 0.0, 0.0, 0.0, 1.0),
    "deuteranopia": (1.0, 0.0, 0.0, 0.494207, 0.0, 1.24827, 0.0, 0.0, 1.0),
    "tritanopia": (1.0, 0.0, 0.0, 0.0, 1.0, 0.0, -0.395913, 0.801109, 0.0),
}


def matvec(flat: tuple[float, ...], v: tuple[float, float, float]) -> tuple[float, float, float]:
    return (
        flat[0] * v[0] + flat[1] * v[1] + flat[2] * v[2],
        flat[3] * v[0] + flat[4] * v[1] + flat[5] * v[2],
        flat[6] * v[0] + flat[7] * v[1] + flat[8] * v[2],
    )


def flat3(m: tuple[tuple[float, float, float], ...]) -> tuple[float, ...]:
    return tuple(x for row in m for x in row)


def linear_to_srgb(c: float) -> float:
    s = c * 12.92 if c <= 0.0031308 else 1.055 * (c ** (1 / 2.4)) - 0.055
    return max(0.0, min(1.0, s)) * 255.0


def simulate(hex6: str, deficiency: str) -> str:
    lin = tuple(srgb_to_linear(v) for v in rgb(hex6))
    lms = matvec(flat3(RGB_TO_LMS), (lin[0], lin[1], lin[2]))
    lin2 = matvec(flat3(LMS_TO_RGB), matvec(PROJECTIONS[deficiency], lms))
    return "#" + "".join(f"{max(0, min(255, round(linear_to_srgb(c)))):02X}" for c in lin2)


def lab(hex6: str) -> tuple[float, float, float]:
    r, g, b = (srgb_to_linear(v) for v in rgb(hex6))
    x = (r * 0.4124 + g * 0.3576 + b * 0.1805) / 0.95047
    y = r * 0.2126 + g * 0.7152 + b * 0.0722
    z = (r * 0.0193 + g * 0.1192 + b * 0.9505) / 1.08883

    def f(t: float) -> float:
        return t ** (1 / 3) if t > 0.008856 else (7.787 * t) + (16 / 116)

    return 116 * f(y) - 16, 500 * (f(x) - f(y)), 200 * (f(y) - f(z))


def delta_e76(a: str, b: str) -> float:
    la, lb = lab(a), lab(b)
    return math.sqrt(sum((p - q) ** 2 for p, q in zip(la, lb, strict=True)))


# ---------------------------------------------------------------------------- spec structure

MO_COLS = (
    "#",
    "Element",
    "Trigger",
    "Property",
    "Safe",
    "Twin",
    "Tokens",
    "Focus",
    "Flash",
    "Board",
)
REG_COLS = ("Frame", "Board", "Word", "Glyph", "Fill", "Motion", "Reduce", "T2", "Exits", "Tag")
FAM_COLS = ("Family", "States", "Glyph", "Fill", "GlyphColour", "Word")
DR_COLS = ("DR", "Source", "Bound", "Class", "Replacement", "Owner", "Verdict")


def mo_rows(spec: str) -> dict[str, dict[str, str]]:
    rows = rows_by(section(spec, "7.2 The motion table"), r"Mo-\d+")
    return {k: dict(zip(MO_COLS, r, strict=False)) for k, r in rows.items()}


def register(spec: str) -> list[dict[str, str]]:
    block = section(spec, "9.2 The frame register")
    return [dict(zip(REG_COLS, r, strict=False)) for r in table_rows(block) if r and r[0]]


def frame_id(cell: str) -> str:
    return re.sub(r"[*_]", "", cell).strip("`")


def families(spec: str) -> list[dict[str, str]]:
    rows = table_rows(section(spec, "3.1 Families"))
    return [dict(zip(FAM_COLS, r, strict=False)) for r in rows if len(r) >= len(FAM_COLS)]


def glyph_names(cell: str) -> list[str]:
    return [g for g in re.findall(r"`([a-z][a-z-]*)`", cell) if "." not in g]


def fill_names(cell: str) -> list[str]:
    return re.findall(r"`(color\.[a-z0-9.-]+)`", cell)


def fam_words(cell: str) -> set[str]:
    """The family's words: each state's word before its cause ("Paused — …" → "paused")."""
    words: set[str] = set()
    for state in cell.split(" · "):
        lead = norm_text(re.sub(r"\([^)]*\)", "", state.split(" — ")[0])).strip()
        if lead and not lead.startswith("the "):
            words.add(lead)
    return words


def boards(spec: str) -> list[list[str]]:
    return [r for r in table_rows(section(spec, "0. Artefacts")) if re.fullmatch(r"\d\d", r[0])]


def mutation_ids(spec: str) -> list[str]:
    """§9.3's ids in order; a row may list several (`M-63 · M-64`) when they share a ruled
    sentence."""
    out: list[str] = []
    for r in table_rows(section(spec, "9.3 The frame-mutation list")):
        if re.fullmatch(r"M-\d+(?: · M-\d+)*", r[0]):
            out += r[0].split(" · ")
    return out


def drift_rows(hand: str) -> dict[str, dict[str, str]]:
    rows = rows_by(section(hand, "§E Drift ledger"), r"DR-\d+")
    return {k: dict(zip(DR_COLS, r, strict=False)) for k, r in rows.items()}


def c8_rows(hand: str) -> list[list[str]]:
    return table_rows(section(hand, "C.8 "))


def story_list(cell: str) -> list[str]:
    body = cell.split("—", 1)[1] if "verbatim —" in cell else cell
    body = re.sub(r"\([^)]*\)", "", body)
    return [s.strip() for s in re.split(r" · |, ", body) if s.strip()]


def storybook_items(line: str) -> list[str]:
    body = line.split(":", 1)[1] if ":" in line else ""
    body = body.split(";")[0]
    body = re.sub(r"\([^)]*\)", "", body)
    return [s.strip(" .") for s in body.split(",") if s.strip(" .")]


# ---------------------------------------------------------------------------- values


def motion_values() -> Values:
    prim = token_file("primitives")
    out: Values = {}
    for k in ("instant", "fast", "normal"):
        ms = str(prim[f"motion.duration.{k}"]).removesuffix("ms")
        out[f"MOTION:duration.{k}"] = f"{ms} ms"
    bez = prim["motion.easing.standard"]
    if not isinstance(bez, list):
        raise SystemExit("FAIL token motion.easing.standard is not a cubic Bézier")
    out["MOTION:easing.standard"] = "cubic-bezier(" + ", ".join(f"{x:g}" for x in bez) + ")"
    p14, p16, p05 = plan("14"), at_base(P16_REL), plan("05")
    scr070 = p14[p14.index("### SCR-070") : p14.index("### SCR-071")]
    out["MOTION:cadence.render-max-hz"] = grab(r"coalesced to (\d+) Hz", scr070, "`14` 2 Hz")
    fo = " ".join(at_base(CITE_FILES["FO"]).split())
    once = re.search(r"sampled at most (once|twice) a second", fo)
    if not once:
        raise SystemExit("FAIL parse: FO's 'sampled at most once a second'")
    out["MOTION:cadence.card-sample-max-hz"] = {"once": "1", "twice": "2"}[once[1]]
    out["MOTION:countdown.tick-s"] = grab(
        r"shared (\d+) s ticker", at_base(CITE_FILES["D03"]), "tick"
    )
    s71 = section(p16, "7.1 Connection")
    out["MOTION:flash.peak-opacity"] = grab(r"peak (0\.\d+)", s71, "`16` §7.1 peak")
    out["MOTION:flash.min-gap-ms"] = grab(r"≥ (\d+) ms between starts", s71, "`16` §7.1 gap")
    out["MOTION:flash.max-per-s"] = grab(
        r"No content flashes more than (\d+) times per second", p05, "`05` flash bar"
    )
    out["MOTION:loop.max-s"] = grab(r"no motion lasting more than (\d+) seconds", p16, "loop")
    slow = int(str(prim["motion.duration.slow"]).removesuffix("ms"))
    period = int(
        grab(r"(\d,?\d+) ms\s+period \(3 × `motion\.duration\.slow`\)", fo, "H3").replace(",", "")
    )
    if period != 3 * slow:
        raise SystemExit(f"FAIL parse: FO H3's period {period} ≠ 3 × slow ({3 * slow})")
    out["MOTION:skeleton.period-ms"] = f"{period:,}"
    out["MOTION:skeleton.stop-s"] = grab(
        r"`motion\.duration\.slow`\), stopped at (\d+) s", fo, "H3"
    )
    ticket = next(t for t in json.loads(at_base(TICKETS_REL)) if t.get("key") == "E33-D04")
    out["MOTION:ticket.crossfade-ms"] = grab(r"cross-fade at (\d+) ms", str(ticket["body"]), "120")
    css = at_base(CSS_REL)
    block = css[css.index(':root[data-motion="reduce"],') :]
    out["MOTION:reduce.runtime-duration"] = (
        grab(r"transition-duration: ([\d.]+)ms", block, "theme.css reduce") + " ms"
    )
    return out


def budget_values() -> Values:
    p14 = plan("14")
    scr070 = p14[p14.index("### SCR-070") : p14.index("### SCR-071")]
    return {
        "BUDGET:announce.progress-gap-s": grab(
            r"progress on the open running view[^\n]*≤ once per (\d+) s",
            at_base(CITE_FILES["D02"]),
            "D02 progress gap",
        ),
        "BUDGET:scr070.rows": grab(r"with (\d+) running algos", scr070, "100 rows"),
        "BUDGET:scr070.script-ms": grab(r"under (\d+) ms scripting", scr070, "3 ms"),
        "BUDGET:spec.lines": f"{SPEC_LINE_BUDGET} lines",
    }


def threshold() -> dict[str, float]:
    mjs = at_base(PAIRS_REL)
    return {
        "text": float(grab(r"^\s*TEXT: ([\d.]+)", mjs, "THRESHOLD.TEXT")),
        "non-text": float(grab(r"^\s*NON_TEXT: ([\d.]+)", mjs, "THRESHOLD.NON_TEXT")),
    }


def contrast_values() -> tuple[Values, dict[str, dict[str, float]]]:
    bars = threshold()
    out: Values = {
        "CONTRAST:bar.text": f"{bars['text']:g}:1",
        "CONTRAST:bar.non-text": f"{bars['non-text']:g}:1",
    }
    matrix: dict[str, dict[str, float]] = {}
    for theme in THEMES:
        t = load_theme(theme)
        for key, (fg, bg, _role) in {**PAIRS, **MEASURED_ONLY}.items():
            r = contrast(hex_of(t, fg), hex_of(t, bg))
            matrix.setdefault(key, {})[theme] = r
            out[f"CONTRAST:{key}.{theme}"] = show_ratio(r)
    return out, matrix


def family_hexes(spec: str, col: str) -> dict[str, dict[str, str]]:
    """theme → family → the colour of its `col` cell's first token (dark and light)."""
    out: dict[str, dict[str, str]] = {}
    for theme in ("dark", "light"):
        t = load_theme(theme)
        out[theme] = {}
        for fam in families(spec):
            names = fill_names(fam.get(col, ""))
            if names:
                out[theme][fam["Family"]] = hex_of(t, names[0])
    return out


def fill_hexes(spec: str) -> dict[str, dict[str, str]]:
    """theme → family → its fill's colour (dark and light)."""
    return family_hexes(spec, "Fill")


def pair_matrix(fams: dict[str, str], sim: str | None) -> dict[str, float]:
    """Every family pair's ΔE76 under `sim` (None: the CIELAB L* gap, greyscale)."""
    out: dict[str, float] = {}
    for a, b in combinations(sorted(fams), 2):
        if sim is None:
            d = abs(lab(fams[a])[0] - lab(fams[b])[0])
        else:
            d = delta_e76(simulate(fams[a], sim), simulate(fams[b], sim))
        out[f"{a}/{b}"] = round(d, 1)
    return out


def cvd_tables(spec: str) -> dict[str, dict[str, float]]:
    """BQ-8's full measurement: `fills.<sim>.<theme>` and `glyphs.<sim>.<theme>` pair matrices
    (every two state fills, every two glyph colours) and `grey.<theme>` (ΔL* between fills)."""
    out: dict[str, dict[str, float]] = {}
    for part, col in (("fills", "Fill"), ("glyphs", "GlyphColour")):
        for theme, fams in family_hexes(spec, col).items():
            for sim in SIMS:
                out[f"{part}.{sim}.{theme}"] = pair_matrix(fams, sim)
    for theme, fams in fill_hexes(spec).items():
        out[f"grey.{theme}"] = pair_matrix(fams, None)
    return out


def cvd_pairs(spec: str, col: str = "Fill") -> dict[tuple[str, str], float]:
    """Every family pair → the smallest ΔE76 of its `col` colours (the fills, or the glyph
    colours) under the three simulations in dark and light."""
    worst: dict[tuple[str, str], float] = {}
    for fams in family_hexes(spec, col).values():
        for a, b in combinations(sorted(fams), 2):
            for sim in SIMS:
                d = delta_e76(simulate(fams[a], sim), simulate(fams[b], sim))
                worst[(a, b)] = min(worst.get((a, b), d), d)
    return worst


def jnd_floor() -> float:
    return float(grab(r"^JND = ([\d.]+)", at_base(JND_REL), "E11-D05 JND"))


def dist_values(spec: str) -> tuple[Values, dict[str, object]]:
    out: Values = {}
    extra: dict[str, object] = {}
    hexes = fill_hexes(spec)
    for theme, fams in hexes.items():
        distinct = sorted(set(fams.values()))
        for sim in SIMS:
            ds = [
                delta_e76(simulate(a, sim), simulate(b, sim)) for a, b in combinations(distinct, 2)
            ]
            out[f"DIST:cvd.min.{SIM_KEY[sim]}.{theme}"] = f"ΔE76 {min(ds):.1f}" if ds else "n/a"
        gaps = [abs(lab(a)[0] - lab(b)[0]) for a, b in combinations(distinct, 2)]
        out[f"DIST:grey.min-luma.{theme}"] = f"ΔL* {min(gaps):.1f}" if gaps else "n/a"
        extra[f"fills.{theme}"] = fams
    out["DIST:cvd.jnd-floor"] = f"ΔE76 {jnd_floor():.1f}"
    light = load_theme("light")
    d = delta_e76(
        hex_of(light, "color.status.warning.strong"), hex_of(light, "color.status.danger.strong")
    )
    out["DIST:glyph.warning-danger.light"] = f"ΔE76 {d:.1f}"
    inset = resolve(load_theme("dark"), "space.inset.xs")
    out["DIST:cmp023.track-height"] = f"{2 * int(float(inset))} px"
    pairs = cvd_pairs(spec)
    extra["cvd.pairs"] = {f"{a}/{b}": round(v, 1) for (a, b), v in sorted(pairs.items())}
    extra["cvd.tables"] = cvd_tables(spec)
    return out, extra


def registered_pairs() -> set[tuple[str, str]]:
    return set(re.findall(r'\{ fg: "([^"]+)", bg: "([^"]+)"', at_base(PAIRS_REL)))


def unregistered_pairs() -> list[str]:
    reg = registered_pairs()
    return [k for k, (fg, bg, _r) in PAIRS.items() if (fg, bg) not in reg]


def story_counts(hand: str) -> dict[str, int]:
    rows = {r[0]: r for r in table_rows(section(hand, "§F Storybook"))}
    shell = story_list(rows.get("CMP-245 AlgoBuilderShell", ["", ""])[1])
    card = story_list(rows.get("CMP-118 card", ["", ""])[1])
    label = story_list(rows.get("CMP-246 AlgoStateLabel", ["", ""])[1])
    t1 = table_rows(section(at_base(CITE_FILES["H03"]), "Table 1"))
    row = 0
    for r in t1:
        if r[0] == "CMP-118 row":
            kinds = len(r[1].split(" · "))
            states = len(re.sub(r"\(spec §\d+\)", "", r[2]).split(" · "))
            row += kinds * states
    return {"shell": len(shell), "card": len(card), "row": row, "label": len(label)}


def bound_names() -> set[str]:
    names: set[str] = set()
    for rel in (CITE_FILES["D02"], CITE_FILES["D03"], CITE_FILES["H03"]):
        names |= set(BOUND_NAME.findall(at_base(rel)))
    return names


def out_of_class_a() -> set[str]:
    """Bound names that are missing at the base (b) or a primitive a semantic name aliases (d)."""
    known = all_token_names()
    alias = aliased_primitives()
    return {n for n in bound_names() if n not in known or n in alias}


def on_request(spec: str) -> int:
    para = next(
        (u for u in units(section(spec, "0. Artefacts")) if u.startswith("**Specified")), ""
    )
    drawn = {frame_id(r["Frame"]).split(" · ")[0].split("/")[-1] for r in register(spec)}
    named = re.findall(r"`((?:CMP-\d+)?/[a-z0-9*-]+)`", para)
    return len({x for x in named if "*" not in x and x.split("/")[-1] not in drawn})


def animated(mo: dict[str, str]) -> bool:
    safe = mo.get("Safe", "")
    if "per CMP-043" in safe:
        return False
    return live(safe, r"\bover\b|\bsweep\w*|\bdecay\w*|\bmoves?\b")


def count_values(spec: str, hand: str) -> tuple[Values, dict[str, object]]:
    bd = boards(spec)
    reg = register(spec)
    mos = mo_rows(spec)
    drs = drift_rows(hand)
    verdicts = [d.get("Verdict", "") for d in drs.values()]
    resolved = [k for k, d in drs.items() if not drift_problems(k, d, hand)]
    stories = story_counts(hand)
    fails = [p for p, d in cvd_pairs(spec).items() if d < jnd_floor()]
    out: Values = {
        "COUNT:boards": str(len(bd)),
        "COUNT:boards.light-twins": str(len([b for b in bd if re.search(r"-light`", b[1])])),
        "COUNT:frames.drawn": str(len(reg)),
        "COUNT:frames.on-request": str(on_request(spec)),
        "COUNT:mutations": str(len(mutation_ids(spec))),
        "COUNT:motion.rows": str(len(mos)),
        "COUNT:motion.animated": str(len([m for m in mos.values() if animated(m)])),
        "COUNT:drift.rows": str(len(drs)),
        "COUNT:drift.corrected": str(verdicts.count("corrected")),
        "COUNT:drift.justified": str(verdicts.count("justified")),
        "COUNT:drift.unresolved": str(len(drs) - len(resolved)),
        "COUNT:tokens.bound": str(len(bound_names())),
        "COUNT:drift.class-a": str(len(bound_names() - out_of_class_a())),
        "COUNT:pairs.gated": str(len(table_rows(section(spec, "10. Contrast")))),
        "COUNT:pairs.proposed": str(len(unregistered_pairs())),
        "COUNT:pairs.label": str(len([k for k in PAIRS if LABEL_PAIR.match(k)])),
        "COUNT:cvd.failing-pairs": str(len(fails)),
        "COUNT:stories.shell": str(stories["shell"]),
        "COUNT:stories.card": str(stories["card"]),
        "COUNT:stories.row": str(stories["row"]),
        "COUNT:stories.label": str(stories["label"]),
        "COUNT:stories.runs": str(sum(stories.values()) * THEME_DENSITY_RUNS),
    }
    extra: dict[str, object] = {
        "stories.arithmetic": f"({' + '.join(str(v) for v in stories.values())}) × "
        f"{THEME_DENSITY_RUNS} (2 themes × 2 densities)",
        "cvd.under-floor": [f"{a}/{b}" for a, b in fails],
        "unregistered.pairs": unregistered_pairs(),
        "out-of-class-a": sorted(out_of_class_a()),
        "spec.line-budget": SPEC_LINE_BUDGET,
    }
    return out, extra


Computed = tuple[Values, dict[str, object], dict[str, dict[str, float]]]


def compute(spec: str, hand: str) -> Computed:
    values: Values = {}
    values.update(motion_values())
    values.update(budget_values())
    cv, matrix = contrast_values()
    values.update(cv)
    dv, extra = dist_values(spec)
    values.update(dv)
    cnt, cextra = count_values(spec, hand)
    values.update(cnt)
    extra.update(cextra)
    return values, extra, matrix


# ---------------------------------------------------------------------------- fill and anchors


def fill(text: str, values: Values) -> tuple[str, list[str]]:
    """Replace every placeholder outside a code span with `VALUE<!--=KEY-->`."""
    unknown: list[str] = []

    def sub(m: re.Match[str]) -> str:
        if m[1] not in values:
            unknown.append(m[1])
            return m[0]
        return f"{values[m[1]]}<!--={m[1]}-->"

    out_lines = []
    for line in text.split("\n"):
        parts, pos = [], 0
        for c in CODE.finditer(line):
            parts.append(PLACEHOLDER.sub(sub, line[pos : c.start()]))
            parts.append(c[0])
            pos = c.end()
        parts.append(PLACEHOLDER.sub(sub, line[pos:]))
        out_lines.append("".join(parts))
    return "\n".join(out_lines), sorted(set(unknown))


# verbatim or copy columns a figure may sit in: (section, column) — Table A's Old cell (verbatim at
# the base), the register's Word cell and §3.1's States cell (copy-deck strings, D03 verbatim)
COPY_CELLS = (("Table A", 3), ("9.2 The frame register", 2), ("3.1 Families", 1))


def bare_figures(text: str, values: Values) -> list[str]:
    """Figures with a unit typed by hand: outside an anchor, a quote, a code span, a cite and the
    copy cells of `COPY_CELLS`."""
    hits: list[str] = []
    blank: dict[str, int] = {}
    for head, col in COPY_CELLS:
        for ln in section(text, head).split("\n"):
            if ln.startswith("|") and not is_rule(ln):
                blank[ln] = col
    for i, line in enumerate(text.split("\n"), 1):
        work = line
        if line in blank:
            cells = split_row(line)
            work = " | ".join(c for j, c in enumerate(cells) if j != blank[line])
        for m in reversed(list(ANCHOR.finditer(work))):
            want = values.get(m[1], "")
            start = m.start() - len(want) if work[: m.start()].endswith(want) else m.start()
            work = work[:start] + " ⟨v⟩ " + work[m.end() :]
        work = PLACEHOLDER.sub(" ⟨v⟩ ", work)
        work = QUOTED.sub(" ", CODE.sub(" ", work))
        work = re.sub(r"\(#\d+\)|#\d+", " ", work)
        for m in FIGURE.finditer(work):
            hits.append(f"line {i}: {m[0]!r}")
    return hits


def anchor_gates(name: str, text: str, values: Values, required: set[str]) -> list[str]:
    bad: list[str] = []
    seen: set[str] = set()
    for i, line in enumerate(text.split("\n"), 1):
        for m in PLACEHOLDER.finditer(CODE.sub("", line)):
            bad.append(f"{name}:{i} placeholder {{{{{m[1]}}}}} not filled")
        spans = [c.span() for c in CODE.finditer(line)]
        for m in ANCHOR.finditer(line):
            if any(a <= m.start() < b for a, b in spans):
                continue  # an anchor quoted as code (the format's description)
            key = m[1]
            seen.add(key)
            want = values.get(key)
            if want is None:
                bad.append(f"{name}:{i} anchor {key} is not a value the tool computes")
            elif not line[: m.start()].endswith(want):
                got = re.split(r"[ |*(]", line[: m.start()])[-1]
                bad.append(f"{name}:{i} {key} reads {got!r}; the tool computes {want!r}")
    bad += [f"{name}: no anchored value for {k}" for k in sorted(required - seen)]
    bad += [f"{name} {h}: a figure typed by hand" for h in bare_figures(text, values)]
    return one("G-ANCHOR", bad)


def text_keys(text: str) -> set[str]:
    bare = CODE.sub("", text)
    return set(PLACEHOLDER.findall(bare)) | set(ANCHOR.findall(bare))


# ---------------------------------------------------------------------------- cites


def cite_path(cid: str) -> str | None:
    if re.fullmatch(r"\d{2}", cid):
        return plan_rel(cid)
    if cid in CITE_FILES:
        return CITE_FILES[cid]
    m = re.fullmatch(r"(E\d{2})-D\d{2}", cid)
    if m:
        return f"docs/design/{m[1]}/{cid}.md"
    if "/" in cid:
        return cid
    return None


def cite_gates(texts: dict[str, str], fetch: Fetch) -> tuple[list[str], list[str], int]:
    fails: list[str] = []
    warns: list[str] = []
    done: set[tuple[str, int]] = set()

    def lines_of(rev: str, rel: str) -> list[str] | None:
        t = fetch(rev, rel)
        return None if t is None else t.split("\n")

    for name, text in texts.items():
        for m in CITE_GROUP.finditer(text):
            cid = m["a"] or m["b"]
            refs = [m["first"], *re.findall(r":(\d+(?:[–-]\d+)?)", m["more"])]
            for ref in refs:
                for part in re.split(r"[–-]", ref):
                    n = int(part)
                    if (cid, n) in done:
                        continue
                    done.add((cid, n))
                    rel = cite_path(cid)
                    base = lines_of(BASE, rel) if rel else None
                    if rel is None or base is None:
                        fails.append(f"{name} `{cid}`:{n} no such file at {BASE}")
                        continue
                    if n < 1 or n > len(base) or not base[n - 1].strip():
                        fails.append(f"{name} `{cid}`:{n} line missing or blank at {BASE}")
                        continue
                    head = lines_of(HEAD, rel)
                    if head is not None and (n > len(head) or head[n - 1] != base[n - 1]):
                        warns.append(f"[G-CITE] `{cid}`:{n} drifted at {HEAD}")
    for cid, n, frag in CITED:
        rel = cite_path(cid)
        base = lines_of(BASE, rel) if rel else None
        if base is None or n > len(base) or frag not in base[n - 1]:
            hits = [i + 1 for i, ln in enumerate(base or []) if frag in ln]
            fails.append(f'`{cid}`:{n} "{frag[:40]}" not on the line at {BASE} (found {hits[:4]})')
    return one("G-CITE", fails), warns, len(done) + len(CITED)


# ---------------------------------------------------------------------------- the gates


@dataclass(frozen=True)
class Texts:
    spec: str
    hand: str
    p15: str
    p16: str
    values: Values
    diff_names: tuple[str, ...]  # `git diff --name-only BASE` on disk (G-UNTOUCHED)


NULL_CELL = re.compile(
    r"(?:none|n ?/? ?a|nil|null|empty|tb[dc]|todo|unknown|same|unchanged|as above|"
    r"same as above|ditto|nothing|open|pending|unresolved)"
)


def nullish(cell: str) -> bool:
    """No value: blank, punctuation only ("—", "-", "(…)"), or a null word ("none", "n/a")."""
    words = " ".join(re.sub(r"[\s\-‐-―.,;:!?()\[\]{}<>|*'\"`_…]+", " ", norm_text(cell)).split())
    return not words or NULL_CELL.fullmatch(words) is not None


def malformed(text: str, head: str, ok: str = r"Mo-\d+") -> list[str]:
    """Table rows of `head` whose first cell is not exactly an id of the form `ok`."""
    return [r[0][:16] for r in table_rows(section(text, head)) if not re.fullmatch(ok, r[0])]


TWIN = "prefers-reduced-motion"
TWIN_NULL = (
    r"\bnone\b|\bn ?/ ?a\b|\bsame as (?:the )?(?:motion )?safe\b|\bunchanged\b|\bas above\b"
    r"|\bno (?:reduced (?:motion )?|prefers reduced motion )?(?:variant|twin|reading)\b|\btb[dc]\b"
)
TWIN_OK = (
    r"\bframe 0\b|\bsteps?\b|\binstant\w*|\bstatic\b|\bno flash\b|\bno loop\b|\bcut\b|\bswaps?\b"
)
DIALOG_TWIN = r"\bper cmp 043\b"  # the dialog's twin, cited: accepted on Mo-8 only (record r1)
TWIN_MISSING = (
    r"\b(?:no|without|lacks?|lacking|missing)\s+(?:a |an |its |any )?"
    r"(?:reduced(?: motion)? |prefers reduced motion |motion reduce )?(?:variant|twin|reading)\b"
)
MOVE_VERBS = (
    r"cross ?fad\w*|\bfad(?:e|es|ed|ing)\b|\btween\w*|\beas(?:e|es|ed|ing)\b|slid\w*"
    r"|\bscal(?:e|es|ed|ing)\b|sweep\w*|\bloop\w*|\bmov(?:e|es|ed|ing)\b|translat\w*|glid\w*"
    r"|animat\w*|\bpuls\w*|\bdrift\w*|shimmer\w*|interpolat\w*|\bbounc\w*|\bzoom\w*"
    r"|\bdissolv\w*|\bblend\w*|\bswoop\w*|\bwip(?:e|es|ed|ing) (?:in|down|out)\b"
    r"|\broll(?:s|ed|ing)? (?:in|down|out)\b|\bdescend\w*|\bflies in\b|\bfly in\b"
)
MOVE = MOVE_VERBS + r"|\bover\b|\btransform\b"
# the motion vocabulary every motion sweep shares (records r1 M-a, M-b and r2): ease, interpolate,
# tween, cross-fade, glide, animate, transition, morph, smooth, slide, fade, settle, fill
# continuously, tick up, pulse, bounce, scale, dissolve, blend, zoom and grow, in every inflection
MOTION_VOCAB = (
    r"\beas(?:e|es|ed|ing)\b|interpolat\w*|\btween\w*|cross ?fad\w*|crossfad\w*|glid\w*"
    r"|animat\w*|\btransition\w*|\bmorph\w*|\bsmooth\w*|\bslid(?:e|es|ing)\b"
    r"|\bfad(?:e|es|ed|ing)\b|\bsettl\w*|\bfill(?:s|ed|ing)? continuous\w*|\bcontinuous\w* fill"
    r"|\btick(?:s|ed|ing)? up\b|\bpuls\w*|\bbounc\w*|\bscal(?:e|es|ed|ing) (?:up|down|in|out)\b"
    r"|\bdissolv\w*"
    r"|\bblend\w*|\bzoom\w*|\bgr[eo]w(?:s|n|ing)?\b"
    r"|\broll(?:s|ed|ing)?\b|\bodometer\w*"  # record r3
)
SAMPLE_NOUN = r"(?:samples?|readings?|ticks?|updates?|values?)"  # what a sample is called (r2)
REDUCED = (
    r"\bunder (?:the )?(?:reduced? motion|reduce|prefers reduced motion|the twin)\b"
    r"|\b(?:with|in) reduced motion\b|\bin (?:the )?reduced (?:twin|mode|reading)\b"
    r"|data motion ?= ?\W?reduce\b|\bwhen (?:motion is )?reduced\b|\breduce mode\b"
)
TIMED = (
    r"\b(?!0 )\d+(?:[.,]\d+)* ?(?:ms|milliseconds?)\b|(?<!\b0 )\bmilliseconds?\b"
    r"|motion\.duration\.(?:fast|normal|slow)|\beas(?:e|es|ed|ing)\b|\bbezier\b|motion\.easing"
    r"|\blinear\b|\bover (?:the )?(?:motion\.duration\.)?(?:fast|normal|slow)\b"
    r"|\b(?:fast|normal|slow) / standard\b|\bsettl\w*|\bgradual\w*|\bsmooth\w*"
    # a duration in words or in seconds, and "not instant" (record r2)
    r"|\b(?:a|an|one|1) (?:tenth|fifth|eighth|quarter|third|sixth|hundredth|twentieth)"
    r" of a second\b|\bhalf a second\b|\b(?:split|fraction of a) second\b"
    r"|\b0?[.,]\d*[1-9]\d* ?s(?:ec(?:onds?)?)?\b"
    r"|\b(?:not|never|no longer|isn't|aren't|hardly|barely|scarcely) (?:\w+ )?instant\w*"
    # a duration in frames, two or more (one frame is the never-animates reading; record r3)
    r"|\b(?:[2-9]|\d{2,}|two|three|four|five|six|seven|eight|nine|ten|twelve|several|a few"
    r"|multiple|many|some) (?:\w+ )?frames\b|\b(?:over|across|for) (?:\w+ )?frames\b"
)
STATE_WORDS = r"(?:running|paused|completing|completed|cancelled|halted|failed|degraded|orphaned)"
STATE_CHANGE = (
    r"\bstate (?:transitions?|changes?|swaps?|flips?)\b|\b(?:transitions?|changes?|swaps?) "
    r"(?:between|across|of) (?:two )?(?:algo |run )?states\b"
    rf"|\b{STATE_WORDS}\b ?(?:→|->|to|into|becomes?|turns? into|goes to) ?\b{STATE_WORDS}\b"
    r"|\b(?:t2|enabled|disabled) ?(?:↔|→|->|to) ?(?:t2|enabled|disabled)\b"
    r"|\bstatus (?:changes?|flips?|swaps?|transitions?)\b"  # record r2
)
# the ticket's ask, quoted after "T Scope" (§7.4, D04-C3): the cite exempts that quote only, never
# the rest of its clause and never a sentence that merely names D04-C3 (record r1 M-g); and only a
# quote the ticket itself holds, three words or more (an elision "…" read piece by piece in
# order), never a paraphrase in quotes (record r2)
TICKET_ASK = re.compile(r'(\bT Scope\b[^"\n|;]{0,60}?)"([^"\n]*)"')


@functools.lru_cache(maxsize=1)
def ticket_text() -> str:
    ticket = next(t for t in json.loads(at_base(TICKETS_REL)) if t.get("key") == "E33-D04")
    out: list[str] = []

    def walk(x: object) -> None:
        if isinstance(x, str):
            out.append(x)
        elif isinstance(x, dict):
            for y in x.values():
                walk(y)
        elif isinstance(x, list):
            for y in x:
                walk(y)

    walk(ticket)
    return norm_text("\n".join(out))


def the_ask(quote: str) -> bool:
    """`quote` is the ticket's own text: every piece between elisions, in order."""
    pieces = [norm_text(p) for p in re.split(r"…|\.\.\.", quote)]
    if any(not p for p in pieces) or sum(len(p.split()) for p in pieces) < 3:
        return False
    text, at = ticket_text(), 0
    for p in pieces:
        at = text.find(p, at)
        if at < 0:
            return False
        at += len(p)
    return True


def uncite_ask(text: str) -> str:
    """The text with the ticket's quoted ask blanked (what it cites), everything else kept."""
    return TICKET_ASK.sub(lambda m: m[1] + '" "' if the_ask(m[2]) else m[0], text)


FADE = r"cross ?fad\w*|\bfad(?:e|es|ing|ed)\b|dissolv\w*|\bblend\w*"
STATEISH = (
    r"\bstates?\b|\bt2\b|\bcontrols?\b|\benabled\b|\bdenied\b|\bauthori[sz]ed\b"
    r"|\bwords?,? (?:and )?glyphs?\b|\bglyphs?,? (?:and )?fills?\b|\bcmp 246\b|\bstatus labels?\b"
    rf"|\b(?:{STATE_WORDS}|status) (?:words?|labels?|glyphs?|fills?|badges?|chips?)\b"  # record r2
    rf"|\b{STATE_WORDS}\b ?(?:→|->|to|into|and) ?\b{STATE_WORDS}\b"
)
NUMBER_WORDS = {
    "once": 1, "twice": 2, "thrice": 3, "one": 1, "two": 2, "three": 3, "four": 4, "five": 5,
    "six": 6, "seven": 7, "eight": 8, "nine": 9, "ten": 10, "eleven": 11, "twelve": 12,
    "dozen": 12, "fifteen": 15, "twenty": 20, "thirty": 30, "sixty": 60,
}  # fmt: skip
_NUM = r"(\d+|" + "|".join(NUMBER_WORDS) + r")"
RATE = re.compile(
    rf"\b(?:a\s+)?{_NUM}\s+"
    r"(?:(?:times?|updates?|frames?|samples?|flash\w*|moves?|ticks?|steps?|pulses?)\s+)?"
    r"(?:a|per|each|every|in a|in one)\s+(?:second|sec)\b|\b(\d+)\s?hz\b"
)
# a rate in fps, hertz or "/s", a period as a fraction of a second or in seconds (record r2)
PER_S = re.compile(rf"\b{_NUM}\s?(?:fps|hz|hertz|/\s?s(?:ec(?:ond)?)?)(?!\w)")
FRACTION = {
    "half": 2, "third": 3, "quarter": 4, "fifth": 5, "sixth": 6, "eighth": 8, "tenth": 10,
    "twentieth": 20, "hundredth": 100,
}  # fmt: skip
EVERY_FRACTION = re.compile(rf"\bevery (?:a |one )?({'|'.join(FRACTION)})(?: of a)? second\b")
EVERY_S = re.compile(r"\bevery (\d*[.,]?\d+) ?s(?:ec(?:onds?)?)?\b")
FRAME_RATE = re.compile(
    r"\b(?:every|each|per)\s+(?:animation\s+|rendered\s+|display\s+|paint(?:ed)?\s+)?frames?\b"
    r"(?!\s*0)|\brequestanimationframe\b"
)
GAP = re.compile(r"≥ ?(\d[\d,]*) ?ms between starts|\bevery (\d[\d,]*) ?(?:ms|milliseconds)\b")
SAMPLED = r"\bsampl\w*|\bvalue changes?\b|\bticker\b|\bticks?\b|\bframes?\b|\bupdat\w*"
CADENCE_MOVE = MOVE_VERBS + r"|\bflash\w*|\btransition\w*|\brepeat\w*|\bupdat\w*|\brender\w*"
LIMIT = (
    r"\b(?:no|never|not|nothing|none)\b[^.;]*\b(?:more than|faster than|exceed\w*|above)\b"
    r"|\bat most\b|≤|\bcapped\b|\bcap\b"
)
LOOPING = r"\bloop\w*|(?<![.\w])shimmer\w*|\bsweep\w*|\bcycl\w*|\brepeat\w*"
LOOPERS = r"\bskeletons?\b|\bshimmer\w*|\bplaceholders?\b|\bloading\b"
ROWWISE = r"\b(?:every|each|all|per) rows?\b"
MOTIONISH = r"animat\w*|flash\w*|transition\w*|\bmov(?:e|es|ed|ing)\b|\bpuls\w*|shimmer\w*"
COUNTDOWN_MOVE = (
    r"\banimat\w*|\bsmooth\w*|\btween\w*|\binterpolat\w*|\bmov(?:e|es|ed|ing)\b|\bslid\w*|\bfad\w*"
    r"|\broll\w*|\bsub ?second\b|\bglid\w*|\bscroll\w*|" + MOTION_VOCAB + "|" + MOVE_VERBS
)
DIALOGS = r"\bdialogs?\b|\bmodals?\b|\bcmp 043\b"
DIALOG_MOVE = (
    r"\bscal(?:e|es|ed|ing)\b|\bfad\w*|slid\w*|\bzoom\w*|animat\w*"
    r"|\bpop(?:s|ped|ping)? (?:in|up|open|out)\b|\bgr[eo]w(?:s|n|ing|th)?\b|\bmorph\w*|\bglid\w*"
    r"|\bbounc\w*|\bdissolv\w*|\bblend\w*"  # record r2
)
DIALOG_CITED = r"per cmp 043|\b16:178\b|\bh21\b|\bh03:111\b|\bd02:415\b"
# the tag or the prop switched off, in any phrasing, on any row type or density (record r2)
EMU_OFF = (
    r"\bfalse\b|\bhid(?:e|es|den|ing)\b|\boptional\b|\bomit\w*|\btoggl\w*|\bdisabl\w*"
    r"|\b(?:switch|turn)(?:s|ed|ing)? (?:it )?off\b|\bsuppress\w*|\bremov(?:e|es|ed|ing|al)\b"
    r"|\bdrop(?:s|ped|ping)?\b|\belid\w*|\bset (?:it )?to (?:no|false|off|0|null|undefined)\b"
    r"|\b(?:is|are) not (?:shown|rendered|displayed)\b"
)
EMU_ALLOWED = r"does not compile|\bfails\b|type error|\bthe row variant\b|\bhost whose caption\b"
# CMP-227 under any name: its id, its component name, the slippage-estimate chip it is (record r2)
ESTIMATED = (
    r"\bcmp ?227\b|\bestimated ?badges?\b|\b(?:slippage )?estimated? (?:chips?|badges?|pills?)\b"
    r"|\bslippage estimate\b"
)
GATED = (
    r"\bt2\b|\block\w*|\bgat(?:e|ed|es|ing)\b|\bdisabled\b|\bgr[ae]y(?:ed)? out\b|\brequir\w*"
    r"|algo\.manage|\bblock(?:s|ed)\b|\bunavailable\b|\bpermission\w*"
    r"|\bgr[ae]yed\b|\bdimmed\b|\binert\b|\bheld back\b|\bhold(?:s|ing)? back\b|\bwithh[eo]ld\w*"
    r"|\bsuppress\w*|\bdeferred\b|\buntil the run (?:settles|ends|stops|finishes)\b"  # record r2
    r"|\bignor(?:e|es|ed|ing)\b|\bswallow\w*|\bdisabl(?:e|es|ing)\b|\bno ?ops?\b|\bdoes nothing\b"  # r3
)
NOT_EXITS = (
    r"\bcloses #\d+|\bclos(?:e|es|ing) (?:all )?(?:open )?positions?\b"  # an issue, a position
)
EXITS = r"\bclos(?:e|es|ed|ing)\b|\besc(?:ape)?\b|\bdismiss\w*|\backnowledg\w*"
COLOUR_ONLY = (
    r"\b(?:colou?rs?|fills?|hues?|tints?) (?:alone|only)\b"
    r"|\bonly (?:by |through |via |with )?(?:its |the |a )?(?:\w+ )?(?:colou?r|fill|hue|tint)s?\b"
)


def swept(t: Texts) -> list[str]:
    """The texts every claim sweep reads: the spec without §9.3 (the mutation list describes the
    violations it plants) and the hand-off."""
    return [t.spec.replace(section(t.spec, "9.3 The frame-mutation list"), ""), t.hand]


def g_triad(t: Texts) -> list[str]:
    """R-1 / BQ-8: every frame that shows a state has its Word, Glyph and Fill; "—" only on the
    frames that show no state (the dialog-only frames, Mo-8); the Word leads (a letter first); a
    null value ("none", "n/a", "-", "(none)") is no value; no sentence lets colour carry a state
    alone."""
    bad: list[str] = []
    for r in register(t.spec):
        f = frame_id(r["Frame"])
        if not re.fullmatch(r"`[^`]+`", r["Frame"]):
            bad.append(f"{f}: the Frame cell is not a backticked frame id")
        cells = [r.get(c, "") for c in ("Word", "Glyph", "Fill")]
        if r.get("Motion") == "Mo-8" and all(c == "—" for c in cells):
            continue
        for col, c in zip(("Word", "Glyph", "Fill"), cells, strict=True):
            if nullish(c):
                bad.append(f"{f}: no {col}")
        word = cells[0]
        if not nullish(word) and not re.match(r"[A-Za-z{]", word):
            bad.append(f"{f}: the Word cell does not lead with a word")
    for fam in families(t.spec):
        for col in ("States", "Glyph", "Fill", "GlyphColour", "Word"):
            if nullish(fam.get(col, "")):
                bad.append(f"§3.1 {fam.get('Family')}: no {col}")
    bad += [f"claim: {c!r}" for c in claims(swept(t), COLOUR_ONLY)]
    return one("G-TRIAD", bad)


def g_encode(t: Texts) -> list[str]:
    """R-1 / BQ-8: glyph → fill is a function; families whose fills differ differ in glyph and
    word; every pair under the ΔE floor (any simulation, dark or light) differs in glyph and word;
    each register frame's fill is its glyph's family fill."""
    bad: list[str] = []
    fams = families(t.spec)
    glyph_fill: dict[str, set[str]] = {}
    info: dict[str, tuple[str, str, set[str]]] = {}
    for f in fams:
        g, fl = glyph_names(f["Glyph"]), fill_names(f["Fill"])
        if not g or not fl:
            continue
        glyph_fill.setdefault(g[0], set()).add(fl[0])
        info[f["Family"]] = (g[0], fl[0], fam_words(f["States"]))
    for glyph, fills in sorted(glyph_fill.items()):
        if len(fills) > 1:
            bad.append(f"glyph `{glyph}` takes {len(fills)} fills (R-1: one fill per glyph)")
    floor = jnd_floor()
    under = {p for p, d in cvd_pairs(t.spec).items() if d < floor}
    under |= {p for p, d in cvd_pairs(t.spec, "GlyphColour").items() if d < floor}
    for a, b in combinations(sorted(info), 2):
        (ga, fa, wa), (gb, fb, wb) = info[a], info[b]
        if (fa != fb or (a, b) in under) and (ga == gb or wa & wb):
            why = "fills differ" if fa != fb else f"fill or glyph colour under ΔE76 {floor:g}"
            bad.append(f"{a} / {b}: {why} but glyph or word is shared")
    by_glyph = {g: next(iter(fl)) for g, fl in glyph_fill.items() if len(fl) == 1}
    for r in register(t.spec):
        gs, fs = glyph_names(r.get("Glyph", "")), fill_names(r.get("Fill", ""))
        if len(gs) != 1 or "→" in r.get("Fill", "") or not fs:
            continue
        want = by_glyph.get(gs[0])
        if want is None:
            bad.append(f"{frame_id(r['Frame'])}: glyph `{gs[0]}` is in no §3.1 family")
        elif want not in fs:
            bad.append(f"{frame_id(r['Frame'])}: `{gs[0]}` on {fs[0]}, its family fill is {want}")
    return one("G-ENCODE", bad)


def g_word_leads(t: Texts) -> list[str]:
    bad = claims(
        swept(t),
        r"(?<!word )(?<!word \()\blead(?:s|ing)?\b",
        near=r"\b(?:glyph|icon|colou?r|fill)s?\b",
    )
    s36 = norm_text(section(t.spec, "3.6 A11y contract"))
    if "the word leads the accessible name" not in s36:
        bad.append("§3.6 does not state that the word leads the accessible name")
    a2 = norm_text(bullet(section(t.hand, "C.2 A-2"), "A11y"))
    if "the word leads the accessible name" not in a2:
        bad.append("A-2 A11y does not state that the word leads the accessible name")
    return one("G-WORD-LEADS", bad)


def twin_body(cell: str) -> str | None:
    """The reduced reading after "prefers-reduced-motion:" (None when the cell has no twin)."""
    m = re.match(r"\s*`?prefers-reduced-motion`?:\s*(.*)$", cell.strip(), re.DOTALL)
    return m[1] if m else None


def twin_ok(cell: str, safe: str = "", dialog: bool = False) -> bool:
    """A twin states its reduced reading: not null, and it names the cut, the step, the swap, the
    static state or the dropped effect; "the same" / "same as motion-safe" is a twin only when
    the motion-safe reading (`safe`) is itself instant; "per CMP-043" only on the dialog row."""
    body = twin_body(cell)
    if body is None or nullish(body):
        return False
    n = norm_text(unquote(body))
    if dialog and re.search(DIALOG_TWIN, n):
        return True
    if live(body, MOVE):
        return True  # a twin that moves is G-REDUCE-INSTANT's
    if re.match(r"(?:the )?same\b", n) or re.search(r"\bsame as\b", n):
        if not live(body, TWIN_OK) and not (live(safe, TWIN_OK) and not live(safe, MOVE)):
            return False
        n = re.sub(r"\bsame as (?:the )?(?:motion )?safe\b", " ", n)
    return not re.search(TWIN_NULL, n) and (live(body, TWIN_OK) or n.startswith("the same"))


def g_twin(t: Texts) -> list[str]:
    bad = [f"{k}: no `prefers-reduced-motion` twin" for k, r in mo_rows(t.spec).items()
           if not twin_ok(r.get("Twin", ""), r.get("Safe", ""), k == "Mo-8")]  # fmt: skip
    bad += [
        f"{frame_id(r['Frame'])}: no Reduce twin"
        for r in register(t.spec)
        if not twin_ok(r.get("Reduce", ""), dialog=r.get("Motion", "").strip() == "Mo-8")
    ]
    if len(mo_rows(t.spec)) < 1:
        bad.append("§7.2 has no motion rows")
    bad += [f"{k}: not a motion-table row id" for k in malformed(t.spec, "7.2 The motion table")]
    for text in swept(t):
        for u in units(text):
            for c in clauses(u):
                n = norm_text(c)
                if re.search(TWIN_MISSING, n) and not re.search(r"\bthe tool\b|\bfails?\b", n):
                    bad.append(f"claim: {n[:60]!r}")
    return one("G-TWIN", bad)


def c8_twins(row: list[str]) -> list[str]:
    """Each reduced reading a C.8 row states (the text after "`prefers-reduced-motion`:")."""
    joined = " | ".join(row[1:])
    return [m[1] for m in re.finditer(r"`prefers-reduced-motion`:\s*([^;|]*)", joined)]


def g_twin16(t: Texts) -> list[str]:
    rows = c8_rows(t.hand)
    bad: list[str] = []
    for r in rows:
        twins = c8_twins(r)
        said = any(live(c, r"prefers reduced motion") for c in sentences(" | ".join(r[1:])))
        if not twins or not said:
            bad.append(f"C.8 '{r[0][:30]}': no `prefers-reduced-motion` twin")
        safe = (r[1] if len(r) > 1 else "").split("`prefers-reduced-motion`")[0]
        bad += [
            f"C.8 '{r[0][:30]}': twin {w[:24]!r}"
            for w in twins
            if not twin_ok(f"{TWIN}: {w}", safe)
        ]
    if not rows:
        bad.append("hand-off §C.8 has no rows")
    return one("G-TWIN16", bad)


def g_reduce_instant(t: Texts) -> list[str]:
    bad = [f"{k} twin moves" for k, r in mo_rows(t.spec).items() if live(r.get("Twin", ""), MOVE)]
    bad += [
        f"{frame_id(r['Frame'])} Reduce moves"
        for r in register(t.spec)
        if live(r.get("Reduce", ""), MOVE)
    ]
    for r in c8_rows(t.hand):
        if any(live(w, MOVE) for w in c8_twins(r)):
            bad.append(f"C.8 '{r[0][:24]}' twin moves")
    if "every twin is instant" not in norm_text(section(t.spec, "7.5 Reduced motion")):
        bad.append("§7.5 does not state that every twin is instant")
    bad += [
        f"claim: {c!r}"
        for c in claims(swept(t), MOVE_VERBS, near=REDUCED, unless=r"\b0[.,]01 ms\b")
    ]
    return one("G-REDUCE-INSTANT", bad)


DURATION_OTHER = r"motion\.duration\.(?:fast|normal|slow)|\b(?!0 ms)\d+(?:[.,]\d+)* ?ms\b"
CUT_ROWS = ("Mo-6", "Mo-9", "Mo-10")  # the state, shading and switch cuts (Mo-5 is G-BANNER's)


def g_instant(t: Texts) -> list[str]:
    """R-2 / BQ-11: a state transition is `motion.duration.instant`, frame 0, no easing."""
    bad: list[str] = []
    mos = mo_rows(t.spec)
    for k in CUT_ROWS:
        r = mos.get(k)
        if r is None:
            bad.append(f"{k} missing")
            continue
        tok = plain(r.get("Tokens", ""), t.values)
        names = set(re.findall(r"`(motion\.[a-z.]+)`", tok))
        if names != {"motion.duration.instant"}:
            bad.append(f"{k} Tokens bind {sorted(names)}, not `motion.duration.instant` alone")
        for col in ("Property", "Tokens", "Safe"):
            if live(plain(r.get(col, ""), t.values), TIMED, keep_quotes=True):
                bad.append(f"{k} {col} carries a non-instant duration or an easing")
    m6 = norm_text(mos.get("Mo-6", {}).get("Safe", ""))
    if "frame 0" not in m6 or "no easing" not in m6:
        bad.append("Mo-6 does not read frame 0, no easing")
    texts = [uncite_ask(plain(x, t.values)) for x in swept(t)]
    bad += [f"claim: {c!r}" for c in claims(texts, TIMED, near=STATE_CHANGE, keep_quotes=True)]
    r2 = norm_text(bullet(section(t.spec, "1.5 Rules stated once"), "R-2"))
    s74 = norm_text(section(t.spec, "7.4 State transitions"))
    if "frame 0" not in r2 or "no easing" not in r2 or "no easing" not in s74:
        bad.append("R-2 / §7.4 do not state frame 0, no easing")
    return one("G-INSTANT", bad)


def g_nofade(t: Texts) -> list[str]:
    """BQ-11 / E09-D08 F-8: no cross-fade between two states, a T2 and an enabled control."""
    mos = mo_rows(t.spec)
    bad = [
        f"{k} {col} fades"
        for k in ("Mo-5", *CUT_ROWS)
        for col in ("Property", "Safe", "Twin")
        if live(mos.get(k, {}).get(col, ""), FADE, keep_quotes=True)
    ]
    asks = [uncite_ask(x) for x in swept(t)]  # quoted copy is a claim; only the ask is a cite
    bad += [f"claim: {c!r}" for c in claims(asks, FADE, near=STATEISH, keep_quotes=True)]
    return one("G-NOFADE", bad)


def g_banner(t: Texts) -> list[str]:
    """BQ-12: the degraded carriers enter and clear at frame 0 in both modes."""
    bad: list[str] = []
    r = mo_rows(t.spec).get("Mo-5", {})
    safe, tok = plain(r.get("Safe", ""), t.values), plain(r.get("Tokens", ""), t.values)
    if "frame 0" not in safe or re.search(DURATION_OTHER, safe + tok) or live(safe, MOVE):
        bad.append("Mo-5 does not enter and clear at frame 0 without motion")
    if live(r.get("Property", ""), MOVE):
        bad.append("Mo-5 Property moves")
    if set(re.findall(r"`(motion\.[a-z.]+)`", tok)) != {"motion.duration.instant"}:
        bad.append("Mo-5 Tokens are not `motion.duration.instant` alone")
    for row in table_rows(section(t.spec, "3.2 Variant `degraded`")):
        if len(row) > 4 and "frame 0, both modes" not in row[4]:
            bad.append(f"§3.2 '{row[0][:20]}' Motion is not frame 0 in both modes")
    near = r"\bbanners?\b|\bcarriers?\b"
    bad += [f"claim: {c!r}" for c in claims(swept(t), MOVE_VERBS, near=near)]
    c8 = [r for r in c8_rows(t.hand) if r[0].startswith("Degraded")]
    if not c8 or "frame 0 in both modes" not in c8[0][1]:
        bad.append("C.8 carriers row is not frame 0 in both modes")
    return one("G-BANNER", bad)


def g_step(t: Texts) -> list[str]:
    """BQ-10: in a grid row the bar is a step: no transition at all, in both modes."""
    bad: list[str] = []
    r = mo_rows(t.spec).get("Mo-1", {})
    safe = plain(r.get("Safe", ""), t.values)
    if "no transition" not in safe or live(safe, MOVE) or re.search(DURATION_OTHER, safe):
        bad.append("Mo-1 is not a step with no transition")
    if "step" not in r.get("Twin", ""):
        bad.append("Mo-1's twin is not the same step")
    moving = MOVE_VERBS + r"|\btransition\w*|\bover\b"
    # the grid's bar under any name: "the row's bar", "bars inside the grid's rows" (record r2)
    near = (
        r"\bgrid(?:'s)? (?:row(?:'s)? )?bars?\b|\bbars? (?:in|inside|within) (?:a |the )?grid"
        r"|\bbars? (?:in|inside|within|on) (?:a |the )?(?:grid(?:'s)? )?rows?\b|\bin a grid row\b"
        r"|\brow's bars?\b"  # possessive only: the hand-off's "(row bar: a step)" names Mo-1
        # every bar, a grid bar included, and bars named by where they sit (record r3)
        r"|\b(?:every|each|all|any|all the|all of the) (?:progress )?bars?\b(?! whose)"
        r"|\b(?:algos tab|scr ?070|algos (?:grid|table|list|screen))\b.*\bbars?\b"
    )
    bad += [f"claim: {c!r}" for c in claims(swept(t), moving, near=near)]
    grid = [x for x in c8_rows(t.hand) if x[0].startswith("Bars in grid rows")]
    if not grid or "no transition" not in grid[0][1]:
        bad.append("C.8 grid-bar row is not a step")
    a7 = next((x for x in table_rows(section(t.hand, "Table A")) if x[0] == "A-7.2"), [])
    if not a7 or "in a grid row the fill steps with no transition" not in a7[-1]:
        bad.append("A-7.2 New does not step the fill in a grid row")
    return one("G-STEP", bad)


def durations_ms(text: str) -> list[int]:
    prim = token_file("primitives")
    out = [
        int(str(prim[f"motion.duration.{k}"]).removesuffix("ms"))
        for k in re.findall(r"motion\.duration\.([a-z]+)", text)
        if f"motion.duration.{k}" in prim
    ]
    return out


def interval_ms(text: str) -> int | None:
    m = re.search(r"at most (\d+) per second", text)
    if m:
        return 1000 // int(m[1])
    m = re.search(r"≥ (\d+) ms between starts", text)
    return int(m[1]) if m else None


def rates_hz(text: str) -> list[float]:
    """Every rate a text states, in Hz: "N per second", "N times a second", "N Hz", "every
    frame" (60), "≥ N ms between starts", "every N ms"; and "N fps", "N hertz", "N/s", "N times
    per sec", "every quarter second", "every 0.1 s" (record r2)."""
    n = norm_text(text)
    out: list[float] = []
    for m in [*RATE.finditer(n), *PER_S.finditer(n)]:
        word = m[1] or m[2]
        out.append(float(word) if word.isdigit() else float(NUMBER_WORDS[word]))
    out += [float(FRACTION[m[1]]) for m in EVERY_FRACTION.finditer(n)]
    for m in EVERY_S.finditer(n):
        secs = float(m[1].replace(",", "."))
        out.append(1.0 / secs if secs else 60.0)
    out += [60.0 for _ in FRAME_RATE.finditer(n)]
    for m in GAP.finditer(n):
        ms = int((m[1] or m[2]).replace(",", ""))
        out.append(1000.0 / ms if ms else 60.0)
    return out


def g_cadence(t: Texts) -> list[str]:
    """R-3 / BQ-10 rule 1: an animated, sampled row off the grid declares its sample interval, the
    rate is within the render cap, and its transition ends before the next sample; no sentence
    moves anything faster than the cap (a flash: than the flash bar)."""
    bad: list[str] = []
    cap = int(t.values.get("MOTION:cadence.render-max-hz", "0"))
    flash_cap = int(t.values.get("MOTION:flash.max-per-s", "0"))
    for k, r in mo_rows(t.spec).items():
        trig = plain(r.get("Trigger", ""), t.values)
        row = plain(" ".join(r.get(c, "") for c in ("Trigger", "Safe")), t.values)
        found = rates_hz(row)
        if not found and not re.search(SAMPLED, norm_text(trig)):
            continue  # a state change, a load or an open: no sample to animate between
        if "grid row" in r.get("Element", "") and not found:
            continue
        if not animated(r) and not found:
            continue
        if re.search(r"\bload\w*|\bopen\w*|\bpress\w*", norm_text(trig)) and not rates_hz(trig):
            continue  # a load or an open: no sample to animate between
        longest = max(durations_ms(row + plain(r.get("Tokens", ""), t.values)) or [0])
        if not found:
            bad.append(f"{k} animates between samples with no declared interval")
        elif cap and max(found) > cap:
            bad.append(f"{k} moves at {max(found):g} Hz, past the {cap} Hz render cap")
        elif longest >= 1000 / max(found):
            bad.append(
                f"{k} moves for {longest} ms, longer than its {1000 / max(found):g} ms interval"
            )
    for text in (plain(x, t.values) for x in swept(t)):
        for u in units(text):
            for c in clauses(u):
                n = norm_text(c)
                if not live(c, CADENCE_MOVE) or re.search(LIMIT, n):
                    continue
                found = rates_hz(c)
                bar = flash_cap if re.search(r"\bflash\w*", n) else cap
                if found and max(found) > bar:
                    bad.append(f"claim: {n[:60]!r} ({max(found):g} Hz > {bar} Hz)")
    s71 = norm_text(plain(section(t.spec, "7.1 Cadence"), t.values))
    if f"at most {cap} hz" not in s71:
        bad.append("§7.1 does not cap the render at the cadence")
    return one("G-CADENCE", bad)


EASING_WORDS = (
    r"\blinear\b|\bease in\b|\bease out\b|\bease in out\b|\bsteps\(|\bspring\w*|\bbounce\w*"
)


def g_easing(t: Texts) -> list[str]:
    """BQ-1: a motion row binds only shipped durations and easings, no other easing curve."""
    prim = token_file("primitives")
    shipped = t.values.get("MOTION:easing.standard", "")
    cells = [(k, c, r.get(c, "")) for k, r in mo_rows(t.spec).items() for c in ("Safe", "Tokens")]
    cells += [("C.8", r[0][:20], " ".join(r[1:])) for r in c8_rows(t.hand)]
    bad: list[str] = []
    for k, col, cell in cells:
        for n in re.findall(r"`(motion\.(?:duration|easing)\.[a-z]+)`", cell):
            if n not in prim:
                bad.append(f"{k} {col}: `{n}` is not shipped")
        if live(cell, EASING_WORDS):
            bad.append(f"{k} {col}: an easing other than the shipped curves")
        for m in re.finditer(r"cubic-bezier\(([^)]*)\)", plain(cell, t.values)):
            if " ".join(m[0].split()) != " ".join(shipped.split()):
                bad.append(f"{k} {col}: {m[0]} is not `motion.easing.standard`")
    return one("G-EASING", bad)


def g_motion_tokens(t: Texts) -> list[str]:
    """BQ-14: Tokens cells bind only shipped motion durations and easings; the skeleton none."""
    prim = token_file("primitives")
    bad: list[str] = []
    for k, r in mo_rows(t.spec).items():
        for n in re.findall(r"`(motion\.[a-z.]+)`", r.get("Tokens", "")):
            if n not in prim:
                bad.append(f"{k}: `{n}` is not a shipped motion token")
    m7 = mo_rows(t.spec).get("Mo-7", {})
    if "motion." in m7.get("Tokens", "") or "no motion token" not in m7.get("Tokens", ""):
        bad.append("Mo-7 (the skeleton) binds a motion token")
    sk = [r for r in c8_rows(t.hand) if r[0].startswith("Skeleton")]
    if sk and "`motion." in " ".join(sk[0]):
        bad.append("C.8 skeleton row binds a motion token")
    return one("G-MOTION-TOKENS", bad)


def g_loop(t: Texts) -> list[str]:
    """BQ-14: nothing moves past the loop limit without a pause control: the skeleton stops."""
    bad: list[str] = []
    lim = int(t.values.get("MOTION:loop.max-s", "0"))
    stop = int(t.values.get("MOTION:skeleton.stop-s", "0"))
    m7 = plain(mo_rows(t.spec).get("Mo-7", {}).get("Safe", ""), t.values)
    sk = [r for r in c8_rows(t.hand) if r[0].startswith("Skeleton")]
    for name, cell in (
        ("Mo-7", m7),
        ("C.8 skeleton", plain(" ".join(sk[0]) if sk else "", t.values)),
    ):
        m = re.search(r"stopped at (\d+) s", cell)
        if not m:
            bad.append(f"{name} loops with no stop")
        elif int(m[1]) > lim:
            bad.append(f"{name} stops at {m[1]} s, past {lim} s")
    if stop > lim:
        bad.append(f"the skeleton stop {stop} s is past {lim} s")
    if "pause control" not in norm_text(section(t.spec, "7.6 Flash")):
        bad.append("§7.6 does not name the pause-control rule")
    for text in (plain(x, t.values) for x in swept(t)):
        for u in units(text):
            if not claims([u], LOOPING, near=LOOPERS):
                continue
            stops = [
                int(x) for x in re.findall(r"\bstop(?:s|ped)? (?:at|after) (\d+) s\b", norm_text(u))
            ]
            if not stops or max(stops) > lim:
                bad.append(f"claim: {norm_text(u)[:60]!r} loops with no stop ≤ {lim} s")
    return one("G-LOOP", bad)


def g_focused(t: Texts) -> list[str]:
    """BQ-14 / T Perf: the flash is bounded to the focused row; no per-row animation on SCR-070."""
    bad: list[str] = []
    r = mo_rows(t.spec).get("Mo-3", {})
    if "the focused row" not in r.get("Element", "") or "on the focused row" not in r.get(
        "Trigger", ""
    ):
        bad.append("Mo-3 is not bounded to the focused row")
    bad += [f"claim: {c!r}" for c in claims(swept(t), MOTIONISH, near=ROWWISE, near_live=True)]
    return one("G-FOCUSED", sorted(set(bad)))


# the countdown under any name: "count-down" (normalised to "count down"), the remaining time, a
# slice timer (record r2)
COUNTDOWNS = (
    r"\bcount ?downs?\b|\bnext slice in\b|\bremaining time\b|\btime (?:remaining|left)\b"
    r"|\b(?:slice |next slice |run )?timers?\b"
    # "time to next slice", "seconds until the next child" (record r3)
    r"|\b(?:time|seconds?|minutes?|wait) (?:to|until|till|before) (?:the )?next\b"
    r"|\b(?:seconds?|minutes?|time) (?:left|remaining|to go)\b|\bslice clock\b|\beta\b"
)


def g_countdown(t: Texts) -> list[str]:
    """BQ-13: countdowns are a text swap on one shared ticker, `aria-live="off"`, never animate."""
    bad: list[str] = []
    r = mo_rows(t.spec).get("Mo-4", {})
    row = " | ".join(r.values())
    if r.get("Focus", "").strip() != '`aria-live="off"`':
        bad.append('Mo-4\'s Focus is not `aria-live="off"`')
    if re.search(r'aria-live="(?:polite|assertive)"', row):
        bad.append("Mo-4 announces the countdown")
    safe = norm_text(r.get("Safe", ""))
    if "never animates" not in safe or "shared ticker" not in safe:
        bad.append("Mo-4 does not read one shared ticker, never animates")
    c8 = [x for x in c8_rows(t.hand) if x[0].startswith("Countdowns")]
    if not c8 or 'aria-live="off"' not in c8[0][1] or "never animates" not in c8[0][1]:
        bad.append("C.8 countdowns row is not off and still")
    # quoted copy is a claim too; only the ticket's own quoted ask is a cite (record r3: a quote
    # the ticket does not hold, then "and it does", carried the claim through the quote)
    asks = [uncite_ask(plain(x, t.values)) for x in swept(t)]
    bad += [
        f"claim: {c!r}" for c in claims(asks, COUNTDOWN_MOVE, near=COUNTDOWNS, keep_quotes=True)
    ]
    return one("G-COUNTDOWN", bad)


NUMBERISH = (
    r"\b(?:digits?|numbers?|prices?|sizes?|countdowns?|figures?|percent\w*|quantit\w*|qty)\b"
    r"|\bprogress (?:text|strings?)\b|\bvalue ?text\b|\bvaluetext\b"
)
TWEEN = (
    r"count(?:s|ing|ed)? (?:up|down)|\btween\w*|interpolat\w*|roll(?:s|ing)? (?:up|over)"
    r"|odometer\w*|" + MOTION_VOCAB
)


_NEXT = r"(?:next|new|following|subsequent|later)"
BETWEEN_SAMPLES = (
    rf"\bbetween (?:two |the |each |successive |consecutive )?{SAMPLE_NOUN}"
    rf"|\b(?:toward\w*|until|for) (?:the |each )?{_NEXT} {SAMPLE_NOUN}"
    rf"|\bfrom (?:one|each|a|the|this) (?:\w+ )?{SAMPLE_NOUN} to (?:the |a )?{_NEXT}\b"
    # "to the following one", "across successive readings" (record r3)
    rf"|\bto the (?:following|subsequent) (?:one|{SAMPLE_NOUN})\b"
    rf"|\b(?:across|over|through|along) (?:\w+ )?(?:successive|consecutive|subsequent)"
    rf" {SAMPLE_NOUN}"
)


def g_tween(t: Texts) -> list[str]:
    """BQ-10 rules 2 and 3: no tweened numbers, and nothing (a bar included) eases, interpolates
    or glides between samples: a single-run bar moves once per sample and ends before the next."""
    # a countdown's motion is G-COUNTDOWN's (one FAIL per form); its digits stay numbers here
    numbers = NUMBERISH.replace(r"countdowns?|", "")
    bad = [f"claim: {c!r}" for c in claims(swept(t), TWEEN, near=numbers)]
    moving = MOTION_VOCAB + "|" + MOVE_VERBS
    bad += [
        f"claim: {c!r}" for c in claims(swept(t), moving, near=BETWEEN_SAMPLES, unless=COUNTDOWNS)
    ]  # a countdown "between ticks" is G-COUNTDOWN's, one FAIL per form
    if "no tweened numbers" not in norm_text(section(t.spec, "7.1 Cadence")):
        bad.append("§7.1 rule 2 is gone")
    return one("G-TWEEN", bad)


def g_dialog(t: Texts) -> list[str]:
    """BQ-14: the dialog row reads "per CMP-043 as ruled"; FO H21 is not decided here."""
    bad: list[str] = []
    r = mo_rows(t.spec).get("Mo-8", {})
    safe = r.get("Safe", "")
    if "per CMP-043 as ruled" not in safe:
        bad.append("Mo-8 does not read per CMP-043 as ruled")
    if live(safe, r"\bscal\w*|\bfad\w*|slid\w*|\bnormal\b"):
        bad.append("Mo-8 decides a dialog recipe")
    bad += [
        f"claim: {c!r}" for c in claims(swept(t), DIALOG_MOVE, near=DIALOGS, unless=DIALOG_CITED)
    ]
    return one("G-DIALOG", bad)


# §7.3's never-animates items no other sweep owns: the theme and density switch, DEMO ↔ LIVE, the
# "Emulated" tag and the stale shading (record r3); state flips, numbers, countdowns, T2 ↔ enabled
# and the carriers are G-INSTANT's, G-NOFADE's, G-TWEEN's, G-COUNTDOWN's and G-BANNER's (one FAIL
# per form)
_SWITCH = r"(?:switch\w*|toggl\w*|chang\w*|flips?|swaps?)"
NEVER_ITEMS = (
    rf"\b(?:theme|density|colou?r scheme|dark mode|light mode)(?: and density)? {_SWITCH}"
    rf"|\b{_SWITCH} (?:between |of )?(?:the )?(?:theme|density|dark and light|light and dark)\b"
    r"|\bdemo ?(?:↔|<->|<>|→|->|/|to|and|or|vs\.?) ?live\b|\blive ?(?:↔|<->|<>|→|->|/|to|and|or)"
    r" ?demo\b|\b(?:environment|env|demo|live|trading mode|account mode) (?:switch\w*|toggl\w*"
    r"|badges?|chips?|pills?)\b|\bemulated (?:tags?|badges?|chips?|pills?)\b|\bstale shad\w*"
)


def g_never(t: Texts) -> list[str]:
    """§7.3 (E30-D04:553): the never-animates items take one frame in both modes; any motion
    vocabulary on one of them is a claim."""
    bad = (
        [] if "one frame in both modes" in section(t.spec, "7.3 Never animates") else ["§7.3 gone"]
    )
    moving = MOTION_VOCAB + "|" + MOVE_VERBS + r"|\bflash\w*"
    bad += [f"claim: {c!r}" for c in claims(swept(t), moving, near=NEVER_ITEMS)]
    # a state flip and a T2 ↔ enabled change in any motion word; a fade or a duration there is
    # G-NOFADE's and G-INSTANT's claim (one FAIL per form)
    asks = [uncite_ask(plain(x, t.values)) for x in swept(t)]
    flips = STATE_CHANGE + r"|\bstatus labels?\b|\bcmp 246\b|\bt2 controls?\b"
    flip_move = moving.replace(r"|\btransition\w*", "")  # "a state transition" names the flip
    owned = set(claims(asks, TIMED, near=STATE_CHANGE, keep_quotes=True))
    owned |= set(claims(asks, FADE, near=STATEISH, keep_quotes=True))
    bound = re.compile(rf"(?:{flips})[^.;|,]{{0,40}}?(?:{flip_move})")  # the item as subject
    for c in (c for x in asks for u in units(x) for c in clauses(u)):
        n = norm_text(c)
        if bound.search(n) and live(c, flip_move, True) and n[:70] not in owned:
            bad.append(f"claim: {n[:70]!r}")
    return one("G-NEVER", bad)


def g_q1(t: Texts) -> list[str]:
    """BQ-9: case 1's Cancel T2 is D03's merged decision, cited, not re-decided."""
    q1 = bullet(section(t.spec, "13.3 Open questions"), "D04-Q1")
    bad: list[str] = []
    if "cited, not re decided" not in norm_text(q1):
        bad.append("D04-Q1 does not cite D03's decision")
    if claims([q1], r"\bt1\b", near=r"\bcancel\w*"):
        bad.append("D04-Q1 re-decides Cancel")
    return one("G-Q1", bad)


def g_tier(t: Texts) -> list[str]:
    """BQ-5: AlgoBuilderShell is an Organism."""
    tier = bullet(section(t.hand, "C.1 A-1"), "Tier")
    bad: list[str] = []
    if "Organism" not in tier or live(tier, r"\bmolecules?\b"):
        bad.append("A-1 Tier is not Organism")
    if "**Tier** Organism" not in section(t.spec, "5. CMP-245"):
        bad.append("§5 Tier is not Organism")
    bad += [
        f"claim: {c!r}"
        for c in claims(swept(t), r"\bmolecules?\b", near=r"algobuildershell|cmp 245")
    ]
    return one("G-TIER", bad)


KIND_UNION = {"twap", "iceberg", "chase"}


def union_of(text: str, field: str) -> set[str] | None:
    m = re.search(rf"`?{field}\??: ((?:\"[a-z]+\"\s*\|?\s*)+)", text)
    return set(re.findall(r'"([a-z]+)"', m[1])) if m else None


def g_kind(t: Texts) -> list[str]:
    """BQ-5: the shell's kind union stays twap · iceberg · chase."""
    a1 = section(t.hand, "C.1 A-1")
    bad: list[str] = []
    for label in ("Props", "API sketch"):
        u = union_of(bullet(a1, label), "kind")
        if u != KIND_UNION:
            bad.append(f"A-1 {label} kind union is {sorted(u or [])}")
    if '`"twap" | "iceberg" | "chase"`' not in section(t.spec, "5. CMP-245"):
        bad.append("§5 does not keep the kind union")
    return one("G-KIND", bad)


def g_reduce_source(t: Texts) -> list[str]:
    """BQ-15: reduced motion is specified once (`data-motion`); no component reads the query."""
    s75 = section(t.spec, "7.5 Reduced motion")
    bad: list[str] = []
    if "`data-motion = safe | reduce`" not in s75:
        bad.append("§7.5 does not name `data-motion`")
    term = r"matchmedia|\breads? (?:the )?(?:prefers reduced motion|media query)"
    bad += [f"claim: {c!r}" for c in claims(swept(t), term)]
    return one("G-REDUCE-SOURCE", bad)


def g_cr(t: Texts) -> list[str]:
    """BQ-8: the glyph CRs, the `algo-status` encoding and the `pairs.mjs` rows are PROPOSED."""
    rows = rows_by(section(t.hand, "§D Change requests"), r"CR-[A-Z0-9]+")
    bad: list[str] = []
    for cr in ("CR-G1", "CR-G2", "CR-G3", "CR-G4", "CR-E1", "CR-P1", "CR-3"):
        if cr not in rows:
            bad.append(f"{cr} missing")
    e1 = rows.get("CR-E1")
    if e1 and ("`algo-status`" not in e1[1] or "CODEOWNER" not in e1[4] or "PROPOSED" not in e1[5]):
        bad.append("CR-E1 is not the PROPOSED `algo-status` row to the `tools/` CODEOWNER")
    if '"algo-status"' in at_base(ENCODINGS_REL):
        bad.append("`algo-status` already exists at the base")
    p1 = rows.get("CR-P1")
    if p1:
        listed = set(re.findall(r'fg: "([^"]+)", bg: "([^"]+)"', p1[2]))
        want = {(PAIRS[k][0], PAIRS[k][1]) for k in unregistered_pairs()}
        if listed != want:
            bad.append(f"CR-P1 lists {len(listed)} rows; {len(want)} §10 pairs are unregistered")
    return one("G-CR", bad)


def cmp_ids(text: str) -> set[int]:
    return {int(x) for x in re.findall(r"CMP-(\d{3})", text)}


@functools.lru_cache(maxsize=1)
def id_ledger() -> tuple[int, frozenset[int]]:
    """`15`'s highest id and the ids above it merged design specs already claim."""
    top = max(cmp_ids(at_base(P15_REL)))
    grep = cmp_ids(git_out("grep", "-ohE", r"CMP-[0-9]{3}", BASE, "--", "docs/design"))
    claimed: set[int] = set()
    while top + len(claimed) + 1 in grep:  # the contiguous run above `15` (not a placeholder id)
        claimed.add(top + len(claimed) + 1)
    return top, frozenset(claimed)


def g_one_entry(t: Texts) -> list[str]:
    """BQ-7: one status entry with variants (CMP-246, an Atom); ids derived, nothing else new."""
    top, claimed = id_ledger()
    shell = max(claimed | {top}) + 1
    label = shell + 1
    bad: list[str] = []
    body = t.spec.replace(section(t.spec, "9.3 The frame-mutation list"), "") + t.hand
    for n in sorted(cmp_ids(body) - set(claimed) - {shell, label}):
        if n > top:
            bad.append(f"CMP-{n} is not a derived id (shell CMP-{shell}, label CMP-{label})")
    if not section(t.spec, f"3. CMP-{label} AlgoStateLabel"):
        bad.append(f"§3 is not CMP-{label} AlgoStateLabel")
    if not section(t.spec, f"5. CMP-{shell} AlgoBuilderShell"):
        bad.append(f"§5 is not CMP-{shell} AlgoBuilderShell")
    if "Atom" not in bullet(section(t.hand, "C.2 A-2"), "Tier"):
        bad.append("A-2 Tier is not Atom")
    tier = rf"cmp {label}\s+(?:algostatelabel\s+)?\(?(?:is\s+)?(?:an?\s+)?(?:molecule|organism)"
    bad += [f"CMP-{label} is given a second tier" for _ in re.finditer(tier, norm_text(body))]
    return one("G-ONE-ENTRY", bad)


def g_resume(t: Texts) -> list[str]:
    """BQ-1 / SC-8: a halted run's next action is "Restart with remaining…", never "Resume"."""
    bad: list[str] = []
    s33 = section(t.spec, "3.3 Variant `halted`")
    if "Restart with remaining" not in s33 or 'never "Resume"' not in s33:
        bad.append("§3.3 does not read Restart with remaining, never Resume")
    for u in [x for text in swept(t) for x in units(text)]:
        n = norm_text(u)
        if "halt" not in n or "next action" not in n:
            continue  # the rule binds the halted host's next action
        if "restart with remaining" not in n:
            bad.append(f"a halted next action without Restart: {n[:50]!r}")
    bad += [
        f"claim: {c!r}"
        for c in claims(
            swept(t), r"\bresum\w*", near=r"\bhalt\w*", keep_quotes=True, unless="onresume"
        )
    ]
    return one("G-RESUME", bad)


# `halted` drawn as shipped, in any phrasing: "as released", "is final", "no longer PROPOSED", "not
# PROPOSED", "no PROPOSED badge", "unstamped" (record r2); "not unmarked" is a double negation
_DONE = r"(?:shipped|merged|final|live|released|stable|standard|done)"
SHIPPED = (
    rf"\b(?:drawn|shown|rendered|treated|marked|specified) as {_DONE}\b|\bas (?:shipped|released)\b"
    r"|\b(?:is|are|now) (?:now )?(?:shipped|merged|final|released|stable)\b"  # not "is live"
    r"|\b(?:no|without|drops?|dropped|removes?|removed|loses?|lost) (?:the |a |its |any )?"
    r"proposed (?:stamps?|mark\w*|badges?|labels?|tags?|chips?)\b"
    r"|\bproposed (?:stamp|mark|badge|label|tag) (?:is )?(?:dropped|removed|gone)\b"
    r"|\b(?:not|never|no longer|isn't|aren't) (?:\w+ ){0,3}?proposed\b"
    r"|\bga\b|\bgenerally available\b|\bgeneral availability\b"  # record r3
    r"|(?<!not )(?<!never )\bun(?:stamped|marked|flagged)\b"
)


def g_halted(t: Texts) -> list[str]:
    """BQ-9: halted is PROPOSED until the wire carries it, with its fallback."""
    bad: list[str] = []
    s33 = norm_text(section(t.spec, "3.3 Variant `halted`"))
    if "proposed until the wire carries" not in s33 or "fallback" not in s33:
        bad.append("§3.3 drops the PROPOSED mark or the fallback")
    if "PROPOSED until the wire carries" not in bullet(section(t.hand, "C.2 A-2"), "Variants"):
        bad.append("A-2 Variants drop the PROPOSED mark")
    if "`halted` PROPOSED" not in bullet(section(t.hand, "C.3 A-3"), "Props"):
        bad.append("A-3 Props drop the PROPOSED mark")
    # every other carrier of `halted` keeps the mark (record r1 M-f)
    s41 = section(t.spec, "4.1 Props")
    s92 = section(t.spec, "9.2 The frame register")
    note = next((x for x in FULL_STOP.split(s92) if "`CMP-246/halted-*`" in x), "")
    locked = table_rows(section(t.spec, "1.3 Locked inputs"))
    li = next((r for r in locked if "`halted`" in r[0]), [])
    card_f = rows_by(section(t.hand, "§F Storybook"), r"CMP-[0-9]+ \w+").get("CMP-118 card", [])
    carriers = (
        ("§4.1 status", "`halted` PROPOSED" in s41),
        ("§9.2 note", "PROPOSED stamp of §3.3" in note),
        ("§1.3 row", "PROPOSED" in " ".join(li[:1])),
        ("A-3 Storybook", "Halted (PROPOSED)" in bullet(section(t.hand, "C.3 A-3"), "Storybook")),
        ("§F card list", "Halted (PROPOSED)" in " ".join(card_f)),
    )
    bad += [f"{k} drops the PROPOSED mark" for k, ok in carriers if not ok]
    for text in swept(t):
        for u in units(text):
            for c in clauses(u):
                n = norm_text(c)
                if re.search(r"\bhalt\w*", n) and re.search(SHIPPED, n):
                    bad.append(f"claim: {n[:60]!r} draws `halted` as shipped")
    return one("G-HALTED", bad)


@functools.lru_cache(maxsize=1)
def merged_keys() -> frozenset[str]:
    text = at_base("docs/design/E09/E09-D09.md") + at_base("docs/design/E30/E30-D02.md")
    text += at_base(CITE_FILES["D03"])  # D03's merged T2 reasons (case 1's `algo.reconnecting`)
    return frozenset(re.findall(r"`((?:rbac|algo|recon|stop|sl)\.[a-z_.]+)`", text))


# a status label under any name: a state's or the status's label, word, badge, chip or pill, the
# possessive "halted state's label" included (record r2)
STATUS_LABEL = (
    rf"\b(?:{STATE_WORDS}|status|state|algo state|waiting|stopped)(?:'s)? (?:state(?:'s)? )?"
    r"(?:labels?|words?|badges?|chips?|pills?)\b|\bcmp 246\b|\balgostatelabel\b"
)
# the lock or the gate: T2, a lock or padlock, gated, disabled, a permission or `algo.manage`
LABEL_GATE = (
    r"\bt2\b|\b(?:pad)?lock(?:s|ed)?\b|\bgat(?:e|ed|es|ing)\b|\bdisabled\b|\bpermission\w*"
    r"|algo\.manage"
)


def g_t2(t: Texts) -> list[str]:
    """R-5 / BQ-9: D04 introduces no T2; a key in a T2 cell or a T2 sentence must be merged."""
    bad: list[str] = []
    for r in register(t.spec):
        cell = r.get("T2", "")
        if cell != "—":
            bad.append(f"{frame_id(r['Frame'])}: T2 {cell!r} (R-5: no T2 here)")
            bad += [
                f"`{k}` is not merged"
                for k in re.findall(r"`([a-z_]+\.[a-z_.]+)`", cell)
                if k not in merged_keys()
            ]
    for text in swept(t):
        for u in units(text):
            for c in clauses(u):
                if not live(c, r"\bt2\b"):
                    continue
                keys = re.findall(r"\b((?:rbac|algo|recon|stop|sl)\.[a-z_]+(?:\.[a-z_]+)*)", c)
                bad += [f"claim: `{k}` is not a merged key" for k in keys if k not in merged_keys()]
                if live(c, r"\bnew (?:t2 )?(?:keys?|t2|states?|gates?)\b"):
                    bad.append(f"claim: {norm_text(c)[:60]!r} adds a T2")
    # R-5 / BQ-9: a status label is never locked and never T2 (lock and T2 belong to controls);
    # a " · " list item is its own clause
    items = [x.replace(" · ", "; ") for x in swept(t)]
    bad += [
        f"claim: {c!r} puts a lock or T2 on a status label"
        for c in claims(items, LABEL_GATE, near=STATUS_LABEL)
    ]
    return one("G-T2", bad)


EXIT_ITEM = re.compile(r"^(?:(?:Close|Acknowledge) \(T1\)|`Esc`)$")


def g_exits(t: Texts) -> list[str]:
    """R-4: exits are present, T1 and never gated."""
    bad: list[str] = []
    for r in register(t.spec):
        cell = r.get("Exits", "")
        if cell == "—":
            continue
        for item in cell.split(", "):
            if not EXIT_ITEM.match(item.strip()):
                bad.append(f"{frame_id(r['Frame'])}: exit {item!r} is not T1")
    bad += [f"claim: {c!r}" for c in claims(swept(t), GATED, near=EXITS, unless=NOT_EXITS)]
    # A-1 copies D02's "finishing T2 … both exits": those are D02's run exits, not R-4's
    a1 = bullet(section(t.hand, "C.1 A-1"), "States")
    if "Cancel and Cancel and flatten, never R-4's dialog exits, which stay T1" not in a1:
        bad.append("A-1 States do not gloss D02's two exits against R-4")
    return one("G-EXITS", bad)


def g_tag(t: Texts) -> list[str]:
    """R-7 / BQ-4: every card shows the tag; a row only inside a host whose caption carries it."""
    bad: list[str] = []
    for r in register(t.spec):
        f, tag = frame_id(r["Frame"]), r.get("Tag", "")
        if f.startswith(("CMP-118/card-", "CMP-245/")):
            ok = tag == "card"
        elif f.startswith("CMP-118/row-"):
            ok = tag == "host"
        elif f.startswith("CMP-246/"):
            ok = tag == "—"
        else:
            ok = tag in ("card", "host", "—")
        if not ok:
            bad.append(f"{f}: Tag {tag!r}")
    return one("G-TAG", bad)


EMU_PHRASE = "it is never false and the tag is never hidden"


def g_emulated(t: Texts) -> list[str]:
    """BQ-4 / T Sec: `emulated` is the literal `true` on CMP-118."""
    bad: list[str] = []
    if EMU_PHRASE not in section(t.spec, "4.3 The `emulated: true`"):
        bad.append("§4.3 drops the invariant")
    a3 = section(t.hand, "C.3 A-3")
    if EMU_PHRASE not in bullet(a3, "Props"):
        bad.append("A-3 Props drop the invariant")
    if "emulated: true }" not in bullet(a3, "API sketch"):
        bad.append("A-3 API sketch does not type `emulated: true`")
    for u in [x for text in swept(t) for x in units(text)]:
        for c in clauses(u):
            typed = re.search(r"emulated\??: (?:false|boolean)", c)
            if typed and "does not compile" not in c and "fails" not in c:
                bad.append(f"claim: {norm_text(c)[:50]!r}")
    bad += [
        f"claim: {c!r}" for c in claims(swept(t), EMU_OFF, near=r"\bemulated\b", unless=EMU_ALLOWED)
    ]
    return one("G-EMULATED", bad)


TAG_KEY_LINE = 363  # D03:363, the copy key `tag.emulated`: the word and the accessible name
# a name stated for the tag: after "name", "aria-label", "named", "labelled", "announced as" or
# "read as", joined by "is", "reads", "=" or ":", in double, single or curly quotes, a code span or
# bare (record r2); the name itself is case-sensitive, so the prop `emulated` is no name
NAME_OF_TAG = re.compile(
    r"(?:accessible name|aria-label|\bnamed|\blabell?ed|tag's name|\bname|\bannounced as"
    r"|\bread (?:out )?as|\b(?:tag|it)(?=\s+(?:reads?|says|announces|speaks)\b))"  # "reads" (r3)
    r"\s*(?:\bis\b|\breads?\b|\bsays\b|\bannounces\b|\bspeaks\b|=|:)?\s*(?:\bas\b\s*)?"
    r"(?:[\"“'‘`]((?-i:Emulated)[^\"”'’`\n]*)[\"”'’`]|((?-i:Emulated)\b[^.;|\n\"“`]*))",
    re.IGNORECASE,
)


@functools.lru_cache(maxsize=1)
def tag_name() -> str:
    """The tag's accessible name as D03:363 (`tag.emulated`) states it at the base."""
    line = at_base(CITE_FILES["D03"]).split("\n")[TAG_KEY_LINE - 1]
    m = re.search(r'`tag\.emulated`.*?name "([^"]+)"', line)
    return m[1] if m else ""


def g_tagname(t: Texts) -> list[str]:
    """BQ-4 part 1 / D03:363: the tag's accessible name is never shortened. Every name stated for
    the tag equals D03's, and the three carriers (§2 part 1, A-1 A11y, A-5.1 New) state it."""
    want = tag_name()
    bad: list[str] = [] if want else ["D03:363 no longer carries `tag.emulated`'s name"]
    for text in swept(t):
        for m in NAME_OF_TAG.finditer(text):
            name = m[1] if m[1] is not None else m[2].strip()
            if name != want and not (m[1] is None and name.startswith(want)):
                bad.append(f"name {name!r} ≠ D03:363")
    a51 = next((r for r in table_rows(section(t.hand, "Table A")) if r[0] == "A-5.1"), [])
    s2 = next((ln for ln in section(t.spec, "2. The emulated").split("\n") if "1. **" in ln), "")
    carriers = (
        ("§2 part 1", s2),
        ("A-1 A11y", bullet(section(t.hand, "C.1 A-1"), "A11y")),
        ("A-5.1 New", " ".join(a51[4:])),
    )
    bad += [f"{k} does not state the tag's name" for k, c in carriers if f'"{want}"' not in c]
    return one("G-TAGNAME", bad)


_UNNEG = r"(?:(?!\b(?:no|never|not|nor|without)\b)[^.;|])"
# CMP-227 (or its visible word "(estimated)") put to work as a badge, a tag or a marker; a negation
# between the subject and the role breaks the claim (record r1 M-c, M-h)
AS_BADGE = (
    rf"(?:{ESTIMATED}|\(estimated\)(?: badges?)?){_UNNEG}{{0,40}}?\b(?:as|is|for|becomes?)\b"
    rf"{_UNNEG}{{0,20}}?\b(?:badges?|tags?|markers?|affordance)\b"
    r"|\b(?:marked|tagged|labell?ed|flagged|badged|shown|carr(?:y|ies|ied)|wears?|bears?|shows?"
    r"|displays?|gets?|uses?|reuses?|has|have)\s+(?:(?:with|by|as)\s+)?(?:the\s+|an?\s+|its\s+)?"
    rf"\W*(?:{ESTIMATED}|estimated\b)"
)


def g_afford(t: Texts) -> list[str]:
    """BQ-4: CMP-227 EstimatedBadge is never the emulation badge: read with the subject carried
    across "; ", parentheses and quotes, and quoted copy ("(estimated)") is a claim too."""
    near = r"emulat\w*|\btag\b"
    # the subject carried across "; " and " — " (record r2); a clause that negates what it says
    # of CMP-227 ("CMP-227 never the badge", §1.3) states the rule, not a claim
    bad = [
        f"claim: {c!r}"
        for c in claims(swept(t), ESTIMATED, near=near, near_live=True, carry=True, affirmed=True)
    ]
    bad += [
        f"claim: {c!r}"
        for c in claims(swept(t), AS_BADGE, near=near, near_live=True, keep_quotes=True, carry=True)
    ]
    if "CMP-227 EstimatedBadge is never the emulation badge." not in section(
        t.spec, "2. The emulated"
    ):
        bad.append("§2 drops the CMP-227 rule")
    return one("G-AFFORD", bad)


def g_untouched(t: Texts) -> list[str]:
    """BQ-2 / condition: `15` and `16` are untouched (the working tree and the branch)."""
    bad: list[str] = []
    if t.p15 != at_base(P15_REL):
        bad.append("`15` differs from the base")
    if t.p16 != at_base(P16_REL):
        bad.append("`16` differs from the base")
    bad += [f"{n} changed on the branch" for n in t.diff_names if n in (P15_REL, P16_REL)]
    return one("G-UNTOUCHED", bad)


def g_boards(t: Texts) -> list[str]:
    """BQ-18: at most ten boards, light twins ≤ ⅓, every frame on a board, every board drawn; no
    board outside §0's table; the number the text gives is the table's."""
    bd = boards(t.spec)
    bad: list[str] = []
    if len(bd) > MAX_BOARDS:
        bad.append(f"{len(bd)} boards > {MAX_BOARDS}")
    light = [b for b in bd if re.search(r"-light`", b[1])]
    if 3 * len(light) > len(bd):
        bad.append(f"{len(light)} light twins of {len(bd)} boards > a third")
    nums = [b[0] for b in bd]
    if nums != [f"{i:02d}" for i in range(1, len(bd) + 1)]:
        bad.append("boards are not numbered 01…n")
    bad += [
        f"§0 row {k!r} is not a board number" for k in malformed(t.spec, "0. Artefacts", r"\d\d")
    ]
    used = {r.get("Board", "") for r in register(t.spec)}
    bad += [f"frame on board {u} not in §0" for u in sorted(used - set(nums))]
    bad += [f"board {n} draws no §9.2 frame" for n in nums if n not in used]
    bad += [f"board {b[0]} is not PENDING" for b in bd if not b[-1].startswith("PENDING")]
    named = {b[1].strip("`") for b in bd}
    for text in swept(t):
        for m in re.finditer(r"E33-D04 / (\d+\w*) [a-z0-9-]+", text):
            if m[0] not in named:
                bad.append(f"`{m[0]}` is not a §0 board")
    for text in swept(t):
        for m in re.finditer(r"\b(\w+) (?:planned |penpot |drawn )?boards\b", norm_text(text)):
            n = NUMBER_WORDS.get(m[1]) if not m[1].isdigit() else int(m[1])
            if n is not None and n not in (len(bd), MAX_BOARDS) and n > 1:
                bad.append(f"the text says {m[0]!r}; §0 has {len(bd)}")
    return one("G-BOARDS", bad)


def g_budget(t: Texts) -> list[str]:
    n = t.spec.count("\n") + (0 if t.spec.endswith("\n") else 1)
    return one(
        "G-BUDGET", [f"the spec has {n} lines > {SPEC_LINE_BUDGET}"] if n > SPEC_LINE_BUDGET else []
    )


def drift_ok_justified(k: str, d: dict[str, str], hand: str) -> bool:
    """A justified row carries a §C "Deliberate exception (DR-n):" line, or a cite it confirms."""
    rep = d.get("Replacement", "")
    if "Deliberate exception" in rep:
        return f"Deliberate exception ({k}):" in section(hand, "§C Copy-ready")
    return "confirmed" in rep and re.search(r"`[\w./-]+`:\d+|\b[A-Z][\w-]*:\d+", rep) is not None


def drift_problems(k: str, d: dict[str, str], hand: str) -> list[str]:
    """Why ledger row `k` is not resolved (empty when it is)."""
    bad: list[str] = []
    if d.get("Class") not in ("a", "b", "c", "d"):
        bad.append(f"{k}: class {d.get('Class')!r}")
    for col in ("Source", "Bound", "Replacement", "Owner"):
        if nullish(d.get(col, "")):
            bad.append(f"{k}: no {col}")
    rep = d.get("Replacement", "")
    if not TOKEN_NAME.search(rep) or live(rep, UNRESOLVED):
        bad.append(f"{k}: the Replacement names no exact token")
    verdict = d.get("Verdict")
    if verdict not in ("corrected", "justified"):
        bad.append(f"{k}: verdict {verdict!r} (unresolved)")
    elif verdict == "justified" and not drift_ok_justified(k, d, hand):
        bad.append(f"{k}: justified without a §C exception line or a confirmed cite")
    return bad


def g_drift(t: Texts) -> list[str]:
    """BQ-17: every drift row has its class, an exact replacement token, an owner and a verdict;
    a justified row has its exception line or its confirmed cite; no sentence leaves a row open."""
    bad: list[str] = []
    for k, d in drift_rows(t.hand).items():
        bad += drift_problems(k, d, t.hand)
    if not drift_rows(t.hand):
        bad.append("hand-off §E has no rows")
    bad += [f"{k}: not a ledger row id" for k in malformed(t.hand, "§E Drift ledger", r"DR-\d+")]
    bad += [
        f"claim: {c!r}"
        for c in claims(swept(t), UNRESOLVED, near=r"\bdr \d+\b|\bdrift (?:row|ledger)\b")
    ]
    return one("G-DRIFT", bad)


def g_drift_scope(t: Texts) -> list[str]:
    """BQ-16: every bound name outside class (a) has a ledger row."""
    covered = {
        n for d in drift_rows(t.hand).values() for n in BOUND_NAME.findall(d.get("Bound", ""))
    }
    bad = [f"`{n}` (class b or d) has no §E row" for n in sorted(out_of_class_a() - covered)]
    return one("G-DRIFT-SCOPE", bad)


def pin_claims(clause: str) -> list[str]:
    """The pin errors of one sentence: an unknown sha; `#PR (sha)` pairs that disagree; a role
    word ("text" / "boards") or a document id next to a sha that is not that pin's."""
    bad: list[str] = []
    last = 0
    for m in re.finditer(r"`([0-9a-f]{7,40})`", clause):
        sha, start, last = m[1], last, m.end()
        pin = next((k for k in PINS if sha.startswith(k) or k.startswith(sha)), None)
        if pin is None:
            if not (sha.startswith(BASE) or BASE.startswith(sha)):
                bad.append(f"`{sha}` is neither a pin nor the base")
            continue
        pr, path = PINS[pin]
        doc, role = PIN_DOC[pin], ("boards" if path.endswith("img/") else "text")
        before = norm_text(clause[start : m.start()])  # since the previous sha
        before = re.sub(r"^[^a-z(]*\((?:text|boards?)\)", " ", before)
        after = norm_text(clause[m.end() :])[:14]
        prm = re.search(r"#(\d{3,5})\W{0,4}$", clause[: m.start()])
        if prm and f"#{prm[1]}" != pr:
            bad.append(f"#{prm[1]} is pinned at `{sha}`, which is {pr}")
        paren = re.match(r"\W*\((text|boards?)\)", after)
        words = [paren[1]] if paren else re.findall(r"\b(text|boards?|pngs?)\b", before)
        if words:
            said = "boards" if re.search(r"boards?|pngs?", words[-1]) else "text"
            if said != role:
                bad.append(f"`{sha}` is the {doc} {role} pin, read as {said}")
        docs = re.findall(r"\b(e05 d02|e33 d02|e33 d03|d02|d03|h03|fo)\b", before)
        if docs and docs[-1] not in PIN_DOCS_OK[doc]:
            bad.append(f"`{sha}` is the {doc} pin, cited for {docs[-1].upper()}")
    return bad


def g_pin(t: Texts) -> list[str]:
    """Condition: merged texts cited at their merge shas — every sha named is a pin or the base;
    a pin's PR, its role (text / boards) and its document agree wherever it is named."""
    bad: list[str] = []
    start = next((ln for ln in t.spec.split("\n") if ln.startswith("**Start.**")), "")
    inputs = next((ln for ln in t.spec.split("\n") if ln.startswith("**Inputs pinned.**")), "")
    for sha, (pr, _path) in PINS.items():
        if not re.search(rf"{re.escape(pr)}\W{{1,4}}`{sha}`", start + " " + inputs):
            bad.append(f"spec Start / Inputs do not pin {pr} at `{sha}`")
        if f"`{sha}`" not in t.hand:
            bad.append(f"hand-off does not cite `{sha}`")
    if f"Base `origin/main` `{BASE}`" not in inputs or f"Base `{BASE}`" not in t.hand:
        bad.append(f"the base `{BASE}` is not named")
    for name, text in zip(("spec", "hand-off"), swept(t), strict=True):
        for u in units(text):
            for c in clauses(u):
                bad += [f"{name}: {x}" for x in pin_claims(c)]
    return one("G-PIN", bad)


@functools.lru_cache(maxsize=1)
def pin_facts() -> tuple[str, ...]:
    bad: list[str] = []
    for sha, (pr, path) in PINS.items():
        if not git_ok("merge-base", "--is-ancestor", sha, BASE):
            bad.append(f"`{sha}` is not an ancestor of {BASE}")
        if pr not in git_out("log", "-1", "--format=%s", sha):
            bad.append(f"`{sha}` is not {pr}")
        if not any(
            n.startswith(path) for n in git_out("show", "--name-only", "--format=", sha).split()
        ):
            bad.append(f"`{sha}` does not touch {path}")
    return tuple(bad)


LANE_ID = re.compile(r"\bLANE-[A-Za-z0-9-]+")


def g_ruled(t: Texts) -> list[str]:
    """Condition: "RULED" cites comment 6397030902 or 6401561066; the twenty rows are there."""
    bad: list[str] = []
    head = next((ln for ln in t.spec.split("\n") if ln.startswith("## The twenty questions")), "")
    if f"RULED (orchestrator, comment {RULING_ID}, on the BQ list {BQ_LIST_ID})" not in head:
        bad.append("the RULED heading does not cite the ruling comment")
    if f"comment {RULING_ID}" not in t.hand:
        bad.append("the hand-off does not cite the ruling comment")
    for text in (t.spec, t.hand):
        for cid in re.findall(r"comment (\d{9,})", text):
            if cid not in (RULING_ID, RULING_1442_ID, BQ_LIST_ID):
                bad.append(f"comment {cid} is not the ruling")
        # "RULED" cites the comment, never a lane thread (record r1)
        bad += [f"{m[0]} is a lane thread, not a #988 comment" for m in LANE_ID.finditer(text)]
        for m in re.finditer(r"\bRULED by ([^.;:]{0,80})", text):
            if RULING_ID not in m[1] and RULING_1442_ID not in m[1]:
                bad.append(f"RULED by {m[1][:40]!r} does not cite a ruling comment")
    bq = list(rows_by(section(t.spec, "The twenty questions"), r"BQ-\d+"))
    if bq != [f"BQ-{i}" for i in range(1, 21)]:
        bad.append("the BQ table is not BQ-1…BQ-20")
    return one("G-RULED", bad)


def g_ac(t: Texts) -> list[str]:
    """BQ-2: AC1 and DoD rows 1–2 are met as copy-ready A-rows, owner approval pending."""
    trace = table_rows(section(t.spec, "Acceptance-criteria trace"))
    bad: list[str] = []
    for key in ("AC1 —", "DoD 1 "):
        r = next((x for x in trace if x[0].startswith(key)), None)
        if r is None or "met as copy-ready A-rows" not in r[-1] or OWNER_MARK not in r[-1]:
            bad.append(f"trace row {key.strip(' —')} is not met as copy-ready A-rows")
    dod = [ln for ln in section(t.spec, "14.1 DoD").split("\n") if ln.startswith("- [")]
    for ln in dod[:2]:
        if "met as" not in ln or OWNER_MARK not in ln:
            bad.append(f"§14.1 {ln[6:30]!r} is not met as copy-ready")
    return one("G-AC", bad)


def g_crow(t: Texts) -> list[str]:
    """BQ-11: D04-C3 records the departure from the ticket's cross-fade."""
    rows = rows_by(section(t.spec, "13.1 Contradictions"), r"D04-C\d+")
    bad: list[str] = []
    want = [f"D04-C{i}" for i in range(1, len(rows) + 2)][: len(rows)]
    if list(rows) != want:
        bad.append("the C-rows are not D04-C1… in order")
    c3 = rows.get("D04-C3")
    if c3 is None:
        bad.append("D04-C3 is missing")
    else:
        row = " | ".join(c3)
        if "MOTION:ticket.crossfade-ms" not in row or "instant" not in row or OWNER_MARK not in row:
            bad.append("D04-C3 does not record the cross-fade departure")
    return one("G-CROW", bad)


def g_owner(t: Texts) -> list[str]:
    """BQ-2 / BQ-11 / BQ-17 are owner-level: marked wherever they depart."""
    bad: list[str] = []
    bq = rows_by(section(t.spec, "The twenty questions"), r"BQ-\d+")
    bad += [
        f"{k} lacks the owner mark" for k in OWNER_BQS if k in bq and OWNER_MARK not in bq[k][-1]
    ]
    if OWNER_MARK not in next((ln for ln in t.spec.split("\n") if ln.startswith("### 7.4")), ""):
        bad.append("§7.4 heading lacks the owner mark")
    if OWNER_MARK not in next((ln for ln in t.hand.split("\n") if ln.startswith("## §E")), ""):
        bad.append("§E heading lacks the owner mark")
    crow = rows_by(section(t.spec, "13.1 Contradictions"), r"D04-C\d+")
    bad += [
        f"{k} lacks the owner mark"
        for k in ("D04-C7", "D04-C8")
        if k in crow and OWNER_MARK not in crow[k][2]
    ]
    return one("G-OWNER", bad)


def g_stories(t: Texts) -> list[str]:
    """BQ-19: the shell's stories are D02's verbatim; the lists match the copy-ready entries."""
    d02 = storybook_items(at_base(CITE_FILES["D02"]).split("\n")[471])
    rows = {r[0]: r for r in table_rows(section(t.hand, "§F Storybook"))}
    bad: list[str] = []
    shell = story_list(rows.get("CMP-245 AlgoBuilderShell", ["", ""])[1])
    if shell != d02:
        bad.append(f"§F shell list ≠ D02:472 ({len(shell)} vs {len(d02)})")
    if storybook_items(bullet(section(t.hand, "C.1 A-1"), "Storybook")) != d02:
        bad.append("A-1 Storybook ≠ D02:472")
    card = story_list(rows.get("CMP-118 card", ["", ""])[1])
    a3 = storybook_items(bullet(section(t.hand, "C.3 A-3"), "Storybook"))
    if [s.replace(" ", "") for s in card] != [s.replace(" ", "") for s in a3]:
        bad.append("§F card list ≠ A-3 Storybook")
    label = story_list(rows.get("CMP-246 AlgoStateLabel", ["", ""])[1])
    if label != storybook_items(bullet(section(t.hand, "C.2 A-2"), "Storybook")):
        bad.append("§F label list ≠ A-2 Storybook")
    if "Paused/RateLimit" not in label:  # §0's `CMP-246/paused-rate-limit` (D03:213)
        bad.append("§F label list has no rate-limit pause story")
    return one("G-STORIES", bad)


def g_handoff(t: Texts) -> list[str]:
    """BQ-3: one hand-off file, sections §A–§F in order."""
    heads = re.findall(r"^## (§[A-Z]) ", t.hand, MULTI)
    want = ["§A", "§B", "§C", "§D", "§E", "§F"]
    return one("G-HANDOFF", [] if heads == want else [f"hand-off sections {heads} ≠ {want}"])


STATUS8 = {
    "running",
    "paused",
    "completing",
    "completed",
    "cancelled",
    "degraded",
    "halted",
    "failed",
}
ALGO5 = {"twap", "iceberg", "chase", "scaled", "oco"}


def g_cmp118(t: Texts) -> list[str]:
    """BQ-6: CMP-118 carries `oco` and the eight-value status set (A-3 and §4.1)."""
    a3 = section(t.hand, "C.3 A-3")
    s41 = section(t.spec, "4.1 Props")
    bad: list[str] = []
    for name, text in (
        ("A-3 Props", bullet(a3, "Props")),
        ("A-3 API", bullet(a3, "API sketch")),
        ("§4.1", s41),
    ):
        if union_of(text, "algoType") != ALGO5:
            bad.append(f"{name} algoType ≠ {sorted(ALGO5)}")
        if union_of(text, "status") != STATUS8:
            bad.append(f"{name} status set ≠ the eight values")
    return one("G-CMP118", bad)


def g_a11y(t: Texts) -> list[str]:
    """BQ-20: the shell's A11y is D02:468 verbatim (D04 appends only the tag's name)."""
    d02 = at_base(CITE_FILES["D02"]).split("\n")[467].rstrip(".")
    a1 = bullet(section(t.hand, "C.1 A-1"), "A11y")
    bad: list[str] = []
    if not a1.startswith(d02):
        bad.append("A-1 A11y is not D02:468 verbatim")
    if "A11y is D02:468 verbatim" not in section(t.spec, "5. CMP-245"):
        bad.append("§5 does not bind D02:468")
    return one("G-A11Y", bad)


def css_names(text: str) -> list[str]:
    """`--cv-color-x-y` / `--color-x-y` CSS variables, as dotted candidate names."""
    return [m[1] for m in re.finditer(r"--(?:cv-)?([a-z][a-z0-9-]*)", text.lower())]


def token_like(text: str) -> list[str]:
    """Every token-shaped name in `text`, case-folded: backticked or bare dotted names of a token
    family (the shipped families and the ones no token has: `shadow`, `z`, `font`…)."""
    found = [m.lower() for m in TOKENISH.findall(_HIDDEN.sub(" ", text))]
    return sorted(set(found))


def g_token(t: Texts) -> list[str]:
    """Condition: no bound token name that neither exists nor has a PROPOSED A-row; every
    token-shaped name (backticked or bare, any case, or a CSS variable) exists, or is recorded as
    missing (a §E row or a §D CR)."""
    known = all_token_names()
    css_known = {n.replace(".", "-") for n in known}
    table_a = {ln for ln in section(t.hand, "Table A").split("\n") if ln.startswith("|")}
    bad: list[str] = []
    binding: list[tuple[str, str]] = []
    for r in register(t.spec):
        binding += [(frame_id(r["Frame"]), r.get("Fill", "") + " " + r.get("Glyph", ""))]
    for fam in families(t.spec):
        cols = ("Fill", "GlyphColour", "Word")
        binding += [(f"§3.1 {fam['Family']}", " ".join(fam.get(c, "") for c in cols))]
    for row in table_rows(section(t.spec, "10. Contrast")):
        binding += [(f"§10 {row[0]}", " ".join(row[1:3]))]
    for a in ("C.1 A-1", "C.2 A-2", "C.3 A-3"):
        binding += [(a, bullet(section(t.hand, a), "Tokens"))]
    for where, cell in binding:
        for n in TOKEN_NAME.findall(cell):
            if not all(x in known for x in expand(n, known)):
                bad.append(f"{where}: `{n}` is bound but not shipped")
    recorded = {
        n for d in drift_rows(t.hand).values() for n in TOKEN_NAME.findall(d.get("Bound", ""))
    }
    recorded |= set(TOKEN_NAME.findall(section(t.hand, "§D Change requests")))
    hand = "\n".join(  # Table A's Old cells are `15` verbatim at the base, not this spec's names
        " | ".join(c for j, c in enumerate(split_row(ln)) if j != 3) if ln in table_a else ln
        for ln in t.hand.split("\n")
    )
    for name, text in (("spec", t.spec), ("hand-off", hand)):
        for n in token_like(text):
            if all(x in known for x in expand(n, known)) or n in recorded:
                continue
            bad.append(f"{name}: `{n}` is neither shipped nor recorded")
        for n in css_names(text):
            if n.split("-")[0] in TOKEN_FAMILIES and n not in css_known:
                bad.append(f"{name}: `--{n}` is not a shipped token's variable")
    return one("G-TOKEN", sorted(set(bad)))


def g_contrast(t: Texts) -> list[str]:
    """§10's rows are the tool's pairs, and each row's own fg / bg meets its role's bar in dark,
    light and high contrast (the spec's cells are measured, not the tool's copy)."""
    bars = threshold()
    bad: list[str] = []
    rows = {r[0].strip("`"): r for r in table_rows(section(t.spec, "10. Contrast"))}
    if set(rows) != set(PAIRS):
        bad.append(f"§10 rows {sorted(set(rows) ^ set(PAIRS))} differ from the tool's pairs")
    for key, r in rows.items():
        want = PAIRS.get(key)
        fg, bg, role = r[1].strip("`"), r[2].strip("`"), r[3] if len(r) > 3 else ""
        if want and (fg, bg, role) != want:
            bad.append(f"§10 {key}: fg / bg / role differ from the tool's")
        if role not in bars:
            bad.append(f"§10 {key}: role {role!r}")
            continue
        for theme in THEMES:
            tok = load_theme(theme)
            if fg not in tok or bg not in tok:
                bad.append(f"§10 {key}: `{fg}` / `{bg}` is not a shipped colour")
                break
            ratio = contrast(hex_of(tok, fg), hex_of(tok, bg))
            if ratio + 1e-9 < bars[role]:
                bad.append(f"{key} {theme} {ratio:.2f} < {bars[role]:g}")
    return one("G-CONTRAST", bad)


def g_cvd_port(t: Texts) -> list[str]:
    """The ported Brettel constants equal `cvd_simulate.py` at the base."""
    src = at_base(CVD_REL)
    nums = [
        float(x)
        for x in re.findall(
            r"-?\d+\.\d+(?:e-?\d+)?", src[src.index("RGB_TO_LMS = (") : src.index("def matvec")]
        )
    ]
    mine = [*flat3(RGB_TO_LMS), *flat3(LMS_TO_RGB)]
    for sim in SIMS:
        mine += [x for x in PROJECTIONS[sim]]
    port = [x for x in mine if x not in (0.0, 1.0)]
    src_nums = [x for x in nums if x not in (0.0, 1.0)]
    return one(
        "G-CVD-PORT",
        [] if port == src_nums else ["the port's constants differ from cvd_simulate.py"],
    )


# the 14:42Z decisions are ruled in comment 6401561066 and cite it as RULED_1442
PENDING_WORDS = r"\bpending\b|\bawait\w*|\brequested\b|\bmay instead\b|\bopen\b"


def g_q3(t: Texts) -> list[str]:
    """L-9 / D04-Q3 (comment 6401561066): `cancelled` takes `slash` (CR-G4, PROPOSED); Q3 is
    marked "RULED (6401561066)"."""
    q3 = bullet(section(t.spec, "13.3 Open questions"), "D04-Q3")
    bad: list[str] = []
    if RULED_1442 not in q3:
        bad.append(f"D04-Q3 is not {RULED_1442}")
    if re.search(PENDING_WORDS, norm_text(q3)):
        bad.append("D04-Q3 still reads as pending")
    # the family's glyph is G-ENCODE's; a missing CR-G4 row is G-CR's
    g4 = rows_by(section(t.hand, "§D Change requests"), r"CR-[A-Z0-9]+").get("CR-G4", [])
    if g4 and ("`slash`" not in g4[1] or "PROPOSED" not in g4[-1] or RULED_1442 not in g4[-1]):
        bad.append(f"CR-G4 is not the PROPOSED `slash` with D04-Q3 {RULED_1442}")
    if g4 and "open" in g4[-1]:
        bad.append("CR-G4 still reads D04-Q3 open")
    return one("G-Q3", bad)


def g_c15(t: Texts) -> list[str]:
    """D04-C15 (comment 6401561066): A-7.2 binds `danger.strong` for the bar fill; CR-T1 carries
    the measurement to E05's tokens owner, PROPOSED, with the measured values anchored."""
    bad: list[str] = []
    a72 = next((r for r in table_rows(section(t.hand, "Table A")) if r[0] == "A-7.2"), [])
    new = a72[4] if len(a72) > 4 else ""
    fills = new.split("; label")[0]
    if "`color.status.danger.strong`" not in fills or "`color.status.danger.default`" in fills:
        bad.append("A-7.2 New does not bind `color.status.danger.strong` for the bar fill")
    t1 = rows_by(section(t.hand, "§D Change requests"), r"CR-[A-Z0-9]+").get("CR-T1", [])
    if len(t1) < 6:
        bad.append("CR-T1 missing")
    else:
        why = t1[3]
        keys = ("bar-danger-default.dark", "bar.non-text", "bar-danger.dark")
        if any(f"<!--=CONTRAST:{k}-->" not in why for k in keys):
            bad.append("CR-T1 lacks the measured values")
        if "not a fill colour on dark surfaces" not in t1[2] or "E05-T01" not in t1[4]:
            bad.append("CR-T1 is not the danger.default statement to E05's tokens owner")
        if t1[5] != "PROPOSED":
            bad.append("CR-T1 is not PROPOSED")
    c15 = rows_by(section(t.spec, "13.1 Contradictions"), r"D04-C\d+").get("D04-C15", [])
    if "CR-T1" not in " ".join(c15) or RULED_1442 not in " ".join(c15):
        bad.append("D04-C15 does not cite the ruling and CR-T1")
    return one("G-C15", bad)


def g_dr14(t: Texts) -> list[str]:
    """DR-14 (comment 6401561066): class (a) CONFIRMED by the `16`:178 cite; FO H21 stays the
    owner's."""
    d = drift_rows(t.hand).get("DR-14", {})
    rep = d.get("Replacement", "")
    bad: list[str] = []
    if "`16`:178" not in rep:
        return []  # no confirmed cite at all: G-DRIFT's FAIL, not a second one
    if d.get("Class") != "a":
        bad.append("DR-14 is not class (a)")
    if "CONFIRMED" not in rep or RULED_1442 not in rep or "`16`:178" not in rep:
        bad.append("DR-14 is not marked CONFIRMED by the `16`:178 cite")
    if "H21 stays with the owner" not in rep:
        bad.append("DR-14 decides FO H21")
    return one("G-DR14", bad)


def g_mutlist(t: Texts) -> list[str]:
    listed = mutation_ids(t.spec)
    mine = [m.mid for m in MUTATIONS]
    return one(
        "G-MUTLIST",
        [] if listed == mine else [f"§9.3 lists {len(listed)}; the tool has {len(mine)}"],
    )


GATES: tuple[Callable[[Texts], list[str]], ...] = (
    g_triad, g_encode, g_word_leads, g_twin, g_twin16, g_reduce_instant, g_instant, g_nofade,
    g_banner, g_step, g_cadence, g_easing, g_motion_tokens, g_loop, g_focused, g_countdown,
    g_tween, g_never, g_dialog, g_q1, g_tier, g_kind, g_reduce_source, g_cr, g_one_entry, g_resume,
    g_halted, g_t2, g_exits, g_tag, g_tagname, g_emulated, g_afford, g_untouched, g_boards,
    g_budget,
    g_drift, g_drift_scope, g_pin, g_ruled, g_ac, g_crow, g_owner, g_stories, g_handoff,
    g_cmp118, g_a11y, g_token, g_contrast, g_cvd_port, g_q3, g_c15, g_dr14, g_mutlist,
)  # fmt: skip


def audit(
    t: Texts, fetch: Fetch, spec_keys: set[str], hand_keys: set[str]
) -> tuple[list[str], list[str], int]:
    fails: list[str] = []
    fails += anchor_gates("spec", t.spec, t.values, spec_keys)
    fails += anchor_gates("hand-off", t.hand, t.values, hand_keys)
    cf, warns, n = cite_gates({"spec": t.spec, "hand-off": t.hand}, fetch)
    fails += cf
    fails += one("G-PIN", list(pin_facts())) if pin_facts() else []
    for gate in GATES:
        fails += gate(t)
    merged: dict[str, list[str]] = {}
    for f in fails:
        merged.setdefault(f.split("]")[0] + "]", []).append(f.split("] ", 1)[1])
    return [f"{k} {'; '.join(v)}" for k, v in merged.items()], warns, n


# ---------------------------------------------------------------------------- mutations

Edit = Callable[[str, Values], str]


def set_cell(line: str, idx: int, fn: Callable[[str], str]) -> str:
    cells = split_row(line)
    cells[idx] = fn(cells[idx])
    return "| " + " | ".join(cells) + " |"


def row_edit(head: str, first: str, col: int, fn: Callable[[str], str]) -> Edit:
    """A cell of the row whose first cell is `first`, inside the section `head`."""

    def run(text: str, _v: Values) -> str:
        block = section(text, head)
        lines = block.split("\n")
        for i, ln in enumerate(lines):
            if ln.startswith("|") and split_row(ln)[0] == first:
                lines[i] = set_cell(ln, col, fn)
                return text.replace(block, "\n".join(lines), 1)
        return text

    return run


def mo(k: str, col: str, fn: Callable[[str], str]) -> Edit:
    return row_edit("7.2 The motion table", k, MO_COLS.index(col), fn)


def reg(frame: str, col: str, fn: Callable[[str], str]) -> Edit:
    return row_edit("9.2 The frame register", f"`{frame}`", REG_COLS.index(col), fn)


def sub_in(head: str, old: str, new: str) -> Edit:
    """Replace the first `old` inside the section `head`."""

    def run(text: str, _v: Values) -> str:
        block = section(text, head)
        return text.replace(block, block.replace(old, new, 1), 1) if old in block else text

    return run


def drop_row(head: str, first: str) -> Edit:
    def run(text: str, _v: Values) -> str:
        block = section(text, head)
        kept = [
            ln for ln in block.split("\n") if not (ln.startswith("|") and split_row(ln)[0] == first)
        ]
        return text.replace(block, "\n".join(kept), 1)

    return run


def anchored(key: str) -> Callable[[Values], str]:
    return lambda v: f"{v[key]}<!--={key}-->"


def to(value: str) -> Callable[[str], str]:
    return lambda _c: value


def appended(extra: str) -> Callable[[str], str]:
    return lambda c: c + extra


def line_edit(prefix: str, old: str, new: str) -> Edit:
    def run(text: str, _v: Values) -> str:
        out = text.split("\n")
        for i, ln in enumerate(out):
            if ln.startswith(prefix) and old in ln:
                out[i] = ln.replace(old, new, 1)
                break
        return "\n".join(out)

    return run


def with_values(build: Callable[[Values], Edit]) -> Edit:
    return lambda text, v: build(v)(text, v)


def add_board(text: str, _v: Values) -> str:
    rows = [ln for ln in section(text, "0. Artefacts").split("\n") if ln.startswith("| 10 ")]
    if not rows:
        return text
    extra = (
        rows[0].replace("| 10 ", "| 11 ", 1).replace("/ 10 builder-shell-light", "/ 11 extra-light")
    )
    return text.replace(rows[0], rows[0] + "\n" + extra, 1)


def overrun(text: str, _v: Values) -> str:
    n = text.count("\n")
    return text + "filler\n" * (SPEC_LINE_BUDGET - n + 5)


def prose_at(head: str, sentence: str) -> Edit:
    """Append a paragraph `sentence` at the end of the section `head`."""

    def run(text: str, _v: Values) -> str:
        block = section(text, head)
        return text.replace(block, block.rstrip("\n") + "\n\n" + sentence + "\n", 1)

    return run


def table_at(head: str, row: str) -> Edit:
    """Append a two-row table (a header, its rule and `row`) at the end of the section `head`."""
    n = len(split_row(row))
    hdr = "| " + " | ".join(["a"] * n) + " |\n| " + " | ".join(["---"] * n) + " |\n"
    return prose_at(head, hdr + row)


def add_row_after(head: str, first: str, row: str) -> Edit:
    def run(text: str, _v: Values) -> str:
        block = section(text, head)
        lines = block.split("\n")
        for i, ln in enumerate(lines):
            if ln.startswith("|") and split_row(ln)[0] == first:
                lines.insert(i + 1, row)
                return text.replace(block, "\n".join(lines), 1)
        return text

    return run


def crlf(text: str) -> str:
    return text.replace("\n", "\r\n")


def nudge_projection() -> Callable[[], None]:
    """Move one ported Brettel constant by 1e-4 (G-CVD-PORT); returns the undo."""
    sim = SIMS[0]
    old = PROJECTIONS[sim]
    PROJECTIONS[sim] = (old[0], old[1] * 1.0001, *old[2:])
    return lambda: PROJECTIONS.__setitem__(sim, old)


@dataclass(frozen=True)
class Mutation:
    mid: str
    gate: str  # the gate tag that must trip
    ruled: str  # the ruled sentence it trips
    spec: Edit | None = None
    hand: Edit | None = None
    p15: Callable[[str], str] | None = None
    patch: Callable[[], Callable[[], None]] | None = None  # moves tool state; returns the undo


MUTATIONS: tuple[Mutation, ...] = (
    Mutation(
        "M-1", "G-TRIAD", "BQ-8", spec=reg("CMP-246/halted-risk-control · dark", "Glyph", to(""))
    ),
    Mutation("M-2", "G-TRIAD", "BQ-8", spec=reg("CMP-246/paused-by-you · light", "Word", to(""))),
    Mutation("M-3", "G-TRIAD", "BQ-8", spec=reg("CMP-246/completed · dark", "Fill", to(""))),
    Mutation(
        "M-4",
        "G-WORD-LEADS",
        "BQ-8",
        spec=sub_in(
            "3.6 A11y contract",
            "The word leads the accessible name",
            "The glyph leads the accessible name",
        ),
    ),
    Mutation("M-5", "G-TWIN", "BQ-15", spec=mo("Mo-3", "Twin", to(""))),
    Mutation(
        "M-6",
        "G-INSTANT",
        "BQ-11",
        spec=with_values(
            lambda v: mo(
                "Mo-6", "Tokens", appended(f", {anchored('MOTION:ticket.crossfade-ms')(v)} ms")
            )
        ),
    ),
    Mutation("M-7", "G-MOTION-TOKENS", "BQ-14", spec=mo("Mo-7", "Tokens", to("`motion.shimmer`"))),
    Mutation("M-8", "G-EASING", "BQ-1", spec=mo("Mo-2", "Safe", appended("; linear"))),
    Mutation("M-9", "G-STEP", "BQ-10", spec=mo("Mo-1", "Safe", to("over `motion.duration.fast`"))),
    Mutation(
        "M-10",
        "G-CADENCE",
        "BQ-10 rule 1",
        spec=lambda text, v: mo(
            "Mo-2",
            "Safe",
            lambda c: c.replace("`motion.duration.normal`", "`motion.duration.slow`"),
        )(mo("Mo-2", "Trigger", to("a sample"))(text, v), v),
    ),
    Mutation("M-11", "G-COUNTDOWN", "BQ-13", spec=mo("Mo-4", "Focus", to('`aria-live="polite"`'))),
    Mutation(
        "M-12",
        "G-BANNER",
        "BQ-12",
        spec=mo("Mo-5", "Safe", appended("; enters over `motion.duration.fast`")),
    ),
    Mutation(
        "M-13",
        "G-NOFADE",
        "BQ-11",
        spec=mo("Mo-6", "Safe", appended("; a cross-fade between the two states")),
    ),
    Mutation(
        "M-14",
        "G-REDUCE-INSTANT",
        "BQ-15",
        spec=mo("Mo-2", "Twin", to("prefers-reduced-motion: a low-amplitude cross-fade")),
    ),
    Mutation(
        "M-15",
        "G-AFFORD",
        "BQ-4",
        spec=sub_in(
            "2. The emulated",
            "Never a tooltip, never an icon alone.",
            "CMP-227 EstimatedBadge as the Emulated tag.",
        ),
    ),
    Mutation(
        "M-16",
        "G-EMULATED",
        "BQ-4",
        spec=sub_in("4.3 The `emulated: true`", EMU_PHRASE, "a consumer may hide the tag"),
        hand=sub_in("C.3 A-3", EMU_PHRASE, "a consumer may hide the tag"),
    ),
    Mutation(
        "M-17", "G-TAG", "BQ-4", spec=reg("CMP-118/row-host-running · dark", "Tag", to("none"))
    ),
    Mutation(
        "M-18",
        "G-RESUME",
        "BQ-1",
        spec=sub_in("3.3 Variant `halted`", "Restart with remaining 0.80 BTC…", "Resume"),
    ),
    Mutation(
        "M-19",
        "G-HALTED",
        "BQ-9",
        spec=sub_in("3.3 Variant `halted`", "PROPOSED until the wire carries ", ""),
    ),
    Mutation(
        "M-20",
        "G-TOKEN",
        "condition",
        spec=reg("CMP-118/card-twap · dark", "Fill", appended(" on `color.track`")),
    ),
    Mutation(
        "M-21",
        "G-T2",
        "BQ-9",
        spec=reg("CMP-118/row-degraded-case-1 · dark", "T2", to("lock · `algo.reconnecting`")),
    ),
    Mutation(
        "M-22",
        "G-EXITS",
        "condition",
        spec=reg("CMP-245/anatomy · dark", "Exits", to("Close (T2), `Esc`")),
    ),
    Mutation("M-23", "G-UNTOUCHED", "BQ-2", p15=lambda text: text + " "),
    Mutation("M-24", "G-BOARDS", "BQ-18", spec=add_board),
    Mutation("M-25", "G-BUDGET", "BQ-1", spec=overrun),
    Mutation(
        "M-26",
        "G-DRIFT",
        "BQ-17",
        hand=row_edit("§E Drift ledger", "DR-1", DR_COLS.index("Verdict"), to("")),
    ),
    Mutation(
        "M-27",
        "G-DRIFT",
        "BQ-17",
        hand=row_edit("§E Drift ledger", "DR-3", DR_COLS.index("Replacement"), to("")),
    ),
    Mutation(
        "M-28",
        "G-ANCHOR",
        "condition",
        spec=with_values(
            lambda v: sub_in("10. Contrast", anchored("CONTRAST:word-danger.dark")(v), "9.99:1")
        ),
    ),
    Mutation("M-29", "G-PIN", "condition", spec=line_edit("**Start.**", " (`4f9d15b6`)", "")),
    Mutation(
        "M-30",
        "G-RULED",
        "condition",
        spec=line_edit("## The twenty questions", f"comment {RULING_ID}, ", ""),
    ),
    Mutation("M-31", "G-AC", "BQ-2", spec=line_edit("| AC1 —", "met as copy-ready A-rows; ", "")),
    Mutation("M-32", "G-CROW", "BQ-11", spec=drop_row("13.1 Contradictions", "D04-C3")),
    Mutation(
        "M-33",
        "G-ENCODE",
        "BQ-8",
        spec=row_edit("3.1 Families", "cancelled", 2, to("✗ `x` (PROPOSED, CR-G1)")),
    ),
    Mutation(
        "M-34",
        "G-TWIN16",
        "BQ-2, BQ-15",
        hand=line_edit("| Bars on single-run surfaces", "; `prefers-reduced-motion`: a step", ""),
    ),
    Mutation(
        "M-35",
        "G-STORIES",
        "BQ-19",
        hand=line_edit(
            "| CMP-245 AlgoBuilderShell", "ReducedMotion (now", "ReducedMotion · Extra (now"
        ),
    ),
    Mutation(
        "M-36",
        "G-FOCUSED",
        "BQ-14",
        spec=mo("Mo-3", "Element", lambda c: c.replace("the focused row", "every row")),
    ),
    Mutation(
        "M-37",
        "G-TWEEN",
        "BQ-10 rule 2",
        spec=sub_in(
            "7.1 Cadence",
            "the digits, prices, sizes and countdowns never interpolate",
            "the digits count up",
        ),
    ),
    Mutation("M-38", "G-DIALOG", "BQ-14", spec=mo("Mo-8", "Safe", to("`normal` scale + fade"))),
    Mutation(
        "M-39",
        "G-Q1",
        "BQ-9",
        spec=line_edit(
            "- **D04-Q1**",
            "Closed with this sentence",
            "Cancel is T1 in case 1. Closed with this sentence",
        ),
    ),
    Mutation(
        "M-40", "G-TIER", "BQ-5", hand=line_edit("- **Tier**: Organism", "Organism", "Molecule")
    ),
    Mutation(
        "M-41",
        "G-KIND",
        "BQ-5",
        hand=line_edit(
            "- **Props**: `kind:",
            '`kind: "twap"|"iceberg"|"chase"`',
            '`kind: "twap"|"iceberg"|"chase"|"oco"`',
        ),
    ),
    Mutation(
        "M-42",
        "G-REDUCE-SOURCE",
        "BQ-15",
        spec=sub_in(
            "7.5 Reduced motion",
            "(M-14).",
            "(M-14). CMP-118 reads `prefers-reduced-motion` via `matchMedia`.",
        ),
    ),
    Mutation("M-43", "G-CR", "BQ-8", hand=drop_row("§D Change requests", "CR-E1")),
    Mutation(
        "M-44",
        "G-LOOP",
        "BQ-14",
        spec=with_values(
            lambda v: mo(
                "Mo-7",
                "Safe",
                lambda c: c.replace(f"stopped at {anchored('MOTION:skeleton.stop-s')(v)} s, ", ""),
            )
        ),
    ),
    Mutation(
        "M-45",
        "G-ONE-ENTRY",
        "BQ-7",
        spec=sub_in(
            "3. CMP-246",
            "The copy-ready entry is hand-off A-2.",
            "A second status entry, CMP-247 AlgoHaltLabel, carries the halted state.",
        ),
    ),
    Mutation("M-46", "G-HANDOFF", "BQ-3", hand=line_edit("## §B ", "## §B ", "## §G ")),
    Mutation(
        "M-47",
        "G-CMP118",
        "BQ-6",
        hand=line_edit("- **Props**: `variant:", '|"scaled"|"oco"`', '|"scaled"`'),
    ),
    Mutation("M-48", "G-DRIFT-SCOPE", "BQ-16", hand=drop_row("§E Drift ledger", "DR-9")),
    Mutation(
        "M-49",
        "G-A11Y",
        "BQ-20",
        hand=line_edit(
            '- **A11y**: `role="dialog"`',
            "`Esc` closes and never cancels a run",
            "`Esc` cancels the run",
        ),
    ),
    Mutation(
        "M-50",
        "G-OWNER",
        "BQ-11",
        spec=line_edit("| BQ-11 ", "; owner approval pending (#2701)", ""),
    ),
    Mutation(
        "M-51",
        "G-DIALOG",
        "BQ-14",
        hand=line_edit(
            "- **Motion spec**: [E33-D04.md](../design/E33/E33-D04.md) §7 — the dialog",
            "the dialog per CMP-043 as ruled;",
            "the dialog per CMP-043 as ruled. The dialog opens with a `normal` scale and fade;",
        ),
    ),
    Mutation(
        "M-52",
        "G-COUNTDOWN",
        "BQ-13",
        spec=prose_at("5. CMP-245", "The countdown animates smoothly between ticks."),
    ),
    Mutation(
        "M-53", "G-RESUME", "BQ-1", spec=prose_at("5. CMP-245", "A halted run offers Resume.")
    ),
    Mutation(
        "M-54",
        "G-REDUCE-INSTANT",
        "BQ-15",
        spec=prose_at("5. CMP-245", "Under reduced motion the bar still slides."),
    ),
    Mutation(
        "M-55",
        "G-TWEEN",
        "BQ-10 rule 2",
        spec=prose_at("5. CMP-245", "The progress text interpolates between samples."),
    ),
    Mutation(
        "M-56",
        "G-LOOP",
        "BQ-14",
        spec=prose_at("5. CMP-245", "The skeleton loops until data arrives, with no stop."),
    ),
    Mutation(
        "M-57",
        "G-EMULATED",
        "BQ-4",
        spec=prose_at("5. CMP-245", "A consumer may set `emulated` to false on demo."),
    ),
    Mutation(
        "M-58",
        "G-NOFADE",
        "BQ-11",
        hand=line_edit(
            "- **Motion spec**: [E33-D04.md](../design/E33/E33-D04.md) §7 Mo-6",
            "§7 Mo-6 — never animates;",
            "§7 Mo-6 — running to paused cross-fades;",
        ),
    ),
    Mutation(
        "M-59",
        "G-DRIFT",
        "BQ-17",
        hand=row_edit("§E Drift ledger", "DR-14", DR_COLS.index("Replacement"), to("TBD")),
    ),
    Mutation(
        "M-60",
        "G-DRIFT",
        "BQ-17",
        hand=sub_in("C.2 A-2", "Deliberate exception (DR-11):", "Deliberate exception:"),
    ),
    Mutation(
        "M-61",
        "G-CONTRAST",
        "BQ-8",
        spec=row_edit("10. Contrast", "`bar-danger`", 1, to("`color.status.danger.default`")),
    ),
    Mutation("M-62", "G-CVD-PORT", "BQ-8", patch=nudge_projection),
    Mutation(
        "M-63", "G-TWIN", "BQ-15", spec=mo("Mo-3", "Twin", to("prefers-reduced-motion: none"))
    ),
    Mutation(
        "M-64",
        "G-TWIN",
        "BQ-15",
        spec=mo("Mo-2", "Twin", to("prefers-reduced-motion: same as motion-safe")),
    ),
    Mutation(
        "M-65",
        "G-TWIN",
        "BQ-15",
        spec=prose_at(
            "7.5 Reduced motion", "Mo-3's flash on the focused row has no reduced variant."
        ),
    ),
    Mutation("M-66", "G-TWIN", "BQ-15", spec=line_edit("| Mo-10 ", "| Mo-10 ", "| **Mo-10** ")),
    Mutation(
        "M-67",
        "G-TWIN16",
        "BQ-15",
        hand=line_edit(
            "| Bars in grid rows",
            "`prefers-reduced-motion`: the same step",
            "`prefers-reduced-motion`: none",
        ),
    ),
    Mutation("M-68", "G-INSTANT", "BQ-11", spec=mo("Mo-6", "Safe", appended("; eased"))),
    Mutation(
        "M-69",
        "G-INSTANT",
        "BQ-11",
        spec=prose_at(
            "7.3 Never animates",
            "State transitions, in motion-safe, take a hundred and twenty milliseconds.",
        ),
    ),
    Mutation(
        "M-70",
        "G-INSTANT",
        "BQ-11",
        spec=table_at(
            "7.3 Never animates", "| state transition | eased over `motion.duration.fast` |"
        ),
    ),
    Mutation(
        "M-71",
        "G-CADENCE",
        "BQ-10 rule 1",
        spec=mo("Mo-2", "Trigger", appended(" (bursting to 4 per second)")),
    ),
    Mutation(
        "M-72",
        "G-CADENCE",
        "BQ-10 rule 1",
        spec=prose_at("7.3 Never animates", "The card bar animates at up to ten updates a second."),
    ),
    Mutation(
        "M-73",
        "G-CADENCE",
        "BQ-10 rule 1",
        spec=mo("Mo-2", "Trigger", lambda c: c.replace("a sample, ", "every animation frame, ")),
    ),
    Mutation(
        "M-74",
        "G-BANNER",
        "BQ-12",
        spec=prose_at("7.3 Never animates", "The degraded banner glides in from the top."),
    ),
    Mutation(
        "M-75",
        "G-BANNER",
        "BQ-12",
        spec=prose_at("7.3 Never animates", "The degraded ban<!---->ner slides in."),
    ),
    Mutation(
        "M-76",
        "G-BANNER",
        "BQ-12",
        spec=prose_at("7.3 Never animates", "The degraded banner never fails to slide in."),
    ),
    Mutation(
        "M-77",
        "G-BANNER",
        "BQ-12",
        spec=mo("Mo-5", "Property", to("`transform: translateY` (a slide)")),
    ),
    Mutation(
        "M-78", "G-TRIAD", "BQ-8", spec=reg("CMP-246/paused-by-you · dark", "Glyph", to("(none)"))
    ),
    Mutation(
        "M-79",
        "G-TRIAD",
        "BQ-8",
        spec=prose_at("3.5 Never colour alone", "Completed is shown by the green fill alone."),
    ),
    Mutation(
        "M-80",
        "G-TRIAD",
        "BQ-8",
        spec=reg("CMP-246/paused-by-you · dark", "Frame", lambda c: c.strip("`")),
    ),
    Mutation(
        "M-81",
        "G-AFFORD",
        "BQ-4",
        spec=prose_at("2. The emulated", "The Estimated Badge, on the card, marks emulated runs."),
    ),
    Mutation(
        "M-82",
        "G-AFFORD",
        "BQ-4",
        spec=prose_at("2. The emulated", "No other badge than CMP-227 marks emulation."),
    ),
    Mutation(
        "M-83",
        "G-TOKEN",
        "condition",
        spec=prose_at("2. The emulated", "The tag fill is color.emulated.tag (new)."),
    ),
    Mutation(
        "M-84",
        "G-TOKEN",
        "condition",
        spec=prose_at("2. The emulated", "The tag fill is `--cv-color-emulated-tag`."),
    ),
    Mutation(
        "M-85",
        "G-TOKEN",
        "condition",
        spec=prose_at("2. The emulated", "The tag casts `Shadow.Emulated`."),
    ),
    Mutation(
        "M-86",
        "G-T2",
        "BQ-9",
        spec=prose_at("7.3 Never animates", "Pause is T2 on `algo.pause_emulated`."),
    ),
    Mutation(
        "M-87",
        "G-EXITS",
        "condition",
        spec=prose_at("7.3 Never animates", "Dismiss, while a run is live, is T2-gated."),
    ),
    Mutation("M-88", "G-EXITS", "condition", spec=table_at("7.3 Never animates", "| Close | T2 |")),
    Mutation(
        "M-89",
        "G-DRIFT",
        "BQ-17",
        hand=row_edit("§E Drift ledger", "DR-1", DR_COLS.index("Owner"), to("—")),
    ),
    Mutation(
        "M-90",
        "G-DRIFT",
        "BQ-17",
        hand=prose_at("§B ", "DR-4 is still unresolved; no owner has answered."),
    ),
    Mutation(
        "M-91",
        "G-DRIFT",
        "BQ-17",
        hand=add_row_after(
            "§E Drift ledger",
            "DR-16",
            "| DR 17 | D02:149 | `radius.badge` | a | `radius.badge` | E33-D02 lane | open |",
        ),
    ),
    Mutation("M-92", "G-UNTOUCHED", "BQ-2", p15=crlf),
    Mutation(
        "M-93",
        "G-PIN",
        "condition",
        spec=prose_at("7.3 Never animates", "D02 is read at `deadbeef00` for this section."),
    ),
    Mutation(
        "M-94",
        "G-PIN",
        "condition",
        spec=line_edit(
            "**Start.**",
            "D02 text #4368 (`4f9d15b6`) and boards #4425",
            "D02 boards #4368 (`4f9d15b6`) and text #4425",
        ),
    ),
    Mutation(
        "M-95",
        "G-PIN",
        "condition",
        spec=prose_at("7.3 Never animates", "D02:415 (`88839ea3`) says the swaps are instant."),
    ),
    Mutation(
        "M-96",
        "G-BOARDS",
        "BQ-18",
        spec=prose_at(
            "0. Artefacts", "An eleventh board, `E33-D04 / 11 tag-specimen`, draws the tag."
        ),
    ),
    Mutation(
        "M-97",
        "G-BOARDS",
        "BQ-18",
        spec=line_edit("## 0. Artefacts", "ten planned boards", "eleven planned boards"),
    ),
    Mutation(
        "M-98",
        "G-BOARDS",
        "BQ-18",
        spec=add_row_after(
            "0. Artefacts",
            "10",
            "| 11a | `E33-D04 / 10 builder-shell-light` | light twin of 05"
            " | PENDING: drawn in the boards PR |",
        ),
    ),
    Mutation(
        "M-99",
        "G-Q3",
        "comment 6401561066",
        spec=line_edit("- **D04-Q3**", RULED_1442, "awaiting ruling"),
    ),
    Mutation(
        "M-100",
        "G-C15",
        "comment 6401561066",
        hand=row_edit(
            "Table A",
            "A-7.2",
            4,
            lambda c: c.replace(
                "`color.status.danger.strong` (not", "`color.status.danger.default` (not", 1
            ),
        ),
    ),
    Mutation(
        "M-101",
        "G-DR14",
        "comment 6401561066",
        hand=row_edit(
            "§E Drift ledger",
            "DR-14",
            DR_COLS.index("Replacement"),
            lambda c: c.replace("CONFIRMED", "proposed", 1),
        ),
    ),
    # record r1 (comment 6400168737): one mutation per form that passed at round 1
    Mutation(
        "M-102",
        "G-TWEEN",
        "BQ-10 rule 3",
        spec=prose_at(
            "7.3 Never animates", "Between samples, the card bar eases to the next value."
        ),
    ),
    Mutation(
        "M-103",
        "G-TWEEN",
        "BQ-10 rule 3",
        spec=prose_at("5. CMP-245", "The bar interpolates between samples."),
    ),
    Mutation(
        "M-104",
        "G-TWEEN",
        "BQ-10 rules 1 and 3",
        hand=row_edit(
            "C.8 The `16`",
            "Bars on single-run surfaces",
            2,
            to("the fill eases on toward the next value between samples"),
        ),
    ),
    Mutation(
        "M-105",
        "G-COUNTDOWN",
        "BQ-13",
        spec=prose_at("7.3 Never animates", "The countdown eases into each new second."),
    ),
    Mutation(
        "M-106",
        "G-AFFORD",
        "BQ-4",
        spec=sub_in(
            "1.3 Locked inputs",
            "`algo-builder`; CMP-227 never the badge",
            "`algo-builder`; CMP-227 EstimatedBadge as the badge",
        ),
    ),
    Mutation(
        "M-107",
        "G-TAGNAME",
        "BQ-4 part 1 (D03:363)",
        spec=sub_in(
            "2. The emulated",
            'accessible name "Emulated — run by CandleViewer, not Bybit"',
            'accessible name "Emulated"',
        ),
    ),
    Mutation(
        "M-108",
        "G-AFFORD",
        "BQ-4 (quoted copy)",
        spec=prose_at(
            "2. The emulated", 'The emulated run is marked with the "(estimated)" badge.'
        ),
    ),
    Mutation(
        "M-109",
        "G-T2",
        "R-5 / BQ-9 (lock)",
        spec=prose_at("3.6 A11y contract", "A halted label carries the CMP-019 `lock` glyph."),
    ),
    Mutation(
        "M-110",
        "G-T2",
        "R-5 / BQ-9 (T2)",
        spec=prose_at("3.6 A11y contract", "The paused label is T2 while a run is live."),
    ),
    Mutation(
        "M-111",
        "G-HALTED",
        "BQ-9",
        spec=sub_in(
            "9.2 The frame register",
            "the PROPOSED stamp of §3.3",
            "`halted` is drawn as shipped, with no PROPOSED stamp",
        ),
    ),
    Mutation(
        "M-112",
        "G-INSTANT",
        "BQ-11 (a cite exempts its clause only)",
        spec=with_values(
            lambda v: prose_at(
                "7.3 Never animates",
                f"Running → paused settles over {anchored('MOTION:ticket.crossfade-ms')(v)} ms"
                " (D04-C3).",
            )
        ),
    ),
    Mutation(
        "M-113",
        "G-NOFADE",
        "BQ-11",
        hand=with_values(
            lambda v: sub_in(
                "C.2 A-2",
                "word, glyph and fill change at frame 0 in both modes",
                "word, glyph and fill cross-fade over"
                f" {anchored('MOTION:ticket.crossfade-ms')(v)} ms",
            )
        ),
    ),
    Mutation(
        "M-114",
        "G-INSTANT",
        "BQ-11 (quoted copy)",
        spec=mo("Mo-6", "Safe", appended('; the copy deck says "settles over 120 ms"')),
    ),
    Mutation(
        "M-115",
        "G-TWIN",
        "BQ-14 (per CMP-043 on Mo-8 only)",
        spec=mo("Mo-2", "Twin", to("prefers-reduced-motion: per CMP-043")),
    ),
    Mutation(
        "M-116",
        "G-RULED",
        "RULED cites comment 6397030902 or 6401561066",
        spec=prose_at(
            "14.3 Deviations",
            "D04-Q3 is RULED by the orchestrator's ruling of 2026-10-25 14:42Z (LANE-hcl1-98).",
        ),
    ),
    Mutation(
        "M-117",
        "G-STORIES",
        "§0 `CMP-246/paused-rate-limit`",
        hand=row_edit(
            "§F Storybook",
            "CMP-246 AlgoStateLabel",
            1,
            lambda c: c.replace(" · Paused/RateLimit", "", 1),
        ),
    ),
    # record r2: one mutation per class of form that passed at round 2
    Mutation(
        "M-118",
        "G-COUNTDOWN",
        "BQ-13 (the motion vocabulary)",
        spec=prose_at("7.3 Never animates", "The countdown pulses on each new second."),
    ),
    Mutation(
        "M-119",
        "G-TWEEN",
        "BQ-10 rule 3 (the sample nouns)",
        spec=prose_at(
            "7.3 Never animates", "Between readings, the card bar eases to the next value."
        ),
    ),
    Mutation(
        "M-120",
        "G-T2",
        "R-5 / BQ-9 (the subject carried across a semicolon)",
        spec=prose_at(
            "3.6 A11y contract",
            "The paused label sits in the header; it is T2 while a run is live.",
        ),
    ),
    Mutation(
        "M-121",
        "G-TWEEN",
        "BQ-10 rule 3 (a negation chain)",
        spec=prose_at("7.3 Never animates", "The bar never stops easing between samples."),
    ),
    Mutation(
        "M-122",
        "G-CADENCE",
        "R-3 / BQ-10 rule 1 (a rate in fps)",
        spec=prose_at("7.3 Never animates", "The card bar moves at 30 fps."),
    ),
    Mutation(
        "M-123",
        "G-DIALOG",
        "BQ-14 (a cite exempts its own sub-clause only)",
        spec=prose_at("5. CMP-245", "Dialogs scale in per CMP-043 as ruled, and also fade."),
    ),
    Mutation(
        "M-124",
        "G-EMULATED",
        "BQ-4 / T Sec (the tag suppressed)",
        spec=prose_at("4.3 The `emulated: true`", "The Emulated tag is suppressed on dense rows."),
    ),
    # record r3: one mutation per class of form that passed at round 3
    Mutation(
        "M-125",
        "G-TWEEN",
        "BQ-10 rule 2 (roll)",
        spec=prose_at("7.3 Never animates", "The sizes roll to each new value."),
    ),
    Mutation(
        "M-126",
        "G-HALTED",
        "BQ-9 (GA as shipped)",
        spec=prose_at("7.3 Never animates", "The `halted` variant is generally available."),
    ),
    Mutation(
        "M-127",
        "G-INSTANT",
        "BQ-11 (barely instant)",
        spec=prose_at("7.3 Never animates", "State changes are barely instant."),
    ),
    Mutation(
        "M-128",
        "G-EXITS",
        "R-4 (Esc swallowed)",
        spec=prose_at("7.3 Never animates", "`Esc` is swallowed while a run is live."),
    ),
    Mutation(
        "M-129",
        "G-INSTANT",
        "BQ-11 (a duration in frames)",
        spec=prose_at("7.3 Never animates", "A state change takes three frames."),
    ),
    Mutation(
        "M-130",
        "G-TWEEN",
        "BQ-10 rule 3 (a flip)",
        spec=prose_at(
            "7.3 Never animates", "It is false that the bar never glides between samples."
        ),
    ),
    Mutation(
        "M-131",
        "G-DIALOG",
        "BQ-14 (a cite exempts its parenthesis only)",
        spec=prose_at(
            "5. CMP-245", "Dialogs open with a scale-up (per CMP-043 as ruled) and a fade."
        ),
    ),
    Mutation(
        "M-132",
        "G-TWEEN",
        "BQ-10 rule 3 (to the following sample)",
        spec=prose_at(
            "7.3 Never animates", "The card bar glides from one sample to the following one."
        ),
    ),
    Mutation(
        "M-133",
        "G-COUNTDOWN",
        "BQ-13 (the countdown under another name)",
        spec=prose_at("7.3 Never animates", "The time until the next slice slides on each tick."),
    ),
    Mutation(
        "M-134",
        "G-STEP",
        "BQ-10 (every bar, by where it sits)",
        spec=prose_at("7.3 Never animates", "On SCR-070, every bar eases to its new value."),
    ),
    Mutation(
        "M-135",
        "G-NEVER",
        "§7.3 (a never-animates item)",
        spec=prose_at("7.3 Never animates", "DEMO ↔ LIVE cross-fades; the theme switch slides."),
    ),
)


def digest_texts(*texts: str) -> list[str]:
    return [hashlib.sha256(t.encode("utf-8")).hexdigest() for t in texts]


def digest(paths: tuple[Path, ...]) -> list[str]:
    """The sha256 of each file's bytes as read from disk now (the restore check's evidence)."""
    return [hashlib.sha256(p.read_bytes()).hexdigest() if p.exists() else "" for p in paths]


def diff_names() -> tuple[str, ...]:
    return tuple(n for n in git_out("diff", "--name-only", BASE).split("\n") if n)


def selftest(
    spec: str, hand: str, p15: str, p16: str, paths: tuple[Path, ...]
) -> tuple[bool, list[str]]:
    on_disk = digest(paths)
    values = compute(spec, hand)[0]
    spec_f, _ = fill(spec, values)
    hand_f, _ = fill(hand, values)
    values = compute(spec_f, hand_f)[0]  # frozen at the filled baseline
    skeys, hkeys = text_keys(spec), text_keys(hand)
    names = diff_names()
    base_t = Texts(spec_f, hand_f, p15, p16, values, names)
    base_fails, base_warns, _ = audit(base_t, git_fetch, skeys, hkeys)
    lines = [f"baseline (filled in memory): {len(base_fails)} FAIL, {len(base_warns)} WARN"]
    lines += [f"  baseline FAIL {x[:160]}" for x in base_fails]
    ok = not base_fails
    pristine = digest_texts(spec_f, hand_f, p15, p16)
    for mu in MUTATIONS:
        s = mu.spec(spec_f, values) if mu.spec else spec_f
        h = mu.hand(hand_f, values) if mu.hand else hand_f
        q = mu.p15(p15) if mu.p15 else p15
        if (s, h, q) == (spec_f, hand_f, p15) and mu.patch is None:
            ok = False
            lines.append(f"  {mu.mid} [{mu.gate}] NOT APPLIED (the target text moved)")
            continue
        undo = mu.patch() if mu.patch else None
        try:
            fails, _w, _ = audit(Texts(s, h, q, p16, values, names), git_fetch, skeys, hkeys)
        except SystemExit as exc:
            fails = [str(exc)]
        finally:
            if undo:
                undo()
        new = [x for x in fails if x not in base_fails]
        named = [x for x in new if x.startswith(f"[{mu.gate}]")]
        hit = bool(named) and len(new) == 1
        restored = digest_texts(spec_f, hand_f, p15, p16) == pristine and digest(paths) == on_disk
        restored = restored and not g_cvd_port(base_t)  # tool state put back
        ok = ok and hit and restored
        first = (named or new or ["nothing new"])[0][:120]
        lines.append(
            f"  {mu.mid} [{mu.gate}] {'ok' if hit else 'MISSED'} ({len(new)} new"
            f"{'' if restored else ', NOT RESTORED'}) — {first}"
        )
        if not hit:
            lines += [f"      new: {x[:160]}" for x in new]
    return ok, lines


def cvd_doc(extra: dict[str, object]) -> dict[str, object]:
    """The `cvd` section (RULED BQ-8): `fills.<sim>.<theme>` and `glyphs.<sim>.<theme>` pair
    matrices, `grey.<theme>` (ΔL*), every family pair's smallest fill ΔE76 across simulations and
    themes (`pairs`, the pass condition's input), the pairs under the floor and the colours."""
    tables = extra.get("cvd.tables")
    doc: dict[str, object] = dict(tables) if isinstance(tables, dict) else {}
    doc["pairs"] = extra.get("cvd.pairs")
    doc["under-floor"] = extra.get("cvd.under-floor")
    doc["colours"] = {k: extra.get(k) for k in ("fills.dark", "fills.light")}
    return doc


def main(argv: list[str]) -> int:
    ap = argparse.ArgumentParser(description="E33-D04 DS and motion audit (module docstring)")
    ap.add_argument("--check", action="store_true", help="audit the spec and the hand-off")
    ap.add_argument("--json", action="store_true", help="print every computed value as JSON")
    ap.add_argument("--fill", action="store_true", help="replace placeholders, then check")
    ap.add_argument("--selftest", action="store_true", help="apply every mutation in memory")
    args = ap.parse_args(argv)
    spec_path, hand_path = ROOT / SPEC_REL, ROOT / HAND_REL
    p15_path, p16_path = ROOT / P15_REL, ROOT / P16_REL
    spec, hand = spec_path.read_text(encoding="utf-8"), hand_path.read_text(encoding="utf-8")
    # `15` / `16` as bytes, so a line-ending change is a change (G-UNTOUCHED)
    p15, p16 = p15_path.read_bytes().decode("utf-8"), p16_path.read_bytes().decode("utf-8")
    if args.selftest:
        ok, lines = selftest(spec, hand, p15, p16, (spec_path, hand_path, p15_path, p16_path))
        print("\n".join(lines))
        print(f"--selftest: {'ok' if ok else 'FAIL'} — {len(MUTATIONS)} mutations in memory")
        return 0 if ok else 1
    skeys, hkeys = text_keys(spec), text_keys(hand)
    values, extra, matrix = compute(spec, hand)
    if args.fill:
        spec, unknown = fill(spec, values)
        hand, unknown_h = fill(hand, values)
        spec_path.write_text(spec, encoding="utf-8")
        hand_path.write_text(hand, encoding="utf-8")
        for u in unknown + unknown_h:
            print(f"FAIL --fill: no value for {{{{{u}}}}}")
        values, extra, matrix = compute(spec, hand)
    if args.json and not (args.check or args.fill):
        print(
            json.dumps(
                {"values": values, "extra": extra, "contrast": matrix, "cvd": cvd_doc(extra)},
                ensure_ascii=False,
                indent=1,
            )
        )
        return 0
    t = Texts(spec, hand, p15, p16, values, diff_names())
    fails, warns, n = audit(t, git_fetch, skeys, hkeys)
    if args.json:
        doc: dict[str, object] = {
            "values": values,
            "extra": extra,
            "contrast": matrix,
            "cvd": cvd_doc(extra),
        }
        doc.update({"fails": fails, "warnings": warns, "cites": n})
        print(json.dumps(doc, ensure_ascii=False, indent=1))
    else:
        print(f"## E33-D04 audit of {SPEC_REL} (+ the hand-off) at base {BASE}")
        print(f"values computed: {len(values)}; cites checked: {n}; gates: {len(GATES) + 3}")
        print(f"stories: {extra.get('stories.arithmetic')}; spec line budget {SPEC_LINE_BUDGET}")
        print("\n".join(f"WARN {w}" for w in warns))
        print("\n".join(f"FAIL {x}" for x in fails) or "OK — every gate passed")
        print(f"summary: {len(fails)} FAIL, {len(warns)} WARN")
    return 1 if fails else 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
