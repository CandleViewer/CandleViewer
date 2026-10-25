#!/usr/bin/env python3
"""E27-D03 hi-fi audit: the accounts and key-vault spec against its inputs, every number computed.

Standalone, offline, stdlib only (``python3 -I -B``). It reads the spec, E27-D02, the E27-D01
memo, E09-D09, ``11``, ``14``, ``15``, the CONSTITUTION, the token JSON and
``tools/contrast/pairs.mjs`` as text, and runs no repository code apart from the design tools it
reuses through one ``_load``: ``verify_tokens.py`` (the theme layering),
``contrast_check.contrast_ratio()``, ``cvd_simulate`` (``simulate``, ``delta_e76``) and
``e27_d02_wires_audit.py`` (``rows``, ``section``, ``ticked``, ``scan``, ``FRAME_RE``) - imported,
never re-implemented. Nine sections, each row labelled with its source so a reviewer can re-grep
it (BQ-16 is the scope):

1. The measured matrix: every fg / bg pair the hi-fi draws x dark / light / high-contrast against
   its role's bar - text 4.5, non-text 3.0, hc-text 7.0 (gated in high-contrast only);
   ``rejected-*``, ``decorative`` and ``composite`` rows are reported, never gated. ``CR:`` rows
   are measured on the token or primitive the change request would alias (no hex is invented).
   Reproductions are gated equal to the hundredth (E09-D09 section 11's T2 rows, the env rows,
   the BQ-3 and BQ-6 anchors) and so are the CMP-039 ring minima over the seven surface tiers.
   Each gated row is ``pairs.mjs`` registered or PROPOSED.
2. AC2 carriers: section 2.1's CMP-175 variant table - the ticket's eight variants each with a
   row, every word its own, every glyph its class's (check, octagon, triangle, clock, dash,
   info), no warning-class state on the octagon, the bold + border mark on the critical state
   only and its word leading with "BLOCKED", "OFF" only in a pass word. CVD (Delta E76 normal /
   protanopia / deuteranopia / tritanopia, JND 5.0) and Rec. 601 luma are reported, never gated.
3. Token bindings: every backticked token exists in the merged set, or its line marks it
   PROPOSED / G-row / DS-n / not a token; ``15``'s non-token names are expected missing (never in
   an Appendix A New cell); ``color.text.disabled`` and ``opacity.disabled`` appear in a T2 or
   disabled row only negated (the validity look excepted).
4. Inventory and cap: E27-D02 section 7's 78 frames, each with exactly one hi-fi row carrying
   D02's number and name (no stray frame name); at most 10 boards (rows numbered with two
   digits), light twins at most a third, each a twin of a dark board; a board's State is
   PENDING, drawn or "not drawn - the text is binding; drawn on request"; a drawn row needs its
   board id and an existing PNG (boards 01-02 also their greyscale, deuteranopia and protanopia
   renders); every frame's board cell agrees with section 0.
5. T2: the rule sentence once, in section 10.1, view-as before every other leg; every E27-D02
   "shows T2" frame's row cites T2_EXACT ("T2 per §10.1"); every gated row names CMP-079 and
   ``lock``, legs view-as first, rendering 2a / 2b / sentence form; the not-T2 list complete;
   every ``keys.*`` / ``accounts.*`` / ``rbac.*`` reason one sentence of at most 60 characters
   with a full stop, ``rbac.*`` verbatim E09-D09 section 3.1.
6. Copy: deck rows keyed ``e27.*`` and unique; status unchanged / refined / new / consumed;
   unchanged CD-n / CP-n strings byte-equal to the memo; consumed strings verbatim in their
   source; no banned product word; every clock time in UTC; a withdrawal "OFF" or "off" only
   beside its "verified" time (AD-3); withdrawal never drawn as allowed.
7. Appendix A: every Old (verbatim) cell occurs exactly once in its ``15`` / ``14`` entry at the
   base - none is a FAIL (gone), more is a FAIL (ambiguous), another line than its cite a WARN
   (drift); CMP-044 and CMP-178 rows WARN while E42-D03's boards PR is in flight; every Old and
   New cell is read whole by 7c; ``14`` inserts are content-only "Hi-fi (E27-D03)" lines.
7b. Frame rows (the standing rule A2, main-orchestrator 2026-10-25 00:32Z): every gate below reads
   each of the 78 frame rows on its own, never a sentence elsewhere. K1 no control that shows or
   copies key material, no key id but ``...`` plus 4; K2 (``reveal``) is 7c's; K3 no withdrawal
   or transfer right drawn as allowed (its dated OFF is 7c's); K4 / K5 each DESTRUCTIVE frame's Copy keys
   name its consequence key and the ask line (both in section 12), section 7's confirms table
   states both, and no other frame draws a destructive confirm; K6-K8 each gated frame names the
   ``lock`` and a known reason key, ``rbac.view_as`` first, and a frame E27-D02's inventory or
   its class names as a view-as frame leads its Hi-fi and Copy keys cells with it (G7); K9 no exit drawn gated (a frame or
   section 10.2); K10 is gate 2 (``ac2.*``); K11 the compromise card's steps, keys and deck
   strings in C-12.12's order; K12 each row naming an environment, an account title or an
   "Attention:" strip string keeps its environment badge; K13 the
   number before a marker is its value and every two-decimal value has a marker; K14 / K15 are
   gate 4 (``inv.missing``, ``inv.board``).
7c. The whole document (the orchestrator's text round 2): every clause of every line of the spec
   and the hand-off, case-insensitive, no section list - a reveal word or affordance, K1's ids,
   K2's show / copy / toggle controls, K3's fund rights drawn as allowed or as a control, and a
   withdrawal OFF without its verified time (frame rows: the reveal words and the OFF only). A hit
   passes only inside a phrase of SECURITY_ALLOWED, each covering at most its pinned count of
   occurrences, so a copy of an allowed phrase elsewhere fails; one FAIL per line.
8. Cites and scans: ``KEY:line`` cites resolve to an existing line (FAIL past the end of the
   file); a cite followed by a quoted fragment WARNs when its line moved and FAILs when the
   fragment is gone or ambiguous (e35_d03's semantics); E27-D02's ``scan()`` (no secret-shaped
   run, key ids ``...`` plus 4, IPv4 only from RFC 5737, 7+ digit numbers only the placeholder
   UIDs) after commit / sha256 pins and ruling ids are masked; ids resolve (C-x.y, CMP, SCR, US);
   no private path, Penpot host, closing keyword or placeholder.
9. Counts and markers: BQ rows all PROPOSED or all RULED; ``--check`` re-derives every
   ``<!-- audit:NAME=VALUE -->`` marker in the spec.

``--self-test`` (or ``--selftest``) builds a passing spec in memory from the base files (E27-D02
section 7, ``15``, ``14``, the memo) and refuses every mutation in MUTATIONS, each by its own
failure code (a reveal prop, a shared word, an octagon on a warning, an 11th board, light twins
over a third, a dimmed T2, an altered unchanged seed, a moved / gone / ambiguous cite, ...);
when the spec on disk has no FAIL it also runs every applicable mutation on it. Then
K_MUTATIONS, one or more per K-item, each in memory on the spec on disk as a plain run: rc 1 with exactly
one distinct FAIL of its own code; restored, ``--check`` passes and the file is byte-identical
(sha256). The file on disk is never touched.

Usage: python3 -I -B docs/design/_tools/e27_d03_hifi_audit.py [--json] [--check] [--self-test]
Exit 1 on any gated FAIL (a plain run and ``--check``); ``--check`` also re-derives the markers;
WARNs never fail. UTF-8 stdout.
"""

from __future__ import annotations

import importlib.util
import json
import re
import string
import sys
from collections.abc import Callable
from hashlib import sha256 as _sha256
from pathlib import Path
from types import ModuleType
from typing import Any

ROOT = Path(__file__).resolve().parents[3]
TOOLS = ROOT / "docs" / "design" / "_tools"
TOKENS = ROOT / "packages" / "ui" / "tokens"
PLAN = ROOT / "docs" / "plan"
DESIGN = ROOT / "docs" / "design"
SPEC = DESIGN / "E27" / "E27-D03.md"
HANDOFF = DESIGN / "E27" / "E27-D03-handoff.md"
D02_SPEC = DESIGN / "E27" / "E27-D02.md"
MEMO = DESIGN / "research" / "e27-key-custody.md"
D09_SPEC = DESIGN / "E09" / "E09-D09.md"
PAIRS_MJS = ROOT / "tools" / "contrast" / "pairs.mjs"
IMG = "docs/design/E27/img"
MULTI = re.MULTILINE


def _load(path: Path, name: str) -> ModuleType:
    spec = importlib.util.spec_from_file_location(name, path)
    if spec is None or spec.loader is None:
        raise ImportError(f"cannot load {path}")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


verify = _load(TOKENS / "tests" / "verify_tokens.py", "verify_tokens")
contrast_check = _load(TOOLS / "contrast_check.py", "contrast_check")
cvd = _load(ROOT / "docs" / "research" / "_tools" / "cvd_simulate.py", "cvd_simulate")
d02 = _load(TOOLS / "e27_d02_wires_audit.py", "e27_d02_wires_audit")

THEMES = ("dark", "light", "high-contrast")
DEFICIENCIES = ("protanopia", "deuteranopia", "tritanopia")
JND = 5.0
BAR: dict[str, float] = {
    "text": 4.5,
    "non-text": 3.0,
    "hc-text": 7.0,
    "rejected-text": 4.5,
    "rejected-non-text": 3.0,
    "rejected-hc-text": 7.0,
}
GATED = ("text", "non-text", "hc-text")
RING_TIERS = ("app", "canvas", "raised", "overlay", "hover", "selected", "sunken")
RING_MIN = {"dark": "4.72", "light": "4.81", "high-contrast": "12.26"}  # E05-D02 CMP-039


def sha256(text: str) -> str:
    return _sha256(text.encode("utf-8")).hexdigest()


def read(path: Path) -> str:
    return path.read_text(encoding="utf-8") if path.exists() else ""


def cells(line: str) -> list[str]:
    """The cells of one Markdown table line; an escaped pipe stays in its cell, unescaped."""
    parts = re.split(r"(?<!\\)\|", line.strip())
    return [p.strip().replace("\\|", "|") for p in parts[1:-1]]


SEPARATOR = re.compile(r"^\|(?:\s*:?-+:?\s*\|)+\s*$")


def tables(text: str) -> list[tuple[list[str], list[tuple[str, list[str]]]]]:
    """Every table in ``text``: its header cells and its body rows as (raw line, cells)."""
    out: list[tuple[list[str], list[tuple[str, list[str]]]]] = []
    head: list[str] | None = None
    body: list[tuple[str, list[str]]] = []
    for line in text.splitlines():
        if line.startswith("|"):
            if head is None:
                head, body = cells(line), []
            elif not SEPARATOR.match(line):
                body.append((line, cells(line)))
            continue
        if head is not None:
            out.append((head, body))
            head = None
    if head is not None:
        out.append((head, body))
    return out


def find_table(text: str, *needles: str) -> tuple[list[str], list[tuple[str, list[str]]]] | None:
    for head, body in tables(text):
        joined = " | ".join(head).lower()
        if all(n.lower() in joined for n in needles):
            return head, body
    return None


def col(head: list[str], needle: str) -> int:
    return next((i for i, h in enumerate(head) if needle.lower() in h.lower()), -1)


def sections(spec: str) -> dict[str, str]:
    """'pre' (before section 0), '0'..'17' for '## N.', 'A' for Appendix A, 'N.M' for '### N.M'."""
    heads = [(m.start(), len(m[1]), m[2]) for m in re.finditer(r"^(#{2,3}) (.+)$", spec, MULTI)]
    first = next((p for p, lv, t in heads if lv == 2 and t.startswith("0.")), len(spec))
    out = {"pre": spec[:first]}
    for i, (pos, level, title) in enumerate(heads):
        end = next((p for p, lv, _ in heads[i + 1 :] if lv <= level), len(spec))
        m = re.match(r"(\d+(?:\.\d+)?)\.? ", title)
        if level == 2 and title.startswith("Appendix A"):
            out.setdefault("A", spec[pos:end])
        elif m and (level == 2) == ("." not in m[1]):
            out.setdefault(m[1], spec[pos:end])
    return out


def quoted(text: str) -> list[str]:
    return re.findall(r'"([^"]+)"', text)


def norm(text: str) -> str:
    return " ".join(text.replace("**", "").replace("`", "").split()).lower()


# --- 1. the measured matrix ----------------------------------------------------------------------
# id | element (where the hi-fi draws it) | fg | bg | role | reproduces (dark / light / hc · source)
PAIRS_TXT = """
c175-pass-word | CMP-175 pass words (verified, trade-only) on their fill | color.text.primary | color.status.success.subtle | text | —
c175-pass-glyph | CMP-175 check glyph on the pass fill | color.status.success.strong | color.status.success.subtle | non-text | —
c175-danger-word | CMP-175 critical and failed words (withdrawal-detected, IP-missing, IP-mismatch, expired, read-only on import); the blocked row's line 1; the KEK notice; the destructive confirm (E42-D02 D3) | color.text.primary | color.status.danger.subtle | text | 12.06 / 14.64 / 13.66 · BQ-6
c175-danger-glyph | CMP-175 octagon on the critical and failed fill; the destructive confirm's border | color.status.danger.strong | color.status.danger.subtle | non-text | —
c175-critical-border | the critical 2 px border and the blocked row's 4 px inline-start rule against the row surface (BQ-6, BQ-7) | color.status.danger.strong | color.surface.raised | non-text | 9.32 / 4.11 / 9.32 · BQ-6
c175-warning-word | CMP-175 warning words (expiring, check overdue) | color.text.primary | color.status.warning.subtle | text | —
c175-warning-glyph | CMP-175 triangle and clock on the warning fill | color.status.warning.strong | color.status.warning.subtle | non-text | —
c175-unknown-word | CMP-175 "not checked" (dash) on the neutral fill | color.text.primary | color.neutral.subtle | text | —
c175-unknown-glyph | CMP-175 dash; CMP-011's neutral label (the OK chip) | color.text.secondary | color.neutral.subtle | text | —
c175-info-word | CMP-175 stored read-only (BQ-5 rider) | color.text.primary | color.status.info.subtle | text | —
c175-info-glyph | CMP-175 info glyph on the info fill | color.status.info.strong | color.status.info.subtle | non-text | —
c175-solid-danger | a solid danger chip (BQ-6 alternative a; never drawn) | color.text.on-action | color.status.danger.default | rejected-hc-text | —
c175-hc-critical | the BLOCKED word in high contrast (7:1) | color.text.primary | color.status.danger.subtle | hc-text | —
page-text | the verdict line, h1 and page copy (CMP-087 page surface) | color.text.primary | color.surface.app | text | —
page-secondary | the verdict line's time and basis, page captions | color.text.secondary | color.surface.app | text | —
page-pass-glyph | the verdict line's check on the page | color.status.success.strong | color.surface.app | non-text | —
page-danger-glyph | the negated verdict's octagon on the page | color.status.danger.strong | color.surface.app | non-text | —
page-warning-glyph | the overdue verdict's clock on the page | color.status.warning.strong | color.surface.app | non-text | —
row-text | CMP-176 line 1 (label, UID, environment word), CMP-034's `...{last4}`, a disabled row at full contrast | color.text.primary | color.surface.raised | text | 14.35 / 15.62 / 16.25 · E30-D01 §3
row-secondary | CMP-176 line 2 (allowlist, key age, rotation due); the T2 reason | color.text.secondary | color.surface.raised | text | 8.81 / 8.98 / 14.35 · E09-D09 §11
row-link | "Details for {label}" and the row's links | color.text.link | color.surface.raised | text | —
row-hover | a hovered row | color.text.primary | color.surface.hover | text | —
row-hover-secondary | a hovered row's line 2 | color.text.secondary | color.surface.hover | text | —
row-pass-glyph | CMP-178 inline "Healthy" check in a row | color.status.success.strong | color.surface.raised | non-text | —
row-warning-glyph | CMP-178 inline "Degraded" triangle; rotation due | color.status.warning.strong | color.surface.raised | non-text | —
row-info-glyph | the stored read-only info glyph in a row | color.status.info.strong | color.surface.raised | non-text | —
blocked-secondary | the blocked row's line 2 sentence on the danger fill | color.text.secondary | color.status.danger.subtle | text | —
secondary-button | [Start the compromise response], Cancel (CMP-001 secondary) | color.text.primary | color.action.secondary.default | text | —
primary-button | Verify and save, Next, Run test (CMP-001 primary) | color.text.on-action | color.action.primary.default | text | 4.76 / 4.76 / 7.45 · E42-D02 §11
env-demo | DEMO glyph and border on a row | color.env.demo | color.surface.raised | non-text | 3.64 / 4.13 / 3.64 · E30-D01 §3
env-live | LIVE glyph and border on a row | color.env.live | color.surface.raised | non-text | 4.42 / 4.51 / 4.42 · E30-D01 §3
env-demo-overlay | DEMO glyph in a dialog title or the drawer | color.env.demo | color.surface.overlay | non-text | 3.36 / 3.80 / 3.36 · E30-D01 §3
env-live-overlay | LIVE glyph in a dialog title or the drawer | color.env.live | color.surface.overlay | non-text | 4.09 / 4.15 / 4.09 · E30-D01 §3
env-word | the environment word, 7:1 in high contrast (`05` §5 item 3) | color.text.primary | color.surface.raised | hc-text | —
t2-label | T2 label and lock (E09-D09 §11) | color.text.tertiary | color.surface.raised | text | 5.62 / 5.92 / 11.21 · E09-D09 §11
t2-label-page | T2 label and lock on the page | color.text.tertiary | color.surface.app | text | 6.29 / 6.81 / 12.54 · E09-D09 §11
t2-dimmed | the dimmed look, never drawn (E09-D09 §11; C-10 for a disabled row) | color.text.disabled | color.surface.raised | rejected-text | 2.86 / 3.74 / 2.86 · E09-D09 §11
hairline | the T2 fill's hairline, the CMP-011 stroke | color.border.default | color.surface.raised | decorative | —
dialog-text | dialog and drawer title and body; the masked id in a dialog; the absolute overlap time | color.text.primary | color.surface.overlay | text | 13.27 / 14.37 / 15.02 · E42-D02 §11
dialog-secondary | consequences, the ask line, CMP-035's relative mm:ss (BQ-10) | color.text.secondary | color.surface.overlay | text | 8.14 / 8.26 / 13.27 · E09-D09 §11
dialog-tertiary | the audit marker (CMP-093); a T2 label in a dialog or the drawer | color.text.tertiary | color.surface.overlay | text | 5.20 / 5.44 / 10.36 · E42-D02 §11
dialog-hc | dialog body text in high contrast (7:1) | color.text.primary | color.surface.overlay | hc-text | —
dialog-danger-fill | the destructive confirm's fill against the dialog | color.status.danger.subtle | color.surface.overlay | decorative | —
step-done | CMP-066 done (check) in the rotation dialog | color.status.success.strong | color.surface.overlay | non-text | —
step-refused | CMP-066 refused (octagon) in the rotation dialog | color.status.danger.strong | color.surface.overlay | non-text | —
step-warning | a triangle or clock in a dialog or the drawer | color.status.warning.strong | color.surface.overlay | non-text | —
field-value | key, secret and typed-label fields (CMP-201 write-only, CMP-044) | color.text.primary | color.surface.sunken | text | —
field-boundary-today | the field boundary today, never drawn (`border.default` on the dialog) | color.border.default | color.surface.overlay | rejected-non-text | 1.30 / 1.12 / 2.64 · E42-D02 §11
field-boundary-ds3 | CR: the DS-3 field boundary in a dialog (E42-D03's routing) | CR:color.border.input | color.surface.overlay | non-text | 5.20 / 5.44 / 10.36 · E42-D03 §15
field-boundary-ds3-page | CR: the DS-3 field boundary on SCR-126's page | CR:color.border.input | color.surface.raised | non-text | —
stale-chip | CMP-239 "Stale since {hh:mm:ss} UTC" (SCR-079) | color.data-confidence.stale.text | color.data-confidence.stale.surface | text | —
stale-glyph | CMP-239's clock on its tint | color.data-confidence.stale.indicator | color.data-confidence.stale.surface | non-text | —
ring-danger | the focus ring on the danger fill (BQ-3) | color.focus.ring | color.status.danger.subtle | non-text | 5.59 / 5.50 / 14.54 · BQ-3
ring-warning | the focus ring on the warning fill (BQ-3) | color.focus.ring | color.status.warning.subtle | non-text | 4.57 / 5.86 / 11.88 · BQ-3
ring-success | the focus ring on the pass fill | color.focus.ring | color.status.success.subtle | non-text | —
ring-neutral | the focus ring on the neutral fill | color.focus.ring | color.neutral.subtle | non-text | —
ring-info | the focus ring on the info fill | color.focus.ring | color.status.info.subtle | non-text | —
ring-page | the focus ring on the page | color.focus.ring | color.surface.app | non-text | —
ring-row | the focus ring on a row | color.focus.ring | color.surface.raised | non-text | —
ring-dialog | the focus ring in a dialog or the drawer | color.focus.ring | color.surface.overlay | non-text | —
ring-field | the focus ring on a text field | color.focus.ring | color.surface.sunken | non-text | —
link-overlay | SCR-079's two links on the drawer (held out of pairs.mjs pending E47-D03's retune) | color.text.link | color.surface.overlay | text | —
"""
# The change requests (CR:), each measured on what it would alias in every theme.
CR: dict[str, dict[str, str]] = {
    # DS-3 (E42-D02 section 11.4), routed by E42-D03 to the tertiary text token: field boundaries.
    "CR:color.border.input": dict.fromkeys(THEMES, "color.text.tertiary"),
    # DS-6 (E42-D02 section 11.4): a red danger.strong - a finding BQ-6 re-raises, never adopted.
    "CR:color.status.danger.strong": {
        "dark": "palette.red.400",
        "light": "palette.light.red.500",
        "high-contrast": "palette.red.400",
    },
}
# id | what | a | b - reported, never gated: the word, glyph and weight carry every state (BQ-6)
CVD_TXT = """
glyph-critical-warning | glyph: critical / failed vs warning (octagon vs triangle; DS-6) | color.status.danger.strong | color.status.warning.strong
glyph-critical-pass | glyph: critical / failed vs pass | color.status.danger.strong | color.status.success.strong
glyph-warning-pass | glyph: warning vs pass | color.status.warning.strong | color.status.success.strong
glyph-info-pass | glyph: stored read-only (info) vs pass | color.status.info.strong | color.status.success.strong
glyph-critical-info | glyph: critical vs info | color.status.danger.strong | color.status.info.strong
fill-critical-warning | fill: critical / failed vs warning | color.status.danger.subtle | color.status.warning.subtle
fill-critical-pass | fill: critical / failed vs pass (BQ-6) | color.status.danger.subtle | color.status.success.subtle
fill-warning-pass | fill: warning vs pass | color.status.warning.subtle | color.status.success.subtle
fill-unknown-pass | fill: not checked (neutral) vs pass | color.neutral.subtle | color.status.success.subtle
fill-unknown-critical | fill: not checked (neutral) vs critical | color.neutral.subtle | color.status.danger.subtle
solid-danger-live | a solid danger fill vs the LIVE accent (BQ-6 alternative a) | color.status.danger.default | color.env.live
env-demo-live | environment: DEMO vs LIVE | color.env.demo | color.env.live
ds6-warning | DS-6 candidate vs warning.strong (a finding, not adopted) | CR:color.status.danger.strong | color.status.warning.strong
"""
LUMA_TOKENS = (
    "color.status.success.subtle",
    "color.status.warning.subtle",
    "color.status.danger.subtle",
    "color.status.info.subtle",
    "color.neutral.subtle",
    "color.status.success.strong",
    "color.status.warning.strong",
    "color.status.danger.strong",
    "color.status.info.strong",
    "color.status.danger.default",
    "color.surface.app",
    "color.surface.raised",
    "color.surface.overlay",
    "color.text.primary",
    "color.env.demo",
    "color.env.live",
)


def rows_txt(txt: str) -> list[list[str]]:
    return [[c.strip() for c in ln.split(" | ")] for ln in txt.strip("\n").splitlines() if ln]


PRIM: dict[str, Any] = dict(verify.load(verify.PRIMITIVES))


def theme_tokens(theme: str) -> dict[str, Any]:
    allt: dict[str, Any] = dict(PRIM)
    allt.update(verify.merged_set(verify.THEMES[theme]))
    return allt


def theme_colors(theme: str) -> dict[str, str]:
    allt = theme_tokens(theme)
    return {
        name: str(verify.resolve(tok["$value"], allt)).upper()
        for name, tok in allt.items()
        if isinstance(tok, dict) and tok.get("$type") == "color"
    }


def colour(th: dict[str, dict[str, str]], theme: str, token: str) -> str:
    return th[theme][CR[token][theme]] if token in CR else th[theme][token]


def ratio(a: str, b: str) -> float:
    return float(contrast_check.contrast_ratio(verify.hex_to_rgb(a), verify.hex_to_rgb(b)))


def luma601(hex6: str) -> int:
    r, g, b = verify.hex_to_rgb(hex6)
    return int(0.299 * r + 0.587 * g + 0.114 * b)


def show(value: float) -> str:
    near = any(abs(value - bar) < 0.005 for bar in (3.0, 4.5, 7.0))
    return f"{value:.4f}" if near else f"{value:.2f}"


def over(top: str, under: str, alpha: float) -> str:
    """``top`` at ``alpha`` over ``under``, as the validity look dims a control (E30-D02 D3)."""
    t, u = verify.hex_to_rgb(top), verify.hex_to_rgb(under)
    return "#" + "".join(
        f"{round(a * alpha + b * (1 - alpha)):02X}" for a, b in zip(t, u, strict=True)
    )


def matrix(th: dict[str, dict[str, str]], registered: set[tuple[str, str]]) -> dict[str, Any]:
    """Section 1: every pair x theme against its role's bar, the reproductions and ring minima."""
    pairs: dict[str, dict[str, Any]] = {}
    fails: list[str] = []
    n = {"rows": 0, "gated": 0, "reported": 0, "registered": 0, "proposed": 0, "fail": 0}
    n.update({"repro": 0, "repro_fail": 0})
    for pid, element, fg, bg, role, repro in rows_txt(PAIRS_TXT):
        vals = {t: ratio(colour(th, t, fg), colour(th, t, bg)) for t in THEMES}
        bar = BAR.get(role)
        themes_gated = ("high-contrast",) if role.endswith("hc-text") else THEMES
        failing = [t for t in themes_gated if bar is not None and vals[t] < bar]
        n["rows"] += 1
        if role in GATED:
            n["gated"] += 1
            verdict = "PASS" if not failing else "FAIL: " + ", ".join(failing)
            if failing:
                n["fail"] += 1
                fails.append(f"contrast {pid}: {fg} on {bg} ({role}) under {bar} in {failing}")
            reg = "registered" if (fg, bg) in registered else "PROPOSED"
            n["registered" if reg == "registered" else "proposed"] += 1
        else:
            n["reported"] += 1
            reg = "—"
            if role.startswith("rejected"):
                verdict = (
                    "rejected by design — would FAIL: " + ", ".join(failing)
                    if failing
                    else "rejected by design (passes; not used)"
                )
            else:
                verdict = "reported, not gated"
        row: dict[str, Any] = {"element": element, "fg": fg, "bg": bg, "role": role}
        row.update({t: round(v, 2) for t, v in vals.items()})
        row.update({"verdict": verdict, "pairs": reg, "repro": repro})
        if repro != "—":
            n["repro"] += 1
            want = [v.strip() for v in repro.split("·")[0].split("/")]
            got = [f"{vals[t]:.2f}" for t in THEMES]
            row["reproduced"] = got == want
            if got != want:
                n["repro_fail"] += 1
                fails.append(f"reproduction off: {pid} expects {want}, got {got} ({repro})")
        pairs[pid] = row
    ring = {
        t: min(ratio(th[t]["color.focus.ring"], th[t][f"color.surface.{s}"]) for s in RING_TIERS)
        for t in THEMES
    }
    ring_min = {t: f"{v:.2f}" for t, v in ring.items()}
    if ring_min != RING_MIN:
        fails.append(f"CMP-039 ring minima not reproduced: {ring_min} vs {RING_MIN}")
    alpha = float(PRIM["opacity.disabled"]["$value"])
    composite = {}
    for t in THEMES:
        fill = over(th[t]["color.action.primary.default"], th[t]["color.surface.overlay"], alpha)
        label = over(th[t]["color.text.on-action"], fill, alpha)
        composite[t] = round(ratio(label, fill), 2)
    return {
        "pairs": pairs,
        "n": n,
        "fails": fails,
        "ring_min": ring_min,
        "composite": composite,
        "opacity_disabled": alpha,
    }


def cvd_rows(th: dict[str, dict[str, str]]) -> tuple[dict[str, Any], dict[str, Any]]:
    """Section 2's reported half: Delta E76 per deficiency and the Rec. 601 luma per token."""
    out: dict[str, Any] = {}
    for rid, what, a, b in rows_txt(CVD_TXT):
        per: dict[str, Any] = {"what": what, "a": a, "b": b}
        for t in THEMES:
            ha, hb = colour(th, t, a), colour(th, t, b)
            de: dict[str, Any] = {"normal": round(float(cvd.delta_e76(ha, hb)), 2)}
            for d in DEFICIENCIES:
                de[d] = round(float(cvd.delta_e76(cvd.simulate(ha, d), cvd.simulate(hb, d))), 2)
            de["under_jnd"] = ",".join(k for k, v in de.items() if isinstance(v, float) and v < JND)
            per[t] = de
        out[rid] = per
    luma = {tok: {t: luma601(th[t][tok]) for t in THEMES} for tok in LUMA_TOKENS}
    return out, luma


def token_files() -> dict[str, int]:
    names = {"primitives": "primitives", "dark": "semantic-dark", "light": "semantic-light"}
    names["hc"] = "semantic-hc"
    return {
        k: sum(
            isinstance(v, dict) and "$value" in v for v in verify.load(f"{f}.tokens.json").values()
        )
        for k, f in names.items()
    }


def memo_strings(text: str) -> dict[str, list[str]]:
    """CP-n / CD-n -> the quoted strings of its candidate column ("CP-n's string" resolved)."""
    out: dict[str, list[str]] = {}
    alias: dict[str, str] = {}
    for line in text.splitlines():
        m = re.match(r"^\| (C[DP]-\d+) +\|", line)
        if not m:
            continue
        row = cells(line)
        cell = row[3 if m[1].startswith("CP") else 2] if len(row) > 3 else ""
        out[m[1]] = quoted(cell)
        a = re.search(r"\b(CP-\d+)'s string", cell)
        if not out[m[1]] and a:
            alias[m[1]] = a[1]
    for k, v in alias.items():
        out[k] = out.get(v, [])
    return out


def d02_inventory(text: str) -> list[dict[str, Any]]:
    """E27-D02 section 7's rows (via its own tool): number, frame name, shows T2."""
    out = []
    for r in d02.rows(d02.section(text, 7)):
        names = d02.ticked(r[1]) if len(r) == 7 else []
        if len(names) == 1:
            out.append(
                {"num": int(r[0]), "name": " ".join(names[0].split()), "t2": "shows T2" in r[2]}
            )
    return out


def entries(text: str, kind: str) -> dict[str, tuple[int, int]]:
    """``### CMP-nnn`` / ``### SCR-nnn`` -> (first line, last line), 1-based, of each entry."""
    lines = text.splitlines()
    starts = [
        (i + 1, m[1])
        for i, ln in enumerate(lines)
        if (m := re.match(rf"^### ({kind}-\d{{3}}) ", ln))
    ]
    heads = [i + 1 for i, ln in enumerate(lines) if re.match(r"^#{2,3} ", ln)]
    out: dict[str, tuple[int, int]] = {}
    for first, key in starts:
        end = next((h - 1 for h in heads if h > first), len(lines))
        out.setdefault(key, (first, end))
    return out


def load_base() -> dict[str, Any]:
    th = {t: theme_colors(t) for t in THEMES}
    registered = set(re.findall(r'fg:\s*"([^"]+)",\s*bg:\s*"([^"]+)"', read(PAIRS_MJS)))
    data = matrix(th, registered)
    cvd_data, luma = cvd_rows(th)
    d02_text = read(D02_SPEC)
    cat14, cat15 = read(PLAN / "14-screens-catalogue.md"), read(PLAN / "15-component-catalogue.md")
    rbac = dict(re.findall(r'^\| `(rbac\.[a-z_]+)` +\| "([^"]+)"', read(D09_SPEC), MULTI))
    known = (
        set(theme_tokens("dark")) | set(theme_tokens("light")) | set(theme_tokens("high-contrast"))
    )
    return {
        "th": th,
        "registered": registered,
        "data": data,
        "cvd": cvd_data,
        "luma": luma,
        "files": token_files(),
        "d02": d02_text,
        "inv": d02_inventory(d02_text),
        "memo": memo_strings(read(MEMO)),
        "rbac": rbac,
        "known": known,
        "cat14": cat14,
        "cat15": cat15,
        "e14": entries(cat14, "SCR"),
        "e15": entries(cat15, "CMP"),
        "us11": read(PLAN / "11-user-stories.md"),
        "constitution": read(ROOT / "CONSTITUTION.md"),
        "handoff": read(HANDOFF),
        "handoff_exists": HANDOFF.exists(),
    }


class Out:
    """The gates' result: FAILs and WARNs as (code, message), and the counts the markers read."""

    def __init__(self) -> None:
        self.fails: list[tuple[str, str]] = []
        self.warns: list[tuple[str, str]] = []
        self.n: dict[str, Any] = {}

    def fail(self, code: str, msg: str) -> None:
        self.fails.append((code, msg))

    def warn(self, code: str, msg: str) -> None:
        self.warns.append((code, msg))


# --- copy checks shared by section 2 (the variant words) and section 6 (the deck) -----------------
BANNED = (
    (r"\breveal\w*", "reveal"),
    (r"Show \{label\}|Hide \{label\}", "Show / Hide {label}"),
    (r"\birreversibl\w*", "irreversible"),
    (r"\bpermanently\b", "permanently"),
    (r"\bstep[- ]?ups?\b", "step-up"),
    (r"\bre-?auth\w*", "re-authentication"),
    (r"\bBybit says\b", "Bybit says"),
    (r"(?<![\w/])n/a(?![\w/])", "n/a"),
)
EXPIRE = re.compile(r"\bexpir(?:e|es|ed|ing|y)\b", re.IGNORECASE)
CLOCK = re.compile(r"\{hh:mm(?::ss)?\}|(?<![\d:])\d{1,2}:\d{2}(?::\d{2})?(?![\d:])")
WITHDRAW_ON = re.compile(
    r"\b(?:withdraw(?:al|als)?|transfers?)\b(?:\s+(?:rights?|permissions?|flag))?\s*[:=]?\s*"
    r"(?:on|allowed|enabled|permitted|yes|true)\b",
    re.IGNORECASE,
)
WITHDRAW_GRANT = re.compile(
    r"\b(?:allows?|allowed|enables?|enabled|permits?|permitted|grants?|granted)\s+"
    r"(?:the\s+|a\s+|its\s+)?(?:withdraw\w*|transfer\w*|fund[- ]moving)",
    re.IGNORECASE,
)
NEGATION = re.compile(
    r"\b(?:never|neither|nor|no|not|without|cannot|refuse\w*)\b|n't", re.IGNORECASE
)
WITHDRAWAL_WORD = re.compile(r"\bwithdrawal\b", re.IGNORECASE)
OFF_WORD = re.compile(r"\boff\b", re.IGNORECASE)


def copy_checks(s: str, where: str, out: Out) -> None:
    """A product string: no banned word, every time UTC, OFF dated, withdrawal never allowed."""
    for pattern, word in BANNED:
        if re.search(pattern, s, re.IGNORECASE):
            out.fail("copy.banned", f"{where}: banned product word {word!r}")
    if EXPIRE.search(s) and "Bybit" not in s:
        out.fail("copy.banned", f"{where}: 'expire' names only Bybit's own expiry (AD-5)")
    for m in CLOCK.finditer(s):
        tail = s[m.end() : m.end() + 5]
        if not tail.startswith((" UTC", " left")):
            out.fail("copy.utc", f"{where}: a time without UTC: {m[0]!r}")
    off = (WITHDRAWAL_WORD.search(s) and OFF_WORD.search(s)) or re.search(r"\bOFF\b", s)
    if off and "verified" not in s:
        out.fail("copy.off", f"{where}: a withdrawal OFF without its verified time (AD-3, D3)")
    if WITHDRAW_ON.search(s):
        out.fail("withdraw", f"{where}: a withdrawal or transfer right drawn as allowed (C-2.8)")
    for m in WITHDRAW_GRANT.finditer(s):
        if not NEGATION.search(s[max(0, m.start() - 30) : m.start()]):
            out.fail(
                "withdraw", f"{where}: a withdrawal or transfer right granted (C-2.8): {m[0]!r}"
            )


# --- 2. AC2 carriers: the CMP-175 variant table (section 2.1) ------------------------------------
VARIANTS = (
    "verified",
    "trade-only",
    "read-only",
    "withdrawal-detected",
    "ip-missing",
    "ip-mismatch",
    "expiring",
    "expired",
)
CLASSES = ("time warning", "critical", "failed", "warning", "pass", "unknown", "info")
CLASS_GLYPH = {
    "pass": "check",
    "failed": "octagon",
    "critical": "octagon",
    "warning": "triangle",
    "time warning": "clock",
    "unknown": "dash",
    "info": "info",
}
GLYPHS = ("check", "octagon", "triangle", "clock", "dash", "lock", "info")


def pick(cell: str, vocab: tuple[str, ...]) -> str:
    low = norm(cell)
    return next((w for w in vocab if re.search(rf"(?<![\w-]){re.escape(w)}(?![\w-])", low)), "")


def ac2_gate(sec: dict[str, str], out: Out) -> None:
    out.n.update({"variants": 0, "variant_words": 0, "critical_rows": 0})
    tab = find_table(sec.get("2.1", ""), "variant", "word")
    if tab is None:
        out.fail(
            "ac2.table",
            "§2.1 has no CMP-175 table (Variant | Served source | Class | Glyph | Word | Mark)",
        )
        return
    head, body = tab
    iv, ic, ig, iw, im = (col(head, k) for k in ("variant", "class", "glyph", "word", "mark"))
    if min(iv, ic, iw, im) < 0:
        out.fail("ac2.table", f"§2.1's CMP-175 table lacks a column: {head}")
        return
    words: dict[str, str] = {}
    found: set[str] = set()
    for _raw, r in body:
        if len(r) <= max(iv, ic, ig, iw, im):
            out.fail("ac2.table", f"§2.1 row with {len(r)} cells: {r[:1]}")
            continue
        v = norm(r[iv])
        name = next((x for x in VARIANTS if v.startswith(x)), v)
        found.add(name)
        cls, glyph = pick(r[ic], CLASSES), pick(r[ig] if ig >= 0 else r[ic], GLYPHS)
        word = (quoted(r[iw]) or [""])[0]
        mark = norm(r[im])
        if not word:
            out.fail("ac2.word", f"{name}: no word of its own (AC2)")
        elif norm(word) in words:
            out.fail("ac2.word", f"{name} shares its word with {words[norm(word)]}: {word!r}")
        else:
            words[norm(word)] = name
        if not cls:
            out.fail("ac2.class", f"{name}: class {r[ic]!r} is none of {CLASSES}")
        elif glyph != CLASS_GLYPH[cls]:
            out.fail(
                "ac2.glyph",
                f"{name}: glyph {glyph or 'none'} is not its class's "
                f"({cls} → {CLASS_GLYPH[cls]}); no warning-class state takes the octagon",
            )
        if name == "withdrawal-detected" and cls != "critical":
            out.fail(
                "ac2.critical", "withdrawal-detected must be the critical, blocking class (AC3)"
            )
        if cls == "critical":
            out.n["critical_rows"] += 1
            if name != "withdrawal-detected":
                out.fail("ac2.critical", f"{name} is critical; only withdrawal-detected is")
            if not word.startswith("BLOCKED"):
                out.fail("ac2.critical", f"the critical word leads with BLOCKED (AC3): {word!r}")
            if not ("bold" in mark and "border" in mark):
                out.fail("ac2.mark", "the critical row lacks its bold + border mark (BQ-6)")
        elif "bold" in mark or "border" in mark:
            out.fail("ac2.mark", f"{name} ({cls}) carries the critical mark (bold + border)")
        if re.search(r"\bOFF\b", word) and cls != "pass":
            out.fail("ac2.off", f"{name}: 'OFF' only for a fresh pass (W-3): {word!r}")
        if word:
            copy_checks(word, f"§2.1 {name}", out)
    for x in VARIANTS:
        if x not in found:
            out.fail("ac2.missing", f"the ticket's variant {x} has no row in §2.1")
    if not out.n["critical_rows"]:
        out.fail("ac2.critical", "no critical row in §2.1 (AC3)")
    out.n.update({"variants": len(body), "variant_words": len(words)})


# --- 3. token bindings ---------------------------------------------------------------------------
TOKEN_RE = re.compile(
    r"`((?:color|space|size|radius|border|type|elevation|opacity|motion|font)\.[a-z0-9.*-]+)`"
)
MARKED_RE = re.compile(
    r"PROPOSED|G-row|\bG-\d+|\bDS-\d|not a token|no such token|does not exist|\bCR\b"
)
# `15`'s names that are not tokens (each replaced by an A-row; never in an Appendix A New cell)
EXPECTED_MISSING = (
    "color.status.success",
    "color.status.danger",
    "color.status.warning",
    "color.status.info",
    "font.mono",
    "color.text.warning",
    "color.text.muted",
    "color.callout.*",
    "motion.slide",
    "color.surface.admin-tint",
    "color.border.admin",
    "color.border.input",
    "space.pageheader.*",
)
DIMMING = re.compile(r"`(?:color\.text\.disabled|opacity\.disabled)`")
BOUNDARY = re.compile(r"\. |; |\||\n\n")


def known_token(tok: str, known: set[str]) -> bool:
    return any(k.startswith(tok[:-1]) for k in known) if tok.endswith(".*") else tok in known


def undimmed(text: str) -> list[str]:
    """Each dimming token in ``text`` must be negated in its clause (the validity look excepted)."""
    bad = []
    for m in DIMMING.finditer(text):
        start = max((b.end() for b in BOUNDARY.finditer(text, 0, m.start())), default=0)
        nxt = BOUNDARY.search(text, m.end())
        clause = text[start : nxt.start() if nxt else len(text)]
        if "validity" in clause.lower() or NEGATION.search(text[start : m.start()]):
            continue
        bad.append(" ".join(clause.split())[:90])
    return bad


def token_gate(spec: str, sec: dict[str, str], base: dict[str, Any], out: Out) -> None:
    bound: set[str] = set()
    missing: set[str] = set()
    for ln in spec.splitlines():
        for tok in TOKEN_RE.findall(ln):
            bound.add(tok)
            if not (
                known_token(tok, base["known"]) or tok in EXPECTED_MISSING or MARKED_RE.search(ln)
            ):
                missing.add(tok)
    for tok in sorted(missing):
        out.fail("tokens.unknown", f"token bound but unknown and unmarked: {tok}")
    scopes = [sec.get("10", "")]
    for key in [k for k in sec if "." not in k and k not in ("9", "A", "pre")]:
        scopes.extend(
            ln for ln in sec[key].splitlines() if ln.startswith("|") and re.search(r"\bT2\b", ln)
        )
    scopes += [
        ln
        for ln in sec.get("2.2", "").splitlines()
        if ln.startswith("|") and re.search(r"isabled|Off by policy", ln)
    ]
    dimmed = sorted({b for text in scopes for b in undimmed(text)})
    for b in dimmed:
        out.fail(
            "tokens.dimmed", f"a T2 or disabled look names a dimming token: {b!r} (E09-D09 §11)"
        )
    out.n.update({"tokens_bound": len(bound), "tokens_missing": len(missing)})


# --- 4. inventory and the board cap --------------------------------------------------------------
NOT_DRAWN = "not drawn — the text is binding; drawn on request"
BOARD_STATES = ("PENDING", "drawn")
MAX_BOARDS = 10  # the lever-4 cap (main-orchestrator, 2026-10-24 03:11Z); light twins <= a third
D03_PREFIXES = (
    "CMP-087",
    "Pattern",
    "SCR-016",
    "SCR-019",
    "SCR-079",
    "SCR-125",
    "SCR-126",
    "SCR-127",
    "SCR-128",
    "SCR-129",
)
AS_DRAWN_RE = re.compile(
    r"(?m)^- `(\d\d) ([a-z0-9-]+)` — board id `([0-9a-f]{8}(?:-[0-9a-f]{4}){3}-[0-9a-f]{12})` — "
    rf"`({re.escape(IMG)}/E27-D03-\d\d-[a-z0-9-]+\.png)` \(\d+ \u00d7 \d+\)$"
)
RENDERS = ("greyscale", "deuteranopia", "protanopia")  # BQ-16: the CMP-175 boards' CVD renders
CVD_BOARDS = ("01", "02")
HIFI_ROW = re.compile(r"^\| *(\d+) +\| *`([^`]+)` *\|")
T2_EXACT = "T2 per §10.1"


def board_drawn(num: str, export: str, s0: str, exists: Callable[[str], bool]) -> list[str]:
    """A drawn board row: one as-drawn item with its board id and a PNG that exists (E10's rule)."""
    hits = [m for m in AS_DRAWN_RE.finditer(s0) if m[1] == num]
    if len(hits) != 1:
        return [f"board {num}: drawn needs exactly one 'Boards as drawn' item with its board id"]
    png, bad = hits[0][4], []
    if not png.endswith("/" + export.rsplit("/", 1)[-1]):
        bad.append(f"board {num}: as drawn {png} is not the row's export {export}")
    if not exists(png):
        bad.append(f"board {num}: {png} does not exist")
    if num in CVD_BOARDS:
        bad += [
            f"board {num}: render {png[:-4]}-{r}.png does not exist (AC2)"
            for r in RENDERS
            if not exists(f"{png[:-4]}-{r}.png")
        ]
    return bad


def board_table(s0: str, out: Out, exists: Callable[[str], bool]) -> dict[str, dict[str, Any]]:
    boards: dict[str, dict[str, Any]] = {}
    tab = find_table(s0, "board", "frames", "state")
    if tab is None:
        out.fail(
            "board.table",
            "§0 has no board table (# | Board | Frames (E27-D02 §7) | Draws | "
            "Theme | Criterion | Export (planned) | State)",
        )
        return boards
    head, body = tab
    ib, ifr, ith, iex, ist = (col(head, k) for k in ("board", "frames", "theme", "export", "state"))
    if min(ib, ifr, ith, iex, ist) < 0:
        out.fail("board.table", f"§0's board table lacks a column: {head}")
        return boards
    for _raw, r in body:
        num = r[0] if r else ""
        if not re.fullmatch(r"\d\d", num) or len(r) <= max(ib, ifr, ith, iex, ist):
            continue
        state, name = r[ist], re.fullmatch(rf"`E27-D03 / {num} ([a-z0-9-]+)`", r[ib])
        if state not in BOARD_STATES and state != NOT_DRAWN:
            out.fail(
                "board.state",
                f"board {num}: State {state!r} is not PENDING, drawn or '{NOT_DRAWN}'",
            )
        if not name:
            out.fail("board.name", f"board {num}: {r[ib]!r}, `E27-D03 / {num} <slug>` expected")
        slug = name[1] if name else ""
        export = f"{IMG}/E27-D03-{num}-{slug}.png"
        if r[iex] != f"`{export}`":
            out.fail("board.name", f"board {num}: export {r[iex]!r}, `{export}` expected")
        theme = norm(r[ith])
        if theme not in ("dark", "light"):
            out.fail("board.theme", f"board {num}: theme {r[ith]!r}, dark or light expected")
        twin = re.search(r"twin of (\d\d)", r[ifr])
        if num in boards:
            out.fail("board.dup", f"board {num} listed twice")
        boards[num] = {
            "slug": slug,
            "theme": theme,
            "twin": twin[1] if twin else "",
            "frames": [" ".join(f.split()) for f in d02.FRAME_RE.findall(r[ifr])],
            "state": state,
            "export": export,
        }
        if state == "drawn":
            for p in board_drawn(num, export, s0, exists):
                out.fail("board.drawn", p)
    return boards


def inventory_gate(
    spec: str, sec: dict[str, str], base: dict[str, Any], out: Out, exists: Callable[[str], bool]
) -> None:
    inv = base["inv"]
    by_name = {f["name"]: f for f in inv}
    boards = board_table(sec.get("0", ""), out, exists)
    counted = {n: b for n, b in boards.items() if b["state"] in BOARD_STATES}
    twins = [n for n, b in counted.items() if b["theme"] == "light"]
    if len(counted) > MAX_BOARDS:
        out.fail("cap.boards", f"{len(counted)} boards, at most {MAX_BOARDS} (the 03:11Z cap)")
    if len(twins) * 3 > len(counted):
        out.fail("cap.twins", f"{len(twins)} light twins of {len(counted)} boards: over a third")
    on_board: dict[str, str] = {}
    for n, b in counted.items():
        if b["theme"] == "light":
            if counted.get(b["twin"], {}).get("theme") != "dark":
                out.fail(
                    "cap.twins", f"board {n}: a light board names its dark board, 'twin of NN'"
                )
            if b["frames"]:
                out.fail("board.twin", f"board {n}: a twin lists no frames of its own")
            if not b["slug"].endswith("-light"):
                out.warn("board.twin", f"board {n}: a twin's slug ends in -light")
            continue
        for f in b["frames"]:
            if f not in by_name:
                out.fail("inv.stray", f"board {n}: {f!r} is not an E27-D02 frame")
            elif f in on_board:
                out.fail("inv.board", f"{f!r} on boards {on_board[f]} and {n}")
            on_board.setdefault(f, n)
    hifi: dict[str, dict[str, Any]] = {}
    for key in [k for k in sec if "." not in k and k not in ("pre", "0", "A")]:
        for line in sec[key].splitlines():
            m = HIFI_ROW.match(line)
            name = " ".join(m[2].split()) if m else ""
            if not m or not d02.FRAME_RE.fullmatch(f"`{name}`"):
                continue
            if name in hifi:
                out.fail("inv.dup", f"{name!r}: two hi-fi rows")
                continue
            hifi[name] = {"num": int(m[1]), "board": cells(line)[-1], "row": line}
    not_drawn = 0
    for f in inv:
        h = hifi.get(f["name"])
        if h is None:
            out.fail("inv.missing", f"frame {f['num']} {f['name']!r} has no hi-fi row")
            continue
        if h["num"] != f["num"]:
            out.fail("inv.number", f"{f['name']!r}: row number {h['num']}, E27-D02's {f['num']}")
        bm, want = re.match(r"(\d\d)\b", h["board"]), on_board.get(f["name"])
        if bm and bm[1] != want:
            where = f"§0 draws it on {want}" if want else "§0 draws it on no board"
            out.fail("inv.board", f"frame {f['num']}: board cell {bm[1]}, but {where}")
        elif not bm and NOT_DRAWN in h["board"]:
            not_drawn += 1
            if want:
                out.fail("inv.board", f"frame {f['num']}: '{NOT_DRAWN}', but §0 draws it on {want}")
        elif not bm:
            out.fail(
                "inv.board",
                f"frame {f['num']}: board cell {h['board']!r} is neither a board "
                f"number nor '{NOT_DRAWN}'",
            )
        if f["t2"] and T2_EXACT not in h["row"]:
            out.fail(
                "t2.cite", f"frame {f['num']} shows T2 (E27-D02 §7): its row cites '{T2_EXACT}'"
            )
        elif not f["t2"] and T2_EXACT in h["row"]:
            out.warn("t2.extra", f"frame {f['num']} cites T2 but E27-D02 §7 draws no gated control")
    names = {" ".join(f.split()) for f in d02.FRAME_RE.findall(spec)}
    for s in sorted(n for n in names - set(by_name) if n.split(" / ")[0] in D03_PREFIXES):
        out.fail("inv.stray", f"frame name outside E27-D02's inventory: {s!r}")
    out.n.update(
        {
            "boards": len(counted),
            "light_twins": len(twins),
            "board_rows": len(boards),
            "frames_on_boards": len(on_board),
            "d02_frames": len(inv),
            "hifi_rows": len(hifi),
            "frames_not_drawn": not_drawn,
            "t2_frames": sum(f["t2"] for f in inv),
        }
    )


# --- 5. T2 ---------------------------------------------------------------------------------------
T2_SENTENCE = (
    "Every control that a view-as context, a permission, a grant, the environment or a known "
    "state blocks is E09-D09's T2"
)
LATER_LEGS = ("rbac.permission", "rbac.owner_only", "rbac.account", "rbac.env")
NOT_T2 = (
    ("busy", r"\bBusy\b"),
    ("outcome", r"\bOutcome\b"),
    ("availability", r"\bAvailability\b|\bAbsence\b"),
    ("the validity look", r"\bvalidity\b"),
    ("T4", r"\bT4\b"),
    ("T1", r"\bT1\b"),
    ("T3", r"\bT3\b"),
)
REASON_KEY = re.compile(r"^`((?:keys|accounts|rbac)\.[a-z_.]+)`$")
LEG_KEY = re.compile(r"`((?:keys|accounts|rbac)\.[a-z_.]+)`")


def t2_gate(spec: str, sec: dict[str, str], base: dict[str, Any], out: Out) -> None:
    s101 = sec.get("10.1", "")
    count = " ".join(spec.split()).count(T2_SENTENCE)  # a hard-wrapped paragraph counts too
    if count != 1:
        out.fail("t2.once", f"the T2 rule sentence appears {count} times (once, in §10.1)")
    elif T2_SENTENCE not in " ".join(s101.split()):
        out.fail("t2.once", "the T2 rule sentence is not in §10.1")
    va = s101.find("rbac.view_as")
    if va < 0 or any(0 <= s101.find(k) < va for k in LATER_LEGS):
        out.fail("t2.viewas", "§10.1 names the view-as leg (`rbac.view_as`) before every other leg")
    for tok in ("`color.text.tertiary`", "`color.text.secondary`"):
        if tok not in s101:
            out.fail("t2.tokens", f"§10.1 binds the T2 label and reason: {tok} is missing")
    used: set[str] = set()
    gated = 0
    tab = find_table(sec.get("10.2", ""), "legs", "components")
    if tab is None:
        out.fail(
            "t2.table",
            "§10.2 has no gated-set table (Control (operation) | Where | Legs in "
            "order → reason key | Rendering | Components)",
        )
    else:
        head, body = tab
        il, ir, ico = col(head, "legs"), col(head, "rendering"), col(head, "components")
        for raw, r in body:
            gated += 1
            label = (r[0] if r else "")[:48]
            if len(r) <= max(il, ir, ico) or min(il, ir, ico) < 0:
                out.fail("t2.table", f"gated row {label!r}: {len(r)} cells")
                continue
            if "CMP-079" not in r[ico] or "`lock`" not in r[ico]:
                out.fail(
                    "t2.lock",
                    f"gated row {label!r}: Components names CMP-079 and the "
                    "CMP-019 `lock` (G-T2.6)",
                )
            if not re.search(r"\b2a\b|\b2b\b|sentence form", r[ir]):
                out.fail("t2.render", f"gated row {label!r}: rendering 2a, 2b or the sentence form")
            if T2_EXACT not in raw:
                out.fail("t2.cite", f"gated row {label!r}: cites '{T2_EXACT}'")
            legs = [leg.strip() for leg in r[il].split(";")]
            if any(re.search(r"view-as|rbac\.view_as", leg) for leg in legs[1:]):
                out.fail("t2.viewas", f"gated row {label!r}: the view-as leg comes first")
            used.update(LEG_KEY.findall(r[il]))
    s103 = sec.get("10.3", "")
    for name, pattern in NOT_T2:
        if not re.search(pattern, s103):
            out.fail("t2.notlist", f"§10.3 (what is NOT T2) lacks {name}")
    reasons: dict[str, str] = {}
    for key in ("10", "12"):
        for _head, body in tables(sec.get(key, "")):
            for _raw, r in body:
                m = REASON_KEY.match(r[0]) if r else None
                if not m or len(r) < 2:
                    continue
                s = (quoted(r[1]) or [""])[0]
                if m[1] in reasons and reasons[m[1]] != s:
                    out.fail("key.dup", f"{m[1]}: two strings")
                reasons[m[1]] = s
                if len(s) > 60 or not s.endswith(".") or re.search(r"[.!?] [A-Z]", s):
                    out.fail(
                        "key.form",
                        f"{m[1]}: one sentence of at most 60 characters with a "
                        f"full stop ({len(s)}): {s!r}",
                    )
                want = base["rbac"].get(m[1])
                if m[1].startswith("rbac.") and s != want:
                    out.fail("key.rbac", f"{m[1]}: {s!r} is not E09-D09 §3.1's {want!r}")
                copy_checks(s, m[1], out)
    for key in sorted(used - set(reasons)):
        if not (key.startswith("rbac.") and key in base["rbac"]):
            out.fail("key.missing", f"the gated set uses {key}, and no reason-key row gives it")
    out.n.update({"t2_rule": count, "gated_rows": gated, "reason_keys": len(reasons)})
    out.n["reason_keys_e27"] = sum(not k.startswith("rbac.") for k in reasons)


# --- 6. the copy deck (section 12) ---------------------------------------------------------------
DECK_ID = re.compile(r"^e27\.[a-z0-9]+(?:\.[a-z0-9_{}-]+)+$")
STATUSES = ("unchanged", "refined", "new", "consumed")
API = ROOT / "services" / "api" / "candleviewer"
NAMED: dict[str, Path] = {
    "D02": D02_SPEC,
    "MEMO": MEMO,
    "PROT": DESIGN / "research" / "e27-d01-session-protocol.md",
    "E05F": DESIGN / "E05" / "E05-D02-form-controls.md",
    "GATE": ROOT / ".claude" / "rules" / "32-design-specs.md",
    "ADR9": PLAN / "27-adrs" / "ADR-0009-secrets-and-key-management.md",
    "TM": ROOT / "docs" / "security" / "threat-models" / "E27-accounts.md",
    "RB": ROOT / "docs" / "ops" / "runbooks" / "key-selfcheck.md",
    "CON": ROOT / "CONSTITUTION.md",
    "SYS": API / "net" / "system_topic.py",
    "ACT": API / "audit" / "actions.py",
    "SU": API / "api" / "step_up.py",
    "ASU": API / "auth" / "step_up.py",
    "REV": API / "ws" / "revocation.py",
    "MX": ROOT / "services" / "api" / "tests" / "contract" / "rbac" / "matrix.yaml",
    "SECR": ROOT / ".claude" / "rules" / "50-security.md",
    # the security digest's short keys for merged specs (the spec's Key lists them)
    "D06": DESIGN / "E09" / "E09-D06.md",
    "D09": D09_SPEC,
    "E09D02": DESIGN / "E09" / "E09-D02.md",
    "E30D02": DESIGN / "E30" / "E30-D02.md",
    "E42D01": DESIGN / "research" / "e42-admin.md",
    "E42D02": DESIGN / "E42" / "E42-D02.md",
}
KEYS_ALT = (
    r"D02|D06|D09|MEMO|PROT|E05F|GATE|ADR9|TM|RB|CON|SYS|ACT|SU|ASU|REV|MX|SECR|E09D02|E30D02"
    r"|E42D01|E42D02|E\d\d-D\d\d|E\d\d\.json|\d\d"
)


def key_path(key: str) -> Path | None:
    """A cite key of the spec's Key paragraph -> its file (None when the key names no file)."""
    if key in NAMED:
        return NAMED[key]
    if re.fullmatch(r"\d\d", key):
        return next((p for p in sorted(PLAN.glob(f"{key}-*")) if p.is_file()), None)
    if re.fullmatch(r"E\d\d-D\d\d", key):
        return DESIGN / key[:3] / f"{key}.md"
    if re.fullmatch(r"E\d\d\.json", key):
        return PLAN / "backlog" / key
    return None


def deck_gate(sec: dict[str, str], base: dict[str, Any], out: Out) -> None:
    ids: set[str] = set()
    by_status = dict.fromkeys(STATUSES, 0)
    for head, body in tables(sec.get("12", "")):
        istr, ist = col(head, "string"), col(head, "status")
        if min(istr, ist) < 0:
            continue
        for _raw, r in body:
            tid = d02.ticked(r[0]) if r else []
            if not tid or not tid[0].startswith("e27.") or len(r) <= max(istr, ist):
                continue
            eid, strings = tid[0], quoted(r[istr])
            if not DECK_ID.match(eid) or eid in ids:
                out.fail("deck.id", f"{eid}: a unique e27.{{screen}}.{{element}}[.{{state}}] id")
            ids.add(eid)
            if not strings:
                out.fail("deck.string", f"{eid}: no quoted string")
            status = (r[ist].split("·")[0].split() or [""])[0].lower()
            if status not in STATUSES:
                out.fail("deck.status", f"{eid}: status {status!r} is none of {STATUSES}")
                continue
            by_status[status] += 1
            if status == "unchanged":
                seeds = re.findall(r"\bC[DP]-\d+\b", r[ist])
                pool = [s for k in seeds for s in base["memo"].get(k, [])]
                if not seeds:
                    out.fail(
                        "deck.unchanged", f"{eid}: an unchanged row names its CD-n / CP-n seed"
                    )
                for s in strings:
                    if seeds and s not in pool:
                        out.fail(
                            "deck.unchanged",
                            f"{eid}: not byte-equal to {'/'.join(seeds)} in the memo: {s[:48]!r}",
                        )
            if status == "consumed":
                m = re.search(rf"(?<![\w-])({KEYS_ALT})(?::\d+)?", r[ist].split("·", 1)[-1])
                path = key_path(m[1]) if m else None
                if path is None or not path.is_file():
                    out.warn("deck.consumed", f"{eid}: its source names no file; not checked")
                else:
                    text = read(path)
                    for s in strings:
                        if s not in text:
                            out.fail(
                                "deck.consumed",
                                f"{eid}: not verbatim in "
                                f"{path.relative_to(ROOT).as_posix()}: {s[:48]!r}",
                            )
            for s in strings:
                copy_checks(s, eid, out)
    if not ids:
        out.fail("deck.table", "§12 has no keyed deck rows (Id | Where | String | Status · source)")
    out.n.update({"deck_rows": len(ids), "deck_by_status": by_status})


# --- 7. Appendix A: the `15` and `14` edits, old -> new -----------------------------------------
IN_FLIGHT = dict.fromkeys(("CMP-044", "CMP-178"), "E42-D03's boards PR (`design/e42-d03-boards`)")
REVEAL_AFFORDANCE = re.compile(
    r"onToggleReveal|\bautoHideMs\b|`revealed\??|\brevealed\??:|`copyable\??|\bcopyable\??:"
    r"|Show \{label\}|Hide \{label\}|\bShow secret\b|\bHide secret\b|\bRevealed\b"
    r"|\bAutoHideCountdown\b|\bCopyable\b|icon/eye"
)
REVEAL_WORD = re.compile(r"\breveal\w*", re.IGNORECASE)
POINTER_NEW = re.compile(r"^`*- \*\*Hi-fi \(E27-D03[^)]*\):\*\* ")


def code_span(cell: str) -> tuple[str, str] | None:
    """(the code span's text, the note after it) of an Old / New cell, or None if unquoted."""
    m = re.match(r"^(``?)(?!`)(.*?)(?<!`)\1(?!`)(.*)$", cell, re.DOTALL)
    if not m:
        return None
    inner = m[2][1:-1] if len(m[1]) == 2 and m[2][:1] == " " and m[2][-1:] == " " else m[2]
    return inner, m[3].strip()


def appendix_gate(sec: dict[str, str], base: dict[str, Any], out: Out) -> None:
    n = {"15": 0, "14": 0}
    for head, body in tables(sec.get("A", "")):
        h0 = head[0].lower() if head else ""
        doc = ""
        if "entry" in h0 and "field" in h0:
            doc = "15"
        elif "14" in h0 and "edit" in h0:
            doc = "14"
        iold, inew = col(head, "old"), col(head, "new")
        if not doc or min(iold, inew) < 0:
            continue
        lines = base[f"cat{doc}"].splitlines()
        for raw, r in body:
            m = re.match(r"(CMP-\d{3}|SCR-\d{3})\b", r[0] if r else "")
            if not m or len(r) <= max(iold, inew):
                continue
            first, key, old, new = r[0], m[1], r[iold], r[inew]
            ent = base[f"e{doc}"].get(key)
            if ent is None:
                out.fail("appx.entry", f"{first}: no `{doc}` entry {key}")
                continue
            n[doc] += 1
            cite = re.search(rf"`{doc}:(\d+)", first)
            if key in IN_FLIGHT:
                out.warn(
                    "appx.inflight",
                    f"{first}: {IN_FLIGHT[key]} proposes edits here — re-read "
                    "and re-base if it lands first (GATE R6)",
                )
            span = code_span(new)  # CMP-034's reveal words: the whole-document gate (§7c)
            if doc == "15" and span:
                for tok in TOKEN_RE.findall(span[0]):
                    if not known_token(tok, base["known"]) and not MARKED_RE.search(raw):
                        out.fail("tokens.unknown", f"{first}: New binds {tok}, which is no token")
            if old.startswith("—"):
                if doc == "14" and not POINTER_NEW.match(new):
                    out.fail(
                        "appx.pointer",
                        f"{first}: a `14` insert is one content-only "
                        "'- **Hi-fi (E27-D03):** …' line",
                    )
                if cite and not ent[0] <= int(cite[1]) <= ent[1] + 1:
                    out.warn(
                        "appx.drift",
                        f"{first}: line {cite[1]} is outside {key} ({ent[0]}\u2013{ent[1]})",
                    )
                continue
            span_old = code_span(old)
            if span_old is None:
                out.warn("appx.described", f"{first}: the Old text is described, not quoted")
                continue
            frag = span_old[0].removeprefix("… ").removesuffix(" …")
            found = [i + 1 for i in range(ent[0] - 1, ent[1]) if frag in lines[i]]
            if not found:
                out.fail(
                    "appx.gone",
                    f"{first}: the Old text is gone from {key} (re-read the base): {frag[:48]!r}",
                )
            elif len(found) > 1:
                out.fail(
                    "appx.ambiguous",
                    f"{first}: the Old text occurs {len(found)} times in {key} (lengthen it)",
                )
            elif cite and int(cite[1]) != found[0]:
                out.warn(
                    "appx.drift", f"{first}: cited line {cite[1]}, the text is now at {found[0]}"
                )
    if not n["15"]:
        out.fail(
            "appx.missing", "Appendix A has no `15` rows (Entry · field | Old (verbatim) | New)"
        )
    out.n.update({"appendix_15": n["15"], "appendix_14": n["14"]})


# --- 7b. frame-level gates: K1-K15 read the frame rows (standing rule A2, 2026-10-25 00:32Z) -----
# The destructive confirms (K4, K5): frame -> the copy key of the consequence it states before the
# press; every one also carries the ask line, `e27.shared.ask`, its step-up (§7's confirms table).
DESTRUCTIVE = {
    5: "e27.scr129.revoke.not_last",
    34: "e27.scr127.stage2.lead",
    49: "e27.scr129.revoke.not_last",
    50: "e27.scr129.revoke.last",
    51: "e27.scr129.revoke.last",
    54: "e27.scr129.disable.stops",
    55: "e27.scr129.disable.stops",
    56: "e27.scr129.unknown.dead",
    58: "e27.scr129.delete.flat",
    59: "e27.scr129.delete.exposure",
}
STEP_UP_KEY = "e27.shared.ask"
TYPED_KEY = "e27.scr129.typed"
# K4, K5: the drawn row itself carries the consequence (its deck string, placeholders filled), the
# ask line and, at rung 3, the typed label - or opens "As frame N" / "Frame N's dialog" on a frame
# that is gated for the same element (that frame's own FAIL speaks for both)
INHERIT = re.compile(r"^(?:As frame (\d+)\b|Frame (\d+)'s dialog\b)")
ASK_DRAWN = re.compile(r"\bthe (?:stamped |served )?ask\b|\bask line\b|\bits served ask\b")
TYPED_DRAWN = re.compile(r"\bthe typed label\b")
PLACEHOLDER_RE = re.compile(r"\{[a-z_0-9]+\}")
# K8 / G7 (r2o): a gated frame that E27-D02 names, or its class names, as a view-as frame draws
# `rbac.view_as` as its first leg - every gated frame, read from the inventory, never a list
VIEWAS_NAMED = re.compile(r"\bview(?:ing)?[- ]as\b", re.IGNORECASE)
# K8: the row's prose never puts the view-as leg after another
VIEWAS_LATE = re.compile(
    r"view-as leg\b[^.;|]*?\b(?:after|second|last|later|then)\b", re.IGNORECASE
)
CONFIRM_BUTTON = re.compile(
    r"\[(?:Revoke|Disable|Delete|Flatten first|Verify and switch)\b[^\]…]*\]"
)
# K12: an environment badge (CMP-075, a "· LIVE" title, a group head); every frame whose row names
# one, or whose title or heading names an account, keeps it (not a fixed list)
ENV_RE = re.compile(
    r"CMP-075|· (?:LIVE|DEMO)\b|\b(?:LIVE|DEMO) \(\d+\)|env-(?:live|demo)|\b(?:LIVE|DEMO) pill\b"
    r"|Attention: (?:LIVE|DEMO)\b"
)
# K12: a frame that draws an attention-strip string ("Attention: ...") draws its environment (the
# item's LIVE pill, or the environment after "Attention:"): an environment frame by that string alone
STRIP_DRAWN = re.compile(r"\"Attention:")
# K11: the compromise card's five steps in C-12.12's order (D9; `CON:824-825`)
COMPROMISE = "SCR-128 / mark as compromised: the ordered card"
STEPS = ("Freeze", "Delete", "Revoke", "Rotate", "Replace")
STEP_RE = re.compile(r'(?:: |· )([1-9]) "([A-Z][a-z]+)')
# K1: a control that shows or copies key material, or a key id longer than `...` plus 4
SHOW_MATERIAL = re.compile(
    r"\[(?:Show|Hide|Reveal|Unmask)\b[^\]]*\]|\[Copy\b[^\]]*\b(?:key|secret)\b[^\]]*\]"
    r"|\.\.\.[A-Za-z0-9]{4} *\[Copy\]|\b(?:show|reveal|copy|unmask|display)(?:s|ed|ing)? +"
    r"(?:the +)?(?:full +|whole +|plaintext +)?(?:API +)?(?:key|secret)s?\b"
    r"(?! (?:id|list|row|step))"
    r"|icon/eye|\bplaintext +(?:key|secret)",
    re.IGNORECASE,
)
MASK_TAIL = re.compile(r"([A-Za-z0-9]?)\.\.\.([A-Za-z0-9{}_]+)")
# K1: a plaintext-like value - a 16+ character run that is not a word, a snake_case or a camelCase
# name (two digits, or camel segments under four letters on average, or one 16+ letter segment),
# and any key / key-id value with a digit or an inner capital that is not `...` plus 4
LONG_RUN = re.compile(r"(?<![A-Za-z0-9_])[A-Za-z0-9_]{16,}(?![A-Za-z0-9_])")
CAMEL = re.compile(r"[A-Z]?[a-z]+|[A-Z]+(?![a-z])|[0-9]+")
ID_VALUE = re.compile(r"\b(?:API key|[Kk]ey(?: id)?)[ :]+`?([A-Za-z0-9][A-Za-z0-9_\-]{5,})")
# K9: an exit drawn gated
GATE_WORD = (
    r"(?:in the validity look|T2\b|`?aria-disabled|disabled\b|gated\b|locked\b|led by the `lock`"
    r"|greyed|dimmed)"
)
EXIT_GATED = re.compile(
    r"(?:\[(?:Cancel|Close(?: card)?|Back)\]|\b(?:Cancel|Close|Back)\b|`Esc`)"
    rf"(?: *\([^)]*?{GATE_WORD}[^)]*\)|(?: *\([^)]*\))? *(?:is +|stays +|becomes +|drawn +)?"
    rf"{GATE_WORD}|(?: *\([^)]*\))?(?: +[a-z]+)?, +(?:[a-z]+ +)?{GATE_WORD})",
    re.IGNORECASE,
)
EXIT_CONTROL = re.compile(r"^(?:\[?(?:Cancel|Close|Back)\b|`?Esc`?)", re.IGNORECASE)
# r1o / r2o (the orchestrator's text rounds 1 and 2): the gates read every clause of every cell of
# a frame row here, and every clause of every line of the spec and the hand-off in §7c. A clause
# ends at a sentence stop, a semicolon, a cell, a " · " or a " — ".
CLAUSE = re.compile(r"(?<=[.;!?])\s+|\||\s·\s|\s—\s")
NEG_BEFORE = re.compile(
    r"(?:\b(?:no|never|not|without|nor|neither)\b|n't)(?:\s+[^\s,;]+){0,2}\s*$", re.IGNORECASE
)
SENTENCE = re.compile(r"(?<=[.;!?])\s+|\|")
NEG_IN = re.compile(r"\b(?:no|not|never|without|absent)\b", re.IGNORECASE)
# K1: a bare id - eight or more letters and digits, both present, outside a name, a token or a cite
BARE_ID = re.compile(
    r"(?<![\w.\-/:#{])(?=[A-Za-z0-9]*[0-9])(?=[A-Za-z0-9]*[A-Za-z])[A-Za-z0-9]{8,}(?![\w\-])"
)
# K1 / K2: a control that shows or copies a key or a secret field, or a toggle on one; CMP-033's
# copy of the egress IP is the one copy control a key screen draws (D6, KV-I11)
SHOW_CONTROL = re.compile(
    r"\b(?:show|hide|unmask|eye|visibility)(?: */ *(?:show|hide))?[ -]+"
    r"(?:toggle|button|control|icon|switch|link)s?\b",
    re.IGNORECASE,
)
TOGGLE_NOUN = re.compile(r"\b(?:a|an|the|its|with|one)\s+(?:\w+\s+)?toggles?\b", re.IGNORECASE)
COPY_CONTROL = re.compile(
    r"\[Copy\b[^\]]*\]|\bCopy\b(?! keys)"
    r"|\bcop(?:y|ies)[ -]+(?:control|button|icon|action|affordance)s?\b"
    r"|\bcopyable\b|\bcopy-to-clipboard\b",
    re.IGNORECASE,
)
FIELD_CUE = re.compile(
    r"\bAPI (?:key|secret)\b|\bsecrets?\b|\bkey (?:well|field|id)s?\b|\bwrite-only\b|CMP-201"
    r"|CMP-034|\.\.\.[A-Za-z0-9]{4}\b|\bmasked\b|\bfields?\b|\bwells?\b",
    re.IGNORECASE,
)
IP_WORD = re.compile(
    r"\b(?:203\.0\.113|198\.51\.100|192\.0\.2)\.\d+|\begress\b|\baddress\b|\ballowlist\b"
    r"|CMP-033|\bIP\b",
    re.IGNORECASE,
)
# K3: a withdrawal or transfer right drawn as a control (a toggle, a switch, a checkbox)
WITHDRAW_CONTROL = re.compile(
    r"\b(?:withdraw\w*|transfer\w*|fund[- ]moving)(?:\s+(?:and|or)\s+transfer\w*)?"
    r"(?:\s+(?:right|permission|flag)s?)?\s+(?:toggle|switch|checkbox|control|button)(?:es|s)?\b"
    r"|\b(?:toggle|switch|checkbox)(?:es|s)?\s+(?:for\s+|of\s+)?(?:the\s+|a\s+|its\s+)?"
    r"(?:withdraw\w*|transfer\w*)",
    re.IGNORECASE,
)
# K3: a withdrawal "OFF" (in any case) carries its verified time in the same string or item
OFF_DRAWN = re.compile(r"\boff\b", re.IGNORECASE)
WITHDRAW_NEAR = re.compile(r"\b(?:withdraw\w*|transfer\w*)", re.IGNORECASE)
VERIFIED_AT = re.compile(r"\bverified\b[^\"|;]{0,24}?(?:\{hh:mm(?::ss)?\}|\d{1,2}:\d{2})")
# K6: a frame that is not gated draws no lock and no RbacGate (§10.3: "never locked")
LOCK_DRAWN = re.compile(
    r"`lock`|\bCMP-079\b|\bRbacGate\b|\b(?:a|the|its) lock\b|\block (?:glyph|icon)s?\b"
)
# K4: while the consequence summary loads the confirm is not in the DOM - never drawn disabled
CONFIRM_SHOWN = re.compile(
    r"\bconfirm\b[^.;|]*?\b(?:disabled|aria-disabled|greyed|dimmed|inert|rendered|drawn|shown)\b",
    re.IGNORECASE,
)
LOADING_WORD = re.compile(r"\b(?:loading|loads|summary|Reading what)\b", re.IGNORECASE)
# K12: a frame whose title or heading names an account names its environment (C-2.11)
ACCOUNT_TITLE = re.compile(
    r"(?:\btitle|`h[123]`)(?: reads)? +\"(?=[^\"]*\b(?:Main|sub_00\d|demo-1)\b)[^\"]*\""
)
# the in-flight E42-D03 boards PR is named by its branch only: no sha pin and no quote (BQ-11)
INFLIGHT_NAME = re.compile(r"E42-D03's boards PR|design/e42-d03-boards")
SHORT_SHA = re.compile(
    r"(?<![0-9A-Za-z])(?=[0-9a-f]*[0-9])(?=[0-9a-f]*[a-f])[0-9a-f]{7,64}(?![0-9A-Za-z])"
)


def negated(clause: str, m: re.Match[str]) -> bool:
    return bool(NEG_BEFORE.search(clause[: m.start()]) or NEG_IN.search(m[0]))


def clause_spans(text: str) -> list[tuple[int, int]]:
    """The (start, end) of every clause of ``text`` (CLAUSE's boundaries)."""
    spans, at = [], 0
    for m in CLAUSE.finditer(text):
        spans.append((at, m.start()))
        at = m.end()
    return [*spans, (at, len(text))]


def control_spans(text: str, field_row: bool = False, negate: bool = True) -> list[tuple[int, int]]:
    """K1 / K2: show, copy and toggle controls on a key or a secret field, clause by clause."""
    spans: list[tuple[int, int]] = []
    for a, b in clause_spans(text):
        clause = text[a:b]
        cued = field_row or FIELD_CUE.search(clause) is not None
        found = list(SHOW_CONTROL.finditer(clause))
        if cued:
            found += list(TOGGLE_NOUN.finditer(clause))
            found += [
                m for m in COPY_CONTROL.finditer(clause) if copies_a_field(clause, m, field_row)
            ]
        spans += [
            (a + m.start(), a + m.end()) for m in found if not (negate and negated(clause, m))
        ]
    return spans


def field_controls(text: str, field_row: bool = False) -> list[str]:
    return [text[a:b] for a, b in control_spans(text, field_row)]


def copies_a_field(clause: str, m: re.Match[str], field_row: bool) -> bool:
    """A copy control belongs to the nearest cue before it (else after it): the IP or a field."""
    before = clause[: m.start()]
    ip = [x.end() for x in IP_WORD.finditer(before)]
    cue = [x.end() for x in FIELD_CUE.finditer(before)]
    if ip or cue:
        return max(cue, default=-1) > max(ip, default=-1)
    after = clause[m.end() :]
    ip_a = IP_WORD.search(after)
    cue_a = FIELD_CUE.search(after)
    if ip_a or cue_a:
        return ip_a is None or (cue_a is not None and cue_a.start() < ip_a.start())
    return field_row


def off_spans(raw: str, negate: bool = True) -> list[tuple[int, int]]:
    """K3: a withdrawal OFF (any case) without its verified time in its own string or item."""
    spans: list[tuple[int, int]] = []
    at = 0
    for cell in raw.split("|"):
        for m in OFF_DRAWN.finditer(cell):
            if negate and NEG_BEFORE.search(cell[max(0, m.start() - 30) : m.start()]):
                continue
            if cell.count('"', 0, m.start()) % 2:  # inside a quoted string: that string
                start = cell.rfind('"', 0, m.start())
                end = cell.find('"', m.end())
                seg = cell[start : end if end >= 0 else len(cell)]
                lead = cell[max(0, start - 40) : start]
            else:  # outside: to the item's end
                stop = re.search(r"[;|]|\.\s", cell[m.end() :])
                seg = cell[m.start() : m.end() + (stop.start() if stop else len(cell))]
                lead = cell[max(0, m.start() - 60) : m.start()]
            if WITHDRAW_NEAR.search(lead + seg) and not VERIFIED_AT.search(seg):
                spans.append((at + m.start(), at + m.end()))
        at += len(cell) + 1
    return spans


def loading_confirm(text: str) -> list[str]:
    """K4: the confirm drawn present or disabled while the consequence summary loads."""
    bad: list[str] = []
    for clause in SENTENCE.split(text):
        if not LOADING_WORD.search(clause):
            continue
        bad += [m[0][:60] for m in CONFIRM_SHOWN.finditer(clause) if not negated(clause, m)]
    return bad


# K13: a standalone number (no id, date, token or rule digit) and a contrast / Delta E value
NUM = re.compile(r"(?<![\w.\-=`/:#–])\d+(?:\.\d+)?(?![\w`\-–]|\.\d)")
TWO_DP = re.compile(r"(?<![\w.\-=`/:#])\d{1,2}\.\d{2}(?![\d.])")
QUANTITY = re.compile(r"(?:long|short) $")


def frame_rows(sec: dict[str, str]) -> dict[int, dict[str, Any]]:
    """Every hi-fi frame row by D02 number: its raw line, cells, header and named columns."""
    out: dict[int, dict[str, Any]] = {}
    for key in [k for k in sec if "." not in k and k not in ("pre", "0", "A")]:
        for head, body in tables(sec[key]):
            ic, ik, ih = col(head, "class"), col(head, "copy keys"), col(head, "hi-fi")
            for raw, r in body:
                m = HIFI_ROW.match(raw)
                name = " ".join(m[2].split()) if m else ""
                if not m or not d02.FRAME_RE.fullmatch(f"`{name}`"):
                    continue
                out.setdefault(
                    int(m[1]),
                    {
                        "raw": raw,
                        "name": name,
                        "cls": r[ic] if 0 <= ic < len(r) else "",
                        "keys": r[ik] if 0 <= ik < len(r) else "",
                        "hifi": r[ih] if 0 <= ih < len(r) else "",
                        "cells": r,
                    },
                )
    return out


def drawn(string_: str) -> re.Pattern[str] | None:
    """A deck string as the frame draws it: each ``{placeholder}`` a filled fixture value."""
    parts = PLACEHOLDER_RE.split(" ".join(string_.split()))
    if not "".join(parts).strip():
        return None
    plural = re.compile(r"(?<=[a-z])s(?![A-Za-z0-9])")  # "{k} running algos" draws "1 running algo"
    return re.compile(r".{1,40}?".join(plural.sub("s?", re.escape(x)) for x in parts))


def plaintext_like(run: str) -> bool:
    """K1: a 16+ character run that reads as key material rather than a word or a name."""
    if sum(c.isdigit() for c in run) >= 2:
        return True
    for part in (x for x in run.split("_") if len(x) >= 16):
        segs = CAMEL.findall(part)
        if not segs or max(map(len, segs)) >= 16 or sum(map(len, segs)) / len(segs) < 4:
            return True
    return False


def deck_ids(sec: dict[str, str]) -> dict[str, str]:
    """§12's keyed strings: id -> its first quoted string."""
    ids: dict[str, str] = {}
    for head, body in tables(sec.get("12", "")):
        istr = col(head, "string")
        for _raw, r in body:
            tid = d02.ticked(r[0]) if r else []
            if tid and istr >= 0 and len(r) > istr:
                ids.setdefault(tid[0], (quoted(r[istr]) or [""])[0])
    return ids


def reason_keys(sec: dict[str, str], base: dict[str, Any]) -> set[str]:
    keys = set(base["rbac"])
    for key in ("10", "12"):
        for _head, body in tables(sec.get(key, "")):
            keys.update(m[1] for _raw, r in body if r and (m := REASON_KEY.match(r[0])))
    return keys


def k13_numbers(spec: str, out: Out) -> None:
    """K13: the number a marker follows is the marker's value; a two-decimal value has a marker."""
    markers = list(MARKER.finditer(spec))
    prev, checked = 0, 0
    for m in markers:
        window = spec[max(prev, m.start() - 160) : m.start()]
        prev = m.end()
        nums = list(NUM.finditer(window))
        want = number(m[2])
        if not nums or want is None:
            continue
        checked += 1
        have = float(nums[-1][0])
        if abs(have - want) >= 0.006:
            out.fail(
                "k13.number",
                f"the spec reads {nums[-1][0]} before marker {m[1]}={m[2]}: not the tool's number",
            )
    spans = [(m.start(), m.end()) for m in markers]
    unmarked = 0
    for m in TWO_DP.finditer(spec):
        if any(a <= m.start() < b for a, b in spans):
            continue
        if QUANTITY.search(spec[max(0, m.start() - 6) : m.start()]):
            continue
        nxt = next((mk for mk in markers if mk.start() >= m.end()), None)
        gap = spec[m.end() : nxt.start()] if nxt else ""
        if nxt is None or len(gap) > 120 or NUM.search(gap):
            unmarked += 1
            line = spec.count("\n", 0, m.start()) + 1
            out.fail("k13.number", f"line {line}: {m[0]} carries no audit marker (from --json)")
    out.n.update({"numbers_before_markers": checked, "numbers_unmarked": unmarked})


def viewas_gate(sec: dict[str, str], out: Out) -> None:
    """K8: a §10.2 control the view-as session reaches as T2 `rbac.view_as` leads with that leg."""
    gated = find_table(sec.get("10.2", ""), "legs")
    for head, body in tables(sec.get("10.2", "")):
        if not head or not head[0].lower().startswith("session") or gated is None:
            continue
        ghead, gbody = gated
        il = col(ghead, "legs")
        for _raw, r in body:
            if not r or "viewing as" not in r[0].lower():
                continue
            for i in [i for i in range(1, min(len(r), len(head))) if "`rbac.view_as`" in r[i]]:
                want = set(re.findall(r"[a-z]+", head[i].lower())) - {"and", "or", "the"}
                hits = [
                    g
                    for _graw, g in gbody
                    if g and want <= set(re.findall(r"[a-z]+", g[0].lower())) and len(g) > il
                ]
                if not hits:
                    out.fail(
                        "t2.viewas", f"§10.2: no gated row for {head[i]!r}, which view-as locks"
                    )
                for g in hits:
                    legs = LEG_KEY.findall(g[il])
                    if not legs or legs[0] != "rbac.view_as":
                        out.fail(
                            "t2.viewas",
                            f"§10.2 {g[0][:40]!r}: view-as reaches it, and its legs do not start "
                            f"with the view-as leg: {legs[:2]}",
                        )


def frame_gate(spec: str, sec: dict[str, str], base: dict[str, Any], out: Out) -> None:
    """K1, K3-K9 and K11-K13 on every frame row (K2 is ``reveal``, K10 ``ac2.*``, K14-15 gate 4)."""
    rows = frame_rows(sec)
    deck = deck_ids(sec)
    reasons = reason_keys(sec, base)
    t2_frames = {n for n, r in rows.items() if T2_EXACT in r["cls"]}
    t2_frames |= {f["num"] for f in base["inv"] if f["t2"] and f["num"] in rows}
    inv_names = {f["num"]: f["name"] for f in base["inv"]}
    for n, r in sorted(rows.items()):
        raw, where = r["raw"], f"frame {n} {r['name']!r}"
        bad = [h[0] for h in SHOW_MATERIAL.finditer(raw)]
        bad += [
            k[0]
            for k in MASK_TAIL.finditer(raw)
            if k[1] or not (re.fullmatch(r"[A-Za-z0-9]{4}", k[2]) or k[2] == "{last4}")
        ]
        bad += [m[0] for m in LONG_RUN.finditer(raw) if plaintext_like(m[0])]
        bad += [
            m[1]
            for m in ID_VALUE.finditer(raw)
            if re.search(r"[0-9]|(?<=.)[A-Z]", m[1]) and not LONG_RUN.fullmatch(m[1])
        ]
        bad += [m[0] for m in BARE_ID.finditer(raw) if m[0] not in bad]
        bad += field_controls(raw)
        if bad:
            out.fail(
                "k1.masked", f"{where} draws more than the masked id, or a control on it: {bad[:3]}"
            )
        grants = [m[0] for m in WITHDRAW_ON.finditer(raw)] + [
            m[0]
            for m in WITHDRAW_GRANT.finditer(raw)
            if not NEGATION.search(raw[max(0, m.start() - 30) : m.start()])
        ]
        grants += [m[0] for m in WITHDRAW_CONTROL.finditer(raw) if not negated(raw, m)]
        if grants:
            out.fail(
                "k3.withdraw", f"{where} draws a withdrawal or transfer right allowed: {grants}"
            )
        if shown := loading_confirm(raw):
            out.fail("k4.loading", f"{where} draws the confirm while the summary loads: {shown}")
        if CONFIRM_BUTTON.search(raw) and n not in DESTRUCTIVE:
            out.fail("k4.consequence", f"{where} draws a destructive confirm §7 does not list")
        gated = [m[0] for m in EXIT_GATED.finditer(raw)]
        if gated:
            out.fail("k9.exit", f"{where} draws an exit gated: {gated[:2]}")
        if n not in t2_frames:
            locks = [m[0] for m in LOCK_DRAWN.finditer(raw) if not negated(raw, m)]
            if locks:
                out.fail("k6.lock", f"{where} is not gated (§10.3) and draws a lock: {locks[:2]}")
        else:
            legs = LEG_KEY.findall(raw)
            if "`lock`" not in raw:
                out.fail("k6.lock", f"{where} is gated (T2 per §10.1) and names no `lock`")
            elif "CMP-079" not in raw:
                out.fail(
                    "k6.lock", f"{where} is gated (T2 per §10.1) and names no CMP-079 RbacGate"
                )
            if not any(k in reasons for k in legs) or [k for k in legs if k not in reasons]:
                out.fail(
                    "k7.reason",
                    f"{where} is gated and names no reason key a §10 / §12 table gives: "
                    f"{sorted({k for k in legs if k not in reasons}) or 'none'}",
                )
            named = f"{inv_names.get(n, '')} | {r['name']} | {r['cls']}"
            heads = [LEG_KEY.findall(r[c])[:1] for c in ("hifi", "keys")]
            if VIEWAS_NAMED.search(named) and any(h != ["rbac.view_as"] for h in heads):
                out.fail(
                    "k8.viewas",
                    f"{where} is a view-as frame (E27-D02 §7 or its class): its Hi-fi and Copy "
                    f"keys cells do not both lead with `rbac.view_as`: {heads}",
                )
            elif "rbac.view_as" in legs and legs[0] != "rbac.view_as":
                out.fail("k8.viewas", f"{where}: the view-as leg comes after {legs[0]}")
            elif late := VIEWAS_LATE.search(raw):
                out.fail("k8.viewas", f"{where}: the row puts the view-as leg late: {late[0]!r}")
    for n, key in sorted(DESTRUCTIVE.items()):
        dr = rows.get(n)
        if dr is None:
            continue  # inv.missing names it
        r = dr
        keys = set(d02.ticked(r["keys"]))
        if key not in keys or not deck.get(key):
            out.fail(
                "k4.consequence",
                f"frame {n}: the destructive confirm loses its consequence line `{key}`",
            )
        if STEP_UP_KEY not in keys or not deck.get(STEP_UP_KEY):
            out.fail("k5.stepup", f"frame {n}: the destructive confirm loses its step-up ask line")
        inh = INHERIT.match(r["hifi"])
        parent = int(inh[1] or inh[2]) if inh else 0
        pat = drawn(deck.get(key, ""))
        if DESTRUCTIVE.get(parent) != key and (pat is None or not pat.search(r["hifi"])):
            out.fail(
                "k4.consequence",
                f"frame {n}: the drawn dialog no longer states its consequence ({key})",
            )
        if parent not in DESTRUCTIVE and not ASK_DRAWN.search(r["hifi"]):
            out.fail("k5.stepup", f"frame {n}: the drawn dialog no longer shows its ask line")
        typed = drawn(deck.get(TYPED_KEY, ""))
        if (
            TYPED_KEY in keys
            and TYPED_KEY not in d02.ticked(rows.get(parent, {}).get("keys", ""))
            and not TYPED_DRAWN.search(r["hifi"])
            and (typed is None or not typed.search(r["hifi"]))
        ):
            out.fail("k5.stepup", f"frame {n}: the rung-3 dialog no longer shows its typed label")
    tab = find_table(sec.get("7", ""), "consequence", "step-up")
    if tab is None:
        out.fail("k4.consequence", "§7 has no confirms table (… | Consequence … | Step-up | …)")
    else:
        head, body = tab
        ia, iq, isu = col(head, "action"), col(head, "consequence"), col(head, "step-up")
        for _raw, tr in body:
            if len(tr) <= max(ia, iq, isu) or "not destructive" in " ".join(tr):
                continue
            if tr[iq].strip("— ") == "":
                out.fail("k4.consequence", f"§7 confirm {tr[ia][:40]!r}: no consequence")
            if tr[isu].strip("— ") == "":
                out.fail("k5.stepup", f"§7 confirm {tr[ia][:40]!r}: no step-up")
    for head, body in tables(sec.get("10.2", "")):
        for _raw, tr in body:
            if tr and EXIT_CONTROL.match(tr[0]):
                out.fail("k9.exit", f"§10.2 gates an exit: {tr[0][:40]!r}")
    card = next((r for r in rows.values() if r["name"] == COMPROMISE), None)
    if card is not None:
        steps = STEP_RE.findall(card["raw"])
        keys = d02.ticked(card["keys"])
        order = [k for k in keys if re.fullmatch(r"e27\.scr128\.card\.step\d", k)]
        problems = []
        if steps != [(str(i + 1), v) for i, v in enumerate(STEPS)]:
            problems.append(f"steps {steps}")
        if order != [f"e27.scr128.card.step{i}" for i in range(1, 6)]:
            problems.append(f"keys {order}")
        problems += [
            f"step{i} reads {deck.get(f'e27.scr128.card.step{i}', '')[:20]!r}"
            for i, v in enumerate(STEPS, 1)
            if not deck.get(f"e27.scr128.card.step{i}", "").startswith(v)
        ]
        if problems:
            out.fail(
                "k11.compromise",
                f"the compromise card leaves C-12.12's order {'/'.join(STEPS)}: "
                + "; ".join(problems),
            )
    env_frames = {
        n
        for n, r in rows.items()
        if ENV_RE.search(r["raw"]) or ACCOUNT_TITLE.search(r["raw"]) or STRIP_DRAWN.search(r["raw"])
    }
    for n in sorted(env_frames):
        r = rows[n]
        if not ENV_RE.search(r["raw"]):
            out.fail("k12.env", f"frame {n} {r['name']!r} loses its environment badge")
    for head, body in tables(sec.get("2.4", "")):
        idx = [i for i, h in enumerate(head) if not re.match(r"current\b", h, re.IGNORECASE)]
        for _raw, tr in body:
            if shown := loading_confirm(" | ".join(tr[i] for i in idx if i < len(tr))):
                out.fail(
                    "k4.loading", f"§2.4 {tr[0][:40]!r} draws the confirm while loading: {shown}"
                )
    viewas_gate(sec, out)
    k13_numbers(spec, out)
    out.n.update(
        {
            "frame_rows": len(rows),
            "frames_destructive": len(DESTRUCTIVE),
            "frames_t2": len(t2_frames),
            "frames_env": len(env_frames),
        }
    )


# --- 7c. the whole-document security gates (r2o, the orchestrator's text round 2) -----------------
# K1, K2, K3, the dated OFF and the reveal words read every clause of every line of the spec AND the
# hand-off - every row of every table and every prose sentence, case-insensitive, no section list.
# The frame rows keep the frame gate's K1 / K3-withdraw (one FAIL per frame) and are read here for
# the reveal words and the dated OFF; every other line is read here for all five.
# A hit passes only inside one of the exact phrases pinned below, and each phrase covers at most its
# pinned count of occurrences (the first ones), so a copy of an allowed phrase elsewhere fails.
DOC_REVEAL = re.compile(REVEAL_AFFORDANCE.pattern + r"|\breveal\w*|\bunmask\w*", re.IGNORECASE)
FIELD_NAMED = re.compile(
    r"\bkeys?\b|\bsecrets?\b|CMP-034|CMP-201|\bmasked\b|MaskedValue|PasswordField", re.IGNORECASE
)
# a line's one FAIL takes the most specific code among its uncovered hits (a mutated control can
# break an allowed reveal phrase beside it; its own code wins)
DOC_CODES = ("k1.masked", "k2.field", "k3.withdraw", "k3.off", "reveal")
SECURITY_ALLOWED: tuple[tuple[str, str, int], ...] = (
    ("spec", "(#4338, `bf130fe52`); its boards", 1),
    ("spec", "E05-D02's time-limited reveal stay the", 1),
    ("spec", "and the reveal words read", 1),
    ("spec", 'a withdrawal "OFF" without its', 1),
    ("spec", "a show, copy or toggle", 1),
    ("spec", "control, a withdrawal control, and a", 1),
    ("spec", "PR base `e8bca4bb7` (every moved", 1),
    ("spec", 'every withdrawal "OFF" dated (D03-C15),', 1),
    ("spec", "Appendix A's copy-ready A-rows and", 1),
    ("spec", "`docs/design/_tools/e27_d03_hifi_audit.py` (`python3 -I", 1),
    ("spec", 'that tool; "copy re-tested with', 1),
    ("spec", "the final copy", 1),
    ("spec", "at `main` `e8bca4bb7`. `D02` =", 1),
    ("spec", '(`05:131`); no reveal (`11:344` "no', 1),
    ("spec", '(`11:344` "no reveal control anywhere', 1),
    ("spec", "(`3a2fc5c29`; CMP-034's reveal rules S1–S7", 1),
    ("spec", "keys), E30-D02 (`f798a64e6`; the validity", 1),
    ("spec", "has no reveal", 1),
    ("spec", "notes — misrepresentation is the", 1),
    ("spec", "and SCR-128 copy; no real", 1),
    ("spec", "must be OFF, IP allowlist", 1),
    ("spec", "verified in copy review", 2),
    ("spec", "of E05-D02's reveal stay the", 1),
    ("spec", "to one (verified-off = verified,", 1),
    ("spec", "no reveal anywhere (AC4;", 1),
    ("spec", 'annotates "secret reveal" as a', 1),
    ("spec", "E05-D02's time-limited reveal stays the", 1),
    ("spec", "draws a reveal meanwhile", 3),
    ("spec", "`label`, and the toggle, the timer", 1),
    ("spec", "and the copy affordance are", 1),
    ("spec", "the only copyable value (binding:", 1),
    ("spec", "D13 no reveal anywhere (binding)", 1),
    ("spec", "(`D02:387`), never OFF", 1),
    ("spec", 'the "Withdrawal: OFF ✓" text;', 1),
    ("spec", "and a copy-ready A-row to", 2),
    ("spec", "respec) defines a toggle, a timer", 1),
    ("spec", "and a copy control that", 1),
    ("spec", "Proposed (no reveal)", 1),
    ("spec", '"MaskedValue ("secret reveal")" (`15:371`)', 1),
    ("spec", 'name "secret reveal": permanently masked,', 2),
    ("spec", 'masked, no reveal)": the old', 1),
    ("spec", "display with reveal toggle (admin", 2),
    ("spec", "key/secret display with reveal toggle (admin key", 2),
    ("spec", "`label` · `revealed?` · `onToggleReveal`", 1),
    ("spec", "`revealed?` · `onToggleReveal` · `autoHideMs?`", 1),
    ("spec", "`onToggleReveal` · `autoHideMs?` · `copyable?`", 1),
    ("spec", "`autoHideMs?` · `copyable?` (`15:374`)", 1),
    ("spec", "8-character mask), revealed, expiring, copied", 1),
    ("spec", 'a "Show {label}" / "Hide', 1),
    ("spec", '{label}" / "Hide {label}" toggle; a', 1),
    ("spec", "Masked, Revealed, AutoHideCountdown, Copyable", 2),
    ("spec", "Masked, Revealed, AutoHideCountdown, Copyable (`15:378`)", 1),
    ("spec", "Revealed, AutoHideCountdown, Copyable (`15:378`)", 1),
    ("spec", "**Why the reveal is deliberately", 1),
    ("spec", 'for "no reveal', 1),
    ("spec", "(`11:344`). A reveal path is", 1),
    ("spec", "recorded as `api_key.reveal_attempt` (`ACT:139`) —", 1),
    ("spec", 'implies a reveal is available"', 1),
    ("spec", "misrepresentations that cause", 1),
    ("spec", "a box, a toggle, a timer", 1),
    ("spec", "or a copy control on", 1),
    ("spec", "nothing leaks, copy never logs,", 1),
    ("spec", "with a reveal toggle, caps-lock", 3),
    ("spec", "input with a reveal toggle, caps-lock warning", 3),
    ("spec", "Default, Revealed, CapsLockOn, WithError", 3),
    ("spec", '"copy-to-clipboard affordance (API', 1),
    ("spec", "screens' one copy control", 3),
    ("spec", "Copy keys", 10),
    ("spec", "(`E42-D03:635-641`); the copy keys are §12.1's", 1),
    ("spec", "Copy keys (§12)", 3),
    ("spec", 'loading…", never OFF. Error: the', 1),
    ("spec", 'account and off for sub_002.";', 1),
    ("spec", "allowed, no reveal control, never", 1),
    ("spec", "step → Copy → API", 1),
    ("spec", "no staged reveal of the", 1),
    ("spec", "secret → Copy → Verify", 1),
    ("spec", "Content and copy", 7),
    ("spec", "allowed, no reveal control and", 1),
    ("spec", "and no copy control; both", 1),
    ("spec", '"Trade, Withdrawal OFF ✓" with', 1),
    ("spec", "secret → Copy (the target", 1),
    ("spec", 'no "reveal", "irreversible", "permanently",', 1),
    ("spec", 'a withdrawal "OFF" or "off"', 2),
    ("spec", '"OFF" or "off" only', 2),
    ("spec", 'account and off for {label}."', 1),
    ("spec", "resembles a reveal (CMP-034 and", 1),
    ("spec", "1).** 62 copy-ready A-rows over", 1),
    ("spec", "S1–S3, the `autoHideMs` cap and", 1),
    ("spec", "draws a reveal meanwhile (D03-C4).", 1),
    ("spec", "out any reveal. **Decision (RULED", 1),
    ("spec", "draws a reveal meanwhile.", 1),
    ("spec", '"Trade, Withdrawal OFF ✓" (`D02:349`,', 1),
    ("spec", 'and "Withdrawal: off." (`D02:785`) with', 1),
    ("spec", "a staged reveal (D18; AD-16),", 1),
    ("spec", "imply a reveal `(heuristic)`", 1),
    ("spec", "box, beside a toggle, under a", 1),
    ("spec", "with a copy control would", 1),
    ("spec", "and no reveal: CMP-034 is", 1),
    ("spec", "`copy.banned`, `copy.utc`, `copy.off`, `withdraw`): ids", 1),
    ("spec", '"OFF" or "off" only beside', 1),
    ("spec", "A** (`appx.*`, `reveal`): each Old", 1),
    ("spec", "2026-10-25; `k1.masked`, `reveal`, `k3.withdraw`,", 1),
    ("spec", "toggle, a `[Copy]` or a", 1),
    ("spec", "or a copy control whose", 1),
    ("spec", "K2: no reveal prop or", 1),
    ("spec", 'every withdrawal "OFF" a', 1),
    ("spec", "in its Copy keys, both in", 1),
    ("spec", "round 2; `reveal`, `k1.masked`, `k2.field`,", 1),
    ("spec", "or a reveal is named,", 1),
    ("spec", "list: a reveal word or", 1),
    ("spec", 'form of "reveal" or "unmask",', 1),
    ("spec", '"reveal" or "unmask",', 1),
    ("spec", "withdrawal OFF, in any", 1),
    ("spec", "for the reveal words and", 1),
    ("spec", "state) with withdrawal-off always visually", 1),
    ("spec", "alone, and withdrawal-off always confirmed", 1),
    ("spec", "`- **A11y**: withdrawal-off state is", 1),
    ("spec", 'affirmative "Withdrawal: OFF ✓" text,', 1),
    ("spec", 'MaskedValue ("secret reveal")`', 1),
    ("spec", "masked, no reveal)`", 1),
    ("spec", "Why no reveal exists: no", 1),
    ("spec", '(C-12.2); "no reveal control anywhere', 1),
    ("spec", "itself a misrepresentation (E27-D03 §2.3).``", 1),
    ("spec", "buttons) · `revealed?: boolean` (never", 1),
    ("spec", "mount) · `onToggleReveal` · `autoHideMs?:", 1),
    ("spec", "`onToggleReveal` · `autoHideMs?: number` (default", 1),
    ("spec", "automatically) · `copyable?: boolean` (default", 1),
    ("spec", "value's length), revealed (only after", 1),
    ("spec", "press of the toggle), expiring (the", 1),
    ("spec", 'with label "Show {label}"/"Hide {label}" ("Show', 1),
    ("spec", 'label "Show {label}"/"Hide {label}" ("Show secret"/"Hide', 1),
    ("spec", '{label}"/"Hide {label}" ("Show secret"/"Hide secret" when', 1),
    ("spec", '{label}" ("Show secret"/"Hide secret" when `label`', 1),
    ("spec", "the value; copy logs nothing", 1),
    ("spec", "shown (the copy deck's string);", 1),
    ("spec", "the box, the toggle and the", 1),
    ("spec", "**Storybook**: Masked, Revealed, AutoHideCountdown, Copyable.`", 1),
    ("spec", "Masked, Revealed, AutoHideCountdown, Copyable.`", 1),
    ("spec", "Revealed, AutoHideCountdown, Copyable.`", 1),
    ("spec", "step 3) with no toggle at all.``", 1),
    ("spec", "``- **A11y**: reveal is a", 2),
    ("spec", "**Storybook**: Default, Revealed, CapsLockOn, WithError.`", 1),
    ("spec", "**Storybook**: Default, Revealed, CapsLockOn, WithError,", 1),
    ("spec", "axe, interaction (reveal toggle, paste", 2),
    ("spec", "· **Purpose**: copy-to-clipboard affordance (API", 1),
    ("hand-off", "`docs/design/_tools/e27_d03_hifi_audit.py`'s (spec §9).", 1),
    ("hand-off", "colours; no reveal, timer or", 1),
    ("hand-off", "timer or copy state exists", 1),
    ("hand-off", "`packages/ui/tokens` at `e8bca4bb7` (spec §2.3,", 1),
    ("hand-off", "draws a reveal meanwhile", 1),
    ("hand-off", "§2.3; no reveal, timer or", 1),
    ("hand-off", "timer or copy exists", 1),
)


def line_hits(
    line: str, frame_row: bool, field_heading: bool = False
) -> list[tuple[int, int, str]]:
    """Every security hit on one line: (start, end, code). A frame row is read for the reveal
    words and the dated OFF only; a row whose first cell, or whose heading, names a key or a secret
    field reads every clause as that field's (K1 / K2)."""
    hits = [(m.start(), m.end(), "reveal") for m in DOC_REVEAL.finditer(line)]
    hits += [(x, y, "k3.off") for x, y in off_spans(line, negate=False)]
    if frame_row:
        return hits
    first = cells(line)[0] if line.lstrip().startswith("|") else ""
    field_row = field_heading or FIELD_NAMED.search(first) is not None
    for a, b in clause_spans(line):
        clause = line[a:b]
        if field_row or FIELD_NAMED.search(clause):
            ids = [(m.start(), m.end()) for m in BARE_ID.finditer(clause)]
            ids += [
                (m.start(), m.end())
                for m in MASK_TAIL.finditer(clause)
                if m[1] or not (re.fullmatch(r"[A-Za-z0-9]{4}", m[2]) or m[2] == "{last4}")
            ]
            ids += [(m.start(), m.end()) for m in LONG_RUN.finditer(clause) if plaintext_like(m[0])]
            hits += [(a + x, a + y, "k1.masked") for x, y in ids]
            shown = [(m.start(), m.end()) for m in SHOW_MATERIAL.finditer(clause)]
            shown += control_spans(clause, field_row, negate=False)
            hits += [(a + x, a + y, "k2.field") for x, y in shown]
        rights = [
            m for p in (WITHDRAW_ON, WITHDRAW_GRANT, WITHDRAW_CONTROL) for m in p.finditer(clause)
        ]
        hits += [(a + m.start(), a + m.end(), "k3.withdraw") for m in rights]
    return hits


def doc_gate(spec: str, handoff: str, sec: dict[str, str], out: Out) -> None:
    """§7c: the K1 / K2 / K3 / dated-OFF / reveal gates over the whole spec and the hand-off."""
    frames = {r["raw"] for r in frame_rows(sec).values()}
    n_hits, n_allowed = 0, 0
    for name, text in (("spec", spec), ("hand-off", handoff)):
        covered = bytearray(len(text))
        for doc, phrase, want in SECURITY_ALLOWED:
            if doc != name:
                continue
            at = [m.start() for m in re.finditer(re.escape(phrase), text)][:want]
            for x in at:
                covered[x : x + len(phrase)] = b"\1" * len(phrase)
        start, heading = 0, ""
        for num, line in enumerate(text.split("\n"), 1):
            heading = line if line.startswith("#") else heading
            field_heading = FIELD_NAMED.search(heading) is not None
            hits = line_hits(line, line in frames and name == "spec", field_heading)
            n_hits += len(hits)
            bad = [(x, y, c) for x, y, c in hits if not all(covered[start + x : start + y])]
            n_allowed += len(hits) - len(bad)
            if bad:
                code = min((c for _x, _y, c in bad), key=DOC_CODES.index)
                words = sorted({line[x:y] for x, y, _c in bad})[:3]
                out.fail(
                    code,
                    f"{name} line {num}: a key, a secret field, a fund right or a reveal outside "
                    f"the pinned allow-list (§7c): {words}",
                )
            start += len(line) + 1
    out.n.update(
        {"doc_hits": n_hits, "doc_allowed": n_allowed, "doc_phrases": len(SECURITY_ALLOWED)}
    )


# --- 8. cites and scans --------------------------------------------------------------------------
CITE_FRAG = re.compile(rf"`({KEYS_ALT})(?:\.md)?:(\d+)(?:[-\u2013](\d+))?`\s+\"([^\"\n]+)\"")
# a bare or backticked `KEY:line[-line]`; a clock time (followed by UTC / Z) is never a cite
CITE_PLAIN = re.compile(
    rf"(?<![\w.:/#-])({KEYS_ALT})(?:\.md)?:(\d+)(?:[-\u2013](\d+))?(?![\d:])(?!\s*(?:UTC|Z\b))"
)
PIN = re.compile(r"(?<![0-9A-Za-z])([0-9a-f]{40}|[0-9a-f]{64})(?![0-9A-Za-z])")
# Private paths and hosts never belong in a public file: generic patterns only, the path literal
# split so this file never holds the string it forbids (R7).
FORBIDDEN = (
    r"/(?:ho" + r"me|Users)/[^/\s]+/",
    r"penpot\.[a-z0-9-]+\.[a-z]{2,}",
    r"team-i" + r"d=",
    r"file-i" + r"d=",
)
CLOSING = re.compile(r"\b(?:close[sd]?|fix(?:e[sd])?|resolve[sd]?)\b\s*:?\s*#\d+", re.IGNORECASE)
PLACEHOLDER = re.compile(r"^> \*\*To write \(|\bTODO\b|\bTBD\b|SET-ME", MULTI)
US_ID = re.compile(r"\bUS-([A-Z]+)-(\d{3})(?:\.\.(\d{3}))?\b")
LINES: dict[Path, list[str]] = {}


def file_lines(path: Path) -> list[str]:
    if path not in LINES:
        LINES[path] = read(path).splitlines()
    return LINES[path]


def cite_gate(spec: str, out: Out) -> None:
    """Fragment cites WARN on drift and FAIL when gone or ambiguous; every cite names a line."""
    plain = frag = 0
    for m in CITE_PLAIN.finditer(spec):
        path, numeric = key_path(m[1]), re.fullmatch(r"\d\d", m[1]) is not None
        if numeric and int(m[2]) == 0:
            continue  # "14:00" is a clock time, never line 0
        if path is None or not path.is_file():
            if not numeric:  # a two-digit key with no plan doc is no cite
                out.fail("cite.file", f"{m[0]}: {m[1]} names no file")
            continue
        plain += 1
        size, lo, hi = len(file_lines(path)), int(m[2]), int(m[3] or m[2])
        if not 1 <= lo <= hi <= size:
            out.fail("cite.eof", f"{m[0]}: {path.name} has {size} lines")
    for m in CITE_FRAG.finditer(spec):
        frag += 1
        path = key_path(m[1])
        lines = file_lines(path) if path and path.is_file() else []
        lo, hi, text = int(m[2]), int(m[3] or m[2]), m[4]
        found = [i + 1 for i, ln in enumerate(lines) if text in ln]
        if len(found) > 1:
            out.fail(
                "cite.ambiguous", f'cite {m[1]}:{lo} "{text}" is ambiguous: {len(found)} lines'
            )
        elif not found:
            out.fail("cite.gone", f'cite {m[1]}:{lo} "{text}" is gone from the file')
        elif not lo <= found[0] <= hi:
            out.warn("cite.drift", f'cite {m[1]}:{lo} "{text}" drifted — now at line {found[0]}')
    out.n.update({"cites": plain, "cites_fragment": frag})


def masked(spec: str) -> str:
    """Commit and sha256 pins and ruling ids masked before E27-D02's scan() (never a secret)."""

    def pin(m: re.Match[str]) -> str:
        before = spec[max(0, m.start() - 40) : m.start()].lower()
        if len(m[1]) == 64 and "sha256" in before:
            return "PIN"
        if len(m[1]) == 40 and re.search(
            r"\b(?:base|main|merged?|at|sha|commit|head|pinned)\b", before
        ):
            return "PIN"
        return m[1]

    text = PIN.sub(pin, spec)
    for word in ("RULED ", "record ", "comment ", "ruling "):
        text = re.sub(rf"(?<={word})\d{{7,}}", "N", text)
    return text


def misc_gate(spec: str, sec: dict[str, str], base: dict[str, Any], out: Out) -> None:
    misses: list[str] = []
    out.n["scans"] = d02.scan(masked(spec), misses)
    for miss in misses:
        out.fail("scan", miss)
    for r in sorted(set(re.findall(r"\bC-\d+\.\d+\b", spec))):
        if not re.search(rf"(?<![\d.]){re.escape(r)}(?!\d)", base["constitution"]):
            out.fail("ids", f"dangling rule id {r}")
    for c in sorted(set(re.findall(r"\bCMP-\d{3}\b", spec)) - set(base["e15"])):
        out.fail("ids", f"no such component {c}")
    for s in sorted(set(re.findall(r"\bSCR-\d{3}\b", spec)) - set(base["e14"])):
        out.fail("ids", f"no such screen {s}")
    for m in US_ID.finditer(spec):
        for k in range(int(m[2]), int(m[3] or m[2]) + 1):
            if f"#### US-{m[1]}-{k:03d} " not in base["us11"]:
                out.fail("ids", f"no such story US-{m[1]}-{k:03d}")
    for p in FORBIDDEN:
        if re.search(p, spec):
            out.fail("forbidden", f"forbidden text (a private path or host): {p}")
    if CLOSING.search(spec):
        out.fail("closing", "a closing keyword with an issue number (Refs + Partial only)")
    for clause in CLAUSE.split(spec):
        name = INFLIGHT_NAME.search(clause)
        if name is None:
            continue
        pins = SHORT_SHA.findall(clause)
        quoted_after = clause.count('"', 0, name.start()) % 2 == 0 and re.search(
            r'"[^"\n]{3,}"', clause[name.end() :]
        )
        if pins or quoted_after:
            out.fail(
                "pin.inflight",
                f"E42-D03's boards PR is in flight: named by its branch only, never pinned or "
                f"quoted: {' '.join(clause.split())[:80]!r}",
            )
    holders = PLACEHOLDER.findall(spec)
    if holders:
        out.fail("placeholder", f"{len(holders)} placeholder(s) left for the section writers")
    out.n["placeholders"] = len(holders)
    pre = sec.get("pre", "")
    out.n["checklist_ticked"] = len(re.findall(r"^\| \[x\] ", pre, MULTI))
    out.n["checklist_open"] = len(re.findall(r"^\| \[ \] ", pre, MULTI))
    rows = re.findall(r"^\| D03-([ACGHDQ])\d+ ", sec.get("14", ""), MULTI)
    out.n["rows"] = {k: rows.count(k) for k in "ACGHDQ"}
    if base["handoff_exists"]:
        blank = re.findall(r"^- \[[ x~]\] \*\*[^*]+\*\*\s*$", base["handoff"], MULTI)
        if blank:
            out.fail("handoff", f"{len(blank)} blank checklist line(s) in E27-D03-handoff.md")
    else:
        out.warn("handoff", "docs/design/E27/E27-D03-handoff.md is not written yet (BQ-14)")


def bq_gate(sec: dict[str, str], out: Out) -> None:
    statuses: dict[int, str] = {}
    tab = find_table(sec.get("pre", ""), "question", "status")
    if tab is None:
        out.fail(
            "bq.table", "no BQ table before §0 (Id | Question | Default built | Level | Status)"
        )
    else:
        head, body = tab
        ist = col(head, "status")
        for _raw, r in body:
            m = re.fullmatch(r"BQ-(\d+)", r[0] if r else "")
            if not m or len(r) <= ist:
                continue
            if int(m[1]) in statuses:
                out.fail("bq.ids", f"BQ-{m[1]} listed twice")
            statuses[int(m[1])] = r[ist]
        if sorted(statuses) != list(range(1, len(statuses) + 1)):
            out.fail("bq.ids", f"BQ ids {sorted(statuses)} are not BQ-1…BQ-{len(statuses)}")
    for k, s in sorted(statuses.items()):
        if not re.match(r"(?:PROPOSED|RULED)\b", s):
            out.fail("bq.status", f"BQ-{k}: status {s!r} is PROPOSED or RULED")
    ruled = sum(s.startswith("RULED") for s in statuses.values())
    if ruled and ruled != len(statuses):
        out.fail("bq.status", f"BQ rows RULED {ruled} of {len(statuses)}: rule every row or none")
    out.n.update({"q_rows": len(statuses), "q_ruled": ruled})


# --- 9. markers and the gates in order -----------------------------------------------------------
MARKER = re.compile(r"<!-- audit:([A-Za-z0-9_.\-]+)=([^ >]+) -->")


def flatten(d: object, prefix: str = "") -> dict[str, object]:
    out: dict[str, object] = {}
    if isinstance(d, dict):
        for k, v in d.items():
            out.update(flatten(v, f"{prefix}{k}."))
    else:
        out[prefix[:-1]] = d
    return out


def number(text: str) -> float | None:
    try:
        return float(text)
    except ValueError:
        return None


def marker_gate(spec: str, flat: dict[str, object], out: Out) -> None:
    for m in MARKER.finditer(spec):
        have, want = flat.get(m[1]), number(m[2])
        if have is None:
            out.fail("marker", f"marker {m[1]}: no such key")
        elif str(have) != m[2] and not (
            isinstance(have, int | float) and want is not None and abs(float(have) - want) < 0.006
        ):
            out.fail("marker", f"marker {m[1]}={m[2]} vs {have}")


def base_numbers(base: dict[str, Any]) -> dict[str, Any]:
    n = base["data"]["n"]
    return {
        "token_files": base["files"],
        "opacity_disabled": base["data"]["opacity_disabled"],
        "pairs_registry": len(base["registered"]),
        "pairs_rows": n["gated"],
        "pairs_registered": n["registered"],
        "pairs_proposed": n["proposed"],
        "pairs_fail": n["fail"],
        "pairs_reported": n["reported"],
        "repro_rows": n["repro"],
        "repro_fail": n["repro_fail"],
    }


def flat_data(base: dict[str, Any], out: Out) -> dict[str, object]:
    data = base["data"]
    return flatten(
        {
            "numbers": out.n,
            "pairs": data["pairs"],
            "ring_min": data["ring_min"],
            "composite": data["composite"],
            "cvd": base["cvd"],
            "luma": base["luma"],
        }
    )


def gates(
    spec: str,
    base: dict[str, Any],
    check_markers: bool = False,
    exists: Callable[[str], bool] | None = None,
) -> Out:
    """Sections 2-9 over one spec text (section 1's FAILs carried in from the base)."""
    out, sec = Out(), sections(spec)
    for f in base["data"]["fails"]:
        out.fail("matrix", f)
    out.n.update(base_numbers(base))
    ac2_gate(sec, out)
    token_gate(spec, sec, base, out)
    inventory_gate(spec, sec, base, out, exists or (lambda rel: (ROOT / rel).is_file()))
    t2_gate(spec, sec, base, out)
    deck_gate(sec, base, out)
    appendix_gate(sec, base, out)
    frame_gate(spec, sec, base, out)
    doc_gate(spec, base["handoff"], sec, out)
    cite_gate(spec, out)
    misc_gate(spec, sec, base, out)
    bq_gate(sec, out)
    out.n.update(
        {"mutations": len(MUTATIONS), "k_mutations": len(K_MUTATIONS) + len(HAND_MUTATIONS)}
    )
    if check_markers:
        marker_gate(spec, flat_data(base, out), out)
    out.n["markers"] = len(MARKER.findall(spec))
    return out


# --- the self-test: a passing spec built in memory from the base, and the mutations it refuses ---
# the cap's ten boards (BQ-2) as the fixture plans them: number, slug, theme, twin of, D02 frames
FIXTURE_BOARDS = (
    ("01", "cmp-175-key-states", "dark", "", (2,)),
    ("02", "cmp-175-key-states-light", "light", "01", ()),
    ("03", "components-and-looks", "dark", "", (3, 4, 5)),
    ("04", "scr-125-128-accounts", "dark", "", (1, *range(6, 18), *range(42, 49))),
    ("05", "scr-125-128-accounts-light", "light", "04", ()),
    ("06", "scr-126-add-key", "dark", "", (*range(18, 33), *range(72, 76))),
    ("07", "scr-127-rotate", "dark", "", tuple(range(33, 42))),
    ("08", "scr-129-confirm", "dark", "", tuple(range(49, 62))),
    ("09", "scr-079-drawer", "dark", "", tuple(range(62, 72))),
    ("10", "keyboard-zoom-forced-colours", "dark", "", ()),
)
FIXTURE_D02_FRAGMENT = "State inventory (AC1, AC5)"
# The fixture's static Markdown; $-fields are filled from the base files when it is built.
FIXTURE_TXT = """# E27-D03 — the self-test fixture

**Status:** Draft (the in-memory fixture).

## Inputs pinned (base `e8bca4bb7`)

| Input | State at the base |
| --- | --- |
| E27-D02 | merged; §7 at `D02:$d02_line` "$fragment" |
| tokens | $prims primitives <!-- audit:numbers.token_files.primitives=$prims --> |

## Acceptance-criteria trace (#816)

| Box | Item | Frame (board) |
| --- | --- | --- |
| [x] | no secret is ever rendered in the list | 04 |

## The questions (BQ-1…BQ-16) and the defaults built — PROPOSED

| Id | Question | Default built | Level | Status |
| --- | --- | --- | --- | --- |
$bq

## 0. The boards (PENDING)

| # | Board | Frames (E27-D02 §7) | Draws | Theme | Criterion | Export (planned) | State |
| --- | --- | --- | --- | --- | --- | --- | --- |
$boards

Boards 10 <!-- audit:numbers.boards=10 -->; the T2 label $t2 <!-- audit:pairs.t2-label.dark=$t2 -->.

## 1. Inputs and decisions

Fixture values only: `...a1b2`, `203.0.113.10`, UID 1234567, C-2.8, US-ACCT-002, `D02:405`.

## 2. Design-system contributions

### 2.1 CMP-175 KeyPermissionBadge

| Variant | Served source | Class | Glyph | Word | Mark |
| --- | --- | --- | --- | --- | --- |
| verified | served | pass | check | "Withdrawal OFF ✓ · verified {hh:mm} UTC" | — |
| trade-only | served | pass | check | "Trade" | — |
| read-only (import) | served | failed | octagon | "Can't trade: needs Contract trade." | — |
| read-only (stored) | served | info | info | "Read only — can't trade" | — |
| withdrawal-detected | served | critical | octagon | "BLOCKED — fund right found" | bold + 2 px border |
| IP-missing | served | failed | octagon | "IP allowlist: none set" | — |
| IP-mismatch | served | failed | octagon | "IP allowlist: no match" | — |
| expiring | served | warning | triangle | "Bybit expiry in {n} d" | — |
| expired | served | failed | octagon | "Expired at Bybit" | — |
| not checked | served | unknown | dash | "Withdrawal: not checked" | — |
| check overdue | served | time warning | clock | "Check overdue — last passed {hh:mm} UTC" | — |

### 2.3 CMP-034 MaskedValue

| Field | Current | Proposed (no reveal) |
| --- | --- | --- |
| Props | `label` · `revealed?` · `onToggleReveal` · `autoHideMs?` · `copyable?` | `maskedId` · `label` |

## 3. The hi-fi rows

| # | Frame (E27-D02 §7) | Class | Hi-fi | Copy keys | Board |
| --- | --- | --- | --- | --- | --- |
$hifi

## 7. SCR-129 — the confirms

| Action (frames) | Rung | Consequence | Step-up | Confirm |
| --- | --- | --- | --- | --- |
| Revoke a key that is not the last (49) | 1 | "It stops working here." | `keys` | "Revoke" |
| Enable a disabled account (61) | 1 (not destructive) | — | — | "Enable" |

## 10. T2

### 10.1 The T2 rule (stated once)

$t2_sentence (E09-D09 §2.2): the native role and the full label; `aria-disabled` and the reason in the DOM at mount, rendering 2a; CMP-079 RbacGate and the CMP-019 `lock`; the label and lock in `color.text.tertiary`; the reason in `color.text.secondary`; never `color.text.disabled`, never `opacity.disabled`. The legs in the server's order: view-as first (`rbac.view_as`), then permission (`rbac.permission`), grant, environment, state.

### 10.2 The gated set

| Control (operation) | Where | Legs in order → reason key | Rendering | Components |
| --- | --- | --- | --- | --- |
| Change leverage… | SCR-079 | view-as → `rbac.view_as`; Viewer → `rbac.permission`; key rejected → `accounts.key_rejected` | 2a, T2 per §10.1 | CMP-079 RbacGate, CMP-019 Icon `lock` |
| Verify and save | SCR-126 | KEK unavailable → `keys.kek_unavailable` | 2a, T2 per §10.1 | CMP-079 RbacGate, CMP-019 Icon `lock` |

### 10.3 What is NOT T2

Busy; Outcome; Availability; the validity look at `opacity.disabled`
$opacity <!-- audit:numbers.opacity_disabled=$opacity -->; T4; T1; T3.

## 12. Copy deck

### 12.1 The deck

| Id | Where | String | Status · source |
| --- | --- | --- | --- |
| `e27.scr125.verdict.ok` | SCR-125 · frame 2 | "$cd1" | unchanged · CD-1 |
| `e27.scr126.secret.help` | SCR-126 · frame 19 | "$cp1" | unchanged · CP-1 |
| `e27.scr129.revoked` | SCR-129 · frame 52 | "$cp4" | unchanged · CP-4 |
| `e27.scr125.chip.blocked` | SCR-125 · frame 13 | "BLOCKED — fund right found" | consumed · D02:405 |
| `e27.scr126.saved` | SCR-126 · frame 21 | "Saved. Key ...a1b2 is active on Main." | refined · D02:1108 |
| `e27.scr127.overlap.until` | SCR-127 · frame 38 | "Old key usable until {hh:mm:ss} UTC." | new · BQ-10 |
$deck_extra

### 12.2 T2 reason keys

| Key | String | Kind · source | Where |
| --- | --- | --- | --- |
| `keys.kek_unavailable` | "Off while the credential key is unavailable." | state | SCR-126 |
| `accounts.key_rejected` | "This account's API key was rejected — trading is off." | state | SCR-079 |
| `rbac.view_as` | "$view_as" | E09-D09 §3.1 | SCR-079 |
| `rbac.permission` | "$permission" | E09-D09 §3.1 | SCR-079 |

## 17. Summary for #816

1. The fixture.

## Appendix A. The `15` and `14` edits, old → new

| Entry · field | Old (verbatim) | New |
| --- | --- | --- |
| CMP-034 · Props (`15:$l34`) | ``$t34`` | ``- **Props**: `maskedId: string` · `label: string`.`` |
| CMP-175 · Tokens (`15:$l175`) | ``$t175`` | ``- **Tokens**: `color.status.danger.subtle` · `font.weight.bold`.`` |
| CMP-044 · Tokens (`15:$l44`) | ``$t44`` | ``- **Tokens**: `color.status.danger.subtle` · `elevation.dialog`.`` |

| `14` entry · edit | Old (verbatim) | New |
| --- | --- | --- |
| SCR-125 · insert before `14:$l14` | — | ``- **Hi-fi (E27-D03):** the accounts list. See `docs/design/E27/E27-D03.md` §3.`` |
"""


def row(*cells_: object) -> str:
    return "| " + " | ".join(str(c).replace("|", "\\|") for c in cells_) + " |"


def entry_line(base: dict[str, Any], doc: str, key: str, prefix: str) -> tuple[int, str]:
    first, last = base[f"e{doc}"][key]
    lines = base[f"cat{doc}"].splitlines()
    i = next(i for i in range(first - 1, last) if lines[i].startswith(prefix))
    return i + 1, lines[i].replace("|", "\\|")


FIXTURE_CONSEQUENCE = "A consequence stated before the press."


def fixture_frame(num: int, frame: dict[str, Any]) -> tuple[str, str]:
    """The fixture's Hi-fi and Copy keys cells: each element its frame-level gate requires."""
    hifi, keys = ["x"], []
    if frame["t2"]:
        view_as = VIEWAS_NAMED.search(frame["name"]) is not None
        hifi.append("T2 `rbac.view_as`, " * view_as + "the `lock` leads it inside CMP-079")
        keys.append("`rbac.view_as`" if view_as else "`keys.kek_unavailable`")
    if num in DESTRUCTIVE:
        keys += [f"`{DESTRUCTIVE[num]}`", f"`{STEP_UP_KEY}`"]
        hifi += [f'"{FIXTURE_CONSEQUENCE}"', "the ask line"]
    if frame["name"] == COMPROMISE:
        hifi.append("steps: " + " · ".join(f'{i} "{v} it"' for i, v in enumerate(STEPS, 1)))
        keys += [f"`e27.scr128.card.step{i}`" for i in range(1, 6)]
    return "; ".join(hifi), " · ".join(keys) or "—"


def fixture(base: dict[str, Any]) -> str:
    """A spec that passes every gate, assembled from the base files (never written to disk)."""
    inv = {f["num"]: f for f in base["inv"]}
    board_of = {n: b[0] for b in FIXTURE_BOARDS for n in b[4]}
    boards = []
    for num, slug, theme, twin, frames in FIXTURE_BOARDS:
        names = "; ".join(f"`{inv[n]['name']}`" for n in frames) or "— (specimens)"
        export = f"`{IMG}/E27-D03-{num}-{slug}.png`"
        cell = f"twin of {twin}" if twin else names
        boards.append(
            row(num, f"`E27-D03 / {num} {slug}`", cell, "x", theme, "x", export, "PENDING")
        )
    hifi = [
        row(n, f"`{f['name']}`", T2_EXACT if f["t2"] else "status", *fixture_frame(n, f))
        + f" {board_of.get(n, NOT_DRAWN)} |"
        for n, f in sorted(inv.items())
    ]
    extra = {key: FIXTURE_CONSEQUENCE for key in DESTRUCTIVE.values()}
    extra[STEP_UP_KEY] = "You'll confirm with your password and a code."
    extra.update(
        {f"e27.scr128.card.step{i}": f"{v} — the fixture's step." for i, v in enumerate(STEPS, 1)}
    )
    lines = base["d02"].splitlines()
    fields = {
        "d02_line": next(i + 1 for i, ln in enumerate(lines) if FIXTURE_D02_FRAGMENT in ln),
        "fragment": FIXTURE_D02_FRAGMENT,
        "prims": base["files"]["primitives"],
        "bq": "\n".join(row(f"BQ-{k}", "x", "x", "orchestrator", "PROPOSED") for k in range(1, 17)),
        "boards": "\n".join(boards),
        "t2": f"{base['data']['pairs']['t2-label']['dark']:.2f}",
        "hifi": "\n".join(hifi),
        "opacity": base["data"]["opacity_disabled"],
        "deck_extra": "\n".join(
            row(f"`{k}`", "fixture", f'"{v}"', "new · the self-test") for k, v in extra.items()
        ),
        "t2_sentence": T2_SENTENCE,
        "cd1": base["memo"]["CD-1"][0],
        "cp1": base["memo"]["CP-1"][0],
        "cp4": base["memo"]["CP-4"][0],
        "view_as": base["rbac"]["rbac.view_as"],
        "permission": base["rbac"]["rbac.permission"],
        "l14": entry_line(base, "14", "SCR-125", "- **Wireframes (E27-D02):**")[0] + 1,
    }
    for key, (cmp, prefix) in {
        "34": ("CMP-034", "- **Props**:"),
        "175": ("CMP-175", "- **Tokens**:"),
        "44": ("CMP-044", "- **Tokens**:"),
    }.items():
        fields[f"l{key}"], fields[f"t{key}"] = entry_line(base, "15", cmp, prefix)
    return string.Template(FIXTURE_TXT).substitute(fields)


Edit = Callable[[list[str], list[tuple[str, list[str]]]], list[tuple[str, str]] | None]
Mutation = Callable[[str], str | None]


def table_edit(spec: str, key: str, needles: tuple[str, ...], edit: Edit) -> str | None:
    """Apply ``edit`` (-> [(old line, new line)]) to the first matching table of section ``key``."""
    tab = find_table(sections(spec).get(key, ""), *needles)
    changes = edit(*tab) if tab else None
    if not changes:
        return None
    for raw, new in changes:
        spec = spec.replace(raw, new, 1)
    return spec


def set_cell(raw: str, r: list[str], i: int, value: str) -> tuple[str, str]:
    r = list(r)
    r[i] = value
    return raw, row(*r)


def variant_edit(select: Callable[[str, str], bool], field: str, value: str) -> Mutation:
    def edit(head: list[str], body: list[tuple[str, list[str]]]) -> list[tuple[str, str]] | None:
        iv, ic, i = col(head, "variant"), col(head, "class"), col(head, field)
        hit = next(((raw, r) for raw, r in body if select(norm(r[iv]), pick(r[ic], CLASSES))), None)
        return [set_cell(*hit, i, value)] if hit and i >= 0 else None

    return lambda spec: table_edit(spec, "2.1", ("variant", "word"), edit)


def board_edit(
    change: Callable[[list[str], list[tuple[str, list[str]]]], list[tuple[str, str]] | None],
) -> Mutation:
    return lambda spec: table_edit(spec, "0", ("board", "frames", "state"), change)


def first_board_state(value: str) -> Mutation:
    def edit(head: list[str], body: list[tuple[str, list[str]]]) -> list[tuple[str, str]] | None:
        hit = next(((raw, r) for raw, r in body if re.fullmatch(r"\d\d", r[0])), None)
        return [set_cell(*hit, col(head, "state"), value)] if hit else None

    return board_edit(edit)


def eleventh_board(
    head: list[str], body: list[tuple[str, list[str]]]
) -> list[tuple[str, str]] | None:
    rows_ = [(raw, r) for raw, r in body if re.fullmatch(r"\d\d", r[0])]
    if not rows_:
        return None
    new = ["x"] * len(head)
    values = {
        "board": "`E27-D03 / 11 extra-sheet`",
        "frames": "— (specimens)",
        "theme": "dark",
        "export": f"`{IMG}/E27-D03-11-extra-sheet.png`",
        "state": "PENDING",
    }
    for k, v in values.items():
        new[col(head, k)] = v
    new[0] = "11"
    return [(rows_[-1][0], rows_[-1][0] + "\n" + row(*new))]


def twins_over_a_third(
    head: list[str], body: list[tuple[str, list[str]]]
) -> list[tuple[str, str]] | None:
    it, ifr = col(head, "theme"), col(head, "frames")
    rows_ = [(raw, r) for raw, r in body if re.fullmatch(r"\d\d", r[0])]
    named = {m[1] for _raw, r in rows_ if (m := re.search(r"twin of (\d\d)", r[ifr]))}
    darks = [(raw, r) for raw, r in rows_ if norm(r[it]) == "dark"]
    need = len(rows_) // 3 + 1 - (len(rows_) - len(darks))
    spare = [(raw, r) for raw, r in darks[1:] if r[0] not in named]
    if not darks or need <= 0 or len(spare) < need:
        return None
    out = []
    for raw, r in spare[-need:]:
        r = list(r)
        r[it], r[ifr] = "light", f"twin of {darks[0][1][0]}"
        out.append((raw, row(*r)))
    return out


def hifi_line(spec: str, base: dict[str, Any], t2: bool | None = None) -> str | None:
    names = {f["name"]: f["t2"] for f in base["inv"]}
    for line in spec.splitlines():
        m = HIFI_ROW.match(line)
        name = " ".join(m[2].split()) if m else ""
        if name in names and (t2 is None or names[name] == t2):
            return line
    return None


def add_to(key: str, text: str) -> Mutation:
    def mutate(spec: str) -> str | None:
        m = re.search(rf"^## {key}\. .*$", spec, MULTI)
        return spec[: m.end()] + "\n\n" + text + spec[m.end() :] if m else None

    return mutate


def deck_row(text: str) -> Mutation:
    def edit(head: list[str], body: list[tuple[str, list[str]]]) -> list[tuple[str, str]] | None:
        istr, ist = col(head, "string"), col(head, "status")
        if not body or min(istr, ist) < 0:
            return None
        new = ["x"] * len(head)
        new[0], new[istr], new[ist] = "`e27.selftest.added`", f'"{text}"', "new · the self-test"
        return [(body[-1][0], body[-1][0] + "\n" + row(*new))]

    return lambda spec: table_edit(spec, "12", ("string", "status"), edit)


def unchanged_altered(
    head: list[str], body: list[tuple[str, list[str]]]
) -> list[tuple[str, str]] | None:
    istr, ist = col(head, "string"), col(head, "status")
    hit = next(
        ((raw, r) for raw, r in body if r[ist].startswith("unchanged") and quoted(r[istr])), None
    )
    return [set_cell(*hit, istr, f'"Note: {quoted(hit[1][istr])[0]}"')] if hit else None


def reason_edit(select: Callable[[str], bool], value: Callable[[str], str]) -> Mutation:
    def mutate(spec: str) -> str | None:
        for line in spec.splitlines():
            r = cells(line) if line.startswith("|") else []
            m = REASON_KEY.match(r[0]) if r else None
            if m and len(r) > 1 and select(m[1]) and quoted(r[1]):
                return spec.replace(line, row(r[0], f'"{value(quoted(r[1])[0])}"', *r[2:]), 1)
        return None

    return mutate


def gated_edit(change: Callable[[list[str], list[str]], list[str] | None]) -> Mutation:
    def edit(head: list[str], body: list[tuple[str, list[str]]]) -> list[tuple[str, str]] | None:
        for raw, r in body:
            new = change(head, list(r))
            if new is not None:
                return [(raw, row(*new))]
        return None

    return lambda spec: table_edit(spec, "10.2", ("legs", "components"), edit)


def swap_view_as(head: list[str], r: list[str]) -> list[str] | None:
    il = col(head, "legs")
    legs = [leg.strip() for leg in r[il].split(";")]
    if len(legs) < 2 or "view-as" not in legs[0]:
        return None
    r[il] = "; ".join([legs[1], legs[0], *legs[2:]])
    return r


def drop_lock(head: list[str], r: list[str]) -> list[str] | None:
    ico = col(head, "components")
    return (
        [*r[:ico], r[ico].replace("`lock`", "glyph"), *r[ico + 1 :]] if "`lock`" in r[ico] else None
    )


def appendix_edit(change: Callable[[str, str], tuple[str, str] | None]) -> Mutation:
    """Change (first cell, Old cell) of the first `15` row whose Old cell is quoted."""

    def edit(head: list[str], body: list[tuple[str, list[str]]]) -> list[tuple[str, str]] | None:
        iold = col(head, "old")
        for raw, r in body:
            if (
                re.match(r"CMP-\d{3}", r[0])
                and code_span(r[iold])
                and (new := change(r[0], r[iold]))
            ):
                return [(raw, row(new[0], *r[1:iold], new[1], *r[iold + 1 :]))]
        return None

    return lambda spec: table_edit(spec, "A", ("entry", "field"), edit)


def old_gone(first: str, old: str) -> tuple[str, str] | None:
    inner = (code_span(old) or ("", ""))[0]
    return first, old.replace(inner, inner + " zz", 1)


def cite_shift(first: str, old: str) -> tuple[str, str] | None:
    m = re.search(r"`15:(\d+)", first)
    return (first.replace(m[0], f"`15:{int(m[1]) + 1}", 1), old) if m else None


def reveal_prop(head: list[str], body: list[tuple[str, list[str]]]) -> list[tuple[str, str]] | None:
    inew = col(head, "new")
    for raw, r in body:
        span = code_span(r[inew]) if r[0].startswith("CMP-034") and "Props" in r[0] else None
        if span:
            return [
                set_cell(raw, r, inew, r[inew].replace(span[0], span[0] + " · `onToggleReveal`", 1))
            ]
    return None


def frag_cite(change: Callable[[re.Match[str]], str]) -> Mutation:
    def mutate(spec: str) -> str | None:
        m = CITE_FRAG.search(spec)
        return spec.replace(m[0], change(m), 1) if m else None

    return mutate


def line_drop(spec: str, base: dict[str, Any]) -> str | None:
    line = hifi_line(spec, base)
    return spec.replace(line + "\n", "", 1) if line else None


def t2_uncited(spec: str, base: dict[str, Any]) -> str | None:
    line = hifi_line(spec, base, t2=True)
    return (
        spec.replace(line, line.replace(T2_EXACT, "T2", 1), 1)
        if line and T2_EXACT in line
        else None
    )


def first_sub(pattern: str, repl: str, key: str = "") -> Mutation:
    def mutate(spec: str) -> str | None:
        part = sections(spec).get(key, "") if key else spec
        m = re.search(pattern, part)
        return spec.replace(part, part[: m.start()] + repl + part[m.end() :], 1) if m else None

    return mutate


def bq_row_flipped(
    head: list[str], body: list[tuple[str, list[str]]]
) -> list[tuple[str, str]] | None:
    """Flip one BQ row against the rest: RULED among PROPOSED rows, PROPOSED among RULED ones."""
    ist = col(head, "status")
    rows_ = [(raw, r) for raw, r in body if re.fullmatch(r"BQ-\d+", r[0])]
    ruled = bool(rows_) and all(r[ist].startswith("RULED") for _raw, r in rows_)
    flip = "PROPOSED" if ruled else "RULED 1234567890"
    return [set_cell(*rows_[0], ist, flip)] if rows_ else None


def in_table(key: str, needles: tuple[str, ...], edit: Edit) -> Mutation:
    return lambda spec: table_edit(spec, key, needles, edit)


def shared_word(head: list[str], body: list[tuple[str, list[str]]]) -> list[tuple[str, str]] | None:
    iw = col(head, "word")
    return [set_cell(body[1][0], body[1][1], iw, body[0][1][iw])] if len(body) > 1 else None


def is_warning(_variant: str, cls: str) -> bool:
    return cls in ("warning", "time warning")


def is_critical(_variant: str, cls: str) -> bool:
    return cls == "critical"


def is_unchecked(variant: str, _cls: str) -> bool:
    return variant.startswith("not checked")


def longer(s: str) -> str:
    return s[:-1] + ", and nothing else changes until a restart."


def reworded(_s: str) -> str:
    return "Read-only while you view as {user}."


def same_old(first: str, _old: str) -> tuple[str, str]:
    return first, "`- **`"


def line_moved(m: re.Match[str]) -> str:
    return m[0].replace(f":{m[2]}", f":{int(m[2]) + 1}", 1)


def fragment(text: str) -> Callable[[re.Match[str]], str]:
    return lambda m: m[0].replace(f'"{m[4]}"', f'"{text}"')


CLOSER = "Clo" + "ses #816."  # split, so this file holds no closing keyword with an issue number
TERTIARY = r"`color\.text\.tertiary`"
DECK = ("string", "status")
# (name, the outcome, the failure or warning code it must raise, the in-memory edit)
MUTATIONS: tuple[tuple[str, str, str, Callable[..., str | None]], ...] = (
    ("a reveal prop on CMP-034", "FAIL", "reveal", in_table("A", ("entry", "field"), reveal_prop)),
    ("two variants share a word", "FAIL", "ac2.word", in_table("2.1", ("word",), shared_word)),
    ("an octagon on a warning", "FAIL", "ac2.glyph", variant_edit(is_warning, "glyph", "octagon")),
    (
        "the critical mark on a warning",
        "FAIL",
        "ac2.mark",
        variant_edit(is_warning, "mark", "bold"),
    ),
    ("the critical word lost", "FAIL", "ac2.word", variant_edit(is_critical, "word", "—")),
    ("not checked reads OFF", "FAIL", "ac2.off", variant_edit(is_unchecked, "word", '"OFF"')),
    ("an 11th board", "FAIL", "cap.boards", board_edit(eleventh_board)),
    ("light twins over a third", "FAIL", "cap.twins", board_edit(twins_over_a_third)),
    ("a board State TBD", "FAIL", "board.state", first_board_state("TBD")),
    ("a drawn board without its PNG", "FAIL", "board.drawn", first_board_state("drawn")),
    ("a frame without its hi-fi row", "FAIL", "inv.missing", line_drop),
    ("a stray frame name", "FAIL", "inv.stray", add_to("1", "`SCR-125 / an invented state`")),
    ("a T2 frame without its cite", "FAIL", "t2.cite", t2_uncited),
    ("the T2 rule twice", "FAIL", "t2.once", add_to("1", T2_SENTENCE + ".")),
    ("a dimmed T2", "FAIL", "tokens.dimmed", first_sub(TERTIARY, "`color.text.disabled`", "10.1")),
    ("view-as not first", "FAIL", "t2.viewas", gated_edit(swap_view_as)),
    ("a gated row without the lock", "FAIL", "t2.lock", gated_edit(drop_lock)),
    ("a reason key over 60", "FAIL", "key.form", reason_edit(lambda k: k[:5] != "rbac.", longer)),
    (
        "an rbac string reworded",
        "FAIL",
        "key.rbac",
        reason_edit(lambda k: k == "rbac.view_as", reworded),
    ),
    (
        "an altered unchanged seed",
        "FAIL",
        "deck.unchanged",
        in_table("12", DECK, unchanged_altered),
    ),
    ("withdrawal drawn as allowed", "FAIL", "withdraw", deck_row("Withdrawal: ON for this key.")),
    ("a banned word in the deck", "FAIL", "copy.banned", deck_row("Reveal the key id.")),
    ("a time without UTC", "FAIL", "copy.utc", deck_row("Old key usable until {hh:mm}.")),
    ("an undated OFF", "FAIL", "copy.off", deck_row("Withdrawal: OFF ✓ for this key.")),
    ("an Appendix A old text gone", "FAIL", "appx.gone", appendix_edit(old_gone)),
    ("an Appendix A old text ambiguous", "FAIL", "appx.ambiguous", appendix_edit(same_old)),
    ("an Appendix A cite shifted", "WARN", "appx.drift", appendix_edit(cite_shift)),
    ("a cite's line moved", "WARN", "cite.drift", frag_cite(line_moved)),
    ("a cite's fragment gone", "FAIL", "cite.gone", frag_cite(fragment("zzqx not in any file"))),
    ("a cite's fragment ambiguous", "FAIL", "cite.ambiguous", frag_cite(fragment("the"))),
    ("a key id of three", "FAIL", "scan", first_sub(r"\.\.\.[A-Za-z0-9]{4}\b", "...abc")),
    ("an address outside RFC 5737", "FAIL", "scan", add_to("1", "Egress 10.1.2.3.")),
    ("an unknown token", "FAIL", "tokens.unknown", add_to("1", "`color.surface.invented`")),
    ("a dangling component", "FAIL", "ids", add_to("1", "CMP-999")),
    ("a closing keyword", "FAIL", "closing", add_to("1", CLOSER)),
    (
        "one BQ row flipped",
        "FAIL",
        "bq.status",
        in_table("pre", ("question", "status"), bq_row_flipped),
    ),
    ("a marker drifted", "FAIL", "marker", add_to("1", "<!-- audit:numbers.boards=11 -->")),
)


def frame_sub(num: int, old: str, new: str, every: bool = False) -> Mutation:
    """Replace ``old`` in frame ``num``'s hi-fi row (its first occurrence, or every one)."""

    def mutate(spec: str) -> str | None:
        r = frame_rows(sections(spec)).get(num)
        if r is None or old not in r["raw"]:
            return None
        line = r["raw"].replace(old, new) if every else r["raw"].replace(old, new, 1)
        return spec.replace(r["raw"], line, 1)

    return mutate


def frame_drop(num: int) -> Mutation:
    def mutate(spec: str) -> str | None:
        r = frame_rows(sections(spec)).get(num)
        return spec.replace(r["raw"] + "\n", "", 1) if r else None

    return mutate


def swap_steps(spec: str) -> str | None:
    """K11: the compromise card's steps 2 and 3 trade places."""
    first = frame_sub(46, '· 2 "Delete', '· 3 "Delete')(spec)
    return frame_sub(46, '· 3 "Revoke', '· 2 "Revoke')(first) if first else None


def sec_sub(key: str, old: str, new: str) -> Mutation:
    """Replace ``old`` (exact text) at its first occurrence in section ``key``."""
    return first_sub(re.escape(old), new, key)


def viewas_swapped(spec: str) -> str | None:
    """G7: frame 69's view-as leg swapped for the role leg, in its prose and its keys."""
    first = frame_sub(69, "`rbac.view_as`", "`rbac.owner_only`", every=True)(spec)
    return (
        frame_sub(69, "the view-as leg checked", "the role leg checked")(first) if first else None
    )


def is_expiring(variant: str, _cls: str) -> bool:
    return variant.startswith("expiring")


ROUTE = "not drawn — the text is binding; drawn on request"
# K1b-K1d's tokens are built at run time from harmless parts, so no line of this file (or of any
# commit) matches a secret scanner's rule for a vendor key; each keeps its mutation's effect
PREFIXED_RUN = "_".join(("s" + "k", "li" + "ve", "Zx81" + "QwEr" + "Ty99" + "AbCd"))
# --self-test prints each mutation's FAIL; a vendor-shaped run (two letters, a live / test mode, a
# body) is masked to its first three characters, so no output or pasted evidence carries one
VENDOR_SHAPE = re.compile(
    r"(?<![A-Za-z0-9])[a-z]{2}_(?:" + "li" + "ve|" + "te" + r"st)_[A-Za-z0-9]+(?![A-Za-z0-9])"
)


def mask_vendor(line: str) -> str:
    return VENDOR_SHAPE.sub(lambda m: m[0][:3] + "\u2026", line)


MIXED_16 = "xQ7m" + "K2pL" + "9vRt" + "4wZn"
MIXED_20 = "AbCd" + "EfGh" + "IjKl" + "MnOp" + "QrSt"
BARE_12 = "7Hq2" + "Lm9X" + "c4Rv"
HEX_12 = "a7b8" + "c9d0" + "e1f2"
HEX_40 = "0f1e2d3c" + "4b5a6978" + "8796a5b4" + "c3d2e1f0" + "0a1b2c3d"
BOARDS = "(`design/e42-d03-boards`, not on main)"
CONSEQUENCE_49 = (
    "It stops working here at once; sub_002 keeps trading on ...d9e0. It still works at Bybit "
    "until you delete it in Bybit's dashboard."
)
# The standing rule's list (main-orchestrator, 2026-10-25 00:32Z): (K, the mutation, the one FAIL
# code it must raise, the in-memory edit of the spec on disk). Each runs as a plain run (rc 1), so a
# count marker it moves (``--check``) is not a second FAIL; K13 is the marker-number gate itself.
K_MUTATIONS: tuple[tuple[str, str, str, Mutation], ...] = (
    (
        "K1",
        "a key row shows more than the masked id",
        "k1.masked",
        frame_sub(31, "...e5f6", "...e5f6 [Show key]"),
    ),
    (
        "K1b",
        "a key row shows a prefixed plaintext-like key",
        "k1.masked",
        frame_sub(31, "...e5f6", PREFIXED_RUN),
    ),
    (
        "K1c",
        "a key row shows a 16-character mixed token",
        "k1.masked",
        frame_sub(31, "...e5f6", MIXED_16),
    ),
    (
        "K1d",
        "a key row shows a 20-character mixed-case token",
        "k1.masked",
        frame_sub(31, "...e5f6", MIXED_20),
    ),
    (
        "K1e",
        "a key cell shows a bare 12-character id",
        "k1.masked",
        frame_sub(42, "sub_002 ...e5f6", f"sub_002 {BARE_12}"),
    ),
    (
        "K1f",
        "a key cell shows a bare 12-character hex id",
        "k1.masked",
        frame_sub(42, "demo-1 ...a7b8", f"demo-1 {HEX_12}"),
    ),
    (
        "K1g",
        "a key cell adds a full id after the masked one",
        "k1.masked",
        frame_sub(42, "sub_002 ...e5f6", f"sub_002 ...e5f6 ({BARE_12})"),
    ),
    (
        "K1h",
        "a [Copy] beside the API secret",
        "k1.masked",
        frame_sub(19, "CMP-201 write-only", "CMP-201 write-only with [Copy] beside the API secret"),
    ),
    (
        "K1i",
        "a [Copy] on both write-only fields",
        "k1.masked",
        frame_sub(35, "read-only and masked.", "read-only and masked, each with [Copy]."),
    ),
    (
        "K1j",
        "a Show toggle on the secret well",
        "k1.masked",
        frame_sub(19, "§4.1 exactly", "§4.1 exactly, the API secret well with a Show toggle"),
    ),
    (
        "K2",
        "CMP-034 regains a reveal prop on a frame",
        "reveal",
        frame_sub(31, "CMP-034", "CMP-034 (`revealed`)"),
    ),
    (
        "K2b",
        "§4.1's key field gains [Show]",
        "k2.field",
        first_sub(r"no reveal control, never re-filled", "a [Show] button, never re-filled", "4.1"),
    ),
    (
        "K2c",
        "§4.1's secret field gains [Copy]",
        "k2.field",
        first_sub(r'as G; label "API secret"', 'as G with [Copy]; label "API secret"', "4.1"),
    ),
    (
        "K2d",
        "§5's key fields gain a copy control",
        "k2.field",
        first_sub(r"and no copy control", "and a copy control", "5"),
    ),
    (
        "K2e",
        "§2.3's write-only A11y cell gains [Copy]",
        "k2.field",
        first_sub(r"no toggle in the DOM", "a [Copy] button in the DOM", "2.3"),
    ),
    (
        "K2f",
        "§2.5's secret-entry home gains [Show]",
        "k2.field",
        first_sub(r"no toggle, autocomplete off", "a [Show] button, autocomplete off", "2.5"),
    ),
    (
        "K1k",
        "a §4.1 table cell shows a bare 12-character id",
        "k1.masked",
        first_sub(r'\(label "API key";', f'(label "API key {BARE_12}";', "4.1"),
    ),
    (
        "K3",
        "a withdrawal right drawn as allowed",
        "k3.withdraw",
        frame_sub(42, "CMP-175", 'CMP-175 "Withdrawal: on"'),
    ),
    (
        "K3b",
        "a withdrawal toggle on the edit form",
        "k3.withdraw",
        frame_sub(
            31, "CMP-175 `key` facets", "CMP-175 `key` facets · a Withdrawal toggle (CMP-012)"
        ),
    ),
    (
        "K3c",
        "a withdrawal switch on the drawer",
        "k3.withdraw",
        frame_sub(
            62,
            "the comfortable inset draws this frame",
            "a Withdrawal switch beside the key; the comfortable inset draws this frame",
        ),
    ),
    (
        "K3d",
        "a frame's withdrawal OFF loses its verified time",
        "k3.off",
        frame_sub(2, " · verified 14:02 UTC", ""),
    ),
    (
        "K3e",
        "the check list's fresh-pass OFF loses its time",
        "k3.off",
        frame_sub(36, '"OFF ✓ · verified 10:39 UTC"', '"OFF ✓"'),
    ),
    (
        "K4",
        "a destructive confirm loses its consequence",
        "k4.consequence",
        frame_sub(49, " · `e27.scr129.revoke.not_last`", ""),
    ),
    (
        "K4b",
        "a drawn confirm loses its consequence sentence",
        "k4.consequence",
        frame_sub(49, f'"{CONSEQUENCE_49}"', "", every=True),
    ),
    (
        "K4c",
        "a rung-3 confirm loses its first consequence",
        "k4.consequence",
        frame_sub(54, '"sub_002 stops trading here; new orders on it are refused." · ', ""),
    ),
    (
        "K5",
        "a destructive confirm loses its step-up",
        "k5.stepup",
        frame_sub(58, " · `e27.shared.ask`", ""),
    ),
    (
        "K5b",
        "a drawn confirm loses its served ask line",
        "k5.stepup",
        frame_sub(50, "the ask line (served); ", ""),
    ),
    (
        "K5c",
        "a drawn confirm loses its stamped ask line",
        "k5.stepup",
        frame_sub(
            54, 'the ask line as a target state stamped "not yet served — G-8, #895 / #898"; ', ""
        ),
    ),
    (
        "K5d",
        "a rung-3 confirm loses its typed label",
        "k5.stepup",
        frame_sub(54, '"Type sub_002 to confirm:"; ', ""),
    ),
    (
        "K4d",
        "the loading frame renders the confirm disabled",
        "k4.loading",
        frame_sub(
            53,
            "[Cancel] alone: the confirm is not in the DOM",
            "[Cancel] and the confirm, rendered and disabled until the summary loads",
        ),
    ),
    (
        "K4e",
        "§2.4's loading state renders the confirm disabled",
        "k4.loading",
        first_sub(r"the confirm is not in the DOM", "the confirm rendered disabled", "2.4"),
    ),
    ("K6", "a gated row loses its lock", "k6.lock", frame_sub(13, "`lock`", "glyph")),
    (
        "K6b",
        "a gated row loses CMP-079",
        "k6.lock",
        frame_sub(60, "; CMP-079 as in frame 41", "", every=True),
    ),
    (
        "K6c",
        "a lock on a frame that is not gated",
        "k6.lock",
        frame_sub(
            54,
            "[Cancel] [Disable sub_002] in the validity look",
            "[Cancel] [Disable sub_002] led by the CMP-019 `lock` (CMP-079 RbacGate)"
            " in the validity look",
        ),
    ),
    (
        "K7",
        "a gated row loses its reason key",
        "k7.reason",
        frame_sub(60, "`accounts.never_keyed`", "the reason", every=True),
    ),
    (
        "K8",
        "view-as not first in a reason order",
        "k8.viewas",
        frame_sub(69, "`rbac.view_as`", "`rbac.permission`, then `rbac.view_as`"),
    ),
    (
        "K8b",
        "the row's prose puts the view-as leg late",
        "k8.viewas",
        frame_sub(
            69,
            "view-as leg checked before every other",
            "view-as leg checked after the permission leg",
        ),
    ),
    (
        "K8c",
        "§10.2's Change leverage row loses its view-as leg",
        "t2.viewas",
        first_sub(r"view-as → `rbac\.view_as`; (?=Viewer → `rbac\.permission`)", "", "10.2"),
    ),
    (
        "K9",
        "an exit drawn gated",
        "k9.exit",
        frame_sub(49, "[Cancel]", "[Cancel] in the validity look"),
    ),
    (
        "K9b",
        "an exit's focus line drawn disabled",
        "k9.exit",
        frame_sub(49, "Focus: Cancel;", "Focus: Cancel (disabled);"),
    ),
    (
        "K9c",
        "an exit gated after a comma",
        "k9.exit",
        frame_sub(11, "[Cancel] (initial focus)", "[Cancel] (initial focus), led by the `lock`"),
    ),
    (
        "K9d",
        "a focus line gated after a comma",
        "k9.exit",
        frame_sub(
            49,
            "Focus: Cancel;",
            "Focus: Cancel throughout, `aria-disabled` until the label matches;",
        ),
    ),
    (
        "K10",
        "a CMP-175 state loses its glyph (colour alone)",
        "ac2.glyph",
        variant_edit(is_expiring, "glyph", "—"),
    ),
    ("K11", "the compromise card's steps reordered", "k11.compromise", swap_steps),
    (
        "K12",
        "an environment badge removed from a frame",
        "k12.env",
        frame_sub(49, " · LIVE", "", every=True),
    ),
    (
        "K12b",
        "a titled frame loses its environment badge",
        "k12.env",
        frame_sub(54, "Disable sub_002 · LIVE", "Disable sub_002", every=True),
    ),
    (
        "K12c",
        "the strip frame loses every LIVE",
        "k12.env",
        frame_sub(13, "Attention: LIVE — ", "Attention: ", every=True),
    ),
    (
        "K13",
        "a contrast number not the tool's",
        "k13.number",
        first_sub(r"9\.32(?= <!-- audit:pairs\.c175-critical-border\.dark=)", "9.33"),
    ),
    ("K14", "a frame missing its hi-fi row", "inv.missing", frame_drop(43)),
    (
        "R1",
        "reveal on press, §4.1 block H",
        "reveal",
        sec_sub("4.1", 'as G; label "API secret"', 'as G with reveal on press; label "API secret"'),
    ),
    (
        "R1b",
        "Reveal on press, §5 key fields",
        "reveal",
        sec_sub(
            "5",
            '"New API secret" with CP-1\'s sentence',
            '"New API secret" with CP-1\'s sentence, Reveal on press',
        ),
    ),
    (
        "R2",
        "a reveal button, §4.1 block H",
        "reveal",
        sec_sub("4.1", 'as G; label "API secret"', 'as G with a reveal button; label "API secret"'),
    ),
    (
        "R2b",
        "A Reveal button, §2.5 secret entry",
        "reveal",
        sec_sub("2.5", "no toggle, autocomplete off", "A Reveal button, autocomplete off"),
    ),
    (
        "R3",
        "revealed on hover, §2.5 CMP-034 row",
        "reveal",
        sec_sub("2.5", "text only, `...{last4}`", "text only, `...{last4}`, revealed on hover"),
    ),
    (
        "R3b",
        "Revealed on hover, §6 Key cell",
        "reveal",
        sec_sub(
            "6",
            "CMP-034, the masked id `...{last4}` and nothing more",
            "CMP-034, the masked id `...{last4}`, Revealed on hover",
        ),
    ),
    (
        "R4",
        "`revealed` in §5 masked id title",
        "reveal",
        sec_sub(
            "5",
            "Rotate the key of sub_002 (...e5f6) · LIVE",
            "Rotate the key of sub_002 (...e5f6, `revealed`) · LIVE",
        ),
    ),
    (
        "R5",
        "`revealed` in §6 Key cell",
        "reveal",
        sec_sub(
            "6",
            "the masked id `...{last4}` and nothing more",
            "the masked id `...{last4}` and `revealed`",
        ),
    ),
    (
        "W1",
        "withdraw: on, §8 drawer key row",
        "k3.withdraw",
        sec_sub("8", '"Trade: yes."', '"Trade: yes." "withdraw: on."'),
    ),
    (
        "W1b",
        "Withdraw: ON, §6 Rights row",
        "k3.withdraw",
        sec_sub("6", '"Trade · Withdrawal OFF ✓ · verified 14:02 UTC"', '"Trade · Withdraw: ON"'),
    ),
    (
        "W2",
        "transfer enabled, §8 drawer key row",
        "k3.withdraw",
        sec_sub("8", '"Trade: yes."', '"Trade: yes." "transfer enabled."'),
    ),
    (
        "W2b",
        "Transfer Enabled, §2.5",
        "k3.withdraw",
        sec_sub(
            "2.5",
            "eight served forms; never dismissible",
            "eight served forms, Transfer Enabled; never dismissible",
        ),
    ),
    (
        "W3",
        "a withdrawal switch, §8 drawer key row",
        "k3.withdraw",
        sec_sub("8", '"Trade: yes."', '"Trade: yes." with a withdrawal switch'),
    ),
    (
        "W3b",
        "A Withdrawal Switch, §4.4",
        "k3.withdraw",
        sec_sub(
            "4.4",
            "a row the server fills after a pass",
            "a row the server fills after a pass, A Withdrawal Switch beside it",
        ),
    ),
    (
        "O1",
        "undated OFF, §4.4 block D",
        "k3.off",
        sec_sub("4.4", "OFF ✓ — verified 14:02 UTC", "OFF ✓"),
    ),
    (
        "O1b",
        "undated off (lowercase), §4.4 block D",
        "k3.off",
        sec_sub("4.4", "OFF ✓ — verified 14:02 UTC", "off ✓"),
    ),
    (
        "O2",
        'lowercase "off ✓", frame 36',
        "k3.off",
        sec_sub("5", '"OFF ✓ · verified 10:39 UTC"', '"off ✓"'),
    ),
    (
        "O3",
        "undated OFF, §6 Rights row",
        "k3.off",
        sec_sub(
            "6", '"Trade · Withdrawal OFF ✓ · verified 14:02 UTC"', '"Trade · Withdrawal OFF ✓"'
        ),
    ),
    (
        "O3b",
        "undated off (lowercase), §6 Rights row",
        "k3.off",
        sec_sub(
            "6", '"Trade · Withdrawal OFF ✓ · verified 14:02 UTC"', '"Trade · Withdrawal off ✓"'
        ),
    ),
    (
        "O4",
        'undated "Withdrawal: off.", §8 statement',
        "k3.off",
        sec_sub("8", '"Withdrawal: off — verified 14:02 UTC."', '"Withdrawal: off."'),
    ),
    (
        "O4b",
        'undated "Withdrawal: OFF.", §8 statement',
        "k3.off",
        sec_sub("8", '"Withdrawal: off — verified 14:02 UTC."', '"Withdrawal: OFF."'),
    ),
    (
        "I1",
        "bare 12-character id, §6 Key cell",
        "k1.masked",
        sec_sub(
            "6",
            "the masked id `...{last4}` and nothing more",
            f"the masked id `{BARE_12}` and nothing more",
        ),
    ),
    (
        "I1b",
        "bare 12-hex id, §8 drawer key line",
        "k1.masked",
        sec_sub("8", '"API key {key_id_masked} ·', f'"API key {HEX_12} ·'),
    ),
    (
        "I2",
        "[Show] in §6 Key cell",
        "k2.field",
        sec_sub(
            "6", "the masked id `...{last4}` and nothing more", "the masked id `...{last4}` [Show]"
        ),
    ),
    (
        "I2b",
        "[Show] in §8 drawer key line",
        "k2.field",
        sec_sub("8", '"API key {key_id_masked} ·', '"API key {key_id_masked} [Show] ·'),
    ),
    (
        "R6",
        "`revealed` in Appendix A States New cell",
        "reveal",
        sec_sub("A", "masked — its only state;", "masked — its only state, `revealed`;"),
    ),
    (
        "A1",
        "an allowed phrase copied to a new place",
        "reveal",
        sec_sub("8", '"Trade: yes."', '"Trade: yes." It has no reveal.'),
    ),
    (
        "G7a",
        "frame 69 Hi-fi loses its view-as leg (prose only)",
        "k8.viewas",
        frame_sub(69, "both mode controls T2 `rbac.view_as`, each", "both mode controls T2, each"),
    ),
    ("G7b", "frame 69 view-as leg swapped for the role leg", "k8.viewas", viewas_swapped),
    (
        "K15",
        "an undrawn frame not named 'not drawn'",
        "inv.board",
        frame_sub(76, ROUTE, "not drawn"),
    ),
    (
        "P1",
        "E42-D03's boards PR pinned by a full sha",
        "pin.inflight",
        first_sub(re.escape(BOARDS), BOARDS.replace("`,", f"` at `{HEX_40}`,")),
    ),
    (
        "P2",
        "E42-D03's boards PR pinned by a short sha",
        "pin.inflight",
        first_sub(re.escape(BOARDS), BOARDS.replace("`,", f"` at `{HEX_40[:9]}`,")),
    ),
    (
        "P3",
        "E42-D03's boards PR quoted",
        "pin.inflight",
        first_sub(
            re.escape(BOARDS),
            BOARDS.replace(")", ', whose Appendix A reads "the confirm is pressed on itself")'),
        ),
    ),
)


# r2o: the whole-document gate reads the hand-off too; each of these edits the hand-off in memory
HAND_MUTATIONS: tuple[tuple[str, str, str, str, str], ...] = (
    (
        "H1",
        "hand-off: a reveal on CMP-034",
        "reveal",
        "no reveal, timer or copy state exists",
        "a reveal on press exists",
    ),
    (
        "H2",
        "hand-off: [Copy] on the masked id",
        "k2.field",
        "no reveal, timer or copy exists",
        "its masked id with [Copy]",
    ),
    (
        "H3",
        "hand-off: withdrawal on",
        "k3.withdraw",
        "no reveal, timer or copy exists",
        "Withdrawal: on",
    ),
)


def k_selftest(spec: str, base: dict[str, Any]) -> tuple[bool, list[str]]:
    """Every K mutation on the spec on disk: rc 1 with exactly one distinct FAIL, its own code."""
    before = gates(spec, base)
    if before.fails:
        return False, [f"K list: the spec on disk has {len(before.fails)} FAIL; nothing to mutate"]
    ok, lines = True, []
    for k, name, code, fn in K_MUTATIONS:
        mutated = fn(spec)
        if not mutated or mutated == spec:
            ok = False
            lines.append(f"{k} {name}: n/a (the spec lacks its target)")
            continue
        new = sorted(set(gates(mutated, base).fails) - set(before.fails))
        hit = len(new) == 1 and new[0][0] == code
        ok = ok and hit
        got = "; ".join(f"{c}: {m}" for c, m in new) or "none"
        lines.append(f"{k} {name}: rc {1 if new else 0}, {'ok' if hit else 'WRONG'} — {got}")
    for k, name, code, old, repl in HAND_MUTATIONS:
        if old not in base["handoff"]:
            ok = False
            lines.append(f"{k} {name}: n/a (the hand-off lacks its target)")
            continue
        edited = {**base, "handoff": base["handoff"].replace(old, repl, 1)}
        new = sorted(set(gates(spec, edited).fails) - set(before.fails))
        hit = len(new) == 1 and new[0][0] == code
        ok = ok and hit
        got = "; ".join(f"{c}: {m}" for c, m in new) or "none"
        lines.append(f"{k} {name}: rc {1 if new else 0}, {'ok' if hit else 'WRONG'} — {got}")
    return ok, lines


def run_mutation(fn: Callable[..., str | None], spec: str, base: dict[str, Any]) -> str | None:
    return fn(spec, base) if fn in (line_drop, t2_uncited) else fn(spec)


def refused(got: Out, before: Out, kind: str, code: str) -> bool:
    new_fails = {c for c, _m in set(got.fails) - set(before.fails)}
    new_warns = {c for c, _m in set(got.warns) - set(before.warns)}
    return code in new_fails if kind == "FAIL" else code in new_warns and not new_fails


def selftest(base: dict[str, Any], spec: str) -> tuple[bool, list[str]]:
    """The fixture passes and refuses every mutation; a clean spec on disk refuses its share."""
    lines, fx = [], fixture(base)
    before = gates(fx, base, check_markers=True)
    ok = not before.fails
    lines.append("fixture: pass" if ok else f"fixture: FAIL {before.fails}")
    ok_board = board_drawn(
        "99",
        f"{IMG}/E27-D03-99-x.png",
        f"- `99 x` — board id `{'0' * 8}-0000-"
        f"4000-8000-{'0' * 12}` — `{IMG}/E27-D03-99-x.png` (10 \u00d7 10)",
        lambda _p: True,
    )
    ok = ok and not ok_board
    lines.append(f"a drawn row with its id, PNG and renders: {ok_board or 'accepted'}")
    on_disk = gates(spec, base, check_markers=True) if spec else None
    clean = on_disk is not None and not on_disk.fails
    for name, kind, code, fn in MUTATIONS:
        mutated = run_mutation(fn, fx, base)
        if mutated is None or mutated == fx:
            ok, got = False, "n/a (the fixture lacks its target)"
        else:
            hit = refused(gates(mutated, base, check_markers=True), before, kind, code)
            ok = ok and hit
            got = f"refused ({kind} {code})" if hit else "PASSED (the check is blind)"
        if clean and on_disk is not None:
            real = run_mutation(fn, spec, base)
            if real is None or real == spec:
                got += "; on the spec: n/a"
            else:
                hit = refused(gates(real, base, check_markers=True), on_disk, kind, code)
                ok = ok and hit
                got += "; on the spec: " + ("refused" if hit else "PASSED (the check is blind)")
        lines.append(f"mutation {name}: {got}")
    k_ok, k_lines = k_selftest(spec, base)
    lines += k_lines
    restored = gates(spec, base, check_markers=True)
    same = read(SPEC) == spec
    lines.append(
        f"restore: rc {1 if restored.fails else 0}, the spec on disk "
        f"{'byte-identical' if same else 'CHANGED'} (sha256 {sha256(spec)[:12]})"
    )
    ok = ok and k_ok and same and not restored.fails
    where = (
        "the fixture and the spec on disk" if clean else "the fixture (the spec on disk has FAILs)"
    )
    lines.append(
        f"--self-test: {'ok' if ok else 'FAIL'} — {len(MUTATIONS)} mutations in memory, on "
        f"{where}; "
        f"{len(K_MUTATIONS)} K mutations on the spec and {len(HAND_MUTATIONS)} on the hand-off, "
        "each one FAIL of its own"
    )
    return ok, [mask_vendor(x) for x in lines]


# --- the report ----------------------------------------------------------------------------------
SECTION_CODES = (
    ("2. AC2 carriers (§2.1)", ("ac2", "withdraw", "copy")),
    ("3. Token bindings", ("tokens",)),
    ("4. Inventory and the cap (§0, the hi-fi rows)", ("board", "cap", "inv")),
    ("5. T2 (§10) and the reason keys", ("t2", "key")),
    ("6. Copy deck (§12)", ("deck",)),
    ("7. Appendix A and CMP-034", ("appx", "reveal")),
    (
        "7b. Frame rows (K1, K3-K9, K11-K13)",
        ("k1", "k2", "k3", "k4", "k5", "k6", "k7", "k8", "k9", "k11", "k12", "k13"),
    ),
    (
        "8. Cites and scans",
        ("cite", "scan", "ids", "forbidden", "closing", "placeholder", "handoff", "pin"),
    ),
    ("9. BQ rows and markers", ("bq", "marker")),
)


def report(base: dict[str, Any], out: Out, check: bool) -> list[str]:
    data, n = base["data"], out.n
    lines = ["# E27-D03 hi-fi audit — docs/design/E27/E27-D03.md against the base files", ""]
    lines.append(
        "## 1. Measured matrix (id | fg on bg | role | dark / light / hc | verdict | pairs.mjs "
        "| reproduces)"
    )
    for pid, r in data["pairs"].items():
        vals = " / ".join(show(r[t]) for t in THEMES)
        rep = "" if r["repro"] == "—" else f" | {r['repro']} {'✓' if r.get('reproduced') else '✗'}"
        lines.append(
            f"{pid} | {r['fg']} on {r['bg']} | {r['role']} | {vals} | {r['verdict']} | "
            f"{r['pairs']}{rep}"
        )
    ring = " · ".join(f"{t} {v}" for t, v in data["ring_min"].items())
    lines.append(f"CMP-039 ring minima over {len(RING_TIERS)} tiers: {ring} (E05-D02: {RING_MIN})")
    lines.append(
        f"validity look (composite; reported): label at opacity.disabled "
        f"{data['opacity_disabled']} over the dimmed primary fill: {data['composite']}"
    )
    lines.append(
        f"rows {data['n']['rows']} · gated {data['n']['gated']} (registered "
        f"{data['n']['registered']}, PROPOSED {data['n']['proposed']}) · reported "
        f"{data['n']['reported']} · FAIL {data['n']['fail']} · reproductions {data['n']['repro']}"
        f" (off {data['n']['repro_fail']})"
    )
    lines += [
        "",
        (
            "## 2. CVD (Delta E76: normal / protanopia / deuteranopia / tritanopia; JND 5.0; "
            "reported, never gated) and Rec. 601 luma"
        ),
    ]
    for rid, r in base["cvd"].items():
        per = " | ".join(
            f"{t}: "
            + "/".join(f"{r[t][k]:.1f}" for k in ("normal", *DEFICIENCIES))
            + (f" (under JND: {r[t]['under_jnd']})" if r[t]["under_jnd"] else "")
            for t in THEMES
        )
        lines.append(f"{rid} — {r['what']} | {per}")
    lines.append(
        "luma: "
        + "; ".join(f"{k} {'/'.join(str(v[t]) for t in THEMES)}" for k, v in base["luma"].items())
    )
    lines.append(
        f"CMP-175 rows {n.get('variants', 0)}, own words {n.get('variant_words', 0)}, "
        f"critical {n.get('critical_rows', 0)}"
    )
    lines += [
        "",
        (
            f"## 4. Inventory: E27-D02 frames {n.get('d02_frames')}, hi-fi rows "
            f"{n.get('hifi_rows')}, T2 frames {n.get('t2_frames')}; boards {n.get('boards')} "
            f"(light twins {n.get('light_twins')}), frames on boards {n.get('frames_on_boards')}, "
            f"not drawn {n.get('frames_not_drawn')}"
        ),
    ]
    lines.append(
        f"## 5. T2 rule sentences {n.get('t2_rule')}, gated rows {n.get('gated_rows')}, "
        f"reason keys {n.get('reason_keys')} (E27 {n.get('reason_keys_e27')})"
    )
    lines.append(f"## 6. Deck rows {n.get('deck_rows')} {n.get('deck_by_status')}")
    lines.append(f"## 7. Appendix A rows: `15` {n.get('appendix_15')}, `14` {n.get('appendix_14')}")
    lines.append(
        f"## 8. Cites {n.get('cites')} (with a fragment {n.get('cites_fragment')}); scans "
        f"{n.get('scans')}; placeholders {n.get('placeholders')}"
    )
    lines.append(
        f"## 9. BQ rows {n.get('q_rows')} (RULED {n.get('q_ruled')}); checklist boxes ticked "
        f"{n.get('checklist_ticked')}, open {n.get('checklist_open')}; markers "
        f"{n.get('markers')}{' re-derived' if check else ' (not checked; --check)'}"
    )
    lines += ["", "## Gates by section"]
    for title, prefixes in SECTION_CODES:
        fails = [m for c, m in out.fails if c.split(".")[0] in prefixes]
        warns = [m for c, m in out.warns if c.split(".")[0] in prefixes]
        lines.append(
            f"### {title}: {'OK' if not fails else f'{len(fails)} FAIL'}"
            + (f", {len(warns)} WARN" if warns else "")
        )
        lines += [f"FAIL {m}" for m in fails] + [f"WARN {m}" for m in warns]
    known = {p for _title, prefixes in SECTION_CODES for p in prefixes}
    lines += [f"FAIL {c}: {m}" for c, m in out.fails if c.split(".")[0] not in known]
    lines += ["", f"FAIL {len(out.fails)} · WARN {len(out.warns)}"]
    return lines


def main(argv: list[str]) -> int:
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")
    base, spec = load_base(), read(SPEC)
    if "--selftest" in argv or "--self-test" in argv:
        ok, lines = selftest(base, spec)
        print("\n".join(lines))
        return 0 if ok else 1
    check = "--check" in argv
    out = gates(spec, base, check_markers=check) if spec else Out()
    if not spec:
        out.fail("spec", f"{SPEC.relative_to(ROOT).as_posix()} does not exist")
    if "--json" in argv:
        doc = {
            "numbers": out.n,
            "matrix": base["data"]["pairs"],
            "ring_min": base["data"]["ring_min"],
            "composite": base["data"]["composite"],
            "cvd": base["cvd"],
            "luma": base["luma"],
            "problems": [f"{c}: {m}" for c, m in out.fails],
            "warnings": [f"{c}: {m}" for c, m in out.warns],
        }
        print(json.dumps(doc, ensure_ascii=False, indent=1))
    else:
        print("\n".join(report(base, out, check)))
    return 1 if out.fails else 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
